"""End-to-end MUTE GROUPS voice tests through stock PGM/SND loading and pads.

Run from the repository root after building BENCH06/WAVEHW:

    python3 -m unittest emu.test_mute_voice -v

The fixtures derive from a PGM saved by the native Disk UI.  Lua only
observes execution and RAM writes; it does not seed program, sound, mute, or
voice state.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
import time
import unittest

from emu import test_mpc3k as base
from emu import pgm as pgm_fixture
from emu.mpc3k import run
from emu.panel import dial, key_tap, pad_hit, panel_pad, write_smf
from emu.snd import disk, sine, snd


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/mute-voice-tests"
SYS = ROOT / "build/mods/WAVEHW.SYS"
MAP = ROOT / "build/mods/wavehw.cave.map"
ROMS = ROOT / "build/roms-wavehw-composite"
TEMPLATE = ROOT / "emu/fixtures/mute-native-blank.PGM"
LUA = ROOT / "emu/lua/mute_voice.lua"

PGM_RECORD = 0x0A82
NOTE_RECORDS = PGM_RECORD + 0x003E
NOTE_SIZE = 0x18


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


def load_actions() -> list[tuple[float, bytes]]:
    events = []
    for at, key in ((62.0, "disk"), (63.5, "7"), (65.5, "soft1"),
                    (68.5, "soft1"), (72.0, "main_screen")):
        events += key_tap(key, at)
    return events


class MuteVoice(unittest.TestCase):
    results: dict[str, list[Event]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if missing := base.missing_tools():
            raise unittest.SkipTest("emulator tests need: " + ", ".join(missing))
        required = (SYS, MAP, ROMS / "composite.json", TEMPLATE, LUA)
        if missing := [str(path) for path in required if not path.is_file()]:
            raise unittest.SkipTest("current BENCH06 artifacts are missing: " + ", ".join(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        probe = observer()

        definitions: dict[str, tuple[Path, Path, Path | None, float]] = {}
        mono = RUNS / "TEST.SND"
        # Six seconds keeps the first voice sounding through the late 78.5 s
        # live-edit and cross-program hits; a release does not end POLY voices.
        mono.write_bytes(snd("TEST", [sine(44_100 * 6)]))
        stereo = RUNS / "STEREO.SND"
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
            program = program_fixture(RUNS / f"{name}.PGM", sound,
                          enabled=enabled, groups=groups,
                          assigned_notes=assigned_notes, layers=layers,
                          note_off=note_off, cutoff=cutoff, duplicate=duplicate)
            image = disk(f"mute-voice-{name}", [(SYS, "STARTUP.SYS"),
                                                (program, "MUTE.PGM"),
                                                (sound, "TEST.SND")])
            actions = load_actions() + (panel_extra or [])
            for pad, at, hold in hits:
                actions += pad_hit(panel_pad(pad), at, hold=hold)
            panel = write_smf(RUNS / f"{name}.mid", actions)
            external = (write_smf(RUNS / f"{name}-external.mid", external_midi)
                        if external_midi is not None else None)
            definitions[name] = (image, panel, external, end)

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
            RUNS / "program_isolation.PGM", mono, enabled=True, groups={0: 1, 1: 1})
        isolation_image = disk("mute-voice-program-isolation",
                               [(SYS, "STARTUP.SYS"),
                                (isolation_program, "MUTE.PGM"), (mono, "TEST.SND")])
        isolation = load_actions()
        for at, key in ((74.0, "program_sounds"), (76.0, "4"), (78.0, "2"),
                        (80.0, "down")):
            isolation += key_tap(key, at)
        isolation += dial(1, 81.0) + key_tap("soft1", 83.0) + key_tap("main_screen", 85.0)
        isolation += pad_hit(panel_pad(1), 86.0, hold=6.0)
        for at, key in ((86.5, "program_sounds"), (88.0, "0"), (89.0, "left"),
                        (89.3, "1"), (90.0, "main_screen")):
            isolation += key_tap(key, at, hold=0.05)
        isolation += pad_hit(panel_pad(2), 91.0, hold=2.0)
        isolation_panel = write_smf(RUNS / "program_isolation.mid", isolation)
        definitions["program_isolation"] = (isolation_image, isolation_panel, None, 93.0)

        def execute(item: tuple[str, tuple[Path, Path, Path | None, float]]) -> tuple[str, list[Event]]:
            name, (image, panel, external, end) = item
            extra = ["-autoboot_script", str(probe)]
            if external is not None:
                # mpc3000.cpp registers mdin, mdin2, then panel.  MAME exposes
                # those media slots as midiin1, midiin2, and midiin3.
                extra += ["-midiin1", str(external)]
            run("vailixi", [74.0, end - 1.0, end], RUNS / name,
                floppy=image, panel=panel, rompath=ROMS,
                extra=extra)
            log = RUNS / name / "mute_voice.log"
            marker = f"SNAP t={end:.6f}"
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if log.is_file() and marker in log.read_text():
                    break
                time.sleep(0.02)
            else:
                raise RuntimeError(f"{name}: mute probe did not flush {marker}")
            return name, parse_events(log)

        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(execute, definitions.items()))

    def events(self, case: str, kind: str) -> list[dict[str, int | float | str]]:
        return [event.values for event in self.results[case] if event.kind == kind]

    def custom_stops(self, case: str) -> list[dict[str, int | float | str]]:
        return [event for event in self.events(case, "STOP") if event["caller_cs"] == "F07D"]

    def allocations(self, case: str) -> list[dict[str, int | float | str]]:
        return [event for event in self.events(case, "TAGWRITE")
                if event["table"] == "program" and event["value"] != 0
                and event["t"] >= 74.0]

    def test_disabled_tags_but_does_not_choke(self) -> None:
        self.assertEqual(len(self.events("disabled", "KEYON")), 2)
        self.assertEqual(self.custom_stops("disabled"), [])
        self.assertGreaterEqual(len(self.events("disabled", "TAGWRITE")), 4)

    def test_same_group_different_pad_chokes_exact_prior_channel(self) -> None:
        starts = self.events("same_group", "KEYON")
        stops = self.custom_stops("same_group")
        self.assertEqual(len(starts), 2)
        self.assertEqual([event["ch"] for event in stops], [starts[0]["ch"]])
        self.assertLess(stops[0]["t"], starts[1]["t"])

    def test_other_groups_and_off_are_unaffected(self) -> None:
        self.assertEqual(len(self.events("unaffected", "KEYON")), 3)
        self.assertEqual(self.custom_stops("unaffected"), [])

    def test_same_pad_keeps_stock_poly_overlap(self) -> None:
        self.assertEqual(len(self.events("same_pad", "KEYON")), 2)
        self.assertEqual(self.custom_stops("same_pad"), [])

    def test_stereo_chokes_both_planes(self) -> None:
        starts = self.allocations("stereo")
        stops = self.custom_stops("stereo")
        self.assertEqual(len(starts), 4)
        self.assertEqual({event["ch"] for event in stops},
                         {event["ch"] for event in starts[:2]})

    def test_simult_layers_are_all_choked(self) -> None:
        starts = self.events("layers", "KEYON")
        stops = self.custom_stops("layers")
        self.assertEqual(len(starts), 4)
        self.assertEqual({event["ch"] for event in stops},
                         {event["ch"] for event in starts[:3]})

    def test_note_off_remains_stock(self) -> None:
        self.assertEqual(len(self.events("note_off", "KEYON")), 1)
        self.assertEqual(self.custom_stops("note_off"), [])
        self.assertTrue(any(event["caller_cs"] == "CFB3"
                            for event in self.events("note_off", "STOP")))

    def test_cutoff_remains_stock(self) -> None:
        self.assertEqual(len(self.events("cutoff", "KEYON")), 2)
        self.assertEqual(self.custom_stops("cutoff"), [])
        self.assertTrue(any(event["caller_cs"] == "CF37"
                            for event in self.events("cutoff", "STOP")))

    def test_enable_and_group_edit_apply_to_ringing_voice(self) -> None:
        starts = self.events("live_edit", "KEYON")
        stops = self.custom_stops("live_edit")
        self.assertEqual(len(starts), 2)
        self.assertEqual([event["ch"] for event in stops], [starts[0]["ch"]])
        self.assertGreater(stops[0]["t"], 78.49)
        self.assertLess(stops[0]["t"], starts[1]["t"])

    def test_external_midi_uses_the_shared_hooks(self) -> None:
        starts = self.events("midi", "KEYON")
        stops = self.custom_stops("midi")
        self.assertEqual(len(starts), 2)
        self.assertEqual([event["ch"] for event in stops], [starts[0]["ch"]])

    def test_duplicate_note_mapping_uses_first_pad_alias(self) -> None:
        self.assertEqual(len(self.events("duplicate_alias", "KEYON")), 2)
        self.assertEqual(self.custom_stops("duplicate_alias"), [])
        pad_writes = [event["value"] for event in self.events("duplicate_alias", "TAGWRITE")
                      if event["table"] == "pad" and event["t"] >= 74.0]
        self.assertEqual(pad_writes, [0, 0])

    def test_program_tags_isolate_sounding_voices(self) -> None:
        starts = self.events("program_isolation", "KEYON")
        self.assertEqual(len(starts), 2)
        self.assertEqual(self.custom_stops("program_isolation"), [])
        self.assertFalse(any(event["ch"] == starts[0]["ch"]
                             and starts[0]["t"] < event["t"] < starts[1]["t"]
                             for event in self.events("program_isolation", "STOP")))
        programs = [event["value"] for event in self.allocations("program_isolation")]
        self.assertEqual(set(programs), {1, 2})


if __name__ == "__main__":
    unittest.main()
