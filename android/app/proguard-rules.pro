# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class nl.b6lab.remote.** {
    *** Companion;
}
-keepclasseswithmembers class nl.b6lab.remote.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class nl.b6lab.remote.**$$serializer { *; }
-keepclassmembers class nl.b6lab.remote.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
# Coil SVG (keep to be safe)
-keep class coil.svg.** { *; }
-keep class com.caverock.androidsvg.** { *; }
-dontwarn com.caverock.androidsvg.**
