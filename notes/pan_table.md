# Directory `+0054` — pan names, not pad labels

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Retracts the `copy_7c92.md` “pad labels `50L` .. `16R`” reading.
The directory block is 101 far pointers `50L` .. ` C ` .. `50R`
plus a NULL. The owned consumer `B354:01C6` is called with title
`Pan:`. D20 (pad / note entry) stays open: this table is a pan
display object, not a pad-hit path.

Reproduction: `python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Name the `+0054` directory block and its owned printer |
| Observable | 101 `xxxx:8010` ptrs; title `Pan:` at DGROUP `+54A1`; `B354:01C6` `CALL B1B1:005B` |
| Inputs | Directory file `[0x20054, 0x201EC)`; four unowned `PUSH DS` / `PUSH 0x0054` sites |
| Outputs | Put-string of one indexed name via `B1B1` |
| Confidence | Table bytes, title, and `B354:01C6` encodings **PROVEN**. Pan unit (percent vs UI step) **UNDETERMINED**. Pad-hit / note-on path **UNDETERMINED** |
| Hardware deferred | Physical pad scan (`U-PANEL-ROM`, `U-TE7774`, D19/D20 remainder) |

---

## 1. Table

DGROUP directory, `DS=8010`. File = `0x20000 + off`.

| Off | File | Dword | Text |
|-----|------|-------|------|
| `+0054` | `0x20054` | `C5 06 10 80` | `50L` at `8010:06C5` / file `0x206C5` |
| `+011C` | `0x2011C` | `8D 07 10 80` | ` C ` at `8010:078D` / file `0x2078D` (index 50) |
| `+01E4` | `0x201E4` | `55 08 10 80` | `50R` at `8010:0855` / file `0x20855` |
| `+01E8` | `0x201E8` | `00 00 00 00` | terminator |

`(0x01E4 - 0x0054) / 4 + 1` = 101 named slots. Order is
`50L` .. `1L`, ` C `, `1R` .. `50R`. `16R` is slot 66, not the
end. **PROVEN.**

---

## 2. Owned consumer — `B354:01C6`

File `0x33706`. Already owned (`[0x33549, 0x3391B)`).

```
B354:01C6  55 8B EC 83 EC 0C 56
           FF 76 08 FF 76 06
           CALL B1B1:005B          ; put-string title
           …
           SHL AX, 2               ; dword stride
           LES BX, [BP+0E]
           ADD BX, AX              ; index into the far-ptr table
           … CALL B1B1:0036        ; put-string name
           RETF
```

Four unowned sites pass `DS:0054` as that table and a title
`Pan:` (`8010:54A1`, file `0x254A1`):

| File | Encoding | Dest |
|------|----------|------|
| `0x46094` / `0x460A1` | `1E 68 54 00` … `9A C6 01 54 B3` | `B354:01C6` |
| `0x465E5` | same CALLF | `B354:01C6` |
| `0x46AB3` | same CALLF | `B354:01C6` |
| `0x4D46F` | same CALLF | `B354:01C6` |

Those callers sit in app-ROM gaps. They are not seeded. **PROVEN**
as encodings and as `CALLF` dests.

---

## 3. What this does not close

D20 needs a path from a pad hit or a note-on to a note number.
`B354:01C6` prints a pan name. It does not read TE7774 or write a
note. Do not treat `C303:0930` `CMP BX,0x65` as this table’s
bound — that site switches on ASCII after `B060:035D`.
