"""CHOP ZONE end-to-end tests: real floppy loading, panel input, and PCM.

No test writes zone/sample/allocator RAM. Failure cases fill the real sound
directory or sample memory through the same UI paths used by a musician.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import struct
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import disk, sine441, snd, stereo1
from emu.test_wave_zones import observer, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-tests"


def do_action(exit_time: float) -> list:
    """Exit WAVE, traverse the 17 stock fields and select appended Do #10."""
    return (taps((exit_time, "soft4"))
            + taps(*[(exit_time + 2 + i * .2, "right") for i in range(16)])
            + dial(10, exit_time + 6)
            + taps((exit_time + 9, "soft4")))


def records(case: str, time: int) -> dict[int, dict]:
    data = (RUNS / case / f"records_{time}.bin").read_bytes()
    return {i: {"name": r[:16].decode().rstrip(" \0"), "volume": r[0x11],
                "tune": struct.unpack_from("b", r, 0x12)[0], "stereo": r[0x13],
                "start": struct.unpack_from("<I", r, 0x14)[0],
                "end": struct.unpack_from("<I", r, 0x18)[0],
                "length": struct.unpack_from("<I", r, 0x1C)[0],
                "wave": struct.unpack_from("<I", r, 0x20)[0]}
            for i in range(128) if (r := data[i * 36:(i + 1) * 36])[0]}


class WaveChop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if missing := base.missing_tools():
            raise unittest.SkipTest(str(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        cls.payload_hash = hashlib.sha256((ROOT / "build/mods/WAVEHW.SYS").read_bytes()).hexdigest()
        probe = observer(RUNS)
        four = taps((81, "right"), (82, "right"), (83, "right")) + dial(-12, 84)
        stereo_four = taps((81, "right"), (82, "right"), (83, "right"),
                           (84, "right")) + dial(-12, 85)
        partial = (four + taps((87, "left"), (88, "left"), (89, "left")) + dial(2, 90)
                   + taps((92, "right"), (93, "right")) + dial(3, 94)
                   + taps((95, "left")) + dial(-3, 96) + do_action(98))
        definitions = {
            "mono": (sine441(), "ZZSOURCE", four + do_action(87) + taps((102, "help")),
                     [80, 95, 101, 103], {}),
            "stereo": (stereo1(), "STEREO", stereo_four + do_action(88), [80, 96, 102], {}),
            "tiny": ([[((i * 701) & 65535) - 32768 for i in range(2048)]], "TINY",
                     do_action(87), [80, 101], {}),
            "partial": (sine441(), "PARTIAL", partial, [80, 97, 112], {}),
            "collision": (sine441(), "ZONE000", four + do_action(87) + taps((103, "soft4")),
                          [80, 101, 109], {}),
            "stale_selection": (sine441(), "ZZSOURCE", four + do_action(87)
                          + taps((102, "help"), (104, "soft4"))
                          + taps(*[(105 + i * .1, "left") for i in range(16)])
                          + taps((107, "-"))
                          + taps(*[(108 + i * .2, "right") for i in range(16)])
                          + taps((114, "soft4"), (116, "enter")), [101, 107, 115, 118], {}),
            "empty": (sine441(), "EMPTY", four + taps((87, "left"), (88, "left"),
                      (89, "0"), (90, "right"), (91, "0"), (92, "right"), (93, "0"),
                      (94, "enter")) + do_action(96), [80, 108], {}),
            "stale": (sine441(), "STALE", do_action(87)[2:], [80, 98], {"skip_wave": True}),
            "directory_full": ([[((i * 31) & 65535) - 32768 for i in range(8192)]], "ZZSOURCE",
                          do_action(87) + taps(*[(t, "soft4") for t in (99, 102, 105, 108, 111, 114, 117)]),
                          [80, 116, 119], {}),
            "memory_full": ([[i % 32767 for i in range(540000)]], "MEMORY", do_action(165),
                          [156, 178], {"late_load": True}),
        }
        cls.definitions = definitions
        cases = {}
        for name, (planes, sound_name, events, times, options) in definitions.items():
            src = RUNS / f"{name}.SND"
            # Deliberately nondefault metadata and trimmed playback bounds.
            # Equal zones must still cover full PCM, ignoring Soft st/end.
            length = len(planes[0])
            data = bytearray(snd(sound_name, planes, vol=77,
                                start=min(123, length // 4), end=length - min(321, length // 4)))
            data[2 + 0x12] = (-12) & 255
            src.write_bytes(data)
            img = disk(f"wave-chop-{name}", [(ROOT / "build/mods/WAVEHW.SYS", "STARTUP.SYS"),
                                            (src, sound_name + ".SND")])
            settings = dict(base.CASES["wave_view"])
            settings.update(times=times, floppy=img, panel=write_smf(RUNS / f"{name}.mid", events),
                            rompath=ROOT / "build/roms-wavehw-composite",
                            extra=["-autoboot_script", str(probe)])
            settings["press"] = [v for v in settings["press"] if v[0] <= (75.5 if options.get("skip_wave") else 77.5)]
            if options.get("late_load"):
                settings["press"] = [v for v in settings["press"] if v[0] <= 65.5] + [
                    (150, "Y0", "Program/Sounds", .1), (152, "Y1", "6", .1), (154, "Y6", "Help", .1)]
            cases[name] = settings

        def execute(item):
            name, kw = item
            return name, run(kw.pop("bios"), kw.pop("times"), RUNS / name, **kw)

        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(execute, cases.items()))

    def pcm(self, case: str, time: int, index: int) -> bytes:
        return (RUNS / case / f"wave_{time}_idx{index}.bin").read_bytes()

    def assert_chop(self, case: str, before: int, after: int, bounds: list[int], repeats: int = 1):
        old, new = records(case, before), records(case, after)
        self.assertEqual(len(old), 1)
        source = old[0]
        self.assertEqual(new[0], source)
        original = self.pcm(case, before, 0)
        self.assertEqual(self.pcm(case, after, 0), original)
        self.assertEqual(len(new), 1 + (len(bounds) - 1) * repeats)
        self.assertEqual(len({r["name"] for r in new.values()}), len(new))
        extents = sorted((r["wave"], r["wave"] + r["length"] * (r["stereo"] + 1))
                         for r in new.values())
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(extents, extents[1:])))
        for i in range(1, len(new)):
            z = (i - 1) % (len(bounds) - 1)
            a, b = bounds[z:z + 2]
            rec = new[i]
            self.assertEqual((rec["length"], rec["start"], rec["end"]), (b - a, 0, b - a - 1))
            self.assertEqual((rec["volume"], rec["tune"], rec["stereo"]),
                             (source["volume"], source["tune"], source["stereo"]))
            expected = b"".join(original[(plane * source["length"] + a) * 2:
                                          (plane * source["length"] + b) * 2]
                                for plane in range(source["stereo"] + 1))
            self.assertEqual(self.pcm(case, after, i), expected, f"{case} slice {i}")

    def test_mono_exact_pcm_and_source_selection(self):
        self.assert_chop("mono", 80, 101, [55125 * i // 4 for i in range(5)])
        self.assertIn("ZZSOURCE", "".join(self.results["mono"][2]["rows"]))
        zones = [json.loads(s) for s in (RUNS / "mono/zones.jsonl").read_text().splitlines()]
        self.assertEqual(zones[-1]["count"], 4)
        self.assertIn("CHOP ZONE", "".join(self.results["mono"][1]["rows"]))

    def test_stereo_planes_and_metadata(self):
        self.assert_chop("stereo", 80, 102, [33075 * i // 4 for i in range(5)])

    def test_tiny_zones_refuse_to_create_unreloadable_sounds(self):
        self.assertEqual(records("tiny", 80), records("tiny", 101))
        self.assertIn("10ms", "".join(self.results["tiny"][-1]["rows"]))

    def test_edited_outer_boundaries_are_respected(self):
        self.assert_chop("partial", 80, 112, [458, 13781, 27562, 41343, 54438])

    def test_repeated_chop_skips_existing_names(self):
        self.assert_chop("collision", 80, 109, [55125 * i // 4 for i in range(5)], repeats=2)
        self.assertEqual([r["name"] for r in records("collision", 109).values()],
                         [f"ZONE{i:03d}" for i in range(9)])

    def test_empty_zone_refuses_without_creating_sounds(self):
        self.assertEqual(records("empty", 80), records("empty", 108))
        self.assertIn("EMPTY ZONE", "".join(self.results["empty"][-1]["rows"]))

    def test_no_zone_map_refuses_without_creating_sounds(self):
        self.assertEqual(records("stale", 80), records("stale", 98))
        self.assertIn("REOPEN WAVE VIEW", "".join(self.results["stale"][-1]["rows"]))

    def test_full_directory_preflight_creates_no_partial_set(self):
        self.assertEqual(len(records("directory_full", 116)), 113)
        self.assertEqual(records("directory_full", 116), records("directory_full", 119))
        self.assertEqual(self.pcm("directory_full", 80, 0), self.pcm("directory_full", 119, 0))

    def test_stale_map_error_keeps_the_newly_selected_sound(self):
        before = records("stale_selection", 101)
        self.assertEqual(before, records("stale_selection", 118))
        # Reopening the stock page keeps the source selected even though the
        # four new alphabetically earlier names changed its sorted position.
        self.assertIn("ZZSOURCE", "".join(self.results["stale_selection"][1]["rows"]))
        self.assertIn("REOPEN WAVE VIEW", "".join(self.results["stale_selection"][2]["rows"]))
        self.assertIn("ZONE003", "".join(self.results["stale_selection"][2]["rows"]))
        self.assertIn("ZONE003", "".join(self.results["stale_selection"][3]["rows"]))

    def test_insufficient_sample_memory_creates_no_partial_set(self):
        self.assertEqual(len(records("memory_full", 156)), 1)
        self.assertEqual(records("memory_full", 156), records("memory_full", 178))
        self.assertEqual(self.pcm("memory_full", 156, 0), self.pcm("memory_full", 178, 0))


if __name__ == "__main__":
    unittest.main()
