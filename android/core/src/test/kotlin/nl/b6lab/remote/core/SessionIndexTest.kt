package nl.b6lab.remote.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The background read of all 240 slots that feeds patch search. */
@OptIn(ExperimentalCoroutinesApi::class)
class SessionIndexTest {
    private val records = Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText())
        .jsonArray.map { it.jsonObject }

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private fun image(slot: Int) = hex(records.first { it["slot"]!!.jsonPrimitive.int == slot }["raw"]!!.jsonPrimitive.content)
    private fun pedal() = FakePedal(List(240) { image(it) })

    private class Tap(val p: FakePedal, scope: CoroutineScope) : MidiTransport {
        var beforeSend: (ByteArray) -> Unit = {}
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
        }

        override val incoming: ReceiveChannel<MidiMessage> get() = ch
        override fun close() = p.close()
    }

    private fun TestScope.clock(): () -> Long = { testScheduler.currentTime }

    private fun isRead(b: ByteArray) = b.size > 5 && b[4].toInt() == 0x46
    private fun isFootswitch(framed: ByteArray) = framed.size > 2 && framed[0].toInt() and 0xFF == 0xF0 &&
        framed.copyOfRange(1, framed.size - 1).let { b -> b.size >= 8 && b[3].toInt() == 0x64 && b[4].toInt() == 0x20 && (b[6].toInt() and 0xFF) == 0x5A }

    private fun TestScope.settle() {
        advanceTimeBy(60_000)
        runCurrent()
    }

    @Test
    fun indexFillsTo240AfterConnect() = runTest {
        val s = B6Session(backgroundScope, pedal(), clock())
        s.connect()
        settle()
        val index = s.index.value
        assertEquals(240, index.indexed)
        assertEquals(Ptcf.parse(image(0)).name, index.entries[0]!!.name)
        assertEquals(Ptcf.parse(image(103)).name, index.entries[103]!!.name)
        assertEquals(103, index.search("z104", Catalog(emptyMap())).first().slot)
    }

    @Test
    fun toggleDuringIndexingWaitsForAtMostOneRead() = runTest {
        val p = pedal()
        val tap = Tap(p, backgroundScope)
        val s = B6Session(backgroundScope, tap, clock())
        val log = ArrayList<String>()
        var reads = 0
        tap.beforeSend = { b ->
            if (isRead(b)) {
                reads++
                log.add("read")
                if (reads == 40) {
                    log.add("toggle-requested")
                    backgroundScope.launch { s.toggle(s.state.value.ref!!, 0) }
                }
            }
            if (isFootswitch(b)) log.add("press")
        }
        s.connect()
        settle()
        val requested = log.indexOf("toggle-requested")
        val pressed = log.indexOf("press")
        assertTrue(requested >= 0 && pressed > requested)
        val readsBefore = log.subList(requested, pressed).count { it == "read" }
        assertTrue("reads between request and press: $readsBefore", readsBefore <= 1)
        assertEquals(240, s.index.value.indexed)
    }

    @Test
    fun unreadableSlotIsMarkedUnknownAndSessionLives() = runTest {
        val tap = Tap(pedal(), backgroundScope)
        // the pedal never answers the stored read of slot 5
        tap.filter = { m ->
            val b = (m as? MidiMessage.Sysex)?.body
            if (b != null && b.size > 8 && b[3].toInt() == 0x45 && b[6].toInt() == 1 && b[8].toInt() == 1) null else m
        }
        val s = B6Session(backgroundScope, tap, clock())
        s.connect()
        settle()
        assertEquals(Connection.CONNECTED, s.state.value.connection)
        assertNull(s.state.value.error)
        assertEquals(IndexStatus.DONE, s.indexStatus.value)
        assertEquals(240, s.index.value.indexed)
        assertTrue(s.index.value.entries.containsKey(5))
        assertNull(s.index.value.entries[5])
        assertEquals(Ptcf.parse(image(6)).name, s.index.value.entries[6]!!.name)
    }

    @Test
    fun saveUpdatesTheEntry() = runTest {
        val p = pedal()
        val s = B6Session(backgroundScope, p, clock())
        s.connect()
        settle()
        val before = s.index.value.entries[0]!!
        val last = s.state.value.edit!!.effects.last { !it.isTail }
        s.delete(s.state.value.ref!!, last.slot)
        settle()
        // an unsaved edit is not in the index
        assertEquals(before, s.index.value.entries[0])
        s.save(s.state.value.ref!!)
        settle()
        assertEquals(null, s.state.value.error)
        val after = s.index.value.entries[0]!!
        assertEquals(before.fxIds.size - 1, after.fxIds.size)
        assertEquals(before.name, after.name)
    }

    @Test
    fun disconnectStopsIndexing() = runTest {
        val s = B6Session(backgroundScope, pedal(), clock())
        s.connect()
        s.disconnect()
        settle()
        assertTrue(s.index.value.indexed < 240)
        assertEquals(Connection.DISCONNECTED, s.state.value.connection)
    }

    @Test
    fun damagedReplyIsAFailedAttemptNotAnError() = runTest {
        val tap = Tap(pedal(), backgroundScope)
        // every stored read of slot 7 comes back with a broken checksum
        tap.filter = { m ->
            val b = (m as? MidiMessage.Sysex)?.body
            if (b != null && b.size > 20 && b[3].toInt() == 0x45 && b[6].toInt() == 1 && b[8].toInt() == 3) {
                val bad = b.copyOf(); bad[bad.size - 2] = (bad[bad.size - 2].toInt() xor 0x55).toByte()
                MidiMessage.Sysex(bad)
            } else m
        }
        val s = B6Session(backgroundScope, tap, clock())
        s.connect()
        settle()
        assertNull(s.state.value.error)
        assertEquals(Connection.CONNECTED, s.state.value.connection)
        assertEquals(240, s.index.value.indexed)
        assertTrue(s.index.value.entries.containsKey(7))
        assertNull(s.index.value.entries[7])
        assertEquals(IndexStatus.DONE, s.indexStatus.value)
    }

    @Test
    fun indexerIssuesNoReadsDuringAKnobDrag() = runTest {
        val tap = Tap(pedal(), backgroundScope)
        val s = B6Session(backgroundScope, tap, clock())
        s.connect()
        runCurrent()
        val log = ArrayList<String>()
        tap.beforeSend = { b -> if (isRead(b)) log.add("read") }
        val ref = s.state.value.ref!!
        val pos = s.state.value.edit!!.effects.first { !it.isTail && it.params.isNotEmpty() }
        repeat(20) { i ->
            s.setKnob(s.state.value.ref!!, pos.slot, 0, i)
            advanceTimeBy(100) // knob steps closer together than the quiet time
        }
        // during the drag (last step was less than 500 ms ago) no read went out beyond the one in flight
        assertTrue("reads during drag: ${log.size}", log.size <= 3)
        settle()
        assertEquals(240, s.index.value.indexed)
    }
}
