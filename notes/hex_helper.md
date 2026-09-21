# BIOS hex helper — `F800:1896` / `189C`

**Image:** Vailixi OS 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

D18 already closed INT 43 AX=0..7. This note contracts the smallest
established BIOS helper whose local exits were classified (D16) but
whose body was still seed-only: `F800:1896` (3 instructions) and its
only callee `189C`.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR is live: BIOS `F800` does not `OUT` to `0xFF00-0xFF7E`.
XA=1. Page `(0xF9896 >> 14) & 63` = 62, word `0x003E`.
**PROVEN** for this reset path.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Print `AL` as two uppercase hex ASCII digits on the LCD surface |
| Observable | Each digit: `INT 43` AX=4 with `BL` in `'0'..'9'`/`'A'..'F'`; default glyph reaches `LCD_put` file `0x7985A` AH=`0x0C` |
| Inputs | `AL` (low 8 bits of `AX`). Wrapper forces `CL=2`. One near caller: `F800:1A14` |
| Outputs | Two glyph puts; `CL=0` on return; `AX` rotated leftover. No direct RAM writes |
| Confidence | Encodings, nibble math, `18CA` path **PROVEN**. AH=`0x0C` controller meaning **HYPOTHESIS**. Glass **UNDETERMINED** |
| Hardware deferred | LC7981 display RAM and pixels (`U-LC7981`, `U-PHYS`) |

---

## Addresses

| CS:IP | File | 20-bit | 24-bit (XA=1, PGR[62]=`003E`) |
|-------|------|--------|-------------------------------|
| `F800:1896` | `0x79896` | `0xF9896` | `0x0F9896` |
| `F800:189C` | `0x7989C` | `0xF989C` | `0x0F989C` |
| `F800:18CA` | `0x798CA` | `0xF98CA` | `0x0F98CA` |
| `F800:1A14` | `0x79A14` | `0xF9A14` | `0x0F9A14` |
| `F800:185A` | `0x7985A` | `0xF985A` | `0x0F985A` |

`file = phys20 & 0x7FFFF`. `phys24 = (0x3E << 14) \| (phys20 & 0x3FFF)`.

---

## 1. Wrapper — `F800:1896`, file `0x79896`

```
MOV  CL, 2
CALL 189C
RET
```

Bytes `b102e80100c3`. Unique in the image. `e80100` at `0x79898` is
`CALLN 189C`. Transfer-scan walk: 3 insns, bounded, `RET` at
`0x7989B`. **PROVEN.**

---

## 2. Digit loop — `F800:189C`, file `0x7989C`

```
MOV  DL, 4
SUB  DL, CL                 ; DL = 4 - CL
SHL  DL, 1
SHL  DL, 1                  ; DL = (4 - CL) * 4
PUSH CX
MOV  CL, DL
SHL  AX, CL                 ; drop unused high nibbles
POP  CX
loop:
  OR   CL, CL
  JZ   done
  PUSH CX
  MOV  CL, 4
  ROL  AX, CL               ; next nibble into AL[3:0]
  PUSH AX
  AND  AL, 0Fh
  CMP  AL, 0Ah
  JL   dec
  ADD  AL, 7                ; 0xA..0xF
dec:
  ADD  AL, 30h              ; ASCII '0'..'9' / 'A'..'F'
  MOV  CL, AL
  CALL 18CA                 ; INT 43 AX=4, BL=CL
  POP  AX
  POP  CX
  DEC  CL
  JMP  loop
done:
  RET
```

`e80700` at `0x798C0` is `CALLN 18CA`. ASCII convert
`240f3c0a7c0204070430` at `0x798B4` is unique. Body
`[0x7989C, 0x798CA)` through `RET` `C3` at `0x798C9`.
`follow_local` is 26 insns, bounded. **PROVEN.**

With the wrapper's `CL=2`: `SHL AX, 8` then two `ROL AX, 4`.
Start `AX=00XY` after the shift; first digit is `X`, second is `Y`.
AH of the incoming `AX` is discarded. **PROVEN** as 8086 shifts.

`189C` encodings would accept other `CL` (zero digits if `CL=0`).
The only near `CALL` to `189C` is `1898`. Executed digit count is
2. Other `CL` **UNDETERMINED** as a caller domain.

---

## 3. Put path — `F800:18CA` ? INT 43 AX=4 ? `LCD_put`

`18CA` (already pinned): `BL=CL`; `AX=4`; `INT 43`; `RET`.

Hex bytes are `'0'..'9'` (`0x30..0x39`) and `'A'..'F'`
(`0x41..0x46`). None match the AX=4 class table (`0x0D`/`0x0A`/
`0x08`/`0x7F`/`0x0C`). They take default `F800:17CC` ?
`MOV AH, 0Ch` / `CALL 185A` at file `0x797F2`. **PROVEN:**
`1896` reaches `LCD_put` at file `0x7985A`. It is not a
non-display sink.

AH=`0x0C` controller meaning stays `U-LC7981` **HYPOTHESIS**.
Glass pixels stay `D3-glass` / `U-PHYS` **UNDETERMINED**.

---

## 4. Named consumer

One `CALLN 1896`: `F800:1A14`, file `0x79A14`, bytes `e87ffe`
(unique). Unexpected-vector path `19B3` after the inline
`" type "` walker:

```
POP  AX
SUB  AX, 1956h
MOV  BL, 3
DIV  BL                    ; AL = (saved IP - 1956) / 3
CALL 1896
CALL 1875                  ; "h\r\ncaused all memory to be lost.…"
```

`AL` is the BIOS ladder slot index. Slot meaning is the IVT
ladder in [`ivt_inventory.md`](ivt_inventory.md), not this helper.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x79896, 0x798CA)` | code — `1896` wrapper + `189C` digit loop through `RET` |

`18CA` / `LCD_put` stay with the INT 43 notes.

---

## What this note does *not* prove

- Glyph pixels on the glass (`D3-glass`).
- That AH=`0x0C` writes display RAM on this controller (`U-LC7981`).
- Any `189C` caller with `CL?2`.
- Device effect of the unexpected-vector `OUT 0xC011,0xFF` (`U-C0XX`).
