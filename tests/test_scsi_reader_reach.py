"""Static side of the scsistack316 proof (tools/scsi_reader_reach.py): only the
UI task (AMX task 7) can reach the SCSI partition reader 2AB2:04F7, and the
reader cannot reach itself again.  No MAME; emu.test_scsi316 is the dynamic side."""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import build_mod_sys as mod  # noqa: E402
from mods import build_wave316 as b  # noqa: E402
from mods import buildkit as kit  # noqa: E402
from mods import route_c as rc  # noqa: E402
from tools import scsi_reader_reach as sr  # noqa: E402


@unittest.skipUnless(shutil.which("nasm"), "needs nasm")
class ReaderReach(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        args = mod.read_args(b.ARGS)
        asm = kit.assemble(args.cave, defines={b.DEFINE: None}, include=[args.cave.parent],
                           map_column="real", listing=True)
        patches = [rc.expand(off, old, new, asm.labels, b.CAVE_HOME) for off, old, new in args.patch]
        result = rc.build(b.M3K316.read_bytes(), asm.code, asm.labels, patches, home=b.CAVE_HOME)
        cls.r = sr.analyse(result.sys, asm.labels["cave_copy_end"])

    def test_the_kernel_transfers_only_to_saved_contexts(self) -> None:
        self.assertEqual(self.r["kernel_transfers"], [])

    def test_the_vector_installs_are_the_modelled_ones(self) -> None:
        amx, direct = self.r["installs"]
        self.assertEqual(amx, sr.AMX_INSTALLS)
        self.assertEqual(direct, sr.DIRECT_INSTALLS)
        for seg, off, vec in amx - {(0x4852, 0x0053, 0x08)}:           # the dead OS-reload install aside
            self.assertIn((seg, off), sr.VECTORS[vec])
        for vec in direct.values():
            self.assertIn(vec, sr.VECTORS)

    def test_no_other_task_interrupt_or_initialiser_reaches_the_reader(self) -> None:
        for name, v in self.r["roots"].items():
            if name.startswith(("task7 ", "start-up")):
                continue
            with self.subTest(root=name):
                self.assertEqual(v["hits"], [])
                self.assertLessEqual(set(map(tuple, v["unresolved"])), {sr.EPROM_INT40})
        self.assertTrue(self.r["roots"]["task7 0281:0034 SS 73E1"]["hits"])     # the UI task does

    def test_the_reader_cannot_reenter_itself(self) -> None:
        body = self.r["reader_body"]
        self.assertEqual((body["hits"], body["unresolved"]), ([], []))
        self.assertGreater(body["insns"], 500)


if __name__ == "__main__":
    unittest.main()
