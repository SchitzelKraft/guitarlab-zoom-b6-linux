# B6 Remote for Android Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Android app that edits the active patch of a Zoom B6 over USB: pedal board with Guitar Lab pictures, live on/off and knobs, add/change/remove/move effects, Save, following the pedal in PC mode.

**Architecture:** A pure-Kotlin `:core` module (no Android) holds everything testable: SysEx codec, PTCF patch format, effect catalogue, message builders, a byte-level fake pedal, the session (PC mode, pushes, live edits, save) and the screen controller. It is a port of `b6lab/` and is checked byte-for-byte against B6 Lab with fixtures that a Python script generates from the user's real data. The `:app` module adds only the USB MIDI transport and the Compose UI.

**Tech Stack:** Kotlin 2.0.21, AGP 8.7.3, Gradle 8.9 (wrapper), JDK 21 for the build, Jetpack Compose (BOM 2024.10.01), kotlinx-coroutines 1.9.0, kotlinx-serialization-json 1.7.3, Coil 2.7.0 (coil-compose + coil-svg), JUnit 4.13.2. Python 3 + the repo's `.venv` for the asset/fixture generator.

**Spec:** `docs/superpowers/specs/2026-11-11-b6-android-remote-design.md`

## Global Constraints

- Android: minSdk 29, compileSdk 35, targetSdk 35; app id `nl.b6lab.remote`; debug build only, installed with `~/Android/Sdk/platform-tools/adb`.
- Build with `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64`; `android/local.properties` holds `sdk.dir=/home/emmanuel/Android/Sdk` (git-ignored).
- Zoom files are never committed: generated assets (`android/app/src/main/assets/generated/`) and fixtures (`android/core/src/test/resources/fixtures/`) are git-ignored and produced by `tools/android_prepare.py`.
- Edge-to-edge (targetSdk 35): every screen pads for system-bar and cutout insets.
- Safety (spec, hard): never send `01`-`0A`, `64 2D`, `64 3F`, `60 xx` (any); never send direct on/off `64 20 00 <slot> 00 <v>` (on/off only via the `5A` press/release); always ack an edit dump `64 12` with `52 00 6E 00 00`. Enforced in one place (`Safety.check`) that every send passes through.
- A pedal message B6 Lab does not already send is never sent without asking the user first.
- Max 6 chain entries (`MAX_ENTRIES = 6`); DSP budget 220 (sum of `dspLoad` of non-tail entries; IR = 86.45).
- No em-dash character in any text, comment, string or commit message.
- Commit at every "Commit" step without asking (the user allowed this for this plan on 2026-11-11), on branch `feature/android-remote`. Commit messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. The pedal changes patch (footswitch) while a phone edit is in flight: the edit must not land on the new patch. Every chain edit checks the edit buffer's effect IDs against what the screen shows, as `b6lab/live.py` does (test in Task 7).
2. USB unplugged mid-operation or pedal switched off: banner "B6 not connected", no crash, no stale "connected" state; reconnect by itself on replug (tests in Task 7 and Task 8 checklist).
3. Fast dial dragging floods the pedal: sends are throttled to at most one knob message pair per 30 ms per knob, and the last value is always sent (test in Task 9).
4. A full chain (6 entries, or no DSP room): "+" places are hidden, and the chooser greys out effects that do not fit; a refused insert does not desync the screen (tests in Tasks 4 and 9).
5. Double-width effects: the tail entry is not a separate pedal, positions count tails (entry index), and its knobs are not editable (tests in Tasks 3 and 9).

---

## File structure

```
android/
  settings.gradle.kts, build.gradle.kts, gradle.properties, gradle/libs.versions.toml, gradlew(+wrapper)
  prepare.sh                         runs tools/android_prepare.py (assets + fixtures)
  core/build.gradle.kts              kotlin("jvm") + serialization
  core/src/main/kotlin/nl/b6lab/remote/core/
    Codec.kt         pack7/unpack7/to7/from7/crc, SysexAssembler
    Ptcf.kt          Patch/Effect model, parse/encode, chain edits
    Catalog.kt       EffectInfo/ParamInfo from catalog.json, formatValue, budget
    Messages.kt      request builders, reply parsers, push parsing, Safety
    Transport.kt     MidiTransport interface, MidiMessage
    FakePedal.kt     byte-level fake B6 (tests + demo mode)
    Session.kt       B6Session: connect, PC mode, pushes, live edits, save, state
    Controller.kt    RemoteController: screen state and user actions
  core/src/test/kotlin/nl/b6lab/remote/core/*Test.kt
  app/build.gradle.kts
  app/src/main/AndroidManifest.xml
  app/src/main/kotlin/nl/b6lab/remote/
    MainActivity.kt  lifecycle, keep-screen-on, insets
    UsbMidiTransport.kt
    ui/BoardScreen.kt, ui/Pedal.kt, ui/Dial.kt, ui/ChooserScreen.kt, ui/Theme.kt
tools/android_prepare.py             generates assets + fixtures from b6lab and local data
```

---

### Task 1: Project skeleton and build pipeline

**Files:**
- Create: everything under `android/` listed above except the Kotlin sources (only a placeholder `Codec.kt` with `object Codec`), `android/prepare.sh`
- Modify: `.gitignore` (add `android/local.properties`, `android/**/build/`, `android/.gradle/`, `android/app/src/main/assets/generated/`, `android/core/src/test/resources/fixtures/`)
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/SmokeTest.kt`

**Interfaces:**
- Produces: modules `:core` (JVM) and `:app` (Android, depends on `:core`); `./gradlew :core:test` and `./gradlew :app:assembleDebug` work.

- [ ] **Step 1:** Generate the wrapper with `~/tools/gradle-8.9/bin/gradle wrapper --gradle-version 8.9` inside `android/`; write the version catalog with the exact versions from Tech Stack (Compose compiler plugin `org.jetbrains.kotlin.plugin.compose` 2.0.21; serialization plugin 2.0.21).
- [ ] **Step 2:** Write `SmokeTest.smoke()` asserting `Codec::class.simpleName == "Codec"`.
- [ ] **Step 3:** Run `cd android && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ./gradlew :core:test :app:assembleDebug`. Expected: BUILD SUCCESSFUL, `app/build/outputs/apk/debug/app-debug.apk` exists. The app shows an empty dark screen with title "B6 Remote" padded below the status bar (install with adb, check on the phone).
- [ ] **Step 4:** `git status` shows no file under the ignored paths. Commit: `android: project skeleton`.

### Task 2: Codec, SysEx assembly and the fixture generator

**Files:**
- Create: `tools/android_prepare.py`, `android/core/src/main/kotlin/nl/b6lab/remote/core/Codec.kt`, `.../Transport.kt` (`MidiMessage` only)
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/CodecTest.kt`

**Interfaces:**
- Produces (Kotlin): `object Codec { fun pack7(data: ByteArray): ByteArray; fun unpack7(d: ByteArray): ByteArray; fun to7(value: Long, n: Int): ByteArray; fun from7(d: ByteArray, off: Int = 0, n: Int = d.size - off): Long; fun crcTail(data: ByteArray): ByteArray; fun packedLen(size: Int): Int; fun decodeBlock(m: ByteArray, off: Int): ByteArray /* size:2 + packed + crc:5; throws IllegalArgumentException("checksum mismatch") */ }`
- Produces: `class SysexAssembler(val onMessage: (MidiMessage) -> Unit) { fun feed(bytes: ByteArray, offset: Int, count: Int) }`; `sealed class MidiMessage { data class Sysex(val body: ByteArray) /* without F0/F7 */; data class Channel(val bytes: ByteArray) }` (put `MidiMessage` in `Transport.kt`).
- Produces (Python): `tools/android_prepare.py [--assets] [--fixtures]`, default both, writing JSON with hex strings. Fixture `codec.json`: `[{data, packed, crc_tail}]` for 20 random lengths 0..820 (seeded) plus every 10th backup patch; `replies.json`: raw `.syx` bodies of 10 backup slots with their decoded data (from `backup/b6-20261106-2339/syx/`).

- [ ] **Step 1:** Write `android_prepare.py --fixtures` for `codec.json` and `replies.json` using `b6lab.codec` and `b6lab.midi.B6._decode`; run `.venv/bin/python tools/android_prepare.py --fixtures`; expect both files in `android/core/src/test/resources/fixtures/`.
- [ ] **Step 2:** Write tests: `packMatchesPython` (every vector: `pack7(data) == packed`, `unpack7(packed).copyOf(size) == data`, `crcTail(data) == crc_tail`); `decodesRealReplies` (`decodeBlock(body, 10) == data` for each reply); `corruptedReplyThrows` (flip one packed byte); `assemblerJoinsChunks` (a 941-byte reply split into 82 chunks of varying size, with `F8` realtime bytes inserted, yields exactly one `Sysex` equal to the body); `assemblerSplitsChannelMessages` (`B0 00 00 B0 20 3B C0 03` yields three `Channel` messages of 3, 3, 2 bytes).
- [ ] **Step 3:** Run `./gradlew :core:test --tests '*CodecTest*'`; expect FAIL (not implemented).
- [ ] **Step 4:** Implement `Codec` and `SysexAssembler` (same rules as `B6._pump` in `b6lab/midi.py:98`).
- [ ] **Step 5:** Run again; expect PASS. Commit: `android: codec and SysEx assembly`.

### Task 3: PTCF patch model and chain edits

**Files:**
- Create: `android/core/src/main/kotlin/nl/b6lab/remote/core/Ptcf.kt`
- Modify: `tools/android_prepare.py` (fixture `ptcf.json`)
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/PtcfTest.kt`

**Interfaces:**
- Produces: `data class Effect(val slot: Int, val fxId: Int, val on: Boolean, val params: List<Int>, val isTail: Boolean, val raw: java.math.BigInteger) { fun editable(index: Int): Boolean; fun maxValue(index: Int): Int; val categoryByte: Int }`
- Produces: `class Patch(val name: String, val effects: List<Effect>, val raw: ByteArray, ...)` plus `object Ptcf { const val MAX_ENTRIES = 6; fun parse(data: ByteArray): Patch; fun encode(p: Patch): ByteArray; fun setParam(p, slot, index, value): Patch; fun setOn(p, slot, on): Patch; fun setType(p, slot, fxId): Patch; fun insertEntry(p, pos): Patch?; fun deleteEntry(p, pos): Patch?; fun moveEntry(p, src, dst): Patch?; fun position(p: Patch, slot: Int): Int /* = live.effect_position, throws for tails */; fun samePatch(a: ByteArray, b: ByteArray): Boolean /* = device._same_patch */ }`. Functions return new patches (immutable), `null` where Python returns False.
- Fixture `ptcf.json`: for every backup patch: Python `parse` result (name, slots, per effect slot/fx_id/on/params/is_tail), `encode(parse(x))` hex, and for patch slots 1, 3, 101: results of `set_param(0,0,37)`, `set_on(0,False)`, `set_type(0, 0x07090010)`, `insert_entry(1)`, `delete_entry(0)`, `move_entry(0,1)` (each encoded, or null).

- [ ] **Step 1:** Extend the generator (port semantics from `b6lab/ptcf.py`, field widths `PARAM_WIDTHS = [12]*5 + [8]*n`, `ENTRY = 24`, `PARAM_START`); regenerate fixtures.
- [ ] **Step 2:** Write tests: `parsesEveryBackupPatchLikePython`, `encodeRoundTripsLikePython`, `chainEditsMatchPython` (each op, each sample), `positionCountsTails` (SVT Drive slot 1: tails `[F,T,F,T,F]`, positions of slots 0,2,4 = 0,2,4, slot 3 throws), `tailKnobsNotEditable`, `insertRefusedAtSixEntries`.
- [ ] **Step 3:** Run, expect FAIL; implement `Ptcf.kt`; run, expect PASS.
- [ ] **Step 4:** Commit: `android: PTCF patch model`.

### Task 4: Effect catalogue and pictures

**Files:**
- Create: `android/core/src/main/kotlin/nl/b6lab/remote/core/Catalog.kt`
- Modify: `tools/android_prepare.py` (`--assets`: `generated/catalog.json` + `generated/svg/<module>.svg`; fixture `format.json`)
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/CatalogTest.kt`

**Interfaces:**
- Produces: `data class ParamInfo(val name: String, val rawMax: Int?, val displayMin: String?, val displayStep: String?, val precision: Int, val labels: List<String>?) { fun format(value: Int): String }`; `data class EffectInfo(val fxId: Int, val name: String, val group: String, val params: List<ParamInfo>, val svg: String? /* asset path or null */, val dspLoad: Double)`; `class Catalog(val effects: Map<Int, EffectInfo>) { companion object { fun load(json: String): Catalog }; fun byGroup(): List<Pair<String, List<EffectInfo>>> /* Guitar Lab group order as in ptcf.CATEGORIES */; fun fits(p: Patch, fxId: Int, replaceSlot: Int? = null): Boolean /* entries after the change <= 6 and total load <= 220.0; whether a new effect is double width is not in the catalogue: the pedal decides and the session re-reads the edit buffer */ }`
- `catalog.json` is produced from `b6lab.effects.load()` (it merges `parameter-ranges.json`), `effects.dsp_load`, the SVG module name as `b6lab/gui/editor.py:_module` resolves it (`_IR` for IR categories `0x1A`,`0x1B`).

- [ ] **Step 1:** Extend the generator; run `tools/android_prepare.py`; expect `catalog.json` with an entry for `0x05890011` named "AMPG SVT" with 7 params, and `svg/SVT_88.svg`.
- [ ] **Step 2:** Write tests: `formatMatchesPython` (fixture `format.json`: 200 `(fx_id, index, value, text)` triples from `ParamInfo.format_value`), `groupsInGuitarLabOrder`, `budgetRejectsOverload` (a chain whose loads sum above 220 rejects one more effect; IR load 86.45), `sixEntriesRejectAdd`.
- [ ] **Step 3:** Run, FAIL; implement; run, PASS. Commit: `android: effect catalogue`.

### Task 5: Messages and safety guard

**Files:**
- Create: `android/core/src/main/kotlin/nl/b6lab/remote/core/Messages.kt`
- Modify: `tools/android_prepare.py` (fixture `messages.json`: bytes B6 Lab sends, captured by calling `B6` methods on a recording stub whose `send` stores payloads)
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/MessagesTest.kt`

**Interfaces:**
- Produces: `object Msg { val IDENTITY; val PATCH_INFO; val ENTER_PC /* 52 00 6E 50 */; val LEAVE_PC /* 51 */; val SELECTED /* 33 */; val READ_EDIT /* 64 13 */; val ACK /* 52 00 6E 00 00 */; val GLOBAL /* 64 0A */; fun readPatch(slot: Int); fun selectSlot(slot: Int): List<ByteArray> /* B0 00 00, B0 20 bank, C0 pos */; fun store(slot: Int) /* 64 0D */; fun pressEffect(pos: Int): List<ByteArray> /* position, 5A 1, position, 5A 0 */; fun setParam(pos: Int, index: Int, value: Int): List<ByteArray>; fun changeType(pos: Int, fxId: Int): List<ByteArray>; fun insertEffect(pos: Int); fun deleteEffect(pos: Int); fun moveEffect(src: Int, dst: Int) }` (SysEx bodies without F0/F7; channel messages raw).
- Produces: `sealed class Push { data class PatchChanged(val slot: Int); data class ParamChanged(val pos: Int, val module: Int, val param: Int, val value: Int); object Ack; data class Error(val code: Int); data class Other(val body: ByteArray) }` and `fun parsePush(m: MidiMessage): Push?` (`64 26 00 00 <bank> 00 <pos> 00` -> slot = bank*4+pos; `64 20 00 <module> <param> <v:5>` -> ParamChanged; the position message itself (`module 0x64, param 1`) is ParamChanged too; caller decides).
- Produces: `object Safety { fun check(body: ByteArray) /* throws IllegalStateException */ }`; `fun parseAutoSave(globalReply: ByteArray): Boolean` (byte 12 != 0, as `global_info`).

- [ ] **Step 1:** Extend the generator (calls `press_effect(2)`, `set_param(4,4,3,57)`, `change_type(2,0x07090010)`, `insert_effect(1)`, `delete_effect(0)`, `move_effect(0,1)`, `store_edit(239)`, `select_slot(239)`, `read_patch(5)` request); regenerate.
- [ ] **Step 2:** Write tests: `buildersMatchB6Lab` (each builder == fixture bytes); `parsesRealPushes` with the literal messages from `captures/pcmode-20261111-185240.log`: `52 00 6e 64 26 00 00 3b 00 03 00` -> `PatchChanged(239)`, `52 00 6e 64 20 00 02 04 63 00 00 00 00` -> `ParamChanged(2, 2, 4, 99)`, `52 00 6e 64 20 00 02 00 01 00 00 00 00` -> `ParamChanged(2, 2, 0, 1)`; `safetyBlocksForbidden` (bodies starting `52 00 6E 01`..`0A`, `64 2D`, `64 3F`, `60 xx`, and `64 20 00 02 00 00 00 00 00 00` all throw; every `Msg` builder output passes); `autoSaveByte12`.
- [ ] **Step 3:** Run, FAIL; implement; run, PASS. Commit: `android: pedal messages and safety guard`.

### Task 6: Fake pedal (byte level)

**Files:**
- Create: `android/core/src/main/kotlin/nl/b6lab/remote/core/FakePedal.kt`
- Modify: `.../Transport.kt` (add the `MidiTransport` interface)
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/FakePedalTest.kt`

**Interfaces:**
- Produces: `interface MidiTransport { fun send(bytes: ByteArray) /* one complete message incl. F0/F7 for SysEx */; val incoming: kotlinx.coroutines.channels.ReceiveChannel<MidiMessage>; fun close() }`
- Produces: `class FakePedal(patches: List<ByteArray>, autoSave: Boolean = false) : MidiTransport` plus test hooks `fun footswitchTo(slot: Int)`, `fun turnKnob(pos: Int, index: Int, value: Int)`, `fun unplug()`, `val sent: List<ByteArray>`. Behaviour follows `b6lab/fake.py` and the verified pedal: identity reply `7E 00 06 02 52 6E 00 1A 00 31 2E 30 30`; `50`/`51` ack `00 00`; pushes only while in PC mode (`64 26` + bank/program change on footswitch, position + param pairs on knob); `33` answers with CC/PC; `64 13` -> `64 12 01 <size> <packed> <crc>` and expects the ack; `46` -> `45`; `64 0D` stores the edit buffer (replies `45` in PC mode); `64 0A` -> `64 09` with byte 12 = autoSave; live edits change the edit buffer through `Ptcf`; insert refused at 6 entries; `autoSave = true` stores every edit immediately; any `Safety`-forbidden body makes it throw (test failure).

- [ ] **Step 1:** Write tests: `answersIdentity`, `pushesOnlyInPcMode` (footswitch before and after `50`), `pressTogglesOnRelease`, `knobPushPair`, `storeAndRead`, `forbiddenMessageFails`.
- [ ] **Step 2:** Run, FAIL; implement; run, PASS. Commit: `android: fake pedal`.

### Task 7: Session

**Files:**
- Create: `android/core/src/main/kotlin/nl/b6lab/remote/core/Session.kt`
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/SessionTest.kt`

**Interfaces:**
- Consumes: `MidiTransport`, `Msg`, `Push`, `Ptcf`, `Codec`, `Safety` (all sends go through `Safety.check`).
- Produces: `data class PedalState(val connection: Connection /* DISCONNECTED, CONNECTING, CONNECTED */, val slot: Int?, val edit: Patch?, val dirty: Boolean, val autoSave: Boolean, val pcMode: Boolean, val error: String?)`; `class B6Session(scope: CoroutineScope, transport: MidiTransport) { val state: StateFlow<PedalState>; suspend fun connect(); suspend fun disconnect() /* sends 51 then closes */; suspend fun selectSlot(slot: Int); suspend fun toggle(slot: Int); suspend fun setKnob(slot: Int, index: Int, value: Int); suspend fun changeType(slot: Int, fxId: Int); suspend fun insert(pos: Int); suspend fun delete(slot: Int); suspend fun move(src: Int, dst: Int); suspend fun save() }`.
- Rules: `connect` = identity (model bytes `1A 00` else error "not a B6"), `50` (if reply `00 11` busy: `pcMode = false`, poll `33` + edit buffer every 750 ms instead), `64 0A` for autoSave, `33`, edit read (ack), stored slot read `46` as the dirty baseline. Every chain edit first re-reads the edit buffer and compares effect IDs with `state.edit` (mismatch: refresh, no send, `error = "patch changed on the pedal"`), sends, waits 250 ms where `b6lab/midi.py` does, then re-reads the edit buffer. `toggle` = `live.set_effect_on` logic incl. undo of an unexpected toggle. `PatchChanged` push -> edit + `46` re-read; `ParamChanged` pushes -> re-read edit, debounced 150 ms. `dirty = !Ptcf.samePatch(edit, stored)`. `save` = `64 0D <slot>`, then `46` read-back must equal the edit buffer (else error "save failed"). Transport closed or 3 s timeout -> `DISCONNECTED`.

- [ ] **Step 1:** Write tests against `FakePedal` with patches from `fixtures/` (via `ptcf.json` raw data): `connectsInPcMode`, `fallsBackToPollingWhenBusy`, `followsFootswitch` (push -> slot and edit updated within 1 s), `followsPedalKnob` (dirty becomes true), `toggleTogglesOnlyThatEffect`, `editRefusedWhenPatchChanged` (fake switches patch between the screen's state and the send: no live message sent, error set), `saveClearsDirty`, `autoSaveReported`, `unplugGoesDisconnected` (no exception escapes), `refusedInsertKeepsStateInSync` (insert into a 6-entry patch: fake refuses, state equals the edit buffer, error set), `neverSendsForbidden` (fake throws on any forbidden body; run all operations).
- [ ] **Step 2:** Run, FAIL; implement with coroutines (`runTest` + virtual time in tests); run, PASS. Commit: `android: B6 session`.

### Task 8: USB transport and app lifecycle

**Files:**
- Create: `android/app/src/main/kotlin/nl/b6lab/remote/UsbMidiTransport.kt`
- Modify: `android/app/src/main/kotlin/nl/b6lab/remote/MainActivity.kt`, `android/app/src/main/AndroidManifest.xml`

**Interfaces:**
- Produces: `class UsbMidiTransport private constructor(...) : MidiTransport { companion object { suspend fun open(context: Context): UsbMidiTransport? /* first MIDI device whose PROPERTY_PRODUCT contains "B6", input port 0 and output port 0; null if none */ } }`. Incoming bytes go through `SysexAssembler`; device removal closes `incoming`.
- MainActivity: `FLAG_KEEP_SCREEN_ON`; `onStart` opens the transport and `connect()`s; `onStop` calls `disconnect()`; a `MidiManager.DeviceCallback` reconnects on attach. Debug-only "Demo" button when no B6 is found, which runs the same session on `FakePedal` with the generated demo patches (`generated/demo/*.zptc`: backup slots 1, 3, 101, written by `android_prepare.py --assets`).
- Manifest: `android.software.midi` required, `NoActionBar` theme.

- [ ] **Step 1:** Implement; build; install on the phone (`adb install -r`).
- [ ] **Step 2: Hardware checklist with the user** (B6 on the phone via OTG, wireless adb for logs: `adb tcpip 5555` while on the cable, then `adb connect <phone-ip>`): app shows CONNECTED, slot and patch name match the pedal; footswitch patch change appears within 1 s; unplug shows DISCONNECTED, replug reconnects; leaving the app and returning reconnects (about 3 s); the B6 display does not show "PC mode" and footswitches work. Record results in `analysis/ANDROID-HW-CHECK.md`.
- [ ] **Step 3:** Commit: `android: USB transport and lifecycle`.

### Task 9: Screen controller

**Files:**
- Create: `android/core/src/main/kotlin/nl/b6lab/remote/core/Controller.kt`
- Test: `android/core/src/test/kotlin/nl/b6lab/remote/core/ControllerTest.kt`

**Interfaces:**
- Consumes: `B6Session`, `Catalog`.
- Produces: `data class PedalView(val slot: Int /* entry */, val fx: EffectInfo?, val on: Boolean, val selected: Boolean)`; `data class KnobView(val index: Int, val name: String, val value: Int, val max: Int, val text: String)`; `data class BoardUi(val header: String /* "BANK 01 · B" */, val name: String, val connected: Boolean, val pedals: List<PedalView> /* tails excluded */, val freePlaces: Int /* 0 when 6 entries or no DSP room */, val knobs: List<KnobView>, val canSave: Boolean, val autoSaveWarning: Boolean, val error: String?)`; `class RemoteController(scope, session, catalog) { val ui: StateFlow<BoardUi>; fun tapPedal(slot: Int) /* unselected: select; selected: session.toggle */; fun dragKnob(index: Int, value: Int) /* clamp 0..max, throttle 30 ms, last value always sent */; fun choose(fxId: Int, replaceSlot: Int?) /* change type or insert+change */; fun remove(slot: Int); fun move(src: Int, dst: Int); fun previousPatch(); fun nextPatch() /* wrap 0..239 */; fun save() }`. Header letters: position 0..3 -> A..D, bank two digits from 01.

- [ ] **Step 1:** Write tests with `FakePedal`: `firstTapSelectsSecondToggles`, `knobThrottleSendsLastValue` (100 drags in 100 ms virtual time -> at most 4 sends, last value equals the final drag), `knobClamped`, `tailsNotShown` (SVT Drive: 3 pedals), `noFreePlacesWhenFull`, `nextPatchWraps` (239 -> 0), `headerFormat` (slot 239 -> "BANK 60 · D"), `autoSaveWarningShown`, `selectionSurvivesPushOfSamePatch`, `selectionResetsOnPatchChange`.
- [ ] **Step 2:** Run, FAIL; implement; run, PASS. Commit: `android: screen controller`.

### Task 10: Board screen (Compose)

**Files:**
- Create: `android/app/src/main/kotlin/nl/b6lab/remote/ui/Theme.kt`, `ui/BoardScreen.kt`, `ui/Pedal.kt`, `ui/Dial.kt`
- Modify: `MainActivity.kt` (show `BoardScreen`)

**Interfaces:**
- Consumes: `RemoteController.ui` and its actions.
- Layout per spec "Decided with the user": dark theme; header (bank·pos, name, ◀ ▶, connection dot), Save button lit only when `canSave`, banners for disconnected / AUTO SAVE on / error. Portrait: pedal row (horizontal scroll allowed) + selected effect's dials in a grid of 3. Landscape (C1): 6 equal places in one row (empty ones "+"), all knobs of the selected effect in one row, no scrolling. Pedal: Guitar Lab SVG via Coil from `generated/svg/`, greyed (alpha 0.35, grayscale) when off, red LED when on, blue outline when selected; drag sideways to move (drop position -> `move`). Dial: vertical drag changes the value (full range over 200 dp), value text in the middle; tap opens a bottom sheet with a large slider and − / + step buttons. Minimum touch target 56 dp.

- [ ] **Step 1:** Implement; build; install; run the Demo mode on the phone.
- [ ] **Step 2:** Check on the phone (and send the user a screenshot via `adb exec-out screencap -p`): portrait and landscape match the chosen mockups (`.superpowers/brainstorm/3549078-1794397492/content/patch-screen-landscape.html`, option C1, and `pedal-look.html`, option A); nothing hidden under system bars; tap/toggle, dial drag, fine slider, drag-to-move work in Demo mode. The user confirms the look.
- [ ] **Step 3:** Commit: `android: board screen`.

### Task 11: Effect chooser

**Files:**
- Create: `android/app/src/main/kotlin/nl/b6lab/remote/ui/ChooserScreen.kt`
- Modify: `ui/BoardScreen.kt` ("+" and long press open it)

**Interfaces:**
- Consumes: `Catalog.byGroup()`, `Catalog.fits()`, `RemoteController.choose()` / `remove()`.
- Full screen: group tabs in Guitar Lab order, grid of effect pictures with names; effects that do not fit (`fits == false`) greyed and not tappable; opened from a pedal's long press it also offers "Remove". Back returns without change.

- [ ] **Step 1:** Implement; Demo-mode check on the phone: add into an empty place, change a type, remove, full-chain greying.
- [ ] **Step 2:** Commit: `android: effect chooser`.

### Task 12: End-to-end on the B6

**Files:**
- Modify: `analysis/ANDROID-HW-CHECK.md`, `docs/superpowers/specs/2026-11-11-b6-android-remote-design.md` (Open questions answered)

- [ ] **Step 1:** Ask the user before the first live edits from the phone; use a scratch patch (an Empty slot, e.g. slot 104, with a copy of SVT Clean written by B6 Lab) and AUTO SAVE switched off on the pedal.
- [ ] **Step 2:** With the user, on the real B6: on/off, knob (hear it), change type, add, remove, move, Save then re-select the slot (change kept), edit then switch patch (change dropped); AUTO SAVE on/off on the pedal flips the app's warning (confirms byte 12); kill the app without `51` (`adb shell am force-stop nl.b6lab.remote`), reopen: reconnects. Note every result in `analysis/ANDROID-HW-CHECK.md`.
- [ ] **Step 3:** Commit: `android: hardware check results`.
