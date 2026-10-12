# Performance map, headroom and optimization backlog

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-10-13.

Where the stock OS spends V53 cycles, how much is free, and what is worth
changing. Measured with the cycle profiler added to the MAME fork
(`nec_prof`, section 2) over nine workload windows (section 3). Every
figure below is one emulated execution under the MAME device models at the
physical CPU clock; it is not a hardware observation (section 8 lists the
hardware tests that close that gap).

Reproduction: `python3 -m emu.profile` then `python3 tools/prof_report.py`
(`build/emu/prof/report.md`, `report.json`).

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | CPU utilization by subsystem, per-event costs, headroom, ROM space map, ranked optimization backlog |
| Observable | `build/emu/prof/<workload>/prof_<i>.txt` dumps; `report.md` tables |
| Inputs | Stock 3.50 EPROM set, panel-link scripts, MIDI In 1 SMF, floppies from `emu/profile.py` |
| Outputs | Sections 3-9 |
| Confidence | Cycle shares **PROVEN (trace)** under the MAME model with the caveats of section 1; hardware figures **UNDETERMINED** until section 8 runs |
| Hardware deferred | CPU clock on the pin, LC7981 busy, interrupt response, pad-to-voice latency, MIDI saturation (section 8) |

---

## 1. Hardware timing model

### 1.1 Clock: the emulator ran the CPU twice too fast

| Fact | Evidence | Tag |
|------|----------|-----|
| X1 crystal 32.000 MHz, part µPD70236GD-16 | Service manual parts list (`04-schematics-service/SERVICE_MANUAL_NOTES.md`) | **PROVEN** |
| The V53 clock generator divides X1 by 2 (or 4, 8, 16) for the CPU; "connect a crystal with a frequency twice the operating frequency"; CLKOUT period 62.5 ns | Data book µPD70236, *Clock Generator (CG)* and *X1, X2*, AC table | **PROVEN** (data book) |
| CPU instruction clock = 16 MHz | the two rows above | **PROVEN** |
| MAME `v53_device` inherits `nec_common_device`'s identity `execute_clocks_to_cycles`, so the core executed 32 M cycles/s: a 2 s window counted 64,024,934 cycles | fork `src/devices/cpu/nec/v5x.h`; `build/emu/prof_smoke/prof_0.txt` | **PROVEN** (code + trace) |
| The TCU, serial and DMA derivations in `v5x.cpp` take the crystal (`clock()/16` = 2 MHz timer clock), so they were right and only the core was fast | `v5x.cpp` lines 151, 165 | **PROVEN** |

Fix in the fork (uncommitted, see section 10): `v53_device` gets
`m_cpu_div` (`execute_clocks_to_cycles = clocks / div`, inverse for
`cycles_to_clocks`). Default 1 keeps the pinned behaviour so the 135
emulator tests are unchanged; `NEC_CPU_DIV=2` is the physical clock and is
what `emu.profile` uses: the same window then counts 32,011,597 cycles.
Consequences: every CPU-bound duration the emulator ever reported (LCD
init 0.0883 s, loader copies, the "boot by 23 s" timelines where they are not
timed waits) is half the physical value; interrupt rates, tick periods and
boot screens are unchanged because they are timer-driven. Making 2 the
default is the right accuracy fix but needs the suites re-timed first
(the wheel-burst coalescing tests depend on redraw time).

### 1.2 Bus, waits, refresh, DMA, I/O

From [`emulator.md`](emulator.md) section 7 (reset stub at file `0x7FF00`,
**PROVEN** register values):

| Access | Cost model (CPU clocks) |
|--------|-------------------------|
| ROM `0x000000`, work RAM `0x300000`, NVRAM `0x500000` | 1 wait per bus cycle; odd word = 2 cycles |
| External I/O (`0x00-0xFE`: LCD, TE7774, DSP, FDC, PPI, PIT) | 3 waits per cycle |
| DMA | 3 waits per transfer; bus stolen from the CPU, **not modelled** (`U-DMA-BUS`): floppy DMA at 500 kbit/s is ~31 k word cycles/s, under 0.5 % |
| Refresh | 4 clocks every 272 (N = 17): 1.5 % ceiling, charged in full (`U-REFRESH-QUEUE`) |
| Prefetch | 2 bytes per fetch cycle, page waits split across both (fork model) |
| READY from slow peripherals (LC7981 busy, DSP, FDC, TE7774) | **not modelled** (`U-READY`); the OS reads LC7981 status (`0xE2`) once before every data write, so a real busy wait would add to every character |

Timers: TCU clock 2 MHz; TCT0 100 Hz system tick (IVT 8), TCT1 sequencer
tick 96 PPQ (192 Hz at 120 BPM, IVT 9), both programmed once
([`sequencer_model.md`](sequencer_model.md)). Serial: TE7774 at 31250 baud,
one interrupt per received byte (IVT 0x0D), 3125 bytes/s per port maximum.

### 1.3 Instruction clocks: MAME's V33 table against the data book

The fork charges the V33 column of MAME's NEC core plus the waits above.
Spot check against the µPD70136 *Instruction Set* table (`01-cpu/`, text
lines 18513-19080 of the extracted book; even/odd word address):

| Instruction | Data book V33 | MAME V33 | Note |
|-------------|---------------|----------|------|
| MOV reg,reg; ADD/CMP/TEST/AND/OR reg,reg; INC/DEC reg; SHL reg,1 | 2 | 2 | match |
| MOV mem,reg (word) | 3/5 | 3/5 | match |
| MOV reg,mem (word) | 5/7 | 5/7 | match |
| LDS/LES (MOV DS0,reg16,mem32) | 10/14 | 10/14 | match |
| RET near | 10/12 | 10 | match (even) |
| RETI (IRET) | 13/19 | 19 | match (odd) |
| IN acc,imm8 / OUT imm8,acc | 5/7, 3/5 | 5, 3 | match |
| NOP, EI, BRKXA | 3, 2, 12 | 3, 2, 12 | match |
| BRK imm8 (INT) | 20/26 | 24 | within range |
| **CALL near direct** | **7/9** | **24** | MAME over-charges by ~15 |
| **BR near (JMP near)** | **7** | **15** | over-charges by 8 |
| **BR short (JMP short)** | 7 (same row class) | 12 | over-charges |
| **Bcc short** | **3 not taken / 6 taken** | **3 flat** | under-charges taken branches by 3 |
| **MOV mem,imm** | **3/5** | **11 (byte) / 15 (word)** | over-charges |
| MUL reg16/mem16, DIV reg8 | 16/18, 16 | tables not compared | **UNDETERMINED** |
| External interrupt response | row not located in the V33 chapter | memory waits only (~10) | **UNDETERMINED**; at ~300 interrupts/s even +30 clocks is < 0.1 % |

Net: C code with many near calls (the whole app ROM) and the AMX kernel
are over-charged; tight loops with taken branches (the idle poll, the FDC
poll) are under-charged. **HYPOTHESIS:** busy fractions below are within
about ±25 % of the physical board for the same instruction stream, with
call-heavy routines on the high side. Section 8 H2 measures the ratio
directly. `U-V53-TIMING` stays open.

---

## 2. The profiler (`nec_prof`)

Fork files `src/devices/cpu/nec/{nec.h,nec.cpp,v5x.cpp,v5x.h}` (section
10). Off unless `NEC_PROF_DIR` is set, then every instruction updates:

| Record | Key | What |
|--------|-----|------|
| `A phys count cycles` | physical (PGR-translated) address of the first byte | self cost; a continued `REP` keeps the string instruction's address |
| `E site target n` | call site, callee | every CALL near/far/indirect and software INT |
| `I entry incl calls` | callee | inclusive cycles from a per-stack-segment shadow stack (pops when SP rises past the frame; a task main that never returns accumulates the whole window; recursion double-counts) |
| `V vec count incl self` | interrupt vector | from the hardware vector fetch to the IRET on the entry stack, or until the scheduler moves to a third stack (AMX abandons IRET frames on a task switch) |
| `S ss cycles` | SS | exclusive split by stack = AMX task (create table SS values) |
| `P port r w` | external I/O port | byte-lane accesses |
| `T` | window | totals, halted cycles, interrupt entry cycles |
| `cov_fetch/read/write.bin` | 1 bit per byte of the 16 MiB space, whole run | executed, data-read, written |

Windows: `NEC_PROF_WINDOWS=s0:e0,s1:e1` (emulated seconds), one dump per
window; the check runs once per timeslice. Cost: a 90 s workload takes
about 30 s wall on this host with the profiler on, versus 2.3 emulated
seconds per wall second without.

Idle is not the AMX empty-queue spin (`FB00:023A`, never reached once task
7 exists). The UI task busy-polls the key queue:

```
D6E1:000B  (file 56E1B)         task 7 wait for a key
56E29  test word [es:bx+2],FFFF   ; ES:BX = DS:12BC, key queue count
56E2F  jnz  6E41                  ; -> FB00:0725 get message
56E31  mov  cl,[D6AB]             ; periodic kick set by the tick ISR (D620:000E)
56E35  or   cl,cl
56E37  jz   6E29
```

`D6E0:0000` (file `56E08`) is the blocking variant used by modal prompts,
and the BIOS floppy driver polls bit 15 of `DS:[0]` for the completion the
FDC interrupt (IVT 0x0B, `F800:2047`) sets (`F9F3:000E`, `F9D2:000C+48`).
"Idle + waits" below is the cycles in those five loops. **PROVEN** (hot
blocks in `report.md`). There is no HALT anywhere in the image's executed
paths (halted cycles 0 in every window).

---

## 3. Workloads and CPU utilization map

Stock 3.50, 2 MB board, Soft Key 4 cancels the SCSI search at 20 s; CPU
16 MHz; 120 BPM. One run per workload (`emu/profile.py`):

| Window | What is running | Busy | Idle + waits | ISR 09 tick | ISR 08 sys | ISR 0D serial | AMX kernel | task 2 (seq) | task 7 (UI) less idle |
|--------|-----------------|-----:|-------------:|------------:|-----------:|--------------:|-----------:|-------------:|----------------------:|
| idle 30-60 s | Play/Record, nothing | **8.1 %** | 91.9 % | 2.5 % | 0.4 % | 0 | 4.8 % | 3.9 % | 0.7 % |
| seq_rec | REC + PLAY START, 16 pad hits, no sounds | 11.3 % | 88.7 % | 2.9 % | 0.4 % | 0.1 % | 4.8 % | 4.4 % | 3 % |
| seq_play | 2-bar loop, 16 notes/4 s, no sounds | 10.8 % | 89.2 % | 2.9 % | 0.4 % | 0 | 4.8 % | 5.2 % | 1.8 % |
| seq_poly_play | same with 1 s sine on 16 pads, 32 notes | 11.5 % | 88.5 % | 2.9 % | 0.4 % | 0 | 4.8 % | 5.6 % | 1.8 % |
| poly_storm | 66 live pad hits/s with sounds, 14 s | **24.4 %** | 75.6 % | 2.5 % | 0.4 % | 2.6 % | 5.1 % | 16.6 % | 2.3 % |
| midi_in | 20 MIDI notes/s on In 1 with sounds | 14.6 % | 85.4 % | 2.5 % | 0.4 % | 0.8 % | 4.8 % | 7.3 % | 1.7 % |
| ui_tour | one screen change per second | 10.9 % | 89.1 % | 2.5 % | 0.4 % | 0 | 4.8 % | 3.8 % | 3.5 % |
| ui_dial | eight 9-step wheel bursts | 13.1 % | 86.9 % | 2.5 % | 0.4 % | 0.1 % | 4.8 % | 4.0 % | 5.4 % |
| edit_dial | Edit Sound, wheel bursts on Zone end ms | 10.6 % | 89.4 % | 2.5 % | 0.4 % | 0.1 % | 4.8 % | 3.9 % | 2.9 % |
| edit_reverse | Do: REVERSE ZONE on 1.000 s (44,100 frames) | 16.7 % | 83.3 % | 2.5 % | 0.4 % | 0 | 4.8 % | 3.7 % | 9.4 % |
| disk_load_pgm | PGM + 88 KB SND from floppy | 8.8 % | 91.2 % (76 % key poll, 15 % FDC poll) | 2.5 % | 0.4 % | 0 | 4.7 % | 3.9 % | 0.9 % |
| disk_save_snd | 130 KB stereo SND to floppy | 8.9 % | 91.1 % (FDC poll) | 2.5 % | 0.4 % | 0 | 4.8 % | 3.5 % | 1 % |
| boot 0-20 s | reset to SCSI search | 77 % | 23 % | 2.5 % | 0.4 % | 0 | 44 % | 3.8 % | 29 % |

The AMX kernel column is exclusive by address (`FB00`-`FB93`); it is spent
inside the ISRs and tasks (scheduler `01EA` 1.0 %, messaging `03B3`/`06B9`/
`06E8`/`0743`/`0725` ~2.2 %, ISR enter/leave `0157`/`0194` ~0.8 %, wake/wait
~0.5 %). Boot's 77 % is task 7 spinning on an AMX timed-wait primitive
(`FB64:0008`, 755 k calls in 20 s) during the SCSI search; it is wait, not
work, but it is not one of the five idle loops.

### 3.1 Fixed cost that is always paid (120 BPM, transport stopped)

| Item | Cycles | Per second | Share of 16 MHz |
|------|-------:|-----------:|----------------:|
| ISR 09 sequencer tick, inclusive | 2,121 per tick | 407 k | 2.5 % |
| of which AMX `03B3` post of the 12-byte tick message to task 2 | 1,117 | 214 k | 1.3 % |
| of which AMX `0157` enter + `0194` leave + `04AC` wake | 616 | 118 k | 0.7 % |
| of which `D61A` body + sync-out + tempo map (`DA69`, `DA1A`, `DA9B`, `D648`, `D620`) | ~390 | 75 k | 0.5 % |
| task 2 per-tick body `EC05:0043` (dequeue, `DD8A:000E` event drain, 5 serial ring reads) | 1,953 per tick | 375 k | 2.3 % |
| AMX `01EA` select on every switch | ~830 per tick | 159 k | 1.0 % |
| ISR 08 system tick (AMX timer walker, `FB58`, `FA05`, `D219`) | 582 per tick | 58 k | 0.4 % |
| sum | | ~1.0 M | **~6.3 %** of the 8.1 % idle busy |

Playing adds 285 cycles per tick to the ISR (2,406) and ~1,000 to the task
body (2,989 with notes due). At 300 BPM (480 ticks/s) the same fixed cost is
~16 %. **PROVEN (trace)**; tempo scaling is arithmetic.

### 3.2 Per-event costs

| Event | Cycles | Time at 16 MHz | Where | Tag |
|-------|-------:|---------------:|-------|-----|
| Serial byte received (panel link or MIDI) | 1,053 | 66 µs | IVT 0x0D `D547:0067`: AMX enter/leave 383, parser `D557:0005` 356, body 291 | PROVEN (poly_storm, 5,601 bytes) |
| Saturated MIDI input, one port (3,125 bytes/s) | 3.3 M/s | | 20.5 % of the CPU per port, inside an ISR | arithmetic from the row above |
| Pad hit (press + release = 6 link bytes) | 6.3 k + note-on | | | |
| Note-on layer `CFC6:039E` (from `CFB3:0008` → `CFC6:0007` in task 2), all voices busy | 23,342 | **1.46 ms** | arithmetic in `039E` with 16 far calls into the BIOS 32-bit runtime (`F800:20C4` mul, `20FA` signed div, `2101` unsigned div, `21A8` shl); allocator `CF37:0002` 7.5 k when it must steal a voice; DSP writes `D1F7`/`D209`/`D21A` 1.3 k | PROVEN (poly_storm, 933 note-ons, 1 s sound) |
| Same, free voices, 50 ms sound | 13,633 | 0.85 ms | divides 7.6 k (56 %), allocator 662 | PROVEN (S1 characterization, 640 note-ons; section 9) |
| LCD character via INT 43 AX=4 | 433-671 | 27-42 µs | class walk `F800:1752` 354, `F800:1744` 333, `F984`/`F985` put 277/89 | PROVEN (ui_dial) |
| Screen change (ui_tour) | ~1.0 M | ~60 ms | 330 k BIOS + 660 k app formatting per screen | PROVEN (15 screens) |
| Wheel step on Play/Record (ui_dial) | ~107 k | 6.7 ms | field repaint through `E0D5:0004`/`E0E4:000A` and INT 43 | PROVEN (72 steps) |
| REVERSE ZONE, per frame | ~218 | 13.6 µs (0.6 s per second of audio) | `BBA2:0005` loop, `F800:20FA` 22 k calls (all on its 133-cycle `DIV` path), `CF94:0005` copy | PROVEN (1.000 s zone) |
| Floppy load / save | ~0 CPU | | BIOS polls DS:[0] bit 15; FDC ISR 0x0B 98 cycles per sector interrupt | PROVEN |

---

## 4. Headroom estimate

| Situation | Free CPU (16 MHz) | Basis |
|-----------|------------------:|-------|
| Play/Record idle, playback of ordinary material, UI use | **86-92 %** | windows above |
| Heaviest measured: 66 live hits/s with sounds | 76 % | poly_storm |
| Worst sustained case the model admits: 300 BPM, three saturated serial inputs, 100 note-ons/s | ~16 % tick + 61 % serial ISR + 15 % note-on = **92 % busy, 8 % free**, with interrupts disabled for 66 µs per byte | arithmetic, **HYPOTHESIS** (no such run) |
| Burst case: a 16-pad chord with sounds | 16 × 1.46 ms = 23 ms of task-2 time, 4.5 ticks at 120 BPM | PROVEN per note, spill behaviour **HYPOTHESIS** (section 5) |

The sustained headroom is large; the real exposure is latency and burst
serialization in task 2, not average load. Scale every row by the
section 1.3 uncertainty (±25 %) and by `U-READY` (LCD/DSP waits only add).

---

## 5. Timing and determinism risks (read before optimizing)

1. **Pad and MIDI events are consumed only when the tick ISR wakes task 2.**
   In this trace the serial ISR `D547:0067` calls `0157`, `D557:0005`,
   `DA0C:0000`, `D9F2:000C`, `0194` and never `04AC`; `DD8A:000E` (the
   drain) runs 2× per tick from `EC05:0043`. Pad-to-voice latency is
   therefore 0-1 sequencer tick (0-5.2 ms at 120 BPM, 0-10.4 ms at 60 BPM)
   plus 1.46 ms, and it varies with tempo. **PROVEN (trace, these runs)**;
   other wake paths (`04AC DL=2` sites at files `0x55E67` in ISR 0x0C and
   `0x56992`) are **UNDETERMINED** because 0x0C never fired here. Hardware
   test H4.
2. **Note-ons serialize in task 2 at 1.46 ms each.** A chord denser than
   ~3 notes per tick at 120 BPM spills into the next tick; the ISR keeps
   counting ("late ticks replayed", `sequencer_model.md`), so timing shifts
   by whole ticks rather than drifting. Any change to the note-on path must
   keep the DSP write sequence per note identical (section 9 oracle).
3. **Serial input runs at 66 µs per byte inside an interrupt** (nested
   interrupts allowed after the AMX enter, `STI` in the handlers). Three
   busy inputs reach 60 % ISR time and delay the tick ISR by up to 66 µs
   each byte: tick jitter on the MIDI clock out. Hardware test H3.
4. **Transport changes are quantized to the tick** (`sequencer_model.md`
   §2.3). Any edit to `D61A:000A`, `03B3` or `EC05:0043` changes that
   quantization and the overflow-forces-stop rule (`[9644]`); the
   `emu/seq_evidence.py` vectors are the regression.
5. **Every emulator duration before this note was at 2× CPU speed**
   (section 1.1). Re-derive any CPU-bound claim before relying on it.
6. **MAME over-charges CALL and under-charges taken branches** (1.3): a
   change that trades calls for inline code will look better in MAME than on
   the board; measure on hardware (H2) before claiming a saving smaller
   than ~25 %.

---

## 6. ROM space map (union of all nine runs; dynamic, not all-paths)

| Class | Bytes | Fetched | Read as data only | Untouched | Reclaimable? |
|-------|------:|--------:|------------------:|----------:|--------------|
| Owned code | 131,128 | 50,580 | 25 | 80,523 | Only the 50,580 are shown live; the 80,523 never ran in these workloads (SMPTE, song, MIDI dump, SCSI, sampling, help pages not exercised). **Not** reclaimable without a consumer-based proof per range; `report.md` lists the 25 largest |
| Patch-write banks (`0xFF`, no PGR page selects them) | 147,372 | 0 | 0 | 147,372 | **Yes** ([`patch_space.md`](patch_space.md)); `0x0FFEF` landing rule applies |
| PGR-selected `0xFF` filler (`[0x27CB0,0x30000)`, `[0x707C8,0x74000)`, `[0x7A78E,0x7AC00)`, `[0x7AF6A,0x7B00C)`, `[0x7BA01,0x7FF00)`, `[0x7FF44,0x7FFF0)`, small) | 67,153 | 0 | 0 | 67,153 | **Probably** (HYPOTHESIS): addressable, but no fetch or data read in any run and no direct transfer into them (D16). A static all-paths proof needs every memory-operand translation; add the read-coverage assertion to the suites before using them |
| DGROUP image `[0x20000,0x27C92)` | 31,890 | 0 | 31,890 | 0 | No (copied to RAM at boot) |
| Tables, PGR images, create table, IVT template | ~1,900 | 2 | 843 | ~1,050 | No; the untouched parts are table entries not selected here |
| Unowned gaps | 144,420 | 8,547 | 198 | 135,675 | Unknown. The 8,547 fetched bytes are code the ledger has not opened (largest: `[0x399A2,0x3DE3E)` 1,906 B, `[0x35098,0x370F1)` 1,273 B, `[0x4C5C9,0x4EBCC)` 1,231 B, `[0x4AC4E,0x4C512)` 1,056 B, `[0x783D8,0x78EE3)` 859 B in the BIOS page): ledger debt, D17 |

Patchable from a floppy (Route A): app ROM `[0x30000,0x74000)` and DGROUP.
The BIOS pages `[0x78000,0x80000)` (BIOS, FAC0, AMX) are EPROM-only
([`floppy_loader.md`](floppy_loader.md)); anything in the backlog that
touches them is an EPROM build.

---

## 7. Optimization backlog

Ranked by (real-time cycles saved × certainty) ÷ risk. "Cycles" are at
16 MHz from section 3; ROM is bytes added to the app ROM unless marked
BIOS. Speed and size are separate lists; nothing here mixes them.

### 7.1 Speed (real-time paths)

| # | Change | Saving | ROM | Risk | Complexity | Notes |
|---|--------|--------|-----|------|------------|-------|
| S1a | **Fast exact divide at the note-on call sites. Implemented** (`mods/s1a.asm`, `mods/S1A.args`, section 9.6). All 17 `CALLF F800:20FA` / `F800:2101` sites in `CFC6:039E` call a 116-byte cave routine: two `DIV r/m16` steps when the divisor high word is 0 and the low word is not, else a tail jump to the runtime | measured: layer 13,633 → 7,530 cycles (−45 %) on the default program, 18,370 → 9,725 (−47 %) on the varied one; divide 917 → 158 cycles per call | +116 cave, 85 bytes patched (app ROM, Route A) | **low**: no result changed in 960 traced S1a note-ons; executes identically to the runtime on 6,800 edge and random operand pairs | done | Hardware H4/H7 pending |
| S1b | Per-pad cache of the velocity-independent blocks (B, D, E) | ~1.2 k per layer after S1a | +~400, RAM | medium: invalidation on every record writer; velocity independence holds only while the velocity sensitivities are 0 (section 9) | medium | Deferred: little left after S1a |
| S2 | **Lean serial receive.** Enter the ring-buffer byte path without the AMX `0157`/`0194` wrapper when the handler wakes nothing (it never does in this trace); keep the wrapper only for the frame-complete path if one is found | 383 of 1,053 cycles per byte (−36 %; 7 % CPU per saturated port) | +~60 | medium-high: `0157` is also the ISR stack switch, so the parser then runs on the interrupted task's stack (needs ~40 B spare on every task stack: `amx_create_table.md` SS:SP values); nested-interrupt behaviour must be checked on hardware (H3) | low-medium | app ROM (`D547`) |
| S3 | **Gate the per-tick ring drain.** `EC05:0043` reads five serial rings every tick (`D8BD:000C` ×5, `D8CC`/`D8CE`/`D8D6`) whether or not bytes arrived; a "pending" word set by ISR 0x0D skips them | ~800 of 1,953 cycles per tick (0.9 % at 120 BPM, 2.4 % at 300) | +~40 | low-medium: the drain order between rings must not change | low | app ROM |
| S4 | **Replace the tick message when stopped.** `03B3` posts 12 bytes per tick (1,117 cycles); when `[D800] < 6` and no event is due, a direct `04AC` wake (177) would do | ~940 per tick (1.1 % at 120 BPM, 2.8 % at 300) | +~50 | high: the message snapshot is the documented transport contract; overflow-forces-stop and the stop/start quantization depend on it | medium | Do after S3 and only with the seq_evidence vectors green |
| S5 | **Field-local repaint on wheel steps.** 107 k cycles (6.7 ms) per step; the stock path repaints the line through INT 43 per character | ~50-70 % of the step cost | +~200 | low (display only) | medium: the painter (`E0D5:0004` / `E0E4:000A`, `C44E` in `pad_note.md`) must be mapped per field | Matters for the 8-key stock queue (bursts beyond 9 steps drop) |
| S6 | **INT 43 fast path for printable characters.** Skip the class walk `F800:1752` (354) for `0x20-0x7E` | ~40 % per character; screen change 60 → 45 ms | +~40 **BIOS (EPROM only)** | low | low | Worth nothing if the LC7981 busy wait dominates on hardware (H5) |
| S7 | AMX scheduler `01EA` (1.0 %) and ISR enter/leave | small | | kernel | | Not recommended |

### 7.2 Background and precompute enablers

| # | Change | Gain | ROM | Risk | Complexity |
|---|--------|------|-----|------|------------|
| B1 | **Background slice in the UI poll loop.** Hook the `jz 6E29` back-edge at file `0x56E37` to call a bounded worker (≤ 1 ms, returns when the key-queue count is non-zero). This turns the 85-92 % idle time into usable time for S1 table builds, directory caching, waveform caches, without touching any ISR | all of the idle time, with key latency bounded by the slice | +~30 hook + workers | low: the loop already tolerates `0725` calls; the worker must not post to task queues (it runs as task 7) | low |
| B2 | Move Edit Sound Do-operations (REVERSE at 218 cycles/frame, ~0.6 s per second of audio) to a word-copy loop with the 32-bit runtime hoisted out (`FA0F` is called 22 k times for 44 k frames) | 3-4× faster edits | +~150 | low (not real time) | low |

### 7.3 Size (ROM)

| # | Change | Gain | Risk | Notes |
|---|--------|------|------|-------|
| Z1 | Use the patch banks | 147,372 B available now | none beyond `0x0FFEF` | `patch_space.md` |
| Z2 | Use the PGR-selected filler | 67,153 B | low after a read-coverage assertion (no run may read them; add to `emu/test_mpc3k.py` with `cov_read.bin`) | HYPOTHESIS until asserted |
| Z3 | Reclaim never-executed owned code | up to 80,523 B | **high**: dead-in-nine-workloads is not dead; SMPTE/song/dump/SCSI/sampling were not driven | Needs feature workloads first, then per-range consumer proofs |
| Z4 | Compact the AMX create/kernel data | negligible | | Not worth it |

Speed items cost ROM; size items free it. Only Z1/Z2 are safe today.

---

## 8. Hardware validation (deferred; physical MPC3000 with a logic analyzer)

Instrumentation is a Route A floppy mod (no EPROM), toggling one LED-latch
bit the current screen does not drive (`OUT 0x00` or `0x20`, write-only HC259;
pick a bit from `MAME_MPC3000_maps_irqs_roms.md`, 1 µs pulse), probed with
the analyzer; passive probes only, audio muted, NVRAM backed up first, abort
if any screen differs from the emulator's.

| ID | Measurement | Closes | Expected (16 MHz model) |
|----|-------------|--------|-------------------------|
| H1 | CLKOUT pin period (also the FDC clock input) | 1.1 on the board | 62.5 ns |
| H2 | Pulse at entry and exit of `D61A:000A` (tick ISR) and of the UI poll back-edge: ISR duration and the free-time duty | `U-V53-TIMING` ratio MAME/board; 1.3 | 133 µs per tick stopped, 150 playing; 86-92 % duty idle |
| H3 | Pulse per serial ISR with a 31250-baud flood on MIDI In 1 (then In 1 + 2): ISR length, tick-ISR delay, MIDI clock out jitter on a MIDI analyzer | S2 feasibility; risk 3 | 66 µs per byte; 20 % per port |
| H4 | Panel TXD link frame → DSP `0x60` write strobe (L7A1045 /CS) at 60, 120, 300 BPM; and MIDI In note → strobe | risk 1 (tick-gated drain), S1a | 1.5 ms + 0-1 tick, tempo dependent |
| H5 | LC7981 E/RS/CS and the `0xE2` status reads per character write | `U-READY`, S5, S6 | MAME: 0 wait |
| H6 | TCT1 output edge → first ISR instruction pulse | interrupt response (1.3) | MAME ~10 clocks |
| H7 | Repeat H2 and H4 with S1a applied and the same sequence | the first experiment's saving | about −6 k cycles per layer |

---

## 9. S1 characterization (done 2026-10-13) and the revised first experiment

Reproduction: `python3 -m emu.s1_characterize` (three MAME runs, about 25 s
wall) writes `build/emu/s1/report.md` and `result.json`;
`python3 -m unittest emu.test_s1_characterize` re-checks the conclusions.
Method: fork trace points (section 10) snapshot registers and memory at the
entry of `CFC6:039E`, at each of its 26 far calls into the runtime and at
the instruction after each, and log every DSP port access `0x60`-`0x6F`. No
ROM, RAM or OS state is modified. MIDI In 1 channel 1, notes `0x23`-`0x62`
(all 64 pads) × velocities 1, 32, 64, 100, 127. Runs: `default` (native
blank program, every pad on one 50 ms mono sound), `default_rev` (same notes
in reverse order, shifted by half a sequencer tick), `varied` (stimulus
bytes in every note-record field the routine reads, a 1 s stereo sound with
volume 77 and tune −12).

### 9.1 Corrected names

The section 3 profile named routines by the nearest known entry. Corrected
from the bytes and [`mute_voice.md`](mute_voice.md):

| Report name | Real entry | File | Role |
|-------------|-----------|------|------|
| `CFFF:000E` | `CFC6:039E` | `0x4FFFE` | per-layer note-on arithmetic and voice start (called by `CFC6:0007` once per base or SIMULT layer) |
| `D011:0000` | `CFC6:04B0` | `0x50110` | inside `039E`, after the `JMP CS:[BX+0B25]` variation switch; not an entry |
| `D078:000D` | `CFC6:0B2D` | `0x5078D` | voice start: resource, allocator, DSP writes |
| `FA0F:000A`, `FA10:0001`, `FA11:0001`, `FA1A:0008` | `F800:20FA`, `F800:2101`, shared body `F800:2114`, `F800:21A8` | `0x7A0FA`, `0x7A101`, `0x7A114`, `0x7A1A8` | BIOS 32-bit runtime: signed divide, unsigned divide, their body, shift left; `F800:20C4` (`0x7A0C4`) is the 32×32 multiply |

`F800:2114` (**PROVEN**, bytes): `CX` selects signed divide, unsigned divide,
signed remainder or unsigned remainder. If the divisor's high word and the
dividend's high word are both 0 it executes one `DIV BX`. Otherwise it
negates negative operands and runs a 32-iteration shift-subtract loop. Every
long-path call ran the loop body exactly 32 times (`F800:215F`).

### 9.2 Static inputs of `CFC6:039E` (**PROVEN**, code)

There is no `0F E0`/`0F F0` in `[0x4FFFE, 0x50785)`. The routine's own
memory operands are its stack frame and these:

| Source | Fields |
|--------|--------|
| `[BP+8]` event | `+0 & 3` variation type (switch at `0469`), `+3` velocity, `+4` variation value |
| `[BP+0Ch]` note record (the 0x18-byte PGM record) | `+0` sound index (`FF` returns), `+6`-`+8`, `+9` word, `+0Bh`, `+0Ch`, `+0Eh`-`+16h` |
| sound record `A2AE:4800 + 24h × index` | `+0`, `+11h`-`+13h`, `+14h`-`+22h` |
| `[BP+10h]`, `[BP+14h]` | 2 + 2 bytes (output level and pan inputs of the DSP writes) |
| `[E5F9]` far pointer | note records of the cutoff notes `+7`/`+8` when ≥ `0x23` |
| DGROUP | `[E739]`; tables `7346` (101-word quadratic time curve), `74DA` (101-word level curve), `7164` (pitch, index clamped to ±0xF0), `7410` (pan law), `75A4` (16 bytes) |

Tempo and sequencer state are not among them, so tempo cannot change this
routine's arithmetic. The callees `CFC6:0B2D`, `CF37:0002` and `D1F7` are
not covered by this statement. The runtime helpers use only registers and
their own stack frame (**PROVEN**, bytes `[0x7A0C4, 0x7A1DE)`).

### 9.3 Results (**PROVEN (trace)**, these 960 note-ons)

| Check | Result |
|-------|--------|
| Default program path | Blocks B C D E G on every note; exactly 16 runtime calls per layer (mul ×4, signed div ×8, unsigned div ×2, shl ×2); all 640 reach the `0B24` return |
| Varied program | 23 runtime calls at most; 7 block combinations; 23 notes leave at `06E2` (velocity-scaled start beyond the sound end, no voice) |
| Same operands → same result | 2,719 distinct operand sets, 0 with two results |
| Same input tuple → same call list | 319 tuples repeated across the two default runs (other order, half-tick shift), 0 differences |
| Runtime arithmetic = Python model | 0 mismatches over all calls |
| DGROUP tables | byte-identical at every entry |
| DSP sequence per input tuple, channel normalized | 0 tuples with two sequences; 22 accesses per mono layer, 43 per stereo note |
| Velocity dependence, default program | blocks B, D, E (10 calls) never change with velocity; blocks C, G (6 calls) always do (level → C, level × decay → G) |
| Velocity dependence, varied program | every block varies with velocity for some pads (velocity → filter feeds A, → start feeds B, → attack feeds D and F) |
| Divide operands | every one of 9,978 divides has a divisor in 1..0xFFFF; every signed quotient fits 16 bits |
| Two-step `DIVU` model | exact on 9,978 of 9,978 traced divides, 0 fallbacks |

Cost (inclusive cycles per call at 16 MHz):

| Routine | default | varied |
|---------|--------:|-------:|
| `CFC6:0007` builder | 14,404 | 19,141 |
| `CFC6:039E` layer | 13,633 | 18,370 |
| `CFC6:0B2D` voice start | 2,686 | 2,835 |
| `CF37:0002` allocator (free voices) | 662 | 679 |
| `F800:20FA` signed divide | 917 | 893 |
| `F800:2101` unsigned divide | 150 | 1,083 |

Solving the two runs' long-path and short-path counts against the runtime's
self-cycles gives about **1,446 cycles per long-path divide** and 133 per
short-path divide. Divides are 7.6 k of the 13.6 k cycles in a default
layer. The long path is taken whenever the dividend exceeds 16 bits or is
negative. Examples are the 1 s sound's start-offset arithmetic, every
`(x << 12) / 10`, and the negated decay terms.

### 9.4 Consequences for S1

- **The planned precompute is the wrong first move.** With default
  velocity sensitivities only blocks B, D and E are velocity-independent.
  Any non-zero sensitivity makes every block velocity-dependent. A cache
  therefore needs the velocity in its key or an invalidation rule tied to
  the sensitivity fields. After S1a it would save about 1.2 k cycles (S1b,
  deferred).
- **S1a, a fast exact divide at the call sites, takes most of the win with
  none of the state.** It is implemented and measured in 9.6.

### 9.5 Correction: 17 divide call sites, not 14

`CFC6:039E` holds 15 `CALLF F800:20FA` and 2 `CALLF F800:2101`, and no
others (byte scan of `[0x4FFFE, 0x50785)`). The signed sites at `0858` and
`085F` are on the variation-type-1 path (`[BP+18h] != 0`), which no traced
note took, so the 9.3 operand table lists 14 sites. S1a redirects all 17.

### 9.6 S1a implemented (2026-10-13)

| Item | Value |
|------|-------|
| Source | `mods/s1a.asm` (cave, 116 bytes at `F07D:0000`, file `[0x707D0, 0x70844)`); `mods/S1A.args` (17 patches `9A FA 20 00 F8` / `9A 01 21 00 F8` → `9A` + cave entry) |
| Build | `python3 mods/build_mod_sys.py @mods/S1A.args` → `build/mods/S1A.SYS`, `.img` (Route A; boots as the first `*.SYS` on a floppy) |
| Entries | `s1a_idiv` `F07D:0000` (signed, replaces `F800:20FA`), `s1a_udiv` `F07D:0048` (unsigned, replaces `F800:2101`) |
| Contract | The runtime's: operands on the stack, quotient in `DX:AX`, `RETF 8`; `BX`, `CX` clobbered; `SI`, `DI`, `BP`, `DS`, `ES` kept. No instruction after any of the 17 call sites reads `BX`, `CX` or the flags before writing them (disassembly) |
| Fast path | divisor high word 0, low word non-zero: two `DIV r/m16` on the dividend's magnitude (high word, then remainder:low word, which cannot overflow), quotient negated for a negative signed dividend. Stack only, so re-entrant |
| Fallback | any other divisor, including 0: `JMP FAR` to the runtime with the caller's stack untouched, so the runtime's divide fault or all-ones quotient is unchanged |
| Changed bytes | only the cave and the 17 × 5 call-site bytes (`tests/test_s1a_divide.py`) |

Static check, `tests/test_s1a_divide.py` (**PROVEN**, execution of both
byte streams): a 16-bit interpreter runs the stock runtime
`F800:20F7`-`21A5` from the pinned image and the assembled cave on 400
edge pairs (0, ±1, `0x7FFF`/`0x8000`, `0x7FFFFFFF`, `0x80000000`,
`0xFFFFFFFF`, divisors 0, `0xFFFF`, `0x10000`, …) and 3,000 seeded random
pairs per entry. Quotient, divide fault (20 cases per entry, all
divide-by-zero), popped bytes and preserved registers agree on every
case. A mutant that skips the final negation disagrees on 800 cases, so
the check discriminates. On the fast path the cave returns without
fetching from `F800`.

Emulator check, `python3 -m emu.s1_characterize`, now seven runs: stock
EPROM (`default`, `default_rev`, `varied`), Route A control `ctrl_default`
(`S1CTRL`: only the builder's mandatory loader patch and demo string), and
Route A S1a (`s1a_default`, `s1a_default_rev`, `s1a_varied`). Same MIDI
input in every run; the notes start at 46 s, because the S1a disk's
310 KB `STARTUP.SYS` delayed the stereo sound's load past 42 s and the
first eight notes were lost in an earlier run. Under Route A, `CFC6` runs
from RAM at physical `0x300000 + 20-bit` and the cave at `0x3F07D0`.

| Check (**PROVEN (trace)**, 2,240 note-ons) | Result |
|-------|--------|
| Input tuples traced in both stock and S1a | 640 of 640 |
| Same input tuple → same 039E call list (sites, operands, results) | 0 differences |
| Same input → same parameter blocks handed to `CFC6:0B2D` | 0 differences over 2,608 voice starts (bytes 039E writes on every path; `[BP-35h]`, block-A-only and output bytes excluded) |
| Same input → same DSP access sequence on the note's own stack, channel normalized | 0 differences |
| Control run vs stock | identical results; layer 13,682 vs 13,633 cycles (+0.4 %): running from RAM is cost-neutral |

| Cost, inclusive cycles per call at 16 MHz | stock | S1a |
|------|------:|----:|
| `CFC6:039E` layer, default program | 13,633 | **7,530** (−44.8 %) |
| `CFC6:039E` layer, varied program | 18,370 | **9,725** (−47.1 %) |
| `CFC6:0007` builder, default | 14,404 | 8,306 |
| signed divide | 917 (`F800:20FA`) | 158 (`s1a_idiv`) |
| unsigned divide | 150 / 1,083 (default / varied) | 121 (`s1a_udiv`) |

Every divide of `039E` reached the cave: the calls routed to `F07D` equal
the divide calls traced in the matching stock run. The six `F800:20FA` and
22 `F800:2101` calls left in the S1a windows come from elsewhere in the OS.
A 16-pad chord on the default program now costs about 8.3 ms of task-2
time instead of 14.4 ms with free voices.

Attribution fix found on the way. Two higher-priority contexts can run
inside a note-on window: AMX task 1 (`B259:0006`, `SS=91C5`) stops voices
whose remaining time ran out (`D21F` sequences), and interrupt handlers
can run too. Because S1a moves each note-on about 0.5 ms earlier, some of
those stops fell inside a window in one build and outside it in the
other, and four varied-program notes appeared to differ. The fork's I/O
trace now records `SS`, and the comparison keeps only accesses on the
note's own stack. That excluded 84 accesses, all on `SS=91C5`. The
allocator's mutable inputs (`DS:E410` remaining times, `E599` owners,
`E597`, `D0AD`) differed in 178 of 320 varied notes, through those
time-dependent countdowns, and every allocation decision still matched.
That is one execution. The allocator can choose a different victim when
note timing shifts, as it already does when a player's timing shifts.

### 9.7 Next

1. Hardware: boot `S1A.img` on the bench machine. Then run H4
   (pad/MIDI → DSP strobe latency) and H7 (tick-ISR duty with a dense
   sequence) against the stock EPROM.
2. Combining with WAVE: WAVE patches `0x502FD` and `0x504F7`. Those sit
   directly after the S1a sites `CFC6:0698` and `0892`, adjacent but not
   overlapping. A combined build needs the cave labels merged and a re-run
   of the WAVE and MUTE suites. Nothing in WAVE was changed here.

---

## 10. Fork changes (committed `b4ab57e6`, pinned)

The profiler (section 2), `NEC_CPU_DIV` (1.1) and the trace points
(`NEC_TRACE_FILE`, `NEC_TRACE_AT`, `NEC_TRACE_IO`, `NEC_TRACE_FROM`:
register and memory snapshots at chosen physical instruction addresses,
and external I/O with data and the accessing stack segment; grammar in the
comment above `trace_start()` in `nec.cpp`) are fork commit `b4ab57e6` on
`mpc3000-accuracy`, pinned in `emu/README.md`. All three are inert unless
their environment variables are set.

The commit sits on four fork commits that landed after `14ffa559`:
`0d671188` (TE7774 TxRdy when idle, interrupt gated by control 3; MIDI for
a host app), `da10ed84` (merge), `29ffba78` (L7A1045 volume envelope) and
`a9d005de` (L7A1045 key-on starts every voice set up since the last
key-on). On the new pin, these pass: `emu.test_mpc3k`, `emu.test_profile`,
`emu.test_s1_characterize`, `emu.test_mute_voice` and
`emu.test_wave_playback` (53 tests). Every section 3 and 9.3 figure is
unchanged. The S1a varied layer moved from 9,789 to 9,725 cycles because
voice timing follows the new envelope; section 9.6 shows the new values.
The full `MPC3K_RELEASE=1` set (22 suites, all 3.16 BIOS sets) has not
been run on this pin.

---

## 11. PMONEY BETA 1.0 audit (2026-10-13)

Target: the released `STARTUP.SYS` (`WAVE316.SYS`, SHA-256 `d8074538…`; the
harness build is byte-identical), OS 3.16 plus the WAVE/ZONES/MUTE GROUP
cave, on the Vailixi 3.50 EPROM set (load segment `6900`). Baseline: the
hash-pinned `M3K316.SYS` on the same set and disk layout. Reproduction:
`python3 -m emu.pmoney_profile` (eight MAME runs, about 30 s wall) writes
`build/emu/pmoney/report.md`. The harness's 3.16 timelines were measured
with the core at the crystal rate, so these runs keep `NEC_CPU_DIV=1`.
Cycles per event do not depend on the core clock; every time below is
cycles / 16 MHz. Idle means the 3.16 key-wait loops (image `2D0DB`,
`2D0BA`, `2D175`, the same bytes as Vailixi `D6E1:000B`/`D6E0:0000`) and
the BIOS floppy polls. **PROVEN (trace)** for these executions.

### 11.1 What the features cost

| Path | Stock 3.16 | PMONEY | Note |
|------|-----------:|-------:|------|
| Idle on Play/Record | 8.2 % | 8.2 % | no idle overhead; also 8.2 % with the waveform view open |
| Note-on, mute groups disabled | 14,656 cycles (builder) | **20,818** (wrapper, builder inside) | +6.2 k; window busy +6.4 k per note |
| Note-on, mute groups enabled (4 groups) | — | 23,840 | +9.2 k; includes the choke stops |
| Audition hooks inside the note-on routine | — | ~52 cycles per note | negligible |
| CHOP of 4 zones (55,125 frames) | — | 10 % busy over 23 s | stock sound creation; the cave's own share is 7 k cycles |
| `STARTUP.SYS` size | 458,047 B | 471,043 B | +2.8 % floppy load |
| Cave (RAM above 3.16) | — | 12,995 B | home limit 24,576 B with `L=7000` (3.08/3.11), 53,248 B with `L=6900` |
| Sequence memory | 439K (overlaps code on 3.12/3.50) | 411K | the deliberate pool-end fix of `port_316.md`, not a feature cost |

Where the mute-disabled overhead goes, per note:

| Item | Cycles |
|------|-------:|
| `T_D9F2_003D` pad lookup in `mute_note_on_wrapper` (stock already calls it twice per note, at image `0x3086B` and `0x03266`) | 5,029 |
| `T_D1F7_0126` re-reserve in `mute_voice_alloc_wrapper` on every allocation | 339 |
| Enable check, frames, allocator-wrapper bookkeeping | ~700 |

`T_D9F2_003D` (3.16 `301D:003B`, image `0x3020B`; **PROVEN**, bytes) scans pad slots
0..63 through a near helper per slot. The helper reads the slot's note
from `DS:[8064+slot]` when `[8063]` is set, else from
`program record + 0x73E + slot` (`[E2E6]`). It returns the first match,
or `FFFF` below note `0x23`. Neither stock caller leaves a per-task
result: both store the global "last pad" `[D399]`, which is what the
wrapper's frame-only design avoids.

Waveform view, one redraw (inclusive cycles, 16 MHz time):

| Redraw | Cycles | Time | Breakdown |
|--------|-------:|-----:|-----------|
| Full view, wheel step | ~996 k | 62 ms | stock blit `1650:0F01` 598 k (1,920 bytes, ~311 cycles each); `refresh` 398 k, of which 11-12 `text` calls 145 k |
| Fine view, wheel step | ~1.73 M | 108 ms | `scan` 815 k (`fill` 541 k reads 9,216 sample words every step), draw and text ~335 k, blit 578 k |
| Zone navigation | ~858 k | 54 ms | 15 redraws for Right x3 and 12 wheel steps |
| Open (full scan, 55,125 frames) | 5.29 M | 0.33 s | ~96 cycles per frame, linear in length: a 20 s mono sound would take about 5.3 s (**HYPOTHESIS**, arithmetic) |

A 9-step wheel burst gives two redraws: the first, then one for the
coalesced rest. The view runs in the UI task, which the tick ISR and the
playback task preempt, so its cost affects responsiveness, not timing.

### 11.2 Opportunities, ranked

| # | Change | Saving | Size | Risk |
|---|--------|--------|------|------|
| P1 | **Port S1a.** 3.16's note-on layer (image `0x21274`, 122 of 1,927 bytes differ from Vailixi `CFC6:039E`) makes the same 15 signed and 2 unsigned divide calls into its own linked copy of the runtime, relative `0009:20F6`/`20FD` (image `0x2186`, byte-identical to `F800:20FA`). Redirect them to the S1a cave routine with the fallback relocated to that copy | ~6 k cycles per layer, mute on or off | +116 B cave, 85 B patched | low: the S1a routine, its static test and the characterization method carry over; the fallback target is relocated |
| P2 | **Inline the pad lookup.** In `mute_note_on_wrapper`, `REPNE SCASB` over the same 64-byte table the stock helper reads (DGROUP `8064` when `[8063]`, else `[E2E6]+0x73E`), first match, `FFFF` below `0x23`; call the stock routine for notes `≥ 0x80`, where its sign extension differs | ~4.7 k per note | ~+40 B | low: same table, same first-match rule, read at the same moment; check against the stock routine over every note and both table modes, and run the mute suites |
| P3 | **Re-take resource 1 only after a choke stop.** Move `FCALL T_D1F7_0126` under the stop path; the wrapper's own comment says it is a no-op unless `D21F` dropped the lock | 339 per note | −5 B | low |
| U1 | **Fine view reads only what it shows.** Fill only the window's samples (240 x zoom), and on a step reuse the overlapping columns, scanning only the new ones | ~0.6-0.8 M per fine step | small | low, display only |
| U2 | **Static text once.** Render the title, labels and soft keys into a saved layer and copy it per redraw, or redraw only changed text | ~130 k per redraw | +1,920 B RAM if a full layer | low |
| U3 | **Partial LCD update.** Send only the changed bytes or rows instead of the stock full blit | up to ~0.5 M per redraw | +~150 B | medium: a cave LCD write path; needs the LC7981 hardware test H5 |
| U4 | **Faster open scan.** Tighten the min/max loop; draw progressively for long sounds | up to ~40 % of 96 cycles per frame; measure first | small | low; the sample read is stock (`T_CF92_000C`) |
| Z1 | Overlay `mute_staging` (792 B, the APS load staging copy) with the view's column arrays (960 B), which are idle during disk I/O | 792 B | — | only if space is needed: 11.6 KB of headroom remain on 3.08/3.11 |

P1-P3 together take PMONEY's note-on from about 20.8 k cycles with mute
groups disabled to about 9.8 k, a third below stock 3.16 (14.7 k). With
groups enabled it drops from about 23.8 k to about 12.8 k (estimate from
the measured parts; the choke work itself is unchanged). U1-U3 would take
a full-view wheel redraw from about 62 ms to about 25 ms and a fine-view
step from about 108 ms to under 50 ms (**HYPOTHESIS** until built).
Nothing else measured shows waste: idle, playback hooks and CHOP are
already at stock cost.

---

## 12. PMONEY note-on fixes P1-P3 (2026-10-13)

Implemented in the shared cave source, so P2 and P3 apply to every build
(WAVE generic, WAVEHW capture, WAVE316 = PMONEY). P1 is PMONEY only.

| Fix | Change |
|-----|--------|
| P1 | `mods/s1a_divide.inc` holds the S1a routines. `mods/s1a.asm` (the 3.50 Route A mod, unchanged bytes: same `S1A.SYS` SHA-256 `020328c1…`) and `mods/wave.asm` under `PROFILE_316` include it. In PMONEY the fallbacks `FJMP` to `T_F800_20FA` = `0009:20F6` and `T_F800_2101` = `0009:20FD`, 3.16's linked copy of the runtime. `mods/WAVE316.args` redirects the 17 calls of the note-on layer (image `[0x2141C, 0x2182C)`) to them |
| P2 | `mute_pad_of_note` in `mods/mute_voice.inc` replaces the wrapper's `FCALL T_D9F2_003D`: `REPNE SCASB` over the same 64 bytes (`MUTE_PAD_NOTES` while `[MUTE_PAD_MODE]`, else `[MUTE_RECORD]+73Eh`), `FFFF` below `23h`, the stock call for notes `≥ 80h`. New profile symbols: `MUTE_PAD_MODE`/`MUTE_PAD_NOTES` = `8375`/`8376` (generic), `8373`/`8374` (capture, read from `ROMAPP.BIN`), `8063`/`8064` (3.16) |
| P3 | `mute_voice_alloc_wrapper` re-reserves AMX resource 1 (`T_D1F7_0126`) only when its scan stopped a channel (`SI` flag) |
| Builder | `NOT_OPERANDS` in `mods/build_wave316.py` lists two operand coincidences with the new runtime segment `0009`: a `CALL FAR` offset word and `MOV BX,9` (a text column) |

Size: the PMONEY cave grows from 12,995 to 13,181 bytes, still under the
24,576-byte home limit of the 3.08/3.11 EPROMs. The generic and capture
caves are 12,878 bytes.

Evidence:

- **PROVEN (bytes):** 3.16's runtime copy, image `[0x2183, 0x2231)`, is
  byte-identical to `F800:20F7`-`21A5`. The PMONEY cave's divide routines
  equal the S1A routines except for the two fallback far jumps
  (`emu/test_pmoney_noteon.py`). So the execution proof of
  `tests/test_s1a_divide.py` applies. All 17 calls of the 3.16 layer
  reach the cave, and none still calls the runtime.
- **PROVEN (trace, one run):** for every note-on of a PMONEY run, the
  stock lookup (`T_D9F2_003D` called at image `0x3086B`) and
  `mute_pad_of_note` return the same pad. That is 64 comparisons in normal
  mode, plus 64 with the mode byte set and the table injected
  (`emu/lua/pad_mode_inject.lua`: reversed notes, one duplicate, one
  missing note, one byte `90h`; 3 notes correctly unmapped). The only
  direct writer of `DS:8063` zeroes it at start-up (image `0x04ABF`), so
  the injection tests equivalence, not when the OS uses the table.
- P3 relies on the stock reserve being a no-op for its owner
  ([`mute_voice.md`](mute_voice.md)). Without a stop in between, the lock
  taken at `0B30` is still the task's own.

Cost, inclusive cycles per note (`python3 -m emu.pmoney_profile`, same
workloads as section 11):

| Note-on | Stock 3.16 | PMONEY before | PMONEY after |
|---------|-----------:|--------------:|-------------:|
| Mute groups disabled | 14,656 | 20,818 | **9,412** (−55 %; 36 % below stock) |
| Mute groups enabled | — | 23,840 | **12,763** (−46 %) |
| Window busy, 64 notes, mute disabled | 13.62 M | 14.03 M | 13.29 M |
| Idle | 8.2 % | 8.2 % | 8.2 % |

Release gate (`python3 -m emu.harness_release`, `MPC3K_RELEASE=1`, every
suite on capture, generic and 316 with all four EPROM sets): 166 tests, 0
failures, 0 errors, 0 skips. **PROVEN (MAME).**

The released PMONEY BETA 1.0 file is unchanged. These fixes take effect
in the next build. The WAVE and WAVEHW payloads also change (P2, P3), so
the BENCH hardware results describe the earlier bytes; physical behaviour
of the new builds is **UNDETERMINED**.

---

## What this note does *not* prove

- Any physical duration. Every number is MAME's cycle model at 16 MHz with
  the deviations of 1.3 and the unmodelled waits of 1.2.
- That unexecuted owned code is dead (section 6).
- The pad-to-voice path on hardware, or that ISR 0x0C never wakes task 2.
- Interrupt response time, LC7981 busy time, DMA bus steal.
