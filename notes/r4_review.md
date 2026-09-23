# R4 — four `C4C8` tables and `C4C8:08CF`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-23.

R1 checkbox: “Every new fact is pinned in `analysis/boot_slice_facts.json`
(or a later ledger) and checked by `python3 tools/verify_boot_slice.py`.”
R2 checkbox: “`python3 -m unittest tests.test_boot_slice -v` stays green.”
Those are stay-green gates until image work is finished. D17 still has
gaps. R1 and R2 stay `[ ]`. Do not mark R4 done: this is four tables plus
one seed, not the whole image.

Re-read linear bytes. Second PGR slot 49 file `0x7AD16` = `31 00` (word
`0x0031`). XA=1. 24-bit `(0x0031<<14)|(phys20&0x3FFF)`.

---

## `C4C8:0913` — 10 words, file `[0x45593, 0x455A7)`

20-bit `0xC5593`, 24-bit `0x0C5593`. Table `49 08 … cf 08`. Word 9 file
`0x455A5` = `CF 08` = `08CF`.

Consumer file `0x454B8`: `8B DE 83 FB 09 76 03 E9 92 00 D1 E3 2E FF A7 13 09`.

| IP | Bytes | Immediate | Writes | Polarity |
|----|-------|-----------|--------|----------|
| `0838` | `8B DE` | none | **BX** from SI (ModR/M `DE`: mod 3, reg 3, rm 6) | |
| `083A` | `83 FB 09` | **imm8** +9 (opcode `83`, `/7` CMP, rm BX) | none (flags) | |
| `083D` | `76 03` | **rel8** +3 | none | **JBE**, taken unsigned `<=`, target `0842` |
| `0842` | `D1 E3` | count 1 | **BX** (`/4` SHL, rm BX) | |
| `0844` | `2E FF A7 13 09` | disp16 `0x0913` | none | `JMP CS:[BX+0913]` |

Table path is the taken JBE (`BX<=9`). **PROVEN.**

## `C4C8:1818` — 6 words, file `[0x46498, 0x464A4)`

20-bit `0xC6498`, 24-bit `0x0C6498`. Table `06 18 0c 18 0c 18 ed 17 f6 17 fe 17`.

Consumer file `0x4645C`: `8B DA 83 EB 75 83 FB 05 77 26 D1 E3 2E FF A7 18 18`.

| IP | Bytes | Immediate | Writes | Polarity |
|----|-------|-----------|--------|----------|
| `17DC` | `8B DA` | none | **BX** from DX (ModR/M `DA`: rm 2) | |
| `17DE` | `83 EB 75` | **imm8** `0x75` (opcode `83`, `/5` SUB, rm BX) | **BX** | |
| `17E1` | `83 FB 05` | **imm8** +5 (`/7` CMP) | none | |
| `17E4` | `77 26` | **rel8** +0x26 | none | **JA**, taken unsigned `>`, target `180C` |
| `17E6` | `D1 E3` | count 1 | **BX** | |
| `17E8` | `2E FF A7 18 18` | disp16 `0x1818` | none | `JMP CS:[BX+1818]` |

Table path is JA fall-through (`BX<=5`). **PROVEN.**

## `C4C8:1844` — 6 words, file `[0x464C4, 0x464D0)`

20-bit `0xC64C4`, 24-bit `0x0C64C4`. Table `4b 15 e4 16 fd 16 17 17 31 17 a8 17`.

Consumer file `0x461BA`: `8B D8 83 FB 05 76 03 E9 84 02 D1 E3 2E FF A7 44 18`.

| IP | Bytes | Immediate | Writes | Polarity |
|----|-------|-----------|--------|----------|
| `153A` | `8B D8` | none | **BX** from AX (ModR/M `D8`: rm 0) | |
| `153C` | `83 FB 05` | **imm8** +5 | none | |
| `153F` | `76 03` | **rel8** +3 | none | **JBE**, taken unsigned `<=`, target `1544` |
| `1544` | `D1 E3` | count 1 | **BX** | |
| `1546` | `2E FF A7 44 18` | disp16 `0x1844` | none | `JMP CS:[BX+1844]` |

Table path is the taken JBE (`BX<=5`). **PROVEN.**

## `C4C8:1850` — 8 words, file `[0x464D0, 0x464E0)`

20-bit `0xC64D0`, 24-bit `0x0C64D0`. Table `9b 14 9b 14 a9 14 a9 14 b7 14 b7 14 c5 14 c5 14`.

Consumer file `0x4610D`: `8B D8 83 FB 07 77 3F D1 E3 2E FF A7 50 18`.

| IP | Bytes | Immediate | Writes | Polarity |
|----|-------|-----------|--------|----------|
| `148D` | `8B D8` | none | **BX** from AX | |
| `148F` | `83 FB 07` | **imm8** +7 | none | |
| `1492` | `77 3F` | **rel8** +0x3F | none | **JA**, taken unsigned `>`, target `14D3` |
| `1494` | `D1 E3` | count 1 | **BX** | |
| `1496` | `2E FF A7 50 18` | disp16 `0x1850` | none | `JMP CS:[BX+1850]` |

Table path is JA fall-through (`BX<=7`). **PROVEN.**

## `C4C8:08CF` seed — file `[0x4554F, 0x45554)`

20-bit `0xC554F`, 24-bit `0x0C554F`. Bytes `BE 0F 00 EB 00`.

| IP | Bytes | Immediate | Writes | Polarity |
|----|-------|-----------|--------|----------|
| `08CF` | `BE 0F 00` | **imm16** `0x000F` (`B8+SI`) | **SI** | not a Jcc |
| `08D2` | `EB 00` | **rel8** +0 | none | **JMPS** to `08D4` (unconditional) |

Word 9 of `0913` is `08CF`. Walk from `08CF` is one contiguous body through
`RETF` at `0912` (file `0x45592`). No `0F E0` / `0F F0`. **PROVEN.**
No correction.
