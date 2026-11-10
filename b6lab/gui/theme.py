"""Palette and category colours used by the editor widgets."""

BG = "#16181d"
PANEL = "#1f232a"
PANEL_ALT = "#272c35"
BORDER = "#343a46"
TEXT = "#e3e6eb"
TEXT_DIM = "#8a92a0"
ACCENT = "#4fa3e0"
OK = "#4cc27a"
BAD = "#e0605a"

CATEGORY_COLORS = {
    "DYNAMICS": "#e0a458",
    "FILTER": "#b58be0",
    "DRIVE": "#e0605a",
    "PREAMP": "#e08a4f",
    "BASS AMP": "#c9a227",
    "CABINET": "#8c7a6b",
    "MODULATION": "#4fc1c9",
    "SFX": "#d86fb5",
    "DELAY": "#5b8fe0",
    "REVERB": "#7a7de0",
    "PEDAL": "#8fbf4f",
    "SND-RTN": "#6fa89a",
    "IR": "#a0a7b4",
}

# Body colour of the effect icon on the B6. Sampled from the official effects list
# (docs/zoom/E_B6_FX-list_2.pdf): the pedal files store the same art as a white
# 1-bit bitmap, and the pedal fills that white with these colours.
# PREAMP, BASS AMP and CABINET are drawn as dark pedals there. Most PEDAL effects
# are dark too; the three exceptions below are the orange and cyan ones.
ICON_COLORS = {
    "DYNAMICS": "#b000f8",
    "FILTER": "#f88000",
    "DRIVE": "#f80000",
    "PREAMP": "#1c1c1c",
    "BASS AMP": "#1c1c1c",
    "CABINET": "#1c1c1c",
    "MODULATION": "#00c8e8",
    "SFX": "#f8e800",
    "DELAY": "#0030c0",
    "REVERB": "#00f800",
    "PEDAL": "#1c1c1c",
    "SND-RTN": "#f86800",
    "IR": "#00b038",
}
ICON_COLORS_BY_ID = {
    0x0B890020: "#ff7700",  # PDL Reso
    0x0B890030: "#00caec",  # Ba PDLPit
    0x0B890040: "#00caec",  # Ba PDLMnP
}

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {PANEL}; }}
QTabBar::tab {{ background: {BG}; color: {TEXT_DIM}; padding: 8px 18px; border: 0; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:disabled {{ color: {BORDER}; }}
QStatusBar {{ background: {PANEL}; color: {TEXT_DIM}; }}
QLabel#brand {{ font-size: 18px; font-weight: bold; letter-spacing: 2px; }}
"""
