"""PMONEY System Information (mods/sysinfo316.inc) from Other -> Soft Key 3, OS 3.16.

    python3 -m unittest emu.test_sysinfo -v

The boot screen is checked by emu/test_port316_boot.py.  Here: Other, Soft
Key 3 <Version> redraws the banner with the memory lines (the probe answer
cached at boot: no I-0055 line in MAME), and Soft Key 1 returns to Other.
"""
from __future__ import annotations

import unittest

from emu import harness as h

RUNS = h.BUILD / "emu" / "sysinfo-tests"
OTHER, INFO, BACK = 35.0, 36.5, 39.0


class SystemInformation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            events = h.taps((p.timeline.cancel, "soft4"), (OTHER, "other"), (INFO, "soft3"), (BACK, "soft1"))
            jobs[p.label] = (p, events)

        def execute(label, job):
            p, events = job
            return p, h.run_case(p, RUNS, label, times=[INFO + 1.0, BACK + 1.0], events=events, parts=[])

        cls.results = h.run_parallel(jobs, execute)

    def test_other_soft_key_3_shows_system_information(self) -> None:
        for label, (p, screens) in self.results.items():
            with self.subTest(set=label):
                rows = [r.replace(".", " ") for r in screens[0]["rows"]]
                seq = 411 if p.load_segment == 0x6900 else 439
                self.assertIn("PMONEY.BETA.1.0", screens[0]["rows"][2])
                self.assertEqual(rows[3], f"Sound memory free (SND/PGM/SET):  {1916:5d}K")
                self.assertEqual(rows[4], f"Seq memory free (SEQ/ALL/MID):    {seq:5d}K")
                self.assertEqual(rows[5].strip(), "")
                self.assertIn("<Exit>", rows[7])
                self.assertIn("Metronome", screens[1]["rows"][0])     # Soft Key 1: back to the Other page


if __name__ == "__main__":
    unittest.main()
