# AKAI mod: save a Sound to an Akai S1000 floppy from the MPC3000

`mods/AKAI.args` + `mods/akai.asm` (Route A, generic Vailixi 3.50). The disk
and sample format, and the stock Disk 8 loader it must satisfy, are
[`akai_disk.md`](akai_disk.md). `tools/snd2akai.py` writes the same files on
a PC; the emulator test requires the two to be byte-identical.

## Use

1. Load the Sounds as usual.
2. Insert an Akai **S1000-format** floppy: one formatted by an S1000/S3000 in
   S1000 mode, or an image from `tools/snd2akai.py --blank` on a Gotek.
3. **Disk → 8** (now labelled `8.Akai S1000/3000`). The stock Load screen
   appears with a new soft key 3, `<Save>`.
4. `<Save>` opens *Save Sound to Akai S1000 Disk*: turn the data wheel to
   choose the Sound; the Akai name(s) and size are shown. Soft key 3
   `<Save it>` writes it, soft key 4 `<Cancel>` returns.
5. The Load screen re-reads the disk and lists the new file(s).

A stereo Sound becomes `NAME-L` and `NAME-R` (the pair Disk 8 and the
samplers join back); a mono name ending `-L`/`-R` is saved as `NAME L`/`R`.
Soft start/end and tune are kept. Refusals use the stock error boxes: file
already exists (F800), not enough room (F900), maximum files (FA00),
not an Akai disk (FF49), no floppy (FF80), write protected (FF03),
disk error (F500). An S3000-format floppy is refused (`S3000 disk: use an
S1000 disk.`): 3.50 reads it with a fixed S1000 header, so S3000 samples
would load shifted (akai_disk.md).

Not provided: formatting a floppy to Akai geometry (stock 3.50 has no N=3
format path; the BIOS format tables are N=2, F800:209A), saving to SCSI
volumes (Soft key 3 there stays the stock `<Sel Vol>`).

## Hooks

| File | `CS:IP` | Stock | Mod | Effect |
|------|---------|-------|-----|--------|
| `0x22353` | DS:`2353` | `8.Load S3000 disk` | `8.Akai S1000/3000` | Disk menu item 8 (one consumer, `B509:0026`) |
| `0x2412D` | DS:`412D` | `           <Sel Dsk>` | ` <Save>    <Sel Dsk>` | floppy soft keys 3/4 (one consumer, `BE7E:1159`) |
| `0x3FAEC` | `BE7E:130C` | `cmp byte [7CAF],0 / jz 1325` | `JMP FAR akai_sk3` | Soft key 3 on the Akai screen (key `7A`, table `CS:134C`) |
| `0x680D1` | `E7F5:0181` | `mov byte [7910],C6` | `CALL FAR fdc_op` | FDC command byte from `[cs:op_byte]` |
| `0x68184` | `E7F5:0234` | `mov dx,C00A / mov al,44 / out dx,al` | `CALL FAR fdc_dma` | DMA mode from `[cs:dma_mode]` |

`op_byte`/`dma_mode` hold the stock C6/44 except inside `akai_write`, which
sets C5 (MT|MFM|WRITE DATA) and 48 (memory → device), the pair the BIOS uses
for its own floppy writes (`F800:1ED6`). So every stock read is unchanged.
**PROVEN (trace)**: the Load screen re-reads the directory through the
patched driver after each save (`emu/test_akai_save.py`).

`akai_sk3` runs in `BE7E:0F9F`'s frame: on SCSI (`[7CAF]`≠0) it continues at
the stock `BE7E:1313`; with the stereo prompt open (`[bp-0A]`≠−1) Soft key 3
stays inert; otherwise it runs the save, sets `[bp-0E]=1` (re-read) and
`[bp-0C]=0`, and returns through `BE7E:133A` with SI=0. **PROVEN (code)**,
`BE7E:1201`–`134B`.

## Save sequence

Floppy session as the stock loader (`BE7E:0889`): `E7F5:0324` hook IRQ3,
`E7F5:0419` ready, `E7F5:0380` detect (2 HD, 1 DD), ... `E7F5:0350`.

1. Read the header (5 HD / 4 DD blocks) into `A2AE:0000` with
   `E7F5:03E5(buf, bytes, block 0)`. Refuse `+0x10 = FF` (S3000 floppy).
2. Count free FAT blocks and free directory entries; refuse a same-named file.
3. Mute (`D980:000C(1)`, as the stock SND save `E905:0012`).
4. Per plane: blocks first-fit from the lowest free block, runs of up to 13
   contiguous blocks staged at `A2AE:1400`–`47FF`: the 150-byte S1000 header
   (as `tools/snd2akai.py sample_header`), then PCM read from wave RAM with
   `CF92:000C(dst, wave, words, 1)` inside `inc/dec byte [9757]`. Each run is
   one `E7F5:03E5` write; the driver splits it at cylinder boundaries
   (`E7F5:010A`–`015D`). The chain and directory entry go into the header
   buffer.
5. Write the header back (block 0) last: a failed data write leaves the disk's
   directory and FAT as they were.
6. Unmute, `E7F5:0350`.

The buffer `A2AE:0000`–`47FF` is the stock transfer buffer the Load screen
itself refills on re-read; that nothing uses it in the background while the
Disk screens run is **HYPOTHESIS** (stock does not preserve it either).

## Evidence

`emu/test_akai_save.py`, two boots of the mod in MAME:

- **AkaiSave**: KICK (mono, tune −25, start 100/end 50000) and PAD (stereo,
  tune 37) loaded from FAT, an empty Akai HFE swapped in
  (`emu/lua/flop_swap.lua`), both saved, KICK saved again. The HFE MAME
  writes back decodes to an image **byte-identical** to
  `tools/snd2akai.py` on the same two SND files; the 3.50 loader model
  returns exactly the wave RAM, markers and tune the MPC held
  (`emu/lua/snddump.lua`); the repeat is refused with F800 and changes
  nothing.
- **AkaiSaveEdges**: an S3000 floppy — Cancel, then a refused save; the disk
  is byte-unchanged. Then a DD S1000 floppy filled by `snd2akai.py` to 50
  KiB free: `S_#R-L` saves as `S #R L`, a 130 KiB stereo Sound is refused
  with F900, and the disk equals `snd2akai.py` on FILLER + `S_#R-L`.

## Open

- **Physical**: not run on hardware. MAME's µPD72069/DMA model accepted
  C5/48; real-drive write timing, GPL 0x35 for writes, and write-protect
  reporting (ST1 NW → FF03) are unobserved. A disk written by the mod should
  be loaded on a real MPC3000 (Disk 8) and an S3000/S3200 before trusting it.
- **Personalized ROM**: the physical machine runs the 2026-10-01 capture,
  which the generic guard rejects (`rom_compatibility.md`). A WAVEHW build
  needs the DGROUP −2 translation for `7CAF`, `7910`, `792A`, the two
  strings, and the `E7F5`/`BE7E` sites checked against the capture
  (`build_wave_physical.py`); the WAVE cave has about 1.5 KiB free and this
  cave is 2.8 KiB.
- The data-wheel key filter ignores mode keys on the Save screen; Soft key 4
  leaves it.
