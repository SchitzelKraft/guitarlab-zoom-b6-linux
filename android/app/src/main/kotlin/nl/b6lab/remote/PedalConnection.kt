package nl.b6lab.remote

import android.content.Context
import android.media.midi.MidiDeviceInfo
import android.media.midi.MidiManager
import android.os.Handler
import android.os.Looper
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import nl.b6lab.remote.core.B6Session
import nl.b6lab.remote.core.Connection
import nl.b6lab.remote.core.FakePedal
import nl.b6lab.remote.core.MidiTransport
import nl.b6lab.remote.core.PedalState

/**
 * Owns the transport and the session of the current connection. A session is single use, so every
 * (re)connection builds a new transport and a new session. Call [start] from onStart, [stop] from
 * onStop and [destroy] from onDestroy.
 */
class PedalConnection(context: Context) {
    private val app = context.applicationContext
    private val midi = app.getSystemService(Context.MIDI_SERVICE) as MidiManager
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val lock = Mutex()
    private val closer = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private val _state = MutableStateFlow<PedalState?>(null)

    /** State of the current session; null before the first connection attempt and when no B6 is found. */
    val state: StateFlow<PedalState?> = _state.asStateFlow()

    private val _isDemo = MutableStateFlow(false)
    val isDemo: StateFlow<Boolean> = _isDemo.asStateFlow()

    /** The session of the current connection, for the UI actions of Task 9/10. */
    @Volatile
    var session: B6Session? = null
        private set

    private var transport: MidiTransport? = null
    private var stateJob: Job? = null
    private var started = false

    private var retryJob: Job? = null

    private val callback = object : MidiManager.DeviceCallback() {
        override fun onDeviceAdded(info: MidiDeviceInfo) {
            if (UsbMidiTransport.isB6(info)) connectWithRetry()
        }
    }

    /** Up to [ATTEMPTS] attempts, 1 s apart, while a B6 is present and the connection does not come up. */
    private fun connectWithRetry() {
        retryJob?.cancel()
        retryJob = scope.launch {
            repeat(ATTEMPTS) { n ->
                if (!started || connectUsb()) return@launch
                if (UsbMidiTransport.findB6(midi) == null || n == ATTEMPTS - 1) return@launch
                delay(1000)
            }
        }
    }

    @Suppress("DEPRECATION") // the Executor overload needs API 33
    fun start() {
        if (started) return
        started = true
        if (!_isDemo.value) _state.value = PedalState(connection = Connection.CONNECTING)
        midi.registerDeviceCallback(callback, Handler(Looper.getMainLooper()))
        connectWithRetry()
    }

    fun stop() {
        if (!started) return
        started = false
        retryJob?.cancel()
        midi.unregisterDeviceCallback(callback)
        scope.launch {
            lock.withLock {
                teardown()
                _state.value = null
                _isDemo.value = false
            }
        }
    }

    /** The disconnect (`51`) outlives the activity: it runs on [closer] and is given 1 s. */
    fun destroy() {
        started = false
        retryJob?.cancel()
        closer.launch {
            withTimeoutOrNull(1000) { lock.withLock { teardown() } }
            transport?.close()
            scope.cancel()
        }
    }

    /** Runs the same session on a [FakePedal] with [patches] (808-byte slot images). */
    fun startDemo(patches: List<ByteArray>) {
        scope.launch {
            lock.withLock {
                teardown()
                _isDemo.value = true
                run(FakePedal(patches))
            }
        }
    }

    /** True when the session is connected (or connecting); false when there is no B6 or the attempt failed. */
    private suspend fun connectUsb(): Boolean = lock.withLock {
        if (!started) return@withLock true
        val current = _state.value
        if (current != null && current.connection != Connection.DISCONNECTED) return@withLock true
        teardown()
        _isDemo.value = false
        _state.value = PedalState(connection = Connection.CONNECTING)
        val t = UsbMidiTransport.open(app)
        if (t == null) {
            _state.value = null
            return@withLock false
        }
        run(t)
        _state.value?.connection == Connection.CONNECTED
    }

    private suspend fun run(t: MidiTransport) {
        val s = B6Session(scope, t)
        transport = t
        session = s
        stateJob = scope.launch { s.state.collect { _state.value = it } }
        s.connect()
    }

    private suspend fun teardown() {
        session?.disconnect()
        transport?.close()
        stateJob?.cancel()
        session = null
        transport = null
        stateJob = null
    }

    private companion object {
        const val ATTEMPTS = 4
    }
}
