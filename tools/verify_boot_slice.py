#!/usr/bin/env python3
"""Reproduce the pinned Vailixi 3.50 reset-to-LCD-init facts from the chip pair."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

REPO_ROOT = Path(__file__).resolve().parents[1]
FACTS_PATH = REPO_ROOT / "analysis" / "boot_slice_facts.json"


def _u16(image: bytes, offset: int) -> int:
    return image[offset] | (image[offset + 1] << 8)


def _expect_hex(image: bytes, offset: int, expected_hex: str, label: str) -> None:
    raw = bytes.fromhex(expected_hex)
    got = image[offset : offset + len(raw)]
    if got != raw:
        raise AssertionError(f"{label}: file 0x{offset:05X} expected {expected_hex}, got {got.hex()}")


def verify(image: bytes, facts: dict) -> list[str]:
    checks: list[str] = []

    if sha256_bytes(image) != LINEAR_SHA256:
        raise AssertionError("linear SHA-256 does not match the pinned identity")
    checks.append("linear SHA-256")

    _expect_hex(image, 0x7FFF0, facts["reset"]["bytes"], "reset vector")
    checks.append("reset vector EA FFF0:0000")

    _expect_hex(image, 0x7FF3F, facts["wait_state_stub"]["final_jmp"], "stub far jump")
    checks.append("FFF0 stub jmp FAC0:0000")

    if image[0x7FF00:0x7FF03] != bytes.fromhex("baeaff"):
        raise AssertionError("wait-state stub does not begin MOV DX,0xFFEA")
    checks.append("stub starts at FFEA")

    for name, key in (("IVT11", "vector_11"), ("IVT12", "vector_12"), ("IVT14", "vector_14")):
        rec = facts["rom_ivt_templates"][key]
        _expect_hex(image, int(rec["file"], 16), rec["bytes"], name)
        checks.append(f"ROM {name} {rec['cs_ip']}")

    if any(b != 0xFF for b in image[0:0x44]):
        raise AssertionError("file [0x00000,0x00044) is not FF padding")
    if any(b != 0xFF for b in image[0x54:0x20000]):
        raise AssertionError("file [0x00054,0x20000) is not FF padding")
    checks.append("low 128 KiB padding except three IVT slots")

    pgr0 = _u16(image, 0x7AE56)
    if pgr0 != 0x00C0:
        raise AssertionError(f"PGR[0] expected 0x00C0, got 0x{pgr0:04X}")
    checks.append("PGR[0] -> 0x300000")

    p61 = facts["pgr61"]
    _expect_hex(image, int(p61["first_file"], 16), p61["word_bytes"], "PGR[61] first")
    _expect_hex(image, int(p61["second_file"], 16), p61["word_bytes"], "PGR[61] second")
    _expect_hex(image, int(p61["third_file"], 16), p61["word_bytes"], "PGR[61] third")
    _expect_hex(image, int(p61["d9b5_es_file"], 16), p61["d9b5_es_bytes"], "D9B5 ES=F400")
    _expect_hex(image, int(p61["d9b5_sig_file"], 16), p61["d9b5_sig_bytes"], "D9B5 ES:[03FE]")
    word61 = int(p61["word"], 16)
    if word61 != int.from_bytes(bytes.fromhex(p61["word_bytes"]), "little"):
        raise AssertionError("pgr61.word does not match word_bytes")
    if (word61 << 14) != int(p61["phys24_base"], 16):
        raise AssertionError("full-word v33_translate of PGR[61] is not 0x500000")
    sig24 = int(p61["phys24_base"], 16) | int(p61["sig_off"], 16)
    if sig24 != int(p61["sig_phys24"], 16):
        raise AssertionError("ES:[03FE] 24-bit is not 0x5003FE")
    if not (int(p61["mame_nvram_lo"], 16) <= sig24 <= int(p61["mame_nvram_hi"], 16)):
        raise AssertionError("0x5003FE is outside the MAME NVRAM window")
    slot = int(p61["only_nonzero_high_byte_slot"])
    for label, base in (
        ("first", 0x7AE56),
        ("second", 0x7ACB4),
        ("third", 0x7ADCF),
    ):
        highs = [image[base + i * 2 + 1] for i in range(64)]
        nonzero = [i for i, h in enumerate(highs) if h]
        if nonzero != [slot]:
            raise AssertionError(f"{label} PGR high-byte slots {nonzero} != [{slot}]")
    if any(b != 0xFF for b in image[0x74000:0x78000]):
        raise AssertionError("linear 20-bit page 61 file range is not 0xFF")
    if image.find(bytes.fromhex("ba7aff")) != -1:
        raise AssertionError("unexpected MOV DX,0xFF7A")
    checks.append("P7/P8: PGR[61]=0x0140 -> 0x500000; D9B5 ES=0xF400 / ES:[03FE]=0x5003FE")

    pan = facts["pan_table"]
    _expect_hex(image, int(pan["dir_first_file"], 16), pan["dir_first_bytes"], "pan dir +0054")
    _expect_hex(image, int(pan["dir_center_file"], 16), pan["dir_center_bytes"], "pan dir +011C")
    _expect_hex(image, int(pan["dir_last_file"], 16), pan["dir_last_bytes"], "pan dir +01E4")
    _expect_hex(image, int(pan["dir_null_file"], 16), pan["dir_null_bytes"], "pan dir NULL")
    _expect_hex(image, int(pan["str_50l_file"], 16), pan["str_50l_bytes"], "50L")
    _expect_hex(image, int(pan["str_c_file"], 16), pan["str_c_bytes"], " C ")
    _expect_hex(image, int(pan["str_50r_file"], 16), pan["str_50r_bytes"], "50R")
    _expect_hex(image, int(pan["title_file"], 16), pan["title_bytes"], "Pan:")
    _expect_hex(image, int(pan["b354_file"], 16), pan["b354_bytes"], "B354:01C6")
    _expect_hex(image, int(pan["caller_push_file"], 16), pan["caller_push_bytes"], "PUSH DS/0054")
    _expect_hex(image, int(pan["caller_callf_file"], 16), pan["caller_callf_bytes"], "CALLF B354:01C6")
    slots = 0
    off = int(pan["dir_first_file"], 16)
    while image[off : off + 4] != bytes(4):
        slots += 1
        off += 4
    if slots != int(pan["slot_count"]):
        raise AssertionError(f"pan table slots {slots} != {pan['slot_count']}")
    if off != int(pan["dir_null_file"], 16):
        raise AssertionError("pan table NULL is not at +01E8")
    checks.append("pan table: 101 names 50L..C..50R; B354:01C6 / Pan:")

    pad = facts["pad_note"]
    _expect_hex(image, int(pad["c44e_file"], 16), pad["c44e_bytes"], "C44E:0119")
    _expect_hex(image, int(pad["title_push_file"], 16), pad["title_push_bytes"], "PUSH +5032")
    _expect_hex(image, int(pad["d6ac_lo_file"], 16), pad["d6ac_lo_bytes"], "[D6AC]>=0")
    _expect_hex(image, int(pad["d6ac_hi_file"], 16), pad["d6ac_hi_bytes"], "[D6AC]<=3F")
    _expect_hex(image, int(pad["pad_push_file"], 16), pad["pad_push_bytes"], "PUSH Pad:")
    _expect_hex(image, int(pad["d9f2_rd_call_file"], 16), pad["d9f2_rd_call_bytes"], "CALL D9F2:000C")
    _expect_hex(image, int(pad["note_push_file"], 16), pad["note_push_bytes"], "PUSH = Note:")
    _expect_hex(image, int(pad["c44e_slot_file"], 16), pad["c44e_slot_bytes"], "C44E [D6AC] to [BP-1]")
    _expect_hex(image, int(pad["c44e_01ee_file"], 16), pad["c44e_01ee_bytes"], "C44E:01EE D9F2:000C")
    _expect_hex(image, int(pad["c44e_020d_file"], 16), pad["c44e_020d_bytes"], "C44E:020D D9F2:0072")
    _expect_hex(image, int(pad["c44e_027d_file"], 16), pad["c44e_027d_bytes"], "C44E:027D D9F2:000C")
    _expect_hex(image, int(pad["c44e_0160_file"], 16), pad["c44e_0160_bytes"], "C44E:0160 MOV [D6AC],0")
    _expect_hex(image, int(pad["c44e_0251_lo_file"], 16), pad["c44e_0251_lo_bytes"], "C44E:0251 CMP [D6AC],0")
    _expect_hex(image, int(pad["c44e_0251_hi_file"], 16), pad["c44e_0251_hi_bytes"], "C44E:0251 CMP [D6AC],0x3F")
    _expect_hex(image, int(pad["c44e_025f_file"], 16), pad["c44e_025f_bytes"], "C44E:025F MOV [D6AC],0")
    _expect_hex(image, int(pad["c44e_0268_file"], 16), pad["c44e_0268_bytes"], "C44E:0268 [D6AC] to [BP-1]")
    _expect_hex(image, int(pad["c44e_0133_dir_file"], 16), pad["c44e_0133_dir_bytes"], "C44E:0133 PUSH +4F0C")
    _expect_hex(image, int(pad["c44e_0137_8375_file"], 16), pad["c44e_0137_8375_bytes"], "C44E:0137 PUSH 0x8375")
    _expect_hex(image, int(pad["c44e_013b_str_file"], 16), pad["c44e_013b_str_bytes"], "C44E:013B PUSH +504E")
    _expect_hex(image, int(pad["c44e_013e_01c6_file"], 16), pad["c44e_013e_01c6_bytes"], "C44E:013E CALLF B354:01C6")
    _expect_hex(image, int(pad["c44e_mode_str_file"], 16), pad["c44e_mode_str_bytes"], "Mode:")
    _expect_hex(image, int(pad["c44e_mode_dir_file"], 16), pad["c44e_mode_dir_bytes"], "+4F0C PROGRAM/MASTER")
    _expect_hex(image, int(pad["c44e_mode_prog_file"], 16), pad["c44e_mode_prog_bytes"], "PROGRAM")
    _expect_hex(image, int(pad["c44e_mode_mast_file"], 16), pad["c44e_mode_mast_bytes"], "MASTER")
    _expect_hex(image, int(pad["c44e_016e_dir_file"], 16), pad["c44e_016e_dir_bytes"], "C44E:016E PUSH +0264")
    _expect_hex(image, int(pad["c44e_0172_lea_file"], 16), pad["c44e_0172_lea_bytes"], "C44E:0172 LEA [BP-1]")
    _expect_hex(image, int(pad["c44e_017a_01c6_file"], 16), pad["c44e_017a_01c6_bytes"], "C44E:017A CALLF B354:01C6")
    _expect_hex(image, int(pad["c44e_pad_dir_file"], 16), pad["c44e_pad_dir_bytes"], "+0264 A01/A02 ptrs")
    _expect_hex(image, int(pad["c44e_pad_dir_last_file"], 16), pad["c44e_pad_dir_last_bytes"], "+0360 D16 ptr + NULL")
    _expect_hex(image, int(pad["c44e_pad_a01_file"], 16), pad["c44e_pad_a01_bytes"], "A01")
    _expect_hex(image, int(pad["c44e_pad_d16_file"], 16), pad["c44e_pad_d16_bytes"], "D16")
    _expect_hex(image, int(pad["c44e_018f_file"], 16), pad["c44e_018f_bytes"], "C44E:018F MOV [BP-2],AL")
    _expect_hex(image, int(pad["c44e_019b_lea_file"], 16), pad["c44e_019b_lea_bytes"], "C44E:019B LEA [BP-2]")
    _expect_hex(image, int(pad["c44e_01a3_03b1_file"], 16), pad["c44e_01a3_03b1_bytes"], "C44E:01A3 CALLF B354:03B1")
    _expect_hex(image, int(pad["c44e_eqnote_str_file"], 16), pad["c44e_eqnote_str_bytes"], " = Note:")
    _expect_hex(image, int(pad["c44e_0005_file"], 16), pad["c44e_0005_bytes"], "C44E:0005 cdecl")
    _expect_hex(image, int(pad["c44e_000c_str_file"], 16), pad["c44e_000c_str_bytes"], "C44E:000C PUSH +4F68")
    _expect_hex(image, int(pad["c44e_midi_title_file"], 16), pad["c44e_midi_title_bytes"], "MIDI")
    _expect_hex(image, int(pad["c44e_0018_str_file"], 16), pad["c44e_0018_str_bytes"], "C44E:0018 PUSH +4F6D")
    _expect_hex(image, int(pad["c44e_menu_file"], 16), pad["c44e_menu_bytes"], "1.Assign pads to MIDI note numbers")
    _expect_hex(image, int(pad["c44e_0049_file"], 16), pad["c44e_0049_bytes"], "C44E:0049 CMP BX,4")
    _expect_hex(image, int(pad["c44e_0050_jmp_file"], 16), pad["c44e_0050_jmp_bytes"], "C44E:0050 JMP CS:[BX+00B8]")
    _expect_hex(image, int(pad["c44e_00b8_tab_file"], 16), pad["c44e_00b8_tab_bytes"], "C44E 00B8 dest table")
    _expect_hex(image, int(pad["c44e_0055_file"], 16), pad["c44e_0055_bytes"], "C44E:0055 CALLN 0119")
    _expect_hex(image, int(pad["c44e_00c2_file"], 16), pad["c44e_00c2_bytes"], "C44E:00C2 cdecl")
    _expect_hex(image, int(pad["c44e_00c2_cmp_file"], 16), pad["c44e_00c2_cmp_bytes"], "C44E:00C2 CMP SI,0x22")
    _expect_hex(image, int(pad["c44e_00c2_str_file"], 16), pad["c44e_00c2_str_bytes"], "C44E:00C2 PUSH +5010")
    _expect_hex(image, int(pad["c44e_gm_str_file"], 16), pad["c44e_gm_str_bytes"], "(Gen MIDI:")
    _expect_hex(image, int(pad["c44e_00c2_idx_file"], 16), pad["c44e_00c2_idx_bytes"], "C44E:00C2 +03EC[SI*4]")
    _expect_hex(image, int(pad["c44e_00c2_005b_file"], 16), pad["c44e_00c2_005b_bytes"], "C44E:00C2 CALLF B1B1:005B")
    _expect_hex(image, int(pad["c44e_00c2_rpar_file"], 16), pad["c44e_00c2_rpar_bytes"], "C44E:00C2 PUSH ')'")
    _expect_hex(image, int(pad["c44e_00c2_010a_file"], 16), pad["c44e_00c2_010a_bytes"], "C44E:010A SI<=0x22 arm")
    _expect_hex(image, int(pad["c44e_01c5_file"], 16), pad["c44e_01c5_bytes"], "C44E:01C5 CALLN 00C2")
    _expect_hex(image, int(pad["c44e_gm23_ptr_file"], 16), pad["c44e_gm23_ptr_bytes"], "+0478 0x23 ptr")
    _expect_hex(image, int(pad["c44e_gm23_str_file"], 16), pad["c44e_gm23_str_bytes"], "ACOUS BASS")
    _expect_hex(image, int(pad["c44e_gm62_ptr_file"], 16), pad["c44e_gm62_ptr_bytes"], "+0574 0x62 ptr")
    _expect_hex(image, int(pad["c44e_gm62_str_file"], 16), pad["c44e_gm62_str_bytes"], "NO GEN MIDI")
    _expect_hex(image, int(pad["c44e_0235_file"], 16), pad["c44e_0235_bytes"], "C44E:0235 CALLF B060:035D")
    _expect_hex(image, int(pad["c44e_0245_file"], 16), pad["c44e_0245_bytes"], "C44E:0245 CMP AX,0x44")
    _expect_hex(image, int(pad["c44e_024a_file"], 16), pad["c44e_024a_bytes"], "C44E:024A CMP AX,0x4E")
    _expect_hex(image, int(pad["be1a_0480_lea_file"], 16), pad["be1a_0480_lea_bytes"], "BE1A:0480 LEA [BP-4]")
    _expect_hex(image, int(pad["be1a_0485_str_file"], 16), pad["be1a_0485_str_bytes"], "BE1A:0485 PUSH +3E62")
    _expect_hex(image, int(pad["be1a_0488_02bb_file"], 16), pad["be1a_0488_02bb_bytes"], "BE1A:0488 CALLF B354:02BB")
    _expect_hex(image, int(pad["be1a_04ab_lea_file"], 16), pad["be1a_04ab_lea_bytes"], "BE1A:04AB LEA [BP-6]")
    _expect_hex(image, int(pad["be1a_04b0_str_file"], 16), pad["be1a_04b0_str_bytes"], "BE1A:04B0 PUSH +3E62")
    _expect_hex(image, int(pad["be1a_04b3_02bb_file"], 16), pad["be1a_04b3_02bb_bytes"], "BE1A:04B3 CALLF B354:02BB")
    _expect_hex(image, int(pad["be1a_0301_file"], 16), pad["be1a_0301_bytes"], "BE1A:0301 MOV [BP-9],AL")
    _expect_hex(image, int(pad["be1a_030d_lea_file"], 16), pad["be1a_030d_lea_bytes"], "BE1A:030D LEA [BP-9]")
    _expect_hex(image, int(pad["be1a_0312_str_file"], 16), pad["be1a_0312_str_bytes"], "BE1A:0312 PUSH +3E62")
    _expect_hex(image, int(pad["be1a_0315_03b1_file"], 16), pad["be1a_0315_03b1_bytes"], "BE1A:0315 CALLF B354:03B1")
    _expect_hex(image, int(pad["be1a_03a1_dir_file"], 16), pad["be1a_03a1_dir_bytes"], "BE1A:03A1 PUSH +0224")
    _expect_hex(image, int(pad["be1a_03a5_996b_file"], 16), pad["be1a_03a5_996b_bytes"], "BE1A:03A5 PUSH 0x996B")
    _expect_hex(image, int(pad["be1a_03a9_str_file"], 16), pad["be1a_03a9_str_bytes"], "BE1A:03A9 PUSH +3E62")
    _expect_hex(image, int(pad["be1a_03ac_01c6_file"], 16), pad["be1a_03ac_01c6_bytes"], "BE1A:03AC CALLF B354:01C6")
    _expect_hex(image, int(pad["be1a_037b_file"], 16), pad["be1a_037b_bytes"], "BE1A:037B MOV [996B],0")
    _expect_hex(image, int(pad["be1a_0334_bnd_file"], 16), pad["be1a_0334_bnd_bytes"], "BE1A:0334 +11 print bounds")
    _expect_hex(image, int(pad["be1a_0341_str_file"], 16), pad["be1a_0341_str_bytes"], "BE1A:0341 PUSH +3E62")
    _expect_hex(image, int(pad["be1a_0344_03b1_file"], 16), pad["be1a_0344_03b1_bytes"], "BE1A:0344 CALLF B354:03B1")
    _expect_hex(image, int(pad["be1a_028d_str_file"], 16), pad["be1a_028d_str_bytes"], "BE1A:028D PUSH +3EAA")
    _expect_hex(image, int(pad["be1a_0290_005b_file"], 16), pad["be1a_0290_005b_bytes"], "BE1A:0290 CALLF B1B1:005B")
    _expect_hex(image, int(pad["be1a_02a5_str_file"], 16), pad["be1a_02a5_str_bytes"], "BE1A:02A5 PUSH +3EB0")
    _expect_hex(image, int(pad["be1a_02a8_005b_file"], 16), pad["be1a_02a8_005b_bytes"], "BE1A:02A8 CALLF B1B1:005B")
    _expect_hex(image, int(pad["be1a_02bd_str_file"], 16), pad["be1a_02bd_str_bytes"], "BE1A:02BD PUSH +3F03")
    _expect_hex(image, int(pad["be1a_02c0_005b_file"], 16), pad["be1a_02c0_005b_bytes"], "BE1A:02C0 CALLF B1B1:005B")
    _expect_hex(image, int(pad["be1a_02d5_str_file"], 16), pad["be1a_02d5_str_bytes"], "BE1A:02D5 PUSH +3F0E")
    _expect_hex(image, int(pad["be1a_02d8_005b_file"], 16), pad["be1a_02d8_005b_bytes"], "BE1A:02D8 CALLF B1B1:005B")
    _expect_hex(image, int(pad["d9f2_000c_file"], 16), pad["d9f2_000c_bytes"], "D9F2:000C")
    _expect_hex(image, int(pad["d9f2_000c_8375_file"], 16), pad["d9f2_000c_8375_bytes"], "D9F2:000C CMP [8375],0")
    _expect_hex(image, int(pad["d9f2_000c_ovl_file"], 16), pad["d9f2_000c_ovl_bytes"], "D9F2:000C MOV AL,[SI+8376]")
    _expect_hex(image, int(pad["d9f2_000c_les_file"], 16), pad["d9f2_000c_les_bytes"], "D9F2:000C LES [E5F9]")
    _expect_hex(image, int(pad["d9f2_000c_073e_file"], 16), pad["d9f2_000c_073e_bytes"], "D9F2:000C MOV AL,[BX+073E]")
    _expect_hex(image, int(pad["d9f2_0072_file"], 16), pad["d9f2_0072_bytes"], "D9F2:0072")
    _expect_hex(image, int(pad["d9f2_0072_8375_file"], 16), pad["d9f2_0072_8375_bytes"], "D9F2:0072 CMP [8375],0")
    _expect_hex(image, int(pad["d9f2_0072_ovl_file"], 16), pad["d9f2_0072_ovl_bytes"], "D9F2:0072 MOV [SI+8376],DL")
    _expect_hex(image, int(pad["d9f2_0072_les_file"], 16), pad["d9f2_0072_les_bytes"], "D9F2:0072 LES [E5F9]")
    _expect_hex(image, int(pad["d9f2_0072_073e_file"], 16), pad["d9f2_0072_073e_bytes"], "D9F2:0072 MOV [BX+073E],DL")
    _expect_hex(image, int(pad["d9f2_003d_file"], 16), pad["d9f2_003d_bytes"], "D9F2:003D")
    _expect_hex(image, int(pad["b060_n_file"], 16), pad["b060_n_bytes"], "B060 'N' remap")
    _expect_hex(image, int(pad["b060_store_file"], 16), pad["b060_store_bytes"], "B060:0504 MOV [D6AC],AL")
    _expect_hex(image, int(pad["sa50_file"], 16), pad["sa50_bytes"], "5A50:0039")
    _expect_hex(image, int(pad["sa50_midi90_file"], 16), pad["sa50_midi90_bytes"], "5A50 CMP AX,0x90")
    _expect_hex(image, int(pad["sa50_call_file"], 16), pad["sa50_call_bytes"], "5A50 CALL 003D / MOV [D6AC]")
    _expect_hex(image, int(pad["d6ad_midi_store_file"], 16), pad["d6ad_midi_store_bytes"], "56D4 MOV [D6AD],AL")
    _expect_hex(image, int(pad["def_file"], 16), pad["def_bytes"], "DGROUP +0859 first 8")
    _expect_hex(image, int(pad["def_last_file"], 16), pad["def_last_bytes"], "DGROUP +0859 last 4")
    _expect_hex(image, int(pad["b21a_copy_file"], 16), pad["b21a_copy_bytes"], "B21A:0033 copy 0859->8376")
    _expect_hex(image, int(pad["b21a_000f_file"], 16), pad["b21a_000f_bytes"], "B21A:000F CALLN 0033")
    _expect_hex(image, int(pad["bdf1_000f_a_file"], 16), pad["bdf1_000f_a_bytes"], "BDF1:0014 CALLF B21A:000F")
    _expect_hex(image, int(pad["bdf1_000f_b_file"], 16), pad["bdf1_000f_b_bytes"], "BDF1:0022 CALLF B21A:000F")
    _expect_hex(image, int(pad["b21a_flag_file"], 16), pad["b21a_flag_bytes"], "B21A:01DD MOV [8375],0")
    _expect_hex(image, int(pad["cf37_copy_file"], 16), pad["cf37_copy_bytes"], "CF37 overlay to +073E")
    _expect_hex(image, int(pad["cf37_04ad_file"], 16), pad["cf37_04ad_bytes"], "CF37:04AD cdecl")
    _expect_hex(image, int(pad["cf37_da04_file"], 16), pad["cf37_da04_bytes"], "CF37:04B8 CALLF DA04:002B")
    _expect_hex(image, int(pad["cf37_ptr_file"], 16), pad["cf37_ptr_bytes"], "CF37 MOV [BP-2]/[BP-4]")
    _expect_hex(image, int(pad["cf37_les_file"], 16), pad["cf37_les_bytes"], "CF37 LES [BP-4]")
    _expect_hex(image, int(pad["cf37_w11_file"], 16), pad["cf37_w11_bytes"], "CF37 MOV [BX+11],0x22")
    _expect_hex(image, int(pad["cf37_w12_file"], 16), pad["cf37_w12_bytes"], "CF37 MOV [BX+12]")
    _expect_hex(image, int(pad["cf37_w14_file"], 16), pad["cf37_w14_bytes"], "CF37 MOV [BX+14]")
    _expect_hex(image, int(pad["cf37_w16_file"], 16), pad["cf37_w16_bytes"], "CF37 MOV [BX+16]")
    _expect_hex(image, int(pad["cf37_w18_file"], 16), pad["cf37_w18_bytes"], "CF37 MOV [BX+18]")
    _expect_hex(image, int(pad["ca45_file"], 16), pad["ca45_bytes"], "CA45:0008")
    _expect_hex(image, int(pad["ca45_store_file"], 16), pad["ca45_store_bytes"], "CA45 MOV [E5F9]")
    _expect_hex(image, int(pad["ca45_da04_file"], 16), pad["ca45_da04_bytes"], "CA45:001A CALLF DA04:002B")
    _expect_hex(image, int(pad["ca45_e60e_ld_file"], 16), pad["ca45_e60e_ld_bytes"], "CA45 MOV AL,[BP+6]")
    _expect_hex(image, int(pad["ca45_e60e_file"], 16), pad["ca45_e60e_bytes"], "CA45 MOV [E60E],AL")
    _expect_hex(image, int(pad["da04_file"], 16), pad["da04_bytes"], "DA04:002B")
    _expect_hex(image, int(pad["da04_cmp_file"], 16), pad["da04_cmp_bytes"], "DA04 CMP CX,[0002]")
    _expect_hex(image, int(pad["be40_file"], 16), pad["be40_bytes"], "BE1A:026C")
    _expect_hex(image, int(pad["be40_title_file"], 16), pad["be40_title_bytes"], "Assign Note Var Slider")
    _expect_hex(image, int(pad["be40_note_file"], 16), pad["be40_note_bytes"], "Note:")
    _expect_hex(image, int(pad["be40_param_file"], 16), pad["be40_param_bytes"], "Param:")
    _expect_hex(image, int(pad["be40_lo_file"], 16), pad["be40_lo_bytes"], "Low range:")
    _expect_hex(image, int(pad["be40_hi_file"], 16), pad["be40_hi_bytes"], "High range:")
    _expect_hex(image, int(pad["be40_f11_file"], 16), pad["be40_f11_bytes"], "BE1A LES +11")
    _expect_hex(image, int(pad["be1a_callf_file"], 16), pad["be1a_callf_bytes"], "CALLF BE1A:026C")
    _expect_hex(image, int(pad["be1a_pgm_file"], 16), pad["be1a_pgm_bytes"], "BE1A MOV [E60E]; INC")
    _expect_hex(image, int(pad["be1a_param_file"], 16), pad["be1a_param_bytes"], "BE1A CMP [996C],0x23")
    _expect_hex(image, int(pad["be1a_fd0d_file"], 16), pad["be1a_fd0d_bytes"], "BE1A LES +FD0D")
    _expect_hex(image, int(pad["be1a_pair12_file"], 16), pad["be1a_pair12_bytes"], "BE1A +12")
    _expect_hex(image, int(pad["be1a_pair14_file"], 16), pad["be1a_pair14_bytes"], "BE1A +14")
    _expect_hex(image, int(pad["be1a_pair16_file"], 16), pad["be1a_pair16_bytes"], "BE1A +16")
    _expect_hex(image, int(pad["be1a_pair18_file"], 16), pad["be1a_pair18_bytes"], "BE1A +18")
    _expect_hex(image, int(pad["be1a_jtab_file"], 16), pad["be1a_jtab_bytes"], "BE1A:0641")
    _expect_hex(image, int(pad["be1a_062f_996b_file"], 16), pad["be1a_062f_996b_bytes"], "BE1A:0592 MOV AL,[996B]")
    _expect_hex(image, int(pad["be1a_062f_cmp_file"], 16), pad["be1a_062f_cmp_bytes"], "BE1A:0598 CMP BX,3")
    _expect_hex(image, int(pad["be1a_062f_jmp_file"], 16), pad["be1a_062f_jmp_bytes"], "BE1A JMP CS:[BX+062F]")
    _expect_hex(image, int(pad["be1a_062f_tab_file"], 16), pad["be1a_062f_tab_bytes"], "BE1A:062F table")
    _expect_hex(image, int(pad["be1a_05a4_les_file"], 16), pad["be1a_05a4_les_bytes"], "BE1A:05A4 LES [E5F9]")
    _expect_hex(image, int(pad["be1a_05a4_w12_file"], 16), pad["be1a_05a4_w12_bytes"], "BE1A:05A4 MOV [BX+12]")
    _expect_hex(image, int(pad["be1a_05b8_w14_file"], 16), pad["be1a_05b8_w14_bytes"], "BE1A:05B8 MOV [BX+14]")
    _expect_hex(image, int(pad["be1a_05cc_w16_file"], 16), pad["be1a_05cc_w16_bytes"], "BE1A:05CC MOV [BX+16]")
    _expect_hex(image, int(pad["be1a_05e0_w18_file"], 16), pad["be1a_05e0_w18_bytes"], "BE1A:05E0 MOV [BX+18]")
    _expect_hex(image, int(pad["param_dir_file"], 16), pad["param_dir_bytes"], "+0224 TUNING..FILTER")
    _expect_hex(image, int(pad["param_tuning_file"], 16), pad["param_tuning_bytes"], "TUNING")
    _expect_hex(image, int(pad["be1a_wr11_file"], 16), pad["be1a_wr11_bytes"], "BE1A MOV ES:[BX+11]")
    _expect_hex(image, int(pad["be1a_wrfd_file"], 16), pad["be1a_wrfd_bytes"], "BE1A MOV ES:[BX+FD0D]")
    _expect_hex(image, int(pad["be1a_16_file"], 16), pad["be1a_16_bytes"], "BE1A:0002")
    _expect_hex(image, int(pad["be1a_16_title_file"], 16), pad["be1a_16_title_bytes"], "Assign '16 Levels'")
    _expect_hex(image, int(pad["be1a_16_d6ad_file"], 16), pad["be1a_16_d6ad_bytes"], "BE1A MOV AL,[D6AD]")
    _expect_hex(image, int(pad["be1a_16_callf_file"], 16), pad["be1a_16_callf_bytes"], "CALLF BE1A:0002")
    _expect_hex(image, int(pad["be1a_16_dir_file"], 16), pad["be1a_16_dir_bytes"], "+3E22 VELOCITY/NOTE VAR")
    _expect_hex(image, int(pad["be1a_16_vel_file"], 16), pad["be1a_16_vel_bytes"], "VELOCITY")
    _expect_hex(image, int(pad["be1a_16_sel_file"], 16), pad["be1a_16_sel_bytes"], "BE1A CMP [81B3],0")
    _expect_hex(image, int(pad["be1a_16_fd0d_file"], 16), pad["be1a_16_fd0d_bytes"], "BE1A:0203 LES +FD0D")
    _expect_hex(image, int(pad["be1a_81b3_init_file"], 16), pad["be1a_81b3_init_bytes"], "B21A MOV [81B3],0")
    _expect_hex(image, int(pad["cf37_0305_file"], 16), pad["cf37_0305_bytes"], "CF37:0305")
    _expect_hex(image, int(pad["cf37_e60e_file"], 16), pad["cf37_e60e_bytes"], "CF37 MOV [E60E],0")
    _expect_hex(image, int(pad["cf37_e60f_file"], 16), pad["cf37_e60f_bytes"], "CF37 MOV [E60F],2")
    _expect_hex(image, int(pad["cf37_e610_init_file"], 16), pad["cf37_e610_init_bytes"], "CF37 MOV [E610],2")
    _expect_hex(image, int(pad["cf37_e639_file"], 16), pad["cf37_e639_bytes"], "CF37 MOV [BX+E639],0x64")
    _expect_hex(image, int(pad["cf37_e639_loop_file"], 16), pad["cf37_e639_loop_bytes"], "CF37 INC / CMP 0x40")
    _expect_hex(image, int(pad["cf37_e613_file"], 16), pad["cf37_e613_bytes"], "CF37 MOV [E613],0x0D")
    _expect_hex(image, int(pad["cf37_e614_file"], 16), pad["cf37_e614_bytes"], "CF37 MOV [E614],0x23")
    _expect_hex(image, int(pad["be1a_center_file"], 16), pad["be1a_center_bytes"], "BE1A Center pad bounds")
    _expect_hex(image, int(pad["be1a_center_str_file"], 16), pad["be1a_center_str_bytes"], "Center pad:")
    _expect_hex(image, int(pad["be1a_00a9_str_file"], 16), pad["be1a_00a9_str_bytes"], "BE1A:00A9 PUSH +3EB9")
    _expect_hex(image, int(pad["be1a_00ac_03b1_file"], 16), pad["be1a_00ac_03b1_bytes"], "BE1A:00AC CALLF B354:03B1")
    _expect_hex(image, int(pad["be1a_00b8_81b3_file"], 16), pad["be1a_00b8_81b3_bytes"], "BE1A:00B8 MOV AL,[81B3]")
    _expect_hex(image, int(pad["be1a_00be_22b_file"], 16), pad["be1a_00be_22b_bytes"], "BE1A:00BE CALLN 022B")
    _expect_hex(image, int(pad["be1a_001b_bnd_file"], 16), pad["be1a_001b_bnd_bytes"], "BE1A:001B Note: bounds")
    _expect_hex(image, int(pad["be1a_0029_str_file"], 16), pad["be1a_0029_str_bytes"], "BE1A:0029 PUSH +3EAA")
    _expect_hex(image, int(pad["be1a_002c_03b1_file"], 16), pad["be1a_002c_03b1_bytes"], "BE1A:002C CALLF B354:03B1")
    _expect_hex(image, int(pad["be1a_note_str_file"], 16), pad["be1a_note_str_bytes"], "Note:")
    _expect_hex(image, int(pad["be1a_0056_dir_file"], 16), pad["be1a_0056_dir_bytes"], "BE1A:0056 PUSH +3E22")
    _expect_hex(image, int(pad["be1a_005a_81b3_file"], 16), pad["be1a_005a_81b3_bytes"], "BE1A:005A PUSH 0x81B3")
    _expect_hex(image, int(pad["be1a_005e_str_file"], 16), pad["be1a_005e_str_bytes"], "BE1A:005E PUSH +3EB0")
    _expect_hex(image, int(pad["be1a_0061_01c6_file"], 16), pad["be1a_0061_01c6_bytes"], "BE1A:0061 CALLF B354:01C6")
    _expect_hex(image, int(pad["be1a_param_str_file"], 16), pad["be1a_param_str_bytes"], "Param:")
    _expect_hex(image, int(pad["be1a_0070_203_file"], 16), pad["be1a_0070_203_bytes"], "BE1A:0070 CALLN 0203")
    _expect_hex(image, int(pad["ead0_file"], 16), pad["ead0_bytes"], "EAD0:000B")
    _expect_hex(image, int(pad["ead0_cmp_file"], 16), pad["ead0_cmp_bytes"], "EAD0 CMP [E614],0x23 / JB")
    _expect_hex(image, int(pad["ead0_fd0d_file"], 16), pad["ead0_fd0d_bytes"], "EAD0 LES +FD0D")
    _expect_hex(image, int(pad["ead0_add90_file"], 16), pad["ead0_add90_bytes"], "EAD0 ADD AL,0x90")
    _expect_hex(image, int(pad["ead0_plus11_file"], 16), pad["ead0_plus11_bytes"], "EAD0 CMP +11,[E614]")
    _expect_hex(image, int(pad["ead0_001d_file"], 16), pad["ead0_001d_bytes"], "EAD0:001D MOV AL,[E614]")
    _expect_hex(image, int(pad["ead0_0022_imul_file"], 16), pad["ead0_0022_imul_bytes"], "EAD0:0022 IMUL AX,0x18")
    _expect_hex(image, int(pad["ead0_003b_file"], 16), pad["ead0_003b_bytes"], "EAD0:003B MOV AL,[E614]")
    _expect_hex(image, int(pad["ead0_0060_lea_file"], 16), pad["ead0_0060_lea_bytes"], "EAD0:0060 LEA [BP-6]")
    _expect_hex(image, int(pad["ead0_0064_cfb3_file"], 16), pad["ead0_0064_cfb3_bytes"], "EAD0:0064 CALLF CFB3:0008")
    _expect_hex(image, int(pad["cfb3_file"], 16), pad["cfb3_bytes"], "CFB3:0008")
    _expect_hex(image, int(pad["cfb3_and_file"], 16), pad["cfb3_and_bytes"], "CFB3 AND AX,0xF8")
    _expect_hex(image, int(pad["cfb3_cmp90_file"], 16), pad["cfb3_cmp90_bytes"], "CFB3 CMP AX,0x90")
    _expect_hex(image, int(pad["cfb3_90_file"], 16), pad["cfb3_90_bytes"], "CFB3 CALLF CFC6:0007")
    _expect_hex(image, int(pad["cfb3_b0_file"], 16), pad["cfb3_b0_bytes"], "CFB3 0xB0 CMP [BX+2],7")
    _expect_hex(image, int(pad["cfb3_d6ab_file"], 16), pad["cfb3_d6ab_bytes"], "CFB3 MOV [D6AB],0x50")
    _expect_hex(image, int(pad["cfb3_c0_file"], 16), pad["cfb3_c0_bytes"], "CFB3 0xC0 PUSH [BX+2]")
    _expect_hex(image, int(pad["cfb3_c0_callf_file"], 16), pad["cfb3_c0_callf_bytes"], "CFB3 CALLF C887:1BE8")
    _expect_hex(image, int(pad["cfb3_f0_file"], 16), pad["cfb3_f0_bytes"], "CFB3 0xF0 CMP [BX+2],0x47")
    _expect_hex(image, int(pad["cfb3_f0_45_file"], 16), pad["cfb3_f0_45_bytes"], "CFB3 0xF0 CMP [BX+5],0x45")
    _expect_hex(image, int(pad["cfb3_f0_46_file"], 16), pad["cfb3_f0_46_bytes"], "CFB3 0xF0 CMP [BX+5],0x46")
    _expect_hex(image, int(pad["cfb3_f0_callf_file"], 16), pad["cfb3_f0_callf_bytes"], "CFB3 CALLF D0AE:0002")
    _expect_hex(image, int(pad["d0ae_file"], 16), pad["d0ae_bytes"], "D0AE:0002 CMP [BP+8],1")
    _expect_hex(image, int(pad["d9f2_paint_file"], 16), pad["d9f2_paint_bytes"], "leftover after D0AE:0002")
    _expect_hex(image, int(pad["d9f2_paint_call_file"], 16), pad["d9f2_paint_call_bytes"], "CALLF D9F2:000C first")
    _expect_hex(image, int(pad["d9f2_paint_loop_file"], 16), pad["d9f2_paint_loop_bytes"], "CALLF D9F2:000C loop")
    _expect_hex(image, int(pad["d9f2_paint_st_file"], 16), pad["d9f2_paint_st_bytes"], "MOV ES:[BX],AL")
    _expect_hex(image, int(pad["d9f2_paint_bound_file"], 16), pad["d9f2_paint_bound_bytes"], "CMP [BP+0A],0x40")
    _expect_hex(image, int(pad["d0ae_d6ab_file"], 16), pad["d0ae_d6ab_bytes"], "D0AE MOV [D6AB],0x50")
    _expect_hex(image, int(pad["picker_file"], 16), pad["picker_bytes"], "FCF6 picker cdecl")
    _expect_hex(image, int(pad["picker_note_file"], 16), pad["picker_note_bytes"], "picker CMP [BX+2],0x23")
    _expect_hex(image, int(pad["picker_fcf6_file"], 16), pad["picker_fcf6_bytes"], "picker ADD BX,FCF6")
    _expect_hex(image, int(pad["picker_plus1_file"], 16), pad["picker_plus1_bytes"], "picker MOV +1; CMP 2")
    _expect_hex(image, int(pad["picker_plus5_file"], 16), pad["picker_plus5_bytes"], "picker CMP +5,0x23")
    _expect_hex(image, int(pad["picker_plus3_file"], 16), pad["picker_plus3_bytes"], "picker CMP +3,0x23")
    _expect_hex(image, int(pad["d9a2_wr0_file"], 16), pad["d9a2_wr0_bytes"], "D9A2:0004 cdecl")
    _expect_hex(image, int(pad["d9a2_wr0_call_file"], 16), pad["d9a2_wr0_call_bytes"], "D9A2:0004 CALLF 000C")
    _expect_hex(image, int(pad["d9a2_wr0_cmp_file"], 16), pad["d9a2_wr0_cmp_bytes"], "D9A2:0004 CMP AX,0x23")
    _expect_hex(image, int(pad["d9a2_wr0_02d6_file"], 16), pad["d9a2_wr0_02d6_bytes"], "D9A2:0004 CALLF 02D6")
    _expect_hex(image, int(pad["d9a2_wr0_st_file"], 16), pad["d9a2_wr0_st_bytes"], "D9A2:0004 MOV ES:[BX],AL")
    _expect_hex(image, int(pad["d9a2_wr1_file"], 16), pad["d9a2_wr1_bytes"], "D9A2:0031 cdecl")
    _expect_hex(image, int(pad["d9a2_wr1_call_file"], 16), pad["d9a2_wr1_call_bytes"], "D9A2:0031 CALLF 000C")
    _expect_hex(image, int(pad["d9a2_wr1_st_file"], 16), pad["d9a2_wr1_st_bytes"], "D9A2:0031 MOV ES:[BX+1],AL")
    _expect_hex(image, int(pad["d9a2_wr2_file"], 16), pad["d9a2_wr2_bytes"], "D9A2:005F cdecl")
    _expect_hex(image, int(pad["d9a2_wr2_call_file"], 16), pad["d9a2_wr2_call_bytes"], "D9A2:005F CALLF 000C")
    _expect_hex(image, int(pad["d9a2_wr2_033a_file"], 16), pad["d9a2_wr2_033a_bytes"], "D9A2:005F CALLF 033A")
    _expect_hex(image, int(pad["d9a2_wr2_st_file"], 16), pad["d9a2_wr2_st_bytes"], "D9A2:005F MOV ES:[BX+2],AL")
    _expect_hex(image, int(pad["d9a2_rd0_file"], 16), pad["d9a2_rd0_bytes"], "D9A2:00C7 cdecl")
    _expect_hex(image, int(pad["d9a2_rd0_call_file"], 16), pad["d9a2_rd0_call_bytes"], "D9A2:00C7 CALLF 000C")
    _expect_hex(image, int(pad["d9a2_rd0_02d6_file"], 16), pad["d9a2_rd0_02d6_bytes"], "D9A2:00C7 CALLF 02D6")
    _expect_hex(image, int(pad["d9a2_rd0_ld_file"], 16), pad["d9a2_rd0_ld_bytes"], "D9A2:00C7 MOV AL,ES:[BX]")
    _expect_hex(image, int(pad["d9a2_rd1_file"], 16), pad["d9a2_rd1_bytes"], "D9A2:00E9 cdecl")
    _expect_hex(image, int(pad["d9a2_rd1_call_file"], 16), pad["d9a2_rd1_call_bytes"], "D9A2:00E9 CALLF 000C")
    _expect_hex(image, int(pad["d9a2_rd1_ld_file"], 16), pad["d9a2_rd1_ld_bytes"], "D9A2:00E9 MOV AL,ES:[BX+1]")
    _expect_hex(image, int(pad["d9a2_rd2_file"], 16), pad["d9a2_rd2_bytes"], "D9A2:010C cdecl")
    _expect_hex(image, int(pad["d9a2_rd2_call_file"], 16), pad["d9a2_rd2_call_bytes"], "D9A2:010C CALLF 000C")
    _expect_hex(image, int(pad["d9a2_rd2_033a_file"], 16), pad["d9a2_rd2_033a_bytes"], "D9A2:010C CALLF 033A")
    _expect_hex(image, int(pad["d9a2_rd2_ld_file"], 16), pad["d9a2_rd2_ld_bytes"], "D9A2:010C MOV AL,ES:[BX+2]")
    _expect_hex(image, int(pad["bdf1_000c_file"], 16), pad["bdf1_000c_bytes"], "BDF1 PUSH 0 / CALLF 000C")
    _expect_hex(image, int(pad["bdf1_d6ad_file"], 16), pad["bdf1_d6ad_bytes"], "BDF1 MOV [D6AD],AL")
    _expect_hex(image, int(pad["cfc6_039e_file"], 16), pad["cfc6_039e_bytes"], "CFC6:039E cdecl")
    _expect_hex(image, int(pad["cfc6_039e_calln_file"], 16), pad["cfc6_039e_calln_bytes"], "CFC6:0007 CALLN 039E")
    _expect_hex(image, int(pad["cfc6_039e_ff_file"], 16), pad["cfc6_039e_ff_bytes"], "CFC6:039E CMP [BP-5C],0xFF")
    _expect_hex(image, int(pad["cfc6_039e_p7_file"], 16), pad["cfc6_039e_p7_bytes"], "CFC6:039E CMP +7,0x23")
    _expect_hex(image, int(pad["cfc6_039e_p7ld_file"], 16), pad["cfc6_039e_p7ld_bytes"], "CFC6:039E MOV AL,+7")
    _expect_hex(image, int(pad["cfc6_039e_e5f9_file"], 16), pad["cfc6_039e_e5f9_bytes"], "CFC6:039E LES [E5F9]")
    _expect_hex(image, int(pad["cfc6_039e_fcf6_file"], 16), pad["cfc6_039e_fcf6_bytes"], "CFC6:039E MOV AL,[BX+FCF6]")
    _expect_hex(image, int(pad["cfc6_039e_p8_file"], 16), pad["cfc6_039e_p8_bytes"], "CFC6:039E CMP +8,0x23")
    _expect_hex(image, int(pad["cfc6_039e_p8ld_file"], 16), pad["cfc6_039e_p8ld_bytes"], "CFC6:039E MOV AL,+8")
    _expect_hex(image, int(pad["cfc6_039e_jmp_file"], 16), pad["cfc6_039e_jmp_bytes"], "CFC6:039E JMP CS:[BX+0B25]")
    _expect_hex(image, int(pad["d9c0_file"], 16), pad["d9c0_bytes"], "D9C0:0006 cdecl")
    _expect_hex(image, int(pad["d9c0_cmp_file"], 16), pad["d9c0_cmp_bytes"], "D9C0 CMP BX,3")
    _expect_hex(image, int(pad["d9c0_jmp_file"], 16), pad["d9c0_jmp_bytes"], "D9C0 JMP CS:[BX+0095]")
    _expect_hex(image, int(pad["d9c0_tab_file"], 16), pad["d9c0_tab_bytes"], "D9C0 0095 table")
    _expect_hex(image, int(pad["d9c0_p12_file"], 16), pad["d9c0_p12_bytes"], "D9C0 LES +12")
    _expect_hex(image, int(pad["d9c0_p14_file"], 16), pad["d9c0_p14_bytes"], "D9C0 LES +14")
    _expect_hex(image, int(pad["d9c0_p16_file"], 16), pad["d9c0_p16_bytes"], "D9C0 LES +16")
    _expect_hex(image, int(pad["d9c0_p18_file"], 16), pad["d9c0_p18_bytes"], "D9C0 LES +18")
    _expect_hex(image, int(pad["be1a_d9c0_file"], 16), pad["be1a_d9c0_bytes"], "BE1A CALLF D9C0:0006")
    _expect_hex(image, int(pad["ca45_d9c0_file"], 16), pad["ca45_d9c0_bytes"], "CA45 CALLF D9C0:0006")
    _expect_hex(image, int(pad["dc2a_file"], 16), pad["dc2a_bytes"], "DC2A:0033 cdecl")
    _expect_hex(image, int(pad["dc2a_90_file"], 16), pad["dc2a_90_bytes"], "DC2A CMP ES:[BX],0x90")
    _expect_hex(image, int(pad["dc2a_81b3_file"], 16), pad["dc2a_81b3_bytes"], "DC2A CMP [81B3],0")
    _expect_hex(image, int(pad["dc2a_ev2_file"], 16), pad["dc2a_ev2_bytes"], "DC2A MOV AL,ES:[BX+2]")
    _expect_hex(image, int(pad["dc85_file"], 16), pad["dc85_bytes"], "DC85:0047 cdecl")
    _expect_hex(image, int(pad["dc85_23_file"], 16), pad["dc85_23_bytes"], "DC85 MOV [BP-2],0x23")
    _expect_hex(image, int(pad["dc85_81b3_file"], 16), pad["dc85_81b3_bytes"], "DC85 CMP [81B3],0")
    _expect_hex(image, int(pad["c20f_0478_file"], 16), pad["c20f_0478_bytes"], "C20F:0478 XOR SI,SI")
    _expect_hex(image, int(pad["c20f_imul_file"], 16), pad["c20f_imul_bytes"], "C20F:047C SI*0x18")
    _expect_hex(image, int(pad["c20f_les_file"], 16), pad["c20f_les_bytes"], "C20F:047C LES [E5F9]")
    _expect_hex(image, int(pad["c20f_cmp_file"], 16), pad["c20f_cmp_bytes"], "C20F:047C CMP [BX+3E],0xFF")
    _expect_hex(image, int(pad["c20f_bound_file"], 16), pad["c20f_bound_bytes"], "C20F:047C CMP SI,0x40")
    _expect_hex(image, int(pad["c20f_ca45_file"], 16), pad["c20f_ca45_bytes"], "C20F:047C CALLF CA45 alias")
    _expect_hex(image, int(pad["c20f_0874_imul_file"], 16), pad["c20f_0874_imul_bytes"], "C20F:0874 SI*0x18")
    _expect_hex(image, int(pad["c20f_0874_cmp_file"], 16), pad["c20f_0874_cmp_bytes"], "C20F:0874 CMP [BX+3E],0xFF")
    _expect_hex(image, int(pad["c20f_085e_file"], 16), pad["c20f_085e_bytes"], "C20F:085E MOV [BP-8],0")
    _expect_hex(image, int(pad["c20f_0868_ca45_file"], 16), pad["c20f_0868_ca45_bytes"], "C20F:0868 CALLF CA45")
    _expect_hex(image, int(pad["c20f_0874_outer_file"], 16), pad["c20f_0874_outer_bytes"], "C20F:0874 CMP [BP-8],0x18")
    _expect_hex(image, int(pad["c20f_0874_rest_file"], 16), pad["c20f_0874_rest_bytes"], "C20F:0874 restore CA45")
    _expect_hex(image, int(pad["c20f_0bbf_file"], 16), pad["c20f_0bbf_bytes"], "C20F:0BBF cdecl")
    _expect_hex(image, int(pad["c20f_0bbf_ld_file"], 16), pad["c20f_0bbf_ld_bytes"], "C20F:0BBF MOV AL,[BX+3E]")
    _expect_hex(image, int(pad["c20f_0bbf_600_file"], 16), pad["c20f_0bbf_600_bytes"], "C20F:0BBF CMP DX,0x600")
    _expect_hex(image, int(pad["c20f_0bbf_e60e_file"], 16), pad["c20f_0bbf_e60e_bytes"], "C20F:0BBF MOV AL,[E60E]")
    _expect_hex(image, int(pad["c20f_0bbf_skip_file"], 16), pad["c20f_0bbf_skip_bytes"], "C20F:0BBF CMP DI,[BP-2]")
    _expect_hex(image, int(pad["c20f_0bbf_ca45_file"], 16), pad["c20f_0bbf_ca45_bytes"], "C20F:0BBF CALLF CA45")
    _expect_hex(image, int(pad["c20f_0bbf_cmp_file"], 16), pad["c20f_0bbf_cmp_bytes"], "C20F:0BBF CMP AX,[BP+6]")
    _expect_hex(image, int(pad["c20f_0bbf_wr_file"], 16), pad["c20f_0bbf_wr_bytes"], "C20F:0BBF MOV [SI+3E],AL")
    _expect_hex(image, int(pad["c20f_0bbf_outer_file"], 16), pad["c20f_0bbf_outer_bytes"], "C20F:0BBF CMP DI,0x18")
    _expect_hex(image, int(pad["c20f_0bbf_rest_file"], 16), pad["c20f_0bbf_rest_bytes"], "C20F:0BBF restore CA45")
    _expect_hex(image, int(pad["d0c0_0c9c_file"], 16), pad["d0c0_0c9c_bytes"], "D0C0:0C9C cdecl")
    _expect_hex(image, int(pad["d0c0_0c9c_e60e_file"], 16), pad["d0c0_0c9c_e60e_bytes"], "D0C0:0C9C MOV AL,[E60E]")
    _expect_hex(image, int(pad["d0c0_0c9c_ca45_file"], 16), pad["d0c0_0c9c_ca45_bytes"], "D0C0:0C9C CALLF CA45 alias")
    _expect_hex(image, int(pad["d0c0_0c9c_di_file"], 16), pad["d0c0_0c9c_di_bytes"], "D0C0:0C9C MOV DI,0x23")
    _expect_hex(image, int(pad["d0c0_0c9c_cx_file"], 16), pad["d0c0_0c9c_cx_bytes"], "D0C0:0C9C MOV CX,0x348")
    _expect_hex(image, int(pad["d0c0_0c9c_les_file"], 16), pad["d0c0_0c9c_les_bytes"], "D0C0:0C9C LES [E5F9]")
    _expect_hex(image, int(pad["d0c0_0c9c_fcf6_file"], 16), pad["d0c0_0c9c_fcf6_bytes"], "D0C0:0C9C MOV AL,[BX+FCF6]")
    _expect_hex(image, int(pad["d0c0_0c9c_add18_file"], 16), pad["d0c0_0c9c_add18_bytes"], "D0C0:0C9C ADD CX,0x18")
    _expect_hex(image, int(pad["d0c0_0c9c_cmp_file"], 16), pad["d0c0_0c9c_cmp_bytes"], "D0C0:0C9C CMP CX,0x930")
    _expect_hex(image, int(pad["d0c0_0c9c_outer_file"], 16), pad["d0c0_0c9c_outer_bytes"], "D0C0:0C9C CMP [BP-4],0x18")
    _expect_hex(image, int(pad["be1a_131_file"], 16), pad["be1a_131_bytes"], "BE1A:0131 CMP [81B3],0")
    _expect_hex(image, int(pad["be1a_131_clamp_file"], 16), pad["be1a_131_clamp_bytes"], "BE1A:0131 CMP [BP-2],3")
    _expect_hex(image, int(pad["be1a_131_imul_file"], 16), pad["be1a_131_imul_bytes"], "BE1A:0131 note*0x18")
    _expect_hex(image, int(pad["be1a_131_les_file"], 16), pad["be1a_131_les_bytes"], "BE1A:0131 LES [E5F9]")
    _expect_hex(image, int(pad["be1a_131_wr_file"], 16), pad["be1a_131_wr_bytes"], "BE1A:0131 MOV [BX+FD0D],AL")
    _expect_hex(image, int(pad["be1a_131_tab_file"], 16), pad["be1a_131_tab_bytes"], "BE1A 01FB table 0131")
    _expect_hex(image, int(pad["be1a_105_file"], 16), pad["be1a_105_bytes"], "BE1A:0105 PUSH [BP-1]")
    _expect_hex(image, int(pad["be1a_105_call_file"], 16), pad["be1a_105_call_bytes"], "BE1A:0105 CALLN 0203")
    _expect_hex(image, int(pad["be1a_105_st_file"], 16), pad["be1a_105_st_bytes"], "BE1A:0105 MOV [BP-2],AL")
    _expect_hex(image, int(pad["be1a_105_81b3_file"], 16), pad["be1a_105_81b3_bytes"], "BE1A:0105 MOV AL,[81B3]")
    _expect_hex(image, int(pad["be1a_105_tab_file"], 16), pad["be1a_105_tab_bytes"], "BE1A 01FB table 0105")
    _expect_hex(image, int(pad["be1a_22b_file"], 16), pad["be1a_22b_bytes"], "BE1A:022B cdecl")
    _expect_hex(image, int(pad["be1a_22b_p6_file"], 16), pad["be1a_22b_p6_bytes"], "BE1A:022B CMP [BP+6],1")
    _expect_hex(image, int(pad["be1a_22b_p8_file"], 16), pad["be1a_22b_p8_bytes"], "BE1A:022B CMP [BP+8],0")
    _expect_hex(image, int(pad["be1a_22b_str_file"], 16), pad["be1a_22b_str_bytes"], "BE1A:022B PUSH +3EB9")
    _expect_hex(image, int(pad["be1a_22b_put_file"], 16), pad["be1a_22b_put_bytes"], "BE1A:022B CALLF B1B1:005B")
    _expect_hex(image, int(pad["be1a_105_22b_file"], 16), pad["be1a_105_22b_bytes"], "BE1A:0105 CALLN 022B")
    _expect_hex(image, int(pad["be1a_131_81b3_file"], 16), pad["be1a_131_81b3_bytes"], "BE1A:0131 MOV AL,[81B3]")
    _expect_hex(image, int(pad["be1a_131_22b_file"], 16), pad["be1a_131_22b_bytes"], "BE1A:0131 CALLN 022B")
    _expect_hex(image, int(pad["be1a_0380_996b_file"], 16), pad["be1a_0380_996b_bytes"], "BE1A:0380 MOV [996B],AL")
    _expect_hex(image, int(pad["be1a_996b_cmp2_file"], 16), pad["be1a_996b_cmp2_bytes"], "BE1A CMP [996B],2")
    _expect_hex(image, int(pad["be1a_996b_cmp1_file"], 16), pad["be1a_996b_cmp1_bytes"], "BE1A CMP [996B],1")
    _expect_hex(image, int(pad["be1a_508_file"], 16), pad["be1a_508_bytes"], "BE1A:0508 DEC [BP-9]")
    _expect_hex(image, int(pad["be1a_508_ca45_file"], 16), pad["be1a_508_ca45_bytes"], "BE1A:0508 CALLF CA45")
    _expect_hex(image, int(pad["be1a_508_tab_file"], 16), pad["be1a_508_tab_bytes"], "BE1A:0637 dest 0508")
    _expect_hex(image, int(pad["be1a_e60e_inc_file"], 16), pad["be1a_e60e_inc_bytes"], "BE1A INC [E60E] to [BP-9]")
    _expect_hex(image, int(pad["dce4_file"], 16), pad["dce4_bytes"], "DCE4:000C cdecl")
    _expect_hex(image, int(pad["dce4_and_file"], 16), pad["dce4_and_bytes"], "DCE4 AND AL,0xF8")
    _expect_hex(image, int(pad["dce4_98_file"], 16), pad["dce4_98_bytes"], "DCE4 CMP AL,0x98")
    _expect_hex(image, int(pad["dce4_f0_file"], 16), pad["dce4_f0_bytes"], "DCE4 CMP AL,0xF0")
    _expect_hex(image, int(pad["dce4_47_file"], 16), pad["dce4_47_bytes"], "DCE4 CMP +2,0x47")
    _expect_hex(image, int(pad["dce4_45_file"], 16), pad["dce4_45_bytes"], "DCE4 CMP +5,0x45")
    _expect_hex(image, int(pad["dce4_46_file"], 16), pad["dce4_46_bytes"], "DCE4 CMP +5,0x46")
    _expect_hex(image, int(pad["dce4_e60f_file"], 16), pad["dce4_e60f_bytes"], "DCE4 CMP [E60F],1")
    _expect_hex(image, int(pad["dce4_e610_file"], 16), pad["dce4_e610_bytes"], "DCE4 CMP [E610],1")
    _expect_hex(image, int(pad["dc85_dce4_file"], 16), pad["dc85_dce4_bytes"], "DC85 CALLF DCE4:000C")
    _expect_hex(image, int(pad["ca45_11_les_file"], 16), pad["ca45_11_les_bytes"], "CA45 LES [E5F9] for +11")
    _expect_hex(image, int(pad["ca45_11_file"], 16), pad["ca45_11_bytes"], "CA45 MOV AL,[BX+11]")
    _expect_hex(image, int(pad["ca45_11_imul_file"], 16), pad["ca45_11_imul_bytes"], "CA45 +11*0x18")
    _expect_hex(image, int(pad["ca45_11_fd0d_file"], 16), pad["ca45_11_fd0d_bytes"], "CA45 MOV AL,[BX+FD0D]")
    _expect_hex(image, int(pad["ca45_11_996b_file"], 16), pad["ca45_11_996b_bytes"], "CA45 MOV [996B],AL")
    _expect_hex(image, int(pad["dc2a_010a_file"], 16), pad["dc2a_010a_bytes"], "DC2A:010A cdecl")
    _expect_hex(image, int(pad["dc2a_010a_les_file"], 16), pad["dc2a_010a_les_bytes"], "DC2A:010A LES [BP+6]")
    _expect_hex(image, int(pad["dc2a_010a_p1_file"], 16), pad["dc2a_010a_p1_bytes"], "DC2A:010A MOV AL,+1")
    _expect_hex(image, int(pad["dc2a_010a_and_file"], 16), pad["dc2a_010a_and_bytes"], "DC2A:010A AND CL,0xF8")
    _expect_hex(image, int(pad["dc2a_010a_c0_file"], 16), pad["dc2a_010a_c0_bytes"], "DC2A:010A CMP CL,0xC0")
    _expect_hex(image, int(pad["dc2a_010a_call_file"], 16), pad["dc2a_010a_call_bytes"], "DC2A:010A CALLN 013B")
    _expect_hex(image, int(pad["dc2a_0033_010a_file"], 16), pad["dc2a_0033_010a_bytes"], "DC2A:0033 CALLF DC3A:000A")
    _expect_hex(image, int(pad["dc85_011a_file"], 16), pad["dc85_011a_bytes"], "DC85:011A cdecl")
    _expect_hex(image, int(pad["dc85_011a_si_file"], 16), pad["dc85_011a_si_bytes"], "DC85:011A XOR SI,SI")
    _expect_hex(image, int(pad["dc85_011a_dce4_file"], 16), pad["dc85_011a_dce4_bytes"], "DC85:011A CALLF DCE4:000C")
    _expect_hex(image, int(pad["dc85_011a_bound_file"], 16), pad["dc85_011a_bound_bytes"], "DC85:011A CMP SI,0x100")
    _expect_hex(image, int(pad["dc2a_996b_file"], 16), pad["dc2a_996b_bytes"], "DC2A:0033 MOV AL,[996B]")
    _expect_hex(image, int(pad["dc85_996b_file"], 16), pad["dc85_996b_bytes"], "DC85:0047 MOV AL,[996B]")
    _expect_hex(image, int(pad["d9ea_file"], 16), pad["d9ea_bytes"], "D9EA:0042 cdecl")
    _expect_hex(image, int(pad["d9ea_shl_file"], 16), pad["d9ea_shl_bytes"], "D9EA:0042 SHL AX,1")
    _expect_hex(image, int(pad["d9ea_shr_file"], 16), pad["d9ea_shr_bytes"], "D9EA:0042 SHR AL,1")
    _expect_hex(image, int(pad["dc85_d9ea_file"], 16), pad["dc85_d9ea_bytes"], "DC85:0047 CALLF D9EA:0042")
    _expect_hex(image, int(pad["dc85_011a_d9ea_file"], 16), pad["dc85_011a_d9ea_bytes"], "DC85:011A CALLF D9EA:0042")
    _expect_hex(image, int(pad["dce4_e60f_jmp_file"], 16), pad["dce4_e60f_jmp_bytes"], "DCE4 [E60F] JMP 00A4")
    _expect_hex(image, int(pad["dce4_e610_jmp_file"], 16), pad["dce4_e610_jmp_bytes"], "DCE4 [E610] JMP 00A4")
    _expect_hex(image, int(pad["dce4_dc3a_file"], 16), pad["dce4_dc3a_bytes"], "DCE4:000C CALLF DC3A:000A")
    _expect_hex(image, int(pad["cfb3_note_file"], 16), pad["cfb3_note_bytes"], "CFB3 CMP [BX+2],0x23")
    _expect_hex(image, int(pad["cfb3_fcf6_file"], 16), pad["cfb3_fcf6_bytes"], "CFB3 ADD BX,FCF6")
    _expect_hex(image, int(pad["cfb3_empty_file"], 16), pad["cfb3_empty_bytes"], "CFB3 CMP ES:[BX],0xFF")
    _expect_hex(image, int(pad["cfb3_plus6_file"], 16), pad["cfb3_plus6_bytes"], "CFB3 CMP ES:[BX+6],2")
    _expect_hex(image, int(pad["cfc6_file"], 16), pad["cfc6_bytes"], "CFC6:0007")
    _expect_hex(image, int(pad["cfc6_note_file"], 16), pad["cfc6_note_bytes"], "CFC6 CMP [BX+2],0x23")
    _expect_hex(image, int(pad["cfc6_hi_file"], 16), pad["cfc6_hi_bytes"], "CFC6 CMP [BX+2],0x62")
    _expect_hex(image, int(pad["cfc6_idx_file"], 16), pad["cfc6_idx_bytes"], "CFC6 LES [E5F9]+FCF6")
    _expect_hex(image, int(pad["cfc6_rd_file"], 16), pad["cfc6_rd_bytes"], "CFC6 MOV AL,ES:[BX+0D]")
    _expect_hex(image, int(pad["cfc6_call_02d6_file"], 16), pad["cfc6_call_02d6_bytes"], "CFC6 CALLN 02D6")
    _expect_hex(image, int(pad["cfc6_call_033a_file"], 16), pad["cfc6_call_033a_bytes"], "CFC6 CALLN 033A")
    _expect_hex(image, int(pad["cfc6_plus1_file"], 16), pad["cfc6_plus1_bytes"], "CFC6 MOV AL,ES:[BX+1]; CMP 2")
    _expect_hex(image, int(pad["cfc6_plus5_cmp_file"], 16), pad["cfc6_plus5_cmp_bytes"], "CFC6 CMP ES:[BX+5],0x23")
    _expect_hex(image, int(pad["cfc6_plus5_note_file"], 16), pad["cfc6_plus5_note_bytes"], "CFC6 MOV AL,ES:[BX+5]")
    _expect_hex(image, int(pad["cfc6_plus3_cmp_file"], 16), pad["cfc6_plus3_cmp_bytes"], "CFC6 CMP ES:[BX+3],0x23")
    _expect_hex(image, int(pad["cfc6_plus3_note_file"], 16), pad["cfc6_plus3_note_bytes"], "CFC6 MOV AL,ES:[BX+3]")
    _expect_hex(image, int(pad["cfc6_plus1_3_file"], 16), pad["cfc6_plus1_3_bytes"], "CFC6 +1==3 LES +0C")
    _expect_hex(image, int(pad["cfc6_plus0c_file"], 16), pad["cfc6_plus0c_bytes"], "CFC6 MOV AL,ES:[BX+0C]")
    _expect_hex(image, int(pad["cfc6_and3_file"], 16), pad["cfc6_and3_bytes"], "CFC6 AND AX,3; CMP 1")
    _expect_hex(image, int(pad["cfc6_ev4_file"], 16), pad["cfc6_ev4_bytes"], "CFC6 MOV AL,ES:[BX+4]")
    _expect_hex(image, int(pad["cfc6_plus1_1_file"], 16), pad["cfc6_plus1_1_bytes"], "CFC6 CMP ES:[BX+1],1")
    _expect_hex(image, int(pad["cfc6_plus1_1_n3_file"], 16), pad["cfc6_plus1_1_n3_bytes"], "CFC6 +1==1 CMP +3,0x23")
    _expect_hex(image, int(pad["cfc6_plus1_1_ld3_file"], 16), pad["cfc6_plus1_1_ld3_bytes"], "CFC6 +1==1 MOV +3")
    _expect_hex(image, int(pad["cfc6_plus1_1_n5_file"], 16), pad["cfc6_plus1_1_n5_bytes"], "CFC6 +1==1 CMP +5,0x23")
    _expect_hex(image, int(pad["cfc6_plus1_1_ld5_file"], 16), pad["cfc6_plus1_1_ld5_bytes"], "CFC6 +1==1 MOV +5")
    _expect_hex(image, int(pad["cfc6_slot_file"], 16), pad["cfc6_slot_bytes"], "CFC6:02D6 note-0x23")
    _expect_hex(image, int(pad["cfc6_clamp_file"], 16), pad["cfc6_clamp_bytes"], "CFC6:02D6 CMP DX,0x40")
    _expect_hex(image, int(pad["cfc6_e60f_file"], 16), pad["cfc6_e60f_bytes"], "CFC6 CMP [E60F],2")
    _expect_hex(image, int(pad["cfc6_063e_file"], 16), pad["cfc6_063e_bytes"], "CFC6 [E5F9]+slot*4+063E")
    _expect_hex(image, int(pad["cfc6_e610_file"], 16), pad["cfc6_e610_bytes"], "CFC6 CMP [E610],2")
    _expect_hex(image, int(pad["cfc6_e60f1_file"], 16), pad["cfc6_e60f1_bytes"], "CFC6 CMP [E60F],1")
    _expect_hex(image, int(pad["cfc6_920a_file"], 16), pad["cfc6_920a_bytes"], "CFC6 OR [920A]:[920C]")
    _expect_hex(image, int(pad["cfc6_002a_file"], 16), pad["cfc6_002a_bytes"], "CFC6 [920A]+slot*4+002A")
    _expect_hex(image, int(pad["cfc6_e639_file"], 16), pad["cfc6_e639_bytes"], "CFC6 DS:E639+slot*4")
    _expect_hex(image, int(pad["cfc6_e6101_file"], 16), pad["cfc6_e6101_bytes"], "CFC6 CMP [E610],1")
    _expect_hex(image, int(pad["midi90_file"], 16), pad["midi90_bytes"], "56D4:000A AND/CMP 90")
    def_off = int(pad["def_file"], 16)
    def_n = int(pad["def_count"])
    got = list(image[def_off : def_off + def_n])
    expect = list(range(int(pad["def_first"]), int(pad["def_last"]) + 1))
    if got != expect:
        raise AssertionError(f"+0859 default table {got[:4]}.. != {expect[:4]}..")
    checks.append("D20: C44E assign; [E5F9] 9770: Pgm; BE1A Slider / 16 Levels")

    if image[0x7AC1C:0x7AC1F] != bytes.fromhex("0fe011"):
        raise AssertionError("missing BRKXA 0x11 at FAC0:001C")
    checks.append("BRKXA 0x11")

    writers = facts["pgr_writers"]
    movs = [int(x, 16) for x in writers["mov_dx_ff00"]]
    if image.count(bytes.fromhex("ba00ff")) != len(movs):
        raise AssertionError("MOV DX,0xFF00 count is not the pinned FAC0 trio")
    for off in movs:
        _expect_hex(image, off, "ba00ff", f"MOV DX,FF00 at 0x{off:05X}")
    for off in (int(x, 16) for x in writers["outsw_files"]):
        if image[off] != 0x6F:
            raise AssertionError(f"expected OUTSW at 0x{off:05X}")
    picker = writers["port_picker"]
    _expect_hex(image, int(picker["file"], 16), picker["bytes"], "D510 port picker")
    wait = writers["wait_blocks_then_selects_task7"]
    _expect_hex(image, int(wait["file"], 16), wait["bytes"], "AMX 01CF wait")
    checks.append("PGR writers: three FAC0 OUTSW only")

    if image[0x7800A] != 0xFA:
        raise AssertionError("BIOS entry F800:000A is not CLI")
    checks.append("BIOS entry CLI")

    banner_off = 0x78125
    _expect_hex(image, banner_off, facts["bios"]["banner_bytes"], "BIOS banner")
    if image[0x78122:0x78125] != bytes.fromhex("e85017"):
        raise AssertionError("banner is not preceded by CALL 0x79875")
    checks.append("inline BIOS banner call")

    # LCD put: IN AL,E2 / AND AL,80 / JNZ / MOV AL,AH / OUT E2,AL
    _expect_hex(image, 0x7985B, "e4e2248075fa8ac4e6e2", "LCD put")
    if image[0x7986C] != 0xE6 or image[0x7986D] != 0xE0:
        raise AssertionError("LCD put does not OUT 0xE0")
    checks.append("LCD put ports 0xE2/0xE0")

    # INT 43 AX=0 begins LCD register programming through that put
    if image[0x796E4:0x796EA] != bytes.fromhex("b83c00e87001"):
        raise AssertionError("INT43 AX=0 does not start with MOV AX,0x3C / CALL LCD_put")
    checks.append("INT43 AX=0 -> LCD put")

    bios = facts["bios"]
    _expect_hex(image, int(bios["epilogue_file"], 16), bios["epilogue_bytes"], "BIOS RETF")
    checks.append("BIOS F800:0142 RETF")

    table = facts["init_table"]
    table_off = int(table["file"], 16)
    packed = "".join(rec["bytes"] for rec in table["records"])
    _expect_hex(image, table_off, packed, "init table")
    checks.append("F07A init table three records")

    _expect_hex(image, 0x7AD9E, table["exit_if_cx_zero"]["jmp_bytes"], "FAC0 CX=0 exit")
    checks.append("FAC0:019E jmp B000:00DF")

    second = facts["second_init"]
    if image[int(second["retf_file"], 16)] != 0xCB:
        raise AssertionError("F800:1AD4 does not RETF")
    if image[int(second["file"], 16) : int(second["file"], 16) + 2] != bytes.fromhex("1eb8"):
        raise AssertionError("F800:1AD4 does not begin PUSH DS / MOV AX")
    checks.append("F800:1AD4 RETF")

    amx = facts["amx"]
    _expect_hex(image, int(amx["file"], 16), amx["entry_bytes"], "AMX entry jmp")
    _expect_hex(image, int(amx["copyright_file"], 16), amx["copyright_bytes"], "KADAK copyright")
    _expect_hex(image, int(amx["dispatcher_file"], 16), amx["dispatcher_bytes"], "AMX dispatcher")
    checks.append("AMX FB00:000C / dispatcher 013E")

    _expect_hex(image, int(amx["select_file"], 16), amx["select_bytes"], "AMX 01EA")
    _expect_hex(image, int(amx["index_file"], 16), amx["index_bytes"], "AMX 0537")
    _expect_hex(image, int(amx["idle_file"], 16), amx["idle_bytes"], "AMX idle")
    create = amx["create_table"]
    rec_size = create["record_size"]
    create_file = int(create["file"], 16)
    _expect_hex(image, create_file + 6 * rec_size, create["record6_bytes"], "AMX create[6]")
    _expect_hex(image, create_file + 7 * rec_size, create["record7_bytes"], "AMX create[7]")
    if image[create_file + 8 * rec_size : create_file + 8 * rec_size + 4] != bytes.fromhex("ffffffff"):
        raise AssertionError("create table is not terminated by FFFF:FFFF")
    for rec in create["records"]:
        _expect_hex(image, int(rec["file"], 16), rec["entry_bytes"], f"create[{rec['n']}] entry")
        _expect_hex(image, int(rec["exit_file"], 16), rec["exit_bytes"], f"create[{rec['n']}] exit")
        if "exit2_file" in rec and image[int(rec["exit2_file"], 16)] != 0xCB:
            raise AssertionError(f"create[{rec['n']}] second exit is not RETF")
    dsset = create["ds8010_set"]
    _expect_hex(image, int(dsset["file"], 16), dsset["bytes"], "E937:0004 DS=8010")
    ready = amx["ready_api"]
    _expect_hex(image, int(ready["file"], 16), ready["bytes"], "AMX 0396")
    path = amx["create_path"]
    _expect_hex(image, int(path["file"], 16), path["bytes"], "AMX 0240")
    _expect_hex(image, int(path["retf_file"], 16), path["retf_bytes"], "AMX 02EE RETF")
    init = amx["pre_dispatch_init"]
    _expect_hex(image, int(init["file"], 16), init["entry_bytes"], "B03B:000A")
    _expect_hex(image, int(init["ready_tail_file"], 16), init["ready_tail_bytes"], "B03B ready 7 then 6")
    task = amx["first_task"]
    _expect_hex(image, int(task["file"], 16), task["bytes"], "D9BD:0009")
    if task["index"] != 6:
        raise AssertionError("first task index must be 6")
    checks.append("AMX 01EA / 0537 / idle / create[6]=D9BD:0009")
    checks.append("AMX create-table tasks 0–7 entries and exits")

    public = amx["public_api"]
    far_ips = {int(x, 16) for x in public["far_call_ips"]}
    far_hits = []
    pos = 0
    needle_end = bytes((0x00, 0xFB))
    while True:
        j = image.find(b"\x9a", pos)
        if j < 0 or j + 5 > len(image):
            break
        if image[j + 3 : j + 5] == needle_end:
            tip = image[j + 1] | (image[j + 2] << 8)
            far_hits.append(tip)
        pos = j + 1
    if len(far_hits) != public["far_call_count"]:
        raise AssertionError(
            f"CALL FAR FB00 count {len(far_hits)} != {public['far_call_count']}"
        )
    if set(far_hits) != far_ips:
        raise AssertionError(f"CALL FAR FB00 IPs {sorted(set(far_hits))} != pinned")
    waitp = public["wait_primitive"]
    _expect_hex(image, int(waitp["file"], 16), waitp["bytes"], "AMX 01CF")
    timed = public["timed_wait"]
    _expect_hex(image, int(timed["file"], 16), timed["bytes"], "AMX 0484")
    if image[0x7B492:0x7B495] != bytes.fromhex("894c0a"):
        raise AssertionError("0484 does not store CX at [SI+0Ah]")
    ax4 = public["wait_ax4"]
    _expect_hex(image, int(ax4["file"], 16), ax4["bytes"], "AMX 0469")
    wake = public["wake_if_bit2"]
    _expect_hex(image, int(wake["file"], 16), wake["bytes"], "AMX 04AC")
    enter = public["irq_enter"]
    _expect_hex(image, int(enter["file"], 16), enter["bytes"], "AMX 0157")
    runw = public["running_word"]
    _expect_hex(image, int(runw["file"], 16), runw["bytes"], "AMX 01EA MOV [SI],4000")
    if public["tcb_stride"] != 64:
        raise AssertionError("TCB stride must be 0x40")
    checks.append("AMX public far-call surface / TCB [SI] grammar")

    ivt = facts["ivt"]
    _expect_hex(image, int(ivt["fac0_slot10_file"], 16), ivt["fac0_slot10_bytes"], "FAC0 IVT[10h]")
    _expect_hex(image, int(ivt["default_iret_file"], 16), ivt["default_iret_bytes"], "BIOS default IRET")
    _expect_hex(image, int(ivt["bios_skip_di40_file"], 16), ivt["bios_skip_di40_bytes"], "BIOS skip DI=40")
    _expect_hex(image, int(ivt["amx_slot0_file"], 16), ivt["amx_slot0_bytes"], "AMX IVT[0]")
    _expect_hex(image, int(ivt["second_init_slot0b_file"], 16), ivt["second_init_slot0b_bytes"], "1AD4 IVT[0Bh]")
    _expect_hex(image, int(ivt["b03b_slot8_file"], 16), ivt["b03b_slot8_bytes"], "B03B IVT[8] entry")
    checks.append("IVT plants: FAC0[10h], AMX[0], 1AD4[0Bh], B03B[8]")

    ax4 = facts["int43_ax4"]
    _expect_hex(image, int(ax4["ax4_file"], 16), ax4["ax4_bytes"], "INT43 AX=4 class walk")
    _expect_hex(image, int(ax4["class_table_file"], 16), ax4["class_table_bytes"], "INT43 AX=4 class table")
    _expect_hex(image, int(ax4["default_file"], 16), ax4["default_bytes"], "INT43 AX=4 default")
    _expect_hex(image, int(ax4["cursor_set_file"], 16), ax4["cursor_set_bytes"], "INT43 cursor 1843")
    _expect_hex(image, int(ax4["walker_file"], 16), ax4["walker_bytes"], "INT43 AX=4 from walker")
    if image[0x797F2:0x797F6] != bytes.fromhex("b40ce863"):
        raise AssertionError("AX=4 default does not MOV AH,0x0C / CALL 185A")
    checks.append("INT43 AX=4 default -> LCD_put AH=0x0C")

    copy = facts["copy_7c92"]
    src = int(copy["source_file"], 16)
    _expect_hex(image, src, copy["signature_bytes"], "copy signature")
    if image[0x7AC84:0x7AC87] != bytes.fromhex("b9927c"):
        raise AssertionError("copy length is not MOV CX,0x7C92")
    if image.count(b"\xaa\x55") != copy["aa55_count"]:
        raise AssertionError("AA 55 is not unique")
    if image.count(bytes.fromhex("b81080")) != copy["mov_ax_8010_count"]:
        raise AssertionError("MOV AX,8010 count is not 21")
    if image.count(bytes.fromhex("b800a0")) != copy["mov_ax_a000_count"]:
        raise AssertionError("MOV AX,A000 is not unique")
    if image.count(bytes.fromhex("00001080")) != copy["farptr_0000_8010_count"]:
        raise AssertionError("stored 0000:8010 dword exists")
    island = int(copy["numeric_island_off"], 16)
    _expect_hex(image, src + island, copy["numeric_island_bytes"], "copy +0238 island")
    _expect_hex(image, int(copy["fac0_copy"]["file"], 16), copy["fac0_copy"]["bytes"], "FAC0:0074 copy")
    _expect_hex(image, int(copy["fac0_bss"]["file"], 16), copy["fac0_bss"]["bytes"], "FAC0:0134 BSS zero")
    _expect_hex(image, int(copy["b03b_es_a90b"]["file"], 16), copy["b03b_es_a90b"]["bytes"], "B03B ES=A90B then 065B")
    _expect_hex(
        image,
        int(copy["b03b_es_8010_mailbox"]["file"], 16),
        copy["b03b_es_8010_mailbox"]["bytes"],
        "B03B ES=8010 BX=125C",
    )
    _expect_hex(image, int(copy["amx_065b"]["file"], 16), copy["amx_065b"]["bytes"], "AMX 065B")
    if image[0x7B668:0x7B66B] != bytes.fromhex("268907"):
        raise AssertionError("065B does not MOV ES:[BX],AX")
    _expect_hex(image, int(copy["ds8010_store_1d11"]["file"], 16), copy["ds8010_store_1d11"]["bytes"], "DS=8010 [1D11]")
    moff = int(copy["mailbox_template_off"], 16)
    _expect_hex(image, src + moff, copy["mailbox_template_bytes"], "8010:125C template")
    checks.append("DS=A000 copy AA 55 / 0x7C92")
    checks.append("DGROUP 8010: directory, BSS zero, 065B overlays")

    if image[0x7AE4F:0x7AE56] != bytes.fromhex("5a595b585e1fcf"):
        raise AssertionError("ROM IVT12 continue is not POP/IRET")
    checks.append("ROM IVT12 FAC0:024F IRET tail")

    conv = facts["calling_convention"]
    walker = conv["inline_walker"]
    _expect_hex(image, int(walker["file"], 16), walker["bytes"], "inline walker 1875")
    if image.count(bytes.fromhex(walker["pattern"])) != 1:
        raise AssertionError("POP SI / ES=CS walker stub is not unique")
    for caller_hex in walker["callers"]:
        off = int(caller_hex, 16)
        if image[off] != 0xE8:
            raise AssertionError(f"walker caller 0x{off:05X} is not CALL near")
        rel = image[off + 1] | (image[off + 2] << 8)
        if rel >= 0x8000:
            rel -= 0x10000
        ip = off - 0x78000
        if (ip + 3 + rel) & 0xFFFF != 0x1875:
            raise AssertionError(f"0x{off:05X} does not CALL F800:1875")
    cdecl = conv["far_cdecl_wait"]
    _expect_hex(image, int(cdecl["file"], 16), cdecl["bytes"], "B060 far cdecl")
    lds = conv["far_cdecl_lds"]
    _expect_hex(image, int(lds["file"], 16), lds["bytes"], "D9B5 LDS [BP+6]")
    three = conv["task6_three_arg_call"]
    _expect_hex(image, int(three["file"], 16), three["bytes"], "task6 cdecl three-arg")
    if image.count(bytes.fromhex("8b4604")) != conv["mov_ax_bp4_count"]:
        raise AssertionError("MOV AX,[BP+4] count is not zero")
    checks.append("calling convention: walker + far cdecl")

    wrap = facts["irq_wrappers"]
    _expect_hex(image, int(wrap["fac0_01a4"]["file"], 16), wrap["fac0_01a4"]["bytes"], "FAC0:01A4")
    if image[0x7ADBA:0x7ADBD] != bytes.fromhex("0ff012"):
        raise AssertionError("FAC0:01A4 does not RETXA 0x12")
    if image[0x7ADCC:0x7ADCF] != bytes.fromhex("0fe012"):
        raise AssertionError("FAC0:01CC is not BRKXA 0x12")
    _expect_hex(image, int(wrap["rom_ivt12_continue"]["file"], 16), wrap["rom_ivt12_continue"]["bytes"], "FAC0:024F")
    _expect_hex(image, int(wrap["amx_02f8"]["file"], 16), wrap["amx_02f8"]["bytes"], "AMX 02F8")
    _expect_hex(image, int(wrap["amx_02ef"]["file"], 16), wrap["amx_02ef"]["bytes"], "AMX 02EF")
    _expect_hex(image, int(wrap["hook_rewrite"]["file"], 16), wrap["hook_rewrite"]["bytes"], "AMX 0312")
    _expect_hex(image, int(wrap["irq_enter"]["file"], 16), wrap["irq_enter"]["bytes"], "AMX 0157")
    _expect_hex(image, int(wrap["irq_stack"]["file"], 16), wrap["irq_stack"]["bytes"], "0157 SS:SP")
    checks.append("IRQ wrappers: FAC0 XA switch, AMX IRET rewrite")

    panel = facts["front_panel"]
    if panel["rom_present"] is not False:
        raise AssertionError("front_panel.rom_present must stay false while the dump is absent")
    rom_hits = list((REPO_ROOT / "07-rom").rglob("*ic602*")) + list(
        (REPO_ROOT / "07-rom").rglob("*op_v1*")
    )
    if rom_hits:
        raise AssertionError(f"panel ROM dump appeared under 07-rom/: {rom_hits[0]}")
    _expect_hex(image, int(panel["b03b_out_c2_file"], 16), panel["b03b_out_c2_bytes"], "B03B OUT 0xC2")
    _expect_hex(image, int(panel["d547_in_d2_file"], 16), panel["d547_in_d2_bytes"], "D547 IN 0xD2")
    checks.append("D19 PARTIAL: panel ROM absent; 0xC0-0xDF I/O encodings pinned")

    ledger = load_ledger()
    checks.extend(validate_ledger(image, ledger))
    meta = facts["owner_ledger"]
    n_notes = notes_covered(ledger)
    if n_notes != meta["note_rows"]:
        raise AssertionError(f"note ownership rows {n_notes} != pinned")
    if ledger["owned_bytes"] != meta["owned_bytes"]:
        raise AssertionError("owned_bytes does not match facts")
    if len(ledger["ranges"]) != meta["range_count"]:
        raise AssertionError("ledger range_count does not match facts")
    if len(gaps(ledger_spans(ledger))) != meta["gap_count"]:
        raise AssertionError("ledger gap_count does not match facts")
    if validate_ff_windows(image, ledger) != meta["ff_runs_ge4"]:
        raise AssertionError("FF run count does not match facts")
    checks.append(f"owner ledger: {ledger['owned_bytes']} bytes, {n_notes} note rows")

    scan = load_scan()
    checks.extend(validate_string_scan(image, scan))
    smeta = facts["string_scan"]
    if scan["established"]["unique_starts"] != smeta["established_unique"]:
        raise AssertionError("string_scan established_unique does not match facts")
    if scan["push_ds_far"]["count"] != smeta["push_ds_far_count"]:
        raise AssertionError("string_scan PUSH DS+far count does not match facts")
    if scan["directory"]["ptr_8010"] != smeta["directory_ptr_8010"]:
        raise AssertionError("string_scan directory count does not match facts")
    checks.append(
        f"string scan: {scan['established']['unique_starts']} established, "
        f"{scan['candidates']['dgroup_unconsumed_min2']} DGROUP candidates"
    )

    entries = load_entry_scan()
    checks.extend(validate_entry_scan(image, entries))
    emeta = facts["entry_scan"]
    if entries["established"]["unique_cs_ip"] != emeta["unique_cs_ip"]:
        raise AssertionError("entry_scan unique_cs_ip does not match facts")
    if entries["raw_encodings"]["callf_9a"] != emeta["raw_9a"]:
        raise AssertionError("entry_scan raw 9A count does not match facts")
    checks.append(
        f"entry scan: {entries['established']['unique_cs_ip']} unique CS:IP, "
        f"{entries['raw_encodings']['callf_9a']} raw 9A suspects"
    )

    transfers = load_transfer_scan()
    checks.extend(validate_transfer_scan(image, transfers))
    tmeta = facts["transfer_scan"]
    if transfers["entries"] != tmeta["entries"]:
        raise AssertionError("transfer_scan entries does not match facts")
    if transfers["status_counts"]["bounded"] != tmeta["bounded"]:
        raise AssertionError("transfer_scan bounded does not match facts")
    if transfers["status_counts"]["indirect"] != tmeta["indirect"]:
        raise AssertionError("transfer_scan indirect does not match facts")
    if transfers["status_counts"]["loop"] != tmeta["loop"]:
        raise AssertionError("transfer_scan loop does not match facts")
    if transfers["discovered"]["callf_new"] != tmeta["callf_new"]:
        raise AssertionError("transfer_scan callf_new does not match facts")
    if transfers["discovered"]["calln_new"] != tmeta["calln_new"]:
        raise AssertionError("transfer_scan calln_new does not match facts")
    if transfers["discovered"]["jmpf_unestablished"] != tmeta["jmpf_unestablished"]:
        raise AssertionError("transfer_scan jmpf_unestablished does not match facts")
    checks.append(
        f"transfer scan: {transfers['entries']} entries, "
        f"{transfers['status_counts']['bounded']} bounded, "
        f"{transfers['status_counts']['indirect']} indirect, "
        f"{transfers['status_counts']['loop']} loop"
    )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, default=FACTS_PATH)
    args = parser.parse_args()
    facts = json.loads(args.facts.read_text())
    image = load_vailixi_linear()
    checks = verify(image, facts)
    print(f"PASS {len(checks)} boot-slice checks")
    for item in checks:
        print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
