"""Per-event cycle budgets: PMONEY against stock OS 3.16 (release gate).

    python3 -m unittest emu.test_cycle_budget -v

Runs the workloads of emu/cycle_budget.py on the current PMONEY payload (Vailixi
3.50 BIOS set, NEC_CPU_DIV=2; 13 profile runs and 2 trace runs, about 4 min on
two workers) and compares each metric with emu/fixtures/cycle_budget_316.json.
The stock 3.16 column there is measured once per MAME pin
(`python3 -m emu.cycle_budget --refresh-stock`).  Validity guards (tick counts,
screens, call counts, a consistent interrupt-flag trace) fail before any budget is
compared.  Metrics 10 % or more under budget are printed as "tighten" notes.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest

from emu import cycle_budget as cb
from emu import harness as h
from emu.mpc3k import M3K316

GROUPS = {
    "real_time": ("idle_", "tick_", "busy_pct_play", "busy_pct_allon", "isr09_", "ifoff_", "tx_", "rx_",
                  "busy_pct_stopped"),
    "notes": ("note_", "pad_", "chord_"),
    "ui": ("int43_", "screen_", "pr_", "view_"),
    "edit_disk": ("reverse_", "silence_", "free_"),
}


@unittest.skipIf(h.missing_tools(), f"missing: {h.missing_tools()}")
class CycleBudget(unittest.TestCase):
    res: dict = {}
    problems: list = []

    @classmethod
    def setUpClass(cls) -> None:
        cls.budgets = json.loads(cb.BUDGETS.read_text())
        profile = h.payload("316", cb.BIOS)
        cls.res, cls.problems = cb.run_build("pmoney", profile)
        (cb.OUT / "report.md").write_text(cb.report(cls.res, cls.budgets))
        _, tight = cb.compare(cls.res, cls.budgets)
        for t in tight:
            print(f"tighten: {t}", file=sys.stderr)

    def test_stock_reference_is_this_pin(self) -> None:
        self.assertEqual(self.budgets["stock_m3k316_sha256"], hashlib.sha256(M3K316.read_bytes()).hexdigest())
        self.assertEqual(self.budgets["cpu_div"], 2)
        missing = [n for n, s in self.budgets["metrics"].items() if s["budget"] is None]
        self.assertEqual(missing, [], "budgets without a stock reference")

    def test_runs_are_valid(self) -> None:
        self.assertEqual(self.problems, [])

    def check(self, group: str) -> None:
        self.assertEqual(self.problems, [], "invalid runs: no budget is compared")
        names = [n for n in self.budgets["metrics"] if n.startswith(GROUPS[group])]
        self.assertTrue(names)
        for name in names:
            spec = self.budgets["metrics"][name]
            with self.subTest(metric=name):
                v = self.res.get(name)
                self.assertIsNotNone(v, f"{name} not measured")
                self.assertLessEqual(v, spec["budget"], f"{name}: {spec['note']} (rule {spec['rule']}, "
                                                        f"stock {spec['stock']})")

    def test_real_time(self) -> None:
        self.check("real_time")

    def test_note_on(self) -> None:
        self.check("notes")

    def test_ui(self) -> None:
        self.check("ui")

    def test_edit_and_disk(self) -> None:
        self.check("edit_disk")

    def test_every_budget_belongs_to_a_group(self) -> None:
        prefixes = tuple(p for g in GROUPS.values() for p in g)
        self.assertEqual([n for n in self.budgets["metrics"] if not n.startswith(prefixes)], [])


if __name__ == "__main__":
    unittest.main()
