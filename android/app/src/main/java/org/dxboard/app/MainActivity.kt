package org.dxboard.app

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.LaunchedEffect

class MainActivity : ComponentActivity() {
    private val vm: BoardViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Diagnostics.breadcrumb(this, "MainActivity onCreate (restored=${savedInstanceState != null})")
        // A crash, or did Android close the app last time? Show the report first (plain screen).
        val exit = if (savedInstanceState == null) Diagnostics.newAbnormalExit(this) else null
        if (exit != null && CrashLog.read(this) == null) CrashLog.save(this, null, exit)
        if (CrashLog.read(this) != null) {
            startActivity(Intent(this, CrashActivity::class.java))
            finish()
            return
        }
        // Used by the emulator test in CI to check the crash report screen.
        if (intent.getBooleanExtra("crashtest", false)) throw RuntimeException("DX test crash")

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
        setContent {
            LaunchedEffect(vm.keepScreenOn) {
                if (vm.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
            DxTheme { BoardApp(vm) }
        }
    }

    override fun onStart() { super.onStart(); Diagnostics.breadcrumb(this, "MainActivity onStart") }
    override fun onStop() { super.onStop(); Diagnostics.breadcrumb(this, "MainActivity onStop") }
    override fun onDestroy() {
        Diagnostics.breadcrumb(this, "MainActivity onDestroy (finishing=$isFinishing, config change=$isChangingConfigurations)")
        super.onDestroy()
    }
}
