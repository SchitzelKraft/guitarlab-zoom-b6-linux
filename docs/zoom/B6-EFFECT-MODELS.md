# B6 effect models: which real gear each effect is based on

Covers everything in the B6 effect catalog (firmware effect set as loaded by
`b6lab.effects.load()`): 116 effects, 3 effects-loop blocks and 36 impulse responses.

Sources: Zoom's effect descriptions (stored in the effect files on the pedal and in
`pedal-files/effects.json`), Zoom's FX list (`docs/zoom/E_B6_FX-list_2.txt`) and the cabinet
and IR chart (`docs/zoom/B6_CabSim-IRChart_2.txt`) (Zoom's files, not in the repository).

Note: `pedal-files/effects.json` still lists the 36 IRs twice, under category 0x1A and 0x1B.
Only 0x1B holds the IRs; 0x1A is the effects loop (FxLoop, Send, Return), which
`b6lab.effects` adds at load time.

**Basis** column:

- **Zoom**: Zoom names the gear itself ("simulation of", "models", "in the style of").
- **Likely**: our identification, from the effect name plus Zoom's description.
- **Guess**: our identification on weaker evidence.
- **Original**: Zoom says it is its own design.
- **Generic**: an effect type, no specific product behind it.

## Dynamics

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| SlowATTCK | volume swell, like the BOSS SG-1 Slow Gear | Guess | violin-like attack |
| ZNR | ZOOM noise reduction | Original | |
| OptComp | optical compressor | Generic | |
| BlackOpt | Demeter COMP-1 Compulator | Zoom | extra tone controls |
| LMT-76 | UREI 1176LN | Zoom | |
| 160 Comp | dbx 160A | Zoom | |
| DualComp | two-band compressor | Generic | |
| MB Comp | "MultiComp (MODE:MB)" | Zoom | Zoom names it only as MultiComp, unit not further identified |
| DYN Comp | MXR Dyna Comp | Zoom | extra tone and attack controls |
| Glam Comp | compressor with Shape control | Original | |

## Filter and EQ

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| SeqFLTR | Z.Vex Seek-Wah | Zoom | "has the flavor of" |
| EG FLTR | footswitch-triggered filter | Generic | |
| Exciter | harmonic exciter, the Aphex Aural Exciter idea | Guess | |
| BassA-Wah | bass auto-wah | Generic | |
| Z Tron | Electro-Harmonix Q-Tron (LP mode) | Zoom | |
| A-Filter | resonant envelope filter | Generic | |
| Bass Cry | talking modulator (talk-box-like filter) | Generic | |
| BassGEQ | 7-band bass graphic EQ, like the BOSS GEB-7 | Guess | |
| St Ba GEQ | stereo version of BassGEQ | Generic | |
| BassPEQ | 1-band parametric EQ | Generic | |
| Splitter | high/low band splitter | Generic | |
| Low EQ | low-frequency EQ with selectable type | Generic | |
| High EQ | high-frequency EQ with selectable type | Generic | |
| EnvFilter | MXR envelope filter (the M82 Bass Envelope Filter) | Zoom / Likely | Zoom says "MXR envelope filter"; the M82 is MXR's bass version |

## Drive

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| EP Stomp | Maestro Echoplex preamp (EP-3) | Zoom | |
| RC Boost | Xotic RC Booster | Likely | name match; Zoom only says "booster" |
| NYC Muff | Electro-Harmonix Big Muff Pi | Zoom | dry/wet mix added |
| TS+Boost | Ibanez Tube Screamer plus a booster | Likely | Zoom: "combines TS Drive and Booster" |
| Squeak | ProCo RAT | Zoom | dry/wet mix added |
| Bass OD | BOSS ODB-3 | Zoom | |
| BassTsDRV | Ibanez TS808 | Zoom | dry/wet mix added |
| Dark OD | Darkglass Microtubes B3K | Zoom | |
| BlueB BOD | Mad Professor Blueberry Bass Overdrive | Zoom | dry/wet mix added |
| VooDoo-B | Roger Mayer Voodoo-Bass | Zoom | dry/wet mix added |
| BaFzSmile | Fuzz Face (Dallas Arbiter / Dunlop) | Zoom | dry/wet mix added |
| BassMetal | BOSS Metal Zone (MT-2) | Zoom | dry/wet mix added |
| BassOctFZ | octave-up fuzz, Octavia style | Guess | |

## Preamp

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| Bass DRV | Tech 21 SansAmp Bass Driver DI | Zoom | |
| D.I Plus | MXR Bass D.I.+ | Zoom | |
| Dark Pre | Darkglass Microtubes B7K | Zoom | |
| Bass BB | Xotic Bass BB Preamp | Zoom | |
| DI-5 | Avalon Design U5 | Zoom | |
| Bass Pre | preamp with 3-band EQ | Generic | |
| Pre1073 | Neve 1073 | Likely | Zoom: "vintage mic preamp characterized by its transformers" |
| SolidPre | SSL console mic preamp (VHD) | Likely | Zoom: "solid-state mic preamp made by a console manufacturer", with harmonics control |
| Clear DRV | linear-phase EQ distortion | Original | |
| SpLoPre | extreme low-end amp | Original | |
| DjentPre | clean lows, distorted highs | Original | |

## Bass amps

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| AMPG SVT | Ampeg SVT | Zoom | |
| BMAN100 | Fender Bassman 100 | Zoom | |
| SMR400 | SWR SM-400 | Zoom | |
| AG 750 | Aguilar DB 750 | Zoom | |
| TE400SMX | Trace Elliot AH400SMX | Zoom | |
| AC 370 | Acoustic 370 | Zoom | |
| Mini MkB | Markbass Minimark 802 | Zoom | |
| EBH360 | EBS HD360 | Zoom | |
| FlipTop | Ampeg B-15N (Portaflex "flip top") | Zoom | |
| SUN CB | Sunn Coliseum Bass | Likely | Zoom: "vintage solid-state amp from the 70s" |
| Monotone | Polytone Mini-Brute | Likely | Zoom: "solid-state combo amp great for jazz"; factory patch "Poly Combo" uses it |

## Cabinets

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| SVT8x10 | Ampeg SVT-810E, 8x10" | Zoom | |
| SVT4x10TW | Ampeg SVT-410HLF, 4x10" + tweeter | Zoom | |
| FD-B4x12 | Fender Bassman 100 cabinet, 4x12" | Zoom | |
| SMR4x10TW | SWR Goliath, 4x10" + tweeter | Zoom | |
| AG4x10TW | Aguilar GS410, 4x10" + tweeter | Zoom | |
| TE4x10 | Trace Elliot 1048, 4x10" | Zoom | |
| AC1x18 | Acoustic 301, 1x18" | Zoom | |
| MkB2x8TW | Markbass Minimark 802, 2x8" + tweeter | Zoom | |
| EB4x10TW | EBS ProLine 410, 4x10" + tweeter | Zoom | |
| AM1x15 | Ampeg B-15N, 1x15" | Zoom | |
| SN2x15 | Sunn Coliseum cabinet, 2x15" | Likely | Zoom: "vintage 70s solid-state amp cabinet" |
| MT1x15 | Polytone combo, 1x15" | Likely | Zoom: "solid-state combo cabinet great for jazz" |

## Modulation and pitch

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| Tremolo | tremolo | Generic | |
| Phaser | phaser | Generic | |
| TheVibe | Shin-ei Uni-Vibe | Likely | Zoom: "vibe sound" |
| PitchSHFT | pitch shifter | Generic | |
| HPS | intelligent (scale-aware) harmonizer | Generic | |
| Kick FLNG | footswitch-triggered flanger | Generic | |
| CloneCho | Electro-Harmonix Small Clone | Zoom | |
| SuperCho | BOSS CH-1 Super Chorus | Zoom | |
| CoronaTri | TC Electronic Corona Tri-Chorus | Zoom | |
| BassStCho | stereo bass chorus | Generic | |
| BaVinFLNG | MXR M-117R flanger | Zoom | "similar to"; low cut added |
| Ba Octave | octave down | Generic | |
| Ba AnaOct | analog octaver, like the BOSS OC-2 | Guess | |
| Ba Detune | detune chorus | Generic | |
| BaMnPitch | monophonic bass pitch shifter | Generic | |
| BaPlShift | polyphonic bass pitch shifter | Generic | |
| BassPhase | bass phaser | Generic | |

## SFX and synth

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| Bomber | explosion sound | Original | |
| LoopRoll | footswitch sample-and-hold | Generic | |
| BaStdSyn | ZOOM bass synth | Original | |
| BaSynTlk | talking (vowel) bass synth | Generic | |
| Z-Syn | analog-style bass synth | Generic | |
| Defret | fretless simulation | Generic | |
| PH+Dist | Roland Jet Phaser (AP-7) | Zoom | "in the style of" |

## Delay

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| Delay | digital delay, up to 4000 ms | Generic | |
| AnalogDly | analog (bucket-brigade) delay | Generic | |
| TapeEcho | tape echo | Generic | |
| ReverseDL | reverse delay | Generic | |
| ModDelay | modulated delay | Generic | |
| Hold DLY | footswitch hold delay | Generic | |
| Dual DLY | Eventide TimeFactor (DigitalDelay) | Zoom | "based on" |

## Reverb

All generic types: Air, Room, BrghtRoom, Hall, BrghtHall, HD Hall, Spring, Plate. Zoom names
no product for any of them.

## Pedal (expression)

| Effect | Real gear | Basis | Notes |
|---|---|---|---|
| PDL Vol | volume pedal | Generic | |
| BassWah | bass wah pedal | Generic | |
| PDL Reso | resonant pedal wah | Generic | |
| Ba PDLPit | pedal pitch shift, DigiTech Whammy style | Likely | |
| Ba PDLMnP | monophonic pedal pitch shift, Whammy style | Likely | |
| Output VP | master output volume | Generic | |

## Effects loop

FxLoop, Send and Return use the B6's own SEND/RETURN jacks, no model. This is where
Ali Martin's patches expect a Big Muff Pi and/or BOSS OC-2.

## Impulse responses

36 IRs: the 12 cabinets above, each captured with three mic setups. The chart names the
mics only as "D20" and "D57"; the cabinet effects' knob descriptions identify them as the
Electro-Voice RE-20 and the Shure SM57 (**Zoom**, e.g. AM1x15 `DYN20` / `DYN57`).

| Cabinet | On mic (D20) | 2nd IR | Room |
|---|---|---|---|
| Ampeg SVT-810E | SVT8_D20 | SVT8_D57 (on mic 2) | SVT8_Room |
| Ampeg SVT-410HLF | SVT4_D20 | SVT4_TW (tweeter mix) | SVT4_Room |
| Fender Bassman 4x12 | FDB_D20 | FDB_D57 (on mic 2) | FDB_Room |
| SWR Goliath 4x10 | SMR_D20 | SMR_TW (tweeter mix) | SMR_Room |
| Aguilar GS410 | AG_D20 | AG_TW (tweeter mix) | AG_Room |
| Trace Elliot 1048 | TE_D20 | TE_D57 (on mic 2) | TE_Room |
| Acoustic 301 | AC_D20 | AC_D57 (on mic 2) | AC_Room |
| Markbass Minimark 802 | MkB_D20 | MkB_TW (tweeter mix) | MkB_Room |
| EBS ProLine 410 | EB_D20 | EB_TW (tweeter mix) | EB_Room |
| Ampeg B-15N 1x15 | AM_D20 | AM_D57 (on mic 2) | AM_Room |
| Sunn 2x15 | SN_D20 | SN_D57 (on mic 2) | SN_Room |
| Polytone 1x15 | MT_D20 | MT_D57 (on mic 2) | MT_Room |

"Tweeter mix" = the D20 on-mic IR mixed with a D57 on the tweeter (per the chart).

## Counts

Of the 116 effects: Zoom names the gear for 48 (EnvFilter counted here; we add the exact
MXR model), we identify 11 more (Likely), 5 are guesses, 7 are stated Zoom originals and
45 are generic effect types.
