# PGR after first AMX select — `U-XA-LIVE`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

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
| Outputs | Second PGR (file `0x7ACB4`) still live through task 7 *select* |
| Confidence | Image-wide full-table writers **PROVEN**. This-trace through first wait **PROVEN**. Task 7 body and later page-picker callers **UNDETERMINED** |
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

Far callers exist (`0x370D2`, `0x539E1`, `0x53D3B`, `0x53D9A` ?
`008D`; `0x53CC3`, `0x53CEE`, `0x53D14`, `0x547A3` ? `0118`). Whether
any caller later `OUT DX,AX` into `0xFF00-0xFF7E` is **UNDETERMINED**.
`0xFF80` is outside the PGR window.

---

## 3. This-trace after first `01EA`

Task 6 `D9BD:0009`:

```
CALL E937:0004             ; DS=ES=8010; RETF; no PGR
loop:
  PUSH 14h
  CALL B060:0000           ; CX=14h; CALL FB00:0484
```

`0484` stores `CX` at `[SI+10h]`, then `0469` calls `01CF` with `AX=4`.
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
`B000:01A6`. Those callees were not entered for PGR. **UNDETERMINED**
after task 7 begins executing.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7AC13, 0x7AC1C)` | code — first PGR `OUTSW` (already in FAC0 span) |
| `[0x7ACA8, 0x7ACB4)` | code — second PGR `OUTSW` |
| `[0x7ADC3, 0x7ADCF)` | code — third PGR `OUTSW` |
| `[0x5518D, 0x55206)` | code — `D510:008D` port picker through `RETF` |

---

## What this note does *not* prove

- That the second table survives the whole of task 7.
- That the `D510` picker is ever used as a PGR store.
- 24-bit identity of RAM touched only after a later page write.
