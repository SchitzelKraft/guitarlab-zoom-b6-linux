"""Table model for the 240 patch slots."""
from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QObject, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate

from b6lab import ptcf

COLUMNS = ["Patch Number", "Patch Name", "Comment"]


def slot_label(slot):
    """Guitar Lab's patch number: A-001 .. Z-104, then AA-105 .. AD-120 (seen in Guitar Lab)."""
    bank = slot // 4
    letters = chr(65 + bank) if bank < 26 else "A" + chr(65 + bank - 26)
    return f"{letters}-{slot + 1:03d}"


# PatchListComponent (decompiled Mac binary, paintRowBackground FUN_100118e60, paintCell
# FUN_100119160, cell components FUN_100119d10, colours set up in FUN_10011dd30):
# row colour = table[(row / 4) % 10], one table for even rows and one for odd rows;
# cells filled inset by 4 px; odd rows darken the comment cell; selection = 2 px frame.
EVEN = ["#708ec2", "#8c7ec2", "#a676c2", "#ce6a9c", "#fd8e69", "#fdba69", "#d0e973", "#79c173",
        "#69b2b3", "#68a5b3"]
ODD = ["#63789b", "#7b719f", "#8a699d", "#a56183", "#d2876e", "#d2a56e", "#b1c172", "#6a9b66",
       "#59898b", "#58818b"]
TABLE_BG = "#282f39"
ODD_COMMENT = "#21262d"
SELECTION = "#f6ab6d"
NAME_TEXT, COMMENT_TEXT = "#ffffff", "#999999"
HEADER_BG, HEADER_TEXT = "#36424f", "#a9a9a9"  # LookAndFeel FUN_100017b70 / FUN_100017cb0
ROW_HEIGHT, HEADER_HEIGHT = 56, 35
MODIFIED_IMAGE = "00324fc0.png"  # drawn at (144, 20), half size


class PatchRowDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        from PySide6.QtCore import QRectF
        from b6lab.gui.glui import CENTRED, LEFT, VCENTRE, draw_fitted_text, font, image
        p = painter
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.setRenderHint(p.RenderHint.TextAntialiasing)
        r = option.rect
        row, col = index.row(), index.column()
        group = (row // 4) % 10
        colour = QColor((ODD if row % 2 else EVEN)[group])
        p.fillRect(r, QColor(TABLE_BG))
        model = index.model()
        if col < 2:
            p.fillRect(r.x(), r.y(), r.width() - 4, r.height() - 4, colour)
        elif row % 2:
            p.fillRect(r.x(), r.y(), r.width() - 4, r.height(), QColor(ODD_COMMENT))
        text = model.data(index, Qt.ItemDataRole.DisplayRole) or ""
        if col == 0:
            p.setPen(QColor(NAME_TEXT))
            draw_fitted_text(p, text, QRectF(r.x() + 8, r.y(), r.width() - 16, r.height()), font(27, True), CENTRED)
        elif col == 1:
            p.setPen(QColor(NAME_TEXT))
            draw_fitted_text(p, text, QRectF(r.x() + 32, r.y(), r.width() - 32 - 10, r.height() - 4),
                             font(27, True), LEFT | VCENTRE)
            if model.is_modified(row):
                img = image(MODIFIED_IMAGE)
                p.drawImage(QRectF(r.x() - 128 + 144, r.y() + 20, img.width() / 2, img.height() / 2), img)
        else:
            p.setPen(QColor(COMMENT_TEXT))
            draw_fitted_text(p, text, QRectF(r.x() + 16, r.y(), r.width() - 16 - 10, r.height() - 4),
                             font(15), LEFT | VCENTRE)
        p.restore()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            pen = QPen(QColor(SELECTION), 2)
            painter.setPen(pen)
            x0 = r.x() + 1 if col == 0 else r.x() - 1
            x1 = r.right() if col == 2 else r.right() + 1
            y0, y1 = r.y() + 1, r.y() + r.height() - 4 - 1
            painter.drawLine(x0, y0, x1, y0)
            painter.drawLine(x0, y1, x1, y1)
            if col == 0:
                painter.drawLine(r.x() + 1, y0, r.x() + 1, y1)
            if col == 2:
                painter.drawLine(r.right() - 1, y0, r.right() - 1, y1)
            painter.restore()


class PatchHeader(QHeaderView):
    """Column headers: (54,66,80) cells 30 px high, 4 px gaps, bold 16 text in (168,170,173)."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setSectionsClickable(False)
        self.setHighlightSections(False)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor(TABLE_BG))
        p.end()
        super().paintEvent(event)

    def paintSection(self, painter, rect, logical):
        from PySide6.QtCore import QRectF
        from b6lab.gui.glui import CENTRED, draw_fitted_text, font
        painter.save()
        painter.setRenderHint(painter.RenderHint.TextAntialiasing)
        painter.fillRect(rect, QColor(TABLE_BG))
        painter.fillRect(rect.x(), rect.y(), rect.width() - 4, 30, QColor(HEADER_BG))
        painter.setPen(QColor(HEADER_TEXT))
        text = self.model().headerData(logical, Qt.Orientation.Horizontal) if self.model() else ""
        draw_fitted_text(painter, text or "", QRectF(rect.x() + 4, rect.y(), rect.width() - 8, 30),
                         font(16, True), CENTRED)
        painter.restore()


class _StretchComment(QObject):
    """Keeps the comment column at the table width minus the two fixed columns."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            obj.setColumnWidth(2, max(200, obj.width() - 128 - 192))
        return False


def configure_patch_table(table, stretch_comment=True):
    """PatchListComponent: rows 56, header 35, columns 128 | 192 | comment (stretches)."""
    table.setHorizontalHeader(PatchHeader(table))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setMinimumSectionSize(1)
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.horizontalHeader().setMinimumSectionSize(1)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
    table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
    table.setColumnWidth(0, 128)
    table.setColumnWidth(1, 192)
    table.setShowGrid(False)
    table.setFrameShape(QAbstractItemView.Shape.NoFrame)
    # JUCE stretches the columns to the list's full width, while the rows are 18 px narrower
    # (vertical scrollbar), so a horizontal scrollbar shows too (seen in Guitar Lab).
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    if stretch_comment:
        table.installEventFilter(_StretchComment(table))
    table.setItemDelegate(PatchRowDelegate(table))
    table.setStyleSheet(f"""
        QTableView {{ background: {TABLE_BG}; border: 0; }}
        QScrollBar:vertical {{ background: {TABLE_BG}; width: 18px; margin: 0; border: 0; }}
        QScrollBar:horizontal {{ background: {TABLE_BG}; height: 18px; margin: 0; border: 0; }}
        QScrollBar::handle {{ background: #222831; border: 1px solid #363b43; border-radius: 5px;
                              margin: 4px; min-height: 20px; min-width: 20px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QAbstractScrollArea::corner {{ background: {TABLE_BG}; }}
    """)


def _name_comment(data):
    try:
        p = ptcf.parse(data)
        return p.name, p.comment
    except Exception:
        return "?", ""


class PatchListModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []  # (name, comment)
        self._modified = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        slot, col = index.row(), index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return slot_label(slot)
            if col == 1:
                return self._rows[slot][0]
            return self._rows[slot][1]
        return None

    def set_all(self, slots):
        self.beginResetModel()
        self._rows = [_name_comment(d) for d in slots]
        self._modified.clear()
        self.endResetModel()

    def set_slot(self, slot, data):
        if 0 <= slot < len(self._rows):
            self._rows[slot] = _name_comment(data)
            self.dataChanged.emit(self.index(slot, 0), self.index(slot, len(COLUMNS) - 1))

    def set_modified(self, slot, modified):
        if modified == (slot in self._modified):
            return
        (self._modified.add if modified else self._modified.discard)(slot)
        if 0 <= slot < len(self._rows):
            self.dataChanged.emit(self.index(slot, 0), self.index(slot, len(COLUMNS) - 1))

    def is_modified(self, slot):
        return slot in self._modified

    # drag source ("PatchListRows" in Guitar Lab)
    MIME_ROWS = "application/x-guitarlab-patchlistrows"

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else f

    def mimeTypes(self):
        return [self.MIME_ROWS]

    def mimeData(self, indexes):
        import json
        from PySide6.QtCore import QByteArray, QMimeData
        rows = sorted({i.row() for i in indexes if i.isValid()})
        mime = QMimeData()
        mime.setData(self.MIME_ROWS, QByteArray(json.dumps(rows).encode()))
        return mime

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction


def paint_table_header_title(p, text, width, height):
    """ClipboardHeaderComponent::paint: header background, then the column title drawing."""
    from PySide6.QtCore import QRectF
    from b6lab.gui.glui import CENTRED, draw_fitted_text, font
    p.fillRect(0, 0, width, height, QColor(HEADER_BG))
    bottom = min(5, height)
    p.fillRect(0, height - bottom, width, bottom, QColor(TABLE_BG))
    p.setPen(QColor(HEADER_TEXT))
    draw_fitted_text(p, text, QRectF(4, 0, width - 8, height - bottom), font(16, True), CENTRED)
