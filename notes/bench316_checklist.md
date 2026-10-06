# WAVE BENCH 08 (universal OS 3.16 build) physical checklist

**Purpose:** first hardware run of the universal build (`WAVE316.SYS`, marker
`WAVE BENCH 08`): the mods on OS 3.16, which every MPC3000 EPROM can load.
Everything below is **PROVEN in MAME only** (notes/port_316.md). On Peter's
Vailixi machine 3.16 loads at segment 6900, the case where stock 3.16
corrupts itself after recording, so gate 4 matters most.

**Image:** `build/mods/WAVE316.img` (`STARTUP.SYS`, `SINE441.SND`,
`STEREO1.SND`); hashes in `build/mods/WAVE316.json`. BENCH 07 stays in
`Disk_01.IMG`.

## Deploy

```bash
python3 build/deploy_wave316_usb.py --expect-sha <image sha256 from WAVE316.json> --select
```

This adds the image in the first free slot (`Disk_07.IMG` on the current USB)
and makes `IMAGE_A.CFG` select it at power-on. **Rollback to BENCH 07:** copy the
backup's `IMAGE_A.CFG` (named in the script's output) back onto the USB.

Use copies of any program or sound disks; this build writes the mute trailer
into PGM and APS files it saves.

## Gates (about 40 minutes; stop at the first failure and photograph it)

| Gate | Steps | Pass means |
|---|---|---|
| 0 Boot | Power on with the USB in. Time "Loading files" to the banner. Soft Key 4 cancels the SCSI search. | Banner `WAVE BENCH 08`, then Play/Record. Note the load time (stock 3.16 takes about 45 s on hardware per its PDF). |
| 1 Wave view | Disk → 7 → load `SINE441`. Program/Sounds → 6, Help. Wheel on Start/End, Soft Key 3 Fine/Full, Up/Down zoom, Soft Key 1 play, Soft Key 4 Exit. | Waveform shown (sine, flat, ramp); edits stay ordered; audition plays the selection; Exit returns to Edit Sound. Photo of the view. |
| 2 CHOP | In the view set 4 zones (ZONE total field), Exit; on Edit Sound choose `Do:` → `CHOP ZONE` (the 9th option, after REVERSE ZONE), press `<Do>`. Leave Edit Sound and return. | `ZONE000`–`ZONE003` created, `SINE441` still selected after returning. |
| 3 Mute groups | Assign SINE441 to pads A01–A03 (Program/Sounds → 1). Program/Sounds → 0: Enabled ON, pads 1 and 2 group 1, pad 3 Off. Hit pad 1, then pad 2. Soft Key 1 (Apply All): prompt; Soft Key 4 cancels. | Pad 2 stops pad 1; pad 3 does not; Apply All asks first. Photo of the page and the prompt. |
| 4 Sequence memory (pool fix) | Main Screen. Note the free sequence memory shown (expect 411K on this machine: 28K less than stock 3.16, so 3.16 cannot write sequences over its own code). Rec+Play, hit pads for 30 s, Stop. Press Song, then Main Screen, then Disk. | Song screen appears; Main Screen and Disk respond; the recorded sequence plays back. Stock 3.16 hangs at this step in MAME on 3.12/Vailixi EPROMs. |
| 5 Save/load | Disk: save the program (PGM) and all programs (APS) with groups set; Program/Sounds → 4 initialise; load them back. | No error; groups return. |
| 6 Stability | Visit every mode key from the wave view and the mute page; leave it running a few minutes. | No hang, no stray Record Ready. |

## Report back

Photos of the banner, wave view, mute page, the Apply All prompt and any
error; the boot time; the free sequence memory figure; pass/fail per gate.
Return the USB for checks of the saved files.

## Results (2026-10-06, Peter's MPC3000: Vailixi 3.50 EPROM, L = 6900, about 32 MB sound memory)

All gates **PASS** (PROVEN, hardware, one session). Evidence: ten photos and a
69 s boot video kept by Peter (`IMG_4896 2.MOV`).

| Gate | Observation |
|---|---|
| 0 Boot | Vailixi EPROM screen, System Information (SND free 32,636K, SEQ free 484K, I-0055 active), "Loading files", banner `WAVE BENCH 08`, SCSI search with `<Cancel>`. About 50 s from power-on to the banner (video). |
| 1 Wave view | SINE441 full view (`<Full>`, zoom 16) and fine view (`<Fine>`, ramp); a real drum loop also displayed with `ZONE:01/16`. |
| 2 CHOP | Pass (reported). |
| 3 Mute groups | Program/Sounds menu shows `0.Mute groups`; Apply All asks "Program 01: set all 64 pads to group 1" with `<Do it>`/`<Cancel>`, then all 64 pads read 1. Pad 02 shows `Note:36`, as 3.16's default map gives (pad 1 = 37, pad 2 = 36). |
| 4 Sequence memory | Other page: 98% free normally. Peter then filled sequence memory to 0% free: the machine kept working normally and refused further steps. This is the case where stock 3.16 on this EPROM writes the pool over its own code. |
| 5 Save/load | Pass (reported). |
| 6 Stability | Pass (reported). |

**PMONEY BETA 1.0** (`WAVE316.img` `a0b1ba10…`, USB `Disk_08.IMG`), same machine,
2026-10-06: the boot screen shows `WAVEFORM/ZONES/MUTE GROUP` and
`PMONEY BETA 1.0` centred under `Akai MPC3000`, then 3.16's own "Searching
floppy for startup files..." (PROVEN, hardware photo). Every cave byte before
entry316 is identical to the bench-tested BENCH 08.
