# PGR page 61 — NVRAM window

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes P7 (24-bit target) and P8 (NVRAM consumer). All three FAC0 PGR
tables store word 61 as `40 01` = `0x0140`. This tree’s
`v33_translate` shifts the **full 16-bit word**:

```
phys24 = uint32_t(PGR[(addr20 >> 14) & 63]) << 14 | (addr20 & 0x3FFF)
```

`0x0140 << 14` = `0x500000`. That is the MAME NVRAM window
`0x500000-0x500FFF`. `D9B5` loads `ES=0xF400` and reads or writes
that window. A prior note used the low byte only (`0x40 << 14` =
`0x100000`); that contradicts the cited formula and is retracted.

Chip identity LC3517 is **HYPOTHESIS** (MAME comment). Do not invent
device behavior.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the 24-bit object behind PGR page 61 and its software consumer |
| Observable | `D9B5:0007` `MOV AX,0xF400` / `MOV ES,AX` (file `0x59B57`); `ES:[03FE]` at file `0x59BC4` |
| Inputs | First/second/third PGR words at file+122 = `40 01` |
| Outputs | `ES=0xF400` under XA ? `0x500000`; `ES:[03FE]` ? `0x5003FE` |
| Confidence | Table words, `ES=0xF400`, and `phys24 = word << 14` **PROVEN**. NVRAM window match **PROVEN** as this-tree MAME map. Chip LC3517 **HYPOTHESIS**. Record format / `CX` domain **UNDETERMINED** |
| Hardware deferred | LC3517 pinout and battery path (`U-PHYS`). Contents on a live board |

---

## 1. The three tables

Slot 61 is word 61 (file offset +122). Little-endian `40 01` = `0x0140`.

| Table | File of PGR[61] | Bytes | Word | `word << 14` |
|-------|-----------------|-------|------|----------------|
| first `CS:0256` | `0x7AED0` | `40 01` | `0x0140` | `0x500000` |
| second `CS:00B4` | `0x7AD2E` | `40 01` | `0x0140` | `0x500000` |
| third `CS:01CF` | `0x7AE49` | `40 01` | `0x0140` | `0x500000` |

Neighbors: first/second `[60]=0x003C` `[62]=0x003E` `[63]=0x003F`
(ROM mirrors / high ROM). Third `[60]=0x00FC` (work RAM), `[62]`/`[63]`
unchanged.

Slot 61 is the **only** PGR word with a non-zero high byte in all three
tables. Every other slot has high byte 0, so “low byte is the frame”
coincides there and fails only here. **PROVEN.**

Linear file `[0x74000, 0x78000)` (20-bit page 61 with XA=0) is 16 KiB
of `0xFF`. That is the padding window before BIOS `F800:000A`. Under
XA=1 those fetches do not use that file range. **PROVEN.**

No `MOV DX,0xFF7A` exists in the image. Page 61 is only written as
part of the three full-table `OUTSW`s. **PROVEN.**

---

## 2. 24-bit translate (PROVEN)

20-bit `0xF400:0000` = `0xF4000`. Page = `(0xF4000 >> 14) & 63` = 61.
Offset = `0xF4000 & 0x3FFF` = 0.

```
phys24(ES:0000) = 0x0140 << 14 | 0x0000 = 0x500000
phys24(ES:03FE) = 0x0140 << 14 | 0x03FE = 0x5003FE
```

Page 61’s 16 KiB window is `0x500000-0x503FFF`. MAME maps only
`0x500000-0x500FFF` (`mpc3000_map` + `NVRAM` share). `0x5003FE` is
inside that 4 KiB. Whether a later `CX` walk reaches `0x501000+` is
**UNDETERMINED**. Do not claim wrap or mirror.

Low-byte-only arithmetic (`0x40 << 14` = `0x100000`) is internally
inconsistent with `notes/address_model.md` § Extended addressing and
with `06-mame/cpu/nec.cpp` `v33_translate`. Retracted.

---

## 3. Consumer — `D9B5` `ES=0xF400`

| CS:IP | File | Bytes | Use |
|-------|------|-------|-----|
| `D9B5:0007` | `0x59B57` | `B8 00 F4 8E C0` | `ES=0xF400`; checksum `ES:[SI]` stride 2, `CX=[BP+0A]`; copy out via `LDS DI,[BP+6]` (`C5 7E 06`) |
| `D9B5:0055` | `0x59BA5` | `B8 00 F4 8E C0` | `ES=0xF400`; copy `LDS SI,[BP+6]` into `ES:[DI]` stride 2; store sum at `ES:[DI]` |
| `D9B5:0074` | `0x59BC4` | `B8 00 F4 8E C0 26 80 3E FE 03 AA` | `ES=0xF400`; `CMP ES:[03FE],0xAA`; if equal `MOV ES:[03FE],0x44` |

Bodies are already owned (D16 extras / `D9B5:0073`). **PROVEN** as
encodings and as ES loads. `0xAA`/`0x44` meaning is **UNDETERMINED**.

`CF0C` `MOV AX,0xF500` (file `0x4F10C`) is an `AX` result after
`INT 41`, not an `ES` load. `C303` `PUSH 0xF7Ex` are DGROUP offsets.
Neither is a page-61 segment. A DGROUP dword `F714:E114` at `0x21436`
is a data lookalike (dest file `0x05254` is low `0xFF`).

---

## 4. Still open

- Chip part LC3517 is MAME commentary, not a schematic readout
  (**HYPOTHESIS**).
- Record grammar and the caller `CX` domain.
- Bytes in `0x501000-0x503FFF` (page remainder past the 4 KiB map).
