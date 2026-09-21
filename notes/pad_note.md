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
After that store: `LES BX,[E5F9]` (file
`0x4A4AC`); `MOV AL,ES:[BX+11]` (file
`0x4A4B0`); `MOV DX,0x18` / `IMUL DX`
(file `0x4A4B8`); `ADD BX,AX`;
`MOV AL,ES:[BX+FD0D]` (file `0x4A4BF`);
`MOV [996B],AL` (file `0x4A4C4`); then
the already-named `CALLF D9C0:0006`.
**PROVEN** as the same `+11` /
`*0x18` / `FD0D` / `[996B]` path as
`BE1A:0329` / `0380`. Not a pad-hit.
Do not name the other copy dests.

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
**PROVEN** as that store. `CA45:0008` repeats
this load after the `[E5F9]` store (files
`0x4A4B0` / `0x4A4BF` / `0x4A4C4`).

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

Already-owned `D9C0:0006` (file `0x59C06`)
takes `[BP+8]`, rejects `>3` (file
`0x59C0F`), and `JMP CS:[BX+0095]`
(file `0x59C16`). Table at file
`0x59C95` is `001B` / `003F` /
`0053` / `0067`. Those dests
`LES [E5F9]` and load `+12`/`+13`,
`+14`/`+15`, `+16`/`+17`,
`+18`/`+19` (files `0x59C1B` /
`0x59C3F` / `0x59C53` /
`0x59C67`). **PROVEN** as the same
Param `0..3` pair map. Shared tail
`007F` is uninterpreted. Owned
callers: `BE1A:026C` (file
`0x3E79C`, pushes `[996B]`) and
`CA45:0008` (file `0x4A4CC`).
Gap `CALLF`s at `0x5564F` /
`0x556DB` / `0x55C0E` stay
unseeded.

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

Already-owned leftover `DC2A:0033` (file
`0x5C2D3`) branches to `0067`: `CMP
ES:[BX],0x90` (file `0x5C30A`); if
`[81B3]==0` (file `0x5C317`) it loads
event `+2` (file `0x5C321`). Sibling
`DC85:0047` (file `0x5C897`) starts a
loop at `0x23` (file `0x5C89F`) and
uses the same `[81B3]==0` gate (file
`0x5C8C4`). **PROVEN** as consumers
of the named VELOCITY default. Not a
pad-hit. Do not name the compared
RAM. Do not invent a 16-level
algorithm.

Already-owned leftover `DC2A:010A`
(file `0x5C3AA`) after `0033`'s
`0109 RETF`. `0033` `CALLF
DC3A:000A` (file `0x5C382`) is
this linear. `LES BX,[BP+6]`
(file `0x5C3AE`);
`MOV AL,ES:[BX+1]` (file
`0x5C3B1`); `AND CL,0xF8` /
`CMP CL,0xC0` (files `0x5C3BD` /
`0x5C3C0`); `CALLN 013B` (file
`0x5C3D0`). **PROVEN** as that
leftover dest and status mask.
Not a pad-hit. Do not name
`0281` / `013B`. Do not invent
`0xC0` meaning.

Already-owned leftover `DC85:011A`
(file `0x5C96A`) after `0047`'s
`0119 RETF`. `XOR SI,SI` (file
`0x5C976`); `CALLF DCE4:000C`
(file `0x5CA0A`); bound
`CMP SI,0x100` (file `0x5CA18`).
**PROVEN** as a second owned
caller of the named `0xF0` gate.
Not a pad-hit. Do not name the
packet bytes or RAM.

`BE1A:0203` (file `0x3E3A3`, already owned): if
`[81B3]==0`, `DX=4`. Else `AX=[BP+6]*0x18`;
`LES BX,[E5F9]`; `AL=ES:[BX+FD0D]`. `0002` passes the
`[D6AD]` note. **PROVEN:** `NOTE VAR` reuses the same
Param byte as `026C`; `VELOCITY` is the other arm
(return 4 indexes the empty `+3E2E` slot). Do not name
a 16-level algorithm from this. Do not BFS
`B77C:202D` / `20C5`.

Already-owned `0002` switch dest
`0105` (file `0x3E2A5`, table word
`0x3E39D`). `PUSH [BP-1]`;
`CS: CALLN 0203` (file `0x3E2AA`
`90 0E E8 F4 00`);
`MOV [BP-2],AL` (file `0x3E2B2`);
then `MOV AL,[81B3]` (file
`0x3E2C3`). **PROVEN** as the
read side that calls the named
`0203` FD0D helper with the
note. Not a pad-hit. Do not
invent a 16-level algorithm.

Already-owned `0002` switch dest
`0131` (file `0x3E2D1`, table word
`0x3E39F`, span `[0x3E292, 0x3E335)`).
`CMP [81B3],0` / `JZ` skips the
store on the VELOCITY default.
Else clamp `[BP-2]` to `0..3`
(file `0x3E2D8`); `AX=[BP-1]*0x18`;
`LES [E5F9]`; `MOV ES:[BX+FD0D],AL`
(file `0x3E2F4`). **PROVEN** as the
NOTE VAR write of that Param byte.
Not a pad-hit. Do not invent a
16-level algorithm.

`00A5` (file `0x3E245`): `B354:03B1` with label
`Center pad:` (`+3EB9`) and value `[E613]`, bounds
`0` / `0x0D`. **PROVEN** as that display. `CF37:0305`
(file `0x4F675`, leftover after `0304` `RETF`,
`CALLN` from `0259`) stores `MOV [E613],0x0D` and
`MOV [E614],0x23` (file `0x4F695` / `0x4F69A`).
Also zeros `[E60E]` (the `Pgm` index) and writes
`[E60F]=2` / `[E610]=2` (file `0x4F681` / `0x4F686`).
Then a 64-slot loop (`INC` / `CMP 0x40` at
`0x4F6C3`) stores `64 32 00 09` at `[E639]+i*4`
(file `0x4F6AF` `C6 87 39 E6 64`). **PROVEN** as
those defaults. Do not name the dword bytes.
Do not read `0x0D` as a pad-hit.

Create-table task 3 `EAD0:000B` (file `0x6AD0B`, already
owned) is a named consumer of `[E614]`. After
`E937:0004`, `CMP [E614],0x23` / `JB 006C` skips the
body when the byte is below the note floor. Else
`AX=[E614]*0x18`; `LES BX,[E5F9]`; `AL=ES:[BX+FD0D]`;
`ADD AL,0x90`; also `CMP ES:[BX+11],[E614]`. Then
`CALLF CFB3:0008`. **PROVEN** as that dataflow. Default
`[E614]=0x23` takes the body. `ADD AL,0x90` as MIDI
note-on **HYPOTHESIS**.

`CFB3:0008` (file `0x4FB38`, already owned in
`[0x4FAEB, 0x4FFFE)`). `LES BX,[BP+6]`;
`AX=ES:[BX] & 0xF8`; switch `0xB0` / `0x80` /
`0x90` / `0xC0` / `0xF0`. The `0x90` arm
(`009D`, file `0x4FBCD`) `CALLF CFC6:0007`
(already owned, same span). The `0xB0`
arm (file `0x4FBDD`) requires
`ES:[BX+2]==7`, stores `ES:[BX+3]` to
`[E739]`, and `MOV [D6AB],0x50` (file
`0x4FBEE`). **PROVEN.** Not `[D6AC]`.
Do not name `[D6AB]` / `[E739]`. The `0xC0`
arm (file `0x4FBF5`) pushes `ES:[BX+2]`
and `CALLF C887:1BE8` (file `0x4FBFF`
`9A E8 1B 87 C8`). That linear file is
`CA45:0008` (`0x4A458`), the already-named
`9770:` / `[E5F9]` selector. **PROVEN**
as that alias. Do not BFS `C887`. That
live `+2` stays in `0..0x17` is
**HYPOTHESIS**. The `0xF0` arm (file
`0x4FC09`) requires `ES:[BX+2]==0x47`
and `ES:[BX+5]` in `{0x45,0x46}`
(files `0x4FC16` / `0x4FC1D`), then
pushes `+8` / `+6` / `+7` and
`CALLF D0AE:0002` (file `0x4FC36`
`9A 02 00 AE D0`). That dest is
already owned (`[0x509F3, 0x50E79)`).
**PROVEN** as that gate and call. Do
not name `D0AE`. The `0x80` arm
requires `ES:[BX+2]` in `0x23`..`0x62` and
indexes `[E5F9]` by that note via
`ADD BX,0xFCF6` (file `0x4FBA3`). Then
`CMP ES:[BX],0xFF` (file `0x4FBB0`) and
`CMP ES:[BX+6],2` (file `0x4FBB9`).
**PROVEN** as that switch. Same
`0x18`-byte table as `CFC6:0007`.
Do not name `+0` / `+6`. Task 3's first packet byte is
`Param+0x90`; if Param is `0..3` then
`& 0xF8` is `0x90` and that arm is taken
(**HYPOTHESIS** live Param stays `0..3`).

Already-owned `DCE4:000C` (file
`0x5CE4C`). `AND AL,0xF8` (file
`0x5CE8A`); `CMP 0x98` / `0xF8` /
`0xF0`. The `0xF0` arm (file
`0x5CEA4`) requires `ES:[SI+2]==0x47`
and `ES:[SI+5]` in `{0x45,0x46}`
(files `0x5CEA8` / `0x5CEAF` /
`0x5CEB6`), then `CMP [E60F],1`
or `CMP [E610],1` (files
`0x5CEC9` / `0x5CED7`). **PROVEN**
as the same `0xF0` gate as
`CFB3` plus the named overlay
flags. Not a pad-hit. Do not
name the `0x98` / `0xF8` arms.
Owned callers `DC85:0047` (file
`0x5C94E`) and leftover `011A`
(file `0x5CA0A`).

`CFC6:0007` (file `0x4FC67`, same owned span).
`ES:[BX+2]` must be `0x23`..`0x62` else
`02D2` `POP`/`LEAVE`/`RETF`. Else
`AX=note*0x18`; `LES BX,[E5F9]`;
`ADD BX,0xFCF6`; `AL=ES:[BX+0x0D]`.
**PROVEN** as that index (effective
`[E5F9]+note*0x18+FD03`, not `+FD0D`).
`FCF6+0x17=FD0D`, so this is the same
`0x18`-byte per-note table whose last
byte is the already-named Param.
**PROVEN.** `CALLN 02D6` (file `0x4FCC3`
`51 90 0E E8 6D 02`) then `CALLN 033A`
(file `0x4FCDB` `50 90 0E E8 B9 02`)
both pass the event note. **PROVEN.**
`CALLN 039E` from `0007` (files
`0x4FE4D` / `0x4FEC0` / `0x4FF29`,
`56 90 0E E8`). Already-owned leftover
cdecl at file `0x4FFFE`
(`[0x4FFFE, 0x500CE)`). If event
`[BP+0C]+0` is `0xFF` (file
`0x5000F`) it `RETF`s. Else event
`+7` / `+8` must be `>=0x23` (files
`0x50046` / `0x50069`); then
`note*0x18+[E5F9]+FCF6` (files
`0x50058` / `0x5005E` and
`0x5007B` / `0x50081`).
**PROVEN** as a second note-floor
index of that table. Do not name
the loaded `FCF6+0` byte. Ends at
`JMP CS:[BX+0B25]` (file `0x500C9`).
Do not walk that dest. After the
`02D6`/`033A` calls, `AL=ES:[BX+1]` (file `0x4FCED`)
is compared to `2` and `3`. When `+1==2`
and event `+3` is above `+4`, `+5` must
be `>=0x23` (file `0x4FD16`) and then
indexes the same table (`+5*0x18+FCF6`,
file `0x4FD23`). When event `+3` is at
or below `+4`, `+3` is the note
(`CMP 0x23` file `0x4FD54`; load file
`0x4FD61`). When `+1==3` (file `0x4FD92`)
the compare key is `+0C` (file `0x4FD95`),
or event `+4` if event status `& 3 == 1`
(file `0x4FDA5` / `0x4FDAD`). Then the
same `+5` / `+3` note-floor arms.
**PROVEN** as note-floor
bytes. When `+1==1` (file `0x4FE59`)
`+3` is the note if `>=0x23` (file
`0x4FE63` / `0x4FE6A`); else `+5`
(file `0x4FECC` / `0x4FED3`).
**PROVEN.** Do not name `+1` / `+2` / `+4` /
`+0C`.
Leftover `02D6`
(file `0x4FF36`, `CALLN` from `0066`):
`DX=[BP+6]-0x23`; clamp
`0`..`0x3F`. **PROVEN** note-to-slot
on that arm. Not a pad-hit. If
`[E60F]==2` (CF37 default), `AX=slot<<2`;
`DX:AX = [E5F9] + AX + 0x063E`. **PROVEN.**
`+063E + 0x40*4 = +073E`, so `+063E` is
64 dwords immediately before the note
table. Do not name those dwords.

Already-owned leftover `C20F:0478`
(file `0x42568`, after `0477` `RETF`
in `[0x420F3, 0x42D0C)`). `XOR SI,SI`
then loop `047C`: `AX=SI*0x18`;
`LES BX,[E5F9]`; `ADD BX,AX`;
`CMP ES:[BX+3E],0xFF` (file
`0x4257B`). Bound `CMP SI,0x40`
(file `0x425CD`). After the loop,
`CALLF C887:1BE8` (file `0x425D8`)
is the named `CA45:0008` alias.
`+3E + 0x40*0x18 = +063E`.
**PROVEN** as a 64-slot walk of
`[E5F9]+SI*0x18+3E` whose exclusive
end is the named dword base. Not a
pad-hit. Sibling leftover `0874`
(file `0x42964`) is the same
`SI*0x18` / `[BX+3E],0xFF` walk.
Already-owned `C20F:0BBF` (file
`0x42CAF`) loads `ES:[BX+3E]`
(file `0x42CDB`) and bounds
`CMP DX,0x600` (file `0x42CF1`;
`0x40*0x18`). It reads `[E60E]`
(file `0x42CB7`) and skips
`DI==[E60E]` (file `0x42CC1`).
Else `CALLF C887:1BE8` (file
`0x42CC7`) is `CA45:0008`;
`CMP AX,[BP+6]` (file `0x42CE1`);
on match `MOV ES:[SI+3E],[BP+8]`
(file `0x42CE9`). Outer
`CMP DI,0x18` (file `0x42CF8`)
then restore `CA45` (file
`0x42D00`). **PROVEN** as a
24-program `+3E` compare/store
that excludes the selected
`Pgm`. Not a pad-hit. Do not
name the `+3E` byte.

Already-owned cdecl `D0C0:0C9C`
(file `0x5189C`, span
`[0x5146F, 0x51917)`). Reads
`[E60E]` (file `0x518A4`);
`CALLF C887:1BE8` (file `0x518B4`)
is `CA45:0008`. Inner loop
`DI=0x23` / `CX=0x348` (files
`0x518BC` / `0x518BF`);
`LES [E5F9]`; `ADD BX,CX`;
`MOV AL,ES:[BX+FCF6]` (file
`0x518CA`); `ADD CX,0x18`;
`CMP CX,0x930` (file `0x518F3`).
`0x23*0x18=0x348`;
`0x62*0x18=0x930`;
`(FCF6+0x348)&0xFFFF=+3E`.
**PROVEN** as that index. Outer
bound `CMP [BP-4],0x18` (file
`0x518FC`) is the named `CA45`
`0..0x17` domain. Not a pad-hit.
Do not name `D0C0`. Do not name
the `+3E` byte.
`033A` (file `0x4FF9A`) is the same map
gated on `[E610]==2` (also default 2).
If `[E60F]==1` and `[920A]:[920C]` is
nonzero (`0309`, file `0x4FF69`),
`DX:AX = [920A]:[920C] + slot*4 + 0x002A`.
**PROVEN** as that far index. Else
`DX:AX = DS:E639 + slot*4` (file `0x4FF8E`).
**PROVEN** as the fallback; it is the
table `CF37:0305` fills. `036D` is the
same pair gated on `[E610]`. Do not name
`[920A]` or the `+0x0D` field. Do not
seed unowned `LES [920A]` at `0x669B8`.

Leftover after `D0AE:0002` `RETF` (file
`0x50BC6`, already owned). `CALLF
D9F2:000C` on `[BP+0A]` (file `0x50BCF`);
then slot `0..0x3F` (file `0x50C00`
`80 7E 0A 40`) calling `000C` again
(file `0x50BE2`). On note match,
`MOV ES:[BX+slot],[BP+0C]` (file
`0x50BFA`). **PROVEN** as a 64-slot
note-match store through the named
accessor. Not a pad-hit. Do not name
`D0AE`. `0002` itself also writes
`[D6AB]=0x50` (files `0x50B3D` /
`0x50B7E` / `0x50BBF`), same as the
`0xB0` arm.

Leftover cdecl at file `0x50A07` (same
owned span, after the 32-loop `RETF`)
clamps event `+2` to `0x23`..`0x62`,
indexes `[E5F9]+FCF6` (file `0x50A41`),
and returns `+5` or `+3` from the same
`+1==2` / `+1==3` note-floor arms as
`CFC6:0007` (files `0x50A4E` / `0x50A73`
/ `0x50A8C`). **PROVEN** as a second
consumer of that table. Do not name
`D0AE`.

Already-owned `D9A2:0004` / `0031` /
`005F` (files `0x59A24` / `0x59A51` /
`0x59A7F`). `PUSH [BP+6]`; `CALLF
D9F2:000C` (files `0x59A2D` /
`0x59A5A` / `0x59A88`). If `AX>=0x23`
(file `0x59A38`), `CALLF CFC6:02D6`
(`0004`/`0031`, files `0x59A3E` /
`0x59A6B`) or `033A` (`005F`, file
`0x59A99`). Then `MOV ES:[BX+0],
[BP+8]` / `+1` / `+2` (files
`0x59A4C` / `0x59A79` / `0x59AA7`).
**PROVEN** as stores through the
named note-to-slot far pointer.
Not a pad-hit. Do not name those
fields.

Sibling leftover `D9A2:00C7` /
`00E9` / `010C` (files `0x59AE7` /
`0x59B09` / `0x59B2C`) is the read
side: `000C` then `02D6`
(`00C7`/`00E9`) or `033A`
(`010C`) then `MOV AL,ES:[BX+0]`
/ `+1` / `+2` (files `0x59B02` /
`0x59B24` / `0x59B47`).
**PROVEN.** No `CMP 0x23` on the
readers. Gap leftover `D9A2:008D`
at file `0x59AAD` is the same
shape with `033A` and `+3`. Do
not seed it.

`BDF1:00E1` (file `0x3DFEF`,
already owned): `PUSH 0`; `CALLF
D9F2:000C`; `MOV [D6AD],AL` (file
`0x3DFF9`). **PROVEN** as slot 0
to `[D6AD]`.

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

`BDF1:00E1` (file `0x3DFF9` `A2 AD D6`)
is the inverse store: `000C(0)` into
`[D6AD]`. Same pair, opposite direction.

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
- Gap leftover `D9A2:008D` at file `0x59AAD`
  (owned `9A` dest; leftover after `005F`
  `RETF`). Do not seed.
- Gap `CALLF D9C0:0006` at files `0x5564F` /
  `0x556DB` / `0x55C0E`. Do not seed.
- Full `9770:` / `Pgm` record grammar past `+11` /
  `+12`..`+19` / `+063E` / `+073E` / `+FCF6` /
  `+FD0D`.
- `C887:09AC` body (mid-hole).
- TE7774 / panel scan (D19).
