# D23 — Load / save (FDC `0xE8`, SCSI `0xA0`, IRQ3 demux)

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

`[PARTIAL]`. Owned code programs `0x00E8`/`0x00EA` and
`0x00A0-0x00BC`. IVT[0x0B] does not read those ports.
`CALLF D3A7:0108` at `0x547FC` is a gap with no owned caller.
Remaining: `U-V53A` pin and a µPD72069 datasheet not in this tree.

Reproduction: `python3 tools/v53_decode.py` (`follow_local` /
`decode_one`) and a read of `analysis/owner_ledger.json`. Second
PGR (file `0x7ACB4`) is live on the AMX path
([`pgr_live_after_amx.md`](pgr_live_after_amx.md)). XA=1.
Identity frames: 24-bit is 20-bit with a leading 0.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name already-owned FDC/SCSI port I/O and the IRQ3-shaped vector, and the observation that blocks D23 |
| Observable | `IN`/`OUT` encodings below; IVT[0x0B] plant; INT 42 FDC body; D3A7 SCSI bodies |
| Inputs | Linear image; second PGR; owner ledger as read-only |
| Outputs | This note. No ledger seed. TODO `[PARTIAL]` |
| Confidence | Instruction bytes and owned bounds **PROVEN**. Device effect **UNDETERMINED**. IRQ3 pin **UNDETERMINED** (`U-V53A`) |
| Hardware deferred | µPD72069 register meaning (datasheet not in this tree); MB89352 beyond port bytes; IRQ3 wire-OR |

MAME maps `0x00E8-0x00EB` to the FDC and `0x00A0-0x00BF` to SCSI,
and names IRQ3 as FDC **OR** SCSI. That map is the working decode,
not a silicon proof ([`address_model.md`](address_model.md)).
This note cites ports and instruction bytes only.

---

## 1. Question

What owned code talks to FDC port `0xE8` and SCSI port `0xA0`,
how IRQ3 is demultiplexed, and what still blocks a load/save
slice?

---

## 2. Already-owned readers and writers

All rows XA=1, second PGR. File = `(CS<<4+IP)&0x7FFFF`.

### 2.1 SCSI — `D3A7` and BIOS `0xA2`

`D3A7:0014` file `0x53A84`, 20-bit `0xD3A84`, 24-bit `0x0D3A84`,
PGR[52]=`0x0034` at `0x7AD1C`. Walk through `0032 RETF`
(file `0x53AA2`). `OUT 0xA2` / `IN 0xA2` (`E6 A2` / `E4 A2` at
`0x53A86` / `0x53A88`); on `AL==0xC0`, `OUT 0xA0,0x07` /
`OUT 0xAA,0` / `OUT 0xA2,0x08` (files `0x53A96` / `0x53A9A` /
`0x53A9E`). Owned `[0x53A84, 0x53A93)` + `[0x53A94, 0x53AAA)`
(1-byte `NOP` at `0x53A93`). **PROVEN.**

`D3A7:0033` file `0x53AA3`. `MOV AL,0x80` / `OUT 0xA2` /
`RETF` `0039` (file `0x53AA9`). Same `[0x53A94, 0x53AAA)`.
**PROVEN.**

`D3A7:003A` file `0x53AAA`. Owned `[0x53AAA, 0x53AC8)`.
`OUT 0xA4` twice, `CALLF FB00:0484`, `IN 0xAA`, `RET` `0057`.
**PROVEN.**

`D3A7:00B0` file `0x53B20`. Owned `[0x53B20, 0x53B78)`.
`OUT 0xA8/B8/BC/BA/A4`; poll `IN 0xA8` / `IN 0xAC` /
`IN 0xB0`; `RET` `0107` (file `0x53B77`). `IN 0xAC` then
`CMP AL,0x90` at `00EA` (file `0x53B5A`) is that poll, not
MIDI ([`pad_note.md`](pad_note.md)). **PROVEN** as encodings.

`D3A7:0108` file `0x53B78`. Owned `[0x53B78, 0x53C90)`.
More `0xA0-0xBC` `IN`/`OUT`. At `019D` (file `0x53C0D`,
`2E FF A7 3C 02`) `JMP CS:[BX+023C]`. Table
`[0x53CAC, 0x53CBC)` is owned data. This note does not
enter those eight IPs.

`F800:1AD4` file `0x79AD4`, 20-bit `0xF9AD4`, 24-bit
`0x0F9AD4`, PGR[62]=`0x003E` at `0x7AD30`. Plants
IVT[0x0B]/[0x40]/[0x42], then `IN AL,0xA2` / `AND 0xFE` /
`OUT 0xA2,AL` (files `0x79AFA` / `0x79AFE`). `RETF` `1B25`.
Owned inside `[0x79946, 0x79B26)`. Device effect of `0xA2`
**UNDETERMINED**. **PROVEN** as the stream
([`boot_reset_to_bios_banner.md`](boot_reset_to_bios_banner.md)).

### 2.2 FDC — INT 42, IVT[8], INT 40 slot 0

`F800:205E` file `0x7A05E`, 20-bit `0xFA05E`, 24-bit
`0x0FA05E`, PGR[62]=`0x003E`. Last writer of IVT[0x42]
(`1AD4`). Owned `[0x7A047, 0x7A094)` with `2047`.
`IN AL,0xE8` (file `0x7A077`); `OUT 0xE8,0x0E` (`0x7A085`);
wait `IN 0xE8` / `AND 0xC0` / `CMP 0xC0`; `IN AL,0xEA`
(`0x7A08F`); `IRET` `2093`. **PROVEN.** Image `INT 42`
sites: `D52A:004F` (file `0x552EF`), BIOS `1946`
(`0x79948`), later IVT[8] plant `FB93:0059` (`0x7B98B`).

`D52A:0008` file `0x552A8`, 20-bit `0xD52A8`, 24-bit
`0x0D52A8`, PGR[53]=`0x0035` at `0x7AD1E`. Resting
IVT[8]. Owned `[0x552A8, 0x552FE)`. `MOV DX,0x00E8` /
`IN AX,DX` / `AND AX,0x1800` (files `0x552DD` / `0x552E0` /
`0x552E1`), then `INT 42`, `OUT 0xC010,0x60`, `IRET`.
**PROVEN.** High-byte identity of that `IN AX` is
**UNDETERMINED**.

`F800:1B36` file `0x79B36` is IVT[0x40]. `AH<=7`:
`CALL CS:[SI]` with SI from `[0x79B26, 0x79B36)`
(8 near IPs). `follow_local` stops at that `CALLN_RM`.
Slot 0 `F800:1B82` (file `0x79B82`) `OUT 0xE8` /
`IN 0xE8` (files `0x79B92` / `0x79BAA`). Owned
`[0x79B82, 0x79C5C)` and `[0x79C5D, 0x79D2C)` cover
all eight table IPs as bytes. This note does not BFS
`CALL CS:[SI]`.

Owned `[0x79ED6, 0x7A047)` also holds `IN AX,0xE8` at
`F800:1F7E` (file `0x79F7E`) and `IN 0xEA`/`0xE8`.
`[0x680EB, 0x68181)` holds `OUT`/`IN 0xE8` and `IN 0xEA`
(files `0x680F4` / `0x68108` / `0x68110`). No `CALLF`
into that last span. CS for it is **UNDETERMINED**.

### 2.3 IVT[0x0B] — not a port demux

`F800:2047` file `0x7A047`, 20-bit `0xFA047`, 24-bit
`0x0FA047`, PGR[62]=`0x003E`. Planted by `1AD4` at
`0000:002C`. Owned `[0x7A047, 0x7A094)`.

```
PUSH AX / DX / DS
DS = 06DD
MOV BYTE [0009], 1          ; file 0x7A04F
POP DS
MOV DX, 0xC010 / MOV AL, 0x63 / OUT DX, AL
POP DX / AX / IRET          ; file 0x7A05D
```

No `IN`/`OUT` of `0xE8-0xEB` or `0xA0-0xBF`. **PROVEN.**
That `AL=0x63` is 8259 specific-EOI for IR3 is
**HYPOTHESIS** (`U-C0XX`, `U-V53A`). Slot meaning stays
`U-V53A` ([`ivt_inventory.md`](ivt_inventory.md)).

### 2.4 DGROUP labels, not the engine

Disk-label table `[0x205FC, 0x20668)`: `FLOPPY DISK` then
`SCSI PART A`..`Z` (first string file `0x20F9C`). Owned
inside `[0x20000, 0x27C92)`. **PROVEN** as a pointer table
([`string_scan.md`](string_scan.md)). `Load/Erase/Rename Files`
(file `0x22206`) and `Save a Sequence` (file `0x2658E`) are
the same DGROUP pool. A paint string is not a load/save
transfer.

---

## 3. Bounds

| File range | Owner (ledger) | This note |
|------------|----------------|-----------|
| `[0x53A84, 0x53AAA)` | `transfer_scan.md` | `D3A7:0014` / `0033` SCSI |
| `[0x53AAA, 0x53AC8)` | `transfer_scan.md` | `D3A7:003A` |
| `[0x53AC8, 0x53B20)` | `transfer_scan.md` | `D3A7:0058` `0xC0xx` (not `0xA0`/`0xE8`) |
| `[0x53B20, 0x53B78)` | `transfer_scan.md` | `D3A7:00B0` |
| `[0x53B78, 0x53C90)` | `transfer_scan.md` | `D3A7:0108` prefix through `JMP CS:[BX+023C]` |
| `[0x53CAC, 0x53CBC)` | `transfer_scan.md` | that jump table; dests not entered |
| `[0x552A8, 0x552FE)` | `transfer_scan.md` | `D52A:0008` `IN AX,0xE8` / `INT 42` |
| `[0x680EB, 0x68181)` | `transfer_scan.md` | owned `0xE8`/`0xEA` bytes; no far entry |
| `[0x79946, 0x79B26)` | `ivt_inventory.md` | `1AD4` including `0xA2` |
| `[0x79B26, 0x79B36)` | `ivt_inventory.md` | INT 40 8 near IPs |
| `[0x79B82, 0x79C5C)` | `transfer_scan.md` | INT 40 dests `1B82`/`1BB1`/`1BB5`; slot 0 `0xE8` |
| `[0x79C5D, 0x79D2C)` | `transfer_scan.md` | INT 40 dests `1C98`..`1D08` |
| `[0x79ED6, 0x7A047)` | `transfer_scan.md` | more BIOS `0xE8`/`0xEA` |
| `[0x7A047, 0x7A094)` | `transfer_scan.md` | `2047` + `205E` |
| `[0x20000, 0x27C92)` | `copy_7c92.md` | disk-label + load/save strings |

No new seed. `D3A7:0008` (`INT 40` / `RETF`, file `0x53A78`)
is a gap. `CALLF D3A7:0108` at file `0x547FC` is a gap.
`INT 40` immediates at `0x4F214` and several other files
are gaps.

---

## 4. Missing observation (blocks D23)

1. IRQ3 demux. Resting IVT[0x0B] never reads `0xE8` or
   `0xA0`. FDC service is `INT 42` (`205E`) from IVT[8]
   (`D52A:0008`). SCSI service is `D3A7` polls. The pin that
   raises slot `0x0B` is `U-V53A`. MAME’s FDC-OR-SCSI wire
   is not a Vailixi instruction fact. A board capture of
   IRQ3, or the NEC ICU init that pins vector base, is the
   missing observation.
2. Device effect of the proven `AL`/`AX` values on `0xE8-0xEA`
   and `0xA0-0xBC`. No µPD72069 datasheet is in this tree
   (`README.md`). `03-peripherals/Fujitsu_1989_SCSI_Product_Guide.pdf`
   is product context, not a register map applied to these
   exact writes.
3. `CALLF D3A7:0108` at file `0x547FC` is `9A 08 01 A7 D3`
   (opcode `9A`, two imm16: IP `0x0108`, CS `0xD3A7`). It sits
   in gap `[0x54787, 0x54807)`. Owned-code `CALLF`/`JMPF` into
   that gap: **zero**. Do not seed. `D3A7:0008` (`CD 40` INT
   imm8 `0x40` / `CB` RETF, file `0x53A78`) is gap
   `[0x53A75, 0x53A7C)` with the same zero count.

The `JMP CS:[BX+023C]` dests are already owned. They were
unread in this note; they are read in §5. They only add more
`0xA0-0xBC` encodings. Device effect stays the datasheet.

D23 is `[PARTIAL]`. Remaining observation: the IRQ3 pin
(`U-V53A`) and a µPD72069 datasheet not in this tree.

---

## 5. 2026-09-22 — owned JMP dests and gap call

Table `[0x53CAC, 0x53CBC)` words, CS `D3A7`. 20-bit is
`0xD3A70+IP`. File is `0x53A70+IP`. XA=1, PGR slot 52 word
`0x0034` at file `0x7AD1C`, so 24-bit equals the 20-bit
address. Memory order, two slots share `0220`:

`01A2`, `01B4`, `01C6`, `01D8`, `0220`, `0220`, `0207`, `01EC`.

`2E FF A7 3C 02` at `019D` (file `0x53C0D`): CS: prefix, `FF /4`
ModR/M `A7` = mod=2, /4=JMPN, rm=BX, disp16 `0x023C`. Not followed
as a transfer. Each dest IP is already `code`. `follow_local` from
the table IPs (owned bodies, not a gap seed):

| IP | File | First writes | Exit |
|----|------|--------------|------|
| `01A2` | `0x53C12` | `B0 00` writes AL, imm8 `0`; `E6 B0` OUT `0xB0`,AL; `CALLN 00B0` (`E8 FE FE` rel16 `-258`) | `EB CB` JMP `017F` (rel8 `-53`) |
| `01B4` | `0x53C24` | `B0 01` AL←1; `E6 B0` | JMP `017F` |
| `01C6` | `0x53C36` | `B0 02` AL←2; `E6 B0` | JMP `017F` |
| `01D8` | `0x53C48` | `B0 03` AL←3; `E6 B0` | JMP `017F` |
| `0220` | `0x53C90` | `B8 04 01` writes AX, imm16 `0x0104`; `EB 11` JMP `0236` | `023B RETF` file `0x53CAB`; no port I/O |
| `0207` | `0x53C77` | `B0 06` AL←6; `E6 B0` | JMP `017F` |
| `01EC` | `0x53C5C` | `B0 07` AL←7; `E6 B0`; also `E6 A4` OUT `0xA4` | JMP `017F` |

Poll at `0186` `E4 AA` IN AL,`0xAA` (writes AL). `A8 80` TEST AL,
imm8 `0x80`. `75 09` JNZ `0195` (taken ZF=0). Shared `023B RETF`.

INT 40 table `[0x79B26, 0x79B36)` words: `1B82`, `1BB1`,
`1BB5`, `1C98`, `1CAD`, `1CB8`, `1CEB`, `1D08`. Slot 0
`F800:1B82` file `0x79B82`, 20-bit `0xF9B82`, 24-bit
`0x0F9B82` (XA=1, PGR slot 62 word `0x003E` at file
`0x7AD30`). Entry is `2A C0` (`SUB AL,AL`) and four `A2`
stores. `B0 36` / `E6 E8` OUT `0xE8`,AL is at `1B90`.
`74 08` at file `0x79BA0` is `JZ 1BAA`. The flag comes
from `TEST word [0000],0x8000` (`F7 06 00 00 00 80` at
`1B9A`), not from `AL` after the `OUT`. The taken arm is `E4 E8` IN
AL,`0xE8`; `A8 10` TEST AL, imm8 `0x10`; `75 EA` JNZ
`1B9A`; `C3` at `1BB0`. **PROVEN.** `1BB1` is `A0 07 00`
then `C3`, not a `CALLN`. `1BB5`, `1C98`, `1CAD`, `1CB8`,
and `1CEB` `CALLN F800:1E81` (file `0x79E81`, owned
`[0x79E7D, 0x79ECF)`). `1D08` is `C6 06 04 00 00`, then
`CMP BL,3` / `73 11` `JAE 1D2B`, and `RET` at file
`0x79D2B`. Not a `CALLN`. `F800:205D` is `CF` IRET.
`208F` is `E4 EA` IN AL,`0xEA`.

`0x547FC` is not an owned-caller target. Remaining: `U-V53A`,
µPD72069 datasheet.

---

## 6. 2026-09-23 — MAME device maps

MAME master, not a datasheet. No ledger seed.

`upd72065_device::map`, which `upd72069_device` does not override:
offset 0 is main-status read / auxiliary-command write; offset 1
is the FIFO. The MPC window starts at `0xE8`, so `0xE8` is offset
0 and `0xE9` is offset 1. `0xEA` is offset 2. That offset is
absent from the map. Owned `IN AL,0xEA` at `F800:208F` (file
`0x7A08F`) and the other owned `0xEA` reads therefore have no
register in this model. **HYPOTHESIS** for the map. The bytes
stay **PROVEN**.

`upd72069_device::auxcmd_w` comment marks `0x0E` (and the same
low nibble at higher high-nibbles) as motor enables. Motor `i`
follows bit `i+4`, active low on `mon_w`. `F800:205E` writes
`OUT 0xE8,0x0E` (file `0x7A085`). `0x0E` has bits 7–4 clear, so
every `mon_w` is called with 1. **HYPOTHESIS.** `F800:1B90`
writes `OUT 0xE8,0x36` (`B0 36` / `E6 E8`, §5).
`0x36` is that function’s software-reset case. **HYPOTHESIS.**

`D52A:0008` `IN AX,0xE8` / `AND AX,0x1800` keeps high-byte bits
3 and 4. The driver’s `fdc_hc365_r` returns
`floppy_is_hd() ? 0x04 : 0` combined with disk-change. It does
not drive bits 3 and 4. The header comment names those bits as
footswitches. The ROM test and the function that MAME runs
disagree. **HYPOTHESIS** for the function. The `AND` is
**PROVEN**.

SCSI `mb89352_device::map`: device `0x00` `bdid`, `0x02` `scmd`,
`0x0A` `dreg`. Added to `0xA0`, the owned `0xA0` / `0xA2` /
`0xAA` ports are those three. `F800:1AD4` `IN 0xA2` / `AND AL,0xFE`
/ `OUT 0xA2` clears `scmd` bit 0, which the header calls term
mode. **HYPOTHESIS.**

`IVT[0x0B]` `OUT 0xC010, AL=0x63` lands on the ICU once
`IULA=0x10`, `OPHA=0xC0`, and `OPSEL` bit 1 are the FAC0 values
and `SCTL` bit 0 selects 8-bit spacing (`notes/d22_sampling.md`
§7.1). A 8259 command `0x63` is specific EOI for IR3 in that
model. **HYPOTHESIS.** The pin that raises IRQ3 is still
unmeasured (`U-V53A`). `upd765.cpp` is not a µPD72069 datasheet.
