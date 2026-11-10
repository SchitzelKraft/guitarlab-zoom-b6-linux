"""Guitar Lab's Clipboard: clips (1..4 effects with their settings) kept on the computer.

Recorded from Guitar Lab 7.3 under Wine (2026-11-10, analysis/captures/20261110-virtual-clip):
- the clips live in <Documents>/ZOOM Guitar Lab/Clipboard, shared with Guitar Lab: one file
  "<name>_<milliseconds>.zpcd" per clip, and Clips.db, a JUCE ValueTree "root" holding a
  "ClipboardItem" (filename, usage = number of chain entries) per clip, in display order;
- a .zpcd file (writer FUN_1002af980, reader FUN_1002b0960, analysis/ui-trace/CLIPBOARD.md):
  u32 2 and 8 bytes `00 20 00 00 00 00 00 00` (device masks: PTCF version and header
  0x10..0x17), the name (10 bytes, zero padded), u8 entry count, 4 zero bytes, u32 entry bytes,
  the 24-byte EDTB entries unchanged (the second half of a double-width effect included), u8
  id count, then u32 per entry: the effect ID (1 for a second half), which go back into the
  PTCF ID table when the clip is pasted.
"""
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from b6lab import ptcf
from b6lab.pool import Node, from_bytes, to_bytes, _legal

DEFAULT_ROOT = Path.home() / "Documents" / "ZOOM Guitar Lab" / "Clipboard"
DB_NAME = "Clips.db"
HEADER = struct.pack("<I", 2) + bytes([0x00, 0x20, 0, 0, 0, 0, 0, 0])
NAME_LEN = 10


@dataclass
class Clip:
    name: str
    entries: list = field(default_factory=list)   # 24-byte EDTB entries
    ids: list = field(default_factory=list)       # effect ID per entry (1 for a second half)
    mask_a: int = 2          # u32 at 0x00: the patch format mask (PTCF version)
    mask_b: int = 0x2000     # u64 at 0x04: the device mask (PTCF header 0x10..0x17)

    def effects(self):
        """ptcf.Effect objects of the entries (for icons and inserting)."""
        out = []
        for i, raw in enumerate(self.entries):
            v = int.from_bytes(raw, "little")
            fx_id = (v >> 1) & 0x1FFFFFFF
            out.append(ptcf.Effect(slot=i, fx_id=fx_id, on=bool(v & 1), params=[], is_tail=fx_id == 1, raw=v))
        return out


def encode(clip):
    name = clip.name.encode("ascii", "replace")[:NAME_LEN].ljust(NAME_LEN, b"\0")
    n = len(clip.entries)
    body = b"".join(bytes(e) for e in clip.entries)
    out = struct.pack("<IQ", clip.mask_a, clip.mask_b) + name + bytes([n]) + bytes(4) + struct.pack("<I", len(body)) + body
    return out + bytes([len(clip.ids)]) + struct.pack(f"<{len(clip.ids)}I", *clip.ids)


def decode(data):
    data = bytes(data)
    if len(data) < 0x1F:
        raise ValueError("not a clip file")
    mask_a, mask_b = struct.unpack_from("<IQ", data, 0)
    name = data[0x0C:0x16].split(b"\0", 1)[0].decode("ascii", "replace")
    size = struct.unpack_from("<I", data, 0x1B)[0]
    n = size // ptcf.ENTRY
    if 0x1F + size + 1 > len(data):
        raise ValueError("truncated clip file")
    entries = [data[0x1F + k * ptcf.ENTRY:0x1F + (k + 1) * ptcf.ENTRY] for k in range(n)]
    p = 0x1F + size
    count = data[p]
    if p + 1 + 4 * count > len(data):
        raise ValueError("truncated clip file")
    ids = list(struct.unpack_from(f"<{count}I", data, p + 1))
    return Clip(name, entries, ids, mask_a, mask_b)


# What the B6 reports at connect (recorded replies, decoded in analysis/ui-trace/CLIP-EXTRA.md):
# Support Patch (48 -> 47): device + 0x6568 = 0x2, + 0x6520 = bit 13; Support ZDL (55 -> 54):
# + 0x6518 = 0x8, + 0x64d0 = bit 32, the 64-byte table at + 0x64d8 with byte 32 = 0x80, + 0x651c = 4.
B6_PATCH_A, B6_PATCH_B = 0x2, 0x2000
B6_ZDL_FLAGS, B6_ZDL_MASK, B6_ZDL_LEVEL = 0x8, 1 << 32, 4
B6_ZDL_VERSIONS = bytes(32) + bytes([0x80]) + bytes(31)


def usable(clip):
    """FUN_1002b06b0: False when Guitar Lab draws the clip at 30 % and refuses its drop. Tests
    the clip's masks and every effect's ZD2 masks against what the pedal reported; whether the
    effect is installed is not part of it. An id the effect list does not know (other than -1)
    is dropped when the file is read (FUN_1002b0960), so it does not count."""
    if not clip.mask_a & B6_PATCH_A or not clip.mask_b & B6_PATCH_B:
        return False
    from b6lab import effects
    for fx_id in clip.ids:
        if fx_id in (0, 1):
            continue
        if fx_id == 0xFFFFFFFF:
            return False
        masks = effects.zdl_masks(fx_id)
        if masks is None:
            continue
        flags, mask, versions, level = masks
        m = mask & B6_ZDL_MASK
        if not flags & B6_ZDL_FLAGS or not m or level > B6_ZDL_LEVEL:
            return False
        if not any(m >> i & 1 and B6_ZDL_VERSIONS[i] >= versions[i] for i in range(64)):
            return False
    return True


def clip_from_patch(patch, first, count, name):
    """A clip of `count` entries of `patch` from entry `first` (FUN_100067550; the second
    half of a double-width effect counts as an entry)."""
    effects = patch.effects[first:first + count]
    entries = [e.raw.to_bytes(ptcf.ENTRY, "little") for e in effects]
    ids = list(patch.effect_ids[first:first + count])
    return Clip(name, entries, ids)


def insert_clip(patch, clip, pos):
    """Put the clip's entries into the patch at entry `pos`; False when they do not fit
    (ptcf.MAX_ENTRIES) or `pos` is inside a double-width effect."""
    effects = clip.effects()
    if len(patch.effects) + len(effects) > ptcf.MAX_ENTRIES or not 0 <= pos <= len(patch.effects):
        return False
    if pos < len(patch.effects) and patch.effects[pos].is_tail:
        return False
    patch.effects[pos:pos] = effects
    patch.effect_ids[pos:pos] = list(clip.ids)
    ptcf._renumber(patch)
    return True


class Clipboard:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.tree = Node("root")
        self.load()

    @property
    def db(self):
        return self.root / DB_NAME

    def load(self):
        if self.db.is_file():
            try:
                self.tree = from_bytes(self.db.read_bytes())
            except (ValueError, IndexError, UnicodeDecodeError):
                pass
        return self.tree

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.db.with_suffix(".tmp")
        tmp.write_bytes(to_bytes(self.tree))
        tmp.replace(self.db)

    @property
    def items(self):
        return [c for c in self.tree.children if c.type == "ClipboardItem"]

    def clip(self, node):
        return decode((self.root / node.get("filename", "")).read_bytes())

    def next_name(self):
        """"Clip " + (rows in Clips.db + 1) (FUN_100067550): not a counter, so a name can come
        back after a delete."""
        return f"Clip {len(self.items) + 1}"

    def add(self, clip):
        self.root.mkdir(parents=True, exist_ok=True)
        base = f"{_legal(clip.name)}_{int(time.time() * 1000)}"
        path = self.root / f"{base}.zpcd"
        n = 2
        while path.exists():
            path = self.root / f"{base}_{n}.zpcd"
            n += 1
        path.write_bytes(encode(clip))
        node = Node("ClipboardItem", {"filename": path.name, "usage": len(clip.entries)})
        self.tree.children.append(node)
        self.save()
        return node

    def import_file(self, src):
        """A .zpcd dropped from the file manager (filesDropped FUN_10026bba0): copied to
        "<source name>_<ms>.zpcd" here (the original stays) and appended to Clips.db with usage =
        its number of ids. No check, no message (also not when the copy fails: None)."""
        import shutil
        src = Path(src)
        self.root.mkdir(parents=True, exist_ok=True)
        dest = self.root / f"{src.stem}_{int(time.time() * 1000)}.zpcd"
        try:
            shutil.copyfile(src, dest)
        except OSError:
            return None
        try:
            usage = len(decode(dest.read_bytes()).ids)
        except (OSError, ValueError, struct.error):
            usage = 0
        node = Node("ClipboardItem", {"filename": dest.name, "usage": usage})
        self.tree.children.append(node)
        self.save()
        return node

    def export_copy(self, node):
        """Dragging a clip out of the window (shouldDropFilesWhenDraggedExternally
        FUN_1000672c0): a copy in Clipboard/Temp named after the clip, JUCE
        getNonexistentChildFile(name, ".zpcd", false): "Clip 1.zpcd", then "Clip 1_2.zpcd"..."""
        import shutil
        temp = self.root / "Temp"
        temp.mkdir(parents=True, exist_ok=True)
        try:
            name = self.clip(node).name
        except (OSError, ValueError, struct.error):
            name = Path(node.get("filename", "clip")).stem
        dest, number = temp / f"{name}.zpcd", 1
        while dest.exists():
            number += 1
            sep = "_" if name[-1:].isdigit() else ""
            dest = temp / f"{name}{sep}{number}.zpcd"
        try:
            shutil.copyfile(self.root / node.get("filename", ""), dest)
        except OSError:
            pass
        return dest

    def remove(self, node):
        """"Delete" (FUN_10026ab10): the file goes, the item goes, Clips.db is rewritten."""
        if node in self.tree.children:
            (self.root / node.get("filename", "")).unlink(missing_ok=True)
            self.tree.children.remove(node)
            self.save()

    def rename(self, node, name):
        """FUN_10026bf40: only the name inside the .zpcd changes (not the file name)."""
        clip = self.clip(node)
        clip.name = name
        (self.root / node.get("filename")).write_bytes(encode(clip))

    def move(self, node, index):
        """Reorder (FUN_10026b100): moveChild(from, to - (from < to)); `index` is the final one."""
        children = self.tree.children
        children.remove(node)
        children.insert(max(0, min(index, len(children))), node)
        self.save()
