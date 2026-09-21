# Service manuals in this folder

| File | Pages | Size | What it is |
|------|-------|------|------------|
| `Akai-MPC-3000-Service-Manual.pdf` | 16 | ~19 MB | High-res scan — **parts / disassembly / board locations** (added 2026-09-21) |
| `Akai_MPC3000_Service_Manual.pdf` | 16 | ~3.7 MB | Same document family, lower-res earlier copy |

**No schematic sheets** in either PDF (no CPU address decode drawings, no wiring diagrams beyond exploded/location views).

## High-value confirms from CPU P.C. BOARD parts list (high-res p.8)

| Ref | Part | Role |
|-----|------|------|
| IC6 | µPD70236GD-16 | Main CPU (V53), marking matches service |
| X1 | 32.000000 MHz HC-49/U | Main XTAL — resolves MAME 32 MHz vs “16 MHz V53” marketing |
| X2 | 33.8688 MHz | DSP clock |
| IC13 / IC14 | AM27C020-150DC | OS EPROMs LS/MS |
| IC15 / IC16 | HM658512LP-85 | Work RAM |
| IC28 | L7A1045 L6028 DSP-A | Sample DSP |
| IC1 | µPD72069GF-3BA | FDC |
| IC23 | MB89254 | External PIT |
| IC30 | MB89255B | 8255-class PPI |
| **IC25** | **18CV8PC-25** (EI-419229J) | PAL/GAL decode |
| **IC29** | **18CV8PC-15** (EI-419230J) | PAL/GAL decode |
| **IC31** | **18CV8PC-15** (EI-419232J) | PAL/GAL decode |

These three 18CV8 devices are the likely **memory/I/O decode** PLDs. Fusemaps still needed (read out from a board, or full schematics).

## Still missing for OS ROM work

1. Full multi-page **schematic set** (CPU board address decode, IRQ OR-ing, TE7774 wiring)
2. **18CV8 fusemaps** for IC25 / IC29 / IC31
3. Panel MCU ROM (see `07-rom/ROM_INVENTORY.md`)
