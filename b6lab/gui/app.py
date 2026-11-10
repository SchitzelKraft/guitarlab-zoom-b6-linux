"""Main window: top bar, tabs, status bar, device worker thread."""
import sys
from pathlib import Path

from PySide6.QtCore import QMetaObject, QThread, Qt, Signal
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QTabWidget, QWidget

from b6lab.gui import theme
from b6lab.gui.glchrome import Chrome, MenuStrip, NavBar
from b6lab.gui.ir_page import IRView
from b6lab.gui.editor import EditorView
from b6lab.gui.effect_list import EffectsView
from b6lab.gui.patches import PatchesView
from b6lab.gui.worker import DeviceWorker



class _Root(QWidget):
    """Central widget laid out like Guitar Lab's window: menu strip, nav bar, current page."""

    parts = ()

    def resizeEvent(self, _event):
        if self.parts:
            strip, nav, page = self.parts
            Chrome.layout(self.width(), self.height(), strip, nav, [page])


class MainWindow(QMainWindow):
    request_connect = Signal()
    request_load_slot = Signal(int)
    request_save = Signal(int, bytes, bytes)
    request_save_edit = Signal(int, bytes, bytes)  # the editor's SAVE (adds Patch Save, 64 0D)
    request_select = Signal(int)
    request_read_all = Signal()
    request_backup = Signal(str)
    request_effect_on = Signal(int, int, bool, object)
    request_param_live = Signal(int, int, int)
    request_check_live = Signal(int, bytes)
    request_type = Signal(int, int, int)
    request_chain = Signal(int, str, int)
    request_install_effect = Signal(int)   # "Load to Device" (effect ID)
    request_tempo = Signal(int)            # TAP / typed BPM
    request_tuner = Signal(bool)           # TUNER on / off
    request_move_effect = Signal(int, int, int)  # patch slot, from entry, to entry
    request_add_clip = Signal(int, bytes, object, bool)  # slot, patch with the clip, (deletes, clip, entry), AUTO SAVE
    request_store = Signal(int)                  # AUTO SAVE on: Patch Save 64 0D of the current patch
    request_move_patches = Signal(object, object)  # moved patch, [(slot, data)]
    request_import_ir = Signal(int, str, bytes)
    request_remove_effect = Signal(int)    # "Delete from Device" (effect ID)

    def __init__(self, factory, backup_dir=Path("backup/overwritten"),
                 backup_root=Path("backup"), browse_root=None, pool_root=None):
        super().__init__()
        self._close_after_save = False
        self.setWindowTitle("ZOOM GuitarLab")
        # Guitar Lab: content 1280 x 700 (MainContentComponent), resize limits 1140 x 640 (MainWindow)
        self.resize(1280, 700)
        self.setMinimumSize(1140, 640)
        self.setStyleSheet(theme.STYLESHEET)
        self.slots = []

        central = _Root(self)
        self.menu_strip = MenuStrip(central)
        self.nav = NavBar(central)
        self.nav.page_selected.connect(self._nav_selected)
        self.nav.reload_clicked.connect(self.reconnect)
        self.nav.tux_clicked.connect(self._say_hello)
        self.navigation = self.nav.buttons
        self.reconnect_button = self.nav.reload
        # Guitar Lab has no status line; the connection is shown by the nav bar's icon.
        self.light_label = QLabel(central)
        self.light_label.hide()
        self.tabs = QTabWidget(central)
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet("QTabWidget::pane { border: 0; }")
        self.editor_tab = QWidget()
        self.patches_tab = QWidget()
        self.effects_tab = QWidget()
        self.backup_tab = QWidget()
        for w, name in ((self.editor_tab, "Editor"), (self.patches_tab, "Patches"),
                        (self.effects_tab, "Effects"), (self.backup_tab, "Backup")):
            self.tabs.addTab(w, name)
        self.tabs.setTabEnabled(3, False)
        central.parts = (self.menu_strip, self.nav, self.tabs)
        self.setCentralWidget(central)
        self.statusBar().hide()  # kept for messages (tests); Guitar Lab shows none
        self.set_connected(False)

        self.thread = QThread(self)
        self.worker = DeviceWorker(factory, backup_dir=backup_dir)
        self.worker.moveToThread(self.thread)
        self.request_connect.connect(self.worker.connect_device)
        self.request_load_slot.connect(self.worker.load_slot)
        self.request_save.connect(self.worker.save)
        self.request_save_edit.connect(self.worker.save_edit)
        self.request_select.connect(self.worker.select)
        self.request_read_all.connect(self.worker.read_all)
        self.request_backup.connect(self.worker.backup_all)
        self.request_effect_on.connect(self.worker.set_effect_on)
        self.request_param_live.connect(self.worker.set_param_live)
        self.request_check_live.connect(self.worker.check_live)
        self.request_type.connect(self.worker.change_type)
        self.request_chain.connect(self.worker.edit_chain)
        self.request_install_effect.connect(self.worker.install_effect)
        self.request_tempo.connect(self.worker.set_tempo)
        self.request_tuner.connect(self.worker.set_tuner)
        self.request_move_effect.connect(self.worker.move_effect)
        self.request_add_clip.connect(self.worker.add_clip)
        self.request_store.connect(self.worker.store)
        self.request_move_patches.connect(self.worker.move_patches)
        self.request_import_ir.connect(self.worker.import_ir)
        self.request_remove_effect.connect(self.worker.remove_effect)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.all_loaded.connect(self._on_all_loaded)
        self.worker.error.connect(self.show_error)
        self.worker.confirm_needed.connect(self._ask_conflict)
        self.editor_tab = EditorView(self)
        self.tabs.removeTab(0)
        self.tabs.insertTab(0, self.editor_tab, "Editor")
        import os
        from b6lab.pool import DEFAULT_ROOT
        pool_root = pool_root or os.environ.get("B6LAB_POOL") or DEFAULT_ROOT
        self.patches_tab = PatchesView(self, backup_root=backup_root, browse_root=browse_root,
                                       pool_root=pool_root)
        self.tabs.removeTab(1)
        self.tabs.insertTab(1, self.patches_tab, "Patches")
        self.effects_tab = EffectsView(self)
        self.tabs.removeTab(2)
        self.tabs.insertTab(2, self.effects_tab, "Effects")
        self.ir_tab = IRView(self)
        self.tabs.addTab(self.ir_tab, "Import IR")
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self._update_navigation)
        self._update_navigation(0)
        self.thread.finished.connect(self.worker.deleteLater)
        self.save_owner = None
        self.thread.start()

    def begin_save(self, owner):
        """Shared guard: only one save may be in flight, whichever view starts it.

        While a save is in flight no other view may start one, so the shared
        `saved` signal can only belong to the view that holds the guard.
        """
        if self.save_owner is not None:
            self.show_error("another save is in progress")
            return False
        self.save_owner = owner
        return True

    PAGES = {"EDITOR": 0, "PATCH": 1, "EFFECT": 2, "IMPORT IR": 4}

    def _update_navigation(self, index):
        for name, page in self.PAGES.items():
            if page == index:
                self.nav.select(name)

    def _nav_selected(self, name):
        if name in self.PAGES:
            self._select_navigation(self.PAGES[name])
        else:
            self._update_navigation(self.tabs.currentIndex())

    def _select_navigation(self, index):
        self.tabs.setCurrentIndex(index)
        self._update_navigation(index)

    def end_save(self, owner):
        if self.save_owner is owner:
            self.save_owner = None

    def start(self):
        self.request_connect.emit()

    def _say_hello(self):
        from b6lab.gui.gldialog import GLDialog, MessageContent
        GLDialog("B6 Lab", MessageContent("Hello from Tux!\nGuitar Lab for the ZOOM B6, on Linux."), self).exec()

    def reconnect(self):
        self.statusBar().showMessage("connecting...")
        self.request_connect.emit()

    def set_connected(self, ok, text=None):
        self.nav.set_connected(ok)
        self.light_label.setText(text or ("connected" if ok else "not connected"))

    def show_error(self, text):
        self.statusBar().showMessage(text)

    # save feedback ------------------------------------------------------------
    def report_saved(self, res):
        text = f"Saved and verified, previous version in {res.backup_file}"
        if res.message != "saved and verified":
            text += f" ({res.message})"
        self.statusBar().showMessage(text)

    def report_save_failed(self, res):
        if res.message == "cancelled":
            self.statusBar().showMessage("save cancelled, pedal untouched")
            return
        self.show_error(res.message)
        self.show_save_failed(res.message)

    def show_save_failed(self, text):
        """Dialog for a failed save. Overridden/monkeypatched in tests."""
        QMessageBox.warning(self, "Save failed", text)

    def editor_save_done(self, ok):
        """Called by the Editor when its save finished; completes a pending close."""
        if self._close_after_save:
            self._close_after_save = False
            if ok:
                self.close()

    def _on_connected(self, _ident):
        self.set_connected(True)
        self.statusBar().clearMessage()

    def _on_disconnected(self, reason):
        self.set_connected(False)
        self.statusBar().showMessage(reason)

    def _on_all_loaded(self, slots):
        self.slots = list(slots)

    def _ask_conflict(self):
        ans = QMessageBox.question(
            self, "Pedal changed",
            "This slot was changed on the pedal since it was loaded. Overwrite it anyway?")
        self.worker.answer_conflict(ans == QMessageBox.StandardButton.Yes)

    def shutdown(self):
        if self.thread.isRunning():
            self.worker.begin_close()
            QMetaObject.invokeMethod(self.worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
            self.thread.quit()
            self.thread.wait(5000)

    def ask_close_unsaved(self):
        """Return "save", "discard" or "cancel". Overridden/monkeypatched in tests."""
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText("The patch in the Editor has unsaved changes. Save it before closing?")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return {save: "save", discard: "discard"}.get(box.clickedButton(), "cancel")

    def closeEvent(self, event):
        ed = self.editor_tab
        if self.thread.isRunning() and isinstance(ed, EditorView) and ed.modified():
            if self._close_after_save:  # the save asked for is still running
                event.ignore()
                return
            answer = self.ask_close_unsaved()
            if answer == "cancel":
                event.ignore()
                return
            if answer == "save":
                event.ignore()
                self._close_after_save = True
                ed.save()
                if ed._saving is None:  # save refused (not connected, invalid name...)
                    self._close_after_save = False
                return
        self.shutdown()
        super().closeEvent(event)


FAKE_DIR = "fake"


def window_paths(fake, root=Path("backup")):
    """Backup folders for MainWindow: --fake never writes into the real backup folders."""
    root = Path(root)
    if fake:
        return {"backup_dir": root / FAKE_DIR / "overwritten", "backup_root": root / FAKE_DIR,
                "browse_root": root}
    return {"backup_dir": root / "overwritten", "backup_root": root, "browse_root": root}


def newest_backup_factory(root=Path("backup")):
    """FakeB6 loaded with the newest real backup set (sets made in --fake mode are ignored)."""
    from b6lab.fake import FakeB6
    from b6lab.library import list_backups
    root = Path(root)
    fake_root = (root / FAKE_DIR).resolve()
    sets = [s for s in list_backups(root)
            if fake_root != s.path.resolve() and fake_root not in s.path.resolve().parents]
    if not sets:
        raise SystemExit("no backup set found for --fake")
    newest = max(sets, key=lambda s: s.created)
    return lambda: FakeB6(newest.slots)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fake = "--fake" in argv
    if fake:
        factory = newest_backup_factory()
    else:
        from b6lab.midi import open_device
        factory = open_device
    app = QApplication(sys.argv[:1])
    win = MainWindow(factory, **window_paths(fake))
    win.show()
    win.start()
    return app.exec()
