"""Program copy and initialize carry/clear mute state through real panel menus."""
from pathlib import Path
import unittest

from emu import test_mpc3k as base
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import disk
from emu.test_mute_ui import observer, states
from emu.test_wave_zones import taps

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'build/emu/mute-lifecycle-tests'


class MuteLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if missing:=base.missing_tools():
            raise unittest.SkipTest(str(missing))
        RUNS.mkdir(parents=True,exist_ok=True)
        events=taps((20,'soft4'),(23,'program_sounds'),(25,'0'),(27,'+'),
                    (28,'right'),(29,'right'),(30,'4'),(31,'soft1'),
                    (32,'left'),(33,'6'),(33.3,'4'),(34,'right'),(35,'2'),
                    (36,'soft4'),(38,'4'),(40,'2'),(42,'down'))
        events+=dial(23,43)
        events+=taps((47,'soft1'),(50,'4'),(52,'3'),(55,'soft1'))
        img=disk('mute-lifecycle',[(ROOT/'build/mods/WAVEHW.SYS','STARTUP.SYS')])
        cls.results=run('vailixi',[35.5,46,48,54,56],RUNS/'run',floppy=img,
            rompath=ROOT/'build/roms-wavehw-composite',
            panel=write_smf(RUNS/'input.mid',events),
            extra=['-autoboot_script',str(observer(RUNS))])

    def test_copy_to_program_24_copies_all_groups_and_enable(self):
        before=states(RUNS/'run',35.5)
        after=states(RUNS/'run',48)
        expected={'enabled':1,'groups':[4]*63+[2]}
        self.assertEqual(before[0],expected)
        self.assertEqual(after[0],expected)
        self.assertEqual(after[23],expected)
        self.assertEqual(after[1:23],before[1:23])

    def test_initialize_clears_only_destination(self):
        before=states(RUNS/'run',48)
        after=states(RUNS/'run',56)
        self.assertEqual(after[23],{'enabled':0,'groups':[0]*64})
        self.assertEqual(after[:23],before[:23])


if __name__=='__main__':
    unittest.main()
