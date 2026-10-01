# MUTE GROUPS page — BENCH 06

**Target:** Vailixi 3.50 interleaved linear image and the hash-pinned captured
application profile. **Implementation:** `mods/mute_ui.inc`,
`mods/mute_storage.inc`, `mods/mute_voice.inc`.

## Controls and behavior

Program/Sounds → **0. Mute groups** opens the page. Cursor keys select Program,
Enabled, Pad, or Group. The wheel and +/− change the selected field; digits
enter a program or pad number, Enabled 0/1, or Group 0–4. Group 0 is Off.
Program and pad entry accepts two digits; Enter finishes a one-digit entry
before starting another. A cursor or other non-digit key also ends entry.
Pads also select their mapped instrument. The overview shows all 64 pad slots,
in banks A–D, with `-` for Off and 1–4 for group membership.

Each program has an enable switch and one assignment per pad: Off, 1, 2, 3,
or 4. Soft key 1 **Apply All** assigns the selected pad's group to all 64 pads
in that program in one action, retaining the enable setting. Soft key 4 exits
to Program/Sounds. A mode key opens the corresponding stock page.

When enabled, a trigger stops sounding voices from other pads in the same
program and group. Off pads are unaffected. Repeated hits on the same pad
retain stock Poly/Mono behavior. Stock Cutoff assignments still apply.
Changing the enable switch or membership takes effect on the next trigger,
including voices that were already ringing. Disabling retains assignments.

Pads mapped to the same MIDI note address one native instrument; they share
the first matching pad's displayed and effective group. The Note field makes
that mapping visible. MIDI does not carry a distinct physical-pad identity.
Each slot retains its stored assignment underneath this effective alias; if
its note later becomes unique, that slot’s previous assignment becomes active.

PGM and APS saves include a validated trailing extension. Legacy programs
load with groups disabled and all pads Off. See the exact grammar, lifecycle,
and error handling in [mute_storage.md](mute_storage.md), and the voice call
contracts in [mute_voice.md](mute_voice.md).

## Address evidence

**PROVEN (source and patched bytes):** the native menu already converts key 0
to option 10. The mod changes its maximum from 9 to 10 and uses an unused
20-character menu line. It dispatches option 10 before the existing nine-entry
jump table. No table index is added to that table.

| Object | Linear file | CPU `CS:IP` | 20-bit | XA=1, third-PGR 24-bit |
|---|---:|---|---:|---:|
| menu maximum | `0x488B6` | `C887:0046` | `0xC88B6` | `0x3C88B6` |
| menu dispatch hook | `0x488D4` | `C887:0064` | `0xC88D4` | `0x3C88D4` |
| stock dispatch continuation | `0x488DB` | `C887:006B` | `0xC88DB` | `0x3C88DB` |
| menu return continuation | `0x48961` | `C887:00F1` | `0xC8961` | `0x3C8961` |
| effective pad-to-note lookup | `0x59F2C` | `D9F2:000C` | `0xD9F2C` | `0x3D9F2C` |
| note-to-first-pad lookup | `0x59F5D` | `D9F2:003D` | `0xD9F5D` | `0x3D9F5D` |

These code sites are identical in the generic and captured application.
Before relocation, the second PGR maps application ROM at physical
`0x0B0000..0x0F3FFF`; after relocation, the third PGR maps that logical window
to RAM at `0x3B0000..0x3F3FFF`. XA=0 is not this execution domain.

The menu string is generic linear `0x25E92`, captured linear `0x25E90`,
inside the DGROUP initializer. Its runtime copies are `8010:5E92` and
`8010:5E90`, respectively: logical `0x85F92`/`0x85F90`, physical
`0x385F92`/`0x385F90` under XA=1 with either RAM-mapping PGR.
The source file offset is not its runtime address.

The UI and its small caches occupy writable CS-relative space in the F07D
cave. Exact offsets are emitted in `build/mods/wavehw.cave.map` and
`wave.cave.map`; linear = `0x707D0 + offset`, CPU = `F07D:offset`, logical =
`0xF07D0 + offset`, and relocated physical = `0x3F07D0 + offset`.

## Lifetime and verification

Entry saves the stock text screen, reads the current program name and effective
64-slot note map, then uses the waveform raster font and framebuffer. The UI
refreshes its context when a program change occurs while waiting for a key.
Wheel repetition uses the native accumulated key count. All program, pad,
and group changes clamp to their legal bounds. It preserves SI, DI, BP and DS;
ES is also restored on return.

**PROVEN (emulator executions):** `emu.test_mute_ui` passes seven tests with
real panel input and read-only observers: individual pads 1 and 64, one-action
Apply All, independent programs, fast-wheel accumulation and bounds, physical
pad selection across four banks, generic-profile entry/exit, and complete
240×64 pixel comparisons against an independent layout reference. Evidence:
`build/wavebench06-navigation-ui-tests.log` and `build/emu/mute-ui-tests/`.
The same final 14-test run includes five End/Zone navigation cases and two
real-menu lifecycle cases: copying all assignments from Program 1 to Program
24, then initializing Program 24 while retaining Program 1.

**UNDETERMINED:** physical panel/LCD/audio behavior of BENCH 06. The emulator's
panel/TE7774 and voice model do not qualify physical timing. Required bench
observations are page navigation, group choking across pads and banks,
program isolation, and PGM/APS save/reload on the actual machine.
