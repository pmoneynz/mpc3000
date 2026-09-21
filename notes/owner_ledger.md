# Owner ledger seed

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D12. D13 padding windows are in [`padding.md`](padding.md).
D16 instruction-byte runs are unioned into the ledger. D17 still
owes no-gap closure: large app-ROM holes remain unowned.

Reproduction: `python3 tools/owner_ledger.py --write` then
`python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Machine-readable owner map for proven file ranges |
| Observable | `analysis/owner_ledger.json`; 187 ranges; 267020 owned bytes |
| Inputs | Byte-ownership tables in the notes; D16 instruction-byte runs |
| Outputs | Owner `code` or `data` only. 82 gaps left as debt |
| Confidence | Seed spans **PROVEN** as the union of those tables. Gaps are **UNDETERMINED**, not owners |
| Hardware deferred | None |

Owners are only `code`, `data`, or `excluded_workspace`.
`unresolved` is never an owner. This seed has no
`excluded_workspace` row. Padding is `data` with `kind=padding`
and is all `0xFF`.

---

## 1. What is seeded

D12 named `boot_reset_to_bios_banner.md` and `amx_wait.md`. Later
G2 notes already opened more ranges. The seed is the union, not
the two files alone. Adjacent same-owner spans are merged only
when they form one proven block (AMX `0x7B04E-0x7B5E9`, BIOS
ladder through `1AD4`).

`E937:0004` is `[0x69374, 0x6937C)` (8 bytes through `RETF`). The
create-table note’s exclusive end `0x6937B` is a subset.

INT 43 AX=4 `[0x79752, 0x79808)` is split: class walk, class
table (`data`), specials, default. The boot note’s “code + class
table” row is covered by that split.

---

## 2. Gaps

D16 walks split the old 26 holes into more, smaller debt.
They are not `excluded_workspace`. Closed this pass:

| File range | Bytes | Owner |
|------------|------:|-------|
| `[0x27CA0, 0x27CB0)` | 16 | data — zeros after DGROUP |
| `[0x707B6, 0x707C8)` | 18 | data — `F07A` tail |
| `[0x7B5E9, 0x7B616)` | 45 | code — `05E9` / `060B` |
| `[0x7B802, 0x7B80E)` | 12 | data — kernel far-ptr table |

Smallest remaining named hole: `[0x7ADA3, 0x7ADA4)` is `CF`
(`IRET`) between `FAC0:019E` `jmp B000:00DF` and `FAC0:01A4`.
No entry is proven. It stays a gap.

Largest remaining holes are unentered app ROM between
established bodies (see the regenerated JSON).

---

## 3. Checks

`tools/owner_ledger.py` rejects overlap, `unresolved` as an owner,
`excluded_workspace` in this seed, a padding byte that is not
`0xFF`, and a Byte-ownership row that the ledger does not cover.
A code note row may contain a `data` island (class table). A data
note row may not be owned as code.

Regenerating the JSON from the seed must match the committed file.

---

## What this note does *not* prove

- Whole-image coverage (D17).
- Purpose of every remaining `0xFF` window (D13).
- That a gap is not code. Gaps are unanalyzed.
