# Lazy Chop for PMONEY (OS 3.16 + cave): implementation specification

Status: specification, 2026-10-17; owner decisions D1–D10 settled the same day (§12). Not implemented. Facts are from a mapping
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
