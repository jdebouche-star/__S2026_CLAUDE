package org.dxboard.app

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketTimeoutException
import kotlin.coroutines.coroutineContext

enum class LinkState { OFF, CONNECTING, CONNECTED, RECEIVING, RETRY, ERROR }

interface ClusterListener {
    fun onState(index: Int, state: LinkState, text: String)
    fun onSpot(index: Int, spot: RawSpot)
    fun onLog(text: String, error: Boolean = false)
}

/**
 * Telnet connection to one DX cluster. [run] keeps reconnecting (with back-off)
 * until the coroutine is cancelled. Pure JVM, no Android classes.
 */
class ClusterClient(
    private val index: Int,
    private val def: ClusterDef,
    private val callsign: String,
    private val listener: ClusterListener,
) {
    private val rbn = def.host.contains("reversebeacon", ignoreCase = true)
    @Volatile private var socket: Socket? = null

    suspend fun run() {
        var backoff = 5_000L
        try {
            while (coroutineContext.isActive) {
                try {
                    listener.onState(index, LinkState.CONNECTING, "connecting")
                    withContext(Dispatchers.IO) { session() }
                    backoff = 5_000L
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (!coroutineContext.isActive) break
                    listener.onLog("[${def.name}] ${e.message ?: e.javaClass.simpleName}", true)
                    listener.onState(index, LinkState.ERROR, (e.message ?: "error").take(40))
                } finally {
                    close()
                }
                listener.onState(index, LinkState.RETRY, "retry in ${backoff / 1000}s")
                delay(backoff)
                backoff = (backoff * 2).coerceAtMost(120_000L)
            }
        } finally {
            close()
            listener.onState(index, LinkState.OFF, "off")
        }
    }

    fun close() {
        try { socket?.close() } catch (_: IOException) { }
        socket = null
    }

    private suspend fun session() {
        val s = Socket()
        socket = s
        s.connect(InetSocketAddress(def.host, def.port), 20_000)
        s.soTimeout = 1_000
        listener.onState(index, LinkState.CONNECTED, "connected")
        listener.onLog("[${def.name}] connected to ${def.host}:${def.port}")
        val input = s.getInputStream()
        val output = s.getOutputStream()
        val buf = ByteArray(4096)
        val line = ByteArrayOutputStream()
        var loggedIn = false
        val t0 = System.currentTimeMillis()
        var spots = 0
        var infoLines = 0
        var iac = 0              // telnet negotiation state
        var iacCmd = 0
        while (coroutineContext.isActive) {
            val n = try { input.read(buf) } catch (_: SocketTimeoutException) { 0 }
            if (n < 0) throw IOException("closed by remote host")
            for (i in 0 until n) {
                val b = buf[i].toInt() and 0xFF
                when (iac) {
                    0 -> if (b == 255) iac = 1 else when (b) {
                        10 -> {
                            val text = line.toString(Charsets.ISO_8859_1.name()).trim('\r', '\u0007', ' ', '\t')
                            line.reset()
                            val dx = text.indexOf("DX de")   // a prompt may sit in front of it
                            if (dx >= 0) {
                                parseSpotLine(text.substring(dx), rbn)?.let {
                                    spots++
                                    if (spots == 1) listener.onState(index, LinkState.RECEIVING, "receiving")
                                    listener.onSpot(index, it)
                                }
                            } else if (text.isNotEmpty() && infoLines < 5) {
                                infoLines++
                                listener.onLog("[${def.name}] ${text.take(100)}")
                            }
                        }
                        else -> if (line.size() < 4096) line.write(b)
                    }
                    1 -> when (b) {
                        251, 252, 253, 254 -> { iacCmd = b; iac = 2 }
                        255 -> { line.write(255); iac = 0 }
                        else -> iac = 0
                    }
                    2 -> {
                        // refuse every option
                        when (iacCmd) {
                            253 -> output.write(byteArrayOf(255.toByte(), 252.toByte(), b.toByte()))
                            251 -> output.write(byteArrayOf(255.toByte(), 254.toByte(), b.toByte()))
                        }
                        output.flush()
                        iac = 0
                    }
                }
            }
            if (!loggedIn) {
                val tail = line.toString(Charsets.ISO_8859_1.name()).lowercase()
                if ("call" in tail || "login" in tail || System.currentTimeMillis() - t0 > 10_000) {
                    output.write("$callsign\r\n".toByteArray(Charsets.US_ASCII))
                    output.flush()
                    loggedIn = true
                    line.reset()             // drop the prompt
                    listener.onLog("[${def.name}] logged in as $callsign")
                }
            }
        }
    }
}
