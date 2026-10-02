"""Release-mode runner: no skip may pass as success.

    python3 -m emu.harness_release emu.test_wave_zones emu.test_wave_playback ...
    python3 -m emu.harness_release            # every emu.test_* suite, one after another

Sets MPC3K_RELEASE=1 (emu.harness.unavailable then raises instead of
skipping), runs the named suites in sequence, and treats any remaining skip,
expected failure or unexpected success as a failed release check.  The last
line is always `tests=N failures=F errors=E skipped=S expected_failures=X`;
the exit status is 0 only for skipped=0 and no failures or errors.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ["MPC3K_RELEASE"] = "1"


def main(argv: list[str]) -> int:
    names = argv or sorted(f"emu.{p.stem}" for p in Path(__file__).parent.glob("test_*.py"))
    loader = unittest.defaultTestLoader
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0,
              "expected_failures": 0, "unexpected_successes": 0}
    for name in names:
        print(f"== {name}", flush=True)
        result = unittest.TextTestRunner(verbosity=2).run(loader.loadTestsFromName(name))
        totals["tests"] += result.testsRun
        totals["failures"] += len(result.failures)
        totals["errors"] += len(result.errors)
        totals["skipped"] += len(result.skipped)
        totals["expected_failures"] += len(result.expectedFailures)
        totals["unexpected_successes"] += len(result.unexpectedSuccesses)
    print(" ".join(f"{k}={v}" for k, v in totals.items()))
    bad = (totals["failures"] or totals["errors"] or totals["skipped"]
           or totals["expected_failures"] or totals["unexpected_successes"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
