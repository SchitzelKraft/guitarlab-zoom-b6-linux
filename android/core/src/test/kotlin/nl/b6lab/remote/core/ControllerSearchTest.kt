package nl.b6lab.remote.core

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ControllerSearchTest {
    private val records = Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText())
        .jsonArray.map { it.jsonObject }
    private val catalog = Catalog.load(javaClass.getResource("/fixtures/catalog.json")!!.readText())
    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private fun image(slot: Int) = hex(records.first { it["slot"]!!.jsonPrimitive.int == slot }["raw"]!!.jsonPrimitive.content)

    @Test
    fun searchUsesTheIndexAndOpenSlotSwitchesThePedal() = runTest {
        val p = FakePedal(List(240) { image(it) })
        val s = B6Session(backgroundScope, p)
        s.connect()
        val c = RemoteController(backgroundScope, s, catalog)
        advanceTimeBy(60_000)
        runCurrent()
        assertEquals(240, c.indexed.value.indexed)
        val hit = c.search("z104").first()
        assertEquals(103, hit.slot)
        assertEquals("Z-104", hit.label)
        assertTrue(c.search("").isEmpty())
        c.openSlot(hit.slot)
        advanceTimeBy(1000)
        runCurrent()
        assertEquals(103, s.state.value.slot)
        assertEquals("Z-104", c.ui.value.header)
    }
}
