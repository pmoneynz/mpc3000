"""Numeric-entry regressions for the waveform view.

Run: python3 -m unittest emu.test_wave_numeric -v

The main cases use the captured-ROM WAVEHW fixture.  A single reference case
uses the generic WAVE payload so both documented NUM_EDITING layouts execute.
This module deliberately consumes existing payload/ROM fixtures: it does not
rebuild them and is safe to run while the build owners validate those files.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import key_tap, write_smf
from emu.snd import disk, sine441, snd, stereo1


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-numeric-tests"
MODS = ROOT / "build/mods"
PHYSICAL_ROMS = ROOT / "build/roms-wavehw-composite"
GENERIC_ROMS = ROOT / "build/roms"
SND_DUMP = ROOT / "emu/lua/snddump.lua"


def taps(*items: tuple[float, str]) -> list[tuple[float, bytes]]:
    return [event for at, key in items for event in key_tap(key, at)]


def record_points(path: Path) -> list[tuple[int, int, int]]:
    """Return (start, end, length) for the sole sound at each probe time."""
    return [tuple(map(int, values)) for values in re.findall(
        r"^idx 0 .* start=(\d+) end=(\d+) len=(\d+)",
        path.read_text(), re.MULTILINE)]


def is_graphics(screen: dict) -> bool:
    return "mode=32" in screen["head"]


class WaveNumeric(unittest.TestCase):
    results: dict[str, list[dict]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if missing := base.missing_tools():
            raise unittest.SkipTest("emulator tests need: " + ", ".join(missing))
        required = [MODS / "WAVEHW.SYS", MODS / "WAVE.SYS", SND_DUMP,
                    PHYSICAL_ROMS / "mpc3000", GENERIC_ROMS / "mpc3000"]
        if missing := [str(path) for path in required if not path.exists()]:
            raise unittest.SkipTest("numeric-entry fixtures are missing: " + ", ".join(missing))

        RUNS.mkdir(parents=True, exist_ok=True)
        small = [[0] * 2000]
        definitions = {
            # name: payload, planes, start, end, keys, probe times, ROM path
            "cancel_typed": (
                MODS / "WAVEHW.SYS", sine441(), base.WAVE_START, base.WAVE_END,
                taps((80, "9"), (81, "soft4"), (83, "soft4")),
                [79.5, 80.5, 81.5, 84], PHYSICAL_ROMS),
            "sample44_idle_enter": (
                MODS / "WAVEHW.SYS", sine441(), 44099, 48000,
                taps((80, "enter"), (81, "enter")), [79.5, 80.5, 82], PHYSICAL_ROMS),
            "sample44_idle_right": (
                MODS / "WAVEHW.SYS", sine441(), 44099, 48000,
                taps((80, "enter"), (81, "right"), (82, "right"), (83, "right")),
                [79.5, 80.5, 81.5, 82.5, 84], PHYSICAL_ROMS),
            "start_clamp": (
                MODS / "WAVEHW.SYS", small, 100, 1000,
                taps((80, "9"), (81.5, "enter")), [79.5, 80.5, 82.5], PHYSICAL_ROMS),
            "end_clamp": (
                MODS / "WAVEHW.SYS", small, 100, 1000,
                taps((79, "right"), (80, "0"), (81, "right"), (82, "0"),
                     (83, "right"), (84, "0"), (85, "enter")),
                [79.5, 80.5, 82.5, 84.5, 86], PHYSICAL_ROMS),
            "navigation_bounds": (
                MODS / "WAVEHW.SYS", small, 100, 1000,
                taps((80, "enter"), (81, "left"), (82, "right"),
                     (83, "right"), (84, "right")),
                [79.5, 80.5, 81.5, 82.5, 83.5, 85], PHYSICAL_ROMS),
            "mode_exit": (
                MODS / "WAVEHW.SYS", small, 100, 1000,
                taps((80, "9"), (81, "main_screen")), [79.5, 80.5, 82.5], PHYSICAL_ROMS),
            "view_ignores_numeric": (
                MODS / "WAVEHW.SYS", stereo1(), base.STEREO_START, base.STEREO_END,
                taps((79, "right"), (79.5, "right"), (80.5, "9"),
                     (81.5, "enter"), (82.5, "soft4")),
                [79.75, 81, 82, 83.5], PHYSICAL_ROMS),
            "generic_basic": (
                MODS / "WAVE.SYS", sine441(), 0, len(sine441()[0]),
                taps((81, "0"), (82, "right"), (83, "1"), (83.5, "0"),
                     (84, "right"), (85, "4"), (85.5, "3"), (86, "enter")),
                [80, 81.5, 82.5, 84.5, 86.5], GENERIC_ROMS),
        }

        cases = {}
        for name, (payload, planes, start, end, events, times, rompath) in definitions.items():
            source = RUNS / f"{name}.SND"
            source.write_bytes(snd(name.upper()[:16], planes, start=start, end=end))
            image = disk(f"wave-numeric-{name}", [(payload, "STARTUP.SYS"), (source, "TEST.SND")])
            panel = write_smf(RUNS / f"{name}.mid", events)
            settings = dict(base.CASES["wave_view"])
            settings.update(times=times, floppy=image, panel=panel, rompath=rompath,
                            extra=["-autoboot_script", str(SND_DUMP)])
            settings["press"] = [press for press in settings["press"] if press[0] <= 77.5]
            cases[name] = settings

        def execute(item: tuple[str, dict]) -> tuple[str, list[dict]]:
            name, settings = item
            settings = dict(settings)
            return name, run(settings.pop("bios"), settings.pop("times"), RUNS / name, **settings)

        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(execute, cases.items()))

    def points(self, name: str) -> list[tuple[int, int, int]]:
        return record_points(RUNS / name / "snd_dir.log")

    def test_typed_cancel_discards_draft_and_restores_graphics(self) -> None:
        self.assertEqual(self.points("cancel_typed"),
                         [(base.WAVE_START, base.WAVE_END, len(sine441()[0]))] * 4)
        self.assertFalse(is_graphics(self.results["cancel_typed"][1]))
        self.assertTrue(is_graphics(self.results["cancel_typed"][2]))
        self.assertIn("Edit Snd:", self.results["cancel_typed"][-1]["rows"][0])

    def test_idle_enter_preserves_unrepresentable_sample_44(self) -> None:
        self.assertEqual(self.points("sample44_idle_enter"), [(44099, 48000, len(sine441()[0]))] * 3)
        self.assertTrue(is_graphics(self.results["sample44_idle_enter"][0]))
        self.assertFalse(is_graphics(self.results["sample44_idle_enter"][1]))
        self.assertTrue(is_graphics(self.results["sample44_idle_enter"][2]))

    def test_idle_right_navigation_preserves_unrepresentable_sample_44(self) -> None:
        self.assertEqual(self.points("sample44_idle_right"), [(44099, 48000, len(sine441()[0]))] * 5)
        self.assertTrue(is_graphics(self.results["sample44_idle_right"][0]))
        self.assertFalse(any(map(is_graphics, self.results["sample44_idle_right"][1:-1])))
        self.assertTrue(is_graphics(self.results["sample44_idle_right"][-1]))

    def test_start_is_clamped_to_end(self) -> None:
        self.assertEqual(self.points("start_clamp")[-1], (1000, 1000, 2000))
        self.assertTrue(is_graphics(self.results["start_clamp"][-1]))

    def test_end_is_clamped_to_start(self) -> None:
        self.assertEqual(self.points("end_clamp")[-1], (100, 100, 2000))
        self.assertTrue(is_graphics(self.results["end_clamp"][-1]))

    def test_navigation_is_bounded_to_selected_component_triple(self) -> None:
        self.assertEqual(self.points("navigation_bounds"), [(100, 1000, 2000)] * 6)
        self.assertFalse(is_graphics(self.results["navigation_bounds"][1]))
        self.assertTrue(is_graphics(self.results["navigation_bounds"][-1]))

    def test_mode_key_discards_draft_and_leaves_wave_page(self) -> None:
        self.assertEqual(self.points("mode_exit"), [(100, 1000, 2000)] * 3)
        self.assertIn("Play/Record", self.results["mode_exit"][-1]["rows"][0])

    def test_view_field_ignores_digits_and_enter(self) -> None:
        expected = (base.STEREO_START, base.STEREO_END, len(stereo1()[0]))
        self.assertEqual(self.points("view_ignores_numeric"), [expected] * 4)
        self.assertTrue(is_graphics(self.results["view_ignores_numeric"][1]))
        self.assertTrue(is_graphics(self.results["view_ignores_numeric"][2]))
        self.assertIn("Edit Snd:", self.results["view_ignores_numeric"][-1]["rows"][0])

    def test_generic_profile_uses_its_numeric_state_layout(self) -> None:
        self.assertEqual(self.points("generic_basic")[-1][0], 484)
        self.assertTrue(is_graphics(self.results["generic_basic"][-1]))


if __name__ == "__main__":
    unittest.main()
