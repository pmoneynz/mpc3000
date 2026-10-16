"""PMONEY Extra Settings (mods/xparams316.inc), OS 3.16.

    python3 -m unittest emu.test_xparams -v

Other > Soft Key 4 opens the page; its six fields default to Vailixi's
defaults through the inverted storage.  Each behaviour is run with the
setting turned ON on the page and against the default OFF:

  - Stay in Edit Sound / Stay in Mixer: PLAY keeps the page open (else the
    stock switch to Play/Record);
Every case first records a short sequence (Rec + Play through the driver's
inputs, STOP), because PLAY on an unused sequence starts no run.
  - Stop all sounds on STOP: STOP after a run calls the stop-all-voices
    routine (3.16 20ED:0D99, T_CFC6_0D93; fork trace point), else not.

The Edit Sound safe lock and mute are covered by emu/test_wave_chop_safety.py.
"""
from __future__ import annotations

import unittest

from emu import harness as h
from emu.snd import sine441, snd

RUNS = h.BUILD / "emu" / "xparams-tests"
PAGE = (45.0, 46.5)                     # Other, Soft Key 4
DEFAULTS = ["OFF", "ON", "OFF", "OFF", "ON", "ON"]
# Rec + Play through MAME's inputs (the driver's panel HLE), as in
# emu/test_wave_chop_safety.py: records into sequence 1 until STOP.
RECORD = [(51.5, "Y7", "Rec", 0.3), (51.6, "Y7", "Play", 0.1)]


def set_row(row: int) -> list:
    """Open Extra Settings, Down to `row` (1..6), '+' (OFF -> ON on a direct row), leave."""
    other, extra = PAGE
    return h.taps((other, "other"), (extra, "soft4"),
                  *[(extra + 1 + 0.5 * i, "down") for i in range(row - 1)],
                  (49.5, "+"), (50.5, "main_screen"))


class ExtraSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        src = RUNS / "SINE441.SND"
        src.write_bytes(snd("SINE441", sine441()))
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            load = h.load_sound_events(profile=p)
            record = h.taps((56.0, "stop"))                 # after Rec + Play at 51.5 (RECORD)
            edit = record + h.taps((57.5, "program_sounds"), (58.3, "6"), (60.5, "play"))
            mixer = record + h.taps((57.5, "mixer_effects"), (58.3, "1"), (60.5, "play"))
            stop = record + h.taps((57.5, "play"), (59.5, "stop"))
            cases = {
                "page": (load + h.taps((PAGE[0], "other"), (PAGE[1], "soft4")), [48.0], None),
                "stay_edit_on": (load + set_row(3) + edit, [60.0, 62.0], None),
                "stay_edit_off": (load + edit, [60.0, 62.0], None),
                "stay_mixer_on": (load + set_row(4) + mixer, [60.0, 62.0], None),
                "stay_mixer_off": (load + mixer, [60.0, 62.0], None),
                "stop_on": (load + set_row(1) + stop, [61.5], p.target("T_CFC6_0D93").phys),
                "stop_off": (load + stop, [61.5], p.target("T_CFC6_0D93").phys),
            }
            for name, (events, times, trace) in cases.items():
                jobs[(p.label, name)] = (p, name, events, times, trace)

        def execute(key, job):
            p, name, events, times, trace = job
            runs = RUNS / p.label
            runs.mkdir(parents=True, exist_ok=True)
            env = {}
            if trace:
                env = {"NEC_TRACE_FILE": str(runs / f"{name}.trace"), "NEC_TRACE_FROM": "53.0",
                       "NEC_TRACE_AT": f"{trace:X}=STOPALL"}
            press = [] if name == "page" else RECORD
            screens = h.run_case(p, runs, name, times=times, events=events, files=[(src, "SINE441.SND")],
                                 parts=[], env=env, press=press or None)
            hits = None
            if trace:
                hits = sum(1 for line in (runs / f"{name}.trace").read_text().splitlines()
                           if line.startswith("H ") and float(line.split()[1]) >= 59.0)
            return screens, hits

        cls.results = h.run_parallel(jobs, execute)

    def each(self, name):
        return [(label, r) for (label, case), r in self.results.items() if case == name]

    def test_page_shows_six_settings_with_vailixi_defaults(self) -> None:
        for label, (screens, _) in self.each("page"):
            with self.subTest(set=label):
                rows = [r.replace(".", " ") for r in screens[0]["rows"]]
                self.assertIn("Extra Settings", rows[0])
                self.assertEqual([r[37:40].strip() for r in rows[1:7]], DEFAULTS)
                self.assertTrue(rows[1].startswith("Stop all sounds on sequencer STOP:"))
                self.assertTrue(rows[6].startswith("Lock Edit Sound <Do> while running:"))
                self.assertIn("<Do it>", rows[7])

    def test_stay_in_edit_sound_on_play(self) -> None:
        for label, (screens, _) in self.each("stay_edit_on"):
            with self.subTest(set=label, setting="ON"):
                self.assertIn("Edit Snd:SINE441", screens[0]["rows"][0])
                self.assertIn("Edit Snd:SINE441", screens[1]["rows"][0])
        for label, (screens, _) in self.each("stay_edit_off"):
            with self.subTest(set=label, setting="OFF"):
                self.assertIn("Edit Snd:SINE441", screens[0]["rows"][0])
                self.assertNotIn("Edit Snd", screens[1]["rows"][0])

    def test_stay_in_mixer_on_play(self) -> None:
        for on, off in zip(self.each("stay_mixer_on"), self.each("stay_mixer_off")):
            (label, (on_screens, _)), (_, (off_screens, _)) = on, off
            with self.subTest(set=label):
                mixer_title = on_screens[0]["rows"][0]
                self.assertEqual(off_screens[0]["rows"][0], mixer_title)          # same page before PLAY
                self.assertEqual(on_screens[1]["rows"][0], mixer_title)           # ON: stays
                self.assertNotEqual(off_screens[1]["rows"][0], mixer_title)       # OFF: switches

    def test_stop_cuts_sounds_only_when_on(self) -> None:
        for label, (_, hits) in self.each("stop_on"):
            with self.subTest(set=label, setting="ON"):
                self.assertGreaterEqual(hits, 1)
        for label, (_, hits) in self.each("stop_off"):
            with self.subTest(set=label, setting="OFF"):
                self.assertEqual(hits, 0)


if __name__ == "__main__":
    unittest.main()
