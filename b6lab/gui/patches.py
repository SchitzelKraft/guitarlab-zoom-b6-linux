"""Patches tab: the 240-slot list with import, export, restore and backup."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog,
                               QInputDialog, QMessageBox, QPushButton, QTableView, QVBoxLayout,
                               QWidget)

from b6lab import library, ptcf
from b6lab.device import used_bytes
from b6lab.gui import patch_search
from b6lab.gui.gldialog import TextButton
from b6lab.gui.glui import Painted, image, rgb, stretch_layout
from b6lab.gui.patch_list import PatchListModel, configure_patch_table, paint_table_header_title, slot_label
from b6lab.gui.patch_pool import MIME_POOL, MIME_ROWS, PatchPoolView, node_at
from b6lab.pool import DEFAULT_ROOT, PatchPool


def _is_empty(data):
    try:
        return ptcf.parse(data).name.strip() == "Empty"
    except Exception:
        return False


class PatchesView(QWidget):
    LEFT_ARROW, RIGHT_ARROW = "00324cd0.png", "00324e50.png"

    def resizeEvent(self, _event):
        w, h = self.width(), self.height()
        lw, bw, pw = stretch_layout(w, [(-0.5, -0.9, -0.75), (4, 4, 4), (256, 360, 256)])
        lh = max(0, h - 40)
        sh = patch_search.HEIGHT
        self.search_box.setGeometry(8, 5, max(0, lw - 16), sh - 10)
        self.list.setGeometry(0, sh, lw, max(0, lh - sh))
        self.bar.setGeometry(lw, 0, bw, lh)
        self.pool.setGeometry(lw + bw, 0, pw, lh)
        self.backup_button.setGeometry(lw - 57, lh + 8, 114, 23)
        self.restore_button.setGeometry(lw - 57, lh + 8, 114, 23)
        self.restore_button.raise_()
        self.arrows.setGeometry(0, lh, w, 40)
        self.backup_button.raise_()

    def _paint_arrows(self, p, widget):
        from PySide6.QtCore import QRectF
        p.fillRect(widget.rect(), rgb(26, 30, 36))
        bar_x = self.list.width()
        if self.restore_button.isVisibleTo(self):
            # the restore pair: 003251c0 left, 00325340 right, the heights swapped
            left, right = image("003251c0.png"), image("00325340.png")
            box_w, box_h = right.width() // 2, right.height() // 2
            p.drawImage(QRectF(bar_x - box_w - 64 + (box_w - left.width() / 2) / 2,
                               7 + (box_h - left.height() / 2) / 2, left.width() / 2, left.height() / 2), left)
            p.drawImage(QRectF(bar_x + 64, 9, right.width() / 2, right.height() / 2), right)
            return
        left, right = image(self.LEFT_ARROW), image(self.RIGHT_ARROW)
        p.drawImage(QRectF(bar_x - left.width() // 2 - 64, 9, left.width() / 2, left.height() / 2), left)
        # both image components are sized from the 38 x 36 image; the other one is centred in it
        box_w, box_h = left.width() // 2, left.height() // 2
        p.drawImage(QRectF(bar_x + 64 + (box_w - right.width() / 2) / 2, 7 + (box_h - right.height() / 2) / 2,
                           right.width() / 2, right.height() / 2), right)

    def paintEvent(self, _event):
        from PySide6.QtGui import QPainter
        QPainter(self).fillRect(self.rect(), rgb(26, 30, 36))

    def __init__(self, window, backup_root=Path("backup"), browse_root=None, pool_root=DEFAULT_ROOT):
        super().__init__()
        self.window = window
        self.backup_root = Path(backup_root)  # where "Back up all" writes
        # where backup sets are listed for Restore / Browse (None: same as backup_root)
        self.browse_root = None if browse_root is None else Path(browse_root)
        self.slots = []
        self.connected = False
        self.offline = False
        self.ready = False  # connected and all 240 slots known
        self._saving = None  # (slot, bytes) of my own in-flight save

        # PatchPageComponent (decompiled Mac binary, ctor FUN_100284..., resized FUN_1002858f0):
        # list | 4 px bar | Patch Pool (256..360 px) above a 40 px strip with "Backup All"
        # (TextButton 114 x 23 at bar-57) between two arrow images. Import, export and restore
        # are drag and drop in Guitar Lab; those buttons are kept for now but not shown.
        self.import_button = QPushButton("Import .zptc...", self)
        self.export_button = QPushButton("Export...", self)
        self.restore_button = QPushButton("Restore from backup...", self)
        self.browse_button = QPushButton("Browse backup...", self)
        for b in (self.import_button, self.export_button, self.restore_button, self.browse_button):
            b.hide()
        self.progress = None  # the "Creating Backup" window while a backup runs
        self.backup_button = TextButton("Backup All", self)
        self.backup_button.outline = rgb(56, 66, 79)
        self.backup_button.text_colour = rgb(230, 238, 240)

        self.model = PatchListModel(self)
        self.list = QTableView(self)
        self.search_box, self.proxy = patch_search.attach(self, self.list, self.model)
        configure_patch_table(self.list)
        self.bar = QWidget(self)
        self.bar.setStyleSheet("background: #1a1e24;")
        # Patch Pool: patches on the computer, in groups (b6lab/pool.py, patch_pool.py)
        self.pool_store = PatchPool(pool_root)
        self.pool = PatchPoolView(self.pool_store, self)
        self.pool.rows_dropped.connect(self._rows_to_pool)
        self.pool.selection_changed.connect(self._pool_selection)
        self.pool.menu_requested.connect(self._pool_menu)
        self.pool.properties_requested.connect(self.pool_properties)
        self._undo = []  # pool trees before each change (Guitar Lab's UndoManager, pool part)
        # "Restore All": shown instead of "Backup All" while a backup group is selected
        # (PatchPageComponent: button 0x6e0, FUN_100285f90; restore FUN_100045c30)
        self.restore_button = TextButton("Restore All", self)
        self.restore_button.outline = rgb(56, 66, 79)
        self.restore_button.text_colour = rgb(230, 238, 240)
        self.restore_button.hide()
        self.restore_button.clicked.connect(lambda: self.restore_all(self.pool.selected))
        # the patch list: rows drag into the pool; pool items drop onto a row (import)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QTableView.DragDropMode.DragOnly)
        self.list.viewport().setAcceptDrops(True)
        self.list.viewport().installEventFilter(self)
        self._imports = []  # (slot, data) still to write for a pool import
        self._moving = None  # [(slot, data)] of a patch move in flight
        self.arrows = Painted(self._paint_arrows, self)
        self.arrows.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.import_button.clicked.connect(self.import_patch)
        self.export_button.clicked.connect(self.export_patch)
        self.restore_button.clicked.connect(self.restore)
        self.backup_button.clicked.connect(self.backup_all)
        self.browse_button.clicked.connect(self.browse_backup)

        w = window.worker
        w.connected.connect(self._on_connected)
        w.disconnected.connect(self._on_disconnected)
        w.all_loaded.connect(self._on_all_loaded)
        w.slot_loaded.connect(self._on_slot_loaded)
        w.saved.connect(self._on_saved)
        w.backup_done.connect(self._on_backup_done)
        w.patches_moved.connect(self._on_moved)
        w.error.connect(self._close_progress)
        w.disconnected.connect(self._close_progress)
        self._update_buttons()

    # dialogs (overridable in tests)
    def ask_open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import patch", "", "Patches (*.zptc)")
        return path or None

    def ask_save_file(self, suggested=""):
        path, _ = QFileDialog.getSaveFileName(self, "Export patch", suggested, "Patches (*.zptc)")
        return path or None

    def ask_confirm(self, text):
        return QMessageBox.question(self, "Confirm", text) == QMessageBox.StandardButton.Yes

    def ask_backup_choice(self):
        sets = library.list_backups(self.browse_root or self.backup_root)
        if not sets:
            self.window.show_error("no backup sets found")
            return None
        sets.sort(key=lambda s: s.created, reverse=True)
        labels = [f"{s.path.name} ({len(s.slots)} patches)" for s in sets]
        label, ok = QInputDialog.getItem(self, "Backup", "Backup set:", labels, 0, False)
        return sets[labels.index(label)] if ok else None

    def ask_backup_slot(self, backup):
        items = [f"{slot_label(i)}  {self._name(d)}" for i, d in enumerate(backup.slots)]
        item, ok = QInputDialog.getItem(self, "Restore", "Patch to restore:", items, 0, False)
        return items.index(item) if ok else None

    @staticmethod
    def _name(data):
        try:
            return ptcf.parse(data).name
        except Exception:
            return "?"

    # state
    def _on_connected(self, _ident):
        self._set_connected(True)

    def _on_disconnected(self, _reason):
        self._set_connected(False)

    def _set_connected(self, ok):
        self.connected = ok
        self.ready = False
        if ok:
            self.offline = False
        self._update_buttons()

    def _update_buttons(self):
        c = self.connected
        for b in (self.import_button, self.restore_button, self.backup_button):
            b.setEnabled(self.ready and self._saving is None)
            b.setToolTip("not connected" if not c else "" if self.ready else "reading patches...")
        self.export_button.setEnabled(bool(self.slots))
        self.browse_button.setEnabled(not c)

    def _on_all_loaded(self, slots):
        self.slots = [bytes(s) for s in slots]
        self.model.set_all(self.slots)
        self.ready = self.connected and len(self.slots) == 240
        self._update_buttons()

    def _on_slot_loaded(self, slot, data):
        if self.offline:
            return
        if 0 <= slot < len(self.slots):
            self.slots[slot] = bytes(data)
        self.model.set_slot(slot, data)

    def _selected(self):
        rows = self.list.selectionModel().selectedRows()
        return self.proxy.slot_of_row(rows[0].row()) if rows else None

    # actions
    def browse_backup(self):
        bs = self.ask_backup_choice()
        if bs is None:
            return
        self.offline = True
        self.slots = [bytes(s) for s in bs.slots]
        self.model.set_all(self.slots)
        self.window.editor_tab.show_offline(self.slots)
        self._update_buttons()
        self.window.statusBar().showMessage(f"browsing {bs.path.name} (read-only)")

    def export_patch(self):
        slot = self._selected()
        if slot is None or slot >= len(self.slots):
            self.window.show_error("select a patch first")
            return
        path = self.ask_save_file(f"{self._name(self.slots[slot]).strip() or 'patch'}.zptc")
        if not path:
            return
        try:
            library.export_zptc(self.slots[slot], path)
        except OSError as e:
            self.window.show_error(f"export failed: {e}")

    def import_patch(self):
        slot = self._selected()
        if slot is None:
            self.window.show_error("select a target slot first")
            return
        path = self.ask_open_file()
        if not path:
            return
        try:
            data = library.load_zptc(path)
        except (ValueError, OSError) as e:
            self.window.show_error(str(e))
            return
        self._write(slot, data, f"Overwrite {slot_label(slot)}")

    def restore(self):
        backup = self.ask_backup_choice()
        if backup is None:
            return
        src = self.ask_backup_slot(backup)
        if src is None:
            return
        slot = self._selected()
        if slot is None:
            slot = src
        try:
            data = used_bytes(backup.slots[src])
        except Exception as e:
            self.window.show_error(f"backup slot {src + 1} unusable: {e}")
            return
        current = self._name(self.slots[slot]) if 0 <= slot < len(self.slots) else "?"
        question = (f"Restore {self._name(data)} from {backup.path.name} into "
                    f"{slot_label(slot)} ({current})?")
        self._write(slot, data, f"Overwrite {slot_label(slot)}", question=question)

    def _write(self, slot, data, verb, question=None):
        """Write data into slot. question, if given, is always asked (even for Empty slots)."""
        if self._saving is not None:
            return
        if not self.connected:
            self.window.show_error("not connected")
            return
        if not self.ready or not 0 <= slot < len(self.slots):
            self.window.show_error("patch list not loaded yet")
            return
        current = self.slots[slot]
        if question is not None:
            if not self.ask_confirm(question):
                return
        elif current and not _is_empty(current):
            text = f"{verb} ({self._name(current)}) with {self._name(data)}?"
            if not self.ask_confirm(text):
                return
        ed = getattr(self.window, "editor_tab", None)
        if ed is not None and getattr(ed, "slot", None) == slot and ed.modified():
            text = (f"{slot_label(slot)} is open in the Editor with unsaved changes. "
                    f"Writing this slot discards those changes. Continue?")
            if not self.ask_confirm(text):
                return
        if not self.window.begin_save(self):
            return
        self._saving = (slot, data)
        self._update_buttons()
        self.window.request_save.emit(slot, data, current)

    def _on_saved(self, res):
        if self._saving is None:
            return
        slot, _data = self._saving
        self._saving = None
        self.window.end_save(self)
        self._update_buttons()
        if not res.ok:
            self._imports = []
            self._close_progress()
            self.window.report_save_failed(res)
            return
        self.window.report_saved(res)
        self.window.request_load_slot.emit(slot)
        if self._imports:
            self._next_import()
        else:
            self._close_progress()

    # Patch Pool ---------------------------------------------------------------------------
    def _snapshot(self):
        import copy
        self._undo.append(copy.deepcopy(self.pool_store.tree))

    def undo_pool(self):
        """Undo the last pool change (Guitar Lab: "Undo" in the pool menu, its UndoManager)."""
        if not self._undo:
            return
        self.pool_store.tree = self._undo.pop()
        self.pool_store.save()
        self.pool.select(None)
        self.pool.refresh()

    def _pool_selection(self, node):
        backup = node is not None and node.type == "PatchGroup" and node.get("isBackup") == 1
        self.restore_button.setVisible(backup)
        self.backup_button.setVisible(not backup)
        self.arrows.update()

    def _pool_menu(self, node, pos):
        """PatchPoolItem's menu (FUN_100046c80): Copy to Device, Delete, Undo, Properties...
        "Copy to Device" needs the pedal: a patch goes to the selected patch-list row; a backup
        group restores the whole backup (FUN_1000476f0 / FUN_1000477b0)."""
        from PySide6.QtWidgets import QMenu
        backup = node.type == "PatchGroup" and node.get("isBackup") == 1
        row = self.proxy.slot_of_row(self.list.currentIndex().row()) if self.list.currentIndex().isValid() else -1
        menu = QMenu(self)
        copy = menu.addAction("Copy to Device")
        copy.setEnabled(self.connected and self.ready and (backup or (node.type == "Patch" and row >= 0)))
        delete = menu.addAction("Delete")
        undo = menu.addAction("Undo")
        undo.setEnabled(bool(self._undo))
        props = menu.addAction("Properties...")
        chosen = self.exec_menu(menu, pos)
        if chosen is copy:
            self.restore_all(node) if backup else self.import_from_pool(node, row)
        elif chosen is delete:
            self.delete_from_pool(node)
        elif chosen is undo:
            self.undo_pool()
        elif chosen is props:
            self.pool_properties(node)

    @staticmethod
    def exec_menu(menu, pos):
        return menu.exec(pos)

    def delete_from_pool(self, node):
        """Delete (FUN_100043990): no question, undoable; the files stay for the undo."""
        self._snapshot()
        self.pool_store.remove(node)
        self.pool.select(None)
        self.pool.refresh()

    def ask_group_properties(self, name, count, device):
        from b6lab.gui.gldialog import ask_group_properties
        return ask_group_properties(self, name, count, device)

    def pool_properties(self, node):
        """Properties (FUN_100046fa0): "Patch Group Properties" renames a group; "Patch
        Properties" (PatchPropertiesComponent) edits a pool patch's name and comment."""
        if node.type == "PatchGroup":
            name = self.ask_group_properties(node.get("name", ""), len(node.children), node.get("device"))
            if name is not None and name != node.get("name"):
                self._snapshot()
                node.props["name"] = name
                self.pool_store.save()
                self.pool.update()
            return
        from b6lab import effects
        try:
            data = self.pool_store.data(node)
            patch = ptcf.parse(data)
        except (OSError, ValueError):
            return
        names = []
        for e in patch.effects:
            info = effects.lookup(e.fx_id) if e.fx_id and not e.is_tail else None
            if info is not None:
                names.append(info.name)
        answer = self.ask_patch_properties(patch.name, patch.comment, names)
        if answer is None or answer == (patch.name, patch.comment):
            return
        name, comment = answer
        self._snapshot()
        try:
            ptcf.set_name(patch, name)
            ptcf.set_comment(patch, comment)
        except (ValueError, PermissionError) as e:
            self.window.show_error(f"patch properties: {e}")
            return
        (self.pool_store.root / node.get("filename")).write_bytes(ptcf.encode(patch))
        node.props["name"] = self.pool_store.patch_name(ptcf.encode(patch))
        self.pool_store.save()
        self.pool.update()

    def ask_patch_properties(self, name, comment, effect_names):
        from b6lab.gui.gldialog import ask_patch_properties
        return ask_patch_properties(self, name, comment, effect_names)

    def restore_all(self, group):
        """Restore All / Copy to Device on a backup group (FUN_100045c30): the backup's patches
        into the pedal from A-001 on, with "Restoring backup..."."""
        if group is None or group.type != "PatchGroup":
            return
        self.import_from_pool(group, 0, progress_text="Restoring backup...")

    def _rows_to_pool(self, rows, group, index):
        """Patch-list rows dropped on the pool: copies of those patches on the computer."""
        datas = [self.slots[r] for r in rows if 0 <= r < len(self.slots) and self.slots[r]]
        if not datas:
            return
        self._snapshot()
        node = self.pool_store.add(datas, group=group, index=index)
        if group is not None:
            self.pool.open.add(id(group))
        self.pool.selected = node
        self.pool.refresh()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.list.viewport() and event.type() == QEvent.Type.DragLeave:
            self._show_drop_line(None)
            return False
        if obj is self.list.viewport() and event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                                                            QEvent.Type.Drop):
            mime = event.mimeData()
            if mime.hasFormat(MIME_ROWS) and event.source() is self.list:
                event.acceptProposedAction()
                self._show_drop_line(self.proxy.slot_of_row(self.list.rowAt(int(event.position().y()))))
                if event.type() == QEvent.Type.Drop:
                    self._show_drop_line(None)
                    import json
                    rows = json.loads(bytes(mime.data(MIME_ROWS)).decode())
                    target = self.proxy.slot_of_row(self.list.rowAt(int(event.position().y())))
                    if rows and target >= 0:
                        self.move_patch(rows[0], target)
                return True
            if not mime.hasFormat(MIME_POOL):
                return False
            event.acceptProposedAction()
            if event.type() == QEvent.Type.Drop:
                import json
                path = json.loads(bytes(mime.data(MIME_POOL)).decode())
                row = self.proxy.slot_of_row(self.list.rowAt(int(event.position().y())))
                self.import_from_pool(node_at(self.pool_store.tree, path), row)
            return True
        return super().eventFilter(obj, event)

    def _show_drop_line(self, row):
        """Where a dragged patch row will go: a 2 px line in the selection colour over that row
        (a B6 Lab aid; Guitar Lab's own drag feedback is not traced)."""
        from PySide6.QtWidgets import QFrame
        if not hasattr(self, "_drop_line"):
            self._drop_line = QFrame(self.list.viewport())
            self._drop_line.setStyleSheet("background: #f6ab6d;")
        if row is None or row < 0:
            self._drop_line.hide()
            return
        rect = self.list.visualRect(self.proxy.index_of_slot(row))
        self._drop_line.setGeometry(0, rect.top(), self.list.viewport().width(), 2)
        self._drop_line.show()
        self._drop_line.raise_()

    def move_patch(self, src, dst):
        """A row dragged onto another: the patch moves there and the ones in between shift, as
        Guitar Lab (recorded: MYOWNCOMPS 99 -> 101 rewrote 99, 100, 101)."""
        if self.proxy.filtering():
            self.window.show_error("Clear the search to move patches")
            return
        if src == dst or self._saving is not None or self._imports or not self.connected or not self.ready:
            return
        order = list(range(len(self.slots)))
        order.insert(dst, order.pop(src))
        lo, hi = min(src, dst), max(src, dst)
        writes = [(i, bytes(self.slots[order[i]])) for i in range(lo, hi + 1)]
        # no question, as Guitar Lab (which offers undo); every rewritten slot is backed up first
        if not self.window.begin_save(self):
            return
        self._moving = writes
        self._saving = (dst, self.slots[src])
        self._update_buttons()
        self.window.request_move_patches.emit(bytes(self.slots[src]), writes)

    def _on_moved(self, res):
        writes, self._moving = self._moving, None
        self._saving = None
        self.window.end_save(self)
        self._update_buttons()
        if not res.ok:
            self.window.report_save_failed(res)
        else:
            self.window.report_saved(res)
        for slot, _data in writes or []:
            self.window.request_load_slot.emit(slot)

    def import_from_pool(self, node, start, progress_text="Importing patches..."):
        """A pool patch or group dropped on the patch list at row `start`: Guitar Lab imports
        them into the pedal from that slot on, showing "Importing patches..."
        (PatchListComponent itemDropped -> FUN_100045770). B6 Lab asks once before writing
        (Guitar Lab offers undo instead) and writes each slot the safe way (backup, verify)."""
        if self._saving is not None or self._imports:
            return
        if not self.connected:
            self.window.show_error("not connected")
            return
        if not self.ready or not 0 <= start < len(self.slots):
            self.window.show_error("patch list not loaded yet")
            return
        datas = self.pool_store.patches_of(node)[:len(self.slots) - start]
        if not datas:
            return
        last = start + len(datas) - 1
        where = slot_label(start) if last == start else f"{slot_label(start)} .. {slot_label(last)}"
        if not self.ask_confirm(f"Write {len(datas)} patch(es) from the Patch Pool into {where}? "
                                f"The patches there now are backed up first."):
            return
        self._imports = list(zip(range(start, last + 1), datas))
        from b6lab.gui.gldialog import show_progress
        if self.progress is None:
            self.progress = show_progress(self, progress_text)
        self._next_import()

    def _next_import(self):
        slot, data = self._imports.pop(0)
        if not self.window.begin_save(self):
            self._imports = []
            self._close_progress()
            return
        self._saving = (slot, data)
        self._update_buttons()
        self.window.request_save.emit(slot, data, self.slots[slot])

    def backup_all(self):
        """Backup All: Guitar Lab shows "Creating Backup" until it is done (FUN_100285b20)."""
        from b6lab.gui.gldialog import show_progress
        if self.progress is not None:
            return
        self.progress = show_progress(self, "Creating Backup")
        self.window.request_backup.emit(str(self.backup_root))
        self.window.statusBar().showMessage("backing up...")

    def _close_progress(self, *_args):
        if self.progress is not None:
            self.progress.close()
            self.progress.deleteLater()
            self.progress = None

    def _on_backup_done(self, path):
        """Guitar Lab puts a backup into the Patch Pool as "Backup_<device>_<date>"
        (FUN_100285b20 -> FUN_100045130 with isBackup); B6 Lab keeps its backup/ folder too."""
        self._close_progress()
        self.window.statusBar().showMessage(f"backup saved to {path}")
        try:
            from b6lab.library import _load_set
            slots = [s for s in _load_set(Path(path)).slots if s]
            if slots:
                self._snapshot()
                self.pool_store.add(slots, backup=True)
                self.pool.refresh()
        except Exception as e:
            self.window.show_error(f"backup not added to the Patch Pool: {e}")
