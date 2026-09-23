# PGR after first AMX select — `U-XA-LIVE`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

Closes D4’s *catalog* and the this-trace bound through task 6’s first
wait. Later individual-page `OUT`s stay `U-XA-LIVE`.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name every `0xFF00-0xFF7E` table writer and the live map after first `01EA` |
| Observable | Only three `MOV DX,0xFF00` / `OUTSW` sites, all FAC0, all before AMX |
| Inputs | Linear image; task 6 `D9BD:0009` then `B060:0000` ? `FB00:0484` |
| Outputs | Second PGR (file `0x7ACB4`) still live through task 7 *select*, `D9DD:005D`, and `DDC0:0031` |
| Confidence | Image-wide full-table writers **PROVEN**. This-trace through first wait, `D9DD:005D`, and `DDC0:0031` **PROVEN**. D510’s eight callers and task 7’s 61 two-level walks do not `MOV DX` into `0xFF00-0xFF7E` **PROVEN**. Next third-level `DDC0:000F` **UNDETERMINED** |
| Hardware deferred | None for the catalog |

---

## 1. Image-wide table writers

Every `BA 00 FF` (`MOV DX,0xFF00`) in the 512 KiB image:

| File | CS:IP | Next | Table |
|------|-------|------|-------|
| `0x7AC13` | `FAC0:0013` | `CS:OUTSW` | first, `CS:0256` file `0x7AE56` |
| `0x7ACA8` | `FAC0:00A8` | `CS:OUTSW` | second, `CS:00B4` file `0x7ACB4` |
| `0x7ADC3` | `FAC0:01C3` | `CS:OUTSW` | third, `CS:01CF` file `0x7ADCF` |

No fourth `MOV DX,0xFF00`. **PROVEN.**

`BRKXA` / `RETXA` (`0F E0` / `0F F0`) exist only at `0x7AC1C`,
`0x7AC9F`, `0x7ACB1`, `0x7ADBA`, `0x7ADCC` — FAC0 boot. **PROVEN.**

False positives (not writers):

- `8D 46 BA` / `50` / `FF …` (`LEA AX,[BP-70]`) at `0x38A19`, `0x38A4D`,
  `0x39003`, `0x39697` — looks like `BA 50 FF`.
- `84 2E 6F 99` (`TEST [996F],CH`) at `0x55F15` — looks like `CS:OUTSW`.

---

## 2. Port picker, not a writer — `D510:008D`, file `0x5518D`

Argument `[BP+6]` selects a constant in `DX`, then `MOV AX,DX` / `RETF`.
Values include `0xFF80`, `0xFF20`, `0xFF10`, `0xFF03`, `0xFF02`,
`0xFF01`, `0xFF50`, and 0. There is no `OUT` in this routine.

Far callers are exactly eight. Each continuation uses `AX` as a
value (`MOV DI,AX`, `MOV [7CB1],AL`, `OR AX,AX`, `MOV DX,AX` then
`CMP`/`JMP`/`PUSH`, or discard and `RETF`). None is `OUT`.
`008D` and `0118` local walks contain no `OUT`. `0118` returns
`MOV AX,DX` / `LEAVE` / `RETF` at file `0x552A4`. **PROVEN:**
these callers do not write `0xFF00-0xFF7E`. `0xFF80` is outside
the PGR window.

| Entry | File | Bytes after `CALLF` |
|-------|------|---------------------|
| `008D` | `0x370D2` | `83 C4 02 8B F8` `ADD SP,2` / `MOV DI,AX` |
| `008D` | `0x539E1` | `83 C4 02 A2 B1 7C C3` `ADD SP,2` / store `AL` / `RET` |
| `008D` | `0x53D3B` | `83 C4 02 5E CB` |
| `008D` | `0x53D9A` | `83 C4 02 5F 5E 5D CB` |
| `0118` | `0x53CC3` | `83 C4 02 0B C0` `ADD SP,2` / `OR AX,AX` |
| `0118` | `0x53CEE` | `83 C4 02 8B D0 EB` `ADD SP,2` / `MOV DX,AX` / `JMP` |
| `0118` | `0x53D14` | `83 C4 02 8B D0 81 FA` `ADD SP,2` / `MOV DX,AX` / `CMP DX` |
| `0118` | `0x547A3` | `83 C4 02 5E C9 CB` |

Task 7 `B000:00DF` (file `0x300DF`, 20-bit `0xB00DF`, 24-bit
`0x0B00DF` under second PGR slot 44 word `0x002C` at `0x7AD0C`,
XA=1) has 20 direct `CALLF`s. Those bodies plus their direct
`CALLF` children are 61 walks. None contains `MOV DX,imm16`
with `imm16` in `0xFF00-0xFF7E`. **PROVEN** for that two-level
tree.

First third-level callee is `D9DD:005D` (file `0x59E2D`, 20-bit
`0xD9E2D`, 24-bit `0x0D9E2D` under second PGR slot 54 word
`0x0036` at `0x7AD20`, XA=1). Task 7 `CALLF DDF4:0002`; that
body `CALLF E21A:000B` at file `0x5DF9E` (`9A 0B 00 1A E2`);
all four `E21A:000B` `CALLF`s are `D9DD:005D`. The body is
`PUSH BP` / `MOV BP,SP` / two `(AX<<4)+[BP+n]` / `SUB`/`SBB` /
`RETF` at file `0x59E61`. No `MOV DX,imm16`. No `OUT DX` /
`OUTSW` / `OUTSB`. `DX` is `XOR DX,DX` then `RCL`/`ADC` high
half (0..16) then `SBB DX,BX` (`0xFFEF`..`0xFFFF` or 0..16),
disjoint from `0xFF00-0xFF7E`. **PROVEN:** this callee does
not write the PGR window. Second third-level is `DDC0:0031`
(file `0x5DC31`, 20-bit `0xDDC31`, 24-bit `0x0DDC31` under
second PGR slot 55 word `0x0037` at `0x7AD22`, XA=1). Level-2
site `E70C:007E` is `DDF4:0002` `CALLF` at `DDF4:007D` file
`0x5DFBD` (`9A 7E 00 0C E7`); that body `CALLF DDC0:0031` at
file `0x67155`. No `MOV DX,imm16`. No `OUT DX` / `OUTSW` /
`OUTSB`. `XOR DX,DX` then `DIV BX` (`BX=0x0A`) remainder
0..9; `CWD` gives `{0, 0xFFFF}` — both disjoint from
`0xFF00-0xFF7E`. `ADC DX,0` follows `CALLF F800:20FA` (return
`DX`, not this body). No `OUT` consumes `DX`. `RETF` at file
`0x5DCEE` and `0x5DD11`. **PROVEN:** this callee does not
write the PGR window. Next unwalked third-level is `E70C:00A0`
`CALLF DDC0:000F` at file `0x67160`. `U-XA-LIVE` stays open.
High-CS 20-bit form of a caller file is `file|0x80000`
(the ROM mirror).

---

## 3. This-trace after first `01EA`

Task 6 `D9BD:0009`:

```
CALL E937:0004             ; DS=ES=8010; RETF; no PGR
loop:
  PUSH 14h
  CALL B060:0000           ; CX=14h; CALL FB00:0484
```

`0484` stores `CX` at `[SI+0Ah]` (not `+10h`) and zeros `[SI+0Ch]`,
then `0469` calls `01CF` with `AX=4`.
`01CF` does `[SI] = ([SI] & 8001h) | 4` (bit 2 = blocked), saves
`SS:SP`, and falls into `01EA`.

`01EA` `TEST AX,000Ch` / `JNZ next` skips the blocked TCB 6. TCB 7 is
still ready (bit 0 from `B03B`). First wait therefore *selects task 7*
`B000:00DF` (create `0240` / `RETF` `02EE`).

None of `E937`, `B060`, `0484`, `0469`, `01CF`, or `01EA` write
`0xFF00-0xFF7E`. **PROVEN:** the second PGR is still live when task 7
is entered.

Task 7’s own body is a far-call chain (`DDF4`, `D9B5`, `BDF1`,
`E521`, `B03B:01DA`, `B1B1`, `CF0C`, `D470:0948`, …) and `RETF`s at
`B000:01A6`. The first third-level callee `D9DD:005D` and second
`DDC0:0031` do not write PGR. **PROVEN:** second table still
live through that `RETF`. Remaining third-level (`DDC0:000F`
next) is `U-XA-LIVE`.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7AC13, 0x7AC1C)` | code — first PGR `OUTSW` (already in FAC0 span) |
| `[0x7ACA8, 0x7ACB4)` | code — second PGR `OUTSW` |
| `[0x7ADC3, 0x7ADCF)` | code — third PGR `OUTSW` |
| `[0x5518D, 0x55206)` | code — `D510:008D` port picker through `RETF` |
| `[0x55206, 0x55218)` | data — `D510:0106` nine near targets for `JMP CS:[BX+0106]` (`2E FF A7 06 01` at file `0x551D8`). Words `00E7 00E2 00F6 00F1 00EC 00FF 00FF 00FF 00DD` |

---

## What this note does *not* prove

- That the second table survives `DDC0:000F` or later third-level
  callees of task 7.
- That some other `MOV DX,r/m` / `OUT DX` uses a PGR port.
- 24-bit identity of RAM touched only after a later page write.
