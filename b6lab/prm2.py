"""PRM2: the 32-byte patch-settings chunk of a B6 patch, computed from the chain.

The chunk is 256 bits, split into fixed-width fields packed LSB first.
"""
from __future__ import annotations

from b6lab.ptcf import Effect

FIELD_WIDTHS = [11, 11, 11, 11, 11, 11, 11, 8, 4, 4, 4, 4, 4, 12,
                11, 11, 11, 11, 11, 22, 5, 5, 8, 8, 8, 28]

_PEDAL_CAT = 0x0B
_SEND_IDS = (0x1A000023, 0x1A000020)
_RETURN_IDS = (0x1A000026, 0x1A000020)


def unpack(prm2: bytes) -> list[int]:
    value = int.from_bytes(prm2, "little")
    fields = []
    for width in FIELD_WIDTHS:
        fields.append(value & ((1 << width) - 1))
        value >>= width
    return fields


def pack(fields: list[int]) -> bytes:
    value = 0
    shift = 0
    for width, field in zip(FIELD_WIDTHS, fields):
        value |= (field & ((1 << width) - 1)) << shift
        shift += width
    return value.to_bytes(32, "little")


def _nibbles(indices: list[int]) -> int:
    value = 0
    for pos in range(4):
        nib = indices[pos] if pos < len(indices) else 0xF
        value |= (nib & 0xF) << (4 * pos)
    return value


def footswitches_of(prm2: bytes) -> list[int]:
    value = unpack(prm2)[25]
    nibs = [(value >> (4 * pos)) & 0xF for pos in range(4)]
    return [n for n in nibs if n != 0xF]


def compute(effects: list[Effect], level: int,
            footswitches: list[int] | None = None) -> bytes:
    fields = [0] * len(FIELD_WIDTHS)
    for i, eff in enumerate(effects):
        bit = 1 << i
        if eff.fx_id >> 24 == _PEDAL_CAT:
            fields[3] |= bit
        if eff.fx_id in _SEND_IDS:
            fields[14] |= bit
        if eff.fx_id in _RETURN_IDS:
            fields[16] |= bit
    fields[7] = level
    order = list(range(min(len(effects), 5)))
    order += [0] * (5 - len(order))
    fields[8:13] = order
    if footswitches is None:
        footswitches = [i for i, eff in enumerate(effects)
                        if not eff.is_tail and eff.fx_id not in (0, 1)][:4]
    fields[25] = _nibbles(footswitches)
    return pack(fields)
