# MPC3000 emulator harness (patched MAME)

Evidence and open boundaries: [`../notes/emulator.md`](../notes/emulator.md).
Everything here writes only under `build/` (gitignored).

## MAME build (pinned)

The driver lives in a MAME fork, outside this repo:

| Item | Value |
|------|-------|
| Fork | <https://github.com/pmoneynz/mame>, branch `mpc3000-accuracy` |
| Pinned commit | `f4a72e1adcb6b9c332e4f7b7c666cd9c93971fdb` (upstream base `9ede38cb`) |
| Changed file | `src/mame/akai/mpc3000.cpp` |
| Binary the harness runs | `$MPC3K_MAME`, default `../MPC3000_builds/mame/mpc3k` |

```bash
git clone --depth 50 -b mpc3000-accuracy https://github.com/pmoneynz/mame.git ../MPC3000_builds/mame
cd ../MPC3000_builds/mame
git checkout f4a72e1adcb6b9c332e4f7b7c666cd9c93971fdb
make SUBTARGET=mpc3k SOURCES=src/mame/akai/mpc3000.cpp TOOLS=0 NOWERROR=1 -j14
```

When the driver changes: commit and push the fork, then update the pinned
commit here in the same change as the tests that depend on it.

Without the binary, `emu.test_mpc3k` is skipped (not failed). It also needs
`nasm` and `mtools`.

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

## Front panel

Interactive: `../MPC3000_builds/mame/mpc3k mpc3000 -rompath build/roms`
and use the keys MAME lists under Input (this Machine); pads are on the
numeric keypad. Config "Front panel" selects the HLE (default) or a real
panel ROM.

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

## Font pipeline

`emu/font/` recovers the LCD glyphs from glass photos. Run the scripts from
that directory: `fit_grid.py`, `homog_fit.py`, … `extract_glyphs.py` (see
[`../notes/emulator.md`](../notes/emulator.md)). Output is `glyphs.json`,
which `emu/romset.py` turns into `hd61830.bin`.
