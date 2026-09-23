# AMX wait — `FB00:01EA` / `0537`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes `U-AMX-WAIT`. First `01EA` does not take this idle; see
[`amx_first_dispatch.md`](amx_first_dispatch.md). A later empty queue
leaves `023A` when IVT[8] `D52A:0008` drives the tick word to zero.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Select a ready 0x40-byte TCB and either resume it (`RETF`) or create it (`0240`), else idle |
| Observable | `STI` + four `NOP` + `jmp 023A` when `0537` returns `SF=1` or a TCB word has bit 15 set |
| Inputs | List header at `CS:[0042]` = `A850:0024`; index `DL`; TCB word `[SI]` |
| Outputs | Ready task: `[SI]=0x4000` and either `RETF` (bit 1 set) or `0240` (bit 1 clear). Empty: idle with `IF=1` |
| Confidence | Instruction partition **PROVEN**. Leave-`023A` transfer **PROVEN** as IVT[8] `D52A:0008` under the second PGR. Pin that raises slot 8 **UNDETERMINED** (`U-V53A`) |
| Hardware deferred | Which pin raises IVT[8], and the device effect of `OUT 0xC010, 0x60` (`U-V53A`, `U-C0XX`, `U-PHYS`) |

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

Sole `CALL 01EA`: `FB00:0143`. `01CF` also enters it: `JS` at `01E2` and fallthrough at `01E7`. `JMP` at `0281`, after `0240`, is the other entry.

`0240` uses create records at `CS:[0036]` = `FB76:0002`, 18 bytes each: far entry at +0, `SS:SP` at +4. Record 7 (file `0x7B7E0`) is `B000:00DF` / `9387:3E80`. `FAC0:019E` (file `0x7AD9E`) is `JMPF` to that same `B000:00DF`. That FAC0 jump is still not on the reset path. The AMX table is.

---

## 4. What idle waits on

The NOP spin does **not** re-scan TCBs. Setting `[SI] |= 1` at
`FB00:03A3` (`0396`) and `044E` (success tail of `03B3`) is a ready-bit
writer; it does not leave `023A` by itself. Full TCB grammar:
[`amx_public_api.md`](amx_public_api.md).

No `INT 0` / `INT 8` instruction exists in this image (the `CD 00` / `CD 08` hits are immediates or PGR data). AMX plants `IVT[0]=FB00:02F8` and `IVT[4]=FB00:02EF`. `0284` zeros TCB `+18h..+1Eh`. Every `CALL 0347` in the image passes `DL` in `{8, 0xC, 0xD, 0xE, 9, 8}` — never 0 or 4 — so the hook arm of `0347` is not taken. **PROVEN:** those handlers `IRET` to the interrupted IP. They do not rewrite a `023A` frame.

The only near transfers to `01EA` are `0143` `CALL`, `01E2` `JS` from `01CF`, and `0281` `JMP`. Nothing transfers to `0281`. **PROVEN.**

## 5. IVT[8] leaves `023A` — `D52A:0008`

XA=1, second PGR (file `0x7ACB4`). Page 53 word `0x0035` (file `0x7AD1E`), same in the first table. Third-table page 53 is `0x00F5` (file `0x7AE39`); the only `INT 10h` in the image is `FB00:09CA` (file `0x7B9CA`), and nothing calls or stores `FB00:0996`.

| Form | Value |
|------|-------|
| CS:IP | `D52A:0008` |
| 20-bit | `0xD52A8` |
| 24-bit | `0x0D52A8` (page 53 frame `0x35`) |
| File | `0x552A8` |
| IVT slot | 8, planted by `B03B:000A` via `0347` |

`FB00` is page 62 frame `0x3E` in all three boot tables, so `FB00:IP` is file `0x7B000+IP`, 20-bit `0xFB000+IP`, 24-bit `0x0FB000+IP`.

Start writes `[DI+14h]` from `FB76:00A4` (file `0x7B804`) = word `0x000A`, then `011E` `CALL 055F` which `CALL`s `05AB`. `05AB` copies `[DI+14h]` to `[DI+12h]`. **PROVEN:** the tick word is 10 before the first `01EA`. Header `A850:0024` is page 42 frame `0xEA`, 24-bit `0x3A8524`. The tick word is `A850:0036` = 24-bit `0x3A8536`. The reload is `A850:0038` = 24-bit `0x3A8538`.

`D52A:0008` calls `0157`, does the work, then calls `0586` (file `0x552CC`). Two `JZ`s (`0036`, `004A`) skip side work and rejoin. `MOV DX,0xC010` is file `0x552F2`; `OUT DX,AL` with `AL=0x60` is file `0x552F7`. Then `CALL 0194` (file `0x552F8`) and `IRET` (file `0x552FD`). The only far call of `0586` is that one. No near call of `0586` exists in `FB00`.

`0586` decrements `[DI+12h]` on every IVT[8] entry, including while a task is running. An entry that does not hit zero returns: `0194` sees `[DI+0Ch]==[DI+11h]` (the scan stores `DL` at `[DI+0Ch]` (file `0x7B22D`) and `[DI+11h]` (file `0x7B230`)) and the `IRET` returns to the interrupted IP. While the idle is live, that IP is `023A`. The entry that decrements 1 to 0 calls `05A0`: `XOR DX,DX` / `CALL 0396` (file `0x7B5A0`). That is the only near call of `0396` in `FB00`. `DL=0` is below the sentinel index, so `[DI+11h]` becomes 0 and bit 0 is set on TCB 0. `05A0` then reloads `[DI+12h]` from `[DI+14h]` (10). `01EA` writes `[DI+10h]=1` at `01F7` and does not write it again before the idle. The inner `0157` decrements that byte from 1 to 0, so its `JS` is not taken and the stack switch runs. The inner `0194` increments it from 0 to 1, so its `JLE` is not taken. `0396` has stored 0 at `[DI+11h]` while `[DI+0Ch]` still holds the idle index, so this inner `0194` takes `CALL 01CF` with `AX=2` when that index is greater than 0.

On the idle path `[DI+0Ah]` is still `[DI+2]`, the bit-15 sentinel (`011A` `MOV word [SI],8000h` lands on that address). `01CF` ORs 2 into it (`8002h`) and `JS 01EA` (file `0x7B1E2`) without saving `SS:SP`. `01EA` reloads the kernel stack from `CS:[004A]` and creates task 0 (`FB00:05B2`) because bit 1 is clear. **PROVEN:** that `IRET` frame is abandoned. Control does not return to `023A`.

`D5DD:000C` (IVT[0xC]) can `CALL 04AC` with `DL=2` before its `0194`. `04AC` lowers the index only when that TCB has bit 2. Slots 0–5 are still zero on the reset-path empty queue, so this call does not leave it. `D5F3:000E` `CALL`s `0396` with `DL=3` only when `[9756]!=0`. That byte is inside the `8010:7C92`–`FFB7` clear. Whether a later writer sets it before the first idle is **UNDETERMINED**. The IVT[8] path does not read it.

Task 0’s `05E9` walk is what later turns an expired `[SI+0Ah]` wait into `[SI]=0002`. It is not what leaves `023A`. The leave is the tick zero-crossing, which readies slot 0 even while task 6 is still blocked.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7B1EA, 0x7B22C)` | code — `01EA` through `RETF` |
| `[0x7B22C, 0x7B240)` | code — next-TCB + idle spin |
| `[0x7B240, 0x7B284)` | code — create path through `JMP 01EA` |
| `[0x7B537, 0x7B552)` | code — `0537` |
| `[0x7B762, 0x7B7F2)` | data — eight 18-byte create records; record 7 = `B000:00DF` |
| `[0x552A8, 0x552FE)` | code — `D52A:0008` through `IRET`; IVT[8] wake |

Do not own the rest of the AMX kernel from this note.
