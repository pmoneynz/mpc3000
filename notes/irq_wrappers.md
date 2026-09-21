# Interrupt wrappers — XA switch and IRET rewrite

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D9. Slot *meaning* (`U-V53A`) and which IRQ leaves a later
`023A` idle (`U-AMX-WAIT`) stay open.

Reproduction: `python3 tools/verify_boot_slice.py`.

`ndisasm` / Capstone must not be followed across `0F E0` / `0F F0`.
`FAC0:01BA` is `RETXA 0x12`; `FAC0:01CC` is `BRKXA 0x12`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Partition wrappers that switch XA or rewrite an `IRET`/`RETF` frame |
| Observable | `FAC0:01A4` third-PGR reload via ROM `IVT[12]`; `02F8`/`02EF` `IRET` to `TCB+18h+AX` or to the interrupted IP; `0157` stack-switch `RETF` |
| Inputs | RAM vs ROM IVT (XA); list header `CS:[0042]`; TCB `+18h`/`+1Ch` hooks |
| Outputs | Frame layouts below |
| Confidence | Instruction streams and the XA=0 vs XA=1 vector fetch **PROVEN**. Hook *consumers* on reset **PROVEN** as null (create zeros `+18h..+1Eh`). Which later writer fills a hook **UNDETERMINED** |
| Hardware deferred | IRQ source for `IVT[10h]` / `IVT[0]` / `IVT[4]` (`U-V53A`, `U-PHYS`) |

---

## 1. `FAC0:01A4` — `IVT[10h]`, file `0x7ADA4`

Planted at `0000:0040` (`FAC0:0061`). BIOS skip `DI=40h` keeps it.

```
PUSH DS / SI / AX / BX / CX / DX
DS = 0
IVT[12h] = FAC0:01BD          ; 0000:0048
RETXA 0x12                    ; file 0x7ADBA  0F F0 12
```

`RETXA` fetches `IVT[12h]` in the **current** mode (XA=1 ? RAM slot
just written) and clears XA. Continue is `FAC0:01BD` (file `0x7ADBD`):

```
CX = 40h
SI = 01CF                     ; third PGR, file 0x7ADCF
DX = FF00
CS:OUTSW / INC DX / LOOP
BRKXA 0x12                    ; file 0x7ADCC  0F E0 12
```

`BRKXA` fetches `IVT[12h]` with XA=0 ? **ROM** template at file
`0x00048` = `FAC0:024F` (`4F 02 C0 FA`), not the RAM plant. **PROVEN.**

`FAC0:024F` (file `0x7AE4F`):

```
POP DX / CX / BX / AX / SI / DS
IRET
```

Pops match the `01A4` pushes. The interrupted `CS:IP`/`FLAGS` are
unchanged. This wrapper **switches XA** and reloads the third PGR; it
does not rewrite the return address.

`01CF` onward is PGR data, not code.

---

## 2. AMX `FB00:02F8` / `02EF` — `IVT[0]` / `IVT[4]`

File `0x7B2F8` / `0x7B2EF`. Shared tail at `02FE`.

```
SUB  SP, 4                    ; two-word hole
PUSH AX
AX = 0 (02F8) or 4 (02EF)
PUSH DS / DI
LDS  DI, CS:[0042]
TEST [DI+10h], 0FFh
JG   0312                     ; nest 1..127
POP  DI / DS / AX
ADD  SP, 4
IRET                          ; 0311 — interrupted CS:IP
```

`01EA` writes `[DI+10h]=1`. `0157` `DEC`s it. `JG` is taken only when
that byte is `01h`–`7Fh`. Zero or `80h`–`FFh` ? plain `IRET`.

Hook path `0312` (file `0x7B312`):

```
DI = [DI+0Ah]                 ; current TCB
LEA DI, [DI+18h]
ADD DI, AX                    ; +0 or +4
AX:DS = far [DI]              ; hook
OR  AX, DI
JZ  030B                      ; null ? plain IRET
; BP frame after PUSH BP:
;   +8/+0A hole  ? hook IP / hook CS
;   +0C / +0E / +10  ? FLAGS / old IP / old CS   (rotated)
POP BP / DI / DS / AX
IRET                          ; to hook. Old CS:IP remain on the stack
```

After this `IRET`, the stack holds the interrupted `IP` then `CS`. A
hook `RETF` resumes the interrupted code. **PROVEN** as the frame
transform. Create `0284` zeros TCB `+18h..+1Eh`, so first dispatch has
null hooks. `0347` with `DL` 0 or 4 writes this table; no such plant
is on the reset path through first `01EA`.

---

## 3. `FB00:0157` / `0194` — ISR enter / leave

Six far callers, all `B03B` `0347` bodies (`9A 57 01 00 FB`).

`0157` (file `0x7B157`):

```
PUSH AX CX DX BX SI DI BP
MOV  BP, SP
MOV  BX, DS
XCHG [BP+0Eh], BX             ; far-return IP ? DS
MOV  AX, ES
XCHG [BP+10h], AX             ; far-return CS ? ES
MOV  ES, AX                   ; ES = original CS
LDS  DI, CS:[0042]
DEC  [DI+10h]
JS   0189                     ; skip switch if nest went negative
MOV  [DI+16h], SP
MOV  [DI+18h], SS
LDS  BP, CS:[0046]            ; FB76:00A6
LDS  SP, [BP+0]               ; SS:SP = 901C:1130 (bytes 30 11 1C 90)
MOV  SS, DS
0189:
MOV  BP, SP
PUSH ES / PUSH BX             ; original CS:IP
MOV  DS, SS / MOV ES, SS
RETF                          ; continue the ISR on the new stack
```

`0194` (file `0x7B194`) reverses: `INC [DI+10h]`; if the result is
positive, restore `SS:SP` from `[DI+16h]`; if `[DI+0Ch] > [DI+11h]`,
`01CF` `AX=2`; `XCHG` the far-return slots back; pop; `RETF`.

`038A` is `0157` then `0194` (forced yield). `0586` may take the same
pair when `[DI+12h]` hits zero.

`D52A:0008` (file `0x552A8`, `IVT[8]`): `CALL 0157`, then `DS=ES=8010`,
work, `CALL 0586`. Device effect **UNDETERMINED** (`U-V53A`).

---

## 4. What wakes `023A`

The NOP spin does not re-scan TCBs. Leave it only by transferring
off that RIP: an `IRET` frame rewrite (`0312`), a `JMP 01EA`/`0281`,
or a task `RETF`.

If `[DI+10h]` is 1 (as `01EA` left it) and a TCB hook is non-null,
`02F8`/`02EF` `IRET` to that hook with the `023A` frame still on the
stack. That is a **software-possible** wake. Which IRQ and which
writer fill the hook remain `U-AMX-WAIT` / `U-V53A`.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7ADA4, 0x7ADCF)` | code — `01A4` through `BRKXA 0x12` (already opened) |
| `[0x7AE4F, 0x7AE56)` | code — ROM `IVT[12]` continue (already opened) |
| `[0x7B157, 0x7B1CF)` | code — `0157` / `0194` (already opened) |
| `[0x7B2EF, 0x7B347)` | code — `02EF` / `02F8` / `0311` / `0312` through `IRET` |

---

## What this note does *not* prove

- That `IVT[10h]` fires on reset (no software `INT 10h` in the slice).
- A non-null TCB hook on the first-select path.
- Which vector leaves a later empty-queue idle.
- `901C:1130` 24-bit identity after a later PGR write (`U-XA-LIVE`).
