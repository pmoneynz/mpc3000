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
   entry `L:0000`. Since the universal layout (2026-10-17, "Cave space") the
   routine first moves a `L = 0x7000` load down to `L = 0x6900`, so `L` is
   `0x6900` at run time on every EPROM set. Offsets are identical in both places because the cave is
   `org 0`. 3.16's start-up then overwrites the staging area.
2. **Home bounds.** `0x7E000 + cave size` must stay below `0xF4000 − L*16`
   = `0xD000` bytes (53,248) with the runtime `L = 0x6900` of every set (before
   the universal layout: `0x6000` = 24,576 with `L = 0x7000`). Page 61
   (`0xF4000`) is NVRAM. See "Cave space" below for the other limits. Whether 3.16 ever touches `[L*16 + 0x7DFB0,
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

## Beta files on stock systems (2026-10-06, MAME, one execution per set)

A PGM and an APS saved by the beta (mute trailer included), one program of the
APS renamed `BETAPGM_01` as a marker, load on stock `M3K316.SYS` (`default`,
`v308`) and on the EPROM systems without a STARTUP.SYS (`vailixi`, `default`
3.12, `v308`): the PGM by Disk → 7 → Load becomes `1-SOURCE2` exactly as a
native PGM control does, the APS loads at start-up with `1-BETAPGM_01` active,
and no screen shows an error. The trailer is ignored there. `v311` not run.

## Boot snapshots (2026-10-07, MAME, one execution of the suite set)

`EmuSuite` cases resume from a per-profile MAME save state instead of booting
cold (`emu/harness.py`, `boot_snapshot`; `MPC3K_SNAPSHOT=0` disables). Vailixi
profiles save 0.5 s before the Soft Key 4 cancel and reinsert the case floppy
on resume; 316 profiles save at entry316's first write to the cave home, before
3.16 reads the floppy. Needs the fork's save-state support (`midiin`
re-seek, `te7774` channel state, `MACHINE_SUPPORTS_SAVE`).

Every `emu.test_*` suite (default BIOS sets `default`, `v308`) on the same
sources and binary: cold, 150 tests OK, 0 skipped, 1353 s; with snapshots,
150 tests OK, 0 skipped, 1019 s (MAME `d651a20c` plus the save-state
changes, uncommitted then). Repeated on the pinned fork `14ffa559`: cold and
with snapshots, 150 tests OK, 0 skipped each (wall times not comparable: the
host was loaded by other jobs). **PROVEN (trace)** for these cases only: a
case whose assertions do not depend on the boot could still differ; boot-path
suites set `SNAPSHOT = False`.

## SCSI reader stack (2026-10-16, stock 3.16 defect, fixed in the cave)

Addresses are relative 3.16 (image offset = `seg*16+off`, runtime logical =
`L*16` + image offset, physical = `0x300000` + logical; 3.16 runs with the
loader's third PGR and no `BRKXA`).

**Defect (stock and PMONEY).** The SCSI partition reader `2AB2:04F7` (image
`0x2B017`, Vailixi `D470:05B6`, same bytes) opens `PUSH BP / MOV BP,SP /
SUB SP,100Eh`: a 4 KB sector buffer at `[bp-100Eh]` plus locals
`[bp-0Eh..-2]`. With a SCSI disk active, Disk 7 enters it on the UI task with
`SP = 07D2`, so `SP` wraps to `F7C2` and the frame and its callees write at
`73E1:F6xx..FFFF` = image `0x835xx..0x83E0F` (deepest seen `0x8350A`), above
3.16's extent (`0x7DFB0`) and inside the range the cave home grows into.

| Fact | Evidence | Tag |
|------|----------|-----|
| UI task (create-table record 7, image `0x483CA`): `0281:0034`, `SS:SP 73E1:3E80` (16,000 bytes); task 6 is `73A2:03F0`, so UI `SS:0000` (image `0x73E10`) is task 6's initial-SP word (`FFFF`, written at image `0x40FE3`) | table bytes, init code | PROVEN |
| Disk 7 page `077D:042D` (image `0x7BFD`) opens `SUB SP,3652h` (13,906 bytes), the only frame in 3.16 code above `100Eh` (12 frames of `400h` or more) | bytes, whole-code scan for `55 8B EC 81 EC` | PROVEN |
| Chain at the low entry: `077D:045D` `CALLF 2033:000C` (function 0, media check) -> `2033:0028` `CALLF 2AB2:0767` -> `2AB2:076E` `PUSH CS / CALL 04F7`. Stack at entry: `[07D2]=0772 [07D4]=2AB2 [07D6]=002D [07D8]=2033 [07DA]=3E38 (BP) [07DC]=0462 [07DE]=077D`; Disk 7's frame base is `BP=3E38`, 0x48 bytes below the stack top. The UI stack is 13,998 bytes deep at entry, 13,906 of them Disk 7's frame; the reader then needs 109Ah more | MAME, `default` and `v308`, stock and PMONEY, one execution each (boot with the SCSI disk, Disk, 7) | PROVEN (this path) |
| Other entries: `2AB2:047F` (in the scan `2AB2:03A5`, near) and `2AB2:076F`; `2AB2:0767` from image `0x11069` and `0x20358`; `2033:000C` from 51 call sites. Boot scan enters with `SP = 3E5A`, `3E1E`; Erase all on SCSI (Disk 7, Soft Key 2, 2, 1) with `0776` and `07D2` | static call search; MAME | callers PROVEN; depth at the other 50 `2033:000C` sites UNDETERMINED |
| Wrapped writes: the stock reads (one block, 512 or 2048 bytes at `[bp-100Eh]`) stay in `F7C2..FFC1`; the callee frames and one IRQ entry reach `F6FA`. The SCSI data arrive by DMA (the write taps see them while other tasks run, e.g. `422F:0162`). PMONEY's `mnt_hybrid` reads LBA 63 into `[bp-100Eh+800h]` = `FFC2..01C1`, crossing into UI `SS:0000..01C1` (image `0x73E10..0x73FD1`): the UI stack's own free space below `SP`, plus task 6's initial-SP word at `0x73E10` (reader of that word UNDETERMINED) | arithmetic from the bytes, MAME | PROVEN (addresses) |

**Fix (`mods/scsistack316.inc`, hook `--patch=2b017:558bec81ec0e10:ea{scsi_stack}9090`).**
The reader runs on a private stack of `SCSI_STK_PARAS` = `120h` paragraphs
(4,608 bytes) between 3.16's sequence pool and its image: `entry316` now sets
the pool-end immediate (image `0x48535`) to `L-1 - 120h` = `67DF` (runtime
`L = 6900` on every set since the universal layout; before it `6EDF` with
`L = 7000`), so the stack is logical `0x67E00..0x68FFF`. The wrapper takes it only when the
live immediate leaves that room, and only for one user at a time (an `XCHG`
flag; a second entry runs the stock prologue). It then runs the replaced
prologue and the body (`T_D470_05BD` = `2AB2:04FE`) with `SS` = that segment,
switches back, and returns with the body's `AX`; an `ES` equal to the private
segment is set to the caller's `SS`, which is what the stock body leaves.

| Claim | Evidence | Tag |
|-------|----------|-----|
| The pool never reaches the stack: every reader of the pool variables `[8B13]..[8B19]` uses the variables set from the immediate (pool fix above), and the pool's last word is `imm:000E` | code (pool-fix review) | PROVEN |
| A task switch or interrupt during the reader keeps the private stack: AMX's ISR entry and exit (`47BF:0151..01C8`) and dispatcher (`01C9..0225`) save and reload `SS:SP` verbatim | code | PROVEN |
| Nothing unwinds past the wrapper: the only `SS`/`SP` loads in 3.16 code are start-up (`0x0005`), the AMX kernel (`0x47C3E..0x47E39`) and the OS reload (`0x485AB`) | linear scan of image `0..0x485EA` (data in `0x23xxx..0x29xxx` decodes as noise) | HYPOTHESIS (no `setjmp`/`longjmp` found) |
| The reader body `2AB2:04FE` and its whole call tree (857 instructions, static walk above) load neither `SS` nor `SP` (no `MOV SS`, `MOV SP`): nothing inside the reader can unwind past the wrapper, so `scsi_stk_busy` is always released | static, `tools/scsi_reader_reach.py` | PROVEN (code) |
| Size: deepest use 109Ah (frame 1010h, `SI`/`DI`, READ `2AB2:0202` -> `00FF` -> `2B36` -> `2A66`, and one AMX IRQ entry of 1Ah); 120h paragraphs leave 166h | MAME write taps on the stack, boot scan + Disk 7 + Erase all, `default` and `v308` | PROVEN (these paths); other IRQ nesting UNDETERMINED |
| After the fix no write lands in `[cave end, image 0x84000)` during Disk 7 or Erase all on SCSI; the reader's entries on the UI stack still come with `SP = 07D2`; Disk 7 lists the files and Erase all erases them | MAME, `default` and `v308`; `emu.test_scsi316` `test_disk7_reader_runs_on_its_own_stack` | PROVEN (these paths) |

**Who enters the reader (2026-10-17).** The private stack is held only while
the reader runs; the fallback (stock frame on the caller's stack) ran when it
was held or missing. Evidence that it is never held at an entry:

| Claim | Evidence | Tag |
|-------|----------|-----|
| Tasks: the static AMX create table (image `0x4834C`, 18-byte records, `FFFFh` end at `0x483DC`) has 8 tasks: 0 `47BF:05AC` (kernel), 1 `04CD:000A`, 2 `422F:000F`, 3 `40FF:0005`, 4 `3416:000A`, 5 `03C1:000C`, 6 `2FE8:0007`, 7 `0281:0034` (UI, `SS:SP 73E1:3E80`); stacks of tasks 0-6 are `320h`..`708h` bytes, so any of them entering the 100Eh-byte frame would have wrapped in stock 3.16 too | table bytes | PROVEN |
| The AMX kernel `47BF:0000..075B` has no far call, far jump, indirect call or jump, or `INT`: it leaves only by `RETF`/`IRET` to saved contexts (no timer procedures or callbacks into OS code) | linear decode, `tools/scsi_reader_reach.py` `kernel_transfers` | PROVEN (code) |
| Interrupt handlers: AMX installs (`MOV AX,seg / MOV ES,AX / MOV BX,off / MOV DL,vec / CALLF 47BF:0341`) 08 `2B50:000C`, 09 `2C45:000C`, 0C `2C08:000E`, 0D `2B6D:006B`, 0E `2C1F:0000` (plus the dead OS-reload one); direct IVT stores 40 `2A53:0024` (image `0x2A645`), 09 `2CCC:0000` (`0x2CE57`), 0B `3E16:0309` (`0x3E48C`); 3.16's BIOS segment `0009` vectors 08, 0F, 41, 42, 43, 45, 46. The cave installs none | image scan (`vector_installs`), cave source | PROVEN (these patterns; another install form would be missed: HYPOTHESIS that there is none) |
| Static reachability (`tools/scsi_reader_reach.py`, `tests/test_scsi_reader_reach.py`): recursive descent over the PMONEY image with the cave at its home (hooks followed), near/far calls, 15 hand-bounded dispatch tables, `INT n` through the vector map. From tasks 0-6, every handler above and the pre-kernel initialisers `0009:0006`, `0009:1AD0`, none of `2033:000C` (INT 41 service, 51 call sites), `2AB2:0767`, `2AB2:03A5`, `2AB2:04F7`/`04FE` is reachable; the only unresolved transfer there is `CALL FAR [79A0]` in INT 40 (`2A53:003C`), the EPROM's own INT 40 (ROM code with no 3.16 address). The UI task reaches the chain (45 `2033:000C` sites, the scan twice, `0767` once) | static analysis | PROVEN (static, the decoder is the project's 8086 length decoder; 3.16 holds no `0F E0`/`0F F0`) |
| No re-entry on the UI task: the reader body `2AB2:04FE` and everything it calls (857 instructions, the cave's `mnt_hybrid` included) reach none of the chain entries and contain no unresolved transfer or `INT`; no interrupt handler reaches it (above); a task switch cannot resume the UI task inside itself | static analysis | PROVEN |
| Every entry seen finds the stack free and comes from the UI stack: the wrapper's `XCHG` read of `scsi_stk_busy` (its only reader) logged in all seven `emu.test_scsi316` cases (boot scans, Disk 7, saves, rescans, Make active) on all four sets: old value 0, `SS` = `L+73E1` | MAME, `test_only_the_ui_task_enters_the_reader_and_never_while_held` | PROVEN (these runs) |

So the busy branch is unreachable, and "missing" cannot happen (entry316
lowers the pool on every set). The fallback is kept as a backstop that cannot
wrap: it runs the stock frame on the caller's stack only when `SP >=
SCSI_STK_BYTES` (1200h, the private stack's own size, above the measured
depth 109Ah), and otherwise returns the reader's read-error result `AX = 4`
with `[79A4] = 0` without reading (`tests/test_build_wave316.py`
`test_scsi_wrapper_fallback_cannot_wrap`, x86sub: `SP = 07D2` returns 4 and
writes only the flag and `[79A4]`; `SP = 1200h` runs the stock frame below
`SP`). The old image `0x83300` backstop on the cave home is gone.

Cost: the sequence pool is 4,608 bytes smaller on every EPROM (Seq memory free
407K, was 411K; 3.08/3.11 showed 435K / 439K before the universal layout); the
cave home grows by 154 bytes (wrapper, its variables and the refusal path).

FDC status byte: at boot `0281:0094` calls the FDC check `3E16:043C`, whose
result reader `3E16:01F6` stores the status byte with `STOSB` at `ES:7319`
(`3E16:021C`) and reads `DS:[7319]` back (`3E16:0224`). Before `0ae678e` the
cave's boot pages left `ES` = the cave segment (image `0x85319`, or NVRAM on
3.08/3.11). `sysinfo316` now leaves `ES = DS`; re-traced under the universal
layout: the write is `off=3D0CD8 mask=FF00 pc=A716:021C ES:DI=C99C:7319
DS=C99C` on `default` and `v308` (DGROUP `609C:7319`, image `0x67CD9`, its own
variable), and no write reaches the cave segment's `7319`. PROVEN (MAME, one
boot each). The cave-offset `0x7319` limit no longer applies.

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

## Cave space (universal build, 2026-10-17)

**Rule.** PMONEY is one STARTUP.SYS that must boot and offer every feature on
any MPC3000, whatever stock EPROM set is fitted. Features are budgeted
against the worst case over all four sets; nothing is gated on EPROM version.

**Same RAM on every machine. PROVEN (bytes).** The third PGR page tables
(`analysis/floppy_loader.json`, `third_pgr_file`) are word-identical in
3.08, 3.11, 3.12 and 3.50: pages 0-60 RAM (`0xC0+n`, `0xEC+`), 61 NVRAM
(`0x140`), 62-63 BIOS ROM. `INT 45` is byte-identical; every set is the same
2 x 256 KB chip pair. The only difference is the hand-off's load segment:
`L = 7000` (3.08, 3.11) or `6900` (3.12, 3.50). Physical equality of every
board revision is not provable from software (hardware RAM test deferred:
UNDETERMINED).

**Universal layout (built 2026-10-17).** `mods/entry316.inc` runs 3.16 at
`L = 6900` on every set. With `L = 7000` its `.move` path (entered after the
`MOV DX,L-1` check, at the stage `CS = L + 6834`) does, with `D = L − 6900 = 700h`:

1. **Re-relocate.** The builder (`mods/route_c.py` `build`) appends the image's
   own copy of the MZ relocation list right after the cave (`reloc_table`,
   image `0x6D70C`, 7,634 bytes: header N/R/Dmin, then 7,312 delta records
   for 7,311 relocated words (one skip record); `01..FF` = advance that many bytes, `00 w` =
   advance `w`, `00 0000` = advance `FFF0h` with no word). Every listed word
   gets `−D`, so the image holds exactly what the loader writes with
   `L = 6900`. The table is never copied home and is read only before
   3.16's start-up zeroes BSS (`DGROUP:7980..FC9E` = image
   `0x68340..0x7065E`, which holds it).
2. **Copy down.** All `N = 6F4E` paragraphs (image, cave, table) go from `L:0`
   to `6900:0` low to high in 800h-paragraph chunks (destination below
   source: forward copy is safe). The copy ends at `6900 + N`, at or below the
   paragraph of `entry316` in the old copy (builder: `D ≥ Dmin = 1F1h`; a
   smaller `D` halts), so the running code and its pointer are never
   overwritten.
3. **Rebase the loader's records of `L`.** BIOS data `0040:640A` (INT 45's
   load segment, `F800:0157`) and `0040:68C2` (the hand-off's
   `JMP FAR [68C0]` segment, floppy_loader.md §5) get `−D` when they hold
   `L` / `CS`; `SS` gets `−D` (`SP` kept), giving `D966:0100` as the loader
   leaves it with `L = 6900`.
4. **Continue in the moved copy.** `JMP FAR [CS:.moved_ptr]` (the one
   indirect far transfer the builder allows, modelled in `ENTRY316`) goes to
   `.moved` at `6900+6834`, which zeroes the `D` paragraphs the image left
   (`6900+N .. 7000+N`, logical `0xD84E0..0xDF4E0`, the old `.move` code
   among them) and jumps to `entry316` again: it now reads `L−1 = 68FF` and
   copies the cave home, sets the pool end and enters `6900:0000` exactly as
   on 3.12/3.50. No stack is used by the move; `BP` and `IF = 0` are kept.

With `L = 6900` the move is skipped (one compare). With any `L < 6900` the
routine runs in place as before.

| Claim | Evidence | Tag |
|---|---|---|
| Final memory (1 MB logical, BIOS data included) and registers at 3.16's entry are identical for `L = 6900` and `L = 7000` | builder model `run_entry` (`verify`, every build); the assembled bytes run by `tests/x86sub.py` from the hand-off state at both `L` (`tests/test_build_wave316.py` `test_entry316_bytes_run_in_x86sub`): identical memory, registers and flags; the model agrees byte for byte except the `PUSH CS` slot under `SP` | PROVEN (simulation of the loader as documented in floppy_loader.md §5, §7) |
| The image's table is the MZ relocation list | builder decodes it and compares with the header list | PROVEN |
| No 3.16 relocated word has meaning outside "L + stored": stored values are `0x0009..0x7DFA`; the one non-image value (`59FA` = `0040` under the original link base, image `0x485AC`) is in the OS-reload routine image `0x48580`, which returns at once: `MOV AX,7DFA / SUB AX,7DF9 / CMP AX,1 / JZ` with both words relocated | bytes, relocation list | PROVEN |
| Nothing else outside the image records `L`: the hand-off writes IVT[8] (`FB93:0059`, L-independent), `0040:68C0/68C2`; INT 45 writes `0040:6408..6410` (`640A` = `L`), the header copy `63EC..` and the relocation buffer `642B..` (file data); 3.16's start-up installs its own `INT 41/42/43/45/46` (segment `0009`) | INT 45 and hand-off bytes (3.08 dump, byte-identical INT 45 in all four), 3.16 image `0x96..0x17C` | PROVEN (code); stale stack bytes below `0040:69C4` (INT 45's pushes, may include `L`) are not rebased: below `SP`, not read (HYPOTHESIS: no reader of dead stack) |
| Boots on all four sets with cave home physical `0x3E7000`, pool end `67DF`, `Seq memory free 407K` on each | MAME, `emu.test_port316_boot`, `emu.test_sysinfo`, release gate (below) | PROVEN (one execution per set) |
| Real hardware | not run | UNDETERMINED (deferred physical test: boot on a 3.08 or 3.11 EPROM machine, read System Information = 407K) |

**Cost.** STARTUP.SYS 479,264 → 487,134 bytes (+7,870: table 7,634, entry316
+236). The home is unchanged (21,140 bytes copied). The later no-wrap SCSI
fallback adds 14 bytes (home 21,154, STARTUP.SYS 487,148). Boot time, MAME
(emulated seconds, read taps on the first fetch of `entry316` at the hand-off
`CS` and of 3.16's entry, one execution each; same disk layout, `STARTUP.SYS`
alone):

| Build, set | hand-off | 3.16 entry | hand-off → entry |
|---|---:|---:|---:|
| before (`0ae678e`), `default` | 25.073240 | 25.077779 | 4.5 ms |
| before, `v308` | 25.071059 | 25.075599 (`7000:0000`) | 4.5 ms |
| universal, `default` | 25.273240 | 25.277778 | 4.5 ms |
| universal, `v308` | 25.271060 | 25.388901 (`6900:0000`) | 117.8 ms |

The move costs 113 ms on 3.08/3.11 and nothing on 3.12/3.50; the larger file
adds 0.20 s of floppy load on every set. PROVEN (MAME timing); real drive
and CPU timing UNDETERMINED.

**Emulator results (2026-10-17, MAME, release mode, all four BIOS sets, one
execution each).** `emu.test_port316_boot` 7/7, `emu.test_sysinfo` 1/1,
`emu.test_scsi316` 5/5, `emu.test_diskutil316` 19/19 (its stock-3.16 control
now reads DGROUP at the loader's segment), `emu.test_wave_chop` 12/12,
`emu.test_harness_lifecycle` 9/9; `python3 -m emu.harness_release`: 242
tests, 2 failures, 0 skipped. The two failures are `emu.test_cycle_budget`
worst-case maxima on the Vailixi set (no move there): `isr09_own_max_play300`
3,154 cycles (budget 2,959.3, pinned PMONEY 2,935.0) and
`tick_done_max_ms_play300` 3.225 ms (budget 3.12). The `0ae678e` build
passes; the same `0ae678e` code with 7,870 zero bytes appended to the file
(so only the floppy load, and with it the phase of every later event, moves by
0.2 s) fails with 3,150 cycles and 3.225 ms. PROVEN (one execution each): the
change in these maxima comes from the boot-time shift, not from the
universal-layout code. Re-pinned in `emu/fixtures/cycle_budget_316.json`
(`isr09_own_max_play300` abs 3,186 = 3,154 + 1 %, PMONEY 3,150; `tick_done_max_ms_play300`
3.29 = PMONEY 3.226 + 2 %), each note citing this experiment.

**Current figures.** Cave home 21,154 bytes at image `0x7E000` on every set.

| Limit | Free |
|---|---:|
| Page 61, universal (`L = 6900` on every set, `0xD000` = 53,248 B home) | 32,094 B |

This is the only cave-room limit. The SCSI stack-wrap backstop (home end at
image `0x83300`, 108 B free before) is gone: only the UI task can enter the
reader, it cannot re-enter it, and the fallback can no longer run the frame
on a shallow stack ("SCSI reader stack" above). The FDC byte limit (cave
offset `0x7319`) is gone too (same section).
`tests/test_build_wave316.py` encodes these limits.
