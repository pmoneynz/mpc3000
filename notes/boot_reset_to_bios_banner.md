# Reset to BIOS banner / LC7981 init

**Image:** Vailixi 3.50 linear
`a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9`.
**Date:** 2026-09-21.

This is the first connected slice. Reset now reaches the AMX dispatcher
spin. That is still not a named application event loop: the wake source
is open (`U-AMX-WAIT`).

Reproduction: `python3 tools/verify_boot_slice.py`.

Address forms: [`address_model.md`](address_model.md).

---

## Contract (slice)

| Field | Value |
|-------|-------|
| Purpose | Power-on fetch, V53 wait-state/refresh setup, first XA map, work-RAM clear, BIOS entry, LC7981 programming, AMX start |
| Observable | Seven `OUT` pairs to LC7981 ports `0xE2`/`0xE0` from `INT 43` AX=0, then an inline-string print of `MPC-3000 BIOS 21/08/07`, then AMX dispatcher spin |
| Inputs | Reset state; ROM as mapped; RAM and NVRAM contents ignored after the clear |
| Outputs | PGR live; XA=1 after `BRKXA 0x14`; IVT in work RAM; LCD controller programmed; AMX entered |
| Confidence | Path to LCD init and AMX start: **PROVEN** statically. Glyph pixels for the banner: **HYPOTHESIS**. Dispatcher wake source: **UNDETERMINED**. |
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
IVT[10h] = FAC0:01A4        ; 0000:0040, now in RAM
                             ; (earlier “IVT[2] at 0000:0008” is retracted)
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
transfers. The copied object is a relocated DGROUP (`U-COPY-7C92`
closed). It is **not** a single relocated code image.

`ndisasm` is not safe from `FAC0:00B4` onward: that is PGR data, not code.

## 6. Init table — `FAC0:0134`, file `0x7AD34`

After the copy, `FAC0:0134` sets `DS=ES=8010`, zeros `8010:7C92` through
`8010:FFB7` (`CX = (0xFFB8 - 0x7C92) / 2` words), then walks 6-byte
records at `ES=F07A` (file `0x707A0`), `SI=4` .. `DI=0x16`.

Record form: `byte0`, `byte1=AH`, `off`, `seg`. `byte0 != 0` selects
`CALL FAR [ES:BX+2]`; `byte0 == 0` selects `CALL NEAR`. After each
successful call, `CX` (initial record count 3) decrements. A miss
advances `BX` by 6. Exhausting `BX` increments `AH` and restarts at
`SI`. `CX=0` falls into `STI` / `XOR BP,BP` / `jmp B000:00DF`.

```
F07A:0004  01 00  0A 00 00 F8     ; AH=0  CALL FAR F800:000A
F07A:000A  01 01  D4 1A 00 F8     ; AH=1  CALL FAR F800:1AD4
F07A:0010  01 FF  0C 00 00 FB     ; AH=FF CALL FAR FB00:000C
```

No record has `byte0=0`. The near-call site at `FAC0:0185` is unused by
this table.

**PROVEN:** BIOS `F800:000A` ends `POP DI/SI/ES/DS; RETF` at file
`0x7813E`. **PROVEN:** `F800:1AD4` is a straight-line IVT/port init that
`RETF`s at file `0x79B25`. **PROVEN:** `FB00:000C` is the KADAK header
(`jmp FB00:004E` over the copyright). Its visible tail is the dispatcher
spin at `FB00:013E` and does not `RETF`.

The earlier claim that only the first record runs on this pass is
**retracted**. This-trace: BIOS returns, the AH=1 record returns, AMX
start is then entered and does not return. `jmp B000:00DF` is therefore
**not** on the reset path unless AMX start grows a return. That jump is
still a real instruction at `FAC0:019E` (file `0x7AD9E`).

## 7. BIOS `F800:000A` — file `0x7800A`

Straight-line through relocated-timer writes, a `DS=0040` BSS clear
(`CX=0x68B0`), IVT fill, `STI`, then:

```
F800:0113  AX=0
           INT 43
           AL=0 .. 0x0F: INT 46
           CALL F800:1875          ; file 0x79875
           db "MPC-3000 BIOS 21/08/07", 13, 10, 0
           pop di / si / es / ds
           retf                   ; file 0x78142
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
Ordinary characters take `INT 43` AX=4 ? `17CC` ? `LCD_put` AH=`0x0C`.
See [`int43_ax4.md`](int43_ax4.md). Glass pixels stay `D3-glass`.

## 10. Second init — `F800:1AD4`, file `0x79AD4`

Straight-line, then `RETF` at `F800:1B25` (file `0x79B25`):

```
PUSH DS; DS=0; PUSHF; CLI
IVT[0x0B] = F800:2047
IVT[0x40] = F800:1B36
IVT[0x42] = F800:205E
IN  AL, 0xA2 / AND 0xFE / OUT 0xA2, AL
IN  AL, DX=0xC011 / AND 0xF7 / OUT DX, AL
POPF
DS=06DD; [02]=20A8; zero [04]..[09]
POP DS; RETF
```

**PROVEN:** instruction stream and the ports written. Device effect of
`0xA2` and `0xC011` is **UNDETERMINED** (`U-C0XX`). `DS=06DD` is a 20-bit
page under the live PGR; its 24-bit identity after BIOS has rewritten
maps is `U-XA-LIVE`.

## 11. AMX start — `FB00:000C`, file `0x7B00C`

```
FB00:000C  jmp short 004E
FB00:000F  db "COPYRIGHT (C) 1983 KADAK PRODUCTS LTD."
FB00:004E  CLI; load kernel pointers from CS:[0046]/[0042]/[0036]
           plant IVT[0]=FB00:02F8 and IVT[4]=FB00:02EF
           …
FB00:013E  LDS DI, CS:[0042]
           CALL 01EA
           JMP 013E
```

`FB00:01EA` / `0537` are partitioned in
[`amx_wait.md`](amx_wait.md). Empty or bit-15 TCB ? `STI` + NOP spin at
`FB00:023A`. A ready TCB is resumed (`RETF`) or created (`0240`). Create
record 7 is `B000:00DF` — same CS:IP as `FAC0:019E`, different path.

**PROVEN:** start call, dispatcher site, wait *condition*.
First `01EA` creates task 6; see
[`amx_first_dispatch.md`](amx_first_dispatch.md). A later empty-queue
wake ISR is still `U-AMX-WAIT`.

Reaching `013E` from `004E` walks data-dependent tables. This-trace from
the header bytes in this image has no `RETF` on that path. All-paths
“never returns” still needs those table bounds.

## 12. Copy bound — `U-COPY-7C92` (closed D10)

| Field | Value | Tag |
|-------|-------|-----|
| Source | `DS=A000` = file `[0x20000, 0x27C92)` | **PROVEN** |
| Dest | `ES=8010` = 24-bit `0x380100` under first *and* second PGR (page 32 frame `0xE0`) | **PROVEN** |
| Length | `0x7C92` (31900) | **PROVEN** |
| Boot writer | `FAC0:0074` `REP MOVSW`; only `MOV AX,A000` in the image | **PROVEN** |
| Signature | `AA 55` then word `0x0100` at `8010:0000`; unique `AA 55` in the image | **PROVEN** as bytes |
| Directory | `[+4, +0x5C8)`: 345 `xxxx:8010` far ptrs, 19 NULLs, 5 numeric dwords at `+0238` | **PROVEN** |
| Rest | string pool + initialized scalars; `065B` overlays `+125C`.. when `ES=8010` | **PROVEN** as writer class |
| Later writers / aliases | boot MOVSW + BSS STOSW + `065B` + per-global stores; dest alias is `8010` only | **PROVEN** — [`copy_7c92.md`](copy_7c92.md) |

The previous “relocated OS body” wording is withdrawn. The copy is a
relocated writable DGROUP. Word `+2` and the `+0238` island *meaning*
stay open inside that note.

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
| `[0x20000, 0x27C92)` | data | `DS=A000` DGROUP image; directory + strings + scalars |
| `[0x707A4, 0x707B6)` | data | three 6-byte init records |
| `[0x7AC00, 0x7ACB4)` | code | FAC0 reset body through `BRKXA 0x14` |
| `[0x7ACB4, 0x7AD34)` | data | second PGR image (consumed by `OUTSW`) |
| `[0x7AD34, 0x7ADA3)` | code | table walk through `jmp B000:00DF` |
| `[0x7ADA4, 0x7ADCF)` | code | `IVT[10h]` handler through `BRKXA 0x12` |
| `[0x7ADCF, 0x7AE4F)` | data | third PGR image |
| `[0x7AE4F, 0x7AE56)` | code | ROM IVT[0x12] continue: pops + `IRET` |
| `[0x7AE56, 0x7AED6)` | data | first PGR image |
| `[0x7AED6, 0x7AF6A)` | data | I/O tables + sentinels |
| `[0x7B00C, 0x7B04E)` | data | AMX header / copyright / config words |
| `[0x7B04E, 0x7B148)` | code | AMX start through dispatcher `JMP 013E` |
| `[0x7FF00, 0x7FF44)` | code | wait-state stub |
| `[0x7FF44, 0x7FFF0)` | data / padding | `0xFF` |
| `[0x7FFF0, 0x7FFF5)` | code | reset vector |
| `[0x7FFF5, 0x80000)` | data / padding | `0xFF` |
| `[0x7800A, 0x78144)` | code + inline string | BIOS entry through `RETF` |
| `[0x79AD4, 0x79B26)` | code | second init record through `RETF` |
| `[0x796AA, 0x796D4)` | code | `INT 43` dispatcher |
| `[0x796D4, 0x796E4)` | data | eight near targets |
| `[0x796E4, 0x7971D)` | code | `INT 43` AX=0 LCD init |
| `[0x79752, 0x79808)` | code + class table | `INT 43` AX=4 through default |
| `[0x79843, 0x79875)` | code | cursor `1843` + LCD put |
| `[0x79875, 0x79896)` | code | inline-string walker |
| `[0x798CA, 0x798D6)` | code | `18CA` issues `INT 43` AX=4 |

`[0x7B04E, 0x7B148)` is the start-to-dispatcher span, not the whole AMX
kernel. Helpers past `0148` stay unresolved.

---

## What this slice does *not* prove

- What leaves a later AMX idle spin (`U-AMX-WAIT` remainder). First
  select creates task 6 and does not idle.
- That `B000:00DF` runs after reset. The instruction exists; AMX start
  does not return on the traced path.
- Panel, MIDI, SCSI, FDC, or DSP behavior.
- That `INT 46` or the AX=4 port writes paint glyphs.
- Any 24-bit access to NVRAM `0x500000`.
- Later writers or aliases of the `0x7C92`-byte copy — **closed** D10.

Next useful uncertainty: owner ledger (D12), or task 7 body
`B000:00DF`. Mailbox grammar at `065B` stays D11.
