# Work queue

Do the highest item that is unblocked. Close a named uncertainty; do not
open a second backlog of unexplained code.

## Now

1. Close `U-AMX-WAIT`: partition `FB00:01EA` / `0537` and name the wake
   writer (IRQ, RAM flag, alias). That is the missing half of the first
   milestone.
2. Trace `INT 43` AX=4 from a banner character to LC7981 memory or a
   justified non-display sink (`U-INT43-AX4`).
3. Inventory consumers of `8010:0000` after the `0x7C92` copy
   (`U-COPY-7C92` remainder).

## Next

4. Catalog writers of PGR after `BRKXA 0x14` (`U-XA-LIVE`).
5. Stand up Ghidra with a V53-capable processor spec. Validate `BRKXA` /
   `RETXA` decode against the bytes at `0x7AC1C` before trusting the tool.
6. Seed a machine-readable owner ledger from the ranges in
   [`notes/boot_reset_to_bios_banner.md`](notes/boot_reset_to_bios_banner.md).
7. Whole-image string and entry-candidate scans. Investigate candidates
   before accepting them as code.

## Blocked on absent artifacts

8. Panel AM27C256 (`U-PANEL-ROM`).
9. Schematic sheets / 18CV8 fusemaps (`U-PAL`, `U-C0XX`).
10. Hardware captures for LCD glass, IRQ timing, and TE7774 (`U-PHYS`).

## Do not do yet

- Copy the MPC2000XL ledger machinery wholesale.
- Build an emulator except to answer a named item above.
- Treat MAME `MACHINE_NOT_WORKING` device models as primary evidence.
- Annotate stock 3.1x or floppy 3.16 as if they were the target.
