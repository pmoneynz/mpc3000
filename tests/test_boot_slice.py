"""Pinned-byte tests for the Vailixi 3.50 reset-to-LCD-init slice."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.linear_rom import LINEAR_SHA256, load_vailixi_linear, sha256_bytes
from tools.owner_ledger import (
    gaps,
    ledger_spans,
    load_ledger,
    notes_covered,
    validate_ff_windows,
    validate_ledger,
)
from tools.string_scan import load_scan, validate as validate_string_scan
from tools.entry_scan import load_scan as load_entry_scan
from tools.entry_scan import validate as validate_entry_scan
from tools.transfer_scan import load_scan as load_transfer_scan
from tools.transfer_scan import validate as validate_transfer_scan
from tools.v53_decode import decode_one, follow_local
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
        amx = self.facts["amx"]
        self.assertEqual(self.image[0x7B1EA:0x7B1F0], bytes.fromhex(amx["select_bytes"]))
        self.assertEqual(self.image[0x7B23A:0x7B240], bytes.fromhex(amx["idle_bytes"]))
        self.assertEqual(self.image[0x7B7E0:0x7B7E8], bytes.fromhex("df0000b0803e8793"))
        self.assertEqual(self.image[0x7B7CE:0x7B7D6], bytes.fromhex("0900bdd9f0034893"))
        self.assertEqual(self.image[0x7B396:0x7B3A6], bytes.fromhex("1e5657e89b0178119cfaff4408830c01"))
        self.assertEqual(self.image[0x7B240:0x7B24B], bytes.fromhex("b012f6e22ec41e360003d8"))
        self.assertEqual(self.image[0x7B2EE], 0xCB)
        self.assertEqual(self.image[0x30579:0x3058A], bytes.fromhex("b2079a960300fbb2069a960300fb071fcb"))
        self.assertEqual(self.image[0x59BD9:0x59BDE], bytes.fromhex("9a040037e9"))
        self.assertEqual(self.image[0x79752:0x7975A], bytes.fromhex("be6e172e8a040ac0"))
        self.assertEqual(self.image[0x7976E:0x7977E], bytes.fromhex("0d7e170a8b17089e177faa170cc81700"))
        self.assertEqual(self.image[0x797CC:0x797D2], bytes.fromhex("8ac38b1eab68"))
        self.assertEqual(self.image[0x797F2:0x797F6], bytes.fromhex("b40ce863"))
        self.assertEqual(self.image[0x798CA:0x798D6], bytes.fromhex("50538ad9b80400cd435b58c3"))
        self.assertEqual(self.image.count(bytes.fromhex("ba00ff")), 3)
        self.assertEqual(self.image[0x7AC13:0x7AC16], bytes.fromhex("ba00ff"))
        self.assertEqual(self.image[0x7ACA8:0x7ACAB], bytes.fromhex("ba00ff"))
        self.assertEqual(self.image[0x7ADC3:0x7ADC6], bytes.fromhex("ba00ff"))
        self.assertEqual(self.image[0x5518D:0x55193], bytes.fromhex("558bec8b4606"))
        self.assertEqual(self.image[0x7B1CF:0x7B1D7], bytes.fromhex("2ec53e42008b750a"))
        self.assertEqual(self.image[0x7AC61:0x7AC69], bytes.fromhex("b8a401bb40008907"))
        self.assertEqual(self.image[0x79952], 0xCF)
        self.assertEqual(self.image[0x7808C:0x78091], bytes.fromhex("83ff407405"))
        self.assertEqual(self.image[0x7B05E:0x7B062], bytes.fromhex("c705f802"))
        self.assertEqual(self.image[0x79ADC:0x79AE2], bytes.fromhex("b84720a32c00"))
        self.assertEqual(self.image[0x552A8:0x552AD], bytes.fromhex("9a570100fb"))
        public = amx["public_api"]
        self.assertEqual(public["far_call_count"], 76)
        self.assertEqual(len(public["far_call_ips"]), 19)
        self.assertEqual(self.image[0x7B1CF:0x7B1E2], bytes.fromhex("2ec53e42008b750afa8b1481e201800bc28904"))
        self.assertEqual(self.image[0x7B492:0x7B495], bytes.fromhex("894c0a"))
        self.assertEqual(self.image[0x7B21C:0x7B220], bytes.fromhex("c7040040"))
        self.assertEqual(self.image[0x7B4B9:0x7B4C3], bytes.fromhex("f70404007416c7040200"))
        self.assertEqual(self.image[0x7B157:0x7B160], bytes.fromhex("505152535657558bec"))
        records = amx["create_table"]["records"]
        self.assertEqual(len(records), 8)
        self.assertEqual(self.image[0x7B5B2:0x7B5B7], bytes.fromhex("2ec53e4200"))
        self.assertEqual(self.image[0x7B5E8], 0xCB)
        self.assertEqual(self.image[0x32596:0x3259B], bytes.fromhex("b810808ed8"))
        self.assertEqual(self.image[0x325FF], 0xCB)
        self.assertEqual(self.image[0x6C070], 0xCB)
        self.assertEqual(self.image[0x6C092], 0xCB)
        self.assertEqual(self.image[0x6AD6D], 0xCB)
        self.assertEqual(self.image[0x5DF41], 0xCB)
        self.assertEqual(self.image[0x3154E], 0xCB)
        self.assertEqual(self.image[0x3156D], 0xCB)
        self.assertEqual(self.image[0x59C03:0x59C05], bytes.fromhex("ebd9"))
        self.assertEqual(self.image[0x301A6], 0xCB)
        self.assertEqual(self.image[0x69374:0x6937C], bytes.fromhex("b810808ec08ed8cb"))
        conv = self.facts["calling_convention"]
        self.assertEqual(self.image.count(bytes.fromhex("5e060e07")), 1)
        self.assertEqual(self.image[0x79875:0x7987F], bytes.fromhex("5e060e07e803000756c3"))
        self.assertEqual(self.image[0x30600:0x3060D], bytes.fromhex("558bec8b4e069a840400fb5dcb"))
        self.assertEqual(self.image[0x59B95:0x59B9F], bytes.fromhex("558bec56571e06c57606"))
        self.assertEqual(self.image[0x59BEF:0x59BFE], bytes.fromhex("68c3061e68737f9a4500b5d983c406"))
        self.assertEqual(self.image.count(bytes.fromhex("8b4604")), 0)
        self.assertEqual(len(conv["inline_walker"]["callers"]), 3)
        wrap = self.facts["irq_wrappers"]
        self.assertEqual(self.image[0x7ADA4:0x7ADBD], bytes.fromhex(wrap["fac0_01a4"]["bytes"]))
        self.assertEqual(self.image[0x7ADBA:0x7ADBD], bytes.fromhex("0ff012"))
        self.assertEqual(self.image[0x7ADCC:0x7ADCF], bytes.fromhex("0fe012"))
        self.assertEqual(self.image[0x7B2F8:0x7B30B], bytes.fromhex(wrap["amx_02f8"]["bytes"]))
        self.assertEqual(self.image[0x7B2EF:0x7B2F8], bytes.fromhex("83ec0450b80400eb06"))
        self.assertEqual(self.image[0x7B312:0x7B31A], bytes.fromhex("8b7d0a8d7d1803f8"))
        self.assertEqual(self.image[0x7B806:0x7B80A], bytes.fromhex("30111c90"))

    def test_copy_7c92_bounds(self) -> None:
        copy = self.facts["copy_7c92"]
        src = int(copy["source_file"], 16)
        length = copy["length"]
        self.assertEqual(length, 0x7C92)
        self.assertEqual(self.image[src : src + 4], bytes.fromhex(copy["signature_bytes"]))
        self.assertEqual(self.image[src + 0x66C : src + 0x677], b"ALL EVENTS ")
        self.assertEqual(self.image.count(b"\xaa\x55"), copy["aa55_count"])
        self.assertEqual(self.image.count(bytes.fromhex("b81080")), copy["mov_ax_8010_count"])
        self.assertEqual(self.image.count(bytes.fromhex("b800a0")), copy["mov_ax_a000_count"])
        self.assertEqual(self.image.count(bytes.fromhex("00001080")), 0)
        island = int(copy["numeric_island_off"], 16)
        self.assertEqual(
            self.image[src + island : src + island + 20],
            bytes.fromhex(copy["numeric_island_bytes"]),
        )
        self.assertEqual(self.image[0x7AC74:0x7AC8F], bytes.fromhex(copy["fac0_copy"]["bytes"]))
        self.assertEqual(self.image[0x7AD34:0x7AD4B], bytes.fromhex(copy["fac0_bss"]["bytes"]))
        self.assertEqual(self.image[0x303BA:0x303D3], bytes.fromhex(copy["b03b_es_a90b"]["bytes"]))
        self.assertEqual(self.image[0x3041F:0x30431], bytes.fromhex(copy["b03b_es_8010_mailbox"]["bytes"]))
        self.assertEqual(self.image[0x7B65B:0x7B67C], bytes.fromhex(copy["amx_065b"]["bytes"]))
        self.assertEqual(self.image[0x313A5:0x313B0], bytes.fromhex(copy["ds8010_store_1d11"]["bytes"]))
        self.assertEqual(self.image[src + 0x125C : src + 0x1264], b"\x00" * 8)

    def test_owner_ledger_seed(self) -> None:
        ledger = load_ledger()
        meta = self.facts["owner_ledger"]
        checks = validate_ledger(self.image, ledger)
        self.assertGreaterEqual(len(checks), 3)
        self.assertEqual(len(ledger["ranges"]), meta["range_count"])
        self.assertEqual(ledger["owned_bytes"], meta["owned_bytes"])
        self.assertEqual(len(gaps(ledger_spans(ledger))), meta["gap_count"])
        self.assertEqual(notes_covered(ledger), meta["note_rows"])
        self.assertEqual(validate_ff_windows(self.image, ledger), meta["ff_runs_ge4"])
        self.assertNotIn("unresolved", ledger["owners"])
        self.assertFalse(any(rec["owner"] == "excluded_workspace" for rec in ledger["ranges"]))
        self.assertIsNone(next((rec for rec in ledger["ranges"] if rec["owner"] == "unresolved"), None))
        self.assertEqual(self.image[0x7B60A], 0xC3)
        self.assertEqual(self.image[0x7B615], 0xC3)
        self.assertEqual(self.image[0x7B802:0x7B80E], bytes.fromhex("78000a0030111c90b20076fb"))
        self.assertEqual(self.image[0x27CA0:0x27CB0], b"\x00" * 16)
        self.assertEqual(self.image[0x56E40], 0x90)
        self.assertEqual(self.image[0x59BD8], 0xCB)
        self.assertEqual(self.image[0x798C9], 0xC3)
        self.assertGreaterEqual(
            sum(1 for rec in ledger["ranges"] if rec.get("kind") == "align"), 26
        )

    def test_string_scan_consumers(self) -> None:
        scan = load_scan()
        meta = self.facts["string_scan"]
        checks = validate_string_scan(self.image, scan)
        self.assertGreaterEqual(len(checks), 4)
        self.assertEqual(scan["established"]["unique_starts"], meta["established_unique"])
        self.assertEqual(scan["push_ds_far"]["count"], meta["push_ds_far_count"])
        self.assertEqual(scan["push_ds_far"]["top_callee"], "B1B1:005B")
        self.assertEqual(scan["directory"]["ptr_8010"], 345)
        self.assertEqual(scan["directory"]["empty_targets"], 2)
        self.assertEqual(scan["disk_label_table"]["count"], 27)
        self.assertEqual(len(scan["walker_inline"]), 3)
        self.assertFalse(scan["candidates"]["kadak"]["established"])
        self.assertEqual(self.image[0x31B6B:0x31B91], bytes.fromhex(scan["put_string"]["bytes"]))
        self.assertEqual(self.image[0x31B90], 0xCB)
        self.assertEqual(self.image[0x210F5:0x210F5 + 26], b"Vailixi 3.50 (---/--/----)")
        self.assertIn(b"mpc3000le@yahoo.com.au", self.image[0x79A1A:0x79AD2])

    def test_entry_scan_consumers(self) -> None:
        entries = load_entry_scan()
        meta = self.facts["entry_scan"]
        checks = validate_entry_scan(self.image, entries)
        self.assertGreaterEqual(len(checks), 4)
        self.assertEqual(entries["established"]["unique_cs_ip"], meta["unique_cs_ip"])
        self.assertEqual(entries["raw_encodings"]["callf_9a"], 6154)
        self.assertEqual(entries["raw_encodings"]["jmpf_ea"], 825)
        self.assertEqual(entries["push_ds_far"]["unique_targets"], 67)
        self.assertEqual(entries["push_ds_far"]["top"]["cs_ip"], "B1B1:005B")
        self.assertEqual(self.image[0x7FF00:0x7FF03], bytes.fromhex("baeaff"))
        self.assertEqual(self.image[0x797A6:0x797A9], bytes.fromhex("e89a00"))
        self.assertEqual(self.image[0x7FFF0:0x7FFF5], bytes.fromhex("ea0000f0ff"))
        self.assertEqual(entries["create_table"][6]["cs_ip"], "D9BD:0009")

    def test_transfer_scan_exits(self) -> None:
        transfers = load_transfer_scan()
        meta = self.facts["transfer_scan"]
        checks = validate_transfer_scan(self.image, transfers)
        self.assertGreaterEqual(len(checks), 3)
        self.assertEqual(transfers["entries"], meta["entries"])
        self.assertEqual(transfers["status_counts"]["bounded"], 128)
        self.assertEqual(transfers["status_counts"]["indirect"], 14)
        self.assertEqual(transfers["status_counts"]["loop"], 1)
        self.assertEqual(transfers["discovered"]["jmpf_unestablished"], 0)
        self.assertEqual(transfers["discovered"]["callf_new"], 74)
        self.assertEqual(transfers["discovered"]["calln_new"], 42)
        self.assertEqual(self.image[0x7B23A:0x7B240], bytes.fromhex("90909090ebfa"))
        self.assertEqual(self.image[0x31B90], 0xCB)
        idle = transfers["specimens"]["idle"]
        self.assertEqual(idle["cs_ip"], "FB00:023A")
        self.assertEqual(idle["status"], "loop")
        insns, hit_limit = follow_local(self.image, 0xFB00, 0x023A)
        self.assertFalse(hit_limit)
        self.assertEqual(len(insns), 5)
        self.assertEqual(insns[-1].kind, "JMPS")

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
