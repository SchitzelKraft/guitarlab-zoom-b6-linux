"""Extract intact embedded PNGs from the supplied Guitar Lab Mac executable.

Each image is named for its byte offset in the input; index.json preserves the
source SHA-256 and exact offsets. This tool only reads the binary and writes to
the requested output directory. It does not execute the Mac application.

The input may be the app's universal binary ("ZOOM Guitar Lab.app/Contents/MacOS/ZOOM
Guitar Lab"): the x86-64 slice is used, because B6 Lab names the images by their offset in
that slice. With --ir-svg, the effect icon Guitar Lab draws for IR effects (an SVG kept in
the binary, not downloaded) is written there too.
"""
import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

PNG = b"\x89PNG\r\n\x1a\n"
FAT_MAGIC = 0xCAFEBABE
CPU_X86_64 = 0x01000007
IR_SVG = re.compile(rb'<svg id="efx_IR_01".*?</svg>', re.S)


def x86_64_slice(data):
    """The x86-64 slice of a universal (fat) Mach-O, or the data unchanged."""
    if len(data) < 8 or struct.unpack_from(">I", data, 0)[0] != FAT_MAGIC:
        return data
    for k in range(struct.unpack_from(">I", data, 4)[0]):
        cpu, _sub, offset, size, _align = struct.unpack_from(">iiIII", data, 8 + 20 * k)
        if cpu & 0xFFFFFFFF == CPU_X86_64:
            return data[offset:offset + size]
    raise SystemExit("no x86-64 slice in this binary")


def find_images(data):
    cursor = 0
    while (offset := data.find(PNG, cursor)) != -1:
        cursor = offset + len(PNG)
        position = cursor
        try:
            while True:
                length = struct.unpack_from(">I", data, position)[0]
                end = position + 12 + length
                if length > 10_000_000 or end > len(data):
                    break
                tag = data[position + 4:position + 8]
                chunk = data[position + 4:position + 8 + length]
                crc = struct.unpack_from(">I", data, position + 8 + length)[0]
                if zlib.crc32(chunk) != crc:
                    break
                position = end
                if tag == b"IEND":
                    width, height = struct.unpack_from(">II", data, offset + 16)
                    yield offset, position, width, height
                    break
        except struct.error:
            continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ir-svg", type=Path, help="also write the IR effect icon to this file")
    args = parser.parse_args()
    data = x86_64_slice(args.binary.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    images = []
    for offset, end, width, height in find_images(data):
        filename = f"{offset:08x}.png"
        image = data[offset:end]
        (args.output / filename).write_bytes(image)
        images.append({"file": filename, "offset": offset, "length": len(image),
                       "width": width, "height": height,
                       "sha256": hashlib.sha256(image).hexdigest()})
    index = {"source_sha256": hashlib.sha256(data).hexdigest(), "images": images}
    (args.output / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"Extracted {len(images)} images to {args.output}")
    if args.ir_svg:
        found = IR_SVG.search(data)
        if not found:
            raise SystemExit("the IR icon was not found in this binary")
        args.ir_svg.parent.mkdir(parents=True, exist_ok=True)
        args.ir_svg.write_bytes(found.group(0) + b"\n")
        print(f"Wrote the IR icon to {args.ir_svg}")


if __name__ == "__main__":
    main()
