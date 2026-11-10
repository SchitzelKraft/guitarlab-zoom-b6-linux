# B6 Lab

B6 Lab is a Linux desktop editor for the Zoom B6 multi-effects pedal. It talks to the pedal
over USB MIDI (raw ALSA, no extra drivers) and lets you browse all 240 patch slots, switch the
pedal to a slot, edit effect on/off and knobs, rename patches, import and export `.zptc`
files, and save back to the pedal with an automatic backup.

## Install

    python3 -m venv .venv && .venv/bin/pip install PySide6 pytest pytest-qt

## Run

    .venv/bin/python -m b6lab           # with the pedal connected and switched on
    .venv/bin/python -m b6lab --fake    # no pedal: uses an in-memory fake device

Only one program can hold the pedal's MIDI port at a time; close other editors and CLI tools first.

## Data files (not in this repository)

B6 Lab loads files that belong to Zoom, so they are not included. Put them next to `b6lab/`:

- `pedal-files/`: the B6's effect files (`*.ZD2`, `FLST_SEQ.ZT2`, read from your own pedal with
  `tools/ffs_read.py`) and `effects.json` / `parameter-ranges.json` built from them.
- `analysis/mac-reference-assets/` and `analysis/pedal-reference-assets/`: the interface images,
  taken from Zoom Guitar Lab 7.3 for Mac.
- `analysis/win-download/SVG/` and `analysis/win-download/model_image3-B6.png`: the effect
  drawings and the B6 picture from Guitar Lab's Windows download.

`--fake` mode also needs a backup set of your patches in `backup/`.

## Tests

    QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q

## CLI tools

- `python3 tools/zoomb6.py info | read | backup | write | watch`: pedal info, read a slot,
  back up all 240 slots (`backup <dir>`), write a patch file to an Empty slot, watch the edit buffer.
- `python3 tools/ptcf.py`: decode and inspect `.zptc` patch files.
- `python3 tools/ffs_read.py NAME... | --list`: read files from the pedal's internal file
  system into `pedal-files/` (read-only; logs every message to `pedal-files/ffs.log`).
- `.venv/bin/python tools/build_effects.py`: build `pedal-files/effects.json` (effect and knob
  names) from the `.ZD2` effect files and the pedal's IR name list.
- `.venv/bin/python tools/build_param_ranges.py`: rebuild captured knob limits and documented
  display mappings from the existing Guitar Lab MIDI capture and Zoom's B6 effect list.
- `python3 tools/e2e_check.py`: hardware end-to-end check on one Empty slot above 100
  (import, edit, rename, re-read, restore). It writes to the real pedal.

## Safety rules

- Every save first copies the slot's current content to `backup/overwritten/`.
- After every write the slot is read back and compared; a mismatch is reported as a failure.
- `tools/zoomb6.py write` refuses a slot that is not named "Empty" unless `--force` is given.
- To undo a save: every save keeps the previous slot content in
  `backup/overwritten/<time>_slotNNN_<name>.zptc`; restore it with Patches > Import .zptc into that slot.
- In `--fake` mode nothing is written to the real backup folders: save backups go to
  `backup/fake/overwritten/` and "Back up all" to `backup/fake/`.
- If the pedal stops answering, the light turns grey with the reason; use Reconnect to connect again
  and re-read all patches.
- If the slot changed on the pedal since it was loaded, the app asks before overwriting.
- Take a full backup before experimenting: `python3 tools/zoomb6.py backup backup/b6-$(date +%Y%m%d-%H%M)`.

## Known limits

- Effect and knob names come from `pedal-files/effects.json`, built from your pedal's own
  effect files. Without that file, boxes show the raw effect ID and knobs P1..Pn. IR boxes
  show the IR name, but their knobs stay P1..P4 (the pedal has no names for them).
  To rebuild it, for example after installing new effects with Guitar Lab:

      python3 tools/ffs_read.py --list        # see the file names
      python3 tools/ffs_read.py FLST_SEQ.ZT2 <every *.ZD2 name>
      .venv/bin/python tools/build_effects.py
- All knobs are editable. Knobs 1-4 were confirmed with a knob test on the pedal; 5 and up
  by checking every stored value of all patches against Zoom's knob ranges. Values stored
  beyond an effect's named knobs are shown small, marked "hidden", and stay read-only.
- Knob limits for the captured effect modules come from the pedal's `64 06` parameter-info
  records. Numeric displays are derived from the documented endpoints when the captured
  limit supports a simple linear scale; enumerated labels come from the effect list. Where
  the display mapping is unknown, the value is marked `raw`. IR controls and effects without
  matching captured metadata still use the existing raw controls. Limits are ignored if an
  effect file changes, until a matching capture is available.
- Effect on/off and knobs are live: the pedal hears a change right away (in its edit
  buffer, the way Guitar Lab does it; see `b6lab/live.py`). A switch shows the state the pedal
  reports; after you stop turning a knob, B6 Lab reads the pedal back and reports any difference
  in the status bar. Nothing is stored until Save; with AUTOSAVE off, switching patch on the pedal
  discards the change. Name, comment and patch level are still heard only after Save.
- No adding, removing or reordering of effects.
- The Effect view lists the extracted B6 effects and counts their uses in the loaded
  patches. Power percentages and favorites are not yet available; the Effect Pool,
  Patch Pool, Clipboard, Import IR, and News do not yet reproduce Guitar Lab's full
  functionality. Effect editing remains available through the Editor view.
- The screenshots supplied for the interface show bank labels and colors through Z;
  later slots use a numeric label and neutral color until their original appearance
  can be verified.

## Protocol notes

See `analysis/PROTOCOL.md` for the SysEx protocol, the PTCF patch format and what has been
verified on hardware.
