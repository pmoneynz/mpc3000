# Track Mute: mute sequence tracks with the pads

**Target:** PMONEY universal build, OS 3.16 + cave (`port-316`, head
`0876235`). **Date:** 2026-10-22. **Status:** implemented
(`mods/trackmute316.inc`, hooks in `mods/WAVE316.args`, pad capture shared
with Lazy Chop, PLAY kept on the page by `xp_play_stay`); control path PROVEN
in MAME on the 3.12 and 3.08 sets (`emu/test_trackmute316.py`, one execution
each); audio not observed; not run on hardware.

Address forms follow [`port_316.md`](port_316.md). Tags per
[`AGENTS.md`](../AGENTS.md).

## 1. Origin

Owner request (2026-10-22): replicate the Track Mute page of the third-party
OS 3.39.3 Beta "Track Mute Edition" (a patched stock 3.16) in PMONEY's own
way, with the same functionality for the user. Owner decision: entry is
**SONG pressed on the Song page** (stock Song mode is kept). Its behaviour was
mapped from its bytes (static analysis, working notes outside the repository);
none of its code or text is used.

What 3.39.3 does (**PROVEN, code**): a short SONG press opens a 4 x 4 page of
tracks bank+1..bank+16 (pads 13-16 on top) without stopping the transport; a
2 s hold opens the stock Song page, which it relocated over the stock Help
text (Help is disabled). A pad toggles the stock "On:" flag of the track's
header slot. Faults found: the cell number is used as the slot (wrong after
Change Track Order); the pad is read from `[D399]` when the key is handled
(MIDI notes and fast pad bursts toggle wrong tracks); `[8976]` is overwritten
while the playback task reads it; no write-through to the track record.

## 2. PMONEY behaviour

| Input on the page | Effect |
|---|---|
| pads | mute / unmute tracks bank+1 .. bank+16; the pads neither sound nor record while the page is up |
| PAD BANK | tracks 1-16, 17-32, 33-48, 49-64 (row 5 names the bank) |
| PLAY / PLAY START | play the active sequence; the page stays |
| Soft Key 1 `<All on>` | unmute tracks 1-99 |
| SONG | back to the Song page |
| MAIN SCREEN, other mode keys | leave as usual |

Cells: `NN NAME   ` (first 6 characters of the track name), `NN(muted) `,
`NN -      ` for an empty track. Row 5: `Seq NN  Pads mute tracks, bank A:
01-16`. Text is PMONEY's own.

A mute is the stock Play/Record `On:NO` flag (bit 0 of the header slot byte
DS `8F9B+slot`), which the playback loop tests per event (image `0x3361B`,
**PROVEN, code**); so it takes effect on the next event of that track, with
no quantize, exactly as `<Tk on/off>`. Persistence is the stock one: the
flag is written through to the track record (`tm_store`, the record loop of
`148A:11BC` without touching the current track or `[8976]`) and is saved
with the sequence. An "(unused)" track has no record and loses its On flag
on the next Song page visit, as in stock 3.16 (MAME, `<Tk on/off>`).

## 3. Design points

- **Entry.** The Song page's key loop skips SONG (image `0x69E3`, `CMP AX,'G'`
  / `JMP 0F6F`). `tm_song_key` makes it leave with `'G'`; the dispatcher calls
  the Song page again through `tm_song` (image `0x15BD7`, was `CALLF
  0671:000A`), which runs Track Mute instead when the previous Song page
  ended that way, and the Song page when Track Mute ends with SONG.
- **Song context.** The Song page loads the current song into the header
  (`3C97:0009` sets `[86DA]`). The page leaves it as the dispatcher's Main
  case does (`3D25:007D`, Vailixi `E704:0081`), so PLAY plays and the pads
  mute the **active sequence**.
- **Mode.** The page runs with `MODE = 'O'` (the Other page's) and the play
  screen `[D39C] = 'M'`: PLAY plays the sequence (only `'G'` plays the song,
  `3481:0215`) and the play-screen updater (image `0x40BB0`: modes M, G, S,
  `/`) does not draw Play/Record fields over the page. `xp_play_stay` keeps the
  page when PLAY would switch to the play screen.
- **Pads.** `pad_own_press` (Lazy Chop) also captures pads while `tm_owned`
  and `MODE = 'O'`: pad + bank from the parser's own bytes (`[701C]`,
  `[D38F]`) into the cave ring, key `'D'`, ring 5 skipped; releases and
  pressure of captured pads stay in the cave. MIDI notes are not captured.
- **Track to slot.** Through the header map DS `8F37+track` as Play/Record
  (image `0x1552A`), building it with `38B1:0382` when it reads `FFh`.

## 4. Hooks (3.16 image offsets)

| Image | Was | Now |
|---|---|---|
| `0x15BD7` | `CALLF 0671:000A` (Song page) | `CALLF tm_song` |
| `0x69E3` | `CMP AX,47h` / `JNZ` | `JMP FAR tm_song_key` |
| `pad_own_press` (cave) | Lazy Chop only | + `tm_owned` → `tm_pad_press` |
| `xp_play_stay` (cave) | Mixer / Edit Sound | + `tm_owned` → stay |

## 5. Evidence and open items

- MAME (`emu/test_trackmute316.py`, sets `default` and `v308`): SONG twice,
  names, PLAY with the page kept and not overdrawn, pad 1 mutes track 1, bank
  B/D labels, Play/Record `On:NO`, the mute kept across a Song page visit,
  `<All on>`, SONG back to the Song page. **PROVEN (one execution per set).**
- Audio: that a muted track is silent rests on the stock flag path above
  (**PROVEN, code**), not on an observed voice count. **UNDETERMINED** in
  MAME; **deferred physical test**: mute a playing drum track on the bench.
- Notes already sounding at the mute are not cut (stock `<Tk on/off>`
  behaviour, **HYPOTHESIS**).
- Song-mode playback (`[86DA]` set) is not offered from the page: entry leaves
  song mode first.
