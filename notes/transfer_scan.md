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
bounded switch-table dest is owned as *code* (D17): 356 dests to
fixpoint (336 from D15, then 20 from the 40 bounded switch IPs);
19 indirect dests stay unowned and stop that chain. 25 switch
dests are themselves indirect; they stay prefix-only.
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

---

## What this note does *not* prove

- Destinations selected by the 19 indirect dests (`BX` domain).
- `CALL [rm]` tables (BIOS and FAC0).
- Which IP `BX` selects at the six `JMP CS:[BX+disp]` sites.
  The 40 bounded table dests are owned; the 25 indirect dests
  stay prefix-only.
- That a bounded cdecl body is fully owned (D17).
- The later empty-queue wake (`U-AMX-WAIT`).
