# JEV classification of the unowned gaps

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-23.

JEV is TypeSafe's System One model. It is not a program in this
tree. The call is `POST https://api.typesafe.ai/v1/systemone` with
`model` `jev-latest`, as named in
[`prompts/rom_freespace_eval.md`](../prompts/rom_freespace_eval.md)
and [`.agents/skills/typesafe-ai/SKILL.md`](../.agents/skills/typesafe-ai/SKILL.md).
The response model on every call was `jev-1.13.0`. Requests and
responses, with the key absent, are under `build/jev_classify_*.json`,
`build/jev_rejudge_*.json`, and `build/jev_procedure_*.json`.

This note does not own bytes and has no Byte-ownership rows.

---

## What was measured

Ledger re-read: 986 ranges, 379868 owned bytes, 132 gaps, 288
Byte-ownership rows. The 132 gaps are 144420 bytes.

**PROVEN:** 131 gaps are not all `0xFF`. The longest `0xFF` run
inside any of those 131 is under 4. Every gap overlaps at least one
ROM window of the three stored PGR tables. `XA=0` can still address
every file byte through the ROM mirror. That mirror is not an
installed PGR page.

**PROVEN:** one gap is a single `0xFF`. File `0x5964F`,
`D90C:058F`, 20-bit `0xD964F`, 24-bit `0xD964F`. Second PGR slot 54,
word `0x0036`, file `0x7AD20`, bytes `36 00`, XA=1.
`0x0036 << 14 | (0xD964F & 0x3FFF) = 0xD964F`. Neighbors, re-read:
`C5 EF 9D C3` then `FF` then `55 8B EC FC`. Both neighbors are owned
code. It is one byte, so it fails the 16-byte rule. The ledger
already leaves this byte a gap. It is not owned.

**PROVEN:** an instruction-aligned walk from established entries,
switch destinations, and bounded callees found 13 distinct direct
`CALLF` / `CALLN` sites into 7 gaps, and 0 instruction fetches inside
a gap. The walk does not enter `CALL` or `JMPF`. Memory-operand
translation was not run. A zero count is not an all-paths unread claim.

`CA9B:01C5`, file `0x4AB75`, 20-bit `0xCAB75`, 24-bit `0xC8B75`,
second PGR slot 50 word `0x0032` at file `0x7AD18` (bytes `32 00`,
XA=1). Re-read `E8 D6 00`. Opcode `E8` is `CALLN`, disp16 `+0x00D6`,
no ModR/M, writes no GPR. Next IP `0x01C8`, target IP `0x029E`
(`CA9B:029E`, file `0x4AC4E`). `CA9B:0241`, file `0x4ABF1`, re-read
`E8 5A 00`, disp16 `+0x005A`, next IP `0x0244`, same target `0x029E`.

The other eleven sites, `bytes_hex` from `decode_one`:

| From | Bytes | Target | Target file |
|------|-------|--------|-------------|
| `C425:014A` | `9a080009b5` | `B509:0008` | `0x35098` |
| `C425:017B` | `9a0c007cb7` | `B77C:000C` | `0x377CC` |
| `C425:01E2` | `9a0c00f9bc` | `BCF9:000C` | `0x3CF9C` |
| `C425:016B` | `9a040087c8` | `C887:0004` | `0x48874` |
| `C425:01A6` | `9a09004cc8` | `C84C:0009` | `0x484C9` |
| `BE1A:0354` | `9aac0987c8` | `C887:09AC` | `0x4921C` |
| `C425:013A` | `9a5702c7ca` | `CAC7:0257` | `0x4AEC7` |
| `C425:0155` | `9a020075cd` | `CD75:0002` | `0x4D752` |
| `C425:018B` | `9a060081cc` | `CC81:0006` | `0x4C816` |
| `C425:01EC` | `9a0b007ace` | `CE7A:000B` | `0x4E7AB` |
| `DCA2:000F` | `9a4000f2da` | `DAF2:0040` | `0x5AF60` |

`C425:016B` is file `0x443BB`, 20-bit `0xC43BB`, 24-bit `0xC43BB`.
Second PGR slot 49, word `0x0031`, file `0x7AD16`, bytes `31 00`,
XA=1. Re-read `9A 04 00 87 C8`: `CALLF` `C887:0004`. Target 20-bit
`0xC8874`, file `0x48874`, 24-bit `0xC8874`, slot 50 word `0x0032`
at `0x7AD18`, XA=1. `C887:09AC` and `DAF2:0040` are refused heads.
None of these calls was entered, so none is a reached closed body.

`DC5B:00BA` file `0x5C66A` and `D5DD:0163` file `0x55F33` were
re-read as `EE` (`OUT DX,AL`). This pass did not re-derive `DX`.
ROM IVT[2] at file `0x08` is `FF FF FF FF`. File `0x0FFEF` is `FF`.

---

## What JEV returned

Call 1 is the recorded JEV result. One `choice` per gap, same
criteria as the procedure. Input 50436 tokens, output 8723.
Labels: `not_free` 16, `mapped_unused_reassignable` 86,
`structural_edge` 30. One hundred of the 132 distributions were
split. That class is a **HYPOTHESIS** about reuse. It does not
own bytes. The gap bounds and the filler test stay **PROVEN**.
None of those 86 are all `0xFF`. 0 of 86 are all `0xFF` and at
least 16 bytes. 86 of 86 fail the filler test. A failed filler
test means the procedure class is `not_free` regardless of JEV's
label. JEV's original labels stay the **HYPOTHESIS**.
`mapped_unused_reassignable` on a gap whose measured
`every_byte_0xFF` is false disagrees with that count. The count
wins. `structural_edge` on a short unowned gap mixed "under 16
bytes" with "unanalyzed gap."

Call 2 is a rejected steered run. The procedure's second request
is only when the first answer says which evidence to fetch or
how to narrow the question. This request put the answer in
`narrow_rule` ("An unowned ledger gap is not_free") and added
"and not an unowned gap" to the other three choice criteria.
Input 54280, output 8386. All 132 choices were `not_free` at
confidence 1.0 and probability 1.0. Nouls: a non-`0xFF` region
is filler, 0.08; an unowned gap is `not_free` even under 16
bytes with a PGR selector, 0.97; file `0x5964F` is a patch
bank, 0.10. Discarded.

Call 3. Input 1444, output 164. Sufficient procedure:
`preimage_procedure` at confidence 1.0 (probability 1.0). The
shortcut choices were 0. Nouls: an `OUT` whose port is not proved
disjoint from `0xFF00-0xFF7E`, 0.91; undecoded gaps remain, 0.97;
`U-PAL` stays unsettled, 0.95; the closed facts establish the
all-paths unread claim, 0.04. The 132 gaps and the unfinished
memory-operand scan keep that claim **UNDETERMINED**. The noul does
not override the gap count.

---

## Ownership

Nothing seeded. No span here has a consumer, a format constraint, and
a bound that would make new owned bytes true, and no reached first
run inside a gap is one closed body. `0x5964F` stays the excluded
one-byte gap. The thirteen call targets stay unowned.
