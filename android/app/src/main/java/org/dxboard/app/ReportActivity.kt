package org.dxboard.app

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
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
 * "DX Board Report": a second launcher icon with a plain screen (no Compose)
 * that shows why Android closed the app, and can start it in safe mode.
 */
class ReportActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val report = Diagnostics.report(this, CrashLog.read(this), Diagnostics.latestAbnormalExit(this))
        val pad = (16 * resources.displayMetrics.density).toInt()

        fun button(label: String, color: String, action: () -> Unit) = Button(this).apply {
            text = label
            isAllCaps = false
            setBackgroundColor(Color.parseColor(color))
            setTextColor(Color.parseColor("#10131F"))
            setOnClickListener { action() }
            layoutParams = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f).apply { setMargins(pad / 4, pad / 4, pad / 4, pad / 4) }
        }
        fun row(vararg b: Button) = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            b.forEach { addView(it) }
        }
        fun start(safe: Boolean) {
            getSharedPreferences("dxboard", Context.MODE_PRIVATE).edit().putBoolean("safeMode", safe).commit()
            CrashLog.clear(this)
            Diagnostics.breadcrumb(this, "Report screen: start app (safe=$safe)")
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            finish()
        }

        val title = TextView(this).apply {
            text = "DX Board Report\nTap Share and send this text."
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
        val share = button("Share", "#3DFF8C") {
            startActivity(Intent.createChooser(
                Intent(Intent.ACTION_SEND).setType("text/plain")
                    .putExtra(Intent.EXTRA_SUBJECT, "DX Cluster Board report")
                    .putExtra(Intent.EXTRA_TEXT, report),
                "Share report"))
        }
        val copy = button("Copy", "#4DA3FF") {
            val cm = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("report", report))
            Toast.makeText(this, "Copied", Toast.LENGTH_SHORT).show()
        }
        val safe = button("Safe start\n(no country list)", "#FFB347") { start(true) }
        val normal = button("Normal start", "#FF5E7E") { start(false) }

        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 3, pad, pad * 3)
            addView(title)
            addView(row(share, copy), LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { topMargin = pad })
            addView(row(safe, normal), LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            addView(body)
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#0B1020"))
            addView(column, MATCH_PARENT, WRAP_CONTENT)
        })
    }
}
