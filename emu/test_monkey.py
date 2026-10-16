"""Monkey smoke gate: emu/monkey.py's fixed seeds on PMONEY, OS 3.16.

    python3 -m unittest emu.test_monkey -v

monkey.SMOKE_SEEDS (three seeds whose generated actions reach every PMONEY
page macro: wave view, Edit Sound Do, CHOP, compress, mute groups, System
Information, Extra Settings, sync page, timing correct, erase all, Disk 9,
and PMONEY pages while the sequencer runs), monkey.SMOKE_MINUTES of random
input each, then the liveness epilogue, on every BIOS set of
harness.bios316_sets() (all four under MPC3K_RELEASE=1).  A run passes when
monkey.judge() finds no failure class: no crash screen, no hang or stuck
screen, Play/Record reached, no write to 3.16 code or to cave instruction
bytes, cave home equal to the loader image on every instruction byte, sound
directory and floppy FAT consistent, MAME exits normally.

Outputs: build/emu/monkey/smoke/<os>-<bios>/seed<N>-.../ (MONKEY_WORK overrides).
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

try:
    from emu import harness as h
    from emu import monkey
except ImportError:                      # scratch copy: monkey.py beside this file
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import monkey                        # noqa: E402
    from emu import harness as h         # noqa: E402


class MonkeyGenerator(unittest.TestCase):
    """No MAME: the generator is deterministic and every file it writes is one MAME accepts."""

    def test_same_seed_same_actions(self) -> None:
        for seed in (1, 5, 6, 7, 14, 203):
            a = [x.to_json() for x in monkey.generate(seed, monkey.Options(5.0))]
            b = [x.to_json() for x in monkey.generate(seed, monkey.Options(5.0))]
            self.assertEqual(a, b)
            self.assertTrue(all(x["t"] >= monkey.START for x in a))

    def test_shorter_run_is_a_prefix(self) -> None:
        long = [x.to_json() for x in monkey.generate(7, monkey.Options(5.0))]
        short = [x.to_json() for x in monkey.generate(7, monkey.Options(3.0))]
        self.assertEqual(long[:len(short)], short)

    def test_midi_and_panel_files_parse_like_mame(self) -> None:
        import tempfile
        from emu.panel import write_smf
        with tempfile.TemporaryDirectory() as d:
            for seed in range(1, 41):
                acts = monkey.generate(seed, monkey.Options(5.0))
                for name, ev in (("panel", [e for a in acts for e in a.panel]),
                                 ("midi", [e for a in acts for e in a.midi])):
                    if ev:
                        monkey.check_smf(write_smf(Path(d) / f"{name}.mid", ev))

    def test_smoke_seeds_reach_every_pmoney_macro(self) -> None:
        pmoney = {"wave_view", "edit_sound_do", "chop", "compress", "mute", "sysinfo", "extra_settings",
                  "sync", "timing_correct", "erase_all", "disk9", "while_running"}
        kinds = {a.kind for seed in monkey.SMOKE_SEEDS
                 for a in monkey.generate(seed, monkey.Options(monkey.SMOKE_MINUTES))}
        self.assertEqual(pmoney - kinds, set())

    def test_sound_directory_invariants(self) -> None:
        import struct
        def rec(name, start, end, length, wave, stereo=0):
            r = bytearray(36)
            r[:16] = name.ljust(16).encode()
            r[0x13] = stereo
            struct.pack_into("<IIII", r, 0x14, start, end, length, wave)
            return bytes(r)
        ok = rec("A", 0, 10, 10, 100) + rec("B", 0, 0, 0, 110) + bytes(36 * 126)
        self.assertEqual(monkey.record_problems(ok), [])
        bad = rec("A", 9, 3, 10, 100) + rec("B", 0, 5, 5, 105, 1) + bytes(36 * 126)
        problems = monkey.record_problems(bad)
        self.assertTrue(any("start=9 end=3" in p for p in problems), problems)
        self.assertTrue(any("overlaps" in p for p in problems), problems)


class MonkeySmoke(unittest.TestCase):
    def test_smoke_seeds_pass_on_pmoney(self) -> None:
        h.require_tools()
        work = Path(os.environ.get("MONKEY_WORK", monkey.DEFAULT_WORK)).resolve()
        work.mkdir(parents=True, exist_ok=True)
        failures = monkey.smoke(work, list(h.bios316_sets()))
        self.assertEqual(failures, {}, "monkey smoke failures (see the run directories under "
                                       f"{work / 'smoke'}; `monkey.py timeline --run DIR`)")


if __name__ == "__main__":
    unittest.main()
