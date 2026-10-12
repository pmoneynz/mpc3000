# Emulator baseline (MAME `mpc3000`, patched)

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-25.

The MAME driver lives in a fork; the harness lives in this tree
([`../emu/README.md`](../emu/README.md)):

| Path | Role |
|------|------|
| MAME fork `pmoneynz/mame` `mpc3000-accuracy` | Upstream MAME `9ede38cb` + driver commits, pinned `b4ab57e6` |
| `emu/mpc3k.py` | Headless runner: fresh NVRAM/cfg per run, LCD text capture |
| `emu/romset.py` | Romset from `07-rom/` + placeholders, in `build/roms/` |
| `emu/probe.lua` | I/O first-access log, LC7981 register log, screen dump |
| `emu/test_mpc3k.py` | Boot regressions (all cases in parallel) |

A trace is one execution. Everything below marked **PROVEN (trace)** is
what the emulator did on that run, under the MAME device models. It is
not evidence about the physical board.

---

## 1. Stock MAME already boots the OS

Upstream `mpc3000` (`MACHINE_NOT_WORKING`) runs Vailixi 3.50, 3.12,
3.11 and 3.08 from reset to the Play/Record screen in about 40 s
emulated. **PROVEN (trace).**

The trace reproduces the static boot slice
([`boot_reset_to_bios_banner.md`](boot_reset_to_bios_banner.md)):
`FAC0:0016` writes the first PGR table (`00C0`-`00E7`, `0028`-`003C`,
`0140`, `003E`, `003F`), then the `FFFE`/`FFFC`/`FFFA`/`FFF8` relocation
writes and the `0x82`/`0x84`/`0x86`/`0xFE` 8255 writes; `F800:186C`
programs LC7981 `IR0=3C IR1=75 IR2=27 IR3=3F IR4=07 IR8=00 IR9=00`.
Static and dynamic evidence agree.

The UI stays in LC7981 character mode (`IR0` = `30`/`38`), 40x8, display
start 0, for every screen reached. Screen text is therefore exact from
display RAM. Glyph pixels come from a partial CG recovered from a glass
photo (section 5).

## 2. Defects fixed on `mpc3000-accuracy`

| Change | Evidence | Tag |
|--------|----------|-----|
| I/O `0x50` (I-0055 SMPTE option). Absent option reads back the last written word | Probe `D6BEA` (file `0x56BEA`): `OUT 50,0000`/`IN`, `OUT 50,FFFF`/`IN`, `AX=(lo1<<8)|lo2`; `AX==00FF` returns 0. Unmapped MAME read 0 gave `AX=0000`, and the System Information screen printed `SMPTE Sync -(I-0055 OPTION......):Active` (string at file `0x211AD`, the only variant). With echo, the line disappears | Probe logic **PROVEN**. Board bus-hold electrics **HYPOTHESIS** (the OS's own definition of "absent") |
| Sound memory: Akai 2 MB / EXM3008 8 MB / 32 MB board plus SIMM pair none / 2x1 / 2x4 MB | Sizing routine `D0C0:0100` (file `0x50D00`), see section 3 | Algorithm **PROVEN**. Decode placement **HYPOTHESIS** |
| `an4_func` was never bound; `an3_func` was bound twice | Driver source | **PROVEN** |
| TE7774 TXD2-4 to `mdout2`-`mdout4`, RXD2 from `mdin2` | MAME's own header wiring comment | **HYPOTHESIS** (MAME) |
| BIOS `v308` (`MPC3000_V3.08_LSB/MSB.BIN`) | Boots to Play/Record; LSB is the even chip | **PROVEN (trace)** |
| V53 wait states and refresh (WCU/REFU registers were no-ops) | Reset stub at file `0x7FF00`, see section 7 | Register values **PROVEN** (code). Timing model **HYPOTHESIS** where noted |

Old flat 32 MiB wave RAM made every machine report `32636K`.

## 3. Sound-memory sizing (`D0C0:0100`)

Hardware helpers, all on `adcexp` 8255 (`F8` A, `FA` B, `FC` C, `FE` ctl):

| Entry | File | Effect |
|-------|------|--------|
| `CF92:01CB` | `0x4FAEB` | `PB[2:0]` = decode mode |
| `CF92:01DD` | `0x4FAFD` | `PA` = nibble, then `PC0` 0->1 (external latch) |
| `CF92:01F3` | `0x4FB13` | latch 0; ctl `90` (PA in); `PC=0E`; return `PA & 0F`; ctl `80` |

DGROUP tables (`8010:75AE`, read from emulator RAM after init):

```
75AE  00 03 06 07            PB mode per probe step si=0..3
75B2  00 01 04 10            banks (2 MB) per class
75B6  03 02 01 00            PB mode, board=1, by SIMM class
75BA  06 06 05 00            PB mode, board=4, by SIMM class
75BE  00 08 08 08            latch,   board=1, by SIMM class
75C2  00 0C 08 08            latch,   board=4, by SIMM class
75C6  00 01 00 02 00 03 00 01 00 02 03 03 03 00 01 00   sense -> SIMM class
```

Algorithm: read sense, `di = [75C6+sense]`. With latch 0, try
16, 4, 1 board banks (PB mode 7, 6, 3): write `0..1000h` to each bank at
`bank*2MB + 0x20000` via DSP DMA, read back, first full match wins. Then
set PB mode and latch from the tables; for 16 banks force `PB=7`,
latch 0, `di=0`. `[FACC] = board + [75B2+di]`. `D0C0:0200` turns that into
`FACC*2MB - 0x107D0 words` = the `-132K` reserve. **PROVEN** (code +
trace).

Emulator model: board banks from address 0; SIMM banks follow the board
only while latch bit 3 is set (every non-zero latch value has it). PB mode
is ignored. Result for all documented combinations
([Operator's Manual v3.0 p.229-230](../08-operators-manual/)):

| Board | SIMM | Screen |
|-------|------|--------|
| 2 MB | none | `1916K` |
| 2 MB | 2x1 MB | `3964K` |
| 2 MB | 2x4 MB | `10108K` |
| 8 MB | none | `8060K` |
| 8 MB | 2x1 MB | `10108K` |
| 8 MB | 2x4 MB | `16252K` |
| 32 MB | - | `32636K` |

The OS only accepts board sizes of 1, 4 or 16 banks, which is why a flat
4/10/16 MB space read as 2/8/8 MB.

## 4. Other runtime facts

- Floppy canary (`mods/build_canary.py` → `build/mods/vailixi350-canary.img`) prints
  `Vailixi 3.51 (---/--/----)` on row 7 about 10 s after reset.
  **PROVEN (trace)**. Physical run still deferred.
- The full floppy loader routine, strings, memory map, MZ rules and
  per-version addresses are in [`floppy_loader.md`](floppy_loader.md).
- Floppy OS 3.16 is not a MAME BIOS and is absent from the 3.12 EPROM
  pair. A 1.44 MB FAT12 image whose only file is `M3K316.SYS` (SHA1
  `b45b017721f0e59974e50de93040ccd1f973ad23`) is inserted at `-flop`.
  The 3.12 loader prints `Loading files ...` at 15 s (FDC `0xE8`/`0xEA`),
  then `System 3.16 (02/20/05)` at 30 s (that string lives only in the
  SYS file). Play/Record is up by 60 s after the SCSI scan; Other →
  Version still reads `System 3.16 (02/20/05)`. The same 3.12 EPROM with
  no floppy stays on `Version 3.12 (03/24/97)`. **PROVEN (trace)**.
  Vailixi 3.50 EPROMs load it the same way: `Loading files ...` at 15 s,
  `System 3.16 (02/20/05)` at 30 s, Play/Record at 60 s, Version reads
  3.16; no-floppy control stays 3.50. Loader in the 3.50 image:
  `B000:01A7` (file `0x301A7`, identity PGR) prints `DS:1218`
  `Loading files ...` (file `0x21218`) via `B1B1:005B`. Two call sites:
  after "...for startup files" (`B000:0124`), near-call `B000:013B`
  (→`B000:03B4`), `JZ`, then `B000:014C` calls `B000:01A7` with arg 0;
  after `Searching SCSI` (`B000:0165`), `CALLF D470:0948`
  (`B000:0171`), `JZ`, then `B000:0184` calls it with arg 1. MAME
  breakpoints (identity PGR): with the 3.16 floppy, `013B` then `014C`,
  `0171`/`0184` never reached; without floppy, `013B` then `0171`,
  no `014C`/`0184`. So the floppy load is the arg-0 site and
  `B000:03B4` is the floppy startup-file test. **PROVEN (trace + code)**.
  `D470:0948`/arg 1 as the SCSI path is **HYPOTHESIS** (no SCSI target
  traced). Same string table (`STARTUP ????????`, `SYS`/`APS`/`PGM`) as
  3.12. No `0F E0`/`0F F0` in `[0x30118, 0x30240)`.
  All EPROM OSes we hold (3.08, 3.11, 3.12, 3.50; no 3.10 image exists
  in `07-rom/`) boot 3.16 from the floppy: `Loading files ...` on row 7
  by 5 s (3.50: after System Information), `System 3.16 (02/20/05)` at
  30 s, Play/Record at 60 s. No EPROM image contains `3.16` or
  `02/20/05`. **PROVEN (trace)**, test
  `test_every_eprom_os_boots_316_from_floppy`. Each interleaved image has
  exactly one `push imm16` of each loader string: "...for startup files"
  / "Searching SCSI" / "Loading files" at file `0x36FA6`/`0x36FE8`/
  `0x3702D` (3.08, DS offs `11D1`/`11F7`/`1220`) and `0x300BE`/`0x30100`/
  `0x30156` (3.11 and 3.12, `11D3`/`11F9`/`1222`). Shape in all three:
  print "...for startup files", near-call a test, `OR AX,AX; JZ`, call
  the loader with arg 0; print "Searching SCSI", far-call a test, call
  the loader with arg 1. The loader prints "Loading files". No
  `0F E0`/`0F F0` in the disassembled windows. **PROVEN (code)**.
  Arg 0 = floppy is PROVEN only for 3.50 (breakpoints above); for
  3.08/3.11/3.12 it is **HYPOTHESIS** by identical structure.
  Sequencer pool, the PDF's 484k→439k: 3.50 prints SEQ free as
  `(E21A:000B() - 400) / 1024` (`B000:00A1`, file `0x300A1`); "Free seq
  mem %" is `E21A:0096` (file `0x62236`) = `100*free/total`, total =
  `lin([8E2C]:[8E2A]) - lin([8E28]:[8E26])` via `D9DD:005D`
  (`seg*16+off` difference). The same byte pattern finds the pool words
  at `8C39` (3.12) and `8B13` (3.16, `M3K316.SYS` file `0x3FE42`). Live
  RAM (`emu/seqmem.py`, DS mode, PGR-translated): 3.50 and 3.12 pool
  `0000:6DF0`..`7000:FFFE` = 496142 bytes = **484K**, matching 3.50's
  own `..484K` line; 3.16 (DS=`C99C`) `0000:2000`..`6000:FFFE` = 450558
  bytes = **439K**, from either loader. **PROVEN (trace + code)**. The
  3.16 menu shows only `%`, so the K figure is derived with 3.50's
  formula, not displayed by 3.16.
- TE7774 status bit 1 is active-low RX ready for the OS: `D547:0077`
  `IN AL,D2 / TEST AL,2 / JNZ skip`, then `C2`, then `CA`. MAME's
  behaviour matches; its comments are inverted. **PROVEN** (consumer).
- Runs are deterministic: two identical runs give byte-identical
  `screens.txt`, `io_first.log`, `lcd_io.log`.

## 5. LC7981 character generator from a glass photo

Source: one photo of a real MPC3000 on Play/Record (`IMG_4706`, copied to
`emu/font/lcd_play_record.jpg`). Pipeline in
`emu/font/`, run in order: `fit_grid.py`, `homog_fit.py`,
`refine_fit.py`, `warp_fit.py`, `normalize.py`, `extract_glyphs.py`;
`emu/romset.py` then builds `hd61830.bin` from `glyphs.json`.

Registration: homography + radial k1 from dot centres, refined so every
cell's 6th column and 8th row sample dark (`IR1=75`: pitch 6x8), plus a
9x3 smooth residual warp. Dark and lit levels are separate fitted
surfaces (background 0-85, lit 90-230 across the photo). Result: 5 of
15360 pixels within 0.3-0.7 of threshold; 8 lit pixels in all gap
columns, 6 in gap rows (the cursor block).

Pairing: display-RAM bytes from the emulated 3.50 boot at 45 s
(`build/emu/font_ref/screens_hex.txt`). Every cell matches the photo except
row 1 cols 24-39, where the real machine showed `BPM: 80.4 (MAS)` and the
cursor. Those cells are excluded from evidence.

| Class | Codes | Rule |
|-------|-------|------|
| **PROVEN** (37) | `00 20 ( ) - . / 0 1 4 : < = > B D F O P R S T a c d e f g k l n o p r s u y` | >= 2 cells, identical bitmaps |
| Observed once (18) | `% & + A C E L M N U V Y h i m q t w` | single cell |
| **HYPOTHESIS** (1) | `8` | from `80.4`, assumes ASCII in the differing region |

No code had conflicting bitmaps. The 11 codes that also occur in the
differing region agree there with ASCII. Code `00` renders blank.
Unobserved codes are filled with a hatch in `roms/mpc3000/hd61830.bin`,
so unproven glyphs are visible on screen.

Closure: MAME's native 240x64 render of that boot equals the photo on all
14297 compared pixels (`test_lcd_pixels_match_glass_photo`). **PROVEN**
for this screen.

Cursor: the photo shows a solid 6x8 block (gap column and 8th row
included) over the cell at address `0x40`, not an inverted glyph. MAME's
HD61830 model with the OS mode `0x38` (blink on, cursor off) draws exactly
that block during the blink-on phase. LC7981 mode-bit equivalence and the
blink period are **UNDETERMINED** (one still frame).

## 6. Named boundaries the emulator does not close

| ID | Boundary | Effect on runtime testing |
|----|----------|---------------------------|
| U-PANEL-ROM | Panel uPD78C10 ROM absent; a `0xFF` (`JR $`) placeholder idles the MCU. An OS-side HLE sends the link frames instead ([`panel_link.md`](panel_link.md)) | All 57 buttons, pads, dial and slider drive the OS. Scan timing, pad velocity/pressure and slider scale are not the real panel's |
| U-LC7981-CG | 55 of 96 codes `20-7F` recovered from one photo; `A0-FF` and the rest unobserved (hatched) | Hatched cells mark unproven glyphs |
| U-LC7981-BLINK | Blink period and LC7981 mode-bit meaning for `0x38` | Cursor timing unverified |
| U-L7A1045-0A | DSP register at I/O `0x6A` (`B03B:01C7` writes `0x0E` once) | Unmodelled |
| U-WAVE-DECODE | Real bank placement and PB mode meaning (PALs IC25/29/31) | Model reproduces OS results only |
| U-WAVE-OPENBUS | Read value of an absent wave bank (MAME returns 0) | Sizing result unaffected |
| U-SIMM-SENSE | Real sense nibble per SIMM type; model uses `F`/`E`/`9` | Any value in a class is OS-equivalent |
| U-I0055 | Installed I-0055 register behaviour; model returns 0 | SMPTE chase untestable |
| U-TCLK | V53 TCLK fixed at 4 MHz in MAME (FIXME: DAWCK from DSP) | Timer-derived tempo accuracy |
| U-DSP-AUDIO | L7A1045 voice/filter/effects accuracy | Audio not validated |
| U-V53-TIMING | Base instruction clocks and prefetch come from MAME's NEC core; its V33 prefetch size/cost is marked "complete guess" | Absolute CPU speed unverified; section 7 adds only the bus waits |
| U-V53-CLOCK | MAME's `v53_device` ran the core at the crystal rate (32 M cycles/s); the data book divides X1 by 2 for the CPU (16 MHz). Fork `b4ab57e6`: `NEC_CPU_DIV=2` (default 1 until the suites are re-timed) | Every CPU-bound duration measured before 2026-10-13 is half the physical value; timer-driven events are unaffected ([`performance.md`](performance.md) §1.1) |
| U-DMA-BUS | DMA cycles do not stall the CPU (MAME grants the bus at once and the CPU keeps running) | CPU time during floppy/SCSI/DSP DMA is optimistic |
| U-REFRESH-QUEUE | Every refresh cycle is charged to the CPU; the V53 queue can hide some while the bus is idle | CPU slowed by up to 4/272 (1.5%) too much |
| U-BUS-SIZE | Every access is modelled as a 16-bit bus cycle (no BS8). NVRAM chip LC3517 is 8-bit | NVRAM word accesses may take one cycle too few |
| U-READY | External READY waits (LCD, DSP, FDC, TE7774) unmodelled; only programmed waits are applied | Slow-peripheral stalls missing |

## 7. V53 wait states (`mpc3000-accuracy`)

Source: *NEC 1991 16-bit V-Series Microprocessor Data Book*
(`01-cpu/`), uPD70236 (V53) Wait Control Unit (figures 53-61) and
Refresh Control Unit (figure 62). Stock MAME mapped these registers to
empty write handlers, so every bus cycle was zero-wait and refresh took no
time.

The reset stub at file `0x7FF00` (`FFF0:0000`, XA off, 20-bit
`0xFFF00`) programs them with nine `MOV DX,port / MOV AX,imm / OUT DX,AL`
and then does `JMP FAR FAC0:0000`. 3.08, 3.11 and 3.12 have the same bytes
at the same offset. `M3K316.SYS` has no `MOV DX` to any of these ports.
**PROVEN** (code).

| Port | Register | Value | Meaning |
|------|----------|-------|---------|
| `FFEA` | WMB0 | `07` | 16 MiB space: lower block 1 MiB, upper block 8 MiB |
| `FFF3` | WMB1 | `00` | 1 MiB area: lower and upper blocks 32 KiB |
| `FFED` | WAC | `00` | 1 MiB area is `0x000000-0x0FFFFF` |
| `FFEC` | WCY0 | `02` | `[0x800000, 0x1000000)`: 2 waits |
| `FFEB` | WCY1 | `11` | `[0x100000, 0x800000)`: 1 wait; 16 MiB lower block: 1 wait |
| `FFF4` | WCY2 | `11` | 1 MiB area lower and middle: 1 wait |
| `FFF5` | WCY3 | `31` | External I/O: 3 waits; 1 MiB area upper: 1 wait |
| `FFF6` | WCY4 | `31` | DMA: 3 waits; refresh: 1 wait |
| `FFF2` | RFC | `90` | Refresh on, N = 17: every 272 clocks (17 us at 16 MHz) |

Clock caveat (2026-10-13): the clocks in this section are MAME core cycles,
which the pinned fork runs at 32 MHz, twice the physical CPU clock
([`performance.md`](performance.md) §1.1); the refresh period "17 us" is
therefore 8.5 us in the pinned build and correct only under `NEC_CPU_DIV=2`.

So ROM (`0x000000`), work RAM (`0x300000`) and NVRAM (`0x500000`) all take
1 wait per bus cycle. Before the stub runs, every cycle takes 7 (WCY reset
value).

Model (MAME fork `src/devices/cpu/nec/`, `src/devices/machine/am9517a.cpp`):

- One wait count per 32 KiB page of the 24-bit physical space, from the
  PGR-translated address. Byte access or aligned word: 1 bus cycle; odd
  word: 2.
- Queue fetches: one bus cycle per 2 bytes, so each byte costs half the
  page's waits on top of the core's fetch cost.
- External I/O (below `0xFF00`, not a relocated internal peripheral):
  IOW waits. The system I/O area takes none (data book).
- Refresh: `2 + max(2, RFW)` clocks (4 here) every `16 x N` clocks.
  The data book's "minimum of 4 clocks" plus RFW is read as a floor.
  **HYPOTHESIS**.
- DMA: DMAW waits in the DMAU `SW` state. The DMAU now runs at the CPU
  clock, as in the data book's clock figure. Before, it ran at half.
- Where the 1 MiB area overlaps the 16 MiB blocks, the area wins.
  **HYPOTHESIS**. It does not matter here: both give `[0, 1 MiB)` 1 wait.
- The WCU and RFC registers are now readable. The data book says all
  system I/O registers except XAM are read/write.

Check against the core (MAME debugger, `totalcycles`, 3.50 boot):
`REP MOVSW` at `FAC0:008D` copies 15945 words from ROM to RAM. Without
waits it takes 179396 clocks = 10 per word + 2 per resume (9973 debugger
timeslice resumes). With waits it takes 218880 clocks. Take away 12162
resumes x 2 and the result is 194556. The model predicts
15945 x 12 = 191340, plus 805 refreshes x 4 = 3219, for 194559. Every
clock is accounted for to within 3 clocks. **PROVEN (trace)** for the
model's arithmetic. This says nothing about the physical board.

Effect: BIOS LCD init (`F800:186C` `IR=00`) moves from 0.0750 s to
0.0883 s. Boot screens at 2-45 s are unchanged (boot is dominated by timed
waits). All regression tests pass. Test:
`test_reset_stub_wait_states_take_effect` (register readback through
`emu/lua/wcu_dump.lua`, plus the LCD init floor).

Every MAME driver on the V53/V53A (for example `hng64`, `mpc2000`) now gets
the waits its own firmware programs. V40/V50 are unchanged (different
register layout).
