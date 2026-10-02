"""Boot regressions for the patched MAME mpc3000 driver.

Run: python3 -m unittest emu.test_mpc3k -v   (from the repo root)

Skipped, not failed, when the MAME binary (MPC3K_MAME), nasm or mtools is
missing (an error under MPC3K_RELEASE=1): see emu/README.md for the pinned
MAME build.  The WAVE cases use the generic payload that emu.harness builds
from the current sources into a test-private directory; build/mods/WAVE.SYS
is neither read nor rewritten, and the demo payloads (MOD350, canary, PETER,
CAVEDEMO) are built into build/emu/tests-mods.
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from emu import harness
from emu.mpc3k import BUILD, M3K316, MAME, REPO, disk, run
from emu.panel import dial, key_tap, write_smf
from emu.seqmem import LAYOUT, offsets, parse, pool
from emu import wave_ref
from emu.snd import disk as snd_disk, sine441, snd, stereo1

RUNS = BUILD / "emu" / "tests"
# Demo payloads (MOD350, canary, PETER, CAVEDEMO) are built from the current
# sources into a test-private directory; build/mods is never written.
MODS = BUILD / "emu" / "tests-mods"
CANARY = MODS / "vailixi350-canary.img"
MOD350 = MODS / "MOD350.img"
PETER = MODS / "PETER.img"
CAVEDEMO = MODS / "CAVEDEMO.img"
WAVE_START, WAVE_END = 13781, 48000   # mid-sine .. mid-ramp of SINE441
STEREO_START, STEREO_END = 5000, 30000
# Full-view wheel step len/240 = 0x12345: above bit 15, so the repeat-count
# multiply in `step` (mods/wave.asm) needs its high-word product and carry.
LONG_STEP = 0x12345
LONG_FRAMES = 240 * LONG_STEP
LONG_BURST = 3                  # wheel events per burst (coalesced 1 + 2)
LUA = REPO / "emu" / "lua"
PHOTO_REF = REPO / "emu" / "font" / "photo_play_record.txt"

MAIN_SCREEN = "============= Play/Record =============="
RESERVED_K = 132


def missing_tools() -> list[str]:
    return harness.missing_tools()


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


def snd_disks(profile: harness.Profile) -> dict[str, Path]:
    """One synthetic sound per disk: <Load> takes the first file (notes/waveform_phase0.md §3)."""
    RUNS.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, name, planes in (("snd_mono", "SINE441", sine441()), ("snd_stereo", "STEREO1", stereo1())):
        src = RUNS / f"{name}.SND"
        src.write_bytes(snd(name, planes))
        out[key] = snd_disk(key, [(src, f"{name}.SND")])
    src = RUNS / "WAVE.SND"
    src.write_bytes(snd("SINE441", sine441(), start=WAVE_START, end=WAVE_END))
    out["wave_view"] = harness.wave_disk(profile, "wave_view", [(src, "SINE441.SND")])
    src = RUNS / "WAVEST.SND"
    src.write_bytes(snd("STEREO1", stereo1(), start=STEREO_START, end=STEREO_END))
    out["wave_stereo"] = harness.wave_disk(profile, "wave_stereo", [(src, "STEREO1.SND")])
    src = RUNS / "EDGE.SND"
    src.write_bytes(snd("EDGE", [[12345]]))
    out["wave_edges"] = harness.wave_disk(profile, "wave_edges", [(src, "EDGE.SND")])
    out["wave_no_sound"] = harness.wave_disk(profile, "wave_no_sound")
    return out


def wave_edge_script(profile: harness.Profile, runs: Path | None = None) -> Path:
    """Inject a long length after the initial one-sample full scan.

    A poke is unavoidable here: no loadable sound reaches the 17.9 M-frame
    length whose wheel step exceeds 16 bits, and the stock loader cannot
    produce a zero-length record (D0C0:0611 clamps +1C to 441).  So the probe
    writes the record's end/len and the cave's cached `len`, and the test
    asserts only what the firmware computes from them: the start point after
    real wheel bursts (step * coalesced repeat count, 32-bit), the empty-view
    pixels and the stock page text.  It never asserts the values it wrote.
    The full-view cache keeps the wheel from copying 34 MiB of wave RAM.
    """
    runs = runs or RUNS
    len_off = profile.symbols()["len"]
    path = harness.observer(profile, runs / "wave_edges.lua", ["repeat_watch"])
    lines = path.read_text().splitlines()
    edge = f"""do
local machine = manager.machine
local cpu = machine.devices[\":maincpu\"]
local iosp = cpu.spaces[\"io\"]
local prog = cpu.spaces[\"program\"]
local out = os.getenv(\"PROBE_OUT\") or \".\"
local function phys(seg, off)
    local a = ((seg << 4) + off) & 0xfffff
    if cpu.state[\"XA\"].value ~= 0 then
        return ((iosp:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
    end
    return a
end
local function rd8(seg, off) return prog:read_u8(phys(seg, off)) end
local function rd32(seg, off)
    return rd8(seg, off) | (rd8(seg, off + 1) << 8) |
           (rd8(seg, off + 2) << 16) | (rd8(seg, off + 3) << 24)
end
local function wr32(seg, off, value)
    for i = 0, 3 do prog:write_u8(phys(seg, off + i), (value >> (8 * i)) & 0xff) end
end
local injected, captured, saved = false, false, false
emu.register_periodic(function()
    local now = machine.time:as_double()
    if not injected and now >= 80.5 then
        wr32(0xa2ae, 0x4818, {LONG_FRAMES})
        wr32(0xa2ae, 0x481c, {LONG_FRAMES})
        wr32(0xf07d, 0x{len_off:x}, {LONG_FRAMES})
        injected = true
    end
    if injected and not captured and now >= 82.5 then
        local f = assert(io.open(out .. \"/wave_edges.txt\", \"w\"))
        f:write(string.format(\"after_plus=%u\\n\", rd32(0xa2ae, 0x4814)))
        f:close()
        captured = true
    end
    if injected and not saved and now >= 85.0 then
        local f = assert(io.open(out .. \"/wave_edges.txt\", \"a\"))
        f:write(string.format(\"after_minus=%u\\n\", rd32(0xa2ae, 0x4814)))
        f:close()
        wr32(0xa2ae, 0x4814, 0)
        wr32(0xa2ae, 0x4818, 0)
        wr32(0xa2ae, 0x481c, 0)
        saved = true
    end
end)
wave_edges_keep = true
end"""
    path.write_text("\n".join(lines[:-1] + edge.splitlines() + lines[-1:]) + "\n")
    return path


def private_floppy(case: str, image: Path) -> Path:
    """A per-case copy: MAME mounts -flop read/write, so parallel cases that
    named one shared image (the four os316 cases, the MOD350 cases) must not
    share the file."""
    copy = RUNS / "floppies" / f"{case}.img"
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image, copy)
    return copy


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
    # V53 wait control, programmed by the reset stub at file 0x7FF00.
    "wcu": dict(bios="vailixi", times=[2], extra=["-autoboot_script", str(LUA / "wcu_dump.lua")]),
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
    # Wave view (mods/WAVE.args), SINE441 with soft start/end set: Help -> view; wheel +3 (Start);
    # Soft Key 3 fine; wheel +2; Up (zoom 8); Soft Key 2 zone; Right (zone end); wheel +5;
    # Soft Key 3 full; Soft Key 4 -> Edit Sound; then Help on Play/Record is still Help.
    "wave_view": dict(bios="vailixi", times=[77, 80, 82.5, 84.5, 86.5, 88.5, 90.5, 92.5, 94.5, 96.5, 100, 103],
                      floppy=None, press=[(t, port, key, 2.0 if t == 102 else 0.1) for t, port, key in (
                          (62, "Y0", "Disk"), (63.5, "Y0", "7"), (65.5, "Y3", "Soft Key 1"),
                          (74, "Y0", "Program/Sounds"), (75.5, "Y1", "6"), (77.5, "Y6", "Help"),
                          (83, "Y4", "Soft Key 3"), (87, "Y5", "Up Arrow"), (89, "Y3", "Soft Key 2"),
                          (91, "Y5", "Right Arrow"), (95, "Y4", "Soft Key 3"), (97, "Y4", "Soft Key 4"),
                          (101, "Y6", "Main Screen"), (102, "Y6", "Help"))],
                      panel=[dial(3, 81.0), dial(2, 85.0), dial(5, 93.0)]),
    # View field on a stereo sound: Help; Right, Right (View); wheel + (R); Left (End); Soft Key 3; Soft Key 4.
    "wave_stereo": dict(bios="vailixi", times=[80, 83, 85, 87, 89.5, 94], floppy=None,
                        press=[(t, port, key, 0.1) for t, port, key in (
                            (62, "Y0", "Disk"), (63.5, "Y0", "7"), (65.5, "Y3", "Soft Key 1"),
                            (74, "Y0", "Program/Sounds"), (75.5, "Y1", "6"), (77.5, "Y6", "Help"),
                            (81, "Y5", "Right Arrow"), (82, "Y5", "Right Arrow"), (86, "Y5", "Left Arrow"),
                            (88, "Y4", "Soft Key 3"), (91, "Y4", "Soft Key 4"))],
                        panel=[dial(1, 84.0)]),
    # A real sound record, mutated after the first cheap full scan: wheel + must use
    # the unsigned 32-bit len/240 step. Main Screen leaves the mode; reopen with an
    # empty length must render safely and Soft Key 4 must return to Edit Sound.
    "wave_edges": dict(bios="vailixi", board_mb=32, times=[79.5, 86, 94, 98], floppy=None,
                       press=[(t, port, key, 0.1) for t, port, key in (
                           (62, "Y0", "Disk"), (63.5, "Y0", "7"), (65.5, "Y3", "Soft Key 1"),
                           (74, "Y0", "Program/Sounds"), (75.5, "Y1", "6"), (77.5, "Y6", "Help"),
                           (84, "Y6", "Main Screen"), (88, "Y0", "Program/Sounds"),
                           (89.5, "Y1", "6"), (91, "Y6", "Help"), (96, "Y4", "Soft Key 4"))],
                       panel=[harness.burst(LONG_BURST, 82.0), harness.burst(-LONG_BURST, 83.0)]),
    # Help on Edit Sound with DI=-1 must remain on the stock no-sounds page.
    "wave_no_sound": dict(bios="vailixi", times=[74, 77], floppy=None,
                          press=[(68, "Y0", "Program/Sounds", 0.1), (70, "Y1", "6", 0.1),
                                 (75, "Y6", "Help", 0.1)]),
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
        harness.require_tools()
        MODS.mkdir(parents=True, exist_ok=True)
        for args in ([], ["@mods/PETER.args"], ["@mods/CAVEDEMO.args"]):
            subprocess.run([sys.executable, str(REPO / "mods/build_mod_sys.py"), *args,
                            "--out", str(MODS)], cwd=REPO, check=True, capture_output=True)
        subprocess.run([sys.executable, "-c", "import sys; from pathlib import Path; "
                        "sys.path.insert(0, 'mods'); import build_canary; "
                        "sys.exit(build_canary.main(Path(sys.argv[1])))", str(MODS)],
                       cwd=REPO, check=True, capture_output=True)
        profile = harness.payload("generic")
        profile.record(RUNS)
        CASES["wave_edges"]["extra"] = ["-autoboot_script", str(wave_edge_script(profile))]
        disks = {"os316": floppy_316(), **loader_disks(), **snd_disks(profile)}
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
            if kw.get("floppy") is not None:
                kw["floppy"] = private_floppy(name, kw["floppy"])
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

    def test_reset_stub_wait_states_take_effect(self) -> None:
        # notes/emulator.md section 7: 1 wait on all memory, 3 on external I/O and DMA, refresh N=17.
        regs = dict(line.split("=") for line in (RUNS / "wcu" / "wcu.txt").read_text().split())
        self.assertEqual(regs, {"FFEA": "07", "FFEB": "11", "FFEC": "02", "FFED": "00", "FFF2": "90",
                                "FFF3": "00", "FFF4": "11", "FFF5": "31", "FFF6": "31"})
        # BIOS LCD init (F800:186C IR=00) runs at 0.0750 s with zero waits, 0.0883 s with them.
        first = (RUNS / "wcu" / "lcd_io.log").read_text().split("\n", 1)[0].split()
        self.assertEqual(first[1:3], ["F800:186C", "IR=00"])
        self.assertGreater(float(first[0]), 0.085)

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

    def test_wave_view_edits_trim_and_zone(self) -> None:
        screens = self.results["wave_view"]
        blocks = (RUNS / "wave_view" / "lcd_pixels.txt").read_text().split("@ ")[1:]
        pixels = {b.split()[0]: b.splitlines()[1:65] for b in blocks}
        wave = sine441()[0]
        a3, b = WAVE_START + 3 * (len(wave) // 240), WAVE_END
        View = wave_ref.View
        first_zone_end = len(wave) // 16
        for t, view in (("80.000", View([WAVE_START, b, 0, first_zone_end])), ("82.500", View([a3, b, 0, first_zone_end])),
                        ("84.500", View([a3, b, 0, first_zone_end], fine=True)),
                        ("86.500", View([a3 + 32, b, 0, first_zone_end], fine=True)),
                        ("88.500", View([a3 + 32, b, 0, first_zone_end], fine=True, zoom=8)),
                        ("90.500", View([a3 + 32, b, 0, first_zone_end], sel=2, fine=True, zoom=8)),
                        ("92.500", View([a3 + 32, b, 0, first_zone_end], sel=3, fine=True, zoom=8)),
                        ("94.500", View([a3 + 32, b, 0, first_zone_end + 40], sel=3, fine=True, zoom=8)),
                        ("96.500", View([a3 + 32, b, 0, first_zone_end + 40], sel=3, zoom=8))):
            with self.subTest(t=t):
                self.assertEqual(pixels[t], wave_ref.screen([wave], "SINE441", view))
        before, after, help_screen = screens[0]["rows"], screens[-2]["rows"], screens[-1]["rows"]
        self.assertIn("Soft st :000.312.22", before[2])
        self.assertIn(f"Soft st :{wave_ref.fmt(a3 + 32)}", after[2])
        self.assertIn(f"Soft end:{wave_ref.fmt(b)}", after[3])
        self.assertIn(f"Zone end:{wave_ref.fmt(first_zone_end + 40)}", after[3])
        self.assertIn("Help", help_screen[0])

    def test_wave_view_field_selects_plane(self) -> None:
        blocks = (RUNS / "wave_stereo" / "lcd_pixels.txt").read_text().split("@ ")[1:]
        pixels = {b.split()[0]: b.splitlines()[1:65] for b in blocks}
        points, View = [STEREO_START, STEREO_END, 0, 0], wave_ref.View
        for t, view in (("80.000", View(points)), ("83.000", View(points, sel=1, onview=True)),
                        ("85.000", View(points, sel=1, onview=True, plane=1)),
                        ("87.000", View(points, sel=1, plane=1)),
                        ("89.500", View(points, sel=1, plane=1, fine=True))):
            with self.subTest(t=t):
                self.assertEqual(pixels[t], wave_ref.screen(stereo1(), "STEREO1", view))
        after = self.results["wave_stereo"][-1]["rows"]
        self.assertIn("(ST)", after[0])
        self.assertIn(f"Soft st :{wave_ref.fmt(STEREO_START)}", after[2])

    def test_wave_view_long_step_empty_sound_and_mode_exits(self) -> None:
        state = dict(field.split("=") for field in
                     (RUNS / "wave_edges" / "wave_edges.txt").read_text().split())
        # Firmware-computed only: LONG_BURST wheel steps of len/240 = 0x12345
        # each (step > 16 bits; coalesced, so count * step crosses words),
        # then the same burst back to zero.
        self.assertEqual(state, {"after_plus": str(LONG_BURST * LONG_STEP), "after_minus": "0"})
        counts = harness.repeats(RUNS / "wave_edges", start=81.9, end=83.9)
        self.assertEqual(sum(counts), 2 * LONG_BURST, counts)
        self.assertGreater(max(counts), 1, counts)

        screens = self.results["wave_edges"]
        self.assertEqual(screens[1]["rows"][0].replace(".", " "), MAIN_SCREEN)
        self.assertIn("Edit Snd:EDGE", screens[-1]["rows"][0])
        self.assertIn("Length:000.000.00", screens[-1]["rows"][4])

        blocks = (RUNS / "wave_edges" / "lcd_pixels.txt").read_text().split("@ ")[1:]
        pixels = {b.split()[0]: b.splitlines()[1:65] for b in blocks}
        self.assertEqual(pixels["94.000"], wave_ref.screen([[]], "EDGE", wave_ref.View([0, 0, 0, 0])))

    def test_wave_view_help_is_safe_when_there_are_no_sounds(self) -> None:
        before, after = self.results["wave_no_sound"]
        self.assertIn("Edit Snd:(no sounds)", before["rows"][0])
        self.assertEqual(after["rows"], before["rows"])
        self.assertIn("40x8", after["head"])

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
