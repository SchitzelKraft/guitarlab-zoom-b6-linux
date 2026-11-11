package nl.b6lab.remote.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Decides when to try to connect. [request] starts a run of up to [attempts] calls of [attempt], [delayMs]
 * apart, stopping at the first success, when [devicePresent] is false, or on [cancel]. A request is ignored
 * while a session [isConnected] or a run is already in progress.
 */
class Reconnector(
    private val scope: CoroutineScope,
    private val isConnected: () -> Boolean,
    private val devicePresent: () -> Boolean,
    private val attempt: suspend () -> Boolean,
    private val attempts: Int = 4,
    private val delayMs: Long = 1000,
) {
    private var job: Job? = null

    fun request() {
        if (isConnected() || job?.isActive == true) return
        job = scope.launch {
            repeat(attempts) { n ->
                if (attempt()) return@launch
                if (n == attempts - 1 || !devicePresent()) return@launch
                delay(delayMs)
            }
        }
    }

    fun cancel() {
        job?.cancel()
        job = null
    }
}
