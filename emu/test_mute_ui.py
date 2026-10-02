"""Mute-group UI: real panel input, observed settings, and LCD pixels.

Run: python3 -m unittest emu.test_mute_ui -v
Payloads come from emu.harness, built from the current sources (capture, plus
the generic case on the generic profile); their SHA-256 is logged.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import unittest

from emu import harness as h
from emu import test_mpc3k as base
from emu import wave_ref
from emu.mpc3k import run
from emu.panel import dial, key_tap, pad_hit, panel_pad, write_smf
from emu.snd import disk
from emu.test_wave_zones import symbols, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/mute-ui-tests'


def observer(directory: Path, generic: bool = False, profile: h.Profile | None = None) -> Path:
    """Read-only mute observer.  With `profile`, use the payload under test
    (emu.harness) and also log the repeat counts; otherwise the release map."""
    if profile is not None:
        return h.observer(profile, directory / f'observe-{profile.name}.lua',
                          ['repeat_watch', 'mute_ui'])
    offsets = symbols(ROOT / ('build/mods/wave.cave.map' if generic else 'build/mods/wavehw.cave.map'))
    names = ('mu_program', 'mu_pad', 'mu_focus', 'mute_states')
    prefix = ('local MUTE_OFFSETS={' + ','.join(f'{n}={offsets[n]}' for n in names) + '}\n'
              + f'local MUTE_PROGRAM_OFFSET={0xE60E if generic else 0xE60C}\n'
              + f'local MUTE_PROBE_PATH="{ROOT / "emu/probe.lua"}"\n')
    result = directory / ('observe-generic.lua' if generic else 'observe.lua')
    result.write_text(prefix + (ROOT / 'emu/lua/mute_ui.lua').read_text())
    return result


def states(directory: Path, at: float) -> list[dict]:
    raw = (directory / f'mute_state_{at:.3f}.bin').read_bytes()
    return [{'enabled': raw[p * 33],
             'groups': [(raw[p * 33 + 1 + i // 2] >> (4 * (i % 2))) & 15 for i in range(64)]}
            for p in range(24)]


def rows(directory: Path) -> dict[float, dict]:
    return {r['time']: r for line in (directory / 'mute_ui.jsonl').read_text().splitlines()
            if (r := json.loads(line))}


def screen(program: int, pad: int, groups: list[int], enabled: bool, focus: int,
           prompt: bool = False) -> list[str]:
    lit = [[False] * 240 for _ in range(64)]
    if not prompt:
        wave_ref._text(lit, 0, 0, 'Mute Groups:')
        wave_ref._text(lit, 0, 13, f'PROGRAM_{program:02d}')
    wave_ref._text(lit, 8, 0, f'Program:{program:02d}    Enabled:{"ON " if enabled else "OFF"}')
    wave_ref._text(lit, 8, 30, f'Note:{pad + 34:02d}')
    group = groups[pad - 1]
    group_text = str(group).ljust(3) if group else 'OFF'
    wave_ref._text(lit, 16, 0, f'Pad:{pad:02d} ({chr(65 + (pad - 1) // 16)}{(pad - 1) % 16 + 1:02d})  Group:{group_text}')
    for bank in range(4):
        chars = ''.join(str(g) if g else '-' for g in groups[bank * 16:bank * 16 + 16])
        spaced = ' '.join(chars[i:i+4] for i in range(0,16,4))
        wave_ref._text(lit, 24 + bank * 8, 0, f'{chr(65 + bank)} {bank*16+1:02d}-{bank*16+16:02d}:{spaced}')
    if prompt:  # Apply All confirmation replaces only the title and soft-key rows
        wave_ref._text(lit, 0, 0, f'Program {program:02d}: set all 64 pads to group {group_text}')
        wave_ref._text(lit, 57, 20, '<Do it>     <Cancel>')
    else:
        wave_ref._text(lit, 57, 0, '<Apply All>')
        wave_ref._text(lit, 57, 34, '<Exit>')
    n = pad - 1
    wave_ref._invert(lit, (8 + n % 16 + (n % 16) // 4) * 6, 6, 24 + n // 16 * 8, 7)
    wave_ref._invert(lit, (8,22,4,20)[focus] * 6, (12,18,12,18)[focus], (8,8,16,16)[focus], 7)
    return [''.join('#' if value else '.' for value in line) for line in lit]


class MuteUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        h.require_tools()
        RUNS.mkdir(parents=True, exist_ok=True)
        profiles = {False: h.payload('capture'), True: h.payload('generic')}
        for profile in profiles.values():
            profile.record(RUNS)
        cls.payload_hash = profiles[False].sha256
        basic = taps((27,'+'), (28,'right'), (29,'right'), (30,'1'),
                     (31,'left'), (32,'6'), (32.3,'4'), (33,'right'), (34,'4'))
        definitions = {
            'individual': (basic, [26,30.5,35], False),
            'all': (basic + taps((36,'soft1'),(38,'soft3')), [35,37,39], False),
            'programs': (basic + taps((35,'left'),(36,'left'),(37,'left'),(38,'+'),
                         (39,'right'),(40,'+'),(41,'right'),(42,'2'),(42.3,'0'),
                         (43,'right'),(44,'3'),(46,'left'),(47,'left'),(48,'left'),(49,'-')),
                         [38.5,45,50], False),
            'bounds': (taps((27,'left')) + dial(40,28,gap=.025) + dial(-40,31,gap=.025)
                       + taps((34,'right'),(35,'right')) + dial(100,36,gap=.025)
                       + taps((40,'right')) + dial(7,41,gap=.025) + dial(-10,43,gap=.025),
                       [30,33,39,42,45], False),
            'banks': (taps((27,'right')) + pad_hit(panel_pad(1),28)
                       + taps((29,'pad_bank')) + pad_hit(panel_pad(16),30)
                       + taps((31,'pad_bank')) + pad_hit(panel_pad(1),32)
                       + taps((33,'pad_bank')) + pad_hit(panel_pad(16),34),
                       [28.5,30.5,32.5,34.5], False),
            'generic': (basic + taps((36,'soft4')), [35,37], True),
            # Wheel bursts 1 ms apart (coalesced by the stock reader): program,
            # enable, pad and group must apply the whole repeat count, clamped.
            'burst': (taps((27,'left')) + h.burst(9,28) + h.burst(-5,30)
                      + taps((32,'right')) + h.burst(3,33)
                      + taps((35,'right')) + h.burst(9,36) + h.burst(9,38)
                      + taps((40,'right')) + h.burst(9,41) + h.burst(-3,43),
                      [27.5,29,31,34,37,39,42,44], False),
        }
        cases = {}
        for name,(events,times,generic) in definitions.items():
            profile = profiles[generic]
            image = h.wave_disk(profile, 'mute-ui-'+name)
            panel = write_smf(RUNS/f'{name}.mid', taps((20,'soft4'),(23,'program_sounds'),(25,'0')) + events)
            cases[name] = (times,dict(floppy=image, panel=panel,
                rompath=profile.rompath,
                extra=['-autoboot_script',str(observer(RUNS,generic,profile))]))
        def execute(item):
            name,(times,kwargs) = item
            return name,run('vailixi',times,RUNS/name,**kwargs)
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(pool.map(execute,cases.items()))

    def test_defaults_and_individual_pad_1_and_64(self):
        initial = states(RUNS/'individual',26)
        self.assertEqual(initial,[{'enabled':0,'groups':[0]*64} for _ in range(24)])
        result = states(RUNS/'individual',35)[0]
        self.assertEqual(result,{'enabled':1,'groups':[1]+[0]*62+[4]})
        self.assertEqual(rows(RUNS/'individual')[35]['pad'],63)

    def test_apply_all_asks_then_soft_key_3_applies_and_retains_enable(self):
        before = states(RUNS/'all',35)
        self.assertEqual(states(RUNS/'all',37),before)  # Soft Key 1 only asks
        self.assertEqual(states(RUNS/'all',39)[0],{'enabled':1,'groups':[4]*64})
        self.assertEqual(states(RUNS/'all',39)[1:],before[1:])
        blocks=(RUNS/'all/lcd_pixels.txt').read_text().split('@ ')[1:]
        pixels={float(b.split()[0]):b.splitlines()[1:65] for b in blocks}
        self.assertEqual(pixels[37],screen(1,64,[1]+[0]*62+[4],True,3,prompt=True))
        self.assertEqual(pixels[39],screen(1,64,[4]*64,True,3))

    def test_program_settings_are_independent(self):
        middle = states(RUNS/'programs',45)
        self.assertEqual(middle[0],{'enabled':1,'groups':[1]+[0]*62+[4]})
        self.assertEqual(middle[1],{'enabled':1,'groups':[0]*19+[3]+[0]*44})
        self.assertEqual(states(RUNS/'programs',50),middle)
        self.assertEqual(rows(RUNS/'programs')[50]['active_program'],0)

    def test_fields_clamp_and_fast_wheel_keeps_all_steps(self):
        r=rows(RUNS/'bounds')
        self.assertEqual([r[30]['program'],r[33]['program']],[23,0])
        self.assertEqual(r[39]['pad'],63)
        self.assertEqual(states(RUNS/'bounds',42)[0]['groups'][63],4)
        self.assertEqual(states(RUNS/'bounds',45)[0]['groups'][63],0)

    def test_physical_pads_select_across_all_four_banks(self):
        r=rows(RUNS/'banks')
        self.assertEqual([r[t]['pad'] for t in (28.5,30.5,32.5,34.5)],[0,31,32,63])

    def test_generic_profile_and_exit_to_menu(self):
        self.assertEqual(states(RUNS/'generic',35)[0],{'enabled':1,'groups':[1]+[0]*62+[4]})
        self.assertIn('0.Mute.groups',''.join(self.results['generic'][-1]['rows']).replace(' ','.'))

    def test_coalesced_wheel_bursts_apply_every_step(self):
        d=RUNS/'burst'
        r=rows(d)
        self.assertEqual([(r[t]['program'],r[t]['focus']) for t in (27.5,29,31)],[(0,0),(9,0),(4,0)])
        self.assertEqual(r[31]['active_program'],4)
        self.assertEqual(states(d,34)[4]['enabled'],1)
        self.assertEqual([r[t]['pad'] for t in (37,39)],[9,18])
        groups=[states(d,t)[4]['groups'][18] for t in (39,42,44)]
        self.assertEqual(groups,[0,4,1])
        self.assertEqual(states(d,44)[:4],states(d,27.5)[:4])
        # Coalescing really happened for every field: counts above one and
        # fewer redraws than wheel events.
        for at,events in ((28,9),(30,5),(33,3),(36,9),(38,9),(41,9),(43,3)):
            counts=h.repeats(d,'mu_repeat',at,at+1)
            self.assertEqual(sum(counts),events,(at,counts))
            self.assertGreater(max(counts),1,(at,counts))
            self.assertLess(h.blits(d,at,at+1),events,at)

    def test_complete_lcd_layout_and_focus(self):
        blocks=(RUNS/'individual/lcd_pixels.txt').read_text().split('@ ')[1:]
        pixels={float(b.split()[0]):b.splitlines()[1:65] for b in blocks}
        self.assertEqual(pixels[26],screen(1,1,[0]*64,False,1))
        self.assertEqual(pixels[35],screen(1,64,[1]+[0]*62+[4],True,3))


if __name__ == '__main__':
    unittest.main()
