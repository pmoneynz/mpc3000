# Vailixi 3.50 licensing and the WAVEHW release question

**Date:** 2026-10-05. **Inputs:** reference linear image
`a52b7122…70c9` (`07-rom/Vailixi 3.50`, MAME `vailixi`); captured
`ROMAPP.BIN` (linear `0x20000–0x73FFF`) `bc1dd8cd…e1e2` and `BIOS.BIN`
(linear `0x78000–0x7FFFF`) `2c654334…1168` from Peter's machine.
Comparisons are linear-file offsets, both images interleaved LS/MS.

## Question

Can the deployed WAVEHW image (BENCH 07) run on another Vailixi 3.50 owner's
machine?

## What is certain

**PROVEN (code):** the image cannot start on any machine whose 32 KiB high
ROM (`F800:0000–7FFF`, linear `0x78000–0x7FFFF`) differs from Peter's in any
byte. `mods/mod_stub.asm` compares all 16,384 words against the embedded
capture before copying anything to RAM, and on a mismatch prints
`Mod ROM mismatch` through `INT 43` and halts. Nothing is written to RAM
beyond the stub's own load, and nothing to disk.
**PROVEN (hardware, 2026-10-01):** the same mechanism stopped the generic
image on Peter's machine (`evidence/2026-10-01-wave-guard-rejected.jpg`); the
machine then booted normally without the floppy.

## What is not known

Whether any other owner's high ROM is byte-identical to Peter's. There are
only two samples: Peter's machine and the reference dump.

## Evidence from the two samples

**1. The reference dump is a redacted licensed ROM.** At linear `0x210F5`,
`0x21110`, `0x2112B` (runtime `8010:10F5/1110/112B`) the reference holds
`Vailixi 3.50 (---/--/----)`, `-------- --: ------- -- -`, `------: -----------`.
Peter's holds a real date (`JUN/28/2008`), a `Licensed To:` name and a
`Serial:` number. The reference is therefore another licensed copy with its
personal fields overwritten, not an unlicensed build. **PROVEN (bytes).**

**2. The license text length moves DGROUP, and the BIOS encodes DGROUP's
size.** From the licensee field onward, DGROUP in Peter's image equals the
reference displaced by 2 bytes (`cap[i] == ref[i+2]` for 27,110 of 27,536
bytes from `0x21100`); the remaining bytes are DGROUP-offset operands.
DGROUP is `0x7C92` bytes in the reference and `0x7C90` in Peter's. The BIOS
hard-codes that size: `FAC0:0084` `MOV CX` (linear `0x7AC85`) and
`FAC0:013D` `MOV DI` (`0x7AD3E`) hold `7C92`/`7C90`, and BIOS operands that
address the end of BSS change `FFB0 → FFAE` (e.g. linear `0x7A436`,
`0x7A583`). So the high-ROM bytes depend on the length of the license
strings. **PROVEN (bytes and consumers).** Inference: an owner whose
licensee line has a different length has a different high ROM, and the
image refuses to start. **HYPOTHESIS until a third ROM is read.**

**3. The two images are also different compiles, not only different text.**
After byte alignment, the last application segments
(`0x6A1B1–0x707C7`) are 97.5% equal but contain real code edits, e.g. the
routine at linear `0x6B746` performs the same port `C011`/`50`/`F0`/`F6`
writes in both images but is compiled differently; Peter's application code
ends 64 bytes earlier (`0x70788` vs `0x707C8`). In the BIOS, the AMX kernel
block starts 10 bytes earlier in Peter's image (`0x7B004` vs `0x7B00E`) with
all its internal references adjusted by `-0xA`, which is why every AMX entry
moved by `-0xA`. **PROVEN (bytes).** Whether these follow the license length
or are a separate code revision is **UNDETERMINED**.

## Release consequences

- **Not portable as built.** Every cave constant (DGROUP addresses, AMX
  entries) is resolved for Peter's layout; the builder already maintains two
  profiles because one 2-byte text-length difference moved 48 operand bytes.
  An owner with another layout would need their own profile even without
  the guard. **PROVEN** for the two known layouts.
- **The image contains the owner's licensed firmware.** Route A copies the
  whole OS from the `.SYS` into RAM, so `WAVEHW.SYS` carries Peter's captured
  application ROM and DGROUP (including the licensee name and serial) and the
  full 32 KiB BIOS as its guard array. Handing it to another owner would
  redistribute that firmware, and their machine would show Peter's license
  fields. **PROVEN (builder and image layout).** This is a release blocker
  independent of compatibility.

## What would settle compatibility

A `ROMDUMP` run (32 KiB high ROM, already proven on hardware) from one or two
other owners, plus a photo of their boot screen. Comparing those dumps with
the two known layouts answers whether layouts cluster by license-text length
or vary by build.

## Release path implied

Change the loader so the `.SYS` carries only the stub, the cave and a patch
list, never Akai/Vailixi bytes: copy the owner's own EPROM application and
DGROUP to RAM, locate each hook by a byte pattern with wildcarded DGROUP/AMX
operands, verify it, derive that owner's DGROUP and AMX displacements from
anchors (for example the `MOV CX,<DGROUP size>` at `FAC0:0084` and the AMX
header at the KADAK copyright string), relocate the cave's constants, and
refuse to start unless every site matches. This removes the redistribution
problem and turns "one image per owner" into "one image, verified per
machine". The two known layouts are the first test cases.

## Universal target (requirement added 2026-10-05)

The build must run on any MPC3000, whichever EPROM OS it has (3.08, 3.11,
3.12, Vailixi 3.50) or whether it runs 3.16.

**OS 3.16 is the only common base.** It is a floppy-loaded OS
(`07-rom/v3.16 maintenance upgrade/M3K316.SYS`, community upgrade by Rohan
Mansell / ECSA, 2005) that runs from RAM. **PROVEN (MAME,
`emu.test_mpc3k.test_every_eprom_os_boots_316_from_floppy`):** it boots under
the 3.08, 3.11, 3.12 and Vailixi 3.50 EPROMs; it is an MZ executable with
relocations, so the loader places it wherever that EPROM's loader puts it
(notes/floppy_loader.md). **PROVEN (user report, 2026-10-01):** it loads on
Peter's Vailixi machine. Its PDF asks for EPROM 3.11 or later; with 3.08,
MAME shows the load depends on directory-entry bytes `+0Eh..+0Fh`
(notes/waveform_bench.md, 2026-10-02), so 3.08 needs a hardware check.

**The current hooks do not exist in the other OS images as they stand.** Exact
search for the stock bytes at each `WAVE.args` code hook: Vailixi 14 unique
matches, 3.16 8, 3.12 8, 3.11 8, 3.08 6. Many misses are far calls whose
segment operands differ by layout. Shared lineage is clear: 12-byte code
windows from the hooked Vailixi routines recur verbatim in 3.16 at 29–63%
(Edit Sound page 37%, field editor 42%, note-on/allocator 63%, PGM load 29%,
PGM save 31%), close to 3.12/3.11 and well above 3.08 (17–51%). So the
features are a port to 3.16 at new addresses, not a recompile.

**Consequences of targeting 3.16:**

- One `.SYS` for every machine; the EPROM only has to load it. No licensed
  Vailixi bytes in the release, and no per-owner capture.
- While booted from that floppy, the machine runs 3.16 rather than its EPROM
  OS: a Vailixi owner loses Vailixi-only features for that session, and
  sequence memory drops from 484K to 439K (3.16 PDF; MAME test
  `test_sequencer_pool_484k_eprom_439k_floppy_316`).
- Redistributing a modified `M3K316.SYS` needs its authors' terms checked;
  the repo does not record them. **UNDETERMINED.**
