package nl.b6lab.remote.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

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

    private val latest = HashMap<Int, Int>()
    private val sending = HashMap<Int, Job>()

    init {
        scope.launch { session.state.collect { s -> synchronized(lock) { lastState = s; publish() } } }
    }

    // ---- user actions -----------------------------------------------------------------------

    /** First tap on an unselected pedal selects it (nothing is sent); a tap on the selected one switches it. */
    fun tapPedal(slot: Int) {
        val ref = synchronized(lock) {
            if (slot != selected) {
                selected = slot
                publish()
                return
            }
            shownRef
        } ?: return
        scope.launch { session.toggle(ref, slot) }
    }

    /** Sets knob [index] of the selected effect; at most one send per [KNOB_THROTTLE_MS], the last value always goes. */
    fun dragKnob(index: Int, value: Int) {
        synchronized(lock) {
            val knob = _ui.value.knobs.firstOrNull { it.index == index } ?: return
            latest[index] = value.coerceIn(0, knob.max)
            if (sending[index]?.isActive == true) return
            sending[index] = scope.launch { sendLatest(index) }
        }
    }

    private suspend fun sendLatest(index: Int) {
        var sent: Int? = null
        while (true) {
            delay(KNOB_THROTTLE_MS)
            val (value, ref, entry) = synchronized(lock) {
                Triple(latest[index], shownRef, selected)
            }
            if (value == null || value == sent || ref == null) break
            sent = value
            session.setKnob(ref, entry, index, value)
        }
        synchronized(lock) { sending.remove(index) }
    }

    /** With [replaceSlot] changes that entry's type, otherwise adds [fxId] at the end of the chain. */
    fun choose(fxId: Int, replaceSlot: Int?) {
        val (ref, count) = synchronized(lock) { shownRef to (lastState.edit?.effects?.size ?: 0) }
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
        }
    }

    fun remove(slot: Int) {
        val ref = synchronized(lock) { shownRef } ?: return
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
            // another patch (or chain): the selection starts again at the first pedal
            selected = lastState.edit?.effects?.firstOrNull { !it.isTail }?.slot ?: 0
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
        val free = if (edit == null || effects.size >= Ptcf.MAX_ENTRIES ||
            catalog.effects.keys.none { catalog.fits(edit, it) }
        ) 0 else Ptcf.MAX_ENTRIES - effects.size
        return BoardUi(
            header = s.slot?.let { "BANK %02d · %c".format(it / 4 + 1, LETTERS[it % 4]) } ?: "",
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
            KnobView(i, p.name, v, p.rawMax ?: e.maxValue(i), p.format(v))
        }
    }
}
