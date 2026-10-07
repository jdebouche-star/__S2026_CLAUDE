package org.dxboard.hello

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.TextView

/** Counts seconds. If the number keeps going up, the phone lets the app run. */
class HelloActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private var seconds = 0
    private lateinit var text: TextView

    private val tick = object : Runnable {
        override fun run() {
            seconds++
            text.text = "DX Test\n\nRunning for $seconds s\n\n" +
                "If this number keeps going up,\nthe phone lets the app run."
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        text = TextView(this).apply {
            setBackgroundColor(Color.parseColor("#0B1020"))
            setTextColor(Color.parseColor("#3DFF8C"))
            textSize = 24f
            gravity = Gravity.CENTER
        }
        setContentView(text)
    }

    override fun onResume() {
        super.onResume()
        handler.post(tick)
    }

    override fun onPause() {
        handler.removeCallbacks(tick)
        super.onPause()
    }
}
