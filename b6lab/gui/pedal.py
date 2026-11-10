"""One effect box: category, effect name, named knobs and an on/off switch.

Names come from the effect catalog (b6lab.effects, read from the pedal's own effect
files). Without a catalog entry the box shows the raw ID and knobs P1..Pn.
Knob count rule: the effect's own parameter count when known, else up to the last
non-zero decoded parameter, at least 4 (the 17 decoded params carry trailing zeros).
When available, knob limits come from the B6's captured parameter information.
Stored values remain raw; verified simple display scales are formatted separately.
Values beyond an effect's named knobs stay read-only and are marked "hidden".
"""
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDial, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QProgressBar, QToolButton, QVBoxLayout)

from b6lab.gui import theme

MIN_KNOBS = 4
MIN_WIDTH = 172
PERCENT_MAX = 100
MAC_ASSETS = Path(__file__).resolve().parents[2] / "analysis" / "mac-reference-assets"
PEDAL_ASSETS = Path(__file__).resolve().parents[2] / "analysis" / "pedal-reference-assets"


class Dial(QDial):
    """Guitar Lab's knob artwork and vertical-drag interaction.

    Scrolling the pedal row must not turn knobs that the pointer happens to pass over.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # the wheel does not give focus
        self._drag_y = None
        self._drag_value = 0.0
        self._art = QPixmap(str(MAC_ASSETS / "0030d860.png"))

    def paintEvent(self, event):
        if self._art.isNull():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1.0 if self.isEnabled() else 0.5)
        painter.drawPixmap(self.rect(), self._art)
        span = self.maximum() - self.minimum()
        fraction = (self.value() - self.minimum()) / span if span else 0
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-135 + 270 * fraction)
        painter.setPen(QPen(QColor("#aab9bb"), max(2, self.width() / 13), Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(0, -self.height() * .11), QPointF(0, -self.height() * .26))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drag_y = event.globalPosition().y()
            self._drag_value = float(self.value())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_y is None:
            return super().mouseMoveEvent(event)
        y = event.globalPosition().y()
        sensitivity = 0.1 if event.modifiers() & Qt.KeyboardModifier.ControlModifier else 1.0
        self._drag_value = min(self.maximum(), max(self.minimum(),
                               self._drag_value + (self._drag_y - y) * sensitivity))
        self._drag_y = y
        self.setValue(round(self._drag_value))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_y is not None:
            self._drag_y = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


def knob_count(params, info=None):
    last = max((i for i, v in enumerate(params) if v), default=-1)
    if info is not None and info.params:
        return max(len(info.params), last + 1)
    return max(MIN_KNOBS, last + 1)


def knob_name(info, index):
    if info is not None and index < len(info.params) and info.params[index].name:
        return info.params[index].name
    return f"P{index + 1}"


def _luma(color):
    c = QColor(color)
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


_ICON_CACHE = {}


def chain_icon(fx_id, category):
    """The pedal's own effect bitmap, with its white body filled in the B6's colour.

    The .ZD2 bitmap is 1-bit: black line art on white. On the B6 the white is the
    category colour, and on a dark body the line art is light so it stays visible.
    """
    key = (fx_id, category)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    source = PEDAL_ASSETS / f"{fx_id:08x}.bmp"
    image = QImage(str(source))
    if image.isNull():
        pix = QPixmap()
        _ICON_CACHE[key] = pix
        return pix
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    body = QColor(theme.ICON_COLORS_BY_ID.get(fx_id) or theme.ICON_COLORS.get(category, theme.BORDER))
    ink = QColor("#f2f2f2") if _luma(body) < 70 else QColor("#111111")
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixelColor(x, y, body if image.pixelColor(x, y).red() > 128 else ink)
    pix = QPixmap.fromImage(image)
    _ICON_CACHE[key] = pix
    return pix


def knob_tip(info, index):
    if info is None or index >= len(info.params):
        return ""
    p = info.params[index]
    return p.explanation + (" (expression pedal)" if p.pedal else "")


def knob_value(info, index, value, raw=False):
    if info is None or index >= len(info.params):
        return f"raw {value}"
    return info.params[index].format_value(value, raw=raw)


class PedalBox(QFrame):
    param_changed = Signal(int, int, int)  # slot, index, value
    toggled = Signal(int, bool)

    def __init__(self, effect, wide=False, info=None, parent=None):
        super().__init__(parent)
        self.slot = effect.slot
        self.setMinimumWidth(int(MIN_WIDTH * (1.5 if wide else 1)))
        self.setMaximumWidth(int(244 * (1.5 if wide else 1)))
        self.wide = wide
        self.setObjectName("pedal")
        self.setStyleSheet(
            "QFrame#pedal { background: #1a1e24; border: 0; }"
            f"QFrame#pedal QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 4)
        lay.setSpacing(0)
        face = QFrame()
        face.setObjectName("pedalFace")
        face.setStyleSheet("QFrame#pedalFace { background: #364250; border-radius: 4px; }")
        face_layout = QVBoxLayout(face)
        face_layout.setContentsMargins(8, 3, 8, 7)
        face_layout.setSpacing(2)
        title = QLabel(f"{effect.slot + 1}              TYPE  ≡")
        title.setStyleSheet("color: #cbdade; font-size: 10px;")
        title.setToolTip("Changing effect type is not yet available")
        face_layout.addWidget(title)
        screen = QFrame()
        screen.setObjectName("pedalScreen")
        screen.setMinimumHeight(67)
        screen.setStyleSheet("QFrame#pedalScreen { background: #d8f7ff; border-radius: 4px; }")
        screen_layout = QVBoxLayout(screen)
        screen_layout.setContentsMargins(5, 2, 5, 2)
        screen_layout.setSpacing(0)
        heading = QHBoxLayout()
        self.category_label = QLabel(effect.category if effect.fx_id else "EMPTY")
        self.category_label.setStyleSheet("color: #343b3d; font-size: 11px;")
        self.info = info
        if info is not None:
            self.id_label = QLabel(info.name)
            self.id_label.setStyleSheet("color: #343b3d; font-weight: bold; font-size: 11px;")
            tip = f"{info.description}\n\nID 0x{effect.fx_id:08X}" if info.description else f"ID 0x{effect.fx_id:08X}"
            self.id_label.setToolTip(tip)
        else:
            self.id_label = QLabel(f"0x{effect.fx_id:08X}")
            self.id_label.setStyleSheet("color: #343b3d; font-size: 10px;")
        heading.addWidget(self.category_label)
        heading.addStretch(1)
        heading.addWidget(self.id_label)
        screen_layout.addLayout(heading)

        self.dials, self.value_labels, self.value_bars = [], [], []
        n = knob_count(effect.params, info) if effect.fx_id else 0
        main = QGridLayout()
        main.setSpacing(1)
        dial_rows = []
        self.max_values = []
        self.normal_maxima = []
        for i in range(n):
            val = effect.params[i]
            hidden = info is not None and bool(info.params) and i >= len(info.params)
            editable = effect.editable(i) and not hidden
            size = 44 if editable else 36
            dial = Dial()
            dial.setNotchesVisible(False)
            dial.setFixedSize(size, size)
            self.max_values.append(effect.max_value(i))
            param = info.params[i] if info is not None and i < len(info.params) else None
            known_max = param.raw_max if param else None
            if known_max is not None and not 0 <= known_max <= self.max_values[i]:
                known_max = None
            maximum = known_max if known_max is not None else (
                PERCENT_MAX if editable and val <= PERCENT_MAX else self.max_values[i])
            self.normal_maxima.append(known_max)
            # Keep unexpected stored values visible without ever sending a clamped value.
            invalid_stored = known_max is not None and val > known_max
            dial.setRange(0, max(maximum, val))
            dial.setValue(val)
            dial.setEnabled(editable and not invalid_stored)
            small = "" if editable else " font-size: 9px;"
            name = QLabel(knob_name(info, i))
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setStyleSheet(f"color: #343b3d; font-size: 10px;{small}")
            value = QLabel(knob_value(info, i, val))
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setStyleSheet(f"color: #343b3d; font-size: 10px;{small}")
            bar = QProgressBar()
            bar.setRange(0, max(1, maximum, val))
            bar.setValue(val)
            bar.setTextVisible(False)
            bar.setFixedHeight(9)
            bar.setStyleSheet("QProgressBar { background: #d8f7ff; border: 1px solid #343b3d; }"
                              "QProgressBar::chunk { background: #343b3d; }")
            tip = knob_tip(info, i)
            if known_max is not None:
                if param.display_labels:
                    limits = "Options: " + ", ".join(param.display_labels)
                elif param.display_min is not None:
                    limits = f"Range: {param.format_value(0)} – {param.format_value(known_max)}"
                else:
                    limits = f"Raw range: 0 – {known_max}; display mapping unknown"
                tip = f"{tip}\n{limits}".strip()
            else:
                tip = f"{tip}\nRange and display mapping unknown; value is raw".strip()
            if invalid_stored:
                tip += f"\nStored raw value {val} exceeds the captured maximum {known_max}; read-only"
            if hidden:
                tip = "hidden: a value the pedal stores but does not show as a knob (read-only)"
                name.setText(f"{name.text()} hidden")
            dial.setToolTip(tip)
            name.setToolTip(tip)
            dial.valueChanged.connect(lambda v, i=i: self._dial_changed(i, v))
            r, c = i // 4, i % 4
            main.addWidget(name, r * 3, c)
            main.addWidget(bar, r * 3 + 1, c)
            main.addWidget(value, r * 3 + 2, c)
            if c == 0:
                dial_rows.append(QHBoxLayout())
                dial_rows[-1].setSpacing(0)
            dial_rows[-1].addWidget(dial, alignment=Qt.AlignmentFlag.AlignCenter)
            self.dials.append(dial)
            self.value_labels.append(value)
            self.value_bars.append(bar)
        screen_layout.addLayout(main)
        face_layout.addWidget(screen)
        for row in dial_rows:
            face_layout.addLayout(row)
        lay.addWidget(face)

        foot = QHBoxLayout()
        self.raw_check = QCheckBox("raw")
        self.raw_check.setEnabled(n > 0 and any(effect.editable(i) for i in range(n)))
        self.raw_check.toggled.connect(self._raw_toggled)
        self.on_check = QToolButton()
        self.on_check.setCheckable(True)
        self.on_check.setAutoRaise(True)
        self.on_check.setFixedSize(140, 48)
        self.on_check.setStyleSheet("QToolButton { background: #364250; border: 0; border-radius: 4px; }")
        self.on_check.setIcon(QIcon(str(MAC_ASSETS / "00307130.png")))
        self.on_check.setIconSize(QSize(44, 44))
        self.on_check.setToolTip("Bypass effect")
        self.on_check.setChecked(effect.on)
        self.on_check.toggled.connect(lambda on: self.toggled.emit(self.slot, on))
        self.indicator = QLabel()
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_indicator(effect.on)
        self.on_check.toggled.connect(self._set_indicator)
        switch = QVBoxLayout()
        switch.setSpacing(0)
        switch.addWidget(self.indicator, alignment=Qt.AlignmentFlag.AlignCenter)
        switch.addWidget(self.on_check, alignment=Qt.AlignmentFlag.AlignCenter)
        foot.addWidget(self.raw_check)
        foot.addStretch(1)
        foot.addLayout(switch)
        foot.addStretch(1)
        lay.addLayout(foot)
        lay.addStretch(1)

    def _dial_changed(self, index, value):
        self.value_labels[index].setText(knob_value(self.info, index, value, self.raw_check.isChecked()))
        self.value_bars[index].setValue(value)
        self.param_changed.emit(self.slot, index, value)

    def _set_indicator(self, on):
        image = "003065c0.png" if on else "003060f0.png"
        self.indicator.setPixmap(QPixmap(str(MAC_ASSETS / image)).scaled(
            18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def set_on(self, on):
        """Show `on` without emitting `toggled` (used for the state the pedal reports)."""
        self.on_check.blockSignals(True)
        self.on_check.setChecked(on)
        self.on_check.blockSignals(False)
        self._set_indicator(on)

    def _raw_toggled(self, raw):
        for i, (dial, top, known_max) in enumerate(zip(self.dials, self.max_values, self.normal_maxima)):
            if not dial.isEnabled():
                continue
            v = dial.value()
            dial.blockSignals(True)
            dial.setMaximum(known_max if known_max is not None else
                            top if raw or v > PERCENT_MAX else PERCENT_MAX)
            dial.setValue(v)
            dial.blockSignals(False)
            self.value_bars[i].setMaximum(max(1, dial.maximum()))
            self.value_bars[i].setValue(v)
            self.value_labels[i].setText(knob_value(self.info, i, v, raw))
