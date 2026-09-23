# Named unknowns

Uncertainties that block dependent work. Ranked by how much they unlock.
A guess is not listed as a fact.

| ID | Unknown | Why it matters | What would close it |
|----|---------|----------------|---------------------|
| U-XA-LIVE | PGR after task 7’s two-level walks | Second table is live through task 7 select. D510’s eight callers do not `OUT`. The 61 direct-and-child walks have no `MOV DX` into `0xFF00-0xFF7E` | A third-level `B000:00DF` callee, or `OUT DX` whose `DX` is loaded from a register or memory in that window |
| U-AMX-WAIT | **Closed.** IVT[8] `D52A:0008` leaves a later `FB00:023A` idle | Tick word `[DI+12h]` starts at 10; the zero entry readies TCB 0 and `0194` enters `01EA`. Hooks stay null | See [`amx_wait.md`](amx_wait.md). Pin of slot 8 stays `U-V53A` |
| U-LC7981 | Meaning of `INT 43` AX=0 pairs and AX=4 AH=`0x0A`/`0x0B`/`0x0C` | Port writes are proven; controller state is not | LC7981 / HD61830 register manual applied to those exact pairs |
| U-C0XX | Board decode of `0xC000-0xC033` | BIOS and FAC0 program this window | Schematic or a tested PAL fusemap; MAME is a hypothesis |
| U-PGR61 | NVRAM record format / LC3517 identity | Window is `0x500000` (P7/P8). Consumer is `D9B5` `ES=0xF400`. Chip name is MAME commentary | Schematic, capture, or a caller that pins `CX` and the `0xAA`/`0x44` marker |
| U-COPY-7C92 | **Closed (D10).** DGROUP at `8010:0000`; directory + string pool + writable globals. Word `+2` and the `+0238` island meaning stay local UNDETERMINED / HYPOTHESIS. String *consumers* closed in D14 | - | See [`copy_7c92.md`](copy_7c92.md), [`string_scan.md`](string_scan.md) |
| U-AMX-POOL | Mailbox/pool record at `ES:[BX]` past `065B` zeroing | `065B`/`067C`/`06B9`/`06E8`/`0725` are the bulk of the public surface | A named slice that consumes one object (D11) |
| U-PANEL-ROM | Panel µPD78C10 image absent | Pad/button/dial path | Obtain the AM27C256 dump MAME names |
| U-PAL | IC25/IC29/IC31 18CV8 fusemaps | Memory and I/O decode | Readout or full schematic sheets |
| U-V53A | µPD70236 vs 70236A on this board | Interrupt-vector numbering and a few opcodes | Chip photo OCR; treat as V53-family until then |
| U-TE7774 | TE7774 register map | MIDI and panel IPC | Datasheet or a bounded I/O consumer study |
| U-PHYS | All glass/timer/IRQ timing | Cannot be closed in software | Deferred hardware captures; do not invent them |

Physical testing is deferred. These stay open. Software-verifiable work
continues around them.
