"""PedalSession: the single owner of every pedal access for the MCP server.

Safety rules (docs/superpowers/specs/2026-11-12-b6-mcp-design.md, decisions 3, 9-12, 14, 15, 18):
- one pedal call at a time (a lock); the MIDI port is opened for the call and closed after it;
- a port held by another program is reported ("close B6 Lab"), never taken over;
- installs go to slots whose live patch is a real Empty patch (named "Empty" and no effects in
  its chain, `patchspec.is_empty_patch`), nothing else is ever overwritten; a patch named
  "Empty" is never installed;
- a full backup before the first write (install or clear) of the session, a per-slot backup
  before every write;
- every write is logged in backup/writes.jsonl;
- clear only undoes the server's own installs, and only while the slot still holds them.

Slots are 1-240 in every argument and result; the device is 0-based.
"""
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from b6lab import ptcf
from b6lab.device import save_slot, used_bytes, validate_patch
from b6lab.library import backup_all, list_backups
from b6lab.midi import B6, DeviceBusy, NotConnected
from b6lab import live
from b6lab.patchspec import EMPTY_NAME, chain_effect_ids, is_empty_patch
from b6lab.pedal_info import auto_save_on

SLOTS = 240
LIVE_SETTLE = 0.25  # seconds before reading back a live knob or on/off change
SELECT_SETTLE = 0.5  # seconds after selecting a slot before reading the edit buffer
AUTO_SAVE_TEXT = "switch AUTO SAVE off on the pedal (SYSTEM > AUTO SAVE)"
SCRATCH_TRIES = 3   # Empty slots tried, highest first, when picking the audition slot


class PedalError(RuntimeError):
    pass


class PedalBusy(PedalError):
    pass


class PedalUnavailable(PedalError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(used_bytes(data)).hexdigest()


def _describe(data: bytes) -> tuple:
    """(name, description) of a slot image; ("", "") if it does not parse."""
    try:
        p = ptcf.parse(bytes(data))
        return p.name, p.comment
    except Exception:
        return "", ""


_CATALOG = None


def _catalog_name(fx_id: int) -> str:
    """Effect name from the B6 catalog (pedal-files/effects.json), else the hex id."""
    global _CATALOG
    if _CATALOG is None:
        from b6lab import effects
        _CATALOG = effects.load()
    info = _CATALOG.get(fx_id)
    return info.name if info is not None else f"0x{fx_id:08X}"


def _check_slot(slot) -> int:
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= SLOTS:
        raise PedalError(f"slot must be a number 1-{SLOTS}, got {slot!r}")
    return slot


class PedalSession:
    def __init__(self, root: Path = Path("."), open_device: Callable = B6.open,
                 write_pause: float = 1.0, effect_name: Optional[Callable[[int], str]] = None):
        self.root = Path(root)
        self.backup_root = self.root / "backup"
        self.overwritten = self.backup_root / "overwritten"
        self.log_path = self.backup_root / "writes.jsonl"
        self._open_device = open_device
        self.write_pause = write_pause
        self._lock = threading.Lock()
        self.effect_name = effect_name or _catalog_name  # fx_id -> name, for messages
        self._full_backup_done = False
        self._own = {}  # slot (1-240) -> (name, description, empty) written by this session
        self._scratch: Optional[int] = None         # slot (1-240) holding the audition patch
        self._audition_from: Optional[int] = None   # slot selected before the audition

    # --- device access -------------------------------------------------------------------

    @contextmanager
    def _device(self):
        """Lock, open the port for this call only, close it after."""
        with self._lock:
            try:
                dev = self._open_device()
            except DeviceBusy as e:
                raise PedalBusy(f"the pedal's MIDI port is in use by another program ({e}); "
                                "close B6 Lab (or whatever holds the port) and try again") from e
            except NotConnected as e:
                raise PedalUnavailable(f"no pedal: {e}") from e
            try:
                yield dev
            except PedalError:
                raise
            except (TimeoutError, OSError) as e:
                raise PedalError(f"pedal communication failed: {e}") from e
            except Exception as e:  # e.g. the pedal's "returned error 0x.." or a corrupt slot
                raise PedalError(f"pedal call failed ({type(e).__name__}): {e}") from e
            finally:
                dev.close()

    def _backup(self, dev) -> str:
        bs = backup_all(dev, self.backup_root)
        self._own = {}  # the new backup already holds this session's writes
        return str(bs.path)

    def _log(self, action, slot, old, new, backup_file, verified, message):
        old_name, _ = _describe(old)
        new_name, _ = _describe(new)
        line = {"time": datetime.now().isoformat(timespec="seconds"), "action": action,
                "slot": slot, "old_name": old_name, "new_name": new_name,
                "old_sha256": _sha(old), "new_sha256": _sha(new),
                "backup_file": str(backup_file) if backup_file else None,
                "verified": bool(verified), "message": message}
        self.backup_root.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(json.dumps(line) + "\n")

    def _read_log(self) -> list:
        if not self.log_path.is_file():
            return []
        out = []
        for raw in self.log_path.read_text().splitlines():
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out

    def _write(self, dev, action, slot, data, live, select) -> dict:
        """save_slot with a log line for every attempted write; raises PedalError on failure.
        Called only after the live checks passed, so a refused call does not spend the full
        backup that precedes the session's first write (install or clear)."""
        full_backup: Optional[str] = None
        if not self._full_backup_done:
            full_backup = self._backup(dev)
            self._full_backup_done = True
        # `live` as loaded_data: save_slot re-reads the slot and cancels (confirm_conflict
        # answers no) if it changed since it was checked, e.g. during the full backup.
        res = save_slot(dev, slot - 1, data, live, self.overwritten, lambda: False,
                        select=select)
        if res.backup_file is not None:  # the pedal was (or may have been) written
            self._log(action, slot, live, data, res.backup_file, res.ok, res.message)
            time.sleep(self.write_pause)  # decision 18: pause after every write, failed or not
        if not res.ok:
            if res.message == "cancelled":
                raise PedalError(f"slot {slot} changed while {action}ing; nothing written")
            raise PedalError(f"slot {slot}: {res.message}")
        self._own[slot] = (*_describe(data), is_empty_patch(data))
        return {"backup_file": str(res.backup_file), "message": res.message,
                "full_backup": full_backup}

    def _require_auto_save_off(self, dev) -> None:
        """Live tools only run with AUTO SAVE known to be off; read on every call."""
        try:
            on = auto_save_on(bytes(dev.global_info()["raw"]))
        except Exception as e:  # noqa: BLE001 - unreadable counts as "maybe on"
            raise PedalError(f"AUTO SAVE could not be read ({e}); {AUTO_SAVE_TEXT}") from e
        if on is not False:
            state = "on" if on else "unknown"
            raise PedalError(f"AUTO SAVE is {state}, so the pedal would store live edits; "
                             f"{AUTO_SAVE_TEXT}")

    def _guard_effect(self, edit: bytes, entry: int, fx_id: int):
        p = ptcf.parse(edit)
        if not 0 <= entry < len(p.effects) or p.effects[entry].is_tail:
            raise PedalError(f"chain entry {entry} holds no effect of its own in the patch "
                             "the pedal is playing")
        found = p.effects[entry].fx_id
        if found != fx_id:
            raise PedalError(f"chain entry {entry} holds {self.effect_name(found)}, not "
                             f"{self.effect_name(fx_id)}: the pedal is on another patch or "
                             "the chain changed; read pedal_status first")
        return p

    # --- public API ----------------------------------------------------------------------

    def read_slot(self, slot: int) -> bytes:
        _check_slot(slot)
        with self._device() as dev:
            return bytes(dev.read_slot(slot - 1))

    def current_slot(self) -> int:
        with self._device() as dev:
            return dev.selected_slot() + 1

    def info(self) -> dict:
        """Everything the pedal reports about itself, raw; a read that fails is reported as
        {"error": ...} and does not stop the others (one port open for all)."""
        out = {}

        def read(key, fn):
            try:
                out[key] = fn()
            except Exception as e:  # noqa: BLE001 - every failure is reported per field
                out[key] = {"error": f"{type(e).__name__}: {e}"}

        with self._device() as dev:
            read("identity", lambda: bytes(dev.identity()))
            read("patch_info", dev.patch_info)
            read("selected_slot", lambda: dev.selected_slot() + 1)
            sel = out["selected_slot"]
            if isinstance(sel, int):
                read("selected_patch", lambda: bytes(dev.read_slot(sel - 1)))
            else:
                out["selected_patch"] = {"error": "selected slot unknown"}
            read("edit", lambda: bytes(dev.read_edit()))
            read("global", lambda: bytes(dev.global_info()["raw"]))
            read("memory_used", lambda: float(dev.memory_usage()))
            read("effect_list", lambda: bytes(dev.read_effect_list()))
            read("product_info", dev.product_info)
            read("patch_capabilities", dev.patch_capabilities)
        return out

    def read_edit(self) -> bytes:
        with self._device() as dev:
            return bytes(dev.read_edit())

    def status(self) -> dict:
        with self._device() as dev:
            slot = dev.selected_slot()
            stored, edit = bytes(dev.read_slot(slot)), bytes(dev.read_edit())
            try:
                auto = auto_save_on(bytes(dev.global_info()["raw"]))
            except Exception:  # noqa: BLE001 - reported as unknown
                auto = None
        return {"slot": slot + 1, "stored": stored, "edit": edit, "auto_save": auto,
                "scratch": self._scratch, "audition_from": self._audition_from}

    def set_param(self, entry: int, fx_id: int, index: int, raw: int) -> bytes:
        with self._device() as dev:
            self._require_auto_save_off(dev)
            p = self._guard_effect(bytes(dev.read_edit()), entry, fx_id)
            live.send_param(dev, p, entry, index, raw)
            time.sleep(LIVE_SETTLE)
            edit = bytes(dev.read_edit())
        got = ptcf.parse(edit).effects[entry].params[index]
        if got != raw:
            raise PedalError(f"the pedal did not take the value: knob {index + 1} of entry "
                             f"{entry} reads {got}, sent {raw}")
        return edit

    def set_effect_on(self, entry: int, fx_id: int, on: bool) -> bytes:
        with self._device() as dev:
            self._require_auto_save_off(dev)
            self._guard_effect(bytes(dev.read_edit()), entry, fx_id)
            try:
                live.set_effect_on(dev, entry, on, None)
            except live.LiveError as e:
                raise PedalError(str(e)) from e
            time.sleep(LIVE_SETTLE)
            edit = bytes(dev.read_edit())
        if ptcf.parse(edit).effects[entry].on != bool(on):
            raise PedalError(f"the pedal did not switch entry {entry} {'on' if on else 'off'}")
        return edit

    def _select(self, slot: int) -> bytes:
        with self._device() as dev:
            dev.select_slot(slot - 1)
            time.sleep(SELECT_SETTLE)
            return bytes(dev.read_edit())

    def _drop_scratch(self) -> None:
        """Back to the slot selected before the audition, then empty the scratch slot."""
        if self._scratch is None:
            return
        self._select(self._audition_from)
        self.clear(self._scratch)
        self._scratch = None

    def audition(self, data: bytes) -> dict:
        """Play `data` on the pedal from a scratch Empty slot (Phase 0 decision: `28` writes
        the selected slot's memory, so it is not used). A new audition replaces the last."""
        with self._device() as dev:
            self._require_auto_save_off(dev)
            before = dev.selected_slot() + 1
        if self._scratch is None:
            self._audition_from = before
            candidates = [p["slot"] for p in reversed(self.list_patches(False)["patches"])
                          if p["empty"] and p["slot"] != before]
        else:
            candidates = [self._scratch]
            self._drop_scratch()
        last = None
        for slot in candidates[:SCRATCH_TRIES]:
            try:
                out = self.install(data, slot, select=True)
            except PedalError as e:
                if "not an Empty slot" not in str(e) and "named Empty but" not in str(e):
                    raise
                last = e
                continue
            self._scratch = slot
            time.sleep(SELECT_SETTLE)
            return {**out, "edit": self.read_edit(), "audition_from": self._audition_from}
        raise PedalError(f"no Empty slot found for the audition ({last})" if last
                         else "no Empty slot left for the audition")

    def revert(self) -> tuple:
        """The pedal plays the stored patch again: back from an audition (scratch slot
        cleared), or the selected slot re-selected (drops live edits, verified 2026-11-13)."""
        if self._scratch is not None:
            slot = self._audition_from
            self._drop_scratch()
            self._audition_from = None
        else:
            with self._device() as dev:
                slot = dev.selected_slot() + 1
        edit = self._select(slot)
        stored = self.read_slot(slot)
        if used_bytes(edit) != used_bytes(stored):
            raise PedalError(f"slot {slot} re-selected but the pedal still plays an edited patch")
        return slot, edit

    def backup(self) -> str:
        with self._device() as dev:
            return self._backup(dev)

    def list_patches(self, refresh: bool = False) -> dict:
        if refresh:
            self.backup()
        sets = list_backups(self.backup_root)
        if not sets:
            self.backup()
            sets = list_backups(self.backup_root)
        if not sets:
            raise PedalError("no full backup could be made or found")
        newest = sets[-1]
        patches = []
        for i, data in enumerate(newest.slots[:SLOTS]):
            name, description = _describe(data)
            patches.append({"slot": i + 1, "name": name, "description": description,
                            "empty": is_empty_patch(data)})
        for slot, (name, description, empty) in self._own.items():
            if slot <= len(patches):
                patches[slot - 1] = {"slot": slot, "name": name, "description": description,
                                     "empty": empty}
        age = int((datetime.now() - newest.created).total_seconds() // 60)
        return {"source": str(newest.path), "age_minutes": max(age, 0), "patches": patches}

    def install(self, data: bytes, slot: int, select: bool = False) -> dict:
        _check_slot(slot)
        data = bytes(data)
        problem = validate_patch(data)
        if problem:
            raise PedalError(f"invalid patch: {problem}")
        name, _ = _describe(data)
        if name.strip() == EMPTY_NAME:
            raise PedalError(f"refusing to install a patch named {EMPTY_NAME!r}: the name is "
                             "reserved for empty slots; rename the patch")
        with self._device() as dev:
            live = bytes(dev.read_slot(slot - 1))
            if not is_empty_patch(live):
                live_name, _ = _describe(live)
                if live_name == EMPTY_NAME:
                    names = ", ".join(self.effect_name(i) for i in chain_effect_ids(live))
                    raise PedalError(f"slot {slot} is named Empty but contains {names}; "
                                     "refusing (the MCP server only installs to Empty slots)")
                raise PedalError(f"slot {slot} holds {live_name!r}, not an Empty slot; "
                                 "the MCP server only installs to Empty slots")
            out = self._write(dev, "install", slot, data, live, select)
        return {"slot": slot, "name": name, "backup_file": out["backup_file"],
                "full_backup": out["full_backup"], "message": out["message"]}

    def clear(self, slot: int) -> dict:
        _check_slot(slot)
        mine = [e for e in self._read_log() if e.get("slot") == slot and e.get("verified")]
        if not mine or mine[-1].get("action") != "install":
            raise PedalError(f"slot {slot} was not written by the MCP server (or was cleared "
                             "already); only the server's own installs can be cleared")
        entry = mine[-1]
        backup_file = Path(entry.get("backup_file") or "")
        if not backup_file.is_file():
            raise PedalError(f"slot {slot}: the Empty image backup {backup_file} is missing")
        empty = backup_file.read_bytes()
        if _sha(empty) != entry.get("old_sha256") or not is_empty_patch(empty):
            raise PedalError(f"slot {slot}: the Empty image backup {backup_file} is not the "
                             "Empty patch the install replaced; nothing written")
        with self._device() as dev:
            live = bytes(dev.read_slot(slot - 1))
            if _sha(live) != entry.get("new_sha256"):
                raise PedalError(f"slot {slot} changed since it was installed; "
                                 "it is left as it is")
            removed, _ = _describe(live)
            out = self._write(dev, "clear", slot, empty, live, False)
        return {"slot": slot, "removed": removed, "full_backup": out["full_backup"],
                "message": out["message"]}
