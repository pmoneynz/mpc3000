# Calling convention

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D8. Interrupt-wrapper frame rewrite stays D9.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the conventions this image actually uses, and which one dominates application code |
| Observable | Far cdecl (`[BP+6]`, caller `ADD SP`, `RETF`); BIOS inline-string walker; AMX register/`RETF`; `INT` `AX` |
| Inputs | Established callers (BIOS banner, task 6, AMX public, create-table 2/3) plus image-wide prologue bytes |
| Outputs | Four conventions below |
| Confidence | Walker, B060, and task-6 ? `D9B5:0045` arg order **PROVEN**. Whole-image `9A` count is **HYPOTHESIS** (data lookalikes). “Dominant” for *application* ROM is **PROVEN** from prologue/epilogue pairing and zero `[BP+4]` |
| Hardware deferred | None |

---

## 1. Dominant — far cdecl

Application bodies (create-table 2/3/5/6, `B060`, `D9B5:0045`, `B19C:000E`) use:

```
PUSH  <args, right-to-left>
CALL FAR dest
ADD  SP, nbytes
```

Callee:

```
PUSH BP
MOV  BP, SP
; first word at [BP+6]
; far pointer at [BP+6]:[BP+8], next word at [BP+0A]
LEAVE          ; or POP BP
RETF
```

Type specimen `B060:0000` (file `0x30600`):

```
PUSH BP / MOV BP, SP
MOV  CX, [BP+6]
CALL FB00:0484
POP  BP
RETF
```

Task 6: `PUSH 14h` / `CALL B060:0000` / `ADD SP,2`. **PROVEN.**

Arg order type specimen — task 6 ? `D9B5:0045` (file `0x59B95`):

```
D9BD:001F  PUSH 06C3
           PUSH DS
           PUSH 7F73
           CALL D9B5:0045
           ADD  SP, 6
```

`D9B5:0045` does `LDS SI, [BP+6]` and `MOV CX, [BP+0A]`. So the
right-to-left layout is far pointer `DS:7F73`, then word `06C3`.
**PROVEN.**

`MOV AX,[BP+4]` does not exist in the image (near-C first arg).
`MOV AX,[BP+6]` exists 164 times. `LEAVE`+`RETF` (`C9 CB`) occurs
1194 times, all in application ROM (`[0x30000,0x70000)` holds 1169);
zero in BIOS `F800` and AMX `FB00:0000–07FF`. **PROVEN** as bytes.

Caller cleanup dominates: `ADD SP,imm8` (`83 C4`) is 5730 raw hits
(`+2/+4/+6/+8` = 1399+2061+473+902). `RETF n` (`CA iw` with `iw?32`)
is a handful. Callee-cleanup far stdcall is not the app rule.

Whole-image `9A` (6154) and `E8` (2009) are not instruction counts.
They only back the HYPOTHESIS that far calls outnumber near calls.

---

## 2. BIOS inline-string walker — `F800:1875`, file `0x79875`

Unique stub (`5E 06 0E 07` occurs once):

```
POP  SI              ; return address = first string byte
PUSH ES
PUSH CS / POP ES
CALL 187F            ; CLD; AL=ES:[SI++]; until AL=0; else 18CA
POP  ES
PUSH SI              ; SI now past the NUL
RET                  ; resume after the string
```

`18CA` (file `0x798CA`): `BL=CL`; `AX=4`; `INT 43`; `RET`.

Three near callers, no far caller. **PROVEN.**

| File | CS:IP | Inline bytes |
|------|-------|--------------|
| `0x78122` | `F800:0122` | BIOS banner (already D2) |
| `0x799BE` | `F800:19BE` | `============= System Error =============Sorry, but a software bug of type ` |
| `0x79A17` | `F800:1A17` | `h\r\ncaused all memory to be lost.…` (after `CALL 1896` hex) |

`19BE` is the unexpected-vector path from [`ivt_inventory.md`](ivt_inventory.md).
`1896` (file `0x79896`) is a *register* helper (`CL=2` hex digits ?
`18CA`), not this walker.

This convention is BIOS-only. It is not how application tasks pass
strings (`D9B5` takes a far pointer on the stack).

---

## 3. AMX public — far, registers, `RETF`

The 19 `CALL FAR FB00` IPs (D6) do not use `[BP+6]` for the task index.
`DL` is the slot (`0396`, `0347`, `04AC`, `0537`). `0484` takes `CX`
from a cdecl wrapper (`B060`), then writes `[SI+0Ah]`. Return is `RETF`
(or near `RET` for `0537` / `0148`).

`FB00` contains three `PUSH BP`/`MOV BP,SP` sites (`0157`, `0327`,
`0996`) for *frame access* in the irq wrapper, not app cdecl.

---

## 4. `INT` — `AX` selector

`INT 43` / `INT 46`: `AX` selects the near handler. Character in `CL`/`BL`
on the AX=4 path. Not a stack convention.

---

## 5. What “dominant” means

| Realm | Convention |
|-------|------------|
| Application ROM (tasks 2–6, `B060`, `D9B5`) | Far cdecl, `[BP+6]`, caller `ADD SP`, `RETF` |
| AMX kernel | Far, `DL`/`CX`, `RETF` |
| BIOS `F800` | Near `CALL`/`RET`; walker for inline text; `INT`+`AX` |
| FAC0 boot | Far jumps / `BRKXA`; not cdecl |

New application slices should assume far cdecl unless the site is
BIOS, AMX, or an `INT`.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x79875, 0x7987F)` | code — walker `1875` (already opened through `1895`) |
| `[0x79896, 0x7989C)` | code — hex helper `1896` |
| `[0x30600, 0x3060D)` | code — `B060:0000` (already opened) |
| `[0x59B95, 0x59BA1)` | code — `D9B5:0045` prologue through `LDS SI,[BP+6]` |

---

## What this note does *not* prove

- That every `9A` is an executed far call.
- Signedness, struct packing, or hidden `ES` args beyond the specimens.
- `RETF n` as a second app convention (too few real `CA iw`).
- Interrupt wrappers (`0157` / `02F8` / `FAC0:01A4`) — D9.
