package nl.b6lab.remote.core

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ReconnectorTest {
    private class Fixture(scope: TestScope, results: List<Boolean>, present: Boolean = true) {
        var calls = 0
        var connected = false
        val reconnector = Reconnector(
            scope, { connected }, { present },
            { val ok = results.getOrElse(calls) { false }; calls++; if (ok) connected = true; ok },
        )
    }

    @Test
    fun startWithDevicePresentOpensExactlyOnce() = runTest {
        val f = Fixture(this, listOf(true))
        f.reconnector.request()
        advanceUntilIdle()
        assertEquals(1, f.calls)
    }

    @Test
    fun transientFailureThenSuccessRetries() = runTest {
        val f = Fixture(this, listOf(false, false, true))
        f.reconnector.request()
        advanceUntilIdle()
        assertEquals(3, f.calls)
        assertEquals(2000, testScheduler.currentTime)
    }

    @Test
    fun givesUpAfterFourAttempts() = runTest {
        val f = Fixture(this, emptyList())
        f.reconnector.request()
        advanceUntilIdle()
        assertEquals(4, f.calls)
    }

    @Test
    fun noDeviceMeansNoRetry() = runTest {
        val f = Fixture(this, emptyList(), present = false)
        f.reconnector.request()
        advanceUntilIdle()
        assertEquals(1, f.calls)
    }

    @Test
    fun cancelDuringRetryStopsAttempts() = runTest {
        val f = Fixture(this, emptyList())
        f.reconnector.request()
        runCurrent()
        assertEquals(1, f.calls)
        f.reconnector.cancel()
        advanceTimeBy(10_000)
        assertEquals(1, f.calls)
    }

    @Test
    fun deviceAddedWhileConnectedDoesNothing() = runTest {
        val f = Fixture(this, listOf(true))
        f.reconnector.request()
        advanceUntilIdle()
        f.reconnector.request()
        advanceUntilIdle()
        assertEquals(1, f.calls)
    }

    @Test
    fun deviceAddedDuringRunDoesNotStartSecondRun() = runTest {
        val f = Fixture(this, listOf(false, true))
        f.reconnector.request()
        runCurrent()
        f.reconnector.request()
        advanceUntilIdle()
        assertEquals(2, f.calls)
    }
}
