"""MUTE GROUPS hooks reject an out-of-range program index.

Every stock caller passes 1..24 (notes/mute_storage.md, "Index bounds"), so
an out-of-range index is fault-injected: emu/lua/mute_range_inject.lua sets
the caller's one-based index to 25 only while the cave hook runs, zeroes
the 33 ``mute_staging`` bytes (the address ``mute_state_bx(24)`` returns),
and restores the index when control is back in the stock caller.

Without the range checks the hook would treat index 24 as a program and
write 33 bytes at ``mute_staging``, or write them to disk.  With the checks
the stock operation completes and the mod state is untouched.  The payloads
and their maps are built from the current sources by emu.harness: capture,
and the 316 profile (WAVE316.SYS on OS 3.16; one BIOS set per load segment
by default, all four in release mode).  Times are Vailixi times moved by
emu.test_mute_ui.delay(profile) (13 s on 3.16).
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest

from emu import harness as h
from emu import pgm
from emu.harness import taps
from emu.mpc3k import DISKS
from emu.panel import dial
from emu.test_mute_persistence import pgm_save_events, stale_then_load_events
from emu.test_mute_ui import PARTS, at, delay, each_run, later, states

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-range-tests"
ZERO = {"enabled": 0, "groups": [0] * 64}
STALE = {"enabled": 1, "groups": [4] + [0] * 63}       # stale_then_load_events, Program 2
COPIED = {"enabled": 1, "groups": [4] * 63 + [2]}      # emu.test_mute_lifecycle, Program 1

# hook label, caller frame offset, width, return site in the stock caller,
# earliest emulated second (the startup loader also loads VALID.PGM)
SITES = {
    "copy": ("mute_program_copy_hook", -2, 1, 0xC887, 0x19FB, 0),    # destination [BP-2]
    "load": ("mute_pgm_load_close", 0x0A, 1, 0xC20F, 0x0417, 36),   # destination [BP+0Ah]
    # CB10:10C4 enters the PGM writer as E86E:000D (= E7F5:079D), so its
    # return site E7F5:0A03 runs as E86E:0273.
    "save": ("mute_pgm_save_close", 0x06, 2, 0xE86E, 0x0273, 0),    # source [BP+06h]
}
# The same return sites in 3.16 (relative seg:off; CS = L + seg at run time).
# copy: the hook's own FJMP target T_C887_19FB (mods/profile_316.inc).
# load: the PGM loader 1396:0009 (image 0x13969) is C20F:0003 instruction for
#   instruction (431 each, same frame, SUB SP,0B36h); its close CALLF 200D:008C
#   at 1396:0418 (image 0x13D78, the mute_pgm_load_close hook site) returns to
#   1396:041D.  The only far references to segment 1396 are CALLF 1396:0009
#   (images 0x2A32, 0x799F) and 1396:04FC, so it runs with CS = L+1396.
# save: the PGM writer 3E8F:0009 (image 0x3E8F9) is E86E:000D instruction for
#   instruction (237 each, SUB SP,0ADCh); its close CALLF at 3E8F:026A (image
#   0x3EB5A, the mute_pgm_save_close hook site) returns to 3E8F:026F.  The
#   only far references to segment 3E8F are CALLF 3E8F:0009 at image 0x1D419
#   (PUSH [BP-0Ah] / CALLF / ADD SP,2 / MOV [BP-6],AX, as at CB10:10C1) and
#   CALLF 3E8F:0413, so it runs with CS = L+3E8F.
SITES_316 = {"copy": h.targets316()["T_C887_19FB"], "load": (0x1396, 0x041D), "save": (0x3E8F, 0x026F)}


def injector(name: str, profile: h.Profile) -> str:
    """The suite prelude: INJECT for emu/lua/mute_range_inject[316].lua."""
    label, frame, width, seg, off, after = SITES[name]
    if profile.is316:
        site = profile.runtime(*SITES_316[name])
        seg, off = site.cs, site.ip
    offsets = profile.symbols()
    return (f"INJECT={{hook={offsets[label]},frame={frame},width={width},value=25,"
            f"back_seg={seg},back_off={off},staging={offsets['mute_staging']},"
            f"after={after + delay(profile)}}}")


def case_disk(profile: h.Profile, runs: Path, case: str) -> Path:
    """The floppy harness.run_case() mounts for `case` (its wave_disk name)."""
    return DISKS / f"{profile.label}-{runs.name}-{case}.img"


def copy_events():
    # emu.test_mute_lifecycle up to its Copy 1 Program to Another (1 -> 24).
    # Soft Key 1 opens the Apply All prompt; Soft Key 3 <Do it> applies.
    events = taps((20, "soft4"), (23, "program_sounds"), (25, "0"), (27, "+"),
                  (28, "right"), (29, "right"), (30, "4"), (31, "soft1"), (31.5, "soft3"),
                  (32, "left"), (33, "6"), (33.3, "4"), (34, "right"), (35, "2"),
                  (36, "soft4"), (38, "4"), (40, "2"), (42, "down"))
    return events + dial(23, 43) + taps((47, "soft1"))


class MuteRange(h.EmuSuite):
    RUNS = RUNS
    PROFILE_NAMES = h.ALL_PROFILES        # no GENERIC case: capture and 316
    saved: dict[str, bytes] = {}

    @classmethod
    def cases(cls, profile, runs):
        if not pgm.NATIVE_BLANK_PATH.is_file():
            h.unavailable(f"native PGM fixture is missing: {pgm.NATIVE_BLANK_PATH}")
        valid = runs / "VALID.PGM"
        valid.write_bytes(pgm.with_mute_state(enabled=True, groups=[1] * 64))
        # setUpClass reads PROGRAM_.PGM back from this image: it must be this run's.
        case_disk(profile, runs, "save").unlink(missing_ok=True)
        t, dt = at(profile), delay(profile)
        definitions = {
            "copy": ([35.5, 48], [], copy_events()),
            "load": ([34, 55], [(valid, "VALID.PGM")], stale_then_load_events()),
            "save": ([39, 62], [], pgm_save_events()),
        }
        return {name: h.Case(events=later(events, dt), times=[t(x) for x in times], files=files,
                             parts=("mute_range_inject", *PARTS), prelude=injector(name, profile))
                for name, (times, files, events) in definitions.items()}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.saved = {}
        for (label, case) in cls.results:
            if case == "save":
                runs = cls.RUNS / label
                target = runs / "saved.PGM"
                target.unlink(missing_ok=True)
                subprocess.run(["mcopy", "-i", str(case_disk(cls.profiles[label], runs, case)),
                                "::PROGRAM_.PGM", str(target)], check=True)
                cls.saved[label] = target.read_bytes()

    def injected(self, d: Path) -> str:
        log = (d / "inject.txt").read_text()
        self.assertEqual(len(re.findall(r"^inject ", log, re.M)), 1, log)
        self.assertIn("value=25", log)
        staged = re.search(r"^restore \S+ staging=([0-9a-f]+)$", log, re.M)
        self.assertIsNotNone(staged, log)
        return staged.group(1)

    def test_copy_to_out_of_range_destination_changes_no_mod_state(self):
        for label, _, d, _, t in each_run(self, "copy"):
            with self.subTest(profile=label):
                self.assertEqual(self.injected(d), "00" * 33)
                before, after = states(d, t(35.5)), states(d, t(48))
                self.assertEqual(before[0], COPIED)
                self.assertEqual(after, before)

    def test_load_close_with_out_of_range_destination_only_closes(self):
        for label, _, d, screens, t in each_run(self, "load"):
            with self.subTest(profile=label):
                self.assertEqual(self.injected(d), "00" * 33)
                # The trailer is neither read nor committed, and no slot is cleared.
                self.assertEqual(states(d, t(34))[1], STALE)
                self.assertEqual(states(d, t(55)), states(d, t(34)))
                self.assertNotIn("Attention", "\n".join(screens[-1]["rows"]))

    def test_save_close_with_out_of_range_source_writes_stock_file(self):
        for label, _, d, screens, _ in each_run(self, "save"):
            with self.subTest(profile=label):
                self.injected(d)
                saved = self.saved[label]
                self.assertEqual(len(saved), pgm.PGM_BYTES)
                self.assertEqual(saved[:2], b"\x07\x00")
                self.assertNotIn("Attention", "\n".join(screens[-1]["rows"]))


if __name__ == "__main__":
    unittest.main()
