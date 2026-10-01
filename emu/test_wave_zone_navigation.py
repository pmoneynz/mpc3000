"""Real panel End -> Up -> Zone -> Down -> End shortcuts, including numeric entry."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import disk, sine441, snd, stereo1
from emu.test_wave_zones import observer, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/wave-zone-navigation'


def rows(name):
    return {r['time']: r for line in (RUNS/name/'zones.jsonl').read_text().splitlines()
            if (r := json.loads(line))}


class ZoneNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if missing := base.missing_tools():
            raise unittest.SkipTest(str(missing))
        RUNS.mkdir(parents=True, exist_ok=True)
        four = taps((81,'right'),(82,'right'),(83,'right')) + dial(-12,84)
        shortcut = taps((87,'down'),(88,'up'),(89,'+'),(90,'down'),(91,'+'),
                        (92,'up'),(93,'right'),(94,'down'))
        numeric = taps((87,'down'),(88,'0'),(89,'right'),(90,'4'),(90.2,'0'),
                       (90.4,'0'),(91,'up'),(92,'+'),(93,'down'))
        stereo = taps((81,'soft2'),(82,'right'),(83,'soft3'),(84,'up'),
                      (85,'+'),(86,'down'),(87,'+'))
        idle = taps((81,'right'),(82,'enter'),(83,'up'),(84,'down'))
        definitions = {
            'mono': (sine441(),four+shortcut,[86,87.5,88.5,89.5,90.5,91.5,94.5],False,None),
            'generic': (sine441(),four+shortcut,[86,87.5,88.5,89.5,90.5,91.5,94.5],True,None),
            'numeric': (sine441(),four+numeric,[87.5,90.7,91.5,92.5,93.5],False,None),
            'stereo_fine': (stereo1(),stereo,[82.5,84.5,85.5,86.5,87.5],False,None),
            'idle_numeric': (sine441(),idle,[81.6,83.6,84.6],False,44099),
        }
        def execute(item):
            name,(planes,events,times,generic,end)=item
            payload=ROOT/('build/mods/WAVE.SYS' if generic else 'build/mods/WAVEHW.SYS')
            src=RUNS/f'{name}.SND';src.write_bytes(snd('NAV',planes,end=end))
            img=disk('zone-nav-'+name,[(payload,'STARTUP.SYS'),(src,'NAV.SND')])
            driver=RUNS/(name+'-driver');driver.mkdir(exist_ok=True)
            probe=observer(driver,ROOT/('build/mods/wave.cave.map' if generic else 'build/mods/wavehw.cave.map'))
            kw=dict(base.CASES['wave_view'])
            kw.update(floppy=img,panel=write_smf(driver/'input.mid',events),
                      rompath=ROOT/('build/roms' if generic else 'build/roms-wavehw-composite'),
                      extra=['-autoboot_script',str(probe)])
            kw['press']=[v for v in kw['press'] if v[0]<=77.5]
            kw.pop('times')
            return name,run(kw.pop('bios'),times,RUNS/name,**kw)
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results=dict(pool.map(execute,definitions.items()))

    def check_shortcut(self,name):
        r=rows(name)
        self.assertEqual((r[87.5]['focus'],r[87.5]['sel']),(0,3))
        self.assertEqual(r[88.5]['focus'],2)
        self.assertEqual(r[89.5]['current'],2)
        self.assertEqual((r[90.5]['focus'],r[90.5]['sel']),(0,3))
        self.assertEqual(r[91.5]['bounds'][:5],[0,13781,27562+229,41343,55125])
        self.assertEqual((r[94.5]['focus'],r[94.5]['sel']),(0,3))
        self.assertTrue(all(v['zoom']==16 for v in r.values()))

    def test_mono_current_and_count_return_directly_to_end(self):
        self.check_shortcut('mono')

    def test_generic_profile_shortcut(self):
        self.check_shortcut('generic')

    def test_stereo_fine_skips_view_and_keeps_zoom(self):
        r=rows('stereo_fine')
        self.assertEqual((r[82.5]['focus'],r[82.5]['sel']),(0,3))
        self.assertEqual(r[84.5]['focus'],2)
        self.assertEqual(r[85.5]['current'],2)
        self.assertEqual((r[86.5]['focus'],r[86.5]['sel']),(0,3))
        self.assertGreater(r[87.5]['bounds'][2],r[86.5]['bounds'][2])
        self.assertTrue(all(v['zoom']==16 for v in r.values()))

    def test_up_accepts_typed_end_and_selects_zone(self):
        r=rows('numeric')
        self.assertEqual(r[91.5]['focus'],2)
        # Up accepts the edited milliseconds and retains the untouched
        # 22-sample component of the initial 00.312.22 endpoint.
        self.assertEqual(r[91.5]['bounds'][:5],[0,17662,27562,41343,55125])
        self.assertEqual(r[92.5]['current'],2)
        self.assertEqual((r[93.5]['focus'],r[93.5]['sel']),(0,3))
        self.assertIn('mode=32',self.results['numeric'][2]['head'])

    def test_idle_numeric_up_preserves_exact_frame(self):
        r=rows('idle_numeric')
        self.assertEqual(r[83.6]['focus'],2)
        self.assertEqual((r[84.6]['focus'],r[84.6]['sel']),(0,1))
        records=sorted((RUNS/'idle_numeric').glob('records_*.bin'))
        self.assertEqual(len(records),3)
        for p in records:
            self.assertEqual(struct.unpack_from('<I',p.read_bytes(),0x18)[0],44099)


if __name__=='__main__':
    unittest.main()
