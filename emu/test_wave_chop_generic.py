"""Verify generic-ROM hook addresses independently of the physical profile.

Run: python3 -m unittest emu.test_wave_chop_generic -v
The generic payload is built from the current sources by emu.harness.
"""
from pathlib import Path
import unittest

from emu import harness as h
from emu.harness import VIEW as V, pcm, taps
from emu.panel import dial
from emu.snd import sine441, snd
from emu.test_wave_chop import do_action

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-generic"


class GenericChop(unittest.TestCase):
    def test_generic_zone_and_chop_hooks(self):
        profile = h.payload("generic")
        profile.record(RUNS)
        source = RUNS / "GENERIC.SND"
        source.write_bytes(snd("GENERIC", sine441()))
        events = h.wave_events(taps((V + 1, "right"), (V + 2, "right"), (V + 3, "right"))
                               + dial(-12, V + 4) + do_action(V + 7))
        screens = h.run_case(profile, RUNS, "run", times=[V, V + 15, V + 21], events=events,
                             files=[(source, "GENERIC.SND")])
        out = RUNS / "run"
        self.assertIn("CHOP ZONE", "".join(screens[1]["rows"]))
        self.assertIn("GENERIC", "".join(screens[2]["rows"]))
        original = pcm(out, V, 0)
        self.assertEqual(pcm(out, V + 21, 0), original)
        bounds = [55125 * i // 4 for i in range(5)]
        for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
            self.assertEqual(pcm(out, V + 21, i), original[2 * a:2 * b])
        self.assertEqual(len(h.sound_records(out, V + 21)), 5)


if __name__ == "__main__":
    unittest.main()
