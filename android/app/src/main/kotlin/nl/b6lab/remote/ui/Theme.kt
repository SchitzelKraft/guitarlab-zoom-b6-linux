package nl.b6lab.remote.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import nl.b6lab.remote.R

/** The stage look: gunmetal and panel greys, silkscreen text, one amber accent, a red LED. */
object B6Colors {
    val Gunmetal = Color(0xFF1D2026)
    val Panel = Color(0xFF2A2E36)
    val Silkscreen = Color(0xFFE8E3D6)
    val SilkscreenDim = Silkscreen.copy(alpha = 0.55f)
    val Amber = Color(0xFFF2B33D)
    val LedRed = Color(0xFFF0412E)
    val LedOff = Color(0xFF4A2420)
}

/** Barlow Condensed (SIL OFL, see res/raw/barlow_condensed_ofl.txt). */
object B6Fonts {
    val Regular = FontFamily(Font(R.font.barlow_condensed_regular, FontWeight.Normal))
    val Medium = FontFamily(Font(R.font.barlow_condensed_medium, FontWeight.Medium))
    val SemiBold = FontFamily(Font(R.font.barlow_condensed_semibold, FontWeight.SemiBold))
}

/** Text styles of the app; sizes are set where they are used. */
object B6Text {
    val Label = TextStyle(fontFamily = B6Fonts.Regular, fontWeight = FontWeight.Normal, color = B6Colors.Silkscreen)
    val Button = TextStyle(fontFamily = B6Fonts.Medium, fontWeight = FontWeight.Medium, color = B6Colors.Silkscreen)
    val Title = TextStyle(fontFamily = B6Fonts.SemiBold, fontWeight = FontWeight.SemiBold, color = B6Colors.Silkscreen)
    val Value = Button.copy(fontFeatureSettings = "tnum")
}

@Composable
fun B6Theme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            background = B6Colors.Gunmetal,
            surface = B6Colors.Panel,
            primary = B6Colors.Amber,
            onPrimary = B6Colors.Gunmetal,
            onBackground = B6Colors.Silkscreen,
            onSurface = B6Colors.Silkscreen,
            surfaceContainerLow = B6Colors.Panel,
            surfaceContainerHigh = B6Colors.Panel,
        ),
        typography = Typography().let { t ->
            t.copy(
                bodyLarge = t.bodyLarge.copy(fontFamily = B6Fonts.Regular),
                bodyMedium = t.bodyMedium.copy(fontFamily = B6Fonts.Regular),
                labelLarge = t.labelLarge.copy(fontFamily = B6Fonts.Medium),
            )
        },
        content = content,
    )
}
