# Front-panel navigation (D19)

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Marks D19 **PARTIAL**. The panel µPD78C10 is not on the V53 program
bus. Its AM27C256 is absent (`U-PANEL-ROM` / P1). No owned V53
consumer has been shown to decode a panel message. Button, dial,
and mode-key meaning stay unnamed.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the software boundary for front-panel navigation |
| Observable | None on this tree. No panel frame is recovered from Vailixi 3.50 |
| Inputs | Missing AM27C256 (`subcpu`, MAME SHA-1 `a60016184fc07ba00dcc19ba4da60e78aceff63c`) |
| Outputs | No owned writer of a panel scan code is established |
| Confidence | ROM absence **PROVEN**. V53 `0xC0-0xDF` I/O sites **PROVEN** as encodings. Device and bit meaning **UNDETERMINED** (`U-TE7774`). MAME RX2/RX3 wiring **HYPOTHESIS** |
| Hardware deferred | Panel dump, pad/button/dial scan, wire capture (`U-PANEL-ROM`, `U-PHYS`, P5) |

---

## 1. What is on this bus

The V53 linear image does not contain panel MCU code. That is a
separate 32 KiB EPROM. File search under `07-rom/` for the MAME
`ic602` / `op_v1` names is empty. **PROVEN.**

DGROUP `+0054` .. `+01E4` is a 101-slot pan-name table
(`50L` .. ` C ` .. `50R`). `B354:01C6` prints one indexed name.
One caller passes the title `Pan:`; three others pass a different
title ([`pan_table.md`](pan_table.md)). It is not a pad-hit
path and not a navigation state machine.

---

## 2. V53 I/O in `0xC0-0xDF`

Owned code has immediate `IN`/`OUT` in that window. Specimens:

| CS:IP | File | Bytes | Port |
|-------|------|-------|------|
| `B03B:00F3` | `0x304A3` | `E6 C2` | `OUT 0xC2,AL` |
| `B03B:011F` | `0x304CF` | `E6 CA` | `OUT 0xCA,AL` |
| `B03B:014B` | `0x304FB` | `E6 D2` | `OUT 0xD2,AL` |
| `B03B:0177` | `0x30527` | `E6 DA` | `OUT 0xDA,AL` |
| `D547:0077` | `0x554E7` | `E4 D2` | `IN AL,0xD2` |
| `D547:0087` | `0x554F7` | `E4 C2` | `IN AL,0xC2` |
| `D547:009A` | `0x5550A` | `E4 CA` | `IN AL,0xCA` |

`B03B:000A` uses `OUT DX,AL` after `MOV DX` of `0x00C2`, `0x00C4`,
`0x00C6`, `0x00CA`, `0x00CC`, `0x00CE`, `0x00D2`, `0x00D4`, `0x00D6`,
`0x00DA`, `0x00DC`, and `0x00DE`. It returns at `01D9` (file
`0x30589`) and does not `IN` those ports. `B03B:01DA` then does
`IN AL,DX` after `MOV DX` of `0x00C0`, `0x00C8`, `0x00D0`, and
`0x00D8`. `D5DD` and `DCF0` have further `DX` sites in the same
window. **PROVEN** as encodings.

These ports are the named `U-TE7774` window. Which site is MIDI
versus panel IPC, and every bit, stay **UNDETERMINED**. Do not
read MAME RX2/RX3 as a Vailixi fact
([`address_model.md`](address_model.md)).

`0xC000-0xC033` is the relocated V53/board window (`U-C0XX`), not
this 8-bit range.

---

## 3. Missing observation

1. The AM27C256 dump MAME names `mp3000__op_v1.0…ic602.bin`.
2. One captured panel IPC frame on the wire (P5).
3. A named V53 consumer that parses that frame into a navigation
   event.

The MAME `mpc3000()` key matrix names the panel rows the missing
ROM would scan. It includes no key called Cancel. The matrix is
the driver’s model. It is not the AM27C256 image and not a
captured frame. D19 stays `[PARTIAL]`.

Until those exist, front-panel navigation cannot be a complete
slice. D20 assign UI and the owned `[D6AC]` remaps are named
(`C44E:0119` / [`pad_note.md`](pad_note.md)); the pad-hit
writer of `[D6AC]` is not.

D11 stays gated. Mailbox/pool objects are not promoted from this
boundary.
