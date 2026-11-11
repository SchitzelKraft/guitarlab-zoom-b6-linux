package nl.b6lab.remote.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import nl.b6lab.remote.core.KnobView
import kotlin.math.roundToInt

/** Full range of a knob over this much vertical drag. */
private val DRAG_RANGE = 200.dp

/** Vertical drag changes the value, tap opens the fine editor. */
@Composable
fun Dial(
    knob: KnobView,
    onValue: (Int) -> Unit,
    onTap: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 72.dp,
) {
    var local by remember { mutableStateOf<Int?>(null) }
    val current by rememberUpdatedState(knob)
    val send by rememberUpdatedState(onValue)
    val rangePx = with(LocalDensity.current) { DRAG_RANGE.toPx() }
    Column(
        modifier
            .defaultMinSize(minWidth = 56.dp, minHeight = 56.dp)
            .clickable(onClick = onTap)
            .pointerInput(knob.index) {
                var start = 0
                var acc = 0f
                // the last value handed to onValue: a drag back to the shown value must be sent too
                var last = 0
                detectVerticalDragGestures(
                    onDragStart = { start = current.value; acc = 0f; local = start; last = start },
                    onDragEnd = { local = null },
                    onDragCancel = { local = null },
                    onVerticalDrag = { change, dy ->
                        change.consume()
                        acc -= dy
                        val v = (start + acc / rangePx * current.max).roundToInt().coerceIn(0, current.max)
                        local = v
                        if (v != last) {
                            last = v
                            send(v)
                        }
                    },
                )
            },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        val shown = local ?: knob.value
        val frac = if (knob.max > 0) shown.toFloat() / knob.max else 0f
        Box(Modifier.size(size), contentAlignment = Alignment.Center) {
            Canvas(Modifier.size(size)) {
                val w = 5.dp.toPx()
                val track = 3.dp.toPx()
                val inset = w / 2
                val arc = Size(this.size.width - w, this.size.height - w)
                drawArc(
                    B6Colors.SilkscreenDim, 135f, 270f, false, Offset(inset, inset), arc,
                    style = Stroke(track, cap = StrokeCap.Round),
                )
                if (frac > 0f) {
                    drawArc(
                        B6Colors.Amber, 135f, 270f * frac, false, Offset(inset, inset), arc,
                        style = Stroke(w, cap = StrokeCap.Round),
                    )
                }
            }
            Text(
                if (shown != knob.value) shown.toString() else knob.text,
                style = B6Text.Value, fontSize = 22.sp, maxLines = 1, textAlign = TextAlign.Center,
            )
        }
        Text(
            knob.name, style = B6Text.Label, color = B6Colors.SilkscreenDim, fontSize = 15.sp, maxLines = 1,
            overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
        )
    }
}
