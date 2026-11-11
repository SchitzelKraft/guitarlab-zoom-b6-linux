package nl.b6lab.remote.core

import java.util.zip.CRC32

/** Zoom B6 SysEx codec: 7-in-8 packing, 7-bit little endian values and the CRC tail. */
object Codec {
    /** Groups of 7 bytes, preceded by a byte holding their high bits (MSB first). */
    fun pack7(data: ByteArray): ByteArray {
        val out = ByteArray(packedLen(data.size))
        var o = 0
        var i = 0
        while (i < data.size) {
            val n = minOf(7, data.size - i)
            var h = 0
            for (j in 0 until n) if (data[i + j].toInt() and 0x80 != 0) h = h or (1 shl (6 - j))
            out[o++] = h.toByte()
            for (j in 0 until n) out[o++] = (data[i + j].toInt() and 0x7F).toByte()
            i += 7
        }
        return out
    }

    fun unpack7(d: ByteArray): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        var i = 0
        while (i < d.size) {
            val h = d[i].toInt()
            for (j in 0 until minOf(7, d.size - i - 1)) {
                val hi = if ((h shr (6 - j)) and 1 != 0) 0x80 else 0
                out.write(d[i + 1 + j].toInt() or hi)
            }
            i += 8
        }
        return out.toByteArray()
    }

    /** value as n 7-bit bytes, little endian. */
    fun to7(value: Long, n: Int): ByteArray = ByteArray(n) { ((value shr (7 * it)) and 0x7F).toByte() }

    fun from7(d: ByteArray, off: Int = 0, n: Int = d.size - off): Long {
        var v = 0L
        for (i in 0 until n) v = v or ((d[off + i].toLong() and 0xFF) shl (7 * i))
        return v
    }

    private fun crcInverted(data: ByteArray): Long = (CRC32().apply { update(data) }.value) xor 0xFFFFFFFFL

    /** 5 bytes of ~CRC32(data), 7-bit little endian. */
    fun crcTail(data: ByteArray): ByteArray = to7(crcInverted(data), 5)

    /** Length of pack7 output for [size] data bytes. */
    fun packedLen(size: Int): Int = (size / 7) * 8 + if (size % 7 != 0) size % 7 + 1 else 0

    /** Reads size:2, packed data and crc:5 at [off]; throws IllegalArgumentException("checksum mismatch"). */
    fun decodeBlock(m: ByteArray, off: Int): ByteArray {
        val size = from7(m, off, 2).toInt()
        val n = packedLen(size)
        require(off + 7 + n <= m.size) { "checksum mismatch" }
        val data = unpack7(m.copyOfRange(off + 2, off + 2 + n)).copyOf(size)
        val want = from7(m, off + 2 + n, 5)
        require(want == crcInverted(data)) { "checksum mismatch" }
        return data
    }
}

/** Splits a MIDI byte stream into SysEx and channel messages (same rules as B6._pump). */
class SysexAssembler(val onMessage: (MidiMessage) -> Unit) {
    private var sx: java.io.ByteArrayOutputStream? = null
    private val ch = ArrayList<Byte>(3)

    fun feed(bytes: ByteArray, offset: Int, count: Int) {
        for (k in offset until offset + count) {
            val b = bytes[k]
            val x = b.toInt() and 0xFF
            if (x >= 0xF8) continue                      // realtime bytes may appear anywhere
            if (x == 0xF0) {
                sx = java.io.ByteArrayOutputStream()
            } else if (x == 0xF7) {
                sx?.let { onMessage(MidiMessage.Sysex(it.toByteArray())) }
                sx = null
            } else if (sx != null) {
                sx!!.write(x)
            } else if (x >= 0x80) {
                ch.clear()
                ch.add(b)
            } else if (ch.isNotEmpty()) {
                ch.add(b)
            }
            if (ch.isNotEmpty()) {
                val want = if ((ch[0].toInt() and 0xF0) == 0xC0 || (ch[0].toInt() and 0xF0) == 0xD0) 2 else 3
                if (ch.size == want) {
                    onMessage(MidiMessage.Channel(ch.toByteArray()))
                    ch.clear()
                }
            }
        }
    }
}
