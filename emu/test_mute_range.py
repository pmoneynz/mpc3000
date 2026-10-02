"""MUTE GROUPS hooks reject an out-of-range program index.

Every stock caller passes 1..24 (notes/mute_storage.md, "Index bounds"), so
an out-of-range index is fault-injected: emu/lua/mute_range_inject.lua sets
the caller's one-based index to 25 only while the cave hook runs, zeroes
the 33 ``mute_staging`` bytes (the address ``mute_state_bx(24)`` returns),
and restores the index when control is back in the stock caller.

Without the range checks the hook would treat index 24 as a program and
write 33 bytes at ``mute_staging``, or write them to disk.  With the checks
the stock operation completes and the mod state is untouched.  The capture
payload and its map are built from the current sources by emu.harness.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import unittest

from emu import harness as h
from emu import pgm
from emu.harness import taps
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.test_mute_persistence import pgm_save_events, stale_then_load_events
from emu.test_mute_ui import observer, states

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


def injector(name: str, profile: h.Profile) -> Path:
    label, frame, width, seg, off, after = SITES[name]
    offsets = profile.symbols()
    prefix = (f"INJECT={{hook={offsets[label]},frame={frame},width={width},value=25,"
              f"back_seg={seg},back_off={off},staging={offsets['mute_staging']},"
              f"after={after}}}\n")
    observe = observer(RUNS / name, profile=profile)
    script = RUNS / name / "inject.lua"
    script.write_text(prefix + (ROOT / "emu/lua/mute_range_inject.lua").read_text()
                      + "\n" + observe.read_text())
    return script


def copy_events():
    # emu.test_mute_lifecycle up to its Copy 1 Program to Another (1 -> 24).
    # Soft Key 1 opens the Apply All prompt; Soft Key 3 <Do it> applies.
    events = taps((20, "soft4"), (23, "program_sounds"), (25, "0"), (27, "+"),
                  (28, "right"), (29, "right"), (30, "4"), (31, "soft1"), (31.5, "soft3"),
                  (32, "left"), (33, "6"), (33.3, "4"), (34, "right"), (35, "2"),
                  (36, "soft4"), (38, "4"), (40, "2"), (42, "down"))
    return events + dial(23, 43) + taps((47, "soft1"))


class MuteRange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile = h.payload("capture")
        if not pgm.NATIVE_BLANK_PATH.is_file():
            h.unavailable(f"native PGM fixture is missing: {pgm.NATIVE_BLANK_PATH}")
        valid = RUNS / "VALID.PGM"
        RUNS.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        valid.write_bytes(pgm.with_mute_state(enabled=True, groups=[1] * 64))
        cases = {
            "copy": ([35.5, 48], h.wave_disk(profile, "mute-range-copy"), copy_events()),
            "load": ([34, 55], h.wave_disk(profile, "mute-range-load", [(valid, "VALID.PGM")]),
                     stale_then_load_events()),
            "save": ([39, 62], h.wave_disk(profile, "mute-range-save"), pgm_save_events()),
        }
        for name in cases:
            (RUNS / name).mkdir(parents=True, exist_ok=True)
        scripts = {name: injector(name, profile) for name in cases}

        def execute(item):
            name, (times, image, events) = item
            out = RUNS / f"{name}-run"
            screens = run("vailixi", times, out, floppy=image,
                          panel=write_smf(RUNS / f"{name}.mid", events), rompath=profile.rompath,
                          extra=["-autoboot_script", str(scripts[name])])
            return name, (out, screens)

        with ThreadPoolExecutor(max_workers=3) as pool:
            cls.results = dict(pool.map(execute, cases.items()))
        image = cases["save"][1]
        target = RUNS / "saved.PGM"
        target.unlink(missing_ok=True)
        subprocess.run(["mcopy", "-i", str(image), "::PROGRAM_.PGM", str(target)], check=True)
        cls.saved = target.read_bytes()

    def injected(self, name: str) -> str:
        out = self.results[name][0]
        log = (out / "inject.txt").read_text()
        self.assertEqual(len(re.findall(r"^inject ", log, re.M)), 1, log)
        self.assertIn("value=25", log)
        staged = re.search(r"^restore \S+ staging=([0-9a-f]+)$", log, re.M)
        self.assertIsNotNone(staged, log)
        return staged.group(1)

    def last_screen(self, name: str) -> str:
        return "\n".join(self.results[name][1][-1]["rows"])

    def test_copy_to_out_of_range_destination_changes_no_mod_state(self):
        self.assertEqual(self.injected("copy"), "00" * 33)
        out = self.results["copy"][0]
        before, after = states(out, 35.5), states(out, 48)
        self.assertEqual(before[0], COPIED)
        self.assertEqual(after, before)

    def test_load_close_with_out_of_range_destination_only_closes(self):
        self.assertEqual(self.injected("load"), "00" * 33)
        out = self.results["load"][0]
        # The trailer is neither read nor committed, and no slot is cleared.
        self.assertEqual(states(out, 34)[1], STALE)
        self.assertEqual(states(out, 55), states(out, 34))
        self.assertNotIn("Attention", self.last_screen("load"))

    def test_save_close_with_out_of_range_source_writes_stock_file(self):
        self.injected("save")
        self.assertEqual(len(self.saved), pgm.PGM_BYTES)
        self.assertEqual(self.saved[:2], b"\x07\x00")
        self.assertNotIn("Attention", self.last_screen("save"))


if __name__ == "__main__":
    unittest.main()
