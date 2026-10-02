"""Static, packaging, and load-contract checks for the high-ROM capture tool."""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mods"))
import build_romdump as r  # noqa: E402


@unittest.skipIf(shutil.which("nasm") is None, "needs nasm")
class RomdumpTests(unittest.TestCase):
    """Builds into a temporary directory; build/mods release artifacts are untouched."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tempdir.cleanup)
        cls.out = Path(cls.tempdir.name)
        cls.sys_path = cls.out / r.SYS_PATH.name
        cls.img_path = cls.out / r.IMG_PATH.name
        cls.manifest_path = cls.out / r.MANIFEST_PATH.name
        cls.manifest = r.build(cls.out)
        cls.payload = cls.sys_path.read_bytes()
        cls.image = cls.img_path.read_bytes()
        cls.labels = {name: int(value, 16) for name, value in cls.manifest["labels"].items()}

    def test_mz_retains_loader_stack_and_fits_load_window(self) -> None:
        r.validate_mz(self.payload)
        fields = struct.unpack_from("<14H", self.payload)
        self.assertEqual(fields[0], 0x5A4D)
        self.assertEqual(fields[3:5], (0, 2))
        self.assertEqual(fields[7:12], (0, 0, 0, 0, 0))
        body_size = len(self.payload) - 32
        self.assertLessEqual(r.LOAD_BASE + body_size, r.LOAD_BASE + r.LOAD_WINDOW)

    def test_buffer_is_aligned_one_sector_inside_body(self) -> None:
        start = self.labels["buffer"]
        end = self.labels["buffer_end"]
        self.assertEqual(start & 1, 0)
        self.assertEqual(end - start, 512)
        self.assertLessEqual(end, len(self.payload) - 32)

    def test_two_files_and_zero_extended_metadata(self) -> None:
        root = int(self.manifest["layout"]["root_directory_offset"])
        startup = self.image[root:root + 32]
        bios = self.image[root + 32:root + 64]
        self.assertEqual(startup[:12], b"STARTUP SYS\x20")
        self.assertEqual(bios[:12], b"BIOS    BIN\x20")
        self.assertEqual(startup[0x0C:0x14], bytes(8))
        self.assertEqual(bios[0x0C:0x14], bytes(8))
        self.assertEqual(self.image[root + 64], 0)

    def test_preallocated_dump_is_exact_sentinel(self) -> None:
        first = int(self.manifest["layout"]["dump_clusters"][0])
        self.assertEqual(r.extract_file(self.image, first, r.DUMP_SIZE), r.SENTINEL)

    @unittest.skipIf(any(shutil.which(tool) is None for tool in ("mdir", "mcopy")),
                     "needs mtools")
    def test_mtools_extracts_both_exact_files(self) -> None:
        listing = subprocess.run(["mdir", "-i", str(self.img_path), "::"], check=True,
                                 capture_output=True, text=True).stdout
        self.assertIn("STARTUP  SYS", listing)
        self.assertIn("BIOS     BIN", listing)
        with tempfile.TemporaryDirectory() as directory:
            extracted_sys = Path(directory) / "STARTUP.SYS"
            extracted_bios = Path(directory) / "BIOS.BIN"
            subprocess.run(["mcopy", "-i", str(self.img_path), "::STARTUP.SYS",
                            str(extracted_sys)], check=True)
            subprocess.run(["mcopy", "-i", str(self.img_path), "::BIOS.BIN",
                            str(extracted_bios)], check=True)
            self.assertEqual(extracted_sys.read_bytes(), self.payload)
            self.assertEqual(extracted_bios.read_bytes(), r.SENTINEL)

    def test_source_uses_only_word_rom_reads_and_buffered_int41_writes(self) -> None:
        source = r.ASM.read_text()
        self.assertIn('filename:       db "BIOS    BIN", 0', source)
        self.assertRegex(source, r"mov ax, \[es:si\]")
        self.assertNotRegex(source, r"mov\s+(?:al|ah),\s*\[es:si\]")
        self.assertNotRegex(source, r"\brep\s+movs[wb]?\b")
        ports = re.findall(r"^\s*out\s+dx,\s*al", source, re.I | re.M)
        self.assertEqual(len(ports), 2)
        self.assertNotRegex(source, r"\b(?:brkxa|retxa)\b")
        self.assertEqual(set(re.findall(r"^\s*int\s+([^;\s]+)", source, re.I | re.M)),
                         {"0x41", "0x43"})

    def test_manifest_hashes_current_outputs(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        self.assertEqual(manifest["payload"]["sha256"], r.sha256(self.sys_path.read_bytes()))
        self.assertEqual(manifest["image"]["sha256"], r.sha256(self.img_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
