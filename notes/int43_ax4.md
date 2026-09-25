# INT 43 LCD surface (AX=0..7)

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D2 / `U-INT43-AX4`, the software half of D3, and D18. Glass pixels
stay `D3-glass` / `U-PHYS` / `U-LC7981`. Every INT 43 slot is now a
named software contract. AH bytes remain `U-LC7981`.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR is live: BIOS `F800:000A` through `1875` / `18CA` / `INT 43` /
`17CC` / `185A` does not `OUT` to `0xFF00-0xFF7E` and does not
`BRKXA`/`RETXA`. **PROVEN** for this reset path.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | BIOS LCD surface: init, fill, cursor, glyph, shadow copy/replay |
| Observable | Banner `'M'` of `MPC-3000 BIOS 21/08/07`: `OUT 0xE2,0x0C` then `OUT 0xE0,AL` |
| Inputs | Inline string at `F800:0125` (file `0x78125`); `DS=0040` cursor `[68AB]=0` |
| Outputs | Shadow `0040:662B+cursor`; cursor `[68AB]`; port pair above |
| Confidence | Path and port writes **PROVEN**. AH meaning **HYPOTHESIS** (HD61830-class). Glass **UNDETERMINED** |
| Hardware deferred | LC7981 display RAM and pixels (`U-LC7981`, `U-PHYS`) |

---

## 1. Walker — `F800:1875`, file `0x79875`

```
POP SI                     ; inline banner
ES = CS
CALL 187F
  CLD
  AL = ES:[SI++]
  JZ  done
  CL = AL
  CALL 18CA
    BL = CL
    AX = 4
    INT 43
  JMP walk
RET / IRET back to BIOS RETF
```

Banner bytes `4d50432d333030302042494f532032312f30382f30370d0a00`
= `MPC-3000 BIOS 21/08/07`, CR, LF, NUL. **PROVEN.**

---

## 2. INT 43 — `F800:16AA`, file `0x796AA`

```
STI
save BX..ES
SI = AX
DS = ES = 0040
CMP SI, 8
JAE  iret                  ; AX>=8 is a no-op
CALL near CS:[16D4+AX*2]
restore / IRET
```

`CS:16D4` (file `0x796D4`) AX=0..7:

| AX | Target | File |
|----|--------|------|
| 0 | `16E4` | `0x796E4` LCD init (already pinned) |
| 1 | `171D` | `0x7971D` fill 0x140 spaces |
| 2 | `1734` | `0x79734` `LCD_put` AH from BX |
| 3 | `1744` | `0x79744` |
| 4 | `1752` | `0x79752` character class |
| 5 | `1808` | `0x79808` copy shadow |
| 6 | `181B` | `0x7981B` |
| 7 | `1839` | `0x79839` cursor ? row/col |

AX=4 **PROVEN**.

---

## 3. Class table — `F800:176E`, file `0x7976E`

```
MOV SI, 176E
AL = CS:[SI]
JZ  176A                   ; default CALL 17CC
CMP AL, BL
JZ  CALL CS:[SI+1]
SI += 3
```

| BL | Handler | File |
|----|---------|------|
| `0x0D` CR | `177E` | `0x7977E` |
| `0x0A` LF | `178B` | `0x7978B` |
| `0x08` BS | `179E` | `0x7979E` |
| `0x7F` DEL | `17AA` | `0x797AA` |
| `0x0C` FF | `17C8` ? AX=1 | `0x797C8` |
| other | `17CC` | `0x797CC` |

Banner letters and digits take `17CC`. CR/LF take `177E`/`178B`.
**PROVEN.**

---

## 4. Default glyph path — `F800:17CC`

`DS=0040`. Cursor word `[68AB]`. Shadow cell `[BX+662Bh]`.

```
AL = BL                    ; character
BX = [68AB]
CMP AL, [BX+662Bh]
JE  skip_put               ; already there
MOV [BX+662Bh], AL
TEST [68AF], FFh
JNZ already_addressed
PUSH AX
AX = BX
CALL 1843                  ; set LCD cursor, [68AF]=FF
POP AX
MOV AH, 0Ch
CALL 185A                  ; LCD_put
INC [68AB] if < 013Fh      ; 320 cells, 40×8
```

`1843` (file `0x79843`):

```
[68AB] = AX
LCD_put AH=0Ah, AL=low
LCD_put AH=0Bh, AL=high    ; high was original AH of AX
[68AF] = FFh
```

`185A` is the already-pinned put: wait `IN 0xE2` bit 7, `OUT 0xE2,AH`,
`OUT 0xE0,AL`.

CR: `[68AB] = ([68AB]/28h)*28h` then `1843` (column 0 of current row).
LF: next row `* 28h` if row < 7, then `1843`.

**PROVEN:** an ordinary banner character is `OUT 0xE2,0x0C` / `OUT 0xE0,char`.
It is not a non-display sink.

---

## 5. RAM under the second PGR

BIOS `F800:0057` `REP STOSB` `CX=68B0h` at `ES=0040` zeros
`0040:0000` through `0040:68AF`. That includes cursor, flag, and the
0x140-byte shadow at `662B`. **PROVEN.**

| Object | `DS:off` | 20-bit | page | frame | 24-bit |
|--------|----------|--------|------|-------|--------|
| BSS base | `0040:0000` | `0x00400` | 0 | `C0` | `0x300400` |
| shadow[0] | `0040:662B` | `0x06A2B` | 1 | `C1` | `0x306A2B` |
| cursor | `0040:68AB` | `0x06CAB` | 1 | `C1` | `0x306CAB` |
| flag | `0040:68AF` | `0x06CAF` | 1 | `C1` | `0x306CAF` |

First char `'M'`: cursor 0, shadow 0, flag 0 ? `1843(0)` then put
`0x0C`/`0x4D`, cursor 1. Later letters skip `1843` while flag stays `FF`
until CR/LF/`1843`.

---

## 6. AH values — HYPOTHESIS only

MAME `hd61830.h` numbers `0x0A`/`0x0B`/`0x0C` as cursor-address low/high
and display-data write. That is a class match, not an LC7981 datasheet.
**HYPOTHESIS:** those control bytes address controller memory and write
the ASCII byte into it. **UNDETERMINED:** pixels on the glass.

---

## 7. INT 43 AX=1 / 2 / 3 / 5 / 6 / 7

Named consumer is the dispatcher `CALL near CS:[16D4+AX*2]`. Bodies
were extra-only D16 bytes; they are now seeded. All `RET` to the
dispatcher. **PROVEN** encodings. Controller meaning stays `U-LC7981`.

### AX=1 — `F800:171D`, file `0x7971D`

```
XOR AX, AX
CALL 1843                  ; cursor 0
MOV CX, 0140h              ; 320 cells
MOV BL, 20h                ; space
CALL 17CC                  ; default glyph
LOOP
XOR AX, AX
CALL 1843                  ; cursor 0
RET
```

`e82101` at `0x7971F` and `e81001` at `0x79730` are `CALLN 1843`.
`e8a100` at `0x79728` is `CALLN 17CC`. **PROVEN:** fill the 320-cell
shadow and the glass path with spaces, cursor back to 0.

### AX=2 — `F800:1734`, file `0x79734`

```
MOV AX, BX
AND AX, 3
SHL AX, 1
SHL AX, 1
ADD AX, 30h                ; AX = ((BX & 3) << 2) + 30h
CALL 185A                  ; LCD_put AH:AL
RET
```

`e81701` at `0x79740` is `CALLN 185A`. **PROVEN:** one put of that
computed AX. **UNDETERMINED:** what `((BX&3)<<2)+30h` means on the
LC7981 (`U-LC7981`). Do not invent a register name.

### AX=3 — `F800:1744`, file `0x79744`

```
MOV AL, BH                 ; row
MOV BH, 28h
MUL BH                     ; AX = row * 40
XOR BH, BH                 ; BX = col (BL untouched)
ADD AX, BX                 ; AX = row * 40 + col
CALL 1843                  ; set cursor
RET
```

Bytes `8ac7 b728 f6e7 32ff 03c3` at `0x79744`: `B7 28` is `MOV BH,28h` and
`F6 E7` is `MUL BH`, so `BL` survives. `e8f200` at `0x7974E` is
`CALLN 1843`. **PROVEN:** cursor word becomes `BH*40+BL` = `row*40+col`.
The OS wrapper `B1B1:0026` (file `0x31B36`) passes `BH`=row, `BL`=col.
Correction (2026-09-25): an earlier revision decoded `MOV BL,28h` / `MUL BL`
and reported `BH*40+40`.

### AX=5 — `F800:1808`, file `0x79808`

```
CLD
MOV SI, 662Bh              ; live shadow
MOV DI, 676Bh              ; SI + 0140h
MOV CX, 0140h
REP MOVSB
MOV AX, [68AB]
MOV [68AD], AX             ; saved cursor
RET
```

**PROVEN:** copy 320 shadow bytes `0040:662B` -> `0040:676B` and save
the cursor at `[68AD]`. Second PGR 24-bit: `676B` is `0x306B6B`.

### AX=6 — `F800:181B`, file `0x7981B`

```
XOR AX, AX
CALL 1843                  ; cursor 0
CLD
MOV SI, 676Bh
MOV CX, 0140h
LODSB / MOV BL, AL
CALL 17CC                  ; replay one saved cell
LOOP
MOV AX, [68AD]
CALL 1843                  ; restore cursor
; falls into AX=7
```

`e82300` at `0x7981D` and `e80a00` at `0x79836` are `CALLN 1843`.
`e89dff` at `0x7982C` is `CALLN 17CC`. **PROVEN:** replay the AX=5
backup through the glyph path, then restore `[68AD]`. Execution
falls into AX=7 and returns row/col in AX.

### AX=7 — `F800:1839`, file `0x79839`

```
MOV AX, [68AB]
MOV CL, 28h
DIV CL                     ; AL = row, AH = col
XCHG AH, AL                ; AL = col, AH = row
RET
```

**PROVEN:** convert cursor to 40-column row/col. Shared `RET` at
`0x79842` with the AX=6 fallthrough.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x796AA, 0x796D4)` | code — INT 43 dispatcher (already opened) |
| `[0x796D4, 0x796E4)` | data — eight near targets (already opened) |
| `[0x7971D, 0x79734)` | code — AX=1 fill 0x140 spaces |
| `[0x79734, 0x79744)` | code — AX=2 `LCD_put` `((BX&3)<<2)+30h` |
| `[0x79744, 0x79752)` | code — AX=3 cursor `row*40+col` |
| `[0x79752, 0x7976E)` | code — AX=4 class walk |
| `[0x7976E, 0x7977E)` | data — class bytes + terminator `00` |
| `[0x7977E, 0x797CC)` | code — CR/LF/BS/DEL/FF |
| `[0x797CC, 0x79808)` | code — default glyph + cursor increment |
| `[0x79808, 0x7981B)` | code — AX=5 copy shadow `662B` to `676B` |
| `[0x7981B, 0x79839)` | code — AX=6 replay `676B` |
| `[0x79839, 0x79843)` | code — AX=7 cursor `/40` |
| `[0x79843, 0x79875)` | code — `1843` + `185A` (put already opened at `0x7985A`) |
| `[0x79875, 0x79896)` | code — walker `1875`/`187F` |
| `[0x798CA, 0x798D6)` | code — `18CA` `INT 43` AX=4 |

---

## What this note does *not* prove

- Glyph pixels (`D3-glass`).
- That AH=`0x0C` is "write display RAM" on this chip (`U-LC7981`).
- What AX=2's `((BX&3)<<2)+30h` programs on the controller.
- First AMX task effect (`D9BD:0009` remains a second observable).
