"""PTCF patch model and decoder (Zoom B6 .zptc files).

See tools/ptcf.py history for the format derivation. Layout (little endian):
  0x00 "PTCF", 0x04 u32 used length, 0x08 u32 version, 0x0C u32 N slots,
  0x10 10 unknown bytes, 0x1A 10-byte name, 0x24 N x u32 effect IDs,
  then chunks <tag:4><len:u32><data>: TXJ1, TXE1, EDTB, PRM2.
"""
import struct
from dataclasses import dataclass, field

PARAM_START, ENTRY = 30, 24
PRM2_LEVEL_BIT, PRM2_LEVEL_WIDTH = 77, 8
PRM2_VISIBLE_START_BIT, PRM2_VISIBLE_START_WIDTH = 85, 4
PARAM_WIDTHS = [12] * 5 + [8] * ((ENTRY * 8 - PARAM_START - 60) // 8)
# Effect ID high byte = category, in the order of Zoom's "B6 Effects List".
CATEGORIES = {0x01: "DYNAMICS", 0x02: "FILTER", 0x03: "DRIVE", 0x04: "PREAMP", 0x05: "BASS AMP",
              0x06: "CABINET", 0x07: "MODULATION", 0x08: "SFX", 0x09: "DELAY", 0x0A: "REVERB",
              0x0B: "PEDAL", 0x0C: "SND-RTN", 0x1A: "SND-RTN", 0x1B: "IR"}


@dataclass
class Effect:
    slot: int
    fx_id: int
    on: bool
    params: list[int]
    is_tail: bool
    raw: int = 0  # full 192-bit little-endian EDTB entry

    @property
    def category(self):
        return CATEGORIES.get(self.fx_id >> 24, "?")

    def editable(self, index):
        """Every decoded parameter of a non-tail entry. Params 1-4 were confirmed with a knob
        test; 5+ by the values of all 108 stock/user patches matching the knob ranges in Zoom's
        effect list (no value of a param 6+ exceeds its 8-bit field; large ranges such as
        delay times live in params 1-5)."""
        return (not self.is_tail) and 0 <= index < len(PARAM_WIDTHS)

    def max_value(self, index):
        return (1 << PARAM_WIDTHS[index]) - 1


@dataclass
class Patch:
    name: str
    slots: int
    effect_ids: list[int]
    effects: list[Effect]
    txj1: bytes
    txe1: bytes
    prm2: list[bytes]
    header_unknown: bytes
    raw: bytes
    version: int = 2
    name_raw: bytes = b""  # exact 10 bytes at 0x1A
    chunks: list[tuple[str, bytes]] = field(default_factory=list)  # file order, bodies verbatim

    @property
    def comment(self):
        return self.txe1.split(b"\x00")[0].decode("latin-1")

    @property
    def pedal_slots(self):
        if not self.prm2 or len(self.prm2[0]) < 8:
            return []
        mask = struct.unpack_from("<I", self.prm2[0], 4)[0]
        return [b - 1 for b in range(1, 32) if mask >> b & 1]

    @property
    def level(self):
        """Patch level from the Mac application's PRM2 field layout."""
        if not self.prm2 or len(self.prm2[0]) * 8 < PRM2_LEVEL_BIT + PRM2_LEVEL_WIDTH:
            return None
        return (int.from_bytes(self.prm2[0], 'little') >> PRM2_LEVEL_BIT) & 0xFF

    @property
    def visible_start(self):
        """First displayed effect position from the Mac app's PRM2 layout."""
        if not self.prm2 or len(self.prm2[0]) * 8 < PRM2_VISIBLE_START_BIT + PRM2_VISIBLE_START_WIDTH:
            return None
        return (int.from_bytes(self.prm2[0], 'little') >> PRM2_VISIBLE_START_BIT) & 0x0F


def parse(data):
    data = bytes(data)
    if data[:4] != b"PTCF":
        raise ValueError("not a PTCF patch")
    if len(data) < 0x24:
        raise ValueError("truncated PTCF patch")
    used, version, n = struct.unpack_from("<III", data, 4)
    if used > len(data) or 0x24 + 4 * n > used:
        raise ValueError("truncated PTCF patch")
    name = data[0x1A:0x24].split(b"\x00")[0].decode("ascii", "replace").rstrip()
    ids = list(struct.unpack_from(f"<{n}I", data, 0x24))
    patch = Patch(name=name, slots=n, effect_ids=ids, effects=[], txj1=b"", txe1=b"", prm2=[],
                  header_unknown=data[0x10:0x1A], raw=data, version=version,
                  name_raw=data[0x1A:0x24])
    p = 0x24 + 4 * n
    while p + 8 <= used:
        tag = data[p:p + 4].decode("ascii", "replace")
        ln = struct.unpack_from("<I", data, p + 4)[0]
        if p + 8 + ln > used:
            raise ValueError("truncated PTCF chunk")
        body = data[p + 8:p + 8 + ln]
        p += 8 + ln
        patch.chunks.append((tag, body))
        if tag == "TXE1":
            patch.txe1 = body
        elif tag == "TXJ1":
            patch.txj1 = body
        elif tag == "EDTB":
            for k in range(len(body) // ENTRY):
                v = int.from_bytes(body[k * ENTRY:(k + 1) * ENTRY], "little")
                fx_id = (v >> 1) & 0x1FFFFFFF
                params, pos = [], PARAM_START
                for w in PARAM_WIDTHS:
                    params.append((v >> pos) & ((1 << w) - 1))
                    pos += w
                patch.effects.append(Effect(slot=k, fx_id=fx_id, on=bool(v & 1), params=params,
                                            is_tail=fx_id == 1, raw=v))
        elif tag == "PRM2":
            patch.prm2.append(body)
    return patch


MAX_SIZE = 808


def _sync_effect(e):
    """Refresh convenience fields of an Effect from its raw entry."""
    v = e.raw
    e.on = bool(v & 1)
    e.fx_id = (v >> 1) & 0x1FFFFFFF
    params, pos = [], PARAM_START
    for w in PARAM_WIDTHS:
        params.append((v >> pos) & ((1 << w) - 1))
        pos += w
    e.params = params


def _set_chunk(p, tag, body):
    for i, (t, _) in enumerate(p.chunks):
        if t == tag:
            p.chunks[i] = (t, body)
            return
    p.chunks.append((tag, body))


def encode(p):
    """Rebuild the used bytes of a patch from the model fields."""
    out = bytearray(b"PTCF")
    out += struct.pack("<III", 0, p.version, p.slots)
    out += p.header_unknown
    out += p.name_raw
    out += struct.pack(f"<{p.slots}I", *p.effect_ids)
    for tag, body in p.chunks:
        if tag == "EDTB":
            body = b"".join(e.raw.to_bytes(ENTRY, "little") for e in p.effects)
        elif tag == "TXE1":
            body = p.txe1
        out += tag.encode("ascii") + struct.pack("<I", len(body)) + body
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def set_param(p, slot, index, value):
    e = p.effects[slot]
    if not e.editable(index):
        raise PermissionError(f"param {index} of slot {slot} is not editable")
    w = PARAM_WIDTHS[index]
    value = max(0, min(int(value), (1 << w) - 1))
    pos = PARAM_START + sum(PARAM_WIDTHS[:index])
    e.raw = (e.raw & ~(((1 << w) - 1) << pos)) | (value << pos)
    _sync_effect(e)


def set_type(p, slot, fx_id):
    """Make entry `slot` the effect `fx_id` (EDTB bits 1-29 and the header ID list).

    Used by the fake and virtual pedals for a type change; what the real B6 does with the
    knob values (defaults or kept) is not known yet, so they are kept here."""
    e = p.effects[slot]
    if e.is_tail:
        raise ValueError(f"entry {slot} is the second half of a double-width effect")
    e.raw = (e.raw & ~(0x1FFFFFFF << 1)) | ((fx_id & 0x1FFFFFFF) << 1)
    _sync_effect(e)
    e.is_tail = e.fx_id == 1
    if slot < len(p.effect_ids):
        p.effect_ids[slot] = fx_id


MAX_ENTRIES = 6  # the B6 refuses an insert into a 6-entry patch (recorded 2026-11-09)


def _renumber(p):
    for i, e in enumerate(p.effects):
        e.slot = i
    p.slots = len(p.effects)


def insert_entry(p, pos):
    """ADD as the B6 does it (64 20 00 64 07 <pos>): an empty entry (raw 0x1: on, effect 0)
    at `pos`; refused (False) when the patch already has MAX_ENTRIES entries. The pedal also
    updates PRM2 position fields, which this model leaves alone."""
    if len(p.effects) >= MAX_ENTRIES or not 0 <= pos <= len(p.effects):
        return False
    if pos < len(p.effects) and p.effects[pos].is_tail:
        return False  # inside a double-width effect (the editor never asks for this)
    p.effects.insert(pos, Effect(slot=pos, fx_id=0, on=True, params=[0] * len(PARAM_WIDTHS),
                                 is_tail=False, raw=1))
    p.effect_ids.insert(pos, 0)
    _renumber(p)
    return True


def delete_entry(p, pos):
    """DELETE as the B6 does it (64 20 00 64 08 <pos>): removes the entry, and the second half
    too for a double-width effect."""
    if not 0 <= pos < len(p.effects) or p.effects[pos].is_tail:
        return False
    n = 2 if pos + 1 < len(p.effects) and p.effects[pos + 1].is_tail else 1
    del p.effects[pos:pos + n]
    del p.effect_ids[pos:pos + n]
    _renumber(p)
    return True


def move_entry(p, src, dst):
    """Chain move (64 20 00 64 09 <src> <dst>, recorded): the effect at entry `src` (with its
    second half when double width) taken out and put back at entry `dst`."""
    if not 0 <= src < len(p.effects) or p.effects[src].is_tail:
        return False
    n = 2 if src + 1 < len(p.effects) and p.effects[src + 1].is_tail else 1
    block, ids = p.effects[src:src + n], p.effect_ids[src:src + n]
    del p.effects[src:src + n]
    del p.effect_ids[src:src + n]
    dst = max(0, min(dst, len(p.effects)))
    p.effects[dst:dst] = block
    p.effect_ids[dst:dst] = ids
    _renumber(p)
    return True


def set_on(p, slot, on):
    e = p.effects[slot]
    e.raw = (e.raw & ~1) | (1 if on else 0)
    _sync_effect(e)


def set_level(p, value):
    """Set the B6 patch level, preserving all other PRM2 bits."""
    if p.level is None:
        raise ValueError("patch has no complete PRM2 level field")
    if not 0 <= value <= 120:
        raise ValueError("patch level must be between 0 and 120")
    body = p.prm2[0]
    raw = int.from_bytes(body, 'little')
    mask = ((1 << PRM2_LEVEL_WIDTH) - 1) << PRM2_LEVEL_BIT
    updated = ((raw & ~mask) | (value << PRM2_LEVEL_BIT)).to_bytes(len(body), 'little')
    p.prm2[0] = updated
    _set_chunk(p, 'PRM2', updated)


def set_name(p, name):
    if len(name) > 10 or not all(0x20 <= ord(c) <= 0x7E for c in name):
        raise ValueError("name must be at most 10 printable ASCII characters")
    p.name_raw = name.encode("ascii").ljust(10, b" ")
    p.name = name.rstrip()


def set_comment(p, text):
    """Latin-1 text padded with NULs to a multiple of 4 (real patches add no
    terminator when the text length is already a multiple of 4)."""
    body = text.encode("latin-1")  # raises UnicodeEncodeError (a ValueError)
    if b"\x00" in body:
        raise ValueError("comment must not contain NUL")
    body += b"\x00" * (-len(body) % 4)
    old = p.txe1
    p.txe1 = body
    old_chunks = list(p.chunks)
    _set_chunk(p, "TXE1", body)
    if len(encode(p)) > MAX_SIZE:
        p.txe1, p.chunks = old, old_chunks
        raise ValueError(f"patch would exceed {MAX_SIZE} bytes")
