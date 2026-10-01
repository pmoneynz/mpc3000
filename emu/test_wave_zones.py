"""Real panel execution of shared ZONE editing and CHOP ZONE.

Build the capture-specific WAVEHW payload before running this suite. Every
case loads a disposable SND through the stock disk UI. The observer only
reads RAM and PCM; no zone data or input fields are injected.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import unittest

from emu import test_mpc3k as base
from emu import wave_ref
from emu.mpc3k import run
from emu.panel import dial, key_tap, write_smf
from emu.snd import disk, sine441, snd, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-zones-tests"


def taps(*items: tuple[float, str]) -> list:
    return [event for at, key in items for event in key_tap(key, at)]


def symbols(map_path: Path | None = None) -> dict[str, int]:
    return {m[3]: int(m[1], 16) for m in re.finditer(
        r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)$",
        (map_path or ROOT / "build/mods/wavehw.cave.map").read_text(), re.M)}


def observer(run_dir: Path = RUNS, map_path: Path | None = None) -> Path:
    names = ("zones_valid", "zones_current", "zones_count", "onview", "sel", "zones_bounds", "zoom")
    offsets = symbols(map_path)
    path = run_dir / "observe.lua"
    script = (ROOT / "emu/lua/wave_zones.lua").read_text().replace(
        'dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "snddump.lua")',
        f'dofile("{ROOT / "emu/lua/snddump.lua"}")')
    path.write_text("local WAVE_ZONE_OFFSETS={" + ",".join(f"{n}={offsets[n]}" for n in names)
                    + "}\n" + script)
    return path


def zone_rows(name: str) -> list[dict]:
    return [json.loads(line) for line in (RUNS / name / "zones.jsonl").read_text().splitlines()]


class WaveZones(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if missing := base.missing_tools():
            raise unittest.SkipTest(str(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        cls.payload_hash = hashlib.sha256((ROOT / "build/mods/WAVEHW.SYS").read_bytes()).hexdigest()
        probe = observer()
        # Mono navigation: Start, End, current zone, total count.
        four = taps((81, "right"), (82, "right"), (83, "right")) + dial(-12, 84)
        definitions = {
            "shared": (sine441(), four + taps((87, "left"), (88, "+"), (89, "left"),
                           (90, "+"), (91, "right"), (92, "+")),
                       [80, 86, 88.5, 90.5, 93]),
            "count_reset": (sine441(), four + taps((87, "left"), (88, "left"),
                           (89, "+"), (90, "right"), (91, "right"), (92, "+")),
                       [86, 89.5, 93]),
            "resume": (sine441(), four + taps((87, "left"), (88, "+"),
                           (89, "soft4"), (92, "help")), [86, 88.5, 93]),
            "new_session": (sine441(), four + taps((87, "main_screen"),
                           (89, "program_sounds"), (90.5, "6"), (92, "help")), [86, 93]),
            "stereo_focus": (stereo1(), taps((81, "right"), (82, "right"),
                           (83, "+"), (84, "right"), (85, "+"), (86, "right")),
                       [80, 83.5, 85.5, 87]),
            "count_limits": (sine441(), taps((81, "right"), (82, "right"), (83, "right"),
                           (84, "+")) + dial(-20, 85) + dial(20, 89), [84.5, 87, 91]),
            "repeat_batch": (sine441(), taps((81, "right"), (82, "right"), (83, "right"))
                           + dial(-5, 84, gap=.05) + taps((86, "left"))
                           + dial(5, 87, gap=.05), [85, 88]),
            "wide_partition": ([[((i * 257) & 65535) - 32768 for i in range(65911)]],
                       four, [80, 86]),
            "numeric_zone": (sine441(), four + taps((87, "left"), (88, "+"),
                           (89, "left"), (90, "left"), (91, "0"), (92, "right"),
                           (93, "4"), (93.3, "0"), (93.6, "0"), (94, "right"),
                           (95, "0"), (96, "enter")), [90.5, 96.5]),
            "edge_clamps": (sine441(), four + taps((87, "left"), (88, "+"),
                           (89, "left")) + dial(100, 90, gap=0.1)
                           + taps((102, "left")) + dial(-100, 103, gap=0.1), [88.5, 101, 114]),
        }
        cases = {}
        for name, (planes, events, times) in definitions.items():
            src = RUNS / f"{name}.SND"
            src.write_bytes(snd(name.upper()[:16], planes))
            img = disk(f"wave-zones-{name}", [(ROOT / "build/mods/WAVEHW.SYS", "STARTUP.SYS"),
                                             (src, "TEST.SND")])
            settings = dict(base.CASES["wave_view"])
            settings.update(times=times, floppy=img, panel=write_smf(RUNS / f"{name}.mid", events),
                            rompath=ROOT / "build/roms-wavehw-composite",
                            extra=["-autoboot_script", str(probe)])
            settings["press"] = [v for v in settings["press"] if v[0] <= 77.5]
            cases[name] = settings

        def execute(item):
            name, kw = item
            return name, run(kw.pop("bios"), kw.pop("times"), RUNS / name, **kw)

        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(execute, cases.items()))

    def test_count_and_shared_edge(self):
        initial, four, selected, edited, neighbor = zone_rows("shared")
        self.assertEqual(initial["bounds"], [55125 * i // 16 for i in range(17)])
        self.assertEqual(four["bounds"][:5], [55125 * i // 4 for i in range(5)])
        self.assertEqual((selected["current"], selected["count"]), (2, 4))
        expected = [0, 13781, 27562 + 229, 41343, 55125]
        self.assertEqual(edited["bounds"][:5], expected)
        self.assertEqual(neighbor["current"], 3)
        self.assertEqual(neighbor["bounds"][:5], expected)
        blocks = (RUNS / "shared/lcd_pixels.txt").read_text().split("@ ")[1:]
        pixels = {b.split()[0]: b.splitlines()[1:65] for b in blocks}
        self.assertEqual(pixels["88.500"], wave_ref.screen(sine441(), "TEST",
                         wave_ref.View([0, 55125, 13781, 27562], sel=2,
                                       zone_current=2, zone_count=4, zone_focus=2)))
        self.assertEqual(pixels["86.000"], wave_ref.screen(sine441(), "TEST",
                         wave_ref.View([0, 55125, 0, 13781], sel=2,
                                       zone_count=4, zone_focus=3)))

    def test_count_change_resets_manual_boundaries(self):
        four, edited, reset = zone_rows("count_reset")
        self.assertNotEqual(four["bounds"][:5], edited["bounds"][:5])
        self.assertEqual(reset["count"], 5)
        self.assertEqual(reset["bounds"][:6], [55125 * i // 5 for i in range(6)])

    def test_exit_to_stock_and_reopen_preserves_map(self):
        _, before, after = zone_rows("resume")
        self.assertEqual((after["current"], after["count"], after["bounds"]),
                         (before["current"], before["count"], before["bounds"]))

    def test_leaving_edit_sound_invalidates_session(self):
        before, after = zone_rows("new_session")
        self.assertEqual(before["count"], 4)
        self.assertEqual((after["current"], after["count"]), (1, 16))

    def test_stereo_view_remains_separate_from_zone_selection(self):
        _, view, zone, count = zone_rows("stereo_focus")
        self.assertEqual((view["focus"], view["current"]), (1, 1))
        self.assertEqual((zone["focus"], zone["current"]), (2, 2))
        self.assertEqual(count["focus"], 3)

    def test_count_is_bounded_one_through_sixteen(self):
        top, bottom, top_again = zone_rows("count_limits")
        self.assertEqual([top["count"], bottom["count"], top_again["count"]], [16, 1, 16])
        self.assertEqual(bottom["bounds"][:2], [0, 55125])

    def test_fast_wheel_batches_apply_every_zone_step(self):
        count, current = zone_rows("repeat_batch")
        self.assertEqual((count["current"], count["count"]), (1, 11))
        self.assertEqual((current["current"], current["count"]), (6, 11))

    def test_division_preserves_remainder_above_16_bit_length(self):
        initial, four = zone_rows("wide_partition")
        self.assertEqual(initial["bounds"], [65911 * i // 16 for i in range(17)])
        self.assertEqual(four["bounds"][:5], [65911 * i // 4 for i in range(5)])

    def test_stock_numeric_edit_updates_the_shared_zone_boundary(self):
        before, after = zone_rows("numeric_zone")
        self.assertEqual(before["bounds"][:5], [0, 13781, 27562, 41343, 55125])
        self.assertEqual(after["bounds"][:5], [0, 17640, 27562, 41343, 55125])

    def test_zone_edits_cannot_cross_neighboring_boundaries(self):
        before, end, start = zone_rows("edge_clamps")
        self.assertEqual(before["current"], 2)
        self.assertEqual(end["bounds"][:5], [0, 13781, 41343, 41343, 55125])
        self.assertEqual(start["bounds"][:5], [0, 0, 41343, 41343, 55125])


if __name__ == "__main__":
    unittest.main()
