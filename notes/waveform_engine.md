# Waveform editor, phase 2: the wave view engine

**Image:** Vailixi 3.50 linear, Route A. **Date:** 2026-09-25.
**Source:** [`../mods/wave.asm`](../mods/wave.asm) (1,312 bytes in the code cave at `F07D:0000`).
**Pixel contract:** [`../emu/wave_ref.py`](../emu/wave_ref.py). Evidence it builds on:
[`waveform_phase0.md`](waveform_phase0.md).

## What it does

1. **Scan.** Reads the sound's plane A from wave RAM.
   - Column `c` (0–239) covers samples `[c·len/240, (c+1)·len/240)`, with at least one sample per column.
   - Each column keeps its signed min and max.
   - Reads go through `CALLF CF92:000C(A2AE:0000, wave + cur, n, 1)` in blocks of `n ≤ 0x2400` words (Best st's buffer and call shape), each wrapped in `INC`/`DEC [8010:9757]`.
2. **Cache.** Two 240-byte arrays in the cave, holding the top and bottom rows of each column's line:
   - top row = `31 − (max >> 11)`
   - bottom row = `31 − (min >> 11)`

   The wave fills rows 16–47 around the zero line at row 31. Rows 0–15 and 48–63 are free for text in phase 3.
3. **Render.** Clears the Mixer framebuffer `8010:1591` (30 bytes × 64 rows, bit 7 = leftmost), draws each column's vertical line, then inverts the columns containing soft start (`+14`) through soft end (`+18`) over rows 16–47. This matches the 2000XL's inverted region.
4. **Show.** `CALLF C4C8:0F5F` enters graphics mode (registers `32/07/1D/3F`) and blits. `CALLF BDE3:000E(0)` waits for a key. `CALLF C4C8:0409` returns to text mode.

## Dev hook (phase 2 only)

[`../mods/WAVETEST.args`](../mods/WAVETEST.args) replaces Best st's `NOP / PUSH CS / CALL 28F9` at `B99A:08CF` (file `0x3A26F`, `90 0E E8 25 20`) with `CALL FAR wave_test`. The contract is kept:
- `wave_test` hands back the current soft start through the caller's dword pointer, so the handler's write to `+14` changes nothing.
- It returns the key that closed the view. `'L'` (Program/Sounds) makes the handler call `D6E0:0075('6')`, which reopens Edit Sound.

Phase 3 moves the entry to Help.

## Evidence

All MAME traces, one execution each:

| Test | Result |
|------|--------|
| `test_wave_engine_pixels_match_reference`: `SINE441`, soft start 13,781 / end 48,000 (columns 60–208) | The 240×64 LCD at 80 s equals `wave_ref.pixels` exactly. After Program/Sounds, Edit Sound returns with its title and `Soft st :000.312.22` unchanged. **PROVEN (trace)** |
| A real stereo sample (Peter's `funkySnare.wav`, 11,391 frames, via `emu.snd.from_wav`; not in the repo) | 0 pixel differences from the reference for plane A. **PROVEN (trace)** |
| Graphics mode | Probe `mode=32`, `30x64`. **PROVEN (trace)** |

Harness fix: `emu/mpc3k.py` `parse_screens` now splits only at lines that start with `@ `. The graphics-mode text dump of a real waveform contained `@ ` mid-line and broke the old split.

## Assumptions and limits

- **Framebuffer reuse:** reusing `8010:1591` while the Mixer is inactive is **HYPOTHESIS**. The Mixer clears and redraws it on entry (`C4C8:0490`). Other writers than `C4C8`/`B13A` are **UNDETERMINED** (computed aliases not searched).
- **Stereo:** only plane A is drawn. That A is the left channel is **HYPOTHESIS**.
- **Scan time on hardware:** `U-PHYS`. Every sample is read through `CF92:000C`.
- **`CF92:000C`:** that it preserves `SI`/`DI`/`BP`/`DS` is **HYPOTHESIS** (C convention). The engine reloads everything else after each call.
- **Keys:** the view closes only on `'L'` or `'M'` and ignores every other key.
- **Glass:** pixel order and graphics mode on the real LC7981 are `U-LC7981` / `U-PHYS`. The register values are the stock Mixer's.
