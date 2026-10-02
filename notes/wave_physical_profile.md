# Physical Vailixi 3.50 WAVE profile

**Profile constant:** `WAVE_CAPTURE_20261001`

This profile is for the personalized Vailixi 3.50 captures returned on
2026-10-01.  It is not a generic "3.50" profile.

## Captured inputs and boundary

| Object | Captured linear-file range | Bytes | SHA-256 | Word sum |
|---|---:|---:|---|---:|
| `ROMAPP.BIN` | `[0x20000,0x74000)` | `0x54000` (344,064) | `bc1dd8cd6d59714c1a1b0d4f5145df26a2cfec8be14ca0787f9cbef8c22be1e2` | `0x7DBA` |
| `BIOS.BIN` | `[0x78000,0x80000)` | `0x08000` (32,768) | `2c654334e011af2943d1d08f05e3ce48ebccdf49600aab7a2f040ba016c21168` | `0x81A0` |

The generic emulator comparison fixture for `[0x20000,0x74000)` is
`build/emu/romapp-vailixi/ROMAPP.BIN`, SHA-256
`355d23c0b9f9b37a96588b03b5a6457abd3ef1eb111424650fd3667f11833b68`.
It is comparison evidence, not physical firmware.

**UNDETERMINED:** linear-file `[0x00000,0x20000)` and
`[0x74000,0x78000)` were not captured.  Concatenating the two physical
captures with generic bytes or fill in those holes creates a composite,
not a physical 512 KiB ROM image.  Route A needs the captured DGROUP,
application code, and high BIOS ranges above; that limited sufficiency
does not close the two holes or establish whole-ROM identity.

## Address mode

The returned high BIOS supplies the third PGR at linear file `0x7ADCF`.
Its relevant words are `PGR[32]=00E0`, `[35]=00E3`, `[36]=00E4`,
`[40]=00E8`, `[41]=00E9`, `[42]=00EA`, `[60]=00FC`, `[61]=0140`,
`[62]=003E`, and `[63]=003F`.

With XA=1 and that table:

- DGROUP `8010:off` has 20-bit address `0x80100+off` and, throughout
  the objects below, 24-bit address `0x380100+off`.
- `A2AE:0000` is 20-bit `0xA2AE0`, 24-bit `0x3A2AE0`.
- `A2AE:4800` is 20-bit `0xA72E0`, 24-bit `0x3A72E0`.
- Relocated application code at 20-bit `0xB0000-0xF3FFF` is at the
  corresponding 24-bit `0x3B0000-0x3F3FFF`.
- High BIOS `F800:0000-7FFF` is linear file `[0x78000,0x80000)`,
  20-bit `[0xF8000,0x100000)`, and 24-bit
  `[0x0F8000,0x100000)` through slots 62/63.

These are address translations, not claims about PAL or device behavior.

## Personalization and DGROUP boundary

**PROVEN:** the physical and generic images are byte-identical through
file `0x210F4`.  The first aligned difference is the personalized date at
`0x21103`.  The string objects are:

| Object | Physical linear file | Runtime | 20-bit | 24-bit, third PGR | Physical bytes |
|---|---:|---:|---:|---:|---|
| Version/date | `[0x210F5,0x21110)` | `8010:10F5` | `0x811F5` | `0x3811F5` | `Vailixi 3.50 (JUN/28/2008)\0` (27 bytes) |
| License | `[0x21110,0x21129)` | `8010:1110` | `0x81210` | `0x381210` | `Licensed To: Tobias Thon\0` (25 bytes) |
| Serial | `[0x21129,0x2113D)` | `8010:1129` | `0x81229` | `0x381229` | `Serial: A9645-47901\0` (20 bytes) |

Generic 3.50 instead has a 27-byte license at `[0x21110,0x2112B)` and a
20-byte serial at `[0x2112B,0x2113F)`.  Therefore the following physical
string, `System Information`, starts at `0x2113D`; the generic one starts
at `0x2113F`.

**PROVEN:** from physical file `0x2113D` through the DGROUP end, the
structural alignment is generic offset minus two.  Comparing the aligned
ranges leaves 370 differing bytes.  Every one is accounted for by 367
little-endian word locations whose physical value is the corresponding
generic value minus two.  Their meanings require consumers; this is not
a blanket assertion that every word is a pointer.  It does establish
that copying generic DGROUP and adjusting only the WAVE constants would
be wrong.  The profile must use the captured bytes.

The reset operands in the captured BIOS establish:

- copied source: linear file `[0x20000,0x27C90)`;
- destination: `8010:0000-7C8F`;
- zeroed BSS: `8010:7C90-FFB5` (`[0x7C90,0xFFB6)` offsets);
- initialization-record segment: `F076`, whose table is at physical
  linear file `0x70764`.

The generic bounds `0x27C92`, `7C92`, `FFB8`, and `F07A` do not apply.

The bench marker must not use the old generic patch at file `0x21110`:
that range is the customer's license and reaches the physical serial
boundary.  `WAVE_CAPTURE_20261001` instead replaces the same-length
27-byte version object at `[0x210F5,0x21110)` with the marker text that
`mods/WAVE.args` plants at `0x21110` (currently `WAVE BENCH 06`), padded
with NUL bytes.  This preserves the license and serial objects.

## WAVE RAM objects

The physical equivalents used directly by `mods/wave.asm` are:

| Meaning | Generic offset | Physical offset | Runtime | 20-bit | 24-bit, third PGR | Evidence |
|---|---:|---:|---:|---:|---:|---|
| Mixer framebuffer, `0x780` bytes | `1591` | `158F` | `8010:158F` | `0x8168F` | `0x38168F` | all seven generic consumer operands change to `158F`; captured source `[0x2158F,0x21D0F)` is exactly 1,920 zero bytes |
| transfer busy counter | `9757` | `9755` | `8010:9755` | `0x89855` | `0x389855` | 107 generic raw operand occurrences have physical `9755`; Best-st consumer at file `0x3C424` changes only this operand |
| current option | `D7CA` | `D7C8` | `8010:D7C8` | `0x8D8C8` | `0x38D8C8` | Edit Sound entry file `0x399B5` stores 6 to `D7C8` |
| current mode | `D7CB` | `D7C9` | `8010:D7C9` | `0x8D8C9` | `0x38D8C9` | physical consumers use `D7C9`, including the field-editor path used by the Help gate |
| zone end dword | `EDB7` | `EDB5` | `8010:EDB5` | `0x8EEB5` | `0x38EEB5` | Edit Sound consumers at files `0x39C50` onward use low/high words `EDB5/EDB7` |
| zone start dword | `EDBB` | `EDB9` | `8010:EDB9` | `0x8EEB9` | `0x38EEB9` | Edit Sound consumers at files `0x39B1A` onward use low/high words `EDB9/EDBB` |
| field index (supporting page state) | `7D79` | `7D77` | `8010:7D77` | `0x87E77` | `0x387E77` | physical field-editor operands |
| graphics-active flag (owned by stock graphics routines) | `98DC` | `98DA` | `8010:98DA` | `0x899DA` | `0x3899DA` | physical `C4C8` enter/exit consumers |

The BSS objects have no initialized byte object in `ROMAPP.BIN`; reset
zeros them from the captured `7C90` boundary.  The operand consumers are
the evidence for their personalized offsets.

## Sound-record ABI and tables

**PROVEN:** the sound workspace is not displaced by the DGROUP deletion.
The physical image retains:

- read buffer `A2AE:0000-47FF`, 0x2400 words, 20-bit
  `[0xA2AE0,0xA72E0)`, 24-bit `[0x3A2AE0,0x3A72E0)`;
- 128 records at `A2AE:4800 + index*0x24`, 20-bit
  `[0xA72E0,0xA84E0)`, 24-bit `[0x3A72E0,0x3A84E0)`;
- record `+00` 16-byte name, `+13` stereo byte, `+14/+18` soft-start/end
  dwords, `+1C` length dword, and `+20` wave-RAM word-address dword.

The following physical and generic instruction ranges are byte-identical:

| Consumer | Linear-file range | What it establishes |
|---|---:|---|
| `B99A:0096` | `[0x39A36,0x39A4D)` | multiply index by `0x24`, add `0x4800`, segment `A2AE` |
| `B99A:0169` | `[0x39B09,0x39B1A)` | record length at `+1C/+1E` |
| `B99A:0685` | `[0x3A025,0x3A039)` | soft-start at `+14/+16` |
| `B99A:0788` | `[0x3A128,0x3A13C)` | soft-end at `+18/+1A` |
| `B99A:16F8` | `[0x3B098,0x3B0A9)` | stereo byte at `+13` |
| `B99A:2A7A` | `[0x3C41A,0x3C45B)` | Best-st buffer/plane read; only the embedded busy-counter word differs (`9757` to `9755`) |
| `B99A:2619` | `[0x3BFB9,0x3C00D)` | frame/time conversion body is byte-identical |

The raw-panel translation table `D547:0006`, file
`[0x55476,0x554D8)`, is byte-identical between physical and generic
images (98 bytes, SHA-256
`0448ad5366abd484ebabc180ab936d14c1bfe87d1cbf3efcd21707c6cab10d88`).
Thus the Help, soft-key, arrow, wheel, and mode character values consumed
by WAVE are unchanged.  The 5x7 font and WAVE labels are assembled into
the WAVE cave from `mods/wave_font.inc` and `mods/wave.asm`; they are not
addresses into an OS font or OS string table.

## Code surfaces used by WAVE

Independent physical mapping found the WAVE patch sites, continuations,
far-call entries, and cave at the same CS:IP and linear-file addresses as
generic 3.50.  Under XA=1 with the third PGR they are:

| Surface | Linear file | CS:IP | 20-bit | 24-bit |
|---|---:|---:|---:|---:|
| Help hook | `0x30A22` | `B060:0422` | `0xB0A22` | `0x3B0A22` |
| Help continuation | `0x30A28` | `B060:0428` | `0xB0A28` | `0x3B0A28` |
| ordinary-key continuation | `0x30A59` | `B060:0459` | `0xB0A59` | `0x3B0A59` |
| return-key continuation | `0x30CE2` | `B060:06E2` | `0xB0CE2` | `0x3B0CE2` |
| page hook | `0x3A1FA` | `B99A:085A` | `0xBA1FA` | `0x3BA1FA` |
| Do continuation | `0x3A493` | `B99A:0AF3` | `0xBA493` | `0x3BA493` |
| page-exit continuation | `0x3AF35` | `B99A:1595` | `0xBAF35` | `0x3BAF35` |
| reopen Edit Sound | `0x56E75` | `D6E0:0075` | `0xD6E75` | `0x3D6E75` |
| filtered key input | `0x3DE3E` | `BDE3:000E` | `0xBDE3E` | `0x3BDE3E` |
| graphics enter/blit | `0x45BDF` | `C4C8:0F5F` | `0xC5BDF` | `0x3C5BDF` |
| graphics re-blit | `0x45B8D` | `C4C8:0F0D` | `0xC5B8D` | `0x3C5B8D` |
| text-mode restore | `0x45089` | `C4C8:0409` | `0xC5089` | `0x3C5089` |
| wave transfer | `0x4F92C` | `CF92:000C` | `0xCF92C` | `0x3CF92C` |
| cave start | `0x707D0` | `F07D:0000` | `0xF07D0` | `0x3F07D0` |

The physical old-byte signatures must still be checked by the builder at
both hook sites and across the exact cave span selected for the assembled
payload.  A matching address alone is not a compatibility proof.

## Build requirements and remaining boundaries

`WAVE_CAPTURE_20261001` must:

1. require the exact `ROMAPP.BIN` and `BIOS.BIN` sizes and SHA-256 values
   above before assembling or emitting output;
2. construct DGROUP from captured `[0x20000,0x27C90)` and code from
   captured `[0x30000,0x74000)`;
3. use the physical RAM constants in the table above;
4. preserve the license and serial, using only the 27-byte version object
   for the bench marker;
5. verify physical hook old bytes and cave fill before patching;
6. embed or check the physical high-BIOS identity rather than accepting a
   generic 3.50 checksum;
7. describe any generated 512 KiB diagnostic/comparison image as a
   composite with the two uncaptured holes.

`mods/build_wave_physical.py` meets these and also (software checks, run on
every build):

- generates its hook list from `mods/WAVE.args` through an explicit
  translation: the marker relocation above; DGROUP data patches only by a
  declared move that equals generic minus two from `0x2113F` (today
  `0x25E92 -> 0x25E90`); DGROUP word operands inside hook old bytes only
  where declared with their generic value (today `0x39A03`+3 `E40A`;
  `0x39E0D`+2/+9/+20 `EDB5`, +16 `35A2`, +24 `3781`; `0x3A49F`+1 `EDB5`).
  Code-patch new bytes must be `EA`/`9A` to a cave label plus NOP fill, or
  a reviewed verbatim entry (`0x488B6` `6A 0A`).  The translated old bytes
  are then verified against the captured image;
- checks every direct far CALL/JMP in the assembled capture cave (found at
  NASM-listed instruction boundaries; indirect far transfers are rejected).
  The capture and generic caves are paired transfer by transfer.  Each
  captured target must equal its generic target, or be the documented AMX
  translation (BIOS window, linear minus `0xA`), and the 64 bytes at the
  captured target must equal the 64 bytes at the generic target except for
  DGROUP word operands (generic `>= 113F`, captured = generic − 2) and far
  pointers into the BIOS window shifted by `−0xA`.  Targets outside captured
  OS code/BIOS, or in captured code at linear `[0x6B700,0x70800)`, fail.
  The current cave has 84 far transfers to 60 distinct targets; 59 are the
  same `CS:IP` in both images and one is `FB00:06B9 -> FB00:06AF`
  (`QUEUE_UNGET`, linear `0x7B6B9 -> 0x7B6AF`).  None is flagged.  The list
  is in `build/mods/WAVEHW.json` under `far_targets`.  This is a byte
  comparison of entry windows, not an all-paths proof of the routines;
- checks the guarded BIOS's own reset immediates against the shipped DGROUP
  size: `MOV CX,7C90` at `FAC0:0084` (opcode linear `0x7AC84`, immediate
  `0x7AC85`) and `MOV DI,7C90` at `FAC0:013D` (immediate `0x7AD3E`), XA=1,
  third PGR; and checks that the stub's embedded guard bytes have the pinned
  `BIOS.BIN` SHA-256.

Hardware wave-transfer completion and speed, framebuffer aliasing on all
paths, LC7981 glass behavior, stereo plane identity, and physical execution
of the rebuilt WAVE profile remain **UNDETERMINED**.  The captures resolve
software compatibility inputs; they do not constitute that execution.

## Frozen build audit (historical, BENCH 02)

This audit describes the BENCH 02 outputs, not the current build.
Independent read-only inspection of those frozen outputs found no software
build blocker:

- `WAVEHW.SYS` is 343,376 bytes, SHA-256
  `92f73b10139978b8a5c2abe7478cbc45614fa2d9972a0e73836e47048d5e207d`.
- `WAVEHW.img` is 1,474,560 bytes, SHA-256
  `05262e05d4ae2d0ebcaeb3fc247e994bcc6aff92d930adbeb451f21c82a53767`.
- The MZ declaration equals the SYS length.  The body has a `0x809C`-byte
  exact-guard stub, DGROUP at body offset `0x80A0` (`0x7C90` bytes), and
  application code at body offset `0xFD30` (`0x44000` bytes).
- Extracted DGROUP and code equal the captured inputs after applying only
  the 27-byte version marker, the one-byte skip-SYS branch, the two hook
  windows, and the 3,656-byte cave.  No byte outside those five authorized
  spans differs.
- The captured BIOS occurs exactly once in the stub.  The emitted guard
  compares `0x4000` aligned words from `F800:0000`, increments both source
  indexes by two, and finishes before either relocated OS copy begins.
- The BENCH 02 physical cave was the same length as the generic cave and
  differed at exactly eight operand bytes (mode, option, zone start, zone
  end, two busy references, two framebuffer references).  The current
  BENCH 06 caves are both 12,042 bytes and differ at 48 bytes, every one
  inside an operand of a `WAVE_CAPTURE_20261001` constant: `CHOP_OPT_0..9`
  10, `ZONE_ST` 5, `ZONE_EN` 5, `NUM_EDITING` 4, `CHOP_DO` 4, `FB` 3,
  `BUSY` 2, `KEY_REPEAT` 2, `MUTE_PROGRAM` 2, and one each for `MODE`,
  `OPTION`, `LIST_SELECTION`, `KEY_QUEUE`, `QUEUE_UNGET`, `CHOP_DO_LABEL`,
  `MUTE_CURRENT_PROGRAM`, `MUTE_PAD`, `MUTE_NOTE`, `MUTE_NOTE_MIDI`,
  `MUTE_RECORD`.  Labels and instruction lengths are stable.
- For load segment `7000`, the DGROUP source ends at 20-bit `0x7FD30`,
  before destination `0x80100`.  The code source begins at `0x7FD30` and
  the existing high-to-low chunk copy remains overlap-safe.  Segment
  `6900` has more separation.

The five focused profile MAME tests and the independent FAT, extraction,
and both-load-segment relocation checks also passed for BENCH 02.
`WAVEHW.img` is now packed deterministically (zeroed directory times and
`+0C..+13`), so its hash is a function of its inputs; the BENCH 02 image
hash above came from the earlier mtools packer.  These are software
tests; the physical-execution boundaries above remain open.

## Physical display follow-up

**PROVEN (IMG_4803.JPG, one execution):** the WAVEHW-associated custom
full-view screen is visible for SINE441 with the expected duration and
qualitatively correct sine/silence/ramp sections. This supersedes the
pending-first-execution boundary above for that observed path. It does
not establish all-path safety, exact pixel identity, edit/zoom/exit
behavior, stereo identity or timing. See
[evidence](evidence/2026-10-01-wavehw-sine441-result.json).

## Physical fine-view follow-up

**PROVEN (IMG_4805.JPG, one execution):** SINE441 fine view shows Start
selected at zero, Zoom 16, sine cycles right of center, and a flat left
half. The window formula `point + (column - 120) * zoom` places the left
half before sample zero, so this shape is expected. The right half spans
1,920 samples / 19.2 cycles of the period-100 test sine. This is qualitative
photographic agreement. Fine-view entry and Start selection are observed;
Up/Down zoom adjustment, edits, exit/reopen, stereo, audition and timing
remain **UNDETERMINED**. Evidence:
`notes/evidence/2026-10-01-wavehw-fine-result.json`.

## Physical start edit and exit

**PROVEN (IMG_4806.JPG and IMG_4807.JPG; user reports editing works):**
custom full view displays Start 000.000.16, and after returning to the
stock Edit Sound page, Soft st also displays 000.000.16. End and Length
remain 001.250.00. This observes the 16-frame start change and its RAM
persistence across exit for this sequence. Saving/reloading from disk,
other point edits, boundaries, stereo and audition are not established.
Evidence: `notes/evidence/2026-10-01-wavehw-edit-result.json`.

## BENCH 03 additions

The waveform now reuses the captured stock numeric parser and Edit Sound
component records; `NUM_EDITING` is `8010:7D72` in this profile versus
`8010:7D74` in the generic reference. It is runtime BSS, with no initialized
ROM-file byte: 20-bit `0x87E72`, 24-bit `0x387E72` under XA=1 and the third
PGR. See [the numeric-entry ABI and field lifetime](wave_numeric.md).

Play X calls the shared stock sound player at `CFC6:0CE9`, with temporary
bounds equal to the selected Trim/Zone range intersected with the Fine
window (or the entire selected range in Full view), then restores the
sound's saved trim bounds. Stereo playback remains stereo regardless of
the displayed plane. See [the playback evidence](wave_playback.md).

These new interaction paths have emulator checks; physical qualification
of BENCH 03 is separate from the successful BENCH 02 photographs and
reported full/Fine edits. Current test and deployment state is in
[the bench log](waveform_bench.md).

BENCH 03 also declares two guarded instruction replacements in the shared
stock player: file `0x502FD` (`CFC6:069D`, 20-bit `0xD02FD`, 24-bit
`0x3D02FD`) and file `0x504F7` (`CFC6:0897`, 20-bit `0xD04F7`, 24-bit
`0x3D04F7`), XA=1 with the third PGR. They recognize the exact nested return
addresses of WAVE's audition call, skip the stock 30 ms early cutoff for that
call only, and reject stop counts below two ticks before voice allocation.
Other callers execute the original arithmetic and branch flags. The playback
note records the call-frame proof, conservative timing boundary, and tests.
