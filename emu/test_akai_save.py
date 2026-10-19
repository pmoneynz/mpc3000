"""mods/AKAI.args: the MPC3000 saves Sounds to an Akai S1000 floppy.

Run: python3 -m unittest emu.test_akai_save -v

One boot of the AKAI mod (Route A, generic Vailixi 3.50):

1. Disk -> 7 loads KICK.SND (mono) and PAD.SND (stereo) from the FAT boot floppy.
2. emu/lua/flop_swap.lua inserts an empty Akai HFE (tools/snd2akai.py).
3. Disk -> 8 (relabelled `8.Akai S1000/3000`), Soft Key 3 <Save>, Soft Key 3
   <Save it> saves KICK; again with the wheel on PAD; then KICK once more,
   which must be refused (file already exists) without touching the disk.
4. MAME writes the HFE back on exit. Decoded, it must equal, byte for byte,
   the image tools/snd2akai.py makes from the same two Sounds, and the 3.50
   loader model returns the wave RAM the MPC held (emu/lua/snddump.lua).
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from emu.mpc3k import MAME, run
from emu.panel import dial, key_tap, write_smf
from emu.snd import disk, sine, sine441, snd, stereo1
from tools import snd2akai as sa

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/akai-save-tests"
LUA = ROOT / "emu/lua"
sys.path.insert(0, str(ROOT / "tests"))
from test_snd2akai import decode_hfe, load_350  # noqa: E402


def tuned(data: bytes, tune: int) -> bytes:
    out = bytearray(data)
    out[2 + 0x12] = tune & 0xFF
    return bytes(out)


SOUNDS = {"KICK.SND": tuned(snd("KICK", sine441(), start=100, end=50000), -25),
          "PAD.SND": tuned(snd("PAD", stereo1(), start=10, end=30000), 37)}

SWAP = 85.0
EVENTS = [key_tap("disk", 62), key_tap("7", 63.5), key_tap("soft1", 65.5),   # load KICK
          dial(1, 72), key_tap("soft1", 73),                                 # load PAD
          key_tap("disk", 90), key_tap("8", 91.5),
          key_tap("soft3", 96), key_tap("soft3", 98),                        # save KICK
          key_tap("soft3", 112), dial(1, 113.5), key_tap("soft3", 115),       # save PAD
          key_tap("soft3", 130), key_tap("soft3", 132),                      # KICK again
          key_tap("soft1", 138)]                                             # <Exit>
TIMES = [80, 91, 92.5, 97, 113, 114.5, 128, 136, 140]


@unittest.skipUnless(MAME.exists(), f"MAME binary not found: {MAME}")
class AkaiSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(ROOT / "mods/build_mod_sys.py"), "@mods/AKAI.args",
                        "--out", str(RUNS / "mod")], cwd=ROOT, check=True, capture_output=True)
        files = [(RUNS / "mod/AKAI.SYS", "AKAI.SYS")]
        for name, data in SOUNDS.items():
            (RUNS / name).write_bytes(data)
            files.append((RUNS / name, name))
        boot = disk("akai_save_boot", files)
        cls.akai = RUNS / "akai.hfe"
        cls.akai.write_bytes(sa.hfe(sa.AkaiFloppy().image()))
        panel = write_smf(RUNS / "akai_save.mid", [e for ev in EVENTS for e in ev])
        cls.out = RUNS / "save"
        cls.screens = run("vailixi", TIMES, cls.out, floppy=boot, panel=panel,
                          extra=["-autoboot_script", str(LUA / "flop_swap.lua")],
                          env={"FLOP_SWAP": f"{SWAP}={cls.akai.resolve()}",
                               "SNDDUMP_PCM": str(TIMES[0])})
        cls.image = decode_hfe(cls.akai.read_bytes())
        log = (cls.out / "snd_dir.log").read_text().split("@ ")[1]
        cls.records = {m[1]: {"idx": int(m[0]), "start": int(m[2]), "end": int(m[3]), "tune": int(m[4])}
                       for m in re.findall(r"^idx (\d+) name='(\S+)\s*' vol=\d+ stereo=\d start=(\d+) "
                                           r"end=(\d+) len=\d+ wave=\w+ tune=(-?\d+)", log, re.M)}

    def text(self, t: float) -> str:
        return "\n".join(next(s for s in self.screens if abs(s["time"] - t) < 1e-3)["rows"])

    def test_menu_and_soft_key(self) -> None:
        self.assertIn("8.Akai S1000/3000", self.text(91))
        self.assertIn("<Load>               <Save>    <Sel Dsk>", self.text(128))

    def test_save_screen(self) -> None:
        screen = self.text(97)
        self.assertIn("Save Sound to Akai S1000 Disk", screen)
        self.assertIn("Sound:KICK", screen)
        self.assertIn("Size:108K", screen)
        stereo = self.text(114.5)
        self.assertIn("Sound:PAD", stereo)
        self.assertIn("(stereo)", stereo)
        self.assertIn("Akai: PAD       -L and PAD       -R", stereo)

    def test_disk_equals_the_pc_converter(self) -> None:
        paths = [RUNS / name for name in SOUNDS]
        [ref] = sa.convert(paths)
        self.assertEqual(self.image, ref.image())

    def test_loader_returns_the_mpc_sounds(self) -> None:
        got = {s.name: s for s in load_350(self.image)}
        self.assertEqual(sorted(got), ["KICK", "PAD"])
        for name, src in SOUNDS.items():
            stem = name[:-4]
            rec = self.records[stem]
            pcm = (self.out / f"wave_{TIMES[0]:g}_idx{rec['idx']}.bin").read_bytes()
            sound = got[stem]
            self.assertEqual(b"".join(sound.planes), pcm, stem)
            self.assertEqual((sound.start, sound.end, sound.tune), (rec["start"], rec["end"], rec["tune"]), stem)

    def test_duplicate_is_refused(self) -> None:
        self.assertEqual([e.name for e, _ in sa.read_floppy(self.image)[2]], ["KICK", "PAD       -L", "PAD       -R"])
        self.assertIn("A file already exists with this name.", self.text(136))
        self.assertIn("[Error code: F800]", self.text(136))
        self.assertIn("Load S1000/S3000 Sample Files", self.text(140))


# Edges, one boot: an S3000 floppy (Cancel, then a refused save, disk
# unchanged), then a DD S1000 floppy that tools/snd2akai.py filled to 50 KiB
# free: an odd name saves (`S_#R-L` -> `S #R L`), a 130 KiB stereo Sound is
# refused (not enough room) and the disk keeps only the first save.
EDGE_SOUNDS = {"AB.SND": snd("AB", stereo1()),
               "S_#R-L.SND": tuned(snd("S_#R-L", [sine(4410)]), 5)}
FILLER = snd("FILLER", [[7] * 381877])          # 746 of the 796 DD blocks
EDGE_EVENTS = [key_tap("disk", 62), key_tap("7", 63.5), key_tap("soft1", 65.5),   # load AB
               dial(1, 72), key_tap("soft1", 73),                                 # load S_#R-L
               key_tap("disk", 90), key_tap("8", 91.5),                           # S3000 disk
               key_tap("soft3", 96), key_tap("soft4", 98),                        # open, Cancel
               key_tap("soft3", 104), key_tap("soft3", 106),                      # refused
               key_tap("soft4", 112),                                             # dismiss
               key_tap("disk", 120), key_tap("8", 121.5),                         # DD disk
               key_tap("soft3", 126), dial(1, 127.5), key_tap("soft3", 129),       # save S_#R-L
               key_tap("soft3", 140), key_tap("soft3", 142),                      # AB: no room
               key_tap("soft1", 148)]                                             # <Exit>
EDGE_TIMES = [97, 100, 110, 128.5, 138, 146, 152]


@unittest.skipUnless(MAME.exists(), f"MAME binary not found: {MAME}")
class AkaiSaveEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        runs = RUNS / "edges"
        runs.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(ROOT / "mods/build_mod_sys.py"), "@mods/AKAI.args",
                        "--out", str(runs / "mod")], cwd=ROOT, check=True, capture_output=True)
        files = [(runs / "mod/AKAI.SYS", "AKAI.SYS")]
        for name, data in EDGE_SOUNDS.items():
            (runs / name).write_bytes(data)
            files.append((runs / name, name))
        boot = disk("akai_edge_boot", files)
        (runs / "FILLER.SND").write_bytes(FILLER)
        cls.s3000 = sa.AkaiFloppy(sa.HD, s3000=True).image()
        [filled] = sa.convert([runs / "FILLER.SND"], sa.DD)
        cls.filled = filled.image()
        s3, dd = runs / "s3000.hfe", runs / "dd.hfe"
        s3.write_bytes(sa.hfe(cls.s3000))
        dd.write_bytes(sa.hfe(cls.filled))
        panel = write_smf(runs / "edges.mid", [e for ev in EDGE_EVENTS for e in ev])
        cls.screens = run("vailixi", EDGE_TIMES, runs / "run", floppy=boot, panel=panel,
                          extra=["-autoboot_script", str(LUA / "flop_swap.lua")],
                          env={"FLOP_SWAP": f"85={s3.resolve()};118={dd.resolve()}", "SNDDUMP_PCM": "0"})
        cls.s3000_after = decode_hfe(s3.read_bytes())
        cls.dd_after = decode_hfe(dd.read_bytes())
        cls.runs = runs

    def text(self, t: float) -> str:
        return "\n".join(next(s for s in self.screens if abs(s["time"] - t) < 1e-3)["rows"])

    def test_s3000_floppy_is_refused_and_untouched(self) -> None:
        self.assertIn("Sound:AB", self.text(97))
        self.assertIn("Load S1000/S3000 Sample Files", self.text(100))      # Cancel
        self.assertIn("S3000 disk: use an S1000 disk.", self.text(110))
        self.assertEqual(self.s3000_after, self.s3000)

    def test_dd_save_and_no_room(self) -> None:
        self.assertIn("Akai: S #R L", self.text(128.5))
        self.assertIn("There is not enough", self.text(146))
        self.assertIn("[Error code: F900]", self.text(146))
        [ref] = sa.convert([self.runs / "FILLER.SND", self.runs / "S_#R-L.SND"], sa.DD)
        self.assertEqual(self.dd_after, ref.image())
        self.assertEqual([e.name for e, _ in sa.read_floppy(self.dd_after)[2]], ["FILLER", "S #R L"])


if __name__ == "__main__":
    unittest.main()
