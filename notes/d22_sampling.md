# D22 — Sampling / DSP register path (`0x0060`, DMA3)

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

`[PARTIAL]`. Owned code writes `0x0060-0x006C` and `0xC006`.
Device effect (`U-PHYS`) and whether `0xC006` is DMA3 (`U-C0XX`)
remain. Owned `CALLF D90C:0454` at file `0x48488` and
`CALLF D90C:0006` at file `0x484A4` land in gap
`[0x590C5, 0x59650)`. No owned `JMPF` does. Do not seed
those two targets.

Reproduction: `python3 tools/v53_decode.py` is the decoder;
facts below are from `follow_local` / `decode_one` on the linear
image and a read of `analysis/owner_ledger.json`. Second PGR
(file `0x7ACB4`) is the live map on the AMX path
([`pgr_live_after_amx.md`](pgr_live_after_amx.md)). XA=1.
Those CS pages are identity frames (`CS:IP` = 20-bit with a
leading 0 = 24-bit).

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name already-owned readers/writers of `0x0060-0x006F` and of `0xC006`, and the observation that blocks D22 |
| Observable | Reset-path `OUT`s to `0x0060/62/64/66` then `0x6A`; `CF92` also `OUT`s `0xC006` |
| Inputs | Linear image; second PGR; owner ledger as read-only |
| Outputs | This note. No ledger seed. TODO `[PARTIAL]` |
| Confidence | Instruction bytes and owned bounds **PROVEN**. `SCTL=0x11` **PROVEN** as the FAC0 byte. DMA offset meaning and L7A1045 effect **HYPOTHESIS** (MAME). Silicon effect **UNDETERMINED** (`U-PHYS`) |
| Hardware deferred | L7A1045 register meaning; 8237 channel map under this `DULA`/`OPHA`; wavedata bus |

---

## 1. Question

What owned code programs sampling — port `0x0060` and DMA3 — and
what is still missing to close D22?

MAME maps `0x0060-0x006F` to L7A1045 and names DMA3 as that DSP.
That map is the working decode, not a silicon proof
([`address_model.md`](address_model.md)). This note cites ports
and instruction bytes only.

---

## 2. Already-owned `0x0060-0x006F`

All rows XA=1, second PGR. File = `(CS<<4+IP)&0x7FFFF`.

### 2.1 Reset path — `B03B:000A` then `D20A`

`B03B:01BB` / `01C0` (file `0x3056B` / `0x30570`, 20-bit
`0xB056B` / `0xB0570`, 24-bit `0x0B056B` / `0x0B0570`,
PGR[44]=`0x002C` at `0x7AD0C`) `CALLF D20A:0008` / `004A`.
Then `B03B:01C5` `MOV AL,0x0E` / `01C7` `E6 6A`
(`OUT 0x6A,AL`, file `0x30577`). Owned
`[0x303BA, 0x3058A)`. **PROVEN.**

`D20A:0008` file `0x520A8`, 20-bit `0xD20A8`, 24-bit
`0x0D20A8`, PGR[52]=`0x0034` at `0x7AD1C`. Owned inside
`[0x51CEF, 0x5218F)`. Sole exit `0049 RETF` (file `0x520E9`).
`CX=0x0020` loop. Each pass `OUT DX,AX` after
`MOV DX,0x0060/62/64/66`:

| IP | File | Bytes | AX then port |
|----|------|-------|----------------|
| `0011` | `0x520B1` | `BA 60 00` `EF` | `0x0100+CX-1` → `0x0060` |
| `0018` | `0x520B8` | `BA 62 00` `EF` | `0` → `0x0062` |
| `001F` | `0x520BF` | `BA 64 00` `EF` | `0xFFFF` → `0x0064` |
| `0026` | `0x520C6` | `BA 66 00` `EF` | `0x000F` → `0x0066` |

`CMP BX,1` / `JE 0047` skips a second burst
(`AX=0x0A00+CX-1` → `0x60`, `3` → `0x62`, `0` → `0x64`).
`BX` is an input. This-trace value after `B03B:00E1`
`MOV BX,0x000E` is **UNDETERMINED** (`FB00:0347` may clobber).
**PROVEN:** the `OUT` encodings and the `RETF` bound.

`D20A:004A` file `0x520EA`, 20-bit `0xD20EA`, 24-bit
`0x0D20EA`. Sole exit `0097 RETF` (file `0x52137`).
`BX=0x0020` outer, `CX=8` inner. Each inner pass
`OUT`s `0x0060/62/64` (`AX=0x0700+BX-1`, `0`,
`(CX-1)&0x8000`). `CMP BX,1` / `74` at `0072`
(file `0x52112`) skips a second burst when `BX`
is 1. That burst writes `0x0700+BX-1`, `0`, and
`0` (`0x000F & 0x8000`) to those same ports.
**PROVEN.**

No `IN` in `D20A`. No RAM. No `0xC0xx`.

### 2.2 Task 1 — `B259:0006` then `D213` / `D21F`

`B259:003E` (file `0x325CE`, 20-bit `0xB25CE`, 24-bit
`0x0B25CE`, PGR[44]=`0x002C`) `CALLF D213:0008`. Owned
`[0x32596, 0x32600)`. **PROVEN.**

`D213:0008` file `0x52138`, 20-bit `0xD2138`, 24-bit
`0x0D2138`. Same `[0x51CEF, 0x5218F)`. Three `RETF`s:
`0029` / `003C` / `005E` (files `0x52159` / `0x5216C` /
`0x5218E`).

| BX test | Path | Ports |
|---------|------|-------|
| `< 0x40` (`83 FB 40` CMP BX, sign-extended imm8 `0x40`; `73 1D` JAE `002A` at `000B`, taken CF=0) | `000D` `8B 8F D3 E4` MOV CX,`[BX+E4D3]` (writes CX); `D1 EB` SHR BX,1 (writes BX); `OUT 0x60` `AX=0x0400+BX` (`B8 00 04` writes AX); `OUT 0x62` `AX=CX`; `OUT 0x64` `AX=0x8000` (`B8 00 80` imm16 `0x8000`) | writers |
| `0x40 <= BX < 0x80` (`81 FB 80 00` CMP BX, imm16 `0x0080` at `002A`; `73 0D` JAE `003D` at `002E`, taken CF=0) | `83 EB 40` SUB BX, sign-extended imm8 `0x40` (writes BX); `SHR BX,1`; `CALLF D21F:0008` | callee |
| `>= 0x80` | `81 EB 80 00` SUB BX, imm16 `0x0080` (writes BX); `SHR BX,1`; `OUT 0x60` `AX=0x0600+BX`; `D1 E3` SHL BX,1 (writes BX); `OUT 0x62` `[BX+E553]`; `OUT 0x64` `[BX+E513]` | writers |

`D21F:0008` file `0x521F8`, 20-bit `0xD21F8`, 24-bit
`0x0D21F8`. Owned `[0x521F8, 0x5227F)`. Sole exit
`008E RETF` (file `0x5227E`). Writes `0x0060/62/64`.
Reader: `003B` `MOV DX,0x0064` / `003E` `ED`
(`IN AX,DX`, file `0x5222E`). Then `AND AX,0x3FC0` /
`OUT DX,AX` back to `0x0064`. Stores
`MOV BYTE [BX+E599],0xFF` (`C6 87 99 E5 FF` at file
`0x5225C`) uses the unshifted `BX`. `D1 E3` at `0071`
(file `0x52261`) shifts `BX` first. The three word
stores are then `[BX+E410]`, `[BX+E450]`, and `[BX+E490]`.
`DS` is the caller’s. Task 1 set `DS=8010` (file `0x32596`).
`8010:E410` is 20-bit `0x8E510`, 24-bit `0x38E510` under
PGR[35]=`0x00E3` at `0x7ACFA` (work RAM). **PROVEN** as
those encodings. Units/lifetime **UNDETERMINED**.

### 2.3 `D1F7` — same owned blob

Inside `[0x51CEF, 0x5218F)`, PGR[52]=`0x0034`.

| CS:IP | File | 20/24-bit | Exit | Ports |
|-------|------|-----------|------|-------|
| `D1F7:000E` | `0x51F7E` | `0xD1F7E` / `0x0D1F7E` | `00E2 RETF` `0x52052` | many `OUT DX,AX` `0x60/62/64/66` |
| `D1F7:00E3` | `0x52053` | `0xD2053` / `0x0D2053` | `00ED RETF` `0x5205D` | `IN AX,0x68` / `OUT AX,0x68` (`E5 68` / `E7 68`) |
| `D1F7:00EE` | `0x5205E` | `0xD205E` / `0x0D205E` | `0125 RETF` `0x52095` | `OUT 0x60` / `0x66` / `0x6C` |

**PROVEN** as encodings. No `0xC0xx` in these three walks.

### 2.4 `CF92:000C` — `0x60` window and `0xC006`

`CF92:000C` file `0x4F92C`, 20-bit `0xCF92C`, 24-bit
`0x0CF92C`, PGR[51]=`0x0033` at `0x7AD1A`. Prologue is in
`[0x4F372, 0x4F944)`; `0025` through `017D RETF` (file
`0x4FA9D`) is `[0x4F945, 0x4FABC)`. One function: `JNZ 0025`
at `0017` (file `0x4F937`). No `JMP CS:[BX]`. **PROVEN.**

Immediate `OUT AX,imm8` to `0x60/62/64/66/68` (`E7 60` at
`0x4F979`, … `E7 68` at `0x4FA0D` / `0x4FA60`). Reader:
`0129` `E5 62` (`IN AX,0x62`, file `0x4FA49`). `0147 RETF`
(file `0x4FA67`) is the `000C` exit.

Same walk programs `0xC00x` (see §3).

Helpers, entered `PUSH CS` / `CALLN` so they `RETF`:

| CS:IP | File | Bound | Ports |
|-------|------|-------|-------|
| `CF92:0148` | `0x4FA68` | `0162 RETF` `0x4FA82` | `OUT AX` to `DX=0xC008`, then `XCHG` with `BX=0xC00F`, `IN AL` / `OR AL,CL` / `OUT AL` on `0xC00F`, then `OUT AX` back on `0xC008` |
| `CF92:0163` | `0x4FA83` | `017D RETF` `0x4FA9D` | same ports; `AND AL,CL` (`22 C1`) where `0148` does `OR AL,CL` (`0A C1`) |

### 2.5 `C4C8:1C3C` / `1C57`

Owned `[0x468BC, 0x46A43)`, PGR[49]=`0x0031` at `0x7AD16`.

`C4C8:1C3C` file `0x468BC`, 20-bit `0xC68BC`, 24-bit
`0x0C68BC`. `MOV BX,1`; `JMP 1C51`; loop while `BX<0x20`:
`AX=BX+0x0A00`, `OUT DX,AX` to `0x0060`, then `XOR AX,AX`
and `OUT DX,AX` to `0x006C` (`AX=0`), `INC BX`. `RETF`
`1C56` file `0x468D6`. **PROVEN.** The two ports do not
receive the same `AX`.

`C4C8:1C57` file `0x468D7` walks four more
`0x0060/62/64` `OUT DX,AX` bursts and `RETF` `1D82`
(file `0x46A02`). **PROVEN.**

### 2.6 Not port I/O

`D9F2:0089` `BA 62 00` (file `0x59FA9`) is `MOV DX,0x0062`, then
`CMP SI,0x40`. No `OUT` in that prefix
([`pad_note.md`](pad_note.md)). `C580:0050` (file `0x45850`)
and `C5A0:004D` (file `0x45A4D`) are `MOV DX,0x0064` /
`PUSH DX` / `PUSH SI` / `CALLF D9A2`, not `CMP DX,0x64`.
No `IN`/`OUT` in those six instructions. `E54C:015D`
file `0x6561D` is `MOV DX,0x0064`. `0160` file `0x65620`
is `IMUL DX` (`F7 EA`). That is arithmetic. **PROVEN** these prefixes are not
`0x0060-0x006F` I/O.

---

## 3. Already-owned `0xC006`

FAC0 `DULA=0x00` / `OPHA=0xC0` are table bytes
([`address_model.md`](address_model.md)). The 8237 channel-3
reading of `0xC006` is retracted in §7.

Owned writers of `MOV DX,0xC006` then `OUT`:

| CS:IP | File | 20/24-bit | Bytes | Next |
|-------|------|-----------|-------|------|
| `CF92:00C2` | `0x4F9E2` | `0xCF9E2` / `0x0CF9E2` | `BA 06 C0` | `8A 46 FE` `0C 30` `EE` (`OUT DX,AL`, file `0x4F9EA`) |
| `D3A7:0077` | `0x53AE7` | `0xD3AE7` / `0x0D3AE7` | `BA 06 C0` | `58` `0C 30` `EE` (file `0x53AED`) |
| `F800:1EDF` | `0x79EDF` | `0xF9EDF` / `0x0F9EDF`, `PGR[62]=0x003E` at `0x7AD30` | `BA 06 C0` | `8B C1` `0D 30 00` `EE` (file `0x79EE7`). No `0x0060` in `[0x79ED6, 0x7A047)` |
| `D90C:034D` | `0x5940D` | `0xD940D` / `0x0D940D`, `PGR[54]=0x0036` at `0x7AD20` | `BA 06 C0` | `EE` (`OUT DX,AL`, file `0x59410`). Walk from `0338` also `OUT`s `0x0060` |

`D3A7:0058` file `0x53AC8`, owned `[0x53AC8, 0x53B20)`,
exit `00AF RET` file `0x53B1F`. Also `OUT`s `0xC001/C004/C002/C00A/C008`.
No `0x0060` in that walk. Named as `0xC0xx` I/O in
[`transfer_scan.md`](transfer_scan.md). Do not BFS
`D3A7 JMP CS:[BX+023C]`.

`CF92:00C2` and `D90C:0338` each write both the
`0x0060` window and `0xC006` in one `follow_local`.
`D3A7:0058` and `F800:1EDF` do not write `0x0060`.

---

## 4. Bounds

| File range | Owner (ledger) | This note |
|------------|----------------|-----------|
| `[0x303BA, 0x3058A)` | `amx_first_dispatch.md` | caller of `D20A`; `OUT 0x6A` |
| `[0x32596, 0x32600)` | `amx_create_table.md` | caller of `D213` |
| `[0x468BC, 0x46A43)` | `transfer_scan.md` | `C4C8` `0x60/62/64/6C` |
| `[0x4F372, 0x4F944)` | `transfer_scan.md` | `CF92:000C` prologue |
| `[0x4F945, 0x4FABC)` | `transfer_scan.md` | `CF92` I/O through `017D RETF` |
| `[0x51CEF, 0x5218F)` | `transfer_scan.md` | `D1F7` / `D20A` / `D213` |
| `[0x521F8, 0x5227F)` | `transfer_scan.md` | `D21F:0008` |
| `[0x53AC8, 0x53B20)` | `transfer_scan.md` | `D3A7:0058` `0xC0xx` |

No new seed.

---

## 5. Missing observation (blocks D22)

1. Device effect of the proven `AX`/`AL` values on
   `0x0060-0x006C` / `0x6A`. No L7A1045 (or other) manual in this
   tree is applied to those exact writes (`U-PHYS`).
2. Proof that `0xC006` is DMA channel 3 under this
   `DULA`/`OPHA` set (`U-C0XX`). MAME’s DMA3→DSP wire is not a
   Vailixi instruction fact.
3. Unowned writers of the same ports sit in gaps with no
   seedable owned caller. Owned `code` contains four `CALLF`s into
   `[0x590C5, 0x59650)`: `D90C:01AD` at file `0x48078` (target owned),
   `D90C:0338` at `0x48493` (target owned), `D90C:0454` at `0x48488`,
   and `D90C:0006` at `0x484A4`. The last two stay unseeded. Twelve unowned `CALLF E7F5`
   sites in the gap around file `0x3E806` target
   `[0x68181, 0x68390)`. No `JMPF` and no owned call target
   that span.
   One `CALLF C6C2:1362` at
   file `0x5E796` (`9A 62 13 C2 C6`) targets owned
   `[0x47F82, 0x48209)`. Already seeded.
   Wavedata is not in the CPU map.

`8010:E4xx` words in `D213`/`D21F` are not a sample buffer
until consumers, units, and aliases are named. Do not BFS that
from this note.

D22 is `[PARTIAL]`. The MAME L7A1045 map and the V53 `SCTL`
decode are applied in §7. They are a model. Silicon effect of
the `0x0060` writes (`U-PHYS`) and a NEC manual for the DMA
offset (`U-C0XX`) are still absent.

---

## 6. 2026-09-22 — owned bodies re-read

`follow_local` / raw bytes. Second PGR, XA=1.

`D20A:0008` (file `0x520A8`): `B9 20 00` writes CX, imm16 `0x0020`.
`B8 00 01` writes AX, imm16 `0x0100`. `83 FB 01` CMP BX, sign-extended
imm8 `+1`. `74 18` JE `0047` (taken ZF=1, BX==1; `0047` LOOP `E2 C2`
rel8 `-62` → `000B`). `0049 RETF`.

`D20A:004A` (file `0x520EA`): `BB 20 00` writes BX, imm16 `0x0020`.
Inner `E2 E1` LOOP `0050` (rel8 `-31`, taken CX≠0 after DEC). First
`0x0064` burst: `8B C1` writes AX from CX; `48` DEC AX; `BA 00 80`
writes DX, imm16 `0x8000`; `23 C2` AND AX,DX (writes AX) =
`(CX-1)&0x8000`. `83 FB 01` / `74 1D` JE `0091` skips a second burst
when BX==1. That burst’s `0x0064` is `B8 0F 00` AND `0x8000` = 0, not
`(CX-1)&0x8000`. `75 B6` JNZ `004D` (taken ZF=0) is the BX outer loop.
`0097 RETF`.

`D213:002A` failed the old `0x8000` claim. File `0x5215A` is
`81 FB 80 00` (CMP BX, imm16 `0x0080`), not `81 FB 00 80`.
`003D` file `0x5216D` is `81 EB 80 00` (SUB BX, imm16 `0x0080`).
Corrected in §2.2.

`C4C8:1C3C`: `BB 01 00` writes BX, imm16 `1`. `EB 10` JMP `1C51`.
`83 FB 20` CMP BX, sign-extended imm8 `+0x20`. `7C EB` JL `1C41`
(taken SF≠OF, BX<`0x20` signed). `1C56 RETF`. `C4C8:1C57` does `LES BX,[BP+6]` at `1C5F` (file `0x468DF`) and loads `AL` from `ES:[BX]`.
`75 08` at file `0x468E9` is `JNZ 1C73`. A zero
byte `CALLN 1C3C` and `RETF`s at `1C72` (file
`0x468F2`). The other arm runs through `1D82 RETF`
file `0x46A02`; twelve `OUT DX,AX` (`EF`).

`CF92:0017` `75 0C` JNZ `0025` (taken ZF=0). `00C2` `BA 06 C0` writes
DX, imm16 `0xC006`; `8A 46 FE` writes AL from `[BP-2]`; `0C 30` OR AL,
imm8 `0x30`; `EE` OUT DX,AL.

Gap `[0x590C5, 0x59650)`: owned `CALLF`s at `0x48488` and
`0x484A4` enter it. No owned `JMPF`. Do not seed.
Wavedata is not on the CPU map. Remaining: `U-PHYS`, `U-C0XX`.

---

## 7. 2026-09-23 — MAME device models

Source is MAME master, not the Vailixi image. `MACHINE_NOT_WORKING`
stays irrelevant. No ledger seed.

### 7.1 `SCTL` selects the 71071 map

FAC0 byte-OUT table, file `0x7AED6`: `FE FF 11 00`. Port
`0xFFFE`, value `0x0011`. The table’s consumer is `OUT DX,AL`,
so `AL=0x11`. **PROVEN** as that byte. Following entries, already
listed in [`address_model.md`](address_model.md): `OPHA=0xC0`
(file `0x7AEDA`), `DULA=0x00` (`0x7AEDE`), `OPSEL=0x0F`
(`0x7AEEE`).

MAME `v53_device::SCTL_w` keeps `data & 0x1F`. Its comments:
bit 0 sets 8-bit peripheral spacing; bit 1 set selects
µPD71037/i8237 mode; bit 1 clear leaves µPD71071 mode; bit 4
is the SCU clock source. `0x11` has bits 0 and 4 set and bit 1
clear. **HYPOTHESIS** (those comments).

`v53_device::install_peripheral_io` in 71071 mode, with
`OPSEL` bit 0 set, installs `v5x_dmau_device` on
`(DULA & ~0x0F)` through `(DULA | 0x0F)`. `DULA=0x00` is
`0x00–0x0F`. `check_OPHA` admits a port whose high byte equals
`OPHA`, so that window is `0xC000–0xC00F`. **HYPOTHESIS.**

`upd71071_device::write` offset `0x06` stores the selected
channel’s address bits 23–16. The channel is `offset 0x01`
bits 1–0 (`0xC001`), not the port number. Offset `0x00` bit 0
is a soft reset and forces channel 0. FAC0 writes `0xC000`
with `0x01` then `0x00` (files `0x7AF3A`, `0x7AF3E`), so the
init leaves channel 0 selected. **HYPOTHESIS.**

The 8237 reading, in which `0xC006` would be channel 3’s
address, is the mode `SCTL` bit 1 would select. This image
writes that bit clear. That reading is retracted.

A NEC V53 / µPD71071 manual is still not in this tree
(`U-C0XX`). Later `OUT 0xC006` sites (§3) hit whichever
channel `0xC001` last selected. This section does not re-walk
them for that channel number.

### 7.2 `0x0060` under the L7A1045 map

MAME installs the L7A1045 at `0x0060`. Its map, as code:
`0x0060` voice select (low byte channel 0–31, high byte
register); `0x0062` / `0x0064` / `0x0066` the three 16-bit
lanes of that 48-bit register; `0x0068` control; `0x006C`
zeroes the selected register. `control_w` acts on bit 6
(DMA timer) and bit 8 (key on). The block comment’s other
control bits are stored. The voice-field diagram is credited
to reverse engineering and has an open delay-effect TODO.
**HYPOTHESIS.**

Reset `D20A:0008` (§2.1), `CX` from `0x0020`: `OUT 0x0060`
with `AX=0x0100+CX-1` is voice select, register 1, channel
`CX-1` (31 down through 0). `OUT 0x0062, AX=0`,
`OUT 0x0064, AX=0xFFFF`, `OUT 0x0066, AX=0x000F` fill that
register’s three lanes. `B03B:01C7` `OUT 0x6A, AL=0x0E`
(file `0x30577`) writes control bits 1, 2, and 3. Bits 6 and
8 are clear, so this model neither starts DMA nor keys a
voice on. **HYPOTHESIS** applied to the proven `OUT`s.

What those writes do on the board remains `U-PHYS`.
