package nl.b6lab.remote.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class CodecTest {
    private fun fixture(name: String): JsonArray =
        Json.parseToJsonElement(javaClass.getResource("/fixtures/$name")!!.readText()).jsonArray

    private fun hex(o: JsonObject, key: String): ByteArray {
        val s = o[key]!!.jsonPrimitive.content
        return ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    }

    @Test
    fun packMatchesPython() {
        val vectors = fixture("codec.json")
        assertTrue(vectors.size >= 20)
        for (v in vectors) {
            val o = v.jsonObject
            val data = hex(o, "data")
            val packed = hex(o, "packed")
            assertArrayEquals(packed, Codec.pack7(data))
            assertEquals(packed.size, Codec.packedLen(data.size))
            assertArrayEquals(data, Codec.unpack7(packed).copyOf(data.size))
            assertArrayEquals(hex(o, "crc_tail"), Codec.crcTail(data))
        }
    }

    @Test
    fun to7From7RoundTrip() {
        assertArrayEquals(byteArrayOf(0x7F, 0x01), Codec.to7(0xFF, 2))
        assertEquals(0xFFFFFFFFL, Codec.from7(Codec.to7(0xFFFFFFFFL, 5)))
        assertEquals(5L, Codec.from7(byteArrayOf(9, 5, 0), 1, 1))
    }

    @Test
    fun decodesRealReplies() {
        for (r in fixture("replies.json")) {
            val o = r.jsonObject
            assertArrayEquals(hex(o, "data"), Codec.decodeBlock(hex(o, "body"), 10))
        }
    }

    @Test
    fun corruptedReplyThrows() {
        val o = fixture("replies.json")[0].jsonObject
        val body = hex(o, "body")
        body[20] = (body[20].toInt() xor 0x01).toByte()
        try {
            Codec.decodeBlock(body, 10)
            fail("expected checksum mismatch")
        } catch (e: IllegalArgumentException) {
            assertEquals("checksum mismatch", e.message)
        }
    }

    private fun collect(): Pair<MutableList<MidiMessage>, SysexAssembler> {
        val out = mutableListOf<MidiMessage>()
        return out to SysexAssembler { out.add(it) }
    }

    @Test
    fun assemblerJoinsChunks() {
        val body = hex(fixture("replies.json")[0].jsonObject, "body")
        assertEquals(941, body.size)
        val stream = byteArrayOf(0xF0.toByte()) + body + byteArrayOf(0xF7.toByte())
        val (out, asm) = collect()
        var pos = 0
        var i = 0
        while (pos < stream.size) {
            val n = minOf(stream.size - pos, 1 + (i * 7) % 23)
            val chunk = stream.copyOfRange(pos, pos + n)
            val withRt = chunk.copyOfRange(0, n / 2) + byteArrayOf(0xF8.toByte()) + chunk.copyOfRange(n / 2, n)
            asm.feed(withRt, 0, withRt.size)
            pos += n
            i++
        }
        assertTrue(i > 30)
        assertEquals(1, out.size)
        assertEquals(MidiMessage.Sysex(body), out[0])
    }

    @Test
    fun assemblerRespectsOffsetAndCount() {
        val (out, asm) = collect()
        val buf = byteArrayOf(0x55, 0xF0.toByte(), 1, 2, 0xF7.toByte(), 0x55)
        asm.feed(buf, 1, 4)
        assertEquals(listOf<MidiMessage>(MidiMessage.Sysex(byteArrayOf(1, 2))), out)
    }

    @Test
    fun assemblerSplitsChannelMessages() {
        val (out, asm) = collect()
        val b = intArrayOf(0xB0, 0x00, 0x00, 0xB0, 0x20, 0x3B, 0xC0, 0x03).map { it.toByte() }.toByteArray()
        asm.feed(b, 0, b.size)
        assertEquals(3, out.size)
        assertEquals(listOf(3, 3, 2), out.map { (it as MidiMessage.Channel).bytes.size })
        assertEquals(MidiMessage.Channel(byteArrayOf(0xC0.toByte(), 3)), out[2])
    }
}
