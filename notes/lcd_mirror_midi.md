# LCD mirror over MIDI (OS 3.16 floppy experiment)

**Target:** stock OS 3.16 (`M3K316.SYS`, SHA-256 `cf997046…de226`) booted from a
floppy, any EPROM set. **Branch:** `lcd-mirror-midi`. **Date:** 2026-10-21.
**Status:** implemented (`mods/lcdmirror316.asm`, hooks in `mods/LCDMIRROR316.args`,
builder `mods/build_lcdmirror316.py`, viewer `tools/lcd_mirror_midi_viewer.py`).
PROVEN in MAME on all four EPROM sets (`emu/test_lcdmirror316.py`). On
hardware it is UNDETERMINED until the bench run
([`bench_lcdmirror_checklist.md`](bench_lcdmirror_checklist.md)). A MAME trace
is evidence about the emulator, not about the board.

This note was written fresh from the handoff of 2026-10-21. The 3.50 design note
that handoff cites (`notes/lcd_mirror_midi.md` on another machine, commit
`03bfc22`) and the 2000XL reference files were not available here. Every 3.16
address below was found and proven again from the 3.16 bytes.

Address forms follow [`port_316.md`](port_316.md):
- 3.16 relative `seg:off`, and image offset = `seg*16+off`;
- file offset = image + `0x7A00`;
- runtime CS = `6900h+seg` on every set (entry316 moves a `7000h` load down);
- logical = `69000h+image`;
- physical = `300000h+logical` (third PGR, XA=1; 3.16 holds no `0F E0`/`0F F0`).

Vailixi addresses are named for comparison only. DS offsets are 3.16 DGROUP
(`609Ch`) unless a segment is given.

## 1. What it does

On every 100 Hz tick, inside 3.16's tick interrupt, the cave compares the screen
with its copy of what the viewer already has. It then queues SysEx messages
(64 bytes or fewer each, up to three per tick, never more than 64 bytes waiting
in the ring) on one MIDI OUT (default OUT D):
- **Text:** the 40×8 text shadow, the cursor and the OS cursor mode.
- **Graphics:** the Mixer page's framebuffer, 1,920 bytes.

The laptop viewer decodes the stream and draws it.

**Why a floppy and 3.16:** the ROM loader boots a floppy's first `*.SYS` and
never returns ([`floppy_loader.md`](floppy_loader.md)).
- No EPROM is touched.
- The mirror's 4.4 KB of code and state live in the Route C cave home, RAM
  above the 3.16 image.
- Rollback is removing the floppy.

The build is Route C ([`port_316.md`](port_316.md) "Architecture"): 3.16 plus a
cave copied home by `entry316`. That also brings the universal layout and the
sequence-pool fix, because stock 3.16 at `L = 6900h` overwrites its own code
after recording. The control floppy, being stock, still has that defect.

## 2. 3.16 map (the handoff's table, resolved)

Agent mapping of 2026-10-21 (read-only, ndisasm plus a reachability walk with
`tools/v53_decode`), cross-checked here. The builder pins every row marked
"pinned" (`STOCK_FACTS`, patch OLD bytes, instruction-shape checks against
Vailixi).

| Object | 3.50 (handoff) | 3.16 | Evidence | Tag |
|---|---|---|---|---|
| INT 43 handler | ROM `F800`, data `0040` | 3.16's own BIOS copy `0009:16A6`; data segment relative `59FA` | IVT[43] plant at image `0x162` `B8 A6 16 A3 0C 01 8C 0E 0E 01`; no 3.16 code loads segment `0040` | PROVEN (forms scanned) |
| Text shadow | `0040:662B` | `59FA:662B..676A` (320 cells, row·40+col) | `mods/display316.inc`; zeroed by `0009:0047` at boot. The handoff's end `672A` is wrong | PROVEN |
| Cursor | `0040:68AB` | `59FA:68AB` word 0..13Fh; `68AF` = FFh when the LCD address equals it | `display316.inc` invariant I | PROVEN |
| INT 43 wrapper | `B1B1` | `0427` (15 `CD 43` sites, AX=1,2,3,4,7,5,6 as in 3.50) | agent list, image `0x427F`..`0x432B` | PROVEN |
| Cursor-mode word | `8010:1D1A` | `[1D02]` (3.50 − 18h, not − 313h) | only writer `0427:0018` image `0x4288` `89 1E 02 1D` (pinned); values 0, 2, 3 | PROVEN |
| Queue creation | `B03B:000A` | `02B2:0004` (AMX start-up procedure; AMX queue create `47BF:0655`) | image `0x2B24`..`0x2BC4` | PROVEN |
| Bulk rings OUT A-D | `A90B:132E…` | `77CA:132E/1930/1F32/2534`, capacity `5FA` each, 602h bytes apart | `CX=05FA` at `0x2B5B` (pinned); send API table `3286:0000` (pinned) | PROVEN |
| Ring descriptor | — | +0 capacity (bits 14-15 = element size−1, 0 here), +2 count, +4 put index, +6 get index (both count down; 0 wraps to capacity), data at +8 | push `3033:003E`, pop `47BF:071F` | PROVEN |
| RT rings | `8010:125C…` | DGROUP `1244/125C/1274/128C`, capacity 10h | `profile_316.inc` `SO_RTQ` | PROVEN |
| TxRdy ISR | `IVT[0C]` = `D5DD:000C` | `2C08:000E`, planted at image `0x2BD8` | agent walk | PROVEN |
| Bulk-active mask | — | `[965C]`, bit 1<<port. Set only by the stock kick `33AF:0043/005D/0077/0091`; cleared by the ISR when that ring is empty | kick bytes `0x33B33` (pinned) | PROVEN |
| Send API | `DC5B` | `3286`: `0039` send_block(buffer far, count, port 1-4), `0086` real-time sender. `0019` send_byte has no caller | bytes; `syncout316.inc` | PROVEN (0019 dead: HYPOTHESIS) |
| Sending-disabled gate | `[9644]` | `[9331]`, an error mask (bits 01/02/04/08/20) | §3.1 | PROVEN |
| Control shadows | `[9628+i]` | `[9315+i]`, ports `C6/CE/D6/DE` | `3286:0010` (pinned) | PROVEN |
| System tick | `IVT[8]` = `D52A:0008` | `2B50:000C`..`0061` IRET. IVT[8] is planted by `02B2` at image `0x2BC9`, the first of its vector installs and after every queue exists | §3.2 | PROVEN |
| Mixer graphics init | `C4C8`, IR0 = 32,07,1D,3F | `1650:0F53` (registers 0-3 ← 32h, 07h, 1Dh, 3Fh via `1650:0F8D`); blit `1650:0F01` writes FB bit-reversed | agent | PROVEN |
| Mixer framebuffer | `8010:1591` | `[1579]`, 30 bytes × 64 rows | `profile_316.inc` `FB` | PROVEN |
| Mixer flag | `[8010:98DC]` | `[95C9]`: set to 1 only in `1650:0F53`, set to 0 only at the end of `1650:03FD` | `0x17453 C6 06 C9 95 01`, `0x16936 C6 06 C9 95 00` (pinned) | PROVEN |
| Transport state | `[A7AE]` | `[A49B]`: 0 stopped, ≥ 6 playing or recording | 36 references; MAME 0 → 8 → 10 ([`wave_chop.md`](wave_chop.md)) | HYPOTHESIS (meaning of each value) |

## 3. The handoff's unknowns

### 3.1 MIDI send API and the gate

**`send_block`** `3286:0039` (Vailixi `DC5B:003B`):
- Frame: `PUSH BP / MOV BP,SP`, buffer far at `[bp+6]`, count at `[bp+10]`, port byte 1-4 at `[bp+12]` (C order, caller pops).
- It tests `[9331]`, looks up the bulk ring in `CS:0000[port-1]`, and calls `3033:003E` once per byte.
- `3033:003E` (Vailixi `DA09:0030`) pushes one byte into `77CA:BX` under its own `PUSHF/CLI/POPF`. It returns AX=0, or FFFF when the ring is full, and never blocks.
- Neither routine starts the transmitter. Callers run the kick `33AF:0000` afterwards.
- PROVEN (bytes; `mods/syncout316.inc` already calls it the same way).

**`[9331]`** is an error mask, not "disk busy":

| Bit | Set by |
|---|---|
| 01 | IRQ 9 sequencer overrun, `2C45:080C` |
| 02 | IRQ 0E wake failure, `2C1F:01DB` |
| 04 | Sequence memory low or full (seven sites after `383B:0007`) |
| 08, 20 | Inside `3BCF:003C` (condition UNDETERMINED) |

- The only clear is in the next-key routine, after the transport stops (`0F6B:0014`, image `0xF6D5`). It shows the stock error and flushes every OUT ring (`2CF7:001A`).
- While the mask is non-zero, stock drops all MIDI output. PROVEN.
- The mirror does the same and asks for a full repaint once the mask is 0 again.

### 3.2 Interrupt safety and where the hook runs

**The tick handler** `2B50:000C` runs between the AMX ISR entry `47BF:0151` and the AMX ISR exit `47BF:018E`. Inside that bracket:
- it saves every register and, at the outermost level, switches to the AMX interrupt stack (`7076:0000`..`1130`, 4,400 bytes);
- it counts ticks and wakes kernel timers;
- it reads the footswitches;
- it runs `INT 42` (`0009:205A` at run time);
- it sends `OUT C010h,60h`, the end of interrupt (HYPOTHESIS: every ISR writes `60h` + its level).

No `STI` is reachable. PROVEN (two independent walks, the second with the footswitch tables bounded by hand; `tools/scsi_reader_reach.py` over-reads those tables and maps INT 42 to the boot-time `194E`). The sequencer clock is IRQ 9 (`2C45`), not this tick.

**Why the hook is not the IVT[8] chain the handoff suggested:** at the outermost level, `47BF:018E` can dispatch a higher-priority task before its RETF. A `PUSHF/CALLF` chain on IVT[8] would then run late, on a task stack, outside the bracket. PROVEN (code).

**The hook** replaces the handler's `CALLF 47BF:018E` at `2B50:005C` (image `0x2B55C`) with `CALLF lm_tick`, which ends `JMP FAR 47BF:018E`. The exit pops this CALLF's return (`2B50:0061`) and reloads everything from its own frame, so it relies on no incoming register. The stack is left exactly as found; the cave's peak stack use is 34 bytes. PROVEN (review).

**Nested ticks.** `2B50:0194` (the TCT0 timestamp routine, reached from INT 0D, INT 0E and IRQ 9) opens a window with only the tick unmasked, so the tick can run inside another ISR, whose mask then stays in force.
- MAME, Vailixi set, the test walk: 35 of 6,126 cave entries were nested (AMX nesting byte `FF`), the rest outermost (`00`).
- The cave reads the nesting byte (`[47BF:003C]` → `593F:0024`, byte `+10h`, decremented by the entry at `47BF:016B`; bytes pinned) and does nothing on a nested tick. PROVEN (MAME).

**Interrupts during the work.** After its gates, with IF still 0, the cave sets IF = 1 and builds and queues its messages.
- That is legal inside the bracket: a nested interrupt raises AMX's nesting level and its exit returns without a task switch; only the outermost exit dispatches.
- No task can run, so the shadow and framebuffer cannot change under the scan. The only critical section is the ring push and the transmitter start, done under `PUSHF/CLI`. IF is 0 again before the AMX exit.

**Message integrity.** The only OUT-ring writers are `send_block` (tasks 2 and 7: SPP, MMC SysEx, notes from pads, soft thru and step-edit audition, Sample Dump) and the cave. PROVEN (review: all 19 relocations of segment `77CA` accounted for; INT 0D writes only input rings).
- `send_block` queues byte by byte with interrupts enabled between bytes. The cave replaces its first 8 bytes (image `0x32899`) with `JMPF lm_send_block`: the stock body inside a nesting count; the tick builds nothing while the count is non-zero.
- The cave's own message enters the ring whole under `CLI`.
- So no message on the port is split by the other writer. 3.16 never uses running status on output, so a cut can never make the next bytes merge with old data. PROVEN.

**Silence rules.** The cave queues nothing:
- while `[A49B] != 0`: count-in, wait for key, play, record. While `[A49B] >= 6` task 2 suspends itself (`340C:0000`, one caller `422F:0399`) whenever any OUT ring is non-empty, for up to one sequencer tick; states 2 and 4 lead straight into it. PROVEN (code); the meaning of 2 and 4 is HYPOTHESIS.
- while `[9331] != 0` (3.16 holds all output), and it asks for a full repaint when it clears;
- for 0.4 s (40 ticks) after any 3.16 message on the mirror's own port (`lm_send_block` sees the port), so live notes and SPP never queue behind a mirror message once 3.16 is using the port;
- while a task message is half queued.

**The ring budget.** A built message waits (`lm_pending`) until the ring would then hold at most 64 bytes. So at the moment the transport starts, at most 64 bytes (20.5 ms at 31,250 baud) are still draining, the same bound as an empty-ring rule. The wire stays about 85% busy during page changes (2,630-2,690 B/s measured, against 3,125 B/s).

**Starting the transmitter:** pushing into the ring and setting bit 1 of the control shadow is not enough. The TxRdy ISR `2C08:000E` reads the bulk ring only when bit 1<<port of `[965C]` is set. PROVEN.
- `lm_kick` does what the stock kick does: `OR [965C]`, `OR [9315+i],2`, `OUT`.
- The ISR clears the enable of ports that were not ready, so the cave re-kicks on every tick while its ring holds bytes (not while `[9331]` holds output, as stock).
- Every write of these bytes from a task is under `CLI` in stock too; no read-modify-write race. PROVEN (review).

**Cost at the board's 16 MHz** (MAME, `NEC_CPU_DIV=2`, Vailixi set, the test walk, 6,126 ticks; `python3 -m emu.lcdmirror_cost`; opcode-fetch taps, a few cycles early from prefetch):

| Interrupts-off window | p50 | p90 | p99 | max |
|---|---:|---:|---:|---:|
| Stock tick: entry → AMX exit | 34.1 µs | 38.0 µs | 50.1 µs | 50.1 µs |
| Mirror tick: entry → the cave's STI | 49.5 µs | 50.1 µs | 59.4 µs | 65.7 µs |
| Mirror: one message into the ring | 22.6 µs | 44.7 µs | 46.8 µs | 46.9 µs |
| Mirror: CLI after the work → AMX exit | 12.3 µs | 12.4 µs | 14.5 µs | 14.6 µs |

- The worst window the mirror adds or lengthens is 66 µs. Stock's own worst during playback is 111 µs (`emu/fixtures/cycle_budget_316.json`, `ifoff_max_us_play`).
- Time in the cave per tick, interruptible part included: p50 101 µs, p99 290 µs, max 667 µs (about 1% CPU idle).
- 3.16's own TxRdy ISR costs about 72 µs per MIDI byte sent (p50; 98 µs max), with interrupts off; stock's cost per byte is the same. That is the mirror's largest CPU cost: 0.9 s over the 102 s walk (stock with only its clock: 0.08 s), about 18% of the CPU during a full Mixer repaint.
- An earlier draft measured at the fork's default 32 MHz and reported half these times; at 16 MHz that draft (one message, whole-screen compares, interrupts off throughout) would have added up to about 380 µs. Found in review; the figures above replace it.
- Whether the TE7774 loses MIDI input in a 66 µs or 98 µs window is unknown hardware (UNDETERMINED; bench gate 6). The MAME 16 MHz cycle model matching the board is HYPOTHESIS ([`performance.md`](performance.md) §1).

### 3.3 The Mixer flag

`[95C9]` is 1 exactly while the Mixer page's graphics are on screen. PROVEN (§2):
- **Set:** page entry `1650:04D5/06BD` and return from Help `0393/1264` call `1650:0F53`.
- **Cleared:** every page exit (`03B5`, `1285`), the Help overlay and the error box `063B:01A8` reach `1650:03FD`. It clears LCD RAM, restores text-mode registers, issues INT 43 AX=1, and then sets `[95C9]` = 0.

MAME agrees: the decoded MODE follows the page in every run, and the decoded framebuffer equals the 240×64 LCD with 0 differing pixels.

### 3.4 Character codes

**Sweep:** 61 stock text pages, Vailixi set (`build/emu/lcdmirror316-codes/codes.json`):
- Every Program/Sounds 1-9, Mixer/Effects 2-5 and Disk 1-9 page.
- The pages of the mode keys, and the four soft keys of Other, Tempo/Sync, MIDI, Song and Edit.

**Display RAM codes seen:** `00 09 20 21 25 26 28 29 2B-3A 3C 3D 3E 40-47 49 4B-56 58-5B 5D 5F 61-69 6B-7A`.
- None is `7F` or higher. `09` appears on the Song page; `00` on many pages.
- PROVEN (MAME, one execution).
- The protocol escapes codes ≥ `7E` anyway. All 256 codes round-trip in `tests/test_lcd_mirror_protocol.py`.

**Blank cells.** Display RAM holds `00` in cells where the shadow holds `20`.
- Every text difference between the decoded stream and display RAM, in every run, is that pair and nothing else (test).
- The put-char skips a cell whose shadow already holds the code ([`display316.inc`](../mods/display316.inc) "unchanged cell": PROVEN). The `00` is left where LCD RAM was cleared without a matching shadow write (HYPOTHESIS: `1650:03FD` and the boot clear).
- Glyph `00` is blank (`emu/font/glyphs.json`, PROVEN from photos) and so is `20`, so the screens look the same.

### 3.5 MIDI OUT ports in the core

- The mac-port core logs all four outputs: `mpc3000.cpp` lines 1048-1051 wire TXD0-3 to `midi_out_byte<0..3>`, and the sink gets port `Port+1`. Pinned core `a9d005de`; replay host `build/core/mpc3k_replay` built 2026-10-07. PROVEN (source).
- This repo's harness traces the OUT D transmit data register, I/O `D8h` (fork wiring, [`emu/test_syncout.py`](../emu/test_syncout.py)).
- The test checks both: the same walk in two binaries.

## 4. Protocol (version 2)

`F0 7D 4D 33 4B <type> <seq> <payload> F7`, at most 64 bytes.
- `7D` is the non-commercial manufacturer ID; `4D 33 4B` is "M3K".
- `seq` is a 7-bit count of messages that entered the ring; gaps are drops. A HELLO resyncs the viewer.

| Type | Payload | Sent |
|---|---|---|
| `01` HELLO | proto 2, mod version 2, OS 3, 16 | at start, after 5 s with nothing to send, and with every full repaint |
| `02` ROW | row, col, len 1..40, codes | a changed span (as much as fits); a row marked whole goes in one or more messages |
| `03` CURSOR | row, col, mode & 7F, mode >> 7 | cursor word or `[1D02]` changed, and after FULL / return to text |
| `04` MODE | `00` text, `01` graphics | `[95C9]` changed, and after FULL |
| `05` PIX | offset >> 7, offset & 7F, len 1..32, 7-in-8 | a changed run of FB |
| `06` FULL | none | at start, every 15 s, after `[9331]` clears, after Stop if a message was draining at the start |
| `07` PCOPY | offset >> 7, offset & 7F, len 1..127, distance >> 7, distance & 7F | FB bytes `offset+i` = `offset-distance+i`, in order (overlap allowed); the mod uses distance 30 (one row up) |

**ROW codes:** a code below `7D` is sent as itself; `7E nn` means `80|nn`; `7F nn` means the literal `nn` (`7D`, `7E`, `7F`); `7D n c` means `n` (4..127) copies of the code `c`, itself escaped. `len` counts decoded codes. Protocol 1 had no run token and sent `7D` as itself.

**7-in-8:** for each group of up to 7 bytes, one byte of high bits (bit i = bit 7 of byte i), then each byte & 7F.

**PIX and PCOPY bytes** are FB as stored. Bit 7 is the leftmost pixel: PROVEN (MAME), with 0 differing pixels this way and 6,374 the other way. The OS bit-reverses each byte for the LC7981.

**Why version 2:** measured on the walk's captures.
- Runs: text payload falls to 72% of the plain encoding, and whole rows fit one message.
- PCOPY: the Mixer page has no runs at all (0 runs of 4 or more equal bytes), but strips repeat and rows match the row above. Copy from one row up takes a full Mixer repaint from 2,880 to about 1,930 bytes; unrestricted LZ over the whole framebuffer would reach only about 1,860, so the wire floor is about 0.6 s.
- The copy source is what the viewer already has: the first 30 bytes are compared with the viewer's copy, the rest with framebuffer bytes the copy itself writes.

## 5. The mod

| Part | Where | What |
|---|---|---|
| Hook 1 | image `0x2B55C` `9A 8E 01 BF 47` → `9A lm_tick` | per tick, inside the AMX bracket |
| Hook 2 | image `0x32899` `55 8B EC 80 3E 31 93 00` → `EA lm_send_block 90 90 90` | send_block with the nesting count and the port hold-off |
| Banner | DGROUP `0x61B5A` `System 3.16 (02/20/05)` → `System 3.16 LCD mirror` | identifies the floppy at boot |
| Cave | about 4.4 KB at home paragraph `7E00` (logical `E7000`, physical `3E7000`) | code, the 320-byte text copy, the 1,920-byte FB copy, the message buffer |

**Per outermost tick:**
1. Start-up: 200 ticks, and the ring must hold capacity `5FA`.
2. `[9331] != 0`: nothing (FULL when it clears).
3. Every 15 s: HELLO and a full repaint.
4. `[A49B] != 0`, the hold-off, or a task inside `send_block`: only re-kick the transmitter.
5. Otherwise, with interrupts on: up to three messages, each pushed when the ring would then hold at most 64 bytes.

**Scans** compare up to 80 text cells or 128 framebuffer bytes per tick with `REPE CMPSW`, from where the last message ended, so no changing cell can starve the others.

**Port:** a build-time option, `--port 1-4` (default 4, OUT D). Ports 1-3 are built and checked by the builder but were not run in MAME.

**Builder checks:**
- `mods/build_wave316.verify()`: both loaders simulated, entry316, hooks landing on their labels, every relocated cave word a known segment.
- The instruction shapes of `T_FB00_0194` (`47BF:018E`) and `T_DA09_0030` (`3033:003E`) equal the Vailixi routines they are named after. Both were added to `profile_316.inc`; the PMONEY `WAVE316.SYS` stays byte-identical (`9017b0f2…b928`).
- The `STOCK_FACTS` bytes, including the AMX nesting byte and the `[A49B]` gate before `340C:0000`.

## 6. Results (MAME at 16 MHz; emulator results, not hardware results)

**Build:** `python3 mods/build_lcdmirror316.py` (hashes in [`bench_lcdmirror_checklist.md`](bench_lcdmirror_checklist.md)).

**`MPC3K_BIOS_316=all python3 -m unittest emu.test_lcdmirror316`:** 6 tests OK on `default` (3.12), `vailixi`, `v311` and `v308` (one execution each, `NEC_CPU_DIV=2`). Harness binary pinned `b4ab57e`; replay host on the Vailixi set.
- At all 17 probe times the decoded stream equals the captured LCD: text codes up to the `00`/`20` blanks, the cursor (row, column, mode) against the machine's own cursor word and `[1D02]` (`emu/lua/lcdmirror_watch.lua`), and Mixer pixels exactly. This holds from the harness trace and from the replay host's `--midi-log`. The replay host runs the same core: its byte times match the harness to about 1 µs, so it is a second recording, not an independent model.
- The stream is well formed: no drops, dups, malformed, cut or foreign messages; longest 51 bytes; contiguous sequence numbers; HELLO first; PIX and PCOPY both used.
- OUT A-C carry only 3.16's clock while the dial passes them, as in the stock control (±1 clock).
- The stock control shows the same display RAM at every probe time and sends only real-time bytes on OUT D.
- Clock on the mirror's port while stopped (from MIDI clock OUT D until Play): every F8 interval within one byte time of 20.833 ms (measured −0.068 to +0.069 ms; stock is steady). During Play: the same F8 count as stock (±2), the same FB and FC counts, and no SysEx.

**Latency from the key press until the decoded picture (text and cursor, or pixels) last settled**, all four sets:

| Step | Seconds | OS drawing alone |
|---|---|---|
| Cursor moves | 0.007 – 0.016 | ≤ 0.002 |
| Wheel edits | 0.021 – 0.053 | ≤ 0.011 |
| Whole page changes | 0.11 – 0.23 | 0.02 – 0.09 |
| MIDI clock wheel (4 steps over 0.45 s) | 0.46 – 0.49 | 0.45 |
| Mixer page (whole framebuffer) | 0.83 – 0.85 | 0.21 |

Before this pass (protocol 1, one message per tick into an empty ring, 32 MHz CPU): pages 0.16–0.29 s, Mixer 1.25 s, cursor moves unmeasured (the old check compared text only).

**Viewer:** `--headless` prints each screen once nothing has arrived for 0.1 s (text with the cursor marked, or pixels), with all six counters. `--log` records every message and every counter change. It notices a port that disappeared and reconnects, and shows how long ago data last arrived (the mirror is silent during play by design). Tests: `tests/test_lcd_mirror_protocol.py` (14, including a fake-port live loop).

**Viewer glyphs:** 20-7E come from [`emu/lcd_font.py`](../emu/lcd_font.py) (photographed glyphs, designed ones for the rest); other codes are a hatch. MAME's character ROM hatches the codes without a photograph, so the viewer and MAME's pixels differ in those cells and in the cursor cell. Codes are compared exactly.

`emu.test_core` (mac-port, unchanged): 17 tests OK.

## 7. Open boundaries (each a bench observation)

| ID | Question | Tag |
|---|---|---|
| LM-H1 | Does the board send the stream on OUT D at all (TE7774 port D, cable, interface)? | UNDETERMINED |
| LM-H2 | Do the 66 µs tick window and 3.16's own 72-98 µs TxRdy window per byte lose MIDI input or panel bytes? | UNDETERMINED |
| LM-H3 | Is the first note after Play, count-in or an external Start late by up to 64 queued bytes (≤ 20.5 ms)? | UNDETERMINED |
| LM-H4 | Is `OUT C010h,60h` the tick's end of interrupt? | HYPOTHESIS (consistent pattern) |
| LM-H5 | Do USB-MIDI interfaces pass 51-byte SysEx intact? | UNDETERMINED |
| LM-H6 | A flush (`2CF7:001A`: the error box, Sample Dump) or an MTC quarter frame (`F1`, only on the message draining at transport start) can cut a mirror message. The viewer counts it `aborted`; the next full repaint (≤ 15 s, or at Stop) repairs it. | PROVEN (code), not exercised |
| LM-H7 | The viewer freezes during count-in, wait for key, play and record (by design). | PROVEN (MAME) |
| LM-H8 | With MIDI clock or MTC on the mirror's port, a Continue sent within about 20 ms of an SPP could overtake it behind a mirror message. Sync defaults to off; the 0.4 s hold-off starts at the SPP. Keep sync and Sample Dump off the mirror's port. | PROVEN (mechanism), occurrence UNDETERMINED |
| LM-H9 | The "Sending note off messages..." panic waits for every port to drain after each of its 128 messages; mirror traffic while its text is being sent lengthens it slightly. | PROVEN (code), bounded |

## 8. Adversarial review (2026-10-21) and what changed

Three read-only reviews of `f3b63b4` (assembly; tests and viewer; stock interactions), each finding reproduced before it was acted on.

| Finding | Disposition |
|---|---|
| Cost figures measured at the fork's default 32 MHz; "below one byte time" did not hold at 16 MHz | All timing now at `NEC_CPU_DIV=2`; interrupts on during the work; windows re-measured (§3.2) |
| Cursor never checked; three probes tested nothing new | Cursor checked against the machine at every text probe; latency includes it |
| Clock test looked only at Play, when the mirror is silent; FA count was 0 = 0 | Jitter checked across the shared stopped span; FB and FC counted |
| `--headless` printed partial frames, no pixels or cursor; `aborted` not visible; reconnect could never trigger | Settled printing, pixels, cursor, all counters on screen and in the log, port-presence reconnect, data age |
| Decoder: long foreign SysEx counted bad; duplicate seq counted 127 drops; reboot counted as drops; CURSOR/MODE unchecked | Fixed and tested |
| `lm_err` set only when the ring was empty | Set whenever `[9331] != 0` |
| A cut message repaired only after 5 s of a still screen | Full repaint every 15 s and after a risky Play |
| Scan starvation by a fast-changing cell | Scans resume after the last message |
| Live notes on the mirror's port wait behind a mirror message; idle repaint took 25% of the Mixer page's wire | 0.4 s hold-off after 3.16 uses the port; idle sends HELLO alone, full repaint every 15 s |
| States 2 and 4 (count-in, wait for key) still sending | Silent unless `[A49B] = 0` |
| The tick can run nested inside INT 0D, INT 0E or IRQ 9 | Nested ticks do nothing |
| "IVT[8] planted last"; `340C` suspend "until the rings drain" | Corrected (§2, §3.2) |
| Viewer cursor drawn when mode 0 | Hidden when mode 0 |

## 9. Deferred: iPhone viewer (after the bench)

**Gate:** start only after LCD MIRROR BENCH 01 passes, any fixes it needs are in,
and the laptop viewer has been used on the real unit without problems
(owner decision, 2026-10-21). Until then the laptop viewer is the only receiver.

**Why an app:** the Python viewer needs desktop Python (python-rtmidi, Tk), and
Safari on iOS has no Web MIDI, so neither runs on a phone. A class-compliant 5-pin
MIDI to USB-C cable works with an iPhone 15 or later through CoreMIDI, with no
driver. Its **IN** plug goes into the MPC's **OUT D**.

**Scope:**
- SwiftUI app with CoreMIDI input; picks the first source (or one chosen in a list) and follows it being unplugged and plugged back in.
- A Swift port of `Decoder` from `tools/lcd_mirror_midi_viewer.py`, protocol 2 (or whatever the bench leaves it at), with the same counters: msgs, drops, dups, bad, aborted, foreign.
- Draws the 40×8 text with the `emu/lcd_font.py` glyphs (hatch for codes it lacks), the cursor (hidden in mode 0), and the 240×64 Mixer pixels (bit 7 leftmost). Landscape, scaled to the screen, LCD colours.
- Shows how long ago data last arrived, since the mirror is silent during count-in, play and record by design.
- Optional: save a session log in the `--log` format, shareable to the Mac.

**Verification:**
- Decoder unit tests ported from `tests/test_lcd_mirror_protocol.py`: all 256 codes, run tokens, 7-in-8, PCOPY, drops, HELLO resync, malformed messages.
- Replay test: feed the MAME recordings (`build/emu/lcdmirror316-tests/*/io_trace.log`, or a replay host `midi.log`) through the Swift decoder. The decoded screen must equal the Python decoder's at every probe time.
- Run in the iOS Simulator (Claude can drive it). On the phone itself it needs the owner's Apple developer signing in Xcode.
- Last step: a short bench with the phone beside the laptop viewer, both on the same stream through a MIDI splitter or thru box. The counters and screens must agree.

**Starting point:** the Swift app scaffolding in `MPC3000-mac-port/app`. A new target or repository is the owner's choice when this starts.
