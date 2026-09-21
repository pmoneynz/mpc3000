# Disassembly checklist — Vailixi OS 3.50

Target: interleaved linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
[`PROJECT_GOAL.md`](PROJECT_GOAL.md) wins conflicts.

Marks: `[x]` done · `[ ]` open · `[PARTIAL]` suspended on a named physical
or artifact block. `unresolved` is never an owner. Close a named
uncertainty; do not accumulate owned but unexplained code.

Loop rule: do the highest unblocked `[ ]`. If the only remaining work on
an item needs hardware, a missing ROM, or a datasheet not in this tree,
mark `[PARTIAL]`, name the missing observation, and continue.

---

## G0 — Artifact and address model

- [x] Pin LS/MS hashes and the linear interleave (`tools/linear_rom.py`).
- [x] Prove the image is a raw chip pair, not a floppy container.
- [x] Record reset `FFFF:0000` = file `0x7FFF0`.
- [x] Write the four address forms and XA/PGR rule (`notes/address_model.md`).
- [x] Pin first, second, and third PGR images as bytes and `OUTSW` sources.
- [ ] Revisit G0 only if a different burn or a PAL fusemap changes decode.

---

## G1 — First slice (reset → loop + one observable)

- [x] Partition `FFF0` wait-state stub and `FAC0:0000` through `BRKXA 0x14`.
- [x] Partition `FAC0:0134` init table; retract “only first record runs.”
- [x] Prove BIOS `F800:000A` and `F800:1AD4` `RETF`.
- [x] Prove AMX start `FB00:000C` and dispatcher `FB00:013E`.
- [x] Partition `01EA` / `0537` and the `FB00:023A` empty-queue idle.
- [x] Bound the `0x7C92` copy (`AA 55` + string pointers, dest `0x380100`).
- [x] Prove `INT 43` AX=0 writes LC7981 ports `0xE2`/`0xE0`.
- [ ] **D1.** Prove whether first `01EA` dispatches a create-table task
      (records 0–7 at `FB76:0002`) or idles. If it idles, name the ISR
      that leaves `023A` (`U-AMX-WAIT`).
- [ ] **D2.** Trace `INT 43` AX=4 from a banner character to LC7981
      memory or a justified non-display sink (`U-INT43-AX4`).
- [ ] **D3.** Connect one observable end to end (banner glyphs **or**
      first AMX task effect) with code, data, RAM, and ports.
- [PARTIAL] **D3-glass.** Pixels on the LC7981 glass (`U-PHYS`, `U-LC7981`).

G1 is complete only when D1 and D3 are `[x]` (D3-glass may stay PARTIAL).

---

## G2 — Shared machinery

- [ ] **D4.** Catalog every writer of `0xFF00-0xFF7E` after first AMX
      `RETF`. Cite the live table for later RAM (`U-XA-LIVE`).
- [ ] **D5.** Inventory IVT slots: ROM templates, BIOS plants, AMX
      `IVT[0]`/`[4]`, `F800:1AD4` plants, later aliases and writers.
- [ ] **D6.** Recover AMX public far-call surface and TCB word grammar
      (`[SI]` bits 0/1/2/3/15, `+4/+6` stack, stride `0x40`).
- [ ] **D7.** Identify create-table tasks 0–6 (`FB76:0002` + `0x12*n`)
      the same way record 7 is `B000:00DF`. Follow each entry; pin exits.
- [ ] **D8.** Establish the dominant calling convention (near vs far,
      register args, inline-string walker at `0x79875`).
- [ ] **D9.** Partition interrupt wrappers that adjust return addresses
      or switch XA (`FAC0:01A4`, AMX `02F8`/`02EF`).
- [ ] **D10.** Finish `U-COPY-7C92`: grammar past the string front;
      consumers of `8010:0000`; later writers and aliases.
- [ ] **D11.** Find allocators / resource interpreters only when a
      named slice needs them. No whole-image leaf hunt first.

---

## G3 — Structural closure (byte and transfer domains)

- [ ] **D12.** Seed a machine-readable owner ledger from ranges in
      `notes/boot_reset_to_bios_banner.md` and `notes/amx_wait.md`.
      Owners are `code`, `data`, or `excluded_workspace` only.
- [ ] **D13.** Purpose-and-boundary every `0xFF` padding window.
      `[0x00054, 0x20000)` and stub tails are already done.
- [ ] **D14.** Whole-image string scan. A consumer, not printability,
      establishes text.
- [ ] **D15.** Whole-image entry-candidate scan (reset, IVT, far-call
      tables, create-table). Investigate before accepting as code.
- [ ] **D16.** From each established entry, follow control flow, check
      instruction bounds, and resolve or exclude every exit.
- [ ] **D17.** No gap and no overlap in the ledger. `unresolved` is
      debt. Regenerating the ledger must match the notes.

Ghidra is navigation, not evidence. Validate `0F E0` / `0F F0` at
`0x7AC1C` as `BRKXA 0x11` before trusting a processor spec.

---

## G4 — Semantic slices (small and complete)

Do these after the dispatcher and address map for that slice are stable.
Each slice needs the contract in `PROJECT_GOAL.md` (purpose, IO, state,
bounds, evidence, unknowns).

- [ ] **D18.** Boot / banner / LCD init (close D2–D3).
- [ ] **D19.** Front-panel navigation (blocked on panel traffic if the
      ROM is absent — then PARTIAL).
- [ ] **D20.** Pad / note entry.
- [ ] **D21.** Sequencer transport (play/stop/position).
- [ ] **D22.** Sampling / DSP register path (`0x0060`, DMA3).
- [ ] **D23.** Load / save (FDC `0xE8`, SCSI `0xA0`, IRQ3 demux).
- [ ] **D24.** MIDI (TE7774 `0xC0-0xDF`).
- [ ] **D25.** Error, cancel, and recovery paths (system-error text at
      `0x79ABB` is bytes only).
- [ ] **D26.** Option-dependent behavior only when a consumer exists.

---

## G5 — Platform (named hardware boundaries)

- [PARTIAL] **P1.** Panel µPD78C10 AM27C256 (`U-PANEL-ROM`). Missing
      observation: the dump MAME names `mp3000__op_v1.0…ic602.bin`.
- [PARTIAL] **P2.** IC25/IC29/IC31 18CV8 fusemaps and schematic sheets
      (`U-PAL`, `U-C0XX`). Missing: service schematic set / JEDEC.
- [PARTIAL] **P3.** LC7981 glass and the seven AX=0 register pairs
      (`U-LC7981`, `U-PHYS`). Software may apply an HD61830 manual to
      the pairs; glass remains PARTIAL.
- [PARTIAL] **P4.** TE7774 register map (`U-TE7774`). Software may
      inventory `IN`/`OUT` consumers; bit meaning stays PARTIAL.
- [PARTIAL] **P5.** IRQ / timer timing, SMPTE, panel IPC on the wire
      (`U-PHYS`).
- [PARTIAL] **P6.** µPD70236 vs 70236A marking (`U-V53A`). Treat as
      V53-family until a chip photo OCR exists.
- [ ] **P7.** PGR page 61 frame `0x40` → `0x100000` (`U-PGR61`): find a
      software consumer or keep UNDETERMINED. Not automatically PARTIAL.
- [ ] **P8.** NVRAM `0x500000` consumer on a proven path, or document
      that boot does not touch it.

---

## G6 — Reproduction

- [ ] **R1.** Every new fact is pinned in `analysis/boot_slice_facts.json`
      (or a later ledger) and checked by `python3 tools/verify_boot_slice.py`.
- [ ] **R2.** `python3 -m unittest tests.test_boot_slice -v` stays green.
- [ ] **R3.** Ghidra project only after `BRKXA`/`RETXA` decode is checked
      against file `0x7AC1C`.
- [ ] **R4.** Independent review of consequential claims against primary
      bytes. Automated names remain proposals.

---

## Do not do

- Copy the MPC2000XL ledger wholesale.
- Build an emulator except to answer a named item above.
- Treat MAME `MACHINE_NOT_WORKING` models as primary evidence.
- Annotate stock 3.1x or floppy 3.16 as if they were the target.
- Mark unanalyzed bytes `excluded_workspace`.
- Accept `ndisasm`/Capstone across `0F E0` / `0F F0`.
