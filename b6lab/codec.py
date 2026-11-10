"""Zoom B6 SysEx codec: 7-in-8 packing, 14-bit values and the CRC tail."""
import zlib


def pack7(data):
    """Groups of 7 bytes, preceded by a byte holding their high bits (MSB first)."""
    out = bytearray()
    for i in range(0, len(data), 7):
        g = data[i:i + 7]
        h = 0
        for j, x in enumerate(g):
            if x & 0x80:
                h |= 1 << (6 - j)
        out.append(h)
        out.extend(x & 0x7F for x in g)
    return bytes(out)


def unpack7(d):
    out = bytearray()
    for i in range(0, len(d), 8):
        h = d[i]
        for j, x in enumerate(d[i + 1:i + 8]):
            out.append(x | (0x80 if (h >> (6 - j)) & 1 else 0))
    return bytes(out)


def to7(value, n):
    """value as n 7-bit bytes, little endian."""
    return [(value >> (7 * i)) & 0x7F for i in range(n)]


def from7(data):
    """Inverse of to7."""
    return sum(x << (7 * i) for i, x in enumerate(data))


def crc_tail(data):
    """5 bytes of ~CRC32(data), 7-bit little endian."""
    return to7(zlib.crc32(data) ^ 0xFFFFFFFF, 5)


def packed_len(size):
    """Length of pack7 output for `size` data bytes."""
    return (size // 7) * 8 + ((size % 7) + 1 if size % 7 else 0)
