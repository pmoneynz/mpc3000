"""WAVEHW regression against captured ranges plus explicitly borrowed ROM holes.

Run: python3 -m unittest emu.test_wave_physical -v
This is a composite emulator fixture, not a full physical ROM dump or a
physical LCD/panel qualification. No fixture chips are written under 07-rom.
The payload and the composite romset come from emu.harness: built from the
current sources into a test-private directory.  build/mods (the release
WAVEHW.SYS/.img/-validation.json) is never touched.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from emu import harness as h
from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import write_smf
from emu.snd import snd, sine441, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/wavehw-tests'


def composite(dest: Path = ROOT / 'build/roms-wavehw-composite') -> Path:
    """Legacy entry point: write the composite romset to `dest`."""
    return h.composite_roms(dest)


class WavePhysical(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        profile = h.payload('capture')
        RUNS.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        cls.addClassCleanup(setattr, base, 'RUNS', base.RUNS)
        base.RUNS = RUNS
        disks = {}
        for name, sound, planes, start, end in (
            ('wave_view', 'SINE441', sine441(), base.WAVE_START, base.WAVE_END),
            ('wave_stereo', 'STEREO1', stereo1(), base.STEREO_START, base.STEREO_END),
            ('wave_edges', 'EDGE', [[12345]], 0, 1)):
            src = RUNS / f'{sound}.SND'
            src.write_bytes(snd(sound, planes, start=start, end=end))
            disks[name] = h.wave_disk(profile, 'physical-' + name, [(src, src.name)])
        disks['wave_no_sound'] = h.wave_disk(profile, 'physical-empty')
        edge = base.wave_edge_script(profile, RUNS)

        def go(name, image):
            kw = dict(base.CASES[name])
            kw['floppy'] = image
            kw['rompath'] = profile.rompath
            if 'panel' in kw:
                kw['panel'] = write_smf(RUNS / f'{name}.mid', [e for ev in kw['panel'] for e in ev])
            if name == 'wave_edges':
                kw['extra'] = ['-autoboot_script', str(edge)]
            return run(kw.pop('bios'), kw.pop('times'), RUNS / name, **kw)
        cls.results = h.run_parallel(disks, go)
        # Negative test: the final payload on the stock reference EPROMs,
        # without any guard substitution, must refuse to start.
        negative = h.wave_disk(profile, 'physical-guard-negative')
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
