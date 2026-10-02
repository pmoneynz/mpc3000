"""Shared builder machinery (mods/buildkit.py) and the small diagnostics that use it.

All builds write to temporary directories.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mods"))
import buildkit as kit  # noqa: E402

HAVE_NASM = shutil.which("nasm") is not None
HAVE_MTOOLS = all(shutil.which(t) for t in ("mdir", "mcopy"))


class PrimitiveTests(unittest.TestCase):
    def test_word_sum_and_interleave(self) -> None:
        self.assertEqual(kit.word_sum(b"\x01\x00\xff\xff"), 0)
        with self.assertRaises(ValueError):
            kit.word_sum(b"\x00")
        with self.assertRaises(ValueError):
            kit.interleave(b"\0" * 4, b"\0" * 4)

    def test_mz_header(self) -> None:
        payload = kit.pack_mz(b"\x90" * 1000)
        self.assertEqual(kit.validate_mz(payload), 1000)
        with self.assertRaises(ValueError):
            kit.validate_mz(payload[:-1])

    def test_listing_and_dependency_parsing(self) -> None:
        lines = kit.parse_listing(
            "     3 00000000 9A08001FD2              call 0xD21F:0x0008\n"
            "     4 00000005 00<rep 3h>         <1> buf: times 3 db 0\n"
            "     5 00000008 [0800]7DF0          <1> dw x, 0xF07D\n"
            "     6 0000000C 0102030405060708-      db 1,2,3,4,5,6,7,8,9\n"
            "     6 00000014 09                \n")
        self.assertEqual([(l.offset, l.data.hex(), l.source) for l in lines], [
            (0, "9a08001fd2", "call 0xD21F:0x0008"), (5, "000000", "buf: times 3 db 0"),
            (8, "08007df0", "dw x, 0xF07D"), (12, "010203040506070809", "db 1,2,3,4,5,6,7,8,9")])
        deps = kit.parse_deps("out : a.asm b\\ c.inc \\\n  /x/d.bin\n", Path("/r"))
        self.assertEqual(deps, [Path("/r/a.asm"), Path("/r/b c.inc"), Path("/x/d.bin")])


class Fat12Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def files(self) -> list[tuple[str, bytes]]:
        return [("STARTUP.SYS", bytes(range(256)) * 7), ("SINE441.SND", b"\x12" * 513),
                ("EMPTY.TXT", b"")]

    def test_deterministic_layout_and_zero_extended_name_bytes(self) -> None:
        a, layout = kit.pack_fat12(self.files(), oem=b"MPC3KTST", volume_id=b"TEST", label=b"T" * 11)
        b, _ = kit.pack_fat12(self.files(), oem=b"MPC3KTST", volume_id=b"TEST", label=b"T" * 11)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 1474560)
        self.assertEqual([(f["first_cluster"], f["clusters"]) for f in layout], [(2, 4), (6, 2), (0, 0)])
        for i, (name, data) in enumerate(self.files()):
            entry = a[kit.ROOT_OFFSET + 32 * i:kit.ROOT_OFFSET + 32 * i + 32]
            self.assertEqual(entry[:11], kit.fat_name(name))
            self.assertEqual(entry[0x0C:0x1A], bytes(14))
            if data:
                self.assertEqual(kit.extract_contiguous(a, layout[i]["first_cluster"], len(data)), data)
        self.assertEqual(a[kit.ROOT_OFFSET + 96], 0)

    def test_rejects_duplicates_and_bad_names(self) -> None:
        with self.assertRaises(ValueError):
            kit.pack_fat12([("A.SYS", b"1"), ("a.sys", b"2")], oem=b"X" * 8, volume_id=b"X" * 4,
                           label=b"X" * 11)
        with self.assertRaises(ValueError):
            kit.fat_name("TOOLONGNAME.SYS")
        with self.assertRaises(ValueError):
            kit.pack_fat12([("BIG.BIN", bytes(1474560))], oem=b"X" * 8, volume_id=b"X" * 4,
                           label=b"X" * 11)

    @unittest.skipUnless(HAVE_MTOOLS, "needs mtools")
    def test_mtools_reads_every_file(self) -> None:
        image, _ = kit.pack_fat12(self.files(), oem=b"MPC3KTST", volume_id=b"TEST", label=b"T" * 11)
        path = self.tmp / "t.img"
        path.write_bytes(image)
        listing = subprocess.run(["mdir", "-i", str(path), "::"], check=True, capture_output=True,
                                 text=True).stdout
        for name, data in self.files():
            base, ext = name.split(".")
            self.assertRegex(listing, rf"{base}\s+{ext}")
            dest = self.tmp / name
            subprocess.run(["mcopy", "-n", "-i", str(path), f"::{name}", str(dest)], check=True)
            self.assertEqual(dest.read_bytes(), data)


@unittest.skipUnless(HAVE_NASM, "needs nasm")
class SmallBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_romsum_romword_canary_build_to_out_directory(self) -> None:
        import build_canary
        import build_romsum
        import build_romword
        manifest = build_romsum.build(self.tmp)
        self.assertEqual(kit.sha256((self.tmp / "ROMSUM.SYS").read_bytes()), manifest["payload"]["sha256"])
        manifest = build_romword.build(self.tmp)
        self.assertEqual(kit.sha256((self.tmp / "ROMWORD.img").read_bytes()), manifest["image"]["sha256"])
        self.assertEqual(manifest["expected"]["vailixi"]["mismatching_words"], 0)
        build_canary.main(self.tmp)
        build_canary.directory_matches((self.tmp / "vailixi350-canary.img").read_bytes())

    def test_assemble_reports_only_its_own_outputs(self) -> None:
        src = self.tmp / "x.asm"
        inc = self.tmp / "x.inc"
        inc.write_text("here: db 1\n")
        src.write_text('bits 16\norg 0\nstart: nop\n%include "x.inc"\n')
        asm = kit.assemble(src, include=[self.tmp], listing=True)
        self.assertEqual(asm.code, b"\x90\x01")
        self.assertEqual(asm.labels, {"start": 0, "here": 1})
        self.assertEqual({p.name for p in asm.deps}, {"x.asm", "x.inc"})
        self.assertEqual(kit.nasm_deps(src, include=[self.tmp]), asm.deps)


if __name__ == "__main__":
    unittest.main()
