"""CHOP ZONE end-to-end tests: real floppy loading, panel input, and PCM.

Run: python3 -m unittest emu.test_wave_chop -v

No test writes zone/sample/allocator RAM. Failure cases fill the real sound
directory or sample memory through the same UI paths used by a musician.
Payloads come from emu.harness (built from the current sources; capture
profile for every case, generic for the GENERIC subset, and every case on the
316 profile: WAVE316.SYS on OS 3.16, one BIOS set per load segment by default,
all four in release mode).  Times are relative to V = profile.view (40 s on
Vailixi, 52 s on 3.16).

OS 3.16 differences, each asserted as 3.16 behaves:
- The stock Do list has 8 options, so CHOP ZONE is Do #8 (Vailixi #10); see
  CHOP_DO.  The page, fields and soft keys are otherwise the same.
- CHOP names its results itself (mods/wave_chop.inc CHOP_OWN_NAMES): the next
  ZONEnnn that no Sound has, so the expected names are the same.
- memory_full loads its 540,000-frame source from a raw SCSI disk (MAME
  -scsi:0 harddisk) in the stock MPC layout instead of the floppy, which
  holds WAVE316.SYS and has no room for it; see memory_case().

Refusal messages replace the whole soft-key row (row 7): before 2026-10-16
the soft-key text after the message stayed on screen (audit B3), so the
empty/stale/short checks compare all 40 columns.

zone_stale_display: four zones, exit, Zone end typed as 800 ms on the stock
page (beyond the next boundary), then CHOP ZONE.  CHOP imports the stock
pair into the map (zones_import), which clamps Zone end to the next boundary
and writes the clamped pair back to ZONE_ST/ZONE_EN (3.16 DS:E45A/E456,
Vailixi EDBB/EDB7), and refuses with EMPTY ZONE.  The page's own component
triples ([BP-0Ch], [BP-12h]) are now resynchronised from that pair
(chop_sync_zone_fields), so the page shows the pair a following DELETE ZONE
acts on.  Before the fix the page kept showing 800 ms while DELETE ZONE
removed the clamped zone (audit B2, MAME).  The pair is read by a read-only
prelude (zonepair.log).
"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import unittest

from emu import harness as h
from emu.harness import pcm, sound_records, taps
from emu.panel import dial
from emu.snd import sine441, snd, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-tests"
DIRECTORY_SOURCE = 8192
# CHOP ZONE's index in the Do list, after the stock options.  Vailixi
# B99A:0B05 (linear 0x3A4A5) `cmp bx,9` bounds the stock Do table to 0..9;
# 3.16 0B72:0B0A (image 0xC22A) `cmp bx,7` bounds it to 0..7
# (mods/profile_316.inc: COPY ZONE->TEMP .. REVERSE ZONE).
CHOP_DO, CHOP_DO_316 = 10, 10


def do_action(exit_time: float, profile: h.Profile | None = None) -> list:
    """Exit WAVE, traverse the 17 stock fields and select appended CHOP ZONE
    (Do #10 on Vailixi and on PMONEY 3.16)."""
    return (taps((exit_time, "soft4"))
            + taps(*[(exit_time + 2 + i * .2, "right") for i in range(16)])
            + dial(CHOP_DO_316 if profile is not None and profile.is316 else CHOP_DO, exit_time + 6)
            + taps((exit_time + 9, "soft4")))


# memory_full on 3.16: the source is on a SCSI disk; the boot scan mounts it
# (done before 30 s) and makes it the current disk, so the case does not cancel
# the scan.  Disk / 7 / <Load> from MEMORY_LOAD_316; 1,080,038 bytes load in
# under 4 s (45 -> 48.0 s on default, MAME).
MEMORY_LOAD_316 = 41.0
MEMORY_DISK_SECTORS = 8192              # 4 MiB raw SCSI disk, one MPC volume


def memory_case(profile: h.Profile) -> tuple[int, float, float, float]:
    """memory_full: source frames, then the view_at, view-open and after-Do
    times (Vailixi: 540,000 frames, 110, 116, 138).

    The source must exceed half of the free sound memory, 980,992 words
    (Free(snd) 1916K with nothing loaded, on every profile in MAME), so its
    copy cannot fit.  Vailixi: 540,000 frames take ~84 s to load from the
    floppy.  3.16: the floppy also holds WAVE316.SYS (over 470 KB), which
    leaves less than the 1,080,038 bytes of 540,000 frames, and any source
    that fits there (under ~490,000 frames) is within a few hundred bytes of
    the 490,497-frame minimum, so every growth of the SYS broke the case.
    The 3.16 source is therefore the same 540,000 frames, loaded from a SCSI
    disk (scsi_source()), and the floppy size no longer matters.
    """
    tl = profile.timeline
    if profile.is316:
        view_at = MEMORY_LOAD_316 + tl.load_key + 5.0
    else:
        view_at = tl.load_at + tl.load_key + 83.5
    return 540_000, view_at, view_at + 6, view_at + 28


def scsi_source(runs: Path, src: Path, name: str) -> Path:
    """A raw SCSI disk holding `src` as `name` in the stock MPC layout, as 2AB2:04F7 reads
    it: one FAT12 volume at LBA 0 (mformat, 16 sectors/track, 16 heads, 512
    root entries), its volume table at 40h (entry 0 = LBA 0, then zero) and
    55 AA 55 AA at 1FCh."""
    env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
    image = runs / "memory_full.hd"
    image.write_bytes(bytes(MEMORY_DISK_SECTORS * 512))
    subprocess.run(["mformat", "-i", str(image), "-T", str(MEMORY_DISK_SECTORS), "-h", "16", "-s", "16",
                    "-c", "16", "-r", "32", "-H", "0", "::"], check=True, env=env, capture_output=True)
    data = bytearray(image.read_bytes())
    data[0x40:0x40 + 26 * 4] = bytes(26 * 4)
    data[0x1FC:0x200] = b"\x55\xaa\x55\xaa"
    image.write_bytes(data)
    subprocess.run(["mcopy", "-i", str(image), str(src), "::" + name], check=True, env=env, capture_output=True)
    return image


# Frame counts and the stock Edit Sound text MAME showed for them (this suite
# and emu/test_harness_lifecycle.py).
SHOWN = {1000: "000.022.30", 3445: "000.078.06", 13913: "000.315.22", 27562: "000.625.00",
         35302: "000.800.22", 50000: "001.133.35", 55125: "001.250.00"}


def text_frames(text: str) -> int:
    """Frames of the page's sss.mmm.ff: milliseconds * 44.1 rounded down, plus
    the frame digits (agrees with every SHOWN pair).  The text of a frame
    count is not unique (27562 also reads as 000.624.44), so tests compare
    frames, not text."""
    sec, ms, rest = (int(x) for x in text.split("."))
    return (sec * 1000 + ms) * 441 // 10 + rest


def zone_field(screen: dict, name: str) -> str:
    """'Zone st' / 'Zone end' text of the stock page (rows 2 and 3, columns 21-39)."""
    import re
    row = screen["rows"][2 if name == "Zone st" else 3]
    match = re.search(r"(\d{3}\.\d{3}\.\d{2})$", row[21:].rstrip())
    assert match and row[21:].replace(".", " ").startswith(name), row
    return match.group(1)


def zone_pair_prelude(profile: h.Profile) -> str:
    """Read-only Lua: ZONE_ST / ZONE_EN dwords (DGROUP) at each probe time -> zonepair.log."""
    return f"""
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, ioport = cpu.spaces["program"], cpu.spaces["io"]
local zlog = assert(io.open((os.getenv("PROBE_OUT") or ".") .. "/zonepair.log", "w"))
local ztimes = {{}}
for t in string.gmatch(os.getenv("PROBE_TIMES") or "", "[^,]+") do ztimes[#ztimes + 1] = tonumber(t) end
local function phys(seg, off)
    local a = ((seg << 4) + off) & 0xfffff
    if cpu.state["XA"].value ~= 0 then
        return ((ioport:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
    end
    return a
end
local zi = 1
emu.register_periodic(function()
    if zi > #ztimes or machine.time:as_double() < ztimes[zi] - 0.05 then return end
    zlog:write(string.format("t=%g zst=%d zen=%d\\n", ztimes[zi],
        prog:read_u32(phys(0x{profile.dgroup_segment:04X}, 0x{profile.dgroup(0xEDBB):04X})),
        prog:read_u32(phys(0x{profile.dgroup_segment:04X}, 0x{profile.dgroup(0xEDB7):04X}))))
    zlog:flush()
    zi = zi + 1
end)
"""


def zone_pairs(d: Path) -> dict[float, tuple[int, int]]:
    out = {}
    for line in (d / "zonepair.log").read_text().splitlines():
        t, st, en = (f.split("=")[1] for f in line.split())
        out[round(float(t), 3)] = (int(st), int(en))
    return out


def records(case: Path | str, time: float) -> dict[int, dict]:
    """Sound directory at a probe time; a str names a legacy RUNS/<case> directory."""
    return sound_records(RUNS / case if isinstance(case, str) else case, time)


def text(screen: dict) -> str:
    return "\n".join(screen["rows"])


class WaveChop(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"mono", "stereo", "memory_full"})
    PROFILE_NAMES = h.ALL_PROFILES

    @classmethod
    def cases(cls, profile, runs):
        V = profile.view
        tl = profile.timeline

        def do(at):
            return do_action(at, profile)

        four = taps((V + 1, "right"), (V + 2, "right"), (V + 3, "right")) + dial(-12, V + 4)
        stereo_four = taps((V + 1, "right"), (V + 2, "right"), (V + 3, "right"),
                           (V + 4, "right")) + dial(-12, V + 5)
        partial = (four + taps((V + 7, "left"), (V + 8, "left"), (V + 9, "left")) + dial(2, V + 10)
                   + taps((V + 12, "right"), (V + 13, "right")) + dial(3, V + 14)
                   + taps((V + 15, "left")) + dial(-3, V + 16) + do(V + 18))
        no_help = taps((tl.view_at, "program_sounds"), (tl.view_at + tl.view_six, "6"))
        memory_frames, memory_view_at, memory_view, memory_after = memory_case(profile)
        definitions = {
            "mono": (sine441(), "ZZSOURCE", four + do(V + 7) + taps((V + 22, "help")),
                     [V, V + 15, V + 21, V + 23], {}),
            "stereo": (stereo1(), "STEREO", stereo_four + do(V + 8), [V, V + 16, V + 22], {}),
            "tiny": ([[((i * 701) & 65535) - 32768 for i in range(2048)]], "TINY",
                     do(V + 7), [V, V + 21], {}),
            "partial": (sine441(), "PARTIAL", partial, [V, V + 17, V + 32], {}),
            "collision": (sine441(), "ZONE000", four + do(V + 7) + taps((V + 23, "soft4")),
                          [V, V + 21, V + 29], {}),
            "stale_selection": (sine441(), "ZZSOURCE", four + do(V + 7)
                                + taps((V + 22, "help"), (V + 24, "soft4"))
                                + taps(*[(V + 25 + i * .1, "left") for i in range(16)])
                                + taps((V + 27, "-"))
                                + taps(*[(V + 28 + i * .2, "right") for i in range(16)])
                                + taps((V + 34, "soft4"), (V + 36, "enter")),
                                [V + 21, V + 27, V + 35, V + 38], {}),
            "empty": (sine441(), "EMPTY", four + taps((V + 7, "left"), (V + 8, "left"),
                      (V + 9, "0"), (V + 10, "right"), (V + 11, "0"), (V + 12, "right"), (V + 13, "0"),
                      (V + 14, "enter")) + do(V + 16), [V, V + 28], {}),
            # The stock page without ever opening the view: no zone map exists.
            "stale": (sine441(), "STALE", do(V + 7)[2:], [V, V + 18], {"no_view": True}),
            "directory_full": ([[((i * 31) & 65535) - 32768 for i in range(DIRECTORY_SOURCE)]],
                               "ZZSOURCE", do(V + 7) + taps(*[(V + t, "soft4")
                                                              for t in (19, 22, 25, 28, 31, 34, 37)]),
                               [V, V + 36, V + 39], {}),
            # Zone end typed beyond the next boundary, CHOP refused (EMPTY ZONE),
            # acknowledged, then DELETE ZONE (Do #4) on the same page.
            "zone_stale_display": (sine441(), "ZSTALE", four + taps((V + 7, "soft4"))
                                   + taps(*[(V + 9 + i * .2, "right") for i in range(11)])
                                   + taps((V + 13, "8"), (V + 13.3, "0"), (V + 13.6, "0"), (V + 14, "enter"))
                                   + taps(*[(V + 15 + i * .2, "right") for i in range(5)])
                                   + dial(CHOP_DO_316 if profile.is316 else CHOP_DO, V + 17)
                                   + taps((V + 20, "soft4"), (V + 23, "left"))
                                   + dial(4 - (CHOP_DO_316 if profile.is316 else CHOP_DO), V + 25)
                                   + taps((V + 28, "soft4")),
                                   [V + 6, V + 14.8, V + 19.5, V + 22, V + 24.5, V + 27.5, V + 32],
                                   {"prelude": zone_pair_prelude(profile)}),
            "memory_full": ([[i % 32767 for i in range(memory_frames)]], "MEMORY",
                            do(memory_view + 9), [memory_view, memory_after],
                            {"view_at": memory_view_at}),
        }
        cls.definitions = definitions
        cases = {}
        for name, (planes, sound_name, events, times, options) in definitions.items():
            src = runs / f"{name}.SND"
            # Deliberately nondefault metadata and trimmed playback bounds.
            # Equal zones must still cover full PCM, ignoring Soft st/end.
            length = len(planes[0])
            data = bytearray(snd(sound_name, planes, vol=77,
                                 start=min(123, length // 4), end=length - min(321, length // 4)))
            data[2 + 0x12] = (-12) & 255
            src.write_bytes(data)
            if name == "memory_full" and profile.is316:
                # The source on a SCSI disk (memory_case()); cold boot: the boot
                # snapshot has no SCSI device.
                disk = scsi_source(runs, src, sound_name + ".SND")
                timeline = (taps((MEMORY_LOAD_316, "disk"), (MEMORY_LOAD_316 + tl.load_seven, "7"),
                                 (MEMORY_LOAD_316 + tl.load_key, "soft1"))
                            + h.open_view_events(options["view_at"], profile) + events)
                cases[name] = h.Case(events=timeline, times=times, files=[],
                                     kwargs={"extra": ["-scsi:0", "harddisk", "-hard", str(disk)],
                                             "snapshot": False})
                continue
            if options.get("no_view"):
                timeline = h.load_sound_events(profile=profile) + no_help + events
            else:
                timeline = h.wave_events(events, view_at=options.get("view_at"), profile=profile)
            cases[name] = h.Case(events=timeline, times=times, files=[(src, sound_name + ".SND")],
                                 prelude=options.get("prelude", ""))
        return cases

    def assert_status(self, screen: dict, message: str):
        """The refusal message owns the whole soft-key row: no soft-key remnants."""
        self.assertEqual(screen["rows"][7].replace(".", " "), message.ljust(40))

    def assert_chop(self, d: Path, before: float, after: float, bounds: list[int], repeats: int = 1):
        old, new = records(d, before), records(d, after)
        self.assertEqual(len(old), 1)
        source = old[0]
        self.assertEqual(new[0], source)
        original = pcm(d, before, 0)
        self.assertEqual(pcm(d, after, 0), original)
        self.assertEqual(len(new), 1 + (len(bounds) - 1) * repeats)
        self.assertEqual(len({r["name"] for r in new.values()}), len(new))
        extents = sorted((r["wave"], r["wave"] + r["length"] * (r["stereo"] + 1))
                         for r in new.values())
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(extents, extents[1:])))
        for i in range(1, len(new)):
            z = (i - 1) % (len(bounds) - 1)
            a, b = bounds[z:z + 2]
            rec = new[i]
            self.assertEqual((rec["length"], rec["start"], rec["end"]), (b - a, 0, b - a - 1))
            self.assertEqual((rec["volume"], rec["tune"], rec["stereo"]),
                             (source["volume"], source["tune"], source["stereo"]))
            expected = b"".join(original[(plane * source["length"] + a) * 2:
                                         (plane * source["length"] + b) * 2]
                                for plane in range(source["stereo"] + 1))
            self.assertEqual(pcm(d, after, i), expected, f"{d.name} slice {i}")

    def test_mono_exact_pcm_and_source_selection(self):
        for prof, d, screens in self.each("mono"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assert_chop(d, V, V + 21, [55125 * i // 4 for i in range(5)])
                self.assertIn("ZZSOURCE", "".join(screens[2]["rows"]))
                self.assertEqual(h.zone_rows(d)[V + 23]["count"], 4)
                self.assertIn("CHOP ZONE", "".join(screens[1]["rows"]))

    def test_stereo_planes_and_metadata(self):
        for prof, d, _ in self.each("stereo"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assert_chop(d, V, V + 22, [33075 * i // 4 for i in range(5)])

    def test_tiny_zones_refuse_to_create_unreloadable_sounds(self):
        for prof, d, screens in self.each("tiny"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assertEqual(records(d, V), records(d, V + 21))
                self.assert_status(screens[-1], "ZONE MUST BE AT LEAST 10ms")

    def test_edited_outer_boundaries_are_respected(self):
        for prof, d, _ in self.each("partial"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assert_chop(d, V, V + 32, [458, 13781, 27562, 41343, 54438])

    def test_repeated_chop_skips_existing_names(self):
        for prof, d, _ in self.each("collision"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assert_chop(d, V, V + 29, [55125 * i // 4 for i in range(5)], repeats=2)
                self.assertEqual([r["name"] for r in records(d, V + 29).values()],
                                 [f"ZONE{i:03d}" for i in range(9)])

    def test_empty_zone_refuses_without_creating_sounds(self):
        for prof, d, screens in self.each("empty"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assertEqual(records(d, V), records(d, V + 28))
                self.assert_status(screens[-1], "EMPTY ZONE - ADJUST BOUNDARIES")

    def test_no_zone_map_refuses_without_creating_sounds(self):
        for prof, d, screens in self.each("stale"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assertEqual(records(d, V), records(d, V + 18))
                self.assert_status(screens[-1], "REOPEN WAVE VIEW FOR THIS SOUND")

    def test_full_directory_preflight_creates_no_partial_set(self):
        bounds = [DIRECTORY_SOURCE * i // 16 for i in range(17)]
        for prof, d, screens in self.each("directory_full"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                # Positive control: seven real 16-way chops filled the
                # directory, and every slice is the exact source PCM.
                self.assert_chop(d, V, V + 36, bounds, repeats=7)
                self.assertEqual(len(records(d, V + 36)), 113)
                # The eighth Do is refused by the stock 128-sound message and
                # changes nothing.
                self.assertEqual(records(d, V + 36), records(d, V + 39))
                self.assertEqual(pcm(d, V, 0), pcm(d, V + 39, 0))
                final = text(screens[-1]).replace(".", " ")
                self.assertIn("Attention", final)
                self.assertIn("128-sound limit", final)

    def test_stale_map_error_keeps_the_newly_selected_sound(self):
        for prof, d, screens in self.each("stale_selection"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                before = records(d, V + 21)
                self.assertEqual(before, records(d, V + 38))
                # Reopening the stock page keeps the source selected even though
                # the four new alphabetically earlier names changed its position.
                self.assertIn("ZZSOURCE", "".join(screens[1]["rows"]))
                self.assert_status(screens[2], "REOPEN WAVE VIEW FOR THIS SOUND")
                self.assertIn("ZONE003", "".join(screens[2]["rows"]))
                self.assertIn("ZONE003", "".join(screens[3]["rows"]))

    def test_insufficient_sample_memory_creates_no_partial_set(self):
        for prof, d, screens in self.each("memory_full"):
            with self.subTest(profile=prof):
                _, _, before, after = memory_case(self.profiles[prof])
                self.assertEqual(len(records(d, before)), 1)
                self.assertEqual(records(d, before), records(d, after))
                self.assertEqual(pcm(d, before, 0), pcm(d, after, 0))
                # Positive control: the view had a 16-zone map of this sound
                # and Do reached the preflight, which refused with the stock
                # sound-memory message.
                self.assertEqual(h.zone_rows(d)[before]["valid"], 1)
                final = text(screens[-1]).replace(".", " ")
                self.assertIn("Attention", final)
                self.assertIn("sound memory", final)

    def test_text_frames_matches_the_stock_page(self):
        for frames, shown in SHOWN.items():
            self.assertEqual(text_frames(shown), frames)

    def test_refused_chop_shows_the_imported_zone_pair(self):
        length = 55125
        for prof, d, screens in self.each("zone_stale_display"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                pair, zones = zone_pairs(d), h.zone_rows(d)
                self.assertEqual(zones[V + 6]["bounds"][:5], [length * i // 4 for i in range(5)])
                # Positive control: the typed 800 ms reached the DS pair and the page.
                self.assertEqual(pair[V + 14.8], (0, 35302))
                self.assertEqual(zone_field(screens[1], "Zone end"), "000.800.22")
                # CHOP: the import clamped the end to B[2] (map and DS pair), EMPTY ZONE.
                self.assertIn("CHOP ZONE", screens[2]["rows"][5])
                self.assertIn("EMPTY ZONE", screens[3]["rows"][7])
                clamped = zones[V + 22]["bounds"][2]
                self.assertEqual(zones[V + 22]["bounds"][:3], [0, clamped, clamped])
                self.assertEqual(pair[V + 22], (0, clamped))
                # The page shows the pair DELETE ZONE will use.
                for screen, t in ((screens[4], V + 24.5), (screens[5], V + 27.5)):
                    shown = (text_frames(zone_field(screen, "Zone st")), text_frames(zone_field(screen, "Zone end")))
                    self.assertEqual(shown, pair[t], t)
                self.assertIn("DELETE ZONE", screens[5]["rows"][5])
                # DELETE ZONE removed exactly the shown range.
                shown = (text_frames(zone_field(screens[5], "Zone st")),
                         text_frames(zone_field(screens[5], "Zone end")))
                after = records(d, V + 32)[0]
                self.assertEqual(after["length"], length - (shown[1] - shown[0]))
                self.assertEqual(pcm(d, V + 32, 0), pcm(d, V + 6, 0)[:2 * shown[0]] + pcm(d, V + 6, 0)[2 * shown[1]:])
                self.assert_status(screens[3], "EMPTY ZONE - ADJUST BOUNDARIES")


if __name__ == "__main__":
    unittest.main()
