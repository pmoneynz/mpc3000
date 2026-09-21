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
        self.assertEqual(self.image[0x319FD], 0xCB)
        self.assertEqual(self.image[0x59BD8], 0xCB)
        self.assertEqual(self.image[0x798C9], 0xC3)
        self.assertEqual(self.image[0x55F64:0x55F7A], bytes.fromhex("6d00d10057016501fb01fb018a01fb01fb01fb01fb01"))
        self.assertEqual(self.image[0x5B447:0x5B461], bytes.fromhex("59006e00c400de00f80006011401220154016e018801a201be01"))
        self.assertEqual(self.image[0x55206:0x55218], bytes.fromhex("e700e200f600f100ec00ff00ff00ff00dd00"))
        self.assertEqual(self.image[0x31FE2:0x31FFC], bytes.fromhex("ec020f040f040f040f040f040f046f030f04f2020f040f044c03"))
        self.assertEqual(self.image[0x79B26:0x79B36], bytes.fromhex("821bb11bb51b981cad1cb81ceb1c081d"))
        self.assertEqual(self.image[0x561AA:0x561AF], bytes.fromhex("9a570100fb"))
        self.assertEqual(self.image[0x5D9AE:0x5D9B3], bytes.fromhex("803ebd8102"))
        self.assertEqual(self.image[0x5DBBB], 0xCB)
        self.assertEqual(self.image[0x79E81:0x79E85], bytes.fromhex("807e0203"))
        self.assertEqual(self.image[0x79E96], 0xC3)
        self.assertEqual(self.image[0x5614D:0x5614F], bytes.fromhex("e450"))
        self.assertEqual(self.image[0x561A8], 0xC3)
        self.assertEqual(self.image[0x30D01:0x30D15], bytes.fromhex("3606490659067d067d068d065906ad069d065906"))
        self.assertEqual(self.image[0x6B7E2:0x6B7EC], bytes.fromhex("2100310041005f008800"))
        self.assertEqual(self.image[0x58BCA:0x58BDC], bytes.fromhex("ad013600ad013000cc0008012f0126010e01"))
        self.assertEqual(self.image[0x53CAC:0x53CBC], bytes.fromhex("a201b401c601d801200220020702ec01"))
        self.assertEqual(self.image[0x5660C:0x56618], bytes.fromhex("be047804a3040f06d0064807"))
        self.assertEqual(self.image[0x553FF:0x55417], bytes.fromhex("d800d8003c012e0100000000bf00e700000000004a010000"))
        self.assertEqual(self.image[0x55420:0x55430], bytes.fromhex("000000004301350100000000d000f800"))
        self.assertEqual(self.image[0x56618:0x5661D], bytes.fromhex("9a0a00f4d6"))
        self.assertEqual(self.image[0x7B989:0x7B996], bytes.fromhex("5052cd42ba10c0b060ee5a58cf"))
        self.assertEqual(self.image[0x7B9AE:0x7B9BD], bytes.fromhex("b893fb8ec0bb5900b2089a470300fb"))
        self.assertEqual(self.image[0x798FB:0x798FF], bytes.fromhex("8db70619"))
        self.assertEqual(self.image[0x79906:0x79916], bytes.fromhex("000008000100090002000a0003000b00"))
        self.assertEqual(self.image[0x559CC:0x559D1], bytes.fromhex("2effa56105"))
        self.assertEqual(self.image[0x5599F:0x559A5], bytes.fromhex("c0eb0383e30e"))
        self.assertEqual(self.image[0x559AA:0x559BA], bytes.fromhex("1d06d7051306fd05e705f70503064a05"))
        self.assertEqual(self.image[0x559BA:0x559C5], bytes.fromhex("bb1f05d1e6899c2e76d1ee"))
        self.assertEqual(
            self.image[0x559D1:0x559F1],
            bytes.fromhex("81058705a505ab05d605d605c905d605b105d605b705bd05c305d605d605d605"),
        )
        self.assertEqual(self.image[0x559F1:0x559F4], bytes.fromhex("bbe107"))
        self.assertEqual(self.image[0x5DB63:0x5DB68], bytes.fromhex("2e8b8c1c02"))
        self.assertEqual(self.image[0x5DBBC:0x5DBC8], bytes.fromhex("040001000100040060000100"))
        self.assertEqual(self.image[0x5DA0B:0x5DA10], bytes.fromhex("2e8b9f2f02"))
        self.assertEqual(
            self.image[0x5DBCF:0x5DBEF],
            bytes.fromhex("000140018001c001000240028002c002000340038003c003000440048004c004"),
        )
        self.assertEqual(self.image[0x5DA9D:0x5DAA2], bytes.fromhex("2e8b9f4f02"))
        self.assertEqual(
            self.image[0x5DBEF:0x5DC0F],
            bytes.fromhex("02000400060008000a000c000e0010002000400060008000a000c000e0000001"),
        )
        self.assertEqual(self.image[0x79D23:0x79D28], bytes.fromhex("2e8b879420"))
        self.assertEqual(self.image[0x7A094:0x7A09A], bytes.fromhex("9a20a820b620"))
        self.assertEqual(self.image[0x5E600:0x5E605], bytes.fromhex("9a2200b1b1"))
        self.assertEqual(self.image[0x31B32:0x31B36], bytes.fromhex("a11a1dcb"))
        self.assertEqual(self.image[0x309B7:0x309BC], bytes.fromhex("9a120361b2"))
        self.assertEqual(self.image[0x32922:0x32928], bytes.fromhex("c60648e700cb"))
        self.assertEqual(self.image[0x44351:0x44356], bytes.fromhex("9a810004e7"))
        self.assertEqual(self.image[0x670C1:0x670CB], bytes.fromhex("0ee882ff9a080014e6cb"))
        self.assertEqual(self.image[0x5EA49:0x5EA4E], bytes.fromhex("9a25016fe5"))
        self.assertEqual(self.image[0x65815:0x65820], bytes.fromhex("9cfaa122d88b1624d89dcb"))
        self.assertEqual(self.image[0x670C5:0x670CA], bytes.fromhex("9a080014e6"))
        self.assertEqual(self.image[0x66148:0x6614D], bytes.fromhex("803eed8900"))
        self.assertEqual(self.image[0x66173], 0xCB)
        self.assertEqual(self.image[0x5EAA6:0x5EAAB], bytes.fromhex("9a880088e6"))
        self.assertEqual(self.image[0x66908:0x66920], bytes.fromhex("8b169fd6eb0aa19fd62bc23d14007f07803edd980075efcb"))
        self.assertEqual(self.image[0x53B90:0x53B93], bytes.fromhex("e817ff"))
        self.assertEqual(self.image[0x53AAA:0x53AC8], bytes.fromhex("512bc0b010e6a4b9e803e2feb000e6a4b903009a840400fbe4aa0ac059c3"))
        self.assertEqual(self.image[0x53BB1:0x53BB6], bytes.fromhex("2e0a870c00"))
        self.assertEqual(self.image[0x53A7C:0x53A84], bytes.fromhex("0102040810204080"))
        self.assertEqual(self.image[0x53C1F:0x53C22], bytes.fromhex("e8fefe"))
        self.assertEqual(self.image[0x53B20:0x53B27], bytes.fromhex("b0ffe6a8e8a1ff"))
        self.assertEqual(self.image[0x53B77], 0xC3)
        self.assertEqual(self.image[0x53AC8:0x53ACF], bytes.fromhex("5152ba01c0b000"))
        self.assertEqual(self.image[0x53B1F], 0xC3)
        self.assertEqual(self.image[0x30C81:0x30C86], bytes.fromhex("9a0f00dab2"))
        self.assertEqual(self.image[0x32DAF:0x32DB5], bytes.fromhex("558bec83ec04"))
        self.assertEqual(self.image[0x32E78], 0xCB)
        self.assertEqual(self.image[0x5B9FB:0x5B9FE], bytes.fromhex("e8af02"))
        self.assertEqual(self.image[0x5BCAD:0x5BCB4], bytes.fromhex("558becc45e0626"))
        self.assertEqual(self.image[0x5BCD3], 0xCB)
        self.assertEqual(self.image[0x7A687:0x7A68A], bytes.fromhex("e86dfa"))
        self.assertEqual(self.image[0x7A6A8:0x7A6AB], bytes.fromhex("e84cfa"))
        self.assertEqual(self.image[0x7A0F7:0x7A0FA], bytes.fromhex("590e51"))
        self.assertEqual(self.image[0x31F42:0x31F45], bytes.fromhex("e8bbfc"))
        self.assertEqual(self.image[0x31C00:0x31C08], bytes.fromhex("558bec57c47e0633"))
        self.assertEqual(self.image[0x31C6E], 0xCB)
        self.assertEqual(self.image[0x5EB1B:0x5EB20], bytes.fromhex("9a5401a2dc"))
        self.assertEqual(self.image[0x5CB74:0x5CB79], bytes.fromhex("b059e9bdfe"))
        self.assertEqual(self.image[0x44470:0x44473], bytes.fromhex("e84600"))
        self.assertEqual(
            self.image[0x444B9:0x444E5],
            bytes.fromhex(
                "558bec9a0200b1b1ff7608ff76069a5b00b1b183c404"
                "1e68c24e9a5b00b1b183c4049a0000e0d6b84d005dcb"
            ),
        )
        self.assertEqual(self.image[0x7A4A5:0x7A4A8], bytes.fromhex("e885ff"))
        self.assertEqual(self.image[0x7A42D:0x7A433], bytes.fromhex("558bec56571e"))
        self.assertEqual(self.image[0x7A458:0x7A45B], bytes.fromhex("c20800"))
        self.assertEqual(self.image[0x4437F:0x44384], bytes.fromhex("9a0c00d0c2"))
        self.assertEqual(self.image[0x42D0C:0x42D14], bytes.fromhex("558bec83ec06561e"))
        self.assertEqual(self.image[0x42E66], 0xCB)
        self.assertEqual(self.image[0x44405:0x4440A], bytes.fromhex("9a0f00edb3"))
        self.assertEqual(self.image[0x33EDF:0x33EE7], bytes.fromhex("558bec83ec141e68"))
        self.assertEqual(self.image[0x33FD5], 0xCB)
        self.assertEqual(self.image[0x4440F:0x44414], bytes.fromhex("9a05004ec4"))
        self.assertEqual(self.image[0x444E5:0x444ED], bytes.fromhex("558bec83ec021e68"))
        self.assertEqual(self.image[0x44529:0x4452C], bytes.fromhex("83fb04"))
        self.assertEqual(self.image[0x4452E:0x44535], bytes.fromhex("d1e32effa7b800"))
        self.assertEqual(self.image[0x44535:0x4453E], bytes.fromhex("900ee8bf008ad0eb55"))
        self.assertEqual(self.image[0x44596:0x44598], bytes.fromhex("c9cb"))
        self.assertEqual(self.image[0x44598:0x445A2], bytes.fromhex("55005e00670070007900"))
        self.assertEqual(self.image[0x443EB:0x443F0], bytes.fromhex("9a0700e6c2"))
        self.assertEqual(self.image[0x42E67:0x42E6F], bytes.fromhex("558bec83ec021e68"))
        self.assertEqual(self.image[0x43033], 0xCB)
        self.assertEqual(self.image[0x44428:0x4442D], bytes.fromhex("9a0800bfce"))
        self.assertEqual(self.image[0x4EBF8:0x4EC00], bytes.fromhex("558bec83ec041e68"))
        self.assertEqual(self.image[0x4ED22:0x4ED25], bytes.fromhex("83fb03"))
        self.assertEqual(self.image[0x4ED27:0x4ED2E], bytes.fromhex("d1e32effa76a02"))
        self.assertEqual(self.image[0x4ED2E:0x4ED31], bytes.fromhex("8a46fc"))
        self.assertEqual(self.image[0x4EE59], 0xCB)
        self.assertEqual(self.image[0x4EE5A:0x4EE62], bytes.fromhex("3e01750189018901"))
        self.assertEqual(self.image[0x44446:0x4444B], bytes.fromhex("9a02001abe"))
        self.assertEqual(self.image[0x3E1A2:0x3E1AA], bytes.fromhex("558bec83ec02561e"))
        self.assertEqual(self.image[0x3E283:0x3E286], bytes.fromhex("83fb03"))
        self.assertEqual(self.image[0x3E28B:0x3E292], bytes.fromhex("d1e32effa7fb01"))
        self.assertEqual(self.image[0x3E292:0x3E296], bytes.fromhex("6a106a07"))
        self.assertEqual(self.image[0x3E39A], 0xCB)
        self.assertEqual(self.image[0x3E39B:0x3E3A3], bytes.fromhex("f200050131018501"))
        self.assertEqual(self.image[0x3E210:0x3E213], bytes.fromhex("e89001"))
        self.assertEqual(self.image[0x3E3A3:0x3E3AB], bytes.fromhex("558becba0400803e"))
        self.assertEqual(self.image[0x3E3CA], 0xCB)
        self.assertEqual(self.image[0x3E2C9:0x3E2CC], bytes.fromhex("e8ff00"))
        self.assertEqual(self.image[0x3E3CB:0x3E3D3], bytes.fromhex("558bec6a1b6a029a"))
        self.assertEqual(self.image[0x3E40B], 0xCB)
        self.assertEqual(self.image[0x44450:0x44455], bytes.fromhex("9a6c021abe"))
        self.assertEqual(self.image[0x3E40C:0x3E414], bytes.fromhex("558bec83ec0e5657"))
        self.assertEqual(self.image[0x3E55A:0x3E55D], bytes.fromhex("83fb03"))
        self.assertEqual(self.image[0x3E699:0x3E69C], bytes.fromhex("83fb04"))
        self.assertEqual(self.image[0x3E738:0x3E73B], bytes.fromhex("83fb03"))
        self.assertEqual(self.image[0x3E7CF:0x3E7E9], bytes.fromhex("a405b805cc05e00508051c05440568057d05c903f10318043f04"))
        self.assertEqual(self.image[0x44356:0x4435B], bytes.fromhex("9a040003c3"))
        self.assertEqual(self.image[0x4436F:0x44374], bytes.fromhex("9a0600fdb3"))
        self.assertEqual(self.image[0x33FD6:0x33FDE], bytes.fromhex("558bec83ec3a5657"))
        self.assertEqual(self.image[0x343A9:0x343AC], bytes.fromhex("83fb0d"))
        self.assertEqual(self.image[0x34433:0x34436], bytes.fromhex("83fb0c"))
        self.assertEqual(self.image[0x3460D:0x34610], bytes.fromhex("83fb0d"))
        self.assertEqual(
            self.image[0x34841:0x34893],
            bytes.fromhex(
                "a8065b08bd07c4075b085b085b085b085b08a8064c065b085a06a806"
                "72047a043a064c05fa05fa05fa05db05fa05540574050506b605"
                "26044d044d044d044d044d044d044d0403044d044d04e503f4030304"
            ),
        )
        self.assertEqual(self.image[0x43034:0x4303C], bytes.fromhex("558bec83ec1a5657"))
        self.assertEqual(self.image[0x43319:0x4331C], bytes.fromhex("83fb12"))
        self.assertEqual(self.image[0x439A5:0x439A8], bytes.fromhex("83fb0d"))
        self.assertEqual(
            self.image[0x43BFC:0x43C3E],
            bytes.fromhex(
                "0c0ab80bb80bb80bb80b7c0bb80bb80be209b80bb80b8409a409b809"
                "f8021d048604be04e1041b0907056805740684060c0808070c080c0800090c080c0808070807"
            ),
        )
        self.assertGreaterEqual(
            sum(1 for rec in ledger["ranges"] if rec.get("kind") == "align"), 26
        )
        self.assertEqual(self.image[0x31B11], 0xFF)
        self.assertEqual(
            sum(
                1
                for rec in ledger["ranges"]
                if rec.get("kind") == "padding" and int(rec["end"], 16) - int(rec["start"], 16) == 1
            ),
            28,
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
