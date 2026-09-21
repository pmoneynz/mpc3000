# AKAI MPC3000 — OS ROM interpretation research pack

**Canonical goal:** [`PROJECT_GOAL.md`](PROJECT_GOAL.md) — reconstruct a
complete, testable model of **Vailixi OS 3.50**, with every ROM byte
connected to that model.

Current slice: [`notes/boot_reset_to_bios_banner.md`](notes/boot_reset_to_bios_banner.md).
Work queue: [`TODO.md`](TODO.md). Start here: [`GETTING_STARTED.md`](GETTING_STARTED.md).

Collected for Peter Wadams.

**Delivery status (box):** tree is complete under `/workspace/mpc3000-docs/`. Executor subagent lacked `GetDynamicTools`/`CopyFromBox`/`ListMachines` (cursor namespace MCP not exposed). Parent must `CopyFromBox` → `/Users/peterwadams/Documents/MPC3000/` (machineId `eb8a6940-1b53-453e-991f-1565b5bc76a9`). Technical index of silicon, datasheets, service docs, and MAME reverse-engineering sources useful for decoding the MPC3000 Operating System ROM (memory map, IRQ, timers, I/O, IPC).

**Do not invent chip IDs.** Confirmed vs suspected are separated below. Sources: Akai service parts list (mpc-tutor PDF), MAME `mpc3000.cpp` (Belmont et al.), studiorepair CPU PCB photo captions, owners manual marketing text (clock claims vary — see notes).

---

## 1. Confirmed architecture

### Main CPU (CONFIRMED)
| Item | Value | Evidence |
|------|-------|----------|
| Part | **NEC µPD70236 (V53)** — service marking `UP070236GD-16` / `UP070236G0-16`; MAME device **V53A** | OCR of service parts list; MAME `V53A`; specs page “V53/16 MHz” vs MAME 32 MHz XTAL (gap) |
| Clock | **32 MHz XTAL** in MAME; `CLKOUT = XTAL/2`, `PCLKOUT = XTAL/4` | `mpc3000.cpp` machine_config |
| ISA | 8086-compatible (V33/V33A core lineage); object-compatible with V20/V30 class | NEC V-Series databook |
| On-die peripherals | **8237-compatible DMA**, **8254-compatible PIT**, **8259-compatible PIC**, UART, DRAM refresh | NEC V53 databook + MAME |

### Secondary / panel CPU (CONFIRMED)
| Item | Value | Evidence |
|------|-------|----------|
| Part | **NEC µPD78C10AGQ** @ **12 MHz** | MAME; ROM `mp3000__op_v1.0.am27c256…ic602.bin` |
| Role | Front panel / pad / dial scan; TxD wire-OR into TE7774 RX channels 2 & 3 | MAME IRQ/UART wiring comments |

### Audio DSP (CONFIRMED)
| Item | Value | Evidence |
|------|-------|----------|
| Part | **L7A1045 L6028 DSP-A** (QFP120; “L6028” on Akai schematics) | Service parts IC28; MAME `l7a1045` |
| Clock | **33.8688 MHz** | MAME (schematic-verified comment) |
| Sample bus | 16-bit data, **24 address bits** → 32 MiB sample space (MAME maps 32 MiB RAM window) | MAME header |

### Other confirmed peripherals
| Function | Part | Notes |
|----------|------|-------|
| OS EPROM | **AM27C020** ×2 (LS/MS interleaved) | Service IC13/IC14; MAME ROM_SKIP(1) interleave |
| Work RAM | **HM658512** ×2 (512K×8 PSRAM) @ `0x300000–0x3FFFFF` | MAME map comment; service IC15/IC16 |
| NVRAM | **LC3517** 2K×8 battery-backed @ `0x500000–0x500FFF` | MAME nvram comment |
| Floppy | **µPD72069** | DMA ch1; IRQ3 OR |
| SCSI | **MB89352** (Fujitsu SPC) | DMA ch0; IRQ3 OR; I/O `0x00A0–0x00BF` |
| MIDI UART | **TE7774** quad UART | I/O `0x00C0–0x00DF`; IRQ4/5/7 |
| LCD | **LC7981** (HD61830-compatible in MAME) | I/O `0x00E0` data, `0x00E2` status/control |
| Sync timers | External **PIT8254 / MB89254** @ I/O `0x00F0–0x00F7` | Separate from V53 on-die timers |
| GPIO expanders | **I8255 / MB89255B** ×2 (`dioexp`, `adcexp`) | `0x0080`, `0x00F8` |
| LED latches | **HC259** ×2 | I/O `0x0000`, `0x0020` |
| PCB | CPU board **L4012A5010** | studiorepair.com |

### Suspected / unverified
- Exact **µPD70236 vs µPD70236A (V53A)** marking on every board revision — MAME uses V53A; service OCR shows `UP070236G0-16`. Treat as V53-family until a clear chip photo is OCR’d.
- Owners manual “16 MHz V53” vs MAME **32 MHz XTAL** — likely bus/CPU vs oscillator distinction; **do not assume** without schematic confirmation.
- DMA channel 2 → “IC31” (direct-audio stream?) — MAME comment only; part not fully identified here.
- **TE7774** manufacturer docs — scarce in public free archives (gap).
- Full **multi-page schematic set** — free mpc-tutor PDF is **16 pages**, appears parts/disassembly heavy; schematics may live in a longer service package (Scribd / ManualsLib / physical).

---

## 2. Memory map (from MAME — primary OS ROM reference)

### CPU program space
| Range | Size | Contents |
|-------|------|----------|
| `000000–07FFFF` (+ mirror `080000`) | 512 KiB | Interleaved OS ROM (2× AM27C020) |
| `300000–3FFFFF` | 1 MiB | Work RAM (2× HM658512) |
| `500000–500FFF` | 4 KiB window (2 KiB device) | Battery NVRAM (LC3517) |

### I/O space (16-bit bus, many 8-bit umask)
| Ports | Device | OS relevance |
|-------|--------|--------------|
| `0000` / `0020` | HC259 LED latches | Panel LEDs |
| `0060–006F` | L7A1045 DSP regs | Sample engine / IPC-ish DMA |
| `0080–0087` | 8255 dioexp | Digital I/O |
| `00A0–00BF` | MB89352 SCSI | Disk / SCSI |
| `00C0–00DF` | TE7774 UART×4 | MIDI + panel IPC path |
| `00E0` / `00E2` | LC7981 LCD | Display |
| `00E8–00EB` | µPD72069 FDC (+ HC365 status high byte) | Floppy |
| `00F0–00F7` | PIT8254 synctmr | External sync/tempo timers |
| `00F8–00FF` | 8255 adcexp | ADC / control |

### Interrupt delivery (MAME wiring)
| Line | Source |
|------|--------|
| IRQ0–2 | V53 on-die timer TOUT0–2 |
| IRQ3 | FDC **OR** SCSI |
| IRQ4 | TE7774 any TXRDY |
| IRQ5 | TE7774 RXRDY1\|2\|3 |
| IRQ6 | SMPTE sync in |
| IRQ7 | TE7774 RXRDY4 |
| DMA0 | SCSI |
| DMA1 | FDC |
| DMA2 | IC31 (unverified) |
| DMA3 | L7A1045 DSP |
| TCLK | 4 MHz (MAME FIXME: DAWCK from DSP; also DSR) |

### Panel IPC
Panel µPD78C10 **TxD** → TE7774 **RX2 & RX3** (wire-OR). MIDI IN1/IN2 → RX1/RX2; MIDI OUT1–4 ← TXD1–4. This is the main documented CPU↔panel path.

---

## 3. Files collected

### `01-cpu/`
| File | Source | Covers |
|------|--------|--------|
| `NEC_1991_16bit_V-Series_Microprocessor_Data_Book.pdf` | bitsavers via Wayback (`1991_16_bit_V-Series_Microprocessor_Data_Book.pdf`) | **V53/µPD70236**: ISA, DMA, timers, IRQ controller, memory/bus — **primary CPU manual** |
| `Intel_8259A.pdf` | MIT 6.828 reading | 8259-compatible PIC behaviour (V53 on-die analogue) |

### `02-memory/`
| File | Source | Covers |
|------|--------|--------|
| `Hitachi_HM658512A_PSRAM_datasheet.pdf` | ardent-tool.com mirror | Work RAM timing/refresh (decoding @ `0x300000`) |

### `03-peripherals/`
| File | Source | Covers |
|------|--------|--------|
| `NEC_uPD78C10_summary.pdf` | datasheets.chipdb.org | Panel MCU summary (ports, A/D, serial) |
| `NEC_1990_MCU_Data_Book.pdf` | archive.org bitsavers item `bitsavers_necdatabooMicrocontrollerDataBook_57118308` | **Full µPD78C10** family databook (ISA, interrupts, serial, A/D) — panel IPC |
| `Fujitsu_1989_SCSI_Product_Guide.pdf` | bitsavers mirror (meulie) | MB89352 feature context (async SPC) |

### `04-schematics-service/`
| File | Source | Covers |
|------|--------|--------|
| `Akai_MPC3000_Service_Manual.pdf` | https://www.mpc-tutor.com/files/mpc-service-manual/MPC3000_ServManual.pdf | Official Akai service: safety, specs, disassembly, **parts list** (chip IDs). **16 pages**; scanned; **full schematic sheets not confirmed in this PDF** |
| `OCR_chip_inventory.md` | tesseract OCR of above PDF | Confirmed markings: µPD70236, AM27C020, HM658512LP-85, LC3517, LC7981, L7A1045, MB89352A, TE7774, µPD72069, µPD78C10AGQ-36, AM27C256 |

### `05-community-re/`
| File | Source | Covers |
|------|--------|--------|
| `egasimus_mpcemu_README.md` | github.com/egasimus/mpcemu | Independent V53 emulator notes (MPC2000XL/3000 interest); attributed community |

### `06-mame/` (BSD-3-Clause MAME sources — **no ROM binaries**)
| Path | Upstream | Role |
|------|----------|------|
| `driver/mpc3000.cpp` | `src/mame/akai/mpc3000.cpp` | Full machine: maps, IRQ/DMA hooks, ROM_LOAD metadata |
| `driver/mpc3000.lay` | `src/mame/layout/mpc3000.lay` | Front-panel layout |
| `MAME_MPC3000_maps_irqs_roms.md` | Extracted from driver | Quick reference maps/IRQs/ROM hashes |
| `cpu/v5x.{h,cpp}` | `devices/cpu/nec/` | V53/V53A device |
| `cpu/nec.{h,cpp}` | `devices/cpu/nec/` | NEC core |
| `cpu/upd7810.{h,cpp}` | `devices/cpu/upd7810/` | Panel MCU |
| `sound/l7a1045_l6028_dsp_a.{h,cpp}` | `devices/sound/` | Audio DSP |
| `machine/te7774.{h,cpp}` | `devices/machine/` | Quad MIDI UART |
| `machine/mb87030.{h,cpp}` | `devices/machine/` | Fujitsu SPC family (MB89352) |
| `machine/upd765.{h,cpp}` | `devices/machine/` | FDC family (µPD72069) |
| `machine/i8255.{h,cpp}`, `pit8253.{h,cpp}`, `74259.{h,cpp}` | `devices/machine/` | PPI / PIT / LED latch |
| `video/hd61830.{h,cpp}` | `devices/video/` | LCD (LC7981 stand-in) |

**MAME status:** `MACHINE_NOT_WORKING`. Useful for OS ROM work even when audio/UI incomplete — maps and IRQ comments are high-value.

#### Expected ROM files (Peter collects; hashes from MAME `ROM_LOAD`)
**Main CPU** region `0x80000`, interleaved odd/even (`ROM_SKIP(1)`):

| BIOS | Files | CRC32 | SHA1 |
|------|-------|-------|------|
| 3.12 (default) | `mpc312ls.bin` / `mpc312ms.bin` | `d4fb6439` / `80ee0ab9` | `555d388e…` / `b8855118…` |
| 3.50 vailixi | `3.50 vailixi lse.bin` / `… mso.bin` | `9f3031b5` / `e62ebb26` | `c270a92f…` / `f6d08048…` |
| 3.11 | `mpc311ls.bin` / `mpc311ms.bin` | `5a272061` / `a8e177de` | `87cc8aef…` / `b63a5c27…` |
| 3.10 | `mpc3000__ls__v3.10.am27c020__id0197.ic13_ls.bin` / `…ic14_ms.bin` | `cbd1b3a6` / `e2ba1904` | `5464a571…` / `27a9f047…` |

**Panel:** `mp3000__op_v1.0.am27c256__id0110.ic602.bin` — CRC `b0b783d3` SHA1 `a6001618…` (32 KiB).

---

## 4. Gaps / next lookups

1. **Full schematic sheets** — free 16-page service PDF likely incomplete for decoding. Candidates: ManualsLib (Akai MPC3000 service, ~58 pp listings), **Scribd** `https://www.scribd.com/document/1073873672/MPC3000-Service-Manual` (Peter has account — use if free sources fail), physical Akai service binder.
2. **AM27C020 datasheet PDF** — free curl mirrors returned HTML/403; get from AMD memory databook / all-datasheet once browser download works.
3. **LC3517**, **µPD72069**, **TE7774**, **LC7981** dedicated datasheets — not freely downloaded yet; LC7981 ≈ HD61830; 72069 ≈ 765-class FDC.
4. **Intel 8254 + 8237** datasheets — 8259 collected; 8254/8237 still needed for on-die timer/DMA programming model.
5. ~~NEC 1990 MCU Data Book~~ — **collected** as `03-peripherals/NEC_1990_MCU_Data_Book.pdf`.
6. **L7A1045** — no public manufacturer datasheet found; rely on MAME device + any schematic register map.
7. **Clock reconciliation** — confirm 32 MHz XTAL vs “16 MHz” marketing from schematic oscillator section.
8. **IC31 / DMA2** identity from schematic.
9. **PAL/GAL fusemaps** — service lists `18CV8` devices (decoding); JEDEC dumps if available from community (not collected).

---

## 5. How to use this for OS ROM work

1. Disassemble interleaved LS/MS EPROM pair as little-endian 16-bit V53 code starting at reset vector (V53/8086-style).
2. Cross-check absolute data accesses against `0x300000` RAM and `0x500000` NVRAM.
3. Trace `IN`/`OUT` to I/O map above; MIDI traffic via TE7774; panel messages via UART ch2/3.
4. Timer ISRs: distinguish **on-die** TOUT→IRQ0–2 vs **external** PIT @ `0xF0`.
5. Disk paths: FDC `0xE8` + SCSI `0xA0` sharing IRQ3 — check ISR demux.
6. Sample engine: DSP regs `0x60` + DMA3; wavedata not in CPU map.


---


## ★ OS 3.16 maintenance upgrade (floppy-load)

**Important:** [`07-rom/v3.16 maintenance upgrade/`](07-rom/v3.16%20maintenance%20upgrade/) is a **floppy-bootable RAM OS** (`M3K316.SYS`), **not** an EPROM image.

- Loads from FDD at power-on; **not permanent** (cleared on power-off)
- Distinct from the burned LS/MS ROM sets (3.08 / 3.11 / 3.12 / Vailixi 3.50)
- Full notes: [`07-rom/v3.16 maintenance upgrade/README.md`](07-rom/v3.16%20maintenance%20upgrade/README.md)

## 7. ROM binaries (`07-rom/`)

Peter supplies binaries. Inventory: [`07-rom/ROM_INVENTORY.md`](07-rom/ROM_INVENTORY.md).

**MAME-matched OS dumps:** Vailixi 3.50, stock 3.11, stock 3.12 (LS+MS).  
**Also present:** v3.08 (full size, not in MAME set).  
**Also:** floppy OS 3.16 (`v3.16 maintenance upgrade/`) — RAM boot, not EPROM.

**Still missing:** panel MCU ROM (32 KiB).

### Service manuals (`04-schematics-service/`)

High-res 16-page parts manual is in place (`Akai-MPC-3000-Service-Manual.pdf`). Notes: [`04-schematics-service/SERVICE_MANUAL_NOTES.md`](04-schematics-service/SERVICE_MANUAL_NOTES.md).

**Still missing:** multi-page schematic sheets + 18CV8 fusemaps (IC25/29/31).

## 8. Operator's Manual (`08-operators-manual/`)

Official **Operator's Manual** — software **v3.0**, Roger Linn / Akai, May 1994 (276 pp).

- PDF: [`08-operators-manual/Akai_MPC3000_Operators_Manual_v3.0.pdf`](08-operators-manual/Akai_MPC3000_Operators_Manual_v3.0.pdf)
- Notes: [`08-operators-manual/README.md`](08-operators-manual/README.md)

User-facing OS behaviour reference for ROM interpretation (disk formats, MIDI, SCSI, menus). Complements hardware docs; does not include schematics.

## 9. Internals photos (`09-internals-photos/`)

Studio Repair gallery teardown photos (Nikolaus Riehm) — **24 slide-size JPGs** (~822×622), highest resolution published on the site.

- Source: http://studiorepair.com/gallery/Akai/MPC3000/index.html
- Index + captions: [`09-internals-photos/README.md`](09-internals-photos/README.md)
- Includes CPU board close-ups (L7A1045 DSP, TE7774 USART, µPD72069 FDC, LC7981), panel/ADC/DAC/SCSI/sample RAM boards

