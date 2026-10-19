# THRU BENCH 01 (universal OS 3.16 build: Lazy Chop + Input Thru) physical checklist

**Purpose:** first hardware run of Lazy Chop ([`lazy_chop.md`](lazy_chop.md))
and Input Thru ([`input_thru.md`](input_thru.md)), with a short regression
pass over the bench-proven PMONEY features.  Everything new is **PROVEN in
MAME only**; whether Thru passes audio at all is **UNDETERMINED** until this
bench (MAME has no input device).

**Build:** branch `claude/input-monitoring-passthrough-o4qvp1`, commit
`8f463c2` (= `port-316` `48d62ff` Lazy Chop + Input Thru).

| File | Size | SHA-256 |
|---|---:|---|
| `build/mods/WAVE316.SYS` | 499,303 | `e24a38c80a78b41cf2bb75405308597cd2cbd6a4c18cffc32e2fa7e19964ac78` |
| `build/mods/WAVE316.img` | 1,474,560 | `21b5cf72220b7db433aeeeb2825c85be4673de8b12e0308a012352f3122d18bf` |

The image holds `STARTUP.SYS` (the SYS above), `SINE441.SND`, `STEREO1.SND`.
The banner still reads `WAVEFORM/ZONES/MUTE GROUP` / `PMONEY BETA 1.0`; the
build is identified by Mixer/Effects showing `6.Input thru`.

## Deploy

```bash
shasum -a 256 WAVE316.img        # must print 21b5cf72...18bf
python3 build/deploy_wave316_usb.py --expect-sha 21b5cf72220b7db433aeeeb2825c85be4673de8b12e0308a012352f3122d18bf --select
```

As for BENCH 08: the script adds the image in the first free USB slot and
selects it in `IMAGE_A.CFG`; rollback is the backup `IMAGE_A.CFG` it names.
Use copies of program/sound disks (PGM/APS saves carry the mute trailer).

## Setup

- Audio source at line level into **RECORD IN** L and R (a stereo source with
  something different on each side helps: e.g. drums left, a tone right).
  RECORD LEVEL knob and rear GAIN as for sampling.
- Monitors or headphones on **STEREO OUT**.  Start with the volume low:
  Thru with a microphone near the speakers feeds back.
- For gate 5: a DAW (or any two-channel recorder) and a splitter cable.
- Optional: an S/PDIF 44.1 kHz source for gate 9; a SCSI disk for gate 8.
- On this machine (Vailixi 3.50 EPROM) no PMONEY setting survives a power
  cycle ([`vailixi_features.md`](vailixi_features.md) F10): Thru is OFF at
  every boot.  That is expected, not a failure.

## Gates (about 75 minutes; photograph any failure and the screen before it)

| Gate | Steps | Pass means |
|---|---|---|
| 0 Boot | Power on with the USB in; Soft Key 4 cancels the SCSI search. Other → Soft Key 3 (System Information). Mixer/Effects. | Banner as above, Play/Record. Sound memory free **16K less than BENCH 08** (expect 32,620K; it was 32,636K). Mixer menu row 5: `5.Effects` … `6.Input thru`. |
| 1 Regression | BENCH 08 gates 1-3 in brief: Disk → 7 → load `SINE441`; Program/Sounds → 6, Help (wave view), Exit; CHOP ZONE to 4 zones; mute groups pads 1/2 group 1. | As BENCH 08: waveform, `ZONE000`-`ZONE003`, pad 2 stops pad 1. |
| 2 Lazy Chop take (H-LC1) | Load or sample a drum loop (2-4 bars). Program/Sounds → 6, Help, then Right, Right (ZONE field): soft keys `<Lazy chop> <Snap ON><To program> <Exit>`. Soft Key 1 `<Lazy chop>`: `Hit a pad to start`. Hit pads in time with the loop as it plays; Soft Key 3 `<Done>` (or let it end). | Playback starts at the first hit; a marker lands at each hit; `Chops: nn` counts. Note how late the markers sit against the transients you hit (that is the latency constant `K`, decision D9). |
| 3 Lazy Chop refine + Convert | Pads 1..n play slices; a pad selects its slice; move a start with the wheel, leave the field (snap); Soft Key 2 toggles `<Snap ON>`/`<SnapOFF>`. Soft Key 3 `<To program>`, accept the defaults (Choke ON), `<Do it>`. Main Screen; play the pads. | Slices play once each, cut each other (choke); the new program holds the slices on A01.. in order; names `<source>01`.. . Note any slice that sounds clipped or late (H-LC3). |
| 4 Thru on (T1) | Mixer/Effects → 6. `Thru:` `+` to `MONO LFT`, signal into the left input. Then `MONO RGT` (signal into the right). Then `STEREO`. Move `Level` 0 → 100 (Down, type or wheel). Leave with Main Screen. | `Status:ON`. MONO: the selected input heard **centred** on both outputs. STEREO: left input only on the left output, right only on the right (**T4**: say so if left is silent or the sides are swapped). Level changes the loudness at once; 0 silences. Thru keeps playing on Play/Record. |
| 5 Latency and wrap (T2) | Split one source: one leg into a DAW channel, one into MPC RECORD IN L; record the MPC's STEREO OUT on a second DAW channel (Thru MONO LFT). Record 10 s of clicks or a snare, then leave it 10 minutes and record again. Listen with Thru alone for a steady tick at about 5.4 Hz (mono) or 10.8 Hz (stereo). | Report the offset in ms at the start and after 10 minutes (any drift = ring slip). No periodic tick or buzz (the ring wraps every 185 ms mono, 93 ms stereo). |
| 6 Thru with playback (T6) | Thru STEREO. Load `STEREO1`, assign it to a few pads; record and play a busy 2-bar sequence (many pads, rolls). Edit Sound → Ply/Stp. Song mode play. | Thru stays clean while the sequencer and auditions play (no crackle on key-ons). Notes still play (28 voices left in stereo; steals are normal under heavy rolls). |
| 7 Disk and edits (T3, T9) | With Thru on: Disk → 7 → load `SINE441` from the floppy; Edit Sound → Do REVERSE ZONE and SILENCE ZONE; save the Sound to the floppy and load it back. | Thru goes **silent** during each load/save/edit and returns about 0.1 s after it ends. Every load reads correctly (no "internally corrupted", no read error); the reloaded Sound plays as saved. |
| 8 SCSI (T8, optional) | With Thru on: save a large Sound (> 1 MB) to the SCSI disk, load it back, play it. | No SCSI error; the Sound is intact. Note whether Thru drops or crackles during SCSI transfers (SCSI DMA runs beside Thru's DMA; not exercised in MAME). |
| 9 Digital (T5, optional) | Mixer/Effects → 6: `Input:` DIGITAL with the S/PDIF source playing. Then unplug it, Main Screen, Mixer/Effects → 6 again. | With the source: `Status:ON`, digital audio heard. Unplugged: `Status:NO DIGITAL LOCK` after re-entering the page. Replugged: back after re-entering. |
| 10 Sample New Sound (T7) | With Thru on: Program/Sounds → 5. Use the stock Monitor ON, Rec ready, record 2 s. Exit to Main Screen. | Sampling and its own monitor work as stock (Thru is off while the page is open); the new sample plays. Thru comes back after leaving. |
| 11 Off and stability | Thru `OFF`; then ON again and leave it 10 minutes on Play/Record; visit every mode key. Power-cycle at the end. | OFF is silent at once. No hang, no stray Record Ready, no drop-out. After the power cycle Thru is OFF (F10). |

## Report back

Pass/fail per gate with photos of: System Information, the Mixer menu, the
Input Thru page in MONO and STEREO, the Lazy Chop take (`Chops: nn`) and the
Slices to Program page, plus any error.  For gate 5 the offsets in ms (and
the DAW session if possible); for gate 2 how far the markers sit after the
hits (or a photo of the fine view on one marker).  Note anything audible:
clicks when Thru resumes, buzz, level jumps, left/right swaps.

## Results

(to fill in after the bench)
