# Pad / note assignment UI — D20 remainder

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Names the owned assign screen and the 64-slot note table
accessors. The physical pad-hit path stays open (`U-PANEL-ROM`,
`U-TE7774`). The `+0054` `50L`..`50R` block is pan, not pads
([`pan_table.md`](pan_table.md)).

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the software assign path from slot index to note |
| Observable | `C44E:0119` title `Assign Pads to Note Numbers`; `D9F2:000C` / `0072` |
| Inputs | `[D6AC]` 0..0x3F; `D9F2` `[BP+6]` index; `0072` `[BP+8]` note |
| Outputs | `D9F2:000C` returns a byte; `0072` stores a byte clamped `0x22`..`0x62` |
| Confidence | Screen strings, `[D6AC]` 0..0x3F, and `D9F2` encodings **PROVEN**. That the byte is a MIDI note **HYPOTHESIS** (range + ` = Note:`). Pad-hit writer of `[D6AC]` **UNDETERMINED** |
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
| `0187` | `0x44667` | `9A 0C 00 F2 D9` | `D9F2:000C`(`[D6AC]`) ? displayed note |
| `01A0` | `0x44680` | `68 59 50` | ` = Note:` then `B354:03B1` |
| `020D` | `0x446ED` | `9A 72 00 F2 D9` | `D9F2:0072` store |

`C887:09AC` is called with the note byte and stays unowned
(mid-hole). Do not BFS it.

`[D6AC]` is the slot shown after `Pad:` and passed to `D9F2`.
**PROVEN** as that dataflow. Who writes it from a pad hit is
**UNDETERMINED**.

---

## 2. Table accessors — `D9F2`

Both already owned.

`000C` (file `0x59F2C`): `SI=[BP+6]`. If `SI>=0x40`, `AX=0x23`.
If `[8375]!=0`, `AL=[SI+8376]`. Else `LES BX,[E5F9]`;
`AL=ES:[BX+SI+073E]`. **PROVEN.**

`0072` (file `0x59F92`): `SI=[BP+6]`, `DX=[BP+8]`. Clamp `DX` to
`0x22`..`0x62`. If `SI>=0x40`, return. Same two stores as `000C`.
**PROVEN.**

`8010:8375` / `8376` and `[E5F9]+073E` are RAM. The linear file
at `0x28375` is `0xFF` padding, not the live table.

---

## 3. Related owned `0x90` sites (not pad-hit)

`56D4:000A` (file `0x56D4A`): `LES BX,[BP+6]`; `AND ES:[BX],0xF8`;
`CMP AL,0x90`; on match take `ES:[BX+2]` and `CALL DA09:0000`.
That is a MIDI-status test on a far event, not a pad scan.

`53B2:003A` `CMP AL,0x90` follows `IN 0xAC` (SCSI window). Do not
read it as MIDI.

---

## 4. Still open

- Writer that sets `[D6AC]` from a pad hit or a MIDI note-on.
- Grammar of the 64 bytes at `[E5F9]+073E` / `8010:8376`.
- `C887:09AC` body (mid-hole).
- TE7774 / panel scan (D19).
