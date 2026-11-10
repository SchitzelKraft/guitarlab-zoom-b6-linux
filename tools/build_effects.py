#!/usr/bin/env python3
"""Build pedal-files/effects.json (effect and knob names) from the pedal's own files.

  1. tools/ffs_read.py FLST_SEQ.ZT2 <all .ZD2 names>   (read the effect files)
  2. tools/build_effects.py                            (reads IR names from the pedal)
     tools/build_effects.py --no-pedal                 (reuse pedal-files/ir_names.txt)
"""
import argparse
import glob
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from b6lab import effects  # noqa: E402
from b6lab.midi import B6  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-d", "--dir", default=os.path.join(ROOT, "pedal-files"))
    ap.add_argument("--no-pedal", action="store_true", help="do not ask the pedal for IR names")
    a = ap.parse_args()
    ir_file = os.path.join(a.dir, "ir_names.txt")
    if a.no_pedal:
        names = open(ir_file).read().split("\n") if os.path.exists(ir_file) else []
        names = [n for n in names if n]
    else:
        dev = B6.open()
        try:
            names = effects.parse_ir_names(dev.request([0x52, 0x00, 0x6E, 0x64, 0x1A],
                                                       [0x52, 0x00, 0x6E, 0x64, 0x1B]))
        finally:
            dev.close()
        open(ir_file, "w").write("\n".join(names) + "\n")
    zd2 = sorted(glob.glob(os.path.join(a.dir, "*.ZD2")))
    cat = effects.build(zd2, names)
    out = os.path.join(a.dir, "effects.json")
    effects.save(cat, out)
    print(f"{len(zd2)} effect files + {len(names)} IR names -> {len(cat)} entries in {out}")


if __name__ == "__main__":
    main()
