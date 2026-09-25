"""Route A builder rules for the code cave (mods/build_mod_sys.py)."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mods"))
import build_mod_sys as b  # noqa: E402


@unittest.skipIf(shutil.which("nasm") is None, "needs nasm")
class CaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.img = b.linear()
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def asm(self, body: str) -> Path:
        src = self.tmp / "t.asm"
        src.write_text("bits 16\norg 0\n" + body)
        return src

    def test_cave_bounds_and_segment(self) -> None:
        self.assertEqual(b.CAVE, (0x707D0, 0x74000))
        self.assertEqual(b.CAVE_SEG, 0xF07D)
        self.assertEqual(self.img[0x707C8:0x74000], b"\xff" * (0x74000 - 0x707C8))

    def test_labels_become_far_pointers(self) -> None:
        patch, labels = b.cave(self.asm("a: nop\nb: retf\n"), self.img)
        self.assertEqual(patch, (0x707D0, "ffff", "90cb"))
        self.assertEqual(labels, {"a": 0, "b": 1})
        self.assertEqual(b.far("9a{b}90", labels), "9a01007df090")
        with self.assertRaises(ValueError):
            b.far("9a{c}", labels)

    def test_rejects_oversize_and_brkxa(self) -> None:
        with self.assertRaises(ValueError):
            b.cave(self.asm(f"times {0x74000 - 0x707D0 + 1} nop\n"), self.img)
        with self.assertRaises(ValueError):
            b.cave(self.asm("db 0x0f, 0xe0, 0x10\n"), self.img)


class FontTests(unittest.TestCase):
    def test_wave_font_include_is_generated(self) -> None:
        import contextlib
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from emu import lcd_font
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            lcd_font.main()
        inc = Path(__file__).resolve().parents[1] / "mods" / "wave_font.inc"
        self.assertEqual(inc.read_text(), out.getvalue())


if __name__ == "__main__":
    unittest.main()
