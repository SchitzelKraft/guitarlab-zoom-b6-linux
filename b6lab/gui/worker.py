"""Device worker: all pedal I/O happens here, in its own QThread."""
import errno
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from b6lab.device import SaveResult
import b6lab.device as _device
from b6lab import ptcf
from b6lab.live import LiveError, compare_effects, set_effect_on
from b6lab.midi import DeviceBusy, NotConnected

BUSY_TEXT = "MIDI device is in use by another program"
NOT_CONNECTED_TEXT = "B6 not connected"


# errno values of a raw MIDI device that went away (unplugged, switched off).
LINK_ERRNOS = {errno.EIO, errno.ENODEV, errno.ENXIO, errno.EPIPE, errno.EBADF}


def is_link_error(exc) -> bool:
    """True when the exception means the MIDI link is gone.

    A timeout or a device-level I/O error counts. An OSError without such an errno
    (such as "pedal rejected the write", or a full disk while writing a backup file)
    does not: the pedal is still there.
    """
    return isinstance(exc, (TimeoutError, NotConnected)) or (
        isinstance(exc, OSError) and exc.errno in LINK_ERRNOS)


AUTO_SAVE_WAIT = 2.0   # FUN_100067910: AUTO SAVE goes back on 2000 ms after a clip drop

class DeviceWorker(QObject):
    connected = Signal(str)
    disconnected = Signal(str)
    slot_loaded = Signal(int, bytes)
    all_loaded = Signal(list)
    saved = Signal(object)
    error = Signal(str)
    confirm_needed = Signal()
    backup_done = Signal(str)
    # patch slot, effect entry, state the pedal reports (after a live on/off request)
    effect_state = Signal(int, int, bool)
    current_slot = Signal(int)  # the pedal's selected patch (33), read after all patches
    tempo = Signal(int)
    memory = Signal(float)  # share of effect memory in use (FFS Space, 60 29)  # patch tempo from the pedal's global data (64 0A -> 64 09)
    patches_moved = Signal(object)        # SaveResult of a patch move
    ir_imported = Signal(int, str)        # IR slot, name
    tuner_reading = Signal(object, int)   # note (CC 98, None before the first), pitch byte (CC 99)
    # what happens on the pedal itself (reported in sync mode)
    pedal_slot = Signal(int)              # the pedal switched to this patch
    pedal_switch = Signal(int, bool)      # effect entry, on
    pedal_param = Signal(int, int, int)   # effect entry, knob index, value
    tuner_calibration = Signal(int)       # Hz
    auto_save = Signal(bool)              # the pedal's AUTO SAVE (global data, or changed on it)
    # {effect ID: installed} from the pedal's FLST_SEQ.ZT2 (read at connect, and after a change)
    effects_installed = Signal(object)
    # patch slot, the pedal's edit buffer after a TYPE change, an ADD or a DELETE
    type_changed = Signal(int, bytes)
    clip_added = Signal(object, int, bytes)   # SaveResult, patch slot, the patch written
    # patch slot, differences between the pedal's edit buffer and the editor (empty = in sync)
    live_checked = Signal(int, list)

    def __init__(self, factory, backup_dir=Path("backup/overwritten"), conflict_timeout=60.0):
        super().__init__()
        self._factory = factory
        self._backup_dir = Path(backup_dir)
        self._conflict_timeout = conflict_timeout
        self._dev = None
        self._answer = False
        self._answered = threading.Event()
        self._closing = threading.Event()
        self._effect_list = None  # the pedal's FLST_SEQ.ZT2
        self._events = None

    # conflict confirmation -------------------------------------------------
    def answer_conflict(self, ok: bool):
        self._answer = bool(ok)
        self._answered.set()

    def begin_close(self):
        """Thread-safe: call from any thread before stopping the worker."""
        self._closing.set()
        self._answer = False
        self._answered.set()

    def _confirm_conflict(self) -> bool:
        if self._closing.is_set():
            return False
        self._answered.clear()
        self._answer = False
        if self._closing.is_set():
            return False
        self.confirm_needed.emit()
        if not self._answered.wait(self._conflict_timeout) or self._closing.is_set():
            return False
        return self._answer

    # helpers ---------------------------------------------------------------
    def _lost(self, exc):
        self._close()
        self.disconnected.emit(f"B6 connection lost: {exc}")

    def _failed(self, exc, text):
        if is_link_error(exc):
            self._lost(exc)
        else:
            self.error.emit(text)

    def _close(self):
        if self._events is not None:
            self._events.stop()
        if self._dev is not None:
            try:
                if getattr(self._dev, "sync", False):
                    self._dev.leave_sync()   # Guitar Lab: 51 when it closes
            except Exception:
                pass
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    @Slot()
    def shutdown(self):
        self.begin_close()
        self._close()

    # slots -----------------------------------------------------------------
    @Slot()
    def connect_device(self):
        self._close()
        try:
            dev = self._factory()
        except DeviceBusy:
            self.disconnected.emit(BUSY_TEXT)
            return
        except NotConnected:
            self.disconnected.emit(NOT_CONNECTED_TEXT)
            return
        except Exception as e:
            self.disconnected.emit(f"B6 not connected: {e}")
            return
        try:
            ident = dev.identity()
        except Exception as e:
            try:
                dev.close()
            except Exception:
                pass
            self.disconnected.emit(f"B6 not responding: {e}")
            return
        self._dev = dev
        try:
            dev.enter_sync()   # Guitar Lab: 50 right after the identity, for the whole session
        except Exception:
            pass               # transports / fakes without sync mode
        self._start_events()
        self.connected.emit(bytes(ident).hex())
        try:
            info = dev.global_info()
            self.tempo.emit(int(info["tempo"]))
            self.auto_save.emit(bool(info.get("auto_save")))
        except Exception:
            pass  # older transports and fakes have no global data
        try:
            self.memory.emit(float(dev.memory_usage()))
        except Exception:
            pass  # unknown: the EFFECT page keeps showing 0 %
        self._effect_list = None
        try:
            self._effect_list = bytes(dev.read_effect_list())   # Guitar Lab does this at connect
            self.effects_installed.emit(self._installed_map())
        except Exception:
            pass  # unknown: every effect is shown as installed
        self.read_all()

    @Slot(int)
    def load_slot(self, slot):
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            data = bytes(self._dev.read_slot(slot))
        except Exception as e:
            self._failed(e, f"read slot {slot + 1} failed: {e}")
            return
        self.slot_loaded.emit(slot, data)

    @Slot(int, bytes, bytes)
    def save(self, slot, new_data, loaded_data, store_edit=False):
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            self.saved.emit(SaveResult(False, NOT_CONNECTED_TEXT, None))
            return
        try:
            res = _device.save_slot(self._dev, slot, new_data, loaded_data or None,
                                    self._backup_dir, self._confirm_conflict, store_edit)
        except Exception as e:
            res = SaveResult(False, f"save failed: {e}", None, e)
            self.error.emit(res.message)
        self.saved.emit(res)
        if res.error is not None and is_link_error(res.error):
            self._lost(res.error)

    @Slot(int)
    def store(self, slot):
        """AUTO SAVE on: the silent Store before making or dropping a clip (FUN_100067550 /
        FUN_100067910): only Patch Save `64 0D` for the current patch, no write."""
        if self._dev is None:
            return
        try:
            self._dev.store_edit(slot)
        except Exception as e:
            self._failed(e, f"store failed: {e}")

    @Slot(int)
    def select(self, slot):
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            self._dev.select_slot(slot)
        except Exception as e:
            self._failed(e, f"select slot {slot + 1} failed: {e}")

    @Slot(int, int, bool, object)
    def set_effect_on(self, patch_slot, effect_slot, on, fx_ids):
        """Switch an effect live on the pedal's current patch (see b6lab/live.py)."""
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            state = set_effect_on(self._dev, effect_slot, on, fx_ids)
        except LiveError as e:
            self.error.emit(f"live on/off: {e}")
            if e.state is not None:
                self.effect_state.emit(patch_slot, effect_slot, bool(e.state))
            return
        except Exception as e:
            self._failed(e, f"live on/off failed: {e}")
            return
        self.effect_state.emit(patch_slot, effect_slot, bool(state))

    @Slot(int, int, int)
    def set_param_live(self, effect_slot, index, value):
        """Send one knob value to the pedal's edit buffer (b6lab/live.py); no read-back."""
        if self._dev is None:
            return
        try:
            self._dev.set_param(effect_slot, effect_slot, index, value)
        except Exception as e:
            self._failed(e, f"live knob failed: {e}")

    # effects on the pedal ------------------------------------------------------------
    def _installed_map(self):
        from b6lab import effect_files, ffs, effects
        by_file = ffs.installed(self._effect_list or b"")
        out = {}
        for fx_id in effects.catalog():
            name = effect_files.module_file(fx_id)
            if name in by_file:
                out[fx_id] = by_file[name]
        return out

    def _effect_change(self, fx_id, install):
        from b6lab import effect_files, ffs
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        base = effect_files.base_name(fx_id)
        if base is None or self._effect_list is None:
            self.error.emit("the pedal's effect list is not known; nothing changed")
            return
        try:
            if install:
                zd2, zic = effect_files.find_zd2(base), effect_files.find_zic(base)
                if zd2 is None or zic is None:
                    self.error.emit(f"no copy of {base}.ZD2 / .ZIC on this computer; nothing changed")
                    return
                new, space = self._dev.install_effect(base, zd2, zic, self._effect_list)
            else:
                # keep copies first, so "Load to Device" can always bring it back
                for name, find in ((f"{base}.ZD2", effect_files.find_zd2), (f"{base}.ZIC", effect_files.find_zic)):
                    if find(base) is None:
                        effect_files.keep(base, name, self._dev.read_file(name))
                if effect_files.find_zd2(base) is None or effect_files.find_zic(base) is None:
                    self.error.emit(f"could not keep a copy of {base}; nothing deleted")
                    return
                new, space = self._dev.remove_effect(base, self._effect_list)
        except Exception as e:
            self._failed(e, f"effect {'load' if install else 'delete'} failed: {e}")
            return
        self._effect_list = bytes(new)
        self.effects_installed.emit(self._installed_map())
        share = ffs.memory_share(space)
        if share is None:
            try:
                share = float(self._dev.memory_usage())
            except Exception:
                share = None
        if share is not None:
            self.memory.emit(share)

    @Slot(bool)
    def set_tuner(self, on):
        """TUNER on / off; while on, the readings are polled and sent to the editor."""
        from PySide6.QtCore import QTimer
        if self._dev is None:
            return
        try:
            self._dev.tuner(on)
            if on:
                self.tuner_calibration.emit(int(self._dev.calibration()))
        except Exception as e:
            self._failed(e, f"tuner failed: {e}")
            return

    # what the pedal reports on its own (sync mode) -------------------------------------------
    def _start_events(self):
        from PySide6.QtCore import QTimer
        if self._events is None:
            self._events = QTimer(self)
            self._events.setInterval(30)
            self._events.timeout.connect(self._poll_events)
        self._bank = 0
        self._note = None
        self._events.start()

    def _poll_events(self):
        if self._dev is None or not hasattr(self._dev, "poll_messages"):
            return
        try:
            sx, ch = self._dev.poll_messages()
        except Exception as e:
            self._events.stop()
            self._failed(e, f"lost the pedal: {e}")
            return
        from b6lab.codec import from7
        reading = None
        for m in ch:
            kind = m[0] & 0xF0
            if kind == 0xB0 and len(m) == 3:
                if m[1] == 0x20:
                    self._bank = m[2]
                elif m[1] == 98:
                    self._note = m[2]
                elif m[1] == 99:
                    reading = (self._note, m[2])
            elif kind == 0xC0 and len(m) == 2:
                self.pedal_slot.emit(self._bank * 4 + m[1])
        if reading is not None:
            self.tuner_reading.emit(*reading)
        for m in sx:
            # 64 20 00 <entry> <param> <value:5> (done on the pedal, recorded 2026-11-10) or
            # 64 20 01 ... (the pedal's answer to the app's own edit): footswitch (param 0) or
            # knob (param 2+); entry 0x64 is the position message before it
            if m[:5] == bytes([0x52, 0x00, 0x6E, 0x64, 0x20]) and m[5] in (0, 1) and len(m) >= 13:
                entry, param, value = m[6], m[7], from7(m[8:13])
                if entry == 0x64 and param == 0x0F:
                    # FUN_100035ac0: module 100, param 0x0F updates the AUTO SAVE flag
                    self.auto_save.emit(bool(value))
                    continue
                if entry >= 0x5A:
                    continue   # position / footswitch / global echoes of our own messages
                if param == 0:
                    self.pedal_switch.emit(entry, bool(value))
                elif param >= 2:
                    self.pedal_param.emit(entry, param - 2, value)

    @Slot(int)
    def set_tempo(self, bpm):
        """TAP / typed BPM: the pedal's tempo (global), as Guitar Lab sends it."""
        if self._dev is None:
            return
        try:
            self._dev.set_tempo(bpm)
        except Exception as e:
            self._failed(e, f"tempo failed: {e}")
            return
        self.tempo.emit(int(bpm))

    @Slot(int)
    def install_effect(self, fx_id):
        """"Load to Device" (recorded from Guitar Lab; b6lab/ffs.py)."""
        self._effect_change(fx_id, True)

    @Slot(int)
    def remove_effect(self, fx_id):
        """"Delete from Device" (recorded from Guitar Lab; b6lab/ffs.py)."""
        self._effect_change(fx_id, False)

    @Slot(int, int, int)
    def move_effect(self, patch_slot, src, dst):
        """Chain drag (64 20 00 64 09 <src> <dst>), then the edit buffer back."""
        if self._dev is None:
            return
        try:
            self._dev.move_effect(src, dst)
            data = bytes(self._dev.read_edit())
        except Exception as e:
            self._failed(e, f"effect move failed: {e}")
            return
        self.type_changed.emit(patch_slot, data)

    @Slot(int, bytes, object, bool)
    def add_clip(self, slot, new_data, plan=None, auto_save=False):
        """A clip dropped into the chain (recorded from Guitar Lab, 2026-11-10): the whole patch
        with the clip's effects is written to its slot at once (64 0E, 45, 64 0F), the slot is
        selected (CC0 / CC32 / PC) and the edit buffer read (64 13). B6 Lab backs the slot up
        and reads it back first, as for a save.
        `plan` = (deletes, clip, entry): when the chain needs room, Guitar Lab first deletes
        empty entries live (FUN_1002b0fb0, highest first, `64 20 00 64 08 <entry>`) and then
        writes the pedal's own patch after those deletes with the clip inserted at `entry`."""
        from b6lab import clipboard
        if self._dev is None:
            self.clip_added.emit(SaveResult(False, NOT_CONNECTED_TEXT, None), slot, b"")
            return
        deletes, clip, entry = plan if plan else ([], None, 0)
        if auto_save:
            # FUN_100067910 with AUTO SAVE on: off for the insert, on again 2 s after it
            try:
                self._dev.set_auto_save(False)
            except Exception as e:
                self._failed(e, f"AUTO SAVE off failed: {e}")
                self.clip_added.emit(SaveResult(False, f"AUTO SAVE off failed: {e}", None, e), slot, b"")
                return
        try:
            self._add_clip(slot, new_data, deletes, clip, entry)
        finally:
            if auto_save and self._dev is not None:
                time.sleep(AUTO_SAVE_WAIT)
                try:
                    self._dev.set_auto_save(True)
                except Exception as e:
                    self._failed(e, f"AUTO SAVE on failed: {e}")

    def _add_clip(self, slot, new_data, deletes, clip, entry):
        from b6lab import clipboard
        if deletes:
            try:
                for k in deletes:
                    self._dev.delete_effect(k)
                patch = ptcf.parse(bytes(self._dev.read_edit()))
            except Exception as e:
                self._failed(e, f"deleting empty effects failed: {e}")
                self.clip_added.emit(SaveResult(False, f"deleting empty effects failed: {e}", None, e),
                                     slot, b"")
                return
            if not clipboard.insert_clip(patch, clip, min(entry, len(patch.effects))):
                msg = "the clip does not fit the pedal's patch"
                self.error.emit(msg)
                self.clip_added.emit(SaveResult(False, msg, None), slot, b"")
                return
            new_data = ptcf.encode(patch)
        res = _device.save_slot(self._dev, slot, new_data, None, self._backup_dir, lambda: True)
        if res.ok:
            try:
                self._dev.read_edit()
            except Exception as e:
                self._failed(e, f"reading the edit buffer failed: {e}")
        else:
            self.error.emit(res.message)
        self.clip_added.emit(res, slot, new_data if res.ok else b"")
        if res.error is not None and is_link_error(res.error):
            self._lost(res.error)

    @Slot(object, object)
    def move_patches(self, moved, writes):
        """A patch moved in the list: Guitar Lab's sequence (B6.move_patches). B6 Lab backs up
        every slot it rewrites first and reads them back afterwards."""
        from b6lab.device import SaveResult, _backup_path, _safe_name, used_bytes
        if self._dev is None:
            self.patches_moved.emit(SaveResult(False, NOT_CONNECTED_TEXT, None))
            return
        try:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            last = None
            for slot, _data in writes:
                current = bytes(self._dev.read_slot(slot))
                last = _backup_path(self._backup_dir, slot, _safe_name(current))
                last.write_bytes(current)
            self._dev.move_patches(moved, writes)
            bad = [slot for slot, data in writes
                   if used_bytes(bytes(self._dev.read_slot(slot))) != used_bytes(data)]
        except Exception as e:
            self.patches_moved.emit(SaveResult(False, f"move failed: {e}", None, e))
            if is_link_error(e):
                self._lost(e)
            return
        if bad:
            self.patches_moved.emit(SaveResult(False, f"verify failed for slots {bad}", last))
        else:
            self.patches_moved.emit(SaveResult(True, "moved and verified", last))

    @Slot(int, str, bytes)
    def import_ir(self, slot, name, wav):
        """IMPORT IR: Guitar Lab's sequence (b6lab/ffs.import_ir)."""
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            self._dev.import_ir(slot, name, wav)
        except Exception as e:
            self._failed(e, f"IR import failed: {e}")
            return
        self.ir_imported.emit(slot, name[:9])

    @Slot(int, bytes, bytes)
    def save_edit(self, slot, new_data, loaded_data):
        """The editor's SAVE: Patch Save (64 0D) + the write, as Guitar Lab."""
        self.save(slot, new_data, loaded_data, True)

    @Slot(int, int, int)
    def change_type(self, patch_slot, effect_slot, fx_id):
        """Change an effect's type live (TYPE picker), then read the edit buffer back: Guitar
        Lab waits for the pedal's 64 12 after the change; the editor takes the new effects."""
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            self._dev.change_type(effect_slot, fx_id)
            data = bytes(self._dev.read_edit())
        except Exception as e:
            self._failed(e, f"effect type change failed: {e}")
            return
        self.type_changed.emit(patch_slot, data)

    @Slot(int, str, int)
    def edit_chain(self, patch_slot, op, position):
        """ADD ("insert") or DELETE ("delete") an effect entry live, then read the edit buffer
        back (the pedal decides; an insert into a full patch changes nothing)."""
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            if op == "insert":
                self._dev.insert_effect(position)
            else:
                self._dev.delete_effect(position)
            data = bytes(self._dev.read_edit())
        except Exception as e:
            self._failed(e, f"effect {op} failed: {e}")
            return
        self.type_changed.emit(patch_slot, data)

    @Slot(int, bytes)
    def check_live(self, patch_slot, patch_data):
        """Compare the pedal's edit buffer with the editor's patch (effects and knobs)."""
        if self._dev is None:
            return
        try:
            diffs = compare_effects(self._dev, ptcf.parse(patch_data))
        except LiveError as e:
            diffs = [str(e)]
        except Exception as e:
            self._failed(e, f"live check failed: {e}")
            return
        if diffs:
            more = f" (+{len(diffs) - 3} more)" if len(diffs) > 3 else ""
            self.error.emit("pedal differs from the editor: " + "; ".join(diffs[:3]) + more)
        self.live_checked.emit(patch_slot, diffs)

    @Slot()
    def read_all(self):
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            n = min(240, self._dev.patch_count())
            slots = [bytes(self._dev.read_slot(i)) for i in range(n)]
        except Exception as e:
            self._failed(e, f"read all failed: {e} (use Reconnect to try again)")
            return
        self.all_loaded.emit(slots)
        try:
            self.current_slot.emit(int(self._dev.selected_slot()))
        except Exception:
            pass  # Guitar Lab opens the pedal's current patch; without an answer nothing opens

    @Slot(str)
    def backup_all(self, root):
        if self._dev is None:
            self.error.emit(NOT_CONNECTED_TEXT)
            return
        try:
            from b6lab.library import backup_all
            bs = backup_all(self._dev, Path(root))
        except Exception as e:
            self._failed(e, f"backup failed: {e}")
            return
        self.backup_done.emit(str(bs.path))
