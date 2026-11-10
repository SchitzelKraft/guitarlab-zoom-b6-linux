"""Guitar Lab's window chrome: the (empty) menu bar strip and the navigation bar.

Sources (decompiled Mac binary, analysis/ui-trace/classes):
- MainContentComponent::resized (FUN_10002b940): nav bar at (0, 0, w, 98), pages below it;
- NavBarComponent ctor (FUN_10001f370), paint (FUN_1000202c0), resized (FUN_1000203c0);
- the 24 px strip above is the Windows build's empty JUCE menu bar, measured on screen
  (analysis/ui-reference/win/editor-1280x700.png).
"""
from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QBrush, QPainter, QTransform
from PySide6.QtWidgets import QButtonGroup, QWidget

from b6lab.gui.glui import ImageButton, image, rgb

MENU_HEIGHT, NAV_HEIGHT = 24, 98

NAV_IMAGES = {
    "EFFECT": ("0031b5c0.png", "0031ad50.png", "0031bdc0.png", "0031a4b0.png"),
    "PATCH": ("003231f0.png", "00322870.png", "00323b70.png", "00321f20.png"),
    "IMPORT IR": ("00320420.png", "0031f820.png", "00321070.png", "0031ebe0.png"),
    "EDITOR": ("003191c0.png", "003189a0.png", "003199f0.png", "00318160.png"),
}
# The NEWS page and button are left out on purpose (user decision, 2026-11-09); its place holds
# a Tux button, just for fun (user request, 2026-11-10; images from tools/make_tux.py).
TUX = ("tux_normal.png", "tux_over.png", "tux_down.png", "tux_disabled.png")
EJECT = ("00312610.png", "00312390.png", "003128e0.png", "003120b0.png")
RELOAD = ("00311860.png", "003114a0.png", "00311c80.png", "00311060.png")
HEADER_TILE = "003130f0.png"     # 196 x 196, drawn at half size, tiled
ZOOM_LOGO = "0048e360.png"       # 234 x 34, drawn at half size
CONNECTED, DISCONNECTED = "0048ba00.png", "0048b510.png"
DEVICE_IMAGE = "model_image3-B6.png"  # downloaded by Guitar Lab (archive/GUITAR_LAB/model_image3)


class MenuStrip(QWidget):
    """The empty menu bar of the Windows build: 24 px, measured row by row."""

    ROWS = [(0, 1, "#3e4147"), (1, 7, "#1b1f25"), (8, 8, "#1a1e24"), (16, 7, "#191d23"), (23, 1, "#3e4147")]

    def paintEvent(self, _event):
        p = QPainter(self)
        for y, h, colour in self.ROWS:
            p.fillRect(0, y, self.width(), h, colour)


def draw_image_within(p, img, rect):
    """juce::Graphics::drawImageWithin with RectanglePlacement::centred (scale to fit)."""
    if img.isNull() or rect.width() <= 0 or rect.height() <= 0:
        return
    scale = min(rect.width() / img.width(), rect.height() / img.height())
    w, h = img.width() * scale, img.height() * scale
    p.drawImage(QRectF(rect.x() + (rect.width() - w) / 2, rect.y() + (rect.height() - h) / 2, w, h), img)


class NavBar(QWidget):
    """Device picture, eject/reload, the five page buttons, ZOOM logo and connection icon."""

    page_selected = Signal(str)
    tux_clicked = Signal()
    eject_clicked = Signal()
    reload_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.has_ir = True  # device flag 2: the B6 has IMPORT IR (five buttons)
        self.eject = ImageButton(*EJECT, placement="fit", parent=self)
        self.eject.setToolTip("Eject")
        self.eject.clicked.connect(self.eject_clicked)
        self.reload = ImageButton(*RELOAD, placement="fit", parent=self)
        self.reload.setToolTip("Reload")
        self.reload.clicked.connect(self.reload_clicked)
        self.buttons = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for name, images in NAV_IMAGES.items():
            b = ImageButton(*images, placement="fit", parent=self)
            b.setCheckable(True)
            b.setToolTip(name.title())
            b.clicked.connect(lambda _c=False, n=name: self.page_selected.emit(n))
            self.group.addButton(b)
            self.buttons[name] = b
        self.tux = ImageButton(*TUX, placement="fit", parent=self)
        self.tux.setToolTip("Tux")
        self.tux.clicked.connect(self.tux_clicked)
        self.set_connected(False)

    def set_connected(self, ok):
        self.connected = ok
        self.eject.setVisible(ok)
        self.reload.setVisible(not ok)
        self.update()

    def select(self, name):
        self.buttons[name].setChecked(True)

    def resizeEvent(self, _event):
        w = self.width()
        # FUN_10001f370: eject and reload share (292, 46), at half the image size
        for b, images in ((self.eject, EJECT), (self.reload, RELOAD)):
            img = image(images[0])
            b.setGeometry(292, 46, int(img.width() * 0.5), int(img.height() * 0.5))
        # FUN_1000203c0: 72 x 72 buttons at y=24, origins 112 px apart around the centre; the
        # start is centre-260 for five buttons and centre-204 for four. Without NEWS there are
        # four, so they use Guitar Lab's own four-button centring.
        cx = w // 2
        order = ["EFFECT", "PATCH"] + (["IMPORT IR"] if self.has_ir else []) + ["EDITOR", "TUX"]
        x = cx - (260 if len(order) == 5 else 204)
        for name in order:
            (self.tux if name == "TUX" else self.buttons[name]).setGeometry(x, 24, 72, 72)
            x += 112
        self.buttons["IMPORT IR"].setVisible(self.has_ir)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # FUN_1000202c0: tiled header image under a 0.5 scale, then the ZOOM logo
        brush = QBrush(image(HEADER_TILE))
        brush.setTransform(QTransform.fromScale(0.5, 0.5))
        p.fillRect(self.rect(), brush)
        logo = image(ZOOM_LOGO)
        p.drawImage(QRectF((self.width() * 2 - logo.width() - 40) / 2, 30, logo.width() / 2, logo.height() / 2),
                    logo)
        # GLImageComponents: device picture at (32, 8, 255, 87), connection at (w-46, 60, 30, 20)
        try:
            draw_image_within(p, image(DEVICE_IMAGE), QRectF(32, 8, 255, 87))
        except FileNotFoundError:
            pass
        draw_image_within(p, image(CONNECTED if self.connected else DISCONNECTED),
                          QRectF(self.width() - 46, 60, 30, 20))


class Chrome:
    """Places the strip, the nav bar and the current page like MainWindow/MainContentComponent."""

    @staticmethod
    def layout(width, height, strip, nav, pages):
        strip.setGeometry(0, 0, width, MENU_HEIGHT)
        nav.setGeometry(0, MENU_HEIGHT, width, NAV_HEIGHT)
        top = MENU_HEIGHT + NAV_HEIGHT
        for page in pages:
            page.setGeometry(0, top, width, max(0, height - top))

