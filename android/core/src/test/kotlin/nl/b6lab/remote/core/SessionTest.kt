package nl.b6lab.remote.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SessionTest {
    private val records = Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText())
        .jsonArray.map { it.jsonObject }

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private fun image(slot: Int) = hex(records.first { it["slot"]!!.jsonPrimitive.int == slot }["raw"]!!.jsonPrimitive.content)
    private fun framed(body: ByteArray) = byteArrayOf(0xF0.toByte()) + body + byteArrayOf(0xF7.toByte())

    /** Slots 0..19 of the user's pedal: slot 0 is SVT Drive (with tails), slot 16 has 6 entries. */
    private fun pedal(autoSave: Boolean = false, busy: Boolean = false) =
        FakePedal(List(20) { image(it) }, autoSave, busy)

    private fun TestScope.session(p: MidiTransport) = B6Session(backgroundScope, p)

    /**
     * A [FakePedal] with hooks on the wire: [beforeSend] / [afterSend] run before / after the pedal gets a message,
     * [filter] edits or drops replies.
     */
    private class Tap(val p: FakePedal, scope: CoroutineScope) : MidiTransport {
        var beforeSend: (ByteArray) -> Unit = {}
        var afterSend: (ByteArray) -> Unit = {}
        var filter: (MidiMessage) -> MidiMessage? = { it }
        private val ch = Channel<MidiMessage>(Channel.UNLIMITED)

        init {
            scope.launch {
                for (m in p.incoming) filter(m)?.let { ch.trySend(it) }
                ch.close()
            }
        }

        override fun send(bytes: ByteArray) {
            beforeSend(bytes)
            p.send(bytes)
            afterSend(bytes)
        }

        override val incoming: ReceiveChannel<MidiMessage> get() = ch
        override fun close() = p.close()
    }

    /** A framed Patch Save (`F0 52 00 6E 64 0D ...`). */
    private fun isStore(b: ByteArray) = b.size > 6 && b[4].toInt() == 0x64 && b[5].toInt() == 0x0D
    private fun isStoreReply(m: MidiMessage) = m is MidiMessage.Sysex && m.body.size > 4 && m.body[3].toInt() == 0x45

    private val B6Session.ref: PatchRef get() = state.value.ref!!

    private fun ids(p: Patch?) = p!!.effects.map { it.fxId }
    private fun editOf(p: FakePedal) = Ptcf.parse(p.editBuffer())
    private fun sentBodies(p: FakePedal) = p.sent.map { if ((it[0].toInt() and 0xFF) == 0xF0) it.copyOfRange(1, it.size - 1) else it }
    private fun count(p: FakePedal, body: ByteArray) = p.sent.count { it.contentEquals(framed(body)) }
    private fun isFootswitch(b: ByteArray) =
        b.size >= 8 && (b[3].toInt() == 0x64) && b[4].toInt() == 0x20 && (b[6].toInt() and 0xFF) == 0x5A

    private fun TestScope.settle() {
        advanceTimeBy(1000)
        runCurrent()
    }

    @Test
    fun connectsInPcMode() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val st = s.state.value
        assertEquals(Connection.CONNECTED, st.connection)
        assertTrue(st.pcMode)
        assertTrue(p.pcMode)
        assertEquals(0, st.slot)
        assertEquals("SVT Drive", st.edit!!.name)
        assertFalse(st.dirty)
        assertFalse(st.autoSave)
        assertNull(st.error)
        // identity, 50, 64 0A, 33, 64 13 (+ ack), 46 in that order
        val order = listOf(Msg.IDENTITY, Msg.ENTER_PC, Msg.GLOBAL, Msg.SELECTED, Msg.READ_EDIT, Msg.ACK, Msg.readPatch(0))
        assertEquals(order.map { it.toList() }, sentBodies(p).map { it.toList() })
    }

    @Test
    fun notAB6() = runTest {
        val other = object : MidiTransport {
            val ch = Channel<MidiMessage>(Channel.UNLIMITED)
            override fun send(bytes: ByteArray) {
                // another Zoom model (model bytes 6E 00)
                ch.trySend(MidiMessage.Sysex(hex("7e000602526e006e00312e3030")))
            }
            override val incoming: ReceiveChannel<MidiMessage> get() = ch
            override fun close() { ch.close() }
        }
        val s = session(other)
        s.connect()
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
        assertEquals("not a B6", s.state.value.error)
    }

    @Test
    fun fallsBackToPollingWhenBusy() = runTest {
        val p = pedal(busy = true)
        val s = session(p)
        s.connect()
        assertEquals(Connection.CONNECTED, s.state.value.connection)
        assertFalse(s.state.value.pcMode)
        assertFalse(p.pcMode)
        p.footswitchTo(3)
        advanceTimeBy(1000)
        runCurrent()
        assertEquals(3, s.state.value.slot)
        assertEquals("Natural AG", s.state.value.edit!!.name)
        assertTrue(count(p, Msg.SELECTED) >= 2)
    }

    @Test
    fun followsFootswitch() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        p.footswitchTo(5)
        advanceTimeBy(1000)
        runCurrent()
        assertEquals(5, s.state.value.slot)
        assertEquals("Warm AC370", s.state.value.edit!!.name)
        assertFalse(s.state.value.dirty)
        // PC mode: no polling
        assertEquals(1, count(p, Msg.SELECTED))
    }

    @Test
    fun followsPedalKnob() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val old = s.state.value.edit!!.effects[0].params[1]
        p.turnKnob(0, 1, old + 3)
        advanceTimeBy(1000)
        runCurrent()
        assertEquals(old + 3, s.state.value.edit!!.effects[0].params[1])
        assertTrue(s.state.value.dirty)
    }

    @Test
    fun toggleTogglesOnlyThatEffect() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val before = s.state.value.edit!!
        s.toggle(s.ref, 2)
        val after = s.state.value.edit!!
        assertNull(s.state.value.error)
        assertEquals(!before.effects[2].on, after.effects[2].on)
        for (i in before.effects.indices) if (i != 2) assertEquals(before.effects[i].on, after.effects[i].on)
        assertEquals(editOf(p).effects.map { it.on }, after.effects.map { it.on })
        assertTrue(s.state.value.dirty)
        // only the press/release of position 2 went out as an on/off message
        val presses = sentBodies(p).filter { isFootswitch(it) }
        assertEquals(Msg.pressEffect(2).filter { isFootswitch(it) }.map { it.toList() }, presses.map { it.toList() })
        // a tail cannot be switched: nothing sent, error set
        val n = p.sent.size
        s.toggle(s.ref, 1)
        assertNotNull(s.state.value.error)
        assertTrue(sentBodies(p).drop(n).none { isFootswitch(it) })
    }

    @Test
    fun editRefusedWhenPatchChanged() = runTest {
        // (operation, busy): without PC mode setKnob reads the edit buffer first; in PC mode it trusts the pushes
        val ops: List<Pair<suspend (B6Session, PatchRef) -> Unit, Boolean>> = listOf(
            Pair({ s, r -> s.toggle(r, 0) }, false),
            Pair({ s, r -> s.setKnob(r, 0, 0, 10) }, true),
            Pair({ s, r -> s.changeType(r, 0, 0x5890011) }, false),
            Pair({ s, r -> s.insert(r, 0) }, false),
            Pair({ s, r -> s.delete(r, 0) }, false),
            Pair({ s, r -> s.move(r, 0, 2) }, false),
        )
        for ((op, busy) in ops) {
            val p = pedal(busy = busy)
            val s = session(p)
            s.connect()
            val shown = s.ref
            // the patch changes on the pedal; the session has not seen the push yet
            p.footswitchTo(1)
            assertNotEquals(shown.fxIds, ids(editOf(p)))
            val n = p.sent.size
            op(s, shown)
            assertEquals("patch changed on the pedal", s.state.value.error)
            // only the edit-buffer read and its ack were sent, no live message
            assertEquals(listOf(Msg.READ_EDIT.toList(), Msg.ACK.toList()), sentBodies(p).drop(n).map { it.toList() })
            assertEquals(ids(editOf(p)), ids(s.state.value.edit))
            advanceTimeBy(1000)
            runCurrent()
            assertEquals(1, s.state.value.slot)
            assertEquals(Connection.CONNECTED, s.state.value.connection)
        }
    }

    @Test
    fun staleRefRefused() = runTest {
        val ops: List<suspend (B6Session, PatchRef) -> Unit> = listOf(
            { s, r -> s.toggle(r, 0) },
            { s, r -> s.setKnob(r, 0, 0, 10) },
            { s, r -> s.changeType(r, 0, 0x5890011) },
            { s, r -> s.insert(r, 0) },
            { s, r -> s.delete(r, 0) },
            { s, r -> s.move(r, 0, 2) },
            { s, r -> s.save(r) },
        )
        for (op in ops) {
            val p = pedal()
            val s = session(p)
            s.connect()
            val shown = s.ref
            // the push is processed before the user's tap reaches the session
            p.footswitchTo(1)
            runCurrent()
            assertEquals(1, s.state.value.slot)
            val n = p.sent.size
            op(s, shown)
            assertEquals("patch changed on the pedal", s.state.value.error)
            val after = sentBodies(p).drop(n).map { it.toList() }
            assertTrue(after.toString(), after.all { it == Msg.READ_EDIT.toList() || it == Msg.ACK.toList() })
            assertTrue(Ptcf.samePatch(p.storedSlot(0), image(0)))
            assertTrue(Ptcf.samePatch(p.storedSlot(1), image(1)))
        }
    }

    @Test
    fun saveRefusedWhenPatchChanged() = runTest {
        for (busy in listOf(false, true)) {
            val p = pedal(busy = busy)
            val s = session(p)
            s.connect()
            s.setKnob(s.ref, 0, 0, 5)
            val shown = s.ref
            p.footswitchTo(1) // not yet seen by the session
            s.save(shown)
            assertEquals("patch changed on the pedal", s.state.value.error)
            assertEquals(0, count(p, Msg.store(0)) + count(p, Msg.store(1)))
            assertTrue(Ptcf.samePatch(p.storedSlot(0), image(0)))
            assertTrue(Ptcf.samePatch(p.storedSlot(1), image(1)))
        }
    }

    @Test
    fun saveChecksTheSelectedSlot() = runTest {
        // slot 1 holds the same effects as slot 0: only the `33` check sees the switch
        val p = FakePedal(listOf(image(0), image(0)))
        val s = session(p)
        s.connect()
        val shown = s.ref
        p.footswitchTo(1)
        s.save(shown)
        assertEquals("patch changed on the pedal", s.state.value.error)
        assertEquals(0, count(p, Msg.store(0)) + count(p, Msg.store(1)))
    }

    @Test
    fun footswitchToIdenticalChainRefused() = runTest {
        // slot 1 holds the same effects as slot 0: only the patch-change push tells them apart
        val ops: List<suspend (B6Session, PatchRef) -> Unit> = listOf(
            { s, r -> s.toggle(r, 0) },
            { s, r -> s.changeType(r, 0, 0x5890011) },
            { s, r -> s.insert(r, 0) },
            { s, r -> s.delete(r, 0) },
            { s, r -> s.move(r, 0, 2) },
            { s, r -> s.save(r) },
        )
        for (op in ops) {
            val p = FakePedal(listOf(image(0), image(0)))
            val s = session(p)
            s.connect()
            val shown = s.ref
            p.footswitchTo(1) // the push arrives while the operation reads the edit buffer
            val n = p.sent.size
            op(s, shown)
            assertEquals("patch changed on the pedal", s.state.value.error)
            val after = sentBodies(p).drop(n).map { it.toList() }
            assertTrue(after.toString(), after.all { it == Msg.READ_EDIT.toList() || it == Msg.ACK.toList() || it == Msg.SELECTED.toList() })
            assertTrue(Ptcf.samePatch(p.editBuffer(), image(0)))
            assertTrue(Ptcf.samePatch(p.storedSlot(0), image(0)))
            settle()
            assertEquals(1, s.state.value.slot)
        }
    }

    @Test
    fun knobRefusedWhilePatchPushWaits() = runTest {
        val p = FakePedal(listOf(image(0), image(0)))
        val s = session(p)
        s.connect()
        val shown = s.ref
        // a toggle holds the session (press waits); a knob step queues behind it
        launch { s.toggle(shown, 2) }
        runCurrent()
        launch { s.setKnob(shown, 0, 0, 10) }
        runCurrent()
        // the footswitch push arrives, but is applied only after the knob step
        p.footswitchTo(1)
        runCurrent()
        settle()
        assertEquals(0, count(p, Msg.setParam(0, 0, 10)[1]))
        assertNotEquals(10, editOf(p).effects[0].params[0])
        assertEquals(1, s.state.value.slot)
    }

    @Test
    fun saveComparesStoredWithCheckedBuffer() = runTest {
        val p = pedal()
        val t = Tap(p, backgroundScope)
        val s = session(t)
        s.connect()
        s.setKnob(s.ref, 0, 0, 5)
        // a knob is turned on the pedal between the check and the store: what is stored (and read back from the
        // edit buffer) is not what was checked
        t.beforeSend = { if (isStore(it)) p.turnKnob(0, 1, 77) }
        s.save(s.ref)
        assertEquals("save failed", s.state.value.error)
        assertEquals(Connection.CONNECTED, s.state.value.connection)
    }

    @Test
    fun saveAcceptsAnyStoreReply() = runTest {
        val p = pedal()
        val t = Tap(p, backgroundScope)
        val s = session(t)
        s.connect()
        s.setKnob(s.ref, 0, 0, 5)
        var storing = false
        t.afterSend = { if (isStore(it)) storing = true }
        t.filter = { m ->
            if (storing && isStoreReply(m)) {
                storing = false
                // other slot bytes than asked for: B6 Lab (store_edit) waits for any 45
                MidiMessage.Sysex((m as MidiMessage.Sysex).body.copyOf().also { it[5] = 0x11 })
            } else m
        }
        s.save(s.ref)
        assertNull(s.state.value.error)
        assertFalse(s.state.value.dirty)
        assertEquals(Connection.CONNECTED, s.state.value.connection)
    }

    @Test
    fun unconfirmedSaveIsARefusal() = runTest {
        val p = pedal()
        val t = Tap(p, backgroundScope)
        val s = session(t)
        s.connect()
        s.setKnob(s.ref, 0, 0, 5)
        var storing = false
        t.afterSend = { if (isStore(it)) storing = true }
        t.filter = { m -> if (storing && isStoreReply(m)) null else m }
        s.save(s.ref)
        assertEquals("save not confirmed", s.state.value.error)
        assertEquals(Connection.CONNECTED, s.state.value.connection)
    }

    @Test
    fun cancelledToggleStillReleases() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val job = launch { s.toggle(s.ref, 2) }
        runCurrent() // inside the wait after the press
        job.cancel()
        settle()
        val presses = sentBodies(p).filter { isFootswitch(it) }.map { it.toList() }
        assertEquals(Msg.pressEffect(2).filter { isFootswitch(it) }.map { it.toList() }, presses)
    }

    @Test
    fun knobStepsAreCheap() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val reads = count(p, Msg.READ_EDIT)
        for (v in 1..20) s.setKnob(s.ref, 2, 0, v)
        assertNull(s.state.value.error)
        assertEquals(20, s.state.value.edit!!.effects[2].params[0])
        assertTrue(s.state.value.dirty)
        assertEquals(reads, count(p, Msg.READ_EDIT))
        for (v in 1..20) assertEquals(1, count(p, Msg.setParam(2, 0, v)[1]))
        assertEquals(20, count(p, Msg.setParam(2, 0, 1)[0]))
        advanceTimeBy(1000)
        runCurrent()
        // one debounced confirming read
        assertTrue(count(p, Msg.READ_EDIT) - reads in 1..2)
        assertEquals(20, s.state.value.edit!!.effects[2].params[0])
        assertTrue(Ptcf.samePatch(s.state.value.edit!!.raw, p.editBuffer()))
    }

    @Test
    fun toggleUndoesMisroutedPress() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val before = s.state.value.edit!!.effects.map { it.on }
        p.misroutePresses(2, 4)
        s.toggle(s.ref, 2)
        assertEquals("the pedal switched effect [4] instead of 2; undone", s.state.value.error)
        assertEquals(before, editOf(p).effects.map { it.on })
        assertEquals(before, s.state.value.edit!!.effects.map { it.on })
        // the press and the undo press, both at position 2
        val presses = sentBodies(p).filter { isFootswitch(it) }.map { it.toList() }
        val one = Msg.pressEffect(2).filter { isFootswitch(it) }.map { it.toList() }
        assertEquals(one + one, presses)
        assertEquals(Connection.CONNECTED, s.state.value.connection)
    }

    @Test
    fun transportFailureDisconnects() = runTest {
        val p = pedal()
        var broken = false
        val t = object : MidiTransport {
            override fun send(bytes: ByteArray) {
                if (broken) throw IllegalStateException("USB port closed")
                p.send(bytes)
            }
            override val incoming: ReceiveChannel<MidiMessage> get() = p.incoming
            override fun close() = p.close()
        }
        val s = session(t)
        s.connect()
        broken = true
        s.setKnob(s.ref, 0, 0, 3)
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
        assertEquals("pedal disconnected", s.state.value.error)
    }

    @Test
    fun liveEditsFollowB6Lab() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        var n = p.sent.size
        s.setKnob(s.ref, 2, 0, 21)
        assertEquals(21, editOf(p).effects[2].params[0])
        assertEquals(21, s.state.value.edit!!.effects[2].params[0])
        assertEquals(
            Msg.setParam(2, 0, 21).map { it.toList() },
            sentBodies(p).drop(n).map { it.toList() },
        )
        n = p.sent.size
        s.changeType(s.ref, 4, 0x5890011)
        assertEquals(0x5890011, s.state.value.edit!!.effects[4].fxId)
        // ack of the read, the change, ack of the pedal's own dump, the read-back and its ack
        assertEquals(
            (listOf(Msg.READ_EDIT, Msg.ACK) + Msg.changeType(4, 0x5890011) + listOf(Msg.ACK, Msg.READ_EDIT, Msg.ACK))
                .map { it.toList() },
            sentBodies(p).drop(n).map { it.toList() },
        )
        s.delete(s.ref, 4)
        assertEquals(4, s.state.value.edit!!.effects.size)
        s.insert(s.ref, 0)
        assertEquals(5, s.state.value.edit!!.effects.size)
        assertEquals(0, s.state.value.edit!!.effects[0].fxId)
        s.move(s.ref, 0, 4)
        assertEquals(0, s.state.value.edit!!.effects[4].fxId)
        assertEquals(ids(editOf(p)), ids(s.state.value.edit))
        assertNull(s.state.value.error)
    }

    @Test
    fun unsolicitedDumpUpdatesState() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val job = launch { s.changeType(s.ref, 4, 0x5890011) }
        // inside the 250 ms wait, before the read-back: the pedal's own 64 12 00 dump is already shown
        advanceTimeBy(100)
        runCurrent()
        assertEquals(0x5890011, s.state.value.edit!!.effects[4].fxId)
        assertEquals(2, count(p, Msg.READ_EDIT)) // connect, and the check before the change
        job.join()
    }

    @Test
    fun selectSlotLoadsIt() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        s.setKnob(s.ref, 0, 0, 5)
        assertTrue(s.state.value.dirty)
        s.selectSlot(7)
        advanceTimeBy(1000)
        runCurrent()
        assertEquals(7, s.state.value.slot)
        assertEquals("EBH Slap", s.state.value.edit!!.name)
        assertFalse(s.state.value.dirty)
        assertEquals(7, p.selectedSlot)
    }

    @Test
    fun saveClearsDirty() = runTest {
        for (busy in listOf(false, true)) {
            val p = pedal(busy = busy)
            val s = session(p)
            s.connect()
            s.selectSlot(4)
            s.setKnob(s.ref, 0, 1, 9)
            assertTrue(s.state.value.dirty)
            s.save(s.ref)
            assertNull(s.state.value.error)
            assertFalse(s.state.value.dirty)
            assertTrue(Ptcf.samePatch(p.storedSlot(4), p.editBuffer()))
            assertEquals(1, count(p, Msg.store(4)))
            assertEquals(Connection.CONNECTED, s.state.value.connection)
        }
    }

    @Test
    fun autoSaveReported() = runTest {
        val s = session(pedal(autoSave = true))
        s.connect()
        assertTrue(s.state.value.autoSave)
        val t = session(pedal())
        t.connect()
        assertFalse(t.state.value.autoSave)
    }

    @Test
    fun unplugGoesDisconnected() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        p.unplug()
        runCurrent()
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
        // operations after the unplug do not throw
        s.setKnob(s.ref, 0, 0, 3)
        s.toggle(s.ref, 0)
        s.save(s.ref)
        s.disconnect()
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
        assertNotNull(s.state.value.error)
    }

    @Test
    fun silentPedalTimesOut() = runTest {
        val silent = object : MidiTransport {
            val ch = Channel<MidiMessage>(Channel.UNLIMITED)
            override fun send(bytes: ByteArray) = Unit
            override val incoming: ReceiveChannel<MidiMessage> get() = ch
            override fun close() { ch.close() }
        }
        val s = session(silent)
        s.connect()
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
        assertNotNull(s.state.value.error)
        assertEquals(3000, currentTime)
    }

    @Test
    fun refusedInsertKeepsStateInSync() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        s.selectSlot(16)
        assertEquals(Ptcf.MAX_ENTRIES, s.state.value.edit!!.effects.size)
        s.insert(s.ref, 0)
        assertNotNull(s.state.value.error)
        assertEquals(Connection.CONNECTED, s.state.value.connection)
        assertTrue(Ptcf.samePatch(s.state.value.edit!!.raw, p.editBuffer()))
        assertEquals(1, count(p, Msg.insertEffect(0)))
    }

    @Test
    fun disconnectLeavesPcMode() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        s.disconnect()
        assertFalse(p.pcMode)
        assertEquals(Msg.LEAVE_PC.toList(), sentBodies(p).last().toList())
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
        assertNull(s.state.value.error)
    }

    @Test
    fun acksEveryEditDump() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        s.changeType(s.ref, 0, 0x5890011)
        s.insert(s.ref, 0)
        s.delete(s.ref, 0)
        s.move(s.ref, 0, 2)
        advanceTimeBy(1000)
        runCurrent()
        // one dump per 64 13 plus the four the pedal sent on its own after the chain edits
        assertEquals(count(p, Msg.READ_EDIT) + 4, count(p, Msg.ACK))
    }

    @Test
    fun neverSendsForbidden() = runTest {
        for (busy in listOf(false, true)) {
            val p = pedal(busy = busy)
            val s = session(p)
            val errors = ArrayList<String?>()
            suspend fun run(op: suspend () -> Unit) {
                op()
                advanceTimeBy(1000)
                runCurrent()
                errors.add(s.state.value.error)
            }
            run { s.connect() }
            run { s.selectSlot(0) }
            for (e in s.state.value.edit!!.effects.indices) run { s.toggle(s.ref, e) }
            for (e in s.state.value.edit!!.effects.indices) run { s.setKnob(s.ref, e, 0, 7) }
            run { s.changeType(s.ref, 0, 0x5890011) }
            run { s.insert(s.ref, 1) }
            run { s.delete(s.ref, 1) }
            run { s.move(s.ref, 0, 3) }
            p.toggleOnPedal(0)
            p.turnKnob(0, 2, 11)
            p.footswitchTo(16)
            run { }
            run { s.insert(s.ref, 0) }
            run { s.selectSlot(2) }
            run { s.save(s.ref) }
            run { s.disconnect() }
            assertTrue(errors.toString(), errors.none { it != null && it.contains("blocked") })
            for (b in sentBodies(p)) Safety.check(b)
            assertTrue(sentBodies(p).none { it.size >= 8 && it[3].toInt() == 0x64 && it[4].toInt() == 0x20 && it[7].toInt() == 0 && (it[6].toInt() and 0xFF) != 0x5A })
        }
    }

    @Test
    fun busyPedalAnswers0011() {
        val p = pedal(busy = true)
        p.send(framed(Msg.ENTER_PC))
        assertEquals(
            MidiMessage.Sysex(hex("52006e0011")),
            p.incoming.tryReceive().getOrNull(),
        )
        assertFalse(p.pcMode)
    }
}
