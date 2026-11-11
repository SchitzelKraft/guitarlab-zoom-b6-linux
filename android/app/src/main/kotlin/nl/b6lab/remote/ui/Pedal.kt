package nl.b6lab.remote.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
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
import kotlin.math.roundToInt

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
        Box(modifier.background(B6Colors.SurfaceHigh), Alignment.Center) {
            Text(fx?.name ?: "?", color = B6Colors.Text, fontSize = 14.sp, textAlign = TextAlign.Center)
        }
    }
}

/**
 * One pedal. Tap selects or toggles, long press asks for the chooser. Moving uses the grip strip on top (a
 * horizontal drag there): the rest of the pedal stays free so a scrolling row can still be scrolled by it.
 * [pitchPx] is the distance between two neighbouring pedals, [index] the position in the row and [count] the row length.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun Pedal(
    view: PedalView,
    index: Int,
    count: Int,
    pitchPx: Float,
    loader: ImageLoader,
    onTap: () -> Unit,
    onLongPress: () -> Unit,
    onMoveTo: (Int) -> Unit,
    wholeDrag: Boolean,
    modifier: Modifier = Modifier,
) {
    val moveTo by rememberUpdatedState(onMoveTo)
    var dx by remember { mutableFloatStateOf(0f) }
    val shape = RoundedCornerShape(12.dp)
    val border = if (view.selected) BorderStroke(3.dp, B6Colors.Accent) else BorderStroke(1.dp, B6Colors.SurfaceHigh)
    Box(
        modifier
            .zIndex(if (dx != 0f) 1f else 0f)
            .graphicsLayer { translationX = dx }
            .clip(shape)
            .background(B6Colors.Surface)
            .then(if (wholeDrag) Modifier.pointerInput(index, count, pitchPx) {
                detectHorizontalDragGestures(
                    onDragEnd = {
                        val target = (index + dx / pitchPx).roundToInt().coerceIn(0, count - 1)
                        dx = 0f
                        if (target != index) moveTo(target)
                    },
                    onDragCancel = { dx = 0f },
                    onHorizontalDrag = { change, d -> change.consume(); dx += d },
                )
            } else Modifier)
            .combinedClickable(onClick = onTap, onLongClick = onLongPress),
    ) {
        val fx = view.fx
        Box(Modifier.fillMaxSize().alpha(if (view.on) 1f else 0.35f)) {
            EffectPicture(fx, loader, !view.on, Modifier.fillMaxSize().padding(top = 28.dp, bottom = 6.dp, start = 4.dp, end = 4.dp))
        }
        // portrait: grip strip (56 dp touch area) moves the pedal; landscape: the whole pedal does
        if (!wholeDrag) Box(
            Modifier
                .fillMaxWidth()
                .height(56.dp)
                .pointerInput(index, count, pitchPx) {
                    detectHorizontalDragGestures(
                        onDragEnd = {
                            val target = (index + dx / pitchPx).roundToInt().coerceIn(0, count - 1)
                            dx = 0f
                            if (target != index) moveTo(target)
                        },
                        onDragCancel = { dx = 0f },
                        onHorizontalDrag = { change, d -> change.consume(); dx += d },
                    )
                },
            contentAlignment = Alignment.TopCenter,
        ) {
            Box(Modifier.padding(top = 12.dp).size(width = 28.dp, height = 4.dp).clip(CircleShape).background(B6Colors.TextDim))
        }
        Box(
            Modifier
                .align(Alignment.TopEnd)
                .padding(6.dp)
                .size(10.dp)
                .clip(CircleShape)
                .background(if (view.on) B6Colors.Led else Color(0xFF3A1A1A)),
        )
        Box(Modifier.fillMaxSize().drawBehind {
            val w = border.width.toPx()
            drawRoundRect(
                if (view.selected) B6Colors.Accent else B6Colors.SurfaceHigh,
                topLeft = androidx.compose.ui.geometry.Offset(w / 2, w / 2),
                size = androidx.compose.ui.geometry.Size(size.width - w, size.height - w),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(12.dp.toPx() - w / 2),
                style = androidx.compose.ui.graphics.drawscope.Stroke(w),
            )
        })
    }
}

/** An empty place: "+" opens the chooser. */
@Composable
fun EmptyPlace(onClick: () -> Unit, modifier: Modifier = Modifier) {
    Box(
        modifier
            .clip(RoundedCornerShape(12.dp))
            .background(B6Colors.Surface.copy(alpha = 0.5f))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text("+", color = B6Colors.TextDim, fontSize = 32.sp)
    }
}
