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
- [PARTIAL] Revisit G0 only if a different burn or a PAL fusemap changes decode.
      Missing observation: a different ROM burn, or a JEDEC fusemap, is not
      in this tree. MAME names BIOS 3.10/3.11/3.12 by CRC and SHA1 only.
      Those bytes and any 18CV8 fusemap are absent. This image’s decode
      is unchanged.

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
      `B03B:000A` readies slots 6 and 7. Idle is not taken.
      U-AMX-WAIT is closed by IVT[8] `D52A:0008`
      ([`notes/amx_wait.md`](notes/amx_wait.md)).
- [x] **D2.** `INT 43` AX=4 default path is `LCD_put` AH=`0x0C` /
      AL=character (`U-INT43-AX4` closed). Not a non-display sink.
- [x] **D3.** Banner path connected: walker, `0040:68AB`/`662B`,
      ports `0xE2`/`0xE0`. Glass stays D3-glass.
- [PARTIAL] **D3-glass.** Pixels on the LC7981 glass. The seven
      AX=0 pairs match HD61830 instruction numbers in MAME’s
      stand-in (`notes/boot_reset_to_bios_banner.md` §9). That
      file is not a manual, and its busy-flag store is commented
      out. Missing: one captured frame (`U-PHYS`) and an
      LC7981 or HD61830 manual (`U-LC7981`).

G1 is complete only when D1 and D3 are `[x]` (D3-glass may stay PARTIAL).

---

## G2 — Shared machinery

- [x] **D4.** Only three `MOV DX,0xFF00`/`OUTSW` sites (all FAC0).
      Second PGR stays live through task 6’s first wait and task 7
      *select*. D510 callers and the task-7 two-level walks do
      not `MOV DX` into `0xFF00-0xFF7E`. A deeper callee remains
      `U-XA-LIVE`.
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
      `SS:SP` to `901C:1130`. U-AMX-WAIT is closed by IVT[8] `D52A:0008`
      ([`notes/amx_wait.md`](notes/amx_wait.md)).
- [x] **D10.** `U-COPY-7C92` closed: DGROUP image at `8010:0000`.
      Directory `[4, 0x5C8)` is 345 `xxxx:8010` ptrs + 19 NULLs +
      the `+0238` numeric island. 21 `MOV AX,8010`. Bulk writer is
      only `FAC0:0074`. `065B` overlays `125C`.. when `ES=8010`.
      `A000` is the ROM source under the first PGR only.
- [ ] **D11.** Find allocators / resource interpreters only when a
      named slice needs them. Blocked: no open slice consumes
      `065B` / `U-AMX-POOL`. No whole-image leaf hunt.

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
      Progress: 366683 owned / 121 gaps. Owned seed and
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
      `[rm]` dests in gaps = 0.       2026-09-22: writer `D52A:06A0` (file
      `0x55940`) is owned. Reached `MOV BX`
      immediates into it are `011D`/`0148`/
      `025D`/`027C`/`0492`. `0492` was the gap
      IP. Seeded `D52A:0492` (file `0x55732`,
      20-bit `0xD5732`, 24-bit `0x0D5732` under
      second PGR slot 53 word `0x0035`, XA=1)
      through `JMP 06A0` (`[0x55732, 0x55742)`).
      `MOV BX,0x011D` at file `0x55588` is
      `JMP BX`, not the store. `0318`/`0328`
      stay unentered (D20). Next byte: file
      `0x55742` (`D52A:04A2`), which that `JMP`
      does not fall into.
      2026-09-22: `D52A:04A2` is not owned.
      File `0x55742`, 20-bit `0xD5742`, 24-bit
      `0x0D5742` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Straight
      line `[0x55742, 0x5575B)` ends `E9 2D 01`
      `JMP 05E8` (file `0x55888`, same gap).
      No near/short, no `A2 04 2A D5`, and no
      `MOV r16,04A2` lands on IP `04A2`.
      In-segment `A2 04` is unowned
      `ADD SI,04A2` at `D52A:2378` (file
      `0x57618`, `81 C6 A2 04`) and owned
      `MOV [8A04],AL` at `D52A:38C3` (file
      `0x58B63`, `A2 04 8A`). Next reached
      gap IP is `D52A:051F` (file `0x557BF`):
      owned `MOV BX,051F` at `D52A:071A`
      (file `0x559BA`, `BB 1F 05`) stores
      `[SI+762E]`; `JMP BX` at `D52A:06ED`
      (file `0x5598D`, `FF E3`) reads it.
      Do not enter `0318`/`0328`.
      2026-09-22: `D52A:051F` is owned. File
      `0x557BF`, 20-bit `0xD57BF`, 24-bit
      `0x0D57BF` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Owned walk
      reaches writer `D52A:071A` (file `0x559BA`,
      `BB 1F 05`) and `JMP BX` at `D52A:06ED`
      (file `0x5598D`, `FF E3`). ROM word at
      file `0x2762E` is `1F 05`. Body:
      `[0x557BF, 0x557ED)`, `D52A:0567`
      `[0x55807, 0x5580A)`, and `D52A:064C`
      through `JMP 06A0` `[0x558EC, 0x55901)`.
      Did not enter `0318`/`0328`/`04A2`.
      2026-09-22: `D52A:054D` is not owned.
      File `0x557ED`, 20-bit `0xD57ED`, 24-bit
      `0x0D57ED` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Straight
      line `[0x557ED, 0x55807)` stops at owned
      `D52A:0567`. Next reached gap IP is
      `D547:0663` (file `0x55AD3`, 20-bit
      `0xD5AD3`, 24-bit `0x0D5AD3`): owned
      `MOV BX,0663` at `D547:05A5` (file
      `0x55A15`, `BB 63 06`) is slot 2 of
      `JMP CS:[DI+0561]` (file `0x559CC`,
      `2E FF A5 61 05`) and stores `[SI+762E]`.
      2026-09-22: `D547:0663` is owned. File
      `0x55AD3`, 20-bit `0xD5AD3`, 24-bit
      `0x0D5AD3` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). `(0xD547<<4)+0x0663`
      masked to the ROM window is `0x55AD3`.
      `D547:0067` calls `04D5` (file `0x55507`,
      `E8 3B 04`). That walk reaches `JMP
      CS:[DI+0561]` (file `0x559CC`, `2E FF A5
      61 05`) and `JMP BX` at `D547:051D`
      (file `0x5598D`, `FF E3`). Slot 2 word
      `A5 05` (file `0x559D5`) is `D547:05A5`
      `MOV BX,0663` (file `0x55A15`, `BB 63 06`)
      then `JMP 0907`, which stores `[SI+762E]`.
      CS at that `JMP BX` is `D547`. Body
      `[0x55AD3, 0x55ADD)` is `88 84 32 76 BB 6D
      06 E9 9A 02` through `JMP 0907`. Next
      reached gap IP is `D547:066D` (file
      `0x55ADD`, bytes `80 3E BD 81 00`).
      2026-09-22: `D547:066D` is owned. File
      `0x55ADD`, 20-bit `0xD5ADD`, 24-bit
      `0x0D5ADD` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Reached
      `MOV BX,066D` at `D547:0667` (file
      `0x55AD7`, `BB 6D 06`) is followed by
      `JMP 0907` (`E9 9A 02`). File `0x55D77`
      (`D1 E6 89 9C 2E 76 C3`) stores
      `[SI+762E]` and returns. `JMP BX` at
      `D547:051D` (file `0x5598D`, `FF E3`)
      reads that word. Body `[0x55ADD, 0x55B03)`
      and `[0x55B17, 0x55B43)` through `JMP
      0907`. `EB 14` skips `[0x55B03, 0x55B17)`.
      Exit `BB 1F 05 E9 34 02` at file `0x55B3D`
      stores `051F`. Next reached gap IP is
      `D547:051F` (file `0x5598F`, 20-bit
      `0xD598F`, 24-bit `0x0D598F`, bytes
      `A8 80 75 03 E9 E1 03`). Did not enter
      `0318`/`0328`/`04A2`/`054D`/`0663`.
      2026-09-22: `D547:051F` is owned. File
      `0x5598F`, 20-bit `0xD598F`, 24-bit
      `0x0D598F` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). `JMP BX`
      at `D547:051D` (file `0x5598D`, `FF E3`)
      does not fall into it. Callers set
      `SI=0` (file `0x55501`, `BE 00 00`) and
      `SI=2` (file `0x55517`, `BE 02 00`)
      before `CALL 04D5`. `04D8` `JZ 0517`
      loads `[SI+762E]` then `SHR SI,1`.
      Owned `MOV BX,051F` at `D547:06CD`
      (file `0x55B3D`, `BB 1F 05 E9 34 02`)
      reaches `0907` (`D1 E6 89 9C 2E 76 C3`),
      whose `SHL SI,1` restores that `SI`
      on the `066D` edges that skip
      `CALLF DA09:0000`. Body
      `[0x5598F, 0x55996)` is `A8 80 75 03
      E9 E1 03` (`TEST AL,0x80` / `JNZ 0526`
      / `JMP 0907`). `0526` and `0907` were
      already owned. Did not enter the sled
      `[0x55B03, 0x55B17)`. Next reached gap
      IP is `D547:0694` (file `0x55B04`,
      20-bit `0xD5B04`, 24-bit `0x0D5B04`,
      head `80 3E BD 81 00 75 32`): slot 3
      of `JMP CS:[DI+0561]` is `D547:05AB`
      (file `0x55A1B`, `BB 94 06 E9 56 03`).
      File `0x55B03` (`90`) stays untargeted.
      Did not enter `0318`/`0328`/`04A2`/
      `054D`/`0663`/`066D`.
      2026-09-22: `D547:0694` is owned. File
      `0x55B04`, 20-bit `0xD5B04`, 24-bit
      `0x0D5B04` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x0694` masked to the ROM
      window is `0x55B04`. Owned walk reaches
      `JMP CS:[BX+053A]` and `JMP CS:[DI+0561]`.
      `AL=0xF3` takes `04E1` (`SHR SI,1`),
      BX-table slot 7 `D547:054A` (file
      `0x559B8`, `4A 05`), which stores `051F`
      then falls into the DI table. Low nibble
      3 is slot 3 `D547:05AB` (file `0x55A1B`,
      `BB 94 06 E9 56 03`). `0907` (`D1 E6 89
      9C 2E 76 C3`) stores `[SI+762E]` at the
      caller `SI` (`0` or `2`) that `JMP BX`
      at file `0x5598D` (`FF E3`) reads. The
      `CL==0` edge reaches that store without
      `CALL 090E`. Body `[0x55B04, 0x55B17)`
      is `80 3E BD 81 00 75 32 80 3E C0 81 00
      74 2B A2 9E D6 B0 6D`. Both jumps land
      on owned `06CD`; fall-through is owned
      `06A7`. Did not enter the `90` at
      `0x55B03`. Next reached gap IP is
      `D547:06D3` (file `0x55B43`, 20-bit
      `0xD5B43`, 24-bit `0x0D5B43`, head
      `88 84 34 76`): BX-table slot 4 is
      `D547:05E7` (word at file `0x559B2`,
      `E7 05`); `MOV BX,06D3` at file
      `0x55A61` (`BB D3 06 E9 10 03`) jumps
      to `0907`. Did not enter `0318`/`0328`/
      `04A2`/`054D`/`0663`/`066D`/`051F`.
      2026-09-22: `D547:06D3` is owned. File
      `0x55B43`, 20-bit `0xD5B43`, 24-bit
      `0x0D5B43` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x06D3` masked to the ROM
      window is `0x55B43`. High nibble `0xC`
      (`AL=0xC0`..`0xCF`) selects BX-table
      slot 4. Slot entry `D547:05E7` is file
      `0x55A57` (`BB 1F 05 F6 06 D8 81 01 74
      03 BB D3 06 E9 10 03`). `[81D8]` bit 0
      clear keeps `BX=051F`; the `JZ` fall-
      through at file `0x55A61` is `MOV
      BX,06D3` / `JMP 0907`. `0907` (`D1 E6
      89 9C 2E 76 C3`) writes `[SI+762E]`.
      `JMP BX` at file `0x5598D` (`FF E3`)
      reads it. Body `[0x55B43, 0x55B4D)` is
      `88 84 34 76 B9 02 00 E9 23 02` through
      `JMP 0900` (owned, file `0x55D70`).
      Did not enter the `90` at `0x55B03`.
      Next reached gap IP is `D547:06DD`
      (file `0x55B4D`, 20-bit `0xD5B4D`,
      24-bit `0x0D5B4D`, head `80 8C 32 76`):
      high nibble `9` selects BX-table slot 1
      `D547:05D7` (word `D7 05` at file
      `0x559AC`); `MOV BX,06DD` at file
      `0x55A51` (`BB DD 06 E9 20 03`). Did
      not enter `0318`/`0328`/`04A2`/`054D`/
      `0663`/`066D`/`051F`.
      2026-09-22: `D547:06DD` is owned. File
      `0x55B4D`, 20-bit `0xD5B4D`, 24-bit
      `0x0D5B4D` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x06DD` masked to the ROM
      window is `0x55B4D`. High nibble `9`
      (`AL=0x90`..`0x9F`) selects BX-table
      slot 1. Slot entry `D547:05D7` is file
      `0x55A47` (`BB 1F 05 F6 06 D7 81 01 74
      03 BB DD 06 E9 20 03`). `[81D7]` bit 0
      clear keeps `BX=051F`; the `JZ` fall-
      through at file `0x55A51` is `MOV
      BX,06DD` / `JMP 0907`. `0907` (`D1 E6
      89 9C 2E 76 C3`) writes `[SI+762E]`.
      `JMP BX` at file `0x5598D` (`FF E3`)
      reads it. Body `[0x55B4D, 0x55B5C)` is
      `80 8C 32 76 90 88 84 34 76 BB EC 06 E9
      1B 02` through `JMP 0907` (owned, file
      `0x55D77`). Did not enter the `90` at
      `0x55B03`. Next reached gap IP is
      `D547:06EC` (file `0x55B5C`, 20-bit
      `0xD5B5C`, 24-bit `0x0D5B5C`, head
      `0A C0 74 19`): `MOV BX,06EC` at file
      `0x55B56` (`BB EC 06 E9 1B 02`). Did
      not enter `0318`/`0328`/`04A2`/`054D`/
      `0663`/`066D`/`051F`.
      2026-09-22: `D547:06EC` is owned. File
      `0x55B5C`, 20-bit `0xD5B5C`, 24-bit
      `0x0D5B5C` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x06EC` masked to the ROM
      window is `0x55B5C`. The `06DD` body is
      reached only when high nibble is `9`
      and `[81D7]` bit 0 is set; that body
      then does `MOV BX,06EC` / `JMP 0907`
      (`BB EC 06 E9 1B 02` at file `0x55B56`).
      `0907` (`D1 E6 89 9C 2E 76 C3`) writes
      `[SI+762E]`. `JMP BX` at file `0x5598D`
      (`FF E3`) reads it. Body
      `[0x55B5C, 0x55B78)` is
      `0A C0 74 19 F6 06 6B 83 FF 74 03 A0 6C
      83 88 84 36 76 C6 84 38 76 40 B9 04 00
      EB 0E` through `JMP` short `0716`. The
      `90` at file `0x55B78` is not entered.
      `[0x55B79, 0x55B8C)` is `80 A4 32 76 EF
      C6 84 36 76 40 B9 03 00 BB DD 06 E9 E4
      01` through `JMP 0900` (owned, file
      `0x55D70`). `090E` pushes and pops
      `BX`, so the join stores owned `06DD`.
      Did not enter `0318`/`0328`/`04A2`/
      `054D`/`0663`/`066D`/`051F` or the `90`
      at `0x55B03`. Next reached gap IP is
      `D547:071C` (file `0x55B8C`, 20-bit
      `0xD5B8C`, 24-bit `0x0D5B8C`, head
      `88 84 34 76`): high nibble `8` selects
      BX-table slot 0 `D547:061D`; `[81D7]`
      bit 0 set falls through to `MOV BX,071C`
      at file `0x55A97` (`BB 1C 07 E9 DA 02`).
      2026-09-22: `D547:071C` is owned. File
      `0x55B8C`, 20-bit `0xD5B8C`, 24-bit
      `0x0D5B8C` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x071C` masked to the ROM
      window is `0x55B8C`. High nibble `8`
      (`AL=0x80`..`0x8F`) selects BX-table
      slot 0. Owned `04D5` reaches
      `JMP CS:[BX+053A]` (`2E FF A7 3A 05`
      at file `0x559A5`); `AND BL,0xF0` /
      `SHR BL,3` / `AND BX,0x0E` at file
      `0x55996` yields index 0. Slot word
      `1D 06` at file `0x559AA` is
      `D547:061D`. Slot body file `0x55A8D`
      is `BB 1F 05 F6 06 D7 81 01 74 03 BB
      1C 07 E9 DA 02`. `[81D7]` bit 0 clear
      takes the `JZ` and keeps `BX=051F`;
      bit 0 set falls through to `MOV
      BX,071C` / `JMP 0907` at file
      `0x55A97`. `0907` (`D1 E6 89 9C 2E 76
      C3`) writes `[SI+762E]`. `JMP BX` at
      file `0x5598D` (`FF E3`) reads it.
      Body `[0x55B8C, 0x55B96)` is
      `88 84 34 76 BB 26 07 E9 E1 01`
      through `JMP 0907`. Did not enter the
      `90` at `0x55B03` or `0x55B78`, or
      `0318`/`0328`/`04A2`/`054D`/`0663`/
      `066D`/`051F`. Next reached gap IP is
      `D547:0726` (file `0x55B96`, 20-bit
      `0xD5B96`, 24-bit `0x0D5B96`, head
      `88 84 36 76`): `MOV BX,0726` at file
      `0x55B90` (`BB 26 07 E9 E1 01`).
      2026-09-22: `D547:0726` is owned. File
      `0x55B96`, 20-bit `0xD5B96`, 24-bit
      `0x0D5B96` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x0726` masked to the ROM
      window is `0x55B96`. High nibble `8`
      and `[81D7]` bit 0 set reach `071C`;
      the owned `071C` body stores `0726` with
      `MOV BX,0726` / `JMP 0907` at file
      `0x55B90` (`BB 26 07 E9 E1 01`) before
      `JMP BX` at file `0x5598D` reads
      `[SI+762E]`. Body `[0x55B96, 0x55BA3)`
      is `88 84 36 76 BB 1C 07 B9 03 00 E9 CD
      01` through `JMP 0900` (owned, file
      `0x55D70`). Did not enter the `90` at
      `0x55B03` or `0x55B78`. Next reached
      gap IP is `D547:0733` (file `0x55BA3`,
      20-bit `0xD5BA3`, 24-bit `0x0D5BA3`,
      head `88 84 34 76`): owned `MOV
      BX,0733` / `JMP 0907` at file `0x55A6D`
      (`BB 33 07 E9 04 03`).
      2026-09-22: `D547:0733` is owned. File
      `0x55BA3`, 20-bit `0xD5BA3`, 24-bit
      `0x0D5BA3` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x0733` masked to the ROM
      window is `0x55BA3`. High nibble `B`
      (`AL=0xB0`..`0xBF`) selects BX-table
      slot 3. Slot word `FD 05` at file
      `0x559B0` is `D547:05FD` (`BB 33 07 E9
      04 03`); no `[81D7]`/`[81D8]` branch on
      that slot. Owned `04D5` reaches `JMP
      CS:[BX+053A]` (file `0x559A5`,
      `2E FF A7 3A 05`); `0907` (`D1 E6 89 9C
      2E 76 C3`) writes `[SI+762E]`; `JMP BX`
      at file `0x5598D` (`FF E3`) reads it.
      Body `[0x55BA3, 0x55BAD)` is
      `88 84 34 76 BB 3D 07 E9 CA 01` through
      `JMP 0907`. Did not enter the `90` at
      `0x55B03` or `0x55B78`. Next reached
      gap IP is `D547:073D` (file `0x55BAD`,
      20-bit `0xD5BAD`, 24-bit `0x0D5BAD`,
      head `88 84 36 76`): the owned `0733`
      body stores `073D` with `MOV BX,073D` /
      `JMP 0907` at file `0x55BA7`
      (`BB 3D 07 E9 CA 01`).
      2026-09-22: `D547:073D` is owned. File
      `0x55BAD`, 20-bit `0xD5BAD`, 24-bit
      `0x0D5BAD` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x073D` masked to the ROM
      window is `0x55BAD`. High nibble `B`
      reaches the owned `0733` body, which
      stores `073D` with `MOV BX,073D` /
      `JMP 0907` at file `0x55BA7`
      (`BB 3D 07 E9 CA 01`); `0907` writes
      `[SI+762E]`; `JMP BX` at file `0x5598D`
      reads it. Body `[0x55BAD, 0x55BF0)` is
      `88 84 36 76` … `BB 33 07 B9 03 00 E9 80
      01` through `JMP 0900` (owned, file
      `0x55D70`). Did not enter the `90` at
      `0x55B03` or `0x55B78`. Next reached
      gap IP is `D547:0780` (file `0x55BF0`,
      20-bit `0xD5BF0`, 24-bit `0x0D5BF0`,
      head `80 3E 74 83 00`): owned `JNZ`
      at file `0x55BC9` (`75 25`).
      2026-09-22: `D547:0780` is owned. File
      `0x55BF0`, 20-bit `0xD5BF0`, 24-bit
      `0x0D5BF0` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x0780` masked to the ROM
      window is `0x55BF0`. High nibble `B`
      reaches owned `073D`; fall-through at
      `074C`/`0752` reaches `0759` `JNZ` when
      `[SI+8081]` bit 0 is set and
      `[SI+7634]==[85B5]` (RAM values
      UNDETERMINED); `0754` `80 3E DB 98 00`
      then `0759` `75 25` enters when
      `[98DB]!=0` (UNDETERMINED). Body
      `[0x55BF0, 0x55C1F)` through `JMP 0907`
      (owned, file `0x55D77`). Did not enter
      the `90` at `0x55B03` or `0x55B78`.
      `D547:07AF` (file `0x55C1F`, head
      `A2 58 97`) is not owned: `07AC`
      `E9 58 01` is `JMP 0907` (file
      `0x55D77`); sequential bytes after that
      `JMP` are not a transfer. Next reached
      gap IP is `D547:07E1` (file `0x55C51`,
      20-bit `0xD5C51`, 24-bit `0x0D5C51`,
      head `80 84 3A 76`): owned
      `MOV BX,07E1` / `JMP 0907` at
      `D547:0581` (file `0x559F1`,
      `BB E1 07 E9 80 03`) stores
      `[SI+762E]`; `JMP BX` at `D547:051D`
      (file `0x5598D`, `FF E3`) reads it
      (pinned `table_bx` in
      `analysis/boot_slice_facts.json`).
      2026-09-22: `D547:07E1` is owned. File
      `0x55C51`, 20-bit `0xD5C51`, 24-bit
      `0x0D5C51` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x07E1` masked to the ROM
      window is `0x55C51`. DI-table slot 0
      (AL&0x0F==0 on the 04E1 path) file
      `0x559D1` bytes `81 05` (word
      `0x0581`); `04D6` `A8 80` requires AL
      bit 7 set. Body `[0x55C51, 0x55C9B)`
      through `JMP 062D` (file `0x55A9D`, gap
      until this pass). Did not enter `07AF`,
      the `90` at `0x55B03` or `0x55B78`.
      `D547:07AF` remains a gap (sequential
      after `0780` `JMP 0907`). Next reached
      gap IP was `D547:062D` (file `0x55A9D`,
      head `BB 34 07`): `0828` `E9 02 FE`.
      2026-09-22: `D547:062D` is owned. File
      `0x55A9D`, 20-bit `0xD5A9D`, 24-bit
      `0x0D5A9D` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x062D` masked to the ROM
      window is `0x55A9D`. Owned `07E1` body
      `0828` `E9 02 FE` (file `0x55C98`) is
      `JMP 062D`. Body `[0x55A9D, 0x55ACD)`
      through `JMP 0907` (owned, file
      `0x55D77`). Did not enter `07AF`,
      `082B`, the `90` at `0x55B03` or
      `0x55B78`, or `CALLF D9C0:0006`. Next
      reached gap IP was `D547:065D` (file
      `0x55ACD`, head `BB 2D 06`): owned
      `JCC` at `D547:063E` (file `0x55AAE`,
      `79 1D`).
      2026-09-22: `D547:065D` is owned. File
      `0x55ACD`, 20-bit `0xD5ACD`, 24-bit
      `0x0D5ACD` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x065D` masked to the ROM
      window is `0x55ACD`. Owned `062D` body
      `063E` `79 1D` (`JNS 065D`; `0630` `0B F6`
      `OR SI,SI` sets SF from SI — SF at `063E`
      after `CALLF DA09:0030` is **UNDETERMINED**).
      Body `[0x55ACD, 0x55AD3)` through `JMP 0907`
      (owned, file `0x55D77`). Did not enter
      `07AF`, `082B`, the `90` at `0x55B03` or
      `0x55B78`, or `CALLF D9C0:0006`. Next open
      gap head in the D547 window is `D547:0491`
      (file `0x55901`, byte `90`); no remaining
      owned `JMP`/`JCC` targets a D547 gap
      (**PROVEN** scan).       Documented deferred gap
      `D547:07AF` (file `0x55C1F`, head
      `A2 58 97`) stays next in the `0780`/`07E1`
      line.
      2026-09-22: `D547:0491` is not owned.
      File `0x55901`, 20-bit `0xD5901`, 24-bit
      `0x0D5901` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). No
      `MOV BX,0491` in CS `D547` and no owned
      `JMP`/`JCC` targets IP `0491`
      (**PROVEN**). Lowest gap head only; not a
      transfer destination. Next reached gap IP
      is `D547:08CF` (file `0x55D3F`, head
      `88 84 34 76`): BX-table slot 6 word
      `03 06` at file `0x559B6`; high nibble
      `E` (`AL=0xE0`..`0xEF`, `TEST AL,0x80` /
      `JMP CS:[BX+053A]`); `[81D9]` bit 0
      set keeps fall-through at `D547:060D`
      (file `0x55A7D`, `BB CF 08 E9 F4 02`).
      `0907` stores `[SI+762E]`; `JMP BX` at
      file `0x5598D` reads it. Did not seed
      `07AF`, `082B`, or the `90` at
      `0x55B03`/`0x55B78`/`0x55D48`.
      2026-09-22: `D547:08CF` is owned. File
      `0x55D3F`, 20-bit `0xD5D3F`, 24-bit
      `0x0D5D3F` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Body
      `[0x55D3F, 0x55D48)` is `88 84 34 76 BB
      D9 08 EB 2F` through `JMPS 0907` (owned,
      file `0x55D77`).
      2026-09-22: `D547:08D9` is owned. File
      `0x55D49`, 20-bit `0xD5D49`, 24-bit
      `0x0D5D49` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Body
      `[0x55D49, 0x55D70)` through `JMPS 0907`
      before owned `0900` (file `0x55D70`):
      `08CF` stores `08D9` with `MOV BX,08D9`
      at file `0x55D43`; entry needs high
      nibble `E` and `[81D9]` bit 0 set to
      reach `08CF` first. All BX/DI
      `[SI+762E]` table bodies through `08D9`
      are owned; the only remaining table
      store target is `07AF` via BX-table slot
      5 word `F7 05` at file `0x559B4`
      (`JMP CS:[BX+053A]` with
      `((AL&0xF0)>>3)&0x0E==10`, e.g.
      `AL=0xD8` on the `04E1` `TEST AL,0x80`
      path): stub `D547:05F7` (file
      `0x55A67`, `BB AF 07 E9 0A 03`) then
      owned `0907` / `JMP BX` at file
      `0x5598D`. **PROVEN** not reached from
      `0780`: `07AC` `E9 58 01` is `JMP 0907`
      (file `0x55D77`); `0x55C1F` is a bounded
      hole only. Did not seed `07AF` (blocked
      reopen). Lowest unowned gap head in CS
      `D547` remains `D547:0491` (file
      `0x55901`, byte `90`, bounded only).
      2026-09-22: `D547:07AF` is owned. File
      `0x55C1F`, 20-bit `0xD5C1F`, 24-bit
      `0x0D5C1F` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Body
      `[0x55C1F, 0x55C4E)` through `JMP 0900`
      (owned, file `0x55D70`): BX-table slot
      5 word `F7 05` at file `0x559B4`;
      index `((AL&0xF0)>>3)&0x0E==10` (**PROVEN**
      high nibble **D**, `AL=0xD0`..`0xDF`, e.g.
      `0xD8` on `04E1` after `TEST AL,0x80` at
      `D547:04D6`, file `0x55946`, `A8 80`);
      stub `D547:05F7` (file `0x55A67`,
      `BB AF 07 E9 0A 03`, no `TEST` on stub);
      `0907` stores `[SI+762E]`; `JMP BX` at
      file `0x5598D` (`FF E3`). **PROVEN** not
      from `0780` (`07AC` `E9 58 01` → `0907`).
      Next reached gap IP: `D547:082B` (file
      `0x55C9B`, head `80 3E DB D7`).
      2026-09-22: `D547:082B` is owned. File
      `0x55C9B`, 20-bit `0xD5C9B`, 24-bit
      `0x0D5C9B` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x082B` masked to the ROM
      window is `0x55C9B`. DI-table slot 1
      (AL&0x0F==1 on the 04E1 path after
      `D547:04D6` `A8 80`, file `0x55946`)
      file `0x559D3` bytes `87 05` (word
      `0x0587`); stub `D547:0587` (file
      `0x559F7`, `80 3E BF 81 00`).
      `[81BF]` nonzero (`74` not taken
      at `058C`, file `0x559FC`),
      `[81BD]==1` (`75` not taken at
      `0593`, file `0x55A03`), and
      `(SI+1)&0xFF` equal to `[81BB]`
      (`75` not taken at `059D`, file
      `0x55A0D`) fall through to
      `D547:059F`
      (file `0x55A0F`, `BB 2B 08 E9 62 03`);
      `0907` stores `[SI+762E]`; `JMP BX` at
      file `0x5598D` (`FF E3`). **PROVEN** not
      from `07E1` (`0828` `E9 02 FE` → `062D`).
      Body `[0x55C9B, 0x55D3E)` through `JMPS
      0907` (owned, file `0x55D77`). Next open
      gap head in CS `D547`: `D547:0491` (file
      `0x55901`, byte `90`; no owned
      `JMP`/`JCC` target — **PROVEN** scan).
      2026-09-22: `D547:07DE` is owned. File
      `0x55C4E`, 20-bit `0xD5C4E`, 24-bit
      `0x0D5C4E` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1). Owned
      `07AF` body `07B7` `74 25` (`JZ 07DE`) and
      `07CF` `7C 0D` (`JL 07DE`); bridge
      `[0x55C4E, 0x55C51)` is `E9 26 01` (`JMP
      0907`, not fall-through from `07DB` `E9 22
      01` → `0900`). **PROVEN** BX/DI stub
      non-default `[SI+762E]` targets and
      reached in-body `Jcc` into D547 gaps are
      exhausted except bounded `0491`. Next open
      gap head in CS `D547`: `D547:0491` (file
      `0x55901`, byte `90`).
      2026-09-22: `D547:0933` is owned. File
      `0x55DA3`, 20-bit `0xD5DA3`, 24-bit
      `0x0D5DA3` under second PGR slot 53 word
      `0x0035` at `0x7AD1E` (XA=1).
      `(0xD547<<4)+0x0933` masked to the ROM
      window is `0x55DA3`. Owned `082B` body
      `CALLN` at `D547:0860` (file `0x55CD0`,
      `E8 D0 00`) and `D547:08BD` (file
      `0x55D2D`, `E8 73 00`) are the only
      near calls to `0933` in CS `D547`.
      `0860` is the `0856` `JZ` (`74 08`);
      `085D` `JMP 08C9` does not fall into it.
      `08BD` is the fall-through of `08BB`
      `JGE 08C0` (`7D 03`). RAM bytes compared
      on those edges are **UNDETERMINED**.
      Body: `AH=AL`, `BX=AL>>5` (`SUB BH,BH`),
      then `TEST AL,0x10`. Bit 4 clear stores
      `AL&0x0F` at `DS:[BX+D7DC]`. Bit 4 set
      and `BX!=3` does `OR [BX+D7DC],AH<<4`.
      `BX==3` with bit 4 set returns without
      that `OR`. `DS` on entry is
      **UNDETERMINED**. Seeds
      `[0x55DA3, 0x55DB9)` through `JMP short
      0956` and `[0x55DBA, 0x55DC7)` through
      `RET`. The `90` at `D547:0949` (file
      `0x55DB9`) is not a target. `RET` at
      `0956` does not fall into `D547:0957`
      (file `0x55DC7`, head `06 56 33 C0`).
      No far immediate and no owned `D547`
      near transfer targets `0957`. Did not
      enter `0491` or `0957`.
      2026-09-22: `C44E:02BF` is owned. File
      `0x4479F`, 20-bit `0xC479F`, 24-bit
      `0x0C479F` under second PGR slot 49
      word `0x0031` at `0x7AD16` (image base
      `0x7ACB4`, XA=1). Owned `00B8` slot 1
      word `5E 00` at file `0x4459A` is
      `C44E:005E` (`90`); fall-through
      `005F` `PUSH CS` / `0060` `E8 5C 02`
      is `CALL 02BF`. `BX<=4` then `SHL 1`
      includes index 1. The value that
      selects index 1 is **UNDETERMINED**.
      Body `[0x4479F, 0x4492D)` reaches
      `RETF` at `044C`. Both switches are
      `MOV BX,SI` / `SUB BX,0x75` /
      `CMP BX,5` / `JA` / `SHL BX,1` /
      `JMP CS:[BX+disp]`. `SI-0x75` above 5
      takes the `JA`. The six-plus-six
      table IPs are local (`040D`/`0442`
      and `03DE`/`03FC`/`03BE`). Tables
      `[0x4492D, 0x44945)`. Callee
      `C44E:0465` `[0x44945, 0x44965)`
      `RETF`s; `[8374]` is
      **UNDETERMINED**. External `CALLF`
      targets are already owned. Did not
      enter `C4C8:000D`. The prior
      “stay unowned (`JMP CS:[BX]`)”
      note is closed for this hole: the
      targets are inside the hole.
      2026-09-22: `C4C8:000D` head is owned.
      File `0x44C8D`, 20-bit `0xC4C8D`,
      24-bit `0x0C4C8D` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `C425:0160` (file
      `0x443B0`, `9A 0D 00 C8 C4`) is
      `CALLF C4C8:000D` on the linear
      stream from file `0x44259`.
      `CMP BX,4` / `JA 0094` / `SHL BX,1` /
      `JMP CS:[BX+0099]`. Index is
      `(SX [BP-1])-1`; `[BP-1]` is
      **UNDETERMINED**. Five slots
      `0069`/`0072`/`007B`/`0084`/`008D`
      are `NOP` / `PUSH CS` / `CALLN` /
      `MOV DL,AL`, then `0094` `MOV AL,DL`
      / `CBW` / `LEAVE` / `RETF`. Head
      `[0x44C8D, 0x44D19)`, table
      `[0x44D19, 0x44D23)`. Callees
      `00A3`/`0FDF`/`12A9`/`1B3F`/`1DC3`
      stay unowned. Next gap head is
      `C4C8:00A3` (file `0x44D23`).
      2026-09-22: `C4C8:00A3` is owned.
      File `0x44D23`, 20-bit `0xC4D23`,
      24-bit `0x0C4D23` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned slot `006B` (file
      `0x44CEB`, `E8 35 00`) is the only
      near caller. Body
      `[0x44D23, 0x45059)` is the whole
      former gap: `PUSH BP` / `MOV BP,SP` /
      `SUB SP,0x0E` / `PUSH SI` / `PUSH DI`,
      one `RETF` at `03D8` (`POP DI` /
      `POP SI` / `LEAVE`). No `BRKXA`.
      Near callees `0448`/`0490`/`04F9`/
      `05B9`/`0927`/`0C64`/`0EC9`/`0F5F`
      stay unowned. What the routine is
      for is **UNDETERMINED**.
      2026-09-22: `C4C8:0448` is owned.
      File `0x450C8`, 20-bit `0xC50C8`,
      24-bit `0x0C50C8` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `00A3` calls it at
      `0186`/`019E`/`01B6` (files
      `0x44E06`/`0x44E1E`/`0x44E36`).
      Body `[0x450C8, 0x45110)` through
      `RETF` at `048F`.       `[BP+6]==0`
      (`74` at `0454`, file `0x450D4`)
      selects the `0EC9` loop. `SI`
      still runs `0..0x0F`, and the
      call is skipped when
      `SI==[BP+0xA]` (`74` at `046F`,
      file `0x450EF`). Otherwise
      `SI` runs `0..0x0F` calling `0927`.
      Both loops then `CALL 0927` with
      `[BP+0xA]` and `[BP+8]`. Those
      argument words are **UNDETERMINED**.
      `0927` and `0EC9` stay unowned.
      Next gap head is `C4C8:0490`
      (file `0x45110`).
      2026-09-22: `C4C8:0490` is owned.
      File `0x45110`, 20-bit `0xC5110`,
      24-bit `0x0C5110` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `00A3` calls it at
      `00F0` and `035E` (files `0x44D70`
      and `0x44FDE`). Body
      `[0x45110, 0x45179)` through `RETF`
      at `04F8`. `INC [F816]`, then
      `ES=DS`, `DI=0x1591`, `CX=0x3C0`,
      `AX=0`, `REP STOSW` (1920 zero
      bytes). `DS` is **UNDETERMINED**.
      Then `SI` runs `0..0x0F` calling
      `05B9`, `CALL 0448` with
      `[BP+0xC]`/`[BP+0xA]`/`[BP+8]`,
      `DEC [F816]`, `CALL 0F5F`, and
      `SI` runs `0..0x0F` calling `04F9`.
      Those callees and the argument
      words stay unowned /
      **UNDETERMINED**. Next gap head is
      `C4C8:04F9` (file `0x45179`).
      2026-09-22: `C4C8:04F9` is owned.
      File `0x45179`, 20-bit `0xC5179`,
      24-bit `0x0C5179` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned callers are `00A3`
      at `02E6` (file `0x44F66`) and
      `0490` at `04E9` (file `0x45169`).
      Body `[0x45179, 0x45239)` through
      `RETF` at `05B8`. `SI=[BP+6]`,
      `AL=[D6A2]`, then `CALLF D9F2:000C`
      with `SI+AX`. `AX<0x23` jumps to
      the epilogue. Otherwise
      `CALLF CFC6:02D6`, `ES=DX`, and
      `AL=ES:[BX]`. `SI*0x0F+7` is
      saved at `[BP-2]` and pushed to
      both `B13A:0000` calls. The first
      loop keeps the original `SI`
      while `0x30-((AL*0x0C)/0x19)` is
      signed above `SI` (`7F` at `0585`,
      file `0x45205`). The second starts
      `SI` at 0 and repeats while `SI`
      is signed below `(AL*0x0C)/0x19`
      (`7C` at `05B3`, file `0x45233`),
      and a zero return leaves early
      (`74` at `05AA`, file `0x4522A`).
      `DS`,
      `[D6A2]`, `[F816]`, and `[BP+6]`
      are **UNDETERMINED**. `B13A:0000`
      (file `0x313A0`) stays unowned.
      Next gap head is `C4C8:05B9`
      (file `0x45239`).
      2026-09-22: `C4C8:05B9` is owned.
      File `0x45239`, 20-bit `0xC5239`,
      24-bit `0x0C5239` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned callers are `00A3`
      at `0336` (file `0x44FB6`) and
      `0490` at `04BF` (file `0x4513F`).
      Body `[0x45239, 0x452F8)` through
      `RETF` at `0677`. Same `D9F2:000C`
      / `AX<0x23` gate as `04F9`, then
      `CALLF CFC6:02D6` and
      `AL=ES:[BX+1]`. Stores immediate
      `0x1591` (the `DI` `0490` zeros)
      and reads `[BX+1429]` after
      `(AL*0x0A)/0x43`, shifted left.
      `SI` runs while `SI<0x0B`, each
      pass reading two bytes through
      that pointer and calling
      `B13A:0000` twice, then adding
      `0x1E` to the `0x1591` pointer.
      `DS`, `[D6A2]`, `[F816]`,
      `[BP+6]`, and `[BX+1429]` are
      **UNDETERMINED**. `B13A:0000`
      stays unowned. Next gap head is
      `C4C8:0678` (file `0x452F8`).
      2026-09-22: `C4C8:0678` stays
      unowned. No owned near transfer
      under `C4C8` reaches it, and the
      image has no far immediate
      `78 06 C8 C4`. The reached gap
      target is `C4C8:0927`.
      2026-09-22: `C4C8:0927` is owned.
      File `0x455A7`, 20-bit `0xC55A7`,
      24-bit `0x0C55A7` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned callers are `00A3`
      at `01EB`/`0220`/`02A9` (files
      `0x44E6B`/`0x44EA0`/`0x44F29`) and
      `0448` at `045C`/`0486` (files
      `0x450DC`/`0x45106`). Body
      `[0x455A7, 0x45602)` through
      `RETF` at `0981`. `BX=[BP+6]<<1`,
      then `AX=[BX+1425]`. `DI` is
      `[BP+8]*0x0F+3`. Immediate
      `0x16F9` is the other pointer.
      `SI` runs while `SI<3`; each pass
      reads one byte through the
      `1425` pointer and calls
      `B13A:0000`, then adds `0x1E` to
      the `0x16F9` pointer. `DS`,
      `[F816]`, `[BP+6]`, `[BP+8]`, and
      `[BX+1425]` are **UNDETERMINED**.
      `B13A:0000` stays unowned. This
      splits the hole: `0678` remains
      the unreached head at `0x452F8`,
      and the next reached head is
      `C4C8:0982` (file `0x45602`).
      2026-09-22: `C4C8:0982` is owned.
      File `0x45602`, 20-bit `0xC5602`,
      24-bit `0x0C5602` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned caller is `0490` at
      `04B4` (file `0x45134`). Body
      `[0x45602, 0x4569E)` through
      `RETF` at `0A1D`. Base is
      `([BP+6]<<2)+0x0264`. Outer count
      `[BP-2]` runs while `<0x10`, the
      middle count while `<3`, and
      `SI` while `<9`. Each inner pass
      calls `B13A:0000` and adds `0x1E`
      to immediate `0x1771`. Each middle
      pass also `CALL 0FB1`, then adds
      `0x78` to that pointer (`83 46 F0
      78` at `09FD`, file `0x4567D`).
      `DS`,
      `[F816]`, and `[BP+6]` are
      **UNDETERMINED**. `0A1E` (file
      `0x4569E`) has no owned caller.
      `0FB1` (file `0x45C31`) and
      `B13A:0000` stay unowned. Next
      reached head is `C4C8:0A99`
      (file `0x45719`).
      2026-09-22: `C4C8:0A99` is owned.
      File `0x45719`, 20-bit `0xC5719`,
      24-bit `0x0C5719` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned caller is `0490` at
      `04A9` (file `0x45129`), which
      pushes `0` at `04A5` (file
      `0x45125`). Body
      `[0x45719, 0x4576F)` through
      `RETF` at `0AEE`. `DI` starts at
      `[BP+6]` and runs while `DI<0x40`.
      Each row starts at
      `DS:([BP+6]*0x1E+0x1591)` and the
      pointer advances `0x1E`. With the
      pushed `0`, that is `0x40` rows,
      `0x780` bytes, the same length
      `0490` zeros at `DI=0x1591`.
      `DS` is **UNDETERMINED**. Each row
      sets 15 bits: `SI<0x0F`, `DX`
      starts at `0x0C` and adds `0x0F`,
      and the bit is
      `1<<(7-(DX&7))` at
      `ES:[BX+(DX>>3)]`. `0AEF` (file
      `0x4576F`) has no owned caller.
      Next reached head is `C4C8:0C64`
      (file `0x458E4`).
      2026-09-22: `C4C8:0C64` is owned.
      File `0x458E4`, 20-bit `0xC58E4`,
      24-bit `0x0C58E4` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned caller is `00A3` at
      `0375` (file `0x44FF5`). Body
      `[0x458E4, 0x45971)` through
      `RETF` at `0CD2` and `0CF0`.
      `DI=[BP+8]`, `AX=[D6A2]>>4`.
      `[BP+0xC]==0` (`74` at `0C7E`,
      file `0x458FE`) calls `0C35`
      once and sets `DX` to
      `1<<[BP+0xA]` (`D3 E2` at
      `0CAF`, file `0x4592F`).
      Otherwise `SI` runs `0..0x0F`
      calling `0C35`, then `DX` is
      `0xFFFF`. `DI!=0` does `SHL BX,1` at
      `0CB8` (file `0x45938`) and
      stores `DX` at `[BX+9738]`,
      then ORs `2` into `[9749]` and
      waits while that word is
      nonzero (`75` at `0CCD`, file
      `0x4594D`). `DI==0` does the
      same shift at `0CD6` (file
      `0x45956`) and stores at
      `[BX+9740]`, then ORs `1` into
      `[9749]` and waits while that
      word is nonzero (`75` at
      `0CEB`, file `0x4596B`). Both
      indexes are `([D6A2]>>4)<<1`.
      `DS`, `[D6A2]`,
      and the stack arguments are
      **UNDETERMINED**. `0C35` stays
      unowned until this body is the
      caller. `0CF1` (file `0x45971`)
      has no owned caller. Next reached
      head is `C4C8:0C35` (file
      `0x458B5`).
      2026-09-22: `C4C8:0C35` is owned.
      File `0x458B5`, 20-bit `0xC58B5`,
      24-bit `0x0C58B5` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `0C64` calls it at
      `0C89` and `0CA3` (files `0x45909`
      and `0x45923`). Body
      `[0x458B5, 0x458E4)` through
      `RETF` at `0C53` and `0C63`.
      `AX=[BP+8]`, `DX=[BP+0xA]`.
      `byte [BP+6]==0x2B` calls `0B8F`;
      otherwise it calls `0AEF`. Both
      calls push `[BP+8]`, the
      sign-extended `[D6A2]`, and
      `[BP+0xA]`. `DS` and `[D6A2]` are
      **UNDETERMINED**. `0AEF` (file
      `0x4576F`) and `0B8F` (file
      `0x4580F`) stay unowned. Next
      reached head is `C4C8:0AEF`
      (file `0x4576F`).
      2026-09-22: `C4C8:0AEF` is owned.
      File `0x4576F`, 20-bit `0xC576F`,
      24-bit `0x0C576F` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `0C35` calls it at
      `0C5C` (file `0x458DC`) when
      `byte [BP+6]` is not `0x2B`. Body
      `[0x4576F, 0x4580F)` through
      `RETF` at `0B45` and `0B8E`.
      `DI=[BP+6]`, `SI=DI+[BP+8]`.
      `[BP+0xA]==0` reads `ES:[BX]`
      after `D9F2:000C` / `CFC6:02D6`,
      subtracts `[D69A]<<1`, calls
      `D9A2:0004`, then owned `04F9`.
      Otherwise it reads `ES:[BX+1]`,
      subtracts `[D69A]*3`, calls
      `D9A2:0031`, then owned `05B9`.
      A zero byte (`74` at `0B21`,
      file `0x457A1`, and `74` at
      `0B66`, file `0x457E6`) skips
      the calls and returns. A
      negative difference (`7D` not
      taken at `0B2C`, file `0x457AC`,
      and at `0B75`, file `0x457F5`)
      is forced to 0 and the calls
      still run. `DS`, `[D69A]`, and the
      stack words are **UNDETERMINED**.
      Next reached head is `C4C8:0B8F`
      (file `0x4580F`).
      2026-09-22: `C4C8:0B8F` is owned.
      File `0x4580F`, 20-bit `0xC580F`,
      24-bit `0x0C580F` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `0C35` calls it at
      `0C4C` (file `0x458CC`) when
      `byte [BP+6]==0x2B`. Body
      `[0x4580F, 0x458B5)` through
      `RETF` at `0BE8` and `0C34`,
      filling the gap up to owned
      `0C35`. Same `D9F2` / `CFC6` /
      `04F9` / `05B9` shape as `0AEF`,
      A zero `[BP+0xA]` reads
      `ES:[BX]`. A signed value
      `>=0x64` (`7D` at `0BC2`, file
      `0x45842`) returns. Otherwise
      `DX` increases by `[D69A]<<1`
      and a signed value above
      `0x64` becomes `0x64`. The
      other arm reads `ES:[BX+1]`.
      A signed value `>=0x64` (`7D`
      at `0C0A`, file `0x4588A`)
      returns. Otherwise `DX`
      increases by `[D69A]*3`
      (`SHL` then `ADD AX,[D69A]`
      at `0C11`, file `0x45891`)
      and a signed value above
      `0x64` becomes `0x64`. `DS`, `[D69A]`, and the
      stack words are **UNDETERMINED**.
      Next reached head is `C4C8:0EC9`
      (file `0x45B49`).
      2026-09-22: `C4C8:0EC9` is owned.
      File `0x45B49`, 20-bit `0xC5B49`,
      24-bit `0x0C5B49` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned callers are `00A3`
      at `01D9`/`020E`/`027E`/`029B`
      (files `0x44E59`/`0x44E8E`/
      `0x44EFE`/`0x44F1B`), `0448` at
      `0474` (file `0x450F4`), and
      `0FDF` at `1103`/`112E`/`1197`/
      `11B2` (files `0x45D83`/`0x45DAE`/
      `0x45E17`/`0x45E32`). Body
      `[0x45B49, 0x45B8D)` through
      `RETF` at `0F0C`. `DI` is the
      low 16 of `[BP+6]*0x0F`, plus
      `3`. Immediate `0x16F9` is the
      pointer. `SI` starts at 0 and
      repeats while signed `<3` (`7C`
      at `0F07`, file `0x45B87`).
      Each pass does `MOV AL,[F816]`
      then `PUSH AX`. The first pass
      still has the high byte of `DI`
      in `AH`. Later passes leave
      `AH` as the previous `B13A`
      return. Each pass then pushes `5`, `0`,
      `DI`, `DS`, and the pointer,
      `CALLF B13A:0000`, and adds
      `0x1E` to the pointer. `DS`,
      `[F816]`, and `[BP+6]` are
      **UNDETERMINED**. `B13A:0000`
      stays unowned. `0F0D` (file
      `0x45B8D`) has no owned caller.
      Next reached head is `C4C8:0F5F`
      (file `0x45BDF`).
      2026-09-22: `C4C8:0F5F` is owned.
      File `0x45BDF`, 20-bit `0xC5BDF`,
      24-bit `0x0C5BDF` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned callers are `00A3`
      at `039F` (file `0x4501F`),
      `0490` at `04E1` (file `0x45161`),
      `0678` at `06C9` (file `0x45349`),
      and `0FDF` at `1270` (file
      `0x45EF0`).
      Body `[0x45BDF, 0x45C19)` through
      `RETF` at `0F98`, up to owned
      `0F99`. Stores `1` at `[98DC]`.
      Then `CALL 0F99` four times with
      push pairs `(0x32,0)`, `(7,1)`,
      `(0x1D,2)`, and `(0x3F,3)`, and
      `CALL 0F0D`. `DS` and `[98DC]` are
      **UNDETERMINED**. `0F99` (file
      `0x45C19`) is already owned.
      `0F0D` stays unowned. Next reached
      head is `C4C8:0F0D` (file
      `0x45B8D`).
      2026-09-22: `C4C8:0F0D` is owned.
      File `0x45B8D`, 20-bit `0xC5B8D`,
      24-bit `0x0C5B8D` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `0F5F` calls it at
      `0F95` (file `0x45C15`) with
      `PUSH CS` and no stack argument.
      Body `[0x45B8D, 0x45BDF)` through
      `RETF` at `0F5E`, filling the gap
      up to owned `0F5F`. `CALL 0F99`
      with `(0x0A,0)` and `(0x0B,0)`,
      then `SI` runs while `SI` is
      signed `< 0x0780` (`7C` at
      `0F5B`, file `0x45BDB`). Each
      byte `[SI+1591]` is passed to
      `0F99` with `0x0C`. A zero byte
      passes 0 (`74` at `0F32`, file
      `0x45BB2`). Any other byte is
      reversed into `DL`: eight
      times, `ROL DL,1` (`D0 E2` at
      `0F36`, file `0x45BB6`), add
      bit 0 of `BL`, then `ROR BL,1`. `0x0780` is
      the same length `0490` zeros at
      `DI=0x1591`. `DS` is
      **UNDETERMINED**. `0F99` is
      already owned. Next reached head
      is `C4C8:0FB1` (file `0x45C31`).
      2026-09-22: `C4C8:0FB1` is owned.
      File `0x45C31`, 20-bit `0xC5C31`,
      24-bit `0x0C5C31` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `0982` calls it at
      `09C6` (file `0x45646`) and stores
      the returned `DX:AX` at
      `[BP-8]`. Body
      `[0x45C31, 0x45C5F)` through
      `RETF` at `0FCE` and `0FDE`.
      `DL=[BP+6]`. `SI` scans
      `[SI+13E5]` until a `0` byte or a
      match. A match returns
      `DX=DS` and `AX=[BX+13FB]` with
      `BX=SI<<1`. No match returns
      `DX=DS` and `AX=[13FB]`. `DS`
      and both tables are
      **UNDETERMINED**. Next reached
      head is `C4C8:0FDF` (file
      `0x45C5F`).
      2026-09-22: `C4C8:0FDF` is owned.
      File `0x45C5F`, 20-bit `0xC5C5F`,
      24-bit `0x0C5C5F` under second PGR
      slot 49 word `0x0031` at `0x7AD16`
      (XA=1). The owned `000D` table
      slot `0072` is `NOP`; `0074`
      (file `0x44CF4`) is `CALL 0FDF`.
      Body `[0x45C5F, 0x45F29)` through
      the one `RETF` at `12A8`. Stores
      `0` at `[7D79]`, then
      `CALLF B1B1:0002`. Local jumps
      share an exit at `1299`. Near
      calls reach owned `0409`, `0448`,
      `0927`, `0EC9`, and `0F5F`.
      `0678`, `06E1`, and `0E5A` stay
      unowned. `DS` and `[7D79]` are
      **UNDETERMINED**. Next reached
      head is `C4C8:12A9` (file
      `0x45F29`).
      2026-09-22: `C4C8:12A9` reached
      runs are owned. File `0x45F29`,
      20-bit `0xC5F29`, 24-bit
      `0x0C5F29` under second PGR slot
      49 word `0x0031` at `0x7AD16`
      (XA=1). The owned `000D` table
      slot `007B` is `NOP`; `007D`
      (file `0x44CFD`) is `CALL 12A9`.
      The local walk covers 667 bytes
      in four runs and stops on three
      `JMP CS:[BX+disp]` (`+1850`,
      `+1844`, `+1818`). Entry `XOR DX,DX`
      then jumps to `180C`: `DX==0`
      jumps to `12B5`, otherwise
      `RETF`. The unreached bytes
      between the runs stay unowned.
      Purpose, `DS`, and the indirect
      tables are **UNDETERMINED**.
      Next reached head is
      `C4C8:1B3F` (file `0x467BF`).
      2026-09-22: `C4C8:1B3F` is owned.
      File `0x467BF`, 20-bit `0xC67BF`,
      24-bit `0x0C67BF` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). The owned
      `000D` table slot `0084` is
      `NOP`; `0086` (file `0x44D06`)
      is `CALL 1B3F`. Body
      `[0x467BF, 0x468BC)` through the
      one `RETF` at `1C3B`.       It calls `B509:2289`. Then
      `B1B1:0026` with `(0,1)`,
      `(0,2)`, and `(0,3)`, each
      followed by `B354:01C6` with
      pointers `0xE60F`, `0xE610`,
      and `0xE611`. Then `B1B1:0026`
      with `(0,4)`, `B1B1:005B`,
      `B1B1:0026` with `(0,5)`
      and `B354:01C6` with `0xE612`,
      then `B1B1:0026` with `(0x17,5)`,
      `B1B1:005B`, and `B77C:20C5`.
      The first pass jumps to the
      `B060:035D` call (`EB` at
      `1C0E`, file `0x4688E`) and does
      not read `[7D79]`. It repeats
      while the returned `AL` is 0
      (`74` at `1C37`, file
      `0x468B7`). Later passes read
      `[7D79]` at `1C10`. `75` at
      `1C17` (file `0x46897`) skips
      `1D83` and `1C57` unless the
      sign-extended byte is 2.
      `DS`, `[7D79]`, and the pointer
      immediates are **UNDETERMINED**.
      The bytes at `0x46498` stay
      unowned. Next reached head is
      `C4C8:1DC3` (file `0x46A43`).
      2026-09-22: `C4C8:1DC3` is owned.
      File `0x46A43`, 20-bit `0xC6A43`,
      24-bit `0x0C6A43` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). The owned
      `000D` table slot `008D` is
      `NOP`; `008F` (file `0x44D0F`)
      is `CALL 1DC3`. Body
      `[0x46A43, 0x46C2B)` through the
      one `RETF` at `1FAA`. It calls
      owned `1D83` and saves `DX` and
      `AX`. Byte `[BP-1]` runs `0`,
      `1`, and `2` (`CMP` 3 at `1EA1`).
      Each pass calls `B354:03B1`
      three times and `B354:01C6`
      once. Later, `CALLF B060:035D`
      repeats while `AL` is 0.       If the
      sign-extended `AL` is `0x78`
      (`98` then `CMP AX,0x0078` at
      `1F50`, file `0x46BD0`), a
      nonzero `ES:[BX]` (`74` not
      taken at `1F68`, file
      `0x46BE8`) stores `0` and calls
      `1C3C`. A zero `ES:[BX]` stores
      `1` and calls `1C57`. Both arms
      call `B1B1:005B` first, then
      set `DL` to `0` and repeat the
      `B060:035D` call. The `RETF`
      returns sign-extended `DL` when
      `DL` is not `0` (`74` at `1FA4`,
      file `0x46C24`). A zero `DL`
      repeats that call.
      `DS`, `ES:[BX]`, and the `1D83`
      result are **UNDETERMINED**.
      `1FAB` (file `0x46C2B`) has no
      owned caller. Next reached head
      is `C4C8:0678` (file `0x452F8`).
      2026-09-22: `C4C8:0678` is owned.
      File `0x452F8`, 20-bit `0xC52F8`,
      24-bit `0x0C52F8` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Owned `0FDF`
      calls it at `102A` (file
      `0x45CAA`) and `1234` (file
      `0x45EB4`). Body
      `[0x452F8, 0x45361)` through the
      one `RETF` at `06E0`. It
      increments `[F816]`, then
      `REP STOSW` writes `0x3C0` zero
      words at `ES:1591` with `ES=DS`.
      It calls owned `0A99` with `0`,
      owned `0982` with `[BP+6]`, and
      owned `0448` with `[BP+8]`,
      `[BP+0xA]`, and `[BP+0xC]`.
      `SI` runs `0..0x0F` through
      unowned `07A2`, then again
      through unowned `06E1`. It
      decrements `[F816]` and calls
      owned `0F5F`. `DS`, `[F816]`,
      and the stack words are
      **UNDETERMINED**. Next reached
      head is `C4C8:06E1` (file
      `0x45361`).
      2026-09-22: `C4C8:06E1` is owned.
      File `0x45361`, 20-bit `0xC5361`,
      24-bit `0x0C5361` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1).       Owned `0678`
      calls it at `06D1` (file
      `0x45351`), owned `0FDF`
      calls it at `120C` (file
      `0x45E8C`), owned `0CF1` at
      `0D3F` (file `0x459BF`), and
      owned `0D8B` at `0DDC` (file
      `0x45A5C`). Body
      `[0x45361, 0x45422)` through the
      one `RETF` at `07A1`. `SI` is
      `[BP+6]`. `AL` is `[D6A2]`.
      `DX=SI+AX`, then
      `CALLF D9F2:000C`. `AX<0x23`
      returns. Otherwise
      `CALLF CFC6:033A` and `AL` is
      `ES:[BX+2]`. The word at
      `[BP-0xA]` is immediate
      `0x1771`. The first loop runs
      while `SI` is signed `<`
      `0x30-DI` (`7F` at `076E`,
      file `0x453EE`) and calls
      `B13A:0000` with push `3,0`.
      The second loop is entered only
      when `DI` is signed `> 0`
      (`XOR SI,SI`, `CMP SI,DI`,
      `7D` at `0774`, file `0x453F4`,
      not taken). It then runs while
      `SI` is signed `< DI` (`7C` at
      `079C`, file `0x4541C`) and
      calls `B13A:0000` with push
      `3,7`, stopping early when the
      returned `AX` is 0 (`8B D0` /
      `0B D2` / `74` at `0793`, file
      `0x45413`).
      `DS`, `[D6A2]`, `[F816]`, and
      `[BP+6]` are **UNDETERMINED**.
      `B13A:0000` stays unowned. Next
      reached head is `C4C8:07A2`
      (file `0x45422`).
      2026-09-22: `C4C8:07A2` reached
      runs are owned. File `0x45422`,
      20-bit `0xC5422`, 24-bit
      `0x0C5422` under second PGR slot
      49 word `0x0031` at `0x7AD16`
      (XA=1). Owned `0678` calls it at
      `06A7` (file `0x45327`) with
      `SI`. Owned `0CF1` calls it at
      `0D81` (file `0x45A01`) and
      owned `0D8B` at `0E21` (file
      `0x45AA1`). `AL` is `[D6A2]`.
      `DX=[BP+6]+AX`, then
      `CALLF D9F2:000C`. `AX<0x23`
      returns at `07C7`. Otherwise
      `AL` is `ES:[BX+3]` masked with
      `0x0F`. `SI>9` jumps to `08D4`.
      `SI<=9` is `JMP CS:[BX+0913]`.
      The 139 bytes after that jump
      and the table at `0913` stay
      unowned. `08D4` calls
      `B13A:0000` while `SI<9`, adding
      `0x1E` to immediate `0x1591`,
      then `RETF` at `0912`. `DS`,
      `[D6A2]`, `[BP+6]`, and the
      indirect table are
      **UNDETERMINED**. Next reached
      head is `C4C8:0E5A` (file
      `0x45ADA`).
      2026-09-22: `C4C8:0E5A` is owned.
      File `0x45ADA`, 20-bit `0xC5ADA`,
      24-bit `0x0C5ADA` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Owned `0FDF`
      calls it at `1248` (file
      `0x45EC8`). Body
      `[0x45ADA, 0x45B49)` through the
      one `RETF` at `0EC8`. `DI` is
      `[BP+8]`. `AX` is `[D6A2]`
      shifted right 4. If `[BP+0xC]`
      is 0 it calls unowned `0E2B`
      once and sets `DX` to
      `1<<[BP+0xA]`. Otherwise `SI`
      runs `0..0x0F` through `0E2B`
      and `DX` is `0xFFFF`.       If `DI`
      is 0 it does `SHL BX,1`
      (`D1 E3` at `0EAE`, file
      `0x45B2E`) and stores `DX` at
      `[BX+9730]` (`89 97 30 97` at
      `0EB0`, file `0x45B30`). That
      index is `([D6A2]>>4)<<1`. It
      ORs `4` into `[9749]`, reloads
      the same index (`D1 E3` at
      `0EBC`, file `0x45B3C`), and
      waits while the word is
      nonzero (`75` at `0EC3`, file
      `0x45B43`). `DS`, `[D6A2]`,
      and the stack words are
      **UNDETERMINED**. The bytes at
      `0x45971` stay unowned. Next
      reached head is `C4C8:0E2B`
      (file `0x45AAB`).
      2026-09-22: `C4C8:0E2B` is owned.
      File `0x45AAB`, 20-bit `0xC5AAB`,
      24-bit `0x0C5AAB` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Owned `0E5A`
      calls it at `0E7F` (file
      `0x45AFF`) and `0E99` (file
      `0x45B19`). Body
      `[0x45AAB, 0x45ADA)` through
      `RETF` at `0E49` and `0E59`.
      `AX` is `[BP+8]` and `DX` is
      `[BP+0xA]`. Byte `[BP+6]==0x2B`
      calls unowned `0D8B`; otherwise
      it calls unowned `0CF1`. Both
      paths push `[BP+8]`,
      sign-extended `[D6A2]`, and
      `[BP+0xA]`. `DS` and `[D6A2]`
      are **UNDETERMINED**. Next
      reached head is `C4C8:0CF1`
      (file `0x45971`).
      2026-09-22: `C4C8:0CF1` is owned.
      File `0x45971`, 20-bit `0xC5971`,
      24-bit `0x0C5971` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Owned `0E2B`
      calls it at `0E52` (file
      `0x45AD2`) when byte `[BP+6]`
      is not `0x2B`. Body
      `[0x45971, 0x45A0B)` through
      `RETF` at `0D48` and `0D8A`.
      `DI` is `[BP+6]` and
      `SI=DI+[BP+8]`. If `[BP+0xA]`
      is 0, `AL` is `ES:[BX+2]` after
      `D9F2:000C` and `CFC6:033A`. A
      zero byte returns. Otherwise
      `DX` is reduced by `[D69A]<<1`,
      clamped at 0, then
      `CALLF D9A2:005F` and owned
      `06E1`.       The other path reads
      `ES:[BX+3]` masked with `0x0F`.
      A zero nibble (`74` at `0D6C`,
      file `0x459EC`) returns.
      Otherwise `DX` is decremented
      (`4A` at `0D6E`). `7D` at
      `0D71` (file `0x459F1`) forces
      a negative result to 0, then
      `D9A2:008D` and owned `07A2`.
      `DS`, `[D69A]`, and the stack
      words are **UNDETERMINED**.
      Next reached head is
      `C4C8:0D8B` (file `0x45A0B`).
      2026-09-22: `C4C8:0D8B` is owned.
      File `0x45A0B`, 20-bit `0xC5A0B`,
      24-bit `0x0C5A0B` under second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Owned `0E2B`
      calls it at `0E42` (file
      `0x45AC2`) when byte `[BP+6]`
      is `0x2B`. Body
      `[0x45A0B, 0x45AAB)` through
      `RETF` at `0DE5` and `0E2A`.
      `DI` is `[BP+6]` and
      `SI=DI+[BP+8]`. If `[BP+0xA]`
      is 0, a byte already `>=0x64`
      returns. Otherwise `DX` is
      increased by `[D69A]<<1` and
      clamped to `0x64`, then
      `CALLF D9A2:005F` and owned
      `06E1`. The other path masks
      `ES:[BX+3]` with `0x0F`. A
      value `>=9` returns. Otherwise
      `DX` is incremented and clamped
      to `9`, then `D9A2:008D` and
      owned `07A2`. `DS`, `[D69A]`,
      and the stack words are
      **UNDETERMINED**. No further
      owned near transfer under
      `C4C8` reaches a gap.
      2026-09-22: `D9A2:008D` is owned.
      File `0x59AAD`, 20-bit `0xD9AAD`,
      24-bit `0x0D9AAD` under second
      PGR slot 54 word `0x0036` at
      `0x7AD20` (XA=1). Owned
      `C4C8:0CF1` calls it at `0D77`
      (file `0x459F7`) and owned
      `C4C8:0D8B` calls it at `0E17`
      (file `0x45A97`). Body
      `[0x59AAD, 0x59AE7)` is the
      whole gap through the one
      `RETF` at `00C6`. It pushes
      `[BP+6]` and calls
      `D9F2:000C`. `AX<0x23` returns.
      Otherwise `CALLF CFC6:033A`,
      then `ES:[BX+3]` becomes
      `(old & 0x80) | byte [BP+8]`.
      `DS`, `[BP+6]`, and `[BP+8]`
      are **UNDETERMINED**. Owned
      `D9A2:005F` is the `+2` sibling.
      No other owned far immediate
      targets a gap start.
      2026-09-22: `B3FD:0B0B` is owned.
      File `0x34ADB`, 20-bit `0xB4ADB`,
      24-bit `0x0B4ADB` under second
      PGR slot 45 word `0x002D` at
      `0x7AD0E` (XA=1). The owned
      `B3FD:0006` body calls it at
      `03EC` (file `0x343BC`). Body
      `[0x34ADB, 0x34D23)` through
      the one `RETF` at `0D52`. It
      calls `E704:0007` and
      `D6CC:0004`, then `B1B1` /
      `B354` with the same shape as
      the `C4C8` slot bodies.
      `CALLF B060:035D` returns in
      `AX`, copied to `SI`. `75` at
      `0BF6` (file `0x34BC6`) is
      `JNZ`: `SI==0x79` clears `SI`
      and skips `0953`. `SI!=0x79`
      calls `0953`, then the
      sign-extended byte `[7D79]` is
      tested for 0 and for 1.       `AX` copied from `SI` selects
      the later stores. `0x75`
      (`E9` at `0C48`, file
      `0x34C18`) stores `2` at byte
      `[D7CA]` and calls `0D53`.
      `0x78` and `0x7A` take the
      other store paths and jump to
      the epilogue at `0D4D` (file
      `0x34D1D`) without that call.
      Any other nonzero value also
      returns there without the
      call.
      `DS` and those memory operands
      are **UNDETERMINED**. The
      prefix at `0x34A9C` and
      `B3FD:0F79` stay unowned. Next
      reached head is `B3FD:0D53`
      (file `0x34D23`).
      2026-09-22: `B3FD:0D53` is owned.
      File `0x34D23`, 20-bit `0xB4D23`,
      24-bit `0x0B4D23` under second
      PGR slot 45 word `0x002D` at
      `0x7AD0E` (XA=1). Owned `0B0B`
      calls it at `0D48` (file
      `0x34D18`). Body
      `[0x34D23, 0x34EB9)` through
      the one `RETF` at `0EE8`. It
      calls `B509:2289` with
      `DS:204F` and `B1B1:0026`
      with `(1,0)`.       It calls `0ACC` at `0D96`
      (file `0x34D66`) with `0x0E`,
      `1`, and zero-extended
      `[89F1]` (`MOV AH,0` at
      `0D92`, file `0x34D62`). It
      calls `0ACC` again at `0DE6`
      (file `0x34DB6`) with those
      same values only when the
      sign-extended `[7D79]` is 0
      (`75` at `0DD9`, file
      `0x34DA9`, not taken).
      `CALLF B77C:20EA` stays
      unowned. `CALLF B060:035D`
      repeats while `AX` is 0.
      `AX==0x78` (`74` at `0DFF`,
      file `0x34DCF`) stores `0` at
      `[89EF]` and `[89F0]`, then
      returns the sign-extended
      `[D7CB]` (`MOV AX,DX` at
      `0EE3`, file `0x34EB3`).
      `AX==0x79` (`E9` at `0E06`,
      file `0x34DD6`) stores `3` at
      `[D7CA]` and calls `0EE9`.
      Any other nonzero `AX` jumps
      to that same `MOV AX,DX`.
      The `RETF` at `0EE8` returns
      that `AX`. `DS`,
      `[89F1]`, and `[D7CA]` are
      **UNDETERMINED**. Next reached
      head is `B3FD:0EE9` (file
      `0x34EB9`).
      2026-09-22: `B3FD:0EE9` is owned.
      File `0x34EB9`, 20-bit `0xB4EB9`,
      24-bit `0x0B4EB9` under second
      PGR slot 45 word `0x002D` at
      `0x7AD0E` (XA=1). Owned `0D53`
      calls it at `0EDE` (file
      `0x34EAE`). Body
      `[0x34EB9, 0x34F49)` through
      the one `RETF` at `0F78`. It
      calls `B509:2289` with
      `DS:20B0`, `B1B1:0026` with
      `(1,0)`, and `B1B1:005B` with
      `DS:20C1`. `CALLF B77C:20EA`
      stays unowned. `CALLF
      B060:035D` repeats while `AX`
      is 0. When `AX==0x78` it zeros
      `0x1388` words at `A99C`, zeros
      `0x0A` words at `A988`, fills
      `0x0A` words at `A974` with
      `0x0101`, calls owned
      `E661:00EC`, and zeros `0x32`
      words at `A7BC`. It stores `0`
      at `[89F0]` and `[89EF]`, and
      `1` at `[89F1]`, then returns
      sign-extended `[D7CB]`. The
      other exit returns the `AX`
      from `B060:035D`. `DS`,
      `[D7CB]`, and those fills are
      **UNDETERMINED**. `B3FD:0ACC`
      stays unowned. Next reached
      head is `B3FD:0F79` (file
      `0x34F49`), called from owned
      `B3FD:03FB`.
      2026-09-22: `B3FD:0F79` is owned.
      File `0x34F49`, 20-bit `0xB4F49`,
      24-bit `0x0B4F49` under second
      PGR slot 45 word `0x002D` at
      `0x7AD0E` (XA=1). Owned
      `B3FD:0006` calls it at `03FB`
      (file `0x343CB`). Body
      `[0x34F49, 0x35098)` through
      the one `RETF` at `10C7`. It
      calls owned `E704:0007` and
      `D6CC:0004`, reads `[89F1]`
      into `[BP-2]`, and calls
      unowned `E605:000E` into
      `[BP-4]`. It calls `B509:2289`
      with `DS:20F3` and `B1B1:0026`
      with `(1,0)`, then
      `B354:03B1`. It calls unowned
      `0ACC` with `(0x14, 1, [BP-2])`.
      A second `B354:03B1` is followed
      by unowned `B77C:1F26` with
      `(0x14, 2, [BP-4])`. It calls
      `B1B1:0026` with `(4,0)` and
      `(5,0)`, each followed by
      `B1B1:005B`, then unowned
      `B77C:20EA`. The first pass
      skips the `[7D79]` test. Then
      `CALLF B060:035D` repeats while
      `AX` is 0. While it is 0,
      `[7D79]==0` calls `0ACC` again
      and `[7D79]==1` calls
      `B77C:1F26` again. When the
      returned `DX` is `0x78` it
      calls `B1B1:0026` with `(7,0)`,
      `B1B1:005B` with `DS:2171`, and
      unowned `E617:0004` with
      `([BP-2]-1, [BP-4])`. A
      non-zero `E617` result (`74`
      not taken at `10B3`, file
      `0x35083`) calls `B3C7:0007`.
      Both that arm and a zero
      `E617` result return the
      sign-extended `[D7CB]`
      (`MOV AX,DX` at `10C4`, file
      `0x35094`). `DX!=0x78` (`75`
      at `1084`, file `0x35054`)
      jumps there with `DX` still
      the `B060` return. `DS`, `[89F1]`,
      `[7D79]`, and `[D7CB]` are
      **UNDETERMINED**. The byte
      after the `RETF` (file
      `0x35098`) has no owned caller.
      Next reached head is
      `B3FD:0ACC` (file `0x34A9C`).
      2026-09-22: `B3FD:0ACC` is owned.
      File `0x34A9C`, 20-bit `0xB4A9C`,
      24-bit `0x0B4A9C` under second
      PGR slot 45 word `0x002D` at
      `0x7AD0E` (XA=1). The body
      `[0x34A9C, 0x34ADB)` is the
      whole gap in front of owned
      `0B0B`, through the one `RETF`
      at `0B0A`. Owned `0D53` calls
      it at `0D96` and, when
      `[7D79]==0`, at `0DE6`. Owned
      `0F79` calls it at `0FD2` and,
      when `[7D79]==0`, at `105A`.
      Each call pushes a count, `1`,
      a zero-extended byte, and `CS`.
      `0D53` passes count `0x0E` and
      `[89F1]`. `0F79` passes count
      `0x14` and `[BP-2]`. The body
      allocates `0x14` bytes, calls
      owned `E661:0006` with
      `(SS:buffer, word[BP+6]-1)`,
      calls owned `B1B1:0026` with
      `([BP+8], [BP+0xA])`, calls
      `B1B1:0036` with `0x2D` (that
      entry is inside the owned
      `B1B1:0026` range), then calls
      owned `B1B1:005B` with
      `SS:buffer`. `DS` and the
      caller bytes are
      **UNDETERMINED**. Next reached
      head is `B77C:20EA` (file
      `0x398AA`), called from owned
      `B3FD:0DB4`.
      2026-09-22: `B77C:20EA` is owned.
      File `0x398AA`, 20-bit `0xB98AA`,
      24-bit `0x0B98AA` under second
      PGR slot 46 word `0x002E` at
      `0x7AD10` (XA=1). The body
      `[0x398AA, 0x398BB)` is the
      whole gap between owned
      `B77C:20C5` at `0x39885` and
      the owned range at `0x398BB`,
      through the one `RETF` at
      `20FA`. Owned `0D53`, `0EE9`,
      and `0F79` each `CALLF` it
      (files `0x34D84`, `0x34EDE`,
      `0x3500C`, bytes `9aea207cb7`).
      It pushes `CS` and calls owned
      `B77C:20C5`, then calls owned
      `B1B1:005B` with `DS:32CF`.
      `DS` is **UNDETERMINED**.
      `B77C:1F26` and `E617:0004`
      stay unowned. Next reached
      head is `E605:000E` (file
      `0x6605E`), called from owned
      `B3FD:0F91`.
      2026-09-22: `E605:000E` is owned.
      File `0x6605E`, 20-bit `0xE605E`,
      24-bit `0x0E605E` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). The body
      `[0x6605E, 0x66095)` is the
      whole gap in front of the
      owned range at `0x66095`,
      through the one `RETF` at
      `0044`. Owned `0F79` calls it
      at `0F91` (file `0x34F61`) and
      stores the returned `AX` at
      `[BP-4]`. It takes no stack
      arguments. `[BP-1]` starts at
      `1`. While that byte is unsigned
      below `0x63` (`72` at `003C`,
      file `0x6608C`) it does
      `MOV AL,[BP-1]` then `PUSH AX`
      and calls `E1A6:0007` at file
      `0x61A67` (20-bit `0xE1A67`),
      inside the owned range that
      starts at `0x61A62`. Only `AL`
      is replaced before the next
      push, so `AH` on later passes
      is the previous return. It then loads
      `LES BX,[8E22]` and compares
      `[BP-1]` with `ES:[BX] & 0x7F`.
      A byte still below that masked
      value is returned, zero-extended.
      Otherwise the byte is
      incremented. The value `0x63`
      is returned without being
      passed to `E1A6:0007`.
      `[8E22]` and `ES:[BX]` are
      **UNDETERMINED**. `E617:0004`
      stays unowned. Next reached
      head is `B77C:1F26` (file
      `0x396E6`), called from owned
      `B3FD:1004`.
      2026-09-22: `B77C:1F26` is owned.
      File `0x396E6`, 20-bit `0xB96E6`,
      24-bit `0x0B96E6` under second
      PGR slot 46 word `0x002E` at
      `0x7AD10` (XA=1). The body
      `[0x396E6, 0x39725)` is a
      mid-gap island of
      `[0x37336, 0x39885)`, through
      the one `RETF` at `1F64`. The
      prefix `0x37336` and the byte
      after the `RETF` (`0x39725`,
      `B77C:1F65`) stay unowned.
      Owned `0F79` calls it at
      `1004` and, when `[7D79]==1`,
      at `1069` (files `0x34FD4` and
      `0x35039`). Both push `0x14`,
      `2`, and `[BP-4]`. The body
      allocates `0x14` bytes, calls
      owned `E4D6:000D` with
      `(SS:buffer, 0xFFFF, [BP+6])`,
      calls owned `B1B1:0026` with
      `([BP+8], [BP+0xA])`, calls
      `B1B1:0036` with `0x2D` inside
      the owned `B1B1:0026` range,
      then calls owned `B1B1:005B`
      with `SS:buffer`. `[BP+6]` and
      the buffer are
      **UNDETERMINED**. `B77C:1F65`
      has no owned caller. Next
      reached head is `E617:0004`
      (file `0x66174`), called from
      owned `B3FD:10A6`.
      2026-09-22: `E617:0004` is owned.
      File `0x66174`, 20-bit `0xE6174`,
      24-bit `0x0E6174` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned `0F79`
      calls it at `10A6` (file
      `0x35076`) with
      `([BP-2]-1, [BP-4])` and stores
      `AX` at `[BP-6]`. Body
      `[0x66174, 0x66447)` is a
      prefix of the gap, 723 bytes,
      six `RETF`s, through the one
      at `02D6`. `[BP+6]` is passed
      to owned `E609:0005`. If that
      `AX` is above `0x03E7` the
      `RETF` returns `0xFFF3`. It
      then calls unowned `035A` with
      `(CS, [BP+6], [BP+8])` and
      returns that `AX` when it is
      not zero. Owned `E21A:000B`
      returns `DX:AX`. Unowned
      `E655:0004` is called with
      `[BP+6]`. If `E655`'s `DX`
      and `AX` are both zero
      (`OR AX,[BP-6]` at `0055`,
      file `0x661C5`; `75` not
      taken at `0058`, file
      `0x661C8`) the `RETF`
      returns `0xFFF2`. If the
      `E21A` `DX:AX` pair, `DX`
      compared first, is below the
      `E655` pair, the `RETF`
      returns `0xFFFD`. The
      continuing path increments
      `[9757]`, calls unowned
      `E692:0000`, and saves `AX` at
      `[BP-2]`. A non-zero `AX`
      decrements `[9757]` and
      returns that `AX`. The long
      path calls unowned       `02D7` and
      `03AE`, decrements `[9757]`
      once, and the final `RETF`
      returns `[BP-2]`. `[BP+6]`,
      `[BP+8]`, and `[9757]` are
      **UNDETERMINED**. `035A`,
      `E655:0004`, `E692:0000`, and
      `03AE` stay unowned. Next
      reached head is `E617:02D7`
      (file `0x66447`), called from
      `014E`.
      2026-09-22: `E617:02D7` is owned.
      File `0x66447`, 20-bit `0xE6447`,
      24-bit `0x0E6447` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned `0004`
      calls it at `014E` (file
      `0x662BE`) after pushing `SI`
      and `CS`; the `RETF` pops that
      `CS`. Body
      `[0x66447, 0x664C6)`, 127
      bytes. `SI` is `[BP+6]`. It
      saves `DS` and sets
      `[BP-4]` to `E75F`, then
      loops at `02EA`. Each pass
      calls owned `D8BC:001C` with
      `(3, DS:E75E, 0x0640)`. It
      masks `[E75E]` with `0xF8`.
      Value `0xF8` returns `SI`.
      Value `0xA8` increments `SI`,
      calls owned `D9EA:0042` with
      the old `SI`, and stores `AX`
      at the saved `DS:E75F`. Values
      `0xB8` and `0x88` skip that
      store. Any other value reads
      `[E75F]`, indexes `[BX+8E70]`,
      and writes that byte back to
      `[E75F]`. Every pass that does
      not return calls owned
      `D8F8:0000` with
      `(1, DS:E75E, DI)` and jumps
      back to `02EA`. `DI` is the
      `AX` from `D8BC:001C`.
      `[E75E]`, `[E75F]`, and
      `[8E70]` are **UNDETERMINED**.
      The four bytes at `0x664C6`
      have no owned caller. Next
      reached head is `E617:035A`
      (file `0x664CA`), called from
      owned `E617:002A`.
      2026-09-22: `E617:035A` is owned.
      File `0x664CA`, 20-bit `0xE64CA`,
      24-bit `0x0E64CA` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned `0004`
      calls it at `002A` (file
      `0x6619A`) after pushing
      `[BP+8]`, `DI`, and `CS`. The
      `RETF` pops that `CS`, and
      `ADD SP,4` drops the two
      words. Body
      `[0x664CA, 0x6651E)`, 84
      bytes, three `RETF`s. `SI` is
      the low 16 bits of
      `[BP+6] * 0x01F4`. `DI` is
      `[BP+8]`. While
      `[SI+A99D]` is not zero it
      reads `[SI+A99C]`, adds `2`
      to `SI` (`83 C6 02` at `037A`,
      file `0x664EA`), then calls
      `E1A6:0007` at file `0x61A67`
      with that byte. `E1A6` returning
      `0xFFFF` makes this `RETF`
      return `0xFFEF`. A byte equal
      to `DI` makes it return
      `0xFFF0`. A zero byte at
      `[SI+A99D]` makes it return
      `0`. `[A99C]`, `[A99D]`, and
      the caller words are
      **UNDETERMINED**. The four
      bytes at `0x664C6` stay
      unowned. Next reached head is
      `E617:03AE` (file `0x6651E`),
      called from owned
      `E617:0278`.
      2026-09-22: `E617:03AE` is owned.
      File `0x6651E`, 20-bit `0xE651E`,
      24-bit `0x0E651E` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned `0004`
      calls it at `0278` (file
      `0x663E8`) after pushing `DI`
      and `CS`. The `RETF` pops
      that `CS`, and `ADD SP,2`
      drops `DI`. `DI` is the word
      `0004` loaded from `[BP+6]`
      at its entry. Body
      `[0x6651E, 0x66554)`, 54
      bytes, one `RETF` at `03E3`.
      The index is the low 16 bits
      of that word times `5`. It
      copies `[index+A7BC]` through
      `[index+A7C0]` to `[8C80]`
      through `[8C84]`. `[A7BC]`
      and those stores are
      **UNDETERMINED**. The four
      bytes at `0x664C6` and
      `E692:0000` stay unowned.
      Next reached head is
      `E655:0004` (file `0x66554`),
      called from owned
      `E617:0047`.
      2026-09-22: `E655:0004` is owned.
      File `0x66554`, 20-bit `0xE6554`,
      24-bit `0x0E6554` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). The body
      `[0x66554, 0x66616)` is the
      whole gap in front of owned
      `E661:0006`, 194 bytes, two
      `RETF`s. Owned `E617:0004`
      calls it at `0047` (file
      `0x661B7`) with `DI`, which
      is that routine's `[BP+6]`,
      and stores the returned
      `DX:AX` at `[BP-6]:[BP-8]`.
      The index is the low 16 bits
      of `DI * 0x01F4`. If
      `[index+A99D]` is zero the
      `RETF` returns `DX:AX = 0`.
      Otherwise a byte counter runs
      from `0` while it is below
      `0xF9`. Each pass uses
      `index + counter*2`. A zero
      `[SI+A99D]` ends the loop.
      Otherwise it calls owned
      `E6D1:0001` with
      `[SI+A99C]`, then owned
      `F800:20C4` with `DX:AX`
      equal to the zero-extended
      `[SI+A99D]` byte and `BX:CX`
      holding `E6D1`'s `AX:DX`. It
      adds that `F800` `DX:AX` into
      one dword and the
      zero-extended `[SI+A99D]`
      byte into another. After the
      loop it calls `F800:20C4`
      again with `DX:AX = 0x0151`,
      `BX` the low word and `CX`
      the high word of the second
      dword, adds `0xFFFFFEAF` to
      that return, subtracts the
      result from the first dword,
      and returns that dword in
      `DX:AX`. What
      `F800:20C4` computes is
      **UNDETERMINED**. `[A99C]`
      and `[A99D]` are
      **UNDETERMINED**. The four
      bytes at `0x664C6` stay
      unowned. Next reached head is
      `E692:0000` (file `0x66920`),
      called from owned
      `E617:008C`.
      2026-09-22: `E692:0000` is owned.
      File `0x66920`, 20-bit `0xE6920`,
      24-bit `0x0E6920` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned
      `E617:0004` calls it at `008C`
      (file `0x661FC`) with
      `(DI, [BP+8])` and stores `AX`
      at `[BP-2]`. `DI` is that
      routine's `[BP+6]`. Body
      `[0x66920, 0x66A9D)` is a
      prefix of the gap, 381 bytes,
      three `RETF`s. `SI` is
      `[BP+6]`. The index is the
      low 16 bits of `SI * 0x01F4`.
      If `[index+A99D]` is zero the
      `RETF` returns `0xFFF2`. It
      calls owned `DF4F:0009` with
      `DS:9208` and owned
      `E1A6:0007` with `[BP+8]`. A
      zero `E1A6` result also calls
      owned `E12D:0009` with
      `[BP+8]`. It then calls owned
      `E07A:0004` with
      `([BP+8], [index+A99C])` and
      returns that `AX` when it is
      not zero. The continuing path
      adds `0x0151` to a copy of the
      dword at `[920A]` and keeps
      the sum at `[BP-0xA]`
      (`ADD DX,0x0151` at `008B`,
      file `0x669AB`). `[920A]` is
      not written. It uses the byte at
      the original far pointer plus
      `0x150` as a sign-extended
      count, and at each step copies
      the next byte over a byte that
      is not `0xFF`, advancing the
      offset by `0x18`. It calls owned
      `E291:0002` with `DS:9208`,
      then fills `0x32` local words
      with the `[A99C]` byte in
      both halves. While `SI` is
      below `0x64`, bit 1 of
      `[SI+8ED4]` selects a call to
      unowned `E7D5:0001`. The final
      `RETF` returns `0` after two
      more `DF4F:0009` calls, with
      `DS:8E2E` and `DS:9208`.
      `[A99C]`, `[A99D]`, `[920A]`,
      and `[8ED4]` are
      **UNDETERMINED**. The byte
      after the `RETF` (file
      `0x66A9D`) has no owned
      caller. Next reached head is
      `E7D5:0001` (file `0x67D51`),
      called from `011B`.
      2026-09-22: `E7D5:0001` is owned.
      File `0x67D51`, 20-bit `0xE7D51`,
      24-bit `0x0E7D51` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned
      `E692:0000` calls it at `011B`
      (file `0x66A3B`) with
      `(SI, [BP-2])` and compares
      the returned `AX` with `-5`.
      `[BP-2]` is the zero-extended
      `[A99C]` byte. Body
      `[0x67D51, 0x67DB9)`, 104
      bytes, three `RETF`s. It calls
      owned `E1A6:0007` with
      `[BP+6]`. A non-zero result is
      returned immediately. Otherwise
      it adds `0x0151` to a copy of
      the dword at `[8E22]` and
      keeps the sum at `[BP-6]`
      (`ADD DX,0x0151` at `0028`,
      file `0x67D78`). `[8E22]` is
      not written. It uses the
      sign-extended byte at the
      original far pointer plus
      `0x150` as a count. Each step
      compares the byte at the
      adjusted pointer with `SI`. A match
      returns the next byte,
      zero-extended. Otherwise the
      offset advances by `0x18`. If
      the count expires the `RETF`
      returns `0xFFFB`. `[8E22]`
      and `[A99C]` are
      **UNDETERMINED**. The byte
      after the `RETF` (file
      `0x67DB9`) has no owned
      caller. `C887:09AC` stays
      unowned. `B13A:0000` stays
      unentered. Next reached head
      is `B77C:202D` (file
      `0x397ED`), called from owned
      `BE1A:003F`.
      2026-09-22: `B77C:202D` is owned.
      File `0x397ED`, 20-bit `0xB97ED`,
      24-bit `0x0B97ED` under second
      PGR slot 46 word `0x002E` at
      `0x7AD10` (XA=1). Owned
      `BE1A:0002` calls it at `003F`
      (file `0x3E1DF`) with the
      sign-extended byte at `[D6AD]`,
      then `1`, `7`, and `0x10`.
      Body `[0x397ED, 0x3981B)`, 46
      bytes, one `RETF` at `205A`.
      `SI` is `[BP+6]` and `DI` is
      `[BP+8]`. It calls unowned
      `B77C:1FDB` with `(SI, DI, 7)`
      and unowned `B77C:1F65` with
      `(SI, DI, 0x0B, 0x10)`. The
      returned `AX` is whatever
      `1F65` left. This is the
      Assign 16 Levels caller. The
      16-level meaning stays
      unnamed. `[D6AD]` is the
      selected note already recorded
      for this screen. The byte
      after the `RETF` (file
      `0x3981B`, `B77C:205B`) has a
      separate owned caller and
      stays unowned. `1FDB` stays
      unowned; its `CALLF
      D9F2:003D` stays unseeded.
      Next reached head is
      `B77C:1F65` (file `0x39725`),
      called from `2051`.
      2026-09-22: `B77C:1F65` is owned.
      File `0x39725`, 20-bit `0xB9725`,
      24-bit `0x0B9725` under second
      PGR slot 46 word `0x002E` at
      `0x7AD10` (XA=1). Owned
      `B77C:202D` calls it at `2051`
      (file `0x39811`) with
      `(SI, DI, 0x0B, 0x10)`. Body
      `[0x39725, 0x3979B)`, 118
      bytes, one `RETF` at `1FDA`.
      `DI` is `[BP+8]`. `SI` is
      `[BP+0C]`, and a value above
      `0x14` becomes `0x14`. It
      calls unowned `D0C0:10B6`
      with `(SS:[BP-0x16], [BP+6])`
      and stores `AX` at `[BP-2]`.
      Then owned `B1B1:0026` with
      `(DI, [BP+0A])`, owned
      `B1B1:0097` with `(0x20, 0x11)`,
      and `B1B1:0026` again with the
      same pair. When `[BP-2]` is 0
      and `SI` is above 0, it calls
      `B1B1:0036` with `0x2D`, stores
      0 at `[BP+SI-0x16]`, and calls
      owned `B1B1:005B` with
      `SS:[BP-0x16]`. The frame is
      `0x16` bytes. What `D0C0:10B6`
      returns, and the 16-level
      meaning, stay **UNDETERMINED**.
      `D0C0:10B6` (file `0x51CB6`)
      stays unowned. Next reached
      head is `B77C:1FDB` (file
      `0x3979B`), called from
      `202D` at `203E`. Its `CALLF
      D9F2:003D` stays unseeded.
      2026-09-22: `B77C:1FDB` stays
      unseeded. The pad note at file
      `0x397B3` is the third `CALLF
      D9F2:003D`, inside body
      `[0x3979B, 0x397ED)`.
      `B77C:205B` is owned. File
      `0x3981B`, 20-bit `0xB981B`,
      24-bit `0x0B981B` under second
      PGR slot 46 word `0x002E` at
      `0x7AD10` (XA=1). Owned
      `CEBF:0008` calls it at `008D`
      (file `0x4EC7D`) with the
      sign-extended byte at `[8C8C]`,
      then the sign-extended byte
      held in `[BP-4]`, then `1`,
      then `8`. `[BP-4]` is `[9970]`,
      or `[8C87]` when `[974C]` is 0
      and `[9970]` is not 0. Those
      RAM names are **UNDETERMINED**.
      Body `[0x3981B, 0x39885)`, 106
      bytes, one `RETF` at `20C4`.
      This span is the entire gap in
      front of owned `B77C:20C5` at
      `0x39885`. `SI` is `[BP+6]`.
      If `[BP+8]` is 0, it copies 8
      words and 1 byte from `DS:3571`
      to `DS:[BP-0x16]` (`PUSH DS` /
      `POP ES`). Otherwise it
      calls unowned `E72C:00A1` with
      `(SI, [BP+8])`, stores `AX` at
      `[BP-2]`. `LEA AX,[BP-0x16]`
      (file `0x3984B`) then
      `MOV AL,[BP-2]` and `PUSH AX`
      (file `0x39852`), so the word
      passed to `E4D6:000D` keeps
      `AH` from that `LEA`. The other
      pushes are `SI` and
      `SS:[BP-0x16]`. Both arms
      then call owned `B1B1:0026`
      with `([BP+0A], [BP+0C])`,
      `B1B1:0036` with `0x2D` (file
      `0x31B46` inside owned
      `[0x31B36, 0x31B6B)`), and owned
      `B1B1:005B` (file `0x31B6B`)
      with `SS:[BP-0x16]`. The frame
      is `0x16` bytes. `DS:3571` is
      **UNDETERMINED**. The 16-level
      meaning stays unnamed.
      `D0C0:10B6` (file `0x51CB6`)
      stays unowned. Next reached
      head is `E72C:00A1` (file
      `0x67361`), called from `205B`
      at `207F`.
      2026-09-22: `E72C:00A1` is owned.
      File `0x67361`, 20-bit `0xE7361`,
      24-bit `0x0E7361` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned
      `B77C:205B` calls it at `207F`
      (file `0x3983F`) with
      `(SI, [BP+8])`. Body
      `[0x67361, 0x67399)`, 56 bytes,
      one `RETF` at `00D8`. This span
      is a mid-gap island in
      `[0x672C6, 0x6769C)`. `DI` is
      `[BP+6]` and `SI` is `[BP+8]`.
      It pushes `SI`, `DI`, and `CS`,
      then `CALLN` unowned
      `E72C:0006`, and adds 4 to `SP`.
      If the returned `AX` is signed
      `>= 0`, that `AX` is returned.
      Otherwise it returns `SI` unless
      the sign-extended byte at
      `[8C8C]` equals `DI` and the
      byte at `[9208]` is not signed
      below 0, in which case it
      returns the sign-extended byte
      at `[SI+924A]`. `[8C8C]`,
      `[9208]`, and `[SI+924A]` are
      **UNDETERMINED**. The byte
      after the `RETF` (file
      `0x67399`) has no owned caller.
      Far calls at `0x3D34E` and
      `0x64A02` target that file as
      `E739:0009`, and both sites are
      in gaps. `B77C:1FDB` stays
      unseeded. Next reached head is
      `E72C:0006` (file `0x672C6`),
      called from `00AF`.
      2026-09-22: `E72C:0006` is owned.
      File `0x672C6`, 20-bit `0xE72C6`,
      24-bit `0x0E72C6` under second
      PGR slot 57 word `0x0039` at
      `0x7AD26` (XA=1). Owned
      `E72C:00A1` reaches it at `00AF`
      (file `0x6736F`) by `PUSH CS` /
      `CALLN`. The callee `RETF`s, so
      `[BP+6]` is `00A1`'s `DI` and
      `[BP+8]` is `00A1`'s `SI`. Body
      `[0x672C6, 0x67361)`, 155 bytes,
      six `RETF`s, the whole gap in
      front of owned `00A1`. The
      frame is 6 bytes. `DX` is
      `[BP+6]` and `SI` is `[BP+8]`.
      When the sign-extended byte at
      `[8C8C]` equals `DX` and the
      byte at `[9208]` is not signed
      below 0, `SI` becomes the
      sign-extended byte at
      `[SI+924A]`. Bit 1 of
      `[SI+92AE]` set returns that
      value; clear returns `0xFFFB`.
      Otherwise it calls owned
      `E1A6:0007` (file `0x61A67`,
      inside `[0x61A62, 0x61F0C)`)
      with `[BP+6]` and returns a
      non-zero `AX`.       A zero result adds `0x0151` to a
      copy of the dword at `[8E22]`
      (`8B 16 22 8E` / `81 C2 51 01` /
      `15 00 00` at file `0x6730F`) and
      keeps the sum in the frame
      (`[BP-6]` low, `[BP-4]` high).
      `[8E22]` is not written. The
      count is the sign-extended byte
      at the original far pointer plus
      `0x150`. Each step
      compares the zero-extended
      byte at the adjusted pointer
      plus 1 with `SI`. A match with
      bit 1 of the byte at plus 2
      set returns the byte at the
      pointer, zero-extended. A match
      with that bit clear returns
      `0xFFFB`. Otherwise the offset
      advances by `0x18`. If the
      count expires the `RETF`
      returns `0xFFFB`. `[8C8C]`,
      `[9208]`, `[SI+924A]`,
      `[SI+92AE]`, and `[8E22]` are
      **UNDETERMINED**. Far calls at
      `0x63EF8` and `0x64264` also
      target `0006`; both sites are
      in gaps. `E739:0009` (file
      `0x67399`, 20-bit `0xE7399`,
      24-bit `0x0E7399`, same PGR
      slot) is one `RETF` body
      `[0x67399, 0x67620)` with no
      `BRKXA`, but its far callers
      at `0x3D34E` and `0x64A02` are
      in gaps, so it stays unowned.
      `B77C:1FDB` stays unseeded.
      `D0C0:10B6` (file `0x51CB6`)
      stays unowned. That is the
      next reached head.
      2026-09-22: `D0C0:10B6` is owned.
      File `0x51CB6`, 20-bit `0xD1CB6`,
      24-bit `0x0D1CB6` under second
      PGR slot 52 word `0x0034` at
      `0x7AD1C` (XA=1). Owned
      `B77C:1F65` calls it at `1F83`
      (file `0x39743`) with `SS`, the
      offset of `SS:[BP-0x16]`, and
      `[BP+6]`. Body
      `[0x51CB6, 0x51CEF)`, 57 bytes,
      one `RETF` at `10EE`. This span
      is the suffix of gap
      `[0x51C1D, 0x51CEF)` and meets
      owned code at `0x51CEF`. `BX` is
      `[BP+6]`. `DX` starts at
      `0xFFFF`. A signed compare keeps
      that `DX` when `BX` is signed
      below `0x23` (`7C` at `10C2`,
      file `0x51CC2`) or signed above
      `0x62` (`7F` at `10C7`, file
      `0x51CC7`). Otherwise `AX` is
      `BX*0x18`, `LES BX,[E5F9]` at
      `10D0` (file `0x51CD0`), `ADD
      BX,AX` at `10D4` (file
      `0x51CD4`), and `DX` is the
      zero-extended byte at
      `ES:[BX+FCF6]`. Both arms push
      `[BP+0A]`, `[BP+8]`, `DX`, and
      `CS`, and `CALLN`s unowned
      `D0C0:101D`. `ADD SP,6` drops
      the three words. The `RETF`
      returns `101D`'s `AX`. `[E5F9]`
      is loaded as a far pointer.
      What it points at stays
      **UNDETERMINED**. The `FCF6` byte stays
      **UNDETERMINED**. `B77C:1FDB`
      stays unseeded. Next reached
      head is `D0C0:101D` (file
      `0x51C1D`).
      2026-09-22: `D0C0:101D` is owned.
      File `0x51C1D`, 20-bit `0xD1C1D`,
      24-bit `0x0D1C1D` under second
      PGR slot 52 word `0x0034` at
      `0x7AD1C` (XA=1). Owned
      `D0C0:10B6` calls it at `10E7`
      (file `0x51CE7`) by `PUSH CS` /
      `CALLN`, with `10B6`'s `DX`,
      `[BP+8]`, and `[BP+0A]`. Body
      `[0x51C1D, 0x51CB6)`, 153 bytes,
      one `RETF` at `10B5`. This span
      is the whole gap in front of
      owned `10B6`. The frame is 2
      bytes. `CX` is `[BP+6]`. When
      `CX` is unsigned `>= 0x8000`, or
      the byte at `A2AE:(low 16 of
      CX*0x24+4800)` is 0 (`MOV DX,
      0xA2AE` discards the high half;
      the product fits below `0x71D`),
      it copies
      8 words and 1
      byte from `DS:75D6` to the far
      pointer `[BP+8]` and returns 1.
      Otherwise it scans that record
      for a zero byte (`CX` starts at
      `0xFFFF`). `NOT CX` is the count
      including the zero. `DX` is
      `0x0011`. `73` at `109A` (file
      `0x51C9A`) is `JAE`: a count of
      at most `0x11` copies that many
      bytes to `[BP+8]`, then writes
      `0x11-count` zeros. A count
      above `0x11` copies `0x11` bytes
      and writes no zeros. `[BP-2]`
      is 0 on this path, so the `RETF`
      returns 0. `DS:75D6`
      is **UNDETERMINED** (`DS` is not
      loaded here). The record's
      20-bit base is `0xA72E0` (file
      `0x272E0`). Second PGR slot 41
      word `0x00E9` at `0x7AD06` maps
      that base to 24-bit `0x3A72E0`
      (XA=1). `CX>=0x5E` crosses into
      page 42, slot word `0x00EA` at
      `0x7AD08`. Those record bytes
      stay **UNDETERMINED**. The body
      has no call. No unblocked reached
      gap target remains. The highest
      remaining reached target is
      `C887:09AC` (file `0x4921C`); it
      stays unseeded. `B77C:1FDB` and
      `B13A:0000` stay unseeded.
      2026-09-22: No compare-bounded jump
      slot was seeded. Ledger re-read is
      952 ranges, 377010 owned bytes, 122
      gaps. Every owned `JMP CS:[BX+disp16]`
      (`2E FF A7`) whose index compare is a
      small immediate and whose table words
      sit in an owned range has every
      selected slot already owned. Four
      `C4C8` switches fail because the table
      is the gap. `C4C8:0838` (file
      `0x454B8`, 20-bit `0xC54B8`) is `8B DE`
      (`MOV BX,SI`: opcode `8B`, ModR/M `DE`
      reg `BX` rm `SI`, writes `BX`). `083A`
      (file `0x454BA`) is `83 FB 09` (`CMP
      BX, imm8 +9`: opcode `83`, ModR/M `FB`
      reg `7`, no write). `083D` (file
      `0x454BD`) is `76 03` `JBE`, taken when
      unsigned `<=`, target IP `0842` (the
      `D1 E3` `SHL BX,1`: opcode `D1`, ModR/M
      `E3` reg `4` rm `BX`, implicit count 1,
      writes `BX`). `0844` (file `0x454C4`)
      is `2E FF A7 13 09` (`JMP CS:[BX+0913]`,
      ModR/M `A7` disp16). Index `BX<=9` is
      10 words. Those words are the whole gap
      `[0x45593, 0x455A7)`. `C4C8:148D` (file
      `0x4610D`) is `8B D8` (`MOV BX,AX`,
      ModR/M `D8` reg `BX` rm `AX`, writes
      `BX`). `148F` (file `0x4610F`) is `83
      FB 07` (`CMP BX, imm8 +7`). `1492`
      (file `0x46112`) is `77 3F` `JA`, taken
      when unsigned `>`, target IP `14D3`,
      so the table path is not taken
      (`BX<=7`). The 8 words at file
      `0x464D0` sit in gap
      `[0x46498, 0x467BF)`. `C4C8:153A`
      (file `0x461BA`) is `8B D8` again.
      `153C` (file `0x461BC`) is `83 FB 05`
      (`CMP BX, imm8 +5`). `153F` (file
      `0x461BF`) is `76 03` `JBE`, taken when
      unsigned `<=`, target IP `1544`. The 6
      words at file `0x464C4` are in that
      same gap. `C4C8:17DC` (file `0x4645C`)
      is `8B DA` (`MOV BX,DX`, ModR/M `DA`
      reg `BX` rm `DX`, writes `BX`). `17DE`
      (file `0x4645E`) is `83 EB 75` (`SUB
      BX, imm8 +0x75`: opcode `83`, ModR/M
      `EB` reg `5`, writes `BX`). `17E1`
      (file `0x46461`) is `83 FB 05`. `17E4`
      (file `0x46464`) is `77 26` `JA`, taken
      when unsigned `>`, target IP `180C`,
      so the table path is not taken
      (`BX<=5`). The 6 words at file
      `0x46498` start that gap. `D547:0532`
      (file `0x559A2`) `83 E3 0E` is `AND
      BX, imm8 +0x0E` (ModR/M `E3` reg `4`,
      writes `BX`), not a compare.
      `D547:0557` (file `0x559C7`) `83 E7 0F`
      is `AND DI, imm8 +0x0F` (ModR/M `E7`,
      writes `DI`) then `D1 E7` `SHL DI,1`.
      Not this class. Nothing seeded. D17
      stays open. No next slot body under
      this rule.
      2026-09-22: Four `C4C8` tables are owned
      data. Each compare and `JMP CS:[BX+disp16]`
      is inside an owned code range, and a linear
      decode from that range's start under `C4C8`
      hits the opcodes. Slot targets are not
      seeded. `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay unseeded.
      `[0x45593, 0x455A7)` is `C4C8:0913`, 10
      words, consumer `C4C8:0844` (file
      `0x454C4`). 20-bit `0xC5593`, 24-bit
      `0x0C5593`, second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1). `0838`
      `8B DE` writes `BX` from `SI`. `083A`
      `83 FB 09` compares `BX` with imm8 +9.
      `083D` `76 03` is `JBE`, taken when
      unsigned `<=`, target `0842`, then
      `D1 E3` `SHL BX,1`. Slot `0849` file
      `0x454C9` stays a gap. `0x455A7` was
      already owned code. `[0x46498, 0x464A4)`
      is `C4C8:1818`, 6 words, consumer
      `C4C8:17E8` (file `0x46468`). 20-bit
      `0xC6498`, 24-bit `0x0C6498`, same slot.
      `17DC` `8B DA` writes `BX` from `DX`.
      `17DE` `83 EB 75` subtracts imm8 `0x75`
      from `BX`. `17E1` `83 FB 05` compares
      `BX` with imm8 +5. `17E4` `77 26` is
      `JA`, taken when unsigned `>`, target
      `180C`, so the table path is `BX<=5`.
      Slot `1806` file `0x46486` stays a gap.
      `0x464A4` stays a gap. `[0x464C4, 0x464D0)`
      is `C4C8:1844`, 6 words, consumer
      `C4C8:1546` (file `0x461C6`). 20-bit
      `0xC64C4`, 24-bit `0x0C64C4`. `153A`
      `8B D8` writes `BX` from `AX`. `153C`
      `83 FB 05` compares `BX` with imm8 +5.
      `153F` `76 03` is `JBE`, taken when
      unsigned `<=`, target `1544`. Slot
      `154B` file `0x461CB` stays a gap.
      The next file `0x464D0` is the next
      table. `[0x464D0, 0x464E0)` is
      `C4C8:1850`, 8 words, consumer
      `C4C8:1496` (file `0x46116`). 20-bit
      `0xC64D0`, 24-bit `0x0C64D0`. `148D`
      `8B D8` writes `BX` from `AX`. `148F`
      `83 FB 07` compares `BX` with imm8 +7.
      `1492` `77 3F` is `JA`, taken when
      unsigned `>`, target `14D3`, so the
      table path is `BX<=7`. Slot `149B`
      file `0x4611B` stays a gap. `0x464E0`
      stays a gap. Ledger is 956 ranges,
      377070 owned bytes, 122 gaps. D17
      stays open.
      2026-09-22: `C4C8:08CF` is the only
      slot whose `follow_local` is one
      contiguous body through `RETF`,
      missing 0, with no `0F E0`/`0F F0`.
      File `0x4554F`, `C4C8:08CF`, 20-bit
      `0xC554F`, 24-bit `0x0C554F`, second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Consumer
      `C4C8:0844` (file `0x454C4`) is
      `2E FF A7 13 09`. `0838` `8B DE`
      writes `BX` from `SI`. `083A`
      `83 FB 09` compares `BX` with imm8
      +9 and writes nothing. `083D` `76 03`
      is `JBE`, taken when unsigned `<=`,
      target `0842` `D1 E3` `SHL BX,1`.
      Word 9 at file `0x455A5` is `08CF`.
      Bytes `BE 0F 00 EB 00` are
      `MOV SI,0x000F` and `JMPS 08D4`.
      The walk meets owned `08D4` and
      `RETF` at `0912` (file `0x45592`).
      Seed is `[0x4554F, 0x45554)`.
      `C4C8:17E8` `8B DA` writes `BX` from
      `DX`; `83 EB 75` subtracts imm8
      `0x75`; `83 FB 05` compares imm8 +5;
      `77 26` `JA` is taken when unsigned
      `>`, target `180C`, so the table
      path is `BX<=5`. `C4C8:1546`
      `8B D8` writes `BX` from `AX`;
      `83 FB 05` compares imm8 +5; `76 03`
      `JBE` is taken when unsigned `<=`,
      target `1544`. `C4C8:1496` `8B D8`
      writes `BX` from `AX`; `83 FB 07`
      compares imm8 +7; `77 3F` `JA` is
      taken when unsigned `>`, target
      `14D3`, so the table path is
      `BX<=7`. Those twenty-three other
      slot targets are two-or-more runs
      and stay unseeded. Slot file
      `0x454C9`, byte `0x464A4`, slot file
      `0x461CB`, and byte `0x464E0` stay
      gaps. `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 957 ranges,
      377075 owned bytes, 122 gaps. D17
      stays open.
      2026-09-23: `C4C8:0849` is the smallest
      of the twenty-three gap slots. Its
      `follow_local` is two runs. The first
      is contiguous, missing 0, and has no
      `0F E0`/`0F F0`. File `0x454C9`,
      `C4C8:0849`, 20-bit `0xC54C9`, 24-bit
      `0x0C54C9`, second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1). Word 0
      at file `0x45593` is `0849`. `BE 10 00`
      is `MOV SI, imm16 0x0010` (opcode
      `B8+6`, writes `SI`). `E9 85 00` is
      a near `JMP`, disp16 `+0x0085`
      (positive), writes nothing, target IP
      `08D4`. That target is owned code at
      file `0x45554`. Seed is
      `[0x454C9, 0x454CF)`. The later run
      is owned `08D4` through `RETF` at
      `0912`. Byte `0x454CF` stays a gap.
      The other twenty-two slots stay
      unseeded. `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 958 ranges,
      377081 owned bytes, 122 gaps. D17
      stays open.
      2026-09-23: `C4C8:17F6` is the
      smallest remaining entry run that
      is still a gap. `C4C8:17FE` is
      also eight bytes and stays
      unseeded. File `0x46476`,
      `C4C8:17F6`, 20-bit `0xC6476`,
      24-bit `0x0C6476`, second PGR slot
      49 word `0x0031` at `0x7AD16`
      (XA=1). Word 4 at file `0x464A0`
      is `17F6`. Consumer `C4C8:17E8`
      (file `0x46468`) is
      `2E FF A7 18 18`. `0E` is
      `PUSH CS` and writes no GPR.
      `E8 AF FA` is a near `CALL`,
      disp16 `-0x0551`, writes nothing,
      target IP `12A9`. `8B D0` is
      `MOV DX, AX` (ModR/M `D0`, reg
      `DX`, rm `AX`, writes `DX`).
      `EB 0E` is `JMPS`, rel8 `+14`,
      writes nothing, target IP `180C`.
      That target is owned code at file
      `0x4648C`. Seed is
      `[0x46476, 0x4647E)`. At `180C`,
      a nonzero `DX` returns that `DX`
      (`75` at `180E`, file `0x4648E`,
      `RETF` at `1817`). A zero `DX`
      jumps to `12B5`. Bytes `0x4646D`
      and `0x4647E` stay gaps. The
      other twenty-one slots stay
      unseeded. `C887:09AC`,
      `B13A:0000`, `B77C:1FDB`, and
      `D52A:0318` stay unseeded. Ledger
      is 959 ranges, 377089 owned
      bytes, 123 gaps. D17 stays open.
      2026-09-23: `C4C8:17FE` is the
      eight-byte `1818` slot `BX==5`.
      Its first run is contiguous, has
      no `0x00`, and has no `0F E0` /
      `0F F0`. File `0x4647E`,
      `C4C8:17FE`, 20-bit `0xC647E`,
      24-bit `0x0C647E`, second PGR
      slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Word 5 at file
      `0x464A2` is `17FE`. `0E` is
      `PUSH CS` and writes no GPR.
      `E8 A7 FA` is a near `CALL`,
      disp16 `-0x0559`, writes nothing,
      target IP `12A9`. That callee is
      already owned at file `0x45F29`
      and is not entered. `8B D0` is
      `MOV DX, AX` (ModR/M `D0`, reg
      `DX`, rm `AX`, writes `DX`).
      `EB 06` is `JMPS`, rel8 `+6`,
      writes nothing, target IP `180C`.
      That target is owned code at file
      `0x4648C`. Seed is
      `[0x4647E, 0x46486)`. At `180C`,
      a nonzero `DX` returns that `DX`
      (`75` at `180E`, file `0x4648E`,
      `RETF` at `1817`). A zero `DX`
      jumps to `12B5`. Byte `0x46486`
      stays a gap. The other twenty
      slots stay unseeded. `C887:09AC`,
      `B13A:0000`, `B77C:1FDB`, and
      `D52A:0318` stay unseeded. Ledger
      is 960 ranges, 377097 owned
      bytes, 123 gaps. D17 stays open.
      2026-09-23: `C4C8:14A9` is the shortest
      remaining entry run that is still a
      gap. `C4C8:14B7` is also fourteen
      bytes and stays unseeded. File
      `0x46129`, `C4C8:14A9`, 20-bit
      `0xC6129`, 24-bit `0x0C6129`, second
      PGR slot 49 word `0x0031` at
      `0x7AD16` (XA=1). Words 2 and 3 at
      files `0x464D4` and `0x464D6` are
      `14A9` (`1850` slots `BX==2` and
      `BX==3`). Consumer `C4C8:1496`
      (file `0x46116`) is `2E FF A7 50 18`.
      The first run is contiguous, missing
      0, and has no `0F E0`/`0F F0`. `1E`
      is `PUSH DS` and writes no GPR.
      `68 BA 54` is `PUSH imm16 0x54BA`
      and writes no GPR. `9A 5B 00 B1 B1`
      is `CALLF B1B1:005B`. The `00` is
      the high byte of IP `0x005B`. That
      callee is already owned at file
      `0x31B6B` and is not entered. `83 C4
      04` is `ADD SP, imm8 +4` (opcode
      `83`, ModR/M `C4` reg `0`, rm `SP`,
      writes `SP`). `EB 1C` is `JMPS`,
      rel8 `+0x1C` (positive), writes
      nothing, target IP `14D3`. That
      target is owned code at file
      `0x46153`. Seed is
      `[0x46129, 0x46137)`. `14D3` leaves
      by `JMPN` at `1533` (file `0x461B3`,
      `E9 92 02`) to owned `17C8` (file
      `0x46448`). `JMPN_RM` at `1546`
      (file `0x461C6`) is the `153A`
      dispatch and is not on this path.
      Bytes `0x4611B` and
      `0x46137` stay gaps. The other
      nineteen slots stay unseeded.
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 961 ranges,
      377111 owned bytes, 124 gaps. D17
      stays open.
      2026-09-23: `C4C8:14B7` is the shortest
      remaining entry run that is still a
      gap. Its first run is contiguous, has
      no uncovered offset, and has no
      `0F E0`/`0F F0`. File `0x46137`,
      `C4C8:14B7`, 20-bit `0xC6137`, 24-bit
      `0x0C6137`, second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1). Words 4
      and 5 at files `0x464D8` and `0x464DA`
      are `14B7` (`1850` slots `BX==4` and
      `BX==5`). Consumer `C4C8:1496`
      (file `0x46116`) is `2E FF A7 50 18`.
      `1E` is `PUSH DS` and writes no GPR.
      `68 BF 54` is `PUSH imm16 0x54BF`
      and writes no GPR. `9A 5B 00 B1 B1`
      is `CALLF B1B1:005B`. The `00` is
      the high byte of IP `0x005B`. That
      callee is already owned at file
      `0x31B6B` and is not entered. `83 C4
      04` is `ADD SP, imm8 +4` (opcode
      `83`, ModR/M `C4` reg `0`, rm `SP`,
      writes `SP`). `EB 0E` is `JMPS`,
      rel8 `+0x0E` (positive), writes
      nothing, from next IP `14C5` to
      `14D3`. That target is owned code at
      file `0x46153`. Seed is
      `[0x46137, 0x46145)`. Bytes `0x4611B`
      and `0x46145` stay gaps. The other
      eighteen slots stay unseeded.
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 962 ranges,
      377125 owned bytes, 124 gaps. D17
      stays open.
      2026-09-23: `C4C8:084F` is the shortest
      remaining first run that is still a
      gap. `C4C8:149B` file `0x4611B` has no
      follow_local run that starts at
      `149B`. The `084F` run is contiguous,
      has no uncovered offset, and has no
      `0F E0`/`0F F0`. File `0x454CF`,
      `C4C8:084F`, 20-bit `0xC54CF`, 24-bit
      `0x0C54CF`, second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1). Word 1
      at file `0x45595` is `084F` (`0913`
      slot `BX==1`). Consumer `C4C8:0844`
      (file `0x454C4`) is `2E FF A7 13 09`.
      `0B FF` is `OR DI, DI` (opcode `0B`,
      ModR/M `FF` reg `DI`, rm `DI`, writes
      `DI`). `74 05` is `JZ` (opcode `74`,
      taken when ZF=1), rel8 `+5`, writes
      nothing, target IP `0858`. `B8 11 00`
      is `MOV AX, imm16 0x0011` (the `00`
      is the high byte) and writes `AX`.
      `EB 03` is `JMPS`, rel8 `+3`, writes
      nothing, target IP `085B`. `B8 02 00`
      is `MOV AX, imm16 0x0002` and writes
      `AX`. `8B F0` is `MOV SI, AX` (opcode
      `8B`, ModR/M `F0` reg `SI`, rm `AX`,
      writes `SI`). `EB 75` is `JMPS`, rel8
      `+0x75` (positive; `75` is the
      displacement), writes nothing, from
      next IP `085F` to `08D4`. That target
      is owned code at file `0x45554`. Seed
      is `[0x454CF, 0x454DF)`. The later
      run is owned `08D4` through `RETF` at
      `0912`. Byte `0x454DF` stays a gap.
      The other seven equal `0913` slots
      stay unseeded. File `0x4611B` stays a
      gap. `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 963 ranges,
      377141 owned bytes, 124 gaps. D17
      stays open.
      2026-09-23: `C4C8:085F` is the shortest
      remaining first run that is still a
      gap. The six later `0913` slots are
      the same length and stay unseeded.
      `C4C8:149B` file `0x4611B` has no
      follow_local run that starts at
      `149B`. The `085F` run is contiguous,
      has no uncovered offset, and has no
      `0F E0`/`0F F0`. File `0x454DF`,
      `C4C8:085F`, 20-bit `0xC54DF`, 24-bit
      `0x0C54DF`, second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1). Word 2
      at file `0x45597` is `085F` (`0913`
      slot `BX==2`). Consumer `C4C8:0844`
      (file `0x454C4`) is `2E FF A7 13 09`.
      `0B FF` is `OR DI, DI` (opcode `0B`,
      ModR/M `FF` reg `DI`, rm `DI`, writes
      `DI`). `74 05` is `JZ` (opcode `74`,
      taken when ZF=1), rel8 `+5`, writes
      nothing, target IP `0868`. `B8 11 00`
      is `MOV AX, imm16 0x0011` (the `00`
      is the high byte) and writes `AX`.
      `EB 03` is `JMPS`, rel8 `+3`, writes
      nothing, target IP `086B`. `B8 03 00`
      is `MOV AX, imm16 0x0003` and writes
      `AX`. `8B F0` is `MOV SI, AX` (opcode
      `8B`, ModR/M `F0` reg `SI`, rm `AX`,
      writes `SI`). `EB 65` is `JMPS`, rel8
      `+0x65` (positive), writes nothing,
      from next IP `086F` to `08D4`. That
      target is owned code at file
      `0x45554`. Seed is
      `[0x454DF, 0x454EF)`. The later run
      is owned `08D4` through `RETF` at
      `0912`. Byte `0x454EF` stays a gap.
      The other six equal `0913` slots stay
      unseeded. File `0x4611B` stays a gap.
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 964 ranges,
      377157 owned bytes, 124 gaps. D17
      stays open.
      2026-09-23: `C4C8:086F` is the shortest
      remaining first run that is still a
      gap. The five later `0913` slots are
      the same length and stay unseeded.
      `C4C8:149B` file `0x4611B` has no
      follow_local run that starts at
      `149B`. The `086F` run is contiguous,
      has no uncovered offset, and has no
      `0F E0`/`0F F0`. File `0x454EF`,
      `C4C8:086F`, 20-bit `0xC54EF`, 24-bit
      `0x0C54EF`, second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1). Word 3
      at file `0x45599` is `086F` (`0913`
      slot `BX==3`). Consumer `C4C8:0844`
      (file `0x454C4`) is `2E FF A7 13 09`.
      `0B FF` is `OR DI, DI` (opcode `0B`,
      ModR/M `FF` reg `DI`, rm `DI`, writes
      `DI`). `74 05` is `JZ` (opcode `74`,
      taken when ZF=1), rel8 `+5`, writes
      nothing, from next IP `0873` to
      `0878`. `B8 12 00` is `MOV AX, imm16
      0x0012` (the `00` is the high byte)
      and writes `AX`. `EB 03` is `JMPS`,
      rel8 `+3`, writes nothing, from next
      IP `0878` to `087B`. `B8 04 00` is
      `MOV AX, imm16 0x0004` and writes
      `AX`. `8B F0` is `MOV SI, AX` (opcode
      `8B`, ModR/M `F0` reg `SI`, rm `AX`,
      writes `SI`). `EB 55` is `JMPS`, rel8
      `+0x55` (positive), writes nothing,
      from next IP `087F` to `08D4`. That
      target is owned code at file
      `0x45554`. Seed is
      `[0x454EF, 0x454FF)`. The later run
      is owned `08D4` through `RETF` at
      `0912`. Byte `0x454FF` stays a gap.
      The other five equal `0913` slots stay
      unseeded. File `0x4611B` stays a gap.
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 965 ranges,
      377173 owned bytes, 124 gaps. D17
      stays open.
      2026-09-23: Five remaining `0913`
      slots match the sixteen-byte
      template `0B FF` / `74 05` / `B8`
      imm16 / `EB 03` / `B8` imm16 /
      `8B F0` / `EB` rel8 to owned `08D4`.
      Each first run is contiguous, has
      no uncovered offset, and has no
      `0F E0`/`0F F0`. Second PGR slot 49
      word `0x0031` at `0x7AD16` (XA=1).
      Consumer `C4C8:0844` (file
      `0x454C4`) is `2E FF A7 13 09`.
      `0B FF` is `OR DI, DI` (opcode
      `0B`, ModR/M `FF` reg `DI`, rm
      `DI`, writes `DI`). `74 05` is
      `JZ` (opcode `74`, taken when
      ZF=1), rel8 `+5`, writes nothing.
      `8B F0` is `MOV SI, AX` (opcode
      `8B`, ModR/M `F0` reg `SI`, rm
      `AX`, writes `SI`). Final `JMPS`
      target is owned `08D4` file
      `0x45554`. `C4C8:087F` file
      `0x454FF`, 20-bit `0xC54FF`, 24-bit
      `0x0C54FF`. Word 4 at file
      `0x4559B` is `087F` (`BX==4`). JZ
      path imm16 `0x0005` (`B8 05 00`);
      other path imm16 `0x0012` (`B8 12
      00`). JZ target IP `0888`. `EB 45`
      from next IP `088F` to `08D4`. Seed
      `[0x454FF, 0x4550F)`. `C4C8:088F`
      file `0x4550F`, 20-bit `0xC550F`,
      24-bit `0x0C550F`. Word 5 at file
      `0x4559D` is `088F` (`BX==5`). JZ
      path imm16 `0x0006` (`B8 06 00`);
      other path imm16 `0x0013` (`B8 13
      00`). JZ target IP `0898`. `EB 35`
      from next IP `089F` to `08D4`. Seed
      `[0x4550F, 0x4551F)`. `C4C8:089F`
      file `0x4551F`, 20-bit `0xC551F`,
      24-bit `0x0C551F`. Word 6 at file
      `0x4559F` is `089F` (`BX==6`). JZ
      path imm16 `0x0007` (`B8 07 00`);
      other path imm16 `0x0013` (`B8 13
      00`). JZ target IP `08A8`. `EB 25`
      from next IP `08AF` to `08D4`. Seed
      `[0x4551F, 0x4552F)`. `C4C8:08AF`
      file `0x4552F`, 20-bit `0xC552F`,
      24-bit `0x0C552F`. Word 7 at file
      `0x455A1` is `08AF` (`BX==7`). JZ
      path imm16 `0x0008` (`B8 08 00`);
      other path imm16 `0x0014` (`B8 14
      00`). JZ target IP `08B8`. `EB 15`
      from next IP `08BF` to `08D4`. Seed
      `[0x4552F, 0x4553F)`. `C4C8:08BF`
      file `0x4553F`, 20-bit `0xC553F`,
      24-bit `0x0C553F`. Word 8 at file
      `0x455A3` is `08BF` (`BX==8`). JZ
      path imm16 `0x0009` (`B8 09 00`);
      other path imm16 `0x0014` (`B8 14
      00`). JZ target IP `08C8`. `EB 05`
      from next IP `08CF` to `08D4`. Seed
      `[0x4553F, 0x4554F)`. The later run
      is owned `08D4` through `RETF` at
      `0912`. `C4C8:149B` file `0x4611B`
      and `C4C8:17ED` stay unseeded.
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 970 ranges,
      377253 owned bytes, 123 gaps. D17
      stays open.
      2026-09-23: PART A re-read the
      sixteen raw bytes of `087F`..`08BF`.
      Each matches the checker and this
      note. `086F` is still
      `0B FF 74 05 B8 12 00 EB 03 B8 04
      00 8B F0 EB 55`. The ten `0913`
      words at `[0x45593, 0x455A7)` are
      all owned. Three remaining `1844`
      slots share one closed store stub
      that `JMPN`s to owned `17C8`. Each
      first run is contiguous, has no
      uncovered offset, and has no
      `0F E0`/`0F F0`. Second PGR slot 49
      word `0x0031` at `0x7AD16` (XA=1).
      Consumer `C4C8:1546` (file
      `0x461C6`) is `2E FF A7 44 18`.
      `8A 46 FF` is `MOV AL, [BP-1]`
      (opcode `8A`, ModR/M `46` reg `AL`,
      rm `[BP]+disp8` `-1`, writes `AL`).
      `98` is `CBW` and writes `AX`. `50`
      is `PUSH AX` and writes `SP`.
      `83 C4 02` is `ADD SP, imm8 +2`
      (opcode `83` `/0`, ModR/M `C4` rm
      `SP`, writes `SP`). `8A 5E` disp8
      writes `BL`. `8E C2` is `MOV ES, DX`
      (opcode `8E`, ModR/M `C2` sreg
      `ES`, rm `DX`, writes `ES`). `93`
      is `XCHG AX, BX` and writes `AX`
      and `BX`. `26 88` stores `AL` to
      `ES:[BX]` or `ES:[BX+disp8]` (writes
      memory). Final `E9` disp16 is
      little-endian and positive; the
      `00` is the high byte, not a hole.
      Target is owned `17C8` file
      `0x46448`. `C4C8:16E4` file
      `0x46364`, 20-bit `0xC6364`, 24-bit
      `0x0C6364`. Word 1 at file
      `0x464C6` is `16E4` (`BX==1`).
      `CALLF CFC6:02D6`. `MOV BL, [BP-2]`
      (`FE` as signed `-2`). `MOV
      ES:[BX], AL`. `E9 CB 00` from next
      IP `16FD` to `17C8`. Seed
      `[0x46364, 0x4637D)`. `C4C8:16FD`
      file `0x4637D`, 20-bit `0xC637D`,
      24-bit `0x0C637D`. Word 2 at file
      `0x464C8` is `16FD` (`BX==2`).
      `CALLF CFC6:033A`. `MOV BL, [BP-4]`
      (`FC` as signed `-4`). `MOV
      ES:[BX+2], AL`. `E9 B1 00` from
      next IP `1717` to `17C8`. Seed
      `[0x4637D, 0x46397)`. `C4C8:1717`
      file `0x46397`, 20-bit `0xC6397`,
      24-bit `0x0C6397`. Word 3 at file
      `0x464CA` is `1717` (`BX==3`).
      `CALLF CFC6:02D6`. `MOV BL, [BP-3]`
      (`FD` as signed `-3`). `MOV
      ES:[BX+1], AL`. `E9 97 00` from
      next IP `1731` to `17C8`. Seed
      `[0x46397, 0x463B1)`. Mid-gap
      island: gap_count 123 to 124.
      `1731` is not this stub. Its
      fall-through reaches `JMP
      CS:[BX+1824]`. `74` at `1745`
      jumps to `17A8`, and `77` at
      `175D` jumps to `179E`. `154B` has no
      follow_local run that starts there.
      `17A8` first run includes owned
      `17C8`. `1806` first run includes
      owned `180C`. `14C5` `EB 00` merges
      into owned `14D3`. `C4C8:149B` file
      `0x4611B` and `C4C8:17ED` stay
      unseeded. `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 973 ranges,
      377330 owned bytes, 124 gaps. D17
      stays open.
      2026-09-23: PART A re-read the
      linear bytes of `16E4` / `16FD` /
      `1717`. Each matches the checker
      and the paragraph above. `8A 46 FF`
      writes `AL` from `[BP-1]`. `98` is
      `CBW` and writes `AX`. `50` writes
      `SP`. `83 C4 02` writes `SP`. `8A
      5E` disp8 writes `BL`. `8E C2`
      writes `ES` from `DX`. `93` writes
      `AX` and `BX`. Final `E9` disp16 is
      little-endian and positive; target
      IP is owned `17C8` file `0x46448`.
      `E9 CB 00` / `E9 B1 00` / `E9 97
      00` from next IPs `16FD` / `1717` /
      `1731`. CFC6 callees `02D6` file
      `0x4FF36` and `033A` file `0x4FF9A`
      were not in those seeds; they were
      already owned `[0x4FAEB, 0x4FFFE)`.
      PART B: 10 non-refused owned-code
      immediates into gaps. First closed
      body in caller-file order is
      `CA9B:0004`. Earlier hits fail
      first-run `JMPN_RM`: `CAC7:0257`
      (2 runs, missing 0, end `JMPN_RM`),
      `B509:0008` (2, 0, `JMPN_RM`),
      `CD75:0002` (2, 0, `JMPN_RM`),
      `B77C:000C` (2, 0, `JMPN_RM`),
      `CC81:0006` (2, 0, `JMPN` to
      unowned `045E`). Next after the
      seed, `BCF9:000C`, is not this
      shape (2 runs, missing 0, end
      `JMPN_RM`). `C6C2:1362` is also a
      closed `RETF` but a different body;
      not seeded. `DE5C:01D6` `CALLF
      C6C2:1362` stays a later hit.
      `C425:01CE` (file `0x4441E`) is `9A
      04 00 9B CA` `CALLF CA9B:0004`.
      The `00` is the IP high byte, not a
      hole. `CA9B:0004` file `0x4A9B4`,
      20-bit `0xCA9B4`, 24-bit
      `0x0CA9B4`. Second PGR slot 50 word
      `0x0032` at `0x7AD18` (XA=1). First
      run is 244 insns, contiguous,
      missing 0, no `0F E0`/`0F F0`, ends
      `RETF` at `029D`. `55` / `8B EC`
      writes `BP` from `SP`. `83 EC 10`
      is `SUB SP, imm8 +0x10` (ModR/M
      `EC` rm `SP`, writes `SP`). `68 6E
      62` is `PUSH` imm16 `0x626E`. `83
      C4 04` is `ADD SP, imm8 +4` (ModR/M
      `C4` writes `SP`). `80 3E 08 92 00`
      is `CMP [9208], imm8 0`; the `00`
      is the immediate, not a hole. `7D
      0D` is `JGE`, taken when `SF=OF`,
      rel8 `+0x0D` from next IP `001D` to
      `002A`. `E8 D6 00` at `01C5` is
      `CALLN` disp16 `0x00D6` positive
      from next IP `01C8` to `029E`; the
      `00` is the high byte. Seed
      `[0x4A9B4, 0x4AC4E)`. Mid-gap
      island in `[0x4A4DE, 0x4C512)`:
      gap_count 124 to 125. `CA9B:029E`
      file `0x4AC4E` stays unowned.
      `C4C8:149B`, `C4C8:17ED`,
      `C4C8:1731`, `C887:09AC`,
      `B13A:0000`, `B77C:1FDB`, and
      `D52A:0318` stay unseeded. Ledger
      is 974 ranges, 377996 owned bytes,
      125 gaps. D17 stays open.
      2026-09-23: PART A re-read the
      linear bytes of `CA9B:0004`. File
      `[0x4A9B4, 0x4AC4E)`, caller
      `C425:01CE` `9A 04 00 9B CA`, `7D
      0D` `JGE` `SF=OF` next IP `001D`
      target `002A`, `E8 D6 00` `CALLN`
      disp16 `+0x00D6` next IP `01C8`
      target `029E`, `8B EC` writes `BP`,
      `83 EC 10` writes `SP`, `83 C4 04`
      writes `SP`, `8B C2` writes `AX`
      from `DX` before `LEAVE`/`RETF`.
      First run missing 0, no `0F E0`/`0F
      F0`. Matches the checker. Seed
      stays. PART B: `DE5C:01D6` (file
      `0x5E796`) is owned `9A 62 13 C2
      C6` `CALLF C6C2:1362` into gap
      `[0x46C2B, 0x4835D)`. `C6C2:1362`
      file `0x47F82`, 20-bit `0xC7F82`,
      24-bit `0x0C7F82`. Second PGR slot
      49 word `0x0031` at `0x7AD16`
      (XA=1). First run is 280 insns,
      contiguous, missing 0, no `0F
      E0`/`0F F0`, ends `RETF` at `15E8`.
      `55` / `8B EC` writes `BP` from
      `SP`. `83 EC 0E` is `SUB SP, imm8
      +0x0E` (ModR/M `EC` rm `SP`, writes
      `SP`). `C7 46 FC 00 00` is `MOV
      [BP-4], imm16 0x0000`; the zeros
      are the immediate, not a hole. `80
      3E 3F 56 00` is `CMP [563F], imm8
      0`. `74 05` is `JZ`, taken when
      `ZF=1`, rel8 `+0x05` from next IP
      `137B` to `1380`. Seed `[0x47F82,
      0x48209)`. Mid-gap island in
      `[0x46C2B, 0x4835D)`: gap_count 125
      to 126. `C6C2:182D` file `0x4844D`
      and `C6C2:1324` file `0x47F44` stay
      unowned. `BCF9:000C` first run is 2
      runs ending `JMPN_RM`; not seeded.
      `CA9B:029E`, `C4C8:149B`,
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 975 ranges,
      378643 owned bytes, 126 gaps. D17
      stays open.
      2026-09-23: PART A re-read the
      linear bytes of `C6C2:1362`. File
      `[0x47F82, 0x48209)`, caller
      `DE5C:01D6` `9A 62 13 C2 C6`, `74
      05` `JZ` `ZF=1` next IP `137B`
      target `1380`, `8B EC` writes `BP`
      from `SP`, `83 EC 0E` writes `SP`,
      `C9` `LEAVE` / `CB` `RETF`. First
      run missing 0, no `0F E0`/`0F F0`.
      Matches the checker. Seed stays.
      PART B: linear decode from
      `C6C2:1362` reaches `13C2` `E8 68
      04` `CALLN` disp16 `+0x0468` next
      IP `13C5` target `182D` file
      `0x47FE2` inside `[0x47F82,
      0x48209)`. `C6C2:182D` file
      `0x4844D`, 20-bit `0xC844D`,
      24-bit `0x0C844D`. Second PGR slot
      50 word `0x0032` at `0x7AD18`
      (XA=1). First run is 41 insns,
      contiguous, missing 0, no `0F
      E0`/`0F F0`, ends `RETF` at `1894`.
      `55` / `8B EC` writes `BP` from
      `SP`. `75 12` is `JNZ`, taken when
      `ZF=0`, rel8 `+0x12` from next IP
      `1839` to `184B`. Exit `5D` writes
      `BP` / `CB` `RETF`; XOR-zero path
      `33 C0` writes `AX` then `5D`/`CB`.
      Seed `[0x4844D, 0x484B5)`. Prefix
      of `[0x4844D, 0x4A458)`: gap_count
      stays 126. `C6C2:1895` file
      `0x484B5`, `D90C:0006` file
      `0x590C6`, and `C6C2:1324` file
      `0x47F44` stay unowned. `1324`
      first run is 1 run, missing 0,
      ends `RETF`; not seeded (182D
      first). `CA9B:029E`, `C4C8:149B`,
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 976 ranges,
      378747 owned bytes, 126 gaps. D17
      stays open.
      2026-09-23: PART A re-read the
      linear bytes of `C6C2:182D`. File
      `[0x4844D, 0x484B5)`, caller
      `C6C2:13C2` `E8 68 04` `CALLN`
      disp16 `+0x0468` next IP `13C5`
      target `182D` file `0x47FE2`
      inside `[0x47F82, 0x48209)`. `75
      12` `JNZ` taken when `ZF=0`, rel8
      `+0x12` from next IP `1839` to
      `184B`. `8B EC` writes `BP` from
      `SP`. Exit `5D` writes `BP` / `CB`
      `RETF`. First run missing 0, no
      `0F E0`/`0F F0`. Range ends at
      `0x484B5` and excludes `0x4921C`.
      Matches the checker. Seed stays.
      PART B: linear decode from
      `C6C2:1362` reaches `13C9` `E8 58
      FF` `CALLN` disp16 `-0x00A8` next
      IP `13CC` target `1324` file
      `0x47FE9` inside `[0x47F82,
      0x48209)`. `C6C2:1324` file
      `0x47F44`, 20-bit `0xC7F44`,
      24-bit `0x0C7F44`. Second PGR
      slot 49 word `0x0031` at
      `0x7AD16` (XA=1). First run is 18
      insns, contiguous, missing 0, no
      `0F E0`/`0F F0`, ends `RETF` at
      `1344`. `57` `PUSH DI`. `BF 5B
      FA` writes `DI` from imm16
      `0xFA5B`. `8A E0` writes `AH`
      from `AL`. No `Jcc`. `E8 8F FF`
      `CALLN` disp16 `-0x0071` next IP
      `1343` target `12D2`. Exit `5F`
      writes `DI` / `CB` `RETF`.
      **PROVEN.** Seed `[0x47F44,
      0x47F65)`. Mid-gap island in
      `[0x46C2B, 0x47F82)`: gap_count
      126 to 127. `C6C2:12D2` file
      `0x47EF2`, leftover `[0x47F65,
      0x47F82)`, `C6C2:1895`, and
      `D90C:0006` stay unowned.
      `CA9B:029E`, `C4C8:149B`,
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 977 ranges,
      378780 owned bytes, 127 gaps. D17
      stays open.
      2026-09-23: PART A re-read the
      linear bytes of `C6C2:1324`. File
      `[0x47F44, 0x47F65)`, RETF at IP
      `1344`. Caller inside owned
      `C6C2:1362` at IP `13C9` file
      `0x47FE9` bytes `E8 58 FF`:
      `CALLN` imm16 `0xFF58` signed
      `-0x00A8`, next IP `13CC`, target
      `1324`. That `CALLN` is hit by a
      linear decode from `1362`. Head
      `57` `PUSH DI`; `BF 5B FA` writes
      `DI` with imm16 `0xFA5B`. No
      `Jcc`. Exit `5F` writes `DI` /
      `CB` `RETF`. 20-bit `0xC7F44`,
      24-bit `0x0C7F44`, slot 49 word
      `0x0031` at `0x7AD16`, XA=1.
      First run missing 0, no `0F
      E0`/`0F F0`. Matches the
      checker. Seed stays.
      PART B: linear decode from
      `C6C2:1324` reaches `1340` `E8 8F
      FF` `CALLN` disp16 `-0x0071` next
      IP `1343` target `12D2` file
      `0x47F60` inside `[0x47F44,
      0x47F65)`. `C6C2:12D2` file
      `0x47EF2`, 20-bit `0xC7EF2`,
      24-bit `0x0C7EF2`. Second PGR
      slot 49 word `0x0031` at
      `0x7AD16` (XA=1). First run is 40
      insns, contiguous, missing 0, no
      `0F E0`/`0F F0`, ends `RETF` at
      `1323`. `A0 A6 85` writes `AL`
      from moffs16 `0x85A6`. `74 0B` is
      `JZ`, taken when `ZF=1`, rel8
      `+0x0B` from next IP `12DA` to
      `12E5`. Exit `83 C4 08` writes
      `SP` from imm8 `+8` / `CB`
      `RETF`. **PROVEN.** Seed
      `[0x47EF2, 0x47F44)`. Suffix of
      `[0x46C2B, 0x47F44)`: leftover
      prefix keeps gap_count 127.
      Adjacent to `1324`; ranges stay
      separate. `C6C2:11EF` file
      `0x47E0F`, leftover `[0x47F65,
      0x47F82)`, `C6C2:1895`, and
      `D90C:0006` stay unowned.
      `CA9B:029E`, `C4C8:149B`,
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318` stay
      unseeded. Ledger is 978 ranges,
      378862 owned bytes, 127 gaps. D17
      stays open.
      2026-09-23: PART A re-read the
      linear bytes of `C6C2:12D2`. File
      `[0x47EF2, 0x47F44)`, RETF at IP
      `1323`. Caller inside owned
      `C6C2:1324` at IP `1340` file
      `0x47F60` bytes `E8 8F FF`:
      `CALLN` imm16 `0xFF8F` signed
      `-0x0071`, next IP `1343`, target
      `12D2`. That `CALLN` is hit by a
      linear decode from `1324`. Head
      `A0 A6 85` writes `AL` from
      moffs16 `0x85A6`. `74 0B` is
      `JZ`, taken when `ZF=1`, rel8
      `+0x0B` from next IP `12DA` to
      `12E5`. Exit `83 C4 08` writes
      `SP` (ModR/M `C4` rm `SP`) from
      imm8 `+8` / `CB` `RETF`. 20-bit
      `0xC7EF2`, 24-bit `0x0C7EF2`,
      slot 49 word `0x0031` at
      `0x7AD16`, XA=1. First run
      missing 0, no `0F E0`/`0F F0`.
      Matches the checker. Seed stays.
      PART B: linear decode from
      `C6C2:12D2` hits `CB` `RETF` at
      IP `12E4` file `0x47F04` before
      any `CALLN`/`CALLF`/`JMP`/`JMPF`
      to `11EF`. `74 0B` `JZ` at
      `12D8` is not taken on that
      walk. CFG first-run `12EE` `E8
      FE FE` `CALLN` disp16 `0xFEFE`
      signed `-0x0102`, next IP
      `12F1`, target `11EF` (file
      `0x47E0F`). The call site file
      `0x47F0E` sits after that
      `RETF`; not a linear hit.
      `follow_local` `C6C2:11EF` file
      `0x47E0F`, 20-bit `0xC7E0F`,
      24-bit `0x0C7E0F`, slot 49 word
      `0x0031` at `0x7AD16` (XA=1): 1
      run, missing 0, ends `RETF` at
      `12D1`. Not seeded. `C6C2:11EF`,
      leftover `[0x47F65, 0x47F82)`,
      `C6C2:1895`, and `D90C:0006`
      stay unowned. `CA9B:029E`,
      `C4C8:149B`, `C887:09AC`,
      `B13A:0000`, `B77C:1FDB`, and
      `D52A:0318` stay unseeded.
      Ledger is 978 ranges, 378862
      owned bytes, 127 gaps. D17
      stays open.
      2026-09-23: PART A:
      `follow_local` from `C6C2:12D2`
      lists IP `12EE`. Re-read file
      `0x47F0E` bytes `E8 FE FE`:
      `CALLN` disp16 `0xFEFE` signed
      `-0x0102`, next IP `12F1`,
      target `11EF`. `74 0B` is `JZ`
      at `12D8`, taken when `ZF=1`,
      rel8 `+0x0B` from next IP
      `12DA` to `12E5`. `12EE` is
      after `12E5` and before range
      end `0x47F44`. A straight-line
      walk that stops at `RETF`
      `12E4` is not the proof. That
      `CALLN` is in
      `follow_local`'s list from
      `12D2`. Head of the caller
      span stays `A0 A6 85` writes
      `AL`. PART B:
      `follow_local` `C6C2:11EF`
      file `0x47E0F`, 20-bit
      `0xC7E0F`, 24-bit `0x0C7E0F`.
      Second PGR slot 49 word
      `0x0031` at `0x7AD16` (XA=1).
      First run is 93 insns,
      contiguous, missing 0, no `0F
      E0`/`0F F0`, ends `RETF` at
      `12D1`. Body `[0x47E0F,
      0x47EF2)`. Head `55` `PUSH
      BP`; `8B EC` writes `BP` from
      `SP` (ModR/M `EC`). `83 EC
      26` writes `SP` from imm8
      `0x26`. `B8 20 00` writes `AX`
      from imm16 `0x0020`; the `00`
      is the high byte, not a hole.
      `74 10` at `123F` is `JZ`,
      taken when `ZF=1`, rel8
      `+0x10` from next IP `1241` to
      `1251`. Exit `83 C4 04` writes
      `SP` (ModR/M `C4` rm `SP`)
      from imm8 `+4` / `5F` writes
      `DI` / `C9` `LEAVE` / `CB`
      `RETF`. **PROVEN.** Suffix of
      `[0x46C2B, 0x47EF2)`: leftover
      prefix `[0x46C2B, 0x47E0F)`
      keeps gap_count 127. Adjacent
      to `12D2`; ranges stay
      separate. Leftover `[0x47F65,
      0x47F82)`, `C6C2:1895`, and
      `D90C:0006` stay unowned.
      `CA9B:029E`, `C4C8:149B`,
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318`
      stay unseeded. Ledger is 979
      ranges, 379089 owned bytes,
      127 gaps. D17 stays open.
      2026-09-23: PART A re-read the
      linear bytes, not the checker.
      `follow_local` from owned
      `C6C2:12D2` lists IP `12EE`.
      File `0x47F0E` bytes `E8 FE
      FE`: `CALLN` disp16 `0xFEFE`
      signed `-0x0102`, next IP
      `12F1`, target `11EF`. `74
      0B` is `JZ` at `12D8`, taken
      when `ZF=1`, rel8 `+0x0B`
      from next IP `12DA` to
      `12E5`. `12EE` is after
      `12E5` and before `0x47F44`.
      First run of `C6C2:11EF` is
      one closed body `[0x47E0F,
      0x47EF2)`, missing 0, no `0F
      E0`/`0F F0`, ends `RETF` at
      `12D1`. Head `55` `PUSH BP`;
      `8B EC` writes `BP` from
      `SP`. Exit `5F` writes `DI` /
      `C9` `LEAVE` / `CB` `RETF`.
      20-bit `0xC7E0F`, 24-bit
      `0x0C7E0F`, slot 49 word
      `0x0031` at `0x7AD16`, XA=1.
      Matches. Seed stays. PART B:
      `follow_local` of `11EF` has
      no `CALLN`/`CALLF`/`JMP`/
      `JMPF` whose target file is
      a gap. Direct transfers:
      `JMPS` `1263` `EB 13` to
      `C6C2:1278` file `0x47E98`
      (same body); `CALLF`
      `B1B1:0081` file `0x31B91`;
      `CALLF` `B1B1:0026` file
      `0x31B36` twice; `CALLF`
      `B1B1:005B` file `0x31B6B`.
      All already owned. No gap
      callee to walk. Nothing
      seeded. Leftover `[0x47F65,
      0x47F82)`, `C6C2:1895`, and
      `D90C:0006` stay unowned.
      `CA9B:029E`, `C4C8:149B`,
      `C887:09AC`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318`
      stay unseeded. Ledger is 979
      ranges, 379089 owned bytes,
      127 gaps. D17 stays open.
      2026-09-23: PART A:
      `follow_local` from owned
      `C6C2:182D` lists IP `185F`
      `CALLN` `C6C2:1895` file
      `0x484B5` and IP `1884`
      `CALLF` `D90C:0006` file
      `0x590C6`. Also `D90C:0454`
      and `D90C:0338`. Re-read file
      `0x4847F` bytes `E8 33 00`:
      `CALLN` disp16 `0x0033`, next
      IP `1862`, target `1895`. The
      `00` is the high byte, not a
      hole. `75 12` is `JNZ` at
      `1837`, taken when `ZF=0`,
      rel8 `+0x12` from next IP
      `1839` to `184B`. `185F` is
      after `184B` and before range
      end `0x484B5`. A straight-line
      walk that takes `74 46` `JZ`
      `1849` to `1891` skips `185F`;
      that walk is not the proof.
      `follow_local` `C6C2:1895`
      file `0x484B5`, 20-bit
      `0xC84B5`, 24-bit `0x0C84B5`.
      Second PGR slot 50 word
      `0x0032` at `0x7AD18` (XA=1).
      First run is 10 insns,
      contiguous, missing 0, no `0F
      E0`/`0F F0`, ends `RETF` at
      `18A8`. Body `[0x484B5,
      0x484C9)`. Does not include
      `0x4921C`. Head `56` `PUSH
      SI`; `33 F6` writes `SI` from
      `SI` (ModR/M `F6`). `9A EE 00
      F7 D1` is `CALLF D1F7:00EE`;
      the `00` is the high byte of
      imm16 IP `0x00EE`. `83 C4 02`
      writes `SP` (ModR/M `C4` rm
      `SP`) from imm8 `+2`. `7C F1`
      at `18A5` is `JL`, taken when
      `SF!=OF`, rel8 `-0x0F` from
      next IP `18A7` to `1898`. Exit
      `5E` writes `SI` / `CB`
      `RETF`. **PROVEN.** Prefix of
      `[0x484B5, 0x4A458)`: leftover
      `[0x484C9, 0x4A458)` keeps
      gap_count 127. Adjacent to
      `182D`; ranges stay separate.
      `D90C:0006` / `0454` / `0338`
      differ (PUSH BP prologues);
      not this class. Leftover
      `[0x47F65, 0x47F82)`,
      `D90C:0006`, and `C887:09AC`
      stay unowned. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318`
      stay unseeded. Ledger is 980
      ranges, 379109 owned bytes,
      127 gaps. D17 stays open.
      2026-09-23: PART A re-read the
      linear image, not the checker.
      `follow_local` from owned
      `C6C2:182D` lists IP `185F`.
      File `0x4847F` bytes `E8 33
      00`: `CALLN` opcode `E8`,
      disp16 `0x0033` signed
      `+0x0033`, next IP `1862`,
      target `1895`. No ModR/M, no
      GPR write. The `00` is the
      high byte, not a hole. Head
      `56 33 F6 56 9A EE 00 F7`;
      tail `7C F1 5E CB`. First run
      is 10 insns, contiguous,
      missing 0, no `0F E0`/`0F
      F0`, ends `RETF` at `18A8`.
      Body `[0x484B5, 0x484C9)`.
      Does not include `0x4921C`.
      File `0x484B5`, `C6C2:1895`,
      20-bit `0xC84B5`, 24-bit
      `0x0C84B5`. Second PGR slot
      50 word `0x0032` at `0x7AD18`
      (XA=1). Head `56` `PUSH SI`;
      `33 F6` writes `SI` from `SI`
      (ModR/M `F6`). `7C F1` at
      `18A5` is `JL`, taken when
      `SF!=OF`, rel8 `-0x0F` from
      next IP `18A7` to `1898`. Exit
      `5E` writes `SI` / `CB`
      `RETF`. **PROVEN.** Matches.
      Seed stays. PART B: re-read
      file `0x484A4` bytes `9A 06
      00 0C D9`: `CALLF` opcode
      `9A`, imm16 IP `0x0006`,
      imm16 CS `0xD90C`. No ModR/M,
      no GPR write. The `00` is the
      high byte of IP, not a hole.
      `follow_local` `D90C:0006`
      file `0x590C6`, 20-bit
      `0xD90C6`, 24-bit `0x0D90C6`.
      Second PGR slot 54 word
      `0x0036` at `0x7AD20` (XA=1).
      Two runs. First run
      `[0x590C6, 0x59153)`, 57
      insns, contiguous, missing 0,
      no `0F E0`/`0F F0`, ends
      `JMPS` `EB 06` at `0091` to
      `D90C:0099` file `0x59159`,
      still a gap. Not RET/RETF and
      not a jump into owned code.
      Head `55` `PUSH BP`; `8B EC`
      writes `BP` from `SP` (ModR/M
      `EC`). `75 08` at `008A` is
      `JNZ`, taken when `ZF=0`,
      rel8 `+0x08` from next IP
      `008C` to `0094`. Not seeded.
      `D90C:0454` and `D90C:0338`
      not this pass. Leftover
      `[0x47F65, 0x47F82)`,
      `D90C:0006`, and `C887:09AC`
      stay unowned. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318`
      stay unseeded. Ledger is 980
      ranges, 379109 owned bytes,
      127 gaps. D17 stays open.
      2026-09-23: PART A: re-read
      each `CALLF` in owned
      `C6C2:182D`. File `0x48488`
      bytes `9A 54 04 0C D9`:
      opcode `9A`, imm16 IP
      `0x0454`, imm16 CS `0xD90C`.
      No ModR/M, no GPR write.
      `follow_local` from `182D`
      lists IP `1868`. File
      `0x48493` bytes `9A 38 03 0C
      D9`: opcode `9A`, imm16 IP
      `0x0338`, imm16 CS `0xD90C`.
      No ModR/M, no GPR write. The
      `03` is the high byte of IP,
      not a hole. `follow_local`
      from `182D` lists IP `1873`.
      Linear fallthrough from
      `D90C:0454` file `0x59514`
      is 28 insns and ends at
      `JMPN` `E9 C2 00` at `0492`
      (file `0x59552`), target
      `0557` file `0x59617`, still
      in the leftover gap. That is
      not `JMPS` `EB 0E` at `04C9`.
      Not RET/RETF. Not seeded.
      `follow_local` `D90C:0338`
      file `0x593F8`, 20-bit
      `0xD93F8`, 24-bit `0x0D93F8`.
      Second PGR slot 54 word
      `0x0036` at `0x7AD20` (XA=1).
      Fallthrough is 56 insns, not
      110. `74 49` at `0367` is
      `JZ` to `03B2` when `ZF=1`.
      The other arm `JMPN`s from
      `03AF` to `0439` and skips
      `[0x59472, 0x594F9)`. Both
      arms stay inside and `RETF`
      at `0440`. Body `[0x593F8,
      0x59501)`. Does not include
      `0x4921C`. Head `55` `PUSH
      BP`; `8B EC` writes `BP` from
      `SP` (ModR/M `EC`). `E8 11
      02` is `CALLN` disp16
      `+0x0211` from next IP `0363`
      to `0574`; not entered. `E9
      87 00` is `JMPN` disp16
      `+0x0087` from next IP `03B2`
      to `0439`; the `00` is the
      high byte, not a hole. `75
      FA` at `043D` is `JNZ`, taken
      when `ZF=0`, rel8 `-0x06`
      from next IP `043F` to
      `0439`. Exit `5D` writes `BP`
      / `CB` `RETF`. **PROVEN.**
      Mid-gap island in `[0x590C5,
      0x59650)`: gap_count 127 to
      128. Leftover `[0x590C5,
      0x593F8)` and `[0x59501,
      0x59650)` keep the extra
      gap. Adjacent seeds stay
      separate. `D90C:0454` /
      `0006` / `0574` not entered.
      Leftover `[0x47F65,
      0x47F82)`, `D90C:0006`, and
      `C887:09AC` stay unowned.
      `CA9B:029E`, `C4C8:149B`,
      `B13A:0000`, `B77C:1FDB`,
      and `D52A:0318` stay
      unseeded. Ledger is 981
      ranges, 379374 owned bytes,
      128 gaps. D17 stays open.
      2026-09-23: PART A: re-read
      `D90C:0338` from the linear
      image. `follow_local` from
      owned `C6C2:182D` lists IP
      `1873`. File `0x48493` bytes
      `9A 38 03 0C D9`: opcode
      `9A`, imm16 IP `0x0338`,
      imm16 CS `0xD90C`. No
      ModR/M, no GPR write. The
      `03` is the high byte of IP,
      not a hole. Two runs, not one.
      `74 49` at `0367` is `JZ` to
      `03B2` when `ZF=1`.
      Fallthrough `JMPN`s from
      `03AF` to `0439`. Both end
      `RETF` at `0440`. No `0F E0`/
      `0F F0`. Body `[0x593F8,
      0x59501)`. Head
      `55` `PUSH BP`; `8B EC`
      writes `BP` from `SP`
      (ModR/M `EC`). `75 FA` at
      `043D` file `0x594FD` is
      `JNZ`, taken when `ZF=0`,
      rel8 `-0x06` from next IP
      `043F` to `0439`. Exit `5D`
      writes `BP` / `CB` `RETF`.
      File `0x593F8`, 20-bit
      `0xD93F8`, 24-bit `0x0D93F8`.
      Slot 54 word `0x0036` at
      `0x7AD20` (XA=1). Seed kept.
      PART B: `follow_local` of
      `0338` has one gap-target
      transfer: `CALLN` at `0360`
      file `0x59420` bytes `E8 11
      02` to `D90C:0574` file
      `0x59634`. Opcode `E8`,
      disp16 `+0x0211` from next
      IP `0363`. No ModR/M, no GPR
      write. `0454` is not in this
      list. `follow_local` `0574`:
      one run, 16 insns,
      contiguous, missing 0, no
      `0F E0`/`0F F0`, ends `RET`
      at `058E`. Body `[0x59634,
      0x5964F)`. Does not include
      `0x4921C`. File `0x59634`,
      20-bit `0xD9634`, 24-bit
      `0x0D9634`. Slot 54 word
      `0x0036` at `0x7AD20`
      (XA=1). Head `BA 08 C0`
      writes `DX` from imm16
      `0xC008`. No Jcc. `B8 14 00`
      writes `AX` from imm16
      `0x0014`; the `00` is the
      high byte, not a hole. Exit
      `C3` `RET`. **PROVEN.**
      Mid-gap island in `[0x59501,
      0x59650)`: leftover
      `[0x59501, 0x59634)` keeps
      `0454` unowned. Isolated
      `0xFF` at `0x5964F` stays a
      leftover; gap_count 128 to
      129. Adjacent seeds stay
      separate. `D90C:0454` /
      `0006` and `C887:09AC` stay
      unowned. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and `D52A:0318`
      stay unseeded. Ledger is 982
      ranges, 379401 owned bytes,
      129 gaps. D17 stays open.
      2026-09-23: PART A: re-read
      `D90C:0574` from the linear
      image. `follow_local` from
      owned `D90C:0338` lists IP
      `0360`. File `0x59420` bytes
      `E8 11 02`: opcode `E8`,
      disp16 `+0x0211` from next
      IP `0363` to `0574`. No
      ModR/M, no GPR write. The
      `02` is the high byte, not a
      hole. Seed kept. Body
      `[0x59634, 0x5964F)`. Head
      `BA 08 C0` writes `DX` from
      imm16 `0xC008`. No Jcc.
      Exit `C3` `RET` at `058E`.
      File `0x59634`, 20-bit
      `0xD9634`, 24-bit `0x0D9634`.
      Slot 54 word `0x0036` at
      `0x7AD20` (XA=1). First run
      one closed body, missing 0,
      no `0F E0`/`0F F0`. PART B:
      `follow_local` `0574` has no
      gap-target `CALLN`/`CALLF`/
      `JMPN`/`JMPF`. Owned-code
      scan, caller-file order,
      five non-refused exact-entry
      hits. First closed body is
      `D90C:01AD`. Later hits
      differ (`C6C2:0D24` 111
      insns `RETF`; `C6C2:1169`
      50 insns `RETF`); not
      seeded. `follow_local` of
      owned `C6C2:1362` lists IP
      `1458`. File `0x48078`
      bytes `9A AD 01 0C D9`:
      opcode `9A`, imm16 IP
      `0x01AD`, imm16 CS `0xD90C`.
      No ModR/M, no GPR write.
      The `01` is the IP high
      byte, not a hole. Callee
      not entered in the caller
      proof. `follow_local`
      `01AD`: one run, 16 insns,
      contiguous, missing 0, no
      `0F E0`/`0F F0`, ends
      `RETF` at `01CC`. Body
      `[0x5926D, 0x5928D)`. Does
      not include `0x4921C`. File
      `0x5926D`, 20-bit `0xD926D`,
      24-bit `0x0D926D`. Slot 54
      word `0x0036` at `0x7AD20`
      (XA=1). Head `B8 00 00`
      writes `AX` from imm16
      `0x0000`; the zeros are the
      immediate, not a hole. `E7
      60` is `OUT` port `0x60`.
      `E5 64` is `IN` port `0x64`.
      `8B D0` writes `DX` from
      `AX` (ModR/M `D0`). `E2 F9`
      at `01C4` is `LOOP`
      (`JCC`), taken when `CX≠0`
      after decrement, rel8
      `-0x07` from next IP `01C6`
      to `01BF`. Exit `CB`
      `RETF`. **PROVEN.**
      Mid-gap island in
      `[0x590C5, 0x593F8)`:
      leftover `[0x590C5,
      0x5926D)` keeps `0006` /
      `0099` unowned; leftover
      `[0x5928D, 0x593F8)` stays
      a gap; gap_count 129 to
      130. Adjacent seeds stay
      separate. `D90C:0454` /
      `0006` / `0099` / `04D9`
      and `C887:09AC` stay
      unowned. Isolated `0xFF`
      at `0x5964F` stays a
      leftover. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and
      `D52A:0318` stay unseeded.
      Ledger is 983 ranges,
      379433 owned bytes, 130
      gaps. D17 stays open.
      2026-09-23: PART A: re-read
      `D90C:01AD` from the linear
      image. `follow_local` from
      owned `C6C2:1362` lists IP
      `1458`. File `0x48078`
      bytes `9A AD 01 0C D9`:
      opcode `9A`, imm16 IP
      `0x01AD`, imm16 CS `0xD90C`.
      No ModR/M, no GPR write.
      The `01` is the IP high
      byte, not a hole. Callee
      not entered in the caller
      proof. Seed kept. Body
      `[0x5926D, 0x5928D)`. Head
      `B8 00 00` writes `AX` from
      imm16 `0x0000`; the zeros
      are the immediate, not a
      hole. `E2 F9` at `01C4` is
      `LOOP`, decrements `CX`,
      taken when `CX≠0`, rel8
      `-0x07` from next IP `01C6`
      to `01BF`. Exit `CB`
      `RETF`. File `0x5926D`,
      20-bit `0xD926D`, 24-bit
      `0x0D926D`. Slot 54 word
      `0x0036` at `0x7AD20`
      (XA=1). First run one
      closed body, missing 0, no
      `0F E0`/`0F F0`. PART B:
      `follow_local` `01AD` has no
      gap-target `CALLN`/`CALLF`/
      `JMPN`/`JMPF`. Try `0D24`
      first. `follow_local` of
      owned `C6C2:1362` lists IP
      `14B5`. File `0x480D5`
      bytes `E8 6C F8`: opcode
      `E8`, disp16 `0xF86C`
      signed `-0x0794` from next
      IP `14B8` to `0D24`. No
      ModR/M, no GPR write. The
      `F8` is the high byte, not
      a hole. `151D` `E8 04 F8`
      is a second listed `CALLN`
      to `0D24`; proof is `14B5`.
      Callee not entered in the
      caller proof. `follow_local`
      `0D24`: one run, 111 insns,
      contiguous, missing 0, no
      `0F E0`/`0F F0`, ends
      `RETF` at `0E4A`. Body
      `[0x47944, 0x47A6B)`. Does
      not include `0x4921C`. File
      `0x47944`, 20-bit `0xC7944`,
      24-bit `0x0C7944`. Slot 49
      word `0x0031` at `0x7AD16`
      (XA=1). Head `55` `PUSH
      BP`; `8B EC` writes `BP`
      from `SP` (ModR/M `EC`);
      `83 EC 0E` writes `SP`
      (ModR/M `EC` rm `SP`, `/5`
      `SUB`) from imm8 `+0x0E`.
      `C7 06 9F D6 00 00` is
      `MOV [D69F],` imm16
      `0x0000`; the zeros are the
      immediate, not a hole. `73
      0E` at `0D7B` is `JNB`/
      `JAE`, taken when `CF=0`,
      rel8 `+0x0E` from next IP
      `0D7D` to `0D8B`. `EB 0F`
      at `0D89` is `JMPS` to
      `0D9A` inside the first
      run, not an exit into a
      gap. Exit `5F`/`5E` writes
      `DI`/`SI`, `C9` `LEAVE`,
      `CB` `RETF`. **PROVEN.**
      Mid-gap island in
      `[0x46C2B, 0x47E0F)`:
      leftover `[0x46C2B,
      0x47944)` keeps the prefix;
      leftover `[0x47A6B,
      0x47E0F)` keeps `1169`
      unowned; gap_count 130 to
      131. Adjacent seeds stay
      separate. `C6C2:1169` is
      also one closed first run
      (50 insns, missing 0, ends
      `RETF`); not seeded (at
      most one). `D90C:0454` /
      `0006` / `0099` / `04D9`
      and `C887:09AC` stay
      unowned. Isolated `0xFF`
      at `0x5964F` stays a
      leftover. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and
      `D52A:0318` stay unseeded.
      Ledger is 984 ranges,
      379728 owned bytes, 131
      gaps. D17 stays open.
      2026-09-23: PART A: re-read
      `C6C2:0D24` from the linear
      image. `follow_local` from
      owned `C6C2:1362` lists IP
      `14B5`. File `0x480D5`
      bytes `E8 6C F8`: opcode
      `E8`, disp16 `0xF86C`
      signed `-0x0794` from next
      IP `14B8` to `0D24`. No
      ModR/M, no GPR write. The
      `F8` is the high byte, not
      a hole. Seed kept. Body
      `[0x47944, 0x47A6B)`. Head
      `55` `PUSH BP`; `8B EC`
      writes `BP` from `SP`
      (ModR/M `EC`); `83 EC 0E`
      writes `SP` (ModR/M `EC`
      rm `SP`, `/5` `SUB`) from
      imm8 `+0x0E`. `73 0E` at
      `0D7B` is `JNB`/`JAE`,
      taken when `CF=0`, rel8
      `+0x0E` from next IP
      `0D7D` to `0D8B`. Exit
      `5F`/`5E` writes `DI`/`SI`,
      `C9` `LEAVE`, `CB` `RETF`
      at `0E4A`. File `0x47944`,
      20-bit `0xC7944`, 24-bit
      `0x0C7944`. Slot 49 word
      `0x0031` at `0x7AD16`
      (XA=1). First run one
      closed body, 111 insns,
      missing 0, no `0F E0`/`0F
      F0`. PART B: `follow_local`
      of owned `C6C2:1362` lists
      IP `1546`. File `0x48166`
      bytes `E8 20 FC`: opcode
      `E8`, disp16 `0xFC20`
      signed `-0x03E0` from next
      IP `1549` to `1169`. No
      ModR/M, no GPR write. The
      `FC` is the high byte, not
      a hole. `15A4` `E8 C2 FB`
      is a second listed `CALLN`
      to `1169`; proof is
      `1546`. Callee not entered
      in the caller proof.
      `follow_local` `1169`: one
      run, 50 insns, contiguous,
      missing 0, no `0F E0`/`0F
      F0`, ends `RETF` at
      `11EE`. Body `[0x47D89,
      0x47E0F)`. Does not
      include `0x4921C`. File
      `0x47D89`, 20-bit
      `0xC7D89`, 24-bit
      `0x0C7D89`. Slot 49 word
      `0x0031` at `0x7AD16`
      (XA=1). Head `55` `PUSH
      BP`; `8B EC` writes `BP`
      from `SP` (ModR/M `EC`);
      `83 EC 02` writes `SP`
      (ModR/M `EC` rm `SP`, `/5`
      `SUB`) from imm8 `+2`.
      `BB C4 03` writes `BX`
      from imm16 `0x03C4`; the
      `03` is the high byte, not
      a hole. `7D 04` at `1184`
      is `JGE`/`JNL`, taken when
      `SF=OF`, rel8 `+4` from
      next IP `1186` to `118A`.
      Exit `C9` `LEAVE` / `CB`
      `RETF`. **PROVEN.** Suffix
      of leftover `[0x47A6B,
      0x47E0F)`: leftover prefix
      `[0x47A6B, 0x47D89)` keeps
      gap_count 131. Adjacent to
      `11EF`; ranges stay
      separate. No 0D24 callee
      seeded. `D90C:0454` /
      `0006` / `0099` / `04D9`
      and `C887:09AC` stay
      unowned. Isolated `0xFF`
      at `0x5964F` stays a
      leftover. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and
      `D52A:0318` stay unseeded.
      Ledger is 985 ranges,
      379862 owned bytes, 131
      gaps. D17 stays open.
      2026-09-23: PART A: re-read
      `C6C2:1169` from the linear
      image. `follow_local` from
      owned `C6C2:1362` lists IP
      `1546`. File `0x48166`
      bytes `E8 20 FC`: opcode
      `E8`, disp16 `0xFC20`
      signed `-0x03E0` from next
      IP `1549` to `1169`. No
      ModR/M, no GPR write. The
      `FC` is the high byte, not
      a hole. Seed kept. Body
      `[0x47D89, 0x47E0F)`. Head
      `55` `PUSH BP`; `8B EC`
      writes `BP` from `SP`
      (ModR/M `EC`); `83 EC 02`
      writes `SP` (ModR/M `EC`
      rm `SP`, `/5` `SUB`) from
      imm8 `+2`. `7D 04` at
      `1184` is `JGE`/`JNL`,
      taken when `SF=OF`, rel8
      `+4` from next IP `1186`
      to `118A`. Exit `C9`
      `LEAVE` / `CB` `RETF` at
      `11EE`. File `0x47D89`,
      20-bit `0xC7D89`, 24-bit
      `0x0C7D89`. Slot 49 word
      `0x0031` at `0x7AD16`
      (XA=1). First run one
      closed body, 50 insns,
      missing 0, no `0F E0`/`0F
      F0`. **PROVEN.** PART B:
      `follow_local` of `1169`
      has no gap-target `CALLN`/
      `CALLF`/`JMPN`/`JMPF`.
      Remaining gap-target
      direct calls in
      `follow_local` of owned
      `C6C2:1362` that are not
      already owned (`0D24`,
      `1169`, `11EF`, `12D2`,
      `1324`, `182D`, `1895`,
      `D90C:01AD` / `0338` /
      `0574`) = 0. Nothing
      seeded. `C6C2:1169`: one
      run, missing 0, ends
      `RETF`. `C6C2:1362`: one
      run, missing 0, ends
      `RETF` at `15E8`. Did not
      scan the rest of the
      image. `D90C:0454` /
      `0006` / `0099` / `04D9`
      and `C887:09AC` stay
      unowned. Isolated `0xFF`
      at `0x5964F` stays a
      leftover. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and
      `D52A:0318` stay unseeded.
      Ledger is 985 ranges,
      379862 owned bytes, 131
      gaps. D17 stays open.
      2026-09-23: Owned-code
      `follow_local` from each
      range start. Direct
      `CALLN`/`CALLF`/`JMPN`/
      `JMPF` immediates into
      gaps, not `JMPN_RM`.
      Named bodies and the
      refused list excluded.
      Non-refused hit count 1:
      `DAF2:0040`. Caller
      `DCA2:000F` `9A 40 00 F2
      DA` is in `follow_local`
      of extra `[0x5CA2E,
      0x5CA78)` from start IP
      `000E` (adjacent `DCA2`
      `JMP CS:[BX+0058]`
      table). File `0x5AF60`,
      `DAF2:0040`, 20-bit
      `0xDAF60`, 24-bit
      `0x0DAF60`, second PGR
      slot 54 word `0x0036` at
      `0x7AD20` (XA=1). Head
      `55` `PUSH BP`; `8B EC`
      writes `BP` from `SP`
      (ModR/M `EC`); `83 EC
      02` writes `SP` (ModR/M
      `EC` rm `SP`, `/5` `SUB`)
      from imm8 `+2`. First run
      29 insns, contiguous,
      missing 0, no `0F E0`/`0F
      F0`. `E9 B5 00` at `0089`
      is `JMPN`, disp16
      `+0x00B5` from next IP
      `008C` to `0141` (file
      `0x5B061`), still a gap.
      Five runs. Ends `JMPN`
      into unowned code. Does
      not qualify. Nothing
      seeded. `C6C2:1169`
      stays. `D90C:0454` /
      `0006` / `0099` / `04D9`
      and `C887:09AC` stay
      unowned. Isolated `0xFF`
      at `0x5964F` stays a
      leftover. `CA9B:029E`,
      `C4C8:149B`, `B13A:0000`,
      `B77C:1FDB`, and
      `D52A:0318` stay
      unseeded. Ledger is 985
      ranges, 379862 owned
      bytes, 131 gaps. D17
      stays open.
      2026-09-23: PART A: re-read
      `DAF2:0040`. `follow_local`
      of owned `[0x5CA2E,
      0x5CA78)` from start IP
      `DCA2:000E` lists
      `DCA2:000F`. File
      `0x5CA2F` bytes `9A 40 00
      F2 DA`: opcode `9A`
      `CALLF`, imm16 IP
      `0x0040`, imm16 CS
      `0xDAF2`. No ModR/M, no
      GPR write. The `00` is
      the IP high byte, not a
      hole. Target file
      `0x5AF60`, `DAF2:0040`,
      20-bit `0xDAF60`, 24-bit
      `0x0DAF60`, second PGR
      slot 54 word `0x0036` at
      `0x7AD20` (XA=1). Head
      `55` `PUSH BP`; `8B EC`
      writes `BP` from `SP`
      (ModR/M `EC`); `83 EC
      02` writes `SP` (ModR/M
      `EC` rm `SP`, `/5` `SUB`)
      from imm8 `+2`. First
      run 29 insns, contiguous,
      missing 0, no `0F E0`/`0F
      F0`. Five runs. `E9 B5
      00` at `0089` file
      `0x5AFA9` is `JMPN`,
      disp16 `+0x00B5`
      little-endian
      sign-extended from next
      IP `008C` to `0141`.
      Unconditional, writes
      nothing. Target file
      `0x5B061` is unowned
      (gap `[0x5AEF9,
      0x5B07D)`). First run
      ends `JMPN` into a gap.
      Does not qualify. Do not
      seed `0040`.
      `follow_local`
      `DAF2:0141`: one run, 8
      insns, contiguous,
      missing 0, no `0F E0`/`0F
      F0`, ends `RETF` at
      `0154`. File `0x5B061`,
      20-bit `0xDB061`, 24-bit
      `0x0DB061`, slot 54 word
      `0x0036` at `0x7AD20`
      (XA=1). Head `83 7E FE
      00` is `CMP [BP-2],`
      imm8 `0`; writes nothing.
      `74 0C` at `0145` is
      `JZ`/`JE`, taken when
      `ZF=1`, rel8 `+0x0C`
      from next IP `0147` to
      `0153`. `9A F1 00 E0
      D6` is `CALLF
      D6E0:00F1`; no ModR/M,
      no GPR write. Closed
      body, but no owned
      caller of its own. Not
      seeded. **PROVEN.** PART
      B: `follow_local` of
      owned `C6C2:0D24`
      `[0x47944, 0x47A6B)`
      from start IP `0D24`:
      111 insns. Seven `CALLF`
      (`B1B1:0081` / `0026` /
      `005B` / `F800:20FA` /
      `20C4`); every target
      file is already owned.
      Gap-target
      `CALLN`/`CALLF`/`JMP`/
      `JMPF` count 0. Owned
      `C6C2:1895` `[0x484B5,
      0x484C9)` from `1895`:
      10 insns. One `CALLF`
      `D1F7:00EE` already
      owned. Gap-target count
      0. Owned `D90C:01AD`
      `[0x5926D, 0x5928D)`
      from `01AD`: 16 insns.
      No `CALLN`/`CALLF`/
      `JMPN`/`JMPF`.
      Gap-target count 0. All
      three have none.
      Nothing seeded. Did not
      redo `C6C2:1169` or
      `C6C2:1362`. Did not
      scan the whole image.
      `C887:09AC`,
      `D90C:0454` / `0006` /
      `0099` / `04D9`,
      leftover `[0x47F65,
      0x47F82)`, `CA9B:029E`,
      `C4C8:149B`,
      `B13A:0000`,
      `B77C:1FDB`, and
      `D52A:0318` stay
      unseeded. Ledger is 985
      ranges, 379862 owned
      bytes, 131 gaps. D17
      stays open.
      2026-09-23: Compare-bounded
      `JMP CS:[BX+disp16]` in
      owned code whose table
      is still a gap: 0. Image
      `2E FF A7` count 100
      (43 owned `code`, 57 in
      gaps). `2E FF A3` and
      `2E FF 67` are absent.
      One owned `2E FF A5` is
      `D547:055C` `JMP
      CS:[DI+0561]`; that
      table is already data.
      Each owned `2E FF A7`
      that `follow_local` hits
      from the range start,
      with an imm8 `CMP BX`
      or imm8 `AND BX` mask,
      already has its word
      span owned as `data`.
      Did not redo `C4C8`
      `[0x45593, 0x455A7)` /
      `[0x46498, 0x464A4)` /
      `[0x464C4, 0x464D0)` /
      `[0x464D0, 0x464E0)`.
      Did not enter slots
      `1806` / `154B` /
      `1731` / `17A8` /
      `14C5` / `149B` /
      `17ED`. First owned hit
      `B060:0631` file
      `0x30C31` is `2E FF A7
      01 07`. `0628` `8B D8`
      writes `BX` from `AX`
      (ModR/M `D8`). `062A`
      `83 FB 09` is `CMP BX,
      imm8 +9` (ModR/M `FB`
      `/7`, writes nothing).
      `062D` `77 7E` is `JA`,
      taken when unsigned `>`
      (`CF=0` and `ZF=0`),
      target `06AD` from next
      IP `062F`, so the table
      path is `BX<=9`. `062F`
      `D1 E3` is `SHL BX,1`
      and writes `BX`. Table
      `B060:0701` file
      `0x30D01` is 10 words
      already data. 20-bit
      `0xB0D01`, 24-bit
      `0x0B0D01`, second PGR
      slot 44 word `0x002C`
      at `0x7AD0C` (XA=1).
      **PROVEN.** `BE1A:059F`
      and `DCA2:0053` are
      owned `2E FF A7` that
      `follow_local` from
      those range starts does
      not hit; both tables
      are already data.
      `DB28:0A74` `2E FF A7
      29 00` has no imm8
      compare; disp `0029`
      lands in owned code.
      `D3A7:019D` is an `IN`
      path. Gap `2E FF A7`
      switches stay unowned.
      Did not seed
      `DAF2:0040` / `0141`.
      Nothing seeded. Ledger
      is 985 ranges, 379862
      owned bytes, 131 gaps.
      D17 stays open.
      2026-09-23: PART A: re-read
      owned `B060:062A`. Range
      `[0x3095D, 0x30D01)` starts
      `B060:035D`. `follow_local`
      from that start lists
      `062A` / `062D` / `0631`.
      File `0x30C2A`,
      `B060:062A`, 20-bit
      `0xB0C2A`, 24-bit
      `0x0B0C2A`, second PGR
      slot 44 word `0x002C` at
      `0x7AD0C` (XA=1). `062A`
      `83 FB 09` is `CMP BX,`
      imm8 `+9` (ModR/M `FB`
      `/7`, writes nothing).
      `062D` `77 7E` is `JA`,
      taken when unsigned `>`
      (`CF=0` and `ZF=0`), rel8
      `+0x7E` from next IP
      `062F` to `06AD`, so the
      table path is `BX<=9`.
      `062F` `D1 E3` is `SHL
      BX,1` and writes `BX`.
      `0631` `2E FF A7 01 07`
      is `JMP CS:[BX+0701]`,
      writes nothing.
      **PROVEN.** Table
      `B060:0701` file
      `[0x30D01, 0x30D15)` is
      10 words already data.
      Did not change the table.
      PART B: the 10 words are
      `0636` / `0649` / `0659`
      / `067D` / `067D` /
      `068D` / `0659` / `06AD`
      / `069D` / `0659`. Every
      slot file sits in owned
      `[0x3095D, 0x30D01)`.
      Next `follow_local` hit
      is owned `B060:0AD9`
      `[0x310D9, 0x31128)`:
      `0B19` `83 FB 09` `CMP
      BX,` imm8 `+9`; `0B1C`
      `76 03` is `JBE` to
      `0B21` when unsigned
      `BX<=9`; `0B23` `2E FF
      A7 58 0C` is `JMP
      CS:[BX+0C58]`. Table
      `[0x31258, 0x3126C)` is
      already data; all 10
      slot files owned. Later
      compare-bounded
      `CS:[BX+disp16]` tables
      that `follow_local`
      hits, excluding the four
      `C4C8` tables, have no
      remaining gap slot.
      Did not redo `C4C8`
      `[0x45593, 0x455A7)` /
      `[0x46498, 0x464A4)` /
      `[0x464C4, 0x464D0)` /
      `[0x464D0, 0x464E0)` or
      refused slots `1806` /
      `154B` / `1731` /
      `17A8` / `14C5` /
      `149B` / `17ED`. Did
      not seed `DAF2:0040` /
      `0141`. Did not own
      another table. No gap
      slot to seed. Nothing
      seeded. Ledger is 985
      ranges, 379862 owned
      bytes, 131 gaps. D17
      stays open.
      2026-09-23: Owned
      `F800:0F07` `[0x78F07,
      0x78F6D)` `follow_local`
      from start IP `0F07`
      lists `0F61` / `0F63` /
      `0F66` / `0F74` /
      `0F82`. File `0x78F63`,
      `F800:0F63`, 20-bit
      `0xF8F63`, 24-bit
      `0x0F8F63`, second PGR
      slot 62 word `0x003E` at
      `0x7AD30` (XA=1). `0F5E`
      `3D 14 00` is `CMP AX,`
      imm16 `0x0014`; writes
      nothing. The `00` is the
      high byte, not a hole.
      `0F61` `77 0B` is `JA`,
      taken when unsigned `>`
      (`CF=0` and `ZF=0`), rel8
      `+0x0B` from next IP
      `0F63` to `0F6E`, so the
      table path is `AX<=0x14`.
      `0F63` `BE 1F 03` is
      `MOV SI,` imm16 `0x031F`
      (opcode `BE` `B8+SI`);
      writes `SI`. `0F66` `B9
      03 00` is `MOV CX,`
      imm16 `+3` (opcode `B9`
      `B8+CX`); writes `CX`.
      The `00` is the CX high
      byte, not a hole. `0F69`
      `B2 00` is `MOV DL,`
      imm8 `0`; writes `DL`.
      `0F6B` `EB 07` is `JMPS`,
      unconditional, rel8 `+7`
      from next IP `0F6D` to
      `0F74`; writes nothing.
      `0F74` `2E 8B 1C` is
      `MOV BX, CS:[SI]`
      (ModR/M `1C` mod `0`
      reg `BX` rm `SI`);
      writes `BX`. `0F7D` `83
      C6 02` is `ADD SI,`
      imm8 `+2` (ModR/M `C6`
      mod `3` `/0` rm `SI`);
      writes `SI`. `0F82` `E2
      F0` is `LOOP`, taken
      after `CX--` while
      `CX!=0`, rel8 `-0x10`
      from next IP `0F84` to
      `0F74`; writes `CX`.
      **PROVEN.** Table
      `F800:031F` file
      `[0x7831F, 0x78325)` is
      3 words, 20-bit
      `0xF831F`, 24-bit
      `0x0F831F`, same slot 62.
      Seeded as data. Prefix
      `[0x78317, 0x7831F)` and
      records at `0x78325`
      stay gaps. Did not seed
      `DAF2:0040` / `0141`.
      Ledger is 986 ranges,
      379868 owned bytes, 132
      gaps. D17 stays open.
      2026-09-23: Same owned
      `F800:0F07` `follow_local`
      also lists `0F3B` /
      `0F3E` / `0F41` / `0F45`
      / `0F47` before the word
      loop. File `0x78F3B`,
      `F800:0F3B`, 20-bit
      `0xF8F3B`, 24-bit
      `0x0F8F3B`, second PGR
      slot 62 word `0x003E` at
      `0x7AD30` (XA=1). `0F3B`
      `B9 15 00` is `MOV CX,`
      imm16 `0x0015` (opcode
      `B9` `B8+CX`); writes
      `CX`. The `00` is the CX
      high byte, not a hole.
      `0F3E` `BE 37 00` is
      `MOV SI,` imm16 `0x0037`
      (opcode `BE` `B8+SI`);
      writes `SI`. The `00` is
      the SI high byte. `0F41`
      `8A 04` is `MOV AL,[SI]`
      (ModR/M `04` mod 0 reg
      `AL` rm `SI`); writes
      `AL`. No `2E`; the
      segment is DS. `0F45`
      `46` is `INC SI`
      (`40+SI`); writes `SI`;
      the advance is +1, not
      +2. `0F47` `E2 F8` is
      `LOOP`, taken after
      `CX--` while `CX!=0`,
      rel8 `-8` from next IP
      `0F49` to `0F41`; writes
      `CX`. Not the word-table
      shape. Stop. The only
      `2E 8B 1C` in the image
      is owned `F800:0F74`.
      Its table `[0x7831F,
      0x78325)` is already
      data. No other owned
      loop of that shape has a
      gap table. Did not seed
      `DAF2:0040` / `0141`.
      Nothing seeded. Ledger
      is 986 ranges, 379868
      owned bytes, 132 gaps.
      D17 stays open.
      2026-09-23: Re-read the
      owned `F800:0F07` byte
      loop. Bytes match.
      `follow_local` from
      `0F07` lists `0F3B` /
      `0F3E` / `0F41` /
      `0F43` / `0F45` /
      `0F46` / `0F47`. File
      `0x78F3B`, `F800:0F3B`,
      20-bit `0xF8F3B`,
      24-bit `0x0F8F3B`,
      second PGR slot 62 word
      `0x003E` at `0x7AD30`
      (XA=1; word re-read
      `3e00`). `0F3B` `B9 15
      00` is `MOV CX,` imm16
      `0x0015` (opcode `B9`
      `B8+CX`); writes `CX`.
      The `00` is the CX high
      byte, not a hole.
      `0F3E` `BE 37 00` is
      `MOV SI,` imm16 `0x0037`
      (opcode `BE` `B8+SI`);
      writes `SI`. The `00` is
      the SI high byte.
      `0F41` `8A 04` is
      `MOV AL, DS:[SI]`
      (ModR/M `04` mod 0 reg
      `AL` rm `SI`); writes
      `AL`. No prefix; the
      segment is DS. `0F43`
      `88 07` is `MOV DS:[BX],
      AL` (ModR/M `07` mod 0
      reg `AL` rm `BX`).
      `0F45` `46` is `INC SI`
      (`40+SI`); writes `SI`;
      +1. `0F46` `43` is
      `INC BX` (`40+BX`);
      writes `BX`. `0F47`
      `E2 F8` is `LOOP`, own
      IP `0F47`, next IP
      `0F49`, rel8 `-8`
      (signed `F8`), target
      `0F41`; taken after
      `CX--` while `CX!=0`;
      writes `CX`. **PROVEN.**
      From range start `0F07`
      through `0F47` there is
      no `8E /r`, no `1F`
      `POP DS`, and no `C5`
      `LDS`. The walk's only
      later segment pop is
      `0FB2` `07` `POP ES`
      (writes `ES`, after the
      loop). DS is
      **UNDETERMINED**. Did
      not seed `DS:0037`. Did
      not seed `DAF2:0040` /
      `0141`. Nothing seeded.
      Ledger is 986 ranges,
      379868 owned bytes, 132
      gaps. D17 stays open.
      2026-09-23: Owned CS-
      prefixed source loops
      after skip `F800:0F74`.
      `2E 8B 04` / `2E A4` /
      `2E A5` are 0 in owned
      code. First candidate
      fails; seed nothing.
      File `0x79755`,
      `F800:1755`, 20-bit
      `0xF9755`, 24-bit
      `0x0F9755`, second PGR
      slot 62 word `0x003E` at
      `0x7AD30` (XA=1; word
      re-read `3e00`).
      `follow_local` from
      `1752` lists `1752` /
      `1755` / `175A` /
      `1760` / `1763`. `1752`
      `BE 6E 17` is `MOV SI,`
      imm16 `0x176E` (opcode
      `BE` `B8+SI`); writes
      `SI`. The `17` is the SI
      high byte, not a hole.
      `1755` `2E 8A 04` is
      `MOV AL, CS:[SI]`
      (prefix `2E`; opcode
      `8A`; ModR/M `04` mod 0
      reg `AL` rm `SI`);
      writes `AL`. `175A`
      `74 0E` is `JZ`, taken
      when `ZF=1`, rel8 `+0x0E`
      from next IP `175C` to
      `176A`. `1760` `83 C6
      03` is `ADD SI,` imm8
      `+3` (ModR/M `C6` mod 3
      `/0` rm `SI`); writes
      `SI`. `1763` `EB F0` is
      `JMPS`, unconditional,
      rel8 `-16` from next IP
      `1765` to `1755`. No
      `MOV CX` / `MOV CL` imm
      in that walk. Count is
      the `AL==0` sentinel.
      Advance is +3, not 1 or
      2. **PROVEN.** Table
      `F800:176E` is already
      data. Fail: count,
      advance. File `0x7AC16`,
      `FAC0:0016`, 20-bit
      `0xFAC16`, 24-bit
      `0x0FAC16`, same slot
      62. `follow_local` from
      `0000` lists `000D` /
      `0010` / `0016` /
      `001A`. `000D` `B9 40
      00` is `MOV CX,` imm16
      `0x0040` (opcode `B9`
      `B8+CX`); writes `CX`.
      The `00` is the CX high
      byte, not a hole. `0010`
      `BE 56 02` is `MOV SI,`
      imm16 `0x0256` (opcode
      `BE`); writes `SI`.
      `0016` `2E 6F` is
      `OUTSW` from `CS:[SI]`
      (prefix `2E`; opcode
      `6F`); writes `SI` +2.
      `001A` `E2 FA` is
      `LOOP`, own IP `001A`,
      next IP `001C`, rel8 `-6`
      (signed `FA`), target
      `0016`; taken after
      `CX--` while `CX!=0`;
      writes `CX`. **PROVEN.**
      Advance is the string
      op, not `INC` / `ADD`
      imm. Table `FAC0:0256`
      is already PGR data.
      Fail: advance. File
      `0x7AC22`, `FAC0:0022`,
      20-bit `0xFAC22`,
      24-bit `0x0FAC22`, same
      slot 62. `001F` `BE D6
      02` is `MOV SI,` imm16
      `0x02D6`; writes `SI`.
      `0022` `2E AD` is
      `LODSW` from `CS:[SI]`;
      writes `AX` and `SI` +2.
      `0024` `3D 34 12` is
      `CMP AX,` imm16 `0x1234`;
      writes nothing. The `12`
      is the high byte, not a
      hole. `0027` `74 07` is
      `JZ`, taken when `ZF=1`,
      rel8 `+7` from next IP
      `0029` to `0030`. `002E`
      `EB F2` is `JMPS`,
      rel8 `-14` from next IP
      `0030` to `0022`.
      **PROVEN.** Count is the
      `0x1234` sentinel, not
      an imm8 / imm16 count.
      Advance is `LODSW`, not
      `INC` / `ADD` imm. Table
      `FAC0:02D6` is already
      data. Fail: count,
      advance. Did not seed
      `DAF2:0040` / `0141`.
      Did not scan DS-default
      loads. Nothing seeded.
      Ledger is 986 ranges,
      379868 owned bytes, 132
      gaps. D17 stays open.
      2026-09-23: FAC0:0022
      LODSW loop re-read from
      the linear image. PART A
      pass. File `0x7AC1F`,
      `FAC0:001F`, 20-bit
      `0xFAC1F`, 24-bit
      `0x0FAC1F`, second PGR
      slot 62 word `0x003E` at
      `0x7AD30` (XA=1; word
      re-read `3e00`). The
      `00` is the slot high
      byte, not a hole. `001F`
      `BE D6 02` is `MOV SI,`
      imm16 `0x02D6` (opcode
      `BE` `B8+SI`); writes
      `SI`. Next IP `0022`.
      File `0x7AC22`,
      `FAC0:0022`, 20-bit
      `0xFAC22`, 24-bit
      `0x0FAC22`, same slot
      62. `0022` `2E AD` is
      `LODSW` from `CS:[SI]`
      (prefix `2E`; opcode
      `AD`); writes `AX` and
      `SI` +2. Next IP `0024`.
      `0024` `3D 34 12` is
      `CMP AX,` imm16 `0x1234`
      (opcode `3D`); writes
      nothing. The `12` is the
      high byte, not a hole.
      Next IP `0027`. `0027`
      `74 07` is `JZ`, taken
      when `ZF=1`, rel8 `+7`
      from next IP `0029` to
      `0030`. `002E` `EB F2`
      is `JMPS`, unconditional,
      rel8 `-14` from next IP
      `0030` to `0022`.
      **PROVEN.** PART B: file
      `0x7AED6`, `FAC0:02D6`,
      20-bit `0xFAED6`, 24-bit
      `0x0FAED6`, same slot
      62. First byte is already
      owned data
      `[0x7AED6, 0x7AF6A)`.
      First 64 little-endian
      words have no `0x1234`
      sentinel. Seed nothing.
      Ledger is 986 ranges,
      379868 owned bytes, 132
      gaps. D17 stays open.
      2026-09-23: JEV is the TypeSafe
      System One model. Requested
      `jev-latest`; response
      `jev-1.13.0`. Not a program in
      this tree. Measured 132 gaps,
      144420 bytes. 131 are not all
      `0xFF`. File `0x5964F` is one
      `FF`, `D90C:058F`, 20-bit
      `0xD964F`, 24-bit `0xD964F`,
      second PGR slot 54 word
      `0x0036` at `0x7AD20` (XA=1;
      bytes `3600`). Neighbors
      re-read `C5 EF 9D C3` / `55 8B
      EC FC`. First call split and
      was not adopted (16 `not_free`,
      86 `mapped_unused`, 30
      `structural_edge`; 50436/8723
      tokens). `mapped_unused` on a
      non-`0xFF` gap loses to that
      count. Second call, narrow rule
      that an unowned gap is
      `not_free`, returned `not_free`
      for all 132 at confidence 1.0
      (54280/8386). Class is
      **HYPOTHESIS**. Noul that
      `0x5964F` is a patch bank is
      0.10. Procedure call chose the
      preimage procedure at
      confidence 1.0 (1444/164).
      All-paths unread noul 0.04.
      `CA9B:01C5` file `0x4AB75`,
      20-bit `0xCAB75`, 24-bit
      `0xC8B75`, slot 50 word
      `0x0032` (XA=1), re-read
      `E8 D6 00`: `CALLN` disp16
      `+0x00D6`, next IP `01C8`,
      target `029E`, writes no GPR.
      Thirteen direct calls into
      seven gaps stay unseeded,
      including `DAF2:0040` and
      `C887:09AC`. Fetches inside
      gaps = 0. Memory operands were
      not translated. Nothing seeded.
      See [`notes/jev_unowned_gaps.md`](notes/jev_unowned_gaps.md).
      Ledger is 986 ranges, 379868
      owned bytes, 132 gaps. D17
      stays open.

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
      absent (`U-PANEL-ROM`). The MAME driver names the key
      matrix and the µPD78C10 wiring. That is the model of the
      missing ROM, not the ROM and not a captured frame.
      V53 `0xC0-0xDF` I/O encodings are pinned; bit meaning
      stays `U-TE7774`. See [`notes/front_panel.md`](notes/front_panel.md).
      Missing: the dump and one captured panel frame.
- [x] **D20.** Pad / note entry. Assign screen, `D9F2` accessors, and
      owned `[D6AC]` writers are named in
      [`notes/pad_note.md`](notes/pad_note.md). Clamps at `0x44640` /
      `0x4473F` and remaps at `0x30B04` / `0x5A5C5` are not a pad-hit.
      The other store, `D52A:0328` (file `0x555C8`, `A2 AC D6`, 20-bit
      `0xD55C8`, 24-bit `0x0D55C8` under second PGR slot 53 word
      `0x0035` at `0x7AD1E`), has no static entry and no reached
      computed near entry. CS `D52A` walk: 19 indirect near transfers,
      17 `CS:` memory (the words `18 03` / `28 03` are absent) and two
      `JMP BX` (`FF E3` at `0x5558B` / `0x5598D`). `[7626]` and
      `[SI+762E]` values that those jumps read are not `0x0318` or
      `0x0328`. A pad hit on the wire stays D19 (`U-PANEL-ROM`,
      `U-TE7774`). DGROUP `+0054` is pan, not pads
      ([`notes/pan_table.md`](notes/pan_table.md)).
- [ ] **D21.** Sequencer transport (play/stop/position).
- [PARTIAL] **D22.** Sampling / DSP register path (`0x0060`, DMA). The 8237 “`0xC006` is channel 3” reading is retracted: FAC0 writes `SCTL=0x11` (file `0x7AED6`), and MAME’s `SCTL` bit 1 clear selects the µPD71071 map, where offset `0x06` is the selected channel’s address high byte (`notes/d22_sampling.md` §7). Missing: silicon effect of the owned `0x0060-0x006C` writes (`U-PHYS`) and a NEC manual for that DMA offset (`U-C0XX`).
- [PARTIAL] **D23.** Load / save (FDC `0xE8`, SCSI `0xA0`, IRQ3 demux). MAME’s 72065 map covers device offsets 0 and 1 only, so `0xEA` is outside it; `OUT 0xE8,0x0E` is that model’s motor auxiliary command (`notes/d23_load_save.md` §6). Missing: the IRQ3 pin (`U-V53A`) and a µPD72069 datasheet not in this tree.
- [ ] **D24.** MIDI (TE7774 `0xC0-0xDF`).
- [PARTIAL] **D25.** Error, cancel, and recovery paths (system-error text is
      walker-established; path semantics stay open). The MAME key
      matrix has no key named Cancel. Missing observations:
      panel Cancel (`U-PANEL-ROM`, ROM not in this tree) and pixels on the
      glass (`U-LC7981`).
- [ ] **D26.** Option-dependent behavior only when a consumer exists. Remaining: unowned In play/Count in in refused gap `[0x484C9, 0x4A458)`, unowned MIDI stores at `0x57607`, Tap Tempo at `0x4D857`.

---

## G5 — Platform (named hardware boundaries)

- [PARTIAL] **P1.** Panel µPD78C10 AM27C256 (`U-PANEL-ROM`). MAME’s
      driver records the name, CRC `b0b783d3`, and SHA1
      `a6001618…`. The device sources do not contain the bytes.
      Missing observation: that dump.
- [PARTIAL] **P2.** IC25/IC29/IC31 18CV8 fusemaps and schematic sheets
      (`U-PAL`, `U-C0XX`). MAME’s “clock verified by schematic”
      comment is not the sheets. Missing: service schematic set / JEDEC.
- [PARTIAL] **P3.** LC7981 glass and the seven AX=0 register pairs
      (`U-LC7981`, `U-PHYS`). MAME’s HD61830 model names those
      seven commands (D3-glass). It is not a manual, and there is
      no frame. Missing: an LC7981 or HD61830 manual, and one
      captured glass frame.
- [PARTIAL] **P4.** TE7774 register map (`U-TE7774`). MAME’s
      `te7774.cpp` says the register bits are complete guesses
      and forces 31250 baud, 8N1. The code tests control-1 bit 0
      (TX enable) and bit 2 (RX enable) only. That file is not a
      datasheet. Missing: a TE7774 datasheet in this tree.
- [PARTIAL] **P5.** IRQ / timer timing, SMPTE, panel IPC on the wire
      (`U-PHYS`). MAME wires timer outs to IRQ0–2, FDC-or-SCSI to
      IRQ3, TE7774 TXRDY to IRQ4, RXRDY 0–2 to IRQ5, and RXRDY 3
      to IRQ7. IRQ6 is unwired. The header’s SMPTE-on-IRQ6 claim
      is not what the config runs. Missing: one timed capture.
- [PARTIAL] **P6.** µPD70236 vs 70236A marking (`U-V53A`).
      `mpc3000()` constructs `V53A`. `v53a_device` adds no methods
      over `v53_device`, so the emulator does not distinguish the
      two dies. Missing: a chip photo.
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
- [x] **R3.** Ghidra project only after `BRKXA`/`RETXA` decode is checked
      against file `0x7AC1C`. **PROVEN:** file `0x7AC1C` =
      `0F E0 11` (`BRKXA 0x11` at `FAC0:001C`); verifier check
      `BRKXA 0x11` and `tests.test_boot_slice` (`test_brkxa_continue_in_place`,
      `test_v53_decode_brkxa_retxa`).
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
