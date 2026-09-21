# INT 43 AX=4 — banner character to LC7981 ports

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D2 / `U-INT43-AX4` and the software half of D3. Glass pixels stay
`D3-glass` / `U-PHYS` / `U-LC7981`.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR is live: BIOS `F800:000A` through `1875` / `18CA` / `INT 43` /
`17CC` / `185A` does not `OUT` to `0xFF00-0xFF7E` and does not
`BRKXA`/`RETXA`. **PROVEN** for this reset path.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Walk the BIOS banner and write each ordinary character to LC7981 ports |
| Observable | For `'M'`… of `MPC-3000 BIOS 21/08/07`: `OUT 0xE2,0x0C` then `OUT 0xE0,AL` |
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

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x796AA, 0x796D4)` | code — INT 43 dispatcher (already opened) |
| `[0x796D4, 0x796E4)` | data — eight near targets (already opened) |
| `[0x79752, 0x7976E)` | code — AX=4 class walk |
| `[0x7976E, 0x7977E)` | data — class bytes + terminator `00` |
| `[0x7977E, 0x797CC)` | code — CR/LF/BS/DEL/FF |
| `[0x797CC, 0x79808)` | code — default glyph + cursor increment |
| `[0x79843, 0x79875)` | code — `1843` + `185A` (put already opened at `0x7985A`) |
| `[0x79875, 0x79896)` | code — walker `1875`/`187F` |
| `[0x798CA, 0x798D6)` | code — `18CA` `INT 43` AX=4 |

---

## What this note does *not* prove

- Glyph pixels (`D3-glass`).
- That AH=`0x0C` is “write display RAM” on this chip (`U-LC7981`).
- AX=2/3/5/6/7 beyond the table targets.
- First AMX task effect (`D9BD:0009` remains a second observable).
