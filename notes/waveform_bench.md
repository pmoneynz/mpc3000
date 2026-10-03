# Waveform bench: 2026-10-01

## BENCH 07: review fixes, ready for the bench (2026-10-03)

BENCH 07 is BENCH 06 plus the review fixes (PR `pmoneynz/mpc3000#1`): CHOP ZONE
safe lock and mute-audio, numeric digit order, task-safe mute context,
Apply All confirmation, the 49 KB APS save budget, and the faster wave
redraw. Only the bench marker changed after the merged verification.

**PROVEN (MAME):** 135 emulator tests in 22 suites with skips forbidden,
67 builder tests, 171 boot-slice checks; the suites' payloads are
byte-identical to the release files. The release image itself boots to
`WAVE BENCH 07`, loads SINE441, and draws the wave view and Mute Groups page
(`build/emu/bench07-release-smoke`). `build/check_wavehw_layout.py` passes.
A near-full image (97 free clusters) refuses an APS save with `F900`
and leaves the disk unchanged; a PGM save succeeds.

- Payload SHA-256: `2cea7a481948b1273e0484c6aa03eb4f667c4318cc658a9ac6d7cbf8b0b879fb`.
- Image SHA-256: `dc953ab5314c4136b4510d5612eee7f589fdc5c9b1da02ecfb952fa4753da057`
  (`STARTUP.SYS`, `SINE441.SND`, `STEREO1.SND`, `DRUMS.SND`).
- Generic `WAVE.SYS`: `28514aa1427308bbfa60a9140c780f9514e3ff72908c5c30a659812cb8eda0f9`.
- Near-full image: `build/mods/WAVEHW-NEARFULL.img`.
- Validation: `build/mods/WAVEHW-validation.json`; BENCH 06 files archived in
  `build/mods/archive-bench06/`.
- Cave: 12,804 of 14,384 bytes.

First image from the builders' own FAT12 packer for a WAVE payload. Not yet
deployed; BENCH 05 remains on the USB. **UNDETERMINED:** all physical
behaviour. Bench procedure: [bench07_checklist.md](bench07_checklist.md).

## BENCH 06: mute groups and direct End/Zone navigation

Program/Sounds → **0. Mute groups** opens four program-scoped groups. Each
program has an enable switch; pads 1–64 each select Off or one of groups 1–4.
Soft key 1 **Apply All** opens a prompt naming the group; only soft key 3 **Do it**
then assigns it to all 64 pads. Any other key cancels without changing anything.
Assignments follow program copy/initialize and persist in PGM and APS files.
Pads sharing one MIDI note share the first matching pad's effective group.
See [controls and UI evidence](mute_groups.md), [voice behavior](mute_voice.md),
and [storage format and lifecycle](mute_storage.md).

The waveform shortcut is **End → Up → Zone**, then **Down → End**. It works in
mono, stereo, Full and Fine. Up while entering an End time accepts the current
component and selects Zone; untouched components are retained. Idle navigation
preserves the exact frame. Start retains Up/Down zoom control.

**PROVEN (final software checks):** 95 emulator tests and 171 stock boot-slice
checks pass against this candidate. This includes pad and external MIDI voice
choking, stereo/layers, same-pad Poly, stock NOTE OFF/Cutoff, live group edits,
program isolation, PGM/APS save/cold reload, program copy/init, legacy/malformed
program defaults, the complete mute-page pixel layout, the new navigation,
and all 65 existing waveform/CHOP regressions. Independent validation covers
both FATs, all four files and chains, MZ bounds, the exact BIOS comparison
array, declared ROM patches, and every relocation at CS=6900 and CS=7000.
The exact final image also reproduces the DRUMS Full/Fine/CHOP previews.

- Payload SHA-256: `39473bfb19b337e7a38c0eb9394520acdecabb50d668531ed5b727a5328ab360`.
- Image SHA-256: `8d68ad11e88c91c092dd9fe972cab1b28be52b05a49e7601ce0430a16ef4774f`.
- Validation: `build/mods/WAVEHW-validation.json`.
- Frozen candidate: `build/mods/wavebench06-preserved/`.
- Cave: 12,042 of 14,384 bytes.

**UNDETERMINED:** physical BENCH 06 panel/LCD/audio timing and media-error
cleanup. BENCH 05 remains installed on the USB; BENCH 06 has not been deployed.
No file under `07-rom/` was modified.

## BENCH 05: shared ZONE editing and CHOP ZONE

BENCH 05 adds the stock MPC2000XL zone model to the MPC3000 waveform
view: 1–16 equal starting divisions over the whole source, current zone 1,
and shared edges. `ZONE:01/16` at the top right has separate cursor positions
for the current zone and the total. Left/Right reaches them after Start,
End, and stereo View when present. The wheel and +/− adjust the focused
value. Changing total count resets manual boundaries. Changing current zone
selects that pair; adjusting an interior edge also changes its neighbor.

Soft keys remain **1 Ply/Stp, 2 Trim/Zone, 3 Fine/Full, 4 Exit**. The selected
zone supports the existing Fine view, numeric entry, and audition. Exit to
stock Edit Sound, choose **Do:CHOP ZONE**, then press **Do**. New collision-safe
`ZONE###` sounds are created with the selected PCM, source channel layout,
volume and tune. Native soft end is `length-1`. The source remains selected
and unchanged. No end margin is added: copies follow the edited boundaries.

Free slots and wave memory are checked before creating sounds; allocator
failure during the loop removes only the results from that invocation.
Empty zones and zones below 441 frames (10 ms) show a message and create
nothing. Shorter saved SND files hit a proven stock reload-length defect,
so this minimum protects the ordinary save/reload workflow.

The map belongs to the current Edit Sound session. Waveform Exit/reopen
preserves it; selecting a sound or leaving the page resets it. Count/boundary
metadata is volatile. The resulting sounds use the regular Disk save flow.

Implementation/evidence: [zone editor](wave_zones.md), [CHOP](wave_chop.md).
BENCH 04 is preserved in `build/mods/wavebench04-preserved/`. BENCH 05 is
installed in USB slot 1. Physical behavior remains **UNDETERMINED**.

**PROVEN in the final emulator runs:** 65 tests pass: 10 zone editor,
10 CHOP, 1 generic-profile CHOP, 1 stereo stock save/cold reload, and
43 existing physical-profile/numeric/playback/generic regressions. The 171
boot-slice checks and independent four-file FAT/MZ/ROM/relocation validation
also pass. No files under `07-rom/` changed.

- SYS SHA-256: `702938f74c18edcdf0a132b85b691fa1a295c719483927d88451e7838e935c73`
- IMG SHA-256: `e39449491b1988730b4e039e49f569eba36d65e8e8fb4b0bd054ef90f322398e`
- Release record and exact test logs: `build/mods/WAVEHW-validation.json`.
- Final disk: `build/mods/WAVEHW.img`, containing STARTUP.SYS, SINE441.SND,
  STEREO1.SND and DRUMS.SND.
- Exact-disk preview: `build/emu/wavebench05-preview/`. DRUMS appears with
  zone 04/04 at 92 s, Fine at 97 s, and stock Do:CHOP ZONE at 110 s.
  The disk hash is unchanged by the preview. The custom graphical display
  uses the complete WAVE font; hatched native-text glyphs remain the named
  U-LC7981-CG emulator boundary in `notes/emulator.md`.
- The source-selection regression covers a source sorting after new
  ZONE names and a stale-map refusal on a subsequently selected sound.
  Fast repeated wheel events now use the stock normalized-key count.

Physical qualification remains deferred. Late allocator-failure rollback is
source-reviewed but not execution-tested; actual preflight refusal for both
full directory and insufficient wave memory is execution-tested.


## BENCH 04 soft-key layout (historical)

The prepared build uses the requested order: **1 Ply/Stp, 2 Trim/Zone toggle,
3 Fine/Full, 4 Exit**. Playback behavior is unchanged; the displayed label
is now `<Ply/Stp>`, and the `Too short` message also moves to key 1.
The numeric editor is unchanged. BENCH 03 is preserved in
`build/mods/wavebench03-preserved/`. BENCH 04 is prepared for emulator review;
USB remains on BENCH 03.

**PROVEN:** 5 capture-profile and 8 playback regressions pass, along with
171 boot-slice checks and the independent complete FAT/MZ/ROM/relocation check.
The four-file disk retains STARTUP.SYS, SINE441.SND, STEREO1.SND and DRUMS.SND.
Numeric-entry code is unchanged; its 9 BENCH 03 tests were not rerun.

- SYS SHA-256: `253587fcd359e8521d858ef9e77103d0443b64d3dd8598e084a3b6ccccb66227`
- IMG SHA-256: `d208d2c300ce294211a6845e9720230494634ba7157695dfadcd6741459a40ba`
- Release record: `build/mods/wavebench04-preserved/WAVEHW-validation.json`.
- Emulator preview of this exact disk: `build/emu/wavebench04-preview/`.
  The disk boots, loads DRUMS and displays Full at 81 s and Fine at 85 s.
  Its SHA-256 is unchanged after the run. Enlarged LCD crops are
  `full-display.png` and `fine-display.png` in that directory.

**UNDETERMINED:** BENCH 04 physical display and panel behavior await hardware observation.

## BENCH 03: stock numeric entry and Play X (historical layout)

**PROVEN (IMG_4810 and user report):** DRUMS displays as expected; Peter reports
that full and Fine waveform editing performs correctly. See
`evidence/2026-10-01-wavehw-drums-result.json`. That observation is for
BENCH 02; it does not qualify the new numeric-entry or audition paths.

BENCH 03 adds the requested stock numeric editor and visible-selection
audition. A scoped timing correction removes the stock 30 ms early cutoff
for WAVE calls only. BENCH 03 passed the final emulator checks and is now
installed in USB slot 1; the deployment record is below.

- Select Start or End with Left/Right. A digit opens the actual stock time
  editor and begins entry in seconds; Enter opens it without changing a value.
  Right advances through seconds, milliseconds, and samples. Enter commits
  and returns to the waveform. Soft key 4 cancels the current draft.
  Components already committed with Right remain committed.
- Soft key 1 switches the active Trim/Zone pair. Both pairs support numeric entry.
- Soft key 2, **Play X**, starts the highlighted range intersected with the
  visible window. Full view plays the selected range; Fine view plays only
  its visible portion. The stock 10 ms timer gives an approximate cutoff;
  ranges below two playback ticks (about 20 ms at original pitch) show
  `Too short` without starting. Another press stops playback through stock Ply/Stp.
  The stop routine stops all active voices, matching the stock behavior.
- Soft key 3 switches Fine/Full; soft key 4 exits. Stereo View L/R remains
  a display choice; audition uses the sound's normal mono/stereo player.
- Pads retain their existing behavior. Their earlier normal-note event is
  already queued before the waveform input loop sees a pad notification;
  a safe audition-only interception has not been established.

Implementation and address evidence: [numeric entry](wave_numeric.md),
[playback](wave_playback.md). The startup guard remains exact comparison
against the captured high-ROM bytes. BENCH 02 rollback files are preserved
in `build/mods/wavebench02-preserved/`.

**BENCH 02 physical results (historical build):** IMG_4806/4807 show Start
000.000.16 in the waveform view and matching Soft st after exiting to
stock Edit Sound. Peter reports editing works. See the final evidence
section below; disk persistence and broader editing cases remain open.

**Latest hardware result — PROVEN (IMG_4805.JPG, one execution):**
Fine view is displayed at Zoom 16 with Start selected at 000.000.00.
Individual sine cycles appear to the right of the center; the left half
is a flat zero line. This agrees with the centered window: the left half
is before sample zero, and the right half covers 1,920 samples (about
19.2 cycles). Evidence: [fine-view photo](evidence/2026-10-01-wavehw-fine.jpg)
and `evidence/2026-10-01-wavehw-fine-result.json`. Full-view display was
previously observed in IMG_4803.JPG. Both are qualitative photo checks.
Up/Down zoom changes, wheel edits, exit/reopen, audition, stereo identity
and timing remain open.

**Current hardware state:** ROMDUMP completed and its returned file was
verified against every previous physical checksum/comparison result.
The image and 32 KiB capture are preserved under
`build/hardware/2026-10-01-romdump/`. It contains 2,494 bytes different
from the generic reference, including incompatible startup and shared
entry layouts. See the [returned capture](rom_compatibility.md#returned-physical-romdump-capture).
ROMAPP also completed and returned a verified 336 KiB application/data
capture (word sum 7DBA). The capture-specific WAVEHW profile passed five emulator regressions
and independent layout/relocation review. The current slot-1 build is
`WAVE BENCH 03`, with the new controls described above. See [the profile mapping](wave_physical_profile.md).
Full and fine views are now observed physically. Remaining steps below
are still pending on this ROM variant.

Target: Vailixi OS 3.50, Route A, on Peter's MPC3000 with FlashFloppy.
The canary result below is historical; the new waveform photograph
provides separate evidence of the custom view executing.

## Physical canary result

**PROVEN (user report + photo, one hardware execution):** the physical LCD
displays `Vailixi 3.51 (---/--/----)`, the Route B canary marker. Peter
reports booting it from FlashFloppy's selected `Disk_01.IMG`.
The original photo is preserved as
[`evidence/2026-10-01-canary.jpg`](evidence/2026-10-01-canary.jpg), SHA-256
`5608a001c6bd2df41ef9807af5e91ea4b8bbe1d6fdda5748b8bc2f5e7e5c6088`.

The mounted USB image and the local canary image were re-read on October 1:

- Image size: 1,474,560 bytes (1.44M FAT12).
- SHA-256: `ce025a0cae336acc8c91e1a073f4008159e3c17e0f87b61a7d9784c68ad59b58`.
- MD5: `5841e908dfa7ef8c64d4355d49887f58`.
- Payload: sole SYS `STARTUP.SYS`, 288 bytes.
- USB configuration: `host = akai`, `interface = ibmpc-hdout`,
  `pin34 = rdy`, `write-protect = no`, `write-drain = eot`.

This establishes that the canary's floppy-load/execute/text-output chain
works on this setup. Exact timing, a power cycle without the canary,
other drive configurations, and waveform graphics remain **UNDETERMINED**.
The photo is a still frame, not a timing or bus trace. Peter also reports
testing OS 3.16 upload before the canary; its complete result is not
documented by this photo.

## Review and changes

**PROVEN (code):** the original waveform wheel step was an unsigned
16-bit value that `move` sign-extended with `CWD`. At lengths of
7,864,320 frames or more, full-view `+` could move backward; at still
greater lengths the step also saturated at `0xFFFF`. `step` now returns
`DX:AX = max(1, length / 240)`, and subtraction negates the complete
32-bit value. Fine-view steps remain 1–64 samples.

**PROVEN (code):** the graphics font has 95 glyphs, codes `0x20–0x7E`.
The renderer now replaces other non-NUL bytes with `?`, keeping names
inside the font table. NUL still terminates a string.

**PROVEN (bounded code walk):** `CF92:000C` preserves SI, DI, BP, and DS
on its returning path. `PUSHA` at `002E` pairs with `POPA` at `0142`;
the frame BP is restored at `0146` before `RETF` at `0147`. The only
local called helpers, `0148` and `0163`, each have one `RETF`, no nested
calls, and no DS writes. The wait for DMA completion remains unbounded;
this register contract does not prove hardware completion.

Address forms for that walk (XA=1):

| Object | Linear file | CS:IP | 20-bit | 24-bit, second PGR | 24-bit, Route A third PGR |
|--------|-------------|-------|--------|-------------------|--------------------------|
| Reader | `0x4F92C` | `CF92:000C` | `0xCF92C` | `0x0CF92C`, slot 51=`0x0033` | `0x3CF92C`, slot 51=`0x00F3` |
| Helper | `0x4FA68` | `CF92:0148` | `0xCFA68` | `0x0CFA68`, same slot | `0x3CFA68`, same slot |
| Helper | `0x4FA83` | `CF92:0163` | `0xCFA83` | `0x0CFA83`, same slot | `0x3CFA83`, same slot |
| Wave code | `0x707D0` | `F07D:0000` | `0xF07D0` | `0x0F07D0`, slot 60=`0x003C` | `0x3F07D0`, slot 60=`0x00FC` |

The reader walk used `tools.v53_decode.follow_local` with no limit hit
(130 instructions for the reader, 16 per helper). Each instruction was
inspected separately; no generic disassembler stream crossed BRKXA/RETXA.

Remaining boundaries: shared framebuffer writers/aliases, actual LCD
graphics/pixel order, wave transfer completion and speed, physical stereo
plane identity, and all-path code-cave non-use. See
[`waveform_engine.md`](waveform_engine.md). Begin with the short included
sounds; a full view scans the entire selected plane and has no cancel
poll inside the scan.

## Current build and payload

```sh
python3 mods/build_wave_physical.py --sound build/samples/DRUMS.SND
```

Requires both hash-pinned physical captures. Outputs `build/mods/WAVEHW.img`
and `WAVEHW.json`. The 343,376-byte WAVEHW payload is the image's sole SYS,
`STARTUP.SYS`; its SHA-256 is
`439123b45e9a69bb8b5ae66db17dff2d874e258182ec3a06eadf4ab43881e5be`.
The deployed BENCH 03 image SHA-256 is
`e1756e253140d0a157ff8ffa4d75f6e157e9350dcdf42a99e6c32cadf6d56e62`.

| Sound | Length | Expected shape |
|-------|--------|----------------|
| `DRUMS.SND` | 1.271 seconds, stereo | Lossless conversion of the supplied drum WAV |
| `SINE441.SND` | 1.250 seconds, mono | Half-second sine, half-second silence, quarter-second rising ramp |
| `STEREO1.SND` | 0.750 seconds, stereo | A/L: sine then silence; B/R: silence then falling ramp. Physical L/R assignment remains a hypothesis |

The RAM version/date object says `WAVE BENCH 03`; captured license/serial
text is preserved. Marker: linear `210F5`, `8010:10F5`, 20-bit `811F5`,
24-bit `3811F5` under XA=1 third PGR. Seeing it proves patched DGROUP
loaded; opening the wave view proves the feature hook executed.
The generic BENCH 01 build and earlier deployments below are historical.

## BENCH 04 bench sequence (after installing the new image)

1. Put the USB in FlashFloppy with the MPC powered off, then power on the
   MPC. FlashFloppy receives power at the same time. The prepared USB
   uses `Disk_01.IMG`, containing the waveform `STARTUP.SYS`, selected
   in `IMAGE_A.CFG` before insertion. Photograph the
   `WAVE BENCH 04` marker. Wait for Play/Record; if the OS is waiting
   for a SCSI disk, its `<Cancel>` soft key can dismiss that search.
2. Disk → `7` (Load, erase, rename), choose `SINE441`, then `<Load>`.
   These sounds do not load automatically at boot.
3. Program/Sounds → `6` (Edit Sound), select `SINE441`, press Help.
   Photograph the waveform. It should have sine, flat, and ramp sections.
4. Turn the wheel a few clicks. Left/Right select start/end;
   soft key 2 toggles the Trim/Zone pair. Check that points stay ordered and
   within the sound. Edits take effect immediately in RAM; `<Exit>` does
   not undo them. These keys edit points; they do not destructively trim
   or delete sample data.
5. `<Fine>` opens the close view. Up/Down change zoom (1–64 samples per
   column); the wheel changes the selected point by that many samples.
   `<Full>` returns to the whole sound.
6. On Start or End, press a digit or Enter to open the stock numeric
   editor. Right advances seconds / milliseconds / samples; Enter commits
   and returns to the wave. Soft key 4 cancels the current draft.
7. Soft key 1 / `<Ply/Stp>` auditions the highlighted visible range; press it
   again to stop. Check Full, Fine at both endpoints, and a Zone. Very short
   intervals show `Too short`; zoom out or widen the range. `<Exit>` or Help
   returns to Edit Sound, where the edited points should agree.
8. Load `STEREO1` through Disk, select it on Edit Sound, then Help.
   Right twice selects `View`; wheel `+` selects R and `-` selects L.
   Confirm the two different shapes in full and fine views.
9. Check Main Screen and Disk from the wave view, then reopen it.
   Note any accidental Record Ready state, corruption, or hang.
10. For the separate diskless-reboot observation, power off and remove the
   USB, then power on. Record whether the stock EPROM OS returns without
   `WAVE BENCH 04`, or waits for a floppy. Do not assume FlashFloppy can
   change slots while the MPC is off.

Record the boot marker, LCD photographs, approximate scan latency,
numeric point changes, audition results, and each exit/reopen result.
Use new filenames if saving test edits.

## Earlier generic-profile validation and deployment

**PROVEN (2026-10-01 software checks / MAME executions):**

- `python3 tools/verify_boot_slice.py`: 171 checks pass.
- `python3 -m unittest discover -v`: all 38 tests pass, 74.993 seconds;
  log `build/wave-bench-tests.log`.
- New regressions capture a `+32768` step followed by `-32768` back to
  zero after injecting a long length into the cached view. They test
  wheel arithmetic, not a full 15 MiB wave scan. Empty-sound pixels match
  the reference; Help with no sounds stays in text mode; Main Screen
  exit/reopen and Soft Key 4 return pass.
- Bench-image mono and stereo runs match the independent pixel reference
  at seven sampled full/fine/plane-selection states, with zero differing
  pixels. Traces: `build/emu/wave-bench/` and
  `build/emu/wave-bench-stereo/`. Both return to ordinary Play/Record,
  without Record Ready in these executions.
- The final image's SYS and both SND files were extracted and their
  sizes and SHA-256 values matched `build/mods/WAVEBENCH.json`.

The final 3,656-byte waveform code fits the relocated cave. Initial slot-2
bench image SHA-256 (before the power-on correction below):
`ff9db81df26c4fa36104a287030a8de2b577a7540cfd49235c1e02acd1f0b9fc`.
`WAVE.SYS` SHA-256:
`9f11f3aa5489476a0f9ff59b4833412cb8b1192c3f8346db971707e89aa9267d`.

The initial USB deployment to `Disk_02.IMG` was copied byte-for-byte,
flushed, and re-read with the same image hash. At that time,
`IMAGE_A.CFG` contained `Disk_02.IMG`. Every other
original non-hidden USB file matched its pre-deployment hash, including
the canary in `Disk_01.IMG`. The complete deployment manifest is
`build/usb_backup/wave-bench-2026-10-01/deployment.json`.
The USB was safely ejected after verification.

An earlier baseline suite and isolated run failed loading OS 3.16 under
3.08 EPROMs with type 11h. The fresh final suite passes that case after
rebuilding its test disks. The discrepancy's cause is **UNDETERMINED**;
it is not represented as fixed by this waveform change.

**2026-10-02 cause found (PROVEN in MAME):** that failure was not load- or
emulation-dependent. `emu.mpc3k.disk()` built images with mtools, which stamps
each directory entry with the host clock. With 3.08 EPROMs the creation-time
word at entry `+0Eh` decides whether `M3K316.SYS` loads or the OS stops with
type 11h: one captured failing image failed 8 of 8 boots, and replacing only
that word (or zeroing `+0Ch..+13h`) made it pass. Observed words `2D2Ch` and
`2D73h` fail; `2C82h` and `2D82h` pass. The 3.08 loader's exact rule for that
word is **UNDETERMINED** (not disassembled). `disk()` now normalizes every
image (zero `+0Ch..+13h`, fixed write stamp and volume serial), and parallel
cases no longer share one image file. A real floppy written by a tool that
timestamps entries could hit the same 3.08 behaviour; the builders' own
packer writes zeros there.

### Slot-1 power-on correction

Peter reports that FlashFloppy has no power until the MPC is powered on.
The bench procedure now starts with the USB already inserted and slot 1
prepared; it does not require preselecting a slot on an unpowered drive.

The revised `Disk_01.IMG` contains the **310,640-byte waveform payload**
as `STARTUP.SYS`, plus `SINE441.SND` and `STEREO1.SND`. It is not the
288-byte canary despite sharing the filename. Payload SHA-256 is unchanged
(`9f11f3aa...aa9267d` above). Revised image SHA-256:
`a1aa073e9e062629d8cf651cf21597fc1826ee1acf6fb3b9ae134a189a53d3be`.

**PROVEN (software checks / MAME execution):** the renamed payload matches
the previously validated code exactly, and the revised image shows
`WAVE BENCH 01` at 17 s and Play/Record at 61 s in MAME. Evidence:
`build/emu/wave-bench-slot01/screens.txt`.

The USB copy was flushed and re-read with that image hash.
`IMAGE_A.CFG` now selects `Disk_01.IMG`. The other original USB files,
including `Disk_02.IMG`, match their pre-correction hashes. Pre-correction
backups and the new deployment manifest are in
`build/usb_backup/wave-slot01-2026-10-01/`; its `Disk_01.IMG` is the canary.

## USB rollback

Before deployment, `Disk_01.IMG`, `Disk_02.IMG`, `IMAGE_A.CFG`, and
`FF.CFG` were copied to `build/usb_backup/wave-bench-2026-10-01/`.
`before.json` records SHA-256 for all non-hidden USB files. The original
OS 3.16 image remains at the user's earlier backup,
`build/usb_backup/Disk_01.IMG.m3k316.2026-10-01`.

The corrected deployment targets `Disk_01.IMG` and selects it through
`IMAGE_A.CFG`, because FlashFloppy powers on with the MPC. The canary is
preserved in the backed-up `Disk_01.IMG`. Restoring that file and the
backed-up `IMAGE_A.CFG` restores canary boot. The initial waveform image
in slot 2 and the other slots need not change for this correction.

## Physical start edit and exit

**PROVEN (IMG_4806.JPG and IMG_4807.JPG; user reports editing works):**
custom full view displays Start 000.000.16, and after returning to the
stock Edit Sound page, Soft st also displays 000.000.16. End and Length
remain 001.250.00. This observes the 16-frame start change and its RAM
persistence across exit for this sequence. Saving/reloading from disk,
other point edits, boundaries, stereo and audition are not established.
Evidence: `notes/evidence/2026-10-01-wavehw-edit-result.json`.

## DRUMS added to physical bench disk

At the user's request, `DRUMS.SND` was added to the existing slot-1
waveform image. The 1.271-second stereo sample is a lossless conversion
of the provided 16-bit 44.1 kHz WAV; emulator loading reproduced every
PCM byte. New disk image SHA-256:
`5f2f1d6ed488cdbffdbeebcec0c5713712534eb5b35bc892152b61c8b51c85ca`.
STARTUP.SYS, SINE441.SND and STEREO1.SND are byte-identical to the
previous bench image. Both FATs and all file chains were verified.
Backup and readback deployment evidence:
`build/usb_backup/wavehw-drums-2026-10-01/`. All other USB files and
slot-1 selection are unchanged. Load DRUMS through Disk / 7 / Load,
then select it in Program/Sounds / 6 and press Help.

## Real drum sample follow-up

**PROVEN (user report):** DRUMS looks accurate and waveform editing works
in both full and fine views. IMG_4810.JPG shows the stereo DRUMS full view,
Start 000.010.43, End/Length 001.271.06 and View L. Evidence:
`notes/evidence/2026-10-01-wavehw-drums-result.json`.
The next requested changes are stock numeric entry and audition from
this page, with pads preferred if their existing dispatch can be reused.

## BENCH 03 final validation and USB deployment

**PROVEN (software, 2026-10-01):** the final 343,376-byte WAVEHW payload
passes 21 generic emulator tests, five captured-profile waveform regressions,
nine stock numeric-entry regressions, and eight playback regressions. The
playback release run was serialized (61.934 seconds); an earlier overlapping
test-output run is not counted as evidence. Recorded Fine previews now contain
substantive audio, both endpoints and end-at-sound-length work, short-range
rejection/recovery matches the pixel reference, and stock Ply/Stp retains its
original timing. 171 boot-slice checks also pass.

The image has four files: STARTUP.SYS, SINE441.SND, STEREO1.SND, and DRUMS.SND.
Independent validation checks both FAT copies, complete non-overlapping chains,
all file bytes/hashes, MZ bounds, the exact embedded BIOS comparison array,
only the declared captured-ROM patches, and every relocation word at both
CS=6900 and CS=7000. No file under `07-rom/` was changed.

- SYS SHA-256: `439123b45e9a69bb8b5ae66db17dff2d874e258182ec3a06eadf4ab43881e5be`.
- Image SHA-256: `e1756e253140d0a157ff8ffa4d75f6e157e9350dcdf42a99e6c32cadf6d56e62`.
- Validation: `build/mods/WAVEHW-validation.json`.
- Backup and verified readback: `build/usb_backup/wavebench03-2026-10-01/`.
- BENCH 02 rollback: `build/mods/wavebench02-preserved/`.

Only USB Disk_01.IMG was replaced. IMAGE_A.CFG still selects that slot;
all other non-hidden USB files match the backup inventory. The complete image
was flushed and read back with the hash above, then the USB was safely ejected.
Physical numeric entry and
Play X remain **UNDETERMINED** until the next machine test; the earlier
photographs establish BENCH 02 full/Fine display and editing, not these new
paths. Nominal playback uses the stock 10 ms timer, with a two-tick minimum;
this is not a claim of sample-exact audio cutoff or bounded physical IRQ delay.

## BENCH 05 USB deployment

**PROVEN (software, 2026-10-01):** installed the validated BENCH 05 disk as
`/Volumes/MPC3000/Disk_01.IMG`. The complete flushed readback matches SHA-256
`e39449491b1988730b4e039e49f569eba36d65e8e8fb4b0bd054ef90f322398e`.
`IMAGE_A.CFG` still selects slot 1. All other non-hidden files are unchanged.
The prior BENCH 03 image and configuration are backed up under
`build/usb_backup/wavebench05-2026-10-01/`; its `deployment.json` records the
before/after inventories. USB device disk41 was safely ejected.
