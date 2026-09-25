# How to build and deploy MPC3000 mods (floppy path)

**Scope:** mods delivered as a `*.SYS` file on floppy and loaded by the ROM
floppy loader at power-on. The EPROMs are never touched. No other delivery
path is covered here.
**Foundation:** [`notes/floppy_loader.md`](notes/floppy_loader.md). Every
address below is pinned there and re-checked by
`python3 tools/verify_boot_slice.py`.
**Date:** 2026-09-25.

Tags follow [`AGENTS.md`](AGENTS.md): **PROVEN** (code or trace, cited),
**HYPOTHESIS**, **UNDETERMINED**. Every trace is MAME `mpc3000` (patched
driver in `MPC3000_builds/mame`). **No mod has run on real hardware yet.**

---

## 1. How a floppy mod gets control

```
power-on → BIOS → ROM OS entry (3.50: B000:00DF)
  "Searching floppy for startup files..."
  floppy ready?  ── no ──→ SCSI search, normal boot
  yes → loader B000:01A7 (arg 0)
        first *.SYS in the root directory?  ── no ──→ APS / PGM / ALL startup files
        yes → FB93:0066 hand-off
              INT 10  third PGR: logical 0xB0000–0xF3FFF (ROM OS pages) become RAM
              INT 45  DOS MZ loader: file → RAM at 6900:0000 (3.12/3.50) or 7000:0000 (3.08/3.11)
              JMP FAR entry  (never returns)
```

**PROVEN** (code, all four EPROM OSes, [`floppy_loader.md`](notes/floppy_loader.md)
§1–§7; trace for 3.16 on 3.08/3.11/3.12/3.50).

Three consequences shape every mod:

1. **The ROM OS is gone** once `INT 10` runs. Its code pages now show RAM.
   A mod either brings a whole OS or carries its own copy of the stock one.
2. **The BIOS stays.** Logical `0xF8000–0xFFFFF` (file `0x78000–0x7FFFF`:
   `F800` BIOS, `FB00` AMX kernel, `FB93` hand-off, `FAC0` XA/IRQ wrappers)
   stays mapped to EPROM. A floppy mod cannot change those bytes.
3. **It is volatile.** The mod lives in RAM. Without the disk, the next
   power-on boots the EPROM OS. **HYPOTHESIS**: the 3.16 PDF says so ("gone
   when power is removed"), but no mod-then-diskless reboot has been traced.
   Whether a mod that writes the NVRAM page (61, `0x500000`) can disturb the
   EPROM OS afterwards is **UNDETERMINED**. Route A writes it exactly as
   stock 3.50 does.

---

## 2. Choose a route

| | Route A: patched Vailixi 3.50 | Route B: replacement OS |
|--|--|--|
| What ships | Stock 3.50 OS code + DGROUP with your byte patches, plus a relocation stub | Your own MZ executable |
| EPROMs required | Vailixi 3.50 exactly (stub enforces it) | Any of 3.08 / 3.11 / 3.12 / 3.50 |
| Tooling | `MPC3000_builds/tools/build_mod_sys.py` | nasm + an MZ header (template: `tools/build_canary.py`) |
| Sequencer memory | 484K, same as EPROM boot (trace) | Yours to define |
| Proven depth | Boots to Play/Record and accepts panel input (trace) | Prints text through the BIOS (trace). Nothing else proven |
| Use for | Bug fixes, string changes, behaviour tweaks | A new OS; experiments with the BIOS services |

Precedent: OS 3.16 (`M3K316.SYS`, 2005) is a Route B file: a full OS linked as
an MZ with 6998 relocations. It shows 439K sequencer memory because its own
image sits in the pool. **PROVEN (trace)**.

---

## 3. Toolchain and layout

Required on the build host: `python3`, `nasm`, `mtools` (`mformat`, `mcopy`),
and the MAME build at `MPC3000_builds/mame/mpc3k` for testing.

| Path | Role |
|------|------|
| `MPC3000_builds/tools/build_mod_sys.py` | Route A builder: patches, stub, MZ header, 1.44 MB image |
| `MPC3000_builds/tools/mod_stub.asm` | Route A relocation stub (BIOS guard, copy, rejoin reset path) |
| `MPC3000_builds/mods/*.args` | One file per mod: its name and patch list |
| `MPC3000_builds/tools/build_canary.py` | Route B minimal example: 288-byte MZ that prints a line |
| `MPC3000_builds/emu/mpc3k.py` | Headless MAME runner: screen capture, panel presses, RAM words |
| `MPC3000_builds/emu/test_mpc3k.py` | Emulator regression tests (add one per mod) |
| `MPC3000_builds/run/pgr_watch.lua` | Proves the relocated code is the code running (§6.3) |
| `MPC3000_builds/out/` | Build output (`<NAME>.SYS`, `<NAME>.img`) |
| `MPC3000/tools/floppy_loader.py` | Pins the loader in every EPROM OS (`--check`) |
| `MPC3000/tools/v53_decode.py` | Instruction lengths, including `BRKXA`/`RETXA` |

Never write under `MPC3000/07-rom/`. The builders only read the chip pair.

---

## 4. Route A — patched Vailixi 3.50

### 4.1 What the builder produces

`MOD350.SYS` = MZ header (2 paragraphs, no relocations, `CS:IP` 0:0,
`SS:SP` 0:0) + stub + DGROUP image + OS code image:

| Part | Source file range | Destination at run time |
|------|-------------------|--------------------------|
| DGROUP | `[0x20000, 0x27C92)` | `8010:0000` (20-bit `0x80100`), as the reset copy does |
| OS code | `[0x30000, 0x74000)` | logical `0xB0000–0xF3FFF` = RAM pages `0xEC–0xFC` under the third PGR |

The stub, in order ([`mod_stub.asm`](../MPC3000_builds/tools/mod_stub.asm)):

1. Sums the words of `F800:0000–7FFF` (file `0x78000–0x7FFFF`) and compares the result with the sum the builder took from the 3.50 chips.
   On a mismatch it prints `Mod needs Vailixi 3.50 EPROMs` through `INT 43`
   AX=4 and halts. This matters because the relocated OS calls the BIOS at fixed addresses.
2. Copies the OS code in 17 × 16 KiB chunks, top chunk first, because the source and destination overlap.
   The builder asserts that the order is safe for both load segments.
3. Copies DGROUP to `8010:0000`.
4. Sets `SS:SP = 900C:0100` (the reset stack) and jumps to `FAC0:0134`.
   That is the reset path right after the DGROUP copy and the second-PGR
   load ([`boot_reset_to_bios_banner.md`](notes/boot_reset_to_bios_banner.md) §5–§6).
   The init walk zeroes BSS, runs the BIOS/AMX init records, enables interrupts and enters the (now RAM) OS at `B000:00DF`.
   The third PGR stays loaded, so every OS fetch hits your patched copy.

The OS then boots a second time and runs its floppy loader again. The builder
always applies one mandatory patch to stop it loading the SYS a second time:

| File | `CS:IP` | Stock | Mod | Effect |
|------|---------|-------|-----|--------|
| `0x30207` | `B000:0207` | `75` (`JNZ 0239`) | `EB` (`JMP 0239`) | SYS step skipped. APS / PGM / ALL steps still run |

**PROVEN (trace)** for 3.50, [`test_mpc3k.py`](../MPC3000_builds/emu/test_mpc3k.py)
`test_patched_350_boots_from_floppy_and_takes_input`:

| Time (MAME) | Screen | Meaning |
|-------------|--------|---------|
| 5 s | `Vailixi 3.50` banner | EPROM boot |
| 12 s | `Loading files ...` | ROM loader reads `MOD350.SYS` |
| 15–19 s | `Vailixi 3.51` banner | the patched DGROUP string, painted by the relocated OS |
| 20 s | System Information, `SEQ … 484K`, `Loading files ...` | second loader pass skips SYS |
| 22 s | `Searching SCSI for hard disk... <Cancel>` | normal path |
| 60 s | Play/Record | boot complete (stock EPROM boot: by 45 s) |
| 65 → 67.5 s | Rec+Play → `Play/Record (Record Ready)` | panel input handled |

RAM `8010:10F5` reads `Vailixi 3.51 (` from 28 s to 60 s. Pages 44–60 hold
`0x0EC–0x0FC` from 7.16 s to 67.5 s, sampled every periodic callback. A stock
boot never loads the third PGR (`run/pgr_watch.lua`). On 3.12 EPROMs, the
guard message is on screen from 12 s through 60 s. **PROVEN (trace)**.

### 4.2 Where patches can go

| Target | File range | Runtime address | Rule |
|--------|------------|-----------------|------|
| OS code | `[0x30000, 0x74000)` | `CS:IP` with `file = (CS<<4)+IP − 0x80000` | Patchable. Example `B000:0207` = file `0x30207` |
| DGROUP (initialised data, strings) | `[0x20000, 0x27C92)` | `8010:X`, `X = file − 0x20000` | Patchable. Example `8010:1100` = file `0x21100` |
| BSS | `8010:7C92–FFB7` | — | Not in the image. The init walk zeroes it |
| BIOS / AMX / hand-off / IRQ | `[0x78000, 0x80000)` | `F800:`–`FFFF:` | **Not patchable.** EPROM stays mapped. The builder rejects it |
| Page-61 file image | `[0x74000, 0x78000)` | — | Not mapped by any table ([`patch_space.md`](notes/patch_space.md)) |
| Low bank | `[0x00000, 0x20000)` | — | Not mapped under XA=1. The builder rejects it |

The builder enforces the ranges. It also checks that the old bytes match the
stock image and that each patch keeps its length. **PROVEN (code)**.

Code cave (**HYPOTHESIS**): file `[0x707C8, 0x74000)` is 14,392 bytes of `FF`
padding inside the relocated code range, at logical `0xF07C8–0xF3FFF`. In a
Route A mod it is RAM and ships in the image, so you can put new code there
and reach it with a patched `CALL FAR`/`JMP FAR`. Two things are open. No
direct far transfer targets it, but all-paths "never read" is
**UNDETERMINED**. The builder only supports same-length patches, so to fill
the cave, write each chunk as a `FF…` → code patch.

### 4.3 Author a patch

1. **Find the bytes.** Locate the consumer, not just the bytes: the
   instruction that pushes the string or the branch you want to change
   ([`AGENTS.md`](AGENTS.md) recovery order). String consumers:
   `analysis/string_scan.json`. Instruction bounds: `tools/v53_decode.py`.
2. **Check the decode.** `ndisasm` and Capstone mis-decode `0F E0`/`0F F0`
   (`BRKXA`/`RETXA`). Scan your window for those bytes before trusting a
   listing.
3. **Keep lengths.** Replace an instruction with one of the same length, or
   pad with `90` (`NOP`). A new string must fit the old slot; pad with the
   original terminator.
4. **Check every other consumer.** A DGROUP string or code path may have
   more than one reader. `tools/floppy_loader.py` shows the style: every
   string it pins has exactly one consumer.
5. **Write the spec** in `MPC3000_builds/mods/<NAME>.args`, one argument
   per line, file offsets in hex:

   ```
   --name=DEMO351
   --patch=21100:30:31
   ```

   `NAME` is 1–8 characters of `A–Z 0–9 _` (the builder checks).
6. **Build:**

   ```sh
   cd MPC3000_builds
   python3 tools/build_mod_sys.py @mods/DEMO351.args
   # → out/DEMO351.SYS (310,640 bytes), out/DEMO351.img (1.44 MB FAT12)
   ```

   With no `--patch`, the builder applies the demo patch (`3.50` → `3.51`).
   `@mods/DEMO351.args` produces a file byte-identical to the default build.

---

## 5. Route B — replacement OS

### 5.1 Contract at your first instruction

**PROVEN (code)**, [`floppy_loader.md`](notes/floppy_loader.md) §5–§7:

| Item | Value |
|------|-------|
| `CS:IP` | `(load + e_cs) : e_ip`, load = `6900` (3.12/3.50) or `7000` (3.08/3.11) |
| `SS:SP` | `(load + e_ss) : e_sp`. Both 0 → `0040:69C4` (BIOS stack; replace it) |
| `DS` / `ES` | `0040` / `= CS` |
| `IF` | 0 |
| XA / PGR | XA=1, third PGR |
| `IVT[8]` | `FB93:0059` (`INT 42` / `OUT C010h,60h` / `IRET`) |
| ICU | last write `OUT C011h,FFh`. "All masked" is **HYPOTHESIS** (`U-C0XX`) |

### 5.2 MZ rules (`INT 45` = `F800:0143`, identical in all four ROMs)

1. `MZ` signature (`ZM` is rejected). `e_cp`/`e_cblp` must describe the
   real file size. The builders compute them.
2. `e_cparhdr ≥ 2`. `e_lfarlc` small: `INT 45` reads that many bytes into
   `0040:642B` with no bound, and ≤ `3Eh` is proven by 3.16.
3. Relocations are applied (4-byte `INT 41` read per entry, slow). Link for
   any base. Never assume the load segment.
4. Ignored: `e_minalloc`, `e_maxalloc`, `e_csum`, `e_ovno`. No overlays.
   **No size check.**
5. Image + BSS + stack must end below logical `0xF4000`: 569,344 bytes from
   `0x69000` (3.12/3.50), 540,672 from `0x70000` (3.08/3.11). Above that is
   page 61 (`0x500000`); writing it is **UNDETERMINED**.
6. Do not overwrite `0040:63EC–0040:6DC4` (20-bit `0x067EC–0x06DC4`: MZ
   header copy, name, relocation buffer, BIOS stack) until `INT 45` has
   returned, which it has by your entry. After entry, the BIOS services you
   call may still use `0040:` data. Treat it as reserved (**HYPOTHESIS**:
   the full BIOS data footprint is not audited).

### 5.3 BIOS services you can call

| Service | Status |
|---------|--------|
| `INT 43` AX=4, `BL` = character: text to the LCD, CR/LF handled | **PROVEN (trace)** by the canary and the Route A guard. [`int43_ax4.md`](notes/int43_ax4.md) |
| `INT 43` AX=1/2/3/5/6/7 | Encodings **PROVEN (code)**. Controller meaning **UNDETERMINED** (`U-LC7981`) |
| `INT 41` AX=2 open / 3 close / 4 read / 9 find-first / 0Ah find-next | **PROVEN (code)** as used by `INT 45` and the loader. Other functions not audited |
| `INT 45` MZ load (`DS:DX` name, `ES` segment) | **PROVEN (code)**. Chain-loading a second file is possible in principle, **HYPOTHESIS** |
| Panel, pads, sampling, MIDI, SCSI | No BIOS API identified. A replacement OS must drive the hardware itself. See the `d2x_*.md`, [`panel_link.md`](notes/panel_link.md) and [`front_panel.md`](notes/front_panel.md) notes; much of the hardware behaviour is **UNDETERMINED** |

### 5.4 Minimal example

`tools/build_canary.py` builds `STARTUP.SYS`: `CLI/CLD`, `DS=SS=CS`,
`SP=0100`, `STI`, print a string through `INT 43` AX=4, spin. It shows
`Vailixi 3.51 (---/--/----)` at 12 s (`test_floppy_canary_prints_351`,
**PROVEN, trace**). Start new OS work from that shape.

Instruction set: the proven stubs use only 8086 forms. V33-core 80186
instructions are **HYPOTHESIS** (NEC datasheet, not verified here). Never
emit `0F E0`/`0F F0` unless you mean `BRKXA`/`RETXA`.

---

## 6. Test before deploying

Run every step in order. Do not skip one because a later step passed.

### 6.1 Build-time checks (automatic)

`build_mod_sys.py` rejects: a patch outside DGROUP/code, stale old bytes,
a length change, an unsafe copy overlap, and a non-8.3 name.
`build_canary.py` replays the `INT 45` header checks and the directory
match.

### 6.2 Boot in the emulator (headless)

```sh
cd MPC3000_builds
python3 -m emu.mpc3k --bios vailixi --floppy out/DEMO351.img --times 5,15,20,30,60
```

The runner sets `-video none`, `SDL_VIDEO_DRIVER=dummy` and
`SDL_MAC_BACKGROUND_APP=1`, so no window opens. `--bios default` is 3.12;
use it to confirm the Route A guard.

### 6.3 Prove your code is what runs

A boot that reaches Play/Record does not prove the mod ran: the EPROM OS
also reaches it. Use at least one of:

- A visible marker: a patched string that appears on screen (Route A demo:
  banner at 15–19 s).
- RAM: pass `words=[…]` to `emu.mpc3k.run` and read DGROUP words at `8010:X`.
- Page table: `extra=["-autoboot_script", "run/pgr_watch.lua"]` logs pages
  44–60. `0EC…0FC` after the load means the OS pages are RAM (your copy).
  `02C…03C` means ROM.

### 6.4 Exercise behaviour

Drive the panel with `press=[(t, port, field, hold)]` (HLE) or `panel=` (link
frames). The Route A test presses Rec+Play at 65 s and expects
`Play/Record (Record Ready)`. Allow about 15 s more than an EPROM boot.

### 6.5 Lock it in

Add a case and a test in `emu/test_mpc3k.py` (pattern: `mod350`,
`mod350_on312`), then run:

```sh
cd MPC3000_builds && python3 -m unittest emu.test_mpc3k
cd ../MPC3000 && python3 tools/verify_boot_slice.py && python3 -m unittest tests.test_boot_slice
```

---

## 7. Deploy to a real machine

**UNDETERMINED: not yet done for any mod from this repo.** Record the first
hardware result against these steps.

1. Use a freshly formatted FAT12 floppy. The 3.16 PDF says to copy the SYS
   to a "blank/fresh floppy".
2. Either copy `out/<NAME>.SYS` to the root, or write `out/<NAME>.img` raw
   to the disk.
3. Make it the **only** `*.SYS` in the root. The loader takes the first
   match in directory order. A bad first SYS is fatal (`type 11h`) and
   there is no fallback. **PROVEN (trace)**.
4. Normal attributes only. Hidden, system, volume and directory entries are
   skipped (`TEST [BX+0B],1E`). **PROVEN (code)**.
5. Insert, power on, and wait (about 60 s for Route A in MAME; real timing
   **UNDETERMINED**). Remove the disk and power-cycle to return to the EPROM
   OS.

Media density: the BIOS has geometry slots for 720K (9 sectors/track), 800K
(10) and 1.44M (18), and the MAME runs use 1.44M. Whether the fitted drive
reads HD media is **UNDETERMINED** (`U-PHYS`). If 1.44M fails, try 720K:
`mformat -f 720`, and a Route A image (310,640 bytes) fits. 720K has not been
traced.

Startup files: with Route A, the relocated OS still runs the APS / PGM / ALL
steps, so such files on the mod disk should load on the second pass.
**PROVEN (code)**, not traced with those files present.

---

## 8. Failure signatures

| Symptom | Cause |
|---------|-------|
| `System Error … software bug of type 11h` forever | First SYS is not a valid MZ, or a short read (`INT 45` AH≠0). **PROVEN (trace)** |
| `Mod needs Vailixi 3.50 EPROMs`, halt | Route A on non-3.50 EPROMs. **PROVEN (trace)** |
| Straight to `Searching SCSI…`, EPROM OS | No matching SYS: wrong extension, attribute bits `1Eh`, not in the root, or the floppy test failed. **PROVEN (trace)** for "no SYS" |
| Stuck at `Searching floppy for startup files...` | The floppy-test wait loop has no bound (`E7F5:0440`). Hardware cause **UNDETERMINED** |
| EPROM banner repeats, reload loop | SYS step not skipped in a relocated OS. The builder always applies `0x30207` `75→EB`. **HYPOTHESIS** (never observed, because it is always applied) |
| Boots to stock 3.50 behaviour | Patch not reached, or a different SYS loaded. Run §6.3 |

---

## 9. Status

| Claim | Status |
|-------|--------|
| Floppy loader present, same shape, in 3.08 / 3.11 / 3.12 / 3.50 | **PROVEN (code)** |
| 3.16 loads from floppy on all four | **PROVEN (trace)** |
| Selection: first `*.SYS`, any 8.3 name, fatal if bad | **PROVEN (trace)** |
| Route A boots, runs from RAM for the session, takes panel input, 484K | **PROVEN (trace)** |
| Route A guard on 3.12 | **PROVEN (trace)** |
| Route B entry contract and MZ rules | **PROVEN (code)** |
| Route B text output via `INT 43` AX=4 | **PROVEN (trace)** |
| Code cave `[0x707C8, 0x74000)` unused | **HYPOTHESIS** |
| No single-word PGR write reverts pages 44–60 later | **PROVEN (trace)** for 67.5 s of one boot. All-paths **UNDETERMINED** ([`patch_space.md`](notes/patch_space.md) §4) |
| Real hardware: drive density, timing, any mod boot | **UNDETERMINED** (`U-PHYS`) |
| 720K / 800K disks | **UNDETERMINED** (not traced) |
| Effect of writing page 61 (`0x500000`) | **UNDETERMINED** |

---

## 10. Rules

1. Floppy only. The SCSI loader never loads a SYS.
2. Never write under `07-rom/`. Build output goes to `MPC3000_builds/out/`.
3. Route A needs 3.50 EPROMs. The stub checks; do not remove the check.
4. Patch only DGROUP and OS code. BIOS behaviour cannot be changed from floppy.
5. Every patch states its file offset, `CS:IP` or `DS` offset, old bytes, new
   bytes and consumer, tagged PROVEN / HYPOTHESIS.
6. Every mod gets an emulator test that proves its own code ran (§6.3).
7. Record hardware results. Until then, the hardware column stays
   **UNDETERMINED**.
