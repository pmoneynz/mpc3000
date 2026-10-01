#!/usr/bin/env python3
"""Build a standalone high-ROM capture diagnostic and preallocated FAT12 image."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

import build_canary as canary

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "mods"
ASM = ROOT / "mods" / "romdump.asm"
SYS_PATH = OUT / "ROMDUMP.SYS"
IMG_PATH = OUT / "ROMDUMP.img"
MANIFEST_PATH = OUT / "ROMDUMP.json"
DUMP_NAME = b"BIOS    BIN"
DUMP_SIZE = 0x8000
SENTINEL = bytes([0xA5]) * DUMP_SIZE
LOAD_BASE = 0x69000
# CS=6900 starts 0x1000 bytes into the 16 KiB [0x68000, 0x6C000) page.
LOAD_WINDOW = 0x3000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def interleave_target() -> bytes:
    return canary.interleave(canary.LS_PATH.read_bytes(), canary.MS_PATH.read_bytes())


def parse_map(path: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    pattern = re.compile(r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)\s*$")
    for line in path.read_text().splitlines():
        if match := pattern.match(line):
            labels[match[3]] = int(match[2], 16)
    return labels


def pack_mz(body: bytes) -> bytes:
    size = 32 + len(body)
    header = struct.pack(
        "<14H", 0x5A4D, size % 512, (size + 511) // 512, 0, 2,
        0, 0xFFFF, 0, 0, 0, 0, 0, 0x1C, 0,
    )
    payload = header.ljust(32, b"\0") + body
    validate_mz(payload)
    return payload


def validate_mz(payload: bytes) -> None:
    """Replay the relevant INT 45 header facts and inherited-stack contract."""
    if len(payload) < 32:
        raise ValueError("MZ payload is shorter than its header")
    fields = struct.unpack_from("<14H", payload)
    magic, cblp, pages, relocations, header_paras = fields[:5]
    if magic != 0x5A4D or relocations != 0 or header_paras != 2:
        raise ValueError("unsupported MZ header")
    file_size = pages * 512 if cblp == 0 else (pages - 1) * 512 + cblp
    if file_size != len(payload):
        raise ValueError("MZ page fields do not match the file size")
    ss, sp = fields[7:9]
    ip, cs = fields[10:12]
    if (cs, ip, ss, sp) != (0, 0, 0, 0):
        raise ValueError("MZ must enter at 6900:0000 and retain the inherited stack")
    body_size = len(payload) - header_paras * 16
    if LOAD_BASE + body_size > LOAD_BASE + LOAD_WINDOW:
        raise ValueError("loaded body crosses its first 16 KiB window")


def clusters_needed(size: int) -> int:
    return (size + canary.BPS - 1) // canary.BPS


def directory_entry(name: bytes, first_cluster: int, size: int) -> bytes:
    if len(name) != 11:
        raise ValueError("FAT name must be exactly 11 bytes")
    entry = bytearray(32)
    entry[:11] = name
    entry[11] = 0x20
    # Bytes +0C..+13 stay NUL: MPC filename characters 9-16, not timestamps.
    struct.pack_into("<H", entry, 26, first_cluster)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def pack_image(payload: bytes, dump: bytes = SENTINEL) -> tuple[bytes, dict[str, object]]:
    if len(dump) != DUMP_SIZE:
        raise ValueError("BIOS.BIN must be exactly 32 KiB")
    sys_count = clusters_needed(len(payload))
    dump_count = clusters_needed(len(dump))
    sys_first = 2
    dump_first = sys_first + sys_count
    last_cluster = dump_first + dump_count - 1
    max_clusters = canary.SECTORS - canary.DATA_START
    if last_cluster - 1 > max_clusters:
        raise ValueError("files do not fit FAT12 data area")

    disk = bytearray(canary.SECTORS * canary.BPS)
    disk[0:3] = b"\xeb\x3c\x90"
    disk[3:11] = b"MPC3KDMP"
    disk[11:32] = canary.BIOS_BPB
    disk[0x26] = 0x29
    disk[0x27:0x2B] = b"RDMP"
    disk[0x2B:0x36] = b"ROMDUMP    "
    disk[0x36:0x3E] = b"FAT12   "
    disk[0x1FE:0x200] = b"\x55\xaa"

    fat = bytearray(canary.SECTORS_PER_FAT * canary.BPS)
    fat[0:3] = b"\xf0\xff\xff"
    for first, count in ((sys_first, sys_count), (dump_first, dump_count)):
        for cluster in range(first, first + count):
            canary.fat12_set(fat, cluster, 0xFFF if cluster == first + count - 1 else cluster + 1)
    for copy in range(canary.FAT_COUNT):
        start = (canary.RESERVED + copy * canary.SECTORS_PER_FAT) * canary.BPS
        disk[start:start + len(fat)] = fat

    root = (canary.RESERVED + canary.FAT_COUNT * canary.SECTORS_PER_FAT) * canary.BPS
    disk[root:root + 32] = directory_entry(b"STARTUP SYS", sys_first, len(payload))
    disk[root + 32:root + 64] = directory_entry(DUMP_NAME, dump_first, len(dump))

    data = canary.DATA_START * canary.BPS
    sys_off = data + (sys_first - 2) * canary.BPS
    dump_off = data + (dump_first - 2) * canary.BPS
    disk[sys_off:sys_off + len(payload)] = payload
    disk[dump_off:dump_off + len(dump)] = dump
    if len(disk) != canary.SECTORS * canary.BPS:
        raise ValueError("disk image size changed")

    layout: dict[str, object] = {
        "startup_clusters": [sys_first, sys_first + sys_count - 1],
        "dump_clusters": [dump_first, last_cluster],
        "dump_data_offset": dump_off,
        "root_directory_offset": root,
    }
    return bytes(disk), layout


def extract_file(image: bytes, first_cluster: int, size: int) -> bytes:
    """Extract a contiguous file from the deterministic image layout."""
    data = canary.DATA_START * canary.BPS + (first_cluster - 2) * canary.BPS
    return image[data:data + size]


def build() -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / "romdump.bin"
    map_path = OUT / "romdump.map"
    pre_path = OUT / "romdump_map.inc"
    pre_path.write_text(f"[map symbols {map_path}]\n")
    subprocess.run(
        ["nasm", "-f", "bin", "-P", str(pre_path), "-o", str(raw_path), str(ASM)],
        cwd=ROOT, check=True,
    )
    body = raw_path.read_bytes()
    labels = parse_map(map_path)
    if labels.get("buffer", 1) & 1:
        raise ValueError("capture buffer is not word-aligned")
    if labels.get("buffer_end", 0) - labels.get("buffer", 0) != canary.BPS:
        raise ValueError("capture buffer is not exactly one sector")
    payload = pack_mz(body)
    image, layout = pack_image(payload)
    SYS_PATH.write_bytes(payload)
    IMG_PATH.write_bytes(image)

    target = interleave_target()
    reference = target[0x78000:0x80000]
    dump_first = int(layout["dump_clusters"][0])
    if extract_file(image, dump_first, DUMP_SIZE) != SENTINEL:
        raise ValueError("initial BIOS.BIN sentinel changed")

    manifest: dict[str, object] = {
        "format": "mpc3000-high-rom-capture-v1",
        "scope": "capture runtime F800:0000-7FFF only; no compatibility approval or guard bypass",
        "payload": {"path": str(SYS_PATH.relative_to(ROOT)), "size": len(payload),
                    "sha256": sha256(payload), "load_base": "0x69000",
                    "body_end": f"0x{LOAD_BASE + len(body):05X}",
                    "load_window_end": "0x6C000", "inherited_ss_sp": "0040:69C4"},
        "image": {"path": str(IMG_PATH.relative_to(ROOT)), "size": len(image),
                  "sha256": sha256(image), "files": ["STARTUP.SYS", "BIOS.BIN"]},
        "bios_bin_initial": {"size": DUMP_SIZE, "fill": "A5", "sha256": sha256(SENTINEL)},
        "expected_reference_capture": {
            "linear_file_range": ["0x78000", "0x80000"],
            "sha256": sha256(reference),
            "word_sum": f"{sum(struct.unpack('<16384H', reference)) & 0xFFFF:04X}",
        },
        "runtime_address": {
            "cs_operand": "F800:0000-7FFF",
            "logical_20_bit": "0xF8000-0xFFFFF",
            "mode": "XA=1, third PGR",
            "reference_third_pgr_slots": {"62": "0x003E", "63": "0x003F"},
            "conditional_24_bit": "0x0F8000-0x0FFFFF if physical slots match the reference",
        },
        "io_contract": {
            "file": "BIOS.BIN is preallocated to 32768 bytes; no allocation is requested",
            "copy": "64 chunks; 256 aligned ROM word reads into a 512-byte RAM buffer per chunk",
            "bios": "INT 41 AX=2 open, AX=5 sequential write, AX=3 close",
            "icu_port_writes": ["C011=F6 before file calls", "C011=FF after close/error"],
            "hardware_write_path": "UNDETERMINED until one physical capture succeeds",
        },
        "layout": layout,
        "labels": {name: f"0x{labels[name]:04X}" for name in
                   ("start", "buffer", "buffer_end") if name in labels},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
