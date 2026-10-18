# Input Thru: live input monitoring in every mode (design)

**Target:** PMONEY universal build, OS 3.16 + cave (`port-316`, head
`48d62ff`). **Date:** 2026-10-18. **Status:** design only; no code.
Owner decisions: build on the latest target (3.16); losing voices while Thru
is on and silence during disk/edit transfers are acceptable; the setting
lives on the MIXER/EFFECTS page.

Address forms follow [`port_316.md`](port_316.md): 3.16 relative `seg:off`,
image = `seg*16+off`, runtime CS = `6900h+seg`, logical = `69000h+image`,
physical = `300000h+logical` (third PGR, XA=1; 3.16 has no `0F E0`/`0F F0`).
Vailixi file = `(CS<<4)+IP-80000h`. Tags per [`AGENTS.md`](../AGENTS.md).

## 1. What stock already does

Sample New Sound's `Monitor:ON` is a digital loopback, not an analog path
(**PROVEN, code**; device meaning **HYPOTHESIS**, MAME L7A1045 model):

| Step | Vailixi | 3.16 | Effect |
|---|---|---|---|
| apply | `C6C2:182D` (0x4844D) | `1849:17F5` (0x19C85) | cache test, clear all 32 voices, then the three below |
| input | `D90C:0454` (0x59514) | `2F37:0456` (0x2F7C6) | 8255 ports 80/84/FA/FC; DMA ch2 (C001=2, mode 55h): ADC -> CPU ring |
| record | `D90C:0338` (0x593F8) | `2F37:033A` (0x2F6AA) | DMA ch3 (mode 59h): CPU ring -> DSP; record voice 0 (+16 stereo); port 68 = 40h / 58h |
| monitor | `D90C:0006` (0x590C6) | `2F37:0008` (0x2F378) | voice 31 (+3 stereo) loops the range the record voice writes; reg 7 5050h mono, 5000h/0050h stereo; key-on RMW of port 68 |
| teardown | `D90C:016C` (0x5922C) | `2F37:016E` (0x2F4DE) | clears all 32 voices, control 0, 8255 restore, all-voice reg-1 init |

The only call of the monitor routine is gated by the Monitor byte
(3.16 `1849:1843`). Settings: Input/Mode/Monitor at 3.16 DS `8293/8294/8295`
(Vailixi `85A5/85A6/85A7`).

Stereo stock keys on only the last-selected voice (3); voice 31 is programmed
but never keyed on that path (**PROVEN, code**). Whether hardware keys the pair
is **UNDETERMINED** (bench item T4).

## 2. Why the stock path cannot simply stay on

| # | Conflict | Evidence |
|---|---|---|
| C1 | CPU ring `SND_SEG:0000..47FF` is 3.16's general staging buffer (SND/SET/PAR/Akai load, SND save, Edit Sound, copy, compaction, wave view, SCSI utils) | **PROVEN** (all 290 relocated `539D` words classified) |
| C2 | Wave ring lives inside a temporary sound that covers all free wave memory, freed on exit | **PROVEN** |
| C3 | Allocator `205E:0008` round-robins voices 0..1Fh and treats a zero stop timer as free: it hands out 0/3/16/31 | **PROVEN** |
| C4 | Wave transfer `20BA:0002` (27 sites + cave) reprograms voice 0 and ch3 and ends with `OUT 68,80h` | **PROVEN** bytes; "stops recording" **HYPOTHESIS** |
| C5 | Stop-all `20ED:0D99` (Edit Sound, Sample page, Sync page, cave) stops every channel | **PROVEN** |
| C6 | All-voice reg-1 init `2338:0000` runs during MIDI sample dump and sampling | **PROVEN** |
| C7 | Stock apply/input/teardown clear all 32 voices and busy-wait | **PROVEN** |
| C8 | Digital input lock retry exists only in the Sample page tick | **PROVEN** |

## 3. Design

### 3.1 Resources

- **Voices.** Mono: 0 (record), 31 (monitor). Stereo: 0, 16 (record), 31, 3
  (monitor). Reserved only while Thru runs; mask empty = stock allocator.
- **Wave ring.** Top 2000h words (16 KB) of wave RAM, carved out of the pool
  by one byte: image `0x2209A` (`21E7:022A`, Vailixi `0x50E24`)
  `05 30 F8 83 D2 FE` -> `05 30 D8 83 D2 FE` (pool length = banks<<20 −
  107D0h − 2000h). Base = `21E7:0206()` + 107D0h. Allocation, compaction,
  rebuild, Delete All, loaders and every free-memory display then exclude it.
  Thru refuses to run if the bank count `[F16A]` is 0. Mono loops one 1FF0h
  range; stereo uses two 0FF0h halves 1000h apart (stock keeps a gap between
  halves; its reason is **UNDETERMINED**, so a gap is kept). Ends are 16-word
  aligned (DSP reg 1 carries A[23:4]).
- **CPU ring.** A dedicated buffer in the cave home (proposed 800h bytes,
  16-byte aligned, inside one 64 KB physical page), passed to the DMA setup as
  the stock routine `2F37:01CF` would compute it. Size does not set latency if
  ch2 and ch3 run at one rate (**HYPOTHESIS**; bench T2).

### 3.2 Engine (`mods/thru316.inc`)

All DSP/DMA writes at task level under AMX resource 1 (`T_D1F7_0126`),
never in an ISR.

- `thru_arm`: input select as `2F37:0456` (analog and digital branches,
  without its 32-voice clear); DMA ch2/ch3 and record voice(s) as
  `2F37:033A` with the Thru rings; monitor voice(s) as `2F37:0008` with reg 7
  from the Level setting; key on each monitor voice explicitly. Digital: if
  port 84 bit 6 shows no lock, leave Thru stopped and show `No digital lock`
  on the page.
- `thru_disarm`: stop the reserved voices by direct writes, mask ch2/ch3,
  clear the DMA-start bit of port 68, restore the 8255 bits as `2F37:016E`
  does, without touching other voices.
- `thru_suspend` / `thru_resume`: nesting counter around the guarded paths.
- `thru_apply`: disarm/arm to match the settings; idempotent.

### 3.3 Hooks (3.16 image offsets)

| Id | Site | Bytes | Purpose |
|---|---|---|---|
| M1 | `0x16513` (`1650:0013`) | `1e68fc4f9a6500270483c404` -> `9a{thru_menu_text}`+7×`90` | Mixer menu text with `6.Input thru` |
| M2 | `0x16532` | `6a05` -> `6a06` | accept option 6 |
| M3 | `0x1654D` | `98488bd883fb04` -> `ea{thru_menu_dispatch}9090` | option 6 opens the page; 1-5 stock (`1650:0054`), exit `1650:0088` |
| H1 | `0x15AD2` (`15AC:0012`) | `9a0700d702` -> `9a{thru_mode_hook}` | re-apply on every mode change and after boot parameter load |
| H2 | `0x1A04D` (`19F9:00BD`) | `9a0f004918` -> `9a{thru_sample_wrap}` | suspend around Sample New Sound (its only caller) |
| H4 | existing `tc_par_apply` (`0x2D68A`) | FJMP -> FCALL + re-apply | re-apply after .PAR load |
| A1 | `0x206BA` (`205E:00DA`) | `8b5efe83c320` -> `ea{thru_alloc_scan}90` | allocator scan skips reserved channels (also zeroes their local W copy so the >=3-voice steal pass ignores them) |
| B | `0x234D0` (`234D:0000`) | `558bec ba0100` -> `ea{thru_stop_guard}90` | one-channel stop ignores reserved channels (covers stop-all) |
| C | `0x20BA2` (`20BA:0002`) | `558bec83ec0e` -> `ea{thru_xfer_guard}90` | wave transfer: suspend, run, resume |
| E | `0x231E7`, `0x23228` | `9a00003823` -> `9a{thru_reg1_init}` | all-voice reg-1 init skips reserved channels |
| F | `0x2209A` | `f8` -> `d8` | pool excludes the ring |

Also: `xp_play_stay` option bound 5 -> 6; on enable set allocator scratch
`[F166]` to a non-reserved channel; defensive re-allocate in
`mute_voice_alloc_wrapper` if a reserved channel ever comes back. New profile
targets: `205E:00E0`, `205E:0174`, `234D:0006`, `20BA:0008`, `1849:000F`,
`1650:0054`, `1650:0088`, `02D7:0007`; `T_D21F_0008`/`T_CF92_000C` join
`HOOK_TARGETS`.

### 3.4 Page (Mixer/Effects -> 6)

```
     0123456789012345678901234567890123456789
r0   ============== Input Thru ==============
r1   Thru:OFF       Input:ANALOG
r2   Level: 31
r6   ========================================
```

- Thru: OFF / MONO LFT / MONO RGT / STEREO; Input: ANALOG / DIGITAL (stock
  list DS `5246`); Level 0-100 (100 = reg-7 byte FFh; 31 ~ stock monitor 50h).
- Stored in the parameter-block reserve (saved to NVRAM and .PAR, zero-filled
  by Init PAR): `831F` mode (0 = OFF), `8320` input, `8321` level stored
  XOR 31 through a cave shadow so zero-fill gives 31. `8322` stays spare. On
  Vailixi-EPROM machines nothing in this block survives power-off
  ([`vailixi_features.md`](vailixi_features.md) F10).
- Built like `xparams316` (`du_title`, `T_B354_01C6`, `T_B354_03B1`,
  `T_B060_035D` with flags 0); each commit calls `thru_apply`.

## 4. Verification

Software (MAME, all four EPROM sets), new `emu/test_thru316.py`:

- page pixels, field editing, NVRAM/.PAR persistence, menu digest update in
  `emu/fixtures/display_tour316.json`;
- arm/disarm port trace (`60/62/64/66/68`, `C000-C00F`, 8255) equal to the
  design, per mode;
- allocator never returns, steals or stops 0/3/16/31 under 32+ note load;
  stop-all and MONO/Cutoff leave them;
- guard C pauses/resumes around SND load/save, Edit Sound, compaction; H2
  hand-off to Sample New Sound and back; free memory 16 KB smaller;
- Thru OFF: allocator, transfers and screens behave as before; full release
  gate (289 tests) and `tests/` pass; cycle budgets re-pinned if needed.

MAME limits: DMA ch2 has no device (no input samples), and the L7A1045
model's DMA writes advance voice 0's position without wrapping, so with Thru
on the emulated record voice writes past the ring through wave RAM. Thru
tests must run in isolated cases, or the fork's `dma_w16_cb` must wrap at
voice 0's end/loop (a change to the MAME fork, owner decision).

Bench (physical, deferred):

| Id | Observation |
|---|---|
| T1 | audible thru on Play/Record, Program, Song, Mixer pages, mono L/R and stereo |
| T2 | latency (loopback click), drift over 10 min, no clicks at the ring wrap |
| T3 | dropouts only during disk/edit transfers; resumes afterwards |
| T4 | stereo: both monitor voices keyed; L/R not swapped |
| T5 | digital input lock / unlock |
| T6 | key-on RMW of port 68 (`2325:00DB`) while recording: no glitch |
| T7 | Sample New Sound still records and monitors as stock; Thru resumes after |
