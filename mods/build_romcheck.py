#!/usr/bin/env python3
"""Build a read-only BIOS identity diagnostic as ROMCHECK.SYS/ROMCHECK.img."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "07-rom" / "Vailixi 3.50"
LS_PATH = ROM / "3.50 Vailixi (LSE).BIN"
MS_PATH = ROM / "3.50 Vailixi (MSO).BIN"
ROM312 = ROOT / "07-rom" / "v3.12"
LS312_PATH = ROM312 / "MPC312LS.BIN"
MS312_PATH = ROM312 / "MPC312MS.BIN"
ASM = ROOT / "mods" / "romcheck.asm"
OUT = ROOT / "build" / "mods"
SYS_PATH = OUT / "ROMCHECK.SYS"
IMG_PATH = OUT / "ROMCHECK.img"
MANIFEST_PATH = OUT / "ROMCHECK.json"
BIOS_RANGE = (0x78000, 0x80000)
FAT12_ROOT_OFFSET = 19 * 512


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def interleave(ls_path: Path, ms_path: Path) -> bytes:
    ls, ms = ls_path.read_bytes(), ms_path.read_bytes()
    if len(ls) != 0x40000 or len(ms) != 0x40000:
        raise ValueError(f"chip size {len(ls)}/{len(ms)}, expected 262144")
    image = bytearray(0x80000)
    image[0::2], image[1::2] = ls, ms
    return bytes(image)


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def word_sum(data: bytes) -> int:
    if len(data) & 1:
        raise ValueError("word sum needs an even byte count")
    return sum(struct.unpack(f"<{len(data) // 2}H", data)) & 0xFFFF


def compare_summary(reference: bytes, actual: bytes) -> dict[str, object]:
    if len(reference) != 0x8000 or len(actual) != 0x8000:
        raise ValueError("BIOS comparison needs two 32 KiB windows")
    diffs = [i for i, (expected, got) in enumerate(zip(reference, actual)) if expected != got]
    blocks = [sum(a != b for a, b in zip(reference[off:off + 0x2000], actual[off:off + 0x2000]))
              for off in range(0, 0x8000, 0x2000)]
    first = diffs[0] if diffs else None
    last = diffs[-1] if diffs else None
    sample = min(first, 0x7FF8) if first is not None else 0
    return {
        "actual_word_sum": f"{word_sum(actual):04X}",
        "mismatch_count": len(diffs),
        "first_linear_offset": f"0x{BIOS_RANGE[0] + first:05X}" if first is not None else None,
        "last_linear_offset": f"0x{BIOS_RANGE[0] + last:05X}" if last is not None else None,
        "block_8k_mismatch_counts": blocks,
        "sample_linear_offset": f"0x{BIOS_RANGE[0] + sample:05X}",
        "sample_expected_hex": reference[sample:sample + 8].hex().upper(),
        "sample_actual_hex": actual[sample:sample + 8].hex().upper(),
    }


def screen_expectation(reference: bytes, actual: bytes) -> dict[str, object]:
    summary = compare_summary(reference, actual)
    first = summary["first_linear_offset"]
    last = summary["last_linear_offset"]
    blocks = summary["block_8k_mismatch_counts"]
    expected_sum = word_sum(reference)
    crc = crc16_ccitt_false(reference)
    rows = [
        "ROMCHECK4 STOP",
        f"SUM EXP {expected_sum:04X} ACT {word_sum(actual):04X}",
        f"REF CRC EXP {crc:04X} ACT {crc:04X} OK ",
        f"DIFF {summary['mismatch_count']:05X} FIRST {first[2:] if first else '-----'} "
        f"LAST {last[2:] if last else '-----'}",
        "8K " + " ".join(f"{count:05X}" for count in blocks),
        f"OFF {summary['sample_linear_offset'][2:]} EXP:{summary['sample_expected_hex']}",
        f"          GOT:{summary['sample_actual_hex']}",
        "NO OS COPY - POWER OFF / PHOTO",
    ]
    if len(rows) != 8 or any(len(row) > 40 for row in rows):
        raise ValueError(f"report does not fit 40x8: {[len(row) for row in rows]}")
    return summary | {"report_rows": rows}


def parse_map(path: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    pattern = re.compile(r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)\s*$")
    for line in path.read_text().splitlines():
        match = pattern.match(line)
        if match:
            labels[match[3]] = int(match[2], 16)
    return labels


def assemble(reference: bytes) -> tuple[bytes, dict[str, int]]:
    OUT.mkdir(parents=True, exist_ok=True)
    expected_path = OUT / "romcheck_expected.bin"
    raw_path = OUT / "romcheck.bin"
    map_path = OUT / "romcheck.map"
    pre_path = OUT / "romcheck_map.inc"
    expected_path.write_bytes(reference)
    pre_path.write_text(f"[map symbols {map_path}]\n")
    define = f'-DEXPECTED_BIN="{expected_path}"'
    subprocess.run(["nasm", "-f", "bin", define, "-P", str(pre_path), "-o", str(raw_path), str(ASM)],
                   cwd=ROOT, check=True)
    body = bytearray(raw_path.read_bytes())
    labels = parse_map(map_path)
    required = {"expected_sum", "expected_crc", "expected_bios", "expected_bios_end", "stack_top"}
    if missing := required - labels.keys():
        raise ValueError(f"NASM map lacks labels: {sorted(missing)}")
    if labels["expected_bios_end"] - labels["expected_bios"] != 0x8000:
        raise ValueError("embedded BIOS is not 32 KiB")
    if labels["expected_bios_end"] != len(body):
        raise ValueError("unexpected data follows embedded BIOS")
    if len(body) >= 0x10000 or labels["stack_top"] > labels["expected_bios"]:
        raise ValueError("payload no longer fits one segment")
    struct.pack_into("<H", body, labels["expected_sum"], word_sum(reference))
    struct.pack_into("<H", body, labels["expected_crc"], crc16_ccitt_false(reference))
    if body[labels["expected_bios"]:] != reference:
        raise ValueError("embedded BIOS changed during assembly")
    return bytes(body), labels


def pack_mz(body: bytes) -> bytes:
    size = 32 + len(body)
    header = struct.pack("<14H", 0x5A4D, size % 512, (size + 511) // 512, 0, 2, 0, 0xFFFF,
                         0, 0, 0, 0, 0, 0x1C, 0)
    return header.ljust(32, b"\0") + body


def normalize_startup_dirent(image: bytes) -> bytes:
    """Clear mtools metadata where the MPC stores filename characters 9-16."""
    disk = bytearray(image)
    entry = disk[FAT12_ROOT_OFFSET:FAT12_ROOT_OFFSET + 32]
    if entry[:11] != b"STARTUP SYS" or entry[11] != 0x20:
        raise ValueError("STARTUP.SYS is not the first normal root entry")
    disk[FAT12_ROOT_OFFSET + 0x0C:FAT12_ROOT_OFFSET + 0x14] = bytes(8)
    return bytes(disk)


def build() -> dict[str, object]:
    linear = interleave(LS_PATH, MS_PATH)
    reference = linear[BIOS_RANGE[0]:BIOS_RANGE[1]]
    body, labels = assemble(reference)
    payload = pack_mz(body)
    SYS_PATH.write_bytes(payload)
    IMG_PATH.unlink(missing_ok=True)
    subprocess.run(["mformat", "-C", "-f", "1440", "-i", str(IMG_PATH), "::"], check=True)
    subprocess.run(["mcopy", "-i", str(IMG_PATH), str(SYS_PATH), "::STARTUP.SYS"], check=True)
    IMG_PATH.write_bytes(normalize_startup_dirent(IMG_PATH.read_bytes()))

    linear312 = interleave(LS312_PATH, MS312_PATH)
    bios312 = linear312[BIOS_RANGE[0]:BIOS_RANGE[1]]
    manifest: dict[str, object] = {
        "format": "mpc3000-romcheck-v4",
        "safety": "read BIOS, write LCD, halt; no OS/PGR/floppy/NVRAM writes",
        "reference": {
            "linear_file_range": ["0x78000", "0x80000"],
            "sha256": sha256(reference),
            "word_sum": f"{word_sum(reference):04X}",
            "crc16_ccitt_false": f"{crc16_ccitt_false(reference):04X}",
            "ls_sha256": sha256(LS_PATH.read_bytes()),
            "ms_sha256": sha256(MS_PATH.read_bytes()),
        },
        "payload": {"path": str(SYS_PATH.relative_to(ROOT)), "size": len(payload), "sha256": sha256(payload)},
        "image": {"path": str(IMG_PATH.relative_to(ROOT)), "size": IMG_PATH.stat().st_size,
                  "sha256": sha256(IMG_PATH.read_bytes()), "disk_name": "STARTUP.SYS"},
        "labels": {name: f"0x{labels[name]:04X}" for name in sorted(labels) if name in {
            "start", "stack_bottom", "stack_top", "expected_sum", "expected_crc", "expected_bios",
            "expected_bios_end"}},
        "expected_screens": {
            "vailixi_repo_target": screen_expectation(reference, reference),
            "stock_3_12": screen_expectation(reference, bios312),
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    manifest = build()
    ref = manifest["reference"]
    print(f"{SYS_PATH}  {manifest['payload']['size']} bytes")
    print(IMG_PATH)
    print(MANIFEST_PATH)
    print(f"expected sum {ref['word_sum']} CRC16 {ref['crc16_ccitt_false']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
