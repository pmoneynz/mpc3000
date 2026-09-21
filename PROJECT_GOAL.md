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
debt until resolved. D19 is PARTIAL: the panel ROM is absent
([`notes/front_panel.md`](notes/front_panel.md)).
P7/P8: `D9B5` consumes page 61 (`ES=0xF400`) at 24-bit
`0x500000` (NVRAM window). Chip LC3517 stays HYPOTHESIS
([`notes/pgr61.md`](notes/pgr61.md)).
DGROUP `+0054` is a 101-slot pan-name table (`Pan:` /
`B354:01C6`), not pad labels ([`notes/pan_table.md`](notes/pan_table.md)).
D20 assign UI is `C44E:0119` / `D9F2` (`000C`/`003D`/`0072`).
ROM default `+0859` is `0x23`..`0x62`. `[E5F9]` selects a
`9770:` record that `BE1A:026C` titles `Pgm`. Param
`0..3` is `TUNING`/`DECAY`/`ATTACK`/`FILTER`.
`BE1A:0002` is `Assign '16 Levels'` (`[D6AD]` /
`[81B3]` `VELOCITY`/`NOTE VAR`; `Center pad:`
`[E613]` default `0x0D`). Task 3 `EAD0:000B`
consumes `[E614]` and `CALLF CFB3:0008` /
`CFC6:0007` (note `+2` / `02D6`/`033A`
slot / `+063E` / `[E639]`;
`FCF6+17=FD0D`; `+5`/`+3` note-floor;
`0007` `CALLN 039E` leftover indexes
`+7`/`+8` through `[E5F9]+FCF6`.
`D9C0:0006` is the same Param
`0..3` pair map as `BE1A`.
`DC2A:0033` / `DC85:0047` consume
`[81B3]==0`. `C20F:0478` leftover
walks `[E5F9]+SI*0x18+3E` for
`SI` `0..0x3F` to exclusive
`+063E`; sibling `0874`;
`0BBF` skips `[E60E]`, compares
`+3E` to `[BP+6]`, stores
`[BP+8]`, restores `CA45`;
`D0C0:0C9C` walks `FCF6` with
`CX` `0x348`..`0x930` and
`(FCF6+0x23*0x18)&0xFFFF=+3E`.
`BE1A:0131` stores NOTE VAR
Param to `FD0D` when
`[81B3]!=0`. `0105` `CALLN`
`0203` with the note then
reads `[81B3]`).
`CFB3` `0xC0` is `CA45:0008`; `0xF0`
is `D0AE:0002`. Leftover after that
`RETF` paints matching `D9F2:000C`
slots. `D9A2:0004`/`0031`/`005F`
store `[BP+8]` at the `02D6`/`033A`
far pointer `+0`/`+1`/`+2`;
`00C7`/`00E9`/`010C` read those
bytes. `BDF1:00E1` is `000C(0)`
into `[D6AD]`. Owned
`[D6AC]` writers are remaps, not pad-hit
([`notes/pad_note.md`](notes/pad_note.md)).

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
writable globals). The owner ledger covers 365870 proven bytes;
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
