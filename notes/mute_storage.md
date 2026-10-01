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
`[0x707D0,0x74000)`).  The final candidate combined WAVE/MUTE payload assembled
on 2026-10-01 uses 12,042 of 14,384 cave bytes, leaving 2,342.  It contains a
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
executes the original record copy, invalidates destination voice tags, copies
33 mod bytes from source to
destination, and far-jumps to `C887:19FB`.  Address forms are linear
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

## Remaining boundary

- PGM and APS fixed-size program persistence is **PROVEN** statically.  A
  hardware save/load round trip of the implemented trailer is deferred.
- The stock `.ALL` save path is **PROVEN** sequence/song-only and therefore
  outside MUTE GROUPS program persistence.
- Near-full-media free-space estimates do not include the 49-byte PGM trailer
  or `16+33*N`-byte APS trailer.  The write wrapper returns the first trailer
  write error through the stock branch and still closes the handle, but exact
  media cleanup behavior on such a failure remains a deferred observation.

**PROVEN (real-menu lifecycle):** `emu.test_mute_lifecycle` copies Program 1
with Enabled=1, pads 1–63 in group 4 and pad 64 in group 2 into Program 24.
Initialization then clears only Program 24. Both tests pass in the final
`build/wavebench06-navigation-ui-tests.log` run against the payload hash above.
