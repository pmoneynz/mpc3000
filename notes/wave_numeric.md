# Stock numeric entry in the waveform view

**Date:** 2026-10-01.  **Implementation:** `mods/wave_numeric.inc`.

The physical evidence image is
`build/hardware/2026-10-01-romapp/ROMAPP.BIN` (336 KiB, linear file
`[0x20000,0x74000)`).  Its code was read as the interleaved application
image, not as either chip.  The stock routines below have the same `CS:IP`
in the generic image and in this capture.  DGROUP operands in the capture
are two bytes below the generic Vailixi image.

For the source evidence addresses below, XA=1 with the second PGR maps each
listed logical application page to the same-numbered ROM page, so the 24-bit
address is `0x0` plus the 20-bit address.  When the floppy loader runs WAVE,
XA=1 with the third PGR maps the copied application/DGROUP pages into RAM,
so the corresponding application address starts with `0x3` instead.  The
high BIOS slots remain mapped to ROM.

## Stock routines used

| Purpose | Linear file | `CS:IP` | 20-bit | 24-bit source / WAVE runtime | Status |
|---|---:|---:|---:|---:|---|
| select a field record | `0x3066B` | `B060:006B` | `0xB066B` | `0x0B066B` / `0x3B066B` | **PROVEN** |
| initialize its parser/display state | `0x3081C` | `B060:021C` | `0xB081C` | `0x0B081C` / `0x3B081C` | **PROVEN** |
| commit the active entry buffer | `0x30D15` | `B060:0715` | `0xB0D15` | `0x0B0D15` / `0x3B0D15` | **PROVEN** |
| stock numeric key parser | `0x331B7` | `B31B:0007` | `0xB31B7` | `0x0B31B7` / `0x3B31B7` | **PROVEN** |
| clamp, draw, and write one numeric value | `0x333C4` | `B31B:0214` | `0xB33C4` | `0x0B33C4` / `0x3B33C4` | **PROVEN** |
| redraw fields 0 through 16 | `0x3B05B` | `B99A:16BB` | `0xBB05B` | `0x0BB05B` / `0x3BB05B` | **PROVEN** |
| components to frames | `0x3BFB9` | `B99A:2619` | `0xBBFB9` | `0x0BBFB9` / `0x3BBFB9` | **PROVEN** |
| frames to components | `0x3C00D` | `B99A:266D` | `0xBC00D` | `0x0BC00D` / `0x3BC00D` | **PROVEN** |
| enqueue the already-read digit | `0x56E75` | `D6E0:0075` | `0xD6E75` | `0x0D6E75` / `0x3D6E75` | **PROVEN** |
| normalized key input | `0x3DE3E` | `BDE3:000E` | `0xBDE3E` | `0x0BDE3E` / `0x3BDE3E` | **PROVEN** |
| leave graphics for character mode | `0x45089` | `C4C8:0409` | `0xC5089` | `0x0C5089` / `0x3C5089` | **PROVEN** |
| enter graphics and blit | `0x45BDF` | `C4C8:0F5F` | `0xC5BDF` | `0x0C5BDF` / `0x3C5BDF` | **PROVEN** |

The source 24-bit addresses use second-PGR slots 44, 46, 47, 49, and 53
(`0x002C`, `0x002E`, `0x002F`, `0x0031`, and `0x0035`).  The WAVE-runtime
forms use the corresponding copied pages in the third PGR.  The physical
capture and generic image use the same instruction addresses for these
routines; only the named DGROUP operands differ.

`B99A:16BB` starts `PUSH BP / MOV BP,SP`, owns its two-byte loop variable,
and ends in `LEAVE / RETF` at `B99A:16DE`.  **PROVEN:** it is a standalone
far routine and does not borrow the suspended page's `BP`.  Its field records
already contain far pointers into that page's stack frame, which is why the
wrapper saves the original page `BP` separately only for calls to
`B99A:2619` and `B99A:266D`.

## Character-screen save and restore

`B1B1:004F` (linear `0x31B5F`, 20-bit `0xB1B5F`, source/runtime 24-bit
`0x0B1B5F` / `0x3B1B5F`) calls `INT 43` with AX=5.  `B1B1:0055` (linear
`0x31B65`, 20-bit `0xB1B65`, source/runtime 24-bit `0x0B1B65` /
`0x3B1B65`) calls it with AX=6.  **PROVEN.**  The interrupt dispatcher at
`F800:16AA` loads `DS=ES=0040` before selecting the service.

- AX=5 is `F800:1808`, linear `0x79808`, 20-bit `0xF9808`, 24-bit
  `0x0F9808` under the high ROM slots.  It copies `0x140` bytes from
  `0040:662B` to `0040:676B` and saves the cursor.  Those buffers are 20-bit
  `0x06A2B` and `0x06B6B`; under the second/third PGR RAM mapping they are
  24-bit `0x306A2B` and `0x306B6B`.
- AX=6 is `F800:181B`, linear `0x7981B`, 20-bit `0xF981B`, 24-bit
  `0x0F981B`.  It replays all 320 saved character cells through the stock
  glyph path and restores the saved cursor.

This establishes the software lifecycle.  Pixel behavior on the physical
LC7981/display remains **UNDETERMINED** and is part of the deferred hardware
observation.

The waveform entry saves the Edit Sound shadow before the first graphics
transition.  `stock_numeric` calls `C4C8:0409`, restores that saved shadow,
and redraws the live stock fields.  A normal or cancelled dialog redraws the
wave and calls `C4C8:0F5F` before returning AX=0.  A mode key returns with
character mode still active so the outer page can pass the key to the stock
mode switch.

## Bounded three-field editor

The Edit Sound time values are three distinct fields, not one composite
string.  Their field indices and suspended-page component triples are:

| Wave point | fields (seconds, ms, samples) | triple relative to page BP |
|---|---:|---:|
| soft start | 1, 2, 3 | `-0x18` |
| soft end | 7, 8, 9 | `-0x1E` |
| zone start | 4, 5, 6 | `-0x0C` |
| zone end | 10, 11, 12 | `-0x12` |

The triple layout is samples at `+0`, milliseconds at `+2`, and seconds at
`+4`.  **PROVEN** from the B99A record constructors and the consumers at
`B99A:2619/266D`.  Widths and maxima are respectively 3/999, 3/999, and
2/43.

`B31B:0007` returns 0 when a digit or backspace is consumed.  An idle Left
returns action `0x0400`; a typed Right first calls `B060:0715` and returns
`0x0800 + field`; an idle Right returns `0x0800` without changing the value.
Enter is handled by calling `B060:0715` directly.  **PROVEN** from the paths
at `B31B:00F7`, `0104`, and `B060:0715`.

The wrapper interprets those actions itself and selects only the three fields
belonging to the point that opened it.  Left on seconds stays on seconds;
Right past samples closes the dialog.  Thus the stock parser, buffer,
backspace, clamp, rendering, and write-back routines are reused without
giving the stock all-page navigation loop an opportunity to enter field 0 or
another point.  This bound is **PROVEN** for the wrapper's direct action
dispatch; physical key behavior remains to be observed on hardware.

`BL=0` opens the seconds field without queued input, allowing Right to select
milliseconds or samples.  A nonzero BL is an ASCII digit already consumed by
the graphics loop; `D6E0:0075` enqueues it through `FB00:0672`, and the first
`BDE3:000E` read consumes it.  **PROVEN** for the software queue path.

## BENCH 06 End-to-Zone shortcut

Up from any numeric component of either End point accepts that component,
returns to graphics, and selects the current zone number. It preserves the
other two time components. An idle Up performs no frame conversion. Down
from the zone number or count returns to End for continued wheel or numeric
editing. This is an explicit exit from the bounded numeric dialog, not native
navigation into an unrelated field. Start numeric entry remains bounded as
before. See `emu/test_wave_zone_navigation.py`.

## Frame commit and the 44-sample edge

On a typed commit, `B99A:2619` converts the selected triple to DX:AX frames.
The wrapper subtracts the selected point's current frame value and passes the
signed delta to the waveform view's existing `move`, which enforces the pair
and sound-length bounds.  It then regenerates all four triples with
`B99A:266D` and redraws the stock fields.  This connection of editor output
to the actual point is **PROVEN** by the implementation and stock ABIs; MAME
and physical interaction tests are separate observations.

`B99A:266D` can represent frame 44099 as 0 seconds, 999 ms, 44 samples, while
the sample field's explicit maximum is 43.  `B99A:16BB` redraw therefore
clamps the temporary component to 43.  The wrapper records whether the stock
entry buffer was active before Enter or Right.  Idle Enter/Right never calls
the frame commit path, so opening, navigating, or cancelling at frame 44099
does not change the actual dword.  **PROVEN** from the state and call graph.
The exact-value emulator regressions below pass; the equivalent physical-panel
run remains unobserved.


## Executed regression

**PROVEN (MAME composite fixture, one execution per case):**
`python3 -m unittest emu.test_wave_numeric -v` passed 9/9 checks in
99.196 seconds. Cases cover cancelling a typed draft, idle Enter and idle
Right navigation at frame 44099, Start clamped to End, End clamped to Start,
bounded field navigation, a mode-key exit that discards the draft, ignored
numeric input on View L/R, and the generic reference's NUM_EDITING layout.
The generic entry sequence 0 seconds / 10 milliseconds / 43 samples produces
484 frames. Root's separate physical-profile basic run also produces 484
and preserves it on exit to stock Edit Sound.

Test artifacts: `build/emu/wave-numeric-tests/` and
`build/emu/wavebench03-numeric-basic/`. The tested WAVEHW payload was
assembled from the current sources into a temporary test directory, leaving
the deployable artifacts untouched. Its SHA-256 is
`439123b45e9a69bb8b5ae66db17dff2d874e258182ec3a06eadf4ab43881e5be`.
Generic WAVE payload SHA-256:
`97e92a555ba9c34f754c9de01a19da53ab0f43c46b1910ab625a0f45beda4c0a`.
The composite fixture borrows uncaptured ROM holes as documented in
[the physical profile](wave_physical_profile.md); this is software evidence,
not physical-keyboard or LCD qualification.
