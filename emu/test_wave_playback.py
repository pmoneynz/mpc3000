"""WAVE <Ply/Stp> emulator regressions.

Run from the repository root:

    python3 -m unittest emu.test_wave_playback -v

Payloads come from emu.harness, built from the current sources (capture
profile for every case, generic for the GENERIC subset, and every case on the
316 profile: WAVE316.SYS on OS 3.16, one BIOS set per load segment by default,
all four in release mode).  Evidence comes from
the stock player's own data reads of the record bounds inside CFC6:0CE9
(BOUNDREAD, CS=CFC6, IP in [0CE9,0D75)), full 16-bit DSP I/O writes, the exact
D213/D21F release/stop instructions, writes/snapshots of the live sound
record, and short WAV windows of the mixed output.  Every started channel must
stop exactly once within the selected duration plus one 10 ms scheduler tick
(notes/wave_playback.md).

On 3.16 the observer is emu/lua/wave_playback316.lua: the same instructions
at their relocated 3.16 addresses (player body T_CFC6_0CE9..T_CFC6_0D75 =
20ED:[0CEF,0D7B), record zero at SND_SEG L+539D:4814), so every assertion is
the same.  Times are relative to V = profile.view (40 s on Vailixi, 52 s on
3.16).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import unittest
import wave

from emu import harness as h, wave_ref
from emu.panel import dial, key_tap
from emu.snd import sine441, snd, stereo1


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-playback-tests"
PROBE = ROOT / "emu/lua/wave_playback.lua"
# Legacy names for modules that import them from here (release artifacts;
# this suite itself uses the payload emu.harness builds).
SYS = ROOT / "build/mods/WAVEHW.SYS"
ROMS = ROOT / "build/roms-wavehw-composite"

MONO_START, MONO_END = 13_781, 48_000
MONO_LEN = len(sine441()[0])
STEREO_START, STEREO_END = 5_000, 30_000
STEREO_LEN = len(stereo1()[0])
RATE = 44_100
TICK = 0.010                    # stock playback scheduler tick
BOUND_WORDS = [0x3A72F4, 0x3A72F6, 0x3A72F8, 0x3A72FA]
HEX_KEYS = {"phys", "data", "mask", "wave", "mixer", "step", "left", "right", "type"}


def bound_words(profile: h.Profile) -> list[int]:
    """Physical words of record zero's start/end dwords (sound segment:4814..481B)."""
    if not profile.is316:
        return BOUND_WORDS
    first = profile.runtime(h.SND_SEG_316, 0x4814).phys
    return [first + 2 * i for i in range(4)]


def player(profile: h.Profile) -> tuple[str, int, int]:
    """The stock player body CE9: CS as logged, IP range [start, end)."""
    if not profile.is316:
        return "CFC6", 0x0CE9, 0x0D75
    start, end = profile.target("T_CFC6_0CE9"), profile.target("T_CFC6_0D75")
    return f"{start.cs:04X}", start.ip, end.ip


@dataclass(frozen=True)
class Event:
    kind: str
    values: dict[str, int | float | str]


def parse_events(path: Path) -> list[Event]:
    """KIND k=v lines: t float; cs/ip/file text; HEX_KEYS and DSP starts hex."""
    events = []
    for line in path.read_text().splitlines():
        kind, *fields = line.split()
        values: dict[str, int | float | str] = {}
        for field in fields:
            key, value = field.split("=", 1)
            if key == "t":
                values[key] = float(value)
            elif key in {"cs", "ip", "file"}:
                values[key] = value
            elif key in HEX_KEYS or (key == "start" and kind in {"KEYON", "STARTREG"}):
                values[key] = int(value, 16)
            else:
                values[key] = int(value)
        events.append(Event(kind, values))
    return events


def common_events() -> list[tuple[float, bytes]]:
    """Legacy timeline (load at 65.5 s, Help at 77.5 s, view from 80 s)."""
    events = []
    for at, key in ((62.0, "disk"), (63.5, "7"), (65.5, "soft1"),
                    (74.0, "program_sounds"), (75.5, "6"), (77.5, "help")):
        events += key_tap(key, at)
    return events


class WavePlayback(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"full_stop", "empty", "fine_record_end", "stock_exit"})
    PROFILE_NAMES = h.ALL_PROFILES
    results: dict = {}

    @classmethod
    def cases(cls, profile, runs):
        V = profile.view
        mono_path = runs / "SINE441.SND"
        stereo_path = runs / "STEREO1.SND"
        end_path = runs / "SINEEND.SND"
        mono_path.write_bytes(snd("SINE441", sine441(), start=MONO_START, end=MONO_END))
        stereo_path.write_bytes(snd("STEREO1", stereo1(), start=STEREO_START, end=STEREO_END))
        end_path.write_bytes(snd("SINEEND", sine441(), start=MONO_START, end=MONO_LEN))

        actions: dict[str, list[tuple[float, bytes]]] = {}
        # Full Trim audition followed by the same key while active: stock D93
        # must stop all 32 channels.
        actions["full_stop"] = key_tap("soft1", V + 1) + key_tap("soft1", V + 1.3)
        # Fine around Trim start clips the end; selecting Trim end recentres
        # the visible window and clips the start.  Default zoom is 16, so each
        # half-window is 120 * 16 = 1,920 frames.
        actions["fine"] = (key_tap("soft3", V + 1) + key_tap("soft1", V + 2)
                           + key_tap("right", V + 3) + key_tap("soft1", V + 4))
        # Select first of 16 equal zones; add 10 wheel steps to its end and 2
        # steps to its start, then audition the Zone pair.  floor(55125/240) = 229.
        actions["zone"] = (key_tap("soft2", V + 1) + key_tap("right", V + 2)
                           + dial(10, V + 3) + key_tap("left", V + 4.5)
                           + dial(2, V + 5.5) + key_tap("soft1", V + 6.5))
        actions["stereo"] = key_tap("soft1", V + 1)
        # Collapse the first zone by advancing Start to its End: Ply/Stp must
        # not call the stock player or touch the record.  Positive control:
        # move Start back 10 steps (to 3445 - 2290) and the same key plays.
        actions["empty"] = (key_tap("soft2", V + 1) + dial(20, V + 1.3)
                            + key_tap("soft1", V + 2.5)
                            + dial(-10, V + 4) + key_tap("soft1", V + 6))
        # Zoom 1 exposes only 120 frames on the selected side: below the
        # scoped hook's two-tick floor.  Reject it, zoom back out to 16, and
        # prove a later request succeeds and clears the warning.
        actions["short_recover"] = (key_tap("soft3", V + 1)
                                    + sum((key_tap("up", V + t) for t in (2.0, 3.0, 4.0, 5.0)), [])
                                    + key_tap("soft1", V + 6)
                                    + sum((key_tap("down", V + t) for t in (7.0, 7.3, 7.6, 7.9)), [])
                                    + key_tap("soft1", V + 9))
        # Select Trim end when it equals record length.  The visible
        # intersection must end at len; no scheduler tail may be added.
        actions["fine_record_end"] = (key_tap("soft3", V + 1) + key_tap("right", V + 2)
                                      + key_tap("soft1", V + 3))
        # Exit WAVE and invoke the stock Edit Sound Ply/Stp caller.  Its
        # original 30 ms subtraction must remain active.
        actions["stock_exit"] = key_tap("soft4", V + 1) + key_tap("soft1", V + 2)

        final_time = {"full_stop": 2, "fine": 5, "zone": 7, "stereo": 2, "empty": 8,
                      "short_recover": 10, "fine_record_end": 4, "stock_exit": 3}
        capture_times = {name: [V, V + end] for name, end in final_time.items()}
        capture_times["short_recover"] = [V, V + 6.5, V + 8.5, V + 10]
        capture_times["empty"] = [V, V + 3.5, V + 8]
        sound = {"full_stop": mono_path, "fine": mono_path, "zone": mono_path,
                 "stereo": stereo_path, "empty": mono_path, "short_recover": mono_path,
                 "fine_record_end": end_path, "stock_exit": mono_path}
        cases = {}
        for name in actions:
            env = {"PLAYBACK_WATCH_FROM": str(V - 1)}
            if name == "fine":
                # 170 ms windows around each audition instead of a whole-run WAV.
                env["PLAYBACK_WAV"] = ";".join(f"{V + k - 0.02}:{V + k + 0.15}:audition{k}.wav"
                                               for k in (2, 4))
            cases[name] = h.Case(events=h.wave_events(actions[name], profile=profile),
                                 times=capture_times[name],
                                 files=[(sound[name], sound[name].name)],
                                 parts=("wave_playback",), env=env)
        return cases

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.logs = {}
        for (prof, case), _ in cls.results.items():
            log = RUNS / prof / case / "wave_playback.log"
            times = cls.cases_times(prof, case)
            # MAME has exited and the log is closed: no polling.  A missing
            # final snapshot means the probe failed, never a negative result.
            h.require_marker(log, f"SNAP t={times[-1]:.6f}")
            cls.logs[(prof, case)] = parse_events(log)

    @classmethod
    def cases_times(cls, prof: str, case: str) -> list[float]:
        return [s["time"] for s in cls.results[(prof, case)]]

    # ------------------------------------------------------------------

    def runs(self, case: str) -> list[tuple[str, list[Event]]]:
        found = [(p, log) for (p, c), log in self.logs.items() if c == case]
        self.assertTrue(found, f"case {case} did not run")
        return found

    @staticmethod
    def kind(log: list[Event], kind: str, start: float = 0.0, end: float = float("inf")) -> list[dict]:
        return [e.values for e in log if e.kind == kind and start <= float(e.values.get("t", 0.0)) < end]

    def assert_restored(self, log, start: int, end: int, length: int) -> None:
        snapshots = self.kind(log, "SNAP")
        self.assertGreaterEqual(len(snapshots), 2)
        for snapshot in snapshots:
            self.assertEqual((snapshot["start"], snapshot["end"], snapshot["len"]),
                             (start, end, length))

    def requested_intervals(self, prof: str, log) -> list[tuple[int, int, float, float]]:
        """(start, end, t_mutate, t_restore) for each temporary record mutation."""
        words = bound_words(self.profiles[prof])
        writes = self.kind(log, "BOUNDWRITE")
        self.assertEqual(len(writes) % 8, 0, writes)
        snapshots = self.kind(log, "SNAP")
        self.assertTrue(snapshots)
        original = (int(snapshots[0]["start"]), int(snapshots[0]["end"]))
        intervals = []
        for offset in range(0, len(writes), 8):
            temporary, restored = writes[offset:offset + 4], writes[offset + 4:offset + 8]
            self.assertEqual([w["phys"] for w in temporary], words)
            self.assertEqual([w["phys"] for w in restored], words)
            self.assertEqual([w["mask"] for w in temporary + restored], [0xFFFF] * 8)
            start = int(temporary[0]["data"]) | (int(temporary[1]["data"]) << 16)
            end = int(temporary[2]["data"]) | (int(temporary[3]["data"]) << 16)
            restored_start = int(restored[0]["data"]) | (int(restored[1]["data"]) << 16)
            restored_end = int(restored[2]["data"]) | (int(restored[3]["data"]) << 16)
            self.assertEqual((restored_start, restored_end), original)
            intervals.append((start, end, float(temporary[-1]["t"]), float(restored[0]["t"])))
        return intervals

    def assert_player_read(self, prof: str, log, start: int, end: int, t0: float, t1: float) -> None:
        """CFC6:0CE9 itself read these start/end dwords in [t0, t1].

        CE9 compares the high words (signed) and reads the low end word only
        when they are equal, so with equal high words all four words must be
        read; otherwise the end's low word may be skipped.  Every read of the
        bounds in the window, by any code, must return the requested values.
        """
        profile = self.profiles[prof]
        start_lo, start_hi, end_lo, end_hi = bound_words(profile)
        cs, first, last = player(profile)
        reads = self.kind(log, "BOUNDREAD", t0, t1 + 1e-9)
        want = {start_lo: start & 0xFFFF, start_hi: start >> 16,
                end_lo: end & 0xFFFF, end_hi: end >> 16}
        for r in reads:
            self.assertEqual(int(r["data"]), want[r["phys"]], r)
        player_reads = {r["phys"] for r in reads
                        if r["cs"] == cs and first <= int(r["ip"], 16) < last}
        required = set(want) if start >> 16 == end >> 16 else set(want) - {end_lo}
        self.assertTrue(required <= player_reads, f"CE9 read {sorted(player_reads)} in [{t0}, {t1}]")

    def assert_calls(self, prof: str, log, intervals: list[tuple[int, int]]) -> int:
        requested = self.requested_intervals(prof, log)
        self.assertEqual([(a, b) for a, b, _, _ in requested], intervals)
        for a, b, t0, t1 in requested:
            self.assert_player_read(prof, log, a, b, t0, t1)
        # Every stock-player read belongs to one of the temporary mutations.
        cs = player(self.profiles[prof])[0]
        reads = [r for r in self.kind(log, "BOUNDREAD") if r["cs"] == cs]
        self.assertTrue(all(any(t0 <= float(r["t"]) <= t1 for _, _, t0, t1 in requested)
                            for r in reads), reads)
        snapshots = self.kind(log, "SNAP")
        self.assertTrue(snapshots)
        return int(snapshots[0]["wave"])

    def assert_lifecycles(self, log, frames: list[int]) -> None:
        """Each started channel: exactly one D21F stop, 0 < dt <= frames/44100 + one tick."""
        starts = self.kind(log, "STARTREG")
        self.assertEqual(len(starts), len(frames), starts)
        for start, n in zip(starts, frames):
            later = [s["t"] for s in starts if s["ch"] == start["ch"] and s["t"] > start["t"]]
            stops = self.kind(log, "D21F", start["t"], min(later, default=float("inf")))
            stops = [s for s in stops if s["ch"] == start["ch"]]
            self.assertEqual(len(stops), 1, (start, stops))
            dt = float(stops[0]["t"]) - float(start["t"])
            self.assertGreater(dt, 0.0)
            self.assertLessEqual(dt, n / RATE + TICK, (start, stops[0], n))

    # ------------------------------------------------------------------

    def test_full_trim_and_explicit_stop(self) -> None:
        for prof, log in self.runs("full_stop"):
            with self.subTest(profile=prof):
                wave_base = self.assert_calls(prof, log, [(MONO_START, MONO_END)])
                starts = self.kind(log, "STARTREG")
                self.assertEqual([(e["start"], e["type"]) for e in starts],
                                 [(wave_base + MONO_START, 0)])
                stops = self.kind(log, "D21F")
                self.assertEqual([stop["ch"] for stop in stops], list(range(32)))
                self.assertLess(float(stops[-1]["t"]) - float(stops[0]["t"]), 0.002)
                # The explicit second press (0.3 s later) stops it early.
                self.assert_lifecycles(log, [MONO_END - MONO_START])
                self.assertLess(float(stops[0]["t"]) - float(starts[0]["t"]), 0.35)
                self.assert_restored(log, MONO_START, MONO_END, MONO_LEN)

    def test_fine_view_clips_both_sides(self) -> None:
        half_window = 120 * 16
        for prof, log in self.runs("fine"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                intervals = [(MONO_START, MONO_START + half_window),
                             (MONO_END - half_window, MONO_END)]
                wave_base = self.assert_calls(prof, log, intervals)
                self.assertEqual([e["start"] for e in self.kind(log, "STARTREG")],
                                 [wave_base + MONO_START, wave_base + MONO_END - half_window])
                self.assert_lifecycles(log, [half_window, half_window])
                # Both 1,920-frame windows contain nonzero source material.
                # This catches an immediate lifecycle stop that otherwise looks
                # correct in the bounds and start-address trace.
                windows = {e["file"]: e for e in self.kind(log, "WAVSTART")}
                self.assertEqual(len(windows), 2)
                for k in (2, 4):
                    began = windows[f"audition{k}.wav"]
                    self.assertEqual(began["ok"], 1)
                    with wave.open(str(RUNS / prof / "fine" / f"audition{k}.wav")) as wav:
                        self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                                         (11, 2, 48_000))
                        key = V + k
                        self.assertLess(float(began["t"]), key)
                        wav.setpos(round((key - float(began["t"])) * wav.getframerate()))
                        raw = wav.readframes(round(0.03 * wav.getframerate()))
                    samples = struct.unpack(f"<{len(raw) // 2}h", raw)
                    nonzero = [sum(samples[i] != 0 for i in range(channel, len(samples), 11))
                               for channel in (1, 2)]
                    self.assertTrue(all(count > 500 for count in nonzero), nonzero)
                self.assert_restored(log, MONO_START, MONO_END, MONO_LEN)

    def test_selected_zone(self) -> None:
        step = MONO_LEN // 240
        for prof, log in self.runs("zone"):
            with self.subTest(profile=prof):
                interval = (2 * step, MONO_LEN // 16 + 10 * step)
                wave_base = self.assert_calls(prof, log, [interval])
                self.assertEqual([e["start"] for e in self.kind(log, "STARTREG")],
                                 [wave_base + 2 * step])
                self.assert_lifecycles(log, [interval[1] - interval[0]])
                self.assert_restored(log, MONO_START, MONO_END, MONO_LEN)

    def test_stereo_starts_both_planes(self) -> None:
        for prof, log in self.runs("stereo"):
            with self.subTest(profile=prof):
                wave_base = self.assert_calls(prof, log, [(STEREO_START, STEREO_END)])
                starts = self.kind(log, "STARTREG")
                self.assertEqual([e["start"] for e in starts],
                                 [wave_base + STEREO_START, wave_base + STEREO_LEN + STEREO_START])
                self.assertTrue(all(e["type"] == 0 for e in starts))
                stops = self.kind(log, "D21F")
                self.assertEqual(len(stops), 2)
                self.assertEqual({e["ch"] for e in stops}, {e["ch"] for e in starts})
                self.assert_lifecycles(log, [STEREO_END - STEREO_START] * 2)
                self.assert_restored(log, STEREO_START, STEREO_END, STEREO_LEN)

    def test_empty_zone_is_rejected(self) -> None:
        zone_end = MONO_LEN // 16
        for prof, log in self.runs("empty"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                # Nothing at all happens for the empty request ...
                for kind in ("BOUNDREAD", "STARTREG", "KEYON", "BOUNDWRITE", "D213", "D21F"):
                    self.assertEqual(self.kind(log, kind, V, V + 3.5), [], kind)
                # ... while the same key, once the zone is non-empty, plays it.
                positive = (zone_end - 10 * (MONO_LEN // 240), zone_end)
                wave_base = self.assert_calls(prof, log, [positive])
                self.assertEqual([e["start"] for e in self.kind(log, "STARTREG")],
                                 [wave_base + positive[0]])
                self.assertGreater(self.kind(log, "STARTREG")[0]["t"], V + 6)
                self.assert_lifecycles(log, [positive[1] - positive[0]])
                self.assert_restored(log, MONO_START, MONO_END, MONO_LEN)

    def test_zoom_one_rejects_then_recovers(self) -> None:
        for prof, log in self.runs("short_recover"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                intervals = [(MONO_START, MONO_START + 120), (MONO_START, MONO_START + 120 * 16)]
                wave_base = self.assert_calls(prof, log, intervals)
                starts = self.kind(log, "STARTREG")
                self.assertEqual([e["start"] for e in starts], [wave_base + MONO_START])
                self.assertGreater(float(starts[0]["t"]), V + 8.5)
                self.assertEqual(len(self.kind(log, "D21F")), 1)
                self.assert_lifecycles(log, [120 * 16])
                self.assert_restored(log, MONO_START, MONO_END, MONO_LEN)
                pixels = h.lcd_pixels(RUNS / prof / "short_recover")
                points = [MONO_START, MONO_END, 0, 0]
                self.assertEqual(pixels[f"{V + 6.5:.3f}"],
                                 wave_ref.screen(sine441(), "SINE441",
                                                 wave_ref.View(points, fine=True, zoom=1,
                                                               too_short=True, bank=h.view_bank(prof))))
                self.assertEqual(pixels[f"{V + 8.5:.3f}"],
                                 wave_ref.screen(sine441(), "SINE441",
                                                 wave_ref.View(points, fine=True, zoom=16,
                                                               bank=h.view_bank(prof))))

    def test_fine_end_at_record_length(self) -> None:
        half_window = 120 * 16
        for prof, log in self.runs("fine_record_end"):
            with self.subTest(profile=prof):
                wave_base = self.assert_calls(prof, log, [(MONO_LEN - half_window, MONO_LEN)])
                self.assertEqual([e["start"] for e in self.kind(log, "STARTREG")],
                                 [wave_base + MONO_LEN - half_window])
                self.assert_lifecycles(log, [half_window])
                self.assert_restored(log, MONO_START, MONO_LEN, MONO_LEN)

    def test_stock_plystp_hook_scope(self) -> None:
        for prof, log in self.runs("stock_exit"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assertEqual(self.kind(log, "BOUNDWRITE"), [])
                starts = self.kind(log, "STARTREG")
                self.assertEqual(len(starts), 1)
                snapshots = self.kind(log, "SNAP")
                self.assertEqual(starts[0]["start"], snapshots[0]["wave"] + MONO_START)
                # The stock caller hands CE9 the record's own bounds.
                self.assert_player_read(prof, log, MONO_START, MONO_END, V, starts[0]["t"])
                releases = self.kind(log, "D213")
                stops = self.kind(log, "D21F")
                self.assertEqual((len(releases), len(stops)), (1, 1))
                elapsed = float(stops[0]["t"]) - float(starts[0]["t"])
                self.assertGreater(elapsed, 0.70)
                self.assertLess(elapsed, 0.75)
                # Release and stop both run on scheduler ticks: the stop
                # follows 2 ticks after the release, or 3 when the release
                # falls late in its tick's task order.  Which one depends on
                # the boot's timing phase, which moves with the payload layout
                # (seen on 316-v311: 30 ms; removing any one cave hook gives
                # 20 ms with the release 10 ms later).
                gap = float(stops[0]["t"]) - float(releases[0]["t"])
                self.assertIn(round(gap / TICK), (2, 3), gap)
                self.assertAlmostEqual(gap, round(gap / TICK) * TICK, delta=0.002)
                self.assert_restored(log, MONO_START, MONO_END, MONO_LEN)


if __name__ == "__main__":
    unittest.main()
