package org.dxboard.app

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import androidx.annotation.RequiresApi
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Helps find out why the app closes on a phone we cannot connect to:
 *  - a small "breadcrumb" file of lifecycle events that survives process death
 *  - Android's own record of why the app process ended (Android 11+)
 */
object Diagnostics {
    private val fmt = SimpleDateFormat("MM-dd HH:mm:ss", Locale.US)
    private fun crumbs(ctx: Context) = File(ctx.filesDir, "events.txt")

    @Synchronized
    fun breadcrumb(ctx: Context, text: String) {
        try {
            val f = crumbs(ctx)
            val lines = if (f.exists()) f.readLines().takeLast(150) else emptyList()
            f.writeText((lines + "${fmt.format(Date())}  $text").joinToString("\n") + "\n")
        } catch (_: Exception) {
        }
    }

    fun breadcrumbs(ctx: Context): String = try {
        crumbs(ctx).takeIf { it.exists() }?.readLines()?.takeLast(60)?.joinToString("\n") ?: "(none)"
    } catch (_: Exception) {
        "(unreadable)"
    }

    private fun reasonName(r: Int) = when (r) {
        1 -> "EXIT_SELF"; 2 -> "SIGNALED (killed)"; 3 -> "LOW_MEMORY"; 4 -> "CRASH"
        5 -> "CRASH_NATIVE"; 6 -> "ANR (not responding)"; 7 -> "INITIALIZATION_FAILURE"
        8 -> "PERMISSION_CHANGE"; 9 -> "EXCESSIVE_RESOURCE_USAGE"; 10 -> "USER_REQUESTED"
        11 -> "USER_STOPPED"; 12 -> "DEPENDENCY_DIED"; 13 -> "OTHER"; 14 -> "FREEZER"
        15 -> "PACKAGE_STATE_CHANGE"; 16 -> "PACKAGE_UPDATED"; else -> "UNKNOWN($r)"
    }

    private val ABNORMAL = setOf(2, 3, 4, 5, 6, 7, 9, 12, 13)

    private fun exits(ctx: Context, max: Int): List<ApplicationExitInfo> {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return emptyList()
        return try {
            val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            am.getHistoricalProcessExitReasons(ctx.packageName, 0, max)
        } catch (_: Exception) {
            emptyList()
        }
    }

    @RequiresApi(Build.VERSION_CODES.R)
    private fun describe(e: ApplicationExitInfo, withTrace: Boolean): String {
        val sb = StringBuilder()
        sb.append("${fmt.format(Date(e.timestamp))}  ${reasonName(e.reason)}  status=${e.status}  " +
            "importance=${e.importance}  pss=${e.pss / 1024}MB")
        e.description?.let { sb.append("\n    ").append(it.take(500)) }
        if (withTrace && e.reason == 6) {   // ANR
            try {
                e.traceInputStream?.use { s ->
                    val text = s.readBytes().toString(Charsets.UTF_8)
                    // the main thread is what matters for an ANR
                    val main = text.indexOf("\"main\"")
                    sb.append("\n--- ANR trace (main thread) ---\n")
                    sb.append(if (main >= 0) text.substring(main).take(3500) else text.take(3500))
                }
            } catch (_: Exception) {
            }
        }
        return sb.toString()
    }

    /** All recent process exits, newest first. */
    fun exitHistory(ctx: Context): String {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return "(needs Android 11+)"
        val list = exits(ctx, 8)
        return if (list.isEmpty()) "(none)" else list.joinToString("\n") { describe(it, false) }
    }

    /**
     * If the app ended abnormally since we last looked, returns a description of it
     * (with the ANR trace when there is one). Each exit is reported only once.
     */
    fun newAbnormalExit(ctx: Context): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        val prefs = ctx.getSharedPreferences("diag", Context.MODE_PRIVATE)
        val seen = prefs.getLong("lastExitSeen", 0L)
        val list = exits(ctx, 8)
        val newest = list.maxOfOrNull { it.timestamp } ?: return null
        prefs.edit().putLong("lastExitSeen", maxOf(seen, newest)).apply()
        val bad = list.firstOrNull { it.timestamp > seen && it.reason in ABNORMAL } ?: return null
        return describe(bad, true)
    }

    /** The newest abnormal exit (crash, ANR, kill, ...) with ANR trace, whether seen or not. */
    fun latestAbnormalExit(ctx: Context): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        val bad = exits(ctx, 8).firstOrNull { it.reason in ABNORMAL } ?: return null
        return describe(bad, true)
    }

    /** Everything useful in one text, for the Share button. */
    fun report(ctx: Context, crash: String?, exit: String?): String = buildString {
        append("DX Cluster Board ${BuildConfig.VERSION_NAME} · Android ${Build.VERSION.RELEASE} ")
        append("(API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL}\n")
        if (crash != null) append("\n=== Crash ===\n").append(crash).append('\n')
        if (exit != null) append("\n=== Last abnormal exit ===\n").append(exit).append('\n')
        append("\n=== Exit history ===\n").append(exitHistory(ctx)).append('\n')
        append("\n=== Events ===\n").append(breadcrumbs(ctx)).append('\n')
    }
}
