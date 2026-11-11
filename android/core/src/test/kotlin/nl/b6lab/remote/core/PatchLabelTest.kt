package nl.b6lab.remote.core

import org.junit.Test
import org.junit.Assert.assertEquals

class PatchLabelTest {
    @Test
    fun labelsLikeTheB6() {
        val expected = mapOf(
            0 to "A-001", 3 to "A-004", 4 to "B-005", 103 to "Z-104",
            104 to "AA-105", 207 to "AZ-208", 208 to "BA-209", 239 to "BH-240",
        )
        for ((slot, label) in expected) assertEquals("slot $slot", label, patchLabel(slot))
    }

    @Test
    fun bankLettersAlone() {
        assertEquals("Z", bankLetters(103))
        assertEquals("AZ", bankLetters(207))
        assertEquals("BH", bankLetters(239))
    }
}
