"""What the B6 reports about itself, decoded (pure functions, no pedal access).

Sources: the identity reply, the global data record (`64 0A` -> `64 09`) and the effect list
file FLST_SEQ.ZT2. Meanings marked "decompile" come from analysis/HANDY-GL.md section 4.1
and are not confirmed on the pedal.
"""
from __future__ import annotations

from b6lab import ffs
from b6lab.codec import from7

B6_MODEL = bytes([0x6E, 0x00, 0x1A, 0x00])
AUTO_SAVE_BYTE = 12   # global data byte for AUTO SAVE (module 100 param 0x0F), any non-zero = on
TEMPO_BYTES = slice(5, 7)
CALIBRATION_BYTE = 9  # tuner reference: Hz = 435 + value (verified 2026-11-10)
FIRST_PARAM = 0x0A    # byte 7 holds module 100 param 0x0A, byte 16 param 0x13
FIRST_PARAM_BYTE = 7
PARAM_COUNT = 10
VERSION_OFFSET, VERSION_LEN = 13, 5  # in a 26-byte FLST_SEQ.ZT2 record, after the name

PARAM_NAMES = {
    0x0C: "tuner calibration (Hz = 435 + value)",
    0x0D: "tuner settings (type or flat tuning)",
    0x0E: "tuner settings (type or flat tuning)",
    0x0F: "AUTO SAVE",
}


def decode_identity(reply: bytes) -> dict:
    reply = bytes(reply)
    model = "B6" if reply[5:9] == B6_MODEL else f"unknown ({reply[5:9].hex(' ')})"
    firmware = reply[9:].decode("ascii", "replace").strip("\0 ")
    return {"model": model, "firmware": firmware, "raw": reply.hex(" ")}


def auto_save_on(reply: bytes) -> bool | None:
    """AUTO SAVE from a global data reply; None when the reply is too short to tell."""
    reply = bytes(reply)
    if len(reply) <= AUTO_SAVE_BYTE:
        return None
    return reply[AUTO_SAVE_BYTE] != 0


def decode_global(reply: bytes) -> dict:
    reply = bytes(reply)
    params = {}
    for i in range(PARAM_COUNT):
        n, at = FIRST_PARAM + i, FIRST_PARAM_BYTE + i
        params[f"0x{n:02X}"] = {"value": reply[at] if at < len(reply) else None,
                                "name": PARAM_NAMES.get(n, "unknown"), "status": "decompile"}
    return {"tempo": from7(reply[TEMPO_BYTES]) if len(reply) >= TEMPO_BYTES.stop else None,
            "tuner_hz": 435 + reply[CALIBRATION_BYTE] if len(reply) > CALIBRATION_BYTE else None,
            "auto_save": auto_save_on(reply), "params": params, "raw": reply.hex(" ")}


def effects_overview(effect_list: bytes, catalog: dict) -> dict:
    """Installed effects from FLST_SEQ.ZT2, compared with the effect catalog."""
    import re
    from b6lab import effect_files
    effect_list = bytes(effect_list)
    flags = ffs.installed(effect_list)
    versions = {}
    for m in re.finditer(rb"([A-Z0-9_]{1,8}\.ZD2)\0", effect_list):
        raw = effect_list[m.start() + VERSION_OFFSET:m.start() + VERSION_OFFSET + VERSION_LEN]
        versions[m.group(1).decode()] = raw.split(b"\0")[0].decode("ascii", "replace")
    by_file = {}
    for fx_id, info in catalog.items():
        try:
            f = effect_files.module_file(fx_id)
        except (OSError, ValueError):
            f = None
        if f:
            by_file[f] = info.name
    return {"installed": sum(flags.values()), "not_installed": sum(not v for v in flags.values()),
            "versions": versions,
            "unknown_to_catalog": sorted(f for f in flags if f not in by_file and f != "BYPASS.ZD2"),
            "catalog_not_on_pedal": sorted(n for f, n in by_file.items() if not flags.get(f))}
