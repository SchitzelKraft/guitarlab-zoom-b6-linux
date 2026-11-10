"""Building blocks that reproduce Guitar Lab's JUCE drawing in Qt.

Guitar Lab 7.3 is a JUCE application. Its layout, colours, fonts and images were read from
the decompiled Mac binary (analysis/ui-trace/classes/*.c, image pointers resolved in
analysis/ui-trace/png-pointers.json) and checked against screenshots of the Windows build
(analysis/ui-reference/win). The helpers here mimic the JUCE behaviour those numbers rely on:

- fonts: JUCE's `Font(height)` is the typeface's ascent + descent in pixels, not its em size;
  every font in Guitar Lab is Arial (Liberation Sans on Linux, as under Wine), optionally bold;
- text: `Graphics::drawFittedText` squeezes a line that is too wide horizontally, down to 70 %
  (JUCE's default minimum horizontal scale), before it falls back to an ellipsis;
- images: the 2x artwork is drawn at half size;
- `ImageButton`: HSImageButton, four images (normal, over, down/on, disabled) and an optional
  caption above the image in a state colour.
"""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractButton, QWidget

ROOT = Path(__file__).resolve().parents[2]
MAC_ASSETS = ROOT / "analysis" / "mac-reference-assets"
DOWNLOADS = ROOT / "analysis" / "win-download"

# Liberation Sans (= Arial metrics): OS/2 winAscent 1854, winDescent 434, 2048 units per em.
ASCENT, DESCENT = 1854 / 2048, 434 / 2048
MIN_HSCALE = 0.7  # juce::Font::getDefaultMinimumHorizontalScaleFactor()

# juce::Justification flags
LEFT, RIGHT, HCENTRE, TOP, BOTTOM, VCENTRE = 1, 2, 4, 8, 16, 32
CENTRED = HCENTRE | VCENTRE


def rgb(r, g, b, a=255):
    return QColor(r, g, b, a)


@lru_cache(maxsize=None)
def image(name):
    """An extracted Mac image (e.g. "002ef7b0.png") or a downloaded one ("model_image3-B6.png")."""
    path = MAC_ASSETS / name
    if not path.exists():
        path = DOWNLOADS / name
    if not path.exists():
        path = Path(__file__).resolve().parent / "assets" / name   # B6 Lab's own (the Tux button)
    img = QImage(str(path))
    if img.isNull():
        raise FileNotFoundError(path)
    return img


def half(name):
    """The artwork at its on-screen size (Guitar Lab draws its 2x images at scale 0.5)."""
    img = image(name)
    return img.width() / 2, img.height() / 2


def font(height, bold=False):
    """JUCE `Font("Arial", height, bold)`: `height` is ascent + descent in pixels."""
    f = QFont("Arial")
    f.setPixelSize(1)  # reset, then set the fractional em size through the point size
    em = height / (ASCENT + DESCENT)
    f.setPointSizeF(em * 72 / 96)  # B6 Lab renders at 96 logical dpi (see app.main)
    f.setBold(bold)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setKerning(True)
    # JUCE anti-aliases text in greyscale; Qt would use coloured subpixel rendering
    f.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
    return f


def font_height(f):
    """The JUCE height of a QFont made by font()."""
    return f.pointSizeF() * 96 / 72 * (ASCENT + DESCENT)


def draw_fitted_text(p, text, rect, f, justification=CENTRED, min_hscale=MIN_HSCALE):
    """Single-line juce::Graphics::drawFittedText: squeeze to fit, then an ellipsis."""
    text = text.strip()
    if not text:
        return
    rect = QRectF(rect)
    fm = QFontMetricsF(f)
    width = fm.horizontalAdvance(text)
    scale = 1.0
    if width > rect.width():
        scale = max(min_hscale, rect.width() / width)
        if width * scale > rect.width():
            while text and fm.horizontalAdvance(text + "...") * scale > rect.width():
                text = text[:-1]
            text = text.rstrip() + "..."
        width = fm.horizontalAdvance(text) * scale
    h = font_height(f)
    em = f.pointSizeF() * 96 / 72
    if justification & LEFT:
        x = rect.left()
    elif justification & RIGHT:
        x = rect.right() - width
    else:
        x = rect.left() + (rect.width() - width) / 2
    if justification & TOP:
        y = rect.top()
    elif justification & BOTTOM:
        y = rect.bottom() - h
    else:
        y = rect.top() + (rect.height() - h) / 2
    p.save()
    p.setFont(f)
    p.translate(x, y + ASCENT * em)
    p.scale(scale, 1.0)
    p.drawText(QPointF(0, 0), text)
    p.restore()


def draw_half(p, name, x, y):
    """Draw 2x artwork at half size with its top-left at (x, y)."""
    w, h = half(name)
    p.drawImage(QRectF(x, y, w, h), image(name))


class ImageButton(QAbstractButton):
    """Guitar Lab's HSImageButton (constructor FUN_10005b7e0, paint FUN_10005bd20).

    Images: normal, over, down (also shown while toggled on) and disabled. With `caption`,
    the text is drawn on top (bold Arial 12 by default) in the colour of the state:
    normal (223,248,254), over white, down/on (247,170,103), disabled (42,46,54).
    `placement`: "centre" draws the image at half size centred; "fit" keeps its aspect
    ratio, fills the width and sits at the bottom (the editor and nav bar buttons).
    """

    def __init__(self, normal, over=None, down=None, disabled=None, caption="", placement="centre",
                 caption_font=None, parent=None):
        super().__init__(parent)
        self.images = {"normal": normal, "over": over, "down": down, "disabled": disabled}
        self.caption = caption
        self.placement = placement
        self.caption_font = caption_font or font(12, True)
        self.colours = {"normal": rgb(223, 248, 254), "over": rgb(255, 255, 255),
                        "down": rgb(247, 170, 103), "disabled": rgb(42, 46, 54)}
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _state(self):
        if not self.isEnabled():
            return "disabled"
        if self.isDown() or self.isChecked():
            return "down"
        if self.underMouse():
            return "over"
        return "normal"

    def _image_for(self, state):
        if state == "disabled":
            return self.images["disabled"] or self.images["normal"]
        if state == "down":
            return self.images["down"] or self.images["over"] or self.images["normal"]
        if state == "over":
            return self.images["over"] or self.images["normal"]
        return self.images["normal"]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        state = self._state()
        name = self._image_for(state)
        if name:
            img = image(name)
            w, h = self.width(), self.height()
            if self.placement == "fit":
                ratio = img.height() / img.width()
                if ratio <= h / w:
                    iw, ih = w, round(ratio * w)
                else:
                    iw, ih = round(h / ratio), h
                x, y = (w - iw) // 2, h - ih
            else:
                iw, ih = img.width() // 2, img.height() // 2
                x, y = (w - iw) // 2, (h - ih) // 2
            p.drawImage(QRectF(x, y, iw, ih), img)
        if self.caption:
            p.setPen(self.colours[state])
            draw_fitted_text(p, self.caption, QRectF(0, 0, self.width(), font_height(self.caption_font) + 4),
                             self.caption_font, CENTRED)


class Painted(QWidget):
    """A widget drawn by a function: `paint(painter, widget)`; for plain JUCE components."""

    def __init__(self, paint, parent=None):
        super().__init__(parent)
        self._paint = paint

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._paint(p, self)


class Clickable(Painted):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


def pixmap(name):
    return QPixmap.fromImage(image(name))


def stretch_layout(total, items):
    """juce::StretchableLayoutManager (horizontal): items are (min, max, preferred), negative
    values are proportions of `total`. Starts from the preferred sizes, then shares out the
    space left over (or missing) in proportion to the preferred sizes of the items that can
    still grow (or shrink); the last item takes the rounding remainder.
    Checked on Guitar Lab: editor 846 | 4 | 430 and patch page 1007 | 4 | 269 at 1280."""
    def size(v):
        return -v * total if v < 0 else v
    lims = [(size(a), size(b), size(c)) for a, b, c in items]
    sizes = [min(max(p, lo), hi) for lo, hi, p in lims]
    for _ in range(len(items)):
        extra = total - sum(int(s) for s in sizes)
        if extra == 0:
            break
        free = [i for i, (lo, hi, _p) in enumerate(lims)
                if (extra > 0 and sizes[i] < hi) or (extra < 0 and sizes[i] > lo)]
        if not free:
            break
        weight = sum(lims[i][2] for i in free) or 1
        for i in free:
            lo, hi, p = lims[i]
            sizes[i] = min(hi, max(lo, int(sizes[i]) + int(extra * p / weight)))
    sizes = [int(s) for s in sizes]
    for i in reversed(range(len(sizes))):
        lo, hi, _p = lims[i]
        room = total - sum(sizes)
        if room == 0:
            break
        sizes[i] = int(min(hi, max(lo, sizes[i] + room)))
    return sizes
