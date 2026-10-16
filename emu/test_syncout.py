"""PMONEY sync out to all four MIDI outputs (mods/syncout316.inc), OS 3.16.

    python3 -m unittest emu.test_syncout -v

Tempo/Sync, Soft Key 1 <Sync>: Right reaches "MIDI clock", Down "MIDI tm
code"; the dial steps OFF, OUT A..D, ALL.  A short recording runs the
sequencer (Rec + Play through the driver's inputs, STOP), and every write to
the four TE7774 transmit data registers (C0, C8, D0, D8 = OUT A..D, fork
wiring TXD0-3) is traced.

  - all: clock and time code ALL: F8 clocks and F1 quarter frames on all four
    outputs, the same count on each; start and stop on each; the real-time
    bytes (F8, FA, FB, FC) form the same sequence on every output from the
    time ALL is on screen (PMONEY inserts each byte into the four rings under
    one CLI, so no tick can queue a clock between two outputs' copies of a
    start or stop).  Before that the dial passes through OUT A..D and each
    of those outputs gets clocks of its own;
  - outa: clock OUT A, time code OFF: F8 only on OUT A, no F1 anywhere;
  - reopen: ALL is still shown after leaving the page and coming back (the
    stock byte holds OUT A plus PMONEY's reserve bit).
"""
from __future__ import annotations

import unittest
from collections import Counter

from emu import harness as h

RUNS = h.BUILD / "emu" / "syncout-tests"
PORTS = ["00C0", "00C8", "00D0", "00D8"]
RECORD = [(42.0, "Y7", "Rec", 0.3), (42.1, "Y7", "Play", 0.1)]
PAGE = h.taps((h.CANCEL_SCSI_316, "soft4"), (36.0, "tempo_sync"), (37.0, "soft1"), (38.5, "right"))


REALTIME = {"F8", "FA", "FB", "FC"}
ALL_FROM = 41.8         # 'all': clock ALL on screen (first probe time), before Rec + Play at 42.0


def realtime(path, start: float = ALL_FROM) -> dict[str, list[str]]:
    """Real-time bytes written to each transmit data register from `start`, in trace order.
    The four copies of one byte are written within ~40 us of each other; clocks
    are ~20 ms apart, so the cut falls between bytes on every output."""
    out = {p: [] for p in PORTS}
    for line in path.read_text().splitlines():
        f = line.split()
        if f[2] == "W" and f[3] in out and f[4] in REALTIME and float(f[0]) >= start:
            out[f[3]].append(f[4])
    return out


def writes(path) -> Counter:
    c = Counter()
    for line in path.read_text().splitlines():
        f = line.split()
        if f[2] == "W":
            c[(f[3], f[4])] += 1
    return c


class SyncOut(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cases = {
            "all": (PAGE + h.dial(5, 39.5) + h.taps((40.5, "down")) + h.dial(5, 41.0)
                    + h.taps((46.0, "stop")), [41.8, 47.0], RECORD),
            "outa": (PAGE + h.dial(1, 39.5) + h.taps((46.0, "stop")), [41.8, 47.0], RECORD),
            "reopen": (PAGE + h.dial(5, 39.5) + h.taps((40.5, "main_screen"), (42.0, "tempo_sync"),
                                                      (43.0, "soft1")), [40.2, 44.5], None),
        }
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            for name, case in cases.items():
                jobs[(p.label, name)] = (p, name, *case)

        def execute(key, job):
            p, name, events, times, press = job
            runs = RUNS / p.label
            runs.mkdir(parents=True, exist_ok=True)
            screens = h.run_case(p, runs, name, times=times, events=events, parts=[],
                                 trace=[int(x, 16) for x in PORTS], press=press)
            trace = runs / name / "io_trace.log"
            return screens, writes(trace), realtime(trace)

        cls.results = h.run_parallel(jobs, execute)

    def each(self, name):
        return [(label, r) for (label, case), r in self.results.items() if case == name]

    def test_all_sends_clock_and_time_code_to_every_output(self) -> None:
        for label, (screens, w, _) in self.each("all"):
            with self.subTest(set=label):
                self.assertIn("MIDI clock:ALL", screens[0]["rows"][1])
                self.assertIn("MIDI tm code:ALL", screens[0]["rows"][2])
                clocks = [w[(p, "F8")] for p in PORTS]
                frames = [w[(p, "F1")] for p in PORTS]
                self.assertGreater(min(clocks), 300, clocks)
                self.assertLessEqual(max(clocks) - min(clocks), 2, clocks)      # the trace ends mid-burst
                self.assertGreater(min(frames), 300, frames)
                self.assertLessEqual(max(frames) - min(frames), 2, frames)
                for p in PORTS:
                    self.assertGreaterEqual(w[(p, "FC")], 1, p)                 # stop
                    self.assertGreaterEqual(w[(p, "FA")] + w[(p, "FB")], 1, p)  # start / continue

    def test_all_outputs_carry_the_same_real_time_sequence(self) -> None:
        for label, (_, _, seq) in self.each("all"):
            with self.subTest(set=label):
                lengths = [len(seq[p]) for p in PORTS]
                self.assertGreater(min(lengths), 200, lengths)
                # The trace ends mid-burst (MAME exits after the last probe time):
                # the outputs may differ only by a missing tail of up to 2 bytes.
                self.assertLessEqual(max(lengths) - min(lengths), 2, lengths)
                common = min(lengths)
                for p in PORTS[1:]:
                    self.assertEqual(seq[p][:common], seq[PORTS[0]][:common], p)
                for p in PORTS:
                    order = [b for b in seq[p] if b != "F8"]
                    self.assertIn("FC", order, p)                  # the run's stop reached every output
                    self.assertIn(order[0], ("FA", "FB"), p)       # started before it stopped

    def test_out_a_only(self) -> None:
        for label, (screens, w, _) in self.each("outa"):
            with self.subTest(set=label):
                self.assertIn("MIDI clock:OUT A", screens[0]["rows"][1])
                self.assertGreater(w[("00C0", "F8")], 300)
                for p in PORTS[1:]:
                    self.assertEqual(w[(p, "F8")], 0, p)
                self.assertEqual(sum(w[(p, "F1")] for p in PORTS), 0)

    def test_all_survives_reopening_the_page(self) -> None:
        for label, (screens, _, _) in self.each("reopen"):
            with self.subTest(set=label):
                self.assertIn("MIDI clock:ALL", screens[0]["rows"][1])
                self.assertIn("Sync Out", screens[1]["rows"][0])
                self.assertIn("MIDI clock:ALL", screens[1]["rows"][1])


if __name__ == "__main__":
    unittest.main()
