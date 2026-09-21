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
because the dests `CALLN` mid-hole IPs. `CEBF:026A` and
`BE1A:01FB` are 4-IP tables owned the same way (`BX<=3` then
`SHL 1`). `BE1A:026C` adds three packed tables at `062F` /
`0637` / `0641`; dests fill the two walk holes and are not
BFS seeds. `C303:0004` is the same pattern after `C2E6`
(`0BCC` 14 IPs, `0BE8` 19 IPs). `C303:0C0E` / `0C64`
are the packed leftover cdecls after those tables.
`B3FD:0006` is the same
pattern after `B3ED` (`0871` 14 IPs, `088D` 13 IPs,
`08A7` 14 IPs). `B3FD:08C3` / `0953` / `097B` / `09AC` /
`09E2` / `0A2F` are the packed leftover cdecls after
those tables. `B060:0715` / `086E` sit after the `0701`
table; `0982`..`0A4A` sit after owned `08E6`; `0C6C` /
`0CBF` sit after the `0C58` table.
Owned `CALLF` dests that sit at hole-starts and walk
through `RETF` are seed-only: `B292:0008`, `B2F1:0002`,
`B354:05F8`, `E4FA:000C`, `E582:0000`, `E676:000D`,
`E7E0:000A`, `EB1A:0002`, `EBC8:0003`. Leftovers after
`B292` / `B2F1` are far dests `B2A0:0007` / `B31B:0007`
(`CALLF` from `B060`). `E4FA:0170` is the leftover
`CALLN` after `E4FA:000C`. `B060:0A7B` now has those
far callers. `B060:0D04` is the hole-start
after `0CBF` (`CALLF` `EBC8:00B0`).
`B20A:0004` is the hole-start after the
1-byte `0xFF` at `0x320A3` (`CALLF` `EB1A`).
`D6E0:008B` is a 42-byte hole-exact AMX
thunk (`CALLF` `C303:029C`). `E398:0009`
is the hole-start through `RETF`
(`CALLF` `C2E6:01B9`). Packed leftovers
`E398:0119` / `01F0` / `0366` / `0386` /
`03BD` / `045A` and far dest `E3E7:0008`
fill `[0x63A99, 0x63EA5)`.
`DCA2:0166` / `0371` / `03C9` are the
hole-start chain after `0154` (`CALLN`
`DCA2:0019`); they close `[0x5CB86, 0x5CE02)`.
`D61A:000A` is not a BFS seed. `B261:000A` is the mid-gap
`CALLF` dest (`9A` at `0x30A85` / `0x30C4D` in owned
`B060` prefix code) at file `0x3261A`, +0x1A into
`[0x32600, 0x32811)`. Walk is hole-exact through
`0200 RETF`. `0273` is the leftover `CALLN` after
already-owned `0201`. Prefix cdecls at
`[0x32600, 0x3261A)` have no `9A` and stay unowned.
Do not BFS `000A`. Owned mid-gap `CALLF` dests
`E59E:0006` / `0035` and `E5A8:0003` / `0030`
(`9A` from owned `E398`) walk through `RETF` and
fill `[0x659E6, 0x65A79)` + `[0x65A83, 0x65AF1)`.
`E582:013A` / `E59E:0099` stay unowned (no owned
`9A`). `C303:0D47` is the leftover after `0C64`
(`9A` at `0x34274` / `0x42D97`). `C303:0CEE` has
no owned caller. Further mid-gap owned `CALLF`
dests `E12D:0009`, `E07A:0004`, `E6D1:0001`,
`E739:030C`, and `E661:0006`/`0095` walk through
`RETF` (callers `E398` / `B3FD` / `E7E0`). Their
hole prefixes stay unowned. Packed `CALLN`
leftovers from owned bodies: `C303:0CEE`
closes `[0x43D1E, 0x43D77)`; `C303:0D76`..`11C4`
closes `[0x43DA6, 0x44259)`; `B060:0044`..`02D6`
fills `[0x30644, 0x3095D)` (20-byte prefix
`0030` stays unowned); `B3FD:0A96` is the
hole-start after `0A2F`. Named `C44E` `00B8`
`CALLN` dests `0119` / `0485` / `070F` plus
leftovers `00C2` / `06B6` fill
`[0x445A2, 0x4479F)` and `[0x44965, 0x44C8D)`.
`02BF` stays unowned (`JMP CS:[BX+0459]` /
`[BX+044D]`). `C887:09AC` stays unowned
(mid-hole in the 8203-byte gap). `D9F2:0072`
is the hole-exact leftover after extra
`000C` (`9A` at `C44E:020D`). Isolated
`0xFF` at `0x59FCD` is auto-align. Do not
BFS those dests. A `55 8B EC` prologue still
does not accept a dest as an entry.

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
| `[0x30D15, 0x30E6E)` | code — `B060:0715` cdecl through `RETF`; `CALLN` `B060:05E8`/`0601`/`0611` |
| `[0x30E6E, 0x30EE6)` | code — `B060:086E` cdecl through `RETF`; `CALLN` `B060:0769` |
| `[0x30F82, 0x30FB1)` | code — `B060:0982` cdecl through `RETF`; `CALLN` `B060:07B1` |
| `[0x30FB1, 0x30FE4)` | code — `B060:09B1` cdecl through `RETF`; `CALLN` `B060:098D` |
| `[0x30FE4, 0x31004)` | code — `B060:09E4` cdecl through `RETF`; `CALLN` `B060:09A9` |
| `[0x31004, 0x3104A)` | code — `B060:0A04` cdecl through `RETF`; `CALLN` `B060:099B` |
| `[0x3104A, 0x3107B)` | code — `B060:0A4A` cdecl through `RETF`; `CALLN` `B060:07D7` |
| `[0x31258, 0x3126C)` | data — `B060` `JMP CS:[BX+0C58]` 10 near IPs |
| `[0x3126C, 0x312BF)` | code — `B060:0C6C` cdecl through `RETF`; `CALLF` `C303:04A9` |
| `[0x312BF, 0x31304)` | code — `B060:0CBF` cdecl through `RETF`; `CALLF` `BE1A:04D1`/`04E1` |
| `[0x30644, 0x3095D)` | code — `B060:0044` through `02D6` packed `CALLN` leftovers through `RETF` |
| `[0x31304, 0x31370)` | code — `B060:0D04` through `RETF`; `CALLF` `EBC8:00B0` |
| `[0x320A4, 0x321AF)` | code — `B20A:0004` cdecl through `RETF`; `CALLF` `EB1A:0155`/`025F`/`030D` |
| `[0x56E8B, 0x56EB5)` | code — `D6E0:008B` `ES=DS` / AMX `0725`/`06B9` through `RETF`; `CALLF` `C303:029C` |
| `[0x63989, 0x63A99)` | code — `E398:0009` through `RETF`; `CALLF` `C2E6:01B9` |
| `[0x63A99, 0x63B70)` | code — `E398:0119` cdecl through `RETF`; `CALLN` `E398:0091` |
| `[0x63B70, 0x63CE6)` | code — `E398:01F0` cdecl through `RETF`; `CALLF` `C2E6:00EC` |
| `[0x63CE6, 0x63D06)` | code — `E398:0366` through `RETF`; `CALLF` `C2E6:0126` |
| `[0x63D06, 0x63D3D)` | code — `E398:0386` through `RETF`; `CALLN` `E398:0065` |
| `[0x63D3D, 0x63DDA)` | code — `E398:03BD` cdecl through `RETF`; `CALLN` `E398:00AB` |
| `[0x63DDA, 0x63E78)` | code — `E398:045A` cdecl through `RETF`; `CALLN` `E398:0351` |
| `[0x63E78, 0x63EA5)` | code — `E3E7:0008` cdecl through `RETF`; `CALLF` `E4FA:0025` |
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
| `[0x55EF4, 0x55F04)` | data — `D5DD` `MOV BX,CS:[SI+0124]` / `[SI+012C]` two 4-word arrays; `CALLN` `D5DD:0032` |
| `[0x5C5B2, 0x5C5CA)` | data — `DC5B` `MOV BX,CS:[BX+0002]` 12 words; `CALLF` `DA9B:0002` |
| `[0x5C6E2, 0x5C702)` | data — `DC6E` `MOV DX,CS:[BX+0002]` 16 mask words (`(n&0xF)<<1`); `CALLF` `DC23:000A` |
| `[0x6B0B2, 0x6B0B6)` | data — `EB0B` `MOV AX/DX,CS:[0002]`/`[0004]` 32-bit dividend; `CALLF` `DC08:0046` |
| `[0x7A094, 0x7A09A)` | data — `F800` `MOV AX,CS:[BX+2094]` 3 words (`BL<3`) |
| `[0x31B32, 0x31B36)` | code — `B1B1:0022` `MOV AX,[1D1A]` / `RETF`; `CALLF` `DE5C:0040` |
| `[0x3261A, 0x32811)` | code — `B261:000A` cdecl through `RETF`; `CALLF` `B060:0A7B`/`08E6`/`0715`; dest sits +0x1A into the post-task-1 gap |
| `[0x32883, 0x32922)` | code — `B261:0273` cdecl through `RETF`; `CALLN` from `000A`; `CALLF` `B060:08E6` |
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
| `[0x32928, 0x32A07)` | code — `B292:0008` cdecl through `RETF`; `CALLF` `B060:06A1` |
| `[0x32A07, 0x32BA3)` | code — `B2A0:0007` cdecl through `RETF`; `CALLF` `B060:0691` |
| `[0x32F12, 0x331B7)` | code — `B2F1:0002` cdecl through `RETF`; `CALLF` `B060:0661` |
| `[0x331B7, 0x333C4)` | code — `B31B:0007` cdecl through `RETF`; `CALLF` `B060:063D` |
| `[0x3107B, 0x310D9)` | code — `B060:0A7B` cdecl through `RETF`; `CALLF` `B2A0:0007`/`B31B:0007` |
| `[0x65110, 0x651D3)` | code — `E4FA:0170` cdecl through `RETF`; `CALLN` `E4FA:0167` |
| `[0x33B38, 0x33B8E)` | code — `B354:05F8` cdecl through `RETF`; `CALLF` `C303:00D4` |
| `[0x64FAC, 0x65110)` | code — `E4FA:000C` cdecl through `RETF`; `CALLF` `C303:06D1` |
| `[0x65820, 0x6595A)` | code — `E582:0000` cdecl through `RETF`; `CALLF` `B3FD:0615` |
| `[0x659E6, 0x65A15)` | code — `E59E:0006` through `RETF`; `CALLF` from `E398:0036` |
| `[0x65A15, 0x65A79)` | code — `E59E:0035` through `RETF`; `CALLF` `E521:0006`/`DF4F:0009`/`E566:000A` |
| `[0x65A83, 0x65AB0)` | code — `E5A8:0003` through `RETF`; `CALLF` from `E398:0031` |
| `[0x65AB0, 0x65AF1)` | code — `E5A8:0030` through `RETF`; `CALLF` `EB5B:0087` |
| `[0x607A4, 0x608C1)` | code — `E07A:0004` cdecl through `RETF`; `CALLF` from `E398:0055` |
| `[0x612D9, 0x613B0)` | code — `E12D:0009` cdecl through `RETF`; `CALLF` from `E398:0394` |
| `[0x66616, 0x666A5)` | code — `E661:0006` cdecl through `RETF`; `CALLF` from `B3FD` |
| `[0x666A5, 0x666FC)` | code — `E661:0095` cdecl through `RETF`; `CALLF` from `B3FD:0480` |
| `[0x66D11, 0x66D8B)` | code — `E6D1:0001` cdecl through `RETF`; `CALLF` from `E398:0206` |
| `[0x6769C, 0x67725)` | code — `E739:030C` cdecl through `RETF`; `CALLF` from `E7E0:0043` |
| `[0x6676D, 0x66883)` | code — `E676:000D` cdecl through `RETF`; `CALLF` `B3FD:0042` |
| `[0x67E0A, 0x67F57)` | code — `E7E0:000A` cdecl through `RETF`; `CALLF` `CEBF:021C` |
| `[0x6B1A2, 0x6B4F2)` | code — `EB1A:0002` cdecl through `RETF`; `CALLF` `DE5C:0496` |
| `[0x6BC83, 0x6BD59)` | code — `EBC8:0003` cdecl through `RETF`; `CALLF` `C44E:0031` |
| `[0x5BCAD, 0x5BCD4)` | code — `DB28:0A2D` `ES:[BX]` init through `RETF`; `CALLN` `DB28:077B` |
| `[0x7A0F7, 0x7A0FA)` | code — `F800:20F7` `POP CX`/`PUSH CS`/`PUSH CX`; `CALLN` `F800:2687`/`26A8` |
| `[0x31C00, 0x31C6F)` | code — `B1BC:0040` `LES DI`/`SCASB` count through `RETF`; `CALLN` `B1BC:0382` |
| `[0x5CB74, 0x5CB79)` | code — `DCA2:0154` `MOV AL,0x59` / `JMP 0016`; `CALLF` `DE5C:055B` |
| `[0x5CB86, 0x5CD91)` | code — `DCA2:0166` through `RETF`; `CALLN` `DCA2:0019` |
| `[0x5CD91, 0x5CDE9)` | code — `DCA2:0371` through `RETF`; `CALLN` `DCA2:0361` |
| `[0x5CDE9, 0x5CE02)` | code — `DCA2:03C9` through `RET`; `CALLN` `DCA2:0187` |
| `[0x444B9, 0x444E5)` | code — `C425:0269` cdecl through `RETF`; `CALLN` `C425:0220` |
| `[0x7A42D, 0x7A45B)` | code — `F800:242D` copy through `RET 8`; 6 `CALLN` from `24A5`.. |
| `[0x33EDF, 0x33FD6)` | code — `B3ED:000F` cdecl through `RETF`; `CALLF` `C425:01B5` |
| `[0x33FD6, 0x34841)` | code — `B3FD:0006` through three `JMP CS:[BX]`; `CALLF` `C425:011F` |
| `[0x34841, 0x3485D)` | data — `B3FD` `JMP CS:[BX+0871]` 14 near IPs (`BX<=0x0D` then `SHL 1`) |
| `[0x3485D, 0x34877)` | data — `B3FD` `JMP CS:[BX+088D]` 13 near IPs (`BX<=0x0C` then `SHL 1`) |
| `[0x34877, 0x34893)` | data — `B3FD` `JMP CS:[BX+08A7]` 14 near IPs (`BX<=0x0D` then `SHL 1`) |
| `[0x34893, 0x34923)` | code — `B3FD:08C3` cdecl through `RETF`; `CALLN` `B3FD:029E`/`03B7` |
| `[0x34923, 0x3494B)` | code — `B3FD:0953` cdecl through `RETF`; `CALLN` `B3FD:03CA` |
| `[0x3494B, 0x3497C)` | code — `B3FD:097B` cdecl through `RETF`; `CALLN` `B3FD:025A`/`032E` |
| `[0x3497C, 0x349B2)` | code — `B3FD:09AC` cdecl through `RETF`; `CALLN` `B3FD:011D`/`0345` |
| `[0x349B2, 0x349FF)` | code — `B3FD:09E2` cdecl through `RETF`; `CALLN` `B3FD:05FD`/`06A2` |
| `[0x349FF, 0x34A66)` | code — `B3FD:0A2F` cdecl through `RETF`; `CALLN` `B3FD:052B`/`05BB` |
| `[0x34A66, 0x34A9C)` | code — `B3FD:0A96` through `RETF`; `CALLN` from `B3FD:0500` |
| `[0x42D0C, 0x42E67)` | code — `C2D0:000C` cdecl through `RETF`; `CALLF` `C425:012F` |
| `[0x42E67, 0x43034)` | code — `C2E6:0007` cdecl through `RETF`; `CALLF` `C425:019B` |
| `[0x43034, 0x43BFC)` | code — `C303:0004` through two `JMP CS:[BX]`; `CALLF` `C425:0106` |
| `[0x43BFC, 0x43C18)` | data — `C303` `JMP CS:[BX+0BCC]` 14 near IPs (`BX<=0x0D` then `SHL 1`) |
| `[0x43C18, 0x43C3E)` | data — `C303` `JMP CS:[BX+0BE8]` 19 near IPs (`BX<=0x12` then `SHL 1`) |
| `[0x43C3E, 0x43C94)` | code — `C303:0C0E` cdecl through `RETF`; `CALLN` `C303:0465`/`04D3` |
| `[0x43C94, 0x43D1E)` | code — `C303:0C64` cdecl through `RETF`; `CALLN` `C303:067B`/`09CF`/`09F9` |
| `[0x43D1E, 0x43D77)` | code — `C303:0CEE` through `RETF`; `CALLN` from `C303:04DB` |
| `[0x43D77, 0x43DA6)` | code — `C303:0D47` through `RETF`; `CALLF` `B1B1:0026`/`005B`/`EA97:000E` |
| `[0x43DA6, 0x44259)` | code — `C303:0D76` through `11C4` packed `CALLN` leftovers through `RETF` |
| `[0x444E5, 0x44535)` | code — `C44E:0005` through `JMP CS:[BX+00B8]`; `CALLF` `C425:01BF` |
| `[0x44535, 0x44598)` | code — `C44E` `00B8` dests `0055`..`0079` plus shared `RETF` `00B3` |
| `[0x44598, 0x445A2)` | data — `C44E` `JMP CS:[BX+00B8]` 5 near IPs (`BX<=4` then `SHL 1`) |
| `[0x445A2, 0x445F9)` | code — `C44E:00C2` cdecl through `RETF`; `CALLN` from `C44E:01C5` |
| `[0x445F9, 0x4479F)` | code — `C44E:0119` cdecl through `RETF`; `CALLN` from `C44E:0057` |
| `[0x44965, 0x44B96)` | code — `C44E:0485` cdecl through `RETF`; `CALLN` from `C44E:0069` |
| `[0x44B96, 0x44BEF)` | code — `C44E:06B6` cdecl through `RETF`; `CALLN` from `C44E:05ED` |
| `[0x44BEF, 0x44C8D)` | code — `C44E:070F` cdecl through `RETF`; `CALLN` from `C44E:0072` |
| `[0x59F92, 0x59FCD)` | code — `D9F2:0072` cdecl through `RETF`; `CALLF` from `C44E:020D` |
| `[0x4EBF8, 0x4ED2E)` | code — `CEBF:0008` through `JMP CS:[BX+026A]`; `CALLF` `C425:01D8` |
| `[0x4ED2E, 0x4EDA2)` | code — `CEBF` `026A` dests `013E`/`0175`/`0189` |
| `[0x4EDA2, 0x4EE5A)` | code — `CEBF` shared `01B2` through `RETF` |
| `[0x4EE5A, 0x4EE62)` | data — `CEBF` `JMP CS:[BX+026A]` 4 near IPs (`BX<=3` then `SHL 1`) |
| `[0x3E1A2, 0x3E292)` | code — `BE1A:0002` through `JMP CS:[BX+01FB]`; `CALLF` `C425:01F6` |
| `[0x3E292, 0x3E335)` | code — `BE1A` `01FB` dests `00F2`/`0105`/`0131`/`0185` |
| `[0x3E335, 0x3E39B)` | code — `BE1A` shared `0195` through `RETF` |
| `[0x3E39B, 0x3E3A3)` | data — `BE1A` `JMP CS:[BX+01FB]` 4 near IPs (`BX<=3` then `SHL 1`) |
| `[0x3E3A3, 0x3E3CB)` | code — `BE1A:0203` cdecl through `RETF`; `CALLN` `0070`/`010C`/`0160` |
| `[0x3E3CB, 0x3E40C)` | code — `BE1A:022B` cdecl through `RETF`; `CALLN` `0129`/`017D`/`018F` |
| `[0x3E40C, 0x3E7CF)` | code — `BE1A:026C` through three `JMP CS:[BX]`; `CALLF` `C425:0200` |
| `[0x3E7CF, 0x3E7D7)` | data — `BE1A` `JMP CS:[BX+062F]` 4 near IPs (`BX<=3` then `SHL 1`) |
| `[0x3E7D7, 0x3E7E1)` | data — `BE1A` `JMP CS:[BX+0637]` 5 near IPs (`BX<=4` then `SHL 1`) |
| `[0x3E7E1, 0x3E7E9)` | data — `BE1A` `JMP CS:[BX+0641]` 4 near IPs (`BX<=3` then `SHL 1`) |

---

## What this note does *not* prove

- Destinations selected by the 19 indirect dests (`BX` domain).
- `CALL [rm]` tables (BIOS and FAC0).
- Which IP `BX` selects at the six `JMP CS:[BX+disp]` sites.
  The 40 bounded table dests are owned; the 25 indirect dests
  stay prefix-only.
- That a bounded cdecl body is fully owned (D17).
- The later empty-queue wake (`U-AMX-WAIT`).
