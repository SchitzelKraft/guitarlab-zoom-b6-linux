"""Editor page, laid out and drawn like Guitar Lab's EditorPageComponent.

Layout from EditorPageComponent::resized (FUN_1000651a0, decompiled Mac binary), relative to
the page's horizontal centre cx:
  ADD (cx-573, 36, 41, 54), DELETE (cx-524, 36, 34, 54), CLIP (cx-477, 36, 34, 54),
  patch number (cx-406, 32, 64, 24), name (cx-336, 32, 128, 24), "Processor" (cx-406, 72, 76, 20),
  chain (cx-176, 34, 495, 56), level knob (cx+352, 36, 54, 64), SAVE (cx+446, 36, 34, 54),
  "120 BPM" (cx+487, 38, 44, 14), TAP (cx+492, 56, 34, 34), TUNER (cx+536, 36, 34, 54);
  pedal viewport (0, 120, w, 280); pedals min(w / n, 260) apart, 1.1 x as high as wide;
  lower part from y=400: patch list | 4 px bar | clipboard 430 px wide;
  expand button (w-32, 364, 18, 18).
Paint (FUN_100064dd0): background (26,30,36), patch panel image at (cx-430, 20) at half size,
"LEVEL" bold 12 in (223,248,254) at (cx+352, 26, 54, 14), processor bar 82 x 7 at
(label right + 8, 75) in (33,145,175) over (30,97,134), and a small (40,47,57) arrow at cx-188.
"""
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QInputDialog, QLineEdit, QScrollArea, QTableView,
                               QWidget, QLabel, QVBoxLayout)

from b6lab import effects as fx_catalog, ptcf
from b6lab.gui import glpicker, patch_search, theme
from b6lab.gui.glpedal import Knob, Pedal
from b6lab.gui.glui import (DOWNLOADS, LEFT, TOP, ImageButton, Painted, draw_fitted_text, font, image, rgb)
from b6lab.gui.patch_list import PatchListModel, configure_patch_table, paint_table_header_title, slot_label

BUTTONS = {  # normal, over, down, disabled (FUN_100062e60)
    "ADD": ("002ef7b0.png", "002ee9c0.png", "002f0570.png", "002edda0.png"),
    "DELETE": ("002f61c0.png", "002f59f0.png", "002f69a0.png", "002f5230.png"),
    "CLIP": ("002f2b70.png", "002f1ef0.png", "002f3870.png", "002f1320.png"),
    "SAVE": ("002f81c0.png", "002f7990.png", "002f89e0.png", "002f7190.png"),
    "TAP": ("002fad50.png", "002fa030.png", "002fbb30.png", "002f91e0.png"),
    "TUNER": ("002fd8b0.png", "002fd120.png", "002fe040.png", "002fc990.png"),
}
EXPAND = ("00305630.png", "00305390.png", "003058e0.png", "003050e0.png")
PATCH_PANEL = "002ed450.png"  # the B6 (model flag > 1) uses the dark chain panel
LABEL_TEXT = rgb(225, 248, 254)
SVG_DIR = DOWNLOADS / "SVG"


def _module(fx_id):
    """The effect's module name (e.g. "NYMUFF88"), which names its Guitar Lab SVG."""
    import json
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def table():
        try:
            return json.loads((fx_catalog.RANGES_PATH).read_text())
        except (OSError, ValueError):
            return {}
    rec = table().get(f"{fx_id:08X}")
    return rec["module"][:-4] if rec else None


_ICONS = {}
_SND_RTN_SVG = {0x1A000020: "FX_LOOP", 0x1A000023: "SEND", 0x1A000026: "RETURN"}


def chain_icon(fx_id, wide=False):
    """The effect's colour SVG rendered at Guitar Lab's size (half of its view box)."""
    key = (fx_id, wide)
    if key in _ICONS:
        return _ICONS[key]
    hi = fx_id >> 24
    name = "_IR" if hi in fx_catalog.IR_CATEGORIES else _SND_RTN_SVG.get(fx_id) or _module(fx_id)
    img = None
    if name and (SVG_DIR / f"{name}.svg").exists():
        r = QSvgRenderer(str(SVG_DIR / f"{name}.svg"))
        # Size from the SVG's width/height when it has them (Send/Return/FxLoop declare 68 x 96
        # over a 457 x 644 view box); otherwise from the view box, as Guitar Lab's own SVGs.
        size = r.defaultSize()
        box = r.viewBoxF()
        w, h = (size.width(), size.height()) if size.isValid() and size.width() < box.width() else (box.width(), box.height())
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage
        img = QImage(int(w / 2), int(h / 2), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p, QRectF(0, 0, img.width(), img.height()))
        p.end()
    _ICONS[key] = img
    return img


class ChainView(QWidget):
    """EffectOverviewComponent: the effect icons joined by a cable (paint FUN_10027ec60).

    Modes (set by the editor's ADD / DELETE buttons, FUN_1000658b0 -> FUN_10027e100):
    ADD (1) draws the insertion marker 002fe7d0 at half size at the right edge of the effect
    under the mouse, and a click inserts an empty entry after it; when the patch already has
    ptcf.MAX_ENTRIES entries the cursor is the forbidden sign (seen in Guitar Lab). Left of the
    first effect the marker sits at the start of the chain (the paint's start position) and a
    click inserts at entry 0 (Guitar Lab sent `64 07 00` on Uprising, recorded).
    DELETE (2) tints the effect under the mouse red (0xffff0000) at 30 % in (2, 0, w-4, h-4)
    with a 1 px red outline, and a click deletes it.
    CLIP (3, analysis/ui-trace/CLIPBOARD.md): a click selects an effect into a box filled
    (30,97,134) at 66 % over the strip's height, with the scissors 002f4520 at half size at
    (centre - 16); a press within 8 px of the boundary at the box's start drags its left edge,
    near another boundary its end (resize cursor there), elsewhere in the box moves it
    (FUN_10027f680); at most 4 entries (a double-width effect counts 2) and no empty entries
    (FUN_100280300); a click in the box without dragging makes the clip (FUN_100067550), a
    click outside selects that effect. The mode's cursor is 002ff950 (64 x 64 at scale 2).
    Clips dropped from the Clipboard (FUN_100280b10) land at the boundary within 8 px of the
    mouse, shown with the red marker; anywhere else they go to the start of the chain."""

    CABLE = rgb(40, 47, 57)
    MARKER = "002fe7d0.png"
    NONE, ADD, DELETE, CLIP = 0, 1, 2, 3
    START = -1  # hover: left of the first effect (ADD inserts at entry 0)
    EDGE = 8    # px: the hit zone of a boundary (box edges, clip drops)
    BOX = QColor(30, 97, 134)
    SCISSORS = "002f4520.png"
    CLIP_CURSOR = "002ff950.png"
    MAX_CLIP = 4
    insert_at = Signal(int)   # entry position for the new empty effect
    move_requested = Signal(int, int)   # drag in the chain (no mode): from entry, to entry
    delete_at = Signal(int)   # entry of the effect to delete
    clip_requested = Signal(int, int)   # first entry, number of entries
    clip_dropped = Signal(int, int)     # clipboard row, entry position

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []  # (slot, image, on)
        self.spans = {}  # slot -> entries it takes (2 for a double-width effect)
        self.entries = 0
        self.mode = self.NONE
        self.hover = None
        self.box = None          # CLIP: (first item, last item)
        self._box_drag = None    # ("left" | "right" | "move", item at the press) while dragging
        self._box_press = None
        self.clip_drop = None    # entry position of a clip being dragged in (for the marker)
        self.accept_clip = lambda row: True   # FUN_100280b10, set by the editor
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    def set_effects(self, items, spans=None, entries=None):
        self.items = list(items)
        if spans is not None:
            self.spans = dict(spans)
        if entries is not None:
            self.entries = entries
        self.hover = None
        self.box = None
        self._cursor()
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.box = None
        self._cursor()
        self.update()

    def full(self):
        return self.entries >= ptcf.MAX_ENTRIES

    def _cursor(self, x=None):
        if self.mode == self.CLIP:
            if x is not None and self.box is not None and self._boundary_at(x) is not None:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                from PySide6.QtGui import QCursor, QPixmap
                img = image(self.CLIP_CURSOR)
                pm = QPixmap.fromImage(img.scaled(img.width() // 2, img.height() // 2,
                                                  Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
                self.setCursor(QCursor(pm, 0, 0))
            return
        forbidden = self.mode == self.ADD and self.full()
        self.setCursor(Qt.CursorShape.ForbiddenCursor if forbidden else Qt.CursorShape.ArrowCursor)

    # boundaries: before each effect and after the last
    def _boundaries(self):
        layout = self._layout()
        out = [x for x, _w in layout]
        if layout:
            out.append(layout[-1][0] + layout[-1][1])
        return out

    def _boundary_at(self, x):
        best = None
        for k, bx in enumerate(self._boundaries()):
            if abs(x - bx) <= self.EDGE and (best is None or abs(x - bx) < abs(x - self._boundaries()[best])):
                best = k
        return best

    def _entry_of(self, k):
        """Entry position of boundary k (before item k)."""
        return sum(self.spans.get(self.items[i][0], 1) for i in range(k))

    def _box_ok(self, first, last):
        if not 0 <= first <= last < len(self.items):
            return False
        if any(self.items[i][1] is None for i in range(first, last + 1)):
            return False   # an empty entry
        return sum(self.spans.get(self.items[i][0], 1) for i in range(first, last + 1)) <= self.MAX_CLIP

    def _box_x(self):
        layout = self._layout()
        first, last = self.box
        return layout[first][0], layout[last][0] + layout[last][1]

    def _clip_press(self, event):
        x = event.position().x()
        self._box_press, self._box_drag = x, None
        if self.box is not None:
            k = self._boundary_at(x)
            if k is not None:
                self._box_drag = ("left" if k == self.box[0] else "right", None)
                return
            bx0, bx1 = self._box_x()
            if bx0 <= x < bx1:
                self._box_drag = ("move", self._item_at(x))

    def _clip_move(self, event):
        x = event.position().x()
        if self._box_press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            self._cursor(x)
            return
        if self._box_drag is None or self.box is None:
            return
        kind, start_item = self._box_drag
        first, last = self.box
        if kind in ("left", "right"):
            bounds = self._boundaries()
            k = min(range(len(bounds)), key=lambda j: abs(bounds[j] - x))
            new = (k, last) if kind == "left" else (first, k - 1)
        else:
            here = self._item_at(x)
            if here is None or start_item is None:
                return
            shift = here - start_item
            new = (first + shift, last + shift)
            if new != self.box and self._box_ok(*new):
                self._box_drag = ("move", here)
        if new != self.box and self._box_ok(*new):
            self.box = new
            self.update()

    def _clip_release(self, event):
        x = event.position().x()
        press, self._box_press = self._box_press, None
        dragged = press is not None and abs(x - press) >= 3
        self._box_drag = None
        if press is None or event.button() != Qt.MouseButton.LeftButton or dragged:
            return
        if self.box is not None:
            bx0, bx1 = self._box_x()
            if bx0 <= x < bx1:
                first, last = self.box
                entry = self._entry_of(first)
                count = sum(self.spans.get(self.items[i][0], 1) for i in range(first, last + 1))
                self.clip_requested.emit(entry, count)
                return
        i = self._item_at(x)
        if i is not None and self._box_ok(i, i):
            self.box = (i, i)
            self.update()

    # clips dragged in from the Clipboard
    def _clip_row(self, event):
        from b6lab.gui.clipboard_view import MIME_CLIP
        md = event.mimeData()
        if not md.hasFormat(MIME_CLIP):
            return None
        import json
        return json.loads(bytes(md.data(MIME_CLIP)).decode())

    def _drop_entry(self, x):
        k = self._boundary_at(x)
        return (k, self._entry_of(k)) if k is not None else (None, 0)

    def dragEnterEvent(self, event):
        row = self._clip_row(event)
        if row is not None and self.accept_clip(row):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        row = self._clip_row(event)
        if row is None or not self.accept_clip(row):
            event.ignore()
            return
        event.acceptProposedAction()
        k, _entry = self._drop_entry(event.position().x())
        if k != self.clip_drop:
            self.clip_drop = k
            self.update()

    def dragLeaveEvent(self, _event):
        self.clip_drop = None
        self.update()

    def dropEvent(self, event):
        self.clip_drop = None
        self.update()
        row = self._clip_row(event)
        if row is None or not self.accept_clip(row):
            return
        event.acceptProposedAction()
        _k, entry = self._drop_entry(event.position().x())
        self.clip_dropped.emit(row, entry)

    def _layout(self, skip=None):
        """(x, width) per effect, centred; with `skip` (the one being dragged) the others close
        the gap from the same start, as the chain paint skips the dragged item."""
        all_widths = [(img.width() + 12 if img is not None else 48) for _slot, img, _on in self.items]
        widths = [w for k, w in enumerate(all_widths) if k != skip]
        x = (self.width() - sum(all_widths)) // 2
        out = []
        for w in widths:
            out.append((x, w))
            x += w
        return out

    def _item_at(self, x):
        for i, (ix, w) in enumerate(self._layout()):
            if ix <= x < ix + w:
                return i
        return None

    def _hover_at(self, x):
        i = self._item_at(x)
        if i is None and self.mode == self.ADD and self.items and 0 <= x < self._layout()[0][0]:
            return self.START
        return i

    def mouseMoveEvent(self, event):
        if self.mode == self.CLIP:
            self._clip_move(event)
            return
        if self.mode == self.NONE and getattr(self, "_drag_from", None) is not None \
                and event.buttons() & Qt.MouseButton.LeftButton:
            from PySide6.QtWidgets import QApplication
            ix, _w = self._layout()[self._drag_from]
            if self._drag_x is None and abs(event.position().x() - (ix + self._grab)) < QApplication.startDragDistance():
                return
            self._drag_x = event.position().x()
            self.update()
            return
        hover = self._hover_at(event.position().x()) if self.mode else None
        if hover != self.hover:
            self.hover = hover
            self.update()

    def leaveEvent(self, _event):
        if self.hover is not None:
            self.hover = None
            self.update()

    # dragging an effect (no mode): DragOverlayComp - the effect's place stays empty, a snapshot
    # follows the mouse at 80 % (FUN_100154560(0.8)); released, it goes in after the neighbours
    # its centre has passed (recorded: first effect dropped after the second sent 0 -> 1)
    def _drop_index(self, x):
        """Insertion index among the other effects for an overlay centred at x: it passes a
        neighbour once its centre passes that neighbour's centre (original positions)."""
        rest = [k for k in range(len(self.items)) if k != self._drag_from]
        full = self._layout()
        return sum(1 for k in rest if full[k][0] + full[k][1] / 2 < x and k > self._drag_from) + \
            sum(1 for k in rest if k < self._drag_from and full[k][0] + full[k][1] / 2 < x), rest

    def mouseReleaseEvent(self, event):
        if self.mode == self.CLIP:
            self._clip_release(event)
            return
        start, self._drag_from = getattr(self, "_drag_from", None), None
        dragging, self._drag_x = getattr(self, "_drag_x", None), None
        self.update()
        if self.mode != self.NONE or start is None or dragging is None:
            return
        self._drag_from = start
        _ix, w = self._layout()[start]
        index, rest = self._drop_index(event.position().x() - self._grab + w / 2)   # overlay centre
        self._drag_from = None
        if index == start:          # back where it was
            return
        before = rest[:index]
        dst = sum(self.spans.get(self.items[k][0], 1) for k in before)
        self.move_requested.emit(self.items[start][0], dst)

    def mousePressEvent(self, event):
        if self.mode == self.CLIP:
            if event.button() == Qt.MouseButton.LeftButton:
                self._clip_press(event)
            return
        if self.mode == self.NONE and event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = self._item_at(event.position().x())
            self._drag_x = None
            if self._drag_from is not None:
                ix, _w = self._layout()[self._drag_from]
                self._grab = event.position().x() - ix
            return
        i = self._hover_at(event.position().x())
        if i is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if i == self.START:
            if self.mode == self.ADD and not self.full():
                self.insert_at.emit(0)
            return
        slot = self.items[i][0]
        if self.mode == self.ADD and not self.full():
            self.insert_at.emit(slot + self.spans.get(slot, 1))
        elif self.mode == self.DELETE:
            self.delete_at.emit(slot)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        h = self.height()
        cable_y = int((h - 6) * 0.5)
        dragging = getattr(self, "_drag_x", None) is not None and getattr(self, "_drag_from", None) is not None
        # the paint (FUN_10027ec60) skips the dragged effect but still advances past it: its place
        # stays empty while the snapshot follows the mouse
        items = self.items
        layout = self._layout()
        x = layout[0][0] if layout else self.width()
        p.fillRect(0, cable_y, max(0, x), 6, self.CABLE)
        for i, ((slot, img, on), (x, w)) in enumerate(zip(items, layout)):
            if dragging and i == self._drag_from:
                p.fillRect(x, cable_y, w, 6, self.CABLE)
                continue
            if img is None:
                p.fillRect(x, cable_y, w, 6, self.CABLE)
            else:
                p.save()
                if not on:
                    p.setOpacity(0.35)
                p.drawImage(x + 6, 2 + 3, img)  # setOrigin(x, 2), then drawImageAt(6, 3)
                p.restore()
                p.fillRect(x, cable_y - 2 + 2, 6, 6, self.CABLE)
                p.fillRect(x + w - 6, cable_y, 6, 6, self.CABLE)
            if self.mode == self.DELETE and i == self.hover:
                red = QColor(255, 0, 0)
                tint = QColor(red)
                tint.setAlphaF(0.3)
                p.fillRect(QRectF(x + 2, 2, w - 4, h - 4), tint)
                p.setPen(red)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(x + 2.5, 2.5, w - 5, h - 5))
        end = layout[-1][0] + layout[-1][1] if layout else 0
        if end < self.width():
            p.fillRect(end, cable_y, self.width() - end, 6, self.CABLE)
        if dragging:
            # the red insertion marker also shows while dragging (paint: mode ADD or the drag
            # flag), at the right edge of the effect it will land after (or before the first)
            _ix, dw = layout[self._drag_from]
            index, rest = self._drop_index(self._drag_x - self._grab + dw / 2)
            if index != self._drag_from:
                if index == 0:
                    mx = layout[rest[0]][0] if rest else 0
                else:
                    ax, aw = layout[rest[index - 1]]
                    mx = ax + aw
                marker = image(self.MARKER)
                p.drawImage(QRectF(mx - 6, 0, marker.width() / 2, marker.height() / 2), marker)
            _slot, img, on = self.items[self._drag_from]
            if img is not None:
                p.save()
                p.setOpacity(0.8 * (1.0 if on else 0.35))
                p.drawImage(QRectF(self._drag_x - self._grab + 6, 2 + 3, img.width(), img.height()), img)
                p.restore()
        if self.mode == self.ADD and self.hover is not None and not self.full():
            marker = image(self.MARKER)
            hx, hw = (layout[0][0], 0) if self.hover == self.START else layout[self.hover]
            p.drawImage(QRectF(hx + hw - 6, 0, marker.width() / 2, marker.height() / 2), marker)
        if self.mode == self.CLIP and self.box is not None:
            bx0, bx1 = self._box_x()
            fill = QColor(self.BOX)
            fill.setAlphaF(0.66)
            p.fillRect(QRectF(bx0, 0, bx1 - bx0, h), fill)
            sc = image(self.SCISSORS)
            cx = (bx0 + bx1) / 2
            p.drawImage(QRectF(cx - 16, h / 2 - 16, sc.width() / 2, sc.height() / 2), sc)
        if self.clip_drop is not None:
            bounds = self._boundaries()
            if self.clip_drop < len(bounds):
                marker = image(self.MARKER)
                p.drawImage(QRectF(bounds[self.clip_drop] - 6, 0, marker.width() / 2, marker.height() / 2),
                            marker)


class _PedalRow(QWidget):
    """The viewport content: pedals spaced like EditorPageComponent::resized."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pedals = []

    def resizeEvent(self, _event):
        n = len(self.pedals)
        if not n:
            return
        per = min(self.width() // n, 260)
        x = int((self.width() - n * per) * 0.5 + 8.0)
        for pedal in self.pedals:
            pedal.setGeometry(x, 0, per - 16, int((per - 16) * 1.1))
            x += per

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), rgb(26, 30, 36))


class EditorView(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.slot = None
        self.loaded = b""
        self.working = None
        self._base = b""
        self._pending_open = None
        self.connected = False
        self.boxes = []
        self.chain_blocks = {}
        self._saving = None
        self._sent = b""  # bytes of the save in flight
        self._invalid = {}
        self._offline = None
        self.processor = 0.0
        self.picker = None       # the open TYPE picker's content (glpicker), if any
        self.picker_slot = None
        self.tempo = 120
        # live knobs: latest value per (effect entry, knob), sent after a few ms; checked after a pause
        self._live_params = {}
        self._send_timer = QTimer(self, singleShot=True, interval=20)
        self._send_timer.timeout.connect(self._send_live_params)
        self._check_timer = QTimer(self, singleShot=True, interval=700)
        self._check_timer.timeout.connect(self._check_live)

        self.buttons = {}
        for caption, images in BUTTONS.items():
            b = ImageButton(*images, caption="" if caption == "TAP" else caption, placement="fit", parent=self)
            self.buttons[caption] = b
        self.save_button = self.buttons["SAVE"]
        self.expand_button = ImageButton(*EXPAND, placement="fit", parent=self)
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(lambda _on: (self.resizeEvent(None), self.pedal_host.resizeEvent(None)))

        self.slot_label = _Text(font(24, True), parent=self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setMaxLength(10)
        self.name_edit.setFrame(False)
        self.name_edit.setFont(font(24, True))
        self.name_edit.setStyleSheet("QLineEdit { background: transparent; color: rgb(225,248,254); border: 0; }"
                                     "QLineEdit:focus { background: rgb(54,66,80); }")
        self.name_edit.setTextMargins(0, 0, 0, 0)
        self.comment_edit = QLineEdit(self)
        self.comment_edit.hide()
        self.processor_label = _Text(font(14), parent=self)
        self.bpm_label = _Text(font(12), justification=0x0C, parent=self)
        self.chain = ChainView(self)
        self.level_dial = Knob(self)
        self.level_dial.text_box = (30, 13)
        self.level_dial.setRange(0, 120)
        self.level_dial.setToolTip("Patch level")
        self.level_value = QLabel(self)
        self.level_value.hide()

        self.pedal_host = _PedalRow()
        self.scroll = QScrollArea(self)
        self.scroll.setWidget(self.pedal_host)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: rgb(26,30,36); border: 0; }")

        self.model = PatchListModel(self)
        self.list = QTableView(self)
        self.search_box, self.proxy = patch_search.attach(self, self.list, self.model)
        configure_patch_table(self.list)
        self.list.clicked.connect(lambda idx: self.open_slot(self.proxy.slot_of_row(idx.row())))
        self.search_box.returnPressed.connect(self._open_search_choice)
        self.search_box.step.connect(self._search_step)
        self.search_box.textChanged.connect(lambda _t: setattr(self, "_search_nav", False))
        self._search_nav = False   # the user moved the selection with Up/Down since the last edit
        self.proxy.refreshed.connect(self._reselect_open_slot)
        self.list.doubleClicked.connect(self._edit_comment_dialog)
        # the same PatchListComponent as on the PATCH page: rows drag into the Patch Pool, pool
        # patches / groups dropped on a row are imported (handled by the PATCH page)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QTableView.DragDropMode.DragOnly)
        self.list.viewport().setAcceptDrops(True)
        self.list.viewport().installEventFilter(self)
        self.bar = QWidget(self)
        self.bar.setStyleSheet("background: #1a1e24;")
        from b6lab.clipboard import Clipboard
        from b6lab.gui.clipboard_view import ClipboardView
        import os
        from b6lab.clipboard import DEFAULT_ROOT as CLIP_ROOT
        self.clip_board = Clipboard(os.environ.get("B6LAB_CLIPBOARD") or CLIP_ROOT)
        self.clipboard = ClipboardView(self.clip_board, self)
        self.clipboard.clip_menu.connect(self._clip_menu)
        self.clipboard.renamed.connect(self._clip_renamed)
        self.clipboard.reordered.connect(self._clip_reordered)
        self._pending_action = None
        self.auto_save = False   # the pedal's AUTO SAVE (global data byte 12, device + 0x6486)

        self.name_edit.textEdited.connect(self._name_edited)
        self.comment_edit.textEdited.connect(self._comment_edited)
        self.level_dial.valueChanged.connect(self._level_edited)
        self.save_button.clicked.connect(lambda _checked=False: self.save())
        # ADD / DELETE / CLIP are exclusive toggles that put the chain view in a mode
        # (FUN_1000658b0); the mode ends after an insert or a delete (seen in Guitar Lab).
        for name in ("ADD", "DELETE", "CLIP"):
            self.buttons[name].setCheckable(True)
        # TAP: triggered on mouse down (FUN_1001cde50(tap, 1)); 60000 / the time between two
        # taps, used when 40..250 BPM (FUN_1000658b0)
        self._last_tap = None
        self.buttons["TAP"].pressed.connect(self._tap)
        # the BPM text can be edited (Label 0x1980, FUN_100065d00 / FUN_100065ff0)
        self.bpm_edit = QLineEdit(self)
        self.bpm_edit.hide()
        self.bpm_edit.setFrame(False)
        self.bpm_edit.setFont(font(12))
        self.bpm_edit.setStyleSheet("QLineEdit { background: rgb(54,66,80); color: rgb(225,248,254); border: 0; }")
        self.bpm_edit.editingFinished.connect(self._bpm_edited)
        self.bpm_label.mouseDoubleClickEvent = lambda _e: self._edit_bpm()
        # TUNER (FUN_1000658b0): the tuner display takes the chain's place; while it is on, any
        # of the editor's buttons only switches it off
        from b6lab.gui.gltuner import TunerView
        self.tuner = TunerView(self)
        self.tuner.hide()
        self.buttons["TUNER"].setCheckable(True)
        self.buttons["TUNER"].toggled.connect(self._tuner_toggled)
        for name, b in self.buttons.items():
            if name != "TUNER":
                b.installEventFilter(self)
        window.worker.tuner_reading.connect(self.tuner.set_reading)
        # sync mode: follow what is done on the pedal itself
        window.worker.pedal_slot.connect(self._on_pedal_slot)
        window.worker.auto_save.connect(lambda on: setattr(self, "auto_save", on))
        window.worker.pedal_switch.connect(lambda entry, on: self._on_effect_state(self.slot, entry, on))
        window.worker.pedal_param.connect(self._on_pedal_param)
        window.worker.tuner_calibration.connect(lambda hz: setattr(self.tuner, "calibration", hz))
        self.buttons["ADD"].toggled.connect(lambda on: self._chain_mode("ADD", on))
        self.buttons["DELETE"].toggled.connect(lambda on: self._chain_mode("DELETE", on))
        self.buttons["CLIP"].toggled.connect(self._clip_toggled)
        self.chain.clip_requested.connect(self._make_clip)
        self.chain.clip_dropped.connect(self._drop_clip)
        self.chain.accept_clip = self._accept_clip
        window.worker.clip_added.connect(self._on_clip_added)
        self.chain.insert_at.connect(lambda pos: self._edit_chain("insert", pos))
        self.chain.delete_at.connect(lambda pos: self._edit_chain("delete", pos))
        self.chain.move_requested.connect(self._move_effect)

        w = window.worker
        w.connected.connect(self._on_connected)
        w.disconnected.connect(self._on_disconnected)
        w.all_loaded.connect(self.model.set_all)
        w.slot_loaded.connect(self._on_slot_loaded)
        w.saved.connect(self._on_saved)
        w.effect_state.connect(self._on_effect_state)
        w.tempo.connect(self._on_tempo)
        w.current_slot.connect(self._on_current_slot)
        w.type_changed.connect(self._on_type_changed)
        self._set_texts()
        self._update_save()

    # layout and drawing -----------------------------------------------------------
    def resizeEvent(self, _event):
        w, h = self.width(), self.height()
        cx = w // 2
        geo = {"ADD": (cx - 573, 36, 41, 54), "DELETE": (cx - 524, 36, 34, 54), "CLIP": (cx - 477, 36, 34, 54),
               "SAVE": (cx + 446, 36, 34, 54), "TAP": (cx + 492, 56, 34, 34), "TUNER": (cx + 536, 36, 34, 54)}
        for name, g in geo.items():
            self.buttons[name].setGeometry(*g)
        self.bpm_label.setGeometry(cx + 487, 38, 44, 14)
        self.chain.setGeometry(cx - 176, 34, 495, 56)
        self.tuner.setGeometry(self.chain.geometry())
        self.slot_label.setGeometry(cx - 406, 32, 64, 24)
        self.name_edit.setGeometry(cx - 336, 32, 128, 24)
        self.processor_label.setGeometry(cx - 406, 72, 76, 20)
        self.level_dial.setGeometry(cx + 352, 36, 54, 64)
        self.scroll.setGeometry(0, 120, w, 280)
        n = len(self.pedal_host.pedals)
        # FUN_1000651a0: with the expand button on, the row is n x 244 + 16 wide (and scrolls when
        # that is wider than the page); off, it is the page width and the pedals shrink to fit
        content = max(n * 244 + 16, w) if self.expand_button.isChecked() else w
        self.pedal_host.resize(content, 280)
        # lower part (StretchableLayoutManager): list | 4 px bar | clipboard 430 px
        top = 400
        lw = max(0, w - 434)
        self.search_box.setGeometry(8, top + 5, max(0, lw - 16), patch_search.HEIGHT - 10)
        self.list.setGeometry(0, top + patch_search.HEIGHT, lw, max(0, h - top - patch_search.HEIGHT))
        self.bar.setGeometry(lw, top, 4, max(0, h - top))
        self.clipboard.setGeometry(lw + 4, top, 430, max(0, h - top))
        self.expand_button.setGeometry(w - 32, top - 36, 18, 18)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), rgb(26, 30, 36))
        cx = self.width() // 2
        panel = image(PATCH_PANEL)
        p.drawImage(QRectF(cx - 430, 20, panel.width() / 2, panel.height() / 2), panel)
        p.setPen(rgb(223, 248, 254))
        draw_fitted_text(p, "LEVEL", QRectF(cx + 352, 26, 54, 14), font(12, True), 0x24)
        x = cx - 406 + 76 + 8
        frac = min(1.0, self.processor)
        p.fillRect(x, 75, int(frac * 82), 7, rgb(33, 145, 175))
        p.fillRect(x + int(frac * 82), 75, int((1 - frac) * 82), 7, rgb(30, 97, 134))
        arrow = QPainterPath()
        arrow.moveTo(cx - 188, 56)
        arrow.lineTo(cx - 180, 62)
        arrow.lineTo(cx - 188, 70)
        arrow.closeSubpath()
        p.fillPath(arrow, rgb(40, 47, 57))

    def _on_current_slot(self, slot):
        """Guitar Lab opens the pedal's current patch after connecting."""
        if self.slot is None and 0 <= slot < self.model.rowCount():
            self.open_slot(slot)

    # the pedal itself (sync mode)
    def _on_pedal_slot(self, slot):
        """The pedal switched patch (its footswitches, or the echo of our own program change):
        show that patch. The pedal has dropped any unsaved edit already, so nothing is asked."""
        if slot == self.slot or self._saving is not None or not 0 <= slot < self.model.rowCount():
            return
        self._start_open(slot, select=False)   # the pedal is there already; only read it

    def _on_pedal_param(self, entry, index, value):
        """A knob turned on the pedal: the patch and the knob follow."""
        if self.working is None or not 0 <= entry < len(self.working.effects):
            return
        e = self.working.effects[entry]
        if not e.editable(index) or (index < len(e.params) and e.params[index] == value):
            return
        ptcf.set_param(self.working, entry, index, value)
        for pedal in self.pedal_host.pedals:
            if pedal.head.slot == entry and pedal.first <= index < pedal.first + 4:
                dial = pedal.dials[index - pedal.first]
                dial.blockSignals(True)
                dial.setValue(value)
                dial.blockSignals(False)
                pedal.update()
        self._update_save()

    # tuner
    def _tuner_toggled(self, on):
        if on and not self.connected:
            self.buttons["TUNER"].setChecked(False)
            return
        self.tuner.setGeometry(self.chain.geometry())
        self.tuner.set_reading(None, None)
        self.tuner.setVisible(on)
        self.chain.setVisible(not on)
        if self.connected:
            self.window.request_tuner.emit(on)

    def _tuner_off_first(self):
        if self.buttons["TUNER"].isChecked():
            self.buttons["TUNER"].setChecked(False)

    # tempo
    def _tap(self, now=None):
        import time
        now = time.monotonic() * 1000 if now is None else now
        last, self._last_tap = self._last_tap, now
        if last is None or now <= last:
            return
        bpm = 60000.0 / (now - last)
        if 40.0 <= bpm <= 250.0:
            self._send_tempo(int(bpm))

    def _edit_bpm(self):
        """Editing shows the number without " BPM" (FUN_100065ff0)."""
        self.bpm_edit.setGeometry(self.bpm_label.geometry())
        self.bpm_edit.setText(str(self.tempo))
        self._bpm_editing = True
        self.bpm_edit.show()
        self.bpm_edit.setFocus()
        self.bpm_edit.selectAll()

    def _bpm_edited(self):
        """FUN_100065d00: a value outside 40..250 shows the pedal's tempo again; otherwise it is
        rounded and sent."""
        if not getattr(self, "_bpm_editing", False):
            return
        self._bpm_editing = False
        self.bpm_edit.hide()
        try:
            value = float(self.bpm_edit.text().replace("BPM", "").strip())
        except ValueError:
            value = 0.0
        if 40.0 <= value <= 250.0:
            self._send_tempo(int(value + 0.5))
        else:
            self._set_texts()

    def _send_tempo(self, bpm):
        self.tempo = bpm
        self._set_texts()
        if self.connected:
            self.window.request_tempo.emit(bpm)

    def _on_tempo(self, bpm):
        self.tempo = bpm
        self._set_texts()

    def _set_texts(self):
        self.slot_label.text = slot_label(self.slot) if self.slot is not None else "---"
        self.processor_label.text = f"Processor {round(self.processor * 100)}%"
        self.bpm_label.text = f"{self.tempo} BPM"
        for wdg in (self.slot_label, self.processor_label, self.bpm_label):
            wdg.update()
        self.update()

    # state helpers
    def _edit_comment_dialog(self, index):
        if index.column() != 2 or self.proxy.slot_of_row(index.row()) != self.slot or self.working is None:
            return
        value, accepted = QInputDialog.getText(self, "Edit comment", "Comment:", text=self.comment_edit.text())
        if accepted:
            self.comment_edit.setText(value)
            self._comment_edited(value)

    def modified(self):
        return self.working is not None and ptcf.encode(self.working) != self._base

    def _on_connected(self, _ident):
        self._set_connected(True)

    def _on_disconnected(self, _reason):
        self._set_connected(False)

    def _set_connected(self, ok):
        self.connected = ok
        self._update_save()

    def _update_save(self):
        # Guitar Lab keeps SAVE enabled whenever a patch is open, changed or not.
        ok = (self.connected and self.working is not None
              and not self._invalid and self._saving is None)
        self.save_button.setEnabled(ok)
        has_patch = self.working is not None
        self.name_edit.setEnabled(has_patch)
        self.comment_edit.setEnabled(has_patch)
        level = self.working.level if has_patch else None
        self.level_dial.setEnabled(level is not None and level <= 120)
        tip = "not connected" if not self.connected else "; ".join(self._invalid.values())
        self.save_button.setToolTip(tip)
        if self.slot is not None:
            self.model.set_modified(self.slot, self.modified())

    def _select_slot(self, slot):
        row = self.proxy.row_of_slot(slot) if slot is not None else -1
        if row >= 0:
            self.list.selectRow(row)
        else:
            self.list.clearSelection()

    def _reselect_open_slot(self):
        """A filter change hides / shows rows: keep the open patch highlighted."""
        if self.slot is not None and not self.list.selectionModel().selectedRows():
            self._select_slot(self.slot)

    def _search_step(self, delta):
        """Up / Down in the search field move the selection through the hits."""
        n = self.proxy.rowCount()
        if not self.proxy.filtering() or n == 0:
            return
        rows = self.list.selectionModel().selectedRows()
        row = rows[0].row() + delta if rows and self._search_nav else (0 if delta > 0 else n - 1)
        self.list.selectRow(max(0, min(n - 1, row)))
        self._search_nav = True

    def _open_search_choice(self):
        """Enter in the search field: only while filtering. Opens the hit chosen with Up/Down,
        else the first hit."""
        if not self.proxy.filtering() or self.proxy.rowCount() == 0:
            return
        rows = self.list.selectionModel().selectedRows()
        row = rows[0].row() if rows and self._search_nav else 0
        slot = self.proxy.slot_of_row(row)
        if slot >= 0:
            self.open_slot(slot)

    # navigation
    def open_slot(self, slot):
        if slot == self.slot and self.working is not None:
            return
        if self._saving is not None:
            self._select_slot(self._saving)
            return
        if self.modified() and self.auto_save:
            # FUN_100119660 with AUTO SAVE on: no question and no save from the app; the edits
            # are on the pedal, which stores them itself when the patch changes
            self.model.set_slot(self.slot, ptcf.encode(self.working))
        elif self.modified():
            # Guitar Lab (recorded on the B6, 2026-11-09): leaving a changed patch opens the
            # "Save Changes" dialog; OK saves (to the patch chosen there) and then switches,
            # Cancel drops the changes and switches.
            dest = self.ask_save_destination()
            if dest is not None:
                self._pending_open = slot
                self.save(dest)
                return
        self._start_open(slot)

    def show_offline(self, slots):
        """Show a read-only list of patches (a backup set) while not connected."""
        self._offline = list(slots)
        self.slot = None
        self.working = None
        self.level_value.setText("-")
        self.model.set_all(self._offline)
        self._update_save()

    def _start_open(self, slot, select=True):
        if not self.connected and self._offline is not None:
            self.slot = slot
            self._select_slot(slot)
            self.loaded = bytes(self._offline[slot])
            try:
                self.working = ptcf.parse(self.loaded)
            except ValueError as e:
                self.window.show_error(f"slot {slot + 1}: {e}")
                return
            self._base = ptcf.encode(ptcf.parse(self.loaded))
            self._rebuild()
            return
        if self.slot is not None:
            self.model.set_modified(self.slot, False)
        self.slot = slot
        self._select_slot(slot)
        # Show nothing until this slot's data arrives: the old patch must never be
        # editable (or savable) while self.slot already names the new slot.
        self._show_loading()
        if select:
            self.window.request_select.emit(slot)
        self.window.request_load_slot.emit(slot)

    def _on_slot_loaded(self, slot, data):
        self.model.set_slot(slot, data)
        if slot != self.slot:
            return
        try:
            working = ptcf.parse(data)
        except ValueError as e:
            self.window.show_error(f"slot {slot + 1}: {e}")
            return
        self.loaded = bytes(data)
        self.working = working
        self._base = ptcf.encode(ptcf.parse(data))
        self._rebuild()
        index = self.proxy.index_of_slot(slot)
        if index.isValid():
            self.list.scrollTo(index, QTableView.ScrollHint.PositionAtTop)

    def _clear_boxes(self):
        for pedal in self.pedal_host.pedals:
            pedal.deleteLater()
        self.pedal_host.pedals = []
        self.boxes = []
        self.chain_blocks = {}
        self.chain.set_effects([], {}, 0)

    def _show_loading(self):
        self._live_params.clear()
        self._send_timer.stop()
        self._check_timer.stop()
        self.working = None
        self.loaded = b""
        self._base = b""
        self._invalid.clear()
        self.level_value.setText("-")
        self._set_texts()
        for edit in (self.name_edit, self.comment_edit):
            edit.clear()
        self._clear_boxes()
        self._update_save()

    def _rebuild(self):
        p = self.working
        self.level_dial.blockSignals(True)
        self.level_dial.setValue(min(p.level, 120) if p.level is not None else 0)
        self.level_dial.blockSignals(False)
        self.level_value.setText(str(p.level) if p.level is not None else "-")
        for edit, text in ((self.name_edit, p.name), (self.comment_edit, p.comment)):
            edit.setText(text)
        self._clear_boxes()
        effects = p.effects
        chain = []
        for i, e in enumerate(effects):
            wide = i + 1 < len(effects) and effects[i + 1].is_tail
            head = effects[i - 1] if e.is_tail and i > 0 else e
            info = fx_catalog.lookup(head.fx_id) if head.fx_id else None
            kind = 2 if e.is_tail else (1 if wide else 0)
            pedal = Pedal(e, info=info, kind=kind, head=head, parent=self.pedal_host)
            pedal.param_changed.connect(self._param_changed)
            pedal.toggled.connect(self._toggled)
            if not e.is_tail:
                pedal.type_button.clicked.connect(lambda _c=False, s=e.slot: self._type_clicked(s))
            pedal.show()
            self.pedal_host.pedals.append(pedal)
            if not e.is_tail:
                self.boxes.append(pedal)
                chain.append((e.slot, chain_icon(e.fx_id, wide) if e.fx_id else None, e.on))
                self.chain_blocks[e.slot] = (pedal, None, True)
        spans = {e.slot: (2 if i + 1 < len(effects) and effects[i + 1].is_tail else 1)
                 for i, e in enumerate(effects) if not e.is_tail}
        self.chain.set_effects(chain, spans, len(effects))
        # EditorPageComponent (FUN_100066240): sum of the effects' loads; 220 = 100 %
        self.processor = sum(fx_catalog.dsp_load(e.fx_id) or 0 for e in effects
                             if e.fx_id and not e.is_tail) / 220
        self.clipboard.set_patch_load(self.processor)
        self._invalid.clear()
        self._set_texts()
        self.resizeEvent(None)
        self.pedal_host.resizeEvent(None)
        self._update_save()

    # edits
    def _param_changed(self, slot, index, value):
        if self.working is None:
            return
        try:
            ptcf.set_param(self.working, slot, index, value)
        except PermissionError as e:
            self.window.show_error(str(e))
            return
        finally:
            self._update_save()
        if self.connected and self.slot is not None:
            # Live: the pedal hears it right away (edit buffer only; nothing stored until Save).
            self._live_params[(slot, index)] = self.working.effects[slot].params[index]
            if not self._send_timer.isActive():
                self._send_timer.start()

    def _send_live_params(self):
        params, self._live_params = self._live_params, {}
        for (slot, index), value in params.items():
            self.window.request_param_live.emit(slot, index, value)
        self._check_timer.start()

    def _check_live(self):
        if self.connected and self.slot is not None and self.working is not None:
            self.window.request_check_live.emit(self.slot, ptcf.encode(self.working))

    def _toggled(self, slot, on):
        if self.working is not None:
            self._apply_on(slot, on)
            if self.connected and self.slot is not None:
                # Live: switch it on the pedal too (its edit buffer; nothing is stored until Save).
                fx_ids = [e.fx_id for e in self.working.effects]
                self.window.request_effect_on.emit(self.slot, slot, on, fx_ids)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonPress and obj in self.buttons.values() \
                and obj is not self.buttons["TUNER"] and self.buttons["TUNER"].isChecked():
            self._tuner_off_first()
            return True   # the click only ends the tuner (FUN_1000658b0)
        if obj is self.list.viewport() and event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                                                            QEvent.Type.Drop):
            from b6lab.gui.patch_pool import MIME_POOL, node_at
            pages = getattr(self.window, "patches_tab", None)
            if pages is None or not event.mimeData().hasFormat(MIME_POOL):
                return False
            event.acceptProposedAction()
            if event.type() == QEvent.Type.Drop:
                import json
                path = json.loads(bytes(event.mimeData().data(MIME_POOL)).decode())
                pages.import_from_pool(node_at(pages.pool_store.tree, path),
                                       self.proxy.slot_of_row(self.list.rowAt(int(event.position().y()))))
            return True
        return super().eventFilter(obj, event)

    def _move_effect(self, src, dst):
        if self.connected and self.slot is not None and self.working is not None:
            self.window.request_move_effect.emit(self.slot, src, dst)

    # ADD / DELETE
    def _chain_mode(self, name, on):
        if on:
            for other in ("ADD", "DELETE", "CLIP"):
                if other != name:
                    self.buttons[other].setChecked(False)
        mode = {"ADD": ChainView.ADD, "DELETE": ChainView.DELETE, "CLIP": ChainView.CLIP}[name]
        if on:
            self.chain.set_mode(mode)
        elif self.chain.mode == mode:
            self.chain.set_mode(ChainView.NONE)

    def _edit_chain(self, op, position):
        """Insert an empty effect / delete one on the pedal (edit buffer); the editor then
        shows the edit buffer the pedal reports (_on_type_changed)."""
        for name in ("ADD", "DELETE"):
            self.buttons[name].setChecked(False)
        if not self.connected or self.slot is None or self.working is None:
            return
        self.window.request_chain.emit(self.slot, op, position)

    # CLIP and the Clipboard (analysis/ui-trace/CLIPBOARD.md)
    def _saved_first(self, action):
        """Guitar Lab before making a clip and adding one (FUN_100067550 / FUN_100067910): a
        changed patch opens the "Save Changes" dialog with AUTO SAVE off; OK saves and goes on,
        Cancel stops. With AUTO SAVE on it is stored silently (Patch Save `64 0D` only).
        Returns False when stopped."""
        if not self.modified():
            action()
            return True
        if self.auto_save:
            self.window.request_store.emit(self.slot)
            self.loaded = ptcf.encode(self.working)
            self._base = ptcf.encode(ptcf.parse(self.loaded))
            self.model.set_slot(self.slot, self.loaded)
            self._update_save()
            action()
            return True
        dest = self.ask_save_destination()
        if dest is None:
            return False
        self._pending_action = action
        self.save(dest)
        return True

    def _clip_toggled(self, on):
        # FUN_1000658b0: the question only with AUTO SAVE off; with it on, no question, no save
        if on and self.modified() and not self.auto_save:
            if not self._saved_first(lambda: None):
                self.buttons["CLIP"].blockSignals(True)
                self.buttons["CLIP"].setChecked(False)
                self.buttons["CLIP"].blockSignals(False)
                return
        self._chain_mode("CLIP", on)

    def _make_clip(self, first, count):
        """A click in the CLIP box (FUN_100067550): CLIP ends, then the clip "Clip <n>" is
        stored in the Clipboard and selected. No MIDI (recorded)."""
        from b6lab import clipboard
        self.buttons["CLIP"].setChecked(False)
        if self.working is None:
            return

        def make():
            clip = clipboard.clip_from_patch(self.working, first, count, self.clip_board.next_name())
            self.clip_board.add(clip)
            self.clipboard.refresh()
            self.clipboard.select_last()
        self._saved_first(make)

    def _clip_menu(self, node, pos):
        """FUN_10026a870: "Delete" only; no question, no undo."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        delete = menu.addAction("Delete")
        if self.exec_menu(menu, pos) is delete:
            self.clip_board.remove(node)
            self.clipboard.refresh()

    @staticmethod
    def exec_menu(menu, pos):
        return menu.exec(pos)

    def _clip_renamed(self, node, name):
        self.clip_board.rename(node, name)
        self.clipboard.refresh()

    def _clip_reordered(self, node, index):
        self.clip_board.move(node, index)
        self.clipboard.refresh()

    def _clip_at(self, row):
        items = self.clip_board.items
        return self.clipboard.clip(items[row]) if 0 <= row < len(items) else None

    def _accept_clip(self, row):
        """FUN_100280b10: the clip's entries fit next to the patch's (empty entries do not
        count) and the processor stays within 100 %; otherwise the drop is refused. An unusable
        clip (FUN_1002b04c0 repeats the dim test, clipboard.usable) is refused too."""
        from b6lab import clipboard
        from b6lab.gui.clipboard_view import clip_load
        clip = self._clip_at(row)
        if clip is None or not self.connected or self.working is None or self._saving is not None:
            return False
        if not clipboard.usable(clip):
            return False
        used = sum(1 for e in self.working.effects if e.fx_id != 0)
        return used + len(clip.entries) <= ptcf.MAX_ENTRIES and self.processor * 100 + clip_load(clip) <= 100

    def _drop_clip(self, row, entry):
        """FUN_100067910: save a changed patch first (or stop), make room by removing empty
        entries when needed, insert the clip and write the whole patch to its slot."""
        from b6lab import clipboard
        clip = self._clip_at(row)
        if clip is None or self.working is None or self.slot is None:
            return

        def add():
            patch = ptcf.parse(ptcf.encode(self.working))
            # FUN_1002b0fb0: exactly as many empty entries as the clip needs are deleted live on
            # the pedal (`64 20 00 64 08 <entry>`), highest first, the insert point moving down
            # for each one before it; too few empties: nothing is sent
            pos, deletes = entry, []
            excess = len(patch.effects) + len(clip.entries) - ptcf.MAX_ENTRIES
            for k in reversed(range(len(patch.effects))):
                if len(deletes) >= excess:
                    break
                if patch.effects[k].fx_id == 0:
                    deletes.append(k)
            for k in deletes:
                del patch.effects[k]
                del patch.effect_ids[k]
                if k < pos:
                    pos -= 1
            ptcf._renumber(patch)
            pos = min(pos, len(patch.effects))
            if not clipboard.insert_clip(patch, clip, pos):
                return
            if not self.window.begin_save(self):
                return
            self._saving = self.slot
            self._update_save()
            self.window.request_add_clip.emit(self.slot, ptcf.encode(patch), (deletes, clip, pos),
                                              self.auto_save)
        self._saved_first(add)

    def _on_clip_added(self, res, slot, sent):
        if self._saving is None:
            return
        self._saving = None
        self.window.end_save(self)
        self._update_save()
        if not res.ok:
            self.window.report_save_failed(res)
            return
        self.model.set_slot(slot, sent)
        if slot == self.slot:
            self.loaded = sent
            self.working = ptcf.parse(sent)
            self._base = ptcf.encode(ptcf.parse(sent))
            self._rebuild()
        self.clipboard.update()

    # TYPE picker
    def _type_clicked(self, slot):
        # opened after the click has returned: a type change rebuilds the pedals, and the
        # button that was clicked is one of them
        QTimer.singleShot(0, lambda: self.open_type_picker(slot))

    def open_type_picker(self, slot):
        """Guitar Lab's "Effect Type List" (glpicker.py) for the effect at entry `slot`.
        It lists the device's effects, so it needs the pedal, like in Guitar Lab."""
        if not self.connected or self.slot is None or self.working is None:
            return
        fx_ids = [e.fx_id for e in self.working.effects]
        if not 0 <= slot < len(fx_ids) or fx_ids[slot] == 1:
            return
        patch_slot = self.slot
        self.picker_slot = slot
        try:
            glpicker.open_picker(self, fx_ids, slot,
                                 lambda fx_id: self.window.request_type.emit(patch_slot, slot, fx_id))
        finally:
            self.picker_slot = None

    def _on_type_changed(self, patch_slot, data):
        """The pedal's edit buffer after a TYPE change: the editor takes its effects (the
        pedal decides knob values and double-width layout); name, comment and level stay."""
        if patch_slot != self.slot or self.working is None:
            return
        try:
            edit = ptcf.parse(data)
        except ValueError as e:
            self.window.show_error(f"effect type change: {e}")
            return
        p = self.working
        p.slots, p.effect_ids, p.effects = edit.slots, list(edit.effect_ids), edit.effects
        self._rebuild()
        if self.picker is not None:
            self.picker.set_fx_ids([e.fx_id for e in p.effects])

    def _apply_on(self, slot, on):
        ptcf.set_on(self.working, slot, on)
        self.chain.set_effects([(sl, img, (on if sl == slot else o)) for sl, img, o in self.chain.items])
        self._update_save()

    def _on_effect_state(self, patch_slot, slot, on):
        """The pedal's actual on/off state after a live switch: the editor follows it."""
        if patch_slot != self.slot or self.working is None or slot >= len(self.working.effects):
            return
        if self.working.effects[slot].on != on:
            self._apply_on(slot, on)
        for box in self.boxes:
            if box.slot == slot:
                box.set_on(on)

    def _name_edited(self, text):
        self._apply_text(self.name_edit, ptcf.set_name, text)

    def _level_edited(self, value):
        if self.working is not None:
            ptcf.set_level(self.working, value)
            self.level_value.setText(str(value))
            self._update_save()

    def _comment_edited(self, text):
        self._apply_text(self.comment_edit, ptcf.set_comment, text)

    def _apply_text(self, edit, setter, text):
        if self.working is None:
            return
        try:
            setter(self.working, text)
            edit.setStyleSheet("")
            self._invalid.pop(edit, None)
        except ValueError as e:
            edit.setStyleSheet(f"border: 1px solid {theme.BAD};")
            self._invalid[edit] = str(e)
            self.window.show_error(str(e))
        self._update_save()

    # saving
    def save(self, dest=None):
        """SAVE: ask where (Guitar Lab's "Save Changes" dialog) unless `dest` is given."""
        if self.working is None or self.slot is None:
            return
        if self._saving is not None:
            return
        if not self.connected:
            self.window.show_error("not connected")
            self._pending_open = None
            self._select_slot(self.slot)
            return
        if self._invalid:
            self.window.show_error("; ".join(self._invalid.values()))
            self._pending_open = None
            self._select_slot(self.slot)
            return
        # Guitar Lab's SAVE asks where to save, starting at the current patch ("Save Changes").
        if dest is None:
            dest = self.ask_save_destination()
        if dest is None:
            self._pending_open = None
            self._select_slot(self.slot)
            return
        if not self.window.begin_save(self):
            self._pending_open = None
            self._select_slot(self.slot)
            return
        expected = self.loaded
        if dest != self.slot:
            slots = getattr(self.window, "slots", [])
            expected = bytes(slots[dest]) if dest < len(slots) else b""
        self._saving = dest
        self._sent = ptcf.encode(self.working)
        self._update_save()
        self.window.request_save_edit.emit(dest, self._sent, expected)

    def ask_save_destination(self):
        """The SAVE dialog; returns the destination slot or None. Replaced in tests."""
        from b6lab.gui.gldialog import ask_save_destination
        names = [self.model.data(self.model.index(i, 1)) or "" for i in range(self.model.rowCount())]
        current = self.working.name if self.working is not None else ""
        return ask_save_destination(self, self.slot, slot_label,
                                    lambda s: current if s == self.slot else names[s],
                                    max(1, self.model.rowCount()))

    def _on_saved(self, res):
        if self._saving is None:
            return
        saved_slot, self._saving = self._saving, None
        self.window.end_save(self)
        pending, self._pending_open = self._pending_open, None
        if res.ok and saved_slot == self.slot and self.working is not None:
            # The pedal now holds what was sent; edits made since stay "modified".
            self._base = self.loaded = self._sent
        self._update_save()
        if not res.ok:
            self._pending_action = None
            self.window.report_save_failed(res)
            self._select_slot(self.slot)
            self.window.editor_save_done(False)
            return
        self.window.report_saved(res)
        action, self._pending_action = self._pending_action, None
        if action is not None and saved_slot == self.slot:
            action()
        if pending is not None:
            self._start_open(pending)
        else:
            self.window.request_load_slot.emit(saved_slot)  # refresh from read-back
        self.window.editor_save_done(True)


class _Text(QWidget):
    """A JUCE Label: text in (225,248,254), left/top justified unless told otherwise."""

    def __init__(self, f, justification=LEFT | TOP, parent=None):
        super().__init__(parent)
        self.text = ""
        self.f = f
        self.justification = justification
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setPen(LABEL_TEXT)
        draw_fitted_text(p, self.text, QRectF(self.rect()), self.f, self.justification)
