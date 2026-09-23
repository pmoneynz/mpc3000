# `0x7C92` copy — DGROUP grammar, consumers, writers

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D10 / `U-COPY-7C92`. Consumer *classes* for the string pool
are in [`string_scan.md`](string_scan.md). Per-screen meaning stays
D25. Mailbox record *meaning* at the `065B` overlays stays D11 /
`U-AMX-POOL`.

Reproduction: `python3 tools/verify_boot_slice.py`.

Second PGR (file `0x7ACB4`) is live after the copy. Dest figures use
that map (page 32/33 still frames `E0`/`E1`, same as the first PGR).
The *source* `A000` is ROM only while the first PGR is live.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Grammar of the `DS=A000` ? `ES=8010` object past the `AA 55` front; who addresses `8010:0000`; who writes it later; aliases |
| Observable | Unique `AA 55`; 21 `MOV AX,8010`; one `MOV AX,A000`; BSS zero from `8010:7C92` |
| Inputs | File `[0x20000, 0x27C92)`; first PGR at copy time; `E937:0004` |
| Outputs | Region table below; consumer / writer / alias lists |
| Confidence | Bounds, directory dword classes, segment-load catalog, and the writer classes **PROVEN**. Word `+2` = `0x0100` **UNDETERMINED**. `+0238` numeric *meaning* **HYPOTHESIS** |
| Hardware deferred | None |

---

## 1. Addresses

| Form | Source (`A000:0000`) | Dest (`8010:0000`) |
|------|----------------------|--------------------|
| File | `[0x20000, 0x27C92)` | RAM only (not in the image after boot) |
| 20-bit | `0xA0000` | `0x80100` |
| First PGR page | 40 frame `0x28` ? 24-bit `0x0A0000` | 32 frame `0xE0` ? 24-bit `0x380100` |
| Second PGR page | 40 frame `0xE8` ? 24-bit `0x3A0000` (RAM; **not** the ROM source) | 32 frame `0xE0` ? 24-bit `0x380100` (unchanged) |

The copy spans `8010:0000` .. `8010:7C91` = 20-bit `0x80100` ..
`0x87D91` = pages 32–33. First and second PGR both map those pages
to frames `E0`/`E1` ? 24-bit `[0x380100, 0x387D92)`. **PROVEN.**

`FAC0:0074` (file `0x7AC74`) is the only `MOV AX,A000`. It runs
*before* the second PGR `OUTSW`, so `DS=A000` is the ROM window.
**PROVEN.**

---

## 2. Grammar

This is a relocated writable DGROUP image, not a relocated code
body and not one uniform far-call table. The previous “string front,
rest UNDETERMINED” bound is replaced by the regions below.

| File / `8010` off | Bytes | Class |
|-------------------|-------|-------|
| `+0000` | `AA 55` | Unique in the image. No `CMP`/`MOV AX,55AA` consumer. **PROVEN** as bytes; runtime reader **UNDETERMINED** (none found) |
| `+0002` | `00 01` (`0x0100`) | Adjacent word. No proven consumer. **UNDETERMINED** |
| `+0004` .. `+05C8` | 369 dwords | Directory. 345 far ptrs `xxxx:8010`, 19 `0000:0000`, 5 other dwords |
| `+0238` .. `+024C` | 10 words | The five “other” dwords: `012C 0030 0032 003C 003C 0BB8 01E0 01F4 0258 0258` (300, 48, 50, 60, 60, 3000, 480, 500, 600, 600). **HYPOTHESIS:** tempo / SMPTE / display scalars. No consumer pinned |
| `+05C8` .. `+7C92` | rest of the copy | String pool (`ALL EVENTS`, `MTrk`, format strings, assign-screen text) mixed with initialized scalars. `+125C`..`+12CC` are eight-byte zeros that `065B` overlays |

Directory groups that resolve (DS=`8010`):

- `+0004` `ALL EVENTS` / `ALL EXCEPT` / `ONLY VIEW` / NULL
- `+0014` `NO` / `YES` / NULL
- `+0020` `OFF` / `ON` / NULL
- `+002C` / `+0038` `MASTER` / `SEQUENCE` / (`PROGRAM`) / NULL
- `+0054` .. `+01E4` pan names `50L` .. ` C ` .. `50R` (101
  slots), then NULL. Printer is `B354:01C6`. One caller passes
  title `Pan:`; three others pass a different title. Not drum-pad
  labels. See [`pan_table.md`](pan_table.md).
- `+01EC` `MIDI` / `DRUM`; SMPTE rate strings; `EARLIER` / `LATER`; `TUNING` / `DECAY` / `ATTACK` / `FILTER`

`+05C8` is `???????????` then more far ptrs and `ALL EVENTS` at
`+066C` (already tested). DGROUP has 1153 C-string candidates of
length >=4; consumer-established text is in
[`string_scan.md`](string_scan.md).
**PROVEN** as bytes and as the targets of the `8010` far ptrs.

---

## 3. Consumers of `8010:0000`

No stored `0000:8010` dword and no `LES`/`LDS` `[0000]`. Offset 0 is
the DGROUP base, not a far-pointer slot and not a checked magic.

`MOV AX,8010` occurs 21 times; each decoded site loads `DS` and/or
`ES` (or is the boot copy / BSS zero). **PROVEN.**

| File | CS:IP | What |
|------|-------|------|
| `0x7AC74` | `FAC0:0074` | `ES=8010`; `DS=A000`; `SI=DI=0`; `REP MOVSW` `CX=0x7C92/2` |
| `0x7AD34` | `FAC0:0134` | `DS=ES=8010`; `DI=7C92`; `REP STOSW` through `0xFFB7` |
| `0x69374` | `E937:0004` | `DS=ES=8010`; `RETF`. Tasks 2, 3, 5, 6, 7 |
| `0x32596` | `B259:0006` | Task 1: `DS=8010` (no `E937`) |
| `0x5DF1A` | `DDF1:000A` | Task 4: `DS=8010` (no `E937`) |
| `0x303C1` | `B03B:0011` | App init: `ES=A90B` first, then `DS=8010` |
| `0x3041F` | `B03B:0065` | `ES=8010`; `065B` overlays at `BX=125C`.. |
| `0x313A5` | — | `DS=8010`; `MOV [1D11],0` |
| `0x538D9` | — | `ES=8010`; scan `DI=D6B0` (BSS) |
| `0x5396A` | — | `DS=8010`; `SUB AX,AX`; `MOV ES,AX` leaves `ES=0` |
| `0x554DC` | — | `DS=8010`; `MOV [964F],0` (BSS) |
| `0x55DE1` | — | `DS=8010`; `TEST [9628],2` (BSS) |
| `0x55F04` | — | `ES=8010`; `0725` |
| `0x55F44` | — | `DS=8010`; flag tests in BSS |
| `0x561AF` | — | `DS=ES=8010` |
| `0x56A14` | — | `DS=ES=8010`; `IVT` leave path |
| `0x56F3F` | — | `ES=8010`; `MOV AX,ES:[12BE]`; `RETF` |
| `0x59068` / `0x590A5` | — | `DS=8010`; compare / store `92xx` (BSS) |
| `0x68260` | — | `DS=8010`; `MOV byte [7934],1` (inside the copy) |
| `0x6B5B7` | — | `ES=8010`; `MOV AL,[SI+3]` |

After `E937`, tasks keep `DS=8010` as the application DGROUP.
Offsets `? 0x7C92` (`[D6A9]`, `[A7AB]`, `[9757]`, `[FFA6]`, …) are
the BSS tail, not the ROM-sourced directory.

---

## 4. Later writers

| Writer | Range | Tag |
|--------|-------|-----|
| `FAC0:0074` `REP MOVSW` | `8010:[0, 7C92)` from `A000` | **PROVEN** — only bulk ROM?RAM copy |
| `FAC0:0134` `REP STOSW` | `8010:[7C92, FFB8)` | **PROVEN** — BSS only; does not touch the copy |
| `FB00:065B` when `ES=8010` | 8 bytes at `ES:BX` | **PROVEN** overlays at `BX` = `125C`, `1274`, `128C`, `12A4`, `12BC`, `12CC` (ROM image already zero there) |
| Direct `DS=8010` stores | individual globals | **PROVEN** examples: `[1D11]=0` (file `0x313AA`); `[7934]=1` (file `0x68265`). BSS examples: `[964F]`, `[9628]` |

No second `MOV AX,A000` and no second `MOV CX,0x7C92` copy.
`065B` first call at `B03B:001E` is `ES=A90B`, `BX=0` — it does
**not** write `8010:0000`. **PROVEN.**

A whole-image list of every `C6`/`C7`/`A3` to `disp < 0x7C92` is
not the grammar. Many such encodings are lookalikes (`JMP` rel16,
ASCII). The writer *classes* are the boot copy, the BSS zero, the
`065B` overlays, and per-global DGROUP stores.

---

## 5. Aliases

| Candidate | Verdict |
|-----------|---------|
| `A000:0000` | ROM source under the *first* PGR only. After the second PGR it is RAM `0x3A0000`, not the dest |
| `8010:0000` | Live dest under first and second PGR (`0x380100`) |
| `MOV AX,8000` (3 sites) | `0x30E61` returns `AX`; `0x52152` / `0x52214` `OUT 0x64,AX`. Not a segment load |
| `MOV AX,7FF0` (3 sites) | `OUT 0x64` / `OUT 0x62` immediates. Not a segment load |
| Other `MOV AX,80xx`/`83xx` | Immediate constants, not a covering data segment |

No second segment is proven to address `20-bit 0x80100`. After
`E937`, `DS=ES=8010` is the live pair.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x20000, 0x27C92)` | data — DGROUP image (directory + strings + initialized scalars) |
| `[0x27CA0, 0x27CB0)` | data — 16 zeros after the copy source |

`E937:0004`, `B03B:000A`, and `065B` are already owned.

---

## What this note does *not* prove

- A runtime reader of `8010:0000` = `55AA` (none found).
- Meaning of `+0002` = `0x0100`.
- A consumer of the `+0238` numeric island.
- Every string's screen meaning (D25). Consumer classes are D14.
- `065B` header fields past the eight-byte zero (`U-AMX-POOL`).
