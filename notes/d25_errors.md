# D25 — Error, cancel, recovery

**Question:** which error/cancel/recovery texts have an owned consumer, and what path they take. Image `a52b7122…e770c9`. XA=1, second PGR live (`PGR[62]=003E`).

**PROVEN BIOS hang** (owned `[0x79946,0x79B26)`). `F800:19B3` file `0x799B3`, 20/24 `0xF99B3`/`0x0F99B3`: `OUT DX=0xC011,AL=0xFF` (`U-C0XX`); `INT 43` AX=1; `CALL 1875` at `19BE`; inline `[0x799C1,0x79A0C)` `System Error…type `; `(saved IP−1956)/3`; `CALL 1896`; `CALL 1875` at `1A17`; inline `[0x79A1A,0x79AD2)` `h\r\ncaused all memory…yahoo.com.au`; `JMP 1AD2`. Walker `F800:1875` file `0x79875`. Bounds = near `CALL` + C-string + `NUL`. No recovery. “Memory lost” is text, not a RAM wipe. Banner `0x78125` is not an error string.

**PROVEN owned `B1B1:005B`** file `0x31B6B`, 20/24 `0xB1B6B`/`0x0B1B6B`, `PGR[44]=002C`: `Searching SCSI for hard disk... <Cancel>` (DGROUP image file `0x211EF`, offset `0x11EF`) `B000:0165` `0x30165`; `Can't find file` then `Please insert disk` (offset `0x4B26`, file `0x24B26`) `C20F:0B1E` `0x42C0E`; `Can't find file` then `Press <Skip file>` (offset `0x4BB3`, file `0x24BB3`) `C20F:0B2C` `0x42C1C`; `PROGRAM MEMORY SPACE ALLOCATION ERROR` (DGROUP image file `0x26F52`, offset `0x6F52`) `CF37:0249` `0x4F5B9` then `JMP $` at `0255`; `<Cancel>` (offset `0x77C7`, file `0x277C7`) `DE5C:0A62` `0x5F022`; `Recovering sequence…` `E1A6:01BE` `0x61C1E`. `[Error code: %04x]` `0x21DE2` via `B354:0919` `PUSH DS` / `PUSH 0x1DE2`; `CALLF B1BC:01EE` is at `091D` file `0x33E5D` (indirect `JMP CS:[BX+0422]` at `B1BC:02CC` file `0x31E8C`; do not BFS).

**No owned consumer:** directory has zero error strings; zero unconsumed DGROUP min-2 keyword C-strings. App-ROM min-4 `error`/`cancelled`/`recover` (`0x53484`…) have no consumer (**UNDETERMINED**). Unowned `PUSH DS` sites: `0x36E16`, `0x47133`, `0x487AB`, `0x4CAC8`, `0x4CADC`. `0x4797B` is owned `C6C2:0D24`. `Enable transport mode error warnings:` is a `B354:01C6` title, not an error path.

**Blocks the checkbox:** Panel Cancel is `U-PANEL-ROM`. Glass is `U-LC7981`. BIOS and ALLOCATION hang. `DF4F:0009` and the `B1BC:01EE` switch dests are explained below.

## 2026-09-22

Ledger read-only (`analysis/owner_ledger.json`). No seed. XA=1, second PGR `0x7ACB4`.

**`DF4F:0009`** owned `[0x5F4F9, 0x5FA5B)`. File `0x5F4F9`, 20/24 `0xDF4F9`/`0x0DF4F9`, `PGR[55]=0037` at `0x7AD22`. Far cdecl `[BP+6]:[BP+8]`. Recovering `E1A6:01BE` file `0x61C1E` (owned `[0x61A62, 0x61F0C)`) puts `DS:77D0` (`0x277D0` `Recovering sequence, please wait ... `) via `B1B1:005B`, then `PUSH DS`/`PUSH 9208`/`CALLF DF4F:0009` at `01CE` file `0x61C2E`. The C-string is not an argument. **PROVEN.** `CMP [89ED],0` / `JZ 003D`; else if the pointer is `DS:9208`, `[920C]=[920A]=0`, `[9208]=0xFF`, `AX=0`, `RETF` `003C` file `0x5F52C`. Otherwise `LES BX,[BP+6]` at `003D` (file `0x5F52D`). `OR AX,ES:[BX+4]` after `MOV AX,ES:[BX+2]` (`26 0B 47 04` at file `0x5F534`). Zero jumps to `051A` (`E9` at file `0x5F53A`). Nonzero reaches `004D`, which tests the pointer again: not `DS:9208` also jumps to `051A` (files `0x5F544` and `0x5F54E`). The copy at `0061` runs only when `[89ED]==0` and the pointer is `DS:9208` and those words are nonzero. `051A` (file `0x5FA0A`) stores `ES:[BX+4]=0`, `ES:[BX+2]=0`, `ES:[BX]=0xFF`, then `CALLF E0AA:02B4` and `CALLF DE36:000C`. `RETF` `056A` file `0x5FA5A`. `[89ED]` and the `9208` object fields **UNDETERMINED**.

Owned absolute stores of that byte, second PGR, XA=1, identity frames (24-bit equals 20-bit): `E0AA:0066` file `0x60B06`, 20/24 `0xE0B06`/`0x0E0B06`, `PGR[56]=0x0038` at `0x7AD24`, `MOV byte [89ED],0` (`C606ED8900`) after `CALLF DF4F:0009` / `ADD SP,4`. `E614:001B` file `0x6615B`, 20/24 `0xE615B`/`0x0E615B`, `PGR[57]=0x0039` at `0x7AD26`, same `MOV` of 0. `E676:006B` file `0x667CB` stores 0; `E676:0081` file `0x667E1` and `E676:0110` file `0x66870` store 1 (same `C6 06 ED 89`). **PROVEN** as stores. What the byte means stays **UNDETERMINED**.

**Six `PUSH DS`:** five callers are still in gaps and are not reached by an owned `code` range linear decode. Do not seed those. `0x36E16` gap `[0x35098,0x370F1)` `Searching SCSI for hard disk... <Cancel>` `B1B1:005B`. `0x47133` gap `[0x46C2B,0x47944)` `Waiting for input signal... <Cancel>` `B1B1:005B`. `0x4797B` is inside owned `C6C2:0D24` `[0x47944,0x47A6B)` and the walk reaches `PUSH DS` at IP `0x0D5B` (`Recording... <Cancel>`, `CALLF B1B1:005B`). `0x487AB` gap `[0x484C9,0x4A458)` title `Enable transport mode error warnings:` `B354:01C6`. `0x4CAC8` / `0x4CADC` gap `[0x4C5C9,0x4EBCC)` `Searching for previous event... <Cancel>` / `Searching for next event... <Cancel>` `B1B1:005B`. **PROVEN.**

D25’s remaining blockers are `U-PANEL-ROM`, `U-LC7981`, and the unfollowed `B1BC:01EE` switch. Panel Cancel stays `U-PANEL-ROM`. Glass stays `U-LC7981`.

**`B1BC:01EE` switch.** Owned body `[0x31DAE, 0x31EAC)`. Entry `B1BC:01EE` file `0x31DAE`, 20/24 `0xB1DAE`/`0x0B1DAE`, XA=1, `PGR[44]=002C` at `0x7AD0C`. Linear sweep of that body to the indirect jump: prologue `JMPN 0412` at `01FF` file `0x31DBF`; `CMP AX,0x64` at `028F` (file `0x31E4F`). `74 63` at `0292` (file `0x31E52`) is `JZ 02F7` when `AX==0x64`. `7F 27` at `0294` (file `0x31E54`) is signed `JG 02BD`, taken when `AX>0x64`; `SUB AX,0x6C` `02BD` file `0x31E7D`; `MOV BX,AX` `02C0` file `0x31E80`; `CMP BX,0x0C` `02C2` file `0x31E82`; `JBE 02CA` else `JMPN 040F`; `SHL BX,1` `02CA` file `0x31E8A`; `JMP CS:[BX+0422]` `02CC` file `0x31E8C`, 20/24 `0xB1E8C`/`0x0B1E8C`. Index domain unsigned `BX<=0x0C` then `SHL 1` — 13 words. Table CS:0422 file `0x31FE2`, 20/24 `0xB1FE2`/`0x0B1FE2`, owned data `[0x31FE2,0x31FFC)`. Did not follow dests. **PROVEN.**

Slots the compare can select (word file, value, dest CS:IP, dest file, dest in owned `code`): `0x31FE2` `02EC` `B1BC:02EC` `0x31EAC` yes `[0x31EAC,0x31EB7)`; `0x31FE4`/`0x31FE6`/`0x31FE8`/`0x31FEA`/`0x31FEC`/`0x31FEE`/`0x31FF2`/`0x31FF6`/`0x31FF8` `040F` `B1BC:040F` `0x31FCF` yes `[0x31F4B,0x31FE2)`; `0x31FF0` `036F` `B1BC:036F` `0x31F2F` yes `[0x31F0C,0x31F4B)`; `0x31FF4` `02F2` `B1BC:02F2` `0x31EB2` yes `[0x31EAC,0x31EB7)`; `0x31FFA` `034C` `B1BC:034C` `0x31F0C` yes `[0x31F0C,0x31F4B)`. Every selectable dest is owned. Switch targets are owned. No gap entry from this table walk. Do not seed. D25 still lacks panel ROM (`U-PANEL-ROM`) and glass (`U-LC7981`).

## 2026-09-22

**`B1BC:01EE` unique dests.** `decode_one` from each dest in owned code. Stop at `RETF` / `JMP $` / indirect. No `JMP $`. Did not enter callees. No dest `CALL` file is a gap. No dest calls `B1B1:005B` or `DF4F:0009`. XA=1, `PGR[44]=002C` at `0x7AD0C`. **PROVEN.**

- `B1BC:02EC` file `0x31EAC`, 20/24 `0xB1EAC`/`0x0B1EAC`, span `[0x31EAC,0x31EB2)`: `MOV SI,1`; `JMPN 0236` file `0x31DF6` (owned switch body). No RET in dest.
- `B1BC:02F2` file `0x31EB2`, 20/24 `0xB1EB2`/`0x0B1EB2`, span `[0x31EB2,0x31F0C)`: `[E743]=1`; both paths owned `CALLN B1BC:00AF` file `0x31C6F`; `JMPN 040F`. Returns via `040F` `RETF`.
- `B1BC:034C` file `0x31F0C`, 20/24 `0xB1F0C`/`0x0B1F0C`, span `[0x31F0C,0x31F2F)`: owned `CALLN B1BC:00AF`; `JMPN 040F`. Returns via `040F` `RETF`.
- `B1BC:036F` file `0x31F2F`, 20/24 `0xB1F2F`/`0x0B1F2F`, span `[0x31F2F,0x31F4B)`: owned `CALLN B1BC:0040` file `0x31C00`; `JMPN 040F`. Returns via `040F` `RETF`.
- `B1BC:040F` file `0x31FCF`, 20/24 `0xB1FCF`/`0x0B1FCF`, span `[0x31FCF,0x31FE2)`: `INC word [BP+6]` at `040F` is the offset loaded by `LES BX,[BP+6]` at `0412`. `0415` is `CMP byte ES:[BX],0`. `74 03` at file `0x31FD9` is `JZ 041E` when that byte is zero, then `POP DI`/`POP SI`/`LEAVE`/`RETF` `0421` file `0x31FE1`, 20/24 `0xB1FE1`/`0x0B1FE1`. A nonzero byte `JMPN 0202`. No hang.

Every dest explained. Remaining unnamed: panel Cancel (`U-PANEL-ROM`) and glass pixels (`U-LC7981`).

## 2026-09-23

MAME’s panel matrix (`06-mame/MAME_MPC3000_maps_irqs_roms.md`) names Soft Key 1–4, Stop, Play, and the pad rows. No row bit is named Cancel. The `<Cancel>` strings in this note stay panel-ROM text until that dump exists. The HD61830 stand-in names the seven AX=0 commands (`notes/boot_reset_to_bios_banner.md`) and does not produce a glass frame. D25 stays `[PARTIAL]`.
