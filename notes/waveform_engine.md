# Waveform editor: the wave view (phases 2 and 3)

**Image:** Vailixi 3.50 linear, Route A. **Date:** 2026-09-25.
**Source:** [`../mods/wave.asm`](../mods/wave.asm) (2,846 bytes in the code cave at `F07D:0000`),
[`../mods/WAVE.args`](../mods/WAVE.args). Font: [`../emu/lcd_font.py`](../emu/lcd_font.py) → `mods/wave_font.inc`.
**Pixel contract:** [`../emu/wave_ref.py`](../emu/wave_ref.py) `screen()`. Evidence it builds on:
[`waveform_phase0.md`](waveform_phase0.md).

## What it does

1. **Scan.** Reads the sound's plane A from wave RAM.
   - Column `c` (0–239) covers samples `[c·len/240, (c+1)·len/240)`, with at least one sample per column.
   - Each column keeps its signed min and max.
   - Reads go through `CALLF CF92:000C(A2AE:0000, wave + cur, n, 1)` in blocks of `n ≤ 0x2400` words (Best st's buffer and call shape), each wrapped in `INC`/`DEC [8010:9757]`.
2. **Cache.** Two 240-byte arrays in the cave, holding the top and bottom rows of each column's line:
   - top row = `31 − (max >> 11)`
   - bottom row = `31 − (min >> 11)`

   The wave fills rows 16–47 around the zero line at row 31. Rows 0–15 and 48–63 hold text.
3. **Render.** Clears the Mixer framebuffer `8010:1591` (30 bytes × 64 rows, bit 7 = leftmost), draws each column's vertical line, then inverts the columns containing soft start (`+14`) through soft end (`+18`) over rows 16–47. This matches the 2000XL's inverted region.
4. **Show.** `CALLF C4C8:0F5F` enters graphics mode (registers `32/07/1D/3F`) and blits. `CALLF BDE3:000E(0)` waits for a key. `CALLF C4C8:0409` returns to text mode.

## Entry: Help on Edit Sound (phase 3)

| Patch | File | Stock | Mod | Effect |
|-------|------|-------|-----|--------|
| `help_gate` | `0x30A22` (`B060:0422`) | `80 7E FF 48 75 31` (`cmp [bp-1],'H' / jnz 0459`) | `EA {help_gate} 90` | If the key is `'H'` and `[D7CB]='L'` and `[D7CA]=6`, the gate returns it with `SI='H'` through `B060:06E2`. Otherwise it resumes at `0428` (show help) or `0459` |
| `page_key` | `0x3A1FA` (`B99A:085A`) | `3D 75 00 75 03 E9 91 02 E9 30 0D` | `EA {page_key}` + 6 × `90` | Same dispatch (`0x75` → `0AF3`, else → `1595`), plus `'H'` → view. The only branch into the window is its own `jnz` at `085D` (linear decode of `B99A:0002`–`2C00`) |

The view takes the sound index from the page frame, exactly as the Best st handler does:
- The index is `[ss: bp-0BCh + [bp-2]]`.
- With no sound (`DI = -1`), Help does nothing (code; not traced).

When the view closes, `page_key` stores the returned key in `[bp-1]`. For Soft Key 4 or Help it also calls `D6E0:0075('6')` before `B99A:1595`, which reopens Edit Sound as Best st does.

### Screen and keys

The screen uses 6 × 8 text cells:

| Rows | Content |
|------|---------|
| 0 | `Edit Snd:` + name |
| 1 | `Start:` value at col 6, `End:` value at col 24; the selected value's 10 cells are inverted |
| 16–47 | wave, with the columns holding start through end inverted |
| 6 | `Length:` |
| 7 | `<Start>   <End>   …   <Exit>` |

Values use the Edit Sound units `sss.mmm.ss`: `s = f/44100`, `ms = (f mod 44100)·10/441`, then the leftover samples.

| Key (code, from the `D547:0006` table) | Action |
|-----------------------------------------|--------|
| Data wheel, `+`/`-` (`'+'`/`'-'`) | Moves the selected point by one column, `len/240` frames (at least 1). Clamped so that `0 ≤ start ≤ end ≤ len`. Written to `+14`/`+18` at once, then redrawn and blitted (`C4C8:0F0D`) |
| Soft Key 1 `'x'`, Left `'<'` | Select Start |
| Soft Key 2 `'y'`, Right `'>'` | Select End |
| Soft Key 4 `'u'`, Help `'H'` | Back to Edit Sound |
| Mode keys `L M F J G U S l s O K` | Leave the view and pass the key on (the OS switches mode) |
| Anything else, including the Help release `'h'` | Ignored |

## Evidence

All MAME traces, one execution each:

| Test | Result |
|------|--------|
| `test_wave_view_edits_start_and_end`: `SINE441` with start 13,781 / end 48,000. Help, wheel +3, Soft Key 2, wheel −2, Soft Key 4 | The LCD equals `wave_ref.screen` at all four states (80, 82.5, 84, 86.5 s). Edit Sound then shows `Soft st :000.328.04` and `Soft end:001.078.03` (+3 and −2 steps of 229 frames). Help on Play/Record still shows the Help page. **PROVEN (trace)** |
| Phase 2 engine (Best st dev hook, since removed) with a real stereo sample (Peter's `funkySnare.wav`, not in the repo) | 0 pixel differences for plane A. **PROVEN (trace)** |
| Graphics mode | Probe `mode=32`, `30x64`. **PROVEN (trace)** |

Harness fix: `emu/mpc3k.py` `parse_screens` now splits only at lines that start with `@ `. The graphics-mode text dump of a real waveform contained `@ ` mid-line and broke the old split.

## Assumptions and limits

- **Framebuffer reuse:** reusing `8010:1591` while the Mixer is inactive is **HYPOTHESIS**. The Mixer clears and redraws it on entry (`C4C8:0490`). Other writers than `C4C8`/`B13A` are **UNDETERMINED** (computed aliases not searched).
- **Stereo:** only plane A is drawn. That A is the left channel is **HYPOTHESIS**.
- **Scan time on hardware:** `U-PHYS`. Every sample is read through `CF92:000C`.
- **`CF92:000C`:** that it preserves `SI`/`DI`/`BP`/`DS` is **HYPOTHESIS** (C convention). The engine reloads everything else after each call.
- **Keys:** the view ignores keys it does not list. The wheel step is fixed at one column; sample-level edits still need the digit fields (a fine view is phase 4).
- **Clamps:** the view's `0 ≤ start ≤ end ≤ len` may be stricter than the OS field clamps (**HYPOTHESIS**: they were not decoded exhaustively).
- **Glass:** pixel order and graphics mode on the real LC7981 are `U-LC7981` / `U-PHYS`. The register values are the stock Mixer's.
