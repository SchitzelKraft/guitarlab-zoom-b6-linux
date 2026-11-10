"""A minimal ALSA sequencer client through ctypes (libasound.so.2, no other dependencies).

The virtual pedal shows up as client "ZOOM B6" with port "ZOOM B6 MIDI 1", the names the
real B6's USB driver uses, so Wine lists it as "ZOOM B6 - ZOOM B6 MIDI 1" like the pedal.

snd_seq_event_t (28 bytes): type@0 flags@1 tag@2 queue@3 time@4..11 source(client,port)@12
dest(client,port)@14 data@16; SysEx data is ext (len u32 @16, ptr @20, packed); controller
is channel@16 param@20 value@24; program change is channel@16 value@24.
"""
import ctypes
import ctypes.util
import select
import struct

_lib = ctypes.CDLL(ctypes.util.find_library("asound") or "libasound.so.2")

SND_SEQ_OPEN_DUPLEX = 3
SND_SEQ_NONBLOCK = 1
CAP_READ, CAP_WRITE, CAP_SUBS_READ, CAP_SUBS_WRITE, CAP_DUPLEX = 1, 2, 0x20, 0x40, 0x10
TYPE_MIDI_GENERIC, TYPE_HARDWARE, TYPE_PORT = 1 << 1, 1 << 16, 1 << 19
EV_CONTROLLER, EV_PGMCHANGE, EV_SYSEX = 10, 11, 130
EV_PORT_SUBSCRIBED, EV_PORT_UNSUBSCRIBED = 66, 67
LENGTH_VARIABLE = 1 << 2
QUEUE_DIRECT, ADDRESS_SUBSCRIBERS, ADDRESS_UNKNOWN = 253, 254, 253
EVENT_SIZE = 28
CHUNK = 256  # the B6's USB driver delivers SysEx in 256-byte events

_lib.snd_seq_open.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
_lib.snd_seq_set_client_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
_lib.snd_seq_create_simple_port.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]
_lib.snd_seq_event_input.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_lib.snd_seq_event_output_direct.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_lib.snd_seq_client_id.argtypes = [ctypes.c_void_p]
_lib.snd_seq_poll_descriptors_count.argtypes = [ctypes.c_void_p, ctypes.c_short]
_lib.snd_seq_close.argtypes = [ctypes.c_void_p]
_lib.snd_seq_nonblock.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.snd_seq_parse_address.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
_lib.snd_seq_connect_to.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
_lib.snd_seq_connect_from.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]


class _Pollfd(ctypes.Structure):
    _fields_ = [("fd", ctypes.c_int), ("events", ctypes.c_short), ("revents", ctypes.c_short)]


_lib.snd_seq_poll_descriptors.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Pollfd), ctypes.c_uint, ctypes.c_short]


class SeqPort:
    def __init__(self, client_name="ZOOM B6", port_name="ZOOM B6 MIDI 1"):
        self.h = None
        h = ctypes.c_void_p()
        if _lib.snd_seq_open(ctypes.byref(h), b"default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK) < 0:
            raise OSError("cannot open the ALSA sequencer")
        self.h = h
        _lib.snd_seq_set_client_name(self.h, client_name.encode())
        caps = CAP_READ | CAP_WRITE | CAP_SUBS_READ | CAP_SUBS_WRITE | CAP_DUPLEX
        self.port = _lib.snd_seq_create_simple_port(self.h, port_name.encode(), caps,
                                                    TYPE_MIDI_GENERIC | TYPE_HARDWARE | TYPE_PORT)
        if self.port < 0:
            raise OSError("cannot create the sequencer port")
        self.client = _lib.snd_seq_client_id(self.h)
        n = _lib.snd_seq_poll_descriptors_count(self.h, 1)  # POLLIN
        fds = (_Pollfd * n)()
        _lib.snd_seq_poll_descriptors(self.h, fds, n, 1)
        self.fds = [f.fd for f in fds]
        self._sysex = bytearray()
        self.subscribed = []  # (event type, client, port) notifications, for the log

    def connect(self, address):
        """Subscribe both ways to the port at `address` ("client:port", names allowed, e.g.
        "ZOOM B6:0"). Raises LookupError when no such port exists."""
        addr = (ctypes.c_ubyte * 2)()
        if _lib.snd_seq_parse_address(self.h, addr, address.encode()) < 0:
            raise LookupError(f"no ALSA sequencer port {address}")
        if (_lib.snd_seq_connect_to(self.h, self.port, addr[0], addr[1]) < 0
                or _lib.snd_seq_connect_from(self.h, self.port, addr[0], addr[1]) < 0):
            raise LookupError(f"cannot connect to ALSA sequencer port {address}")
        return addr[0], addr[1]

    def close(self):
        if self.h:
            _lib.snd_seq_close(self.h)
            self.h = None

    # ---- input ---------------------------------------------------------------
    def read(self, timeout=0.1):
        """Complete incoming messages (SysEx without F0/F7, channel messages as raw bytes)."""
        if not select.select(self.fds, [], [], timeout)[0]:
            return []
        out = []
        while True:
            ev = ctypes.c_void_p()
            rc = _lib.snd_seq_event_input(self.h, ctypes.byref(ev))
            if rc < 0 or not ev.value:
                break
            raw = ctypes.string_at(ev.value, EVENT_SIZE)
            out.extend(self._decode(ev.value, raw))
            if rc == 0:
                break
        return out

    def _decode(self, addr, raw):
        etype = raw[0]
        if etype == EV_SYSEX:
            n, ptr = struct.unpack_from("<IQ", raw, 16)
            data = ctypes.string_at(ptr, n)
            out = []
            for b in data:
                if b == 0xF0:
                    self._sysex = bytearray()
                elif b == 0xF7:
                    out.append(bytes(self._sysex))
                    self._sysex = bytearray()
                else:
                    self._sysex.append(b)
            return out
        if etype == EV_CONTROLLER:
            ch, param, value = raw[16], struct.unpack_from("<I", raw, 20)[0], struct.unpack_from("<i", raw, 24)[0]
            return [bytes([0xB0 | ch, param & 0x7F, value & 0x7F])]
        if etype == EV_PGMCHANGE:
            return [bytes([0xC0 | raw[16], struct.unpack_from("<i", raw, 24)[0] & 0x7F])]
        if etype in (EV_PORT_SUBSCRIBED, EV_PORT_UNSUBSCRIBED):
            self.subscribed.append((etype, raw[16], raw[17], raw[18], raw[19]))
        return []

    # ---- output --------------------------------------------------------------
    def _event(self, etype, flags=0):
        ev = bytearray(EVENT_SIZE)
        ev[0], ev[1], ev[3] = etype, flags, QUEUE_DIRECT
        ev[12], ev[13] = self.client, self.port
        ev[14], ev[15] = ADDRESS_SUBSCRIBERS, ADDRESS_UNKNOWN
        return ev

    def _output(self, ev):
        buf = ctypes.create_string_buffer(bytes(ev), EVENT_SIZE)
        while True:
            rc = _lib.snd_seq_event_output_direct(self.h, buf)
            if rc != -11:  # -EAGAIN: output pool full
                return rc
            select.select([], [], [], 0.001)

    def send(self, msg):
        msg = bytes(msg)
        if msg and msg[0] >= 0x80:
            status = msg[0] & 0xF0
            if status == 0xB0:
                ev = self._event(EV_CONTROLLER)
                ev[16] = msg[0] & 0x0F
                struct.pack_into("<Ii", ev, 20, msg[1], msg[2])
            elif status == 0xC0:
                ev = self._event(EV_PGMCHANGE)
                ev[16] = msg[0] & 0x0F
                struct.pack_into("<i", ev, 24, msg[1])
            else:
                raise ValueError(f"unsupported channel message {msg.hex(' ')}")
            self._output(ev)
            return
        data = b"\xf0" + msg + b"\xf7"
        for i in range(0, len(data), CHUNK):
            chunk = ctypes.create_string_buffer(data[i:i + CHUNK], len(data[i:i + CHUNK]))
            ev = self._event(EV_SYSEX, LENGTH_VARIABLE)
            struct.pack_into("<IQ", ev, 16, len(data[i:i + CHUNK]), ctypes.addressof(chunk))
            self._output(ev)
