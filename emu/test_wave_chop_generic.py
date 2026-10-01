"""Verify generic-ROM hook addresses independently of the physical profile."""
from pathlib import Path
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import disk, sine441, snd
from emu.test_wave_chop import do_action
from emu.test_wave_zones import observer, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-generic"


class GenericChop(unittest.TestCase):
    def test_generic_zone_and_chop_hooks(self):
        if missing := base.missing_tools():
            self.skipTest(str(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        probe = observer(RUNS, ROOT / "build/mods/wave.cave.map")
        source = RUNS / "GENERIC.SND"
        source.write_bytes(snd("GENERIC", sine441()))
        image = disk("wave-chop-generic", [(ROOT / "build/mods/WAVE.SYS", "STARTUP.SYS"),
                                           (source, "GENERIC.SND")])
        events = (taps((81, "right"), (82, "right"), (83, "right"))
                  + dial(-12, 84) + do_action(87))
        kw = dict(base.CASES["wave_view"])
        kw.update(times=[80, 95, 101], floppy=image, rompath=ROOT / "build/roms",
                  panel=write_smf(RUNS / "input.mid", events), extra=["-autoboot_script", str(probe)])
        kw["press"] = [v for v in kw["press"] if v[0] <= 77.5]
        out = RUNS / "run"
        screens = run(kw.pop("bios"), kw.pop("times"), out, **kw)
        self.assertIn("CHOP ZONE", "".join(screens[1]["rows"]))
        self.assertIn("GENERIC", "".join(screens[2]["rows"]))
        original = (out / "wave_80_idx0.bin").read_bytes()
        self.assertEqual((out / "wave_101_idx0.bin").read_bytes(), original)
        bounds = [55125 * i // 4 for i in range(5)]
        for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
            self.assertEqual((out / f"wave_101_idx{i}.bin").read_bytes(), original[2*a:2*b])


if __name__ == "__main__":
    unittest.main()
