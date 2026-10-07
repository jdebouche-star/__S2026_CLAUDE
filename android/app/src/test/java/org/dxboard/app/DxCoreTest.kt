package org.dxboard.app

import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ServerSocket
import java.util.Collections
import kotlin.concurrent.thread

class DxCoreTest {

    @Test
    fun parsesClusterSpot() {
        val s = parseSpotLine("DX de DL1ABC:     14025.0  VP8LP        CW up 1                        1234Z")!!
        assertEquals("DL1ABC", s.spotter)
        assertEquals(14025.0, s.freq, 0.001)
        assertEquals("VP8LP", s.call)
        assertEquals("20m", s.band)
        assertEquals("CW", s.mode)
        assertEquals("1234", s.time)
    }

    @Test
    fun parsesRbnSpot() {
        val s = parseSpotLine("DX de KM3T-2-#:  7074.0  JA1XYZ       FT8 -12 dB                     0001Z", rbn = true)!!
        assertEquals("KM3T", s.spotter)
        assertEquals("FT8", s.mode)
        assertEquals("40m", s.band)
    }

    @Test
    fun infersModeFromFrequency() {
        assertEquals("SSB", parseSpotLine("DX de ON4UN:     21295.0  EA8/ON4XX    59 tnx   2359Z")!!.mode)
        assertEquals("FT8", parseSpotLine("DX de ON4UN:     14075.2  K1ABC    -10   2359Z")!!.mode)
        assertEquals("CW", parseSpotLine("DX de ON4UN:     7012.0  K1ABC    tnx   2359Z")!!.mode)
    }

    @Test
    fun rejectsGarbage() {
        assertNull(parseSpotLine("Hello DL1ABC, welcome"))
        assertNull(parseSpotLine("DX de DL1ABC:  14025.0  HELLO   test  1234Z"))
    }

    @Test
    fun callHelpers() {
        assertEquals("ON4XX", homeCall("EA8/ON4XX/P"))
        assertEquals("EA8", locationPrefix("EA8/ON4XX"))
        assertEquals("K1ABC", locationPrefix("K1ABC/4"))
        assertNull(locationPrefix("W1AW/MM"))
    }

    @Test
    fun ctyLookup() {
        val db = CtyDatabase()
        db.load(
            """
            Belgium:                  14:  27:  EU:   50.70:    -4.85:    -1.0:  ON:
                ON,OO,OP,OQ,OR,OS,OT;
            Canary Islands:           33:  36:  AF:   28.32:    15.85:     0.0:  EA8:
                AM8,AN8,AO8,EA8,EB8,EC8(33)[36],ED8,EE8,EF8,EG8,EH8;
            Falkland Islands:         13:  16:  SA:  -51.63:    58.72:     4.0:  VP8:
                VP8,=VP8LP;
            """.trimIndent(),
        )
        assertEquals("Belgium", db.find("ON4UN"))
        assertEquals("Canary Islands", db.find("EA8/ON4XX"))
        assertEquals("Canary Islands", db.find("EC8AAA"))
        assertEquals("Falkland Islands", db.find("VP8LP"))
        assertNull(db.find("ZZ9Z"))
    }

    @Test
    fun clientLogsInAndReceivesSpots() = runBlocking {
        val server = ServerSocket(0)
        val received = Collections.synchronizedList(mutableListOf<RawSpot>())
        val logins = Collections.synchronizedList(mutableListOf<String>())
        thread(isDaemon = true) {
            server.accept().use { s ->
                val out = s.getOutputStream()
                // telnet negotiation (IAC DO ECHO) + login prompt
                out.write(byteArrayOf(255.toByte(), 253.toByte(), 1))
                out.write("Welcome to the test cluster\r\nPlease enter your call: ".toByteArray())
                out.flush()
                val reader = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
                val line = reader.readLine()
                logins += line.filter { it.isLetterOrDigit() }
                out.write("DX de DL1ABC:     14025.0  VP8LP        CW up 1                        1234Z\r\n".toByteArray())
                out.write("DX de G3XYZ:      21295.0  ZL7X         59                             1235Z\u0007\u0007\r\n".toByteArray())
                out.flush()
                Thread.sleep(3000)
            }
        }
        val listener = object : ClusterListener {
            override fun onState(index: Int, state: LinkState, text: String) {}
            override fun onSpot(index: Int, spot: RawSpot) { received += spot }
            override fun onLog(text: String, error: Boolean) {}
        }
        val client = ClusterClient(0, ClusterDef("TEST", "127.0.0.1", server.localPort, true), "ON4TEST", listener)
        val job = launch(Dispatchers.IO) { client.run() }
        withTimeout(8000) { while (received.size < 2) delay(50) }
        job.cancel()
        server.close()
        assertTrue(logins.first().endsWith("ON4TEST"))
        assertEquals(listOf("VP8LP", "ZL7X"), received.map { it.call })
        assertEquals("SSB", received[1].mode)
    }
}
