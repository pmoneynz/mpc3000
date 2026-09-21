# Pad / note assignment UI — D20 remainder

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Names the owned assign screen, the 64-slot note table
accessors, and the owned writers of `[D6AC]`. Those writers
are note-to-slot remaps, not a pad-hit. The physical pad-hit
path stays open (`U-PANEL-ROM`, `U-TE7774`). The `+0054`
`50L`..`50R` block is pan, not pads
([`pan_table.md`](pan_table.md)).

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the software assign path from slot index to note |
| Observable | `C44E:0119` title `Assign Pads to Note Numbers`; `D9F2:000C` / `003D` / `0072` |
| Inputs | `[D6AC]` 0..0x3F; `D9F2` `[BP+6]` index or note; `0072` `[BP+8]` note |
| Outputs | `000C` returns a byte; `003D` returns a slot or `-1`; `0072` stores a byte clamped `0x22`..`0x62` |
| Confidence | Screen strings, `[D6AC]` 0..0x3F, `D9F2` encodings, remap stores, and `+0859` `0x23`..`0x62` **PROVEN**. That the table byte is a MIDI note **HYPOTHESIS** (range + ` = Note:`). Pad-hit writer of `[D6AC]` **UNDETERMINED** |
| Hardware deferred | Pad scan on the wire (D19 / P1 / P4) |

---

## 1. Screen — `C44E:0119`

File `0x445F9`. Already owned (`[0x445F9, 0x4479F)`). Sole exit
`02BE RETF`.

| IP | File | Bytes | Use |
|----|------|-------|-----|
| `0119` | `0x445F9` | `55 8B EC 83 EC 02 1E 68 32 50 9A 89 22 09 B5` | Title `+5032` `Assign Pads to Note Numbers` via `B509:2289` |
| `0152` | `0x44632` | `80 3E AC D6 00` / `80 3E AC D6 3F` | Clamp `[D6AC]` to 0..0x3F |
| `0177` | `0x44657` | `68 54 50` | `Pad:` then `B354:01C6` |
| `0187` | `0x44667` | `9A 0C 00 F2 D9` | `D9F2:000C`(`[D6AC]`) displayed note |
| `01A0` | `0x44680` | `68 59 50` | ` = Note:` then `B354:03B1` |
| `020D` | `0x446ED` | `9A 72 00 F2 D9` | `D9F2:0072` store |

`C887:09AC` is called with the note byte and stays unowned
(mid-hole). Do not BFS it.

`[D6AC]` is the slot shown after `Pad:` and passed to `D9F2`.
**PROVEN** as that dataflow. The clamp stores
(`C6 06 AC D6 00` at `0x44642` / `0x44741`) force 0 when the
byte is outside 0..0x3F. That is UI, not a pad-hit.

---

## 2. Table accessors — `D9F2`

All three already owned in `[0x59F2C, 0x59F92)` and
`[0x59F92, 0x59FCD)`.

`000C` (file `0x59F2C`): `SI=[BP+6]`. If `SI>=0x40`, `AX=0x23`.
If `[8375]!=0`, `AL=[SI+8376]`. Else `LES BX,[E5F9]`;
`AL=ES:[BX+SI+073E]`. Slot to byte. **PROVEN.**

`003D` (file `0x59F5D`): leftover cdecl after `000C`'s `003C
RETF`. `DI=[BP+6]`. If `DI<0x23`, `AX=0xFFFF` and `RETF`.
Else `SI=0`; loop `AX=000C(SI)`; if `AX==DI` return `SI`;
`INC SI`; while `SI<0x40`. Else `AX=0xFFFF`. Byte to slot.
**PROVEN.**

`0072` (file `0x59F92`): `SI=[BP+6]`, `DX=[BP+8]`. Clamp `DX` to
`0x22`..`0x62`. If `SI>=0x40`, return. Same two stores as `000C`.
**PROVEN.**

`8010:8375` / `8376` and `[E5F9]+073E` are RAM. The linear file
at `0x28375` is `0xFF` padding, not the live table.

---

## 3. ROM default and overlay

DGROUP `+0859` (file `0x20859`) is 64 bytes `0x23`..`0x62`.
Already owned as DGROUP data. **PROVEN** as the default
slot-to-byte table: pad 0 = `0x23`, pad 63 = `0x62`. That
range matches `0072`'s store clamp and `003D`'s `DI<0x23`
reject. `000C` returns `0x23` when `SI>=0x40` (the default
for slot 0).

`B21A:0033` (file `0x321D3`, already owned leftover after
`000F` `RETF`). `SI=0`; `AL=[SI+0859]`; `MOV [SI+8376],AL`;
`INC SI`; while `SI<0x40`; `RETF`. **PROVEN** copy of the
ROM default into the `8010:8376` overlay. Callers include
`CALLF B21A:000F` (which calls `0033`) and `CALLF B21A:0033`
at file `0x48722`.

`B21A:01DD` (file `0x3237D`, inside `0107` init):
`C6 06 75 83 00` — `MOV [8375],0`. **PROVEN.** No owned
store sets `[8375]` nonzero. The `000C` overlay-read arm
is encoded; who selects it is **UNDETERMINED**.

`CF37:04AD` (file `0x4F81D`, leftover after `044F` `RETF`,
already owned). At `056A` (file `0x4F8DA`): `ADD DI,0x073E`;
`MOV AL,[SI+8376]`; `MOV ES,[BP-2]`; `MOV ES:[DI],AL`;
loop `SI<0x40`. **PROVEN** as overlay to far-`+073E`
(the live table `000C` reads when `[8375]==0`).
`CALLF CF37:0002` at file `0x507AC` pins CS `CF37`.

`C44E:0137` `PUSH 0x8375` is an argument to `B354:01C6`
(`ADD SP,0x0E`). Not a store. Purpose of that arg is
**UNDETERMINED**.

---

## 4. Owned writers of `[D6AC]` (not pad-hit)

Whole-image `AC D6` has 18 hits. Owned stores:

| CS:IP | File | Encoding | Source of `AL` |
|-------|------|----------|----------------|
| `C44E` clamp | `0x44642` / `0x44741` | `C6 06 AC D6 00` | Immediate 0 |
| `B060:0504` | `0x30B04` | `A2 AC D6` | `D9F2:003D`(`[D6AD]`) |
| `5A50:00C5` | `0x5A5C5` | `A2 AC D6` | `D9F2:003D`(event note) |

`B060:035D` (file `0x3095D`, already owned) is a key
dispatcher. `[BP-1]` is compared to ASCII (`'D'`/`'N'`/…).
At `04F1` (file `0x30AF1`): `CMP [BP-1],0x4E`;
`MOV AL,[D6AD]`; `CALLF D9F2:003D`; `MOV [D6AC],AL`.
**PROVEN** as note-to-slot on the `'N'` arm. Not an `IN`.

`5A50:0039` (file `0x5A539`, leftover after `000E` `RETF`,
already owned in `[0x5A50E, 0x5A665)`). `LES BX,[BP+6]`;
`CMP ES:[BX],0xA0`; note at `ES:[BX+2]` is bounded
`0x23`..`0x62`. Status switch includes `CMP AX,0x90` at
`0071` (file `0x5A571`). The `0x90` arm (`0081`) pushes that
note, `CALLF D9F2:003D`, `MOV [D6AC],AL`. **PROVEN** as
MIDI note-on to slot. Not a pad scan.

`56D4:000A` writes `[D6AD]`, not `[D6AC]`. After
`AND ES:[BX],0xF8` / `CMP AL,0x90`, if `[7664]==0` it stores
`ES:[BX+2]` to `[D6AD]` (file `0x56D6F` `A2 AD D6`).
**PROVEN** on that arm. When `[7664]!=0`, `AL` is
`CFC6:0DA7`'s return (**UNDETERMINED**).

An owned inverse store at file `0x3DFFA` is
`CALLF D9F2:000C` / `MOV [D6AD],AL` (slot to note into
`[D6AD]`). Same pair, opposite direction.

No owned `IN` / `OUT` sits next to an `[D6AC]` store.

---

## 5. Related owned `0x90` sites (not pad-hit)

`56D4:000A` (file `0x56D4A`): `LES BX,[BP+6]`; `AND ES:[BX],0xF8`;
`CMP AL,0x90`; on match take `ES:[BX+2]` and `CALL DA09:0000`.
That is a MIDI-status test on a far event, not a pad scan.

`53B2:003A` `CMP AL,0x90` follows `IN 0xAC` (SCSI window). Do not
read it as MIDI.

---

## 6. Still open

- Writer that sets `[D6AC]` from a pad hit. Missing observation:
  a named consumer that stores a pad index from panel IPC or
  `IN` in `0xC0-0xDF`. Gap store `A2 AC D6` at file `0x555C9`
  is mid-gap after owned `[0x55575, 0x555B8)`. Gap start
  `3C 10 73 21` is not hole-start cdecl. Do not seed it.
- Third `CALLF D9F2:003D` at file `0x397B3` is in a gap. Do
  not seed it.
- Writer that sets `[8375]` nonzero (overlay select).
- Identity of the far object at `[E5F9]` (live table base).
- `C887:09AC` body (mid-hole).
- TE7774 / panel scan (D19).
