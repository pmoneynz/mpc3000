# Akai S1000/S3000 floppies: the 3.50 loader and `tools/snd2akai.py`

Closes the uncertainty "what must an Akai floppy contain for Disk 8 to load
it exactly", which the SND → Akai converter depends on.

Image and address model: the Vailixi 3.50 linear image
(`tools/linear_rom.py`). Code runs with XA=1 under the second PGR, where these
pages map one-to-one: for segment `BE7E`, file = `0x3E7E0`+IP and 24-bit =
`0x0BE7E0`+IP; for `E7F5`, file = `0x67F50`+IP; DGROUP offset X (DS=`8010`) is
file `0x20000`+X. Neither `BE7E` (`0x3E7E0`–`0x3FB30`) nor `E7F5` contains
`0F E0` or `0F F0`, so the 8086 decode is valid there.

## Entry

`BE7E:0F9F` (file `0x3F77F`) paints `Load S1000/S3000 Sample Files`
(`PUSH 3F58` at `BE7E:0FC4`, string at file `0x23F58`). **PROVEN**. Its one
far caller, file `0x352A1`, is in a menu jump arm; that this is Disk item
`8.Load S3000 disk` (string file `0x2235A`) is **HYPOTHESIS**, and the
emulator run in `emu/test_akai_load.py` enters the screen that way.

## Disk and geometry

| Fact | Site | Status |
|------|------|--------|
| Detection patches the FDC parameters with the HD table DS:`7870` (N=3, EOT=10, GPL 0x35), reads 0x40 bytes of C0/H0/R1; on failure retries with the DD table DS:`78B4` (EOT=5) | `E7F5:0380` (file `0x682D0`) | PROVEN |
| No content check: any disk with a readable 1024-byte R1 is "Akai" | same | PROVEN |
| Block b → cylinder b/(2·spt), head (b/spt)&1, sector b%spt+1 | `E7F5:027A` (file `0x681CA`) | PROVEN |
| 80 cylinders | not bounded in code | HYPOTHESIS |

## Directory and FAT (floppy branch)

| Fact | Site | Status |
|------|------|--------|
| 0x43D0 bytes from block 0 into `A2AE:0000` (DS:`3F44`) | `BE7E:0486` (file `0x3EC66`) | PROVEN |
| If byte `+0x10` is `0xFF` (S3000 floppy flag), the directory is at `+0x1400`, else `+0` | `BE7E:04DF` | PROVEN |
| 64 entries of 24 bytes, all scanned (`[bp-4]=0x40`) | `BE7E:03C5` (file `0x3EBA5`) | PROVEN |
| Header length set to 0x96 for every floppy entry (`[bp-2]=0x96`, stored at entry `+0E`) | `BE7E:03CA`, `BE7E:045A` | PROVEN |
| A sample is `(entry+0x10 & 0x7F) == 0x73`: S1000 `s` and S3000 `s`+0x80 both pass | `BE7E:0438`–`0444` | PROVEN |
| Name `+00..0B` through table DS:`3F1A` = `0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-.`; trailing `_` dropped | `BE7E:01B7` | PROVEN |
| `+11..13` 24-bit byte size including header; `+14` start block | `BE7E:011C`, `BE7E:0858` | PROVEN |
| FAT at `+0x600`, one word per 1 KiB block; next = FAT[cur]; `0x8000` while words remain aborts; the end is the header word count, not a FAT marker | `BE7E:03B3`, `BE7E:0A3E`–`0A4F` | PROVEN |
| Volume label not read on floppy | — | PROVEN |

Consequence: on floppy, 3.50 always reads a 150-byte S1000 header. A native
S3000 sample (192-byte header, 42 zero bytes after the S1000 part) loads with
21 leading zero words and loses its last 21 frames. A DD S3000 floppy keeps
its directory at `+0x1000`, which the `+0x1400` branch misses.

## Sample header

| Offset | Use | Site | Status |
|--------|-----|------|--------|
| `+03..0E` | name; must equal the directory name or the load fails (−3) | `BE7E:0939`–`096F` | PROVEN |
| `+14` int16 | tune = trunc((v ± 13)·10/256), clamped ±120, to record `+12` | `BE7E:0AE5`–`0B36` | PROVEN (code); record unit HYPOTHESIS (tenths of a semitone) |
| `+1A` u32 | words to copy | | PROVEN |
| `+1E` / `+22` u32 | to record `+14` / `+18` (soft start / end) unchanged | `BE7E:0AC1`–`0AE0` | PROVEN |

Not read: block ID, bandwidth, root key, loops, play mode, sample rate
(`+8A`). Data goes to wave RAM unchanged by DMA (`CF92:000C`); no rate check
and no resampling.

## Stereo

A name longer than two characters ending `-L` or `-R` is a stereo half
(`BE7E:0626`). The partner (last letter flipped) must exist with an equal
24-bit size (`BE7E:06D9`); `-L` loads first, `-R` follows it in wave RAM, and
the sound is named after the `-L` name without `-L`, spaces trimmed
(`BE7E:0C6B`). **PROVEN**.

## What `tools/snd2akai.py` writes

Default: an S1000 floppy (64-entry header directory, FAT, label; byte-equal
to akaiutil 4.6.8 `formatfloppyh1` when empty) with S1000 samples: block ID
3, 20 kHz bandwidth, root key 60, play mode no-loop, 44,100 Hz, `+14` =
round(25.6·tune) so the 3.50 conversion returns the SND tune for every value
in ±120, `+1E`/`+22` = the SND soft start/end (0 and length when the SND pair
is not 0 ≤ start < end ≤ length, which 3.50 playback rejects). `--s3000`
writes akaiutil's `formatfloppyh3` layout and 192-byte headers, with the
3.50 consequence above.

Evidence that the files are right, `tests/test_snd2akai.py`:

- a Python model of the loader above returns the source PCM, markers and tune
  for mono, stereo, HD and DD images;
- akaiutil (`AKAIUTIL=path`) reads both layouts and exports the source PCM
  unchanged;
- the HFE image decodes back to the raw image, with valid ID and data CRCs.

`emu/test_akai_load.py` boots stock 3.50 in MAME with the HFE and loads the
samples through the panel: records and wave RAM match the sources.

## Open

- Physical: a converted disk loaded by a real MPC3000 and by an S3000/S3200
  is not yet observed (deferred).
- Whether an S3000 shows end = length as valid (akaiutil writes length − 1)
  is **UNDETERMINED**; the MPC3000 round trip needs the SND value.
