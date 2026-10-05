"""End-to-end MUTE GROUPS voice tests through stock PGM/SND loading and pads.

Run from the repository root:

    python3 -m unittest emu.test_mute_voice -v

The payloads are built from the current sources by emu.harness (their
SHA-256 is logged): capture, and 316 (WAVE316.SYS on OS 3.16) once per BIOS
set of harness.bios316_sets(), all four in release mode.  The fixtures derive
from a PGM saved by the native Disk UI.  Lua only observes execution and RAM
writes; it does not seed program, sound, mute, or voice state.  Tag writes
are counted only when the cave itself (CS=F07D; 316: its home segment L+7E00)
writes them: the loader's copy of the cave (CS=6900; 316: the entry routine
copying it from its staging segment) also writes every tag byte at boot.

OS 3.16: the hooks, the cave and the stop primitive are the same code; only
the run-time segments the assertions name differ (Vailixi -> 3.16 relative,
runtime CS = L + seg; instruction bytes compared, emu/lua/mute_voice316.lua):
the stop D21F:0008 = 234D:0000, the note-event module CFB3 = 20DA (entry
CFB3:0008 = 20DA:000E, note-off stop call CFB3:0125 = 20DA:012B) and the
voice allocator CF37:0002 = 205E:0008 (Cutoff stop call CF37:0071 =
205E:0077).  3.16 boots later and its start-up loader takes longer over the
529 KB TEST.SND, so every time from Main Screen on is shifted by shift().
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unittest

from emu import harness as h
from emu import pgm as pgm_fixture
from emu.mpc3k import run
from emu.panel import dial, key_tap, pad_hit, panel_pad, write_smf
from emu.snd import sine, snd
from emu.test_mute_persistence import suite_profiles


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-voice-tests"
SYS = ROOT / "build/mods/WAVEHW.SYS"          # legacy default for symbols()/observer()
MAP = ROOT / "build/mods/wavehw.cave.map"
TEMPLATE = ROOT / "emu/fixtures/mute-native-blank.PGM"
LUA = ROOT / "emu/lua/mute_voice.lua"

PGM_RECORD = 0x0A82
NOTE_RECORDS = PGM_RECORD + 0x003E
NOTE_SIZE = 0x18

LOAD = 62.0             # Vailixi: Disk, once the SCSI search has timed out
MAIN = 72.0             # Main Screen after the PGM load; later times are relative to it
# OS 3.16 (MAME, one run per set): the start-up file loader loads MUTE.PGM and
# TEST.SND before the SCSI search, which is on screen from 45.5 s (v308), 46.0
# (default, v311) and 50.0 (vailixi, whose EPROM loader starts 3.16 later).
# Soft Key 4 cancels it here; the Disk keys then follow profile.timeline.
STARTUP_316 = 51.0
NOTE_EVENT_SEG_316 = 0x20DA     # CFB3: entry 20DA:000E (CALLF sites 0x311C6, 0x33B15, 0x4104E)


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
            elif key in {"table", "tags"}:
                values[key] = value
            elif key in {"cs", "ip", "caller_cs", "caller_ip", "stop_ip"}:
                values[key] = value.upper()
            elif key in {"value", "mask"}:
                values[key] = int(value, 16)
            else:
                values[key] = int(value)
        events.append(Event(kind, values))
    return events


def symbols() -> dict[str, int]:
    text = MAP.read_text()
    return {match.group(2): int(match.group(1), 16) for match in re.finditer(
        r"^\s*[0-9A-Fa-f]+\s+([0-9A-Fa-f]+)\s+(\S+)$", text, re.M)}


def observer() -> Path:
    wanted = ("mute_context_valid", "mute_context_program", "mute_context_pad",
              "mute_context_group", "mute_voice_program", "mute_voice_pad")
    found = symbols()
    missing = [name for name in wanted if name not in found]
    if missing:
        raise RuntimeError("mute observer symbols missing: " + ", ".join(missing))
    path = RUNS / "observe.lua"
    table = ",".join(f"{name}=0x{found[name]:X}" for name in wanted)
    script = LUA.read_text().replace(
        'dofile(debug.getinfo(1, "S").source:match("^@(.*/)") .. "../probe.lua")',
        f'dofile("{ROOT / "emu/probe.lua"}")')
    path.write_text(f"local MUTE_VOICE_OFFSETS={{{table}}}\n" + script)
    return path


def program_fixture(path: Path, sound: Path, *, enabled: bool, groups: dict[int, int],
        assigned_notes: tuple[int, ...] = (0x23, 0x24),
        layers: bool = False, note_off: bool = False, cutoff: bool = False,
        duplicate: bool = False) -> Path:
    group_values = [groups.get(pad, 0) for pad in range(64)]
    data = bytearray(pgm_fixture.for_sound(
        TEMPLATE.read_bytes(), sound.read_bytes(),
        pads=(note - 0x23 for note in assigned_notes), enabled=enabled,
        groups=group_values, program_name="MUTE TEST"))
    if layers:
        base_record = NOTE_RECORDS
        base_record_end = base_record + NOTE_SIZE
        data[base_record + 1] = 1       # SIMULT
        data[base_record + 3] = 0x25
        data[base_record + 5] = 0x26
        assert base_record_end <= len(data)
    if note_off:
        data[NOTE_RECORDS + 6] = 2
    if cutoff:
        data[NOTE_RECORDS + NOTE_SIZE + 7] = 0x23
    if duplicate:
        data[PGM_RECORD + 0x073E + 1] = 0x23
    path.write_bytes(data)
    return path


def load_times(profile: h.Profile | None = None) -> tuple[float, ...]:
    """Disk, 7, <Load> (MUTE.PGM, the first file), <Load it>, Main Screen."""
    if profile is None or not profile.is316:
        return LOAD, LOAD + 1.5, LOAD + 3.5, LOAD + 6.5, MAIN
    tl = profile.timeline
    disk = STARTUP_316 + tl.load_at - tl.cancel
    load = disk + tl.load_key
    return disk, disk + tl.load_seven, load, load + 3.0, load + 6.5


def shift(profile: h.Profile | None = None) -> float:
    """Added to every Vailixi time from MAIN on: 0 on Vailixi, -8.5 on 3.16."""
    return load_times(profile)[-1] - MAIN


def load_actions(profile: h.Profile | None = None) -> list[tuple[float, bytes]]:
    events = h.taps((STARTUP_316, "soft4")) if profile is not None and profile.is316 else []
    for at, key in zip(load_times(profile), ("disk", "7", "soft1", "soft1", "main_screen")):
        events += key_tap(key, at)
    return events


def segments(profile: h.Profile) -> dict[str, str]:
    """Run-time CS values the logs are compared with: the cave, the stock
    note-event module (Vailixi CFB3) and the voice allocator (CF37)."""
    if profile.is316:
        return {"cave": f"{profile.cave_segment:04X}",
                "note_event": f"{profile.runtime(NOTE_EVENT_SEG_316, 0).cs:04X}",
                "allocator": f"{profile.target('T_CF37_0002').cs:04X}"}
    return {"cave": f"{profile.cave_segment:04X}", "note_event": "CFB3", "allocator": "CF37"}


class MuteVoice(unittest.TestCase):
    results: dict[tuple[str, str], list[Event]] = {}
    profiles: dict[str, h.Profile] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if not TEMPLATE.is_file():
            h.unavailable(f"native PGM fixture is missing: {TEMPLATE}")
        jobs = {}
        cls.profiles = {}
        for profile in suite_profiles():
            cls.profiles[profile.label] = profile
            for name, job in cls.cases(profile).items():
                jobs[(profile.label, name)] = job

        def execute(key: tuple[str, str], job: tuple) -> list[Event]:
            profile, runs, probe, (image, panel, external, end) = job
            extra = ["-autoboot_script", str(probe)]
            if external is not None:
                # mpc3000.cpp registers mdin, mdin2, then panel.  MAME exposes
                # those media slots as midiin1, midiin2, and midiin3.
                extra += ["-midiin1", str(external)]
            s = shift(profile)
            run(profile.bios, [74.0 + s, end - 1.0, end], runs / key[1],
                floppy=image, panel=panel, rompath=profile.rompath,
                extra=extra)
            log = runs / key[1] / "mute_voice.log"
            # MAME has exited, so the log is complete; no polling.
            h.require_marker(log, f"SNAP t={end:.6f}")
            return parse_events(log)

        cls.results = h.run_parallel(jobs, execute, 4)

    @classmethod
    def cases(cls, profile: h.Profile) -> dict[str, tuple]:
        """Every case of one profile; Vailixi times from MAIN on are moved by shift()."""
        runs = RUNS / profile.label
        runs.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        probe = h.observer(profile, runs / "observe.lua", ["mute_voice"])
        s = shift(profile)

        def moved(events: list[tuple[float, bytes]]) -> list[tuple[float, bytes]]:
            return [(at + s, data) for at, data in events]

        definitions: dict[str, tuple[Path, Path, Path | None, float]] = {}
        mono = runs / "TEST.SND"
        # Six seconds keeps the first voice sounding through the late 78.5 s
        # live-edit and cross-program hits; a release does not end POLY voices.
        mono.write_bytes(snd("TEST", [sine(44_100 * 6)]))
        stereo = runs / "STEREO.SND"
        plane = sine(44_100 * 2)
        stereo.write_bytes(snd("TEST", [plane, list(reversed(plane))]))

        def add(name: str, *, enabled: bool, groups: dict[int, int],
                hits: list[tuple[int, float, float]], sound: Path = mono,
                assigned_notes: tuple[int, ...] = (0x23, 0x24),
                layers: bool = False, note_off: bool = False, cutoff: bool = False,
                duplicate: bool = False,
                panel_extra: list[tuple[float, bytes]] | None = None,
                external_midi: list[tuple[float, bytes]] | None = None,
                end: float = 78.0) -> None:
            program = program_fixture(runs / f"{name}.PGM", sound,
                          enabled=enabled, groups=groups,
                          assigned_notes=assigned_notes, layers=layers,
                          note_off=note_off, cutoff=cutoff, duplicate=duplicate)
            image = h.wave_disk(profile, f"mute-voice-{name}", [(program, "MUTE.PGM"),
                                                                 (sound, "TEST.SND")])
            actions = load_actions(profile) + moved(panel_extra or [])
            for pad, at, hold in hits:
                actions += pad_hit(panel_pad(pad), at + s, hold=hold)
            panel = write_smf(runs / f"{name}.mid", actions)
            external = (write_smf(runs / f"{name}-external.mid", moved(external_midi))
                        if external_midi is not None else None)
            definitions[name] = (image, panel, external, end + s)

        add("disabled", enabled=False, groups={0: 1, 1: 1},
            hits=[(1, 75.0, 3.0), (2, 75.5, 3.0)])
        add("same_group", enabled=True, groups={0: 1, 1: 1},
            hits=[(1, 75.0, 3.0), (2, 75.5, 3.0)])
        add("unaffected", enabled=True, groups={0: 1, 1: 2, 2: 0},
            assigned_notes=(0x23, 0x24, 0x25),
            hits=[(1, 75.0, 3.0), (2, 75.3, 3.0), (3, 75.6, 3.0)])
        add("same_pad", enabled=True, groups={0: 1},
            hits=[(1, 75.0, 3.0), (1, 75.5, 3.0)])
        add("stereo", enabled=True, groups={0: 1, 1: 1}, sound=stereo,
            hits=[(1, 75.0, 3.0), (2, 75.5, 3.0)])
        add("layers", enabled=True, groups={0: 1, 1: 1},
            assigned_notes=(0x23, 0x24, 0x25, 0x26), layers=True,
            hits=[(1, 75.0, 3.0), (2, 75.5, 3.0)])
        add("note_off", enabled=True, groups={0: 1}, note_off=True,
            hits=[(1, 75.0, 0.5)], end=77.0)
        add("cutoff", enabled=True, groups={0: 1, 1: 2}, cutoff=True,
            hits=[(1, 75.0, 3.0), (2, 75.5, 3.0)])

        # Status-90 note packets in the native note range exercise the
        # external-MIDI arm rather than the panel's raw-pad indices 0..15.
        midi = [(75.0, bytes((0x90, 0x23, 0x7F))),
                (75.5, bytes((0x90, 0x24, 0x7F))),
                (77.0, bytes((0x80, 0x23, 0))),
                (77.2, bytes((0x80, 0x24, 0)))]
        add("midi", enabled=True, groups={0: 1, 1: 1}, hits=[], external_midi=midi)

        add("duplicate_alias", enabled=True, groups={0: 1, 1: 2}, duplicate=True,
            hits=[(1, 75.0, 3.0), (2, 75.5, 3.0)])

        # Tag pad 1 while disabled/Off, then enable the program and assign its
        # group through the real UI before pad 2 arrives.
        live = []
        for at, key in ((75.3, "program_sounds"), (76.0, "0"),
                        (76.8, "+"), (77.1, "right"), (77.3, "right"),
                        (77.5, "1"), (77.8, "main_screen")):
            live += key_tap(key, at, hold=0.05)
        add("live_edit", enabled=False, groups={0: 0, 1: 1}, panel_extra=live,
            hits=[(1, 75.0, 4.0), (2, 78.5, 2.0)], end=80.0)

        # Load Program 1, copy it to Program 2 through the stock program menu,
        # start a voice in Program 2, select Program 1 through MUTE GROUPS, then
        # hit another pad.  Equal group numbers remain isolated by program tag.
        isolation_program = program_fixture(
            runs / "program_isolation.PGM", mono, enabled=True, groups={0: 1, 1: 1})
        isolation_image = h.wave_disk(profile, "mute-voice-program-isolation",
                                      [(isolation_program, "MUTE.PGM"), (mono, "TEST.SND")])
        isolation = []
        for at, key in ((74.0, "program_sounds"), (76.0, "4"), (78.0, "2"),
                        (80.0, "down")):
            isolation += key_tap(key, at)
        isolation += dial(1, 81.0) + key_tap("soft1", 83.0) + key_tap("main_screen", 85.0)
        isolation += pad_hit(panel_pad(1), 86.0, hold=6.0)
        for at, key in ((86.5, "program_sounds"), (88.0, "0"), (89.0, "left"),
                        (89.3, "1"), (90.0, "main_screen")):
            isolation += key_tap(key, at, hold=0.05)
        isolation += pad_hit(panel_pad(2), 91.0, hold=2.0)
        isolation_panel = write_smf(runs / "program_isolation.mid",
                                    load_actions(profile) + moved(isolation))
        definitions["program_isolation"] = (isolation_image, isolation_panel, None, 93.0 + s)
        return {name: (profile, runs, probe, spec) for name, spec in definitions.items()}

    def each(self):
        """(label, run-time segments, time shift) of every profile that ran."""
        self.assertTrue(self.profiles, "no profile ran")
        for label, profile in self.profiles.items():
            yield label, segments(profile), shift(profile)

    def events(self, label: str, case: str, kind: str) -> list[dict[str, int | float | str]]:
        self.assertIn((label, case), self.results, f"{case} did not run on {label}")
        return [event.values for event in self.results[(label, case)] if event.kind == kind]

    def custom_stops(self, label: str, case: str) -> list[dict[str, int | float | str]]:
        cave = segments(self.profiles[label])["cave"]
        return [event for event in self.events(label, case, "STOP") if event["caller_cs"] == cave]

    def firmware_tags(self, label: str, case: str) -> list[dict[str, int | float | str]]:
        """Tag writes made by the cave code itself, not the loader's copy."""
        cave = segments(self.profiles[label])["cave"]
        return [event for event in self.events(label, case, "TAGWRITE") if event["cs"] == cave]

    def allocations(self, label: str, case: str) -> list[dict[str, int | float | str]]:
        s = shift(self.profiles[label])
        return [event for event in self.firmware_tags(label, case)
                if event["table"] == "program" and event["value"] != 0
                and event["t"] >= 74.0 + s]

    def test_disabled_tags_but_does_not_choke(self) -> None:
        for p, _, s in self.each():
            with self.subTest(profile=p):
                starts = self.events(p, "disabled", "KEYON")
                self.assertEqual(len(starts), 2)
                self.assertEqual(self.custom_stops(p, "disabled"), [])
                # Each voice start tags its channel with the program (1) and its
                # zero-based pad, each written once by the cave before key-on.
                tags = [(t["table"], t["ch"], t["value"]) for t in self.firmware_tags(p, "disabled")
                        if t["t"] >= 74.0 + s]
                self.assertEqual(tags, [("program", starts[0]["ch"], 1), ("pad", starts[0]["ch"], 0),
                                        ("program", starts[1]["ch"], 1), ("pad", starts[1]["ch"], 1)])

    def test_same_group_different_pad_chokes_exact_prior_channel(self) -> None:
        for p, _, _ in self.each():
            with self.subTest(profile=p):
                starts = self.events(p, "same_group", "KEYON")
                stops = self.custom_stops(p, "same_group")
                self.assertEqual(len(starts), 2)
                self.assertEqual([event["ch"] for event in stops], [starts[0]["ch"]])
                self.assertLess(stops[0]["t"], starts[1]["t"])

    def test_other_groups_and_off_are_unaffected(self) -> None:
        for p, _, _ in self.each():
            with self.subTest(profile=p):
                self.assertEqual(len(self.events(p, "unaffected", "KEYON")), 3)
                self.assertEqual(self.custom_stops(p, "unaffected"), [])

    def test_same_pad_keeps_stock_poly_overlap(self) -> None:
        for p, _, _ in self.each():
            with self.subTest(profile=p):
                self.assertEqual(len(self.events(p, "same_pad", "KEYON")), 2)
                self.assertEqual(self.custom_stops(p, "same_pad"), [])

    def test_stereo_chokes_both_planes(self) -> None:
        for p, _, _ in self.each():
            with self.subTest(profile=p):
                starts = self.allocations(p, "stereo")
                stops = self.custom_stops(p, "stereo")
                self.assertEqual(len(starts), 4)
                self.assertEqual({event["ch"] for event in stops},
                                 {event["ch"] for event in starts[:2]})

    def test_simult_layers_are_all_choked(self) -> None:
        for p, _, _ in self.each():
            with self.subTest(profile=p):
                starts = self.events(p, "layers", "KEYON")
                stops = self.custom_stops(p, "layers")
                self.assertEqual(len(starts), 4)
                self.assertEqual({event["ch"] for event in stops},
                                 {event["ch"] for event in starts[:3]})

    def test_note_off_remains_stock(self) -> None:
        for p, seg, _ in self.each():
            with self.subTest(profile=p):
                self.assertEqual(len(self.events(p, "note_off", "KEYON")), 1)
                self.assertEqual(self.custom_stops(p, "note_off"), [])
                self.assertTrue(any(event["caller_cs"] == seg["note_event"]
                                    for event in self.events(p, "note_off", "STOP")))

    def test_cutoff_remains_stock(self) -> None:
        for p, seg, _ in self.each():
            with self.subTest(profile=p):
                self.assertEqual(len(self.events(p, "cutoff", "KEYON")), 2)
                self.assertEqual(self.custom_stops(p, "cutoff"), [])
                self.assertTrue(any(event["caller_cs"] == seg["allocator"]
                                    for event in self.events(p, "cutoff", "STOP")))

    def test_enable_and_group_edit_apply_to_ringing_voice(self) -> None:
        for p, _, s in self.each():
            with self.subTest(profile=p):
                starts = self.events(p, "live_edit", "KEYON")
                stops = self.custom_stops(p, "live_edit")
                self.assertEqual(len(starts), 2)
                self.assertEqual([event["ch"] for event in stops], [starts[0]["ch"]])
                self.assertGreater(stops[0]["t"], 78.49 + s)
                self.assertLess(stops[0]["t"], starts[1]["t"])

    def test_external_midi_uses_the_shared_hooks(self) -> None:
        # The notes arrive on MIDI In 1 (-midiin1, MAME slot mdin); the panel
        # link carries only the load keys, never a pad frame.
        for p, _, s in self.each():
            with self.subTest(profile=p):
                starts = self.events(p, "midi", "KEYON")
                stops = self.custom_stops(p, "midi")
                self.assertEqual(len(starts), 2)
                self.assertEqual([event["ch"] for event in stops], [starts[0]["ch"]])
                for start, sent in zip(starts, (75.0 + s, 75.5 + s)):
                    self.assertGreater(start["t"], sent)
                    self.assertLess(start["t"], sent + 0.02)

    def test_duplicate_note_mapping_uses_first_pad_alias(self) -> None:
        for p, _, s in self.each():
            with self.subTest(profile=p):
                self.assertEqual(len(self.events(p, "duplicate_alias", "KEYON")), 2)
                self.assertEqual(self.custom_stops(p, "duplicate_alias"), [])
                pad_writes = [event["value"] for event in self.events(p, "duplicate_alias", "TAGWRITE")
                              if event["table"] == "pad" and event["t"] >= 74.0 + s]
                self.assertEqual(pad_writes, [0, 0])

    def test_program_tags_isolate_sounding_voices(self) -> None:
        for p, _, _ in self.each():
            with self.subTest(profile=p):
                starts = self.events(p, "program_isolation", "KEYON")
                self.assertEqual(len(starts), 2)
                self.assertEqual(self.custom_stops(p, "program_isolation"), [])
                self.assertFalse(any(event["ch"] == starts[0]["ch"]
                                     and starts[0]["t"] < event["t"] < starts[1]["t"]
                                     for event in self.events(p, "program_isolation", "STOP")))
                programs = [event["value"] for event in self.allocations(p, "program_isolation")]
                self.assertEqual(set(programs), {1, 2})


if __name__ == "__main__":
    unittest.main()
