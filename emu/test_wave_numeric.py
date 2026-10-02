"""Numeric-entry regressions for the waveform view.

Run: python3 -m unittest emu.test_wave_numeric -v

Payloads come from emu.harness, built from the current sources: every case
on the capture profile, the GENERIC subset also on the generic profile, so
both documented NUM_EDITING layouts execute.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from emu import harness as h
from emu.harness import VIEW as V, taps
from emu.snd import sine441, snd, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-numeric-tests"
WAVE_START, WAVE_END = 13781, 48000
STEREO_START, STEREO_END = 5000, 30000
# Legacy names for modules that import them from here.
MODS = ROOT / "build/mods"
PHYSICAL_ROMS = ROOT / "build/roms-wavehw-composite"
GENERIC_ROMS = ROOT / "build/roms"
SND_DUMP = h.SNDDUMP


def record_points(path: Path) -> list[tuple[int, int, int]]:
    """Return (start, end, length) for the sole sound at each probe time."""
    return [tuple(map(int, values)) for values in re.findall(
        r"^idx 0 .* start=(\d+) end=(\d+) len=(\d+)",
        path.read_text(), re.MULTILINE)]


def is_graphics(screen: dict) -> bool:
    return "mode=32" in screen["head"]


class WaveNumeric(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"generic_basic", "cancel_typed", "start_clamp", "sample44_idle_enter"})

    @classmethod
    def cases(cls, profile, runs):
        small = [[0] * 2000]
        definitions = {
            # name: planes, start, end, keys, probe times
            "cancel_typed": (
                sine441(), WAVE_START, WAVE_END,
                taps((V, "9"), (V + 1, "soft4"), (V + 3, "soft4")),
                [V - 0.5, V + 0.5, V + 1.5, V + 4]),
            "sample44_idle_enter": (
                sine441(), 44099, 48000,
                taps((V, "enter"), (V + 1, "enter")), [V - 0.5, V + 0.5, V + 2]),
            "sample44_idle_right": (
                sine441(), 44099, 48000,
                taps((V, "enter"), (V + 1, "right"), (V + 2, "right"), (V + 3, "right")),
                [V - 0.5, V + 0.5, V + 1.5, V + 2.5, V + 4]),
            "start_clamp": (
                small, 100, 1000,
                taps((V, "9"), (V + 1.5, "enter")), [V - 0.5, V + 0.5, V + 2.5]),
            "end_clamp": (
                small, 100, 1000,
                taps((V - 1, "right"), (V, "0"), (V + 1, "right"), (V + 2, "0"),
                     (V + 3, "right"), (V + 4, "0"), (V + 5, "enter")),
                [V - 0.5, V + 0.5, V + 2.5, V + 4.5, V + 6]),
            "navigation_bounds": (
                small, 100, 1000,
                taps((V, "enter"), (V + 1, "left"), (V + 2, "right"),
                     (V + 3, "right"), (V + 4, "right")),
                [V - 0.5, V + 0.5, V + 1.5, V + 2.5, V + 3.5, V + 5]),
            "mode_exit": (
                small, 100, 1000,
                taps((V, "9"), (V + 1, "main_screen")), [V - 0.5, V + 0.5, V + 2.5]),
            "view_ignores_numeric": (
                stereo1(), STEREO_START, STEREO_END,
                taps((V - 1, "right"), (V - 0.5, "right"), (V + 0.5, "9"),
                     (V + 1.5, "enter"), (V + 2.5, "soft4")),
                [V - 0.25, V + 1, V + 2, V + 3.5]),
            "generic_basic": (
                sine441(), 0, len(sine441()[0]),
                taps((V + 1, "0"), (V + 2, "right"), (V + 3, "1"), (V + 3.5, "0"),
                     (V + 4, "right"), (V + 5, "4"), (V + 5.5, "3"), (V + 6, "enter")),
                [V, V + 1.5, V + 2.5, V + 4.5, V + 6.5]),
        }
        cases = {}
        for name, (planes, start, end, events, times) in definitions.items():
            source = runs / f"{name}.SND"
            source.write_bytes(snd(name.upper()[:16], planes, start=start, end=end))
            cases[name] = h.Case(events=h.wave_events(events), times=times,
                                 files=[(source, "TEST.SND")], parts=("repeat_watch", "snddump"),
                                 env={"SNDDUMP_PCM": "0"})
        return cases

    def points(self, d: Path) -> list[tuple[int, int, int]]:
        return record_points(d / "snd_dir.log")

    def test_typed_cancel_discards_draft_and_restores_graphics(self) -> None:
        for prof, d, s in self.each("cancel_typed"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d), [(WAVE_START, WAVE_END, len(sine441()[0]))] * 4)
                self.assertFalse(is_graphics(s[1]))
                self.assertTrue(is_graphics(s[2]))
                self.assertIn("Edit Snd:", s[-1]["rows"][0])

    def test_idle_enter_preserves_unrepresentable_sample_44(self) -> None:
        for prof, d, s in self.each("sample44_idle_enter"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d), [(44099, 48000, len(sine441()[0]))] * 3)
                self.assertTrue(is_graphics(s[0]))
                self.assertFalse(is_graphics(s[1]))
                self.assertTrue(is_graphics(s[2]))

    def test_idle_right_navigation_preserves_unrepresentable_sample_44(self) -> None:
        for prof, d, s in self.each("sample44_idle_right"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d), [(44099, 48000, len(sine441()[0]))] * 5)
                self.assertTrue(is_graphics(s[0]))
                self.assertFalse(any(map(is_graphics, s[1:-1])))
                self.assertTrue(is_graphics(s[-1]))

    def test_start_is_clamped_to_end(self) -> None:
        for prof, d, s in self.each("start_clamp"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d)[-1], (1000, 1000, 2000))
                self.assertFalse(is_graphics(s[1]))      # the digit opened the editor
                self.assertTrue(is_graphics(s[-1]))

    def test_end_is_clamped_to_start(self) -> None:
        for prof, d, s in self.each("end_clamp"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d)[-1], (100, 100, 2000))
                self.assertTrue(is_graphics(s[-1]))

    def test_navigation_is_bounded_to_selected_component_triple(self) -> None:
        for prof, d, s in self.each("navigation_bounds"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d), [(100, 1000, 2000)] * 6)
                self.assertFalse(is_graphics(s[1]))
                self.assertTrue(is_graphics(s[-1]))

    def test_mode_key_discards_draft_and_leaves_wave_page(self) -> None:
        for prof, d, s in self.each("mode_exit"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d), [(100, 1000, 2000)] * 3)
                self.assertFalse(is_graphics(s[1]))      # a draft really existed
                self.assertIn("Play/Record", s[-1]["rows"][0])

    def test_view_field_ignores_digits_and_enter(self) -> None:
        expected = (STEREO_START, STEREO_END, len(stereo1()[0]))
        for prof, d, s in self.each("view_ignores_numeric"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d), [expected] * 4)
                self.assertTrue(is_graphics(s[1]))
                self.assertTrue(is_graphics(s[2]))
                self.assertIn("Edit Snd:", s[-1]["rows"][0])

    def test_generic_profile_uses_its_numeric_state_layout(self) -> None:
        # 0 s, 10 ms, 43 samples = 441 + 43 frames, through each profile's
        # own NUM_EDITING layout.
        for prof, d, s in self.each("generic_basic"):
            with self.subTest(profile=prof):
                self.assertEqual(self.points(d)[0][0], 0)
                self.assertEqual(self.points(d)[-1][0], 484)
                self.assertTrue(is_graphics(s[-1]))


if __name__ == "__main__":
    unittest.main()
