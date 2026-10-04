# Brief: run the emulator suites on the OS 3.16 build

For implementation workers (`port-mechanic`). Read `AGENTS.md`,
`notes/port_316.md`, `emu/README.md` and `emu/harness.py` first.

## What exists

- `python3 mods/build_wave316.py --out DIR` builds `WAVE316.SYS`, a floppy
  image `WAVE316.img` (STARTUP.SYS + SINE441 + STEREO1), `WAVE316.json` and
  `wave316.cave.{bin,map}`. It is the universal build: it boots on every MAME
  BIOS set (`default` = 3.12, `vailixi`, `v311`, `v308`) with the stock romset.
- At run time the cave lives at logical `L*16 + 0x7E000` (physical
  `0x300000 + L*16 + 0x7E000`), where `L = 0x6900` for `default` and
  `vailixi`, `0x7000` for `v311` and `v308`. 3.16 DGROUP is at runtime
  segment `L + 0x609C`, so DS offset `X` is physical
  `0x300000 + (L + 0x609C)*16 + X`.
- 3.16 stock routines are at relative `seg:off` (see `mods/profile_316.inc`
  and `notes/port_316.md`); at run time CS = `L + seg`. A Lua tap on a stock
  instruction must use the relocated CS:IP or the physical address.
- Every 3.16 DGROUP offset the mods use is in `mods/profile_316.inc`
  (e.g. `KEY_REPEAT 0xD387`, `ZONE_ST 0xE45A`, `MUTE_CURRENT_PROGRAM 0xE2FB`).
- 3.16 key timeline (verified on all four sets): `<scratchpad>/port/work-memprobe/timeline_316.py`.
  Boot: Soft Key 4 at 33.0 s cancels the SCSI search, Play/Record at 33.6 s.
  Disk → 7 lists files 3.5 s after Disk; Soft Key 1 loads the selected SND.
  Program/Sounds → 6 opens Edit Sound on the first sound.
- Proven so far (MAME): banner `WAVE BENCH 08`; the full wave view of SINE441
  is pixel-identical to `emu/wave_ref.screen` on all four sets; Help/Exit,
  Program/Sounds → 0 (Mute Groups) and its exit work; the cave is at its home
  and the pool fix is applied only with `L = 0x6900`.

## Behaviour that differs from the Vailixi builds (tests must expect it)

- Do list has 8 stock options; CHOP ZONE is the 9th (index 8).
- No "safe lock" and no Edit Sound mute: CHOP never refuses for a running
  sequence and writes no port 6A. Entering Edit Sound (and every waveform
  re-entry through the queued `6`) stops a playing sequence, as stock 3.16 does.
- CHOP names results `ZONE000`, `ZONE001`, … itself (collision-free).
- Sequence memory: 411K with `L = 0x6900`, 439K with `L = 0x7000`.

## Task

1. Add a `316` profile to `emu/harness.py` (payload built by
   `mods/build_wave316.py` into the harness's private payload directory, source
   digest covering its inputs) with per-BIOS romset, load segment, cave
   physical base and DGROUP translation. Keep the Vailixi profiles working.
2. Port the suites so each runs on the `316` profile on at least one `L=6900`
   set and one `L=7000` set, and on all four sets in release mode. Keep every
   assertion's meaning; where 3.16 behaviour differs (above), assert the 3.16
   behaviour and say why in the test.
3. Add a regression for the pool fix: record a sequence, press Song, confirm
   the Song screen and later key input on all four sets, and that image bytes
   `0x0000..0x6FFF` in RAM are unchanged except the hook bytes at `0x318C..0x3191`.
4. Run everything in release mode (skips are failures). Report counts per suite
   and per BIOS set, and every failure with evidence. Do not weaken tests.
