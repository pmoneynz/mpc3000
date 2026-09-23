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
from tools.v53_decode import decode_one, follow_local

REPO_ROOT = Path(__file__).resolve().parents[1]
FACTS_PATH = REPO_ROOT / "analysis" / "boot_slice_facts.json"


def _u16(image: bytes, offset: int) -> int:
    return image[offset] | (image[offset + 1] << 8)


def _expect_hex(image: bytes, offset: int, expected_hex: str, label: str) -> None:
    raw = bytes.fromhex(expected_hex)
    got = image[offset : offset + len(raw)]
    if got != raw:
        raise AssertionError(f"{label}: file 0x{offset:05X} expected {expected_hex}, got {got.hex()}")


def _fb00_near(image: bytes, target: int) -> list[int]:
    """File offsets in FB00 whose E8/E9/EB/Jcc short target this IP."""
    base = 0x7B000
    end = min(len(image), base + 0x5000)
    hits: list[int] = []
    i = base
    while i + 2 < end:
        op = image[i]
        ip = i - base
        if op in (0xE8, 0xE9) and i + 3 <= end:
            rel = image[i + 1] | (image[i + 2] << 8)
            if rel >= 0x8000:
                rel -= 0x10000
            tgt = (ip + 3 + rel) & 0xFFFF
            if tgt == target:
                hits.append(i)
        elif op == 0xEB or 0x70 <= op <= 0x7F:
            rel = image[i + 1]
            if rel >= 128:
                rel -= 256
            tgt = (ip + 2 + rel) & 0xFFFF
            if tgt == target:
                hits.append(i)
        i += 1
    return hits


def _check_idle_wake(image: bytes, wake: dict) -> None:
    _expect_hex(image, int(wake["handler_file"], 16), "9a570100fb", "IVT[8] CALL 0157")
    _expect_hex(image, int(wake["call_0586_file"], 16), wake["call_0586_bytes"], "D52A CALL 0586")
    _expect_hex(image, int(wake["eoi_file"], 16), wake["eoi_bytes"], "D52A OUT 0xC010")
    _expect_hex(image, int(wake["call_0194_file"], 16), wake["call_0194_bytes"], "D52A CALL 0194")
    if image[int(wake["iret_file"], 16)] != 0xCF:
        raise AssertionError("D52A:005D is not IRET")
    _expect_hex(image, int(wake["tick_reload_file"], 16), wake["tick_reload_bytes"], "FB76:00A4")
    if _u16(image, int(wake["tick_reload_file"], 16)) != wake["tick_reload_value"]:
        raise AssertionError("tick reload is not 10")
    _expect_hex(image, int(wake["header_store_file"], 16), wake["header_store_bytes"], "start [DI+14]")
    _expect_hex(image, int(wake["counter_init_call_file"], 16), wake["counter_init_call_bytes"], "055F CALL 05AB")
    _expect_hex(image, int(wake["counter_copy_file"], 16), wake["counter_copy_bytes"], "05AB copy tick")
    _expect_hex(image, int(wake["dec_file"], 16), wake["dec_bytes"], "0586 DEC [DI+12]")
    _expect_hex(image, int(wake["dec_jnz_file"], 16), wake["dec_jnz_bytes"], "0586 JNZ")
    _expect_hex(image, int(wake["call_05a0_file"], 16), wake["call_05a0_bytes"], "0586 CALL 05A0")
    _expect_hex(image, int(wake["ready_slot0_file"], 16), wake["ready_slot0_bytes"], "05A0 ready DL=0")
    _expect_hex(image, int(wake["reschedule_file"], 16), wake["reschedule_bytes"], "0194 INC nest")
    _expect_hex(image, int(wake["index_cmp_file"], 16), wake["index_cmp_bytes"], "0194 index compare")
    _expect_hex(image, int(wake["scan_index_file"], 16), wake["scan_index_bytes"], "01EA both indices")
    _expect_hex(image, int(wake["wait_js_file"], 16), wake["wait_js_bytes"], "01CF JS 01EA")
    _expect_hex(image, int(wake["sentinel_mask_file"], 16), wake["sentinel_mask_bytes"], "01CF keep bit 15")
    _expect_hex(image, int(wake["hook_zero_file"], 16), wake["hook_zero_bytes"], "0284 zero hooks")
    _expect_hex(image, int(wake["second_pgr_frame_file"], 16), wake["second_pgr_frame"], "second PGR[53]")
    _expect_hex(image, int(wake["third_pgr_frame_file"], 16), wake["third_pgr_frame"], "third PGR[53]")
    if image[int(wake["int10_file"], 16) : int(wake["int10_file"], 16) + 2] != bytes.fromhex("cd10"):
        raise AssertionError("pinned INT 10h site is not CD 10")
    int10 = []
    pos = 0
    while True:
        j = image.find(bytes.fromhex("cd10"), pos)
        if j < 0:
            break
        int10.append(j)
        pos = j + 1
    if int10 != [int(wake["int10_file"], 16)]:
        raise AssertionError(f"INT 10h sites {int10} != pinned")
    plants = []
    pos = 0
    pat = bytes.fromhex("9a470300fb")
    while True:
        j = image.find(pat, pos)
        if j < 0:
            break
        if image[j - 2] != 0xB2:
            raise AssertionError(f"CALL 0347 at 0x{j:05X} is not preceded by MOV DL,imm8")
        plants.append(image[j - 1])
        pos = j + 1
    if plants != wake["plant_dl"]:
        raise AssertionError(f"0347 DL values {plants} != pinned")
    if any(dl in (0, 4) for dl in plants):
        raise AssertionError("0347 hook arm DL 0/4 is reachable")
    far_0586 = []
    pos = 0
    pat = bytes.fromhex("9a860500fb")
    while True:
        j = image.find(pat, pos)
        if j < 0:
            break
        far_0586.append(j)
        pos = j + 1
    if far_0586 != [int(wake["call_0586_file"], 16)]:
        raise AssertionError(f"CALLF 0586 sites {far_0586}")
    if _fb00_near(image, 0x0586):
        raise AssertionError("near transfer to 0586 exists in FB00")
    if _fb00_near(image, 0x05A0) != [int(wake["call_05a0_file"], 16)]:
        raise AssertionError("05A0 callers are not only 0586")
    if _fb00_near(image, 0x05AB) != [int(wake["counter_init_call_file"], 16)]:
        raise AssertionError("05AB callers are not only 055F")
    if _fb00_near(image, 0x0396) != [0x7B5A3]:
        raise AssertionError("near CALL 0396 is not only 05A3")
    if _fb00_near(image, 0x0996) or _fb00_near(image, 0x09B8):
        raise AssertionError("FB00:0996 has a near transfer")
    if image.find(bytes.fromhex("960900fb")) != -1 or image.find(bytes.fromhex("b80900fb")) != -1:
        raise AssertionError("stored far pointer to FB00:0996/09B8")
    entries = _fb00_near(image, 0x01EA)
    if entries != [0x7B143, 0x7B1E2, 0x7B281]:
        raise AssertionError(f"01EA entries { [hex(x) for x in entries] }")
    if _fb00_near(image, 0x0281):
        raise AssertionError("something transfers to 0281")


def _find_all(image: bytes, pat: bytes) -> list[int]:
    found: list[int] = []
    pos = 0
    while True:
        hit = image.find(pat, pos)
        if hit < 0:
            break
        found.append(hit)
        pos = hit + 1
    return found


def _walk_body(image: bytes, cs: int, ip: int):
    body, hit = follow_local(image, cs, ip, limit=800)
    if hit:
        raise AssertionError(f"{cs:04X}:{ip:04X} walk hit the instruction cap")
    return body


def _is_out(raw: bytes) -> bool:
    if raw[:1] in (b"\xee", b"\xef", b"\xe6", b"\xe7", b"\x6e", b"\x6f"):
        return True
    return raw[:2] in (b"\xf3\x6e", b"\xf3\x6f", b"\xf2\x6e", b"\xf2\x6f")


def _pgr_dx(raw: bytes) -> int | None:
    if len(raw) >= 3 and raw[0] == 0xBA and raw[2] == 0xFF and raw[1] <= 0x7E:
        return raw[1] | 0xFF00
    return None


def _near_targets(image: bytes, cs: int, target: int) -> list[int]:
    base = (cs << 4) & 0x7FFFF
    end = min(len(image), base + 0x10000)
    hits: list[int] = []
    i = base
    while i < end - 2:
        op = image[i]
        ip = i - base
        if op in (0xE8, 0xE9) and i + 3 <= end:
            rel = image[i + 1] | (image[i + 2] << 8)
            if rel >= 0x8000:
                rel -= 0x10000
            if ((ip + 3 + rel) & 0xFFFF) == target:
                hits.append(i)
        elif op == 0xEB or 0x70 <= op <= 0x7F:
            rel = image[i + 1]
            if rel >= 128:
                rel -= 256
            if ((ip + 2 + rel) & 0xFFFF) == target:
                hits.append(i)
        i += 1
    return hits


def _check_d510_and_task7(image: bytes, writers: dict) -> None:
    for entry, pat in (("008D", bytes.fromhex("9a8d0010d5")), ("0118", bytes.fromhex("9a180110d5"))):
        found = _find_all(image, pat)
        expect = [int(row["file"], 16) for row in writers["d510_callers"] if row["entry"] == entry]
        if found != expect:
            raise AssertionError(f"D510:{entry} callers {found} != {expect}")
    for row in writers["d510_callers"]:
        _expect_hex(image, int(row["file"], 16), row["bytes"], f"D510 caller {row['entry']}")
    _expect_hex(image, int(writers["d510_ret_file"], 16), writers["d510_ret_bytes"], "D510:0118 return AX")
    for cs, ip, name in ((0xD510, 0x008D, "008D"), (0xD510, 0x0118, "0118")):
        outs = [insn.file for insn in _walk_body(image, cs, ip) if _is_out(bytes.fromhex(insn.bytes_hex))]
        if outs:
            raise AssertionError(f"D510:{name} has OUT at {outs}")
    task = writers["task7_pgr"]
    root = _walk_body(image, 0xB000, 0x00DF)
    direct = [(insn.target_cs, insn.target_ip) for insn in root if insn.kind == "CALLF"]
    if len(direct) != task["direct_calls"]:
        raise AssertionError(f"task 7 direct CALLF {len(direct)} != {task['direct_calls']}")
    seen = {(cs, ip) for cs, ip in direct if cs is not None and ip is not None}
    children: set[tuple[int, int]] = set()
    for cs, ip in seen:
        for insn in _walk_body(image, cs, ip):
            port = _pgr_dx(bytes.fromhex(insn.bytes_hex))
            if port is not None:
                raise AssertionError(f"task 7 callee MOV DX,0x{port:04X} at 0x{insn.file:05X}")
            if insn.kind == "CALLF" and insn.target_cs is not None and insn.target_ip is not None:
                children.add((insn.target_cs, insn.target_ip))
    for cs, ip in children - seen:
        for insn in _walk_body(image, cs, ip):
            port = _pgr_dx(bytes.fromhex(insn.bytes_hex))
            if port is not None:
                raise AssertionError(f"task 7 nested MOV DX,0x{port:04X} at 0x{insn.file:05X}")
    walked = len(seen | children)
    if walked != task["walked"] or task["mov_dx_ff_window"] != 0:
        raise AssertionError(f"task 7 PGR walk {walked} != pinned")
    third = task["third_callee"]
    _expect_hex(image, int(third["file"], 16), third["entry_bytes"], "D9DD:005D entry")
    _expect_hex(image, int(third["xor_dx_file"], 16), third["xor_dx_bytes"], "D9DD:005D XOR DX,DX")
    _expect_hex(image, int(third["retf_file"], 16), third["retf_bytes"], "D9DD:005D RETF")
    _expect_hex(
        image,
        int(third["parent_callf_file"], 16),
        third["parent_callf_bytes"],
        "DDF4:005E CALLF E21A:000B",
    )
    _expect_hex(
        image,
        int(third["second_pgr54_file"], 16),
        third["second_pgr54_bytes"],
        "second PGR[54]",
    )
    e21a = _walk_body(image, 0xE21A, 0x000B)
    callf_files = [insn.file for insn in e21a if insn.kind == "CALLF"]
    expect_callf = [int(x, 16) for x in third["caller_callf_files"]]
    if callf_files != expect_callf:
        raise AssertionError(f"E21A:000B CALLF sites {callf_files} != {expect_callf}")
    for off in expect_callf:
        _expect_hex(image, off, third["callf_bytes"], f"E21A CALLF D9DD:005D at 0x{off:05X}")
        insn = [row for row in e21a if row.file == off][0]
        if (insn.target_cs, insn.target_ip) != (0xD9DD, 0x005D):
            raise AssertionError(f"E21A CALLF at 0x{off:05X} is not D9DD:005D")
    body = _walk_body(image, 0xD9DD, 0x005D)
    for insn in body:
        raw = bytes.fromhex(insn.bytes_hex)
        port = _pgr_dx(raw)
        if port is not None:
            raise AssertionError(f"D9DD:005D MOV DX,0x{port:04X} at 0x{insn.file:05X}")
        if _is_out(raw):
            raise AssertionError(f"D9DD:005D OUT at 0x{insn.file:05X}")
    if not body or body[-1].kind != "RETF" or body[-1].file != int(third["retf_file"], 16):
        raise AssertionError("D9DD:005D does not end RETF at the pinned file")
    ddc0 = task["third_callee_ddc0"]
    _expect_hex(image, int(ddc0["file"], 16), ddc0["entry_bytes"], "DDC0:0031 entry")
    _expect_hex(image, int(ddc0["xor_dx_file"], 16), ddc0["xor_dx_bytes"], "DDC0:0031 XOR DX,DX")
    _expect_hex(image, int(ddc0["retf_file"], 16), ddc0["retf_bytes"], "DDC0:0031 RETF")
    _expect_hex(image, int(ddc0["retf_early_file"], 16), ddc0["retf_bytes"], "DDC0:00EE RETF")
    _expect_hex(
        image,
        int(ddc0["l2_callf_file"], 16),
        ddc0["l2_callf_bytes"],
        "DDF4:007D CALLF E70C:007E",
    )
    _expect_hex(
        image,
        int(ddc0["parent_callf_file"], 16),
        ddc0["parent_callf_bytes"],
        "E70C:0095 CALLF DDC0:0031",
    )
    _expect_hex(
        image,
        int(ddc0["second_pgr55_file"], 16),
        ddc0["second_pgr55_bytes"],
        "second PGR[55]",
    )
    if ((0xDDC0 << 4) + 0x0031) & 0x7FFFF != int(ddc0["file"], 16):
        raise AssertionError("DDC0:0031 file is not ((CS<<4)+IP)&0x7FFFF")
    e70c = _walk_body(image, 0xE70C, 0x007E)
    callf_ddc0 = [insn for insn in e70c if insn.kind == "CALLF"]
    if len(callf_ddc0) != 2:
        raise AssertionError(f"E70C:007E CALLF count {len(callf_ddc0)} != 2")
    first = callf_ddc0[0]
    if first.file != int(ddc0["parent_callf_file"], 16) or (first.target_cs, first.target_ip) != (
        0xDDC0,
        0x0031,
    ):
        raise AssertionError("E70C:007E first CALLF is not DDC0:0031")
    body = _walk_body(image, 0xDDC0, 0x0031)
    for insn in body:
        raw = bytes.fromhex(insn.bytes_hex)
        port = _pgr_dx(raw)
        if port is not None:
            raise AssertionError(f"DDC0:0031 MOV DX,0x{port:04X} at 0x{insn.file:05X}")
        if _is_out(raw):
            raise AssertionError(f"DDC0:0031 OUT at 0x{insn.file:05X}")
    if not body or body[-1].kind != "RETF" or body[-1].file != int(ddc0["retf_file"], 16):
        raise AssertionError("DDC0:0031 does not end RETF at the pinned file")
    nxt = task["next_third"]
    _expect_hex(image, int(nxt["call_file"], 16), nxt["call_bytes"], "E70C:00A0 CALLF DDC0:000F")
    if (callf_ddc0[1].target_cs, callf_ddc0[1].target_ip) != (0xDDC0, 0x000F):
        raise AssertionError("E70C:007E second CALLF is not DDC0:000F")
    if callf_ddc0[1].file != int(nxt["call_file"], 16):
        raise AssertionError("E70C:00A0 CALLF file is not the pinned next_third")


def _check_d6ac_store(image: bytes, pin: dict) -> None:
    a2 = _find_all(image, bytes.fromhex("a2acd6"))
    c6 = _find_all(image, bytes.fromhex(pin["c6_bytes"]))
    if a2 != [int(x, 16) for x in pin["a2_files"]]:
        raise AssertionError(f"[D6AC] A2 stores {a2}")
    if c6 != [int(x, 16) for x in pin["c6_files"]]:
        raise AssertionError(f"[D6AC] C6 stores {c6}")
    for kind, pat in (
        ("8806", "8806acd6"),
        ("a3", "a3acd6"),
        ("8906", "8906acd6"),
        ("fe06", "fe06acd6"),
        ("c706", "c706acd6"),
    ):
        if _find_all(image, bytes.fromhex(pat)):
            raise AssertionError(f"unexpected [D6AC] store form {kind}")
    _expect_hex(image, int(pin["gap_store_file"], 16), pin["gap_store_bytes"], "D52A:0328 store")
    _expect_hex(image, int(pin["jmp_file"], 16), pin["jmp_bytes"], "D52A:0315 JMP 06A0")
    _expect_hex(image, int(pin["cmp_file"], 16), pin["cmp_bytes"], "D52A:0318 CMP AL,0x10")
    _expect_hex(image, int(pin["xlat_file"], 16), pin["xlat_bytes"], "D52A:031F XLAT")
    _expect_hex(image, int(pin["xlat_base_file"], 16), pin["xlat_base_bytes"], "D52A:0057 OUT/CALL/IRET")
    _expect_hex(image, int(pin["state_e0_file"], 16), pin["state_e0_bytes"], "D52A:0312 MOV BX,0492")
    _expect_hex(image, int(pin["tail_file"], 16), pin["tail_bytes"], "D52A:06A0 store [7626]")
    _expect_hex(image, int(pin["second_pgr53_file"], 16), pin["second_pgr53_bytes"], "second PGR[53]")
    if image.find(bytes.fromhex("bb1803")) != -1 or image.find(bytes.fromhex("18032ad5")) != -1:
        raise AssertionError("static immediate targets D52A:0318")
    if image.find(bytes.fromhex("bb2803")) != -1 or image.find(bytes.fromhex("28032ad5")) != -1:
        raise AssertionError("static immediate targets D52A:0328")
    base = (0xD52A << 4) & 0x7FFFF
    end = base + 0x10000
    for word, ip in ((bytes.fromhex("1803"), 0x0318), (bytes.fromhex("2803"), 0x0328)):
        if image.find(word, base, end) != -1:
            raise AssertionError(f"word {ip:04X} appears in CS D52A")
        if _near_targets(image, 0xD52A, ip):
            raise AssertionError(f"near/short targets D52A:{ip:04X}")


def _d52a_owned_walk(image: bytes, pin: dict) -> tuple[set[int], dict[int, list[tuple[int, str]]]]:
    """Instruction starts in CS D52A reached from owned code, plus edges."""
    cs = 0xD52A
    base = (cs << 4) & 0x7FFFF
    end = base + 0x10000
    edges: dict[int, list[tuple[int, str]]] = {}
    seen: set[int] = set()
    work: list[int] = []
    for start, stop, owner, _kind in ledger_spans(load_ledger()):
        if owner != "code" or stop <= base or start >= end:
            continue
        seed_file = max(start, base)
        if _file_in_d547_store_bodies(pin, seed_file):
            continue
        work.append((seed_file - base) & 0xFFFF)
    while work:
        ip = work.pop()
        if ip in seen:
            continue
        seen.add(ip)
        if _file_in_d547_store_bodies(pin, (base + ip) & 0x7FFFF):
            continue
        insn = decode_one(image, cs, ip)
        kind = insn.kind

        def add(target: int, how: str) -> None:
            edges.setdefault(target, []).append((ip, how))
            if target not in seen:
                work.append(target)

        if kind in ("RET", "RETF", "IRET", "RETN", "RETFN", "JMPF", "JMPF_RM", "UNKNOWN_0F", "JMPN_RM"):
            continue
        if kind in ("CALLN", "CALLF", "CALLN_RM", "CALLF_RM", "BRKXA", "RETXA"):
            add((ip + insn.length) & 0xFFFF, "next")
            continue
        if kind in ("JMPN", "JMPS"):
            add(insn.target_ip or 0, kind)
            continue
        if kind == "JCC":
            add((ip + insn.length) & 0xFFFF, "fall")
            add(insn.target_ip or 0, "JCC")
            continue
        add((ip + insn.length) & 0xFFFF, "next")
    return seen, edges


def _file_in_d547_store_bodies(pin: dict, file_off: int) -> bool:
    """Those file bytes run with CS D547. The D52A window aliases them."""
    spans = [
        (int(pin["state_0663"]["body_file"], 16), int(pin["state_0663"]["body_end"], 16)),
        (int(pin["state_066d"]["body_file"], 16), int(pin["state_066d"]["body_end"], 16)),
        (int(pin["state_066d"]["join_file"], 16), int(pin["state_066d"]["join_end"], 16)),
        (int(pin["state_d547_051f"]["body_file"], 16), int(pin["state_d547_051f"]["body_end"], 16)),
        (int(pin["state_0694"]["body_file"], 16), int(pin["state_0694"]["body_end"], 16)),
        (int(pin["state_06d3"]["body_file"], 16), int(pin["state_06d3"]["body_end"], 16)),
        (int(pin["state_06dd"]["body_file"], 16), int(pin["state_06dd"]["body_end"], 16)),
        (int(pin["state_06ec"]["body_file"], 16), int(pin["state_06ec"]["body_end"], 16)),
        (int(pin["state_06ec"]["join_file"], 16), int(pin["state_06ec"]["join_end"], 16)),
        (int(pin["state_071c"]["body_file"], 16), int(pin["state_071c"]["body_end"], 16)),
        (int(pin["state_0726"]["body_file"], 16), int(pin["state_0726"]["body_end"], 16)),
        (int(pin["state_0733"]["body_file"], 16), int(pin["state_0733"]["body_end"], 16)),
        (int(pin["state_073d"]["body_file"], 16), int(pin["state_073d"]["body_end"], 16)),
        (int(pin["state_073d"]["alias_file"], 16), int(pin["state_073d"]["alias_end"], 16)),
        (int(pin["state_0780"]["body_file"], 16), int(pin["state_0780"]["body_end"], 16)),
        (int(pin["state_07af"]["body_file"], 16), int(pin["state_07af"]["body_end"], 16)),
        (int(pin["state_07de"]["body_file"], 16), int(pin["state_07de"]["body_end"], 16)),
        (int(pin["state_07e1"]["body_file"], 16), int(pin["state_07e1"]["body_end"], 16)),
        (int(pin["state_082b"]["body_file"], 16), int(pin["state_082b"]["body_end"], 16)),
        (int(pin["state_062d"]["body_file"], 16), int(pin["state_062d"]["body_end"], 16)),
        (int(pin["state_065d"]["body_file"], 16), int(pin["state_065d"]["body_end"], 16)),
        (int(pin["state_08cf"]["body_file"], 16), int(pin["state_08cf"]["body_end"], 16)),
        (int(pin["state_08d9"]["body_file"], 16), int(pin["state_08d9"]["body_end"], 16)),
        (0x559F1, 0x55A9D),
    ]
    return any(lo <= file_off < hi for lo, hi in spans)


def _check_d52a_computed(image: bytes, pin: dict) -> None:
    """Reached computed near transfers in CS D52A cannot enter 0318 or 0328."""
    cs = 0xD52A
    base = (cs << 4) & 0x7FFFF
    end = base + 0x10000
    comp = pin["computed"]
    seen, edges = _d52a_owned_walk(image, pin)
    indirect: list[tuple[int, str]] = []
    for ip in sorted(seen):
        insn = decode_one(image, cs, ip)
        if insn.kind in ("JMPN_RM", "CALLN_RM"):
            indirect.append((insn.file, insn.bytes_hex))
    if len(indirect) != int(comp["reached_indirect"]):
        raise AssertionError(f"D52A reached indirect near {len(indirect)}")
    jmp_bx = [off for off, hx in indirect if hx == "ffe3"]
    cs_mem = [off for off, hx in indirect if hx.startswith("2eff")]
    if jmp_bx != [int(x, 16) for x in comp["jmp_bx_files"]]:
        raise AssertionError(f"D52A JMP BX files {jmp_bx}")
    if len(cs_mem) != int(comp["cs_memory_indirect"]) or len(jmp_bx) + len(cs_mem) != len(indirect):
        raise AssertionError("D52A indirect near is not CS-memory plus two JMP BX")
    for reg in range(8):
        for ipw, name in ((0x0318, "0318"), (0x0328, "0328")):
            sig = bytes([0xB8 + reg, ipw & 0xFF, ipw >> 8])
            if image.find(sig) != -1:
                raise AssertionError(f"MOV r{reg},0x{name} exists")
    _expect_hex(image, int(comp["load_7626_file"], 16), comp["load_7626_bytes"], "MOV BX,[7626]")
    _expect_hex(image, int(comp["dgroup_7626_file"], 16), comp["dgroup_7626_bytes"], "DGROUP [7626]")
    _expect_hex(image, int(comp["read_762e_file"], 16), comp["read_762e_bytes"], "MOV BX,[SI+762E]/JMP BX")
    _expect_hex(image, int(comp["dgroup_762e_file"], 16), comp["dgroup_762e_bytes"], "DGROUP [762E]")
    if image.find(bytes.fromhex("2676")) != int(comp["load_7626_file"], 16) + 2:
        raise AssertionError("[7626] abs is not only the load and the tail store")
    hits = _find_all(image, bytes.fromhex("2676"))
    if hits != [int(comp["load_7626_file"], 16) + 2, int(pin["tail_file"], 16) + 2]:
        raise AssertionError(f"[7626] abs sites {hits}")
    allowed = {int(x, 16) for x in comp["tail_bx"]}
    found: set[int] = set()
    i = base
    while i < end - 2:
        op = image[i]
        ip = i - base
        dest = None
        if op == 0xE9 and i + 3 <= end:
            rel = image[i + 1] | (image[i + 2] << 8)
            if rel >= 0x8000:
                rel -= 0x10000
            dest = (ip + 3 + rel) & 0xFFFF
        elif op == 0xEB:
            rel = image[i + 1]
            if rel >= 128:
                rel -= 256
            dest = (ip + 2 + rel) & 0xFFFF
        if dest == 0x06A0:
            if image[i - 3] != 0xBB:
                raise AssertionError(f"jump to 06A0 at 0x{i:05X} is not MOV BX,imm")
            imm = image[i - 2] | (image[i - 1] << 8)
            if imm in (0x0318, 0x0328):
                raise AssertionError(f"06A0 stores BX=0x{imm:04X}")
            found.add(imm)
        i += 1
    if found != allowed:
        raise AssertionError(f"[7626] BX set {sorted(found)} != pinned")
    # Fallthrough into the store is MOV BX,0x011D.
    if image[int(pin["tail_file"], 16) - 3 : int(pin["tail_file"], 16)] != bytes.fromhex("bb1d01"):
        raise AssertionError("fallthrough into [7626] store is not MOV BX,0x011D")

    # Reached writers of [SI+762E]: the 071A block and the one walked jump to 0AD7.
    # D547:0663 is the same file bytes under CS D547; do not count it as a D52A writer.
    _expect_hex(image, 0x559BA, "bb1f05d1e6899c2e76", "MOV BX,051F / store [SI+762E]")
    _expect_hex(image, 0x559F1, "bbe107e98003", "MOV BX,07E1 / JMP 0AD7")

    def _d52a_file(ip: int) -> int:
        return ((0xD52A << 4) + ip) & 0x7FFFF

    jumped = sorted(
        src
        for src, how in edges.get(0x0AD7, [])
        if how in ("JMPN", "JMPS") and not _file_in_d547_store_bodies(pin, _d52a_file(src))
    )
    if jumped:
        raise AssertionError(f"walked jumps to 0AD7 {jumped}")
    if 0x071A not in seen or 0x0AD9 not in seen:
        raise AssertionError("table store blocks are not in the owned walk")
    table_ok = {int(x, 16) for x in comp["table_bx"]}
    i = base
    while i < end - 2:
        op = image[i]
        ip = i - base
        dest = None
        if op == 0xE9 and i + 3 <= end:
            rel = image[i + 1] | (image[i + 2] << 8)
            if rel >= 0x8000:
                rel -= 0x10000
            dest = (ip + 3 + rel) & 0xFFFF
        elif op == 0xEB:
            rel = image[i + 1]
            if rel >= 128:
                rel -= 256
            dest = (ip + 2 + rel) & 0xFFFF
        if dest in (0x0AD0, 0x0AD7) and image[i - 3] == 0xBB:
            imm = image[i - 2] | (image[i - 1] << 8)
            if imm in (0x0318, 0x0328):
                raise AssertionError(f"table jump at 0x{i:05X} stores 0x{imm:04X}")
            mov_file = i - 3
            # D547 MOV BX,imm / JMP 0907. The D52A window aliases those files.
            if _file_in_d547_store_bodies(pin, mov_file) or _file_in_d547_store_bodies(pin, i):
                i += 1
                continue
            if mov_file >= 0x559F1 and mov_file < int(pin["state_07e1"]["body_end"], 16):
                i += 1
                continue
            if ip in seen and imm not in table_ok:
                raise AssertionError(f"reached table jump stores 0x{imm:04X}")
        i += 1

    # Reached MOV BX,imm / JMP 06A0. 0492 is the only one whose IP is a gap.
    state = pin["state_0492"]
    if 0x0312 not in seen or 0x06A0 not in seen:
        raise AssertionError("writer 06A0 or MOV BX,0492 is not in the owned walk")
    if 0x069D in seen:
        raise AssertionError("unreached fallthrough MOV BX,011D is in the owned walk")
    mov = decode_one(image, cs, 0x0312)
    nxt = decode_one(image, cs, 0x0315)
    if mov.bytes_hex != state["mov_bytes"] or nxt.kind != "JMPN" or nxt.target_ip != 0x06A0:
        raise AssertionError("0312 is not MOV BX,0492 / JMP 06A0")
    cmp_jnz = decode_one(image, cs, 0x030E)
    jnz = decode_one(image, cs, 0x0310)
    if cmp_jnz.bytes_hex != "3ce0" or jnz.kind != "JCC" or jnz.target_ip != 0x0315:
        raise AssertionError("0492 store is not the CMP AL,0xE0 fallthrough")
    reached_imm: set[int] = set()
    for ip in seen:
        insn = decode_one(image, cs, ip)
        if not insn.bytes_hex.startswith("bb") or insn.length != 3:
            continue
        follow = decode_one(image, cs, (ip + 3) & 0xFFFF)
        if follow.kind == "JMPN" and follow.target_ip == 0x06A0:
            reached_imm.add(int(insn.bytes_hex[2:4], 16) | (int(insn.bytes_hex[4:6], 16) << 8))
    if reached_imm != {int(x, 16) for x in state["reached_bx"]}:
        raise AssertionError(f"reached [7626] immediates {sorted(reached_imm)}")
    if edges.get(0x0492):
        raise AssertionError("direct near edge into D52A:0492")
    if 0x04A2 in seen or 0x0318 in seen:
        raise AssertionError("walk entered past the 0492 JMP or into 0318")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D52A:0492 body")
    _expect_hex(image, int(state["caller_dx_file"], 16), state["caller_dx_bytes"], "MOV DX,0x00D0 / CALL 02D5")
    body, hit = follow_local(image, cs, 0x0492)
    jmp_out = next((insn for insn in body if insn.ip == 0x049F), None)
    if hit or body[-1].kind != "RET" or body[-1].ip != 0x06A4:
        raise AssertionError("0492 body does not end at the 06A0 RET")
    if jmp_out is None or jmp_out.kind != "JMPN" or jmp_out.target_ip != 0x06A0:
        raise AssertionError("0492 does not JMP 06A0")
    if any(insn.bytes_hex.startswith("0fe0") or insn.bytes_hex.startswith("0ff0") for insn in body):
        raise AssertionError("0492 body contains BRKXA/RETXA")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D52A:0492 body is not the owned seed")

    state = pin["state_051f"]
    if 0x071A not in seen or 0x06ED not in seen or 0x051F not in seen:
        raise AssertionError("051F writer, JMP BX, or body is not in the owned walk")
    if 0x0328 in seen or 0x054D in seen:
        raise AssertionError("walk entered 0328 or the byte after the 051F JMP")
    _expect_hex(image, int(state["writer_file"], 16), state["writer_bytes"], "MOV BX,051F store [SI+762E]")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX [SI+762E]")
    _expect_hex(image, int(state["rom_word_file"], 16), state["rom_word_bytes"], "ROM word [762E]")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D52A:051F through JMP 064C")
    _expect_hex(image, int(state["jcc_file"], 16), state["jcc_bytes"], "D52A:0567 JMP 064C")
    _expect_hex(image, int(state["join_file"], 16), state["join_bytes"], "D52A:064C through JMP 06A0")
    phys20 = (cs << 4) + 0x051F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D52A:051F file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D52A:051F 24-bit 0x{phys24:06X}")
    body, hit = follow_local(image, cs, 0x051F)
    if hit or any(insn.ip in (0x0318, 0x0328, 0x04A2) for insn in body):
        raise AssertionError("051F body entered 0318, 0328, 04A2, or the walk limit")
    exit_insn = next((insn for insn in body if insn.ip == 0x065F), None)
    if exit_insn is None or exit_insn.kind != "JMPS" or exit_insn.target_ip != 0x06A0:
        raise AssertionError("051F does not JMP 06A0")
    if body[-1].kind != "RET" or body[-1].ip != 0x06A4:
        raise AssertionError("051F follow does not end at the 06A0 RET")
    if any(insn.bytes_hex.startswith("0fe0") or insn.bytes_hex.startswith("0ff0") for insn in body):
        raise AssertionError("051F body contains BRKXA/RETXA")
    want = {
        (int(state["body_file"], 16), int(state["body_end"], 16)),
        (int(state["jcc_file"], 16), int(state["jcc_end"], 16)),
        (int(state["join_file"], 16), int(state["join_end"], 16)),
    }
    got = {
        (start, end)
        for start, end, owner, _kind in ledger_spans(load_ledger())
        if owner == "code" and (start, end) in want
    }
    if got != want:
        raise AssertionError("D52A:051F body is not the owned seed")


def _check_d547_0663(image: bytes, pin: dict) -> None:
    """Slot 2 stores 0663; JMP BX that reads it runs with CS D547."""
    state = pin["state_0663"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x0663
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:0663 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:0663 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["call_file"], 16), state["call_bytes"], "D547:0097 CALL 04D5")
    _expect_hex(image, int(state["jmp_file"], 16), state["jmp_bytes"], "JMP CS:[DI+0561]")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "slot 2 word 05A5")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,0663 / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / JMP BX")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:0663 through JMP 0907")
    call = decode_one(image, cs, 0x0097)
    if call.kind != "CALLN" or call.target_ip != 0x04D5:
        raise AssertionError("0097 is not CALL D547:04D5")
    entry, entry_hit = follow_local(image, cs, 0x0067)
    if entry_hit or not any(insn.ip == 0x0097 and insn.target_ip == 0x04D5 for insn in entry):
        raise AssertionError("IVT D547:0067 does not call 04D5")
    reached, hit = follow_local(image, cs, 0x04D5)
    if hit:
        raise AssertionError("04D5 walk hit the limit")
    ips = {insn.ip: insn for insn in reached}
    jmp = ips.get(0x055C)
    reader = ips.get(0x051D)
    if jmp is None or jmp.bytes_hex != state["jmp_bytes"]:
        raise AssertionError("04D5 walk does not reach JMP CS:[DI+0561]")
    if reader is None or reader.kind != "JMPN_RM" or reader.bytes_hex != "ffe3":
        raise AssertionError("04D5 walk does not reach JMP BX")
    if reader.file != int(state["reader_file"], 16) + 6:
        raise AssertionError("JMP BX file is not 0x5598D")
    slot = follow_local(image, cs, 0x05A5)
    slot_insns, slot_hit = slot
    if slot_hit or slot_insns[0].bytes_hex != "bb6306" or slot_insns[1].kind != "JMPN":
        raise AssertionError("05A5 is not MOV BX,0663 / JMP 0907")
    if slot_insns[1].target_ip != 0x0907 or slot_insns[-1].kind != "RET":
        raise AssertionError("05A5 does not store [SI+762E] and RET")
    body, body_hit = follow_local(image, cs, 0x0663)
    if body_hit:
        raise AssertionError("0663 walk hit the limit")
    head = [insn for insn in body if insn.ip < 0x0907]
    if [insn.ip for insn in head] != [0x0663, 0x0667, 0x066A]:
        raise AssertionError("0663 body is not the three-instruction straight line")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("0663 does not JMP 0907")
    if any(insn.bytes_hex.startswith("0fe0") or insn.bytes_hex.startswith("0ff0") for insn in head):
        raise AssertionError("0663 body contains BRKXA/RETXA")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("0663 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
        if start <= int(state["store_file"], 16) < end and owner != "code":
            raise AssertionError("0907 store is not owned code")
    if not owned:
        raise AssertionError("D547:0663 body is not the owned seed")


def _gap_at(file_off: int) -> bool:
    for start, end, _owner, _kind in ledger_spans(load_ledger()):
        if start <= file_off < end:
            return False
    return True


def _check_d547_066d(image: bytes, pin: dict) -> None:
    """0663 stores 066D; the reached JMP BX reads [SI+762E] with CS D547."""
    state = pin["state_066d"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x066D
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:066D file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:066D 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,066D / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / JMP BX")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:066D through JMP 06A7")
    _expect_hex(image, int(state["join_file"], 16), state["join_bytes"], "D547:06A7 through JMP 0907")
    _expect_hex(image, int(state["exit_file"], 16), state["exit_bytes"], "MOV BX,051F / JMP 0907")
    _expect_hex(image, int(state["skip_file"], 16), state["skip_bytes"], "unreached sled at 0693")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:051F gap head")
    mov = decode_one(image, cs, 0x0667)
    jmp = decode_one(image, cs, 0x066A)
    if mov.bytes_hex != "bb6d06" or jmp.kind != "JMPN" or jmp.target_ip != 0x0907:
        raise AssertionError("0667 is not MOV BX,066D / JMP 0907")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6":
        raise AssertionError("0907 is not SHL SI,1")
    if decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0909 is not MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    if decode_one(image, cs, 0x0517).bytes_hex != "8b9c2e76":
        raise AssertionError("0517 is not MOV BX,[SI+762E]")
    if decode_one(image, cs, 0x051D).kind != "JMPN_RM" or decode_one(image, cs, 0x051D).bytes_hex != "ffe3":
        raise AssertionError("051D is not JMP BX")
    prior, prior_hit = follow_local(image, cs, 0x0663, limit=16)
    if prior_hit:
        raise AssertionError("0663 walk hit the limit")
    prior_ips = {insn.ip: insn for insn in prior}
    if prior_ips[0x0667].bytes_hex != "bb6d06" or prior_ips[0x066A].target_ip != 0x0907:
        raise AssertionError("reached 0663 does not store BX=066D")
    if prior_ips[0x090D].kind != "RET":
        raise AssertionError("0663 store path does not RET")
    body, hit = follow_local(image, cs, 0x066D, limit=40)
    if hit:
        raise AssertionError("066D walk hit the limit")
    if any(insn.ip == 0x0693 for insn in body):
        raise AssertionError("066D walk entered the short-jump sled")
    if any(insn.file == 0x5A090 for insn in body):
        raise AssertionError("066D walk entered CALLF DA09:0000")
    if any(insn.bytes_hex.startswith("0fe0") or insn.bytes_hex.startswith("0ff0") for insn in body):
        raise AssertionError("066D body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.ip < 0x0907]
    covered: list[tuple[int, int]] = []
    for insn in sorted(head, key=lambda item: item.file):
        start, end = insn.file, insn.file + insn.length
        if covered and start == covered[-1][1]:
            covered[-1] = (covered[-1][0], end)
        else:
            if covered and start < covered[-1][1]:
                raise AssertionError("066D instructions overlap")
            covered.append((start, end))
    want_ranges = [
        (int(state["body_file"], 16), int(state["body_end"], 16)),
        (int(state["join_file"], 16), int(state["join_end"], 16)),
    ]
    if covered != want_ranges:
        raise AssertionError(f"066D coverage {covered}")
    exit_insn = next(insn for insn in body if insn.ip == 0x06D0)
    if exit_insn.kind != "JMPN" or exit_insn.target_ip != 0x0907:
        raise AssertionError("066D does not JMP 0907")
    if next(insn for insn in body if insn.ip == 0x06CD).bytes_hex != "bb1f05":
        raise AssertionError("066D exit is not MOV BX,051F")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("066D follow does not end at the 0907 RET")
    want = set(want_ranges)
    got = {
        (start, end)
        for start, end, owner, _kind in ledger_spans(load_ledger())
        if owner == "code" and (start, end) in want
    }
    if got != want:
        raise AssertionError("D547:066D body is not the owned seed")
    if not _gap_at(int(state["skip_file"], 16)):
        raise AssertionError("short-jump sled at 0693 is owned")


def _check_d547_051f(image: bytes, pin: dict) -> None:
    """06CD stores 051F where D547:051D JMP BX reads it. FF E3 does not fall through."""
    state = pin["state_d547_051f"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x051F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:051F file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:051F 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:051F through JMP 0907")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,051F / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / JMP BX")
    _expect_hex(image, int(state["si0_file"], 16), state["si0_bytes"], "MOV SI,0")
    _expect_hex(image, int(state["si2_file"], 16), state["si2_bytes"], "MOV SI,2")
    _expect_hex(image, int(state["jz_file"], 16), state["jz_bytes"], "JZ 0517")
    _expect_hex(image, int(state["slot3_file"], 16), state["slot3_bytes"], "slot 3 word 05AB")
    _expect_hex(image, int(state["writer_0694_file"], 16), state["writer_0694_bytes"], "MOV BX,0694 / JMP 0907")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0694 gap head")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    if decode_one(image, cs, 0x0091).bytes_hex != "be0000":
        raise AssertionError("0091 is not MOV SI,0")
    if decode_one(image, cs, 0x0097).target_ip != 0x04D5:
        raise AssertionError("MOV SI,0 is not followed by CALL 04D5")
    if decode_one(image, cs, 0x00A7).bytes_hex != "be0200":
        raise AssertionError("00A7 is not MOV SI,2")
    if decode_one(image, cs, 0x00AA).target_ip != 0x04D5:
        raise AssertionError("MOV SI,2 is not followed by CALL 04D5")
    if decode_one(image, cs, 0x04D5).bytes_hex != "ec" or decode_one(image, cs, 0x04D6).bytes_hex != "a880":
        raise AssertionError("04D5 is not IN AL,DX / TEST AL,0x80")
    jz = decode_one(image, cs, 0x04D8)
    if jz.kind != "JCC" or jz.target_ip != 0x0517:
        raise AssertionError("04D8 does not JZ to the [SI+762E] reader")
    if decode_one(image, cs, 0x0517).bytes_hex != "8b9c2e76":
        raise AssertionError("0517 is not MOV BX,[SI+762E]")
    jmp_bx = decode_one(image, cs, 0x051D)
    if jmp_bx.kind != "JMPN_RM" or jmp_bx.bytes_hex != "ffe3":
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x051B).bytes_hex != "d1ee":
        raise AssertionError("051B is not SHR SI,1")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    mov = decode_one(image, cs, 0x06CD)
    jmp = decode_one(image, cs, 0x06D0)
    if mov.bytes_hex != "bb1f05" or jmp.kind != "JMPN" or jmp.target_ip != 0x0907:
        raise AssertionError("06CD is not MOV BX,051F / JMP 0907")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if any(insn.ip == 0x051F for insn in dispatch):
        raise AssertionError("JMP BX fall-through entered D547:051F")
    if not any(insn.ip == 0x051D and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP BX")
    prior, prior_hit = follow_local(image, cs, 0x066D, limit=40)
    if prior_hit:
        raise AssertionError("066D walk hit the limit")
    if any(insn.file == 0x5A090 for insn in prior):
        raise AssertionError("066D walk entered CALLF DA09:0000")
    if not any(insn.ip < 0x06B6 and insn.kind == "JCC" and insn.target_ip == 0x06CD for insn in prior):
        raise AssertionError("066D has no edge to the 051F store before CALLF")
    for insn in prior:
        if insn.ip >= 0x06B6:
            continue
        if insn.bytes_hex[:4] in ("d1e6", "d1ee") or insn.bytes_hex.startswith(("be", "8bf")):
            raise AssertionError("066D changes SI before the 051F store")
    if not any(insn.ip == 0x06CD and insn.bytes_hex == "bb1f05" for insn in prior):
        raise AssertionError("066D walk does not store BX=051F")
    body, hit = follow_local(image, cs, 0x051F, limit=16)
    if hit:
        raise AssertionError("051F walk hit the limit")
    if any(insn.ip == 0x0693 or insn.file == 0x55B03 for insn in body):
        raise AssertionError("051F walk entered the short-jump sled")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("051F body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x051F, 0x0521, 0x0523]:
        raise AssertionError("051F body is not TEST / JNZ 0526 / JMP 0907")
    if head[1].kind != "JCC" or head[1].target_ip != 0x0526:
        raise AssertionError("051F does not JNZ to owned 0526")
    if head[2].kind != "JMPN" or head[2].target_ip != 0x0907:
        raise AssertionError("051F does not JMP 0907")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("051F follow does not end at the 0907 RET")
    if (head[0].file, head[-1].file + head[-1].length) != (
        int(state["body_file"], 16),
        int(state["body_end"], 16),
    ):
        raise AssertionError("051F coverage is not the owned seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:051F body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    writer = decode_one(image, cs, 0x05AB)
    writer_jmp = decode_one(image, cs, 0x05AE)
    if writer.bytes_hex != "bb9406" or writer_jmp.kind != "JMPN" or writer_jmp.target_ip != 0x0907:
        raise AssertionError("slot 3 is not MOV BX,0694 / JMP 0907")


def _check_d547_0694(image: bytes, pin: dict) -> None:
    """AL=0xF3 reaches slot 7, which falls into slot 3. That stores 0694 for JMP BX."""
    state = pin["state_0694"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x0694
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:0694 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:0694 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:0694 through fall into 06A7")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,0694 / JMP 0907")
    _expect_hex(image, int(state["slot3_file"], 16), state["slot3_bytes"], "slot 3 word 05AB")
    _expect_hex(image, int(state["slot7_file"], 16), state["slot7_bytes"], "BX-table slot 7 word 054A")
    _expect_hex(image, int(state["fall_file"], 16), state["fall_bytes"], "054A store 051F then fall into 0555")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:06D3 gap head")
    _expect_hex(image, int(state["writer_06d3_file"], 16), state["writer_06d3_bytes"], "MOV BX,06D3 / JMP 0907")
    _expect_hex(image, int(state["slot4_file"], 16), state["slot4_bytes"], "BX-table slot 4 word 05E7")
    if decode_one(image, cs, 0x04D6).bytes_hex != "a880":
        raise AssertionError("04D6 is not TEST AL,0x80")
    if decode_one(image, cs, 0x04D8).target_ip != 0x0517:
        raise AssertionError("bit 7 clear does not go to the reader")
    if decode_one(image, cs, 0x04DA).bytes_hex != "3cf8":
        raise AssertionError("04DA is not CMP AL,0xF8")
    jb = decode_one(image, cs, 0x04DC)
    if jb.kind != "JCC" or jb.target_ip != 0x04E1:
        raise AssertionError("AL < 0xF8 does not go to 04E1")
    if decode_one(image, cs, 0x04E1).bytes_hex != "d1ee":
        raise AssertionError("04E1 is not SHR SI,1")
    jz = decode_one(image, cs, 0x04E9)
    if jz.kind != "JCC" or jz.target_ip != 0x0502:
        raise AssertionError("CL==0 does not skip CALL 090E")
    if decode_one(image, cs, 0x0502).bytes_hex != "d1e6" or decode_one(image, cs, 0x0508).bytes_hex != "d1ee":
        raise AssertionError("CL==0 edge does not SHL then SHR SI")
    if decode_one(image, cs, 0x050E).target_ip != 0x0526 or decode_one(image, cs, 0x0514).target_ip != 0x0526:
        raise AssertionError("CL==0 edge does not reach 0526")
    if decode_one(image, cs, 0x0526).bytes_hex != "8ad8" or decode_one(image, cs, 0x0528).bytes_hex != "80e3f0":
        raise AssertionError("0526 is not MOV BL,AL / AND BL,0xF0")
    if decode_one(image, cs, 0x052F).bytes_hex != "c0eb03" or decode_one(image, cs, 0x0532).bytes_hex != "83e30e":
        raise AssertionError("052F is not SHR BL,3 / AND BL,0x0E")
    jmp_bx_tab = decode_one(image, cs, 0x0535)
    if jmp_bx_tab.kind != "JMPN_RM" or jmp_bx_tab.bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x0555).bytes_hex != "8bf8" or decode_one(image, cs, 0x0557).bytes_hex != "83e70f":
        raise AssertionError("0555 is not MOV DI,AX / AND DI,0x0F")
    if decode_one(image, cs, 0x055A).bytes_hex != "d1e7":
        raise AssertionError("055A is not SHL DI,1")
    jmp_di = decode_one(image, cs, 0x055C)
    if jmp_di.kind != "JMPN_RM" or jmp_di.bytes_hex != "2effa56105":
        raise AssertionError("055C is not JMP CS:[DI+0561]")
    al = 0xF3
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xF3 is not on the 04E1 path")
    bx_off = ((al & 0xF0) >> 3) & 0x0E
    if _u16(image, 0x559AA + bx_off) != 0x054A:
        raise AssertionError("AL=0xF3 does not select BX-table slot 054A")
    if _u16(image, 0x559D1 + ((al & 0x0F) << 1)) != 0x05AB:
        raise AssertionError("AL=0xF3 does not select DI-table slot 05AB")
    if decode_one(image, cs, 0x0517).bytes_hex != "8b9c2e76" or decode_one(image, cs, 0x051D).bytes_hex != "ffe3":
        raise AssertionError("reader is not MOV BX,[SI+762E] / JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if not any(insn.ip == 0x055C and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[DI+0561]")
    if any(insn.ip in (0x05AB, 0x0694) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 05AB or 0694")
    fall, fall_hit = follow_local(image, cs, 0x054A, limit=16)
    if fall_hit:
        raise AssertionError("054A walk hit the limit")
    if [insn.ip for insn in fall] != [0x054A, 0x054D, 0x054F, 0x0553, 0x0555, 0x0557, 0x055A, 0x055C]:
        raise AssertionError("054A does not fall into JMP CS:[DI+0561]")
    if any(insn.ip == 0x05AB for insn in fall):
        raise AssertionError("054A walk entered 05AB by fall-through")
    slot, slot_hit = follow_local(image, cs, 0x05AB, limit=8)
    if slot_hit:
        raise AssertionError("05AB walk hit the limit")
    if [insn.ip for insn in slot] != [0x05AB, 0x05AE, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("05AB is not MOV BX,0694 / JMP 0907 / store / RET")
    if slot[0].bytes_hex != "bb9406" or slot[1].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("05AB does not store BX=0694")
    body, hit = follow_local(image, cs, 0x0694, limit=40)
    if hit:
        raise AssertionError("0694 walk hit the limit")
    if any(insn.file == 0x55B03 or insn.ip == 0x0693 for insn in body):
        raise AssertionError("0694 walk entered the NOP at 0693")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0694 body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x0694, 0x0699, 0x069B, 0x06A0, 0x06A2, 0x06A5]:
        raise AssertionError("0694 body is not the six instructions before 06A7")
    if head[1].kind != "JCC" or head[1].target_ip != 0x06CD:
        raise AssertionError("0699 does not JNZ to owned 06CD")
    if head[3].kind != "JCC" or head[3].target_ip != 0x06CD:
        raise AssertionError("06A0 does not JZ to owned 06CD")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("0694 does not fall into owned 06A7")
    if not any(insn.ip == 0x06A7 for insn in body):
        raise AssertionError("0694 walk does not enter owned 06A7")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("0694 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:0694 body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    writer = decode_one(image, cs, 0x05F1)
    writer_jmp = decode_one(image, cs, 0x05F4)
    if writer.bytes_hex != "bbd306" or writer_jmp.kind != "JMPN" or writer_jmp.target_ip != 0x0907:
        raise AssertionError("05F1 is not MOV BX,06D3 / JMP 0907")


def _check_d547_06d3(image: bytes, pin: dict) -> None:
    """High nibble 0xC selects BX slot 4. The JZ fall-through stores 06D3 for JMP BX."""
    state = pin["state_06d3"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x06D3
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:06D3 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:06D3 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:06D3 through JMP 0900")
    _expect_hex(image, int(state["slot4_file"], 16), state["slot4_bytes"], "BX-table slot 4 word 05E7")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "05E7 through JMP 0907")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,06D3 / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / JMP BX")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned JMP 0900 target")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:06DD gap head")
    _expect_hex(image, int(state["writer_06dd_file"], 16), state["writer_06dd_bytes"], "MOV BX,06DD / JMP 0907")
    _expect_hex(image, int(state["slot1_file"], 16), state["slot1_bytes"], "BX-table slot 1 word 05D7")
    al = 0xC0
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xC0 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 8 or _u16(image, 0x559AA + 8) != 0x05E7:
        raise AssertionError("AL high nibble 0xC does not select BX-table slot 05E7")
    if (((0x40 & 0xF0) >> 3) & 0x0E) != 8 or (0x40 & 0x80) != 0:
        raise AssertionError("high nibble 4 does not share the slot index off the writer path")
    if decode_one(image, cs, 0x0535).bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3":
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    jz = decode_one(image, cs, 0x05EF)
    if jz.kind != "JCC" or jz.target_ip != 0x05F4:
        raise AssertionError("05EF does not JZ over MOV BX,06D3")
    if decode_one(image, cs, 0x05E7).bytes_hex != "bb1f05" or decode_one(image, cs, 0x05F1).bytes_hex != "bbd306":
        raise AssertionError("05E7 is not MOV BX,051F then MOV BX,06D3")
    if decode_one(image, cs, 0x05F4).kind != "JMPN" or decode_one(image, cs, 0x05F4).target_ip != 0x0907:
        raise AssertionError("05F4 does not JMP 0907")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if any(insn.ip in (0x05E7, 0x05F1, 0x06D3) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 05E7 or 06D3")
    slot, slot_hit = follow_local(image, cs, 0x05E7, limit=12)
    if slot_hit:
        raise AssertionError("05E7 walk hit the limit")
    if [insn.ip for insn in slot] != [0x05E7, 0x05EA, 0x05EF, 0x05F1, 0x05F4, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("05E7 is not MOV BX,06D3 / JMP 0907 / store / RET")
    if slot[3].bytes_hex != "bbd306" or slot[4].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("05E7 does not store BX=06D3")
    if any(insn.ip == 0x06D3 for insn in slot):
        raise AssertionError("05E7 walk entered 06D3")
    body, hit = follow_local(image, cs, 0x06D3, limit=16)
    if hit:
        raise AssertionError("06D3 walk hit the limit")
    if any(insn.file == 0x55B03 or insn.ip == 0x0693 for insn in body):
        raise AssertionError("06D3 walk entered the NOP at 0693")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("06D3 body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x06D3, 0x06D7, 0x06DA]:
        raise AssertionError("06D3 body is not MOV [SI+7634],AL / MOV CX,2 / JMP 0900")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0900:
        raise AssertionError("06DA does not JMP to owned 0900")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("06D3 body does not end at the JMP")
    if decode_one(image, cs, 0x0900).file != int(state["jmp_target_file"], 16):
        raise AssertionError("0900 is not the owned target")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("06D3 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:06D3 body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    writer = decode_one(image, cs, 0x05E1)
    writer_jmp = decode_one(image, cs, 0x05E4)
    if writer.bytes_hex != "bbdd06" or writer_jmp.kind != "JMPN" or writer_jmp.target_ip != 0x0907:
        raise AssertionError("05E1 is not MOV BX,06DD / JMP 0907")


def _check_d547_06dd(image: bytes, pin: dict) -> None:
    """High nibble 9 selects BX slot 1. The JZ fall-through stores 06DD for JMP BX."""
    state = pin["state_06dd"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x06DD
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:06DD file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:06DD 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x06EC
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:06EC file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:06EC 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:06DD through JMP 0907")
    _expect_hex(image, int(state["slot1_file"], 16), state["slot1_bytes"], "BX-table slot 1 word 05D7")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "05D7 through JMP 0907")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,06DD / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:06EC gap head")
    _expect_hex(image, int(state["writer_06ec_file"], 16), state["writer_06ec_bytes"], "MOV BX,06EC / JMP 0907")
    al = 0x90
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0x90 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 2 or _u16(image, 0x559AA + 2) != 0x05D7:
        raise AssertionError("AL high nibble 9 does not select BX-table slot 05D7")
    if ((0x9F & 0xF0) >> 3) & 0x0E != 2:
        raise AssertionError("AL=0x9F does not share slot 1")
    if (((0x10 & 0xF0) >> 3) & 0x0E) != 2 or (0x10 & 0x80) != 0:
        raise AssertionError("high nibble 1 does not share the slot index off the writer path")
    if decode_one(image, cs, 0x04D8).target_ip != 0x0517:
        raise AssertionError("bit 7 clear does not go to the reader")
    if decode_one(image, cs, 0x0535).bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3" or decode_one(image, cs, 0x051D).file != 0x5598D:
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    jz = decode_one(image, cs, 0x05DF)
    if jz.kind != "JCC" or jz.target_ip != 0x05E4:
        raise AssertionError("05DF does not JZ over MOV BX,06DD")
    if decode_one(image, cs, 0x05D7).bytes_hex != "bb1f05" or decode_one(image, cs, 0x05DA).bytes_hex != "f606d78101":
        raise AssertionError("05D7 is not MOV BX,051F / TEST [81D7],1")
    if decode_one(image, cs, 0x05E1).bytes_hex != "bbdd06":
        raise AssertionError("05E1 is not MOV BX,06DD")
    if decode_one(image, cs, 0x05E4).kind != "JMPN" or decode_one(image, cs, 0x05E4).target_ip != 0x0907:
        raise AssertionError("05E4 does not JMP 0907")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if any(insn.ip in (0x05D7, 0x05E1, 0x06DD) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 05D7 or 06DD")
    slot, slot_hit = follow_local(image, cs, 0x05D7, limit=12)
    if slot_hit:
        raise AssertionError("05D7 walk hit the limit")
    if [insn.ip for insn in slot] != [0x05D7, 0x05DA, 0x05DF, 0x05E1, 0x05E4, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("05D7 is not MOV BX,06DD / JMP 0907 / store / RET")
    if slot[3].bytes_hex != "bbdd06" or slot[4].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("05D7 does not store BX=06DD")
    if any(insn.ip == 0x06DD for insn in slot):
        raise AssertionError("05D7 walk entered 06DD")
    body, hit = follow_local(image, cs, 0x06DD, limit=16)
    if hit:
        raise AssertionError("06DD walk hit the limit")
    if any(insn.file == 0x55B03 or insn.ip == 0x0693 for insn in body):
        raise AssertionError("06DD walk entered the NOP at 0693")
    if any(insn.ip == 0x06EC or insn.file == int(state["next_file"], 16) for insn in body):
        raise AssertionError("06DD walk entered 06EC")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("06DD body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x06DD, 0x06E2, 0x06E6, 0x06E9]:
        raise AssertionError("06DD body is not OR [SI+7632],0x90 / MOV [SI+7634],AL / MOV BX,06EC / JMP 0907")
    if head[0].bytes_hex != "808c327690" or head[2].bytes_hex != "bbec06":
        raise AssertionError("06DD does not OR [SI+7632],0x90 then MOV BX,06EC")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("06E9 does not JMP to owned 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("06DD body does not end at the JMP")
    if decode_one(image, cs, 0x0907).file != int(state["store_file"], 16):
        raise AssertionError("0907 is not the owned store")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("06DD follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:06DD body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")


def _check_d547_06ec(image: bytes, pin: dict) -> None:
    """High nibble 9 and [81D7] bit 0 set reach 06DD, which stores 06EC for JMP BX."""
    state = pin["state_06ec"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x06EC
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:06EC file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:06EC 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x071C
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:071C file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:071C 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:06EC through JMP short 0716")
    _expect_hex(image, int(state["join_file"], 16), state["join_bytes"], "D547:0709 through JMP 0900")
    _expect_hex(image, int(state["writer_file"], 16), state["writer_bytes"], "MOV BX,06EC / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned JMP 0900 target")
    _expect_hex(image, int(state["push_bx_file"], 16), state["push_bx_bytes"], "090E PUSH BX")
    _expect_hex(image, int(state["pop_bx_file"], 16), state["pop_bx_bytes"], "090E POP BX / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:071C gap head")
    _expect_hex(image, int(state["writer_071c_file"], 16), state["writer_071c_bytes"], "MOV BX,071C / JMP 0907")
    al = 0x90
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0x90 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 2 or _u16(image, 0x559AA + 2) != 0x05D7:
        raise AssertionError("AL high nibble 9 does not select BX-table slot 05D7")
    if decode_one(image, cs, 0x05DF).kind != "JCC" or decode_one(image, cs, 0x05DF).target_ip != 0x05E4:
        raise AssertionError("05DF does not JZ over MOV BX,06DD")
    if decode_one(image, cs, 0x05E1).bytes_hex != "bbdd06":
        raise AssertionError("05E1 is not MOV BX,06DD")
    if decode_one(image, cs, 0x06E6).bytes_hex != "bbec06" or decode_one(image, cs, 0x06E6).file != 0x55B56:
        raise AssertionError("06DD body does not MOV BX,06EC")
    if decode_one(image, cs, 0x06E9).kind != "JMPN" or decode_one(image, cs, 0x06E9).target_ip != 0x0907:
        raise AssertionError("06E9 does not JMP 0907")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3" or decode_one(image, cs, 0x051D).file != 0x5598D:
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    callee, callee_hit = follow_local(image, cs, 0x090E, limit=20)
    if callee_hit or [insn.bytes_hex for insn in callee[:2]] != ["8dbc3276", "53"]:
        raise AssertionError("090E does not start LEA DI,[SI+7632] / PUSH BX")
    if callee[-2].bytes_hex != "5b" or callee[-1].kind != "RET" or callee[-1].ip != 0x0932:
        raise AssertionError("090E does not POP BX and RET")
    if any(insn.kind == "RET" and insn.ip != 0x0932 for insn in callee):
        raise AssertionError("090E has another RET")
    body, hit = follow_local(image, cs, 0x06EC, limit=24)
    if hit:
        raise AssertionError("06EC walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708, 0x06DD) for insn in body):
        raise AssertionError("06EC walk entered an unreached NOP or 06DD")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("06EC body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["join_end"], 16)]
    if [insn.ip for insn in head] != [
        0x06EC, 0x06EE, 0x06F0, 0x06F5, 0x06F7, 0x06FA, 0x06FE, 0x0703, 0x0706,
        0x0709, 0x070E, 0x0713, 0x0716, 0x0719,
    ]:
        raise AssertionError("06EC body is not the reached instructions through JMP 0900")
    if head[1].kind != "JCC" or head[1].target_ip != 0x0709:
        raise AssertionError("06EE does not JZ to 0709")
    if head[3].kind != "JCC" or head[3].target_ip != 0x06FA:
        raise AssertionError("06F5 does not JZ over MOV AL,[836C]")
    if head[8].kind != "JMPS" or head[8].target_ip != 0x0716:
        raise AssertionError("0706 does not JMP short 0716")
    if head[12].bytes_hex != "bbdd06" or head[13].kind != "JMPN" or head[13].target_ip != 0x0900:
        raise AssertionError("0716 is not MOV BX,06DD / JMP 0900")
    if head[8].file + head[8].length != int(state["body_end"], 16):
        raise AssertionError("06EC straight line does not end at the short JMP")
    if head[-1].file + head[-1].length != int(state["join_end"], 16):
        raise AssertionError("06EC join does not end at JMP 0900")
    if decode_one(image, cs, 0x0900).file != int(state["jmp_target_file"], 16):
        raise AssertionError("0900 is not the owned target")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("06EC follow does not end at the 0907 RET")
    want = {
        (int(state["body_file"], 16), int(state["body_end"], 16)),
        (int(state["join_file"], 16), int(state["join_end"], 16)),
    }
    got = {
        (start, end)
        for start, end, owner, _kind in ledger_spans(load_ledger())
        if owner == "code" and (start, end) in want
    }
    if got != want:
        raise AssertionError("D547:06EC body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    if not _gap_at(int(state["nop_file"], 16)):
        raise AssertionError("NOP at 0708 is owned")
    al = 0x80
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0x80 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 0 or _u16(image, 0x559AA) != 0x061D:
        raise AssertionError("AL high nibble 8 does not select BX-table slot 061D")
    if ((0x8F & 0xF0) >> 3) & 0x0E != 0:
        raise AssertionError("AL=0x8F does not share slot 0")
    if decode_one(image, cs, 0x0625).kind != "JCC" or decode_one(image, cs, 0x0625).target_ip != 0x062A:
        raise AssertionError("0625 does not JZ over MOV BX,071C")
    if decode_one(image, cs, 0x0627).bytes_hex != "bb1c07" or decode_one(image, cs, 0x0627).file != 0x55A97:
        raise AssertionError("0627 is not MOV BX,071C")
    if decode_one(image, cs, 0x062A).kind != "JMPN" or decode_one(image, cs, 0x062A).target_ip != 0x0907:
        raise AssertionError("062A does not JMP 0907")


def _check_d547_071c(image: bytes, pin: dict) -> None:
    """High nibble 8 selects BX slot 0. [81D7] bit 0 set stores 071C for JMP BX."""
    state = pin["state_071c"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x071C
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:071C file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:071C 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x0726
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:0726 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:0726 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:071C through JMP 0907")
    _expect_hex(image, int(state["slot0_file"], 16), state["slot0_bytes"], "BX-table slot 0 word 061D")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "061D through JMP 0907")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,071C / JMP 0907")
    _expect_hex(image, int(state["index_file"], 16), state["index_bytes"], "high-nibble index into BX table")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0726 gap head")
    _expect_hex(image, int(state["writer_0726_file"], 16), state["writer_0726_bytes"], "MOV BX,0726 / JMP 0907")
    al = 0x80
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0x80 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 0 or _u16(image, 0x559AA) != 0x061D:
        raise AssertionError("AL high nibble 8 does not select BX-table slot 061D")
    if ((0x8F & 0xF0) >> 3) & 0x0E != 0:
        raise AssertionError("AL=0x8F does not share slot 0")
    if decode_one(image, cs, 0x04D8).target_ip != 0x0517:
        raise AssertionError("bit 7 clear does not go to the reader")
    if decode_one(image, cs, 0x0535).bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3" or decode_one(image, cs, 0x051D).file != 0x5598D:
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    jz = decode_one(image, cs, 0x0625)
    if jz.kind != "JCC" or jz.target_ip != 0x062A:
        raise AssertionError("0625 does not JZ over MOV BX,071C")
    if decode_one(image, cs, 0x061D).bytes_hex != "bb1f05" or decode_one(image, cs, 0x0620).bytes_hex != "f606d78101":
        raise AssertionError("061D is not MOV BX,051F / TEST [81D7],1")
    if decode_one(image, cs, 0x0627).bytes_hex != "bb1c07" or decode_one(image, cs, 0x0627).file != 0x55A97:
        raise AssertionError("0627 is not MOV BX,071C")
    if decode_one(image, cs, 0x062A).kind != "JMPN" or decode_one(image, cs, 0x062A).target_ip != 0x0907:
        raise AssertionError("062A does not JMP 0907")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0526 for insn in dispatch):
        raise AssertionError("04D5 walk does not reach the high-nibble index")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if not any(insn.ip == 0x051D and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP BX")
    if any(insn.ip in (0x061D, 0x0627, 0x071C) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 061D or 071C")
    slot, slot_hit = follow_local(image, cs, 0x061D, limit=12)
    if slot_hit:
        raise AssertionError("061D walk hit the limit")
    if [insn.ip for insn in slot] != [0x061D, 0x0620, 0x0625, 0x0627, 0x062A, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("061D is not MOV BX,071C / JMP 0907 / store / RET")
    if slot[3].bytes_hex != "bb1c07" or slot[4].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("061D does not store BX=071C")
    if any(insn.ip == 0x071C for insn in slot):
        raise AssertionError("061D walk entered 071C")
    body, hit = follow_local(image, cs, 0x071C, limit=12)
    if hit:
        raise AssertionError("071C walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708, 0x0726) for insn in body):
        raise AssertionError("071C walk entered an unreached NOP or 0726")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("071C body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x071C, 0x0720, 0x0723]:
        raise AssertionError("071C body is not MOV [SI+7634],AL / MOV BX,0726 / JMP 0907")
    if head[0].bytes_hex != "88843476" or head[1].bytes_hex != "bb2607":
        raise AssertionError("071C does not MOV [SI+7634],AL then MOV BX,0726")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("0723 does not JMP to owned 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("071C body does not end at the JMP")
    if decode_one(image, cs, 0x0907).file != int(state["store_file"], 16):
        raise AssertionError("0907 is not the owned store")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("071C follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:071C body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    if not _gap_at(int(state["nop_file"], 16)):
        raise AssertionError("NOP at 0708 is owned")
    owned_0726 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["next_file"], 16) and owner == "code":
            owned_0726 = True
    if not owned_0726:
        raise AssertionError("D547:0726 is not owned")


def _check_d547_0726(image: bytes, pin: dict) -> None:
    """071C stores 0726 for JMP BX after high nibble 8 and [81D7] bit 0 set reach 071C."""
    state = pin["state_0726"]
    prev = pin["state_071c"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x0726
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:0726 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:0726 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x0733
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:0733 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:0733 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:0726 through JMP 0900")
    _expect_hex(image, int(state["writer_file"], 16), state["writer_bytes"], "MOV BX,0726 / JMP 0907")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned JMP 0900 target")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0733 gap head")
    _expect_hex(image, int(state["writer_0733_file"], 16), state["writer_0733_bytes"], "MOV BX,0733 / JMP 0907")
    if decode_one(image, cs, 0x0720).bytes_hex != "bb2607" or decode_one(image, cs, 0x0720).file != int(prev["body_file"], 16) + 4:
        raise AssertionError("071C does not MOV BX,0726")
    if decode_one(image, cs, 0x0723).kind != "JMPN" or decode_one(image, cs, 0x0723).target_ip != 0x0907:
        raise AssertionError("0723 does not JMP 0907")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3" or decode_one(image, cs, 0x051D).file != 0x5598D:
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    if decode_one(image, cs, 0x0730).kind != "JMPN" or decode_one(image, cs, 0x0730).target_ip != 0x0900:
        raise AssertionError("0730 does not JMP 0900")
    body, hit = follow_local(image, cs, 0x0726, limit=16)
    if hit:
        raise AssertionError("0726 walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708, 0x0733) for insn in body):
        raise AssertionError("0726 walk entered an unreached NOP or 0733")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0726 body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x0726, 0x072A, 0x072D, 0x0730]:
        raise AssertionError("0726 body is not MOV [SI+7636],AL / MOV BX,071C / MOV CX,3 / JMP 0900")
    if head[0].bytes_hex != "88843676" or head[1].bytes_hex != "bb1c07" or head[2].bytes_hex != "b90300":
        raise AssertionError("0726 does not MOV [SI+7636],AL then MOV BX,071C / MOV CX,3")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0900:
        raise AssertionError("0730 does not JMP to owned 0900")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("0726 body does not end at the JMP")
    if decode_one(image, cs, 0x0900).file != int(state["jmp_target_file"], 16):
        raise AssertionError("0900 is not the owned target")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("0726 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:0726 body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    if not _gap_at(int(state["nop_file"], 16)):
        raise AssertionError("NOP at 0708 is owned")
    owned_0733 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["next_file"], 16) and owner == "code":
            owned_0733 = True
    if not owned_0733:
        raise AssertionError("D547:0733 is not owned")


def _check_d547_0733(image: bytes, pin: dict) -> None:
    """High nibble B selects BX slot 3. That stores 0733 for JMP BX."""
    state = pin["state_0733"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x0733
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:0733 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:0733 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x073D
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:073D file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:073D 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:0733 through JMP 0907")
    _expect_hex(image, int(state["slot3_file"], 16), state["slot3_bytes"], "BX-table slot 3 word 05FD")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "05FD MOV BX,0733 / JMP 0907")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,0733 / JMP 0907")
    _expect_hex(image, int(state["index_file"], 16), state["index_bytes"], "high-nibble index into BX table")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:073D gap head")
    _expect_hex(image, int(state["writer_073d_file"], 16), state["writer_073d_bytes"], "MOV BX,073D / JMP 0907")
    al = 0xB0
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xB0 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 6 or _u16(image, 0x559AA + 6) != 0x05FD:
        raise AssertionError("AL high nibble B does not select BX-table slot 05FD")
    if (((0x30 & 0xF0) >> 3) & 0x0E) != 6 or (0x30 & 0x80) != 0:
        raise AssertionError("high nibble 3 shares slot index but is not on the 04E1 path")
    if decode_one(image, cs, 0x0535).bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3":
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if any(insn.ip in (0x05FD, 0x0733) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 05FD or 0733")
    slot, slot_hit = follow_local(image, cs, 0x05FD, limit=8)
    if slot_hit:
        raise AssertionError("05FD walk hit the limit")
    if [insn.ip for insn in slot] != [0x05FD, 0x0600, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("05FD is not MOV BX,0733 / JMP 0907 / store / RET")
    if slot[0].bytes_hex != "bb3307" or slot[1].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("05FD does not store BX=0733")
    if any(insn.ip == 0x0733 for insn in slot):
        raise AssertionError("05FD walk entered 0733")
    body, hit = follow_local(image, cs, 0x0733, limit=16)
    if hit:
        raise AssertionError("0733 walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708, 0x073D) for insn in body):
        raise AssertionError("0733 walk entered an unreached NOP or 073D")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0733 body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x0733, 0x0737, 0x073A]:
        raise AssertionError("0733 body is not MOV [SI+7634],AL / MOV BX,073D / JMP 0907")
    if head[0].bytes_hex != "88843476" or head[1].bytes_hex != "bb3d07":
        raise AssertionError("0733 does not MOV [SI+7634],AL then MOV BX,073D")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("073A does not JMP to owned 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("0733 body does not end at the JMP")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("0733 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:0733 body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    if not _gap_at(int(state["nop_file"], 16)):
        raise AssertionError("NOP at 0708 is owned")
    owned_073d = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["next_file"], 16) and owner == "code":
            owned_073d = True
    if not owned_073d:
        raise AssertionError("D547:073D is not owned")


def _check_d547_073d(image: bytes, pin: dict) -> None:
    """0733 stores 073D for JMP BX when high nibble B reaches slot 3."""
    state = pin["state_073d"]
    prev = pin["state_0733"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x073D
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:073D file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:073D 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x0780
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:0780 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:0780 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:073D through JMP 0900")
    _expect_hex(image, int(prev["writer_073d_file"], 16), prev["writer_073d_bytes"], "MOV BX,073D / JMP 0907")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned JMP 0900 target")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0780 gap head")
    _expect_hex(image, int(state["branch_file"], 16), state["branch_bytes"], "JNZ to 0780")
    if decode_one(image, cs, 0x0900).file != int(state["jmp_target_file"], 16):
        raise AssertionError("0900 is not the owned target")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    body, hit = follow_local(image, cs, 0x073D, limit=64)
    if hit:
        raise AssertionError("073D walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708) for insn in body):
        raise AssertionError("073D walk entered an unreached NOP")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("073D body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if head[0].bytes_hex != "88843676" or head[0].ip != 0x073D:
        raise AssertionError("073D does not begin with MOV [SI+7636],AL")
    if head[-1].kind != "JMPN" or head[-1].target_ip != 0x0900:
        raise AssertionError("077D does not JMP to owned 0900")
    if head[-1].bytes_hex != "e98001" or head[-2].bytes_hex != "b90300" or head[-3].bytes_hex != "bb3307":
        raise AssertionError("0777 is not MOV BX,0733 / MOV CX,3 / JMP 0900")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("073D body does not end at the JMP")
    jcc_0780 = decode_one(image, cs, 0x0759)
    if jcc_0780.kind != "JCC" or jcc_0780.target_ip != 0x0780 or jcc_0780.file != int(state["branch_file"], 16):
        raise AssertionError("0759 does not JNZ to 0780")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("073D follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:073D body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    if not _gap_at(int(state["nop_file"], 16)):
        raise AssertionError("NOP at 0708 is owned")
    owned_0780 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["next_file"], 16) and owner == "code":
            owned_0780 = True
    if not owned_0780:
        raise AssertionError("D547:0780 is not owned")


def _check_d547_0780(image: bytes, pin: dict) -> None:
    """073D fall-through reaches 0759 JNZ when prior JCCs fall through; JNZ targets 0780 if [98DB]!=0."""
    state = pin["state_0780"]
    prev = pin["state_073d"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x0780
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:0780 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:0780 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x07AF
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:07AF file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:07AF 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:0780 through JMP 0907")
    _expect_hex(image, int(prev["branch_file"], 16), prev["branch_bytes"], "073D JNZ to 0780")
    _expect_hex(image, int(state["cmp_file"], 16), state["cmp_bytes"], "CMP [98DB],0 before JNZ")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:073D body")
    _expect_hex(image, int(prev["writer_file"], 16), prev["writer_bytes"], "MOV BX,073D / JMP 0907")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned JMP 0907 target")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:07AF gap head")
    test_8081 = decode_one(image, cs, 0x0747)
    jz_07a9 = decode_one(image, cs, 0x074C)
    cmp_85b5 = decode_one(image, cs, 0x074E)
    jnz_075b = decode_one(image, cs, 0x0752)
    cmp_98db = decode_one(image, cs, 0x0754)
    jcc_0780 = decode_one(image, cs, 0x0759)
    if test_8081.bytes_hex != "f687e08101" or jz_07a9.kind != "JCC" or jz_07a9.target_ip != 0x07A9:
        raise AssertionError("0747 is not TEST [SI+8081],01 / JZ 07A9")
    if cmp_85b5.bytes_hex != "3a1eb585" or jnz_075b.kind != "JCC" or jnz_075b.target_ip != 0x075B:
        raise AssertionError("074E is not CMP BL,[85B5] / JNZ 075B")
    if cmp_98db.bytes_hex != "803edb9800" or cmp_98db.file != int(state["cmp_file"], 16):
        raise AssertionError("0754 is not CMP byte ptr [98DB],0")
    if jcc_0780.kind != "JCC" or jcc_0780.target_ip != 0x0780 or jcc_0780.file != int(prev["branch_file"], 16):
        raise AssertionError("0759 does not JNZ to 0780")
    al = 0xB0
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xB0 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 6 or _u16(image, 0x559AA + 6) != 0x05FD:
        raise AssertionError("AL high nibble B does not select BX-table slot 05FD")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    body, hit = follow_local(image, cs, 0x0780, limit=64)
    if hit:
        raise AssertionError("0780 walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708) for insn in body):
        raise AssertionError("0780 walk entered an unreached NOP")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0780 body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [
        0x0780,
        0x0785,
        0x0787,
        0x078B,
        0x078E,
        0x0790,
        0x0794,
        0x0796,
        0x079A,
        0x079B,
        0x079E,
        0x07A3,
        0x07A6,
        0x07A9,
        0x07AC,
    ]:
        raise AssertionError("0780 body is not the fifteen-instruction seed through JMP 0907")
    if head[0].bytes_hex != "803e748300" or head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("0780 does not begin with CMP [7483],0 / end with JMP 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("0780 body does not end at the JMP")
    if decode_one(image, cs, 0x0907).file != int(state["store_file"], 16):
        raise AssertionError("0907 is not the owned store helper")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("0780 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:0780 body is not the owned seed")
    if not _gap_at(int(state["sled_file"], 16)):
        raise AssertionError("NOP at 0693 is owned")
    if not _gap_at(int(state["nop_file"], 16)):
        raise AssertionError("NOP at 0708 is owned")
    owned_073d = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_073d = True
    if not owned_073d:
        raise AssertionError("D547:073D body is not owned")
    owned_07af = False
    nxt = pin["state_07af"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(nxt["body_file"], 16)
            and end == int(nxt["body_end"], 16)
            and owner == "code"
        ):
            owned_07af = True
    if not owned_07af:
        raise AssertionError("D547:07AF is not owned")


def _check_d547_07af(image: bytes, pin: dict) -> None:
    """High nibble D selects BX slot 5; stub 05F7 stores 07AF for JMP BX."""
    state = pin["state_07af"]
    prev = pin["state_0780"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x07AF
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:07AF file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:07AF 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x0491
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:0491 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:0491 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:07AF through JMP 0900")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:0780 body")
    _expect_hex(image, int(state["slot5_file"], 16), state["slot5_bytes"], "BX-table slot 5 word 05F7")
    _expect_hex(image, int(state["slot_stub_file"], 16), state["slot_stub_bytes"], "05F7 MOV BX,07AF / JMP 0907")
    _expect_hex(image, int(state["index_file"], 16), state["index_bytes"], "high-nibble index into BX table")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned JMP 0900 target")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0491 bounded gap head")
    if decode_one(image, cs, 0x07AC).kind != "JMPN" or decode_one(image, cs, 0x07AC).target_ip != 0x0907:
        raise AssertionError("0780 ends at 07AC JMP 0907; 07AF is not sequential fall-through")
    if decode_one(image, cs, 0x04D6).bytes_hex != "a880":
        raise AssertionError("04D6 is not TEST AL,0x80")
    al = 0xD8
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xD8 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 10 or _u16(image, int(state["slot5_file"], 16)) != 0x05F7:
        raise AssertionError("AL high nibble D does not select BX-table slot 05F7")
    if ((0xDF & 0xF0) >> 3) & 0x0E != 10:
        raise AssertionError("AL=0xDF does not share slot 5")
    if decode_one(image, cs, 0x04D8).target_ip != 0x0517:
        raise AssertionError("bit 7 clear does not go to the reader")
    if decode_one(image, cs, 0x0535).bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3" or decode_one(image, cs, 0x051D).file != 0x5598D:
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0526 for insn in dispatch):
        raise AssertionError("04D5 walk does not reach the high-nibble index")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if not any(insn.ip == 0x051D and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP BX")
    if any(insn.ip in (0x05F7, 0x07AF) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 05F7 or 07AF")
    slot, slot_hit = follow_local(image, cs, 0x05F7, limit=8)
    if slot_hit:
        raise AssertionError("05F7 walk hit the limit")
    if [insn.ip for insn in slot] != [0x05F7, 0x05FA, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("05F7 is not MOV BX,07AF / JMP 0907 / store / RET")
    if slot[0].bytes_hex != "bbaf07" or slot[-1].kind != "RET":
        raise AssertionError("05F7 does not store BX=07AF")
    if any(insn.ip == 0x07AF for insn in slot):
        raise AssertionError("05F7 walk entered 07AF before RET")
    body, hit = follow_local(image, cs, 0x07AF, limit=48)
    if hit:
        raise AssertionError("07AF walk hit the limit")
    if any(
        insn.file in (0x55B03, 0x55B78, 0x55C51, 0x55C9B)
        or insn.ip in (0x0693, 0x0708, 0x07E1, 0x082B, 0x0491)
        for insn in body
    ):
        raise AssertionError("07AF walk entered an unreached NOP, 07E1, or 082B")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("07AF body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [
        0x07AF,
        0x07B2,
        0x07B7,
        0x07B9,
        0x07BB,
        0x07BD,
        0x07BF,
        0x07C1,
        0x07C5,
        0x07C7,
        0x07C9,
        0x07CB,
        0x07CF,
        0x07D1,
        0x07D4,
        0x07D8,
        0x07DB,
    ]:
        raise AssertionError("07AF body is not the seventeen-instruction seed through JMP 0900")
    if head[0].bytes_hex != "a25897" or head[-1].kind != "JMPN" or head[-1].target_ip != 0x0900:
        raise AssertionError("07AF does not begin with MOV [9967],AL / end with JMP 0900")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("07AF body does not end at the JMP 0900")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("07AF follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:07AF body is not the owned seed")
    bridge = pin["state_07de"]
    if _gap_at(int(bridge["body_file"], 16)):
        raise AssertionError("D547:07DE JMP 0907 bridge is still a gap")
    owned_bridge = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(bridge["body_file"], 16)
            and end == int(bridge["body_end"], 16)
            and owner == "code"
        ):
            owned_bridge = True
    if not owned_bridge:
        raise AssertionError("D547:07DE bridge is not the owned seed")
    if decode_one(image, cs, 0x07B7).bytes_hex != bridge["jcc1_bytes"] or decode_one(image, cs, 0x07B7).target_ip != 0x07DE:
        raise AssertionError("07B7 is not JZ 07DE")
    if decode_one(image, cs, 0x07CF).bytes_hex != bridge["jcc2_bytes"] or decode_one(image, cs, 0x07CF).target_ip != 0x07DE:
        raise AssertionError("07CF is not JL 07DE")
    if decode_one(image, cs, 0x07DE).bytes_hex != bridge["body_bytes"] or decode_one(image, cs, 0x07DE).target_ip != 0x0907:
        raise AssertionError("07DE is not JMP 0907")
    if not _gap_at(int(state["next_file"], 16)):
        raise AssertionError("D547:0491 bounded gap head is owned")
    owned_0780 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_0780 = True
    if not owned_0780:
        raise AssertionError("D547:0780 body is not owned")
    if int(prev["next_file"], 16) != int(state["body_file"], 16):
        raise AssertionError("0780 bounded hole head does not match 07AF body file")
    owned_082b = False
    gap082 = pin["state_082b"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(gap082["body_file"], 16)
            and end == int(gap082["body_end"], 16)
            and owner == "code"
        ):
            owned_082b = True
    if not owned_082b:
        raise AssertionError("D547:082B body is not owned")


def _check_d547_07de(image: bytes, pin: dict) -> None:
    """07AF JZ 07B7 and JL 07CF reach JMP 0907; not fall-through from 07DB JMP 0900."""
    state = pin["state_07de"]
    prev = pin["state_07af"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x07DE
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:07DE file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:07DE 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:07DE JMP 0907")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:07AF body")
    _expect_hex(image, int(state["jcc1_file"], 16), state["jcc1_bytes"], "07B7 JZ 07DE")
    _expect_hex(image, int(state["jcc2_file"], 16), state["jcc2_bytes"], "07CF JL 07DE")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned 0907 store helper")
    if decode_one(image, cs, 0x07DB).target_ip != 0x0900:
        raise AssertionError("07DB JMP 0900 does not fall into 07DE")
    if decode_one(image, cs, 0x07DE).target_ip != 0x0907:
        raise AssertionError("07DE does not JMP to owned 0907")
    if int(state["body_end"], 16) != int(pin["state_07e1"]["body_file"], 16):
        raise AssertionError("07DE bridge does not stop before owned 07E1")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:07DE bridge is not the owned seed")
    if not _gap_at(int(state["next_file"], 16)):
        raise AssertionError("D547:0491 bounded gap head is owned")
    owned_07af = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_07af = True
    if not owned_07af:
        raise AssertionError("D547:07AF body is not owned")


def _check_d547_062d(image: bytes, pin: dict) -> None:
    """07E1 JMP 062D at 0828 reaches the body; body exits through JMP 0907 at 065A."""
    state = pin["state_062d"]
    prev = pin["state_07e1"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x062D
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:062D file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:062D 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:062D through JMP 0907")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:07E1 body")
    _expect_hex(image, int(state["reacher_file"], 16), state["reacher_bytes"], "07E1 JMP 062D")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["join_file"], 16), state["join_bytes"], "owned D547:0663 head")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    reach = decode_one(image, cs, 0x0828)
    if reach.kind != "JMPN" or reach.target_ip != 0x062D or reach.bytes_hex != "e902fe":
        raise AssertionError("0828 is not JMP 062D")
    if reach.file != int(state["reacher_file"], 16):
        raise AssertionError("0828 file is not 0x55C98")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    body, hit = follow_local(image, cs, 0x062D, limit=80)
    if hit:
        raise AssertionError("062D walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708, 0x07AF) for insn in body):
        raise AssertionError("062D walk entered an unreached NOP or 07AF")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("062D body contains BRKXA/RETXA")
    head = [insn for insn in body if int(state["body_file"], 16) <= insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [
        0x062D,
        0x0630,
        0x0632,
        0x0634,
        0x0637,
        0x0639,
        0x063E,
        0x0640,
        0x0641,
        0x0644,
        0x0646,
        0x064B,
        0x064C,
        0x064E,
        0x0653,
        0x0657,
        0x065A,
    ]:
        raise AssertionError("062D body is not the seventeen-instruction seed through JMP 0907")
    if head[0].bytes_hex != "bb3407" or head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("062D does not begin with MOV BX,0734 / end with JMP 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("062D body does not end at the JMP 0907")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("062D follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:062D body is not the owned seed")
    owned_07e1 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_07e1 = True
    if not owned_07e1:
        raise AssertionError("D547:07E1 body is not owned")


def _check_d547_065d(image: bytes, pin: dict) -> None:
    """062D JNS 065D at 063E; body is MOV BX,062D / JMP 0907."""
    state = pin["state_065d"]
    prev = pin["state_062d"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x065D
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:065D file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:065D 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x08CF
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:08CF file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:08CF 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:065D through JMP 0907")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:062D body")
    _expect_hex(image, int(state["jcc_file"], 16), state["jcc_bytes"], "062D JNS 065D")
    _expect_hex(image, int(state["flag_file"], 16), state["flag_bytes"], "062D OR SI,SI")
    _expect_hex(image, int(state["join_file"], 16), state["join_bytes"], "owned D547:0663 head")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:08CF gap head")
    jcc = decode_one(image, cs, 0x063E)
    if jcc.kind != "JCC" or jcc.target_ip != 0x065D or jcc.bytes_hex != "791d":
        raise AssertionError("063E is not JNS 065D")
    if decode_one(image, cs, 0x0630).bytes_hex != "0bf6":
        raise AssertionError("0630 is not OR SI,SI")
    body, hit = follow_local(image, cs, 0x065D, limit=40)
    if hit:
        raise AssertionError("065D walk hit the limit")
    head = [insn for insn in body if int(state["body_file"], 16) <= insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x065D, 0x0660]:
        raise AssertionError("065D body is not MOV BX,062D / JMP 0907")
    if head[0].bytes_hex != "bb2d06" or head[-1].kind != "JMPN" or head[-1].target_ip != 0x0907:
        raise AssertionError("065D does not begin with MOV BX,062D / end with JMP 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("065D body does not end at the JMP 0907")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("065D follow does not end at the 0907 RET")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in head):
        raise AssertionError("065D body contains BRKXA/RETXA")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:065D body is not the owned seed")
    owned_08cf = False
    nxt = pin["state_08cf"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(nxt["body_file"], 16) and end == int(nxt["body_end"], 16) and owner == "code":
            owned_08cf = True
    if not owned_08cf:
        raise AssertionError("D547:08CF body is not owned")


def _check_d547_08cf(image: bytes, pin: dict) -> None:
    """High nibble 6 selects BX slot 6. [81D9] bit 0 set stores 08CF for JMP BX."""
    state = pin["state_08cf"]
    prev = pin["state_065d"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x08CF
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:08CF file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:08CF 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x08D9
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:08D9 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:08D9 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:08CF through JMPS 0907")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:065D body")
    _expect_hex(image, int(state["slot6_file"], 16), state["slot6_bytes"], "BX-table slot 6 word 0603")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "0603 through JMP 0907")
    _expect_hex(image, int(state["mov_file"], 16), state["mov_bytes"], "MOV BX,08CF / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["unreached_nop_file"], 16), state["unreached_nop_bytes"], "unreached NOP at 08D8")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:08D9 gap head")
    _expect_hex(image, int(state["writer_08d9_file"], 16), state["writer_08d9_bytes"], "08CF MOV BX,08D9")
    al = 0xE0
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xE0 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 0x0C or _u16(image, 0x559B6) != 0x0603:
        raise AssertionError("AL high nibble 0xE does not select BX-table slot 0603")
    if (((0x60 & 0xF0) >> 3) & 0x0E) != 0x0C or (0x60 & 0x80) != 0:
        raise AssertionError("high nibble 6 does not share the slot index off the writer path")
    if decode_one(image, cs, 0x04D8).target_ip != 0x0517:
        raise AssertionError("bit 7 clear does not go to the reader")
    if decode_one(image, cs, 0x0535).bytes_hex != "2effa73a05":
        raise AssertionError("0535 is not JMP CS:[BX+053A]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3" or decode_one(image, cs, 0x051D).file != 0x5598D:
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    jz = decode_one(image, cs, 0x060B)
    if jz.kind != "JCC" or jz.target_ip != 0x062A:
        raise AssertionError("060B does not JZ over MOV BX,08CF")
    if decode_one(image, cs, 0x0603).bytes_hex != "bb1f05" or decode_one(image, cs, 0x0606).bytes_hex != "f606d98101":
        raise AssertionError("0603 is not MOV BX,051F / TEST [81D9],1")
    if decode_one(image, cs, 0x060D).bytes_hex != "bbcf08" or decode_one(image, cs, 0x060D).file != 0x55A7D:
        raise AssertionError("060D is not MOV BX,08CF")
    if decode_one(image, cs, 0x062A).kind != "JMPN" or decode_one(image, cs, 0x062A).target_ip != 0x0907:
        raise AssertionError("062A does not JMP 0907")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x0526 for insn in dispatch):
        raise AssertionError("04D5 walk does not reach the high-nibble index")
    if not any(insn.ip == 0x0535 and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[BX+053A]")
    if not any(insn.ip == 0x051D and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP BX")
    if any(insn.ip in (0x0603, 0x060D, 0x08CF) for insn in dispatch):
        raise AssertionError("indirect JMP fall-through entered 0603 or 08CF")
    if decode_one(image, cs, 0x0610).kind != "JMPN" or decode_one(image, cs, 0x0610).target_ip != 0x0907:
        raise AssertionError("0610 does not JMP 0907 on the [81D9] bit-0 set path")
    if decode_one(image, cs, 0x062A).kind != "JMPN" or decode_one(image, cs, 0x062A).target_ip != 0x0907:
        raise AssertionError("062A does not JMP 0907 on the [81D9] bit-0 clear path")
    body, hit = follow_local(image, cs, 0x08CF, limit=12)
    if hit:
        raise AssertionError("08CF walk hit the limit")
    if any(
        insn.file in (0x55B03, 0x55B78, 0x55D48) or insn.ip in (0x0693, 0x0708, 0x08D8, 0x08D9)
        for insn in body
    ):
        raise AssertionError("08CF walk entered an unreached NOP or 08D9")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("08CF body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [0x08CF, 0x08D3, 0x08D6]:
        raise AssertionError("08CF body is not MOV [SI+7634],AL / MOV BX,08D9 / JMPS 0907")
    if head[0].bytes_hex != "88843476" or head[1].bytes_hex != "bbd908":
        raise AssertionError("08CF does not MOV [SI+7634],AL then MOV BX,08D9")
    if head[-1].kind != "JMPS" or head[-1].target_ip != 0x0907:
        raise AssertionError("08D6 does not JMPS to owned 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("08CF body does not end at the JMPS")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("08CF follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:08CF body is not the owned seed")
    if not _gap_at(int(state["unreached_nop_file"], 16)):
        raise AssertionError("NOP at 08D8 is owned")
    owned_08d9 = False
    nxt = pin["state_08d9"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(nxt["body_file"], 16) and end == int(nxt["body_end"], 16) and owner == "code":
            owned_08d9 = True
    if not owned_08d9:
        raise AssertionError("D547:08D9 body is not owned")
    owned_065d = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_065d = True
    if not owned_065d:
        raise AssertionError("D547:065D body is not owned")


def _check_d547_08d9(image: bytes, pin: dict) -> None:
    """08CF stores 08D9 for JMP BX when high nibble E and [81D9] bit 0 set reach 08CF."""
    state = pin["state_08d9"]
    prev = pin["state_08cf"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x08D9
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:08D9 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:08D9 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x082B
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:082B file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:082B 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:08D9 through JMPS 0907")
    _expect_hex(image, int(prev["writer_08d9_file"], 16), prev["writer_08d9_bytes"], "08CF MOV BX,08D9")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:08CF body")
    _expect_hex(image, int(state["jmp_target_file"], 16), state["jmp_target_bytes"], "owned 0900 entry")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["unreached_nop_file"], 16), state["unreached_nop_bytes"], "unreached NOP at 08D8")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:082B gap head")
    if decode_one(image, cs, 0x0900).file != int(state["jmp_target_file"], 16):
        raise AssertionError("0900 is not the owned target")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    al = 0xE0
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0xE0 is not on the 04E1 path")
    if ((al & 0xF0) >> 3) & 0x0E != 0x0C or _u16(image, 0x559B6) != 0x0603:
        raise AssertionError("AL high nibble 0xE does not select BX-table slot 0603")
    if decode_one(image, cs, 0x060D).bytes_hex != "bbcf08" or decode_one(image, cs, 0x060D).file != 0x55A7D:
        raise AssertionError("060D is not MOV BX,08CF")
    cf_body, cf_hit = follow_local(image, cs, 0x08CF, limit=12)
    if cf_hit:
        raise AssertionError("08CF walk hit the limit")
    if cf_body[1].bytes_hex != "bbd908" or cf_body[-1].kind != "RET" or cf_body[-1].ip != 0x090D:
        raise AssertionError("08CF does not store 08D9 through the owned 0907 helper")
    body, hit = follow_local(image, cs, 0x08D9, limit=32)
    if hit:
        raise AssertionError("08D9 walk hit the limit")
    if any(
        insn.file in (0x55B03, 0x55B78, 0x55D48, 0x55901, 0x55C9B)
        or insn.ip in (0x0693, 0x0708, 0x08D8, 0x0491, 0x082B, 0x08CF)
        for insn in body
    ):
        raise AssertionError("08D9 walk entered an unreached NOP, bounded hole, or 08CF")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("08D9 body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if [insn.ip for insn in head] != [
        0x08D9,
        0x08DC,
        0x08E0,
        0x08E2,
        0x08E4,
        0x08E8,
        0x08EA,
        0x08EC,
        0x08EE,
        0x08F2,
        0x08F4,
        0x08F7,
        0x08FA,
        0x08FD,
    ]:
        raise AssertionError("08D9 body is not the reached instructions through JMPS 0907")
    if head[0].bytes_hex != "bbcf08" or head[1].bytes_hex != "88843676":
        raise AssertionError("08D9 does not MOV BX,08CF then MOV [SI+7636],AL")
    if head[12].kind != "JMPS" or head[12].target_ip != 0x0900:
        raise AssertionError("08FA does not JMPS to owned 0900")
    if head[-1].kind != "JMPS" or head[-1].target_ip != 0x0907:
        raise AssertionError("08FD does not JMPS to owned 0907")
    if int(state["body_end"], 16) != head[-1].file + head[-1].length + 1:
        raise AssertionError("08D9 seed includes dead NOP fall-through before owned 0900")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("08D9 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:08D9 body is not the owned seed")
    if not _gap_at(int(state["unreached_nop_file"], 16)):
        raise AssertionError("NOP at 08D8 is owned")
    owned_07af = False
    nxt = pin["state_07af"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(nxt["body_file"], 16)
            and end == int(nxt["body_end"], 16)
            and owner == "code"
        ):
            owned_07af = True
    if not owned_07af:
        raise AssertionError("D547:07AF body is not owned")
    owned_08cf = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_08cf = True
    if not owned_08cf:
        raise AssertionError("D547:08CF body is not owned")
    owned_082b = False
    nxt082 = pin["state_082b"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(nxt082["body_file"], 16)
            and end == int(nxt082["body_end"], 16)
            and owner == "code"
        ):
            owned_082b = True
    if not owned_082b:
        raise AssertionError("D547:082B body is not owned")
    if not _gap_at(int(nxt082["next_file"], 16)):
        raise AssertionError("D547:0491 bounded gap head is owned")


def _check_d547_082b(image: bytes, pin: dict) -> None:
    """DI slot 1 (AL&0x0F==1) stub 0587 fall-through stores 082B for JMP BX."""
    state = pin["state_082b"]
    prev = pin["state_07af"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x082B
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:082B file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:082B 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x0491
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:0491 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:0491 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:082B through JMPS 0907")
    _expect_hex(image, int(state["di_slot1_file"], 16), state["di_slot1_bytes"], "DI-table slot 1 word 0587")
    _expect_hex(image, int(state["slot_stub_file"], 16), state["slot_stub_bytes"], "0587 CMP [81BF],0 / JZ skip")
    _expect_hex(image, int(state["writer_file"], 16), state["writer_bytes"], "MOV BX,082B / JMP 0907")
    _expect_hex(image, int(prev["body_file"], 16), prev["body_bytes"], "owned D547:07AF body")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0491 bounded gap head")
    if decode_one(image, cs, 0x0828).bytes_hex != "e902fe":
        raise AssertionError("0828 is JMP 062D; 082B is not sequential fall-through from 07E1")
    al = 0x81
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0x81 is not on the 04E1 path")
    if _u16(image, 0x559D1 + ((al & 0x0F) << 1)) != 0x0587:
        raise AssertionError("AL low nibble 1 does not select DI-table slot 0587")
    if decode_one(image, cs, 0x04D6).bytes_hex != "a880":
        raise AssertionError("04D6 is not TEST AL,0x80")
    if decode_one(image, cs, 0x0587).bytes_hex != "803ebf8100":
        raise AssertionError("0587 is not CMP byte [81BF],0")
    if decode_one(image, cs, 0x059F).bytes_hex != "bb2b08":
        raise AssertionError("059F is not MOV BX,082B")
    if decode_one(image, cs, 0x055C).bytes_hex != "2effa56105":
        raise AssertionError("055C is not JMP CS:[DI+0561]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3":
        raise AssertionError("051D is not JMP BX")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x055C and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[DI+0561]")
    if not any(insn.ip == 0x051D and insn.bytes_hex == "ffe3" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP BX")
    if any(insn.ip in (0x0587, 0x082B) for insn in dispatch):
        raise AssertionError("04D5 walk entered 0587 or 082B by fall-through")
    slot, slot_hit = follow_local(image, cs, 0x059F, limit=8)
    if slot_hit:
        raise AssertionError("059F walk hit the limit")
    if [insn.ip for insn in slot] != [0x059F, 0x05A2, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("059F is not MOV BX,082B / JMP 0907 / store / RET")
    if slot[0].bytes_hex != "bb2b08" or slot[1].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("059F does not store BX=082B")
    if any(insn.ip == 0x082B for insn in slot):
        raise AssertionError("059F walk entered 082B before RET")
    body, hit = follow_local(image, cs, 0x082B, limit=128)
    if hit:
        raise AssertionError("082B walk hit the limit")
    if any(
        insn.file in (0x55B03, 0x55B78, 0x55D48, 0x55901)
        or insn.ip in (0x0693, 0x0708, 0x08D8, 0x0491)
        for insn in body
    ):
        raise AssertionError("082B walk entered an unreached NOP or bounded hole")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("082B body contains BRKXA/RETXA")
    head = [insn for insn in body if insn.file < int(state["body_end"], 16)]
    if len(head) != 52:
        raise AssertionError("082B body is not the fifty-two-instruction seed through JMPS 0907")
    if head[0].bytes_hex != "803edbd700" or head[0].ip != 0x082B:
        raise AssertionError("082B does not begin with CMP byte [DBD7],0")
    if head[-1].kind != "JMPS" or head[-1].target_ip != 0x0907 or head[-1].ip != 0x08CC:
        raise AssertionError("08CC does not JMPS to owned 0907")
    if head[-1].file + head[-1].length != int(state["body_end"], 16):
        raise AssertionError("082B body does not end at the JMPS")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("082B follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:082B body is not the owned seed")
    owned_07af = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_07af = True
    if not owned_07af:
        raise AssertionError("D547:07AF body is not owned")
    if not _gap_at(int(state["next_file"], 16)):
        raise AssertionError("D547:0491 bounded gap head is owned")


def _check_d547_0933(image: bytes, pin: dict) -> None:
    """Owned 082B CALLN at 0860 and 08BD enter 0933; RET does not fall into 0957."""
    state = pin["state_0933"]
    caller = pin["state_082b"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x0933
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:0933 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:0933 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x0957
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:0957 file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:0957 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:0933 through JMP short 0956")
    _expect_hex(image, int(state["join_file"], 16), state["join_bytes"], "D547:094A through RET")
    _expect_hex(image, int(state["call1_file"], 16), state["call1_bytes"], "D547:0860 CALL 0933")
    _expect_hex(image, int(state["call1_jcc_file"], 16), state["call1_jcc_bytes"], "D547:0856 JZ 0860")
    _expect_hex(image, int(state["call2_file"], 16), state["call2_bytes"], "D547:08BD CALL 0933")
    _expect_hex(image, int(state["call2_jcc_file"], 16), state["call2_jcc_bytes"], "D547:08BB JGE 08C0")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0949")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:0957 gap head")
    _expect_hex(image, int(caller["body_file"], 16), caller["body_bytes"], "owned D547:082B body")
    if decode_one(image, cs, 0x0860).kind != "CALLN" or decode_one(image, cs, 0x0860).target_ip != 0x0933:
        raise AssertionError("0860 is not CALL 0933")
    if decode_one(image, cs, 0x08BD).kind != "CALLN" or decode_one(image, cs, 0x08BD).target_ip != 0x0933:
        raise AssertionError("08BD is not CALL 0933")
    if decode_one(image, cs, 0x0856).kind != "JCC" or decode_one(image, cs, 0x0856).target_ip != 0x0860:
        raise AssertionError("0856 is not JZ 0860")
    if decode_one(image, cs, 0x085D).kind != "JMPS" or decode_one(image, cs, 0x085D).target_ip != 0x08C9:
        raise AssertionError("085D JMP 08C9 does not skip 0860")
    if decode_one(image, cs, 0x08BB).kind != "JCC" or decode_one(image, cs, 0x08BB).target_ip != 0x08C0:
        raise AssertionError("08BB is not JGE 08C0")
    if decode_one(image, cs, 0x093E).target_ip != 0x094A or decode_one(image, cs, 0x0947).target_ip != 0x0956:
        raise AssertionError("0933 does not skip the 0949 NOP")
    if decode_one(image, cs, 0x094D).target_ip != 0x0956 or decode_one(image, cs, 0x0956).kind != "RET":
        raise AssertionError("094A path does not RET at 0956")
    body, hit = follow_local(image, cs, 0x0933, limit=24)
    if hit:
        raise AssertionError("0933 walk hit the limit")
    if any(insn.ip in (0x0949, 0x0957) or insn.file in (0x55DB9, 0x55DC7) for insn in body):
        raise AssertionError("0933 walk entered the skipped NOP or 0957")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0933 body contains BRKXA/RETXA")
    if [insn.ip for insn in body] != [
        0x0933,
        0x0935,
        0x0937,
        0x093A,
        0x093C,
        0x093E,
        0x0940,
        0x0943,
        0x0947,
        0x094A,
        0x094D,
        0x094F,
        0x0952,
        0x0956,
    ]:
        raise AssertionError("0933 body is not the fourteen reached instructions")
    if body[0].bytes_hex != "8ae0" or body[2].bytes_hex != "c0eb05" or body[3].bytes_hex != "2aff":
        raise AssertionError("0933 does not MOV AH,AL / SHR BL,5 / SUB BH,BH")
    if body[7].bytes_hex != "88a7dcd7" or body[12].bytes_hex != "08a7dcd7":
        raise AssertionError("0933 does not write DS:[BX+D7DC]")
    if body[-1].kind != "RET" or body[-1].file + body[-1].length != int(state["join_end"], 16):
        raise AssertionError("0933 does not RET at the end of the join seed")
    owned_head = False
    owned_join = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned_head = True
        if start == int(state["join_file"], 16) and end == int(state["join_end"], 16) and owner == "code":
            owned_join = True
    if not owned_head or not owned_join:
        raise AssertionError("D547:0933 seeds are not owned code")
    if not _gap_at(int(state["nop_file"], 16)) or not _gap_at(int(state["next_file"], 16)):
        raise AssertionError("0949 NOP or 0957 tail is owned")
    owned_082b = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(caller["body_file"], 16) and end == int(caller["body_end"], 16) and owner == "code":
            owned_082b = True
    if not owned_082b:
        raise AssertionError("D547:082B body is not owned")


def _check_c44e_02bf(image: bytes, pin: dict) -> None:
    """C44E:0060 falls through slot 005E into CALL 02BF. Both BX tables stay local."""
    state = pin["state_c44e_02bf"]
    cs = 0xC44E
    phys20 = (cs << 4) + 0x02BF
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C44E:02BF file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C44E:02BF is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C44E:02BF 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["pgr_file"], 16), state["pgr_bytes"], "second PGR slot 49")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C44E:02BF head")
    _expect_hex(image, int(state["caller_file"], 16), state["caller_bytes"], "C44E:0060 CALL 02BF")
    _expect_hex(image, int(state["slot_file"], 16), state["slot_bytes"], "00B8 slot 1 IP 005E")
    _expect_hex(image, int(state["table_044d_file"], 16), state["table_044d_bytes"], "BX+044D table")
    _expect_hex(image, int(state["table_0459_file"], 16), state["table_0459_bytes"], "BX+0459 table")
    _expect_hex(image, int(state["callee_file"], 16), state["callee_bytes"], "C44E:0465 through RETF")
    if decode_one(image, cs, 0x005E).bytes_hex != "90" or decode_one(image, cs, 0x0060).target_ip != 0x02BF:
        raise AssertionError("slot 005E does not fall into CALL 02BF")
    if decode_one(image, cs, 0x03B2).bytes_hex != "83fb05" or decode_one(image, cs, 0x03B5).target_ip != 0x03FC:
        raise AssertionError("first switch is not CMP BX,5 / JA 03FC")
    if decode_one(image, cs, 0x03B9).bytes_hex != "2effa75904":
        raise AssertionError("03B9 is not JMP CS:[BX+0459]")
    if decode_one(image, cs, 0x0401).bytes_hex != "83fb05" or decode_one(image, cs, 0x0404).target_ip != 0x0442:
        raise AssertionError("second switch is not CMP BX,5 / JA 0442")
    if decode_one(image, cs, 0x0408).bytes_hex != "2effa74d04":
        raise AssertionError("0408 is not JMP CS:[BX+044D]")
    if decode_one(image, cs, 0x044C).kind != "RETF":
        raise AssertionError("044C is not RETF")
    if decode_one(image, cs, 0x0484).kind != "RETF":
        raise AssertionError("0465 does not RETF at 0484")
    covered: set[int] = set()
    for ip in (0x02BF, 0x03BE, 0x03DE, 0x040D, 0x0465):
        body, hit = follow_local(image, cs, ip, limit=250)
        if hit:
            raise AssertionError(f"{ip:04X} walk hit the limit")
        if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
            raise AssertionError(f"{ip:04X} body contains BRKXA/RETXA")
        for insn in body:
            if int(state["body_file"], 16) <= insn.file < int(state["callee_end"], 16):
                covered.update(range(insn.file, insn.file + insn.length))
    code = set(range(int(state["body_file"], 16), int(state["body_end"], 16)))
    callee = set(range(int(state["callee_file"], 16), int(state["callee_end"], 16)))
    table = set(range(int(state["table_044d_file"], 16), int(state["callee_file"], 16)))
    if code - covered or callee - covered or covered & table:
        raise AssertionError("02BF reached bytes do not match the code seeds")
    words_044d = [_u16(image, int(state["table_044d_file"], 16) + 2 * i) for i in range(6)]
    words_0459 = [_u16(image, int(state["table_0459_file"], 16) + 2 * i) for i in range(6)]
    if words_044d != [0x040D, 0x0442, 0x0442, 0x040D, 0x040D, 0x040D]:
        raise AssertionError("044D table is not the six local IPs")
    if words_0459 != [0x03DE, 0x03FC, 0x03FC, 0x03BE, 0x03BE, 0x03DE]:
        raise AssertionError("0459 table is not the six local IPs")
    owned_body = owned_table = owned_callee = False
    for start, end, owner, kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned_body = True
        if start == int(state["table_044d_file"], 16) and end == int(state["callee_file"], 16) and kind == "jump_table":
            owned_table = True
        if start == int(state["callee_file"], 16) and end == int(state["callee_end"], 16) and owner == "code":
            owned_callee = True
    if not (owned_body and owned_table and owned_callee):
        raise AssertionError("C44E:02BF seeds are not owned")
    if _gap_at(int(state["body_file"], 16)) or _gap_at(int(state["callee_end"], 16)):
        raise AssertionError("02BF body or the following 0485 entry is still a gap")


def _check_c4c8_000d(image: bytes, pin: dict) -> None:
    """C425:0160 calls C4C8:000D. Slot callees 00A3/0FDF/12A9/1B3F/1DC3 stay unowned."""
    state = pin["state_c4c8_000d"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x000D
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:000D file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:000D is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:000D 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["pgr_file"], 16), state["pgr_bytes"], "second PGR slot 49")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C4C8:000D prologue")
    _expect_hex(image, int(state["body_end"], 16) - 5, state["epilogue_bytes"], "C4C8:0094 epilogue")
    _expect_hex(image, int(state["caller_file"], 16), state["caller_bytes"], "C425:0160 CALLF")
    _expect_hex(image, int(state["table_file"], 16), state["table_bytes"], "C4C8:0099 table")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "C4C8:00A3 gap head")
    if decode_one(image, 0xC425, 0x0160).kind != "CALLF" or decode_one(image, 0xC425, 0x0160).target_ip != 0x000D:
        raise AssertionError("C425:0160 is not CALLF C4C8:000D")
    if decode_one(image, 0xC425, 0x0160).target_cs != cs:
        raise AssertionError("C425:0160 target CS is not C4C8")
    if decode_one(image, cs, 0x005D).bytes_hex != "83fb04" or decode_one(image, cs, 0x0060).target_ip != 0x0094:
        raise AssertionError("005D is not CMP BX,4 / JA 0094")
    if decode_one(image, cs, 0x0064).bytes_hex != "2effa79900":
        raise AssertionError("0064 is not JMP CS:[BX+0099]")
    if decode_one(image, cs, 0x0098).kind != "RETF":
        raise AssertionError("0098 is not RETF")
    words = [_u16(image, int(state["table_file"], 16) + 2 * i) for i in range(5)]
    if words != [0x0069, 0x0072, 0x007B, 0x0084, 0x008D]:
        raise AssertionError("0099 table is not the five slot IPs")
    covered: set[int] = set()
    for ip in (0x000D, 0x0069, 0x0072, 0x007B, 0x0084, 0x008D):
        walked, hit = follow_local(image, cs, ip, limit=80)
        if hit:
            raise AssertionError(f"{ip:04X} walk hit the limit")
        if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in walked):
            raise AssertionError(f"{ip:04X} body contains BRKXA/RETXA")
        if any(insn.file >= int(state["next_file"], 16) for insn in walked):
            raise AssertionError(f"{ip:04X} walk entered a slot callee")
        for insn in walked:
            if int(state["body_file"], 16) <= insn.file < int(state["body_end"], 16):
                covered.update(range(insn.file, insn.file + insn.length))
    if set(range(int(state["body_file"], 16), int(state["body_end"], 16))) - covered:
        raise AssertionError("000D reached bytes do not cover the head seed")
    owned_body = owned_table = False
    for start, end, owner, kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned_body = True
        if start == int(state["table_file"], 16) and end == int(state["next_file"], 16) and kind == "jump_table":
            owned_table = True
    if not (owned_body and owned_table):
        raise AssertionError("C4C8:000D seeds are not owned")
    if _gap_at(int(state["next_file"], 16)):
        raise AssertionError("C4C8:00A3 callee is still a gap")


def _check_c4c8_00a3(image: bytes, pin: dict) -> None:
    """Slot 006B calls 00A3. The walk covers the whole gap and RETFs; near callees stay out."""
    state = pin["state_c4c8_00a3"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x00A3
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:00A3 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:00A3 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:00A3 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C4C8:00A3 prologue")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:00A3 epilogue")
    _expect_hex(image, int(state["caller_file"], 16), state["caller_bytes"], "C4C8:006B CALL 00A3")
    call = decode_one(image, cs, 0x006B)
    if call.kind != "CALLN" or call.target_ip != 0x00A3:
        raise AssertionError("006B is not CALL 00A3")
    body, hit = follow_local(image, cs, 0x00A3, limit=400)
    if hit:
        raise AssertionError("00A3 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("00A3 body contains BRKXA/RETXA")
    if [insn for insn in body if insn.kind == "RETF"] != [body[-1]] or body[-1].ip != 0x03D8:
        raise AssertionError("00A3 does not RETF once at 03D8")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(int(state["body_file"], 16), int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("00A3 walk does not match the gap seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:00A3 body is not the owned seed")
    for file_off in (0x4569E,):
        if not _gap_at(file_off):
            raise AssertionError(f"near callee file 0x{file_off:05X} is owned")


def _check_c4c8_0448(image: bytes, pin: dict) -> None:
    """00A3 calls 0448 three times. Body RETFs; 0927 and 0EC9 stay unowned."""
    state = pin["state_c4c8_0448"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0448
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0448 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0448 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0448 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C4C8:0448 prologue")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0448 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0448:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0448")
    if decode_one(image, cs, 0x0450).bytes_hex != "837e0600" or decode_one(image, cs, 0x0454).target_ip != 0x046A:
        raise AssertionError("0450 is not CMP word [BP+6],0 / JZ 046A")
    if decode_one(image, cs, 0x0463).bytes_hex != "83fe10" or decode_one(image, cs, 0x045C).target_ip != 0x0927:
        raise AssertionError("first loop is not SI<0x10 / CALL 0927")
    if decode_one(image, cs, 0x0474).target_ip != 0x0EC9:
        raise AssertionError("0474 is not CALL 0EC9")
    if decode_one(image, cs, 0x048F).kind != "RETF":
        raise AssertionError("048F is not RETF")
    body, hit = follow_local(image, cs, 0x0448, limit=80)
    if hit:
        raise AssertionError("0448 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0448 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(int(state["body_file"], 16), int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0448 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x048F:
        raise AssertionError("0448 walk does not end at RETF 048F")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0448 body is not the owned seed")


def _check_c4c8_0490(image: bytes, pin: dict) -> None:
    """00A3 calls 0490 twice. The body zeros 0x3C0 words at DS:1591 and RETFs."""
    state = pin["state_c4c8_0490"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0490
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0490 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0490 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0490 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C4C8:0490 prologue")
    _expect_hex(image, int(state["body_file"], 16) + 9, state["zero_bytes"], "C4C8:0490 REP STOSW")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0490 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0490:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0490")
    if decode_one(image, cs, 0x0499).bytes_hex != "b9c003" or decode_one(image, cs, 0x04A3).bytes_hex != "f3ab":
        raise AssertionError("0499 is not MOV CX,0x3C0 / REP STOSW")
    if decode_one(image, cs, 0x04C6).bytes_hex != "83fe10" or decode_one(image, cs, 0x04BF).target_ip != 0x05B9:
        raise AssertionError("first loop is not SI<0x10 / CALL 05B9")
    if decode_one(image, cs, 0x04D5).target_ip != 0x0448:
        raise AssertionError("04D5 is not CALL 0448")
    if decode_one(image, cs, 0x04F0).bytes_hex != "83fe10" or decode_one(image, cs, 0x04E9).target_ip != 0x04F9:
        raise AssertionError("second loop is not SI<0x10 / CALL 04F9")
    if decode_one(image, cs, 0x04F8).kind != "RETF":
        raise AssertionError("04F8 is not RETF")
    body, hit = follow_local(image, cs, 0x0490, limit=80)
    if hit:
        raise AssertionError("0490 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0490 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(int(state["body_file"], 16), int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0490 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x04F8:
        raise AssertionError("0490 walk does not end at RETF 04F8")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0490 body is not the owned seed")


def _check_c4c8_04f9(image: bytes, pin: dict) -> None:
    """00A3 and 0490 call 04F9. AX<0x23 returns; otherwise two B13A loops."""
    state = pin["state_c4c8_04f9"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x04F9
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:04F9 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:04F9 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:04F9 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C4C8:04F9 prologue")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:04F9 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x04F9:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 04F9")
    if decode_one(image, cs, 0x0501).bytes_hex != "8b7606" or decode_one(image, cs, 0x0504).bytes_hex != "a0a2d6":
        raise AssertionError("0501 is not MOV SI,[BP+6] / MOV AL,[D6A2]")
    far = decode_one(image, cs, 0x050D)
    if far.kind != "CALLF" or far.target_cs != 0xD9F2 or far.target_ip != 0x000C:
        raise AssertionError("050D is not CALLF D9F2:000C")
    if decode_one(image, cs, 0x0518).bytes_hex != "3d2300" or decode_one(image, cs, 0x051D).target_ip != 0x05B5:
        raise AssertionError("AX<0x23 does not jump to the epilogue")
    far = decode_one(image, cs, 0x0523)
    if far.kind != "CALLF" or far.target_cs != 0xCFC6 or far.target_ip != 0x02D6:
        raise AssertionError("0523 is not CALLF CFC6:02D6")
    if decode_one(image, cs, 0x052D).bytes_hex != "8ec2" or decode_one(image, cs, 0x052F).bytes_hex != "268a07":
        raise AssertionError("052D is not MOV ES,DX / MOV AL,ES:[BX]")
    if decode_one(image, cs, 0x053C).bytes_hex != "f7ea" or decode_one(image, cs, 0x0539).bytes_hex != "ba0f00":
        raise AssertionError("0539 is not IMUL by 0x0F")
    if decode_one(image, cs, 0x0558).bytes_hex != "f7fb" or decode_one(image, cs, 0x0554).bytes_hex != "bb1900":
        raise AssertionError("0554 is not IDIV by 0x19")
    for ip in (0x0571, 0x059E):
        far = decode_one(image, cs, ip)
        if far.kind != "CALLF" or far.target_cs != 0xB13A or far.target_ip != 0:
            raise AssertionError(f"{ip:04X} is not CALLF B13A:0000")
    if decode_one(image, cs, 0x05B8).kind != "RETF":
        raise AssertionError("05B8 is not RETF")
    body, hit = follow_local(image, cs, 0x04F9, limit=120)
    if hit:
        raise AssertionError("04F9 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("04F9 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(int(state["body_file"], 16), int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("04F9 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x05B8:
        raise AssertionError("04F9 walk does not end at RETF 05B8")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:04F9 body is not the owned seed")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_05b9(image: bytes, pin: dict) -> None:
    """00A3 and 0490 call 05B9. AX<0x23 returns; otherwise SI<0x0B calls B13A."""
    state = pin["state_c4c8_05b9"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x05B9
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:05B9 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:05B9 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:05B9 24-bit 0x{phys24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["head_bytes"], "C4C8:05B9 prologue")
    _expect_hex(image, int(state["body_file"], 16) + 0x42, state["buf_bytes"], "C4C8:05B9 word 1591")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:05B9 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x05B9:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 05B9")
    if decode_one(image, cs, 0x05C1).bytes_hex != "8b7606" or decode_one(image, cs, 0x05C4).bytes_hex != "a0a2d6":
        raise AssertionError("05C1 is not MOV SI,[BP+6] / MOV AL,[D6A2]")
    far = decode_one(image, cs, 0x05CD)
    if far.kind != "CALLF" or far.target_cs != 0xD9F2 or far.target_ip != 0x000C:
        raise AssertionError("05CD is not CALLF D9F2:000C")
    if decode_one(image, cs, 0x05D8).bytes_hex != "3d2300" or decode_one(image, cs, 0x05DD).target_ip != 0x0674:
        raise AssertionError("AX<0x23 does not jump to the epilogue")
    far = decode_one(image, cs, 0x05E3)
    if far.kind != "CALLF" or far.target_cs != 0xCFC6 or far.target_ip != 0x02D6:
        raise AssertionError("05E3 is not CALLF CFC6:02D6")
    if decode_one(image, cs, 0x05EF).bytes_hex != "268a4701":
        raise AssertionError("05EF is not MOV AL,ES:[BX+1]")
    if decode_one(image, cs, 0x0605).bytes_hex != "f7ea" or decode_one(image, cs, 0x0602).bytes_hex != "ba0f00":
        raise AssertionError("0602 is not IMUL by 0x0F")
    if decode_one(image, cs, 0x0615).bytes_hex != "f7fb" or decode_one(image, cs, 0x0611).bytes_hex != "bb4300":
        raise AssertionError("0611 is not IDIV by 0x43")
    if decode_one(image, cs, 0x0617).bytes_hex != "d1e0" or decode_one(image, cs, 0x061B).bytes_hex != "8b872914":
        raise AssertionError("0617 is not SHL AX,1 / MOV AX,[BX+1429]")
    if decode_one(image, cs, 0x066F).bytes_hex != "83fe0b" or decode_one(image, cs, 0x0672).target_ip != 0x0627:
        raise AssertionError("loop is not SI<0x0B")
    for ip in (0x0643, 0x0662):
        far = decode_one(image, cs, ip)
        if far.kind != "CALLF" or far.target_cs != 0xB13A or far.target_ip != 0:
            raise AssertionError(f"{ip:04X} is not CALLF B13A:0000")
    if decode_one(image, cs, 0x0677).kind != "RETF":
        raise AssertionError("0677 is not RETF")
    body, hit = follow_local(image, cs, 0x05B9, limit=120)
    if hit:
        raise AssertionError("05B9 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("05B9 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(int(state["body_file"], 16), int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("05B9 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0677:
        raise AssertionError("05B9 walk does not end at RETF 0677")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:05B9 body is not the owned seed")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_0927(image: bytes, pin: dict) -> None:
    """00A3 and 0448 call 0927. SI<3 reads [BX+1425] and calls B13A:0000."""
    state = pin["state_c4c8_0927"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0927
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0927 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0927 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0927 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0927 prologue")
    _expect_hex(image, body_file + 0x0D, state["table_bytes"], "C4C8:0927 [BX+1425]")
    _expect_hex(image, body_file + 0x27, state["buf_bytes"], "C4C8:0927 word 16F9")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0927 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0927:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0927")
    if decode_one(image, cs, 0x092F).bytes_hex != "8b5e06" or decode_one(image, cs, 0x0932).bytes_hex != "d1e3":
        raise AssertionError("092F is not MOV BX,[BP+6] / SHL BX,1")
    if decode_one(image, cs, 0x093E).bytes_hex != "8b4608" or decode_one(image, cs, 0x0946).bytes_hex != "050300":
        raise AssertionError("093E is not [BP+8]*0x0F+3")
    if decode_one(image, cs, 0x0979).bytes_hex != "83fe03" or decode_one(image, cs, 0x097C).target_ip != 0x0955:
        raise AssertionError("loop is not SI<3")
    far = decode_one(image, cs, 0x096C)
    if far.kind != "CALLF" or far.target_cs != 0xB13A or far.target_ip != 0:
        raise AssertionError("096C is not CALLF B13A:0000")
    if decode_one(image, cs, 0x0981).kind != "RETF":
        raise AssertionError("0981 is not RETF")
    body, hit = follow_local(image, cs, 0x0927, limit=80)
    if hit:
        raise AssertionError("0927 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0927 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0927 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0981:
        raise AssertionError("0927 walk does not end at RETF 0981")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0927 body is not the owned seed")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_0982(image: bytes, pin: dict) -> None:
    """0490 calls 0982. Three nested counts call 0FB1 and B13A:0000."""
    state = pin["state_c4c8_0982"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0982
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0982 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0982 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0982 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0982 prologue")
    _expect_hex(image, body_file + 0x15, state["base_bytes"], "C4C8:0982 add 0264")
    _expect_hex(image, body_file + 0x20, state["buf_bytes"], "C4C8:0982 word 1771")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0982 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0982:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0982")
    if decode_one(image, cs, 0x0991).bytes_hex != "8b4606" or decode_one(image, cs, 0x0994).bytes_hex != "c1e002":
        raise AssertionError("0991 is not MOV AX,[BP+6] / SHL AX,2")
    if decode_one(image, cs, 0x09C6).target_ip != 0x0FB1:
        raise AssertionError("09C6 is not CALL 0FB1")
    if decode_one(image, cs, 0x09F8).bytes_hex != "83fe09" or decode_one(image, cs, 0x09FB).target_ip != 0x09D4:
        raise AssertionError("inner loop is not SI<9")
    if decode_one(image, cs, 0x0A04).bytes_hex != "837efc03" or decode_one(image, cs, 0x0A08).target_ip != 0x09BA:
        raise AssertionError("middle loop is not count<3")
    if decode_one(image, cs, 0x0A14).bytes_hex != "837efe10" or decode_one(image, cs, 0x0A18).target_ip != 0x099F:
        raise AssertionError("outer loop is not count<0x10")
    far = decode_one(image, cs, 0x09EB)
    if far.kind != "CALLF" or far.target_cs != 0xB13A or far.target_ip != 0:
        raise AssertionError("09EB is not CALLF B13A:0000")
    if decode_one(image, cs, 0x0A1D).kind != "RETF":
        raise AssertionError("0A1D is not RETF")
    body, hit = follow_local(image, cs, 0x0982, limit=100)
    if hit:
        raise AssertionError("0982 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0982 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0982 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0A1D:
        raise AssertionError("0982 walk does not end at RETF 0A1D")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0982 body is not the owned seed")
    for file_off in (
        int(state["next_file"], 16),
        0x313A0,
    ):
        if not _gap_at(file_off):
            raise AssertionError(f"file 0x{file_off:05X} is owned")


def _check_c4c8_0a99(image: bytes, pin: dict) -> None:
    """0490 calls 0A99 with 0. The body sets bits across 0x40 rows at 1591."""
    state = pin["state_c4c8_0a99"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0A99
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0A99 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0A99 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0A99 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0A99 prologue")
    _expect_hex(image, body_file + 0x0D, state["base_bytes"], "C4C8:0A99 row base")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0A99 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        _expect_hex(image, int(caller["arg_file"], 16), caller["arg_bytes"], caller["cs_ip"] + " argument")
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0A99:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0A99")
    if decode_one(image, cs, 0x0AA1).bytes_hex != "8b5e06" or decode_one(image, cs, 0x0AA6).bytes_hex != "ba1e00":
        raise AssertionError("0AA1 is not MOV BX,[BP+6] / MOV DX,0x1E")
    if decode_one(image, cs, 0x0AAB).bytes_hex != "059115":
        raise AssertionError("0AAB is not ADD AX,0x1591")
    if decode_one(image, cs, 0x0AE6).bytes_hex != "83ff40" or decode_one(image, cs, 0x0AE9).target_ip != 0x0AB8:
        raise AssertionError("outer loop is not DI<0x40")
    if decode_one(image, cs, 0x0ADC).bytes_hex != "83fe0f" or decode_one(image, cs, 0x0ADF).target_ip != 0x0ABF:
        raise AssertionError("inner loop is not SI<0x0F")
    if decode_one(image, cs, 0x0AC1).bytes_hex != "c1e803" or decode_one(image, cs, 0x0AD5).bytes_hex != "260807":
        raise AssertionError("0AC1 is not SHR AX,3 / OR ES:[BX],AL")
    if decode_one(image, cs, 0x0AEE).kind != "RETF":
        raise AssertionError("0AEE is not RETF")
    body, hit = follow_local(image, cs, 0x0A99, limit=80)
    if hit:
        raise AssertionError("0A99 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0A99 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0A99 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0AEE:
        raise AssertionError("0A99 walk does not end at RETF 0AEE")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0A99 body is not the owned seed")


def _check_c4c8_0c64(image: bytes, pin: dict) -> None:
    """00A3 calls 0C64. Both RETFs wait on a DS word after calling 0C35."""
    state = pin["state_c4c8_0c64"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0C64
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0C64 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0C64 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0C64 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0C64 prologue")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0C64 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0C64:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0C64")
    if decode_one(image, cs, 0x0C6C).bytes_hex != "8b7e08" or decode_one(image, cs, 0x0C6F).bytes_hex != "a0a2d6":
        raise AssertionError("0C6C is not MOV DI,[BP+8] / MOV AL,[D6A2]")
    if decode_one(image, cs, 0x0C74).bytes_hex != "c1f804":
        raise AssertionError("0C74 is not SAR AX,4")
    if decode_one(image, cs, 0x0C7A).bytes_hex != "837e0c00" or decode_one(image, cs, 0x0C7E).target_ip != 0x0C9A:
        raise AssertionError("0C7A is not CMP word [BP+0xC],0 / JZ 0C9A")
    for ip in (0x0C89, 0x0CA3):
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0C35:
            raise AssertionError(f"{ip:04X} is not CALL 0C35")
    if decode_one(image, cs, 0x0C90).bytes_hex != "83fe10":
        raise AssertionError("0C90 is not CMP SI,0x10")
    if decode_one(image, cs, 0x0CBA).bytes_hex != "89973897" or decode_one(image, cs, 0x0CBE).bytes_hex != "800e499702":
        raise AssertionError("nonzero DI path does not store [BX+9738] / OR [9749],2")
    if decode_one(image, cs, 0x0CC8).bytes_hex != "83bf389700" or decode_one(image, cs, 0x0CCD).target_ip != 0x0CC3:
        raise AssertionError("0CC8 does not wait on [BX+9738]")
    if decode_one(image, cs, 0x0CD8).bytes_hex != "89974097" or decode_one(image, cs, 0x0CDC).bytes_hex != "800e499701":
        raise AssertionError("zero DI path does not store [BX+9740] / OR [9749],1")
    if decode_one(image, cs, 0x0CE6).bytes_hex != "83bf409700" or decode_one(image, cs, 0x0CEB).target_ip != 0x0CE1:
        raise AssertionError("0CE6 does not wait on [BX+9740]")
    if decode_one(image, cs, 0x0CD2).kind != "RETF" or decode_one(image, cs, 0x0CF0).kind != "RETF":
        raise AssertionError("0CD2 or 0CF0 is not RETF")
    body, hit = follow_local(image, cs, 0x0C64, limit=100)
    if hit:
        raise AssertionError("0C64 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0C64 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0C64 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0CF0:
        raise AssertionError("0C64 walk does not end at RETF 0CF0")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0C64 body is not the owned seed")


def _check_c4c8_0c35(image: bytes, pin: dict) -> None:
    """0C64 calls 0C35 twice. Byte 0x2B selects 0B8F; otherwise 0AEF."""
    state = pin["state_c4c8_0c35"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0C35
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0C35 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0C35 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0C35 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0C35 prologue")
    _expect_hex(image, int(state["body_end"], 16) - 2, state["tail_bytes"], "C4C8:0C35 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0C35:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0C35")
    if decode_one(image, cs, 0x0C38).bytes_hex != "8b4608" or decode_one(image, cs, 0x0C3B).bytes_hex != "8b560a":
        raise AssertionError("0C38 is not MOV AX,[BP+8] / MOV DX,[BP+0xA]")
    if decode_one(image, cs, 0x0C3E).bytes_hex != "807e062b" or decode_one(image, cs, 0x0C42).target_ip != 0x0C54:
        raise AssertionError("0C3E is not CMP byte [BP+6],0x2B / JNZ 0C54")
    if decode_one(image, cs, 0x0C4C).target_ip != 0x0B8F or decode_one(image, cs, 0x0C5C).target_ip != 0x0AEF:
        raise AssertionError("0C35 does not call 0B8F and 0AEF")
    if decode_one(image, cs, 0x0C45).bytes_hex != "a0a2d6" or decode_one(image, cs, 0x0C55).bytes_hex != "a0a2d6":
        raise AssertionError("both paths do not read [D6A2]")
    if decode_one(image, cs, 0x0C53).kind != "RETF" or decode_one(image, cs, 0x0C63).kind != "RETF":
        raise AssertionError("0C53 or 0C63 is not RETF")
    body, hit = follow_local(image, cs, 0x0C35, limit=40)
    if hit:
        raise AssertionError("0C35 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0C35 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0C35 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0C63:
        raise AssertionError("0C35 walk does not end at RETF 0C63")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0C35 body is not the owned seed")


def _check_c4c8_0aef(image: bytes, pin: dict) -> None:
    """0C35 calls 0AEF when the byte is not 0x2B. Zero selects 04F9; else 05B9."""
    state = pin["state_c4c8_0aef"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0AEF
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0AEF file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0AEF is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0AEF 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0AEF prologue")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0AEF epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0AEF:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0AEF")
    if decode_one(image, cs, 0x0AF4).bytes_hex != "8b7e06" or decode_one(image, cs, 0x0AF9).bytes_hex != "037608":
        raise AssertionError("0AF4 is not MOV DI,[BP+6] / ADD SI,[BP+8]")
    if decode_one(image, cs, 0x0AFC).bytes_hex != "837e0a00" or decode_one(image, cs, 0x0B00).target_ip != 0x0B46:
        raise AssertionError("0AFC is not CMP word [BP+0xA],0 / JNZ 0B46")
    if decode_one(image, cs, 0x0B18).bytes_hex != "268a07" or decode_one(image, cs, 0x0B5C).bytes_hex != "268a4701":
        raise AssertionError("paths do not read ES:[BX] and ES:[BX+1]")
    if decode_one(image, cs, 0x0B23).bytes_hex != "a19ad6" or decode_one(image, cs, 0x0B26).bytes_hex != "d1e0":
        raise AssertionError("zero path is not [D69A]<<1")
    if decode_one(image, cs, 0x0B6D).bytes_hex != "03069ad6":
        raise AssertionError("nonzero path is not [D69A]*3")
    if decode_one(image, cs, 0x0B3C).target_ip != 0x04F9 or decode_one(image, cs, 0x0B85).target_ip != 0x05B9:
        raise AssertionError("0AEF does not call 04F9 and 05B9")
    far = decode_one(image, cs, 0x0B32)
    if far.kind != "CALLF" or far.target_cs != 0xD9A2 or far.target_ip != 0x0004:
        raise AssertionError("0B32 is not CALLF D9A2:0004")
    far = decode_one(image, cs, 0x0B7B)
    if far.kind != "CALLF" or far.target_cs != 0xD9A2 or far.target_ip != 0x0031:
        raise AssertionError("0B7B is not CALLF D9A2:0031")
    if decode_one(image, cs, 0x0B45).kind != "RETF" or decode_one(image, cs, 0x0B8E).kind != "RETF":
        raise AssertionError("0B45 or 0B8E is not RETF")
    body, hit = follow_local(image, cs, 0x0AEF, limit=120)
    if hit:
        raise AssertionError("0AEF walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0AEF body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0AEF walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0B8E:
        raise AssertionError("0AEF walk does not end at RETF 0B8E")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0AEF body is not the owned seed")


def _check_c4c8_0b8f(image: bytes, pin: dict) -> None:
    """0C35 calls 0B8F when the byte is 0x2B. DX is raised and clamped at 0x64."""
    state = pin["state_c4c8_0b8f"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0B8F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0B8F file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0B8F is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0B8F 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0B8F prologue")
    _expect_hex(image, body_file + 0x41, state["clamp_bytes"], "C4C8:0B8F clamp")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0B8F epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0B8F:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0B8F")
    if decode_one(image, cs, 0x0B94).bytes_hex != "8b7e06" or decode_one(image, cs, 0x0B99).bytes_hex != "037608":
        raise AssertionError("0B94 is not MOV DI,[BP+6] / ADD SI,[BP+8]")
    if decode_one(image, cs, 0x0B9C).bytes_hex != "837e0a00" or decode_one(image, cs, 0x0BA0).target_ip != 0x0BE9:
        raise AssertionError("0B9C is not CMP word [BP+0xA],0 / JNZ 0BE9")
    if decode_one(image, cs, 0x0BB8).bytes_hex != "268a07" or decode_one(image, cs, 0x0BFF).bytes_hex != "268a4701":
        raise AssertionError("paths do not read ES:[BX] and ES:[BX+1]")
    if decode_one(image, cs, 0x0BBF).bytes_hex != "83fa64" or decode_one(image, cs, 0x0BC2).target_ip != 0x0C31:
        raise AssertionError("zero path does not skip when DX>=0x64")
    if decode_one(image, cs, 0x0BC9).bytes_hex != "03d0" or decode_one(image, cs, 0x0C15).bytes_hex != "03d0":
        raise AssertionError("0B8F does not add the [D69A] term to DX")
    if decode_one(image, cs, 0x0C11).bytes_hex != "03069ad6":
        raise AssertionError("nonzero path is not [D69A]*3")
    if decode_one(image, cs, 0x0BD0).bytes_hex != "ba6400" or decode_one(image, cs, 0x0C1C).bytes_hex != "ba6400":
        raise AssertionError("0B8F does not clamp DX to 0x64")
    if decode_one(image, cs, 0x0BDF).target_ip != 0x04F9 or decode_one(image, cs, 0x0C2B).target_ip != 0x05B9:
        raise AssertionError("0B8F does not call 04F9 and 05B9")
    far = decode_one(image, cs, 0x0BD5)
    if far.kind != "CALLF" or far.target_cs != 0xD9A2 or far.target_ip != 0x0004:
        raise AssertionError("0BD5 is not CALLF D9A2:0004")
    far = decode_one(image, cs, 0x0C21)
    if far.kind != "CALLF" or far.target_cs != 0xD9A2 or far.target_ip != 0x0031:
        raise AssertionError("0C21 is not CALLF D9A2:0031")
    if decode_one(image, cs, 0x0BE8).kind != "RETF" or decode_one(image, cs, 0x0C34).kind != "RETF":
        raise AssertionError("0BE8 or 0C34 is not RETF")
    body, hit = follow_local(image, cs, 0x0B8F, limit=120)
    if hit:
        raise AssertionError("0B8F walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0B8F body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0B8F walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0C34:
        raise AssertionError("0B8F walk does not end at RETF 0C34")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0B8F body is not the owned seed")
    if _gap_at(int(state["body_end"], 16)):
        raise AssertionError("0C35 is not owned at the end of 0B8F")


def _check_c4c8_0ec9(image: bytes, pin: dict) -> None:
    """00A3 and 0448 call 0EC9. SI<3 calls B13A with an immediate 0."""
    state = pin["state_c4c8_0ec9"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0EC9
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0EC9 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0EC9 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0EC9 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0EC9 prologue")
    _expect_hex(image, body_file + 0x18, state["buf_bytes"], "C4C8:0EC9 word 16F9")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0EC9 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0EC9:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0EC9")
    if decode_one(image, cs, 0x0ED1).bytes_hex != "8b4606" or decode_one(image, cs, 0x0ED4).bytes_hex != "ba0f00":
        raise AssertionError("0ED1 is not MOV AX,[BP+6] / MOV DX,0x0F")
    if decode_one(image, cs, 0x0ED9).bytes_hex != "050300":
        raise AssertionError("0ED9 is not ADD AX,3")
    if decode_one(image, cs, 0x0EEE).bytes_hex != "6a00":
        raise AssertionError("0EEE is not PUSH 0")
    if decode_one(image, cs, 0x0F04).bytes_hex != "83fe03" or decode_one(image, cs, 0x0F07).target_ip != 0x0EE8:
        raise AssertionError("loop is not SI<3")
    far = decode_one(image, cs, 0x0EF7)
    if far.kind != "CALLF" or far.target_cs != 0xB13A or far.target_ip != 0:
        raise AssertionError("0EF7 is not CALLF B13A:0000")
    if decode_one(image, cs, 0x0F0C).kind != "RETF":
        raise AssertionError("0F0C is not RETF")
    body, hit = follow_local(image, cs, 0x0EC9, limit=50)
    if hit:
        raise AssertionError("0EC9 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0EC9 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0EC9 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0F0C:
        raise AssertionError("0EC9 walk does not end at RETF 0F0C")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0EC9 body is not the owned seed")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_0f5f(image: bytes, pin: dict) -> None:
    """00A3 and 0490 call 0F5F. It stores 1 at [98DC] and calls 0F99 four times."""
    state = pin["state_c4c8_0f5f"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0F5F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0F5F file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0F5F is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0F5F 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0F5F store")
    _expect_hex(image, int(state["body_end"], 16) - 4, state["tail_bytes"], "C4C8:0F5F epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0F5F:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0F5F")
    pairs = (
        (0x0F64, "6a32", 0x0F66, "6a00", 0x0F6A),
        (0x0F70, "6a07", 0x0F72, "6a01", 0x0F76),
        (0x0F7C, "6a1d", 0x0F7E, "6a02", 0x0F82),
        (0x0F88, "6a3f", 0x0F8A, "6a03", 0x0F8E),
    )
    for first_ip, first_bytes, second_ip, second_bytes, call_ip in pairs:
        if decode_one(image, cs, first_ip).bytes_hex != first_bytes:
            raise AssertionError(f"{first_ip:04X} push mismatch")
        if decode_one(image, cs, second_ip).bytes_hex != second_bytes:
            raise AssertionError(f"{second_ip:04X} push mismatch")
        insn = decode_one(image, cs, call_ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0F99:
            raise AssertionError(f"{call_ip:04X} is not CALL 0F99")
    if decode_one(image, cs, 0x0F95).target_ip != 0x0F0D:
        raise AssertionError("0F95 is not CALL 0F0D")
    if decode_one(image, cs, 0x0F98).kind != "RETF":
        raise AssertionError("0F98 is not RETF")
    body, hit = follow_local(image, cs, 0x0F5F, limit=40)
    if hit:
        raise AssertionError("0F5F walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0F5F body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0F5F walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0F98:
        raise AssertionError("0F5F walk does not end at RETF 0F98")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0F5F body is not the owned seed")
    if _gap_at(int(state["body_end"], 16)):
        raise AssertionError("0F99 is not owned at the end of 0F5F")


def _check_c4c8_0f0d(image: bytes, pin: dict) -> None:
    """0F5F calls 0F0D. The body popcounts 0x780 bytes at [SI+1591]."""
    state = pin["state_c4c8_0f0d"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0F0D
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0F0D file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0F0D is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0F0D 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0F0D prologue")
    _expect_hex(image, body_file + 0x1D, state["walk_bytes"], "C4C8:0F0D [SI+1591]")
    _expect_hex(image, int(state["body_end"], 16) - 2, state["tail_bytes"], "C4C8:0F0D epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0F0D:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0F0D")
    if decode_one(image, cs, 0x0F0E).bytes_hex != "6a00" or decode_one(image, cs, 0x0F10).bytes_hex != "6a0a":
        raise AssertionError("0F0E is not PUSH 0 / PUSH 0x0A")
    if decode_one(image, cs, 0x0F1A).bytes_hex != "6a00" or decode_one(image, cs, 0x0F1C).bytes_hex != "6a0b":
        raise AssertionError("0F1A is not PUSH 0 / PUSH 0x0B")
    for ip in (0x0F14, 0x0F20, 0x0F50):
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0F99:
            raise AssertionError(f"{ip:04X} is not CALL 0F99")
    if decode_one(image, cs, 0x0F2A).bytes_hex != "8a9c9115":
        raise AssertionError("0F2A is not MOV BL,[SI+1591]")
    if decode_one(image, cs, 0x0F42).bytes_hex != "3d0800" or decode_one(image, cs, 0x0F45).target_ip != 0x0F36:
        raise AssertionError("bit loop is not AX<8")
    if decode_one(image, cs, 0x0F57).bytes_hex != "81fe8007" or decode_one(image, cs, 0x0F5B).target_ip != 0x0F28:
        raise AssertionError("outer loop is not SI<0x780")
    if decode_one(image, cs, 0x0F5E).kind != "RETF":
        raise AssertionError("0F5E is not RETF")
    body, hit = follow_local(image, cs, 0x0F0D, limit=60)
    if hit:
        raise AssertionError("0F0D walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0F0D body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0F0D walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0F5E:
        raise AssertionError("0F0D walk does not end at RETF 0F5E")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0F0D body is not the owned seed")
    if _gap_at(int(state["body_end"], 16)):
        raise AssertionError("0F5F is not owned at the end of 0F0D")


def _check_c4c8_0fb1(image: bytes, pin: dict) -> None:
    """0982 calls 0FB1 and keeps DX:AX. The scan matches [BP+6] in [SI+13E5]."""
    state = pin["state_c4c8_0fb1"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0FB1
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0FB1 file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0FB1 is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0FB1 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0FB1 prologue")
    _expect_hex(image, body_file + 0x0B, state["scan_bytes"], "C4C8:0FB1 compare")
    _expect_hex(image, int(state["body_end"], 16) - 3, state["tail_bytes"], "C4C8:0FB1 epilogue")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0FB1:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0FB1")
    if decode_one(image, cs, 0x09CC).bytes_hex != "8956fa" or decode_one(image, cs, 0x09CF).bytes_hex != "8946f8":
        raise AssertionError("0982 does not store DX:AX from 0FB1")
    if decode_one(image, cs, 0x0FB5).bytes_hex != "8a5606" or decode_one(image, cs, 0x0FB8).bytes_hex != "33f6":
        raise AssertionError("0FB5 is not MOV DL,[BP+6] / XOR SI,SI")
    if decode_one(image, cs, 0x0FBC).bytes_hex != "3894e513" or decode_one(image, cs, 0x0FD0).bytes_hex != "80bce51300":
        raise AssertionError("scan is not CMP [SI+13E5],DL / CMP byte [SI+13E5],0")
    if decode_one(image, cs, 0x0FC4).bytes_hex != "d1e3" or decode_one(image, cs, 0x0FC6).bytes_hex != "8b87fb13":
        raise AssertionError("match path is not SHL BX,1 / MOV AX,[BX+13FB]")
    if decode_one(image, cs, 0x0FD7).bytes_hex != "a1fb13" or decode_one(image, cs, 0x0FCA).bytes_hex != "8cda":
        raise AssertionError("return is not AX from 13FB / MOV DX,DS")
    if decode_one(image, cs, 0x0FCE).kind != "RETF" or decode_one(image, cs, 0x0FDE).kind != "RETF":
        raise AssertionError("0FCE or 0FDE is not RETF")
    body, hit = follow_local(image, cs, 0x0FB1, limit=40)
    if hit:
        raise AssertionError("0FB1 walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0FB1 body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0FB1 walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x0FDE:
        raise AssertionError("0FB1 walk does not end at RETF 0FDE")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0FB1 body is not the owned seed")


def _check_c4c8_0fdf(image: bytes, pin: dict) -> None:
    """000D slot 0074 calls 0FDF. One RETF; 0678, 06E1, and 0E5A stay unowned."""
    state = pin["state_c4c8_0fdf"]
    cs = 0xC4C8
    phys20 = (cs << 4) + 0x0FDF
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("C4C8:0FDF file or 20-bit address")
    if (phys20 >> 14) != state["pgr_slot"]:
        raise AssertionError("C4C8:0FDF is not second-PGR slot 49")
    word = _u16(image, int(state["pgr_file"], 16))
    phys24 = (word << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"C4C8:0FDF 24-bit 0x{phys24:06X}")
    body_file = int(state["body_file"], 16)
    _expect_hex(image, body_file, state["head_bytes"], "C4C8:0FDF prologue")
    _expect_hex(image, body_file + 8, state["store_bytes"], "C4C8:0FDF store 0")
    _expect_hex(image, int(state["body_end"], 16) - 1, state["tail_bytes"], "C4C8:0FDF RETF")
    if decode_one(image, cs, 0x0072).bytes_hex != "90" or decode_one(image, cs, 0x0073).bytes_hex != "0e":
        raise AssertionError("slot 0072 is not NOP / PUSH CS")
    for caller in state["callers"]:
        _expect_hex(image, int(caller["file"], 16), caller["bytes"], caller["cs_ip"])
        ip = int(caller["cs_ip"].split(":")[1], 16)
        insn = decode_one(image, cs, ip)
        if insn.kind != "CALLN" or insn.target_ip != 0x0FDF:
            raise AssertionError(f"{caller['cs_ip']} is not CALL 0FDF")
    if decode_one(image, cs, 0x0FE7).bytes_hex != "c606797d00":
        raise AssertionError("0FE7 is not MOV byte [7D79],0")
    far = decode_one(image, cs, 0x0FEC)
    if far.kind != "CALLF" or far.target_cs != 0xB1B1 or far.target_ip != 0x0002:
        raise AssertionError("0FEC is not CALLF B1B1:0002")
    if decode_one(image, cs, 0x102A).target_ip != 0x0678 or decode_one(image, cs, 0x120C).target_ip != 0x06E1:
        raise AssertionError("0FDF does not call 0678 and 06E1")
    if decode_one(image, cs, 0x1248).target_ip != 0x0E5A or decode_one(image, cs, 0x10BD).target_ip != 0x0448:
        raise AssertionError("0FDF does not call 0E5A and 0448")
    if decode_one(image, cs, 0x12A8).kind != "RETF":
        raise AssertionError("12A8 is not RETF")
    body, hit = follow_local(image, cs, 0x0FDF, limit=400)
    if hit:
        raise AssertionError("0FDF walk hit the limit")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("0FDF body contains BRKXA/RETXA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    want = set(range(body_file, int(state["body_end"], 16)))
    if covered != want:
        raise AssertionError("0FDF walk does not match the seed")
    if body[-1].kind != "RETF" or body[-1].ip != 0x12A8:
        raise AssertionError("0FDF walk does not end at RETF 12A8")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0FDF body is not the owned seed")


def _check_c4c8_12a9(image: bytes, pin: dict) -> None:
    """12A9 reached runs; unreached holes stay gaps."""
    state = pin["state_c4c8_12a9"]
    if int(state["phys20"], 16) != 0xC5F29:
        raise AssertionError("C4C8:12A9 phys20 moved")
    if int(state["phys24"], 16) != 0xC5F29:
        raise AssertionError("C4C8:12A9 phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    runs = [(int(a, 16), int(b, 16)) for a, b in state["runs"]]
    if image[runs[0][0]:runs[0][0] + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:12A9 head bytes moved")
    if image[runs[-1][1] - 3:runs[-1][1]].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:12A9 tail bytes moved")
    entry = decode_one(image, 0xC4C8, 0x12B2)
    if entry.kind != "JMPN" or entry.target_ip != 0x180C:
        raise AssertionError("C4C8:12A9 entry jump moved")
    slot = decode_one(image, 0xC4C8, 0x007D)
    if (
        slot.kind != "CALLN"
        or slot.target_ip != 0x12A9
        or slot.file != 0x44CFD
        or slot.bytes_hex != "e82912"
    ):
        raise AssertionError("C4C8:12A9 slot call moved")
    body, hit = follow_local(image, 0xC4C8, 0x12A9, limit=800)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:12A9 walk hit a boundary")
    if body[-1].ip != 0x1817 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:12A9 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    expected = set()
    for start, end in runs:
        expected.update(range(start, end))
    if covered != expected:
        raise AssertionError("C4C8:12A9 reached bytes moved")
    for file_off in (int(x, 16) for x in state["holes"]):
        if not _gap_at(file_off):
            raise AssertionError(f"C4C8:12A9 hole 0x{file_off:05X} is owned")


def _check_c4c8_1b3f(image: bytes, pin: dict) -> None:
    """1B3F is the suffix of the post-12A9 gap through one RETF."""
    state = pin["state_c4c8_1b3f"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC67BF or (0xC67BF & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:1B3F file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC67BF:
        raise AssertionError("C4C8:1B3F phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:1B3F head bytes moved")
    if image[body_end - 3:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:1B3F tail bytes moved")
    if image[int(state["loop_file"], 16):int(state["loop_file"], 16) + 8].hex() != state["loop_bytes"]:
        raise AssertionError("C4C8:1B3F loop bytes moved")
    slot = decode_one(image, 0xC4C8, 0x0086)
    if (
        slot.kind != "CALLN"
        or slot.target_ip != 0x1B3F
        or slot.file != 0x44D06
        or slot.bytes_hex != "e8b61a"
    ):
        raise AssertionError("C4C8:1B3F slot call moved")
    body, hit = follow_local(image, 0xC4C8, 0x1B3F, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:1B3F walk hit a boundary")
    if body[-1].ip != 0x1C3B or body[-1].kind != "RETF":
        raise AssertionError("C4C8:1B3F does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:1B3F walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:1B3F body is not the owned seed")
    if not _gap_at(int(state["prefix_file"], 16)):
        raise AssertionError("C4C8:1B3F prefix is owned")


def _check_c4c8_1dc3(image: bytes, pin: dict) -> None:
    """1DC3 is the prefix of the post-1B3F gap through one RETF."""
    state = pin["state_c4c8_1dc3"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC6A43 or (0xC6A43 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:1DC3 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC6A43:
        raise AssertionError("C4C8:1DC3 phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:1DC3 head bytes moved")
    if image[body_end - 3:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:1DC3 tail bytes moved")
    count = int(state["count_file"], 16)
    if image[count:count + 6].hex() != state["count_bytes"]:
        raise AssertionError("C4C8:1DC3 count bytes moved")
    slot = decode_one(image, 0xC4C8, 0x008F)
    if (
        slot.kind != "CALLN"
        or slot.target_ip != 0x1DC3
        or slot.file != 0x44D0F
        or slot.bytes_hex != "e8311d"
    ):
        raise AssertionError("C4C8:1DC3 slot call moved")
    body, hit = follow_local(image, 0xC4C8, 0x1DC3, limit=400)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:1DC3 walk hit a boundary")
    if body[-1].ip != 0x1FAA or body[-1].kind != "RETF":
        raise AssertionError("C4C8:1DC3 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:1DC3 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:1DC3 body is not the owned seed")
    if not _gap_at(int(state["next_file"], 16)):
        raise AssertionError("C4C8:1FAB is owned")


def _check_c4c8_0678(image: bytes, pin: dict) -> None:
    """0678 zeros 0x3C0 words at 1591 and RETFs. 07A2 and 06E1 stay out."""
    state = pin["state_c4c8_0678"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC52F8 or (0xC52F8 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:0678 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC52F8:
        raise AssertionError("C4C8:0678 phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:0678 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:0678 tail bytes moved")
    stos = int(state["stos_file"], 16)
    if image[stos:stos + 12].hex() != state["stos_bytes"]:
        raise AssertionError("C4C8:0678 store bytes moved")
    for ip, file_off, raw in ((0x102A, 0x45CAA, "e84bf6"), (0x1234, 0x45EB4, "e841f4")):
        call = decode_one(image, 0xC4C8, ip)
        if call.kind != "CALLN" or call.target_ip != 0x0678 or call.file != file_off or call.bytes_hex != raw:
            raise AssertionError(f"C4C8:{ip:04X} is not CALL 0678")
    if decode_one(image, 0xC4C8, 0x06A7).target_ip != 0x07A2:
        raise AssertionError("06A7 is not CALL 07A2")
    if decode_one(image, 0xC4C8, 0x06D1).target_ip != 0x06E1:
        raise AssertionError("06D1 is not CALL 06E1")
    if decode_one(image, 0xC4C8, 0x06AE).bytes_hex != "83fe10":
        raise AssertionError("06AE is not CMP SI,0x10")
    body, hit = follow_local(image, 0xC4C8, 0x0678, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:0678 walk hit a boundary")
    if body[-1].ip != 0x06E0 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:0678 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:0678 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0678 body is not the owned seed")


def _check_c4c8_06e1(image: bytes, pin: dict) -> None:
    """06E1 gates on AX<0x23, then two B13A loops. 07A2 stays out."""
    state = pin["state_c4c8_06e1"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC5361 or (0xC5361 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:06E1 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC5361:
        raise AssertionError("C4C8:06E1 phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:06E1 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:06E1 tail bytes moved")
    gate = int(state["gate_file"], 16)
    if image[gate:gate + 5].hex() != state["gate_bytes"]:
        raise AssertionError("C4C8:06E1 gate bytes moved")
    for ip, file_off, raw in ((0x06D1, 0x45351, "e80d00"), (0x120C, 0x45E8C, "e8d2f4")):
        call = decode_one(image, 0xC4C8, ip)
        if call.kind != "CALLN" or call.target_ip != 0x06E1 or call.file != file_off or call.bytes_hex != raw:
            raise AssertionError(f"C4C8:{ip:04X} is not CALL 06E1")
    far = decode_one(image, 0xC4C8, 0x075A)
    if far.kind != "CALLF" or far.target_cs != 0xB13A or far.target_ip != 0:
        raise AssertionError("075A is not CALLF B13A:0000")
    body, hit = follow_local(image, 0xC4C8, 0x06E1, limit=120)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:06E1 walk hit a boundary")
    if body[-1].ip != 0x07A1 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:06E1 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:06E1 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:06E1 body is not the owned seed")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_07a2(image: bytes, pin: dict) -> None:
    """07A2 reached runs. The indirect-jump hole stays a gap. The 0913 table is data."""
    state = pin["state_c4c8_07a2"]
    if int(state["phys20"], 16) != 0xC5422 or (0xC5422 & 0x7FFFF) != int(state["runs"][0][0], 16):
        raise AssertionError("C4C8:07A2 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC5422:
        raise AssertionError("C4C8:07A2 phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    runs = [(int(a, 16), int(b, 16)) for a, b in state["runs"]]
    if image[runs[0][0]:runs[0][0] + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:07A2 head bytes moved")
    if image[runs[-1][1] - 4:runs[-1][1]].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:07A2 tail bytes moved")
    call = decode_one(image, 0xC4C8, 0x06A7)
    if call.kind != "CALLN" or call.target_ip != 0x07A2 or call.file != 0x45327 or call.bytes_hex != "e8f800":
        raise AssertionError("06A7 is not CALL 07A2")
    gate = decode_one(image, 0xC4C8, 0x07BF)
    if gate.bytes_hex != "3d2300" or decode_one(image, 0xC4C8, 0x07C7).kind != "RETF":
        raise AssertionError("07A2 early return moved")
    indirect = decode_one(image, 0xC4C8, 0x0844)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71309":
        raise AssertionError("0844 is not JMP CS:[BX+0913]")
    body, hit = follow_local(image, 0xC4C8, 0x07A2, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:07A2 walk hit a boundary")
    if body[-1].ip != 0x0912 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:07A2 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    expected = set()
    for start, end in runs:
        expected.update(range(start, end))
    if covered != expected:
        raise AssertionError("C4C8:07A2 reached bytes moved")
    for file_off in (int(x, 16) for x in state["holes"]):
        if not _gap_at(file_off):
            raise AssertionError(f"C4C8:07A2 hole 0x{file_off:05X} is owned")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _linear_cs(image: bytes, cs: int, start_ip: int, end_ip: int) -> dict[int, object]:
    """Sequential decode. Does not follow jumps."""
    ip = start_ip
    seen: dict[int, object] = {}
    while ip < end_ip:
        insn = decode_one(image, cs, ip)
        if insn.length <= 0 or ip + insn.length > end_ip:
            raise AssertionError(f"{cs:04X}:{ip:04X} linear decode leaves the range")
        seen[ip] = insn
        ip += insn.length
    return seen


def _check_c4c8_bx_tables(image: bytes, pin: dict) -> None:
    """Own the four C4C8 word tables. Do not own their slot targets."""
    state = pin["state_c4c8_bx_tables"]
    if state["xa"] != 1 or state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError("C4C8 tables are not second-PGR slot 49 XA=1")
    if _u16(image, int(state["pgr_file"], 16)) != 0x0031:
        raise AssertionError("second PGR slot 49 word moved")
    cs = 0xC4C8
    reg16 = {0: "AX", 1: "CX", 2: "DX", 3: "BX", 4: "SP", 5: "BP", 6: "SI", 7: "DI"}
    owned = {
        (start, end, kind)
        for start, end, owner, kind in ledger_spans(load_ledger())
        if owner == "data"
    }
    for row in state["tables"]:
        table_file = int(row["table_file"], 16)
        table_end = int(row["table_end"], 16)
        disp = int(row["disp"], 16)
        words = row["words"]
        if table_end - table_file != words * 2:
            raise AssertionError(f"C4C8:{disp:04X} table span is not {words} words")
        phys20 = (cs << 4) + disp
        if phys20 != int(row["phys20"], 16) or (phys20 & 0x7FFFF) != table_file:
            raise AssertionError(f"C4C8:{disp:04X} file or 20-bit address")
        if (phys20 >> 14) != 49:
            raise AssertionError(f"C4C8:{disp:04X} is not PGR slot 49")
        phys24 = (0x0031 << 14) | (phys20 & 0x3FFF)
        if phys24 != int(row["phys24"], 16):
            raise AssertionError(f"C4C8:{disp:04X} 24-bit 0x{phys24:06X}")
        _expect_hex(image, table_file, row["table_bytes"], f"C4C8:{disp:04X} table")
        if (table_file, table_end, "jump_table") not in owned:
            raise AssertionError(f"C4C8:{disp:04X} table is not owned data")
        slot_ip = _u16(image, table_file)
        slot_file = ((cs << 4) + slot_ip) & 0x7FFFF
        if slot_file != int(row["slot_file"], 16):
            raise AssertionError(f"C4C8:{disp:04X} slot file moved")
        if row["slot_gap"] and not _gap_at(slot_file):
            raise AssertionError(f"C4C8:{disp:04X} slot 0x{slot_ip:04X} is not still a gap")
        after = int(row["after_file"], 16)
        if after != table_end or _gap_at(after) != row["after_gap"]:
            raise AssertionError(f"C4C8:{disp:04X} byte after the table changed")
        cmp_ip = next(int(op["ip"], 16) for op in row["ops"] if op["bytes"].startswith("83fb"))
        cmp_file = ((cs << 4) + cmp_ip) & 0x7FFFF
        jmp_file = ((cs << 4) + int(row["consumer_ip"], 16)) & 0x7FFFF
        code = None
        for rec in load_ledger()["ranges"]:
            start, end = int(rec["start"], 16), int(rec["end"], 16)
            if rec["owner"] == "code" and start <= cmp_file < end and start <= jmp_file < end:
                code = (start, end, rec["why"])
                break
        if code is None:
            raise AssertionError(f"C4C8:{disp:04X} compare or JMP is not in owned code")
        why_cs = int(code[2].split(":", 1)[0].split()[-1], 16)
        if why_cs != cs:
            raise AssertionError(f"C4C8:{disp:04X} range CS is not the first name in why")
        base = (cs << 4) & 0x7FFFF
        seen = _linear_cs(image, cs, code[0] - base, code[1] - base)
        bound = None
        for op in row["ops"]:
            ip = int(op["ip"], 16)
            insn = seen.get(ip)
            if insn is None or insn.bytes_hex != op["bytes"]:
                raise AssertionError(f"C4C8:{ip:04X} is not in the linear decode")
            raw = bytes.fromhex(op["bytes"])
            if raw[0] == 0x8B:
                modrm = raw[1]
                if (modrm >> 6) != 3 or reg16[(modrm >> 3) & 7] != "BX":
                    raise AssertionError(f"C4C8:{ip:04X} does not write BX")
            elif raw[0] == 0x83 and raw[1] == 0xEB:
                if raw[2] != 0x75 or ((raw[1] >> 3) & 7) != 5:
                    raise AssertionError(f"C4C8:{ip:04X} is not SUB BX, imm8 0x75")
            elif raw[0] == 0x83 and raw[1] == 0xFB:
                if len(raw) != 3 or ((raw[1] >> 3) & 7) != 7:
                    raise AssertionError(f"C4C8:{ip:04X} is not CMP BX, imm8")
                bound = raw[2]
            elif raw[0] == 0x76:
                if insn.target_ip != int(op["target"], 16):
                    raise AssertionError(f"C4C8:{ip:04X} JBE target moved")
            elif raw[0] == 0x77:
                if insn.target_ip != int(op["target"], 16) or (ip + 2) & 0xFFFF == insn.target_ip:
                    raise AssertionError(f"C4C8:{ip:04X} JA does not leave the table path")
            elif raw[0] == 0xD1:
                if raw[1] != 0xE3 or ((raw[1] >> 3) & 7) != 4:
                    raise AssertionError(f"C4C8:{ip:04X} is not SHL BX,1")
            elif raw[0] == 0x2E:
                got = raw[3] | (raw[4] << 8)
                if raw[1:3] != bytes.fromhex("ffa7") or got != disp:
                    raise AssertionError(f"C4C8:{ip:04X} is not JMP CS:[BX+{disp:04X}]")
            else:
                raise AssertionError(f"C4C8:{ip:04X} opcode is not part of the switch")
        if bound is None or words != bound + 1:
            raise AssertionError(f"C4C8:{disp:04X} word count is not the compare bound")
        jcc = next(op for op in row["ops"] if op["bytes"][:2] in ("76", "77"))
        shl = next(op for op in row["ops"] if op["bytes"] == "d1e3")
        if jcc["bytes"].startswith("76") and int(jcc["target"], 16) != int(shl["ip"], 16):
            raise AssertionError(f"C4C8:{disp:04X} JBE does not reach SHL BX,1")
        if jcc["bytes"].startswith("77") and (int(jcc["ip"], 16) + 2) & 0xFFFF != int(shl["ip"], 16):
            raise AssertionError(f"C4C8:{disp:04X} JA fallthrough is not SHL BX,1")


def _check_c4c8_08cf(image: bytes, pin: dict) -> None:
    """0913 slot BX==9. One contiguous walk meets owned 08D4 and RETF."""
    state = pin["state_c4c8_08cf"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    phys20 = (cs << 4) + 0x08CF
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:08CF file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:08CF is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:08CF 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:08CF bytes moved")
    mov = decode_one(image, cs, 0x08CF)
    jmp = decode_one(image, cs, 0x08D2)
    if mov.bytes_hex != "be0f00" or jmp.kind != "JMPS" or jmp.target_ip != 0x08D4 or jmp.file + jmp.length != join:
        raise AssertionError("08CF is not MOV SI,0x000F / JMPS 08D4")
    movbx = decode_one(image, cs, 0x0838)
    cmpbx = decode_one(image, cs, 0x083A)
    jbe = decode_one(image, cs, 0x083D)
    shl = decode_one(image, cs, 0x0842)
    indirect = decode_one(image, cs, 0x0844)
    modrm = bytes.fromhex(movbx.bytes_hex)[1]
    if movbx.bytes_hex != "8bde" or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 3 or (modrm & 7) != 6:
        raise AssertionError("0838 does not write BX from SI")
    raw_cmp = bytes.fromhex(cmpbx.bytes_hex)
    if raw_cmp != bytes.fromhex("83fb09") or ((raw_cmp[1] >> 3) & 7) != 7 or (raw_cmp[1] & 7) != 3:
        raise AssertionError("083A is not CMP BX, imm8 +9")
    if jbe.bytes_hex != "7603" or jbe.kind != "JCC" or jbe.target_ip != 0x0842:
        raise AssertionError("083D JBE does not reach SHL BX,1 when unsigned <=")
    if shl.bytes_hex != "d1e3" or ((bytes.fromhex(shl.bytes_hex)[1] >> 3) & 7) != 4:
        raise AssertionError("0842 is not SHL BX,1")
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71309":
        raise AssertionError("0844 is not JMP CS:[BX+0913]")
    if _u16(image, 0x45593 + 9 * 2) != 0x08CF:
        raise AssertionError("0913 word 9 is not 08CF")
    body, hit = follow_local(image, cs, 0x08CF, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:08CF walk hit a boundary")
    if body[-1].ip != 0x0912 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:08CF does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, join_end)) or join != body_end:
        raise AssertionError("C4C8:08CF walk is not one contiguous body through owned 08D4")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
    if not owned or not meets:
        raise AssertionError("C4C8:08CF seed does not meet owned 08D4")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_0849(image: bytes, pin: dict) -> None:
    """0913 slot BX==0. First run is MOV SI,0x0010 / JMP 08D4. The later run stays out."""
    state = pin["state_c4c8_0849"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    phys20 = (cs << 4) + 0x0849
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:0849 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:0849 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:0849 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:0849 bytes moved")
    mov = decode_one(image, cs, 0x0849)
    jmp = decode_one(image, cs, 0x084C)
    raw_mov = bytes.fromhex(mov.bytes_hex)
    if raw_mov != bytes.fromhex("be1000") or raw_mov[0] != 0xB8 + 6:
        raise AssertionError("0849 is not MOV SI, imm16")
    if (raw_mov[1] | (raw_mov[2] << 8)) != 0x0010:
        raise AssertionError("0849 immediate is not imm16 0x0010")
    raw_jmp = bytes.fromhex(jmp.bytes_hex)
    if raw_jmp[0] != 0xE9 or jmp.kind != "JMPN" or len(raw_jmp) != 3:
        raise AssertionError("084C is not a near JMP")
    rel = raw_jmp[1] | (raw_jmp[2] << 8)
    if rel >= 0x8000:
        rel -= 0x10000
    if rel != 0x0085 or jmp.target_ip != 0x08D4 or jmp.file + jmp.length != body_end:
        raise AssertionError("084C disp16 is not +0x0085 to 08D4")
    if ((cs << 4) + jmp.target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 08D4 file moved")
    if _u16(image, 0x45593) != 0x0849:
        raise AssertionError("0913 word 0 is not 0849")
    body, hit = follow_local(image, cs, 0x0849, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:0849 walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) < 2:
        raise AssertionError("C4C8:0849 is one run")
    first = runs[0]
    if [insn.ip for insn in first] != [0x0849, 0x084C]:
        raise AssertionError("C4C8:0849 first run is not MOV SI / JMP 08D4")
    if first[-1].kind != "JMPN" or first[-1].target_ip != 0x08D4:
        raise AssertionError("C4C8:0849 first run does not jump into owned 08D4")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:0849 first run is not a contiguous span")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:0849 first run contains BRKXA/RETXA")
    if runs[1][0].file != join or runs[1][-1].kind != "RETF" or runs[1][-1].ip != 0x0912:
        raise AssertionError("C4C8:0849 later run is not owned 08D4 through RETF")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
    if not owned or not meets:
        raise AssertionError("C4C8:0849 seed does not meet owned 08D4")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_c4c8_084f(image: bytes, pin: dict) -> None:
    """0913 slot BX==1. Sixteen-byte first run jumps to owned 08D4."""
    state = pin["state_c4c8_084f"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    phys20 = (cs << 4) + 0x084F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:084F file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:084F is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:084F 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:084F bytes moved")
    raw = image[body_file:body_end]
    if len(raw) != 16 or raw[0] != 0x0B:
        raise AssertionError("084F is not OR r16, r/m16")
    modrm = raw[1]
    if (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 7 or (modrm & 7) != 7:
        raise AssertionError("084F does not OR DI, DI")
    if raw[2] != 0x74 or raw[3] >= 0x80 or raw[3] != 0x05:
        raise AssertionError("0851 is not JZ rel8 +5")
    if (0x0853 + raw[3]) & 0xFFFF != 0x0858:
        raise AssertionError("0851 target is not 0858")
    if raw[4] != 0xB8 or (raw[5] | (raw[6] << 8)) != 0x0011:
        raise AssertionError("0853 is not MOV AX, imm16 0x0011")
    if raw[7] != 0xEB or raw[8] >= 0x80 or raw[8] != 0x03:
        raise AssertionError("0856 rel8 is not +3")
    if (0x0858 + raw[8]) & 0xFFFF != 0x085B:
        raise AssertionError("0856 target is not 085B")
    if raw[9] != 0xB8 or (raw[10] | (raw[11] << 8)) != 0x0002:
        raise AssertionError("0858 is not MOV AX, imm16 0x0002")
    modrm = raw[13]
    if raw[12] != 0x8B or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 6 or (modrm & 7) != 0:
        raise AssertionError("085B is not MOV SI, AX")
    if raw[14] != 0xEB or raw[15] >= 0x80 or raw[15] != 0x75:
        raise AssertionError("085D rel8 is not +0x75")
    if (0x085F + raw[15]) & 0xFFFF != 0x08D4:
        raise AssertionError("085D target is not 08D4")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:084F first run contains BRKXA/RETXA")
    if _u16(image, 0x45595) != 0x084F:
        raise AssertionError("0913 word 1 is not 084F")
    indirect = decode_one(image, cs, 0x0844)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71309":
        raise AssertionError("0844 is not JMP CS:[BX+0913]")
    body, hit = follow_local(image, cs, 0x084F, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:084F walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    first = next(run for run in runs if run[0].ip == 0x084F)
    if [insn.ip for insn in first] != [0x084F, 0x0851, 0x0853, 0x0856, 0x0858, 0x085B, 0x085D]:
        raise AssertionError("C4C8:084F first run is not the sixteen-byte body")
    if first[1].kind != "JCC" or first[1].target_ip != 0x0858:
        raise AssertionError("0851 does not JZ to 0858")
    if first[3].kind != "JMPS" or first[3].target_ip != 0x085B:
        raise AssertionError("0856 does not jump to 085B")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x08D4:
        raise AssertionError("C4C8:084F first run does not jump into owned 08D4")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:084F first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "RETF" or later[-1].ip != 0x0912:
        raise AssertionError("C4C8:084F later run is not owned 08D4 through RETF")
    if later[-1].file + later[-1].length != join_end:
        raise AssertionError("C4C8:084F later run does not end at the owned span")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 08D4 file moved")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
    if not owned or not meets:
        raise AssertionError("C4C8:084F seed does not meet owned 08D4")
    if join in covered:
        raise AssertionError("C4C8:084F seed entered 08D4")
    if not _gap_at(0x4611B) or not _gap_at(0x313A0):
        raise AssertionError("149B or B13A:0000 is owned")


def _check_c4c8_085f(image: bytes, pin: dict) -> None:
    """0913 slot BX==2. Sixteen-byte first run jumps to owned 08D4."""
    state = pin["state_c4c8_085f"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    phys20 = (cs << 4) + 0x085F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:085F file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:085F is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:085F 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:085F bytes moved")
    raw = image[body_file:body_end]
    if len(raw) != 16 or raw[0] != 0x0B:
        raise AssertionError("085F is not OR r16, r/m16")
    modrm = raw[1]
    if (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 7 or (modrm & 7) != 7:
        raise AssertionError("085F does not OR DI, DI")
    if raw[2] != 0x74 or raw[3] >= 0x80 or raw[3] != 0x05:
        raise AssertionError("0861 is not JZ rel8 +5")
    if (0x0863 + raw[3]) & 0xFFFF != 0x0868:
        raise AssertionError("0861 target is not 0868")
    if raw[4] != 0xB8 or (raw[5] | (raw[6] << 8)) != 0x0011:
        raise AssertionError("0863 is not MOV AX, imm16 0x0011")
    if raw[7] != 0xEB or raw[8] >= 0x80 or raw[8] != 0x03:
        raise AssertionError("0866 rel8 is not +3")
    if (0x0868 + raw[8]) & 0xFFFF != 0x086B:
        raise AssertionError("0866 target is not 086B")
    if raw[9] != 0xB8 or (raw[10] | (raw[11] << 8)) != 0x0003:
        raise AssertionError("0868 is not MOV AX, imm16 0x0003")
    modrm = raw[13]
    if raw[12] != 0x8B or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 6 or (modrm & 7) != 0:
        raise AssertionError("086B is not MOV SI, AX")
    if raw[14] != 0xEB or raw[15] >= 0x80 or raw[15] != 0x65:
        raise AssertionError("086D rel8 is not +0x65")
    if (0x086F + raw[15]) & 0xFFFF != 0x08D4:
        raise AssertionError("086D target is not 08D4")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:085F first run contains BRKXA/RETXA")
    if _u16(image, 0x45597) != 0x085F:
        raise AssertionError("0913 word 2 is not 085F")
    indirect = decode_one(image, cs, 0x0844)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71309":
        raise AssertionError("0844 is not JMP CS:[BX+0913]")
    body, hit = follow_local(image, cs, 0x085F, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:085F walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    first = next(run for run in runs if run[0].ip == 0x085F)
    if [insn.ip for insn in first] != [0x085F, 0x0861, 0x0863, 0x0866, 0x0868, 0x086B, 0x086D]:
        raise AssertionError("C4C8:085F first run is not the sixteen-byte body")
    if first[1].kind != "JCC" or first[1].target_ip != 0x0868:
        raise AssertionError("0861 does not JZ to 0868")
    if first[3].kind != "JMPS" or first[3].target_ip != 0x086B:
        raise AssertionError("0866 does not jump to 086B")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x08D4:
        raise AssertionError("C4C8:085F first run does not jump into owned 08D4")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:085F first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "RETF" or later[-1].ip != 0x0912:
        raise AssertionError("C4C8:085F later run is not owned 08D4 through RETF")
    if later[-1].file + later[-1].length != join_end:
        raise AssertionError("C4C8:085F later run does not end at the owned span")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 08D4 file moved")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
    if not owned or not meets:
        raise AssertionError("C4C8:085F seed does not meet owned 08D4")
    if join in covered:
        raise AssertionError("C4C8:085F seed entered 08D4")
    if not _gap_at(0x4611B) or not _gap_at(0x313A0):
        raise AssertionError("149B or B13A:0000 is owned")


def _check_c4c8_086f(image: bytes, pin: dict) -> None:
    """0913 slot BX==3. Sixteen-byte first run jumps to owned 08D4."""
    state = pin["state_c4c8_086f"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    phys20 = (cs << 4) + 0x086F
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:086F file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:086F is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:086F 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:086F bytes moved")
    raw = image[body_file:body_end]
    if len(raw) != 16 or raw[0] != 0x0B:
        raise AssertionError("086F is not OR r16, r/m16")
    modrm = raw[1]
    if (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 7 or (modrm & 7) != 7:
        raise AssertionError("086F does not OR DI, DI")
    if raw[2] != 0x74 or raw[3] >= 0x80 or raw[3] != 0x05:
        raise AssertionError("0871 is not JZ rel8 +5")
    if (0x0873 + raw[3]) & 0xFFFF != 0x0878:
        raise AssertionError("0871 target is not 0878")
    if raw[4] != 0xB8 or (raw[5] | (raw[6] << 8)) != 0x0012:
        raise AssertionError("0873 is not MOV AX, imm16 0x0012")
    if raw[7] != 0xEB or raw[8] >= 0x80 or raw[8] != 0x03:
        raise AssertionError("0876 rel8 is not +3")
    if (0x0878 + raw[8]) & 0xFFFF != 0x087B:
        raise AssertionError("0876 target is not 087B")
    if raw[9] != 0xB8 or (raw[10] | (raw[11] << 8)) != 0x0004:
        raise AssertionError("0878 is not MOV AX, imm16 0x0004")
    modrm = raw[13]
    if raw[12] != 0x8B or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 6 or (modrm & 7) != 0:
        raise AssertionError("087B is not MOV SI, AX")
    if raw[14] != 0xEB or raw[15] >= 0x80 or raw[15] != 0x55:
        raise AssertionError("087D rel8 is not +0x55")
    if (0x087F + raw[15]) & 0xFFFF != 0x08D4:
        raise AssertionError("087D target is not 08D4")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:086F first run contains BRKXA/RETXA")
    if _u16(image, 0x45599) != 0x086F:
        raise AssertionError("0913 word 3 is not 086F")
    indirect = decode_one(image, cs, 0x0844)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71309":
        raise AssertionError("0844 is not JMP CS:[BX+0913]")
    body, hit = follow_local(image, cs, 0x086F, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:086F walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    first = next(run for run in runs if run[0].ip == 0x086F)
    if [insn.ip for insn in first] != [0x086F, 0x0871, 0x0873, 0x0876, 0x0878, 0x087B, 0x087D]:
        raise AssertionError("C4C8:086F first run is not the sixteen-byte body")
    if first[1].kind != "JCC" or first[1].target_ip != 0x0878:
        raise AssertionError("0871 does not JZ to 0878")
    if first[3].kind != "JMPS" or first[3].target_ip != 0x087B:
        raise AssertionError("0876 does not jump to 087B")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x08D4:
        raise AssertionError("C4C8:086F first run does not jump into owned 08D4")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:086F first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "RETF" or later[-1].ip != 0x0912:
        raise AssertionError("C4C8:086F later run is not owned 08D4 through RETF")
    if later[-1].file + later[-1].length != join_end:
        raise AssertionError("C4C8:086F later run does not end at the owned span")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 08D4 file moved")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
    if not owned or not meets:
        raise AssertionError("C4C8:086F seed does not meet owned 08D4")
    if join in covered:
        raise AssertionError("C4C8:086F seed entered 08D4")
    if not _gap_at(0x4611B) or not _gap_at(0x313A0):
        raise AssertionError("149B or B13A:0000 is owned")


def _check_c4c8_0913_or_di_slots(image: bytes, pin: dict) -> None:
    """0913 slots BX==4..8. Each sixteen-byte first run jumps to owned 08D4."""
    state = pin["state_c4c8_0913_or_di_slots"]
    cs = 0xC4C8
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError("second PGR slot 49 word moved")
    indirect = decode_one(image, cs, 0x0844)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71309":
        raise AssertionError("0844 is not JMP CS:[BX+0913]")
    for slot in state["slots"]:
        ip = int(slot["ip"], 16)
        bx = slot["bx"]
        body_file = int(slot["body_file"], 16)
        body_end = int(slot["body_end"], 16)
        other_imm = int(slot["other_imm16"], 16)
        jz_imm = int(slot["jz_imm16"], 16)
        jz_target = int(slot["jz_target_ip"], 16)
        jmps_target = int(slot["jmps_target_ip"], 16)
        phys20 = (cs << 4) + ip
        if phys20 != int(slot["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
            raise AssertionError(f"C4C8:{ip:04X} file or 20-bit address")
        if (phys20 >> 14) != 49:
            raise AssertionError(f"C4C8:{ip:04X} is not PGR slot 49")
        phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
        if phys24 != int(slot["phys24_second_pgr"], 16):
            raise AssertionError(f"C4C8:{ip:04X} 24-bit 0x{phys24:06X}")
        if image[body_file:body_end].hex() != slot["body_bytes"]:
            raise AssertionError(f"C4C8:{ip:04X} bytes moved")
        raw = image[body_file:body_end]
        if len(raw) != 16 or raw[0] != 0x0B:
            raise AssertionError(f"{ip:04X} is not OR r16, r/m16")
        modrm = raw[1]
        if (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 7 or (modrm & 7) != 7:
            raise AssertionError(f"{ip:04X} does not OR DI, DI")
        if raw[2] != 0x74 or raw[3] >= 0x80 or raw[3] != 0x05:
            raise AssertionError(f"{ip + 2:04X} is not JZ rel8 +5")
        if (ip + 4 + raw[3]) & 0xFFFF != jz_target:
            raise AssertionError(f"{ip + 2:04X} JZ target is not {jz_target:04X}")
        if raw[4] != 0xB8 or (raw[5] | (raw[6] << 8)) != other_imm:
            raise AssertionError(f"{ip + 4:04X} other path is not MOV AX, imm16 0x{other_imm:04X}")
        if raw[7] != 0xEB or raw[8] >= 0x80 or raw[8] != 0x03:
            raise AssertionError(f"{ip + 7:04X} rel8 is not +3")
        if (ip + 9 + raw[8]) & 0xFFFF != ip + 12:
            raise AssertionError(f"{ip + 7:04X} target is not {ip + 12:04X}")
        if raw[9] != 0xB8 or (raw[10] | (raw[11] << 8)) != jz_imm:
            raise AssertionError(f"{jz_target:04X} JZ path is not MOV AX, imm16 0x{jz_imm:04X}")
        modrm = raw[13]
        if raw[12] != 0x8B or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 6 or (modrm & 7) != 0:
            raise AssertionError(f"{ip + 12:04X} is not MOV SI, AX")
        if raw[14] != 0xEB or raw[15] >= 0x80:
            raise AssertionError(f"{ip + 14:04X} is not JMPS rel8")
        if (ip + 16 + raw[15]) & 0xFFFF != jmps_target:
            raise AssertionError(f"{ip + 14:04X} target is not {jmps_target:04X}")
        if jmps_target != 0x08D4:
            raise AssertionError(f"C4C8:{ip:04X} final JMPS is not 08D4")
        if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
            raise AssertionError(f"C4C8:{ip:04X} first run contains BRKXA/RETXA")
        if _u16(image, 0x45593 + bx * 2) != ip:
            raise AssertionError(f"0913 word {bx} is not {ip:04X}")
        if int(slot["word_file"], 16) != 0x45593 + bx * 2:
            raise AssertionError(f"C4C8:{ip:04X} word file moved")
        body, hit = follow_local(image, cs, ip, limit=80)
        if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
            raise AssertionError(f"C4C8:{ip:04X} walk hit a boundary")
        ordered = sorted(body, key=lambda insn: insn.file)
        runs: list[list] = [[ordered[0]]]
        for insn in ordered[1:]:
            prev = runs[-1][-1]
            if insn.file == prev.file + prev.length:
                runs[-1].append(insn)
            else:
                runs.append([insn])
        first = next(run for run in runs if run[0].ip == ip)
        expected_ips = [ip, ip + 2, ip + 4, ip + 7, ip + 9, ip + 12, ip + 14]
        if [insn.ip for insn in first] != expected_ips:
            raise AssertionError(f"C4C8:{ip:04X} first run is not the sixteen-byte body")
        if first[1].kind != "JCC" or first[1].target_ip != jz_target:
            raise AssertionError(f"{ip + 2:04X} does not JZ to {jz_target:04X}")
        if first[3].kind != "JMPS" or first[3].target_ip != ip + 12:
            raise AssertionError(f"{ip + 7:04X} does not jump to {ip + 12:04X}")
        if first[-1].kind != "JMPS" or first[-1].target_ip != 0x08D4:
            raise AssertionError(f"C4C8:{ip:04X} first run does not jump into owned 08D4")
        covered = set()
        for insn in first:
            covered.update(range(insn.file, insn.file + insn.length))
        if covered != set(range(body_file, body_end)):
            raise AssertionError(f"C4C8:{ip:04X} first run is not a contiguous span")
        later = next(run for run in runs if run[0].file == join)
        if later[-1].kind != "RETF" or later[-1].ip != 0x0912:
            raise AssertionError(f"C4C8:{ip:04X} later run is not owned 08D4 through RETF")
        if later[-1].file + later[-1].length != join_end:
            raise AssertionError(f"C4C8:{ip:04X} later run does not end at the owned span")
        if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
            raise AssertionError("JMP 08D4 file moved")
        owned = False
        meets = False
        for start, end, owner, _kind in ledger_spans(load_ledger()):
            if start == body_file and end == body_end and owner == "code":
                owned = True
            if start == join and end == join_end and owner == "code":
                meets = True
        if not owned or not meets:
            raise AssertionError(f"C4C8:{ip:04X} seed does not meet owned 08D4")
        if join in covered:
            raise AssertionError(f"C4C8:{ip:04X} seed entered 08D4")
    if not _gap_at(0x4611B) or not _gap_at(0x4646D) or not _gap_at(0x313A0):
        raise AssertionError("149B, 17ED, or B13A:0000 is owned")
    if not _gap_at(0x4921C) or not _gap_at(0x3979B):
        raise AssertionError("C887:09AC or B77C:1FDB is owned")


def _check_c4c8_17f6(image: bytes, pin: dict) -> None:
    """1818 slot BX==4. Entry run is eight bytes and jumps to owned 180C."""
    state = pin["state_c4c8_17f6"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    phys20 = (cs << 4) + 0x17F6
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:17F6 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:17F6 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:17F6 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:17F6 bytes moved")
    raw = image[body_file:body_end]
    if raw[0] != 0x0E or len(raw) != 8:
        raise AssertionError("17F6 is not PUSH CS")
    if raw[1] != 0xE8:
        raise AssertionError("17F7 is not a near CALL")
    rel = raw[2] | (raw[3] << 8)
    if rel < 0x8000:
        raise AssertionError("17F7 disp16 is not negative")
    rel -= 0x10000
    if rel != -0x551 or (0x17FA + rel) & 0xFFFF != 0x12A9:
        raise AssertionError("17F7 disp16 is not -0x0551 to 12A9")
    modrm = raw[5]
    if raw[4] != 0x8B or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 2 or (modrm & 7) != 0:
        raise AssertionError("17FA does not write DX from AX")
    if raw[6] != 0xEB or raw[7] >= 0x80 or raw[7] != 0x0E:
        raise AssertionError("17FC rel8 is not +14")
    if (0x17FE + raw[7]) & 0xFFFF != 0x180C:
        raise AssertionError("17FC target is not 180C")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:17F6 first run contains BRKXA/RETXA")
    if _u16(image, 0x464A0) != 0x17F6:
        raise AssertionError("1818 word 4 is not 17F6")
    indirect = decode_one(image, cs, 0x17E8)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71818":
        raise AssertionError("17E8 is not JMP CS:[BX+1818]")
    body, hit = follow_local(image, cs, 0x17F6, limit=800)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:17F6 walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) < 2:
        raise AssertionError("C4C8:17F6 is one run")
    first = next(run for run in runs if run[0].ip == 0x17F6)
    if [insn.ip for insn in first] != [0x17F6, 0x17F7, 0x17FA, 0x17FC]:
        raise AssertionError("C4C8:17F6 first run is not PUSH CS / CALL / MOV DX,AX / JMPS")
    if first[1].kind != "CALLN" or first[1].target_ip != 0x12A9:
        raise AssertionError("17F7 does not CALL 12A9")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x180C:
        raise AssertionError("C4C8:17F6 first run does not jump into owned 180C")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:17F6 first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "RETF" or later[-1].ip != 0x1817:
        raise AssertionError("C4C8:17F6 later run is not owned 180C through RETF")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 180C file moved")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
    if not owned or not meets:
        raise AssertionError("C4C8:17F6 seed does not meet owned 180C")
    if not _gap_at(0x4646D) or not _gap_at(0x313A0):
        raise AssertionError("17ED or B13A:0000 is owned")


def _check_c4c8_17fe(image: bytes, pin: dict) -> None:
    """1818 slot BX==5. Entry run is eight bytes and jumps to owned 180C."""
    state = pin["state_c4c8_17fe"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    callee = int(state["callee_file"], 16)
    phys20 = (cs << 4) + 0x17FE
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:17FE file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:17FE is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:17FE 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:17FE bytes moved")
    raw = image[body_file:body_end]
    if raw[0] != 0x0E or len(raw) != 8 or b"\x00" in raw:
        raise AssertionError("17FE is not PUSH CS, or the run contains 0")
    if raw[1] != 0xE8:
        raise AssertionError("17FF is not a near CALL")
    rel = raw[2] | (raw[3] << 8)
    if rel < 0x8000:
        raise AssertionError("17FF disp16 is not negative")
    rel -= 0x10000
    if rel != -0x559 or (0x1802 + rel) & 0xFFFF != 0x12A9:
        raise AssertionError("17FF disp16 is not -0x0559 to 12A9")
    modrm = raw[5]
    if raw[4] != 0x8B or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 2 or (modrm & 7) != 0:
        raise AssertionError("1802 does not write DX from AX")
    if raw[6] != 0xEB or raw[7] >= 0x80 or raw[7] != 0x06:
        raise AssertionError("1804 rel8 is not +6")
    if (0x1806 + raw[7]) & 0xFFFF != 0x180C:
        raise AssertionError("1804 target is not 180C")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:17FE first run contains BRKXA/RETXA")
    if _u16(image, 0x464A2) != 0x17FE:
        raise AssertionError("1818 word 5 is not 17FE")
    indirect = decode_one(image, cs, 0x17E8)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa71818":
        raise AssertionError("17E8 is not JMP CS:[BX+1818]")
    body, hit = follow_local(image, cs, 0x17FE, limit=800)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:17FE walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) < 2:
        raise AssertionError("C4C8:17FE is one run")
    first = next(run for run in runs if run[0].ip == 0x17FE)
    if [insn.ip for insn in first] != [0x17FE, 0x17FF, 0x1802, 0x1804]:
        raise AssertionError("C4C8:17FE first run is not PUSH CS / CALL / MOV DX,AX / JMPS")
    if first[1].kind != "CALLN" or first[1].target_ip != 0x12A9:
        raise AssertionError("17FF does not CALL 12A9")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x180C:
        raise AssertionError("C4C8:17FE first run does not jump into owned 180C")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:17FE first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "RETF" or later[-1].ip != 0x1817:
        raise AssertionError("C4C8:17FE later run is not owned 180C through RETF")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 180C file moved")
    if ((cs << 4) + 0x12A9) & 0x7FFFF != callee:
        raise AssertionError("CALL 12A9 file moved")
    owned = False
    meets = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
        if start <= callee < end and owner == "code":
            callee_owned = True
    if not owned or not meets or not callee_owned:
        raise AssertionError("C4C8:17FE seed does not meet owned 180C")
    if callee in covered:
        raise AssertionError("C4C8:17FE seed entered 12A9")
    if not _gap_at(0x46486) or not _gap_at(0x4646D) or not _gap_at(0x313A0):
        raise AssertionError("1806, 17ED, or B13A:0000 is owned")


def _check_c4c8_14a9(image: bytes, pin: dict) -> None:
    """1850 slots BX==2 and BX==3. Entry run is fourteen bytes and jumps to owned 14D3."""
    state = pin["state_c4c8_14a9"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    callee = int(state["callee_file"], 16)
    phys20 = (cs << 4) + 0x14A9
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:14A9 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:14A9 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:14A9 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:14A9 bytes moved")
    raw = image[body_file:body_end]
    if len(raw) != 14 or raw[0] != 0x1E:
        raise AssertionError("14A9 is not PUSH DS")
    if raw[1] != 0x68 or (raw[2] | (raw[3] << 8)) != 0x54BA:
        raise AssertionError("14AA is not PUSH imm16 0x54BA")
    if raw[4] != 0x9A or (raw[5] | (raw[6] << 8)) != 0x005B or (raw[7] | (raw[8] << 8)) != 0xB1B1:
        raise AssertionError("14AD is not CALLF B1B1:005B")
    modrm = raw[10]
    if raw[9] != 0x83 or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 0 or (modrm & 7) != 4 or raw[11] != 0x04:
        raise AssertionError("14B2 does not ADD SP, imm8 +4")
    if raw[12] != 0xEB or raw[13] >= 0x80 or raw[13] != 0x1C:
        raise AssertionError("14B5 rel8 is not +0x1C")
    if (0x14B7 + raw[13]) & 0xFFFF != 0x14D3:
        raise AssertionError("14B5 target is not 14D3")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:14A9 first run contains BRKXA/RETXA")
    if _u16(image, 0x464D4) != 0x14A9 or _u16(image, 0x464D6) != 0x14A9:
        raise AssertionError("1850 words 2 and 3 are not 14A9")
    indirect = decode_one(image, cs, 0x1496)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa75018":
        raise AssertionError("1496 is not JMP CS:[BX+1850]")
    body, hit = follow_local(image, cs, 0x14A9, limit=800)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:14A9 walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    first = next(run for run in runs if run[0].ip == 0x14A9)
    if [insn.ip for insn in first] != [0x14A9, 0x14AA, 0x14AD, 0x14B2, 0x14B5]:
        raise AssertionError("C4C8:14A9 first run is not PUSH DS / PUSH / CALLF / ADD SP / JMPS")
    if first[2].kind != "CALLF" or first[2].target_cs != 0xB1B1 or first[2].target_ip != 0x005B:
        raise AssertionError("14AD does not CALLF B1B1:005B")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x14D3:
        raise AssertionError("C4C8:14A9 first run does not jump into owned 14D3")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:14A9 first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "JMPN_RM" or later[-1].ip != 0x1546:
        raise AssertionError("C4C8:14A9 later run is not owned 14D3 through JMPN_RM 1546")
    if later[-1].file + later[-1].length != join_end:
        raise AssertionError("C4C8:14A9 later run does not end at the owned span")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 14D3 file moved")
    if ((0xB1B1 << 4) + 0x005B) & 0x7FFFF != callee:
        raise AssertionError("CALLF B1B1:005B file moved")
    owned = False
    meets = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
        if start <= callee < end and owner == "code":
            callee_owned = True
    if not owned or not meets or not callee_owned:
        raise AssertionError("C4C8:14A9 seed does not meet owned 14D3")
    if callee in covered:
        raise AssertionError("C4C8:14A9 seed entered B1B1:005B")
    if not _gap_at(0x4611B) or not _gap_at(0x313A0):
        raise AssertionError("149B or B13A:0000 is owned")


def _check_c4c8_14b7(image: bytes, pin: dict) -> None:
    """1850 slots BX==4 and BX==5. Entry run is fourteen bytes and jumps to owned 14D3."""
    state = pin["state_c4c8_14b7"]
    cs = 0xC4C8
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    callee = int(state["callee_file"], 16)
    phys20 = (cs << 4) + 0x14B7
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:14B7 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C4C8:14B7 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:14B7 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError("C4C8:14B7 bytes moved")
    raw = image[body_file:body_end]
    if len(raw) != 14 or raw[0] != 0x1E:
        raise AssertionError("14B7 is not PUSH DS")
    if raw[1] != 0x68 or (raw[2] | (raw[3] << 8)) != 0x54BF:
        raise AssertionError("14B8 is not PUSH imm16 0x54BF")
    if raw[4] != 0x9A or (raw[5] | (raw[6] << 8)) != 0x005B or (raw[7] | (raw[8] << 8)) != 0xB1B1:
        raise AssertionError("14BB is not CALLF B1B1:005B")
    modrm = raw[10]
    if raw[9] != 0x83 or (modrm >> 6) != 3 or ((modrm >> 3) & 7) != 0 or (modrm & 7) != 4 or raw[11] != 0x04:
        raise AssertionError("14C0 does not ADD SP, imm8 +4")
    if raw[12] != 0xEB or raw[13] >= 0x80 or raw[13] != 0x0E:
        raise AssertionError("14C3 rel8 is not +0x0E")
    if (0x14C5 + raw[13]) & 0xFFFF != 0x14D3:
        raise AssertionError("14C3 target is not 14D3")
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C4C8:14B7 first run contains BRKXA/RETXA")
    if _u16(image, 0x464D8) != 0x14B7 or _u16(image, 0x464DA) != 0x14B7:
        raise AssertionError("1850 words 4 and 5 are not 14B7")
    indirect = decode_one(image, cs, 0x1496)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa75018":
        raise AssertionError("1496 is not JMP CS:[BX+1850]")
    body, hit = follow_local(image, cs, 0x14B7, limit=800)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:14B7 walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    first = next(run for run in runs if run[0].ip == 0x14B7)
    if [insn.ip for insn in first] != [0x14B7, 0x14B8, 0x14BB, 0x14C0, 0x14C3]:
        raise AssertionError("C4C8:14B7 first run is not PUSH DS / PUSH / CALLF / ADD SP / JMPS")
    if first[2].kind != "CALLF" or first[2].target_cs != 0xB1B1 or first[2].target_ip != 0x005B:
        raise AssertionError("14BB does not CALLF B1B1:005B")
    if first[-1].kind != "JMPS" or first[-1].target_ip != 0x14D3:
        raise AssertionError("C4C8:14B7 first run does not jump into owned 14D3")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:14B7 first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "JMPN_RM" or later[-1].ip != 0x1546:
        raise AssertionError("C4C8:14B7 later run is not owned 14D3 through JMPN_RM 1546")
    if later[-1].file + later[-1].length != join_end:
        raise AssertionError("C4C8:14B7 later run does not end at the owned span")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 14D3 file moved")
    if ((0xB1B1 << 4) + 0x005B) & 0x7FFFF != callee:
        raise AssertionError("CALLF B1B1:005B file moved")
    owned = False
    meets = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
        if start <= callee < end and owner == "code":
            callee_owned = True
    if not owned or not meets or not callee_owned:
        raise AssertionError("C4C8:14B7 seed does not meet owned 14D3")
    if callee in covered:
        raise AssertionError("C4C8:14B7 seed entered B1B1:005B")
    if not _gap_at(0x4611B) or not _gap_at(0x46145) or not _gap_at(0x313A0):
        raise AssertionError("149B, 14C5, or B13A:0000 is owned")


def _check_c4c8_1844_store_slot(image: bytes, pin: dict, key: str) -> None:
    """1844 store stub. First run jumps near to owned 17C8."""
    state = pin[key]
    cs = 0xC4C8
    ip = int(state["ip"], 16)
    bx = state["bx"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    join = int(state["join_file"], 16)
    join_end = int(state["join_end"], 16)
    callee = int(state["callee_file"], 16)
    callee_cs = int(state["callee_cs"], 16)
    callee_ip = int(state["callee_ip"], 16)
    bl_disp = int(state["bl_disp8"], 16)
    if bl_disp >= 0x80:
        bl_disp -= 0x100
    store_bytes = bytes.fromhex(state["store_bytes"])
    jmpn_disp = int(state["jmpn_disp16"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError(f"C4C8:{ip:04X} file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError(f"C4C8:{ip:04X} is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C4C8:{ip:04X} 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_end].hex() != state["body_bytes"]:
        raise AssertionError(f"C4C8:{ip:04X} bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError(f"C4C8:{ip:04X} first run contains BRKXA/RETXA")
    if raw[0] != 0x8A:
        raise AssertionError(f"{ip:04X} is not MOV r8, r/m8")
    modrm = raw[1]
    if (modrm >> 6) != 1 or ((modrm >> 3) & 7) != 0 or (modrm & 7) != 6 or raw[2] != 0xFF:
        raise AssertionError(f"{ip:04X} does not write AL from [BP-1]")
    if raw[3] != 0x98:
        raise AssertionError(f"{ip + 3:04X} is not CBW (writes AX)")
    if raw[4] != 0x50:
        raise AssertionError(f"{ip + 4:04X} is not PUSH AX (writes SP)")
    if raw[5] != 0x9A:
        raise AssertionError(f"{ip + 5:04X} is not CALLF")
    far_ip = raw[6] | (raw[7] << 8)
    far_cs = raw[8] | (raw[9] << 8)
    if far_ip != callee_ip or far_cs != callee_cs:
        raise AssertionError(f"{ip + 5:04X} is not CALLF {callee_cs:04X}:{callee_ip:04X}")
    add_modrm = raw[11]
    if (
        raw[10] != 0x83
        or (add_modrm >> 6) != 3
        or ((add_modrm >> 3) & 7) != 0
        or (add_modrm & 7) != 4
        or raw[12] != 0x02
    ):
        raise AssertionError(f"{ip + 10:04X} does not ADD SP, imm8 +2")
    bl_modrm = raw[14]
    disp8 = raw[15]
    if disp8 >= 0x80:
        signed = disp8 - 0x100
    else:
        signed = disp8
    if raw[13] != 0x8A or (bl_modrm >> 6) != 1 or ((bl_modrm >> 3) & 7) != 3 or (bl_modrm & 7) != 6:
        raise AssertionError(f"{ip + 13:04X} does not write BL from [BP+disp8]")
    if signed != bl_disp:
        raise AssertionError(f"{ip + 13:04X} BL disp8 is not {bl_disp}")
    es_modrm = raw[17]
    if raw[16] != 0x8E or (es_modrm >> 6) != 3 or ((es_modrm >> 3) & 7) != 0 or (es_modrm & 7) != 2:
        raise AssertionError(f"{ip + 16:04X} does not write ES from DX")
    if raw[18] != 0x93:
        raise AssertionError(f"{ip + 18:04X} is not XCHG AX, BX")
    store = raw[19 : 19 + len(store_bytes)]
    if store != store_bytes:
        raise AssertionError(f"{ip + 19:04X} store is not {state['store_bytes']}")
    if store[0] != 0x26 or store[1] != 0x88:
        raise AssertionError(f"{ip + 19:04X} is not ES: MOV r/m8, r8")
    store_modrm = store[2]
    if ((store_modrm >> 3) & 7) != 0 or (store_modrm & 7) != 7:
        raise AssertionError(f"{ip + 19:04X} does not store AL via [BX]")
    jmp_off = 19 + len(store_bytes)
    if jmp_off + 3 != len(raw):
        raise AssertionError(f"C4C8:{ip:04X} length is not the store stub")
    if raw[jmp_off] != 0xE9:
        raise AssertionError(f"{ip + jmp_off:04X} is not JMPN")
    rel = raw[jmp_off + 1] | (raw[jmp_off + 2] << 8)
    if rel >= 0x8000:
        raise AssertionError(f"{ip + jmp_off:04X} disp16 is not positive")
    if rel != jmpn_disp:
        raise AssertionError(f"{ip + jmp_off:04X} disp16 is not 0x{jmpn_disp:04X}")
    next_ip = (ip + len(raw)) & 0xFFFF
    if (next_ip + rel) & 0xFFFF != 0x17C8:
        raise AssertionError(f"{ip + jmp_off:04X} target is not 17C8")
    if _u16(image, 0x464C4 + bx * 2) != ip:
        raise AssertionError(f"1844 word {bx} is not {ip:04X}")
    if int(state["word_file"], 16) != 0x464C4 + bx * 2:
        raise AssertionError(f"C4C8:{ip:04X} word file moved")
    indirect = decode_one(image, cs, 0x1546)
    if indirect.kind != "JMPN_RM" or indirect.bytes_hex != "2effa74418":
        raise AssertionError("1546 is not JMP CS:[BX+1844]")
    body, hit = follow_local(image, cs, ip, limit=800)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError(f"C4C8:{ip:04X} walk hit a boundary")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    first = next(run for run in runs if run[0].ip == ip)
    expected_ips = [int(x, 16) for x in state["expected_ips"]]
    if [insn.ip for insn in first] != expected_ips:
        raise AssertionError(f"C4C8:{ip:04X} first run is not the store stub")
    callf = first[3]
    if callf.kind != "CALLF" or callf.target_cs != callee_cs or callf.target_ip != callee_ip:
        raise AssertionError(f"{ip + 5:04X} does not CALLF {callee_cs:04X}:{callee_ip:04X}")
    if first[-1].kind != "JMPN" or first[-1].target_ip != 0x17C8:
        raise AssertionError(f"C4C8:{ip:04X} first run does not jump into owned 17C8")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError(f"C4C8:{ip:04X} first run is not a contiguous span")
    later = next(run for run in runs if run[0].file == join)
    if later[-1].kind != "JMPN_RM" or later[-1].ip != 0x17E8:
        raise AssertionError(f"C4C8:{ip:04X} later run is not owned 17C8 through JMPN_RM 17E8")
    if later[-1].file + later[-1].length != join_end:
        raise AssertionError(f"C4C8:{ip:04X} later run does not end at the owned span")
    if ((cs << 4) + first[-1].target_ip) & 0x7FFFF != join:
        raise AssertionError("JMP 17C8 file moved")
    if ((callee_cs << 4) + callee_ip) & 0x7FFFF != callee:
        raise AssertionError(f"CALLF {callee_cs:04X}:{callee_ip:04X} file moved")
    owned = False
    meets = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == join and end == join_end and owner == "code":
            meets = True
        if start <= callee < end and owner == "code":
            callee_owned = True
    if not owned or not meets or not callee_owned:
        raise AssertionError(f"C4C8:{ip:04X} seed does not meet owned 17C8")
    if join in covered:
        raise AssertionError(f"C4C8:{ip:04X} seed entered 17C8")
    if callee in covered:
        raise AssertionError(f"C4C8:{ip:04X} seed entered the CALLF dest")
    if not _gap_at(0x461CB) or not _gap_at(0x463B1) or not _gap_at(0x46428):
        raise AssertionError("154B, 1731, or 17A8 is owned")
    if not _gap_at(0x4611B) or not _gap_at(0x46145) or not _gap_at(0x313A0):
        raise AssertionError("149B, 14C5, or B13A:0000 is owned")
    if not _gap_at(0x4646D) or not _gap_at(0x46486):
        raise AssertionError("17ED or 1806 is owned")


def _check_c4c8_16e4(image: bytes, pin: dict) -> None:
    """1844 slot BX==1. Store stub jumps near to owned 17C8."""
    _check_c4c8_1844_store_slot(image, pin, "state_c4c8_16e4")


def _check_c4c8_16fd(image: bytes, pin: dict) -> None:
    """1844 slot BX==2. Store stub jumps near to owned 17C8."""
    _check_c4c8_1844_store_slot(image, pin, "state_c4c8_16fd")


def _check_c4c8_1717(image: bytes, pin: dict) -> None:
    """1844 slot BX==3. Store stub jumps near to owned 17C8."""
    _check_c4c8_1844_store_slot(image, pin, "state_c4c8_1717")


def _check_ca9b_0004(image: bytes, pin: dict) -> None:
    """CA9B:0004 is one closed first run through RETF. CALLN 029E stays out."""
    state = pin["state_ca9b_0004"]
    cs = 0xCA9B
    ip = 0x0004
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    callee = int(state["callee_file"], 16)
    caller_file = int(state["caller_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("CA9B:0004 file or 20-bit address")
    if (phys20 >> 14) != 50:
        raise AssertionError("CA9B:0004 is not PGR slot 50")
    phys24 = (_u16(image, 0x7AD18) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD18) != 0x0032:
        raise AssertionError(f"CA9B:0004 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 50 or state["pgr_bytes"] != "3200" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("CA9B:0004 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("CA9B:0004 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("CA9B:0004 first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("0004 is not PUSH BP")
    if raw[1] != 0x8B or raw[2] != 0xEC:
        raise AssertionError("0005 does not write BP from SP")
    sub_modrm = raw[4]
    if (
        raw[3] != 0x83
        or (sub_modrm >> 6) != 3
        or ((sub_modrm >> 3) & 7) != 5
        or (sub_modrm & 7) != 4
        or raw[5] != 0x10
    ):
        raise AssertionError("0007 does not SUB SP, imm8 +0x10")
    if raw[6] != 0x1E:
        raise AssertionError("000A is not PUSH DS")
    if raw[7] != 0x68 or raw[8] != 0x6E or raw[9] != 0x62:
        raise AssertionError("000B is not PUSH imm16 0x626E")
    push_cs = decode_one(image, cs, 0x000B)
    if push_cs.bytes_hex != "686e62":
        raise AssertionError("000B PUSH imm16 moved")
    callf = decode_one(image, cs, 0x000E)
    if callf.kind != "CALLF" or callf.target_cs != 0xB509 or callf.target_ip != 0x2289:
        raise AssertionError("000E is not CALLF B509:2289")
    add_modrm = raw[16]
    if (
        raw[15] != 0x83
        or (add_modrm >> 6) != 3
        or ((add_modrm >> 3) & 7) != 0
        or (add_modrm & 7) != 4
        or raw[17] != 0x04
    ):
        raise AssertionError("0013 does not ADD SP, imm8 +4")
    cmp_file = int(state["jge_file"], 16) - 5
    if image[cmp_file:cmp_file + 7].hex() != "803e0892007d0d":
        raise AssertionError("0016 is not CMP [9208],0 / JGE 002A")
    jge = decode_one(image, cs, 0x001B)
    if jge.kind != "JCC" or jge.bytes_hex != state["jge_bytes"] or jge.target_ip != 0x002A:
        raise AssertionError("001B is not JGE 002A")
    if image[jge.file] != 0x7D:
        raise AssertionError("001B is not opcode 7D")
    caller = decode_one(image, 0xC425, 0x01CE)
    if (
        caller.kind != "CALLF"
        or caller.target_cs != cs
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("C425:01CE is not CALLF CA9B:0004")
    far_ip = image[caller_file + 1] | (image[caller_file + 2] << 8)
    far_cs = image[caller_file + 3] | (image[caller_file + 4] << 8)
    if far_ip != 0x0004 or far_cs != 0xCA9B:
        raise AssertionError("C425:01CE far immediate is not CA9B:0004")
    calln = decode_one(image, cs, 0x01C5)
    if (
        calln.kind != "CALLN"
        or calln.target_ip != 0x029E
        or calln.file != int(state["calln_file"], 16)
        or calln.bytes_hex != state["calln_bytes"]
    ):
        raise AssertionError("01C5 is not CALLN 029E")
    rel = image[calln.file + 1] | (image[calln.file + 2] << 8)
    if rel != 0x00D6:
        raise AssertionError("01C5 disp16 is not 0x00D6")
    if ((0x01C5 + 3 + rel) & 0xFFFF) != 0x029E:
        raise AssertionError("01C5 target is not 029E")
    leave = decode_one(image, cs, 0x029C)
    retf = decode_one(image, cs, 0x029D)
    if leave.bytes_hex != "c9" or retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("029C is not LEAVE / RETF")
    ax_modrm = image[int(state["body_end"], 16) - 4 + 1]
    if image[body_end - 4] != 0x8B or (ax_modrm >> 6) != 3 or ((ax_modrm >> 3) & 7) != 0 or (ax_modrm & 7) != 2:
        raise AssertionError("029A does not write AX from DX")
    body, hit = follow_local(image, cs, ip, limit=400)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("CA9B:0004 walk hit a boundary")
    if body[-1].ip != 0x029D or body[-1].kind != "RETF":
        raise AssertionError("CA9B:0004 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("CA9B:0004 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip:
        raise AssertionError("CA9B:0004 first run does not start at 0004")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("CA9B:0004 first run is not a contiguous span")
    if callee in covered:
        raise AssertionError("CA9B:0004 seed entered CALLN 029E")
    if ((cs << 4) + 0x029E) & 0x7FFFF != callee:
        raise AssertionError("CA9B:029E file moved")
    owned = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= callee < end and owner == "code":
            callee_owned = True
    if not owned:
        raise AssertionError("CA9B:0004 body is not the owned seed")
    if callee_owned:
        raise AssertionError("CA9B:029E was entered")
    if not _gap_at(callee) or not _gap_at(0x313A0) or not _gap_at(0x4611B):
        raise AssertionError("CA9B:029E, B13A:0000, or C4C8:149B is owned")
    if not _gap_at(0x463B1) or not _gap_at(0x4646D) or not _gap_at(0x4921C):
        raise AssertionError("1731, 17ED, or C887:09AC is owned")


def _check_c6c2_1362(image: bytes, pin: dict) -> None:
    """C6C2:1362 is one closed first run through RETF. CALLN 182D stays out."""
    state = pin["state_c6c2_1362"]
    cs = 0xC6C2
    ip = 0x1362
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    callee = int(state["callee_file"], 16)
    prefix_callee = int(state["prefix_callee_file"], 16)
    caller_file = int(state["caller_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:1362 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C6C2:1362 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C6C2:1362 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:1362 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:1362 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:1362 first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("1362 is not PUSH BP")
    if raw[1] != 0x8B or raw[2] != 0xEC:
        raise AssertionError("1363 does not write BP from SP")
    sub_modrm = raw[4]
    if (
        raw[3] != 0x83
        or (sub_modrm >> 6) != 3
        or ((sub_modrm >> 3) & 7) != 5
        or (sub_modrm & 7) != 4
        or raw[5] != 0x0E
    ):
        raise AssertionError("1365 does not SUB SP, imm8 +0x0E")
    if raw[6] != 0x56 or raw[7] != 0x57:
        raise AssertionError("1368 is not PUSH SI / PUSH DI")
    zero_imm = decode_one(image, cs, 0x136F)
    if zero_imm.bytes_hex != "c746fc0000":
        raise AssertionError("136F is not MOV [BP-4], imm16 0x0000")
    imm16 = image[zero_imm.file + 3] | (image[zero_imm.file + 4] << 8)
    if imm16 != 0x0000:
        raise AssertionError("136F imm16 is not 0x0000")
    cmp_file = int(state["jz_file"], 16) - 5
    if image[cmp_file:cmp_file + 7].hex() != "803e3f56007405":
        raise AssertionError("1374 is not CMP [563F],0 / JZ 1380")
    jz = decode_one(image, cs, 0x1379)
    if jz.kind != "JCC" or jz.bytes_hex != state["jz_bytes"] or jz.target_ip != 0x1380:
        raise AssertionError("1379 is not JZ 1380")
    if image[jz.file] != 0x74:
        raise AssertionError("1379 is not opcode 74")
    if ((0x1379 + 2 + image[jz.file + 1]) & 0xFFFF) != 0x1380:
        raise AssertionError("1379 target is not 1380")
    caller = decode_one(image, 0xDE5C, 0x01D6)
    if (
        caller.kind != "CALLF"
        or caller.target_cs != cs
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("DE5C:01D6 is not CALLF C6C2:1362")
    far_ip = image[caller_file + 1] | (image[caller_file + 2] << 8)
    far_cs = image[caller_file + 3] | (image[caller_file + 4] << 8)
    if far_ip != 0x1362 or far_cs != 0xC6C2:
        raise AssertionError("DE5C:01D6 far immediate is not C6C2:1362")
    calln = decode_one(image, cs, 0x13C2)
    if calln.kind != "CALLN" or calln.target_ip != 0x182D or calln.bytes_hex != "e86804":
        raise AssertionError("13C2 is not CALLN 182D")
    rel = image[calln.file + 1] | (image[calln.file + 2] << 8)
    if rel != 0x0468:
        raise AssertionError("13C2 disp16 is not 0x0468")
    if ((0x13C2 + 3 + rel) & 0xFFFF) != 0x182D:
        raise AssertionError("13C2 target is not 182D")
    prefix = decode_one(image, cs, 0x13C9)
    if prefix.kind != "CALLN" or prefix.target_ip != 0x1324:
        raise AssertionError("13C9 is not CALLN 1324")
    leave = decode_one(image, cs, 0x15E7)
    retf = decode_one(image, cs, 0x15E8)
    if leave.bytes_hex != "c9" or retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("15E7 is not LEAVE / RETF")
    if image[body_end - 4] != 0x5F or image[body_end - 3] != 0x5E:
        raise AssertionError("15E5 is not POP DI / POP SI")
    body, hit = follow_local(image, cs, ip, limit=400)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:1362 walk hit a boundary")
    if body[-1].ip != 0x15E8 or body[-1].kind != "RETF":
        raise AssertionError("C6C2:1362 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:1362 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip:
        raise AssertionError("C6C2:1362 first run does not start at 1362")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:1362 first run is not a contiguous span")
    if callee in covered or prefix_callee in covered:
        raise AssertionError("C6C2:1362 seed entered CALLN 182D or 1324")
    if ((cs << 4) + 0x182D) & 0x7FFFF != callee:
        raise AssertionError("C6C2:182D file moved")
    if ((cs << 4) + 0x1324) & 0x7FFFF != prefix_callee:
        raise AssertionError("C6C2:1324 file moved")
    owned = False
    callee_owned = False
    prefix_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= callee < end and owner == "code":
            callee_owned = True
        if start <= prefix_callee < end and owner == "code":
            prefix_owned = True
    if not owned:
        raise AssertionError("C6C2:1362 body is not the owned seed")
    if not prefix_owned:
        raise AssertionError("C6C2:1324 body is not owned")
    if not _gap_at(0x3CF9C):
        raise AssertionError("BCF9:000C is owned")
    if not _gap_at(0x4AC4E) or not _gap_at(0x313A0) or not _gap_at(0x4611B):
        raise AssertionError("CA9B:029E, B13A:0000, or C4C8:149B is owned")
    if not callee_owned:
        raise AssertionError("C6C2:182D body is not owned")


def _check_c6c2_182d(image: bytes, pin: dict) -> None:
    """C6C2:182D is one closed first run through RETF. CALLN 1895 stays out."""
    state = pin["state_c6c2_182d"]
    cs = 0xC6C2
    ip = 0x182D
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    near_callee = int(state["near_callee_file"], 16)
    far_callee = int(state["far_callee_file"], 16)
    prefix_callee = int(state["prefix_callee_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:182D file or 20-bit address")
    if (phys20 >> 14) != 50:
        raise AssertionError("C6C2:182D is not PGR slot 50")
    phys24 = (_u16(image, 0x7AD18) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD18) != 0x0032:
        raise AssertionError(f"C6C2:182D 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 50 or state["pgr_bytes"] != "3200" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD18:0x7AD1A].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 50 word moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:182D head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:182D tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:182D first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("182D is not PUSH BP")
    if raw[1] != 0x8B or raw[2] != 0xEC:
        raise AssertionError("182E does not write BP from SP")
    mov_modrm = raw[2]
    if (mov_modrm >> 6) != 3 or ((mov_modrm >> 3) & 7) != 5 or (mov_modrm & 7) != 4:
        raise AssertionError("182E ModR/M does not write BP from SP")
    jnz = decode_one(image, cs, 0x1837)
    if jnz.kind != "JCC" or jnz.bytes_hex != state["jnz_bytes"] or jnz.target_ip != 0x184B:
        raise AssertionError("1837 is not JNZ 184B")
    if image[jnz.file] != 0x75 or jnz.file != int(state["jnz_file"], 16):
        raise AssertionError("1837 is not opcode 75")
    rel8 = image[jnz.file + 1]
    if rel8 != 0x12 or ((0x1837 + 2 + rel8) & 0xFFFF) != 0x184B:
        raise AssertionError("1837 target is not 184B")
    walk_ip = 0x1362
    caller = None
    for _ in range(80):
        insn = decode_one(image, cs, walk_ip)
        if not (0x47F82 <= insn.file < 0x48209):
            raise AssertionError("linear 1362 left the owned span before 13C2")
        if insn.ip == 0x13C2:
            caller = insn
            break
        if insn.kind in ("RETF", "RET", "IRET", "RETN", "RETFN"):
            raise AssertionError("linear 1362 hit RET before 13C2")
        walk_ip = (walk_ip + insn.length) & 0xFFFF
    if caller is None:
        raise AssertionError("linear 1362 did not reach 13C2")
    if (
        caller.kind != "CALLN"
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("13C2 is not CALLN 182D")
    disp = image[caller_file + 1] | (image[caller_file + 2] << 8)
    if disp != 0x0468 or ((0x13C2 + 3 + disp) & 0xFFFF) != ip:
        raise AssertionError("13C2 disp16 is not +0x0468 to 182D")
    calln = decode_one(image, cs, 0x185F)
    if calln.kind != "CALLN" or calln.target_ip != 0x1895 or calln.bytes_hex != "e83300":
        raise AssertionError("185F is not CALLN 1895")
    if ((cs << 4) + 0x1895) & 0x7FFFF != near_callee:
        raise AssertionError("C6C2:1895 file moved")
    far = decode_one(image, cs, 0x1884)
    if far.kind != "CALLF" or far.target_cs != 0xD90C or far.target_ip != 0x0006:
        raise AssertionError("1884 is not CALLF D90C:0006")
    if ((0xD90C << 4) + 0x0006) & 0x7FFFF != far_callee:
        raise AssertionError("D90C:0006 file moved")
    pop = decode_one(image, cs, 0x1893)
    retf = decode_one(image, cs, 0x1894)
    if pop.bytes_hex != "5d" or retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("1893 is not POP BP / RETF")
    if decode_one(image, cs, 0x1890).kind != "RETF":
        raise AssertionError("1890 is not RETF")
    add_modrm = image[decode_one(image, cs, 0x1889).file + 1]
    add = decode_one(image, cs, 0x1889)
    if (
        add.bytes_hex != "83c402"
        or (add_modrm >> 6) != 3
        or ((add_modrm >> 3) & 7) != 0
        or (add_modrm & 7) != 4
    ):
        raise AssertionError("1889 does not ADD SP, imm8 +2")
    body, hit = follow_local(image, cs, ip, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:182D walk hit a boundary")
    if body[-1].ip != 0x1894 or body[-1].kind != "RETF":
        raise AssertionError("C6C2:182D does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:182D first run is not the only run")
    first = runs[0]
    if first[0].ip != ip:
        raise AssertionError("C6C2:182D first run does not start at 182D")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:182D first run is not a contiguous span")
    if near_callee in covered or far_callee in covered or prefix_callee in covered:
        raise AssertionError("C6C2:182D seed entered 1895, D90C:0006, or 1324")
    owned = False
    caller_owned = False
    far_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start <= far_callee < end and owner == "code":
            far_owned = True
    if not owned:
        raise AssertionError("C6C2:182D body is not the owned seed")
    if not caller_owned:
        raise AssertionError("C6C2:13C2 caller is not owned")
    if far_owned:
        raise AssertionError("D90C:0006 was entered")
    if not _gap_at(far_callee):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E) or not _gap_at(0x4921C):
        raise AssertionError("BCF9:000C, CA9B:029E, or C887:09AC is owned")


def _check_c6c2_1324(image: bytes, pin: dict) -> None:
    """C6C2:1324 is one closed first run through RETF. CALLN 12D2 stays out."""
    state = pin["state_c6c2_1324"]
    cs = 0xC6C2
    ip = 0x1324
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    callee = int(state["callee_file"], 16)
    next_file = int(state["next_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:1324 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C6C2:1324 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C6C2:1324 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD16:0x7AD18].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 49 word moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:1324 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:1324 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:1324 first run contains BRKXA/RETXA")
    if raw[0] != 0x57:
        raise AssertionError("1324 is not PUSH DI")
    mov_di = decode_one(image, cs, 0x1327)
    if mov_di.bytes_hex != "bf5bfa":
        raise AssertionError("1327 is not MOV DI, imm16 0xFA5B")
    di_imm = image[mov_di.file + 1] | (image[mov_di.file + 2] << 8)
    if image[mov_di.file] != 0xBF or di_imm != 0xFA5B:
        raise AssertionError("1327 opcode does not write DI from imm16")
    xor_ax = decode_one(image, cs, 0x132A)
    xor_modrm = image[xor_ax.file + 1]
    if (
        xor_ax.bytes_hex != "33c0"
        or (xor_modrm >> 6) != 3
        or ((xor_modrm >> 3) & 7) != 0
        or (xor_modrm & 7) != 0
    ):
        raise AssertionError("132A does not write AX from AX")
    mov_ah = decode_one(image, cs, 0x132C)
    ah_modrm = image[mov_ah.file + 1]
    if (
        mov_ah.bytes_hex != "8ae0"
        or (ah_modrm >> 6) != 3
        or ((ah_modrm >> 3) & 7) != 4
        or (ah_modrm & 7) != 0
    ):
        raise AssertionError("132C does not write AH from AL")
    mov_cx = decode_one(image, cs, 0x132E)
    cx_imm = image[mov_cx.file + 1] | (image[mov_cx.file + 2] << 8)
    if mov_cx.bytes_hex != "b90200" or image[mov_cx.file] != 0xB9 or cx_imm != 0x0002:
        raise AssertionError("132E does not write CX from imm16 0x0002")
    walk_ip = 0x1362
    caller = None
    for _ in range(80):
        insn = decode_one(image, cs, walk_ip)
        if not (0x47F82 <= insn.file < 0x48209):
            raise AssertionError("linear 1362 left the owned span before 13C9")
        if insn.ip == 0x13C9:
            caller = insn
            break
        if insn.kind in ("RETF", "RET", "IRET", "RETN", "RETFN"):
            raise AssertionError("linear 1362 hit RET before 13C9")
        walk_ip = (walk_ip + insn.length) & 0xFFFF
    if caller is None:
        raise AssertionError("linear 1362 did not reach 13C9")
    if (
        caller.kind != "CALLN"
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("13C9 is not CALLN 1324")
    disp = image[caller_file + 1] | (image[caller_file + 2] << 8)
    if disp != 0xFF58:
        raise AssertionError("13C9 disp16 is not 0xFF58")
    rel = disp - 0x10000
    if ((0x13C9 + 3 + rel) & 0xFFFF) != ip:
        raise AssertionError("13C9 disp16 is not -0x00A8 to 1324")
    calln = decode_one(image, cs, 0x1340)
    if (
        calln.kind != "CALLN"
        or calln.target_ip != 0x12D2
        or calln.bytes_hex != state["calln_bytes"]
        or calln.file != int(state["calln_file"], 16)
    ):
        raise AssertionError("1340 is not CALLN 12D2")
    near_disp = image[calln.file + 1] | (image[calln.file + 2] << 8)
    if near_disp != 0xFF8F:
        raise AssertionError("1340 disp16 is not 0xFF8F")
    near_rel = near_disp - 0x10000
    if ((0x1340 + 3 + near_rel) & 0xFFFF) != 0x12D2:
        raise AssertionError("1340 disp16 is not -0x0071 to 12D2")
    if ((cs << 4) + 0x12D2) & 0x7FFFF != callee:
        raise AssertionError("C6C2:12D2 file moved")
    pop = decode_one(image, cs, 0x1343)
    retf = decode_one(image, cs, 0x1344)
    if pop.bytes_hex != "5f" or retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("1343 is not POP DI / RETF")
    if image[pop.file] != 0x5F:
        raise AssertionError("1343 does not write DI")
    body, hit = follow_local(image, cs, ip, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:1324 walk hit a boundary")
    if body[-1].ip != 0x1344 or body[-1].kind != "RETF":
        raise AssertionError("C6C2:1324 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:1324 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip:
        raise AssertionError("C6C2:1324 first run does not start at 1324")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind == "JCC":
            raise AssertionError("C6C2:1324 first run contains a Jcc")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:1324 first run is not a contiguous span")
    if callee in covered or next_file in covered:
        raise AssertionError("C6C2:1324 seed entered 12D2 or leftover 1345")
    if body_end != next_file:
        raise AssertionError("C6C2:1324 seed extended past RETF")
    owned = False
    caller_owned = False
    callee_owned = False
    next_owned = False
    far_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start <= callee < end and owner == "code":
            callee_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= 0x590C6 < end and owner == "code":
            far_owned = True
    if not owned:
        raise AssertionError("C6C2:1324 body is not the owned seed")
    if not caller_owned:
        raise AssertionError("C6C2:13C9 caller is not owned")
    if not callee_owned:
        raise AssertionError("C6C2:12D2 body is not owned")
    if next_owned or far_owned:
        raise AssertionError("leftover 1345 or D90C:0006 was entered")
    if not _gap_at(next_file):
        raise AssertionError("leftover 1345 is owned")
    if not _gap_at(0x590C6):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E) or not _gap_at(0x4921C):
        raise AssertionError("BCF9:000C, CA9B:029E, or C887:09AC is owned")


def _check_c6c2_12d2(image: bytes, pin: dict) -> None:
    """C6C2:12D2 is one closed first run through RETF. CALLN 11EF stays out."""
    state = pin["state_c6c2_12d2"]
    cs = 0xC6C2
    ip = 0x12D2
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    callee = int(state["callee_file"], 16)
    next_file = int(state["next_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:12D2 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C6C2:12D2 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C6C2:12D2 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD16:0x7AD18].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 49 word moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:12D2 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:12D2 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:12D2 first run contains BRKXA/RETXA")
    if raw[0] != 0xA0:
        raise AssertionError("12D2 is not MOV AL, moffs16")
    moffs = image[body_file + 1] | (image[body_file + 2] << 8)
    if moffs != 0x85A6:
        raise AssertionError("12D2 moffs16 is not 0x85A6")
    if decode_one(image, cs, 0x12D5).bytes_hex != "98":
        raise AssertionError("12D5 is not CBW")
    or_ax = decode_one(image, cs, 0x12D6)
    or_modrm = image[or_ax.file + 1]
    if (
        or_ax.bytes_hex != "0bc0"
        or (or_modrm >> 6) != 3
        or ((or_modrm >> 3) & 7) != 0
        or (or_modrm & 7) != 0
    ):
        raise AssertionError("12D6 does not write AX from AX")
    jz = decode_one(image, cs, 0x12D8)
    if jz.kind != "JCC" or jz.bytes_hex != state["jz_bytes"] or jz.target_ip != 0x12E5:
        raise AssertionError("12D8 is not JZ 12E5")
    if image[jz.file] != 0x74 or jz.file != int(state["jz_file"], 16):
        raise AssertionError("12D8 is not opcode 74")
    rel8 = image[jz.file + 1]
    if rel8 != 0x0B or ((0x12D8 + 2 + rel8) & 0xFFFF) != 0x12E5:
        raise AssertionError("12D8 target is not 12E5")
    cmp_ax = decode_one(image, cs, 0x12DA)
    cmp_imm = image[cmp_ax.file + 1] | (image[cmp_ax.file + 2] << 8)
    if cmp_ax.bytes_hex != "3d0100" or image[cmp_ax.file] != 0x3D or cmp_imm != 0x0001:
        raise AssertionError("12DA does not CMP AX, imm16 0x0001")
    walk_ip = 0x1324
    caller = None
    for _ in range(40):
        insn = decode_one(image, cs, walk_ip)
        if not (0x47F44 <= insn.file < 0x47F65):
            raise AssertionError("linear 1324 left the owned span before 1340")
        if insn.ip == 0x1340:
            caller = insn
            break
        if insn.kind in ("RETF", "RET", "IRET", "RETN", "RETFN"):
            raise AssertionError("linear 1324 hit RET before 1340")
        walk_ip = (walk_ip + insn.length) & 0xFFFF
    if caller is None:
        raise AssertionError("linear 1324 did not reach 1340")
    if (
        caller.kind != "CALLN"
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("1340 is not CALLN 12D2")
    disp = image[caller_file + 1] | (image[caller_file + 2] << 8)
    if disp != 0xFF8F:
        raise AssertionError("1340 disp16 is not 0xFF8F")
    rel = disp - 0x10000
    if ((0x1340 + 3 + rel) & 0xFFFF) != ip:
        raise AssertionError("1340 disp16 is not -0x0071 to 12D2")
    calln = decode_one(image, cs, 0x131D)
    if (
        calln.kind != "CALLN"
        or calln.target_ip != 0x11EF
        or calln.bytes_hex != state["calln_bytes"]
        or calln.file != int(state["calln_file"], 16)
    ):
        raise AssertionError("131D is not CALLN 11EF")
    near_disp = image[calln.file + 1] | (image[calln.file + 2] << 8)
    if near_disp != 0xFECF:
        raise AssertionError("131D disp16 is not 0xFECF")
    near_rel = near_disp - 0x10000
    if ((0x131D + 3 + near_rel) & 0xFFFF) != 0x11EF:
        raise AssertionError("131D disp16 is not -0x0131 to 11EF")
    if ((cs << 4) + 0x11EF) & 0x7FFFF != callee:
        raise AssertionError("C6C2:11EF file moved")
    add = decode_one(image, cs, 0x1320)
    add_modrm = image[add.file + 1]
    if (
        add.bytes_hex != "83c408"
        or (add_modrm >> 6) != 3
        or ((add_modrm >> 3) & 7) != 0
        or (add_modrm & 7) != 4
        or image[add.file + 2] != 0x08
    ):
        raise AssertionError("1320 does not ADD SP, imm8 +8")
    if decode_one(image, cs, 0x12E4).kind != "RETF":
        raise AssertionError("12E4 is not RETF")
    retf = decode_one(image, cs, 0x1323)
    if retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("1323 is not RETF")
    body, hit = follow_local(image, cs, ip, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:12D2 walk hit a boundary")
    if body[-1].ip != 0x1323 or body[-1].kind != "RETF":
        raise AssertionError("C6C2:12D2 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:12D2 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip:
        raise AssertionError("C6C2:12D2 first run does not start at 12D2")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:12D2 first run is not a contiguous span")
    if callee in covered or next_file in covered or 0x47F44 in covered:
        raise AssertionError("C6C2:12D2 seed entered 11EF, leftover 1345, or 1324")
    if body_end != 0x47F44:
        raise AssertionError("C6C2:12D2 seed is not adjacent to 1324")
    owned = False
    caller_owned = False
    parent_owned = False
    callee_owned = False
    next_owned = False
    far_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == 0x47F44 and end == 0x47F65 and owner == "code":
            parent_owned = True
        if start <= callee < end and owner == "code":
            callee_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= 0x590C6 < end and owner == "code":
            far_owned = True
    if not owned:
        raise AssertionError("C6C2:12D2 body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:1340 caller or C6C2:1324 body is not owned")
    if not callee_owned:
        raise AssertionError("C6C2:11EF body is not owned")
    if next_owned or far_owned:
        raise AssertionError("leftover 1345 or D90C:0006 was entered")
    if not _gap_at(next_file):
        raise AssertionError("leftover 1345 is owned")
    if not _gap_at(0x590C6):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E) or not _gap_at(0x4921C):
        raise AssertionError("BCF9:000C, CA9B:029E, or C887:09AC is owned")


def _check_c6c2_11ef(image: bytes, pin: dict) -> None:
    """C6C2:11EF is one closed first run through RETF. CALLN from follow_local 12D2."""
    state = pin["state_c6c2_11ef"]
    cs = 0xC6C2
    ip = 0x11EF
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    prefix_file = int(state["prefix_file"], 16)
    parent_file = int(state["parent_file"], 16)
    next_file = int(state["next_file"], 16)
    sibling_1169 = int(state["sibling_1169"], 16)
    sibling_1169_end = int(state["sibling_1169_end"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:11EF file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C6C2:11EF is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C6C2:11EF 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD16:0x7AD18].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 49 word moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:11EF head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:11EF tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:11EF first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("11EF is not PUSH BP")
    mov_bp = decode_one(image, cs, 0x11F0)
    mov_modrm = image[mov_bp.file + 1]
    if (
        mov_bp.bytes_hex != "8bec"
        or (mov_modrm >> 6) != 3
        or ((mov_modrm >> 3) & 7) != 5
        or (mov_modrm & 7) != 4
    ):
        raise AssertionError("11F0 does not write BP from SP")
    sub_sp = decode_one(image, cs, 0x11F2)
    sub_modrm = image[sub_sp.file + 1]
    if (
        sub_sp.bytes_hex != "83ec26"
        or (sub_modrm >> 6) != 3
        or ((sub_modrm >> 3) & 7) != 5
        or (sub_modrm & 7) != 4
        or image[sub_sp.file + 2] != 0x26
    ):
        raise AssertionError("11F2 does not write SP from imm8 0x26")
    mov_ax = decode_one(image, cs, 0x11FB)
    ax_imm = image[mov_ax.file + 1] | (image[mov_ax.file + 2] << 8)
    if mov_ax.bytes_hex != "b82000" or image[mov_ax.file] != 0xB8 or ax_imm != 0x0020:
        raise AssertionError("11FB does not write AX from imm16 0x0020")
    body_jz = decode_one(image, cs, 0x123F)
    if body_jz.kind != "JCC" or body_jz.bytes_hex != state["body_jz_bytes"] or body_jz.target_ip != 0x1251:
        raise AssertionError("123F is not JZ 1251")
    if image[body_jz.file] != 0x74 or body_jz.file != int(state["body_jz_file"], 16):
        raise AssertionError("123F is not opcode 74")
    body_rel8 = image[body_jz.file + 1]
    if body_rel8 != 0x10 or ((0x123F + 2 + body_rel8) & 0xFFFF) != 0x1251:
        raise AssertionError("123F target is not 1251")
    parent, parent_hit = follow_local(image, cs, 0x12D2, limit=80)
    if parent_hit:
        raise AssertionError("follow_local 12D2 hit a limit")
    caller = None
    for insn in parent:
        if insn.ip == 0x12EE:
            caller = insn
            break
    if caller is None:
        raise AssertionError("follow_local 12D2 does not list 12EE")
    parent_jz = decode_one(image, cs, 0x12D8)
    if (
        parent_jz.kind != "JCC"
        or parent_jz.bytes_hex != state["jz_bytes"]
        or parent_jz.target_ip != 0x12E5
    ):
        raise AssertionError("12D8 is not JZ 12E5")
    if image[parent_jz.file] != 0x74 or parent_jz.file != int(state["jz_file"], 16):
        raise AssertionError("12D8 is not opcode 74")
    parent_rel8 = image[parent_jz.file + 1]
    if parent_rel8 != 0x0B or ((0x12D8 + 2 + parent_rel8) & 0xFFFF) != 0x12E5:
        raise AssertionError("12D8 target is not 12E5")
    if caller.ip <= 0x12E5 or caller.file >= 0x47F44:
        raise AssertionError("12EE is not after 12E5 inside owned 12D2")
    if not (0x47EF2 <= caller.file < 0x47F44):
        raise AssertionError("12EE is not inside owned 12D2")
    if (
        caller.kind != "CALLN"
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("12EE is not CALLN 11EF")
    disp = image[caller_file + 1] | (image[caller_file + 2] << 8)
    if disp != 0xFEFE:
        raise AssertionError("12EE disp16 is not 0xFEFE")
    rel = disp - 0x10000
    if ((0x12EE + 3 + rel) & 0xFFFF) != ip:
        raise AssertionError("12EE disp16 is not -0x0102 to 11EF")
    add = decode_one(image, cs, 0x12CC)
    add_modrm = image[add.file + 1]
    if (
        add.bytes_hex != "83c404"
        or (add_modrm >> 6) != 3
        or ((add_modrm >> 3) & 7) != 0
        or (add_modrm & 7) != 4
        or image[add.file + 2] != 0x04
    ):
        raise AssertionError("12CC does not ADD SP, imm8 +4")
    pop = decode_one(image, cs, 0x12CF)
    if pop.bytes_hex != "5f" or image[pop.file] != 0x5F:
        raise AssertionError("12CF does not write DI")
    if decode_one(image, cs, 0x12D0).bytes_hex != "c9":
        raise AssertionError("12D0 is not LEAVE")
    retf = decode_one(image, cs, 0x12D1)
    if retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("12D1 is not RETF")
    body, hit = follow_local(image, cs, ip, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:11EF walk hit a boundary")
    if body[-1].ip != 0x12D1 or body[-1].kind != "RETF":
        raise AssertionError("C6C2:11EF does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:11EF first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("C6C2:11EF first run does not start at 11EF")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:11EF first run is not a contiguous span")
    if parent_file in covered or next_file in covered or prefix_file in covered:
        raise AssertionError("C6C2:11EF seed entered 12D2, leftover 1345, or prefix")
    if body_end != parent_file:
        raise AssertionError("C6C2:11EF seed is not adjacent to 12D2")
    if body_file != sibling_1169_end:
        raise AssertionError("C6C2:11EF is not adjacent to 1169")
    owned = False
    caller_owned = False
    parent_owned = False
    prefix_owned = False
    next_owned = False
    far_owned = False
    sibling_1169_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == 0x47F44 and owner == "code":
            parent_owned = True
        if start <= prefix_file < end and owner == "code":
            prefix_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= 0x590C6 < end and owner == "code":
            far_owned = True
        if start == sibling_1169 and end == sibling_1169_end and owner == "code":
            sibling_1169_owned = True
    if not owned:
        raise AssertionError("C6C2:11EF body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:12EE caller or C6C2:12D2 body is not owned")
    if not sibling_1169_owned:
        raise AssertionError("C6C2:1169 body was lost")
    if prefix_owned or next_owned or far_owned:
        raise AssertionError("leftover prefix, leftover 1345, or D90C:0006 was entered")
    if not _gap_at(prefix_file) or not _gap_at(0x46C2B):
        raise AssertionError("leftover prefix is owned")
    if not _gap_at(next_file):
        raise AssertionError("leftover 1345 is owned")
    if not _gap_at(0x590C6):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E) or not _gap_at(0x4921C):
        raise AssertionError("BCF9:000C, CA9B:029E, or C887:09AC is owned")


def _check_c6c2_1895(image: bytes, pin: dict) -> None:
    """C6C2:1895 is one closed first run through RETF. CALLN from follow_local 182D."""
    state = pin["state_c6c2_1895"]
    cs = 0xC6C2
    ip = 0x1895
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    parent_file = int(state["parent_file"], 16)
    next_file = int(state["next_file"], 16)
    far_callee = int(state["far_callee_file"], 16)
    d90c_file = int(state["d90c_file"], 16)
    forbidden = int(state["forbidden_file"], 16)
    leftover = int(state["leftover_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:1895 file or 20-bit address")
    if (phys20 >> 14) != 50:
        raise AssertionError("C6C2:1895 is not PGR slot 50")
    phys24 = (_u16(image, 0x7AD18) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD18) != 0x0032:
        raise AssertionError(f"C6C2:1895 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 50 or state["pgr_bytes"] != "3200" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD18:0x7AD1A].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 50 word moved")
    if state["caller_bytes"] != "e83300":
        raise AssertionError("185F CALLN bytes are not E8 33 00")
    if state["head_bytes"] != "5633f6569aee00f7":
        raise AssertionError("C6C2:1895 head bytes are not 56 33 F6 56 9A EE 00 F7")
    if state["tail_bytes"] != "7cf15ecb":
        raise AssertionError("C6C2:1895 tail bytes are not 7C F1 5E CB")
    if image[caller_file : caller_file + 3] != bytes.fromhex("e83300"):
        raise AssertionError("185F CALLN image bytes are not E8 33 00")
    if image[body_file:body_file + 8] != bytes.fromhex("5633f6569aee00f7"):
        raise AssertionError("C6C2:1895 head image bytes moved")
    if image[body_end - 4:body_end] != bytes.fromhex("7cf15ecb"):
        raise AssertionError("C6C2:1895 tail image bytes moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:1895 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:1895 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:1895 first run contains BRKXA/RETXA")
    if raw[0] != 0x56:
        raise AssertionError("1895 is not PUSH SI")
    xor_si = decode_one(image, cs, 0x1896)
    xor_modrm = image[xor_si.file + 1]
    if (
        xor_si.bytes_hex != "33f6"
        or (xor_modrm >> 6) != 3
        or ((xor_modrm >> 3) & 7) != 6
        or (xor_modrm & 7) != 6
    ):
        raise AssertionError("1896 does not write SI from SI")
    far = decode_one(image, cs, 0x1899)
    if (
        far.kind != "CALLF"
        or far.target_cs != 0xD1F7
        or far.target_ip != 0x00EE
        or far.bytes_hex != "9aee00f7d1"
    ):
        raise AssertionError("1899 is not CALLF D1F7:00EE")
    if image[far.file + 1] | (image[far.file + 2] << 8) != 0x00EE:
        raise AssertionError("1899 IP immediate is not 0x00EE")
    if ((0xD1F7 << 4) + 0x00EE) & 0x7FFFF != far_callee:
        raise AssertionError("D1F7:00EE file moved")
    add = decode_one(image, cs, 0x189E)
    add_modrm = image[add.file + 1]
    if (
        add.bytes_hex != "83c402"
        or (add_modrm >> 6) != 3
        or ((add_modrm >> 3) & 7) != 0
        or (add_modrm & 7) != 4
        or image[add.file + 2] != 0x02
    ):
        raise AssertionError("189E does not write SP from imm8 +2")
    cmp_si = decode_one(image, cs, 0x18A2)
    cmp_modrm = image[cmp_si.file + 1]
    if (
        cmp_si.bytes_hex != "83fe20"
        or (cmp_modrm >> 6) != 3
        or ((cmp_modrm >> 3) & 7) != 7
        or (cmp_modrm & 7) != 6
        or image[cmp_si.file + 2] != 0x20
    ):
        raise AssertionError("18A2 is not CMP SI, imm8 0x20")
    jl = decode_one(image, cs, 0x18A5)
    if jl.kind != "JCC" or jl.bytes_hex != state["jl_bytes"] or jl.target_ip != 0x1898:
        raise AssertionError("18A5 is not JL 1898")
    if image[jl.file] != 0x7C or jl.file != int(state["jl_file"], 16):
        raise AssertionError("18A5 is not opcode 7C")
    jl_rel8 = image[jl.file + 1]
    if jl_rel8 != 0xF1 or ((0x18A5 + 2 + (jl_rel8 - 256)) & 0xFFFF) != 0x1898:
        raise AssertionError("18A5 target is not 1898")
    pop = decode_one(image, cs, 0x18A7)
    retf = decode_one(image, cs, 0x18A8)
    if pop.bytes_hex != "5e" or image[pop.file] != 0x5E:
        raise AssertionError("18A7 does not write SI")
    if retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("18A8 is not RETF")
    parent, parent_hit = follow_local(image, cs, 0x182D, limit=80)
    if parent_hit:
        raise AssertionError("follow_local 182D hit a limit")
    caller = None
    for insn in parent:
        if insn.ip == 0x185F:
            caller = insn
            break
    if caller is None:
        raise AssertionError("follow_local 182D does not list 185F")
    parent_jnz = decode_one(image, cs, 0x1837)
    if (
        parent_jnz.kind != "JCC"
        or parent_jnz.bytes_hex != state["jnz_bytes"]
        or parent_jnz.target_ip != 0x184B
    ):
        raise AssertionError("1837 is not JNZ 184B")
    if image[parent_jnz.file] != 0x75 or parent_jnz.file != int(state["jnz_file"], 16):
        raise AssertionError("1837 is not opcode 75")
    parent_rel8 = image[parent_jnz.file + 1]
    if parent_rel8 != 0x12 or ((0x1837 + 2 + parent_rel8) & 0xFFFF) != 0x184B:
        raise AssertionError("1837 target is not 184B")
    if caller.ip <= 0x184B or caller.file >= 0x484B5:
        raise AssertionError("185F is not after 184B inside owned 182D")
    if not (0x4844D <= caller.file < 0x484B5):
        raise AssertionError("185F is not inside owned 182D")
    if (
        caller.kind != "CALLN"
        or caller.target_ip != ip
        or caller.file != caller_file
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("185F is not CALLN 1895")
    disp = image[caller_file + 1] | (image[caller_file + 2] << 8)
    if disp != 0x0033:
        raise AssertionError("185F disp16 is not 0x0033")
    if ((0x185F + 3 + disp) & 0xFFFF) != ip:
        raise AssertionError("185F disp16 is not +0x0033 to 1895")
    body, hit = follow_local(image, cs, ip, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:1895 walk hit a boundary")
    if body[-1].ip != 0x18A8 or body[-1].kind != "RETF":
        raise AssertionError("C6C2:1895 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:1895 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("C6C2:1895 first run does not start at 1895")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind in ("CALLN", "CALLF", "JMPN", "JMPF", "JMPS") and insn.file != far.file:
            raise AssertionError("C6C2:1895 first run has an extra direct transfer")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:1895 first run is not a contiguous span")
    if forbidden in covered or d90c_file in covered or leftover in covered:
        raise AssertionError("C6C2:1895 seed entered C887:09AC, D90C:0006, or leftover 1345")
    if far_callee in covered:
        raise AssertionError("C6C2:1895 seed entered D1F7:00EE")
    if body_end != next_file:
        raise AssertionError("C6C2:1895 seed extended past RETF")
    if body_file != 0x484B5 or parent_file != 0x4844D:
        raise AssertionError("C6C2:1895 is not adjacent to 182D")
    if body_end > forbidden:
        raise AssertionError("C6C2:1895 seed reached C887:09AC")
    owned = False
    caller_owned = False
    parent_owned = False
    next_owned = False
    d90c_owned = False
    forbidden_owned = False
    leftover_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == body_file and owner == "code":
            parent_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= d90c_file < end and owner == "code":
            d90c_owned = True
        if start <= forbidden < end and owner == "code":
            forbidden_owned = True
        if start <= leftover < end and owner == "code":
            leftover_owned = True
    if not owned:
        raise AssertionError("C6C2:1895 body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:185F caller or C6C2:182D body is not owned")
    if next_owned or d90c_owned or leftover_owned:
        raise AssertionError("leftover 18A9, D90C:0006, or leftover 1345 was entered")
    if not _gap_at(next_file):
        raise AssertionError("leftover 18A9 is owned")
    if not _gap_at(d90c_file):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(leftover):
        raise AssertionError("leftover 1345 is owned")
    if forbidden_owned or not _gap_at(forbidden):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E):
        raise AssertionError("BCF9:000C or CA9B:029E is owned")


def _check_d90c_0338(image: bytes, pin: dict) -> None:
    """D90C:0338 is one closed first run through RETF. CALLF from follow_local 182D."""
    state = pin["state_d90c_0338"]
    cs = 0xD90C
    ip = 0x0338
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    sibling_file = int(state["sibling_file"], 16)
    parent_file = int(state["parent_file"], 16)
    next_file = int(state["next_file"], 16)
    prefix_file = int(state["prefix_file"], 16)
    callee = int(state["callee_file"], 16)
    d90c_0006 = int(state["d90c_0006"], 16)
    d90c_0454 = int(state["d90c_0454"], 16)
    forbidden = int(state["forbidden_file"], 16)
    leftover = int(state["leftover_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("D90C:0338 file or 20-bit address")
    if (phys20 >> 14) != 54:
        raise AssertionError("D90C:0338 is not PGR slot 54")
    phys24 = (_u16(image, 0x7AD20) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD20) != 0x0036:
        raise AssertionError(f"D90C:0338 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 54 or state["pgr_bytes"] != "3600" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD20:0x7AD22].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 54 word moved")
    if state["caller_bytes"] != "9a38030cd9":
        raise AssertionError("1873 CALLF bytes are not 9A 38 03 0C D9")
    if state["sibling_bytes"] != "9a54040cd9":
        raise AssertionError("1868 CALLF bytes are not 9A 54 04 0C D9")
    if state["head_bytes"] != "558becba01c0b003":
        raise AssertionError("D90C:0338 head bytes are not 55 8B EC BA 01 C0 B0 03")
    if state["tail_bytes"] != "75fa5dcb":
        raise AssertionError("D90C:0338 tail bytes are not 75 FA 5D CB")
    if image[caller_file : caller_file + 5] != bytes.fromhex("9a38030cd9"):
        raise AssertionError("1873 CALLF image bytes are not 9A 38 03 0C D9")
    if image[sibling_file : sibling_file + 5] != bytes.fromhex("9a54040cd9"):
        raise AssertionError("1868 CALLF image bytes are not 9A 54 04 0C D9")
    if image[body_file:body_file + 8] != bytes.fromhex("558becba01c0b003"):
        raise AssertionError("D90C:0338 head image bytes moved")
    if image[body_end - 4:body_end] != bytes.fromhex("75fa5dcb"):
        raise AssertionError("D90C:0338 tail image bytes moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("D90C:0338 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("D90C:0338 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("D90C:0338 first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("0338 is not PUSH BP")
    mov_bp = decode_one(image, cs, 0x0339)
    mov_modrm = image[mov_bp.file + 1]
    if (
        mov_bp.bytes_hex != "8bec"
        or (mov_modrm >> 6) != 3
        or ((mov_modrm >> 3) & 7) != 5
        or (mov_modrm & 7) != 4
    ):
        raise AssertionError("0339 does not write BP from SP")
    mov_dx = decode_one(image, cs, 0x033B)
    if mov_dx.bytes_hex != "ba01c0" or image[mov_dx.file] != 0xBA:
        raise AssertionError("033B does not write DX from imm16 0xC001")
    if image[mov_dx.file + 1] | (image[mov_dx.file + 2] << 8) != 0xC001:
        raise AssertionError("033B imm16 is not 0xC001")
    calln = decode_one(image, cs, 0x0360)
    if (
        calln.kind != "CALLN"
        or calln.target_ip != 0x0574
        or calln.bytes_hex != state["calln_bytes"]
        or calln.file != int(state["calln_file"], 16)
    ):
        raise AssertionError("0360 is not CALLN 0574")
    if image[calln.file] != 0xE8:
        raise AssertionError("0360 is not opcode E8")
    calln_disp = image[calln.file + 1] | (image[calln.file + 2] << 8)
    if calln_disp != 0x0211:
        raise AssertionError("0360 disp16 is not 0x0211")
    if ((0x0360 + 3 + calln_disp) & 0xFFFF) != 0x0574:
        raise AssertionError("0360 disp16 is not +0x0211 to 0574")
    if ((cs << 4) + 0x0574) & 0x7FFFF != callee:
        raise AssertionError("D90C:0574 file moved")
    jz = decode_one(image, cs, 0x0367)
    if jz.kind != "JCC" or jz.bytes_hex != state["jz_bytes"] or jz.target_ip != 0x03B2:
        raise AssertionError("0367 is not JZ 03B2")
    if image[jz.file] != 0x74 or jz.file != int(state["jz_file"], 16):
        raise AssertionError("0367 is not opcode 74")
    jz_rel8 = image[jz.file + 1]
    if jz_rel8 != 0x49 or ((0x0367 + 2 + jz_rel8) & 0xFFFF) != 0x03B2:
        raise AssertionError("0367 target is not 03B2")
    jmpn = decode_one(image, cs, 0x03AF)
    if (
        jmpn.kind != "JMPN"
        or jmpn.target_ip != 0x0439
        or jmpn.bytes_hex != state["jmpn_bytes"]
        or jmpn.file != int(state["jmpn_file"], 16)
    ):
        raise AssertionError("03AF is not JMPN 0439")
    if image[jmpn.file] != 0xE9:
        raise AssertionError("03AF is not opcode E9")
    jmpn_disp = image[jmpn.file + 1] | (image[jmpn.file + 2] << 8)
    if jmpn_disp != 0x0087:
        raise AssertionError("03AF disp16 is not 0x0087")
    if ((0x03AF + 3 + jmpn_disp) & 0xFFFF) != 0x0439:
        raise AssertionError("03AF disp16 is not +0x0087 to 0439")
    jnz = decode_one(image, cs, 0x043D)
    if jnz.kind != "JCC" or jnz.bytes_hex != state["jnz_bytes"] or jnz.target_ip != 0x0439:
        raise AssertionError("043D is not JNZ 0439")
    if image[jnz.file] != 0x75 or jnz.file != int(state["jnz_file"], 16):
        raise AssertionError("043D is not opcode 75")
    jnz_rel8 = image[jnz.file + 1]
    if jnz_rel8 != 0xFA or ((0x043D + 2 + (jnz_rel8 - 256)) & 0xFFFF) != 0x0439:
        raise AssertionError("043D target is not 0439")
    pop = decode_one(image, cs, 0x043F)
    retf = decode_one(image, cs, 0x0440)
    if pop.bytes_hex != "5d" or image[pop.file] != 0x5D:
        raise AssertionError("043F does not write BP")
    if retf.kind != "RETF" or retf.bytes_hex != "cb":
        raise AssertionError("0440 is not RETF")
    parent, parent_hit = follow_local(image, 0xC6C2, 0x182D, limit=80)
    if parent_hit:
        raise AssertionError("follow_local 182D hit a limit")
    caller = None
    sibling = None
    for insn in parent:
        if insn.ip == 0x1873:
            caller = insn
        if insn.ip == 0x1868:
            sibling = insn
    if caller is None:
        raise AssertionError("follow_local 182D does not list 1873")
    if sibling is None:
        raise AssertionError("follow_local 182D does not list 1868")
    if not (0x4844D <= caller.file < 0x484B5) or caller.file != caller_file:
        raise AssertionError("1873 is not inside owned 182D")
    if (
        caller.kind != "CALLF"
        or caller.target_cs != cs
        or caller.target_ip != ip
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("1873 is not CALLF D90C:0338")
    if image[caller.file] != 0x9A:
        raise AssertionError("1873 is not opcode 9A")
    caller_ip_imm = image[caller.file + 1] | (image[caller.file + 2] << 8)
    caller_cs_imm = image[caller.file + 3] | (image[caller.file + 4] << 8)
    if caller_ip_imm != 0x0338 or caller_cs_imm != 0xD90C:
        raise AssertionError("1873 immediates are not D90C:0338")
    if (
        sibling.kind != "CALLF"
        or sibling.target_cs != cs
        or sibling.target_ip != 0x0454
        or sibling.file != sibling_file
        or sibling.bytes_hex != state["sibling_bytes"]
    ):
        raise AssertionError("1868 is not CALLF D90C:0454")
    if image[sibling.file] != 0x9A:
        raise AssertionError("1868 is not opcode 9A")
    sibling_ip_imm = image[sibling.file + 1] | (image[sibling.file + 2] << 8)
    sibling_cs_imm = image[sibling.file + 3] | (image[sibling.file + 4] << 8)
    if sibling_ip_imm != 0x0454 or sibling_cs_imm != 0xD90C:
        raise AssertionError("1868 immediates are not D90C:0454")
    if parent_file != 0x4844D:
        raise AssertionError("C6C2:182D parent file moved")
    body, hit = follow_local(image, cs, ip, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("D90C:0338 walk hit a boundary")
    if body[-1].ip != 0x0440 or body[-1].kind != "RETF":
        raise AssertionError("D90C:0338 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("D90C:0338 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("D90C:0338 first run does not start at 0338")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind in ("JMPN_RM", "JMPF_RM", "CALLF", "JMPF", "JMPS"):
            raise AssertionError("D90C:0338 first run has an extra direct transfer")
        if insn.kind == "CALLN" and insn.file != calln.file:
            raise AssertionError("D90C:0338 first run has an extra CALLN")
        if insn.kind == "JMPN" and insn.file != jmpn.file:
            raise AssertionError("D90C:0338 first run has an extra JMPN")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("D90C:0338 first run is not a contiguous span")
    if callee in covered:
        raise AssertionError("D90C:0338 seed entered D90C:0574")
    if d90c_0006 in covered or d90c_0454 in covered or leftover in covered:
        raise AssertionError("D90C:0338 seed entered D90C:0006, D90C:0454, or leftover 1345")
    if forbidden in covered:
        raise AssertionError("D90C:0338 seed entered C887:09AC")
    if body_end != next_file:
        raise AssertionError("D90C:0338 seed extended past RETF")
    if forbidden in range(body_file, body_end):
        raise AssertionError("D90C:0338 seed reached C887:09AC")
    owned = False
    caller_owned = False
    parent_owned = False
    next_owned = False
    prefix_owned = False
    d90c_0006_owned = False
    d90c_0454_owned = False
    forbidden_owned = False
    leftover_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == 0x484B5 and owner == "code":
            parent_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= prefix_file < end and owner == "code":
            prefix_owned = True
        if start <= d90c_0006 < end and owner == "code":
            d90c_0006_owned = True
        if start <= d90c_0454 < end and owner == "code":
            d90c_0454_owned = True
        if start <= forbidden < end and owner == "code":
            forbidden_owned = True
        if start <= leftover < end and owner == "code":
            leftover_owned = True
    if not owned:
        raise AssertionError("D90C:0338 body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:1873 caller or C6C2:182D body is not owned")
    if next_owned or prefix_owned:
        raise AssertionError("leftover 0441 or D90C gap prefix was entered")
    if d90c_0006_owned or d90c_0454_owned or leftover_owned:
        raise AssertionError("D90C:0006, D90C:0454, or leftover 1345 was entered")
    if not _gap_at(next_file):
        raise AssertionError("leftover 0441 is owned")
    if not _gap_at(prefix_file):
        raise AssertionError("D90C gap prefix is owned")
    if not _gap_at(d90c_0006):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(d90c_0454):
        raise AssertionError("D90C:0454 is owned")
    if not _gap_at(leftover):
        raise AssertionError("leftover 1345 is owned")
    if forbidden_owned or not _gap_at(forbidden):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E):
        raise AssertionError("BCF9:000C or CA9B:029E is owned")


def _check_d90c_0574(image: bytes, pin: dict) -> None:
    """D90C:0574 is one closed first run through RET. CALLN from follow_local 0338."""
    state = pin["state_d90c_0574"]
    cs = 0xD90C
    ip = 0x0574
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    parent_file = int(state["parent_file"], 16)
    parent_end = int(state["parent_end"], 16)
    next_file = int(state["next_file"], 16)
    prefix_file = int(state["prefix_file"], 16)
    d90c_0006 = int(state["d90c_0006"], 16)
    d90c_0454 = int(state["d90c_0454"], 16)
    forbidden = int(state["forbidden_file"], 16)
    leftover = int(state["leftover_file"], 16)
    after_file = int(state["after_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("D90C:0574 file or 20-bit address")
    if (phys20 >> 14) != 54:
        raise AssertionError("D90C:0574 is not PGR slot 54")
    phys24 = (_u16(image, 0x7AD20) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD20) != 0x0036:
        raise AssertionError(f"D90C:0574 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 54 or state["pgr_bytes"] != "3600" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD20:0x7AD22].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 54 word moved")
    if state["caller_bytes"] != "e81102":
        raise AssertionError("0360 CALLN bytes are not E8 11 02")
    if state["head_bytes"] != "ba08c0bb0fc0b814":
        raise AssertionError("D90C:0574 head bytes are not BA 08 C0 BB 0F C0 B8 14")
    if state["tail_bytes"] != "8ac5ef9dc3":
        raise AssertionError("D90C:0574 tail bytes are not 8A C5 EF 9D C3")
    if image[caller_file : caller_file + 3] != bytes.fromhex("e81102"):
        raise AssertionError("0360 CALLN image bytes are not E8 11 02")
    if image[body_file:body_file + 8] != bytes.fromhex("ba08c0bb0fc0b814"):
        raise AssertionError("D90C:0574 head image bytes moved")
    if image[body_end - 5:body_end] != bytes.fromhex("8ac5ef9dc3"):
        raise AssertionError("D90C:0574 tail image bytes moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("D90C:0574 head bytes moved")
    if image[body_end - 5:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("D90C:0574 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("D90C:0574 first run contains BRKXA/RETXA")
    mov_dx = decode_one(image, cs, ip)
    if image[mov_dx.file] != 0xBA or mov_dx.bytes_hex != "ba08c0":
        raise AssertionError("0574 does not write DX from imm16")
    dx_imm = image[mov_dx.file + 1] | (image[mov_dx.file + 2] << 8)
    if dx_imm != 0xC008:
        raise AssertionError("0574 imm16 is not 0xC008")
    mov_bx = decode_one(image, cs, 0x0577)
    if image[mov_bx.file] != 0xBB or mov_bx.bytes_hex != "bb0fc0":
        raise AssertionError("0577 does not write BX from imm16")
    bx_imm = image[mov_bx.file + 1] | (image[mov_bx.file + 2] << 8)
    if bx_imm != 0xC00F:
        raise AssertionError("0577 imm16 is not 0xC00F")
    mov_ax = decode_one(image, cs, 0x057A)
    if image[mov_ax.file] != 0xB8 or mov_ax.bytes_hex != "b81400":
        raise AssertionError("057A does not write AX from imm16")
    ax_imm = image[mov_ax.file + 1] | (image[mov_ax.file + 2] << 8)
    if ax_imm != 0x0014:
        raise AssertionError("057A imm16 is not 0x0014")
    mov_ch = decode_one(image, cs, 0x057D)
    if image[mov_ch.file] != 0xB5 or mov_ch.bytes_hex != "b510":
        raise AssertionError("057D does not write CH from imm8")
    mov_al = decode_one(image, cs, 0x058A)
    mov_modrm = image[mov_al.file + 1]
    if (
        mov_al.bytes_hex != "8ac5"
        or (mov_modrm >> 6) != 3
        or ((mov_modrm >> 3) & 7) != 0
        or (mov_modrm & 7) != 5
    ):
        raise AssertionError("058A does not write AL from CH")
    popf = decode_one(image, cs, 0x058D)
    ret = decode_one(image, cs, 0x058E)
    if popf.bytes_hex != "9d" or image[popf.file] != 0x9D:
        raise AssertionError("058D is not POPF")
    if ret.kind != "RET" or ret.bytes_hex != "c3":
        raise AssertionError("058E is not RET")
    parent, parent_hit = follow_local(image, cs, 0x0338, limit=200)
    if parent_hit:
        raise AssertionError("follow_local 0338 hit a limit")
    caller = None
    for insn in parent:
        if insn.ip == 0x0360:
            caller = insn
            break
    if caller is None:
        raise AssertionError("follow_local 0338 does not list 0360")
    if not (0x593F8 <= caller.file < 0x59501) or caller.file != caller_file:
        raise AssertionError("0360 is not inside owned 0338")
    if (
        caller.kind != "CALLN"
        or caller.target_ip != ip
        or caller.target_cs != cs
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("0360 is not CALLN D90C:0574")
    if image[caller.file] != 0xE8:
        raise AssertionError("0360 is not opcode E8")
    disp = image[caller.file + 1] | (image[caller.file + 2] << 8)
    if disp != 0x0211:
        raise AssertionError("0360 disp16 is not 0x0211")
    if ((0x0360 + 3 + disp) & 0xFFFF) != ip:
        raise AssertionError("0360 disp16 is not +0x0211 to 0574")
    if parent_file != 0x593F8 or parent_end != 0x59501:
        raise AssertionError("D90C:0338 parent file moved")
    body, hit = follow_local(image, cs, ip, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("D90C:0574 walk hit a boundary")
    if body[-1].ip != 0x058E or body[-1].kind != "RET":
        raise AssertionError("D90C:0574 does not end at RET")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("D90C:0574 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("D90C:0574 first run does not start at 0574")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind in ("CALLN", "CALLF", "JMPN", "JMPF", "JMPS", "JCC"):
            raise AssertionError("D90C:0574 first run has a direct transfer")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("D90C:0574 first run is not a contiguous span")
    if d90c_0006 in covered or d90c_0454 in covered or leftover in covered:
        raise AssertionError("D90C:0574 seed entered D90C:0006, D90C:0454, or leftover 1345")
    if forbidden in covered:
        raise AssertionError("D90C:0574 seed entered C887:09AC")
    if next_file in covered or after_file in covered:
        raise AssertionError("D90C:0574 seed extended past RET")
    if body_end != next_file:
        raise AssertionError("D90C:0574 seed extended past RET")
    if forbidden in range(body_file, body_end):
        raise AssertionError("D90C:0574 seed reached C887:09AC")
    if image[next_file] != 0xFF:
        raise AssertionError("byte after 0574 RET is not 0xFF")
    owned = False
    caller_owned = False
    parent_owned = False
    prefix_owned = False
    d90c_0006_owned = False
    d90c_0454_owned = False
    forbidden_owned = False
    leftover_owned = False
    pad_owned = False
    after_owned = False
    for start, end, owner, kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == parent_end and owner == "code":
            parent_owned = True
        if start <= prefix_file < end and owner == "code":
            prefix_owned = True
        if start <= d90c_0006 < end and owner == "code":
            d90c_0006_owned = True
        if start <= d90c_0454 < end and owner == "code":
            d90c_0454_owned = True
        if start <= forbidden < end and owner == "code":
            forbidden_owned = True
        if start <= leftover < end and owner == "code":
            leftover_owned = True
        if start <= next_file < end and owner == "code":
            pad_owned = True
        if start == after_file and owner == "code":
            after_owned = True
    if not owned:
        raise AssertionError("D90C:0574 body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("D90C:0360 caller or D90C:0338 body is not owned")
    if prefix_owned or d90c_0006_owned or d90c_0454_owned or leftover_owned:
        raise AssertionError("leftover 0441, D90C:0006, D90C:0454, or leftover 1345 was entered")
    if pad_owned:
        raise AssertionError("0xFF after 0574 RET was entered")
    if not after_owned:
        raise AssertionError("owned D90C:0590 after the 0xFF was lost")
    if not _gap_at(prefix_file):
        raise AssertionError("leftover 0441 is owned")
    if not _gap_at(next_file):
        raise AssertionError("0xFF after 0574 RET is owned")
    if not _gap_at(d90c_0006):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(d90c_0454):
        raise AssertionError("D90C:0454 is owned")
    if not _gap_at(leftover):
        raise AssertionError("leftover 1345 is owned")
    if forbidden_owned or not _gap_at(forbidden):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E):
        raise AssertionError("BCF9:000C or CA9B:029E is owned")


def _check_d90c_01ad(image: bytes, pin: dict) -> None:
    """D90C:01AD is one closed first run through RETF. CALLF from follow_local 1362."""
    state = pin["state_d90c_01ad"]
    cs = 0xD90C
    ip = 0x01AD
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    parent_file = int(state["parent_file"], 16)
    parent_end = int(state["parent_end"], 16)
    next_file = int(state["next_file"], 16)
    prefix_file = int(state["prefix_file"], 16)
    d90c_0006 = int(state["d90c_0006"], 16)
    d90c_0454 = int(state["d90c_0454"], 16)
    d90c_0099 = int(state["d90c_0099"], 16)
    d90c_04d9 = int(state["d90c_04d9"], 16)
    forbidden = int(state["forbidden_file"], 16)
    leftover = int(state["leftover_file"], 16)
    pad_file = int(state["pad_file"], 16)
    sibling_0338 = int(state["sibling_0338"], 16)
    sibling_0338_end = int(state["sibling_0338_end"], 16)
    sibling_0574 = int(state["sibling_0574"], 16)
    sibling_0574_end = int(state["sibling_0574_end"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("D90C:01AD file or 20-bit address")
    if (phys20 >> 14) != 54:
        raise AssertionError("D90C:01AD is not PGR slot 54")
    phys24 = (_u16(image, 0x7AD20) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD20) != 0x0036:
        raise AssertionError(f"D90C:01AD 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 54 or state["pgr_bytes"] != "3600" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD20:0x7AD22].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 54 word moved")
    if state["caller_bytes"] != "9aad010cd9":
        raise AssertionError("1458 CALLF bytes are not 9A AD 01 0C D9")
    if state["head_bytes"] != "b80000e760e5648b":
        raise AssertionError("D90C:01AD head bytes are not B8 00 00 E7 60 E5 64 8B")
    if state["tail_bytes"] != "d2e30ad3cb":
        raise AssertionError("D90C:01AD tail bytes are not D2 E3 0A D3 CB")
    if image[caller_file : caller_file + 5] != bytes.fromhex("9aad010cd9"):
        raise AssertionError("1458 CALLF image bytes are not 9A AD 01 0C D9")
    if image[body_file:body_file + 8] != bytes.fromhex("b80000e760e5648b"):
        raise AssertionError("D90C:01AD head image bytes moved")
    if image[body_end - 5:body_end] != bytes.fromhex("d2e30ad3cb"):
        raise AssertionError("D90C:01AD tail image bytes moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("D90C:01AD head bytes moved")
    if image[body_end - 5:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("D90C:01AD tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("D90C:01AD first run contains BRKXA/RETXA")
    mov_ax = decode_one(image, cs, ip)
    if image[mov_ax.file] != 0xB8 or mov_ax.bytes_hex != "b80000":
        raise AssertionError("01AD does not write AX from imm16")
    ax_imm = image[mov_ax.file + 1] | (image[mov_ax.file + 2] << 8)
    if ax_imm != 0x0000:
        raise AssertionError("01AD imm16 is not 0x0000")
    out60 = decode_one(image, cs, 0x01B0)
    if (
        out60.bytes_hex != state["out_bytes"]
        or image[out60.file] != 0xE7
        or image[out60.file + 1] != 0x60
        or out60.file != int(state["out_file"], 16)
    ):
        raise AssertionError("01B0 is not OUT 0x60, AX")
    in64 = decode_one(image, cs, 0x01B2)
    if (
        in64.bytes_hex != state["in_bytes"]
        or image[in64.file] != 0xE5
        or image[in64.file + 1] != 0x64
        or in64.file != int(state["in_file"], 16)
    ):
        raise AssertionError("01B2 is not IN AX, 0x64")
    mov_dx = decode_one(image, cs, 0x01B4)
    mov_modrm = image[mov_dx.file + 1]
    if (
        mov_dx.bytes_hex != "8bd0"
        or (mov_modrm >> 6) != 3
        or ((mov_modrm >> 3) & 7) != 2
        or (mov_modrm & 7) != 0
    ):
        raise AssertionError("01B4 does not write DX from AX")
    mov_cx = decode_one(image, cs, 0x01BC)
    if image[mov_cx.file] != 0xB9 or mov_cx.bytes_hex != "b90c00":
        raise AssertionError("01BC does not write CX from imm16")
    cx_imm = image[mov_cx.file + 1] | (image[mov_cx.file + 2] << 8)
    if cx_imm != 0x000C:
        raise AssertionError("01BC imm16 is not 0x000C")
    loop = decode_one(image, cs, 0x01C4)
    if loop.kind != "JCC" or loop.bytes_hex != state["loop_bytes"] or loop.target_ip != 0x01BF:
        raise AssertionError("01C4 is not LOOP 01BF")
    if image[loop.file] != 0xE2 or loop.file != int(state["loop_file"], 16):
        raise AssertionError("01C4 is not opcode E2")
    loop_rel8 = image[loop.file + 1]
    if loop_rel8 != 0xF9 or ((0x01C4 + 2 + (loop_rel8 - 256)) & 0xFFFF) != 0x01BF:
        raise AssertionError("01C4 target is not 01BF")
    retf = decode_one(image, cs, 0x01CC)
    if retf.kind != "RETF" or retf.bytes_hex != "cb" or image[retf.file] != 0xCB:
        raise AssertionError("01CC is not RETF")
    parent, parent_hit = follow_local(image, 0xC6C2, 0x1362, limit=400)
    if parent_hit:
        raise AssertionError("follow_local 1362 hit a limit")
    if any(insn.file == body_file or insn.ip == ip for insn in parent):
        raise AssertionError("follow_local 1362 entered D90C:01AD")
    caller = None
    for insn in parent:
        if insn.ip == 0x1458:
            caller = insn
            break
    if caller is None:
        raise AssertionError("follow_local 1362 does not list 1458")
    if not (0x47F82 <= caller.file < 0x48209) or caller.file != caller_file:
        raise AssertionError("1458 is not inside owned 1362")
    if (
        caller.kind != "CALLF"
        or caller.target_cs != cs
        or caller.target_ip != ip
        or caller.bytes_hex != state["caller_bytes"]
    ):
        raise AssertionError("1458 is not CALLF D90C:01AD")
    if image[caller.file] != 0x9A:
        raise AssertionError("1458 is not opcode 9A")
    caller_ip_imm = image[caller.file + 1] | (image[caller.file + 2] << 8)
    caller_cs_imm = image[caller.file + 3] | (image[caller.file + 4] << 8)
    if caller_ip_imm != 0x01AD or caller_cs_imm != 0xD90C:
        raise AssertionError("1458 immediates are not D90C:01AD")
    if parent_file != 0x47F82 or parent_end != 0x48209:
        raise AssertionError("C6C2:1362 parent file moved")
    body, hit = follow_local(image, cs, ip, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("D90C:01AD walk hit a boundary")
    if body[-1].ip != 0x01CC or body[-1].kind != "RETF":
        raise AssertionError("D90C:01AD does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("D90C:01AD first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("D90C:01AD first run does not start at 01AD")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind in ("CALLN", "CALLF", "JMPN", "JMPF", "JMPS"):
            raise AssertionError("D90C:01AD first run has a direct transfer")
        if insn.kind == "JCC" and insn.file != loop.file:
            raise AssertionError("D90C:01AD first run has an extra JCC")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("D90C:01AD first run is not a contiguous span")
    if d90c_0006 in covered or d90c_0454 in covered or leftover in covered:
        raise AssertionError("D90C:01AD seed entered D90C:0006, D90C:0454, or leftover 1345")
    if d90c_0099 in covered or d90c_04d9 in covered:
        raise AssertionError("D90C:01AD seed entered D90C:0099 or D90C:04D9")
    if forbidden in covered:
        raise AssertionError("D90C:01AD seed entered C887:09AC")
    if next_file in covered or pad_file in covered:
        raise AssertionError("D90C:01AD seed extended past RETF")
    if body_end != next_file:
        raise AssertionError("D90C:01AD seed extended past RETF")
    if forbidden in range(body_file, body_end):
        raise AssertionError("D90C:01AD seed reached C887:09AC")
    owned = False
    caller_owned = False
    parent_owned = False
    prefix_owned = False
    next_owned = False
    d90c_0006_owned = False
    d90c_0454_owned = False
    d90c_0099_owned = False
    d90c_04d9_owned = False
    forbidden_owned = False
    leftover_owned = False
    pad_owned = False
    sibling_0338_owned = False
    sibling_0574_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == parent_end and owner == "code":
            parent_owned = True
        if start <= prefix_file < end and owner == "code":
            prefix_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= d90c_0006 < end and owner == "code":
            d90c_0006_owned = True
        if start <= d90c_0454 < end and owner == "code":
            d90c_0454_owned = True
        if start <= d90c_0099 < end and owner == "code":
            d90c_0099_owned = True
        if start <= d90c_04d9 < end and owner == "code":
            d90c_04d9_owned = True
        if start <= forbidden < end and owner == "code":
            forbidden_owned = True
        if start <= leftover < end and owner == "code":
            leftover_owned = True
        if start <= pad_file < end and owner == "code":
            pad_owned = True
        if start == sibling_0338 and end == sibling_0338_end and owner == "code":
            sibling_0338_owned = True
        if start == sibling_0574 and end == sibling_0574_end and owner == "code":
            sibling_0574_owned = True
    if not owned:
        raise AssertionError("D90C:01AD body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:1458 caller or C6C2:1362 body is not owned")
    if not sibling_0338_owned or not sibling_0574_owned:
        raise AssertionError("D90C:0338 or D90C:0574 body was lost")
    if prefix_owned or next_owned:
        raise AssertionError("D90C gap prefix or byte after 01AD RETF was entered")
    if d90c_0006_owned or d90c_0454_owned or leftover_owned:
        raise AssertionError("D90C:0006, D90C:0454, or leftover 1345 was entered")
    if d90c_0099_owned or d90c_04d9_owned:
        raise AssertionError("D90C:0099 or D90C:04D9 was entered")
    if pad_owned:
        raise AssertionError("0xFF after 0574 RET was entered")
    if not _gap_at(prefix_file):
        raise AssertionError("D90C gap prefix is owned")
    if not _gap_at(next_file):
        raise AssertionError("byte after 01AD RETF is owned")
    if not _gap_at(d90c_0006):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(d90c_0454):
        raise AssertionError("D90C:0454 is owned")
    if not _gap_at(d90c_0099):
        raise AssertionError("D90C:0099 is owned")
    if not _gap_at(d90c_04d9):
        raise AssertionError("D90C:04D9 is owned")
    if not _gap_at(leftover):
        raise AssertionError("leftover 1345 is owned")
    if not _gap_at(pad_file):
        raise AssertionError("0xFF after 0574 RET is owned")
    if forbidden_owned or not _gap_at(forbidden):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E):
        raise AssertionError("BCF9:000C or CA9B:029E is owned")


def _check_c6c2_0d24(image: bytes, pin: dict) -> None:
    """C6C2:0D24 is one closed first run through RETF. CALLN from follow_local 1362."""
    state = pin["state_c6c2_0d24"]
    cs = 0xC6C2
    ip = 0x0D24
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    parent_file = int(state["parent_file"], 16)
    parent_end = int(state["parent_end"], 16)
    next_file = int(state["next_file"], 16)
    prefix_file = int(state["prefix_file"], 16)
    gap_start = int(state["gap_start"], 16)
    c6c2_1169 = int(state["c6c2_1169"], 16)
    c6c2_1169_end = int(state["c6c2_1169_end"], 16)
    sibling_11ef = int(state["sibling_11ef"], 16)
    sibling_11ef_end = int(state["sibling_11ef_end"], 16)
    d90c_0006 = int(state["d90c_0006"], 16)
    d90c_0454 = int(state["d90c_0454"], 16)
    d90c_0099 = int(state["d90c_0099"], 16)
    d90c_04d9 = int(state["d90c_04d9"], 16)
    d90c_01ad = int(state["d90c_01ad"], 16)
    d90c_01ad_end = int(state["d90c_01ad_end"], 16)
    forbidden = int(state["forbidden_file"], 16)
    leftover = int(state["leftover_file"], 16)
    pad_file = int(state["pad_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:0D24 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C6C2:0D24 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C6C2:0D24 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD16:0x7AD18].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 49 word moved")
    if state["caller_bytes"] != "e86cf8":
        raise AssertionError("14B5 CALLN bytes are not E8 6C F8")
    if state["head_bytes"] != "558bec83ec0e5657":
        raise AssertionError("C6C2:0D24 head bytes are not 55 8B EC 83 EC 0E 56 57")
    if state["tail_bytes"] != "5f5ec9cb":
        raise AssertionError("C6C2:0D24 tail bytes are not 5F 5E C9 CB")
    if image[caller_file : caller_file + 3] != bytes.fromhex("e86cf8"):
        raise AssertionError("14B5 CALLN image bytes are not E8 6C F8")
    if image[body_file:body_file + 8] != bytes.fromhex("558bec83ec0e5657"):
        raise AssertionError("C6C2:0D24 head image bytes moved")
    if image[body_end - 4:body_end] != bytes.fromhex("5f5ec9cb"):
        raise AssertionError("C6C2:0D24 tail image bytes moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:0D24 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:0D24 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:0D24 first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("0D24 is not PUSH BP")
    mov_bp = decode_one(image, cs, 0x0D25)
    mov_modrm = image[mov_bp.file + 1]
    if (
        mov_bp.bytes_hex != "8bec"
        or (mov_modrm >> 6) != 3
        or ((mov_modrm >> 3) & 7) != 5
        or (mov_modrm & 7) != 4
    ):
        raise AssertionError("0D25 does not write BP from SP")
    sub_sp = decode_one(image, cs, 0x0D27)
    sub_modrm = image[sub_sp.file + 1]
    if (
        sub_sp.bytes_hex != "83ec0e"
        or (sub_modrm >> 6) != 3
        or ((sub_modrm >> 3) & 7) != 5
        or (sub_modrm & 7) != 4
        or image[sub_sp.file + 2] != 0x0E
    ):
        raise AssertionError("0D27 does not write SP from imm8 0x0E")
    mov_si = decode_one(image, cs, 0x0D2C)
    si_modrm = image[mov_si.file + 1]
    if (
        mov_si.bytes_hex != "8b7606"
        or (si_modrm >> 6) != 1
        or ((si_modrm >> 3) & 7) != 6
        or (si_modrm & 7) != 6
    ):
        raise AssertionError("0D2C does not write SI from [BP+6]")
    zero = decode_one(image, cs, 0x0D37)
    if (
        zero.bytes_hex != state["zero_bytes"]
        or image[zero.file] != 0xC7
        or zero.file != int(state["zero_file"], 16)
    ):
        raise AssertionError("0D37 is not MOV [D69F], imm16")
    zero_imm = image[zero.file + 4] | (image[zero.file + 5] << 8)
    if zero_imm != 0x0000:
        raise AssertionError("0D37 imm16 is not 0x0000")
    jnb = decode_one(image, cs, 0x0D7B)
    if jnb.kind != "JCC" or jnb.bytes_hex != state["jnb_bytes"] or jnb.target_ip != 0x0D8B:
        raise AssertionError("0D7B is not JNB 0D8B")
    if image[jnb.file] != 0x73 or jnb.file != int(state["jnb_file"], 16):
        raise AssertionError("0D7B is not opcode 73")
    jnb_rel8 = image[jnb.file + 1]
    if jnb_rel8 != 0x0E or ((0x0D7B + 2 + jnb_rel8) & 0xFFFF) != 0x0D8B:
        raise AssertionError("0D7B target is not 0D8B")
    jmps = decode_one(image, cs, 0x0D89)
    if jmps.kind != "JMPS" or jmps.bytes_hex != state["jmps_bytes"] or jmps.target_ip != 0x0D9A:
        raise AssertionError("0D89 is not JMPS 0D9A")
    if image[jmps.file] != 0xEB or jmps.file != int(state["jmps_file"], 16):
        raise AssertionError("0D89 is not opcode EB")
    jmps_rel8 = image[jmps.file + 1]
    if jmps_rel8 != 0x0F or ((0x0D89 + 2 + jmps_rel8) & 0xFFFF) != 0x0D9A:
        raise AssertionError("0D89 target is not 0D9A")
    pop_di = decode_one(image, cs, 0x0E47)
    pop_si = decode_one(image, cs, 0x0E48)
    leave = decode_one(image, cs, 0x0E49)
    retf = decode_one(image, cs, 0x0E4A)
    if pop_di.bytes_hex != "5f" or pop_si.bytes_hex != "5e":
        raise AssertionError("0E47 is not POP DI / POP SI")
    if leave.bytes_hex != "c9" or retf.kind != "RETF" or retf.bytes_hex != "cb" or image[retf.file] != 0xCB:
        raise AssertionError("0E4A is not RETF")
    parent, parent_hit = follow_local(image, cs, 0x1362, limit=400)
    if parent_hit:
        raise AssertionError("follow_local 1362 hit a limit")
    if any(insn.file == body_file or insn.ip == ip for insn in parent):
        raise AssertionError("follow_local 1362 entered C6C2:0D24")
    caller = None
    for insn in parent:
        if insn.ip == 0x14B5:
            caller = insn
            break
    if caller is None:
        raise AssertionError("follow_local 1362 does not list 14B5")
    if not (0x47F82 <= caller.file < 0x48209) or caller.file != caller_file:
        raise AssertionError("14B5 is not inside owned 1362")
    if caller.kind != "CALLN" or caller.target_ip != ip or caller.bytes_hex != state["caller_bytes"]:
        raise AssertionError("14B5 is not CALLN C6C2:0D24")
    if image[caller.file] != 0xE8:
        raise AssertionError("14B5 is not opcode E8")
    caller_disp = image[caller.file + 1] | (image[caller.file + 2] << 8)
    if caller_disp != 0xF86C or ((0x14B5 + 3 + caller_disp - 0x10000) & 0xFFFF) != ip:
        raise AssertionError("14B5 disp16 is not -0x0794 to 0D24")
    if parent_file != 0x47F82 or parent_end != 0x48209:
        raise AssertionError("C6C2:1362 parent file moved")
    body, hit = follow_local(image, cs, ip, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:0D24 walk hit a boundary")
    if body[-1].ip != 0x0E4A or body[-1].kind != "RETF":
        raise AssertionError("C6C2:0D24 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:0D24 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("C6C2:0D24 first run does not start at 0D24")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind in ("CALLN", "JMPN", "JMPF"):
            raise AssertionError("C6C2:0D24 first run has a near/far jump or CALLN")
        if insn.kind == "JMPS":
            tfile = ((cs << 4) + insn.target_ip) & 0x7FFFF
            if not (body_file <= tfile < body_end):
                raise AssertionError("C6C2:0D24 JMPS leaves the first run")
        if insn.kind == "CALLF":
            tfile = ((insn.target_cs << 4) + insn.target_ip) & 0x7FFFF
            if _gap_at(tfile):
                raise AssertionError("C6C2:0D24 CALLF target is a gap")
        if insn.kind == "JCC":
            tfile = ((cs << 4) + insn.target_ip) & 0x7FFFF
            if not (body_file <= tfile < body_end):
                raise AssertionError("C6C2:0D24 JCC leaves the first run")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:0D24 first run is not a contiguous span")
    if c6c2_1169 in covered or gap_start in covered or leftover in covered:
        raise AssertionError("C6C2:0D24 seed entered 1169, gap start, or leftover 1345")
    if d90c_0006 in covered or d90c_0454 in covered or d90c_0099 in covered or d90c_04d9 in covered:
        raise AssertionError("C6C2:0D24 seed entered D90C:0006, 0454, 0099, or 04D9")
    if forbidden in covered:
        raise AssertionError("C6C2:0D24 seed entered C887:09AC")
    if next_file in covered or pad_file in covered:
        raise AssertionError("C6C2:0D24 seed extended past RETF")
    if body_end != next_file:
        raise AssertionError("C6C2:0D24 seed extended past RETF")
    if forbidden in range(body_file, body_end):
        raise AssertionError("C6C2:0D24 seed reached C887:09AC")
    owned = False
    caller_owned = False
    parent_owned = False
    prefix_owned = False
    next_owned = False
    gap_start_owned = False
    c6c2_1169_owned = False
    sibling_11ef_owned = False
    d90c_0006_owned = False
    d90c_0454_owned = False
    d90c_0099_owned = False
    d90c_04d9_owned = False
    d90c_01ad_owned = False
    forbidden_owned = False
    leftover_owned = False
    pad_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == parent_end and owner == "code":
            parent_owned = True
        if start <= prefix_file < end and owner == "code":
            prefix_owned = True
        if start <= next_file < end and owner == "code":
            next_owned = True
        if start <= gap_start < end and owner == "code":
            gap_start_owned = True
        if start == c6c2_1169 and end == c6c2_1169_end and owner == "code":
            c6c2_1169_owned = True
        if start == sibling_11ef and end == sibling_11ef_end and owner == "code":
            sibling_11ef_owned = True
        if start <= d90c_0006 < end and owner == "code":
            d90c_0006_owned = True
        if start <= d90c_0454 < end and owner == "code":
            d90c_0454_owned = True
        if start <= d90c_0099 < end and owner == "code":
            d90c_0099_owned = True
        if start <= d90c_04d9 < end and owner == "code":
            d90c_04d9_owned = True
        if start == d90c_01ad and end == d90c_01ad_end and owner == "code":
            d90c_01ad_owned = True
        if start <= forbidden < end and owner == "code":
            forbidden_owned = True
        if start <= leftover < end and owner == "code":
            leftover_owned = True
        if start <= pad_file < end and owner == "code":
            pad_owned = True
    if not owned:
        raise AssertionError("C6C2:0D24 body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:14B5 caller or C6C2:1362 body is not owned")
    if not sibling_11ef_owned or not d90c_01ad_owned:
        raise AssertionError("C6C2:11EF or D90C:01AD body was lost")
    if not c6c2_1169_owned:
        raise AssertionError("C6C2:1169 body was lost")
    if prefix_owned or next_owned or gap_start_owned:
        raise AssertionError("C6C2 gap prefix, byte after 0D24 RETF, or 0x46C2B was entered")
    if leftover_owned:
        raise AssertionError("leftover 1345 was entered")
    if d90c_0006_owned or d90c_0454_owned or d90c_0099_owned or d90c_04d9_owned:
        raise AssertionError("D90C:0006, 0454, 0099, or 04D9 was entered")
    if pad_owned:
        raise AssertionError("0xFF after 0574 RET was entered")
    if not _gap_at(prefix_file):
        raise AssertionError("byte before 0D24 is owned")
    if not _gap_at(next_file):
        raise AssertionError("byte after 0D24 RETF is owned")
    if not _gap_at(gap_start):
        raise AssertionError("C6C2 gap start 0x46C2B is owned")
    if not _gap_at(d90c_0006):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(d90c_0454):
        raise AssertionError("D90C:0454 is owned")
    if not _gap_at(d90c_0099):
        raise AssertionError("D90C:0099 is owned")
    if not _gap_at(d90c_04d9):
        raise AssertionError("D90C:04D9 is owned")
    if not _gap_at(leftover):
        raise AssertionError("leftover 1345 is owned")
    if not _gap_at(pad_file):
        raise AssertionError("0xFF after 0574 RET is owned")
    if forbidden_owned or not _gap_at(forbidden):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E):
        raise AssertionError("BCF9:000C or CA9B:029E is owned")


def _check_c6c2_1169(image: bytes, pin: dict) -> None:
    """C6C2:1169 is one closed first run through RETF. CALLN from follow_local 1362."""
    state = pin["state_c6c2_1169"]
    cs = 0xC6C2
    ip = 0x1169
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    caller_file = int(state["caller_file"], 16)
    parent_file = int(state["parent_file"], 16)
    parent_end = int(state["parent_end"], 16)
    prefix_file = int(state["prefix_file"], 16)
    leftover_0d24 = int(state["leftover_0d24"], 16)
    sibling_11ef = int(state["sibling_11ef"], 16)
    sibling_11ef_end = int(state["sibling_11ef_end"], 16)
    sibling_0d24 = int(state["sibling_0d24"], 16)
    sibling_0d24_end = int(state["sibling_0d24_end"], 16)
    gap_start = int(state["gap_start"], 16)
    d90c_0006 = int(state["d90c_0006"], 16)
    d90c_0454 = int(state["d90c_0454"], 16)
    d90c_0099 = int(state["d90c_0099"], 16)
    d90c_04d9 = int(state["d90c_04d9"], 16)
    d90c_01ad = int(state["d90c_01ad"], 16)
    d90c_01ad_end = int(state["d90c_01ad_end"], 16)
    forbidden = int(state["forbidden_file"], 16)
    leftover = int(state["leftover_file"], 16)
    pad_file = int(state["pad_file"], 16)
    phys20 = (cs << 4) + ip
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != body_file:
        raise AssertionError("C6C2:1169 file or 20-bit address")
    if (phys20 >> 14) != 49:
        raise AssertionError("C6C2:1169 is not PGR slot 49")
    phys24 = (_u16(image, 0x7AD16) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16) or _u16(image, 0x7AD16) != 0x0031:
        raise AssertionError(f"C6C2:1169 24-bit 0x{phys24:06X}")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100" or state["xa"] != 1:
        raise AssertionError(state)
    if image[0x7AD16:0x7AD18].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 49 word moved")
    if state["caller_bytes"] != "e820fc":
        raise AssertionError("1546 CALLN bytes are not E8 20 FC")
    if state["head_bytes"] != "558bec83ec028b46":
        raise AssertionError("C6C2:1169 head bytes are not 55 8B EC 83 EC 02 8B 46")
    if state["tail_bytes"] != "880fc9cb":
        raise AssertionError("C6C2:1169 tail bytes are not 88 0F C9 CB")
    if image[caller_file : caller_file + 3] != bytes.fromhex("e820fc"):
        raise AssertionError("1546 CALLN image bytes are not E8 20 FC")
    if image[body_file:body_file + 8] != bytes.fromhex("558bec83ec028b46"):
        raise AssertionError("C6C2:1169 head image bytes moved")
    if image[body_end - 4:body_end] != bytes.fromhex("880fc9cb"):
        raise AssertionError("C6C2:1169 tail image bytes moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C6C2:1169 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C6C2:1169 tail bytes moved")
    raw = image[body_file:body_end]
    if b"\x0f\xe0" in raw or b"\x0f\xf0" in raw:
        raise AssertionError("C6C2:1169 first run contains BRKXA/RETXA")
    if raw[0] != 0x55:
        raise AssertionError("1169 is not PUSH BP")
    mov_bp = decode_one(image, cs, 0x116A)
    mov_modrm = image[mov_bp.file + 1]
    if (
        mov_bp.bytes_hex != "8bec"
        or (mov_modrm >> 6) != 3
        or ((mov_modrm >> 3) & 7) != 5
        or (mov_modrm & 7) != 4
    ):
        raise AssertionError("116A does not write BP from SP")
    sub_sp = decode_one(image, cs, 0x116C)
    sub_modrm = image[sub_sp.file + 1]
    if (
        sub_sp.bytes_hex != "83ec02"
        or (sub_modrm >> 6) != 3
        or ((sub_modrm >> 3) & 7) != 5
        or (sub_modrm & 7) != 4
        or image[sub_sp.file + 2] != 0x02
    ):
        raise AssertionError("116C does not write SP from imm8 0x02")
    mov_ax = decode_one(image, cs, 0x116F)
    ax_modrm = image[mov_ax.file + 1]
    if (
        mov_ax.bytes_hex != "8b4606"
        or (ax_modrm >> 6) != 1
        or ((ax_modrm >> 3) & 7) != 0
        or (ax_modrm & 7) != 6
        or image[mov_ax.file + 2] != 0x06
    ):
        raise AssertionError("116F does not write AX from [BP+6]")
    mov_bx = decode_one(image, cs, 0x1172)
    if image[mov_bx.file] != 0xBB or mov_bx.bytes_hex != "bbc403":
        raise AssertionError("1172 does not write BX from imm16")
    bx_imm = image[mov_bx.file + 1] | (image[mov_bx.file + 2] << 8)
    if bx_imm != 0x03C4:
        raise AssertionError("1172 imm16 is not 0x03C4")
    jge = decode_one(image, cs, 0x1184)
    if jge.kind != "JCC" or jge.bytes_hex != state["jge_bytes"] or jge.target_ip != 0x118A:
        raise AssertionError("1184 is not JGE 118A")
    if image[jge.file] != 0x7D or jge.file != int(state["jge_file"], 16):
        raise AssertionError("1184 is not opcode 7D")
    jge_rel8 = image[jge.file + 1]
    if jge_rel8 != 0x04 or ((0x1184 + 2 + jge_rel8) & 0xFFFF) != 0x118A:
        raise AssertionError("1184 target is not 118A")
    leave = decode_one(image, cs, 0x11ED)
    retf = decode_one(image, cs, 0x11EE)
    if leave.bytes_hex != "c9" or retf.kind != "RETF" or retf.bytes_hex != "cb" or image[retf.file] != 0xCB:
        raise AssertionError("11EE is not RETF")
    parent, parent_hit = follow_local(image, cs, 0x1362, limit=400)
    if parent_hit:
        raise AssertionError("follow_local 1362 hit a limit")
    if any(insn.file == body_file or insn.ip == ip for insn in parent):
        raise AssertionError("follow_local 1362 entered C6C2:1169")
    caller = None
    for insn in parent:
        if insn.ip == 0x1546:
            caller = insn
            break
    if caller is None:
        raise AssertionError("follow_local 1362 does not list 1546")
    if not (0x47F82 <= caller.file < 0x48209) or caller.file != caller_file:
        raise AssertionError("1546 is not inside owned 1362")
    if caller.kind != "CALLN" or caller.target_ip != ip or caller.bytes_hex != state["caller_bytes"]:
        raise AssertionError("1546 is not CALLN C6C2:1169")
    if image[caller.file] != 0xE8:
        raise AssertionError("1546 is not opcode E8")
    caller_disp = image[caller.file + 1] | (image[caller.file + 2] << 8)
    if caller_disp != 0xFC20 or ((0x1546 + 3 + caller_disp - 0x10000) & 0xFFFF) != ip:
        raise AssertionError("1546 disp16 is not -0x03E0 to 1169")
    if parent_file != 0x47F82 or parent_end != 0x48209:
        raise AssertionError("C6C2:1362 parent file moved")
    body, hit = follow_local(image, cs, ip, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C6C2:1169 walk hit a boundary")
    if body[-1].ip != 0x11EE or body[-1].kind != "RETF":
        raise AssertionError("C6C2:1169 does not end at RETF")
    ordered = sorted(body, key=lambda insn: insn.file)
    runs: list[list] = [[ordered[0]]]
    for insn in ordered[1:]:
        prev = runs[-1][-1]
        if insn.file == prev.file + prev.length:
            runs[-1].append(insn)
        else:
            runs.append([insn])
    if len(runs) != 1:
        raise AssertionError("C6C2:1169 first run is not the only run")
    first = runs[0]
    if first[0].ip != ip or first[0].file != body_file:
        raise AssertionError("C6C2:1169 first run does not start at 1169")
    covered = set()
    for insn in first:
        covered.update(range(insn.file, insn.file + insn.length))
        if insn.kind in ("CALLN", "CALLF", "JMPN", "JMPF", "JMPS"):
            raise AssertionError("C6C2:1169 first run has a near/far jump or call")
        if insn.kind == "JCC":
            tfile = ((cs << 4) + insn.target_ip) & 0x7FFFF
            if not (body_file <= tfile < body_end):
                raise AssertionError("C6C2:1169 JCC leaves the first run")
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C6C2:1169 first run is not a contiguous span")
    if leftover_0d24 in covered or gap_start in covered or leftover in covered:
        raise AssertionError("C6C2:1169 seed entered leftover 0D24, gap start, or leftover 1345")
    if d90c_0006 in covered or d90c_0454 in covered or d90c_0099 in covered or d90c_04d9 in covered:
        raise AssertionError("C6C2:1169 seed entered D90C:0006, 0454, 0099, or 04D9")
    if forbidden in covered:
        raise AssertionError("C6C2:1169 seed entered C887:09AC")
    if pad_file in covered:
        raise AssertionError("C6C2:1169 seed extended past RETF")
    if body_end != sibling_11ef:
        raise AssertionError("C6C2:1169 is not adjacent to 11EF")
    if forbidden in range(body_file, body_end):
        raise AssertionError("C6C2:1169 seed reached C887:09AC")
    owned = False
    caller_owned = False
    parent_owned = False
    prefix_owned = False
    leftover_0d24_owned = False
    gap_start_owned = False
    sibling_11ef_owned = False
    sibling_0d24_owned = False
    d90c_0006_owned = False
    d90c_0454_owned = False
    d90c_0099_owned = False
    d90c_04d9_owned = False
    d90c_01ad_owned = False
    forbidden_owned = False
    leftover_owned = False
    pad_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= caller_file < end and owner == "code":
            caller_owned = True
        if start == parent_file and end == parent_end and owner == "code":
            parent_owned = True
        if start <= prefix_file < end and owner == "code":
            prefix_owned = True
        if start <= leftover_0d24 < end and owner == "code":
            leftover_0d24_owned = True
        if start <= gap_start < end and owner == "code":
            gap_start_owned = True
        if start == sibling_11ef and end == sibling_11ef_end and owner == "code":
            sibling_11ef_owned = True
        if start == sibling_0d24 and end == sibling_0d24_end and owner == "code":
            sibling_0d24_owned = True
        if start <= d90c_0006 < end and owner == "code":
            d90c_0006_owned = True
        if start <= d90c_0454 < end and owner == "code":
            d90c_0454_owned = True
        if start <= d90c_0099 < end and owner == "code":
            d90c_0099_owned = True
        if start <= d90c_04d9 < end and owner == "code":
            d90c_04d9_owned = True
        if start == d90c_01ad and end == d90c_01ad_end and owner == "code":
            d90c_01ad_owned = True
        if start <= forbidden < end and owner == "code":
            forbidden_owned = True
        if start <= leftover < end and owner == "code":
            leftover_owned = True
        if start <= pad_file < end and owner == "code":
            pad_owned = True
    if not owned:
        raise AssertionError("C6C2:1169 body is not the owned seed")
    if not caller_owned or not parent_owned:
        raise AssertionError("C6C2:1546 caller or C6C2:1362 body is not owned")
    if not sibling_11ef_owned or not sibling_0d24_owned or not d90c_01ad_owned:
        raise AssertionError("C6C2:11EF, C6C2:0D24, or D90C:01AD body was lost")
    if prefix_owned or leftover_0d24_owned or gap_start_owned:
        raise AssertionError("byte before 1169, leftover after 0D24, or 0x46C2B was entered")
    if leftover_owned:
        raise AssertionError("leftover 1345 was entered")
    if d90c_0006_owned or d90c_0454_owned or d90c_0099_owned or d90c_04d9_owned:
        raise AssertionError("D90C:0006, 0454, 0099, or 04D9 was entered")
    if pad_owned:
        raise AssertionError("0xFF after 0574 RET was entered")
    if not _gap_at(prefix_file):
        raise AssertionError("byte before 1169 is owned")
    if not _gap_at(leftover_0d24):
        raise AssertionError("byte after 0D24 RETF is owned")
    if not _gap_at(gap_start):
        raise AssertionError("C6C2 gap start 0x46C2B is owned")
    if not _gap_at(d90c_0006):
        raise AssertionError("D90C:0006 is owned")
    if not _gap_at(d90c_0454):
        raise AssertionError("D90C:0454 is owned")
    if not _gap_at(d90c_0099):
        raise AssertionError("D90C:0099 is owned")
    if not _gap_at(d90c_04d9):
        raise AssertionError("D90C:04D9 is owned")
    if not _gap_at(leftover):
        raise AssertionError("leftover 1345 is owned")
    if not _gap_at(pad_file):
        raise AssertionError("0xFF after 0574 RET is owned")
    if forbidden_owned or not _gap_at(forbidden):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x3CF9C) or not _gap_at(0x4AC4E):
        raise AssertionError("BCF9:000C or CA9B:029E is owned")


def _check_c4c8_0e5a(image: bytes, pin: dict) -> None:
    """0E5A is the suffix of the post-0C64 gap through one RETF. 0E2B stays out."""
    state = pin["state_c4c8_0e5a"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC5ADA or (0xC5ADA & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:0E5A file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC5ADA:
        raise AssertionError("C4C8:0E5A phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:0E5A head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:0E5A tail bytes moved")
    flag = int(state["flag_file"], 16)
    if image[flag:flag + 5].hex() != state["flag_bytes"]:
        raise AssertionError("C4C8:0E5A flag bytes moved")
    call = decode_one(image, 0xC4C8, 0x1248)
    if call.kind != "CALLN" or call.target_ip != 0x0E5A or call.file != 0x45EC8 or call.bytes_hex != "e80ffc":
        raise AssertionError("1248 is not CALL 0E5A")
    if decode_one(image, 0xC4C8, 0x0E7F).target_ip != 0x0E2B:
        raise AssertionError("0E7F is not CALL 0E2B")
    if decode_one(image, 0xC4C8, 0x0E86).bytes_hex != "83fe10":
        raise AssertionError("0E86 is not CMP SI,0x10")
    body, hit = follow_local(image, 0xC4C8, 0x0E5A, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:0E5A walk hit a boundary")
    if body[-1].ip != 0x0EC8 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:0E5A does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:0E5A walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0E5A body is not the owned seed")


def _check_c4c8_0e2b(image: bytes, pin: dict) -> None:
    """0E2B is the suffix before 0E5A. byte [BP+6]==0x2B selects 0D8B, else 0CF1."""
    state = pin["state_c4c8_0e2b"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC5AAB or (0xC5AAB & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:0E2B file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC5AAB:
        raise AssertionError("C4C8:0E2B phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:0E2B head bytes moved")
    if image[body_end - 2:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:0E2B tail bytes moved")
    gate = int(state["gate_file"], 16)
    if image[gate:gate + 6].hex() != state["gate_bytes"]:
        raise AssertionError("C4C8:0E2B gate bytes moved")
    for ip, file_off, raw in ((0x0E7F, 0x45AFF, "e8a9ff"), (0x0E99, 0x45B19, "e88fff")):
        call = decode_one(image, 0xC4C8, ip)
        if call.kind != "CALLN" or call.target_ip != 0x0E2B or call.file != file_off or call.bytes_hex != raw:
            raise AssertionError(f"C4C8:{ip:04X} is not CALL 0E2B")
    if decode_one(image, 0xC4C8, 0x0E42).target_ip != 0x0D8B:
        raise AssertionError("0E42 is not CALL 0D8B")
    if decode_one(image, 0xC4C8, 0x0E52).target_ip != 0x0CF1:
        raise AssertionError("0E52 is not CALL 0CF1")
    body, hit = follow_local(image, 0xC4C8, 0x0E2B, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:0E2B walk hit a boundary")
    if body[-1].ip != 0x0E59 or body[-1].kind != "RETF":
        raise AssertionError("C4C8:0E2B does not end at RETF")
    if decode_one(image, 0xC4C8, 0x0E49).kind != "RETF":
        raise AssertionError("0E49 is not RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:0E2B walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0E2B body is not the owned seed")


def _check_c4c8_0cf1(image: bytes, pin: dict) -> None:
    """0CF1 is the prefix of the post-0C64 gap. [BP+0xA]==0 calls 06E1, else 07A2."""
    state = pin["state_c4c8_0cf1"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC5971 or (0xC5971 & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:0CF1 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC5971:
        raise AssertionError("C4C8:0CF1 phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:0CF1 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:0CF1 tail bytes moved")
    shift = int(state["shift_file"], 16)
    if image[shift:shift + 7].hex() != state["shift_bytes"]:
        raise AssertionError("C4C8:0CF1 shift bytes moved")
    call = decode_one(image, 0xC4C8, 0x0E52)
    if call.kind != "CALLN" or call.target_ip != 0x0CF1 or call.file != 0x45AD2 or call.bytes_hex != "e89cfe":
        raise AssertionError("0E52 is not CALL 0CF1")
    if decode_one(image, 0xC4C8, 0x0D3F).target_ip != 0x06E1:
        raise AssertionError("0D3F is not CALL 06E1")
    if decode_one(image, 0xC4C8, 0x0D81).target_ip != 0x07A2:
        raise AssertionError("0D81 is not CALL 07A2")
    body, hit = follow_local(image, 0xC4C8, 0x0CF1, limit=100)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:0CF1 walk hit a boundary")
    if body[-1].ip != 0x0D8A or body[-1].kind != "RETF":
        raise AssertionError("C4C8:0CF1 does not end at RETF")
    if decode_one(image, 0xC4C8, 0x0D48).kind != "RETF":
        raise AssertionError("0D48 is not RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:0CF1 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0CF1 body is not the owned seed")


def _check_c4c8_0d8b(image: bytes, pin: dict) -> None:
    """0D8B fills the gap before 0E2B. It adds to DX and clamps, then calls 06E1 or 07A2."""
    state = pin["state_c4c8_0d8b"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xC5A0B or (0xC5A0B & 0x7FFFF) != body_file:
        raise AssertionError("C4C8:0D8B file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xC5A0B:
        raise AssertionError("C4C8:0D8B phys24 moved")
    if state["pgr_slot"] != 49 or state["pgr_bytes"] != "3100":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("C4C8:0D8B head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("C4C8:0D8B tail bytes moved")
    clamp = int(state["clamp_file"], 16)
    if image[clamp:clamp + 3].hex() != state["clamp_bytes"]:
        raise AssertionError("C4C8:0D8B clamp bytes moved")
    call = decode_one(image, 0xC4C8, 0x0E42)
    if call.kind != "CALLN" or call.target_ip != 0x0D8B or call.file != 0x45AC2 or call.bytes_hex != "e846ff":
        raise AssertionError("0E42 is not CALL 0D8B")
    if decode_one(image, 0xC4C8, 0x0DDC).target_ip != 0x06E1:
        raise AssertionError("0DDC is not CALL 06E1")
    if decode_one(image, 0xC4C8, 0x0E21).target_ip != 0x07A2:
        raise AssertionError("0E21 is not CALL 07A2")
    body, hit = follow_local(image, 0xC4C8, 0x0D8B, limit=100)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("C4C8:0D8B walk hit a boundary")
    if body[-1].ip != 0x0E2A or body[-1].kind != "RETF":
        raise AssertionError("C4C8:0D8B does not end at RETF")
    if decode_one(image, 0xC4C8, 0x0DE5).kind != "RETF":
        raise AssertionError("0DE5 is not RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("C4C8:0D8B walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("C4C8:0D8B body is not the owned seed")


def _check_d9a2_008d(image: bytes, pin: dict) -> None:
    """008D is the whole gap after owned 005F. AX<0x23 returns; else ORs [BP+8] into ES:[BX+3]."""
    state = pin["state_d9a2_008d"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xD9AAD or (0xD9AAD & 0x7FFFF) != body_file:
        raise AssertionError("D9A2:008D file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xD9AAD:
        raise AssertionError("D9A2:008D phys24 moved")
    if state["pgr_slot"] != 54 or state["pgr_bytes"] != "3600":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("D9A2:008D head bytes moved")
    if image[body_end - 2:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("D9A2:008D tail bytes moved")
    gate = int(state["gate_file"], 16)
    if image[gate:gate + 5].hex() != state["gate_bytes"]:
        raise AssertionError("D9A2:008D gate bytes moved")
    store = int(state["store_file"], 16)
    if image[store:store + 9].hex() != state["store_bytes"]:
        raise AssertionError("D9A2:008D store bytes moved")
    for ip, file_off in ((0x0D77, 0x459F7), (0x0E17, 0x45A97)):
        call = decode_one(image, 0xC4C8, ip)
        if (
            call.kind != "CALLF"
            or call.target_cs != 0xD9A2
            or call.target_ip != 0x008D
            or call.file != file_off
            or call.bytes_hex != "9a8d00a2d9"
        ):
            raise AssertionError(f"C4C8:{ip:04X} is not CALLF D9A2:008D")
    body, hit = follow_local(image, 0xD9A2, 0x008D, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("D9A2:008D walk hit a boundary")
    if body[-1].ip != 0x00C6 or body[-1].kind != "RETF":
        raise AssertionError("D9A2:008D does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("D9A2:008D walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D9A2:008D body is not the owned seed")


def _check_b3fd_0b0b(image: bytes, pin: dict) -> None:
    """0B0B is the reached app-ROM head. One RETF; 0D53 stays out."""
    state = pin["state_b3fd_0b0b"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB4ADB or (0xB4ADB & 0x7FFFF) != body_file:
        raise AssertionError("B3FD:0B0B file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB4ADB:
        raise AssertionError("B3FD:0B0B phys24 moved")
    if state["pgr_slot"] != 45 or state["pgr_bytes"] != "2d00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B3FD:0B0B head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B3FD:0B0B tail bytes moved")
    store = int(state["store_file"], 16)
    if image[store:store + 5].hex() != state["store_bytes"]:
        raise AssertionError("B3FD:0B0B store bytes moved")
    call = decode_one(image, 0xB3FD, 0x03EC)
    if call.kind != "CALLN" or call.target_ip != 0x0B0B or call.file != 0x343BC or call.bytes_hex != "e81c07":
        raise AssertionError("03EC is not CALL 0B0B")
    if decode_one(image, 0xB3FD, 0x0D48).target_ip != 0x0D53:
        raise AssertionError("0D48 is not CALL 0D53")
    body, hit = follow_local(image, 0xB3FD, 0x0B0B, limit=400)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B3FD:0B0B walk hit a boundary")
    if body[-1].ip != 0x0D52 or body[-1].kind != "RETF":
        raise AssertionError("B3FD:0B0B does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B3FD:0B0B walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("B3FD:0B0B body is not the owned seed")


def _check_b3fd_0d53(image: bytes, pin: dict) -> None:
    """0D53 is the prefix after 0B0B. 0ACC and 0EE9 stay out."""
    state = pin["state_b3fd_0d53"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB4D23 or (0xB4D23 & 0x7FFFF) != body_file:
        raise AssertionError("B3FD:0D53 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB4D23:
        raise AssertionError("B3FD:0D53 phys24 moved")
    if state["pgr_slot"] != 45 or state["pgr_bytes"] != "2d00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B3FD:0D53 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B3FD:0D53 tail bytes moved")
    store = int(state["store_file"], 16)
    if image[store:store + 5].hex() != state["store_bytes"]:
        raise AssertionError("B3FD:0D53 store bytes moved")
    call = decode_one(image, 0xB3FD, 0x0D48)
    if call.kind != "CALLN" or call.target_ip != 0x0D53 or call.file != 0x34D18 or call.bytes_hex != "e80800":
        raise AssertionError("0D48 is not CALL 0D53")
    if decode_one(image, 0xB3FD, 0x0D96).target_ip != 0x0ACC:
        raise AssertionError("0D96 is not CALL 0ACC")
    if decode_one(image, 0xB3FD, 0x0EDE).target_ip != 0x0EE9:
        raise AssertionError("0EDE is not CALL 0EE9")
    body, hit = follow_local(image, 0xB3FD, 0x0D53, limit=250)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B3FD:0D53 walk hit a boundary")
    if body[-1].ip != 0x0EE8 or body[-1].kind != "RETF":
        raise AssertionError("B3FD:0D53 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B3FD:0D53 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("B3FD:0D53 body is not the owned seed")


def _check_b3fd_0ee9(image: bytes, pin: dict) -> None:
    """0EE9 is the prefix after 0D53. B77C:20EA and 0F79 stay out."""
    state = pin["state_b3fd_0ee9"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB4EB9 or (0xB4EB9 & 0x7FFFF) != body_file:
        raise AssertionError("B3FD:0EE9 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB4EB9:
        raise AssertionError("B3FD:0EE9 phys24 moved")
    if state["pgr_slot"] != 45 or state["pgr_bytes"] != "2d00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B3FD:0EE9 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B3FD:0EE9 tail bytes moved")
    store = int(state["store_file"], 16)
    if image[store:store + 5].hex() != state["store_bytes"]:
        raise AssertionError("B3FD:0EE9 store bytes moved")
    call = decode_one(image, 0xB3FD, 0x0EDE)
    if call.kind != "CALLN" or call.target_ip != 0x0EE9 or call.file != 0x34EAE or call.bytes_hex != "e80800":
        raise AssertionError("0EDE is not CALL 0EE9")
    if decode_one(image, 0xB3FD, 0x0F0E).kind != "CALLF" or decode_one(image, 0xB3FD, 0x0F0E).target_cs != 0xB77C:
        raise AssertionError("0F0E is not CALLF B77C")
    body, hit = follow_local(image, 0xB3FD, 0x0EE9, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B3FD:0EE9 walk hit a boundary")
    if body[-1].ip != 0x0F78 or body[-1].kind != "RETF":
        raise AssertionError("B3FD:0EE9 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B3FD:0EE9 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("B3FD:0EE9 body is not the owned seed")


def _check_b3fd_0f79(image: bytes, pin: dict) -> None:
    """0F79 follows 0EE9. 0ACC and the far callees stay out."""
    state = pin["state_b3fd_0f79"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB4F49 or (0xB4F49 & 0x7FFFF) != body_file:
        raise AssertionError("B3FD:0F79 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB4F49:
        raise AssertionError("B3FD:0F79 phys24 moved")
    if state["pgr_slot"] != 45 or state["pgr_bytes"] != "2d00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B3FD:0F79 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B3FD:0F79 tail bytes moved")
    read = int(state["read_file"], 16)
    if image[read:read + 3].hex() != state["read_bytes"]:
        raise AssertionError("B3FD:0F79 read bytes moved")
    call = decode_one(image, 0xB3FD, 0x03FB)
    if call.kind != "CALLN" or call.target_ip != 0x0F79 or call.file != 0x343CB or call.bytes_hex != "e87b0b":
        raise AssertionError("03FB is not CALL 0F79")
    if decode_one(image, 0xB3FD, 0x0FD2).target_ip != 0x0ACC:
        raise AssertionError("0FD2 is not CALL 0ACC")
    if decode_one(image, 0xB3FD, 0x105A).target_ip != 0x0ACC:
        raise AssertionError("105A is not CALL 0ACC")
    body, hit = follow_local(image, 0xB3FD, 0x0F79, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B3FD:0F79 walk hit a boundary")
    if body[-1].ip != 0x10C7 or body[-1].kind != "RETF":
        raise AssertionError("B3FD:0F79 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B3FD:0F79 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("B3FD:0F79 body is not the owned seed")
    if not _gap_at(int(state["suffix_file"], 16)):
        raise AssertionError("file 0x35098 is owned")


def _check_b3fd_0acc(image: bytes, pin: dict) -> None:
    """0ACC fills the gap in front of owned 0B0B. Every callee is already owned."""
    state = pin["state_b3fd_0acc"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB4A9C or (0xB4A9C & 0x7FFFF) != body_file:
        raise AssertionError("B3FD:0ACC file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB4A9C:
        raise AssertionError("B3FD:0ACC phys24 moved")
    if state["pgr_slot"] != 45 or state["pgr_bytes"] != "2d00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B3FD:0ACC head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B3FD:0ACC tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 2].hex() != state["imm_bytes"]:
        raise AssertionError("B3FD:0ACC immediate moved")
    callers = (
        (0x0D96, 0x34D66, "e833fd"),
        (0x0DE6, 0x34DB6, "e8e3fc"),
        (0x0FD2, 0x34FA2, "e8f7fa"),
        (0x105A, 0x3502A, "e86ffa"),
    )
    for ip, file_off, raw in callers:
        call = decode_one(image, 0xB3FD, ip)
        if call.kind != "CALLN" or call.target_ip != 0x0ACC or call.file != file_off or call.bytes_hex != raw:
            raise AssertionError(f"{ip:04X} is not CALL 0ACC")
    body, hit = follow_local(image, 0xB3FD, 0x0ACC, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B3FD:0ACC walk hit a boundary")
    if body[-1].ip != 0x0B0A or body[-1].kind != "RETF":
        raise AssertionError("B3FD:0ACC does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B3FD:0ACC walk does not match the seed")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == body_end and owner == "code":
            meets = True
    if not owned:
        raise AssertionError("B3FD:0ACC body is not the owned seed")
    if not meets:
        raise AssertionError("B3FD:0ACC does not meet owned 0B0B")


def _check_b77c_20ea(image: bytes, pin: dict) -> None:
    """20EA fills the gap between owned 20C5 and the following owned range."""
    state = pin["state_b77c_20ea"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB98AA or (0xB98AA & 0x7FFFF) != body_file:
        raise AssertionError("B77C:20EA file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB98AA:
        raise AssertionError("B77C:20EA phys24 moved")
    if state["pgr_slot"] != 46 or state["pgr_bytes"] != "2e00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B77C:20EA head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B77C:20EA tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("B77C:20EA immediate moved")
    callers = (
        (0x0DB4, 0x34D84),
        (0x0F0E, 0x34EDE),
        (0x103C, 0x3500C),
    )
    for ip, file_off in callers:
        call = decode_one(image, 0xB3FD, ip)
        if (
            call.kind != "CALLF"
            or call.target_cs != 0xB77C
            or call.target_ip != 0x20EA
            or call.file != file_off
            or call.bytes_hex != "9aea207cb7"
        ):
            raise AssertionError(f"{ip:04X} is not CALLF 20EA")
    near = decode_one(image, 0xB77C, 0x20EB)
    if near.kind != "CALLN" or near.target_ip != 0x20C5 or near.bytes_hex != "e8d7ff":
        raise AssertionError("20EB is not CALL 20C5")
    body, hit = follow_local(image, 0xB77C, 0x20EA, limit=20)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B77C:20EA walk hit a boundary")
    if body[-1].ip != 0x20FA or body[-1].kind != "RETF":
        raise AssertionError("B77C:20EA does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B77C:20EA walk does not match the seed")
    owned = False
    before = False
    after = False
    near_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if end == body_file and owner == "code":
            before = True
        if start == body_end and owner == "code":
            after = True
        if start <= 0x39885 < end and owner == "code":
            near_owned = True
    if not owned:
        raise AssertionError("B77C:20EA body is not the owned seed")
    if not before or not after:
        raise AssertionError("B77C:20EA does not sit between owned ranges")
    if not near_owned:
        raise AssertionError("B77C:20C5 is not owned")


def _check_e605_000e(image: bytes, pin: dict) -> None:
    """000E fills the gap before owned E609. E1A6:0007 is already owned."""
    state = pin["state_e605_000e"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE605E or (0xE605E & 0x7FFFF) != body_file:
        raise AssertionError("E605:000E file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE605E:
        raise AssertionError("E605:000E phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E605:000E head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E605:000E tail bytes moved")
    store = int(state["store_file"], 16)
    if image[store:store + 4].hex() != state["store_bytes"]:
        raise AssertionError("E605:000E store bytes moved")
    call = decode_one(image, 0xB3FD, 0x0F91)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xE605
        or call.target_ip != 0x000E
        or call.file != 0x34F61
        or call.bytes_hex != "9a0e0005e6"
    ):
        raise AssertionError("0F91 is not CALLF E605:000E")
    far = decode_one(image, 0xE605, 0x001E)
    if far.kind != "CALLF" or far.target_cs != 0xE1A6 or far.target_ip != 0x0007 or far.bytes_hex != "9a0700a6e1":
        raise AssertionError("001E is not CALLF E1A6:0007")
    body, hit = follow_local(image, 0xE605, 0x000E, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E605:000E walk hit a boundary")
    if body[-1].ip != 0x0044 or body[-1].kind != "RETF":
        raise AssertionError("E605:000E does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E605:000E walk does not match the seed")
    owned = False
    meets = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == body_end and owner == "code":
            meets = True
        if start <= 0x61A67 < end and owner == "code":
            callee_owned = True
    if not owned:
        raise AssertionError("E605:000E body is not the owned seed")
    if not meets:
        raise AssertionError("E605:000E does not meet the next owned range")
    if not callee_owned:
        raise AssertionError("E1A6:0007 is not owned")


def _check_b77c_1f26(image: bytes, pin: dict) -> None:
    """1F26 is a mid-gap island. The prefix and the byte after the RETF stay out."""
    state = pin["state_b77c_1f26"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB96E6 or (0xB96E6 & 0x7FFFF) != body_file:
        raise AssertionError("B77C:1F26 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB96E6:
        raise AssertionError("B77C:1F26 phys24 moved")
    if state["pgr_slot"] != 46 or state["pgr_bytes"] != "2e00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B77C:1F26 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B77C:1F26 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 2].hex() != state["imm_bytes"]:
        raise AssertionError("B77C:1F26 immediate moved")
    callers = (
        (0x1004, 0x34FD4),
        (0x1069, 0x35039),
    )
    for ip, file_off in callers:
        call = decode_one(image, 0xB3FD, ip)
        if (
            call.kind != "CALLF"
            or call.target_cs != 0xB77C
            or call.target_ip != 0x1F26
            or call.file != file_off
            or call.bytes_hex != "9a261f7cb7"
        ):
            raise AssertionError(f"{ip:04X} is not CALLF 1F26")
    far = decode_one(image, 0xB77C, 0x1F36)
    if far.kind != "CALLF" or far.target_cs != 0xE4D6 or far.target_ip != 0x000D or far.bytes_hex != "9a0d00d6e4":
        raise AssertionError("1F36 is not CALLF E4D6:000D")
    body, hit = follow_local(image, 0xB77C, 0x1F26, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B77C:1F26 walk hit a boundary")
    if body[-1].ip != 0x1F64 or body[-1].kind != "RETF":
        raise AssertionError("B77C:1F26 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B77C:1F26 walk does not match the seed")
    owned = False
    callee_owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == 0x64D6D and owner == "code":
            callee_owned = True
    if not owned:
        raise AssertionError("B77C:1F26 body is not the owned seed")
    if not callee_owned:
        raise AssertionError("E4D6:000D is not owned")
    if not _gap_at(int(state["prefix_file"], 16)):
        raise AssertionError("file 0x37336 is owned")


def _check_e617_0004(image: bytes, pin: dict) -> None:
    """0004 is the prefix of its gap. Near callees 035A, 02D7, and 03AE stay out."""
    state = pin["state_e617_0004"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE6174 or (0xE6174 & 0x7FFFF) != body_file:
        raise AssertionError("E617:0004 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE6174:
        raise AssertionError("E617:0004 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E617:0004 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E617:0004 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E617:0004 immediate moved")
    call = decode_one(image, 0xB3FD, 0x10A6)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xE617
        or call.target_ip != 0x0004
        or call.file != 0x35076
        or call.bytes_hex != "9a040017e6"
    ):
        raise AssertionError("10A6 is not CALLF E617:0004")
    if decode_one(image, 0xE617, 0x002A).target_ip != 0x035A:
        raise AssertionError("002A is not CALL 035A")
    if decode_one(image, 0xE617, 0x014E).target_ip != 0x02D7:
        raise AssertionError("014E is not CALL 02D7")
    if decode_one(image, 0xE617, 0x0278).target_ip != 0x03AE:
        raise AssertionError("0278 is not CALL 03AE")
    body, hit = follow_local(image, 0xE617, 0x0004, limit=400)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E617:0004 walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x0023, 0x003A, 0x0060, 0x0079, 0x00B5, 0x02D6]:
        raise AssertionError(f"E617:0004 RETFs moved: {retfs}")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E617:0004 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("E617:0004 body is not the owned seed")


def _check_e617_02d7(image: bytes, pin: dict) -> None:
    """02D7 loops until [E75E]&0xF8 == 0xF8. The byte after the back-edge stays out."""
    state = pin["state_e617_02d7"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE6447 or (0xE6447 & 0x7FFFF) != body_file:
        raise AssertionError("E617:02D7 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE6447:
        raise AssertionError("E617:02D7 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E617:02D7 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E617:02D7 tail bytes moved")
    store = int(state["store_file"], 16)
    if image[store:store + 5].hex() != state["store_bytes"]:
        raise AssertionError("E617:02D7 store bytes moved")
    call = decode_one(image, 0xE617, 0x014E)
    if call.kind != "CALLN" or call.target_ip != 0x02D7 or call.file != 0x662BE or call.bytes_hex != "e88601":
        raise AssertionError("014E is not CALL 02D7")
    body, hit = follow_local(image, 0xE617, 0x02D7, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E617:02D7 walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x0322]:
        raise AssertionError(f"E617:02D7 RETF moved: {retfs}")
    if body[-1].ip != 0x0354 or body[-1].kind != "JMPS" or body[-1].target_ip != 0x02EA:
        raise AssertionError("E617:02D7 does not loop to 02EA")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E617:02D7 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("E617:02D7 body is not the owned seed")
    if not _gap_at(int(state["suffix_file"], 16)):
        raise AssertionError("file 0x664C6 is owned")


def _check_e617_035a(image: bytes, pin: dict) -> None:
    """035A is the island after the four unreached bytes. 03AE stays out."""
    state = pin["state_e617_035a"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE64CA or (0xE64CA & 0x7FFFF) != body_file:
        raise AssertionError("E617:035A file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE64CA:
        raise AssertionError("E617:035A phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E617:035A head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E617:035A tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E617:035A immediate moved")
    call = decode_one(image, 0xE617, 0x002A)
    if call.kind != "CALLN" or call.target_ip != 0x035A or call.file != 0x6619A or call.bytes_hex != "e82d03":
        raise AssertionError("002A is not CALL 035A")
    far = decode_one(image, 0xE617, 0x0381)
    if far.kind != "CALLF" or far.target_cs != 0xE1A6 or far.target_ip != 0x0007:
        raise AssertionError("0381 is not CALLF E1A6:0007")
    body, hit = follow_local(image, 0xE617, 0x035A, limit=60)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E617:035A walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x0394, 0x03A0, 0x03AD]:
        raise AssertionError(f"E617:035A RETFs moved: {retfs}")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E617:035A walk does not match the seed")
    owned = False
    callee = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= 0x61A67 < end and owner == "code":
            callee = True
    if not owned:
        raise AssertionError("E617:035A body is not the owned seed")
    if not callee:
        raise AssertionError("E1A6:0007 is not owned")
    if not _gap_at(int(state["prefix_file"], 16)):
        raise AssertionError("file 0x664C6 is owned")


def _check_e617_03ae(image: bytes, pin: dict) -> None:
    """03AE copies five bytes and meets the still-unowned E655:0004."""
    state = pin["state_e617_03ae"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE651E or (0xE651E & 0x7FFFF) != body_file:
        raise AssertionError("E617:03AE file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE651E:
        raise AssertionError("E617:03AE phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E617:03AE head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E617:03AE tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E617:03AE immediate moved")
    call = decode_one(image, 0xE617, 0x0278)
    if call.kind != "CALLN" or call.target_ip != 0x03AE or call.file != 0x663E8 or call.bytes_hex != "e83301":
        raise AssertionError("0278 is not CALL 03AE")
    body, hit = follow_local(image, 0xE617, 0x03AE, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E617:03AE walk hit a boundary")
    if body[-1].ip != 0x03E3 or body[-1].kind != "RETF":
        raise AssertionError("E617:03AE does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E617:03AE walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("E617:03AE body is not the owned seed")


def _check_e655_0004(image: bytes, pin: dict) -> None:
    """0004 fills the gap in front of owned E661:0006."""
    state = pin["state_e655_0004"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE6554 or (0xE6554 & 0x7FFFF) != body_file:
        raise AssertionError("E655:0004 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE6554:
        raise AssertionError("E655:0004 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E655:0004 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E655:0004 tail bytes moved")
    bound = int(state["bound_file"], 16)
    if image[bound:bound + 4].hex() != state["bound_bytes"]:
        raise AssertionError("E655:0004 bound bytes moved")
    call = decode_one(image, 0xE617, 0x0047)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xE655
        or call.target_ip != 0x0004
        or call.file != 0x661B7
        or call.bytes_hex != "9a040055e6"
    ):
        raise AssertionError("0047 is not CALLF E655:0004")
    body, hit = follow_local(image, 0xE655, 0x0004, limit=120)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E655:0004 walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x003A, 0x00C5]:
        raise AssertionError(f"E655:0004 RETFs moved: {retfs}")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E655:0004 walk does not match the seed")
    owned = False
    meets = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == body_end and owner == "code":
            meets = True
    if not owned:
        raise AssertionError("E655:0004 body is not the owned seed")
    if not meets:
        raise AssertionError("E655:0004 does not meet owned E661:0006")


def _check_e692_0000(image: bytes, pin: dict) -> None:
    """0000 is the prefix of its gap. E7D5:0001 stays out."""
    state = pin["state_e692_0000"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE6920 or (0xE6920 & 0x7FFFF) != body_file:
        raise AssertionError("E692:0000 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE6920:
        raise AssertionError("E692:0000 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E692:0000 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E692:0000 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E692:0000 immediate moved")
    call = decode_one(image, 0xE617, 0x008C)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xE692
        or call.target_ip != 0x0000
        or call.file != 0x661FC
        or call.bytes_hex != "9a000092e6"
    ):
        raise AssertionError("008C is not CALLF E692:0000")
    far = decode_one(image, 0xE692, 0x011B)
    if far.kind != "CALLF" or far.target_cs != 0xE7D5 or far.target_ip != 0x0001:
        raise AssertionError("011B is not CALLF E7D5:0001")
    body, hit = follow_local(image, 0xE692, 0x0000, limit=200)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E692:0000 walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x002C, 0x0083, 0x017C]:
        raise AssertionError(f"E692:0000 RETFs moved: {retfs}")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E692:0000 walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("E692:0000 body is not the owned seed")
    if not _gap_at(int(state["suffix_file"], 16)):
        raise AssertionError("file 0x66A9D is owned")


def _check_e7d5_0001(image: bytes, pin: dict) -> None:
    """0001 searches a far-pointer table. The byte after the last RETF stays out."""
    state = pin["state_e7d5_0001"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE7D51 or (0xE7D51 & 0x7FFFF) != body_file:
        raise AssertionError("E7D5:0001 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE7D51:
        raise AssertionError("E7D5:0001 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E7D5:0001 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E7D5:0001 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E7D5:0001 immediate moved")
    call = decode_one(image, 0xE692, 0x011B)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xE7D5
        or call.target_ip != 0x0001
        or call.file != 0x66A3B
        or call.bytes_hex != "9a0100d5e7"
    ):
        raise AssertionError("011B is not CALLF E7D5:0001")
    body, hit = follow_local(image, 0xE7D5, 0x0001, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E7D5:0001 walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x0020, 0x0057, 0x0068]:
        raise AssertionError(f"E7D5:0001 RETFs moved: {retfs}")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E7D5:0001 walk does not match the seed")
    owned = False
    callee = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= 0x61A67 < end and owner == "code":
            callee = True
    if not owned:
        raise AssertionError("E7D5:0001 body is not the owned seed")
    if not callee:
        raise AssertionError("E1A6:0007 is not owned")
    if not _gap_at(int(state["suffix_file"], 16)):
        raise AssertionError("file 0x67DB9 is owned")


def _check_b77c_202d(image: bytes, pin: dict) -> None:
    """202D is a mid-gap island. 1F65 and the byte after the RETF stay out."""
    state = pin["state_b77c_202d"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB97ED or (0xB97ED & 0x7FFFF) != body_file:
        raise AssertionError("B77C:202D file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB97ED:
        raise AssertionError("B77C:202D phys24 moved")
    if state["pgr_slot"] != 46 or state["pgr_bytes"] != "2e00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B77C:202D head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B77C:202D tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("B77C:202D immediate moved")
    call = decode_one(image, 0xBE1A, 0x003F)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xB77C
        or call.target_ip != 0x202D
        or call.file != 0x3E1DF
        or call.bytes_hex != "9a2d207cb7"
    ):
        raise AssertionError("003F is not CALLF B77C:202D")
    near_1fdb = decode_one(image, 0xB77C, 0x203E)
    if near_1fdb.kind != "CALLN" or near_1fdb.target_ip != 0x1FDB or near_1fdb.bytes_hex != "e89aff":
        raise AssertionError("203E is not CALLN 1FDB")
    near_1f65 = decode_one(image, 0xB77C, 0x2051)
    if near_1f65.kind != "CALLN" or near_1f65.target_ip != 0x1F65 or near_1f65.bytes_hex != "e811ff":
        raise AssertionError("2051 is not CALLN 1F65")
    body, hit = follow_local(image, 0xB77C, 0x202D, limit=40)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B77C:202D walk hit a boundary")
    if body[-1].ip != 0x205A or body[-1].kind != "RETF":
        raise AssertionError("B77C:202D does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B77C:202D walk does not match the seed")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("B77C:202D body is not the owned seed")


def _check_b77c_1f65(image: bytes, pin: dict) -> None:
    """1F65 is the prefix of the gap in front of 202D. 1FDB stays out."""
    state = pin["state_b77c_1f65"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB9725 or (0xB9725 & 0x7FFFF) != body_file:
        raise AssertionError("B77C:1F65 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB9725:
        raise AssertionError("B77C:1F65 phys24 moved")
    if state["pgr_slot"] != 46 or state["pgr_bytes"] != "2e00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B77C:1F65 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B77C:1F65 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("B77C:1F65 immediate moved")
    call = decode_one(image, 0xB77C, 0x2051)
    if (
        call.kind != "CALLN"
        or call.target_ip != 0x1F65
        or call.file != 0x39811
        or call.bytes_hex != "e811ff"
    ):
        raise AssertionError("2051 is not CALLN 1F65")
    far = (
        (0x1F83, 0xD0C0, 0x10B6, "9ab610c0d0"),
        (0x1F92, 0xB1B1, 0x0026, "9a2600b1b1"),
        (0x1F9E, 0xB1B1, 0x0097, "9a9700b1b1"),
        (0x1FAA, 0xB1B1, 0x0026, "9a2600b1b1"),
        (0x1FBE, 0xB1B1, 0x0036, "9a3600b1b1"),
        (0x1FCF, 0xB1B1, 0x005B, "9a5b00b1b1"),
    )
    for ip, tcs, tip, raw in far:
        insn = decode_one(image, 0xB77C, ip)
        if insn.kind != "CALLF" or insn.target_cs != tcs or insn.target_ip != tip or insn.bytes_hex != raw:
            raise AssertionError(f"{ip:04X} far call moved")
    body, hit = follow_local(image, 0xB77C, 0x1F65, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B77C:1F65 walk hit a boundary")
    if body[-1].ip != 0x1FDA or body[-1].kind != "RETF":
        raise AssertionError("B77C:1F65 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B77C:1F65 walk does not match the seed")
    owned = False
    b26 = b36 = b5b = b97 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == 0x31B36 and end == 0x31B6B and owner == "code":
            b26 = True
        if start <= 0x31B46 < end and owner == "code":
            b36 = True
        if start == 0x31B6B and owner == "code":
            b5b = True
        if start <= 0x31BA7 < end and owner == "code":
            b97 = True
    if not owned:
        raise AssertionError("B77C:1F65 body is not the owned seed")
    if not (b26 and b36 and b5b and b97):
        raise AssertionError("B1B1 callee is not owned")
    if not _gap_at(int(state["suffix_file"], 16)):
        raise AssertionError("B77C:1FDB is owned")


def _check_b77c_205b(image: bytes, pin: dict) -> None:
    """205B fills the gap after 202D. 1FDB stays unseeded."""
    state = pin["state_b77c_205b"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xB981B or (0xB981B & 0x7FFFF) != body_file:
        raise AssertionError("B77C:205B file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xB981B:
        raise AssertionError("B77C:205B phys24 moved")
    if state["pgr_slot"] != 46 or state["pgr_bytes"] != "2e00":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("B77C:205B head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("B77C:205B tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("B77C:205B immediate moved")
    call = decode_one(image, 0xCEBF, 0x008D)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xB77C
        or call.target_ip != 0x205B
        or call.file != 0x4EC7D
        or call.bytes_hex != "9a5b207cb7"
    ):
        raise AssertionError("008D is not CALLF B77C:205B")
    far = (
        (0x207F, 0xE72C, 0x00A1, "9aa1002ce7"),
        (0x2094, 0xE4D6, 0x000D, "9a0d00d6e4"),
        (0x20A2, 0xB1B1, 0x0026, "9a2600b1b1"),
        (0x20AC, 0xB1B1, 0x0036, "9a3600b1b1"),
        (0x20B9, 0xB1B1, 0x005B, "9a5b00b1b1"),
    )
    for ip, tcs, tip, raw in far:
        insn = decode_one(image, 0xB77C, ip)
        if insn.kind != "CALLF" or insn.target_cs != tcs or insn.target_ip != tip or insn.bytes_hex != raw:
            raise AssertionError(f"{ip:04X} far call moved")
    body, hit = follow_local(image, 0xB77C, 0x205B, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("B77C:205B walk hit a boundary")
    if body[-1].ip != 0x20C4 or body[-1].kind != "RETF":
        raise AssertionError("B77C:205B does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("B77C:205B walk does not match the seed")
    owned = False
    e4 = b26 = b5b = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == 0x64D6D and owner == "code":
            e4 = True
        if start == 0x31B36 and owner == "code":
            b26 = True
        if start == 0x31B6B and owner == "code":
            b5b = True
    if not owned:
        raise AssertionError("B77C:205B body is not the owned seed")
    if not (e4 and b26 and b5b):
        raise AssertionError("205B callee is not owned")
    if not _gap_at(0x3979B):
        raise AssertionError("B77C:1FDB is owned")


def _check_e72c_00a1(image: bytes, pin: dict) -> None:
    """00A1 is a mid-gap island. The byte after the RETF stays out."""
    state = pin["state_e72c_00a1"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE7361 or (0xE7361 & 0x7FFFF) != body_file:
        raise AssertionError("E72C:00A1 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE7361:
        raise AssertionError("E72C:00A1 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E72C:00A1 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E72C:00A1 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E72C:00A1 immediate moved")
    call = decode_one(image, 0xB77C, 0x207F)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xE72C
        or call.target_ip != 0x00A1
        or call.file != 0x3983F
        or call.bytes_hex != "9aa1002ce7"
    ):
        raise AssertionError("207F is not CALLF E72C:00A1")
    near = decode_one(image, 0xE72C, 0x00AF)
    if near.kind != "CALLN" or near.target_ip != 0x0006 or near.bytes_hex != "e854ff":
        raise AssertionError("00AF is not CALLN 0006")
    body, hit = follow_local(image, 0xE72C, 0x00A1, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E72C:00A1 walk hit a boundary")
    if body[-1].ip != 0x00D8 or body[-1].kind != "RETF":
        raise AssertionError("E72C:00A1 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E72C:00A1 walk does not match the seed")
    owned = False
    callee = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start == 0x672C6 and end == 0x67361 and owner == "code":
            callee = True
    if not owned:
        raise AssertionError("E72C:00A1 body is not the owned seed")
    if not callee:
        raise AssertionError("E72C:0006 is not owned")
    if not _gap_at(int(state["suffix_file"], 16)):
        raise AssertionError("file 0x67399 is owned")


def _check_e72c_0006(image: bytes, pin: dict) -> None:
    """0006 fills the gap in front of 00A1. E739:0009 stays out."""
    state = pin["state_e72c_0006"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xE72C6 or (0xE72C6 & 0x7FFFF) != body_file:
        raise AssertionError("E72C:0006 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xE72C6:
        raise AssertionError("E72C:0006 phys24 moved")
    if state["pgr_slot"] != 57 or state["pgr_bytes"] != "3900":
        raise AssertionError(state)
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("E72C:0006 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("E72C:0006 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("E72C:0006 immediate moved")
    call = decode_one(image, 0xE72C, 0x00AF)
    if (
        call.kind != "CALLN"
        or call.target_ip != 0x0006
        or call.file != 0x6736F
        or call.bytes_hex != "e854ff"
    ):
        raise AssertionError("00AF is not CALLN E72C:0006")
    far = decode_one(image, 0xE72C, 0x003A)
    if (
        far.kind != "CALLF"
        or far.target_cs != 0xE1A6
        or far.target_ip != 0x0007
        or far.bytes_hex != "9a0700a6e1"
    ):
        raise AssertionError("003A is not CALLF E1A6:0007")
    body, hit = follow_local(image, 0xE72C, 0x0006, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("E72C:0006 walk hit a boundary")
    retfs = [insn.ip for insn in body if insn.kind == "RETF"]
    if retfs != [0x0032, 0x0038, 0x004B, 0x0089, 0x008F, 0x00A0]:
        raise AssertionError("E72C:0006 RETFs moved")
    if body[-1].ip != 0x00A0 or body[-1].kind != "RETF":
        raise AssertionError("E72C:0006 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("E72C:0006 walk does not match the seed")
    owned = False
    e1 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == body_file and end == body_end and owner == "code":
            owned = True
        if start <= 0x61A67 < end and owner == "code":
            e1 = True
    if not owned:
        raise AssertionError("E72C:0006 body is not the owned seed")
    if not e1:
        raise AssertionError("E1A6:0007 is not owned")
    if not _gap_at(0x67399):
        raise AssertionError("E739:0009 is owned")
    if not _gap_at(0x3979B):
        raise AssertionError("B77C:1FDB is owned")


def _check_d0c0_10b6(image: bytes, pin: dict) -> None:
    """10B6 is the suffix of the gap in front of owned code. 101D is the callee."""
    state = pin["state_d0c0_10b6"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xD1CB6 or (0xD1CB6 & 0x7FFFF) != body_file:
        raise AssertionError("D0C0:10B6 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xD1CB6:
        raise AssertionError("D0C0:10B6 phys24 moved")
    if state["pgr_slot"] != 52 or state["pgr_bytes"] != "3400":
        raise AssertionError(state)
    if image[0x7AD1C:0x7AD1E].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 52 word moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("D0C0:10B6 head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("D0C0:10B6 tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("D0C0:10B6 immediate moved")
    call = decode_one(image, 0xB77C, 0x1F83)
    if (
        call.kind != "CALLF"
        or call.target_cs != 0xD0C0
        or call.target_ip != 0x10B6
        or call.file != 0x39743
        or call.bytes_hex != "9ab610c0d0"
    ):
        raise AssertionError("1F83 is not CALLF D0C0:10B6")
    base = (0xB77C << 4) & 0x7FFFF
    if not (base <= 0x39743 < 0x3979B <= base + 0x10000):
        raise AssertionError("1F83 is outside the B77C window")
    near = decode_one(image, 0xD0C0, 0x10E7)
    if near.kind != "CALLN" or near.target_ip != 0x101D or near.file != 0x51CE7 or near.bytes_hex != "e833ff":
        raise AssertionError("10E7 is not CALLN D0C0:101D")
    body, hit = follow_local(image, 0xD0C0, 0x10B6, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("D0C0:10B6 walk hit a boundary")
    if body[-1].ip != 0x10EE or body[-1].kind != "RETF":
        raise AssertionError("D0C0:10B6 does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("D0C0:10B6 walk does not match the seed")
    owned = False
    caller = False
    callee = False
    for rec in load_ledger()["ranges"]:
        start = int(rec["start"], 16)
        end = int(rec["end"], 16)
        if start == body_file and end == body_end and rec["owner"] == "code":
            if not rec["why"].startswith("D0C0:"):
                raise AssertionError("10B6 why does not start with D0C0")
            owned = True
        if start == 0x51C1D and end == 0x51CB6 and rec["owner"] == "code":
            callee = True
        if start == 0x39725 and end == 0x3979B and rec["owner"] == "code":
            if not rec["why"].startswith("B77C:"):
                raise AssertionError("1F65 why does not start with B77C")
            caller = True
    if not owned:
        raise AssertionError("D0C0:10B6 body is not the owned seed")
    if not caller:
        raise AssertionError("B77C:1F65 caller is not owned")
    if not callee:
        raise AssertionError("D0C0:101D is not owned")
    if not _gap_at(0x3979B):
        raise AssertionError("B77C:1FDB is owned")


def _check_d0c0_101d(image: bytes, pin: dict) -> None:
    """101D fills the gap in front of 10B6. It has no call."""
    state = pin["state_d0c0_101d"]
    body_file = int(state["body_file"], 16)
    body_end = int(state["body_end"], 16)
    if int(state["phys20"], 16) != 0xD1C1D or (0xD1C1D & 0x7FFFF) != body_file:
        raise AssertionError("D0C0:101D file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0xD1C1D:
        raise AssertionError("D0C0:101D phys24 moved")
    if state["pgr_slot"] != 52 or state["pgr_bytes"] != "3400":
        raise AssertionError(state)
    if image[0x7AD1C:0x7AD1E].hex() != state["pgr_bytes"]:
        raise AssertionError("slot 52 word moved")
    if image[body_file:body_file + 8].hex() != state["head_bytes"]:
        raise AssertionError("D0C0:101D head bytes moved")
    if image[body_end - 4:body_end].hex() != state["tail_bytes"]:
        raise AssertionError("D0C0:101D tail bytes moved")
    imm = int(state["imm_file"], 16)
    if image[imm:imm + 3].hex() != state["imm_bytes"]:
        raise AssertionError("D0C0:101D immediate moved")
    _expect_hex(image, 0x51C28, "81f98000", "D0C0:101D CMP CX,0x8000")
    _expect_hex(image, 0x51C62, "b8aea2", "D0C0:101D MOV AX,0xA2AE")
    call = decode_one(image, 0xD0C0, 0x10E7)
    if (
        call.kind != "CALLN"
        or call.target_ip != 0x101D
        or call.file != 0x51CE7
        or call.bytes_hex != "e833ff"
    ):
        raise AssertionError("10E7 is not CALLN D0C0:101D")
    if not (0x50C00 <= 0x51CE7 < 0x51CEF <= 0x50C00 + 0x10000):
        raise AssertionError("10E7 is outside the D0C0 window")
    body, hit = follow_local(image, 0xD0C0, 0x101D, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("D0C0:101D walk hit a boundary")
    if any(insn.kind in ("CALLF", "CALLN", "CALLF_RM", "CALLN_RM") for insn in body):
        raise AssertionError("D0C0:101D has a call")
    if body[-1].ip != 0x10B5 or body[-1].kind != "RETF":
        raise AssertionError("D0C0:101D does not end at RETF")
    covered = set()
    for insn in body:
        covered.update(range(insn.file, insn.file + insn.length))
    if covered != set(range(body_file, body_end)):
        raise AssertionError("D0C0:101D walk does not match the seed")
    owned = False
    caller = False
    for rec in load_ledger()["ranges"]:
        start = int(rec["start"], 16)
        end = int(rec["end"], 16)
        if start == body_file and end == body_end and rec["owner"] == "code":
            if not rec["why"].startswith("D0C0:"):
                raise AssertionError("101D why does not start with D0C0")
            owned = True
        if start == 0x51CB6 and end == 0x51CEF and rec["owner"] == "code":
            if not rec["why"].startswith("D0C0:"):
                raise AssertionError("10B6 why does not start with D0C0")
            caller = True
    if not owned:
        raise AssertionError("D0C0:101D body is not the owned seed")
    if not caller:
        raise AssertionError("D0C0:10B6 caller is not owned")
    if not _gap_at(0x3979B):
        raise AssertionError("B77C:1FDB is owned")
    if not _gap_at(0x4921C):
        raise AssertionError("C887:09AC is owned")
    if not _gap_at(0x313A0):
        raise AssertionError("B13A:0000 is owned")


def _check_f800_031f(image: bytes, pin: dict) -> None:
    """F800:031F is three CS words. CX=3 bounds the walk. Prefix and records stay gaps."""
    state = pin["state_f800_031f"]
    cs = 0xF800
    table_file = int(state["table_file"], 16)
    table_end = int(state["table_end"], 16)
    consumer_file = int(state["consumer_file"], 16)
    phys20 = (cs << 4) + 0x0F63
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != consumer_file:
        raise AssertionError("F800:0F63 file or 20-bit address")
    if int(state["phys24_second_pgr"], 16) != 0x0F8F63:
        raise AssertionError("F800:0F63 phys24 moved")
    table20 = (cs << 4) + 0x031F
    if table20 != int(state["table_phys20"], 16) or (table20 & 0x7FFFF) != table_file:
        raise AssertionError("F800:031F file or 20-bit address")
    if int(state["table_phys24"], 16) != 0x0F831F:
        raise AssertionError("F800:031F phys24 moved")
    if state["pgr_slot"] != 62 or state["pgr_bytes"] != "3e00":
        raise AssertionError(state)
    if image[int(state["pgr_file"], 16) : int(state["pgr_file"], 16) + 2].hex() != "3e00":
        raise AssertionError("second PGR slot 62 word moved")
    slot_word = _u16(image, 0x7AD30)
    if slot_word != 0x003E:
        raise AssertionError("slot 62 is not 0x003E")
    phys24 = (slot_word << 14) | (phys20 & 0x3FFF)
    if phys24 != 0x0F8F63:
        raise AssertionError(f"F800:0F63 24-bit 0x{phys24:06X}")
    table24 = (slot_word << 14) | (table20 & 0x3FFF)
    if table24 != 0x0F831F:
        raise AssertionError(f"F800:031F 24-bit 0x{table24:06X}")
    _expect_hex(image, consumer_file, state["consumer_bytes"], "F800:0F63 MOV SI,0x031F")
    _expect_hex(image, int(state["cx_file"], 16), state["cx_bytes"], "F800:0F66 MOV CX,3")
    _expect_hex(image, table_file, state["table_bytes"], "F800:031F three words")
    if table_end - table_file != 6:
        raise AssertionError("F800:031F is not three words")
    mov_si = decode_one(image, cs, 0x0F63)
    if mov_si.bytes_hex != "be1f03" or mov_si.file != 0x78F63:
        raise AssertionError("0F63 is not MOV SI, imm16 0x031F")
    if bytes.fromhex(mov_si.bytes_hex)[0] != 0xBE:
        raise AssertionError("0F63 opcode is not B8+SI")
    mov_cx = decode_one(image, cs, 0x0F66)
    if mov_cx.bytes_hex != "b90300" or mov_cx.file != 0x78F66:
        raise AssertionError("0F66 is not MOV CX, imm16 +3")
    if bytes.fromhex(mov_cx.bytes_hex)[0] != 0xB9:
        raise AssertionError("0F66 opcode is not B8+CX")
    mov_dl = decode_one(image, cs, 0x0F69)
    if mov_dl.bytes_hex != "b200":
        raise AssertionError("0F69 is not MOV DL, imm8 0")
    ja = decode_one(image, cs, 0x0F61)
    if ja.kind != "JCC" or ja.bytes_hex != "770b" or ja.target_ip != 0x0F6E:
        raise AssertionError("0F61 is not JA to 0F6E")
    jmp = decode_one(image, cs, 0x0F6B)
    if jmp.kind != "JMPS" or jmp.bytes_hex != "eb07" or jmp.target_ip != 0x0F74:
        raise AssertionError("0F6B is not JMP to 0F74")
    load = decode_one(image, cs, 0x0F74)
    if load.bytes_hex != "2e8b1c" or load.file != 0x78F74:
        raise AssertionError("0F74 is not MOV BX, CS:[SI]")
    modrm = bytes.fromhex(load.bytes_hex)[2]
    if (modrm >> 6) != 0 or ((modrm >> 3) & 7) != 3 or (modrm & 7) != 4:
        raise AssertionError("0F74 ModR/M is not BX from [SI]")
    cmp_ax = decode_one(image, cs, 0x0F5E)
    if cmp_ax.bytes_hex != "3d1400":
        raise AssertionError("0F5E is not CMP AX, imm16 0x0014")
    add_si = decode_one(image, cs, 0x0F7D)
    if add_si.bytes_hex != "83c602":
        raise AssertionError("0F7D is not ADD SI, imm8 +2")
    add_mod = bytes.fromhex(add_si.bytes_hex)[1]
    if (add_mod >> 6) != 3 or ((add_mod >> 3) & 7) != 0 or (add_mod & 7) != 6:
        raise AssertionError("0F7D ModR/M is not ADD SI")
    loop = decode_one(image, cs, 0x0F82)
    if loop.kind != "JCC" or loop.bytes_hex != "e2f0" or loop.target_ip != 0x0F74:
        raise AssertionError("0F82 is not LOOP to 0F74")
    body, hit = follow_local(image, cs, 0x0F07, limit=80)
    if hit or any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("F800:0F07 walk hit a boundary")
    by_ip = {insn.ip: insn for insn in body}
    for ip, raw in (
        (0x0F5E, "3d1400"),
        (0x0F61, "770b"),
        (0x0F63, "be1f03"),
        (0x0F66, "b90300"),
        (0x0F69, "b200"),
        (0x0F6B, "eb07"),
        (0x0F74, "2e8b1c"),
        (0x0F7D, "83c602"),
        (0x0F82, "e2f0"),
    ):
        insn = by_ip.get(ip)
        if insn is None or insn.bytes_hex != raw:
            raise AssertionError(f"F800:{ip:04X} is not in follow_local from 0F07")
    owned = False
    consumer = False
    for start, end, owner, kind in ledger_spans(load_ledger()):
        if start == table_file and end == table_end and owner == "data" and kind == "table":
            owned = True
        if start <= consumer_file < end and owner == "code":
            consumer = True
    if not owned:
        raise AssertionError("F800:031F table is not the owned seed")
    if not consumer:
        raise AssertionError("F800:0F63 consumer is not owned code")
    if not _gap_at(int(state["prefix_file"], 16)):
        raise AssertionError("F800:0317 prefix is owned")
    if not _gap_at(int(state["record_file"], 16)):
        raise AssertionError("F800:0325 record is owned")


def _check_d547_07e1(image: bytes, pin: dict) -> None:
    """DI slot 0 (AL&0x0F==0) stores 07E1 at 0581; JMP BX at 051D reaches the body."""
    state = pin["state_07e1"]
    prev = pin["state_0780"]
    join = pin["state_062d"]
    cs = 0xD547
    phys20 = (cs << 4) + 0x07E1
    if phys20 != int(state["phys20"], 16) or (phys20 & 0x7FFFF) != int(state["body_file"], 16):
        raise AssertionError("D547:07E1 file or 20-bit address")
    phys24 = (_u16(image, 0x7AD1E) << 14) | (phys20 & 0x3FFF)
    if phys24 != int(state["phys24_second_pgr"], 16):
        raise AssertionError(f"D547:07E1 24-bit 0x{phys24:06X}")
    next20 = (cs << 4) + 0x082B
    if next20 != int(state["next_phys20"], 16) or (next20 & 0x7FFFF) != int(state["next_file"], 16):
        raise AssertionError("D547:082B file or 20-bit address")
    next24 = (_u16(image, 0x7AD1E) << 14) | (next20 & 0x3FFF)
    if next24 != int(state["next_phys24"], 16):
        raise AssertionError(f"D547:082B 24-bit 0x{next24:06X}")
    _expect_hex(image, int(state["body_file"], 16), state["body_bytes"], "D547:07E1 through JMP 062D")
    _expect_hex(image, int(state["di_slot0_file"], 16), state["di_slot0_bytes"], "DI-table slot 0 word 0581")
    _expect_hex(image, int(state["writer_file"], 16), state["writer_bytes"], "MOV BX,07E1 / JMP 0907")
    _expect_hex(image, int(state["store_file"], 16), state["store_bytes"], "store [SI+762E] / RET")
    _expect_hex(image, int(state["reader_file"], 16), state["reader_bytes"], "MOV BX,[SI+762E] / SHR SI,1 / JMP BX")
    _expect_hex(image, int(state["jmp_bx_file"], 16), state["jmp_bx_bytes"], "JMP BX")
    _expect_hex(image, int(state["sled_file"], 16), state["sled_bytes"], "unreached NOP at 0693")
    _expect_hex(image, int(state["nop_file"], 16), state["nop_bytes"], "unreached NOP at 0708")
    _expect_hex(image, int(prev["next_file"], 16), prev["next_bytes"], "D547:07AF gap head")
    _expect_hex(image, int(join["body_file"], 16), join["body_bytes"], "owned D547:062D body")
    _expect_hex(image, int(state["next_file"], 16), state["next_bytes"], "D547:082B gap head")
    al = 0x80
    if (al & 0x80) == 0 or al >= 0xF8:
        raise AssertionError("0x80 is not on the 04E1 path")
    if _u16(image, 0x559D1 + ((al & 0x0F) << 1)) != 0x0581:
        raise AssertionError("AL low nibble 0 does not select DI-table slot 0581")
    if decode_one(image, cs, 0x04D6).bytes_hex != "a880":
        raise AssertionError("04D6 is not TEST AL,0x80")
    if decode_one(image, cs, 0x055C).bytes_hex != "2effa56105":
        raise AssertionError("055C is not JMP CS:[DI+0561]")
    if decode_one(image, cs, 0x051D).bytes_hex != "ffe3":
        raise AssertionError("051D is not JMP BX")
    if decode_one(image, cs, 0x0907).bytes_hex != "d1e6" or decode_one(image, cs, 0x0909).bytes_hex != "899c2e76":
        raise AssertionError("0907 is not SHL SI,1 / MOV [SI+762E],BX")
    if decode_one(image, cs, 0x090D).kind != "RET":
        raise AssertionError("090D is not RET")
    dispatch, dispatch_hit = follow_local(image, cs, 0x04D5, limit=80)
    if dispatch_hit:
        raise AssertionError("04D5 walk hit the limit")
    if not any(insn.ip == 0x055C and insn.kind == "JMPN_RM" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP CS:[DI+0561]")
    if not any(insn.ip == 0x051D and insn.bytes_hex == "ffe3" for insn in dispatch):
        raise AssertionError("04D5 walk does not reach JMP BX")
    if any(insn.ip in (0x0581, 0x07E1) for insn in dispatch):
        raise AssertionError("04D5 walk entered 0581 or 07E1 by fall-through")
    slot, slot_hit = follow_local(image, cs, 0x0581, limit=8)
    if slot_hit:
        raise AssertionError("0581 walk hit the limit")
    if [insn.ip for insn in slot] != [0x0581, 0x0584, 0x0907, 0x0909, 0x090D]:
        raise AssertionError("0581 is not MOV BX,07E1 / JMP 0907 / store / RET")
    if slot[0].bytes_hex != "bbe107" or slot[1].target_ip != 0x0907 or slot[-1].kind != "RET":
        raise AssertionError("0581 does not store BX=07E1")
    if any(insn.ip == 0x07E1 for insn in slot):
        raise AssertionError("0581 walk entered 07E1")
    body, hit = follow_local(image, cs, 0x07E1, limit=96)
    if hit:
        raise AssertionError("07E1 walk hit the limit")
    if any(insn.file in (0x55B03, 0x55B78) or insn.ip in (0x0693, 0x0708, 0x07AF) for insn in body):
        raise AssertionError("07E1 walk entered an unreached NOP or 07AF")
    if any(insn.bytes_hex.startswith(("0fe0", "0ff0")) for insn in body):
        raise AssertionError("07E1 body contains BRKXA/RETXA")
    head = [
        insn
        for insn in body
        if int(state["body_file"], 16) <= insn.file < int(state["body_end"], 16)
    ]
    if len(head) != 24:
        raise AssertionError("07E1 body is not the twenty-four-instruction seed through JMP 062D")
    if head[0].bytes_hex != "80843a7602" or head[0].ip != 0x07E1:
        raise AssertionError("07E1 does not begin with CMP [SI+763A],2 / INC DX")
    last = head[-1]
    if last.kind != "JMPN" or last.target_ip != 0x062D or last.ip != 0x0828:
        raise AssertionError("0828 does not JMP to owned 062D")
    if last.file + last.length != int(state["body_end"], 16):
        raise AssertionError("07E1 body does not end at the JMP 062D")
    if body[-1].kind != "RET" or body[-1].ip != 0x090D:
        raise AssertionError("07E1 follow does not end at the 0907 RET")
    owned = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(state["body_file"], 16) and end == int(state["body_end"], 16) and owner == "code":
            owned = True
    if not owned:
        raise AssertionError("D547:07E1 body is not the owned seed")
    owned_07af = False
    gap = pin["state_07af"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(gap["body_file"], 16)
            and end == int(gap["body_end"], 16)
            and owner == "code"
        ):
            owned_07af = True
    if not owned_07af:
        raise AssertionError("D547:07AF body is not owned")
    bridge = pin["state_07de"]
    owned_bridge = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(bridge["body_file"], 16)
            and end == int(bridge["body_end"], 16)
            and owner == "code"
        ):
            owned_bridge = True
    if not owned_bridge:
        raise AssertionError("D547:07DE bridge is not owned")
    if _gap_at(int(bridge["body_file"], 16)):
        raise AssertionError("D547:07DE bridge is still a gap")
    owned_082b = False
    gap082 = pin["state_082b"]
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if (
            start == int(gap082["body_file"], 16)
            and end == int(gap082["body_end"], 16)
            and owner == "code"
        ):
            owned_082b = True
    if not owned_082b:
        raise AssertionError("D547:082B body is not owned")
    if not _gap_at(int(gap082["next_file"], 16)):
        raise AssertionError("D547:0491 bounded gap head is owned")
    owned_0780 = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(prev["body_file"], 16) and end == int(prev["body_end"], 16) and owner == "code":
            owned_0780 = True
    if not owned_0780:
        raise AssertionError("D547:0780 body is not owned")
    owned_062d = False
    for start, end, owner, _kind in ledger_spans(load_ledger()):
        if start == int(join["body_file"], 16) and end == int(join["body_end"], 16) and owner == "code":
            owned_062d = True
    if not owned_062d:
        raise AssertionError("D547:062D body is not owned")


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
    patch_banks = ((0x54, 0x20000), (0x74000, 0x78000))
    for label, base in (("first", 0x7AE56), ("second", 0x7ACB4), ("third", 0x7ADCF)):
        for page in range(64):
            word = _u16(image, base + page * 2)
            phys = word << 14
            if phys >= 0x100000:
                continue
            file_base = phys & 0x7FFFF
            file_end = file_base + 0x4000
            for bank_lo, bank_hi in patch_banks:
                if file_base < bank_hi and bank_lo < file_end:
                    raise AssertionError(
                        f"{label} PGR page {page} word 0x{word:04X} selects a patch bank"
                    )
    checks.append("patch banks unselected by the three PGR tables")
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
    _check_d510_and_task7(image, writers)
    checks.append("D510 callers and task-7 two-level walks: no PGR MOV DX")
    checks.append("task-7 third-level D9DD:005D: no PGR MOV DX/OUT")
    checks.append("task-7 third-level DDC0:0031: no PGR MOV DX/OUT")
    _check_d6ac_store(image, facts["d6ac_store"])
    _check_d52a_computed(image, facts["d6ac_store"])
    checks.append("D6AC stores classified; D52A:0328 has no static or computed entry")
    checks.append("D52A:0492 reached via [7626]; body through JMP 06A0 owned")
    checks.append("D52A:051F reached via [SI+762E]; body through JMP 06A0 owned")
    _check_d547_0663(image, facts["d6ac_store"])
    checks.append("D547:0663 reached via [SI+762E]; body through JMP 0907 owned")
    _check_d547_066d(image, facts["d6ac_store"])
    checks.append("D547:066D reached via [SI+762E]; body through JMP 0907 owned")
    _check_d547_051f(image, facts["d6ac_store"])
    checks.append("D547:051F reached via [SI+762E]; body through JMP 0907 owned")
    _check_d547_0694(image, facts["d6ac_store"])
    checks.append("D547:0694 reached via [SI+762E]; body through fall into 06A7 owned")
    _check_d547_06d3(image, facts["d6ac_store"])
    checks.append("D547:06D3 reached via [SI+762E]; body through JMP 0900 owned")
    _check_d547_06dd(image, facts["d6ac_store"])
    checks.append("D547:06DD reached via [SI+762E]; body through JMP 0907 owned")
    _check_d547_06ec(image, facts["d6ac_store"])
    checks.append("D547:06EC reached via [SI+762E]; body through JMP 0900 owned")
    _check_d547_071c(image, facts["d6ac_store"])
    checks.append("D547:071C reached via [SI+762E]; body through JMP 0907 owned")
    _check_d547_0726(image, facts["d6ac_store"])
    checks.append("D547:0726 reached via [SI+762E]; body through JMP 0900 owned")
    _check_d547_0733(image, facts["d6ac_store"])
    checks.append("D547:0733 reached via [SI+762E]; body through JMP 0907 owned")
    _check_d547_073d(image, facts["d6ac_store"])
    checks.append("D547:073D reached via [SI+762E]; body through JMP 0900 owned")
    _check_d547_0780(image, facts["d6ac_store"])
    checks.append("D547:0780 reached via 073D JNZ; body through JMP 0907 owned")
    _check_d547_07af(image, facts["d6ac_store"])
    checks.append("D547:07AF reached via BX slot 5; body through JMP 0900 owned")
    _check_d547_07de(image, facts["d6ac_store"])
    checks.append("D547:07DE reached via 07AF JZ/JL; JMP 0907 bridge owned")
    _check_d547_07e1(image, facts["d6ac_store"])
    checks.append("D547:07E1 reached via [SI+762E]; body through JMP 062D owned")
    _check_d547_062d(image, facts["d6ac_store"])
    checks.append("D547:062D reached via 07E1 JMP; body through JMP 0907 owned")
    _check_d547_065d(image, facts["d6ac_store"])
    checks.append("D547:065D reached via 062D JNS; body through JMP 0907 owned")
    _check_d547_08cf(image, facts["d6ac_store"])
    checks.append("D547:08CF reached via [SI+762E]; body through JMPS 0907 owned")
    _check_d547_08d9(image, facts["d6ac_store"])
    checks.append("D547:08D9 reached via 08CF MOV BX,08D9; body through JMPS 0907 owned")
    _check_d547_082b(image, facts["d6ac_store"])
    checks.append("D547:082B reached via DI slot 1 stub 0587; body through JMPS 0907 owned")
    _check_d547_0933(image, facts["d6ac_store"])
    checks.append("D547:0933 reached via CALLN 0860/08BD; body through RET owned")
    _check_c44e_02bf(image, facts["d6ac_store"])
    checks.append("C44E:02BF reached via slot 005E CALL 0060; local BX tables owned")
    _check_c4c8_000d(image, facts["d6ac_store"])
    checks.append("C4C8:000D reached via C425:0160; head and BX table owned")
    _check_c4c8_00a3(image, facts["d6ac_store"])
    checks.append("C4C8:00A3 reached via slot 006B; body through RETF owned")
    _check_c4c8_0448(image, facts["d6ac_store"])
    checks.append("C4C8:0448 reached via 00A3; body through RETF owned")
    _check_c4c8_0490(image, facts["d6ac_store"])
    checks.append("C4C8:0490 reached via 00A3; body through RETF owned")
    _check_c4c8_04f9(image, facts["d6ac_store"])
    checks.append("C4C8:04F9 reached via 00A3 and 0490; body through RETF owned")
    _check_c4c8_05b9(image, facts["d6ac_store"])
    checks.append("C4C8:05B9 reached via 00A3 and 0490; body through RETF owned")
    _check_c4c8_0927(image, facts["d6ac_store"])
    checks.append("C4C8:0927 reached via 00A3 and 0448; body through RETF owned")
    _check_c4c8_0982(image, facts["d6ac_store"])
    checks.append("C4C8:0982 reached via 0490; body through RETF owned")
    _check_c4c8_0a99(image, facts["d6ac_store"])
    checks.append("C4C8:0A99 reached via 0490; body through RETF owned")
    _check_c4c8_0c64(image, facts["d6ac_store"])
    checks.append("C4C8:0C64 reached via 00A3; body through both RETFs owned")
    _check_c4c8_0c35(image, facts["d6ac_store"])
    checks.append("C4C8:0C35 reached via 0C64; body through both RETFs owned")
    _check_c4c8_0aef(image, facts["d6ac_store"])
    checks.append("C4C8:0AEF reached via 0C35; body through both RETFs owned")
    _check_c4c8_0b8f(image, facts["d6ac_store"])
    checks.append("C4C8:0B8F reached via 0C35; body through both RETFs owned")
    _check_c4c8_0ec9(image, facts["d6ac_store"])
    checks.append("C4C8:0EC9 reached via 00A3 and 0448; body through RETF owned")
    _check_c4c8_0f5f(image, facts["d6ac_store"])
    checks.append("C4C8:0F5F reached via 00A3 and 0490; body through RETF owned")
    _check_c4c8_0f0d(image, facts["d6ac_store"])
    checks.append("C4C8:0F0D reached via 0F5F; body through RETF owned")
    _check_c4c8_0fb1(image, facts["d6ac_store"])
    checks.append("C4C8:0FB1 reached via 0982; body through both RETFs owned")
    _check_c4c8_0fdf(image, facts["d6ac_store"])
    checks.append("C4C8:0FDF reached via slot 0074; body through RETF owned")
    _check_c4c8_12a9(image, facts["d6ac_store"])
    checks.append("C4C8:12A9 reached via slot 007D; four runs owned")
    _check_c4c8_1b3f(image, facts["d6ac_store"])
    checks.append("C4C8:1B3F reached via slot 0086; body through RETF owned")
    _check_c4c8_1dc3(image, facts["d6ac_store"])
    checks.append("C4C8:1DC3 reached via slot 008F; body through RETF owned")
    _check_c4c8_0678(image, facts["d6ac_store"])
    checks.append("C4C8:0678 reached via 0FDF; body through RETF owned")
    _check_c4c8_06e1(image, facts["d6ac_store"])
    checks.append("C4C8:06E1 reached via 0678 and 0FDF; body through RETF owned")
    _check_c4c8_07a2(image, facts["d6ac_store"])
    checks.append("C4C8:07A2 reached via 0678; two runs owned")
    _check_c4c8_bx_tables(image, facts["d6ac_store"])
    checks.append("C4C8 BX tables 0913/1818/1844/1850 owned; 1818/1844/1850 first slots stay gaps")
    _check_c4c8_08cf(image, facts["d6ac_store"])
    checks.append("C4C8:08CF reached via 0913 slot BX==9; five bytes meet owned 08D4")
    _check_c4c8_0849(image, facts["d6ac_store"])
    checks.append("C4C8:0849 reached via 0913 slot BX==0; six bytes meet owned 08D4")
    _check_c4c8_084f(image, facts["d6ac_store"])
    checks.append("C4C8:084F reached via 0913 slot BX==1; sixteen bytes meet owned 08D4")
    _check_c4c8_085f(image, facts["d6ac_store"])
    checks.append("C4C8:085F reached via 0913 slot BX==2; sixteen bytes meet owned 08D4")
    _check_c4c8_086f(image, facts["d6ac_store"])
    checks.append("C4C8:086F reached via 0913 slot BX==3; sixteen bytes meet owned 08D4")
    _check_c4c8_0913_or_di_slots(image, facts["d6ac_store"])
    checks.append("C4C8:087F/088F/089F/08AF/08BF reached via 0913 slots BX==4..8; sixteen bytes each meet owned 08D4")
    _check_c4c8_17f6(image, facts["d6ac_store"])
    checks.append("C4C8:17F6 reached via 1818 slot BX==4; eight bytes meet owned 180C")
    _check_c4c8_17fe(image, facts["d6ac_store"])
    checks.append("C4C8:17FE reached via 1818 slot BX==5; eight bytes meet owned 180C")
    _check_c4c8_14a9(image, facts["d6ac_store"])
    checks.append("C4C8:14A9 reached via 1850 slots BX==2 and BX==3; fourteen bytes meet owned 14D3")
    _check_c4c8_14b7(image, facts["d6ac_store"])
    checks.append("C4C8:14B7 reached via 1850 slots BX==4 and BX==5; fourteen bytes meet owned 14D3")
    _check_c4c8_16e4(image, facts["d6ac_store"])
    checks.append("C4C8:16E4 reached via 1844 slot BX==1; store stub meets owned 17C8")
    _check_c4c8_16fd(image, facts["d6ac_store"])
    checks.append("C4C8:16FD reached via 1844 slot BX==2; store stub meets owned 17C8")
    _check_c4c8_1717(image, facts["d6ac_store"])
    checks.append("C4C8:1717 reached via 1844 slot BX==3; store stub meets owned 17C8")
    _check_ca9b_0004(image, facts["d6ac_store"])
    checks.append("CA9B:0004 reached via C425:01CE; body through RETF owned")
    _check_c6c2_1362(image, facts["d6ac_store"])
    checks.append("C6C2:1362 reached via DE5C:01D6; body through RETF owned")
    _check_c6c2_182d(image, facts["d6ac_store"])
    checks.append("C6C2:182D reached via C6C2:13C2; body through RETF owned")
    _check_c6c2_1324(image, facts["d6ac_store"])
    checks.append("C6C2:1324 reached via C6C2:13C9; body through RETF owned")
    _check_c6c2_12d2(image, facts["d6ac_store"])
    checks.append("C6C2:12D2 reached via C6C2:1340; body through RETF owned")
    _check_c6c2_11ef(image, facts["d6ac_store"])
    checks.append("C6C2:11EF reached via C6C2:12EE; body through RETF owned")
    _check_c6c2_1895(image, facts["d6ac_store"])
    checks.append("C6C2:1895 reached via C6C2:185F; body through RETF owned")
    _check_d90c_0338(image, facts["d6ac_store"])
    checks.append("D90C:0338 reached via C6C2:1873; body through RETF owned")
    _check_d90c_0574(image, facts["d6ac_store"])
    checks.append("D90C:0574 reached via D90C:0360; body through RET owned")
    _check_d90c_01ad(image, facts["d6ac_store"])
    checks.append("D90C:01AD reached via C6C2:1458; body through RETF owned")
    _check_c6c2_0d24(image, facts["d6ac_store"])
    checks.append("C6C2:0D24 reached via C6C2:14B5; body through RETF owned")
    _check_c6c2_1169(image, facts["d6ac_store"])
    checks.append("C6C2:1169 reached via C6C2:1546; body through RETF owned")
    _check_c4c8_0e5a(image, facts["d6ac_store"])
    checks.append("C4C8:0E5A reached via 0FDF; body through RETF owned")
    _check_c4c8_0e2b(image, facts["d6ac_store"])
    checks.append("C4C8:0E2B reached via 0E5A; body through both RETFs owned")
    _check_c4c8_0cf1(image, facts["d6ac_store"])
    checks.append("C4C8:0CF1 reached via 0E2B; body through both RETFs owned")
    _check_c4c8_0d8b(image, facts["d6ac_store"])
    checks.append("C4C8:0D8B reached via 0E2B; body through both RETFs owned")
    _check_d9a2_008d(image, facts["d6ac_store"])
    checks.append("D9A2:008D reached via 0CF1 and 0D8B; body through RETF owned")
    _check_b3fd_0b0b(image, facts["d6ac_store"])
    checks.append("B3FD:0B0B reached via 03EC; body through RETF owned")
    _check_b3fd_0d53(image, facts["d6ac_store"])
    checks.append("B3FD:0D53 reached via 0B0B; body through RETF owned")
    _check_b3fd_0ee9(image, facts["d6ac_store"])
    checks.append("B3FD:0EE9 reached via 0D53; body through RETF owned")
    _check_b3fd_0f79(image, facts["d6ac_store"])
    checks.append("B3FD:0F79 reached via 03FB; body through RETF owned")
    _check_b3fd_0acc(image, facts["d6ac_store"])
    checks.append("B3FD:0ACC reached via 0D53 and 0F79; body through RETF owned")
    _check_b77c_20ea(image, facts["d6ac_store"])
    checks.append("B77C:20EA reached via 0D53, 0EE9, and 0F79; body through RETF owned")
    _check_e605_000e(image, facts["d6ac_store"])
    checks.append("E605:000E reached via 0F79; body through RETF owned")
    _check_b77c_1f26(image, facts["d6ac_store"])
    checks.append("B77C:1F26 reached via 0F79; body through RETF owned")
    _check_e617_0004(image, facts["d6ac_store"])
    checks.append("E617:0004 reached via 0F79; body through six RETFs owned")
    _check_e617_02d7(image, facts["d6ac_store"])
    checks.append("E617:02D7 reached via 0004; body through RETF and loop owned")
    _check_e617_035a(image, facts["d6ac_store"])
    checks.append("E617:035A reached via 0004; body through three RETFs owned")
    _check_e617_03ae(image, facts["d6ac_store"])
    checks.append("E617:03AE reached via 0004; body through RETF owned")
    _check_e655_0004(image, facts["d6ac_store"])
    checks.append("E655:0004 reached via E617:0004; body through both RETFs owned")
    _check_e692_0000(image, facts["d6ac_store"])
    checks.append("E692:0000 reached via E617:0004; body through three RETFs owned")
    _check_e7d5_0001(image, facts["d6ac_store"])
    checks.append("E7D5:0001 reached via E692:0000; body through three RETFs owned")
    _check_b77c_202d(image, facts["d6ac_store"])
    checks.append("B77C:202D reached via BE1A:003F; body through RETF owned")
    _check_b77c_1f65(image, facts["d6ac_store"])
    checks.append("B77C:1F65 reached via B77C:202D; body through RETF owned")
    _check_b77c_205b(image, facts["d6ac_store"])
    checks.append("B77C:205B reached via CEBF:008D; body through RETF owned")
    _check_e72c_00a1(image, facts["d6ac_store"])
    checks.append("E72C:00A1 reached via B77C:207F; body through RETF owned")
    _check_e72c_0006(image, facts["d6ac_store"])
    checks.append("E72C:0006 reached via E72C:00AF; body through six RETFs owned")
    _check_d0c0_10b6(image, facts["d6ac_store"])
    checks.append("D0C0:10B6 reached via B77C:1F83; body through RETF owned")
    _check_d0c0_101d(image, facts["d6ac_store"])
    checks.append("D0C0:101D reached via D0C0:10E7; body through RETF owned")
    _check_f800_031f(image, facts["d6ac_store"])
    checks.append("F800:031F three CS words; CX=3 from owned F800:0F07")

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

    _check_idle_wake(image, amx["idle_wake"])
    checks.append("AMX idle wake: IVT[8] D52A:0008 tick word 10")

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

    hx = facts["hex_helper"]
    _expect_hex(image, int(hx["file"], 16), hx["bytes"], "F800:1896 hex stub")
    if image.count(bytes.fromhex(hx["bytes"])) != 1:
        raise AssertionError("F800:1896 stub is not unique")
    _expect_hex(image, int(hx["body_file"], 16), hx["body_bytes"], "F800:189C hex loop")
    _expect_hex(image, int(hx["ascii_file"], 16), hx["ascii_bytes"], "189C nibble ASCII")
    if image.count(bytes.fromhex(hx["ascii_bytes"])) != 1:
        raise AssertionError("189C nibble-to-ASCII convert is not unique")
    call_off = int(hx["call_18ca_file"], 16)
    _expect_hex(image, call_off, hx["call_18ca_bytes"], "189C CALL 18CA")
    rel = image[call_off + 1] | (image[call_off + 2] << 8)
    if rel >= 0x8000:
        rel -= 0x10000
    if (0x18C0 + 3 + rel) & 0xFFFF != 0x18CA:
        raise AssertionError("0x798C0 does not CALL F800:18CA")
    _expect_hex(image, int(hx["put_file"], 16), ax4["walker_bytes"], "18CA INT 43 AX=4")
    caller_off = int(hx["caller_file"], 16)
    _expect_hex(image, caller_off, hx["caller_bytes"], "F800:1A14 CALL 1896")
    if image.count(bytes.fromhex(hx["caller_bytes"])) != 1:
        raise AssertionError("CALL 1896 encoding is not unique")
    rel = image[caller_off + 1] | (image[caller_off + 2] << 8)
    if rel >= 0x8000:
        rel -= 0x10000
    if (0x1A14 + 3 + rel) & 0xFFFF != 0x1896:
        raise AssertionError("0x79A14 does not CALL F800:1896")
    if int(hx["lcd_put_file"], 16) != 0x7985A:
        raise AssertionError("hex helper lcd_put_file is not 0x7985A")
    if hx["digit_count"] != 2 or hx["pgr_slot"] != 62 or hx["xa"] != 1:
        raise AssertionError("hex helper digit_count / PGR slot / XA mismatch")
    checks.append("F800:1896 hex digits -> 18CA / INT 43 AX=4")

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
