"""S1 characterization regression (notes/performance.md §9).

    python3 -m unittest emu.test_s1_characterize -v

Re-runs emu.s1_characterize (seven MAME runs with the fork's trace points:
stock EPROM, Route A control, Route A S1a = mods/S1A.args) and checks the
conclusions the note draws from them, including that S1a changes no result.
"""
from __future__ import annotations

import unittest

from emu import s1_characterize as s1
from emu.harness import missing_tools, run_parallel


@unittest.skipIf(missing_tools(), f"missing: {missing_tools()}")
class S1Characterization(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        jobs = s1.runs()
        run_parallel(jobs, s1.execute)
        cls.notes = {name: s1.parse(s1.OUT / f"{name}.trace", name) for name in jobs}
        cls.res = s1.analyse(cls.notes)
        cls.cost = s1.costs(jobs)

    def test_every_note_is_traced(self) -> None:
        for name, ns in self.notes.items():
            self.assertEqual(len(ns), 64 * len(s1.VELOCITIES), name)
            self.assertEqual(sorted({n.velocity for n in ns}), list(s1.VELOCITIES), name)

    def test_default_program_takes_sixteen_runtime_calls(self) -> None:
        for name in ("default", "default_rev", "ctrl_default", "s1a_default", "s1a_default_rev"):
            self.assertEqual(self.res["runs"][name]["calls_per_note"], {16: 320})
            self.assertEqual(self.res["runs"][name]["complete"], 320)

    def test_results_are_pure_functions_of_the_traced_inputs(self) -> None:
        p = self.res["purity"]
        self.assertEqual(p["operand_sets_with_two_results"], 0)
        self.assertEqual(p["input_tuples_with_two_call_lists"], 0)
        self.assertGreaterEqual(p["input_tuples_seen_more_than_once"], 300)
        self.assertEqual(p["runtime_results_not_matching_python"], 0)
        self.assertTrue(self.res["tables_constant"])
        self.assertEqual(self.res["dsp"]["tuples_with_two_sequences"], 0)
        self.assertEqual(self.res["voice_params"]["tuples_with_two_parameter_lists"], 0)

    def test_s1a_changes_no_result(self) -> None:
        """Every input tuple is traced in both builds, with equal call results,
        equal voice-start parameters and equal DSP sequences (analysed above)."""
        self.assertEqual(self.res["cross_build"]["stock+s1a"], 640)
        self.assertEqual(self.res["cross_build"]["stock+ctrl"], 320)
        for name in ("s1a_default", "s1a_varied"):
            self.assertEqual(self.res["runs"][name]["note_ons"], 320)

    def test_s1a_takes_every_divide_and_halves_the_layer(self) -> None:
        for plan in ("default", "default_rev", "varied"):
            stock, s1a = self.cost[plan], self.cost[f"s1a_{plan}"]
            self.assertLess(s1a["CFC6:039E layer"]["incl_per_call"],
                            0.6 * stock["CFC6:039E layer"]["incl_per_call"], plan)
            routed = sum(v["calls"] for k, v in s1a.items() if k.startswith("F07D:"))
            traced = sum(1 for n in self.notes[plan] for c in n.calls if c.callee in ("20FA", "2101"))
            self.assertEqual(routed, traced, plan)       # every divide of 039E, none elsewhere

    def test_velocity_dependence_on_the_default_program(self) -> None:
        for site, d in self.res["velocity"]["default"].items():
            block = site.rsplit("_", 1)[1]
            if block in "BDE":
                self.assertEqual(d["varies"], 0, site)
            else:
                self.assertEqual(d["same"], 0, site)

    def test_two_step_divu_is_exact_on_every_traced_divide(self) -> None:
        f = self.res["fast_divide"]
        self.assertGreater(f["divides"], 9000)
        self.assertEqual(f["fallback"], 0)
        self.assertEqual(f["exact"], f["divides"])

    def test_fast_divide_edge_cases_match_the_runtime_semantics(self) -> None:
        def ref(callee, a, b):
            if callee == "2101":
                return a // b
            sa = a - (1 << 32) if a >> 31 else a
            sb = b - (1 << 32) if b >> 31 else b
            q = abs(sa) // abs(sb)
            return (q if (sa < 0) == (sb < 0) else -q) & 0xFFFFFFFF
        for callee in ("20FA", "2101"):
            for a in (0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x12345678, 0xFFFF0000, 0x0000FFFF):
                for b in (1, 2, 10, 0x1B9, 0xC671, 0xFFFF):
                    self.assertEqual(s1.fast_divide(callee, a, b), ref(callee, a, b), (callee, a, b))
            self.assertIsNone(s1.fast_divide(callee, 5, 0))
            self.assertIsNone(s1.fast_divide(callee, 5, 0x10000))
        self.assertIsNone(s1.fast_divide("20FA", 100, 0xFFFFFFFF))     # negative divisor: runtime


if __name__ == "__main__":
    unittest.main()
