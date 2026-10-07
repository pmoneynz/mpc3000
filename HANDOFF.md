# Handoff: MPC3000 OS mods (Cursor → Claude Code)

Paste this whole file as your first message in Claude Code, started in
`/Users/peterwadams/Documents/MPC3000`.

---

## Who you are working for, and how

Peter is reverse-engineering the Akai MPC3000 (NEC V53 CPU) OS and building
the most accurate MAME emulator of it. The goal now is to **build, test and
deploy real OS mods through the ROM floppy loader**.

Working rules (non-negotiable):

- Be direct and brutally honest. Deal in proven facts only.
- Tag every technical claim **PROVEN** (cite code or trace), **HYPOTHESIS**, or
  **UNDETERMINED**. A trace is one execution; all-paths claims need writers,
  aliases and entry domains.
- Cite linear-file offsets, `CS:IP`, 20/24-bit addresses and the PGR/XA mode
  that makes them true.
- Efficient, elegant, simple code. Match the surrounding style. Comments only
  for constraints the code cannot show.
- **Never modify `07-rom/`.** Generated output goes to `build/` (gitignored).
- Do not invent LC7981, TE7774, PAL or panel behaviour. Unknown hardware is a
  named boundary (`U-PHYS`, `U-C0XX`, `U-LC7981`, …).
- `ndisasm`/Capstone mis-decode `0F E0`/`0F F0` (`BRKXA`/`RETXA`). Use
  `tools/v53_decode.py` for instruction bounds; check every window.
- Physical tests are deferred: record the missing observation and keep doing
  software-verifiable work.
- Do not commit or push unless Peter asks.

The full rule set is in `AGENTS.md` and `PROJECT_GOAL.md`
(`PROJECT_GOAL.md` wins conflicts). **First action:** create `CLAUDE.md`
containing the single line `@AGENTS.md` so Claude Code loads the rules every
session (Claude Code reads `CLAUDE.md`, not `AGENTS.md`).

---

## Read these first (in order)

1. `MODDING_HOWTO.md`: the mod procedure, both routes, test sequence,
   deployment, failure signatures, status table. **This is the spec for the
   work.**
2. `notes/floppy_loader.md`: every loader address, string, the `INT 45` MZ
   rules and the memory map, for all four EPROM OSes.
3. `emu/README.md`: pinned MAME build, romset, harness usage.
4. `notes/emulator.md`: what the emulator proves and what it does not.
5. `STATUS.md`, `notes/named_unknowns.md`: the rest of the RE project.

---

## Repository and environment

| Item | Value |
|------|-------|
| Repo | `/Users/peterwadams/Documents/MPC3000`, remote `origin` = <https://github.com/pmoneynz/mpc3000> (**private**: it holds Akai ROM dumps and manuals; keep it private). Old Cursor remote kept as `cursor`. `gh` is logged in as `pmoneynz` |
| Last commits | `b9078a4` (harness + mods moved in), `ae086b9` (loader pinned + HOWTO) |
| MAME driver | Fork <https://github.com/pmoneynz/mame>, branch `mpc3000-accuracy`, pinned `14ffa559` (upstream base `9ede38cb`); changed files: `emu/README.md` |
| MAME checkout / binary | `../MPC3000_builds/mame/`, binary `../MPC3000_builds/mame/mpc3k` (override with `MPC3K_MAME`). Shallow clone: remote `fork` = GitHub fork, `origin` = upstream mamedev |
| MAME rebuild | `cd ../MPC3000_builds/mame && make SUBTARGET=mpc3k SOURCES=src/mame/akai/mpc3000.cpp TOOLS=0 NOWERROR=1 -j14` |
| Host tools | Python 3.14, NASM 2.16.03, GNU mtools 4.0.49, macOS |
| Line endings | `core.autocrlf=true`, so commits print LF→CRLF warnings. Harmless |

Layout:

| Path | Role |
|------|------|
| `mods/build_mod_sys.py` | Route A builder: patched Vailixi 3.50 relocated to RAM → `build/mods/<NAME>.SYS/.img` |
| `mods/mod_stub.asm` | Route A stub: 3.50 BIOS checksum guard, copy OS code + DGROUP, jump `FAC0:0134` |
| `mods/*.args` | One mod per file (`--name=`, `--patch=FILE:OLD:NEW`). Example `DEMO351.args` |
| `mods/build_canary.py` | Route B minimal MZ that prints a line via `INT 43` AX=4 |
| `emu/mpc3k.py` | Headless runner (`run()`, `disk()`), fresh NVRAM/cfg per run |
| `emu/romset.py` | Builds `build/roms/mpc3000/` from `07-rom/` + placeholders (panel ROM `0xFF`, `hd61830.bin` from `emu/font/glyphs.json`) |
| `emu/test_mpc3k.py` | Emulator regressions (skip if MAME/nasm/mtools missing) |
| `emu/lua/pgr_watch.lua` | Logs PGR pages 44–60: `0EC…` = RAM copy running, `02C…` = ROM |
| `emu/lua/loader_bp.lua` | Breakpoints on loader call sites (`-debug -debugger none -log`) |
| `tools/` | Static analysis: `floppy_loader.py`, `v53_decode.py`, `verify_boot_slice.py`, … |
| `tests/test_boot_slice.py` | Static-fact regressions |

Commands (repo root):

```sh
python3 tools/verify_boot_slice.py            # regenerate/verify pinned facts
python3 -m unittest discover -v               # 25 tests: 13 static + 12 emulator (~65 s)
python3 mods/build_mod_sys.py @mods/DEMO351.args
python3 -m emu.mpc3k --bios vailixi --floppy build/mods/DEMO351.img --times 5,15,20,30,60
```

`--bios`: `vailixi` (3.50), `default` (3.12), `v311`, `v308`. No 3.10 dump.
The runner is headless (`-video none`, `SDL_VIDEO_DRIVER=dummy`,
`SDL_MAC_BACKGROUND_APP=1`). **Keep it that way: Peter does not want MAME
windows taking over his screen.** Runs are deterministic.

---

## What is proven (MAME traces unless marked code)

- The floppy `*.SYS` loader exists with the same shape in 3.08/3.11/3.12/3.50
  (code). OS 3.16 (`M3K316.SYS`) boots from floppy on all four (trace).
- Selection: first `*.SYS` in the root directory, any 8.3 name; a bad first
  SYS is fatal (`software bug of type 11h`), with no fallback (trace).
- Hand-off `FB93:0066`: `INT 10` loads the third PGR (logical
  `0xB0000–0xF3FFF` → RAM pages `0xEC–0xFC`), `INT 45` loads the MZ at
  `6900:0000` (3.12/3.50) or `7000:0000` (3.08/3.11), then a far jump with
  `IF=0`, `DS=0040`, `ES=CS` (code).
- **Route A works:** `MOD350.SYS` (3.50 + "3.51" string patch + mandatory
  `0x30207` `75→EB`) shows the `Vailixi 3.51` banner at 15 s and 484K
  sequencer memory. It reaches Play/Record and accepts Rec+Play (Record
  Ready at 67.5 s). PGR pages 44–60 stay `0EC–0FC` from 7.16 s to 67.5 s.
  On 3.12 EPROMs the guard prints `Mod needs Vailixi 3.50 EPROMs` (trace).
- Route B entry contract and MZ rules (code); text output via `INT 43` AX=4
  (trace).
- The BIOS pages (file `0x78000–0x7FFFF`: `F800` BIOS, `FB00` AMX, `FB93`,
  `FAC0`) stay EPROM. **A floppy mod cannot patch them.** Patchable: DGROUP
  file `[0x20000, 0x27C92)` (`8010:X`, `X = file − 0x20000`) and OS code
  `[0x30000, 0x74000)` (`file = (CS<<4)+IP − 0x80000`).

## Not proven: do not claim these

- **Nothing has run on real hardware.** Drive density (1.44M vs 720K),
  timing, disk-change behaviour: `U-PHYS`.
- 720K/800K images: not traced.
- Code cave file `[0x707C8, 0x74000)` (14,392 bytes of `FF` in the relocated
  code range, logical `0xF07C8–0xF3FFF`): unused is **HYPOTHESIS**
  (all-paths read UNDETERMINED).
- "Diskless reboot after a mod returns to the EPROM OS": HYPOTHESIS (3.16 PDF
  says so; not traced).
- No single-word PGR write reverts pages 44–60: proven for one 67.5 s boot
  only; all-paths UNDETERMINED (`notes/patch_space.md` §4).
- APS/PGM/ALL startup files on a Route A disk load on the second pass: code
  only, not traced.
- Instruction set: proven stubs use 8086 forms only; 80186 forms on the V33
  core are HYPOTHESIS.

---

## Next work (suggested order; confirm priorities with Peter)

1. **First real mod.** Ask Peter which behaviour to change. For each patch:
   find the consumer (`analysis/string_scan.json`, `tools/v53_decode.py`),
   keep lengths, write `mods/<NAME>.args`, and add a test in
   `emu/test_mpc3k.py` that proves *its own* code ran (a visible marker, RAM
   words, or `pgr_watch.lua`). Reaching Play/Record proves nothing: the
   EPROM OS gets there too.
2. **Cave support in the builder**, if a mod needs new code: assemble a NASM
   blob for the cave, emit it as `FF…`→code patches, and call it with a
   same-length patched `CALL FAR`. First prove the cave is unread on the
   paths the mod exercises.
3. **720K trace**: `mformat -f 720` image of DEMO351 in the emulator (the
   BIOS geometry slot exists at `F800:0325`).
4. **Diskless-reboot trace** after a mod, to settle the volatility claim.
5. **Hardware deployment** when Peter has a machine and disk: follow
   `MODDING_HOWTO.md` §7 and record results in the §9 status table. Start
   with `build/mods/vailixi350-canary.img` (smallest), then `DEMO351.img`.
6. **Route B**: audit further `INT 41`/`INT 43` functions before promising
   anything to a replacement OS.

When the MAME driver changes: commit and push the fork (`git push fork
mpc3000-accuracy` in `../MPC3000_builds/mame`), then update the pinned
commit in `emu/README.md` and `notes/emulator.md` in the same commit as the
tests that depend on it.

---

## Gotchas learned the hard way

- `emu.mpc3k.run()` builds MAME's environment from scratch (`PATH=/usr/bin:/bin`
  plus probe variables). Other environment variables do not reach the Lua
  scripts; pass paths via the script location (see `emu/lua/*.lua`). An
  earlier breakpoint run hung for exactly this reason.
- LCD text rows use `.` for spaces in some glyph states; compare with
  `.replace(".", " ")` where needed.
- The Route A build always applies `0x30207 75→EB`. Without it, the relocated
  OS would try to load the SYS again.
- The first boot banner (5 s) is always the EPROM OS. The mod's banner
  appears at about 15–19 s. Sample densely or read RAM.
- Only one `*.SYS` per disk. A leftover `M3K316.SYS` sorted first will load
  instead of the mod.
