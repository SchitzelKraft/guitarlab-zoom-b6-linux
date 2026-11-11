package nl.b6lab.remote.core

import java.math.BigDecimal
import java.math.RoundingMode
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** One knob of an effect. Port of `b6lab.effects.ParamInfo`. */
data class ParamInfo(
    val name: String,
    val rawMax: Int?,
    val displayMin: String?,
    val displayStep: String?,
    val precision: Int,
    val labels: List<String>?,
) {
    /** The value as Guitar Lab shows it: a label, `min + step * value` with `precision` decimals, or `raw n`. */
    fun format(value: Int): String {
        labels?.let { if (value in it.indices) return it[value] }
        val min = displayMin
        val step = displayStep
        if (min == null || step == null) return "raw $value"
        val result = BigDecimal(min).add(BigDecimal(step).multiply(BigDecimal(value)))
        return result.setScale(precision, RoundingMode.HALF_EVEN).toPlainString()
    }

    /** What the app shows: like [format], but the plain number when the parameter has no display info. */
    fun display(value: Int): String {
        labels?.let { if (value in it.indices) return it[value] }
        return if (displayMin == null || displayStep == null) value.toString() else format(value)
    }
}

data class EffectInfo(
    val fxId: Int,
    val name: String,
    val group: String,
    val params: List<ParamInfo>,
    /** Asset path relative to the assets root (e.g. `generated/svg/SVT_88.svg`), or null. */
    val svg: String?,
    val dspLoad: Double,
)

class Catalog(val effects: Map<Int, EffectInfo>) {
    /** Groups in Guitar Lab order (`ptcf.CATEGORIES` by category byte); effects by id inside a group. */
    fun byGroup(): List<Pair<String, List<EffectInfo>>> {
        val byName = effects.values.groupBy { it.group }
        return GROUP_ORDER.filter { it in byName }.map { g -> g to byName.getValue(g).sortedBy { it.fxId } } +
            byName.filterKeys { it !in GROUP_ORDER }.map { (g, l) -> g to l.sortedBy { it.fxId } }
    }

    /** Index in [byGroup] of the group holding [fxId]; 0 when it is null or unknown. */
    fun groupIndexOf(fxId: Int?): Int =
        if (fxId == null) 0 else byGroup().indexOfFirst { (_, l) -> l.any { it.fxId == fxId } }.coerceAtLeast(0)

    private fun load(fxId: Int) = effects[fxId]?.dspLoad ?: 0.0

    /**
     * Whether `fxId` can be added (or, with `replaceSlot`, can replace that entry) within 6 entries and a DSP
     * load of 220. Whether the new effect is double width is not in the catalogue: the pedal decides.
     */
    fun fits(p: Patch, fxId: Int, replaceSlot: Int? = null): Boolean {
        var count = p.effects.size
        var total = p.effects.filter { !it.isTail }.sumOf { load(it.fxId) }
        if (replaceSlot != null) {
            p.effects.firstOrNull { it.slot == replaceSlot }?.let {
                count -= 1
                if (!it.isTail) total -= load(it.fxId)
            }
        }
        return count + 1 <= Ptcf.MAX_ENTRIES && total + load(fxId) <= MAX_LOAD + 1e-9
    }

    companion object {
        const val MAX_LOAD = 220.0

        private val GROUP_ORDER = listOf(
            "DYNAMICS", "FILTER", "DRIVE", "PREAMP", "BASS AMP", "CABINET", "MODULATION",
            "SFX", "DELAY", "REVERB", "PEDAL", "SND-RTN", "IR",
        )

        private fun str(o: JsonObject, k: String) = o[k]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content

        fun load(json: String): Catalog {
            val root = Json.parseToJsonElement(json).jsonObject
            val map = LinkedHashMap<Int, EffectInfo>()
            for ((key, v) in root) {
                val o = v.jsonObject
                val id = key.toLong(16).toInt()
                val params = o["params"]!!.jsonArray.map { pv ->
                    val q = pv.jsonObject
                    ParamInfo(
                        name = q["name"]!!.jsonPrimitive.content,
                        rawMax = q["raw_max"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.int,
                        displayMin = str(q, "display_min"),
                        displayStep = str(q, "display_step"),
                        precision = q["precision"]!!.jsonPrimitive.int,
                        labels = q["labels"]?.takeIf { it !is JsonNull }?.jsonArray?.map { it.jsonPrimitive.content },
                    )
                }
                map[id] = EffectInfo(
                    id, o["name"]!!.jsonPrimitive.content, o["group"]!!.jsonPrimitive.content, params,
                    str(o, "svg"), o["dsp_load"]!!.jsonPrimitive.double,
                )
            }
            return Catalog(map)
        }
    }
}
