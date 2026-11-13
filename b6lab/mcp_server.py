"""Local stdio MCP server for the Zoom B6 (docs/superpowers/specs/2026-11-12-b6-mcp-design.md).

A thin layer: it registers the tools and translates arguments and results. Pedal access and its
safety rules live in `pedal_session`, patch specs in `patchspec`, knob units in `knobs`.

Run: `.venv/bin/python -m b6lab.mcp_server` (registered in the project `.mcp.json`).
"""
from __future__ import annotations

import difflib
import re
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Iterator

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from b6lab import draw, effects, patch_search, ptcf
from b6lab.effect_models import load_models
from b6lab.knobs import KnobError, display_value, raw_value
from b6lab.library import list_backups, load_zptc
from b6lab.device import used_bytes
from b6lab.patchspec import (EMPTY_NAME, References, SpecError, build, describe, diff_patches,
                             reference_index)
from b6lab.patchspec import _check_description, _check_name, effect_load
from b6lab.pedal_info import decode_global, decode_identity, effects_overview
from b6lab.pedal_session import SLOTS, PedalError, PedalSession

REPO_ROOT = Path(__file__).resolve().parent.parent
CREATED = Path("downloads/patches/created")
DOWNLOADS = Path("downloads/patches")
FACTORY_SLOTS = 100

INSTRUCTIONS = """\
Tools for a Zoom B6 bass multi-effects pedal connected over USB. Slots are numbered 1-240,
as on the pedal. Knob values are in display units as the pedal shows them (numbers or labels
such as "8 STG"); a knob without known display units takes {"raw": n}.
Safety rules: patches are only installed to Empty slots (named Empty with no effects in the
chain) and the name Empty is refused; rename_patch changes only the name and description of a
non-empty slot (checked byte for byte) and needs its current name; a full backup is made before the first write (install
or clear) of the session and a per-slot backup before every write; every write is logged
in backup/writes.jsonl; clear_slot only undoes this server's own unchanged installs. Only one
program can hold the pedal's MIDI port: if a tool says the port is busy, ask the user to close
B6 Lab. Claude cannot hear the pedal; the user judges the sound.
Tuning: audition_patch plays a patch from a scratch Empty slot; set_knob and set_effect_on
change only what the pedal plays now (nothing is stored) and name the effect they expect at
the chain entry; all three are refused while the pedal's AUTO SAVE is on. Keep the result with
save_edit (to an Empty slot), drop it with revert_edit; pedal_status shows what changed.
Results with a "drawing" (or draw_patch's "text") are a text pedalboard: show it to the user
verbatim in a code block."""

SLOT_TEXT = "Slot number 1-240, as shown on the pedal."

SPEC_TEXT = """\
A patch spec: {"name": up to 10 printable ASCII characters, "description": optional text
(warned above 161, refused above 191 characters), "level": 0-120 (default 80), "footswitches":
optional list of up to 4 chain-entry indices, "effects": [{"effect": effect name, "on": true or
false (default true), "knobs": {knob name: display value}}, ...]}. No other keys are allowed.
{"effect": null} is an empty chain entry. The chain holds at most 6 entries; a double-width
effect (amps and some others) takes two. Footswitch numbers are chain-entry indices starting
at 0 that count the hidden second entry of every double-width effect; they are not positions
in the listed effects. Example: with effects [160 Comp, FlipTop (double-width), Phaser] the
entries are 0 160 Comp, 1 FlipTop, 2 FlipTop's hidden half, 3 Phaser, so Phaser is entry 3.
Results of get_patch, validate_patch and build_patch give each listed effect its chain-entry
index as "entry" (the number footswitches use); "entry" is ignored when a spec is built.
Use effect_info for knob names and values."""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                              open_world_hint=False)
BACKUP = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
FILE_WRITE = BACKUP  # writes a local file, never the pedal (build_patch)
# changes what the pedal plays, never stored (audition writes only its scratch Empty slot)
LIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                       open_world_hint=False)
# audition_patch / revert_edit: install to / clear the scratch Empty slot (v1 write path)
AUDITION = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False,
                           open_world_hint=False)
MISSING_EFFECTS = ("B6 Lab data files missing: pedal-files/effects.json; "
                   "see README Data files")

Slot = Annotated[int, Field(description=SLOT_TEXT)]
Spec = Annotated[dict[str, Any], Field(description=SPEC_TEXT)]


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Expected failures reach the client as tool errors with their message."""
    try:
        yield
    except ToolError:
        raise
    except (PedalError, SpecError, KnobError, ValueError, OSError) as e:
        raise ToolError(str(e)) from e


def _parses(data: bytes) -> bool:
    try:
        ptcf.parse(data)
    except Exception:
        return False
    return True


def default_references(root: Path) -> References:
    """Reference entries from the newest full backup (slots 1-100 first, then 101-240), then
    from downloads/patches/*/*.zptc, leaving out downloads/patches/created/ (the server's own
    builds never become references)."""
    root = Path(root)
    patches: list[bytes] = []
    sets = list_backups(root / "backup")
    if sets:
        slots = sets[-1].slots[:SLOTS]
        patches += slots[:FACTORY_SLOTS] + slots[FACTORY_SLOTS:]
    downloads = root / DOWNLOADS
    created = (root / CREATED).resolve()
    if downloads.is_dir():
        for f in sorted(downloads.glob("*/*.zptc")):
            if f.parent.resolve() == created:
                continue
            try:
                patches.append(f.read_bytes())
            except OSError:
                continue
    return reference_index(p for p in patches if _parses(p))


def _newest_backup_key(backup_root: Path) -> tuple | None:
    """Name and index.json mtime of the newest full backup folder (cheap: no patch reads)."""
    try:
        dirs = sorted(d for d in Path(backup_root).iterdir() if (d / "index.json").is_file())
        if not dirs:
            return None
        return dirs[-1].name, (dirs[-1] / "index.json").stat().st_mtime_ns
    except OSError:
        return None


def safe_file_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._-")
    return stem or "patch"


def _unique_path(folder: Path, stem: str) -> Path:
    path = folder / f"{stem}.zptc"
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{stem}-{n}.zptc"
    return path


def _dsp_percent(fx_id: int) -> float | None:
    load = effects.dsp_load(fx_id)
    return None if load is None else round(load / 2.2, 1)


def _knob(param) -> dict:
    out: dict[str, Any] = {"name": param.name, "explanation": param.explanation}
    if param.display_labels is not None:
        out["labels"] = list(param.display_labels)
    elif param.display_min is not None and param.display_step is not None:
        step = Decimal(param.display_step)
        out["range"] = {
            "min": display_value(param, 0),
            "max": display_value(param, param.raw_max) if param.raw_max is not None else None,
            "step": float(step) if param.display_precision else int(step),
        }
    else:
        out["raw"] = {"max": param.raw_max}
    if param.pedal:
        out["pedal"] = True
    return out


class _Server:
    """The tool implementations; build_server registers them."""

    def __init__(self, session: PedalSession, catalog, refs, models):
        self.session = session
        self._catalog = catalog
        self._refs = refs
        self._refs_injected = refs is not None
        self._refs_key = None
        self._models = models

    # --- lazy data ---------------------------------------------------------------------------

    @property
    def catalog(self) -> dict:
        if self._catalog is None:
            if not effects.DEFAULT_PATH.is_file():
                raise ToolError(MISSING_EFFECTS)
            self._catalog = effects.load(effects.DEFAULT_PATH)
        return self._catalog

    def effect_name(self, fx_id: int) -> str:
        """Catalog name for pedal_session messages; the hex id without a catalog."""
        try:
            info = self.catalog.get(fx_id)
        except ToolError:
            info = None
        return info.name if info is not None else f"0x{fx_id:08X}"

    @property
    def refs(self) -> References:
        """Injected refs as given; default refs are rebuilt when the newest backup changes
        (e.g. the first full backup, made by backup_pedal, list_patches or install_patch)."""
        if self._refs_injected:
            return self._refs
        key = _newest_backup_key(self.session.backup_root)
        if self._refs is None or key != self._refs_key:
            self._refs = default_references(self.session.root)
            self._refs_key = key
        return self._refs

    @property
    def models(self) -> dict:
        if self._models is None:
            self._models = load_models()
        return self._models

    # --- helpers -----------------------------------------------------------------------------

    def _find(self, name: str):
        wanted = name.strip().lower()
        for fx_id, info in self.catalog.items():
            if info.name.lower() == wanted:
                return fx_id, info
        names = {info.name.lower(): info.name for info in self.catalog.values()}
        close = difflib.get_close_matches(wanted, list(names), n=3, cutoff=0.6)
        hint = f"; did you mean {' or '.join(names[c] for c in close)}?" if close else ""
        raise ToolError(f"unknown effect {name!r}{hint}")

    def _duplicates(self, name: str, pedal: bool) -> list[str]:
        """Decision 17: a name already on the pedal is a warning, never a refusal. Without
        `pedal` the check only uses an existing backup (no pedal access)."""
        if not pedal and not list_backups(self.session.backup_root):
            return []
        try:
            patches = self.session.list_patches()["patches"]
        except PedalError as e:
            return [f"duplicate names not checked: {e}"]
        slots = [str(p["slot"]) for p in patches if p["name"].strip() == name.strip()]
        if not slots:
            return []
        return [f"name '{name.strip()}' already used in slot(s) {', '.join(slots)}"]

    def _build(self, spec: dict) -> tuple[bytes, list[str]]:
        return build(spec, self.refs, self.catalog)

    def _save(self, data: bytes, name: str) -> Path:
        folder = self.session.root / CREATED
        folder.mkdir(parents=True, exist_ok=True)
        path = _unique_path(folder, safe_file_name(name))
        path.write_bytes(data)
        return path

    def _file(self, file: str) -> Path:
        path = Path(file).expanduser()
        return path if path.is_absolute() else self.session.root / path

    def _source(self, tool: str, file: str | None, spec: dict | None):
        """A patch from exactly one of a .zptc file or a spec (built and saved to created/)."""
        if (file is None) == (spec is None):
            raise ToolError(f"{tool} needs exactly one of 'file' (a .zptc path) or "
                            "'spec' (a patch spec)")
        if spec is not None:
            data, warnings = self._build(spec)
            return data, warnings, self._save(data, ptcf.parse(data).name)
        path = self._file(file)
        return load_zptc(path), [], path

    def _drawing(self, data: bytes, slot: int | None = None) -> str:
        return draw.render(describe(data, self.catalog), slot=slot,
                           entries=len(ptcf.parse(data).effects))

    def _knob(self, info, knob: str):
        wanted = knob.strip().lower()
        for i, param in enumerate(info.params):
            if param.name.lower() == wanted:
                return i, param
        raise ToolError(f"{info.name} has no knob {knob!r}; its knobs: "
                        f"{', '.join(p.name for p in info.params)}")

    def _live_result(self, edit: bytes) -> dict:
        st = self.session.status()
        changes = diff_patches(describe(st["stored"], self.catalog), describe(edit, self.catalog))
        return {"slot": st["slot"], "patch": describe(edit, self.catalog), "changes": changes}

    # --- tools -------------------------------------------------------------------------------

    def list_patches(self, refresh: bool) -> dict:
        with _tool_errors():
            out = self.session.list_patches(refresh)
        empty = sum(1 for p in out["patches"] if p["empty"])
        out["summary"] = (f"{len(out['patches']) - empty} patches and {empty} Empty slots, "
                          f"from a backup {out['age_minutes']} min old")
        return out

    def get_patch(self, slot: int) -> dict:
        with _tool_errors():
            data = self.session.read_slot(slot)
            return {"slot": slot, **describe(data, self.catalog, slot=slot),
                    "drawing": self._drawing(data, slot)}

    def current_patch(self) -> dict:
        with _tool_errors():
            slot = self.session.current_slot()
            data = self.session.read_slot(slot)
            return {"slot": slot, **describe(data, self.catalog, slot=slot),
                    "drawing": self._drawing(data, slot)}

    def draw_patch(self, slot: int | None, file: str | None, spec: dict | None,
                   current: bool) -> dict:
        if sum(x is not None for x in (slot, file, spec)) + bool(current) != 1:
            raise ToolError("draw_patch needs exactly one of slot, file, spec or current=true")
        with _tool_errors():
            if slot is not None:
                data = self.session.read_slot(slot)
            elif current:
                data = self.session.read_edit()
                slot = self.session.current_slot()
            elif file is not None:
                data = load_zptc(self._file(file))
            else:
                data, _ = self._build(spec)
            text = self._drawing(data, slot)
        return {"text": text, "summary": describe(data, self.catalog, slot=slot)["summary"]}

    def list_effects(self, group: str | None) -> dict:
        with _tool_errors():
            return self._list_effects(group)

    def _list_effects(self, group: str | None) -> dict:
        groups = sorted({info.group for info in self.catalog.values()})
        if group is not None and group.strip().upper() not in groups:
            raise ToolError(f"unknown group {group!r}; groups: {', '.join(groups)}")
        rows = []
        for fx_id, info in sorted(self.catalog.items(), key=lambda kv: (kv[1].group, kv[1].name)):
            if group is not None and info.group != group.strip().upper():
                continue
            rows.append({"name": info.name, "group": info.group,
                         "dsp_percent": _dsp_percent(fx_id), "buildable": fx_id in self.refs})
        where = f" in {group.strip().upper()}" if group is not None else ""
        buildable = sum(1 for r in rows if r["buildable"])
        return {"effects": rows, "groups": groups,
                "summary": f"{len(rows)} effects{where}, {buildable} usable in build_patch"}

    def effect_info(self, name: str) -> dict:
        with _tool_errors():
            return self._effect_info(name)

    def _effect_info(self, name: str) -> dict:
        fx_id, info = self._find(name)
        knobs = [_knob(p) for p in info.params[:len(ptcf.PARAM_WIDTHS)]]
        model = self.models.get(info.name)
        percent = _dsp_percent(fx_id)
        buildable = fx_id in self.refs
        gear = (f", model: {model['gear']} ({model.get('basis', '?')})"
                if model and model.get("gear") else "")
        dsp = f"{percent} % DSP" if percent is not None else "DSP load unknown"
        summary = (f"{info.name} ({info.group}{gear}): {len(knobs)} knobs, {dsp}"
                   + ("" if buildable else ", not usable in build_patch (no reference entry)"))
        return {"name": info.name, "group": info.group, "description": info.description,
                "dsp_percent": percent, "buildable": buildable, "knobs": knobs, "model": model,
                "summary": summary}

    def validate_patch(self, spec: dict) -> dict:
        with _tool_errors():
            data, warnings = self._build(spec)
            patch = describe(data, self.catalog)
        note = f", {len(warnings)} warning(s)" if warnings else ""
        return {"valid": True, "warnings": warnings, "patch": patch,
                "summary": f"Valid: {patch['summary']}{note}"}

    def build_patch(self, spec: dict) -> dict:
        with _tool_errors():
            data, warnings = self._build(spec)
            patch = describe(data, self.catalog)
            warnings += self._duplicates(patch["name"], pedal=False)
            path = self._save(data, patch["name"])
        note = f", {len(warnings)} warning(s)" if warnings else ""
        return {"file": str(path), "warnings": warnings, "patch": patch,
                "summary": f"Built {patch['summary']}; saved to {path}{note}"}

    def install_patch(self, slot: int, file: str | None, spec: dict | None,
                      select: bool) -> dict:
        with _tool_errors():
            data, warnings, path = self._source("install_patch", file, spec)
            patch = describe(data, self.catalog, slot=slot)
            warnings += self._duplicates(patch["name"], pedal=True)
            out = self.session.install(data, slot, select)
        selected = ", selected on the pedal" if select else ""
        note = f", {len(warnings)} warning(s)" if warnings else ""
        return {**out, "file": str(path), "warnings": warnings, "patch": patch,
                "summary": f"Installed {patch['name']!r} in slot {slot}{selected}{note}"}

    def clear_slot(self, slot: int) -> dict:
        with _tool_errors():
            out = self.session.clear(slot)
        return {**out, "summary": f"Slot {slot} is Empty again (removed {out['removed']!r})"}

    def pedal_info(self) -> dict:
        with _tool_errors():
            raw = self.session.info()
        out: dict = {}

        def field(key, fn):
            try:
                out[key] = fn()
            except Exception as e:  # noqa: BLE001 - one field failing never fails the call
                out[key] = {"error": f"{type(e).__name__}: {e}"}

        def need(value):
            if isinstance(value, dict) and "error" in value:
                raise ValueError(value["error"])
            return value

        ident = raw["identity"]
        field("model", lambda: decode_identity(need(ident))["model"])
        field("firmware", lambda: decode_identity(need(ident))["firmware"])
        field("identity_raw", lambda: need(ident).hex(" "))
        field("patch_slots", lambda: {k: v for k, v in need(raw["patch_info"]).items()
                                      if k != "raw"})
        field("selected", lambda: {"slot": need(raw["selected_slot"]),
                                   **{k: v for k, v in describe(need(raw["selected_patch"]),
                                                                self.catalog).items()
                                      if k in ("name", "description")}})
        field("edited", lambda: bool(diff_patches(describe(need(raw["selected_patch"]),
                                                          self.catalog),
                                                 describe(need(raw["edit"]), self.catalog))))
        g = raw["global"]
        field("auto_save", lambda: decode_global(need(g))["auto_save"])
        field("tempo", lambda: decode_global(need(g))["tempo"])
        field("tuner_hz", lambda: decode_global(need(g))["tuner_hz"])
        field("global_params", lambda: decode_global(need(g))["params"])
        field("global_raw", lambda: decode_global(need(g))["raw"])
        field("memory_used_percent", lambda: round(need(raw["memory_used"]) * 100))
        field("effects", lambda: effects_overview(need(raw["effect_list"]), self.catalog))
        field("visible_chain_width", lambda: need(raw["product_info"])["visible_width"])
        field("support_patch_flags", lambda: {
            "flags": need(raw["patch_capabilities"])["flags"],
            "raw": bytes(need(raw["patch_capabilities"])["raw"]).hex(" "),
            "status": "meaning unknown"})

        def patch_memory():
            listing = self.session.list_patches(False)
            pts = listing["patches"]
            empty = sum(1 for p in pts if p["empty"])
            named = [p["slot"] for p in pts if p["name"].strip() == EMPTY_NAME and not p["empty"]]
            return {"in_use": len(pts) - empty, "empty": empty,
                    "named_empty_not_empty": named, "backup": listing["source"],
                    "backup_age_minutes": listing["age_minutes"]}
        field("patch_memory", patch_memory)

        def part(key, fmt):
            v = out.get(key)
            return fmt(v) if v is not None and not (isinstance(v, dict) and "error" in v) else None
        bits = [part("model", lambda v: f"{v} firmware {out.get('firmware')}"),
                part("selected", lambda v: f"slot {v['slot']} {v.get('name', '')}".strip()),
                part("auto_save", lambda v: f"AUTO SAVE {'on' if v else 'off'}"),
                part("memory_used_percent", lambda v: f"effect memory {v} %"),
                part("effects", lambda v: f"{v['installed']} effects installed")]
        failed = [k for k, v in out.items() if isinstance(v, dict) and "error" in v]
        summary = ", ".join(b for b in bits if b)
        if failed:
            summary += f" (could not read: {', '.join(failed)})"
        out["summary"] = summary or "nothing could be read from the pedal"
        return out

    def pedal_status(self) -> dict:
        with _tool_errors():
            st = self.session.status()
            stored = describe(st["stored"], self.catalog)
            edit = describe(st["edit"], self.catalog)
        changes = diff_patches(stored, edit)
        auto = {True: "on", False: "off", None: "unknown"}[st["auto_save"]]
        extra = (f", auditioning from scratch slot {st['scratch']} (revert_edit returns to slot "
                 f"{st['audition_from']})" if st["scratch"] else "")
        what = f"{len(changes)} unsaved change(s)" if changes else "no unsaved changes"
        return {"slot": st["slot"], "stored_name": stored["name"], "auto_save": st["auto_save"],
                "edited": bool(changes), "changes": changes, "scratch_slot": st["scratch"],
                "audition_from": st["audition_from"], "patch": edit,
                "drawing": self._drawing(st["edit"], st["slot"]),
                "summary": f"Slot {st['slot']} {stored['name']}: {what}, AUTO SAVE {auto}{extra}"}

    def audition_patch(self, file: str | None, spec: dict | None) -> dict:
        with _tool_errors():
            data, warnings, path = self._source("audition_patch", file, spec)
            out = self.session.audition(data)
            patch = describe(out["edit"], self.catalog)
        return {"slot": out["slot"], "audition_from": out["audition_from"], "file": str(path),
                "warnings": warnings, "patch": patch, "full_backup": out["full_backup"],
                "summary": f"Auditioning {patch['name']!r} from scratch slot {out['slot']}; "
                           f"revert_edit returns to slot {out['audition_from']}"}

    def set_knob(self, entry: int, effect: str, knob: str, value: Any) -> dict:
        fx_id, info = self._find(effect)
        index, param = self._knob(info, knob)
        with _tool_errors():
            raw = raw_value(param, value)
            out = self._live_result(self.session.set_param(entry, fx_id, index, raw))
        shown = display_value(param, raw)
        return {**out, "summary": f"{info.name} (entry {entry}) {param.name} = {shown}; "
                                  f"{len(out['changes'])} unsaved change(s)"}

    def set_effect_on(self, entry: int, effect: str, on: bool) -> dict:
        fx_id, info = self._find(effect)
        with _tool_errors():
            out = self._live_result(self.session.set_effect_on(entry, fx_id, on))
        return {**out, "summary": f"{info.name} (entry {entry}) {'on' if on else 'off'}; "
                                  f"{len(out['changes'])} unsaved change(s)"}

    def _chain_result(self, edit: bytes, summary: str) -> dict:
        out = self._live_result(edit)
        return {**out, "drawing": self._drawing(edit, out["slot"]),
                "summary": f"{summary}; {len(out['changes'])} unsaved change(s)"}

    def add_effect(self, entry: int, effect: str, expect_at: str | None) -> dict:
        fx_id, info = self._find(effect)
        expect = self._find(expect_at)[0] if expect_at else None
        ref = self.refs.get(fx_id)
        wide = ref is not None and ref[1] is not None
        with _tool_errors():
            edit = self.session.add_effect(entry, fx_id, expect, wide, effect_load(fx_id))
        return self._chain_result(edit, f"Added {info.name} at entry {entry}")

    def remove_effect(self, entry: int, effect: str) -> dict:
        fx_id, info = self._find(effect)
        with _tool_errors():
            edit = self.session.remove_effect(entry, fx_id)
        return self._chain_result(edit, f"Removed {info.name} from entry {entry}")

    def move_effect(self, entry: int, effect: str, to: int) -> dict:
        fx_id, info = self._find(effect)
        with _tool_errors():
            edit = self.session.move_effect(entry, fx_id, to)
        return self._chain_result(edit, f"Moved {info.name} from entry {entry} to {to}")

    def change_effect(self, entry: int, effect: str, to_effect: str) -> dict:
        fx_id, info = self._find(effect)
        to_fx, to_info = self._find(to_effect)
        with _tool_errors():
            ref = self.refs.get(to_fx)
            edit = self.session.change_effect(entry, fx_id, to_fx,
                                              ref is not None and ref[1] is not None)
        return self._chain_result(edit, f"Entry {entry}: {info.name} -> {to_info.name}")

    def revert_edit(self) -> dict:
        with _tool_errors():
            slot, edit = self.session.revert()
            patch = describe(edit, self.catalog)
        return {"slot": slot, "patch": patch,
                "summary": f"Slot {slot} {patch['name']}: playing the stored patch again"}

    def save_edit(self, slot: int, name: str | None, description: str | None) -> dict:
        with _tool_errors():
            p = ptcf.parse(used_bytes(self.session.read_edit()))
            warnings: list[str] = []
            if name is not None:
                ptcf.set_name(p, _check_name(name))
            elif p.name.strip() == EMPTY_NAME:
                raise ToolError("the patch the pedal plays is named Empty; give save_edit a "
                                "name")
            if description is not None:
                ptcf.set_comment(p, _check_description(description, warnings))
            data = ptcf.encode(p)
            path = self._save(data, p.name)
            patch = describe(data, self.catalog, slot=slot)
            warnings += self._duplicates(patch["name"], pedal=True)
            out = self.session.install(data, slot, False)
        note = f", {len(warnings)} warning(s)" if warnings else ""
        return {**out, "file": str(path), "warnings": warnings, "patch": patch,
                "summary": f"Saved what the pedal plays as {patch['name']!r} in slot {slot}"
                           f"{note}"}

    def rename_patch(self, slot: int, expect_name: str, name: str | None,
                     description: str | None) -> dict:
        if name is None and description is None:
            raise ToolError("rename_patch needs a new name or description")
        with _tool_errors():
            warnings: list[str] = []
            if name is not None:
                _check_name(name)
            if description is not None:
                _check_description(description, warnings)
            out = self.session.rename(slot, expect_name, name, description)
            data = self.session.read_slot(slot)
            patch = describe(data, self.catalog, slot=slot)
        what = " and ".join(w for w, v in (("name", name), ("description", description))
                            if v is not None)
        return {**out, "warnings": warnings, "patch": patch,
                "drawing": self._drawing(data, slot),
                "summary": f"Slot {slot}: {what} changed ({out['old_name']!r} -> "
                           f"{out['name']!r})"}

    def search_patches(self, query: str, sources: list[str] | None) -> dict:
        wanted = set(sources or patch_search.SOURCES)
        unknown = wanted - set(patch_search.SOURCES)
        if unknown:
            raise ToolError(f"unknown source(s) {sorted(unknown)}; use "
                            f"{', '.join(patch_search.SOURCES)}")
        with _tool_errors():
            entries = patch_search.collect(self.session.pedal_patches(),
                                           self.session.backup_root,
                                           self.session.root / DOWNLOADS, wanted)
            hits = patch_search.search(entries, query, lambda d: describe(d, self.catalog),
                                       self.models)
        q = query.strip()
        summary = (f"{len(hits)} hit(s) for {q!r}" if hits else f"no patches match {q!r}")
        return {"query": q, "sources": sorted(wanted), "hits": hits, "summary": summary}

    def _patch_of(self, ref) -> tuple[bytes, int | None]:
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
            slot = int(ref)
            return self.session.read_slot(slot), slot
        if isinstance(ref, str) and ref.strip().lower() == "current":
            return self.session.read_edit(), self.session.current_slot()
        return load_zptc(self._file(str(ref))), None

    def compare_patches(self, a, b) -> dict:
        with _tool_errors():
            da, sa = self._patch_of(a)
            db, sb = self._patch_of(b)
            pa, pb = describe(da, self.catalog), describe(db, self.catalog)
            changes = diff_patches(pa, pb)
        what = f"{len(changes)} difference(s)" if changes else "identical in name, level and chain"
        return {"a": a, "b": b, "changes": changes, "drawing_a": self._drawing(da, sa),
                "drawing_b": self._drawing(db, sb),
                "summary": f"{pa['name'].strip()} vs {pb['name'].strip()}: {what}"}

    def backup_pedal(self) -> dict:
        with _tool_errors():
            path = self.session.backup()
        return {"backup": path, "summary": f"Full backup of all {SLOTS} slots saved to {path}"}


def build_server(session: PedalSession, catalog: dict | None = None,
                 refs: References | None = None, models: dict | None = None) -> MCPServer:
    """MCP server with the B6 tools. `catalog`, `refs` and `models` default to the effect
    catalog, `default_references(session.root)` and the effect models, loaded on first use."""
    impl = _Server(session, catalog, refs, models)
    session.effect_name = impl.effect_name  # effect names in refusals, from the same catalog
    server = MCPServer(name="zoom-b6", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "List all 240 patch slots (1-240) with name and description. Answers from the newest "
        "full backup and reports its age; refresh=true re-reads the whole pedal first (about "
        "a minute)."))
    def list_patches(refresh: bool = False) -> dict[str, Any]:
        return impl.list_patches(refresh)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Read one patch from the pedal (slot 1-240): name, description, level, effects with "
        "knobs in display units and their chain-entry index \"entry\" (double-width effects "
        "count twice; the numbers footswitches use), DSP percent and footswitch entries."))
    def get_patch(slot: Slot) -> dict[str, Any]:
        return impl.get_patch(slot)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "The patch the pedal has selected now (its slot 1-240 and contents, as get_patch)."))
    def current_patch() -> dict[str, Any]:
        return impl.current_patch()

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "List the effects of the B6 catalog with group, DSP percent and whether build_patch "
        "can use them. Optional group filter, e.g. DRIVE, BASS AMP, REVERB."))
    def list_effects(group: Annotated[str | None, Field(description="Effect group")] = None
                     ) -> dict[str, Any]:
        return impl.list_effects(group)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Details of one effect by name: group, description, DSP percent, the real gear it is "
        "modelled on, and its knobs (name, labels or display range, explanation)."))
    def effect_info(name: Annotated[str, Field(description="Effect name, e.g. Phaser")]
                    ) -> dict[str, Any]:
        return impl.effect_info(name)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Check a patch spec without saving or touching the pedal; returns the patch as it "
        "would be built and any warnings. " + SPEC_TEXT))
    def validate_patch(spec: Spec) -> dict[str, Any]:
        return impl.validate_patch(spec)

    @server.tool(annotations=FILE_WRITE, structured_output=True, description=(
        "Build a .zptc patch file from a spec; saved to downloads/patches/created/<name>.zptc "
        "(never overwrites: -2, -3 ...). Does not touch the pedal. Returns the file path, the "
        "patch and warnings (e.g. a name already used on the pedal). " + SPEC_TEXT))
    def build_patch(spec: Spec) -> dict[str, Any]:
        return impl.build_patch(spec)

    @server.tool(annotations=DESTRUCTIVE, structured_output=True, description=(
        "Write a patch to an Empty slot (1-240) of the pedal; any other slot is refused. Give "
        "exactly one of file (a .zptc path, relative to the repository or absolute) or spec "
        "(built first and saved to downloads/patches/created/). Backs up the slot first (and "
        "the whole pedal before the first write of the session) and logs the write. The pedal "
        "switches to the slot only with select=true. " + SPEC_TEXT))
    def install_patch(slot: Slot,
                      file: Annotated[str | None, Field(description=".zptc file")] = None,
                      spec: Annotated[dict[str, Any] | None, Field(description="Patch spec")]
                      = None,
                      select: bool = False) -> dict[str, Any]:
        return impl.install_patch(slot, file, spec, select)

    @server.tool(annotations=DESTRUCTIVE, structured_output=True, description=(
        "Undo an install_patch: make the slot (1-240) Empty again. Only for slots this server "
        "installed that still hold exactly what it wrote; the user's own patches are never "
        "touched."))
    def clear_slot(slot: Slot) -> dict[str, Any]:
        return impl.clear_slot(slot)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Everything the pedal reports about itself: model and firmware, patch slots, the "
        "selected patch and whether it has unsaved edits, tempo, tuner calibration, AUTO SAVE, "
        "the other global settings (raw, names from the decompile), effect memory used, "
        "installed effects with versions, chain width, Support Patch flags (raw), and a patch "
        "memory overview from the newest backup. A field that cannot be read shows its error."))
    def pedal_info() -> dict[str, Any]:
        return impl.pedal_info()

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Draw a patch as a text pedalboard (boxes per effect, on/off, knobs in display units, "
        "footswitch marks): give exactly one of slot (read from the pedal), file (.zptc), spec, "
        "or current=true (what the pedal plays now). Show the text verbatim in a code block."))
    def draw_patch(slot: Annotated[int | None, Field(description=SLOT_TEXT)] = None,
                   file: Annotated[str | None, Field(description=".zptc file")] = None,
                   spec: Annotated[dict[str, Any] | None, Field(description="Patch spec")] = None,
                   current: bool = False) -> dict[str, Any]:
        return impl.draw_patch(slot, file, spec, current)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "What the pedal plays now: its slot, AUTO SAVE, whether the patch has unsaved changes "
        "(and which, in display units, against the stored slot), and a running audition."))
    def pedal_status() -> dict[str, Any]:
        return impl.pedal_status()

    @server.tool(annotations=AUDITION, structured_output=True, description=(
        "Play a patch on the pedal to try it: give exactly one of file (.zptc) or spec. It is "
        "installed to a scratch Empty slot (the highest free one; a new audition replaces it) "
        "and selected; revert_edit goes back and empties the scratch slot, save_edit keeps it "
        "in a slot of your choice. Refused while AUTO SAVE is on. " + SPEC_TEXT))
    def audition_patch(file: Annotated[str | None, Field(description=".zptc file")] = None,
                       spec: Annotated[dict[str, Any] | None, Field(description="Patch spec")]
                       = None) -> dict[str, Any]:
        return impl.audition_patch(file, spec)

    @server.tool(annotations=LIVE, structured_output=True, description=(
        "Turn one knob of the patch the pedal plays now; nothing is stored. Name the effect "
        "expected at the chain entry (refused if it is not there, e.g. after a footswitch "
        "press). Value in display units as effect_info shows them, or {\"raw\": n}. The pedal "
        "is read back. Refused while AUTO SAVE is on."))
    def set_knob(entry: Annotated[int, Field(description="Chain-entry index, as get_patch "
                                                         "shows it")],
                 effect: Annotated[str, Field(description="Effect expected there, e.g. Phaser")],
                 knob: Annotated[str, Field(description="Knob name, e.g. Rate")],
                 value: Annotated[Any, Field(description="Display value or {\"raw\": n}")]
                 ) -> dict[str, Any]:
        return impl.set_knob(entry, effect, knob, value)

    @server.tool(annotations=LIVE, structured_output=True, description=(
        "Switch one effect of the patch the pedal plays now on or off; nothing is stored. "
        "Name the effect expected at the chain entry. Read back. Refused while AUTO SAVE is "
        "on."))
    def set_effect_on(entry: Annotated[int, Field(description="Chain-entry index")],
                      effect: Annotated[str, Field(description="Effect expected there")],
                      on: bool) -> dict[str, Any]:
        return impl.set_effect_on(entry, effect, on)

    @server.tool(annotations=LIVE, structured_output=True, description=(
        "Add an effect to the patch the pedal plays now, at chain entry `entry`; nothing is "
        "stored. expect_at names the effect now at that entry (the new one goes in front of "
        "it); leave it out to append at the end. Refused on a full chain or over the DSP "
        "budget; the pedal sets the new effect's knobs; read back. Refused while AUTO SAVE is "
        "on."))
    def add_effect(entry: Annotated[int, Field(description="Chain-entry index")],
                   effect: Annotated[str, Field(description="Effect to add, e.g. Hall")],
                   expect_at: Annotated[str | None, Field(description="Effect now at entry")]
                   = None) -> dict[str, Any]:
        return impl.add_effect(entry, effect, expect_at)

    @server.tool(annotations=LIVE, structured_output=True, description=(
        "Remove the effect at chain entry `entry` (named, as a guard) from the patch the pedal "
        "plays now; nothing is stored; read back. Refused while AUTO SAVE is on."))
    def remove_effect(entry: Annotated[int, Field(description="Chain-entry index")],
                      effect: Annotated[str, Field(description="Effect expected there")]
                      ) -> dict[str, Any]:
        return impl.remove_effect(entry, effect)

    @server.tool(annotations=LIVE, structured_output=True, description=(
        "Move the effect at chain entry `entry` (named, as a guard) to entry `to` (its index "
        "once taken out of the chain) in the patch the pedal plays now; nothing is stored; "
        "read back. Refused while AUTO SAVE is on."))
    def move_effect(entry: Annotated[int, Field(description="Chain-entry index")],
                    effect: Annotated[str, Field(description="Effect expected there")],
                    to: Annotated[int, Field(description="New chain-entry index")]
                    ) -> dict[str, Any]:
        return impl.move_effect(entry, effect, to)

    @server.tool(annotations=LIVE, structured_output=True, description=(
        "Change the effect at chain entry `entry` (named, as a guard) into another effect type "
        "in the patch the pedal plays now; the pedal sets the knobs; nothing is stored; read "
        "back. Refused while AUTO SAVE is on."))
    def change_effect(entry: Annotated[int, Field(description="Chain-entry index")],
                      effect: Annotated[str, Field(description="Effect expected there")],
                      to_effect: Annotated[str, Field(description="New effect type")]
                      ) -> dict[str, Any]:
        return impl.change_effect(entry, effect, to_effect)

    @server.tool(annotations=AUDITION, structured_output=True, description=(
        "Drop unsaved changes: the pedal plays the stored patch again. After an audition it "
        "returns to the slot selected before and empties the scratch slot."))
    def revert_edit() -> dict[str, Any]:
        return impl.revert_edit()

    @server.tool(annotations=DESTRUCTIVE, structured_output=True, description=(
        "Store what the pedal plays now (with its unsaved changes) to an Empty slot (1-240), "
        "with v1's install rules (backups, log, Empty slots only); optional new name and "
        "description. The pedal keeps playing what it played."))
    def save_edit(slot: Slot,
                  name: Annotated[str | None, Field(description="New patch name")] = None,
                  description: Annotated[str | None, Field(description="New description")]
                  = None) -> dict[str, Any]:
        return impl.save_edit(slot, name, description)

    @server.tool(annotations=DESTRUCTIVE, structured_output=True, description=(
        "Give a patch on the pedal (any non-empty slot 1-240, factory patches included) a new "
        "name and/or description; nothing else changes (checked byte for byte). expect_name is "
        "the slot's current name (guards against a wrong slot). Refused while that slot plays "
        "with unsaved changes. Backed up, logged and read back like install_patch."))
    def rename_patch(slot: Slot,
                     expect_name: Annotated[str, Field(description="The slot's current name")],
                     name: Annotated[str | None, Field(description="New name, 1-10 ASCII")] = None,
                     description: Annotated[str | None, Field(description="New description")]
                     = None) -> dict[str, Any]:
        return impl.rename_patch(slot, expect_name, name, description)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Search patches without touching the pedal: the pedal's slots (newest full backup plus "
        "this server's writes), older backups and downloads/patches/. Matches slot number or "
        "label (A-001), name, description, effect name and the real gear an effect models "
        "(e.g. SVT, MXR). Each hit's ref (slot or file path) works in draw_patch, "
        "compare_patches and install_patch."))
    def search_patches(query: Annotated[str, Field(description="Text to look for")],
                       sources: Annotated[list[str] | None, Field(
                           description="Any of pedal, backups, downloads (default all)")] = None
                       ) -> dict[str, Any]:
        return impl.search_patches(query, sources)

    @server.tool(annotations=READ_ONLY, structured_output=True, description=(
        "Compare two patches in display units, with both drawings. Each of a and b is a slot "
        "number (read from the pedal), a .zptc path, or \"current\" (what the pedal plays "
        "now)."))
    def compare_patches(a: Annotated[int | str, Field(description="Slot, .zptc path or current")],
                        b: Annotated[int | str, Field(description="Slot, .zptc path or current")]
                        ) -> dict[str, Any]:
        return impl.compare_patches(a, b)

    @server.tool(annotations=BACKUP, structured_output=True, description=(
        "Read all 240 slots (1-240) of the pedal into a new full backup folder under backup/ "
        "(about a minute). Writes nothing to the pedal."))
    def backup_pedal() -> dict[str, Any]:
        return impl.backup_pedal()

    return server


def main() -> None:
    build_server(PedalSession(REPO_ROOT)).run()


if __name__ == "__main__":
    main()
