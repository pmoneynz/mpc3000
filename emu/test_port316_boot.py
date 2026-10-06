"""WAVE316.SYS (OS 3.16, Route C) boots and works on every stock BIOS set.

Run: python3 -m unittest emu.test_port316_boot -v

The payload is built from the current sources by emu.harness (316 profile)
and booted from the stock romset on all four MAME BIOS sets: `default`
(3.12) and `vailixi` load it at L = 6900h, `v311` and `v308` at L = 7000h
(notes/port_316.md).  Two runs per set, real panel input only; the observers
(emu/lua/wave_zones316.lua, image316.lua) only read RAM.

- `view`: boot banner, the harness 3.16 timeline (cancel SCSI, Disk / 7 /
  <Load> SINE441, Program/Sounds / 6 / Help), the full wave view against
  emu.wave_ref, Program/Sounds -> 0 (Mute Groups) and Soft Key 4 back; the
  cave at its home and the pool-end immediate read from physical memory.
- `song`: the pool-fix regression.  Record a sequence, press Song, then
  Main Screen and Disk; image bytes 0x0000..0x6FFF in RAM must still be the
  relocated WAVE316.SYS image.  With L = 6900h stock 3.16's sequence pool
  (logical 2000..6FFFE) overlaps exactly those image bytes; WAVE316's entry
  routine lowers the pool end to L-1 (notes/port_316.md, mods/entry316.inc).
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from emu import harness as h
from emu import wave_ref
from emu.panel import key_tap, pad_hit, panel_pad
from emu.snd import sine441, snd

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/port316-boot"
HEAD = 0x7000                       # image offsets the L=6900 pool used to overlap
HOOK = (0x318C, 0x3192)             # help_gate hook (mods/WAVE316.args), inside HEAD

T = h.TIMELINE_316
V = T.view                          # 52.0
VIEW_TIMES = [31.5, 32.6, 34.0, 38.5, 44.5, 48.0, V, 54.5, 56.5, 59.0, 61.5, 63.0, 64.5]
VIEW_DUMPS = [34.0, 61.5]

# Recording (scratchpad timeline_316.record): Main Screen, Rec held 0.5 s
# with Play Start 0.2 s into it (new SEQ01), a pad every 0.3 s for 31 s, Stop.
REC = 35.2
STOP = REC + 31.8                   # 67.0
SONG = round(STOP + 1.1, 3)         # 68.1: stopped and ready
SONG_TIMES = [34.5, REC + 0.7, REC + 15.3, STOP + 0.7, SONG + 0.6, SONG + 1.5, SONG + 2.6,
              SONG + 4.6, SONG + 6.0]
SONG_DUMPS = [34.5, SONG + 6.0]


def view_events(profile: h.Profile) -> list:
    return (h.wave_events(profile=profile)
            + h.taps((V + 1, "soft4"), (V + 3, "program_sounds"), (V + 5, "0"), (V + 8, "soft4"),
                     (V + 10, "1")) + pad_hit(panel_pad(1), V + 11.5))


def mute_page(note: int) -> list[str]:
    """emu.test_mute_ui.screen() for program 1, pad 1, all groups off, focus on
    Enabled, with the Note field showing `note` (its reference assumes the
    Vailixi default map, note = pad + 34)."""
    from emu.test_mute_ui import screen
    lit = [[c == "#" for c in row] for row in screen(1, 1, [0] * 64, False, 1)]
    for y in range(8, 15):                      # Note digits: text row 8, cells 35-36
        lit[y][35 * 6:37 * 6] = [False] * 12
    wave_ref._text(lit, 8, 35, f"{note:02d}")
    return ["".join("#" if v else "." for v in row) for row in lit]


def song_events() -> list:
    events = h.taps((T.cancel, "soft4"), (34.0, "main_screen"))
    events += key_tap("rec", REC - 0.2, 0.5) + key_tap("play_start", REC, 0.2)
    pads, t, i = (1, 2, 3, 1, 4, 2, 5, 3), REC + 0.8, 0
    while t <= REC + 31.0 - 0.2:
        events += pad_hit(panel_pad(pads[i % len(pads)]), t, hold=0.08)
        t, i = round(t + 0.3, 3), i + 1
    events += h.taps((STOP, "stop"), (SONG, "song"), (SONG + 2.0, "main_screen"), (SONG + 4.0, "disk"))
    return sorted(events, key=lambda e: e[0])


def text(screen: dict) -> str:
    """Screen rows; the probe prints NUL and unprintable cells as '.', so '.' reads as blank."""
    return "\n".join(r.replace(".", " ") for r in screen["rows"])


def image_rows(d: Path) -> dict[float, dict]:
    return {round(r["time"], 3): r for line in (d / "image316.jsonl").read_text().splitlines()
            if (r := json.loads(line))}


class Port316Boot(unittest.TestCase):
    results: dict = {}
    profiles: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        h.require_tools()
        jobs = {}
        src = RUNS / "SINE441.SND"
        RUNS.mkdir(parents=True, exist_ok=True)
        src.write_bytes(snd("SINE441", sine441()))
        for bios in h.BIOS_316:
            profile = h.payload("316", bios)
            cls.profiles[bios] = profile
            runs = RUNS / profile.label
            runs.mkdir(parents=True, exist_ok=True)
            profile.record(RUNS)
            jobs[(bios, "view")] = (profile, runs, dict(
                times=VIEW_TIMES, events=view_events(profile), files=[(src, "SINE441.SND")],
                parts=["wave_zones", "image"],
                env={"SNDDUMP_PCM": "0", "IMAGE316_AT": ",".join(map(str, VIEW_DUMPS)),
                     "IMAGE316_WATCH_FROM": "31.0"}))
            jobs[(bios, "song")] = (profile, runs, dict(
                times=SONG_TIMES, events=song_events(), parts=["image"],
                env={"IMAGE316_AT": ",".join(map(str, SONG_DUMPS)), "IMAGE316_WATCH_FROM": "31.0"}))

        def go(key, job):
            profile, runs, spec = job
            return h.run_case(profile, runs, key[1], snapshot=False, **spec)    # the boot is under test
        cls.results = h.run_parallel(jobs, go)

    def each(self, case: str):
        for bios in h.BIOS_316:
            self.assertIn((bios, case), self.results, f"{case} did not run on {bios}")
            profile = self.profiles[bios]
            yield bios, profile, RUNS / profile.label / case, self.results[(bios, case)]

    # ---------------------------------------------------------------- view

    def test_banner_and_timeline(self):
        for bios, _, _, screens in self.each("view"):
            with self.subTest(bios=bios):
                s = {t: text(x) for t, x in zip(VIEW_TIMES, screens)}
                raw = screens[VIEW_TIMES.index(31.5)]["rows"]               # spaces print as "."
                self.assertEqual(raw[3], "." * 7 + "WAVEFORM/ZONES/MUTE.GROUP" + "." * 8)   # cave banner316
                self.assertEqual(raw[4], "." * 12 + "PMONEY.BETA.1.0" + "." * 13)
                self.assertIn("Searching SCSI", s[32.6])
                self.assertIn("Play/Record", s[34.0].splitlines()[0])
                self.assertIn("Load/Erase/Rename", s[38.5])
                self.assertIn("File:SINE441 SND", s[38.5])
                self.assertIn("Free(snd)", s[44.5])
                self.assertIn("Edit Snd:SINE441", s[48.0])
                self.assertIn("mode=32", screens[VIEW_TIMES.index(V)]["head"])
                self.assertIn("Edit Snd:SINE441", s[54.5])          # Soft Key 4 left the view
                self.assertNotIn("mode=32", screens[VIEW_TIMES.index(54.5)]["head"])

    def test_wave_view_matches_reference(self):
        for bios, _, d, _ in self.each("view"):
            with self.subTest(bios=bios):
                pixels = h.lcd_pixels(d)[f"{V:.3f}"]
                self.assertEqual(pixels, wave_ref.screen(sine441(), "SINE441",
                                                         wave_ref.View([0, 55125, 0, 55125 // 16])))
                zones = h.zone_rows(d)[V]
                self.assertEqual((zones["valid"], zones["current"], zones["count"], zones["sel"]),
                                 (1, 1, 16, 0))
                self.assertEqual(zones["bounds"], [55125 * i // 16 for i in range(17)])
                record = h.sound_records(d, V)[0]
                self.assertEqual((record["name"], record["length"]), ("SINE441", 55125))

    def test_mute_groups_open_and_soft_key_4_returns(self):
        for bios, _, d, screens in self.each("view"):
            with self.subTest(bios=bios):
                s = {t: x for t, x in zip(VIEW_TIMES, screens)}
                self.assertIn("0 Mute groups", text(s[56.5]))
                self.assertIn("mode=32", s[59.0]["head"])
                self.assertNotIn("mode=32", s[61.5]["head"])
                self.assertIn("0 Mute groups", text(s[61.5]))
                self.assertIn("Select option", text(s[61.5]))
                # The page's Note field shows the native note of pad 1, which
                # differs between OSes: stock 3.16's own Select Program shows
                # pad 1 as note 37 (A01) here, where Vailixi's default program
                # has 35.  The mute page must show the same note as 3.16.
                self.assertIn("Select Program", text(s[63.0]))
                self.assertIn("Assign Note:37/A01", text(s[64.5]))
                self.assertEqual(h.lcd_pixels(d)["59.000"], mute_page(37))

    def test_cave_home_and_pool_end_in_physical_memory(self):
        for bios, profile, d, _ in self.each("view"):
            with self.subTest(bios=bios):
                L = profile.load_segment
                self.assertEqual(profile.cave_phys, 0x300000 + L * 16 + 0x7E000)
                rows = image_rows(d)
                self.assertEqual(sorted(rows), VIEW_DUMPS)
                for t, row in rows.items():
                    self.assertEqual(row["xa"], 1, t)
                    self.assertEqual(row["cave_pgr"], profile.cave_phys, t)     # live PGR agrees
                    self.assertEqual(row["pool_opcode"], 0xBB, t)               # MOV BX,imm16
                    self.assertEqual(row["pool_imm"], 0x68FF if L == 0x6900 else 0x6FFF, t)
                # At Play/Record, before any key reached the cave, its home is
                # byte for byte the loader simulation (relocated words, entry
                # copy).  Later its variables change, so only this dump is exact.
                home = profile.cave_home_image()
                ram = (d / f"cave_{h.label(VIEW_DUMPS[0])}.bin").read_bytes()
                self.assertEqual(len(ram), len(home))
                diff = [i for i in range(len(home)) if ram[i] != home[i]]
                self.assertEqual(diff, [], "cave home differs from the loader simulation")

    # ---------------------------------------------------------------- song

    def test_song_after_recording_and_later_keys(self):
        for bios, _, _, screens in self.each("song"):
            with self.subTest(bios=bios):
                s = {round(t, 3): text(x) for t, x in zip(SONG_TIMES, screens)}
                self.assertIn("Seq: 1-(unused)", s[34.5])
                for want in ("Record Ready", "Seq: 1-SEQ01", "Bars:  2"):
                    self.assertIn(want, s[round(REC + 0.7, 3)])
                self.assertIn("Trk: 1-TRK01", s[round(REC + 15.3, 3)])
                self.assertIn("(00:00:3", s[round(STOP + 0.7, 3)])
                for t in (SONG + 0.6, SONG + 1.5):
                    self.assertIn("Song Mode", s[round(t, 3)].splitlines()[0])
                    self.assertIn("<Ins/Del>", s[round(t, 3)])
                self.assertIn("Play/Record", s[round(SONG + 2.6, 3)].splitlines()[0])
                self.assertIn("Seq: 1-SEQ01", s[round(SONG + 2.6, 3)])
                for t in (SONG + 4.6, SONG + 6.0):
                    self.assertIn("Save to Disk", s[round(t, 3)].splitlines()[0])

    def test_song_leaves_image_head_intact(self):
        for bios, profile, d, _ in self.each("song"):
            with self.subTest(bios=bios):
                image = profile.relocated_image()[:HEAD]
                for t, row in image_rows(d).items():
                    self.assertEqual(row["pool_imm"], min(profile.load_segment - 1, 0x6FFF), t)
                    ram = (d / f"head_{h.label(t)}.bin").read_bytes()
                    self.assertEqual(len(ram), HEAD)
                    outside = [i for i in range(HEAD) if not HOOK[0] <= i < HOOK[1] and ram[i] != image[i]]
                    self.assertEqual(outside, [], f"t={t}: image bytes changed outside the hook")
                    self.assertEqual(ram[HOOK[0]:HOOK[1]], image[HOOK[0]:HOOK[1]], t)
                # No CPU write reached image offsets 0..6FFF after 3.16 started.
                self.assertEqual(image_rows(d)[SONG_DUMPS[-1]]["writes"], 0,
                                 (d / "image316_writes.log").read_text()[:2000])

    def test_view_run_writes_no_image_head(self):
        for bios, _, d, _ in self.each("view"):
            with self.subTest(bios=bios):
                self.assertEqual(image_rows(d)[VIEW_DUMPS[-1]]["writes"], 0,
                                 (d / "image316_writes.log").read_text()[:2000])


if __name__ == "__main__":
    unittest.main()
