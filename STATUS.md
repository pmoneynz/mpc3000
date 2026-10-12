# Audited project status

**2026-10-13 PMONEY note-on fixes (not built as a release):** S1a ported to OS 3.16
(17 divide calls to the cave, fallback to 3.16's runtime copy, byte-identical to the BIOS
one), an inline pad lookup in the mute note-on wrapper, and the allocation lock re-taken
only after a choke stop. PROVEN in MAME: the cave's pad lookup equals stock's on 128
note-ons in both table modes; a PMONEY note-on costs 9,412 cycles with mute groups off
(was 20,818; stock 3.16 14,656) and 12,763 with them on (was 23,840). Lookup and lock
changes also apply to the WAVE/WAVEHW builds; release gate 166 tests, no failures or
skips. notes/performance.md section 12.

**2026-10-13 S1a implemented (not deployed):** `mods/S1A.args` + `mods/s1a.asm` redirect
the 17 divide calls of the note-on layer `CFC6:039E` to a 116-byte cave doing two DIV
steps (fallback to the BIOS runtime). PROVEN: the cave and the runtime execute
identically on 6,800 edge and random operand pairs (tests/test_s1a_divide.py);
PROVEN (trace, MAME 16 MHz): over 640 input tuples in stock and S1a runs, no call
result, voice-start parameter or own-stack DSP access differs; the layer costs
7,530 instead of 13,633 cycles (-45 %), 9,725 instead of 18,370 on the varied
program (MAME pin b4ab57e6). Physical behaviour UNDETERMINED (H4/H7). notes/performance.md section 9.6.

**2026-10-13 S1 characterization:** fork trace points traced 960 note-ons of
`CFC6:039E` (all 64 pads x 5 velocities, three runs). PROVEN (trace): every runtime
call result and every DSP write sequence is a function of the traced inputs only;
tempo is not an input (PROVEN, code). Divides are 56 % of a default layer (about
1,446 cycles per long-path call); a two-step DIVU model is exact on all 9,978 traced
divides. The per-pad precompute is demoted: velocity reaches every block once any
velocity sensitivity is non-zero. Next: S1a, a fast exact divide at 14 call sites
(Route A), about -46 % per layer. notes/performance.md section 9.

**2026-10-13 performance map:** a cycle profiler (`nec_prof`) is in the MAME fork's
NEC core (working tree, uncommitted) and `emu/profile.py` drives nine stock-3.50
workloads; `tools/prof_report.py` writes the map. PROVEN (data book + code):
the pinned fork runs the V53 core at 32 M cycles/s, twice the physical 16 MHz;
`NEC_CPU_DIV=2` corrects it (default unchanged). PROVEN (trace, 16 MHz): the OS
is 8 % busy idle and at most 24 % in the heaviest workload (66 pad hits/s with
sounds); the "idle" is task 7 polling the key queue; the sequencer tick ISR
costs 2,121 cycles even when stopped, a note-on 23 k cycles (1.46 ms, 45 % in
32-bit runtime arithmetic), a received serial byte 1,053 cycles. Pad/MIDI
events are drained only on the tick (latency 0-1 tick + 1.5 ms). Backlog,
hardware tests and the first experiment (note-on precompute): notes/performance.md.

**2026-10-03 WAVE BENCH 07 built (not deployed):** BENCH 06 plus the review
fixes. Payload `2cea7a48...79fb`, image `dc953ab5...a057`. PROVEN in MAME:
135 emulator tests (22 suites, no skips), 67 builder tests, 171 boot checks,
release-image boot, near-full APS refusal. Physical behaviour is
UNDETERMINED; the bench procedure is notes/bench07_checklist.md.

**2026-10-02 review fixes merged (not yet built as a release):** an
adversarial review of BENCH 06 and its fixes are in the sources. CHOP ZONE now
honours the stock Edit Sound safe lock and mute-audio settings and keeps the
saved list selection; numeric entry no longer reorders fast-typed digits; the
mute trigger context lives on the note-on wrapper's stack instead of in
globals; mute storage range-checks program indices; Apply All asks and only
soft key 3 applies; the APS save budget is 49 KB (three stock patches) so a
near-full disk refuses instead of losing the file; the wave view keeps a
separate full-view cache and inverts by column. Builders share
`mods/buildkit.py`, derive the capture patch list from `WAVE.args`, and check
every cave far target against the captured ROM. PROVEN in MAME: 135 emulator
tests in 22 suites with skips forbidden, 67 builder tests, 171 boot checks;
payloads are built from current sources per run (`emu/harness.py`). Cave
12,804 of 14,384 bytes. The `build/mods` BENCH 06 artifacts predate these
changes and were deliberately not rebuilt. Physical behaviour is
UNDETERMINED. Cross-task mute interleaving, CHOP rollback after a late
allocator failure, and wheel bursts beyond the 8-key stock queue remain
without a hardware observation.

**2026-10-01 WAVE BENCH 06 ready:** four program-level mute groups, per-pad
Off/1-4, enable, Apply All, and PGM/APS persistence are implemented. End Up
selects Zone; Down returns to End, including typed End acceptance. PROVEN:
95 final emulator tests, 171 boot checks, exact disk/FAT/ROM/relocation checks,
and DRUMS preview. BENCH 05 remains on USB; BENCH 06 is prepared, not deployed.
Physical BENCH 06 behavior is UNDETERMINED. See notes/mute_groups.md,
notes/waveform_bench.md and build/mods/WAVEHW-validation.json.

**2026-10-01 WAVE BENCH 05 ready:** shared 1â€“16 zone editing and
Do:CHOP ZONE are implemented. Current/total fields use cursor and wheel/+âˆ’;
created sounds preserve exact PCM, stereo and volume/tune. PROVEN: 65 final
emulator tests, including stock stereo save/cold reload, plus 171 boot checks
and full four-file disk/relocation validation. The DRUMS preview uses the
exact final image. Chopping requires >=441 frames (10 ms) per zone. Maps last
for the current Edit Sound session; resulting sounds save normally. BENCH 05 is
installed in USB slot 1, readback verified and safely ejected. Physical
behavior is UNDETERMINED. See
notes/waveform_bench.md and build/mods/WAVEHW-validation.json.

**2026-10-01 WAVE BENCH 04 prepared:** waveform keys now read 1 Ply/Stp,
2 Trim/Zone, 3 Fine/Full, 4 Exit. Playback/numeric behavior is unchanged.
PROVEN: 13 emulator regressions, 171 boot checks and full disk/relocation
validation pass. The image is prepared for emulator display review;
USB remains on BENCH 03. Physical BENCH 04 behavior is UNDETERMINED.
See notes/waveform_bench.md for hashes and evidence.

**2026-10-01 WAVE BENCH 03:** stock numeric entry and visible-selection
Play X are implemented and deployed to FlashFloppy slot 1, retaining DRUMS,
SINE441 and STEREO1. 43 emulator regressions and 171 boot-slice checks pass;
image/FAT/relocation and USB readback are verified. WAVE-only call-chain
hooks remove stock's 30 ms early cutoff; playback still uses the 10 ms
timer and rejects intervals below two ticks as Too short. Earlier BENCH 02
full/Fine editing is physically observed; BENCH 03 numeric/audio behavior
awaits the next machine test. See notes/waveform_bench.md, wave_numeric.md
and wave_playback.md. The prior working image is preserved for rollback.

**2026-10-01 physical editing/exit:** IMG_4806/4807 show the 16-frame
Start edit in the custom view and the same Soft st after returning to
stock Edit Sound. User reports editing works. RAM edit persistence across
this exit is PROVEN; disk save/reload and broader cases remain open.

**2026-10-01 physical fine view:** IMG_4805.JPG shows SINE441 at Zoom16,
Start selected at zero, expected left out-of-range zero line and right
sine cycles. Full/fine rendering and Start selection are now observed.
Wheel edits, exit/reopen, zoom changes, audition and stereo remain open.
Evidence: notes/evidence/2026-10-01-wavehw-fine-result.json.

**2026-10-01 first physical waveform display:** IMG_4803.JPG shows the
custom SINE441 full view with correct 1.250-second duration and expected
sine/silence/ramp sections. First feature execution/display is PROVEN
for this run; fine zoom, edits, exits, audition and stereo remain pending.
Evidence: notes/evidence/2026-10-01-wavehw-sine441-result.json.

**2026-10-01 WAVE BENCH 02 ready:** ROMAPP completed physically; its
336 KiB capture is verified (sum 7DBA). WAVEHW uses that exact captured
OS/DGROUP and an exact 32 KiB BIOS guard, with six verified RAM-offset
changes. Five focused emulator tests, independent FAT/relocation review,
19 probe regressions and 171 boot checks pass. USB slot 1 is installed,
read back and safely ejected. Next: boot to WAVE BENCH 02 / Play-Record,
load SINE441, then Program/Sounds -> 6 -> Help. Physical waveform
qualification remains pending. See notes/wave_physical_profile.md.

**2026-10-01 ROMAPP ready:** captured BIOS confirms the generic WAVE
ABI is incompatible. A guarded 336 KiB application/data capture is
validated in MAME, installed in USB slot 1, and safely ejected. It
excludes the NVRAM page. The next physical run should reach ROMAPP
DONE; then return the USB for extraction. Reference MSO restoration
is verified and all 171 boot-slice checks pass.

**2026-10-01 captured physical BIOS:** ROMDUMP returned 32 KiB,
SHA-256 2c654334e011af2943d1d08f05e3ce48ebccdf49600aab7a2f040ba016c21168.
All prior measurements match. 2,494 bytes differ; AMX public entries
shift by -0xA, DGROUP length is 7C90, and init table is F076. The
generic WAVE ABI is incompatible; guard remains intact. Details in
notes/rom_compatibility.md.

**2026-10-01 focused physical result:** ROMWORD5 completed: 0x0507
(1,287) differing words, first 7A25C / last 7BA00. The first change
is a DGROUP classification-table displacement, 7B91 -> 7B8F. Keep
the WAVE guard; physical ROM bytes are needed before compatibility
work. ROMDUMP is validated and installed on USB slot 1, safely
ejected; next run saves high-ROM BIOS.BIN for analysis. Evidence:
notes/rom_compatibility.md.

**2026-10-01 comparison checkpoint:** ROMCHECK4 shows CS=6900, SUM
DONE, and NEXT OFFSET 2400. The user confirms successful M3K316.SYS
loading on this same machine/FlashFloppy. ROMWORD5 now compares the
two changed blocks with aligned word reads; verified on USB slot 1
and safely ejected. Exact ROM differences remain pending.

**2026-10-01 comparator follow-up:** ROMCHECK3 stayed at ENTER for
over 30 seconds. Cause unresolved; ROMCHECK4 now adds stage and scan
progress markers. It is verified on USB slot 1 and safely ejected.

**2026-10-01 ROMSUM2 result:** physical diagnostic completed with sum
81A0 (reference 8634). Blocks corresponding to file 7A000 and 7B000
have different sums. ROMCHECK3 is on USB slot 1 for byte comparison,
verified and safely ejected. Compatibility remains unresolved.

**2026-10-01 diagnostic follow-up:** the first ROMCHECK stayed on
Loading files. Its forbidden PGR reads and directory metadata were
corrected; the exact hardware stopping point is still undetermined.
A 353-byte ROMSUM2 probe is verified on USB slot 1 and safely ejected,
awaiting the next LCD photograph.

**2026-10-01 bench follow-up:** physical WAVE startup halted at the BIOS
checksum guard on the personalized Vailixi 3.50 machine. The waveform
feature did not run. Compatibility diagnosis is in
[`notes/rom_compatibility.md`](notes/rom_compatibility.md).

**2026-10-01 hardware/mod update:** the Route B canary marker was observed
on Peter's physical MPC3000, loaded through FlashFloppy (**PROVEN**, user
report and photo). WAVE bench preparation corrects signed wheel movement
on long sounds and adds a marked image with disposable mono/stereo sounds.
Route A/WAVE hardware behavior remains **UNDETERMINED**. See
[`notes/waveform_bench.md`](notes/waveform_bench.md) for the evidence,
validation, USB manifest, and bench procedure. The baseline below describes
reverse-engineering coverage; it is not a summary of the latest mods.

**2026-09-21.** Target: Vailixi OS 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.

This tree was a document-and-dump pack. It now has a project goal, an
address model, a static reset-to-AMX-start slice, a seeded owner
ledger (986 ranges, 379868 bytes), a consumer-established string
inventory, an entry inventory (143 unique `CS:IP`), and a
local-exit inventory (128 bounded / 14 indirect / 1 idle loop).
It does not have whole-image coverage or Ghidra exports.
R3 is closed: `0x7AC1C` is pinned `BRKXA 0x11` and checked by the verifier and unit tests.
U-AMX-WAIT is closed by IVT[8] `D52A:0008`
([`notes/amx_wait.md`](notes/amx_wait.md)).

## What is established

- Chip-pair identity matches MAME `vailixi` SHA-1/CRC32. Linear SHA-256 is
  pinned and regenerated by `tools/linear_rom.py`.
- The image is interleaved LS/MS EPROM, not a floppy container.
- Reset is `EA FFF0:0000` at file `0x7FFF0`. The wait-state stub at
  `0x7FF00` far-jumps to `FAC0:0000`.
- First PGR maps 20-bit page 0 to work RAM `0x300000`. `BRKXA 0x11`
  continues in place from ROM IVT[0x11].
- `FAC0:0134` walks three `F07A` records. BIOS `F800:000A` and
  `F800:1AD4` both `RETF`. The third record is AMX start `FB00:000C`.
- BIOS issues `INT 43` AX=0, which programs LC7981 ports `0xE2`/`0xE0`
  through the put at `0x7985A`.
- The `0x7C92`-byte `DS=A000` to `ES=8010` copy is a relocated DGROUP:
  directory `[+4, +0x5C8)`, string pool, writable globals. 21
  `MOV AX,8010`. Dest 24-bit `0x380100` under first and second PGR.
- AMX `0537` maps `DL` to a 0x40-byte TCB. `01EA` resumes or creates a
  ready TCB, else `STI`+NOP at `FB00:023A`. Create record 7 is
  `B000:00DF`. Second PGR is live through that first select.
- First `01EA` does not idle. `B03B:000A` readies TCB 6 and 7 via
  `0396`; scan from index 0 creates task 6 at `D9BD:0009`.
- Reset-path IVT: 219 default `F800:1952` `IRET`s; `IVT[10h]=FAC0:01A4`;
  AMX owns 0 and 4; `B03B` owns 8/`0Ch`/`0Dh`/`0Eh`. The old `IVT[2]`
  plant claim is retracted.
- Only three `MOV DX,0xFF00` sites exist; all are FAC0 `OUTSW`. Second
  PGR is live through task 6’s first wait (`01CF` AX=4) and task 7
  select (`B000:00DF`).
- AMX public far-call surface is 76 `CALL FAR FB00` sites, 19 IPs.
  TCB `[SI]` bits 0/1/2/3/14/15, stack at `+4/+6`, timed wait at
  `+0Ah`, stride `0x40`. Mailbox/pool objects at `ES:[BX]` stay D11.
- Create-table tasks 0–7: entries and exits pinned. Task 6 never
  `RETF`s. Reset readies only 6 and 7. `E937:0004` is `DS=ES=8010`.
- Dominant application convention is far cdecl: `[BP+6]`, caller
  `ADD SP`, `RETF`. The `F800:1875` walker is BIOS-only (3 sites).
  AMX public APIs take `DL` (or `CX` via `B060`). `INT 43` takes `AX`.
- `FAC0:01A4` switches XA and reloads the third PGR; `IRET` at
  `024F` keeps the interrupted IP. AMX `02F8`/`02EF` rewrite the
  `IRET` frame to `TCB+18h+AX` when nest is 1..127 and the hook is
  non-null. `0157` stack-switches to `901C:1130`.
- `U-COPY-7C92` closed: only bulk writer is `FAC0:0074`; BSS zero
  is `[7C92, FFB8)`; `065B` overlays `8010:125C`..; `A000` is ROM
  only under the first PGR. No second dest alias.
- BIOS banner characters take `INT 43` AX=4, then `17CC`, then `LCD_put`
  AH=`0x0C` / AL=char on ports `0xE2`/`0xE0`. Cursor and a 320-cell
  shadow live at `0040:68AB` / `0040:662B`.
- File `[0x00054, 0x20000)` is `0xFF` padding. Three IVT template slots
  sit in the 128 KiB prefix.
- Owner ledger: 986 ranges, 379868 bytes, 132 gaps. Owners are
  `code` or `data` only. Every `0xFF` run of 4+ bytes is classified.
- String scan (D14): 1096 C-string starts are text because a
  consumer points at them (directory 345 `8010` ptrs, 27 disk
  labels, 3 walker inlines, 886 `PUSH DS`/`PUSH off`/`CALL FAR`).
  Put-string `B1B1:005B` (file `0x31B6B`) does `LDS DI,[BP+6]` and
  `INT 43` AX=4. 355 DGROUP C-strings and app-ROM lookalikes stay
  candidates. KADAK is identity bytes, not text.
- Entry scan (D15): 143 unique `CS:IP` from reset, ROM IVT, `F07A`,
  create-table, AMX public/internals, reset-path IVT, INT 43, BIOS
  helpers, `E937`/`B060`/`D9B5:0045`, and 67 `PUSH DS`+far cdecl
  targets. 6154 `9A` and 825 `EA` encodings are suspects.
  `0x7FF01` and `0x797A7` are immediates, not far transfers.
- Transfer scan (D16): every local exit from the 143 entries is
  classified. 128 bounded, 14 indirect (`JMP`/`CALL [rm]` slot
  named, table UNDETERMINED), 1 idle loop at `FB00:023A`. All
  `JMPF` dests are already established. 74 CALLF + 42 CALLN dests
  are named candidates, not accepted as code.

Evidence: [`notes/boot_reset_to_bios_banner.md`](notes/boot_reset_to_bios_banner.md),
[`notes/copy_7c92.md`](notes/copy_7c92.md),
[`notes/owner_ledger.md`](notes/owner_ledger.md),
[`notes/string_scan.md`](notes/string_scan.md),
[`notes/entry_scan.md`](notes/entry_scan.md),
[`notes/transfer_scan.md`](notes/transfer_scan.md).
Validator: `python3 tools/verify_boot_slice.py`.

## What is not established

- Which pin raises IVT[8] (`U-V53A`). U-AMX-WAIT is closed by IVT[8]
  `D52A:0008` ([`notes/amx_wait.md`](notes/amx_wait.md)). First select
  is closed; see [`notes/amx_first_dispatch.md`](notes/amx_first_dispatch.md).
- LC7981 glass pixels (`D3-glass`). Software banner path is closed.
- PGR after task 7 runs (`U-XA-LIVE`). Second table is live through
  task 6’s first wait, task 7 select, `D9DD:005D`, and `DDC0:0031`
  (`RETF` files `0x5DCEE` / `0x5DD11`; no `MOV DX`/`OUT` into
  `0xFF00-0xFF7E`). Next unwalked third-level is `DDC0:000F`.
  Only three full-table `OUTSW` sites exist, all FAC0.
- First ready of create-table slot 2. Slot 0 is the IVT[8] tick
  ([`notes/amx_wait.md`](notes/amx_wait.md)).
- Word `+2` = `0x0100` and the `+0238` numeric-island *meaning*
  (`copy_7c92.md`). Per-screen string meaning stays D25.
- Panel ROM, PAL fusemaps, full schematics. D19 is PARTIAL
  ([`notes/front_panel.md`](notes/front_panel.md)): `0xC0-0xDF`
  encodings exist; navigation meaning does not.
- DGROUP `+0054`..`+01E4` is 101 pan names (`50L`..` C `..`50R`),
  not drum-pad labels. Owned printer `B354:01C6` is called with
  title `Pan:` ([`notes/pan_table.md`](notes/pan_table.md)).
- D20 is closed: reachable `[D6AC]` writers are clamps and note-to-slot
  remaps. `D52A:0328` has no static or computed near entry. A pad hit on
  the wire stays D19.
- PGR page 61 word `0x0140` maps to 24-bit `0x500000`
  (full-word `v33_translate`). Consumer is `D9B5`
  `ES=0xF400`; `ES:[03FE]` is `0x5003FE` inside the
  MAME NVRAM window. Chip LC3517 is HYPOTHESIS
  ([`notes/pgr61.md`](notes/pgr61.md)). Low-byte-only
  `0x100000` is retracted.
- Instruction bounds for CALL dests that are still indirect or
  have no named consumer. Jump-table *selection* (`BX` domain)
  at the six `CS:[BX+disp]` sites.
- Whole-image ledger coverage (D17). Reached `D52A:0312` stores `[7626]=0x0492`; `D52A:0492` through `JMP 06A0` is owned. 132 gaps remain (379868 owned). Later
  `IVT[8]` is `FB93:0059` (file `0x7B989`). `F800:1906` is
  a 16×4-byte OUTSW table.   `D547:0561` is a 16-IP `DI` switch. `D547:053A` is 8 IPs
  (`AND BX,0x0E`); slot 7 is `054A`.
  `B2DA:000F`, `DB28:0A2D`, `F800:20F7`, `B1BC:0040`,
  `DCA2:0154`, `C425:0269`, `F800:242D`, `C2D0:000C`,
  `B3ED:000F`, `C44E:0005`/`00B8`, `C2E6:0007`,
  `CEBF:0008`/`026A`, `BE1A:0002`/`01FB`, `BE1A:0203`/
  `022B`, `BE1A:026C` (three packed tables), `C303:0004`
  (`0BCC`/`0BE8`), `B3FD:0006` (`0871`/`088D`/`08A7`), and
  `B3FD:08C3`/`0953`/`097B`/`09AC`/`09E2`/`0A2F`,
  `C303:0C0E`/`0C64`, `B060:0715`/`086E`/`0982`..
  `0A4A`/`0C6C`/`0CBF`, and hole-start `CALLF` dests
  `B292:0008`/`B2F1:0002`/`B354:05F8`/`E4FA:000C`/
  `E582:0000`/`E676:000D`/`E7E0:000A`/`EB1A:0002`/
  `EBC8:0003`/`B2A0:0007`/`B31B:0007`/`E4FA:0170`/
  `B060:0A7B`/`B060:0D04`/`B20A:0004`/`D6E0:008B`/
  `E398:0009`/`0119`/`01F0`/`0366`/`0386`/`03BD`/
  `045A`/`E3E7:0008`/`DCA2:0166`/`0371`/`03C9`
  are seed-only. Those switch tables are
  not BFS seeds.
  Indirect *targets* and unentered app ROM stay
  debt. The 1-byte `CF` at `0x7ADA3` has no entry.
  2026-09-21 09:00 UTC CALL-set hunt was empty.
  A later real-modrm CS-relative pass owned
  `D5DD:0124` / `DC5B:0002` / `DC6E:0002` /
  `EB0B:0002` data tables (plus two auto 1-byte
  `0xFF` aligns). `EB0D` / `EB5B` stay unowned
  (RAM `BX`/`DI`). Unentered app ROM stays debt.
  2026-09-21 09:20 UTC: far ptrs in owned data to
  hole starts = 0. F800 alternate `590e51` entries
  and `D6D4:003F` still have no owned caller.
  INT 43 AX=1..7 dests were already owned extras;
  they are now seeded. D18 software contract is
  closed. `FB81:0008` (`CS:[003A]` slot 0, file
  `0x7B818`) is seed-only: list header, jump-over
  sled, `CS:[0032]`/`[0036]`, `003A`/`0061`.
  `0061` `CALLF FB00:065B` with `ES=A850`, `AL=2`
  is a named `065B` consumer; D11 stays gated.
  `B261:000A` (file `0x3261A`, `CALLF` from
  owned `B060` prefix at `0x30A85`/`0x30C4D`)
  and leftover `0273` are seed-only. Prefix
  cdecls at `[0x32600, 0x3261A)` stay unowned.
  `E59E:0006`/`0035` and `E5A8:0003`/`0030`
  (`CALLF` from owned `E398`) and leftover
  `C303:0D47` (`B3FD:02A4` / `C2D0:000C`) are
  seed-only. `E582:013A` / `E59E:0099` /
  Mid-hole `C4C8`
  / `B77C` stay unowned. `E12D:0009`,
  `E07A:0004`, `E6D1:0001`, `E739:030C`, and
  `E661:0006`/`0095` are seed-only. Packed
  `CALLN` leftovers `C303:0CEE`/`0D76`..`11C4`,
  `B060:0044`..`02D6`, and `B3FD:0A96` are
  seed-only. Named `C44E` `CALLN` dests
  `00C2`/`0119`/`0485`/`06B6`/`070F` and
  leftover `D9F2:0072` are seed-only.
  Leftover `B060:0030` closes the 20-byte
  prefix. `C44E:02BF` and `C887:09AC` stay
  unowned. 2026-09-21 10:40: `LES`/`LDS`
  static dests into gaps = 0; `INT` dests
  already owned; CS-relative far `[rm]`
  into gaps = 0. Further D17 growth needs
  another named consumer.
- RAM object lifetime past the `8010` DGROUP / BSS split and the
  `065B` overlays.

Physical hardware remains deferred.

## Progress measure

The useful increment is the removal of a named uncertainty. First `01EA`
creates task 6. U-AMX-WAIT is closed by IVT[8] `D52A:0008`
([`notes/amx_wait.md`](notes/amx_wait.md)).
