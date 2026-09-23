# Address model — V53 on MPC3000

**Checked:** 2026-09-21 against Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.

A correct instruction at the wrong address contaminates everything built on
it. Keep these forms distinct.

## Address forms

| Form | Meaning | Example |
|------|---------|---------|
| Chip-file offset | Position inside one 256 KiB LS or MS image | do not cite as a CPU address |
| Linear-file offset | Byte in the interleaved 512 KiB image | `0x7FFF0` |
| 20-bit physical | `(CS << 4) + IP` while XA=0 | `FFFF:0000` ? `0xFFFF0` |
| 24-bit physical | PGR-translated address while XA=1 | linear `0x00044` ? `0x300044` after the first PGR load |
| I/O port | V53 `IN`/`OUT` address | `0x00E2`, `0xFFEA` |

Linear-file offset for any 20-bit address in the ROM window:

```
file = phys20 & 0x7FFFF
```

MAME maps `0x000000-0x07FFFF` with `mirror(0x80000)`, so
`0x00000-0x7FFFF` and `0x80000-0xFFFFF` show the same 512 KiB.

This is **not** the MPC2000XL map. On the 2000XL the 512 KiB OS image sits
only at the top of the 1 MB space (`phys = 0x80000 + file`). On the 3000 the
same 512 KiB is visible in both halves. Citing a 2000XL file offset as a
3000 physical address is a category error.

## Reset

V53 reset (MAME `nec_common_device::device_reset`, NEC V-series manuals):

```
PS/CS = 0xFFFF
IP    = 0x0000
XA    = 0
```

20-bit fetch address `0xFFFF0` = linear file `0x7FFF0`.

## Extended addressing

The V33/V53 core has a 24-bit bus and a 64-entry page table at I/O
`0xFF00-0xFF7E` (PGR). MAME `v33_translate`:

```
if XA:
    phys24 = (PGR[(addr20 >> 14) & 63] << 14) | (addr20 & 0x3FFF)
else:
    phys20 = addr20 & 0xFFFFF
```

`BRKXA imm8` is `0F E0 ib`. `RETXA imm8` is `0F F0 ib`. Both fetch
`IVT[imm8]` then switch XA. Vector fetch uses the **current** mode
([2kxl `v53_extended_mode.md`](/Users/peterwadams/Documents/2kxl/notes/v53_extended_mode.md);
NEC V-series instruction manual). Compatibility with 8086 decoding does not
make Capstone or `ndisasm` a complete V53 model. Those tools treat `0F E0`
as MMX and break the instruction stream.

## First PGR load (PROVEN)

FAC0:0000 writes 64 words from `CS:0256` (file `0x7AE56`) to `0xFF00-0xFF7E`,
then `BRKXA 0x11`. `v33_translate` shifts the **full 16-bit word**.
Slots 0–60 and 62–63 have high byte 0, so the old “low byte is the
frame” arithmetic coincides. Slot 61 is the only non-zero high byte
(`0x0140`). See [`pgr61.md`](pgr61.md).

| 20-bit pages | Word | 24-bit base | Object |
|--------------|------|-------------|--------|
| 0–39 | `00C0`–`00E7` | `0x300000`–`0x39C000` | work RAM (640 KiB of the 1 MiB HM658512 pair) |
| 40–60 | `0028`–`003C` | `0x0A0000`–`0x0F0000` | ROM mirror windows |
| 61 | `0140` | `0x500000` | NVRAM window. Consumer `D9B5` `ES=0xF400` **PROVEN**. Chip LC3517 **HYPOTHESIS** |
| 62–63 | `003E`–`003F` | `0x0F8000`–`0x0FC000` | high ROM (FAC0, reset stub) |

After this table, `0000:0044` is work RAM `0x300044`, not the ROM IVT
template. The first `BRKXA 0x11` still fetches ROM `0x00044` because XA is
still 0.

Later boot reloads PGR (tables at `FAC0:00B4` and `FAC0:01CF`) to cover more
of `0x300000-0x3FFFFF`. Those tables are **PROVEN** as bytes and as
`OUTSW` sources. On the reset path, BIOS, `F800:1AD4`, and AMX
`004E`/`01EA`/`0537` do not write `0xFF00-0xFF7E`. The **second** table
(`FAC0:00B4`) is live when AMX first selects a TCB and still live when
task 6 first waits and task 7 is selected. D510’s eight
callers and task 7’s 61 two-level walks do not `MOV DX` into
`0xFF00-0xFF7E`. A deeper callee is still **UNDETERMINED**
(`U-XA-LIVE`). See [`pgr_live_after_amx.md`](pgr_live_after_amx.md).

## Work RAM and NVRAM

| 24-bit range | Device | Evidence |
|--------------|--------|----------|
| `0x300000-0x3FFFFF` | 1 MiB work RAM | MAME map; PGR frames `C0`–`FF` span this window; service IC15/IC16 |
| `0x500000-0x500FFF` | NVRAM window (MAME `nvram` share). Chip LC3517 **HYPOTHESIS** | PGR[61]=`0x0140` ? `0x500000`. Consumer `D9B5` `ES=0xF400`; `ES:[03FE]` = `0x5003FE` **PROVEN**. See [`pgr61.md`](pgr61.md) |

PAL/GAL decode (IC25/IC29/IC31) is **UNDETERMINED**. The MAME map is the
working decode. A schematic or fusemap can refute it.

## On-die versus board I/O

Fixed V53 system I/O lives at `0xFFE0-0xFFFE` (MAME `v53_device::internal_port_map`,
NEC V53 user's manual). The reset stub and the FAC0 byte-OUT table program
those ports. Relocated on-die peripherals (TCU/ICU/SCU/DMAU) are placed by
`SULA`/`TULA`/`IULA`/`DULA`/`OPHA`/`OPSEL`. The FAC0 table writes
`OPHA=0xC0`, `DULA=0x00`, `IULA=0x10`, `SULA=0x20`, `TULA=0x30`,
`OPSEL=0x0F`. **PROVEN** as bytes. Bit-level meaning of each value is
**HYPOTHESIS** until checked against the NEC manual for this exact write
set.

Board I/O used on the first slice:

| Port | Device | Evidence |
|------|--------|----------|
| `0x00E0` / `0x00E2` | LC7981 data / status-control | MAME map; BIOS LCD put at file `0x7985A` |
| `0x0082` / `0x0084` / `0x0086` | 8255 `dioexp` | FAC0 OUT table; MAME `0x0080-0x0087` |
| `0x00FE` | 8255 `adcexp` | FAC0 OUT table; MAME `0x00F8-0x00FF` |
| `0xC000` / `0xC010` / `0xC011` / `0xC021`–`0xC023` / `0xC033` | relocated V53 + board window | FAC0 table and BIOS entry; decode **HYPOTHESIS** beyond “OPHA=C0” |

## Panel CPU

The µPD78C10 is **not** on the V53 program bus. Its 32 KiB EPROM is a
separate image, missing from this tree. Panel traffic reaches the V53
through TE7774 RX2/RX3 (MAME). Until that ROM is present, panel messages
are an external-interface boundary.
