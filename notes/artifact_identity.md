# Artifact identity — Vailixi OS 3.50

**Checked:** 2026-09-21. Status tags: **PROVEN** / **HYPOTHESIS** / **UNDETERMINED**.

## What the target is

The target is not a single raw 512 KiB file. It is a **pair of 256 KiB
AM27C020 chip images** that MAME interleaves onto the V53 program bus.

| Role | Path | Size | SHA-256 | SHA-1 | CRC32 |
|------|------|------|---------|-------|-------|
| LS / even | `07-rom/Vailixi 3.50/3.50 Vailixi (LSE).BIN` | 262144 | `cb4531fab4f2a43d3ad71465ac9efbe4bd6c3b23401cdbac379eea37234c4004` | `c270a92f8ed273a1ede16388bb8f30c85ac1faab` | `9f3031b5` |
| MS / odd | `07-rom/Vailixi 3.50/3.50 Vailixi (MSO).BIN` | 262144 | `514c745dea6bb711d19cf6e09bb4e7987f732c1bfa6b01857068c9982e295801` | `f6d080481de40bea2c94bbc96b222c5f9b7afaf4` | `e62ebb26` |

**PROVEN:** SHA-1 and CRC32 match the MAME `vailixi` BIOS `ROMX_LOAD` lines in
[`06-mame/driver/mpc3000.cpp`](../06-mame/driver/mpc3000.cpp). These are
therefore the same chip images MAME expects, not a transformed update
container.

## Linear image

```
linear[0::2] = LS
linear[1::2] = MS
```

| Field | Value |
|-------|-------|
| Size | 524288 (`0x80000`) |
| SHA-256 | `a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9` |
| Builder | [`tools/linear_rom.py`](../tools/linear_rom.py) |

Do not treat the LS or MS file as a loadable V53 program by itself. A
correct instruction decoded in chip-file order is at the wrong address.

## Kind of artifact

| Question | Verdict | Evidence |
|----------|---------|----------|
| Raw chip images? | **PROVEN** yes | 262144-byte pair; MAME `ROM_SKIP(1)`; service IC13/IC14 AM27C020 |
| Update container / floppy payload? | **PROVEN** no | Contrast `07-rom/v3.16 maintenance upgrade/M3K316.SYS` |
| Interleaved dump? | **PROVEN** yes, this is the native packaging | LS/MS pair |
| Transformed payload after a header? | **PROVEN** no header on the chip images | first 68 linear bytes are `0xFF` padding plus IVT slots, not a container |

## Embedded identity strings

| File | Text | Confidence |
|------|------|------------|
| `0x210F5` | `Vailixi 3.50 (---/--/----)` | **PROVEN** as bytes; date field unused |
| `0x78125` | `MPC-3000 BIOS 21/08/07` | **PROVEN** as bytes; **HYPOTHESIS** that `21/08/07` is 2007-08-21 |
| `0x79ABB` | `mpc3000le@yahoo.com.au` | **PROVEN** as bytes in the system-error text |
| `0x7B00F` | `COPYRIGHT (C) 1983 KADAK PRODUCTS LTD.` | **PROVEN** as bytes; **PROVEN** start at `FB00:000C` from the `F07A` init table |

## Hardware revision under study

| Item | Value | Status |
|------|-------|--------|
| CPU board | L4012A family | **PROVEN** from service parts list |
| Main CPU | µPD70236GD-16 (V53), 32.000 MHz XTAL | **PROVEN** marking + X1; marketing “16 MHz V53” is the CPU/bus clock, not the crystal |
| OS EPROMs | AM27C020 ×2, LS/MS | **PROVEN** |
| Work RAM | 2× HM658512 @ `0x300000` | **PROVEN** as MAME map + PGR[0]=`0xC0`; PAL decode still **UNDETERMINED** |
| Panel MCU ROM | AM27C256, expected SHA-1 `a6001618…` | **UNDETERMINED** — image not in this tree |
| Fitted options | Standard BOM; no expansion claim | **HYPOTHESIS** until a specific board is photographed against this OS |

Vailixi 3.50 is a community OS, not a factory Akai burn. The machine model
is still the MPC3000 V53 platform documented in the service pack and MAME
driver.

## Supporting images (not the target)

Stock 3.08 / 3.11 / 3.12 LS+MS pairs and floppy OS 3.16 are present under
`07-rom/`. Their hashes are in [`07-rom/ROM_INVENTORY.md`](../07-rom/ROM_INVENTORY.md).
The reset stub at `0x7FF00` and the `EA FFF0:0000` vector are **byte-identical**
on 3.08, 3.11, 3.12, and 3.50.

## Regeneration

```bash
python3 tools/verify_boot_slice.py
python3 -m unittest tests.test_boot_slice -v
```
