package nl.b6lab.remote.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PatchIndexTest {
    private val records = Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText())
        .jsonArray.map { it.jsonObject }
    private val catalog = Catalog.load(javaClass.getResource("/fixtures/catalog.json")!!.readText())

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private val patches: Map<Int, Patch> = records.filter { it["slot"]!!.jsonPrimitive.int in 0..239 }.associate {
        it["slot"]!!.jsonPrimitive.int to Ptcf.parse(hex(it["raw"]!!.jsonPrimitive.content))
    }
    private val index = patches.entries.fold(PatchIndex()) { i, (s, p) -> i.with(s, PatchIndex.entryOf(p)) }

    private fun slots(q: String) = index.search(q, catalog).map { it.slot }

    @Test
    fun fixtureHas240Patches() {
        assertEquals(240, index.indexed)
    }

    @Test
    fun labelsAndNumbersFindSlot103First() {
        for (q in listOf("z104", "Z-104", "Z 104", "104", "0104")) assertEquals(q, 103, slots(q).first())
        assertEquals(1, index.search("104", catalog).first().rank)
    }

    @Test
    fun emptyQueryGivesNothing() {
        assertTrue(slots("").isEmpty())
        assertTrue(slots("  ").isEmpty())
    }

    @Test
    fun shortDigitsMatchExactThenPrefix() {
        val hits = index.search("10", catalog).filter { it.rank == 1 }
        assertEquals((listOf(9) + (99..108)), hits.map { it.slot })
        assertEquals(9, slots("10").first())
    }

    @Test
    fun nameMatchStartsWithBeforeContains() {
        val sweet = patches.entries.first { it.value.name.contains("Sweet", ignoreCase = true) }
        val hits = index.search("sweet", catalog)
        assertEquals(sweet.key, hits.first().slot)
        assertEquals(2, hits.first().rank)
        assertNull(hits.first().reason)
        val starts = hits.takeWhile { it.name.lowercase().replace(" ", "").startsWith("sweet") }
        assertTrue(hits.drop(starts.size).none { it.name.lowercase().replace(" ", "").startsWith("sweet") })
    }

    @Test
    fun svtListsEveryPatchWithTheEffectByNameOrEffect() {
        val svtId = catalog.effects.entries.first { it.value.name == "AMPG SVT" }.key
        val withSvt = patches.filter { (_, p) -> p.effects.any { !it.isTail && it.fxId == svtId } }.keys
        val hits = index.search("svt", catalog)
        val effectHits = hits.filter { it.rank == 3 }
        assertTrue(effectHits.isNotEmpty())
        // the reason names the first matching effect (a cabinet like SVT8x10 can match too)
        assertTrue(effectHits.all { it.reason!!.startsWith("uses ") })
        assertTrue(effectHits.any { it.reason == "uses AMPG SVT" })
        assertTrue(effectHits.filter { it.slot in withSvt }.all { h ->
            val first = h.fxIds.mapNotNull { catalog.effects[it]?.name }.first { it.lowercase().contains("svt") }
            h.reason == "uses $first"
        })
        // every patch with the effect is found (by name or by effect)
        assertEquals(withSvt, withSvt.intersect(hits.map { it.slot }.toSet()))
        // slot order inside the rank and each patch once
        assertEquals(effectHits.map { it.slot }.sorted(), effectHits.map { it.slot })
        assertEquals(hits.size, hits.map { it.slot }.toSet().size)
    }

    @Test
    fun emptyPatchesAreExcludedUnlessNumber() {
        val i = PatchIndex().with(5, IndexEntry("Empty", emptyList())).with(6, IndexEntry("Real", listOf(0)))
        assertTrue(i.search("empty", catalog).isEmpty())
        assertEquals(listOf(5), i.search("6", catalog).map { it.slot }.filter { it == 5 })
    }

    @Test
    fun unindexedSlotsOnlyMatchByNumber() {
        val i = PatchIndex()
        assertEquals(103, i.search("z104", catalog).single().slot)
        assertTrue(i.search("sweet", catalog).isEmpty())
    }

    @Test
    fun bestRankWins() {
        val i = PatchIndex().with(0, IndexEntry("10 Years", emptyList()))
        val hits = i.search("10", catalog)
        assertEquals(listOf(9), hits.map { it.slot }.take(1))
        assertEquals(1, hits.count { it.slot == 0 })
    }

    @Test
    fun leadingZerosAreDroppedAndZeroIsNoNumber() {
        val expected = listOf(0) + (9..18) + (99..198)
        assertEquals(expected, index.search("1", catalog).filter { it.rank == 1 }.map { it.slot })
        assertEquals(expected, index.search("01", catalog).filter { it.rank == 1 }.map { it.slot })
        assertTrue(slots("0").isEmpty())
        assertTrue(slots("00").isEmpty())
    }

    @Test
    fun zeroPaddedDigitsGiveExactlyTheSameHitsAsUnpadded() {
        for ((a, b) in listOf("01" to "1", "0104" to "104", "010" to "10", "08" to "8")) {
            assertEquals(index.search(a, catalog), index.search(b, catalog))
        }
    }
}
