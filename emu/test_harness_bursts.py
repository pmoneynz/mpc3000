"""Coalesced wheel bursts on the wave view's point motion.

Run: python3 -m unittest emu.test_harness_bursts -v

A real wheel spin delivers data-entry frames faster than the view redraws.
The stock normalized-key reader D6E0:001B (generic file 0x56E1B) folds
consecutive identical queue keys into one key and writes their count to DGROUP
D69A (generic) / D698 (capture); WAVE's `step` multiplies its 32-bit base step
by that count and saturates the product at the sound length (mods/wave.asm).
Here bursts are sent 1 ms apart on the panel link (a 3-byte frame takes
0.96 ms at 31,250 baud), so the first event is read at once and the rest
queue up while the view redraws (about 34 ms full / 53 ms fine since the
column caches; 63 ms before).  emu/lua/repeat_watch logs the count WAVE
copied for every key (read-only).

What the assertions rely on, and why:

- Total steps = events, for bursts of at most 9: one event is consumed at
  once and the stock key queue (DGROUP 12BC generic / 12BA capture) holds 8,
  so nothing can be dropped whatever the redraw time.
- Coalescing happened (a count above 1, fewer blits than events): true as
  long as one redraw outlasts one 1 ms frame gap.
- Exact count values (the saturating 64 x 8 step, and 1 + 8 for the
  20-event overflow) additionally need the whole burst to arrive before the
  cave's second key read.  `burst_inside_first_redraw` checks that from the
  log first, so a faster redraw makes the test fail with that reason instead
  of silently testing something else.
Payloads come from emu.harness (both profiles for every case).
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from emu import harness as h
from emu.harness import VIEW as V, burst, taps
from emu.snd import sine441, snd

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/harness-bursts-tests"
START, END = 13781, 48000
LEN = len(sine441()[0])
STEP = LEN // 240                   # 229 frames per full-view wheel step
SHORT = 480                         # frames (>= the loader minimum 441): 64 x 8 > 480
QUEUE = 8
FRAME = 30 / 31250                  # one 3-byte link frame, 8N1


def points(d: Path) -> dict[float, tuple[int, int, int]]:
    text = (d / "snd_dir.log").read_text()
    out = {}
    for block in text.split("@ ")[1:]:
        t = round(float(block.split()[0]), 3)
        m = re.search(r"^idx 0 .* start=(\d+) end=(\d+) len=(\d+)", block, re.M)
        out[t] = tuple(map(int, m.groups()))
    return out


class Bursts(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"motion", "saturate", "overflow"})

    @classmethod
    def cases(cls, profile, runs):
        mono = runs / "MONO.SND"
        mono.write_bytes(snd("MONO", sine441(), start=START, end=END))
        short = runs / "SHORT.SND"
        short.write_bytes(snd("SHORT", [sine441()[0][:SHORT]], start=100, end=200))
        motion = (burst(9, V + 1) + burst(-9, V + 3)                    # Start
                  + taps((V + 5, "right")) + burst(9, V + 6)            # End, full view
                  + taps((V + 8, "soft3")) + burst(9, V + 9)            # End, Fine zoom 16
                  + burst(-5, V + 11))
        # Fine, zoom 16 -> 32 -> 64 (Down), then bursts whose step * count
        # exceeds the 480-frame length: `step` saturates at len and the move
        # clamps at the other point or the sound's ends.
        saturate = (taps((V + 1, "soft3"), (V + 2, "down"), (V + 3, "down"))
                    + burst(9, V + 4)                                   # Start -> End (200)
                    + taps((V + 6, "right")) + burst(9, V + 7)          # End -> len (480)
                    + burst(-9, V + 9)                                  # End -> Start (200)
                    + taps((V + 11, "left")) + burst(-9, V + 12))       # Start -> 0
        overflow = burst(20, V + 1)
        return {
            "motion": h.Case(events=h.wave_events(motion), files=[(mono, "MONO.SND")],
                             times=[V, V + 2, V + 4, V + 7, V + 10, V + 12],
                             parts=("repeat_watch", "wave_zones", "snddump"),
                             env={"SNDDUMP_PCM": "0"}),
            "saturate": h.Case(events=h.wave_events(saturate), files=[(short, "SHORT.SND")],
                               times=[V, V + 3.5, V + 5, V + 8, V + 10, V + 13],
                               parts=("repeat_watch", "wave_zones", "snddump"),
                               env={"SNDDUMP_PCM": "0"}),
            "overflow": h.Case(events=h.wave_events(overflow), files=[(mono, "MONO.SND")],
                               times=[V, V + 2], parts=("repeat_watch", "snddump"),
                               env={"SNDDUMP_PCM": "0"}),
        }

    def burst_inside_first_redraw(self, d: Path, at: float, events: int) -> None:
        """The cave's second key read comes after the burst's last frame has arrived."""
        reads = [v["t"] for k, v in h.parse_kv_log(d / "repeat.log", hex_keys={"mask"},
                                                    text_keys={"sym"})
                 if k == "REPEAT" and v["sym"] == "key_repeat" and at <= v["t"] < at + 1]
        last_frame = at + (events - 1) * 0.001 + FRAME
        self.assertGreaterEqual(len(reads), 2, reads)
        self.assertGreater(reads[1], last_frame,
                           f"redraw ({reads[1] - reads[0]:.4f} s) no longer outlasts the "
                           f"{events}-event burst; lengthen the burst or tighten its spacing")

    def assert_coalesced(self, d: Path, at: float, events: int) -> list[int]:
        counts = h.repeats(d, start=at, end=at + 1)
        self.assertEqual(sum(counts), events, (at, counts))
        self.assertGreater(max(counts), 1, (at, counts))
        self.assertLess(h.blits(d, at, at + 1), events, at)
        return counts

    def test_point_motion_applies_whole_repeat_count(self):
        for prof, d, _ in self.each("motion"):
            with self.subTest(profile=prof):
                p = points(d)
                self.assertEqual(p[V], (START, END, LEN))
                self.assertEqual(p[V + 2][0], START + 9 * STEP)
                self.assertEqual(p[V + 4][0], START)
                self.assertEqual(p[V + 7][1], END + 9 * STEP)
                self.assertEqual(p[V + 10][1], END + 9 * STEP + 9 * 16)
                self.assertEqual(p[V + 12][1], END + 9 * STEP + 4 * 16)
                for at, n in ((V + 1, 9), (V + 3, 9), (V + 6, 9), (V + 9, 9), (V + 11, 5)):
                    self.assert_coalesced(d, at, n)

    def test_saturated_step_clamps_exactly(self):
        for prof, d, _ in self.each("saturate"):
            with self.subTest(profile=prof):
                p = points(d)
                rows = h.zone_rows(d)
                self.assertEqual(rows[V + 3.5]["zoom"], 64)
                self.assertEqual(p[V], (100, 200, SHORT))
                self.assertEqual(p[V + 5], (200, 200, SHORT))
                self.assertEqual(p[V + 8], (200, SHORT, SHORT))
                self.assertEqual(p[V + 10], (200, 200, SHORT))
                self.assertEqual(p[V + 13], (0, 200, SHORT))
                for at in (V + 4, V + 7, V + 9, V + 12):
                    counts = self.assert_coalesced(d, at, 9)
                    # The whole burst lands in one redraw, so the second key
                    # carries count 8 and 64 * 8 > 480 frames: the
                    # saturate-at-length branch.
                    self.burst_inside_first_redraw(d, at, 9)
                    self.assertEqual(counts, [1, 8])
                    self.assertGreater(64 * max(counts), SHORT)

    def test_burst_beyond_queue_capacity(self):
        """Stock limit, not a WAVE property.

        When all 20 frames arrive while the cave is still busy with the first
        key, the stock FIFO keeps exactly its capacity and drops the rest, so
        1 + capacity steps apply.  The precondition is checked from the log.
        """
        for prof, d, _ in self.each("overflow"):
            with self.subTest(profile=prof):
                queue = [v for k, v in h.parse_kv_log(d / "repeat.log", hex_keys={"mask"},
                                                       text_keys={"sym"}) if k == "QUEUE"]
                self.assertEqual([q["capacity"] for q in queue], [QUEUE])
                self.burst_inside_first_redraw(d, V + 1, 20)
                applied = sum(h.repeats(d, start=V + 1, end=V + 2))
                self.assertEqual(applied, 1 + QUEUE)
                self.assertEqual(points(d)[V + 2][0], START + applied * STEP)


if __name__ == "__main__":
    unittest.main()
