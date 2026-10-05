# MPC3000 emulator harness (patched MAME)

Evidence and open boundaries: [`../notes/emulator.md`](../notes/emulator.md).
Everything here writes only under `build/` (gitignored).

## MAME build (pinned)

The driver lives in a MAME fork, outside this repo:

| Item | Value |
|------|-------|
| Fork | <https://github.com/pmoneynz/mame>, branch `mpc3000-accuracy` |
| Pinned commit | `d651a20c55e90e9f183e089d0070addc1a878b08` (upstream base `9ede38cb`) |
| Changed files | `src/mame/akai/mpc3000.cpp`, `src/mame/layout/mpc3000.lay`, `src/devices/cpu/nec/{nec,v5x}.{cpp,h}`, `necpriv.ipp`, `src/devices/machine/am9517a.{cpp,h}` |
| Binary the harness runs | `$MPC3K_MAME`, default `../MPC3000_builds/mame/mpc3k` |

```bash
git clone --depth 50 -b mpc3000-accuracy https://github.com/pmoneynz/mame.git ../MPC3000_builds/mame
cd ../MPC3000_builds/mame
git checkout d651a20c55e90e9f183e089d0070addc1a878b08
make SUBTARGET=mpc3k SOURCES=src/mame/akai/mpc3000.cpp TOOLS=0 NOWERROR=1 -j14
```

When the driver changes: commit and push the fork, then update the pinned
commit here in the same change as the tests that depend on it.

Without the binary, the emulator suites are skipped (not failed). They also
need `nasm` and `mtools`. Under `MPC3K_RELEASE=1` a missing tool or fixture is
an error instead of a skip; `python3 -m emu.harness_release [suites]` sets it,
runs the suites in sequence and fails unless the summary line says
`skipped=0` with no failures, errors or expected failures.

## ROM set

`python3 -m emu.romset` (run automatically by every emulator run) writes
`build/roms/mpc3000/`. It holds the `07-rom/` chip pairs under MAME's names,
plus two placeholders that do **not** match MAME's hashes:

| File | Placeholder | Consequence |
|------|-------------|-------------|
| `mp3000__op_v1.0.am27c256__id0110.ic602.bin` | 32 KiB of `0xFF` | Panel MCU idles; the driver's panel HLE (default) supplies keys, pads, dial, slider |
| `hd61830.bin` | Built from `emu/font/glyphs.json` (glass photos) | 55 of 96 codes `20-7F` evidence-backed; unobserved codes render as a hatch |

Replace them in `emu/romset.py` when real dumps exist. There is no 3.10
dump, so `--bios v310` fails.

## Run

From the repo root:

```bash
python3 -m emu.mpc3k --bios vailixi --times 10,45
python3 -m emu.mpc3k --board 8 --simm 4          # EXM3008 + 2x4 MB SIMMs
python3 -m emu.mpc3k --smpte                     # I-0055 installed (unmodelled)
python3 -m emu.mpc3k --floppy build/mods/MOD350.img
python3 -m unittest emu.test_mpc3k -v
```

`--bios`: `vailixi`, `default` (3.12), `v311`, `v308`.
Each run writes `build/emu/<name>/` with `screens.txt`, `screens_hex.txt`
(raw display RAM), `lcd_pixels.txt` (native 240x64), `io_first.log`
(first access per I/O port with `PS:IP`), `lcd_io.log`, and snapshots.
Runs are headless (`-video none`, `SDL_VIDEO_DRIVER=dummy`,
`SDL_MAC_BACKGROUND_APP=1`): no window, no focus change.

Extra probes in `emu/lua/`, passed as
`extra=["-autoboot_script", "emu/lua/<file>"]`; each chains `probe.lua`:

| Script | Shows |
|--------|-------|
| `pgr_watch.lua` | Page table words 44–60 on every change (RAM `0EC…` vs ROM `02C…`) |
| `loader_bp.lua` | Which floppy-loader call sites fire (needs `-debug -debugger none -log`) |
| `snddump.lua` | Sound records `A2AE:4800` and each sound's wave RAM words at every snapshot time (`snd_dir.log`, `wave_<t>_idx<i>.bin`; `SNDDUMP_PCM=0` for the directory only) |
| `wcu_dump.lua` | V53 wait control / refresh registers after 1 s (`wcu.txt`) |
| `cave_watch.lua` | Reads (including fetches) and writes of the code cave in EPROM and in the Route A RAM copy (`cave.txt`) |

## WAVE / MUTE GROUPS suites (`emu/harness.py`)

Every WAVE and MUTE GROUPS suite gets its payload from `harness.payload()`:
it assembles the cave and builds the SYS from the current sources into
`build/emu/harness-payloads/<source digest>/<profile>/` (both builders are
called with `out=` a private directory: `build_mod_sys.build(..., out)` and
`build_wave_physical.build(out=...)`; `build/mods` release artifacts are never
read or written). The digest covers `mods/*.inc`, `mods/*.asm`, both
builders, `mods/buildkit.py`, `WAVE.args`, the 3.50 chips, the hash-pinned
captures and the NASM version; a rebuild with the same digest must give the same bytes. Each
suite logs `STARTUP.SYS sha256=...` to stderr and to
`<runs>/payload-<profile>.json`, and every disk image is read back to prove
its `STARTUP.SYS` is that payload. Suites therefore do not depend on
discovery order or on earlier builds.

| Profile | Payload | Romset |
|---------|---------|--------|
| `capture` | `build_wave_physical.build()` (`WAVE_CAPTURE_20261001`) | composite: captured ranges over the reference interleave |
| `generic` | `mods/WAVE.args` on the 3.50 interleave | `build/roms` |
| `316` | `mods/build_wave316.py` (`WAVE316.SYS`, OS 3.16 Route C) | `build/roms`, any of `default`, `vailixi`, `v311`, `v308` (below) |

`harness.EmuSuite` runs a suite's cases on `capture` and its `GENERIC`
subset on `generic`. Environment: `MPC3K_GENERIC=all` runs every case on
both; `MPC3K_PROFILES=capture` (or `generic`) and `MPC3K_CASES=a,b` narrow a
development run; `MPC3K_TIMEOUT_SCALE` scales the per-run wall-time limit
(`emu/mpc3k.py` kills MAME after `240 + 8 * last probe time` seconds and
checks that one screen was captured per requested time).

Timeline: Soft Key 4 at 20 s cancels the SCSI search; `<Load>` of the disk's
sound at 26.5 s; the wave view is open from `harness.VIEW` = 40 s for sounds
up to ~170 KB. `harness.burst(n, t)` sends wheel events 1 ms apart, which the
stock reader coalesces (the stock key queue holds 8 keys, so bursts of up to
9 apply exactly whatever the redraw time; see `emu/test_harness_bursts.py`
for which assertions also depend on a redraw outlasting the burst).

Observers are composed by `harness.observer(profile, path, parts)` from
`emu/lua/<part>.lua` with a preamble defining `CAVE` (every symbol of that
profile's map) and `DG` (its DGROUP offsets); all parts only read state:

| Part | Writes |
|------|--------|
| `repeat_watch` | `repeat.log`: every `key_repeat`/`mu_repeat` store with its value, key-queue capacity |
| `wave_zones` | `zones.jsonl`, `records_<t>.bin` |
| `snddump` | `snd_dir.log`, `wave_<t>_idx<i>.bin` (`SNDDUMP_PCM=0` or a time list limits PCM) |
| `wave_playback` | `wave_playback.log`: BOUNDREAD/BOUNDWRITE, STARTREG/KEYON, D213/D21F, WAV windows (`PLAYBACK_WAV`) |
| `mute_voice`, `mute_ui` | mute tag/stop log; mute page state |

### OS 3.16 profile (`316`)

`payload("316", bios)` builds `mods/build_wave316.build(out=...)` into
`build/emu/harness-payloads/<digest>/316/` (`WAVE316.SYS`, its map as
`wave.map`). Its own source digest covers `mods/*.inc` (entry, profiles),
`mods/*.asm`, `build_wave316.py`, `route_c.py`, `build_mod_sys.py`,
`buildkit.py`, `WAVE316.args`, `M3K316.SYS`, the 3.50 chips (stock-target
shape check) and the NASM and ndisasm versions; the capture/generic digest is
unchanged. It boots from the stock romset on `bios` = `default` (3.12),
`vailixi`, `v311` or `v308` (`harness.BIOS_316`); `profile.label` is
`316-<bios>`, the run directory and result key. Notes: [`../notes/port_316.md`](../notes/port_316.md).

| `Profile` member (316) | Value |
|---|---|
| `load_segment` | L: `0x6900` (`default`, `vailixi`), `0x7000` (`v311`, `v308`) |
| `cave_segment`, `cave_phys` | `L+0x7E00`; `0x300000 + L*16 + 0x7E000` (cave map offsets add to these) |
| `dgroup(generic)` | 3.16 DS offset of a generic Vailixi DS offset, from the `NAME equ 0x<3.16> ; <generic>:` pairs of `mods/profile_316.inc` (`KeyError` if unpaired) |
| `dgroup_segment`, `dgroup_phys(generic)` | `L+0x609C`; `0x300000 + (L+0x609C)*16 + dgroup(generic)` |
| `sound_segment` | `L+0x539D` (records at `+0x4800`, generic `A2AE`) |
| `runtime(seg, off)`, `target("T_B99A_0AF3")` | `Runtime(cs=L+seg, ip=off, phys=0x300000+cs*16+off)` for a 3.16 relative address / a profile target |
| `image_phys(o)`, `relocated_image()`, `cave_home_image()` | physical address of image offset `o`; the load image with relocations for L; the cave at its home per the loader simulation |
| `timeline`, `view` | `harness.TIMELINE_316`; `52.0` |

Physical = `0x300000 + logical` because 3.16 keeps the loader's third PGR
(`image316.lua` checks it through the live PGR). The capture/generic profiles
answer `cave_segment`/`cave_phys`/`dgroup_segment`/`sound_segment`/`view`
with their Vailixi values (`F07D`, `0x3F07D0`, `8010`, `A2AE`, `40`).

Timeline (`TIMELINE_316`, all four sets): banner by 31 s, SCSI search 32.6 s,
Soft Key 4 at 33.0 (Play/Record by 33.6); Disk 35.0, 7 at 35.8, `<Load>` at
39.0 (108K loaded by 43.8); Program/Sounds 46.0, 6 at 46.8, Help 49.0; wave
view from 52. `load_sound_events`, `open_view_events` and `wave_events` take
`profile=` (default: the Vailixi timeline, unchanged).

Observers: for a 316 profile `observer()` loads part `X` from
`emu/lua/X316.lua` (missing port: `FileNotFoundError`) and adds `LOAD_SEG`,
`CAVE_SEG`, `CAVE_PHYS`, `DG_SEG`, `DG_PHYS`, `SND_SEG`, `IMAGE_PHYS`,
`CAVE_LEN` to the preamble (`DG` holds 3.16 offsets). Ported parts:
`wave_zones316`, `snddump316`, `repeat_watch316`, and `image316` (pool-end
immediate, cave home and image-head dumps at `IMAGE316_AT`, writes to image
`0..0x6FFF` from `IMAGE316_WATCH_FROM`).

`EmuSuite`: a suite opts in with `PROFILE_NAMES = harness.ALL_PROFILES`; its
cases run on 316 once per BIOS set (`default` and `v308` by default, all four
under `MPC3K_RELEASE=1`; `MPC3K_BIOS_316=v311,vailixi` or `all` overrides,
release refuses a subset), minus `SKIP_316`. `cases()` takes times from
`profile.view`; tests use `self.view(label)`. `MPC3K_PROFILES=316` runs only
316. `emu/test_port316_boot.py`: banner, timeline, wave view pixels, Mute
Groups, cave home and pool end, and the pool-fix Song regression, on all four
sets.

`<t>` in file names is the probe time formatted as `%g` (79.5 and 80.5 stay
distinct). New suites: `test_harness_bursts` (coalesced point motion and
saturation), `test_harness_long` (220,500-frame sound, 32-bit paths),
`test_harness_lifecycle` (stock Do 0-9, zone-pair import, A->B->A, sound
delete).

## Front panel

Interactive: `../MPC3000_builds/mame/mpc3k mpc3000 -rompath build/roms`
and use the keys MAME lists under Input (this Machine); pads are on the
numeric keypad. Config "Front panel" selects the HLE (default) or a real
panel ROM.

Views (Tab → Video Options, or `-view "<name>"`): `Default Layout`,
`Large Screen` (full panel, LCD enlarged over the knobs) and `LCD Only`.
Snapshots use the first view unless `-snapview` names another.

Scripted, two equivalent paths (grammar and key map:
[`../notes/panel_link.md`](../notes/panel_link.md)):

```python
from emu.panel import key_tap, dial, pad_hit, panel_pad, write_smf
from emu.mpc3k import BUILD, run
smf = write_smf(BUILD / "x.mid", key_tap("rec", 45) + key_tap("play", 46) + pad_hit(panel_pad(1), 47))
run("vailixi", [49], BUILD / "emu" / "x", panel=smf)                            # link frames
run("vailixi", [47], BUILD / "emu" / "y", press=[(45.0, "Y0", "Disk", 0.1)])    # MAME inputs -> HLE
```

`python3 -m emu.key_sweep` re-derives the key map.

Test sounds: `emu/snd.py` writes `.SND` files (`snd`, `sine441`, `stereo1`) and
floppy images that 3.50 can open (`disk`). Load: Disk, `7`, Soft Key 1 `<Load>`.

## Font pipeline

`emu/font/` recovers the LCD glyphs from glass photos. Run the scripts from
that directory: `fit_grid.py`, `homog_fit.py`, … `extract_glyphs.py` (see
[`../notes/emulator.md`](../notes/emulator.md)). Output is `glyphs.json`,
which `emu/romset.py` turns into `hd61830.bin`.
