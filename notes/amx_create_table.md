# AMX create-table tasks 0–7

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D7. Record 7 was already `B000:00DF`; 0–6 are identified the
same way: table bytes, entry stream, every exit of that stream.
Callee *meaning* stays with later slices.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR (file `0x7ACB4`) maps each of these CS pages to an identity
frame (page = frame). `CS:IP` = file `20-bit & 0x7FFFF` = 20-bit =
24-bit with a leading 0.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name create-table entries `FB76:0002 + 12h*n` and pin each exit |
| Observable | Eight 18-byte records; terminator `FFFF:FFFF` at file `0x7B7F2` |
| Inputs | `0240` `DL`; `SS:SP` from the record; `E937:0004` sets `DS=ES=8010` |
| Outputs | Entry/exit table below |
| Confidence | Record bytes, first instructions, and listed exits **PROVEN**. Ready-on-reset only for 6 and 7 **PROVEN**. Slot 0’s first ready is the IVT[8] tick ([`amx_wait.md`](amx_wait.md)). Slot 2’s first bit 0 stays **UNDETERMINED** |
| Hardware deferred | `D213:0008` `OUT` `0x60`/`0x62` device effect (`U-PHYS`) |

---

## 1. Table

`CS:[0036]` = `FB76:0002` (file `0x7B762`). Each record: IP, CS, SP,
SS, then 10 extra bytes. Start copies record `+8` to TCB `+2`
(`00DF`). Extra is `00` except record 2 (`00005a00…` at `+8`).
Consumer of that `005A` is **UNDETERMINED**.

| n | CS:IP | File | 20-bit / 24-bit | SS:SP | Entry bytes |
|---|-------|------|-----------------|-------|-------------|
| 0 | `FB00:05B2` | `0x7B5B2` | `0xFB5B2` / `0x0FB5B2` | `9186:03F0` | `2EC5 3E42 00` |
| 1 | `B259:0006` | `0x32596` | `0xB2596` / `0x0B2596` | `91C5:0320` | `B810 808E D8` |
| 2 | `EC05:0000` | `0x6C050` | `0xEC050` / `0x0EC050` | `91F7:0708` | `55 8BEC 56 8B7606` |
| 3 | `EAD0:000B` | `0x6AD0B` | `0xEAD0B` / `0x0EAD0B` | `9267:0648` | `55 8BEC 83EC06` |
| 4 | `DDF1:000A` | `0x5DF1A` | `0xDDF1A` / `0x0DDF1A` | `92CB:03F0` | `B810 808E D8` |
| 5 | `B14B:0002` | `0x314B2` | `0xB14B2` / `0x0B14B2` | `930A:03E8` | `9A040037E9` |
| 6 | `D9BD:0009` | `0x59BD9` | `0xD9BD9` / `0x0D9BD9` | `9348:03F0` | `9A040037E9` |
| 7 | `B000:00DF` | `0x300DF` | `0xB00DF` / `0x0B00DF` | `9387:3E80` | `56 33F6 9A040037E9` |

`0240` `RETF` at `02EE` enters these. A later `RETF` from the task
returns to `0262` and re-selects. A task that never `RETF`s stays
off the create epilogue (task 6).

---

## 2. Shared `E937:0004` — file `0x69374`

```
MOV AX, 8010
MOV ES, AX
MOV DS, AX
RETF
```

**PROVEN.** Tasks 2, 3, 5, 6, 7 call it first (task 7 after `PUSH SI` /
`XOR SI,SI`). Tasks 1 and 4 load `DS=8010` themselves (`MOV AX,8010` /
`MOV DS,AX`) and do not call `E937`.

`B060:0000` (file `0x30600`): `CX = [BP+6]`; `CALL FB00:0484`; `RETF`.
Timed wait. Tasks 5 and 6 use it.

---

## 3. Exits

### 0 — `FB00:05B2` — table walker

`LDS DI, CS:[0042]`; `CALL 05E9` (TCB walk; may `MOV [SI],0002`);
`LES SI, CS:[003E]` = `FB76:00AA` (one far ptr `FB76:00B2` then
`FFFF:FFFF`). `CX = [DI+8]`. If `CX=0`, `RETF` at `05E8` (file
`0x7B5E8`). Else loop `CALL 060B` / `0616` / `ADD SI,4`.

`FB76:00B2` (file `0x7B812`) is `CB` (`RETF`). Start `055F` counts that
slot into `[DI+8]`. **PROVEN:** the only exit of task 0 is `05E8 RETF`.

No far `CALL FB00:0396` uses `DL=0`. The ready is the near `CALL 0396`
at `FB00:05A3` with `DL=0`, from `05A0`, when `0586` sees `[DI+12h]`
hit zero. **PROVEN.** See [`amx_wait.md`](amx_wait.md).

### 1 — `B259:0006` — `8010` walker

`DS=8010`; `DX=1`; `CALL FB81:0089`. Loop at `001D` scans a word table
at `[BX+E410]`. Hits call `D213:0008` (`OUT 0x60` / `OUT 0x62`; device
**UNDETERMINED**). Sentinel path `0058` stores counts, `CALL FB81:00C7`,
`RETF` at `006F` (file `0x325FF`). **PROVEN:** sole exit is that `RETF`.

Later ready: `0396` `DL=1` at file `0x521A1`.

### 2 — `EC05:0000` — C far frame

`PUSH BP` / `MOV BP,SP` / `SI=[BP+6]`; `CALL E937:0004`.

| Path | Condition | Exit |
|------|-----------|------|
| `0020` | `[9757]?0` and `[A7AE]?0` | `INC [FFA6]`; `RETF` file `0x6C070` |
| `0042` | `[9757]=0` drain, or `[A7AE]=0` | `RETF` file `0x6C092` |

The drain (`0021`/`002C`) `CALL`s near `0043` (more flag tests,
`B19C:000E`) and loops on `[FFA6]`. `0043` is a callee, not an exit.

No `0396` `DL=2`. `04AC` `DL=2` at `0x55E67` and `0x56992`; `03B3`
`DL=2` at `0x5699C` (ready bit 0 on the success tail). First *create*
of slot 2 is **UNDETERMINED** until a bit-0 writer before the first
`04AC` is shown.

### 3 — `EAD0:000B` — C far frame

`PUSH BP` / `MOV BP,SP` / `SUB SP,6`; `CALL E937:0004`.
`CMP [E614],0x23` / `JB 006C` (file `0x6AD16` `72 4F`):
if `[E614] < 0x23`, skip to `LEAVE` / `RETF`. Else index
`[E5F9]` by `[E614]*0x18` and read `+FD0D` / `+11`
([`pad_note.md`](pad_note.md)), then `CALL CFB3:0008`.
Both paths `LEAVE` / `RETF` at `006D` (file `0x6AD6D`).
**PROVEN:** sole exit. The old “`>= 0x23` skips” reading
is retracted (`JB` is unsigned below).

Later ready: `0396` `DL=3` at file `0x56112`.

### 4 — `DDF1:000A` — wait worker

`DS=8010`; `CX=8`; `CALL FB00:0484` (block). Loop `0017`: if
`[D6A9]?0` then `CALL DA09:0000` / `0484` `CX=1` / `jmp 0017`. If
`[D6A9]=0`, `RETF` at `0031` (file `0x5DF41`). **PROVEN:** wait-loop
or that `RETF`.

Later ready: `0396` `DL=4` at file `0x55838`; `04AC` `DL=4` at
`0x55895`.

### 5 — `B14B:0002` — mode dispatch

`CALL E937:0004`; `MOV [E73A],1`; jump `00B3`. If `[A7AB]=0`, `RETF`
at `00BD` (file `0x3156D`). Else dispatch on `[A7B0] & 3Fh`
(`8` ? `0023`, `0Ah` ? `004D`, other ? `0075`): many `D6FA:0001`,
then `B060:0000` `CX=4` at `00A1`, then back to `00B3`. Path `0075`
can `MOV [A7AB],0` and `RETF` at `009E` (file `0x3154E`).

**PROVEN:** exits are `009E` and `00BD`. The `00A1` wait is a
suspension, not a task-body exit.

Later ready: `0396` `DL=5` at `0x566A9`, `0x56835`, `0x56853`.

### 6 — `D9BD:0009` — no `RETF`

`CALL E937:0004`; loop `000E`: `PUSH 14h` / `CALL B060:0000`; if
`[D6A1]=0` spin; else `CALL D9B5:0045`; clear `[D6A1]`; `jmp 000E`
at file `0x59C03` (`EB D9`). **PROVEN:** no `RETF` in this body.
Reset-path first select. Ready: `B03B` `0396` `DL=6`.

### 7 — `B000:00DF` — init then `RETF`

`PUSH SI` / `XOR SI,SI`; `E937`; then `DDF4:0002` / `0083`,
`D9B5:0073`, `BDF1:0000`, `E521:0006`, `B03B:01DA` / `01F7`,
`B1B1:*`, `CF0C:0006`, `D470:0948`, `D6E0:00F1`, `C425:0009`.
`RETF` at `01A6` (file `0x301A6`). **PROVEN:** sole exit of the
entry stream. Callee PGR/`OUT`s stay `U-XA-LIVE` / `U-PHYS`.

Ready on reset: `B03B` `0396` `DL=7`. Selected after task 6’s first
wait.

---

## 4. Ready map

| Slot | Reset (`B03B:000A`) | Later `0396` (file) | Notes |
|------|---------------------|---------------------|-------|
| 0 | no | near `0x7B5A3` | First ready is the IVT[8] tick |
| 1 | no | `0x521A1` | |
| 2 | no | none | `04AC`/`03B3` `DL=2`; first bit 0 **UNDETERMINED** |
| 3 | no | `0x56112` | |
| 4 | no | `0x55838` | also `04AC` `0x55895` |
| 5 | no | `0x566A9`, `0x56835`, `0x56853` | |
| 6 | yes | — | first `01EA` create |
| 7 | yes | — | first wait then create |

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7B5B2, 0x7B5E9)` | code — task 0 through `RETF` |
| `[0x7B812, 0x7B813)` | code — `FB76:00B2` `RETF` stub |
| `[0x32596, 0x32600)` | code — task 1 through `006F RETF` |
| `[0x6C050, 0x6C093)` | code — task 2 through `0042 RETF` |
| `[0x6AD0B, 0x6AD6E)` | code — task 3 through `006D RETF` |
| `[0x5DF1A, 0x5DF42)` | code — task 4 through `0031 RETF` |
| `[0x314B2, 0x3156E)` | code — task 5 through `00BD RETF` |
| `[0x59BD9, 0x59C05)` | code — task 6 loop (already opened) |
| `[0x300DF, 0x301A7)` | code — task 7 through `01A6 RETF` |
| `[0x69374, 0x6937B)` | code — `E937:0004` |
| `[0x30600, 0x3060D)` | code — `B060:0000` |

`D213`, `D6FA`, `DA09`, `D9B5`, `B03B:01DA`, and the rest of the
task-7 chain stay unowned until a named slice needs them.

---

## What this note does *not* prove

- That tasks 0–5 run on reset (they do not; only 6 then 7).
- First ready of slots 0 and 2.
- Purpose of `[9757]`, `[A7AE]`, `[A7AB]`, `[D6A9]`, `[D6A1]`.
- `D213` DSP port meaning.
- Calling convention as a whole-image rule (D8). Tasks 2/3 use a
  C far frame (`[BP+6]`); that is one data point, not the dominant
  convention.
