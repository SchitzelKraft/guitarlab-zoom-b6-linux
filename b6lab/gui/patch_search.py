"""The patch search field and the filtering model shared by the EDITOR and PATCH pages.

The list views show a SearchProxy over the PatchListModel: with an empty field all 240 slots in
slot order, otherwise only the hits of b6lab.search in hit order. A view row is NOT a slot then:
use slot_of_row / row_of_slot (the proxy) for every row <-> slot conversion."""
from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QLineEdit

from b6lab import search as patch_search
from b6lab.gui.patch_list import HEADER_BG

PLACEHOLDER = "Search patches: number, name or effect"
HEIGHT = 40
TEXT = "#e6e8ec"          # typed text and the magnifier
HINT = "#aeb4bf"          # placeholder: readable on the header background
FOCUS = "#f6ab6d"         # the patch list's selection orange


def _magnifier(size=18, color=TEXT):
    """A small magnifier icon drawn in code (no image file needed)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), size * 0.12)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    r = size * 0.30
    c = QPointF(size * 0.42, size * 0.42)
    p.drawEllipse(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
    p.drawLine(QPointF(c.x() + r * 0.72, c.y() + r * 0.72), QPointF(size * 0.88, size * 0.88))
    p.end()
    return QIcon(pm)


class SearchProxy(QSortFilterProxyModel):
    refreshed = Signal()  # the filter / order was recomputed

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self._query = ""
        self._hits = {}   # slot -> Hit
        self._order = {}  # slot -> position among the hits
        self.setSourceModel(source)
        self.setDynamicSortFilter(True)
        self.sort(0)
        source.content_changed.connect(self._refresh)

    def query(self):
        return self._query

    def set_query(self, query):
        self._query = query
        self._refresh()

    def _refresh(self):
        old = self._hits, self._order
        self._hits, self._order = {}, {}
        if self._query.strip():
            hits = patch_search.search(self.sourceModel().slot_data(), self._query)
            self._hits = {h.slot: h for h in hits}
            self._order = {h.slot: i for i, h in enumerate(hits)}
        if (self._hits, self._order) != old:   # unchanged (e.g. no query): no relayout
            self.invalidate()
        self.refreshed.emit()

    def filtering(self):
        return bool(self._query.strip())

    def filterAcceptsRow(self, row, parent):
        return not self.filtering() or row in self._hits

    def lessThan(self, left, right):
        a, b = left.row(), right.row()
        if self.filtering():
            a, b = self._order.get(a, a + 1000), self._order.get(b, b + 1000)
        return a < b

    def hit(self, slot):
        return self._hits.get(slot)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if self.filtering() and index.isValid():
            hit = self._hits.get(self.slot_of_row(index.row()))
            if hit is not None and hit.reason:
                if index.column() == 2 and role == Qt.ItemDataRole.DisplayRole:
                    return hit.reason
                if role == Qt.ItemDataRole.ToolTipRole:
                    return hit.reason
        return super().data(index, role)

    # row <-> slot
    def slot_of_row(self, row):
        if not 0 <= row < self.rowCount():
            return -1
        return self.mapToSource(self.index(row, 0)).row()

    def row_of_slot(self, slot):
        """The view row of `slot`, or -1 when the filter hides it."""
        idx = self.mapFromSource(self.sourceModel().index(slot, 0))
        return idx.row() if idx.isValid() else -1

    def index_of_slot(self, slot):
        row = self.row_of_slot(slot)
        return self.index(row, 0) if row >= 0 else QModelIndex()

    def is_modified(self, slot):
        return self.sourceModel().is_modified(slot)


class SearchBox(QLineEdit):
    """Esc clears, Up/Down emit step(-1/+1); styled like the list's header cells."""
    step = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        from b6lab.gui.glui import font
        self.setPlaceholderText(PLACEHOLDER)
        self.setClearButtonEnabled(False)
        self.setFont(font(16))
        self.addAction(_magnifier(), QLineEdit.ActionPosition.LeadingPosition)
        self.setStyleSheet(
            f"QLineEdit {{ background: {HEADER_BG}; color: {TEXT}; border: 1px solid #5b6270;"
            f" border-radius: 4px; padding: 0 8px 0 6px;"
            f" selection-background-color: {FOCUS}; }}"
            f"QLineEdit:focus {{ border: 2px solid {FOCUS}; }}")
        pal = self.palette()
        pal.setColor(pal.ColorRole.PlaceholderText, QColor(HINT))
        self.setPalette(pal)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.step.emit(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.clear()
            event.accept()
            return
        super().keyPressEvent(event)


def attach(page, view, source):
    """Put a SearchProxy on `view` and a SearchBox on `page` (Ctrl+F focuses it).
    Returns (box, proxy); the page lays the box out above the view."""
    proxy = SearchProxy(source, page)
    view.setModel(proxy)
    box = SearchBox(page)
    box.textChanged.connect(proxy.set_query)
    sc = QShortcut(QKeySequence.StandardKey.Find, page)
    sc.setContext(Qt.ShortcutContext.WindowShortcut)  # only the visible page's is active
    sc.activated.connect(lambda: (box.setFocus(), box.selectAll()))
    box._shortcut = sc
    return box, proxy
