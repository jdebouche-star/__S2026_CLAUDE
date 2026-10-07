package org.dxboard.app

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

// ------------------------------------------------------------------ colours

val Bg = Color(0xFF0B1020)
val Panel = Color(0xFF131A33)
val Panel2 = Color(0xFF1A2342)
val Fg = Color(0xFFE8ECFF)
val Dim = Color(0xFF8892B8)
val Accent = Color(0xFFFFCC33)
val Glow = Color(0xFFFFF27A)
val Ink = Color(0xFF10131F)

fun c(v: Long) = Color(v)

fun stateColor(s: LinkState?) = when (s) {
    LinkState.CONNECTED, LinkState.RECEIVING -> Color(0xFF3DFF8C)
    LinkState.CONNECTING -> Color(0xFFFFD23D)
    LinkState.RETRY -> Color(0xFFFF9A3D)
    LinkState.ERROR -> Color(0xFFFF4D6D)
    else -> Color(0xFF59607D)
}

private const val NEW_MS = 45_000L

@Composable
fun DxTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Accent, onPrimary = Ink, background = Bg, surface = Panel,
            onBackground = Fg, onSurface = Fg, surfaceVariant = Panel2, onSurfaceVariant = Dim,
            secondaryContainer = Panel2,
        ),
        content = content,
    )
}

/** Ticks every second so ages, the clock and the "new spot" glow update. */
@Composable
fun rememberNow(): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            now = System.currentTimeMillis()
        }
    }
    return now
}

// --------------------------------------------------------------------- app

@Composable
fun BoardApp(vm: BoardViewModel) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val ctx = LocalContext.current
    val now = rememberNow()
    Scaffold(
        containerColor = Bg,
        topBar = {
            Header(vm, now) {
                vm.toggleConnect()?.let { msg ->
                    Toast.makeText(ctx, msg, Toast.LENGTH_LONG).show()
                    tab = 1
                }
            }
        },
        bottomBar = {
            NavigationBar(containerColor = Panel) {
                listOf("📡" to "Spots", "🛰" to "Clusters", "📜" to "Log").forEachIndexed { i, (icon, label) ->
                    NavigationBarItem(
                        selected = tab == i,
                        onClick = { tab = i },
                        icon = { Text(icon, fontSize = 20.sp) },
                        label = { Text(label) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedTextColor = Accent, unselectedTextColor = Dim, indicatorColor = Panel2,
                        ),
                    )
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad).consumeWindowInsets(pad).imePadding().fillMaxSize()) {
            when (tab) {
                0 -> SpotsScreen(vm, now)
                1 -> ClustersScreen(vm)
                else -> LogScreen(vm)
            }
        }
    }
}

@Composable
fun Header(vm: BoardViewModel, now: Long, onConnect: () -> Unit) {
    val utc = remember { SimpleDateFormat("HH:mm:ss", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") } }
    Column(Modifier.background(Bg).statusBarsPadding().padding(top = 8.dp)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(rainbow("DX Cluster Board"), fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Text(utc.format(Date(now)) + " UTC", color = Accent, fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold, fontSize = 15.sp)
            }
            val btn by animateColorAsState(if (vm.connected) Color(0xFFFF5E7E) else Color(0xFF3DFF8C), label = "btn")
            Button(onClick = onConnect, colors = ButtonDefaults.buttonColors(containerColor = btn, contentColor = Ink)) {
                Text(if (vm.connected) "Disconnect" else "Connect", fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.height(8.dp))
        Box(Modifier.fillMaxWidth().height(4.dp).background(Brush.horizontalGradient(BANDS.map { c(it.color) })))
    }
}

fun rainbow(text: String) = buildAnnotatedString {
    var k = 0
    for (ch in text) {
        withStyle(SpanStyle(color = if (ch == ' ') Fg else c(BANDS[k % BANDS.size].color))) { append(ch) }
        if (ch != ' ') k++
    }
}

// ------------------------------------------------------------------- spots

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SpotsScreen(vm: BoardViewModel, now: Long) {
    val visible = vm.visibleSpots()
    val ctx = LocalContext.current
    val listState = rememberLazyListState()
    Column(Modifier.fillMaxSize()) {
        // band activity chips
        val bandCounts = vm.spots.groupingBy { it.band }.eachCount()
        val top = (bandCounts.values.maxOrNull() ?: 0).coerceAtLeast(1)
        LazyRow(
            Modifier.fillMaxWidth().padding(top = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp),
        ) {
            items(BANDS) { b ->
                val on = b.name in vm.bandsOn
                val n = bandCounts[b.name] ?: 0
                val col = c(b.color)
                Column(
                    Modifier
                        .width(54.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(if (on) col.copy(alpha = 0.16f) else Panel)
                        .border(1.5.dp, if (on) col else col.copy(alpha = 0.25f), RoundedCornerShape(12.dp))
                        .combinedClickable(
                            onClick = { vm.toggleBand(b.name, false) },
                            onLongClick = { vm.toggleBand(b.name, true) },
                        )
                        .padding(vertical = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    // mini activity bar
                    Box(Modifier.height(30.dp).width(20.dp), contentAlignment = Alignment.BottomCenter) {
                        if (n > 0) {
                            Box(
                                Modifier.fillMaxWidth().fillMaxHeight(maxOf(0.12f, n.toFloat() / top))
                                    .clip(RoundedCornerShape(4.dp)).background(if (on) col else col.copy(alpha = 0.3f)),
                            )
                        }
                    }
                    Text(b.name, color = if (on) col else Dim, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    Text("$n", color = if (on) Fg else Dim, fontSize = 11.sp)
                }
            }
        }
        // mode chips
        val modeCounts = vm.spots.groupingBy { it.mode }.eachCount()
        LazyRow(
            Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp),
        ) {
            items(MODES) { m ->
                val on = m in vm.modesOn
                val col = c(MODE_COLOR.getValue(m))
                Row(
                    Modifier
                        .clip(RoundedCornerShape(50))
                        .background(if (on) col else Panel)
                        .border(1.5.dp, col, RoundedCornerShape(50))
                        .combinedClickable(
                            onClick = { vm.toggleMode(m, false) },
                            onLongClick = { vm.toggleMode(m, true) },
                        )
                        .padding(horizontal = 12.dp, vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(m, color = if (on) Ink else col, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                    Spacer(Modifier.width(6.dp))
                    Text("${modeCounts[m] ?: 0}", color = if (on) Ink.copy(alpha = 0.7f) else Dim, fontSize = 12.sp)
                }
            }
        }
        // search + counter
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.search, onValueChange = { vm.search = it },
                placeholder = { Text("🔍 Search call or country", color = Dim) },
                singleLine = true, modifier = Modifier.weight(1f),
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                colors = fieldColors(),
            )
            Spacer(Modifier.width(8.dp))
            Column(horizontalAlignment = Alignment.End) {
                Text("${visible.size}", color = Accent, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("of ${vm.spots.size}", color = Dim, fontSize = 11.sp)
            }
        }
        Text("Tap = show/hide · long-press = only this one · tap a spot = QRZ.com",
            color = Dim, fontSize = 10.sp, modifier = Modifier.padding(horizontal = 14.dp))

        if (visible.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("📡", fontSize = 48.sp)
                    Text(
                        when {
                            !vm.connected -> "Press Connect to receive spots"
                            vm.spots.isEmpty() -> "Waiting for spots …"
                            else -> "No spot matches the filters"
                        },
                        color = Dim, fontSize = 16.sp,
                    )
                }
            }
        } else {
            // stay at the top when new spots arrive, unless the user scrolled down
            LaunchedEffect(visible.firstOrNull()?.id) {
                if (listState.firstVisibleItemIndex <= 1) listState.scrollToItem(0)
            }
            LazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(visible, key = { it.id }) { s ->
                    SpotCard(s, vm, now) {
                        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://www.qrz.com/db/" + homeCall(s.call))))
                    }
                }
            }
        }
    }
}

@Composable
fun SpotCard(s: Spot, vm: BoardViewModel, now: Long, onClick: () -> Unit) {
    val bcol = c(bandColor(s.band))
    val mcol = c(MODE_COLOR[s.mode] ?: 0xFF888888)
    val fresh = (1f - (now - s.first).toFloat() / NEW_MS).coerceIn(0f, 1f)
    val age = ((now - s.last) / 60_000L).toInt()
    val fade = 1f - (age.toFloat() / vm.keepMinutes).coerceIn(0f, 1f) * 0.5f
    val cardBg = lerp(Panel, Color(0xFF3A3410), fresh * 0.8f)
    Row(
        Modifier
            .fillMaxWidth()
            .alpha(fade)
            .clip(RoundedCornerShape(12.dp))
            .background(cardBg)
            .clickable(onClick = onClick),
    ) {
        Box(Modifier.width(6.dp).height(78.dp).background(bcol))
        Column(Modifier.weight(1f).padding(horizontal = 10.dp, vertical = 7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.clip(RoundedCornerShape(8.dp)).background(bcol).padding(horizontal = 7.dp, vertical = 2.dp)) {
                    Text(s.band ?: "?", color = Ink, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                }
                Spacer(Modifier.width(8.dp))
                Text(String.format(Locale.US, "%.1f", s.freq), color = bcol, fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold, fontSize = 15.sp)
                Spacer(Modifier.width(10.dp))
                Text(s.call, color = lerp(Fg, Glow, fresh), fontWeight = FontWeight.ExtraBold, fontSize = 19.sp,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Box(
                    Modifier.clip(RoundedCornerShape(50)).border(2.dp, mcol, RoundedCornerShape(50))
                        .padding(horizontal = 9.dp, vertical = 2.dp),
                ) {
                    Text(s.mode, color = mcol, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                }
            }
            Row(Modifier.padding(top = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(s.country.ifEmpty { "—" }, color = Fg, fontSize = 13.sp, maxLines = 1,
                    overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                s.clusters.sorted().take(6).forEach { ci ->
                    Box(Modifier.padding(start = 3.dp).size(9.dp).clip(CircleShape).background(c(clusterColor(ci))))
                }
                Spacer(Modifier.width(8.dp))
                Text("${s.time}z", color = Dim, fontFamily = FontFamily.Monospace, fontSize = 12.sp)
                Text(if (age < 1) " · now" else " · ${age}m", color = Dim, fontSize = 12.sp)
            }
            val who = s.spotters.last() + if (s.spotters.size > 1) "  +${s.spotters.size - 1}" else ""
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = Dim)) { append("de $who") }
                    if (s.comment.isNotEmpty()) {
                        withStyle(SpanStyle(color = Dim.copy(alpha = 0.8f), fontStyle = FontStyle.Italic)) {
                            append("   " + s.comment)
                        }
                    }
                },
                fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

// ---------------------------------------------------------------- clusters

@Composable
fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Accent, unfocusedBorderColor = Color(0xFF2C3866),
    focusedTextColor = Fg, unfocusedTextColor = Fg, cursorColor = Accent,
    focusedContainerColor = Panel2, unfocusedContainerColor = Panel2,
    focusedLabelColor = Accent, unfocusedLabelColor = Dim,
)

@Composable
fun SectionTitle(text: String) {
    Text(text, color = Accent, fontWeight = FontWeight.Bold, fontSize = 14.sp,
        modifier = Modifier.padding(top = 14.dp, bottom = 6.dp))
}

@Composable
fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = Fg, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange, colors = switchColors(Color(0xFF3DFF8C)))
    }
}

@Composable
fun switchColors(col: Color) = SwitchDefaults.colors(
    checkedThumbColor = Ink, checkedTrackColor = col, uncheckedThumbColor = Dim, uncheckedTrackColor = Panel2,
)

@Composable
fun ClustersScreen(vm: BoardViewModel) {
    val ctx = LocalContext.current
    var newName by remember { mutableStateOf("") }
    var newAddr by remember { mutableStateOf("") }
    var keepText by remember { mutableStateOf(vm.keepMinutes.toString()) }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 14.dp)) {
        item {
            SectionTitle("MY STATION")
            Row {
                OutlinedTextField(
                    value = vm.callsign, onValueChange = vm::updateCallsign, label = { Text("My callsign") },
                    singleLine = true, modifier = Modifier.weight(1f), colors = fieldColors(),
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters),
                )
                Spacer(Modifier.width(8.dp))
                OutlinedTextField(
                    value = keepText,
                    onValueChange = { t ->
                        keepText = t.filter { it.isDigit() }.take(3)
                        keepText.toIntOrNull()?.let { vm.updateKeep(it) }
                    },
                    label = { Text("Keep (min)") }, singleLine = true, modifier = Modifier.width(110.dp),
                    colors = fieldColors(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }
            Spacer(Modifier.height(6.dp))
            SwitchRow("Keep screen on", vm.keepScreenOn, vm::updateKeepScreenOn)
            SwitchRow("Demo mode (made-up spots)", vm.demo) { if (!vm.connected) vm.updateDemo(it) }
            Row {
                TextButton(onClick = vm::clearSpots) { Text("Clear spots", color = Color(0xFF4DA3FF)) }
                TextButton(onClick = {
                    if (vm.connected) Toast.makeText(ctx, "Disconnect first", Toast.LENGTH_SHORT).show()
                    else vm.resetClusters()
                }) { Text("Reset cluster list", color = Color(0xFFA77BFF)) }
            }
            SectionTitle("DX CLUSTERS")
            if (vm.connected) {
                Text("Disconnect and connect again to apply changes.", color = Dim, fontSize = 12.sp)
            }
        }
        itemsIndexed(vm.clusters) { i, cl ->
            val st = vm.status[i]
            val n = vm.counts[i] ?: 0
            val col = c(clusterColor(i))
            Row(
                Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp))
                    .background(Panel).padding(start = 10.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(14.dp).clip(CircleShape).background(col))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(cl.name, color = Fg, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    Text("${cl.host}:${cl.port}", color = Dim, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(stateColor(st?.state)))
                        Spacer(Modifier.width(5.dp))
                        Text(
                            if (n > 0) "$n spots" else st?.text ?: "off",
                            color = if (n > 0) Fg else stateColor(st?.state), fontSize = 11.sp,
                        )
                    }
                }
                Switch(checked = cl.enabled, onCheckedChange = { vm.setClusterEnabled(i, it) }, colors = switchColors(col))
                TextButton(onClick = {
                    if (vm.connected) Toast.makeText(ctx, "Disconnect first", Toast.LENGTH_SHORT).show()
                    else vm.removeCluster(i)
                }) { Text("✕", color = Dim, fontSize = 16.sp) }
            }
        }
        item {
            SectionTitle("ADD A CLUSTER")
            OutlinedTextField(
                value = newName, onValueChange = { newName = it.take(10) }, label = { Text("Name (optional)") },
                singleLine = true, modifier = Modifier.fillMaxWidth(), colors = fieldColors(),
            )
            Spacer(Modifier.height(6.dp))
            OutlinedTextField(
                value = newAddr, onValueChange = { newAddr = it.trim() }, label = { Text("host:port") },
                placeholder = { Text("my.cluster.org:7300", color = Dim) },
                singleLine = true, modifier = Modifier.fillMaxWidth(), colors = fieldColors(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            )
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = {
                    val err = vm.addCluster(newName, newAddr)
                    if (err != null) Toast.makeText(ctx, err, Toast.LENGTH_LONG).show()
                    else { newName = ""; newAddr = "" }
                },
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFA77BFF), contentColor = Ink),
            ) { Text("+ Add cluster", fontWeight = FontWeight.Bold) }
            Text("Version ${BuildConfig.VERSION_NAME}", color = Dim, fontSize = 11.sp,
                modifier = Modifier.padding(top = 16.dp))
            Spacer(Modifier.height(24.dp))
        }
    }
}

// --------------------------------------------------------------------- log

@Composable
fun LogScreen(vm: BoardViewModel) {
    val state = rememberLazyListState()
    LaunchedEffect(vm.logs.size) { if (vm.logs.isNotEmpty()) state.scrollToItem(vm.logs.size - 1) }
    LazyColumn(state = state, modifier = Modifier.fillMaxSize().padding(10.dp)) {
        items(vm.logs) { line ->
            Text(
                line, fontFamily = FontFamily.Monospace, fontSize = 11.sp,
                color = when {
                    line.startsWith("⚠") -> Color(0xFFFF6B81)
                    "connected" in line || "loaded" in line -> Color(0xFF3DFF8C)
                    else -> Color(0xFFAAB4E0)
                },
                modifier = Modifier.padding(vertical = 1.dp),
            )
        }
    }
}
