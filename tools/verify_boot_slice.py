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
