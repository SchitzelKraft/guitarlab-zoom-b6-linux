package nl.b6lab.remote.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import coil.ImageLoader
import coil.compose.AsyncImage
import coil.decode.SvgDecoder
import coil.request.ImageRequest
import nl.b6lab.remote.core.EffectInfo
import nl.b6lab.remote.core.PedalView
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import kotlin.math.floor

@Composable
fun rememberSvgLoader(): ImageLoader {
    val ctx = LocalContext.current
    return remember(ctx) { ImageLoader.Builder(ctx).components { add(SvgDecoder.Factory()) }.build() }
}

private val GREY = ColorFilter.colorMatrix(ColorMatrix().apply { setToSaturation(0f) })

/** The Guitar Lab picture of an effect, or its name on a coloured box when there is no picture. */
@Composable
fun EffectPicture(fx: EffectInfo?, loader: ImageLoader, grey: Boolean, modifier: Modifier = Modifier) {
    if (fx?.svg != null) {
        AsyncImage(
            model = ImageRequest.Builder(LocalContext.current).data("file:///android_asset/${fx.svg}").build(),
            imageLoader = loader,
            contentDescription = fx.name,
            contentScale = ContentScale.Fit,
            colorFilter = if (grey) GREY else null,
            modifier = modifier,
        )
    } else {
        Box(modifier.background(B6Colors.Panel), Alignment.Center) {
            Text(fx?.name ?: "?", style = B6Text.Label, fontSize = 14.sp, textAlign = TextAlign.Center)
        }
    }
}

/**
 * One pedal in a grid of [cols] columns (cells [pitchX] by [pitchY] px apart). Tap selects, the footswitch band at the
 * bottom switches it on or off (and does nothing else), long press asks for the chooser, and dragging the body (after
 * the touch slop) moves it: the cell under the finger on release, in screen order, goes to [onMoveTo].
 * [index] is the position among the shown pedals and [count] their number.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Pedal(
    view: PedalView,
    index: Int,
    count: Int,
    cols: Int,
    pitchX: Float,
    pitchY: Float,
    loader: ImageLoader,
    onTap: () -> Unit,
    onToggle: () -> Unit,
    onLongPress: () -> Unit,
    onMoveTo: (Int) -> Unit,
    modifier: Modifier = Modifier,
    onDragActive: (Boolean) -> Unit = {},
) {
    val moveTo by rememberUpdatedState(onMoveTo)
    var dx by remember { mutableFloatStateOf(0f) }
    var dy by remember { mutableFloatStateOf(0f) }
    val shape = RoundedCornerShape(12.dp)
    val moving = dx != 0f || dy != 0f
    Box(
        modifier
            .zIndex(if (moving) 1f else 0f)
            .graphicsLayer { translationX = dx; translationY = dy }
            .clip(shape)
            .background(B6Colors.Panel)
    ) {
        val rows = (PLACES + cols - 1) / cols
        val moveDrag = Modifier.pointerInput(index, count, cols, pitchX, pitchY) {
            detectDragGestures(
                onDragStart = { onDragActive(true) },
                onDragEnd = {
                    onDragActive(false)
                    val cx = ((index % cols) + 0.5f) * pitchX + dx
                    val cy = ((index / cols) + 0.5f) * pitchY + dy
                    val col = floor(cx / pitchX).toInt().coerceIn(0, cols - 1)
                    val row = floor(cy / pitchY).toInt().coerceIn(0, rows - 1)
                    val target = (row * cols + col).coerceIn(0, count - 1)
                    dx = 0f; dy = 0f
                    if (target != index) moveTo(target)
                },
                onDragCancel = { dx = 0f; dy = 0f; onDragActive(false) },
                onDrag = { change, d -> change.consume(); dx += d.x; dy += d.y },
            )
        }
        // the body (select, long press for the chooser, move) fills the pedal; the footswitch band overlays its bottom
        Box(Modifier.fillMaxSize().then(moveDrag).combinedClickable(onClick = onTap, onLongClick = onLongPress)) {
            Box(Modifier.fillMaxSize().alpha(if (view.on) 1f else 0.3f)) {
                EffectPicture(view.fx, loader, !view.on, Modifier.fillMaxSize().padding(4.dp))
            }
        }
        // footswitch: the 48 dp touch area fades in from transparent so the picture's printed name stays readable
        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(48.dp)
                .background(Brush.verticalGradient(listOf(Color.Transparent, B6Colors.Panel.copy(alpha = 0.9f))))
                .combinedClickable(onClick = onToggle, onLongClick = {}),
        ) {
            Row(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(24.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(if (view.on) B6Colors.LedRed else B6Colors.LedOff))
                Spacer(Modifier.width(6.dp))
                Text(
                    if (view.on) "On" else "Off",
                    style = B6Text.Button, fontSize = 14.sp,
                    color = if (view.on) B6Colors.Silkscreen else B6Colors.SilkscreenDim,
                )
            }
        }
        // the selected pedal: amber outline, 3 dp, drawn inside
        if (view.selected) Box(Modifier.fillMaxSize().drawBehind {
            val w = 3.dp.toPx()
            drawRoundRect(
                B6Colors.Amber,
                topLeft = Offset(w / 2, w / 2),
                size = Size(size.width - w, size.height - w),
                cornerRadius = CornerRadius(12.dp.toPx() - w / 2),
                style = Stroke(w),
            )
        })
    }
}

/** An empty place: with [onClick] a "+" that opens the chooser, otherwise a quiet cell. */
@Composable
fun EmptyPlace(onClick: (() -> Unit)?, modifier: Modifier = Modifier) {
    Box(
        modifier
            .clip(RoundedCornerShape(12.dp))
            .background(B6Colors.Panel.copy(alpha = 0.4f))
            .let { if (onClick != null) it.clickable(onClick = onClick) else it },
        contentAlignment = Alignment.Center,
    ) {
        if (onClick != null) Text("+", style = B6Text.Label, color = B6Colors.SilkscreenDim, fontSize = 36.sp)
    }
}
