"""Save a chopped stereo sound with stock Disk UI, then reload it cold.

Run: python3 -m unittest emu.test_wave_chop_save -v
The capture payload is built from the current sources by emu.harness.
"""
import hashlib
from pathlib import Path
import struct
import unittest

from emu import harness as h
from emu.harness import VIEW as V, taps
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import snd, stereo1
from emu.test_wave_chop import do_action

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-save"


class ChopSave(unittest.TestCase):
    def test_stereo_chop_survives_stock_save_and_cold_reload(self):
        profile = h.payload("capture")
        profile.record(RUNS)
        src = RUNS / "SAMPLE.SND"
        data = bytearray(snd("SAMPLE", stereo1(), vol=77))
        data[2 + 0x12] = (-12) & 255
        src.write_bytes(data)
        events = h.wave_events(taps((V + 1, "right"), (V + 2, "right"), (V + 3, "right"),
                                    (V + 4, "right"))
                               + dial(-12, V + 5) + do_action(V + 8)
                               + taps((V + 24, "disk"), (V + 25.5, "3"), (V + 28, "+"),
                                      (V + 30, "soft1")))
        image = h.wave_disk(profile, "wave-chop-save", [(src, "SAMPLE.SND")])
        before = hashlib.sha256(image.read_bytes()).hexdigest()
        first = RUNS / "save"
        screens = run("vailixi", [V + 22, V + 29, V + 42], first, floppy=image,
                      rompath=profile.rompath, panel=write_smf(RUNS / "save.mid", events),
                      extra=["-autoboot_script",
                             str(h.observer(profile, RUNS / "save.lua",
                                            ["wave_zones", "snddump"]))])
        self.assertIn("ZONE000", "".join(screens[1]["rows"]))
        self.assertNotEqual(hashlib.sha256(image.read_bytes()).hexdigest(), before)
        self.assertIn(b"ZONE000 SND", image.read_bytes()[0x2600:0x4200])

        # Cold boot of the saved disk: Disk / 7, '+' selects the second file
        # (ZONE000.SND), <Load>, then Edit Sound.
        load = (taps((h.CANCEL_SCSI, "soft4"), (23, "disk"), (24.5, "7"), (26, "+"),
                     (27.5, "soft1")) + taps((34, "program_sounds"), (35.5, "6")))
        second = RUNS / "reload"
        loaded = run("vailixi", [26.75, V], second, floppy=image, rompath=profile.rompath,
                     panel=write_smf(RUNS / "load.mid", load),
                     extra=["-autoboot_script",
                            str(h.observer(profile, RUNS / "reload.lua",
                                           ["wave_zones", "snddump"]))])
        self.assertIn("ZONE000", "".join(loaded[0]["rows"]))
        self.assertIn("ZONE000", "".join(loaded[1]["rows"]))
        self.assertEqual(h.pcm(second, V, 0), h.pcm(first, V + 22, 1))
        old = (first / f"records_{h.label(V + 22)}.bin").read_bytes()[36:72]
        new = (second / f"records_{h.label(V)}.bin").read_bytes()[:36]
        self.assertEqual(new[:0x20], old[:0x20])
        self.assertEqual(struct.unpack_from("<I", new, 0x1C)[0], 33075 // 4)


if __name__ == "__main__":
    unittest.main()
