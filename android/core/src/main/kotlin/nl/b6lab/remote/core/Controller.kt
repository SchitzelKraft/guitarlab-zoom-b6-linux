package nl.b6lab.remote.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.Locale

/** One pedal of the board. [slot] is the chain entry index (what the session operations take). */
data class PedalView(val slot: Int, val fx: EffectInfo?, val on: Boolean, val selected: Boolean)

data class KnobView(val index: Int, val name: String, val value: Int, val max: Int, val text: String)

data class BoardUi(
    /** "BANK 01 · B", empty while no patch is known. */
    val header: String,
    val name: String,
    val connected: Boolean,
    /** Tails of double-width effects are not shown. */
    val pedals: List<PedalView>,
    /** 0 when the chain has 6 entries or no effect of the catalogue fits. */
    val freePlaces: Int,
    val knobs: List<KnobView>,
    val canSave: Boolean,
    val autoSaveWarning: Boolean,
    val error: String?,
)

/**
 * Turns [B6Session] state into what the board shows and taps and drags into session operations. Every operation
 * passes the [PatchRef] of the state this controller last rendered, never a fresh one, so the session refuses it
 * when the pedal moved on in the meantime.
 */
class RemoteController(
    private val scope: CoroutineScope,
    private val session: B6Session,
    private val catalog: Catalog,
) {
    companion object {
        const val KNOB_THROTTLE_MS = 30L
        const val PATCHES = 240
        private val LETTERS = "ABCD"
    }

    private val lock = Any()
    private var lastState = PedalState()
    private var shownRef: PatchRef? = null
    private var selected = 0

    private val _ui = MutableStateFlow(build())
    val ui: StateFlow<BoardUi> = _ui.asStateFlow()

    /** A knob value as dragged: what the screen showed (ref, entry) when the finger moved. */
    private data class Drag(val value: Int, val ref: PatchRef, val entry: Int)

    private val latest = HashMap<Int, Drag>()
    private var freeRef: PatchRef? = null
    private var freeCached = 0
    private val sending = HashMap<Int, Job>()

    init {
        scope.launch { session.state.collect { s -> synchronized(lock) { lastState = s; publish() } } }
    }

    // ---- user actions -----------------------------------------------------------------------

    /** Selects the pedal (nothing is sent); switching it on or off is [togglePedal]. */
    fun tapPedal(slot: Int) {
        synchronized(lock) {
            if (_ui.value.pedals.none { it.slot == slot }) return
            selected = slot
            publish()
        }
    }

    /** Switches the effect at [slot] on or off; the selection stays where it is. */
    fun togglePedal(slot: Int) {
        val ref = synchronized(lock) {
            if (_ui.value.pedals.none { it.slot == slot }) return
            shownRef
        } ?: return
        scope.launch { session.toggle(ref, slot) }
    }

    /** Sets knob [index] of the selected effect; at most one send per [KNOB_THROTTLE_MS], the last value always goes. */
    fun dragKnob(index: Int, value: Int) {
        synchronized(lock) {
            val knob = _ui.value.knobs.firstOrNull { it.index == index } ?: return
            val ref = shownRef ?: return
            latest[index] = Drag(value.coerceIn(0, knob.max), ref, selected)
            if (sending[index]?.isActive == true) return
            sending[index] = scope.launch { sendLatest(index) }
        }
    }

    private suspend fun sendLatest(index: Int) {
        var sent: Drag? = null
        while (true) {
            delay(KNOB_THROTTLE_MS)
            val next = synchronized(lock) {
                val d = latest[index]
                if (d == null || d == sent) {
                    // decided and unregistered in one step: a drag arriving now starts a new job
                    sending.remove(index)
                    null
                } else d
            } ?: return
            sent = next
            session.setKnob(next.ref, next.entry, index, next.value)
        }
    }

    /** With [replaceSlot] changes that entry's type, otherwise adds [fxId] at the end of the chain. */
    fun choose(fxId: Int, replaceSlot: Int?, expected: PatchRef? = null) {
        if (!fits(fxId, replaceSlot)) return
        val (shown, count) = synchronized(lock) { shownRef to (lastState.edit?.effects?.size ?: 0) }
        val ref = expected ?: shown
        if (ref == null) return
        scope.launch {
            if (replaceSlot != null) {
                session.changeType(ref, replaceSlot, fxId)
                return@launch
            }
            session.insert(ref, count)
            if (session.state.value.error != null) return@launch
            // the chain changed by our own insert: continue from the session's new state
            val now = session.state.value.ref ?: return@launch
            session.changeType(now, count, fxId)
            synchronized(lock) {
                if (lastState.ref?.slot == now.slot && _ui.value.pedals.any { it.slot == count }) {
                    selected = count
                    publish()
                }
            }
        }
    }

    /** Whether [fxId] fits the shown patch (as a new entry, or replacing entry [replaceSlot]); false without a patch. */
    fun fits(fxId: Int, replaceSlot: Int?): Boolean {
        val edit = synchronized(lock) { lastState.edit } ?: return false
        return catalog.fits(edit, fxId, replaceSlot)
    }

    /** The patch the board shows now; a chooser keeps the one it was opened on and passes it as `expected`. */
    fun currentRef(): PatchRef? = synchronized(lock) { shownRef }

    fun remove(slot: Int, expected: PatchRef? = null) {
        val ref = expected ?: synchronized(lock) { shownRef } ?: return
        scope.launch { session.delete(ref, slot) }
    }

    fun move(src: Int, dst: Int) {
        val ref = synchronized(lock) { shownRef } ?: return
        scope.launch { session.move(ref, src, dst) }
    }

    fun previousPatch() = step(-1)

    fun nextPatch() = step(1)

    private fun step(delta: Int) {
        val slot = synchronized(lock) { lastState.slot } ?: return
        scope.launch { session.selectSlot(((slot + delta) % PATCHES + PATCHES) % PATCHES) }
    }

    fun save() {
        val ref = synchronized(lock) { shownRef } ?: return
        scope.launch { session.save(ref) }
    }

    // ---- rendering --------------------------------------------------------------------------

    /** Call with [lock] held. */
    private fun publish() {
        val ref = lastState.ref
        if (ref != shownRef) {
            val effects = lastState.edit?.effects.orEmpty()
            val firstShown = effects.firstOrNull { !it.isTail }?.slot ?: 0
            if (ref?.slot != shownRef?.slot) {
                // another patch: the selection starts again at the first pedal, pending knob values are dropped
                selected = firstShown
                latest.clear()
            } else if (effects.none { it.slot == selected && !it.isTail }) {
                // same patch, the chain changed: the nearest shown pedal before the selection, else the first
                selected = effects.lastOrNull { it.slot < selected && !it.isTail }?.slot ?: firstShown
            }
            shownRef = ref
        }
        _ui.value = build()
    }

    private fun build(): BoardUi {
        val s = lastState
        val edit = s.edit
        val connected = s.connection == Connection.CONNECTED
        val effects = edit?.effects.orEmpty()
        val pedals = effects.filter { !it.isTail }
            .map { PedalView(it.slot, catalog.effects[it.fxId], it.on, it.slot == selected) }
        val ref = s.ref
        if (ref != freeRef) {
            freeRef = ref
            freeCached = if (edit == null || effects.size >= Ptcf.MAX_ENTRIES ||
                catalog.effects.keys.none { catalog.fits(edit, it) }
            ) 0 else Ptcf.MAX_ENTRIES - effects.size
        }
        val free = freeCached
        return BoardUi(
            header = s.slot?.let { "BANK %02d · %c".format(Locale.ROOT, it / 4 + 1, LETTERS[it % 4]) } ?: "",
            name = edit?.name ?: "",
            connected = connected,
            pedals = pedals,
            freePlaces = free,
            knobs = knobsOf(effects.firstOrNull { it.slot == selected && !it.isTail }),
            canSave = connected && s.dirty && edit != null,
            autoSaveWarning = connected && s.autoSave,
            error = s.error,
        )
    }

    private fun knobsOf(e: Effect?): List<KnobView> {
        val info = e?.let { catalog.effects[it.fxId] } ?: return emptyList()
        return info.params.mapIndexedNotNull { i, p ->
            if (!e.editable(i) || i >= e.params.size) return@mapIndexedNotNull null
            val v = e.params[i]
            KnobView(i, p.name, v, p.rawMax ?: e.maxValue(i), p.display(v))
        }
    }
}
