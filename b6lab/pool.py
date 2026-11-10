"""Guitar Lab's Patch Pool: patches kept on the computer, in groups.

From the decompiled Mac binary (analysis/ui-trace/classes/PatchPoolComponent.c, pool-add.c,
pool-patch.c, pool-file.c):
- the pool lives in <Documents>/ZOOM Guitar Lab/Patches (FUN_10004d9c0: userDocumentsDirectory);
  each patch is a file "<name>-<milliseconds>.zptc" there (FUN_100044be0), and the tree is
  PatchPool.db, a JUCE ValueTree in its binary stream format (FUN_100042b50 / FUN_100042c80);
- the tree: "PoolRoot" (name "root", GroupCount) holding "PatchGroup" (name, isBackup) and
  "Patch" (name, filename) nodes; a group holds patches;
- adding one patch puts it in the given group (or the root); several patches make a new group,
  "New Patch Group <GroupCount>" (GroupCount then goes up), or for Backup All
  "Backup_<device>_<%Y%m%d_%H_%M>" with isBackup = 1 (FUN_100045130).
"""
import io
import re
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from b6lab import ptcf

DEFAULT_ROOT = Path.home() / "Documents" / "ZOOM Guitar Lab" / "Patches"
DB_NAME = "PatchPool.db"

# juce::var stream markers
_INT, _TRUE, _FALSE, _DOUBLE, _STRING, _INT64, _UNDEFINED = 1, 2, 3, 4, 5, 6, 9


@dataclass
class Node:
    """A juce::ValueTree: type, properties (in order) and children."""
    type: str
    props: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def get(self, name, default=None):
        return self.props.get(name, default)


# ---- JUCE stream format ------------------------------------------------------------------
def _write_compressed_int(out, value):
    """juce::OutputStream::writeCompressedInt."""
    n = abs(int(value))
    data = b""
    while n:
        data += bytes([n & 0xFF])
        n >>= 8
    out.write(bytes([len(data) | (0x80 if value < 0 else 0)]) + data)


def _read_compressed_int(inp):
    head = inp.read(1)[0]
    n = head & 0x7F
    if n > 4:
        raise ValueError("bad compressed int")
    value = int.from_bytes(inp.read(n), "little") if n else 0
    return -value if head & 0x80 else value


def _write_string(out, s):
    out.write(s.encode("utf-8") + b"\0")


def _read_string(inp):
    buf = bytearray()
    while True:
        b = inp.read(1)
        if not b:
            raise ValueError("unterminated string")
        if b == b"\0":
            return buf.decode("utf-8", "replace")
        buf += b


def _write_var(out, v):
    if v is None:
        _write_compressed_int(out, 0)
    elif isinstance(v, bool):
        _write_compressed_int(out, 1)
        out.write(bytes([_TRUE if v else _FALSE]))
    elif isinstance(v, int) and -2 ** 31 <= v < 2 ** 31:
        _write_compressed_int(out, 5)
        out.write(bytes([_INT]) + struct.pack("<i", v))
    elif isinstance(v, int):
        _write_compressed_int(out, 9)
        out.write(bytes([_INT64]) + struct.pack("<q", v))
    elif isinstance(v, float):
        _write_compressed_int(out, 9)
        out.write(bytes([_DOUBLE]) + struct.pack("<d", v))
    else:
        data = str(v).encode("utf-8") + b"\0"
        _write_compressed_int(out, len(data) + 1)
        out.write(bytes([_STRING]) + data)


def _read_var(inp):
    n = _read_compressed_int(inp)
    if n <= 0:
        return None
    data = inp.read(n)
    marker, body = data[0], data[1:]
    if marker == _INT:
        return struct.unpack("<i", body[:4])[0]
    if marker == _TRUE:
        return True
    if marker == _FALSE:
        return False
    if marker == _DOUBLE:
        return struct.unpack("<d", body[:8])[0]
    if marker == _STRING:
        return body.split(b"\0", 1)[0].decode("utf-8", "replace")
    if marker == _INT64:
        return struct.unpack("<q", body[:8])[0]
    return None


def write_tree(node, out):
    """juce::ValueTree::writeToStream."""
    _write_string(out, node.type)
    _write_compressed_int(out, len(node.props))
    for name, value in node.props.items():
        _write_string(out, name)
        _write_var(out, value)
    _write_compressed_int(out, len(node.children))
    for child in node.children:
        write_tree(child, out)


def read_tree(inp):
    """juce::ValueTree::readFromStream."""
    node = Node(_read_string(inp))
    for _ in range(_read_compressed_int(inp)):
        name = _read_string(inp)
        node.props[name] = _read_var(inp)
    for _ in range(_read_compressed_int(inp)):
        node.children.append(read_tree(inp))
    return node


def to_bytes(node):
    out = io.BytesIO()
    write_tree(node, out)
    return out.getvalue()


def from_bytes(data):
    return read_tree(io.BytesIO(data))


# ---- the pool ----------------------------------------------------------------------------
def _legal(name):
    """A file-name-safe version of a patch name (juce::File::createLegalFileName); spaces stay."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name) or "Patch"


class PatchPool:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.tree = Node("PoolRoot", {"name": "root", "GroupCount": 1})
        self.load()

    @property
    def db(self):
        return self.root / DB_NAME

    def load(self):
        if self.db.is_file():
            try:
                self.tree = from_bytes(self.db.read_bytes())
            except (ValueError, IndexError, UnicodeDecodeError):
                pass  # unreadable: start empty, never overwrite before the next change
        return self.tree

    def save(self):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.db.with_suffix(".tmp")
        tmp.write_bytes(to_bytes(self.tree))
        tmp.replace(self.db)

    # files
    @staticmethod
    def patch_name(data):
        """The name as stored in the patch, trailing spaces kept (Guitar Lab: "SVT Drive ")."""
        p = ptcf.parse(data)
        raw = p.name_raw.split(b"\0", 1)[0] if p.name_raw else p.name.encode()
        return raw.decode("ascii", "replace")

    def _write_patch_file(self, data):
        """FUN_100044be0: "<name>-<milliseconds>.zptc" (name with its spaces), "_2", "_3" ...
        when taken (seen in Guitar Lab's pool); the file holds the patch's used bytes."""
        from b6lab.device import used_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        base = f"{_legal(self.patch_name(data))}-{int(time.time() * 1000)}"
        path = self.root / f"{base}.zptc"
        n = 2
        while path.exists():
            path = self.root / f"{base}_{n}.zptc"
            n += 1
        path.write_bytes(used_bytes(bytes(data)))
        return path

    def patch_node(self, data):
        """FUN_1000449f0 / FUN_100043450: store the file, return its "Patch" node."""
        path = self._write_patch_file(data)
        return Node("Patch", {"name": self.patch_name(data), "filename": path.name})

    def data(self, node):
        """The patch bytes of a "Patch" node."""
        return (self.root / node.get("filename", "")).read_bytes()

    # adding (FUN_100045130)
    def add(self, patches, group=None, index=-1, backup=False, device="B6", name=""):
        """Add patch bytes. One patch: into `group` (a "PatchGroup" node) or the root, at
        `index`. Several: a new group, inserted at `index` of the root. Returns the new node."""
        patches = [bytes(p) for p in patches]
        if len(patches) == 1 and not backup:
            node = self.patch_node(patches[0])
            parent = group if group is not None else self.tree
            self._insert(parent, node, index)
            self.save()
            return node
        props = {}
        if backup:
            props["name"] = name or f"Backup_{device}_{datetime.now():%Y%m%d_%H_%M}"
            props["isBackup"] = 1
        else:
            if not name:
                count = int(self.tree.get("GroupCount", 1))
                self.tree.props["GroupCount"] = count + 1
                name = f"New Patch Group {count}"
            props["name"] = name
        node = Node("PatchGroup", props)
        for data in patches:
            node.children.append(self.patch_node(data))
        self._insert(self.tree, node, index)
        self.save()
        return node

    @staticmethod
    def _insert(parent, node, index):
        if index is None or index < 0 or index > len(parent.children):
            parent.children.append(node)
        else:
            parent.children.insert(index, node)

    def remove(self, node):
        """Take a node out of the tree (its files stay, as Guitar Lab's undo needs them)."""
        def walk(parent):
            for i, child in enumerate(parent.children):
                if child is node:
                    del parent.children[i]
                    return True
                if walk(child):
                    return True
            return False
        if walk(self.tree):
            self.save()

    def patches_of(self, node):
        """The patch bytes under a node (a group: its patches in order; a patch: itself)."""
        if node.type == "Patch":
            return [self.data(node)]
        return [self.data(c) for c in node.children if c.type == "Patch"]
