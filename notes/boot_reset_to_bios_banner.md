# Reset to BIOS banner / LC7981 init

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

This is the first connected slice. It is **not** reset-to-event-loop.
The KADAK copyright at file `0x7B00F` is on the image and unused by this
note.

Reproduction: `python3 tools/verify_boot_slice.py`.

Address forms: [`address_model.md`](address_model.md).

---

## Contract (slice)

| Field | Value |
|-------|-------|
| Purpose | Power-on fetch, V53 wait-state/refresh setup, first XA map, work-RAM clear, BIOS entry, LC7981 programming |
| Observable | Seven `OUT` pairs to LC7981 ports `0xE2`/`0xE0` from `INT 43` AX=0, then an inline-string print of `MPC-3000 BIOS 21/08/07` |
| Inputs | Reset state; ROM as mapped; RAM and NVRAM contents ignored after the clear |
| Outputs | PGR live; XA=1 after `BRKXA 0x14`; IVT in work RAM; LCD controller programmed |
| Confidence | Path to LCD init: **PROVEN** statically. Glyph pixels for the banner: **HYPOTHESIS**. Event loop: **UNDETERMINED**. |
| Hardware deferred | Actual LC7981 glass; busy-bit timing; PAL decode of `0xC0xx` |

---

## 1. Reset vector — file `0x7FFF0`

```
FFFF:0000  EA 00 00 F0 FF    jmp FFF0:0000
FFFF:0005  FF × 11           erased tail
```

20-bit target `0xFFF00` = file `0x7FF00`.

Byte-identical on stock 3.08, 3.11, 3.12, and Vailixi 3.50.

## 2. Wait-state stub — `FFF0:0000`, file `0x7FF00`

Straight-line `MOV DX,port` / `MOV AX,imm` / `OUT DX,AL`, then a far jump.

| Port | AL | V53 name (MAME `v53_device::internal_port_map`) |
|------|----|--------------------------------------------------|
| `0xFFEA` | `0x07` | WMB0 |
| `0xFFF3` | `0x00` | WMB1 |
| `0xFFED` | `0x00` | WAC |
| `0xFFEC` | `0x02` | WCY0 |
| `0xFFEB` | `0x11` | WCY1 |
| `0xFFF4` | `0x11` | WCY2 |
| `0xFFF5` | `0x31` | WCY3 |
| `0xFFF6` | `0x31` | WCY4 |
| `0xFFF2` | `0x90` | RFC |

Then `EA 00 00 C0 FA` = `jmp FAC0:0000` (file `0x7AC00`).

**PROVEN:** instruction stream and port numbers. **UNDETERMINED:** what those
wait-state and refresh encodings do on this board. The writes happened; the
device effect is a named boundary.

`[0x7FF44, 0x7FFF0)` is `0xFF` padding. Purpose: unused space between the
stub and the reset vector. Boundary **PROVEN**.

## 3. FAC0:0000 — delay, PGR, `BRKXA 0x11`

```
FAC0:0000  cli
           cld
           DX=3, CX=0
           loop/dec DX          ; software delay; duration UNDETERMINED
           CX=0x40, SI=0x0256, DX=0xFF00
           CS OUTSW; DX+=2      ; 64 PGR words
           BRKXA 0x11           ; bytes 0F E0 11
```

ROM IVT[0x11] at file `0x00044` = `FAC0:001F`. Vector fetch is still XA=0,
so this continues in place and then XA=1.

**PROVEN:** PGR[0]=`0x00C0` maps 20-bit page 0 to `0x300000`. After this
instruction, a read of `0000:0000` is work RAM, not the ROM template.

## 4. I/O tables and RAM clear — `FAC0:001F`

Two CS-relative tables terminated by `0x1234`:

| Table | File | Form |
|-------|------|------|
| `CS:02D6` | `0x7AED6` | word port, word value, `OUT DX,AL` |
| `CS:0364` | `0x7AF64` | word port, word value, `OUTSW` (one entry: `0xC008=0x0010`) |

The byte table reprograms SCTL/OPHA/OPSEL, repeats the wait-state set, and
hits relocated `0xC0xx` plus 8255 ports `0x82`/`0x84`/`0x86`/`0xFE`.
**PROVEN** as bytes and as the consumed format. Device effects of `0xC0xx`
remain **UNDETERMINED**.

Then eight passes of `REP STOSW` with `CX=0x8000`, `ES+=0x1000`:
512 KiB starting at translated `ES=0` = `0x300000`. **PROVEN** as
instruction intent under the first PGR. Whether every later alias of that
RAM is covered is a later lifetime question.

## 5. Copy and XA dance

Still at `FAC0` (high ROM stays mapped):

```
IVT[2] = FAC0:01A4          ; 0000:0008, now in RAM
SS:SP  = 900C:0100          ; 24-bit 0x3901C0 under PGR[36]
ES     = 8010               ; 24-bit 0x380100
DS     = A000               ; 24-bit 0x0A0000 = ROM file 0x20000
CX     = 0x7C92 / 2
REP MOVSW
IVT[0x12] = FAC0:00A2
RETXA 0x12
; FAC0:00A2
OUTSW second PGR from CS:00B4
BRKXA 0x14                  ; ROM IVT[0x14] = FAC0:0134
```

**PROVEN:** the copy length, the segment numbers, and the two extended-mode
transfers. **HYPOTHESIS:** `0x7C92` bytes from file `0x20000` are the main
relocated OS body. Consumers of that copy are not yet inventoried.

`ndisasm` is not safe from `FAC0:00B4` onward: that is PGR data, not code.

## 6. Init table ? BIOS — `FAC0:0134`

After further RAM zeroing, the stub walks 6-byte records at `ES=F07A`
(file `0x707A0`), `SI=4` .. `DI=0x16`, `AH=0`:

```
01 00  0A 00 00 F8     ; byte1==AH, byte0!=0 ? CALL FAR F800:000A
01 01  D4 1A 00 F8     ; skipped (byte1=01)
01 FF  0C 00 00 FB     ; skipped (byte1=FF)
```

**PROVEN:** only the first record is called on this pass. That is the BIOS
entry.

## 7. BIOS `F800:000A` — file `0x7800A`

Straight-line through relocated-timer writes, a `DS=0040` BSS clear
(`CX=0x68B0`), IVT fill, `STI`, then:

```
F800:0113  AX=0
           INT 43
           AL=0 .. 0x0F: INT 46
           CALL F800:1875          ; file 0x79875
           db "MPC-3000 BIOS 21/08/07", 13, 10, 0
```

`INT 43` handler `F800:16AA` (installed at `0000:010C`) dispatches
`AX < 8` through `CS:16D4`. `AX=0` ? `F800:16E4`:

```
AX=003C; call LCD_put
AX=0175; call LCD_put
AX=0227; call LCD_put
AX=033F; call LCD_put
AX=0407; call LCD_put
AX=0800; call LCD_put
AX=0900; call LCD_put
```

## 8. LCD put — file `0x7985A`

```
7985A  push ax
7985B  in  al, 0xE2
       and al, 0x80
       jnz wait
       mov al, ah
       out 0xE2, al      ; LC7981 control
       pop ax
       out 0xE0, al      ; LC7981 data
       ret
```

Ports match MAME (`0x00E0` data, `0x00E2` status/control). Bit 7 = busy
matches HD61830-class behavior. **PROVEN:** this routine writes those
ports. **UNDETERMINED:** the exact LC7981 register map for AH/AL pairs
`00/3C`, `01/75`, … without the controller datasheet. The writes are the
observable. Their glass-level effect is the hardware boundary.

## 9. Banner string

`0x79875` pops the return address into `SI`, sets `ES=CS`, and walks
bytes until `0x00`. Each character is handed to `0x798CA`, which issues
`INT 43` with `AX=4`.

**PROVEN:** the BIOS banner bytes are the inline argument of that walker.
**HYPOTHESIS:** ordinary ASCII reaches the LC7981 pixel memory. `INT 43`
AX=4 is a character-class dispatcher (`0x79752`) whose default path is not
yet fully traced to `LCD_put`. Do not claim the letters are on the glass
until that path is closed.

---

## Byte ownership opened by this slice

These ranges now have an evidence-backed owner. Everything else stays
unresolved.

| File range | Owner | Why |
|------------|-------|-----|
| `[0x00000, 0x00044)` | data / padding | leading `0xFF`; unused IVT slots 0–0x10 |
| `[0x00044, 0x0004C)` | data / IVT template | vectors 0x11, 0x12 |
| `[0x0004C, 0x00050)` | data / padding | `0xFF` |
| `[0x00050, 0x00054)` | data / IVT template | vector 0x14 |
| `[0x00054, 0x20000)` | data / padding | 131,020 `0xFF` bytes; no other non-`FF` in the window |
| `[0x7AC00, 0x7ACB4)` | code | FAC0 reset body through `BRKXA 0x14` |
| `[0x7ACB4, 0x7AD34)` | data | second PGR image (consumed by `OUTSW`) |
| `[0x7AD34, 0x7ADC0)` | code | `BRKXA 0x14` target through the next XA switch; exact end **HYPOTHESIS** |
| `[0x7AE56, 0x7AED6)` | data | first PGR image |
| `[0x7AED6, 0x7AF6A)` | data | I/O tables + sentinels |
| `[0x7FF00, 0x7FF44)` | code | wait-state stub |
| `[0x7FF44, 0x7FFF0)` | data / padding | `0xFF` |
| `[0x7FFF0, 0x7FFF5)` | code | reset vector |
| `[0x7FFF5, 0x80000)` | data / padding | `0xFF` |
| `[0x7800A, 0x7813E)` | code + inline string | BIOS entry through banner NUL |
| `[0x796AA, 0x796D4)` | code | `INT 43` dispatcher |
| `[0x796D4, 0x796E4)` | data | eight near targets |
| `[0x796E4, 0x7971D)` | code | `INT 43` AX=0 LCD init |
| `[0x7985A, 0x79875)` | code | LCD put |

`[0x7AD34, 0x7ADC0)` is deliberately coarse. Do not treat it as a finished
instruction partition.

---

## What this slice does *not* prove

- The KADAK/AMX scheduler is the event loop. The copyright is present;
  no start call is shown here.
- Panel, MIDI, SCSI, FDC, or DSP behavior.
- That `INT 46` or `INT 43` AX=4 paints glyphs.
- Any 24-bit access to NVRAM `0x500000`.
- Runtime copies after the `0x7C92`-byte move: aliases, later overwrite,
  interrupt writers.

Next useful uncertainty: the `FAC0:0134` instruction partition through the
return from `F800:000A`, then the first AMX entry, then `INT 43` AX=4 to
pixels.
