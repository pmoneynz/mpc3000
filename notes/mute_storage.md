# MUTE GROUPS program state and persistence

**Target:** Vailixi 3.50 linear image
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`;
captured application ROM
`build/hardware/2026-10-01-romapp/ROMAPP.BIN` (linear `+0x20000`).
**Date:** 2026-10-01.

This note answers whether the MUTE GROUPS state can safely occupy the stock
program record and gives a lifecycle ABI for the mod.  It does not assign
meaning to bytes merely because they look constant.

## Result

**PROVEN:** the stock program arena has no tail outside its 24 records.  Each
record is exactly `0x077E` bytes and the arena is exactly `0xB3D0 =
24*0x077E` bytes.  The pad-to-note table occupies the final 64 bytes,
record `+0x073E..+0x077D`.  PGM and APS paths read and write all `0x077E`
record bytes.  There is therefore no evidence-backed reserved record field
large enough for MUTE GROUPS.

**PROVEN (implementation and emulator execution):** the mod keeps a 24-slot
table in the relocated code cave and appends a signature-checked extension to
PGM and APS files immediately before
the stock close.  Stock Vailixi ignores the trailing extension because its
loaders close immediately after their fixed-size reads.  The mod defaults to
disabled/all-Off when the extension is absent, malformed, or short.

## Address frame

All stock code below runs with XA=1.  Under the second PGR, the app-ROM pages
are identity mapped, so their 24-bit physical address is the 20-bit address
with a leading zero.  After the `.SYS` hand-off installs the third PGR, the
same logical app addresses execute from RAM at `0x3xxxxx`.  Thus, for example,
linear `0x4A262` is `C887:19F2`, logical 20-bit `0xCA262`, stock physical
`0x0CA262`, and mod physical `0x3CA262`.  The program pool is below `0xB0000`;
both PGRs map it to RAM, so `9770:0004` is physical `0x397704` while XA=1.

For the captured ROM, `ROMAPP.BIN` offset is `linear - 0x20000`.  Every hook
window in this note is byte-identical in generic Vailixi and the capture.

## Stock record extent

`DA04:000E`, linear `0x5A04E`, logical/stock physical
`0xDA04E`/`0x0DA04E`, stores its argument at `9770:[0000]`, then stores
`floor(0xB3D0 / argument)` at `9770:[0002]`.  Its sole call at linear
`0x4F5A7` is preceded by `PUSH 0x077E`.  Therefore:

- `9770:0000 = 0x077E` record stride;
- `9770:0002 = 0x0018` record count;
- record `i` is `9770:(0004 + i*077E)`, `0 <= i < 24`;
- the exclusive arena end is `9770:B3D4`.

`DA04:002B`, linear `0x5A06B`, returns that pointer for an index below the
count.  `CA45:0008`, linear `0x4A458`, installs it in `[E5F9]:[E5FB]` and
stores the index in `[E60E]`.  In the captured profile these DGROUP objects
are shifted by two bytes: `[E5F7]:[E5F9]` and `[E60C]`.

`D9F2:000C`/`0072` read/write the 64-byte pad-slot-to-note table at selected
record `+0x073E`.  Since `0x073E + 0x40 = 0x077E`, that table reaches the
record's exclusive end.  This also establishes that a MUTE GROUP assignment
indexed by pad slot remains attached to pads when the note bytes are remapped;
the mute table itself requires no rewrite on a pad-to-note edit.

## Stock PGM and APS persistence

The following instructions are **PROVEN**.  `CF0C:0073` is the fixed-size
read wrapper, `CF0C:0096` is the fixed-size write wrapper, and `CEE6:0086`
closes the handle.

| Operation | Record transfer | Immediate close suitable for extension hook |
|---|---|---|
| PGM load | `C20F:0360` linear `0x42450` pushes `0x077E`; call at `036E`, linear `0x4245E` | call at `C20F:0412`, linear `0x42502`, bytes `9A 86 00 E6 CE` |
| APS load | loop at `C20F:0767`, linear `0x42857`, pushes `0x077E`; call at `0775`, linear `0x42865` | call at `C20F:07CC`, linear `0x428BC`, same bytes |
| PGM save | `E7F5:09C4`, linear `0x68914`, pushes `0x077E`; call at `09D2`, linear `0x68922` | call at `E7F5:09FE`, linear `0x6894E`, same bytes |
| APS save | loop at `E7F5:0DD7`, linear `0x68D27`, pushes `0x077E`; call at `0DE5`, linear `0x68D35` | call at `E7F5:0E5E`, linear `0x68DAE`, same bytes |

For these rows, the logical/stock/mod physical forms of the close hooks are:

| Linear | `CS:IP` | 20-bit | stock 24-bit | mod 24-bit | capture offset |
|---|---|---:|---:|---:|---:|
| `0x42502` | `C20F:0412` | `0xC2502` | `0x0C2502` | `0x3C2502` | `0x22502` |
| `0x428BC` | `C20F:07CC` | `0xC28BC` | `0x0C28BC` | `0x3C28BC` | `0x228BC` |
| `0x6894E` | `E7F5:09FE` | `0xE894E` | `0x0E894E` | `0x3E894E` | `0x4894E` |
| `0x68DAE` | `E7F5:0E5E` | `0xE8DAE` | `0x0E8DAE` | `0x3E8DAE` | `0x48DAE` |

Replacing each 5-byte close `CALLF` with a 5-byte far call to a mod wrapper
preserves the caller's cdecl frame.  The load wrappers consume an optional
extension, ignore extension errors, then return the real close result.  The
save wrappers write the extension, always close, and return the first write
error or the close result.  This keeps the stock error branches live.

The genuine stock file `emu/fixtures/mute-native-blank.PGM` establishes the
complete fixed PGM extent and agrees with the static read sequence.  It was
saved as `PROGRAM_01.PGM` through the unmodified Disk / 4 / Do it path while
running the BENCH05 payload, then extracted without changing its 4,608 bytes;
its SHA-256 is
`92fb1c621c10db67788da83b4f2dfc7d97919b16d1f2472886f871495023e733`.

| File range | Size | Consumer |
|---|---:|---|
| `0000..0001` | `2` | type/version bytes `07 00` |
| `0002..0881` | `0x880` | 128 records of 17-byte sound names |
| `0882..0A81` | `0x200` | 128 little-endian 32-bit sound metadata values |
| `0A82..11FF` | `0x077E` | one stock program record |

Thus stock PGM EOF is exactly `0x1200`.  In the loaded program record, each
24-byte note record's byte `+0x3E` is initially an index into the 128-entry
name directory.  The post-close loop at `C20F:0478`, linear `0x42568`, calls
`D0C0:0D17` on that name and replaces the byte with the live sound-directory
index, or `FF` when the sound is missing.  A PGM therefore binds sounds by the
17-byte name directory and stored source indices; the 32-bit table is
additional per-sound metadata, not the binding key.

**PROVEN:** the close hooks are success-only commit points.  The PGM close at
`C20F:0412` is reached only after the header, both directory tables, and the
full program record were read successfully.  The APS close at `C20F:07CC` is
reached only after its header, declared program-record count, and sound-name
table were read successfully.  Every fixed-read error returns before these
hooks and therefore cannot cause a trailer to be inspected or committed.

## Mod-owned state ABI

**PROVEN (implementation and emulator execution):** each program uses a packed
33-byte state record.  Public accessors hide the nibble layout from the UI and
playback paths.

```
state +00  enabled       0=Off, 1=On
state +01  pad 0 low nibble, pad 1 high nibble
...
state +20  pad 62 low nibble, pad 63 high nibble
```

Each nibble is `0=Off`, `1..4=Group 1..4`; values `5..15` are invalid.  There
are 24 records (`0x0318` bytes total) in program-index order.  All-zero
is the backward-compatible default.  Disabling MUTE GROUPS retains the pad
assignments.  Apply All writes the selected value to `+01..+20` and does not
change `enabled`.

The table belongs in the payload assembled at `F07D:0000` (linear cave
`[0x707D0,0x74000)`).  After the range checks below, the combined WAVE/MUTE
payload assembled on 2026-10-01 uses 12,026 of 14,384 cave bytes (both
profiles), leaving 2,358; the previous candidate used 12,042.  It contains a
792-byte live table and a 792-byte transactional staging table.  Exact label offsets must
always come from the current assembler map.  Under the third PGR they are
writable RAM at physical
`0x3F07D0 + label_offset`.

## File extension ABI

**PROVEN (implementation and emulator execution):** the mod appends this
little-endian chunk without changing the stock file header or record bytes:

```
+00 char magic[8] = "MUTEGP35"
+08 u8   kind       1=PGM, 2=APS
+09 u8   version    1
+0A u16  header_len 0x0010
+0C u16  state_len  0x0021
+0E u16  count      1 for PGM, stock APS program count N (0..24)
+10 state[count]
```

The PGM chunk is 49 bytes and holds the disk operation's chosen program.  The
APS chunk is `16 + 33*N` bytes (808 bytes at `N=24`) and holds slots
`0..N-1` in index order.  Matching the APS trailer count to the stock record
count prevents state for programs absent from the APS from being revived.  A
loader accepts the chunk only if every header field matches, `enabled <= 1`,
and both nibbles of every group byte are `<= 4`; otherwise it leaves the
affected state cleared.  Unknown versions are ignored.  This is a mod ABI,
not a claim about a stock reserved format.

`C20F:0003` receives the one-based PGM load destination at `[BP+0A]` and
selects `[BP+0A]-1` at `C20F:01B5`.  `E7F5:079D` receives the one-based PGM
save source at `[BP+06]` and selects it at `E7F5:07B0`.  The wrappers follow
their saved caller BP and use those stable arguments rather than the mutable
selected-program byte.  This remains correct when Disk saves a program other
than the one active before the operation and if an interrupt changes selection
during I/O.  APS load/save similarly obtain `N` from the stable byte
`[caller BP-3]` used by the stock record loops.

The loader clears live state before optional trailer input, reads into a
separate staging table, validates the complete payload, and commits only after
all records pass.  A PGM post-close resolution failure calls `CF55:02CD` for
the chosen destination.  An APS post-close resolution failure calls
`CF55:0125`; its `CF55:01BF..01D4` loop calls `CF55:02CD` for all 24 programs.
Because `CF55:02CD` aliases the hooked initializer, both cleanup paths clear
any state that had just been committed.

The stock PGM/APS loaders do not test EOF after their fixed record reads;
they close.  Therefore a stock 3.50 loader ignores this appended chunk.
Conversely, EOF at the optional read is the expected legacy-file case in the
mod.  A physical save/load round trip is still a deferred observation.

## Stock ALL scope

**PROVEN:** Disk option 2, whose title is `Save All Sequences & Songs`, writes
a dedicated `.ALL` sequence/song container.  It does not call either program
writer and does not serialize a program record.  The six-way option table at
`CB10:1178`, linear `0x4C278`, sends option 2 to `CB10:0338`, linear
`0x4B438`.  The corresponding six-way save table at `CB10:114E`, linear
`0x4C24E`, sends option 2 to `CB10:1072`; its call at `CB10:1083`, linear
`0x4C183`, enters the ALL writer as `E83C:000E`, the same bytes as
`E7F5:047E`, linear `0x683CE`.  Options 4 and 5 instead call the PGM writer at
`CB10:10C4`, linear `0x4C1C4` (`E86E:000D` = `E7F5:079D`), and the APS writer
at `CB10:10DA`, linear `0x4C1DA` (`E86E:0417` = `E7F5:0BA7`).

The complete ALL writer is `E7F5:047E..06B2`, linear
`[0x683CE,0x68603)`.  It writes the `04 03` word at `04DD`, a four-byte length
at `0506`, and the far-pointer-bounded sequencer buffer through
`CF17:000A` at `0542`.  It then walks exactly 20 entries assembled from the
arrays at `A820`, `A7BC`, and `A99C`, writes each nonempty entry at `0654`,
writes a one-byte zero terminator at `0692`, and closes at `06A7`.  The
streaming helper `CF17:000A` uses only the far pointer and 32-bit count passed
by this writer.  Across the bounded writer there is no reference to selected
program state `[E5F9]:[E5FB]` or `[E60E]`, no `0x077E` program-record
transfer, and no call to the PGM or APS writer.  Every exit was checked; the
body contains no `BRKXA` or `RETXA` byte sequence.  The exact subfield
meanings within `A820`, `A7BC`, and `A99C` are **UNDETERMINED**; that does not
affect the proven absence of a program-record source.

These addresses run with XA=1.  Under the second PGR their 24-bit physical
addresses are the identity forms: the option-2 save call is logical
`0xCC183` / physical `0x0CC183`, and the ALL writer entry is logical
`0xE83CE` / physical `0x0E83CE`.  Under the third PGR used by the mod, the
same logical code executes from physical `0x3CC183` and `0x3E83CE`.
Consequently the PGM/APS extension hooks intentionally do not affect `.ALL`;
MUTE GROUPS program state persists through `.PGM` and `.APS`, while `.ALL`
remains sequence/song-only.

## New, initialize, copy, and selection identities

`CF37:04AD`, linear `0x4F81D`, initializes one record and receives the
zero-based program index at `[BP+6]`.  `CF37:0305` loops over all 24 indices
and near-calls it.  `CF55:02CD` is an alias of the same `CF37:04AD` bytes and
is called by the `Initialize program:` path (linear call `0x4A3B7`) and by
load-error cleanup.  Hooking the shared entry therefore gives one exact
default rule for boot/global initialization, one-program initialization, and
failed-load cleanup.

| Linear | `CS:IP` | 20-bit | stock/mod 24-bit | bytes | replacement |
|---|---|---:|---|---|---|
| `0x4F81D` | `CF37:04AD` | `0xCF81D` | `0x0CF81D` / `0x3CF81D` | `55 8B EC 83 EC 04` | `JMPF init_hook; NOP` |

The hook recreates `PUSH BP / MOV BP,SP / SUB SP,4`, invalidates voice tags,
clears state `[BP+6]`, restores the original register/flag surface, then
far-jumps to `CF37:04B3`.  The capture offset is `0x2F81D` and the six bytes
are identical.

The `Copy 1 Program to Another` action performs the only image-wide full
record copy.  At `C887:19F2`, linear `0x4A262`, it executes:

```
B9 BF 03       MOV CX,03BF       ; 0x077E / 2
1E             PUSH DS
8E D8          MOV DS,AX         ; source segment
F3 A5          REP MOVSW         ; source SI -> destination ES:DI
1F             POP DS
```

At this point source program is `[BP-1]-1` and destination is `[BP-2]-1`.
Replace these nine bytes with `JMPF copy_hook` plus four NOPs; the hook
executes the original record copy, range-checks both indices, invalidates
destination voice tags, copies 33 mod bytes from source to
destination, and far-jumps to `C887:19FB`.  Flags and AX/BX/DX/SI/DI are
restored; CX leaves as 0, as after the stock `REP MOVSW`.  Address forms are linear
`0x4A262`, logical `0xCA262`, stock/mod physical
`0x0CA262`/`0x3CA262`, capture offset `0x2A262`.  The nine bytes are
identical in both profiles.

The selected-program identity is `[E60E]` in generic Vailixi and `[E60C]`
in the capture.  The selected record pointer is `[E5F9]:[E5FB]` generic and
`[E5F7]:[E5F9]` captured.  Storage should index the mod table by the program
number, not by the far pointer, because the pointer is selection state and
changes during APS loops.

Pad-to-note remapping needs no storage migration: `D9F2:000C` maps slot to
note from record `+073E`, and `D9F2:003D` searches that table from slot 0
upward to map note to slot.  A runtime path that only has a note should use
that accessor rather than assuming `note-0x23`; duplicate note assignments
resolve to the first slot by the proven loop.  Whether a panel event retains
a distinct physical-pad identity remains the named hardware boundary
`U-PANEL-ROM` / `U-TE7774`.

## Index bounds and range checks

`mute_state_bx` does not validate its argument.  The three hooks that take a
one-based program number from a stock frame now test `number-1 < 24`
(unsigned, so 0 is rejected) before any mod-state work:

| Hook | Index | Out-of-range action |
|---|---|---|
| `mute_program_copy_hook` (`C887:19F2`) | source `[BP-1]-1`, destination `[BP-2]-1` (bytes) | stock copy already done; skip voice-tag forget and the 33-byte copy |
| `mute_pgm_load_close` (`C20F:0412`) | `[caller BP+0Ah]-1` (byte, as `C20F` uses it) | `mute_close_only`: stock `CEE6:0086` close, return its AX/DX; no forget, clear, trailer read or commit |
| `mute_pgm_save_close` (`E7F5:09FE`) | `[caller BP+06h]-1` (word, as `E7F5:07B0` uses it) | `mute_close_only`; no trailer is written, so the file is the stock `0x1200` bytes |

The APS wrappers were already bounded: they clamp the stock count byte
`[caller BP-3]` to `<= 24` and loop over `0..count-1`.

**PROVEN (code, all stock callers):** an out-of-range value is not reachable
from stock Vailixi 3.50; the checks are defensive.  Generic addresses, XA=1;
20-bit = stock 24-bit (second PGR, identity), mod 24-bit = `0x300000 | 20-bit`
(third PGR):

- *Copy.* `[BP-1]` and `[BP-2]` are stack locals of the `C887` copy screen.
  Their only direct writers are `C887:17A7` / `C887:1827` (linear
  `0x4A017` / `0x4A097`), which store `[E60E]+1`.  Each is then registered at
  `C887:17BB` / `183B` through `B354:03B1(label, &slot, 2, 1, 0x18, 8)`
  (linear `0x338F1`, 20-bit `0xB38F1`), which builds a type-0 numeric field
  at `B354:02BB` with min `+9` = 1, max `+B` = 24, flags `+D` = 8 (byte), no
  callback.  `B060:021C` (linear `0x3081C`) loads the field pointer into
  `[7D41]` and its type into `[7D78]`.  For type 0, the commit path
  `B060:0715` (linear `0x30D15`) and the key handler `B31B:0007` write only
  through `B31B:0214` (linear `0x333C4`), which clamps signed to `[min,max]`
  and stores a byte at `B31B:033B` (flag 8).  The other writes through
  `[7D41]` (`B060:07E0` string copy, type 1; `B2A0:01D5` dword, type 5) are
  type-guarded: the commit at `B060:0735..0751` and the key dispatch at
  `B060:0621..0631` (table `B060:0701`, type 0 → `B31B:0007`, type 5 →
  `B2A0:0007`) both select on `type & 0x0F`.  The hook is reached only from
  `C887:19E9`, after key `0x78`.
- *PGM load.* `C20F:0003` has two callers.  The startup loader
  `B000:02C8` (linear `0x302C8`) passes its counter `n`, tested
  `n <= 0x18` at `B000:02B9` and started at 1.  The Disk page
  `B509:01CB` (linear `0x3525B`, 20-bit `0xB525B`) passes 0, which selects the
  interactive arm: `C20F:0041..0046` stores `[E60E]+1` and `C20F:005A`
  registers the same 1..24 byte field.  No other instruction in
  `C20F:0003..04F5` writes `[BP+0Ah]`.
- *PGM save.* The only caller of `E7F5:079D` is `CB10:10C4` (as `E86E:000D`,
  linear `0x4C1C4`), pushing word `[BP-0Ah]` of `CB10:0261`.  Dispatch
  `CB10:0279..0287` and `CB10:0FE7..0FF5` both index by the unmodified
  argument `[BP+6]`; option 4 runs `CB10:04AB`, whose `CB10:04C5..04CB`
  stores word `[E60E]+1` (AH=0) and whose `CB10:04DF` registers the 1..24
  byte field.  The byte write-back leaves the high byte 0.
- *`[E60E]` (capture `[E60C]`).* Direct writers in the image:
  `CA45:002C` (linear `0x4A47C`) after `CA45:000B..0015` rejects indices
  outside `0..23`; linear `0x4F67C` (`CF37:030C`) stores 0; linear `0x51905`
  (20-bit `0xD1905`) restores the value that function read at linear
  `0x518A4`.  Writers through aliases or block moves were not searched;
  that residual is **UNDETERMINED** but does not affect the field clamp,
  which bounds every value the user can commit.

Every window above is byte-identical in the capture except DGROUP
displacements shifted by −2 (checked byte-by-byte against `ROMAPP.BIN`); the
one other difference in `CB10:0261..10FD`, the far call at `CB10:1047`, is in
the option-1 branch and not on these paths.

**PROVEN (emulator, fault injection):** `emu/test_mute_range.py` sets the
caller's one-based index to 25 only while the cave hook runs
(`emu/lua/mute_range_inject.lua`), zeroes `mute_staging` (the address
`mute_state_bx(24)` returns), and restores the index at the stock return
site (`C887:19FB`; `C20F:0417`; `E86E:0273` = `E7F5:0A03`, linear `0x68953`).
With the checks: copy and load leave `mute_staging` zero and all 24 states
unchanged, the load shows no error, and the save writes exactly `0x1200`
bytes.  Against the previous payload all three tests fail: the copy writes
Program 1's state into `mute_staging`, the load commits the trailer there,
and the save writes a 4,657-byte file.

## Staging buffer

**UNDETERMINED, not changed:** whether stock scratch RAM can replace the
792-byte `mute_staging`.  `CF0C:0073` (linear `0x4F133`) takes a far
buffer (`LDS DX,[BP+6]`), so a buffer at `A2AE:0000` would be accepted by
the wrapper; whether the BIOS `INT 41` AX=4 read has placement limits is not
established.  `A2AE:0000..47FF` is not a single-owner buffer: the image has
297 immediate `A2AE` segment loads, and `A2AE:0000` is passed as a disk
buffer to `CF0C:0073` (linear `0x574BB`, `0x58597`), to `E7F5:03E5` with
`0x43D0` bytes (linear `0x3ECA3`), to `CF92:000C` (linear `0x69242`), and
others.  Proving that none of them, nor any interrupt- or task-driven path,
owns `A2AE:0000..0317` at the PGM/APS close points needs an execution-context
classification of all 297 sites; that was not done.  Reading the trailer
straight into the live table and re-clearing on failure would expose
unvalidated bytes to the note-on path during the read, so it was rejected.
`CF0C` exposes only sequential read/write wrappers (AX=4/5 at `CF0C:0073` /
`0096`) besides the generic `CF0C:0006`; no seek wrapper was found, so a
validate-then-re-read pass is not available either.

The saving actually taken is small and safe: 186 immediate shifts
(`SHL AX,5`, `SHR AL,4`) replace repeated single-bit shifts in this file,
which more than pays for the range checks (cave 12,042 → 12,026 bytes).
The V53 executes these encodings already in `mods/mute_ui.inc`.

## Near-full media

Generic addresses, XA=1; 20-bit = stock 24-bit (second PGR), mod 24-bit =
`0x300000 | 20-bit` (third PGR); capture offset = linear − `0x20000`.

**PROVEN (code): what the Save page shows and what it enforces are
different constants.**

- *Display.* `CB10:13C3` (linear `0x4C4C3`) computes free space as
  `floor(free bytes / 1024)` from `CF0C:0056` (`INT 41` AX=8).  The page
  setup stores the size estimate in `[BP-4]` and draws it as `Size`: PGM
  `CB10:1207` (linear `0x4C307`), 5 KB plus the rounded size of the sounds
  when `[8625]` selects them; APS `CB10:12BD` (linear `0x4C3BD`), stock
  46 KB, plus sounds.  That AX=8 returns cluster count and cluster size is
  **HYPOTHESIS**; the displayed `Free` matches `floor(clusters*512/1024)` in
  every run.
- *Gate.* On `<Do it>` (key `0x78`), `CB10:0E4A..0E5D` overwrites `[BP-4]`
  with a constant: `CB10:0E52` (linear `0x4BF52`) `MOV WORD [BP-4],5` for
  option 4 (PGM), `CB10:0E5D` (linear `0x4BF5D`) `MOV WORD [BP-4],0x2A`
  (42 KB) for option 5 (APS).  If the file already exists,
  `CB10:0ED1..0F04` refuses with `F900` when free + old size is below
  `[BP-4]`, deletes it, and re-reads free space at `CB10:0F9B`.  Either way
  `CB10:0FC8..0FD3` (linear `0x4C0C8`) refuses with `F900` when `[BP-4]`
  exceeds free.  The sounds term of the display estimate is not part of this
  gate.  For the APS, the stock gate (42 KB) and display (46 KB) are both
  below the stock 24-program file (48,531 bytes, 95 clusters).

Cluster arithmetic, 512-byte clusters: the APS with trailer is 48,531 + 808
= 49,339 bytes = 97 clusters (49,664 bytes).  A 49 KB gate requires
`floor(n*512/1024) >= 49`, that is `n >= 98` free clusters; it refuses 97,
where the file would have fit, by one cluster.  48 KB would admit 96
clusters, which is too few, so 49 KB is the smallest whole-KB gate that is
safe.  For the PGM, 4,657 bytes = 10 clusters, and the stock 5 KB gate
requires exactly 10.

### Defect as observed before the fix

**PROVEN (emulator, 1.44 MB FAT12, free space set by a filler file).**
Stock gates; mod payload with trailers:

| Case | Free clusters | Result |
|---|---:|---|
| APS, stock OS | 95, 96 | saved; 48,531 bytes; FAT consistent |
| APS, mod | 95 | error box `FF04` (the stock "not formatted ... or possibly bad" text); entry 48,640 bytes = stock + 16-byte header + 93 payload bytes; FAT consistent; reloads as a legacy APS |
| APS, mod | 96 | error box `FF04`; directory entry size 0, cluster 0; all 96 allocated clusters lost |
| APS, mod | 97 | saved; 49,339 bytes |

The stock OS shows the same size-0/lost-chain result when its own APS does
not fit (94 free clusters, exploratory run).  So the corruption comes from
how the BIOS handles a failed write, and the trailer widened the window in
which that happens.  Why one failed write leaves a consistent entry and
another a lost chain is **UNDETERMINED**.

### Fix

Three code patches in `mods/WAVE.args` raise the APS figure from 46/42 KB to
49 KB.  Bytes were checked identical in generic Vailixi and in `ROMAPP.BIN`;
the whole `CB10:12BD..12E7` window differs only at the DGROUP byte
`[8625]`→`[8623]`.

| Role | `CS:IP` | Linear | 20-bit | mod 24-bit | capture offset | Bytes |
|---|---|---:|---:|---:|---:|---|
| gate, enforced | `CB10:0E5D` | `0x4BF5D` | `0xCBF5D` | `0x3CBF5D` | `0x2BF5D` | `C7 46 FC 2A 00` → `C7 46 FC 31 00` |
| display, no sounds | `CB10:12C4` | `0x4C3C4` | `0xCC3C4` | `0x3CC3C4` | `0x2C3C4` | `B8 2E 00` → `B8 31 00` |
| display, with sounds | `CB10:12E3` | `0x4C3E3` | `0xCC3E3` | `0x3CC3E3` | `0x2C3E3` | `05 2E 00` → `05 31 00` |

The two display patches alone do not change behaviour.  In an emulator run
with only them, the page showed `Size: 49K` / `Free: 48K` at 96 free clusters,
saved anyway, and lost the file exactly as before.  The `CB10:0E5D` gate
patch is required.  `CB10:12E3` adds 49 KB to the rounded sound total for
the display only.  Whether each `.SND` written by "with sounds" has its own
free-space check is **UNDETERMINED**.

### Result after the fix

**PROVEN (emulator, `emu/test_mute_disk_full.py`, payload with all three
patches):**

| Case | Free clusters | Result |
|---|---:|---|
| PGM, mod | 9 | `Size 5K` / `Free 4K`; `F900` "not enough room"; nothing written; FAT unchanged |
| PGM, mod | 10 | saved; 4,657 bytes; chain 10 clusters; trailer decodes |
| APS, mod | 95, 96, 97 | `Size 49K` / `Free 47K, 48K, 48K`; `F900` "not enough room"; no entry; directory and both FATs byte-identical to before |
| APS, mod | 98 | saved; 49,339 bytes; 1 cluster left; FAT consistent; trailer holds the two configured states and 22 clear ones |
| APS, stock OS | 96 | saved; 48,531 bytes; FAT consistent |

None of the tested levels left a lost cluster or a zero-size entry.

Still unobserved: clusters of 2 KB or more, where a whole-KB gate does not
bound the cluster count; a PGM or APS saved together with sounds; saving over
an existing file on a near-full disk; and the same paths on a real floppy
drive.

## Execution evidence

`python3 -m unittest emu.test_mute_persistence -v` passed all four tests in
145.966 seconds against the final captured-profile candidate
`build/mods/WAVEHW.SYS`, SHA-256
`39473bfb19b337e7a38c0eb9394520acdecabb50d668531ed5b727a5328ab360`.
The observer was read-only and obtained `mute_states` from the assembler map;
all mutations used real panel events and stock Disk or startup-file paths.

- **PROVEN (emulator):** saving Program 2 while Program 1 was active appended
  Program 2's exact 49-byte state trailer.  A cold run then loaded that file
  through Disk / Load into destination Program 2 and restored the state there.
- **PROVEN (emulator):** Disk / Save All Programs produced a 24-state,
  808-byte APS trailer.  A cold startup APS load restored distinct Program 1
  and Program 2 states and left Programs 3..24 clear.
- **PROVEN (emulator):** loading the checked-in legacy PGM into a destination
  with nonzero stale state cleared it to the backward-compatible default.
- **PROVEN (emulator):** a full-size PGM extension with an exact header but an
  invalid group nibble was rejected transactionally; no staged byte committed
  and the destination remained clear.

The durable test log is `build/wavebench06-mute-persistence-tests.log` and the
test source is `emu/test_mute_persistence.py`.  `tools/verify_boot_slice.py`
also passed all 171 stock-image checks after the final build.

After the range checks (2026-10-01, captured-profile `build/mods/WAVEHW.SYS`
SHA-256 `917ef453d5a3e1411fb0d245b4d6e09063d7231f9859300c76f7e797bd56cafa`,
before merging other workers' changes): `emu.test_mute_persistence` 4/4,
`emu.test_mute_lifecycle` 2/2, `emu.test_mute_ui` 7/7,
`emu.test_mute_range` 3/3, and `emu.test_mute_disk_full` 8/8 (one expected
failure, the APS defect) passed.  With the three APS patches, the reworked
`emu.test_mute_disk_full` passed 6/6 and `emu.test_mute_persistence` 4/4.

## Remaining boundary

- PGM and APS fixed-size program persistence is **PROVEN** statically.  A
  hardware save/load round trip of the implemented trailer is deferred.
- The stock `.ALL` save path is **PROVEN** sequence/song-only and therefore
  outside MUTE GROUPS program persistence.
- Near-full media: observed in the emulator ("Near-full media" above).  The
  PGM trailer fits the stock gate.  The APS trailer is covered only when the
  `CB10:0E5D` gate patch is present.  Real-drive behaviour of the BIOS
  failed-write path is a deferred physical observation.
- The staging buffer stays in the cave until the ownership of
  `A2AE:0000..0317` at the close points is established.

**PROVEN (real-menu lifecycle):** `emu.test_mute_lifecycle` copies Program 1
with Enabled=1, pads 1–63 in group 4 and pad 64 in group 2 into Program 24.
Initialization then clears only Program 24. Both tests pass in the final
`build/wavebench06-navigation-ui-tests.log` run against the payload hash above.
