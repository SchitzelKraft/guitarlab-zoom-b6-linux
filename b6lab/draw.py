"""A patch as a text pedalboard (MCP v3, layout B), from a `patchspec.describe` result.

 ┌──────────┐┌──────────┐┌──────────────────────┐
 │● 160 Comp││● Phaser  ││● FlipTop             │
 │THRSH  -20││Color 8STG││BRGHT ON   Treble  +8 │
 └──────────┘└───[FS1]──┘└────────[FS2]─────────┘
 163 Love Money · level 80 · 74 % DSP

One box per chain entry; a double-width effect gets a box twice as wide with its knobs in two
columns. ● on, ○ off; knob values in display units, raw-only values as r<n>; [FS<n>] marks the
box footswitch n switches. Rows of boxes wrap to stay within `width` columns.
"""
from __future__ import annotations

INNER = 10          # inside width of a single box
WIDE_INNER = 22     # inside width of a double-width box
CELL = 10           # one knob column in a double-width box (two columns, a space between)


def _value(v) -> str:
    if isinstance(v, dict) and "raw" in v:
        return f"r{v['raw']}"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _cell(name: str, value, width: int) -> str:
    val = _value(value)[:width - 2]
    room = width - len(val) - 1
    return f"{name[:room]:<{room}} {val}"[:width].ljust(width)


def _widths(effects: list, entries: int | None) -> list[bool]:
    """True for a double-width effect: the next listed entry skips one."""
    out = []
    for i, e in enumerate(effects):
        if i + 1 < len(effects):
            out.append(effects[i + 1]["entry"] == e["entry"] + 2)
        else:
            out.append(entries is not None and entries == e["entry"] + 2)
    return out


def _box(effect: dict, wide: bool, marks: list[int]) -> list[str]:
    """Lines of one box without its knob-row padding: top, title, knob rows, bottom."""
    inner = WIDE_INNER if wide else INNER
    if effect.get("effect") is None:
        title, rows = "  empty", []
    else:
        title = f"{'●' if effect.get('on', True) else '○'} {effect['effect']}"
        knobs = list(effect.get("knobs", {}).items())
        if wide:
            rows = [_cell(*knobs[i], CELL) + " " + (_cell(*knobs[i + 1], CELL)
                                                     if i + 1 < len(knobs) else " " * CELL) + " "
                    for i in range(0, len(knobs), 2)]
        else:
            rows = [_cell(n, v, inner) for n, v in knobs]
    label = "".join(f"[FS{n}]" for n in marks)
    if label and len(label) <= inner:
        left = (inner - len(label)) // 2
        bottom = "└" + "─" * left + label + "─" * (inner - left - len(label)) + "┘"
    else:
        bottom = "└" + "─" * inner + "┘"
    body = ["│" + title[:inner].ljust(inner) + "│"] + ["│" + r + "│" for r in rows]
    return ["┌" + "─" * inner + "┐"] + body + [bottom]


def render(patch: dict, slot: int | None = None, width: int = 80,
           entries: int | None = None) -> str:
    effects = patch.get("effects", [])
    wides = _widths(effects, entries)
    fs = patch.get("footswitches") or []
    boxes = []
    for effect, wide in zip(effects, wides):
        covered = {effect["entry"], effect["entry"] + 1} if wide else {effect["entry"]}
        marks = [n + 1 for n, e in enumerate(fs) if e in covered]
        boxes.append(_box(effect, wide, marks))

    lines: list[str] = []
    row: list[list[str]] = []
    used = 1

    def flush():
        if not row:
            return
        height = max(len(b) for b in row)
        padded = []
        for b in row:
            w = len(b[0])
            filler = "│" + " " * (w - 2) + "│"
            padded.append(b[:-1] + [filler] * (height - len(b)) + b[-1:])
        for i in range(height):
            lines.append(" " + "".join(b[i] for b in padded))

    for b in boxes:
        w = len(b[0])
        if row and used + w > width:
            flush()
            row, used = [], 1
        row.append(b)
        used += w
    flush()

    head = f"{slot} " if slot is not None else ""
    dsp = patch.get("dsp_percent")
    footer = f" {head}{patch.get('name', '').strip()} · level {patch.get('level')}"
    if dsp is not None:
        footer += f" · {int(dsp + 0.5)} % DSP"
    lines.append(footer[:width])
    if patch.get("description"):
        lines.append((" " + patch["description"])[:width])
    return "\n".join(lines)
