package org.dxboard.app

// Pure Kotlin spot logic (no Android imports, so it can be unit tested on the JVM).

data class Band(val name: String, val lowKhz: Double, val highKhz: Double, val color: Long)

val BANDS = listOf(
    Band("160m", 1800.0, 2000.0, 0xFFFF3B3B),
    Band("80m", 3500.0, 4000.0, 0xFFFF8C00),
    Band("60m", 5060.0, 5450.0, 0xFFFFC800),
    Band("40m", 7000.0, 7300.0, 0xFFFFF200),
    Band("30m", 10100.0, 10150.0, 0xFFA8FF00),
    Band("20m", 14000.0, 14350.0, 0xFF00FF6A),
    Band("17m", 18068.0, 18168.0, 0xFF00FFD0),
    Band("15m", 21000.0, 21450.0, 0xFF00B4FF),
    Band("12m", 24890.0, 24990.0, 0xFF5C7CFF),
    Band("10m", 28000.0, 29700.0, 0xFFB45CFF),
    Band("6m", 50000.0, 54000.0, 0xFFFF4DE6),
    Band("4m", 70000.0, 71000.0, 0xFFFF85A8),
    Band("2m", 144000.0, 148000.0, 0xFFE8E8E8),
)
val BAND_NAMES = BANDS.map { it.name }

val MODES = listOf("CW", "SSB", "FT8", "FT4", "RTTY", "DIGI")
val MODE_COLOR = mapOf(
    "CW" to 0xFFFFE600,
    "SSB" to 0xFFFF4D4D,
    "FT8" to 0xFF00E5FF,
    "FT4" to 0xFF4DFF88,
    "RTTY" to 0xFFFF9A1F,
    "DIGI" to 0xFFD27DFF,
)

data class ClusterDef(val name: String, val host: String, val port: Int, val enabled: Boolean)

/** Well known public DX clusters. The list can be changed in the app. */
val DEFAULT_CLUSTERS = listOf(
    ClusterDef("VE7CC", "dxc.ve7cc.net", 23, true),
    ClusterDef("W3LPL", "w3lpl.net", 7373, false),
    ClusterDef("NC7J", "dxc.nc7j.com", 7373, false),
    ClusterDef("GB7DJK", "gb7djk.dxcluster.net", 7300, true),
    ClusterDef("DL9GTB", "cluster.dl9gtb.de", 8000, true),
    ClusterDef("ON0DXK", "on0dxk.dyndns.org", 8000, false),
    ClusterDef("DXFun", "dxfun.com", 8000, false),
    ClusterDef("HamQTH", "hamqth.com", 7300, false),
    ClusterDef("RBN CW", "telnet.reversebeacon.net", 7000, false),
    ClusterDef("RBN FT8", "telnet.reversebeacon.net", 7001, false),
)

val CLUSTER_PALETTE = listOf(
    0xFFFF5E7E, 0xFFFFB347, 0xFFFFE066, 0xFF7CFF6B, 0xFF3EE0D0,
    0xFF4DA3FF, 0xFFA77BFF, 0xFFFF7AE0, 0xFFC0C0C0, 0xFFFF9E5E,
)

fun clusterColor(index: Int): Long = CLUSTER_PALETTE[Math.floorMod(index, CLUSTER_PALETTE.size)]

/** One raw "DX de" line from a cluster. */
data class RawSpot(
    val spotter: String,
    val freq: Double,
    val call: String,
    val band: String?,
    val mode: String,
    val comment: String,
    val time: String,
)

private val CW_TOP = mapOf(
    "160m" to 1838.0, "80m" to 3570.0, "60m" to 5354.0, "40m" to 7040.0, "30m" to 10130.0,
    "20m" to 14070.0, "17m" to 18095.0, "15m" to 21070.0, "12m" to 24915.0,
    "10m" to 28070.0, "6m" to 50100.0, "4m" to 70100.0, "2m" to 144150.0,
)
private val SSB_BOTTOM = mapOf(
    "160m" to 1843.0, "80m" to 3600.0, "60m" to 5354.0, "40m" to 7060.0, "30m" to 99999.0,
    "20m" to 14100.0, "17m" to 18110.0, "15m" to 21150.0, "12m" to 24930.0,
    "10m" to 28300.0, "6m" to 50100.0, "4m" to 70100.0, "2m" to 144150.0,
)
private val FT8_DIALS = listOf(1840.0, 3573.0, 5357.0, 7074.0, 10136.0, 14074.0, 18100.0,
    21074.0, 24915.0, 28074.0, 50313.0, 70154.0, 144174.0)
private val FT4_DIALS = listOf(3575.5, 7047.5, 10140.0, 14080.0, 18104.0, 21140.0, 24919.0,
    28180.0, 50318.0, 144170.0)
private val MODE_WORDS = listOf(
    Regex("\\bFT8\\b") to "FT8",
    Regex("\\bFT4\\b") to "FT4",
    Regex("\\bRTTY\\b") to "RTTY",
    Regex("\\bCW\\b") to "CW",
    Regex("\\b(SSB|USB|LSB|PHONE)\\b") to "SSB",
    Regex("\\b(B?PSK\\d*|JT65|JT9|JS8|MSK144|Q65|OLIVIA|SSTV|MFSK\\d*|DIGI|VARAC|FST4)\\b") to "DIGI",
)
private val CALL_SUFFIXES = setOf("P", "M", "MM", "AM", "QRP", "QRPP", "A", "B", "R", "LH",
    "J", "E", "PM", "LGT", "BCN", "N", "T", "X")
private val CALL_RE = Regex("^(?=.*\\d)(?=.*[A-Z])[A-Z0-9/]{3,15}$")
private val SPOT_RE = Regex(
    "^DX de\\s+([^\\s:]+):?\\s+(\\d+(?:\\.\\d+)?)\\s+([A-Za-z0-9/]+)\\s+(.*)\\s(\\d{4})Z")

fun bandOf(khz: Double): String? = BANDS.firstOrNull { khz >= it.lowKhz && khz <= it.highKhz }?.name

fun bandColor(band: String?): Long = BANDS.firstOrNull { it.name == band }?.color ?: 0xFF888888

/** Mode from the spot comment, else from the frequency (band plan). */
fun inferMode(khz: Double, band: String?, comment: String): String {
    val text = comment.uppercase()
    for ((rx, mode) in MODE_WORDS) if (rx.containsMatchIn(text)) return mode
    if (FT8_DIALS.any { khz >= it - 0.5 && khz <= it + 3.5 }) return "FT8"
    if (FT4_DIALS.any { khz >= it - 0.5 && khz <= it + 3.5 }) return "FT4"
    if (band == null) return "DIGI"
    if (khz < (CW_TOP[band] ?: 0.0)) return "CW"
    if (khz >= (SSB_BOTTOM[band] ?: 1e9)) return "SSB"
    return "DIGI"
}

/** 'KM3T-2-#' -> 'KM3T', 'DL1ABC-7' -> 'DL1ABC'. */
fun cleanSpotter(raw: String): String =
    raw.uppercase().trimEnd(':').replace("-#", "").replace(Regex("-\\d+$"), "")

private fun looksLikeCall(p: String) = Regex("^[A-Z0-9]{1,3}\\d[A-Z]{1,5}$").matches(p)

/** The station's own call: 'EA8/ON4XX/P' -> 'ON4XX'. */
fun homeCall(call: String): String {
    val parts = call.uppercase().split("/").filter { it.isNotEmpty() }
    if (parts.size <= 1) return parts.firstOrNull() ?: call.uppercase()
    val cands = parts.filter { it !in CALL_SUFFIXES && !(it.length == 1 && it[0].isDigit()) }
    if (cands.isEmpty()) return parts[0]
    return cands.maxWith(compareBy<String>({ looksLikeCall(it) }, { it.length }))
}

/** The part that tells where the station is: 'EA8/ON4XX' -> 'EA8'. Null for /MM and /AM. */
fun locationPrefix(call: String): String? {
    val parts = call.uppercase().split("/").filter { it.isNotEmpty() }
    if ("MM" in parts || "AM" in parts) return null
    val hc = homeCall(call)
    val others = parts.filter { it != hc && it !in CALL_SUFFIXES }
    if (others.isEmpty() || (others[0].length == 1 && others[0][0].isDigit())) return hc
    return others[0]
}

fun parseSpotLine(line: String, rbn: Boolean = false): RawSpot? {
    val m = SPOT_RE.find(line) ?: return null
    val (spotter, freq, rawCall, rawComment, hhmm) = m.destructured
    val call = rawCall.uppercase()
    if (!CALL_RE.matches(call)) return null
    val khz = freq.toDoubleOrNull() ?: return null
    val band = bandOf(khz)
    val comment = rawComment.trim().replace(Regex("\\s+"), " ")
    val mode = if (rbn) {
        val word = comment.split(" ").firstOrNull()?.uppercase() ?: ""
        if (word in setOf("CW", "RTTY", "FT8", "FT4")) word else "DIGI"
    } else {
        inferMode(khz, band, comment)
    }
    return RawSpot(cleanSpotter(spotter), khz, call, band, mode, comment, hhmm)
}

/** cty.dat (country-files.com): prefix -> country name. */
class CtyDatabase {
    private val prefixes = HashMap<String, String>()
    private val exact = HashMap<String, String>()
    val size get() = prefixes.size

    fun load(text: String): Int {
        val overrides = Regex("\\(.*?\\)|\\[.*?\\]|<.*?>|\\{.*?\\}|~.*?~")  // ] and } escaped: Android's ICU regex needs it
        for (record in text.split(";")) {
            val fields = record.split(":")
            if (fields.size < 9) continue
            val name = fields[0].trim()
            for (item in fields.drop(8).joinToString(":").split(",")) {
                val p = overrides.replace(item, "").trim()
                if (p.startsWith("=")) exact[p.substring(1)] = name
                else if (p.isNotEmpty()) prefixes[p] = name
            }
        }
        return prefixes.size
    }

    fun find(call: String): String? {
        val c = call.uppercase()
        exact[c]?.let { return it }
        val loc = locationPrefix(c) ?: return "Maritime / air mobile"
        exact[loc]?.let { return it }
        for (i in loc.length downTo 1) prefixes[loc.substring(0, i)]?.let { return it }
        return null
    }
}
