# Service-manual chip inventory (OCR from mpc-tutor 16-page PDF)

Source PDF: 04-schematics-service/Akai_MPC3000_Service_Manual.pdf
OCR date: 2026-09-21 (box-local PT / Auckland)

## Confirmed markings (OCR; OCR noise corrected where obvious)

| Marking (service) | Role | Confidence |
|-------------------|------|------------|
| UP070236GD-16 / UP070236G0-16 (µPD70236) | Main CPU V53 | High — appears on CPU PCB parts |
| AM27C020-150DC ×2 | OS EPROM LS/MS | High |
| HM658512LP-85 ×2 | Work PSRAM | High |
| LC3517BSL-15 / LC3517BL-15 | Battery NVRAM | High |
| LC7981 | LCD controller | High |
| L7A1045 L6028 DSP-A | Audio DSP | High |
| MB89352A-P-G | SCSI SPC | High |
| TE7774 | Quad MIDI UART | High |
| UPD72069GF-3BA / UPO72069GF-38A | Floppy controller | High |
| UPD78C10AGQ-36 | Panel MCU | High (operation board) |
| AM27C256-150DC | Panel MCU EPROM | High |

## Specs page note
Service specs OCR: "CPU... V53/16 MHz" — conflicts with MAME 32 MHz XTAL; treat as unresolved (likely oscillator vs internal/CPU clock wording).

## Boards (from parts list)
- BA-L4012A020A PC CPU BLK MPC3000
- BA-L4012A030A AD/DA
- BA-L4012A040A/B Drum Pad
- BA-L4012A050A Operation
- BA-L4012A090A Jack
- Memory expansion related: BA-L6028A050A 2M-MEMORY (S3000 family part listed)

## Limitation
This 16-page PDF is primarily safety/specs/disassembly/parts — **schematic netlists/pages not present** in the free mpc-tutor scan. Need longer service package for address decoding PALs and bus diagrams.

---

## Update 2026-09-21 — high-res service PDF

Source: `Akai-MPC-3000-Service-Manual.pdf` (16 pp, ~19 MB). Same content class as the earlier 16-page PDF: **no schematics**. See `SERVICE_MANUAL_NOTES.md` for CPU BOM confirms (32 MHz XTAL, three 18CV8 PALs IC25/29/31).
