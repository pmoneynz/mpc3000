# Named unknowns

Uncertainties that block dependent work. Ranked by how much they unlock.
A guess is not listed as a fact.

| ID | Unknown | Why it matters | What would close it |
|----|---------|----------------|---------------------|
| U-XA-LIVE | Which PGR table is live after BIOS returns | Every later RAM/ROM citation depends on the active map | Trace writers of `0xFF00-0xFF7E` from `BRKXA 0x14` to the event loop |
| U-AMX-ENTRY | How KADAK AMX is started, and what its dispatcher waits on | First-milestone event loop | Find the consumer of file `0x7B00C` / the AMX header; static call/entry scan plus a later execution harness |
| U-INT43-AX4 | `INT 43` AX=4 path from a banner character to LC7981 memory | Whether the banner is an observed display write or only a string consumer | Finish the `0x79752` / `0x797CC` partition to `LCD_put` or a glyph blit |
| U-LC7981 | Meaning of the seven AX values used in `INT 43` AX=0 | LCD init is proven as port writes, not as controller state | LC7981 / HD61830 register manual applied to those exact pairs |
| U-C0XX | Board decode of `0xC000-0xC033` | BIOS and FAC0 program this window | Schematic or a tested PAL fusemap; MAME is a hypothesis |
| U-PGR61 | Frame `0x40` ? `0x100000` | Not in the MAME program map | Consumer of linear page 61, or a decode document |
| U-COPY-7C92 | Object grammar of the `DS=A000` ? `ES=8010` copy | Likely the relocated OS body | Bounds, entry points, and consumers of RAM `0x380100` |
| U-PANEL-ROM | Panel µPD78C10 image absent | Pad/button/dial path | Obtain the AM27C256 dump MAME names |
| U-PAL | IC25/IC29/IC31 18CV8 fusemaps | Memory and I/O decode | Readout or full schematic sheets |
| U-V53A | µPD70236 vs 70236A on this board | Interrupt-vector numbering and a few opcodes | Chip photo OCR; treat as V53-family until then |
| U-TE7774 | TE7774 register map | MIDI and panel IPC | Datasheet or a bounded I/O consumer study |
| U-PHYS | All glass/timer/IRQ timing | Cannot be closed in software | Deferred hardware captures; do not invent them |

Physical testing is deferred. These stay open. Software-verifiable work
continues around them.
