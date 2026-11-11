package nl.b6lab.remote.core

/** Bank letters of a slot as the B6 shows them: A..Z, then AA..AZ, then BA..BH (4 patches per bank). */
fun bankLetters(slot: Int): String {
    val bank = slot / 4
    if (bank < 26) return ('A' + bank).toString()
    val i = bank - 26
    return "" + ('A' + i / 26) + ('A' + i % 26)
}

/** The 1-based patch number of a slot, 3 digits. */
fun patchNumber(slot: Int): String = (slot + 1).toString().padStart(3, '0')

/** "Z-104": bank letters, a hyphen, then the patch number. */
fun patchLabel(slot: Int): String = bankLetters(slot) + "-" + patchNumber(slot)
