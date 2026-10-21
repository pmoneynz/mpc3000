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
with its copy of what the viewer already has. It then queues at most one SysEx
message (64 bytes or fewer) on one MIDI OUT (default OUT D):
- **Text:** the 40×8 text shadow, the cursor and the OS cursor mode.
- **Graphics:** the Mixer page's framebuffer, 1,920 bytes.

The laptop viewer decodes the stream and draws it.

**Why a floppy and 3.16:** the ROM loader boots a floppy's first `*.SYS` and
never returns ([`floppy_loader.md`](floppy_loader.md)).
- No EPROM is touched.
- The mirror's 3.8 KB of code and state live in the Route C cave home, RAM
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
| System tick | `IVT[8]` = `D52A:0008` | `2B50:000C`..`0061` IRET. IVT[8] is planted last by `02B2` at image `0x2BC9`, after every queue exists | §3.2 | PROVEN |
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
- it saves every register;
- it switches to the AMX interrupt stack;
- it counts ticks and wakes kernel timers;
- it reads the footswitches;
- it runs `INT 42`;
- it sends `OUT C010h,60h`.

No `STI` is reachable. PROVEN (code). The sequencer clock is IRQ 9 (`2C45`), not this tick.

**Why the hook is not the IVT[8] chain the handoff suggested:** at the outermost level, `47BF:018E` can dispatch a higher-priority task before its RETF. A `PUSHF/CALLF` chain on IVT[8] would then run late, on a task stack, outside the bracket. PROVEN (code).

**The hook instead** replaces the handler's `CALLF 47BF:018E` at `2B50:005C` (image `0x2B55C`, `9A 8E 01 BF 47`) with `CALLF lm_tick`:
- `lm_tick` does its work, then `JMP FAR 47BF:018E`.
- The exit pops this CALLF's return address (`2B50:0061`), so the stack is left as found.
- The work therefore runs inside the bracket, after the tick's end-of-interrupt write, with IF = 0, on the AMX interrupt stack. It cannot be preempted or run twice.
- That `OUT C010h,60h` is the end of interrupt for this level is HYPOTHESIS.

**Is queuing from the tick safe?** The ring push is a `PUSHF/CLI` critical section with no lock or flag, so pushing from the ISR is safe. PROVEN. Message integrity is the real issue:
- The only OUT-ring writer is `send_block`, and only tasks call it (tasks 2 and 7: SPP, MMC SysEx, note-offs and repeats, Sample Dump).
- It queues byte by byte with interrupts enabled between bytes, so the tick could fall inside a task's message. PROVEN.
- The cave therefore replaces `send_block`'s first 8 bytes (image `0x32899`, no relocation inside) with `JMPF lm_send_block`. That is the stock body inside a nesting count; the tick sends nothing while the count is non-zero.
- The mirror's own message enters the ring whole under `CLI`.
- Result: no message on the port is split by the other writer. Task-against-task interleaving (task 2 inside task 7's Sample Dump) is a stock hazard and stays as stock.

**Stock interaction that forces silence during playback:** while `[A49B] >= 6`, task 2 calls `340C:0000` at `422F:0399`. That suspends task 2 whenever any OUT bulk ring is non-empty. PROVEN (code).
- So any mirror traffic during playback would hold back sequencer output.
- The mirror sends nothing while `[A49B] >= 6`, and only into an empty ring otherwise.
- Bound at the moment Play is pressed: at most one message (≤ 64 bytes, ≤ 20.5 ms at 31,250 baud) is still draining. Whether a first note is then late on hardware is UNDETERMINED (bench gate 5).
- In MAME, no SysEx starts during play on any set (test).

**Starting the transmitter:** pushing into the ring and setting bit 1 of the control shadow is not enough. The TxRdy ISR `2C08:000E` reads the bulk ring only when bit 1<<port of `[965C]` is set. PROVEN.
- `lm_kick` does exactly what the stock kick does: `OR [965C]`, then `OR [9315+i],2`, then `OUT`.
- The ISR clears the enable bits of ports that were not ready, so the cave re-kicks on every tick while its ring holds bytes.

**Interrupt-off time, MAME, Vailixi set, the test walk, final build** (`emu/lua/lcdmirror_cost.lua`: opcode-fetch taps; 5,480 ticks):

| Measured | p50 | p90 | p99 | max |
|---|---:|---:|---:|---:|
| Stock tick handler, entry → IRET | 16.7 µs | — | 35.3 µs | 36.2 µs |
| Cave added, `lm_tick` → AMX exit | 44.4 µs | 44.5 µs | 106.9 µs | 156.0 µs |
| Cave added, Mixer page window (53.5-56 s) | 56.1 µs | — | — | 140.6 µs |

- The first draft (byte loops, whole-screen compare per tick) took 389 µs at p50. The cave now compares two text rows or 128 framebuffer bytes per tick with `REPE CMPSW`. It builds each message backward so that one `REP MOVSB` (two when the message wraps) puts it in the ring, and caps ROW at 24 codes.
- The worst case, stock plus cave, is below one MIDI byte time (320 µs).
- Whether the TE7774 receiver loses input during that time is unknown hardware (UNDETERMINED; bench gate 6).
- The MAME 16 MHz cycle model matching the board is HYPOTHESIS ([`performance.md`](performance.md) §3).

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

## 4. Protocol (version 1, frozen)

`F0 7D 4D 33 4B <type> <seq> <payload> F7`, at most 64 bytes.
- `7D` is the non-commercial manufacturer ID; `4D 33 4B` is "M3K".
- `seq` is a 7-bit count of messages that entered the ring; gaps are drops.

| Type | Payload | Sent |
|---|---|---|
| `01` HELLO | proto 1, mod version 1, OS 3, 16 | about 2 s after the hook first runs, then after every 5 s with nothing to send |
| `02` ROW | row, col, len 1..24, codes escaped | a changed span; a row marked whole goes in up to two messages |
| `03` CURSOR | row, col, mode & 7F, mode >> 7 | cursor word or `[1D02]` changed, and after FULL / return to text |
| `04` MODE | `00` text, `01` graphics | `[95C9]` changed, and after FULL |
| `05` PIX | offset >> 7, offset & 7F, len 1..32, 7-in-8 | a changed run of FB; the whole FB after MODE 01 or FULL |
| `06` FULL | none | after HELLO, after `[9331]` clears, and when a ring had no room |

**Encoding rules:**
- **Escapes:** a code below `7E` is sent as itself; `7E nn` means `80|nn`; `7F nn` means the literal `nn` (`7E`, `7F`).
- **7-in-8:** for each group of up to 7 bytes, one byte of high bits (bit i = bit 7 of byte i), then each byte & 7F.
- **PIX bytes** are FB as stored. Bit 7 is the leftmost pixel: PROVEN (MAME), with 0 differing pixels this way and 6,374 the other way. The OS bit-reverses each byte for the LC7981.

The handoff's ROW length limit of 40 cannot fit 64 bytes when codes are escaped, so ROW carries at most 24 codes (2·24 + 11 ≤ 64).

## 5. The mod

| Part | Where | What |
|---|---|---|
| Hook 1 | image `0x2B55C` `9A 8E 01 BF 47` → `9A lm_tick` | per tick, inside the AMX bracket |
| Hook 2 | image `0x32899` `55 8B EC 80 3E 31 93 00` → `EA lm_send_block 90 90 90` | send_block with the nesting count |
| Banner | DGROUP `0x61B5A` `System 3.16 (02/20/05)` → `System 3.16 LCD mirror` | identifies the floppy at boot |
| Cave | 3,820 bytes at home paragraph `7E00` (logical `E7000`, physical `3E7000`) | code, the 320-byte text copy, the 1,920-byte FB copy, the message buffer |

**Gates on each tick, in this order:**
1. Start-up: 200 ticks, and the ring must hold capacity `5FA`.
2. Ring non-empty: kick and stop.
3. `[9331] != 0`: stop.
4. `[A49B] >= 6`: stop.
5. A task inside `send_block`: stop.
6. Otherwise build at most one message, push it and kick.

**Port:** a build-time option, `--port 1-4` (default 4, OUT D).

**Builder checks:**
- `mods/build_wave316.verify()`: both loaders simulated, entry316, hooks landing on their labels, every relocated cave word a known segment.
- The instruction shapes of `T_FB00_0194` (`47BF:018E`) and `T_DA09_0030` (`3033:003E`) equal the Vailixi routines they are named after. Both were added to `profile_316.inc`; the PMONEY `WAVE316.SYS` stays byte-identical (`9017b0f2…b928`).
- The `STOCK_FACTS` bytes.

## 6. Results (MAME; emulator results, not hardware results)

**Build:** `python3 mods/build_lcdmirror316.py`

| File | Bytes | SHA-256 |
|---|---:|---|
| `build/lcd_mirror/M3K316.SYS` | 469,175 | `5a34eab0b537c309afbed0d4df897391542b8ec09581a88a114658eed06341c8` |
| `build/lcd_mirror/LCDMIRROR_316.img` | 1,474,560 | `6f9629d9032d150eca0ad623792c0fbb3794357d0382411f2c2b9985526809b2` |
| `build/lcd_mirror/STOCK_316.img` (control) | 1,474,560 | `2752cf3e29141880a1f9949a68d2dfdf02b3dc7f536998632844ccf10946c3e1` |

**`MPC3K_BIOS_316=all python3 -m unittest emu.test_lcdmirror316`:** 6 tests OK on `default` (3.12), `vailixi`, `v311` and `v308` (one execution each). Harness binary pinned `b4ab57e`; replay host on the Vailixi set.
- At all 16 probe times, the decoded stream equals the captured LCD (text codes up to the `00`/`20` blanks; Mixer pixels exactly). This holds from the harness trace and from the replay host's `--midi-log`.
- The stream is well formed:
  - no drops, nothing malformed or cut, no foreign SysEx;
  - longest message 48 bytes;
  - contiguous sequence numbers, HELLO first;
  - at least 60 PIX messages and 2 MODE messages.
- OUT A-C carry only 3.16's clock while the dial passes them, as in the stock control (±1 clock).
- The stock control shows the same display RAM at every probe time and sends only real-time bytes on OUT D.
- 3.16's MIDI clock on OUT D during 4 s of Play: the same F8 count as stock (±2; > 150), the same FA/FC counts. No SysEx starts while the transport runs.

**Latency from the key press until the decoded picture last settled** (all four sets agree within 0.04 s; the replay host gives the same):

| Step | Seconds |
|---|---|
| Cursor moves, wheel edits | 0.00 – 0.06 |
| Whole page changes | 0.16 – 0.29 |
| MIDI clock wheel (4 steps over 0.45 s) | 0.46 |
| Mixer page (whole framebuffer) | 1.25 |

**Viewer glyphs:** the viewer draws 20-7E with [`emu/lcd_font.py`](../emu/lcd_font.py) (photographed glyphs, designed ones for the rest). Other codes are drawn as a hatch.
- The MAME character ROM hatches the codes without a photograph, so the viewer and MAME's pixels differ in those cells (for example `Q`, `X`) and in the cursor cell.
- Codes are compared exactly. Pixels differ by design.

`emu.test_core` (mac-port, unchanged): 17 tests OK.

## 7. Open boundaries (each a bench observation)

| ID | Question | Tag |
|---|---|---|
| LM-H1 | Does the board send the stream on OUT D at all (TE7774 port D, cable, interface)? | UNDETERMINED |
| LM-H2 | Does the extra 45-160 µs with interrupts off per tick lose MIDI input or panel bytes? | UNDETERMINED |
| LM-H3 | Is the first note after Play late by up to one queued message (≤ 20.5 ms)? | UNDETERMINED |
| LM-H4 | Is `OUT C010h,60h` the tick's end of interrupt, so later interrupts can be taken during the cave? (A wrong answer delays them by ≤ 160 µs.) | HYPOTHESIS |
| LM-H5 | Do cheap USB-MIDI interfaces pass 48-byte SysEx intact? | UNDETERMINED |
| LM-H6 | A Sample Dump flush (`2CF7:001A`) can cut a mirror message in flight. The viewer counts it as `aborted` and repairs at the next HELLO (≤ 5 s idle). | PROVEN (code), not exercised |
| LM-H7 | The viewer freezes while the transport runs (by design, §3.2). | PROVEN (MAME) |
