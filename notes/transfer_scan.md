# Transfer inventory from established entries

**Image:** Vailixi OS 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D16 for the 143 D15 entries. Every local exit is classified.
New CALLF/CALLN targets are named candidates, not accepted as code.
Indirect `[rm]` stays UNDETERMINED (no jump-table ownership).

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

The 74+42 new dests are **candidates**. A `55 8B EC` prologue does
not accept them (D15 rule). D18+ / a later entry pass may promote
them after investigation.

---

## 3. Indirect exits

Six `JMP CS:[BX+disp16]` switch-shaped sites, all `2E FF A7 iw`:

`B1BC:01EE`, `D5F3:000E`, `DB28:000D` / `01E1` / `0465`, `DCF0:0006`.

Ten `CALL [rm]` sit in BIOS (`F800:0364`, `16AA`, `1752`, `19B3`,
`1B36`), `B354:02BB`, and two FAC0 walks (`001F`, `0134`). The
**slot** is named by file and bytes. The **table** is not owned.
**UNDETERMINED.**

---

## Byte ownership

Instruction bytes of each D16 `follow_entry` walk are `code`.
Holes inside a min-max span are not claimed. The ledger unions
those runs; do not treat a walk’s `[min, max)` as one range.

| File range | Owner |
|------------|-------|
| `[0x7B23A, 0x7B240)` | code — idle `NOP*4` / `JMP` (already inside AMX) |
| `[0x56E40, 0x56E41)` | code — specimen `NOP` between owned ranges |

---

## What this note does *not* prove

- Instruction bounds for the 74+42 new callees.
- Jump-table contents at the six `CS:[BX+disp]` sites.
- That a bounded cdecl body is fully owned (D17).
- The later empty-queue wake (`U-AMX-WAIT`).
