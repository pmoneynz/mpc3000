# Floppy mods

Procedure, rules and evidence: [`../MODDING_HOWTO.md`](../MODDING_HOWTO.md).
Loader facts: [`../notes/floppy_loader.md`](../notes/floppy_loader.md).
Builders read `07-rom/` (and, for the capture profile, `build/hardware/`)
and write only `build/mods/`, or the directory given by `--out` / `out=`
(tests use temporary directories). NASM runs in a private scratch
directory per invocation, so concurrent builds cannot read each other's
maps. Floppy images come from one deterministic FAT12 packer: directory
times and bytes `+0C..+13` (3.50 filename characters 9-16) are zero, so an
image hash is a function of its files. Builders no longer need mtools.

| File | Role |
|------|------|
| `buildkit.py` | Shared: pinned ROM interleave, word sum, MZ header, NASM map/listing/deps, deterministic FAT12 |
| `build_mod_sys.py` | Route A: patched Vailixi 3.50 relocated to RAM → `<NAME>.SYS`, `<NAME>.img`; checks DGROUP size against the guarded BIOS |
| `mod_stub.asm` | Route A stub: 3.50 BIOS guard, copy OS code + DGROUP, rejoin reset at `FAC0:0134` |
| `*.args` | One mod per file: `--name=` and `--patch=FILE:OLD:NEW` lines |
| `build_canary.py` | Route B minimal example: 288-byte `STARTUP.SYS` that prints `Vailixi 3.51 (---/--/----)` |
| `WAVE.args`, `wave.asm` | Waveform editor: Help on Edit Sound; trim/zone, full/fine zoom and stereo planes |
| `wave_numeric.inc`, `wave_playback.inc` | Stock numeric-entry integration and visible-selection audition |
| `wave_zones.inc`, `wave_chop.inc` | Shared zone editor, source lifetime guards, and native sample creation through CHOP ZONE |
| `mute_ui.inc`, `mute_voice.inc`, `mute_storage.inc` | Four program-level mute groups, 64-pad page, voice choking, and PGM/APS persistence |
| `build_wave_bench.py` | `WAVEBENCH.img`: WAVE plus disposable mono/stereo sounds; manifest marker from `WAVE.args`, sources from `nasm -M` |
| `build_romcheck.py`, `romcheck.asm` | `ROMCHECK4` high-ROM byte comparison; physical stop at comparison checkpoint `2400` |
| `build_romsum.py`, `romsum.asm` | One-cluster `ROMSUM2` checksum probe; physical run measured `81A0` versus reference `8634` |
| `build_romword.py`, `romword.asm` | `ROMWORD5` focused aligned-word comparison of `7A000–7BFFF`; physical result: 1,287 differing words |
| `build_romdump.py`, `romdump.asm` | Capture runtime `F800:0000–7FFF` to preallocated `BIOS.BIN`; physical 32 KiB capture verified |
| `build_wave_physical.py` | WAVEHW, hash-pinned captured ROM profile with exact high-ROM guard; hooks generated from `WAVE.args`; every cave far target checked against the capture |
| `build_romapp.py`, `romapp.asm` | Guarded 336 KiB application/data capture to `ROMAPP.BIN`; excludes NVRAM, uses captured PGR wrapper |
| `PETER.args`, `CAVEDEMO.args` | Version-screen credit and execution-from-RAM demonstrations |
| `S1A.args`, `s1a.asm` | S1a: the 17 divide calls of the note-on layer `CFC6:039E` go to a two-step `DIV` cave routine (exact, falls back to the BIOS runtime); layer −45 % in MAME; `notes/performance.md` §9.6, `tests/test_s1a_divide.py` |

```bash
python3 mods/build_mod_sys.py @mods/DEMO351.args   # build/mods/DEMO351.{SYS,img}; --out DIR elsewhere
python3 mods/build_canary.py                       # build/mods/STARTUP.SYS, vailixi350-canary.img
python3 mods/build_wave_bench.py                   # build/mods/WAVEBENCH.{img,json}
python3 mods/build_romcheck.py                     # build/mods/ROMCHECK.{SYS,img,json}
python3 mods/build_romsum.py                       # build/mods/ROMSUM.{SYS,img,json}
python3 mods/build_romword.py                      # build/mods/ROMWORD.{SYS,img,json}
python3 mods/build_romdump.py                      # build/mods/ROMDUMP.{SYS,img,json}
python3 mods/build_wave_physical.py                # build/mods/WAVEHW.{SYS,img,json}; requires both verified captures
python3 mods/build_romapp.py                       # build/mods/ROMAPP.{SYS,img,json}; requires preserved physical BIOS.BIN
```

## Writing a real disk

The images are 2880-sector, 512-byte, 18-sector/track FAT12 (BIOS
geometry slot `F800:034F`). Copy the `.SYS` onto a freshly formatted
floppy, or write the whole image. On macOS, find the USB floppy with
`diskutil list` first:

```bash
diskutil unmountDisk /dev/diskN
sudo dd if=build/mods/DEMO351.img of=/dev/rdiskN bs=512
diskutil eject /dev/diskN
```

The canary ran on Peter's physical MPC3000 through FlashFloppy on
2026-10-01 (**PROVEN**, user report and photo). Route A and WAVE still need
their own hardware qualification. See the [bench procedure and evidence](../notes/waveform_bench.md).

For FlashFloppy, replace a backed-up `.IMG` **file** on the mounted USB
filesystem with the bench image; do not write to the USB block device.
The bench image contains the waveform payload as its sole SYS,
`STARTUP.SYS`. Put this image in `Disk_01.IMG` and select that slot in
`IMAGE_A.CFG` before moving the USB to the MPC: FlashFloppy is powered
with the MPC, so the bench procedure must not require selecting a slot
before power-on. The SND files are loaded manually after boot; the current USB also retains DRUMS.

The captured personalized ROM requires `build_wave_physical.py`. Its
validated BENCH 05 image is installed in slot 1; BENCH 06 adds mute groups. Both capture hashes are pinned; the loader compares all 32 KiB
of high ROM before relocation. The build fails if a cave far CALL/JMP
target in the capture is not the generic routine (allowing only the
DGROUP −2 and AMX −0xA operand shifts); see
[the profile note](../notes/wave_physical_profile.md#build-requirements-and-remaining-boundaries). BENCH 02 full/Fine editing is physically observed; the new numeric and audio
controls need their next physical check;
see [the capture and validation](../notes/rom_compatibility.md#wavehw-capture-specific-waveform-build).

BENCH 04 retains stock numeric entry (digit or Enter on Start/End) and
visible-selection audition (`<Ply/Stp>`, soft key 1). Soft key 2 toggles Trim/Zone. Include the converted DRUMS
sample in the capture-specific image with:

```sh
python3 mods/build_wave_physical.py --sound build/samples/DRUMS.SND
```

See the [current bench instructions](../notes/waveform_bench.md) for controls,
validation, deployment state, and the preserved BENCH 02 rollback.

Waveform audition uses a conservative stock timer cutoff. Ranges shorter than two playback
ticks (about 20 ms at original pitch) show `Too short`; widen the range or zoom out.

BENCH 04 reorders the waveform soft keys: 1 `<Ply/Stp>`, 2 Trim/Zone toggle,
3 Fine/Full, 4 Exit. Playback and numeric-entry behavior are unchanged.

BENCH 05 adds MPC2000XL-style shared zones. `ZONE:01/16` shows the active
zone and total count as separate cursor fields. Left/Right reaches both;
wheel or +/− changes them. Count is 1–16 and changing it resets the divisions
across the whole sound. Adjacent zones share an edge. Stock numeric entry
also edits these edges. The existing four soft keys keep their BENCH 04 order.

Return to Edit Sound, select `Do:CHOP ZONE`, and press `<Do>` to create one
new `ZONE###` sound per zone. The source is retained, stereo and volume/tune
are preserved, and each result contains the exact selected PCM interval.
Empty zones or zones under 441 frames (10 ms) are refused; the latter limit
avoids the stock SND loader's incorrect short-sound length on reload. Free
sound slots and sample memory are checked before creation. Save the resulting
sounds through the usual Disk workflow.

Zone edits last within the current Edit Sound session, including waveform
Exit/reopen. Selecting a sound again or leaving Edit Sound resets the map;
created sounds are ordinary independent sound objects. Detailed evidence:
[zone editor](../notes/wave_zones.md), [CHOP ZONE](../notes/wave_chop.md).

BENCH 06 adds **Program/Sounds → 0. Mute groups**: Enabled per program,
Group Off/1–4 per pad 1–64, and soft key 1 Apply All, which asks first: only
soft key 3 `<Do it>` applies it and any other key cancels. Assignments are stored
with PGM/APS files. See [controls and evidence](../notes/mute_groups.md).

BENCH 06 also adds the waveform shortcut **End → Up → Zone**, then **Down →
End**. Up during End numeric entry accepts the value before selecting Zone.
