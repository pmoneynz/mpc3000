"""Real panel execution of shared ZONE editing.

Run: python3 -m unittest emu.test_wave_zones -v

The payload is built from the current sources by emu.harness (capture
profile for every case, generic for the GENERIC subset, and every case on the
316 profile: WAVE316.SYS on OS 3.16, one BIOS set per load segment by default,
all four in release mode).  Every case loads a disposable SND through the
stock disk UI.  The observers only read RAM; no zone data or input fields are
injected.  Times are emulated seconds; the wave view is open from V =
profile.view (harness.VIEW = 40 on Vailixi, harness.VIEW_316 = 52 on 3.16:
3.16 boots later), and every case time is relative to it.  The zone editing
is the same cave code on every profile, so every assertion is the same.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from emu import harness as h
from emu import wave_ref
from emu.harness import VIEW as V, burst, taps, zone_rows
from emu.panel import dial
from emu.snd import sine441, snd, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-zones-tests"
WIDE = 65911

# Legacy helpers kept for suites that import them from here.
symbols = h.symbols


def observer(run_dir: Path = RUNS, map_path: Path | None = None) -> Path:
    """Legacy zone observer for an explicit map (default: the release capture map).

    New suites use harness.run_case(), which builds the payload under test.
    """
    names = ("zones_valid", "zones_current", "zones_count", "onview", "sel", "zones_bounds", "zoom")
    offsets = symbols(map_path or ROOT / "build/mods/wavehw.cave.map")
    path = run_dir / "observe.lua"
    script = (ROOT / "emu/lua/wave_zones.lua").read_text().replace(
        'dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "snddump.lua")',
        f'dofile("{ROOT / "emu/lua/snddump.lua"}")')
    path.write_text("local WAVE_ZONE_OFFSETS={" + ",".join(f"{n}={offsets[n]}" for n in names)
                    + "}\n" + script)
    return path


def four_zones(at: float = V + 1) -> list:
    """Mono: Right x3 reaches the zone count; the wheel takes it 16 -> 4."""
    return taps((at, "right"), (at + 1, "right"), (at + 2, "right")) + dial(-12, at + 3)


class WaveZones(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"shared", "resume", "repeat_batch", "wide_partition"})
    PROFILE_NAMES = h.ALL_PROFILES

    @classmethod
    def cases(cls, profile, runs):
        V = profile.view
        four = four_zones(V + 1)
        definitions = {
            "shared": (sine441(), four + taps((V + 7, "left"), (V + 8, "+"), (V + 9, "left"),
                                              (V + 10, "+"), (V + 11, "right"), (V + 12, "+")),
                       [V, V + 6, V + 8.5, V + 10.5, V + 13]),
            "count_reset": (sine441(), four + taps((V + 7, "left"), (V + 8, "left"), (V + 9, "+"),
                                                   (V + 10, "right"), (V + 11, "right"), (V + 12, "+")),
                            [V + 6, V + 9.5, V + 13]),
            # Exit to the stock page and reopen with Help.  V+10.5 is the stock
            # page (text mode): a positive control that the view really closed.
            "resume": (sine441(), four + taps((V + 7, "left"), (V + 8, "+"), (V + 9, "soft4"),
                                              (V + 12, "help")),
                       [V + 6, V + 8.5, V + 10.5, V + 13]),
            "new_session": (sine441(), four + taps((V + 7, "main_screen"), (V + 9, "program_sounds"),
                                                   (V + 10.5, "6"), (V + 12, "help")),
                            [V + 6, V + 10, V + 13]),
            "stereo_focus": (stereo1(), taps((V + 1, "right"), (V + 2, "right"), (V + 3, "+"),
                                             (V + 4, "right"), (V + 5, "+"), (V + 6, "right")),
                             [V, V + 3.5, V + 5.5, V + 7]),
            "count_limits": (sine441(), taps((V + 1, "right"), (V + 2, "right"), (V + 3, "right"),
                                             (V + 4, "+")) + dial(-20, V + 5) + dial(20, V + 9),
                             [V + 4.5, V + 7, V + 11]),
            # Wheel bursts 1 ms apart: the stock reader coalesces them, so the
            # zone code must apply the whole repeat count (and clamp) at once.
            # Nine events = one read at once + the eight-entry key queue.
            "repeat_batch": (sine441(), four + burst(9, V + 6)          # count 4 -> 13
                             + taps((V + 8, "left")) + burst(9, V + 9)   # current 1 -> 10
                             + burst(-9, V + 11)                         # current 10 -> 1
                             + burst(5, V + 13)                          # current 1 -> 6
                             + taps((V + 15, "right")) + burst(9, V + 16)  # count 13 -> 16 (clamp)
                             + burst(-9, V + 18)                         # count 16 -> 7
                             + taps((V + 20, "left")) + burst(-9, V + 21),  # current 6 -> 1 (clamp)
                             [V + 5.5, V + 7.5, V + 10.5, V + 12.5, V + 14.5, V + 17.5, V + 19.5,
                              V + 22.5]),
            "wide_partition": ([[((i * 257) & 65535) - 32768 for i in range(WIDE)]], four,
                               [V, V + 6]),
            "numeric_zone": (sine441(), four + taps((V + 7, "left"), (V + 8, "+"), (V + 9, "left"),
                                                    (V + 10, "left"), (V + 11, "0"), (V + 12, "right"),
                                                    (V + 13, "4"), (V + 13.3, "0"), (V + 13.6, "0"),
                                                    (V + 14, "right"), (V + 15, "0"), (V + 16, "enter")),
                             [V + 10.5, V + 16.5]),
            "edge_clamps": (sine441(), four + taps((V + 7, "left"), (V + 8, "+"), (V + 9, "left"))
                            + dial(100, V + 10, gap=0.1) + taps((V + 22, "left"))
                            + dial(-100, V + 23, gap=0.1), [V + 8.5, V + 21, V + 34]),
        }
        cases = {}
        for name, (planes, events, times) in definitions.items():
            src = runs / f"{name}.SND"
            src.write_bytes(snd(name.upper()[:16], planes))
            cases[name] = h.Case(events=h.wave_events(events, profile=profile), times=times,
                                 files=[(src, "TEST.SND")], env={"SNDDUMP_PCM": "0"})
        return cases

    def test_count_and_shared_edge(self):
        for prof, d, _ in self.each("shared"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                initial, four, selected, edited, neighbor = (r[t] for t in sorted(r))
                self.assertEqual(initial["bounds"], [55125 * i // 16 for i in range(17)])
                self.assertEqual(four["bounds"][:5], [55125 * i // 4 for i in range(5)])
                self.assertEqual((selected["current"], selected["count"]), (2, 4))
                expected = [0, 13781, 27562 + 229, 41343, 55125]
                self.assertEqual(edited["bounds"][:5], expected)
                self.assertEqual(neighbor["current"], 3)
                self.assertEqual(neighbor["bounds"][:5], expected)
                pixels = h.lcd_pixels(d)
                self.assertEqual(pixels[f"{V + 8.5:.3f}"], wave_ref.screen(sine441(), "TEST",
                                 wave_ref.View([0, 55125, 13781, 27562], sel=2,
                                               zone_current=2, zone_count=4, zone_focus=2)))
                self.assertEqual(pixels[f"{V + 6:.3f}"], wave_ref.screen(sine441(), "TEST",
                                 wave_ref.View([0, 55125, 0, 13781], sel=2,
                                               zone_count=4, zone_focus=3)))

    def test_count_change_resets_manual_boundaries(self):
        for prof, d, _ in self.each("count_reset"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                four, edited, reset = (zone_rows(d)[t] for t in (V + 6, V + 9.5, V + 13))
                self.assertNotEqual(four["bounds"][:5], edited["bounds"][:5])
                self.assertEqual(reset["count"], 5)
                self.assertEqual(reset["bounds"][:6], [55125 * i // 5 for i in range(6)])

    def test_exit_to_stock_and_reopen_preserves_map(self):
        for prof, d, screens in self.each("resume"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                before, after = r[V + 8.5], r[V + 13]
                self.assertEqual((before["current"], before["count"]), (2, 4))
                # Positive control: the view did close (stock text page) and
                # did reopen (graphics showing the retained zone 2 of 4).
                self.assertNotIn("mode=32", screens[2]["head"])
                self.assertIn("Edit Snd:TEST", screens[2]["rows"][0])
                self.assertIn("mode=32", screens[3]["head"])
                self.assertEqual(h.lcd_pixels(d)[f"{V + 13:.3f}"], wave_ref.screen(
                    sine441(), "TEST", wave_ref.View([0, 55125, 13781, 27562],
                                                       zone_current=2, zone_count=4)))
                self.assertEqual((after["valid"], after["current"], after["count"], after["bounds"]),
                                 (1, before["current"], before["count"], before["bounds"]))

    def test_leaving_edit_sound_invalidates_session(self):
        for prof, d, screens in self.each("new_session"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                self.assertEqual(r[V + 6]["count"], 4)
                self.assertNotIn("mode=32", screens[1]["head"])    # really left the view
                self.assertEqual((r[V + 13]["current"], r[V + 13]["count"]), (1, 16))
                self.assertEqual(r[V + 13]["bounds"], [55125 * i // 16 for i in range(17)])
                self.assertIn("mode=32", screens[2]["head"])

    def test_stereo_view_remains_separate_from_zone_selection(self):
        for prof, d, _ in self.each("stereo_focus"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                view, zone, count = r[V + 3.5], r[V + 5.5], r[V + 7]
                self.assertEqual((view["focus"], view["current"]), (1, 1))
                self.assertEqual((zone["focus"], zone["current"]), (2, 2))
                self.assertEqual(count["focus"], 3)

    def test_count_is_bounded_one_through_sixteen(self):
        for prof, d, _ in self.each("count_limits"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                top, bottom, top_again = r[V + 4.5], r[V + 7], r[V + 11]
                self.assertEqual([top["count"], bottom["count"], top_again["count"]], [16, 1, 16])
                self.assertEqual(bottom["bounds"][:2], [0, 55125])

    def test_coalesced_wheel_bursts_apply_every_zone_step(self):
        for prof, d, _ in self.each("repeat_batch"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                self.assertEqual([(r[t]["current"], r[t]["count"]) for t in sorted(r)],
                                 [(1, 4), (1, 13), (10, 13), (1, 13), (6, 13), (6, 16), (6, 7),
                                  (1, 7)])
                self.assertEqual(r[V + 19.5]["bounds"][:8], [55125 * i // 7 for i in range(8)])
                # Coalescing really happened: the stock reader handed the
                # cave counts above one, and every burst drew fewer screens
                # than it had events.
                for at, events in ((V + 6, 9), (V + 9, 9), (V + 11, 9), (V + 13, 5),
                                   (V + 16, 9), (V + 18, 9), (V + 21, 9)):
                    counts = h.repeats(d, start=at, end=at + 1)
                    self.assertEqual(sum(counts), events, (at, counts))
                    self.assertGreater(max(counts), 1, (at, counts))
                    self.assertLess(h.blits(d, at, at + 1), events, at)

    def test_division_preserves_remainder_above_16_bit_length(self):
        for prof, d, _ in self.each("wide_partition"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                self.assertEqual(r[V]["bounds"], [WIDE * i // 16 for i in range(17)])
                self.assertEqual(r[V + 6]["bounds"][:5], [WIDE * i // 4 for i in range(5)])

    def test_stock_numeric_edit_updates_the_shared_zone_boundary(self):
        for prof, d, _ in self.each("numeric_zone"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                self.assertEqual(r[V + 10.5]["bounds"][:5], [0, 13781, 27562, 41343, 55125])
                self.assertEqual(r[V + 16.5]["bounds"][:5], [0, 17640, 27562, 41343, 55125])

    def test_zone_edits_cannot_cross_neighboring_boundaries(self):
        for prof, d, _ in self.each("edge_clamps"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                self.assertEqual(r[V + 8.5]["current"], 2)
                self.assertEqual(r[V + 21]["bounds"][:5], [0, 13781, 41343, 41343, 55125])
                self.assertEqual(r[V + 34]["bounds"][:5], [0, 0, 41343, 41343, 55125])


if __name__ == "__main__":
    unittest.main()
