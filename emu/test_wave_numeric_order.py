"""Fast numeric entry from the waveform view keeps the typed digit order.

Run: python3 -m unittest emu.test_wave_numeric_order -v

The waveform loop consumes the first digit before `stock_numeric` spends
emulated time leaving graphics mode and redrawing the stock fields.  Later
panel keys arrive in the stock FIFO `8010:12BC` during that work.  The first
digit must still reach the stock editor first: "0", "1" in the seconds field
is 1 s (44100 frames), while the reversed "10" is 10 s and clamps Start to
End.  Input is real panel-link traffic; the observers are the read-only
screen probe and `snddump.lua`.

Payloads come from emu.harness (built from the current sources): both cases
on the capture profile, the two-digit case also on generic.  Times follow
the early timeline (wave view from harness.VIEW; previously 80 s).
"""
from __future__ import annotations

import unittest

from emu import harness as h
from emu.harness import VIEW as V
from emu.snd import sine441, snd
from emu.test_wave_numeric import ROOT, is_graphics, record_points, taps


RUNS = ROOT / "build/emu/wave-numeric-order-tests"
LENGTH = len(sine441()[0])          # 55125 frames: only 0 or 1 whole second fits
ONE_SECOND = 44100


class WaveNumericOrder(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"two"})

    @classmethod
    def cases(cls, profile, runs):
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
            cases[name] = h.Case(events=h.wave_events(events), times=[V - 0.5, V + 1.0, V + 3.0],
                                 files=[(source, "TEST.SND")], parts=("snddump",),
                                 env={"SNDDUMP_PCM": "0"})
        return cases

    def run_of(self, name: str) -> tuple[str, str]:
        """Legacy case names: physical_* is the capture profile, generic_* generic."""
        profile, case = ("generic", name[8:]) if name.startswith("generic_") else ("capture", name[9:])
        if (profile, case) not in self.results:
            h.unavailable(f"{profile}/{case} not selected (MPC3K_PROFILES / MPC3K_CASES)")
        return profile, case

    def points(self, name: str) -> list[tuple[int, int, int]]:
        profile, case = self.run_of(name)
        return record_points(RUNS / profile / case / "snd_dir.log")

    def screens(self, name: str) -> list[dict]:
        return self.results[self.run_of(name)]

    def assert_typed_order(self, name: str) -> None:
        screens = self.screens(name)
        self.assertTrue(is_graphics(screens[0]))
        self.assertEqual(self.points(name)[0], (0, LENGTH, LENGTH))
        # "01" -> 001.000.00 = 44100; the reversed "10" would clamp to End.
        self.assertEqual(self.points(name)[-1], (ONE_SECOND, LENGTH, LENGTH))
        self.assertTrue(is_graphics(screens[-1]), screens[-1]["rows"][2])

    def assert_open_draft(self, name: str) -> None:
        # Before Enter, the stock seconds field shows the uncommitted draft.
        draft = self.screens(name)[1]
        self.assertFalse(is_graphics(draft))
        self.assertTrue(draft["rows"][2].startswith("Soft.st.:01"), draft["rows"][2])

    def test_physical_profile_two_fast_digits(self) -> None:
        self.assert_open_draft("physical_two")
        self.assert_typed_order("physical_two")

    def test_physical_profile_digits_and_enter_in_one_burst(self) -> None:
        # Enter follows in the same burst.  It must commit "01" and close the
        # dialog without leaving the first digit queued behind it, where the
        # waveform loop would read it and reopen a second numeric dialog.
        self.assert_typed_order("physical_enter")
        screen = self.screens("physical_enter")[1]
        self.assertTrue(is_graphics(screen), screen["rows"][2])

    def test_generic_profile_two_fast_digits(self) -> None:
        self.assert_open_draft("generic_two")
        self.assert_typed_order("generic_two")


if __name__ == "__main__":
    unittest.main()
