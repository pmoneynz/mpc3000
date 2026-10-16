"""Regression tests for the stock-OS-3.16 bug fixes carried by PMONEY.

Run:  python3 -m unittest emu.test_stock316_bugs -v
      MPC3K_MAME=.../mpc3k   (the emulator);  MPC3K_WORKERS caps concurrency (<=2 advised)

Each test boots the built PMONEY payload (emu.harness.payload("316"),
WAVE316.SYS with mods/bugfix316.inc) in MAME and asserts the fixed behaviour;
several also boot the unmodified M3K316.SYS to show the stock bug is present.
The loader cases reuse the fuzzer's boot-snapshot driver and read-only oracle
(emu.fuzz_loaders), so a MAME run is one load from Play/Record.  See
notes/port_316.md and polish/stock_bugs/report.md.

Bugs covered: F1 bad-version SND (no freeze), F2 PGM/APS error text, F3 Mixer
Soft Key 2 stack, F4 nearly-full-floppy Save a Sound, F5 SET note index,
C1/C3 corrupt-PGM name overflow + dangling pad on the next pad hit, C2
SND/SET header geometry.
"""
from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path

from emu import fuzz_loaders as fz
from emu import harness as h
from emu.mpc3k import parse_screens, run
from emu.panel import key_tap, pad_hit, panel_pad, write_smf
from emu.snd import sine, snd

MAME_OK = fz.M3K316.is_file() and Path(os.environ.get("MPC3K_MAME", "/nonexistent")).exists()
WORKERS = min(2, int(os.environ.get("MPC3K_WORKERS", "2")))
BIOS = os.environ.get("MPC3K_BUG_BIOS", "v311")          # L=7000h: stock pool does not overlap its image


def payload_sys() -> Path:
    """The built PMONEY WAVE316.SYS (fixes included).  MPC3K_FIX_SYS overrides the
    path (used to validate against a scratch build before the fixes are merged)."""
    override = os.environ.get("MPC3K_FIX_SYS")
    return Path(override) if override else h.payload("316", BIOS).sys


def runner(tag: str, sys_path: Path) -> fz.Runner:
    out = (fz.OUT.parent / "stock316-bugs" / tag)
    return fz.Runner(out.resolve(), bios=BIOS, sys_path=sys_path.resolve())


def snd_bytes(name: str, frames: int = 2205, *, version: int = 2, magic: int = 1,
              start: int = 0, end: int | None = None, length: int | None = None,
              stereo: int = 0) -> bytes:
    planes = [sine(frames)] * (stereo + 1)
    b = bytearray(snd(name, planes))
    b[0] = magic
    b[1] = version
    if end is not None:
        struct.pack_into("<I", b, 2 + 0x18, end)
    if length is not None:
        struct.pack_into("<I", b, 2 + 0x1C, length)
    struct.pack_into("<I", b, 2 + 0x14, start)
    b[2 + 0x13] = stereo
    return bytes(b)


@unittest.skipUnless(MAME_OK, "needs MPC3K_MAME and M3K316.SYS")
class StockBugs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fix = payload_sys()
        cls.r_fix = runner("fix", cls.fix)
        cls.r_stock = runner("stock", fz.M3K316)
        cls.fmts = fz.formats(fz.FIXTURES)
        cls.mask = fz.load_mask(cls.r_fix.out)

    def verdict(self, res):
        return fz.classify(res, self.mask)

    # ---- helpers -------------------------------------------------------
    def load_case(self, r: fz.Runner, name: str, ext: str, data: bytes):
        return r.case(name, self.fmts[ext], data)

    # ---- F1 ------------------------------------------------------------
    def test_f1_bad_version_snd_does_not_freeze(self):
        bad = snd_bytes("VERTEST", version=3)
        fix = self.load_case(self.r_fix, "f1-fix", "SND", bad)
        o = fix["oracle"]
        self.assertEqual(o["busy_load"], 0, "BUSY left incremented -> playback freeze")
        self.assertNotEqual(o["port6a"], 0, "outputs left muted")
        self.assertEqual(o["badpc"], [], "execution ran off (crash)")
        # Stock shows the freeze: BUSY stuck non-zero after the load.
        stock = self.load_case(self.r_stock, "f1-stock", "SND", bad)
        self.assertNotEqual(stock["oracle"]["busy_load"], 0,
                            "expected the stock version>=3 BUSY leak")

    # ---- F2 ------------------------------------------------------------
    def test_f2_aps_sound_error_text(self):
        # An APS whose sound directory names the companion FZSND twice: the
        # second load returns "sound name already exists" (a sound/category-2
        # error).  Stock passes it through as a category-1 sequence-memory
        # message; the fix shows the sound text.
        aps = bytearray(self.fmts["APS"].base(fz.FIXTURES))
        n = aps[2]
        names = 7 + 0x13C + n * 0x77E
        aps[names + 17:names + 34] = b"FZSND".ljust(17, b"\0")   # slot 1 duplicates slot 0
        fix = self.r_fix.case("f2-fix", self.fmts["APS"], bytes(aps))
        text = "\n".join("\n".join(s) for s in fix["screens"])
        self.assertNotIn("not enough sequence memory", text.lower().replace(".", " "))
        self.assertTrue(any("already exists" in "\n".join(s) for s in fix["screens"]),
                        "fix should show the sound 'already exists' text")
        stock = self.r_stock.case("f2-stock", self.fmts["APS"], bytes(aps))
        self.assertFalse(any("already exists" in "\n".join(s) for s in stock["screens"]),
                         "stock mis-shows the sound error as a category-1 sequence message")

    # ---- F3 ------------------------------------------------------------
    def test_f3_mixer_softkey2_stack_constant(self):
        sps = mixer_soft2_sps(self.r_fix, "f3-fix", presses=12)
        self.assertTrue(sps, "field editor never ran")
        self.assertEqual(len(set(sps)), 1, f"UI stack descends per press: {sps}")

    # ---- F4 ------------------------------------------------------------
    def test_f4_nearly_full_save_refused_and_unchanged(self):
        refused, before, after = disk_full_save(self.r_fix, "f4-refuse", free=40, frames=10240)
        self.assertIn("F900", refused)
        self.assertEqual(before, after, "a refused save must not touch the disk")
        ok, _, _ = disk_full_save(self.r_fix, "f4-fit", free=48, frames=10240)
        self.assertNotIn("F900", ok, "a sound that fits must still save")

    # ---- F5 ------------------------------------------------------------
    def test_f5_set_note_index_not_dangling(self):
        res = self.load_case(self.r_fix, "f5", "SET", self.fmts["SET"].base(fz.FIXTURES))
        self.assertEqual(res["oracle"]["bad_notes"], [],
                         "a name-lookup miss left a dangling note index (FCh)")

    # ---- C1 / C3 -------------------------------------------------------
    def test_c1_c3_corrupt_pgm_name_no_crash(self):
        base = self.fmts["PGM"].base(fz.FIXTURES)
        data = fz.apply(base, [["fill", 401, 64, 0x80]])       # PGM-15 minimal: unterminated names
        fix = self.load_case(self.r_fix, "c1c3-fix", "PGM", data)
        fv = self.verdict(fix)
        self.assertNotIn("crash", fv, fix["oracle"]["badpc"])
        self.assertNotIn("hang", fv)
        self.assertEqual(fix["oracle"]["bad_notes"], [], "dangling pad after a corrupt PGM")
        self.assertIn("Play/Record", "\n".join(fix["screens"][-1]))
        # Stock crashes (System Error) on the same file.
        stock = self.load_case(self.r_stock, "c1c3-stock", "PGM", data)
        self.assertIn("crash", self.verdict(stock), "expected the stock name-overflow crash")

    # ---- C2 ------------------------------------------------------------
    def test_c2_bad_geometry_snd_clamped(self):
        bad = snd_bytes("GEOM", frames=2205, end=0x7FFFFFFF, length=2205)  # end > length
        fix = self.load_case(self.r_fix, "c2-fix", "SND", bad)
        self.assertEqual(fix["oracle"]["bad_sounds"], [],
                         "end>length geometry left unclamped in the sound record")
        stock = self.load_case(self.r_stock, "c2-stock", "SND", bad)
        self.assertNotEqual(stock["oracle"]["bad_sounds"], [],
                            "expected the stock unclamped geometry")


# --------------------------------------------------------------------------
# Custom panel runs for the two non-loader bugs (F3, F4)


def _boot_disk(r: fz.Runner, files):
    return r._disk("bug-disk", files, startup=False)


def mixer_soft2_sps(r: fz.Runner, tag: str, presses: int) -> list[int]:
    """Press Mixer/Effects 3, Soft Key 2 `presses` times; return the field-editor
    entry SP at each press (constant with the F3 fix, descending without it)."""
    states, lcd, _ = r.snapshot()
    L = r.load_segment
    lua = (f"LOAD_SEG = 0x{L:04X}\n" + r"""
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local out = os.getenv("PROBE_OUT")
local log = assert(io.open(out .. "/sp.log", "w"))
local cs = (LOAD_SEG + 0x02D7) & 0xffff
local p = 0x300000 + ((cs * 16 + 0x0357) & 0xfffff)
sp_tap = prog:install_read_tap(p & ~1, p | 1, "sp", function()
  if machine.time:as_double() < 37 then return end
  local ps = cpu.state["PS"].value
  if ps == cs and ((cpu.state["CURPC"].value - (ps << 4)) & 0xffff) == 0x0357 then
    log:write(string.format("%04X\n", cpu.state["SP"].value)); log:flush()
  end
end)
""")
    d = r.out / tag
    d.mkdir(parents=True, exist_ok=True)
    script = d / "sp.lua"
    script.write_text(lua + f'\ndofile("{(Path(fz.__file__).resolve().parent / "probe.lua").as_posix()}")\n')
    ev = fz._taps((33.0, "soft4"), (35.0, "mixer_effects"), (36.5, "3"))
    ev += fz._taps(*[(38.0 + 0.4 * i, "soft2") for i in range(presses)])
    img = _boot_disk(r, [])
    run(r.bios, [38.0 + 0.4 * presses + 2], d / "mame", floppy=img, rompath=r.rompath,
        panel=write_smf(d / "panel.mid", ev),
        extra=["-autoboot_script", str(script), "-state_directory", str(states), "-state", "boot"],
        env={"PROBE_LCD_SEED": str(lcd), "PROBE_REINSERT": "1"})
    return [int(x, 16) for x in (d / "mame" / "sp.log").read_text().split()]


def disk_full_save(r: fz.Runner, tag: str, free: int, frames: int):
    """Load a sound from a data disk, then Save a Sound onto a target floppy left
    with `free` clusters (two timed disk swaps from the boot snapshot).  Returns
    (last-screen text, target dir+FAT bytes before, after)."""
    from emu import fat12
    from emu.mpc3k import disk as fat_disk
    d = r.out / tag
    d.mkdir(parents=True, exist_ok=True)
    states, lcd, _ = r.snapshot()
    src = d / "BIG.SND"
    src.write_bytes(snd("BIGSND", [sine(frames)]))
    data_img = fat_disk(f"bug-src-{tag}", [(src, "BIG.SND")])
    empty = fat_disk(f"bug-tgt-empty-{tag}", [])
    filler = d / "FILL.BIN"
    filler.write_bytes(bytes(fat12.filler_bytes(empty, free)))
    tgt = fat_disk(f"bug-tgt-{tag}", [(filler, "FILL.BIN")])
    assert fat12.free_clusters(tgt.read_bytes()) == free
    before = tgt.read_bytes()[:fat12.DATA_OFFSET]
    L = r.load_segment
    lua = (f"LOAD_SEG = 0x{L:04X}\n"
           f'SWAPS = {{{{t=34.0, image="{data_img.resolve()}"}}, {{t=42.0, image="{tgt.resolve()}"}}}}\n'
           + _SWAP_LUA)
    script = d / "swap.lua"
    script.write_text(lua + f'\ndofile("{(Path(fz.__file__).resolve().parent / "probe.lua").as_posix()}")\n')
    ev = fz._taps((33.0, "soft4"), (35.0, "disk"), (35.8, "7"), (39.0, "soft1"),
                  (43.0, "main_screen"), (44.0, "disk"), (45.0, "3"), (47.0, "soft1"))
    boot = _boot_disk(r, [])
    screens = run(r.bios, [46.5, 60.0], d / "mame", floppy=boot, rompath=r.rompath,
                  panel=write_smf(d / "panel.mid", ev),
                  extra=["-autoboot_script", str(script), "-state_directory", str(states), "-state", "boot"],
                  env={"PROBE_LCD_SEED": str(lcd), "PROBE_REINSERT": "1"})
    after = tgt.read_bytes()[:fat12.DATA_OFFSET]
    return "\n".join(screens[-1]["rows"]), before, after


_SWAP_LUA = r"""
local machine = manager.machine
local i = 1
emu.register_periodic(function()
  if i <= #SWAPS and machine.time:as_double() >= SWAPS[i].t then
    for tag, img in pairs(machine.images) do
      if img.image_type_name == "floppydisk" then img:unload(); img:load(SWAPS[i].image) end
    end
    i = i + 1
  end
end)
"""


if __name__ == "__main__":
    unittest.main()
