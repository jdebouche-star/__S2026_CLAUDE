package org.dxboard.app

import android.app.Application
import android.content.Context
import android.os.Build
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter

/** Installs the crash recorder before any activity starts. */
class DxApp : Application() {
    override fun onCreate() {
        super.onCreate()
        CrashLog.install(this)
        val proc = if (android.os.Build.VERSION.SDK_INT >= 28) getProcessName() else "?"
        Diagnostics.breadcrumb(this, "--- process started: $proc (${BuildConfig.VERSION_NAME}) ---")
    }
}

/** Saves an uncaught exception to a file, so CrashActivity can show it on the next start. */
object CrashLog {
    private fun file(ctx: Context) = File(ctx.filesDir, "last_crash.txt")

    fun install(ctx: Context) {
        val app = ctx.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        if (previous is Handler) return
        Thread.setDefaultUncaughtExceptionHandler(Handler(app, previous))
    }

    private class Handler(
        val app: Context,
        val previous: Thread.UncaughtExceptionHandler?,
    ) : Thread.UncaughtExceptionHandler {
        override fun uncaughtException(t: Thread, e: Throwable) {
            try {
                val sw = StringWriter()
                e.printStackTrace(PrintWriter(sw))
                Diagnostics.breadcrumb(app, "CRASH in thread ${t.name}: $e")
                save(app, "Thread: ${t.name}\n" + sw.toString().take(8000), null)
            } catch (_: Throwable) {
            }
            previous?.uncaughtException(t, e)
        }
    }

    fun save(ctx: Context, crash: String?, exit: String?) {
        try {
            file(ctx).writeText(Diagnostics.report(ctx, crash, exit))
        } catch (_: Throwable) {
        }
    }

    fun read(ctx: Context): String? = try {
        file(ctx).takeIf { it.exists() }?.readText()
    } catch (_: Exception) {
        null
    }

    fun clear(ctx: Context) {
        file(ctx).delete()
    }
}
