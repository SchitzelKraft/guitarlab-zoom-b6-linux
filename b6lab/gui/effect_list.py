"""EFFECT page, laid out and drawn like Guitar Lab's EffectPageComponent.

From the decompiled Mac binary (analysis/ui-trace/classes):
- EffectPageComponent::resized (FUN_100053640): list | 4 px bar | Effect Pool (256..360 px,
  shared like the PATCH page) above a 40 px strip; "Used Memory nn%" at (w-150, h-32, 120, 13)
  with a 120 x 7 bar under it (processor-bar colours);
- EffectListComponent: rows 56, header 35, columns Category (160, 160..256), Effect (170,
  160..256), Power 96, Comment (180, 180..1000), Use 80, Fav 64, fitted to the width like
  juce::TableHeaderComponent::resizeColumnsToFit (checked: 184 | 192 | 96 | 390 | 80 | 64);
- paintRowBackground (FUN_1000803b0): Category, Effect and Power cells in the category colour
  with saturation x0.85 / brightness x0.74 (even rows) or x0.8 / x0.5 (odd rows); odd rows
  darken the other cells (33,38,45); selection = 2 px (0,255,255) frame;
- paintCell (FUN_100080570): category bold 22 white at x=32 with an 8 px category bar at
  (12, 6); effect icon (its colour SVG at 0.375) and name bold 22 at x=64; power as a
  white 23 % bar (4, 16, (w-12) x share, 20) with "nn%" regular 17 right-aligned; comment
  regular 15 (153,153,153) on up to 3 lines; use count regular 15 centred; star image;
- category colours: the 10-colour table DAT_10051bc60 indexed by category number % 10.
- EffectPoolComponent: tree (8, 48, w-8, h-240) on (41,47,57); info panel 188 px at the bottom.
"""
from collections import Counter

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableView, QWidget

from b6lab import effects, ptcf
from b6lab.gui.glui import (CENTRED, LEFT, RIGHT, VCENTRE, ImageButton, Painted, draw_fitted_text, font, image, rgb,
                            stretch_layout)
from b6lab.gui.patch_list import (HEADER_BG, HEADER_TEXT, TABLE_BG, PatchHeader, paint_table_header_title)

CATEGORY_COLOURS = ["#0c419a", "#3d258e", "#6b1687", "#ae0158", "#ff4000", "#ff8c00", "#b2db11",
                    "#1b9850", "#017e74", "#006881"]
COLUMNS = [  # title, width, minimum, maximum
    ("Category", 160, 160, 256), ("Effect", 170, 160, 256), ("Power", 96, 96, 96),
    ("Comment", 180, 180, 1000), ("Use", 80, 80, 80), ("Fav", 64, 64, 64)]
STAR, STAR_ON = "00312bc0.png", "00312eb0.png"


def fit_columns(widths, minimums, maximums, target):
    """juce::StretchableObjectResizer::resizeToFit, as used by TableHeaderComponent:
    the space is shared in proportion to each column's room to grow (or shrink)."""
    current = sum(widths)
    if target >= current:
        room = sum(mx - w for w, mx in zip(widths, maximums))
        scale = min(1.0, (target - current) / room) if room > 0 else 0.0
        sizes = [w + (mx - w) * scale for w, mx in zip(widths, maximums)]
    else:
        room = sum(w - mn for w, mn in zip(widths, minimums))
        scale = min(1.0, (current - target) / room) if room > 0 else 0.0
        sizes = [w - (w - mn) * scale for w, mn in zip(widths, minimums)]
    return [int(s) for s in sizes]


def category_colour(fx_id):
    return QColor(CATEGORY_COLOURS[(fx_id >> 24) % 10])


def row_colour(fx_id, row):
    h, s, v, a = category_colour(fx_id).getHsvF()
    sat, bright = (0.8, 0.5) if row % 2 else (0.85, 0.74)
    return QColor.fromHsvF(h, min(1.0, s * sat), min(1.0, v * bright), a)


_ICONS = {}


def effect_icon(fx_id, scale=0.375):
    """The effect's colour SVG at 0.375 of its view box (EffectListComponent::paintCell); a
    larger scale gives the full image (Effect Properties draws it at half its size)."""
    if scale == 0.375 and fx_id in _ICONS:
        return _ICONS[fx_id]
    from b6lab.gui.editor import SVG_DIR, _module
    name = _module(fx_id)
    img = None
    if name and (SVG_DIR / f"{name}.svg").exists():
        r = QSvgRenderer(str(SVG_DIR / f"{name}.svg"))
        box = r.viewBoxF()
        img = QImage(round(box.width() * scale), round(box.height() * scale),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p)
        p.end()
    if scale == 0.375:
        _ICONS[fx_id] = img
    return img


class EffectModel(QAbstractTableModel):
    HEADERS = tuple(c[0] for c in COLUMNS)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = sorted((info for info in effects.catalog().values() if info.group != "IR"),
                            key=lambda i: (i.fx_id >> 24, i.fx_id))
        self.uses = None
        self.installed = {}          # effect ID -> on the pedal (FLST_SEQ.ZT2); missing = yes
        self.favorites = load_favorites()

    def is_installed(self, fx_id):
        return self.installed.get(fx_id, True)

    def set_installed(self, mapping):
        self.installed = dict(mapping)
        if self.items:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.items) - 1, len(COLUMNS) - 1))

    def toggle_favorite(self, fx_id):
        self.favorites ^= {fx_id}
        save_favorites(self.favorites)
        if self.items:
            self.dataChanged.emit(self.index(0, 5), self.index(len(self.items) - 1, 5))

    # drag source (Guitar Lab's effect list rows) and drop target (Effect Pool items)
    MIME = "application/x-guitarlab-effect"

    def flags(self, index):
        f = super().flags(index)
        return f | Qt.ItemFlag.ItemIsDragEnabled if index.isValid() else f

    def mimeTypes(self):
        return [self.MIME]

    def mimeData(self, indexes):
        from PySide6.QtCore import QByteArray, QMimeData
        rows = sorted({i.row() for i in indexes if i.isValid()})
        mime = QMimeData()
        if rows:
            mime.setData(self.MIME, QByteArray(b"list:%d" % self.items[rows[0]].fx_id))
        return mime

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return "" if section == 5 else self.HEADERS[section]
        return None

    def power(self, info):
        load = effects.dsp_load(info.fx_id)
        return None if load is None else load / 220

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        info = self.items[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            power = self.power(info)
            return (info.group, info.name, "" if power is None else f"{int(power * 100 + 0.5)}%",
                    info.description.replace("\r", " ").replace("\n", " "),
                    str(self.uses[info.fx_id]) if self.uses is not None else "", "")[column]
        return None

    SORTABLE = (0, 1, 2, 4, 5)  # column flags 0x13 (sortable); Comment (3) is not

    def sort_key(self, column):
        def power(i):
            return self.power(i) or 0.0
        keys = {0: lambda i: (i.fx_id >> 24, i.fx_id), 1: lambda i: i.name.lower(), 2: power,
                4: lambda i: (self.uses or {}).get(i.fx_id, 0), 5: lambda i: 0}
        return keys[column]

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if column not in self.SORTABLE:
            return
        self.layoutAboutToBeChanged.emit()
        # stable: equal keys keep the catalog order (category, then effect ID)
        self.items.sort(key=lambda i: (i.fx_id >> 24, i.fx_id))
        self.items.sort(key=self.sort_key(column), reverse=order == Qt.SortOrder.DescendingOrder)
        self.layoutChanged.emit()

    def set_slots(self, slots):
        uses = Counter()
        for data in slots:
            try:
                patch = ptcf.parse(data)
            except ValueError:
                continue
            uses.update(effect.fx_id for effect in patch.effects if effect.fx_id and not effect.is_tail)
        self.uses = uses
        if self.items:
            self.dataChanged.emit(self.index(0, 4), self.index(len(self.items) - 1, 4))


def _favorites_path():
    import os
    from pathlib import Path
    return Path(os.environ.get("B6LAB_FAVORITES", Path.home() / ".config" / "b6lab" / "favorites.json"))


def load_favorites():
    """The starred effects ("Favorite" in the effect list's menu), kept on this computer."""
    import json
    try:
        return {int(x) for x in json.loads(_favorites_path().read_text())}
    except (OSError, ValueError, TypeError):
        return set()


def save_favorites(favorites):
    import json
    path = _favorites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(favorites)))


NOT_ON_DEVICE = "0030a8e0.png"


def effect_version(fx_id):
    """The version in the pedal's effect list record (FLST_SEQ.ZT2: name 13, version 5)."""
    from pathlib import Path
    from b6lab import effect_files
    name = effect_files.module_file(fx_id)
    path = effect_files.PEDAL_FILES / "FLST_SEQ.ZT2"
    if not name or not path.is_file():
        return ""
    data = path.read_bytes()
    key = name.encode().ljust(13, b"\0")
    i = data.find(key)
    return data[i + 13:i + 18].split(b"\0")[0].decode("ascii", "replace") if i >= 0 else ""  # round arrow over the icon of an effect that is not on the pedal


def _wrapped(p, text, rect, f, max_lines, top=False):
    """juce drawFittedText with several lines: word-wrapped, lines centred vertically (or from
    the top for a top justification)."""
    from PySide6.QtGui import QFontMetricsF
    from b6lab.gui.glui import font_height
    fm = QFontMetricsF(f)
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if fm.horizontalAdvance(trial) <= rect.width() or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    h = font_height(f)
    y = rect.y() if top else rect.y() + (rect.height() - h * len(lines)) / 2
    for ln in lines:
        draw_fitted_text(p, ln, QRectF(rect.x(), y, rect.width(), h), f, LEFT | VCENTRE)
        y += h


class EffectRowDelegate(QStyledItemDelegate):
    def paint(self, p, option, index):
        model = index.model()
        info = model.items[index.row()]
        row, col = index.row(), index.column()
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(r, QColor(TABLE_BG))
        if col < 3:
            p.fillRect(r.x(), r.y(), r.width() - 4, r.height() - 4, row_colour(info.fx_id, row))
        elif row % 2:
            p.fillRect(r.x(), r.y(), r.width() - 4, r.height(), rgb(33, 38, 45))
        p.translate(r.x(), r.y())
        w, h = r.width(), r.height()
        text = model.data(index) or ""
        if col == 0:
            p.setPen(rgb(255, 255, 255))
            draw_fitted_text(p, text, QRectF(32, 0, w - 40, h), font(22, True), LEFT | VCENTRE)
            p.fillRect(12, 6, 8, h - 16, category_colour(info.fx_id))
        elif col == 1:
            p.setPen(rgb(255, 255, 255))
            draw_fitted_text(p, text, QRectF(64, 0, w - 40, h), font(22, True), LEFT | VCENTRE, 1.0)
            icon = effect_icon(info.fx_id)
            if icon is not None:
                p.drawImage(QRectF(32 - icon.width() * 0.5, max(0.0, (h - icon.height()) * 0.5),
                                   icon.width(), icon.height()), icon)
            if not model.is_installed(info.fx_id):
                # paintCell case 2: image 0030a8e0 at half size at (16, 12) when not on the pedal
                arrow = image(NOT_ON_DEVICE)
                p.drawImage(QRectF(16, 12, arrow.width() / 2, arrow.height() / 2), arrow)
        elif col == 2:
            power = model.power(info)
            if power is not None:
                bar = QColor(255, 255, 255)
                bar.setAlphaF(0.23)
                p.fillRect(QRectF(4, 16, int((w - 12) * power), 20), bar)
                p.setPen(rgb(255, 255, 255))
                draw_fitted_text(p, text, QRectF(8, 0, w - 20, h), font(17), RIGHT | VCENTRE)
        elif col == 3:
            p.setPen(rgb(153, 153, 153))
            _wrapped(p, text, QRectF(24, 8, w - 32, h - 16), font(15), 3)
        elif col == 4:
            p.setPen(rgb(153, 153, 153))
            draw_fitted_text(p, text, QRectF(8, 0, w - 16, h), font(15), CENTRED)
        else:
            star = image(STAR_ON if info.fx_id in model.favorites else STAR)
            p.drawImage(QRectF(22, 18, star.width() / 2, star.height() / 2), star)
        p.restore()
        if option.state & QStyle.StateFlag.State_Selected:
            p.save()
            p.setPen(QPen(QColor(0, 255, 255), 2))
            y0, y1 = r.y() + 1, r.y() + h - 4 - 1
            x0 = r.x() + 1 if col == 0 else r.x() - 1
            x1 = r.right() - 1 if col == 5 else r.right() + 1
            p.drawLine(x0, y0, x1, y0)
            p.drawLine(x0, y1, x1, y1)
            if col == 0:
                p.drawLine(r.x() + 1, y0, r.x() + 1, y1)
            if col == 5:
                p.drawLine(r.right() - 1, y0, r.right() - 1, y1)
            p.restore()


class EffectHeader(PatchHeader):
    """The table header with JUCE's sort arrow on the sorted column (Category, ascending).

    Like juce::TableHeaderComponent: clicking a sortable column sorts it ascending, clicking
    the sorted column again reverses it; the arrow points up when ascending."""

    sorted_column = 0
    ascending = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSectionsClickable(True)
        self.sectionClicked.connect(self._clicked)

    def _clicked(self, column):
        model = self.model()
        if model is None or column not in model.SORTABLE:
            return
        self.ascending = not self.ascending if column == self.sorted_column else True
        self.sorted_column = column
        model.sort(column, Qt.SortOrder.AscendingOrder if self.ascending else Qt.SortOrder.DescendingOrder)
        self.viewport().update()

    def paintSection(self, painter, rect, logical):
        super().paintSection(painter, rect, logical)
        if logical == self.sorted_column:
            from PySide6.QtGui import QPainterPath
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            x = rect.x() + rect.width() - 4 - 22
            path = QPainterPath()
            if self.ascending:
                path.moveTo(x, 19)
                path.lineTo(x + 8, 19)
                path.lineTo(x + 4, 12)
            else:
                path.moveTo(x, 12)
                path.lineTo(x + 8, 12)
                path.lineTo(x + 4, 19)
            path.closeSubpath()
            painter.fillPath(path, QColor(HEADER_TEXT))
            painter.restore()


class EffectsView(QWidget):
    def __init__(self, window):
        super().__init__()
        self.memory = 0.0  # share of the pedal's effect memory in use (FFS space), unknown yet
        self.model = EffectModel(self)
        self.list = QTableView(self)
        self.list.setModel(self.model)
        from b6lab.gui.patch_list import configure_patch_table
        configure_patch_table(self.list, stretch_comment=False)
        self.list.setHorizontalHeader(EffectHeader(self.list))
        for i in range(len(COLUMNS)):
            self.list.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        self.list.setItemDelegate(EffectRowDelegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.bar = QWidget(self)
        self.bar.setStyleSheet("background: #1a1e24;")
        self.open_groups = set()   # Effect Pool categories that are open
        self.pool_scroll = 0
        self.pool = Painted(self._paint_pool, self)
        self.pool.mousePressEvent = lambda e: (setattr(self, "_pool_press", e.position().toPoint()),
                                               self._pool_clicked(e.position()))
        self.pool.wheelEvent = self._pool_wheel
        self.strip = Painted(self._paint_strip, self)
        window.worker.all_loaded.connect(self.model.set_slots)
        window.worker.memory.connect(self._on_memory)
        # effects on the pedal: right-click menu, the delete question, drags list <-> pool
        self.window = window
        self.connected = False
        window.worker.connected.connect(lambda _i: setattr(self, "connected", True))
        window.worker.disconnected.connect(lambda _r: setattr(self, "connected", False))
        window.worker.effects_installed.connect(self.model.set_installed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.list.viewport().setAcceptDrops(True)
        self.list.viewport().installEventFilter(self)
        self.pool.setAcceptDrops(True)
        self.pool.installEventFilter(self)
        self.pool.mouseMoveEvent = self._pool_drag
        self._pool_press = None
        # EffectPoolInfoComponent: the selected pool effect and its "Load to Device" button
        self.pool_info = None
        self.pool_load = ImageButton("0030c5c0.png", "0030c2a0.png", "0030c8e0.png", "0030bf60.png",
                                     caption="", placement="fit", parent=self.pool)
        self.pool_load.setText("Load to Device")
        self.pool_load.hide()
        self.pool_load.clicked.connect(lambda: self.pool_info is not None and self.load_effect(self.pool_info.fx_id))
        self.pool_load.paintEvent = self._paint_pool_load
        self.model.dataChanged.connect(lambda *_: self.pool_info is not None and self.show_pool_info(self.pool_info))

    # effects on the pedal ---------------------------------------------------------------
    def _menu(self, pos):
        """EffectListComponent's right-click menu (FUN_100081250): Favorite (ticked),
        "Load to Device" or "Delete from Device", "Properties..."."""
        from PySide6.QtWidgets import QMenu
        index = self.list.indexAt(pos)
        if not index.isValid():
            return
        info = self.model.items[index.row()]
        menu = QMenu(self)
        fav = menu.addAction("Favorite")
        fav.setCheckable(True)
        fav.setChecked(info.fx_id in self.model.favorites)
        installed = self.model.is_installed(info.fx_id)
        change = menu.addAction("Delete from Device" if installed else "Load to Device")
        change.setEnabled(self.connected and bool(self.model.installed))
        props = menu.addAction("Properties...")
        chosen = self.exec_menu(menu, self.list.viewport().mapToGlobal(pos))
        if chosen is fav:
            self.model.toggle_favorite(info.fx_id)
        elif chosen is change:
            (self.delete_effect if installed else self.load_effect)(info.fx_id)
        elif chosen is props:
            self.show_properties(info)

    @staticmethod
    def exec_menu(menu, pos):
        return menu.exec(pos)

    def ask_ok_cancel(self, title, text):
        from b6lab.gui.gldialog import ask_ok_cancel
        return ask_ok_cancel(self, title, text)

    def delete_effect(self, fx_id):
        """"Delete from Device" (FUN_1000814a0 case 3): Guitar Lab asks first, naming how many
        patches use the effect; then the files go (b6lab/ffs.py)."""
        info = effects.lookup(fx_id)
        if info is None or not self.connected or not self.model.is_installed(fx_id):
            return False
        uses = self.model.uses[fx_id] if self.model.uses is not None else 0
        text = f"Are you sure you want to delete {info.name}?\n{info.name} Usage: {uses} Patches"
        if not self.ask_ok_cancel("ZOOM Guitar Lab", text):
            return False
        self.window.request_remove_effect.emit(fx_id)
        return True

    def load_effect(self, fx_id):
        """"Load to Device" (case 2): no question (Guitar Lab asks none)."""
        if not self.connected or self.model.is_installed(fx_id):
            return False
        self.window.request_install_effect.emit(fx_id)
        return True

    def show_properties(self, info):
        """"Properties...": Guitar Lab's "Effect Properties" (EffectPropertiesComponent)."""
        from b6lab.gui.gldialog import show_effect_properties
        show_effect_properties(self, info, effect_icon(info.fx_id, 2.0))

    def _pool_drag(self, event):
        """Drag an effect out of the Effect Pool (onto the list: Load to Device)."""
        from PySide6.QtCore import QByteArray, QMimeData
        from PySide6.QtGui import QDrag
        from PySide6.QtWidgets import QApplication
        if not event.buttons() & Qt.MouseButton.LeftButton or self._pool_press is None:
            return
        if (event.position().toPoint() - self._pool_press).manhattanLength() < QApplication.startDragDistance():
            return
        start, self._pool_press = self._pool_press, None
        index = int((start.y() - (47 - self.pool_scroll)) // self.ROW)
        rows = self.pool_rows()
        if not 0 <= index < len(rows) or rows[index][0] != "effect":
            return
        mime = QMimeData()
        mime.setData(EffectModel.MIME, QByteArray(b"pool:%d" % rows[index][1].fx_id))
        drag = QDrag(self.pool)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        kinds = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
        if event.type() in kinds and obj in (self.list.viewport(), self.pool):
            data = bytes(event.mimeData().data(EffectModel.MIME)).decode() if \
                event.mimeData().hasFormat(EffectModel.MIME) else ""
            source, _, fx = data.partition(":")
            wanted = "pool" if obj is self.list.viewport() else "list"
            if source != wanted:
                return False
            event.acceptProposedAction()
            if event.type() == QEvent.Type.Drop:
                # pool -> list: Load to Device; list -> pool: Delete from Device
                (self.load_effect if wanted == "pool" else self.delete_effect)(int(fx))
            return True
        return super().eventFilter(obj, event)

    def _on_memory(self, share):
        self.memory = share
        self.strip.update()

    def resizeEvent(self, _event):
        w, h = self.width(), self.height()
        lw, bw, pw = stretch_layout(w, [(-0.5, -0.9, -0.75), (4, 4, 4), (256, 360, 256)])
        lh = max(0, h - 40)
        self.list.setGeometry(0, 0, lw, lh)
        widths = fit_columns([c[1] for c in COLUMNS], [c[2] for c in COLUMNS], [c[3] for c in COLUMNS], lw)
        for i, cw in enumerate(widths):
            self.list.setColumnWidth(i, cw)
        self.bar.setGeometry(lw, 0, bw, lh)
        self.pool.setGeometry(lw + bw, 0, pw, lh)
        self.strip.setGeometry(0, lh, w, 40)
        self._place_pool_load()

    def _paint_strip(self, p, widget):
        p.fillRect(widget.rect(), rgb(26, 30, 36))
        x = widget.width() - 150
        p.setPen(rgb(225, 248, 254))
        draw_fitted_text(p, f"Used Memory {int(self.memory * 100 + 0.5)}%", QRectF(x, 8, 120, 13), font(14),
                         CENTRED)
        used = int(min(1.0, self.memory) * 120)
        p.fillRect(x, 25, used, 7, rgb(33, 145, 175))
        p.fillRect(x + used, 25, 120 - used, 7, rgb(30, 97, 134))

    ROW = 26  # Effect Pool tree row height (measured)

    def pool_rows(self):
        """The tree's visible rows: ("group", name) and, under an open group, ("effect", info)."""
        ordered = sorted(self.model.items, key=lambda i: (i.fx_id >> 24, i.fx_id))
        rows = []
        for group in dict.fromkeys(info.group for info in ordered):
            rows.append(("group", group))
            if group in self.open_groups:
                # Guitar Lab lists them by name in plain character order (seen: "DYN Comp"
                # before "DualComp"), not in catalog order
                rows.extend(("effect", info) for info in sorted(
                    (i for i in ordered if i.group == group), key=lambda i: i.name))
        return rows

    def _pool_clicked(self, pos):
        """A click on a category row opens or closes it (TreeView inside (8, 48, w-8, h-240))."""
        top = 47 - self.pool_scroll
        if not (8 <= pos.x() and 47 <= pos.y() < self.pool.height() - 240 + 48):
            return
        index = int((pos.y() - top) // self.ROW)
        rows = self.pool_rows()
        if 0 <= index < len(rows) and rows[index][0] == "group":
            self.open_groups ^= {rows[index][1]}
            self.pool_scroll = 0
            self.pool.update()
        elif 0 <= index < len(rows):
            self.show_pool_info(rows[index][1])

    def _paint_pool_load(self, _event):
        """HSImageButton with the caption bold 15 in (42,50,63) on the button images."""
        b = self.pool_load
        p = QPainter(b)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        state = b._state()
        p.drawImage(QRectF(0, 0, b.width(), b.height()), image(b._image_for(state)))
        p.setPen(rgb(42, 50, 63))
        draw_fitted_text(p, "Load to Device", QRectF(0, 0, b.width(), b.height()), font(15, True), CENTRED)

    def show_pool_info(self, info):
        """An effect picked in the pool shows in the info panel; "Load to Device" appears when it
        is not on the pedal (EffectPoolInfoComponent, button FUN_10007b870 -> load)."""
        self.pool_info = info
        self.pool_load.setVisible(info is not None and not self.model.is_installed(info.fx_id))
        self._place_pool_load()
        self.pool.update()

    def _place_pool_load(self):
        self.pool_load.setGeometry(16, self.pool.height() - 188 + 144, 127, 23)

    def _pool_wheel(self, event):
        visible = self.pool.height() - 240
        extra = max(0, len(self.pool_rows()) * self.ROW - visible)
        self.pool_scroll = max(0, min(extra, self.pool_scroll - event.angleDelta().y() // 120 * self.ROW))
        self.pool.update()

    def _paint_pool(self, p, widget):
        from PySide6.QtGui import QPainterPath
        w, h = widget.width(), widget.height()
        p.fillRect(widget.rect(), rgb(41, 47, 57))
        f = font(20)
        p.save()
        p.setClipRect(QRectF(8, 47, w - 8, max(0, h - 240)))
        y = 47 - self.pool_scroll
        for kind, item in self.pool_rows():
            p.setPen(QColor(HEADER_TEXT))
            arrow = QPainterPath()
            indent = 0 if kind == "group" else 20
            if kind == "group" and item in self.open_groups:
                arrow.moveTo(8 + 10, y + 10)
                arrow.lineTo(8 + 18, y + 10)
                arrow.lineTo(8 + 14, y + 17)
            elif kind == "group":
                arrow.moveTo(8 + 11, y + 9)
                arrow.lineTo(8 + 18, y + 13)
                arrow.lineTo(8 + 11, y + 17)
            arrow.closeSubpath()
            if kind == "group":
                p.fillPath(arrow, QColor(HEADER_TEXT))
            text = item if kind == "group" else item.name
            draw_fitted_text(p, text, QRectF(8 + 25 + indent, y, w - 41 - indent, self.ROW), f, LEFT | VCENTRE)
            y += self.ROW
        p.restore()
        paint_table_header_title(p, "Effect Pool", w, 35)
        p.fillRect(0, 30, w, 5, rgb(41, 47, 57))
        info_y = h - 188
        p.fillRect(0, info_y - 4, w, 4, rgb(26, 30, 36))
        p.fillRect(0, info_y, w, 30, QColor(HEADER_BG))
        p.fillRect(0, info_y + 30, w, h - info_y - 30, QColor(TABLE_BG))
        info = self.pool_info
        if info is not None:
            # EffectPoolInfoComponent: the name as the header title (paint FUN_10007b720),
            # Description regular 15 (166,166,166) in (14, 40, w-22, 80), top-left, squeezed to
            # 80 %; Version in (16, 120, w-24, 15) (resized FUN_10007b810)
            p.save()
            p.translate(0, info_y)
            paint_table_header_title(p, info.name, w, 30)
            p.setPen(rgb(166, 166, 166))
            _wrapped(p, info.description.replace("\r", " ").replace("\n", " "),
                     QRectF(14, 40, w - 22, 80), font(15), 5, top=True)
            version = effect_version(info.fx_id)
            if version:
                draw_fitted_text(p, f"Version {version}", QRectF(16, 120, w - 24, 15), font(15),
                                 LEFT | VCENTRE)
            p.restore()
