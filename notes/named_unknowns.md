# Named unknowns

Uncertainties that block dependent work. Ranked by how much they unlock.
A guess is not listed as a fact.

| ID | Unknown | Why it matters | What would close it |
|----|---------|----------------|---------------------|
| U-XA-LIVE | PGR after task 7 body (and later picker `OUT`s) | Second table is live through task 6 wait and task 7 select | Follow `B000:00DF` callees and `D510:008D` callers for `OUT` to `0xFF00-0xFF7E` |
| U-AMX-WAIT | Which IRQ or hook leaves a later `FB00:023A` idle | First `01EA` creates task 6; later empty-queue wake is open | Find an ISR that rewrites the `023A` frame, `JMP`s `01EA`/`0281`, or `RETF`s a TCB |
| U-LC7981 | Meaning of `INT 43` AX=0 pairs and AX=4 AH=`0x0A`/`0x0B`/`0x0C` | Port writes are proven; controller state is not | LC7981 / HD61830 register manual applied to those exact pairs |
| U-C0XX | Board decode of `0xC000-0xC033` | BIOS and FAC0 program this window | Schematic or a tested PAL fusemap; MAME is a hypothesis |
| U-PGR61 | Frame `0x40` ? `0x100000` | Not in the MAME program map | Consumer of linear page 61, or a decode document |
| U-COPY-7C92 | Grammar past the `AA 55` / string-pointer front of the `0x7C92` copy; later writers | Shared UI/resource object at RAM `0x380100` | Consumers of `8010:0000` after boot; alias and overwrite inventory |
| U-AMX-POOL | Mailbox/pool record at `ES:[BX]` past `065B` zeroing | `065B`/`067C`/`06B9`/`06E8`/`0725` are the bulk of the public surface | A named slice that consumes one object (D11) |
| U-PANEL-ROM | Panel µPD78C10 image absent | Pad/button/dial path | Obtain the AM27C256 dump MAME names |
| U-PAL | IC25/IC29/IC31 18CV8 fusemaps | Memory and I/O decode | Readout or full schematic sheets |
| U-V53A | µPD70236 vs 70236A on this board | Interrupt-vector numbering and a few opcodes | Chip photo OCR; treat as V53-family until then |
| U-TE7774 | TE7774 register map | MIDI and panel IPC | Datasheet or a bounded I/O consumer study |
| U-PHYS | All glass/timer/IRQ timing | Cannot be closed in software | Deferred hardware captures; do not invent them |

Physical testing is deferred. These stay open. Software-verifiable work
continues around them.
