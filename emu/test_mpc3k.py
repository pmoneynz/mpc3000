"""Boot regressions for the patched MAME mpc3000 driver.

Run: python3 -m unittest emu.test_mpc3k -v   (from the repo root)

Skipped, not failed, when the MAME binary (MPC3K_MAME), nasm or mtools is
missing: see emu/README.md for the pinned MAME build.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from emu.mpc3k import BUILD, M3K316, MAME, REPO, disk, run
from emu.panel import dial, key_tap, write_smf
from emu.seqmem import LAYOUT, offsets, parse, pool
from emu import wave_ref
from emu.snd import disk as snd_disk, sine441, snd, stereo1

RUNS = BUILD / "emu" / "tests"
MODS = BUILD / "mods"
CANARY = MODS / "vailixi350-canary.img"
MOD350 = MODS / "MOD350.img"
PETER = MODS / "PETER.img"
CAVEDEMO = MODS / "CAVEDEMO.img"
WAVE_START, WAVE_END = 13781, 48000   # mid-sine .. mid-ramp of SINE441
LUA = REPO / "emu" / "lua"
PHOTO_REF = REPO / "emu" / "font" / "photo_play_record.txt"

MAIN_SCREEN = "============= Play/Record =============="
RESERVED_K = 132


def missing_tools() -> list[str]:
    missing = [] if MAME.is_file() else [f"MAME binary {MAME} (set MPC3K_MAME)"]
    return missing + [t for t in ("nasm", "mformat", "mcopy") if shutil.which(t) is None]


def floppy_316() -> Path:
    return disk("m3k316", [(M3K316, "M3K316.SYS")])


def loader_disks() -> dict[str, Path]:
    """Floppy loader contract (notes/floppy_loader.md): any 8.3 name with
    extension SYS; first SYS in directory order only; non-MZ is fatal."""
    RUNS.mkdir(parents=True, exist_ok=True)
    bad, txt = RUNS / "not_mz.bin", RUNS / "readme.txt"
    bad.write_bytes(b"X" * 2048)
    txt.write_bytes(b"not a startup file\n")
    return {
        "ld_rename": disk("ld_rename", [(M3K316, "ZZMOD.SYS")]),
        "ld_good_first": disk("ld_good_first", [(M3K316, "ZZMOD.SYS"), (bad, "AAA.SYS")]),
        "ld_bad_first": disk("ld_bad_first", [(bad, "AAA.SYS"), (M3K316, "M3K316.SYS")]),
        "ld_no_sys": disk("ld_no_sys", [(txt, "README.TXT")]),
    }


def snd_disks() -> dict[str, Path]:
    """One synthetic sound per disk: <Load> takes the first file (notes/waveform_phase0.md §3)."""
    RUNS.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, name, planes in (("snd_mono", "SINE441", sine441()), ("snd_stereo", "STEREO1", stereo1())):
        src = RUNS / f"{name}.SND"
        src.write_bytes(snd(name, planes))
        out[key] = snd_disk(key, [(src, f"{name}.SND")])
    src = RUNS / "WAVE.SND"
    src.write_bytes(snd("SINE441", sine441(), start=WAVE_START, end=WAVE_END))
    out["wave_engine"] = snd_disk("wave_engine", [(MODS / "WAVETEST.SYS", "WAVETEST.SYS"), (src, "SINE441.SND")])
    return out


def text(screen: dict) -> str:
    return "\n".join(screen["rows"])


def free_k(screen: dict) -> int:
    row = next(r for r in screen["rows"] if "(SET,SND,ST1,PGM,APS)" in r)
    return int(row.split(":")[-1].rstrip("K").lstrip(". "))


CASES = {
    **{f"bios_{b}": dict(bios=b, times=[45]) for b in ("vailixi", "default", "v311", "v308")},
    "seq_350": dict(bios="vailixi", times=[15], words=offsets(*LAYOUT["3.50"])),
    **{f"mem_{b}_{s}": dict(bios="vailixi", times=[10], board_mb=b, simm_mb=s)
       for b, s in ((2, 0), (2, 1), (2, 4), (8, 0), (8, 1), (8, 4), (32, 0))},
    "smpte_on": dict(bios="vailixi", times=[10], smpte=True),
    "canary": dict(bios="vailixi", times=[12], floppy=CANARY),
    # 3.16 is floppy-only (not a BIOS). 3.12 EPROM is the loader; SCSI
    # search after the overlay needs Cancel (soft 4) or ~60 s.
    "os316": dict(bios="default", times=[15, 30, 60], floppy=None, panel=[
        key_tap("soft4", 33)], words=offsets(*LAYOUT["3.16"])),
    **{f"os316_{b}": dict(bios=b, times=[15, 30], floppy=None) for b in ("vailixi", "v311", "v308")},
    **{n: dict(bios="vailixi", times=[30], floppy=None)
       for n in ("ld_rename", "ld_good_first", "ld_bad_first", "ld_no_sys")},
    # Patched 3.50 relocated to RAM by mods/build_mod_sys.py (MODDING_HOWTO.md).
    "mod350": dict(bios="vailixi", times=[17, 67.5], floppy=MOD350,
                   press=[(65.0, "Y7", "Rec", 0.3), (65.1, "Y7", "Play", 0.1)]),
    "mod350_on312": dict(bios="default", times=[20], floppy=MOD350),
    "mod_peter": dict(bios="vailixi", times=[5, 17], floppy=PETER),
    "mod_cavedemo": dict(bios="vailixi", times=[17], floppy=CAVEDEMO,
                         extra=["-autoboot_script", str(LUA / "cave_watch.lua")]),
    # Waveform phase 0: load a synthetic SND (Disk, 7, <Load>), open Edit Sound (6).
    **{n: dict(bios="vailixi", times=[60], floppy=None, extra=["-autoboot_script", str(LUA / "snddump.lua")],
               press=[(45.0, "Y0", "Disk", 0.1), (46.5, "Y0", "7", 0.1), (48.5, "Y3", "Soft Key 1", 0.1),
                      (57.0, "Y0", "Program/Sounds", 0.1), (58.5, "Y1", "6", 0.1)])
       for n in ("snd_mono", "snd_stereo")},
    # Wave engine (mods/WAVETEST.args): Route A boot, load, Edit Sound, Best st -> wave view,
    # Program/Sounds -> back to Edit Sound.
    "wave_engine": dict(bios="vailixi", times=[77, 80, 84], floppy=None, press=[
        (62.0, "Y0", "Disk", 0.1), (63.5, "Y0", "7", 0.1), (65.5, "Y3", "Soft Key 1", 0.1),
        (74.0, "Y0", "Program/Sounds", 0.1), (75.5, "Y1", "6", 0.1), (77.5, "Y3", "Soft Key 2", 0.1),
        (82.0, "Y0", "Program/Sounds", 0.1)]),
    # Code cave: stock EPROM boot and Route A, each visiting Edit Sound, both graphic mixers, Disk, Other.
    **{n: dict(bios="vailixi", times=[t + 22], floppy=f, extra=["-autoboot_script", str(LUA / "cave_watch.lua")],
               press=[(t + 2 * i, port, key, 0.1) for i, (port, key) in enumerate((
                   ("Y0", "Program/Sounds"), ("Y1", "6"), ("Y6", "Main Screen"), ("Y0", "Mixer/Effects"),
                   ("Y2", "1"), ("Y6", "Main Screen"), ("Y0", "Mixer/Effects"), ("Y2", "2"),
                   ("Y6", "Main Screen"), ("Y0", "Disk"), ("Y1", "Other")))])
       for n, f, t in (("cave_stock", None, 46.0), ("cave_mod", MOD350, 62.0))},
    # Panel link, injected frames (midiin3) and the driver HLE (MAME input fields).
    "link_disk": dict(bios="vailixi", times=[46.5], panel=[key_tap("disk", 45)]),
    "link_dial": dict(bios="vailixi", times=[46.5], panel=[dial(2, 45), dial(-1, 45.5)]),
    "link_locate": dict(bios="vailixi", times=[50.5], panel=[
        key_tap("rec", 45), key_tap("play", 46), key_tap("stop", 49), key_tap("forward_bar", 50)]),
    "hle_rec_play": dict(bios="vailixi", times=[47.5],
                         press=[(45.0, "Y7", "Rec", 0.3), (45.1, "Y7", "Play", 0.1)]),
    "hle_pad13": dict(bios="vailixi", times=[47.0],
                      press=[(45.0, "Y1", "16 Levels", 0.1), (46.0, "PB3", "Crash", 0.1)]),
}


class Mpc3kBoot(unittest.TestCase):
    results: dict[str, list[dict]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if missing := missing_tools():
            raise unittest.SkipTest("emulator tests need: " + ", ".join(missing))
        for args in (["build_mod_sys.py"], ["build_canary.py"], ["build_mod_sys.py", "@mods/PETER.args"],
                     ["build_mod_sys.py", "@mods/CAVEDEMO.args"], ["build_mod_sys.py", "@mods/WAVETEST.args"]):
            subprocess.run([sys.executable, str(REPO / "mods" / args[0]), *args[1:]], cwd=REPO,
                           check=True, capture_output=True)
        disks = {"os316": floppy_316(), **loader_disks(), **snd_disks()}
        for name in CASES:
            key = "os316" if name.startswith("os316") else name
            if key in disks:
                CASES[name]["floppy"] = disks[key]

        def go(item):
            name, kw = item
            kw = dict(kw)
            if "panel" in kw:
                RUNS.mkdir(parents=True, exist_ok=True)
                kw["panel"] = write_smf(RUNS / f"{name}.mid", [e for ev in kw["panel"] for e in ev])
            return name, run(kw.pop("bios"), kw.pop("times"), RUNS / name, **kw)

        with ThreadPoolExecutor(max_workers=8) as pool:
            cls.results = dict(pool.map(go, CASES.items()))

    def test_every_rom_os_reaches_play_record(self) -> None:
        for bios in ("vailixi", "default", "v311", "v308"):
            with self.subTest(bios=bios):
                self.assertEqual(self.results[f"bios_{bios}"][-1]["rows"][0].replace(".", " "),
                                 MAIN_SCREEN)

    def test_sound_memory_matches_documented_configs(self) -> None:
        for board, simm in ((2, 0), (2, 1), (2, 4), (8, 0), (8, 1), (8, 4), (32, 0)):
            with self.subTest(board=board, simm=simm):
                total_mb = board + (2 * simm if board != 32 else 0)
                self.assertEqual(free_k(self.results[f"mem_{board}_{simm}"][-1]),
                                 total_mb * 1024 - RESERVED_K)

    def test_smpte_line_only_with_option(self) -> None:
        self.assertNotIn("I-0055", text(self.results["mem_2_0"][-1]))
        self.assertIn("(I-0055 OPTION......):Active", text(self.results["smpte_on"][-1]))

    def test_floppy_canary_prints_351(self) -> None:
        self.assertIn("Vailixi 3.51 (---/--/----)", text(self.results["canary"][-1]))

    def test_floppy_os_316_loads_via_disk_not_eprom(self) -> None:
        s15, s30, s60 = self.results["os316"]
        self.assertIn("Loading files", text(s15))
        self.assertIn("Version.3.12.(03/24/97)", text(s15))
        self.assertIn("System.3.16.(02/20/05)", text(s30))
        self.assertIn("Play/Record", s60["rows"][0])
        self.assertNotIn("3.16", text(self.results["bios_default"][-1]))

    def test_every_eprom_os_boots_316_from_floppy(self) -> None:
        for bios in ("vailixi", "v311", "v308"):
            with self.subTest(bios=bios):
                s15, s30 = self.results[f"os316_{bios}"]
                self.assertIn("Loading files", s15["rows"][7])
                self.assertIn("System.3.16.(02/20/05)", text(s30))

    def test_floppy_loader_file_selection(self) -> None:
        loaded, fatal = "System.3.16.(02/20/05)", "Sorry,.but.a.software.bug.of.type.11h"
        for name in ("ld_rename", "ld_good_first"):
            with self.subTest(disk=name):
                self.assertIn(loaded, text(self.results[name][-1]))
        self.assertIn(fatal, text(self.results["ld_bad_first"][-1]))
        no_sys = self.results["ld_no_sys"][-1]
        self.assertIn("Searching SCSI", no_sys["rows"][7].replace(".", " "))
        self.assertNotIn("3.16", text(no_sys))

    def test_patched_350_boots_from_floppy_and_takes_input(self) -> None:
        banner, main = self.results["mod350"]
        self.assertIn("Vailixi.3.51.(---/--/----)", text(banner))
        self.assertEqual(main["rows"][0], "====== Play/Record (Record Ready) ======")
        self.assertIn("Mod needs Vailixi 3.50 EPROMs", text(self.results["mod350_on312"][-1]))

    def test_peter_mod_credit_on_version_screen(self) -> None:
        eprom, mod = self.results["mod_peter"]
        self.assertEqual(eprom["rows"][3], ".......--------.--:.-------.--.-........")
        self.assertEqual(mod["rows"][2], ".......Vailixi.3.50.(---/--/----).......")
        self.assertEqual(mod["rows"][3], "..............Mod.by.Peter..............")

    def test_cave_code_runs_from_ram(self) -> None:
        self.assertEqual(self.results["mod_cavedemo"][-1]["rows"][3], ".............Cave.code.ran..............")
        lines = (RUNS / "mod_cavedemo" / "cave.txt").read_text().splitlines()
        counts = dict(line.split() for line in lines[:4])
        self.assertEqual((counts["RF07C8"], counts["WF07C8"]), ("0", "0"))   # EPROM copy never used
        self.assertGreater(int(counts["R3F07C8"]), 0)
        self.assertTrue(any(" F07D:" in line and "R3F07C8" in line for line in lines[4:]))

    def test_wave_engine_pixels_match_reference(self) -> None:
        before, _, after = self.results["wave_engine"]
        blocks = (RUNS / "wave_engine" / "lcd_pixels.txt").read_text().split("@ ")[1:]
        got = next(b.splitlines()[1:65] for b in blocks if b.startswith("80.000"))
        self.assertEqual(got, wave_ref.pixels(sine441()[0], WAVE_START, WAVE_END))
        for row in (0, 2):   # title; soft start handed back unchanged ('.' may stand for space)
            self.assertEqual(after["rows"][row][:20].replace(".", " "), before["rows"][row][:20].replace(".", " "))
        self.assertIn("Soft st :000.312.22", before["rows"][2])

    def test_synthetic_snd_loads_into_wave_ram(self) -> None:
        for name, title, length, planes in (("snd_mono", "Edit Snd:SINE441", "001.250.00", sine441()),
                                            ("snd_stereo", "Edit Snd:STEREO1", "000.750.00", stereo1())):
            with self.subTest(name=name):
                screen = text(self.results[name][-1]).replace(".", " ")
                self.assertIn(title, screen)
                self.assertIn(length.replace(".", " "), screen)
                want = b"".join(struct.pack(f"<{len(p)}h", *p) for p in planes)
                self.assertEqual((RUNS / name / "wave_60_idx0.bin").read_bytes(), want)

    def test_code_cave_never_read(self) -> None:
        for name, copied in (("cave_stock", 0), ("cave_mod", 0x3838 // 2)):
            with self.subTest(name=name):
                counts = dict(line.split() for line in (RUNS / name / "cave.txt").read_text().splitlines()[:4])
                self.assertEqual(counts, {"RF07C8": "0", "WF07C8": "0", "R3F07C8": "0", "W3F07C8": str(copied)})

    def test_sequencer_pool_484k_eprom_439k_floppy_316(self) -> None:
        w350 = parse(RUNS / "seq_350" / "ram_words.log")
        self.assertEqual(pool(w350, *LAYOUT["3.50"])["free_k"], 484)
        self.assertIn("..484K", self.results["seq_350"][-1]["rows"][3])
        w316 = parse(RUNS / "os316" / "ram_words.log")
        self.assertEqual(pool(w316, *LAYOUT["3.16"])["free_k"], 439)

    def test_panel_link_frames_drive_the_os(self) -> None:
        self.assertEqual(self.rows("link_disk")[0], "== Save to Disk --   --- Load, Other ===")
        self.assertTrue(self.rows("link_dial")[1].startswith("Seq:.2-"))
        self.assertIn("Now:003.01.00", self.rows("link_locate")[6])

    def test_panel_hle_from_mame_inputs(self) -> None:
        self.assertEqual(self.rows("hle_rec_play")[0], "====== Play/Record (Record Ready) ======")
        self.assertIn("Now:002.01.", self.rows("hle_rec_play")[6])
        self.assertTrue(self.rows("hle_pad13")[1].startswith("Note:47/A13"))

    def rows(self, name: str) -> list[str]:
        return self.results[name][-1]["rows"]

    def test_lcd_pixels_match_glass_photo(self) -> None:
        ref = [l for l in PHOTO_REF.read_text().splitlines() if not l.startswith(";")]
        emu = (RUNS / "bios_vailixi" / "lcd_pixels.txt").read_text().splitlines()[1:65]
        bad = [(y, x) for y in range(64) for x in range(240)
               if ref[y][x] != "?" and ref[y][x] != emu[y][x]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
