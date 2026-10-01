"""WAVEHW regression against captured ranges plus explicitly borrowed ROM holes.

Run: python3 -m unittest emu.test_wave_physical -v
This is a composite emulator fixture, not a full physical ROM dump or a
physical LCD/panel qualification. No fixture chips are written under 07-rom.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.romset import build as romset
from emu.panel import write_smf
from emu.snd import disk, snd, sine441, stereo1
from mods import build_mod_sys as mod
from mods import build_wave_physical as profile

ROOT = profile.ROOT
RUNS = ROOT / 'build/emu/wavehw-tests'


def composite() -> Path:
    dest = ROOT / 'build/roms-wavehw-composite'
    shutil.copytree(romset(), dest, dirs_exist_ok=True)
    image = bytearray(mod.linear())
    capture = profile.inputs()
    image[0x20000:0x74000] = capture[0x20000:0x74000]
    image[0x78000:] = capture[0x78000:]
    (dest / 'mpc3000/3.50 vailixi lse.bin').write_bytes(image[::2])
    (dest / 'mpc3000/3.50 vailixi mso.bin').write_bytes(image[1::2])
    (dest / 'composite.json').write_text(json.dumps({
        'physical_ranges': [[0x20000, 0x74000], [0x78000, 0x80000]],
        'reference_substituted_unobserved_ranges': [[0, 0x20000], [0x74000, 0x78000]],
        'sha256': hashlib.sha256(image).hexdigest()}, indent=2) + '\n')
    return dest


class WavePhysical(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        if missing := base.missing_tools():
            raise unittest.SkipTest(str(missing))
        if not profile.APP.exists() or not profile.HIGH.exists():
            raise unittest.SkipTest('verified physical captures are required')
        profile.build()
        rompath = composite()
        RUNS.mkdir(parents=True, exist_ok=True)
        cls.addClassCleanup(setattr, base, 'RUNS', base.RUNS)
        base.RUNS = RUNS
        sysfile = mod.OUT / 'WAVEHW.SYS'
        disks = {}
        for name, sound, planes, start, end in (
            ('wave_view', 'SINE441', sine441(), base.WAVE_START, base.WAVE_END),
            ('wave_stereo', 'STEREO1', stereo1(), base.STEREO_START, base.STEREO_END),
            ('wave_edges', 'EDGE', [[12345]], 0, 1)):
            src = RUNS / f'{sound}.SND'
            src.write_bytes(snd(sound, planes, start=start, end=end))
            disks[name] = disk('physical-' + name, [(sysfile, 'STARTUP.SYS'), (src, src.name)])
        disks['wave_no_sound'] = disk('physical-empty', [(sysfile, 'STARTUP.SYS')])
        edge = base.wave_edge_script(mod.OUT / 'wavehw.cave.map')

        def go(name):
            kw = dict(base.CASES[name])
            kw['floppy'] = disks[name]
            kw['rompath'] = rompath
            if 'panel' in kw:
                kw['panel'] = write_smf(RUNS / f'{name}.mid', [e for ev in kw['panel'] for e in ev])
            if name == 'wave_edges':
                kw['extra'] = ['-autoboot_script', str(edge)]
            return name, run(kw.pop('bios'), kw.pop('times'), RUNS / name, **kw)
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(go, disks))
        # Negative test uses final payload without any guard substitution.
        negative = disk('physical-guard-negative', [(sysfile, 'STARTUP.SYS')])
        before = negative.read_bytes()
        cls.rejected = run('vailixi', [10, 35, 65], RUNS / 'guard-negative', floppy=negative)
        cls.negative_unchanged = negative.read_bytes() == before

    test_trim_and_zone = base.Mpc3kBoot.test_wave_view_edits_trim_and_zone
    test_stereo = base.Mpc3kBoot.test_wave_view_field_selects_plane
    test_long_step_and_empty = base.Mpc3kBoot.test_wave_view_long_step_empty_sound_and_mode_exits
    test_no_sound = base.Mpc3kBoot.test_wave_view_help_is_safe_when_there_are_no_sounds

    def test_incompatible_rom_rejected(self):
        self.assertTrue(self.negative_unchanged)
        self.assertIn('Mod ROM mismatch', '\n'.join(self.rejected[-1]['rows']))
        self.assertNotIn('Play/Record', '\n'.join(self.rejected[-1]['rows']))


if __name__ == '__main__':
    unittest.main()
