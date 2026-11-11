package nl.b6lab.remote.core

/** Pedal messages B6 Lab sends, as SysEx bodies (no F0/F7) or raw channel messages. */
object Msg {
    private val HDR = byteArrayOf(0x52, 0x00, 0x6E)

    private fun b(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }
    private fun sx(vararg tail: Int) = HDR + b(*tail)
    private fun sx(vararg tail: ByteArray) = tail.fold(HDR) { a, t -> a + t }
    private fun ctl(a: Int, vararg rest: Int) = sx(0x64, 0x20, 0x00) + b(a, *rest)

    val IDENTITY = b(0x7E, 0x7F, 0x06, 0x01)
    val PATCH_INFO = sx(0x44)
    val ENTER_PC = sx(0x50)
    val LEAVE_PC = sx(0x51)
    val SELECTED = sx(0x33)
    val READ_EDIT = sx(0x64, 0x13)
    val ACK = sx(0x00, 0x00)
    val GLOBAL = sx(0x64, 0x0A)

    private fun pos(p: Int) = p.also { require(it in 0..5) { "position $it" } }
    private fun slot(s: Int) = s.also { require(it in 0..239) { "slot $it" } }

    private fun slotBytes(slot: Int) = slot(slot).let { b(0, 0, slot / 4, 0, slot % 4, 0) }

    fun readPatch(slot: Int) = sx(0x46) + slotBytes(slot)
    fun store(slot: Int) = sx(0x64, 0x0D) + slotBytes(slot)

    fun selectSlot(slot: Int): List<ByteArray> = slot(slot).let {
        listOf(b(0xB0, 0x00, 0x00), b(0xB0, 0x20, slot / 4), b(0xC0, slot % 4))
    }

    private fun position(pos: Int) = ctl(0x64, 0x01) + Codec.to7(pos(pos).toLong(), 5)

    fun pressEffect(pos: Int): List<ByteArray> = listOf(1L, 0L).flatMap { v ->
        listOf(position(pos), ctl(0x5A, 0x00) + Codec.to7(v, 5))
    }

    fun setParam(pos: Int, index: Int, value: Int): List<ByteArray> {
        require(index in 0..125) { "param index $index" }
        require(value >= 0) { "value $value" }
        return listOf(position(pos), ctl(pos(pos), index + 2) + Codec.to7(value.toLong(), 5))
    }

    fun changeType(pos: Int, fxId: Int): List<ByteArray> {
        require(fxId in 0..0x1FFFFFFF) { "effect id $fxId" }
        return listOf(position(pos), ctl(pos, 0x01) + Codec.to7(fxId.toLong(), 5))
    }

    fun insertEffect(pos: Int) = ctl(0x64, 0x07) + Codec.to7(pos(pos).toLong(), 5)
    fun deleteEffect(pos: Int) = ctl(0x64, 0x08) + Codec.to7(pos(pos).toLong(), 5)
    fun moveEffect(src: Int, dst: Int) = ctl(0x64, 0x09, pos(src), pos(dst), 0, 0, 0)
}

sealed class Push {
    data class PatchChanged(val slot: Int) : Push()
    data class ParamChanged(val pos: Int, val module: Int, val param: Int, val value: Int) : Push()
    object Ack : Push()
    data class Error(val code: Int) : Push()
    class Other(val body: ByteArray) : Push()
}

/** Classify a message from the pedal; null for channel messages. */
fun parsePush(m: MidiMessage): Push? {
    val body = (m as? MidiMessage.Sysex)?.body ?: return null
    fun at(i: Int) = body[i].toInt() and 0xFF
    val ours = body.size >= 5 && at(0) == 0x52 && at(1) == 0x00 && at(2) == 0x6E
    if (!ours) return Push.Other(body)
    if (at(3) == 0x00) return if (at(4) == 0x00) Push.Ack else Push.Error(at(4))
    if (at(3) == 0x64 && at(4) == 0x26 && body.size >= 10) {
        return Push.PatchChanged(at(7) * 4 + at(9))
    }
    if (at(3) == 0x64 && at(4) == 0x20 && body.size >= 13) {
        val module = at(6)
        return Push.ParamChanged(module, module, at(7), Codec.from7(body, 8, 5).toInt())
    }
    return Push.Other(body)
}

/** Auto save is on when byte 12 of the `64 09` global reply is non-zero (as `B6.global_info`). */
fun parseAutoSave(globalReply: ByteArray): Boolean = globalReply.size > 12 && globalReply[12].toInt() != 0

object Safety {
    /** Throws when [body] is a SysEx body that must never reach the pedal. */
    fun check(body: ByteArray) {
        fun at(i: Int) = body[i].toInt() and 0xFF
        fun deny(why: String): Nothing =
            throw IllegalStateException("blocked pedal message ($why): " + body.joinToString(" ") { "%02x".format(it) })
        if (body.isEmpty()) deny("empty")
        if (at(0) >= 0xF0) deny("framing or system byte")
        if (at(0) >= 0x80) {   // channel message
            if (body.size !in 2..3 || (1 until body.size).any { at(it) >= 0x80 }) deny("bad channel message")
            return
        }
        if (body.any { it < 0 }) deny("byte of 0x80 or higher inside SysEx")
        if (at(0) != 0x52) return
        if (body.size < 4 || at(1) != 0x00 || at(2) != 0x6E) deny("unknown device or short")
        val cmd = at(3)
        if (cmd in 0x01..0x0A) deny("command 01-0A")
        if (cmd == 0x60) deny("command 60")
        if (cmd == 0x64 && body.size >= 5) {
            val sub = at(4)
            if (sub == 0x2D || sub == 0x3F) deny("64 ${"%02x".format(sub)}")
            if (sub == 0x20) {
                // 64 20 00 <module> <param> ...: param 0 is direct on/off, only the 5A press is allowed
                if (body.size < 8) deny("short parameter message")
                if (at(7) == 0x00 && at(6) != 0x5A) deny("direct on/off")
            }
        }
    }
}
