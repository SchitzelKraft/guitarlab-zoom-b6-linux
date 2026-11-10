"""Guitar Lab's effect pedal (EffectPedalComponent) and its knobs.

From the decompiled Mac binary (analysis/ui-trace):
- layout FUN_100005d70: s = width / 240; four knobs 54s square at y=104s, from x=8s in steps
  of (width - 8s) / 4; footswitch (centre - 26s, 206s, 52s, 52s); TYPE button (100s, 3s, 60s, 16s);
- face FUN_100004bd0: body (54,66,80) rounded 4, height 168s; footswitch plate
  (25s, 204s, 190s, 48s); LCD (10s, 36s, 220s, 66s) in (216,247,255); separator line at 22s,
  3s thick in (26,30,36); number at (8s, 3s, 16s, 16s) bold 15s in (203,218,222), orange
  (247,170,103) when selected; "TYPE" with lines either side;
- paint FUN_1000030b0: LED 24s at (centre - 12s, 174s); category "[DRIVE]" bold 14s at
  (10s, 42s, 96s, 15s); name tag image at (104s, 42s) and name bold 15s in (216,247,255) at
  (110s, 42s, 96s, 16s); per knob, from x=16s in steps of (width - 16s) / 4: name at
  (0, 61s, 42s, 11s), bar outline (0, 74s, 42s, 10s), value at (0, 88s, 42s, 11s), Arial 13s,
  squeezed down to 60 %; effects with pedal + 0x154 & 0x40 (ZD2 INFO bit 0, effects.has_sliders:
  BassGEQ, St Ba GEQ) draw a small vertical slider instead (FUN_1000055a0);
- knob drawing GuitarLabLookAndFeel::drawRotarySlider (FUN_100018860): image 0030f0e0
  (0030d860 while the mouse is over it) and a pointer from radius 2k to size/5, 2k thick
  (k = height / 54), colour (143,159,167) at 70 % (100 % under the mouse), JUCE's default
  rotary range 216 deg + 288 deg x position.
A double-width effect shows as two pedals: the head (kind 1) with knobs 1-4 and the first
half of the name, the tail (kind 2) with knobs 5-8 and the second half.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractSlider, QWidget

from b6lab import effects
from b6lab.gui.glui import CENTRED, RIGHT, VCENTRE, ImageButton, draw_fitted_text, font, image, rgb

FACE = rgb(54, 66, 80)
LCD = rgb(216, 247, 255)
LCD_RING = rgb(216, 247, 255)   # DAT_10053d040, the handle's inner ring (same as LCD)
INK = rgb(52, 59, 61)
BACKGROUND = rgb(26, 30, 36)
KNOB, KNOB_OVER = "0030f0e0.png", "0030d860.png"
FOOTSWITCH, FOOTSWITCH_DOWN = "00307130.png", "00308b10.png"
LED_ON, LED_OFF = "003065c0.png", "003060f0.png"
TAGS = {0: "00306e70.png", 1: "00305b90.png", 2: "00305e50.png"}
POINTER = rgb(143, 159, 167)
DRAG_PIXELS = 250  # juce::Slider default mouse drag sensitivity (pixels for the full range)


class Knob(QAbstractSlider):
    """A JUCE rotary slider (RotaryHorizontalVerticalDrag) drawn like Guitar Lab's."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._drag = None
        self.text_box = None  # (width, height) for a value text below the knob (patch level)

    def knob_rect(self):
        if self.text_box:
            return QRectF(0, 0, self.width(), self.height() - self.text_box[1])
        return QRectF(0, 0, self.width(), self.height())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.knob_rect()
        over = self.underMouse() or self._drag is not None
        img = image(KNOB_OVER if over else KNOB)
        side = min(r.width(), r.height())
        scale = min(r.width() / img.width(), r.height() / img.height())
        iw, ih = img.width() * scale, img.height() * scale
        p.drawImage(QRectF(r.x() + (r.width() - iw) / 2, r.y() + (r.height() - ih) / 2, iw, ih), img)
        span = self.maximum() - self.minimum()
        pos = (self.value() - self.minimum()) / span if span else 0.0
        angle = 1.2 * math.pi + pos * 1.6 * math.pi
        k = r.height() / 54
        colour = QColor(POINTER) if self.isEnabled() else QColor(0x80, 0x80, 0x80, 0x80)
        if self.isEnabled():
            colour.setAlphaF(1.0 if (self.underMouse() and self.isEnabled()) else 0.7)
        path = QPainterPath()
        path.moveTo(0, -2 * k)
        path.lineTo(0, -side / 5)
        p.translate(r.x() + r.width() / 2, r.y() + r.height() / 2)
        p.rotate(math.degrees(angle))
        p.setPen(QPen(colour, 2 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawPath(path)
        p.resetTransform()
        if self.text_box:
            w, h = self.text_box
            p.setPen(rgb(223, 248, 255))
            draw_fitted_text(p, str(self.value()), QRectF((self.width() - w) / 2, self.height() - h, w, h),
                             font(12), CENTRED)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._drag = (event.globalPosition(), float(self.value()))
            self.setSliderDown(True)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            self.update()
            return
        start, value = self._drag
        d = event.globalPosition() - start
        span = self.maximum() - self.minimum()
        # RotaryHorizontalVerticalDrag: right and up both increase
        new = value + (d.x() - d.y()) / DRAG_PIXELS * span
        self.setValue(round(min(self.maximum(), max(self.minimum(), new))))

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.setSliderDown(False)
            self.update()

    def wheelEvent(self, event):
        event.ignore()  # Guitar Lab's knobs do not react to the scroll wheel

    def leaveEvent(self, _event):
        self.update()


def _half_name(name, kind):
    """A double-width effect's name split over its two pedals (ceil(len / 2))."""
    n = math.ceil(len(name) * 0.5)
    if kind == 1:
        return name[:n]
    if kind == 2:
        return name[n:]
    return name


class Pedal(QWidget):
    """One effect pedal: header, LCD, four knobs, LED and footswitch."""

    param_changed = Signal(int, int, int)  # effect entry (slot), knob index, value
    toggled = Signal(int, bool)

    def __init__(self, effect, info=None, kind=0, head=None, parent=None):
        super().__init__(parent)
        self.effect = effect
        self.slot = effect.slot
        self.kind = kind          # 0 single, 1 head of a double-width effect, 2 its tail
        self.head = head or effect  # the entry whose knobs are shown (the head for a tail)
        self.info = info
        self.selected = False
        self.first = 4 if kind == 2 else 0
        self.dials = []
        for i in range(4):
            knob = Knob(self)
            index = self.first + i
            param = info.params[index] if info is not None and index < len(info.params) else None
            if param is None:
                knob.hide()
            else:
                top = param.raw_max if param.raw_max is not None else self.head.max_value(index)
                knob.setRange(0, max(top, self.head.params[index]))
                knob.setValue(self.head.params[index])
                knob.setEnabled(self.head.editable(index) and self.head.params[index] <= top)
                knob.setToolTip(param.explanation)
            knob.valueChanged.connect(lambda v, i=index: self._knob_changed(i, v))
            self.dials.append(knob)
        self.on_check = ImageButton(FOOTSWITCH, FOOTSWITCH, FOOTSWITCH_DOWN, FOOTSWITCH, placement="fit", parent=self)
        self.on_check.setCheckable(True)
        self.on_check.setChecked(self._on())
        # The footswitch shows its pressed image only while it is held down.
        self.on_check.images["down"] = FOOTSWITCH_DOWN
        self.on_check.toggled.connect(self._switched)
        self.on_check._state = self._footswitch_state
        self.type_button = ImageButton(None, parent=self)
        self.type_button.setToolTip("Effect type")

    def _footswitch_state(self):
        b = self.on_check
        if not b.isEnabled():
            return "disabled"
        if b.isDown():
            return "down"
        return "normal"

    def _on(self):
        return self.effect.on if self.kind != 2 else False

    def _switched(self, on):
        self.update()
        if self.kind == 2:
            return
        self.toggled.emit(self.slot, on)

    def set_on(self, on):
        """Show `on` without emitting `toggled` (the state the pedal reports)."""
        self.on_check.blockSignals(True)
        self.on_check.setChecked(on)
        self.on_check.blockSignals(False)
        self.update()

    def _knob_changed(self, index, value):
        self.update()
        self.param_changed.emit(self.head.slot, index, value)

    def value_text(self, i):
        """The value shown under knob i of this pedal (i = 0..3)."""
        index = self.first + i
        if self.info is None or index >= len(self.info.params):
            return ""
        return _format(self.info.params[index], self.dials[i].value())

    # layout ---------------------------------------------------------------------
    def scale(self):
        return self.width() / 240

    def resizeEvent(self, _event):
        s, w = self.scale(), self.width()
        x0 = int(s * 8)
        step = int((w - x0) * 0.25)
        y, size = int(s * 104), int(s * 54)
        for i, knob in enumerate(self.dials):
            knob.setGeometry(x0 + i * step, y, size, size)
        self.on_check.setGeometry(int(s * -26 + w // 2), int(s * 206), int(s * 52), int(s * 52))
        self.type_button.setGeometry(int(s * 100), int(s * 3), int(s * 60), int(s * 16))
        self.type_button.setVisible(self.kind != 2)

    # drawing --------------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        s, w = self.scale(), self.width()
        self._face(p, s, w)
        # LED (FUN_1000030b0)
        led = image(LED_ON if self.on_check.isChecked() and self.kind != 2 else LED_OFF)
        p.drawImage(QRectF(s * -12 + w // 2, s * 174, led.width() * 0.5 * s, led.height() * 0.5 * s), led)
        if self.info is None:
            return
        self._lcd(p, s, w)

    def _face(self, p, s, w):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(FACE)
        p.drawRoundedRect(QRectF(0, 0, w, s * 168), 4, 4)
        p.drawRoundedRect(QRectF(s * 25, s * 204, s * 190, s * 48), s * 4, s * 4)
        p.setBrush(LCD)
        p.drawRoundedRect(QRectF(s * 10, s * 36, s * 220, s * 66), 4, 4)
        p.setPen(QPen(BACKGROUND, s * 3))
        p.drawLine(QPointF(0, s * 22), QPointF(w, s * 22))
        p.setPen(rgb(247, 170, 103) if self.selected else rgb(203, 218, 222))
        draw_fitted_text(p, str(self.slot + 1), QRectF(int(s * 8), int(s * 3), int(s * 16), int(s * 16)),
                         font(s * 15, True), CENTRED)
        if self.kind != 2:
            pen = QPen(p.pen().color(), 1)
            p.setPen(pen)
            p.drawLine(QPointF(s * 32, s * 10), QPointF(s * 92, s * 10))
            draw_fitted_text(p, "TYPE", QRectF(int(s * 100), int(s * 3), int(s * 40), int(s * 16)),
                             font(s * 15, True), CENTRED)
            p.drawLine(QPointF(s * 164, s * 10), QPointF(s * 220, s * 10))
            for dy in (0, 2 * s, 4 * s):
                p.drawLine(QPointF(s * 144, s * 10 + dy), QPointF(s * 156, s * 10 + dy))

    def _lcd(self, p, s, w):
        tag = image(TAGS[self.kind])
        tx = s * (16 if self.kind == 2 else 104)
        p.drawImage(QRectF(tx, s * 42, tag.width() * 0.5 * s, tag.height() * 0.5 * s), tag)
        p.setPen(LCD)
        nx = int((32 if self.kind == 2 else 110) * s)
        draw_fitted_text(p, _half_name(self.info.name, self.kind), QRectF(nx, int(s * 42), int(s * 96), int(s * 16)),
                         font(s * 15, True), CENTRED)
        if self.kind != 2:
            p.setPen(INK)
            draw_fitted_text(p, f"[{self.info.group}]", QRectF(int(s * 10), int(s * 42), int(s * 96), int(s * 15)),
                             font(s * 14, True), CENTRED)
        step = (w - s * 16) * 0.25
        x = s * 16
        for i, knob in enumerate(self.dials):
            index = self.first + i
            if index >= len(self.info.params):
                break
            param = self.info.params[index]
            value = knob.value()
            top = knob.maximum() or 1
            frac = value / top
            p.save()
            p.translate(int(x), 0)
            p.setPen(INK)
            f13 = font(s * 13)
            if effects.slider_param(self.info.fx_id, index):
                # f = value / max, 0 when max is 0 or the value is above it (FUN_1000030b0)
                pmax = param.raw_max
                self._geq_slider(p, s, value / pmax if pmax and value <= pmax else 0.0)
                cw = int(s * 42 * 0.7)
                draw_fitted_text(p, param.name, QRectF(0, int(s * 61), cw, int(s * 11)), f13, RIGHT | VCENTRE)
                draw_fitted_text(p, _format(param, value), QRectF(0, int(s * 88), cw, int(s * 11)), f13,
                                 RIGHT | VCENTRE)
            else:
                p.setPen(QPen(INK, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(0.5, s * 74 + 0.5, s * 42 - 1, s * 10 - 1))
                p.fillRect(QRectF(0, s * 74, frac * s * 42, s * 10), INK)
                draw_fitted_text(p, _format(param, value), QRectF(0, int(s * 88), int(s * 42), int(s * 11)), f13,
                                 CENTRED, 0.6)
                draw_fitted_text(p, param.name, QRectF(0, int(s * 61), int(s * 42), int(s * 11)), f13, CENTRED, 0.6)
            p.restore()
            x += step

    def _geq_slider(self, p, s, frac):
        """FUN_1000055a0: track, five ticks and the handle of a GEQ band."""
        p.fillRect(QRectF(s * 32, s * 62, s * 6, s * 35), INK)
        step = s * 35 * 0.25
        pen = QPen(INK, 2 * s)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)   # JUCE Path::addLineSegment: butt ends
        p.setPen(pen)
        y = s * 62
        for _ in range(5):
            p.drawLine(QPointF(s * 31, y), QPointF(s * 39, y))
            y += step
        y1 = (s * 35 - s * 6) * (1 - frac) + s * 62
        # JUCE drawRect strokes inside the rectangle and fills nothing: the middle stays INK
        _ring(p, QRectF(s * 30, y1, s * 10, s * 6), s, INK)
        _ring(p, QRectF(s * 31, y1 + s, s * 8, s * 4), s, LCD_RING)


def _ring(p, r, t, colour):
    """JUCE Graphics::drawRect(r, thickness): four filled strips inside r."""
    p.fillRect(QRectF(r.x(), r.y(), r.width(), t), colour)
    p.fillRect(QRectF(r.x(), r.bottom() - t, r.width(), t), colour)
    p.fillRect(QRectF(r.x(), r.y() + t, t, r.height() - 2 * t), colour)
    p.fillRect(QRectF(r.right() - t, r.y() + t, t, r.height() - 2 * t), colour)


def _format(param, value):
    text = param.format_value(value)
    return str(value) if text.startswith("raw ") else text
