"""MUTE GROUPS persistence through native PGM/APS Disk paths.

The observer is read-only.  Every state transition comes from real panel
events, stock Disk save/load code, or the stock startup-file loader.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import subprocess
import unittest

from emu import harness as h
from emu import pgm
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.test_mute_ui import observer, states
from emu.harness import taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-persistence-tests"
NATIVE_PGM_SHA256 = "92fb1c621c10db67788da83b4f2dfc7d97919b16d1f2472886f871495023e733"
ZERO = {"enabled": 0, "groups": [0] * 64}


def extract(image: Path, dos_name: str, destination: Path) -> bytes:
    destination.unlink(missing_ok=True)
    subprocess.run(["mcopy", "-i", str(image), f"::{dos_name}", str(destination)], check=True)
    return destination.read_bytes()


def pgm_save_events():
    # Configure Program 2 while Program 1 was active, return to Program 1,
    # then choose Program 2 independently on the stock Save a Program page.
    return (taps((20, "soft4"), (23, "program_sounds"), (25, "0"),
                 (27, "left"), (28, "+"), (29, "right"), (30, "+"),
                 (31, "right"), (32, "right"), (33, "3"),
                 (35, "left"), (36, "left"), (37, "left"), (38, "-"),
                 (40, "soft4"), (43, "disk"), (45, "4"))
            + dial(1, 48) + taps((50, "soft1")))


def aps_save_events():
    # Program 1: enabled, pad 1 group 1.  Program 2: enabled, pad 1 group 2.
    # Return to Program 1 before saving all programs.
    return taps((20, "soft4"), (23, "program_sounds"), (25, "0"),
                (27, "+"), (28, "right"), (29, "right"), (30, "1"),
                (32, "left"), (33, "left"), (34, "left"), (35, "+"),
                (36, "right"), (37, "+"), (38, "right"), (39, "right"),
                (40, "2"), (42, "left"), (43, "left"), (44, "left"),
                (45, "-"), (47, "soft4"), (50, "disk"), (52, "5"),
                (55, "soft1"))


def stale_then_load_events():
    # Give Program 2 unmistakable stale state, leave it selected, and load the
    # sole PGM into that destination using Disk / 7 / Load / Load it.
    return taps((20, "soft4"), (23, "program_sounds"), (25, "0"),
                (27, "left"), (28, "+"), (29, "right"), (30, "+"),
                (31, "right"), (32, "right"), (33, "4"), (35, "soft4"),
                (38, "disk"), (40, "7"), (43, "soft1"), (46, "soft1"))


class MutePersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = h.payload("capture")
        SYS, ROMS = profile.sys, profile.rompath
        if not pgm.NATIVE_BLANK_PATH.is_file():
            h.unavailable(f"native PGM fixture is missing: {pgm.NATIVE_BLANK_PATH}")
        native = pgm.native_blank()
        if hashlib.sha256(native).hexdigest() != NATIVE_PGM_SHA256:
            raise RuntimeError("native PGM fixture hash changed")
        RUNS.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        cls.payload_hash = profile.sha256
        probe = observer(RUNS, profile=profile)

        # The two saves are independent and both use the stock Disk UI.
        pgm_image = h.wave_disk(profile, "mute-persistence-pgm-save")
        aps_image = h.wave_disk(profile, "mute-persistence-aps-save")
        saves = {
            "pgm-save": ([39, 49, 62], pgm_image, pgm_save_events()),
            "aps-save": ([46, 54, 76], aps_image, aps_save_events()),
        }

        def execute_save(item):
            name, (times, image, events) = item
            screens = run("vailixi", times, RUNS / name, floppy=image,
                          panel=write_smf(RUNS / f"{name}.mid", events), rompath=ROMS,
                          extra=["-autoboot_script", str(probe)])
            return name, screens

        with ThreadPoolExecutor(max_workers=2) as pool:
            cls.screens = dict(pool.map(execute_save, saves.items()))

        cls.saved_pgm = extract(pgm_image, "PROGRAM_.PGM", RUNS / "saved-program-2.PGM")
        cls.saved_aps = extract(aps_image, "ALL_PGMS.APS", RUNS / "saved-all.APS")

        # Exact malformed payload: valid header and length, invalid group nibble.
        malformed = bytearray(pgm.with_mute_state(enabled=True, groups=[1] * 64))
        malformed[pgm.PGM_BYTES + pgm.MUTE_HEADER.size + 1] = 0xF1
        malformed_path = RUNS / "MALFORM.PGM"
        malformed_path.write_bytes(malformed)

        cold_pgm_image = h.wave_disk(profile, "mute-persistence-pgm-cold", [
                               (RUNS / "saved-program-2.PGM", "SOURCE2.PGM")])
        cold_aps_image = h.wave_disk(profile, "mute-persistence-aps-cold", [
                               (RUNS / "saved-all.APS", "ALL_PGMS.APS")])
        legacy_image = h.wave_disk(profile, "mute-persistence-legacy", [
                            (pgm.NATIVE_BLANK_PATH, "LEGACY.PGM")])
        malformed_image = h.wave_disk(profile, "mute-persistence-malformed", [
                               (malformed_path, "MALFORM.PGM")])
        loads = {
            # Startup also sees the PGM, then the explicit Disk path selects
            # destination Program 2 before the second load.
            "pgm-cold": ([30, 32, 50], cold_pgm_image,
                         taps((20, "soft4"), (23, "disk"), (25, "7"), (28, "soft1"))
                         + dial(1, 31) + taps((33, "soft1"))),
            # APS is loaded by the stock cold-start file loader.
            "aps-cold": ([50], cold_aps_image, taps((20, "soft4"))),
            "legacy": ([34, 55], legacy_image, stale_then_load_events()),
            "malformed": ([34, 55], malformed_image, stale_then_load_events()),
        }

        def execute_load(item):
            name, (times, image, events) = item
            screens = run("vailixi", times, RUNS / name, floppy=image,
                          panel=write_smf(RUNS / f"{name}.mid", events), rompath=ROMS,
                          extra=["-autoboot_script", str(probe)])
            return name, screens

        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.screens.update(pool.map(execute_load, loads.items()))

    def test_pgm_save_uses_chosen_source_and_cold_load_uses_chosen_destination(self):
        expected = {"enabled": 1, "groups": [3] + [0] * 63}
        before = states(RUNS / "pgm-save", 39)
        self.assertEqual(before[0], ZERO)
        self.assertEqual(before[1], expected)
        self.assertEqual(len(self.saved_pgm), pgm.PGM_BYTES + pgm.MUTE_HEADER.size + 33)
        self.assertEqual(pgm.read_mute_trailer(self.saved_pgm), [expected])
        loaded = states(RUNS / "pgm-cold", 50)
        self.assertEqual(loaded[1], expected)

    def test_aps_multi_program_round_trip(self):
        one = {"enabled": 1, "groups": [1] + [0] * 63}
        two = {"enabled": 1, "groups": [2] + [0] * 63}
        before = states(RUNS / "aps-save", 46)
        self.assertEqual(before[:2], [one, two])
        offset = self.saved_aps.rfind(pgm.MUTE_MAGIC)
        self.assertGreater(offset, 0)
        self.assertEqual(len(self.saved_aps) - offset, pgm.MUTE_HEADER.size + 24 * 33)
        trailer = pgm.read_mute_trailer(self.saved_aps, offset)
        self.assertEqual(trailer[:2], [one, two])
        self.assertEqual(trailer[2:], [ZERO] * 22)
        self.assertEqual(states(RUNS / "aps-cold", 50), trailer)

    def test_legacy_pgm_clears_stale_destination_state(self):
        stale = {"enabled": 1, "groups": [4] + [0] * 63}
        self.assertEqual(states(RUNS / "legacy", 34)[1], stale)
        self.assertEqual(states(RUNS / "legacy", 55)[1], ZERO)

    def test_malformed_trailer_is_rejected_transactionally(self):
        stale = {"enabled": 1, "groups": [4] + [0] * 63}
        self.assertEqual(states(RUNS / "malformed", 34)[1], stale)
        self.assertEqual(states(RUNS / "malformed", 55)[1], ZERO)


if __name__ == "__main__":
    unittest.main()
