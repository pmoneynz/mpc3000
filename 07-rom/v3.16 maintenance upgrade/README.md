# ★ IMPORTANT — OS 3.16 maintenance upgrade (floppy-load, not EPROM)

**This is not a normal EPROM dump.** Treat it differently from the LS/MS pairs in `v3.08` / `v3.11` / `v3.12` / `Vailixi 3.50`.

## What it is

Community **MPC3000 / MPC3000LE operating system maintenance upgrade 3.16** (Rohan Mansell / ECSA, 2005).

- Delivered as a **floppy-bootable** image: `M3K316.SYS`
- Loaded into **RAM at power-on** from the floppy drive
- **Temporary** — gone when power is removed (does not burn to EPROM)
- Bundles features of 3.11, 3.12, 3.14B, 3.14 plus bug fixes / enhancements
- **Not** produced or supported by Akai or Roger Linn Design

## Files in this folder

| File | Role |
|------|------|
| `M3K316.SYS` | Floppy bootable OS image (MS-DOS executable container). SHA1 `b45b017721f0e59974e50de93040ccd1f973ad23`, 458047 bytes |
| `M3K316.pdf` | Original install / changelog notes. SHA1 `65124765aacddddb5e0ae52cd6de4f759cb5c928` |

## How it runs (from the PDF)

1. Copy `M3K316.SYS` to a blank/fresh floppy
2. Insert disk, power on MPC3000 / MPC3000LE
3. After ~45 s, machine runs OS 3.16 from RAM
4. Sequencer memory drops **484k → 439k** (~10%) while floppy-booted

Requires base ROM **≥ 3.11** on the EPROMs or boot may fail.

Optional permanent path mentioned in the PDF: same upgrade burned to a ROM chip set (not included here).

## Why it matters for OS ROM research

- Shows an alternate **load path**: FDC → RAM overlay / boot, not only the interleaved AM27C020 map at `000000–07FFFF`
- Useful for comparing **post-3.12** behaviour and bugfix deltas vs stock EPROM images
- Do **not** treat `M3K316.SYS` as a raw AM27C020 image for MAME `ROMX_LOAD` / EPROM programming without further unpacking analysis

## Changelog (from M3K316.pdf)

**Bugs fixed:** stale “function not implemented” menus; long-sample memory instability; unmuted outputs during disk I/O; wrong “sequencer memory low” on max SND load (3.12); SCSI sleep after low-level format.

**Enhancements:** clear all sound memory before PGM/SND/SET load; FAST/SLOW disk format options.
