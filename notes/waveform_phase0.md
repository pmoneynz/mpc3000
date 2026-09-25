# Waveform editor, phase 0: evidence for the Edit Sound wave view

**Image:** Vailixi 3.50 linear. **Date:** 2026-09-25.
**Mode:** XA=1 with the second PGR, unless stated otherwise. File offset = `((CS<<4)+IP) & 0x7FFFF` for
`CS >= B000`. DGROUP `8010:X` = file `0x20000+X`.
Traces are MAME `mpc3000` at fork `87e2129c`, one execution each, and are pinned by
`emu/test_mpc3k.py`.

Goal: a graphical wave view on Program/Sounds → 6 (Edit Sound), modelled on the
MPC2000XL TRIM page, shipped as a Route A floppy mod
([`../MODDING_HOWTO.md`](../MODDING_HOWTO.md)).

---

## 1. Edit Sound page (`B99A`, file `0x399A0 + IP`)

| Item | Evidence | Status |
|------|----------|--------|
| Draw | `B99A:0002` (file `0x399A2`). The menu line `…6.Edit s…` (`8010:5DF2`) is pushed at file `0x48898`, and `CALLF B99A:0002` at `0x48930` | **PROVEN** (code) |
| Input loop | `B99A:082E` calls `B060:035D(0x44)`. A return of 0 means a field was committed, and `8010:7D79` holds its index, dispatched through `CS:15F2`. Returns `0x78` Ply/Stp, `0x79` Best st, `0x7A` Play X, `0x75` Do and `0x44`/`0x4E` (pad/note: pick sound, `C887:093B`) are handled. Any other code goes to `B99A:1595` and back to the menu, and from there to the main mode loop `C425:0009` | **PROVEN** (code) |
| Page identity | `[D7CB]='L'` (mode) with `[D7CA]=6` (option) | **PROVEN** (code) |
| Fields | 0 sound, 1–3 soft start, 4–6 zone start, 7–9 soft end, 10–12 zone end, 13 Play X, 14 Vol, 15 Tune, 16 Do. Each point is three fields (s, ms, samples 0–43); `B99A:2619` computes `s*44100 + ms*441/10 + samp`, and `B99A:266D` converts back | **PROVEN** (code) |
| Redraw | `B99A:16BB` calls `CALLF B060:0AD9(field)` for each of fields 0..16 | **PROVEN** (code) |

### Sound record, `A2AE:4800 + idx*0x24` (24-bit `0x3A72E0`), 128 records

| Offset | Field |
|--------|-------|
| `+00` | name, 16 characters, space padded; first byte 0 = empty |
| `+11` / `+12` | vol / tune (units **UNDETERMINED**) |
| `+13` | stereo, 0 or 1 |
| `+14` / `+18` | soft start / soft end, u32 frames. Written back at `B99A:0685` / `0788` |
| `+1C` | length in frames, u32 |
| `+20` | wave RAM word address, u32 |

`+20` is a word address: the SND loader writes byte `n` of the sample data to `+20 + n/2`
(`D7FA:059B`), and MAME's wave RAM held the file's samples at exactly those addresses.
**PROVEN** (code + trace).

The zone points are `8010:EDBB` (start) and `EDB7` (end), both dwords. **PROVEN** (code).

## 2. Field editor contracts

| Routine | Contract | Status |
|---------|----------|--------|
| `B060:035D(flags)` (file `0x3095D`) | Waits for a key. The key comes via `BDE3:000E`, after the global filter `DE5C:000E` has consumed Count In, Wait For, Pad Bank, `[ ] { }` and Tap Tempo. Bits of `flags`: low 3 = number of soft keys to pass through, `0x10` = pass `[ ] { }`, `0x20` = return Up/Down, `0x40`/`0x80` = pad events. Handled internally: Help (`0x48`, shows help until released, release = `0x68`), Up/Down (field on the next row), Enter, and per-type keys (table `CS:0701`; numeric `B31B:0007`, choice `B2F1:0002`). Returns 0 on commit, with `[7D79]` = field; otherwise returns the key | **PROVEN** (code) |
| Numeric field keys | Digits go into `7D4A`; `+`/`-` step by `[D69A]` (×10 when field flag 4 is set); Left = backspace or previous field; Right = commit and next field | **PROVEN** (code). That `[D69A]` is the wheel step count is **HYPOTHESIS** |
| Write-back | `B31B:0214` clamps to min/max, runs the field callback, then writes through the field's pointer. Editing is in place | **PROVEN** (code) |
| `B354:03B1(label, ptr, width, min, max, flags)` | Adds a 0x13-byte numeric record at the current cursor: row, col, type 0, width, ptr `+5`, min `+9`, max `+B`, flags `+D`, callback `+E` | **PROVEN** (code) |
| `B354:01C6(label, ptr, options, width)` | Adds a 0x0E-byte choice record, type 2 | **PROVEN** (code) |
| Field list | Records from `8010:7D80`, with a 0 marker at `7D7F`. Byte 0 of each record is its length, repeated in its last byte. Current record pointer at `7D7B`/`7D7D`. No overflow check | Layout **PROVEN**. Capacity **UNDETERMINED** |
| Active field | Shown by the hardware cursor on the field's first cell (`B1B1:0026` → `INT 43` AX=3). Mode `0x38` while idle, `0x3C` while typing digits, `0x30` with no field (`INT 43` AX=2). No inverse video | **PROVEN** (code). What the bits do on the glass is `U-LC7981` |
| `B060:0AD9(field)` | Places the cursor, redraws by type (`CS:0C58`), sets `[D6A1]=1`. Numeric redraw goes through `B31B:0214`, so a redraw also clamps | **PROVEN** (code) |

Raw panel codes reach the OS through the table at `D547:0006` (file `0x55476`).
For example, `0x4A` (Help) becomes `'H'` (`0x48`) and Main Screen becomes `'M'`. **PROVEN** (table).

### Which key opens the wave view

No key reaches the Edit Sound loop unhandled. In one emulator run each:
- Mode keys, Erase, Timing Correct, Locate, Assign, 16 Levels and Tap Tempo leave the page.
- Pad Bank, Full Level, After, Wait For, Count In, `<`, `>`, `>>` and `.` produce no visible change.
- The `<<` run failed and was not repeated.

**Chosen: Help**, on this page only.
- Patch `B060:0422` so that when `[D7CB]=='L'` and `[D7CA]==6` it returns `0x48` instead of showing help.
- Add a `0x48` case to the loop at `B99A:0842`. Without it, `'H'` would reach `C425:0009`, which answers "function is not yet implemented".
- The wave view must ignore the release code `0x68`.

## 3. Sample memory

- **SND file:** `01 02`, then the 36-byte sound record, then signed 16-bit LE samples. The loader `D7FA:000E` accepts version byte ≤1 (MPC60 conversion at `D7FA:0651`) or 2 (`D7FA:03A5`). Name and `+20` are ignored on load. **PROVEN** (code).
- **Byte 1 bit 7:** changes the tune through `D7FA:07FC`. Its meaning is **UNDETERMINED**.
- **Mono / stereo:** mono is `length` words. Stereo is two planes, A at `+20` and B at `+20+length`:
  - Best st reads B at `B99A:2A95`. **PROVEN** (code).
  - Wave RAM matched plane A followed by plane B. **PROVEN** (trace).
  - A is left: **HYPOTHESIS** (MAME mixer bits).
- **CPU read path:** `CALLF CF92:000C(dst, wave, count, dir)` (file `0x4F92C`), with `dir=1` to read. Best st reads at most `0x2400` words into `A2AE:0000`–`47FF`, which ends where the sound records start. Call shape **PROVEN** (code). Port meanings `U-C0XX`. Throughput on real hardware `U-PHYS`.
- **`8010:9757`:** a byte busy counter around disk and wave RAM transfers (105 `INC`/`DEC` sites).
  - `DCA2:017C` (file `0x5CB9C`) skips transport commands while it or `[A7AE]` is non-zero.
  - `EC05:000C` (file `0x6C05C`) defers work through `[FFA6]`.
  - Readers are **PROVEN**. Purpose is **HYPOTHESIS**.
  - The wave view must increment it before each `CF92:000C` call and decrement it after, as Best st does.

**Test sounds** (`emu/snd.py`):
- `SINE441`: 55,125 frames, mono. 0.5 s of sine at 441 Hz (100 samples per period, amplitude 30000), 0.5 s of silence, then a 0.25 s ramp from −30000 to +30000.
- `STEREO1`: 33,075 frames. Plane A is 0.25 s of sine, then silence; plane B is 0.25 s of silence, then a ramp from +30000 to −30000.

In MAME each loads through Disk → `7` → `<Load>`, and Edit Sound shows its name and length. The wave RAM is byte-identical to the file samples (`test_synthetic_snd_loads_into_wave_ram`). **PROVEN** (trace).

Disk images need NUL at directory entry `+0C..+13`, which is where 3.50 keeps name characters 9–16. The mtools timestamps there caused `FD00` "requested file was not found" (trace).

The power-on loader never loads a bare SND. It reads APS, then PGM, then ALL (`B000:01A7`), and the program formats are not recovered. **PROVEN** (code) for the order.

## 4. Display

- 3.50 already uses graphics mode, on the Mixer (`C4C8`):
  - `C4C8:0F5F` sets `8010:98DC`=1, then registers 0–3 = `32/07/1D/3F` (30 bytes × 64 lines), then streams `0x780` bytes from the framebuffer `8010:1591`–`1D10`.
  - `C4C8:0409` restores `3C/75/27/3F`, calls `INT 43` AX=1 and clears `98DC`.
  - `B13A:0000` writes a bit field into the framebuffer and pushes the changed bytes.
  - Guards: `0x33E0D` leaves graphics mode before text when `98DC` is set; `0x5E5F0` and `0x61BEF` skip the AX=5 shadow save while it is set.
  - Code **PROVEN**. Mixer option 1 gives `mode=32`, a 30×64 display and 16 bitmap strips (trace).
- Character mode and graphics mode are exclusive in MAME's `hd61830`, so the wave view must draw its own text. The real LC7981 is `U-LC7981`. Stock 3.50 uses these register values on the Mixer, so they are the ones to reuse.
- Pixel order: MAME shows bit 0 leftmost, and the OS bit-reverses its framebuffer bytes before writing (`B13A`). **PROVEN** (code + MAME source). The real glass is `U-PHYS`.

## 5. Code cave `[0x707C8, 0x74000)`, 14,392 bytes

`emu/lua/cave_watch.lua` taps both physical homes of the cave for reads, including opcode fetches, and for writes:
- the EPROM at `0xF07C8`–`0xF3FFF`;
- the Route A RAM copy at `0x3F07C8`–`0x3F3FFF` (logical page 60 → physical page `0x0FC`).

A control run confirmed that the tap sees fetches: `B000:01FF`–`0207` were logged at `0x3B0200`–`0208`.

| Run | Pages visited | Reads | Writes |
|-----|---------------|-------|--------|
| Stock 3.50, 68 s | Edit Sound, Mixer 1 and 2 (graphics), Disk, Other | 0 | 0 |
| `MOD350.SYS`, 84 s | same | 0 | 7,196 words, all from the stub copy at `6900:0041` |

**PROVEN** (trace) for these two runs (`test_code_cave_never_read`). "Never read on any path" is still
**UNDETERMINED**; each new page a mod exercises needs its own run.

## Open

- Field list capacity. `[D69A]` = wheel step. The meaning of `[A75D]`.
- Vol/tune units. Left/right on real hardware.
- LC7981 graphics mode, cursor and blink bits on glass (`U-LC7981`, `U-PHYS`).
- Wave RAM read throughput on hardware (`U-PHYS`), and so the time to scan a long sound.
- Loading a sound at boot without panel input (needs the PGM/APS format).
- After either graphical Mixer page, Main Screen shows `Play/Record (Record Ready)`,
  not `Play/Record` (both cave runs, trace). Cause **UNDETERMINED**. Check that the
  wave view's exit path does not do the same.
