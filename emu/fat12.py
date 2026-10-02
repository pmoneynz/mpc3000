"""Read-only FAT12 checks for 1.44 MB test floppies (mformat -f 1440 layout).

Used by the near-full-media tests to inspect what the stock Disk code left
on the image: directory sizes, cluster chains, FAT copy agreement, and lost
clusters.  It never writes an image.
"""

from __future__ import annotations

import struct
from pathlib import Path

SECTOR = 512
FAT_OFFSET = 1 * SECTOR            # one reserved sector
FAT_SECTORS = 9
FAT_COPIES = 2
ROOT_OFFSET = FAT_OFFSET + FAT_COPIES * FAT_SECTORS * SECTOR   # 0x2600
ROOT_ENTRIES = 224
DATA_OFFSET = ROOT_OFFSET + ROOT_ENTRIES * 32                  # 0x4200
CLUSTER = SECTOR                   # one sector per cluster
CLUSTERS = 2880 - DATA_OFFSET // SECTOR                         # 2847


def _fat(image: bytes, copy: int = 0) -> list[int]:
    base = FAT_OFFSET + copy * FAT_SECTORS * SECTOR
    raw = image[base:base + FAT_SECTORS * SECTOR]
    out = []
    for n in range(CLUSTERS + 2):
        word = struct.unpack_from("<H", raw, n * 3 // 2)[0]
        out.append(word >> 4 if n & 1 else word & 0xFFF)
    return out


def entries(image: bytes) -> list[dict]:
    """Live root-directory entries (no LFN, no volume label)."""
    result = []
    for n in range(ROOT_ENTRIES):
        raw = image[ROOT_OFFSET + n * 32:ROOT_OFFSET + n * 32 + 32]
        if raw[0] == 0:
            break
        if raw[0] == 0xE5 or raw[11] & 0x08:
            continue
        result.append({"name": raw[0:8].decode("latin-1").rstrip(),
                       "ext": raw[8:11].decode("latin-1").rstrip(),
                       "cluster": struct.unpack_from("<H", raw, 26)[0],
                       "size": struct.unpack_from("<I", raw, 28)[0]})
    return result


def chain(image: bytes, first: int) -> list[int]:
    fat = _fat(image)
    out = []
    n = first
    while 2 <= n < 0xFF0:
        if n in out or len(out) > CLUSTERS:
            raise ValueError(f"FAT cycle at cluster {n}")
        out.append(n)
        n = fat[n]
    if n < 0xFF8:
        raise ValueError(f"chain from {first} ends in {n:#x}, not EOF")
    return out


def free_clusters(image: bytes) -> int:
    return sum(1 for value in _fat(image)[2:] if value == 0)


def read_file(image: bytes, entry: dict) -> bytes:
    data = b"".join(image[DATA_OFFSET + (c - 2) * CLUSTER:DATA_OFFSET + (c - 1) * CLUSTER]
                    for c in chain(image, entry["cluster"])) if entry["cluster"] else b""
    return data[:entry["size"]]


def check(image: bytes) -> dict:
    """Return a consistency report: FAT copies equal, chains sized, no lost clusters."""
    fat = _fat(image)
    owned: set[int] = set()
    sized = True
    for entry in entries(image):
        clusters = chain(image, entry["cluster"]) if entry["cluster"] else []
        if owned & set(clusters):
            raise ValueError("cross-linked clusters")
        owned |= set(clusters)
        sized &= len(clusters) == -(-entry["size"] // CLUSTER)
    allocated = {n for n in range(2, CLUSTERS + 2) if fat[n] != 0}
    return {"fat_copies_equal": _fat(image, 0) == _fat(image, 1),
            "chains_match_sizes": sized,
            "lost_clusters": sorted(allocated - owned),
            "free_clusters": free_clusters(image)}


def filler_bytes(image: Path, free_wanted: int) -> int:
    """Bytes for a filler file that leaves exactly ``free_wanted`` clusters."""
    free = free_clusters(image.read_bytes())
    if free < free_wanted:
        raise ValueError("image already has fewer free clusters")
    return (free - free_wanted) * CLUSTER
