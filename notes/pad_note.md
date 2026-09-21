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
| Observable | `C44E:0119` title `Assign Pads to Note Numbers`; `D9F2:000C` / `003D` / `0072`; `[E5F9]` via `CA45:0008` / `DA04:002B`; `BE1A:026C` `Pgm`; `BE1A:0002` `16 Levels` |
| Inputs | `[D6AC]` 0..0x3F; `D9F2` `[BP+6]` index or note; `0072` `[BP+8]` note |
| Outputs | `000C` returns a byte; `003D` returns a slot or `-1`; `0072` stores a byte clamped `0x22`..`0x62` |
| Confidence | Screen strings, `[D6AC]` 0..0x3F, `D9F2` encodings, remap stores, `+0859` `0x23`..`0x62`, and `BE1A` Param `TUNING`..`FILTER` **PROVEN**. That `+11` is a MIDI note **HYPOTHESIS** (range + `Note:`). Pad-hit writer of `[D6AC]` **UNDETERMINED** |
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

## 4. Selected record — `[E5F9]`

`[E5F9]`:`[E5FB]` is a far pointer to one record in a
`DS=0x9770` array. That segment is RAM: linear file
`0x17700` is `0xFF` padding, not the live table.

`DA04:002B` (file `0x5A06B`, already owned). `CX=[BP+6]`;
`DS=0x9770`. If `CX>=[0002]`, `DX:AX=0`. Else
`AX=[0000]*CX+4`, `DX=0x9770`. **PROVEN:** word `+0` is
record size, word `+2` is count, records start at `+4`.

`CA45:0008` (file `0x4A458`, already owned). Index
`[BP+6]` must be `0..0x17`. `CALL DA04:002B`;
`MOV [E5FB],DX`; `MOV [E5F9],AX`; `MOV [E60E],AL`.
**PROVEN** as the selector that writes `[E5F9]`. Then
`CALLF C4C8:1D83` / `1C57` (mid-hole; do not BFS).

`D9F2:000C` when `[8375]==0` reads
`ES:[BX+SI+073E]` after `LES BX,[E5F9]`. The 64-byte
note table is field `+073E` of the selected record.
**PROVEN** as that dataflow.

`BE1A:026C` (file `0x3E40C`, already owned) is the
`Assign Note Var Slider (Pgm:  )` screen (`+3EE3` via
`B509:2289`). The sole `9A` consumer is `C425:0200`
(file `0x44450` `9A 6C 02 1A BE`). `BE40:000C` is the
same linear bytes under a different CS; that `9A` does
not exist. **PROVEN.** Labels `Note:` / `Param:` /
`Low range:` / `High range:` (`+3EAA` / `+3EB0` /
`+3F03` / `+3F0E`).

At `02FC` (file `0x3E49C`): `MOV AL,[E60E]`; `INC AL`;
printed via `B354:03B1`. **PROVEN** the title `Pgm:`
slot is the 1-based form of `CA45`'s `0..0x17` index.

At `0329` (file `0x3E4C9`): `LES BX,[E5F9]`;
`AL=ES:[BX+11]`; `MOV [996C],AL`; then `B354:03B1` with
bounds `0x22` / `0x62`. Field `+11` is the `Note:` value
(**HYPOTHESIS** a note number: same clamp as `D9F2:0072`).
`0523` (file `0x3E6C3`) writes `[996C]` back to
`ES:[BX+11]`. **PROVEN** as that store.

At `0380` (file `0x3E520`): if `[996C]>=0x23`,
`AX=[996C]*0x18`; `LES BX,[E5F9]`; `ADD BX,AX`;
`AL=ES:[BX+FD0D]`; `MOV [996B],AL`. **PROVEN** as
the `Param:` index. `+FD0D` is a 16-bit disp
(effective `(BX+AX+FD0D)&0xFFFF`). `055D` (file
`0x3E6FD`) writes `[996B]` back to `ES:[BX+FD0D]`.
**PROVEN** as that store.

`B354:01C6` is called with table `DS:0224` and index
`[996B]`. Directory `+0224`..`+0230` is four
`xxxx:8010` ptrs `TUNING` / `DECAY` / `ATTACK` /
`FILTER` plus a NULL (`+0234`). **PROVEN** as the
`Param:` names. DGROUP `+0204` is SMPTE
`24`/`25`/`30`/`29.97 DROP`, not this table. The
`PUSH 0x3E62` title is the NUL after `VELOCITY`,
not a name table. Nearby `(TUNING)` / `(DECAY)`
pool strings are not this consumer.

`03BA` (file `0x3E55A`): `MOV BX,[996B]`; `CMP BX,3`;
`JBE` then `SHL BX,1`; `JMP CS:[BX+0641]`. The
owned table at `BE1A:0641` (file `0x3E7E1`, already
`jump_table`) is `03C9` / `03F1` / `0418` / `043F`.
Those IPs load signed pairs into `Low range:` /
`High range:` temps (`[BP-4]` / `[BP-6]`, then
`B354:02BB`):

| `[996B]` | Name | Fields | IP | File |
|----------|------|--------|----|------|
| 0 | `TUNING` | `+12`/`+13` | `03C9` | `0x3E569` |
| 1 | `DECAY` | `+14`/`+15` | `03F1` | `0x3E591` |
| 2 | `ATTACK` | `+16`/`+17` | `0418` | `0x3E5B8` |
| 3 | `FILTER` | `+18`/`+19` | `043F` | `0x3E5DF` |

**PROVEN** as that map. `0x3EA41` is `BE40:0641`
(wrong CS) and sits in a gap. Do not seed it.

Do not BFS `B77C:20C5`, `B77C:202D`, or `C887:09AC`.

`CF37:04AD` also `CALLF DA04:002B` (file `0x4F828`)
before the overlay-to-`+073E` copy.

---

## 5. Sixteen Levels — `BE1A:0002`

File `0x3E1A2`. Already owned (`[0x3E1A2, 0x3E292)`).
Sole `9A` consumer is `C425:01F6` (file `0x44446`
`9A 02 00 1A BE`). Title `+3E97` `Assign '16 Levels'`
via `B509:2289`. **PROVEN.**

`0015` (file `0x3E1B5`): `MOV AL,[D6AD]`; copy to
`[BP-1]`; `B354:03B1` with bounds `0x23` / `0x62` and
label `Note:`. **PROVEN** this screen shows the selected
note already held in `[D6AD]`, not a pad-hit.

`0056` calls `B354:01C6` with table `DS:3E22` and index
`[81B3]`. Directory `+3E22` / `+3E26` is `VELOCITY` /
`NOTE VAR` plus a NULL. **PROVEN** as the `Param:` names.
`[81B3]` is RAM (linear `0x281B3` is `0xFF` padding).
The owned store is `B21A:01E2` (file `0x32382`, same
init as `01DD` `MOV [8375],0`): `MOV [81B3],0`.
**PROVEN** default is the `VELOCITY` arm. Gap store
`A2 B3 81` at file `0x5771E` is mid-gap. Do not seed it.

`BE1A:0203` (file `0x3E3A3`, already owned): if
`[81B3]==0`, `DX=4`. Else `AX=[BP+6]*0x18`;
`LES BX,[E5F9]`; `AL=ES:[BX+FD0D]`. `0002` passes the
`[D6AD]` note. **PROVEN:** `NOTE VAR` reuses the same
Param byte as `026C`; `VELOCITY` is the other arm
(return 4 indexes the empty `+3E2E` slot). Do not name
a 16-level algorithm from this. Do not BFS
`B77C:202D` / `20C5`.

`00A5` (file `0x3E245`): `B354:03B1` with label
`Center pad:` (`+3EB9`) and value `[E613]`, bounds
`0` / `0x0D`. **PROVEN** as that display. `CF37:0305`
(file `0x4F675`, leftover after `0304` `RETF`,
`CALLN` from `0259`) stores `MOV [E613],0x0D` and
`MOV [E614],0x23` (file `0x4F695` / `0x4F69A`).
Also zeros `[E60E]` (the `Pgm` index). **PROVEN** as
those defaults. Do not read `0x0D` as a pad-hit.

---

## 6. Owned writers of `[D6AC]` (not pad-hit)

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

## 7. Related owned `0x90` sites (not pad-hit)

`56D4:000A` (file `0x56D4A`): `LES BX,[BP+6]`; `AND ES:[BX],0xF8`;
`CMP AL,0x90`; on match take `ES:[BX+2]` and `CALL DA09:0000`.
That is a MIDI-status test on a far event, not a pad scan.

`53B2:003A` `CMP AL,0x90` follows `IN 0xAC` (SCSI window). Do not
read it as MIDI.

---

## 8. Still open

- Writer that sets `[D6AC]` from a pad hit. Missing observation:
  a named consumer that stores a pad index from panel IPC or
  `IN` in `0xC0-0xDF`. Gap store `A2 AC D6` at file `0x555C9`
  is mid-gap after owned `[0x55575, 0x555B8)`. Gap start
  `3C 10 73 21` is not hole-start cdecl. Do not seed it.
- Third `CALLF D9F2:003D` at file `0x397B3` is in a gap. Do
  not seed it.
- Writer that sets `[8375]` nonzero (overlay select).
- Writer that sets `[81B3]` nonzero (gap `0x5771E`;
  do not seed).
- Full `9770:` / `Pgm` record grammar past `+11` /
  `+12`..`+19` / `+073E` / `+FD0D`.
- `C887:09AC` body (mid-hole).
- TE7774 / panel scan (D19).
