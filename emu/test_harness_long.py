"""32-bit paths on a really loaded 220,500-frame sound (5 s, above 16 bits).

Run: python3 -m unittest emu.test_harness_long -v

One run per profile loads LONG.SND through Disk / 7 / <Load> (no RAM pokes)
and checks, against emu/wave_ref.py or exact arithmetic:

- full and fine view pixels with points above 65,535;
- the 16- and 3-way zone divisions of a length above 16 bits;
- point motion whose result carries from 65,000 across 65,536;
- numeric commit of 2.000.00 = 88,200 frames;
- an audition whose start (88,200) is above 65,535: the stock player's own
  reads of the record bounds and the DSP start address;
- CHOP ZONE with source offsets 73,500 and 147,000, PCM compared.

Profiles: capture, generic and 316 (WAVE316.SYS on OS 3.16; one BIOS set per
load segment by default, all four in release mode).  Times are relative to
VL = profile.view + LONG_LOAD.  The arithmetic is the same cave code on every
profile, so every value is the same; on 3.16 the stock addresses are its own:
the player CFC6:0CE9..0D75 is 20ED:0CEF..0D7B and the record SND_SEG:4800
(profile_316.inc, emu/lua/wave_playback316.lua), and CHOP ZONE is Do option 8
instead of 10 (3.16 has eight stock options, CHOP_STOCK_OPTIONS).
"""
from __future__ import annotations

import math
from pathlib import Path
import unittest

from emu import harness as h
from emu import wave_ref
from emu.harness import burst, pcm, sound_records, taps, zone_rows
from emu.panel import dial
from emu.snd import snd
from emu.test_wave_chop import do_action
from emu.test_wave_playback import parse_events

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/harness-long-tests"
L = 220_500
STEP = L // 240                     # 918
START, END = 65_000, 200_000
NUMERIC = 2 * 44_100
# 441 KB loads in about 16 s (Vailixi), so the view opens LONG_LOAD s after
# the profile's ~170 KB view time; it then scans all 220,500 frames.  VL = 58
# on Vailixi, 70 on 3.16 (Program/Sounds at 64 s, 25 s after <Load> at 39 s).
LONG_LOAD = 18.0
CHOP_INDEX_316 = 10                 # CHOP ZONE after the ten Do options (Vailixi order, mods/wave_chop.inc)


def long_wave() -> list[list[int]]:
    """441 Hz sine under a linear envelope: distinct columns everywhere."""
    return [[round(30000 * (i / L) * math.sin(2 * math.pi * i / 100)) for i in range(L)]]


def chop_action(at: float, profile: h.Profile) -> list:
    """test_wave_chop.do_action (exit, Right x16 to Do:, select CHOP ZONE, Do),
    with CHOP ZONE at its 3.16 index on the 316 profile."""
    if not profile.is316:
        return do_action(at)
    return (taps((at, "soft4")) + taps(*[(at + 2 + i * .2, "right") for i in range(16)])
            + dial(CHOP_INDEX_316, at + 6) + taps((at + 9, "soft4")))


def record_bounds_phys(profile: h.Profile) -> int:
    """Physical address of sound record zero's start dword (SND_SEG:4814;
    0x3A72F4 on Vailixi, 0x300000 + (L+539D)*16 + 4814 on 3.16)."""
    return 0x300000 + profile.sound_segment * 16 + 0x4814


def player_window(profile: h.Profile) -> tuple[str, int, int]:
    """Runtime CS (hex text, as logged) and IP range of the stock player body."""
    if not profile.is316:
        return "CFC6", 0x0CE9, 0x0D75
    entry, after = profile.target("T_CFC6_0CE9"), profile.target("T_CFC6_0D75")
    return f"{entry.cs:04X}", entry.ip, after.ip


class Long(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"long"})
    PROFILE_NAMES = h.ALL_PROFILES

    @classmethod
    def cases(cls, profile, runs):
        VL = profile.view + LONG_LOAD
        tl = profile.timeline
        src = runs / "LONG.SND"
        if not src.exists():
            src.write_bytes(snd("LONG", long_wave(), start=START, end=END))
        events = (burst(5, VL + 1)                                       # Start 65000 -> 69590
                  + taps((VL + 3, "soft3"), (VL + 5, "soft3"))            # Fine, then Full
                  + taps((VL + 8, "2"), (VL + 9, "right"), (VL + 10, "0"), (VL + 11, "right"),
                         (VL + 12, "0"), (VL + 13, "enter"))              # Start = 2.000.00
                  + taps((VL + 15, "soft1"), (VL + 16, "soft1"))          # audition, stop
                  + taps((VL + 18, "right"), (VL + 19, "right"), (VL + 20, "right"))
                  + dial(-13, VL + 21)                                    # 16 -> 3 zones
                  + chop_action(VL + 24, profile))                        # CHOP ZONE
        return {"long": h.Case(
            events=h.wave_events(events, view_at=VL - (tl.view - tl.view_at), profile=profile),
            times=[VL, VL + 2.5, VL + 4.5, VL + 14.5, VL + 17, VL + 23, VL + 43],
            files=[(src, "LONG.SND")],
            parts=("repeat_watch", "wave_zones", "snddump", "wave_playback"),
            env={"SNDDUMP_PCM": f"{VL},{VL + 43}", "PLAYBACK_WATCH_FROM": str(VL - 1)})}

    def vl(self, prof: str) -> float:
        return self.view(prof) + LONG_LOAD

    def test_full_and_fine_pixels_above_16_bits(self):
        planes = long_wave()
        for prof, d, screens in self.each("long"):
            with self.subTest(profile=prof):
                VL = self.vl(prof)
                px = h.lcd_pixels(d)
                zone = [0, L // 16]
                self.assertEqual(px[f"{VL:.3f}"], wave_ref.screen(
                    planes, "LONG", wave_ref.View([START, END, *zone])))
                moved = START + 5 * STEP
                self.assertEqual(px[f"{VL + 2.5:.3f}"], wave_ref.screen(
                    planes, "LONG", wave_ref.View([moved, END, *zone])))
                self.assertEqual(px[f"{VL + 4.5:.3f}"], wave_ref.screen(
                    planes, "LONG", wave_ref.View([moved, END, *zone], fine=True)))

    def test_point_motion_carries_across_16_bits(self):
        for prof, d, _ in self.each("long"):
            with self.subTest(profile=prof):
                VL = self.vl(prof)
                records = sound_records(d, VL + 2.5)[0]
                self.assertEqual((records["start"], records["end"], records["length"]),
                                 (START + 5 * STEP, END, L))
                self.assertGreater(START + 5 * STEP, 0xFFFF)
                self.assertEqual(sum(h.repeats(d, start=VL + 1, end=VL + 2)), 5)

    def test_zone_divisions_above_16_bits(self):
        for prof, d, _ in self.each("long"):
            with self.subTest(profile=prof):
                VL = self.vl(prof)
                r = zone_rows(d)
                self.assertEqual(r[VL]["bounds"], [L * i // 16 for i in range(17)])
                self.assertEqual(r[VL + 23]["count"], 3)
                self.assertEqual(r[VL + 23]["bounds"][:4], [0, 73_500, 147_000, L])

    def test_numeric_commit_above_16_bits(self):
        for prof, d, screens in self.each("long"):
            with self.subTest(profile=prof):
                VL = self.vl(prof)
                self.assertEqual(sound_records(d, VL + 14.5)[0]["start"], NUMERIC)
                self.assertIn("mode=32", screens[3]["head"])

    def test_audition_start_above_16_bits(self):
        for prof, d, _ in self.each("long"):
            with self.subTest(profile=prof):
                VL = self.vl(prof)
                profile = self.profiles[prof]
                log = parse_events(d / "wave_playback.log")
                kinds = lambda k: [e.values for e in log if e.kind == k]
                # The 316 probe's taps assume the record's physical address (live PGR check).
                self.assertEqual(kinds("SNDPHYS"), [])
                # The audition's temporary record bounds (point edits before it
                # also write the start word; take the window around Ply/Stp).
                writes = [w for w in kinds("BOUNDWRITE") if VL + 15 <= w["t"] < VL + 16]
                self.assertEqual(len(writes), 8)
                self.assertEqual([w["data"] for w in writes[:4]],
                                 [NUMERIC & 0xFFFF, NUMERIC >> 16, END & 0xFFFF, END >> 16])
                # CFC6:0CE9 (3.16 20ED:0CEF) read the start dword and the
                # end's high word (its signed high-word compare decides
                # start < end here).
                cs, first, end_ip = player_window(profile)
                bound = record_bounds_phys(profile)
                reads = {(r["phys"], r["data"]) for r in kinds("BOUNDREAD")
                         if r["cs"] == cs and first <= int(r["ip"], 16) < end_ip}
                self.assertEqual(reads, {(bound, NUMERIC & 0xFFFF), (bound + 2, NUMERIC >> 16),
                                         (bound + 6, END >> 16)})
                base = kinds("SNAP")[0]["wave"]
                self.assertEqual([s["start"] for s in kinds("STARTREG")], [base + NUMERIC])
                # Restored after the call.
                after = sound_records(d, VL + 17)[0]
                self.assertEqual((after["start"], after["end"]), (NUMERIC, END))

    def test_chop_with_source_offsets_above_16_bits(self):
        bounds = [0, 73_500, 147_000, L]
        for prof, d, _ in self.each("long"):
            with self.subTest(profile=prof):
                VL = self.vl(prof)
                old, new = sound_records(d, VL), sound_records(d, VL + 43)
                self.assertEqual(len(old), 1)
                self.assertEqual(len(new), 4)
                source = pcm(d, VL, 0)
                self.assertEqual(pcm(d, VL + 43, 0), source)
                for i, (a, b) in enumerate(zip(bounds, bounds[1:]), 1):
                    self.assertEqual(new[i]["length"], b - a)
                    self.assertEqual(pcm(d, VL + 43, i), source[2 * a:2 * b], f"slice {i}")


if __name__ == "__main__":
    unittest.main()
