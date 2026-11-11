# B6 Remote for Android: design

Date: 2026-11-11. Status: reviewed, awaiting the user's approval.

## Intent and why

An Android phone app that edits the **active patch** of a Zoom B6 bass pedal, for quick changes
during practice and on stage. The phone sits on a mic stand and gets quick glances only. The
pedal keeps showing its own patch screen and is played with the feet as usual; the phone always
shows the effect chain of whatever patch is active and follows when the patch changes on the
pedal.

It is the user's own counterpart of Zoom's iOS "Handy Guitar Lab for B6" (which needs an iPhone
and a BTA-1 Bluetooth adapter), reduced to what matters on stage. Everything else stays in
B6 Lab, the existing Linux desktop editor in this repository.

## Goals

- Show the active patch: bank and position, patch name, connection state, and the effect chain.
- Switch an effect on/off.
- Turn an effect's knobs.
- Add, change (swap type), remove and move effects in the chain.
- Change patch from the phone (previous/next); follow patch changes made on the pedal at once.
- Keep edits temporary unless saved: a Save button that lights up when the patch has unsaved
  changes; switching patch drops unsaved changes without asking.
- Warn when the pedal's own AUTO SAVE is on (then the pedal stores edits itself, so the
  "temporary unless saved" promise cannot hold). The user's B6 probably has it on; **the user
  will switch AUTO SAVE off on the pedal themselves**. The app only reads it and shows a clear
  warning while it is on; it never writes this setting.

## Non-goals (for now)

Patch list management (rename, move, copy, delete patches or banks), IR import, Patch Pool,
system settings, tuner, rhythm, looper, Bluetooth/BTA-1, iOS, Play Store release. These stay in
B6 Lab or are out of scope.

## Anti-goals (a failure even if it works)

- Freezing or bricking the pedal. The safety rules below are hard requirements.
- Edits stored without the user saving them (beyond what the pedal's AUTO SAVE does, which the
  app must flag).
- The pedal's display or footswitches behaving differently because the phone is connected
  (beyond the selected effect following phone edits, which the user accepted).
- Controls too small or fiddly to hit on a mic stand; anything that needs reading small text.

## Constraints

- Kotlin + Jetpack Compose. Android MIDI API (`android.media.midi`) over USB OTG; the B6 is a
  class-compliant USB MIDI device and appears as one device with 1 input + 1 output port.
- Target phone: the user's Pixel 9 Pro, Android 17 (API 37). Debug build, installed with
  `adb` from `~/Android/Sdk`; never published. No Android Studio on the machine: command-line
  Gradle build.
- Zoom's files (effect pictures, effect catalogue) are not committed. The build copies them
  from the local, git-ignored folders B6 Lab already uses (`analysis/win-download/SVG/*.svg`,
  `pedal-files/effects.json` and its parameter ranges) into the app's assets. A personal debug
  build may contain them; the repository may not.
- Behaviour copies what is verified on the pedal or recorded from Guitar Lab (the project rule:
  never invent protocol behaviour). Unknowns are tested on the pedal with the user first.

## Decided with the user

- **Main screen = pedal board** ("C"). Upright: a row of pedals with a red LED for on, the
  selected effect highlighted, its knobs as large dials below. Sideways ("C1", chosen): all 6
  effect places in one row across the top (empty places show "+"), every knob of the selected
  effect in one row below; nothing scrolls. Header: bank and position, patch name, previous/next
  patch, connection dot.
- **Pictures:** Guitar Lab's colour effect drawings (the same SVGs as B6 Lab); effects that are
  off are greyed out. Dark background for stage light.
- **Interaction (user accepted these):** tap a pedal to select it, tap the selected one again to
  switch it on/off; "+" or a long press opens a full-screen effect chooser grouped by category
  (Guitar Lab's categories, with pictures); drag a pedal sideways to move it.
- **Saving:** temporary edits, Save button, no prompt when switching patch (see Goals).
- **Scope:** only the active patch (see Non-goals).
- **Pedal follows the phone's selection (user accepted):** every live edit starts with the
  position message `64 20 00 64 01 <pos>`, so tapping an effect or turning a knob on the phone
  also moves the pedal's selected effect to it. The patch screen stays. Port B6 Lab's live
  edits as they are; no untested alternative route.

## Verified facts the design rests on

From the USB test app on the Pixel (2026-11-11) and `tools/pcmode_probe.py` on the real B6
(log `captures/pcmode-20261111-185240.log`):

- Android delivers the B6's SysEx intact: all 240 patches read with correct CRC in 3.0 s,
  0 errors. A 941-byte reply arrives split into up to 82 `onSend()` chunks, so the app must
  reassemble F0..F7 itself (realtime bytes may interleave).
- With Android's `targetSdk` 35+, apps are drawn edge-to-edge: pad for system-bar insets.
- **PC mode (`50`, acknowledged `00 00`) is the connection mode.** With it the pedal pushes, at
  once: patch change as `64 26 00 00 <bank> 00 <pos> 00` plus `B0 00 00`, `B0 20 <bank>`,
  `C0 <pos>`; knob turns as `64 20 00 64 01 <pos>` then `64 20 00 <module> <knob+2> <value>`
  per step; on/off as the same pair with param 0. The display does not change and the
  footswitches keep working. `51` ends PC mode. Without `50` the pedal sends nothing by itself
  (polling `33` + edit-buffer read every ~0.75 s also works and is the fallback).
- Protocol details already implemented and verified in B6 Lab, to be ported:
  `b6lab/codec.py` (7-in-8 packing, 14-bit values, CRC tail), `b6lab/ptcf.py` (patch format,
  chain edits), `b6lab/midi.py` (requests, `selected_slot`, `select_slot`, `read_edit` with its
  `00 00` ack, save `64 0D`), `b6lab/live.py` (live on/off via the virtual footswitch `5A`
  press/release, live knobs, change type, add/delete/move via module 100 params 7/8/9),
  `b6lab/effects.py` (catalogue, parameter ranges and display values).
- Command inventory and firmware addresses: `analysis/HANDY-GL.md`. Live-edit history and
  failures: `analysis/LIVE-EDIT.md`.

## Safety rules (hard requirements)

- Never send: `01`-`0A`, `64 2D`, `64 3F`, `60 10`, `60 30` (HANDY-GL.md section 7).
- Never send direct on/off (`64 20 00 <slot> 00 <v>`): it froze the B6 three times. On/off only
  via the `5A` press/release as `b6lab/live.py` does.
- Always acknowledge an edit-buffer dump (`64 12`) with `52 00 6E 00 00`.
- No file-system (`60 xx`) traffic at all in this app.
- Send `51` when the app disconnects on purpose; on reconnect start again with identity + `50`.
- A protocol message B6 Lab does not already send is tried on the pedal only after asking the
  user.

## Left to the builder

- Architecture inside the app (layers, state handling, threading), as long as the protocol and
  patch logic is a plain Kotlin module with no Android dependencies, tested on the JVM.
- How to keep the phone's view in sync: e.g. apply pushes directly and re-read the edit buffer
  after each own edit and after each patch-change push (B6 Lab confirms with a read).
- How "unsaved changes" is detected (e.g. edit buffer vs the stored slot read with `46`).
- Dial behaviour details (drag sensitivity, fine steps, value display), effect chooser layout,
  how double-width effects look, upright layout details.
- Tests: port B6 Lab's tests and use real data in the repo (`backup/` patches with their raw
  replies, `captures/`) as fixtures, so the Kotlin port must produce the same bytes as B6 Lab.
- An in-app fake pedal for working without the B6 (like `b6lab --fake`).

## My calls (not discussed with the user, open to change)

- App lives in `android/` in this repository, build files committed, Zoom assets git-ignored.
- PC mode as primary sync, polling only as fallback if `50` is refused (`00 11` busy).
- No network bridge to the virtual pedal (`vpedal/`): the real B6 is available for testing.
- Minimum Android version 10 (API 29); compileSdk 35, matching the working test app.
- **Effect catalogue = build-time snapshot** of `pedal-files/effects.json` (as B6 Lab uses it).
  The chooser offers only effects in that snapshot; after installing or removing effects on the
  pedal with B6 Lab, rebuild the app. No live effect-list read (it would need `60 xx` or
  untested commands).
- **Lifecycle:** the screen is kept on while the app is in front. When the app leaves the
  foreground it sends `51` and closes the port; on return it reconnects by itself (identity,
  `50`, `33`, edit-buffer read; about 3 s). No foreground service.
- **AUTO SAVE is read** with `64 0A` (already sent read-only by B6 Lab, `global_info()` decodes
  byte 12). That decoding comes from the decompile: confirm it on the pedal once (with AUTO SAVE
  on and off) before relying on it.
- **Development without the PC cable:** the B6 occupies the phone's only USB port, so use
  wireless adb when testing against the pedal.

## Open questions to settle on the pedal

- Exact message for patch volume as a live parameter (not found yet; volume is out of the
  goals anyway, listed for completeness).
- What the pedal does if the app disappears without `51` (stays in PC mode? harmless?).
- Confirm the AUTO SAVE byte in `64 0A` (see My calls).
