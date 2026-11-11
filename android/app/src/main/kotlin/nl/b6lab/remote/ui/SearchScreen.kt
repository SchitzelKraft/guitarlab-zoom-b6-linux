package nl.b6lab.remote.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import nl.b6lab.remote.core.Catalog
import nl.b6lab.remote.core.IndexStatus
import nl.b6lab.remote.core.PatchIndex
import nl.b6lab.remote.core.RemoteController
import nl.b6lab.remote.core.SearchHit
import nl.b6lab.remote.core.bankLetters
import nl.b6lab.remote.core.patchNumber

/**
 * Full screen patch search over the board: number, name or effect name. Tapping a result switches the pedal to that
 * patch and closes the search. Back and the close button leave without a change.
 */
@Composable
fun SearchScreen(
    catalog: Catalog,
    controller: RemoteController,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BackHandler(onBack = onClose)
    val loader = rememberSvgLoader()
    val index by controller.indexed.collectAsStateWithLifecycle()
    var query by rememberSaveable { mutableStateOf("") }
    val status by controller.indexStatus.collectAsStateWithLifecycle()
    val hits = remember(query, index) { controller.search(query) }
    val focus = remember { FocusRequester() }
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(Unit) {
        focus.requestFocus()
        keyboard?.show()
    }
    val pick = { hit: SearchHit ->
        keyboard?.hide()
        focusManager.clearFocus()
        controller.openSlot(hit.slot)
        onClose()
    }
    val searchKey = {
        val top = hits.firstOrNull()
        if (top != null) pick(top) else { keyboard?.hide(); focusManager.clearFocus() }
    }
    val close = {
        keyboard?.hide()
        focusManager.clearFocus()
        onClose()
    }

    Box(modifier.fillMaxSize().background(B6Colors.Gunmetal)) {
        // blocks touches to the board: a sibling behind the content
        Box(Modifier.fillMaxSize().pointerInput(Unit) { detectTapGestures { } })
        Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(horizontal = 12.dp)) {
            Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) {
                    if (query.isEmpty()) {
                        Text("Number, name or effect", style = B6Text.Label, fontSize = 24.sp, color = B6Colors.SilkscreenDim)
                    }
                    BasicTextField(
                        value = query,
                        onValueChange = { query = it },
                        singleLine = true,
                        textStyle = B6Text.Title.copy(fontSize = 24.sp),
                        cursorBrush = SolidColor(B6Colors.Amber),
                        keyboardActions = KeyboardActions(onSearch = { searchKey() }),
                        keyboardOptions = KeyboardOptions(
                            capitalization = KeyboardCapitalization.None, autoCorrectEnabled = false, imeAction = ImeAction.Search,
                        ),
                        modifier = Modifier.fillMaxWidth().focusRequester(focus),
                    )
                }
                Box(
                    Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)).clickable(onClick = close),
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Default.Close, contentDescription = "Close", tint = B6Colors.Silkscreen, modifier = Modifier.size(28.dp)) }
            }
            Box(Modifier.fillMaxWidth().height(2.dp).background(B6Colors.Amber))
            val unknown = index.entries.values.count { it == null }
            val note = when {
                status == IndexStatus.RUNNING -> "Reading patches ${index.indexed}/${PatchIndex.SLOTS}"
                status == IndexStatus.STOPPED || unknown > 0 -> "Some patches could not be read"
                else -> null
            }
            if (note != null) {
                Text(note, style = B6Text.Label, fontSize = 15.sp, color = B6Colors.SilkscreenDim, modifier = Modifier.padding(vertical = 8.dp))
            }
            when {
                query.isBlank() -> Hint("Type a patch number like Z-104, part of a name, or an effect like SVT")
                hits.isEmpty() -> Hint("No patches found")
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(hits, key = { it.slot }) { hit -> ResultRow(hit, index.entries.containsKey(hit.slot), catalog, loader) { pick(hit) } }
                }
            }
        }
    }
}

@Composable
private fun Hint(text: String) {
    Text(text, style = B6Text.Label, fontSize = 18.sp, color = B6Colors.SilkscreenDim, modifier = Modifier.padding(top = 16.dp))
}

@Composable
private fun ResultRow(hit: SearchHit, tried: Boolean, catalog: Catalog, loader: coil.ImageLoader, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(onClick = onClick).padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(Modifier.width(92.dp), verticalAlignment = Alignment.Bottom) {
            Text(bankLetters(hit.slot), style = B6Text.Title, color = B6Colors.Amber, fontSize = 22.sp, maxLines = 1, softWrap = false)
            Text("-" + patchNumber(hit.slot), style = B6Text.Label, color = B6Colors.SilkscreenDim, fontSize = 22.sp, maxLines = 1, softWrap = false)
        }
        Column(Modifier.weight(1f)) {
            if (hit.name.isEmpty()) {
                Text(if (tried) "Could not read" else "Not read yet", style = B6Text.Label, fontSize = 20.sp, color = B6Colors.SilkscreenDim)
            } else {
                Text(hit.name, style = B6Text.Title, fontSize = 24.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (hit.fxIds.isNotEmpty()) {
                Row(Modifier.padding(top = 2.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    hit.fxIds.forEach { id -> EffectPicture(catalog.effects[id], loader, false, Modifier.size(28.dp)) }
                }
            }
            hit.reason?.let {
                Text(it, style = B6Text.Label, fontSize = 14.sp, color = B6Colors.SilkscreenDim, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
