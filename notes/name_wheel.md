# Name Wheel: spell names with the data wheel

**Target:** PMONEY universal build, OS 3.16 + cave (`port-316`, head
`0876235`). **Date:** 2026-10-22. **Status:** implemented
(`mods/namewheel316.inc`, Extra Settings 2 in `mods/xparams316.inc`, hooks
in `mods/WAVE316.args`); PROVEN in MAME on the 3.12 and 3.08 sets
(`emu/test_namewheel316.py`, one execution each); not run on hardware.

Address forms follow [`port_316.md`](port_316.md). Tags per
[`AGENTS.md`](../AGENTS.md).

## 1. Origin

Owner request (2026-10-22): replicate the "RenameX" feature of the
third-party OS 3.39.3 Beta "Track Mute Edition" (a patched stock 3.16), "in
our PMONEY way, not a byte for byte copy, the same functionality for the
user". The 3.39.3 behaviour was mapped from its bytes (static analysis,
working notes outside the repository); none of its code or text is used.

What 3.39.3 does (**PROVEN, code**): one global switch, `<RenameX>` on the
Other page (Soft Key 4), ON at every boot and never saved. While ON, every
stock text field (type 1, made by `05C8:000D`) is edited with the wheel
through a 50-character set; Up/Down set capitals/small letters; Left/Right
set capital at position 0 and small elsewhere; PLAY types a space. Every
other key is swallowed while editing: the letter buttons and digits stop
typing (a regression from stock).

## 2. PMONEY behaviour

| Key, editing a name | Name Wheel ON | Stock 3.16 (OFF) |
|---|---|---|
| wheel / `+` `-`, idle field | opens the edit **and** steps the character at once | opens the edit only |
| wheel / `+` `-`, editing | steps space, A-Z, 0-9, then the stock symbols `-@!#$%&(){}'_` (read live from DS `1D51`), wrapping; letters take the current case | the field's original character and ` -@!#$%&(){}'_` only |
| Up / Down | capitals / small letters, applied in place and **locked** for the rest of the edit | type `P` / `Q` |
| Left / Right | move as stock; without a lock the letter landed on takes title case (capital at a word start: position 0 or after space, `_`, `-`) | move |
| letter buttons, digits, `.`, PLAY (space), PLAY START (case), ENTER, soft keys, MAIN SCREEN | stock | stock |

Differences from 3.39.3, by design: nothing is swallowed; the first turn steps
one character, not the coalesced count; the case lock (3.39.3 re-cases on
every Left/Right); title case at word starts, not only at position 0; the
switch is saved with the system parameters; it lives on a new Extra Settings
page, because Other → Soft Key 4 is PMONEY's `<Extra>`.

Setting: **Other → `<Extra>` → `<More>`**, "Spell names with the data
wheel: ON/OFF", default ON (3.39.3's default). Byte DS `8322` (the last free
byte of the parameter-block reserve, zero-filled and read by no stock code;
see `profile_316.inc` Input Thru), stored inverted (0 = ON), so Init PAR, a
failed NVRAM checksum and every older `.PAR` give ON.

## 3. Hooks (3.16 image offsets; DS = DGROUP)

| Image | Stock bytes | Hook | Stock routine |
|---|---|---|---|
| `0x4DE9` | `MOV AL,[7A61]` … `MOV [1D4F],AL` (13) | `nw_first` | text-field key handler `04D5:000E`, idle `+`/`-` after `begin_edit` |
| `0x4DFE` | `MOV AX,DX` / `CMP AX,4Dh` | `nw_edit_key` | same handler, the editing-state switch (DX = key) |
| `0x4FC7` | `PUSH BP` / `MOV BP,SP` / `SUB SP,6` | `nw_wheel` | wheel step `04D5:0277` |
| `0x5066` | `MOV [E436],0` / `RETF` | `nw_reset_case` | case reset at every field entry `04D5:0316` |

State: buffer DS `7A38` (41 bytes), cursor `7A61`, length `7A65`, case flag
`E436`, original-character slot `1D4F` (all **PROVEN, code**; the handler is
Vailixi `B261:000A`, offsets +4). Gate: setting ON and length 1..40.
Characters go to the LCD through `0427:0040` (the display316 fast put-char
hook site), as stock does.

## 4. Evidence and open items

- MAME (`emu/test_namewheel316.py`, sets `default` and `v308`): spelling on
  Play/Record's sequence name, case lock, PLAY space, digits at the cursor,
  stock commit (`space -> _`), Extra Settings 2 ON/OFF, OFF = stock first turns.
  **PROVEN (one execution per set).**
- Not tested: every other name field (track, program, sound, file, copy
  names share the handler, **HYPOTHESIS** that they behave identically);
  8-character file names with small letters on a PC (stock PLAY START can
  already make them; **UNDETERMINED**).
- Hardware: the physical wheel detent rate and the letter legends of the
  real panel (emulator names, `emu/panel.py`) — **deferred physical test**.
