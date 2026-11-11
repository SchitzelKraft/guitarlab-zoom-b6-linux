package nl.b6lab.remote.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class MessagesTest {
    private val fixture: JsonObject =
        Json.parseToJsonElement(javaClass.getResource("/fixtures/messages.json")!!.readText()).jsonObject

    private fun bytes(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private fun hex(s: String) = bytes(s.replace(" ", ""))

    /** The recorded messages of one case, in order. */
    private fun sent(name: String): List<ByteArray> =
        fixture[name]!!.jsonArray.map { bytes(it.jsonObject["hex"]!!.jsonPrimitive.content) }

    private fun expectOne(name: String, actual: ByteArray) = assertArrayEquals(name, sent(name)[0], actual)
    private fun expectAll(name: String, actual: List<ByteArray>) {
        val want = sent(name)
        assertEquals(name, want.size, actual.size)
        want.indices.forEach { assertArrayEquals("$name[$it]", want[it], actual[it]) }
    }

    @Test
    fun buildersMatchB6Lab() {
        expectOne("identity", Msg.IDENTITY)
        expectOne("patch_info", Msg.PATCH_INFO)
        expectOne("enter_pc", Msg.ENTER_PC)
        expectOne("leave_pc", Msg.LEAVE_PC)
        expectOne("selected", Msg.SELECTED)
        expectOne("global", Msg.GLOBAL)
        expectOne("read_edit", Msg.READ_EDIT)
        assertArrayEquals(sent("read_edit")[1], Msg.ACK)
        expectOne("read_patch_5", Msg.readPatch(5))
        expectOne("store_239", Msg.store(239))
        expectAll("select_239", Msg.selectSlot(239))
        expectAll("press_2", Msg.pressEffect(2))
        expectAll("set_param_4_4_3_57", Msg.setParam(4, 3, 57))
        expectAll("change_type_2", Msg.changeType(2, 0x07090010))
        expectOne("insert_1", Msg.insertEffect(1))
        expectOne("delete_0", Msg.deleteEffect(0))
        expectOne("move_0_1", Msg.moveEffect(0, 1))
    }

    @Test
    fun parsesRealPushes() {
        fun push(s: String) = parsePush(MidiMessage.Sysex(hex(s)))
        assertEquals(Push.PatchChanged(239), push("52 00 6e 64 26 00 00 3b 00 03 00"))
        assertEquals(Push.ParamChanged(2, 2, 4, 99), push("52 00 6e 64 20 00 02 04 63 00 00 00 00"))
        assertEquals(Push.ParamChanged(2, 2, 0, 1), push("52 00 6e 64 20 00 02 00 01 00 00 00 00"))
        assertEquals(Push.Ack, push("52 00 6e 00 00"))
        assertEquals(Push.Error(3), push("52 00 6e 00 03"))
        assertTrue(push("52 00 6e 64 12 01") is Push.Other)
        assertNull(parsePush(MidiMessage.Channel(hex("c0 03"))))
    }

    @Test
    fun safetyBlocksForbidden() {
        val blocked = listOf("52 00 6e 64 2d", "52 00 6e 64 3f", "52 00 6e 60 29", "52 00 6e 60",
            "52 00 6e 64 20 00 02 00 00 00 00 00 00",
            "52 00 6e 64 20 00 02 f7 00", "f0 52 00 6e 60 f7", "52 01 6e 60", "52 00 6e 64 20 00 02 80 00",
            "", "f7", "b0 20 80", "c0 03 03 03", "52 00 6e 64 20 00 64 00 00 00 00 00",
            "52 00 6e 64 20 00 02") + (1..10).map { "52 00 6e %02x 00".format(it) }
        for (s in blocked) {
            try {
                Safety.check(hex(s))
                fail("not blocked: $s")
            } catch (e: IllegalStateException) {
            }
        }
        val allowed = listOf(Msg.IDENTITY, Msg.PATCH_INFO, Msg.ENTER_PC, Msg.LEAVE_PC, Msg.SELECTED, Msg.READ_EDIT,
            Msg.ACK, Msg.GLOBAL, Msg.readPatch(239), Msg.store(239), Msg.insertEffect(5), Msg.deleteEffect(5),
            Msg.moveEffect(5, 4)) + Msg.pressEffect(5) + Msg.changeType(5, 0x07090010) + Msg.selectSlot(239) +
            (0..5).flatMap { pos -> (0..15).flatMap { Msg.setParam(pos, it, 100) } }
        allowed.forEach { Safety.check(it) }
    }

    @Test
    fun builderRangeChecks() {
        val bad = listOf<() -> Any>({ Msg.setParam(6, 0, 0) }, { Msg.setParam(0, 126, 0) }, { Msg.selectSlot(240) },
            { Msg.selectSlot(512) }, { Msg.readPatch(-1) }, { Msg.store(240) }, { Msg.changeType(0, 0x20000000) },
            { Msg.insertEffect(6) }, { Msg.deleteEffect(-1) }, { Msg.moveEffect(0, 6) }, { Msg.pressEffect(6) })
        for (f in bad) {
            try {
                f()
                fail("accepted")
            } catch (e: IllegalArgumentException) {
            }
        }
        Msg.setParam(5, 125, 0).forEach { Safety.check(it) }
    }

    @Test
    fun autoSaveByte12() {
        val reply = ByteArray(20)
        assertFalse(parseAutoSave(reply))
        reply[12] = 1
        assertTrue(parseAutoSave(reply))
        assertFalse(parseAutoSave(ByteArray(8)))
    }
}
