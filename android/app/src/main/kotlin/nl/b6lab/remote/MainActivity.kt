package nl.b6lab.remote

import android.content.pm.ApplicationInfo
import android.content.res.Configuration
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import nl.b6lab.remote.core.Catalog
import nl.b6lab.remote.core.Connection
import nl.b6lab.remote.core.PatchRef
import nl.b6lab.remote.ui.B6Theme
import nl.b6lab.remote.ui.BoardScreen
import nl.b6lab.remote.ui.ChooserScreen

private class ChooserTarget(val ref: PatchRef, val replaceSlot: Int) {
    companion object {
        val Saver = androidx.compose.runtime.saveable.Saver<ChooserTarget?, List<Int>>(
            save = { t -> t?.let { listOf(it.replaceSlot, it.ref.slot) + it.ref.fxIds } ?: emptyList() },
            restore = { l -> if (l.isEmpty()) null else ChooserTarget(PatchRef(l[1], l.drop(2)), l[0]) },
        )
    }
}

/** Shows the board while a session exists, otherwise a status screen. */
class MainActivity : ComponentActivity() {
    private lateinit var pedal: PedalConnection

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        applyBars(resources.configuration)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val catalog = Catalog.load(assets.open("generated/catalog.json").use { it.readBytes().decodeToString() })
        pedal = PedalConnection(this, catalog)
        val debuggable = applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        val demo = if (debuggable) loadDemoPatches() else null
        setContent {
            val state by pedal.state.collectAsStateWithLifecycle()
            val isDemo by pedal.isDemo.collectAsStateWithLifecycle()
            val controller by pedal.controller.collectAsStateWithLifecycle()
            val color = MaterialTheme.colorScheme.onBackground
            B6Theme {
                val c = controller
                if (c != null) {
                    val ui by c.ui.collectAsStateWithLifecycle()
                    // null = closed; else the patch it was opened on (slot and chain) and the entry to change
                    // (-1 = add at the end)
                    var chooser by rememberSaveable(stateSaver = ChooserTarget.Saver) { mutableStateOf<ChooserTarget?>(null) }
                    BoardScreen(
                        ui, c,
                        onAddEffect = { c.currentRef()?.let { chooser = ChooserTarget(it, -1) } },
                        onLongPressPedal = { slot -> c.currentRef()?.let { chooser = ChooserTarget(it, slot) } },
                    )
                    chooser?.let { t ->
                        val now = c.currentRef()
                        if (now == null || now.slot != t.ref.slot) {
                            // another patch: the chooser's choices would hit the wrong one
                            chooser = null
                        } else {
                            ChooserScreen(
                                ui, catalog, c, t.replaceSlot.takeIf { it >= 0 }, t.ref,
                                onClose = { chooser = null },
                            )
                        }
                    }
                    return@B6Theme
                }
                Column(
                    Modifier
                        .fillMaxSize()
                        .background(MaterialTheme.colorScheme.background)
                        .safeDrawingPadding()
                        .padding(16.dp)
                ) {
                    val s = state
                    Text("B6 Remote" + if (isDemo) " (demo)" else "", color = color)
                    val connection = s?.connection ?: Connection.DISCONNECTED
                    Text(
                        when (connection) {
                            Connection.CONNECTED -> "Connected"
                            Connection.CONNECTING -> "Connecting..."
                            Connection.DISCONNECTED -> "B6 not connected"
                        },
                        color = color,
                    )
                    if (s != null) {
                        Text("Slot: ${s.slot ?: "-"}", color = color)
                        Text("Patch: ${s.edit?.name ?: "-"}", color = color)
                        Text("PC mode: ${s.pcMode}", color = color)
                        Text("Auto save: ${s.autoSave}", color = color)
                        s.error?.let { Text("Error: $it", color = color) }
                    }
                    if (connection == Connection.DISCONNECTED && !isDemo && demo != null) {
                        Button(onClick = { pedal.startDemo(demo) }) { Text("Demo") }
                    }
                }
            }
        }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        applyBars(newConfig)
    }

    /** Landscape: system bars hidden (a swipe from the edge shows them for a moment); portrait: shown. */
    private fun applyBars(config: Configuration) {
        val c = WindowInsetsControllerCompat(window, window.decorView)
        if (config.orientation == Configuration.ORIENTATION_LANDSCAPE) {
            c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            c.hide(WindowInsetsCompat.Type.systemBars())
        } else {
            c.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun onStart() {
        super.onStart()
        pedal.start()
    }

    override fun onStop() {
        pedal.stop()
        super.onStop()
    }

    override fun onDestroy() {
        pedal.destroy()
        super.onDestroy()
    }

    /** Backup slots 1, 3 and 101 as 808-byte images; null when the generated assets are absent. */
    private fun loadDemoPatches(): List<ByteArray>? = runCatching {
        listOf(0, 2, 100).map { assets.open("generated/demo/$it.bin").use { s -> s.readBytes() } }
    }.getOrNull()
}
