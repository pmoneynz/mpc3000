# MPC3000 for Apple silicon: playable emulator spec

**Status:** draft for review, 2026-10-05.
**Target OS:** Vailixi 3.50 (also stock 3.08, 3.11, 3.12 and floppy 3.16, plus
the Route A mods in `mods/`).
**Host:** Apple silicon MacBook Pro (M1 or later), macOS 14 or later.

This spec describes an instrument, not a debugger. The real MPC3000
firmware runs unmodified on an emulated board, and each part of the board
is replaced by a native macOS service. The rule from this repo still
applies: anything not established is a named boundary, and the app must
show where it fills a gap rather than present a guess as the real machine.

---

## 1. What "playable" means

| Requirement | Target |
|-------------|--------|
| Key or pad to sound | ≤ 10 ms on built-in speakers, not counting the OS's own processing time (which is authentic and is kept) |
| Timing jitter added by the host | ≤ 0.1 ms. Events are placed at an exact emulated time, not polled per frame |
| Audio dropouts | None in a 1 hour, 32-voice playback soak with a 128-frame buffer on a base M1 |
| Cold boot to Play/Record | ≤ 10 s wall time. ≤ 1 s with a saved state |
| Every front-panel control reachable | From the keyboard, trackpad, on-screen panel or a MIDI controller |
| Pad dynamics | Velocity and pressure from any source that has them |
| Files | Disks are Mac files or folders. WAV in, WAV out |

## 2. Constraints

1. **Real firmware only.** No high-level emulation of the OS. The panel
   microcontroller is the one exception (section 4, `U-PANEL-ROM`).
2. **One core.** The app links the same MAME fork (`pmoneynz/mame`,
   `mpc3000-accuracy`) that the headless harness in `emu/` tests. A fix
   lands in one place, and the harness suites guard the app.
3. **No ROMs in the app.** The user imports their own chip dumps (section 7.1).
4. **Two modes, named in the UI.** *Play* fills unknown hardware with
   documented stand-ins. *Lab* shows only what is established (hatched
   glyphs, logging on). Every stand-in is listed in section 11.

---

## 3. Architecture

### 3.1 Decision

**Embed the MAME core as a library under a custom macOS OSD layer, with a
native Swift app on top.**

| Option | Latency | Accuracy | Effort | Verdict |
|--------|---------|----------|--------|---------|
| A. Stock MAME window + layout + Lua | ≥ 40 ms (20 ms audio chunks, per-frame input polling, frame throttle) | Same as harness | Small | Not playable |
| **B. MAME core as a library, custom OSD, Swift app** | ~10 ms (section 5) | Same as harness | Medium | **Chosen** |
| C. New core written from scratch (Swift/C++) | Best possible | Starts over. Loses the validated V53, PGR, DMA and wait-state work | Very large | Rejected |
| D. libretro MAME in a RetroArch-style host | Frame-based input and audio | Same | Medium | Same limits as A |

Why B:
- MAME's split between machine and OSD (`src/osd/`) is designed for this.
  A native Cocoa OSD (`src/osd/mac`) already exists to start from.
- The headless harness, the 19 emulator tests and the OS 3.16 suites keep
  running against the same commit.
- The license headers look permissive. `src/emu`, `src/lib/util`,
  `src/osd/mac`, `src/frontend/mame` and the device files this driver uses
  (`nec`, `v5x`, `l7a1045`, `hd61830`, `upd765`, `mb87030`, `te7774`) carry
  BSD-3-Clause headers, with no GPL headers in those directories. The full
  linked set, including `3rdparty/`, still needs an audit (section 14).

### 3.2 Components

```
┌──────────────────────────── Swift app (SwiftUI + AppKit) ───────────────────────────┐
│  PanelView     LCDView (Metal)   InputRouter      DiskManager     Library/Settings  │
│  (keys, touch) 240x64 1bpp       layers, maps,    images, folder  ROM import, NVRAM │
│  LEDs, pads    glass shader      MIDI profiles    disks, WAV↔SND  states, profiles  │
│        │             ▲                 │                 │                          │
│        ▼             │                 ▼                 ▼                          │
│  ┌───────────── MachineController (Swift wrapper over C API) ─────────────┐         │
│  │  AudioIO (AUHAL, 44.1 kHz, 2 or 10 ch)    MIDIIO (CoreMIDI, virtual ports) │      │
└──┼─────────────────────────────────────────────────────────────────────────┼─────┘
   │ C API: libmpc3k.h                                                       │
┌──▼─────────────────────────────────────────────────────────────────────────▼─────┐
│ libmpc3k (C++)                                                                    │
│   OSD "mpcapp": sound sink → SPSC ring (back-pressure pacing)                     │
│                 MIDI module → CoreMIDI bridge callbacks                           │
│                 LCD frame hand-off, LED notifier, no MAME UI                      │
│   MAME emu core (scheduler, memory, save states)                                  │
│   mpc3000 driver + app event port (timed panel frames, velocity, pressure)        │
│   V53 · L7A1045 · HD61830 (LC7981) · uPD72069 · MB89352 · TE7774 · 8255 · 8254    │
└───────────────────────────────────────────────────────────────────────────────────┘
```

MAME runs one machine per process. One app window drives one machine. Run
a second machine as a second process.

---

## 4. Hardware to Mac mapping

The status column comes from [`notes/emulator.md`](notes/emulator.md) §6–7
and the gap review.

| MPC3000 part | Emulated by | Mac side | Status and boundary |
|--------------|-------------|----------|---------------------|
| V53 CPU (16 MHz), EPROM, 1 MB RAM, wait states, refresh | MAME NEC core + fork | One emulation thread (section 5) | Waits **PROVEN** registers, model §7. Base instruction timings are MAME's (`U-V53-TIMING`) |
| Battery NVRAM (`0x500000`) | `nvram` device | File per machine profile | Chip LC3517 **HYPOTHESIS**. Persistence is exact |
| LCD, LC7981 240×64 | HD61830 model | Metal view, integer scaling, STN shader; text copy and VoiceOver in character mode | 55 of 96 ASCII glyphs recovered. **Digits 2, 3, 5, 6, 7, 9 are not** (`U-LC7981-CG`); see 11.1 |
| Front panel MCU (uPD78C10) | Not emulated: ROM not dumped | App event port sends the link frames the OS parses (`90`, `A0`, `B0`, `E0`; [`notes/panel_link.md`](notes/panel_link.md)) | OS meaning **PROVEN**. Scan rate, velocity curve and slider scale are stand-ins (`U-PANEL-ROM`) |
| 16 pads (velocity, pressure) | Panel frames `90 kk vv` / `A0 kk vv` | Keyboard, trackpad, on-screen pads, MIDI pads (section 6) | Frames **PROVEN** (code). The current HLE always sends `7F`; the fork must change that (C2) |
| Data entry wheel | `E0` frames | Two-finger scroll with haptic detents, `[` `]` keys, MIDI relative CC | **PROVEN** |
| Note Variation slider | `B0 xx vv` | ⌥-scroll, on-screen fader, MIDI CC | Value scale **UNDETERMINED** |
| 16 LEDs (two HC259 latches) | `led0`–`led15` outputs | Panel LEDs, compact strip; Play LED drives the Space key's play/stop toggle | Wiring per MAME header |
| Floppy (uPD72069, 3.5" HD, FAT12) | MAME FDC + floppy image | `.img` files, or a Mac folder built into a FAT12 image | 3.50 reads FAT12 1.44 MB images: **PROVEN (trace)** (`emu/snd.py` disks) |
| SCSI (MB89352) | `nscsi` hard disk | Disk image files, ID 0–6 | OS disk format **UNDETERMINED** (D23). The OS formats a blank image; to be verified |
| Sound DSP L7A1045, 32 voices, 44.1 kHz | MAME model | AUHAL output: stereo, or 10 channels (stereo + 8 individual outs) | 33.8688 MHz / 768 = 44 100 Hz. Voice, filter and mix accuracy not validated (`U-DSP-AUDIO`) |
| Sampling input (ADC) | Not modelled | Audio input device (planned) | Blocked on D22 sampling path. **WAV import covers loading sounds in the meantime** |
| Sound memory board + SIMMs | Fork decode model | Profile setting. Default 32 MB | Sizes match the manual: **PROVEN (trace)** |
| TE7774 UART: MIDI In 1-2, Out 1-4, panel link | MAME model (registers guessed) | CoreMIDI virtual ports and device routing | All channels forced to 31 250 8N1 (`U-TE7774`) |
| Sequencer clock (TCT1, 2 MHz, 96 PPQ) | V53 TCU | Host MIDI timestamps derived from emulated time | Model in [`notes/sequencer_model.md`](notes/sequencer_model.md); TCT1 does not use TCLK |
| External 8254 (FSK sync out) | Device present, output not routed | Optional extra audio channel (later) | Out of MVP |
| Footswitches (HC365 bits 3-4) | Read as 0 today | Keys, MIDI CC64, or a USB pedal via CoreMIDI | Polarity **UNDETERMINED** |
| I-0055 SMPTE option | Probe only | Not offered | `U-I0055` |
| Volume / record / headphone knobs (analog) | Not in the CPU path | App gain controls; macOS volume | Analog, outside the emulation |

---

## 5. Real-time design

### 5.1 What MAME does today, and why it is not enough

| Mechanism | Today | Effect |
|-----------|-------|--------|
| Sound hand-off | `sound_manager` updates at `STREAMS_UPDATE_FREQUENCY = 50` (`src/emu/sound.h:126`) | 20 ms audio chunks: at least 20 ms latency |
| Input | `ioport` values change once per video frame (80 Hz screen). The HLE scan timer reads them every 1 ms | Up to 12.5 ms of quantisation jitter |
| Pacing | Throttle sleeps per video frame | Machine time runs ahead and behind the audio device |
| Panel MCU | Placeholder ROM still executes `JR $` at 12 MHz | Burns host time doing nothing |

Measured speed: **4.6× real time** on M1 Max (`mpc3k -bench 90`, Vailixi
boot plus idle, one core, sound and video off). Speed under heavy voice
load is not yet measured (P0.1).

### 5.2 Threads

| Thread | QoS | Job |
|--------|-----|-----|
| Core Audio I/O | Real time (system) | Reads the ring. Never blocks or allocates. On underrun, fades to zero and counts the event |
| Emulation | User-interactive. Joins the device's audio workgroup (`kAudioDevicePropertyIOThreadOSWorkgroup`, `os_workgroup_join`) so it gets performance-core deadlines | Runs the machine in 1 ms slices and writes 44 frames per slice to the ring |
| Main | UI | Captures input and stamps it with `mach_absolute_time` |
| CoreMIDI | System | Stamps MIDI input and pushes it to the same event queue |

Disable App Nap for the life of the machine
(`ProcessInfo.beginActivity(.latencyCritical)`).

### 5.3 Pacing: the audio device is the clock

1. MAME runs unthrottled.
2. The sound sink in the OSD writes each 1 ms block to a lock-free SPSC
   ring. It blocks on a semaphore while the ring holds more than the target
   fill (default 3 ms, grows 1 ms after each underrun, up to 10 ms).
3. The audio callback signals the semaphore when it consumes data.

Emulated time is therefore tied to the output device's sample clock. Clock
drift between the two cannot accumulate.

Sample rate: the core produces 44.1 kHz. Offer to set the device to
44.1 kHz. Otherwise AUHAL converts the rate (a little extra latency).

### 5.4 Placing input in time

Each input event carries host time `h`. The app keeps the mapping between
emulated time and host time from the audio stream: sample `n` reaches the
speaker at the known output latency after it is consumed. The event is
scheduled at emulated time `E(h) + L`, where `L` is a fixed offset slightly
larger than the ring target plus one slice. In the driver, a timer fires at
that exact emulated time and sends the panel frame (C1).

Result: constant latency `L`, and no host jitter beyond the timestamp
resolution. The panel link still sends each 3-byte frame at 31 250 baud
(0.96 ms per frame), so simultaneous pad hits are spread out the way the
OS sees them over a serial link. The link baud rate itself is a
**HYPOTHESIS** ([`notes/panel_link.md`](notes/panel_link.md) §1).

### 5.5 Latency budget (target, to be measured in P0 and P3)

| Stage | Budget |
|-------|--------|
| Keyboard or trackpad to app event | 1–2 ms (measure per model) |
| Scheduling offset `L` (ring 3 ms + slice 1 ms) | 4 ms |
| Panel link frame | 0.96 ms |
| OS parse to DSP key-on | Authentic. Measure in emulation (P0.4) |
| Core Audio buffer, 128 frames | 2.9 ms |
| Device and safety offset (built-in speakers) | 1–3 ms |
| **Total, excluding OS processing** | **≈ 10–11 ms** |

---

## 6. Playing it on a MacBook Pro

### 6.1 Principles

- Every control acts as press and release, never as a one-shot. The MPC
  relies on held keys (Rec + Play, Erase + pad, Locate, 16 Levels). Key
  autorepeat is ignored.
- Two keyboard layers: **PLAY** (pads under the left hand, transport under
  the right) and **EDIT** (number row is the numeric keypad, letters are
  mode keys).
- **Caps Lock switches layers**, and its own LED shows PLAY. Tab is an
  alternative toggle. Some Macs delay Caps Lock activation; verify on each
  keyboard and fall back to Tab.
- Holding ⌥ shows each key's binding over the on-screen panel. Every
  binding can be changed; layouts are saved as presets.
- ⌘ shortcuts belong to the app only (disks, states, settings). They never
  reach the MPC.

### 6.2 Always active

| Mac key | MPC control |
|---------|-------------|
| Space | Play if the Play LED is off, Stop if it is on |
| ⇧ Space | Play Start |
| Return | Enter |
| Esc | Main Screen |
| ← ↑ ↓ → | Cursor keys |
| F1–F4 (or ⌃1–⌃4) | Soft keys 1–4 |
| `[` / `]` | Data wheel −1 / +1. With ⇧, ±10 |
| `` ` `` (backtick) | Help (the Vailixi wave view opens from Help) |
| Delete | Erase |
| Two-finger scroll | Data wheel, with a haptic tick per detent (`NSHapticFeedbackManager`) and acceleration |
| ⌥ + two-finger scroll | Note Variation slider |

### 6.3 PLAY layer (Caps Lock on)

Pads follow the MPC layout, with pad 1 at bottom left:

```
  1  2  3  4      →  pads 13 14 15 16
  Q  W  E  R      →  pads  9 10 11 12
  A  S  D  F      →  pads  5  6  7  8
  Z  X  C  V      →  pads  1  2  3  4
```

| Keys (right hand) | MPC control |
|-------------------|-------------|
| H J K L ; | Rec, Over Dub, Stop, Play, Play Start |
| M , . / | <<, <, >, >> |
| 7 8 9 0 | Bank A, B, C, D (the app presses Pad Bank until the bank LED matches) |
| Y U I O | Full Level, 16 Levels, After, Assign |
| G | Tap Tempo |
| T | Timing Correct |

Velocity from the keyboard: 100 by default, 127 with ⇧ held, 64 with ⌥
held. All three values can be changed. The OS's own Full Level and 16
Levels then apply as on the hardware.

Keyboard rollover and ghosting on Apple keyboards is **UNDETERMINED** for
4-pad chords. Test each supported model in P3 and record the chords that
fail.

### 6.4 EDIT layer (Caps Lock off)

| Keys | MPC control |
|------|-------------|
| 1–9, 0, `.`, `-`, `=` | Numeric keypad 1–9, 0, `.`, `−`, `+` |
| D P X M S O | Disk, Program/Sounds, Mixer/Effects, MIDI, Song, Other |
| E J L | Seq Edit, Step Edit, Edit Loop |
| T Y U | Tempo/Sync, Transpose, Simul Seq |
| A C W | Auto Punch, Count In, Wait For |
| I G K | Timing Correct, Tap Tempo, Locate |
| B N | Rec, Over Dub |
| Q V F Z | Full Level, 16 Levels, After, Assign |
| Tab | Pad Bank (when Tab is not the layer toggle) |

### 6.5 MIDI pad controllers: the best playing surface

A pad controller gives real velocity and pressure. Built-in profiles cover
the common 4×4 controllers (Akai MPD218/226, LPD8, Arturia BeatStep,
Novation Launchpad in note mode, Maschine in MIDI mode). MIDI learn covers
everything else.

| Controller message | Default routing |
|--------------------|-----------------|
| Note on/off | **Panel mode**: panel pad frame with the note's velocity. Behaves like the MPC's own pads, including bank, 16 Levels, Note Variation and recording |
| Poly or channel aftertouch | Pad pressure frame `A0 kk vv` for the held pad |
| Relative CC (encoder) | Data wheel |
| Absolute CC (fader) | Note Variation slider |
| CC 64 | Footswitch 1 |

**MIDI In mode** (per controller) instead sends the controller's raw
messages to emulated MIDI IN 1, so the OS treats it as an external MIDI
device, exactly as on a real MPC3000.

### 6.6 Trackpad pads (experimental)

The trackpad becomes a 4×4 grid. Finger positions come from public
`NSTouch` indirect touches; multiple fingers are allowed. NSTouch gives no
per-finger pressure, so velocity is fixed, and the Force Touch pressure
(`NSEvent.pressure`) is sent as aftertouch for the most recent pad. Off by
default.

### 6.7 On-screen panel

- **Full**: a vector-drawn faceplate (no Akai artwork or logos, section 14).
  Every button is clickable. Click and hold presses; right-click latches a
  button (for example hold Erase while hitting pads). A pad's velocity comes
  from the vertical click position.
- **Compact** (default on 14-inch screens): LCD, soft-key labels, 4×4 pads,
  transport, LED strip, and a strip showing the active layer.
- **LCD only**: for controller-driven setups. Works in full screen and
  Stage Manager.

### 6.8 LCD

- The 240×64 frame is copied from the HD61830 bitmap at every LCD refresh
  (80 Hz) into a triple buffer, and drawn by Metal at display refresh
  (ProMotion 120 Hz). Integer scaling only. The palette is the driver's
  backlight blue and lit pixels.
- An optional STN shader adds pixel gaps, slow response and contrast.
- In character mode the screen is text, read straight from display RAM:
  ⌘C copies it, and VoiceOver reads each row and the cursor cell.
- In graphics mode (for example the wave view) ⌘C copies a PNG.

---

## 7. Files and storage

Everything lives under `~/Library/Application Support/<App>/`.

### 7.1 ROM import

1. Drag in the LS/MS chip files. The app interleaves them and checks the
   SHA-256 against the known sets: Vailixi 3.50 linear
   `a52b7122…770c9` ([`PROJECT_GOAL.md`](PROJECT_GOAL.md)), and stock 3.08,
   3.11, 3.12.
2. An unknown set imports with a warning, and Lab mode records its hash.
3. The app writes a MAME romset per profile. It uses the same placeholder
   policy as `emu/romset.py` for the absent panel ROM and the LCD CG.

### 7.2 Machine profiles

A profile holds the OS (EPROM set, plus an optional boot floppy such as
`MOD350.img` or `M3K316.SYS`), sound memory (default 32 MB), SCSI devices,
its NVRAM file, and its saved states.

### 7.3 Boot and resume

- **Cold boot** runs unthrottled until the first Play/Record screen
  (about 36 s emulated, about 8 s at 4.6×), then switches to real time.
- **Warm start**: after the first good boot, save a full machine state.
  Launch restores it (target under 1 s). The state is invalidated when the
  ROM, the profile or the core build changes.
- **Quit** saves a state. Save and restore must round-trip in P1 (C8).

### 7.4 Floppy

- **Image mode**: mount and eject `.img`, `.hfe` and other MAME-supported
  formats. The drive slot accepts drag and drop.
- **Folder mode**: a Mac folder becomes a 1.44 MB FAT12 disk when inserted.
  Files the OS writes are copied back after 2 s with no writes and on eject.
  A changed file on both sides is a conflict: keep both, never overwrite
  silently. A folder over 1.44 MB is refused, and the files that do not fit
  are listed.

### 7.5 SCSI

Create a blank image (size presets) at an ID, and let the OS format it.
Reading files out of such an image depends on D23 (format undetermined),
so it comes after P4.

### 7.6 WAV and SND

- **Import**: WAV or AIFF to `.SND`, using the converter in `emu/snd.py`
  (16-bit, mono or stereo, 44.1 kHz). The app resamples other rates with
  `AVAudioConverter` before converting; this is separate from the
  44.1 kHz-only decision for the on-machine WAV mod
  ([`notes/wav_feasibility.md`](notes/wav_feasibility.md)). Dropping a WAV
  on the window adds it to the folder disk in the drive.
- **Export**: `.SND` from any disk to WAV.
- **Bounce**: record the stereo mix, or all 10 outputs, sample-accurately
  from the ring in emulated time, independent of the output device.

---

## 8. MIDI and sync

| Emulated port | CoreMIDI |
|---------------|----------|
| MIDI IN 1, IN 2 | Virtual destinations "<App> In A/B", plus any connected sources |
| MIDI OUT 1–4 | Virtual sources "<App> Out A–D", plus device routing |

- **Outgoing timestamps**: the emulated time each byte leaves the UART,
  mapped to host time plus the fixed output latency. MIDI clock to a DAW
  therefore has no host jitter. Clock period follows the sequencer model
  (TCT1, `N = floor(12 500 000 / T10)`; tempo truncates and runs 0–160 ppm
  fast, [`notes/sequencer_model.md`](notes/sequencer_model.md) §1).
- **Incoming**: scheduled at emulated time `E(h) + L`, like panel events.
  External clock follows the OS's own software PLL (§11 of that note).
- FSK and SMPTE: not in MVP.

---

## 9. Audio output

- AUHAL output at 44.1 kHz, 128-frame buffer by default; 64 and 256 are
  offered.
- **Stereo mode** sends the L/R mix to any device.
- **Multi-out mode** maps the stereo mix and the 8 individual outputs to
  the first 10 channels of an interface (map editable).
- Optional dither when converting to 24-bit.
- Master gain stands in for the analog volume knob; headphone and record
  level are not modelled.
- The diagnostics view shows the dropout counter, ring fill, emulation
  speed and measured round-trip latency.

---

## 10. Core changes required (MAME fork)

| ID | Change | Where |
|----|--------|-------|
| C1 | App event port: an SPSC queue of `{emu_time, kind, code, value}`; a timer fires at each event's emulated time and sends the panel frame. MAME input ports stay for the CLI and harness | `src/mame/akai/mpc3000.cpp` |
| C2 | Velocity in pad frames; pad pressure (`A0`); slider value (`B0`); footswitch bits on the HC365 | driver |
| C3 | Configurable sound update rate (1 kHz for the app; harness keeps 50 Hz unless tests pass at both) | `src/emu/sound.{h,cpp}` |
| C4 | OSD `mpcapp`: ring sink with back-pressure, CoreMIDI bridge, LCD frame and LED hand-off, MAME UI off | `src/osd/mpcapp/` (new) |
| C5 | Suspend the panel MCU while the HLE is selected (performance) | driver |
| C6 | `libmpc3k.h` C API: create(profile), run/pause, push_event, insert/eject disk, SCSI attach, get_lcd, get_leds, ring read, save/load state, fast-forward | `src/osd/mpcapp/` |
| C7 | Library build: link MAME's intermediate static libraries with the new OSD into an `.xcframework` | build scripts |
| C8 | Verify save and restore for every device, including floppy and SCSI images | driver and devices |
| C9 | "Play mode" CG font: fill unobserved glyph codes from a documented 5×7 font; Lab mode keeps the hatch | `emu/romset.py` equivalent in the app |

Every core change ships with a harness test, as for the wait-state work.

---

## 11. Known gaps and how the app handles them

| Gap | Effect on playing | Play mode | Lab mode | Closes with |
|-----|-------------------|-----------|----------|-------------|
| 11.1 LCD glyphs (`U-LC7981-CG`): 41 of 96 ASCII codes and all of `A0`–`FF` unobserved, including digits 2 3 5 6 7 9 | Numbers unreadable on many screens | Documented 5×7 stand-in font, marked in About | Hatched | More glass photos; an LC7981 datasheet |
| 11.2 Panel (`U-PANEL-ROM`): scan rate, velocity curve, slider scale | Feel differs from a real panel | Linear velocity; slider 0–100 % → 0–127 | Same, logged | Panel ROM dump |
| 11.3 DSP audio (`U-DSP-AUDIO`) | Tone may differ: interpolation, filter, levels | MAME model | Same | Recordings from a real unit, same sounds and settings |
| 11.4 Sampling input (D22) | Cannot sample live | WAV import | Same | Model the ADC path |
| 11.5 DMA bus contention (`U-DMA-BUS`), READY waits (`U-READY`) | CPU slightly fast during disk and DSP transfers | Accept | Same | Fork work + timing capture |
| 11.6 SCSI format (D23) | HD file exchange with the Mac | Image only | Same | Trace format |
| 11.7 Footswitch polarity | Pedal may be inverted | Invert toggle | Same | Schematic or hardware |

---

## 12. Verification

| Test | Pass condition |
|------|----------------|
| Harness parity | All `emu.test_mpc3k` tests and the OS 3.16 suites pass on the core commit the app ships |
| Event replay | A recorded event log (emulated timestamps) replays to an identical audio hash and identical LCD frames |
| Latency | In-app loopback: inject a pad event at host time T, detect the onset in the output; also a physical mic loopback on built-in speakers. Median ≤ 10 ms plus measured OS processing |
| Jitter | 1000 repeated pad hits: onset spread ≤ 0.1 ms after removing the link serialisation |
| Tempo | MIDI clock out at 120.0 BPM: periods match the sequencer model, host timestamp jitter ≤ 0.1 ms |
| Soak | 1 h, 32-voice sequence, 128-frame buffer, base M1: no dropouts |
| Controls | Every panel control triggered from keyboard, on-screen panel and a MIDI profile; the screen changes as in `emu/key_sweep.py` |
| Folder disk | Round trip: Mac → OS load → OS save → Mac file matches the OS output |
| Resume | 100 save/restore cycles mid-playback with no divergence from a straight run |

---

## 13. Phases

| Phase | Scope | Exit criteria | Size |
|-------|-------|---------------|------|
| **P0 Spikes** | P0.1 speed under 32-voice load; P0.2 overhead of 1 kHz sound updates; P0.3 static-library build with a null OSD running the harness; P0.4 measure frame-to-key-on time in emulation; P0.5 save-state round trip | Real-time factor ≥ 2.5× worst case, or a plan to get there; library build passes the harness | S |
| **P1 Core library** | C1–C8 | Harness parity through the library; C API documented; event replay test | M |
| **P2 MVP app** | LCD, stereo audio, keyboard layers, on-screen panel, LEDs, floppy images, NVRAM, ROM import, warm start | Playable on built-in keyboard and speakers; latency and soak tests pass | M |
| **P3 Playability** | MIDI controller profiles and CoreMIDI ports, velocity and pressure, scroll and haptic wheel, folder disks, WAV↔SND, Play-mode font, rollover survey | All section 12 tests pass | M |
| **P4 Studio** | Multi-out, bounce, SCSI images, MIDI sync polish, presets, trackpad pads | Studio tests pass | M |
| **P5 Fidelity** | Close section 11 items as evidence arrives (glyphs, panel, DSP, sampling) | Per item | Open |

**Later:** an AUv3 instrument. macOS runs AUv3 out of process, but
instances in one host share a process, and MAME runs one machine per
process. That needs one helper process per instance.

---

## 14. Decisions needed before P1

1. **Project rules.** [`TODO.md`](TODO.md) "Do not do" says *"Build an
   emulator except to answer a named item above"*, and AGENTS.md makes
   [`PROJECT_GOAL.md`](PROJECT_GOAL.md) win any conflict. This app is a new
   goal. Recommendation: a separate product repository that consumes the
   MAME fork and the harness, plus one line in `PROJECT_GOAL.md` naming it
   as a downstream consumer. The owner decides.
2. **License audit.** Of the full linked set, including `3rdparty/`, before
   any distribution.
3. **Name and artwork.** "Akai" and "MPC" are trademarks. The product name,
   icon and faceplate must not imply affiliation. Use a generic drawn panel.
4. **ROMs and OS licensing.** No firmware ships. Vailixi 3.50 is a
   commercial third-party OS; confirm its terms with Vailixi before any
   distribution beyond personal use.
5. **Distribution.** Developer ID plus notarization (recommended), or the
   Mac App Store (sandbox, plus security-scoped bookmarks for folder disks).
6. **Default panel stand-ins** (velocity values, slider scale) are product
   choices until 11.2 closes.
