"""Stock Vailixi 3.50 Disk 8 loads tools/snd2akai.py floppies exactly.

Run: python3 -m unittest emu.test_akai_load -v

Each case boots stock 3.50 with a converted HFE floppy, opens Disk -> 8
"Load S1000/S3000 Sample Files" and loads samples with <Load> (stereo:
<Yes,stereo>) through the panel link, then compares the sound records and
wave RAM (emu/lua/snddump.lua) with the source SND files. Loader evidence:
notes/akai_disk.md.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from emu.mpc3k import MAME, run
from emu.panel import dial, key_tap, write_smf
from emu.snd import sine, sine441, snd, stereo1
from tools import snd2akai as sa

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/akai-load-tests"
LUA = ROOT / "emu/lua"

KICK = ("KICK.SND", snd("Kick_01", sine441(), start=100, end=50000))
PAD = ("PAD.SND", snd("Pad", stereo1(), start=10, end=30000))
HIT = ("HIT.SND", snd("Hit", [sine(441)]))
TUNES = {"KICK.SND": -25, "PAD.SND": 37, "HIT.SND": 120}

# Directory order on the Akai screen is by name: HIT, KICK 01, PAD-L, PAD-R.
# One <Load> per file; the screen returns to itself after a load (screens at 52 / 62 show it).
LOADS = [key_tap("disk", 45), key_tap("8", 46.5),
         key_tap("soft1", 48.5),                                  # HIT
         dial(1, 55), key_tap("soft1", 56),                       # KICK 01
         dial(1, 70), key_tap("soft1", 71), key_tap("soft1", 73)]  # PAD-L, <Yes,stereo>
TIMES = [47.5, 49.5, 52, 56.5, 62, 71.5, 73.5, 95]


def with_tune(name: str, data: bytes) -> bytes:
    out = bytearray(data)
    out[2 + 0x12] = TUNES[name] & 0xFF
    return bytes(out)


@unittest.skipUnless(MAME.exists(), f"MAME binary not found: {MAME}")
class AkaiLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        cls.sources = {}
        paths = []
        for name, data in (HIT, KICK, PAD):
            path = RUNS / name
            path.write_bytes(with_tune(name, data))
            cls.sources[name] = sa.read_snd(path.read_bytes())
            paths.append(path)
        [disk] = sa.convert(paths, label="AKAI TEST")
        image = RUNS / "akai.hfe"
        image.write_bytes(sa.hfe(disk.image()))
        panel = write_smf(RUNS / "akai.mid", [e for ev in LOADS for e in ev])
        out = RUNS / "load"
        cls.screens = run("vailixi", TIMES, out, floppy=image, panel=panel,
                          extra=["-autoboot_script", str(LUA / "snddump.lua")],
                          env={"SNDDUMP_PCM": str(TIMES[-1])})
        cls.out = out
        last = (out / "snd_dir.log").read_text().split("@ ")[-1]
        cls.records = {m["name"].strip(): m for m in (
            {"idx": int(a), "name": b, "stereo": int(c), "start": int(d), "end": int(e), "len": int(f),
             "tune": int(g)}
            for a, b, c, d, e, f, g in re.findall(
                r"^idx (\d+) name='([^']*)' vol=\d+ stereo=(\d) start=(\d+) end=(\d+) len=(\d+) "
                r"wave=\w+ tune=(-?\d+)", last, re.M))}

    def text(self, t: float) -> str:
        return "\n".join(next(s for s in self.screens if abs(s["time"] - t) < 1e-3)["rows"])

    def test_screen_lists_the_converted_samples(self) -> None:
        self.assertIn("Reading disk...", self.text(47.5))
        screen = self.text(52)
        self.assertIn("Load S1000/S3000 Sample Files", screen)
        self.assertIn("File:HIT", screen)
        self.assertIn("<Load>", screen)
        self.assertIn("File:KICK_01", self.text(62))

    def test_stereo_prompt(self) -> None:
        self.assertIn("Also load PAD", self.text(71.5).replace("_", " "))

    def test_loaded_sounds_match_the_sources(self) -> None:
        want = {"HIT": "HIT.SND", "KICK_01": "KICK.SND", "PAD": "PAD.SND"}
        self.assertEqual(sorted(self.records), sorted(want), self.records)
        for shown, src_name in want.items():
            with self.subTest(sound=shown):
                rec, src = self.records[shown], self.sources[src_name]
                self.assertEqual((rec["stereo"], rec["len"]), (len(src.planes) - 1, src.frames))
                self.assertEqual((rec["start"], rec["end"]), sa.markers(src))
                self.assertEqual(rec["tune"], src.tune)
                pcm = (self.out / f"wave_{TIMES[-1]:g}_idx{rec['idx']}.bin").read_bytes()
                self.assertEqual(pcm, b"".join(src.planes))


if __name__ == "__main__":
    unittest.main()
