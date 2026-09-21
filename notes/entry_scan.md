# Entry-candidate scan

**Image:** Vailixi OS 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D15. A transfer consumer, not a `9A`/`EA` encoding, establishes
an entry. Whole-image candidates stay suspects until investigated.
Following every exit is [`transfer_scan.md`](transfer_scan.md) (D16).

Reproduction: `python3 tools/entry_scan.py --write` then
`python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name every established entry and keep raw far encodings as suspects |
| Observable | 143 unique `CS:IP`; 6154 `9A`; 825 `EA`; two pinned lookalikes |
| Inputs | Reset, ROM IVT, `F07A`, create-table, reset-path IVT, AMX public, `PUSH DS`+far |
| Outputs | `analysis/entry_scan.json` |
| Confidence | Named consumers and lookalikes **PROVEN**. Remaining `9A`/`EA` **UNDETERMINED** as instructions |
| Hardware deferred | None |

File offset is `(CS<<4+IP)&0x7FFFF` (same wrap as `D9BD:0009` ->
`0x59BD9`). 20-bit is `CS<<4+IP`. 24-bit follows the live PGR.

---

## 1. Encoding is not an entry

The image has 6154 `9A` and 825 `EA` bytes. D8 already treated the
raw `9A` count as a lookalike hypothesis. D15 investigates two
owned-code hits that are **not** transfers:

| File | Bytes | Real instruction |
|------|-------|------------------|
| `0x7FF01` | `EA FF B8 07 00` | `FFF0:0000` `MOV DX,0xFFEA` (`BA EA FF`). The `EA` is the port immediate |
| `0x797A7` | `9A 00 C3 A1 AB` | `F800:17A6` `CALL 1843` (`E8 9A 00`). The `9A` is the rel16 low byte |

**PROVEN.** A decoder aimed at the `9A`/`EA` byte invents `CALL ABA1:C300`
and `JMP 0007:B8FF`. `ndisasm` will do the same. Do not accept that
stream.

---

## 2. Established consumers

143 unique `CS:IP` (148 records; a few IPs are reached more than one
way). Every row has a transfer consumer.

| Consumer | n | What reaches it |
|----------|--:|-----------------|
| Reset / stub / FAC0 / ROM IVT / `FAC0:019E` | 7 | CPU reset, `BRKXA`/`RETXA`, `JMPF B000:00DF` |
| `F07A` init table | 3 | `FAC0:0134` walker |
| Create-table `FB76:0002` | 8 | AMX `0240` |
| AMX public `9A iw 00 FB` | 19 | 76 sites; unique CS=`FB00` pattern (D6) |
| AMX internals | 10 | Near flow from `FB00:000C` (`013E`, `01EA`, idle, create, …) |
| Reset-path IVT named slots | 17 | Last writer through `B03B:000A` (D5). 219 other slots are `F800:1952` |
| INT 43 near table | 8 | `F800:16AA` AX dispatch |
| BIOS helpers | 5 | Walker `1875`, hex `1896`, `18CA`, `19B3`, cursor/`LCD_put` |
| Shared app (`E937`, `B060`, `D9B5:0045`) | 3 | Create-table / task-6 consumers (D7/D8) |
| `PUSH DS` / `PUSH imm16` / `CALL FAR` | 67 | 1409 sites; every target is `55 8B EC`. Top: `B1B1:005B` (406) |

`PUSH DS`+far is the same five-byte tail as D14’s string pass, without
requiring the immediate to be a C-string. All 67 targets are far cdecl
entries. Their *bodies* stay D16 except `B1B1:005B` and `D9B5:0045`,
already owned.

Specimens:

| CS:IP | File | Consumer |
|-------|------|----------|
| `FFFF:0000` | `0x7FFF0` | reset vector |
| `FAC0:0000` | `0x7AC00` | stub `JMPF` |
| `B000:00DF` | `0x300DF` | `FAC0:019E` and create[7] |
| `D9BD:0009` | `0x59BD9` | create[6] |
| `FB00:013E` | `0x7B13E` | AMX start |
| `B1B1:005B` | `0x31B6B` | `PUSH DS`+far |

---

## 3. Later plants, not reset-path entries

`9A 47 03 00 FB` (`CALL FB00:0347`) also at `0x305B8` (`B03B:0208`,
`DL=9`) and `0x7B9B8` (`FB00:09B8`, `DL=8`). D5 listed these. They
are real CALLF sites. They are not the resting IVT after `B03B:000A`.
Slot-9 first ready stays UNDETERMINED.

---

## 4. What stays suspect

- The other ~6000 `9A` and ~800 `EA` bytes, including hits in app ROM
  that land in padding or on `0xFF`.
- Far-pointer runs that are not `F07A`, the create-table, the INT 43
  near table, or a proven `8010` data directory (D10/D14).
- Task-7 callee *bodies* past the owned `9A` sites (`DDF4`, `BDF1`,
  `E521`, …). The CALLF encodings in `[0x300DF, 0x301A7)` are
  instructions; the callees are entries only once that site is
  decoded from `B000` (D7 already named them). D16 follows them.

---

## Byte ownership

No new range. D15 is an inventory over entries already opened or
left as gap debt. `B1B1:005B` stays
[`string_scan.md`](string_scan.md).

---

## What this note does *not* prove

- Every exit from the 143 entries (closed in [`transfer_scan.md`](transfer_scan.md)).
- That a `55 8B EC` target is a complete function.
- Instruction bounds for unowned `PUSH DS`+far bodies.
- IRQ pin identity for IVT slots (`U-V53A`).
