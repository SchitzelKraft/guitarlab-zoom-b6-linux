package nl.b6lab.remote.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import nl.b6lab.remote.core.BoardUi
import nl.b6lab.remote.core.Catalog
import nl.b6lab.remote.core.RemoteController

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
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BackHandler(onBack = onClose)
    val loader = rememberSvgLoader()
    val groups = remember(catalog) { catalog.byGroup() }
    var tab by remember { mutableIntStateOf(0) }
    val current = groups.getOrNull(tab)?.second.orEmpty()
    // ui is read so that the greying follows a patch change while the chooser is open
    val fitting = remember(ui, current, replaceSlot) { current.map { controller.fits(it.fxId, replaceSlot) } }

    Column(
        modifier
            .fillMaxSize()
            .background(B6Colors.Background)
            .safeDrawingPadding()
            .padding(horizontal = 12.dp),
    ) {
        Row(Modifier.fillMaxWidth().height(64.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (replaceSlot == null) "Add effect" else "Change effect",
                color = B6Colors.Text, fontSize = 22.sp, modifier = Modifier.weight(1f),
            )
            if (replaceSlot != null) {
                Button(
                    onClick = { controller.remove(replaceSlot); onClose() },
                    modifier = Modifier.height(56.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = B6Colors.Error),
                ) { Text("Remove", fontSize = 16.sp) }
                Box(Modifier.size(8.dp))
            }
            Box(
                Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = onClose),
                contentAlignment = Alignment.Center,
            ) { Text("X", color = B6Colors.Text, fontSize = 22.sp) }
        }
        ScrollableTabRow(
            selectedTabIndex = tab.coerceAtMost((groups.size - 1).coerceAtLeast(0)),
            containerColor = B6Colors.Background,
            contentColor = B6Colors.Accent,
            edgePadding = 0.dp,
        ) {
            groups.forEachIndexed { i, (name, _) ->
                Tab(
                    selected = i == tab,
                    onClick = { tab = i },
                    modifier = Modifier.heightIn(min = 56.dp),
                    text = { Text(name, fontSize = 15.sp, color = if (i == tab) B6Colors.Text else B6Colors.TextDim) },
                )
            }
        }
        LazyVerticalGrid(
            columns = GridCells.Adaptive(104.dp),
            modifier = Modifier.fillMaxSize().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(current.size, key = { current[it].fxId }) { i ->
                val fx = current[i]
                val ok = fitting[i]
                Column(
                    Modifier
                        .alpha(if (ok) 1f else 0.3f)
                        .clip(RoundedCornerShape(12.dp))
                        .background(B6Colors.Surface)
                        .let { if (ok) it.clickable { controller.choose(fx.fxId, replaceSlot); onClose() } else it }
                        .padding(6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    EffectPicture(fx, loader, false, Modifier.fillMaxWidth().height(96.dp))
                    Text(
                        fx.name, color = B6Colors.Text, fontSize = 13.sp, maxLines = 2,
                        overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
                        modifier = Modifier.heightIn(min = 36.dp),
                    )
                }
            }
        }
    }
}
