# AMX wait — `FB00:01EA` / `0537`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes the *condition* half of `U-AMX-WAIT`. First `01EA` does not take
this idle; see [`amx_first_dispatch.md`](amx_first_dispatch.md). The wake
ISR for a later empty queue is still open.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Select a ready 0x40-byte TCB and either resume it (`RETF`) or create it (`0240`), else idle |
| Observable | `STI` + four `NOP` + `jmp 023A` when `0537` returns `SF=1` or a TCB word has bit 15 set |
| Inputs | List header at `CS:[0042]` = `A850:0024`; index `DL`; TCB word `[SI]` |
| Outputs | Ready task: `[SI]=0x4000` and either `RETF` (bit 1 set) or `0240` (bit 1 clear). Empty: idle with `IF=1` |
| Confidence | Instruction partition **PROVEN**. 24-bit of `A850:0024` **PROVEN** only while the second PGR is live. Wake ISR **UNDETERMINED** |
| Hardware deferred | Which IRQ actually leaves `023A` (`U-PHYS`) |

---

## 1. PGR on this path

`BRKXA 0x14` loads the second PGR (file `0x7ACB4`). BIOS `F800:000A`, `INT 43` / `INT 46` as followed, `F800:1AD4`, AMX start `004E`, `01EA`, and `0537` contain no `OUT` to `0xFF00-0xFF7E` and no `BRKXA`/`RETXA`.

**PROVEN** for this reset path: the second PGR is still live when AMX first runs `01EA`. Later task code can reload PGR (`U-XA-LIVE` remainder).

Under that map, `A850:0024` is page 42 frame `0xEA` ? 24-bit `0x3A8524`. High ROM `FB00`/`FB76` (pages 62–63, frames `3E`/`3F`) is the same in all three boot PGR tables.

---

## 2. `FB00:0537` — index to TCB — file `0x7B537`

```
LDS DI, CS:[0042]
MOV AX, FFFF
CMP DL, [DI+0Eh]
JAE empty          ; AX left FFFF
MOV AX, 0040
MUL DL
ADD AX, [DI]       ; TCB base (near, in DS)
MOV SI, AX
XOR AX, AX
empty:
OR  AX, AX
RET
```

`SF=1` iff `DL >= [DI+0Eh]` (no slot). `SF=0` and `SI` = TCB[`DL`]. TCB stride **0x40**. **PROVEN**.

---

## 3. `FB00:01EA` — select — file `0x7B1EA`

```
CLI
LES SP, CS:[004A]     ; kernel stack from header
MOV SS, ES
MOV DL, [DI+11h]
MOV BYTE [DI+10h], 1  ; in-scheduler
MOV [DI+0Ah], word [DI+2]
MOV [DI+0Ch], DL
STI
CALL 0537
JS  idle_0239
scan:
CLI
MOV AX, [SI]
TEST AX, 000Ch        ; bits 2|3 ? next
JNZ next
TEST AX, 8003h        ; bits 15|1|0
JZ  next
JS  idle_0239         ; bit 15
MOV [DI+0Ah], SI
MOV WORD [SI], 4000h  ; running
TEST AX, 0002h        ; bit 1
JZ  create_0240
MOV SP, [SI+4]
MOV SS, [SI+6]
RETF                  ; resume
next:
INC DX
MOV [DI+0Ch], DL
MOV [DI+11h], DL
STI
ADD SI, 40h
JMP scan
idle_0239:
STI
NOP × 4
JMP 023A
```

Sole `CALL 01EA`: `FB00:0143`. Sole other entry: `JMP 0281` after `0240`.

`0240` uses create records at `CS:[0036]` = `FB76:0002`, 18 bytes each: far entry at +0, `SS:SP` at +4. Record 7 (file `0x7B7E0`) is `B000:00DF` / `9387:3E80` — the same CS:IP as `FAC0:019E`. That FAC0 jump is still not on the reset path. The AMX table is.

---

## 4. What idle waits on

The NOP spin does **not** re-scan TCBs. Setting `[SI] |= 1` at `FB00:03A3` (and `044E`) is a ready-bit writer; it does not leave `023A` by itself.

No `INT 0` / `INT 8` instruction exists in this image (the `CD 00` / `CD 08` hits are immediates or PGR data). AMX plants `IVT[0]=FB00:02F8` and `IVT[4]=FB00:02EF`. Those handlers IRET to a hook table at `[DI+0Ah]+18h+AX`, or IRET to the interrupted IP if the hook is null.

**PROVEN:** leave `023A` only by transferring control off that RIP (ISR frame rewrite, `JMP 01EA`/`0281`, or a task `RETF`).  
**UNDETERMINED:** which IRQ or hook does that on a later empty queue.
First select does not reach `023A`.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7B1EA, 0x7B22C)` | code — `01EA` through `RETF` |
| `[0x7B22C, 0x7B240)` | code — next-TCB + idle spin |
| `[0x7B240, 0x7B284)` | code — create path through `JMP 01EA` |
| `[0x7B537, 0x7B552)` | code — `0537` |
| `[0x7B762, 0x7B7F2)` | data — eight 18-byte create records; record 7 = `B000:00DF` |

Do not own the rest of the AMX kernel from this note.
