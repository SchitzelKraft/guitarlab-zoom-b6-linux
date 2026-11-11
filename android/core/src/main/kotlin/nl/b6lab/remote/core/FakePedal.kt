package nl.b6lab.remote.core

import kotlinx.coroutines.channels.Channel

/**
 * A byte-level fake B6 (firmware 1.00) for tests and demo mode. Reply layouts follow vpedal/pedal.py;
 * edit semantics follow b6lab/fake.py. Deterministic: replies are queued on [incoming] without delay.
 * Every message received goes through [Safety.check], which throws for anything the app must never send.
 * [busy]: PC mode is held by another program, so `50` is answered `00 11` and the pedal stays out of PC mode.
 */
class FakePedal(
    patches: List<ByteArray>,
    private val autoSave: Boolean = false,
    private val busy: Boolean = false,
) : MidiTransport {
    private companion object {
        const val SLOTS = 240
        const val SLOT_SIZE = 808
        const val FOOTSWITCH = 0x5A
        const val GLOBAL = 0x64
        val HDR = byteArrayOf(0x52, 0x00, 0x6E)
        val ACK = HDR + byteArrayOf(0x00, 0x00)
        val BUSY = HDR + byteArrayOf(0x00, 0x11)
        val IDENTITY_REPLY = hex("7e000602526e001a00312e3030")
        val GLOBAL_REPLY = hex(
            "52006e6409340001000500000001320600000000000000010006060000000000000000283232640100020108005001010064000000010101000000",
        )

        fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
        fun bytes(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }
        fun padded(d: ByteArray) = d.copyOf(SLOT_SIZE)

        fun emptyPatch(from: ByteArray): ByteArray {
            var p = Ptcf.parse(from)
            while (p.effects.isNotEmpty()) p = Ptcf.deleteEntry(p, 0) ?: break
            val out = Ptcf.encode(p)
            for (i in 0x1A until 0x24) out[i] = 0
            "Empty".forEachIndexed { i, c -> out[0x1A + i] = c.code.toByte() }
            return padded(out)
        }
    }

    private val slots: Array<ByteArray>
    private var selected = 0
    private var edit: ByteArray
    private var inPcMode = false
    private var position = 0
    private var bank = 0
    private var unplugged = false
    private val typeMemory = HashMap<Int, List<Int>>()
    private val misrouted = HashMap<Int, Int>()
    private val sentLog = ArrayList<ByteArray>()
    private val channel = Channel<MidiMessage>(Channel.UNLIMITED)

    init {
        require(patches.isNotEmpty()) { "FakePedal needs at least one patch" }
        require(patches.size <= SLOTS) { "at most $SLOTS patches" }
        val empty = emptyPatch(patches[0])
        slots = Array(SLOTS) { if (it < patches.size) padded(patches[it]) else empty.copyOf() }
        edit = slots[0].copyOf()
    }

    /** Every message the app sent, as given to [send]. */
    val sent: List<ByteArray> get() = sentLog

    override val incoming: kotlinx.coroutines.channels.ReceiveChannel<MidiMessage> get() = channel

    override fun close() {
        channel.close()
    }

    // ---- test hooks ---------------------------------------------------------------------------

    /** The footswitch selects `slot` on the pedal; in PC mode the pedal announces it. */
    fun footswitchTo(slot: Int) {
        select(slot)
        if (inPcMode) announceSlot(slot)
    }

    /** The knob `index` of the effect at `pos` is turned on the pedal. */
    fun turnKnob(pos: Int, index: Int, value: Int) {
        edit(Ptcf.setParam(patch(), pos, index, value))
        pushPair(pos, index + 2, value)
    }

    /** The effect at `pos` is switched on or off on the pedal. */
    fun toggleOnPedal(pos: Int) {
        val p = patch()
        val on = !p.effects[pos].on
        edit(Ptcf.setOn(p, pos, on))
        pushPair(pos, 0, if (on) 1 else 0)
    }

    /**
     * From now on a press at position [pos] toggles entry [to] instead (a misbehaving pedal). It stays that way,
     * so a second press at [pos] toggles [to] back, which is what B6 Lab's undo relies on.
     */
    fun misroutePresses(pos: Int, to: Int) {
        misrouted[pos] = to
    }

    /** The USB cable is pulled: no more messages, sending fails. */
    fun unplug() {
        unplugged = true
        channel.close()
    }

    /** The slot image as stored on the pedal (808 bytes). */
    fun storedSlot(slot: Int): ByteArray = slots[slot].copyOf()

    /** The edit buffer (808 bytes). */
    fun editBuffer(): ByteArray = edit.copyOf()

    val selectedSlot: Int get() = selected
    val pcMode: Boolean get() = inPcMode

    // ---- wire ---------------------------------------------------------------------------------

    override fun send(bytes: ByteArray) {
        if (unplugged) throw java.io.IOException("pedal unplugged")
        sentLog.add(bytes.copyOf())
        val first = bytes.firstOrNull()?.toInt()?.and(0xFF)
        if (first == 0xF0) {
            check(bytes.size >= 2 && (bytes.last().toInt() and 0xFF) == 0xF7) { "SysEx without F7" }
            val body = bytes.copyOfRange(1, bytes.size - 1)
            Safety.check(body)
            handleSysex(body)
        } else {
            Safety.check(bytes)
            handleChannel(bytes)
        }
    }

    private fun reply(body: ByteArray) {
        channel.trySend(MidiMessage.Sysex(body))
    }

    private fun replyChannel(vararg v: Int) {
        channel.trySend(MidiMessage.Channel(bytes(*v)))
    }

    private fun at(m: ByteArray, i: Int) = m[i].toInt() and 0xFF

    private fun patch() = Ptcf.parse(edit)

    private fun edit(p: Patch) {
        edit = padded(Ptcf.encode(p))
        if (autoSave) slots[selected] = edit.copyOf()
    }

    private fun select(slot: Int) {
        selected = slot
        edit = slots[slot].copyOf()
    }

    private fun dump(data: ByteArray) = Codec.to7(data.size.toLong(), 2) + Codec.pack7(data) + Codec.crcTail(data)

    private fun editDump(flag: Int) = HDR + bytes(0x64, 0x12, flag) + dump(edit)

    private fun announceSlot(slot: Int) {
        val b = slot / 4
        val pos = slot % 4
        reply(HDR + bytes(0x64, 0x26, 0, 0, b, 0, pos, 0))
        replyChannel(0xB0, 0x00, 0x00)
        replyChannel(0xB0, 0x20, b)
        replyChannel(0xC0, pos)
    }

    private fun pushPair(pos: Int, param: Int, value: Int) {
        if (!inPcMode) return
        reply(HDR + bytes(0x64, 0x20, 0x00, 0x64, 0x01) + Codec.to7(pos.toLong(), 5))
        reply(HDR + bytes(0x64, 0x20, 0x00, pos, param) + Codec.to7(value.toLong(), 5))
    }

    private fun handleChannel(m: ByteArray) {
        when (at(m, 0) and 0xF0) {
            0xB0 -> if (m.size >= 3 && at(m, 1) == 0x20) bank = at(m, 2)
            0xC0 -> {
                val slot = bank * 4 + at(m, 1)
                if (slot in 0 until SLOTS) {
                    select(slot)
                    if (inPcMode) announceSlot(slot)
                }
            }
        }
    }

    private fun handleSysex(m: ByteArray) {
        if (m.size >= 4 && at(m, 0) == 0x7E && at(m, 2) == 0x06 && at(m, 3) == 0x01) {
            reply(IDENTITY_REPLY)
            return
        }
        if (m.size < 4 || at(m, 0) != 0x52) return
        when (at(m, 3)) {
            0x50 -> if (busy) reply(BUSY) else { inPcMode = true; reply(ACK) }
            0x51 -> { inPcMode = false; reply(ACK) }
            0x00 -> Unit // the app's acknowledgement of a dump
            0x33 -> {
                replyChannel(0xB0, 0x00, 0x00)
                replyChannel(0xB0, 0x20, selected / 4)
                replyChannel(0xC0, selected % 4)
            }
            0x46 -> if (m.size >= 10) {
                val b = at(m, 6)
                val pos = at(m, 8)
                val slot = b * 4 + pos
                if (slot in 0 until SLOTS) reply(HDR + bytes(0x45, 0, 0, b, 0, pos, 0) + dump(slots[slot]))
            }
            0x64 -> if (m.size >= 5) handleFx(m)
        }
    }

    private fun handleFx(m: ByteArray) {
        when (at(m, 4)) {
            0x13 -> reply(editDump(0x01))
            0x0A -> reply(GLOBAL_REPLY.copyOf().also { it[12] = if (autoSave) 1 else 0 })
            0x0D -> if (m.size >= 10) store(at(m, 7) * 4 + at(m, 9))
            0x20 -> if (m.size >= 13 && at(m, 5) == 0x00) live(m)
        }
    }

    /** Patch Save: the edit buffer goes into the slot and the slot is selected; PC mode answers like vpedal. */
    private fun store(slot: Int) {
        if (slot !in 0 until SLOTS) return
        slots[slot] = edit.copyOf()
        selected = slot
        if (!inPcMode) return
        reply(HDR + bytes(0x45, 0, 0, slot / 4, 0, slot % 4, 0) + dump(edit))
        replyChannel(0xB0, 0x00, 0x00)
        replyChannel(0xB0, 0x20, slot / 4)
        replyChannel(0xC0, slot % 4)
    }

    private fun live(m: ByteArray) {
        val module = at(m, 6)
        val param = at(m, 7)
        val value = Codec.from7(m, 8, 5).toInt()
        val echo = HDR + bytes(0x64, 0x20, 0x01) + m.copyOfRange(6, 13)
        val p = patch()
        if (module == GLOBAL) {
            when (param) {
                0x01 -> { position = value; if (inPcMode) reply(echo) }
                0x02 -> if (inPcMode) reply(echo) // tempo: not modelled
                0x07, 0x08 -> {
                    val done = (if (param == 0x07) Ptcf.insertEntry(p, value) else Ptcf.deleteEntry(p, value))
                    if (done != null) {
                        edit(done)
                        if (inPcMode) reply(editDump(0x00))
                    }
                }
                0x09 -> {
                    Ptcf.moveEntry(p, at(m, 8), at(m, 9))?.let { edit(it) }
                    if (inPcMode) reply(editDump(0x00))
                }
            }
            return
        }
        if (module == FOOTSWITCH && param == 0x00) {
            val pos = misrouted[position] ?: position
            if (pos !in p.effects.indices || p.effects[pos].isTail) return
            val now = if (value == 1) !p.effects[pos].on else p.effects[pos].on
            if (value == 1) edit(Ptcf.setOn(p, pos, now))
            if (inPcMode) reply(HDR + bytes(0x64, 0x20, 0x01, pos, 0x00) + Codec.to7(if (now) 1 else 0, 5))
            return
        }
        if (module >= p.effects.size) return
        if (param == 0x01 && !p.effects[module].isTail) {
            // Type change: the effect gets back the knob values it last had (measured on the B6).
            val e = p.effects[module]
            typeMemory[e.fxId] = e.params
            var q = Ptcf.setType(p, module, value)
            typeMemory[value]?.forEachIndexed { i, v -> q = Ptcf.setParam(q, module, i, v) }
            edit(q)
            if (inPcMode) {
                reply(echo)
                reply(editDump(0x00))
            }
        } else if (param >= 2 && p.effects[module].editable(param - 2)) {
            edit(Ptcf.setParam(p, module, param - 2, value))
            if (inPcMode) reply(echo)
        }
    }
}
