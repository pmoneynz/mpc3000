"""R3: a MIDI note-on while stopped wakes the playback task; other messages wait for the tick.

    python3 -m unittest emu.test_midi_wake316 -v

Stock 3.16's MIDI receive ISR, while the transport is stopped, wakes task 2 and
posts it a tick message after every complete channel message (2B6D:0900-0928).
PMONEY's B6/B8 port (after Vailixi) dropped that, so a stopped MIDI note waited
for the next sequencer tick.  R3 (cave `midi_msg_done`, JMPF from img 0x2BFCD,
2B6D:08FD) restores the wake for note-ons with velocity > 0 only.

One run per build (stock M3K316.SYS and the PMONEY payload, Vailixi 3.50 BIOS
set, NEC_CPU_DIV=2), MUTE.PGM loaded, transport stopped:

(a) six 16-note MIDI chords: the first voice set-up (OUT 62h at 2325:004C) of
    every chord comes no later than stock's + 0.5 ms;
(b) full-rate CC, poly aftertouch and sysex floods: no extra task-2 tick bodies
    (stock runs one per CC / aftertouch message), and busy cycles stay well under
    stock for CC and aftertouch (the B6/B8 saving) and not above it for sysex;
(c) chords while recording (Rec + Play, 2 bars at 120 BPM, before the stopped
    phase): no extra tick bodies in either build (the wake is gated on the stopped
    transport, as in stock).
"""
from __future__ import annotations

import json
import sys
import unittest

from emu import cycle_budget as cb
from emu import harness as h

REC = cb.REC                       # Rec + Play at 69 s (as emu.cycle_budget's "seq" run)
CHORDS = [76.0 + k for k in range(6)]   # 16-note MIDI chords, stopped
PADS = [83.0 + k for k in range(6)]     # 16-pad panel chords, stopped
FLOODS = (("stopped_cc", "cc", 90.0, 3.0), ("stopped_pressure", "pressure", 94.0, 3.0),
          ("stopped_sysex", "sysex", 98.0, 3.0))


def job(build: str, fx: dict, profile: h.Profile) -> dict:
    """MUTE.PGM loaded; record 2 bars of 4-note chords from MIDI In 1 (69-73 s), stop;
    then, stopped: six 16-note MIDI chords, six 16-pad chords, CC / aftertouch / sysex
    floods.  The probe logs OUT 62h (voice set-up)."""
    if build == "pmoney":
        floppy = h.wave_disk(profile, "r3-midi", [(fx["off"], "MUTE.PGM"), (fx["tone"], "TEST.SND")])
    else:
        floppy = cb.disk("r3-stock-midi", [(fx["stock"], "STARTUP.SYS"), (fx["off"], "MUTE.PGM"),
                                           (fx["tone"], "TEST.SND")])
    panel = cb.taps((cb.T0, "soft4")) + cb.load_first(53.0) + cb.taps((REC + 5.0, "stop"))
    midi = [(t, m, "m") for t, m in cb.chords(REC + 0.2, REC + 4.0)]
    for t in CHORDS:
        midi += [(t, bytes((0x90, 37 + j, 100)), "m") for j in range(16)]
        midi += [(t + 0.5, bytes((0x80, 37 + j, 0)), "m") for j in range(16)]
    for t in PADS:
        for p in range(1, 17):
            panel += cb.pad_hit(cb.panel_pad(p), t, 100, 0.3)
    windows = {"recording": (REC + 0.5, REC + 3.5), "midichord": (75.9, 82.0), "padchord": (82.9, 89.0)}
    for name, kind, at, sec in FLOODS:
        data = cb.flood(kind, sec)
        midi.append((at, data, "x"))
        windows[name] = (at + 0.1, at + 0.1 + len(data) / 3125.0)
    return {"disk": floppy, "panel": panel, "midi": midi, "press": cb.RECORD, "windows": windows, "io": [0x62],
            "screens": {75.0: ["Trk: 1-TRK01"]}}


@unittest.skipIf(h.missing_tools(), f"missing: {h.missing_tools()}")
class MidiWake(unittest.TestCase):
    runs: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        profile = h.payload("316", cb.BIOS)
        fx = cb.fixtures()
        jobs = {b: job(b, fx, profile) for b in ("stock", "pmoney")}
        h.run_parallel(jobs, lambda b, j: cb.execute(b, "r3midi", j, profile))
        cls.windows = {b: cb.windows_of(cb.run_dir(b, "r3midi")) for b in jobs}
        cls.chords = {b: cb.chord_times(cb.run_dir(b, "r3midi") / "io_trace.log", CHORDS) for b in jobs}
        cls.screens = {b: cb.screen_problems(b, "r3midi", jobs[b]) for b in jobs}
        summary = {b: {"first_ms": [round(1e3 * c[1], 3) if c[1] is not None else None for c in cls.chords[b]],
                       "voices": [c[0] for c in cls.chords[b]],
                       **{lab: {"busy_pct": round(cb.busy_pct(w), 2), "ticks": w["vec"].get(9, (0, 0))[0],
                                "tick_bodies": cb.per_call(w, cb.BASE + cb.TICK_BODY)[0],
                                "rx_byte": round(cb.per_vector(w, 0x0D)[1] or 0, 1)}
                          for lab, w in cls.windows[b].items()}} for b in jobs}
        (cb.OUT / "r3_summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1), file=sys.stderr)

    def extra(self, build: str, label: str) -> int:
        w = self.windows[build][label]
        return cb.per_call(w, cb.BASE + cb.TICK_BODY)[0] - w["vec"].get(9, (0, 0))[0]

    def test_workload(self) -> None:
        self.assertEqual(self.screens, {"stock": [], "pmoney": []})     # track 1 recorded

    def test_a_first_note_of_a_stopped_chord_at_stock_latency(self) -> None:
        for build in ("stock", "pmoney"):
            self.assertEqual([c[0] >= 16 for c in self.chords[build]], [True] * 6, f"{build}: voices per chord")
        for k, (s, p) in enumerate(zip(self.chords["stock"], self.chords["pmoney"])):
            with self.subTest(chord=k):
                self.assertLessEqual(p[1], s[1] + 0.0005, f"chord {k}: first voice {p[1] * 1e3:.2f} ms, "
                                                          f"stock {s[1] * 1e3:.2f} ms")
                # Without R3 the first voice waits for the next tick (5.2 ms period at 120 BPM).
                self.assertLess(p[1], 0.0045)

    def test_b_stopped_floods_keep_the_b6b8_saving(self) -> None:
        for label, kind, _, _ in FLOODS:
            with self.subTest(flood=kind):
                self.assertLessEqual(self.extra("pmoney", label), 2, "PMONEY: no task-2 wake per message")
                stock, pm = (cb.busy_pct(self.windows[b][label]) for b in ("stock", "pmoney"))
                if kind == "sysex":
                    self.assertLessEqual(pm, stock + 0.5)
                else:
                    self.assertGreater(self.extra("stock", label), 100, "stock wakes task 2 per message")
                    self.assertLess(pm, stock - 5.0, f"busy {pm:.2f} % vs stock {stock:.2f} %")

    def test_c_no_wake_while_recording(self) -> None:
        for build in ("stock", "pmoney"):
            with self.subTest(build=build):
                w = self.windows[build]["recording"]
                self.assertGreater(w["vec"].get(9, (0, 0))[0], 500)
                self.assertLessEqual(abs(self.extra(build, "recording")), 2)


if __name__ == "__main__":
    unittest.main()
