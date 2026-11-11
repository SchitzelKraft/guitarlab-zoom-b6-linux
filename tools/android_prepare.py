#!/usr/bin/env python3
"""Generate the git-ignored test fixtures and app assets for the B6 Remote Android app.

Usage: tools/android_prepare.py [--fixtures] [--assets]   (no flag = both)
Output contains Zoom data and the user's patches: never commit it.
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from b6lab import library, ptcf  # noqa: E402
from b6lab.codec import crc_tail, pack7  # noqa: E402
from b6lab.midi import B6  # noqa: E402

FIXTURES = ROOT / "android/core/src/test/resources/fixtures"
BACKUP = ROOT / "backup/b6-20261106-2339"


def write_json(directory, name, obj):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(obj, indent=1))
    print("wrote", directory / name)


def backup_entries():
    """(patch entry, decoded data, raw reply body without F0/F7) for every backup slot."""
    index = json.loads((BACKUP / "index.json").read_text())
    for p in index["patches"]:
        raw = (BACKUP / "syx" / (Path(p["file"]).stem + ".syx")).read_bytes()
        body = raw[1:-1] if raw[:1] == b"\xf0" and raw[-1:] == b"\xf7" else raw
        yield p, B6._decode(body, 10, f"slot {p['slot']}"), body


def codec_fixture():
    rng = random.Random(6)
    datas = [bytes(rng.randrange(256) for _ in range(rng.randint(0, 820))) for _ in range(20)]
    datas += [data for i, (_, data, _) in enumerate(backup_entries()) if i % 10 == 0]
    write_json(FIXTURES, "codec.json", [
        {"data": d.hex(), "packed": pack7(d).hex(), "crc_tail": bytes(crc_tail(d)).hex()}
        for d in datas])


def replies_fixture():
    entries = list(backup_entries())
    write_json(FIXTURES, "replies.json", [
        {"slot": p["slot"], "body": body.hex(), "data": data.hex()}
        for i, (p, data, body) in enumerate(entries) if i % 24 == 0])


SVT_TAILS = ROOT / "backup/b6-20261107-0139/001_SVT Drive.zptc"
EDIT_SLOTS = (1, 3, 101)
SLOT_IMAGE = 808


def _model(p):
    return {"name": p.name,
            "effects": [{"slot": e.slot, "fx_id": e.fx_id, "on": e.on, "params": e.params,
                         "is_tail": e.is_tail} for e in p.effects]}


def _edits(data):
    """Each chain edit applied to a fresh parse, encoded (null when Python refuses it)."""
    ops = {"set_param": lambda p: ptcf.set_param(p, 0, 0, 37),
           "set_on": lambda p: ptcf.set_on(p, 0, False),
           "set_type": lambda p: ptcf.set_type(p, 0, 0x07090010),
           "insert_entry": lambda p: ptcf.insert_entry(p, 1),
           "delete_entry": lambda p: ptcf.delete_entry(p, 0),
           "move_entry": lambda p: ptcf.move_entry(p, 0, 1)}
    out = {}
    for name, op in ops.items():
        p = ptcf.parse(data)
        try:
            ok = op(p)
        except (PermissionError, ValueError):
            ok = False
        out[name] = None if ok is False else ptcf.encode(p).hex()
    return out


def ptcf_record(slot, file, image):
    p = ptcf.parse(image)
    rec = {"slot": slot, "file": file, "raw": image.hex(), **_model(p),
           "encoded": ptcf.encode(p).hex()}
    if slot in EDIT_SLOTS:
        rec["edits"] = _edits(image)
    return rec


def ptcf_fixture():
    records = []
    for p, data, _ in backup_entries():
        image = bytes(data).ljust(SLOT_IMAGE, b"\0")
        assert len(image) == SLOT_IMAGE, (p["slot"], len(data))
        records.append(ptcf_record(p["slot"], p["file"], image))
    # SVT Drive with tails [F,T,F,T,F], padded to a slot image
    image = library.load_zptc(SVT_TAILS).ljust(SLOT_IMAGE, b"\0")
    records.append(ptcf_record(-1, "0139/" + SVT_TAILS.name, image))
    write_json(FIXTURES, "ptcf.json", records)


def fixtures():
    codec_fixture()
    replies_fixture()
    ptcf_fixture()


def assets():
    pass  # catalog.json and svg/ are added by later tasks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", action="store_true")
    ap.add_argument("--assets", action="store_true")
    a = ap.parse_args()
    both = not (a.fixtures or a.assets)
    if a.fixtures or both:
        fixtures()
    if a.assets or both:
        assets()


if __name__ == "__main__":
    main()
