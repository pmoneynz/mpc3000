"""MUTE GROUPS trailers on nearly full floppies.

Every save goes through the stock Disk UI on a 1.44 MB image whose free
space is set to an exact number of 512-byte clusters by a filler file.  The
image is then inspected read-only (emu/fat12.py): directory size, cluster
chain, FAT copies, lost clusters.  See notes/mute_storage.md, "Near-full
media".

The gate is a constant compared against floor(free bytes / 1024):
CB10:0E52 (linear 0x4BF52) sets 5 KB for a PGM; CB10:0E5D (linear 0x4BF5D)
sets the APS figure, 42 KB stock and 49 KB in the mod.  The displayed Size
(CB10:12C4 / 12E3, 49 KB in the mod) does not gate.  A 49 KB gate needs at
least 98 free 512-byte clusters; the 49,339-byte APS with its trailer
occupies 97.  The APS cases need all three patches.  The capture payload is
built from the current sources by emu.harness and read back from each image.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from emu import fat12, pgm
from emu import harness as h
from emu.harness import taps
from emu.mpc3k import run
from emu.panel import write_smf
from emu.snd import disk
from emu.test_mute_persistence import aps_save_events, pgm_save_events
from emu.test_mute_ui import observer

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-disk-full-tests"
ZERO = {"enabled": 0, "groups": [0] * 64}
STOCK_APS_BYTES = 48531          # 24 programs, stock writer only
APS_TRAILER_BYTES = 16 + 24 * 33
PGM_STATE = {"enabled": 1, "groups": [3] + [0] * 63}   # pgm_save_events, Program 2
APS_ONE = {"enabled": 1, "groups": [1] + [0] * 63}     # aps_save_events, Program 1
APS_TWO = {"enabled": 1, "groups": [2] + [0] * 63}     # aps_save_events, Program 2
APS_LEVELS = (95, 96, 97, 98)


def text(screen: dict) -> str:
    return "\n".join(screen["rows"]).replace(".", " ")


class MuteDiskFull(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = h.payload("capture")
        ROMS = profile.rompath
        RUNS.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        probe = observer(RUNS, profile=profile)

        def image(name: str, free: int, mod: bool = True) -> Path:
            filler = RUNS / f"FILL-{name}.BIN"
            if mod:
                empty = h.wave_disk(profile, f"full-{name}-empty")
            else:
                empty = disk(f"full-{name}-empty", [])
            filler.write_bytes(bytes(fat12.filler_bytes(empty, free)))
            if mod:
                result = h.wave_disk(profile, f"full-{name}", [(filler, "FILL.BIN")])
            else:
                result = disk(f"full-{name}", [(filler, "FILL.BIN")])
            if fat12.free_clusters(result.read_bytes()) != free:
                raise RuntimeError(f"{name}: filler did not leave {free} clusters")
            return result

        pgm_times, aps_times, stock_times = [49, 62], [54, 76], [30, 52]
        stock_events = taps((20, "soft4"), (23, "disk"), (25, "5"), (28, "soft1"))
        cls.saves = {
            # 9 clusters hold the stock 0x1200 bytes but not the 49-byte trailer.
            "pgm-9": (image("pgm-9", 9), pgm_times, pgm_save_events()),
            "pgm-10": (image("pgm-10", 10), pgm_times, pgm_save_events()),
            # 95 and 96 clusters hold the stock 48,531-byte APS but not the
            # 808-byte trailer; 97 holds both but is below the 49 KB budget.
            **{f"aps-{n}": (image(f"aps-{n}", n), aps_times, aps_save_events())
               for n in APS_LEVELS},
            # The unmodified captured OS (46 KB budget) saving the same APS.
            "stock-96": (image("stock-96", 96, mod=False), stock_times, stock_events),
        }
        cls.before = {name: img.read_bytes() for name, (img, _, _) in cls.saves.items()}

        def execute(item):
            name, (img, times, events) = item
            extra = ["-autoboot_script", str(probe)] if name != "stock-96" else []
            return name, run("vailixi", times, RUNS / name, floppy=img,
                             panel=write_smf(RUNS / f"{name}.mid", events),
                             rompath=ROMS, extra=extra)

        with ThreadPoolExecutor(max_workers=3) as pool:
            cls.screens = dict(pool.map(execute, cls.saves.items()))
        cls.images = {name: img.read_bytes() for name, (img, _, _) in cls.saves.items()}

    @classmethod
    def entry(cls, run_name: str, name: str, ext: str) -> dict | None:
        found = [e for e in fat12.entries(cls.images[run_name])
                 if (e["name"], e["ext"]) == (name, ext)]
        return found[0] if found else None

    def assert_consistent(self, run_name: str):
        report = fat12.check(self.images[run_name])
        self.assertTrue(report["fat_copies_equal"], report)
        self.assertTrue(report["chains_match_sizes"], report)
        self.assertEqual(report["lost_clusters"], [], report)

    def test_pgm_stock_budget_rejects_before_any_write(self):
        # Stock size 5K against floor(9*512/1024)=4K: error F900, nothing written.
        last = text(self.screens["pgm-9"][-1])
        self.assertIn("not enough room", last)
        self.assertIn("F900", last)
        self.assertIsNone(self.entry("pgm-9", "PROGRAM_", "PGM"))
        self.assert_consistent("pgm-9")
        self.assertEqual(fat12.free_clusters(self.images["pgm-9"]), 9)

    def test_pgm_trailer_fits_the_stock_budget(self):
        # 5K = 10 clusters is exactly what stock+trailer (4,657 bytes) needs.
        entry = self.entry("pgm-10", "PROGRAM_", "PGM")
        self.assertEqual(entry["size"], pgm.PGM_BYTES + pgm.MUTE_HEADER.size + 33)
        self.assert_consistent("pgm-10")
        self.assertNotIn("Attention", text(self.screens["pgm-10"][-1]))
        saved = fat12.read_file(self.images["pgm-10"], entry)
        self.assertEqual(pgm.read_mute_trailer(saved), [PGM_STATE])

    def assert_refused_untouched(self, run_name: str):
        last = text(self.screens[run_name][-1])
        self.assertIn("not enough room", last)
        self.assertIn("F900", last)
        self.assertIsNone(self.entry(run_name, "ALL_PGMS", "APS"))
        # Directory and both FATs are byte-for-byte unchanged.
        end = fat12.DATA_OFFSET
        self.assertEqual(self.images[run_name][:end], self.before[run_name][:end])

    def test_aps_below_budget_is_refused_before_any_write(self):
        # floor(95*512/1024)=47, floor(96*512/1024)=48, floor(97*512/1024)=48 < 49.
        for free in (95, 96, 97):
            with self.subTest(free=free):
                self.assert_refused_untouched(f"aps-{free}")
                self.assertEqual(fat12.free_clusters(self.images[f"aps-{free}"]), free)

    def test_aps_at_budget_saves_full_file_with_trailer(self):
        entry = self.entry("aps-98", "ALL_PGMS", "APS")
        self.assertEqual(entry["size"], STOCK_APS_BYTES + APS_TRAILER_BYTES)
        self.assert_consistent("aps-98")
        self.assertEqual(fat12.free_clusters(self.images["aps-98"]), 1)
        self.assertNotIn("Attention", text(self.screens["aps-98"][-1]))
        saved = fat12.read_file(self.images["aps-98"], entry)
        trailer = pgm.read_mute_trailer(saved, STOCK_APS_BYTES)
        self.assertEqual(trailer[:2], [APS_ONE, APS_TWO])
        self.assertEqual(trailer[2:], [ZERO] * 22)

    def test_stock_os_saves_the_same_aps_at_96_clusters(self):
        entry = self.entry("stock-96", "ALL_PGMS", "APS")
        self.assertEqual(entry["size"], STOCK_APS_BYTES)
        self.assert_consistent("stock-96")
        self.assertNotIn("Attention", text(self.screens["stock-96"][-1]))

    def test_no_tested_level_loses_clusters_or_leaves_an_empty_entry(self):
        for run_name in self.saves:
            with self.subTest(run=run_name):
                self.assert_consistent(run_name)
                for entry in fat12.entries(self.images[run_name]):
                    self.assertGreater(entry["size"], 0, entry)


if __name__ == "__main__":
    unittest.main()
