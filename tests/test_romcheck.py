"""Static and packaging checks for the read-only ROM identity diagnostic."""

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
import build_romcheck as r  # noqa: E402


@unittest.skipIf(any(shutil.which(tool) is None for tool in ("nasm", "mformat", "mcopy")),
                 "needs nasm and mtools")
class RomcheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = r.build()
        cls.payload = r.SYS_PATH.read_bytes()
        cls.body = cls.payload[32:]
        cls.labels = {name: int(value, 16) for name, value in cls.manifest["labels"].items()}
        cls.reference = r.interleave(r.LS_PATH, r.MS_PATH)[0x78000:0x80000]

    def test_mz_and_embedded_reference(self) -> None:
        fields = struct.unpack_from("<14H", self.payload)
        self.assertEqual(fields[0], 0x5A4D)
        self.assertEqual(fields[3:5], (0, 2))
        self.assertEqual(fields[7:12], (0, 0, 0, 0, 0))
        size = fields[2] * 512 if fields[1] == 0 else (fields[2] - 1) * 512 + fields[1]
        self.assertEqual(size, len(self.payload))
        start = self.labels["expected_bios"]
        self.assertEqual(self.body[start:start + 0x8000], self.reference)
        self.assertEqual(struct.unpack_from("<H", self.body, self.labels["expected_sum"])[0], 0x8634)
        self.assertEqual(struct.unpack_from("<H", self.body, self.labels["expected_crc"])[0],
                         r.crc16_ccitt_false(self.reference))

    def test_report_math_for_reference_and_312(self) -> None:
        target = self.manifest["expected_screens"]["vailixi_repo_target"]
        self.assertEqual(target["actual_word_sum"], "8634")
        self.assertEqual(target["mismatch_count"], 0)
        self.assertEqual(target["block_8k_mismatch_counts"], [0, 0, 0, 0])
        bios312 = r.interleave(r.LS312_PATH, r.MS312_PATH)[0x78000:0x80000]
        stock = r.compare_summary(self.reference, bios312)
        recorded = self.manifest["expected_screens"]["stock_3_12"]
        self.assertEqual({key: recorded[key] for key in stock}, stock)
        self.assertGreater(stock["mismatch_count"], 0)
        self.assertEqual(stock["actual_word_sum"], "562C")
        self.assertEqual(recorded["report_rows"], [
            "ROMCHECK4 STOP",
            "SUM EXP 8634 ACT 562C",
            "REF CRC EXP 79E8 ACT 79E8 OK ",
            "DIFF 0518C FIRST 78133 LAST 7FECC",
            "8K 00534 01705 01F42 01611",
            "OFF 78133 EXP:32312F30382F3037",
            "          GOT:30332F32332F3936",
            "NO OS COPY - POWER OFF / PHOTO",
        ])

    def test_image_has_only_startup_sys_and_matches_payload(self) -> None:
        image = r.IMG_PATH.read_bytes()
        entry = image[r.FAT12_ROOT_OFFSET:r.FAT12_ROOT_OFFSET + 32]
        self.assertEqual(entry[:12], b"STARTUP SYS\x20")
        self.assertEqual(entry[0x0C:0x14], bytes(8))
        listing = subprocess.run(["mdir", "-i", str(r.IMG_PATH), "::"], check=True,
                                 capture_output=True, text=True).stdout
        self.assertIn("STARTUP  SYS", listing)
        self.assertNotIn("ROMCHECK SYS", listing)
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory) / "STARTUP.SYS"
            subprocess.run(["mcopy", "-i", str(r.IMG_PATH), "::STARTUP.SYS", str(extracted)], check=True)
            self.assertEqual(extracted.read_bytes(), self.payload)

    def test_source_has_no_direct_device_io(self) -> None:
        source = r.ASM.read_text()
        self.assertIsNone(re.search(
            r"^\s*(?:in|insb|insw|out|outsb|outsw|brkxa|retxa)\b", source, re.I | re.M
        ))
        interrupts = re.findall(r"^\s*int\s+([^;\s]+)", source, re.I | re.M)
        self.assertEqual(set(interrupts), {"0x43"})
        self.assertIn("ROMCHECK4 STOP", source)
        self.assertIn("ROMCHECK4 ENTER", source)
        self.assertIn("NO OS COPY - POWER OFF / PHOTO", source)

    def test_manifest_hashes_current_outputs(self) -> None:
        manifest = json.loads(r.MANIFEST_PATH.read_text())
        self.assertEqual(manifest["payload"]["sha256"], r.sha256(r.SYS_PATH.read_bytes()))
        self.assertEqual(manifest["image"]["sha256"], r.sha256(r.IMG_PATH.read_bytes()))
        self.assertEqual(manifest["reference"]["sha256"], r.sha256(self.reference))


if __name__ == "__main__":
    unittest.main()
