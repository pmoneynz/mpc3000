# Patch-write banks

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-23.

These two filler ranges are the patch-write area. A later edit may
replace their bytes. They stay `data` / `padding` in the owner ledger.
This note does not create an `excluded_workspace` row.

Reproduction: `python3 tools/verify_boot_slice.py` asserts both ranges
are `0xFF` and that none of the three PGR tables selects them.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the file ranges a patch may overwrite |
| Observable | 147,372 `0xFF` bytes in two ranges; zero direct far targets from owned code |
| Inputs | Linear image; three PGR tables; owner-ledger code ranges |
| Outputs | The two banks below, plus the `0x0FFEF` landing rule |
| Confidence | All-`0xFF`, PGR non-selection, and direct `CALLF`/`JMPF` count **PROVEN**. All-paths unread **UNDETERMINED** at the sites in §4 |
| Hardware deferred | `U-PHYS` for NMI during an XA=0 interval. `U-PAL` for a board decode outside this image’s ROM mirror |

---

## 1. Banks

147,372 bytes. Half-open file ranges.

| Bank | File | Bytes | XA=0 20-bit | XA=0 mirror | XA=1 |
|------|------|------:|-------------|-------------|------|
| Low | `[0x00054, 0x20000)` | 130988 | `[0x00054, 0x20000)` | `[0x80054, 0xA0000)` | no page in the three tables |
| Page-61 image | `[0x74000, 0x78000)` | 16384 | `[0x74000, 0x78000)` | `[0xF4000, 0xF8000)` | page 61 is `0x500000`, not this file |

`file = phys20 & 0x7FFFF`. The mirror is MAME `mirror(0x80000)` on
`0x000000-0x07FFFF`. See [`address_model.md`](address_model.md).

XA=1 uses `phys24 = PGR[(addr20 >> 14) & 63] << 14 | (addr20 & 0x3FFF)`.
A table word selects the ROM file only when `word << 14` is below
`0x100000`; the file window is then `(phys & 0x7FFFF)` for `0x4000`
bytes. Walked on 2026-09-23 for all 64 words of:

| Table | File | `CS:IP` |
|-------|------|---------|
| first | `0x7AE56` | `FAC0:0256` |
| second | `0x7ACB4` | `FAC0:00B4` |
| third | `0x7ADCF` | `FAC0:01CF` |

Zero windows overlap either bank. **PROVEN.** Page 61 is `40 01` =
`0x0140` in all three, so `0x0140 << 14` = `0x500000`
([`pgr61.md`](pgr61.md)). **PROVEN.**

Chip images, even file bounds, so LS and MS get the same span.
LS is `07-rom/Vailixi 3.50/3.50 Vailixi (LSE).BIN`. MS is
`3.50 Vailixi (MSO).BIN`. Chip offset = file / 2.

| Bank | Each chip |
|------|-----------|
| Low | `[0x0002A, 0x10000)` = 65,494 bytes |
| Page-61 image | `[0x3A000, 0x3C000)` = 8,192 bytes |

Neighbors, measured:

| Edge | Bytes | What it is |
|------|-------|------------|
| file `0x50` | `34 01 C0 FA` | IVT[0x14] = `FAC0:0134`, ends at `0x54` |
| file `0x20000` | `AA 55` | DGROUP image |
| file `0x7800A` | `FA` | BIOS `CLI`. `[0x78000, 0x7800A)` is a 10-byte `0xFF` head in front of that instruction and is not part of the bank |

Direct far transfers: an instruction-aligned walk of the 866 owned
`code` ranges (50,809 instructions) found 2,483 `CALLF`/`JMPF` sites.
The absolute target `file = ((CS << 4) + IP) & 0x7FFFF` landed in
neither bank. **PROVEN** for those direct sites. A fake `CS = file >> 4`
is valid for that absolute target. It is not a near-target result.

---

## 2. Landing byte inside the low bank

File `0x0FFEF` is inside the low bank and is `FF` today.
`FFFF:FFFF` is 20-bit `(0xFFFF << 4) + 0xFFFF = 0x10FFEF`, masked to
`0x0FFEF`. ROM IVT[2] at file `0x08` is `FF FF FF FF`, so an XA=0 NMI
that uses that ROM vector fetches `0x0FFEF`. **PROVEN** as address
arithmetic. Whether the pin is asserted in that window is `U-PHYS`.

A patch writes one of these at file `0x0FFEF` (MS chip offset `0x7FF7`,
the byte is odd):

- `CF` (`IRET`), and payload may occupy every other byte of both banks.
- the existing `FF`, and payload does not begin in the bytes that
  instruction consumes. `FF` is a ModR/M opcode, so the following byte
  is part of it.

The other 147,371 bytes are payload once `0x0FFEF` is `CF`.

---

## 3. Filler that stays put

These `0xFF` runs are padding ([`padding.md`](padding.md)). At least
one of the three tables can still fetch them. They are not patch-write
banks.

| File | Bytes | Tables that select it |
|------|------:|------------------------|
| `[0x27CB0, 0x30000)` | 33616 | first |
| `[0x707C8, 0x74000)` | 14392 | first, second |
| `[0x78000, 0x7800A)` | 10 | first, second, third |
| `[0x7A78E, 0x7AC00)` | 1138 | first, second, third |
| `[0x7AF6A, 0x7B00C)` | 162 | first, second, third |
| `[0x7BA01, 0x7FF00)` | 17663 | first, second, third |
| `[0x7FF44, 0x7FFF0)` | 172 | first, second, third |

IVT image `[0x00000, 0x00054)`, one-byte aligns, the DGROUP `0xFF` tail,
and the 11 bytes after the reset jump stay structural. Unowned gaps
stay debt.

---

## 4. Still open

All-paths unread is **UNDETERMINED**. These sites can still install a
PGR word or fetch the low bank. They do not change the decision that
the two banks are the patch-write area. There is no measured crash rate.

| Site | File | Why it stays open |
|------|------|-------------------|
| `DC5B:00BA` | `0x5C66A` | `OUT DX,AL`. `DX` is `CS:[BX+0x12]`. Callers with `BL` past the compared range can load a word in `0xFF00-0xFF7E` from that segment |
| `D5DD:0163` | `0x55F33` | `OUT DX,AL` after `FB00:0725`, which overwrites the caller’s `DX` |
| XA=0 NMI | `0x0FFEF` | §2. Pin state is `U-PHYS` |
| `U-PAL` | — | A board decode outside `0x000000-0x0FFFFF` is not fixed by this image |

Jev, given the measured packet, labeled the low bank
`unmapped_reassignable` at probability 0.99 (confidence 0.99) and the
page-61 image `pgr_unselected_reassignable` at probability 0.95
(confidence 0.92) on the narrowed second call. Those scores repeat the
table above. They are not a separate measurement.
