"""MUTE GROUPS context against overlapping Edit Sound auditions.

Run from the repository root:

    python3 -m unittest emu.test_mute_audition -v

The payloads are built from the current sources by emu.harness: capture, and
the 316 profile (WAVE316.SYS on OS 3.16; one BIOS set per load segment by
default, all four in release mode).

The voice allocator wrapper decides whether an allocation belongs to a pad
trigger by walking the stock BP chain to the note-on wrapper's frame.  These
cases start an audition first (stock Edit Sound Ply/Stp through CFC6:0CE9, and
the WAVE view's Ply/Stp, whose CFC6:0CE9 caller is in the cave itself),
then hit two pads of one group while the audition still sounds.  The audition
allocation must resolve no trigger context (zero tag, no custom stop); the
second pad must choke exactly the first pad's channel and never the audition.
On 3.16 CFC6:0CE9 is 20ED:0CEF (T_CFC6_0CE9) and the cave runs at its home
segment L+7E00, which takes F07D's place in the CS checks.

Times are Vailixi times moved by emu.test_mute_ui.delay(profile) (13 s on
3.16).  The Vailixi times start after its SCSI search has timed out; on 3.16
Soft Key 4 cancels the search at TIMELINE_316.cancel instead.

This is a single-task regression: whether a pad note-on can be made to
preempt an audition inside CFC6:0B2D with real inputs is not provoked here.
Lua only observes execution and RAM writes; it does not seed any state.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from emu import harness as h
from emu.panel import key_tap, pad_hit, panel_pad, write_smf
from emu.snd import sine, snd
from emu.test_mute_ui import at, delay, each_run, later
from emu.test_mute_voice import TEMPLATE, load_actions, parse_events, program_fixture


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-audition-tests"

AUDITION_AT = 79.0
PAD1_AT = 80.0
PAD2_AT = 81.0
QUIET_AT = 79.6          # after the audition allocation, before any pad hit
END = 83.0


class MuteAudition(h.EmuSuite):
    RUNS = RUNS
    PROFILE_NAMES = h.ALL_PROFILES        # no GENERIC case: capture and 316
    # PMONEY on 3.16: in the wave view the pads play zones (Lazy Chop D1,
    # mods/lazychop316.inc).  The 3.16 "wave" case plays the two program notes
    # from MIDI In 1 instead (notes are not owned, D8): the same notes, the same
    # note-on path and mute group, so every assertion is the same.

    @classmethod
    def cases(cls, profile, runs):
        if not TEMPLATE.is_file():
            h.unavailable(f"native PGM fixture is missing: {TEMPLATE}")
        # Six seconds keeps the audition sounding through both pad hits.
        mono = runs / "TEST.SND"
        mono.write_bytes(snd("TEST", [sine(44_100 * 6)]))
        program = program_fixture(runs / "AUDITION.PGM", mono,
                                  enabled=True, groups={0: 1, 1: 1})
        pads = pad_hit(panel_pad(1), PAD1_AT, hold=1.5) + pad_hit(panel_pad(2), PAD2_AT, hold=1.5)
        edit_sound = key_tap("program_sounds", 75.0) + key_tap("6", 76.5)
        definitions = {
            # Stock Edit Sound Ply/Stp: CFC6:0CE9 called from stock code.
            "stock": edit_sound + key_tap("soft1", AUDITION_AT),
            # WAVE Ply/Stp: CFC6:0CE9 called from the cave, the wrapper's own CS.
            "wave": edit_sound + key_tap("help", 77.5) + key_tap("soft1", AUDITION_AT),
        }
        cancel = h.taps((profile.timeline.cancel, "soft4")) if profile.is316 else []
        t, dt = at(profile), delay(profile)
        midi = None
        if profile.is316:
            midi = write_smf(runs / "wave-midi.mid", [(t(PAD1_AT), bytes((0x90, 0x23, 0x7F))),
                                                     (t(PAD1_AT + 1.5), bytes((0x80, 0x23, 0))),
                                                     (t(PAD2_AT), bytes((0x90, 0x24, 0x7F))),
                                                     (t(PAD2_AT + 1.5), bytes((0x80, 0x24, 0)))])
        # One image per case (harness.run_case): MAME mounts -flop read/write.
        cases = {}
        for name, actions in definitions.items():
            via_midi = profile.is316 and name == "wave"
            cases[name] = h.Case(events=cancel + later(load_actions() + actions + ([] if via_midi else pads), dt),
                                 times=[t(x) for x in (74.0, QUIET_AT, END - 1.0, END)],
                                 files=[(program, "MUTE.PGM"), (mono, "TEST.SND")], parts=("mute_voice",),
                                 kwargs={"extra": ["-midiin1", str(midi)], "snapshot": False} if via_midi else None)
        return cases

    def events(self, d: Path, kind: str) -> list[dict[str, int | float | str]]:
        return [event.values for event in parse_events(d / "mute_voice.log") if event.kind == kind]

    def check(self, case: str) -> None:
        for label, profile, d, _, t in each_run(self, case):
            with self.subTest(profile=label):
                self.check_run(d, f"{profile.cave_segment:04X}", t)    # cave CS: F07D on capture

    def check_run(self, d: Path, cave: str, t) -> None:
        # MAME has exited, so the log is complete; no polling.
        h.require_marker(d / "mute_voice.log", f"SNAP t={t(END):.6f}")
        starts = [e for e in self.events(d, "KEYON") if e["t"] >= t(AUDITION_AT)]
        self.assertEqual(len(starts), 3, starts)
        audition, pad1, pad2 = starts
        self.assertLess(audition["t"], t(PAD1_AT))
        self.assertGreater(pad1["t"], t(PAD1_AT))
        self.assertGreater(pad2["t"], t(PAD2_AT))

        program_tags = [e for e in self.events(d, "TAGWRITE")
                        if e["table"] == "program" and e["t"] >= t(AUDITION_AT)]
        # The audition's allocation clears its channel's tag; it is the first
        # tag write after the key and lands on the audition channel.
        self.assertEqual((program_tags[0]["ch"], program_tags[0]["value"], program_tags[0]["cs"]),
                         (audition["ch"], 0, cave))
        self.assertLess(program_tags[0]["t"], audition["t"])
        quiet = [e for e in self.events(d, "SNAP") if abs(e["t"] - t(QUIET_AT)) < 1e-6]
        self.assertEqual(len(quiet), 1)
        self.assertEqual((quiet[0]["valid"], quiet[0]["group"]), (0, 0))

        # Both pad allocations resolve Program 1 (tag 1) and their own pads.
        pad_tags = [(e["ch"], e["value"]) for e in program_tags
                    if e["t"] > t(PAD1_AT) and e["value"] != 0]
        self.assertEqual(pad_tags, [(pad1["ch"], 1), (pad2["ch"], 1)])
        pads = [(e["ch"], e["value"]) for e in self.events(d, "TAGWRITE")
                if e["table"] == "pad" and e["t"] > t(PAD1_AT)]
        self.assertIn((pad1["ch"], 0), pads)
        self.assertIn((pad2["ch"], 1), pads)

        custom = [e for e in self.events(d, "STOP") if e["caller_cs"] == cave]
        self.assertEqual([e["ch"] for e in custom], [pad1["ch"]])
        self.assertGreater(custom[0]["t"], t(PAD2_AT))
        self.assertLess(custom[0]["t"], pad2["t"])
        self.assertNotEqual(audition["ch"], pad1["ch"])
        self.assertFalse(any(e["ch"] == audition["ch"] and t(AUDITION_AT) < e["t"] <= t(END)
                             for e in self.events(d, "STOP")))

    def test_stock_edit_sound_audition_is_unmapped(self) -> None:
        self.check("stock")

    def test_wave_audition_from_cave_cs_is_unmapped(self) -> None:
        self.check("wave")


if __name__ == "__main__":
    unittest.main()
