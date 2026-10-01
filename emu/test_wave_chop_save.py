"""Save a chopped stereo sound with stock Disk UI, then reload it cold."""
import hashlib
from pathlib import Path
import struct
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import disk, snd, stereo1
from emu.test_wave_chop import do_action
from emu.test_wave_zones import observer, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-save"


class ChopSave(unittest.TestCase):
    def test_stereo_chop_survives_stock_save_and_cold_reload(self):
        if missing := base.missing_tools():
            self.skipTest(str(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        probe = observer(RUNS)
        src = RUNS / "SAMPLE.SND"
        data = bytearray(snd("SAMPLE", stereo1(), vol=77))
        data[2 + 0x12] = (-12) & 255
        src.write_bytes(data)
        image = disk("wave-chop-save", [(ROOT / "build/mods/WAVEHW.SYS", "STARTUP.SYS"),
                                        (src, "SAMPLE.SND")])
        before = hashlib.sha256(image.read_bytes()).hexdigest()
        events = (taps((81, "right"), (82, "right"), (83, "right"), (84, "right"))
                  + dial(-12, 85) + do_action(88)
                  + taps((104, "disk"), (105.5, "3"), (108, "+"), (110, "soft1")))
        kw = dict(base.CASES["wave_view"])
        kw.update(times=[102, 109, 122], floppy=image, rompath=ROOT / "build/roms-wavehw-composite",
                  panel=write_smf(RUNS / "save.mid", events), extra=["-autoboot_script", str(probe)])
        kw["press"] = [v for v in kw["press"] if v[0] <= 77.5]
        first = RUNS / "save"
        screens = run(kw.pop("bios"), kw.pop("times"), first, **kw)
        self.assertIn("ZONE000", "".join(screens[1]["rows"]))
        self.assertNotEqual(hashlib.sha256(image.read_bytes()).hexdigest(), before)
        self.assertIn(b"ZONE000 SND", image.read_bytes()[0x2600:0x4200])

        kw = dict(base.CASES["wave_view"])
        kw.update(times=[65.75, 80], floppy=image, rompath=ROOT / "build/roms-wavehw-composite",
                  panel=write_smf(RUNS / "load.mid", taps((65, "+"))),
                  extra=["-autoboot_script", str(probe)])
        kw["press"] = [(62, "Y0", "Disk", .1), (63.5, "Y0", "7", .1),
                       (66.5, "Y3", "Soft Key 1", .1), (74, "Y0", "Program/Sounds", .1),
                       (75.5, "Y1", "6", .1)]
        second = RUNS / "reload"
        loaded = run(kw.pop("bios"), kw.pop("times"), second, **kw)
        self.assertIn("ZONE000", "".join(loaded[0]["rows"]))
        self.assertIn("ZONE000", "".join(loaded[1]["rows"]))
        self.assertEqual((second / "wave_80_idx0.bin").read_bytes(), (first / "wave_102_idx1.bin").read_bytes())
        old = (first / "records_102.bin").read_bytes()[36:72]
        new = (second / "records_80.bin").read_bytes()[:36]
        self.assertEqual(new[:0x20], old[:0x20])
        self.assertEqual(struct.unpack_from("<I", new, 0x1C)[0], 33075 // 4)


if __name__ == "__main__":
    unittest.main()
