#!/usr/bin/env python3
"""Build the physical application-ROM capture probe and preallocated image."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

import build_canary as fat12

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "mods"
ASM = ROOT / "mods" / "romapp.asm"
CAPTURED_BIOS = ROOT / "build" / "hardware" / "2026-10-01-romdump" / "BIOS.BIN"
CAPTURED_BIOS_SHA256 = "2c654334e011af2943d1d08f05e3ce48ebccdf49600aab7a2f040ba016c21168"
SYS_PATH = OUT / "ROMAPP.SYS"
IMG_PATH = OUT / "ROMAPP.img"
MANIFEST_PATH = OUT / "ROMAPP.json"
OUTPUT_NAME = b"ROMAPP  BIN"
OUTPUT_SIZE = 0x54000
SENTINEL = bytes([0xA5]) * OUTPUT_SIZE
LOAD_BASE = 0x69000
# First- and third-PGR slots 0..39 select the same translated RAM.  The
# capture payload must remain wholly below logical A0000 while either table
# is active; only its explicit ES source window may cross that boundary.
SHARED_RAM_END = 0xA0000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_bios(path: Path = CAPTURED_BIOS) -> bytes:
    data = path.read_bytes()
    if len(data) != 0x8000:
        raise ValueError(f"captured BIOS is {len(data)} bytes, expected 32768")
    if sha256(data) != CAPTURED_BIOS_SHA256:
        raise ValueError("captured BIOS hash does not match the preserved hardware capture")
    return data


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
    if body_size >= 0x10000:
        raise ValueError("loaded body does not fit one CS segment")
    if LOAD_BASE + body_size > SHARED_RAM_END:
        raise ValueError("loaded body crosses the first/third-PGR shared RAM boundary")


def assemble(expected_bios: Path, stem: str = "romapp") -> tuple[bytes, dict[str, int]]:
    """Assemble with a data-only high-BIOS guard substitution.

    Non-default stems are for emulator fixtures.  They keep every generated
    file distinct from the physical candidate built by :func:`build`.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / f"{stem}.bin"
    map_path = OUT / f"{stem}.map"
    pre_path = OUT / f"{stem}_map.inc"
    bios_text = str(expected_bios.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    pre_path.write_text(f'%define EXPECTED_BIOS "{bios_text}"\n[map symbols {map_path}]\n')
    subprocess.run(
        ["nasm", "-f", "bin", "-P", str(pre_path), "-o", str(raw_path), str(ASM)],
        cwd=ROOT, check=True,
    )
    body = raw_path.read_bytes()
    labels = parse_map(map_path)
    required = ("start", "first_pgr_handler", "buffer", "buffer_end",
                "expected_bios", "expected_bios_end")
    missing = [name for name in required if name not in labels]
    if missing:
        raise ValueError(f"assembly map is missing labels: {missing}")
    if labels["buffer"] & 1:
        raise ValueError("capture buffer is not word-aligned")
    if labels["buffer_end"] - labels["buffer"] != 0x4000:
        raise ValueError("capture buffer is not exactly 16 KiB")
    if labels["expected_bios"] & 1:
        raise ValueError("embedded BIOS guard is not word-aligned")
    if labels["expected_bios_end"] - labels["expected_bios"] != 0x8000:
        raise ValueError("embedded BIOS guard is not exactly 32 KiB")
    if labels["expected_bios_end"] > len(body):
        raise ValueError("mapped objects exceed the assembled body")
    if LOAD_BASE + len(body) > SHARED_RAM_END:
        raise ValueError("assembled body crosses logical A0000 under the active PGR tables")
    return body, labels


def build_test_fixture(expected_bios: Path, stem: str) -> tuple[Path, Path, dict[str, int]]:
    """Build an explicitly named emulator fixture without touching ROMAPP.*.

    The only substituted bytes are the embedded 32 KiB guard.  Tests compare
    assembled bodies outside that mapped object before accepting a fixture.
    """
    if not stem or stem.casefold() == "romapp":
        raise ValueError("test fixture stem must be non-empty and distinct from ROMAPP")
    if Path(stem).name != stem:
        raise ValueError("test fixture stem must be a plain filename")
    body, labels = assemble(expected_bios, f"{stem}-asm")
    payload = pack_mz(body)
    image, _layout = pack_image(payload)
    sys_path = OUT / f"{stem}.SYS"
    img_path = OUT / f"{stem}.img"
    sys_path.write_bytes(payload)
    img_path.write_bytes(image)
    return sys_path, img_path, labels


def clusters_needed(size: int) -> int:
    return (size + fat12.BPS - 1) // fat12.BPS


def directory_entry(name: bytes, first_cluster: int, size: int) -> bytes:
    if len(name) != 11:
        raise ValueError("FAT name must be exactly 11 bytes")
    entry = bytearray(32)
    entry[:11] = name
    entry[11] = 0x20
    # MPC extended filename bytes +0C..+13 must remain zero.
    struct.pack_into("<H", entry, 26, first_cluster)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def pack_image(payload: bytes, output: bytes = SENTINEL) -> tuple[bytes, dict[str, object]]:
    if len(output) != OUTPUT_SIZE:
        raise ValueError("ROMAPP.BIN must be exactly 0x54000 bytes")
    sys_count = clusters_needed(len(payload))
    output_count = clusters_needed(len(output))
    sys_first = 2
    output_first = sys_first + sys_count
    output_last = output_first + output_count - 1
    max_clusters = fat12.SECTORS - fat12.DATA_START
    if output_last - 1 > max_clusters:
        raise ValueError("files do not fit FAT12 data area")

    disk = bytearray(fat12.SECTORS * fat12.BPS)
    disk[0:3] = b"\xeb\x3c\x90"
    disk[3:11] = b"MPC3KAPP"
    disk[11:32] = fat12.BIOS_BPB
    disk[0x26] = 0x29
    disk[0x27:0x2B] = b"RAPP"
    disk[0x2B:0x36] = b"ROMAPP     "
    disk[0x36:0x3E] = b"FAT12   "
    disk[0x1FE:0x200] = b"\x55\xaa"

    fat = bytearray(fat12.SECTORS_PER_FAT * fat12.BPS)
    fat[0:3] = b"\xf0\xff\xff"
    for first, count in ((sys_first, sys_count), (output_first, output_count)):
        for cluster in range(first, first + count):
            next_cluster = 0xFFF if cluster == first + count - 1 else cluster + 1
            fat12.fat12_set(fat, cluster, next_cluster)
    for copy in range(fat12.FAT_COUNT):
        start = (fat12.RESERVED + copy * fat12.SECTORS_PER_FAT) * fat12.BPS
        disk[start:start + len(fat)] = fat

    root = (fat12.RESERVED + fat12.FAT_COUNT * fat12.SECTORS_PER_FAT) * fat12.BPS
    disk[root:root + 32] = directory_entry(b"STARTUP SYS", sys_first, len(payload))
    disk[root + 32:root + 64] = directory_entry(OUTPUT_NAME, output_first, len(output))

    data = fat12.DATA_START * fat12.BPS
    sys_off = data + (sys_first - 2) * fat12.BPS
    output_off = data + (output_first - 2) * fat12.BPS
    disk[sys_off:sys_off + len(payload)] = payload
    disk[output_off:output_off + len(output)] = output
    if len(disk) != fat12.SECTORS * fat12.BPS:
        raise ValueError("disk image size changed")

    layout: dict[str, object] = {
        "startup_clusters": [sys_first, sys_first + sys_count - 1],
        "output_clusters": [output_first, output_last],
        "output_cluster_count": output_count,
        "output_data_offset": output_off,
        "root_directory_offset": root,
    }
    return bytes(disk), layout


def extract_contiguous(image: bytes, first_cluster: int, size: int) -> bytes:
    offset = fat12.DATA_START * fat12.BPS + (first_cluster - 2) * fat12.BPS
    return image[offset:offset + size]


def build() -> dict[str, object]:
    bios = checked_bios()
    body, labels = assemble(CAPTURED_BIOS)
    payload = pack_mz(body)
    image, layout = pack_image(payload)
    SYS_PATH.write_bytes(payload)
    IMG_PATH.write_bytes(image)

    first = int(layout["output_clusters"][0])
    if extract_contiguous(image, first, OUTPUT_SIZE) != SENTINEL:
        raise ValueError("initial ROMAPP.BIN sentinel changed")

    manifest: dict[str, object] = {
        "format": "mpc3000-romapp-capture-v1",
        "scope": {
            "captured_linear_file_range": ["0x20000", "0x74000"],
            "captured_bytes": OUTPUT_SIZE,
            "captured_kib": OUTPUT_SIZE // 1024,
            "runtime_first_pgr_range": ["0xA0000", "0xF4000"],
            "conditional_24_bit_range": ["0x0A0000", "0x0F4000"],
            "excluded_first_pgr_slot_61": "logical 0xF4000-0xF7FFF maps NVRAM frame 0x0140",
            "remaining_uncaptured_linear_ranges": [["0x00000", "0x20000"],
                                                    ["0x74000", "0x78000"]],
        },
        "payload": {"path": str(SYS_PATH.relative_to(ROOT)), "size": len(payload),
                    "sha256": sha256(payload), "load_base": "0x69000",
                    "body_end": f"0x{LOAD_BASE + len(body):05X}",
                    "shared_ram_end": f"0x{SHARED_RAM_END:05X}",
                    "inherited_ss_sp": "0040:69C4"},
        "image": {"path": str(IMG_PATH.relative_to(ROOT)), "size": len(image),
                  "sha256": sha256(image), "files": ["STARTUP.SYS", "ROMAPP.BIN"]},
        "romapp_bin_initial": {"size": OUTPUT_SIZE, "fill": "A5",
                               "sha256": sha256(SENTINEL)},
        "high_bios_guard": {"path": str(CAPTURED_BIOS.relative_to(ROOT)),
                            "size": len(bios), "sha256": sha256(bios),
                            "word_sum": f"{sum(struct.unpack('<16384H', bios)) & 0xFFFF:04X}"},
        "transition_contract": {
            "ivt12_ram": "0000:0048 under XA=1",
            "xa0_first_pgr_loop": {"cs_ip": "FAC0:01C6", "linear_file": "0x7ADC6"},
            "first_pgr_table": {"cs_ip": "FAC0:0256", "linear_file": "0x7AE56"},
            "xa1_restore_wrapper": {"cs_ip": "FAC0:024F", "linear_file": "0x7AE4F"},
            "third_pgr_restore": "INT 10 -> FAC0:01A4/01BD before every INT 41 write",
            "unknown_boundary": "NMI/board behavior during the brief XA=0 interval",
        },
        "io_contract": {
            "pages": 21,
            "page_bytes": 0x4000,
            "sectors_per_page": 32,
            "total_sectors": OUTPUT_SIZE // fat12.BPS,
            "file": "ROMAPP.BIN is preallocated to 0x54000 bytes; no allocation is requested",
            "copy": "aligned word reads into a 16 KiB RAM buffer under first PGR",
            "bios": "INT 41 AX=2 open, AX=5 sequential write, AX=3 close under third PGR",
            "icu_port_writes": ["C011=F6 before file calls", "C011=FF after close/error"],
            "hardware_write_path": "UNDETERMINED until one physical capture succeeds",
        },
        "layout": layout,
        "labels": {name: f"0x{labels[name]:04X}" for name in
                   ("start", "first_pgr_handler", "buffer", "buffer_end",
                    "expected_bios", "expected_bios_end")},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
