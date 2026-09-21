#!/usr/bin/env python3
"""Reproduce the pinned Vailixi 3.50 reset-to-LCD-init facts from the chip pair."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.linear_rom import LINEAR_SHA256, load_vailixi_linear, sha256_bytes

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
    _expect_hex(image, int(copy["source_file"], 16), copy["signature_bytes"], "copy signature")
    if image[0x7AC84:0x7AC87] != bytes.fromhex("b9927c"):
        raise AssertionError("copy length is not MOV CX,0x7C92")
    checks.append("DS=A000 copy AA 55 / 0x7C92")

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
