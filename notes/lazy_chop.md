# Lazy Chop for PMONEY (OS 3.16 + cave): implementation specification

Status: specification, 2026-10-17; owner decisions D1–D10 settled the same day (§12). Implemented 2026-10-18: §13 (as built, evidence, deviations). Facts are from a mapping
of commit `0ae678e` (static bytes plus two MAME traces, `default` set,
L=6900); every address below is 3.16 relative `seg:off` with image offset
`seg*16+off` unless marked otherwise. Evidence tags follow `AGENTS.md`.
Precedent: the MPC2000XL Lazy Chop spec
(`~/Documents/2kxl/lazy_chop/design/feature_spec_v1.md`); terminology and
owner decisions carried over are marked **(XL)**.

## 1. Purpose

Turn one loaded Sound into playable slices by tapping pads in time with it,
refine the slices by ear on the pads, and convert them to Sounds on a new
drum program in one step.

Owner workflow (2026-10-17):

1. Load a Sound and open the waveform editor (Program/Sounds 6, Edit Sound,
   Help: PMONEY's waveform view).
2. Play and tap. The first pad hit starts the Sound playing; each later pad
   hit drops a chop point at that moment in the audio.
3. Refine the start and end of individual slices so they do not clip or cut
   off awkwardly.
4. Convert: the slices become Sounds assigned to a new drum program, ready
   to play or sequence.

Owner rules (2026-10-17):

- **R1 Pads play slices.** Individual chops/zones are played from the pads.
- **R2 Parity.** The same pad playback is shared by Lazy Chop and the
  existing zone workflow (Equal Division zones and CHOP ZONE).
- **R3 Banks.** Zones beyond 16 go to the next pad bank: pad n of bank b
  plays zone (b−1)·16+n. A 1–16, B 17–32, C 33–48, D 49–64.
- **R4 One universal build** (project rule): every part works on every EPROM
  set; budget against the universal cave room.

## 2. Terms

| Term | Meaning |
|---|---|
| Source | The Sound open in the waveform view |
| Take | One Lazy Chop pass: arm, play, taps, end |
| Chop point | A tap's position in the Source, in frames |
| Slice k | The k-th range, k = 1..N (N ≤ 64): `{start_k, end_k}` |
| Equal Division | Today's zone map: N contiguous zones from shared boundaries B[0..N] |
| CHOPS **(XL)** | A slice map with independent start/end per slice (gaps, overlaps allowed); what Lazy Chop produces |
| Slot | Pad index 0..63 = bank·16 + pad−1 (stock `[D399]`) |
| Pad ownership | While owned, a pad hit drives the view instead of playing its program note |

## 3. User interface

All screens are inside the waveform view; text is PMONEY's own wording
(project rule). Soft keys keep the view's layout; the exact row-7 strings are
in §3.5.

### 3.1 Modes of the view

| View mode | Pads | Entered by | Left by |
|---|---|---|---|
| Normal (today) | not owned: stock behaviour | opening the view | — |
| **Zones** | owned: pad → zone (R1–R3) | any view with a zone map (Equal Division or CHOPS) | Exit/Help, Main Screen, or a mode key |
| **Armed** | owned: first hit starts the take | Lazy Chop soft key | Cancel, or first hit |
| **Recording** | owned: hits drop chop points | first hit | end of Source, Stop key, Soft Key "Done", 64 slices |
| Refine | = Zones on the new CHOPS map | end of take | as Zones |

Owner decision **D1 (yes)**: pads are owned in Zones mode
whenever the view shows a zone map, so the existing zone workflow auditions
from the pads exactly as Lazy Chop does (R2). Without a map the view leaves
the pads stock.

### 3.2 Take

1. **Arm.** Soft key `<Lazy chop>` from the view. Row 7: `Hit a pad to start
   <Cancel>`. Nothing plays. Any existing zone map stays until the first hit
   (Cancel keeps it).
2. **First hit** (any pad, any bank): starts playback of the whole Source from
   frame 0 (owner decision **D2**: frame 0, so slice 1 includes any pickup) and creates
   chop point 1 = 0. The previous zone map is discarded.
3. **Later hits:** each adds chop point k at the audio position of the hit
   (§5). Pad identity does not matter during the take: chops are numbered in
   time order (owner decision **D3**; the XL's "pad number is
   the Level" rule is not used because the 3000 workflow converts slices to
   pads in order). Hits closer than 441 frames (10 ms) to the previous chop
   are ignored (minimum slice, same as CHOP).
4. **End:** the take ends when playback reaches the Source end, on STOP, on
   Soft Key `<Done>`, or at 64 chops. Cancel (`<Cancel>`, or a mode key)
   aborts: the previous map is restored.
5. **Result:** a CHOPS map: slice k = `{chop_k, chop_{k+1}}`, the last slice
   ends at the Source end. The view enters Refine with slice 1 selected.

During Recording row 7 shows `Chops: nn  <Done> <Cancel>`; the waveform shows
a marker at each chop as it lands (redraw coalesced: at most one redraw per
key-queue drain, marks are never lost because they are buffered in the cave,
§6.2).

### 3.3 Refine (and Zones)

- **Pads play slices** (R1–R3): pad n of the current bank plays slice/zone
  (bank·16)+n once, start to end, full level. A pad with no slice is silent.
- **Selection follows the pad:** a pad hit also selects that slice for
  editing (XL: "pressing a marked pad selects and auditions that Level").
- **Edit:** the selected slice's Start and End are the view's two markers;
  wheel, +/−, numeric entry and the fine view work as today. In CHOPS, moving
  one slice's start or end changes **only that slice** **(XL)**; Equal
  Division keeps linked boundaries (today's behaviour). Every slice must stay
  `start < end`, inside the Source, ≥ 441 frames; an edit that would break it
  is refused and the previous value kept.
- **Snap** (owner decision **D4**: on, toggle on a soft key):
  a committed start snaps to the nearest zero crossing within ±2 ms.
- **Audition retrigger** (owner decision **D5**: **mono**): a new
  pad hit stops the previous slice audition first (one voice), as the XL made
  slices cut each other.
- **Bank** keys work as stock while the view is open (`[D38F]` steps 0/10h/
  20h/30h; PROVEN trace); the title shows the bank letter.
- **Zone count** for Equal Division can now go to 64; the default division
  stays 16 (§6.3).

### 3.4 Convert

Soft key `<To program>` in Refine/Zones opens a confirm page:

```
============ Slices to Program ============
Slices: nn   Sound names: <src>nn
Program: nn-<name>            (field, 1..24)
Pads: A01..Dnn in slice order
Choke slices: ON/OFF          (mute group 1; default ON)
<Do it>                       <Cancel>
```

- **Sounds:** one new Sound per slice, exact frames per channel (CHOP's
  existing engine: validation, allocation, copy, rollback). Names: the
  Source's first 13 characters + 2-digit slice number (owner decision **D6**;
  CHOP's `ZONEnnn` is the fallback when a name exists).
- **Program:** the user picks the destination (default: the first program
  after the current one whose 64 note records are all empty; else the
  current + 1). A program that is not empty asks `Replace program nn?` first.
  It is initialised with the stock "Initialize a program" path (through the
  existing `mute_program_init_hook`), named after the Source, then slice k is
  assigned to slot k−1's note, in bank order (A01..A16, B01.. — R3). Notes
  outside 35..98 or already used are skipped and reported.
- **Choke** (owner decision **D7**: ON by default): every slice pad goes in
  mute group 1 (PMONEY mute groups), so slices cut each other; the user can
  switch it OFF on the confirm page.
- The new program is selected. The Source and its map are unchanged.
- Failure (not enough sound records or memory, a slice < 441 frames): one
  message, nothing created (CHOP's rollback).

### 3.5 Strings (PMONEY wording, ≤ 40 columns)

`<Lazy chop>`, `Hit a pad to start  <Cancel>`, `Chops: %2d  <Done> <Cancel>`,
`<To program>`, `Slices to Program`, `Replace program %2d?`, `Choke slices:`,
`Bank %c`, `Too many slices (64)`, `Slice too short`.

## 4. Pad ownership (shared by Zones and Lazy Chop)

### 4.1 Facts (PROVEN unless marked)

- Panel pad bytes arrive in the serial ISR `2B6D:006B`; the panel parser
  (`2B6D:0109`, Vailixi `D547:0105`) resolves slot `[D399]` = bank `[D38F]` +
  pad, note `[7019]` = `301D:000A(slot)`, velocity `[701A]` (7Fh with FULL
  LEVEL), and queues 4 bytes into ring 5 (`RING_SEG:06AC`) at `2B6D:022E`;
  a release queues 3 bytes at `2B6D:04A5`. No task wake.
- At the next sequencer tick task 2 reads ring 5 (`3045:000B`), calls the pad
  handler `3258:0001`, which (a) calls the UI callback `2CFF:000C` → key 'D'
  into `KEY_QUEUE`, `[D39A]` = note, then (b) queues the note-on
  (`20DA:000E`). The stock voice keys on about 0.37 ms **before** the view
  sees 'D' (trace). The view today ignores 'D'.
- Latency frame→view: 1.5–6.5 ms at 120 BPM, up to ~22 ms at 30 BPM (tick
  wait). MIDI drum notes also produce 'N' and 'D'.
- Pad Bank in the view: key 'd' (5Ch) handled by the global filter
  (`3481:063E`), view stays open (PROVEN trace).

### 4.2 Hook

ISR-level capture, the only way to keep the stock note silent and avoid the
tick wait:

```
--patch=2b8fe:bbac068a0e1870:ea{pad_own_press}9090      ; rejoin 2B6D:0235, owned exit 2B6D:0255
--patch=2bb75:bbac068a0e1870:ea{pad_own_release}9090    ; rejoin 2B6D:04AC, owned exit 2B6D:04C3
```

(7 bytes `BB AC 06 8A 0E 18 70` at each site; no relocations; the only two
occurrences; no current patch overlaps — PROVEN.)

`pad_own_press` (IF=0, ISR stack, DS=DGROUP):
- If not owned — `[pad_owned]`=0 **or** `[MODE]`≠'L' **or** `[OPTION]`≠6
  (belt and braces: a stuck flag can never silence pads outside the view) —
  run the replaced bytes and rejoin.
- Else: timestamp (§5.1), push `{t, slot, velocity}` into a 16-entry cave
  ring; queue key 'D' with `3033:000E` (as the ISR already does at
  `2B6D:0474`); skip the ring-5 queue (owned exit). Ring full → drop the hit
  (counted).

`pad_own_release`: owned → skip only releases of slots captured while owned
(a release of a pad pressed before arming must reach stock, or the held-pad
count `[9447]` goes stale).

MIDI drum notes are **not** owned in v1 (owner decision **D8**):
they still play their program note; the view ignores their 'D'/'N'.

The view drains the cave ring on every 'D' (and on every redraw), so no hit
is lost when the 8-key queue is full during a redraw.

## 5. Timing

### 5.1 Clock

`2B50:0194` (Vailixi `D52A:0190`): TCT0 timestamp in 0.5 µs units, PUSHF/CLI,
latches counter 0, base advanced by the 100 Hz ISR; DX:AX = absolute time;
wraps after 35.8 min; the only reader of `C030h` in the image. PROVEN.
Calling it from the panel ISR is **HYPOTHESIS** until the MAME wrap test
(§9 A7). Fallback: read the TCT0 latch inline.

One frame at 44.1 kHz = 45.35 counts. Rejected sources: the 100 Hz count
(441 frames), TCT1 (tempo), DSP voice read-back (UNDETERMINED on hardware,
needs resource 1), TCT2 (TCLK UNDETERMINED).

### 5.2 Position of a hit

```
t0  = timestamp right after the playback key-on (CE9 return)
pos = Δ·441/20000 frames,  Δ = t_hit − t0 − K   (q,r split: q·441 + (r·441+10000) div 20000)
```

`K` = latency constant: panel scan + link (0.96–1.0 ms MAME) + key-on→audio
(UNDETERMINED) + user offset. Default `K` = 0 in MAME builds, **owner
decision D9** for hardware after the bench (H-LC1). A user offset field
(−20..+20 ms, default 0) is on the Lazy Chop soft page.

Tune ≠ 0 changes the playback rate (HYPOTHESIS, layer reads sound
+11..+13): v1 plays the take at the sound's own tune and scales Δ by the
rate (2^(tune/1200) table); simplest acceptable v1: force tune 0 for the
take (owner decision **D10**: tune 0).

## 6. Data

### 6.1 Slice map

| Field | Size | Notes |
|---|---|---|
| mode | 1 B | 0 Equal Division, 1 CHOPS |
| count N | 1 B | 1..64 |
| B[0..64] | 65 × 4 B | Equal Division boundaries (today 17 × 4) |
| pair[1..64] | 64 × 8 B | CHOPS `{start,end}` |
| source identity | 25 B | today's `zones_source` + identity |

RAM only, in the cave (as zones today): cleared by a fresh Edit Sound entry,
a sound-field commit, a stock Do, or deleting the Source; kept across the
view's Exit/Help re-entry. **Not saved** (v1 exclusion, §8); after Convert the
result persists as ordinary SND/PGM files.

### 6.2 Cave state

`pad_owned` (byte), ring 16 × 8 B, take state (phase, t0, chop count, user
offset), last audition channel(s), bank shown.

### 6.3 Zone table to 64

`zones_bounds` 68 → 260 B; `chop_created` 64 B (still inside `cave_pool`,
988 B); decouple the default division count (16) from `ZONE_MAX` (64) in
`zones_enter`. The title `ZONE:nn/nn` already has two digits.

## 7. Playback

- **One audition entry** for both workflows (R2): `play_range(start, end)`:
  BUSY++, swap record +14/+18 to the range, `FCALL T_CFC6_0CE9`, restore,
  return through `audition.return_from_stock` (so `audition_duration`/
  `audition_ticks` treat it as an audition). **Non-toggle** (today's
  `audition` stops all voices if any is active; pad playback must not).
- **Stop** (mono, D5): stop only the previous audition channel(s): captured
  in `mute_voice_alloc_wrapper` (owner 62h, still active), stopped with
  `T_D21F_0008`. Never the global stop `T_CFC6_0D93` (it also kills
  sequence voices).
- **Take playback:** `play_range(0, len)`; t0 timestamped after it returns.
- Level: full (CE9 plays 7Fh). Velocity-sensitive audition is v2.

## 8. Exclusions (v1)

- No persistence of zone/CHOPS maps in SND/PGM (the XL's SND trailer is a v2
  candidate).
- No MIDI-note ownership, no recording of the take into a sequence.
- No pad-number identity of slices during the take (time order only).
- No velocity-sensitive slice audition.
- Lazy Chop on a sound being recorded (the XL's SAMPLE path) is not part of
  this feature: the 3000 workflow starts from a loaded Sound.

## 9. Acceptance (MAME, all four BIOS sets; harness `emu.panel.pad_hit` on the 1 ms SMF grid)

| # | Check |
|---|---|
| A1 | Arm, first hit starts playback (one DSP key-on), creates chop 1 = 0; no stock note-on (`20DA:000E` not executed, no ring-5 enqueue) while owned |
| A2 | Hits at known SMF times give chops equal to (t_isr − t0 − K)·44.1 within ±1 frame; identical at 30, 120 and 300 BPM |
| A3 | A 20-hit roll: every hit recorded (ring + coalesced redraw), N=21 |
| A4 | End at source end / STOP / Done / 64; Cancel restores the previous map |
| A5 | Refine: pad n bank A plays slice n (key-on wave base = source base + start_n); bank B pad 1 plays slice 17; empty pad silent; mono retrigger stops the previous channel only (a running sequence voice survives) |
| A6 | CHOPS edit of slice 3 leaves slices 2 and 4 unchanged; invalid edits refused |
| A7 | Hits at the TCT0 wrap and near the 100 Hz tick give monotonic, correct positions |
| A8 | Equal Division zones: pads play zones with the same code path (parity), 64 zones over banks A–D |
| A9 | Convert: N new Sounds bit-exact per channel; program initialised, named; note records +0 = new indices in slot order; program selected; pads key on the slice bases; choke ON (the default) sets group 1, OFF leaves the pads ungrouped; replace prompt on a non-empty program; memory-full and short-slice refusals create nothing |
| A10 | Ownership ends on every exit (Exit, Help, Main Screen, mode keys, error box): pads play program notes again; a pad held across arming releases normally |
| A11 | PGM save/load round trip of the new program; release gate, soak smoke |

## 10. Hardware (deferred, named)

H-LC1 pad contact → link → audio latency (sets K; U-PANEL-ROM); H-LC2 DSP
44.1 kHz vs TCT0 drift over 10 s; H-LC3 key-on → analog onset; H5 LC7981
timing (redraws during takes).

## 11. Size and order

| Part | Estimate |
|---|---:|
| ISR ownership hooks + ring | ~350 B |
| View phases, markers, strings | 1.0–1.5 KB |
| Time conversion | ~150 B |
| `play_range` + targeted stop | ~250 B |
| Zone table to 64 + CHOPS pairs | +192 B (+512 B) data, ~400 B code |
| Convert page | 0.7–1.0 KB |
| Snap | ~200 B |
| **Total** | **≈3.2–4.5 KB** |

Requires the universal layout (≈32 KB cave room); does not fit the current
3,436-byte limit.

Build order: (1) shared pad ownership + `play_range` + 64-zone table, with
Zones mode on today's Equal Division (R2 parity, small, testable alone);
(2) the take (arm/record/timing); (3) CHOPS refine; (4) Convert.

## 12. Owner decisions (settled 2026-10-17)

The owner accepted every recommendation except D7, which defaults to ON.

| # | Question | Decision |
|---|---|---|
| D1 | Pads owned in the view whenever a zone map exists | Yes |
| D2 | Playback/chop 1 starts at frame 0 or Soft start | Frame 0 |
| D3 | Chops numbered in time order, pad identity ignored during the take | Yes |
| D4 | Snap to zero crossing on commit | On, toggle |
| D5 | Pad audition retrigger | Mono |
| D6 | Slice sound names | Source name + 2 digits |
| D7 | Choke slices by default on Convert | **On** (mute group 1) |
| D8 | MIDI drum notes owned in the view | No (v1) |
| D9 | Hardware latency constant K | Set from bench H-LC1 |
| D10 | Take at tune 0 | Yes |

## 13. Implementation (as built, 2026-10-18)

Sources: `mods/lazychop316.inc` (new; ownership hooks, ring, time, the take,
CHOPS edits, snap, drawing, Convert), `mods/wave_zones.inc` (pair table, 64
zones), `mods/wave_playback.inc` (`aud_range`), `mods/wave_chop.inc` (engine on
the pair table, D6 names), `mods/mute_voice.inc` (capture), `mods/wave.asm` and
`mods/wave_numeric.inc` (view hooks), `mods/profile_316.inc` (targets),
`mods/WAVE316.args` (three hooks: press, pressure, release). Everything is under `PROFILE_316`: the Vailixi
builds are byte-identical (`tests/test_build_mod_sys.py`). Tests:
`emu/test_lazychop.py` (42 MAME tests, 41 cases, all four BIOS sets) with
`emu/lua/lazychop316.lua`, and `tests/test_lazychop316.py` (no MAME). Addresses
are 3.16 relative `seg:off`, image offset `seg*16+off`, physical
`0x300000 + 0x69000 +` image offset (third PGR, XA on, no `BRKXA`; runtime
L = 6900 on every set).

### 13.1 Phase 1: shared pad ownership, `play_range`, 64 zones

| Item | As built | Tag |
|---|---|---|
| Press hook | `2B6D:022E` (img `0x2B8FE`, `BB AC 06 8A 0E 18 70`) `JMPF pad_own_press`; not owned: the 7 replaced bytes, rejoin `2B6D:0235` (T_D547_0231). Owned (`lc_owned` and `[MODE]`='L' and `[OPTION]`=6): `FCALL 2B50:0194` (T_D52A_0190) from the ISR, ring entry `{time, slot [701C]+[D38F] (the parser's own bytes; `[D399]` is also written by the MIDI note handler `307E:0093`), velocity [701A]}`, key 'D' by `3033:000E` (T_DA09_0000), exit `2B6D:0255` (T_D547_0251) without ring 5 | PROVEN (bytes; MAME all sets; x86sub differential) |
| Pressure hook | `2B6D:02CC` (img `0x2B99C`, `88 87 48 95 BB 21 01`) `JMPF pad_own_pressure`: the held-table store `[9548+note]` is skipped for a pad captured while owned; rejoin `2B6D:02D3` (T_D547_02CF) | PROVEN (bytes; x86sub; MAME "zones") |
| Release hook | `2B6D:04A5` (img `0x2BB75`, same 7 bytes) `JMPF pad_own_release`: a raw pad (`[701C]`, bank-independent) captured on an owned press is skipped (`2B6D:04C3`, T_D547_04CD), any other release is stock (`2B6D:04AC`, T_D547_04B6). `2B6D:04A5` has one entry, the pad release at `2B6D:01A2` (state `025B`, the other `JMP 04A5`, has no writer of `[7016]`: only `2B6D:04C6` writes it) | PROVEN (bytes) |
| Ring | 16 × 8 bytes in the cave, ISR producer / view consumer, an entry published before the tail moves; full: hit dropped and counted (`lc_dropped`), its press still captured | PROVEN (x86sub) |
| Ownership | `lc_owned` = `zones_valid` at view entry (D1), 0 at the view's one exit (`lc_leave`: Exit, Help, Main Screen, any mode key), while a Convert message waits for its key, and while a stock `BDE3:000E` error box is up (`[9331]` and `[A44F]` set: `lc_box`, owned again at the next key if the view is still open) | PROVEN (MAME, A10, "errbox") |
| `aud_range` | the one `CFC6:0CE9` call site (`aud_range.return_from_stock` = `audition_callsite`'s chain); Ply/Stp (`audition`), pads and the take use it; non-toggle; `lc_tune0` plays at Tune 0 | PROVEN (MAME: an `AUD` per key-on) |
| Mono stop | `lc_alloc_seen`, called from `mute_voice_alloc_wrapper` after each allocation only while `lc_owned` or `lc_aud_n` ≠ 0 (both 0 once the view closes), lists channels whose chain is `0B2D ← 039E ← 0CE9 ← aud_range` and drops a listed channel any other caller allocates; `lc_stop_auditions` stops each with `234D:0000` (T_D21F_0008) if its owner is still 62h and it has no mute tag | PROVEN (MAME: "zones", "midi") |
| Zones | 65 `{start, end}` pairs + a guard dword (`zones_pairs`, 524 B); Equal Division writes the linked neighbour end on every edit; count 1..64, default 16; pad n of bank b plays zone (b−1)·16+n | PROVEN (MAME, A8) |

### 13.2 Phase 2: the take

`<Lazy chop>` arms (full view forced); `+`/`−` set the user offset (−20..+20
ms, row 49 "Offset:+00ms"). First ring entry: mono stop, `aud_range(0, len)` at
Tune 0, `t0` = the TCT0 time right after `0CE9` returns, read in the task by `lc_time` (base `[D501]` + 20000 − counter 0 under CLI, again if the base moved; the ICU is not touched: `2B50:0194`'s IR0-only STI window, taken from a task, can reschedule with the mask left at FEh — review finding, MAME trace), chop 1 = 0. Later
entries: `lc_pos`, a chop unless under `LC_MIN` (1,368) frames after the previous one or
within `LC_MIN` of the Source end (§13.5 item 13). End: Source end (the 100 Hz tick count `[D38C]` passes `ceil(len/441) + ceil(offset/10 ms) + 1` ticks after t0; no timestamp is taken in the task), STOP (`[A49F]`, the
panel's STOP-held flag, Vailixi `A7B2`), `<Done>` (Soft Key 3), 64 chops
(row 49 "Too many slices (64)" until the next key). After a take ends by itself (Source end, 64), Soft Key 3 is ignored for 0.5 s (a late `<Done>` is not `<To program>`). Cancel: Soft Key 4, Help
or a mode key; the chops live in `lc_chops` until the end commits them, so the
previous map was never touched.

Keys (`lc_poll`, every phase; `lc_key` for the Convert page, its Replace prompt
and a message).  The view never waits inside `BDE3:000E`: its loop
(`0F6B:00A6..00D3`, img `0xF756..0xF783`) keeps reading while the global filter
`3481:000E` returns 0 (Pad Bank, COUNT IN, STOP's event, the kick 'P' in Edit
Sound: `3481:01C8`), so the bank shown would go stale and its error-box check
(`[9331]` and `[A44F]`, `0F6B:00A6`) would open the box with the pads owned
(second review B1, MAME).  Every queued key but `+`/`−` is taken without waiting
(`2D0B:0002` T_D6E0_0000, `[D387]` = 1) and passed through the filter
(T_DE5C_000E); the kick `[D398]` (Vailixi `D6AB`, 'P', set by the tick ISR and by
the MIDI-in overflow writer img `0x2C3CB..0x2C3D8`) is taken as `D6E0:001B`
(img `0x2D0CD`) takes it — read and cleared with interrupts off — and filtered
too; a filter result of 0 loops back to the bank and box checks.  `+`/`−` are
coalesced in the cave as `D6E0:001B` coalesces them (`2D0B:00F3..010D`: the
copies of the key at the head of the queue, taken with interrupts off, counted
into `[D387]`; third review #6: the wheel moves as before, "burst"), so
`BDE3:000E` is entered only, outside a take, for the error box, with the pads stock (`lc_box` / `lc_cv_boxed`; owned again at the next
key, the Convert page drawn again).  A poll that never took the kick stopped all
panel and MIDI input under a MIDI note stream (first review round, "d399race",
3.08 and Vailixi: 134 of 200 hits).  PROVEN (MAME, all sets: "d399race",
"kickbank", "kickbox", "cvbox").

Time: `pos = q·441 + (r·441+10000) div 20000`, `(q, r) = divmod(t − t0 − K,
20000)` mod 2³², K = offset·2000 + `LC_K_LAT` (0, D9). PROVEN (x86sub against
the formula, wrap included).

### 13.3 Phase 3: CHOPS refine

At the end of a take the map becomes CHOPS (`zones_mode` 1), slice 1 selected,
title "CHOP:nn/nn", ticks at slice starts. Pads play and select slices.
Moving a CHOPS start or end writes only that slice; an edit outside
`[0, end−LC_MIN]` / `[start+LC_MIN, len]` is refused (the step is not applied);
`zones_import` refuses a stock-page edit that leaves a slice under `LC_MIN`; the
count field offers "Equal zones again? Enter: yes" in CHOPS (any other key
keeps the chops). Snap (D4, Soft Key 2 on the ZONE fields, default
ON): each chop after the first at the end of a take, a CHOPS start or end
committed by numeric entry, and a point stepped with the wheel or +/- when its
field is left (any key but `+`/`−`, a pad's 'D' or a MIDI note's 'N'), before
Convert and when the view closes, move to the nearest zero crossing (sample 0, or a
sign change from the previous sample) within ±88 frames, `p = s+d` before
`s−d`, keeping both slices ≥ `LC_MIN`; plane L for a stereo Source.  Only the
point the user moved snaps (`lc_edit_point`, `sel` bit 0), and never a start at
frame 0 or an end at the Source end (D2). PROVEN (MAME,
A6, "roll", "numeric", "settle0"; x86sub for the search and the D2 guard).

### 13.4 Phase 4: Convert

Soft Key 3 `<To program>` on the ZONE fields opens "Slices to Program" (drawn in
the view's graphics): Slices/Names, Program nn-name (wheel, +/−, two digits),
"Pads: A01-Xnn in slice order", "Choke slices:ON (mute group 1)",
"ENTER:Do it".  `<Do it>` is ENTER, a key that never opens the page (Soft Key 3
opens it, Soft Key 1 is `<Lazy chop>` / `<Ply/Stp>`): queued soft keys and ENTER
are dropped when the page is drawn, and ENTER counts only 0.25 s after the page
and after the previous key (a mashed burst never reaches it; a pad's 'D', a MIDI
note's 'N' and the kick 'P' do not restart that guard); every slice must
be at least `LC_MIN` frames, else "Slice nn too short" (the first such slice)
and nothing is made; with the transport running and the Edit Sound lock on (`[A49B]`≠0,
`[831D]`=0) it says "Stop the sequencer first" and makes nothing; a program
with any note record naming a Sound asks "Replace program nn?" (`<Replace>` is
Soft Key 2; any other key says "Program kept: nn"). Then:
`chop_create_all` with BP = the suspended Edit Sound page (validation,
allocation, exact copy per plane, rollback on any failure), names D6
(`<source ≤13 chars>nn`; if a Sound in memory or a `.SND` file of the selected
disk has the name, `nn` + 100, + 200 … with the name cut to keep 16 characters —
never ZONEnnn; the disk is read once per Convert with the stock find first /
next `200D:017B` / `01E7` (INT 41 fn 9) on the floppy or the selected SCSI
partition, numbers under 1000; find first's "no file" result `FD00h` (an empty
partition; also the end of every list) is a checked disk, any other failure
(no floppy: `FF80h`, MAME) leaves the names unique in memory only and the
success message ends "(disk not checked)"); the program through
`mute_program_init_hook` → `207C:02D9`, named after the Source (with 2 digits
if another program has that name); selected
(`19F9:1BF3`); slice k → note `301D:000A(k−1)` of the new program (35..98,
first use; others counted and reported "Pads skipped:nn (note)"); choke: mute
group 1 on each assigned slot, those notes MONO (`+6` = 1, the owner's default
after review, as on the XL: a repeated pad cuts itself) and the program's mute
groups enabled.  Success shows "nn sounds, program nn" on row 49. Records:
`302F:0029` (T_DA04_002B). Refusals ("Slice too short", "Not enough sound
memory", "Not enough sound records") show on row 40 with the pads stock until
a key; a mode key acknowledging one leaves the view with it. PROVEN (MAME, A9, A11 save to floppy and reload on a fresh machine).

### 13.5 Deviations from the specification

1. The "Lazy Chop soft page" is the ZONE fields' focus (Right, Right from the
   view's start point): `<Lazy chop> <Snap ON><To program> <Exit>`. Soft keys
   elsewhere are unchanged.
2. The bank letter is on row 49 ("Bank A", column 26): the title row has no
   room (16-character name and the ZONE field). Armed and Recording rows use the
   spec's words at the soft-key columns: `Hit a pad to start` … `<Cancel>`
   (Soft Key 4), `Chops: nn` … `<Done>` (Soft Key 3) `<Cancel>`.
3. Releases are matched by raw pad (0..15), not by slot, and the captured bit
   is honoured even after ownership ended (a press kept from stock never sends a
   release to stock).
4. A hit within `LC_MIN` frames of the Source end is ignored (every slice ≥ `LC_MIN`).
5. Snap applies on a take's end, on a numeric commit, and to a slice moved with
   the wheel or +/- when its field is left, before Convert and when the view
   closes, never per wheel step (a snap per step would hold the start on one
   crossing).
6. A pad on a slice or zone under `LC_MIN` frames does not audition; row 49 says
   "Slice too short" instead (Ply/Stp keeps the view's own rule, two 10 ms
   player ticks, and the stock "Too short" soft key).
7. The previous map is kept until the take ends (not discarded at the first
   hit); the outcome is the spec's.
8. Default destination: the first empty program after the current one,
   searching all 24 circularly; else current + 1 (wrapping).
9. Skipped pads leave their slice's Sound unassigned.
10. The user offset is set while Armed only (it applies to the next take); the
    CHOPS refine page has no offset (the chops are already positions).
11. Slice names are unique against the Sounds in memory and the `.SND` files of
    the selected disk (numbers under 1000; second review B7: "Replace same
    sounds on disk: NO" kept an older file of the same name and a reload played
    it).  A disk that is changed between Convert and the save is not re-read; a
    directory that cannot be read leaves memory-only uniqueness and says so.
12. Existing suites follow the new behaviour: `test_mute_audition`'s "wave"
    case plays its two notes from MIDI In 1 on 3.16 (pads are owned in the
    view, D1);
    `test_wave_zones` expects the 64-zone maximum on 3.16; the 3.16 wave-view
    pixel references (`emu/wave_ref.py` `View.bank`) include "Bank A" and the
    zone-page soft keys; `emu/fixtures/display_tour316.json`'s two wave-view
    digests were re-recorded from the final build (review fixes included) with
    display316 removed (`emu/test_display316.py` docstring says how);
    `test_scsi316`'s overrun watch, whose window `[cave end, image 0x84000)` the
    larger home now covers, also flags any stack write inside the home.
13. The minimum slice is `LC_MIN` = 1,368 frames (31.0 ms), not the spec's 441
    (10 ms): stock 3.16 never keys on a shorter Sound (second review B2), so a
    shorter slice auditioned in the view and was silent after Convert.  The rule,
    PROVEN from the code (player `20ED:0697..06C0`, img `0x21567..0x21590`, the
    note-on duration path): `floor(10 · (end − start − skip) / 441) − 30 > 0`
    with the C runtime's unsigned long divide (`0009:20FD`), `skip` =
    `[6D5C + 2·((128 − velocity) · note[+15h] div 127)] · 441 div 10` frames (0 for
    the note records a new program has, `+15h` = 0), else `20ED:0B27` (no voice);
    `L ≥ 1368`.  It is length-only (Tune changes only the later tick count
    `[bp−58h]`, which is raised to 1 when 0).  MAME confirms it on stock 3.16
    (`test_stock_minimum_length_rule`: 1,367 frames silent, 1,368 keyed on).  It
    applies to the take's gap and end margin, CHOPS edits and their refusals,
    `zones_import`, snap limits, a pad's audition (Equal Division zones too) and
    Convert, which refuses a map with a shorter slice ("Slice nn too short");
    on 3.16 also to CHOP ZONE and ZONE->NEW SOUND (`wave_chop.inc`
    `CHOP_MIN_FRAMES`, "ZONE MUST BE AT LEAST 31ms"; the Vailixi profiles keep
    441 and "10ms"; third review #7).
    Fast rolls lose hits closer than 31 ms (A3 at 12 ms: every third hit).

Stock hazard (recorded, not fixed): a 2 ms MIDI note stream on MIDI In 1 can stop
all serial input in MAME on the 3.11 BIOS set with stock 3.16 too (second review:
5 of 12 seeds on stock).  Dense-MIDI tests stay at ≥ 4 ms on v311 ("d399race"
uses 8 ms).  UNDETERMINED on hardware.

### 13.6 Size

Cave home 21,386 → 26,738 bytes with Lazy Chop (+5,352: code ≈ 4.4 KB, data
≈ 0.9 KB: pairs 524, chops 256, ring 128), → 28,132 with the review fixes
(+1,394), → 28,998 with the second review's (+866: key polling, the disk name
scan, its 125-byte bitmap and 28-byte find record). Free under the universal
page-61 limit 24,250 bytes; `HOME_HEADROOM` 31,000 → 26,000 → 25,000 → 24,000,
`HOME_BUDGET` 29,100 (`tests/test_build_wave316.py`). Relocated cave words
279 → 300 → 302 → 304 → 306 (unrelocated not-operand words 46); relocation table
7,683 bytes, 7,347 records.  Third review: 29,100 bytes (+102), 24,148 free.

### 13.7 Measured (MAME, release mode, all four BIOS sets, one execution each)

Release gate `python3 -m emu.harness_release` (final tree, all three reviews'
fixes included): 289 tests, 0 failures, 0 errors, 0 skips; `python3 -m unittest
discover -s tests`: 136 tests OK (282 and 135 after the second review, 271 and
132 after the first, 264 and 125 before it).


| Measure | Value |
|---|---|
| chop − (t_isr − t0 − K)·44.1 | −0.47 .. +0.59 frame (600 hits: 120/30/300 BPM, +5 ms offset, base wrap) |
| panel SMF → owned ISR timestamp | 0.994 .. 1.058 ms (link: 3 bytes ≈ 0.96 ms) at every tempo |
| first hit SMF → take key-on; ISR → t0 | 1.36 .. 1.58 ms; 0.37 .. 0.60 ms |
| pad in the view → audition key-on | 1.36 .. 1.46 ms (stock pad note-on outside the view: 4.6 .. 5.9 ms, tick wait) |
| TCT0 phases covered | hits every 0.32 ms of the 10 ms period, including ≤ 0.5 ms after a tick (`2B50:0194`'s STI window from the ISR: HYPOTHESIS of §5.1 now PROVEN in MAME) |
| note-on path, view closed | MIDI note-on (`note_wrapper_off`) 9,789 cycles (9,852 before), 16-pad chord last voice 20.79 ms (21.50); mapped note-ons never reach the capture branch. Pad ISR path: +2 `JMPF`, `CMP`, `Jcc` per press and +7 instructions per release (static) |
| cycle budgets moved | `view_zones` 317,270 → 332,496 (Lazy Chop soft keys + Bank), `free_cluster_search` 112,432 → 114,585 → 115,710 after the reviews (larger STARTUP.SYS; rule stock+6 % → +7 %); `emu/fixtures/cycle_budget_316.json` notes |

### 13.8 D1 in practice, and a residual risk

D1 (the view owns the pads while its zones are valid) means in practice that
the pads are always owned while the view is open: `zones_valid` is set for
every Sound the view can show (`zones_enter` keeps a matching map or builds
an Equal Division, so `zones_valid` is 1 on every entry: PROVEN, code), so a pad in the
view never reaches the stock note path; ownership ends only at the view's exit,
under a Convert message and under a stock error box (§13.1). A pad held on
entry keeps its stock release (captured bit, §13.5 item 3).

Residual risk (HYPOTHESIS, not observed): the cave home, image `0x7E000` ..
`0x851AC` (physical `0x3E7000` ..), now covers the whole range a wrapped UI
stack would hit, image `0x835D2`–`0x83E0F` (SS relative `73E1`, SP wrapping
below 0 to `F7xx`..`FFFF`).  The one known cause is stock 3.16's SCSI partition
reader `2AB2:04F7` (`SUB SP,100Eh`, entered with SP ≈ `07D2`).
`scsistack316` makes that cause safe: the reader runs on its own private
stack, and its fallback (busy or no private stack, both unreachable:
`tools/scsi_reader_reach.py`) runs the stock frame only when SP ≥
`SCSI_STK_BYTES` and otherwise returns the reader's error 4, so it refuses
rather than wraps (`tests/test_build_wave316.py` `test_scsi_wrapper_*`,
`emu.test_scsi316`'s stack-write watch over the home).  An unknown deep UI
path that wraps the stack would now overwrite cave code instead of free
memory; no such path is known.

### 13.9 Review fixes (2026-10-18)

Each with a regression test that fails on the pre-review tree (x86sub tests
there error or fail; the MAME cases were also run there: all 25 fail, several
because the keys moved, so the reviewers' repros in `review_code/` and
`review_behave/` are the other half of the before-evidence) and passes on all
four BIOS sets.

| # | Change | Test |
|---|---|---|
| 1 | `chop_name_slice` rewritten: the prefix length is `min(len, 15 − digits)`, the pad starts after the digits (BX was 10 after `digits`), spaces to 16, NUL | `tests/test_lazychop316.py` `test_slice_names_every_length` (lengths 1..16, trailing spaces, after a longer name) |
| 2 | Slice names `<source>nn`, unique against the Sounds in memory: `nn`, `nn`+100, … with 2..5 digits and the prefix cut to fit 16; never ZONEnnn. The program is named after the Source, with 2 digits if taken | `test_slice_names_unique_in_memory`; MAME `test_second_convert_round_trip` (two Converts, saved next to `ZONE000.SND`, reloaded on a fresh machine: pads play their own PCM) |
| 3 | `chop_make_name` (3.16) writes `ZONEnnn`, spaces to 16 and the NUL | `test_make_name_writes_its_template` |
| 4 | Convert with the transport running and the Edit Sound lock on says "Stop the sequencer first" and makes nothing | MAME `test_safe_lock_refuses_convert` |
| 5 | The ring slot is `[701C]` + `[D38F]` (the parser's own bytes), not `[D399]` | `test_owned_slot_ignores_d399`; MAME `test_slot_is_the_parser_s_under_midi_traffic` (200 hits under a MIDI note every 8 ms, 0 wrong slots) |
| 6 | No `2B50:0194` call from the task: `t0` by `lc_time` (CLI read of base and counter), the end by the tick count `[D38C]` | MAME `test_take_timing_*` (no `0194` entry on the UI stack; the take still ends) |
| 7 | `<Do it>` on Soft Key 3; queued soft keys dropped (`2D0B:008D` T_D6E0_008B) when the page is drawn and a press within 0.25 s ignored; Soft Key 3 ignored 0.5 s after a self-ended take | MAME `test_keystroke_traps_make_nothing` |
| 8 | Choke ON sets each slice note MONO (`+6` = 1) | MAME `test_convert_defaults` (poly list), `test_replace_prompt_choke_off_stereo` (choke OFF stays POLY) |
| 9 | The bank shown follows `[D38F]` (poll redraw) | MAME `test_zones_pads_banks_and_held_pad` ("Bank B" pixels after Pad Bank alone) |
| 10 | `lc_flush` at the end of `lc_cv_run` (pads hit while making are dropped) | MAME `test_convert_defaults` (no audition during and after making) |
| 11 | `lc_message` returns its key: a mode key leaves the view; a stock `BDE3:000E` error box is shown with the pads stock and ownership comes back at the next key | MAME `test_mode_key_acknowledges_a_message_and_leaves`, `test_stock_error_box_releases_the_pads` |
| 12 | A pad on a slice under 20 ms says "Slice too short" on row 49 (until a key that is not a pad's, or a pad that plays; Ply/Stp keeps the stock "Too short" soft key) | MAME `test_roll_and_snap` |
| 13 | `lc_alloc_seen` drops a listed channel another caller allocates | `test_alloc_seen_drops_a_reused_channel`; MAME `test_midi_voice_survives_the_mono_stops` |
| 14 | New pressure hook `2B6D:02CC`: owned pad pressure skips `[9548+note]` | `test_owned_pressure_skips_the_held_table`; MAME "zones" (held table 0) |
| 15 | Snap of a wheel/+/- moved boundary when its field is left, before Convert and at view exit (`lc_settle`), not per step | MAME `test_snap_when_the_field_is_left_and_equal_zones_again` |
| 16 | "Program kept: nn" on any key but `<Replace>`; "nn sounds, program nn" on success; "Equal zones again? Enter: yes" from the CHOPS count field; offset documented as Armed-only (§13.5 item 10); "Chop:>>" hint on row 49; "Lost:nn" while recording | MAME `test_replace_prompt_choke_off_stereo`, `test_convert_defaults`, `test_snap_when_the_field_is_left_and_equal_zones_again`; `emu/wave_ref.py` pixel references (`test_wave_zones`, `test_wave_physical`) and the display tour; `test_recording_row_shows_lost_hits` |
| 17 | `test_mute_audition`'s 3.16 "wave" case plays notes 0x23/0x24 from MIDI In 1; display-tour wave-view digests re-recorded from the final build with display316 removed (`emu/test_display316.py` docstring) | `emu.test_mute_audition`, `emu.test_display316` |

Found while fixing: the poll that follows Pad Bank (#9) must hand the stock
kick key `[D398]` to `BDE3:000E` (§13.2); without it MIDI and panel input
stopped under the 8 ms note stream of #5's test.

### 13.10 Second review fixes (2026-10-18)

Each with a regression test that fails on the first-review tree (the second
reviewer's `review2/tree`; x86sub tests there error, the MAME cases fail as
noted) and passes on all four BIOS sets.

| # | Change | Test (fails before: why) |
|---|---|---|
| B1 | The view never waits inside `BDE3:000E` (§13.2): every queued key but `+`/`−` and the kick are taken by `lc_take_key` / `lc_read_key` and filtered, 0 loops back to the bank and box checks; `BDE3:000E` only for `+`/`−` and the error box (pads stock); the Convert page, Replace prompt and messages wait the same way (`lc_key`, the page drawn again after a box) | MAME `test_bank_follows_after_filtered_keys_and_kicks` (before: "Bank B" not drawn), `test_stock_box_after_a_kick_has_the_pads_stock` (before: box up with the pads owned), `test_stock_box_on_the_convert_page_has_the_pads_stock` (before: owned) |
| B2 | `LC_MIN` = 1,368, stock's keyable minimum (§13.5 item 13): take gap and end margin, CHOPS edits, `zones_import`, snap limits, a pad's audition (Equal Division zones too: "Slice too short"), Convert ("Slice nn too short", nothing made) | MAME `test_short_gaps_are_no_chops_and_every_slice_plays` (before: 5 slices, 529..1,147-frame ones silent after Convert), `test_short_equal_zones_say_so_and_convert_refuses` (before: no refusal); evidence `test_stock_minimum_length_rule` (stock 3.16: 1,367 silent, 1,368 keyed on; passes on both trees) |
| B3 | `<Do it>` is ENTER ("ENTER:Do it"); queued soft keys and ENTER dropped when the page is drawn; ENTER counts only 0.25 s after the page and the previous key | MAME `test_do_it_is_enter_and_soft_key_3_never_makes` (before: mashed Soft Key 3 made MASH01..03) |
| B4 | `lc_after_move` records the point (`sel` bit 0); `lc_settle` snaps only it, never a start at 0 or an end at the Source end; pad 'D' and MIDI 'N' keys do not settle | MAME `test_settle_snaps_only_the_moved_point` (before: slice 1's start 0 → 1); x86sub `test_settle_keeps_frame_0_and_the_source_end` |
| B5 | `lc_dropped` = 0 when a take is armed and when it starts | MAME `test_lost_counts_only_this_take` (before: the reviewer's "lost2", Lost:05 on the next take; the test's ENTER makes nothing on the old tree) |
| B6 | A key that closes "Equal zones again?" takes it off row 49 (a pad: redrawn with its audition) | MAME `test_equal_zones_question_goes_with_a_pad` (before: the question stayed) |
| B7 | `lc_disk_scan`: the selected disk's `.SND` names of the Convert form mark their numbers (`lc_taken`, n < 1000); `chop_name_slice` skips them; "(disk not checked)" when the directory cannot be read | x86sub `test_disk_names_mark_the_convert_form`, `test_slice_name_skips_disk_names`; MAME `test_disk_name_collision` (older BREAKS01.SND kept, slice 1 BREAKS101, reload on a fresh machine with PMONEY and with stock 3.16: the pads play the new slices bit-exactly; before: the reviewer's "disk_collision", the reload played the old file) |

The stock reloads and `test_stock_minimum_length_rule` run stock M3K316.SYS where
its loader puts it (`test_lazychop.stock_of`: 7000h on 3.08 and 3.11).

### 13.11 Third review fixes (2026-10-18)

Fails before on the second-review tree (`review3/tree`), passes on all four sets.

| # | Change | Test (fails before: why) |
|---|---|---|
| 1 | `lc_disk_entry` matches the Convert form directly: for d = 2 and 3, p = min(length, 15 − d); a name of p + d characters whose first p are the Source's and last d are digits marks n (3 digits: n ≥ 100) — Source names ending in digits match | x86sub `test_disk_names_mark_the_convert_form` (LOOP1/LOOP101, KICK808/KICK80801, BEAT 1/BEAT 101, DRUMS90/DRUMS90101 marked nothing); MAME `test_digit_source_disk_name_collision` (slice 1 LOOP1101; reload with PMONEY and stock 3.16 bit-exact; before: LOOP101.SND kept, slice 1 named LOOP101) |
| 2 | `lc_cv_key` does not restart the 0.25 s guard for 'D', 'N', 'P' | MAME `test_midi_notes_do_not_hold_enter_off` (before: nothing made under a 100 ms MIDI note stream) |
| 3 | A key that closes "Equal zones again?" sets `lc_redraw`; `lc_poll` redraws before the next key | MAME `test_equal_zones_question_goes_with_any_key` (before: still drawn after '0') |
| 4 | `lc_after_move` snaps a still-stepped point of another slice or the other point before marking the new one | MAME `test_a_stepped_point_snaps_when_another_is_stepped` (before: slice 2's start never snapped) |
| 5 | `LC_FIND_NONE` = `FD00h` (find first / next "no file", MAME: an empty SCSI partition and the end of a floppy's list; no floppy `FF80h`) is a checked disk | MAME `test_empty_disk_is_a_checked_disk` ("cvscsi": no "(disk not checked)", before: shown; "cvnodisk": shown, the fallback) |
| 6 | No `BDE3:000E` for `+`/`−`: coalesced in `lc_take_key` (above); `BDE3:000E` is entered only for the error box, the pads stock first, so no flags can open it with the pads owned | x86sub `test_plus_minus_coalesced_without_bde3` (before: FFh, left for `BDE3:000E`); MAME `test_wheel_bursts_step_as_before` (5 steps 1 ms and 50 ms apart: 5 · 735 frames each, as before) |
| 7 | 3.16 CHOP ZONE / ZONE->NEW SOUND minimum = 1,368 (`CHOP_MIN_FRAMES`, `LC_MIN` is it), message "ZONE MUST BE AT LEAST 31ms"; Vailixi profiles unchanged (441, byte-identical builds) | MAME `emu.test_wave_chop` `test_zones_under_the_stock_playable_minimum_on_316` (1,000-frame zones: refused on 3.16, made on capture/generic; before: made on 3.16); `test_tiny_zones_…` expects the 31ms text on 3.16; `directory_full`'s source is 16 × 1,400 frames (was 8,192: 512-frame zones) |

Measurement note: `check_take`'s reference time for a hit is now its
timestamp call's entry (TS, `2B50:0194`, which reads the counter) instead of the
ISR's log after it: a tick ISR in `0194`'s STI window delayed one log by ~30 µs
on 3.08 at 300 BPM (−1.29 frames against the log, 0.67 against TS).

### 13.12 UNDETERMINED (hardware)

H-LC1 (panel contact → link → audio latency, sets `LC_K_LAT`), H-LC2 (DSP
44.1 kHz against TCT0 over a take), H-LC3 (key-on → analog onset), H5 (LC7981
timing of redraws during a take), the V53 ICU's handling of `2B50:0194`'s STI
window inside the serial ISR on hardware (MAME only), and the audible result of
mono stops and choke. None is observed; the MAME results above are one
execution per set.
