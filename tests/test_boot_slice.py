"""Pinned-byte tests for the Vailixi 3.50 reset-to-LCD-init slice."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.linear_rom import LINEAR_SHA256, load_vailixi_linear, sha256_bytes
from tools.verify_boot_slice import FACTS_PATH, verify


class BootSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.image = load_vailixi_linear()
        cls.facts = json.loads(FACTS_PATH.read_text())

    def test_linear_identity(self) -> None:
        self.assertEqual(sha256_bytes(self.image), LINEAR_SHA256)
        self.assertEqual(len(self.image), 524288)

    def test_all_pinned_facts(self) -> None:
        checks = verify(self.image, self.facts)
        self.assertGreaterEqual(len(checks), 10)

    def test_brkxa_continue_in_place(self) -> None:
        ip = self.image[0x44] | (self.image[0x45] << 8)
        cs = self.image[0x46] | (self.image[0x47] << 8)
        self.assertEqual((cs, ip), (0xFAC0, 0x001F))
        self.assertEqual(self.image[0x7AC1C:0x7AC1F], bytes.fromhex("0fe011"))


if __name__ == "__main__":
    unittest.main()
