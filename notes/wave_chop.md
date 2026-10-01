# Multi-zone Sound creation

**Target:** Vailixi OS 3.50 linear image
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Implementation:** `mods/wave_chop.inc`.
**Date:** 2026-10-01.

The WAVE extension appends `CHOP ZONE` to the stock Edit Sound `Do:`
choice.  It creates one new Sound for each shared-boundary interval
`[B[i],B[i+1])`, keeps the source Sound selected and unchanged, and does not
use or delete `TEMPORARY999`.

Address forms below distinguish the stock linear image from the Route A RAM
execution used by the mod.  File offset is the interleaved LS/MS image offset.
The CPU runs with `XA=1`.  Under the stock second PGR, an application address
has the shown `0x0.....` 24-bit home; after the loader selects the third PGR,
the same logical address executes from the Route A `0x3.....` RAM copy.

## Hook surfaces

| Purpose | Linear file | `CS:IP` | 20-bit | 24-bit Route A, third PGR | Status |
|---|---:|---:|---:|---:|---|
| rebuild `Do:` choice | `[0x39E0D,0x39E2F)` | `B99A:046D` | `0xB9E0D` | `0x3B9E0D` | **PROVEN** whole-instruction span |
| dispatch choice 10 | `[0x3A49F,0x3A4AD)` | `B99A:0AFF` | `0xBA49F` | `0x3BA49F` | **PROVEN** whole-instruction span |
| invalidate on Sound delete | `[0x51719,0x5171F)` | `D0C0:0B19` | `0xD1719` | `0x3D1719` | **PROVEN** replaced prologue |
| cave start | `0x707D0` | `F07D:0000` | `0xF07D0` | `0x3F07D0` | **PROVEN** Route A mapping |

The generic field bytes are
`803eb5ed0a7c05c606b5ed006a101e68a2351e68b5ed1e6881379ac60154b383c40e`.
The captured 2026-10-01 profile differs only at the personalized DGROUP
operands: `EDB5/35A2/3781` become `EDB3/35A0/377F`.  The dispatch bytes are
`a0b5ed988bd883fb097603e9880a`, or `a0b3ed...` in that capture.  Delete's
six-byte prologue is `558bec83ec06` in both.  **PROVEN.**

The choice-field ABI is `B354:01C6(label far, selection far, directory far,
width)` with the caller pushing `16, directory segment/offset, selection
segment/offset, label segment/offset` and dropping 14 bytes.  The new
directory contains the ten stock far string pointers, one cave pointer to
`CHOP ZONE`, then a null dword.  Generic selection is `8010:EDB5` (20-bit
`0x8EEB5`, Route A 24-bit `0x38EEB5`); the physical-capture profile uses
`8010:EDB3`.  **PROVEN** from `B99A:046D` and `B354:01C6`.

The dispatch hook reconstructs `BX=index` and rejoins `B99A:0B0D` for stock
values 0 through 9.  It clears the zone-map lifetime before those stock Do
operations.  Value 10 runs the backend.  Other values leave through
`B99A:1595`.  **PROVEN** control-flow shape; choice 10 executes in both generic and
capture-profile MAME tests.

## Stock machinery used by the backend

| Routine | File / logical entry | Stock second-PGR / Route A 24-bit | Established contract |
|---|---|---|---|
| unique zone name | `0x4835D`, `C6C2:173D`, 20-bit `0xC835D` | `0x0C835D` / `0x3C835D` | writes collision-free padded `ZONE%03d` for mode 1 |
| allocate Sound | `0x51211`, `D0C0:0611`, `0xD1211` | `0x0D1211` / `0x3D1211` | name far, length dword, stereo; returns index or `-1/-2/-3` |
| count free records | `0x5144D`, `D0C0:084D`, `0xD144D` | `0x0D144D` / `0x3D144D` | returns count in `AX` |
| count free wave words | `0x50E36`, `D0C0:0236`, `0xD0E36` | `0x0D0E36` / `0x3D0E36` | returns `DX:AX` |
| copy wave words | `0x51A50`, `D0C0:0E50`, `0xD1A50` | `0x0D1A50` / `0x3D1A50` | source, destination and count dwords; no error result |
| free Sound | `0x51719`, `D0C0:0B19`, `0xD1719` | `0x0D1719` / `0x3D1719` | index, mode, flag; mode 0 frees allocator owner entries |
| rebuild allocation state | `0x5146F`, `D0C0:086F`, `0xD146F` | `0x0D146F` / `0x3D146F` | rebuilds allocator extents from record base/length/stereo |
| rebuild Edit Sound list | `0x3C192`, `B99A:27F2`, `0xBC192` | `0x0BC192` / `0x3BC192` | fills page index/pointer arrays, returns count |
| redraw Edit Sound fields | `0x3B05B`, `B99A:16BB`, `0xBB05B` | `0x0BB05B` / `0x3BB05B` | redraws the 17 stock fields |

`D0C0:0611` allocates the caller's exact requested word count at
`D0C0:0691..06B3`, including the stereo doubling.  Only later, at
`D0C0:076A..0793`, it clamps record `+1C` to at least 441 frames.  The
allocator extent therefore remains exact even when the descriptor says 441.
`D0C0:0B19` frees by the allocation table's owner byte and allocation
boundaries; it does not derive the initial freed extent from record `+1C`.
Its final `D0C0:086F` call rebuilds survivor allocation entries from record
`+20` and `(stereo+1)*length` at `D0C0:08DD..093A`.  Edit Sound entry
`B99A:0024` also calls `086F`.  **PROVEN.**

The version-2 SND loader calls the same allocator at `D7FA:0408` (file
`0x583A8`, 20-bit `0xD83A8`, stock/Route-A 24-bit
`0x0D83A8`/`0x3D83A8`).  It copies the file's actual word count through
`D7FA:059B`, and later writes file start at `D7FA:056B` and file end at
`D7FA:0580`; it does not put the original sub-441 length back into record
`+1C`.  A one-frame file with file end zero therefore reserves one word but
leaves `length=441,end=0`.  **PROVEN** by the instruction stream.  Existing
EDGE traces do not prove a one-frame record because their Lua probe replaces
the cave `len` after entry.

The SND saver at `E905:0049` (file `0x69099`, 20-bit `0xE9099`, Route A
24-bit `0x3E9099`) reads descriptor `+1C` at `E905:011A/013E` and transfers
that exact mono/stereo word count at `E905:018D`.  A corrected one-frame
Sound can therefore be saved, but loading that file recreates the
`allocated=1,length=441` mismatch above.  **PROVEN.**

The backend consequently rejects every interval shorter than 441 frames
(10 ms at 44.1 kHz) before allocation and displays
`ZONE MUST BE AT LEAST 10ms`.  This preserves exact boundaries for every
created Sound without adding a separate SND-loader compatibility patch.
The minimum is an implementation constraint justified by the stock loader,
not a claim that `D0C0:0611` allocates 441 words.  **PROVEN** in source
and the `tiny` MAME case, which creates no new Sound.

## Backend contract

`chop_create_all` keeps the suspended `B99A` page frame in `BP`.  It first
resolves the live selected Sound through `SS:[BP-0xBC + [BP-2]]`; the cached
`sound_index` alone is insufficient.  It requires:

- `zones_valid=1`, count `1..16`, and current `1..count`;
- live index equal to `zones_source`;
- source name, stereo, length and wave base equal to `zones_identity`;
- stereo exactly 0 or 1;
- after importing the active stock start/end pair, unsigned boundaries
  `0 <= B[0] < ... < B[N] <= source length`, with every delta at least 441.

The outer boundaries are deliberately editable.  The chopped domain is
`[B[0],B[N]]`, not necessarily the whole Sound.  A zero or reversed interval
is rejected before mutation with `EMPTY ZONE - ADJUST BOUNDARIES`; stale
identity or out-of-range state uses `REOPEN WAVE VIEW FOR THIS SOUND`.
**PROVEN** in source and the `empty`, `stale`, and `stale_selection`
MAME cases.

Preflight requires at least `N` empty records and
`(B[N]-B[0]) * (stereo+1)` free wave words.  This equals the sum of the exact
strictly-positive interval allocations.  For each zone it:

1. asks `C6C2:173D` for a collision-free `ZONE%03d` name;
2. allocates through `D0C0:0611` without calling `B99A:1728`;
3. copies source volume/tune (`+11/+12`), exact length and end;
4. re-reads the source base after allocation, because allocator compaction
   may have moved it;
5. copies plane A, then plane B for stereo, through `D0C0:0E50`.

If allocation returns a negative result, created records are deleted in
reverse order with `D0C0:0B19(index,0,1)`.  After success or rollback the
backend refreshes the source wave base in `zones_identity` and the waveform
cache so allocator compaction does not reset valid cuts on the next entry.
It then rebuilds the page list, scans the new list for the live index captured
before dispatch (including a rejected stale-map request), writes
the new position to `[BP-2]`, and redraws.  This prevents lower-numbered free
slots filled by the batch from changing the selected Sound.  **PROVEN** in
source and the repeated-chop/source-selection MAME cases.

The operation is transactional for preflight and allocator errors.
`D0C0:0E50` and its `CF92` transfer have no error result, so wave-hardware
failure cannot be rolled back from software evidence.  That is an
**UNDETERMINED** hardware boundary; no all-failures atomicity claim is made.

## Current validation

- Both generic and `WAVE_CAPTURE_20261001` profiles assemble with NASM.
- The assembled cave is below the `[0x707D0,0x74000)` bound and contains no
  `0F E0` or `0F F0` byte pair.
- `python3 tools/verify_boot_slice.py` passes its 171 baseline checks.
- MAME cases exercise mono/stereo four-way chopping, partial outer boundaries,
  duplicate-name avoidance, empty/short/stale refusals, and retained source
  selection after names sort ahead of it. Result PCM is compared byte for
  byte against both source planes; volume/tune, length, end and nonoverlapping
  extents are checked. Source PCM and descriptor remain unchanged.
- Real repeated chopping fills the directory to 113 records, then refuses a
  further 16 without mutation. A real 540,000-frame load exhausts the memory
  needed for its chop; preflight refuses without creating records.
- A stereo result is saved through stock Disk, then loaded after a cold
  emulator restart and compared for exact metadata and both PCM planes.
- **PROVEN for the recorded executions:** see `emu/test_wave_chop.py`,
  `emu/test_wave_chop_generic.py`, `emu/test_wave_chop_save.py` and the final
  hash-pinned `build/mods/WAVEHW-validation.json` release record.
- **UNDETERMINED:** rollback after a late allocator failure is source-reviewed
  but has no execution trace; physical panel/audio/wave-memory behavior still
  needs hardware observation. Preflight refusal is not a rollback test.

Stock-key test path: from Edit Sound field 0, Right sixteen times reaches
`Do:`; `+` ten times selects `CHOP ZONE`; normalized Soft Key 4 / Do is `u`
(`0x75`).
