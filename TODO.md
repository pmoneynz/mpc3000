# Disassembly checklist — Vailixi OS 3.50

Target: interleaved linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
[`PROJECT_GOAL.md`](PROJECT_GOAL.md) wins conflicts.

Marks: `[x]` done · `[ ]` open · `[PARTIAL]` suspended on a named physical
or artifact block. `unresolved` is never an owner. Close a named
uncertainty; do not accumulate owned but unexplained code.

Loop rule: do the highest unblocked `[ ]`. If the only remaining work on
an item needs hardware, a missing ROM, or a datasheet not in this tree,
mark `[PARTIAL]`, name the missing observation, and continue.

---

## G0 — Artifact and address model

- [x] Pin LS/MS hashes and the linear interleave (`tools/linear_rom.py`).
- [x] Prove the image is a raw chip pair, not a floppy container.
- [x] Record reset `FFFF:0000` = file `0x7FFF0`.
- [x] Write the four address forms and XA/PGR rule (`notes/address_model.md`).
- [x] Pin first, second, and third PGR images as bytes and `OUTSW` sources.
- [ ] Revisit G0 only if a different burn or a PAL fusemap changes decode.

---

## G1 — First slice (reset → loop + one observable)

- [x] Partition `FFF0` wait-state stub and `FAC0:0000` through `BRKXA 0x14`.
- [x] Partition `FAC0:0134` init table; retract “only first record runs.”
- [x] Prove BIOS `F800:000A` and `F800:1AD4` `RETF`.
- [x] Prove AMX start `FB00:000C` and dispatcher `FB00:013E`.
- [x] Partition `01EA` / `0537` and the `FB00:023A` empty-queue idle.
- [x] Bound the `0x7C92` copy (`AA 55` + string pointers, dest `0x380100`).
- [x] Prove `INT 43` AX=0 writes LC7981 ports `0xE2`/`0xE0`.
- [x] **D1.** First `01EA` creates task 6 (`D9BD:0009`) after
      `B03B:000A` readies slots 6 and 7. Idle is not taken. Wake ISR
      for a later empty queue remains `U-AMX-WAIT`.
- [x] **D2.** `INT 43` AX=4 default path is `LCD_put` AH=`0x0C` /
      AL=character (`U-INT43-AX4` closed). Not a non-display sink.
- [x] **D3.** Banner path connected: walker, `0040:68AB`/`662B`,
      ports `0xE2`/`0xE0`. Glass stays D3-glass.
- [PARTIAL] **D3-glass.** Pixels on the LC7981 glass (`U-PHYS`, `U-LC7981`).

G1 is complete only when D1 and D3 are `[x]` (D3-glass may stay PARTIAL).

---

## G2 — Shared machinery

- [x] **D4.** Only three `MOV DX,0xFF00`/`OUTSW` sites (all FAC0).
      Second PGR stays live through task 6’s first wait and task 7
      *select*. Later page-picker `OUT`s remain `U-XA-LIVE`.
- [x] **D5.** Reset-path IVT inventoried through `B03B:000A`.
      `IVT[10h]` is `FAC0:01A4` (not `IVT[2]`). 219 slots are
      `F800:1952` `IRET`. Later `0347` plants listed, not applied.
- [x] **D6.** 76 far `CALL FB00` sites, 19 IPs. `[SI]` bits
      0/1/2/3/14/15, `+4/+6` stack, `+0Ah` timed wait, stride `0x40`.
      Mailbox/pool objects stay D11.
- [x] **D7.** Create-table 0–7 identified. Exits: 0/1/3/7 one `RETF`;
      2 and 5 two `RETF`s; 4 wait-loop or `RETF`; 6 no `RETF`.
      Reset readies only 6 and 7. Slots 0 and 2 first-ready open.
- [x] **D8.** Dominant app convention is far cdecl (`[BP+6]`, caller
      `ADD SP`, `RETF`). Walker `F800:1875` is BIOS-only (3 sites).
      AMX is far + `DL`. `INT` uses `AX`.
- [x] **D9.** `FAC0:01A4` `RETXA`/`BRKXA` 0x12 reloads the third PGR
      via ROM `IVT[12]`=`024F` (no IP rewrite). AMX `02F8`/`02EF`
      `IRET` to `TCB+18h+AX` or the interrupted IP. `0157` switches
      `SS:SP` to `901C:1130`. Wake ISR still `U-AMX-WAIT`.
- [x] **D10.** `U-COPY-7C92` closed: DGROUP image at `8010:0000`.
      Directory `[4, 0x5C8)` is 345 `xxxx:8010` ptrs + 19 NULLs +
      the `+0238` numeric island. 21 `MOV AX,8010`. Bulk writer is
      only `FAC0:0074`. `065B` overlays `125C`.. when `ES=8010`.
      `A000` is the ROM source under the first PGR only.
- [ ] **D11.** Find allocators / resource interpreters only when a
      named slice needs them. Gated on D19+ (or another named
      consumer of `065B` / `U-AMX-POOL`). No whole-image leaf hunt.

---

## G3 — Structural closure (byte and transfer domains)

- [x] **D12.** Owner ledger seeded: `code`/`data` only. Gaps are
      debt. No `unresolved` owner. No `excluded_workspace`.
      `analysis/owner_ledger.json`.
- [x] **D13.** Every `0xFF` run ≥ 4 bytes classified: 11 padding
      windows, 3 table terminators, reset `CS` high byte. Short
      `FFFF` runs are immediates, not windows.
- [x] **D14.** Whole-image string scan. 1096 starts established by
      directory / disk table / walker / `PUSH DS`+far. Put-string
      `B1B1:005B` walks `INT 43` AX=4. Printable-without-consumer
      stays candidate. KADAK is identity bytes, not text.
- [x] **D15.** Entry scan: 143 unique `CS:IP` from named consumers.
      Raw `9A`/`EA` (6154/825) stay suspects. `0x7FF01` and
      `0x797A7` are immediates, not transfers. 67 `PUSH DS`+far
      cdecl entries. Bodies stay D16.
- [x] **D16.** Every local exit from the 143 entries classified.
      128 bounded, 14 indirect (slot named, table UNDETERMINED),
      1 idle loop. 74+42 new CALL dests are candidates. JMPF dests
      all established.
- [ ] **D17.** No gap and no overlap in the ledger. `unresolved` is
      debt. Regenerating the ledger must match the notes.
      Progress: 365870 owned / 116 gaps. Owned seed and
      extra-only walks reach no gap instruction bytes
      and no hole-start `CALLF`/`CALLN` dest. A
      real-modrm CS-relative pass owned `D5DD:0124`
      (two 4-word arrays), `DC5B:0002` (12 words),
      `DC6E:0002` (16 mask words, `(n&0xF)<<1`), and
      `EB0B:0002`/`0004` (32-bit dividend). Isolated
      1-byte `0xFF` between owned ranges is align
      padding (32 bytes). `EB0D` / `EB5B` stay
      unowned (RAM `BX`). Mid-hole `C4C8` / `B77C`
      stay unowned. `CEBF:0272` /
      `BE1A:0649` / `E582:013A` / `B060:0D70` /
      `D3A7:0005` / `DC5B:001A` / `DC5B:0123` have
      no owned caller. `0xC0xx` bit meaning is not
      claimed. Unentered app ROM remains. The 1-byte
      `CF` at `0x7ADA3` has no entry. 2026-09-21 09:20
      hunt: far ptrs in owned data to hole *starts* = 0.
      Far dest `FB81:0008` sits 5 bytes into
      `[0x7B813, 0x7B899)` (`FB00:0121` /
      `CS:[003A]` slot 0). Seeded: list header
      `FB76:00B4`, jump-over sled, `CS:[0032]`/`[0036]`,
      `003A` through `RETF`, `0061` through `RET`
      (`CALLF FB00:065B` `AL=2`, `ES=A850`). Isolated
      `90` at `0x7B813` is auto-align. Do not BFS
      `0008`. F800 `20FE`/`2106`/`210E`/`21A5`/`21C6`
      and `D3A7:0005` / `D6D4:003F` still have no
      owned caller; DS-default abs16 is DGROUP RAM.
      INT 43 AX=1..7 dests were already owned extras
      (now seeded). Mid-gap `CALLF` from owned code
      owned `B261:000A` (file `0x3261A`, +0x1A after
      task 1) through `RETF` and leftover `0273`.
      Prefix cdecls `[0x32600, 0x3261A)` have no `9A`.
      Mid-gap owned `CALLF` dests `E59E:0006`/`0035`
      and `E5A8:0003`/`0030` (from `E398`) plus
      leftover `C303:0D47` (from `B3FD`/`C2D0`) are
      seeded. `E582:013A` / `E59E:0099` have
      no owned caller. Mid-hole `C4C8` / `B77C`
      stay unowned. Mid-gap `E12D:0009`,
      `E07A:0004`, `E6D1:0001`, `E739:030C`, and
      `E661:0006`/`0095` are seeded (owned `E398` /
      `B3FD` / `E7E0` callers; all `CALLF` dests
      already owned). Hole prefixes stay unowned.
      Destinations with `JMP CS:[BX]` stay unowned.
      Packed `CALLN` leftovers: `C303:0CEE` and
      `0D76`..`11C4` close two holes; `B060:0044`..
      `02D6` fills `[0x30644, 0x3095D)`; `B3FD:0A96`
      is the hole-start after `0A2F`. Leftover
      `B060:0030` closes the 20-byte prefix.
      Named `C44E` `CALLN` dests `00C2`/`0119`/
      `0485`/`06B6`/`070F` and leftover
      `D9F2:0072` are seeded. `C44E:02BF` stays
      unowned (`JMP CS:[BX]`). `C887:09AC` stays
      unowned (mid-hole). `C4C8:000D` is now
      hole-start of `[0x44C8D, 0x45059)` but
      has `JMP CS:[BX+0099]`. Do not BFS into
      the `B3FD:0B0B` app-ROM hole. Named
      `CALLN` / clean mid-gap `9A` class is
      exhausted: remaining dests are app-ROM
      (`B3FD:0B0B`/`0F79`), `JMP CS:[BX]`
      (`C44E:02BF`, `C4C8:000D`, `DAF2:0040`),
      or refused mid-hole families. Next D17
      hunt: owned-code `JMPN` into a gap, or
      another transfer class not already
      exhausted. 2026-09-21 10:20 hunt:
      owned-code `JMPN`/`JMPS`/`JMPF` dests
      in gaps = 0; `JCC` dests in gaps = 0.
      Next D17 class: another transfer not
      already exhausted (not `CALLN`/`9A`/
      CS-rel / far-ptr-to-hole-start /
      JMP/JCC). Small `55 8B EC` holes
      without a named consumer stay unowned.
      P7/P8: page 61 word `0x0140` → `0x500000`
      (full-word `v33_translate`). Consumer `D9B5`
      `ES=0xF400`; `ES:[03FE]` = `0x5003FE`.
      Low-byte-only `0x100000` is retracted.
      2026-09-21 10:40 hunt: owned-code
      `LES`/`LDS` static far ptrs into gaps
      = 0 (885 encodings; 709 are `[BP+n]`).
      `MOV AX,imm` / `MOV ES,AX` dest0 in a
      gap: `D5DD` at `0x55DD0` and `6900` at
      `0x69000` — both mid-hole, not entries.
      `INT` vecs 10h/11h/40h–43h/45h/46h are
      already owned extras. CS-relative far
      `[rm]` dests in gaps = 0. Next D17
      class: another transfer not already
      exhausted. D20 pad/note path is the
      next unblocked slice once a named
      V53 consumer exists.

Ghidra is navigation, not evidence. Validate `0F E0` / `0F F0` at
`0x7AC1C` as `BRKXA 0x11` before trusting a processor spec.

---

## G4 — Semantic slices (small and complete)

Do these after the dispatcher and address map for that slice are stable.
Each slice needs the contract in `PROJECT_GOAL.md` (purpose, IO, state,
bounds, evidence, unknowns).

- [x] **D18.** Boot / banner / LCD init (close D2–D3). INT 43
      AX=0..7 software contracts are in `int43_ax4.md`. Glass
      stays D3-glass.
- [PARTIAL] **D19.** Front-panel navigation. Panel AM27C256
      absent (`U-PANEL-ROM`). V53 `0xC0-0xDF` I/O encodings
      are pinned; bit meaning and the wire path stay
      unnamed. See [`notes/front_panel.md`](notes/front_panel.md).
      Missing: the dump and one captured panel frame.
- [ ] **D20.** Pad / note entry. Assign UI is `C44E:0119`;
      `D9F2:000C`/`003D`/`0072` are slot/note. ROM default
      at DGROUP `+0859` is 64 bytes `0x23`..`0x62`
      (`B21A:0033` copies to `[8376]`; `CF37:04AD` copies
      overlay to far `+073E`). `[E5F9]` is the selected
      `9770:` record (`CA45:0008` / `DA04:002B`, index
      `0..0x17`). `BE40:000C` is `Assign Note Var Slider
      (Pgm:  )`. Owned `[D6AC]` stores are remaps, not
      pad-hit. See
      [`notes/pad_note.md`](notes/pad_note.md). `+0054` is
      pan ([`notes/pan_table.md`](notes/pan_table.md)).
- [ ] **D21.** Sequencer transport (play/stop/position).
- [ ] **D22.** Sampling / DSP register path (`0x0060`, DMA3).
- [ ] **D23.** Load / save (FDC `0xE8`, SCSI `0xA0`, IRQ3 demux).
- [ ] **D24.** MIDI (TE7774 `0xC0-0xDF`).
- [ ] **D25.** Error, cancel, and recovery paths (system-error text is
      walker-established; path semantics stay open).
- [ ] **D26.** Option-dependent behavior only when a consumer exists.

---

## G5 — Platform (named hardware boundaries)

- [PARTIAL] **P1.** Panel µPD78C10 AM27C256 (`U-PANEL-ROM`). Missing
      observation: the dump MAME names `mp3000__op_v1.0…ic602.bin`.
- [PARTIAL] **P2.** IC25/IC29/IC31 18CV8 fusemaps and schematic sheets
      (`U-PAL`, `U-C0XX`). Missing: service schematic set / JEDEC.
- [PARTIAL] **P3.** LC7981 glass and the seven AX=0 register pairs
      (`U-LC7981`, `U-PHYS`). Software may apply an HD61830 manual to
      the pairs; glass remains PARTIAL.
- [PARTIAL] **P4.** TE7774 register map (`U-TE7774`). Software may
      inventory `IN`/`OUT` consumers; bit meaning stays PARTIAL.
- [PARTIAL] **P5.** IRQ / timer timing, SMPTE, panel IPC on the wire
      (`U-PHYS`).
- [PARTIAL] **P6.** µPD70236 vs 70236A marking (`U-V53A`). Treat as
      V53-family until a chip photo OCR exists.
- [x] **P7.** PGR page 61 word `0x0140` → `0x500000` via
      full-word `v33_translate`. Consumer is `D9B5`
      `ES=0xF400` (file `0x59B57`). Low-byte-only
      `0x100000` is retracted. See
      [`notes/pgr61.md`](notes/pgr61.md).
- [x] **P8.** NVRAM consumer is `D9B5`: `ES:0000` → `0x500000`,
      `ES:[03FE]` → `0x5003FE` inside MAME
      `0x500000-0x500FFF`. Chip LC3517 stays
      HYPOTHESIS. Record format stays UNDETERMINED.

---

## G6 — Reproduction

- [ ] **R1.** Every new fact is pinned in `analysis/boot_slice_facts.json`
      (or a later ledger) and checked by `python3 tools/verify_boot_slice.py`.
- [ ] **R2.** `python3 -m unittest tests.test_boot_slice -v` stays green.
- [ ] **R3.** Ghidra project only after `BRKXA`/`RETXA` decode is checked
      against file `0x7AC1C`.
- [ ] **R4.** Independent review of consequential claims against primary
      bytes. Automated names remain proposals.

---

## Do not do

- Copy the MPC2000XL ledger wholesale.
- Build an emulator except to answer a named item above.
- Treat MAME `MACHINE_NOT_WORKING` models as primary evidence.
- Annotate stock 3.1x or floppy 3.16 as if they were the target.
- Mark unanalyzed bytes `excluded_workspace`.
- Accept `ndisasm`/Capstone across `0F E0` / `0F F0`.
