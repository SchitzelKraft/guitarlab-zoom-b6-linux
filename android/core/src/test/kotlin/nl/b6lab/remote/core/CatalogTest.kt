package nl.b6lab.remote.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CatalogTest {
    private fun res(name: String) = javaClass.getResource("/fixtures/$name")!!.readText()

    private val catalog = Catalog.load(res("catalog.json"))
    private val records = Json.parseToJsonElement(res("ptcf.json")).jsonArray.map { it.jsonObject }

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    private fun patchOf(slot: Int) =
        Ptcf.parse(hex(records.first { it["slot"]!!.jsonPrimitive.int == slot }["raw"]!!.jsonPrimitive.content))

    @Test
    fun loadsSvtAmp() {
        val e = catalog.effects[0x05890011]!!
        assertEquals("AMPG SVT", e.name)
        assertEquals(7, e.params.size)
        assertEquals("generated/svg/SVT_88.svg", e.svg)
    }

    @Test
    fun formatMatchesPython() {
        val cases = Json.parseToJsonElement(res("format.json")).jsonArray.map { it.jsonObject }
        assertEquals(200, cases.size)
        for (c in cases) {
            val id = c["fx_id"]!!.jsonPrimitive.int
            val i = c["index"]!!.jsonPrimitive.int
            val v = c["value"]!!.jsonPrimitive.int
            assertEquals("fx $id param $i value $v", c["text"]!!.jsonPrimitive.content,
                catalog.effects[id]!!.params[i].format(v))
        }
    }

    @Test
    fun groupsInGuitarLabOrder() {
        val names = catalog.byGroup().map { it.first }
        assertEquals(
            listOf("DYNAMICS", "FILTER", "DRIVE", "PREAMP", "BASS AMP", "CABINET", "MODULATION",
                "SFX", "DELAY", "REVERB", "PEDAL", "IR"), names)
        assertTrue(catalog.byGroup().all { it.second.isNotEmpty() })
    }

    private val ir = 0x1A000010
    private val light = catalog.effects.values.filter { it.dspLoad in 1.0..20.0 && it.group != "IR" }.first().fxId

    private fun chain(vararg ids: Int): Patch {
        var p = patchOf(1)
        while (p.effects.isNotEmpty()) p = Ptcf.deleteEntry(p, 0)!!
        ids.forEachIndexed { i, id ->
            p = Ptcf.setType(Ptcf.insertEntry(p, i)!!, i, id)
        }
        return p
    }

    @Test
    fun budgetRejectsOverload() {
        val p = chain(ir, ir)
        assertEquals(2, p.effects.size)
        assertEquals(172.9, catalog.effects[ir]!!.dspLoad * 2, 1e-9)
        assertFalse(catalog.fits(p, ir))
        assertTrue(catalog.fits(p, light))
        // replacing one IR by a light effect frees its load
        assertTrue(catalog.fits(p, ir, replaceSlot = p.effects[0].slot))
    }

    @Test
    fun sixEntriesRejectAdd() {
        val p = chain(light, light, light, light, light, light)
        assertEquals(6, p.effects.size)
        assertFalse(catalog.fits(p, light))
        assertTrue(catalog.fits(p, light, replaceSlot = p.effects[0].slot))
    }

    @Test
    fun unknownIdCountsZeroAndDoesNotCrash() {
        assertNull(catalog.effects[0x7F7F7F7F])
        assertTrue(catalog.fits(chain(light), 0x7F7F7F7F))
        assertNotNull(catalog.effects[light])
    }
}
