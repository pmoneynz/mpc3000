"""WAVEHW regression against captured ranges plus explicitly borrowed ROM holes.

Run: python3 -m unittest emu.test_wave_physical -v
This is a composite emulator fixture, not a full physical ROM dump or a
physical LCD/panel qualification. No fixture chips are written under 07-rom.
The payload and the composite romset come from emu.harness: built from the
current sources into a test-private directory.  build/mods (the release
WAVEHW.SYS/.img/-validation.json) is never touched.

WavePhysical316 runs the same four wave-view feature checks on the 316
profile (WAVE316.SYS on OS 3.16, stock romset; one BIOS set per load segment
by default, all four in release mode).  The ROM-guard test stays capture-only:
WAVE316.SYS has no ROM guard by design (one SYS for every EPROM OS;
mods/build_wave316.py docstring, notes/port_316.md "No ROM guard").
"""
from __future__ import annotations

import os
from pathlib import Path
import unittest

from emu import harness as h
from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import write_smf
from emu.snd import snd, sine441, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/wavehw-tests'
RUNS316 = ROOT / 'build/emu/wavehw-316-tests'
CASES = ('wave_view', 'wave_stereo', 'wave_edges', 'wave_no_sound')
# The Mpc3kBoot cases (old SCSI-time-out timeline) press Help at 77.5 s and
# assert the wave view from 80 s.
LEGACY_HELP, LEGACY_VIEW = 77.5, 80.0


def composite(dest: Path = ROOT / 'build/roms-wavehw-composite') -> Path:
    """Legacy entry point: write the composite romset to `dest`."""
    return h.composite_roms(dest)


def sound_disks(profile: h.Profile, runs: Path, prefix: str) -> dict[str, Path]:
    disks = {}
    for name, sound, planes, start, end in (
        ('wave_view', 'SINE441', sine441(), base.WAVE_START, base.WAVE_END),
        ('wave_stereo', 'STEREO1', stereo1(), base.STEREO_START, base.STEREO_END),
        ('wave_edges', 'EDGE', [[12345]], 0, 1)):
        src = runs / f'{sound}.SND'
        src.write_bytes(snd(sound, planes, start=start, end=end))
        disks[name] = h.wave_disk(profile, prefix + name, [(src, src.name)])
    disks['wave_no_sound'] = h.wave_disk(profile, prefix + 'empty')
    return disks


class WavePhysical(unittest.TestCase):
    results = {}

    @classmethod
    def setUpClass(cls):
        profile = h.payload('capture')
        RUNS.mkdir(parents=True, exist_ok=True)
        profile.record(RUNS)
        cls.addClassCleanup(setattr, base, 'RUNS', base.RUNS)
        base.RUNS = RUNS
        disks = sound_disks(profile, RUNS, 'physical-')
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


def edge_script_316(profile: h.Profile, runs: Path) -> Path:
    """base.wave_edge_script with the 316 profile's segments: the same pokes and
    reads of sound record zero (SND_SEG:4814..481F, Vailixi A2AE) and the
    cave's cached `len` (CAVE_SEG, Vailixi F07D), from the harness preamble."""
    path = base.wave_edge_script(profile, runs)
    text = path.read_text()
    for vailixi, name in (('0xa2ae', 'SND_SEG'), ('0xf07d', 'CAVE_SEG')):
        if vailixi not in text:
            raise RuntimeError(f'{path}: {vailixi} not found; base.wave_edge_script changed')
        text = text.replace(vailixi, name)
    path.write_text(text)
    return path


def cases316(profile: h.Profile, runs: Path, disks: dict[str, Path]) -> dict[str, dict]:
    """base.CASES on the 316 timeline.

    The load and the first view opening come from the profile's timeline
    (cancel SCSI, Disk / 7 / <Load>, Program/Sounds / 6 / Help), anchored so
    the view is on screen at the legacy 80 s: every later key, dial, poke and
    probe time of the case, and so every reused assertion, is unchanged.
    3.16 presses that Help at 77.0 s, so wave_view's Edit Sound screen is
    taken 0.5 s before it (legacy 77 s, 0.5 s before Help at 77.5 s).
    wave_no_sound loads nothing; its keys (68-75 s) come after 3.16's
    Play/Record, so only the SCSI cancel is added."""
    tl = profile.timeline
    view_at = LEGACY_VIEW - (tl.view - tl.view_at)
    help_at = view_at + tl.view_help
    opened = h.load_sound_events(profile=profile) + h.open_view_events(view_at, profile=profile)
    out = {}
    for name in CASES:
        kw = dict(base.CASES[name], bios=profile.bios, floppy=disks[name], rompath=profile.rompath)
        if name == 'wave_no_sound':
            pre = h.taps((tl.cancel, 'soft4'))
        else:
            kw['press'] = [p for p in kw['press'] if p[0] > LEGACY_HELP]
            pre = opened
        kw['panel'] = write_smf(runs / f'{name}.mid', pre + [e for ev in kw.get('panel', []) for e in ev])
        out[name] = kw
    out['wave_view']['times'] = [help_at - 0.5, *base.CASES['wave_view']['times'][1:]]
    out['wave_edges']['extra'] = ['-autoboot_script', str(edge_script_316(profile, runs))]
    return out


class WavePhysical316(unittest.TestCase):
    """WavePhysical's four wave-view checks (the Mpc3kBoot assertions,
    unchanged) on every 3.16 BIOS set of harness.bios316_sets()."""
    results = {}
    sets: dict = {}

    @classmethod
    def setUpClass(cls):
        wanted = set(filter(None, os.environ.get('MPC3K_PROFILES', '').split(',')))
        if wanted and '316' not in wanted:
            h.unavailable('316 profile not selected (MPC3K_PROFILES)')
        jobs = {}
        for bios in h.bios316_sets():
            profile = h.payload('316', bios)
            runs = RUNS316 / profile.label
            runs.mkdir(parents=True, exist_ok=True)
            profile.record(RUNS316)
            disks = sound_disks(profile, runs, 'physical316-')
            for name, kw in cases316(profile, runs, disks).items():
                jobs[(profile.label, name)] = (runs, kw)

        def go(key, job):
            runs, kw = job
            kw = dict(kw)
            return run(kw.pop('bios'), kw.pop('times'), runs / key[1], **kw)
        results = h.run_parallel(jobs, go)
        cls.sets = {}
        for (label, name), screens in results.items():
            cls.sets.setdefault(label, {})[name] = screens
        cls.addClassCleanup(setattr, base, 'RUNS', base.RUNS)

    def each_set(self, check) -> None:
        """Run a reused Mpc3kBoot check against one BIOS set's runs at a time."""
        self.assertEqual(sorted(self.sets), sorted(f'316-{b}' for b in h.bios316_sets()))
        for label, results in sorted(self.sets.items()):
            self.assertEqual(sorted(results), sorted(CASES), label)
            with self.subTest(profile=label):
                base.RUNS = RUNS316 / label
                self.results = results
                base.VIEW_BANK = 'A'            # PMONEY 3.16: "Bank A" in the wave view
                try:
                    check(self)
                finally:
                    base.VIEW_BANK = None

    def test_trim_and_zone(self):
        self.each_set(base.Mpc3kBoot.test_wave_view_edits_trim_and_zone)

    def test_stereo(self):
        self.each_set(base.Mpc3kBoot.test_wave_view_field_selects_plane)

    def test_long_step_and_empty(self):
        self.each_set(base.Mpc3kBoot.test_wave_view_long_step_empty_sound_and_mode_exits)

    def test_no_sound(self):
        self.each_set(base.Mpc3kBoot.test_wave_view_help_is_safe_when_there_are_no_sounds)


if __name__ == '__main__':
    unittest.main()
