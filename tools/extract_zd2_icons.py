"""Extract embedded BMP effect images from ZOOM .ZD2 modules, without executing them."""
import argparse
import hashlib
import json
import struct
from pathlib import Path


def embedded_bitmap(data):
    if data[:4] != b'ZDLF' or len(data) < 0x7A:
        raise ValueError('not a ZD2 effect module')
    position = data.find(b'BM', 0x7A)
    while position >= 0:
        if position + 26 <= len(data):
            size = struct.unpack_from('<I', data, position + 2)[0]
            pixels = struct.unpack_from('<I', data, position + 10)[0]
            dib_size = struct.unpack_from('<I', data, position + 14)[0]
            if 26 <= size <= len(data) - position and 14 + dib_size <= pixels < size:
                return data[position:position + size], position
        position = data.find(b'BM', position + 2)
    raise ValueError('no valid embedded BMP found')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('modules', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in sorted(args.modules.glob('*.ZD2')):
        data = source.read_bytes()
        image, offset = embedded_bitmap(data)
        effect_id = struct.unpack_from('<I', data, 0x60)[0]
        filename = f'{effect_id:08x}.bmp'
        (args.output / filename).write_bytes(image)
        rows.append({'file': filename, 'effect_id': effect_id, 'module': source.name,
                     'module_sha256': hashlib.sha256(data).hexdigest(), 'offset': offset,
                     'length': len(image), 'sha256': hashlib.sha256(image).hexdigest()})
    (args.output / 'index.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(f'Extracted {len(rows)} effect images to {args.output}')


if __name__ == '__main__':
    main()
