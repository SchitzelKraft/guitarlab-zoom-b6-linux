"""Raw ALSA MIDI transport for the Zoom B6 (no dependencies)."""
import errno
import os
import re
import select
import time
import zlib

from b6lab.codec import pack7, unpack7, to7, from7, packed_len

HDR = bytes([0x52, 0x00, 0x6E])
SLOT_SIZE = 808
# Enable UI (64 0F) after a write outside sync mode: the B6 does not ack it, and sent right
# after the write ack it was lost 4 times on 2026-11-12, leaving the pedal locked (screen and
# switches dead, MIDI still answering) until a later 64 0F unlocked it. Wait, then send it twice.
ENABLE_UI_DELAY = 0.3
ENABLE_UI_SENDS = 2


class DeviceBusy(Exception):
    """The MIDI device is open in another program."""


class NotConnected(Exception):
    """No ZOOM B6 sound card found."""


def _read_cards():
    with open("/proc/asound/cards") as f:
        return f.read()


def find_device():
    """Path of the B6 raw MIDI device, or raise NotConnected."""
    try:
        text = _read_cards()
    except OSError:
        raise NotConnected("cannot read /proc/asound/cards")
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+\[.*\]:.*ZOOM B6", line)
        if m:
            path = f"/dev/snd/midiC{m.group(1)}D0"
            if os.path.exists(path):
                return path
    raise NotConnected("ZOOM B6 not found (is it connected and switched on?)")


class B6:
    sync = False  # sync mode ("PC mode", 50 .. 51), as Guitar Lab keeps it for its session

    def __init__(self, path=None, fd=None):
        if fd is None:
            try:
                fd = os.open(path or find_device(), os.O_RDWR | os.O_NONBLOCK)
            except OSError as e:
                if e.errno == errno.EBUSY:
                    raise DeviceBusy(str(e)) from e
                raise
        self.fd = fd
        self._pending = []
        self.drain()

    @classmethod
    def open(cls, path=None):
        return cls(path)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def drain(self):
        self._pending.clear()
        while select.select([self.fd], [], [], 0.05)[0]:
            if not os.read(self.fd, 4096):
                break
        self._sx_q, self._ch_q, self._sx_buf, self._ch_buf = [], [], None, []

    def _write_all(self, payload, timeout=5.0):
        """Write an entire MIDI message, including on a nonblocking raw MIDI port."""
        data = memoryview(bytes(payload))
        end = time.monotonic() + timeout
        while data:
            remaining = end - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError("timed out sending MIDI message")
            try:
                count = os.write(self.fd, data)
            except BlockingIOError:
                continue
            if count <= 0:
                raise OSError("MIDI device accepted no data")
            data = data[count:]

    def send(self, payload):
        self._write_all(bytes([0xF0]) + bytes(payload) + bytes([0xF7]))

    def send_raw(self, payload):
        self._write_all(payload)

    # ---- receiving: one byte parser, two queues (SysEx / channel messages) ----------------
    # In sync mode (50) the pedal mixes SysEx and channel messages on its own; both are kept.
    def _pump(self, timeout):
        """Read what is available (waiting up to `timeout`) and split it into messages."""
        if select.select([self.fd], [], [], max(0.0, timeout))[0]:
            data = os.read(self.fd, 4096)
            if data:
                self._pending.extend(data)
        if not hasattr(self, "_sx_q"):
            self._sx_q, self._ch_q, self._sx_buf, self._ch_buf = [], [], None, []
        for x in self._pending:
            if x >= 0xF8:                     # realtime bytes may appear anywhere
                continue
            if x == 0xF0:
                self._sx_buf = bytearray()
            elif x == 0xF7:
                if self._sx_buf is not None:
                    self._sx_q.append(bytes(self._sx_buf))
                self._sx_buf = None
            elif self._sx_buf is not None:
                self._sx_buf.append(x)
            elif x >= 0x80:
                self._ch_buf = [x]
            elif self._ch_buf:
                self._ch_buf.append(x)
            if self._ch_buf and len(self._ch_buf) == (2 if self._ch_buf[0] & 0xF0 in (0xC0, 0xD0) else 3):
                self._ch_q.append(bytes(self._ch_buf))
                self._ch_buf = []
        self._pending.clear()

    def recv_sysex(self, timeout=3.0):
        end = time.monotonic() + timeout
        while True:
            self._pump(0)
            if self._sx_q:
                return self._sx_q.pop(0)
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no SysEx reply from the pedal")
            self._pump(min(remaining, 0.1))
            if self._sx_q:
                return self._sx_q.pop(0)

    def request(self, payload, expect, timeout=3.0):
        self.send(payload)
        end = time.monotonic() + timeout
        while True:
            msg = self.recv_sysex(max(0.1, end - time.monotonic()))
            if msg[:3] == HDR and msg[3] == 0x00 and len(msg) >= 5:
                raise RuntimeError(f"pedal returned error 0x{msg[4]:02X}")
            if msg[:len(expect)] == bytes(expect):
                return msg

    def request_ack(self, payload, timeout=3.0):
        """Send a command whose reply is the Mac app's Respondence message."""
        self.send(payload)
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no acknowledgement from the pedal")
            msg = self.recv_sysex(remaining)
            if len(msg) >= 5 and msg[:4] == HDR + b"\x00":
                if msg[4] != 0:
                    raise RuntimeError(f"pedal returned error 0x{msg[4]:02X}")
                return msg

    def identity(self):
        return self.request([0x7E, 0x7F, 0x06, 0x01], [0x7E])

    def patch_info(self):
        m = self.request([*HDR, 0x44], [*HDR, 0x43])
        return {"count": m[4] | m[5] << 7, "size": m[6] | m[7] << 7, "raw": m.hex(" ")}

    def patch_count(self):
        return self.patch_info()["count"]

    def patch_capabilities(self):
        """Read Guitar Lab's Support Patch capability flags (48 -> 47).

        The Mac application's response handler reads a five-byte 7-bit integer
        first. The remaining fields are retained until their meanings are known.
        """
        msg = self.request([*HDR, 0x48], [*HDR, 0x47])
        if len(msg) < 9 or any(byte > 0x7F for byte in msg[4:9]):
            raise ValueError("Support Patch: invalid capability flags")
        flags = from7(msg[4:9])
        if flags > 0xFFFFFFFF:
            raise ValueError("Support Patch: capability flags exceed 32 bits")
        return {"flags": flags, "raw": bytes(msg)}

    def product_info(self):
        """Read the product information used by Guitar Lab's editor viewport."""
        msg = self.request([*HDR, 0x64, 0x11], [*HDR, 0x64, 0x10])
        if len(msg) < 10 or any(byte > 0x7F for byte in msg[5:10]):
            raise ValueError("FX Product Info: truncated or invalid reply")
        # The original handler stores the second single-byte field at 0x640b;
        # FUN_1002ab1b0 uses that field as the number of visible positions.
        return {"visible_width": msg[8], "raw": bytes(msg)}

    def global_info(self):
        """Read the Mac app's global-data record, including the tempo field."""
        msg = self.request([*HDR, 0x64, 0x0A], [*HDR, 0x64, 0x09])
        if len(msg) < 7 or any(byte > 0x7F for byte in msg[5:7]):
            raise ValueError("FX Global Data: truncated or invalid tempo")
        # FUN_100033c60 case 0x640A: indexes 7.. are global params 0x0A, 0x0B, 0x0C (tuner
        # calibration), 0x0D, 0x0E, 0x0F (AUTO SAVE, any non-zero = on), 0x10..0x13
        auto = bool(msg[12]) if len(msg) > 12 else False
        return {"tempo": from7(msg[5:7]), "auto_save": auto, "raw": bytes(msg)}

    @staticmethod
    def _decode(m, off, what):
        size = from7(m[off:off + 2])
        n = packed_len(size)
        packed, tail = m[off + 2:off + 2 + n], m[off + 2 + n:off + 7 + n]
        data = unpack7(packed)[:size]
        want = from7(tail)
        got = zlib.crc32(data) ^ 0xFFFFFFFF
        if len(data) != size or want != got:
            raise ValueError(f"{what}: checksum mismatch (got {got:08x}, want {want:08x})")
        return data

    def read_patch(self, slot):
        bank, pos = divmod(slot, 4)
        m = self.request([*HDR, 0x46, 0, 0, bank, 0, pos, 0], [*HDR, 0x45, 0, 0, bank, 0, pos, 0])
        return self._decode(m, 10, f"slot {slot}"), m

    def read_slot(self, slot):
        return self.read_patch(slot)[0]

    def write_slot(self, slot, data, timeout=5.0):
        """Patch write as Guitar Lab sends it: `64 0E` (Disable UI), the `45` write, `64 0F`
        (Enable UI). Outside sync mode the B6 answers only the `45` (tested on Z-103,
        captures/20261109-save-test.json); Guitar Lab, in sync mode, gets an ack for each."""
        if self.sync:   # sync mode: 64 0F is acknowledged; 64 0E maybe (two acks for three steps
            # in Guitar Lab's table, three seen once), so it may stay unanswered
            self.soft_ack([*HDR, 0x64, 0x0E])
            try:
                write_patch(self, slot, data, timeout=timeout)
            finally:
                self.request_ack([*HDR, 0x64, 0x0F])
            return
        self.send([*HDR, 0x64, 0x0E])
        try:
            write_patch(self, slot, data, timeout=timeout)
        finally:
            for _ in range(ENABLE_UI_SENDS):
                time.sleep(ENABLE_UI_DELAY)
                self.send([*HDR, 0x64, 0x0F])

    def store_edit(self, slot):
        """Patch Save (`64 0D 00 00 <bank> 00 <pos> 00`): Guitar Lab's SAVE first asks the pedal
        to store its edit buffer into `slot`, then writes the patch itself (write_slot), so the
        write decides what is stored. No reply outside sync mode (tested)."""
        bank, pos = divmod(slot, 4)
        if self.sync:   # answered with the stored patch (45) and bank select / program change
            self.request([*HDR, 0x64, 0x0D, 0, 0, bank, 0, pos, 0], [*HDR, 0x45], timeout=10.0)
            time.sleep(0.1)
            self.drain()
            return
        self.send([*HDR, 0x64, 0x0D, 0, 0, bank, 0, pos, 0])
        time.sleep(0.1)

    def read_edit(self):
        """Current edit buffer: 64 13 -> 64 12 01 <size:2> <packed> <crc:5>, then ack 00 00.

        Guitar Lab acknowledges every edit-buffer dump with `52 00 6E 00 00` (recorded and
        verified on the B6); reading without the ack preceded two of the pedal's freezes."""
        m = self.request([*HDR, 0x64, 0x13], [*HDR, 0x64, 0x12])
        self.send([*HDR, 0x00, 0x00])
        return self._decode(m, 6, "edit buffer")

    def press_effect(self, position):
        """Click the effect at chain `position`: press and release of Guitar Lab's virtual
        footswitch (module 0x5A), see b6lab/live.py. Toggles the effect in the edit buffer."""
        for value in (1, 0):
            self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x01, *to7(position, 5)])
            self.send([*HDR, 0x64, 0x20, 0x00, 0x5A, 0x00, *to7(value, 5)])
            time.sleep(0.05)
        self.drain()

    def set_param(self, position, module, index, value):
        """Set knob `index` (0-based) of the effect at entry `module` in the edit buffer,
        as Guitar Lab does (see b6lab/live.py); the pedal answers nothing outside sync mode."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x01, *to7(position, 5)])
        self.send([*HDR, 0x64, 0x20, 0x00, module, index + 2, *to7(value, 5)])

    def soft_ack(self, payload, wait=0.3):
        """Send a step whose acknowledgement is not certain (`56` Disable Audio is not
        acknowledged on the B6; `64 0E` unclear) and take an ack only if it comes quickly."""
        self.send(payload)
        try:
            end = time.monotonic() + wait
            while True:
                msg = self.recv_sysex(max(0.01, end - time.monotonic()))
                if msg[:4] == HDR + b"\x00":
                    return msg
        except TimeoutError:
            return None

    def enter_sync(self):
        """`50`: Guitar Lab's first message after the identity, acknowledged with 00 00; the pedal
        then reports patch changes, knobs, footswitches and tuner readings on its own."""
        self.request_ack([*HDR, 0x50])
        self.sync = True

    def leave_sync(self):
        """`51`: Guitar Lab's last message when it closes."""
        self.drain()
        self.request_ack([*HDR, 0x51])
        self.sync = False

    def send_to_edit(self, data):
        """`28 <packed 808 bytes> <crc:5>`: a whole patch into the pedal's edit buffer."""
        data = bytes(data)[:SLOT_SIZE].ljust(SLOT_SIZE, b"\0")
        crc = zlib.crc32(data) ^ 0xFFFFFFFF
        self.request_ack([*HDR, 0x28, *pack7(data), *to7(crc, 5)])

    def move_patches(self, moved, writes):
        """Moving a patch in the list, as Guitar Lab does it (recorded 2026-11-10): 52 (async),
        28 <the moved patch>, 56 (audio off), a 45 write for each shifted slot in ascending
        order, 57 (audio on), 53. Every step is acknowledged."""
        self.request_ack([*HDR, 0x52])
        try:
            self.send_to_edit(moved)
            self.soft_ack([*HDR, 0x56])   # not acknowledged (43 acks for 51 steps: 56 is the one)
            try:
                for slot, data in sorted(writes):
                    write_patch(self, slot, data)
            finally:
                self.request_ack([*HDR, 0x57])
        finally:
            self.request_ack([*HDR, 0x53])

    def move_effect(self, src, dst):
        """Dragging an effect in the chain (recorded): module 100, parameter 9, value bytes
        <from> <to> 0 0 0 - "64 20 00 64 09 00 01 00 00 00" moved the first effect after the
        second. Edit buffer only; waits like change_type before the caller reads it back."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x09, src & 0x7F, dst & 0x7F, 0, 0, 0])
        time.sleep(0.25)

    def import_ir(self, slot, name, wav):
        from b6lab import ffs
        ffs.import_ir(self, slot, name, wav)

    def tuner(self, on):
        """TUNER (recorded from Guitar Lab on the B6, captures/20261109-real-tuner): `64 0B`
        starts the pedal's tuner, `64 0C` stops it; the pedal answers with the same message and
        streams readings as CC 98 (note) / CC 99 (pitch byte)."""
        # The B6 only streams the readings in sync mode ("PC mode", 50), which Guitar Lab (and
        # B6 Lab) keep on for the session; without it the pedal's tuner starts but sends nothing
        # (tried 2026-11-09). Outside sync mode it is switched on around the tuner.
        if not self.sync:
            if on:
                self.request_ack([*HDR, 0x50])
                self.send([*HDR, 0x64, 0x0B])
            else:
                self.send([*HDR, 0x64, 0x0C])
                time.sleep(0.05)
                self.drain()
                self.request_ack([*HDR, 0x51])
            return
        self.send([*HDR, 0x64, 0x0B if on else 0x0C])

    def set_auto_save(self, on):
        """AUTO SAVE (global parameter 0x0F) as Guitar Lab's setter FUN_1002a7ff0 sends it, the
        same path as the tempo: `64 20 00 64 0F <0|1 as five 7-bit bytes>`. Guitar Lab sends it
        only around a clip drop when AUTO SAVE is on (FUN_100067910). From the decompile;
        never captured on the B6."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x0F, *to7(1 if on else 0, 5)])

    def calibration(self):
        """Tuner reference in Hz: global data byte 9 + 435. Checked on the B6 (2026-11-10,
        captures/20261110-calibration.log): 440 Hz = 5, set to 441 on the pedal = 6, back = 5."""
        msg = self.request([*HDR, 0x64, 0x0A], [*HDR, 0x64, 0x09])
        return 435 + msg[9] if len(msg) > 9 else 440

    def set_tempo(self, bpm):
        """Tempo (TAP or a typed BPM), as Guitar Lab sends it (EditorPageComponent FUN_1000658b0
        -> FUN_1002a7ff0 case 2 -> FUN_1002a7890(dev, 100, 2, bpm): "Patch Param Scroll 2",
        0x26403A): module 100 (global), parameter 2, the value as five 7-bit bytes. From the
        decompile; tried on the B6 (captures/20261109-real-b6lab-tap): the pedal follows."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x02, *to7(int(bpm), 5)])

    def change_type(self, position, fx_id):
        """Make the effect at chain entry `position` the effect `fx_id`, as Guitar Lab's TYPE
        picker does (FUN_1002aa550 -> FUN_1002b5200 -> "Patch Param Type Change 2", 0x26403C):
        the position message, then module = entry, paramIx 1, value = effect ID. Edit buffer
        only; the picker's B6 window is one effect wide, so the window start is the entry.
        Recorded from Guitar Lab on the B6 (captures/20261109-real-typechange) and sent by B6 Lab
        on the B6 (captures/20261109-real-b6lab-typechange): the pedal changes the effect and
        sets the knob values itself: each effect type gets the values it last had on the pedal
        (captures/20261109-knob-rule.json). The pedal reports them 65..90 ms after the change
        (before that the edit buffer still holds the old values), so this waits 250 ms before
        the caller reads the edit buffer."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x01, *to7(position, 5)])
        self.send([*HDR, 0x64, 0x20, 0x00, position, 0x01, *to7(fx_id, 5)])
        time.sleep(0.25)

    def insert_effect(self, position):
        """ADD: an empty effect entry at chain entry `position` (recorded from Guitar Lab on the
        B6: `64 20 00 64 07 <pos:5>`; the pedal refuses it when the patch has 6 entries).
        Edit buffer only; waits like change_type before the caller reads it back."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x07, *to7(position, 5)])
        time.sleep(0.25)

    def delete_effect(self, position):
        """DELETE: remove the effect at entry `position` (both halves of a double-width one),
        `64 20 00 64 08 <pos:5>`, recorded from Guitar Lab on the B6. Edit buffer only."""
        self.send([*HDR, 0x64, 0x20, 0x00, 0x64, 0x08, *to7(position, 5)])
        time.sleep(0.25)

    # effects on the pedal (b6lab/ffs.py: recorded from Guitar Lab)
    def read_file(self, name):
        from b6lab import ffs
        return ffs.read_file(self, name)

    def read_effect_list(self):
        """FLST_SEQ.ZT2: which effects are installed (Guitar Lab reads it at connect)."""
        from b6lab import ffs
        return ffs.read_file(self, ffs.LIST)

    def remove_effect(self, base, effect_list):
        from b6lab import ffs
        return ffs.remove_effect(self, base, effect_list)

    def install_effect(self, base, zd2, zic, effect_list):
        from b6lab import ffs
        return ffs.install_effect(self, base, zd2, zic, effect_list)

    def memory_usage(self):
        """Share of the pedal's effect memory in use, as Guitar Lab shows it ("Used Memory").

        FFS Space: `60 29` -> `60 04 29 02 00 08 00 <total:5> <free:5> ...`, then the status
        poll `60 05 00` -> `60 03 ...`, the order Guitar Lab uses for every FFS command
        (recorded from the B6: total 9558330, free 2764840 -> 71 %). Read only."""
        msg = self.request([*HDR, 0x60, 0x29], [*HDR, 0x60, 0x04, 0x29])
        self.request([*HDR, 0x60, 0x05, 0x00], [*HDR, 0x60, 0x03])
        if len(msg) < 20 or any(b > 0x7F for b in msg[10:20]):
            raise ValueError("FFS Space: truncated reply")
        total, free = from7(msg[10:15]), from7(msg[15:20])
        if not total or free > total:
            raise ValueError("FFS Space: implausible sizes")
        return 1 - free / total

    def _recv_channel(self, timeout):
        """Next channel message (status >= 0x80, not SysEx) as bytes."""
        end = time.monotonic() + timeout
        while True:
            self._pump(0)
            if self._ch_q:
                return self._ch_q.pop(0)
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no answer from the pedal")
            self._pump(min(remaining, 0.1))
            if self._ch_q:
                return self._ch_q.pop(0)

    def poll_messages(self):
        """Everything that arrived on its own (sync mode): (sysex list, channel list)."""
        self._pump(0)
        sx, ch = self._sx_q, self._ch_q
        self._sx_q, self._ch_q = [], []
        return sx, ch

    def selected_slot(self, timeout=3.0):
        """The pedal's current patch: `33` (Patch Get Selected) is answered with bank select
        MSB, bank select LSB and program change (recorded from the B6 with Guitar Lab)."""
        self.drain()   # sync mode: earlier bank select / program change echoes must not count
        self.send([*HDR, 0x33])
        bank, end = 0, time.monotonic() + timeout
        while True:
            m = self._recv_channel(max(0.1, end - time.monotonic()))
            if m[0] & 0xF0 == 0xB0 and m[1] == 0x20:
                bank = m[2]
            elif m[0] & 0xF0 == 0xC0:
                return bank * 4 + m[1]

    def select_slot(self, slot):
        """Select a slot: Bank Select MSB=0, LSB=slot//4, Program Change=slot%4.

        Verified on hardware (slots 0, 5, 100): the edit buffer name matches the slot name."""
        bank, pos = divmod(slot, 4)
        self.send_raw([0xB0, 0x00, 0x00])
        self.send_raw([0xB0, 0x20, bank])
        self.send_raw([0xC0, pos])


SEQ_ADDRESS = os.environ.get("B6LAB_SEQ", "ZOOM B6:0")


class SeqB6(B6):
    """The same pedal protocol over the ALSA sequencer instead of raw MIDI.

    Reaches the virtual pedal (vpedal, which has no raw MIDI device) and, as a fallback,
    the real B6's sequencer port. The address can be set with B6LAB_SEQ."""

    def __init__(self, address=SEQ_ADDRESS):
        from b6lab.alsaseq import SeqPort
        try:
            self.seq = SeqPort("B6 Lab", "B6 Lab")
        except OSError as e:
            raise NotConnected(str(e)) from e
        try:
            self.seq.connect(address)
        except LookupError as e:
            self.seq.close()
            raise NotConnected("ZOOM B6 not found (is it connected and switched on?)") from e
        self.fd = None
        self._pending = []
        self._sysex = []
        self._channel = []
        self.drain()

    def close(self):
        if self.seq is not None:
            self.seq.close()
            self.seq = None

    def drain(self):
        self._sysex.clear()
        self._channel.clear()
        while self.seq.read(0.05):
            pass

    def _write_all(self, payload, timeout=5.0):
        payload = bytes(payload)
        self.seq.send(payload[1:-1] if payload[:1] == b"\xf0" else payload)

    def _recv_channel(self, timeout):
        end = time.monotonic() + timeout
        while True:
            if self._channel:
                return self._channel.pop(0)
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no answer from the pedal")
            for m in self.seq.read(min(remaining, 0.1)):
                (self._channel if m[:1] >= b"\x80" else self._sysex).append(m)

    def poll_messages(self):
        for m in self.seq.read(0):
            (self._channel if m[:1] >= b"\x80" else self._sysex).append(m)
        sx, ch = self._sysex, self._channel
        self._sysex, self._channel = [], []
        return sx, ch

    def recv_sysex(self, timeout=3.0):
        end = time.monotonic() + timeout
        while not self._sysex:
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no SysEx reply from the pedal")
            for m in self.seq.read(min(remaining, 0.1)):
                (self._channel if m[:1] >= b"\x80" else self._sysex).append(m)
        return self._sysex.pop(0)


def open_device(path=None):
    """The B6 over raw MIDI, or over the ALSA sequencer when there is no raw MIDI device
    (the virtual pedal). B6LAB_TRANSPORT=seq forces the sequencer."""
    if os.environ.get("B6LAB_TRANSPORT") == "seq":
        return SeqB6()
    try:
        return B6.open(path)
    except NotConnected:
        return SeqB6()


def read_patch(dev, slot):
    """(data, raw SysEx message) of a slot."""
    return dev.read_patch(slot)


def write_patch(dev, slot, data, size=SLOT_SIZE, timeout=5.0):
    """Patch Write: same layout as the Patch Load reply, sent to the pedal.

    Returns the pedal reply; raises IOError on a nonzero reply code."""
    if len(data) > size:
        raise ValueError(f"patch is {len(data)} bytes, pedal slot holds {size}")
    data = bytes(data) + bytes(size - len(data))
    bank, pos = divmod(slot, 4)
    crc = zlib.crc32(data) ^ 0xFFFFFFFF
    dev.drain()
    dev.send([*HDR, 0x45, 0, 0, bank, 0, pos, 0, *to7(size, 2), *pack7(data), *to7(crc, 5)])
    # The ack is `52 00 6E 00 <code>`; other SysEx messages are ignored.
    # Raises TimeoutError if no ack arrives within `timeout` seconds.
    end = time.monotonic() + timeout
    while True:
        reply = dev.recv_sysex(max(0.1, end - time.monotonic()))
        if reply[:3] == HDR and len(reply) >= 5 and reply[3] == 0x00:
            if reply[4] != 0:
                raise IOError(f"pedal rejected the write (code 0x{reply[4]:02X})")
            return reply
