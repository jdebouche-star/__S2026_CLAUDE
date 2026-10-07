package org.dxboard.app

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import kotlin.random.Random

/** A DX station on a frequency, merged from every cluster that reported it. */
data class Spot(
    val id: Long,
    val call: String,
    val freq: Double,
    val band: String?,
    val mode: String,
    val comment: String,
    val time: String,
    val spotters: List<String>,
    val clusters: Set<Int>,
    val first: Long,
    val last: Long,
    val country: String,
)

data class LinkStatus(val state: LinkState, val text: String)

private const val DEDUP_MS = 10 * 60 * 1000L     // same call within 1 kHz in 10 min = same spot
private const val MAX_SPOTS = 1500
private val CTY_URLS = listOf(
    "https://www.country-files.com/cty/cty.dat",
    "https://www.country-files.com/bigcty/cty.dat",
)

class BoardViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = app.getSharedPreferences("dxboard", Context.MODE_PRIVATE)

    // ---- settings (saved) ----
    var callsign by mutableStateOf(prefs.getString("callsign", "") ?: "")
        private set
    var keepMinutes by mutableIntStateOf(prefs.getInt("keep", 30))
        private set
    var clusters by mutableStateOf(loadClusters())
        private set
    var bandsOn by mutableStateOf(loadSet("bands", BAND_NAMES))
        private set
    var modesOn by mutableStateOf(loadSet("modes", MODES))
        private set
    var demo by mutableStateOf(prefs.getBoolean("demo", false))
        private set
    var keepScreenOn by mutableStateOf(prefs.getBoolean("screenOn", true))
        private set

    // ---- live state ----
    var search by mutableStateOf("")
    var spots by mutableStateOf<List<Spot>>(emptyList())
        private set
    var status by mutableStateOf<Map<Int, LinkStatus>>(emptyMap())
        private set
    var counts by mutableStateOf<Map<Int, Int>>(emptyMap())
        private set
    var received by mutableIntStateOf(0)
        private set
    var connected by mutableStateOf(false)
        private set
    var logs by mutableStateOf<List<String>>(emptyList())
        private set

    private var cty = CtyDatabase()
    private var nextId = 1L
    private val jobs = mutableListOf<Job>()
    private val events = Channel<Any>(Channel.UNLIMITED)
    private val logTime = SimpleDateFormat("HH:mm:ss", Locale.US)
    private val utcTime = SimpleDateFormat("HHmm", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }

    private data class SpotEvent(val index: Int, val spot: RawSpot)
    private data class StateEvent(val index: Int, val status: LinkStatus)
    private data class LogEvent(val text: String, val error: Boolean)

    private val listener = object : ClusterListener {
        override fun onState(index: Int, state: LinkState, text: String) {
            events.trySend(StateEvent(index, LinkStatus(state, text)))
        }
        override fun onSpot(index: Int, spot: RawSpot) { events.trySend(SpotEvent(index, spot)) }
        override fun onLog(text: String, error: Boolean) { events.trySend(LogEvent(text, error)) }
    }

    init {
        Diagnostics.breadcrumb(app, "BoardViewModel created")
        log("DX Cluster Board ${BuildConfig.VERSION_NAME}")
        log("Welcome! Enter your call on the Clusters page and press Connect.")
        viewModelScope.launch { pumpEvents() }
        viewModelScope.launch { purgeLoop() }
        if (prefs.getBoolean("safeMode", false)) {
            log("Safe start: the country list is not loaded.")
            Diagnostics.breadcrumb(app, "Safe start (no country list)")
        } else {
            viewModelScope.launch { loadCty() }
        }
    }

    // ---------------------------------------------------------------- events

    /** Apply queued events on the main thread in small batches (smooth UI). */
    private suspend fun pumpEvents() {
        while (true) {
            val first = events.receive()
            var list = spots
            var changed = false
            var ev: Any? = first
            var n = 0
            while (ev != null && n++ < 200) {   // keep the UI thread free
                when (ev) {
                    is SpotEvent -> { list = merge(list, ev.index, ev.spot); changed = true }
                    is StateEvent -> status = status + (ev.index to ev.status)
                    is LogEvent -> log(ev.text, ev.error)
                }
                if (n < 200) ev = events.tryReceive().getOrNull()
            }
            if (changed) spots = list
            delay(300)
        }
    }

    private fun merge(list: List<Spot>, index: Int, raw: RawSpot): List<Spot> {
        val now = System.currentTimeMillis()
        counts = counts + (index to (counts[index] ?: 0) + 1)
        received++
        val pos = list.indexOfFirst {
            now - it.last <= DEDUP_MS && it.call == raw.call && kotlin.math.abs(it.freq - raw.freq) <= 1.0
        }
        if (pos >= 0) {
            val old = list[pos]
            val updated = old.copy(
                freq = raw.freq, time = raw.time, last = now,
                spotters = if (raw.spotter in old.spotters) old.spotters else old.spotters + raw.spotter,
                clusters = old.clusters + index,
                comment = if (raw.comment.length > 2) raw.comment else old.comment,
            )
            return listOf(updated) + list.filterIndexed { i, _ -> i != pos }
        }
        val spot = Spot(
            id = nextId++, call = raw.call, freq = raw.freq, band = raw.band, mode = raw.mode,
            comment = raw.comment, time = raw.time, spotters = listOf(raw.spotter),
            clusters = setOf(index), first = now, last = now, country = country(raw.call),
        )
        return (listOf(spot) + list).take(MAX_SPOTS)
    }

    private suspend fun purgeLoop() {
        while (true) {
            delay(5_000)
            val limit = System.currentTimeMillis() - keepMinutes * 60_000L
            if (spots.any { it.last < limit }) spots = spots.filter { it.last >= limit }
        }
    }

    private fun country(call: String) = if (cty.size > 0) cty.find(call) ?: "" else ""

    fun log(text: String, error: Boolean = false) {
        val line = (if (error) "⚠ " else "") + logTime.format(Date()) + "  " + text
        logs = (logs + line).takeLast(300)
        android.util.Log.i("DxBoard", line)
    }

    // --------------------------------------------------------------- filters

    fun visibleSpots(): List<Spot> {
        val q = search.trim().uppercase()
        return spots.filter { s ->
            (s.band == null || s.band in bandsOn) && s.mode in modesOn &&
                (q.isEmpty() || q in s.call || q in s.country.uppercase())
        }
    }

    fun toggleBand(band: String, solo: Boolean) {
        bandsOn = toggled(bandsOn, band, BAND_NAMES, solo)
        saveSet("bands", bandsOn)
    }

    fun toggleMode(mode: String, solo: Boolean) {
        modesOn = toggled(modesOn, mode, MODES, solo)
        saveSet("modes", modesOn)
    }

    private fun toggled(on: Set<String>, item: String, all: List<String>, solo: Boolean): Set<String> =
        when {
            solo && on == setOf(item) -> all.toSet()
            solo -> setOf(item)
            item in on -> on - item
            else -> on + item
        }

    // ------------------------------------------------------------- settings

    fun updateCallsign(v: String) {
        callsign = v.uppercase().filter { it.isLetterOrDigit() || it == '/' }.take(12)
        prefs.edit().putString("callsign", callsign).apply()
    }

    fun updateKeep(v: Int) {
        keepMinutes = v.coerceIn(1, 720)
        prefs.edit().putInt("keep", keepMinutes).apply()
    }

    fun updateDemo(v: Boolean) {
        demo = v
        prefs.edit().putBoolean("demo", v).apply()
    }

    fun updateKeepScreenOn(v: Boolean) {
        keepScreenOn = v
        prefs.edit().putBoolean("screenOn", v).apply()
    }

    fun setClusterEnabled(i: Int, on: Boolean) {
        clusters = clusters.mapIndexed { k, c -> if (k == i) c.copy(enabled = on) else c }
        saveClusters()
    }

    /** Returns an error message, or null when the cluster was added. */
    fun addCluster(name: String, address: String): String? {
        val m = Regex("^(?:telnet://)?([A-Za-z0-9.\\-]+)[: ]+(\\d{1,5})$").find(address.trim())
            ?: return "Type the address as host:port, e.g. dxc.ve7cc.net:23"
        val host = m.groupValues[1]
        val port = m.groupValues[2].toInt()
        if (port !in 1..65535) return "Port must be 1 - 65535"
        val label = name.trim().ifEmpty { host.substringBefore('.').uppercase() }.take(10)
        clusters = clusters + ClusterDef(label, host, port, true)
        saveClusters()
        log("Added $label ($host:$port)")
        return null
    }

    fun removeCluster(i: Int) {
        if (connected) return
        clusters = clusters.filterIndexed { k, _ -> k != i }
        status = emptyMap()
        counts = emptyMap()
        saveClusters()
    }

    fun resetClusters() {
        if (connected) return
        clusters = DEFAULT_CLUSTERS
        saveClusters()
    }

    private fun loadClusters(): List<ClusterDef> {
        val json = prefs.getString("clusters", null) ?: return DEFAULT_CLUSTERS
        return try {
            val arr = JSONArray(json)
            (0 until arr.length()).map {
                val o = arr.getJSONObject(it)
                ClusterDef(o.getString("name"), o.getString("host"), o.getInt("port"), o.getBoolean("on"))
            }.ifEmpty { DEFAULT_CLUSTERS }
        } catch (e: Exception) {
            DEFAULT_CLUSTERS
        }
    }

    private fun saveClusters() {
        val arr = JSONArray()
        clusters.forEach {
            arr.put(JSONObject().put("name", it.name).put("host", it.host).put("port", it.port).put("on", it.enabled))
        }
        prefs.edit().putString("clusters", arr.toString()).apply()
    }

    private fun loadSet(key: String, all: List<String>): Set<String> =
        prefs.getString(key, null)?.split(",")?.filter { it in all }?.toSet()?.ifEmpty { null } ?: all.toSet()

    private fun saveSet(key: String, set: Set<String>) {
        prefs.edit().putString(key, set.joinToString(",")).apply()
    }

    // ------------------------------------------------------------- connect

    /** Returns an error message, or null. */
    fun toggleConnect(): String? {
        if (connected) {
            jobs.forEach { it.cancel() }
            jobs.clear()
            connected = false
            log("Disconnected.")
            Diagnostics.breadcrumb(getApplication(), "Disconnect")
            return null
        }
        if (demo) {
            jobs += viewModelScope.launch { demoLoop() }
        } else {
            val call = callsign
            if (!Regex("^[A-Z0-9/]{3,12}$").matches(call) || call.none { it.isDigit() }) {
                return "Please enter your callsign first (Clusters page). The clusters need it to log you in."
            }
            val chosen = clusters.withIndex().filter { it.value.enabled }
            if (chosen.isEmpty()) return "Switch on at least one cluster (Clusters page)."
            for ((i, def) in chosen) {
                jobs += viewModelScope.launch(Dispatchers.IO) { ClusterClient(i, def, call, listener).run() }
            }
        }
        connected = true
        Diagnostics.breadcrumb(getApplication(), "Connect (demo=$demo)")
        return null
    }

    fun clearSpots() {
        spots = emptyList()
        counts = emptyMap()
        received = 0
    }

    private suspend fun demoLoop() {
        val calls = listOf("VP8LP", "3Y0K", "ZL7X", "JA1XYZ", "VK9DX", "A71AN", "PY2XB", "EA8/ON4XX",
            "TF3ML", "KH6LC", "ZS6BK", "9M2TO", "UA0SDX", "W1AW", "OX3LX", "FY5KE", "5B4AHJ", "T88WA")
        val spotters = listOf("DL1ABC", "ON4UN", "G3XYZ", "K3LR", "JA7ABC", "VE3AB", "F5NBX", "OH2BH")
        val comments = listOf("", "CW", "FT8 -12dB", "SSB 59", "up 2", "TNX QSO", "RTTY", "loud!")
        try {
            clusters.indices.forEach { listener.onState(it, LinkState.RECEIVING, "demo") }
            while (true) {
                delay(Random.nextLong(300, 1500))
                val b = BANDS[Random.nextInt(11)]
                val khz = Math.round((b.lowKhz + Random.nextDouble() * minOf(300.0, b.highKhz - b.lowKhz)) * 10) / 10.0
                val line = String.format(Locale.US, "DX de %s: %9.1f  %-12s %-30s %sZ",
                    spotters.random(), khz, calls.random(), comments.random(), utcTime.format(Date()))
                parseSpotLine(line)?.let { listener.onSpot(Random.nextInt(maxOf(1, clusters.size)), it) }
            }
        } finally {
            clusters.indices.forEach { listener.onState(it, LinkState.OFF, "off") }
        }
    }

    // ----------------------------------------------------------------- cty

    private suspend fun loadCty() {
        val file = File(getApplication<Application>().filesDir, "cty.dat")
        val db = withContext(Dispatchers.IO) {
            val old = !file.exists() || System.currentTimeMillis() - file.lastModified() > 30L * 86_400_000
            if (old) {
                listener.onLog("Downloading country list (cty.dat) ...")
                for (u in CTY_URLS) {
                    try {
                        val c = URL(u).openConnection() as HttpURLConnection
                        c.connectTimeout = 20_000
                        c.readTimeout = 30_000
                        val bytes = c.inputStream.use { it.readBytes() }
                        if (bytes.size > 1000) {
                            file.writeBytes(bytes)
                            break
                        }
                    } catch (e: Exception) {
                        listener.onLog("cty.dat download failed: ${e.message}", true)
                    }
                }
            }
            try {
                if (file.exists()) CtyDatabase().also { it.load(file.readText(Charsets.ISO_8859_1)) } else null
            } catch (e: Exception) {
                listener.onLog("cty.dat could not be read: ${e.message}", true)
                null
            }
        }
        if (db != null && db.size > 0) {
            cty = db
            spots = spots.map { it.copy(country = country(it.call)) }
            log("Country list loaded (${db.size} prefixes).")
        } else {
            log("No country list: countries will not be shown.", true)
        }
    }

    fun diagnosticsReport(): String = Diagnostics.report(getApplication(), null, null)

    override fun onCleared() {
        Diagnostics.breadcrumb(getApplication(), "BoardViewModel cleared")
        jobs.forEach { it.cancel() }
        super.onCleared()
    }
}
