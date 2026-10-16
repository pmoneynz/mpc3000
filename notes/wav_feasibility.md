# WAV load, save and record: feasibility for Vailixi 3.50

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-10-05.
**Mode:** XA=1. OS code under the second PGR (third under Route A, same
`CS:IP`); file = `((CS<<4)+IP) & 0x7FFFF`. DGROUP `8010:X` = file
`0x20000+X`. BIOS `F800:X` = file `0x78000+X`, EPROM, not patchable
([`../MODDING_HOWTO.md`](../MODDING_HOWTO.md) §4.2).

`[STATIC]`. Code reading only. Nothing here has run in MAME.

Decisions (Peter, 2026-10-05): ship combined with WAVE BENCH 07; reject
WAV files that are not 44.1 kHz.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Decide whether 2000XL-style WAV load / save / record can be added to 3.50 as a Route A floppy mod, and name what blocks it |
| Inputs | Linear image; 2kxl corpus (`/Users/peterwadams/Documents/2kxl`) as a behaviour reference only |
| Outputs | This note. No mod, no ledger change |
| Confidence | Instruction bytes and control flow cited below **PROVEN** (code). Host-OS behaviour and size estimates **HYPOTHESIS**. Anything needing a run is listed in §10 |
| Hardware deferred | PC/Mac-written floppy on a real MPC3000; MPC-written WAV on a host |

Reproduction: `build/wav_feas/v53dis.py CS IP END` (V53 bounds from
`tools/v53_decode.py`, mnemonics from Capstone; needs a Python with
`capstone`) and `build/wav_feas/be7e_reach.py` (§6). Both are scratch
files under `build/`.

---

## 1. Verdict

Feasible as a reimplementation, not a binary port. The 2000XL OS, sample
engine and sample header differ; its loader is a behaviour spec (§2).

| Capability | Result |
|------------|--------|
| Load 16-bit 44.1 kHz mono / stereo WAV | Feasible on stock allocation and streaming (§3.2) |
| Save a sound as WAV | Feasible on stock create / write / wave-RAM read (§3.3) |
| Record | The stock sampler fills memory; "record WAV" = sample, then save as WAV (§3.5). Direct-to-floppy recording is impossible (§8) |
| PC- or Mac-written files | Stock open fails in the EPROM BIOS (§4). The WAV code must open with a wildcard tail |
| Space, combined with WAVE BENCH 07 | Does not fit in the 1,580 bytes left in the cave. Needs §6 resolved first |

---

## 2. Reference: the 2000XL loader

From the 2kxl corpus (`notes/functions.md`, `notes/strings_catalog.md`),
2000XL addresses. Behaviour only; nothing here is reusable code.

- `wav_file_load_core` `0x45864`: `RIFF` at `0x458FE`, `WAVE` at
  `0x45912`; chunk dispatch `0x459A9`–`0x459F5` (`data`, `cue `, `fmt `,
  `smpl`, `fact`); unknown chunks skipped (`0x45ACA`).
- Rejects non-PCM (`0x45B3A`), not 16-bit (`0x45B4E`), more than two
  channels (`0x45B5C`). Messages: `Wrong .WAV file format`,
  `not PCM .WAV file`, `not 16bit .WAV file`, `Unknown .WAV file format`.
- Accepts any sample rate; stores it in the sample header (`+0x24`,
  `+0x38`). The 3.50 sound record has no rate field (§3.2).

---

## 3. Stock 3.50 machinery

### 3.1 Disk load path

| Item | Evidence | Status |
|------|----------|--------|
| Browser | `B509:0429` finds every file (pattern `?`×20, `CEE6:0175` / `01E1`), up to `0x200` entries of `0x17` bytes. `.WAV` files are already listed | **PROVEN** (code) |
| Type match | `B509:0295`. Table pointer loaded only at `B509:02DC` (file `0x3536C`): `8010:2186`, 12 far pointers (`SET SND SEQ ALL PAR ST1 ST2 PGM APS MID SMF MFF`), null at `8010:21B6`. No spare slot. Not-found result `-1` continues at `B509:032B` | **PROVEN** (code) |
| Unknown type | Browser reports error `-0x1E` (`B3C7:0007`) and stays in the browser | **PROVEN** (code) |
| Dispatch | `B509:00CD` on the browser result; codes `-10..-6` through `CS:0242`; other codes reach `B509:0208` (from `00DF`), which returns `SI` to the caller (`SI` = 0 re-enters the browser at `00B6`). `-2` (SND) calls `D7FA:000E` at file `0x351C8` | **PROVEN** (code) |

### 3.2 Memory and streaming

| Item | Evidence | Status |
|------|----------|--------|
| Allocate | `D0C0:0611(name, frames dword, stereo)` from the v2 loader `D7FA:03A5` | **PROVEN** (code) |
| Stream in | `D7FA:059B(handle, wave word addr dword, words dword)`, far-callable (`NOP / PUSH CS / CALL`). Reads up to `0x4800` bytes into `A2AE:0000` (`CF0C:0073`), writes `n/2` words to wave RAM (`CF92:000C`, dir 0). A mono 16-bit LE `data` chunk has the SND body layout and streams unchanged | **PROVEN** (code) |
| Stereo layout | `D7FA:0431–0444` doubles the word count when record `+13` = 1; one `D7FA:059B` call streams plane A then plane B. In wave RAM, B = `+20` + length words | **PROVEN** (code) |
| Rate | Record `A2AE:4800 + idx*0x24` has no rate field ([`waveform_phase0.md`](waveform_phase0.md) §1). Playback rate is fixed | **PROVEN** (record layout) |

WAV interleaves L/R. Stereo load therefore needs a de-interleave pass and
stereo save an interleave pass. Splitting the 18 KiB buffer as L (N words)
+ R (N words) + interleaved (2N words) gives N = `0x900` frames per pass.

### 3.3 Save path

`E905:0049(idx)` (file `0x69099`), wrapped by `E905:000C` (mute, call,
close on error, unmute):

1. Name via `CB10:1412(name, ".SND" 8010:7A2A, out)`.
2. `CEE6:0044` open succeeds → return `0xF800` (file exists).
3. `CEE6:0002` create, handle to `[FF9C]`.
4. `CF0C:0096` writes `01 02` and the `0x24`-byte record.
5. `E905:018D(handle, wave, words)` reads wave RAM (`CF92:000C`, dir 1) into
   `A2AE:0000` in `0x4800`-byte chunks and writes each.
6. Close. **PROVEN** (code).

A WAV saver is the same sequence with a 44-byte RIFF header in step 4 and an
interleave pass for stereo. UI precedent: Save a Sequence already has a
`Save as:` field (`8010:65A5`); Save a Sound (`8010:65E2`, page near
`CB10:03E0`) does not.

### 3.4 File API (`INT 41`)

`IVT[0x41]` = `F800:0364` ([`ivt_inventory.md`](ivt_inventory.md)). The
handler sets `ES` = caller `DS`, `DS = 0x0040`, `SI = AX`; `AX >= 0x10`
returns `F700`; then `CALL CS:[0x03D8 + 2*AX]` (`F800:03C9–03CF`) and
`RETF 2`. **PROVEN** (code).

| AX | Handler | OS wrapper |
|----|---------|------------|
| 1 create | `F800:0423` | `CEE6:0002` |
| 2 open | `F800:04A2` | `CEE6:0044` |
| 3 close | `F800:0505` | `CEE6:0086` |
| 4 read | `F800:05A7` | `CF0C:0073` |
| 5 write | `F800:07A1` | `CF0C:0096` |
| 9 find first | `F800:0A10` | `CEE6:0175` |
| 0A find next | `F800:0AC8` | `CEE6:01E1` |

The OS wrappers copy the name to `8010:FAB1` and `INT 41` at `CF0C:0038`.
`CEE6:0044` copies with `REPNE SCASB` / `REP MOVSW/MOVSB`: a NUL-terminated
copy. **PROVEN** (code).

### 3.5 Sampling

`Sample New Sound` (`8010:566D`) is pushed at file `0x46C3F`. The DSP path
is [`d22_sampling.md`](d22_sampling.md) `[PARTIAL]`. Adjacent strings
`MONO LFT` / `MONO RGT` / `STEREO` (`8010:5643–565C`) suggest the input
modes; their consumer is not traced. **HYPOTHESIS**.

---

## 4. BIOS directory names versus PC-written files

3.50 stores name characters 9–16 in directory-entry bytes `+0C..+13`.
FAT hosts store NT case flags, creation time / date and access date there.

### 4.1 Find record (`F800:0A10`, file `0x78A10`)

27 bytes: `+0` attribute, `+1` size dword, `+5` cluster count, `+7` name:

- entry `+0C` = 0: 8 name bytes + 3 extension bytes + NUL (short form);
- otherwise: 8 name bytes + entry `+0C..+13` raw + 3 extension bytes + NUL
  (long form).

**PROVEN** (code, `F800:0A7F–0AAF`).

### 4.2 Open (`F800:04A2`)

`F800:0E8A` handle, `F800:0E2F` name conversion, `F800:0FFF` search
(`F800:1325` with `AL=0`), `AH=FD` on a miss (`F800:04EC`).

`F800:0E2F` builds a 20-byte pattern from `ES:DX`: name `[0..8)`,
extension `[8..11)`, tail `[12..20)`. Input byte 11 = 0 → short form, tail
= 8 zero bytes. Otherwise input `[8..16)` is the tail (all spaces → zeros)
and `[16..19)` the extension.

Matcher `F800:1366–138E`: skips entries with attribute & `0x1E`
(`F800:1366`), then compares 11 bytes and, after the attribute byte, 8 tail
bytes against entry `+0C..+13`. Pattern byte `?` (`0x3F`) matches anything
in both loops (`F800:1371`, `F800:1384`). **PROVEN** (code).

### 4.3 Consequence

- A short-form name opens only an entry whose `+0C..+13` are all zero.
  A PC entry with `+0C` = 0 and non-zero timestamps returns `FD00`. This is
  the mechanism behind the mtools `FD00` trace recorded in
  [`../emu/snd.py`](../emu/snd.py) `disk()`. **PROVEN** (code; one trace).
- A long-form record whose timestamp tail contains a zero byte is cut
  short by the NUL-terminated copy in `CEE6:0044`; the BIOS then reads
  stale `8010:FAB1` bytes. **PROVEN** (code).
- This applies to every stock file type, not only WAV. How often host
  writers leave `+0C..+13` non-zero is **HYPOTHESIS** (VFAT creation and
  access stamps make it the normal case).

### 4.4 Wildcard open

Opening `name[0..8)` + `????????` + extension (19 bytes + NUL) makes
`F800:0E2F` take the long form (input byte 11 = `?`) with tail `????????`,
which matches any `+0C..+13`. **PROVEN** (code path). Not yet run.

The first entry with the same 8.3 name and extension wins. With 8.3 names
for saved WAVs (§4.5), the only collision is an MPC 16-character name whose
first 8 characters and extension match.

### 4.5 Long names, create, save naming

- VFAT long-name entries (attribute `0x0F`) fail `F800:1366`. Only the
  8.3 alias (`MYKICK~1.WAV`) is visible. **PROVEN** (code). Reading long
  names would need raw directory sectors (`INT 40`); not assessed.
- Create (`F800:0423`) searches with an exact pattern (`F800:104E`). On a
  match it marks the entry `E5` and frees its FAT12 chain
  (`F800:1062–10A5`). It then zeroes the attribute and entry bytes
  `+14..+1F` (time, date, cluster, size; `F800:0437–0447`) and takes a
  free slot (`F800:1028`). **PROVEN** (code).
- So an overwrite / exists check with the exact name misses a PC-written
  file of the same 8.3 name, and create adds a second entry with that
  name. The WAV saver's exists check must use the wildcard tail.
- Saving WAVs with 8-character names keeps `+0C..+13` zero. A
  16-character name puts MPC characters in the host's case-flag and
  timestamp bytes; effect on hosts **HYPOTHESIS** (cosmetic).

---

## 5. Format policy

| Input | v1 policy | Note |
|-------|-----------|------|
| 16-bit PCM, 1–2 ch, 44,100 Hz | Load | 2000XL parity |
| Other rates | Reject with a message | Decided. Record has no rate field and 3.50 has no converter |
| 8-bit, 24-bit PCM | Open decision | 2000XL rejects both. Conversion loops are small |
| `WAVE_FORMAT_EXTENSIBLE` (`0xFFFE`), PCM subformat | Open decision | 2000XL rejects (non-PCM). Common from DAWs for 24-bit |
| Float, compressed, more than 2 ch | Reject | 2000XL parity |
| `smpl` loops, `cue ` | Ignore | Record has start / end only (`+14`, `+18`) |
| `fmt ` after `data` | Re-open and re-read | No seek wrapper is established; read-and-discard plus re-open covers it |

Odd chunk sizes carry a pad byte. The rate policy means record `+12` (tune,
units **UNDETERMINED**) is never written by the WAV loader. The S1000
importer scales its tune by 10/256 and clamps to ±120
(`BE7E:0AE5–0B36`); that is evidence for 0.1-semitone units, not proof.

---

## 6. Space for the combined build

The cave `F07D:0000` (file `[0x707D0, 0x74000)`) holds 14,384 bytes. WAVE
BENCH 07 uses 12,804 ([`../STATUS.md`](../STATUS.md)), leaving 1,580.
Estimated WAV code: 2–3.5 KB (**HYPOTHESIS**; parser and chunk walk,
mono / stereo load, header writer, interleave, wildcard naming, two UI
hooks, messages). It does not fit.

[`patch_space.md`](patch_space.md) lists no other RAM-mapped free range.
The other options:

**A. Retire the S1000/S3000 importer (`BE7E`).** It reads Akai-format
volumes (`Select Volume`, `8010:3F8E`), not FAT files.

- Span: file `[0x3E7E9, 0x3FB38)`, 4,943 bytes. It starts after `BE1A`'s
  jump table ending at `0x3E7E9` (owner ledger) and ends at `BFB3:0008`
  (file `0x3FB38`).
- Reach: the near-call closure from `BE7E:0F9F`, through the 6-entry switch
  at `BE7E:11FC` (`CS:134C`, `BX <= 5`), covers every byte of the span
  (`be7e_reach.py`). **PROVEN** (code).
- Entry: the only direct far transfer into the span from outside is
  `CALLF BE7E:0F9F` at `B509:0211` (file `0x352A1`), the Disk-mode menu
  option. Other byte matches decode as `F7 EA` (`IMUL DX`). No DGROUP value
  that resolves into the span is a function entry. **PROVEN** for direct
  transfers and stored pointers. Runtime-built pointers **UNDETERMINED**.
- Cost: the S1000/S3000 import is lost. `B509:0211` must be repointed.
  The builder needs a second code origin (paragraph-aligned
  `BE7F:0000` = file `0x3E7F0`, 4,936 bytes) that checks stock bytes
  instead of `FF` filler.
- Combined room: 1,580 + 4,936 = 6,516 bytes.

**B. Shrink WAVE BENCH 07** by 0.5–2 KB. Unmeasured.

**C. Cut WAV scope** to fit 1,580 bytes. **HYPOTHESIS**: not enough for
load and save with stereo.

Before A, run a fetch watch on `[0x3E7E9, 0x3FB38)` (as
`emu/lua/cave_watch.lua` does for the cave) through the WAVE suites and
Disk pages.

---

## 7. Hook sites

| Site | File | Stock bytes | Use |
|------|------|-------------|-----|
| `B509:00C1` | `0x35151` | `90 0E E8 63 03` (`NOP / PUSH CS / CALL 0429`) | Same-length `CALLF` to a wrapper that calls the browser and handles a WAV result |
| `B509:032B` | `0x353BB` | matcher not-found path | Recognise `WAV` without a table slot |
| Save a Sound page | near `CB10:03E0` | — | `Save as:` field, or a separate entry. Not designed |
| `B509:0211` | `0x352A1` | `9A 9F 0F 7E BE` | Only if §6 option A |

The `WAV` string and messages can live in the code region: the type table
holds far pointers (`LES DI,[BX]` at `B509:02F2`). Only a table, if one is
kept, must be `DS`-relative.

---

## 8. Limits

- 1.44 MB FAT12 holds 1,457,664 data bytes: 16.5 s mono, 8.3 s stereo at
  16-bit 44.1 kHz. The `{1}` / `{2}` split (`D7FA:09E3`, `E905:023C`) does
  not apply to WAV.
- 44.1 kHz 16-bit mono needs 88,200 B/s; an HD floppy's raw MFM rate is
  62,500 B/s. Direct-to-floppy recording is impossible. The 2000XL also
  samples to RAM.
- SCSI / Zip: the FAT walks read here test 12-bit end of chain
  (`AND BX,0FF8`, `F800:0A6B`, `F800:1097`). Whether PC-formatted SCSI
  media work is **UNDETERMINED**.

---

## 9. Plan

1. Mono 16-bit 44.1 kHz load with the wildcard open. Emulator image from
   `emu.mpc3k.disk` (mtools timestamps kept, not `emu.snd.disk`). Compare
   wave RAM to the file PCM with `snddump`.
2. Stereo load; WAV save (mono, stereo) and exists check. Extract with
   mtools; compare with Python `wave` against wave RAM. SND → WAV → load
   round trip.
3. Rejections and errors: rates, non-PCM, 8 / 24-bit, more than 2 ch,
   truncated `data`, odd chunk sizes, `LIST` before `fmt `, `data` before
   `fmt `, out of memory, disk full, existing name.
4. Space (§6) before integration; WAVE BENCH 07 suites and cave / `BE7E`
   watches with skips forbidden.
5. Physical, deferred: Windows- and macOS-written floppies on the MPC3000;
   MPC-written WAVs on Windows and macOS.

---

## 10. Open

| Item | Status |
|------|--------|
| Wildcard open on a timestamped image | **UNDETERMINED** until §9 step 1 runs |
| Host writers leaving `+0C..+13` non-zero | **HYPOTHESIS** |
| Host reaction to MPC bytes in `+0C..+13` | **HYPOTHESIS** |
| Runtime-built pointers into `BE7E` | **UNDETERMINED** |
| WAV code size | **HYPOTHESIS** (2–3.5 KB) |
| Tune units | **UNDETERMINED** (not needed under the reject policy) |
| Sampler input modes | **HYPOTHESIS** |
| PC-formatted SCSI media | **UNDETERMINED** |
| Save a Sound UI patch | Not designed |
