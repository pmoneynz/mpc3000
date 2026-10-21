"""PMONEY Track Mute (mods/trackmute316.inc), OS 3.16.

    python3 -m unittest emu.test_trackmute316 -v

Turning the wheel on Play/Record's fourth field makes SEQ01 with track 1
"TRK01" (a track with a record: an "(unused)" track keeps no On flag across a
Song page visit, in stock 3.16 too).  SONG opens the Song page, SONG again Track
Mute; PLAY plays the sequence with the page still up; panel pad 1 mutes track
1; PAD BANK shows tracks 17-32; MAIN SCREEN shows track 1 "On:NO" on
Play/Record; SONG twice finds it still muted; <All on> unmutes it; SONG
returns to the Song page.
"""
from __future__ import annotations

import unittest

from emu import harness as h
from emu.panel import dial, pad_hit, panel_pad

RUNS = h.BUILD / "emu" / "trackmute-tests"
STEP = 2.5
PAD1 = panel_pad(1)


def tour(t0: float) -> tuple[list, list[float], list[str]]:
    steps = [("down", "d1"), ("down", "d2"), ("down", "d3"), ("right", "right"), (11, "track"),
             ("main_screen", "main0"), ("song", "song0"), ("soft1", "ins_del"), ("soft1", "insert"),
             ("main_screen", "main1"), ("song", "song"), ("song", "track_mute"), ("play", "playing"), (PAD1, "muted"),
             ("pad_bank", "bank_b"), ("pad_bank", "bank_c"), ("pad_bank", "bank_d"), ("pad_bank", "bank_a"),
             ("stop", "stopped"), ("main_screen", "main"), ("song", "song2"), ("song", "track_mute2"),
             ("soft1", "all_on"), ("song", "back_to_song"), ("main_screen", "main2")]
    ev = h.taps((t0, "soft4"))
    t = t0 + STEP
    times, labels = [], []
    for what, label in steps:
        if isinstance(what, int):
            ev += pad_hit(what, t) if label != "track" else dial(what, t, gap=0.15)
        else:
            ev += h.taps((t, what))
        times.append(round(t + STEP - 0.3, 3))
        labels.append(label)
        t += STEP
    return ev, times, labels


class TrackMute(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            jobs[p.label] = p

        def execute(label, p):
            ev, times, labels = tour(p.timeline.cancel)
            screens = h.run_case(p, RUNS, label, times=times, events=ev, parts=[])
            return {name: [r.replace(".", " ") for r in s["rows"]] for name, s in zip(labels, screens)}

        cls.results = h.run_parallel(jobs, execute)

    def test_song_twice_opens_the_page_and_song_leaves_it(self) -> None:
        for label, s in self.results.items():
            with self.subTest(set=label):
                self.assertIn("Song Mode", s["song"][0])
                self.assertIn("Song Mode", s["insert"][0])            # <Ins/Del> <Insert> refreshes the Song page
                self.assertIn("Track Mute", s["track_mute"][0])
                self.assertEqual(s["track_mute"][1], "13 -      14 -      15 -      16 -      ")
                self.assertIn("TRK01", s["main0"][4])
                self.assertTrue(s["track_mute"][4].startswith("01 TRK01  02 -"))
                self.assertEqual(s["track_mute"][5], "Seq 01  Pads mute tracks, bank A: 01-16 ")
                self.assertIn("<All on>", s["track_mute"][7])
                self.assertIn("Song Mode", s["back_to_song"][0])
                self.assertIn("Play/Record", s["main2"][0])

    def test_pads_mute_while_the_sequence_plays(self) -> None:
        for label, s in self.results.items():
            with self.subTest(set=label):
                self.assertIn("Track Mute", s["playing"][0])           # PLAY keeps the page
                self.assertEqual(s["playing"][1:5], s["track_mute"][1:5])  # nothing drawn over it
                self.assertTrue(s["muted"][4].startswith("01(muted) "))
                self.assertIn("bank B: 17-32", s["bank_b"][5])
                self.assertTrue(s["bank_b"][4].startswith("17 "))
                self.assertIn("bank D: 49-64", s["bank_d"][5])
                self.assertTrue(s["bank_a"][4].startswith("01(muted) "))
                self.assertNotIn("001.01.00", s["main"][6])              # the sequence ran

    def test_the_mute_is_the_track_on_flag_and_stays(self) -> None:
        for label, s in self.results.items():
            with self.subTest(set=label):
                self.assertIn("On:NO ", s["main"][4])                     # Play/Record track 1
                self.assertTrue(s["track_mute2"][4].startswith("01(muted) "))
                self.assertTrue(s["all_on"][4].startswith("01 TRK01 "))    # <All on>
                self.assertIn("On:YES", s["main2"][4])


if __name__ == "__main__":
    unittest.main()
