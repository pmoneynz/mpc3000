"""PMONEY Name Wheel (mods/namewheel316.inc), OS 3.16.

    python3 -m unittest emu.test_namewheel316 -v

Play/Record's sequence name "(unused)" is spelled with the wheel, Up/Down and
Left/Right while Name Wheel is ON (the default), then the switch on Extra
Settings 2 is turned OFF and the same first turns behave as stock 3.16.
"""
from __future__ import annotations

import unittest

from emu import harness as h
from emu.panel import dial

RUNS = h.BUILD / "emu" / "namewheel-tests"
STEP = 2.5


def tour(t0: float) -> tuple[list, list[float], list[str]]:
    steps = [("right", "to_name"), (-1, "minus1"), (-1, "minus2"), ("down", "small"), ("right", "right1"),
             (1, "plus_small"), ("up", "caps"), ("right", "right2"), ("play", "space"), (5, "plus5"),
             ("4", "digit"), ("enter", "enter"),
             ("other", "other"), ("soft4", "extra"), ("soft4", "extra2"), ("+", "off"), ("soft1", "doit"),
             ("right", "to_name_off"), (1, "stock_first"), (1, "stock_second"), ("main_screen", "cancel")]
    ev = h.taps((t0, "soft4"))
    t = t0 + STEP
    times, labels = [], []
    for what, label in steps:
        ev += dial(what, t, gap=0.15) if isinstance(what, int) else h.taps((t, what))
        times.append(round(t + STEP - 0.3, 3))
        labels.append(label)
        t += STEP
    return ev, times, labels


class NameWheel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            jobs[p.label] = p

        def execute(label, p):
            ev, times, labels = tour(p.timeline.cancel)
            screens = h.run_case(p, RUNS, label, times=times, events=ev, parts=[])
            return {name: [r.replace(".", " ") for r in s["rows"]] for name, s in zip(labels, screens)}

        cls.results = h.run_parallel(jobs, execute)

    def name(self, rows: list[str]) -> str:
        return rows[1][4:24]

    def test_wheel_spells_with_case_lock(self) -> None:
        for label, s in self.results.items():
            with self.subTest(set=label):
                self.assertEqual(self.name(s["minus1"]), " 1-&unused)         ")    # first turn edits at once
                self.assertEqual(self.name(s["minus2"]), " 1-%unused)         ")    # symbols: stock order
                self.assertEqual(self.name(s["plus_small"]), " 1-%vnused)         ")  # Down: small, locked
                self.assertEqual(self.name(s["caps"]), " 1-%Vnused)         ")    # Up recases in place
                self.assertEqual(self.name(s["space"]), " 1-%V used)         ")   # PLAY still types a space
                self.assertEqual(self.name(s["plus5"]), " 1-%V Zsed)         ")   # lock holds after Right
                self.assertEqual(self.name(s["digit"]), " 1-%V 4sed)         ")   # digits still type, at the cursor
                self.assertEqual(self.name(s["enter"]), " 1-%V_4sed)         ")   # stock commit: space -> _

    def test_extra_settings_page_two_switches_it_off(self) -> None:
        for label, s in self.results.items():
            with self.subTest(set=label):
                self.assertIn("Extra Settings ", s["extra"][0])
                self.assertIn("<More>", s["extra"][7])
                self.assertIn("Extra Settings 2", s["extra2"][0])
                self.assertEqual(s["extra2"][1], "Spell names with the data wheel:     ON ")
                self.assertEqual(s["off"][1], "Spell names with the data wheel:     OFF")
                self.assertIn("<Back>", s["off"][7])

    def test_off_is_stock(self) -> None:
        for label, s in self.results.items():
            with self.subTest(set=label):
                self.assertEqual(self.name(s["stock_first"]), " 1-%V_4sed)         ")   # first turn only opens
                self.assertNotEqual(self.name(s["stock_second"])[3], "&")                # stock list, not ours


if __name__ == "__main__":
    unittest.main()
