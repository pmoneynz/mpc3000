# WAVE stock audition and pad-input boundary

This note records the stock machinery available to the WAVE view.  It covers
the repository Vailixi 3.50 LS/MS interleave and the hash-pinned personalized
capture used by `WAVE_CAPTURE_20261001`.

## Address mode

All application-code addresses below are for XA=1 with the third PGR active,
the mode used by the relocated application and WAVE.  In that mode application
20-bit addresses `0xB0000-0xF3FFF` map to 24-bit
`0x3B0000-0x3F3FFF`.  Linear-file offsets name bytes in the interleaved
512 KiB image; they do not name either chip file by itself.

The sound workspace is RAM.  Record `index` starts at
`A2AE:4800 + index*0x24`: 20-bit base `0xA72E0`, 24-bit base
`0x3A72E0` under the same third-PGR mapping.  There is no linear ROM-file
offset for a live record.

## Stock playback entries

| Entry | Linear file | 20-bit | 24-bit | Established behavior |
|---|---:|---:|---:|---|
| `CFC6:0CE9` | `0x50949` | `0xD0949` | `0x3D0949` | Start the sound whose zero-based index is the one word stack argument |
| `CFC6:0D75` | `0x509D5` | `0xD09D5` | `0x3D09D5` | Return zero when all 32 voice-state words are zero, otherwise the one-based first active slot |
| `CFC6:0D93` | `0x509F3` | `0xD09F3` | `0x3D09F3` | Call `D21F:0008` for every channel `0..31` |

**PROVEN:** `CFC6:0CE9` spans linear file
`[0x50949,0x509D5)` and is byte-identical in the generic interleave and
physical capture.  It multiplies the argument by `0x24`, reads the sound
record's start dword at `+14/+16` and end dword at `+18/+1A`, and returns
without starting when start is not below end.  The high-word comparison is
signed and the equal-high low-word comparison is unsigned.  It then builds
the stock playback objects and starts the voice.  The caller removes the
one-word argument.

Treat `AX`, `BX`, `CX`, `DX`, `ES`, and flags as clobbered.  `DS` remains the
application DGROUP.  The stock wrapper `B99A:1612` keeps the sound index in
`DI` across this call, establishing the compiler ABI expectation that `DI`
is preserved, but WAVE need not depend on it because its saved state is
CS-relative.

**PROVEN:** `CFC6:0D93` spans `[0x509F3,0x50A07)` and is also byte-identical.
It is a global stop-all operation, not an audition-owned stop.

**PROVEN:** `CFC6:0D75` has the same entry and ABI in both images, but its
embedded DGROUP offsets differ because the physical customer's DGROUP is two
bytes shorter:

- Generic: scan 32 words `DS:E450..E48E`; terminator `E490`.
- Physical capture: scan 32 words `DS:E44E..E48C`; terminator `E48E`.

The routine owns those profile-specific offsets internally.  Common WAVE
source can call `CFC6:0D75`; it must not reproduce either operand.

## Stock callers and exact-range use

**PROVEN:** the stock Edit Sound `Ply/Stp` handler starts at `B99A:0875`,
linear file `0x3A215`, 20-bit `0xBA215`, 24-bit `0x3BA215`.  It clears the
page key, calls `CFC6:0D75`, calls global `CFC6:0D93` when any voice is active,
and otherwise calls `CFC6:0CE9` for the selected sound.  It then leaves the
page dispatch.  This establishes the toggle behavior and also establishes
that the stock stop affects unrelated active voices.

**PROVEN:** `B99A:1612`, linear file `0x3AFB2`, 20-bit `0xBAFB2`, 24-bit
`0x3BAFB2`, temporarily increases record end by `0x557` frames, clamps it to
record length, calls `CFC6:0CE9`, reloads `ES=A2AE`, recomputes the record
pointer, restores the original end dword, and returns.  It does this without
disabling interrupts.  This is stock precedent for a synchronous temporary
record-bound change, but its extra tail is unsuitable for exact WAVE range
audition.

**PROVEN for the bounds presented to the stock player:** WAVE can use the
same stock entry while temporarily replacing both boundary dwords:

1. Reject unless unsigned `0 <= start < end <= record_length`.
2. Save all four words at record `+14`, `+16`, `+18`, and `+1A` outside
   registers that the far call may clobber.
3. Write the selected Trim or Zone start/end pair.
4. Push the zero-extended sound-index word, call `CFC6:0CE9`, and remove the
   argument.
5. Reload `ES=A2AE` and the record offset, then restore all four saved words
   before any other exit.

`mods/wave_playback.inc` follows this sequence with CS-relative saved values,
so `ES` or `DI` clobber cannot redirect restoration.  There is no early exit
between mutation and restoration.  This establishes the requested bounds at
`CFC6:0CE9`; it does **not** establish that every requested frame is audible.
`CFC6:0CE9` itself reads all four bound words only when the start and end high
words are equal: its signed high-word compare at `CFC6:0D13..0D21` skips the
end's low word otherwise (observed with start 88,200 and end 200,000 in
`emu/test_harness_long.py`).  The player `CFC6:039E` reads the full bounds.
The rejected-candidate evidence below disproves that stronger claim for the
unmodified stock duration path.

**UNDETERMINED:** an interrupt can observe the temporary record bounds while
the stock player runs.  The stock `B99A:1612` pattern establishes that the OS
itself accepts that exposure for its Play-X path; it does not prove that no
interrupt-time consumer exists on every hardware path.

## Rejected candidate: early cutoff

The initial exact-bounds implementation exposed a stock timing behavior that
made short windows unusable.  In the superseded payload with SHA-256
`5b01d73a48a5527506cc6ec40345330bd0229ac5e33b066c7ad6211d34fcfee7`,
1,800-, 1,920-, and 2,048-frame requests reached `D21F` almost immediately.
Requests of 2,500, 2,944, 3,500, and 4,096 frames lasted approximately 10,
20, 30, and 50 ms.  The 1,920-frame Fine WAVs contained only 16 and 17
nonzero main-output samples.  This established that correct bounds and start
addresses alone did not provide usable short audition.

**PROVEN (static software):** `CFC6:069D`, linear file `0x502FD`, 20-bit
`0xD02FD`, 24-bit `0x3D02FD`, subtracts 30 ms in the stock duration path.
`CFC6:0897`, file `0x504F7`, 20-bit `0xD04F7`, 24-bit `0x3D04F7`, stores and
tests the pitch-adjusted, floored natural-stop tick count.

The earlier approximately 2,048-frame threshold was an empirical description
of that rejected trace, not the implementation.  Static recovery establishes
the 30 ms subtraction followed by 10 ms tick flooring; use those operations
when reasoning about the stock path.

## Accepted emulator candidate: scoped duration hooks

The current implementation replaces those two instruction sequences with
far jumps to WAVE code.  Each hook walks the live stack and changes behavior
only for this exact chain:

`CFC6:039E <- CFC6:0D70 (CE9) <- F07D:audition.return_from_stock`.

For that chain, the first hook skips the stock 30 ms subtraction and the
second rejects a result below two 10 ms ticks before a voice is allocated.
Every unmatched path executes the original `SUB/SBB` or `MOV/CMP` behavior.
The discriminator uses stack return addresses rather than a global flag, so
another task cannot inherit WAVE ownership.

**PROVEN (static software):** the DSP does not fetch the selected record end
as a hardware stop boundary.  `D20A:0008..0049`, file
`0x520A8..0x520E9`, initializes every voice's encoded DSP end to
`0xFFFFFF0`.  `D1F7:000E..00E2`, file `0x51F7E..0x52052`, later writes the
start register and only lane zero of register 1 for pitch.  Therefore the OS
timer is the established selected-end enforcement mechanism.  Extending the
record end would permit playback beyond the visible selection; the scoped
timing hooks retain the real selected end instead.

The current physical-profile payload has SHA-256
`439123b45e9a69bb8b5ae66db17dff2d874e258182ec3a06eadf4ab43881e5be`.
`emu/test_wave_playback.py` uses that already-built payload and the existing
composite fixture; it does not rebuild the payload.  Its Lua probe observes
these locations with XA=1 and the third PGR active:

- WAVE at `F07D:0000`, 20-bit `0xF07D0`, 24-bit `0x3F07D0`;
- record-zero bounds at `A2AE:4814..481B`, 20-bit
  `0xA72F4..0xA72FB`, 24-bit `0x3A72F4..0x3A72FB`;
- stock player `CFC6:0CE9`, 20-bit `0xD0949`, 24-bit `0x3D0949`;
- DSP start-register completion at `D1F7:0054`, 20-bit `0xD1FC4`,
  24-bit `0x3D1FC4`; and
- channel-stop selector `D21F:001C`, 20-bit `0xD220C`, 24-bit
  `0x3D220C`.

**PROVEN in the current emulator run:** the focused cases pass:

- Full Trim requests `[13781,48000)`, programs start `0x013DA5`, restores
  the original record, and a second Play X press visits all 32 `D21F`
  selectors in about 0.955 ms.
- Fine requests exactly `[13781,15701)` and `[46080,48000)`, programming
  starts `0x013DA5` and `0x01BBD0`.  Each reaches `D213` after about 10.27 ms
  and `D21F` after about 30.25 ms.  In each first 30 ms WAV window, both main
  channels contain 1,360 nonzero samples, with peaks 10,589 and 5,870.
- Selected Zone `[458,2290)` has the same approximately 10/30 ms
  release/stop lifecycle and restores the Trim record fields afterward.
- Stereo Trim programs both plane starts, `0x011B58` and `0x019C8B`, and
  both channels reach the natural release and stop paths.
- Empty Zone `[0,0)` reaches neither the player, DSP programming, nor stop
  machinery.
- Fine zoom 1 requests `[13781,13901)`, restores the record, displays
  `Too short`, and allocates no voice.  Navigation clears the message; zoom
  16 recovery then programs `0x013DA5` and plays normally.
- A Fine interval ending at record length requests exactly
  `[53205,55125)`, programs `0x01D7A5`, and does not extend the end.
- After WAVE exits, stock Edit Sound `Ply/Stp` remains unchanged: key-on to
  `D21F` is about 730.19 ms, with `D213` about 20 ms before `D21F`.

The duration evidence is:

| Case | Requested frames | Nominal source time at 44.1 kHz | Emulator observation |
|---|---:|---:|---|
| Fine at Trim start | 1,920 | 43.54 ms | 30.25 ms of nonzero WAV output |
| Fine at Trim end | 1,920 | 43.54 ms | 30.25 ms of nonzero WAV output |
| Selected Zone | 1,832 | 41.54 ms | `D21F` 30.26 ms after key-on |
| Fine ending at record length | 1,920 | 43.54 ms | `D21F` 30.25 ms after key-on |
| Stereo Trim | 25,000 | 566.89 ms | both `D21F` calls about 550.2 ms after key-on |
| Fine zoom 1 | 120 | 2.72 ms | rejected before DSP programming (`<2` ticks) |
| Stock `Ply/Stp` control | 34,219 | 775.94 ms | unchanged `D21F` at 730.19 ms |

The Fine WAV output begins about 1.67 ms after the key event and its first to
last nonzero span is 30.25 ms on both main channels.  Each channel has 1,452
nonzero samples over that complete span.  The first 30 ms validation window
contains 1,360 nonzero samples per channel.  These measurements establish
useful audio that remains within the requested source bounds; the 10 ms
scheduler does not promise sample-exact duration.

The MAME L7A1045 model clears its key state when `D21F` writes zero to the
register-3 low word.  This explains the captured WAV in that model; it does
not establish the unknown physical DSP's internal behavior.

**UNDETERMINED on physical hardware:** no physical Play X observation has
been made for this payload.  The scheduler supplies nominal 10 ms ticks, but
interrupt and task delay remain possible, and no all-path physical timing
claim follows from one emulator execution.  The required observation is
audible playback and bounded stopping for Full, Fine, Zone, stereo, and the
Too-short rejection/recovery sequence on the MPC3000.

## Stop on explicit key and on page exit

**PROVEN:** `CFC6:0D75` reports global voice activity and does not identify
which voice belongs to WAVE.  `CFC6:0D93` stops all 32 channels.  The stock
Edit Sound page uses that pair for an explicit `Ply/Stp` press.  Its ordinary
page exit does not call `CFC6:0D93`.

An `audition_started` byte cannot establish current ownership: it remains set
after a finite audition ends.  If unrelated audio starts before WAVE exits,
`D75 != 0` followed by `D93` stops that unrelated audio.  Therefore the
stock-matching exit is to let the finite selected range finish.  If exit-stop
is retained as a product choice, its global side effect must remain explicit;
there is no proven targeted cleanup entry.

## Pad-input decision

The WAVE input loop calls filtered-key entry `BDE3:000E`, linear file
`0x3DE3E`, 20-bit `0xBDE3E`, 24-bit `0x3BDE3E`.  Its profile-specific body
differs at embedded DGROUP operands, but the entry and returned-key ABI are
common.

**PROVEN for the inspected raw-panel route:** the handler beginning at
`D547:0148`, file `0x555B8`, 20-bit `0xD55B8`, 24-bit `0x3D55B8`, interprets
`90 kk vv` with `kk < 0x10`.  Nonzero `vv` builds a note-on event; zero `vv`
builds the release-status path.  It enqueues the internal four-byte event
before the later UI notification.

The UI callbacks are:

| Entry | Linear file | 20-bit | 24-bit | UI result |
|---|---:|---:|---:|---|
| `D6D4:000B` | `0x56D4B` | `0xD6D4B` | `0x3D6D4B` | status masked with `F8` must equal `90`; queue key `0x44` |
| `D6D4:023D` | `0x56F7D` | `0xD6F7D` | `0x3D6F7D` | same status test; queue key `0x4E` |

The generic callback operands are `DS:D6AD` and `DS:D6AE`; the physical
capture uses `DS:D6AB` and `DS:D6AC`.  WAVE does not need these globals.

**PROVEN for this route:** the release-status event fails the callbacks'
`status & 0xF8 == 0x90` test, so BDE3 does not receive a matching pad-release
key.  By the time BDE3 returns `0x44` or `0x4E`, the earlier internal note
event has already been enqueued.

**UNDETERMINED:** no narrow, ownership-safe hook has been established that
suppresses the ordinary pad event before it reaches the normal program-sound
machinery while still delivering a WAVE audition trigger.  Consuming the
later UI key can prevent stock Edit Sound selection handling, but it cannot
retract the earlier event.  A duplicate normal sound plus WAVE audition is a
material risk.

Use an explicit `Ply/Stp`/Play key or an assigned soft key for WAVE audition.
Do not bind pads until the earlier event's writers, consumers, and release
path are established for the intended entry domain.
