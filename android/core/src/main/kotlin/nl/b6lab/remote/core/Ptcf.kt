package nl.b6lab.remote.core

import java.math.BigInteger

/** One EDTB entry (192 bits, little endian). `raw` is the source of truth; the rest is decoded from it. */
class Effect(
    val slot: Int,
    val fxId: Int,
    val on: Boolean,
    val params: List<Int>,
    val isTail: Boolean,
    val raw: BigInteger,
) {
    /** Every decoded knob of a non-tail entry. */
    fun editable(index: Int): Boolean = !isTail && index in Ptcf.PARAM_WIDTHS.indices

    fun maxValue(index: Int): Int = (1 shl Ptcf.PARAM_WIDTHS[index]) - 1

    /** Effect ID high byte: the category (0x03 DRIVE, 0x07 MODULATION, ...). */
    val categoryByte: Int get() = fxId ushr 24

    internal fun withRaw(newRaw: BigInteger, newSlot: Int = slot): Effect = Ptcf.effectFromRaw(newSlot, newRaw)

    override fun equals(other: Any?) =
        other is Effect && other.slot == slot && other.raw == raw

    override fun hashCode() = raw.hashCode() * 31 + slot

    override fun toString() = "Effect(slot=$slot, fxId=0x${fxId.toString(16)}, on=$on, tail=$isTail)"
}

/** A parsed PTCF patch. Immutable: edits in [Ptcf] return new patches. */
class Patch internal constructor(
    val name: String,
    val effects: List<Effect>,
    /** The bytes this patch was parsed from (unchanged by edits). */
    val raw: ByteArray,
    internal val effectIds: List<Int>,
    internal val version: Int,
    internal val headerUnknown: ByteArray,
    internal val nameRaw: ByteArray,
    internal val chunks: List<Pair<String, ByteArray>>,
    /** The entry count written to the header (the parsed count until an insert, delete or move). */
    val slots: Int,
) {
    internal fun copy(
        effects: List<Effect> = this.effects,
        effectIds: List<Int> = this.effectIds,
        slots: Int = this.slots,
    ) = Patch(name, effects, raw, effectIds, version, headerUnknown, nameRaw, chunks, slots)
}

object Ptcf {
    const val MAX_ENTRIES = 6
    const val PARAM_START = 30
    const val ENTRY = 24

    /** Knob field widths: five 12-bit knobs, then 8-bit ones up to the end of the entry. */
    val PARAM_WIDTHS: List<Int> = List(5) { 12 } + List((ENTRY * 8 - PARAM_START - 60) / 8) { 8 }

    private val ID_MASK = BigInteger.valueOf(0x1FFFFFFFL)

    internal fun effectFromRaw(slot: Int, v: BigInteger): Effect {
        val fxId = v.shiftRight(1).and(ID_MASK).toInt()
        val params = ArrayList<Int>(PARAM_WIDTHS.size)
        var pos = PARAM_START
        for (w in PARAM_WIDTHS) {
            params.add(v.shiftRight(pos).toInt() and ((1 shl w) - 1))
            pos += w
        }
        return Effect(slot, fxId, v.testBit(0), params, fxId == 1, v)
    }

    private fun u32(d: ByteArray, o: Int): Long =
        (d[o].toLong() and 0xFF) or ((d[o + 1].toLong() and 0xFF) shl 8) or
            ((d[o + 2].toLong() and 0xFF) shl 16) or ((d[o + 3].toLong() and 0xFF) shl 24)

    private fun putU32(out: java.io.ByteArrayOutputStream, v: Long) {
        for (i in 0 until 4) out.write(((v ushr (8 * i)) and 0xFF).toInt())
    }

    private fun ascii(b: ByteArray, from: Int, to: Int): String =
        String(CharArray(to - from) { val c = b[from + it].toInt() and 0xFF; if (c < 0x80) c.toChar() else '�' })

    fun parse(data: ByteArray): Patch {
        require(data.size >= 4 && data[0] == 'P'.code.toByte() && data[1] == 'T'.code.toByte() &&
            data[2] == 'C'.code.toByte() && data[3] == 'F'.code.toByte()) { "not a PTCF patch" }
        require(data.size >= 0x24) { "truncated PTCF patch" }
        val used = u32(data, 4)
        val version = u32(data, 8).toInt()
        val n = u32(data, 12)
        require(used <= data.size && 0x24 + 4 * n <= used) { "truncated PTCF patch" }
        val nameEnd = (0x1A until 0x24).firstOrNull { data[it].toInt() == 0 } ?: 0x24
        val name = ascii(data, 0x1A, nameEnd).trimEnd()
        val ids = List(n.toInt()) { u32(data, 0x24 + 4 * it).toInt() }
        val effects = ArrayList<Effect>()
        val chunks = ArrayList<Pair<String, ByteArray>>()
        var p = 0x24 + 4 * n.toInt()
        while (p + 8 <= used) {
            val tag = ascii(data, p, p + 4)
            val ln = u32(data, p + 4)
            require(p + 8 + ln <= used) { "truncated PTCF chunk" }
            val body = data.copyOfRange(p + 8, p + 8 + ln.toInt())
            p += 8 + ln.toInt()
            chunks.add(tag to body)
            if (tag == "EDTB") {
                for (k in 0 until body.size / ENTRY) {
                    val le = body.copyOfRange(k * ENTRY, (k + 1) * ENTRY).reversedArray()
                    effects.add(effectFromRaw(k, BigInteger(1, le)))
                }
            }
        }
        return Patch(name, effects, data.copyOf(), ids, version, data.copyOfRange(0x10, 0x1A),
            data.copyOfRange(0x1A, 0x24), chunks, n.toInt())
    }

    private fun entryBytes(raw: BigInteger): ByteArray {
        val be = raw.toByteArray() // big endian, may carry a leading sign byte
        val out = ByteArray(ENTRY)
        for (i in 0 until ENTRY) {
            val j = be.size - 1 - i
            if (j >= 0) out[i] = be[j]
        }
        return out
    }

    /** Rebuild the used bytes of a patch from the model fields. */
    fun encode(p: Patch): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        out.write("PTCF".toByteArray(Charsets.US_ASCII))
        putU32(out, 0)
        putU32(out, p.version.toLong())
        putU32(out, p.slots.toLong())
        out.write(p.headerUnknown)
        out.write(p.nameRaw)
        for (id in p.effectIds) putU32(out, id.toLong() and 0xFFFFFFFFL)
        for ((tag, original) in p.chunks) {
            val body = if (tag == "EDTB") {
                java.io.ByteArrayOutputStream().also { b -> p.effects.forEach { b.write(entryBytes(it.raw)) } }.toByteArray()
            } else original
            out.write(tag.toByteArray(Charsets.US_ASCII))
            putU32(out, body.size.toLong())
            out.write(body)
        }
        val bytes = out.toByteArray()
        val len = bytes.size.toLong()
        for (i in 0 until 4) bytes[4 + i] = ((len ushr (8 * i)) and 0xFF).toByte()
        return bytes
    }

    fun setParam(p: Patch, slot: Int, index: Int, value: Int): Patch {
        val e = p.effects[slot]
        if (!e.editable(index)) throw IllegalArgumentException("param $index of slot $slot is not editable")
        val w = PARAM_WIDTHS[index]
        val v = value.coerceIn(0, (1 shl w) - 1)
        val pos = PARAM_START + PARAM_WIDTHS.take(index).sum()
        val mask = BigInteger.ONE.shiftLeft(w).subtract(BigInteger.ONE).shiftLeft(pos)
        val raw = e.raw.andNot(mask).or(BigInteger.valueOf(v.toLong()).shiftLeft(pos))
        return p.copy(effects = p.effects.replaceAt(slot, e.withRaw(raw)))
    }

    fun setOn(p: Patch, slot: Int, on: Boolean): Patch {
        val e = p.effects[slot]
        val raw = if (on) e.raw.setBit(0) else e.raw.clearBit(0)
        return p.copy(effects = p.effects.replaceAt(slot, e.withRaw(raw)))
    }

    /** Make entry `slot` the effect `fxId` (EDTB bits 1-29 and the header ID list); knob values are kept. */
    fun setType(p: Patch, slot: Int, fxId: Int): Patch {
        val e = p.effects[slot]
        require(!e.isTail) { "entry $slot is the second half of a double-width effect" }
        val raw = e.raw.andNot(ID_MASK.shiftLeft(1))
            .or(BigInteger.valueOf(fxId.toLong() and 0x1FFFFFFFL).shiftLeft(1))
        val ids = if (slot < p.effectIds.size) p.effectIds.replaceAt(slot, fxId) else p.effectIds
        return p.copy(effects = p.effects.replaceAt(slot, e.withRaw(raw)), effectIds = ids)
    }

    private fun renumber(effects: List<Effect>): List<Effect> =
        effects.mapIndexed { i, e -> if (e.slot == i) e else e.withRaw(e.raw, i) }

    /** An empty entry (on, effect 0) at `pos`; null when the patch is full or `pos` is inside a double-width effect. */
    fun insertEntry(p: Patch, pos: Int): Patch? {
        if (p.effects.size >= MAX_ENTRIES || pos !in 0..p.effects.size) return null
        if (pos < p.effects.size && p.effects[pos].isTail) return null
        val fresh = effectFromRaw(pos, BigInteger.ONE)
        val effects = p.effects.toMutableList().also { it.add(pos, fresh) }
        val ids = p.effectIds.toMutableList().also { it.add(minOf(pos, it.size), 0) }
        return p.copy(effects = renumber(effects), effectIds = ids, slots = effects.size)
    }

    private fun blockLen(p: Patch, pos: Int) = if (pos + 1 < p.effects.size && p.effects[pos + 1].isTail) 2 else 1

    /** Removes the entry (and the second half of a double-width effect); null for a bad position or a tail. */
    fun deleteEntry(p: Patch, pos: Int): Patch? {
        if (pos !in p.effects.indices || p.effects[pos].isTail) return null
        val n = blockLen(p, pos)
        val effects = p.effects.toMutableList().also { for (i in 0 until n) it.removeAt(pos) }
        val ids = p.effectIds.toMutableList().also { for (i in 0 until n) if (pos < it.size) it.removeAt(pos) }
        return p.copy(effects = renumber(effects), effectIds = ids, slots = effects.size)
    }

    /** Takes the effect at `src` (with its second half) out and puts it back at `dst`; null for a bad `src` or a tail. */
    fun moveEntry(p: Patch, src: Int, dst: Int): Patch? {
        if (src !in p.effects.indices || p.effects[src].isTail) return null
        val n = blockLen(p, src)
        val block = p.effects.subList(src, src + n).toList()
        val ids = p.effectIds.subList(minOf(src, p.effectIds.size), minOf(src + n, p.effectIds.size)).toList()
        val effects = p.effects.toMutableList().also { for (i in 0 until n) it.removeAt(src) }
        val newIds = p.effectIds.toMutableList().also { for (i in 0 until n) if (src < it.size) it.removeAt(src) }
        val d = dst.coerceIn(0, effects.size)
        effects.addAll(d, block)
        newIds.addAll(minOf(d, newIds.size), ids)
        return p.copy(effects = renumber(effects), effectIds = newIds, slots = effects.size)
    }

    /** Position (and module number) of the effect at entry `slot`: the entry index; throws for a tail. */
    fun position(p: Patch, slot: Int): Int {
        require(!p.effects[slot].isTail) { "entry $slot is the second half of a double-width effect" }
        return slot
    }

    /** Same name and same entries (device._same_patch); false when either does not parse. */
    fun samePatch(a: ByteArray, b: ByteArray): Boolean = try {
        val pa = parse(a)
        val pb = parse(b)
        pa.name == pb.name && pa.effects.map { it.raw } == pb.effects.map { it.raw }
    } catch (e: Exception) {
        false
    }

    private fun <T> List<T>.replaceAt(i: Int, v: T): List<T> = toMutableList().also { it[i] = v }
}
