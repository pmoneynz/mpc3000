**Non-refused hit count under the CS:IP filter: 0.** That filter skips owned `code` whose `why` has no `CS:IP`. Twelve further owned `CALLF` immediates into current gaps are listed below. They are not seed recommendations.

# D17 — owned-code immediates into ledger gaps

**Ledger:** 952 ranges, 377010 owned bytes, 122 gaps — `analysis/owner_ledger.json` mtime `2026-09-22T06:08:50+00:00`.

Method: linear image via `tools.linear_rom.load_vailixi_linear`; gaps via `tools.owner_ledger`; owned `code` ranges decoded with `tools.v53_decode.decode_one` from range start when the file span lies in the 20-bit CS window from the first `CS:IP` in `why`. Only `CALLN`, `CALLF`, `JMPN`, `JMPF` immediates; no indirect r/m.

**Non-refused target CS:IP under the filter:** _(none)_. The twelve `CALLF`s in the next section were skipped because their range `why` has no `CS:IP`.

## Hits the CS:IP filter skipped

Same ledger (952 ranges, 377010 owned bytes, 122 gaps). Linear `decode_one` from the owned-range start, `CALLF` only. Target file is inside a gap. XA not re-derived; these are immediate encodings.

| Caller file | Bytes | Target | Target file | Gap |
|-------------|-------|--------|-------------|-----|
| `0x4438A` | `9A 57 02 C7 CA` | `CAC7:0257` | `0x4AEC7` | `[0x4A4DE, 0x4C512)` |
| `0x4439A` | `9A 08 00 09 B5` | `B509:0008` | `0x35098` | `[0x35098, 0x370F1)` |
| `0x443A5` | `9A 02 00 75 CD` | `CD75:0002` | `0x4D752` | `[0x4C5C9, 0x4EBCC)` |
| `0x443BB` | `9A 04 00 87 C8` | `C887:0004` | `0x48874` | `[0x4844D, 0x4A458)` |
| `0x443CB` | `9A 0C 00 7C B7` | `B77C:000C` | `0x377CC` | `[0x37336, 0x396E6)` |
| `0x443DB` | `9A 06 00 81 CC` | `CC81:0006` | `0x4C816` | `[0x4C5C9, 0x4EBCC)` |
| `0x443F6` | `9A 09 00 4C C8` | `C84C:0009` | `0x484C9` | `[0x4844D, 0x4A458)` |
| `0x4441E` | `9A 04 00 9B CA` | `CA9B:0004` | `0x4A9B4` | `[0x4A4DE, 0x4C512)` |
| `0x44432` | `9A 0C 00 F9 BC` | `BCF9:000C` | `0x3CF9C` | `[0x399A2, 0x3DE3E)` |
| `0x4443C` | `9A 0B 00 7A CE` | `CE7A:000B` | `0x4E7AB` | `[0x4C5C9, 0x4EBCC)` |
| `0x5CA2F` | `9A 40 00 F2 DA` | `DAF2:0040` | `0x5AF60` | `[0x5AEF9, 0x5B07D)` |
| `0x5E796` | `9A 62 13 C2 C6` | `C6C2:1362` | `0x47F82` | `[0x46C2B, 0x4835D)` |

The ten `B13A:0000` and four `C887:09AC` rows above are the other far hits. Do not seed any of these from this list.

## Refused (do not recommend)

| caller CS:IP | caller file | bytes | target CS:IP | target file | gap [start, end) |
|--------------|-------------|-------|--------------|-------------|------------------|
| C4C8:0571 | 0x451F1 | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:059E | 0x4521E | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:0643 | 0x452C3 | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:0662 | 0x452E2 | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:075A | 0x453DA | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:0787 | 0x45407 | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:08FD | 0x4557D | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:096C | 0x455EC | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:09EB | 0x4566B | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| C4C8:0EF7 | 0x45B77 | 9a00003ab1 | B13A:0000 | 0x313A0 | [0x31370, 0x314B2) |
| B77C:203E | 0x397FE | e89aff | B77C:1FDB | 0x3979B | [0x3979B, 0x397ED) |
| BE1A:0354 | 0x3E4F4 | 9aac0987c8 | C887:09AC | 0x4921C | [0x4844D, 0x4A458) |
| C44E:01B3 | 0x44693 | 9aac0987c8 | C887:09AC | 0x4921C | [0x4844D, 0x4A458) |
| C44E:021D | 0x446FD | 9aac0987c8 | C887:09AC | 0x4921C | [0x4844D, 0x4A458) |
| C44E:029A | 0x4477A | 9aac0987c8 | C887:09AC | 0x4921C | [0x4844D, 0x4A458) |
