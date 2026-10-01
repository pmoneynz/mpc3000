"""WAVE <Ply/Stp> emulator regressions against the current physical payload.

Run from the repository root:

    python3 -m unittest emu.test_wave_playback -v

The test uses the already-built ``build/mods/WAVEHW.SYS`` and existing
physical/reference composite ROM fixture.  It deliberately does not invoke a
payload builder.  Evidence comes from the exact CFC6:0CE9 entry, full 16-bit
DSP I/O writes, and writes/snapshots of the live sound record.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import struct
import time
import unittest
import wave

from emu import test_mpc3k as base, wave_ref
from emu.mpc3k import run
from emu.panel import dial, key_tap, write_smf
from emu.snd import disk, sine441, snd, stereo1


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-playback-tests"
SYS = ROOT / "build/mods/WAVEHW.SYS"
ROMS = ROOT / "build/roms-wavehw-composite"
PROBE = ROOT / "emu/lua/wave_playback.lua"

MONO_START, MONO_END = 13_781, 48_000
MONO_LEN = len(sine441()[0])
STEREO_START, STEREO_END = 5_000, 30_000
STEREO_LEN = len(stereo1()[0])


@dataclass(frozen=True)
class Event:
    kind: str
    values: dict[str, int | float | str]


def parse_events(path: Path) -> list[Event]:
    events = []
    for line in path.read_text().splitlines():
        kind, *fields = line.split()
        values: dict[str, int | float | str] = {}
        for field in fields:
            key, value = field.split("=", 1)
            if key == "t":
                values[key] = float(value)
            elif key in {"cs", "ip"}:
                values[key] = value
            elif key in {"phys", "data", "mask", "wave", "mixer", "step", "left", "right"} \
                    or (key == "start" and kind in {"KEYON", "STARTREG"}):
                values[key] = int(value, 16)
            else:
                values[key] = int(value)
        events.append(Event(kind, values))
    return events


def common_events() -> list[tuple[float, bytes]]:
    events = []
    for at, key in ((62.0, "disk"), (63.5, "7"), (65.5, "soft1"),
                    (74.0, "program_sounds"), (75.5, "6"), (77.5, "help")):
        events += key_tap(key, at)
    return events


class WavePlayback(unittest.TestCase):
    results: dict[str, list[Event]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if missing := base.missing_tools():
            raise unittest.SkipTest("emulator tests need: " + ", ".join(missing))
        if not SYS.is_file():
            raise unittest.SkipTest(f"current payload is missing: {SYS}")
        if not (ROMS / "composite.json").is_file():
            raise unittest.SkipTest(f"existing composite fixture is missing: {ROMS}")

        RUNS.mkdir(parents=True, exist_ok=True)
        mono_path = RUNS / "SINE441.SND"
        stereo_path = RUNS / "STEREO1.SND"
        end_path = RUNS / "SINEEND.SND"
        mono_path.write_bytes(snd("SINE441", sine441(), start=MONO_START, end=MONO_END))
        stereo_path.write_bytes(snd("STEREO1", stereo1(), start=STEREO_START, end=STEREO_END))
        end_path.write_bytes(snd("SINEEND", sine441(), start=MONO_START, end=MONO_LEN))

        actions: dict[str, list[tuple[float, bytes]]] = {}

        # Full Trim audition followed by the same key while active: stock D93
        # must stop all 32 channels.
        actions["full_stop"] = key_tap("soft1", 81.0) + key_tap("soft1", 81.3)

        # Fine around Trim start clips the end; selecting Trim end recentres
        # the visible window and clips the start.  Default zoom is 16, so each
        # half-window is 120 * 16 = 1,920 frames.
        actions["fine"] = (key_tap("soft3", 81.0) + key_tap("soft1", 82.0)
                           + key_tap("right", 83.0) + key_tap("soft1", 84.0))

        # Select first of 16 equal zones; add 10 wheel steps to its end
        # and 2 steps to its start,
        # then audition the selected Zone pair.  floor(55125 / 240) = 229.
        actions["zone"] = (key_tap("soft2", 81.0) + key_tap("right", 82.0)
                           + dial(10, 83.0) + key_tap("left", 84.5)
                           + dial(2, 85.5) + key_tap("soft1", 86.5))

        actions["stereo"] = key_tap("soft1", 81.0)

        # Collapse the first zone by advancing Start to its End. Ply/Stp must not
        # call the stock player or touch the sound record.
        actions["empty"] = (key_tap("soft2", 81.0) + dial(20, 81.3)
                            + key_tap("soft1", 82.5))

        # Zoom 1 exposes only 120 frames on the selected side: below the
        # scoped hook's safe two-tick floor.  Reject it, zoom back out to 16,
        # and prove a later request succeeds and clears the warning.
        actions["short_recover"] = (key_tap("soft3", 81.0)
                                    + sum((key_tap("up", t) for t in (82.0, 83.0, 84.0, 85.0)), [])
                                    + key_tap("soft1", 86.0)
                                    + sum((key_tap("down", t) for t in (87.0, 87.3, 87.6, 87.9)), [])
                                    + key_tap("soft1", 89.0))

        # Select Trim end when it equals record length.  The visible
        # intersection must end at len; no scheduler tail may be added.
        actions["fine_record_end"] = (key_tap("soft3", 81.0) + key_tap("right", 82.0)
                                      + key_tap("soft1", 83.0))

        # Exit WAVE and invoke the stock Edit Sound Ply/Stp caller.  Its
        # original 30 ms subtraction must remain active.
        actions["stock_exit"] = key_tap("soft4", 81.0) + key_tap("soft1", 82.0)

        final_time = {"full_stop": 82.0, "fine": 85.0, "zone": 87.0,
                      "stereo": 82.0, "empty": 83.0, "short_recover": 90.0,
                      "fine_record_end": 84.0, "stock_exit": 83.0}
        capture_times = {name: [80.0, end] for name, end in final_time.items()}
        capture_times["short_recover"] = [80.0, 86.5, 88.5, 90.0]
        sound = {"full_stop": mono_path, "fine": mono_path, "zone": mono_path,
                 "stereo": stereo_path, "empty": mono_path, "short_recover": mono_path,
                 "fine_record_end": end_path, "stock_exit": mono_path}

        jobs = []
        for name in actions:
            image = disk(f"wave-playback-{name}", [(SYS, "STARTUP.SYS"),
                                                    (sound[name], sound[name].name)])
            panel = write_smf(RUNS / f"{name}.mid", common_events() + actions[name])
            jobs.append((name, image, panel, capture_times[name]))

        def go(job: tuple[str, Path, Path, list[float]]) -> tuple[str, list[Event]]:
            name, image, panel, times = job
            extra = ["-autoboot_script", str(PROBE)]
            if name == "fine":
                extra += ["-wavwrite", str(RUNS / name / "audition.wav")]
            run("vailixi", times, RUNS / name, floppy=image, panel=panel,
                rompath=ROMS, extra=extra)
            # Require the final snapshot marker before parsing so an
            # incomplete trace can never be accepted as a negative result.
            log = RUNS / name / "wave_playback.log"
            marker = f"SNAP t={times[-1]:.6f}"
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if log.is_file() and marker in log.read_text():
                    break
                time.sleep(0.02)
            else:
                raise RuntimeError(f"{name}: playback probe did not flush {marker}")
            return name, parse_events(log)

        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(go, jobs))

    def events(self, case: str, kind: str) -> list[dict[str, int | float | str]]:
        return [event.values for event in self.results[case] if event.kind == kind]

    def assert_restored(self, case: str, start: int, end: int, length: int) -> None:
        snapshots = self.events(case, "SNAP")
        self.assertGreaterEqual(len(snapshots), 2)
        for snapshot in snapshots:
            self.assertEqual((snapshot["start"], snapshot["end"], snapshot["len"]),
                             (start, end, length))

    def requested_intervals(self, case: str) -> list[tuple[int, int]]:
        writes = self.events(case, "BOUNDWRITE")
        self.assertEqual(len(writes) % 8, 0, writes)
        snapshots = self.events(case, "SNAP")
        self.assertTrue(snapshots)
        original = (int(snapshots[0]["start"]), int(snapshots[0]["end"]))
        intervals = []
        for offset in range(0, len(writes), 8):
            temporary, restored = writes[offset:offset + 4], writes[offset + 4:offset + 8]
            self.assertEqual([w["phys"] for w in temporary],
                             [0x3A72F4, 0x3A72F6, 0x3A72F8, 0x3A72FA])
            self.assertEqual([w["phys"] for w in restored],
                             [0x3A72F4, 0x3A72F6, 0x3A72F8, 0x3A72FA])
            self.assertEqual([w["mask"] for w in temporary + restored], [0xFFFF] * 8)
            start = int(temporary[0]["data"]) | (int(temporary[1]["data"]) << 16)
            end = int(temporary[2]["data"]) | (int(temporary[3]["data"]) << 16)
            intervals.append((start, end))
            restored_start = int(restored[0]["data"]) | (int(restored[1]["data"]) << 16)
            restored_end = int(restored[2]["data"]) | (int(restored[3]["data"]) << 16)
            self.assertEqual((restored_start, restored_end), original)
        return intervals

    def assert_calls(self, case: str, intervals: list[tuple[int, int]]) -> int:
        self.assertEqual(self.requested_intervals(case), intervals)
        calls = self.events(case, "CE9")
        # Some MAME builds expose instruction prefetch taps and some expose
        # only data-space reads.  Bound writes immediately before D1F7 plus
        # full-word DSP starts remain the portable proof.  When CE9 fetches
        # are exposed, check the entry and its live record as well.
        self.assertIn(len(calls), (0, len(intervals)))
        self.assertEqual([(c["start"], c["end"]) for c in calls], intervals if calls else [])
        for call in calls:
            self.assertEqual((call["cs"], call["ip"], call["phys"], call["index"], call["xa"]),
                             ("CFC6", "0CE9", 0x3D0949, 0, 1))
        snapshots = self.events(case, "SNAP")
        self.assertTrue(snapshots)
        wave_base = int(snapshots[0]["wave"])
        self.assertTrue(all(int(c["wave"]) == wave_base for c in calls))
        return wave_base

    def test_full_trim_and_explicit_stop(self) -> None:
        wave_base = self.assert_calls("full_stop", [(MONO_START, MONO_END)])
        starts = self.events("full_stop", "STARTREG")
        self.assertEqual([(event["start"], event["type"]) for event in starts],
                         [(wave_base + MONO_START, 0)])
        stops = self.events("full_stop", "D21F")
        self.assertEqual([stop["ch"] for stop in stops], list(range(32)))
        self.assertLess(float(stops[-1]["t"]) - float(stops[0]["t"]), 0.002)
        self.assert_restored("full_stop", MONO_START, MONO_END, MONO_LEN)

    def test_fine_view_clips_both_sides(self) -> None:
        half_window = 120 * 16
        intervals = [(MONO_START, MONO_START + half_window),
                     (MONO_END - half_window, MONO_END)]
        wave_base = self.assert_calls("fine", intervals)
        self.assertEqual([event["start"] for event in self.events("fine", "STARTREG")],
                         [wave_base + MONO_START, wave_base + MONO_END - half_window])
        # Both 1,920-frame windows contain nonzero source material.  This
        # catches an immediate lifecycle stop that otherwise looks correct in
        # the bounds and start-address trace.
        wav_path = RUNS / "fine/audition.wav"
        with wave.open(str(wav_path)) as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                             (11, 2, 48_000))
            for start in (82.0, 84.0):
                wav.setpos(round(start * wav.getframerate()))
                raw = wav.readframes(round(0.03 * wav.getframerate()))
                samples = struct.unpack(f"<{len(raw) // 2}h", raw)
                nonzero = [sum(samples[i] != 0 for i in range(channel, len(samples), 11))
                           for channel in (1, 2)]
                self.assertTrue(all(count > 500 for count in nonzero), nonzero)
        self.assert_restored("fine", MONO_START, MONO_END, MONO_LEN)

    def test_selected_zone(self) -> None:
        step = MONO_LEN // 240
        intervals = [(2 * step, MONO_LEN // 16 + 10 * step)]
        wave_base = self.assert_calls("zone", intervals)
        self.assertEqual([event["start"] for event in self.events("zone", "STARTREG")],
                         [wave_base + 2 * step])
        self.assert_restored("zone", MONO_START, MONO_END, MONO_LEN)

    def test_stereo_starts_both_planes(self) -> None:
        wave_base = self.assert_calls("stereo", [(STEREO_START, STEREO_END)])
        starts = self.events("stereo", "STARTREG")
        self.assertEqual([event["start"] for event in starts],
                         [wave_base + STEREO_START,
                          wave_base + STEREO_LEN + STEREO_START])
        self.assertTrue(all(event["type"] == 0 for event in starts))
        stops = self.events("stereo", "D21F")
        self.assertEqual(len(stops), 2)
        self.assertEqual({event["ch"] for event in stops}, {event["ch"] for event in starts})
        self.assert_restored("stereo", STEREO_START, STEREO_END, STEREO_LEN)

    def test_empty_zone_is_rejected(self) -> None:
        for kind in ("CE9", "STARTREG", "KEYON", "BOUNDWRITE", "D213", "D21F"):
            self.assertEqual(self.events("empty", kind), [], kind)
        self.assert_restored("empty", MONO_START, MONO_END, MONO_LEN)

    def test_zoom_one_rejects_then_recovers(self) -> None:
        intervals = [(MONO_START, MONO_START + 120),
                     (MONO_START, MONO_START + 120 * 16)]
        wave_base = self.assert_calls("short_recover", intervals)
        starts = self.events("short_recover", "STARTREG")
        self.assertEqual([event["start"] for event in starts], [wave_base + MONO_START])
        self.assertGreater(float(starts[0]["t"]), 88.5)
        self.assertEqual(len(self.events("short_recover", "D21F")), 1)
        self.assert_restored("short_recover", MONO_START, MONO_END, MONO_LEN)

        blocks = (RUNS / "short_recover/lcd_pixels.txt").read_text().split("@ ")[1:]
        pixels = {block.split()[0]: block.splitlines()[1:65] for block in blocks}
        points = [MONO_START, MONO_END, 0, 0]
        self.assertEqual(pixels["86.500"],
                         wave_ref.screen(sine441(), "SINE441",
                                         wave_ref.View(points, fine=True, zoom=1,
                                                       too_short=True)))
        self.assertEqual(pixels["88.500"],
                         wave_ref.screen(sine441(), "SINE441",
                                         wave_ref.View(points, fine=True, zoom=16)))

    def test_fine_end_at_record_length(self) -> None:
        half_window = 120 * 16
        wave_base = self.assert_calls("fine_record_end",
                                      [(MONO_LEN - half_window, MONO_LEN)])
        self.assertEqual([event["start"] for event in self.events("fine_record_end", "STARTREG")],
                         [wave_base + MONO_LEN - half_window])
        self.assert_restored("fine_record_end", MONO_START, MONO_LEN, MONO_LEN)

    def test_stock_plystp_hook_scope(self) -> None:
        self.assertEqual(self.events("stock_exit", "BOUNDWRITE"), [])
        starts = self.events("stock_exit", "STARTREG")
        self.assertEqual(len(starts), 1)
        snapshots = self.events("stock_exit", "SNAP")
        self.assertEqual(starts[0]["start"], snapshots[0]["wave"] + MONO_START)
        releases = self.events("stock_exit", "D213")
        stops = self.events("stock_exit", "D21F")
        self.assertEqual((len(releases), len(stops)), (1, 1))
        elapsed = float(stops[0]["t"]) - float(starts[0]["t"])
        self.assertGreater(elapsed, 0.70)
        self.assertLess(elapsed, 0.75)
        self.assertAlmostEqual(float(stops[0]["t"]) - float(releases[0]["t"]), 0.020,
                               delta=0.002)
        self.assert_restored("stock_exit", MONO_START, MONO_END, MONO_LEN)


if __name__ == "__main__":
    unittest.main()
