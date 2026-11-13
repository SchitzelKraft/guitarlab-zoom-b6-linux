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

from b6lab import effects, ptcf
from b6lab.effect_models import load_models
from b6lab.knobs import KnobError, display_value
from b6lab.library import list_backups, load_zptc
from b6lab.device import used_bytes
from b6lab.patchspec import EMPTY_NAME, References, SpecError, build, describe, reference_index
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
chain) and the name Empty is refused; a full backup is made before the first write (install
or clear) of the session and a per-slot backup before every write; every write is logged
in backup/writes.jsonl; clear_slot only undoes this server's own unchanged installs. Only one
program can hold the pedal's MIDI port: if a tool says the port is busy, ask the user to close
B6 Lab. Claude cannot hear the pedal; the user judges the sound."""

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
            return {"slot": slot, **describe(data, self.catalog, slot=slot)}

    def current_patch(self) -> dict:
        with _tool_errors():
            slot = self.session.current_slot()
            data = self.session.read_slot(slot)
            return {"slot": slot, **describe(data, self.catalog, slot=slot)}

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
        if (file is None) == (spec is None):
            raise ToolError("install_patch needs exactly one of 'file' (a .zptc path) or "
                            "'spec' (a patch spec)")
        with _tool_errors():
            if spec is not None:
                data, warnings = self._build(spec)
                path = self._save(data, ptcf.parse(data).name)
            else:
                path = self._file(file)
                data, warnings = load_zptc(path), []
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
        field("edited", lambda: used_bytes(need(raw["edit"]))
              != used_bytes(need(raw["selected_patch"])))
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
    server = MCPServer(name="b6", instructions=INSTRUCTIONS)

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
