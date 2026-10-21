"""LCD mirror builder (mods/build_lcdmirror316.py): deterministic, checked, port option.

    python3 -m unittest tests.test_build_lcdmirror316 -v
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import build_lcdmirror316 as lm  # noqa: E402
from mods import route_c as rc  # noqa: E402
from mods import buildkit as kit  # noqa: E402


@unittest.skipIf(shutil.which("nasm") is None or shutil.which("ndisasm") is None, "needs nasm and ndisasm")
class Build(unittest.TestCase):
    def build(self, port: int) -> tuple[dict, Path]:
        out = Path(tempfile.mkdtemp(prefix="lcdmirror-"))
        self.addCleanup(shutil.rmtree, out)
        return lm.build(port, out), out

    def test_deterministic_and_stock_untouched(self) -> None:
        stock = lm.w316.M3K316.read_bytes()
        a, out_a = self.build(4)
        b, _ = self.build(4)
        self.assertEqual(a["sys"]["sha256"], b["sys"]["sha256"])
        self.assertEqual(a["images"], b["images"])
        self.assertEqual(kit.sha256(lm.w316.M3K316.read_bytes()), lm.w316.M3K316_SHA256)
        self.assertEqual(lm.w316.M3K316.read_bytes(), stock)
        disk = (out_a / "STOCK_316.img").read_bytes()
        self.assertIn(stock[:4096], disk)                  # the control holds the stock file

    def test_hooks_and_patches(self) -> None:
        m, out = self.build(4)
        self.assertEqual([p["image"] for p in m["patches"]], ["0x61B5A", "0x2B55C", "0x32899"])
        image = rc.MZ.parse((out / "M3K316.SYS").read_bytes()).image
        self.assertEqual(bytes(image[0x61B5A:0x61B71]), b"System 3.16 LCD mirror\0")
        self.assertEqual(image[0x2B55C], 0x9A)            # CALLF lm_tick
        self.assertEqual(image[0x32899], 0xEA)            # JMPF lm_send_block
        self.assertEqual(len(m["stock_facts"]), len(lm.STOCK_FACTS))

    def test_port_option(self) -> None:
        a, _ = self.build(1)
        d, _ = self.build(4)
        self.assertNotEqual(a["sys"]["sha256"], d["sys"]["sha256"])
        with self.assertRaises(ValueError):
            lm.build(5, Path(tempfile.gettempdir()))


if __name__ == "__main__":
    unittest.main()
