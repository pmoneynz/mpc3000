# LCD MIRROR BENCH 01 (OS 3.16 floppy + LCD mirror over MIDI) physical checklist

**Experiment.** This is the first hardware run of the LCD mirror
([`lcd_mirror_midi.md`](lcd_mirror_midi.md)). The unit boots stock OS 3.16 from
the floppy, with a small resident addition. Every 10 ms it sends what is on the
screen as SysEx out of **MIDI OUT D** (protocol 2), and a laptop draws it.
Everything below is **PROVEN in MAME only**, on all four EPROM sets, with the CPU
at the board's 16 MHz. A passing emulator run is an
emulator result. Only this bench is a hardware result.

**Build:** branch `lcd-mirror-midi`, `python3 mods/build_lcdmirror316.py` (port 4 = OUT D).

| File | Size | SHA-256 |
|---|---:|---|
| `build/lcd_mirror/LCDMIRROR_316.img` (experiment) | 1,474,560 | `67b99755da20a470c26b104a7aa7b96e44f1ebf838f4408920364ea1ba7243da` |
| `build/lcd_mirror/M3K316.SYS` (on that image) | 469,660 | `20823ea4f7f9fc2f1eff6d18c7fda6c667c5199ca916cfc4f186309a00030e76` |
| `build/lcd_mirror/STOCK_316.img` (control: stock `M3K316.SYS`) | 1,474,560 | `2752cf3e29141880a1f9949a68d2dfdf02b3dc7f536998632844ccf10946c3e1` |

**Telling the floppies apart:**
- The experiment's boot banner reads **`System 3.16 LCD mirror`**.
- The control reads `System 3.16 (02/20/05)`.

## Deploy (FlashFloppy)

```bash
shasum -a 256 build/lcd_mirror/LCDMIRROR_316.img build/lcd_mirror/STOCK_316.img
```

1. Check both hashes against the table.
2. Back up the USB stick's `IMAGE_A.CFG`.
3. Copy each image into a **free** `Disk_NN.IMG` slot. Never overwrite a slot.
4. Point `IMAGE_A.CFG` at the experiment's slot. FlashFloppy is powered with the MPC, so the slot must be chosen before power-on.

To switch to the control, change `IMAGE_A.CFG` to the control slot with the power off.

**Rollback:** power off, then restore the backed-up `IMAGE_A.CFG` (or remove the USB stick). The EPROM OS boots as before. Nothing on the MPC is changed: no EPROM, no NVRAM write by the mirror.

## Receiver setup

**Cabling:** MPC **MIDI OUT D** → USB-MIDI interface IN → laptop. Use a known-good interface if you have one; cheap cables that cut long SysEx are themselves a finding (LM-H5).

**Viewer:**

```bash
python3 -m pip install python-rtmidi
python3 tools/lcd_mirror_midi_viewer.py --port "<part of the interface name>" --log build/lcd_mirror/bench01.log
```

- The window needs a Python with Tk. On this Mac the Homebrew 3.15 has no `_tkinter`: add `--headless`. It prints each screen once it has settled (0.1 s with no new message): the text with the cursor marked by `^`, or on the Mixer page the 240×64 pixels.
- Both modes show six counters: `msgs drops dups bad aborted foreign`, and how long ago data last arrived. The log records every message and every counter change. Keep it: it is the bench record.
- If the interface is unplugged, the viewer notices within 2 s and reconnects when it comes back.
- **Use OUT D for the mirror alone.** Keep MIDI clock, MTC and Sample Dump off OUT D except in gate 3 (notes LM-H8).

## Predicted observations (from MAME at 16 MHz)

- **Boot:** the unit boots 3.16 from the floppy as stock does. About 2 s after 3.16 starts, the viewer receives HELLO (`proto 2, mod 2, OS 3.16`) and shows the boot screen, then Play/Record once you cancel the SCSI search.
- **Changes:** cursor moves appear within about 0.02 s, wheel edits within about 0.05 s, whole page changes within about 0.25 s of the key press.
- **Mixer:** the Mixer page (Mixer/Effects → 1) appears as pixels within about 0.9 s.
- **Idle:** with nothing changing, a HELLO every 5 s, and a full repaint every 15 s.
- **Transport:** during count-in, wait for key, play and record the viewer stays frozen on purpose (the mirror sends nothing). It catches up within about 0.25 s of Stop.
- **Your own MIDI on OUT D** (pads routed to OUT D, for example) pauses the mirror for 0.4 s after each message.
- **Counters:** `drops 0`, `dups 0`, `bad 0`, `aborted 0`.

## Gates (about 45 minutes; photograph any failure and the screen before it)

| Gate | Steps | Pass means |
|---|---|---|
| 0 Boot | Experiment slot selected. Power on; Soft Key 4 cancels the SCSI search. | Banner `System 3.16 LCD mirror`; Play/Record, as with the control. Viewer: HELLO, then the same screen. No `System Error`, no hang. |
| 1 Walk | Main Screen; Down; wheel +1 (Trk 2); Other; Disk; Program/Sounds; Mixer/Effects; 1 (Mixer page); Main Screen; Up; wheel +2 (Seq); Tempo/Sync; Soft Key 1 (Sync). | The viewer shows each screen, character for character, within the predicted times. Mixer pixels match the LCD (faders, labels). Return to text repaints fully. |
| 2 Idle | Leave Play/Record for 30 s. | About 6 HELLOs and 2 FULL repaints in the log, `drops 0`, picture unchanged. |
| 3 Clock on the same output | Tempo/Sync → Soft Key 1 → Right → wheel to `MIDI clock:OUT D`. Flip a few pages (stopped, clock running), then Main Screen, Play 10 s, Stop. Set the clock back to OFF afterwards. Optional: a DAW listening to the same interface sees the clock. | The viewer keeps following while stopped with the clock on; the DAW tempo stays steady at 120. During play the viewer is frozen and the clock arrives. After Stop the viewer catches up; `drops 0`, `bad 0`, `aborted 0`. |
| 4 Other outputs | `MIDI clock:OUT A` (a DAW or monitor on OUT A if available). Play 5 s. | OUT A gets the clock, OUT D gets nothing while playing; mirror traffic never appears on OUT A. |
| 5 Sequencer timing (LM-H3) | Record a 1-bar 16th-note pattern (one pad, or notes to an external synth on OUT A). Play it 30 s on the **experiment**, then on the **control** floppy. If you can, record OUT A into a DAW both times. | No audible difference, including the first note after Play. DAW: first-note offset and jitter equal within about 1 ms (the bound if not is ≤ 20.5 ms on the first note). |
| 6 MIDI input under load (LM-H2) | The mirror only sends while stopped, so test there. From a DAW into **MIDI IN A**: a dense stream (16ths at 160 BPM plus a continuous CC sweep) for 30 s, while you change pages every 2 s so the mirror keeps sending. If the MIDI page offers a soft thru, route IN A to OUT A and record OUT A in the DAW; otherwise let the notes play a program and listen. Repeat on the control. | Soft thru: the DAW recording of OUT A holds every note sent, on both floppies. Without thru: no drop-outs or stuck notes that the control does not also show. |
| 7 Disk and errors | Disk → save the sequence to the floppy, load it back. Then fill sequence memory until 3.16 reports it (optional). | Load and save work as stock. After an error box is dismissed, the viewer repaints (FULL in the log). |
| 8 Control A/B | Power off, select the control slot, power on, do gates 0 and 1 with the viewer running. | Control: stock banner; the viewer receives nothing (no HELLO). |

## Falsifiers → stop condition

Stop at the first of these:
- boot hang or `System Error`;
- a screen the viewer does not follow, or shows wrong after its settle time;
- MIDI data on OUT D corrupting the stream (`bad` or `aborted` above 0, or garbage in the viewer);
- sequencer timing audibly affected with the mirror running (gate 5);
- any OS MIDI feature misbehaving (clock, input, start/stop).

**Stop:** power off, select the control slot (or remove the USB stick), and record the observation against image SHA-256 `67b99755…43da` in [`lcd_mirror_midi.md`](lcd_mirror_midi.md) §7 (LM-H1..H5), with the viewer log and photos.

## Results

(not yet run)
