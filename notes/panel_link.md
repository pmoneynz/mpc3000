# Panel link: OS-side protocol and key map

**Image:** Vailixi 3.50 linear. **Date:** 2026-09-25.
Emulator: `MPC3000_builds` (MAME branch `mpc3000-accuracy`), see
[`emulator.md`](emulator.md).

This note is about what the **V53 OS accepts** on the panel link. What
the real uPD78C10 firmware sends, and when, is `U-PANEL-ROM` / `U-PHYS`.
A frame below reaching the OS proves the OS's meaning for that frame, not
that the physical panel emits it.

## 1. Transport

The OS polls the TE7774 at `D547:006C`: port `D2` (channel 2, panel), then
`C2`, then `CA`, each `IN AL,port / TEST AL,2 / JNZ skip`. Channel-2 data
is read at `D547:010D` (`IN AL,DX`, file `0x5557D`) inside the parser.
**PROVEN** (code).

Frames injected at 31250 baud 8N1 into TE7774 RXD3/RXD4 (MAME `panel`
port, media `midiin3`) are read at `D547:010D` byte for byte, e.g.
`45.000327 90`, `45.000647 42`, `45.000967 7F`. **PROVEN (trace).**
The real link's baud rate is not established on hardware (MAME's TE7774
model receives every channel at 31250).

## 2. Frame grammar (parser `D547:0105`, file `0x55575`)

State continuation in `[7626]` (default `0x11D`); a byte with bit 7 set
restarts; `[9645]` counts restarts mid-frame. No `0F E0`/`0F F0` bytes in
`D547:0000-05FF`, so the ndisasm stream is usable there.

| Frame | Handler | Meaning | Tag |
|-------|---------|---------|-----|
| `90 kk vv`, `kk < 10` | `0x148` | Raw pad `kk` -> pad `CS:0057[kk]` (= `kk ^ 0C`) into `[762C]`; `+[D6A2]` (bank) into `[D6AC]`; note via `D9F2:000C`; `vv` velocity, 0 = release | **PROVEN** (code + trace) |
| `90 kk vv`, `kk >= 10` | `0x16D` -> `0x2D2` | Key: `vv != 0` press, `0` release (`0x418`) | **PROVEN** |
| `A0 kk vv` | `0x27C` | Pad pressure | **PROVEN** (code) |
| `B0 xx vv` | `0x25D` -> `0x263` | `xx` ignored; `vv` -> `[9969]`, `D9C0:0006` -> `[996A]` (note variation) | **PROVEN** (code). Value scale **UNDETERMINED** |
| `E0 dd dd` | `0x492` -> `0x49B` | Second byte must equal first; `00` queues `+`, `7F` queues `-` | **PROVEN** (code + trace: Seq 1->3->2) |

Key press (`0x2D2`): `code - 0x40` indexes the table at `CS:0006`; the
result is a command character. Codes `10-3F` and characters `0` are
ignored on press (`0x348` -> `0x48C`). Characters `V W X Y Z`
(`0x74-0x78`) set transport flags `[A7B1]`/`[A7B2]`/`[A7B3]` and call
`DCA2:0004`; `+ - ! ^ > < [ { } ]` go through `FB00:0396` (repeat) then
the queue; `T` stamps `[D7D0]=[D69F]`; `a`/`c` toggle `[D699]`/`[D697]`
with `INT 46` `AL=0F`/`0D`. Everything else is queued into `DS:12BC`
via `DA09:0000` (overflow counter `[9649]`). **PROVEN** (code).

`[D697]` set forces pad velocity to `7F` (`0x1A1`, `0x29A`): FULL LEVEL
semantics. **PROVEN** (code).

## 3. Key map

Method: boot 3.50 to Play/Record, tap one code at 45 s, read the LCD at
47 s (`MPC3000_builds/emu/key_sweep.py`); codes with no text change were
re-run in a context where the effect is visible (cursor address writes
`IR 0A/0B`, recorded bars, tempo field, count-in). Button names come from
the screen the OS opens. **PROVEN (trace)** unless tagged.

| Code | Button | Evidence |
|------|--------|----------|
| `40` | Full Level | `[D697]` toggle (code) |
| `41` | 16 Levels | "Assign '16 Levels'" |
| `42` | After | **HYPOTHESIS**: only unassigned left-column button; toggles `[D699]`, LED `0F` |
| `43 44 45` | 7 8 9 | digit typed into Seq field |
| `46 47 48 49` | Soft keys 1-4 | Tk on/off, Solo, Track- (after Track+), Track+ |
| `4A` | Help | "Help" screen while held |
| `4B 4C 4D` | 4 5 6 | digit |
| `4E` | Disk | "Save to Disk -- Load, Other" |
| `4F` | Tempo/Sync | "Tempo" |
| `50` | Mixer/Effects | "Mixer" |
| `51` | Program/Sounds | "Programs / Sounds" |
| `52` | Song | "Song Mode" |
| `53` | none | table value `0` |
| `54 55 56` | 1 2 3 | digit |
| `57` | Edit (Seq Edit) | "Edit Sequence" |
| `58` | Step Edit | "Step Edit" |
| `59` | Edit Loop | "Edit Loop" |
| `5A` | MIDI | "MIDI" |
| `5B` | Other | "Metronome / Foot switches / Free Memory" |
| `5C` | Pad Bank | pad label A13 -> B13 after one press; routine at file `0x5EC42` steps `[D6A2]` by 16 and sets LEDs 9-12 via `D6FA:0001` |
| `5D` | . | tempo `1 0 0 . 5 Enter` -> 100.5 |
| `5E` | 0 | digit |
| `5F` | Enter | tempo `2 0 0` shows `200`; with Enter `200.0` |
| `60` | Wait For Key | transport holds at 001.01.00 until a pad hit |
| `61` | Auto Punch | "Auto Punch" |
| `62 6B 6A 6C` | Up Down Left Right | cursor `2C`->`A4` (down), back (up); `2C`->`2F` (right), back (left) |
| `63` | Transpose | "Transpose" |
| `64` | 2nd Seq (Simul Seq) | "Simul Sequence" |
| `65 6E` | + - | Seq 1->2; 2->1 |
| `66` | Erase | "Erase" |
| `67` | Timing Correct | "Timing Correct / Step Size" |
| `68` | Tap Tempo | 5 taps 0.4 s apart -> BPM 150.2 |
| `69` | Count In | start delayed one bar, then runs |
| `6D` | Main Screen | Play/Record redraw |
| `6F 70` | << < | 002.03.00 -> 002.01.00; -> 002.02.72 |
| `71` | Locate | "Locate" |
| `72 73` | > >> | 002.03.00 -> 002.03.24; -> 003.01.00 |
| `74 75` | Rec, Over Dub | both "(Record Ready)". Order **HYPOTHESIS** (code sequence `6F-78` follows the panel's left-to-right layout) |
| `76` | Stop | Now frozen at 001.04.00 |
| `77` | Play | resumes from stop position |
| `78` | Play Start | restarts from 001.01 |
| `79` | Assign (Note Var) | "Assign Note Var Slider" |
| `7A-7F` | none | table value `0` |

57 buttons, 57 non-null codes. Front-panel LEDs are not on the link:
they are the main CPU's `loledlatch`/`hiledlatch` at I/O `00`/`20`
(no OS writes to TE7774 `D0`/`D8` were seen after any key).

## 4. Emulator stand-in

With CONFIG "Front panel = HLE" (default), the driver scans MAME's `Y0-Y7`,
`PB0-PB3`, `DATAENTRY` and `VARIATION` ports every 1 ms and sends the
frames above at 31250 baud into the same wired-AND RXD3/RXD4 line.
Pad numbering follows MAME's layout (`PBn` bit 4-7 = pad rows from the
bottom, `PB3` left column); verified: pads 1, 13, 16 and bank B pad 2
give OS labels A01, A13, A16, B02.

Not modelled (all `U-PANEL-ROM`): real scan rate and debounce, pad
velocity curve and pressure stream (HLE pads send `7F`, no `A0`),
dial acceleration, slider value scale, and any frames the firmware sends
that this OS-side analysis has not seen.
