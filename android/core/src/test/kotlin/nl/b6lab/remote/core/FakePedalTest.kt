package nl.b6lab.remote.core

import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class FakePedalTest {
    private val records = Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText())
        .jsonArray.map { it.jsonObject }

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private fun image(slot: Int) = hex(records.first { it["slot"]!!.jsonPrimitive.int == slot }["raw"]!!.jsonPrimitive.content)
    private fun b(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }
    private fun framed(body: ByteArray) = b(0xF0) + body + b(0xF7)

    private fun pedal(autoSave: Boolean = false) =
        FakePedal(List(8) { image(it) } + listOf(image(-1)), autoSave)

    private fun FakePedal.sx(body: ByteArray) = send(framed(body))
    private fun FakePedal.sx(msgs: List<ByteArray>) = msgs.forEach { sx(it) }

    private fun ReceiveChannel<MidiMessage>.drain(): List<MidiMessage> {
        val out = ArrayList<MidiMessage>()
        while (true) out.add(tryReceive().getOrNull() ?: break)
        return out
    }

    private fun body(m: MidiMessage) = (m as MidiMessage.Sysex).body

    private fun editPatch(p: FakePedal): Patch {
        p.sx(Msg.READ_EDIT)
        val reply = body(p.incoming.drain().single())
        assertArrayEquals(b(0x52, 0x00, 0x6E, 0x64, 0x12, 0x01), reply.copyOf(6))
        return Ptcf.parse(Codec.decodeBlock(reply, 6))
    }

    @Test
    fun answersIdentity() {
        val p = pedal()
        p.sx(Msg.IDENTITY)
        assertEquals(
            listOf<MidiMessage>(MidiMessage.Sysex(hex("7e000602526e001a00312e3030"))),
            p.incoming.drain(),
        )
        p.sx(Msg.ENTER_PC)
        assertEquals(listOf<MidiMessage>(MidiMessage.Sysex(Msg.ACK)), p.incoming.drain())
        p.sx(Msg.LEAVE_PC)
        assertEquals(listOf<MidiMessage>(MidiMessage.Sysex(Msg.ACK)), p.incoming.drain())
    }

    @Test
    fun pushesOnlyInPcMode() {
        val p = pedal()
        p.footswitchTo(2)
        assertTrue(p.incoming.drain().isEmpty())
        p.sx(Msg.ENTER_PC)
        p.incoming.drain()
        p.footswitchTo(5)
        val got = p.incoming.drain()
        assertEquals(
            listOf(
                MidiMessage.Sysex(hex("52006e6426000001000100")),
                MidiMessage.Channel(hex("b00000")),
                MidiMessage.Channel(hex("b02001")),
                MidiMessage.Channel(hex("c001")),
            ),
            got,
        )
        assertEquals(Push.PatchChanged(5), parsePush(got[0]))
        p.sx(Msg.LEAVE_PC)
        p.incoming.drain()
        p.footswitchTo(6)
        assertTrue(p.incoming.drain().isEmpty())
        // the footswitch loaded the slot into the edit buffer
        assertEquals(Ptcf.parse(image(6)).name, editPatch(p).name)
    }

    @Test
    fun pressTogglesOnRelease() {
        val p = pedal()
        val before = editPatch(p).effects[0].on
        p.sx(Msg.pressEffect(0)[0])
        p.sx(Msg.pressEffect(0)[1])
        assertEquals(!before, editPatch(p).effects[0].on)
        // press only: toggles once; release alone changes nothing
        val after = editPatch(p).effects[0].on
        p.sx(Msg.pressEffect(0)[2])
        p.sx(Msg.pressEffect(0)[3])
        assertEquals(after, editPatch(p).effects[0].on)
        p.sx(Msg.pressEffect(0)[0])
        p.sx(Msg.pressEffect(0)[1])
        assertEquals(before, editPatch(p).effects[0].on)
    }

    @Test
    fun knobPushPair() {
        val p = pedal()
        p.turnKnob(0, 1, 77)
        assertTrue(p.incoming.drain().isEmpty())
        assertEquals(77, editPatch(p).effects[0].params[1])
        p.sx(Msg.ENTER_PC)
        p.incoming.drain()
        p.turnKnob(0, 1, 55)
        val got = p.incoming.drain()
        assertEquals(
            listOf(
                MidiMessage.Sysex(hex("52006e64200064010000000000")),
                MidiMessage.Sysex(hex("52006e64200000033700000000")),
            ),
            got,
        )
        assertEquals(Push.ParamChanged(0, 0, 3, 55), parsePush(got[1]))
        assertEquals(55, editPatch(p).effects[0].params[1])
        p.toggleOnPedal(0)
        val on = p.incoming.drain()
        assertEquals(Push.ParamChanged(0, 0, 0, if (editPatch(p).effects[0].on) 1 else 0), parsePush(on[1]))
    }

    @Test
    fun storeAndRead() {
        val p = pedal()
        p.sx(Msg.readPatch(3))
        val first = body(p.incoming.drain().single())
        assertArrayEquals(b(0x52, 0x00, 0x6E, 0x45, 0, 0, 0, 0, 3, 0), first.copyOf(10))
        assertEquals(Ptcf.parse(image(3)).name, Ptcf.parse(Codec.decodeBlock(first, 10)).name)
        // edit slot 3 live, store it into slot 9 (an in-memory patch) and read it back
        Msg.selectSlot(3).forEach { p.send(it) }
        p.sx(Msg.setParam(0, 0, 33))
        p.sx(Msg.store(9))
        assertTrue(p.incoming.drain().isEmpty())
        p.sx(Msg.readPatch(9))
        val stored = Ptcf.parse(Codec.decodeBlock(body(p.incoming.drain().single()), 10))
        assertEquals(33, stored.effects[0].params[0])
        p.sx(Msg.readPatch(200))
        assertEquals("Empty", Ptcf.parse(Codec.decodeBlock(body(p.incoming.drain().single()), 10)).name)
        // selected slot is now 9 (store selects), answered to 33
        p.sx(Msg.SELECTED)
        assertEquals(
            listOf(
                MidiMessage.Channel(hex("b00000")),
                MidiMessage.Channel(hex("b02002")),
                MidiMessage.Channel(hex("c001")),
            ),
            p.incoming.drain(),
        )
        // the global reply carries auto save at byte 12
        p.sx(Msg.GLOBAL)
        assertFalse(parseAutoSave(body(p.incoming.drain().single())))
        val auto = pedal(autoSave = true)
        auto.sx(Msg.GLOBAL)
        assertTrue(parseAutoSave(body(auto.incoming.drain().single())))
    }

    @Test
    fun autoSaveStoresEveryEdit() {
        val p = pedal(autoSave = true)
        p.sx(Msg.setParam(0, 0, 21))
        assertEquals(21, Ptcf.parse(p.storedSlot(0)).effects[0].params[0])
        val q = pedal()
        q.sx(Msg.setParam(0, 0, 21))
        assertFalse(21 == Ptcf.parse(q.storedSlot(0)).effects[0].params[0])
    }

    @Test
    fun chainEditsAndInsertRefusedWhenFull() {
        val p = pedal()
        p.sx(Msg.ENTER_PC)
        p.incoming.drain()
        val n = editPatch(p).effects.size
        p.sx(Msg.insertEffect(0))
        val dump = p.incoming.drain().single()
        assertEquals(0x12, body(dump)[4].toInt())
        assertEquals(0x00, body(dump)[5].toInt())
        assertEquals(n + 1, Ptcf.parse(Codec.decodeBlock(body(dump), 6)).effects.size)
        repeat(Ptcf.MAX_ENTRIES) { p.sx(Msg.insertEffect(0)) }
        p.incoming.drain()
        val full = editPatch(p)
        assertEquals(Ptcf.MAX_ENTRIES, full.effects.size)
        p.sx(Msg.insertEffect(0))
        assertTrue(p.incoming.drain().isEmpty())
        assertEquals(Ptcf.MAX_ENTRIES, editPatch(p).effects.size)
        p.sx(Msg.deleteEffect(0))
        p.incoming.drain()
        assertEquals(Ptcf.MAX_ENTRIES - 1, editPatch(p).effects.size)
    }

    @Test
    fun typeChangeKeepsPerTypeMemory() {
        val p = pedal()
        val e0 = editPatch(p).effects[0]
        val other = editPatch(p).effects.first { it.fxId != e0.fxId && !it.isTail }.fxId
        p.sx(Msg.setParam(0, 0, 42))
        p.sx(Msg.changeType(0, other))
        assertEquals(other, editPatch(p).effects[0].fxId)
        p.sx(Msg.changeType(0, e0.fxId))
        assertEquals(42, editPatch(p).effects[0].params[0])
    }

    @Test
    fun forbiddenMessageFails() {
        val p = pedal()
        for (bad in listOf(b(0x52, 0x00, 0x6E, 0x05), b(0x52, 0x00, 0x6E, 0x64, 0x2D), b(0x52, 0x00, 0x6E, 0x60, 0x20),
            b(0x52, 0x00, 0x6E, 0x64, 0x20, 0x00, 0x00, 0x00, 1, 0, 0, 0, 0))) {
            try {
                p.sx(bad)
                fail("not blocked: ${bad.toList()}")
            } catch (e: IllegalStateException) {
                assertNotNull(e.message)
            }
        }
        try {
            p.send(b(0xB0, 0x20, 0x90))
            fail("bad channel message not blocked")
        } catch (e: IllegalStateException) {
            assertNotNull(e.message)
        }
    }

    @Test
    fun unplugEndsTheLink() {
        val p = pedal()
        p.unplug()
        assertNull(p.incoming.tryReceive().getOrNull())
        assertTrue(p.incoming.tryReceive().isClosed)
        try {
            p.send(framed(Msg.IDENTITY))
            fail("send after unplug")
        } catch (e: java.io.IOException) {
            // expected
        }
    }
}
