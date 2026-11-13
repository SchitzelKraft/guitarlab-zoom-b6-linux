"""Which real-world gear each B6 effect imitates (data in data/effect_models.json).

`docs/zoom/B6-EFFECT-MODELS.md` is generated from that file by
`tools/gen_effect_models_doc.py`; edit the JSON, not the doc.
"""
import json
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "effect_models.json"

BASES = ("Zoom", "Zoom / Likely", "Likely", "Guess", "Original", "Generic")

# (group in b6lab.effects, section heading), in document order
SECTIONS = (
    ("DYNAMICS", "Dynamics"),
    ("FILTER", "Filter and EQ"),
    ("DRIVE", "Drive"),
    ("PREAMP", "Preamp"),
    ("BASS AMP", "Bass amps"),
    ("CABINET", "Cabinets"),
    ("MODULATION", "Modulation and pitch"),
    ("SFX", "SFX and synth"),
    ("DELAY", "Delay"),
    ("REVERB", "Reverb"),
    ("PEDAL", "Pedal (expression)"),
    ("SND-RTN", "Effects loop"),
)

HEADER = """# B6 effect models: which real gear each effect is based on

Covers everything in the B6 effect catalog (firmware effect set as loaded by
`b6lab.effects.load()`): 116 effects, 3 effects-loop blocks and 36 impulse responses.

Sources: Zoom's effect descriptions (stored in the effect files on the pedal and in
`pedal-files/effects.json`), Zoom's FX list (`docs/zoom/E_B6_FX-list_2.txt`) and the cabinet
and IR chart (`docs/zoom/B6_CabSim-IRChart_2.txt`) (Zoom's files, not in the repository).

Note: `pedal-files/effects.json` still lists the 36 IRs twice, under category 0x1A and 0x1B.
Only 0x1B holds the IRs; 0x1A is the effects loop (FxLoop, Send, Return), which
`b6lab.effects` adds at load time.

**Basis** column:

- **Zoom**: Zoom names the gear itself ("simulation of", "models", "in the style of").
- **Likely**: our identification, from the effect name plus Zoom's description.
- **Guess**: our identification on weaker evidence.
- **Original**: Zoom says it is its own design.
- **Generic**: an effect type, no specific product behind it.
"""

REVERB_TEXT = """All generic types: {names}. Zoom names
no product for any of them.
"""

LOOP_TEXT = """FxLoop, Send and Return use the B6's own SEND/RETURN jacks, no model. This is where
Ali Martin's patches expect a Big Muff Pi and/or BOSS OC-2.
"""

IR_SECTION = """## Impulse responses

36 IRs: the 12 cabinets above, each captured with three mic setups. The chart names the
mics only as "D20" and "D57"; the cabinet effects' knob descriptions identify them as the
Electro-Voice RE-20 and the Shure SM57 (**Zoom**, e.g. AM1x15 `DYN20` / `DYN57`).

| Cabinet | On mic (D20) | 2nd IR | Room |
|---|---|---|---|
| Ampeg SVT-810E | SVT8_D20 | SVT8_D57 (on mic 2) | SVT8_Room |
| Ampeg SVT-410HLF | SVT4_D20 | SVT4_TW (tweeter mix) | SVT4_Room |
| Fender Bassman 4x12 | FDB_D20 | FDB_D57 (on mic 2) | FDB_Room |
| SWR Goliath 4x10 | SMR_D20 | SMR_TW (tweeter mix) | SMR_Room |
| Aguilar GS410 | AG_D20 | AG_TW (tweeter mix) | AG_Room |
| Trace Elliot 1048 | TE_D20 | TE_D57 (on mic 2) | TE_Room |
| Acoustic 301 | AC_D20 | AC_D57 (on mic 2) | AC_Room |
| Markbass Minimark 802 | MkB_D20 | MkB_TW (tweeter mix) | MkB_Room |
| EBS ProLine 410 | EB_D20 | EB_TW (tweeter mix) | EB_Room |
| Ampeg B-15N 1x15 | AM_D20 | AM_D57 (on mic 2) | AM_Room |
| Sunn 2x15 | SN_D20 | SN_D57 (on mic 2) | SN_Room |
| Polytone 1x15 | MT_D20 | MT_D57 (on mic 2) | MT_Room |

"Tweeter mix" = the D20 on-mic IR mixed with a D57 on the tweeter (per the chart).
"""

COUNTS = """## Counts

Of the 116 effects: Zoom names the gear for 48 (EnvFilter counted here; we add the exact
MXR model), we identify 11 more (Likely), 5 are guesses, 7 are stated Zoom originals and
45 are generic effect types.
"""


def load_models(path: Path = DATA_PATH) -> dict[str, dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _section(group: str, heading: str, models: dict) -> str:
    rows = [(n, m) for n, m in models.items() if m["group"] == group]
    out = f"## {heading}\n\n"
    if group == "REVERB":
        return out + REVERB_TEXT.format(names=", ".join(n for n, _ in rows))
    if group == "SND-RTN":
        return out + LOOP_TEXT
    out += "| Effect | Real gear | Basis | Notes |\n|---|---|---|---|\n"
    for name, m in rows:
        out += f"| {name} | {m['gear']} | {m['basis']} | {m['notes']} |".replace(" |  |", " | |") + "\n"
    return out


def render_doc(models: dict) -> str:
    parts = [HEADER]
    parts += [_section(g, h, models) for g, h in SECTIONS]
    parts += [IR_SECTION, COUNTS]
    return "\n".join(parts)
