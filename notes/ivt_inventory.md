# IVT inventory — reset path through `B03B:000A`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D5 for the reset path through first `01EA`. Later `0347` plants
stay listed as writers, not as this-trace state.

Reproduction: `python3 tools/verify_boot_slice.py`.

Live IVT after `BRKXA` is work RAM `0000:0000` = 24-bit `0x300000`
(second PGR page 0 frame `C0`). ROM file `[0x00000,0x00054)` is only
the XA=0 template.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name every IVT slot’s last writer and target on the reset path |
| Observable | 256 far pointers in work RAM; 219 of them are `F800:1952` `IRET` |
| Inputs | FAC0 RAM clear; BIOS fill; `1AD4`; AMX start; `B03B:000A` |
| Outputs | Table below. Vector meaning (`U-V53A`) is not assigned |
| Confidence | Plants **PROVEN**. IRQ line identity **UNDETERMINED** |
| Hardware deferred | Which pin hits which slot (`U-PHYS`, `U-V53A`) |

---

## 1. ROM templates (XA=0 only)

| Slot | File | CS:IP | Used by |
|------|------|-------|---------|
| 0x11 | `0x00044` | `FAC0:001F` | `BRKXA 0x11` |
| 0x12 | `0x00048` | `FAC0:024F` | `RETXA 0x12` continue |
| 0x14 | `0x00050` | `FAC0:0134` | `BRKXA 0x14` |

`[0x00000,0x00044)` and `[0x0004C,0x00050)` are `0xFF`. After XA=1 these
bytes are not the live IVT.

---

## 2. FAC0 RAM plants

After the 512 KiB clear (`ES=0` under the first PGR):

```
FAC0:0061  MOV AX, 01A4
           MOV BX, 0040
           MOV [BX], AX / MOV [BX+2], CS    ; IVT[10h] = FAC0:01A4
FAC0:0094  MOV AX, 00A2
           MOV BX, 0048
           MOV [BX], AX / MOV [BX+2], CS    ; IVT[12h] = FAC0:00A2
           RETXA 0x12
```

The previous note that this was `IVT[2]` at `0000:0008` is **retracted**.
`BX=0040` is slot `0x10`. BIOS later skips `DI=0040` so this plant survives.

`FAC0:01A4` (the slot-`0x10` handler) writes `IVT[12h]=FAC0:01BD`,
`RETXA 0x12`, `OUTSW` the third PGR, `BRKXA 0x12`. That is a later
exception path, not the resting reset-path map.

---

## 3. BIOS `F800:000A` fill — file `0x7806C`

`DS=ES=0`. First loop `CX=20h`, `AX=1953`, `DI=0`:

```
if CX >= 18h and [DI]:[DI+2] != 0: skip      ; only FAC0 slots can hit
if DI == 40h: skip                           ; keep IVT[10h]
else [DI] = AX, [DI+2] = CS
AX += 3
DI += 4
```

Then `AX=1952`, `CX=E0h`, fill `DI=0080` through `03FC` (slots `20h–FFh`).

Overrides (still `CS=F800`):

| Slot | IP | File of store |
|------|-----|----------------|
| 8 | `1946` | `0x780AE` |
| 0x0F | `1952` | `0x780B8` |
| 0x41 | `0364` | `0x780C2` |
| 0x42 | `1952` | `0x780CC` |
| 0x43 | `16AA` | `0x780D6` |
| 0x45 | `0143` | `0x780E0` |
| 0x46 | `18D6` | `0x780EA` |

`1952` is a single `IRET` (file `0x79952`). `1953`, `1956`, … `19B0` are
3-byte `CALL 19B3` stubs. `19B3` does `OUT 0xC011,0xFF`, `INT 43` AX=1,
then the inline-string walker — unexpected-vector path. **PROVEN** as
bytes. Device effect of `0xC011` is `U-C0XX`.

`1946` (BIOS `IVT[8]`, later overwritten): `INT 42`; `OUT 0xC010,0x60`;
falls into `1952` `IRET`.

---

## 4. `F800:1AD4`

| Slot | CS:IP | RAM offset |
|------|-------|------------|
| 0x0B | `F800:2047` | `0000:002C` |
| 0x40 | `F800:1B36` | `0000:0100` |
| 0x42 | `F800:205E` | `0000:0108` (replaces BIOS `1952`) |

---

## 5. AMX `FB00:004E`

| Slot | CS:IP | Bytes at `0x7B05E` |
|------|-------|---------------------|
| 0 | `FB00:02F8` | `C7 05 F8 02` / `MOV [DI+2],CS` with `DI=0` |
| 4 | `FB00:02EF` | `C7 45 10 EF 02` |

Both share a tail: if `[DI+10h]` is `01h`–`7Fh`, rewrite the
`IRET` frame from hook `[current TCB + 18h + AX]`; else `IRET` to the
interrupted IP. `AX` is 0 at `02F8` and 4 at `02EF`. Frame layout:
[`irq_wrappers.md`](irq_wrappers.md).

---

## 6. `B03B:000A` via `FB00:0347`

`0347` plants `IVT[DL]=ES:BX` unless `DL` is 0 or 4 (AMX reserved).
Null `ES:BX` stores `FB00:0311` (`IRET`).

This-trace calls:

| DL | CS:IP | File | Entry bytes |
|----|-------|------|-------------|
| 8 | `D52A:0008` | `0x552A8` | `9a570100fb` |
| 0x0C | `D5DD:000C` | `0x55DDC` | `9a570100fb` |
| 0x0D | `D547:0067` | `0x554D7` | `9a570100fb` |
| 0x0E | `D5F3:000E` | `0x55F3E` | `9a570100fb` |

Each begins `CALL FB00:0157` (AMX interrupt wrapper). Slot meaning is
`U-V53A`.

---

## 7. Resting map after `B03B:000A`

219 slots = `F800:1952`. Named exceptions:

| Slot | CS:IP | Last writer |
|------|-------|-------------|
| 0 | `FB00:02F8` | AMX |
| 1 | `F800:1956` | BIOS ladder |
| 2 | `F800:1959` | BIOS ladder |
| 4 | `FB00:02EF` | AMX |
| 8 | `D52A:0008` | `B03B` (`0347`) |
| 0x0B | `F800:2047` | `1AD4` |
| 0x0C | `D5DD:000C` | `B03B` |
| 0x0D | `D547:0067` | `B03B` |
| 0x0E | `D5F3:000E` | `B03B` |
| 0x0F | `F800:1952` | BIOS override |
| 0x10 | `FAC0:01A4` | FAC0; BIOS skip `DI=40h` |
| 0x40 | `F800:1B36` | `1AD4` |
| 0x41 | `F800:0364` | BIOS |
| 0x42 | `F800:205E` | `1AD4` |
| 0x43 | `F800:16AA` | BIOS (`INT 43`) |
| 0x45 | `F800:0143` | BIOS |
| 0x46 | `F800:18D6` | BIOS (`INT 46`) |

Other `01h–1Fh` ladder slots follow `F800:(1953+3*n)` except 0, 4, 8,
`0Bh–0Eh`, `0Fh`, `10h` as above.

---

## 8. Later writers (not this-trace)

`9A 47 03 00 FB` (`CALL 0347`) also at:

| File | CS:IP | DL | This-trace? |
|------|-------|-----|-------------|
| `0x305B8` | `B03B:0208` | 9 ? `D61A:000A` | no; callee of task 7 `B03B:01F7` |
| `0x7B9B8` | `FB00:09B8` | 8 | no |

Those overwrite slots 9 and 8 after first select. D5 does not claim
the post-task-7 map.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x7806C, 0x780F4)` | code — BIOS IVT fill and overrides |
| `[0x79946, 0x79952)` | code — `1946` |
| `[0x79952, 0x79953)` | code — default `IRET` |
| `[0x79953, 0x79B13)` | code — ladder `CALL 19B3` through last stub |
| `[0x79B26, 0x79B36)` | data — INT 40 `CALL CS:[SI]` 8 near IPs (`AH<=7`) |
| `[0x7AC5C, 0x7AC6C)` | code — FAC0 `IVT[10h]` plant (inside FAC0 span) |
| `[0x7AC8F, 0x7AC9F)` | code — FAC0 `IVT[12h]` plant |

---

## What this note does *not* prove

- Which hardware IRQ uses slots 8/`0Ch`/`0Dh`/`0Eh` (`U-V53A`).
- `19B3` string bounds past the first `=======` bytes.
- Hook-table grammar at `TCB+18h` (D9).
- IVT state after task 7.
