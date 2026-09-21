# Agent rules

[`PROJECT_GOAL.md`](PROJECT_GOAL.md) wins conflicts.

## Target

Vailixi OS 3.50, interleaved from the LS/MS pair under `07-rom/Vailixi 3.50/`.
Do not analyze a chip file as if it were the linear program image.

## Evidence

- Cite linear-file offsets, `CS:IP`, 20-bit and 24-bit physical addresses,
  and the PGR/XA mode that makes them true.
- Tag `PROVEN`, `HYPOTHESIS`, or `UNDETERMINED`.
- Unknown hardware is a named boundary. Do not invent LC7981, TE7774, PAL,
  or panel behavior.
- Physical tests are deferred. Record the missing observation. Continue
  software-verifiable work.
- A trace is one execution. All-paths claims need writers, aliases, and
  entry domains.
- `ndisasm` and Capstone are 8086 tools. They mis-decode `BRKXA`/`RETXA`
  (`0F E0` / `0F F0`). Do not accept their stream across those bytes.

## Recovery order

1. Established entries: reset, proven IVT/BRKXA targets, far-call table
   consumers.
2. Follow control flow. Check instruction bounds and every exit.
3. Whole-image candidates are suspects until investigated.
4. Data objects are established by consumers, format constraints, and
   bounds — not by “looks like text.”
5. Shared machinery before leaf routines.
6. RAM objects: init, readers, writers, aliases, bounds, units, lifetime,
   interrupt interaction.

## Ownership

Padding needs a purpose and a boundary, not a per-byte essay. Do not mark
unanalyzed bytes `excluded_workspace`. Do not treat `unresolved` as an
owner.

## Tools

Never modify files under `07-rom/`. Generated images go to `build/`.
Regenerate facts with `python3 tools/verify_boot_slice.py`.
