"""Patch files (.zptc) and whole-pedal backups on disk."""
import json
import re
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from b6lab.device import used_bytes, validate_patch, _safe_name


def load_zptc(path) -> bytes:
    """Read a .zptc file; raise ValueError with a readable message if unusable."""
    path = Path(path)
    data = path.read_bytes()
    problem = validate_patch(data)
    if problem:
        raise ValueError(f"{path.name} is not a usable B6 patch: {problem}")
    return used_bytes(data)


def export_zptc(data: bytes, path) -> None:
    """Write the used part of a patch image to a .zptc file."""
    Path(path).write_bytes(used_bytes(data))


@dataclass
class BackupSet:
    path: Path
    created: datetime
    slots: list


def _created(path: Path) -> datetime:
    m = re.fullmatch(r"b6-(\d{8})-(\d{4})", path.name)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _load_set(path: Path):
    try:
        index = json.loads((path / "index.json").read_text())
        slots = []
        for entry in sorted(index["patches"], key=lambda e: e["slot"]):
            slots.append((path / entry["file"]).read_bytes())
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return BackupSet(path, _created(path), slots)


def list_backups(root=Path("backup")) -> list:
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "index.json").is_file():
            bs = _load_set(d)
            if bs is not None:
                out.append(bs)
    return out


def backup_all(dev, root) -> BackupSet:
    """Back up every slot into a new b6-YYYYMMDD-HHMM directory under root.

    Same layout as `zoomb6.py backup`, except that syx/ is not written (read_slot
    does not expose the raw pedal reply).
    """
    root = Path(root)
    now = datetime.now()
    path = root / now.strftime("b6-%Y%m%d-%H%M")
    n = 1
    while path.exists():
        n += 1
        path = root / f"{now.strftime('b6-%Y%m%d-%H%M')}-{n}"
    path.mkdir(parents=True)
    count = dev.patch_count()
    info = dev.patch_info() if hasattr(dev, "patch_info") else {"count": count, "size": 808}
    index = {"identity": dev.identity().hex(" "), "patch_info": info, "patches": []}
    slots = []
    for slot in range(count):
        data = bytes(dev.read_slot(slot))
        name = ""
        try:
            from b6lab import ptcf
            name = ptcf.parse(data).name
        except Exception:
            name = _safe_name(data)
        fn = f"{slot + 1:03d}_{_safe_name(data)}.zptc"
        (path / fn).write_bytes(data)
        index["patches"].append({"slot": slot, "bank": slot // 4 + 1, "pos": slot % 4 + 1,
                                 "name": name, "file": fn, "crc32": f"{zlib.crc32(data):08x}"})
        slots.append(data)
    (path / "index.json").write_text(json.dumps(index, indent=1))
    return BackupSet(path, now, slots)
