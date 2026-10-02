"""Apply All confirmation: real panel/MIDI input and read-only observers.

Soft Key 1 only opens the prompt; Soft Key 3 <Do it> applies. Any other key
cancels with every program's settings unchanged, and a mode key still leaves.
Payloads come from emu.harness, built from the current sources.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from emu import harness as h
from emu.harness import taps
from emu.mpc3k import run
from emu.panel import dial, pad_hit, panel_pad, write_smf
from emu.test_mute_ui import ROOT, observer, rows, screen, states

RUNS = ROOT / 'build/emu/mute-apply-all-tests'
# Program 1 enabled, pad 1 group 1, pad 64 group 4; Pad 64 selected, Group focused.
BASIC = taps((27,'+'), (28,'right'), (29,'right'), (30,'1'),
             (31,'left'), (32,'6'), (32.3,'4'), (33,'right'), (34,'4'))
BEFORE = [1] + [0]*62 + [4]
# Cancelling input -> (Soft Key 1 opens, input arrives); observed one second later.
# Each would otherwise change something: exit, focus, group 2, group 3, pad 1.
CANCELS = {'soft1': (36, 38), 'soft4': (40, 41), 'left': (43, 44), '2': (46, 47),
           'wheel': (49, 50), 'pad': (52, 53), 'soft2': (55, 56)}


def pixels(directory: Path) -> dict[float, list[str]]:
    blocks = (directory / 'lcd_pixels.txt').read_text().split('@ ')[1:]
    return {float(b.split()[0]): b.splitlines()[1:65] for b in blocks}


class MuteApplyAll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profiles = {False: h.payload('capture'), True: h.payload('generic')}
        RUNS.mkdir(parents=True, exist_ok=True)
        for profile in profiles.values():
            profile.record(RUNS)
        chain = []
        for key, (opened, at) in CANCELS.items():
            chain += taps((opened,'soft1'))
            if key == 'wheel':
                chain += dial(-1, at)
            elif key == 'pad':
                chain += pad_hit(panel_pad(1), at)
            else:
                chain += taps((at, key))
        chain += taps((59,'soft1'), (60,'soft3'))
        cancel_times = [35, 37] + [at + 1 for _, at in CANCELS.values()] + [61]
        program_change = write_smf(RUNS/'program-change.mid', [(37.0, bytes((0xC0, 0x01)))])
        definitions = {
            'cancel': (BASIC + chain, cancel_times, False, None),
            'mode': (BASIC + taps((36,'soft1'), (37,'other')), [35, 39], True, None),
            'program': (BASIC + taps((36,'soft1'), (39,'soft3')), [35, 38, 40], False,
                        program_change),
        }
        cases = {}
        for name, (events, times, generic, external) in definitions.items():
            profile = profiles[generic]
            image = h.wave_disk(profile, 'mute-apply-all-' + name)
            panel = write_smf(RUNS/f'{name}.mid',
                              taps((20,'soft4'), (23,'program_sounds'), (25,'0')) + events)
            extra = ['-autoboot_script', str(observer(RUNS, generic, profile))]
            if external is not None:
                extra += ['-midiin1', str(external)]  # MAME slots: mdin, mdin2, panel
            cases[name] = (times, dict(floppy=image, panel=panel, extra=extra,
                rompath=profile.rompath))

        def execute(item):
            name, (times, kwargs) = item
            return name, run('vailixi', times, RUNS/name, **kwargs)
        with ThreadPoolExecutor(max_workers=3) as pool:
            cls.results = dict(pool.map(execute, cases.items()))

    def test_soft_key_1_only_shows_the_prompt(self):
        before = states(RUNS/'cancel', 35)
        self.assertEqual(before[0], {'enabled': 1, 'groups': BEFORE})
        self.assertEqual(states(RUNS/'cancel', 37), before)
        self.assertEqual(pixels(RUNS/'cancel')[37], screen(1, 64, BEFORE, True, 3, prompt=True))

    def test_every_other_key_cancels_and_restores_the_page(self):
        before = states(RUNS/'cancel', 35)
        normal = screen(1, 64, BEFORE, True, 3)
        r, lcd = rows(RUNS/'cancel'), pixels(RUNS/'cancel')
        for key, (_, at) in CANCELS.items():
            with self.subTest(key=key):
                self.assertEqual(states(RUNS/'cancel', at + 1), before)
                self.assertEqual((r[at + 1]['pad'], r[at + 1]['focus']), (63, 3))
                self.assertEqual(lcd[at + 1], normal)

    def test_soft_key_3_still_applies_after_cancels(self):
        before = states(RUNS/'cancel', 35)
        after = states(RUNS/'cancel', 61)
        self.assertEqual(after[0], {'enabled': 1, 'groups': [4]*64})
        self.assertEqual(after[1:], before[1:])
        self.assertEqual(pixels(RUNS/'cancel')[61], screen(1, 64, [4]*64, True, 3))

    def test_mode_key_cancels_and_still_leaves(self):
        self.assertEqual(states(RUNS/'mode', 39), states(RUNS/'mode', 35))
        text = ''.join(self.results['mode'][-1]['rows'])
        self.assertNotIn('<Do it>', text)
        self.assertIn('Metronome', text)  # the stock Other page

    def test_program_change_cancels_instead_of_applying(self):
        before = states(RUNS/'program', 35)
        r = rows(RUNS/'program')
        self.assertEqual(r[38]['active_program'], 1)  # the MIDI change arrived
        # The page only notices at the next key, so the prompt still names Program 01;
        # <Do it> then cancels and the page is redrawn for Program 02.
        self.assertEqual(pixels(RUNS/'program')[38], screen(1, 64, BEFORE, True, 3, prompt=True))
        self.assertEqual(states(RUNS/'program', 40), before)
        self.assertEqual(r[40]['program'], 1)
        self.assertEqual(pixels(RUNS/'program')[40], screen(2, 64, [0]*64, False, 3))


if __name__ == '__main__':
    unittest.main()
