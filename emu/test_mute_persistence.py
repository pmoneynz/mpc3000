"""MUTE GROUPS persistence through native PGM/APS Disk paths.

The observer is read-only.  Every state transition comes from real panel
events, stock Disk save/load code, or the stock startup-file loader.

Profiles: capture, and 316 (WAVE316.SYS on OS 3.16) once per BIOS set of
harness.bios316_sets(), all four in release mode.  On 3.16 every panel time is
the Vailixi time plus offset() = the later SCSI cancel (33.0 instead of 20.0);
the hooked load/save close calls are 3.16's own (mods/WAVE316.args), so every
assertion is the same.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import unittest

from emu import harness as h
from emu import pgm
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.test_mute_ui import observer, states

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-persistence-tests"
NATIVE_PGM_SHA256 = "92fb1c621c10db67788da83b4f2dfc7d97919b16d1f2472886f871495023e733"
ZERO = {"enabled": 0, "groups": [0] * 64}


def suite_profiles() -> list[h.Profile]:
    """capture, then 316 once per BIOS set of harness.bios316_sets().
    MPC3K_PROFILES=capture (or 316) narrows a development run."""
    wanted = set(filter(None, os.environ.get("MPC3K_PROFILES", "").split(","))) or {"capture", "316"}
    profiles = [h.payload("capture")] if "capture" in wanted else []
    if "316" in wanted:
        profiles += [h.payload("316", bios) for bios in h.bios316_sets()]
    return profiles


def offset(profile: h.Profile | None = None) -> float:
    """Added to every Vailixi panel time: 0, or 13.0 on 3.16 (SCSI cancel 33.0)."""
    return 0.0 if profile is None else profile.timeline.cancel - h.CANCEL_SCSI


def taps_at(d: float, *items: tuple[float, str]) -> list[tuple[float, bytes]]:
    return h.taps(*((at + d, key) for at, key in items))


def extract(image: Path, dos_name: str, destination: Path) -> bytes:
    destination.unlink(missing_ok=True)
    subprocess.run(["mcopy", "-i", str(image), f"::{dos_name}", str(destination)], check=True)
    return destination.read_bytes()


def pgm_save_events(d: float = 0.0):
    # Configure Program 2 while Program 1 was active, return to Program 1,
    # then choose Program 2 independently on the stock Save a Program page.
    return (taps_at(d, (20, "soft4"), (23, "program_sounds"), (25, "0"),
                 (27, "left"), (28, "+"), (29, "right"), (30, "+"),
                 (31, "right"), (32, "right"), (33, "3"),
                 (35, "left"), (36, "left"), (37, "left"), (38, "-"),
                 (40, "soft4"), (43, "disk"), (45, "4"))
            + dial(1, 48 + d) + taps_at(d, (50, "soft1")))


def aps_save_events(d: float = 0.0):
    # Program 1: enabled, pad 1 group 1.  Program 2: enabled, pad 1 group 2.
    # Return to Program 1 before saving all programs.
    return taps_at(d, (20, "soft4"), (23, "program_sounds"), (25, "0"),
                (27, "+"), (28, "right"), (29, "right"), (30, "1"),
                (32, "left"), (33, "left"), (34, "left"), (35, "+"),
                (36, "right"), (37, "+"), (38, "right"), (39, "right"),
                (40, "2"), (42, "left"), (43, "left"), (44, "left"),
                (45, "-"), (47, "soft4"), (50, "disk"), (52, "5"),
                (55, "soft1"))


def stale_then_load_events(d: float = 0.0):
    # Give Program 2 unmistakable stale state, leave it selected, and load the
    # sole PGM into that destination using Disk / 7 / Load / Load it.
    return taps_at(d, (20, "soft4"), (23, "program_sounds"), (25, "0"),
                (27, "left"), (28, "+"), (29, "right"), (30, "+"),
                (31, "right"), (32, "right"), (33, "4"), (35, "soft4"),
                (38, "disk"), (40, "7"), (43, "soft1"), (46, "soft1"))


class MutePersistence(unittest.TestCase):
    profiles: dict[str, h.Profile] = {}

    @classmethod
    def setUpClass(cls):
        if not pgm.NATIVE_BLANK_PATH.is_file():
            h.unavailable(f"native PGM fixture is missing: {pgm.NATIVE_BLANK_PATH}")
        native = pgm.native_blank()
        if hashlib.sha256(native).hexdigest() != NATIVE_PGM_SHA256:
            raise RuntimeError("native PGM fixture hash changed")
        cls.profiles = {p.label: p for p in suite_profiles()}
        probes = {}
        for label, profile in cls.profiles.items():
            (RUNS / label).mkdir(parents=True, exist_ok=True)
            profile.record(RUNS)
            probes[label] = observer(RUNS / label, profile=profile)

        def execute(key, job):
            label, name = key
            times, image, events = job
            profile = cls.profiles[label]
            return run(profile.bios, times, RUNS / label / name, floppy=image,
                       panel=write_smf(RUNS / label / f"{name}.mid", events), rompath=profile.rompath,
                       extra=["-autoboot_script", str(probes[label])])

        # The two saves are independent and both use the stock Disk UI.
        saves = {}
        for label, profile in cls.profiles.items():
            d = offset(profile)
            saves[(label, "pgm-save")] = ([39 + d, 49 + d, 62 + d],
                                          h.wave_disk(profile, "mute-persistence-pgm-save"),
                                          pgm_save_events(d))
            saves[(label, "aps-save")] = ([46 + d, 54 + d, 76 + d],
                                          h.wave_disk(profile, "mute-persistence-aps-save"),
                                          aps_save_events(d))
        cls.screens = h.run_parallel(saves, execute, 4)

        cls.saved_pgm, cls.saved_aps = {}, {}
        loads = {}
        for label, profile in cls.profiles.items():
            runs, d = RUNS / label, offset(profile)
            cls.saved_pgm[label] = extract(saves[(label, "pgm-save")][1], "PROGRAM_.PGM",
                                           runs / "saved-program-2.PGM")
            cls.saved_aps[label] = extract(saves[(label, "aps-save")][1], "ALL_PGMS.APS",
                                           runs / "saved-all.APS")

            # Exact malformed payload: valid header and length, invalid group nibble.
            malformed = bytearray(pgm.with_mute_state(enabled=True, groups=[1] * 64))
            malformed[pgm.PGM_BYTES + pgm.MUTE_HEADER.size + 1] = 0xF1
            malformed_path = runs / "MALFORM.PGM"
            malformed_path.write_bytes(malformed)

            cold_pgm_image = h.wave_disk(profile, "mute-persistence-pgm-cold", [
                                   (runs / "saved-program-2.PGM", "SOURCE2.PGM")])
            cold_aps_image = h.wave_disk(profile, "mute-persistence-aps-cold", [
                                   (runs / "saved-all.APS", "ALL_PGMS.APS")])
            legacy_image = h.wave_disk(profile, "mute-persistence-legacy", [
                                (pgm.NATIVE_BLANK_PATH, "LEGACY.PGM")])
            malformed_image = h.wave_disk(profile, "mute-persistence-malformed", [
                                   (malformed_path, "MALFORM.PGM")])
            # Startup also sees the PGM, then the explicit Disk path selects
            # destination Program 2 before the second load.
            loads[(label, "pgm-cold")] = (
                [30 + d, 32 + d, 50 + d], cold_pgm_image,
                taps_at(d, (20, "soft4"), (23, "disk"), (25, "7"), (28, "soft1"))
                + dial(1, 31 + d) + taps_at(d, (33, "soft1")))
            # APS is loaded by the stock cold-start file loader.
            loads[(label, "aps-cold")] = ([50 + d], cold_aps_image, taps_at(d, (20, "soft4")))
            loads[(label, "legacy")] = ([34 + d, 55 + d], legacy_image, stale_then_load_events(d))
            loads[(label, "malformed")] = ([34 + d, 55 + d], malformed_image, stale_then_load_events(d))
        cls.screens.update(h.run_parallel(loads, execute, 4))

    def each(self):
        """(label, run directory, panel-time offset) of every profile that ran."""
        self.assertTrue(self.profiles, "no profile ran")
        for label, profile in self.profiles.items():
            yield label, RUNS / label, offset(profile)

    def test_pgm_save_uses_chosen_source_and_cold_load_uses_chosen_destination(self):
        expected = {"enabled": 1, "groups": [3] + [0] * 63}
        for label, runs, d in self.each():
            with self.subTest(profile=label):
                before = states(runs / "pgm-save", 39 + d)
                self.assertEqual(before[0], ZERO)
                self.assertEqual(before[1], expected)
                saved = self.saved_pgm[label]
                self.assertEqual(len(saved), pgm.PGM_BYTES + pgm.MUTE_HEADER.size + 33)
                self.assertEqual(pgm.read_mute_trailer(saved), [expected])
                loaded = states(runs / "pgm-cold", 50 + d)
                self.assertEqual(loaded[1], expected)

    def test_aps_multi_program_round_trip(self):
        one = {"enabled": 1, "groups": [1] + [0] * 63}
        two = {"enabled": 1, "groups": [2] + [0] * 63}
        for label, runs, d in self.each():
            with self.subTest(profile=label):
                before = states(runs / "aps-save", 46 + d)
                self.assertEqual(before[:2], [one, two])
                saved = self.saved_aps[label]
                trailer_at = saved.rfind(pgm.MUTE_MAGIC)
                self.assertGreater(trailer_at, 0)
                self.assertEqual(len(saved) - trailer_at, pgm.MUTE_HEADER.size + 24 * 33)
                trailer = pgm.read_mute_trailer(saved, trailer_at)
                self.assertEqual(trailer[:2], [one, two])
                self.assertEqual(trailer[2:], [ZERO] * 22)
                self.assertEqual(states(runs / "aps-cold", 50 + d), trailer)

    def test_legacy_pgm_clears_stale_destination_state(self):
        stale = {"enabled": 1, "groups": [4] + [0] * 63}
        for label, runs, d in self.each():
            with self.subTest(profile=label):
                self.assertEqual(states(runs / "legacy", 34 + d)[1], stale)
                self.assertEqual(states(runs / "legacy", 55 + d)[1], ZERO)

    def test_malformed_trailer_is_rejected_transactionally(self):
        stale = {"enabled": 1, "groups": [4] + [0] * 63}
        for label, runs, d in self.each():
            with self.subTest(profile=label):
                self.assertEqual(states(runs / "malformed", 34 + d)[1], stale)
                self.assertEqual(states(runs / "malformed", 55 + d)[1], ZERO)


if __name__ == "__main__":
    unittest.main()
