package nl.b6lab.remote.core

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

    private fun ids(p: Patch?) = p!!.effects.map { it.fxId }
    private fun editOf(p: FakePedal) = Ptcf.parse(p.editBuffer())
    private fun sentBodies(p: FakePedal) = p.sent.map { if ((it[0].toInt() and 0xFF) == 0xF0) it.copyOfRange(1, it.size - 1) else it }
    private fun count(p: FakePedal, body: ByteArray) = p.sent.count { it.contentEquals(framed(body)) }
    private fun isFootswitch(b: ByteArray) =
        b.size >= 8 && (b[3].toInt() == 0x64) && b[4].toInt() == 0x20 && (b[6].toInt() and 0xFF) == 0x5A

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
        s.toggle(2)
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
        s.toggle(1)
        assertNotNull(s.state.value.error)
        assertTrue(sentBodies(p).drop(n).none { isFootswitch(it) })
    }

    @Test
    fun editRefusedWhenPatchChanged() = runTest {
        val ops: List<suspend (B6Session) -> Unit> = listOf(
            { it.toggle(0) },
            { it.setKnob(0, 0, 10) },
            { it.changeType(0, 0x5890011) },
            { it.insert(0) },
            { it.delete(0) },
            { it.move(0, 2) },
        )
        for (op in ops) {
            val p = pedal()
            val s = session(p)
            s.connect()
            val shown = s.state.value.edit!!
            // the patch changes on the pedal; the session has not seen the push yet
            p.footswitchTo(1)
            assertNotEquals(ids(shown), ids(editOf(p)))
            val n = p.sent.size
            op(s)
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
    fun liveEditsFollowB6Lab() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        var n = p.sent.size
        s.setKnob(2, 0, 21)
        assertEquals(21, editOf(p).effects[2].params[0])
        assertEquals(21, s.state.value.edit!!.effects[2].params[0])
        assertEquals(
            (listOf(Msg.READ_EDIT, Msg.ACK) + Msg.setParam(2, 0, 21) + listOf(Msg.READ_EDIT, Msg.ACK)).map { it.toList() },
            sentBodies(p).drop(n).map { it.toList() },
        )
        n = p.sent.size
        s.changeType(4, 0x5890011)
        assertEquals(0x5890011, s.state.value.edit!!.effects[4].fxId)
        // ack of the read, the change, ack of the pedal's own dump, the read-back and its ack
        assertEquals(
            (listOf(Msg.READ_EDIT, Msg.ACK) + Msg.changeType(4, 0x5890011) + listOf(Msg.ACK, Msg.READ_EDIT, Msg.ACK))
                .map { it.toList() },
            sentBodies(p).drop(n).map { it.toList() },
        )
        s.delete(4)
        assertEquals(4, s.state.value.edit!!.effects.size)
        s.insert(0)
        assertEquals(5, s.state.value.edit!!.effects.size)
        assertEquals(0, s.state.value.edit!!.effects[0].fxId)
        s.move(0, 4)
        assertEquals(0, s.state.value.edit!!.effects[4].fxId)
        assertEquals(ids(editOf(p)), ids(s.state.value.edit))
        assertNull(s.state.value.error)
    }

    @Test
    fun unsolicitedDumpUpdatesState() = runTest {
        val p = pedal()
        val s = session(p)
        s.connect()
        val job = launch { s.changeType(4, 0x5890011) }
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
        s.setKnob(0, 0, 5)
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
            s.setKnob(0, 1, 9)
            assertTrue(s.state.value.dirty)
            s.save()
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
        s.setKnob(0, 0, 3)
        s.toggle(0)
        s.save()
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
        s.insert(0)
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
        s.changeType(0, 0x5890011)
        s.insert(0)
        s.delete(0)
        s.move(0, 2)
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
            for (e in s.state.value.edit!!.effects.indices) run { s.toggle(e) }
            for (e in s.state.value.edit!!.effects.indices) run { s.setKnob(e, 0, 7) }
            run { s.changeType(0, 0x5890011) }
            run { s.insert(1) }
            run { s.delete(1) }
            run { s.move(0, 3) }
            p.toggleOnPedal(0)
            p.turnKnob(0, 2, 11)
            p.footswitchTo(16)
            run { }
            run { s.insert(0) }
            run { s.selectSlot(2) }
            run { s.save() }
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
