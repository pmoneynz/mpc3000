# PGR page 61 — `U-PGR61`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes P7’s *consumer* question. All three FAC0 PGR tables map 20-bit
page 61 (`addr20` `0xF4000-0xF7FFF`) with frame `0x40` to 24-bit
`0x100000`. `D9B5` loads `ES=0xF400` and reads or writes that window.
The device at `0x100000` stays **UNDETERMINED**. It is not in the MAME
program map. Do not invent it.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name a software consumer of PGR page 61 |
| Observable | `D9B5:0007` `MOV AX,0xF400` / `MOV ES,AX` (file `0x59B57`) |
| Inputs | First/second/third PGR words at file+122 = `40 01` |
| Outputs | `ES:0000` reads and writes under `CS=D9B5`; `ES:[03FE]` compare/store |
| Confidence | Table words and `ES=0xF400` **PROVEN**. 24-bit object **UNDETERMINED** |
| Hardware deferred | What sits at `0x100000` (`U-PGR61` remainder, `U-PHYS`) |

---

## 1. The three tables

Slot 61 is word 61 (file offset +122). Little-endian `40 01` = `0x0140`.
Low byte `0x40` is the frame: `phys24 = (0x40 << 14) | (addr20 & 0x3FFF)`
= `0x100000` + 14-bit offset. High byte `0x01` is not interpreted.

| Table | File of PGR[61] | Bytes |
|-------|-----------------|-------|
| first `CS:0256` | `0x7AED0` | `40 01` |
| second `CS:00B4` | `0x7AD2E` | `40 01` |
| third `CS:01CF` | `0x7AE49` | `40 01` |

Neighbors: first/second `[60]=0x003C` `[62]=0x003E` `[63]=0x003F`
(ROM mirrors / high ROM). Third `[60]=0x00FC` (work RAM), `[62]`/`[63]`
unchanged.

Linear file `[0x74000, 0x78000)` (20-bit page 61 with XA=0) is 16 KiB
of `0xFF`. That is the padding window before BIOS `F800:000A`. Under
XA=1 those fetches do not use that file range. **PROVEN.**

No `MOV DX,0xFF7A` exists in the image. Page 61 is only written as
part of the three full-table `OUTSW`s. **PROVEN.**

---

## 2. Consumer — `D9B5` `ES=0xF400`

20-bit `0xF400:0000` = `0xF4000` = page 61, offset 0.

| CS:IP | File | Bytes | Use |
|-------|------|-------|-----|
| `D9B5:0007` | `0x59B57` | `B8 00 F4 8E C0` | `ES=0xF400`; checksum `ES:[SI]`; copy out via `LES DI,[BP+6]` |
| `D9B5:0055` | `0x59BA5` | `B8 00 F4 8E C0` | `ES=0xF400`; copy `LDS SI,[BP+6]` into `ES:[DI]` |
| `D9B5:0074` | `0x59BC4` | `B8 00 F4 8E C0` | `ES=0xF400`; `CMP ES:[03FE],0xAA`; else `MOV ES:[03FE],0x44` |

Bodies are already owned (D16 extras / `D9B5:0073`). **PROVEN** as
encodings and as ES loads.

`CF0C` `MOV AX,0xF500` (file `0x4F10C`) is an `AX` result after
`INT 41`, not an `ES` load. `C303` `PUSH 0xF7Ex` are DGROUP offsets.
Neither is a page-61 segment. A DGROUP dword `F714:E114` at `0x21436`
is a data lookalike (dest file `0x05254` is low `0xFF`).

---

## 3. Still open

The 24-bit window `0x100000-0x103FFF` has no named device. MAME does
not map it. A schematic, a bus capture, or a later writer that names
the object would close the remainder of `U-PGR61`.
