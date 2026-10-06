"""Fast numeric entry from the waveform view keeps the typed digit order.

Run: python3 -m unittest emu.test_wave_numeric_order -v

The waveform loop consumes the first digit before `stock_numeric` spends
emulated time leaving graphics mode and redrawing the stock fields.  Later
panel keys arrive in the stock FIFO `8010:12BC` (3.16: DGROUP 12A4) during
that work.  The first digit must still reach the stock editor first: "0", "1"
in the seconds field is 1 s (44100 frames), while the reversed "10" is 10 s
and clamps Start to End.  Input is real panel-link traffic; the observers are
the read-only screen probe and `snddump.lua`.

Payloads come from emu.harness (built from the current sources): both cases
on the capture profile, the two-digit case also on generic, and both cases on
the 316 profile (WAVE316.SYS on OS 3.16, one BIOS set per load segment by
default, all four in release mode).  Times are relative to V = profile.view
(40 s on Vailixi, 52 s on 3.16).
"""
from __future__ import annotations

import unittest

from emu import harness as h
from emu.snd import sine441, snd
from emu.test_wave_numeric import ROOT, is_graphics, record_points, taps


RUNS = ROOT / "build/emu/wave-numeric-order-tests"
LENGTH = len(sine441()[0])          # 55125 frames: only 0 or 1 whole second fits
ONE_SECOND = 44100


class WaveNumericOrder(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"two"})
    PROFILE_NAMES = h.ALL_PROFILES

    @classmethod
    def cases(cls, profile, runs):
        V = profile.view
        # Keys 10 ms apart: the later keys are in the stock queue while the
        # first is still being handed to the text-mode editor.
        definitions = {
            "two": taps((V, "0"), (V + 0.01, "1"), (V + 2.0, "enter")),
            "enter": taps((V, "0"), (V + 0.01, "1"), (V + 0.02, "enter")),
        }
        cases = {}
        for name, events in definitions.items():
            source = runs / f"{name}.SND"
            source.write_bytes(snd(name.upper()[:16], sine441(), start=0, end=LENGTH))
            cases[name] = h.Case(events=h.wave_events(events, profile=profile),
                                 times=[V - 0.5, V + 1.0, V + 3.0],
                                 files=[(source, "TEST.SND")], parts=("snddump",),
                                 env={"SNDDUMP_PCM": "0"})
        return cases

    def run_of(self, name: str) -> tuple[str, str]:
        """Legacy case names: physical_* is the capture profile, generic_* generic."""
        profile, case = ("generic", name[8:]) if name.startswith("generic_") else ("capture", name[9:])
        if (profile, case) not in self.results:
            h.unavailable(f"{profile}/{case} not selected (MPC3K_PROFILES / MPC3K_CASES)")
        return profile, case

    def runs316(self, case: str) -> list[tuple[str, str]]:
        """(label, case) of every 316 run of `case`, one per BIOS set."""
        found = [(p, c) for (p, c) in self.results if c == case and self.profiles[p].is316]
        if not found:
            h.unavailable(f"316/{case} not selected (MPC3K_PROFILES / MPC3K_CASES)")
        return found

    def points(self, run: tuple[str, str]) -> list[tuple[int, int, int]]:
        profile, case = run
        return record_points(RUNS / profile / case / "snd_dir.log")

    def screens(self, run: tuple[str, str]) -> list[dict]:
        return self.results[run]

    def assert_typed_order(self, run: tuple[str, str]) -> None:
        screens = self.screens(run)
        self.assertTrue(is_graphics(screens[0]))
        self.assertEqual(self.points(run)[0], (0, LENGTH, LENGTH))
        # "01" -> 001.000.00 = 44100; the reversed "10" would clamp to End.
        self.assertEqual(self.points(run)[-1], (ONE_SECOND, LENGTH, LENGTH))
        self.assertTrue(is_graphics(screens[-1]), screens[-1]["rows"][2])

    def assert_open_draft(self, run: tuple[str, str]) -> None:
        # Before Enter, the stock seconds field shows the uncommitted draft.
        draft = self.screens(run)[1]
        self.assertFalse(is_graphics(draft))
        self.assertTrue(draft["rows"][2].startswith("Soft.st.:01"), draft["rows"][2])

    def assert_burst_commits(self, run: tuple[str, str]) -> None:
        # Enter follows in the same burst.  It must commit "01" and close the
        # dialog without leaving the first digit queued behind it, where the
        # waveform loop would read it and reopen a second numeric dialog.
        self.assert_typed_order(run)
        screen = self.screens(run)[1]
        self.assertTrue(is_graphics(screen), screen["rows"][2])

    def test_physical_profile_two_fast_digits(self) -> None:
        self.assert_open_draft(self.run_of("physical_two"))
        self.assert_typed_order(self.run_of("physical_two"))

    def test_physical_profile_digits_and_enter_in_one_burst(self) -> None:
        self.assert_burst_commits(self.run_of("physical_enter"))

    def test_generic_profile_two_fast_digits(self) -> None:
        self.assert_open_draft(self.run_of("generic_two"))
        self.assert_typed_order(self.run_of("generic_two"))

    def test_316_profile_two_fast_digits(self) -> None:
        for run in self.runs316("two"):
            with self.subTest(profile=run[0]):
                self.assert_open_draft(run)
                self.assert_typed_order(run)

    def test_316_profile_digits_and_enter_in_one_burst(self) -> None:
        for run in self.runs316("enter"):
            with self.subTest(profile=run[0]):
                self.assert_burst_commits(run)


if __name__ == "__main__":
    unittest.main()
