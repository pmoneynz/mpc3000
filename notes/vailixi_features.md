# Vailixi 3.50 features versus PMONEY (OS 3.16)

**Date:** 2026-10-13. **Images:** Vailixi 3.50 linear `a52b7122…70c9`;
stock 3.12 interleaved from `07-rom/v3.12`; OS 3.16 load image of the
hash-pinned `M3K316.SYS`. PMONEY BETA 1.0 is 3.16 plus the WAVE, ZONES and
MUTE GROUP cave; nothing from Vailixi.

## Method

Every printable string of at least 5 characters (4 letters or more) in each
image. Vailixi 3.50 has 257 that 3.12 lacks. Five of those are in 3.16: two
SCSI format messages, the crash-report text and address, and a filler line.
For each feature, the Vailixi routines that load its strings (`PUSH`/`MOV`
of the DS offset, file − `0x20000`) are located and sized from `55 8B EC`
prologue to the next. Those are the screens; the engines they call are not
counted. **PROVEN (bytes)** for presence and absence of the strings;
feature behaviour is from the Vailixi release notes unless stated.

## Inventory

| # | Vailixi 3.50 feature | Vailixi UI code (routines, bytes) | In 3.16 / PMONEY BETA 1.0 |
|---|----------------------|-----------------------------------|------------------|
| F1 | System Information: free SET/SND/PGM and SEQ memory, I-0055 option | `B000:000E` 409 | **absent** |
| F2 | Clear sound memory before PGM/SND/SET load; disk `ERASE ALL` | `B5C4:0003`, `B766:0003`, 387 | **absent** |
| F3 | Edit Sound Do: `TRUNC SFT ST+END` (and `COPY ZONE-> SND`) | `BB0C:0008` 563 | **absent** (PMONEY's README already lists both as Vailixi-only) |
| F4 | Real-time sample editing while the sequencer runs | no strings; engine change | **UNDETERMINED** (not located) |
| F5 | Program/Sounds 9: Compression (halve a sound) | `CA4D:000E` 859 | **absent** |
| F6 | Timing correct 1/4, 1/4T, 1/64, 1/64T; OFF at 1/128, 1/192 | table-driven strings `1/64 NOTE`, `1/64 TRPLT`, `1/128`, `1/192` (no direct consumer) | **absent** (strings missing) |
| F7 | Swing for every timing correct value | no new strings | **UNDETERMINED** |
| F8/F9 | MIDI clock and MTC to all four outputs | new `Sync In / Sync Out` layout; table-driven | **absent** (layout string missing) |
| F10 | Extra System Parameters: SND stop on STOP, transport error warnings, stay in Edit Sound / Mixer on PLAY, mute audio during Edit Sound processes, Do safe lock | `C844:000D`, `C86B:0001`, 1,063 | **absent** |
| F11 | SCSI sector-at-a-time disk copier | `B6E5:000C` 661 | **absent** |
| F12/F13 | Make active: multi-sector transfer, bus reset during AUTO search | `B6CD:000D` 383 | **absent** |
| F14 | Hardware/Software low-level format with software fallback | `B614:000C` 2,264 (shared with F15) | **absent**; 3.16 has its own `<Slow>`/`<Fast>` format choice |
| F15 | Hybrid partitions | `B614:000C`, `B76F:000D` | **absent** |
| F16 | Save samples up to 32 MB in one file | no strings | **UNDETERMINED** |
| B1 | "function is not yet implemented" fixes | `C44B:0009` 44 (the message itself) | **absent** (string missing) |
| B2 | Audio muted while loading/saving sounds | no strings | **UNDETERMINED** |
| B3 | Correct "too many sounds" error on PGM load | `CF37:0002` 771 (`PROGRAM MEMORY SPACE ALLOCATION ERROR`) | **absent** (string); see Port status |
| B4/B5 | Recording past 327.6/163.8 s; full 32 MB for recording | no strings | **UNDETERMINED** |
| B6/B8 | MIDI input overload while stopped; faster MIDI input | no strings | **UNDETERMINED** |
| B7 | Unused-track flags at sequencer init | no strings | **UNDETERMINED** |
| B9 | SCSI protocol engine rewrite | no strings | **UNDETERMINED** |
| B10 | Redundant functions removed | Vailixi has 4.1 KB more `0xFF` filler in `[0x20000, 0x74000)` than 3.12 | not applicable |

3.16 has two things Vailixi lacks: `Load S1000/S3000 Sample Files` and its
own low-level format type selection.

## What a port involves

- **Size:** the UI routines alone are about 9 KB. The engines behind them
  (copier, formatter, partitioner, compression, the parameters' effects on
  transport, mixer and editor) and the string-less fixes are in callees and
  core subsystems that this project has not mapped (D17 gaps). The cave has
  11.4 KB free on 3.08/3.11 EPROMs (home limit 24,576 bytes) and 40 KB on
  3.12/3.50. Porting everything would not fit on 3.08/3.11 machines without
  a new memory layout.
- **Base mismatch:** Vailixi changes 3.12 code; PMONEY is 3.16, a different
  Akai build with its own DGROUP, kernel copy and code layout. Each feature
  has to be re-mapped onto 3.16, as `notes/port_316.md` did for the WAVE
  hooks.
- **Rights:** Vailixi 3.50 is licensed per machine to a named owner
  ([`license_personalization.md`](license_personalization.md)). Copying its
  code into a free release that runs on any MPC3000 redistributes that
  product. That needs the rights holder's permission. Implementing the same
  features in this project's own code does not.

## Port status (PMONEY, 3.16 + cave)

Owner decisions (2026-10-13): Vailixi code is ported under the rights
holder's permission; PMONEY uses its own UI wording, not Vailixi's strings;
two builds if the full set does not fit the 3.08/3.11 cave home (24,576
bytes); small self-contained features first, SCSI/disk last.

| # | Status | PMONEY form | Evidence |
|---|--------|-------------|----------|
| F1 | **ported** | `mods/sysinfo316.inc`: one screen under the banner (rows 3-5) at boot and on Other -> Soft Key 3; no 5 s license delay, so the boot timing is unchanged; I-0055 probed once at boot and reused | `emu/test_port316_boot.py` (all four sets: 1916K, 411K/439K), `emu/test_sysinfo.py` |
| F3 | **ported** | `mods/wave_chop.inc` CHOP_EDITDO: the Do list in Vailixi's order with `ZONE->NEW SOUND` (k=1) and `CROP SOFT ST-END` (k=7); CHOP ZONE is option 10. Deviations: the source stays selected, TEMPORARY999 is not deleted when it is the source, zones under 441 frames are refused | `emu/test_harness_lifecycle.py` do1/do7 on 3.16, `emu/test_wave_chop.py`, `emu/test_harness_long.py` |
| F5 | **ported** | `mods/compress.inc`: Program/Sounds 9 `Compress sound` replaces MIDI sample dump, as in Vailixi. Deviations: no zero-length transfer (Vailixi's count-0 hang), per-plane stereo, BUSY-held stock buffer, results under 441 frames refused, Tune up to +120, voices stopped first | `emu/test_compress.py` (mono/stereo odd/even PCM = per-plane `[0::2]`; record fields; negative Tune refused; menu) |
| F4 | **ported** | `mods/xparams316.inc`: Edit Sound no longer stops the transport on entry (image `0x1A056`), and the seven Edit Sound wave transfers run inside the playback lock (`xp_xfer_locked`, as Vailixi's `inc/dec [9757]`) | `emu/test_wave_chop_safety.py` (3.16 cases), `emu/test_xparams.py` stay-in-Edit-Sound |
| F6/F7 | **ported** | `mods/tc316.inc`: 13 Timing Correct values in Vailixi's order with Swing on every note value; the stored index stays a stock 0..6 value (projection), the full index lives in RAM. Limitation: after a power cycle a new value reads back as its stock projection | `emu/test_timing_correct.py` (labels, stored values, grid intervals, Swing hidden for OFF values) |
| F10 | **ported** | `mods/xparams316.inc`: Other -> Soft Key 4 `Extra Settings`, six OFF/ON fields stored inverted in the parameter-block reserve DS `8316..831D` (persist with no hook on 3.12/3.16 EPROMs; zero = Vailixi default). On Vailixi-EPROM machines no PMONEY parameter survives a power cycle: Vailixi checksums 6C3h bytes where 3.16 uses 6C2h, so every boot applies Vailixi's defaults, then 3.16's (PROVEN, code and MAME). Inverted rows turn OFF with '+' | `emu/test_xparams.py` (page, stay in Edit Sound / Mixer, stop all sounds on STOP), `emu/test_wave_chop_safety.py` (safe lock, mute). The sequence-change warning setting has no emulator test yet |
| F2 | **in stock 3.16 + ported** | Clear before load is stock 3.16's `<Clr&load>` (Load a Program Soft Key 2, `1396:01AC`; MPC60 SET loader `113A:09FB`), identical to Vailixi: it zeroes all sound records and the allocation table and unlinks every pad; no image clears memory on SND loads. Erase all is ported: `mods/eraseall316.inc`, Disk 7, Soft Key 2 `<Erase>`, Soft Key 2 `<Erase all>`. Deviations: a confirmation page naming the disk, `.SYS` files kept (the PMONEY boot file), the first delete error stops the loop, no file count | `emu/test_erase_all.py` (erase keeps only STARTUP.SYS and the FAT consistent; a mode key cancels; `<Erase it>` still erases one file) |
| F8/F9 | **ported** | `mods/syncout316.inc`: Sync page MIDI clock and MIDI tm code gain `ALL` (3.16's own label). ALL is stored as OUT A in the stock byte plus a bit in reserve `DS:831E`, never as 5 (a stock OS reading 5 corrupts DGROUP). Deviations: Song Position Pointer also goes to all four (Vailixi sends none with ALL); values above 5 are dropped | `emu/test_syncout.py` (F8, F1, start/stop on all four TE7774 data registers; OUT A only; ALL kept on reopening) |
| F12/F13 | **ported** | `mods/scsi316.inc`: two rows on Disk 9 4 SCSI Status. Multi-sector transfers (`DS:831B`, stored inverted, default ON = stock traffic); OFF sends one READ(6)/WRITE(6) per device block (Vailixi `D470:0121`). Reset SCSI chip on AUTO search (`DS:831C`, default OFF) re-runs the SPC initialisation after each failed ID probe (Vailixi `D470:04C4`). That call is the SPC chip init, not the bus RST pulse, so the label does not promise a bus reset. Deviation: a zero-count transfer returns 0 | `emu/test_scsi316.py` (MAME SCSI disk: page and defaults; PARAMS.PAR identical apart from the setting byte with OFF and more SELECTs; with the disk at ID 3, three extra SPC inits per rescan when ON) |
| F15 (+H6) | **ported** | `mods/diskutil316.inc`. H6: the 3.16 partition reader (`2AB2:059D`, image `0x2B0BD`) mounts a disk whose LBA 0 is not an MPC disk when LBA 0 is a hybrid MBR (`55 AA`, entry 1 type 05 from LBA 63; D4, Vailixi has no MBR test) and LBA 63 passes Vailixi's EBR test (`D470:065C..0723`: `+18h`/`+1Ah` = 10h, `CA FE 20 07` at `1B8h`, `55 AA`); the table at EBR `+80h` is copied as `2AB2:054D` does. F15: after `<Slow>`, `<Fast>` or `<Zero>`, Format Hard Disk asks `<MPC only>` (the stock count page, unchanged) or `<MPC + PC>`: options 1-5 that fit (`n. cc volume(s) of mm MB`), a confirmation page, then Vailixi's MBR + EBR chain + FAT12 layout, rescan. Deviations: D1 write order LBA 0 and 63 zeroed, volumes, EBRs c-1..0, MBR last; D2 32 sectors/cluster for option 4 too (Vailixi's option 4 overflows its 11-sector FAT, 4,008 > 3,752 clusters); D3 FAT sector 0 = `F8 FF FF` (Vailixi `F8 FF FF FF FF` marks clusters 2 and 3 used); D4 MBR predicate; stops at the first failed write (Vailixi keeps only the last stage's error); refuses a non-512-byte device; INT 41 AX=0 before writing; media-changed flag `[799B]` set as the stock writer. OEM `PMONEY  `, labels `PMONEY-PT-A`.., serials `504D00nn` (no MPC reader tests them). Stock 3.08-3.16 see a hybrid disk as code 5 (searching, then box FF48 "No SCSI device was found", as for a blank disk) and never write it unasked | `emu/test_diskutil316.py`: options 1 (40 MiB, 5 volumes) and 5 (80 MiB, 2 volumes) equal the layout model sector for sector, every other sector zero; mtools reads every volume; PMONEY mounts both after a reboot (count, table, geometry 16/16, Select disk reaches the last volume, Free = model), saves PARAMS.PAR into the last volume, mtools reads it back, nothing else changes; PMONEY mounts a Vailixi-built model disk (Free 7952K = clusters 2-3 used); stock M3K316.SYS: no partitions, disk byte-identical; `<MPC only>` gives the stock layout byte for byte (apart from boot bytes `1Ch-1Fh`, uninitialised stack in stock); a mode key on the confirmation page writes nothing |
| F11 | **ported** | `mods/diskutil316.inc`: Disk 9 item `5.Copy a SCSI disk to another` (image `0x86DE`, `0x8713`, `0x874F`). Unit page (source = active unit, target = next, 0..6), checks, confirmation, 9 blocks per READ(6)/WRITE(6) through `SND_SEG:0000` (as Vailixi), percentage on row 5, rescan. Deviations: C1 source = target refused; C2 no disk or block size not 512 refused, `[7998]`/`[799A]` saved and restored, `[799A]` = 0 during the copy; C3 only the source layout's extent is copied (MPC: last table entry + volume size; hybrid MBR: 63 + extended length; else the capacity; at most 2^21 blocks) and a target smaller than that extent is refused (Vailixi truncates silently); C4 confirmation naming both units, Soft Key 1 only after dropping queued keys, INT 41 AX=0 first; C5 Soft Key 1 `<Stop>` between commands (the target is left partial); C6 a copy onto the active unit rescans it (`[799B]` set). A refusal shows on row 3 with `<Back>` to the unit page | `emu/test_diskutil316.py`: a 9 MiB pattern-filled option-1 disk with PARAMS.PAR (unit 0) onto a 16,065-sector blank (unit 1, smaller than the source disk, not than its layout): target = source's first 16,065 sectors, source unchanged, mtools lists PARAMS.PAR on the copy; 16,064-sector target and source = target refused with the disks unchanged; a mode key on the confirmation page; `<Stop>` leaves a copied prefix and zeros; unit 1 onto the active unit 0 (stock layout, 2 partitions): after the rescan 1 hybrid volume at LBA 126 is mounted (Free 7928K) |
| F14 | **ported** | `mods/diskutil316.inc`: Format Hard Disk's third key `<Zero>` (images `0x8958`, `0x8969`, `0x897E`): confirmation, then WRITE(6) of zeros, 9 blocks per command, over min(capacity, 2^21) blocks, percentage, `<Stop>`; success continues to the layout page (F15). Deviations: confirmation, progress and stop (Vailixi has none); capped at 2^21 blocks (Vailixi's `<Soft>` wraps the 6-byte CDB on larger disks); write errors show the stock box (Vailixi ignores the result); after Stop or an error the active unit is rescanned. Vailixi's post-`<Hard>` 4,096-sector fallback is not ported (the partitioners rewrite every metadata sector they use) | `emu/test_diskutil316.py`: a pattern-filled 9 MiB disk is entirely zero afterwards (sampled LBAs and the whole image) and the layout page follows; `<Stop>` leaves a zeroed prefix and the rest unchanged, back to the Disk page; a mode key on the confirmation page writes nothing |
| B9 | **in stock 3.16** | Not a rewrite. The BIOS disk services are the same code in 3.12, Vailixi and 3.16; the SCSI driver's only change from 3.12 is a 6-byte poll of the SPC interrupt register in the transfer-start wait (Vailixi `D3A7:00CA`), which 3.16 has byte for byte at `2A66:00C8` (image `0x2A728`) | |
| B6/B8 | **ported, with a deviation (R3)** | JMPF at image `0x2BFCD` (`2B6D:08FD`) to cave `midi_msg_done` (`mods/perf316.inc`), after Vailixi `D547:0903..090D`: the pending count is incremented inline, and while stopped the MIDI input interrupt no longer wakes the playback task and posts a tick message after every complete message. 3.16 had 3.12's code. Deviation from Vailixi: a note-on with velocity > 0 while stopped (`[A49B]` = 0) still gets 3.16's wake and post (`2B6D:0907..0928`), so the first note of a chord plays at stock latency; every other message (note-off, CC, aftertouch, pressure, program change, pitch bend) waits for the next sequencer tick (up to 5.2 ms at 120 BPM). Sysex never took this path. While playing nothing changes (stock posts only when stopped) | `emu/test_midi_wake316.py`: stopped 16-note MIDI chords, first voice set-up no later than stock + 0.5 ms; stopped CC, aftertouch and sysex floods run no extra task-2 tick bodies and stay under stock busy cycles; no wake while recording. `emu/test_cycle_budget.py`: `chord_midi_first_ms`, `busy_pct_stopped_*`, `rx_byte_stopped_*` |
| B1/B2/B3 | **in stock 3.16** | No hook. B1: 3.16's Edit Sequence menu counts 9 entries and Mixer/Effects 3 handles every soft key, as Vailixi. B2: 3.16's port-6Ah mute `2FAB:000E` is Vailixi's `D980:000C` without PUSHF/CLI, called at the same SET/ST1, SND and .PAR load/save sites (3.12's is an empty stub). B3: `1396:0465` negates the worker's code, byte for byte Vailixi. Left in both 3.16 and Vailixi: the Load All Programs & Sounds path still shows the sequence-memory message at the limit; an SND with version byte 3 or more leaves the outputs muted and BUSY held (`2E26:010C`, code PROVEN, effect not run); Mixer Soft Key 2 nests the screen | `tests/test_stock316_fixes.py` |
| B7 | **UNDETERMINED; no port** | Ten MAME boot and sequencer scenarios on 3.12, Vailixi and stock 3.16 (cold, warm, foreign NVRAM, A5h-filled RAM, a changed Initialize-Sequence default, record / Track+ / Delete All, ALL autoload): sequence structures and the default track-status table are byte-identical between 3.12 and Vailixi; every track defaults to UNUSED in 3.08-3.16 and Vailixi. Executed boot code differs only in other features. Vailixi's one boot-time sequencer change, resetting the Erase screen's `Erase:` field to ALL EVENTS (`BDF1:01E5`), does not fit the release note and is not ported. Not exercised: SCSI boot with STARTUP.ALL/APS, memory boards | |
| B4/B5 | **in stock 3.16** | No hook. 3.12 compares the sampler tick counter with Length x 10 signed (`C2E5:1429`, file `0x44279`), so Length 327.7 s or more stops recording at once; only MONO on a 32 MB board reaches it. Vailixi makes four Length operations unsigned; 3.16 has the same four edits (image `0x187C2`, `0x18932`, `0x19061`, `0x198C7`). PROVEN (bytes). Vailixi's "163.8 s stereo" figure is not produced by any code found: UNDETERMINED | `tests/test_stock316_fixes.py` |
| F16 | **ported (F15 option 5 + H6)** | SND save/load and the file system are identical in 3.12, Vailixi and 3.16 and are 32-bit. The limit is the disk: the stock partitioner caps a partition at 60,053 sectors (3.16 image `0x94D1`), below a full 32 MB-board file (33,392,558 bytes). F15 option 5 makes 65,535-sector volumes with 16 KiB clusters (2,046 clusters, 32,736K free); H6 mounts them | `emu/test_diskutil316.py`: on the option-5 disk PMONEY shows Free 32,736K; on the host mcopy stores a 33,392,558-byte file in volume A (114,688 bytes left) and reads it back; f16 case (32 MB board): PMONEY loads a 16,696,260-frame sound (33,392,558 bytes) from volume A in ~100 s, Free(snd) 26K, saves it into volume B (Free 32,736K -> 112K) in ~75 s, and the saved file has every frame of the original (record differs only in name padding and the ignored wave address `+20h`); volume A unchanged |

Builder: `mods/build_wave316.py` treats a word named by a cave label at
that offset as an offset, not a segment (the cave grew past `0x301D`).
