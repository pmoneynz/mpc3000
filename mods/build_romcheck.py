#!/usr/bin/env python3
"""Build a read-only BIOS identity diagnostic as ROMCHECK.SYS/ROMCHECK.img."""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildkit as kit  # noqa: E402

ROOT = kit.ROOT
ROM = kit.ROM350
LS_PATH = kit.LS350_PATH
MS_PATH = kit.MS350_PATH
ROM312 = kit.ROM312
LS312_PATH = kit.LS312_PATH
MS312_PATH = kit.MS312_PATH
ASM = ROOT / "mods" / "romcheck.asm"
OUT = ROOT / "build" / "mods"
SYS_PATH = OUT / "ROMCHECK.SYS"
IMG_PATH = OUT / "ROMCHECK.img"
MANIFEST_PATH = OUT / "ROMCHECK.json"
BIOS_RANGE = (0x78000, 0x80000)
FAT12_ROOT_OFFSET = kit.ROOT_OFFSET

sha256 = kit.sha256
word_sum = kit.word_sum
pack_mz = kit.pack_mz
parse_map = kit.parse_map


def interleave(ls_path: Path, ms_path: Path) -> bytes:
    """Linear image of a chip pair; the Vailixi 3.50 pair is hash-pinned."""
    digest = kit.VAILIXI350_SHA256 if (ls_path, ms_path) == (LS_PATH, MS_PATH) else None
    return kit.linear(ls_path, ms_path, digest)


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


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


def assemble(reference: bytes, out: Path | None = None) -> tuple[bytes, dict[str, int]]:
    out = OUT if out is None else out
    with tempfile.TemporaryDirectory(prefix="romcheck-") as scratch:
        expected_path = Path(scratch) / "romcheck_expected.bin"
        expected_path.write_bytes(reference)
        asm = kit.assemble(ASM, defines={"EXPECTED_BIN": kit.nasm_string(expected_path)},
                           publish_bin=out / "romcheck.bin", publish_map=out / "romcheck.map")
    kit.write_atomic(out / "romcheck_expected.bin", reference)
    body = bytearray(asm.code)
    labels = asm.labels
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


def pack_image(payload: bytes) -> bytes:
    image, _ = kit.pack_fat12([("STARTUP.SYS", payload)], oem=b"MPC3KCHK",
                              volume_id=b"RCHK", label=b"ROMCHECK   ")
    return image


def build(out: Path | None = None) -> dict[str, object]:
    out = OUT if out is None else out
    sys_path, img_path, manifest_path = out / SYS_PATH.name, out / IMG_PATH.name, out / MANIFEST_PATH.name
    linear = interleave(LS_PATH, MS_PATH)
    reference = linear[BIOS_RANGE[0]:BIOS_RANGE[1]]
    body, labels = assemble(reference, out)
    payload = pack_mz(body)
    kit.validate_mz(payload)
    image = pack_image(payload)
    kit.write_atomic(sys_path, payload)
    kit.write_atomic(img_path, image)

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
        "payload": {"path": kit.relpath(sys_path), "size": len(payload), "sha256": sha256(payload)},
        "image": {"path": kit.relpath(img_path), "size": len(image),
                  "sha256": sha256(image), "disk_name": "STARTUP.SYS"},
        "labels": {name: f"0x{labels[name]:04X}" for name in sorted(labels) if name in {
            "start", "stack_bottom", "stack_top", "expected_sum", "expected_crc", "expected_bios",
            "expected_bios_end"}},
        "expected_screens": {
            "vailixi_repo_target": screen_expectation(reference, reference),
            "stock_3_12": screen_expectation(reference, bios312),
        },
    }
    kit.write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
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
