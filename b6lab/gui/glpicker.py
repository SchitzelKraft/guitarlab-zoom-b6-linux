"""Guitar Lab's effect TYPE picker ("Effect Type List"), EffectPickerComponent.

From the decompiled Mac binary (analysis/ui-trace/classes/EffectPickerComponent.c, picker*.c):
- opened by EditorPageComponent FUN_1000656a0 as a modal DialogWindow titled "Effect Type List"
  with its close button, background (41,47,57), content 409 x 233 (setSize 0x199, 0xe9), Escape closes it;
- resized (FUN_100108bc0): category list at (10, 10, 180, 223), effect list at (200, 10, 208, 223),
  both JUCE ListBoxes with 20 px rows;
- paint (FUN_100108b30): fill (41,47,57), a line in (45,66,80) from (190, 8) to (190, h - 16);
- category rows (FUN_100109b30): selected row filled (54,66,80); name bold 14 in (212,236,243) at
  (6, 3, 120, 14), left + vertically centred;
- effect rows (FUN_100108f20): selected row filled (54,66,80); load "NN%" regular 14 at
  (120, 3, 50, 14) right-aligned, in (212,236,243), or (106,118,121) when the effect is not
  allowed; name at (6, 3, 120, 14) in white, or (85,85,85) when not allowed;
- model (FUN_1001093f0): first a category "BYPASS", then one per category of the device's effect
  list in its order, effects sorted by name; load = round(load / 220 x 100) %;
- selecting a category (FUN_100109ce0) shows its effects and clears the effect selection
  (FUN_100108c20); selecting an allowed effect (FUN_100109210) changes the effect type at once
  (FUN_1002aa550); the picker stays open; Left / Right move between the lists (FUN_100108d50),
  Right also selects the first effect;
- a 500 ms timer (FUN_100108de0) closes the picker when its effect entry is gone or became the
  second half of a double-width effect.
"""
from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QWidget

from b6lab import effects
from b6lab.gui.glui import LEFT, RIGHT, VCENTRE, draw_fitted_text, font, rgb

BACKGROUND = rgb(41, 47, 57)
LINE = rgb(45, 66, 80)
SELECTED = rgb(54, 66, 80)
TEXT = rgb(212, 236, 243)
LOAD_OFF = rgb(106, 118, 121)
NAME_ON, NAME_OFF = rgb(255, 255, 255), rgb(85, 85, 85)  # juce::Colours::white, 0xff555555
ROW = 20
SIZE = (409, 233)
PREAMP, PEDAL = 0x04, 0x0B


def allowed(fx_ids, slot, fx_id):
    """FUN_1002b0780: may the effect at entry `slot` become `fx_id`?

    Same category: always. Otherwise one PREAMP and one PEDAL effect per patch (the binary
    checks per-patch fields set by its patch parser; this is the B6 reading of them).
    IR effects are not in the B6 picker."""
    if not 0 <= slot < len(fx_ids) or fx_ids[slot] == 1:
        return False
    new = fx_id >> 24
    if new == fx_ids[slot] >> 24:
        return True
    if new in (PREAMP, PEDAL):
        return not any(i != slot and f not in (0, 1) and f >> 24 == new for i, f in enumerate(fx_ids))
    return True


def picker_categories(catalog=None):
    """[(name, [(name, fx_id, load_text)])] in Guitar Lab's order: BYPASS, then the categories
    as the effect list has them, effects in effect-ID order (seen in Guitar Lab on the B6)."""
    catalog = effects.catalog() if catalog is None else catalog
    groups = {0: ("BYPASS", [("BYPASS", 0, "0%")])}
    for info in sorted(catalog.values(), key=lambda i: i.fx_id):
        cat = info.fx_id >> 24
        if cat in effects.IR_CATEGORIES:
            continue
        load = effects.dsp_load(info.fx_id) or 0
        groups.setdefault(cat, (info.group, []))[1].append(
            (info.name, info.fx_id, f"{int(load / 220 * 100 + 0.5)}%"))
    return [(name, items) for _cat, (name, items) in sorted(groups.items())]


class _Model(QAbstractListModel):
    def __init__(self, rows=(), parent=None):
        super().__init__(parent)
        self.rows = list(rows)

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            return self.rows[index.row()]
        return None


class _CategoryDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(r, SELECTED)
        p.setPen(TEXT)
        draw_fitted_text(p, index.data()[0], QRectF(r.x() + 6, r.y() + 3, 120, 14), font(14, True),
                         LEFT | VCENTRE)
        p.restore()

    def sizeHint(self, option, index):
        return QSize(10, ROW)


class _EffectDelegate(_CategoryDelegate):
    def __init__(self, picker):
        super().__init__(picker)
        self.picker = picker

    def paint(self, p, option, index):
        r = option.rect
        name, fx_id, load = index.data()
        on = self.picker.is_allowed(fx_id)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(r, SELECTED)
        f = font(14)
        p.setPen(TEXT if on else LOAD_OFF)
        draw_fitted_text(p, load, QRectF(r.x() + 120, r.y() + 3, 50, 14), f, RIGHT | VCENTRE)
        p.setPen(NAME_ON if on else NAME_OFF)
        draw_fitted_text(p, name, QRectF(r.x() + 6, r.y() + 3, 120, 14), f, LEFT | VCENTRE)
        p.restore()


def _list(parent, delegate):
    view = QListView(parent)
    view.setItemDelegate(delegate)
    view.setUniformItemSizes(True)
    view.setFrameShape(QListView.Shape.NoFrame)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setStyleSheet("""
        QListView { background: transparent; border: 0; outline: 0; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 0; border: 0; }
        QScrollBar::handle:vertical { background: #222831; border: 1px solid #363b43;
            border-radius: 3px; min-height: 20px; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: none; }
    """)
    return view


class EffectPickerContent(QWidget):
    """The picker's content. `chosen(fx_id)` is emitted for each allowed effect selected."""

    chosen = Signal(int)
    gone = Signal()  # the effect entry no longer exists: the dialog closes

    def __init__(self, fx_ids, slot, parent=None, catalog=None):
        super().__init__(parent)
        self.resize(*SIZE)
        self.fx_ids = list(fx_ids)
        self.slot = slot
        self.groups = picker_categories(catalog)
        self.categories = _list(self, _CategoryDelegate(self))
        self.categories.setGeometry(10, 10, 180, 223)
        self.category_model = _Model(self.groups, self)
        self.categories.setModel(self.category_model)
        self.effects = _list(self, _EffectDelegate(self))
        self.effects.setGeometry(200, 10, 208, 223)
        self.effect_model = _Model((), self)
        self.effects.setModel(self.effect_model)
        for view in (self.categories, self.effects):
            view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            view.installEventFilter(self)
        # FUN_100108760: preselect the current effect's category and row (no change sent)
        current = self.fx_ids[slot] if 0 <= slot < len(self.fx_ids) else 0
        cat_row, fx_row = 0, None
        for ci, (_name, items) in enumerate(self.groups):
            for ri, (_n, fx_id, _l) in enumerate(items):
                if fx_id == current:
                    cat_row, fx_row = ci, ri
                    break
            if fx_row is not None:
                break
        self._select(self.categories, cat_row)
        self._show_category(cat_row)
        if fx_row is not None:
            self._select(self.effects, fx_row)
        self.categories.selectionModel().currentRowChanged.connect(self._category_changed)
        self.effects.selectionModel().currentRowChanged.connect(self._effect_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._check_slot)
        self.timer.start()

    @staticmethod
    def _select(view, row):
        index = view.model().index(row, 0)
        view.selectionModel().setCurrentIndex(index, view.selectionModel().SelectionFlag.ClearAndSelect)
        view.scrollTo(index)

    def is_allowed(self, fx_id):
        return allowed(self.fx_ids, self.slot, fx_id)

    def set_fx_ids(self, fx_ids):
        """The patch changed (after a type change): re-evaluate which effects are allowed."""
        self.fx_ids = list(fx_ids)
        self.effects.viewport().update()

    def _show_category(self, row):
        self.effect_model.set_rows(self.groups[row][1] if 0 <= row < len(self.groups) else ())

    def _category_changed(self, current, _previous):
        self._show_category(current.row())
        self.effects.selectionModel().clearSelection()

    def _effect_changed(self, current, _previous):
        if not current.isValid():
            return
        _name, fx_id, _load = current.data()
        if self.is_allowed(fx_id):
            self.chosen.emit(fx_id)

    def _check_slot(self):
        if not 0 <= self.slot < len(self.fx_ids) or self.fx_ids[self.slot] == 1:
            self.timer.stop()
            self.gone.emit()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.key(event.key())
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.key(event.key())
        else:
            super().keyPressEvent(event)

    def key(self, key):
        """FUN_100108d50: Left focuses the categories; Right focuses the effects and selects
        the first one."""
        if key == Qt.Key.Key_Left:
            self.categories.setFocus()
        elif not self.effects.hasFocus():
            self.effects.setFocus()
            if self.effect_model.rowCount():
                self._select(self.effects, 0)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), BACKGROUND)
        p.setPen(LINE)
        p.drawLine(190, 8, 190, self.height() - 16)


def open_picker(parent, fx_ids, slot, on_chosen):
    """Show the picker modally; `on_chosen(fx_id)` runs for every effect picked.
    Returns the content so the caller can update it while it is open."""
    from b6lab.gui.gldialog import GLDialog
    content = EffectPickerContent(fx_ids, slot)
    dialog = GLDialog("Effect Type List", content, parent, background=BACKGROUND, close_button=True)
    content.chosen.connect(on_chosen)
    content.gone.connect(dialog.reject)
    parent_picker = getattr(parent, "picker", None)
    try:
        if parent is not None:
            parent.picker = content
        dialog.exec()
    finally:
        if parent is not None:
            parent.picker = parent_picker
    return content
