package nl.b6lab.remote.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
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

class PtcfTest {
    private val records: JsonArray =
        Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText()).jsonArray

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    private fun raw(o: JsonObject) = hex(o["raw"]!!.jsonPrimitive.content)

    private fun record(slot: Int) = records.map { it.jsonObject }.first { it["slot"]!!.jsonPrimitive.int == slot }

    @Test
    fun parsesEveryBackupPatchLikePython() {
        assertTrue(records.size >= 240)
        for (r in records) {
            val o = r.jsonObject
            val p = Ptcf.parse(raw(o))
            assertEquals(o["name"]!!.jsonPrimitive.content, p.name)
            val expected = o["effects"]!!.jsonArray
            assertEquals(expected.size, p.effects.size)
            for ((e, x) in p.effects.zip(expected.map { it.jsonObject })) {
                assertEquals(x["slot"]!!.jsonPrimitive.int, e.slot)
                assertEquals(x["fx_id"]!!.jsonPrimitive.content.toLong(), e.fxId.toLong() and 0xFFFFFFFFL)
                assertEquals(x["on"]!!.jsonPrimitive.boolean, e.on)
                assertEquals(x["params"]!!.jsonArray.map { it.jsonPrimitive.int }, e.params)
                assertEquals(x["is_tail"]!!.jsonPrimitive.boolean, e.isTail)
            }
        }
    }

    @Test
    fun encodeRoundTripsLikePython() {
        for (r in records) {
            val o = r.jsonObject
            assertArrayEquals(hex(o["encoded"]!!.jsonPrimitive.content), Ptcf.encode(Ptcf.parse(raw(o))))
        }
    }

    @Test
    fun chainEditsMatchPython() {
        var samples = 0
        for (r in records) {
            val o = r.jsonObject
            val edits = o["edits"]?.jsonObject ?: continue
            val p = Ptcf.parse(raw(o))
            val actual: Map<String, Patch?> = mapOf(
                "set_param" to Ptcf.setParam(p, 0, 0, 37),
                "set_on" to Ptcf.setOn(p, 0, false),
                "set_type" to Ptcf.setType(p, 0, 0x07090010),
                "insert_entry" to Ptcf.insertEntry(p, 1),
                "delete_entry" to Ptcf.deleteEntry(p, 0),
                "move_entry" to Ptcf.moveEntry(p, 0, 1),
            )
            assertEquals(edits.keys, actual.keys)
            for ((op, expected) in edits) {
                val got = actual[op]
                if (expected is JsonNull) assertNull("$op slot ${o["slot"]}", got)
                else assertArrayEquals("$op slot ${o["slot"]}", hex(expected.jsonPrimitive.content), Ptcf.encode(got!!))
                samples++
            }
            // immutable: the source patch is unchanged
            assertArrayEquals(hex(o["encoded"]!!.jsonPrimitive.content), Ptcf.encode(p))
        }
        assertEquals(18, samples)
    }

    @Test
    fun wideChainEditsMatchPython() {
        val o = record(-1)
        val p = Ptcf.parse(raw(o))
        val cases = o["wide_edits"]!!.jsonArray.map { it.jsonObject }
        assertEquals(10, cases.size)
        for (c in cases) {
            val op = c["op"]!!.jsonPrimitive.content
            val args = c["args"]!!.jsonArray.map { it.jsonPrimitive.int }
            val got = when (op) {
                "move_entry" -> Ptcf.moveEntry(p, args[0], args[1])
                "delete_entry" -> Ptcf.deleteEntry(p, args[0])
                else -> throw AssertionError("unknown op $op")
            }
            val expected = c["encoded"]!!
            if (expected is JsonNull) assertNull("$op $args", got)
            else assertArrayEquals("$op $args", hex(expected.jsonPrimitive.content), Ptcf.encode(got!!))
        }
    }

    @Test
    fun positionCountsTails() {
        val p = Ptcf.parse(raw(record(-1)))
        assertEquals(listOf(false, true, false, true, false), p.effects.map { it.isTail })
        assertEquals(0, Ptcf.position(p, 0))
        assertEquals(2, Ptcf.position(p, 2))
        assertEquals(4, Ptcf.position(p, 4))
        try {
            Ptcf.position(p, 3)
            fail("a tail has no position")
        } catch (e: IllegalArgumentException) {
        }
    }

    @Test
    fun tailKnobsNotEditable() {
        val p = Ptcf.parse(raw(record(-1)))
        assertFalse(p.effects[1].editable(0))
        assertTrue(p.effects[0].editable(0))
        assertFalse(p.effects[0].editable(Ptcf.PARAM_WIDTHS.size))
        assertEquals(4095, p.effects[0].maxValue(0))
        assertEquals(255, p.effects[0].maxValue(5))
        assertEquals(p.effects[0].fxId ushr 24, p.effects[0].categoryByte)
        try {
            Ptcf.setParam(p, 1, 0, 1)
            fail("tail knob must be refused")
        } catch (e: IllegalArgumentException) {
        }
    }

    @Test
    fun insertRefusedAtSixEntries() {
        val full = records.map { it.jsonObject }.map { Ptcf.parse(raw(it)) }.first { it.effects.size == Ptcf.MAX_ENTRIES }
        assertNull(Ptcf.insertEntry(full, 0))
        val small = records.map { it.jsonObject }.map { Ptcf.parse(raw(it)) }.first { it.effects.size < Ptcf.MAX_ENTRIES }
        assertEquals(small.effects.size + 1, Ptcf.insertEntry(small, 0)!!.effects.size)
    }

    @Test
    fun samePatchComparesNameAndEntries() {
        val a = raw(record(1))
        assertTrue(Ptcf.samePatch(a, a.copyOf()))
        assertFalse(Ptcf.samePatch(a, raw(record(3))))
        assertFalse(Ptcf.samePatch(a, byteArrayOf(1, 2, 3)))
        val edited = Ptcf.encode(Ptcf.setOn(Ptcf.parse(a), 0, !Ptcf.parse(a).effects[0].on))
        assertFalse(Ptcf.samePatch(a, edited))
    }
}
