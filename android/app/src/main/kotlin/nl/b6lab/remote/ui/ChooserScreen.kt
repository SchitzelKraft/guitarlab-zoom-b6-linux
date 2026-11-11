package nl.b6lab.remote.ui

import android.content.res.Configuration
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import nl.b6lab.remote.core.BoardUi
import nl.b6lab.remote.core.Catalog
import nl.b6lab.remote.core.PatchRef
import nl.b6lab.remote.core.RemoteController

/** "BASS AMP" becomes "Bass amp". */
private fun sentenceCase(group: String): String =
    group.lowercase().replaceFirstChar { it.uppercase() }

/**
 * Full screen effect chooser over the board. [replaceSlot] null adds the effect at the end of the chain, otherwise
 * it changes the type of that entry and a "Remove" button is offered. Effects that do not fit are greyed and
 * not tappable. Back and the close button leave without a change.
 */
@Composable
fun ChooserScreen(
    ui: BoardUi,
    catalog: Catalog,
    controller: RemoteController,
    replaceSlot: Int?,
    expected: PatchRef,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BackHandler(onBack = onClose)
    val landscape = LocalConfiguration.current.orientation == Configuration.ORIENTATION_LANDSCAPE
    val loader = rememberSvgLoader()
    val groups = remember(catalog) { catalog.byGroup() }
    val currentFx = replaceSlot?.let { slot -> ui.pedals.firstOrNull { it.slot == slot }?.fx }
    // opens on the group of the effect being changed, else the first group
    var tab by rememberSaveable { mutableIntStateOf(groups.indexOfFirst { it.first == currentFx?.group }.coerceAtLeast(0)) }
    val tabIndex = tab.coerceIn(0, (groups.size - 1).coerceAtLeast(0))
    val current = groups.getOrNull(tabIndex)?.second.orEmpty()
    // ui is read so that the greying follows a patch change while the chooser is open
    val fitting = remember(ui, current, replaceSlot) { current.map { controller.fits(it.fxId, replaceSlot) } }
    val title = if (replaceSlot == null) "Add effect" else "Change ${currentFx?.name ?: "effect"}"
    val removeLabel = "Remove ${currentFx?.name ?: "effect"}"
    val remove = { controller.remove(replaceSlot!!, expected); onClose() }

    Box(
        modifier
            .fillMaxSize()
            .background(B6Colors.Gunmetal)
            // consume touches on empty areas so nothing behind (the board) receives them
            .pointerInput(Unit) { awaitPointerEventScope { while (true) awaitPointerEvent().changes.forEach { it.consume() } } }
            .safeDrawingPadding()
            .padding(horizontal = 12.dp),
    ) {
        if (landscape) {
            Row(Modifier.fillMaxSize()) {
                Column(Modifier.width(120.dp).fillMaxHeight().verticalScroll(rememberScrollState())) {
                    groups.forEachIndexed { i, (name, _) -> GroupTab(sentenceCase(name), i == tabIndex, true) { tab = i } }
                }
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
                        CloseButton(onClose)
                        Text(title, style = B6Text.Title, fontSize = 24.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                        if (replaceSlot != null) RemoveButton(removeLabel, remove)
                    }
                    EffectGrid(GridCells.Adaptive(96.dp), 88, current, fitting, currentFx?.fxId, loader) { fx ->
                        controller.choose(fx.fxId, replaceSlot, expected); onClose()
                    }
                }
            }
        } else {
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(title, style = B6Text.Title, fontSize = 28.sp, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    CloseButton(onClose)
                }
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                    groups.forEachIndexed { i, (name, _) -> GroupTab(sentenceCase(name), i == tabIndex, false) { tab = i } }
                }
                Box(Modifier.weight(1f)) {
                    EffectGrid(GridCells.Fixed(3), 96, current, fitting, currentFx?.fxId, loader) { fx ->
                        controller.choose(fx.fxId, replaceSlot, expected); onClose()
                    }
                }
                if (replaceSlot != null) Row(Modifier.fillMaxWidth()) { RemoveButton(removeLabel, remove) }
            }
        }
    }
}

@Composable
private fun CloseButton(onClose: () -> Unit) {
    Box(
        Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClose),
        contentAlignment = Alignment.Center,
    ) { Icon(Icons.Default.Close, contentDescription = "Close", tint = B6Colors.Silkscreen, modifier = Modifier.size(28.dp)) }
}

/** Destructive but quiet: red text, no fill. */
@Composable
private fun RemoveButton(label: String, onClick: () -> Unit) {
    Box(
        Modifier.height(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(horizontal = 12.dp),
        contentAlignment = Alignment.Center,
    ) { Text(label, style = B6Text.Button, color = B6Colors.LedRed, fontSize = 17.sp, maxLines = 1) }
}

/** A group tab: amber indicator (a bar on the left in the vertical rail, an underline in the row). */
@Composable
private fun GroupTab(label: String, selected: Boolean, vertical: Boolean, onClick: () -> Unit) {
    val text: @Composable () -> Unit = {
        Text(
            label, style = B6Text.Button, fontSize = 17.sp, maxLines = 1,
            color = if (selected) B6Colors.Silkscreen else B6Colors.SilkscreenDim,
        )
    }
    if (vertical) {
        Row(Modifier.fillMaxWidth().height(48.dp).clickable(onClick = onClick), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(3.dp).height(24.dp).background(if (selected) B6Colors.Amber else androidx.compose.ui.graphics.Color.Transparent))
            Spacer(Modifier.width(10.dp))
            text()
        }
    } else {
        Column(Modifier.height(56.dp).clickable(onClick = onClick).padding(horizontal = 14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) { text() }
            Box(Modifier.height(3.dp).fillMaxWidth().background(if (selected) B6Colors.Amber else androidx.compose.ui.graphics.Color.Transparent))
        }
    }
}

@Composable
private fun EffectGrid(
    cells: GridCells,
    pictureHeight: Int,
    effects: List<nl.b6lab.remote.core.EffectInfo>,
    fitting: List<Boolean>,
    currentFxId: Int?,
    loader: coil.ImageLoader,
    onPick: (nl.b6lab.remote.core.EffectInfo) -> Unit,
) {
    LazyVerticalGrid(
        columns = cells,
        modifier = Modifier.fillMaxSize().padding(top = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items(effects.size, key = { effects[it].fxId }) { i ->
            val fx = effects[i]
            val ok = fitting.getOrElse(i) { false }
            val shape = RoundedCornerShape(10.dp)
            Column(
                Modifier
                    .alpha(if (ok) 1f else 0.3f)
                    .clip(shape)
                    .let { if (fx.fxId == currentFxId) it.background(B6Colors.Panel).border(2.dp, B6Colors.Amber, shape) else it }
                    .let { if (ok) it.clickable { onPick(fx) } else it }
                    .padding(6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                EffectPicture(fx, loader, !ok, Modifier.fillMaxWidth().height(pictureHeight.dp))
                Text(
                    fx.name, style = B6Text.Label, fontSize = 14.sp, maxLines = 1,
                    overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
                )
            }
        }
    }
}
