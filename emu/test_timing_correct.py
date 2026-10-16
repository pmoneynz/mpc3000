"""PMONEY Timing Correct with Vailixi's 13 note values (mods/tc316.inc), OS 3.16.

    python3 -m unittest emu.test_timing_correct -v

TIMING CORRECT opens the screen at 1/16; the wheel walks the extended list.
At each stop the RAM words (probe PROBE_WORDS, DGROUP) give the stored stock
index [7EBD] = PROJ[extended] (what NVRAM and .PAR files keep) and the live
grid: [86E3] interval in ticks, [86E2] pair = 2 * interval.  Swing% is shown
for every note value from 1/4 down and hidden for the three OFF values.

par_load: Save Parameters (Disk 6) at 1/32, then 1/64 and Swing 60, then
Load Parameters (Disk 7, PARAMS.PAR).  1/32 and 1/64 project to the same
stock index (5), so the stock load does not change [7EBD]; PMONEY's
extended value must still come from the file: TC_EXT is reset to FFh after
the stock .PAR apply (3.16 call site image 0x2D68A -> T_BDF1_012B,
mods/tc316.inc tc_par_apply).  Before the fix the screen kept 1/64 and the
grid stayed at 6 ticks while Swing returned to 50 (audit 2026-10-16 F-4,
MAME).  DGROUP bytes from emu/lua/dg_words316.lua (read-only).
"""
from __future__ import annotations

import re
import unittest

from emu import harness as h
from emu.mpc3k import run
from emu.panel import dial, key_tap, write_smf

RUNS = h.BUILD / "emu" / "timing-correct-tests"
TICKS = [3, 2, 1, 96, 64, 48, 32, 24, 16, 12, 8, 6, 4]
PROJ = [0, 0, 0, 1, 2, 1, 2, 3, 4, 5, 6, 5, 6]
LABELS = ["OFF 128th", "OFF 192nd", "OFF 384th", "1/4 NOTE", "1/4 TRPLT", "1/8 NOTE", "1/8 TRPLT",
          "1/16 NOTE", "1/16 TRPLT", "1/32 NOTE", "1/32 TRPLT", "1/64 NOTE", "1/64 TRPLT"]
# (time of the wheel move, steps, extended index reached); screens 1 s later.
STEPS = [(None, 0, 7), (46.0, -7, 0), (48.0, 12, 12), (50.0, -9, 3), (52.0, 1, 4)]
# par_load (floppy: the payload disk): TIMING CORRECT, +2 (1/32), Disk 6 <Do it>;
# TIMING CORRECT, +2 (1/64), Right, +10 (Swing 60); Disk 7, <Load> (PARAMS.PAR,
# the first file), <Do It>; TIMING CORRECT.
PAR_EVENTS = (key_tap("timing_correct", 44.0) + dial(2, 45.0)
              + h.taps((47.0, "disk"), (48.5, "6"), (50.5, "soft1"))
              + key_tap("timing_correct", 54.0) + dial(2, 55.0) + h.taps((55.5, "right")) + dial(10, 56.0)
              + h.taps((57.0, "disk"), (58.0, "7"), (63.0, "soft1"), (65.5, "soft1"))
              + key_tap("timing_correct", 69.0))
PAR_TIMES = [46.0, 52.5, 57.0, 61.0, 64.5, 70.0]
TC_STOCK, TC_GRID = 0x7EBD, 0x86E3            # stock index; grid interval in ticks


def dg_bytes(run_dir) -> dict[float, dict[int, int]]:
    from emu.test_scsi316 import dg_bytes as parse
    return parse(run_dir)


def words(run_dir) -> dict[float, dict[int, int]]:
    out, t = {}, None
    for line in (run_dir / "ram_words.log").read_text().splitlines():
        if line.startswith("@"):
            t = float(line.split()[1]); out[t] = {}
        else:
            k, v = line.split(); out[t][int(k, 16)] = int(v, 16)
    return out


class TimingCorrect(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            events = h.taps((p.timeline.cancel, "soft4")) + key_tap("timing_correct", 44.0, hold=0.1)
            for at, steps, _ in STEPS[1:]:
                events += dial(steps, at)
            jobs[p.label] = (p, events)
            jobs[("par", p.label)] = (p, h.taps((p.timeline.cancel, "soft4")) + PAR_EVENTS)

        def execute(label, job):
            p, events = job
            if isinstance(label, tuple):
                runs = RUNS / f"{p.label}-par"          # RUNS/<label> is the step run's own output
                runs.mkdir(parents=True, exist_ok=True)
                screens = h.run_case(p, runs, "par_load", times=PAR_TIMES, events=events, parts=["dg_words"],
                                     env={"DG_BYTES": f"{TC_STOCK:X},{TC_GRID:X}"}, snapshot=False)
                return screens, dg_bytes(runs / "par_load")
            out = RUNS / label
            image = h.wave_disk(p, f"tc-{label}")
            times = [45.0] + [at + 1.0 for at, _, _ in STEPS[1:]]
            screens = run(p.bios, times, out, floppy=image, rompath=p.rompath,
                          panel=write_smf(RUNS / f"{label}.mid", events), words=[0x7EBC, 0x86E2])
            return screens, words(out)

        results = h.run_parallel(jobs, execute)
        cls.results = {k: v for k, v in results.items() if not isinstance(k, tuple)}
        cls.par = {k[1]: v for k, v in results.items() if isinstance(k, tuple)}

    def test_note_values_labels_and_grid(self) -> None:
        for label, (screens, ram) in self.results.items():
            times = sorted(ram)
            for (at, _, ext), screen, t in zip(STEPS, screens, times):
                with self.subTest(set=label, index=ext):
                    text = " ".join(screen["rows"]).replace(".", " ")
                    self.assertIn(LABELS[ext], text)
                    self.assertEqual("Swing%" in screen["rows"][1], ext >= 3)   # hidden for the OFF values
                    if at is None:
                        continue        # the probe's DS histogram still holds the boot DS here
                    stock = ram[t][0x7EBC] >> 8                 # [7EBD]: high byte of the word at 7EBC
                    pair, interval = ram[t][0x86E2] & 0xFF, ram[t][0x86E2] >> 8
                    self.assertEqual(stock, PROJ[ext])
                    self.assertEqual(interval, TICKS[ext])
                    self.assertEqual(pair, 2 * TICKS[ext] & 0xFF)

    def test_load_parameters_restores_the_extended_note_value(self) -> None:
        for label, (screens, ram) in self.par.items():
            with self.subTest(set=label):
                rows = [" ".join(s["rows"]).replace(".", " ") for s in screens]
                self.assertIn("1/32 NOTE", rows[0])
                self.assertEqual((ram[46.0][TC_STOCK], ram[46.0][TC_GRID]), (PROJ[9], TICKS[9]))
                self.assertIn("Saving 'PARAMS PAR'", rows[1])
                # Changed after the save: 1/64 (same stock index 5), Swing 60.
                self.assertIn("1/64 NOTE", rows[2])
                self.assertIn("Swing%:60", rows[2])
                self.assertEqual((ram[57.0][TC_STOCK], ram[57.0][TC_GRID]), (PROJ[11], TICKS[11]))
                self.assertIn("File:PARAMS PAR", rows[3])
                self.assertIn("Load a Parameter File", rows[4])
                # After the load: the saved 1/32, its 12-tick grid, and Swing 50.
                self.assertIn("1/32 NOTE", rows[5])
                self.assertIn("Swing%:50", rows[5])
                self.assertEqual((ram[70.0][TC_STOCK], ram[70.0][TC_GRID]), (PROJ[9], TICKS[9]))


if __name__ == "__main__":
    unittest.main()
