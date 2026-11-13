"""Patch spec: describe a B6 patch in display units, and build a patch from such a spec.

A spec is {"name", "description", "level", "footswitches", "effects": [{"effect", "on",
"knobs"}]}. `describe` adds each effect's chain-entry index ("entry", tails counted), which
`build` ignores. `build` starts every effect from a reference entry (the raw EDTB entry of the
first known patch that uses it, with its tail entry when double width), applies the listed
knobs and computes PRM2 from the chain. Effects without a reference entry are refused: their
chain width is unknown, and a wrong width would give a malformed chain.
"""
from __future__ import annotations

import difflib
from typing import Iterable

from b6lab import effects, prm2, ptcf
from b6lab.knobs import KnobError, display_value, raw_value

BUDGET = 220.0             # DSP load units the firmware admits per patch
NAME_MAX = 10
DESCRIPTION_WARN = 161     # longest Zoom description
DESCRIPTION_MAX = 191      # longest description seen on the pedal
LEVEL_MAX = 120
DEFAULT_LEVEL = 80
FOOTSWITCH_MAX = 4
HEADER_UNKNOWN = bytes.fromhex("00200000000000000000")
VERSION = 2
EMPTY_RAW = 1              # an empty entry as the B6 inserts it: on, effect 0
TAIL_ID = 1
EMPTY_NAME = "Empty"       # the name of an empty slot on the pedal

SPEC_KEYS = {"name", "description", "level", "footswitches", "effects"}
EFFECT_KEYS = {"effect", "on", "knobs", "entry"}  # "entry" (from describe) is ignored

References = dict[int, tuple[int, int | None]]


class SpecError(ValueError):
    """A patch spec that cannot be built."""


def reference_index(patches: Iterable[bytes]) -> References:
    """fx_id -> (raw entry, raw tail entry or None), first occurrence wins."""
    refs: References = {}
    for data in patches:
        p = ptcf.parse(data)
        for i, e in enumerate(p.effects):
            if e.is_tail or e.fx_id in (0, TAIL_ID) or e.fx_id in refs:
                continue
            nxt = p.effects[i + 1] if i + 1 < len(p.effects) else None
            refs[e.fx_id] = (e.raw, nxt.raw if nxt is not None and nxt.is_tail else None)
    return refs


def chain_effect_ids(data: bytes) -> list[int]:
    """fx_ids of the effects in a patch's chain (no empty entries, no tails)."""
    return [e.fx_id for e in ptcf.parse(bytes(data)).effects
            if not e.is_tail and e.fx_id not in (0, TAIL_ID)]


def is_empty_patch(data: bytes) -> bool:
    """A real Empty slot: named Empty and every chain entry is effect 0. A slot that only has
    the name (e.g. a user's edits kept under it by AUTOSAVE) is not empty."""
    try:
        p = ptcf.parse(bytes(data))
    except Exception:
        return False
    return p.name == EMPTY_NAME and all(e.fx_id == 0 for e in p.effects)


def _load(fx_id: int) -> float | None:
    return effects.dsp_load(fx_id)  # looked up at call time (tests replace it)


def _dsp_total(entries) -> tuple[float, list[int]]:
    """Sum of the known loads of the non-tail entries, and the fx_ids with unknown load."""
    total, unknown = 0.0, []
    for e in entries:
        if e.is_tail or e.fx_id in (0, TAIL_ID):
            continue
        load = _load(e.fx_id)
        if load is None:
            unknown.append(e.fx_id)
        else:
            total += load
    return total, unknown


def _percent(total: float) -> float:
    return round(total / 2.2, 1)


def _effect_name(catalog: dict, fx_id: int) -> str:
    info = catalog.get(fx_id)
    return info.name if info is not None else f"0x{fx_id:08X}"


def describe(data: bytes, catalog: dict, slot: int | None = None) -> dict:
    p = ptcf.parse(data)
    chain = []
    for entry, e in enumerate(p.effects):  # entry: chain-entry index, tails counted
        if e.is_tail:
            continue
        if e.fx_id == 0:
            chain.append({"effect": None, "entry": entry})
            continue
        info = catalog.get(e.fx_id)
        knobs = {}
        if info is not None:
            for i, param in enumerate(info.params[:len(ptcf.PARAM_WIDTHS)]):
                knobs.setdefault(param.name, display_value(param, e.params[i]))
        chain.append({"effect": _effect_name(catalog, e.fx_id), "on": e.on, "knobs": knobs,
                      "entry": entry})
    total, _ = _dsp_total(p.effects)
    percent = _percent(total)
    names = [c["effect"] for c in chain if c["effect"] is not None]
    summary = f"{p.name}: {' > '.join(names) or 'no effects'}, {int(percent + 0.5)} % DSP"
    if slot is not None:
        summary = f"Slot {slot} {summary}"
    return {
        "name": p.name,
        "description": p.comment,
        "level": p.level,
        "effects": chain,
        "dsp_percent": percent,
        "footswitches": prm2.footswitches_of(p.prm2[0]) if p.prm2 else [],
        "summary": summary,
    }


def _check_keys(obj: dict, allowed: set, what: str) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise SpecError(f"{what}: unknown key(s) {', '.join(map(repr, unknown))}; "
                        f"allowed: {', '.join(sorted(allowed))}")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_name(name) -> str:
    if (not isinstance(name, str) or not name.strip() or len(name) > NAME_MAX
            or not all(0x20 <= ord(c) <= 0x7E for c in name)):
        raise SpecError(f"name must be 1 to {NAME_MAX} printable ASCII characters, got {name!r}")
    if name.strip() == EMPTY_NAME:
        raise SpecError(f"the name {EMPTY_NAME!r} is reserved for empty slots on the pedal; "
                        "choose another name")
    return name


def _check_description(text, warnings: list[str]) -> str:
    if not isinstance(text, str):
        raise SpecError("description must be a string")
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        raise SpecError("description must be latin-1 text") from None
    if "\x00" in text:
        raise SpecError("description must not contain NUL")
    if len(text) > DESCRIPTION_MAX:
        raise SpecError(f"description has {len(text)} characters; at most {DESCRIPTION_MAX} "
                        f"are known to work on the pedal")
    if len(text) > DESCRIPTION_WARN:
        warnings.append(f"description has {len(text)} characters; Zoom's longest is "
                        f"{DESCRIPTION_WARN}, longer ones may be cut off on the pedal")
    return text


def _find_effect(name, catalog: dict, refs: References) -> int:
    if not isinstance(name, str):
        raise SpecError(f"effect name must be a string, got {name!r}")
    matches = [fx_id for fx_id, info in catalog.items() if info.name.lower() == name.strip().lower()]
    if not matches:
        names = {info.name.lower(): info.name for info in catalog.values()}
        close = difflib.get_close_matches(name.strip().lower(), list(names), n=3, cutoff=0.6)
        hint = f"; did you mean {' or '.join(names[c] for c in close)}?" if close else ""
        raise SpecError(f"unknown effect {name!r}{hint}")
    for fx_id in matches:
        if fx_id in refs:
            return fx_id
    raise SpecError(f"effect {catalog[matches[0]].name!r} has no reference entry in any known "
                    f"patch (its chain width is unknown), so it cannot be built")


def _apply_knobs(p, slot: int, info, knobs) -> None:
    if not isinstance(knobs, dict):
        raise SpecError(f"{info.name}: knobs must be an object of knob name to value")
    params = info.params[:len(ptcf.PARAM_WIDTHS)]
    by_name: dict[str, int] = {}
    for i, param in enumerate(params):
        by_name.setdefault(param.name.lower(), i)
    for knob, value in knobs.items():
        index = by_name.get(str(knob).lower())
        if index is None:
            raise SpecError(f"{info.name} has no knob {knob!r}; knobs: "
                            f"{', '.join(p.name for p in params)}")
        param = params[index]
        try:
            raw = raw_value(param, value)
        except KnobError as e:
            raise SpecError(f"{info.name}: {e}") from None
        if raw > p.effects[slot].max_value(index):
            raise SpecError(f"{info.name}: {param.name} raw value {raw} does not fit its field "
                            f"(at most {p.effects[slot].max_value(index)})")
        ptcf.set_param(p, slot, index, raw)


def _check_footswitches(value, entries) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(_is_int(v) for v in value):
        raise SpecError("footswitches must be a list of entry indices")
    if len(value) > FOOTSWITCH_MAX:
        raise SpecError(f"at most {FOOTSWITCH_MAX} footswitches, got {len(value)}")
    if len(set(value)) != len(value):
        raise SpecError(f"footswitches has a repeated entry: {value}")
    for v in value:
        if not 0 <= v < len(entries):
            raise SpecError(f"footswitch entry {v} is outside the chain (entries 0 to "
                            f"{len(entries) - 1})")
        if entries[v].is_tail or entries[v].fx_id in (0, TAIL_ID):
            raise SpecError(f"footswitch entry {v} is not an effect (empty entry or the "
                            f"second half of a double-width effect)")
    return value


def _new_patch() -> ptcf.Patch:
    return ptcf.Patch(name="", slots=0, effect_ids=[], effects=[], txj1=b"", txe1=b"",
                      prm2=[bytes(32)], header_unknown=HEADER_UNKNOWN, raw=b"", version=VERSION,
                      name_raw=b" " * NAME_MAX,
                      chunks=[("TXJ1", b""), ("TXE1", b""), ("EDTB", b""), ("PRM2", bytes(32))])


def _append(p: ptcf.Patch, raw: int) -> int:
    e = ptcf.Effect(slot=len(p.effects), fx_id=0, on=False, params=[], is_tail=False, raw=raw)
    ptcf._sync_effect(e)
    e.is_tail = e.fx_id == TAIL_ID
    p.effects.append(e)
    p.effect_ids.append(e.fx_id)
    p.slots = len(p.effects)
    return e.slot


def build(spec: dict, refs: References, catalog: dict) -> tuple[bytes, list[str]]:
    """Encoded PTCF patch for `spec`, and warnings. Raises SpecError."""
    warnings: list[str] = []
    if not isinstance(spec, dict):
        raise SpecError("spec must be an object")
    _check_keys(spec, SPEC_KEYS, "spec")
    name = _check_name(spec.get("name"))
    description = _check_description(spec.get("description", ""), warnings)
    level = spec.get("level", DEFAULT_LEVEL)
    if not _is_int(level) or not 0 <= level <= LEVEL_MAX:
        raise SpecError(f"level must be a whole number from 0 to {LEVEL_MAX}, got {level!r}")
    chain = spec.get("effects")
    if not isinstance(chain, list) or not chain:
        raise SpecError("effects must be a list with at least one effect")

    p = _new_patch()
    for n, item in enumerate(chain, 1):
        if not isinstance(item, dict):
            raise SpecError(f"effect {n} must be an object")
        _check_keys(item, EFFECT_KEYS, f"effect {n}")
        if item.get("effect") is None:
            if set(item) - {"effect", "entry"}:
                raise SpecError(f"effect {n} is empty and takes no 'on' or 'knobs'")
            _append(p, EMPTY_RAW)
            continue
        fx_id = _find_effect(item["effect"], catalog, refs)
        info = catalog[fx_id]
        on = item.get("on", True)
        if not isinstance(on, bool):
            raise SpecError(f"{info.name}: on must be true or false, got {on!r}")
        raw, tail = refs[fx_id]
        slot = _append(p, raw)
        if tail is not None:
            _append(p, tail)
        _apply_knobs(p, slot, info, item.get("knobs", {}))
        ptcf.set_on(p, slot, on)

    if len(p.effects) > ptcf.MAX_ENTRIES:
        raise SpecError(f"the chain needs {len(p.effects)} entries (a double-width effect takes "
                        f"2); the B6 holds at most {ptcf.MAX_ENTRIES}")
    footswitches = _check_footswitches(spec.get("footswitches"), p.effects)

    total, unknown = _dsp_total(p.effects)
    if total > BUDGET:
        raise SpecError(f"DSP load {total:.2f} ({_percent(total)} %) is over the budget of "
                        f"{BUDGET:g} (100 %); remove or replace an effect")
    for fx_id in unknown:
        warnings.append(f"DSP load of {_effect_name(catalog, fx_id)} is unknown, not counted")

    try:
        ptcf.set_name(p, name)
        ptcf.set_comment(p, description)
    except ValueError as e:
        raise SpecError(str(e)) from None
    body = prm2.compute(p.effects, level, footswitches)
    p.prm2 = [body]
    ptcf._set_chunk(p, "PRM2", body)
    data = ptcf.encode(p)
    if len(data) > ptcf.MAX_SIZE:
        raise SpecError(f"patch would be {len(data)} bytes, over {ptcf.MAX_SIZE}")
    check = ptcf.parse(data)
    if ([e.raw for e in check.effects] != [e.raw for e in p.effects]
            or check.prm2 != [body] or check.name != name.rstrip()):
        raise SpecError("internal error: the encoded patch does not read back as built")
    return data, warnings


def _show(value) -> str:
    if isinstance(value, dict) and "raw" in value:
        return f"raw {value['raw']}"
    return str(value)


def diff_patches(stored: dict, edit: dict) -> list[str]:
    """Readable differences between two `describe` outputs (e.g. stored slot vs edit buffer):
    name, description, level, then per chain entry the effect, on/off and every knob."""
    out = []
    for key in ("name", "description", "level"):
        if stored.get(key) != edit.get(key):
            out.append(f"{key}: {stored.get(key)!r} -> {edit.get(key)!r}" if key != "level"
                       else f"level: {stored.get(key)} -> {edit.get(key)}")
    a = {e["entry"]: e for e in stored.get("effects", [])}
    b = {e["entry"]: e for e in edit.get("effects", [])}
    for entry in sorted(set(a) | set(b)):
        x, y = a.get(entry), b.get(entry)
        if x is None or y is None or x["effect"] != y["effect"]:
            out.append(f"entry {entry}: {(x or {}).get('effect') or '(none)'} -> "
                       f"{(y or {}).get('effect') or '(none)'}")
            continue
        if x["effect"] is None:  # an empty entry on both sides
            continue
        where = f"{x['effect']} (entry {entry})"
        if x["on"] != y["on"]:
            out.append(f"{where}: {'on' if x['on'] else 'off'} -> {'on' if y['on'] else 'off'}")
        for knob, old in x["knobs"].items():
            new = y["knobs"].get(knob)
            if new != old:
                out.append(f"{where} {knob}: {_show(old)} -> {_show(new)}")
    return out


def only_text_changed(old: bytes, new: bytes) -> bool:
    """True when `new` differs from `old` at most in the patch name and the description (TXE1):
    header fields, the effect ID list, every effect entry and every other chunk (EDTB, PRM2 with
    the level, TXJ1, ...) are identical. The guard of rename_patch (MCP v3)."""
    try:
        a, b = ptcf.parse(old), ptcf.parse(new)
    except Exception:  # noqa: BLE001 - unparseable is "not only text"
        return False
    if (a.version, a.slots, a.effect_ids, a.header_unknown) != (
            b.version, b.slots, b.effect_ids, b.header_unknown):
        return False
    if [(e.raw, e.params) for e in a.effects] != [(e.raw, e.params) for e in b.effects]:
        return False
    return ([c for c in a.chunks if c[0] != "TXE1"] == [c for c in b.chunks if c[0] != "TXE1"])


def dsp_load(data: bytes) -> float:
    """Known DSP load units of a patch's effects (unknown loads count 0)."""
    return _dsp_total(ptcf.parse(data).effects)[0]


def effect_load(fx_id: int) -> float | None:
    return _load(fx_id)
