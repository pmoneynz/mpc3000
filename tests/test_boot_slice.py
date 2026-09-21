"""Pinned-byte tests for the Vailixi 3.50 reset-to-LCD-init slice."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.linear_rom import LINEAR_SHA256, load_vailixi_linear, sha256_bytes
from tools.v53_decode import decode_one
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

    def test_init_table_and_amx_entry(self) -> None:
        table = self.facts["init_table"]
        off = int(table["file"], 16)
        packed = bytes.fromhex("".join(rec["bytes"] for rec in table["records"]))
        self.assertEqual(self.image[off : off + len(packed)], packed)
        self.assertEqual(self.image[0x7B00C:0x7B00E], bytes.fromhex("eb40"))
        self.assertEqual(self.image[0x7B13E:0x7B148], bytes.fromhex("2ec53e4200e8a400ebf6"))
        self.assertEqual(self.image[0x7813E:0x78143], bytes.fromhex("5f5e071fcb"))
        self.assertEqual(self.image[0x79B25], 0xCB)

    def test_copy_7c92_bounds(self) -> None:
        copy = self.facts["copy_7c92"]
        src = int(copy["source_file"], 16)
        length = copy["length"]
        self.assertEqual(length, 0x7C92)
        self.assertEqual(self.image[src : src + 4], bytes.fromhex(copy["signature_bytes"]))
        self.assertEqual(self.image[src + 0x66C : src + 0x677], b"ALL EVENTS ")
        self.assertEqual(self.image.count(b"\xaa\x55"), 1)

    def test_v53_decode_brkxa_retxa(self) -> None:
        brk = decode_one(self.image, 0xFAC0, 0x001C)
        self.assertEqual(brk.kind, "BRKXA")
        self.assertEqual(brk.text, "BRKXA 0x11")
        ret = decode_one(self.image, 0xFAC0, 0x009F)
        self.assertEqual(ret.kind, "RETXA")
        self.assertEqual(ret.text, "RETXA 0x12")
        jmp = decode_one(self.image, 0xFAC0, 0x019E)
        self.assertEqual(jmp.kind, "JMPF")
        self.assertEqual((jmp.target_cs, jmp.target_ip), (0xB000, 0x00DF))


if __name__ == "__main__":
    unittest.main()
