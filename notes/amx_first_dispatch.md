# AMX first dispatch — create-table task 6

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D1 / the first-select half of `U-AMX-WAIT`. First `01EA` does **not**
idle. It creates task 6.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR (file `0x7ACB4`) is still live: `004E`, `B03B:000A`, `0396`,
`0240`, and `D9BD:0009` do not `OUT` to `0xFF00-0xFF7E` and do not
`BRKXA`/`RETXA`. **PROVEN** for this reset path.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Show what first `FB00:01EA` does after AMX start |
| Observable | Far transfer to `D9BD:0009` via `0240` `RETF` at `02EE` |
| Inputs | Eight zeroed TCBs; ready bits from `B03B:000A` ? `0396` `DL=7` then `DL=6` |
| Outputs | TCB[6] and TCB[7] have bit 0 set; scan index `[DI+11h]` stays 0; create record 6 is entered |
| Confidence | This-trace first select **PROVEN**. Later empty-queue idle / wake ISR still **UNDETERMINED** |
| Hardware deferred | Device effect of `B03B` TE7774 / DSP / DMA ports (`U-TE7774`, `U-PHYS`) |

---

## 1. Start builds eight zero TCBs plus a sentinel

`FB00:004E` (file `0x7B04E`):

```
LDS DI, CS:[0042]          ; A850:0024
LES BP, CS:[0036]          ; FB76:0002
BX = DI + 40h              ; first TCB
[DI] = BX                  ; TCB base
zero [DI+0Ch], [DI+0Eh], [DI+10h]
```

Until `ES:[BP]` AND `ES:[BP+2]` INC wraps (`FFFF:FFFF` after record 7,
file `0x7B7F2`):

```
CX = 0020h                 ; 32 words
MOV [BX], AX               ; AX is 0 — not 0x0020
BX += 2
LOOP
BP += 12h
DX += 1
```

Eight TCBs, each 0x40 bytes of zeros. `[DI+0Eh] = 8`. Then
`MOV WORD [SI], 8000h` on the next slot (bit 15 sentinel).

**PROVEN.** A zero TCB is not ready (`01EA` `TEST AX,8003h` / `JZ next`).
The sentinel alone would idle. Start is not finished yet.

---

## 2. Pre-dispatcher far table `CS:[003A]`

`FB00:0121` `LES SI, CS:[003A]` = `FB76:0096`. Two far pointers, then
`FFFF:FFFF`. Each is entered through `0616` (`LDS AX, ES:[SI]` / `RETF`).

| Slot | CS:IP | File | 20-bit | 24-bit (2nd PGR) | Role |
|------|-------|------|--------|------------------|------|
| 0 | `FB81:0008` | `0x7B818` | `0xFB818` | high ROM | list init at `A850:0004` from `FB76:00B4`; no TCB ready write |
| 1 | `B03B:000A` | `0x303BA` | `0xB03BA` | `0x0B03BA` page 44 frame `0x2C` | app init; readies tasks 6 and 7 |

### 2.1 `FB81:0008` — list init, file `0x7B818`

Named dest of `CS:[003A]` slot 0. `0616` `RETF`s here. Seed-only;
not a BFS CALL dest. Isolated `90` at `0x7B813` is auto-align
between `FB76:00B2` `RETF` and this block.

```
FB81:0008  JMP  003A                 ; eb30; jumps the sled
FB81:003A  LDS  DI, CS:[0036]        ; A850:0004
           LES  SI, CS:[0032]        ; FB76:00B4
           MOV  DX, ES:[SI]          ; count = 0001
           MOV  [DI], DX
           SI += 2, DI += 2
           BX = DI + 6*DX            ; A850:000C on this list
           INC  DX
loop:      DEC  DX
           JZ   RETF                 ; CALL 0061 DX times (original count)
           CALL 0061
           JMP  loop
FB81:0060  RETF                      ; file 0x7B870
```

`FB81:0032` / `0036` (file `[0x7B842, 0x7B84A)`) are
`b40076fb 040050a8`. `FB76:00B4` (file `[0x7B814, 0x7B818)`) is
`01000800`. Jump-over `[0x7B81A, 0x7B842)` is `10` + 38×`58` +
`90` — not walked; not `0xFF` padding.

`0061` (file `[0x7B871, 0x7B899)`), one `CALLN` from `005B`:

```
PUSH ES
MOV  AX, FFFF
MOV  [DI], AX / [DI+2], AX / [DI+4], BX
MOV  CX, ES:[SI]           ; 0008
MOV  ES, DS                ; ES = A850
MOV  AL, 2
CALL FB00:065B             ; 9a5b0600fb at 0x7B886
ADD  DI, 6
SI += 2
CX *= 2
BX += 8 + CX
POP  ES
RET                        ; c3 at 0x7B898; exact to owned 0089
```

**PROVEN:** this-trace count is 1; one `065B` with `ES=A850`,
`AL=2`. No TCB ready write. `065B` effect at `A850` stays
`U-AMX-POOL` (D11). `A850:0004` is RAM, not the linear file
at `0x28504` (that offset is ROM `0xFF`).

`B03B:000A` through `01D9` `RETF` (file `0x30589`):

- `DS=8010` (the `0x7C92` copy dest). `ES` walks `A90B` / `8010` / `D52A`…
- Many `CALL FB00:065B` — pool headers at `ES:[BX]`, not TCB words.
- `CALL FB00:0347` with `DL=8,0xC,0xD,0xE` plants `IVT[DL]=ES:BX`
  (`DS=0`, `DI=DL*4`). Not a ready-bit writer. Vector *meaning* is
  `U-V53A`.
- `CALL D20A:0008` / `004A` — `OUT` to DSP ports `0x0060-0x0066`.
- Port block `0xC2`–`0xDE`, then `0x86`/`0x80`/`0x82`/`0x84`,
  `0xFE`/`0xF8`/`0xFC`/`0xFA`, `0x6A`. Device effect **UNDETERMINED**.
- Tail file `0x30579`:

```
B03B:01C9  MOV DL, 7
           CALL FB00:0396
           MOV DL, 6
           CALL FB00:0396
           POP ES / POP DS / RETF
```

---

## 3. `FB00:0396` — ready bit 0 — file `0x7B396`

```
CALL 0537                  ; SI = TCB[DL]
JS  return                 ; no slot
CLI
INC [SI+8]
OR  [SI], 1                ; bit 0
CMP DL, [DI+11h]
JAE skip
MOV [DI+11h], DL           ; only if DL < current index
```

`[DI+11h]` was zeroed at start. Both `DL=7` and `DL=6` are `>= 0`, so
the index stays **0**. **PROVEN:** TCB[6] and TCB[7] have bit 0 set;
slots 0–5 remain 0; scan starts at slot 0.

---

## 4. First `01EA` takes create `0240` for `DL=6`

`01EA` loads `DL` from `[DI+11h]` (=0), `CALL 0537`, then scans:

| Slot | `[SI]` after `B03B` | `01EA` |
|------|---------------------|--------|
| 0–5 | `0000` | `TEST 8003h` / `JZ next` |
| 6 | bit 0 set | ready, bit 1 clear ? `0240` |
| 7 | bit 0 set | not reached on this select |
| 8 | `8000` | sentinel; not reached |

```
MOV [SI], 4000h
TEST AX, 2                 ; bit 1
JZ  0240
```

`0240` (file `0x7B240`):

```
MOV AL, 12h
MUL DL                     ; 18 * 6
LES BX, CS:[0036]          ; FB76:0002
ADD BX, AX                 ; record 6, file 0x7B7CE
SS:SP = ES:[BX+4]
LES BX, ES:[BX]            ; D9BD:0009
… PUSH ES / PUSH BX …
FB00:02EE RETF             ; ? D9BD:0009
```

Record 6 bytes `0900bdd9f0034893` = `D9BD:0009` / `9348:03F0`.
**PROVEN.**

---

## 5. First task body — `D9BD:0009`, file `0x59BD9`

20-bit `0xD9BD9`. Second PGR page 54 frame `0x36` ? 24-bit `0x0D9BD9`.

```
CALL E937:0004             ; once
loop:
  PUSH 14h
  CALL B060:0000
  ADD  SP, 2
  CMP  [D6A1], 0
  JZ   loop
  PUSH 06C3 / PUSH DS / PUSH 7F73
  CALL D9B5:0045
  ADD  SP, 6
  MOV  [D6A1], 0
  JMP  loop
```

This-trace does not `RETF` back to `0262`. The `023A` idle is not taken
on first select. What `E937:0004` / `B060:0000` / `[D6A1]` *do* is D3 /
D7, not D1.

---

## Create-table roster (bytes only)

| n | CS:IP | File of IP | SS:SP |
|---|-------|------------|-------|
| 0 | `FB00:05B2` | `0x7B5B2` | `9186:03F0` |
| 1 | `B259:0006` | `0x32596` | `91C5:0320` |
| 2 | `EC05:0000` | `0x6C050` | `91F7:0708` |
| 3 | `EAD0:000B` | `0x6AD0B` | `9267:0648` |
| 4 | `DDF1:000A` | `0x5DF1A` | `92CB:03F0` |
| 5 | `B14B:0002` | `0x314B2` | `930A:03E8` |
| 6 | `D9BD:0009` | `0x59BD9` | `9348:03F0` |
| 7 | `B000:00DF` | `0x300DF` | `9387:3E80` |

Only 6 and 7 are readied before first `01EA`. Records 0–5 entries and
exits are in [`amx_create_table.md`](amx_create_table.md).

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7B04E, 0x7B148)` | code — start through dispatcher (already opened) |
| `[0x7B240, 0x7B2EF)` | code — create `0240` through `02EE` `RETF` |
| `[0x7B396, 0x7B3B3)` | code — ready API `0396` |
| `[0x7B347, 0x7B371)` | code — `0347` IVT plant (null ? `FB00:0311`) |
| `[0x7B762, 0x7B7F2)` | data — eight create records; terminator `FFFF:FFFF` at `0x7B7F2` |
| `[0x7B7F6, 0x7B7FE)` | data — `CS:[003A]` two far pointers + terminator |
| `[0x7B802, 0x7B80E)` | data — kernel far-ptr table `000A:0078` / `901C:1130` / `FB76:00B2` |
| `[0x7B814, 0x7B818)` | data — `FB76:00B4` list header `01000800` |
| `[0x7B818, 0x7B81A)` | code — `FB81:0008` `JMP 003A` |
| `[0x7B81A, 0x7B842)` | data — jump-over sled; not walked |
| `[0x7B842, 0x7B84A)` | data — `FB81` `CS:[0032]`/`[0036]` far ptrs |
| `[0x7B84A, 0x7B871)` | code — `FB81:003A` through `0060 RETF` |
| `[0x7B871, 0x7B899)` | code — `FB81:0061` through `0088 RET` |
| `[0x303BA, 0x3058A)` | code — `B03B:000A` through `RETF` |
| `[0x59BD9, 0x59C05)` | code — `D9BD:0009` through `JMP 000E` |

Callees `E937:0004`, `B060:0000`, `D9B5:0045` stay unowned until D3/D7.

---

## What this note does *not* prove

- The wake ISR that would leave `023A` if the queue is later empty
  (`U-AMX-WAIT` remainder).
- That tasks 0–5 or 7 run on reset. 7 is ready but not selected first.
- Meaning of `[D6A1]`, `B060:0000`, or `E937:0004`.
- PGR after task 6 runs (`U-XA-LIVE`).
- IVT[8]/[0xC]/[0xD]/[0xE] as named IRQs (`U-V53A`).
