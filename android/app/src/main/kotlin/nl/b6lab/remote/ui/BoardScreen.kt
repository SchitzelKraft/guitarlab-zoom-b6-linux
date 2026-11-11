package nl.b6lab.remote.ui

import android.content.res.Configuration
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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

private const val PLACES = 6

/**
 * The board. [onAddEffect] gets the entry index of the new place, [onLongPressPedal] the entry index (both open the
 * chooser, wired by the chooser screen).
 */
@Composable
fun BoardScreen(
    ui: BoardUi,
    controller: RemoteController,
    onAddEffect: (place: Int) -> Unit,
    onLongPressPedal: (slot: Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    val loader = rememberSvgLoader()
    var fine by remember { mutableStateOf<Int?>(null) }
    val fineKnob = ui.knobs.firstOrNull { it.index == fine }

    Column(
        modifier
            .fillMaxSize()
            .background(B6Colors.Background)
            .safeDrawingPadding()
            .padding(horizontal = 12.dp),
    ) {
        Header(ui, controller, landscape)
        Banners(ui)
        val pedals: @Composable (Modifier) -> Unit = { m ->
            PedalRow(ui, controller, loader, landscape, onAddEffect, onLongPressPedal, m)
        }
        val dials: @Composable (Modifier) -> Unit = { m ->
            Dials(ui, controller, landscape, { fine = it }, m)
        }
        if (landscape) {
            pedals(Modifier.fillMaxWidth().height(116.dp))
            Spacer(Modifier.height(4.dp))
            dials(Modifier.fillMaxWidth().weight(1f))
        } else {
            pedals(Modifier.fillMaxWidth().height(140.dp))
            Spacer(Modifier.height(12.dp))
            dials(Modifier.fillMaxWidth().weight(1f))
        }
    }
    if (fineKnob != null) FineSheet(fineKnob, controller) { fine = null }
}

@Composable
private fun Header(ui: BoardUi, c: RemoteController, landscape: Boolean) {
    val controls: @Composable () -> Unit = {
        NavButton("◀") { c.previousPatch() }
        NavButton("▶") { c.nextPatch() }
        Spacer(Modifier.width(8.dp))
        Box(
            Modifier.size(12.dp).clip(CircleShape)
                .background(if (ui.connected) B6Colors.Ok else B6Colors.Error),
        )
        Spacer(Modifier.width(8.dp))
        SaveButton(ui.canSave) { c.save() }
    }
    if (landscape) {
        Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(ui.header, color = B6Colors.TextDim, fontSize = 13.sp, maxLines = 1, softWrap = false)
                Text(ui.name, color = B6Colors.Text, fontSize = 24.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            controls()
        }
    } else {
        Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
            Text(ui.header, color = B6Colors.TextDim, fontSize = 14.sp, maxLines = 1, softWrap = false)
            Text(
                ui.name, color = B6Colors.Text, fontSize = 36.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                controls()
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
                .background(if (enabled) B6Colors.Accent else B6Colors.Surface)
                .padding(horizontal = 16.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text("Save", fontSize = 14.sp, color = if (enabled) B6Colors.Background else B6Colors.TextDim)
        }
    }
}

@Composable
private fun NavButton(label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(label, color = B6Colors.Text, fontSize = 22.sp) }
}

@Composable
private fun Banners(ui: BoardUi) {
    if (!ui.connected) Banner("B6 not connected", B6Colors.Error)
    if (ui.autoSaveWarning) Banner("AUTO SAVE is on: the pedal stores every change", B6Colors.Warn)
    ui.error?.let { Banner(it, B6Colors.Error) }
}

@Composable
private fun Banner(text: String, color: androidx.compose.ui.graphics.Color) {
    Text(
        text,
        color = color,
        fontSize = 14.sp,
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 6.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.15f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
    )
}

@Composable
private fun PedalRow(
    ui: BoardUi,
    c: RemoteController,
    loader: coil.ImageLoader,
    landscape: Boolean,
    onAdd: (Int) -> Unit,
    onLong: (Int) -> Unit,
    modifier: Modifier,
) {
    val gap = 8.dp
    val density = LocalDensity.current
    val used = ui.pedals.size
    val plus = ui.freePlaces.coerceAtMost((PLACES - used).coerceAtLeast(0))
    val nextEntry = (ui.pedals.maxOfOrNull { it.slot } ?: -1) + 1
    BoxWithConstraints(modifier) {
        val cell: Dp = if (landscape) (maxWidth - gap * (PLACES - 1)) / PLACES else 96.dp
        val pitch = with(density) { (cell + gap).toPx() }
        val scroll = rememberScrollState()
        val viewport = with(density) { maxWidth.toPx() }
        val selIndex = ui.pedals.indexOfFirst { it.selected }
        // the selected pedal is scrolled into view (a new patch selects its first pedal: back to the start)
        LaunchedEffect(selIndex, used, ui.header, pitch, viewport, scroll.maxValue) {
            if (landscape || selIndex < 0) return@LaunchedEffect
            val left = selIndex * pitch
            val right = left + pitch - with(density) { gap.toPx() }
            val target = when {
                left < scroll.value -> left
                right > scroll.value + viewport -> right - viewport
                else -> return@LaunchedEffect
            }
            scroll.animateScrollTo(target.roundToInt().coerceAtLeast(0))
        }
        val rowMod = if (landscape) Modifier.fillMaxSize() else Modifier.fillMaxSize().horizontalScroll(scroll)
        Row(rowMod, horizontalArrangement = Arrangement.spacedBy(gap)) {
            ui.pedals.forEachIndexed { i, p ->
              key(p.slot) {
                Pedal(
                    view = p, index = i, count = used, pitchPx = pitch, loader = loader,
                    onTap = { c.tapPedal(p.slot) },
                    onToggle = { c.togglePedal(p.slot) },
                    onLongPress = { onLong(p.slot) },
                    onMoveTo = { target -> c.move(p.slot, ui.pedals[target].slot) },
                    wholeDrag = landscape,
                    modifier = Modifier.width(cell).fillMaxSize(),
                )
              }
            }
            repeat(plus) {
                EmptyPlace({ onAdd(nextEntry) }, Modifier.width(cell).fillMaxSize())
            }
        }
    }
}

@Composable
private fun Dials(ui: BoardUi, c: RemoteController, landscape: Boolean, onFine: (Int) -> Unit, modifier: Modifier) {
    if (landscape) {
        // one row, the whole width: the blue outline on the board shows which effect these are
        BoxWithConstraints(modifier) {
            val n = ui.knobs.size.coerceAtLeast(1)
            val size = minOf(112.dp, maxWidth / n - 4.dp, maxHeight - 24.dp).coerceAtLeast(48.dp)
            Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
                ui.knobs.forEach { k -> Dial(k, { c.dragKnob(k.index, it) }, { onFine(k.index) }, Modifier.weight(1f), size = size) }
            }
        }
    } else {
        Column(modifier) {
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                ui.knobs.chunked(3).forEach { row ->
                    Row(Modifier.fillMaxWidth()) {
                        row.forEach { k -> Dial(k, { c.dragKnob(k.index, it) }, { onFine(k.index) }, Modifier.weight(1f), size = 84.dp) }
                        repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
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
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = B6Colors.Surface) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(knob.name, color = B6Colors.TextDim, fontSize = 16.sp)
            Text(
                local?.takeIf { it != knob.value }?.toString() ?: knob.text,
                color = B6Colors.Text, fontSize = 40.sp,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                StepButton("-") { c.dragKnob(knob.index, knob.value - 1) }
                Slider(
                    value = (local ?: knob.value).toFloat(),
                    onValueChange = {
                        val v = it.roundToInt().coerceIn(0, knob.max)
                        local = v
                        c.dragKnob(knob.index, v)
                    },
                    onValueChangeFinished = { local = null },
                    valueRange = 0f..knob.max.toFloat().coerceAtLeast(1f),
                    modifier = Modifier.weight(1f).height(56.dp),
                )
                StepButton("+") { c.dragKnob(knob.index, knob.value + 1) }
            }
        }
    }
}

@Composable
private fun StepButton(label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).background(B6Colors.SurfaceHigh).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Text(label, color = B6Colors.Text, fontSize = 28.sp) }
}
