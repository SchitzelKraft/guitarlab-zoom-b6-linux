"""Effect catalog: effect ID -> name, group, description and knob names.

Built from the pedal's own effect files (`*.ZD2`, read with tools/ffs_read.py) and the
IR name list (`64 1A`), by tools/build_effects.py, into pedal-files/effects.json.

ZD2 layout (see zoom-zt2's zoomzt2.ZD2): "ZDLF", ..., version @0x58, group byte @0x5F,
effect ID u32 LE @0x60, name (NUL-terminated, max 11) @0x64, group name @0x6F, then
chunks ... PRMJ (Japanese) and PRME (English) parameter JSON:
{"Parameters": [{"name", "explanation", "blackback", "pedal"}, ...]} in knob order.

IR effects (ID high byte 0x1B) have no ZD2 file: ID low byte - 0x10 = index into
the pedal's IR name list. High byte 0x1A is the SND-RTN group (FxLoop, Send, Return), also
without a ZD2 file; both are filled in by `with_builtin` (parameters verified on the B6).
"""
import functools
import json
import hashlib
import struct
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "pedal-files" / "effects.json"
RANGES_PATH = DEFAULT_PATH.with_name("parameter-ranges.json")
IR_CATEGORIES = (0x1B,)
SND_RTN_CATEGORY = 0x1A
IR_BASE = 0x10
IR_LOAD = 86.45  # measured, see dsp_load


@dataclass
class ParamInfo:
    name: str
    explanation: str = ""
    pedal: bool = False  # expression pedal can control it
    raw_max: int | None = None
    display_min: str | None = None
    display_step: str | None = None
    display_precision: int = 0
    display_labels: list[str] | None = None

    def format_value(self, value, raw=False):
        if not raw and self.display_labels is not None and 0 <= value < len(self.display_labels):
            return self.display_labels[value]
        if raw or self.display_min is None or self.display_step is None:
            return f"raw {value}"
        result = Decimal(self.display_min) + Decimal(self.display_step) * value
        return f"{result:.{self.display_precision}f}"


@dataclass
class EffectInfo:
    fx_id: int
    name: str
    group: str = ""
    description: str = ""
    params: list[ParamInfo] = field(default_factory=list)


def _cstr(b):
    return b.split(b"\0", 1)[0].decode("ascii", "replace")


def _chunk(data, tag):
    """Body of the last chunk `tag` (4-char tag, u32 LE length, body)."""
    i = data.rfind(tag)
    if i < 0 or i + 8 > len(data):
        return None
    n = struct.unpack_from("<I", data, i + 4)[0]
    return data[i + 8:i + 8 + n]


def parse_zd2(data):
    if data[:4] != b"ZDLF" or len(data) < 0x7A:
        raise ValueError("not a ZD2 effect file")
    fx_id = struct.unpack_from("<I", data, 0x60)[0]
    info = EffectInfo(fx_id, _cstr(data[0x64:0x6F]), _cstr(data[0x6F:0x7A]))
    txe = _chunk(data, b"TXE1")
    if txe:
        info.description = txe.split(b"\0", 1)[0].decode("utf-8", "replace").strip()
    prme = _chunk(data, b"PRME")
    if prme:
        doc = json.loads(prme.decode("utf-8", "replace").rstrip("\0 \r\n"))
        info.params = [ParamInfo(p.get("name", ""), p.get("explanation", ""), bool(p.get("pedal")))
                       for p in doc.get("Parameters", [])]
    return info


def parse_ir_names(msg):
    """IR names from the `64 1B` reply (SysEx body without F0/F7): 9-char names from byte 45."""
    count = msg[8] | msg[9] << 7
    return [msg[45 + 9 * i:54 + 9 * i].decode("ascii", "replace").strip() for i in range(count)]


def _p(name, explanation, maximum=100, **kw):
    return ParamInfo(name, explanation, raw_max=maximum, display_min="0", display_step="1", **kw)


def ir_params():
    return [
        _p("LO", "Adjusts volume of low frequencies."),
        _p("HI", "Adjusts volume of high frequencies."),
        ParamInfo("BAL", "Adjusts the balance between original and effect sounds. When it is set "
                  "between -100 to -1, the polarity of effect sound is reversed.",
                  raw_max=200, display_min="-100", display_step="1"),
        ParamInfo("VOL", "Adjusts the volume.", raw_max=510, display_min="-45.0",
                  display_step="0.1", display_precision=1),
    ]


def ir_info(fx_id, ir_names):
    i = (fx_id & 0xFF) - IR_BASE
    if fx_id >> 24 != IR_CATEGORIES[0] or not 0 <= i < len(ir_names):
        return None
    return EffectInfo(fx_id, ir_names[i], "IR", f"Impulse response {ir_names[i]} (IR {i + 1})",
                      ir_params())


def snd_rtn_effects():
    """The SND-RTN effects (high byte 0x1A), no ZD2 file; parameters read off the B6 display."""
    level = "Adjusts the volume."
    dry = "Adjusts the volume of the unaffected sound."
    return {
        0x1A000020: EffectInfo(
            0x1A000020, "FxLoop", "SND-RTN",
            "Use this to insert an external effect, for example, between effects on this unit. "
            "The signal will be sent to the SEND jack from the position where this effect is placed, "
            "and the signal from the RETURN jack will be returned to the same position.",
            [_p("Send", "Adjusts the SEND jack output level."),
             _p("Return", "Adjusts the RETURN jack input level."),
             _p("Dry", dry), _p("Vol", level)]),
        0x1A000023: EffectInfo(
            0x1A000023, "Send", "SND-RTN",
            "Use this to output sound to an external effect, for example, in the middle of the "
            "effect chain of this unit. The signal will be sent to the SEND jack from the position "
            "where this effect is placed.",
            [_p("Send", "Adjusts the SEND jack output level."), _p("Dry", dry),
             _p("Mode", "Chooses the function assigned to SEND. When it is set to SUBOUT, the patch "
                "level and master volume are applied to the output signal to SEND.", 1,
                display_labels=["SEND", "SUBOUT"]),
             _p("ON/OFF", "Sets the foot switch function.", 1,
                display_labels=["LATCH", "UnLATCH"])]),
        0x1A000026: EffectInfo(
            0x1A000026, "Return", "SND-RTN",
            "Use this to mix the sound from an external effect, for example, into the middle of "
            "the effect chain of this unit. The signal from the RETURN jack will be returned to "
            "the position where this effect is placed.",
            [_p("Return", "Adjusts the RETURN jack input level."),
             _p("Phase", "Set the phase of the RETURN jack input signal.", 1,
                display_labels=["NORM", "INV"]),
             _p("Dry", dry), _p("Vol", level)]),
    }


def with_builtin(cat):
    """Correct `cat` in place: no fake 0x1A IR entries, IR entries carry their four parameters,
    and the SND-RTN effects are present."""
    for fx_id in [k for k, v in cat.items() if k >> 24 == SND_RTN_CATEGORY]:
        del cat[fx_id]
    for fx_id, info in cat.items():
        if fx_id >> 24 in IR_CATEGORIES:
            info.group = "IR"
            info.params = ir_params()
    cat.update(snd_rtn_effects())
    return cat


def build(zd2_files, ir_names=()):
    cat = {}
    for f in zd2_files:
        info = parse_zd2(Path(f).read_bytes())
        cat[info.fx_id] = info
    for i, _ in enumerate(ir_names):
        fx_id = IR_CATEGORIES[0] << 24 | (i + IR_BASE)
        cat[fx_id] = ir_info(fx_id, ir_names)
    return with_builtin(cat)


def save(cat, path=DEFAULT_PATH):
    out = {f"{k:08X}": asdict(v) for k, v in sorted(cat.items())}
    Path(path).write_text(json.dumps(out, indent=1, ensure_ascii=False))


def load(path=DEFAULT_PATH):
    """Catalog from JSON; empty dict if the file is missing or unreadable."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    cat = {}
    for k, v in raw.items():
        v["params"] = [ParamInfo(**p) for p in v.get("params", [])]
        cat[int(k, 16)] = EffectInfo(**v)
    with_builtin(cat)
    if Path(path).resolve() == DEFAULT_PATH.resolve():
        _load_parameter_ranges(cat, RANGES_PATH)
    return cat


def _load_parameter_ranges(cat, path):
    """Use captured limits only for the exact effect-module files they describe."""
    try:
        ranges = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return
    for fx_id, record in ranges.items():
        try:
            info = cat[int(fx_id, 16)]
            module = Path(path).parent / record['module']
            if hashlib.sha256(module.read_bytes()).hexdigest() != record['module_sha256']:
                continue
            for param, limit in zip(info.params, record['parameters']):
                param.raw_max = int(limit['maximum'])
                display = limit.get('display')
                if display:
                    param.display_min = display['minimum']
                    param.display_step = display['step']
                    param.display_precision = display['precision']
                if limit.get('labels'):
                    param.display_labels = list(limit['labels'])
        except (KeyError, OSError, TypeError, ValueError):
            continue


@lru_cache(maxsize=1)
def catalog():
    return load()


def lookup(fx_id):
    return catalog().get(fx_id)


@lru_cache(maxsize=None)
def dsp_load(fx_id):
    """The effect's processor load, from the last float of its ZD2 `INFO` chunk.

    Guitar Lab shows it as a percentage: load / 2.2 (EFFECT page "Power", EDITOR "Processor"),
    checked on 9 compressors and on Uprising's 78 %. None when the module file is unknown
    (IR effects have no ZD2 file)."""
    if fx_id >> 24 == SND_RTN_CATEGORY:
        return None  # unknown
    if fx_id >> 24 in IR_CATEGORIES:
        # IR cabinets have no ZD2 file. Measured on the B6 with Guitar Lab: Warm AC370 (73 %)
        # and SVT Drive (98 %) both leave 86.4..86.5 for their IR; where Guitar Lab gets the
        # figure is not found yet (no such constant in the binary, maybe the 64 1B / 64 06 data).
        return IR_LOAD
    info = _info_chunk(fx_id)
    if info is None or len(info) < 20:
        return None
    return struct.unpack_from("<f", info, 16)[0]


@lru_cache(maxsize=None)
def _info_chunk(fx_id):
    """The body of the effect's ZD2 `INFO` chunk (8 bytes after the tag), or None when the
    module file is unknown. Guitar Lab finds it with FUN_10008f660, a forward scan for the tag
    (FUN_1000a1a70); in every module of pedal-files/ the first "INFO" is that chunk."""
    try:
        ranges = json.loads(RANGES_PATH.read_text())
        module = RANGES_PATH.parent / ranges[f"{fx_id:08X}"]["module"]
        data = module.read_bytes()
    except (OSError, ValueError, KeyError):
        return None
    i = data.find(b"INFO")
    if i < 0 or i + 8 > len(data):
        return None
    return data[i + 8:]


def info_flags(fx_id):
    """The first u32 (LE) of the effect's ZD2 `INFO` chunk, or None without a module file.

    Guitar Lab's ZDL parser FUN_1000a1a70 stores it at effect + 0x158 (the next field, INFO
    + 0x10, is the processor load at + 0x15c); GetEffect FUN_1002ace60 copies it into the
    pedal's effect information as (flags & 5) << 6, i.e. pedal component + 0x154 bit 0x40 =
    INFO bit 0 and bit 0x100 = INFO bit 2 (analysis/ui-trace/geq-flag.c, geq-zdlparse.c)."""
    info = _info_chunk(fx_id)
    if info is None or len(info) < 4:
        return None
    return struct.unpack_from("<I", info, 0)[0]


def has_sliders(fx_id):
    """True when Guitar Lab draws the effect's parameters as vertical sliders instead of
    bars: EffectPedalComponent paint FUN_1000030b0 tests pedal + 0x154 & 0x40, which is ZD2
    INFO bit 0 (info_flags). Set in BA_GEQ88.ZD2 (BassGEQ) and STBGEQ88.ZD2 (St Ba GEQ) only;
    BassPEQ's INFO word is 0, so Guitar Lab shows it with bars."""
    return bool((info_flags(fx_id) or 0) & 1)


SLIDER_OFF = 0x78000   # parameter flags that keep a parameter out of the slider style


def param_flags(fx_id):
    """The u32 flags of each shown parameter (OnOff and the effect-name record left out), as
    the pedal's `64 06` reply sends them (4th field, stored at parameter + 0x40 by GetEffect
    FUN_1002ace60). The same values sit in the ZD2 parameter table: 0x38-byte records from
    "OnOff", flags at +0x30 (checked against a recorded `64 06` stream for every module,
    analysis/ui-trace/GEQ-BARS.md). [] without a module file."""
    try:
        ranges = json.loads(RANGES_PATH.read_text())
        data = (RANGES_PATH.parent / ranges[f"{fx_id:08X}"]["module"]).read_bytes()
    except (OSError, ValueError, KeyError):
        return []
    i = data.find(b"OnOff\0")
    out = []
    if i < 0:
        return out
    k = i + 2 * 0x38
    while k + 0x38 <= len(data) and data[k:k + 1].isascii() and 0x20 < data[k] < 0x7F:
        out.append(struct.unpack_from("<I", data, k + 0x30)[0])
        k += 0x38
    return out


def slider_param(fx_id, index):
    """FUN_1000030b0 (100003b23..100003b50): a parameter is drawn as a vertical slider when
    the effect has_sliders and (flags & 0x78000) == 0; otherwise with the normal bar."""
    flags = param_flags(fx_id)
    return has_sliders(fx_id) and not (flags[index] if index < len(flags) else 0) & SLIDER_OFF


@functools.lru_cache(maxsize=None)
def zdl_masks(fx_id):
    """The device-compatibility fields of the effect's ZD2 header, as the ZDL parser
    FUN_1000a1a70 keeps them (analysis/ui-trace/CLIP-EXTRA.md): (u32 at 0x0c, u64 at 0x10, the
    64 version bytes 0x18..0x57, the byte at 0x58), or None without a module file. Every B6
    module: (0x8, 1 << 32, byte 32 = 0x80, 1 or 2)."""
    try:
        ranges = json.loads(RANGES_PATH.read_text())
        data = (RANGES_PATH.parent / ranges[f"{fx_id:08X}"]["module"]).read_bytes()
    except (OSError, ValueError, KeyError):
        return None
    if len(data) < 0x59:
        return None
    return (struct.unpack_from("<I", data, 0x0C)[0], struct.unpack_from("<Q", data, 0x10)[0],
            bytes(data[0x18:0x58]), data[0x58])
