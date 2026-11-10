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

B6 Lab uses files that belong to Zoom, so they are not in this repository. You get them from
your own pedal and from Zoom's Guitar Lab 7.3 downloads. All paths below are relative to the
repository folder. Step 2 is required: B6 Lab draws its whole interface with those images and
does not start properly without them. Without the others, names, icons and pictures are missing.

1. **Effect files from your pedal** (effect and knob names, effect icons in the pedal view).
   Connect the B6, switch it on, close every other MIDI program, then:

       python3 tools/ffs_read.py --all              # FLST_SEQ.ZT2 + every .ZD2 into pedal-files/
       .venv/bin/python tools/build_effects.py      # pedal-files/effects.json (also asks the pedal for the IR names)
       python3 tools/extract_zd2_icons.py pedal-files analysis/pedal-reference-assets

   `ffs_read.py` only reads; it takes a few minutes. If it is stopped halfway and the pedal
   stops answering, switch the pedal off and on.

2. **Interface images from Guitar Lab for Mac.** Download "Guitar Lab 7.3 for macOS"
   (`GuitarLab_Mac_v7.3.0.130_E.zip`) from the B6 support page
   (https://zoomcorp.com/en/us/multi-effects/bass-effects/b6/b6-support/) and unzip it. You need no Mac: open the disk image read-only on Linux (`sudo apt install
   dmg2img`) and extract the images from the app's program file:

       dmg2img -s "Guitar Lab Installer.dmg" gl.img
       udisksctl loop-setup -r -f gl.img            # prints /dev/loopN
       udisksctl mount -b /dev/loopN -o ro          # prints the mount folder
       python3 tools/extract_mac_assets.py "<mount folder>/ZOOM Guitar Lab.app/Contents/MacOS/ZOOM Guitar Lab" \
           analysis/mac-reference-assets --ir-svg analysis/win-download/SVG/_IR.svg
       udisksctl unmount -b /dev/loopN && udisksctl loop-delete -b /dev/loopN

   This must give 144 images; B6 Lab finds them by their position in the program file, so
   only Guitar Lab 7.3.0.130 fits.

3. **The B6 picture and the colour effect drawings**, which Guitar Lab downloads from Zoom
   when it runs. The picture can be fetched directly:

       mkdir -p analysis/win-download
       curl -L -o analysis/win-download/model_image3-B6.png \
           https://www.zoom.co.jp/archive/GUITAR_LAB/model_image3/B6.png

   The effect drawings (`<module>.svg`, about 390 files) can only be taken from a Guitar Lab
   that has been connected to the B6 once. Guitar Lab for Windows runs under Wine; after
   it has shown the pedal, copy the folder:

       mkdir -p analysis/win-download/SVG
       cp ~/.wine/drive_c/users/$USER/AppData/Roaming/GL/SVG/*.svg analysis/win-download/SVG/

   (On Windows the folder is `%APPDATA%\GL\SVG`.) Without them the chain shows no effect
   icons.

4. **Knob limits** (`pedal-files/parameter-ranges.json`) are optional. They were built from a
   recording of Guitar Lab talking to the pedal, which is not available outside this project,
   so without the file knob values are shown raw. The same file also tells B6 Lab which `.ZD2`
   belongs to which effect, so the processor load, the BassGEQ sliders and the Clipboard's
   compatibility check also need it.

`--fake` mode also needs a backup set of your patches in `backup/` (PATCH page > Backup All,
while connected to the pedal).

## Tools

- `python3 tools/ffs_read.py NAME... | --list | --all`: read files from the pedal's internal
  file system into `pedal-files/` (read-only; logs every message to `pedal-files/ffs.log`).
- `.venv/bin/python tools/build_effects.py [--no-pedal]`: build `pedal-files/effects.json`
  (effect and knob names) from the `.ZD2` effect files and the pedal's IR name list.
- `python3 tools/extract_zd2_icons.py MODULES OUTPUT`: the effect bitmaps inside `.ZD2` files.
- `python3 tools/extract_mac_assets.py BINARY OUTPUT [--ir-svg FILE]`: the PNG images inside
  Guitar Lab for Mac's program file.

## Safety rules

- Every save first copies the slot's current content to `backup/overwritten/`.
- After every write the slot is read back and compared; a mismatch is reported as a failure.
- To undo a save: every save keeps the previous slot content in
  `backup/overwritten/<time>_slotNNN_<name>.zptc`; restore it with Patches > Import .zptc into that slot.
- In `--fake` mode nothing is written to the real backup folders: save backups go to
  `backup/fake/overwritten/` and "Back up all" to `backup/fake/`.
- If the pedal stops answering, the light turns grey with the reason; use Reconnect to connect again
  and re-read all patches.
- If the slot changed on the pedal since it was loaded, the app asks before overwriting.
- Take a full backup before experimenting: PATCH page > Backup All.

## Known limits

- Effect and knob names come from `pedal-files/effects.json`, built from your pedal's own
  effect files. Without that file, boxes show the raw effect ID and knobs P1..Pn. IR boxes
  show the IR name, but their knobs stay P1..P4 (the pedal has no names for them).
  To rebuild it, for example after installing new effects with Guitar Lab, repeat step 1
  of "Data files".
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
