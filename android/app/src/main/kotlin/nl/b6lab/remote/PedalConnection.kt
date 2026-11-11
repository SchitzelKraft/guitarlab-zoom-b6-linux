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

    private val callback = object : MidiManager.DeviceCallback() {
        override fun onDeviceAdded(info: MidiDeviceInfo) {
            if (!UsbMidiTransport.isB6(info)) return
            scope.launch {
                // the device may not be ready to open right after it is announced
                repeat(4) {
                    if (connectUsb()) return@launch
                    delay(500)
                }
            }
        }
    }

    @Suppress("DEPRECATION") // the Executor overload needs API 33
    fun start() {
        if (started) return
        started = true
        midi.registerDeviceCallback(callback, Handler(Looper.getMainLooper()))
        scope.launch { connectUsb() }
    }

    fun stop() {
        if (!started) return
        started = false
        midi.unregisterDeviceCallback(callback)
        scope.launch {
            lock.withLock {
                teardown()
                _state.value = null
                _isDemo.value = false
            }
        }
    }

    fun destroy() {
        scope.cancel()
        transport?.close()
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

    /** True when a connection is up or was attempted with a B6 present; false when there is no B6 to open. */
    private suspend fun connectUsb(): Boolean = lock.withLock {
        if (!started) return@withLock true
        val current = _state.value
        if (current != null && current.connection != Connection.DISCONNECTED) return@withLock true
        teardown()
        _isDemo.value = false
        val t = UsbMidiTransport.open(app) ?: return@withLock false
        run(t)
        true
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
}
