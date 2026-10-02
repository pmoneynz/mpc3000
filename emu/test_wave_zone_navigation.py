"""Real panel End -> Up -> Zone -> Down -> End shortcuts, including numeric entry.

Run: python3 -m unittest emu.test_wave_zone_navigation -v
Payloads come from emu.harness (built from the current sources).
"""
from pathlib import Path
import struct
import unittest

from emu import harness as h
from emu.harness import VIEW as V, taps, zone_rows
from emu.panel import dial
from emu.snd import sine441, snd, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/wave-zone-navigation'


class ZoneNavigation(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({'mono', 'stereo_fine'})

    @classmethod
    def cases(cls, profile, runs):
        four = taps((V + 1, 'right'), (V + 2, 'right'), (V + 3, 'right')) + dial(-12, V + 4)
        shortcut = taps((V + 7, 'down'), (V + 8, 'up'), (V + 9, '+'), (V + 10, 'down'), (V + 11, '+'),
                        (V + 12, 'up'), (V + 13, 'right'), (V + 14, 'down'))
        numeric = taps((V + 7, 'down'), (V + 8, '0'), (V + 9, 'right'), (V + 10, '4'), (V + 10.2, '0'),
                       (V + 10.4, '0'), (V + 11, 'up'), (V + 12, '+'), (V + 13, 'down'))
        stereo = taps((V + 1, 'soft2'), (V + 2, 'right'), (V + 3, 'soft3'), (V + 4, 'up'),
                      (V + 5, '+'), (V + 6, 'down'), (V + 7, '+'))
        idle = taps((V + 1, 'right'), (V + 2, 'enter'), (V + 3, 'up'), (V + 4, 'down'))
        shortcut_times = [V + 6, V + 7.5, V + 8.5, V + 9.5, V + 10.5, V + 11.5, V + 14.5]
        definitions = {
            'mono': (sine441(), four + shortcut, shortcut_times, None),
            'numeric': (sine441(), four + numeric, [V + 7.5, V + 10.7, V + 11.5, V + 12.5, V + 13.5], None),
            'stereo_fine': (stereo1(), stereo, [V + 2.5, V + 4.5, V + 5.5, V + 6.5, V + 7.5], None),
            'idle_numeric': (sine441(), idle, [V + 1.6, V + 3.6, V + 4.6], 44099),
        }
        cases = {}
        for name, (planes, events, times, end) in definitions.items():
            src = runs / f'{name}.SND'
            src.write_bytes(snd('NAV', planes, end=end))
            cases[name] = h.Case(events=h.wave_events(events), times=times,
                                 files=[(src, 'NAV.SND')], env={'SNDDUMP_PCM': '0'})
        return cases

    def check_shortcut(self, d):
        r = zone_rows(d)
        self.assertEqual((r[V + 7.5]['focus'], r[V + 7.5]['sel']), (0, 3))
        self.assertEqual(r[V + 8.5]['focus'], 2)
        self.assertEqual(r[V + 9.5]['current'], 2)
        self.assertEqual((r[V + 10.5]['focus'], r[V + 10.5]['sel']), (0, 3))
        self.assertEqual(r[V + 11.5]['bounds'][:5], [0, 13781, 27562 + 229, 41343, 55125])
        self.assertEqual((r[V + 14.5]['focus'], r[V + 14.5]['sel']), (0, 3))
        self.assertTrue(all(v['zoom'] == 16 for v in r.values()))

    def test_mono_current_and_count_return_directly_to_end(self):
        for prof, d, _ in self.each('mono'):
            with self.subTest(profile=prof):
                self.check_shortcut(d)

    def test_generic_profile_shortcut(self):
        runs = [d for prof, d, _ in self.each('mono') if prof == 'generic']
        if not runs:
            h.unavailable('generic profile not selected (MPC3K_PROFILES)')
        self.check_shortcut(runs[0])

    def test_stereo_fine_skips_view_and_keeps_zoom(self):
        for prof, d, _ in self.each('stereo_fine'):
            with self.subTest(profile=prof):
                r = zone_rows(d)
                self.assertEqual((r[V + 2.5]['focus'], r[V + 2.5]['sel']), (0, 3))
                self.assertEqual(r[V + 4.5]['focus'], 2)
                self.assertEqual(r[V + 5.5]['current'], 2)
                self.assertEqual((r[V + 6.5]['focus'], r[V + 6.5]['sel']), (0, 3))
                self.assertGreater(r[V + 7.5]['bounds'][2], r[V + 6.5]['bounds'][2])
                self.assertTrue(all(v['zoom'] == 16 for v in r.values()))

    def test_up_accepts_typed_end_and_selects_zone(self):
        for prof, d, screens in self.each('numeric'):
            with self.subTest(profile=prof):
                r = zone_rows(d)
                self.assertEqual(r[V + 11.5]['focus'], 2)
                # Up accepts the edited milliseconds and retains the untouched
                # 22-sample component of the initial 00.312.22 endpoint.
                self.assertEqual(r[V + 11.5]['bounds'][:5], [0, 17662, 27562, 41343, 55125])
                self.assertEqual(r[V + 12.5]['current'], 2)
                self.assertEqual((r[V + 13.5]['focus'], r[V + 13.5]['sel']), (0, 3))
                self.assertIn('mode=32', screens[2]['head'])
                # Positive control: the typed digits really opened the stock
                # numeric editor (text mode) before Up accepted them.
                self.assertNotIn('mode=32', screens[1]['head'])

    def test_idle_numeric_up_preserves_exact_frame(self):
        for prof, d, _ in self.each('idle_numeric'):
            with self.subTest(profile=prof):
                r = zone_rows(d)
                self.assertEqual(r[V + 3.6]['focus'], 2)
                self.assertEqual((r[V + 4.6]['focus'], r[V + 4.6]['sel']), (0, 1))
                for t in (V + 1.6, V + 3.6, V + 4.6):
                    record = h.sound_records(d, t)[0]
                    self.assertEqual(record['end'], 44099)


if __name__ == '__main__':
    unittest.main()
