package org.dxboard.app

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.sp
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter

class MainActivity : ComponentActivity() {
    private val vm: BoardViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        CrashLog.install(this)
        super.onCreate(savedInstanceState)
        // dark bars with light icons, whatever the phone's theme is
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        // adb shell am start -n org.dxboard.app/.MainActivity --ez demo true
        if (savedInstanceState == null && intent.getBooleanExtra("demo", false)) {
            vm.updateDemo(true)
            if (!vm.connected) vm.toggleConnect()
        }
        val lastCrash = CrashLog.read(this)
        setContent {
            LaunchedEffect(vm.keepScreenOn) {
                if (vm.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
            DxTheme {
                BoardApp(vm)
                var crash by remember { mutableStateOf(lastCrash) }
                crash?.let { text ->
                    AlertDialog(
                        onDismissRequest = { CrashLog.clear(this); crash = null },
                        title = { Text("The app crashed last time") },
                        text = {
                            Text(text, fontFamily = FontFamily.Monospace, fontSize = 10.sp,
                                modifier = Modifier.verticalScroll(rememberScrollState()))
                        },
                        confirmButton = {
                            TextButton(onClick = {
                                startActivity(Intent.createChooser(
                                    Intent(Intent.ACTION_SEND).setType("text/plain")
                                        .putExtra(Intent.EXTRA_SUBJECT, "DX Cluster Board crash")
                                        .putExtra(Intent.EXTRA_TEXT, text),
                                    "Share crash report"))
                            }) { Text("Share") }
                        },
                        dismissButton = {
                            TextButton(onClick = { CrashLog.clear(this); crash = null }) { Text("Close") }
                        },
                    )
                }
            }
        }
    }
}

/** Saves an uncaught exception to a file, so it can be shown on the next start. */
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
                val version = try {
                    app.packageManager.getPackageInfo(app.packageName, 0).versionName
                } catch (_: Exception) { "?" }
                file(app).writeText(
                    "App $version · Android ${Build.VERSION.RELEASE} " +
                        "(API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL}\n" +
                        "Thread: ${t.name}\n\n" + sw.toString().take(6000),
                )
            } catch (_: Throwable) {
            }
            previous?.uncaughtException(t, e)
        }
    }

    fun read(ctx: Context): String? = file(ctx).takeIf { it.exists() }?.readText()

    fun clear(ctx: Context) {
        file(ctx).delete()
    }
}
