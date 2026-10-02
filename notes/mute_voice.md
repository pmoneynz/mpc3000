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
tuple in its own stack frame while the stock note builder runs.
`mute_voice_alloc_wrapper` finds that frame through the stock BP chain, stops
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
wrappers were `F07D:2222` and `F07D:22A4`.  After the frame-context change
(2026-10-01, both profiles, before any merge with other cave edits) they are
`F07D:2222` (logical `0xF29F2`, physical `0x3F29F2`) and `F07D:227C` (logical
`0xF2A4C`, physical `0x3F2A4C`); the note-on return signature
`mute_note_on_wrapper.builder_return` is `F07D:227A`.  The observer mirror
`mute_context_*` begins at `F07D:2366`, and the program/pad tag arrays begin at
`F07D:236A` / `F07D:238A`, physical `0x3F2B3A` / `0x3F2B5A`.  The emitted
`build/mods/wavehw.cave.map` / `wave.cave.map` are authoritative for offsets.

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

## Trigger context and task boundary

### Stock facts

**PROVEN (bytes, both profiles):** `CFC6:0B2D`, linear `0x5078D`, takes AMX
resource 1 before the hooked allocator call: `CALLF D1F7:0126` at `CFC6:0B30`
(linear `0x50790`) is `MOV DX,1` / `CALLF FB81:0089` (generic linear
`0x7B899`; captured `FB80:008F`, the same linear address minus `0xA`).
`FB81:0089` gets the current task index with `CALLF FB00:0552`; if the
resource is owned by a different task (`CMP AL,[DI+2]`) it queues the caller
(`FB00:06B9`) and suspends it with `CALLF FB00:0469` (`01CF`, `AX=4`).  The
release is `CALLF D1F7:012F` at `CFC6:0C3F` (linear `0x5089F`), which reaches
`FB81:00C7` and wakes a waiter (`FB00:06E8` / `04AC` / `038A`).  The stock
allocator call at `CFC6:0B4C` therefore runs inside the resource, and the
call path from the note-on hook to it can block.

`FB00:0552`, linear `0x7B552` (`BIOS.BIN` offset `0x3552`, 20-bit `0xFB552`,
24-bit `0x0FB552` with page 62 frame `0x3E`), is
`PUSH DS / PUSH DI / LDS DI,CS:[0042] / MOV AX,[DI+0Ch] / POP DI / POP DS /
RETF`: `AX` only, flags and interrupt state untouched.  In the captured BIOS
the identical routine is `FB00:0548` (`BIOS.BIN` offset `0x3548`) with
`LDS DI,CS:[0038]`; captured `CS:[0038]` and generic `CS:[0042]` both hold
`A850:0024`, and the captured reserve/release call it from linear `0x7B894` /
`0x7B8D2`, exactly `0xA` below the generic `0x7B89E` / `0x7B8DC`.  The mod does
not call it (see design choice below).

**PROVEN:** AMX can switch tasks at interrupt exit: `FB00:0194` calls `01CF`
with `AX=2` when a ready task with a lower index than the running one exists
([amx_public_api.md](amx_public_api.md)).

### Which tasks reach `CFB3:0008`

`CFB3:0008`, linear `0x4FB38`, contains the hooked call.  It has exactly three
`9A` far callers in both images; no other far encoding or stored far pointer
to it exists.

| Call | `CS:IP` | Containing routine | Task |
|---|---|---|---|
| `0x6AD64` | `EAD0:0059` | `EAD0:000B` (linear `0x6AD0B`), AMX create record 3 (`FB76:0038`, linear `0x7B798`; captured `0x7B78E`) | **PROVEN** task 3: the record is the only reference to `EAD0:000B`.  It builds a `0x90` note-on for note `[E614]` (captured `[E612]`) and calls `CFB3:0008` |
| `0x5D8D3` | `DD8A:0033` (= `DCF0:09D3`) | event pump `DD8A:000E` (linear `0x5D8AE`): `CALLF D8BC:001C` / `CALLF CFB3:0008` until empty, unless `[9644]` (captured `[9642]`) is nonzero | **UNDETERMINED**: eight far callers (linear `0x4CA38`, `0x4CBFC`, `0x5A23D`, `0x5ACDB`, `0x5AEA3`, `0x6C240`, `0x6C25F`, `0x6C2B4`) were not attributed to tasks |
| `0x5AF18` | `DA8C:0658` | near routine `DA8C:0639` (linear `0x5AEF9`): MIDI-out via `DC3A:000A` when `[98DB]` (captured `[98D9]`) is nonzero, else local `CFB3:0008` | **UNDETERMINED**: no near `CALL` to `0639` in its segment was found; its caller is not established |

Task 3 is readied by `0396` with `DL=3` at linear `0x56112`; that this is at
interrupt level is **HYPOTHESIS**.  Consequently the former statement that the
shared handler runs only from one event-processing task is **retracted**: at
least task 3 and the pump's task(s) reach it, and whether those are the same
task is **UNDETERMINED**.  The 2026-10-01 design below does not depend on the
answer.

### Design: context on the trigger's own stack

The former CS-global context was live across the blocking reserve.  An Edit
Sound audition (`CFC6:0CE9` -> `039E` -> `0B2D`, not via the note-on hook)
could hold resource 1 inside the allocator while a higher-priority task
entered the note-on hook, installed a valid context, and blocked; the
audition then tagged its voice with that task's program/pad.  Non-LIFO
interleaving of two note-on tasks could also restore a stale valid context
permanently.

**PROVEN (implementation, both profiles):** `mute_note_on_wrapper` now keeps
`valid, program, pad, group` at `[BP-4..BP-1]` of its own frame and writes no
global.  `mute_voice_alloc_wrapper` follows exactly three saved-BP links and
accepts the context only if the third frame's return address is
`mute_note_on_wrapper.builder_return` in the wrapper's own `CS`:

| Frame | Prologue | Calls toward the allocator (return IP) | Body, linear |
|---|---|---|---|
| `CFC6:0007` | `55 8B EC` | `039E` at `01F0`, `0263`, `02CC` (`01F3`, `0266`, `02CF`): base record and both SIMULT records | `[0x4FC67, 0x4FF36)` |
| `CFC6:039E` | `55 8B EC` | `0B2D` at `0A8A`, `0AEC`, `0B16` (`0A8D`, `0AEF`, `0B19`): the mono and stereo-plane arms | `[0x4FFFE, 0x50785)`, table `[0x50785, 0x5078D)` |
| `CFC6:0B2D` | `55 8B EC` | hooked `CF37:0002` at `0B4C` | `[0x5078D, 0x508A6)` |

All three bodies were decoded in both images; every branch target, including
the four-entry `JMP CS:[BX+0B25]` table (`046E`, `0481`, `0494`, `04A2`), is an
instruction boundary; `BP` is written only by those prologues and by
`LEAVE`/`POP BP` before `RETF`; no `SS`/`SP` load occurs.  The two WAVE
patches inside `039E` (`CFC6:069D`, linear `0x502FD`, to `audition_duration`;
`CFC6:0897`, linear `0x504F7`, to `audition_ticks`) write no `BP`, balance
their near call, and return to `CFC6:06A3`, `089E`, or the `039E` epilogue at
`0B21`, so the patched bodies keep the same chain.  The only callers of
`0007` are the hooked call and `CFC6:0C68`; of `039E` the three above plus
`CFC6:0CE1` and `CFC6:0D6D` (Edit Sound); of `0B2D` the three above.  The
captured bodies differ only in DGROUP displacements (`-2`), so frame shape,
call sites, and return IPs are identical.  Every allocation reached through
the note-on hook is therefore exactly three frames deep; `0C68`, `0CE1`,
`0CE9` (stock or WAVE caller) resolve "no trigger" and clear the channel's tag.
Only our wrapper pushes `F07D:227A`, so a WAVE audition (third frame returns
to `F07D:audition.return_from_stock`) does not match.

The alternative—recording the AMX task index from `FB00:0552` with a per-task
context—was not chosen: it costs two BIOS far calls per note-on/allocation,
needs a per-profile BIOS address, and still needs an index bound for code
interrupted at the idle slot.  The frame design has no new stock or BIOS call
target.

**What is protected.** The trigger context belongs to one stack; task
switches, blocking in the reserve, and nested note-ons cannot exchange or
restore it.  The allocation wrapper's scan and tag writes run inside resource
1, so two tasks cannot interleave them.  **Not protected:** the note-on
wrapper's reads of the selected program and storage table (single-byte reads;
a concurrent UI edit is seen either before or after); `mute_forget_program`
from the UI task is not inside resource 1, so it can clear a tag the
allocator has already selected (that channel is still stopped) or precede a
new tag for the reinitialized program (one possible extra safe stop later).
An interrupt-level caller of `0B2D` would pass the owner test as the
interrupted task; none is established.  `mute_context_*` is now a write-only
mirror of the last allocation's resolved context for emulator observers; no
code reads it.

**Cost.** Per note-on: three register instructions replace seven
CS-memory pushes/stores/pops and `ADD SP,4` (net four fewer), no added call.
Per allocation: up to 17 added instructions (two clears, six SS loads,
`MOV CX,CS`, two compare/branch pairs, two pushes, two mirror stores), no added call; four more bytes of
stack under `0B2D`.

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
`A0 0C E6`).  BENCH 06 patched the two five-byte calls to
`9A 22 22 7D F0` and `9A A4 22 7D F0`; the frame-context build patches
`9A 22 22 7D F0` and `9A 7C 22 7D F0` (map-derived; the builder verifies the
stock bytes and replacements).

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

**PROVEN (emulator, 2026-10-01 frame-context build):** `emu.test_mute_voice`
(12) and `emu.test_mute_ui` (7) pass unchanged, which exercises the walk on
the base, SIMULT-layer, stereo-plane, panel and external-MIDI paths.
`emu/test_mute_audition.py` (2) starts an audition first—stock Edit Sound
Ply/Stp and the WAVE view's Ply/Stp, whose `CFC6:0CE9` caller is in `F07D`—then
hits two pads of group 1 while it sounds.  The audition's allocation writes a
zero tag on its channel and the mirror reads `valid=0`; both pads are tagged
Program 1 with their own pads; the second pad stops exactly the first pad's
channel and nothing stops the audition channel.

**UNDETERMINED (not provoked):** the cross-task interleaving itself.  It needs
a pad/MIDI note-on in a higher-priority task to become ready while another
task is between the reserve at `CFC6:0B30` and the allocator's return—a window
of a few microseconds—and no real-input sequence that forces it
deterministically in MAME was found.  The new test is a single-task
regression; it is not expected to distinguish the old global context.  The
missing observation is an execution in which the AMX current-task byte
`[A850:0030]` (header `+0Ch`, physical `0x3A8530` under the second PGR)
differs between a note-on wrapper entry and an allocation inside it.

The L7A1045 register interpretation, physical panel behavior, and equivalent
audio result on real hardware remain **UNDETERMINED / U-PHYS**.  The missing
observation is a bench capture showing both planes/layers key off for one
group hit while other groups and programs continue sounding.
