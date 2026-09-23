# D11 gate — no owned port/RAM `065B` consumer

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-22.

**PROVEN:** D11 stays `[ ]`. Walk of every owner-ledger `code` range
(710 ranges, 131128 bytes) with `tools/v53_decode.py` `decode_one` found
no `IN`/`OUT` of port `0x065B` and no direct memory operand `[0x065B]`.
Do not name hardware for this location.

Reproduction: `python3 tools/v53_decode.py` (imported); ledger read-only.

---

## Search (owned code only)

| Form | Encoding check | Hits |
|------|----------------|------|
| `IN`/`OUT` imm8 | `E4`–`E7` + imm8. Port is 8-bit, unsigned, not sign-extended. Port `0x065B` cannot appear. Port `0x5B` also 0 | 0 |
| `MOV DX,0x065B` then `IN`/`OUT DX` | `BA` = `B8+2` writes **DX** (opcode register field, no ModR/M). imm16 `5B 06` = `0x065B`, not sign-extended. `EC`/`ED`/`EE`/`EF` encode no port | 0 `BA 5B 06` |
| moffs16 `[0x065B]` | `A0`–`A3` + disp16. disp16 unsigned `5B 06`. Writes `AL`/`AX` (`A0`/`A1`) or memory (`A2`/`A3`) | 0 |
| ModR/M `[disp16]` | `_has_modrm` and `mod=00 r/m=110`; disp16 unsigned `0x065B` | 0 |

No Jcc was used as a `065B` consumer. No branch-polarity claim.

## Far-call immediate is a different operand

Sixteen owned `CALLF` sites are `9A 5B 06 00 FB`. Re-read
`B03B:001E` file `0x303CE`: `9A 5B 06 00 FB`. Opcode `9A` `CALLF`;
imm16 IP = `0x065B` (not sign-extended); imm16 CS = `0xFB00` (not
sign-extended); no ModR/M; no GPR write. Kind `CALLF`, text
`call FB00:065B`. Same five bytes at `FB81:0076` file `0x7B886`.

That is the AMX mailbox-init *entry* `FB00:065B`, not port `0x065B`
and not RAM `[0x065B]`. It does not consume `U-AMX-POOL`.

## Gate

D11 stays blocked: no named slice consumes port or RAM `065B` /
`U-AMX-POOL`. Do not call that hardware.
