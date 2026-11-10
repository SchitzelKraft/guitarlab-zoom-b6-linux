"""Guitar Lab's dialogs: a JUCE DialogWindow drawn by GuitarLabLookAndFeel, and the SAVE dialog.

Window (measured on Guitar Lab under Wine, analysis/ui-reference/win/dialog-save-changes-full.png):
a black rounded frame (radius 10; 9 px at the sides, 7 at the top, 11 at the bottom) around a
1 px (28,32,38) border, a 24 px title bar (54,66,80) with the title bold 14 in (212,236,243)
centred (LookAndFeel drawDocumentWindowTitleBar, FUN_100018b60), then the content.
The dialog is centred on the main window and modal.

SAVE dialog (SavePatchDialogComponent, FUN_100091ff0 / paint FUN_1000924e0 / resized
FUN_100092910; opened by FUN_1001197a0 with title "Save Changes", content 352 x 124,
background (28,32,38)): "PATCH <number>" and the name, bold 15, right-aligned at (32, 28) and
(32, 43) for the source and (195, 28) / (195, 43) for the destination, each 105 x 15; the arrow
image at (155, 32); Prev / Next (destination -1 / +1) at (310, 32) and (310, 48); OK at
(108, h-42, 44, 26) and Cancel at (198, h-42, 80, 26). OK returns True.
"""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QDialog, QWidget

from b6lab.gui.glui import CENTRED, LEFT, RIGHT, TOP, VCENTRE, ImageButton, draw_fitted_text, font, image, rgb

FRAME = (9, 7, 9, 11)  # left, top, right, bottom of the black frame
TITLE_HEIGHT = 24
BACKGROUND = rgb(28, 32, 38)
TITLE_BG = rgb(54, 66, 80)
TITLE_TEXT = rgb(212, 236, 243)
BUTTON_OUTLINE = rgb(40, 47, 57)
ARROW = "0048aa90.png"
NEXT = ("0048aec0.png", "0048add0.png", "0048afd0.png", "0048acc0.png")
PREV = ("0048b2e0.png", "0048b200.png", "0048b400.png", "0048b0e0.png")


def default_font(height, bold=False):
    """juce::Font(height[, bold]) with JUCE's default sans-serif typeface: Guitar Lab sets no
    typeface for alert windows and text buttons (GuitarLabLookAndFeel overrides no font method
    for them, FUN_1000268a0 sets no default typeface), so JUCE picks the platform's default
    (Verdana on Windows, Lucida Grande on the Mac; here Verdana or Qt's substitute). JUCE's
    height is ascent + descent, so the em size is measured from the font Qt resolves."""
    f = QFont("Verdana")
    f.setBold(bold)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setKerning(True)
    f.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
    f.setPixelSize(100)
    fm = QFontMetricsF(f)
    ratio = (fm.ascent() + fm.descent()) / 100.0 or 1.0
    f.setPixelSize(1)
    f.setPointSizeF(height / ratio * 72 / 96)   # B6 Lab renders at 96 logical dpi
    return f


def text_button_font(height=26):
    """LookAndFeel_V2::getTextButtonFont (FUN_1001ecab0, not overridden by Guitar Lab):
    Font(min(15, button height x 0.6)) in the default typeface."""
    return default_font(min(15.0, height * 0.6))


def _draw_centred(p, text, rect, f):
    """One line centred in `rect` the way juce::Graphics::drawFittedText places it (font
    height = ascent + descent); falls back to draw_fitted_text's squeeze when it is too wide."""
    fm = QFontMetricsF(f)
    width = fm.horizontalAdvance(text)
    if width > rect.width():
        draw_fitted_text(p, text, rect, f, CENTRED)
        return
    p.setFont(f)
    y = rect.top() + (rect.height() - fm.ascent() - fm.descent()) / 2 + fm.ascent()
    p.drawText(QPointF(rect.left() + (rect.width() - width) / 2, y), text)


class TextButton(QAbstractButton):
    """A JUCE TextButton drawn by GuitarLabLookAndFeel.

    Background FUN_100018250 (drawButtonBackground): nothing when the colour is transparent;
    otherwise a rounded rectangle (2, 2, w-4, h-4), corner min(round(w/10), round(h/10)),
    stroked 2 px in TextButton::buttonColourId (40,47,57) (constructor FUN_100016e00), made
    brighter(0.4) while down and, under the mouse, darker(0.1) when its brightness is over 0.5
    else brighter(0.1). Text LookAndFeel_V2::drawButtonText (FUN_1001ecbc0): textColourOffId
    (212,236,243), alpha 0.5 when disabled, text_button_font, centred in (indent, yIndent,
    w - 2 indent, h - 2 yIndent) with yIndent = min(4, round(h x 0.3)) and indent =
    min(round(font height x 0.6), 2 + min(w, h) / 2 / 2)."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.outline = BUTTON_OUTLINE    # juce TextButton::buttonColourId
        self.text_colour = TITLE_TEXT    # juce TextButton::textColourOffId
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def outline_colour(self):
        c = QColor(self.outline)
        if self.isDown():
            return brighter(c, 0.4)
        if self.underMouse():
            return darker(c, 0.1) if max(c.red(), c.green(), c.blue()) / 255 > 0.5 else brighter(c, 0.1)
        return c

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        corner = min(round(w * 0.1), round(h * 0.1))
        p.setPen(QPen(self.outline_colour(), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), corner, corner)
        colour = QColor(self.text_colour)
        if not self.isEnabled():
            colour.setAlphaF(colour.alphaF() * 0.5)
        p.setPen(colour)
        f = text_button_font(h)
        y_indent = min(4, round(h * 0.3))
        indent = min(round(min(15.0, h * 0.6) * 0.6), 2 + min(w, h) // 2 // 2)
        _draw_centred(p, self.text(), QRectF(indent, y_indent, w - 2 * indent, h - 2 * y_indent), f)


def brighter(c, amount):
    """juce::Colour::brighter (FUN_100143b70)."""
    ratio = 1.0 / (1.0 + amount)
    return QColor(*(int(255 - ratio * (255 - v)) for v in (c.red(), c.green(), c.blue())), c.alpha())


def darker(c, amount):
    """juce::Colour::darker (FUN_100143c00)."""
    ratio = 1.0 / (1.0 + amount)
    return QColor(*(int(v * ratio) for v in (c.red(), c.green(), c.blue())), c.alpha())


class CloseButton(QAbstractButton):
    """The DialogWindow close button: GuitarLabLookAndFeel::createDocumentWindowButton
    (FUN_100018e00, "close": two line segments (0,0)-(1,1) and (1,0)-(0,1), 0.35 thick, colour
    0xffdd1100) painted by FUN_100019c20: brighter(0.4) under the mouse, alpha 0.6 when
    disabled, the cross scaled to fit a square of 2 x k x 0.9 x min(w, h) / 2 around the centre
    (k = 0.65, 0.6 while pressed). Placed like JUCE's positionDocumentWindowButtons: 1.2 x the
    title bar height wide, at the right of the title bar."""

    COLOUR = rgb(221, 17, 0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setToolTip("close")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(self.COLOUR)
        if not self.isEnabled():
            colour.setAlphaF(0.6)
        elif self.underMouse():
            colour = brighter(colour, 0.4)
        k = 0.6 if self.isDown() else 0.65
        cx, cy = self.width() / 2, self.height() / 2
        r = k * min(cx, cy) * 0.9
        shape = QPainterPath()
        for (x1, y1, x2, y2) in ((0, 0, 1, 1), (1, 0, 0, 1)):
            # juce::Path::addLineSegment: a quad 0.35 wide around the line
            dx, dy = x2 - x1, y2 - y1
            n = (dx * dx + dy * dy) ** 0.5
            ox, oy = -dy / n * 0.175, dx / n * 0.175
            seg = QPainterPath()
            seg.moveTo(x1 + ox, y1 + oy)
            seg.lineTo(x2 + ox, y2 + oy)
            seg.lineTo(x2 - ox, y2 - oy)
            seg.lineTo(x1 - ox, y1 - oy)
            seg.closeSubpath()
            shape.addPath(seg)
        b = shape.boundingRect()
        scale = 2 * r / max(b.width(), b.height())
        p.translate(cx - b.center().x() * scale, cy - b.center().y() * scale)
        p.scale(scale, scale)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawPath(shape)


class GLDialog(QDialog):
    """A frameless dialog drawn like Guitar Lab's DialogWindow, holding `content`.
    `close_button`: the SAVE dialog hides it (FUN_1001197a0), the TYPE picker keeps it."""

    def __init__(self, title, content, parent=None, background=BACKGROUND, close_button=False):
        super().__init__(parent)
        self.background = background  # DialogWindow::LaunchOptions::dialogBackgroundColour
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.title = title
        self.content = content
        content.setParent(self)
        left, top, right, bottom = FRAME
        cw, ch = content.width(), content.height()
        # 1 px border, title bar, content, 3 px below the content (measured)
        self.inner = QRectF(left, top, cw + 2, 1 + TITLE_HEIGHT + ch)
        content.move(left + 1, top + 1 + TITLE_HEIGHT)
        self.setFixedSize(left + cw + 2 + right, top + int(self.inner.height()) + bottom)
        self.setWindowTitle(title)
        self.close_button = None
        if close_button:
            bw = int(TITLE_HEIGHT * 1.2)
            self.close_button = CloseButton(self)
            self.close_button.setGeometry(int(self.inner.right()) - 1 - bw, top + 1, bw, TITLE_HEIGHT)
            self.close_button.clicked.connect(self.reject)

    def showEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            win = QWidget.window(parent)  # some views keep the main window in .window
            centre = win.mapToGlobal(win.rect().center())
            self.move(centre.x() - self.width() // 2, centre.y() - self.height() // 2)
        super().showEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.fillPath(path, QColor(0, 0, 0))
        p.fillRect(self.inner, self.background)
        bar = QRectF(self.inner.x() + 1, self.inner.y() + 1, self.inner.width() - 2, TITLE_HEIGHT)
        p.fillRect(bar, TITLE_BG)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setPen(TITLE_TEXT)
        draw_fitted_text(p, self.title, bar, font(14, True), CENTRED)


class SavePatchContent(QWidget):
    """SavePatchDialogComponent: source patch, arrow, destination patch with Prev / Next."""

    def __init__(self, source, label, name, count, parent=None):
        super().__init__(parent)
        self.resize(352, 127)  # setSize(352, 124) plus 3 px the DialogWindow adds (measured)
        self.source, self.dest = source, source
        self.label, self.name, self.count = label, name, count
        self.next = ImageButton(*NEXT, parent=self)
        self.prev = ImageButton(*PREV, parent=self)
        for b, y, step in ((self.next, 48, 1), (self.prev, 32, -1)):
            img = image(b.images["normal"])
            b.setGeometry(310, y, img.width() // 2, img.height() // 2)
            b.clicked.connect(lambda _c=False, d=step: self.move_dest(d))
        self.ok = TextButton("OK", self)
        self.ok.setGeometry(108, self.height() - 42, 44, 26)
        self.cancel = TextButton("Cancel", self)
        self.cancel.setGeometry(198, self.height() - 42, 80, 26)

    def move_dest(self, step):
        self.dest = (self.dest + step) % self.count
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), BACKGROUND)
        p.setPen(QColor(255, 255, 255))
        f = font(15, True)
        for x, slot in ((32, self.source), (195, self.dest)):
            draw_fitted_text(p, f"PATCH {self.label(slot)}", QRectF(x, 28, 105, 15), f, RIGHT | TOP)
            draw_fitted_text(p, self.name(slot), QRectF(x, 43, 105, 15), f, RIGHT | TOP)
        arrow = image(ARROW)
        p.drawImage(QRectF(155, 32, arrow.width() / 2, arrow.height() / 2), arrow)


class MessageContent(QWidget):
    """Guitar Lab's message box content (FUN_10008d490, paint FUN_10008d610): fill (28,32,38),
    the text bold 15 in (212,236,243), centred lines from x=8 to w-8 with the first baseline at
    y=32; optional OK / Cancel (none for "Creating Backup")."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.resize(352, 127)  # setSize(352, 124) plus the 3 px the DialogWindow adds (measured)
        self.text = text

    def paintEvent(self, _event):
        from PySide6.QtGui import QFontMetricsF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), BACKGROUND)
        f = font(15, True)
        p.setFont(f)
        p.setPen(TITLE_TEXT)
        fm = QFontMetricsF(f)
        y = 32.0
        for line in self.text.split("\n"):
            p.drawText(QPointF(8 + (self.width() - 16 - fm.horizontalAdvance(line)) / 2, y), line)
            y += fm.height()


class GroupPropertiesContent(QWidget):
    """PatchGroupPropertiesComponent (ctor / resized in the decompile): 352 x 176 on (28,32,38);
    labels bold 13 in (212,236,243), right-aligned in (6, 26 / 66 / 106, 90, 14): "Group Name",
    "Device" (only when the group has one), "# Patches"; the name editor at (108, 21, 208, 26),
    the values at (108, 66 / 106, 208, 14); OK (108, h-42, 44, 26), Cancel (198, h-42, 80, 26)."""

    def __init__(self, name, count, device=None, parent=None):
        from PySide6.QtWidgets import QLineEdit
        super().__init__(parent)
        self.resize(352, 179)  # setSize(352, 176) plus the DialogWindow's 3 px (measured on SAVE)
        self.count, self.device = count, device
        self.name_edit = QLineEdit(name, self)
        self.name_edit.setGeometry(108, 21, 208, 26)
        self.name_edit.setFont(font(14))
        self.name_edit.setStyleSheet("QLineEdit { background: rgb(41,47,57); color: rgb(255,255,255);"
                                     " border: 1px solid rgb(54,66,80); }")
        self.ok, self.cancel = TextButton("OK", self), TextButton("Cancel", self)
        self.ok.setGeometry(108, self.height() - 42, 44, 26)
        self.cancel.setGeometry(198, self.height() - 42, 80, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), BACKGROUND)
        f = font(13, True)
        rows = [("Group Name", 26, None), ("# Patches", 106, str(self.count))]
        if self.device is not None:
            rows.insert(1, ("Device", 66, str(self.device)))
        for label, y, value in rows:
            p.setPen(TITLE_TEXT)
            draw_fitted_text(p, label, QRectF(6, y, 90, 14), f, RIGHT | VCENTRE)
            if value is not None:
                p.setPen(QColor(255, 255, 255))
                draw_fitted_text(p, value, QRectF(108, y, 208, 14), font(13), LEFT | VCENTRE)


class PatchPropertiesContent(QWidget):
    """PatchPropertiesComponent (ctor / resized): 352 x 347 on (28,32,38); labels bold 14 in
    (212,236,243) in (16, 26 / 66 / 148, 80, 14): "Patch Name", "Comment", "Effect"; the name
    editor (108, 21, 208, 26), the comment (108, 61, 208, 68), the effects (108, 143, 208, 145);
    OK (108, h-42, 44, 26), Cancel (198, h-42, 80, 26)."""

    def __init__(self, name, comment, effect_names, parent=None):
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
        super().__init__(parent)
        self.resize(352, 350)  # setSize(352, 347) plus the DialogWindow's 3 px
        style = ("background: rgb(41,47,57); color: rgb(255,255,255); border: 1px solid rgb(54,66,80);")
        self.name_edit = QLineEdit(name, self)
        self.name_edit.setMaxLength(10)
        self.name_edit.setGeometry(108, 21, 208, 26)
        self.comment_edit = QPlainTextEdit(comment, self)
        self.comment_edit.setGeometry(108, 61, 208, 68)
        self.effects = QPlainTextEdit("\n".join(effect_names), self)
        self.effects.setReadOnly(True)
        self.effects.setGeometry(108, 143, 208, 145)
        for w in (self.name_edit, self.comment_edit, self.effects):
            w.setFont(font(14))
            w.setStyleSheet(f"{type(w).__name__} {{ {style} }}")
        self.ok, self.cancel = TextButton("OK", self), TextButton("Cancel", self)
        self.ok.setGeometry(108, self.height() - 42, 44, 26)
        self.cancel.setGeometry(198, self.height() - 42, 80, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), BACKGROUND)
        p.setPen(TITLE_TEXT)
        for label, y in (("Patch Name", 26), ("Comment", 66), ("Effect", 148)):
            draw_fitted_text(p, label, QRectF(16, y, 80, 14), font(14, True), LEFT | VCENTRE)


def ask_patch_properties(parent, name, comment, effect_names):
    """"Patch Properties": (name, comment) on OK, None on Cancel."""
    content = PatchPropertiesContent(name, comment, effect_names)
    dialog = GLDialog("Patch Properties", content, parent)
    content.ok.clicked.connect(dialog.accept)
    content.cancel.clicked.connect(dialog.reject)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return content.name_edit.text(), content.comment_edit.toPlainText()


class EffectPropertiesContent(QWidget):
    """EffectPropertiesComponent: 535 x 337 on (28,32,38); the effect's icon at half size, right
    edge at x = 124, y = 40; the name bold 30 in (162, 36, 340, 32); the description regular 12
    (212,236,243) in (162, 70, 340, 36) from the top; the parameters below, a "P" box for those
    the pedal can control; lines 2 px in (54,66,80): x = 144 from y = 29 to 278 and under the
    list from x = 73 to 501; OK centred at the bottom (44 x 26)."""

    def __init__(self, info, icon=None, parent=None):
        super().__init__(parent)
        self.resize(535, 340)
        self.info, self.icon = info, icon
        self.ok = TextButton("OK", self)
        self.ok.setGeometry(self.width() // 2 - 22, self.height() - 42, 44, 26)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), BACKGROUND)
        if self.icon is not None:
            w, h = self.icon.width() / 2, self.icon.height() / 2
            p.drawImage(QRectF(124 - w, 40, w, h), self.icon)
        p.setPen(QColor(255, 255, 255))
        draw_fitted_text(p, self.info.name, QRectF(162, 36, 340, 32), font(30, True), LEFT | VCENTRE)
        p.setPen(TITLE_TEXT)
        from b6lab.gui.effect_list import _wrapped
        _wrapped(p, " ".join(self.info.description.split()), QRectF(162, 70, 340, 36), font(12), 2, top=True)
        y = 112
        for param in self.info.params[:9]:
            if param.pedal:
                p.setPen(QPen(TITLE_TEXT, 1))
                p.drawRect(QRectF(162, y + 2, 10, 14))
                draw_fitted_text(p, "P", QRectF(162, y + 3, 10, 12), font(13, True), CENTRED)
            p.setPen(TITLE_TEXT)
            draw_fitted_text(p, param.name, QRectF(178, y, 100, 18), font(13, True), LEFT | VCENTRE)
            draw_fitted_text(p, param.explanation, QRectF(282, y, 220, 18), font(12), LEFT | VCENTRE)
            y += 18
        p.setPen(QPen(rgb(54, 66, 80), 2))
        p.drawLine(QRectF(144, 29, 0, 249).topLeft(), QRectF(144, 29, 0, 249).bottomLeft())
        p.drawLine(73, y + 10, 501, y + 10)


def show_effect_properties(parent, info, icon=None):
    content = EffectPropertiesContent(info, icon)
    dialog = GLDialog("Effect Properties", content, parent)
    content.ok.clicked.connect(dialog.accept)
    dialog.exec()


def ask_group_properties(parent, name, count, device=None):
    """"Patch Group Properties": returns the (possibly new) name on OK, None on Cancel."""
    content = GroupPropertiesContent(name, count, device)
    dialog = GLDialog("Patch Group Properties", content, parent)
    content.ok.clicked.connect(dialog.accept)
    content.cancel.clicked.connect(dialog.reject)
    return content.name_edit.text() if dialog.exec() == QDialog.DialogCode.Accepted else None


# --- JUCE AlertWindow (AlertWindow::showOkCancelBox, FUN_1001dbc70) -------------------------
# Guitar Lab makes GuitarLabLookAndFeel the default look and switches native alert windows off
# (FUN_1000268a0: setUsingNativeAlertWindows(false) FUN_1001e8880, setDefaultLookAndFeel
# FUN_1001e8660), so its questions are JUCE AlertWindows on every platform, also on the Mac.
ALERT_BACKGROUND = rgb(28, 32, 38)   # AlertWindow::backgroundColourId 0x1001800 (FUN_100016e00)
ALERT_TEXT = rgb(212, 236, 243)      # AlertWindow::textColourId 0x1001810
ALERT_OUTLINE = rgb(54, 66, 80)      # AlertWindow::outlineColourId 0x1001820
ALERT_BAND = 30                      # drawAlertBox FUN_100019250: fillRect(0, 0, width, 30)
ALERT_BUTTON_HEIGHT = 28             # LookAndFeel_V2::getAlertWindowButtonHeight FUN_1001edfb0
ALERT_MESSAGE_HEIGHT = 15.0          # getAlertWindowMessageFont FUN_1001ee0a0: Font(15)
ALERT_TITLE_HEIGHT = 15.0 * 1.1      # getAlertWindowTitleFont FUN_1001edfc0: message x 1.1, bold


class _Token:
    """juce::TextLayoutHelpers::Token: a word, a run of white space or one line break."""

    def __init__(self, text, f, height):
        self.text, self.font, self.height = text, f, height
        fm = QFontMetricsF(f)
        self.newline = "\n" in text or "\r" in text
        self.whitespace = (not self.newline) and text.isspace()
        # the advance of a line break is taken as 0 (the typeface's glyph for it is unknown)
        self.width = 0.0 if self.newline else fm.horizontalAdvance(text)
        self.ascent = height * fm.ascent() / ((fm.ascent() + fm.descent()) or 1.0)
        self.x = self.y = 0.0
        self.line = 0


def _tokens(runs):
    """TokenList::appendText for each (text, font, height) run: a new token at every change of
    character type (word / white space) and for every line break."""
    out = []
    for text, f, height in runs:
        current, last = "", None
        for c in text:
            kind = 0 if c in "\r\n" else (2 if c.isspace() else 1)
            if kind == 0 or kind != last:
                if current:
                    out.append(_Token(current, f, height))
                current = c
            else:
                current += c
            last = kind
        if current:
            out.append(_Token(current, f, height))
    return out


class AlertTextLayout:
    """juce::TextLayout built the portable way (TokenList::layoutRuns / createLayout; the Mac
    build uses CoreText through createNativeLayout FUN_1001712a0, with the same rules).
    `lines`: per line its tokens that draw glyphs; `width` / `height`: the bounds after
    recalculateSize."""

    def __init__(self, runs, max_width):
        tokens = _tokens(runs)
        x = y = h = 0.0
        line = 0
        for i, t in enumerate(tokens):
            t.x, t.y, t.line = x, y, line
            x += t.width
            h = max(h, t.height)
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is None:
                break
            if t.newline or (not nxt.whitespace and x + nxt.width > max_width):
                x, y, h = 0.0, y + h, 0.0
                line += 1
        self.lines = []
        for n in range(line + 1):
            members = [t for t in tokens if t.line == n]
            # white space and line breaks draw nothing, unless they start the line
            glyphs = [t for k, t in enumerate(members) if k == 0 or not (t.whitespace or t.newline)]
            if glyphs:
                self.lines.append((glyphs, members))
        if self.lines:
            self.width = max(self.line_width(i) for i in range(len(self.lines)))
            # line bounds: baseline (first glyph token's top + its ascent) minus the line's
            # largest ascent, plus its largest descent (addRun keeps both per line)
            top = min(g[0].y + g[0].ascent - max(m.ascent for m in ms) for g, ms in self.lines)
            bottom = max(g[0].y + g[0].ascent + max(m.height - m.ascent for m in ms)
                         for g, ms in self.lines)
            self.height = bottom - top
        else:
            self.width = self.height = 0.0

    def line_width(self, i):
        glyphs = self.lines[i][0]
        return glyphs[-1].x + glyphs[-1].width - glyphs[0].x


def balanced_layout(runs, max_width):
    """TextLayout::createLayoutWithBalancedLineLengths (FUN_100172350): shrink the width in
    steps of 10 down to half, stop when the last two lines are within 10 % of each other, else
    keep the width whose last two lines differ the most."""
    min_width = max_width / 2.0
    best_width, best_prop = max_width, 0.0
    width = max_width
    layout = None
    while width > min_width:
        layout = AlertTextLayout(runs, width)
        if len(layout.lines) < 2:
            return layout
        a, b = layout.line_width(-1), layout.line_width(-2)
        shortest, longest = min(a, b), max(a, b)
        prop = longest / shortest if shortest > 0 else 1.0
        if 0.9 < prop < 1.1:
            return layout
        if prop > best_prop:
            best_prop, best_width = prop, width
        width -= 10.0
    if layout is not None and best_width == width:
        return layout
    return AlertTextLayout(runs, best_width)


def alert_geometry(title, message, buttons, parent_size):
    """AlertWindow::updateLayout (FUN_100224160) for a box without icon or extra components.
    Returns (width, height, layout, text area (x, y, w, h), [(x, y, w, h) per button])."""
    pw, ph = parent_size
    msg_font = default_font(ALERT_MESSAGE_HEIGHT)
    title_font = default_font(ALERT_TITLE_HEIGHT, True)
    fm = QFontMetricsF(msg_font)
    wid = max(round(fm.horizontalAdvance(message.replace("\n", ""))), round(fm.horizontalAdvance(title)))
    cap = int(pw * 0.7)
    w = min(int(math.sqrt(ALERT_MESSAGE_HEIGHT * wid)) * 2 + 300, cap)
    runs = [(title, title_font, ALERT_TITLE_HEIGHT)]
    if message:
        runs.append(("\n\n" + message, msg_font, ALERT_MESSAGE_HEIGHT))
    layout = balanced_layout(runs, float(w))           # justification centredTop (no icon)
    w = min(max(310, int(layout.width)) + 40, cap)
    text_bottom = int(layout.height) + 40              # 16 + title height 24 + text
    bfm = QFontMetricsF(text_button_font(ALERT_BUTTON_HEIGHT))
    widths = [round(bfm.horizontalAdvance(b)) + ALERT_BUTTON_HEIGHT for b in buttons]  # V2 width to fit
    w = max(40 + sum(16 + bw for bw in widths), w)
    h = text_bottom + (20 + ALERT_BUTTON_HEIGHT if buttons else 0)
    w, h = min(w, cap), min(ph - 50, h)
    total = -16 + sum(bw + 16 for bw in widths)
    x = (w - total) // 2
    y = round(h * 0.95) - ALERT_BUTTON_HEIGHT
    rects = []
    for bw in widths:
        rects.append((x, y, bw, ALERT_BUTTON_HEIGHT))
        x += bw + 16
    return w, h, layout, (10, 10, w - 20, h - 10), rects


class AlertContent(QWidget):
    """The AlertWindow's face: GuitarLabLookAndFeel::drawAlertBox (FUN_100019250) fills the
    background, a 30 px band at the top in the outline colour, then draws the text layout (the
    title bold, a blank line, the message) centred at the top of the text area; the buttons are
    TextButtons at the bottom (OK, Cancel: LookAndFeel_V2::createAlertWindow FUN_1001ed7f0)."""

    def __init__(self, title, message, buttons=("OK", "Cancel"), parent_size=(1280, 800), parent=None):
        super().__init__(parent)
        w, h, self.layout, self.text_area, rects = alert_geometry(title, message, buttons, parent_size)
        self.resize(w, h)
        self.buttons = []
        for text, (x, y, bw, bh) in zip(buttons, rects):
            b = TextButton(text, self)
            b.setGeometry(x, y, bw, bh)
            self.buttons.append(b)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), ALERT_BACKGROUND)
        p.fillRect(QRectF(0, 0, self.width(), ALERT_BAND), ALERT_OUTLINE)
        p.setPen(ALERT_TEXT)
        ax, ay, aw, _ah = self.text_area
        for i, (glyphs, _members) in enumerate(self.layout.lines):
            # TextLayout::draw with centredTop: each line centred in the text area
            left = ax + (aw - self.layout.line_width(i)) / 2 - glyphs[0].x
            for t in glyphs:
                if t.newline or t.whitespace:
                    continue
                p.setFont(t.font)
                p.drawText(QPointF(left + t.x, ay + t.y + t.ascent), t.text)


class AlertWindow(QDialog):
    """A JUCE AlertWindow on the desktop: getAlertBoxWindowFlags FUN_1000193b0 = 0x101 (on the
    taskbar, drop shadow, no title bar), centred on the active window (centreAroundComponent),
    kept 12 px inside the screen. Return / the first letter of OK give 1, Escape / the first
    letter of Cancel 0 (createAlertWindow FUN_1001ed7f0)."""

    def __init__(self, title, message, buttons=("OK", "Cancel"), parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setWindowTitle(title)
        screen = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)
        self.content = AlertContent(title, message, buttons, (area.width(), area.height()), self)
        self.setFixedSize(self.content.size())
        self.buttons = self.content.buttons
        results = [1, 0] if len(buttons) == 2 else [0]
        self.shortcuts = {}
        for b, r in zip(self.buttons, results):
            b.clicked.connect(lambda _c=False, r=r: self.done(r))
            if b.text():
                self.shortcuts.setdefault(b.text()[0].lower(), r)
        if len(buttons) == 2 and buttons[0][:1].lower() == buttons[1][:1].lower():
            self.shortcuts = {buttons[0][:1].lower(): 1}
        self.return_result, self.escape_result = (1, 0) if len(buttons) == 2 else (0, 0)
        self.area = area

    def showEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            win = QWidget.window(parent)
            centre = win.mapToGlobal(win.rect().center())
            inner = self.area.adjusted(12, 12, -12, -12)
            x = max(inner.left(), min(centre.x() - self.width() // 2, inner.right() + 1 - self.width()))
            y = max(inner.top(), min(centre.y() - self.height() // 2, inner.bottom() + 1 - self.height()))
            self.move(x, y)
        super().showEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.done(self.return_result)
        elif key == Qt.Key.Key_Escape:
            self.done(self.escape_result)
        elif event.modifiers() == Qt.KeyboardModifier.NoModifier and event.text().lower() in self.shortcuts:
            self.done(self.shortcuts[event.text().lower()])
        else:
            super().keyPressEvent(event)


def ask_ok_cancel(parent, title, text):
    """AlertWindow::showOkCancelBox (FUN_1001dbc70), as Guitar Lab asks before "Delete from
    Device" (FUN_1000814a0 case 3) and "ALL Initialize?" (FUN_10002bf40): no icon, buttons
    "OK" and "Cancel" (the defaults for empty button texts). Returns True for OK."""
    return AlertWindow(title, text, ("OK", "Cancel"), parent).exec() == 1


def show_progress(parent, text):
    """Guitar Lab's progress note (FUN_10008d970): a non-modal "ZOOM Guitar Lab" window with
    the message and no close button; the caller closes it when the work is done."""
    dialog = GLDialog("ZOOM Guitar Lab", MessageContent(text), parent)
    dialog.setModal(False)
    dialog.show()
    return dialog


def ask_save_destination(parent, source, label, name, count=240):
    """Guitar Lab's SAVE dialog. Returns the destination slot, or None when cancelled."""
    content = SavePatchContent(source, label, name, count)
    dialog = GLDialog("Save Changes", content, parent)
    content.ok.clicked.connect(dialog.accept)
    content.cancel.clicked.connect(dialog.reject)
    return content.dest if dialog.exec() == QDialog.DialogCode.Accepted else None
