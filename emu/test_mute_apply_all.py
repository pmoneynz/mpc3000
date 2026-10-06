"""Apply All confirmation: real panel/MIDI input and read-only observers.

Soft Key 1 only opens the prompt; Soft Key 3 <Do it> applies. Any other key
cancels with every program's settings unchanged, and a mode key still leaves.
Payloads come from emu.harness, built from the current sources: every case on
capture and on the 316 profile (WAVE316.SYS on OS 3.16; one BIOS set per load
segment by default, all four in release mode), the mode case also on generic.
Times are Vailixi times moved by emu.test_mute_ui.delay(profile) (13 s on 3.16).
"""
import unittest

from emu import harness as h
from emu.harness import taps
from emu.panel import dial, pad_hit, panel_pad, write_smf
from emu.test_mute_ui import (OPEN, PARTS, ROOT, at, delay, each_run, later, pad_note, pixels,
                              rows, screen, states)

RUNS = ROOT / 'build/emu/mute-apply-all-tests'
# Program 1 enabled, pad 1 group 1, pad 64 group 4; Pad 64 selected, Group focused.
BASIC = taps((27,'+'), (28,'right'), (29,'right'), (30,'1'),
             (31,'left'), (32,'6'), (32.3,'4'), (33,'right'), (34,'4'))
BEFORE = [1] + [0]*62 + [4]
# Cancelling input -> (Soft Key 1 opens, input arrives); observed one second later.
# Each would otherwise change something: exit, focus, group 2, group 3, pad 1.
CANCELS = {'soft1': (36, 38), 'soft4': (40, 41), 'left': (43, 44), '2': (46, 47),
           'wheel': (49, 50), 'pad': (52, 53), 'soft2': (55, 56)}


class MuteApplyAll(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({'mode'})
    PROFILE_NAMES = h.ALL_PROFILES

    @classmethod
    def cases(cls, profile, runs):
        chain = []
        for key, (opened, when) in CANCELS.items():
            chain += taps((opened,'soft1'))
            if key == 'wheel':
                chain += dial(-1, when)
            elif key == 'pad':
                chain += pad_hit(panel_pad(1), when)
            else:
                chain += taps((when, key))
        chain += taps((59,'soft1'), (60,'soft3'))
        cancel_times = [35, 37] + [when + 1 for _, when in CANCELS.values()] + [61]
        t, dt = at(profile), delay(profile)
        program_change = write_smf(runs/'program-change.mid', later([(37.0, bytes((0xC0, 0x01)))], dt))
        definitions = {
            'cancel': (BASIC + chain, cancel_times, None),
            'mode': (BASIC + taps((36,'soft1'), (37,'other')), [35, 39], None),
            # MAME slots: mdin, mdin2, panel
            'program': (BASIC + taps((36,'soft1'), (39,'soft3')), [35, 38, 40],
                        {'extra': ['-midiin1', str(program_change)]}),
        }
        return {name: h.Case(events=later(OPEN + events, dt), times=[t(x) for x in times],
                             parts=PARTS, kwargs=kwargs)
                for name, (events, times, kwargs) in definitions.items()}

    def test_soft_key_1_only_shows_the_prompt(self):
        for label, profile, d, _, t in each_run(self, 'cancel'):
            with self.subTest(profile=label):
                before = states(d, t(35))
                self.assertEqual(before[0], {'enabled': 1, 'groups': BEFORE})
                self.assertEqual(states(d, t(37)), before)
                self.assertEqual(pixels(d)[t(37)], screen(1, 64, BEFORE, True, 3, prompt=True,
                                                         note=pad_note(profile, 64)))

    def test_every_other_key_cancels_and_restores_the_page(self):
        for label, profile, d, _, t in each_run(self, 'cancel'):
            before = states(d, t(35))
            normal = screen(1, 64, BEFORE, True, 3, note=pad_note(profile, 64))
            r, lcd = rows(d), pixels(d)
            for key, (_, when) in CANCELS.items():
                with self.subTest(profile=label, key=key):
                    self.assertEqual(states(d, t(when + 1)), before)
                    self.assertEqual((r[t(when + 1)]['pad'], r[t(when + 1)]['focus']), (63, 3))
                    self.assertEqual(lcd[t(when + 1)], normal)

    def test_soft_key_3_still_applies_after_cancels(self):
        for label, profile, d, _, t in each_run(self, 'cancel'):
            with self.subTest(profile=label):
                before = states(d, t(35))
                after = states(d, t(61))
                self.assertEqual(after[0], {'enabled': 1, 'groups': [4]*64})
                self.assertEqual(after[1:], before[1:])
                self.assertEqual(pixels(d)[t(61)], screen(1, 64, [4]*64, True, 3,
                                                         note=pad_note(profile, 64)))

    def test_mode_key_cancels_and_still_leaves(self):
        for label, _, d, screens, t in each_run(self, 'mode'):
            with self.subTest(profile=label):
                self.assertEqual(states(d, t(39)), states(d, t(35)))
                text = ''.join(screens[-1]['rows'])
                self.assertNotIn('<Do it>', text)
                self.assertIn('Metronome', text)  # the stock Other page

    def test_program_change_cancels_instead_of_applying(self):
        for label, profile, d, _, t in each_run(self, 'program'):
            with self.subTest(profile=label):
                before = states(d, t(35))
                r, lcd = rows(d), pixels(d)
                self.assertEqual(r[t(38)]['active_program'], 1)  # the MIDI change arrived
                # The page only notices at the next key, so the prompt still names Program 01;
                # <Do it> then cancels and the page is redrawn for Program 02.
                note = pad_note(profile, 64)
                self.assertEqual(lcd[t(38)], screen(1, 64, BEFORE, True, 3, prompt=True, note=note))
                self.assertEqual(states(d, t(40)), before)
                self.assertEqual(r[t(40)]['program'], 1)
                self.assertEqual(lcd[t(40)], screen(2, 64, [0]*64, False, 3, note=note))


if __name__ == '__main__':
    unittest.main()
