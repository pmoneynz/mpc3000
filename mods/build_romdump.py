#!/usr/bin/env python3
"""Build a standalone high-ROM capture diagnostic and preallocated FAT12 image."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildkit as kit  # noqa: E402

ROOT = kit.ROOT
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

sha256 = kit.sha256
parse_map = kit.parse_map
clusters_needed = kit.clusters_needed
directory_entry = kit.directory_entry


def interleave_target() -> bytes:
    return kit.vailixi350()


def pack_mz(body: bytes) -> bytes:
    payload = kit.pack_mz(body)
    validate_mz(payload)
    return payload


def validate_mz(payload: bytes) -> None:
    """Replay the relevant INT 45 header facts and inherited-stack contract."""
    body_size = kit.validate_mz(payload)
    if LOAD_BASE + body_size > LOAD_BASE + LOAD_WINDOW:
        raise ValueError("loaded body crosses its first 16 KiB window")


def pack_image(payload: bytes, dump: bytes = SENTINEL) -> tuple[bytes, dict[str, object]]:
    if len(dump) != DUMP_SIZE:
        raise ValueError("BIOS.BIN must be exactly 32 KiB")
    disk, (sys_file, dump_file) = kit.pack_fat12(
        [("STARTUP.SYS", payload), (DUMP_NAME, dump)],
        oem=b"MPC3KDMP", volume_id=b"RDMP", label=b"ROMDUMP    ")
    layout: dict[str, object] = {
        "startup_clusters": [sys_file["first_cluster"], sys_file["last_cluster"]],
        "dump_clusters": [dump_file["first_cluster"], dump_file["last_cluster"]],
        "dump_data_offset": dump_file["data_offset"],
        "root_directory_offset": kit.ROOT_OFFSET,
    }
    return disk, layout


def extract_file(image: bytes, first_cluster: int, size: int) -> bytes:
    """Extract a contiguous file from the deterministic image layout."""
    return kit.extract_contiguous(image, first_cluster, size)


def build(out: Path | None = None) -> dict[str, object]:
    out = OUT if out is None else out
    sys_path, img_path, manifest_path = out / SYS_PATH.name, out / IMG_PATH.name, out / MANIFEST_PATH.name
    asm = kit.assemble(ASM, publish_bin=out / "romdump.bin", publish_map=out / "romdump.map")
    body, labels = asm.code, asm.labels
    if labels.get("buffer", 1) & 1:
        raise ValueError("capture buffer is not word-aligned")
    if labels.get("buffer_end", 0) - labels.get("buffer", 0) != kit.BPS:
        raise ValueError("capture buffer is not exactly one sector")
    payload = pack_mz(body)
    image, layout = pack_image(payload)
    kit.write_atomic(sys_path, payload)
    kit.write_atomic(img_path, image)

    target = interleave_target()
    reference = target[0x78000:0x80000]
    dump_first = int(layout["dump_clusters"][0])
    if extract_file(image, dump_first, DUMP_SIZE) != SENTINEL:
        raise ValueError("initial BIOS.BIN sentinel changed")

    manifest: dict[str, object] = {
        "format": "mpc3000-high-rom-capture-v1",
        "scope": "capture runtime F800:0000-7FFF only; no compatibility approval or guard bypass",
        "payload": {"path": kit.relpath(sys_path), "size": len(payload),
                    "sha256": sha256(payload), "load_base": "0x69000",
                    "body_end": f"0x{LOAD_BASE + len(body):05X}",
                    "load_window_end": "0x6C000", "inherited_ss_sp": "0040:69C4"},
        "image": {"path": kit.relpath(img_path), "size": len(image),
                  "sha256": sha256(image), "files": ["STARTUP.SYS", "BIOS.BIN"]},
        "bios_bin_initial": {"size": DUMP_SIZE, "fill": "A5", "sha256": sha256(SENTINEL)},
        "expected_reference_capture": {
            "linear_file_range": ["0x78000", "0x80000"],
            "sha256": sha256(reference),
            "word_sum": f"{kit.word_sum(reference):04X}",
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
    kit.write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
