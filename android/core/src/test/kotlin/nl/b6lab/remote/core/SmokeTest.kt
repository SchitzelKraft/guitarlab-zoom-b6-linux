package nl.b6lab.remote.core

import org.junit.Assert.assertEquals
import org.junit.Test

class SmokeTest {
    @Test
    fun smoke() {
        assertEquals("Codec", Codec::class.simpleName)
    }
}
