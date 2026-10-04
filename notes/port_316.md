# Porting the WAVE / CHOP / mute-group mods to OS 3.16

**Goal:** one `.SYS` that runs on every MPC3000, whatever its EPROM OS (3.08,
3.11, 3.12, Vailixi 3.50 — licensed or not). **Started:** 2026-10-05.
Background and the reason Vailixi cannot be the base:
[license_personalization.md](license_personalization.md).

## Base: `M3K316.SYS`

`07-rom/v3.16 maintenance upgrade/M3K316.SYS` (458,047 bytes, SHA-1
`b45b017721f0e59974e50de93040ccd1f973ad23`) is an MZ executable. **PROVEN
(header bytes):** header `0x7A00` bytes; load image `0x6833F` bytes; 6,998
relocations from file offset `0x3E`; entry `0000:0000`; `SS:SP` `7066:0100`;
`minalloc` `0x15C7` paragraphs. Every EPROM loader loads it at segment `L`
(`0x6900` on 3.12 and 3.50, `0x7000` on 3.08 and 3.11) and adds `L` to every
listed segment word ([floppy_loader.md](floppy_loader.md) §5–§7, §10).

In this note 3.16 addresses are **relative**: `seg:off` as stored in the image,
image offset = `seg*16+off`, runtime logical = `L*16` + image offset.

**PROVEN (code), 3.16 image:**

- Entry `0000:0000` is a C start-up: `SS:SP = 7066:0100`, `DS = ES = 609C`
  (DGROUP), zero BSS `DGROUP:7980..FC9E`, call three init entries from
  `6098:0004..0016`, `STI`, `JMP 0281:0034` (main). DGROUP is relative
  segment `0x609C`; its initialised part ends exactly at the image end
  (`0x609C0 + 0x7980 = 0x68340`).
- Highest relocated segment value is `0x7DFA`; image + BSS + stack end at
  relative paragraph `0x7DFB` (`minalloc`).
- No write to the page-register ports (`MOV DX,0FF00h` absent) and no
  `BRKXA`/`RETXA` (`0F E0` / `0F F0` absent): 3.16 keeps the loader's third
  PGR, so logical `A` in `0x00000–0xF3FFF` is physical `0x300000 + A`.
- 3.16 contains its own AMX kernel (KADAK copyright at image `0x47BF9`) and
  makes no genuine far call or jump into the EPROM BIOS/AMX.
- 3.16 also carries its own BIOS services. Start-up initializer entry 0 (table
  `6098:0004`, relocated far pointer) is `0009:0006` (image `0x96`, text
  "MPC-3000 BIOS 02/20/05"): it programs the timer and interrupt controller
  and installs its own `INT 41` (image `0x151`), `42`, `43` (`0x165`), `45` and
  `46` vectors in segment `0009`. After start-up 3.16 depends on the EPROM
  only for having loaded it.
- The sequence pool bound is chosen at image `0x48526`: `MOV AX,7DFA` −
  `7DF9` (both relocated, so always 1) → fixed pool `0x0200:0000` to
  `0x6FFF:000E`, i.e. logical `0x2000–0x6FFFE`, whatever `L` is.

**Hazard in stock 3.16 (PROVEN by addresses; exposure HYPOTHESIS):** with
`L = 0x6900` (3.12 and Vailixi 3.50 EPROMs) the pool overlaps logical
`0x69000–0x6FFFE`, which is 3.16's own image offsets `0x0000–0x6FFE`. That
range holds live code, including relative segment `0x0427` (the most
referenced code segment, 1,336 relocations). The pool reports this space as
free (439K), so a sequence that grows past about 412K would overwrite 3.16
code on those machines. On 3.08/3.11 (`L = 0x7000`) the pool ends just
below the image. **Proposed fix in the port:** before jumping to 3.16, the
entry routine sets the pool-end immediate at image `0x48535` (`MOV BX,6FFF`)
to `L−1`, so the pool ends at `L*16−2`: unchanged on 3.08/3.11, 28K smaller
on 3.12/3.50. Needs the user's decision and a MAME check.

## Architecture ("Route C")

The release file is `M3K316.SYS` with patched hook sites, one appended
segment (the cave) and an extended relocation table.

1. **Cave placement.** The cave (code + its writable data) is assembled at
   `org 0` and appended to the image at relative paragraph `B0 = 0x6834`
   (image end). That spot is 3.16 BSS, zeroed by 3.16's start-up, so it is
   only a staging area. The header entry `e_cs:e_ip` points at a routine in
   the cave that copies the cave to its home at relative paragraph
   `C0 = 0x7E00` (logical `L*16 + 0x7E000`), then far-jumps to 3.16's own
   entry `L:0000`. Offsets are identical in both places because the cave is
   `org 0`. 3.16's start-up then overwrites the staging area.
2. **Home bounds.** `0x7E000 + cave size` must stay below `0xF4000 − L*16`:
   `0x6000` bytes (24,576) with `L = 0x7000`, `0xD000` with `L = 0x6900`. Page 61
   (`0xF4000`) is NVRAM. Whether 3.16 ever touches `[L*16 + 0x7DFB0,
   0xF3FFF]` is being measured in MAME under heavy use; static evidence so
   far: no relocated segment above `0x7DFA`, fixed pool below the image.
3. **Relocations.** Every segment word becomes an MZ relocation, applied by
   the EPROM loader at load time (before the copy, which preserves the
   relocated values): hook sites in 3.16 code (`EA`/`9A` to the cave, value
   `C0`), cave calls into 3.16 code (relative 3.16 segment), the DGROUP
   segment (`0x609C`), the sound-record segment, and the cave's own segment
   (`C0`). Existing relocations inside replaced hook bytes are removed. The
   header has room for 794 more entries before `0x7A00`.
4. **Source.** One cave source for every profile. `mods/profile.inc` selects
   `profile_vailixi.inc`, `profile_capture.inc` or `profile_316.inc`; stock
   targets are `T_SSSS_OOOO` symbols named after their Vailixi address;
   `RELOC_PREV` marks each segment word and emits `__reloc_N` labels only
   in the 3.16 profile. The Vailixi builds must stay byte-identical.
5. **No ROM guard.** 3.16 depends only on BIOS interrupts that all EPROMs
   provide; the builder pins `M3K316.SYS` by hash and verifies every hook's
   original bytes.

**PROVEN (MAME, 2026-10-05, one execution per EPROM set):** a Route C test
file (`ROUTEC.SYS`: 62-byte probe cave, hook at image `0x2847` replacing
`CALLF 3F58:0000` in main, banner text patch at DGROUP `0x61B5A`) boots on
the `default` (3.12), `vailixi`, `v311` and `v308` sets: the banner reads
`RouteC 3.16 (02/20/05)`; at 45 s the cave home holds the relocated copy
(physical `0x3E7000` with `L = 0x6900`, `0x3EE000` with `L = 0x7000`), its
hit counter is 1 and its recorded CS is `L+0x7E00`; 3.16 reaches Play/Record.
The builder's own loader simulation agrees at both `L`. Builder:
`<scratchpad>/port/route-c/route_c.py` (to be moved into `mods/`).

## Differences from Vailixi that change features

- The Edit Sound page exists with the same soft keys (`<Ply/Stp> <Best st>
  <Play X> <Do>`), `Do:` field and `TEMPORARY999`; the Program/Sounds menu has
  the same spare slot for "0. Mute groups" (item 9 is "MIDI sample dump").
- Vailixi's Other → Extra settings (`EDIT SND '<Do> SOFT KEY 4' safe lock`,
  `Mute audio during EDIT SND processes`) do not exist in 3.16. CHOP must
  mirror 3.16's own Do handlers instead (being mapped).
- Lineage: 12-byte code windows of the hooked Vailixi routines recur
  verbatim in 3.16 at 29–63%; `CFC6:0CE9` (audition entry) matches image
  `0x21BBF` exactly over 0x8C bytes.

## Results of the first full build (2026-10-05, MAME, one execution per set)

`python3 mods/build_wave316.py`: `WAVE316.SYS` 470,944 bytes, SHA-256
`c5fda657b9e8c8514dc2c5c34e8a6c8d481dc54cdb420c9c61f75ecd6245a5ef`; cave
12,896 bytes at home paragraph `7E00` (logical `0xE7000–0xEA260` with
`L = 0x6900`, `0xEE000–0xF1260` with `L = 0x7000`); 7,123 relocations (132
added, 7 removed inside replaced hook bytes). The builder's checks passed: 87
cave far transfers each name a profile target whose first instructions have
the same shapes as the Vailixi routine; 113 relocated cave words, all known
segments; loader simulation at both `L`.

**PROVEN (MAME) on `default` (3.12), `vailixi`, `v311` and `v308`:**

- Boot banner `WAVE BENCH 08`; Play/Record; SINE441 loads from the image.
- Program/Sounds → 6 → Help opens the wave view; its 240×64 pixels equal
  `emu.wave_ref.screen` exactly (0 differing pixels on every set). Exit returns
  to Edit Sound. Program/Sounds → 0 opens Mute Groups; Soft Key 4 returns.
- The cave is relocated at its home; the pool-end immediate reads `68FF` with
  `L = 0x6900` and stays `6FFF` with `L = 0x7000`.
- Pool fix: after recording a sequence, Song shows its screen and later keys
  work on all four sets; with `L = 0x6900` no pool write reaches logical
  `0x69000–0x6FFFF` after entry and image bytes `0x0000–0x6FFF` are unchanged.
  Stock `M3K316.SYS` hangs at this step on `default` and `vailixi`
  (`<scratchpad>/port/work-memprobe/song_wave316.log`, `runs/song_ab_*`).

**Not yet run on 3.16:** the emulator suites (zones, CHOP, numeric,
playback, mute UI/voice/persistence, disk full); see
[port_316_harness_brief.md](port_316_harness_brief.md). Physical behaviour is
**UNDETERMINED**.

## Status

| Work | State |
|---|---|
| Hook/target/data mapping, seven feature packages | done, cross-checked |
| Memory above 3.16's extent, all four EPROM sets, MAME | no access in 355 s of heavy use |
| Cave source profile refactor (byte-identical Vailixi builds) | done |
| Route C builder core and loader simulation | proven in MAME with a probe cave |
| Full build, smoke, pixel check, pool fix | done (MAME) |
| Emulator suites on 3.16, all four sets | next |
