"""PMONEY Timing Correct with Vailixi's 13 note values (mods/tc316.inc), OS 3.16.

    python3 -m unittest emu.test_timing_correct -v

TIMING CORRECT opens the screen at 1/16; the wheel walks the extended list.
At each stop the RAM words (probe PROBE_WORDS, DGROUP) give the stored stock
index [7EBD] = PROJ[extended] (what NVRAM and .PAR files keep) and the live
grid: [86E3] interval in ticks, [86E2] pair = 2 * interval.  Swing% is shown
for every note value from 1/4 down and hidden for the three OFF values.
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

        def execute(label, job):
            p, events = job
            out = RUNS / label
            image = h.wave_disk(p, f"tc-{label}")
            times = [45.0] + [at + 1.0 for at, _, _ in STEPS[1:]]
            screens = run(p.bios, times, out, floppy=image, rompath=p.rompath,
                          panel=write_smf(RUNS / f"{label}.mid", events), words=[0x7EBC, 0x86E2])
            return screens, words(out)

        cls.results = h.run_parallel(jobs, execute)

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


if __name__ == "__main__":
    unittest.main()
