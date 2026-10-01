"""Mute-group UI: real panel input, observed settings, and LCD pixels."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import unittest

from emu import test_mpc3k as base
from emu import wave_ref
from emu.mpc3k import run
from emu.panel import dial, key_tap, pad_hit, panel_pad, write_smf
from emu.snd import disk
from emu.test_wave_zones import symbols, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/mute-ui-tests'


def observer(directory: Path, generic: bool = False) -> Path:
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


def screen(program: int, pad: int, groups: list[int], enabled: bool, focus: int) -> list[str]:
    lit = [[False] * 240 for _ in range(64)]
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
    wave_ref._text(lit, 57, 0, '<Apply All>')
    wave_ref._text(lit, 57, 34, '<Exit>')
    n = pad - 1
    wave_ref._invert(lit, (8 + n % 16 + (n % 16) // 4) * 6, 6, 24 + n // 16 * 8, 7)
    wave_ref._invert(lit, (8,22,4,20)[focus] * 6, (12,18,12,18)[focus], (8,8,16,16)[focus], 7)
    return [''.join('#' if value else '.' for value in line) for line in lit]


class MuteUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if missing := base.missing_tools():
            raise unittest.SkipTest(str(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        cls.payload_hash = hashlib.sha256((ROOT/'build/mods/WAVEHW.SYS').read_bytes()).hexdigest()
        basic = taps((27,'+'), (28,'right'), (29,'right'), (30,'1'),
                     (31,'left'), (32,'6'), (32.3,'4'), (33,'right'), (34,'4'))
        definitions = {
            'individual': (basic, [26,30.5,35], False),
            'all': (basic + taps((36,'soft1')), [35,37], False),
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
        }
        cases = {}
        for name,(events,times,generic) in definitions.items():
            payload = ROOT / ('build/mods/WAVE.SYS' if generic else 'build/mods/WAVEHW.SYS')
            image = disk('mute-ui-'+name, [(payload,'STARTUP.SYS')])
            panel = write_smf(RUNS/f'{name}.mid', taps((20,'soft4'),(23,'program_sounds'),(25,'0')) + events)
            cases[name] = (times,dict(floppy=image, panel=panel,
                rompath=ROOT / ('build/roms' if generic else 'build/roms-wavehw-composite'),
                extra=['-autoboot_script',str(observer(RUNS,generic))]))
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

    def test_apply_all_is_one_action_and_retains_enable(self):
        self.assertEqual(states(RUNS/'all',37)[0],{'enabled':1,'groups':[4]*64})
        self.assertEqual(states(RUNS/'all',37)[1:],states(RUNS/'all',35)[1:])

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

    def test_complete_lcd_layout_and_focus(self):
        blocks=(RUNS/'individual/lcd_pixels.txt').read_text().split('@ ')[1:]
        pixels={float(b.split()[0]):b.splitlines()[1:65] for b in blocks}
        self.assertEqual(pixels[26],screen(1,1,[0]*64,False,1))
        self.assertEqual(pixels[35],screen(1,64,[1]+[0]*62+[4],True,3))


if __name__ == '__main__':
    unittest.main()
