package nl.b6lab.remote.core

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ClosedReceiveChannelException
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

enum class Connection { DISCONNECTED, CONNECTING, CONNECTED }

/** The patch the screen showed when the user acted: slot and effect IDs of every entry (tails included). */
data class PatchRef(val slot: Int, val fxIds: List<Int>)

data class PedalState(
    val connection: Connection = Connection.DISCONNECTED,
    /** The selected patch slot (0..239). */
    val slot: Int? = null,
    /** The pedal's edit buffer as last read. */
    val edit: Patch? = null,
    /** The edit buffer differs from the stored slot. */
    val dirty: Boolean = false,
    /** The pedal's AUTO SAVE is on (it stores edits by itself). */
    val autoSave: Boolean = false,
    /** PC mode (`50`) is on: the pedal reports changes itself; otherwise the session polls. */
    val pcMode: Boolean = false,
    /** Short English message about the last failure, null after a successful operation. */
    val error: String? = null,
) {
    /** What the screen shows now; pass it to the live operations, which refuse when the pedal moved on. */
    val ref: PatchRef? get() = if (slot != null && edit != null) PatchRef(slot, edit.effects.map { it.fxId }) else null
}

/**
 * One connection to a B6. Ports B6 Lab's protocol (b6lab/midi.py, b6lab/live.py): PC mode, following the pedal,
 * live edits and save. Every message goes through [Safety.check]; every edit dump (`64 12`) is acknowledged.
 *
 * Live operations and save take the [PatchRef] the screen showed and refuse ("patch changed on the pedal")
 * when the pedal is on another patch. Operations are serialized by a mutex and never throw: failures land in [PedalState.error]. A session is used
 * once: after [disconnect] or a lost link (transport closed, or no reply within 3 s) make a new one.
 */
class B6Session(private val scope: CoroutineScope, private val transport: MidiTransport) {
    companion object {
        const val REQUEST_TIMEOUT_MS = 3000L
        /** b6lab/midi.py store_edit waits up to 10 s for the `45` answer in PC mode. */
        const val STORE_TIMEOUT_MS = 10_000L
        const val POLL_MS = 750L
        const val PARAM_DEBOUNCE_MS = 150L
        /** b6lab/midi.py waits: after each press/release pair, after a chain edit, after a store. */
        const val PRESS_WAIT_MS = 50L
        const val EDIT_WAIT_MS = 250L
        const val STORE_WAIT_MS = 100L

        private val HDR = byteArrayOf(0x52, 0x00, 0x6E)
        private val SOLICITED_DUMP = HDR + byteArrayOf(0x64, 0x12, 0x01)
        private val UNSOLICITED_DUMP = HDR + byteArrayOf(0x64, 0x12, 0x00)
        private val EDIT_DUMP = HDR + byteArrayOf(0x64, 0x12)
        private val GLOBAL_REPLY = HDR + byteArrayOf(0x64, 0x09)
        /** Any stored-patch answer (`45`): b6lab/midi.py store_edit waits for this prefix only. */
        private val STORE_REPLY = HDR + byteArrayOf(0x45)
        private val RESPONSE = HDR + byteArrayOf(0x00)
        private const val BUSY = 0x11
        private const val SLOT_SIZE = 808
        private const val PATCH_CHANGED = "patch changed on the pedal"
        /** How [Safety.check] messages start. */
        private const val SAFETY_REJECTION = "blocked pedal message"

        private fun ByteArray.startsWith(p: ByteArray) = size >= p.size && p.indices.all { this[it] == p[it] }
        private fun slotReply(slot: Int) = HDR + byteArrayOf(0x45, 0, 0, (slot / 4).toByte(), 0, (slot % 4).toByte(), 0)
        private fun isError(b: ByteArray) = b.size >= 5 && b.startsWith(RESPONSE) && b[4].toInt() != 0
    }

    /** The link is gone: transport closed, send failed or the pedal stopped answering. */
    private class LinkLost(message: String) : Exception(message)

    /** An operation the pedal or the session refused; the message goes to [PedalState.error]. */
    private class Refused(message: String) : Exception(message)

    private class Pending(val accept: (MidiMessage) -> Boolean) {
        val replies = Channel<MidiMessage>(Channel.UNLIMITED)
    }

    private val _state = MutableStateFlow(PedalState())
    val state: StateFlow<PedalState> = _state.asStateFlow()

    private val mutex = Mutex()
    private val sendLock = Any()

    @Volatile private var pending: Pending? = null
    /** The selected slot as stored on the pedal: the baseline for [PedalState.dirty]. */
    @Volatile private var stored: ByteArray? = null
    @Volatile private var ended = false
    /** Parent of the read loop, the push followers and the poller. */
    private val work = SupervisorJob(scope.coroutineContext[Job])
    /** Patch-change pushes: (number of the push, slot). */
    private val patchPushes = Channel<Pair<Int, Int>>(Channel.UNLIMITED)

    /** Patch-change pushes counted by the read loop as they arrive (no mutex needed), and how many are loaded. */
    @Volatile private var pushesArrived = 0
    @Volatile private var pushesLoaded = 0
    /** The slot of the last patch-change push, or of our own [selectSlot] in PC mode; null before either. */
    @Volatile private var pushedSlot: Int? = null
    private val paramPushes = Channel<Unit>(Channel.CONFLATED)

    // ---- public operations ------------------------------------------------------------------

    /** Identity, PC mode (or polling when busy), AUTO SAVE, selected slot, edit buffer, stored slot. */
    suspend fun connect(): Unit = mutex.withLock {
        if (_state.value.connection != Connection.DISCONNECTED) return
        if (ended) {
            _state.update { it.copy(error = "connection closed") }
            return
        }
        _state.value = PedalState(connection = Connection.CONNECTING)
        scope.launch(work) { readLoop() }
        try {
            val id = sysexRequest(Msg.IDENTITY, byteArrayOf(0x7E))
            if (id.size < 9 || id[7].toInt() != 0x1A || id[8].toInt() != 0x00) throw Refused("not a B6")
            val pc = when (val code = ackRequest(Msg.ENTER_PC)) {
                0 -> true
                BUSY -> false
                else -> throw Refused("pedal returned error 0x%02X".format(code))
            }
            val autoSave = parseAutoSave(sysexRequest(Msg.GLOBAL, GLOBAL_REPLY))
            val slot = selectedSlot()
            val edit = readEdit()
            stored = readStored(slot)
            _state.value = PedalState(Connection.CONNECTED, slot, edit, isDirty(edit), autoSave, pc, null)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            lose(e.message ?: "connection failed")
            return
        }
        startFollowing()
    }

    /** Leaves PC mode (`51`) and closes the transport. */
    suspend fun disconnect(): Unit = mutex.withLock {
        if (_state.value.connection == Connection.DISCONNECTED) return
        ended = true
        if (_state.value.pcMode) {
            try {
                ackRequest(Msg.LEAVE_PC)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // closing anyway
            }
        }
        stop()
        _state.update { it.copy(connection = Connection.DISCONNECTED, pcMode = false, error = null) }
    }

    /** Bank select + program change, then the new patch is read. Unsaved changes are dropped. */
    suspend fun selectSlot(slot: Int) = op {
        // in PC mode the pedal follows our own selection, whether or not it announces it with a push (without PC mode
        // there are no pushes: the poller reads the slot)
        if (_state.value.pcMode) pushedSlot = slot
        sendAll(Msg.selectSlot(slot))
        load(slot)
    }

    /** Switches effect entry [slot] (b6lab/live.py set_effect_on, with the undo of an unexpected toggle). */
    suspend fun toggle(expected: PatchRef, slot: Int) = op { toggleEffect(expected, slot) }

    /**
     * Knob [index] of effect entry [slot] (b6lab/live.py send_param). No edit-buffer read per step: in PC mode the
     * pushes keep [state] current, so [expected] is checked against it (without PC mode one read per call). The
     * new value is shown at once; one confirming read follows [PARAM_DEBOUNCE_MS] after the last step.
     */
    suspend fun setKnob(expected: PatchRef, slot: Int, index: Int, value: Int) = op {
        checkRef(expected)
        val now = if (_state.value.pcMode) _state.value.edit!! else checkedEdit(expected)
        val pos = positionOf(now, slot)
        if (!now.effects[slot].editable(index)) throw Refused("knob ${index + 1} of effect entry $slot is not editable")
        sendAll(Msg.setParam(pos, index, value))
        setEdit(Ptcf.parse(Ptcf.encode(Ptcf.setParam(now, slot, index, value)).copyOf(SLOT_SIZE)))
        paramPushes.trySend(Unit)
    }

    suspend fun changeType(expected: PatchRef, slot: Int, fxId: Int) = chainEdit(expected) { now ->
        sendAll(Msg.changeType(positionOf(now, slot), fxId))
        delay(EDIT_WAIT_MS)
    }

    suspend fun insert(expected: PatchRef, pos: Int) = chainEdit(
        expected,
        verify = { before, after -> if (after.effects.size == before.effects.size) "the pedal refused to add an effect" else null },
    ) {
        send(Msg.insertEffect(pos))
        delay(EDIT_WAIT_MS)
    }

    /**
     * Adds effect [fxId] at entry [pos] (b6lab/live.py: insert an empty entry, then change its type) under one hold
     * of the session: the type change goes out only when the buffer after the insert is [expected]'s chain with an
     * empty entry at [pos] and no patch-change push came in.
     */
    suspend fun add(expected: PatchRef, pos: Int, fxId: Int) = op {
        checkRef(expected)
        val before = checkedEdit(expected)
        if (pos !in 0..before.effects.size) throw Refused("no place $pos")
        send(Msg.insertEffect(pos))
        delay(EDIT_WAIT_MS)
        val added = readEdit()
        setEdit(added)
        checkPushes(expected)
        if (added.effects.size == before.effects.size) throw Refused("the pedal refused to add an effect")
        if (added.effects.map { it.fxId } != expected.fxIds.toMutableList().apply { add(pos, 0) }) throw Refused(PATCH_CHANGED)
        sendAll(Msg.changeType(pos, fxId))
        delay(EDIT_WAIT_MS)
        setEdit(readEdit())
    }

    suspend fun delete(expected: PatchRef, slot: Int) = chainEdit(
        expected,
        verify = { before, after -> if (after.effects.size == before.effects.size) "the pedal did not delete the effect" else null },
    ) { now ->
        send(Msg.deleteEffect(positionOf(now, slot)))
        delay(EDIT_WAIT_MS)
    }

    suspend fun move(expected: PatchRef, src: Int, dst: Int) = chainEdit(expected) { now ->
        send(Msg.moveEffect(positionOf(now, src), dst))
        delay(EDIT_WAIT_MS)
    }

    /**
     * Patch Save (`64 0D`) into [expected]'s slot, only when the pedal (`33`, the edit buffer and the pushes) is still
     * on that patch; the `46` read-back must equal the edit buffer as checked before the store. In PC mode an
     * unanswered store is refused ("save not confirmed"), it does not end the link.
     */
    suspend fun save(expected: PatchRef) = op {
        checkRef(expected)
        val slot = expected.slot
        if (selectedSlot() != slot) throw Refused(PATCH_CHANGED)
        val before = checkedEdit(expected)
        checkPushes(expected)
        if (_state.value.pcMode) {
            sysexRequest(Msg.store(slot), STORE_REPLY, STORE_TIMEOUT_MS) { Refused("save not confirmed") }
        } else {
            send(Msg.store(slot))
        }
        delay(STORE_WAIT_MS)
        val edit = readEdit()
        stored = readStored(slot)
        setEdit(edit)
        if (!Ptcf.samePatch(before.raw, stored!!)) throw Refused("save failed")
    }

    // ---- operation framework ----------------------------------------------------------------

    /** A user operation: serialized, only while connected, clears the previous error, never throws. */
    private suspend fun op(block: suspend () -> Unit) = mutex.withLock {
        if (_state.value.connection != Connection.CONNECTED) {
            _state.update { it.copy(error = "not connected") }
            return@withLock
        }
        _state.update { it.copy(error = null) }
        guarded(block)
    }

    /** Background work (following the pedal): serialized, only while connected, keeps the user's error. */
    private suspend fun background(block: suspend () -> Unit) = mutex.withLock {
        if (_state.value.connection == Connection.CONNECTED) guarded(block)
    }

    private suspend fun guarded(block: suspend () -> Unit) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: LinkLost) {
            lose(e.message ?: "pedal disconnected")
        } catch (e: Exception) {
            _state.update { it.copy(error = e.message ?: e.javaClass.simpleName) }
        }
    }

    /**
     * A live edit: re-read the edit buffer and refuse when its effects differ from the screen's, send, then
     * re-read. [verify] compares the buffers before and after and returns an error message, or null.
     */
    private suspend fun chainEdit(
        expected: PatchRef,
        verify: ((Patch, Patch) -> String?)? = null,
        action: suspend (Patch) -> Unit,
    ) = op {
        checkRef(expected)
        val before = checkedEdit(expected)
        action(before)
        val after = readEdit()
        setEdit(after)
        verify?.invoke(before, after)?.let { throw Refused(it) }
    }

    /** Refuses at once (nothing sent) when the session already knows the pedal moved on from [expected]. */
    private fun checkRef(expected: PatchRef) {
        if (_state.value.ref != expected) throw Refused(PATCH_CHANGED)
        checkPushes(expected)
    }

    /**
     * Refuses when a patch-change push has arrived that is not loaded yet, or the last one named another slot: the
     * state may still show the old patch (a patch with the same effects passes the ID check).
     */
    private fun checkPushes(expected: PatchRef) {
        if (pushesArrived != pushesLoaded || (pushedSlot ?: expected.slot) != expected.slot) throw Refused(PATCH_CHANGED)
    }

    /** The edit buffer, read now; refuses (after showing it) when the pedal is on another patch than [expected]. */
    private suspend fun checkedEdit(expected: PatchRef): Patch {
        val now = readEdit()
        if (now.effects.map { it.fxId } != expected.fxIds || _state.value.slot != expected.slot) {
            setEdit(now)
            throw Refused(PATCH_CHANGED)
        }
        checkPushes(expected)
        return now
    }

    private fun positionOf(p: Patch, slot: Int): Int {
        if (slot !in p.effects.indices) throw Refused("no effect entry $slot")
        return Ptcf.position(p, slot)
    }

    private fun onFlags(p: Patch): Map<Int, Boolean> = p.effects.filter { !it.isTail }.associate { it.slot to it.on }

    private suspend fun toggleEffect(expected: PatchRef, slot: Int) {
        checkRef(expected)
        val shown = _state.value.edit!!
        if (slot !in shown.effects.indices) throw Refused("no effect entry $slot")
        val on = !shown.effects[slot].on
        val before = checkedEdit(expected)
        val flags = onFlags(before)
        if (slot !in flags) throw Refused("effect entry $slot cannot be switched")
        if (flags[slot] == on) {
            setEdit(before)
            return
        }
        val pos = Ptcf.position(before, slot)
        press(pos)
        val afterPatch = readEdit()
        val after = onFlags(afterPatch)
        val changed = flags.keys.filter { flags[it] != after[it] }
        if (changed == listOf(slot)) {
            setEdit(afterPatch)
            return
        }
        if (changed.isNotEmpty()) {
            press(pos) // undo the unexpected toggle
            setEdit(readEdit())
            throw Refused("the pedal switched effect $changed instead of $slot; undone")
        }
        setEdit(afterPatch)
        throw Refused("the pedal did not switch the effect")
    }

    /**
     * b6lab/midi.py press_effect: position + 5A press, wait, position + 5A release, wait. Not cancellable: a cancel
     * must never leave the virtual footswitch pressed.
     */
    private suspend fun press(pos: Int) = withContext(NonCancellable) {
        Msg.pressEffect(pos).chunked(2).forEach { pair ->
            sendAll(pair)
            delay(PRESS_WAIT_MS)
        }
    }

    // ---- following the pedal ----------------------------------------------------------------

    private fun startFollowing() {
        scope.launch(work) {
            for ((n, slot) in patchPushes) background {
                try {
                    // the newest slot known (a later push or our own selection beats an older push)
                    load(pushedSlot ?: slot)
                } finally {
                    pushesLoaded = n
                }
            }
        }
        scope.launch(work) {
            while (true) {
                paramPushes.receive()
                // debounce: wait until the knob pushes pause for PARAM_DEBOUNCE_MS
                while (withTimeoutOrNull(PARAM_DEBOUNCE_MS) { paramPushes.receive() } != null) Unit
                background { setEdit(readEdit()) }
            }
        }
        if (!_state.value.pcMode) {
            scope.launch(work) {
                while (true) {
                    delay(POLL_MS)
                    background { poll() }
                }
            }
        }
    }

    /** Without PC mode: `33` and an edit-buffer read; the stored slot is read again when the slot changed. */
    private suspend fun poll() {
        val slot = selectedSlot()
        val edit = readEdit()
        if (slot != _state.value.slot) stored = readStored(slot)
        _state.update { it.copy(slot = slot, edit = edit, dirty = isDirty(edit)) }
    }

    /** Slot [slot] is selected: read its edit buffer and its stored image. */
    private suspend fun load(slot: Int) {
        val edit = readEdit()
        stored = readStored(slot)
        _state.update { it.copy(slot = slot, edit = edit, dirty = isDirty(edit)) }
    }

    private fun setEdit(p: Patch) = _state.update { it.copy(edit = p, dirty = isDirty(p)) }

    private fun isDirty(p: Patch): Boolean = stored?.let { !Ptcf.samePatch(p.raw, it) } ?: false

    // ---- receiving --------------------------------------------------------------------------

    private suspend fun readLoop() {
        try {
            for (m in transport.incoming) dispatch(m)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // a transport failure ends the link like a close
        }
        pending?.replies?.close()
        if (!ended) lose("pedal disconnected")
    }

    private fun dispatch(m: MidiMessage) {
        val body = (m as? MidiMessage.Sysex)?.body
        if (body != null && body.startsWith(EDIT_DUMP)) {
            // every edit dump is acknowledged, asked for or not (B6 Lab read_edit; spec safety rule)
            try {
                send(Msg.ACK)
            } catch (e: Exception) {
                // the link is gone; the read loop ends on the close
            }
        }
        val p = pending
        if (p != null && p.accept(m)) {
            p.replies.trySend(m)
            return
        }
        when (val push = parsePush(m)) {
            is Push.PatchChanged -> {
                // recorded at once (operations check it), loaded later under the mutex; this loop and selectSlot write these
                pushedSlot = push.slot
                pushesArrived += 1
                patchPushes.trySend(pushesArrived to push.slot)
            }
            is Push.ParamChanged -> paramPushes.trySend(Unit)
            is Push.Other -> if (body != null && body.startsWith(UNSOLICITED_DUMP)) applyDump(body)
            else -> Unit
        }
    }

    /** The pedal sent its new edit buffer after a chain edit (`64 12 00`): show it. */
    private fun applyDump(body: ByteArray) {
        if (_state.value.connection != Connection.CONNECTED) return
        try {
            setEdit(Ptcf.parse(Codec.decodeBlock(body, 6)))
        } catch (e: Exception) {
            // a damaged dump: the operation's own read-back follows
        }
    }

    // ---- requests ---------------------------------------------------------------------------

    private fun send(body: ByteArray) = sendAll(listOf(body))

    /**
     * Sends [bodies] back to back under one hold of the send lock, so the read loop's ack never lands inside a
     * sequence (position + press, position + knob, position + type). All pass [Safety.check] before any is sent.
     * A failing transport ends the link, except a Safety rejection by the transport itself.
     */
    private fun sendAll(bodies: List<ByteArray>) {
        bodies.forEach { Safety.check(it) }
        val wire = bodies.map { if ((it[0].toInt() and 0xFF) >= 0x80) it else byteArrayOf(0xF0.toByte()) + it + byteArrayOf(0xF7.toByte()) }
        try {
            synchronized(sendLock) { wire.forEach { transport.send(it) } }
        } catch (e: IllegalStateException) {
            if (e.message?.startsWith(SAFETY_REJECTION) == true) throw e
            throw LinkLost("pedal disconnected")
        } catch (e: Exception) {
            throw LinkLost("pedal disconnected")
        }
    }

    /** Sends [body] and hands the accepted replies to [collect], within [timeoutMs]; then throws [onTimeout]. */
    private suspend fun <T : Any> exchange(
        body: ByteArray,
        timeoutMs: Long = REQUEST_TIMEOUT_MS,
        onTimeout: () -> Exception = { LinkLost("pedal not responding") },
        accept: (MidiMessage) -> Boolean,
        collect: suspend (ReceiveChannel<MidiMessage>) -> T,
    ): T {
        val p = Pending(accept)
        pending = p
        try {
            send(body)
            return withTimeoutOrNull(timeoutMs) { collect(p.replies) } ?: throw onTimeout()
        } catch (e: ClosedReceiveChannelException) {
            throw LinkLost("pedal disconnected")
        } finally {
            if (pending === p) pending = null
        }
    }

    /** A SysEx request answered by a message starting with [prefix]; an error response fails it (B6.request). */
    private suspend fun sysexRequest(
        body: ByteArray,
        prefix: ByteArray,
        timeoutMs: Long = REQUEST_TIMEOUT_MS,
        onTimeout: () -> Exception = { LinkLost("pedal not responding") },
    ): ByteArray =
        exchange(body, timeoutMs, onTimeout, { m -> m is MidiMessage.Sysex && (m.body.startsWith(prefix) || isError(m.body)) }) {
            val reply = (it.receive() as MidiMessage.Sysex).body
            if (!reply.startsWith(prefix)) throw Refused("pedal returned error 0x%02X".format(reply[4].toInt() and 0xFF))
            reply
        }

    /** A request answered by the response message `52 00 6E 00 <code>`; returns the code. */
    private suspend fun ackRequest(body: ByteArray): Int =
        exchange(body, accept = { m -> m is MidiMessage.Sysex && m.body.size >= 5 && m.body.startsWith(RESPONSE) }) {
            (it.receive() as MidiMessage.Sysex).body[4].toInt() and 0xFF
        }

    /** `33`: answered with bank select MSB, bank select LSB and program change (B6.selected_slot). */
    private suspend fun selectedSlot(): Int =
        exchange(Msg.SELECTED, accept = { it is MidiMessage.Channel }) { replies ->
            var bank = 0
            var slot: Int? = null
            while (slot == null) {
                val m = (replies.receive() as MidiMessage.Channel).bytes
                val status = m[0].toInt() and 0xF0
                if (status == 0xB0 && m.size >= 3 && m[1].toInt() == 0x20) bank = m[2].toInt()
                if (status == 0xC0) slot = bank * 4 + m[1].toInt()
            }
            slot
        }

    /** `64 13` -> `64 12 01 ...`; the read loop has already acknowledged the dump. */
    private suspend fun readEdit(): Patch = Ptcf.parse(Codec.decodeBlock(sysexRequest(Msg.READ_EDIT, SOLICITED_DUMP), 6))

    /** `46` -> `45` with the stored slot image. */
    private suspend fun readStored(slot: Int): ByteArray = Codec.decodeBlock(sysexRequest(Msg.readPatch(slot), slotReply(slot)), 10)

    // ---- ending -----------------------------------------------------------------------------

    private fun stop() {
        work.cancel()
        try {
            transport.close()
        } catch (e: Exception) {
            // already closed
        }
    }

    /** The link is gone: [Connection.DISCONNECTED] with [message]; the last edit buffer stays visible. */
    private fun lose(message: String) {
        ended = true
        stop()
        _state.update { it.copy(connection = Connection.DISCONNECTED, pcMode = false, error = message) }
    }
}
