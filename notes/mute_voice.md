# MUTE GROUPS voice backend

**Target:** Vailixi 3.50 linear image
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`;
captured application ROM
`build/hardware/2026-10-01-romapp/ROMAPP.BIN` (linear `+0x20000`).
**Date:** 2026-10-01.  **Implementation:** `mods/mute_voice.inc`.

## Result

**PROVEN (code and emulator):** raw-panel pad hits and true external MIDI input
both pass the shared far call at linear `0x4FBD3`, and all voice planes built
by that engine pass the sole stock allocator call at linear `0x507AC`.  The
first call supplies a stable program/note context; the second is reached once
per selected layer and once per stereo plane.  These two calls add
program-scoped mute groups without replacing the stock Poly, Cutoff, NOTE OFF,
voice-steal, or hardware-start logic.

**PROVEN (implemented and executed):** `mute_note_on_wrapper` resolves an event note to the
first matching pad slot, reads the incoming pad's current group, and holds the
tuple while the stock note builder runs.  `mute_voice_alloc_wrapper` stops
tagged channels from other pads in the same program whose current group now
matches, forwards the stock five-word allocator call, then tags the channel
returned in `AX`.  A hit from the same pad is left to the stock retrigger
behavior.  Every mapped ordinary trigger is tagged even while MUTE GROUPS is
disabled or its pad is Off, so enabling or editing a group applies to voices
that are still sounding.  Unmapped/audition allocations clear reused tags.

## Address frame

The relocated application executes with XA=1 and the third PGR.  Its logical
application window `0xB0000..0xF3FFF` maps to physical
`0x3B0000..0x3F3FFF`.  The table below gives linear-file, CPU, logical 20-bit,
and third-PGR physical forms.  The generic and captured images have identical
bytes at both hook sites.

| Purpose | Linear | `CS:IP` | 20-bit | third-PGR 24-bit |
|---|---:|---|---:|---:|
| shared note-on call | `0x4FBD3` | `CFB3:00A3` | `0xCFBD3` | `0x3CFBD3` |
| stock note builder | `0x4FC67` | `CFC6:0007` | `0xCFC67` | `0x3CFC67` |
| stock allocator call | `0x507AC` | `CFC6:0B4C` | `0xD07AC` | `0x3D07AC` |
| stock allocator | `0x4F372` | `CF37:0002` | `0xCF372` | `0x3CF372` |
| note-to-pad resolver | `0x59F5D` | `D9F2:003D` | `0xD9F5D` | `0x3D9F5D` |
| one-channel stop | `0x521F8` | `D21F:0008` | `0xD21F8` | `0x3D21F8` |

The selected program is `[8010:E60E]`, logical `0x8E70E`, third-PGR physical
`0x38E70E`, in the generic image.  The captured profile is `[8010:E60C]`,
logical `0x8E70C`, third-PGR physical `0x38E70C`.  The tag arrays are
CS-relative writable bytes in the F07D cave.  In the final BENCH 06 map the
wrappers are `F07D:2222` (logical `0xF29F2`, physical `0x3F29F2`) and
`F07D:22A4` (logical `0xF2A74`, physical `0x3F2A74`).  The context begins at
`F07D:2369`, and the program/pad tag arrays begin at `F07D:236D` /
`F07D:238D`, physical `0x3F2B3D` / `0x3F2B5D`.

None of the followed bodies contains `0F E0` (`BRKXA`) or `0F F0` (`RETXA`).

## Hook contracts

At `CFB3:009D`, linear `0x4FBCD`, the stock handler pushes the event segment
and offset and calls `CFC6:0007` at `0x4FBD3` (`9A 07 00 C6 CF`).  Replacing
only that call with a far call to `mute_note_on_wrapper` preserves the two-word
cdecl frame:

```
[BP+6] event offset
[BP+8] event segment
```

The event note is byte `+2`.  `D9F2:003D` scans the selected program's 64-byte
pad mapping from slot 0 upward and returns the first matching slot or `FFFF`.
Thus duplicate note mappings use a canonical first-slot group.  Whether a
front-panel event retains a separate physical-pad identity before this shared
event is **UNDETERMINED** at the panel/TE7774 boundary.

At `CFC6:0B2D`, linear `0x5078D`, the helper takes the allocation lock, pushes
five words, and calls `CF37:0002` at `0x507AC`
(`9A 02 00 37 CF`).  Replacing only that call with a far call to
`mute_voice_alloc_wrapper` preserves this cdecl frame:

```
[BP+06] Poly enum
[BP+08] owner/source note
[BP+0A] Cutoff note 1
[BP+0C] Cutoff note 2
[BP+0E] channel excluded from voice stealing
```

The wrapper forwards all five words unchanged and returns the stock channel
in `AX`.  Both wrappers preserve `SI`, `DI`, `BP`, and `DS`.

## Stock behavior retained

**PROVEN:** program-note byte `+6` is `Poly:`: `0=POLY`, `1=MONO`, and
`2=NOTE OFF`.  Bytes `+7` and `+8` are the two `Cutoff:` notes, with `0x22`
as Off and `0x23..0x62` as pad notes.

`CF37:0002`, linear `[0x4F372,0x4F555)`, scans the stock 32-byte channel-owner
array.  MONO stops channels owned by the incoming source note.  Each active
Cutoff value independently stops channels owned by that note.  It then finds
a free channel or chooses a victim.  The wrapper calls this routine rather
than copying it.

`CFC6:0007` can invoke the builder for a base record and SIMULT records at
note `+3` and `+5`.  Each selected layer may invoke `CFC6:0B2D` once or twice
for mono/stereo samples.  The wrapper context deliberately remains the
triggering canonical pad for every such allocation, so one pad's layers and
planes do not mute one another.

For stereo, stock code changes MONO to POLY before the second allocation so
the first plane survives the MONO scan.  Cutoff scans still run for both
planes.  Both channels receive the same stock owner note.  MUTE GROUPS adds
no exception to those stock rules.

`CFB3:0008`, linear `0x4FB38`, handles note-off events.  When record `+6` is
NOTE OFF it reaches `CFB3:0110`, linear `[0x4FC40,0x4FC67)`, which stops all
32 channels matching the note owner.  MUTE GROUPS does not intercept this
path.

## Tags, stops, and lifetime

The backend maintains two parallel 32-byte arrays.  A nonzero program tag
encodes `program+1` (`1..24`); the second byte identifies the canonical pad.
For an enabled incoming pad in group 1..4, the scan selects tags from the same
program whose pad differs, calls `mute_get_group` for each candidate pad, and
stops only current group matches.  It clears each selected tag before passing
the channel to `D21F:0008`, which prevents a repeated stop if execution is
re-entered.  Keeping group membership in the program table rather than in the
voice tag makes Enable and group edits effective for already-sounding voices.

**PROVEN:** `D21F:0008`, linear `[0x521F8,0x5227F)`, is the stock one-channel
stop primitive.  It performs the port `0x60/0x62/0x64` writes and clears the
stock owner byte plus three per-channel words.  Another stock caller passes
all channel numbers `0..31`, so that range is valid even without first testing
the owner byte.  The allocator's existing outer lock already encloses stock
MONO/Cutoff calls to this same stop routine, establishing that the wrapper's
placement does not introduce a new lock ordering.

The L7A1045 interpretation that register-3 zero clears the physical key is
**HYPOTHESIS** from MAME.  Actual chip behavior is **UNDETERMINED / U-PHYS**
until a hardware observation is made.

Natural stock stops do not clear the mod tag.  This is safe for the established
engine because every later allocation through the sole `CF37:0002` call
overwrites or clears the returned channel's tag.  A stale tag may cause one
extra safe stop before it is cleared.  Alias-complete proof for every possible
hardware-start path remains **UNDETERMINED**; a path that reuses a channel
without the shared allocator would need another tag writer.

`mute_forget_program(AL)` is the near callback used before initialization or
copy-overwrite of a program record.  It invalidates tags for that program
without stopping sounding channels.  It preserves `SI`, `DI`, `BP`, and `DS`.

## Re-entry and task boundary

The note wrapper saves the previous four-byte context on its own stack before
installing a new one and restores it after the stock builder returns.  A
nested note-on therefore cannot erase an outer layer/stereo context.

The reached raw-panel event path enqueues work; the shared `CFB3` handler runs
from the event-processing task.  A separate MAME `mdin` (`-midiin1`) execution
also reached the same wrappers.  Allocation and stopping use the stock locking
path.  Concurrent UI mutation of the mod-owned program table has not been
observed and remains a cooperative-task scheduling boundary rather than an
all-paths atomicity claim.

The sequencer's per-track program dispatch was not executed by this suite.
The wrapper captures `[8010:E60E]` (captured profile `[8010:E60C]`) before it
calls `CFC6:0007`; the inspected `CFC6` body therefore cannot repair an
incorrect program already captured by the wrapper.  Whether every sequencer
caller has placed its per-track program in that selected-program byte before
entering `CFB3` is **UNDETERMINED**.  This is the named boundary on extending
the panel/external-MIDI result to all sequencer playback paths.

## Validation

**PROVEN:** the include assembles as 16-bit `cpu 186` code in both generic and
`WAVE_CAPTURE_20261001` profiles.  The isolated harness confirms the only
profile-dependent opcode is the selected-program read (`A0 0E E6` versus
`A0 0C E6`).  Final integration patches the two five-byte calls to
`9A 22 22 7D F0` and `9A A4 22 7D F0`; `build/mods/WAVEHW.json` verifies the
stock bytes and replacements.

**PROVEN (emulator):** `emu/test_mute_voice.py` loads native PGM/SND files and
uses read-only Lua taps; it does not inject MPC RAM.  Its 12 cases cover:

- disabled, Off, different-group, same-pad, duplicate-note-alias, and live
  Enable/group-edit behavior;
- mono, stereo, and SIMULT-layer allocations;
- retained stock NOTE OFF and Cutoff stops;
- raw-panel hits and true external MIDI on MAME `mdin` (`-midiin1`), while
  panel control remains on the separate `panel` port (`-midiin3`);
- program isolation by copying Program 1 to Program 2 through the stock menu,
  starting a Program 2 voice, selecting Program 1 through MUTE GROUPS, and
  starting another grouped pad without a custom stop.

The mono fixture is 264,600 frames (six seconds at 44.1 kHz), so the first
voice in the late live-edit and program-isolation cases is still active at the
second hit.  The live-edit case requires its `D21F:001C` stop after 78.49 s and
before the second key-on.  The isolation case requires no stop of its first
channel between key-ons and observes distinct program tags 2 then 1.  The
frozen result is `build/wavebench06-mute-voice-tests.log`, pinned to
`build/mods/WAVEHW.SYS` SHA-256
`39473bfb19b337e7a38c0eb9394520acdecabb50d668531ed5b727a5328ab360`.

The L7A1045 register interpretation, physical panel behavior, and equivalent
audio result on real hardware remain **UNDETERMINED / U-PHYS**.  The missing
observation is a bench capture showing both planes/layers key off for one
group hit while other groups and programs continue sounding.
