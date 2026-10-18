"""display316 (put-char and string writer without INT 43 round trips) in MAME, OS 3.16.

    python3 -m unittest emu.test_display316 -v

Runs emu/display_tour316.py's page tour (Play/Record and its wheel, Edit Sound and
its wheel, the wave view and back to text, Mute groups, Mixer, Disk, Disk 7, Other,
System Information, Extra Settings and its wheel, Sync, MIDI, Song, Edit, Step Edit,
Help: 36 captures) on every BIOS set of harness.bios316_sets() with
emu/lua/display_watch316.lua, and requires:

* the LCD (pixels and display RAM) at every capture equal to the build without
  display316 (emu/fixtures/display_tour316.json, recorded from the universal-layout build without display316 (SYS af2c32f4…, all four BIOS sets); originally commit 0ae678e's
  payload on the same tour).  Lazy Chop (2026-10-18) shows "Bank A" and the "Chop:>>"
  hint in the wave view: the wave_view and wave_view_wheel digests were re-recorded from
  the final Lazy Chop build (review fixes included) with display316 removed: the three
  WAVE316.args patches 17de/42b0/42d5 deleted and T_B1B1_005B taken out of
  build_wave316.HOOK_TARGETS, then `python3 -m emu.display_tour316 OUT --bios SETS
  --record F` on all four BIOS sets, and only those two digests merged (every other
  capture's digest was unchanged by that run);
* invariant I at every put-char and string-writer (0427:0065) entry: [68AF] = FFh implies LC7981 cursor
  address (MAME hd61830 m_cac) = [68AB];
* put-char and the string writer entered only on the UI task's stack (SS 73E1 relative) and INT 43 only
  there or on the 3.16 start-up stack (SS 7066, image 0x0002, before AMX runs);
* LC7981 port writes only from 0009:185F/1868 (BIOS), 1650:0F9B/0FA2 (1650:0F8D),
  03B0:010D/0119 (03B0:00FD), the cave's fast_blit and dsp_lcd (put-char and the
  string writer 0427:0065).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from emu import display_tour316 as tour
from emu import harness as h

RUNS = h.BUILD / "emu" / "display316-tests"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "display_tour316.json"
STOCK_WRITERS = {"0009:185F E2", "0009:1868 E0", "1650:0F9B E2", "1650:0FA2 E0", "03B0:010D E2", "03B0:0119 E0"}


@unittest.skipIf(h.missing_tools(), f"missing: {h.missing_tools()}")
class DisplayTour(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.runs = {k: Path(v) for k, v in tour.run(RUNS, h.bios316_sets()).items()}
        cls.profiles = {p.label: p for p in (h.payload("316", b) for b in h.bios316_sets())}

    def test_lcd_equals_the_build_without_display316(self) -> None:
        for label, run in self.runs.items():
            with self.subTest(set=label):
                want = self.fixture["digests"][label]
                got = tour.digests(run)
                self.assertEqual(sorted(got), sorted(want))
                bad = [f"{t} ({self.fixture['labels'][t]})" for t in want if got[t] != want[t]]
                self.assertEqual(bad, [], "LCD differs from the build without display316")

    def test_invariant_and_task(self) -> None:
        for label, run in self.runs.items():
            with self.subTest(set=label):
                w = tour.watch(run)
                self.assertGreater(w["n"], 2000, "put-char entries")
                self.assertEqual(w["violations"], 0, w["viol"])
                self.assertEqual(w["other_fetch"], 0)
                self.assertEqual(set(w["ss_putc"]), {"73E1"})
                self.assertGreater(w["puts_n"], 400, "string-writer entries")
                self.assertEqual(w["puts_viol"], 0, w["viol"])
                self.assertEqual(set(w["ss_puts"]), {"73E1"})
                self.assertLessEqual(set(w["ss_int43"]), {"73E1", "7066"})

    def test_lcd_writers(self) -> None:
        for label, run in self.runs.items():
            with self.subTest(set=label):
                syms = self.profiles[label].symbols()
                lcd = syms.get("dsp_lcd", syms["fast_putc"])            # P's 0009:1856 copy (MX has none)
                ranges = [(syms["fast_blit"], syms["bitrev"]), (lcd, lcd + 0x20)]
                w = tour.watch(run)
                for key in w["writers"]:
                    if key in STOCK_WRITERS:
                        continue
                    seg_off, _ = key.split()
                    seg, off = (int(x, 16) for x in seg_off.split(":"))
                    self.assertEqual(seg, h.CAVE_HOME_316, key)
                    self.assertTrue(any(lo <= off < hi for lo, hi in ranges), key)


if __name__ == "__main__":
    unittest.main()
