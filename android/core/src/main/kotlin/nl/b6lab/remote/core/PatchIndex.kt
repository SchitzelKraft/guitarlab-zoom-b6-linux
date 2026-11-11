package nl.b6lab.remote.core

/** What search knows about one patch: its name and the effect IDs of its entries (tails left out). */
data class IndexEntry(val name: String, val fxIds: List<Int>)

/** How the background read of all slots stands. */
enum class IndexStatus { RUNNING, DONE, STOPPED }

/**
 * One search result. [rank]: 1 number, 2 name, 3 effect (then [reason] is "uses <effect name>", otherwise null).
 */
data class SearchHit(
    val slot: Int,
    val label: String,
    val name: String,
    val fxIds: List<Int>,
    val rank: Int,
    val reason: String?,
)

/**
 * The patches the session has read so far, and the search over them (spec .superpowers/search/spec.md).
 * [entries] holds every slot that was attempted: null marks a slot that could not be read. Immutable.
 */
class PatchIndex(val entries: Map<Int, IndexEntry?> = emptyMap()) {
    companion object {
        const val SLOTS = 240

        fun entryOf(p: Patch) = IndexEntry(p.name, p.effects.filter { !it.isTail }.map { it.fxId })

        private fun norm(s: String) = s.lowercase().filter { it != ' ' && it != '-' }
    }

    /** How many slots are done (read, or given up on). */
    val indexed: Int get() = entries.size

    fun with(slot: Int, entry: IndexEntry?) = PatchIndex(entries + (slot to entry))

    private class Candidate(val hit: SearchHit, val sub: Int)

    /** Number, name and effect matches for [query], best rank first, slot order inside a rank. */
    fun search(query: String, catalog: Catalog): List<SearchHit> {
        val q = norm(query.trim())
        if (q.isEmpty()) return emptyList()
        val digits = q.all { it in '0'..'9' }
        // a digits-only query is a patch number: leading zeros dropped, "0" is no number at all
        val numberText = if (digits) q.trimStart('0') else null
        if (numberText != null && numberText.isEmpty()) return emptyList()
        val number = numberText?.toBigInteger()
        // names and effects are matched with the same text, so "01" gives exactly the hits of "1"
        val text = numberText ?: q
        val out = ArrayList<Candidate>()
        for (slot in 0 until SLOTS) {
            val label = patchLabel(slot)
            val entry = entries[slot]
            val name = entry?.name ?: ""
            val fxIds = entry?.fxIds ?: emptyList()
            fun hit(rank: Int, sub: Int, reason: String? = null) =
                out.add(Candidate(SearchHit(slot, label, name, fxIds, rank, reason), sub))
            when {
                norm(label) == q || (number != null && number == (slot + 1).toBigInteger()) -> hit(1, 0)
                numberText != null && (slot + 1).toString().startsWith(numberText) -> hit(1, 1)
                entry == null || norm(entry.name) == "empty" -> Unit
                norm(entry.name).startsWith(text) -> hit(2, 0)
                norm(entry.name).contains(text) -> hit(2, 1)
                else -> {
                    val fx = fxIds.mapNotNull { catalog.effects[it]?.name }.firstOrNull { norm(it).contains(text) }
                    if (fx != null) hit(3, 0, "uses $fx")
                }
            }
        }
        return out.sortedWith(compareBy({ it.hit.rank }, { it.sub }, { it.hit.slot })).map { it.hit }
    }
}
