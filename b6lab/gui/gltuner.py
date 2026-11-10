"""Guitar Lab's tuner display (ColorTunerComponent, paint FUN_100276480), shown in the chain's
place while TUNER is on (seen in Guitar Lab on the B6, 2026-11-09).

- pitch byte (CC 99) -> cents (FUN_1000767c0): 0 / 127 = no signal; < 51: b - 51;
  51..59: (b - 50) x 0.1 - 1; 64: 0 (in tune); 60..68: (b - 59) x 0.02 - 0.1;
  69..77: (b - 69) x 0.1 + 0.1; 78..126: b - 77;
- 9 boxes 48 x 24 at x = 0, 52 .. 416, y = 2, filled (21,33,48) overlaid with red (green
  (170,242,0) for the centre box) at the strength of that box's curve at round(cents) + 50
  (FUN_100276b60): an 18-step curve shifted 0, 10, 20, 30, 40, 53, 63, 73, 83 steps (table
  DAT_100496100) into a 101-step range;
- arrows (images at half size): for cents <= 0 at (190, 30), for cents >= 0 at (264, 30);
  0048c780 / 0048ccb0 off pitch, 0048c9d0 / 0048cf00 in tune;
- the note (CC 98) bold 24 white centred in (208, 28, 48, 24): A A# B C C# D D# E F F# G G#
  (10 = G seen with G on screen; 12 = no note); the calibration "<Hz>" bold 14 (225,248,255)
  at (w - 110, 32, 24, 16), justification 0x24.
"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from b6lab.gui.glui import CENTRED, draw_fitted_text, font, image, rgb

BASE = rgb(21, 33, 48)
SHIFTS = (0, 10, 20, 30, 40, 53, 63, 73, 83)
# the strengths per box, extracted from the decompile (FUN_100276b60's FUN_100277910 calls); the
# centre box has 21. Checked on the B6 screenshot: at +9 cents box 4 = 0.4, box 5 = 0.9.
CURVES = (
    (0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8, 0.8, 0.6, 0.6, 0.6, 0.4, 0.4),
    (0.4, 0.4, 0.4, 0.6, 0.6, 0.6, 0.8, 0.8, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8, 0.6, 0.6, 0.4, 0.4),
    (0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8, 0.6, 0.6, 0.4, 0.4),
    (0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3),
    (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4,
     0.3),
    (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8, 0.6, 0.6, 0.4, 0.4),
    (0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.8, 0.6, 0.6, 0.4, 0.4),
    (0.4, 0.4, 0.6, 0.6, 0.8, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.6, 0.6, 0.6, 0.4, 0.4, 0.4),
    (0.4, 0.4, 0.6, 0.6, 0.6, 0.8, 0.8, 0.8, 1.0, 1.0, 1.0, 1.0, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6),
)
NOTES = ("A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#")


def cents(byte):
    if byte is None or byte in (0, 0x7F):
        return None
    if byte < 0x33:
        return byte - 51.0
    if byte < 0x3C:
        return (byte - 50.0) * 0.1 - 1.0
    if byte < 0x45:
        return 0.0 if byte == 0x40 else (byte - 59.0) * 0.02 - 0.1
    if byte < 0x4E:
        return (byte - 69.0) * 0.1 + 0.1
    return byte - 77.0


def box_strength(box, value):
    curve = [0.0] * SHIFTS[box] + list(CURVES[box])
    i = int(round(value)) + 50
    return curve[i] if 0 <= i < len(curve) else 0.0


class TunerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.note, self.pitch, self.calibration = None, None, 440

    def set_reading(self, note, pitch):
        self.note, self.pitch = note, pitch
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        value = cents(self.pitch)
        if value is not None:
            left, right = ("0048c9d0.png", "0048cf00.png") if value == 0 else ("0048c780.png", "0048ccb0.png")
            for name, x, show in ((left, 190, value <= 0), (right, 264, value >= 0)):
                if show:
                    img = image(name)
                    p.drawImage(QRectF(x, 30, img.width() / 2, img.height() / 2), img)
        for box in range(9):
            colour = QColor(BASE)
            if value is not None:
                lit = rgb(170, 242, 0) if box == 4 else rgb(255, 0, 0)
                a = box_strength(box, value)
                colour = QColor(int(BASE.red() + (lit.red() - BASE.red()) * a),
                                int(BASE.green() + (lit.green() - BASE.green()) * a),
                                int(BASE.blue() + (lit.blue() - BASE.blue()) * a))
            p.fillRect(QRectF(box * 52, 2, 48, 24), colour)
        if self.note is not None and 0 <= self.note < len(NOTES) and value is not None:
            p.setPen(rgb(255, 255, 255))
            draw_fitted_text(p, NOTES[self.note], QRectF(208, 28, 48, 24), font(24, True), CENTRED)
        p.setPen(rgb(225, 248, 255))
        draw_fitted_text(p, str(self.calibration), QRectF(self.width() - 110, 32, 24, 16), font(14, True), CENTRED)
