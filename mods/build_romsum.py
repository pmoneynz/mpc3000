#!/usr/bin/env python3
"""Build a single-cluster staged checksum probe using the canary FAT layout."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from pathlib import Path

import build_canary as canary

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/mods"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def word_sum(data: bytes) -> int:
    return sum(struct.unpack(f"<{len(data)//2}H", data)) & 0xFFFF


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    body_path = OUT / "romsum.bin"
    subprocess.run(["nasm", "-f", "bin", "-o", str(body_path),
                    str(ROOT / "mods/romsum.asm")], check=True)
    body = body_path.read_bytes()
    size = len(body) + 32
    if size > 512:
        raise ValueError(f"probe must fit the canary's single cluster: {size}")
    header = struct.pack("<14H", 0x5A4D, size % 512, (size + 511) // 512,
                         0, 2, 0, 0xFFFF, 0, 0, 0, 0, 0, 0x1C, 0)
    payload = header.ljust(32, b"\0") + body
    image = canary.pack_floppy(payload)
    canary.directory_matches(image)
    linear = canary.interleave(canary.LS_PATH.read_bytes(), canary.MS_PATH.read_bytes())
    reference = linear[0x78000:0x80000]
    if word_sum(reference) != 0x8634:
        raise ValueError("reference no longer matches displayed expected sum")
    blocks = [f"{word_sum(reference[i:i+0x1000]):04X}" for i in range(0, 0x8000, 0x1000)]
    sys_path, img_path = OUT / "ROMSUM.SYS", OUT / "ROMSUM.img"
    sys_path.write_bytes(payload)
    img_path.write_bytes(image)
    manifest = {
        "format": "mpc3000-romsum-v2",
        "payload": {"path": str(sys_path.relative_to(ROOT)), "size": size, "sha256": sha(payload)},
        "image": {"path": str(img_path.relative_to(ROOT)), "size": len(image), "sha256": sha(image)},
        "disk_file": "STARTUP.SYS",
        "sources": {name: sha((ROOT / name).read_bytes()) for name in
                    ("mods/romsum.asm", "mods/build_romsum.py", "mods/build_canary.py")},
        "reference_linear_sha256": sha(linear),
        "expected_rows": ["ROMSUM2 ENTER", "SUM EXP 8634 ACT 8634",
                          "78000+4K: " + " ".join(blocks[:4]),
                          "7C000+4K: " + " ".join(blocks[4:]),
                          "ROMSUM2 DONE - PHOTO / POWER OFF"],
        "scope": "word sums only; no byte comparison or compatibility approval",
    }
    (OUT / "ROMSUM.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
