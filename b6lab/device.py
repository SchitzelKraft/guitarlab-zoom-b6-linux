"""Safe save of a patch to a pedal slot: conflict check, backup, write, verify, select."""
import os
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from b6lab import ptcf
from b6lab.midi import SLOT_SIZE


@dataclass
class SaveResult:
    ok: bool
    message: str
    backup_file: Optional[Path] = None
    error: Optional[BaseException] = None  # the exception behind a failure, if any


def used_bytes(data: bytes) -> bytes:
    """The PTCF part of a slot image (length is the u32 at offset 4)."""
    used = struct.unpack_from("<I", data, 4)[0]
    return bytes(data[:used])


def validate_patch(new_data) -> Optional[str]:
    """Reason the data is not a writable PTCF image, or None if it is fine."""
    if len(new_data) < 0x24:
        return f"only {len(new_data)} bytes, shorter than a PTCF header"
    if new_data[:4] != b"PTCF":
        return "missing PTCF magic"
    used, _version, n = struct.unpack_from("<III", new_data, 4)
    if used > SLOT_SIZE:
        return f"used length {used} exceeds the pedal slot size {SLOT_SIZE}"
    if used > len(new_data):
        return f"used length {used} exceeds the data length {len(new_data)}"
    header = 0x24 + 4 * n
    if used < header:
        return f"used length {used} is smaller than the header ({header} bytes)"
    try:
        ptcf.parse(new_data)
    except Exception as e:
        return str(e)
    return None


def _safe_name(data: bytes) -> str:
    try:
        name = ptcf.parse(data).name
    except Exception:
        name = data[26:36].split(b"\x00")[0].decode("ascii", "replace")
    return re.sub(r"[^A-Za-z0-9 _.-]", "_", name).strip() or "unnamed"


def _backup_path(backup_dir: Path, slot: int, name: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_slot{slot + 1:03d}_{name}"
    path = backup_dir / f"{base}.zptc"
    n = 1
    while path.exists():
        n += 1
        path = backup_dir / f"{base}-{n}.zptc"
    return path


SELECT_RETRY = 0.5   # seconds between selects while the pedal is still busy after a write
SELECT_TRIES = 6


def _same_patch(a, b):
    try:
        pa, pb = ptcf.parse(a), ptcf.parse(b)
    except Exception:
        return False
    return pa.name == pb.name and [e.raw for e in pa.effects] == [e.raw for e in pb.effects]


def select_written(dev, slot, data):
    """Select `slot` after writing `data` to it. Right after a write the B6 ignores the select
    (tested 2026-11-10 on Z-103: a select at once was lost, one 1 s later was taken). Guitar
    Lab waits for the pedal's ack of each write step in sync mode; B6 Lab gets no acks outside
    sync mode, so it selects, reads the edit buffer back and selects again until it holds the
    patch. Returns True once the pedal shows it. In sync mode the select is sent once: the
    acks already spaced the write, and the pedal's `64 26` report is left for the idle poll."""
    if getattr(dev, "sync", False) or not hasattr(dev, "read_edit"):
        dev.select_slot(slot)
        return True
    for attempt in range(SELECT_TRIES):
        if attempt:
            time.sleep(SELECT_RETRY)
        dev.select_slot(slot)
        if _same_patch(bytes(dev.read_edit()), data):
            return True
    raise TimeoutError(f"the pedal did not switch to slot {slot + 1}")


def save_slot(dev, slot: int, new_data: bytes, loaded_data: Optional[bytes],
              backup_dir: Path, confirm_conflict: Callable[[], bool],
              store_edit: bool = False, select: bool = True) -> SaveResult:
    """Never raises: every failure is reported in the SaveResult.
    `store_edit`: the editor's SAVE, which (like Guitar Lab) sends Patch Save (`64 0D`) after
    the backup and before the write.
    `select`: after a verified write, select the slot on the pedal (default). False leaves the
    pedal on whatever it had selected."""
    backup_dir = Path(backup_dir)
    backup = None
    problem = validate_patch(new_data)
    if problem:
        return SaveResult(False, f"invalid patch: {problem}", None)
    try:
        current = dev.read_slot(slot)
        if loaded_data is not None and used_bytes(current) != used_bytes(loaded_data):
            if not confirm_conflict():
                return SaveResult(False, "cancelled", None)
        backup_dir.mkdir(parents=True, exist_ok=True)
        path = _backup_path(backup_dir, slot, _safe_name(current))
        with open(path, "xb") as f:
            f.write(current)
            f.flush()
            os.fsync(f.fileno())  # the backup must be on disk before the pedal is touched
        backup = path
    except Exception as e:
        return SaveResult(False, f"save failed before writing, pedal untouched: {e}", backup, e)

    try:
        if store_edit and hasattr(dev, "store_edit"):
            dev.store_edit(slot)
        dev.write_slot(slot, new_data)
    except Exception as e:
        return SaveResult(False, f"save failed: {e} (backup kept at {backup})", backup, e)

    try:
        back = dev.read_slot(slot)
        expected = used_bytes(new_data)
        same = back[: len(expected)] == expected
    except Exception as e:
        return SaveResult(False, f"could not verify the write: {e} (backup kept at {backup})", backup, e)
    if not same:
        return SaveResult(False, f"verify failed: read-back differs from what was written "
                                 f"(backup kept at {backup})", backup)

    if not select:
        return SaveResult(True, "saved and verified", backup)
    try:
        select_written(dev, slot, new_data)
    except Exception as e:
        return SaveResult(True, f"saved and verified; could not select the slot on the pedal: {e}",
                          backup, e)
    return SaveResult(True, "saved and verified", backup)
