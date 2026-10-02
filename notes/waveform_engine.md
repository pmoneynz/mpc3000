# Waveform editor: the wave view (phases 2–4)

Current extension: BENCH 05 adds the [shared ZONE editor](wave_zones.md)
and [CHOP ZONE](wave_chop.md). The title row now includes separate active-zone
and total-count fields. Those notes supersede the original single-zone state
and cursor-domain descriptions below.

**Image:** Vailixi 3.50 linear, Route A. **Updated:** 2026-10-01.
**Source:** [`../mods/wave.asm`](../mods/wave.asm) (in the code cave at `F07D:0000`),
[`../mods/WAVE.args`](../mods/WAVE.args). Font: [`../emu/lcd_font.py`](../emu/lcd_font.py) → `mods/wave_font.inc`.
**Pixel contract:** [`../emu/wave_ref.py`](../emu/wave_ref.py) `screen()`. Evidence it builds on:
[`waveform_phase0.md`](waveform_phase0.md).
Hardware canary result, review fixes, build manifest, and bench procedure:
[`waveform_bench.md`](waveform_bench.md).

## What it does

1. **Scan.** Reads the selected plane from wave RAM: L = plane A at `+20`, R = plane B at `+20 + len` (stereo only; the layout is **PROVEN**, code + trace, [`waveform_phase0.md`](waveform_phase0.md) §3).
   - Column `c` (0–239) covers samples `[c·len/240, (c+1)·len/240)`, with at least one sample per column.
   - Each column keeps its signed min and max.
   - Reads go through `CALLF CF92:000C(A2AE:0000, wave + cur, n, 1)` in blocks of `n ≤ 0x2400` words (Best st's buffer and call shape), each wrapped in `INC`/`DEC [8010:9757]`.
2. **Cache.** Each mode has its own pair of 240-byte arrays in the cave (`tops`/`bots` for full, `ftops`/`fbots` for fine; `cols` points at the active pair), holding the top and bottom rows of each column's line:
   - top row = `31 − (max >> 11)`
   - bottom row = `31 − (min >> 11)`

   The wave fills rows 16–47 around the zero line at row 31. Rows 0–15 and 48–63 hold text.
   - The full arrays are valid while `full_ok` is set. `view` clears it on every entry (after loading `len`/`wbase` from the record, so CHOP's `chop_refresh_source_base` rewrite of `wbase` between sessions is always picked up), and the View field clears it on a plane change. Nothing else writes `wave`, `len` or `wbase` during a session. Visiting the fine view no longer drops it, so Fine → Full redraws without reading wave RAM.
   - The fine arrays are rescanned on every fine redraw.
3. **Render.** Clears the Mixer framebuffer `8010:1591` (30 bytes × 64 rows, bit 7 = leftmost), draws each column's vertical line, then inverts the columns containing soft start (`+14`) through soft end (`+18`) over rows 16–47. This matches the 2000XL's inverted region.
   - `bound` and each column's end never decrease with the column, so the selected columns are one run. `draw` stops testing at the first column that starts after `b` and inverts the run with one `invert` call.
   - `invert` (AX = first row < 64, BX = first x, CX = width ≥ 1, DX = rows ≥ 1) XORs one mask per framebuffer byte the span touches, stepping 30 bytes per row. It keeps BX, CX, SI, BP, DS and ES and clobbers AX, DX, DI and flags. All callers (`draw`, `zones_focus`, `mute_ui_draw`) reload AX/DX before any later use; several tail-call it. `text` computes one framebuffer byte and mask per glyph and walks them, instead of calling `pixel` per lit bit.
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

### Points

| # | Point | Storage |
|---|-------|---------|
| 0 / 1 | soft start / soft end | sound record `+14` / `+18` |
| 2 / 3 | zone start / zone end | `8010:EDBB` / `EDB7` (Edit Sound's zone fields) |

- **Clamps:** the first point of a pair stays in `[0, second]`, the second in `[first, len]`.
- **Zone points survive reopening Edit Sound.** On entry the page only clamps them: zone start to `[0, len]`, zone end to `[zone start, len]` (`B99A:017A`–`01B0`, `02B0`–`0300`). **PROVEN** (code).

### Full and fine views

- **Full:** column `c` starts at `c·len/240`. It is scanned once per open, and again after a plane change.
- **Fine:** column `c` starts at `p + (c−120)·zoom`, where `p` is the selected point.
  - Zoom runs from 1 to 64, starting at 16. The window is rescanned on every change.
  - Samples outside `[0, len)` count as 0, as on the 2000XL fine window.
  - Column 120, the point itself, is XORed as a cursor.
- **Both:** columns overlapping the selected pair `[a, b]` are inverted over rows 16–47. In the full view the last column reaches `len`; this rule gives the same columns as phase 3's.

### Screen

The screen uses 6-pixel columns:

| Rows | Content |
|------|---------|
| 0–6 | `Edit Snd:` + name |
| 7–14 | The pair: `Start:` (value at col 6) / `End:` (col 24), or `Zone st:` (col 8) / `Zone end:` (col 28). The selected value's ten cells are inverted over rows 7–14 |
| 15, 48 | blank |
| 16–47 | wave |
| 49–55 | `Length:`. For a stereo sound (`+13` ≠ 0), `View:` at col 19 and `L`/`R` at col 24; when the View field is selected its cell is inverted over rows 49–55. In the fine view also `Zoom:nn` at col 33 |
| 57–63 | `<Ply/Stp>` col 0, `<Zone>`/`<Trim>` toggle col 10, `<Fine>`/`<Full>` col 21, `<Exit>` col 34 |

Values use the Edit Sound units `sss.mmm.ss`: `s = f/44100`, `ms = (f mod 44100)·10/441`, then the leftover samples.

### Keys

| Key (code, from the `D547:0006` table) | Action |
|-----------------------------------------|--------|
| Data wheel, `+`/`-` | On the View field: `+` = R, `-` = L, then the view rescans that plane. Otherwise it moves the selected point by one column: `len/240` frames (at least 1) in the full view, `zoom` samples in the fine view. Clamped, written at once, redrawn and blitted (`C4C8:0F0D`) |
| Soft Key 2 `'y'` | Toggle Trim/Zone pair (keeps first or second) |
| Soft Key 1 `'x'` | Ply/Stp: selected range intersected with visible window |
| Digits / Enter on a point | Open the stock numeric editor; see [numeric ABI](wave_numeric.md) |
| Left `'<'` / Right `'>'` | Step between the fields: first point, second point, View (stereo only). Stops at the ends |
| Soft Key 3 `'z'` | Fine ↔ full |
| Up `'^'` / Down `'!'` | BENCH 06: Up from End selects Zone; Down from Zone/Count returns to End. On Start, halve/double zoom (1–64). Other field paths retain their zoom behavior. |
| Soft Key 4 `'u'`, Help `'H'` | Back to Edit Sound |
| Mode keys `L M F J G U S l s O K` | Leave the view and pass the key on |
| Anything else, including the Help release `'h'` | Ignored |

## Evidence

All MAME traces, one execution each:

| Test | Result |
|------|--------|
| `test_wave_view_edits_trim_and_zone`: `SINE441` with start 13,781 / end 48,000. Help; wheel +3; Soft Key 3 (fine); wheel +2; Up; Soft Key 2 (zone); Right; wheel +5; Soft Key 3 (full); Soft Key 4 | The LCD equals `wave_ref.screen` at all nine states (80–96.5 s). Edit Sound then shows `Soft st :000.328.36` (+3 × 229, then +2 × 16) and `Zone end:000.000.40` (+5 × 8). Help on Play/Record still shows the Help page. **PROVEN (trace)** |
| `test_wave_view_field_selects_plane`: `STEREO1` with start 5,000 / end 30,000. Help; Right ×2 (View); wheel +1 (R); Left (End); Soft Key 3 (fine on plane R); Soft Key 4 | The LCD equals `wave_ref.screen` at all five states. Edit Sound comes back with `(ST)` and the start unchanged. **PROVEN (trace)** |
| Phase 2 engine (Best st dev hook, since removed) with a real stereo sample (Peter's `funkySnare.wav`, not in the repo) | 0 pixel differences for plane A. **PROVEN (trace)** |
| Graphics mode | Probe `mode=32`, `30x64`. **PROVEN (trace)** |

Harness fix: `emu/mpc3k.py` `parse_screens` now splits only at lines that start with `@ `. The graphics-mode text dump of a real waveform contained `@ ` mid-line and broke the old split.

## Assumptions and limits

- **Framebuffer reuse:** reusing `8010:1591` while the Mixer is inactive is **HYPOTHESIS**. The Mixer clears and redraws it on entry (`C4C8:0490`). Other writers than `C4C8`/`B13A` are **UNDETERMINED** (computed aliases not searched).
- **Stereo:** one plane at a time, chosen with the View field, which starts at L on every open. Labelling plane A as L and B as R is **HYPOTHESIS** (MAME's mixer bits, [`waveform_phase0.md`](waveform_phase0.md) §3). Real-hardware left/right is `U-PHYS`.
- **Scan time on hardware:** `U-PHYS`. The full view reads every sample through `CF92:000C` once per open (and per plane change). The fine view reads `240 × zoom` samples (at most 15,360) on every change.
- **Redraw time in MAME** (one execution, 551,040-frame mono sound, whole sound selected; MAME's V53 timing is an approximation of hardware): wheel tick in the full view, refresh to blit end 75.4 → 31.5 ms (draw 56.7 → 13.0 ms); Fine → Full 1,686 → 31.5 ms (the 1,610 ms rescan is gone); fine redraw at zoom 16 79.7 → 55.1 ms. The blit (`C4C8:0F0D`) is about 18.6 ms in both.
- **`CF92:000C`:** preservation of `SI`/`DI`/`BP`/`DS` on return is **PROVEN** by the bounded reader/helper walk in [`waveform_bench.md`](waveform_bench.md). The engine reloads everything else after each call. Hardware DMA completion remains unverified.
- **Keys:** the view ignores keys it does not list.
- **Clamps:** the view's `0 ≤ start ≤ end ≤ len` may be stricter than the OS field clamps (**HYPOTHESIS**: they were not decoded exhaustively).
- **Glass:** pixel order and graphics mode on the real LC7981 are `U-LC7981` / `U-PHYS`. The register values are the stock Mixer's.
