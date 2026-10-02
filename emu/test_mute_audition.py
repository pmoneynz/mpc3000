"""MUTE GROUPS context against overlapping Edit Sound auditions.

Run from the repository root:

    python3 -m unittest emu.test_mute_audition -v

The capture payload is built from the current sources by emu.harness.

The voice allocator wrapper decides whether an allocation belongs to a pad
trigger by walking the stock BP chain to the note-on wrapper's frame.  These
cases start an audition first (stock Edit Sound Ply/Stp through CFC6:0CE9, and
the WAVE view's Ply/Stp, whose CFC6:0CE9 caller is in the F07D cave itself),
then hit two pads of one group while the audition still sounds.  The audition
allocation must resolve no trigger context (zero tag, no custom stop); the
second pad must choke exactly the first pad's channel and never the audition.

This is a single-task regression: whether a pad note-on can be made to
preempt an audition inside CFC6:0B2D with real inputs is not provoked here.
Lua only observes execution and RAM writes; it does not seed any state.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from emu import harness as h
from emu.mpc3k import run
from emu.panel import key_tap, pad_hit, panel_pad, write_smf
from emu.snd import sine, snd
from emu.test_mute_voice import (TEMPLATE, Event, load_actions, parse_events,
                                 program_fixture)


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-audition-tests"

AUDITION_AT = 79.0
PAD1_AT = 80.0
PAD2_AT = 81.0
QUIET_AT = 79.6          # after the audition allocation, before any pad hit
END = 83.0


class MuteAudition(unittest.TestCase):
    results: dict[str, list[Event]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        profile = h.payload("capture")
        if not TEMPLATE.is_file():
            h.unavailable(f"native PGM fixture is missing: {TEMPLATE}")
        RUNS.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        probe = h.observer(profile, RUNS / "observe.lua", ["mute_voice"])

        # Six seconds keeps the audition sounding through both pad hits.
        mono = RUNS / "TEST.SND"
        mono.write_bytes(snd("TEST", [sine(44_100 * 6)]))
        program = program_fixture(RUNS / "AUDITION.PGM", mono,
                                  enabled=True, groups={0: 1, 1: 1})
        pads = pad_hit(panel_pad(1), PAD1_AT, hold=1.5) + pad_hit(panel_pad(2), PAD2_AT, hold=1.5)
        edit_sound = key_tap("program_sounds", 75.0) + key_tap("6", 76.5)
        cases = {
            # Stock Edit Sound Ply/Stp: CFC6:0CE9 called from stock code.
            "stock": edit_sound + key_tap("soft1", AUDITION_AT),
            # WAVE Ply/Stp: CFC6:0CE9 called from F07D, the wrapper's own CS.
            "wave": edit_sound + key_tap("help", 77.5) + key_tap("soft1", AUDITION_AT),
        }

        def execute(item: tuple[str, list[tuple[float, bytes]]]) -> tuple[str, list[Event]]:
            name, extra_actions = item
            panel = write_smf(RUNS / f"{name}.mid", load_actions() + extra_actions + pads)
            # One image per case: MAME mounts -flop read/write.
            image = h.wave_disk(profile, f"mute-audition-{name}",
                                [(program, "MUTE.PGM"), (mono, "TEST.SND")])
            run("vailixi", [74.0, QUIET_AT, END - 1.0, END], RUNS / name,
                floppy=image, panel=panel, rompath=profile.rompath,
                extra=["-autoboot_script", str(probe)])
            log = RUNS / name / "mute_voice.log"
            # MAME has exited, so the log is complete; no polling.
            h.require_marker(log, f"SNAP t={END:.6f}")
            return name, parse_events(log)

        with ThreadPoolExecutor(max_workers=2) as pool:
            cls.results = dict(pool.map(execute, cases.items()))

    def events(self, case: str, kind: str) -> list[dict[str, int | float | str]]:
        return [event.values for event in self.results[case] if event.kind == kind]

    def check(self, case: str) -> None:
        starts = [e for e in self.events(case, "KEYON") if e["t"] >= AUDITION_AT]
        self.assertEqual(len(starts), 3, starts)
        audition, pad1, pad2 = starts
        self.assertLess(audition["t"], PAD1_AT)
        self.assertGreater(pad1["t"], PAD1_AT)
        self.assertGreater(pad2["t"], PAD2_AT)

        program_tags = [e for e in self.events(case, "TAGWRITE")
                        if e["table"] == "program" and e["t"] >= AUDITION_AT]
        # The audition's allocation clears its channel's tag; it is the first
        # tag write after the key and lands on the audition channel.
        self.assertEqual((program_tags[0]["ch"], program_tags[0]["value"], program_tags[0]["cs"]),
                         (audition["ch"], 0, "F07D"))
        self.assertLess(program_tags[0]["t"], audition["t"])
        quiet = [e for e in self.events(case, "SNAP") if abs(e["t"] - QUIET_AT) < 1e-6]
        self.assertEqual(len(quiet), 1)
        self.assertEqual((quiet[0]["valid"], quiet[0]["group"]), (0, 0))

        # Both pad allocations resolve Program 1 (tag 1) and their own pads.
        pad_tags = [(e["ch"], e["value"]) for e in program_tags
                    if e["t"] > PAD1_AT and e["value"] != 0]
        self.assertEqual(pad_tags, [(pad1["ch"], 1), (pad2["ch"], 1)])
        pads = [(e["ch"], e["value"]) for e in self.events(case, "TAGWRITE")
                if e["table"] == "pad" and e["t"] > PAD1_AT]
        self.assertIn((pad1["ch"], 0), pads)
        self.assertIn((pad2["ch"], 1), pads)

        custom = [e for e in self.events(case, "STOP") if e["caller_cs"] == "F07D"]
        self.assertEqual([e["ch"] for e in custom], [pad1["ch"]])
        self.assertGreater(custom[0]["t"], PAD2_AT)
        self.assertLess(custom[0]["t"], pad2["t"])
        self.assertNotEqual(audition["ch"], pad1["ch"])
        self.assertFalse(any(e["ch"] == audition["ch"] and AUDITION_AT < e["t"] <= END
                             for e in self.events(case, "STOP")))

    def test_stock_edit_sound_audition_is_unmapped(self) -> None:
        self.check("stock")

    def test_wave_audition_from_cave_cs_is_unmapped(self) -> None:
        self.check("wave")


if __name__ == "__main__":
    unittest.main()
