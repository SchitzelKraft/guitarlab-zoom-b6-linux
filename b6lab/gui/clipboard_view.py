"""Guitar Lab's Clipboard pane on the EDITOR page (ClipboardComponent, a TableListBox).

Traced from the decompiled Mac binary (analysis/ui-trace/CLIPBOARD.md, clip-component.c):
- constructor FUN_100267580: header 35 px ("Clipboard" only, FUN_10026c630), rows 67 px,
  columns Number 50, Name 124, Icons 233;
- row background FUN_100269fe0: each column filled (113,137,152) in (x, 0, w-1, h-1) over the
  list background (40,47,57); the selected row has a 2 px orange (246,171,109) outline in
  (0, 0, w-1, h-1); while reordering, the drop line is an orange fillRect(0, h-3, w, 2) on the
  row above the insertion point;
- cells FUN_10026a130: the number (row + 1, three digits) bold 20 black centred in
  (8, 0, w-16, 67); the name bold 20 black fitted centred-left in (12, 0, w-24, 67); the
  clip's processor share bold 13 at (12, 42, 80, 16) of the name column, "<n>%", in (51,64,75)
  or darkred (139,0,0) when it no longer fits into the open patch;
- icons FUN_100268980: per effect its chain icon at (6, (67-h)/2) with 6 x 6 cable stubs at
  both ends at y = 30 in (40,47,57); an empty entry is a 12 x 6 line; the row of icons is
  centred in the column;
- right click (FUN_10026a870): a menu with "Delete" only (no question, no undo); double click
  on the name (FUN_10026a9d0): an editor, 10 characters of a fixed set, which renames the clip
  inside its file (FUN_10026bf40); rows are dragged ("ClipboardItem") to reorder them
  (FUN_10026b100) or into the chain to add the clip to the patch.
"""
import json

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from b6lab import clipboard
from b6lab import effects as fx_catalog
from b6lab.gui.glui import CENTRED, LEFT, VCENTRE, draw_fitted_text, font, image, rgb
from b6lab.gui.patch_list import paint_table_header_title

MIME_CLIP = "application/x-guitarlab-clipboarditem"   # "ClipboardItem"
HEADER = 35
ROW = 67
COLUMNS = (50, 124, 233)
CELL = rgb(113, 137, 152)
BACKGROUND = rgb(40, 47, 57)
ORANGE = rgb(246, 171, 109)
LOAD_TEXT = rgb(51, 64, 75)
LOAD_OVER = rgb(139, 0, 0)
CABLE = rgb(40, 47, 57)
UNKNOWN = "0030d160.png"
MAX_LOAD = 220   # the device's processor capacity (the editor's "Processor" uses the same)
NAME_CHARS = " !#$%~&'()+,-0123456789;=@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{}."


def clip_load(clip):
    """FUN_1002b1e30: the clip's effects' loads (second halves not counted) in % of the
    device's capacity."""
    return sum(fx_catalog.dsp_load(e.fx_id) or 0 for e in clip.effects()
               if e.fx_id not in (0, 1)) / MAX_LOAD * 100


class _ClipMime(QMimeData):
    """The row drag: the "ClipboardItem" data for drops inside the window, and a file for the
    file manager. Guitar Lab makes the Clipboard/Temp copy when the drag leaves the window
    (FUN_1000672c0); here it is made when another program asks for the file."""

    def __init__(self, board, node):
        super().__init__()
        self._board, self._node, self._file = board, node, None

    def formats(self):
        return super().formats() + ["text/uri-list"]

    def hasFormat(self, mimetype):
        return mimetype == "text/uri-list" or super().hasFormat(mimetype)

    def retrieveData(self, mimetype, preferred):
        if mimetype == "text/uri-list":
            from PySide6.QtCore import QUrl
            if self._file is None:
                self._file = self._board.export_copy(self._node)
            return QByteArray((QUrl.fromLocalFile(str(self._file)).toString() + "\r\n").encode())
        return super().retrieveData(mimetype, preferred)


def _zpcd_file(mime):
    """isInterestedInFileDrag FUN_10026baf0: exactly one file, extension ".zpcd"."""
    urls = mime.urls() if mime.hasUrls() else []
    if len(urls) != 1 or not urls[0].isLocalFile():
        return None
    path = urls[0].toLocalFile()
    return path if path.lower().endswith(".zpcd") else None


class ClipboardView(QWidget):
    clip_menu = Signal(object, QPoint)   # node, global position
    renamed = Signal(object, str)        # node, new name
    reordered = Signal(object, int)      # node, final index

    def __init__(self, board, parent=None):
        super().__init__(parent)
        self.board = board
        self.selected = None     # the selected node
        self.scroll = 0
        self.patch_load = 0.0    # the open patch's share (0..1), for the red percentage
        self._press = None
        self._drop_row = None
        self._file_over = False  # + 0x1a1: an OS file drag over the pane (orange frame)
        self._clips = {}         # filename -> Clip (cached)
        self._icons = {}         # filename -> QImage
        self.setAcceptDrops(True)
        self.editor = QLineEdit(self)
        self.editor.hide()
        self.editor.setFrame(False)
        self.editor.setMaxLength(10)
        self.editor.setFont(font(20, True))
        self.editor.setValidator(QRegularExpressionValidator(
            QRegularExpression("[" + QRegularExpression.escape(NAME_CHARS) + "]*"), self.editor))
        self.editor.setStyleSheet("QLineEdit { background: rgb(113,137,152); color: black; border: 0;"
                                  " padding: 10px 12px 10px 12px; }")
        self.editor.editingFinished.connect(self._finish_rename)
        self._editing = None

    # data
    def refresh(self):
        self._clips.clear()
        self._icons.clear()
        if self.selected not in self.board.items:
            self.selected = None
        self._clamp()
        self.update()

    def clip(self, node):
        name = node.get("filename", "")
        if name not in self._clips:
            try:
                self._clips[name] = self.board.clip(node)
            except (OSError, ValueError):
                self._clips[name] = None
        return self._clips[name]

    def set_patch_load(self, load):
        self.patch_load = load
        self.update()

    def select_last(self):
        items = self.board.items
        self.selected = items[-1] if items else None
        self._clamp()
        self.scroll = max(0, len(items) * ROW - (self.height() - HEADER))
        self.update()

    # geometry
    def _row_at(self, y):
        if y < HEADER:
            return None
        i = int((y - HEADER + self.scroll) // ROW)
        return i if 0 <= i < len(self.board.items) else None

    def _clamp(self):
        extra = max(0, len(self.board.items) * ROW - (self.height() - HEADER))
        self.scroll = max(0, min(self.scroll, extra))

    def _row_rect(self, i):
        return QRectF(0, HEADER + i * ROW - self.scroll, sum(COLUMNS), ROW)

    # mouse
    def mousePressEvent(self, event):
        i = self._row_at(event.position().y())
        self.selected = self.board.items[i] if i is not None else None
        self.update()
        if i is None:
            return
        if event.button() == Qt.MouseButton.RightButton or (
                event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.clip_menu.emit(self.selected, event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseDoubleClickEvent(self, event):
        i = self._row_at(event.position().y())
        x = event.position().x()
        if i is None or not COLUMNS[0] <= x < COLUMNS[0] + COLUMNS[1]:
            return
        self.start_rename(self.board.items[i])

    def mouseMoveEvent(self, event):
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        if self.selected is None:
            return
        mime = _ClipMime(self.board, self.selected)
        mime.setData(MIME_CLIP, QByteArray(json.dumps(self.board.items.index(self.selected)).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, _event):
        self._press = None

    def wheelEvent(self, event):
        self.scroll -= event.angleDelta().y() // 120 * ROW
        self._clamp()
        self.update()

    def resizeEvent(self, _event):
        self._clamp()

    # rename
    def start_rename(self, node):
        i = self.board.items.index(node)
        clip = self.clip(node)
        r = self._row_rect(i)
        self._editing = node
        self.editor.setGeometry(int(COLUMNS[0]), int(r.y()), COLUMNS[1] - 1, ROW - 1)
        self.editor.setText(clip.name if clip else "")
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _finish_rename(self):
        node, self._editing = self._editing, None
        self.editor.hide()
        if node is None:
            return
        clip = self.clip(node)
        text = self.editor.text()
        if clip is not None and text != clip.name:
            self.renamed.emit(node, text)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._editing is not None:
            self._editing = None
            self.editor.hide()
            return
        super().keyPressEvent(event)

    # reordering (drops of the pane's own rows)
    def _insert_index(self, y):
        n = len(self.board.items)
        return max(0, min(n, int(round((y - HEADER + self.scroll) / ROW))))

    def dragEnterEvent(self, event):
        if event.source() is None and _zpcd_file(event.mimeData()):
            self._file_over = True
            event.acceptProposedAction()
            self.update()
        elif event.mimeData().hasFormat(MIME_CLIP) and event.source() is self:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if self._file_over:
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(MIME_CLIP) and event.source() is self:
            event.acceptProposedAction()
            self._drop_row = self._insert_index(event.position().y())
            self.update()

    def dragLeaveEvent(self, _event):
        self._drop_row = None
        self._file_over = False
        self.update()

    def dropEvent(self, event):
        self._drop_row = None
        if self._file_over:
            # filesDropped FUN_10026bba0: copy in, append, select it, then deselectAllRows
            self._file_over = False
            path = _zpcd_file(event.mimeData())
            event.acceptProposedAction()
            if path and self.board.import_file(path) is not None:
                self.refresh()
            self.selected = None
            self.update()
            return
        self.update()
        if not event.mimeData().hasFormat(MIME_CLIP) or event.source() is not self:
            return
        src = json.loads(bytes(event.mimeData().data(MIME_CLIP)).decode())
        to = self._insert_index(event.position().y())
        event.acceptProposedAction()
        dst = to - (1 if src < to else 0)   # moveChild(from, to - (from < to))
        if dst != src:
            self.reordered.emit(self.board.items[src], dst)

    # paint
    def _icon_image(self, node, clip):
        from PySide6.QtGui import QImage
        from b6lab.gui.editor import chain_icon
        key = node.get("filename", "")
        if key in self._icons:
            return self._icons[key]
        w, h = COLUMNS[2], ROW
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        if clip is not None:
            effects = clip.effects()
            pieces = []
            for k, e in enumerate(effects):
                if e.is_tail:
                    continue
                wide = k + 1 < len(effects) and effects[k + 1].is_tail
                if e.fx_id == 0:
                    pieces.append(("line", None, 12))
                    continue
                icon = chain_icon(e.fx_id, wide)
                if icon is None:
                    pieces.append(("unknown", None, 46))
                else:
                    pieces.append(("icon", icon, icon.width() + 12))
            x = (w - sum(p[2] for p in pieces)) / 2
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            for kind, icon, pw in pieces:
                if kind == "line":
                    p.fillRect(QRectF(x, 30, pw, 6), CABLE)
                elif kind == "unknown":
                    warn = image(UNKNOWN)
                    iw, ih = warn.width() / 2, warn.height() / 2
                    p.fillRect(QRectF(x, 30, 12, 6), CABLE)
                    p.drawImage(QRectF(x + (pw - iw) / 2, (h - ih) / 2, iw, ih), warn)
                    p.fillRect(QRectF(x + pw - 12, 30, 12, 6), CABLE)
                else:
                    p.drawImage(QRectF(x + 6, (h - icon.height()) / 2, icon.width(), icon.height()), icon)
                    p.fillRect(QRectF(x, 30, 6, 6), CABLE)
                    p.fillRect(QRectF(x + pw - 6, 30, 6, 6), CABLE)
                x += pw
            p.end()
        self._icons[key] = img
        return img

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), BACKGROUND)
        p.save()
        p.setClipRect(QRectF(0, HEADER, w, max(0, h - HEADER)))
        for i, node in enumerate(self.board.items):
            r = self._row_rect(i)
            if r.bottom() < HEADER or r.top() > h:
                continue
            p.save()
            p.translate(0, r.top())
            clip = self.clip(node)
            x = 0
            for cw in COLUMNS:
                p.fillRect(QRectF(x, 0, cw - 1, ROW - 1), CELL)
                x += cw
            # FUN_10026a130: an unusable clip (clipboard.usable) has its number, name and icons
            # at 30 %; the percentage, the cells and the frame stay as they are
            dim = clip is not None and not clipboard.usable(clip)
            p.setPen(QColor(0, 0, 0, 77) if dim else QColor(0, 0, 0))
            draw_fitted_text(p, f"{i + 1:03d}", QRectF(8, 0, COLUMNS[0] - 16, ROW), font(20, True), CENTRED)
            name_x = COLUMNS[0]
            draw_fitted_text(p, clip.name if clip else "", QRectF(name_x + 12, 0, COLUMNS[1] - 24, ROW),
                             font(20, True), LEFT | VCENTRE)
            if clip is not None:
                load = clip_load(clip)
                p.setPen(LOAD_OVER if self.patch_load * 100 + load > 100 else LOAD_TEXT)
                draw_fitted_text(p, f"{round(load)}%", QRectF(name_x + 12, 42, 80, 16), font(13, True),
                                 LEFT | VCENTRE)
            p.setOpacity(0.3 if dim else 1.0)
            p.drawImage(COLUMNS[0] + COLUMNS[1], 0, self._icon_image(node, clip))
            p.setOpacity(1.0)
            if node is self.selected:
                pen = p.pen()
                pen.setColor(ORANGE)
                pen.setWidthF(2)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(1, 1, sum(COLUMNS) - 2, ROW - 2))
            if self._drop_row is not None and self._drop_row == i + 1:
                p.fillRect(QRectF(0, ROW - 3, sum(COLUMNS), 2), ORANGE)
            p.restore()
        p.restore()
        if self._file_over:
            # FUN_100269f90: a 2 px orange frame around the list while a file is over it
            pen = p.pen()
            pen.setColor(ORANGE)
            pen.setWidthF(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(1, HEADER + 1, w - 2, max(0, h - HEADER - 2)))
        paint_table_header_title(p, "Clipboard", w, HEADER)
