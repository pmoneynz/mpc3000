# ROM floppy startup loader — the path that boots a `.SYS` from disk

**Image:** Vailixi OS 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
Cross-checked in stock 3.08, 3.11, 3.12 (§10). No 3.10 image exists in
`07-rom/`. **Date:** 2026-09-25.

This is the only ROM path that runs code from removable media. It is the
delivery path for OS 3.16 (`M3K316.SYS`) and for any future mod.

Reproduction:

- `python3 tools/floppy_loader.py --check` pins every address, string,
  instruction count and routine hash below in all four EPROM OSes. It
  refuses to decode across `BRKXA`/`RETXA`.
- `analysis/floppy_loader.json` holds the byte-exact routine dumps.
- `python3 tools/verify_boot_slice.py` runs the same check.
- Emulator runs: `python3 -m unittest emu.test_mpc3k` in `MPC3000_builds/`
  (tests `…boots_316_from_floppy`, `…file_selection`, canary).

Mnemonics come from ndisasm. Every window was scanned for `0F E0`/`0F F0`.
The only hits are inside `FAC0:01A4`, which is read from
[`irq_wrappers.md`](irq_wrappers.md), not from ndisasm. Instruction
bounds come from `tools/v53_decode.py`.

Address form throughout: XA=1, second PGR (identity for the ROM pages
used here) until `INT 10` loads the third PGR. `file = (CS<<4)+IP & 0x7FFFF`.
24-bit = 20-bit for these ROM pages (second-PGR words `0x2C..0x3E`).

---

## Contract

| Field | Value |
|-------|-------|
| Purpose | At power-on, if a floppy is ready, load the first `*.SYS` on it as an MZ executable and jump to it; otherwise load startup `APS`/`PGM`/`ALL` files |
| Observable | Row 7 `Searching floppy for startup files...` → `Loading files ...` → loaded program runs. Bad SYS: `System Error … software bug of type 11h` forever |
| Inputs | Floppy FAT12 volume (720K / 800K / 1.44M geometry); caller flags in `SI` |
| Outputs | Never returns if a SYS loads. Otherwise `AX` = flags (bit 0 program loaded, bit 1 `ALL` loaded) |
| Confidence | Code stream and trace behaviour **PROVEN**. FDC register meaning **HYPOTHESIS** (no µPD72069 datasheet in tree). Real-drive timing **UNDETERMINED** |
| Hardware deferred | Physical drive, disk-change and ready lines (`U-PHYS`); ICU mask meaning of `OUT 0xC011` (`U-C0XX`) |

---

## 1. Chain

```
FAC0:019E  JMPF B000:00DF                      BIOS → OS main entry (already pinned)
B000:00DF  OS entry
  0124       print "Searching floppy for startup files..."
  013B       CALL 03B4  → CALLF E7F5:0440      floppy ready?      AX≠0 = yes
  014C       CALL 01A7 (arg 0)                  floppy loader
  0166       print "Searching SCSI for hard disk... <Cancel>"
  0171       CALLF D470:0948                    SCSI startup?
  0184       CALL 01A7 (arg 1)                  SCSI loader (no SYS step)
B000:01A7  loader
  0231       CALLF FB93:0066 (name)             SYS found on floppy → never returns
FB93:0066  hand-off: IVT[8], stack 0040:69C4, INT 10, ES=6900, INT 45, JMP FAR
FAC0:01A4  INT 10: load third PGR (ROM pages 0x2C..0x3C become RAM)
F800:0143  INT 45: DOS-style MZ loader over INT 41 file services
```

Order of the call sites is **PROVEN (code)**. Which site fires is
**PROVEN (trace, MAME breakpoints)**. With the 3.16 floppy, `013B` then `014C`
run, and `0171`/`0184` never run. With no floppy, `013B` then `0171` run.

---

## 2. Strings (3.50)

DGROUP's ROM image `[0x20000, 0x27C92)` is copied to RAM `8010:0000`
([`copy_7c92.md`](copy_7c92.md)), so DS offset X is file `0x20000+X`.
One NUL-separated block. Every string has exactly one consumer in the
image, listed below:

| DS | File | Text | Consumer |
|----|------|------|----------|
| `11C9` | `0x211C9` | `Searching floppy for startup files...` | `PUSH` at `B000:0124` (file `0x30124`) |
| `11EF` | `0x211EF` | `Searching SCSI for hard disk... <Cancel>` | `PUSH` at `B000:0166` (file `0x30166`) |
| `1218` | `0x21218` | `Loading files ...` | `PUSH` at `B000:01BC` (file `0x301BC`) |
| `122A` | `0x2122A` | `STARTUP ????????` | `MOV SI` at `B000:01E6` (SCSI pattern) |
| `123B` | `0x2123B` | `????????????????` | `MOV SI` at `B000:01F6` (floppy pattern) |
| `124C` | `0x2124C` | `SYS` | `MOV SI` at `B000:020E` |
| `1250` | `0x21250` | `APS` | `MOV SI` at `B000:0248` |
| `1254` | `0x21254` | `PGM` | `MOV SI` at `B000:0296` |
| `1258` | `0x21258` | `ALL` | `MOV SI` at `B000:0326` |

Prints go through `B1B1:005B` (put-string), after `B1B1:0026(7, 0)`, which
selects row 7 **HYPOTHESIS** by the screen trace. **PROVEN** as bytes,
consumers, and uniqueness (`tools/floppy_loader.py`).

---

## 3. Floppy test — `B000:03B4` → `E7F5:0440`

`B000:03B4` is `CALLF E7F5:0440` / `RETF` (file `0x303B4`). Body (file `0x68390`):

```
PUSH ES / SI / DI
AX=1E, BX=32 ; CALL 019B
wait: TEST [786E],8000h ; JZ wait          ; no timeout in this loop
AX=7924, BX=14 ; CALL 01C4 ; JC fail
AX=1, BX=[786E] ; CALL 01FA ; JC fail
AND AL,20h ; JZ fail
AX=1 ; return
fail: CALL 00D5 ; AX=0 ; return             ; RETF at 047D
```

Returns non-zero with a disk and 0 without one in MAME. **PROVEN (trace)**. That
`AL & 20h` is µPD765-family ST3 Ready is **HYPOTHESIS**. The writer of
`[786E]` bit 15 is **UNDETERMINED**. The loop has no bound of its own.

---

## 4. Loader — `B000:01A7` (file `0x301A7`, `RETF` `03B3`, 217 insns)

Far cdecl. `[BP+6]` = device (0 floppy, 1 SCSI). `[BP+8]` = flags in/out
(the caller's `SI`, 0 at entry, carried from the floppy call into the SCSI
call). Frame:

| Slot | Size | Use |
|------|------|-----|
| `[BP-32h]` | 16 + 1 | name pattern, copied from `122A` (SCSI) or `123B` (floppy) |
| `[BP-22h]` | 4 | extension, overwrites the pattern NUL → `????????????????SYS\0` |
| `[BP-1Eh]` | 27 | find result block; name string at `+7` (`[BP-17h]`) |
| `[BP-2]` | 2 | PGM slot counter |

```
print row 7 "Loading files ..."; CALLF B1FF:000C(0x28); CALLF CF0C:0006(0)
pattern = device ? "STARTUP ????????" : "????????????????"
INC [9757]
if device == 0:                                   ; SYS only from floppy
    ext = "SYS"; if find_first(pattern, res) == 0:
        CALLF FB93:0066(&res+7)                  ; §5, does not return on success
if !(flags & 1):
    ext = "APS"; if find_first == 0:
        if CALLF C20F:04F6(&res+7, 1) != 0: CALLF CF55:0005   ; error
        else flags |= 1
    elif device == 0:                             ; PGM only from floppy
        ext = "PGM"; r = find_first
        for n = 1; r == 0 and n <= 24; n++:
            if CALLF C20F:0003(&res+7, n) != 0: n = 0; break
            r = find_next
        if n == 0: CALLF CF55:0005 elif n > 1: flags |= 1
        CALLF C887:1BE8(0)
if !(flags & 2):
    ext = "ALL"; if find_first == 0:
        if (e = CALLF D6FA:000E(&res+7)) != 0: CALLF B3C7:0007(e); CALLF DDF4:0002
        else copy name (≤16, NUL-padded) to DS:9606; flags |= 2
DEC [9757]; return flags
```

**PROVEN (code)**. Callee meanings (APS/PGM/ALL loaders, error box) are
**HYPOTHESIS** from the extension and branch shape. They are not needed for
the SYS path.

Find: `CEE6:0175` (find-first) and `CEE6:01E1` (find-next) copy the pattern
to `DS:FAB1` and the 27-byte result to `DS:FA82`. They call
`CF0C:0006(fn, FAB1, FA82, …)`, a wrapper that loads `AX=fn, DX, BX, CX`
and executes `INT 41` at `CF0C:0038` (file `0x4F0F8`). fn = 9 / `0x0A`.
**PROVEN.**

BIOS directory match (`INT 41` side):

- `F800:1366` (file `0x79366`) is `TEST BYTE [BX+0Bh],1Eh` / `JNZ`. It skips
  hidden, system, volume-label and directory entries.
- `F800:136C` compares 11 bytes of the 8.3 entry, with `3Fh` (`?`) as a wildcard.
  It then skips the attribute byte and compares 8 more bytes (entry
  `+0Ch..+13h`, where the MPC keeps the rest of a 16-character name).
- The scan stops at a `00` entry byte.

**PROVEN (code)**. That the 16+3 pattern is normalised to that 8+3 / +8
layout before the match is **HYPOTHESIS**. The behaviour it implies (any 8.3
`*.SYS` matches, first entry wins) is **PROVEN (trace)**, §8.

---

## 5. SYS hand-off — `FB93:0066` (file `0x7B996`, 48 insns, `RETF` `00CF`)

```
PUSH BP / MOV BP,SP / PUSH ES
AX = 7FFF - 06DF ; CMP AX,1 ; JZ ret          ; constant 0x7920: never taken
CLI ; OUT C011h,F6h                           ; ICU mask write (U-C0XX)
IVT[8] = FB93:0059 via CALLF FB00:0347        ; 0059: INT 42 ; OUT C010h,60h ; IRET
LDS DX,[BP+6]                                 ; DS:DX = file name
CLI ; SS:SP = 0040:69C4 ; STI
INT 10                                        ; FAC0:01A4, third PGR (§6)
ES = 6900 ; INT 45                            ; F800:0143, MZ load (§7)
OR AH,AH ; JNZ die
CLI ; if SI|DI: SS=SI, SP=DI                  ; image stack
OUT C011h,FFh
DS = 0040 ; [68C0] = BX ; [68C2] = ES ; JMP FAR [68C0]
die: INT 11 ; JMP die                         ; file 0x7B9F9
```

`INT 11` is the BIOS ladder stub `F800:1986`. It paints
`System Error / Sorry, but a software bug of type 11h caused all memory
to be lost…`. **PROVEN (trace)** with a non-MZ `AAA.SYS`.

State at the first instruction of the loaded image (**PROVEN, code**):

| Item | Value |
|------|-------|
| `CS:IP` | `(load_seg + e_cs) : e_ip` |
| `SS:SP` | `(load_seg + e_ss) : e_sp`. If both header fields are 0, `0040:69C4` is kept |
| `DS` | `0040` |
| `ES` | same as `CS` |
| `IF` | 0 (`CLI`, no `STI` before the jump) |
| ICU | last write `OUT C011h,FFh`. "all masked" is **HYPOTHESIS** (`U-C0XX`) |
| XA / PGR | XA=1, third PGR (§6) |
| `IVT[8]` | `FB93:0059` |

---

## 6. Memory map seen by the loaded image

`INT 10` = `FAC0:01A4` switches XA and `OUTSW`s the third PGR (file
`0x7ADCF`) ([`irq_wrappers.md`](irq_wrappers.md)). Word `n` = page `n`:

| Logical 20-bit | Pages | Second PGR (OS running) | Third PGR (after `INT 10`) |
|----------------|-------|--------------------------|-----------------------------|
| `0x00000–0xAFFFF` | 0–43 | `0xC0+n` RAM | `0xC0+n` RAM |
| `0xB0000–0xF3FFF` | 44–60 | `0x2C+` **ROM** (OS code) | `0xEC+` **RAM** |
| `0xF4000–0xF7FFF` | 61 | `0x140` (`0x500000`) | `0x140` ([`pgr61.md`](pgr61.md)) |
| `0xF8000–0xFFFFF` | 62–63 | `0x3E`/`0x3F` BIOS ROM | unchanged, so `FB93`, `F800`, `FAC0` keep running |

**PROVEN** as table words (all four ROMs, `tools/floppy_loader.py`).

Consequences, derived from the table and the load segment:

- Load region starts at `0x69000` (3.12/3.50) or `0x70000` (3.08/3.11).
- Contiguous RAM runs up to `0xF3FFF`. That leaves `0x8B000` = 569,344 bytes
  (3.12/3.50) or `0x84000` = 540,672 bytes (3.08/3.11) for image + BSS +
  stack.
- `INT 45` has **no** size check (§7). A larger image writes into page 61.
- BIOS data used during the load: `0040:63EC–6426` (header, name), the
  relocation buffer from `0040:642B` (`e_lfarlc` bytes, then 4 per entry),
  and the stack under `0040:69C4`. That is 20-bit `0x067EC–0x06DC4`.

**PROVEN (code)** for the arithmetic. The effect of writing page 61 is
**UNDETERMINED**.

`M3K316.SYS` on 3.50: image `0x6833F` bytes at `0x69000–0xD133F`. `minalloc`
`0x15C7` paragraphs reaches `0xE6FAF`. `SS:SP` = `D966:0100`. It fits.
3.16's live `DS` was `C99C` (emulator trace).

---

## 7. `INT 45` — MZ loader `F800:0143` (file `0x78143`, 468 bytes)

Planted by the BIOS fill: `MOV AX,0143 / MOV [0114],AX / MOV [0116],CS`
(file `0x780E0`). The bytes are identical in all four ROMs (SHA-256
`8edaf657…beb2ef31`). In: `DS:DX` = name, `ES` = load segment. Uses
`INT 41` AX=2 open (handle in AX), AX=4 read (`BX` handle, `CX` count,
`DS:DX` buffer, `CX` = bytes read), AX=3 close.

1. Copy the name (≤ 20 bytes, NUL-terminated) to `0040:6412`. Open it.
2. Read `1Ch` header bytes to `0040:63EC`. Short read: `AH=1`.
3. `word[00] == 'MZ'` (`5A4Dh`), else `AH=2`. `ZM` is not accepted.
4. Read `e_cparhdr*16 − 1Ch` bytes to `load:0000` (skips the header;
   scratch). Short read: `AH=3`.
5. Image size = `(e_cp − (e_cblp≠0))*512 + e_cblp − e_cparhdr*16`. Read it
   to `load:0000` in 16 KiB chunks, advancing the segment by `400h`. Short
   read: `AH=4`. Close.
6. If `e_crlc ≠ 0`: reopen. Read `e_lfarlc` bytes to `0040:642B` (skips
   to the table; there is no seek). Then for each relocation read 4 bytes and
   do `word[(seg+load):off] += load`. Close.
7. Return `BX = e_ip`, `ES = e_cs + load`, `DI = e_sp`,
   `SI = e_ss + load` (SI stays 0 when `e_ss|e_sp == 0`), `AX = 0`.
   On an `INT 41` error its `AH` is returned unchanged.

Ignored: `e_minalloc`, `e_maxalloc`, `e_csum`, `e_ovno`. Overlays are
not supported. **PROVEN (code)**.

`e_lfarlc` bytes land at `0040:642B` with no bound. 3.16 uses `3Eh`.
Anything larger than the space below the stack is **UNDETERMINED** and
unsafe. There is one 4-byte `INT 41` read per relocation (3.16 has 6998).
Whether that is most of the ~45 s boot time the PDF gives is **HYPOTHESIS**.

---

## 8. Disk format

BIOS mount (`F800:0F38`, file `0x78F38`):

- It copies the 21-byte BPB (bytes/sector through hidden sectors).
- It requires heads in 1..20h and sectors/track in 1..14h, else `AH=4`.
- It then selects the geometry slot whose sectors/track matches. Slot pointers
  are at `F800:031F`:

| Slot | Bytes | Total sectors | Sec/track | Media | Format |
|------|-------|---------------|-----------|-------|--------|
| `F800:0325` | `…A005 F9 0300 0900…` | 1440 | 9 | `F9` | 720K |
| `F800:033A` | `…4006 F9 0300 0A00…` | 1600 | 10 | `F9` | 800K |
| `F800:034F` | `…400B F0 0900 1200…` | 2880 | 18 | `F0` | 1.44M |

**PROVEN (code)**. When no slot matches, `DL=3` falls through. The behaviour is
**UNDETERMINED**. A plain `mformat -f 1440` FAT12 image loads (trace). 720K and
800K were not traced.

---

## 9. Emulator evidence (one execution each, MAME `mpc3000`, 3.50 unless noted)

| Disk (root order) | Result at 30 s |
|-------------------|----------------|
| `M3K316.SYS` | `System 3.16 (02/20/05)`, then Play/Record. Same on 3.08, 3.11, 3.12 |
| `ZZMOD.SYS` (= M3K316) | 3.16 loads. The name is irrelevant |
| `ZZMOD.SYS`, `AAA.SYS` (non-MZ) | 3.16 loads. The second SYS is never opened |
| `AAA.SYS` (non-MZ), `M3K316.SYS` | `software bug of type 11h`, permanent. No fallback |
| `README.TXT` only | `Searching SCSI…`, stays 3.50 |
| `STARTUP.SYS` 288-byte canary (`tools/build_canary.py`) | prints `Vailixi 3.51` |
| `MOD350.SYS` patched 3.50 relocated to RAM (`tools/build_mod_sys.py`) | `Vailixi 3.51` banner at 15 s, 484K, Play/Record, panel input. On 3.12: `Mod needs Vailixi 3.50 EPROMs`. See [`../MODDING_HOWTO.md`](../MODDING_HOWTO.md) §4 |
| none | `013B` → `0171`, no loader call |

**PROVEN (trace)**. The rows are regression tests in
`MPC3000_builds/emu/test_mpc3k.py`.

---

## 10. Every EPROM OS (from `tools/floppy_loader.py`)

| | 3.08 | 3.11 | 3.12 | 3.50 |
|--|------|------|------|------|
| OS entry | `B6ED:0000` | `B000:0074` | `B000:0074` | `B000:00DF` |
| floppy test → target | `B6ED:0355` → `F0B9:0442` | `B000:034E` → `E828:0442` | `B000:034E` → `E7F0:0438` | `B000:03B4` → `E7F5:0440` |
| loader | `B6ED:0148` | `B000:0141` | `B000:0141` | `B000:01A7` |
| SYS hand-off | `FB93:0064` | `FB93:005A` | `FB93:005C` | `FB93:0066` |
| load segment | **`7000`** | **`7000`** | `6900` | `6900` |
| `INT 45` | `F800:013D` | `F800:0143` | `F800:0143` | `F800:0143` |
| strings DS | `11D1…` | `11D3…` | `11D3…` | `11C9…` |
| DGROUP file | `0x30000` | `0x20000` | `0x20000` | `0x20000` |
| third PGR file | `0x7AD29` | `0x7ADCF` | `0x7ADCF` | `0x7ADCF` |

The loaders are 217 insns in all four, with the same pattern and extension
order. The hand-offs are 48 insns, differing only in load segment, IVT[8] IP
and the IP of the `FB00` plant-vector routine. `INT 45` is byte-identical. **PROVEN (code)**.
MZ relocation absorbs the segment difference: 3.16 boots on all four
(trace). The 3.16 PDF says "requires ≥ 3.11". Its reason is
**UNDETERMINED**, because 3.08 reaches Play/Record in MAME.

---

## 11. Rules for a mod `.SYS` (derived from §4–§8)

The working procedure built on these rules is [`../MODDING_HOWTO.md`](../MODDING_HOWTO.md).

1. Floppy only. The SCSI call (arg 1) skips the SYS step. **PROVEN (code)**.
2. FAT12, root directory, attribute without bits `1Eh`, extension `SYS`,
   any 8.3 name. **PROVEN (code + trace)**.
3. Exactly one `*.SYS`, or put yours first in directory order. A bad
   first SYS is fatal (`type 11h`). **PROVEN (trace)**.
4. DOS MZ with correct `e_cp`/`e_cblp` for the real file size, `e_cparhdr ≥ 2`,
   and `e_lfarlc` small (≤ `3Eh` is proven by 3.16). Relocations are
   applied, so link for any base. Do not depend on the load segment
   (`6900` vs `7000`). **PROVEN (code)**.
5. Image + BSS + stack must end below logical `0xF4000`. Set
   `e_ss:e_sp`, or set up your own stack first thing. `DS=0040` at entry.
   **PROVEN (code)**.
6. Entry runs with `IF=0`, XA=1, third PGR, BIOS `INT 41/42/43/45` intact
   in pages 62–63. The ROM OS pages are now RAM, so the ROM OS is **gone**.
   A mod is a whole OS, or must copy what it needs before `INT 10`.
   **PROVEN (code)** for the map. Services beyond those used here are
   not audited.

---

## 12. Object bounds

These bounds are for the owner ledger. This note does not seed or change
ledger owners.

| File range | Class | Object |
|------------|-------|--------|
| `[0x300DF, 0x301A7)` | code | OS entry through `RETF` |
| `[0x301A7, 0x303B4)` | code | loader through `RETF` |
| `[0x303B4, 0x303BA)` | code | floppy-test stub |
| `[0x7B996, 0x7BA00)` | code | SYS hand-off through `RETF` |
| `[0x78143, 0x78317)` | code | `INT 45` MZ loader |
| `[0x7831F, 0x78364)` | data | geometry pointers + three BPB slots |
| `[0x211C9, 0x2125C)` | data | loader strings (DGROUP image) |

---

## 13. Not proven here

- FDC register effects of the floppy test and `INT 41` (µPD72069
  datasheet absent; see [`d23_load_save.md`](d23_load_save.md)).
- What `D470:0948` tests on SCSI. arg 1 = SCSI is **HYPOTHESIS**.
- 720K/800K disks, real drive timing, disk-change behaviour (`U-PHYS`).
- The APS/PGM/ALL loader callees and the `CF55:0005` / `B3C7:0007` error UI.
- Any hardware run. Every trace above is MAME.
