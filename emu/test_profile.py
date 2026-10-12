"""Cycle profiler regression (fork `nec_prof`, emu/profile.py).

    python3 -m unittest emu.test_profile -v

One short boot: a 2 s window at NEC_CPU_DIV=2 must count 16 M cycles per
second within 1 %, the dump must parse, the UI key-queue poll must dominate
once Play/Record is up, and the coverage maps must mark the reset vector.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from emu.harness import missing_tools
from emu.mpc3k import BUILD, run
from emu.panel import key_tap, write_smf
from tools.prof_report import IDLE, Window, parse

RUNS = BUILD / "emu" / "profile-tests"


@unittest.skipIf(missing_tools(), f"missing: {missing_tools()}")
class Profiler(unittest.TestCase):
    windows: dict[str, Window] = {}

    @classmethod
    def setUpClass(cls) -> None:
        out = RUNS / "boot"
        RUNS.mkdir(parents=True, exist_ok=True)
        run("vailixi", [30.5], out, panel=write_smf(RUNS / "boot.mid", key_tap("soft4", 20.0)),
            env={"NEC_PROF_DIR": str(out), "NEC_CPU_DIV": "2", "NEC_PROF_WINDOWS": "2:4,28:30"})
        cls.out = out
        cls.windows["boot"] = parse(out / "prof_0.txt", "test", "boot", 2.0, 4.0)
        cls.windows["idle"] = parse(out / "prof_1.txt", "test", "idle", 28.0, 30.0)

    def test_core_runs_at_16_mhz(self) -> None:
        for w in self.windows.values():
            self.assertAlmostEqual(w.total / w.seconds / 16_000_000, 1.0, delta=0.01)
            self.assertEqual(w.halt, 0)

    def test_dump_is_consistent(self) -> None:
        w = self.windows["idle"]
        self.assertEqual(sum(c for _, c in w.addr.values()) + w.irq_entry, w.total)
        self.assertEqual(sum(w.ss.values()), w.total - w.irq_entry)
        self.assertEqual(w.irqs, sum(v[0] for v in w.vec.values()))
        self.assertGreater(w.vec[9][0], 300)      # 192 Hz sequencer tick for 2 s
        self.assertGreater(w.vec[8][0], 150)      # 100 Hz system tick

    def test_idle_is_the_ui_key_queue_poll(self) -> None:
        w = self.windows["idle"]
        idle = sum(c for phys, (_, c) in w.addr.items()
                   if phys < 0x100000 and any(s <= (phys & 0x7FFFF) < e for s, e in IDLE))
        self.assertGreater(idle / w.total, 0.85)

    def test_coverage_marks_the_reset_vector_and_dgroup_copy(self) -> None:
        fetch = (self.out / "cov_fetch.bin").read_bytes()
        read = (self.out / "cov_read.bin").read_bytes()
        self.assertTrue(fetch[0xFFFF0 >> 3] >> (0xFFFF0 & 7) & 1)       # EA FFF0:0000 at reset
        self.assertTrue(read[0x20000 >> 3] & 1 or read[0xA0000 >> 3] & 1)  # DGROUP image copied


if __name__ == "__main__":
    unittest.main()
