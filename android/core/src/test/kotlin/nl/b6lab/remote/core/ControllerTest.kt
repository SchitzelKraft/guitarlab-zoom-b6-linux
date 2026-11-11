package nl.b6lab.remote.core

import kotlinx.coroutines.ExperimentalCoroutinesApi
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ControllerTest {
    private val records = Json.parseToJsonElement(javaClass.getResource("/fixtures/ptcf.json")!!.readText())
        .jsonArray.map { it.jsonObject }
    private val catalog = Catalog.load(javaClass.getResource("/fixtures/catalog.json")!!.readText())

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private fun image(slot: Int) = hex(records.first { it["slot"]!!.jsonPrimitive.int == slot }["raw"]!!.jsonPrimitive.content)
    private fun pedal(autoSave: Boolean = false) = FakePedal(List(240) { image(it) }, autoSave)

    private class Rig(val p: FakePedal, val s: B6Session, val c: RemoteController)

    private suspend fun TestScope.rig(p: FakePedal = pedal()): Rig {
        val s = B6Session(backgroundScope, p)
        s.connect()
        val c = RemoteController(backgroundScope, s, catalog)
        runCurrent()
        return Rig(p, s, c)
    }

    private fun TestScope.settle() {
        advanceTimeBy(1000)
        runCurrent()
    }

    private fun framed(body: ByteArray) = byteArrayOf(0xF0.toByte()) + body + byteArrayOf(0xF7.toByte())

    private fun knobMessages(p: FakePedal, pos: Int, index: Int, max: Int): List<ByteArray> {
        val all = (0..max).map { framed(Msg.setParam(pos, index, it)[1]) }
        return p.sent.filter { m -> all.any { it.contentEquals(m) } }
    }

    @Test
    fun tapOnlySelectsNeverToggles() = runTest {
        val r = rig()
        val before = r.p.sent.size
        assertTrue(r.c.ui.value.pedals[0].selected)
        val second = r.c.ui.value.pedals[1].slot
        r.c.tapPedal(second)
        settle()
        assertEquals(before, r.p.sent.size)
        assertTrue(r.c.ui.value.pedals[1].selected)
        assertFalse(r.c.ui.value.pedals[0].selected)
        val on = r.c.ui.value.pedals[1].on
        r.c.tapPedal(second)
        settle()
        assertEquals(before, r.p.sent.size)
        assertEquals(on, r.s.state.value.edit!!.effects[second].on)
        assertEquals(on, r.c.ui.value.pedals[1].on)
    }

    @Test
    fun togglePedalKeepsSelection() = runTest {
        val r = rig()
        val other = r.c.ui.value.pedals[1].slot
        assertTrue(r.c.ui.value.pedals[0].selected)
        val on = r.c.ui.value.pedals[1].on
        r.c.togglePedal(other)
        settle()
        assertEquals(!on, r.s.state.value.edit!!.effects[other].on)
        assertEquals(!on, r.c.ui.value.pedals[1].on)
        assertTrue(r.c.ui.value.pedals[0].selected)
        assertFalse(r.c.ui.value.pedals[1].selected)
    }

    @Test
    fun demoPatchesAreNotDirtyAfterConnect() = runTest {
        val files = listOf(0, 2, 100).map { java.io.File("../app/src/main/assets/generated/demo/$it.bin") }
        Assume.assumeTrue("demo patches missing: run android/prepare.sh", files.all { it.exists() })
        val demo = files.map { it.readBytes() }
        val r = rig(FakePedal(demo))
        assertFalse(r.s.state.value.dirty)
        assertFalse(r.c.ui.value.canSave)
        for (i in 0 until 6) {
            r.c.nextPatch()
            settle()
            assertFalse("slot ${r.s.state.value.slot}", r.c.ui.value.canSave)
        }
    }

    @Test
    fun noChangeAfterConnectMeansNotDirty() = runTest {
        val r = rig()
        assertFalse(r.s.state.value.dirty)
        assertFalse(r.c.ui.value.canSave)
    }

    @Test
    fun knobThrottleSendsLastValue() = runTest {
        val r = rig()
        val knob = r.c.ui.value.knobs.first()
        val max = knob.max
        for (i in 0 until 100) {
            r.c.dragKnob(knob.index, i % (max + 1))
            advanceTimeBy(1)
        }
        val final = 99 % (max + 1)
        settle()
        val sends = knobMessages(r.p, 0, knob.index, max)
        assertTrue("sends: ${sends.size}", sends.size <= 4)
        assertTrue(sends.isNotEmpty())
        assertTrue(sends.last().contentEquals(framed(Msg.setParam(0, knob.index, final)[1])))
        assertEquals(final, r.c.ui.value.knobs.first { it.index == knob.index }.value)
    }

    @Test
    fun knobClamped() = runTest {
        val r = rig()
        val knob = r.c.ui.value.knobs.first()
        r.c.dragKnob(knob.index, 100000)
        settle()
        assertEquals(knob.max, r.s.state.value.edit!!.effects[0].params[knob.index])
        r.c.dragKnob(knob.index, -5)
        settle()
        assertEquals(0, r.s.state.value.edit!!.effects[0].params[knob.index])
    }

    @Test
    fun tailsNotShown() = runTest {
        val r = rig()
        assertEquals(3, r.c.ui.value.pedals.size)
        assertEquals(5, r.s.state.value.edit!!.effects.size)
        assertTrue(r.c.ui.value.pedals.all { !r.s.state.value.edit!!.effects[it.slot].isTail })
    }

    @Test
    fun noFreePlacesWhenFull() = runTest {
        val r = rig()
        r.p.footswitchTo(57)
        settle()
        assertEquals(2, r.s.state.value.edit!!.effects.size)
        assertEquals(4, r.c.ui.value.freePlaces)
        r.p.footswitchTo(16)
        settle()
        assertEquals(6, r.s.state.value.edit!!.effects.size)
        assertEquals(0, r.c.ui.value.freePlaces)
    }

    @Test
    fun fitsFollowsShownPatch() = runTest {
        val r = rig()
        r.p.footswitchTo(57)
        settle()
        val edit = r.s.state.value.edit!!
        val fx = catalog.effects.values.first { catalog.fits(edit, it.fxId) }
        assertTrue(r.c.fits(fx.fxId, null))
        r.p.footswitchTo(16)
        settle()
        val full = r.s.state.value.edit!!
        assertEquals(6, full.effects.size)
        assertFalse(r.c.fits(fx.fxId, null))
        assertEquals(catalog.fits(full, fx.fxId, 2), r.c.fits(fx.fxId, 2))
    }

    @Test
    fun staleChooserIsRefusedAfterPatchChange() = runTest {
        val r = rig()
        val opened = r.c.currentRef()!!
        val slot = r.c.ui.value.pedals.first().slot
        val fx = catalog.effects.values.first { it.fxId != r.s.state.value.edit!!.effects[slot].fxId && catalog.fits(r.s.state.value.edit!!, it.fxId, slot) }
        r.p.footswitchTo(57)
        settle()
        val before = r.s.state.value.edit!!.effects.map { it.fxId }
        assertTrue(r.c.currentRef() != opened)
        r.c.remove(slot, opened)
        settle()
        assertEquals(before, r.s.state.value.edit!!.effects.map { it.fxId })
        r.c.choose(fx.fxId, slot, opened)
        settle()
        assertEquals(before, r.s.state.value.edit!!.effects.map { it.fxId })
    }

    @Test
    fun chooseDoesNothingWhenItDoesNotFit() = runTest {
        val r = rig()
        r.p.footswitchTo(16)
        settle()
        val before = r.p.sent.size
        val fx = catalog.effects.values.first { !r.c.fits(it.fxId, null) }
        r.c.choose(fx.fxId, null)
        settle()
        assertEquals(before, r.p.sent.size)
    }

    @Test
    fun nextPatchWraps() = runTest {
        val r = rig()
        r.p.footswitchTo(239)
        settle()
        assertEquals(239, r.s.state.value.slot)
        r.c.nextPatch()
        settle()
        assertEquals(0, r.s.state.value.slot)
        r.c.previousPatch()
        settle()
        assertEquals(239, r.s.state.value.slot)
    }

    @Test
    fun headerFormat() = runTest {
        val r = rig()
        assertEquals("BANK 01 · A", r.c.ui.value.header)
        r.p.footswitchTo(239)
        settle()
        assertEquals("BANK 60 · D", r.c.ui.value.header)
    }

    @Test
    fun autoSaveWarningShown() = runTest {
        assertTrue(rig(pedal(autoSave = true)).c.ui.value.autoSaveWarning)
        assertFalse(rig().c.ui.value.autoSaveWarning)
    }

    @Test
    fun selectionSurvivesPushOfSamePatch() = runTest {
        val r = rig()
        r.c.tapPedal(2)
        r.p.turnKnob(0, 0, 3)
        settle()
        assertEquals(3, r.s.state.value.edit!!.effects[0].params[0])
        assertTrue(r.c.ui.value.pedals.first { it.slot == 2 }.selected)
    }

    @Test
    fun selectionResetsOnPatchChange() = runTest {
        val r = rig()
        r.c.tapPedal(2)
        r.p.footswitchTo(1)
        settle()
        assertEquals(1, r.s.state.value.slot)
        assertTrue(r.c.ui.value.pedals.first().selected)
        assertEquals(1, r.c.ui.value.pedals.count { it.selected })
    }

    @Test
    fun staleScreenIsRefusedAndErrorShown() = runTest {
        val r = rig()
        // the pedal changes patch; the session has not processed the push before the tap's operation runs
        r.p.footswitchTo(1)
        r.c.togglePedal(0)
        settle()
        assertEquals("patch changed on the pedal", r.c.ui.value.error)
        assertEquals(1, r.s.state.value.slot)
    }

    @Test
    fun chooseInsertsAtEndThenChangesType() = runTest {
        val r = rig()
        r.p.footswitchTo(57)
        settle()
        val fx = catalog.effects.values.first { catalog.fits(r.s.state.value.edit!!, it.fxId) }
        val n = r.s.state.value.edit!!.effects.size
        r.c.choose(fx.fxId, null)
        settle()
        assertNull(r.c.ui.value.error)
        assertEquals(n + 1, r.s.state.value.edit!!.effects.size)
        assertEquals(fx.fxId, r.s.state.value.edit!!.effects[n].fxId)
    }

    @Test
    fun removeAndSaveGoThroughTheSession() = runTest {
        val r = rig()
        r.c.remove(r.c.ui.value.pedals.last().slot)
        settle()
        assertNull(r.c.ui.value.error)
        assertTrue(r.c.ui.value.canSave)
        r.c.save()
        settle()
        assertNull(r.c.ui.value.error)
        assertFalse(r.c.ui.value.canSave)
    }

    @Test
    fun nothingFitsGivesNoFreePlaces() = runTest {
        val r = rig()
        assertEquals(5, r.s.state.value.edit!!.effects.size)
        assertEquals(0, r.c.ui.value.freePlaces)
    }

    @Test
    fun changeTypeKeepsSelection() = runTest {
        val r = rig()
        val third = r.c.ui.value.pedals[2].slot
        r.c.tapPedal(third)
        val fx = catalog.effects.values.first { it.fxId != r.s.state.value.edit!!.effects[third].fxId && catalog.fits(r.s.state.value.edit!!, it.fxId, third) }
        r.c.choose(fx.fxId, third)
        settle()
        assertNull(r.c.ui.value.error)
        assertEquals(fx.fxId, r.s.state.value.edit!!.effects[third].fxId)
        assertEquals(third, r.c.ui.value.pedals.single { it.selected }.slot)
    }

    @Test
    fun chooseNewSelectsTheNewPedal() = runTest {
        val r = rig()
        r.p.footswitchTo(57)
        settle()
        val fx = catalog.effects.values.first { catalog.fits(r.s.state.value.edit!!, it.fxId) }
        r.c.choose(fx.fxId, null)
        settle()
        assertNull(r.c.ui.value.error)
        assertEquals(2, r.c.ui.value.pedals.single { it.selected }.slot)
    }

    @Test
    fun removeSelectedFallsBack() = runTest {
        val r = rig()
        r.p.footswitchTo(1)
        settle()
        val last = r.c.ui.value.pedals.last().slot
        r.c.tapPedal(last)
        r.c.remove(last)
        settle()
        assertNull(r.c.ui.value.error)
        val sel = r.c.ui.value.pedals.single { it.selected }
        assertEquals(r.c.ui.value.pedals.last().slot, sel.slot)
    }

    @Test
    fun pendingDragDroppedOnPatchChange() = runTest {
        val r = rig()
        val knob = r.c.ui.value.knobs.first()
        r.c.dragKnob(knob.index, knob.max)
        r.p.footswitchTo(1)
        runCurrent()
        val before = r.s.state.value.edit!!.effects[0].params[knob.index]
        settle()
        assertEquals(1, r.s.state.value.slot)
        assertEquals(before, r.s.state.value.edit!!.effects[0].params[knob.index])
        assertEquals(0, knobMessages(r.p, 0, knob.index, 1000).size)
    }

    @Test
    fun tapOnUnknownPedalIgnored() = runTest {
        val r = rig()
        r.c.tapPedal(1)
        assertTrue(r.c.ui.value.pedals[0].selected)
    }
}

class ParamDisplayTest {
    @Test
    fun plainNumberWithoutDisplayInfo() {
        assertEquals("raw 4", ParamInfo("x", 10, null, null, 0, null).format(4))
        assertEquals("4", ParamInfo("x", 10, null, null, 0, null).display(4))
        assertEquals("3.0", ParamInfo("x", 10, "1", "0.5", 1, null).display(4))
    }
}
