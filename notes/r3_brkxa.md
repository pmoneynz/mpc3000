# R3 — `BRKXA` at file `0x7AC1C`

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

Do not mark R3 done. The byte check below is satisfied. Remaining R3
work is the standing rule: Ghidra is navigation, not evidence.

---

## File `0x7AC1C`

Re-read linear bytes: `0F E0 11`.

| Field | Value |
|-------|-------|
| File | `0x7AC1C` |
| Bytes | `0F E0 11` |
| `CS:IP` | `FAC0:001C` |
| 20-bit | `0xFAC1C` (`(CS<<4)+IP`) |
| PGR/XA | **XA=0** at this fetch (first `BRKXA`; PGR already programmed). 24-bit translate is not applied |
| Decode | `tools/v53_decode.py` `decode_one`: kind `BRKXA`, text `BRKXA 0x11`, length 3 |

Immediate: opcode `0F E0` (`BRKXA`); **imm8** vector `0x11`, unsigned,
not sign-extended. No ModR/M. No GPR write from opcode or ModR/M.

Not a Jcc: no branch polarity. Vector fetch is `IVT[0x11]`. Re-read
file `0x00044`: `1F 00 C0 FA` = IP imm16 `0x001F` + CS imm16 `0xFAC0`
(neither sign-extended) → `FAC0:001F`.

`0F F0` is **not** at `0x7AC1C`. Re-read file `0x7AC9F`: `0F F0 12`.
`decode_one(FAC0:009F)` kind `RETXA`, text `RETXA 0x12`. Opcode `0F F0`;
**imm8** unsigned `0x12`; no ModR/M; no GPR write.

## Unittest already locks these bytes

`tests.test_boot_slice`:

- `test_brkxa_continue_in_place` asserts `image[0x7AC1C:0x7AC1F] == 0F E0 11` and IVT `[0x44:0x48] == FAC0:001F`.
- `test_v53_decode_brkxa_retxa` asserts `decode_one(FAC0:001C)` kind `BRKXA` / `BRKXA 0x11`, and `decode_one(FAC0:009F)` kind `RETXA` / `RETXA 0x12`.

`tools/verify_boot_slice.py` also appends check `BRKXA 0x11` for the
same three bytes.

**PROVEN:** R3’s decode check is satisfied. Remaining R3 work is “do
not treat Ghidra as evidence,” a standing rule, not an open code task.
