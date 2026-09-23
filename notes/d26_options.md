# D26 — Option-dependent behavior

**Question:** which option values have a proven owned reader and writer. Image `a52b7122…e770c9`. XA=1, second PGR live. No ledger seed. No `JMP CS:[BX]` BFS.

Printer `B354:01C6` file `0x33706`, `B354:01C6`, 20/24 `0xB3706`/`0x0B3706`, `PGR[44]=0x002C` at `0x7AD0C`: reads a byte through `[BP+0A]`, `SHL 2`, `LES` table `[BP+0E]`. Dir `+0014` file `[0x20014,0x20020)` `NO `/`YES`/NULL. Dir `+0020` file `[0x20020,0x2002C)` `OFF`/`ON `/NULL. **PROVEN** tables (consumer, dword stride, NULL bound). BSS init is `FAC0:0134` zero, not an option writer.

**PROVEN owned reader and writer**

- `[F7EC]` byte 0/1, ` On:` via `+0014`. Writer `C303:019C` file `0x431CC`, 20/24 `0xC31CC`/`0x0C31CC`, `PGR[48]=0x0030` at `0x7AD14`: `MOV [F7EC],AL` (`A2 EC F7`) after `PUSH CS` at `0198` (file `0x431C8`, `0E`) and `CALLN 0EFE` at `0199` (file `0x431C9`). The other caller is `C303:0F50` file `0x43F80` (`0E`), then `CALLN` and the same store at `0F54` file `0x43F84`. `0EFE` (file `0x43F2E`) is `MOV AL,[8C89]` / `CBW` / `MOV BX,AX`. `0F04` (file `0x43F34`) `TEST [BX+92AE],1`: bit set → `XOR AX,AX` / `RETF`; bit clear → `MOV AX,1` / `RETF`. **PROVEN.** Both returns are `RETF` (`CB`). Reader `C303:01AD` `CALLF B354:01C6`; `C303:07AC` file `0x437DC` `MOV AL,[F7EC]`. Bit name **UNDETERMINED**.
- `[89F2]` byte, Simul Sequence `On/Off:` via `+0020`. Paint `B3ED:002F` file `0x33EFF`, 20/24 `0xB3EFF`/`0x0B3EFF`, `PGR[44]=0x002C`. Reader `E398:000A` file `0x6398A`, 20/24 `0xE398A`/`0x0E398A`, `PGR[56]=0x0038` at `0x7AD24` `MOV AL,[89F2]`. Writers `E398:0010` `MOV [89F2],0`; `E398:03B4` file `0x63D34` `MOV [89F2],AL` from `[FF80]`. Effect **UNDETERMINED** (do not enter `DE32:000F`).

**Owned reader, no owned writer:** `C44E` `Local mode:` `[8370]`, `Soft thru:` `[836F]`, `Convert sustain pedal to duration:` `[8371]`, `Send MMC:` `[8623]` (`+0020`); `C4C8:1BE9` `Record mix changes:` `[E612]` (`+0014`). Stores `MOV [836F],AL` file `0x57607` and `MOV [8371],AL` file `0x5760F` are unowned.

**No owned Other Options paint:** `In play:` `+5BAE` / `[8457]` / `+0014` at file `0x48511`; `Count in:` `+5BBF` / `[8372]` / table `+59BC` `REC+PLAY`/`REC ONLY`/NULL, title push at file `0x4854F`, `CALLF B354:01C6` at `0x48553`; `Tap Tempo` `+6B2F` at file `0x4D857` is `PUSH 0x6B2F` then `CALLF EBFF:0000` and `ADD SP,4`, not `B354:01C6`. Gap `[0x484C9,0x4A458)`. `C6C2:182D` and `C6C2:1895` own `[0x4844D, 0x484C9)`. `[8372]` zero is `B21A:0334` file `0x324D4` `C6 06 72 83 00`, init, not that screen. `[8457]` store file `0x5763A` unowned.

**Blocks the checkbox:** those unowned app-ROM bodies. Not a datasheet-only close. `Select option:` `EBC8:0018` and `SMPTE Sync -(I-0055 OPTION…)` `B000:00CC` are other strings. No owned board-present consumer (EXM3008 photos are not one). OTHER key is `U-PANEL-ROM`. Do not invent panel, LCD, or option-hardware behavior.

D26 stays `[ ]`. The unowned In play / Count in / Tap Tempo bodies and the MIDI stores at `0x57607` are still software. Refused `C887:09AC` file `0x4921C` stays refused. A missing panel ROM does not turn those holes into hardware.

---

## 2026-09-22 — owned `[F7EC]` / `[89F2]` re-read

`C303:0198` file `0x431C8` `0E` PUSH CS. `0199` file `0x431C9` `E8 62 0D` CALLN rel16 `+3426` → `0EFE`. `019C` `A2 EC F7` MOV `[F7EC]`,AL (opcode `A2`, AL source, moffs16 `0xF7EC`). `0F50` `0E` PUSH CS; `E8 AA FF` CALLN rel16 `-86` → `0EFE`; `0F54` same `A2 EC F7`. `07AC` `A0 EC F7` MOV AL,`[F7EC]` (opcode `A0` writes AL).

`0EFE` file `0x43F2E` is `A0 89 8C` MOV AL,`[8C89]` (writes AL), `98` CBW (writes AX), `8B D8` MOV BX,AX (writes BX). `0F04` file `0x43F34`: `F6 87 AE 92 01` TEST BYTE `[BX+92AE]`, imm8 `1` (`F6 /0`, ModR/M `87`, disp16 `0x92AE`). `74 03` JZ `0F0E` (taken ZF=1, bit clear) → `B8 01 00` writes AX, imm16 `1`, `CB` RETF. Fallthrough (bit set, ZF=0): `33 C0` XOR AX,AX (writes AX), `CB` RETF.

`E398:000A` file `0x6398A` `A0 F2 89` MOV AL,`[89F2]` (writes AL). `0010` `C6 06 F2 89 00` MOV BYTE `[89F2]`, imm8 `0` (`C6 /0`, ModR/M `06`). Owned `[0x63989, 0x63A99)` ends `0118 RETF`; this walk does not reach `03B4`.

`E398:0386` file `0x63D06`, owned `[0x63D06, 0x63D3D)`: `03B1` `A0 80 FF` MOV AL,`[FF80]` (writes AL); `03B4` `A2 F2 89` MOV `[89F2]`,AL; `03BC RETF`. Starting at `03B0` (`E5 A0`) is not an instruction boundary.

Unowned: `A2 6F 83` at file `0x57607` (opcode `A2`, moffs16 `0x836F`); `A2 71 83` at `0x5760F` (`0x8371`); `A2 57 84` at `0x5763A` (`0x8457`). Gap `[0x57379, 0x57A0C)`, zero owned `CALLF`/`JMPF`. In play / Count in remain in refused gap `[0x484C9, 0x4A458)`. Tap Tempo file `0x4D857` is gap `[0x4C5C9, 0x4EBCC)`. Do not seed. D26 stays `[ ]`.

---

## 2026-09-22 — MIDI store `0x57607` / Tap Tempo `0x4D857` callers

Owned `code` linear `decode_one` from range start, CS = first `CS:IP` in `why`, span in that CS window. Immediate `CALLN`/`CALLF`/`JMPN`/`JMPF` only (no r/m). Target file `0x57607` (`MOV [836F],AL`): no immediate `CALLF`/`JMPF` in owned code, and no immediate near transfer in a range whose `why` names a `CS:IP` or whose `CS` is a far-call target. Target file `0x4D857` (Tap Tempo `+6B2F`): the same. 269 `code` ranges have neither source of `CS`, so a near transfer in those ranges is unchecked. Stop. Do not seed. Did not enter `C887:09AC` or the gap `[0x484C9, 0x4A458)`. D26 stays `[ ]`.
