"""Static, packaging, and guard-substitution checks for ROMAPP."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mods"))
import build_romapp as r  # noqa: E402


@unittest.skipIf(shutil.which("nasm") is None, "needs nasm")
@unittest.skipUnless(r.CAPTURED_BIOS.exists(),
                     "needs the preserved physical capture build/hardware/2026-10-01-romdump/BIOS.BIN")
class RomappTests(unittest.TestCase):
    """Builds into a temporary directory; build/mods release artifacts are untouched."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tempdir.name) / "out"
        cls.sys_path = cls.out / r.SYS_PATH.name
        cls.img_path = cls.out / r.IMG_PATH.name
        cls.manifest_path = cls.out / r.MANIFEST_PATH.name
        cls.manifest = r.build(cls.out)
        cls.payload = cls.sys_path.read_bytes()
        cls.body = cls.payload[32:]
        cls.image = cls.img_path.read_bytes()
        cls.labels = {name: int(value, 16) for name, value in cls.manifest["labels"].items()}

        generic = r.fat12.interleave(r.fat12.LS_PATH.read_bytes(),
                                     r.fat12.MS_PATH.read_bytes())[0x78000:0x80000]
        cls.generic_path = Path(cls.tempdir.name) / "generic-high.bin"
        cls.generic_path.write_bytes(generic)
        cls.generic_body, cls.generic_labels = r.assemble(
            cls.generic_path, "romapp-test-generic", cls.out
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_final_payload_pins_preserved_physical_guard(self) -> None:
        r.validate_mz(self.payload)
        self.assertEqual(r.sha256(r.CAPTURED_BIOS.read_bytes()), r.CAPTURED_BIOS_SHA256)
        start = self.labels["expected_bios"]
        end = self.labels["expected_bios_end"]
        self.assertEqual(end - start, 0x8000)
        self.assertEqual(self.body[start:end], r.CAPTURED_BIOS.read_bytes())
        self.assertEqual(self.manifest["high_bios_guard"]["sha256"],
                         r.CAPTURED_BIOS_SHA256)

    def test_data_only_guard_substitution_cannot_change_code_or_buffer(self) -> None:
        for name, value in self.labels.items():
            self.assertEqual(self.generic_labels[name], value)
        start = self.labels["expected_bios"]
        end = self.labels["expected_bios_end"]
        self.assertEqual(self.generic_body[:start], self.body[:start])
        self.assertEqual(self.generic_body[end:], self.body[end:])
        self.assertNotEqual(self.generic_body[start:end], self.body[start:end])
        expected = self.generic_path.read_bytes()
        self.assertEqual(self.generic_body[start:end], expected)

    def test_body_and_working_objects_remain_in_shared_translated_ram(self) -> None:
        body_size = len(self.payload) - 32
        self.assertLess(body_size, 0x10000)
        self.assertLessEqual(r.LOAD_BASE + body_size, r.SHARED_RAM_END)
        self.assertEqual(self.manifest["payload"]["body_end"],
                         f"0x{r.LOAD_BASE + body_size:05X}")
        self.assertEqual(self.labels["buffer"] & 1, 0)
        self.assertEqual(self.labels["buffer_end"] - self.labels["buffer"], 0x4000)
        self.assertEqual(self.labels["buffer_end"], self.labels["expected_bios"])

    def test_image_has_exact_preallocated_capture_file(self) -> None:
        root = int(self.manifest["layout"]["root_directory_offset"])
        startup = self.image[root:root + 32]
        output = self.image[root + 32:root + 64]
        self.assertEqual(startup[:12], b"STARTUP SYS\x20")
        self.assertEqual(output[:12], b"ROMAPP  BIN\x20")
        self.assertEqual(startup[0x0C:0x14], bytes(8))
        self.assertEqual(output[0x0C:0x14], bytes(8))
        self.assertEqual(struct.unpack_from("<I", output, 28)[0], r.OUTPUT_SIZE)
        first = int(self.manifest["layout"]["output_clusters"][0])
        self.assertEqual(r.extract_contiguous(self.image, first, r.OUTPUT_SIZE), r.SENTINEL)
        self.assertEqual(self.manifest["layout"]["output_cluster_count"], 672)

    @unittest.skipIf(any(shutil.which(tool) is None for tool in ("mdir", "mcopy")),
                     "needs mtools")
    def test_mtools_extracts_final_payload_and_sentinel(self) -> None:
        listing = subprocess.run(["mdir", "-i", str(self.img_path), "::"], check=True,
                                 capture_output=True, text=True).stdout
        self.assertIn("STARTUP  SYS", listing)
        self.assertIn("ROMAPP   BIN", listing)
        with tempfile.TemporaryDirectory() as directory:
            sys_path = Path(directory) / "STARTUP.SYS"
            output_path = Path(directory) / "ROMAPP.BIN"
            subprocess.run(["mcopy", "-i", str(self.img_path), "::STARTUP.SYS",
                            str(sys_path)], check=True)
            subprocess.run(["mcopy", "-i", str(self.img_path), "::ROMAPP.BIN",
                            str(output_path)], check=True)
            self.assertEqual(sys_path.read_bytes(), self.payload)
            self.assertEqual(output_path.read_bytes(), r.SENTINEL)

    def test_final_manifest_hashes_current_outputs(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        self.assertEqual(manifest["payload"]["sha256"], r.sha256(self.sys_path.read_bytes()))
        self.assertEqual(manifest["image"]["sha256"], r.sha256(self.img_path.read_bytes()))
        self.assertEqual(manifest["scope"]["captured_linear_file_range"],
                         ["0x20000", "0x74000"])
        self.assertEqual(manifest["scope"]["remaining_uncaptured_linear_ranges"],
                         [["0x00000", "0x20000"], ["0x74000", "0x78000"]])

    def test_fixture_builder_cannot_overwrite_physical_candidate(self) -> None:
        before = (self.sys_path.read_bytes(), self.img_path.read_bytes())
        with self.assertRaises(ValueError):
            r.build_test_fixture(self.generic_path, "ROMAPP", self.out)
        r.build_test_fixture(self.generic_path, "ROMAPP-TEST-GENERIC", self.out)
        self.assertEqual((self.sys_path.read_bytes(), self.img_path.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
