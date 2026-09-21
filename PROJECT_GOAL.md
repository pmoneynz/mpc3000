# Canonical project goal

This file is the single authoritative statement of project priority. When
another document, task, experiment, or instruction conflicts with it, this
file wins and the conflicting text must be corrected.

The completion distinctions below follow the MPC2000XL preview project
([`/Users/peterwadams/Documents/2kxl/PROJECT_GOAL.md`](/Users/peterwadams/Documents/2kxl/PROJECT_GOAL.md)).
That file is the model for evidence, ownership, and semantic debt. This file
is the model for *this* machine and *this* image.

## Priority goal

Reconstruct a complete, testable model of the Akai MPC3000 running
**Vailixi OS 3.50**, with every persistent ROM byte connected to that model.

The governing question is: **what does this object do, under which
conditions, and what evidence establishes that?**

The target is the interleaved 512 KiB linear image built from:

| Chip | Path | SHA-256 |
|------|------|---------|
| LS (even) | `07-rom/Vailixi 3.50/3.50 Vailixi (LSE).BIN` | `cb4531fab4f2a43d3ad71465ac9efbe4bd6c3b23401cdbac379eea37234c4004` |
| MS (odd) | `07-rom/Vailixi 3.50/3.50 Vailixi (MSO).BIN` | `514c745dea6bb711d19cf6e09bb4e7987f732c1bfa6b01857068c9982e295801` |

Linear image: 524,288 bytes, SHA-256
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
Provenance, chip-versus-linear identity, and address forms are in
[`notes/artifact_identity.md`](notes/artifact_identity.md) and
[`notes/address_model.md`](notes/address_model.md).

Stock 3.08 / 3.11 / 3.12, floppy OS 3.16, and the panel µPD78C10 ROM are
supporting evidence. Full annotation of those images is a later milestone.
Hardware and panel behavior needed to explain Vailixi 3.50 remain tracked as
debt until resolved.

Physical hardware qualification is deferred. Continue software-verifiable
work. Record any fact that cannot be distinguished without hardware as an
exact dependency. Deferral does not turn a guess into a proven behavior.

## Definition of completion

A named function list is not completion. Completion requires all of the
following:

| Dimension | Completion requirement |
|-----------|------------------------|
| Bytes | Every persistent byte has an evidence-backed owner (`code`, `data`, or `excluded_workspace`); no gaps or conflicts. Padding is an evidence-backed subtype of data. `unresolved` is debt, never an owner. |
| Execution | Complete entry and transfer domains. Every transfer is resolved or justified as excluded. |
| Meaning | Every required code and data object has an accepted explanation. No hidden semantic debt. |
| Platform | Required hardware and external-interface behavior is established within the declared scope. |
| Reproduction | Evidence, inventories, and validation results regenerate consistently. |

A byte-exact reconstruction is additional verification. Reproducing opaque
byte arrays preserves contents without resolving meaning.

### Semantic contract

For each routine, entry, or data object, maintain:

- purpose and observable effect;
- inputs, outputs, assumptions, and calling convention;
- state read or changed, including hardware effects;
- bounds, units, errors, cancellation, and timing dependencies;
- evidence, confidence, and remaining unknowns.

For data, explain grammar and consumers. “Table of 64 words” is structure.
Understanding also requires what selects an entry and how its value is used.

Structural recovery and semantic explanation advance together.

## First milestone

An explained **reset-to-event-loop** path plus **one small observable
interaction**, with the relevant code, data, RAM state, and hardware
interface connected end to end.

Current slice (2026-09-21): reset through the FAC0 boot stub, the first PGR
map, the `F07A` init table, LC7981 init via `INT 43` AX=0, and the BIOS
banner through `INT 43` AX=4 to ports `0xE2`/`0xE0`. First AMX select
creates task 6 at `D9BD:0009`. The second PGR stays live through that
task’s first wait and the select of task 7. AMX public far calls and
TCB `[SI]` grammar are catalogued. Create-table tasks 0–7 have
pinned entries and exits. Application calls are far cdecl.
The `0x7C92` copy is the `8010` DGROUP (directory + strings +
writable globals). The owner ledger covers 267020 proven bytes;
gaps stay unowned. 1096 strings are
consumer-established; printable-without-consumer
stays candidate. 143 entries are
consumer-established; raw `9A`/`EA` stay suspects.
Every local exit from those entries is classified (128 bounded,
14 indirect, 1 idle loop); new CALL dests stay candidates.
Glass pixels and the later
empty-queue wake ISR stay open. See
[`notes/boot_reset_to_bios_banner.md`](notes/boot_reset_to_bios_banner.md),
[`notes/int43_ax4.md`](notes/int43_ax4.md),
[`notes/amx_wait.md`](notes/amx_wait.md),
[`notes/amx_first_dispatch.md`](notes/amx_first_dispatch.md),
[`notes/amx_public_api.md`](notes/amx_public_api.md),
[`notes/amx_create_table.md`](notes/amx_create_table.md),
[`notes/calling_convention.md`](notes/calling_convention.md),
[`notes/irq_wrappers.md`](notes/irq_wrappers.md), and
[`notes/copy_7c92.md`](notes/copy_7c92.md),
[`notes/owner_ledger.md`](notes/owner_ledger.md), and
[`notes/string_scan.md`](notes/string_scan.md), and
[`notes/entry_scan.md`](notes/entry_scan.md), and
[`notes/transfer_scan.md`](notes/transfer_scan.md).

## Priority order

1. Repair evidence-integrity or safety failures.
2. Resolve shared uncertainties: addressing, dispatch, writers, aliases, and
   lifetimes.
3. Complete the first milestone, then recover shared machinery (startup,
   relocation, calling convention, interrupt wrappers, resource interpreters).
4. Explain small complete behavioral slices. Do not accumulate owned but
   unexplained code.
5. Extend emulator or hardware work only when a named investigation needs it.

## Evidence rules

- File offsets, physical addresses, CPU `segment:offset` values, and runtime
  copies stay explicitly connected.
- Bytes acquire meaning through the instructions, tables, strings, resources,
  and other objects they belong to.
- A padding region needs an established purpose and boundary. Each padding
  byte does not need a separate explanation.
- Unknown hardware behavior is a named boundary, not an invented device
  model.
- A trace establishes what happened in that execution. Claims about all
  possible executions need additional reasoning.
- Automated names are proposals. They still need evidence.
- Tag claims `PROVEN`, `HYPOTHESIS`, or `UNDETERMINED`.
