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

**Hazard in stock 3.16 (PROVEN by addresses; MAME, one execution per set):**
with `L = 0x6900` (3.12 and Vailixi 3.50 EPROMs) the pool overlaps logical
`0x69000–0x6FFFE`, which is 3.16's own image offsets `0x0000–0x6FFE`. That
range holds live code, including relative segment `0x0427` (the most
referenced code segment, 1,336 relocations). The pool reports this space as
free (439K). In MAME, stock `M3K316.SYS` hangs at Song after a short
recording on `default` and `vailixi` (Results below). On 3.08/3.11
(`L = 0x7000`) the pool ends just below the image.

**Fix in the port (`mods/entry316.inc`):** before jumping to 3.16, the entry
routine sets the pool-end immediate at image `0x48535` (`MOV BX,6FFF`) to
`L−1`, so the pool ends at `L*16−2`: unchanged on 3.08/3.11, 28K smaller on
3.12/3.50 (`0x6DFFE` → `0x66FFE` bytes; 411K free). **PROVEN (code, review
2026-10-05):** the immediate's only reader is `4852:0006`, whose only caller
(`0x3419B`) runs it once after start-up; every reader of the pool variables
`[8B13]..[8B19]` uses the variables, so ALL/SEQ data larger than the smaller
pool is refused rather than written over code. What 3.16 shows then is
**UNDETERMINED**.

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
The builder's own loader simulation agrees at both `L`. The builder is now
`mods/route_c.py`.

## Differences from Vailixi that change features

- The Edit Sound page exists with the same soft keys (`<Ply/Stp> <Best st>
  <Play X> <Do>`), `Do:` field and `TEMPORARY999`; the Program/Sounds menu has
  the same spare slot for "0. Mute groups" (item 9 is "MIDI sample dump").
- Vailixi's Other → Extra settings (`EDIT SND '<Do> SOFT KEY 4' safe lock`,
  `Mute audio during EDIT SND processes`) do not exist in 3.16. CHOP must
  mirror 3.16's own Do handlers instead (being mapped).
- Lineage: 12-byte code windows of the hooked Vailixi routines recur
  verbatim in 3.16 at 29–63%; `CFC6:0CE9` (audition entry) matches image
  `0x21BBF` over 0x8C bytes once relocated segment words are masked
  (`mov dx,539D` against `A2AE`).

## Results of the first full build (2026-10-05, MAME, one execution per set)

These results are for the first build (`c5fda657…`). The build after the review
(below) differs by one removed lock re-take and the load-segment bound; every
emulator suite has since passed on it ("Emulator suites on 3.16").

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


## Adversarial review (2026-10-05, read-only, code; no MAME)

| # | Finding | Disposition |
|---|---|---|
| 1 | The lock re-take after the voice allocator (`mute_voice.inc`, all profiles) added a yield between the allocator choosing a channel (it writes only `[E284]`) and `0B2D` marking it busy; a task waiting on resource 1 could take the same channel. PROVEN (code); the race is HYPOTHESIS. | Removed. The re-take before the allocator stays: it repairs only the drop caused by the mute stops, before any channel is chosen. The allocator's own MONO/Cutoff stops drop the lock in stock as well. |
| 2 | The loader simulation did not model `entry316` (copy count, pool rule). | Builder runs it: `entry316` must assemble to the modelled routine (`ENTRY316`, read from the NASM listing); `cave_end` = cave size; the copy uses its `CX` (`2*CX` = size or size+1) and the home must equal the cave relocated independently; the halt immediate must be the highest `L−1` whose home ends below page 61 (`0x72D8`) and every `L` must pass it; the pool rule runs on the guard constants as assembled and must leave `min(L−1, 6FFF)` (`68FF`, `6FFF`). |
| 3 | Targets were shape-checked against the unpatched image (`T_D0C0_0B19` sits on the `chop_sound_delete` hook, as intended). | Builder compares the patched image; a target's compared instructions may not reach a patch unless it is listed in `HOOK_TARGETS` (only `T_D0C0_0B19`), which must start a patch and is compared on its stock bytes. Compared bytes holding `0F E0` / `0F F0` (BRKXA/RETXA, which ndisasm mis-decodes) are an error. |
| 4 | Loose relocation checks: `0000`/`FFFF`/`4853` accepted anywhere; the unrelocated-word scan covered only data segments. | Builder pins `FFFF`, `4853` and `0000` to their three `entry316` sites; every other relocated word must be a profile segment (`T_` target segments, DGROUP, sound, player, cave). No unrelocated word within one listing line may equal one of those, except the 23 listing-proven instruction bytes in `NOT_OPERANDS` (21 × `CMP AX,[CS:x]` = `2E 3B 06`, the word being `063B`; 2 × `MOV DX,0020h` = `BA 20 00`, the word being `20BA`). Far transfers into DGROUP or the sound segment are rejected. |
| 5 | No bound on `L`: the home crosses page 61 when `L > 0x72D9` (cave `0x3264` bytes). | `entry316` halts in that case instead of writing NVRAM. |
| 6 | The pool is 28K smaller with `L = 0x6900`. | Recorded above and in the bench checklist. |
| 7 | Stale notes. | Fixed. |

Build after the review: `WAVE316.SYS` 470,948 bytes, SHA-256
`c3eeefbbe8e5a3cfa6176ff9f8e261c6ca1244a7a0d9ce42777be017671be303`; cave
12,900 bytes (logical `0xE7000–0xEA264` with `L = 0x6900`,
`0xEE000–0xF1264` with `L = 0x7000`); 7,122 relocations; 86 far transfers;
112 relocated cave words. The hardened builder checks (rows 2–4) pass on this
build with its output unchanged; `tests/test_build_wave316.py` pins the
hashes and breaks each check once on in-memory inputs.

## Emulator suites on 3.16 (2026-10-05, MAME, one execution per set)

Every suite except `test_mpc3k` (stock emulator checks) runs its cases on the
316 profile as well as on the Vailixi builds (`capture`; `generic` for its
subset). Release run (`python3 -m emu.harness_release`, 23 suites in four
groups) on `port-316` at `9a9ad8e`, build `c3eeefbb…`, 3.16 on `default`,
`vailixi`, `v311` and `v308`: **150 tests, 0 failures, 0 errors, 0 skipped**
(boot 7, CHOP 10/1/6/1, `test_mpc3k` 21, mute UI 8, range 3, apply-all 5,
audition 2, voice 12, persistence 4, disk full 6, lifecycle 2, zones 10,
zone navigation 5, bursts 3, harness lifecycle 7, long 6, physical 9,
numeric 9, numeric order 5, playback 8).

Where 3.16 behaves differently the suites assert 3.16's behaviour:

- Do list: 8 stock options, CHOP ZONE is index 8 (3.16 `0B72:0B0A`
  `cmp bx,7`; Vailixi `B99A:0B05` `cmp bx,9`). COPY ZONE-> SND and TRUNC SFT
  ST+END are Vailixi-only (`test_harness_lifecycle` `do1`, `do7`: `SKIP_316`).
- No safe lock and no Edit Sound mute: entering Edit Sound stops a Rec+Play
  transport (DS `A49B` 8 → 0 at the `6` key), so CHOP runs and writes no port
  `6Ah`. `test_wave_chop_safety` `unlocked_running` (it turns the Vailixi
  setting off) is `SKIP_316`.
- Default pad map: pad 1 = note 37 … pad 64 = note 98, a 64-byte table at 3.16
  DGROUP `087F` (image `0x6123F`) that image `0x493D` copies to DGROUP `8064`
  (PROVEN, code); Vailixi pad 1 = 35.
- Timeline: boot-relative times are 13 s later (Soft Key 4 cancels the SCSI
  search at 33.0 s against 20 s); the second of two sounds is selected 5.0 s
  after the first `<Load>` (4.5 s on Vailixi).
- `test_wave_chop` `memory_full` uses a 492,000-frame source: with
  `WAVE316.SYS` the floppy has 986,624 bytes free, too few for the
  540,000-frame source; 492,000 frames still exceed half of the 980,992 free
  sound words, so the refusal is the same.
- The disk-full stock control boots `M3K316.SYS`; `test_incompatible_rom_rejected`
  stays capture-only (`WAVE316.SYS` has no ROM guard by design).

Stock 3.16 addresses only the tests use (instruction-identical windows
against Vailixi, rechecked by the orchestrator; not in `profile_316.inc`):

| Vailixi | 3.16 relative | Use |
|---|---|---|
| `D1F7:0054` | `2325:004C` | start register `OUT 62h` |
| `D213:001B` | `2341:0013` | release register select (`OUT 60h`) |
| `D21F:001C` | `234D:0014` | stop register select (`OUT 60h`) |
| `CFB3:0008`, `CFB3:0125` | `20DA:000E`, `20DA:012B` | note-event entry; its note-off stop call |
| `CF37:0071` | `205E:0077` | the allocator's Cutoff stop call |
| `C20F:0417` | `1396:041D` | PGM load: return after close (range injection) |
| `E86E:0273` | `3E8F:026F` | PGM save: return after close (range injection) |

Physical behaviour: all bench gates pass on one machine (Vailixi 3.50 EPROM, `L = 0x6900`); other EPROMs are **UNDETERMINED** on hardware ([bench316_checklist.md](bench316_checklist.md)).

## Status

| Work | State |
|---|---|
| Hook/target/data mapping, seven feature packages | done, cross-checked |
| Memory above 3.16's extent, all four EPROM sets, MAME | no access in 355 s of heavy use |
| Cave source profile refactor (byte-identical Vailixi builds) | done |
| Route C builder core and loader simulation | proven in MAME with a probe cave |
| Full build, smoke, pixel check, pool fix | done (MAME) |
| Emulator suites on 3.16, all four sets | done (MAME): 150 tests, 0 skipped |
| Bench run of `WAVE BENCH 08` | all gates pass on hardware (Vailixi EPROM, 2026-10-06; bench316_checklist.md) |
| Public beta `PMONEY BETA 1.0` | next: boot banner, rebuild, release run, beta package |
