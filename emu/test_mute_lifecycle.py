"""Program copy and initialize carry/clear mute state through real panel menus.

Run: python3 -m unittest emu.test_mute_lifecycle -v
The payloads are built from the current sources by emu.harness: capture, and
316 (WAVE316.SYS on OS 3.16) once per BIOS set of harness.bios316_sets(), all
four in release mode.  On 3.16 every panel time is moved by
emu.test_mute_persistence.offset() (SCSI cancel 33.0 instead of 20.0); the
copy and initialize hooks are 3.16's own (mods/WAVE316.args), so every
assertion is the same.
"""
from pathlib import Path
import unittest

from emu import harness as h
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.test_mute_persistence import offset, suite_profiles, taps_at
from emu.test_mute_ui import observer, states

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'build/emu/mute-lifecycle-tests'
TIMES=[35.5,46,48,54,56]


class MuteLifecycle(unittest.TestCase):
    profiles={}

    @classmethod
    def setUpClass(cls):
        cls.profiles={p.label:p for p in suite_profiles()}
        jobs={}
        for label,profile in cls.profiles.items():
            runs=RUNS/label
            runs.mkdir(parents=True,exist_ok=True)
            profile.record(RUNS)
            d=offset(profile)
            # Soft Key 1 opens the Apply All prompt; Soft Key 3 <Do it> applies.
            events=taps_at(d,(20,'soft4'),(23,'program_sounds'),(25,'0'),(27,'+'),
                           (28,'right'),(29,'right'),(30,'4'),(31,'soft1'),(31.5,'soft3'),
                           (32,'left'),(33,'6'),(33.3,'4'),(34,'right'),(35,'2'),
                           (36,'soft4'),(38,'4'),(40,'2'),(42,'down'))
            events+=dial(23,43+d)
            events+=taps_at(d,(47,'soft1'),(50,'4'),(52,'3'),(55,'soft1'))
            jobs[label]=(profile,runs,d,events)

        def execute(label,job):
            profile,runs,d,events=job
            img=h.wave_disk(profile,'mute-lifecycle')
            return run(profile.bios,[t+d for t in TIMES],runs/'run',floppy=img,
                rompath=profile.rompath,
                panel=write_smf(runs/'input.mid',events),
                extra=['-autoboot_script',str(observer(runs,profile=profile))])
        cls.results=h.run_parallel(jobs,execute)

    def each(self):
        self.assertTrue(self.profiles,'no profile ran')
        for label,profile in self.profiles.items():
            yield label,RUNS/label/'run',offset(profile)

    def test_copy_to_program_24_copies_all_groups_and_enable(self):
        for label,d_run,d in self.each():
            with self.subTest(profile=label):
                before=states(d_run,35.5+d)
                after=states(d_run,48+d)
                expected={'enabled':1,'groups':[4]*63+[2]}
                self.assertEqual(before[0],expected)
                self.assertEqual(after[0],expected)
                self.assertEqual(after[23],expected)
                self.assertEqual(after[1:23],before[1:23])

    def test_initialize_clears_only_destination(self):
        for label,d_run,d in self.each():
            with self.subTest(profile=label):
                before=states(d_run,48+d)
                after=states(d_run,56+d)
                self.assertEqual(after[23],{'enabled':0,'groups':[0]*64})
                self.assertEqual(after[:23],before[:23])


if __name__=='__main__':
    unittest.main()
