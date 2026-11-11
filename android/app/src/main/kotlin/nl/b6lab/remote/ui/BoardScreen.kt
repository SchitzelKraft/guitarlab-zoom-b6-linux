package nl.b6lab.remote.ui

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import kotlinx.coroutines.delay
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import nl.b6lab.remote.core.BoardUi
import nl.b6lab.remote.core.KnobView
import nl.b6lab.remote.core.RemoteController
import kotlin.math.roundToInt

internal const val PLACES = 6

/**
 * The board. [onAddEffect] gets the entry index of the new place, [onLongPressPedal] the entry index (both open the
 * chooser, wired by the chooser screen). [onReconnect], when given, puts a Reconnect button in the not-connected banner.
 */
@Composable
fun BoardScreen(
    ui: BoardUi,
    controller: RemoteController,
    onAddEffect: (place: Int) -> Unit,
    onLongPressPedal: (slot: Int) -> Unit,
    modifier: Modifier = Modifier,
    onSearch: () -> Unit = {},
    onReconnect: (() -> Unit)? = null,
) {
    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    val loader = rememberSvgLoader()
    var fine by remember { mutableStateOf<Int?>(null) }
    val fineKnob = ui.knobs.firstOrNull { it.index == fine }

    Column(
        modifier
            .fillMaxSize()
            .background(B6Colors.Gunmetal)
            .safeDrawingPadding()
            .padding(horizontal = 12.dp),
    ) {
        Header(ui, controller, landscape, onSearch)
        Banners(ui, onReconnect)
        if (landscape) {
            PedalGrid(ui, controller, loader, 6, 116.dp, onAddEffect, onLongPressPedal, Modifier.fillMaxWidth())
            Spacer(Modifier.height(4.dp))
            Dials(ui, controller, true, { fine = it }, Modifier.fillMaxWidth().weight(1f))
        } else {
            // the places and the knobs of the selected pedal; the page scrolls only when the knobs do not fit
            Column(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState())) {
                Spacer(Modifier.height(8.dp))
                PedalGrid(ui, controller, loader, 3, 120.dp, onAddEffect, onLongPressPedal, Modifier.fillMaxWidth())
                Spacer(Modifier.height(12.dp))
                Dials(ui, controller, false, { fine = it }, Modifier.fillMaxWidth())
                Spacer(Modifier.height(12.dp))
            }
        }
    }
    if (fineKnob != null) FineSheet(fineKnob, controller) { fine = null }
}

@Composable
private fun BankLabel(ui: BoardUi, size: androidx.compose.ui.unit.TextUnit) {
    Row(verticalAlignment = Alignment.Bottom) {
        if (ui.bankLetters.isNotEmpty()) {
            Text(ui.bankLetters, style = B6Text.Title, color = B6Colors.Amber, fontSize = size, maxLines = 1, softWrap = false)
            Text("-" + ui.patchNumber, style = B6Text.Label, color = B6Colors.SilkscreenDim, fontSize = size, maxLines = 1, softWrap = false)
        }
    }
}

@Composable
private fun Header(ui: BoardUi, c: RemoteController, landscape: Boolean, onSearch: () -> Unit) {
    val nav: @Composable () -> Unit = {
        SearchButton(onSearch)
        NavButton("◀") { c.previousPatch() }
        NavButton("▶") { c.nextPatch() }
    }
    val status: @Composable () -> Unit = {
        Box(
            Modifier.size(12.dp).clip(CircleShape)
                .background(if (ui.connected) B6Colors.Amber else B6Colors.SilkscreenDim),
        )
        Spacer(Modifier.width(8.dp))
        SaveButton(ui.canSave) { c.save() }
    }
    if (landscape) {
        Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
            BankLabel(ui, 18.sp)
            Spacer(Modifier.width(12.dp))
            Text(
                ui.name, style = B6Text.Title, fontSize = 26.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            nav()
            Spacer(Modifier.width(8.dp))
            status()
        }
    } else {
        Column(Modifier.fillMaxWidth()) {
            Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) { BankLabel(ui, 20.sp) }
                nav()
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    ui.name, style = B6Text.Title, fontSize = 40.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                status()
            }
        }
    }
}

/** A small pill (32 dp) inside a 48 dp touch target. */
@Composable
private fun SaveButton(enabled: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.height(48.dp).widthIn(min = 64.dp).clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.height(32.dp).clip(RoundedCornerShape(16.dp))
                .background(if (enabled) B6Colors.Amber else B6Colors.Panel)
                .padding(horizontal = 16.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "Save", style = B6Text.Button, fontSize = 16.sp,
                color = if (enabled) B6Colors.Gunmetal else B6Colors.SilkscreenDim,
            )
        }
    }
}

@Composable
private fun SearchButton(onClick: () -> Unit) {
    Box(
        Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(Icons.Default.Search, contentDescription = "Search patches", tint = B6Colors.Silkscreen, modifier = Modifier.size(26.dp)) }
}

@Composable
private fun NavButton(label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(label, style = B6Text.Label, fontSize = 22.sp) }
}

@Composable
private fun Banners(ui: BoardUi, onReconnect: (() -> Unit)?) {
    if (!ui.connected) Banner("B6 not connected", B6Colors.Silkscreen, "Reconnect".takeIf { onReconnect != null }, onReconnect)
    if (ui.autoSaveWarning) Banner("Auto save is on: the pedal stores every change", B6Colors.Silkscreen)
    ui.error?.let { Banner(it, B6Colors.LedRed) }
}

@Composable
private fun Banner(
    text: String,
    color: androidx.compose.ui.graphics.Color,
    action: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 6.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(B6Colors.Panel)
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, style = B6Text.Label, color = color, fontSize = 16.sp, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
        if (action != null && onAction != null) {
            Box(
                Modifier.height(48.dp).clickable(onClick = onAction).padding(horizontal = 12.dp),
                contentAlignment = Alignment.Center,
            ) { Text(action, style = B6Text.Button, color = B6Colors.Amber, fontSize = 16.sp) }
        }
    }
}

/**
 * The six places in chain order, [cols] per row: the pedals, then a "+" per free place, then quiet empty cells.
 * Cells are placed absolutely so a dragged pedal can cross rows; a drop maps the cell under the finger to the
 * position among the shown pedals ([RemoteController.movePedal]).
 */
@Composable
private fun PedalGrid(
    ui: BoardUi,
    c: RemoteController,
    loader: coil.ImageLoader,
    cols: Int,
    cellHeight: Dp,
    onAdd: (Int) -> Unit,
    onLong: (Int) -> Unit,
    modifier: Modifier,
) {
    val gap = 8.dp
    val density = LocalDensity.current
    val rows = (PLACES + cols - 1) / cols
    val used = ui.pedals.size
    val plus = ui.freePlaces.coerceAtMost((PLACES - used).coerceAtLeast(0))
    val nextEntry = (ui.pedals.maxOfOrNull { it.slot } ?: -1) + 1
    var dragging by remember { mutableStateOf(false) }
    // a row without a pedal or "+" collapses to a thin strip, except while a pedal is dragged (it is a drop row)
    val collapseH = 24.dp
    val rowH = List(rows) { r ->
        if (r > 0 && used + plus <= r * cols && !dragging) collapseH else cellHeight
    }
    val rowY = rowH.runningFold(0.dp) { acc, h -> acc + h + gap }
    BoxWithConstraints(modifier.height(rowH.fold(0.dp) { acc, h -> acc + h } + gap * (rows - 1))) {
        val cellW = (maxWidth - gap * (cols - 1)) / cols
        val pitchX = with(density) { (cellW + gap).toPx() }
        val pitchY = with(density) { (cellHeight + gap).toPx() }
        fun place(i: Int) = Modifier
            .offset(x = (cellW + gap) * (i % cols), y = rowY[i / cols])
            .size(cellW, rowH[i / cols])
        ui.pedals.forEachIndexed { i, p ->
            key(p.slot) {
                Pedal(
                    view = p, index = i, count = used, cols = cols, pitchX = pitchX, pitchY = pitchY, loader = loader,
                    onTap = { c.tapPedal(p.slot) },
                    onToggle = { c.togglePedal(p.slot) },
                    onLongPress = { onLong(p.slot) },
                    onMoveTo = { target -> c.movePedal(p.slot, target) },
                    onDragActive = { dragging = it },
                    modifier = place(i),
                )
            }
        }
        for (r in 0 until rows) {
            if (rowH[r] == collapseH && r > 0) {
                EmptyPlace(null, Modifier.offset(y = rowY[r]).fillMaxWidth().height(collapseH))
            } else {
                for (i in maxOf(used, r * cols) until minOf(PLACES, (r + 1) * cols)) {
                    EmptyPlace(if (i - used < plus) ({ onAdd(nextEntry) }) else null, place(i))
                }
            }
        }
    }
}

@Composable
private fun Dials(ui: BoardUi, c: RemoteController, landscape: Boolean, onFine: (Int) -> Unit, modifier: Modifier) {
    if (landscape) {
        // one row, the whole width: the amber outline on the board shows which effect these are
        BoxWithConstraints(modifier) {
            val n = ui.knobs.size.coerceAtLeast(1)
            val size = minOf(112.dp, maxWidth / n - 4.dp, maxHeight - 24.dp).coerceAtLeast(48.dp)
            Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
                ui.knobs.forEach { k -> Dial(k, { c.dragKnob(k.index, it) }, { onFine(k.index) }, Modifier.weight(1f), size = size) }
            }
        }
    } else {
        BoxWithConstraints(modifier) {
            val size = (maxWidth / 4 - 8.dp).coerceIn(48.dp, 96.dp)
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ui.knobs.chunked(4).forEach { row ->
                    Row(Modifier.fillMaxWidth()) {
                        row.forEach { k -> Dial(k, { c.dragKnob(k.index, it) }, { onFine(k.index) }, Modifier.weight(1f), size = size) }
                        repeat(4 - row.size) { Spacer(Modifier.weight(1f)) }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FineSheet(knob: KnobView, c: RemoteController, onDismiss: () -> Unit) {
    var local by remember { mutableStateOf<Int?>(null) }
    // the last value the step buttons sent, until the knob shows it: fast taps add up
    var stepped by remember(knob.index) { mutableStateOf<Int?>(null) }
    LaunchedEffect(knob.value) { if (knob.value == stepped) stepped = null }
    // a refused step never shows up as the knob value: do not keep it as the base for the next step
    LaunchedEffect(stepped) { if (stepped != null) { delay(1000); stepped = null } }
    val step = { d: Int ->
        val v = ((local ?: stepped ?: knob.value) + d).coerceIn(0, knob.max)
        stepped = v
        c.dragKnob(knob.index, v)
    }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = B6Colors.Panel) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(knob.name, style = B6Text.Label, color = B6Colors.SilkscreenDim, fontSize = 20.sp)
            Text(
                local?.takeIf { it != knob.value }?.toString() ?: knob.text,
                style = B6Text.Value, fontSize = 56.sp,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                StepButton("−") { step(-1) }
                Slider(
                    value = (local ?: knob.value).toFloat(),
                    onValueChange = {
                        val v = it.roundToInt().coerceIn(0, knob.max)
                        local = v
                        stepped = v
                        c.dragKnob(knob.index, v)
                    },
                    onValueChangeFinished = { local = null },
                    valueRange = 0f..knob.max.toFloat().coerceAtLeast(1f),
                    colors = SliderDefaults.colors(
                        thumbColor = B6Colors.Amber,
                        activeTrackColor = B6Colors.Amber,
                        inactiveTrackColor = B6Colors.SilkscreenDim.copy(alpha = 0.3f),
                    ),
                    modifier = Modifier.weight(1f).height(56.dp),
                )
                StepButton("+") { step(1) }
            }
        }
    }
}

@Composable
private fun StepButton(label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(56.dp).clip(RoundedCornerShape(12.dp))
            .border(1.5.dp, B6Colors.Silkscreen, RoundedCornerShape(12.dp)).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(label, style = B6Text.Button, fontSize = 30.sp) }
}
