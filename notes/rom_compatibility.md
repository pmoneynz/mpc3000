# Physical Vailixi 3.50: Route A guard rejection

**Current state:** physical `ROMSUM2` completed and measured `81A0`,
confirming the mismatch with reference sum `8634`. The 4 KiB blocks at
reference-file coordinates `7A000` and `7B000` have different sums.
`ROMCHECK4` reached the comparison checkpoint `2400` with `CS=6900`
before stopping. The user also confirms that M3K316.SYS loaded correctly
on this same machine and FlashFloppy. `ROMWORD5` completed physically:
1,287 aligned words differ in the focused 8 KiB window. Its first
difference changes a ROM instruction's DGROUP table displacement from
`7B91` to `7B8F`. The guard remains necessary. A validated `ROMDUMP`
file-capture completed physically. Its saved 32 KiB reproduces all prior
measurements and shows 2,494 differing bytes. The returned disk image and
capture are preserved under `build/hardware/2026-10-01-romdump/`.
`ROMAPP` also completed physically: its 336 KiB capture is verified,
with word sum `7DBA`. The validated capture-specific WAVEHW image is installed in USB slot 1
and safely ejected; see [the profile mapping](wave_physical_profile.md).

## Observation, 2026-10-01

**PROVEN (user photographs):** the physical boot screen identifies Vailixi
3.50 dated `JUN/28/2008` and displays personalized license/serial fields.
The waveform startup subsequently prints the stub's
`Mod needs Vailixi 3.50 EPROMs` warning. The warning is an overstatement:
the implemented check compares a checksum against one reference ROM dump;
it does not identify every Vailixi 3.50 release.

Evidence:

- [`evidence/2026-10-01-licensed-vailixi.jpg`](evidence/2026-10-01-licensed-vailixi.jpg),
  SHA-256 `ef78773d6a59f2ef7f5ef33fe7b1eb493cd16a2e15d5dda7c1554d31cb50d5c3`.
- [`evidence/2026-10-01-wave-guard-rejected.jpg`](evidence/2026-10-01-wave-guard-rejected.jpg),
  SHA-256 `942fcabe7d7a3b25ea0af7ef05576e3ee0a3b8243dd13cbeb8c578406a27dcb3`.

The reconnected USB's `Disk_01.IMG` still matches the deployed waveform
image SHA-256
`a1aa073e9e062629d8cf651cf21597fc1826ee1acf6fb3b9ae134a189a53d3be`.
Thus the stored image is unchanged. This read-back does not independently
verify every byte as loaded into the physical MPC's RAM.

## What the guard actually checks

**PROVEN (code):** `mods/mod_stub.asm` sets `DS=CS`, `ES=F800`, clears
`SI`/`BX`, and adds `0x4000` little-endian words from `ES:[SI]`, advancing
SI by two. The 16-bit sum wraps modulo 65536. The builder calculates the
same operation over linear file `[0x78000,0x80000)`, yielding `0x8634`.
The rejected payload embeds `34 86` at MZ-file offset `0xC0`
(body offset `0xA0`). Only the failed comparison enters the warning path.
It halts before the OS code or DGROUP copies and before `FAC0:0134`.
The waveform feature has not executed in this hardware run.

Reference-model address forms:

| Object | File | CS:IP / operand | 20-bit | 24-bit under reference third PGR, XA=1 |
|--------|------|-----------------|--------|--------------------------------------|
| Checked BIOS/AMX/reset region | `0x78000–0x7FFFF` | `F800:0000–7FFF` | `0xF8000–0xFFFFF` | `0x0F8000–0x0FFFFF`; slots 62/63=`003E`/`003F` |
| Guard comparison | SYS body `0x17` | `6900:0017` | `0x69017` | `0x369017`; slot 26=`00DA` |
| Expected sum | SYS body `0xA0` | `6900:00A0` | `0x690A0` | `0x3690A0`; same slot |

`CS=6900` and those PGR words are established for the repository loader.
The licensed machine's exact loader addresses and PGR contents remain
**UNDETERMINED** from the photographs alone. The fixed operand `F800:SI`
is established by the payload, but its physical translation on that
particular execution has not been captured.

The reference BIOS has 4 KiB word sums, in file order from `0x78000`:
`3E89 4A20 6693 AB65 F800 F800 F800 0393`.

## Why the license text is not yet an explanation

**PROVEN (reference bytes and consumers):** the visible version/date,
license, and serial fields come from DGROUP at linear offsets `0x210F5`,
`0x21110`, and `0x2112B`. Their runtime addresses are `8010:10F5`,
`8010:1110`, `8010:112B`; 20-bit `0x811F5`, `0x81210`, `0x8122B`;
24-bit `0x3811F5`, `0x381210`, `0x38122B` under the reference third PGR
(slot 32=`00E0`, XA=1). They lie outside the summed region.

The user's personalized build may also differ in high-ROM code or data
(**HYPOTHESIS**). The visible personalization alone cannot establish
that the checksum difference is harmless. A load/mapping/read discrepancy
also remains possible until the diagnostic measures it.

## Next observation

Keep the guard in place. A standalone `ROMCHECK` startup compares the
runtime-visible `F800:0000–7FFF` bytes with an embedded reference, checks
the embedded reference's CRC, and displays the differences. It stops
without copying the OS, changing PGR mappings, or writing a ROM, NVRAM,
or floppy file. Its only intended writes are its own RAM/stack and the
BIOS LCD/shadow output path.

The diagnostic is packaged as the only `STARTUP.SYS` in an image for
`Disk_01.IMG`. The next hardware observation is a photograph of its full
LCD report. This is a diagnostic, not a guard bypass or a working waveform
installation. Whether the actual ROM is compatible with the reference
mod remains **UNDETERMINED**.

Do not accept a new checksum merely because the screen says 3.50. A fix
needs the differing code/data located and its significance established;
if required, obtain the actual ROM bytes and build against that artifact.

## First diagnostic build and validation (historical)

Build with `python3 mods/build_romcheck.py`. Outputs are
`build/mods/ROMCHECK.SYS`, `ROMCHECK.img`, and `ROMCHECK.json`.
The 34,184-byte MZ payload embeds the reference 32 KiB window and uses
its own 512-byte stack. It reads the window, calculates its word sum,
counts differing bytes, and checks the embedded reference with
CRC-16/CCITT-FALSE (expected `79E8`). CRC validation covers the embedded
reference, not the entire executable, and is not a proof against all
possible corruption.

**PROVEN (software checks and two MAME executions):** five dedicated
tests pass (`python3 -m unittest discover -s tests -p test_romcheck.py`),
and all 171 boot-slice checks pass. The reference Vailixi run reports
sum `8634`, reference CRC `79E8 OK`, and zero differing bytes. Stock
3.12 reports sum `562C`, `0518C` differing bytes, first `78133`, last
`7FECC`; all four block counts and the eight displayed sample bytes match
the independent Python comparison. Traces are in
`build/emu/romcheck-vailixi/` and `build/emu/romcheck-312/`.
The MAME setup uses panel/LCD support substitutes and emits checksum
warnings for them; these executions do not qualify physical LCD behavior.

The report uses hexadecimal throughout:

| Row | Meaning |
|-----|---------|
| `ROMCHECK STOP 7C=... 7E=...` | Raw reads from I/O ports `FF7C` and `FF7E`; physical readback semantics remain **UNDETERMINED** |
| `SUM EXP ... ACT ...` | Expected and observed 16-bit word sums |
| `REF CRC EXP ... ACT ... OK/BAD` | Integrity check of the embedded comparison reference |
| `DIFF ... FIRST ... LAST ...` | Number of differing bytes and first/last corresponding reference-file offsets; dashes mean none |
| `8K ... ... ... ...` | Counts in the four consecutive 8 KiB blocks |
| `OFF ... EXP:...` | Reference-file offset and eight expected bytes |
| `GOT:...` | Eight observed bytes at the same window offset |
| `NO OS COPY - POWER OFF / PHOTO` | Deliberate stop; no normal OS startup follows |

`OFF` starts at the first difference, clamped to `7FFF8` if necessary so
eight bytes remain inside the window. When there are no differences it
starts at `78000`. These are corresponding reference-file coordinates;
the physical address translation retains the conditional mapping stated
above. The raw port values alone do not establish hardware PGR readback.

## First diagnostic USB deployment (superseded)

**PROVEN (USB read-back, 2026-10-01):** `Disk_01.IMG` then contained the
diagnostic as its only file, `STARTUP.SYS`. `IMAGE_A.CFG` still selects
`Disk_01.IMG`. All other original non-hidden USB files match their prior
hashes. The copy was flushed, re-read, and the USB safely ejected.

- Payload SHA-256:
  `bba78d048b6bee2da541f4b79f3245148646ded37d13eee27269422cf64756db`.
- Deployed image SHA-256:
  `c400f989156a45f94d55339adf011dc019bdec0e2255488c266a707ac87ce8e9`.
- Previous slot-1 waveform image, configuration backups, and deployment
  manifest: `build/usb_backup/romcheck-2026-10-01/`.

FAT formatting metadata can change the image hash on a rebuild; the
manifest pins the deployed artifact. Its SYS bytes match the MAME-tested
payload above. With the MPC off, insert the USB, then power on. Photograph
the entire eight-row screen after `ROMCHECK STOP` appears, then power off.
Hardware results for this diagnostic are still **UNDETERMINED**.

## First diagnostic hang and PGR access error

**PROVEN (user report):** the first diagnostic stayed on `Loading files`
with FlashFloppy displaying track `02.0`. Its USB image was subsequently
re-read with the same deployed hash `c400f989...87ce8e9`. That observation
does not establish the CPU's stopping point: the first diagnostic emitted
no marker before reading the PGR ports or scanning ROM. A drive position
is not an instruction address or proof that loading has not completed.

**PROVEN (source and CPU manual):** the original diagnostic executed
`IN AX,DX` at `FF7C` and `FF7E` before its first output. The reference
loader enters with XA=1. The NEC manual requires expanded addressing to
be disabled when accessing page registers: see
[`NEC V-Series data book`](../01-cpu/NEC_1991_16bit_V-Series_Microprocessor_Data_Book.pdf),
PDF page 361, printed V53 page 46, “Address Expansion Registers.”
Treating these accesses as harmless raw observations was an error.

The local MAME implementation (`06-mame/cpu/nec.cpp:189–192`) maps
`FF00–FF7F` as RAM without testing XA. Therefore the original MAME pass
did not validate those accesses on hardware. The forbidden access is a
strong **HYPOTHESIS** for the hang; the actual hardware response and
stopping instruction remain **UNDETERMINED**. No physical PGR values
were obtained. The old report's raw-port rows and hashes above describe
the superseded artifact, not an approved hardware probe.

**PROVEN (image bytes):** the failed image also retained mtools directory
metadata in entry bytes `+0C..+13` (`00 00 00 7C 41 5D 41 5D`). Vailixi
uses this area for name characters 9–16; an earlier SND-loading trace
showed an `FD00` lookup failure from such metadata
([phase-0 evidence](waveform_phase0.md)). This is another packaging
defect to remove, but that earlier trace does not prove it caused this
SYS-loading hang. The replacement's corresponding bytes are all zero,
as in the successful canary. Both defects must stay distinct from a
confirmed explanation of the physical stop.

The full `ROMCHECK` sources were also corrected: PGR reads, fields and
arguments are removed, and the builder zeros the eight extended-name
bytes. Five focused tests pass, including checks against direct I/O and
nonzero extended-name metadata. A fresh target MAME run completes with
sum `8634` and zero differences (trace:
`build/emu/romcheck-vailixi-nopgr/`). That repaired full diagnostic has not
been deployed; current hardware testing uses the small probe below.

## Replacement: one-cluster ROMSUM2

`python3 mods/build_romsum.py` builds `build/mods/ROMSUM.SYS` and
`ROMSUM.img`, with a manifest in `ROMSUM.json`. The **353-byte** SYS fits
one 512-byte FAT cluster and uses the same deterministic FAT layout as
the successful canary. The 32 KiB embedded comparison reference is
omitted. Reduced size is a diagnostic simplification; file size has not
been established as the cause of the earlier hang.

The first operation after setting DS is to print `ROMSUM2 ENTER` through
the same `INT 43 AX=4` character service used by the physical guard
warning. It retains the loader stack and IF=0, as that guard does. It
then positions and blanks individual report rows using `AX=3` and
ordinary spaces, with no clear-screen call. It reads ROM and calculates
the full word sum and eight consecutive 4 KiB word sums. It executes no
direct port I/O, XA changes, PGR writes, OS copy, or disk/NVRAM writes.

Addresses remain the conditional reference-model forms in the table
above: `F800:0000–7FFF`, 20-bit `F8000–FFFFF`, 24-bit `0F8000–0FFFFF`
under XA=1 and third PGR slots 62/63=`003E`/`003F`, corresponding to
linear-file `78000–7FFFF`. The eight blocks begin at `78000`, `79000`,
`7A000`, `7B000`, `7C000`, `7D000`, `7E000`, `7F000`.

**PROVEN (packaging and MAME):** MZ fields, the single-cluster FAT chain,
both FAT copies, the sole root entry, and extracted payload bytes pass
independent checks. Target Vailixi reports full sum `8634` and block
sums `3E89 4A20 6693 AB65 F800 F800 F800 0393`. Stock 3.12 reports
`562C` and `408C 541A 4E8D 37BD FBC0 4DC2 EA6A 0750`. Both screens
match independent sums calculated from their interleaved chip pairs.
Traces: `build/emu/romsum-vailixi/`, `build/emu/romsum-312/`; validation
record: `build/mods/ROMSUM-validation.json`. These are emulator results,
not physical qualification.

Expected reference screen content (other boot text may remain):

```text
SUM EXP 8634 ACT 8634
78000+4K: 3E89 4A20 6693 AB65
7C000+4K: F800 F800 F800 0393
ROMSUM2 DONE - PHOTO / POWER OFF
...
ROMSUM2 ENTER
```

`ENTER` appears first, at the bottom; `DONE` appears after all sums.
If the screen stops earlier, photograph whichever marker is visible.
The sums localize a mismatch but cannot prove byte identity or approve
compatibility. The Route A guard remains unchanged.

### ROMSUM2 deployment and next observation

**PROVEN (USB verification):** `Disk_01.IMG` was replaced with the new
image, flushed and re-read. `IMAGE_A.CFG` selects `Disk_01.IMG`; every
other original non-hidden USB file matches its prior hash. The USB was
safely ejected. The previous failing diagnostic and configurations are
backed up in `build/usb_backup/romsum-2026-10-01/`, alongside
`before.json` and `deployment.json`.

- Payload SHA-256:
  `8d03f73748212fc4bc869afe2765be4ad7f2bd37dbaace0e7e7ee19138d78923`.
- Image SHA-256:
  `76018ac9843fbb478bf828522a5e2debd30e2c7747532403967e5b0204900f3b`.

Insert the USB with the MPC off, power on, and photograph the whole LCD
at `ROMSUM2 DONE`, or at whichever screen it stops on. Power off after
the photograph. The physical result remains **UNDETERMINED**; no checksum
guard was bypassed and waveform compatibility is still unresolved.

## Physical ROMSUM2 result

**PROVEN (photograph, one execution):** the LCD shows both
`ROMSUM2 ENTER` and `ROMSUM2 DONE`. The measured full sum is `81A0`.
Evidence: [`2026-10-01-romsum2-result.jpg`](evidence/2026-10-01-romsum2-result.jpg),
SHA-256 `420df8ac3185fe04154ff9c036a16b2be8b91cac51f895fd582e393a00f6f9fc`.
The transcription and independent arithmetic check are in
[`2026-10-01-romsum2-result.json`](evidence/2026-10-01-romsum2-result.json).

| Reference-file 4 KiB block | Expected sum | Observed sum |
|---------------------------|--------------|--------------|
| `78000–78FFF` | `3E89` | `3E89` |
| `79000–79FFF` | `4A20` | `4A20` |
| `7A000–7AFFF` | `6693` | `4473` |
| `7B000–7BFFF` | `AB65` | `C8F1` |
| `7C000–7CFFF` | `F800` | `F800` |
| `7D000–7DFFF` | `F800` | `F800` |
| `7E000–7EFFF` | `F800` | `F800` |
| `7F000–7FFFF` | `0393` | `0393` |

The observed block sums add to `81A0` modulo 65536. The two nonzero
deltas are `DDE0` and `1D8C`, summing to `FB6C` (`81A0–8634` modulo
65536). Thus the previously rejected checksum is reproduced by an
independent payload. This establishes a runtime-window mismatch in this
execution; it does not identify the changed bytes, prove the other six
blocks identical, or establish compatibility.

The differing blocks use operands `F800:2000–3FFF`, equivalent to
`FA00:0000–1FFF`; 20-bit addresses `FA000–FBFFF`. Under the reference
third PGR, XA=1, slot 62=`003E`, these reach 24-bit `0FA000–0FBFFF`
and reference linear-file `7A000–7BFFF`. The physical mapping on the
personalized build remains conditional; no PGR readback is claimed.

**PROVEN (reference contents):** these are live regions as well as
padding. The first block contains FAC0 reset/init/XA code and all three
PGR tables; the second contains AMX scheduler/public services, tables,
and the SYS handoff. Evidence: [owner ledger](../analysis/owner_ledger.json),
[PGR writers](pgr_live_after_amx.md), [padding bounds](patch_space.md),
and [loader](floppy_loader.md). A checksum cannot distinguish changes to
those routines from differences in padding. Under the reference mapping
these are EPROM regions, with no established RAM-copy alias at this
stage. A licensed-only mapping change remains **UNDETERMINED**.

## ROMCHECK3 byte comparison

The full comparison now prints `ROMCHECK3 ENTER` before scanning ROM,
uses only the physically observed `INT 43 AX=3/4` display services,
and clears rows with spaces. It makes no direct port accesses. Its FAT
extended-name bytes are zero. The report compares the whole 32 KiB
window with an embedded reference and displays its CRC, mismatch count,
first/last differing offsets, four 8 KiB counts, and eight sample bytes.
Equal additive sums elsewhere will not hide differences from this pass.

**PROVEN (software):** five focused tests pass. MAME runs with target
Vailixi and stock 3.12 produce all eight rows exactly as independently
calculated in the manifest. Evidence:
`build/emu/romcheck3-vailixi/` and `build/emu/romcheck3-312/`.
The physical result for this revision remains **UNDETERMINED**.

**PROVEN (USB read-back):** the reconnected USB still held the tested
ROMSUM2 image. It was backed up under
`build/usb_backup/romcheck3-2026-10-01/`, then slot 1 was replaced with
ROMCHECK3, flushed, and re-read. All other original non-hidden USB files
are unchanged, `IMAGE_A.CFG` still selects slot 1, and the USB was safely
ejected. The deployment manifest is in that backup directory.

- SYS size: 34,198 bytes, sole disk file `STARTUP.SYS`.
- SYS SHA-256:
  `4b1b32ba0996ab844e641f66dafc3eecccdc88235ee6c95d72c3424390b2829f`.
- Image SHA-256:
  `d2cbf08949f38d9a2902bdabda4e251e4d75219969a2264103d9584bc3b525ff`.

Next observation: insert USB with MPC off, power on, and photograph the
whole LCD at `ROMCHECK3 STOP` (or whichever screen it reaches), then
power off. The stop is deliberate and the waveform mod is not installed.

## ROMCHECK3 entry-marker stop; ROMCHECK4 instrumentation

**PROVEN (user report):** `ROMCHECK3 ENTER` remained on the physical
LCD for at least 30 seconds. This establishes that entry and character
output were reached. It does not establish that `print_line` returned,
or identify which subsequent instruction stopped. On reconnection the
USB image still matched the deployed ROMCHECK3 hash. No physical byte
comparison result was obtained.

**PROVEN (bounded source audit):** the sum/comparison/CRC loops have
finite counts and preserve their loop registers. ROMCHECK3's reference
occupied `CS:0576–8575`, without 64 KiB wrap; its stack reserves 512
bytes below `CS:0576`. The MZ header describes the correct file length.
No instruction or arithmetic error explaining the physical stop was
found. The exact cause remains **UNDETERMINED**.

Unlike the small ROMSUM2, the comparator reads later pages of its loaded
payload. Under the reference map those pages are ordinary RAM. A
different mapping or load segment in the licensed build is a
**HYPOTHESIS**, not a measured cause. The mismatching ROM blocks contain
the PGR tables and handoff code, so the missing observation remains
material. Direct PGR reads in XA=1 remain forbidden; none were added.

ROMCHECK4 retains the comparison, CRC, display, and private-stack logic
and adds the following visible checkpoints:

| Visible text | What it establishes if reached |
|--------------|--------------------------------|
| `ROMCHECK4 ENTER` | Initial output reached; return from it not yet established |
| `RC4 1 ENTRY RETURNED - SUM CS=....` | Entry-print call returned; measured code segment appears when the four hex digits replace dashes |
| `RC4 2 SUM DONE - COMPARE START` | Full word-sum loop and result store completed |
| `RC4 COMPARE NEXT OFFSET ....` | Comparison is about to read that window offset; updates every `0400` bytes |
| `RC4 3 COMPARE DONE - CRC START` | Full byte comparison completed |
| `RC4 CRC NEXT OFFSET ....` | Embedded-reference CRC is about to process that offset; updates every `1000` bytes |
| `RC4 4 CRC DONE - FORMAT START` | CRC loop and result store completed |
| `RC4 5 FORMAT DONE - REPORT START` | Report fields were formatted |
| `ROMCHECK4 STOP` and full report | Normal terminal report path reached |

Progress offsets are relative to the 32 KiB comparison window, not
absolute physical addresses. ROMCHECK4's embedded reference starts at
`CS:06CC` and ends at `CS:86CB`. If the measured CS is `6900`, it crosses
20-bit page boundaries `6C000` and `70000` at comparison offsets
`2934` and `6934`; under reference XA=1, third PGR slots 26/27/28 are
`00DA/00DB/00DC`, yielding 24-bit RAM `368000–373FFF`. Actual licensed
PGR words remain unknown. A stop near a boundary would narrow the
investigation, not prove that the mapping caused it.

**PROVEN (software):** the progress helpers preserve live registers and
flags. Five focused tests pass, and complete MAME reports for Vailixi
and stock 3.12 match the manifest's independent expectations. Traces:
`build/emu/romcheck4-vailixi/` and `build/emu/romcheck4-312/`.

**PROVEN (USB read-back):** slot 1 was backed up in
`build/usb_backup/romcheck4-2026-10-01/`, replaced, flushed, and re-read.
All other original non-hidden USB files are unchanged; slot 1 remains
selected and the USB was safely ejected. The deployment manifest is in
that backup directory.

- SYS size: 34,540 bytes.
- SYS SHA-256:
  `19ebb564064cad07af902a3b15abd117655a8318718067fc129461b6b189e97f`.
- Image SHA-256:
  `9cda0699fbb4e6b982393a39f93bec45cb5df74ef5e881e053a92f4c28c4d297`.

Next observation: boot with USB inserted before power-on and photograph
the whole screen wherever it stops. The last stage/offset is the useful
measurement; power off afterward. Physical results are **UNDETERMINED**.

## ROMCHECK4 comparison checkpoint and successful 3.16 load

**PROVEN (photographs and user report):** the screen is not limited to
the bottom `ROMCHECK4 ENTER` marker. Its upper rows show:

```text
RC4 1 ENTRY RETURNED - SUM CS=6900
RC4 2 SUM DONE - COMPARE START
RC4 COMPARE NEXT OFFSET 2400
```

Evidence: [LCD photograph](evidence/2026-10-01-romcheck4-compare-2400.jpg),
SHA-256 `46167a8635a7181550ca34e5c828ca85871bae4fe42aca7b0187eecf319b361c`;
[FlashFloppy photograph](evidence/2026-10-01-romcheck4-flashfloppy-track02.jpg),
SHA-256 `54de110a9aa3fc525385fcb8ae05ec0c9749e997f4d9a8b763a786d928fe936e`.
The latter shows slot 1 and track `02.0`. The transcription is in
[`romcheck4-compare-2400.json`](evidence/2026-10-01-romcheck4-compare-2400.json).

The initial print returned, the full ROM word sum completed, and output
for the comparison checkpoint at `2400` was reached. The next checkpoint
would be `2800`. The exact stopping instruction is unknown: it could be
in the checkpoint's remaining output/return path or the subsequent
comparison interval. This program makes no floppy file-service calls
after entry; the displayed drive position does not locate the CPU or
prove a continuing file read.

With measured CS=`6900`, ROMCHECK4's reference operand at offset `2400`
is `6900:2ACC`, 20-bit `6BACC`, conditional 24-bit `36BACC` under XA=1,
reference third-PGR slot 26=`00DA`. Its actual-ROM operand is
`F800:2400`, 20-bit `FA400`, conditional 24-bit `0FA400` under slot
62=`003E`, corresponding to reference file `7A400`. The next reference
page crossing is offset `2934`, beyond this checkpoint interval. Thus
the simple page-crossing hypothesis does not account for this location.

**PROVEN (user report):** M3K316.SYS loaded correctly on this same machine
using the same FlashFloppy. The report supports the ability to load and
run a substantially larger OS payload and argues against a general drive
failure or simple 34 KiB file-size limit. It does not establish every
byte of the diagnostic's RAM image or identify the comparison fault.

No invalid instruction or ABI error was found in ROMCHECK4's comparison
loop. `INC word [disp16]` is a supported V53 instruction, also used by
the stock timer path. A fault at the first mismatch bookkeeping or a
byte-read difference remains a **HYPOTHESIS**, not a diagnosed cause.
ROM word reads across the whole window already completed in ROMSUM2
and ROMCHECK4. The next test collects data through that proven read width.

## ROMWORD5 focused comparison and deployment

`mods/build_romword.py` builds a deterministic FAT12 image containing
only `STARTUP.SYS` from `mods/romword.asm`. The 8,990-byte MZ compares
aligned **16-bit words** in `F800:2000–3FFE`, corresponding conditionally
to reference file `7A000–7BFFF`. It embeds only that 8 KiB reference,
keeps the loader stack, and holds the scan count and first/last mismatch
offsets in registers. No direct I/O, PGR changes, OS copies, or file
writes are performed. Text uses the already observed `INT 43 AX=3/4`.

At CS=`6900`, the embedded reference is `CS:02FE–22FD`, 20-bit
`692FE–6B2FD`, all within page 26; conditional 24-bit
`3692FE–36B2FD` under XA=1 and PGR26=`00DA`. The runtime comparison
window stays in page 62. The probe also changes read width, counter
storage, stack choice, and reference size: success would acquire the
missing data, not prove which of those differences fixed the old stop.

The first row checks the embedded reference's additive word sum against
`11F8`; a mismatch prints `REFERENCE BAD` and stops. This is a limited
integrity check, not a collision-free proof. Scan progress updates every
`100` bytes. The first differing word is printed immediately as
`FIRST <file offset> EXP <word> GOT <word>`, before the scan continues.
The final `WORDS` value counts differing **words**, not bytes; first
and last are their even reference-file offsets. The sample rows show
four consecutive 16-bit words at the displayed file offset. For example,
word `0305` means bytes `05 03`. No whole-ROM identity claim follows
from this focused 8 KiB comparison.

**PROVEN (software):** MZ fields, sole directory entry, zero extended-name
metadata, both FAT copies and the complete extracted cluster chain were
checked. MAME target Vailixi reports zero differing words. Stock 3.12
reports `0BBD` differing words, first `7A000`, last `7BFFE`, with all
sample words matching the independent Python comparison. A deliberately
damaged embedded reference reports `11F9` and stops at `REFERENCE BAD`.
Evidence: `build/emu/romword5-vailixi/`, `romword5-312/`,
`romword5-badref/`, and `build/mods/ROMWORD-validation.json`.
All 171 boot-slice checks pass.

The diagnostic assemblers now explicitly select the 8086 instruction
subset. This prevents unintended 386 near-conditional-jump encodings
in future edits. ROMSUM2 and ROMCHECK4 remain byte-identical when rebuilt
with that constraint, so this change is not an explanation of their
different physical results.

**PROVEN (USB read-back):** the reconnected slot 1 still matched ROMCHECK4.
It was backed up in `build/usb_backup/romword5-2026-10-01/`, then replaced
with ROMWORD5, flushed, and re-read. All other original non-hidden USB
files match their previous hashes; slot 1 remains selected and the USB
was safely ejected. Its deployment manifest is in the backup directory.

- SYS SHA-256:
  `5142c26c11ecfa32fbe9a4552766d31e414e663b014e8b1e0c4473e98e377ca1`.
- Image SHA-256:
  `c25553af348026721a1dc5f102d7b31e51c62f9cdfe3f5c2705f064ca6e6a997`.

Next observation: boot with the USB inserted before power-on, photograph
the whole LCD at `ROMWORD5 DONE` or wherever it stops, then power off.
The physical result was subsequently obtained below. Keep the waveform guard.

## ROMWORD5 physical result and DGROUP compatibility

**PROVEN (one physical execution):** the
[full LCD photograph](evidence/2026-10-01-romword5-result.jpg) shows
`ROMWORD5 DONE`, entry `CS=6900`, embedded-reference sums `11F8/11F8`,
and the following comparison result. The
[transcription](evidence/2026-10-01-romword5-result.json) preserves its
units and limits. Photograph SHA-256:
`4ffac8569f41954a3e23d08803e7bec4604425d730eecbb5bd3aea3ce692ba30`.

```text
WORDS 0507 FIRST 7A25C LAST 7BA00
EXP 7B91 7404 8A09 B4C2
GOT 7B8F 7404 8A09 B4C2
```

`0507` is hexadecimal: **1,287 differing aligned words** in
reference-file `[7A000,7C000)`. It is not a byte count, nor a comparison
of the complete ROM. The matching reference sum is an additive integrity
check. It does not prove every embedded reference byte correct.

**PROVEN (reference code plus observed operand):** file `7A25C` is the
16-bit displacement in `TEST byte [BX+7B91],04` at `F800:225A`, within
the reference helper entered at `F800:2244`. The corresponding physical
word is `7B8F`; the following three words agree with the reference. The
operand word is at `F800:225C`, 20-bit `FA25C`, conditional 24-bit
`0FA25C` under XA=1 and reference third-PGR slot 62=`003E`.

The reference helper tests character classification and conditionally
adds `20` to convert uppercase to lowercase. Established reference
callers include far calls at linear `31E47` and `327F4`. The reference
DGROUP classification table starts at file `27B91`, copied to
`8010:7B91` (20-bit `87C91`, conditional 24-bit `387C91` under XA=1,
third-PGR slot 33=`00E1`). The observed operand instead addresses
`8010:7B8F` for BX=0 (20-bit `87C8F`, conditional 24-bit `387C8F`).
For example, character `41` selects reference byte `14` at table+`41`,
whereas using displacement `7B8F` with that same reference DGROUP
selects `40`. Thus copying the repository DGROUP while retaining this
physical ROM instruction can change the classification test.

**HYPOTHESIS:** the personalized ROM uses a matching DGROUP layout with
this table two bytes earlier. One measured operand does not prove a
uniform shift or locate every related difference. **UNDETERMINED:**
the complete physical helper and remaining 1,286 changed words, the
personalized application/DGROUP contents, and a compatible WAVE build.
Do not accept checksum `81A0` as sufficient compatibility evidence.

The user confirms that no dumps from this particular machine are
available; `07-rom/Vailixi 3.50/` contains only the generic reference.
The next software step is a capture of the currently readable
`F800:0000–7FFF` window to a preallocated floppy file. This captures
32 KiB, not the entire 512 KiB EPROM image. Lower-ROM mapping and the
actual disk-write behavior remain separate observation boundaries.


## ROMDUMP high-window capture and deployment

`mods/romdump.asm` and `mods/build_romdump.py` produce a 1,234-byte
MZ and a deterministic FAT12 image containing `STARTUP.SYS` and an
already allocated 32,768-byte `BIOS.BIN`. The initial output file is
filled with `A5`, so an untouched or partially written file is detectable
when the USB returns. This file is inside `Disk_01.IMG`, not at the USB
filesystem root.

The probe keeps the loader stack, uses the 8086 instruction subset, and
copies 64 chunks of 256 aligned words from `F800:0000–7FFE` into a
512-byte RAM buffer. `INT 41` writes each RAM buffer sequentially;
it never receives ROM as a byte-copy source. The filename object is
fixed 8+3 `BIOS    BIN` with a NUL extension marker. Each write must
return AX=0 and CX=0200; final close must succeed before `ROMDUMP DONE`.
Open, write, short-write, and close failures lead to an error screen.

The buffer is `CS:02B2–04B1`: for measured/prior CS=6900, 20-bit
`692B2–694B1`, conditional 24-bit `3692B2–3694B1` under XA=1 and
reference third-PGR slot 26=`00DA`. Source is 20-bit `F8000–FFFFF`,
conditional 24-bit `0F8000–0FFFFF` under slots 62/63=`003E/003F`,
corresponding to reference linear file `[78000,80000)`. No PGR or XA
changes are made. The port writes restore the loader-observed
`C011=F6` for file calls and `C011=FF` on terminal paths; device-bit
semantics remain the existing U-C0XX boundary. Firmware close may
update directory metadata; the pristine preallocation avoids requesting
new clusters. The diagnostic is intended only for its supplied image.

**PROVEN (software):** seven focused build/packaging checks passed,
as did an independent FAT-chain walk, both FAT copies, file extraction,
MZ bounds/entry/inherited stack checks, and the 171 boot-slice checks.
Headless MAME tests ran against disposable copies, leaving the deployment
image pristine. Reference Vailixi produced `DONE`, sum `8634`, and a
file exactly matching its high 32 KiB (SHA-256
`8fc531c1b8e1d160ffa2a6a7b965eda45c31ff147d74d9e880e24c20f8c10748`).
Stock 3.12 produced sum `562C` and exact capture SHA-256
`5588ceeee7a4ad4db781c2fd724df9d6a7710713c369d7b575c77a292432c56a`.
In both tests every byte outside the output file's existing data extent
was unchanged. A missing-file clone produced `ERROR O AX=FD00`, no
success marker, and no disk-image changes. Evidence is aggregated in
`build/mods/ROMDUMP-validation.json`.

**PROVEN (deployment):** the connected USB still matched ROMWORD5.
It was backed up under `build/usb_backup/romdump6-2026-10-01/`, then
slot 1 alone was replaced, flushed, and read back. All other original
non-hidden USB files are unchanged; `IMAGE_A.CFG` selects slot 1.
macOS initially declined ejection due to loginwindow; a safe retry after
sync succeeded. No forced unmount was used.

- Payload SHA-256:
  `91e5e01a832509b15e3d75151d5d3b61b12ae84fa6efbd34a49baa9a74ad8583`.
- Pristine image SHA-256:
  `d398437a0e4fca0fa70733d6dab678d824bc303082840bd6c72084d75f40a0b4`.
- Deployment manifest: `build/usb_backup/romdump6-2026-10-01/deployment.json`.

**Next physical observation:** insert USB with the MPC powered off, boot,
and wait for `ROMDUMP DONE`. Leave it ten seconds after DONE and wait for
drive activity to stop before powering off. Reconnect the USB to the
computer; preserve `Disk_01.IMG` for extraction. If it shows an error or
stops before DONE, photograph the full LCD and report that result.
Physical file-write completion is **UNDETERMINED** until this run and
returned-file checks. The output covers only 32 KiB; it does not supply
the lower ROM or establish WAVE compatibility.


## Returned physical ROMDUMP capture

**PROVEN (one hardware run and returned USB read-back):** the
[completion photograph](evidence/2026-10-01-romdump-done.jpg) shows
`ROMDUMP DONE` and `WORD SUM 81A0`. The full returned `Disk_01.IMG`
was copied before analysis to `build/hardware/2026-10-01-romdump/`.
Both FAT copies agree, the entire BIOS.BIN cluster chain is valid,
and extracted `STARTUP.SYS` equals the deployed payload. **Every byte
outside BIOS.BIN's existing data extent is unchanged** from the pristine
image, including FAT, directory, and startup content. The USB was read
only during extraction.

- Returned disk SHA-256:
  `78a9c63f51ed4611ff4c1c328f2a779a1b4628d685e9d9fa5efb0d495acf1d8e`.
- Captured `BIOS.BIN`: 32,768 bytes, SHA-256
  `2c654334e011af2943d1d08f05e3ce48ebccdf49600aab7a2f040ba016c21168`.
- Photograph SHA-256:
  `e785953928aed3a2889e1e68d54320212f13d4cec51201a509d9d3870231d5b0`.
- [Evidence metadata](evidence/2026-10-01-romdump-result.json).

The extracted file's sum is `81A0`; its eight 4 KiB sums are
`3E89 4A20 4473 C8F1 F800 F800 F800 0393`, exactly matching ROMSUM2.
It differs from the generic reference at 2,494 bytes in 87 contiguous
runs, comprising 1,287 aligned words. The first/last changed coordinates
are `7A25C`/`7BA00`, exactly matching ROMWORD5. These are reference-file
coordinates for runtime `F800:0000–7FFF`; physical address/mode conditions
are unchanged from the capture contract above. The portions before
`7A25C` and after `7BA00` are now established **byte identical**, rather
than merely equal in additive sum.

`capture.json` preserves extraction metadata and `comparison.json`
preserves each exact changed-byte run in the capture directory. The
captured bytes are evidence for the personalized machine; they do not
replace the project's canonical generic Vailixi target or alter `07-rom/`.
Compatibility work must account for the shared BIOS/scheduler and DGROUP
layout changes before a physical WAVE build can be qualified.


### Concrete startup-layout differences in the capture

**PROVEN (captured bytes versus reference):** the DGROUP-copy immediate
at file-coordinate `7AC85` changes from `7C92` to `7C90` (instruction
`FAC0:0084`). At the Route A rejoin `FAC0:0134`, the actual initialization
sets DI=`7C90`, CX=`FFB6`, and ES=`F076`; the reference sets DI=`7C92`,
CX=`FFB8`, and ES=`F07A`. The changed immediate-byte coordinates are
`7AD3E`, `7AD41`, and `7AD52`. These are 20-bit `FAD3E`, `FAD41`, and
`FAD52`, conditional 24-bit equal under XA=1, PGR62=`003E`.

Thus the existing Route A stub's fixed reference DGROUP copy and rejoin
would feed the physical startup routine incompatible layout assumptions.
Matching the physical high-ROM checksum alone cannot repair that.
The generic builder consumes DGROUP `[20000,27C92)` and code
`[30000,74000)`. The personalized matching data/code bytes are absent
from this high-window capture and are the next required source evidence.
The PGR tables and wrapper in the captured high window can be checked
before designing a bounded acquisition of that region.


### Shared-entry ABI shift

**PROVEN (entry-anchored comparison):** the captured AMX region uses
entry offsets ten bytes earlier than the generic 3.50 image, matching
the placement pattern in the supporting 3.12 image. This does not make
the whole capture stock 3.12. For example, generic `FB00:0157` becomes
captured `FB00:014D`; generic `FB00:0347` becomes captured `FB00:033D`.
The corresponding file coordinates are `7B157` versus `7B14D`, and
`7B347` versus `7B33D`. The logical 20-bit addresses are `FB157` versus
`FB14D`, and `FB347` versus `FB33D`; conditional 24-bit addresses equal
these under XA=1 with PGR62=`003E`.

The established generic ISR at `D52A:0008` (file `552A8`) calls
`FB00:0157`. In the captured BIOS, offset `0156` starts `MOV BX,DS`
(bytes `8C DB`), so its old target `0157` lands inside that instruction
and skips the register-saving entry at `014D`. Similarly, the old
vector-helper entry `0347` skips the actual helper's pushes at `033D`
but reaches its later pops. These are concrete ABI incompatibilities,
not just differing checksums.

The full public-entry mapping, generic -> captured, is:
`0157->014D`, `0194->018A`, `0347->033D`, `038A->0380`,
`0396->038C`, `03B3->03A9`, `0469->045F`, `0484->047A`,
`04AC->04A2`, `0552->0548`, `0586->057C`, `0624->061A`,
`0637->062D`, `0648->063E`, `065B->0651`, `067C->0672`,
`06B9->06AF`, `06E8->06DE`, `0725->071B` (all in segment FB00).
A matching application/data capture is required before selecting new
patch sites and rebuilding the hardware WAVE variant.


### Reference-file audit incident and recovery

During follow-up analysis, an audit command passed a two-file wildcard
to `xxd`. Its second positional path was interpreted as an output file,
replacing the generic MSO chip file with 608 bytes of textual hex output.
The mandatory source-hash check detected the change. This was an agent
error, not a change in the physical capture or the machine's ROM.

The affected bytes were preserved under
`build/recovery/2026-10-01-mso/`. A recovery copy from Git HEAD matched
both the canonical MSO SHA-256 and the independent existing MAME chip
copy. The user explicitly approved restoring the original despite the
normal prohibition on writes under `07-rom/`. Restoration was verified
byte for byte, `07-rom/` has no Git changes, and all 171 boot-slice checks
pass afterward. The physical capture's SHA-256 was rechecked and is
unchanged. No new probe was built or deployed using the corrupted file.
The recovery record is `build/recovery/2026-10-01-mso/recovery.json`.


## ROMAPP guarded application/data capture

The next probe captures reference-file `[20000,74000)` (336 KiB),
covering the DGROUP and all 17 code chunks consumed by the WAVE builder.
It uses first-PGR logical `A0000–F3FFF`, conditional 24-bit
`0A0000–0F3FFF` under frames 0028–003C. Slot 61 (`F4000–F7FFF`, frame
0140) remains the NVRAM mapping and is excluded from reads. Together
with BIOS.BIN this still leaves reference-file `[00000,20000)` and
`[74000,78000)` uncaptured; it is not a complete 512 KiB chip dump.

Before changing the map or opening the output, ROMAPP compares all
16,384 aligned high-ROM words with the preserved physical BIOS capture.
The expected array is embedded in the 50,236-byte MZ. Its buffer is
`CS:041C–441B`, guard `CS:441C–C41B`, and body end `CS:C41C` exclusive.
For CS=6900, their 20-bit ranges are `6941C–6D41B` and `6D41C–7541B`;
conditional 24-bit ranges are `36941C–36D41B` and `36D41C–37541B`
under the shared first/third-PGR RAM frames. All working bytes stay
below logical A0000; the inherited stack remains `0040:69C4`.

**PROVEN (control-flow and software tests):** a real INT12 creates the
interrupt return frame. Its local RAM handler pushes DS, SI, AX, BX, CX,
DX in the order consumed by `FAC0:024F`, then stages RAM IVT12 with
`FAC0:01C6`. It supplies SI=0256, CX=0040, DX=FF00 and executes literal
`0F F0 12` (RETXA12). Under XA=0, the existing ROM CS:OUTSW loop at
`FAC0:01C6` (file `7ADC6`, physical FADC6) loads the first PGR from
`FAC0:0256` (file `7AE56`, physical FAE56). Its BRKXA12 uses the ROM
vector and returns through `FAC0:024F` (file `7AE4F`, physical FAE4F),
popping the saved registers and the real interrupt frame under XA=1.
These high-ROM addresses are identical physical addresses under XA=0
and under XA=1 with PGR62=003E. Bytes `[7ADA4,7AED6)` are identical
in the captured, generic 3.50, and supporting 3.12 ROMs.

For each of 21 pages, the probe reads 8,192 aligned ROM words into its
16 KiB RAM buffer, then calls INT10 to restore the third PGR **before**
any display or file service. It writes 32 sectors from RAM using the
already exercised INT41 API, checking status and byte count, then closes
the preallocated `ROMAPP.BIN` before displaying DONE. The total output
is exactly 672 sectors. The brief XA=0 transition on this physical
machine remains the required hardware observation.

**PROVEN (validation):** seven focused tests and an independent full FAT
chain/MZ/file-boundary check pass. Positive MAME fixtures replace only
the embedded expected-BIOS array with the emulator's ROM slice; every
byte outside that array is asserted identical to the final physical
payload. Both generic 3.50 and stock 3.12 save exactly their known
336 KiB source region, with every image byte outside ROMAPP.BIN unchanged.
Their output sums are 2EE7 and 6C12 respectively. Selected PGR traces
show exactly 21 first/third pairs after the initial loader transition;
slot 61 remains 0140 throughout. This is qualified testing of identical
capture code with substituted guard data, not an emulation of the
complete personalized firmware.

The unmodified final physical-guard image, run against generic 3.50,
reports `ERROR G AX=225C CX=7B91 P=00`, never reports DONE, and leaves
the entire disk image unchanged. One earlier agent-run emulator process
stalled before producing snapshots and was stopped; the independent
retry produced this result. All 171 canonical boot checks pass after
the source-file recovery. Evidence is aggregated in
`build/mods/ROMAPP-validation.json`.

**PROVEN (USB deployment):** the returned ROMDUMP image was additionally
backed up under `build/usb_backup/romapp-2026-10-01/`. Only Disk_01.IMG
was replaced, flushed, and read back; every other original non-hidden
USB file is unchanged. Slot 1 remains selected. Safe ejection succeeded.

- Final physical payload SHA-256:
  `a8e717cc895f0b39e195cc6a983a33f2af2529fb33a8bf2cd8a9c96ce0afff1d`.
- Pristine deployed image SHA-256:
  `320d4509fc2c66f37597250ffdd2ddbfa0aec5d270f5549f13e410baf86634cc`.
- Deployment record: `build/usb_backup/romapp-2026-10-01/deployment.json`.

**Next observation:** insert the USB while the MPC is off, boot, and
wait for `ROMAPP DONE`. After another ten seconds with drive activity
stopped, power off and reconnect the USB for extraction. If an error
appears or progress stops, photograph the full LCD. Preserve the returned
image before any subsequent deployment. Physical capture and WAVE
compatibility remain **UNDETERMINED** until those separate checks.

## Returned physical ROMAPP capture

**PROVEN (physical photograph and returned FAT12 file):** ROMAPP completed
21 pages / 336K, word sum `7DBA`. The preserved image is
`build/hardware/2026-10-01-romapp/Disk_01.IMG`, SHA-256
`94b3575d6a5291f6ff154fcd37ce3b2552d8398337dc2587c28b295c09fddd29`.
Both FAT copies agree; all 672 output clusters were followed and checked.
STARTUP.SYS matches the deployed payload, and every image byte outside
ROMAPP.BIN is unchanged. Output is exactly 344,064 bytes, SHA-256
`bc1dd8cd6d59714c1a1b0d4f5145df26a2cfec8be14ca0787f9cbef8c22be1e2`.
Evidence: `notes/evidence/2026-10-01-romapp-result.json` and its photograph.
The initial conversational transcription `7D8A` was corrected to `7DBA`
after checking the photograph and extracted data; the capture is intact.

**PROVEN:** the capture supplies reference-file coordinates
`[20000,74000)`, first-PGR XA=1 logical/20-bit `A0000..F3FFF`,
24-bit ROM `0A0000..0F3FFF`. The NVRAM slot at `F4000` is excluded.
Together with BIOS.BIN `[78000,80000)`, these captures include every byte
needed by the RAM OS builder: DGROUP `[20000,27C90)`, OS code
`[30000,74000)`, and high-ROM compatibility bytes `[78000,80000)`.
The files remain scoped captures, not a complete 512 KiB ROM dump.

The previously requested physical observation for ROMAPP's PGR transition
is now satisfied for this execution. WAVE execution on hardware remains
**UNDETERMINED** pending a separate run of the adapted waveform image.

## WAVEHW capture-specific waveform build

**PROVEN (software):** `mods/build_wave_physical.py` pins both returned
capture hashes and constructs WAVEHW.SYS exclusively from their covered
DGROUP/code/BIOS ranges. Unobserved ranges are zero-filled workspace and
are never copied into the startup file. The canonical generic builder
and WAVE.SYS remain byte-identical. The profile uses the six individually
verified RAM offsets in [the mapping report](wave_physical_profile.md),
the unchanged call/hook addresses, and the captured 7C90-byte DGROUP.
The RAM boot marker is `WAVE BENCH 02`; captured license/serial objects
are preserved.

The loader now compares every one of 16,384 aligned high-ROM words,
not a sum. A mismatch prints `Mod ROM mismatch` and stops before any
relocation. Embedded expected bytes occupy `CS:0096..8095`; the stub
ends at `CS:809C`. At the observed loader CS=6900 under XA=1 third PGR,
these bytes are 20-bit `69096..71095`, 24-bit `369096..371095`.
DGROUP source is `CS:80A0..FD2F`, 20-bit `710A0..78D2F`, 24-bit
`3710A0..378D2F`. The first code source paragraph is CS+0FD3.
The complete descending code-copy and subsequent DGROUP-copy operations
were independently simulated word by word at both supported loader
segments 6900 and 7000; final destinations exactly match the declared
patched captured ranges. Physical rejoin is still `FAC0:0134`, linear
file `7AD34`, 20/24-bit `FAD34` under third-PGR slot 62=003E.

**PROVEN (emulator):** the captured application/high BIOS with explicitly
borrowed generic holes `[00000,20000)` and `[74000,78000)` cold-boots to
Play/Record. The unmodified final WAVEHW payload passes five regressions:
exact mono/stereo LCD pixels; trim/zone edits and return to Edit Sound;
unsigned long-step +32768/-32768, empty-sound display and mode exit;
no-sound Help behavior; and rejection of the generic high ROM. Positive
tests use the actual captured guard bytes with no substitution. The
negative test leaves its whole disk image unchanged. This composite
fixture does not qualify physical LCD/panel behavior or establish the
uncaptured ROM contents.

Independent FAT12 validation checks both FAT copies, every cluster chain,
no crosslinks, the exact three files, MZ header, embedded high ROM, and
captured DGROUP/code with only the declared patches. All 19 capture-probe
regressions and 171 canonical boot checks pass. Frozen build evidence is
`build/mods/WAVEHW-validation.json`; emulator log is
`build/wavehw-tests.log`.

- Payload: 343,376 bytes, SHA-256
  `92f73b10139978b8a5c2abe7478cbc45614fa2d9972a0e73836e47048d5e207d`.
- Bench image: 1,474,560 bytes, SHA-256
  `05262e05d4ae2d0ebcaeb3fc247e994bcc6aff92d930adbeb451f21c82a53767`.
- Root files: `STARTUP.SYS` (the above WAVEHW payload), `SINE441.SND`,
  and `STEREO1.SND`. No capture probe remains inside this image.

**UNDETERMINED:** physical boot, waveform pixels, keys and editing for
this adapted build. The next bench run supplies those observations.

**PROVEN (USB deployment):** the returned ROMAPP disk and configuration
were backed up under `build/usb_backup/wavehw-2026-10-01/` before replacing
only `Disk_01.IMG`. Its readback matches the frozen bench-image SHA above.
All other original non-hidden USB files are unchanged; IMAGE_A.CFG still
selects Disk_01.IMG. Safe ejection succeeded. The deployment record is
`build/usb_backup/wavehw-2026-10-01/deployment.json`.

Next: insert the USB while the MPC is off, boot, check `WAVE BENCH 02`
and Play/Record. Load SINE441 through Disk / 7 / Load; open Program/Sounds
/ 6 / Help and photograph the waveform. If startup stops or displays
`Mod ROM mismatch`, photograph the complete LCD before proceeding.

## First physical WAVEHW display

**PROVEN (one user photograph, IMG_4803.JPG):** the custom full-view
waveform screen is reached for SINE441, showing start 000.000.00 and
end/length 001.250.00. Text, labels, a dense sine envelope, middle zero
line, and final rising ramp are visible. The approximate 40%/40%/20%
sections agree with the generated sound. This is qualitative agreement,
not a pixel-by-pixel LCD qualification. It establishes physical execution
of the feature after the capture-specific deployment; the boot marker
itself is not visible in this photograph.

Evidence is preserved in `notes/evidence/2026-10-01-wavehw-sine441.jpg`
and `notes/evidence/2026-10-01-wavehw-sine441-result.json`. Previous
pending-physical-display statements above describe the earlier checkpoint.
Fine zoom, edits, exits, stereo identity, audition and timing remain
**UNDETERMINED**. The next observation is Left to select Start, then
soft key 3 / Fine, so the sine region can be inspected at close range.

## Physical fine-view follow-up

**PROVEN (IMG_4805.JPG, one execution):** SINE441 fine view shows Start
selected at zero, Zoom 16, sine cycles right of center, and a flat left
half. The window formula `point + (column - 120) * zoom` places the left
half before sample zero, so this shape is expected. The right half spans
1,920 samples / 19.2 cycles of the period-100 test sine. This is qualitative
photographic agreement. Fine-view entry and Start selection are observed;
Up/Down zoom adjustment, edits, exit/reopen, stereo, audition and timing
remain **UNDETERMINED**. Evidence:
`notes/evidence/2026-10-01-wavehw-fine-result.json`.

## Physical start edit and exit

**PROVEN (IMG_4806.JPG and IMG_4807.JPG; user reports editing works):**
custom full view displays Start 000.000.16, and after returning to the
stock Edit Sound page, Soft st also displays 000.000.16. End and Length
remain 001.250.00. This observes the 16-frame start change and its RAM
persistence across exit for this sequence. Saving/reloading from disk,
other point edits, boundaries, stereo and audition are not established.
Evidence: `notes/evidence/2026-10-01-wavehw-edit-result.json`.
