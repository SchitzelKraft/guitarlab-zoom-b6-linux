"""IMPORT IR page, laid out and drawn like Guitar Lab's IRPageComponent.

From the decompiled Mac binary (analysis/ui-trace/classes):
- IRPageComponent::resized (FUN_1001b77c0): list | 4 px bar | IR Pool (256..360 px, shared
  like the PATCH page) above a 40 px strip;
- IRListComponent: rows 56, header 35, columns IR Number 128, IR Category 192, IR Name
  (400, 200..4000, stretched to the list width); paintRowBackground (FUN_1001376f0): all three
  cells in (66,92,113) for factory IRs, (96,128,154) for user IRs, inset 4 px; selection frame
  (246,171,109); paintCell (FUN_100137a00): number "%03d" bold 27 white centred in
  (8, 0, w-16), category "FACTORY" / "USER" bold 27 white at x=16, name bold 27 white 32 px
  in, "<EMPTY>" when an IR slot has no name.
The IR names are the pedal's own (64 1A, kept in the effect catalog).
"""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QTableView, QWidget

from b6lab import effects
from b6lab.gui.glui import CENTRED, LEFT, VCENTRE, Painted, draw_fitted_text, font, rgb, stretch_layout
from b6lab.gui.patch_list import SELECTION, TABLE_BG, configure_patch_table, paint_table_header_title

FACTORY_ROW, USER_ROW = rgb(66, 92, 113), rgb(96, 128, 154)
IR_SLOTS = 120  # 64 1B reply byte 6 on the B6


def ir_names():
    """The pedal's IR names in slot order (from the effect catalog's IR entries)."""
    cat = effects.catalog()
    names = {}
    for fx_id, info in cat.items():
        if fx_id >> 24 == effects.IR_CATEGORIES[0]:
            names[(fx_id & 0xFFFFFF) - effects.IR_BASE] = info.name
    return [names[i] for i in sorted(names)]


class IRModel(QAbstractTableModel):
    HEADERS = ("IR Number", "IR Category", "IR Name")

    def __init__(self, parent=None):
        super().__init__(parent)
        # The B6's IR list (64 1B) has 120 slots, of which the first 36 hold the factory IRs;
        # the rest are user slots, empty until an IR is imported.
        factory = ir_names()
        self.factory = len(factory)
        self.names = factory + [""] * max(0, IR_SLOTS - len(factory))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.names)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row, col = index.row(), index.column()
        if col == 0:
            return f"{row + 1:03d}"
        if col == 1:
            return "FACTORY" if row < self.factory else "USER"
        return self.names[row] or "<EMPTY>"


class IRRowDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        r = option.rect
        row, col = index.row(), index.column()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(r, QColor(TABLE_BG))
        p.fillRect(r.x(), r.y(), r.width() - 4, r.height() - 4,
                   FACTORY_ROW if row < index.model().factory else USER_ROW)
        p.setPen(rgb(255, 255, 255))
        text = index.model().data(index) or ""
        f = font(27, True)
        if col == 0:
            draw_fitted_text(p, text, QRectF(r.x() + 8, r.y(), r.width() - 16, r.height()), f, CENTRED)
        elif col == 1:
            draw_fitted_text(p, text, QRectF(r.x() + 16, r.y(), r.width() - 32, r.height()), f, LEFT | VCENTRE)
        else:
            draw_fitted_text(p, text, QRectF(r.x() + 32, r.y(), r.width() - 42, r.height() - 4), f,
                             LEFT | VCENTRE)
        p.restore()
        if option.state & QStyle.StateFlag.State_Selected:
            p.save()
            p.setPen(QPen(QColor(SELECTION), 2))
            y0, y1 = r.y() + 1, r.y() + r.height() - 4 - 1
            x0 = r.x() + 1 if col == 0 else r.x() - 1
            x1 = r.right() - 1 if col == 2 else r.right() + 1
            p.drawLine(x0, y0, x1, y0)
            p.drawLine(x0, y1, x1, y1)
            if col == 0:
                p.drawLine(r.x() + 1, y0, r.x() + 1, y1)
            if col == 2:
                p.drawLine(r.right() - 1, y0, r.right() - 1, y1)
            p.restore()


class IRView(QWidget):
    def __init__(self, window=None):
        super().__init__()
        self.model = IRModel(self)
        self.list = QTableView(self)
        self.list.setModel(self.model)
        configure_patch_table(self.list)
        self.list.setItemDelegate(IRRowDelegate(self.list))
        self.bar = QWidget(self)
        self.bar.setStyleSheet("background: #1a1e24;")
        self.pool = Painted(lambda p, w: (p.fillRect(w.rect(), QColor(TABLE_BG)),
                                          paint_table_header_title(p, "IR Pool", w.width(), 35)), self)
        self.strip = Painted(lambda p, w: p.fillRect(w.rect(), rgb(26, 30, 36)), self)
        # IMPORT IR: a .wav dropped on a USER slot (recorded from Guitar Lab, b6lab/ffs.import_ir)
        self.window = window
        self.list.viewport().setAcceptDrops(True)
        self.list.viewport().installEventFilter(self)
        if window is not None:
            window.worker.ir_imported.connect(self._on_imported)
            window.worker.error.connect(self._close_progress)
            window.worker.disconnected.connect(self._close_progress)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.list.viewport() and event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                                                            QEvent.Type.Drop):
            urls = [u for u in event.mimeData().urls() if u.toLocalFile().lower().endswith(".wav")]
            row = self.list.rowAt(int(event.position().y()))
            if not urls or row < self.model.factory:
                return False
            event.acceptProposedAction()
            if event.type() == QEvent.Type.Drop:
                self.import_wav(row, urls[0].toLocalFile())
            return True
        return super().eventFilter(obj, event)

    def import_wav(self, slot, path):
        """The WAV goes to the pedal unchanged; the pedal makes the IR. The name is the file's
        name, cut to 9 characters as Guitar Lab sent it ("B6Lab-test-IR" -> "B6Lab-tes")."""
        from pathlib import Path
        if self.window is None or slot < self.model.factory:
            return False
        p = Path(path)
        from b6lab.gui.gldialog import show_progress
        if getattr(self, "progress", None) is None:
            self.progress = show_progress(self, "Importing IRs...")   # Guitar Lab's text
        self.window.request_import_ir.emit(slot, p.stem, p.read_bytes())
        return True

    def _close_progress(self, *_args):
        if getattr(self, "progress", None) is not None:
            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

    def _on_imported(self, slot, name):
        self._close_progress()
        if 0 <= slot < len(self.model.names):
            self.model.names[slot] = name
            self.model.dataChanged.emit(self.model.index(slot, 0), self.model.index(slot, 2))

    def resizeEvent(self, _event):
        w, h = self.width(), self.height()
        lw, bw, pw = stretch_layout(w, [(-0.5, -0.9, -0.75), (4, 4, 4), (256, 360, 256)])
        lh = max(0, h - 40)
        self.list.setGeometry(0, 0, lw, lh)
        self.bar.setGeometry(lw, 0, bw, lh)
        self.pool.setGeometry(lw + bw, 0, pw, lh)
        self.strip.setGeometry(0, lh, w, 40)

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), rgb(26, 30, 36))

