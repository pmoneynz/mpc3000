# Whole-image string scan

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

Closes D14. A consumer, not printability, establishes text.

Reproduction: `python3 tools/string_scan.py --write` then
`python3 tools/verify_boot_slice.py`.

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | Classify every C-string candidate; name the consumers that make a run *text* |
| Observable | 1096 established starts; 886 `PUSH DS` / `PUSH off` / `CALL FAR`; put-string `B1B1:005B` |
| Inputs | Linear image; DGROUP directory (D10); walker `F800:1875` (D8) |
| Outputs | `analysis/string_scan.json`; put-string bounds |
| Confidence | Consumer classes and put-string body **PROVEN**. Per-screen meaning of each string **UNDETERMINED** (D25). App-ROM printable runs **UNDETERMINED** (lookalikes) |
| Hardware deferred | None. Glass pixels stay D3-glass |

---

## 1. Scan, not ownership

A C-string candidate is a run of printable bytes (`0x20-0x7E`, TAB, CR, LF)
terminated by `NUL`, minimum two printable bytes unless a named table
points at a one-byte or empty slot.

Whole-image counts (regenerated):

| Region | min 2 | min 4 |
|--------|------:|------:|
| Whole image | 2576 | 1451 |
| DGROUP `[0x20000, 0x27C92)` | 1441 | 1153 |
| App `[0x30000, 0x70000)` | 1037 | 295 |
| BIOS `[0x78000, 0x7AC00)` | 72 | 3 |

Printability does not establish text. 1037 app-ROM min-2 runs are
opcode lookalikes until a consumer exists. Zero of the 295 min-4
app-ROM runs sit after a near `CALL` the way the BIOS walker does.

---

## 2. Consumer classes

Four classes. In this image their start sets are disjoint.

### Directory — `8010` far pointers `[0x20004, 0x205C8)`

345 `xxxx:8010`, 19 NULLs, 5 numeric dwords (the `+0238` island).
Every `8010` slot is a C-string: 343 nonempty, 2 empty at `8010:0677`
(the `NUL` after `ALL EVENTS `). 325 unique starts. File
`0x20004` / DGROUP `+0004`. **PROVEN** (D10 table plus this target
check).

### Disk-label table — `[0x205FC, 0x20668)`

27 consecutive `xxxx:8010` after the `???????????` at `+05C8`.
First `FLOPPY DISK`, then `SCSI PART A` .. `SCSI PART Z`. All
C-strings. **PROVEN** as a pointer table by format and bounds.
Other `xxxx:8010` runs deeper in the DGROUP stay suspects (D25).

### BIOS walker — `F800:1875`, file `0x79875`

Three near callers, inline C-strings. **PROVEN** (D8).

| Call file | CS:IP | File | Text |
|-----------|-------|------|------|
| `0x78122` | `F800:0122` | `0x78125` | `MPC-3000 BIOS 21/08/07\r\n` |
| `0x799BE` | `F800:19BE` | `0x799C1` | `=======... System Error ... type ` |
| `0x79A17` | `F800:1A17` | `0x79A1A` | `h\r\ncaused all memory to be lost... mpc3000le@yahoo.com.au` |

The email is inside the third walker string, not a separate object.

### `PUSH DS` / `PUSH off` / `CALL FAR`

Unique pattern `1E 68 iw 9A ip cs` in application / BIOS / FAC0 /
AMX code windows, where `iw` is a DGROUP C-string start. 886 sites,
741 unique targets, 15 callees. Every site is preceded by `PUSH DS`
(`DS=8010` after `E937`). **PROVEN.**

Top callee (382 sites): `B1B1:005B`, file `0x31B6B`, 20-bit
`0xB1B6B` (identity wrap `(CS<<4+IP)&0x7FFFF`, same rule as
`D9BD:0009` -> `0x59BD9`). 24-bit follows the live PGR
(second table through task 7 select).

```
B1B1:005B  PUSH BP / MOV BP, SP / PUSH DS / PUSH DI
           LDS  DI, [BP+6]          ; 8010:string
           MOV  BL, [DI]
           OR   BL, BL
           JZ   0071
           MOV  AX, 4
           INT  43                  ; same AX=4 path as the BIOS walker
           INC  DI
           JMP  0063
           MOV  AX, 7 / INT 43
           MOV  BX, AX
           MOV  AX, 3 / INT 43
           POP  DI / POP DS / POP BP
           RETF                     ; file 0x31B90
```

`[0x31B6B, 0x31B91)`. **PROVEN.** AH=`0x0A`/`0x0B`/`0x0C` meaning
stays `U-LC7981`. Glass stays D3-glass.

The other 14 callees (format/`printf`-shaped `B1BC:01EE`, and the
rest) are named only as CS:IP immediates. Their bodies stay D19+.

---

## 3. Established versus candidate

1096 unique starts, 19843 payload bytes including NULs.

Specimens:

| File | Consumer | Text |
|------|----------|------|
| `0x2066C` | directory | `ALL EVENTS ` |
| `0x20690` | directory | `NO ` |
| `0x206C5` | directory | `50L` |
| `0x20F9C` | disk table | `FLOPPY DISK` |
| `0x210E0` | PUSH DS+far | `www.mansell-labs.com` |
| `0x210F5` | PUSH DS+far | `Vailixi 3.50 (---/--/----)` |
| `0x78125` | walker | `MPC-3000 BIOS 21/08/07\r\n` |
| `0x799C1` | walker | system-error lead-in |

355 DGROUP C-strings (min 2) have none of the four consumers.
They stay **UNDETERMINED** as text. Examples that *look* like
labels (`STARTUP ????????`, `CLICK`, `SYS`/`APS`/`PGM`) are still
candidates until a reader is pinned.

KADAK at `0x7B00F` (`COPYRIGHT (C) 1983 KADAK PRODUCTS LTD.`) is
already owned as the AMX header. `EB 40` at `FB00:000C` jumps over
it. There is no `NUL`. No instruction reads it. **PROVEN** as
identity bytes; **not** consumer-established text.

---

## Byte ownership

| File range | Owner |
|------------|-------|
| `[0x31B6B, 0x31B91)` | code - `B1B1:005B` put-string through `RETF` |

DGROUP strings stay `[0x20000, 0x27C92)` from
[`copy_7c92.md`](copy_7c92.md). Walker inlines stay inside the
BIOS ranges already opened.

---

## What this note does *not* prove

- Meaning of each established string on a screen (D25).
- The 14 non-`B1B1:005B` PUSH callees.
- A consumer for the 355 leftover DGROUP C-strings.
- That an app-ROM printable run is a string.
- LC7981 glass (D3-glass).
