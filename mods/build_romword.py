#!/usr/bin/env python3
"""Build a one-page, word-only comparison of the two mismatching ROM blocks."""
from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_canary as canary  # noqa: E402
import build_romcheck as full  # noqa: E402
import buildkit as kit  # noqa: E402

ROOT = kit.ROOT
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
    """The canary layout with a contiguous multi-cluster STARTUP.SYS."""
    image, _ = kit.pack_fat12([("STARTUP.SYS", payload)], oem=b"MPC3KCAN",
                              volume_id=canary.VOLUME_ID, label=canary.VOLUME_LABEL)
    return image


def build(out: Path | None = None) -> dict:
    out = OUT if out is None else out
    linear = full.interleave(full.LS_PATH, full.MS_PATH)
    reference = linear[0x7A000:0x7C000]
    if full.word_sum(reference) != 0x11F8:
        raise ValueError("reference 7A000-7BFFF no longer has word sum 11F8")
    with tempfile.TemporaryDirectory(prefix="romword-") as scratch:
        expected_path = Path(scratch) / "romword_expected.bin"
        expected_path.write_bytes(reference)
        asm = kit.assemble(ROOT / "mods/romword.asm",
                           defines={"EXPECTED_BIN": kit.nasm_string(expected_path)},
                           publish_bin=out / "romword.bin", publish_map=out / "romword.map")
    kit.write_atomic(out / "romword_expected.bin", reference)
    body, labels = asm.code, asm.labels
    if len(body) + 32 > 0x3000:
        raise ValueError("payload must fit initial mapped page at CS=6900")
    if "expected_bios" not in labels or labels["expected_bios"] % 2:
        raise ValueError("embedded reference is missing or not word-aligned")
    if body[labels["expected_bios"]:] != reference:
        raise ValueError("embedded reference differs from linear 7A000-7BFFF")
    payload = full.pack_mz(body)
    kit.validate_mz(payload)
    image = pack_floppy(payload)
    kit.write_atomic(out / "ROMWORD.SYS", payload)
    kit.write_atomic(out / "ROMWORD.img", image)
    actual312 = full.interleave(full.LS312_PATH, full.MS312_PATH)[0x7A000:0x7C000]
    manifest = {
        "format": "mpc3000-romword-v5",
        "scope": "aligned-word comparison of reference-file 7A000-7BFFF only; no compatibility approval",
        "reference_word_sum": "11F8",
        "reference_sha256": full.sha256(reference),
        "payload": {"path": kit.relpath(out / "ROMWORD.SYS"), "size": len(payload),
                    "sha256": full.sha256(payload)},
        "image": {"path": kit.relpath(out / "ROMWORD.img"), "size": len(image),
                  "sha256": full.sha256(image)},
        "disk_file": "STARTUP.SYS",
        "labels": {k: f"{labels[k]:04X}" for k in ("expected_bios", "expected_bios_end")},
        "expected": {"vailixi": summary(reference, reference), "312": summary(reference, actual312)},
    }
    kit.write_atomic(out / "ROMWORD.json", (json.dumps(manifest, indent=2)+"\n").encode())
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
