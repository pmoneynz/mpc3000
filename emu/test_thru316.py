"""PMONEY Input Thru (mods/thru316.inc, notes/input_thru.md), OS 3.16.

    python3 -m unittest emu.test_thru316 -v

Mixer/Effects -> 6 opens the Input Thru page.  Every case that turns Thru on
runs in its own MAME process: the pinned L7A1045 model's DMA writes advance
channel 0's position without wrapping and DMA ch2 has no device, so a running
Thru writes on through emulated wave RAM and carries no input.  These cases
prove the control path only (owner decision 2026-10-18): the page and its
stored bytes, the DMA / 8255 / DSP writes the engine makes, the reserved
channels' exclusion from the allocator and stop paths, the pauses around wave
transfers and floppy operations, and the hand-off to Sample New Sound.  Whether
audio passes is a bench item (notes/input_thru.md, T1-T7).

Observer: emu/lua/thru316.lua (read-only).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from emu import harness as h
from emu.panel import pad_hit, panel_pad
from emu.snd import sine, sine441, snd
from emu.test_mute_voice import load_actions, program_fixture, shift

RUNS = h.BUILD / "emu" / "thru-tests"
CANCEL = 33.0
MIXER, SIX, PAGE = 34.0, 34.8, 36.0      # Mixer/Effects, 6, the page is drawn
ON = PAGE + 0.5                           # '+' on the Thru field
RING_WORDS = 0x2000                       # THRU_WAVE_WORDS
CPU_WORDS = 0x400                         # THRU_CPU_WORDS
LEVEL_DEF = 31
POOL_BASE = 0x107D0                       # stock reserved bottom of wave RAM (21E7:0206)
MAIN_316 = 72.0                           # test_mute_voice's MAIN; shift() moves it


def page(*more: tuple[float, str]) -> list:
    return h.taps((CANCEL, "soft4"), (MIXER, "mixer_effects"), (SIX, "6"), *more)


def parse(path: Path) -> dict:
    lines = path.read_text().splitlines()
    out = {"snap": [], "x": [], "keyon": [], "dsp": [], "dma": [], "ppi": []}
    for line in lines:
        kind, _, rest = line.partition(" ")
        if kind == "SNAP":
            out["snap"].append(json.loads(rest))
            continue
        fields = dict(re.findall(r"(\w+)=(\S+)", rest))
        if kind == "X":
            out["x"].append((float(fields["t"]), fields["name"]))
        elif kind == "KEYON":
            out["keyon"].append((float(fields["t"]), int(fields["ch"]), fields["cs"]))
        elif kind in ("DSP", "DMA", "PPI"):
            out[kind.lower()].append((float(fields["t"]), int(fields["port"], 16), int(fields["data"], 16),
                                      fields["cs"]))
    return out


def snap_at(log: dict, t: float) -> dict:
    return next(s for s in log["snap"] if abs(s["t"] - t) < 1e-6)


def reserved(s: dict) -> set[int]:
    return {i for i, v in enumerate(s["resv"]) if v}


def mixers(log: dict, cave: str) -> dict[int, int]:
    """Channel -> the last reg-7 lane-62 word the cave wrote."""
    sel, out = None, {}
    for _, port, data, cs in log["dsp"]:
        if cs != cave:
            continue
        if port == 0x60:
            sel = data
        elif port == 0x62 and sel is not None and sel >> 8 == 7:
            out[sel & 0x1F] = data
    return out


class InputThru(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        sine_snd = RUNS / "SINE441.SND"
        sine_snd.write_bytes(snd("SINE441", sine441()))
        jobs = {}
        load = h.taps((38.0, "disk"), (38.8, "7"), (42.0, "soft1"))
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            runs = RUNS / p.label
            runs.mkdir(parents=True, exist_ok=True)
            mono = page((ON, "+"))
            cases = {
                "page": (page(), [MIXER + 0.6, PAGE], []),
                "mono": (mono + h.taps((38.5, "main_screen")), [38.0, 40.0], []),
                "stereo": (page((ON, "+"), (ON + 0.5, "+"), (ON + 1.0, "+")), [39.0], []),
                "level": (mono + h.taps((37.5, "down"), (38.0, "5"), (38.3, "0"), (38.6, "enter")),
                          [40.0], []),
                "off": (mono + h.taps((38.0, "-")), [37.5, 39.5], []),
                "load": (mono + h.taps((36.8, "main_screen")) + load, [37.5, 49.0], [(sine_snd, "SINE441.SND")]),
                "sample": (mono + h.taps((36.8, "main_screen"), (38.0, "program_sounds"), (38.8, "5"),
                                         (43.0, "main_screen")), [41.0, 45.0], []),
                "edit": (mono + h.taps((36.8, "main_screen")) + load
                         + h.taps((48.0, "program_sounds"), (48.8, "6"), (50.5, "soft1"), (51.5, "soft1")),
                         [53.0], [(sine_snd, "SINE441.SND")]),
            }
            for name, (events, times, files) in cases.items():
                jobs[(p.label, name)] = (p, runs, name, events, times, files, {})
            # 32 MB board: [F16A] = 16 banks.  The boot snapshot is a 2 MB board.
            big = {"board_mb": 32, "snapshot": False}
            jobs[(p.label, "mono32")] = (p, runs, "mono32", cases["mono"][0], [38.0], [], big)
            jobs[(p.label, "stereo32")] = (p, runs, "stereo32", cases["stereo"][0], [39.0], [], big)
            jobs[(p.label, "pads")] = cls.pads_case(p, runs)

        def execute(key, job):
            p, runs, name, events, times, files, kw = job
            screens = h.run_case(p, runs, name, times=times, events=events, files=files, parts=["thru"],
                                 env={"THRU_FROM": "30.0"}, **kw)
            log = runs / name / "thru.log"
            h.require_marker(log, f'"t":{times[-1]:.3f}')
            return p, screens, parse(log)

        cls.results = h.run_parallel(jobs, execute)

    @staticmethod
    def pads_case(p: h.Profile, runs: Path) -> tuple:
        """Stereo Thru, then 40 hits of a 6-second POLY sound on two pads: more
        voices than the 28 left, so the allocator steals."""
        sound = runs / "TEST.SND"
        sound.write_bytes(snd("TEST", [sine(44_100 * 6)]))
        program = program_fixture(runs / "pads.PGM", sound, enabled=False, groups={})
        main = MAIN_316 + shift(p)
        events = load_actions(p) + h.taps((main + 1.0, "mixer_effects"), (main + 1.8, "6"),
                                          (main + 3.0, "+"), (main + 3.5, "+"), (main + 4.0, "+"),
                                          (main + 5.0, "main_screen"))
        for k in range(40):
            events += pad_hit(panel_pad(1 + k % 2), main + 6.0 + 0.08 * k, hold=0.04)
        return (p, runs, "pads", events, [main + 5.5, main + 11.0], [(program, "MUTE.PGM"), (sound, "TEST.SND")], {})

    def each(self, name):
        return [(label, r) for (label, case), r in self.results.items() if case == name]

    def test_menu_item_and_page_defaults(self) -> None:
        for label, (p, screens, log) in self.each("page"):
            with self.subTest(set=label):
                menu = [r.replace(".", " ") for r in screens[0]["rows"]]
                self.assertIn("Mixer", menu[0])
                self.assertTrue(menu[5].startswith("5 Effects           6 Input thru"), menu[5])
                rows = [r.replace(".", " ") for r in screens[1]["rows"]]
                self.assertIn("Input Thru", rows[0])
                self.assertTrue(rows[1].startswith("Thru:OFF"), rows[1])
                self.assertEqual(rows[1][20:32], "Input:ANALOG")
                self.assertTrue(rows[2].startswith("Level: 31"), rows[2])
                self.assertTrue(rows[4].startswith("Status:OFF"), rows[4])
                s = snap_at(log, PAGE)
                self.assertEqual((s["in_on"], s["stage_on"], reserved(s)), (0, 0, set()))
                self.assertEqual((s["set_mode"], s["set_input"], s["set_level"]), (0, 0, 0))

    def test_mono_programs_dma_input_and_voices(self) -> None:
        for label, (p, screens, log) in self.each("mono"):
            cave = f"{p.cave_segment:04X}"
            with self.subTest(set=label):
                rows = [r.replace(".", " ") for r in screens[0]["rows"]]
                self.assertTrue(rows[1].startswith("Thru:MONO LFT"), rows[1])
                self.assertTrue(rows[4].startswith("Status:ON"), rows[4])
                s = snap_at(log, 38.0)
                self.assertEqual((s["in_on"], s["stage_on"], s["hold"], s["status"]), (1, 1, 0, 1))
                self.assertEqual(reserved(s), {0, 31})
                self.assertEqual((s["set_mode"], s["set_level"], s["mix"]), (1, 0, 79))
                # The pool gives up the top RING_WORDS words of wave RAM.
                top = s["banks"] << 20
                self.assertEqual(s["pool_len"], top - POOL_BASE - RING_WORDS)
                ring = top - RING_WORDS
                self.assertEqual(s["wave"][:5], [ring >> 20, (ring >> 4) & 0xFFFF, (ring & 15) << 12,
                                                 ((ring + 0x1FF0) >> 20) | 0x110, ((ring + 0x1FF0) >> 4) & 0xFFFF])
                # DMA: ch2 (ADC -> ring, 55h) then ch3 (ring -> DSP, 59h) on the cave ring, both unmasked.
                dma = [(port, data) for _, port, data, cs in log["dma"] if cs == cave]
                addr = (s["dma_lo"], s["dma_hi"])
                self.assertEqual(addr[1] & 0xF0, 0x30)
                phys = ((addr[1] & 0x0F) << 16 | addr[0]) + 0x300000
                self.assertEqual(phys, p.cave_phys + p.symbols()["thru_cpu_ring"])
                for ch, mode in ((2, 0x55), (3, 0x59)):
                    i = dma.index((0xC001, ch))
                    self.assertEqual(dma[i + 1:i + 5], [(0xC004, addr[0]), (0xC006, addr[1]),
                                                        (0xC002, CPU_WORDS - 1), (0xC00A, mode)])
                masks = [data for port, data in dma if port == 0xC00F]
                self.assertEqual(masks[-1] & 0x0C, 0)
                # 8255: analog MONO-LFT as 2F37:04ED (FC bits 4-5 = 1, bit 6 set).
                fc = [data for _, port, data, cs in log["ppi"] if cs == cave and port == 0xFC]
                self.assertEqual(fc[-1] & 0x70, 0x50)
                # DSP: record DMA on, monitor channel 31 keyed by the cave, centre at the level.
                ctl = [data for _, port, data, cs in log["dsp"] if cs == cave and port == 0x68]
                self.assertIn(0x40, ctl)
                self.assertIn((31, cave), [(ch, cs) for _, ch, cs in log["keyon"]])
                self.assertEqual(mixers(log, cave)[31], 0x4F4F)
                # Leaving the page is a mode change: Thru stays as it is, no re-key.
                self.assertEqual(snap_at(log, 40.0)["stage_on"], 1)
                self.assertEqual([t for t, _, cs in log["keyon"] if t > 38.5], [])

    def test_stereo_reserves_four_channels_and_pans_hard(self) -> None:
        for label, (p, screens, log) in self.each("stereo"):
            cave = f"{p.cave_segment:04X}"
            with self.subTest(set=label):
                self.assertTrue(screens[0]["rows"][1].replace(".", " ").startswith("Thru:STEREO"))
                s = snap_at(log, 39.0)
                self.assertEqual((s["in_on"], s["stage_on"], s["mode"]), (1, 1, 2))
                self.assertEqual(reserved(s), {0, 3, 16, 31})
                ring = (s["banks"] << 20) - RING_WORDS
                right = ring + 0x1000
                self.assertEqual(s["wave"][5:], [right >> 20, (right >> 4) & 0xFFFF, (right & 15) << 12,
                                                 ((right + 0xFF0) >> 20) | 0x110, ((right + 0xFF0) >> 4) & 0xFFFF])
                ctl = [data for _, port, data, cs in log["dsp"] if cs == cave and port == 0x68]
                self.assertEqual(ctl[-1] & 0xFF, 0x58)
                keyed = {ch for t, ch, cs in log["keyon"] if cs == cave and t > ON + 1.0}
                self.assertEqual(keyed, {3, 31})
                mix = mixers(log, cave)
                self.assertEqual((mix[31], mix[3]), (0x4F00, 0x004F))

    def test_32mb_board_runs_with_the_ring_at_the_top(self) -> None:
        """A 32 MB board stores 16 banks in [F16A]; Thru ran up to 8 (bench THRU 01:
        Status NO SOUND MEMORY on a 32 MB MPC3000)."""
        for name, t, voices in (("mono32", 38.0, {0, 31}), ("stereo32", 39.0, {0, 3, 16, 31})):
            for label, (p, screens, log) in self.each(name):
                with self.subTest(set=label, case=name):
                    rows = [r.replace(".", " ") for r in screens[0]["rows"]]
                    self.assertTrue(rows[4].startswith("Status:ON"), rows[4])
                    s = snap_at(log, t)
                    self.assertEqual((s["banks"], s["in_on"], s["stage_on"], s["status"]), (16, 1, 1, 1))
                    self.assertEqual(reserved(s), voices)
                    top = 16 << 20
                    self.assertEqual(s["pool_len"], top - POOL_BASE - RING_WORDS)
                    ring = top - RING_WORDS
                    self.assertEqual(s["wave"][:3], [ring >> 20, (ring >> 4) & 0xFFFF, (ring & 15) << 12])
                    if name == "stereo32":
                        right = ring + 0x1000
                        self.assertEqual(s["wave"][5:], [right >> 20, (right >> 4) & 0xFFFF, (right & 15) << 12,
                                                         ((right + 0xFF0) >> 20) | 0x110,
                                                         ((right + 0xFF0) >> 4) & 0xFFFF])

    def test_level_is_stored_and_rewrites_only_the_mixer(self) -> None:
        for label, (p, screens, log) in self.each("level"):
            cave = f"{p.cave_segment:04X}"
            with self.subTest(set=label):
                self.assertTrue(screens[0]["rows"][2].startswith("Level: 50"), screens[0]["rows"][2])
                s = snap_at(log, 40.0)
                self.assertEqual((s["set_level"], s["mix"], s["stage_on"]), (50 ^ LEVEL_DEF, 128, 1))
                self.assertEqual(mixers(log, cave)[31], 0x8080)
                self.assertEqual([t for t, _, cs in log["keyon"] if t > 37.5], [])

    def test_off_restores_input_and_frees_the_channels(self) -> None:
        for label, (p, screens, log) in self.each("off"):
            cave = f"{p.cave_segment:04X}"
            with self.subTest(set=label):
                self.assertEqual(snap_at(log, 37.5)["in_on"], 1)
                s = snap_at(log, 39.5)
                self.assertEqual((s["in_on"], s["stage_on"], s["status"], reserved(s)), (0, 0, 0, set()))
                self.assertTrue(screens[1]["rows"][4].startswith("Status:OFF"))
                after = [(port, data) for t, port, data, cs in log["ppi"] if cs == cave and t > 38.0]
                fc = [data for port, data in after if port == 0xFC]
                self.assertEqual(fc[-1] & 0xB0, 0x80)              # as 2F37:016E: bit 7 set, mode bits clear
                masks = [data for t, port, data, cs in log["dma"] if cs == cave and port == 0xC00F and t > 38.0]
                self.assertEqual(masks[-1] & 0x0C, 0x0C)
                self.assertEqual(s["owner"][0], 255)
                self.assertEqual(s["owner"][31], 255)

    def test_load_pauses_for_floppy_and_transfers_then_resumes(self) -> None:
        for label, (p, screens, log) in self.each("load"):
            with self.subTest(set=label):
                self.assertIn("Free(snd)", screens[1]["rows"][2])
                self.assertNotIn("Attention", screens[1]["rows"][0])
                names = [n for _, n in log["x"]]
                self.assertGreater(names.count("thru_fdc_enter"), 0)
                self.assertEqual(names.count("thru_fdc_enter"), names.count("thru_fdc_leave"))
                self.assertGreater(names.count("thru_xfer_guard.wrap"), 0)
                s = snap_at(log, 49.0)
                self.assertEqual((s["in_on"], s["stage_on"], s["hold"]), (1, 1, 0))
                # The stage restarts only after the last pause, and THRU_QUIET ticks later.
                last_pause = max(t for t, n in log["x"] if n in ("thru_fdc_leave", "thru_xfer_guard.wrap"))
                starts = [t for t, n in log["x"] if n == "thru_stage_start" and t > 38.0]
                self.assertGreater(starts[-1], last_pause + 0.09)

    def test_sample_new_sound_runs_with_thru_off(self) -> None:
        for label, (p, screens, log) in self.each("sample"):
            cave = f"{p.cave_segment:04X}"
            with self.subTest(set=label):
                self.assertIn("Sample New Sound", screens[0]["rows"][0])
                s = snap_at(log, 41.0)
                self.assertEqual((s["in_on"], s["stage_on"], reserved(s)), (0, 0, set()))
                stock = [ch for t, ch, cs in log["keyon"] if 38.8 < t < 43.0 and cs != cave]
                self.assertIn(31, stock)                       # the stock monitor 2F37:0008
                s = snap_at(log, 45.0)
                self.assertEqual((s["in_on"], s["stage_on"], s["hold"], reserved(s)), (1, 1, 0, {0, 31}))

    def test_stop_all_and_audition_leave_the_reserved_channels(self) -> None:
        for label, (p, screens, log) in self.each("edit"):
            cave = f"{p.cave_segment:04X}"
            with self.subTest(set=label):
                names = [n for t, n in log["x"] if t > 50.0]
                self.assertIn("thru_stop_guard.skip", names)
                stock = [ch for t, ch, cs in log["keyon"] if t > 50.0 and cs != cave]
                self.assertTrue(stock)
                self.assertFalse({0, 31} & set(stock), stock)
                s = snap_at(log, 53.0)
                self.assertEqual((s["in_on"], s["stage_on"], reserved(s)), (1, 1, {0, 31}))

    def test_pads_never_get_a_reserved_channel(self) -> None:
        for label, (p, screens, log) in self.each("pads"):
            cave = f"{p.cave_segment:04X}"
            main = MAIN_316 + shift(p)
            with self.subTest(set=label):
                s = snap_at(log, main + 5.5)
                self.assertEqual(reserved(s), {0, 3, 16, 31})
                played = [ch for t, ch, cs in log["keyon"] if t > main + 6.0 and cs != cave]
                self.assertGreaterEqual(len(played), 40)
                self.assertFalse({0, 3, 16, 31} & set(played), played)
                self.assertEqual(len(set(played)), 28)             # every other channel, then steals
                end = snap_at(log, main + 11.0)
                self.assertEqual((end["stage_on"], reserved(end)), (1, {0, 3, 16, 31}))
                self.assertEqual([end["owner"][c] for c in (0, 3, 16, 31)], [255] * 4)


if __name__ == "__main__":
    unittest.main()
