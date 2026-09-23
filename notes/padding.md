# `0xFF` padding windows

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D13. Every maximal `0xFF` run of 4 or more bytes is classified.
A 1-byte `0xFF` whose both neighbors are already owned is align
padding (same emit pass as the 1-byte `NOP` rule). Other short runs
are immediates or data words (`MOV CX,0xFFFF`, `FFFF:FFFF` already
owned inside a table, and the like). They are not padding windows.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Purpose and boundary for every `0xFF` padding window |
| Observable | 15 runs of length ? 4; 11 are padding; 3 are table terminators; 1 overlaps the reset vector |
| Inputs | Linear image; owner ledger |
| Outputs | Ledger `kind=padding` rows below |
| Confidence | All-`0xFF` bounds **PROVEN**. Isolated 1-byte `0xFF` between owned ranges **PROVEN** as padding. Filler *intent* (unprogrammed ROM vs assembler align) **HYPOTHESIS**. Neighbors that are not yet owned stay gaps |
| Hardware deferred | None |

---

## 1. Padding windows

Already seeded in D12:

| File range | Bytes | Purpose |
|------------|------:|---------|
| `[0x00000, 0x00044)` | 68 | unused low IVT template |
| `[0x0004C, 0x00050)` | 4 | `0xFF` between IVT[12] and IVT[14] |
| `[0x00054, 0x20000)` | 130988 | patch-write bank after IVT[0x14]; see [`patch_space.md`](patch_space.md) |
| `[0x7FF44, 0x7FFF0)` | 172 | wait-stub tail through the reset vector |
| `[0x7FFF5, 0x80000)` | 11 | after `EA FFF0:0000` |

Added this note:

| File range | Bytes | Purpose / boundary |
|------------|------:|--------------------|
| `[0x27C92, 0x27CA0)` | 14 | after the DGROUP image; next 16 bytes are zeros, not padding |
| `[0x27CB0, 0x3000E)` | 33630 | unprogrammed ROM; ends at a C prologue `55 8B EC` |
| `[0x7079C, 0x707A4)` | 8 | after `LEAVE`/`RETF`; then the `F07A` init table |
| `[0x707C8, 0x7800A)` | 30786 | unprogrammed ROM after the `F07A` tail zeros; BIOS `CLI` at `0x7800A`. File `[0x74000, 0x78000)` inside this run is a patch-write bank ([`patch_space.md`](patch_space.md)); the bytes before `0x74000` and `[0x78000, 0x7800A)` are not |
| `[0x7A78E, 0x7AC00)` | 1138 | after a `RETF`; FAC0 reset at `0x7AC00` |
| `[0x7AF6A, 0x7B00C)` | 162 | between I/O tables and the AMX header `EB 40` |
| `[0x7BA01, 0x7FF00)` | 17663 | after a `RETF`; wait-state stub at `0x7FF00` |

---

## 2. `0xFF` runs that are not padding

| File range | Why |
|------------|-----|
| `[0x7B7F2, 0x7B7F6)` | create-table `FFFF:FFFF` terminator (data) |
| `[0x7B7FE, 0x7B802)` | `CS:[003A]` table `FFFF:FFFF` terminator (data) |
| `[0x7B80E, 0x7B812)` | kernel far-ptr table `FFFF:FFFF` terminator (data) |
| `[0x7FFF4, 0x7FFF5)` | high byte of reset `CS=0xFFF0`, then padding |

A 2-byte `FF FF` at `[0x707B6, 0x707B8)` sits after the third `F07A`
record and before zeros. Too short to be a window. **UNDETERMINED**
as table tail vs align. Not claimed.

374 runs of length 2–3 are `FFFF` immediates (`B9 FF FF`, `3D FF FF`,
`C7 06 … FF FF`). **PROVEN** as the encoding class, not as a padding
inventory.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x27C92, 0x27CA0)` | data / padding |
| `[0x27CB0, 0x3000E)` | data / padding |
| `[0x7079C, 0x707A4)` | data / padding |
| `[0x707C8, 0x7800A)` | data / padding |
| `[0x7A78E, 0x7AC00)` | data / padding |
| `[0x7AF6A, 0x7B00C)` | data / padding |
| `[0x707B6, 0x707C8)` | data / F07A tail (`FFFF` + 16 zeros) |
| `[0x7B7FE, 0x7B802)` | data / table terminator |
| `[0x7B80E, 0x7B812)` | data / table terminator |
| `[0x7BA01, 0x7FF00)` | data / padding |
| `[0x31B11, 0x31B12)` | data / padding — specimen 1-byte `0xFF` after `RETF` |

---

## 3. Isolated 1-byte align

`emit_ledger` owns every 1-byte `0xFF` gap between already-owned
ranges as `data`/`padding`. That is the same pass as the 1-byte
`NOP` rule. The 1-byte `CB` at `0x59C05`, `CF` at `0x7ADA3`, and
`58` at `0x7BA00` are not `0xFF` and stay gaps.

---

## What this note does *not* prove

- Why the assembler or burner chose these gaps.
- Code between a `RETF` and the start of a padding window
  (for example the 1-byte `58` at `[0x7BA00, 0x7BA01)`).
  `FB81:0008` now owns `[0x7B813, 0x7B899)`.
