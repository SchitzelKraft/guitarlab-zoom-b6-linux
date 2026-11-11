package nl.b6lab.remote

import android.content.Context
import android.media.midi.MidiDevice
import android.media.midi.MidiDeviceInfo
import android.media.midi.MidiInputPort
import android.media.midi.MidiManager
import android.media.midi.MidiOutputPort
import android.media.midi.MidiReceiver
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.suspendCancellableCoroutine
import nl.b6lab.remote.core.MidiMessage
import nl.b6lab.remote.core.MidiTransport
import nl.b6lab.remote.core.SysexAssembler
import java.io.IOException
import kotlin.coroutines.resume

/**
 * The B6 over USB MIDI. The app sends on the device's input port 0 and receives on its output port 0.
 * Incoming bytes are reassembled by [SysexAssembler] (Android splits long SysEx over many callbacks).
 * Removal of the device, or a failed write, closes [incoming].
 */
class UsbMidiTransport private constructor(
    private val midi: MidiManager,
    private val device: MidiDevice,
    private val input: MidiInputPort,
    private val output: MidiOutputPort,
) : MidiTransport {
    private val channel = Channel<MidiMessage>(Channel.UNLIMITED)
    private val assembler = SysexAssembler {
        if (BuildConfig.DEBUG) {
            when (it) {
                is MidiMessage.Sysex -> trace("<<", byteArrayOf(0xF0.toByte()) + it.body + byteArrayOf(0xF7.toByte()))
                is MidiMessage.Channel -> trace("<<", it.bytes)
            }
        }
        channel.trySend(it)
    }
    private val removal = object : MidiManager.DeviceCallback() {
        override fun onDeviceRemoved(info: MidiDeviceInfo) {
            if (info.id == device.info.id) {
                if (BuildConfig.DEBUG) Log.d(TAG, "device removed (id ${info.id})")
                close("device removed")
            }
        }
    }
    private val receiver = object : MidiReceiver() {
        override fun onSend(msg: ByteArray, offset: Int, count: Int, timestamp: Long) {
            assembler.feed(msg, offset, count)
        }
    }

    @Volatile
    private var closed = false

    override val incoming: ReceiveChannel<MidiMessage> get() = channel

    @Suppress("DEPRECATION") // the Executor overload needs API 33
    private fun listen() {
        midi.registerDeviceCallback(removal, Handler(Looper.getMainLooper()))
    }

    init {
        output.connect(receiver)
        listen()
    }

    override fun send(bytes: ByteArray) {
        if (closed) return
        if (BuildConfig.DEBUG) trace(">>", bytes)
        try {
            input.send(bytes, 0, bytes.size)
        } catch (e: IOException) {
            close("write failed: ${e.message}")
        }
    }

    override fun close() = close("close requested")

    @Synchronized
    private fun close(reason: String) {
        if (closed) return
        closed = true
        if (BuildConfig.DEBUG) Log.d(TAG, "closed: $reason")
        runCatching { midi.unregisterDeviceCallback(removal) }
        runCatching { output.disconnect(receiver) }
        runCatching { output.close() }
        runCatching { input.close() }
        runCatching { device.close() }
        channel.close()
    }

    companion object {
        private const val TAG = "B6TRACE"

        private fun trace(prefix: String, bytes: ByteArray) {
            val hex = { b: ByteArray -> b.joinToString(" ") { "%02x".format(it) } }
            val text = if (bytes.size > 48) "${hex(bytes.copyOf(24))} ... (${bytes.size} bytes)" else hex(bytes)
            Log.d(TAG, "$prefix $text")
        }

        fun isB6(info: MidiDeviceInfo): Boolean =
            info.type == MidiDeviceInfo.TYPE_USB &&
                info.inputPortCount >= 1 && info.outputPortCount >= 1 &&
                info.properties.getString(MidiDeviceInfo.PROPERTY_PRODUCT)?.contains("B6") == true

        @Suppress("DEPRECATION")
        private fun devices(midi: MidiManager): Collection<MidiDeviceInfo> =
            if (Build.VERSION.SDK_INT >= 33) {
                midi.getDevicesForTransport(MidiManager.TRANSPORT_MIDI_BYTE_STREAM)
            } else {
                midi.devices.toList()
            }

        fun findB6(midi: MidiManager): MidiDeviceInfo? = devices(midi).firstOrNull(::isB6)

        /** The first B6 found, with input port 0 and output port 0 open; null when there is none or it cannot be opened. */
        suspend fun open(context: Context): UsbMidiTransport? {
            val midi = context.getSystemService(Context.MIDI_SERVICE) as MidiManager
            val info = findB6(midi) ?: return null
            val device = suspendCancellableCoroutine<MidiDevice?> { cont ->
                midi.openDevice(info, { dev -> cont.resume(dev) { _, d, _ -> d?.close() } }, Handler(Looper.getMainLooper()))
            } ?: return null
            if (BuildConfig.DEBUG) Log.d(TAG, "device opened (id ${info.id})")
            val input = device.openInputPort(0)
            val output = device.openOutputPort(0)
            if (input == null || output == null) {
                if (BuildConfig.DEBUG) Log.d(TAG, "ports not available (input=${input != null}, output=${output != null}), closing device")
                runCatching { input?.close() }
                runCatching { output?.close() }
                runCatching { device.close() }
                return null
            }
            if (BuildConfig.DEBUG) Log.d(TAG, "ports opened (input 0, output 0)")
            return UsbMidiTransport(midi, device, input, output)
        }
    }
}
