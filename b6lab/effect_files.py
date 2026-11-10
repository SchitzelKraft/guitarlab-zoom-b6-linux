"""Where an effect's files come from for "Load to Device", and the effect <-> file mapping.

An effect is two files on the B6: <BASE>.ZD2 (the module) and <BASE>.ZIC (its icon). For a
reinstall B6 Lab uses, in this order: its own copies in pedal-files/ (downloaded from the pedal,
and saved there before every "Delete from Device"), then Guitar Lab's library under Wine
(AppData/Roaming/GL/<BASE>_<version>.zd2 and GL/ZIC/50_71_2byte_zic/<BASE>.ZIC), which is
where Guitar Lab itself takes them from (byte-identical to what it wrote, recorded 2026-11-09).
"""
import json
import re
from pathlib import Path

from b6lab import effects

PEDAL_FILES = Path(__file__).resolve().parents[1] / "pedal-files"
GL_LIBRARY = Path.home() / ".wine-guitarlab/drive_c/users" / Path.home().name / "AppData/Roaming/GL"


def module_file(fx_id):
    """"BOMBER88.ZD2" for an effect ID (from the catalog's parameter ranges)."""
    ranges = json.loads(effects.RANGES_PATH.read_text())
    entry = ranges.get(f"{fx_id:08X}")
    return entry["module"].upper() if entry and entry.get("module") else None


def base_name(fx_id):
    m = module_file(fx_id)
    return m[:-4] if m and m.endswith(".ZD2") else None


def find_zd2(base, roots=(PEDAL_FILES, GL_LIBRARY)):
    own = roots[0] / f"{base}.ZD2"
    if own.is_file():
        return own.read_bytes()
    lib = roots[1]
    if lib.is_dir():
        versions = sorted((p for p in lib.glob("*.zd2") if re.fullmatch(rf"{re.escape(base)}_\d+\.zd2", p.name, re.I)),
                          key=lambda p: int(re.search(r"_(\d+)\.zd2$", p.name, re.I).group(1)))
        if versions:
            return versions[-1].read_bytes()
    return None


def find_zic(base, roots=(PEDAL_FILES, GL_LIBRARY)):
    for path in (roots[0] / f"{base}.ZIC", roots[1] / "ZIC" / "50_71_2byte_zic" / f"{base}.ZIC"):
        if path.is_file():
            return path.read_bytes()
    return None


def keep(base, name, data, root=PEDAL_FILES):
    """Save a file read from the pedal (before deleting it there), unless a copy exists."""
    path = Path(root) / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path
