# D24 — MIDI (TE7774 `0xC0-0xDF`)

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

Does **not** close D24. Owned code has `IN`/`OUT` in `0x00C0-0x00DF`.
No consumer names a port as MIDI versus panel. `D547:0105` and
`D547:04D5` are bounded in §9 and §10. `051D` still jumps through
`[SI+762E]`. D24 stays open.

Reproduction: `python3 tools/v53_decode.py` (`follow_local` /
`decode_one`) and a read of `analysis/owner_ledger.json`. Second
PGR (file `0x7ACB4`) is live. XA=1. Identity frames: 24-bit is
20-bit with a leading 0. `JMP BX` / `JMP CS:[BX+053A]` are
bounded in §9. Did not enter an indirect dest.
Did not seed `C887:09AC`, `B13A:0000`, or `B77C:1FDB`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name already-owned `IN`/`OUT` in `0xC0-0xDF`, the bytes written or tested, and the unread path that blocks D24 |
| Observable | Encodings below. No proven MIDI-versus-panel split |
| Inputs | Linear image; second PGR; owner ledger as read-only |
| Outputs | This note. No ledger seed. No TODO checkbox |
| Confidence | Instruction bytes and owned bounds **PROVEN**. Port/bit meaning **UNDETERMINED** (`U-TE7774`). Chip identity TE7774 is the named window, not a decode of these bytes |
| Hardware deferred | TE7774 datasheet (not in this tree); wire capture (`U-PHYS`) |

Odd ports `0xC1,C3,…,DF` have no owned `IN`/`OUT`. `0xC000-0xC033`
is `U-C0XX`, not this window. `D5F3:000E` (IVT[0x0E]) uses
`0xC011` / `0xC010` / `0x0050` only. DGROUP `MIDI` strings are
UI (`C44E` menu title at file `0x24F68`); they are not port names.

---

## 1. Proven owned ports

Every even port `0xC0-0xDE` has at least one owned `IN` or `OUT`.

| Port | Owned `IN` | Owned `OUT` |
|------|------------|-------------|
| `0xC0` | `B03B:01E0` (result discarded) | `D5DD:0163` is `OUT DX,AL` after `SUB DX,6` at `0160`. Caller sets `DX=0xC6`. `FB00:0725` returns that `DX` only on the paths that reach `POP DX` at `06DD` (file `0x7B6DD`). The other path `POP DX` at `0710` (file `0x7B710`) then `MOV DX,[BX+SI+0Ah]` (file `0x7B711`). Port **UNDETERMINED** |
| `0xC2` | `D547:0087`; `D5DD:0025` | `B03B:00F0` / `00F3`–`0103` |
| `0xC4` | none | `B03B:010A` `AL=0` |
| `0xC6` | none | `B03B:0116`; `D547:00B9`/`00E6`; `D5DD:00A8`/`00E7`; `D61A:0BF7`; `DCF0:0A01` |
| `0xC8` | `B03B:01E4` (discarded) | same `0163` site. Caller sets `DX=0xCE`. Same `0725` split. Port **UNDETERMINED** |
| `0xCA` | `D547:009A`; `D5DD:0042` | `B03B:011C` / `011F`–`012F` |
| `0xCC` | none | `B03B:0136` `AL=0` |
| `0xCE` | none | `B03B:0142`; `D547:00C5`/`00F2`; `D5DD:00B4`/`00F9`; `D61A:0C03`; `DCF0:0A1B` |
| `0xD0` | `B03B:01E8` (discarded) | same `0163` site. Caller sets `DX=0xD6`. Same `0725` split. Port **UNDETERMINED** |
| `0xD2` | `D547:0077`; `D5DD:005F` | `B03B:0148` / `014B`–`015B` |
| `0xD4` | none | `B03B:0162` `AL=0` |
| `0xD6` | none | `B03B:016E`; `D547:00D1`/`00FE`; `D5DD:00C0`/`010B`; `DCF0:0A35` |
| `0xD8` | `B03B:01EC` (discarded) | same `0163` site. Caller sets `DX=0xDE`. Same `0725` split. Port **UNDETERMINED** |
| `0xDA` | `D5DD:007D` | `B03B:0174` / `0177`–`0187` |
| `0xDC` | none | `B03B:018E` `AL=0` |
| `0xDE` | none | `B03B:019A`; `D5DD:00CC`/`011D`; `DCF0:0A4F` |

`D547:0105` (`IN AL,DX` with `DX=0xD0`) and `D547:04D5`
(`IN AL,DX` with `DX=0xC0` or `0xC8`) are **not** in this table.
Those sites are instruction prefixes of indirect dests, not
complete owned bodies. See §6.

---

## 2. `B03B:000A` — init writes

Owned `[0x303BA, 0x3058A)`. Entry `B03B:000A` file `0x303BA`,
20-bit `0xB03BA`, 24-bit `0x0B03BA`, `PGR[44]=0x002C` at
`0x7AD0C`. `follow_local` through `01D9 RETF` file `0x30589`.
No `JMP` r/m. **PROVEN.**

`B03B` writes `DL` to `8`, `0xC`, `0xD`, and `0xE`
(`B2 08` at `00B7`, file `0x30467`) and calls
`FB00:0347`. That callee uses `DX` as the IVT index
and restores `DX` (`POP DX` at `036E`). It does not
write those four immediates. Four
identical write groups follow. Each group:

1. `DX` = `0xC2` / `0xCA` / `0xD2` / `0xDA`; `OUT DX,AL=0`.
2. Immediate `OUT` of `AL=0`, `0`, `0xC0`, `0x02`, then `0x95`
   (`0x91` on `0xDA` only) to that same port.
3. `DX` = `0xC4` / `0xCC` / `0xD4` / `0xDC`; `OUT DX,AL=0`.
4. `OR [9628+i], imm8` then `MOV AL,[9628+i]`; `OUT` to
   `0xC6` / `0xCE` / `0xD6` / `0xDE`. Imm8 is `4`,`4`,`4`,`0`.

`OR [962B],0` at `018F` file `0x3053F` is a no-op; `AL` is
still `[962B]`. Bit and port meaning **UNDETERMINED**
(`U-TE7774`). Later `OUT 0x86/80/82/84/FE/F8/FC/FA/6A` are
outside this window.

---

## 3. `B03B:01DA` — discarded `IN` of `0xC0/C8/D0/D8`

Owned `[0x3058A, 0x30600)`. Entry `B03B:01DA` file `0x3058A`,
20/24 `0xB058A` / `0x0B058A`, `PGR[44]=0x002C`. Task 7
`B000:010B` file `0x3010B` `CALLF B03B:01DA` then `0110`
`CALLF B03B:01F7`. **PROVEN.**

`MOV CX,3`; loop `IN AL,DX` with `DX=0xC0,0xC8,0xD0,0xD8`;
`LOOP`. `AL` is not stored. Then `DX=0xC011` (`U-C0XX`)
`IN` / `AND 0xCF` / `OUT`; `RETF` `01F6` file `0x305A6`.

`B03B:01F7` (same span, `CALLF` from `B000:0110`) programs
`0xC033` / `0xC010` / `0xC011` / `0xC031` and plants
IVT[9] `D61A:000A`. Not `0xC0-0xDF`.

---

## 4. `D547:0067` — IVT[0x0D]

Owned `[0x554D7, 0x55575)`. Entry `D547:0067` file `0x554D7`,
20/24 `0xD54D7` / `0x0D54D7`, `PGR[53]=0x0035` at `0x7AD1E`.
Planted by `B03B` `DL=0x0D`. `CALLF FB00:0157`; `IRET` `0104`
file `0x55574`. **PROVEN.**

`DS=8010`; `[964F]=0`.

- `IN AL,0xD2` `0077` file `0x554E7`; `TEST AL,2`; `JNZ 0087`;
  else `INC [964F]`; `DX=0xD0`; `CALLN D547:0105`.
- `IN AL,0xC2` `0087` file `0x554F7`; `TEST AL,2`; `JNZ 009A`;
  else `INC [964F]`; `SI=0`; `DX=0xC0`; `CALLN D547:04D5`.
- `IN AL,0xCA` `009A` file `0x5550A`; `TEST AL,2`; `JNZ 00AD`;
  else `INC [964F]`; `DX=0xC8`; `SI=2`; `CALLN D547:04D5`.

Then `CLI`; `AND [9628],~4` / `OUT 0xC6`; same `~4` on
`[9629]`→`0xCE`, `[962A]`→`0xD6`; `OUT DX,AL` with
`DX=0xC010` and `AL=0x65`, then `AL=0xC7` (`EE` at
`00DA`, file `0x5554A`; `DX` is still `0xC010`,
`U-C0XX`); `OR [9628],4` / `OUT 0xC6` and the
same `4` on `9629`/`962A`. No fourth-group `962B` / `0xDE`.
`CALLF FB00:0194`; `IRET`.

`TEST AL,2` is an encoding. Bit name **UNDETERMINED**.

---

## 5. `D5DD:000C` — IVT[0x0C], and `D5DD:0134`

Owned `[0x55DDC, 0x55EF4)`. Entry `D5DD:000C` file `0x55DDC`,
20/24 `0xD5DDC` / `0x0D5DDC`, `PGR[53]=0x0035`. `IRET` `0123`
file `0x55EF3`. **PROVEN.**

Four groups, `i=0..3`, RAM `[9628+i]`, status `0xC2/CA/D2/DA`,
`DX` for the near call `0xC6/CE/D6/DE`, `SI=0,2,4,6`,
`CH=1,2,4,8`:

`TEST [9628+i],2`; `JZ` skip; `OR DI, 0x10/0x20/0x40/0x0080`
(`81 CF 80 00` at `0076`, file `0x55E46`, imm16 `0x0080`); `IN AL,DX`
status; `AND AL,1` (or `TEST AL,1` on `0xDA`); `JZ` skip;
`CALLN D5DD:0134`.

`D5DD:0134` owned `[0x55F04, 0x55F36)` plus `[0x55F37, 0x55F3E)`
through `016D RET` file `0x55F3D`, 20/24 `0xD5F04` / `0x0D5F04`.
(NOP align at `0x55F36`.) `ES=8010`;
`BX=CS:[SI+012C]`; `CALLF FB00:0725`; `JNS 015C`. Else
`TEST [996F],CH`; `JZ RET`. `ES=A90B`; `BX=CS:[SI+0124]`;
`CALLF FB00:0725`; `JS 0167` (`NOT CH`; `AND [996F],CH`;
`RET`). `015C`: `OR DI,CX`; `MOV AL,CL`; `SUB DX,6`;
`OUT DX,AL`. `FB00:0725` reaches `POP DX` at `06DD`
(file `0x7B6DD`) on the `DX==0` path (`JZ` at `072A` lands
on `06DB`, and `DEC AH` falls into `06DD`) and on the
`0719` / `071E` jumps. The other path `JMP 0706`. When
`DEC AL` there is neither zero nor negative, it does
`POP DX` at `0710` (file `0x7B710`) and then
`MOV DX,[BX+SI+0Ah]` (file `0x7B711`), so the
subtract does not establish ports `0xC0/C8/D0/D8`.
The four
sites write `CH` (`B5 01/02/04/08`), not `CL`, so
`AL` is not `{1,2,4,8}`. Table `[0x55EF4, 0x55F04)` is owned data
(eight words). Mailbox field meaning **UNDETERMINED**.

After the four groups: `PUSH CS` / `CALLN D5DD:1190` (owned
`[0x56F3E, 0x56F7B)`, `ES=A90B`, sum of `ES:[1330]/[1932]/[1F34]/[2536]`,
`RETF`; no `0xC0-0xDF` I/O). If `AX=0`, `CALLF FB00:04AC`
`DL=2`. Then `CLI`; `AND [9628+i],~2` / `OUT` `C6/CE/D6/DE`;
`OUT DX,AL` with `DX=0xC010` and `AL=0x64`, then
`AL=0xC4` (`EE` at `00D5`, file `0x55EA5`; `DX` is still
`0xC010`); if `DI` bits `0x0100/0200/0400/0800`,
`OR [9628+i],2` / `OUT` again. `CALLF FB00:0194`; `IRET`.

---

## 6. `D547:0105` and `D547:04D5` — calls from `0067`

`D547:0067` is owned through `IRET`. It still transfers to:

| Callee | File | `DX` at call | Owner | First I/O | Stop |
|--------|------|--------------|-------|-----------|------|
| `D547:0105` | `0x55575`, 20/24 `0xD5575` / `0x0D5575` | `0xD0` | prefix `[0x55575, 0x555B8)` | `IN AL,DX` `010D` file `0x5557D` | `JMP BX` `011B` file `0x5558B` (`FFE3`) |
| `D547:04D5` | `0x55945`, 20/24 `0xD5945` / `0x0D5945` | `0xC0` or `0xC8` | prefix `[0x55940, 0x55950)` | `IN AL,DX` `04D5` | `JMP CS:[DI+0561]` `055C` file `0x559CC` (also `JMP BX` `051D`, `JMP CS:[BX+053A]` `0535`) |

**PROVEN** that the calls exist and that the callees `IN` the
`DX` loaded by `0067`. The bytes after each `IN`, and the
bounded `JMP BX` / table slots, are §9 and §10. `051D` remains
**UNDETERMINED**. That is what blocks PARTIAL.

---

## 7. Other complete owned `OUT`s of `C6/CE/D6/DE`

`D61A:0BEA` owned `[0x56D8A, 0x56DA6)` through `0C05 RETF`.
File `0x56D8A`, 20/24 `0xD6D8A` / `0x0D6D8A`, `PGR[53]=0x0035`.
`PUSHF`/`CLI`; `OR [9628],4` / `OUT 0xC6`; `OR [9629],4` /
`OUT 0xCE`; `POPF`; `RETF`. **PROVEN.**

`DCF0:09AE` owned `[0x5D8AE, 0x5D953)` through `0A52 RETF`.
File `0x5D8AE`, 20/24 `0xDD8AE` / `0x0DD8AE`, `PGR[55]=0x0037`
at `0x7AD22`. If `[9644]!=0`, `JMPN 0A51` (file `0x5D8B6`) to `POP ES`
/ `RETF`. `[9644]==0` (`74` at `09B4`) runs a loop:
`CALLF D8BC:001C`, and `CALLF CFB3:0008` while `AX!=0`.
Only after `AX==0` does it set `ES=A90B`. For each of
`ES:[1330]/[1932]/[1F34]/[2536]`
nonzero: `OR [996F], {1,2,4,8}` and `OR [9628+i],2` /
`OUT` `C6/CE/D6/DE` with `AL=[9628+i]`. **PROVEN.**
`DCF0:0006` has `JMP CS:[BX+045E]`; not followed. That
walk has no `0xC0-0xDF` `IN`/`OUT` in the prefix.

`DC5B:00E9` file `0x5C699`, 20/24 `0xDC699` / `0x0DC699`,
`PGR[55]=0x0037` at `0x7AD22`. `2E 8B 16 12 00` is
`MOV DX,CS:[0012]`, not a RAM load. The CS words are
`0x00C6` / `0x00CE` / `0x00D6` / `0x00DE` at `0012/0014/0016/0018`.
`OUT DX,AL` follows at `00F6` / `0104` / `0112` / `0120`
(files `0x5C6A6` / `0x5C6B4` / `0x5C6C2` / `0x5C6D0`).
`RETF` `0122` file `0x5C6D2`. The earlier `OUT` at `00BA`
file `0x5C66A` uses `MOV DX,CS:[BX+0012]`, so that port
is not one immediate. **PROVEN.**

---

## 8. Still unknown

- Which site is MIDI versus panel IPC (`U-TE7774`). No
  consumer binds a port to a DGROUP `MIDI` string.
- Bit meaning of `AL` after `IN 0xC2/CA/D2/DA`, of the
  `B03B` write sequence `0,0,0xC0,0x02,0x95`/`0x91`, and
  of `[9628..962B]`.
- `D547:051D` `JMP BX` through `[SI+762E]` (§9). The
  `0105` / `04D5` bytes after the `IN` are §9 and §10.

D24 is not PARTIAL while `051D` is **UNDETERMINED** and the
gap tails at `0x555B8`, `0x556CD`, `0x556EC`, and `0x55902`
are unseeded.

---

## 9. Bound jumps — 2026-09-22

XA=1. Second PGR slot 53 word `0x0035` at file `0x7AD1E`.
24-bit equals the 20-bit address. No `BRKXA`/`RETXA` in these
bodies. Did not enter an indirect dest.

### `D547:0105` — `JMP BX`

Entry file `0x55575`, `D547:0105`, 20-bit `0xD5575`, 24-bit
`0x0D5575`. `JMP BX` file `0x5558B`, `D547:011B`, 20-bit
`0xD558B`, 24-bit `0x0D558B` (`FF E3`). **PROVEN.**

BX writes before that jump: `0105` `MOV BX,[7626]` file
`0x55575` (`8B1E2676`); `0118` `MOV BX,0x011D` file `0x55588`
(`BB1D01`), and only when `TEST AL,0x80` at `0110` is nonzero.
`IN AL,DX` (`EC` at `010D`, `DX=0xD0`) does not write BX.
`CMP BX,0x011D` is at `0109`. `IN AL,DX` at `010D` does not
write flags, so the `JZ 011D` at `010E` still tests that
compare. Taken when `BX==0x011D`, it skips `JMP BX`. The
jump target is not the port byte.
**PROVEN.** `[7626]` as an IP is **UNDETERMINED**.

The only image encoding of disp `7626` is that read and
`04D0` `MOV [7626],BX` / `RET` (file `0x55940`). The owned
`011D` tail stores immediates `0x0148`, `0x027C`, `0x025D`,
`0x0492` (or leaves `0x011D`). `D547:0148` is file `0x555B8`,
a gap. The other three are gap files `0x556EC`, `0x556CD`,
`0x55902`. Did not seed them.

### `D547:04D5` — `JMP CS:[BX+053A]`

Entry file `0x55945`, `D547:04D5`, 20-bit `0xD5945`, 24-bit
`0x0D5945`. Jump file `0x559A5`, `D547:0535`, 20-bit
`0xD59A5`, 24-bit `0x0D59A5` (`2E FF A7 3A 05`). **PROVEN.**

BX writes on that path: `0526` `MOV BL,AL` file `0x55996`;
`0528` `AND BL,0xF0`; `052F` `SHR BL,3`; `0532` `AND BX,0x0E`
(`83 E3 0E`). Domain `BX ∈ {0,2,4,6,8,A,C,E}`. Table
`D547:053A` file `0x559AA`, 20-bit `0xD59AA`, 24-bit
`0x0D59AA`, owned data. Eight words, every target owned
code. Did not follow.

| BX | Word file | Word | Target | Target file | Owned |
|----|-----------|------|--------|-------------|-------|
| `0` | `0x559AA` | `0x061D` | `D547:061D` | `0x55A8D` | yes |
| `2` | `0x559AC` | `0x05D7` | `D547:05D7` | `0x55A47` | yes |
| `4` | `0x559AE` | `0x0613` | `D547:0613` | `0x55A83` | yes |
| `6` | `0x559B0` | `0x05FD` | `D547:05FD` | `0x55A6D` | yes |
| `8` | `0x559B2` | `0x05E7` | `D547:05E7` | `0x55A57` | yes |
| `A` | `0x559B4` | `0x05F7` | `D547:05F7` | `0x55A67` | yes |
| `C` | `0x559B6` | `0x0603` | `D547:0603` | `0x55A73` | yes |
| `E` | `0x559B8` | `0x054A` | `D547:054A` | `0x559BA` | yes |

`JMP BX` at `051D` file `0x5598D`, 20-bit `0xD598D`, 24-bit
`0x0D598D`: the BX write on that edge is `0517`
`MOV BX,[SI+762E]` file `0x55987`. No compare bounds it.
Not the port byte. **UNDETERMINED.**

`04DE` reaches `0555` when `AL>=0xF8`. `DI=(AL&0x0F)<<1`
is `0x10..0x1E`. Those eight words at file `0x559E1`
(`0x05B1`, `0x05D6`, `0x05B7`, `0x05BD`, `0x05C3`, then
`0x05D6` three times) target owned files `0x55A21`,
`0x55A46`, `0x55A27`, `0x55A2D`, `0x55A33`. Did not follow.

D24 stays open. `0105`'s `JMP BX` does not take the port byte
as `BX`. `TEST AL,0x80` does choose `0x011D` over `[7626]`.
The target is not an owned table. File `0x555B8` is a gap.
Not PARTIAL.

---

## 10. Eight `04D5` slots — 2026-09-22

XA=1. `PGR[53]=0x0035` at file `0x7AD1E`. 24-bit is the
20-bit address with a leading 0. No `0F E0` / `0F F0`.
No `IN`/`OUT` in any slot. Did not enter a gap callee.
Did not seed.

Seven slots load `BX` and `JMP D547:0907` (file `0x55D77`,
20-bit `0xD5D77`, 24-bit `0x0D5D77`). That tail is
`SHL SI,1` / `MOV [SI+762E],BX` / `RET` `090D` file
`0x55D7D`. `0067` enters `04D5` with `SI` 0 or 2.
`04D8` `JZ 0517` when `AL` bit 7 is clear; that arm
`SHR SI,1` at `051B` and then `JMP BX`. `04DC` `JB 04E1`
when `AL<0xF8`; `04E1` is the other `SHR SI,1`.
`AL>=0xF8` takes `JMPS 0555` at `04DE`, skips both of
those shifts, and reaches the indirect jump with `SI`
still 0 or 2. Slots that then jump to `0907` store
`[762E]` or `[7632]` on that path. **PROVEN.**
Bit tests are `DS:81D7` and neighbors (`DS=8010` from
`0067`, `MOV AX,8010` / `MOV DS,AX` at file `0x554DC`).
Which arm runs is **UNDETERMINED** (RAM).

| BX | Entry file / IP | `BX` stored at `[SI+762E]` | Stop |
|----|-----------------|----------------------------|------|
| `0` | `0x55A8D` `061D` | `051F`, or `071C` if `[81D7]&1` | `JMP 0907` `062A` |
| `2` | `0x55A47` `05D7` | `051F`, or `06DD` if `[81D7]&1` | `JMP 0907` `05E4` |
| `4` | `0x55A83` `0613` | `051F` if `[81DB]&1` clear; else slot 0 | `JZ 062A` or fall into `061D` |
| `6` | `0x55A6D` `05FD` | `0733` | `JMP 0907` `0600` |
| `8` | `0x55A57` `05E7` | `051F`, or `06D3` if `[81D8]&1` | `JMP 0907` `05F4` |
| `A` | `0x55A67` `05F7` | `07AF` | `JMP 0907` `05FA` |
| `C` | `0x55A73` `0603` | `051F`, or `08CF` if `[81D9]&1` | `JZ 062A` or `JMP 0907` `0610` |
| `E` | `0x559BA` `054A` | `051F` at `054F` file `0x559BF` | `JMP CS:[DI+0561]` `055C` file `0x559CC` |

20-bit of each entry is `0xD5A8D`, `0xD5A47`, `0xD5A83`,
`0xD5A6D`, `0xD5A57`, `0xD5A67`, `0xD5A73`, `0xD59BA`.
Those `[762E]` IPs
are already owned (`051F` `0x5598F`, `071C` `0x55B8C`,
`06DD` `0x55B4D`, `0733` `0x55BA3`, `06D3` `0x55B43`,
`07AF` `0x55C1F`, `08CF` `0x55D3F`). Not entered past
the `RET` / indirect. Slot E does not follow the `DI`
table. **PROVEN.**

`D547:011B` `JMP BX` (file `0x5558B`) domain is the
pad-note immediates `{011D,0148,0176,025D,0263,027C,029A,02D2,0492,049B}`.
Every `E9`/`EB` in file `0x54000`–`0x66000` whose target
is the writer `D547:04D0` (file `0x55940`, same bytes as
`D52A:06A0`) is preceded by `MOV BX` of one of those.
No other immediate. **PROVEN.** Owned stores, under
CS `D547` from IVT[0x0D], are `011D` (the tail), `0148`,
`025D`, `027C`, `0492`. Files: `0148`=`0x555B8` (pad note:
do not seed `D52A:0318`), `025D`=`0x556CD`, `027C`=`0x556EC`,
`0492`=`0x55902`. `follow_local` of each ends at near
`RET` `04D4` file `0x55944`, not one bounded `RETF`.
Not seeded. `051D` also has pad-note `MOV BX,07E1` at
file `0x559F1`; target `D547:07E1` file `0x55C51` is
owned. Not a new writer.

D24 stays open. Not PARTIAL. Refused gap file `0x555B8`.

---

## 11. Three `[7626]` gap IPs — 2026-09-22

The pad note does not refuse files `0x556CD`, `0x556EC`, or `0x55902`; it refuses `D52A:0318` ("Do not seed `0318`") at file `0x555B8`. Gap `CALLF D9C0:0006` sites are `0x5564F` and `0x556DB`. `0x55C0E` is the same `CALLF`, but it is inside owned `D547:0780` `[0x55BF0, 0x55C1F)` and the walk reaches it when `JNZ` at `0794` is not taken. None of those three is `025D`, `027C`, or `0492`. XA=1, second PGR slot 53 word `0x0035` at file `0x7AD1E`; 20-bit `0xD56CD` / `0xD56EC` / `0xD5902`, 24-bit `0x0D56CD` / `0x0D56EC` / `0x0D5902`. `follow_local` from owned-store IPs `D547:025D`, `D547:027C`, and `D547:0492` each ends at near `RET` `04D4` file `0x55944` with no `0F E0` / `0F F0`, but each walk is two runs (missing 621, 566, and 54 bytes) because the near jump enters the already-owned `MOV [7626],BX` / `RET` at file `0x55940`. Not one contiguous body, so nothing was seeded, `JMP CS:[DI+0561]` was not followed, and D24 stays open.
