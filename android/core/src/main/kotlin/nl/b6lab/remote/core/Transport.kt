package nl.b6lab.remote.core

sealed class MidiMessage {
    /** A SysEx message without the F0 and F7 bytes. */
    class Sysex(val body: ByteArray) : MidiMessage() {
        override fun equals(other: Any?) = other is Sysex && body.contentEquals(other.body)
        override fun hashCode() = body.contentHashCode()
        override fun toString() = "Sysex(${body.joinToString(" ") { "%02x".format(it) }})"
    }

    /** A channel message: 3 bytes, or 2 for program change and channel pressure. */
    class Channel(val bytes: ByteArray) : MidiMessage() {
        override fun equals(other: Any?) = other is Channel && bytes.contentEquals(other.bytes)
        override fun hashCode() = bytes.contentHashCode()
        override fun toString() = "Channel(${bytes.joinToString(" ") { "%02x".format(it) }})"
    }
}

/** A MIDI link to a pedal. */
interface MidiTransport {
    /** Sends one complete message as it goes on the wire: SysEx with F0 and F7, channel messages raw. */
    fun send(bytes: ByteArray)

    /** Messages from the pedal, in order. Closed when the link ends. */
    val incoming: kotlinx.coroutines.channels.ReceiveChannel<MidiMessage>

    fun close()
}
