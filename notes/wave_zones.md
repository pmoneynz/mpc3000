# Waveform ZONE editor

**Target:** Vailixi OS 3.50 linear image
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Updated:** 2026-10-01.
**Implementation:** [`../mods/wave.asm`](../mods/wave.asm) and
[`../mods/wave_zones.inc`](../mods/wave_zones.inc).

## Behavioral contract

The editor keeps 17 shared dword boundaries for at most 16 zones.  For a
one-based current zone `z`, its displayed range is
`[boundary[z-1], boundary[z]]`.  Editing an interior start therefore also
changes the preceding zone's end; editing an interior end also changes the
following zone's start.  **PROVEN** by the implementation and bounded state
transitions and the MAME cases in `emu/test_wave_zones.py`. Physical-panel
execution remains **UNDETERMINED**.

The initial state is 16 zones, current zone 1.  For sound length `L` and
zone count `N`, rebuilding the map sets:

```
boundary[i] = floor(L * i / N),  i = 0..N
```

Thus the first boundary is zero and the last is exactly `L`, including when
`L` is not divisible by `N`.  Changing the current zone only loads another
adjacent pair.  Changing the total count rebuilds every boundary and resets
manual edits.  Zero-length zones are possible when `L < N`.  The assembly
uses a quotient/remainder accumulator, so the multiply cannot overflow and
lengths above 16 bits retain their remainder distribution.  **PROVEN** by
code for all admitted lengths; 55,125 and 65,911-frame MAME cases check
these divisions in execution.

The domain is the whole MPC3000 sound, `0..record[+1C/+1E]`; Soft Start and
Soft End do not define the division.  This follows the MPC2000XL divider and
slice domain established in
[`sample_structures.md`](</Users/peterwadams/Documents/2kxl/notes/sample_structures.md>)
and
[`slice_sound.md`](</Users/peterwadams/Documents/2kxl/lazy_chop/research/slice_sound.md>).
That source contract is **PROVEN** for the XL code.  Its use here is an
intentional porting choice and is **PROVEN** by the MPC3000 implementation.

The graphical adaptation adds `ZONE:current/total` at the upper right.
Left/Right traverse Start, End, stereo View when present, current zone, and
total count.  The data wheel or `+`/`-` changes the focused value.  Switching
Trim/Zone focus inside one open graphical view preserves boundary edits;
only a total-count change redivides them.  This differs from treating every
focus toggle as a fresh XL ZONE-page entry and is intentional because the
MPC3000 combines both pairs on one screen.

The stock normalized-key reader coalesces consecutive identical queue keys.
At generic `D6E0:001B` it writes their count to `8010:D69A`; the captured
profile uses `8010:D698`.  WAVE snapshots that word immediately after
`BDE3:000E` returns.  Zone-current and zone-count adjustment applies the
whole snapshot, clamps at its existing bounds, then loads or redivides once.
Thus a wheel batch that fits the stock key queue does not lose steps or
redraw every intermediate state.  **PROVEN** by the stock producer/consumer
code and implementation; `emu/test_harness_bursts.py`, `emu/test_wave_zones.py`
and `emu/test_mute_ui.py` send bursts 1 ms apart and check the coalesced
counts in execution.  The bound is the queue: it holds 8 keys (capacity word
of `8010:12BC`, captured `8010:12BA`), so while one redraw is in progress at
most 1 + 8 events survive and stock code drops the rest.  A 20-event burst
applies 9 steps (`test_burst_beyond_queue_capacity`, both profiles).  The
earlier unbounded claim is retracted.  Whether the physical dial can deliver
more than 8 events inside one redraw is **UNDETERMINED** (`U-PANEL-ROM`).
Point motion similarly multiplies its 32-bit base step by the repeat count,
saturating at source length before signed movement clamps the endpoint.

## Bounds and storage

The zone state lives in the relocated WAVE cave, not in unowned DGROUP RAM:

- `zones_count` is constrained to `1..16`;
- `zones_current` is constrained to `1..zones_count`;
- `zones_bounds` contains 17 dwords, so the largest accessed pair is
  elements 15 and 16;
- a start is clamped between the previous boundary (or zero) and its end;
- an end is clamped between its start and the next boundary (or sound
  length).

The active pair is mirrored to the stock Edit Sound globals
`8010:EDBB`/`EDB7` in generic 3.50 and `8010:EDB9`/`EDB5` in the captured
personalized profile.  On a deliberate return from the graphical view, the
stock page may edit those two globals.  Reopening the view imports the pair
atomically between its two outer neighbors and writes the clamped result
back to both the shared map and the stock globals.  **PROVEN** by code;
equivalent physical-panel numeric edits remain **UNDETERMINED**.

## State lifetime and source identity

Record slot, name, channel flag, length, and wave base are useful sanity
checks, but they cannot prove object identity: a Disk workflow can unload and
reload a different sound with identical values.  `zones_valid` therefore has
a session lifetime rather than a metadata lifetime.

Every stock Edit Sound invocation clears the map at the `B99A:0002` entry
hook.  The sole ordinary exception is the re-entry requested by waveform
Help/Exit.  `zones_reopen` places option `6` at the **front** of the stock key
queue and sets a one-shot `zones_resume` byte only if that insertion succeeds;
the next Edit Sound entry consumes the byte and arms a second one-shot selector.
After the stock list builder sorts the current Sound records, the selector
scans `SS:[BP-0xBC]` for `zones_source` and writes its new list position to
`[BP-2]`.  This keeps the same Sound selected when CHOP ZONE inserted names
which sort before it.  A found position is also stored to the word global
`8010:E40A` (capture `E408`) in stock's `cbw` form, as `B99A:04E9` does;
positions are `0..127`, so the zero-extended index is identical.  The stock
`cmp [E40A],di / jl` at `B99A:006B` (linear `0x39A0B`) that follows the
rejoin therefore keeps the resolved position (always below the count `DI`),
instead of zeroing it when a stale global is at or above the count, and the
next fresh Edit Sound entry restores the same Sound.  A missed scan or an
ordinary entry leaves the global untouched, as stock does.  The
choice-10 handler stores it the same way after its list rebuild.  The front
insertion matters:
`D6E0:0075` appends to the FIFO, so an older queued mode key could otherwise
run first and leave the resume byte alive across a Disk reload.  If the queue
is full, the helper clears both resume and validity and safely loses the map.

Every commit of field 0 (sound selection) also invalidates the map.  This is
required even for A -> B -> A within one page invocation: the stock zone
globals are shared and may have been clamped for B, so importing them after
returning to A would corrupt A's retained boundaries.  The next graphical
entry creates a fresh equal division.

Stock `DO IT` operations must invalidate before dispatch because they can
mutate or replace the selected sound without changing all cached identity
bytes.  `CHOP ZONE` may retain the map only while its executor guarantees
that the source descriptor and sample data remain unchanged.  If that
executor causes a fresh Edit Sound invocation, it must use the same one-shot
resume path.  A `CHOP ZONE` refused by the stock safe lock touches nothing
and keeps the map.  This is the required integration contract; the chop
backend is documented separately.

Replacement of the active descriptor by an asynchronous external writer
while the same Edit Sound invocation remains open is **UNDETERMINED**.  No
such writer is established in the recovered software path.  A physical or
external-interface observation is still required before making an all-paths
claim.

## Hook and queue evidence

The addresses below use the interleaved linear file.  The generic route uses
XA=1 with the second PGR; slot 46 contains word `0x002E` at file `0x7AD10`.
The capture-specific WAVE route uses XA=1 with the third PGR, hence the
`0x3xxxxx` forms.  The cave itself runs at `F07D:0000`, file `0x707D0`,
20-bit `0xF07D0`, 24-bit `0x3F07D0` under that third table.

| Surface | Linear file | `CS:IP` | 20-bit | 24-bit, generic / capture | Evidence |
|---|---:|---:|---:|---:|---|
| Edit Sound entry | `0x399A2` | `B99A:0002` | `0xB99A2` | `0x0B99A2` / `0x3B99A2` | Seven replaced bytes are `55 8B EC 81 EC C0 02`; identical in the target and captured APP. The hook reproduces `PUSH BP; MOV BP,SP; SUB SP,2C0h` and resumes at `0009`. **PROVEN** |
| Sorted-list selection | `0x39A03` | `B99A:0063` | `0xB9A03` | `0x0B9A03` / `0x3B9A03` | Runs immediately after `B99A:27F2` returns the Sound count and builds the record-index list at `SS:[BP-BC]`. Replaced generic bytes are `8B F8 A0 0A E4 88 46 FE`; the capture differs only in its shifted selector global, `E408`. The hook preserves the stock `DI=AX` result, resolves `zones_source` only for a one-shot waveform re-entry, stores the sorted position at `[BP-2]` and, when found, as the word `[E40A]`/`[E408]`, and resumes at `006B`. **PROVEN** |
| Sound-field commit | `0x39E7B` | `B99A:04DB` | `0xB9E7B` | `0x0B9E7B` / `0x3B9E7B` | Field-dispatch table word 0 selects `04DB`. Replaced bytes `83 FF FF 75 03 E9 4B 03` are identical in both inputs. The hook preserves the original `DI==-1` exits after invalidating. **PROVEN** |
| Help/page key | `0x3A1FA` | `B99A:085A` | `0xBA1FA` | `0x0BA1FA` / `0x3BA1FA` | Existing WAVE key hook. **PROVEN** |
| Stock Do dispatch | `0x3A493` | `B99A:0AF3` | `0xBA493` | `0x0BA493` / `0x3BA493` | Clears `[BP-1]`, then dispatches the selected Do action. **PROVEN** |
| Page loop/exit | `0x3AF35` | `B99A:1595` | `0xBAF35` | `0x0BAF35` / `0x3BAF35` | Zero key loops to `082E`; nonzero key enters the mode dispatcher and returns. **PROVEN** |

Generic `D6E0:0075` at file `0x56E75`, `D6E0:0075`, 20-bit
`0xD6E75`, calls `FB00:067C` with queue `8010:12BC`; this is FIFO append.
Generic `FB00:06B9` at file `0x7B6B9`, 20-bit `0xFB6B9`, is the push-front
operation used by `D6E0:008B` to restore the next key after a peek.  Under
XA=1, PGR slots 53 and 62 select those pages; the third-table capture forms
are `0x3D6E75` and `0x3FB6B9`.

The captured profile shifts the queue to `8010:12BA`, and its byte-identical
queue algorithm begins ten bytes earlier: append `FB00:0672`, push-front
`FB00:06AF`, pop `FB00:071B`.  These offsets are **PROVEN** from the
hash-pinned APP and high-BIOS captures.  Queue push-front returns `-1` when
already full, `0` on ordinary success, and `1` when the insertion fills the
last slot; `zones_reopen` accepts both nonnegative results and preserves all
caller registers and flags.

Generic `BDE3:00BD` at file `0x3DEED`, 20-bit `0xBDEED`, pushes
`DS:D69A` and calls `D6E0:001B`; under XA=1 this is `0x0BDEED` through the
second PGR.  The captured third-PGR instruction at 24-bit `0x3BDEED` pushes
`D698`.  `D6E0:001B` starts the count at one, removes consecutive copies of
the same key under `CLI`, increments the count for each copy, restores the
first different key at the queue head, and writes the count through the far
pointer supplied by `BDE3`.  Generic `B31B:0054` at linear file `0x33204`,
20-bit `0xB3204`, 24-bit `0x0B3204` loads `DI=[D69A]`; the captured code at
24-bit `0x3B3204` loads `[D698]`.  Its `+`/`-` paths add or subtract `DI`,
after multiplying it by ten when the numeric field's flag bit 4 is set.
This proves that the word is the normalized-key repeat count for physical
buttons and wheel-derived `+`/`-`, rather than a wheel-only hint. **PROVEN**.

## BENCH 06 vertical navigation

From either End point, Up selects the current `ZONE:01/04` number directly.
Down from either the current-zone or zone-count field returns directly to End.
This shortcut also works in Fine and stereo views, skipping the View field.
When typing an End time, Up accepts the current numeric component and opens
the zone selector; idle Up preserves the exact frame value, including values
whose displayed sample component is rounded by the stock numeric editor.
Up/Down on Start retains zoom control. Left/Right navigation is unchanged.
Implementation: `view.up`/`view.down` in `mods/wave.asm` and `stock_numeric.zone`
in `mods/wave_numeric.inc`; both execute in the relocated F07D cave, XA=1,
third PGR. Exact linear and physical offsets follow the final cave map as
`0x707D0 + offset` / `0x3F07D0 + offset`.

**PROVEN (final-candidate emulator executions):** five direct-navigation tests
pass on mono, stereo Fine, and generic profiles. Typed End Up retains the
untouched sample component, and idle End Up preserves frame 44,099 exactly.
Log: `build/wavebench06-navigation-ui-tests.log` (14 tests including mute UI
and lifecycle); implementation payload SHA-256
`39473bfb19b337e7a38c0eb9394520acdecabb50d668531ed5b727a5328ab360`.
