"""PMONEY Program/Sounds 9 "Compress sound" (mods/compress.inc), OS 3.16.

    python3 -m unittest emu.test_compress -v

Per BIOS set (harness.bios316_sets()): load a sound, Program/Sounds, 9, Soft
Key 1 <Do it>, then compare the sound directory and the PCM in sound memory
before and after (emu/lua/wave_zones316.lua, snddump316.lua; read-only):

  - every plane becomes its even samples (out[k] = in[2k], per plane);
  - Length, Soft st and Soft end halve; Tune drops by 120;
  - a negative Tune is refused (nothing changes);
  - the menu lists "9.Compress sound" and 0 still opens Mute groups.
"""
from __future__ import annotations

import struct
import unittest

from emu import harness as h
from emu.snd import sine, sine441, snd, stereo1

RUNS = h.BUILD / "emu" / "compress-tests"
MENU, PAGE, BEFORE, DO, AFTER = 46.0, 46.8, 48.5, 49.0, 56.0


def plane_words(data: bytes, length: int, stereo: int) -> list[list[int]]:
    words = struct.unpack(f"<{len(data) // 2}h", data)
    return [list(words[p * length:(p + 1) * length]) for p in range(stereo + 1)]


class CompressSound(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sounds = {
            "mono_odd": snd("SINE441", sine441()),
            "stereo_odd": snd("STEREO1", stereo1()),
            "stereo_even": snd("STEREO2", [sine(33076), [-x for x in sine(33076)]], start=100, end=30001),
            "negative_tune": bytearray(snd("NEGTUNE", [sine(4410)])),
        }
        sounds["negative_tune"][2 + 0x12] = (-12) & 0xFF
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            tl = p.timeline
            runs = RUNS / p.label
            runs.mkdir(parents=True, exist_ok=True)
            for name, data in sounds.items():
                f = runs / f"{name}.SND"
                f.write_bytes(bytes(data))
                events = h.load_sound_events(profile=p) + h.taps((MENU, "program_sounds"), (PAGE, "9"), (DO, "soft1"))
                jobs[(p.label, name)] = (p, runs, name, events, [MENU + 0.6, BEFORE, AFTER], [(f, f"{name[:8].upper()}.SND")])
            events = h.load_sound_events(profile=p) + h.taps((MENU, "program_sounds"), (PAGE, "0"))
            jobs[(p.label, "menu")] = (p, runs, "menu", events, [MENU + 0.6, BEFORE],
                                       [(runs / "mono_odd.SND", "MONO_ODD.SND")])
        assert tl.load_at + tl.load_key + 6 < MENU

        def execute(key, job):
            p, runs, name, events, times, files = job
            screens = h.run_case(p, runs, name, times=times, events=events, files=files,
                                 parts=["wave_zones", "snddump"],
                                 env={"SNDDUMP_PCM": f"{BEFORE},{AFTER}"})
            return runs / name, screens

        cls.results = h.run_parallel(jobs, execute)

    def each(self, name):
        return [(label, result) for (label, case), result in self.results.items() if case == name]

    def check_compressed(self, name: str) -> None:
        for label, (run_dir, screens) in self.each(name):
            with self.subTest(set=label):
                self.assertIn("Compress Sound", screens[1]["rows"][0])
                before = h.sound_records(run_dir, BEFORE)[0]
                after = h.sound_records(run_dir, AFTER)[0]
                n, st = before["length"], before["stereo"]
                self.assertEqual(after["length"], n // 2)
                self.assertEqual(after["start"], before["start"] // 2)
                self.assertEqual(after["end"], before["end"] // 2)
                self.assertEqual(after["tune"], max(before["tune"] - 120, -120))
                self.assertEqual((after["name"], after["stereo"], after["volume"], after["wave"]),
                                 (before["name"], st, before["volume"], before["wave"]))
                old = plane_words(h.pcm(run_dir, BEFORE, 0), n, st)
                new = plane_words(h.pcm(run_dir, AFTER, 0), n // 2, st)
                for plane in range(st + 1):
                    self.assertEqual(new[plane], old[plane][0::2][:n // 2], f"plane {plane}")

    def test_mono_odd_length(self) -> None:
        self.check_compressed("mono_odd")

    def test_stereo_odd_length_keeps_planes_apart(self) -> None:
        self.check_compressed("stereo_odd")

    def test_stereo_even_length(self) -> None:
        self.check_compressed("stereo_even")

    def test_negative_tune_is_refused(self) -> None:
        for label, (run_dir, _) in self.each("negative_tune"):
            with self.subTest(set=label):
                self.assertEqual(h.sound_records(run_dir, AFTER)[0], h.sound_records(run_dir, BEFORE)[0])
                self.assertEqual(h.pcm(run_dir, AFTER, 0), h.pcm(run_dir, BEFORE, 0))

    def test_menu_lists_compress_and_keeps_mute_groups(self) -> None:
        for label, (_, screens) in self.each("menu"):
            with self.subTest(set=label):
                menu = " ".join(screens[0]["rows"]).replace(".", " ")    # cells the dump shows as '.'
                menu = menu.replace("9 Compress", "9.Compress").replace("0 Mute", "0.Mute")
                self.assertIn("9.Compress sound", menu)
                self.assertIn("0.Mute groups", menu)
                self.assertNotIn("MIDI sample dump", menu)
                # 0 opens the cave's Mute groups page, the only graphics-mode
                # page on this menu (LC7981 mode register bit 1; text is 30h/38h)
                self.assertIn("mode=38", screens[0]["head"])
                mode = int(screens[1]["head"].split("mode=")[1][:2], 16)
                self.assertTrue(mode & 0x02, screens[1]["head"])


if __name__ == "__main__":
    unittest.main()
