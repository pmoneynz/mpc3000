# AMX public API and TCB grammar

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D6. Create-table *bodies* stay D7. Interrupt-wrapper frame rewrite
stays D9. Mailbox/pool object grammar stays D11.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR (file `0x7ACB4`) is the map used for the 24-bit figures
below. High ROM `FB00` is page 62 frame `0x3E` in all three boot PGR
tables, so `FB00:IP` = file `0x7B000+IP` = 20-bit `0xFB000+IP` =
24-bit `0x0FB000+IP`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name every image-wide far call into `FB00` and the TCB word those calls mutate |
| Observable | 76 `CALL FAR FB00:xxxx` sites; 19 distinct IPs; `[SI]` bits 0/1/2/3/14/15 |
| Inputs | List header `CS:[0042]` = `A850:0024`; TCB stride `0x40`; `DL` slot index |
| Outputs | Public catalog below; TCB / header field map |
| Confidence | Far-call catalog and TCB bit writers **PROVEN**. Mailbox/pool *meaning* **HYPOTHESIS**. Whether every `9A` site is an executed instruction (vs. a data lookalike) is **HYPOTHESIS**; none sit in padding or the `0x7C92` copy |
| Hardware deferred | None |

---

## 1. Image-wide far-call surface

Every `9A xx xx 00 FB` in the 512 KiB image (76 sites, 19 IPs).
No `EA xx xx 00 FB`. **PROVEN.**

| IP | File | n | Class | Effect |
|----|------|---|-------|--------|
| `0157` | `0x7B157` | 6 | irq enter | Push regs; `DEC` byte `[DI+10h]` (`FE 4D 10` at `0171`). `JS 0189` at `0174` (`78 13`) skips the save when that byte is `0x80`–`0xFF`. Otherwise `MOV [DI+16h],SP` and `MOV [DI+18h],SS`. `RETF` at `0193` |
| `0194` | `0x7B194` | 6 | irq leave | `INC` byte `[DI+10h]` (`FE 45 10` at `019A`). `JLE 01B9` at `019D` (`7E 1A`) is taken when that byte is `0` or `0x81`–`0xFF`. Otherwise the bytes at `[DI+0Ch]` and `[DI+11h]` are compared, and `JBE 01B9` at `01AF` (`76 08`) skips the call unless `[DI+0Ch]` is unsigned greater. That arm is `MOV AX,2` / `CALLN 01CF` at `01B5`. Then pop; `RETF` `01CE` |
| `0347` | `0x7B347` | 6 | IVT / hook plant | `IVT[DL]=ES:BX` unless `DL` is 0 or 4. Null `ES:BX` stores `FB00:0311`. `DL` 0/4 writes hook `[current TCB+18h+DX]` |
| `038A` | `0x7B38A` | 1 | yield | `0157` then `0194` (forced enter/leave) |
| `0396` | `0x7B396` | 8 | ready | `INC [SI+8]`; `OR [SI],1` |
| `03B3` | `0x7B3B3` | 1 | post + maybe wait | Uses `[SI+10h]` as a mailbox pointer; on the success tail `INC [SI+8]`; `OR [SI],1`; if `DX` negative, `01CF` `AX=8` |
| `0469` | `0x7B469` | 2 | wait | `01CF` `AX=4` |
| `0484` | `0x7B484` | 4 | timed wait | `[SI+0Ah]=CX`; `[SI+0Ch]=0`; then `0469`. `AX=0` or `FFFB` |
| `04AC` | `0x7B4AC` | 4 | wake if bit 2 | If `TEST [SI],4`: `[SI]=0002`, `[SI+0Ch]=4`, `[SI+0Ah]=0` |
| `0552` | `0x7B552` | 2 | get index | `AX = [DI+0Ch]` |
| `0586` | `0x7B586` | 1 | nest | `DEC [DI+12h]`; if zero, `0157` / `05A0` / `0194` |
| `0624` | `0x7B624` | 1 | mailbox store 0 | `LDS BX, CS:[0042]`; word at `([BX+6] + DX)` = 0 |
| `0637` | `0x7B637` | 1 | mailbox store | same address; word = `CX` |
| `0648` | `0x7B648` | 1 | mailbox load | `AX` = that word; `OR AX,AX` |
| `065B` | `0x7B65B` | 16 | mailbox init | Packs flags into `ES:[BX]` (`26 89 07` at `0668`), then zeros `ES:[BX+2]`, `ES:[BX+4]`, and `ES:[BX+6]` |
| `067C` | `0x7B67C` | 3 | mailbox | Alloc-side; calls `0743` |
| `06B9` | `0x7B6B9` | 4 | mailbox | Free-side; calls `0743` |
| `06E8` | `0x7B6E8` | 2 | mailbox | Pop-side; calls `0743` |
| `0725` | `0x7B725` | 7 | mailbox | Push-side; calls `0743` |

Sites fall in app ROM (`0x303xx`, `0x521xx`, `0x53xxx`, `0x55xxx`,
`0x56xxx`, `0x5DExx`) and AMX-high (`0x7B8xx`–`0x7B9xx`). None in
`[0,0x20000)` or the `0x7C92` copy. **PROVEN** as bytes.

`065B`–`0725` operate on `ES:[BX]` headers. `0624`/`0637`/`0648`
use `DS` from `CS:[0042]` and index `[BX+6] + DX`. None of them
write TCB `[SI]`. Their object grammar is D11.

---

## 2. Internal entries (not far-called from this image)

| IP | Role |
|----|------|
| `000C` | Start (`jmp 004E` over the KADAK copyright) |
| `013E` | Dispatcher: `LDS DI,CS:[0042]` / `CALL 01EA` / `jmp 013E` |
| `01CF` | Wait primitive (near only) |
| `01EA` | Select |
| `0240` | Create from `FB76:0002 + 12h*DL` |
| `0284` | First-entry `RETF` into a new task (`02EE`) |
| `02EF` / `02F8` | `IVT[4]` / `IVT[0]` |
| `0311` | Default `IRET` planted by `0347` |
| `04DC` | Post-create / priority gate; can `MOV [SI],2` if bit 3 |
| `0537` | `DL` ? `SI` (stride `0x40`) |
| `05B2` | Create-table record 0 (D7) |
| `05E9` | Walks TCBs. `MOV AX,[SI]` / `AND AX,0x8004` (`25 04 80` at `05EE`) tests the word and does not store the mask. `05FF` `MOV [SI],2` runs when bit 2 is set, bit 15 is clear, and `060B` decrements `[SI+0Ah]` to zero |
| `0616` | `LDS AX,ES:[SI]` / `RETF` |

Near `CALL 01CF` exists only at `01B5` (`AX=2`), `0461` (`AX=8`),
`0476` (`AX=4`). **PROVEN.**

---

## 3. TCB word grammar — `SI` = TCB[`DL`], stride `0x40`

`0537` (file `0x7B537`): `SI = [DI] + 0x40*DL` when `DL < [DI+0Eh]`.

### `[SI+0]` status

| Bit | Mask | Writer | Reader | Meaning |
|-----|------|--------|--------|---------|
| 0 | `0001` | `0396` / `044E` `OR [SI],1`; `0240` `MOV [SI],1` when `[SI+8]` is nonzero | `01EA` `TEST 8003h` | Ready (never created, or re-ready after create) |
| 1 | `0002` | `01CF` `AX=2`; `04AC` / `04DC` / `05FF` `MOV [SI],0002` | `01EA` `TEST 0002h` ? resume vs create | Resumable: `SS:SP` at `+4/+6` is live |
| 2 | `0004` | `01CF` `AX=4` (`0469` / `0484`) | `01EA` `TEST 000Ch`; `04AC` `TEST 4` | Blocked (ordinary wait) |
| 3 | `0008` | `01CF` `AX=8` (`03B3` tail) | `01EA` `TEST 000Ch`; `04DC` `TEST 8` | Blocked (mailbox wait) |
| 14 | `4000` | `01EA` `MOV [SI],4000h` | — | Running (selected) |
| 15 | `8000` | Start `MOV [SI],8000h` on the slot after the last TCB | `01EA` `JS` idle; `01CF` keeps it | Sentinel / empty-queue |

`01CF` (file `0x7B1CF`):

```
LDS DI, CS:[0042]
MOV SI, [DI+0Ah]          ; current TCB
CLI
MOV DX, [SI]
AND DX, 8001h             ; keep bits 15 and 0
OR  AX, DX                ; AX = caller value OR bits 15 and 0
MOV [SI], AX
JS  01EA                  ; bit 15: do not save stack
MOV [SI+4], SP
MOV [SI+6], SS
; fall into 01EA
```

`01EA` then `TEST AX,000Ch` / `JNZ next` (skip bits 2 or 3),
`TEST AX,8003h` / `JZ next`, `JS idle` (bit 15), store `4000h`,
and either `RETF` (bit 1) or `0240` (bit 1 clear).

No `OR [SI],2/4/8` exists in `FB00`. Bits 1/2/3 are only written by
`01CF` (via `AX`) or by a whole-word `MOV [SI],imm`. **PROVEN.**

### Other TCB fields

| Off | Size | Writers | Role |
|-----|------|---------|------|
| `+2` | word | start zeros; `0284` `TEST [SI+2],2` | Flag consumed at first entry. Meaning **HYPOTHESIS** |
| `+4` / `+6` | SP / SS | `01CF` save; `01EA` restore. `0240` loads CPU `SS:SP` from the create record and does not write these slots | Live stack while bit 1 is set |
| `+8` | word | `0396`/`044B` `INC`; `0240` `DEC`; start 0 | Ready-count. Create leaves `[SI]=1` iff this stays non-zero |
| `+0Ah` | word | `0484` `MOV [SI+0Ah],CX`; `04AC` zeros it; `0284` zeros it | Timed-wait argument. **Not** `+10h` (D4 wording retracted) |
| `+0Ch` | word | `0484` zeros; `04AC` writes `0004`; `0284` zeros | Wait result (`0484` returns `FFFB` if non-zero on resume) |
| `+0Eh` | byte | `0284` writes `7F`; `04DC` compares `7F` / bit 7 | Priority-like. Meaning **HYPOTHESIS** |
| `+10h` | word | `03B3` reads as a mailbox pointer | Not the wait timeout |
| `+18h` / `+1Ch` | far | `0284` zeros; `0347` when `DL` is 0 or 4; `02F8`/`02EF` consume `[TCB+18h+AX]` | IRQ hooks. Frame rewrite is D9 |

---

## 4. List header — `A850:0024` via `CS:[0042]`

`DI` after `LDS DI, CS:[0042]`. 24-bit `0x3A8524` while the second PGR
is live (page 42 frame `0xEA`).

| Off | Role |
|-----|------|
| `+00` | TCB base (near, in `DS`) |
| `+02` | Copied to `+0Ah` at the start of `01EA`, then overwritten with `SI` |
| `+0A` | Current TCB (`SI`) |
| `+0C` | Current `DL` (also the value `0552` returns) |
| `+0E` | Record count. `004E` stores `DL` here after walking `ES:[BP]` by 18 until `FFFF:FFFF`. The table has 8 records, then that terminator at file `0x7B7F2`. `0072` is `LES BP,CS:[0036]` (`2E C4 2E 36 00`), so this entry sets `BP` |
| `+10` | In-scheduler / irq-nest byte (`01EA` writes 1; `0157` `DEC`; `0194` `INC`) |
| `+11` | Scan index (`0396` / `04AC` / `044E` may lower it) |
| `+12` | Tick word (`0586` `DEC` word; `05A0` reloads it from `+14h`) |
| `+16` / `+18` | Saved `SP` / `SS` in `0157` |

---

## 5. Kernel config words at `FB00:0036`

| CS | Pointer | Role |
|----|---------|------|
| `0036` | `FB76:0002` | Create table, 18-byte records |
| `003A` | `FB76:0096` | Pre-dispatch far table (`0616`) |
| `003E` | `FB76:00AA` | Start `055F` zero-table |
| `0042` | `A850:0024` | List header |
| `0046` | `FB76:00A6` | `0157` stack-switch table |
| `004A` | `912F:0578` | Kernel `SS:SP` loaded by `01EA` |

---

## 6. This-trace use

Task 6 `B060:0000` ? `0484` with `CX=14h` writes `[SI+0Ah]=0014h`,
zeros `[SI+0Ch]`, then `0469` / `01CF` `AX=4`. TCB 6 becomes bits
0+2 (`0005` if bit 0 was still set, else `0004`). `01EA` skips it
and creates task 7. **PROVEN** (see [`pgr_live_after_amx.md`](pgr_live_after_amx.md)).

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7B148, 0x7B157)` | code — `0148` mailbox helper used at start |
| `[0x7B157, 0x7B1CF)` | code — `0157` / `0194` |
| `[0x7B1CF, 0x7B1EA)` | code — `01CF` |
| `[0x7B347, 0x7B38A)` | code — `0347` through the hook tail |
| `[0x7B38A, 0x7B3B3)` | code — `038A` / `0396` |
| `[0x7B3B3, 0x7B4AC)` | code — `03B3` through `0484` |
| `[0x7B4AC, 0x7B537)` | code — `04AC` / `04DC` |
| `[0x7B552, 0x7B5B2)` | code — `0552` / `055F` / `0586` |
| `[0x7B5E9, 0x7B616)` | code — `05E9` TCB walk and `060B` helper through `RET` |
| `[0x7B616, 0x7B762)` | code — `0616` through mailbox `0743` |

`01EA` / `0240` / `0537` / create-table bytes are already owned.

---

## What this note does *not* prove

- Create-table task 0–5 and 7 bodies (D7).
- A non-null TCB hook. `0284` zeros `+18h..+1Eh`, and no `CALL 0347`
  passes `DL` 0 or 4. The leave of `023A` is IVT[8], not a hook
  ([`amx_wait.md`](amx_wait.md)).
- Mailbox/pool record layout past the `065B` zeroing (D11).
- KADAK source names. Automated “aj_wait” labels remain proposals.
