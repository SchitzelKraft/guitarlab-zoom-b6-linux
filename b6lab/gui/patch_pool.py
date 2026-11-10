"""Guitar Lab's Patch Pool panel (PatchPoolComponent / PatchPoolItem) on the PATCH page.

From the decompiled Mac binary (analysis/ui-trace/classes/PatchPoolComponent.c, PatchPoolItem.c):
- paint FUN_1000429e0: background, the "Patch Pool" table-header title in the top 30 px;
- resized FUN_100042af0: a JUCE TreeView at (8, 48, w - 8, h - 48);
- PatchPoolItem: rows 26 px (vf_6), the name in bold 18 (vf_9) at (4, 0, w - 4, h), left and
  vertically centred, in (169,169,169), or (20,20,20) for a patch of another device; the
  "modified" image 00324fc0 at half size after the name when flagged;
- groups ("PatchGroup") open and close like the Effect Pool's categories; drag sources are
  "PatchPoolItem" / "PatchPoolGroup", and the patch list's rows ("PatchListRows") can be
  dropped in (PatchPoolComponent itemDropped -> FUN_100045130).
The data is b6lab.pool.PatchPool.
"""
import json

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget

from b6lab.gui.glui import LEFT, VCENTRE, draw_fitted_text, font, rgb
from b6lab.gui.patch_list import HEADER_TEXT, TABLE_BG, paint_table_header_title

MIME_ROWS = "application/x-guitarlab-patchlistrows"   # "PatchListRows"
MIME_POOL = "application/x-guitarlab-patchpoolitem"   # "PatchPoolItem" / "PatchPoolGroup"
ROW = 26
TREE_TOP = 48
SELECTED = rgb(54, 66, 80)  # selection fill: not traced yet (the editor's selected-row colour)


def node_path(tree, node):
    """Index path of `node` under `tree` (for drag data)."""
    def walk(parent, path):
        for i, child in enumerate(parent.children):
            if child is node:
                return path + [i]
            found = walk(child, path + [i])
            if found:
                return found
        return None
    return walk(tree, [])


def node_at(tree, path):
    node = tree
    for i in path:
        node = node.children[i]
    return node


class PatchPoolView(QWidget):
    rows_dropped = Signal(list, object, int)   # patch-list slots, target group (or None), index
    selection_changed = Signal(object)          # the selected node (or None)
    menu_requested = Signal(object, QPoint)     # right click (PatchPoolItem vf_13): node, global pos
    properties_requested = Signal(object)       # double click (vf_14 -> FUN_100046fa0)

    def __init__(self, pool, parent=None):
        super().__init__(parent)
        self.pool = pool
        self.open = set()        # id() of open groups
        self.selected = None     # the selected node
        self.scroll = 0
        self._press = None
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

    # rows
    def rows(self):
        """Visible rows: (depth, node)."""
        out = []

        def walk(parent, depth):
            for child in parent.children:
                out.append((depth, child))
                if child.type == "PatchGroup" and id(child) in self.open:
                    walk(child, depth + 1)
        walk(self.pool.tree, 0)
        return out

    def _row_at(self, y):
        if y < TREE_TOP:
            return None
        i = int((y - TREE_TOP + self.scroll) // ROW)
        rows = self.rows()
        return i if 0 <= i < len(rows) else None

    def toggle(self, node):
        if node.type == "PatchGroup":
            self.open ^= {id(node)}
            self._clamp()
            self.update()

    def _clamp(self):
        extra = max(0, len(self.rows()) * ROW - (self.height() - TREE_TOP))
        self.scroll = max(0, min(self.scroll, extra))

    def refresh(self):
        self._clamp()
        self.update()

    # mouse
    def select(self, node):
        if node is not self.selected:
            self.selected = node
            self.selection_changed.emit(node)
        self.update()

    def mousePressEvent(self, event):
        i = self._row_at(event.position().y())
        if i is None:
            self.select(None)
            return
        depth, node = self.rows()[i]
        self.select(node)
        if event.button() == Qt.MouseButton.RightButton:
            self.menu_requested.emit(node, event.globalPosition().toPoint())
            return
        x = event.position().x() - 8 - depth * 20
        if node.type == "PatchGroup" and 0 <= x < 25:   # the open / close arrow
            self.toggle(node)
        self._press = event.position().toPoint()
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Double click opens Properties (PatchPoolItem vf_14); the arrow still opens / closes."""
        i = self._row_at(event.position().y())
        if i is None:
            return
        depth, node = self.rows()[i]
        if node.type == "PatchGroup" and 0 <= event.position().x() - 8 - depth * 20 < 25:
            return
        self.properties_requested.emit(node)

    def mouseMoveEvent(self, event):
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        if self.selected is None:
            return
        mime = QMimeData()
        mime.setData(MIME_POOL, QByteArray(json.dumps(node_path(self.pool.tree, self.selected)).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, _event):
        self._press = None

    def wheelEvent(self, event):
        self.scroll -= event.angleDelta().y() // 120 * ROW
        self._clamp()
        self.update()

    # drops from the patch list
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_ROWS):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_ROWS):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MIME_ROWS):
            return
        slots = json.loads(bytes(event.mimeData().data(MIME_ROWS)).decode())
        group, index = self.drop_target(event.position().y())
        event.acceptProposedAction()
        self.rows_dropped.emit(slots, group, index)

    def drop_target(self, y):
        """Where dropped patches go: onto a group (into it, at its end), onto a patch (before
        it, in its parent), or below the rows (the end of the root)."""
        i = self._row_at(y)
        if i is None:
            return None, -1
        _depth, node = self.rows()[i]
        if node.type == "PatchGroup":
            return node, -1
        path = node_path(self.pool.tree, node)
        parent = node_at(self.pool.tree, path[:-1])
        return (parent if parent is not self.pool.tree else None), path[-1]

    # paint
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(TABLE_BG))
        p.save()
        p.setClipRect(QRectF(8, TREE_TOP, w - 8, max(0, h - TREE_TOP)))
        f = font(18, True)
        y = TREE_TOP - self.scroll
        for depth, node in self.rows():
            if y + ROW >= TREE_TOP and y < h:
                x = 8 + depth * 20
                if node is self.selected:
                    p.fillRect(QRectF(8, y, w - 8, ROW), SELECTED)
                if node.type == "PatchGroup":
                    arrow = QPainterPath()
                    if id(node) in self.open:
                        arrow.moveTo(x + 10, y + 10)
                        arrow.lineTo(x + 18, y + 10)
                        arrow.lineTo(x + 14, y + 17)
                    else:
                        arrow.moveTo(x + 11, y + 9)
                        arrow.lineTo(x + 18, y + 13)
                        arrow.lineTo(x + 11, y + 17)
                    arrow.closeSubpath()
                    p.fillPath(arrow, QColor(HEADER_TEXT))
                p.setPen(QColor(HEADER_TEXT))
                draw_fitted_text(p, node.get("name", ""), QRectF(x + 25 + 4, y, w - x - 33, ROW), f,
                                 LEFT | VCENTRE)
            y += ROW
        p.restore()
        paint_table_header_title(p, "Patch Pool", w, 35)
