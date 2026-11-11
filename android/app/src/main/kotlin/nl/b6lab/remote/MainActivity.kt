package nl.b6lab.remote

import android.content.pm.ApplicationInfo
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
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import nl.b6lab.remote.core.Connection

/** Minimal status screen until the board screen (Task 10) replaces it. */
class MainActivity : ComponentActivity() {
    private lateinit var pedal: PedalConnection

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        pedal = PedalConnection(this)
        val debuggable = applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
        val demo = if (debuggable) loadDemoPatches() else null
        setContent {
            val state by pedal.state.collectAsStateWithLifecycle()
            val isDemo by pedal.isDemo.collectAsStateWithLifecycle()
            val color = MaterialTheme.colorScheme.onBackground
            MaterialTheme(colorScheme = darkColorScheme()) {
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
