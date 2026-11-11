package nl.b6lab.remote.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Decides when to try to connect. [request] starts a run of up to [attempts] calls of [attempt], [delayMs]
 * apart, stopping at the first success, when [devicePresent] is false, or on [cancel]. A request is ignored
 * while a session [isConnected] or a run is already in progress.
 *
 * [linkLost] (the link ended while the B6 is still there, e.g. a timeout) starts such a run by itself. Those
 * automatic attempts share one budget of [attempts] until the next [request], so a link that keeps failing is not
 * retried forever; after that the user asks again (a Reconnect button calling [request]).
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
    private var automaticLeft = attempts
    /** Number of the current run; a cancelled run that ends late does not clear [running] of a newer one. */
    private var runs = 0

    private val _running = MutableStateFlow(false)

    /** A run is in progress. */
    val running: StateFlow<Boolean> = _running.asStateFlow()

    fun request() {
        automaticLeft = attempts
        run(automatic = false)
    }

    fun linkLost() {
        if (automaticLeft <= 0 || !devicePresent()) return
        run(automatic = true)
    }

    private fun run(automatic: Boolean) {
        if (isConnected() || job?.isActive == true) return
        _running.value = true
        val id = ++runs
        job = scope.launch {
            try {
                repeat(attempts) { n ->
                    if (automatic) {
                        if (automaticLeft <= 0) return@launch
                        automaticLeft -= 1
                    }
                    if (attempt()) return@launch
                    if (n == attempts - 1 || !devicePresent()) return@launch
                    delay(delayMs)
                }
            } finally {
                if (runs == id) _running.value = false
            }
        }
    }

    fun cancel() {
        runs += 1
        job?.cancel()
        job = null
        _running.value = false
    }
}
