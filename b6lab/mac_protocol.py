"""Offline reconstruction of Guitar Lab's Mac parameter-edit message builder.

This module only constructs messages; it never opens or writes to a MIDI device.
The implementation follows FUN_1002ab1b0 and the command callback at
LAB_10003695a in the recovered Mac executable. The B6-specific session and
bypass sequence have not yet been established.
"""
from dataclasses import dataclass
import time

from b6lab import ptcf
from b6lab.codec import from7, to7
from b6lab.midi import B6, HDR


@dataclass(frozen=True)
class ParameterEdit:
    messages: tuple[bytes, ...]  # SysEx payloads, excluding F0/F7
    visible_start: int


@dataclass(frozen=True)
class ParameterChange:
    command: int
    first_byte: int  # Mac listener tests this byte, but its meaning is unconfirmed.
    module: int
    parameter: int
    value: int


@dataclass(frozen=True)
class EffectParameterInfo:
    name: str
    metadata: bytes
    flag: int
    records: tuple[tuple[int, int, int, int], ...]
    trailing: bytes


def parse_effect_parameter_info(message):
    """Decode the fields read from a 64 06 record by the Mac app.

    The first 11-byte record is kept here, even though the Mac handler skips it
    when populating its parameter vector. Field meanings remain unconfirmed.
    """
    message = bytes(message)
    if (len(message) < 36 or message[0] != 0x52 or message[2:5] != b"\x6e\x64\x06"
            or any(byte > 0x7F for byte in message)):
        raise ValueError("invalid FX Param Info record")
    name = message[5:19].split(b"\0", 1)[0].decode("ascii")
    metadata, flag = message[19:35], message[35]
    body = message[36:]
    count = len(body) // 11
    records = []
    for i in range(count):
        record = body[i * 11:(i + 1) * 11]
        value = from7(record[6:11])
        if value > 0xFFFFFFFF:
            raise ValueError("FX Param Info field exceeds 32 bits")
        records.append((from7(record[0:2]), from7(record[2:4]),
                        from7(record[4:6]), value))
    return EffectParameterInfo(name, metadata, flag, tuple(records), body[count * 11:])


def read_edit_buffer(transport):
    """Run the Mac app's two-send edit-buffer transaction on a transport.

    The application does not invoke this yet. The packet sequence comes from
    the Mac command registry and its zero-initialized command parameters; the
    B6 session requirements are not yet verified. ``transport`` must provide
    ``request`` and ``send`` methods with the same framing rules as ``B6``.
    """
    message = transport.request([*HDR, 0x64, 0x13], [*HDR, 0x64, 0x12])
    data = B6._decode(message, 6, "edit buffer")
    transport.send([*HDR, 0x00, 0x00])
    return data


def read_effect_parameters(transport, timeout=30.0):
    """Run the Mac app's FX Param Info request sequence on an injected transport.

    The app requests 64 04, waits for Respondence, then requests 64 05 for
    each 64 06 record until 64 07 ends the stream. The response bodies are
    retained verbatim. This has not been connected to the physical pedal.
    """
    deadline = time.monotonic() + timeout
    transport.request_ack([*HDR, 0x64, 0x04], timeout=timeout)
    records = []
    while True:
        if deadline <= time.monotonic():
            raise TimeoutError("FX Param Info transaction timed out")
        transport.send([*HDR, 0x64, 0x05])
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("FX Param Info transaction timed out")
            msg = bytes(transport.recv_sysex(remaining))
            if len(msg) >= 5 and msg[0] == 0x52 and msg[2:4] == b"\x6e\x64":
                if msg[4] == 0x06:
                    records.append(msg)
                    break
                if msg[4] == 0x07:
                    return records
            if len(msg) >= 5 and msg[:4] == HDR + b"\x00" and msg[4] != 0:
                raise RuntimeError(f"FX Param Info: pedal returned error 0x{msg[4]:02X}")


def parse_parameter_change(message):
    """Decode the 64 03 / 64 20 messages accepted by the Mac listener.

    Input excludes MIDI's F0/F7 framing, matching ``B6.recv_sysex``.
    """
    message = bytes(message)
    if (len(message) != 13 or message[:4] != HDR + b"\x64"
            or message[4] not in (0x03, 0x20) or any(b > 0x7F for b in message)):
        raise ValueError("not a complete Guitar Lab parameter-change message")
    value = from7(message[8:13])
    if value > 0xFFFFFFFF:
        raise ValueError("parameter-change value exceeds 32 bits")
    return ParameterChange(message[4], message[5], message[6], message[7], value)


def apply_parameter_change(patch, change):
    """Apply the Mac listener's normal effect-parameter update to a patch.

    This covers only the branch whose first byte is zero and parameter number
    is at least two. Bypass and special module messages use separate paths in
    the Mac application and are deliberately left to their own handlers.
    """
    if change.first_byte != 0 or change.parameter < 2 or change.module >= len(patch.effects):
        return False
    slot = change.module
    if patch.effects[slot].is_tail:
        slot -= 1
        if slot < 0 or patch.effects[slot].is_tail:
            raise ValueError("orphaned double-width effect slot")
    index = change.parameter - 2
    effect = patch.effects[slot]
    if not effect.editable(index) or change.value > effect.max_value(index):
        raise ValueError("parameter change exceeds the decoded effect field")
    ptcf.set_param(patch, slot, index, change.value)
    return True


def parameter_edit(effect_widths, effect_index, parameter_index, value, *,
                   capability_flags, visible_start, visible_width):
    """Reproduce the Mac app's knob-edit payloads and viewport calculation.

    ``effect_widths`` counts physical chain positions occupied by each effect.
    All capability and viewport values must come from the connected device and
    current app state; this function does not guess them.
    """
    if not effect_widths or any(width not in (1, 2) for width in effect_widths):
        raise ValueError("effect widths must be 1 or 2")
    if not 0 <= effect_index < len(effect_widths):
        raise ValueError("effect index out of range")
    if not 0 <= parameter_index <= 125:
        raise ValueError("parameter index out of range")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("parameter value out of range")
    if not 0 <= capability_flags <= 0xFFFFFFFF:
        raise ValueError("capability flags out of range")
    if not 0 <= visible_start <= 127 or not 1 <= visible_width <= 128:
        raise ValueError("invalid effect viewport")

    physical = sum(effect_widths[:effect_index])
    if physical > 127:
        raise ValueError("physical effect position exceeds MIDI range")
    new_start = visible_start
    if physical < visible_start:
        new_start = physical
    elif physical >= visible_start + visible_width:
        new_start = physical - visible_width + 1

    embedded = bool(capability_flags & 2)
    command = 0x20 if capability_flags.bit_length() > 1 else 0x03
    prefix = bytes([*HDR, 0x64, command, 0])
    messages = []
    if embedded or new_start != visible_start:
        # LAB_10003695a uses module 100 for embedded devices, 10 otherwise.
        messages.append(prefix + bytes([100 if embedded else 10, 1, *to7(new_start, 5)]))
    messages.append(prefix + bytes([physical, parameter_index + 2, *to7(value, 5)]))
    return ParameterEdit(tuple(messages), new_start)


def send_parameter_edit(transport, effect_widths, effect_index, parameter_index, value, *,
                        capability_flags, visible_start, visible_width):
    """Send a Mac-app knob-edit sequence on an already initialized session.

    This is not connected to the GUI: the original session initialization and
    hardware recovery behavior still need to be established for the B6.
    """
    edit = parameter_edit(effect_widths, effect_index, parameter_index, value,
                          capability_flags=capability_flags, visible_start=visible_start,
                          visible_width=visible_width)
    for message in edit.messages:
        transport.send(message)
    return edit.visible_start


class ParameterSession:
    """Track Mac-style parameter messages for an already initialized session.

    Session setup, pedal bypass and recovery are intentionally outside this
    component. It is not connected to the application or physical B6 yet.
    """

    def __init__(self, transport, patch, *, capability_flags, visible_width, visible_start=None):
        self.transport = transport
        self.patch = patch
        self.capability_flags = capability_flags
        self.visible_width = visible_width
        self.visible_start = patch.visible_start if visible_start is None else visible_start
        if self.visible_start is None:
            raise ValueError("patch does not contain a visible effect position")

    def edit(self, slot, index, value):
        heads = [effect.slot for effect in self.patch.effects if not effect.is_tail]
        if slot not in heads:
            raise ValueError("effect slot is not a head position")
        effect = self.patch.effects[slot]
        if not effect.editable(index) or not 0 <= value <= effect.max_value(index):
            raise ValueError("parameter value exceeds the decoded effect field")
        widths = [2 if head + 1 < len(self.patch.effects) and self.patch.effects[head + 1].is_tail
                  else 1 for head in heads]
        start = send_parameter_edit(self.transport, widths, heads.index(slot), index, value,
                                    capability_flags=self.capability_flags,
                                    visible_start=self.visible_start,
                                    visible_width=self.visible_width)
        ptcf.set_param(self.patch, slot, index, value)
        self.visible_start = start

    def receive(self, message):
        return apply_parameter_change(self.patch, parse_parameter_change(message))
