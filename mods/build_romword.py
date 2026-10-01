#!/usr/bin/env python3
"""Build a one-page, word-only comparison of the two mismatching ROM blocks."""
from __future__ import annotations
import json
import struct
import subprocess
from pathlib import Path

import build_canary as canary
import build_romcheck as full

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/mods"


def summary(reference: bytes, actual: bytes) -> dict:
    a = struct.unpack("<4096H", reference)
    b = struct.unpack("<4096H", actual)
    diffs = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    first = diffs[0]*2 if diffs else None
    last = diffs[-1]*2 if diffs else None
    sample = min(first, 0x1FF8) if first is not None else 0
    exp = struct.unpack_from("<4H", reference, sample)
    got = struct.unpack_from("<4H", actual, sample)
    return {
        "mismatching_words": len(diffs),
        "first_file_offset": f"{0x7A000+first:05X}" if first is not None else None,
        "last_file_offset": f"{0x7A000+last:05X}" if last is not None else None,
        "first_expected_word": f"{a[diffs[0]]:04X}" if diffs else None,
        "first_actual_word": f"{b[diffs[0]]:04X}" if diffs else None,
        "sample_file_offset": f"{0x7A000+sample:05X}",
        "expected_words": [f"{v:04X}" for v in exp],
        "actual_words": [f"{v:04X}" for v in got],
    }


def pack_floppy(payload: bytes) -> bytes:
    disk = bytearray(canary.pack_floppy(b"x"))
    sectors = (len(payload)+511)//512
    fat = bytearray(canary.SECTORS_PER_FAT*512)
    fat[:3] = b"\xF0\xFF\xFF"
    for cluster in range(2, 2+sectors):
        canary.fat12_set(fat, cluster, 0xFFF if cluster == sectors+1 else cluster+1)
    for index in range(2):
        off = (1+index*9)*512
        disk[off:off+len(fat)] = fat
    struct.pack_into("<I", disk, 19*512+28, len(payload))
    disk[33*512:33*512+len(payload)] = payload
    return bytes(disk)


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    linear = full.interleave(full.LS_PATH, full.MS_PATH)
    reference = linear[0x7A000:0x7C000]
    assert full.word_sum(reference) == 0x11F8
    expected_path = OUT / "romword_expected.bin"
    expected_path.write_bytes(reference)
    map_path = OUT / "romword.map"
    pre_path = OUT / "romword_map.inc"
    pre_path.write_text(f"[map symbols {map_path}]\n")
    body_path = OUT / "romword.bin"
    subprocess.run(["nasm", "-f", "bin", f'-DEXPECTED_BIN="{expected_path}"',
                    "-P", str(pre_path), "-o", str(body_path), str(ROOT / "mods/romword.asm")], check=True)
    body = body_path.read_bytes()
    labels = full.parse_map(map_path)
    assert len(body)+32 <= 0x3000, "payload must fit initial mapped page at CS=6900"
    assert labels['expected_bios'] % 2 == 0
    assert body[labels['expected_bios']:] == reference
    payload = full.pack_mz(body)
    image = pack_floppy(payload)
    (OUT / "ROMWORD.SYS").write_bytes(payload)
    (OUT / "ROMWORD.img").write_bytes(image)
    actual312 = full.interleave(full.LS312_PATH, full.MS312_PATH)[0x7A000:0x7C000]
    manifest = {
        "format": "mpc3000-romword-v5",
        "scope": "aligned-word comparison of reference-file 7A000-7BFFF only; no compatibility approval",
        "reference_word_sum": "11F8",
        "reference_sha256": full.sha256(reference),
        "payload": {"path": "build/mods/ROMWORD.SYS", "size": len(payload), "sha256": full.sha256(payload)},
        "image": {"path": "build/mods/ROMWORD.img", "size": len(image), "sha256": full.sha256(image)},
        "disk_file": "STARTUP.SYS",
        "labels": {k: f"{labels[k]:04X}" for k in ("expected_bios", "expected_bios_end")},
        "expected": {"vailixi": summary(reference, reference), "312": summary(reference, actual312)},
    }
    (OUT / "ROMWORD.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
