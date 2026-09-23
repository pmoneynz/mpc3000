# Sequencer transport — D21

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

D21 asks for sequencer transport: play / stop / position.
This note inventories already-owned consumers. It does not
seed ranges. It does not BFS `JMP CS:[BX]`.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name owned Play/Record and Locate paint, and bound what is not yet transport |
| Observable | Task 7 `B000:01A0` `CALLF C425:0009`; `C425:0106` `CALLF C303:0004`; `C303:10A3` titles; `C303:0D47` Now: template; `C425:012F` `CALLF C2D0:000C` Locate |
| Inputs | `[8C8B]`, `[9208]`, `[D7CB]`, `[7D79]` as encodings only |
| Outputs | Screen strings listed below. No proven play/stop state bit. No proven live bar.beat.tick writer |
| Confidence | Path, titles, Now: template, Locate, and second-PGR fetch for this first `C425` call **PROVEN**. `[9208]==0` selects the Record Ready title **PROVEN**. That the byte is record-ready state **HYPOTHESIS**. Live position fill, MMC name table, and PLAY/STOP function-key table **UNDETERMINED** |
| Hardware deferred | Panel PLAY/STOP on the wire (D19 / `U-PANEL-ROM`, `U-TE7774`) |

---

## 1. What D21 asks

Play, stop, and position as a complete slice: purpose, IO,
state, bounds, evidence. A title string is not transport.
G4 waits for a stable dispatcher and address map. The
dispatcher for this UI is owned. The engine is not.

---

## 2. Dispatcher and address map

Task 7 entry `B000:00DF` (file `0x300DF`, 20-bit `0xB00DF`,
24-bit `0x0B00DF` under second PGR slot 44 word `0x002C` at
`0x7AD0C`, XA=1) ends `CALLF C425:0009` at `B000:01A0`
(file `0x301A0`) then `RETF` at `01A6`. Sole `9A` of
`C425:0009`. **PROVEN.**

`C425:0009` (file `0x44259`, 20-bit `0xC4259`, 24-bit
`0x0C4259` under second PGR slot 49 word `0x0031` at
`0x7AD16`, XA=1) is already owned
(`[0x44259, 0x44483)`). `C425:00FA` (file `0x4434A`)
`CMP [89ED],0`; `JZ 0106`. `C425:0106` (file `0x44356`)
`CALLF C303:0004`. **PROVEN.** `[89ED]` **UNDETERMINED**.

`C425:0084` (file `0x442D4`) `CMP AX,0x2F` (`3D 2F 00`).
`JNZ 008C` (`75 03` at file `0x442D7`). The equal arm is
`JMP 012A` at `0089` (file `0x442D9`), then `CALLF C2D0:000C`
at `012F` (file `0x4437F`). **PROVEN** as the owned transfer
to Locate. That `0x2F` is the LOCATE key **HYPOTHESIS** (D19).

Second PGR is live through task 7 select
([`pgr_live_after_amx.md`](pgr_live_after_amx.md)).
`C425` is a direct task-7 `CALLF`; `C303:0004` is a direct
child. Those two-level walks do not `MOV DX` into
`0xFF00-0xFF7E`. **PROVEN** for that tree. Deeper `C303`
callees stay `U-XA-LIVE`.

Page 48 (this `C303` body) second-PGR word `0x0030` at
`0x7AD14` → 24-bit ROM `0x0C0000`. Third PGR word `0x00F0`
at `0x7AE2F` → RAM `0x3C0000`. File / `CS:IP` / 20-bit
do not depend on that. 24-bit after a later PGR write is
**UNDETERMINED**. That does not block reading the owned
ROM bytes. It does block claiming one 24-bit for every
later Play/Record entry.

---

## 3. Already-owned consumers

### Play/Record — `C303:0004`

File `0x43034`, 20-bit `0xC3034`, 24-bit `0x0C3034` under
second PGR slot 48 word `0x0030` at `0x7AD14`, XA=1.
Owned `[0x43034, 0x43BFC)`.

`000E` `CALLN 10E9`; `0016` `CALLN 10A3`; `0019`
`MOV AL,[D7CB]` / `MOV [D6AF],AL`; then `Seq:` via
`B354:03B1` (`PUSH +4D75` at file `0x4305D`).
`00F5` (file `0x43125`) `PUSH +4D81`
`Sig:  /    Bars:        Loop:` via `B354:01C6`.
`0066` (file `0x43096`) `PUSH +01EC` (directory dword
file `0x201EC` = `8010:0899` `BPM`). **PROVEN** as
paint. `[D7CB]` / `[D6AF]` names stay unnamed (D20).

`C303:10A3` (file `0x440D3`, 20-bit `0xC40D3`, 24-bit
`0x0C40D3` under slot 49, XA=1) is owned leftover
`[0x43DA6, 0x44259)`:

| Path | Test | String | Callee |
|------|------|--------|--------|
| `10B6` | `[8C8B]` signed `> 0` (`JLE 10C8` at `10B4`, `7E 12`) | `+4E70` `========== (Next Sequence:%2d) ==========` | `B1BC:01EE` |
| `10CF` | `[9208] == 0` | `+4E9A` `Play/Record (Record Ready)` | `EBFF:0000` |
| `10DC` | `[9208] != 0` (`JNZ 10DC` at `10CD`, file `0x440FD`, `75 0D`) | `+4EB5` `Play/Record` | `EBFF:0000` |

**PROVEN** as the title selector. `[9208]==0` selects the
Record Ready title. `[9208]!=0` selects plain `Play/Record`.
**PROVEN.** That the byte is record-ready state **HYPOTHESIS**.

ROM sources: `+4E9A` file `0x24E9A`, `+4EB5` file
`0x24EB5`, `+4E70` file `0x24E70` (DGROUP copy, runtime
`8010`).

### Now: template — `C303:0D47`

File `0x43D77`, 20-bit `0xC3D77`, 24-bit `0x0C3D77`
under slot 48, XA=1. Owned `[0x43D77, 0x43DA6)`.
`PUSH 0` / `PUSH 6` / `CALLF B1B1:0026`; `PUSH DS` /
`PUSH +4E36` / `CALLF B1B1:005B`; `PUSH 0` /
`CALLF EA97:000E`; `PUSH 0` / `PUSH 7` /
`CALLF B1B1:0026`; `RETF`. **PROVEN:** puts the ROM
template `===== Now:001.01.00 (00:00:00.00) ======`
(file `0x24E36`, `8010:4E36`). Sole `PUSH +4E36` in
the image. This is not a live bar.beat.tick fill.

Owned callers: `C2D0:0097` (Locate) and `B3FD:02A4`
(file `0x34274`, inside owned `B3FD:0006`). Two
further `9A` sites (`0x4AFE5`, `0x4C8F2`) are
unowned. Do not BFS them.

`EA97:000E` (file `0x6A97E`) is owned. It tests
`[D6A8]`, `[D7CA]`, `[A75D]`. It does not `PUSH +4E36`.
Live Now: rewrite **UNDETERMINED**.

### Locate — `C2D0:000C`

File `0x42D0C`, 20-bit `0xC2D0C`, 24-bit `0x0C2D0C`
under slot 48, XA=1. Owned `[0x42D0C, 0x42E67)`.
`PUSH +4C44` `Locate` via `EBFF:0000`. Then
`E5AF:0001` with `DS:9208`, and `B1B1:0026` with
`(1, 0)`. Then `PUSH +4C4B`
`Hit softkeys or LOCATE to go to markers:` via
`B1B1:005B`. Then `B1B1:0026` with `(2, 9)`,
`(3, 9)`, and `(4, 9)`, each followed by
`B354:053A` for `Marker A: ` (`+4C74`),
`Marker B: ` (`+4C7F`), and `Marker C: `
(`+4C8A`). Then `CALLF C303:0D47` at `0097`
(file `0x42D97`). **PROVEN** as
position-*marker* UI, not transport play/stop.

### Related owned text, not the engine

`C44E:070F` (file `0x44BEF`, owned `[0x44BEF, 0x44C8D)`)
`PUSH +5228` (file `0x44C42`): MMC help names Play/Record
or Song and hold STOP & press PLAY. MIDI menu leftover
(D20). Not a play/stop writer.

`B3FD:08C3` (file `0x34893`, owned) `PUSH +1F43` `Tempo:`
and `PUSH +1F39` `Bars:`. Not Play/Record.

Do not name unowned `PUSH` sites (`Play X:`,
`<Ply/Stp>`, `<Play/Stop>` sample-keep, Other Options
`In play:` / `Count in:`, Tap Tempo).

---

## 4. Bounds — do not BFS

`C303:02E1` (file `0x43311`) `MOV AL,[7D79]`; `CBW`;
`MOV DI,AX`; `MOV BX,AX`; `CMP BX,0x12`. `76 03` at
`02EC` (file `0x4331C`) is `JBE` to the `SHL` when
unsigned `BX` is at most `0x12`. Above that, `JMP
091B`. `JMP CS:[BX+0BE8]` at `02F3` (file `0x43323`).
Table file `0x43C18`, 19 near IPs, owned
`[0x43C18, 0x43C3E)`, after the code span. Dest 0
`02F8` is more UI (`[974F]`, `B1B1`/`B3C7`/`B060:0AD9`).
**PROVEN** as a `[7D79]` switch. Index meaning
**UNDETERMINED**. Do not BFS this table.

`C303:097F` `JMP CS:[BX+0BCC]` (file `0x439AF`): `SUB
BX,0x6D`, then `76 03` at `0978` (file `0x439A8`) is
`JBE` when unsigned `BX` is at most `0x0D`. The 14
words are owned `[0x43BFC, 0x43C18)`. Do not
BFS.

`[7D79]` is a shared event byte (owned `B060` writers
and many screens). Not a transport flag.

Directory `SEQUENCE` at `+06A9` (file `0x206A9`; dir
dwords `+0030` / `+003C`) is D10 text. Not play/stop.

MMC far-ptr block `8010:771C` (file `0x2771C`): ten
`8010` dwords — `locate` / `play from start` / `play` /
`stop` / `record on` / `record from start` / `record on`
(file `0x27734`, `8010:7765`) / `record exit` /
`MMC turned on.` / `MMC turned off.` No `PUSH` / `LDS` /
`LES` of `771C` in the image. Consumer **UNDETERMINED**.
Do not seed.

Function-key names `8010:5980` `PLAY/STOP` …
`PLAY-STRT/STP` / `RECORD IN/OUT` / `TAP TEMPO` /
`REC+PLAY`. `PUSH +5980` only at unowned `0x485A2` /
`0x485B8`. Do not BFS.

`+0238` tempo/SMPTE scalars stay as in
[`copy_7c92.md`](copy_7c92.md): no consumer.

---

## 5. What still blocks the checkbox

Owned code paints Play/Record, Locate, and a static
Now: line. That is not play, stop, or live position.

Single missing observation: a proven writer of
transport state (play vs stop vs record-ready beyond
the `[9208]` title test) and of the live bar.beat.tick
that Now: is supposed to show. `C303:0D47` only puts
the template. The in-screen key path is `JMP CS:[BX]`
on `[7D79]` — do not BFS it. Panel PLAY/STOP stays
D19. MMC `play`/`stop` names have no consumer.

Do not mark D21 done.

---

## 6. 2026-09-22 — owned stores of title RAM and Now: digits

Hunt: linear `v53_decode` of owned code, plus
encoding search for abs16 stores. Indirect
`JMP CS:[BX]` targets that leave the owned body
were not entered.

### Now: digits — RAM the painter actually reads

`C303:0D47` `PUSH 0` / `CALLF EA97:000E` (file
`0x43D91`). `EA97:0086` `MOV AX,0x923E` (file
`0x6A9F6`, `B8 3E 92`) then `CALLN EA97:021E`.
**PROVEN.**

`EA97:021E` (file `0x6AB8E`, 20-bit `0xEAB8E`,
24-bit `0x0EAB8E` under second PGR slot 58 word
`0x003A` at `0x7AD28`, XA=1), `LES BX` of that
far ptr:

| Field | Operand | Format |
|-------|---------|--------|
| bar | word `ES:[BX+2]` + `[9750]` | 3 digits, then `'.'` |
| beat | byte `ES:[BX+1]` | 2 digits, then `'.'` |
| tick | byte `ES:[BX]` | 2 digits (`[BP+0A]==0`) |

With `BX=0x923E` that is `DS:[9240]`,
`DS:[923F]`, `DS:[923E]`. Cursor `PUSH 0x0A` /
`PUSH 6` overwrites `001.01.00` on the template
row. **PROVEN** as the Now: bar.beat.tick *read*.
`SI!=0` uses `0x8A03` instead; `C303:0D47` does
not.

### Owned stores that hit that RAM

These are reached by `follow_local` inside an
owned range. Values are constants or a one-shot
copy, not a tick advance.

| Site | File | Bytes | Writes |
|------|------|-------|--------|
| `B3FD:0ABD` | `0x34A8D` | `89 16 40 92` `C6 06 3F 92 01` `C6 06 3E 92 00` | `[9240]=DX` after `MOV DX,AX` from `CALLF E56F:00FE`; only when `[89EF]!=[89F1]` (`75 0E` at file `0x34A7D`). Beat `1`, tick `0` |
| `E7CE:004B` | `0x67D2B` | `C7 06 40 92 01 00` `C6 06 3F 92 01` `C6 06 3E 92 00` | bar `1`, beat `1`, tick `0` |
| `E7E0:0135` | `0x67F35` | `C7 06 40 92 00 00` `C7 06 3E 92 00 00` | bar `0`; word `[923E]=0` (tick and beat) |
| `DEE9:004F` | `0x5EEDF` | `C7 06 40 92 00 00` | bar `0` |
| `DCF0:01CA` | `0x5D0CA` | `A3 40 92` | `[9240]=AX` after `MOV AX,[A7B8]` (`A1 B8 A7`) |

Addresses for the table (second PGR, XA=1):

- `B3FD:0ABD`: 20-bit `0xB4A8D`, 24-bit `0x0B4A8D`,
  slot 45 word `0x002D` at `0x7AD0E`.
- `E7CE:004B`: 20-bit `0xE7D2B`, 24-bit `0x0E7D2B`,
  slot 57 word `0x0039` at `0x7AD26`. Caller
  `E7CE:0009` also `MOV byte [9208],0` at
  `E7CE:0039` (file `0x67D19`, `C6 06 08 92 00`)
  only when `[A7AE]==0` and `[9208]==2`. Both
  compares are `75` to `006F` (files `0x67CF4`
  and `0x67CFB`) when the byte differs.
- `E7E0:0135`: 20-bit `0xE7F35`, 24-bit `0x0E7F35`,
  slot 57 word `0x0039` at `0x7AD26`.
- `DEE9:004F`: 20-bit `0xDEEDF`, 24-bit `0x0DEEDF`,
  slot 55 word `0x0037` at `0x7AD22`.
- `DCF0:01CA`: 20-bit `0xDD0CA`, 24-bit `0x0DD0CA`,
  slot 55 word `0x0037` at `0x7AD22`. Owned span
  `[0x5CF06, 0x5D0CF)`. `DCF0:047E`
  `JMP CS:[BX+045E]` (file `0x5D37E`) is outside
  that span — do not BFS it.

No owned `INC`/`DEC`/`ADD` of `[923E]`,
`[923F]`, or `[9240]` (encoding search of
`FE 06` / `FF 06` / `FF 0E` / `80 06` on those
disp16s = 0 hits in owned code). **PROVEN.**
`[A7B8]` is not a Now: operand. Copying it to
`[9240]` is not live tick.

### Play vs stop — not among those loads

`C303:10A3` reads `[8C8B]` and `[9208]` only.
`[9208]==0` selects `Play/Record (Record Ready)`.
`[9208]!=0` selects plain `Play/Record`.
That is not play vs stop. **PROVEN** as the title
test; record-ready meaning stays **HYPOTHESIS**.

Owned `[9208]` stores found by the same scan
write `0`, `1`, or `0xFF` (example:
`E7CE:0039` writes `0`). None is a play/stop
pair that the title or Now: line reads as
transport. `[8C8B]` stores inside
`C303:0004` sit after `C303:02F3`
`JMP CS:[BX+0BE8]` (file `0x43323`) — out of
scope.

### Missing store (D21 stays open)

Not found: a store that advances
`DS:[923E]` / `[923F]` / `[9240]` as play
runs, and a play-vs-stop state bit that these
consumers read as transport. Reset-to-`001.01.00`
and bar-zero stores do not close the slice.
Not `[PARTIAL]`: the gap is unowned or
unentered software, not a missing ROM or
datasheet.

Do not mark D21 done.

---

## 7. 2026-09-22 — whole-image [923E]/[923F]/[9240]

New owned: `BDF1:01D2` file `0x3E0E2`
`C7 06 40 92 00 00` `[9240]=0` (owned
`[0x3DE3E, 0x3E1A2)`). `CALLN` at `0118`
targets `012B`. `CMP byte [9208],0` /
`7C` at `01C3` (file `0x3E0D3`) skips
this store when that byte is signed
below 0. Reset, not INC. **PROVEN.** No INC/ADD.
No proven-base `[BX+disp]` store.
Gap, no owned CALL/JMP to the insn:
`0x4C877` `0x4EAE8` `0x5E0F0` `0x614C1`
`0x675F9` `0x67CB7`. Stop. Do not seed.
Live writer is not a direct store in this
image. D21 stays open. Not `[PARTIAL]`.

---

## 8. 2026-09-22 — owned IRQ/timer pointer increment

Linear `v53_decode` of the owned IVT entries (`D52A:0008`, `D5DD:000C`,
`D547:0067`, `D5F3:000E`, `D61A:000A`, `FB00:02F8`/`02EF`, `FB93:0059`,
`FAC0:01A4`, BIOS `F800` slots) plus AMX `0157`/`0586`/`0194`/`05A0` and
`B060:0000`, including owned `CALLN` callees and not `JMP CS:[BX]`, never
writes BX/SI/DI/BP from `B8+rw` / `C7 /0` / `8D` with imm16/disp16
`0x923E`/`0x923F`/`0x9240` in that same body. **PROVEN.** Owned timer
r/m INC/DEC in those bodies include `D52A:0024` `FF 06 9F D6` (`FF /0` mod=0
rm=6 disp16 `[D69F]`, file `0x552C4`, 20-bit `0xD52C4`, 24-bit `0x0D52C4`,
second PGR slot 53 word `0x0035` at `0x7AD1E`, XA=1) and `D52A:0028` `FF 0E 6E 78` (`FF /1` DEC word `[786E]`, file `0x552C8`, 20-bit `0xD52C8`, 24-bit `0x0D52C8`, same slot) and `FB00:058D`
`FF 4D 12` (`FF /1` mod=1 rm=5 `[DI+12h]` after `C5 /7` `LDS DI,CS:[0042]`
at `0588` `2E C5 3E 42 00`, file `0x7B58D`, 20-bit `0xFB58D`, 24-bit
`0x0FB58D`, slot 62 word `0x003E` at `0x7AD30`, XA=1). The same walks also
INC/DEC `[964F]`, `[9645]`, `[9647]`, `[D838]`, `[9759]`, `[D7F6]`,
`[763C]`, `[8C8A]`, `[D7D9]`, and indexed `[SI+9971]`, `[SI+8]`,
`[DI+10]`. None of those absolute displacements is `923E`/`923F`/`9240`,
so the missing Now: store stays software and D21 stays open, not
`[PARTIAL]`.
