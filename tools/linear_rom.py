"""Build the Vailixi 3.50 linear 16-bit image from the LS/MS chip pair.

MAME loads LS at even bytes and MS at odd bytes (`ROM_SKIP(1)`). The linear
image is the CPU-visible 512 KiB at program addresses `0x00000-0x7FFFF`,
mirrored at `0x80000-0xFFFFF`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LS_PATH = REPO_ROOT / "07-rom" / "Vailixi 3.50" / "3.50 Vailixi (LSE).BIN"
MS_PATH = REPO_ROOT / "07-rom" / "Vailixi 3.50" / "3.50 Vailixi (MSO).BIN"

CHIP_SIZE = 262144
LINEAR_SIZE = 524288

LS_SHA256 = "cb4531fab4f2a43d3ad71465ac9efbe4bd6c3b23401cdbac379eea37234c4004"
MS_SHA256 = "514c745dea6bb711d19cf6e09bb4e7987f732c1bfa6b01857068c9982e295801"
LINEAR_SHA256 = "a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def interleave_ls_ms(ls: bytes, ms: bytes) -> bytes:
    if len(ls) != CHIP_SIZE or len(ms) != CHIP_SIZE:
        raise ValueError(f"chip images must be {CHIP_SIZE} bytes each, got {len(ls)}/{len(ms)}")
    out = bytearray(LINEAR_SIZE)
    out[0::2] = ls
    out[1::2] = ms
    return bytes(out)


def load_vailixi_linear(*, verify_chip_hashes: bool = True) -> bytes:
    ls = LS_PATH.read_bytes()
    ms = MS_PATH.read_bytes()
    if verify_chip_hashes:
        ls_hash = sha256_bytes(ls)
        ms_hash = sha256_bytes(ms)
        if ls_hash != LS_SHA256:
            raise ValueError(f"LS hash mismatch: {ls_hash}")
        if ms_hash != MS_SHA256:
            raise ValueError(f"MS hash mismatch: {ms_hash}")
    linear = interleave_ls_ms(ls, ms)
    if verify_chip_hashes:
        linear_hash = sha256_bytes(linear)
        if linear_hash != LINEAR_SHA256:
            raise ValueError(f"linear hash mismatch: {linear_hash}")
    return linear


def file_offset_from_phys20(phys20: int) -> int:
    """20-bit CPU address -> linear-file offset via the 512 KiB ROM mirror."""
    return phys20 & 0x7FFFF


def phys20_from_cs_ip(cs: int, ip: int) -> int:
    return ((cs << 4) + ip) & 0xFFFFF
