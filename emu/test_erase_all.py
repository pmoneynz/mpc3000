"""PMONEY Disk 7 "Erase all" (mods/eraseall316.inc), OS 3.16.

    python3 -m unittest emu.test_erase_all -v

Per BIOS set: a floppy with STARTUP.SYS (the payload) and three sounds.
Disk, 7, Soft Key 2 <Erase> opens Erase a File; its Soft Key 2 <Erase all>
opens PMONEY's confirmation page.  Then:

  - erase: Soft Key 1 confirms; every file but *.SYS is deleted, the FAT
    stays consistent, and the list is re-read;
  - cancel: a mode key leaves the confirmation page; nothing is deleted;
  - single: the page's Soft Key 1 <Erase it> is still the stock single erase.
"""
from __future__ import annotations

import unittest

from emu import fat12
from emu import harness as h
from emu.mpc3k import DISKS
from emu.snd import sine, snd

RUNS = h.BUILD / "emu" / "erase-all-tests"
DISK, SEVEN, ERASE, ALL, CONFIRM = 35.0, 35.8, 40.0, 42.0, 44.0
SOUNDS = ["SNDA", "SNDB", "SNDC"]


def names(image: bytes) -> list[tuple[str, str]]:
    return sorted((e["name"], e["ext"]) for e in fat12.entries(image))


def text(screen: dict) -> str:
    return "\n".join(screen["rows"]).replace(".", " ")


class EraseAll(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        jobs = {}
        base = h.taps((h.CANCEL_SCSI_316, "soft4"), (DISK, "disk"), (SEVEN, "7"), (ERASE, "soft2"))
        cases = {
            "erase": (base + h.taps((ALL, "soft2"), (CONFIRM, "soft1")), [ERASE + 1.5, ALL + 1.5, 55.0]),
            "cancel": (base + h.taps((ALL, "soft2"), (CONFIRM, "main_screen")), [ALL + 1.5, 50.0]),
            "single": (base + h.taps((ALL, "soft1")), [ERASE + 1.5, 50.0]),
        }
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            runs = RUNS / p.label
            runs.mkdir(parents=True, exist_ok=True)
            files = []
            for i, n in enumerate(SOUNDS):
                f = runs / f"{n}.SND"
                f.write_bytes(snd(n, [sine(2000 + 500 * i)]))
                files.append((f, f"{n}.SND"))
            for name, (events, times) in cases.items():
                jobs[(p.label, name)] = (p, runs, name, events, times, files)

        def execute(key, job):
            p, runs, name, events, times, files = job
            screens = h.run_case(p, runs, name, times=times, events=events, files=files, parts=[])
            image = DISKS / f"{p.label}-{runs.name}-{name}.img"
            return screens, image.read_bytes()

        cls.results = h.run_parallel(jobs, execute)

    def each(self, name):
        return [(label, r) for (label, case), r in self.results.items() if case == name]

    def test_erase_all_keeps_sys_and_fat_consistent(self) -> None:
        for label, (screens, image) in self.each("erase"):
            with self.subTest(set=label):
                self.assertIn("<Erase it> <Erase all>", text(screens[0]))
                self.assertIn("Erase All Files", screens[1]["rows"][0])
                self.assertIn("Erase every file on this disk?", text(screens[1]))
                self.assertIn("<Erase all>", screens[1]["rows"][7])
                self.assertEqual(names(image), [("STARTUP", "SYS")])
                report = fat12.check(image)
                self.assertTrue(report["fat_copies_equal"], report)
                self.assertTrue(report["chains_match_sizes"], report)
                self.assertEqual(report["lost_clusters"], [], report)

    def test_mode_key_cancels(self) -> None:
        for label, (screens, image) in self.each("cancel"):
            with self.subTest(set=label):
                self.assertIn("Erase All Files", screens[0]["rows"][0])
                self.assertEqual(names(image), sorted([("STARTUP", "SYS")] + [(n, "SND") for n in SOUNDS]))

    def test_erase_it_is_still_the_single_erase(self) -> None:
        for label, (screens, image) in self.each("single"):
            with self.subTest(set=label):
                self.assertEqual(len(fat12.entries(image)), 3)
                self.assertIn(("STARTUP", "SYS"), names(image))


if __name__ == "__main__":
    unittest.main()
