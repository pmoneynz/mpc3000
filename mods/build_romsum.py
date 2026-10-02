#!/usr/bin/env python3
"""Build a single-cluster staged checksum probe using the canary FAT layout."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_canary as canary  # noqa: E402
import buildkit as kit  # noqa: E402

ROOT = kit.ROOT
OUT = ROOT / "build/mods"

sha = kit.sha256
word_sum = kit.word_sum


def build(out: Path | None = None) -> dict:
    out = OUT if out is None else out
    body = kit.assemble(ROOT / "mods/romsum.asm", symbols=False,
                        publish_bin=out / "romsum.bin").code
    size = len(body) + 32
    if size > 512:
        raise ValueError(f"probe must fit the canary's single cluster: {size}")
    payload = kit.pack_mz(body)
    kit.validate_mz(payload)
    image = canary.pack_floppy(payload)
    canary.directory_matches(image)
    linear = kit.vailixi350()
    reference = linear[0x78000:0x80000]
    if word_sum(reference) != 0x8634:
        raise ValueError("reference no longer matches displayed expected sum")
    blocks = [f"{word_sum(reference[i:i+0x1000]):04X}" for i in range(0, 0x8000, 0x1000)]
    sys_path, img_path = out / "ROMSUM.SYS", out / "ROMSUM.img"
    kit.write_atomic(sys_path, payload)
    kit.write_atomic(img_path, image)
    manifest = {
        "format": "mpc3000-romsum-v2",
        "payload": {"path": kit.relpath(sys_path), "size": size, "sha256": sha(payload)},
        "image": {"path": kit.relpath(img_path), "size": len(image), "sha256": sha(image)},
        "disk_file": "STARTUP.SYS",
        "sources": {name: sha((ROOT / name).read_bytes()) for name in
                    ("mods/romsum.asm", "mods/build_romsum.py", "mods/build_canary.py",
                     "mods/buildkit.py")},
        "reference_linear_sha256": sha(linear),
        "expected_rows": ["ROMSUM2 ENTER", "SUM EXP 8634 ACT 8634",
                          "78000+4K: " + " ".join(blocks[:4]),
                          "7C000+4K: " + " ".join(blocks[4:]),
                          "ROMSUM2 DONE - PHOTO / POWER OFF"],
        "scope": "word sums only; no byte comparison or compatibility approval",
    }
    kit.write_atomic(out / "ROMSUM.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
