# Owner ledger seed

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D12. D13 padding windows are in [`padding.md`](padding.md).
D17 still owes no-gap closure.

Reproduction: `python3 tools/owner_ledger.py --write` then
`python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Machine-readable owner map for proven file ranges |
| Observable | `analysis/owner_ledger.json`; 61 ranges; 252100 owned bytes |
| Inputs | Byte-ownership tables in the notes |
| Outputs | Owner `code` or `data` only. 26 gaps left as debt |
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

26 holes. They are debt. They are not
`excluded_workspace`. Largest:

| File range | Bytes | Why it is a gap |
|------------|------:|-----------------|
| `[0x32600, 0x5518D)` | 142221 | app ROM past task 1 |
| `[0x5DF42, 0x69374)` | 46130 | between task 4 and `E937` |
| `[0x27C92, 0x300DF)` | 33869 | after the DGROUP image, before task 7 |
| `[0x707B6, 0x7800A)` | 30804 | after `F07A`, before BIOS |
| `[0x7B813, 0x7FF00)` | 18157 | after the create-table stub, before the wait stub |

Smallest named hole: `[0x7ADA3, 0x7ADA4)` is `CF` (`IRET`) between
`FAC0:019E` `jmp B000:00DF` and `FAC0:01A4`. No entry is proven.
It stays a gap.

`[0x7B5E9, 0x7B616)` is `05E9` through the byte before `0616`.
`05E9` is named as a TCB walker and is not yet bounded.

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
