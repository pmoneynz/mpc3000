# Completion roadmap

[`PROJECT_GOAL.md`](PROJECT_GOAL.md) is the definition of done.
[`STATUS.md`](STATUS.md) is the audited present tense.
[`TODO.md`](TODO.md) is the executable queue.

## Gate 0 — Artifact and address model

Identity, interleave, hashes, and the four address forms. **Admitted**
2026-09-21 for Vailixi 3.50. Revisit if a different burn or a PAL fusemap
changes decode.

## Gate 1 — First behavioral slice

Reset to a named loop plus one observable, end to end.

- Done: reset through AMX start; `01EA`/`0537` TCB select; empty-queue
  idle condition; first `01EA` creates task 6 (`D9BD:0009`); create
  records 0–7 pinned as bytes; second PGR live through that transfer;
  `0x7C92` copy bounded; LC7981 init writes; banner AX=4 to `LCD_put`.
- Open: later AMX wake ISR; task 6 wait / task 7 body; PGR after
  task 7; glass pixels. AMX public API (D6) and create-table
  entries/exits (D7) are closed.

## Gate 2 — Shared machinery

Startup tails, calling convention (D8), interrupt wrappers (D9), the
`0x7C92` DGROUP (D10), dispatchers, allocators, resource interpreters.
Recover entries, blocks, continuations, and shared tails before forcing
conventional function bounds. D10 is closed. D11 waits on a named slice.

## Gate 3 — Structural closure

Every persistent byte owned. Every transfer in scope resolved or excluded.
Machine-audited ledger. D12/D13 seeded `analysis/owner_ledger.json`
(748 ranges, 133 gaps; every `0xFF` run of 4+ classified; D14
established 1096 strings by consumer; D15 established 143
entries; D16 classified every local exit: 128 bounded, 14
indirect, 1 idle loop). Ghidra is the planned navigation environment; its
processor spec must be checked against V53 `BRKXA`/`RETXA` and PGR, not
assumed from “8086-compatible.”

## Gate 4 — Semantic acceptance

Every required object has a contract. No unexplained owned code backlog.

## Gate 5 — Platform scope

Panel, LCD, timers, MIDI, SCSI, FDC, DSP, and fitted options, each to the
declared boundary. Missing hardware stays named.

## Gate 6 — Reproduction

Inventories and validators regenerate. Independent review of consequential
claims.

Supporting images (stock 3.1x, floppy 3.16, panel ROM) and a byte-exact
source rebuild are later deliverables. They are not prerequisites for
Gate 1.
