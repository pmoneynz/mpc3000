# Getting started

Read [`PROJECT_GOAL.md`](PROJECT_GOAL.md) first.

## What is here

A research pack for the MPC3000 (CPU manuals, service OCR, MAME sources,
operator's manual, internals photos) plus the Vailixi 3.50 LS/MS EPROM
pair. Analysis lives in `notes/`, `analysis/`, and `tools/`.

This is not the MPC2000XL project. The CPU family is shared. The memory
map is not.

## Prove the image

```bash
python3 tools/verify_boot_slice.py
python3 -m unittest tests.test_boot_slice -v
```

Both must pass before a claim that depends on the linear image.

`ndisasm` is optional and 8086-only:

```bash
mkdir -p build
python3 -c "from tools.linear_rom import load_vailixi_linear; open('build/vailixi350.bin','wb').write(load_vailixi_linear())"
# ndisasm -b 16 is 8086-only; do not trust it across 0F E0 / 0F F0
```

Ghidra is not set up yet. When it is, the processor spec must decode
`0F E0 11` at file `0x7AC1C` as `BRKXA 0x11`.

## Address cheat sheet

| You have | You want | Rule |
|----------|----------|------|
| LS or MS chip offset | linear file | do not convert in your head; interleave first |
| 20-bit `CS:IP` | linear file | `((CS<<4)+IP) & 0x7FFFF` |
| 20-bit address after first PGR, page 0–39 | 24-bit RAM | `0x300000 + (addr20 & 0x9FFFF)` is **wrong**; use the PGR formula in `notes/address_model.md` |
| Reset vector | file `0x7FFF0` | `FFFF:0000` |

## First reading order

1. [`notes/artifact_identity.md`](notes/artifact_identity.md)
2. [`notes/address_model.md`](notes/address_model.md)
3. [`notes/boot_reset_to_bios_banner.md`](notes/boot_reset_to_bios_banner.md)
4. [`notes/named_unknowns.md`](notes/named_unknowns.md)
5. [`TODO.md`](TODO.md)

Hardware background stays in [`README.md`](README.md).
