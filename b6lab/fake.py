"""In-memory stand-in for the B6 transport, for tests and offline use."""
import struct

from b6lab import ptcf
from b6lab.midi import SLOT_SIZE


class FakeB6:
    def __init__(self, slots):
        self.slots = [bytes(s).ljust(SLOT_SIZE, b"\0") for s in slots]
        self.fail_next_write = False
        self.timeout_next = False
        self.selected = 0
        self.edit = self.slots[0]  # edit buffer: the selected patch plus live changes
        self.type_changes = []     # (position, fx_id) of change_type calls, for tests
        self.chain_edits = []      # ("insert" | "delete", position), for tests
        self.stores = []           # slots of store_edit calls (64 0D), for tests
        self.auto_saves = []       # set_auto_save calls, for tests
        self.effect_ops = []       # ("remove" | "install", base), for tests
        self.tempos = []           # set_tempo calls, for tests
        self.moves = []            # slots written by move_patches, for tests
        self.ir_imports = []       # (slot, name, size) of import_ir calls, for tests
        self.tuner_calls = []      # tuner(on) calls, for tests
        self.tuner_queue = []      # (note, pitch) readings the "pedal" sends next
        self.incoming_sysex = []   # messages the "pedal" sends on its own (sync mode), for tests
        self.incoming_channel = []
        self.sync = False
        from pathlib import Path as _P
        _flst = _P(__file__).resolve().parents[1] / "pedal-files" / "FLST_SEQ.ZT2"
        self.effect_list = _flst.read_bytes() if _flst.is_file() else None
        self.files = {}            # module / icon files on the pedal, when tests put them there
        self.presses = []          # positions of press_effect calls, for tests
        self.params_sent = []      # (position, module, index, value) of set_param calls
        self.closed = False

    def _check_timeout(self):
        if self.timeout_next:
            self.timeout_next = False
            raise TimeoutError("no SysEx reply from the pedal")

    def identity(self):
        self._check_timeout()
        return bytes([0x7E, 0x00, 0x06, 0x02, 0x52, 0x6E, 0x00, 0x00, 0x00, 0x31, 0x2E, 0x30, 0x30])

    def patch_count(self):
        self._check_timeout()
        return len(self.slots)

    def _check_slot(self, slot):
        if not 0 <= slot < min(240, len(self.slots)):
            raise IndexError(f"slot {slot} out of range")

    def read_slot(self, slot):
        self._check_slot(slot)
        self._check_timeout()
        return self.slots[slot]

    def write_slot(self, slot, data):
        self._check_slot(slot)
        self._check_timeout()
        if self.fail_next_write:
            self.fail_next_write = False
            raise IOError("pedal rejected the write (code 0x0A)")
        if len(data) > SLOT_SIZE:
            raise ValueError(f"patch is {len(data)} bytes, pedal slot holds {SLOT_SIZE}")
        data = bytes(data)
        # Like the real pedal: only the PTCF used length is replaced, the tail keeps old content.
        used = struct.unpack_from("<I", data, 4)[0] if len(data) >= 8 else len(data)
        used = min(used, len(data))
        old = self.slots[slot]
        self.slots[slot] = data[:used] + old[used:]

    def read_edit(self):
        self._check_timeout()
        return self.edit

    def memory_usage(self):
        """Like the pedal's FFS Space answer; None (unknown) unless a test sets self.memory."""
        if getattr(self, "memory", None) is None:
            raise NotImplementedError("no memory figure")
        return self.memory

    def selected_slot(self):
        self._check_timeout()
        return self.selected

    def select_slot(self, slot):
        self.selected = slot
        self.edit = self.slots[slot]

    def set_param(self, position, module, index, value):
        """Like the pedal: sets a knob of the effect at entry `module` in the edit buffer."""
        self._check_timeout()
        self.params_sent.append((position, module, index, value))
        p = ptcf.parse(self.edit)
        if module < len(p.effects) and not p.effects[module].is_tail:
            ptcf.set_param(p, module, index, value)
            self.edit = ptcf.encode(p).ljust(SLOT_SIZE, b"\0")

    def tuner(self, on):
        self._check_timeout()
        self.tuner_calls.append(bool(on))

    def enter_sync(self):
        self.sync = True

    def leave_sync(self):
        self.sync = False

    def poll_messages(self):
        """What the "pedal" sends on its own: queued messages, tuner readings as CC 98 / 99."""
        sx, ch = list(self.incoming_sysex), list(self.incoming_channel)
        self.incoming_sysex, self.incoming_channel = [], []
        for note, pitch in self.tuner_queue:
            ch += [bytes([0xB0, 98, note]), bytes([0xB0, 99, pitch])]
        self.tuner_queue = []
        return sx, ch

    def calibration(self):
        return 440

    def set_tempo(self, bpm):
        self._check_timeout()
        self.tempos.append(int(bpm))

    def change_type(self, position, fx_id):
        self._check_timeout()
        self.type_changes.append((position, fx_id))
        p = ptcf.parse(self.edit)
        ptcf.set_type(p, position, fx_id)
        self.edit = ptcf.encode(p).ljust(SLOT_SIZE, b"\0")

    # effects on the pedal: FLST_SEQ.ZT2 and the module / icon files (b6lab/ffs.py)
    def read_effect_list(self):
        self._check_timeout()
        if self.effect_list is None:
            raise OSError("no effect list")
        return self.effect_list

    def read_file(self, name):
        self._check_timeout()
        if name not in self.files:
            raise OSError(f"{name} not found")
        return self.files[name]

    def remove_effect(self, base, effect_list):
        from b6lab import ffs
        self._check_timeout()
        self.effect_ops.append(("remove", base))
        for ext in (".ZD2", ".ZIC"):
            self.files.pop(base + ext, None)
        self.effect_list = ffs.set_installed(effect_list, base + ".ZD2", False)
        return self.effect_list, None

    def install_effect(self, base, zd2, zic, effect_list):
        from b6lab import ffs
        self._check_timeout()
        self.effect_ops.append(("install", base))
        self.files[base + ".ZD2"], self.files[base + ".ZIC"] = bytes(zd2), bytes(zic)
        self.effect_list = ffs.set_installed(effect_list, base + ".ZD2", True)
        return self.effect_list, None

    def move_effect(self, src, dst):
        self._check_timeout()
        self.chain_edits.append(("move", src, dst))
        p = ptcf.parse(self.edit)
        if ptcf.move_entry(p, src, dst):
            self.edit = ptcf.encode(p).ljust(SLOT_SIZE, b"\0")

    def move_patches(self, moved, writes):
        self._check_timeout()
        self.moves.append(sorted(s for s, _ in writes))
        self.edit = bytes(moved).ljust(SLOT_SIZE, b"\0")
        for slot, data in writes:
            self.slots[slot] = bytes(data).ljust(SLOT_SIZE, b"\0")

    def import_ir(self, slot, name, wav):
        self._check_timeout()
        self.ir_imports.append((slot, name[:9], len(wav)))

    def store_edit(self, slot):
        """Patch Save: the pedal stores its edit buffer into `slot`."""
        self._check_slot(slot)
        self._check_timeout()
        self.stores.append(slot)
        self.slots[slot] = bytes(self.edit).ljust(SLOT_SIZE, b"\0")

    def insert_effect(self, position):
        self._check_timeout()
        self.chain_edits.append(("insert", position))
        p = ptcf.parse(self.edit)
        if ptcf.insert_entry(p, position):
            self.edit = ptcf.encode(p).ljust(SLOT_SIZE, b"\0")

    def set_auto_save(self, on):
        self._check_timeout()
        self.auto_saves.append(bool(on))

    def delete_effect(self, position):
        self._check_timeout()
        self.chain_edits.append(("delete", position))
        p = ptcf.parse(self.edit)
        if ptcf.delete_entry(p, position):
            self.edit = ptcf.encode(p).ljust(SLOT_SIZE, b"\0")

    def press_effect(self, position):
        """Like the pedal's virtual footswitch: toggles the effect at entry index `position`."""
        self._check_timeout()
        self.presses.append(position)
        p = ptcf.parse(self.edit)
        if position < len(p.effects) and not p.effects[position].is_tail:
            e = p.effects[position]
            ptcf.set_on(p, e.slot, not e.on)
            self.edit = ptcf.encode(p).ljust(SLOT_SIZE, b"\0")

    def close(self):
        self.closed = True
