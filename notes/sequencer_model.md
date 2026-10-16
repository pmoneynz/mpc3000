# MPC3000 sequencer model — implementation specification

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Cross-checked against:** stock 3.12 linear
`ad9974c9c541e14eae1740825edb23edf58c1f0c3a9f6868e62fcf8f6f9f7eb8`
(section 14).
**Date:** 2026-10-02.

This note is written for an agent who has to re-implement the MPC3000
sequencer on other hardware (Teensy 4.1, Raspberry Pi, Linux) and wants the
timing to match the original, quirks included. Sections 2–11 are the model.
Section 12 is portable reference pseudocode. Section 13 has test vectors.
Section 15 lists what is still unknown; do not fill those gaps by guessing.

It also closes the gap left open in [`d21_sequencer.md`](d21_sequencer.md):
the live bar.beat.tick writer is `DA4C:0008`, which writes through
`ES:[BX+34h..38h]` (so a search for direct stores to `[923E]`/`[9240]`
finds nothing), and the play/stop state is the byte `[D800]`, written by
the tick interrupt.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Behavioural model of the sequencer clock, transport, playback order, timing correct, metronome and sync |
| Observable | Timer reload words, tick interrupt `D61A:000A`, playback task `EC05:0000`, the routines in section 16 |
| Inputs | DGROUP `8010:xxxx` variables listed per section |
| Outputs | This note, `emu/lua/seq_watch.lua`, `emu/seq_evidence.py` |
| Confidence | Per claim, tagged below |
| Hardware deferred | Section 15: crystal frequency, timer reload edge, pad-scan latency, voice start latency |

### Evidence tags

| Tag | Meaning |
|-----|---------|
| **PROVEN** | Read from instruction bytes of the 3.50 image at the cited address |
| **PROVEN (trace)** | Also observed in the MAME harness (`python3 -m emu.seq_evidence`). A trace is one execution under MAME's device models; it supports the software logic, not board timing |
| **HYPOTHESIS** | Consistent with the code but a consumer, a name or a hardware fact is not established |
| **UNDETERMINED** | Not recovered |

### Address convention

Code is cited as linear-file offset plus `CS:IP`. For every address in this
note, 20-bit physical = file + `0x80000`, and 24-bit physical = that value
zero-extended, valid with XA=1 under the second PGR table (identity frames
for the ROM pages; [`address_model.md`](address_model.md),
[`pgr_live_after_amx.md`](pgr_live_after_amx.md)). Variables are DGROUP
offsets, `DS = 8010h`, written `[xxxx]`; they are RAM through the PGR.
Offsets are for 3.50; the DGROUP layout differs in 3.12 (section 14).

---

## 1. The model in one page

```
 2 MHz timer clock ──► TCT1, mode 2, count N ──► IRQ1 ──► tick interrupt (every tick, always running)
                                                          │  1 advance position, tempo map, SMPTE
                                                          │  2 reload N
                                                          │  3 transport state machine
                                                          │  4 post snapshot to the playback task
                                                          │  5 MIDI clock every 4th tick
                                                          ▼
                                             playback task (AMX task 2, one message per tick; steps as in 7.2)
                                                          │  a metronome for this position
                                                          │  b events AT this position (first tick after a start only)
                                                          │  c live input: sound it, queue it for recording
                                                          │  d timing-correct grid: note repeat, record flush
                                                          │  e advance counters
                                                          │  h note-offs, then events of the NEXT position
```

The facts that define the feel:

1. **One hardware interrupt per tick, 96 ticks per quarter note.** The tick
   length is a timer count `N = floor(12 500 000 / T10)` at 0.5 µs per
   count, `T10` = tempo × 10. The timer never stops; transport changes
   happen on tick boundaries.
2. **Tempo is truncated, never dithered.** The machine runs 0–160 ppm fast
   depending on tempo.
3. **Playback leads the position counter by one tick.** Events stored at
   position `p` sound when the position counter reads `p − 1`. The
   metronome and MIDI clock do not lead. On the first pass after a start,
   position 0 and position 1 sound in the same tick.
4. **Swing is rounded to the nearest tick**: swung position
   `= (interval × swing% + 25) / 50`.
5. **Record quantise decides on the position counter**, flushing at the
   midpoint between grid points; a hit exactly on the midpoint goes to the
   earlier grid point.
6. **Late ticks are replayed, not dropped.** If the playback task is locked
   out, ticks are counted and run back-to-back afterwards.

---

## 2. Time base

### 2.1 Clocks

| Item | Value | Evidence |
|------|-------|----------|
| Timer clock select | `OUT FFF0h, 12h` (TCKS) at file `0x78021` (`F800:0021`) | **PROVEN** |
| TCKS decode | `PS=10b` → oscillator ÷ 16 for TCT0 and TCT1; bit 4 set → TCT2 clocked from the TCLK pin | **PROVEN** (NEC 1991 V-Series data book, µPD70236 figure 51, in `01-cpu/`) |
| Timer clock assumed by the firmware | 2 000 000 Hz. The tempo constant (12 500 000) and the system tick count (20 000 for 10 ms) are only correct at this rate | **PROVEN** (arithmetic) |
| Oscillator | 32 MHz, implied by ÷16 → 2 MHz. MAME uses a 32 MHz crystal | **HYPOTHESIS** (`U-PHYS`; not read off a board) |

### 2.2 The three V53 timers

Ports: TCT0 `C030h`, TCT1 `C031h`, TCT2 `C032h`, mode `C033h`. ICU `C010h`/`C011h`.

| Timer | Mode word | Count | Role | Evidence |
|-------|-----------|-------|------|----------|
| TCT0 | `34h` (mode 2) | `4E20h` = 20 000 → 100 Hz | AMX system tick, `IVT[8]` = `D52A:0008` (file `0x552A8`). Also the time-stamp source (2.4) | **PROVEN**; 10.000 ms **PROVEN (trace)** |
| TCT1 | `74h` (mode 2, LSB then MSB) at file `0x305AB` (`B03B:01FB`) | `N`, rewritten every tick | **Sequencer tick**, `IVT[9]` = `D61A:000A` (file `0x561AA`) | **PROVEN** |
| TCT2 | `B4h` | — | Clocked from TCLK. Not used by the sequencer clock | **PROVEN** (mode), role **UNDETERMINED** |

The external 8254 at `F0h`–`F6h` is not the sequencer clock. Counter 2
(`F4h`) makes the FSK sync-out tone (section 10.2).

TCT1 is also reloaded by a second handler (`D61A:086E`, file `0x56A0E`;
the write is at file `0x56A6E`). It is not the one planted at `IVT[9]` on
the reset path. Its planter, and whether it belongs to the Generate SMPTE
function, are **UNDETERMINED**. Not part of normal play.

### 2.3 Tick timer rules

- The tick interrupt writes the reload word `[D842]` to `C031h`, low byte
  then high byte, on **every** tick (file `0x564AD`, `D61A:030D`).
  **PROVEN.**
- TCT1's mode word is written only during start-up (file `0x7801A` in
  the BIOS, file `0x305AD` in `B03B:01F7`). Nothing rewrites it when play
  starts, so **the tick grid is free-running and PLAY is quantised to
  it**: a start takes effect at the next tick interrupt, 0 to 1 tick
  after the request. **PROVEN** (no other `OUT C033h` with a counter-1
  mode word in the image).
- In mode 2 a count written during a period is loaded at the end of that
  period. A new `N` written in tick interrupt `n` therefore sets the
  length of the period that starts at tick `n + 1`. **HYPOTHESIS**
  (µPD71054/8254 mode-2 behaviour; not measured on a board).
- Period = `N` counts = `N × 0.5 µs`. **HYPOTHESIS** for the same reason.
  The MAME harness measures `N + 1` counts (5208.48 µs at `N` = 10416)
  while TCT0, which is never rewritten, measures exactly 10.000 ms. The
  extra count comes from MAME's `pit8253` adding one clock when a count is
  written mid-cycle (`middle_of_a_cycle` in `06-mame/machine/pit8253.cpp`).
  Treat it as an emulator artifact until a scope says otherwise
  (section 15).

### 2.4 Time stamps

`D52A:0190` (file `0x55430`) returns a 32-bit time in 0.5 µs units:
`[D814:D816]` (advanced by 20 000 in the 100 Hz handler) plus
`20000 − TCT0`. Used for external sync measurement, not for playback.
**PROVEN.**

---

## 3. Tempo

### 3.1 Variables

| Variable | Meaning | Evidence |
|----------|---------|----------|
| `[81B4]` word | Master tempo × 10. Reset value `04B0h` = 120.0 | **PROVEN** (file `0x322A9`) |
| `[8C85]` word | Tempo × 10 of the selected sequence (sequence header `+23h`) | **PROVEN** (file `0x34A1C`) |
| `[81B8]` byte | Tempo source: non-zero = sequence, 0 = master. Reset 1 | **PROVEN** (file `0x3E061`); the label "(SEQ)" on the main screen matches |
| `[D83E]` word | Base tempo × 10 in use = `[81B8] ? [8C85] : [81B4]` | **PROVEN** (file `0x3E061`–`0x3E070`) |
| `[D7FD]` word | Tempo ratio, `1000h` = 100 % | **PROVEN** (file `0x34A45`, `0x5C0C6`) |
| `[8A1B]` word | Ratio at the loop point (start-of-sequence ratio) | **PROVEN** (file `0x56443`) |
| `[D842]` word | Tick timer reload `N` | **PROVEN** |
| `[D83A]`/`[D83C]` | `N` as 16.16 (fraction, integer). Used only for SMPTE position | **PROVEN** (file `0x56294`) |
| `[D844]` word | Copy of `N`; under external sync, the measured tick length | **PROVEN** |

### 3.2 Formulas

Effective tempo, `DC08:000E` (file `0x5C08E`). **PROVEN.**

```
T10 = (ratio * base + 0x800) >> 12        ; 16x16 -> 32-bit product, round half up
T10 = min(max(T10, 300), 3000)            ; 30.0 .. 300.0 BPM
```

Tick length, `EB0B:0006` (file `0x6B0B6`), constant 12 500 000 at file
`0x6B0B2`. **PROVEN.**

```
N    = 12_500_000 div T10                 ; integer part  -> [D842], [D844], [D83C]
frac = ((12_500_000 mod T10) << 16) div T10     ; -> [D83A]
```

Apply, `DC08:0046` (file `0x5C0C6`): computes both and stores them. Called
from the tick interrupt (tempo map) and from `DDC0:000F` (file `0x5DC0F`),
which skips the update while slaved to MIDI clock, FSK or clicks.
**PROVEN.**

### 3.3 Quirks

- **Truncation.** Only the integer part reaches the timer. `frac` is never
  used to dither the tick. The sequencer therefore runs fast by
  `frac / N`: 0 ppm at 80, 100, 125 BPM; +64 ppm at 90, 120, 140;
  +160 ppm at 300. **PROVEN** (three writers of `[D842]`, none dithers:
  files `0x3E089`, `0x5C0E5`, `0x5DBB7`).
- **Ratio rounding.** A tempo change is base × ratio rounded to 0.1 BPM,
  then clamped. **PROVEN.**
- **Boot value.** The timer is first loaded with `28B1h` = 10417 (file
  `0x305CD`), and the init path `DDC0:0031` rounds
  (`(125 000 000 / T10 + 5) / 10`). After the first `DC08:0046` the
  truncated value is in force: `[D842]` = `28B0h` = 10416 at 120.0 with
  the machine idle. **PROVEN (trace)**.
- **Sequence select.** `B3FD:0A2F` (file `0x349FF`) sets
  `ratio = (seq_tempo << 12) / base` when the source is the sequence, and
  `1000h` when the source is master. **PROVEN.**

### 3.4 Tempo map

A list of 6-byte entries `{u32 tick, u16 ratio}` starting at `[8A0F]`,
current entry `[8A13]`, 32-bit countdown `[8A17:8A19]`. In the tick
interrupt, while playing (file `0x563EC`–`0x564A9`). **PROVEN.**

```
countdown -= 1
if countdown == 0:
    e = current
    if tempo_changes_on [D7FF] and not (ext-sync active and mode not in {1,2}):
        if e.ratio != 0:
            ratio = e.ratio; apply()
        else:                               ; ratio 0 marks the loop point
            if looping:  ratio = [8A1B]; apply(); current = first; prev_time = loop_start
            else:        stop walking the list
    advance: countdown = next.tick - this.tick
```

With `[D7FF]` = 0 the list is still walked but nothing is applied. The
editing of this list (Tempo Change screen) is **UNDETERMINED**.

---

## 4. Position and the sequence structure

One `tick` = 1/96 quarter note. **PROVEN** (operator's manual v3.0 p.26;
constant 96 throughout).

The main sequence is described by a structure at `DS:9208`; the second
(simultaneous) sequence uses the same layout at `DS:8E2E`. Fields
established by consumers:

| Offset | 3.50 address | Meaning | Evidence |
|--------|--------------|---------|----------|
| `+00` byte | `[9208]` | Status. `FFh` = unused, 0 = usable, 2 = pending switch | **PROVEN** (file `0x5CF0F`), meanings **HYPOTHESIS** |
| `+01` byte | `[9209]` | Bit 0 = loop on | **PROVEN** (file `0x5657F`) |
| `+12` dword | `[921A]` | Stream read pointer | **PROVEN** |
| `+1A` dword | `[9222]` | Stream pointer of the loop point | **PROVEN** (file `0x5D17C`) |
| `+1E` dword | `[9226]` | Loop-to position in ticks | **PROVEN** (file `0x56586`) |
| `+22` dword | `[922A]` | Sequence length in ticks | **PROVEN** (file `0x564E5`) |
| `+26` dword | `[922E]` | Ticks run since start | **PROVEN** (file `0x56273`) |
| `+2A` dword | `[9232]` | **Position counter** `POS` | **PROVEN** |
| `+2E` word | `[9236]` | Stream handle | **PROVEN** (file `0x5CF31`) |
| `+30` word | `[9238]` | Number of bars | **PROVEN** (file `0x565CD`) |
| `+32` word | `[923A]` | Loop-to bar (1 = whole sequence) | **PROVEN** (file `0x56596`), name from the main screen "Loop:TO BAR 1" |
| `+34` word | `[923C]` | Tick within the bar | **PROVEN** (file `0x5A4D2`) |
| `+36` byte | `[923E]` | Tick within the beat | **PROVEN** |
| `+37` byte | `[923F]` | Beat, from 1 | **PROVEN** |
| `+38` word | `[9240]` | Bar | **PROVEN** |
| `+3A` word | `[9242]` | **Ticks until the next stream event** `NEXT` | **PROVEN** |
| `+3C` byte | `[9244]` | Beats per bar | **PROVEN** |
| `+3E` word | `[9246]` | Ticks per bar | **PROVEN** (384 for 4/4, trace) |
| `+40` word | `[9248]` | Ticks per beat | **PROVEN** (96 for 4/4, trace) |

`DA4C:0008` (file `0x5A4C8`), once per tick per active sequence. **PROVEN.**

```
NEXT -= 1
tick_in_bar += 1
tick_in_beat += 1
if tick_in_beat >= ticks_per_beat:
    tick_in_beat = 0; beat += 1
    if beat > beats_per_bar: beat = 1; tick_in_bar = 0; bar += 1
```

`POS` and `[922E]` are advanced by the tick interrupt. The bar/beat/tick
counters and `NEXT` are advanced by the playback task. They can differ by
the ticks the task has not processed yet.

---

## 5. The tick interrupt — `D61A:000A` (file `0x561AA`)

Runs on every TCT1 period whether or not the sequencer is playing. Order
is normative. **PROVEN** unless tagged.

```
 1  AMX interrupt enter (FB00:0157)
 2  irq_count [D838] += 1
 3  external-sync watchdog (section 11.3)
 4  [8A0D] += 1
 5  if state [D800] < 6:                      ; not running
        (MIDI-clock pass-through bookkeeping when [D7F7] == 10h)
        goto 9
 6  run [922E] += 1 ;  POS [9232] += 1
 7  SMPTE: acc48 [D7E0..D7E4] += N as 16.16 ; on overflow of the frame length
       [D818..D81C]: frame [D7E6] += 1 ; MTC quarter frames out if enabled
 8  clock divider: if div [D7F6] == 0: div = DIV[sync_mode]; clock_count [D826] += 1
                   div -= 1
    tempo map (3.4)
 9  OUT C031h <- N low, N high ;  STI
10  transport state machine (section 6). May change state, wrap POS,
    extend the sequence, or force a stop.
11  [D804:D806] = POS
12  CLI ; wake task 2 (FB00:04AC, DL=2)
    post 12 bytes at [D800..D80B] to task 2 (FB00:03B3, BX=D800h, CX=0)
    if the post fails and state != 0: [9644] |= 1        ; forces a stop next tick
13  FSK sync tone (10.2)
14  if (irq_count & 3) == 0 and clock_hold [D7DA] == 0:
        if skip [D7D9] > 0: skip -= 1
        else: send F8h to the sync-out port(s) [81BC]
15  EOI (OUT C010h <- 61h, C4h) ; AMX interrupt leave (FB00:0194) ; IRET
```

`DIV` is the byte table at `DS:0F5A`: `4, 1, 1, 4, 96` by sync mode
(section 11.1). The message is a snapshot: byte 0 is the state after step
10, bytes 4–7 the position. The task therefore sees the state that was true
at its tick, even if it runs late. **PROVEN** (`FB00:03B3` copies six
words from `ES:BP` = caller's `BX`, file `0x7B3FD`).

AMX leave (step 15) switches to task 2 at once if it is the highest ready
task. Task index is priority; lower index wins (`[DI+11h]` compare at
file `0x7B3A6`, inside the ready primitive). Tasks 0 and 1 outrank the sequencer; tasks
3–7, including the UI (task 7), do not. **PROVEN** for the compare;
identity of tasks 0 and 1 **UNDETERMINED**.

---

## 6. Transport state machine

### 6.1 State and request

| Value | State `[D800]` | Evidence |
|-------|----------------|----------|
| 0 | Stopped | **PROVEN (trace)** |
| 2 | Waiting (Wait For Key) | **PROVEN** code; name **HYPOTHESIS** |
| 4 | Count-in | **PROVEN** code; name **HYPOTHESIS** |
| 6 | Play | **PROVEN (trace)** |
| 8 | Record | **PROVEN (trace)** |
| 0Ah | Overdub | **PROVEN (trace)** |

The request is `[A7B0] & 3Fh`, written by other tasks; the state only
changes inside the tick interrupt. Bit 6 of `[A7B0]` was set for
REC + PLAY START in the trace; its meaning is **UNDETERMINED**. Jump
table `D61A:046C` (file `0x5660C`): `04BE, 0478, 04A3, 060F, 06D0, 0748`.

### 6.2 Before the state dispatch (file `0x564B8`–`0x56602`)

`END` is `[A763:A765]`. **PROVEN.**

```
if next_seq [8C8B] <= 0: switch_count [8C8A] = 0
elif switch_count >= 2:   next_seq = FFh; switch_count = 0

req = [A7B0] & 3Fh
if state == 0:
    if req == 0: dispatch
    END = length [922A]

if song_mode [89ED] != 0:                  ; name is a HYPOTHESIS, see below
    if POS == step_end [89E7]:
        if not ([A987 + [89F1]] & 1): STOP_NOTIFY
        POS = step_start [89E3]
elif POS == END:
    if next_seq > 0:                       ; queued sequence change
        END = next_length [A767]; POS = 0; run = 0; switch_count += 1
    elif loop on:
        POS = loop_to [9226]
        if loop_bar [923A] == 1:  if req == 8:  req = 0Ah (overdub)
        else:                      if req >= 8: req = 6   (play)
    else:                                   ; loop off
        if req != 8 or bars >= 999: STOP_NOTIFY
        length += ticks_per_bar; END = length          ; record extends by one bar

if req == 0: STOP
if overrun [9644] != 0: STOP_NOTIFY
dispatch on state
```

`STOP_NOTIFY` = far call `DCA2:014F` (stub at file `0x5CB6F`, body at file
`0x5CA9A`; sends MIDI Stop `FCh` when sync out is on) then `STOP`. `STOP` (file `0x5695D`): if state
≥ 8 record-out position `[8469]` = `POS`; request = 0; state = 0;
`[A7AB]` = 0.

`[89ED]` selects a second set of end/start positions. The event player
handles the same flag with a step index `[89F0]`, a repeat count `[89EE]`
and a per-step table (file `0x5D047`–`0x5D114`), which fits Song mode.
**HYPOTHESIS**; not modelled further here.

Consequences, all **PROVEN**:

- **Record with loop on, loop to bar 1:** Record becomes Overdub at the
  loop. **PROVEN (trace)**: state 8 → 0Ah at the 768th tick of a two-bar
  sequence.
- **Record or Overdub with loop to a later bar:** drops to Play at the
  loop.
- **Record with loop off:** the sequence grows by one bar each time the
  end is reached, up to 999 bars. Play and Overdub stop at the end.
- **Overrun:** if a tick message could not be posted, the sequencer stops
  on the next tick.

### 6.3 Per-state handling

```
state 0, req != 0:
    if wait_for_key [A7B6]: state = 2
    else START

state 2:  if a key or MIDI event arrived (D6F4:000A): wait_for_key = 0; START

state 4 (count-in):
    if req == 0: state = 0
    else: count [8A0B] -= 1 ; if count == 0: BEGIN

START:
    if punch enabled and req in {8, 0Ah} and POS != punch_in [845D]:
        pending [A7AB] = req ; ready task 5
    if count_in [A7B7] and not (count_in_record_only [8372] and req == 6):
        state = 4 ; count = ticks_per_bar ; return
    BEGIN

BEGIN:
    if pending: new = 6
    else:
        if POS == END (or step_end when [89ED] != 0): STOP_NOTIFY
        new = req ; if new in {8, 0Ah}: record_in [8465] = POS
    state = new
    irq_count = low word of run            ; aligns MIDI clock to the start
    clock_count [D826] = run / 4 (run / 96 in click-sync mode)
    div = DIV[sync_mode] - 1 ; clock_hold [D7DA] = 0 ; first_tick [A761] = 1

state 6 (play):
    if pending punch-in and POS + 1 (wrapped at END) == punch_in:
        state = pending ; pending = 0                   ; punch in on the next tick
    elif req == 0: STOP
    elif req in {8, 0Ah}:
        if punch enabled: pending = req ; stay in 6
        else: record_in = POS ; state = req

state 8 / 0Ah:
    if punch-out enabled and POS + 1 (wrapped) == punch_out [8461]:
        state = 6 ; req = 6
    elif req == 0: STOP
    elif req == 6: record_out [8469] = POS ; state = 6
    else: state = req
```

The count-in is always one bar of the current time signature (`[9246]`
ticks). During count-in the position does not advance (step 5 of section 5
is taken). **PROVEN.** The punch and wait-for-key variable names are
**HYPOTHESIS**; the control flow is **PROVEN**.

---

## 7. The playback task — AMX task 2, `EC05:0000` (file `0x6C050`)

Receives one message per tick; argument = the state snapshot.

### 7.1 Lock and catch-up (file `0x6C05C`–`0x6C090`). **PROVEN.**

```
task2(state):
    if lock [9757] != 0:
        if last_state [A7AE] != 0: backlog [FFA6] += 1
        return
    tick(state)
    while backlog != 0: tick(state); backlog -= 1
```

Ticks that arrive while the sequence data is locked by another task are
counted and replayed in one burst on the next unlocked tick, using the
current message's state. Nothing is skipped. If messages cannot be posted
at all, the overrun stop of 6.2 applies instead.

### 7.2 `tick(state)` — `EC05:0043` (file `0x6C093`)

Order is normative. **PROVEN**; names of helpers are descriptive.

```
tick(state):
    if [A7AD] != 0: (separate metronome-only path, UNDETERMINED) ; return

    if last_state != 0 and state == 0:              ; stopping
        flush the record queue (9.5), cancel a queued sequence change
    last_state [A7AE] = state

 a  METRONOME (section 8), for the tick-in-bar of this position

 b  if state >= 6 and NEXT <= 0:                    ; start, or after a locate
        play_due(main)                               ; events AT this position
        (same for the second sequence if active)

 c  if state not in {2, 4} (and not stopped with [A7AF] & 14h):
        LIVE INPUT: drain the input queue; sound each event now and, when
        recording, put it in the record queue (9.5)

    if state < 6: goto g

 d  on_grid = (phase [89FD] == 0) or (phase == swing_pos [89F9])
    if on_grid:
        if TIMING CORRECT is held and note value is not OFF: NOTE REPEAT (9.6)
        since_grid: [89FF] = [8A01]; [8A01] = 0; flush_armed [89F7] = 1
    if mid [89FB] == 0: FLUSH RECORD QUEUE (9.5)

 e  mid   = (mid + 1)   mod interval
    phase = (phase + 1) mod pair
    [8A01] += 1
    advance(main) ; advance(second)                  ; DA4C:0008, section 4

 g  if state == 4: count-in tick-in-bar [923C] += 1, wrap at ticks_per_bar

 h  if state >= 6:
        NOTE-OFFS (7.4)
        play_due(main) ; play_due(second)            ; events of position + 1
```

### 7.3 Playback leads the position by one tick

Step `e` decrements `NEXT`, then step `h` plays whatever is now due. So
while the task handles the tick in which `POS` = `k`, it plays the events
stored at stream position `k + 1`. Step `b` only fires when `NEXT` is
already 0 on entry, i.e. on the first tick after a start or locate.

Let `t(n)` be the time of the n-th tick interrupt after the one that
entered Play/Record (`t(0)` = that interrupt), `L` the loop length.

| What | When it happens | Evidence |
|------|-----------------|----------|
| Events at position 0, first pass | `t(0)` | **PROVEN (trace)**: +0.05 tick |
| Events at position `p ≥ 1`, first pass | `t(p − 1)` | **PROVEN (trace)**: 24 → 23.04, 96 → 95.04 |
| Events at position `p` on pass `m ≥ 2` | `t((m − 1)·L + p − 1)` | **PROVEN (trace)**: 0 → 767.06, 24 → 791.04 with `L` = 768 |
| Metronome click for position `p` | `t(p)` | **PROVEN** (step a uses the counter before step e) |
| MIDI clock | `t(4j)` | **PROVEN** (section 5 step 14, `irq_count` aligned at BEGIN) |
| `POS` reads `p` | from `t(p)` | **PROVEN (trace)** |

So:

- **After a start, the first tick is swallowed.** Position 0 and position
  1 both sound at `t(0)`. Everything after the first downbeat is one tick
  closer to it than written. From the second pass on, spacing is exact.
- **Sequence events are one tick ahead of the metronome click and of the
  outgoing MIDI clock**, except the first downbeat.

Whether the lead is intended (for example to offset voice start latency)
is **UNDETERMINED**. A faithful implementation reproduces it; section 12
has a switch.

The fractions (0.04–0.06 tick ≈ 220–320 µs) are the interrupt-to-task
latency under MAME's CPU model. Indicative only.

### 7.4 Note-offs — `DD70:00F4` (file `0x5D7F4`)

Sounding notes have a duration in ticks in a table (`[9EEA]`, count
`[9F4E]`), with a countdown to the earliest expiry `[9F50]`. Each tick the
countdown is decremented; at zero, every entry is reduced by the elapsed
amount, expired entries send note-off, and the minimum is recomputed.
Note-offs run before the next position's note-ons (step `h`). **PROVEN.**

---

## 8. Metronome and count-in

Step `a` of 7.2 (file `0x6C1D4`–`0x6C207`). **PROVEN.**

```
if state >= 4 and not (state == 6 and click_in_play [8457] == 0):
    if tick_in_bar [923C] mod click_interval [8A09] == 0:
        click(accent = (tick_in_bar == 0))
```

- `click_interval` = `DS:0F52[rate]` = `96, 64, 48, 32, 24, 16, 12, 8`
  for 1/4, 1/4 T, 1/8, 1/8 T, 1/16, 1/16 T, 1/32, 1/32 T (file `0x3E048`).
  **PROVEN** values; option order **HYPOTHESIS**.
- Clicks in count-in, Record and Overdub always; in Play only when the
  option is on. **PROVEN.**
- The accent is the first tick of the bar. Unaccented clicks play at one
  quarter of the click volume `[8456]` (`B19C:000E`, file `0x319CE`).
  **PROVEN.**
- The tick-in-bar counter restarts at each bar, so the click follows the
  time signature. **PROVEN.**

---

## 9. Timing Correct

### 9.1 Parameters

| Variable | Meaning | Evidence |
|----------|---------|----------|
| `[81CF]` byte | Note value index | **PROVEN** |
| `[81CE]` byte | Swing %, 50–75 (field limits `32h`, `4Bh`, file `0x4E83F`) | **PROVEN (trace)** |
| `[81CD]` byte | Shift, signed ticks: + later, − earlier | **PROVEN (trace)** (+3 for LATER 3) |
| `[89F6]` byte | `interval` in ticks | **PROVEN** |
| `[89F5]` byte | `pair` = 2 × interval | **PROVEN** |
| `[89F9]` word | `swing_pos` | **PROVEN (trace)** (62 % → 30) |
| `[89FD]` word | `phase`, 0 … pair − 1 | **PROVEN (trace)** |
| `[89FB]` word | `mid`, 0 … interval − 1 | **PROVEN (trace)** |
| `[89F4]` byte | `on_grid` flag | **PROVEN** |

Note values (ticks): stock 3.12 has seven, index 0–6:
`1 (OFF), 48, 32, 24, 16, 12, 8`. Vailixi 3.50 has thirteen, index 0–12:
`3, 2, 1, 96, 64, 48, 32, 24, 16, 12, 8, 6, 4` (table `DS:6D3A`, labels
"OFF 1/128", "OFF 1/192", "OFF 1/384", "1/4 NOTE" … "1/64 TRPLT"). Reset
value is 1/16 in both. **PROVEN.**

### 9.2 Grid — `CE7A:042C` (file `0x4EBCC`). **PROVEN.**

```
interval  = TABLE[note_value]
pair      = 2 * interval
swing_pos = (interval * swing + 25) div 50
```

A pair has two grid points: phase 0 and phase `swing_pos`. At 50 %
`swing_pos = interval`. The `+ 25` rounds to the nearest tick.

Swing applies to 1/8 and 1/16 only on stock (other values force 50 %,
file `0x4A5D9` in 3.12). Vailixi shows the field for every note value
from 1/4 down and does not force 50 % (file `0x4E855`); behaviour of
swing ≠ 50 with its OFF values is **UNDETERMINED**.

### 9.3 Shift — file `0x4E9BA`. **PROVEN.**

```
max_shift = (pair - swing_pos) div 2 - 1        ; 11 for 1/16 at 50 %
shift     = clamp(amount, 0, max_shift) * (LATER ? +1 : -1)
```

### 9.4 Counters

Reset by `DA0F:000E` (file `0x5A0FE`), called from the seek-to-bar routine
(file `0x5E441`). **PROVEN**; reset values **PROVEN (trace)**.

```
phase = (pair - shift) mod pair
mid   = (phase + pair - (swing_pos div 2)) mod interval
```

Both then advance by one per tick (7.2 step `e`; also `E2EA:000C` forward
and file `0x5E12C` backward when stepping while stopped). With `k` = the
number of ticks processed since the seek:

```
on_grid  when (k - shift) mod pair is 0 or swing_pos
midpoint when (k - shift) mod pair is  swing_pos div 2
                                   or  swing_pos div 2 + interval
```

The counters are **not** recomputed from the bar position while playing.
They are only reset on a seek to a bar. If a bar, or the loop, is not a
whole number of pairs (odd metres with triplet or 1/8-swing settings), the
grid drifts against the bar lines until the next seek. **PROVEN** (no
other writer of `[89FD]`); musical consequence not exercised.

### 9.5 Recording: which grid point a hit lands on

Mechanism (files `0x6C273`–`0x6C340`, `0x5DDDE`). **PROVEN.**

- A live event is sounded immediately and placed in a holding queue
  (queue 4).
- At each `on_grid` tick the delta counter since the previous grid point
  is saved (`[89FF] = [8A01]`) and the flush is armed.
- At each midpoint tick the holding queue is written to the sequence with
  the saved delta, i.e. **at the last grid point**.
- Live input is drained (step `c`) before the midpoint test (step `d`) in
  the same tick.

Rule, in terms of the phase `φ = (k − shift) mod pair` of the tick in
which the hit is processed, with `mA = swing_pos div 2`,
`mB = mA + interval`:

| φ | Recorded at |
|---|-------------|
| `0` … `mA` | phase 0 of the current pair (the grid point just passed) |
| `mA + 1` … `mB` | phase `swing_pos` of the current pair |
| `mB + 1` … `pair − 1` | phase 0 of the next pair |

A hit processed exactly on a midpoint tick goes to the **earlier** grid
point. **PROVEN (trace)** for 1/16, 50 %: phases 10, 11, 12 → the
1/16 just passed; 13, 14, 15, 16 → the next one.

Because a recorded note is only written after its grid point has passed,
it is not re-triggered in the pass in which it was played.
**PROVEN (trace).**

In real time (section 7.3) a hit is processed in tick `k` if it arrived
during the tick before `t(k)`. The capture window of a grid point at
50 % swing is therefore

- relative to the **metronome click** of that grid point: more than
  `interval/2` ticks before, up to and including `interval/2` ticks after
  → `(−12, +12]` for 1/16;
- relative to the **playback** of notes on that grid point (one tick
  earlier): `(−11, +13]` for 1/16.

Input latency ahead of the queue (pad scan, panel link) shifts both
windows and is **UNDETERMINED** (`U-PANEL-ROM`).

Recorded note durations, and the "Move existing" edit, are
**UNDETERMINED** (entry points: `DD46:000B`, file `0x5D46B`; duration
encode `D9EA:0042`).

### 9.6 Note repeat — `DC89:0007` (drum), `DC96:000A` (MIDI track)

On every `on_grid` tick while TIMING CORRECT is held, in Play, Record or
Overdub, with the note value not OFF (7.2 step `d`). **PROVEN.**

```
for each pad or key currently held:
    velocity = current pressure of that pad (drum track), or the last
               channel pressure, 64 if none (MIDI track); a fixed value
               replaces it when [836B] != 0 (meaning UNDETERMINED)
    emit note, duration = max(interval - 4, 1) ticks
    (in Record/Overdub it is also recorded)
```

While TIMING CORRECT or ERASE is held, a pad hit itself does not sound; it
only updates the held table (`DC2D:0003`, file `0x5C2D3`). **PROVEN.**
Vailixi gates on index > 2 (file `0x6C2F9`); the stock gate is the OFF
index, **HYPOTHESIS** (not re-read in 3.12).

### 9.7 Other uses

The interval is also the step of the `<` and `>` keys (operator's manual
p.50). The stepping routines above move the grid counters with it.
**PROVEN** for the counters; key binding **HYPOTHESIS**.

---

## 10. Sync out

### 10.1 MIDI clock

- `F8h` on every tick interrupt whose `irq_count` is a multiple of 4,
  **whether or not the sequencer is playing**, at the current tempo
  (section 5 step 14). **PROVEN.**
- Port select `[81BC]`: 0 = off, 1–4 = OUT A–D, 5 = all
  (`DC5B:0088`, file `0x5C638`). Reset value 0. **PROVEN**; names
  **HYPOTHESIS**.
- Start/Continue/Stop are sent by `DCA2:0159` (`FAh`), `DCA2:0154`
  (`FBh`), `DCA2:014F` (`FCh`): stubs at files `0x5CB79`, `0x5CB74`,
  `0x5CB6F` load a code `5Ah`/`59h`/`58h` and share the dispatcher at
  file `0x5CA36` (table `DCA2:0058`); bodies at files `0x5CB09`,
  `0x5CAC5`, `0x5CA9A`.
  Start and Continue set `clock_hold` so no `F8h` goes out until `BEGIN`
  (6.3) clears it and aligns `irq_count`. The first `F8h` after Start is
  sent at `t(0)`. **PROVEN** for the flags; the caller that sends `FAh`
  on a PLAY key press is **UNDETERMINED**.
- Suppressed while the error flag `[9644]` is set. **PROVEN.**

### 10.2 FSK

When `[D7F8]` ≠ 0, the tick interrupt programs external 8254 counter 2
(`F4h`) with `1A0Ah` (6666) or `0D05h` (3333): the lower value while
playing and bit 1 of `irq_count` is clear, i.e. the tone alternates every
two ticks (file `0x569AF`). **PROVEN.** Tone frequencies depend on that
counter's clock: **UNDETERMINED** (1200/2400 Hz if it is 8 MHz).

### 10.3 MIDI Time Code / SMPTE

The tick interrupt accumulates the exact tick length (16.16) into a 48-bit
position and emits MTC quarter frames from it (file `0x56287`–`0x563C7`).
This is the only user of the fractional tick length. Details
**UNDETERMINED**.

---

## 11. Sync in

### 11.1 Modes

`[81BD]` indexes `DIV` (`DS:0F5A`) = `4, 1, 1, 4, 96` and the word table
at file `0x5DBBC`. The Sync In mode strings are stored in the order MIDI
CLOCK, MIDI TIME CODE, SMPTE, FSK24, 1/4 NOTE CLICKS (file `0x26A8E`).
Mapping index → name in that order fits the divisors (24 ppq, time code,
time code, 24 ppq, one pulse per quarter note) and the mode tests in the
code (`[81BD]` 1 and 2 take the time-code paths). **HYPOTHESIS.**
`[81BF]` ≠ 0 enables sync in. **HYPOTHESIS.**

### 11.2 Following an external clock: a software PLL

The tick timer keeps generating all 96 ticks per quarter note; incoming
pulses only steer its period. `DD9A:000E` (file `0x5D9AE`), run on each
incoming pulse from `DBCD:0004` (file `0x5BCD4`), which first shifts the
pulse time stamps (`[D832]` ← `[D82E]` ← now, 0.5 µs units) and counts the
pulse in `[D822:D824]`. **PROVEN.**

```
base = clamp((t_last - t_prev) div DIV[mode], 3571, 50000)      ; -> [D844]
                                                 ; modes 1 and 2: base = [D844] unchanged
err  = pulses_received [D822] - clocks_generated [D826]

if |err| > 1:                                    ; coarse
    m = (err > 0) ? err - 1 : -err
    g = TABLE_A[(m <= 15 ? m : 16) - 1]          ; 0100h, 0140h, ... 04C0h
else:                                            ; fine: phase within one pulse
    frac = phase_error / (t_last - t_prev)       ; 0 .. 1 as a 16-bit fraction
    g = TABLE_B[frac >> 12]                      ; 2,4,6,8,10,12,14,16,32,64,96,128,160,192,224,256

corr = (base * g) >> 8
N = (internal clock is ahead) ? min(base + corr, 50000) : max(base - corr, 3571)
[D842] = N
```

`N` limits 3571 and 50 000 correspond to 350 and 25 BPM. Tables at file
`0x5DBCF` and `0x5DBEF`. The arithmetic above is **PROVEN**; the exact
sign conventions of the fine branch and the pulse/phase definitions for
the time-code modes are **HYPOTHESIS** (read once, not traced).

### 11.3 Start, stop, drop-out

A state byte `[D7F7]` (values 0–14h, jump table at file `0x5BCF9`) tracks
the external source. For modes other than 1 (file `0x5BDB0`–`0x5BDEC`,
**PROVEN**): a first pulse without a preceding Start enters a follow-only
state (10h) and zeroes both clock counts; with Start or Continue pending
(`[D7D8]` = 1 or 2) it enters state 12h and calls the same `DCA2` Start or
Continue entry as section 10.1. A pulse is ignored (state 0Eh) when the
sequence is unused or `[A7AF] & 15h` is set. In the tick
interrupt, if no pulse has arrived for 6 × 65 536 timer counts (≈197 ms;
≈2.0 s in click mode) the source is declared lost and, unless already
idle, the sequencer is stopped (file `0x561F7`–`0x56229`). **PROVEN** for
the timeout; the full state table is **UNDETERMINED**.

---

## 12. Reference pseudocode

Portable, single sequence, internal clock. `LEAD = 1` reproduces the
MPC3000; `LEAD = 0` removes the one-tick playback lead and the swallowed
first tick (not authentic).

```python
TIMER_HZ = 2_000_000

def effective_tempo10(base10, ratio=0x1000):
    return min(max((base10 * ratio + 0x800) >> 12, 300), 3000)

def tick_count(t10):                 # timer counts per tick
    return 12_500_000 // t10

def grid(interval, swing, shift):
    pair = 2 * interval
    sp = (interval * swing + 25) // 50
    phase = (pair - shift) % pair
    mid = (phase + pair - sp // 2) % interval
    return pair, sp, phase, mid

class Sequencer:
    # state: 0 stop, 4 count-in, 6 play, 8 record, 10 overdub

    def timer_irq(self):                         # every tick_count(t10) * 0.5 us, always
        self.irq += 1
        if self.state >= 6:
            self.run += 1
            self.pos += 1
            self.tempo_map_step()                # may change N
        self.timer.reload(self.N)                # takes effect after the current period
        self.transport()                         # section 6; may wrap pos, change state
        self.post(self.state, self.pos)          # snapshot; never drop, queue if busy
        if self.irq % 4 == 0 and not self.clock_hold:
            self.midi_clock()

    def tick(self, state):                       # one per posted message, in order
        if state >= 4 and (state != 6 or self.click_in_play):
            if self.tick_in_bar % self.click_interval == 0:
                self.click(accent=self.tick_in_bar == 0)
        if state >= 6 and self.next <= 0:
            self.play_due()                      # start / after locate only
        if state not in (2, 4):
            for ev in self.drain_live_input():
                self.sound(ev)
                if state >= 8:
                    self.hold.append(ev)
        if state >= 6:
            on_grid = self.phase == 0 or self.phase == self.swing_pos
            if on_grid:
                if self.repeat_held and self.interval_is_not_off:
                    self.note_repeat(duration=max(self.interval - 4, 1))
                self.grid_delta, self.since = self.since, 0
                self.armed = True
            if self.mid == 0 and self.armed:
                self.write_at_last_grid(self.hold)   # timestamp = last on_grid tick
                self.hold.clear(); self.armed = False
            self.mid = (self.mid + 1) % self.interval
            self.phase = (self.phase + 1) % self.pair
            self.since += 1
            self.advance_counters()              # next -= 1, bar/beat/tick
        if state == 4:
            self.tick_in_bar = (self.tick_in_bar + 1) % self.ticks_per_bar
        if state >= 6:
            self.note_offs()
            if LEAD:
                self.play_due()                  # events of position + 1
```

`play_due()` plays every event whose delta has expired, in stream order,
until it reads a non-zero delta. With `LEAD = 0`, call `play_due()` before
`advance_counters()` instead and drop the start-only call.

---

## 13. Test vectors

### 13.1 Tempo → timer count (ratio `1000h`)

| BPM | `T10` | `N` | `frac` | Tick (µs) | Actual BPM | Error (ppm) |
|-----|-------|-----|--------|-----------|-----------|-------------|
| 30.0 | 300 | 41666 | `AAAAh` | 20833.0 | 30.0005 | +16 |
| 60.0 | 600 | 20833 | `5555h` | 10416.5 | 60.0010 | +16 |
| 80.0 | 800 | 15625 | `0000h` | 7812.5 | 80.0000 | 0 |
| 90.0 | 900 | 13888 | `E38Eh` | 6944.0 | 90.0058 | +64 |
| 93.3 | 933 | 13397 | `A45Bh` | 6698.5 | 93.3045 | +48 |
| 100.0 | 1000 | 12500 | `0000h` | 6250.0 | 100.0000 | 0 |
| 120.0 | 1200 | 10416 | `AAAAh` | 5208.0 | 120.0077 | +64 |
| 125.0 | 1250 | 10000 | `0000h` | 5000.0 | 125.0000 | 0 |
| 133.3 | 1333 | 9377 | `5826h` | 4688.5 | 133.3049 | +37 |
| 140.0 | 1400 | 8928 | `9249h` | 4464.0 | 140.0090 | +64 |
| 174.0 | 1740 | 7183 | `E875h` | 3591.5 | 174.0220 | +126 |
| 240.0 | 2400 | 5208 | `5555h` | 2604.0 | 240.0154 | +64 |
| 300.0 | 3000 | 4166 | `AAAAh` | 2083.0 | 300.0480 | +160 |

`N` and `frac` at 120.0 match RAM (`[D842]` = `28B0h`, `[D83A]` =
`AAAAh`). **PROVEN (trace).** Tick and BPM columns assume period = `N`
counts at 2 MHz (2.3).

Ratio, base 120.0: `0800h` → 60.0; `0C00h` → 90.0; `0F5Ch` → 115.2;
`10CCh` → 126.0; `1333h` → 144.0; `1800h` → 180.0.

### 13.2 Swing: `swing_pos` and midpoints (`mA`, `mB`), maximum shift

| Swing % | 1/16 pos | `mA` | `mB` | max shift | 1/8 pos | `mA` | `mB` | max shift |
|---------|----------|------|------|-----------|---------|------|------|-----------|
| 50 | 24 | 12 | 36 | 11 | 48 | 24 | 72 | 23 |
| 51 | 24 | 12 | 36 | 11 | 49 | 24 | 72 | 22 |
| 52 | 25 | 12 | 36 | 10 | 50 | 25 | 73 | 22 |
| 53 | 25 | 12 | 36 | 10 | 51 | 25 | 73 | 21 |
| 54 | 26 | 13 | 37 | 10 | 52 | 26 | 74 | 21 |
| 55 | 26 | 13 | 37 | 10 | 53 | 26 | 74 | 20 |
| 56 | 27 | 13 | 37 | 9 | 54 | 27 | 75 | 20 |
| 57 | 27 | 13 | 37 | 9 | 55 | 27 | 75 | 19 |
| 58 | 28 | 14 | 38 | 9 | 56 | 28 | 76 | 19 |
| 59 | 28 | 14 | 38 | 9 | 57 | 28 | 76 | 18 |
| 60 | 29 | 14 | 38 | 8 | 58 | 29 | 77 | 18 |
| 61 | 29 | 14 | 38 | 8 | 59 | 29 | 77 | 17 |
| 62 | 30 | 15 | 39 | 8 | 60 | 30 | 78 | 17 |
| 63 | 30 | 15 | 39 | 8 | 60 | 30 | 78 | 17 |
| 64 | 31 | 15 | 39 | 7 | 61 | 30 | 78 | 16 |
| 65 | 31 | 15 | 39 | 7 | 62 | 31 | 79 | 16 |
| 66 | 32 | 16 | 40 | 7 | 63 | 31 | 79 | 15 |
| 67 | 32 | 16 | 40 | 7 | 64 | 32 | 80 | 15 |
| 68 | 33 | 16 | 40 | 6 | 65 | 32 | 80 | 14 |
| 69 | 33 | 16 | 40 | 6 | 66 | 33 | 81 | 14 |
| 70 | 34 | 17 | 41 | 6 | 67 | 33 | 81 | 13 |
| 71 | 34 | 17 | 41 | 6 | 68 | 34 | 82 | 13 |
| 72 | 35 | 17 | 41 | 5 | 69 | 34 | 82 | 12 |
| 73 | 35 | 17 | 41 | 5 | 70 | 35 | 83 | 12 |
| 74 | 36 | 18 | 42 | 5 | 71 | 35 | 83 | 11 |
| 75 | 36 | 18 | 42 | 5 | 72 | 36 | 84 | 11 |

Swing 62 % at 1/16 gives `[89F9]` = 30 in RAM. **PROVEN (trace).**

### 13.3 Grid counters

1/16, swing 62 %, shift LATER 3: reset `phase` = 45, `mid` = 6. After 76
ticks: `phase` = 25, `mid` = 10. After 328 ticks: `phase` = 37, `mid` = 22.
**PROVEN (trace)** (`[89FD]`, `[89FB]`).

### 13.4 Per note value, swing 50 %

| Interval | Pair | Max shift | Note-repeat duration |
|----------|------|-----------|----------------------|
| 96 | 192 | 47 | 92 |
| 64 | 128 | 31 | 60 |
| 48 | 96 | 23 | 44 |
| 32 | 64 | 15 | 28 |
| 24 | 48 | 11 | 20 |
| 16 | 32 | 7 | 12 |
| 12 | 24 | 5 | 8 |
| 8 | 16 | 3 | 4 |
| 6 | 12 | 2 | 2 |
| 4 | 8 | 1 | 1 |

Intervals 96, 64, 6 and 4 exist only in Vailixi.

### 13.5 Timeline (two-bar 4/4 loop, 120.0 BPM, started with PLAY START)

Ticks after the start interrupt. **PROVEN (trace).**

| Stored position | First pass | Second pass |
|-----------------|-----------|-------------|
| 0 | 0 | 767 |
| 24 | 23 | 791 |
| 96 | 95 | 863 |
| 408 | 407 | 1175 |

Record, 1/16, 50 %, no shift: hits processed at position counter
106, 203, 300 were stored at 96, 192, 288; hits processed at
397, 494, 591, 688 were stored at 408, 504, 600, 696.
**PROVEN (trace).**

---

## 14. Vailixi 3.50 versus stock 3.12

| Item | 3.12 | 3.50 | Evidence |
|------|------|------|----------|
| Tick interrupt | `D6D9:0008`, file `0x56D98` | `D61A:000A`, file `0x561AA` | Same instruction stream apart from relocated addresses (97 % identical with addresses masked; the rest is far-call offsets and an embedded jump table) **PROVEN** |
| Tempo constant | 12 500 000 at file `0x6B138`; `EB13:000C` | file `0x6B0B2`; `EB0B:0006` | **PROVEN** |
| Tempo scale / apply | `DCC6:0008` / `DCC6:0040` (files `0x5CC68`, `0x5CCA0`) | `DC08:000E` / `DC08:0046` | **PROVEN** |
| Swing formula | file `0x4A806` | file `0x4EBCC` | Same bytes `05 19 00 BB 32 00 99 F7 FB` **PROVEN** |
| Playback task | task 2 = `EC09:000B`, file `0x6C09B` | task 2 = `EC05:0000`, file `0x6C050` | Same lock/backlog structure **PROVEN**; body not compared line by line |
| Sync divisors | `DS:0F7F` = `4, 1, 1, 4, 96` | `DS:0F5A`, same values | **PROVEN** |
| Click intervals | `DS:0F77` = `96 … 8` | `DS:0F52`, same values | **PROVEN** |
| Note values | 7 (`DS:68C8`: `1, 48, 32, 24, 16, 12, 8`), reset index 3 | 13 (`DS:6D3A`), reset index 7 | **PROVEN** |
| Swing allowed | 1/8 and 1/16 only | every value from 1/4 down | **PROVEN** |
| AMX entries | `FB00:014D` enter, `018A` leave, `04A2` wake, `03A9` post | each + `0Ah` | **PROVEN** |

Main 3.12 variable equivalents: state `[D613]`, request `[A5C3]`, `POS`
`[9045]`, run `[9041]`, `irq_count` `[D64B]`, reload `[D655]`, base tempo
`[D651]`, ratio `[D610]`, sync mode `[7FD1]`, swing `[7FE2]`, note value
`[7FE3]`, interval `[8809]`, pair `[8808]`, `swing_pos` `[880C]`, lock
`[956A]`, backlog `[F76A]`.

Sections 6–9 were read in 3.50. Apart from the rows above they have not
been re-read in 3.12. For a stock-exact implementation use the stock
note-value table and swing rule; treat the rest as **HYPOTHESIS** for 3.12
until compared.

---

## 15. Open items

### Hardware observations to record (deferred)

| Missing observation | Why it matters |
|---------------------|----------------|
| Oscillator frequency and tolerance on a board | Absolute tempo. The firmware assumes 2 MHz at the timer |
| TOUT1 period for a known `N` (scope on the tick, e.g. MIDI clock out at 120.0: 20.832 ms if period = `N`, 20.834 ms if `N + 1`) | Decides `N` versus `N + 1` (2.3) |
| Delay from tick interrupt to voice start and to first MIDI byte | Absolute latency; whether the one-tick lead compensates something |
| Pad strike to input-queue latency (panel MCU scan + link) | Real position of the record window (9.5) |
| Whether the first-tick swallow is audible/measurable on hardware as modelled | Confirms 7.3 outside the emulator |

### Not recovered

- Recorded note duration; "Move existing"; Erase; Step Edit.
- Sequence stream format beyond: delta marker `88h` with a 14-bit value
  (two 7-bit bytes), bar marker `A8h` (bar number, time signature), end
  marker `F8h`, note events with the track number in byte 1 and status
  `90h`/`98h` families (`DCF0:0006`, file `0x5CF06`). **PROVEN** as far as
  listed.
- Track mute/solo, track velocity %, program change handling in playback.
  Known: live note velocity is scaled `(vel × pct + 50) / 100`, capped at
  127 (file `0x5C420`). **PROVEN.**
- Song mode; second (simultaneous) sequence beyond its being advanced and
  played with the main one; queued sequence change details.
- Tap tempo. FPB (frames per beat) tempo display.
- SMPTE/MTC generation and chase; FSK and click input conditioning.
- The `[A7AD]` path in the playback task, and the `[A75D]` flag that
  bypasses the grid step and the record flush (7.2 step `d`).
- MIDI output pacing (UART queues) and ordering between ports.
- The mailbox depth for task 2 (create-table word `005Ah`), which sets how
  many ticks can queue before the overrun stop.

---

## 16. Routine index (3.50)

| File | `CS:IP` | Role |
|------|---------|------|
| `0x561AA` | `D61A:000A` | Tick interrupt (`IVT[9]`) |
| `0x552A8` | `D52A:0008` | 100 Hz system tick (`IVT[8]`) |
| `0x55430` | `D52A:0190` | Time stamp, 0.5 µs units |
| `0x305A7` | `B03B:01F7` | TCT1 mode, `IVT[9]` plant, first count |
| `0x6C050` | `EC05:0000` | Playback task entry (lock, backlog) |
| `0x6C093` | `EC05:0043` | `tick(state)` |
| `0x5CF06` | `DCF0:0006` | Play due events of one sequence |
| `0x5A4C8` | `DA4C:0008` | Advance bar/beat/tick and `NEXT` |
| `0x5D7F4` | `DD70:00F4` | Note-off countdown |
| `0x5C08E` | `DC08:000E` | Effective tempo |
| `0x5C0C6` | `DC08:0046` | Apply tempo → timer count |
| `0x6B0B6` | `EB0B:0006` | 12 500 000 / `T10`, 16.16 |
| `0x5DC0F` | `DDC0:000F` | Apply tempo unless slaved |
| `0x5DC31` | `DDC0:0031` | Init-time count (rounded) |
| `0x349FF` | `B3FD:0A2F` | Sequence select: ratio |
| `0x4EBCC` | `CE7A:042C` | Interval, pair, `swing_pos` |
| `0x4E9BA` | — | Shift clamp |
| `0x5A0FE` | `DA0F:000E` | Reset grid counters |
| `0x62EAC` | `E2EA:000C` | Step forward one tick (stopped) |
| `0x5DDDE` | `DDDD:000E` | Flush record holding queue |
| `0x5A1AD` | `DA1A:000D` | Drain live input |
| `0x5C2D3` | `DC2D:0003` | Live event: sound and queue |
| `0x5C897` | `DC89:0007` | Note repeat, drum track |
| `0x5C96A` | `DC96:000A` | Note repeat, MIDI track |
| `0x319CE` | `B19C:000E` | Metronome click |
| `0x5C638` | `DC5B:0088` | Send a MIDI real-time byte |
| `0x5CB6F` | `DCA2:014F` / `0154` / `0159` | Send Stop / Continue / Start (stubs; dispatcher file `0x5CA36`) |
| `0x5BCD4` | `DBCD:0004` | Incoming sync pulse |
| `0x5D9AE` | `DD9A:000E` | External sync PLL |
| `0x7B3B3` | `FB00:03B3` | AMX post message |
| `0x7B4AC` | `FB00:04AC` | AMX wake task |

---

## 17. Reproduction

Static: decode the cited offsets of the linear image with
`tools/v53_decode.py`.

Trace (needs the pinned MAME build, [`../emu/README.md`](../emu/README.md)):

```bash
python3 -m emu.seq_evidence
```

It records a two-bar sequence with pad hits at chosen phases, stops, plays
it from the start, and prints the tick period, the state changes, where
each hit was processed and when each event played.
[`../emu/lua/seq_watch.lua`](../emu/lua/seq_watch.lua) time-stamps writes
to any DGROUP word (`SEQ_WATCH=name=hexoffset,...`). Expected output on
build `d651a20c`: tick period 5208.48 µs (see 2.3), states 8 → 10 → 0 →
6 → 0, phases 10–16 and 21, 2, and the play times of 13.5.

---

## What this note does not prove

- Anything about the physical board: oscillator, timer reload edge, voice
  and MIDI latency, pad latency.
- That stock 3.12 matches sections 6–9 beyond the items compared in
  section 14.
- All-paths behaviour of the transport: the control flow of the tick
  interrupt is read in full, but the writers of the request byte and of
  the punch, wait and count-in flags are not enumerated.
- The external sync state machine beyond the PLL arithmetic and the
  timeout.
