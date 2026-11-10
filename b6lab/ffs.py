"""The B6's flash file system (FFS) as Guitar Lab writes it: effect install and remove.

Recorded from Guitar Lab 7.3 on the B6 (captures/20261109-real-effect-pool: Bomber and Air
removed and loaded again); every command gets exactly one `60 xx` reply:

  delete   60 24 <name>\0                     -> 60 03 <status:5>   (0 ok, -6 not found)
  open     60 20 01 <9 x 00> <name>\0         -> 60 04 20 ...        then poll 60 05 00 -> 60 03
  write    60 23 <handle:5> <len:5> <packed> <crc:5> -> 60 04 23 ... <len:5>, then the poll
           (handle -1 = the open file; blocks of 760 bytes, data 7-bit packed, crc32 ^ ~0)
  close    60 21 <handle:5>                   -> 60 03
  flush    60 09                              -> 60 05 00
  space    60 29                              -> 60 04 29 ...       then the poll

Remove ("Delete from Device"): delete X.ZD2, delete X.ZIC, delete FLST_SEQ.ZT2, write it again
with the effect's installed flag 0, flush, space. Install ("Load to Device"): delete and write
X.ZIC, delete and write X.ZD2, delete and write FLST_SEQ.ZT2 with the flag 1, flush, space.
FLST_SEQ.ZT2 holds a 26-byte record per effect: name (13), version (5), installed flag at +18.
"""
import binascii

from b6lab.codec import from7, pack7, to7

HDR = bytes([0x52, 0x00, 0x6E])
BLOCK = 760
HANDLE = to7(0xFFFFFFFF, 5)  # the file just opened
LIST = "FLST_SEQ.ZT2"
FLAG_OFFSET = 18


class FFSError(OSError):
    pass


def _name(name):
    """A file name as Guitar Lab sends it: zero-padded to 13 bytes ("SOURCE.WAV" + 3 zeros,
    "BOMBER88.ZD2" + 1, recorded)."""
    raw = name.encode("ascii")
    return list(raw + b"\0" * max(1, 13 - len(raw)))


def _cmd(dev, payload, timeout=5.0):
    """Send one FFS command and return the pedal's `60 xx` reply."""
    dev.send([*HDR, 0x60, *payload])
    while True:
        reply = dev.recv_sysex(timeout)
        if reply[:4] == HDR + b"\x60":
            return reply


def _status(reply):
    return from7(reply[5:10]) if len(reply) >= 10 else 0


def poll(dev):
    return _cmd(dev, [0x05, 0x00])


def delete(dev, name):
    """60 24: the status (-6 / 0xFFFFFFFA when the file is not there, which is fine)."""
    return _status(_cmd(dev, [0x24, *_name(name)]))


def write_file(dev, name, data):
    reply = _cmd(dev, [0x20, 0x01] + [0] * 9 + _name(name))
    if reply[4:5] != b"\x04":
        raise FFSError(f"open {name} for writing: {reply.hex(' ')}")
    # the handle the pedal returns: -1 for effect files, a real one for SOURCE.WAV (recorded)
    handle = list(reply[10:15]) if len(reply) >= 15 else list(HANDLE)
    poll(dev)
    for i in range(0, len(data), BLOCK):
        block = bytes(data[i:i + BLOCK])
        crc = binascii.crc32(block) ^ 0xFFFFFFFF
        reply = _cmd(dev, [0x23, *handle, *to7(len(block), 5), *pack7(block), *to7(crc, 5)])
        if reply[4:5] != b"\x04" or from7(reply[10:15]) != len(block):
            raise FFSError(f"write {name} at {i}: {reply.hex(' ')}")
        status = _status(poll(dev))
        if status:
            raise FFSError(f"write {name} at {i}: status {status:#x}")
    status = _status(_cmd(dev, [0x21, *handle]))
    if status:
        raise FFSError(f"close {name}: status {status:#x}")


def read_file(dev, name):
    """Read a whole file as Guitar Lab reads FLST_SEQ.ZT2 at connect (recorded): find
    `60 25 00 00 <name>`, poll, `60 27`, open `60 20 02 ...`, poll, then per block `60 22
    <handle> <760:5>` and the poll, whose reply carries `60 04 22 01 00 <len:2> <packed>
    <crc:5>`; a short block ends the file, then one more poll and the close `60 21`."""
    import binascii
    from b6lab.codec import unpack7
    _cmd(dev, [0x25, 0x00, 0x00, *_name(name)])
    poll(dev)
    _cmd(dev, [0x27])
    reply = _cmd(dev, [0x20, 0x02] + [0] * 9 + _name(name))
    if reply[4:5] != b"\x04":
        raise FFSError(f"open {name} for reading: {reply.hex(' ')}")
    poll(dev)
    data = bytearray()
    try:
        while True:
            _cmd(dev, [0x22, *HANDLE, *to7(BLOCK, 5)])
            p = poll(dev)
            if p[4:6] != b"\x04\x22" or len(p) < 15:
                raise FFSError(f"read {name}: {p.hex(' ')[:60]}")
            n = p[8] | p[9] << 7
            block = bytes(unpack7(p[10:-5]))[:n]
            if from7(p[-5:]) ^ 0xFFFFFFFF != binascii.crc32(block):
                raise FFSError(f"read {name}: CRC mismatch at {len(data)}")
            data += block
            if n < BLOCK:
                break
        poll(dev)  # Guitar Lab polls once more after the last block (recorded)
    finally:
        _cmd(dev, [0x21, *HANDLE])
    return bytes(data)


def installed(effect_list):
    """{ZD2 file name: installed flag} from FLST_SEQ.ZT2's 26-byte effect records."""
    import re
    return {m.group(1).decode(): effect_list[m.start() + FLAG_OFFSET] == 1
            for m in re.finditer(rb"([A-Z0-9_]{1,8}\.ZD2)\0", effect_list)
            if m.start() + FLAG_OFFSET < len(effect_list)}


FLUSH_TIMEOUT = 60.0  # the B6 answers 60 09 only once the flash is committed: > 5 s seen


def finish(dev):
    """Flush and read the space (Used Memory), as Guitar Lab ends every change. The flush can
    take several seconds (on 2026-11-09 a 5 s wait was too short after deleting Bomber)."""
    _cmd(dev, [0x09], timeout=FLUSH_TIMEOUT)
    reply = _cmd(dev, [0x29], timeout=FLUSH_TIMEOUT)
    poll(dev)
    return reply


def record_offset(effect_list, zd2_name):
    """Offset of the effect's record in FLST_SEQ.ZT2 (its 13-byte name field)."""
    key = zd2_name.encode("ascii")
    key = key + b"\0" * (13 - len(key))
    i = effect_list.find(key)
    if i < 0:
        raise KeyError(f"{zd2_name} is not in {LIST}")
    return i


def set_installed(effect_list, zd2_name, installed):
    data = bytearray(effect_list)
    data[record_offset(effect_list, zd2_name) + FLAG_OFFSET] = 1 if installed else 0
    return bytes(data)


def remove_effect(dev, base, effect_list):
    """"Delete from Device" for the effect whose files are BASE.ZD2 / BASE.ZIC. `effect_list`
    is the pedal's current FLST_SEQ.ZT2; returns the new one and the `60 29` reply."""
    new_list = set_installed(effect_list, f"{base}.ZD2", False)
    delete(dev, f"{base}.ZD2")
    delete(dev, f"{base}.ZIC")
    delete(dev, LIST)
    write_file(dev, LIST, new_list)
    return new_list, finish(dev)


def install_effect(dev, base, zd2, zic, effect_list):
    """"Load to Device": the module and icon files, then the list with the flag set."""
    new_list = set_installed(effect_list, f"{base}.ZD2", True)
    delete(dev, f"{base}.ZIC")
    write_file(dev, f"{base}.ZIC", zic)
    delete(dev, f"{base}.ZD2")
    write_file(dev, f"{base}.ZD2", zd2)
    delete(dev, LIST)
    write_file(dev, LIST, new_list)
    return new_list, finish(dev)


def import_ir(dev, slot, name, wav):
    """IMPORT IR as Guitar Lab does it on the B6 (recorded 2026-11-10, captures/20261110-real-all):
    52 (async), 64 21 (Start IR Load), the WAV unchanged as SOURCE.WAV, 64 27 <slot:2> <name, 9
    characters> (Analyze IR: the pedal makes the IR), flush, 53. `slot` counts from 0 over all
    120 IR slots (36 = the first USER slot)."""
    dev.request_ack([*HDR, 0x52])
    try:
        dev.request_ack([*HDR, 0x64, 0x21])
        delete(dev, "SOURCE.WAV")
        write_file(dev, "SOURCE.WAV", wav)
        label = name.encode("ascii", "replace")[:9]
        dev.request_ack([*HDR, 0x64, 0x27, *to7(slot, 2), *label], timeout=FLUSH_TIMEOUT)
        _cmd(dev, [0x09], timeout=FLUSH_TIMEOUT)
    finally:
        dev.request_ack([*HDR, 0x53])


def memory_share(space_reply):
    """Used Memory from a `60 04 29` reply: 1 - free / total (as B6.memory_usage)."""
    if space_reply is None or len(space_reply) < 20:
        return None
    total, free = from7(space_reply[10:15]), from7(space_reply[15:20])
    return 1 - free / total if total and free <= total else None
