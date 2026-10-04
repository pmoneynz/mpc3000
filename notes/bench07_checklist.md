# WAVE BENCH 07 physical checklist

**Purpose:** first hardware run of the BENCH 06 features and the review fixes
(PR `pmoneynz/mpc3000#1`). Every item below is **PROVEN in MAME only**; this
run turns them into physical observations or records where hardware differs.
Do the whole list on Peter's machine before any image goes to another tester.

**Image:** `build/mods/WAVEHW.img` (marker `WAVE BENCH 07`), containing
`STARTUP.SYS`, `SINE441.SND`, `STEREO1.SND`, `DRUMS.SND`. The payload is pinned
to this machine's captured ROM; any other machine stops at `Mod ROM mismatch`.
Hashes and test logs: `build/mods/WAVEHW.json`, `build/mods/WAVEHW-validation.json`.

Optional second image: `build/mods/WAVEHW-NEARFULL.img` (same `STARTUP.SYS`,
plus a filler file leaving exactly 97 free 512-byte clusters), for item 10;
the deploy script adds it as `Disk_03.IMG`.

## Fast-track session (about 45 minutes)

Run the gates in order; each one is release-blocking. Stop at the first
failure, photograph it, and roll back (below) unless it is cosmetic. Items
not listed here are follow-ups, not release blockers.

| Gate | Items | Time | Pass means |
|---|---|---|---|
| 0 Deploy and boot | deploy script, item 1 | 5 min | `WAVE BENCH 07` banner, Play/Record reached |
| 1 Data safety | item 10 (first three boxes) | 15 min | PGM/APS save and reload with groups; the stock OS loads the same files cleanly |
| 2 Mute groups | item 8 (first five boxes), item 9 | 10 min | choke works on the real voices; Apply All asks and cancels |
| 3 Wave and CHOP | item 2 (first box), items 4 and 7 (first two boxes), item 3 (second box) | 10 min | digits in order; CHOP works stopped and is refused while running; Fine→Full is quick |
| 4 Stability | item 11 (first box) | 5 min | no hang or stray Record Ready |

Deploy with the FlashFloppy USB mounted at `/Volumes/MPC3000`:

```bash
python3 build/deploy_wavebench07_usb.py
```

It backs up to `build/usb_backup/wavebench07-<date>/`, replaces only
`Disk_01.IMG`, adds the near-full image as `Disk_03.IMG` if that slot is
free, reads everything back and ejects. **Rollback:** copy that backup's
`Disk_01.IMG` onto the USB (BENCH 05).

Follow-ups, if time remains: item 5 (fast wheel), the audition-overlap and
MIDI boxes of item 8, item 6, safe lock off in item 7, and the near-full disk
in item 10 (needs `Disk_03.IMG` selected in `IMAGE_A.CFG` before power-on).

## Before you start

- [ ] Use copies of any program or sound disks. BENCH 07 writes a trailer into
      PGM and APS files it saves.
- [ ] Back up the USB's current `Disk_01.IMG` (BENCH 05) and `IMAGE_A.CFG`.
      Earlier images are preserved in `build/mods/archive-bench06/` and
      `build/mods/wavebench0*-preserved/`.
- [ ] Run `python3 build/deploy_wavebench07_usb.py` with the USB mounted (see
      the fast-track section). It keeps slot 1 selected and ejects the USB.

For each item, record: pass / fail / not tested, a photo of the LCD where it
says **photo**, and anything unexpected (hang, wrong screen, noise, slow redraw).

## 1. Boot

- [ ] Power on with the USB in. **Photo:** the banner shows `WAVE BENCH 07`.
- [ ] Play/Record is reached (Cancel the SCSI search with soft key 4 if shown).

## 2. Wave view regression (SINE441)

- [ ] Disk → 7 → load `SINE441`. Program/Sounds → 6, select it, press Help.
      **Photo:** sine, flat and ramp sections; title `Edit Snd:SINE441`.
- [ ] Wheel moves Start/End; Left/Right select; soft key 2 toggles Trim/Zone;
      soft key 3 Fine/Full; Up/Down zoom on Start; End → Up selects Zone,
      Down returns to End.
- [ ] Exit (soft key 4) and Help reopen keep the edited points.

## 3. Redraw speed (new)

- [ ] Load `DRUMS`, open its wave view, select the whole sound (Start 0, End at
      the end). Turn the wheel steadily: note whether redraw keeps up.
- [ ] Toggle Fine → Full several times. **Expected:** Full returns at once
      (MAME: about 30 ms; BENCH 06 rescanned the whole sound, about 1.7 s on a
      12.5 s sound in MAME). Record the felt delay.

## 4. Numeric entry ordering (fix)

- [ ] On SINE441, Start selected, type `0` then `1` as fast as you can, then
      Enter. **Expected:** Start = `001.000.00` (1 s). BENCH 06 could enter
      `10` (clamped to End).
- [ ] Repeat a few times; record any reversed or dropped digit.

## 5. Fast wheel (observation)

- [ ] On the `ZONE` total field, spin the wheel fast from 1 towards 16, and
      on a point in Full view spin fast. Record whether the value lags or
      loses steps. MAME shows the stock 8-key queue drops wheel events beyond
      9 inside one redraw; whether the real dial is that fast is unknown.

## 6. Audition

- [ ] `<Ply/Stp>` in Full, in Fine at both ends, and on a Zone: sound stops at
      the selection end; a second press stops it. Very short ranges show
      `Too short`.

## 7. CHOP ZONE safety (fix)

Set 4 zones on SINE441 in the wave view, Exit, then on Edit Sound choose
`Do:CHOP ZONE` and press `<Do>` (soft key 4).

- [ ] **Sequencer stopped:** four `ZONE###` sounds appear; `SINE441` stays
      selected. Leave Edit Sound and come back: `SINE441` is still selected.
      Listen for a click or dropout while it works (the stock "mute audio
      during EDIT SND processes" setting is on by default and now applies).
- [ ] **Sequencer running, safe lock on (default):** start Play (or Rec+Play),
      then CHOP. **Expected:** nothing is created and the page stays as it was;
      Help reopens with the same 4 zones. Stop the sequencer.
- [ ] Optional, **safe lock off:** Other → soft key 4 (Extra) →
      `EDIT SND '<Do> SOFT KEY 4' safe lock` → OFF. With the sequencer running,
      CHOP now works. Note any audio glitch in the running sequence. Set the
      safe lock back ON.
- [ ] Delete the `ZONE###` sounds afterwards (or reload) before item 8.

## 8. Mute groups

Assign `SINE441` (1.25 s, easy to hear) to pads A01, A02 and A03 in
Program/Sounds → 1. Then Program/Sounds → 0.

- [ ] **Photo:** `Mute Groups:` page with Program, Enabled, Pad, Group and the
      A–D overview.
- [ ] Set Enabled ON; pads 1 and 2 to group 1; pad 3 Off. Hit pad 1, then pad 2
      while it rings: pad 1 stops. Hit pad 3 over pad 2: both ring.
- [ ] Hit pad 1 repeatedly: stock same-pad behaviour (Poly/Mono) unchanged.
- [ ] Put pad 2 in group 2: no longer chokes pad 1.
- [ ] Enabled OFF: no choking; assignments kept when switched back ON.
- [ ] Other program: settings are independent.
- [ ] **Audition overlap (fix):** in Edit Sound, start `<Ply/Stp>` on a long
      sound, then hit pads 1 and 2 (group 1). Pad 2 stops pad 1 only; the
      audition keeps playing.
- [ ] Optional: send notes from an external MIDI keyboard (note 35 = pad 1,
      36 = pad 2 with the default map) and check the same choking.

## 9. Apply All confirmation (new)

- [ ] On the mute page select a pad in group 2, press soft key 1.
      **Photo:** title row `Program 01: set all 64 pads to group 2`,
      bottom row `<Do it>` and `<Cancel>`. Nothing has changed yet.
- [ ] Soft key 1 again: cancels, grid unchanged.
- [ ] Soft key 1, then a cursor key or the wheel: cancels, grid unchanged.
- [ ] Soft key 1, then soft key 4 `<Cancel>`: cancels.
- [ ] Soft key 1, then a mode key (e.g. Disk): cancels and opens that page.
- [ ] Soft key 1, then soft key 3 `<Do it>`: all 64 pads show group 2.

## 10. Persistence

- [ ] Set distinctive groups on two programs. Disk: save one PGM, then
      save all programs (APS) to `Disk_01`. No error.
- [ ] Program/Sounds → 4: initialise the program, then load the PGM back:
      groups return. Load the APS: both programs' groups return.
- [ ] **Stock compatibility:** power off, remove the USB, power on (stock EPROM
      OS, no `WAVE BENCH` banner; record whether it waits for a floppy). Insert
      the USB, load the saved PGM and APS. **Expected:** they load without
      error; pad/sound assignments are intact (the mute trailer is ignored).
      If FlashFloppy will not mount after boot, record that and skip.
- [ ] Optional, **near-full disk** (`Disk_03.IMG` = `WAVEHW-NEARFULL.img`; boot
      with slot 3 selected in `IMAGE_A.CFG`, then set it back to `Disk_01.IMG`): save all programs (APS). **Expected:**
      `not enough room` / `F900`, nothing written. Save one PGM: it succeeds.
      Bring the USB back so `Disk_02.IMG` can be checked for FAT damage.

## 11. Exits and stability

- [ ] From the wave view and from the mute page, press Main Screen, Disk and
      Other, then come back. No hang, no stray Record Ready.
- [ ] Leave the machine on the wave view for a few minutes, then use it.

## Report back

- Photos marked above, plus any screen that looks wrong.
- The pass/fail list with notes, especially items 3, 4, 5, 7 and 8.
- The USB itself afterwards (do not reformat it): the saved PGM/APS files and
  both disk images are checked for exact contents and FAT consistency.

Known limits, not failures: APS saves are refused below 98 free clusters
(stock would save at 96); a burst of more than 9 wheel events inside one
redraw loses the extra events (stock queue); behaviour with a 3.08 EPROM
machine is not covered by this image.
