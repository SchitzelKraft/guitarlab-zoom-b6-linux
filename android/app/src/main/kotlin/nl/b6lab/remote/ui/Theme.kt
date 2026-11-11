package nl.b6lab.remote.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object B6Colors {
    val Background = Color(0xFF101216)
    val Surface = Color(0xFF1B1E25)
    val SurfaceHigh = Color(0xFF262A33)
    val Text = Color(0xFFE8EAEE)
    val TextDim = Color(0xFF8C93A1)
    val Accent = Color(0xFF3D8BFF)
    val Led = Color(0xFFFF3B30)
    val Ok = Color(0xFF34C759)
    val Warn = Color(0xFFE0A030)
    val Error = Color(0xFFE5484D)
}

@Composable
fun B6Theme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            background = B6Colors.Background,
            surface = B6Colors.Surface,
            primary = B6Colors.Accent,
            onBackground = B6Colors.Text,
            onSurface = B6Colors.Text,
        ),
        content = content,
    )
}
