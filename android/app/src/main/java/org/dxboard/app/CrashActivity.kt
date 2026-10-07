package org.dxboard.app

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * Shows the last crash report. Built with plain Android views (no Compose),
 * so it still works when the main screen is the thing that crashes.
 */
class CrashActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val report = CrashLog.read(this) ?: "No crash report."
        val pad = (16 * resources.displayMetrics.density).toInt()

        val title = TextView(this).apply {
            text = "The app crashed last time 😕\nPlease tap Share and send this report."
            setTextColor(Color.parseColor("#FFCC33"))
            textSize = 18f
            setTypeface(typeface, Typeface.BOLD)
        }
        val body = TextView(this).apply {
            text = report
            setTextColor(Color.parseColor("#E8ECFF"))
            textSize = 11f
            typeface = Typeface.MONOSPACE
            setTextIsSelectable(true)
            setPadding(0, pad, 0, pad)
        }
        fun button(label: String, color: String, action: () -> Unit) = Button(this).apply {
            text = label
            setBackgroundColor(Color.parseColor(color))
            setTextColor(Color.parseColor("#10131F"))
            setOnClickListener { action() }
            layoutParams = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply { setMargins(pad / 4, 0, pad / 4, 0) }
        }
        val share = button("Share", "#3DFF8C") {
            startActivity(Intent.createChooser(
                Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_SUBJECT, "DX Cluster Board crash")
                    .putExtra(Intent.EXTRA_TEXT, report),
                "Share crash report"))
        }
        val copy = button("Copy", "#4DA3FF") {
            val cm = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("crash", report))
            Toast.makeText(this, "Copied", Toast.LENGTH_SHORT).show()
        }
        val restart = button("Start app", "#FF5E7E") {
            CrashLog.clear(this)
            startActivity(Intent(this, MainActivity::class.java))
            finish()
        }
        val buttons = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(share); addView(copy); addView(restart)
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 3, pad, pad * 3)
            addView(title)
            addView(buttons, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = pad })
            addView(body)
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#0B1020"))
            addView(column, MATCH_PARENT, WRAP_CONTENT)
        })
    }
}
