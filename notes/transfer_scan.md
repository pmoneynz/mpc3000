# Transfer inventory from established entries

**Image:** Vailixi OS 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D16 for the 143 D15 entries. Every local exit is classified.
New CALLF/CALLN targets are named candidates, not accepted as entries.
Six `JMP CS:[BX+disp]` tables are owned as data where a hole or
an owned-code edge bounds the IP list. `D510` port words are in
[`pgr_live_after_amx.md`](pgr_live_after_amx.md).

Reproduction: `python3 tools/transfer_scan.py --write` then
`python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | From each established entry, walk a local CFG and classify every exit |
| Observable | 143 walks; 128 bounded; 14 indirect; 1 idle loop; 0 JMPF to a new CS:IP |
| Inputs | D15 unique `CS:IP`; `follow_entry` (does not enter JMPF/CALLF or another established IP) |
| Outputs | `analysis/transfer_scan.json` |
| Confidence | Exit kinds and idle/put-string/reset specimens **PROVEN**. Indirect table contents **UNDETERMINED** |
| Hardware deferred | None |

File = `(CS<<4+IP)&0x7FFFF`. The walk does not enter a far call or a
far jump. Fallthrough into another established `CS:IP` is a resolved
transfer (`to_established`).

---

## 1. Status of the 143

| Status | n | Meaning |
|--------|--:|---------|
| bounded | 128 | Every exit is return, JMPF to an established IP, CALL, XA, or fall into an established IP |
| indirect | 14 | At least one `JMP [rm]` / `CALL [rm]` |
| loop | 1 | `FB00:023A` `STI`-less `NOP*4` / `JMP 023A` (empty-queue idle) |

No walk hit the 800-instruction cap. No `UNKNOWN_0F`. Every `JMPF`
dest is already in D15 (reset -> stub -> FAC0; FAC0 `CX=0` ->
`B000:00DF`).

Specimens:

| CS:IP | File | n | Exits | Status |
|-------|------|--:|-------|--------|
| `FFFF:0000` | `0x7FFF0` | 1 | `JMPF FFF0:0000` | bounded |
| `FB00:013E` | `0x7B13E` | 3 | `CALLN 01EA` then `JMP 013E` | bounded |
| `FB00:023A` | `0x7B23A` | 5 | none (self-`JMP`) | loop |
| `D9BD:0009` | `0x59BD9` | 13 | 3 `CALLF` (`E937`, `B060`, `D9B5`); `JMP 000E` | bounded |
| `B1B1:005B` | `0x31B6B` | 21 | `RETF` at `0x31B90` | bounded |

Task 6 never `RETF`s. That is a resolved loop, not a missing exit
(D7). The idle spin is the one loop with no CALL/RETF.

---

## 2. Exit census

| Kind | n | Tag |
|------|--:|-----|
| `callf` | 224 | dest `CS:IP` named; 74 dests are not in D15 |
| `return` | 162 | `RETF`/`RET`/`IRET`/`RETFN` |
| `calln` | 140 | dest named; 42 dests are not in D15 |
| `to_established` | 12 | fallthrough or near jump into a D15 IP |
| `call_indirect` | 10 | `CALL [rm]` |
| `indirect` | 6 | `JMP CS:[BX+disp16]` (`2E FF A7 iw`) |
| `jmpf` | 4 | dest established |
| `brkxa` | 3 | `0F E0 ib` |
| `retxa` | 2 | `0F F0 ib` |

The 74+42 new dests are **candidates** as *entries* (D15). A
bounded CALL dest on a consumer chain from a D16 entry or a
bounded switch-table dest is owned as *code* (D17). 25 hole- or
edge-bounded near-IP tables (JMP/CALL CS:[BX+disp], INT 40) seed that
BFS. 135 of 187 table dests are bounded; 52 stay prefix-only.
`C44E:00B8` is a 5-IP table owned as data; it is not a BFS seed
because the dests `CALLN` mid-hole IPs.
`D61A:000A` is not a BFS seed. A `55 8B EC` prologue still does
not accept a dest as an entry.

---

## 3. Indirect exits

Six `JMP CS:[BX+disp16]` switch-shaped sites, all `2E FF A7 iw`:

`B1BC:01EE`, `D5F3:000E`, `DB28:000D` / `01E1` / `0465`, `DCF0:0006`.

Ten `CALL [rm]` sit in BIOS (`F800:0364`, `16AA`, `1752`, `19B3`,
`1B36`), `B354:02BB`, and two FAC0 walks (`001F`, `0134`). The
**slot** is named by file and bytes. All six `JMP CS:[BX+disp]`
tables of those sites are owned: a hole or an owned-code edge
bounds an in-CS IP list. Indirect dests are not promoted; their
decoded instruction prefixes are owned as code.

---

## Byte ownership

Instruction bytes of each D16 `follow_entry` walk are `code`.
Holes inside a min-max span are not claimed. The ledger unions
those runs; do not treat a walk’s `[min, max)` as one range.

| File range | Owner |
|------------|-------|
| `[0x7B23A, 0x7B240)` | code — idle `NOP*4` / `JMP` (already inside AMX) |
| `[0x56E40, 0x56E41)` | code — specimen `NOP` between owned ranges |
| `[0x59BC3, 0x59BD9)` | code — `D9B5:0073` bounded CALLF dest through `RETF` |
| `[0x7989C, 0x798CA)` | code — `F800:189C` bounded CALLN dest through `RET` |
| `[0x55F64, 0x55F7A)` | data — `D5F3` `JMP CS:[BX+0034]` 11 near IPs |
| `[0x5B447, 0x5B461)` | data — `DB28` `JMP CS:[BX+01C7]` 13 near IPs |
| `[0x31FE2, 0x31FFC)` | data — `B1BC` `JMP CS:[BX+0422]` 13 near IPs |
| `[0x5B56B, 0x5B585)` | data — `DB28` `JMP CS:[BX+02EB]` 13 near IPs |
| `[0x5BC6B, 0x5BC87)` | data — `DB28` `JMP CS:[BX+09EB]` 14 near IPs |
| `[0x5D35E, 0x5D376)` | data — `DCF0` `JMP CS:[BX+045E]` 12 near IPs |
| `[0x561AA, 0x561AF)` | code — `D61A:000A` `0347` IVT[9] plant prefix (`CALL 0157`) |
| `[0x319CE, 0x319FE)` | code — `B19C:000E` hop-2 cdecl dest through `RETF` |
| `[0x5D9AE, 0x5DBBC)` | code — `DD9A:000E` hop-1 CALLF dest of `D5F3:018A` through `RETF` |
| `[0x79E81, 0x79E97)` | code — `F800:1E81` hop-1 CALLN dest of INT 40 `AH<=7` through `RET` |
| `[0x5614D, 0x561A9)` | code — `D5F3:021D` hop-1 CALLN dest of `D5F3` switch IPs through `RET` |
| `[0x30D01, 0x30D15)` | data — `B060` `JMP CS:[BX+0701]` 10 near IPs |
| `[0x31258, 0x3126C)` | data — `B060` `JMP CS:[BX+0C58]` 10 near IPs |
| `[0x44483, 0x444B9)` | data — `C425` `JMP CS:[BX+0233]` 27 near IPs |
| `[0x50785, 0x5078D)` | data — `CFC6` `JMP CS:[BX+0B25]` 4 near IPs |
| `[0x53CAC, 0x53CBC)` | data — `D3A7` `JMP CS:[BX+023C]` 8 near IPs |
| `[0x559AA, 0x559BA)` | data — `D547` `JMP CS:[BX+053A]` 8 near IPs (`(nibble<<1)&0xE`) |
| `[0x559BA, 0x559C5)` | code — `D547:054A` slot-7 dest through fall into `0555` |
| `[0x559D1, 0x559F1)` | data — `D547` `JMP CS:[DI+0561]` 16 near IPs (`(AX&0xF)<<1`) |
| `[0x58BCA, 0x58BDC)` | data — `D8BC` `JMP CS:[BX+000A]` 9 near IPs |
| `[0x59C95, 0x59C9D)` | data — `D9C0` `JMP CS:[BX+0095]` 4 near IPs |
| `[0x5B24D, 0x5B25F)` | data — `DAF2` `JMP CS:[BX+032D]` 9 near IPs |
| `[0x5CA78, 0x5CA84)` | data — `DCA2` `JMP CS:[BX+0058]` 6 near IPs |
| `[0x5EE45, 0x5EE8D)` | data — `DE5C` `JMP CS:[BX+0885]` 36 near IPs |
| `[0x5EE8D, 0x5EE9B)` | data — `DE5C` `JMP CS:[BX+08CD]` 7 near IPs |
| `[0x6B7E2, 0x6B7EC)` | data — `EB74` `JMP CS:[BX+00A2]` 5 near IPs |
| `[0x6BE65, 0x6BE6F)` | data — `EBC8` `JMP CS:[BX+01E5]` 5 near IPs |
| `[0x553FF, 0x55417)` | data — `D52A` `CALL CS:[BX+015F]` 12 near IPs |
| `[0x55420, 0x55430)` | data — `D52A` `CALL CS:[BX+0180]` 8 near IPs |
| `[0x5660C, 0x56618)` | data — `D61A` `JMP CS:[BX+046C]` 6 near IPs |
| `[0x7B989, 0x7B996)` | code — `FB93:0059` `0347` IVT[8] plant (`INT 42` / `OUT 0xC010,0x60` / `IRET`) |
| `[0x79906, 0x79946)` | data — `F800:1906` 16×4-byte records (`LEA SI,[BX+1906]` / `OUTSW`) |
| `[0x5DBBC, 0x5DBC8)` | data — `DD9A` `MOV CX,CS:[SI+021C]` 6 words |
| `[0x5DBCF, 0x5DBEF)` | data — `DD9A` `MOV BX,CS:[BX+022F]` 16 mask words |
| `[0x5DBEF, 0x5DC0F)` | data — `DD9A` `MOV BX,CS:[BX+024F]` 16 mask words |
| `[0x7A094, 0x7A09A)` | data — `F800` `MOV AX,CS:[BX+2094]` 3 words (`BL<3`) |
| `[0x31B32, 0x31B36)` | code — `B1B1:0022` `MOV AX,[1D1A]` / `RETF`; `CALLF` `DE5C:0040` |
| `[0x32922, 0x32928)` | code — `B261:0312` `MOV [E748],0` / `RETF`; `CALLF` `B060:03B7` |
| `[0x670C1, 0x670CB)` | code — `E704:0081` `PUSH CS` / `CALL 0007` / `CALLF E614:0008` / `RETF` |
| `[0x65815, 0x65820)` | code — `E56F:0125` CLI snapshot through `RETF`; `CALLF` `DE5C:0489` |
| `[0x66148, 0x66174)` | code — `E614:0008` flag thunk through `RETF`; `CALLF` from `E704:0081` |
| `[0x66908, 0x66920)` | code — `E688:0088` compare through `RETF`; `CALLF` `DE5C:04E6` |
| `[0x53A7C, 0x53A84)` | data — `D3A7` `OR AL,CS:[BX+000C]` 8 bit masks (`BX<=7`) |
| `[0x53AAA, 0x53AC8)` | code — `D3A7:003A` `OUT 0xA4` pulse / `CALL FB00:0484` / `RET` |
| `[0x53AC8, 0x53B20)` | code — `D3A7:0058` `0xC0xx` I/O through `RET`; `CALLN` from `00B0` |
| `[0x53B20, 0x53B78)` | code — `D3A7:00B0` port poll / `CALL 0058` / `RET`; six `CALLN` sites |
| `[0x32DAF, 0x32E79)` | code — `B2DA:000F` cdecl through `RETF`; `CALLF` `B060:0681` |
| `[0x5BCAD, 0x5BCD4)` | code — `DB28:0A2D` `ES:[BX]` init through `RETF`; `CALLN` `DB28:077B` |
| `[0x7A0F7, 0x7A0FA)` | code — `F800:20F7` `POP CX`/`PUSH CS`/`PUSH CX`; `CALLN` `F800:2687`/`26A8` |
| `[0x31C00, 0x31C6F)` | code — `B1BC:0040` `LES DI`/`SCASB` count through `RETF`; `CALLN` `B1BC:0382` |
| `[0x5CB74, 0x5CB79)` | code — `DCA2:0154` `MOV AL,0x59` / `JMP 0016`; `CALLF` `DE5C:055B` |
| `[0x444B9, 0x444E5)` | code — `C425:0269` cdecl through `RETF`; `CALLN` `C425:0220` |
| `[0x7A42D, 0x7A45B)` | code — `F800:242D` copy through `RET 8`; 6 `CALLN` from `24A5`.. |
| `[0x33EDF, 0x33FD6)` | code — `B3ED:000F` cdecl through `RETF`; `CALLF` `C425:01B5` |
| `[0x42D0C, 0x42E67)` | code — `C2D0:000C` cdecl through `RETF`; `CALLF` `C425:012F` |
| `[0x42E67, 0x43034)` | code — `C2E6:0007` cdecl through `RETF`; `CALLF` `C425:019B` |
| `[0x444E5, 0x44535)` | code — `C44E:0005` through `JMP CS:[BX+00B8]`; `CALLF` `C425:01BF` |
| `[0x44535, 0x44598)` | code — `C44E` `00B8` dests `0055`..`0079` plus shared `RETF` `00B3` |
| `[0x44598, 0x445A2)` | data — `C44E` `JMP CS:[BX+00B8]` 5 near IPs (`BX<=4` then `SHL 1`) |

---

## What this note does *not* prove

- Destinations selected by the 19 indirect dests (`BX` domain).
- `CALL [rm]` tables (BIOS and FAC0).
- Which IP `BX` selects at the six `JMP CS:[BX+disp]` sites.
  The 40 bounded table dests are owned; the 25 indirect dests
  stay prefix-only.
- That a bounded cdecl body is fully owned (D17).
- The later empty-queue wake (`U-AMX-WAIT`).
