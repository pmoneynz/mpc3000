#!/usr/bin/env python3
"""Build the physical application-ROM capture probe and preallocated image."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_canary as fat12  # noqa: E402,F401  (kept: tests and build/ scripts use fat12.interleave)
import buildkit as kit  # noqa: E402

ROOT = kit.ROOT
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

sha256 = kit.sha256
parse_map = kit.parse_map
clusters_needed = kit.clusters_needed
directory_entry = kit.directory_entry
extract_contiguous = kit.extract_contiguous


def checked_bios(path: Path = CAPTURED_BIOS) -> bytes:
    data = path.read_bytes()
    if len(data) != 0x8000:
        raise ValueError(f"captured BIOS is {len(data)} bytes, expected 32768")
    if sha256(data) != CAPTURED_BIOS_SHA256:
        raise ValueError("captured BIOS hash does not match the preserved hardware capture")
    return data


def pack_mz(body: bytes) -> bytes:
    payload = kit.pack_mz(body)
    validate_mz(payload)
    return payload


def validate_mz(payload: bytes) -> None:
    body_size = kit.validate_mz(payload)
    if body_size >= 0x10000:
        raise ValueError("loaded body does not fit one CS segment")
    if LOAD_BASE + body_size > SHARED_RAM_END:
        raise ValueError("loaded body crosses the first/third-PGR shared RAM boundary")


def assemble(expected_bios: Path, stem: str = "romapp",
             out: Path | None = None) -> tuple[bytes, dict[str, int]]:
    """Assemble with a data-only high-BIOS guard substitution.

    Non-default stems are for emulator fixtures.  They keep every generated
    file distinct from the physical candidate built by :func:`build`.
    """
    out = OUT if out is None else out
    asm = kit.assemble(ASM, defines={"EXPECTED_BIOS": kit.nasm_string(expected_bios)},
                       publish_bin=out / f"{stem}.bin", publish_map=out / f"{stem}.map")
    body, labels = asm.code, asm.labels
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


def build_test_fixture(expected_bios: Path, stem: str,
                       out: Path | None = None) -> tuple[Path, Path, dict[str, int]]:
    """Build an explicitly named emulator fixture without touching ROMAPP.*.

    The only substituted bytes are the embedded 32 KiB guard.  Tests compare
    assembled bodies outside that mapped object before accepting a fixture.
    """
    out = OUT if out is None else out
    if not stem or stem.casefold() == "romapp":
        raise ValueError("test fixture stem must be non-empty and distinct from ROMAPP")
    if Path(stem).name != stem:
        raise ValueError("test fixture stem must be a plain filename")
    body, labels = assemble(expected_bios, f"{stem}-asm", out)
    payload = pack_mz(body)
    image, _layout = pack_image(payload)
    sys_path = out / f"{stem}.SYS"
    img_path = out / f"{stem}.img"
    kit.write_atomic(sys_path, payload)
    kit.write_atomic(img_path, image)
    return sys_path, img_path, labels


def pack_image(payload: bytes, output: bytes = SENTINEL) -> tuple[bytes, dict[str, object]]:
    if len(output) != OUTPUT_SIZE:
        raise ValueError("ROMAPP.BIN must be exactly 0x54000 bytes")
    disk, (sys_file, out_file) = kit.pack_fat12(
        [("STARTUP.SYS", payload), (OUTPUT_NAME, output)],
        oem=b"MPC3KAPP", volume_id=b"RAPP", label=b"ROMAPP     ")
    layout: dict[str, object] = {
        "startup_clusters": [sys_file["first_cluster"], sys_file["last_cluster"]],
        "output_clusters": [out_file["first_cluster"], out_file["last_cluster"]],
        "output_cluster_count": out_file["clusters"],
        "output_data_offset": out_file["data_offset"],
        "root_directory_offset": kit.ROOT_OFFSET,
    }
    return disk, layout


def build(out: Path | None = None) -> dict[str, object]:
    out = OUT if out is None else out
    sys_path, img_path, manifest_path = out / SYS_PATH.name, out / IMG_PATH.name, out / MANIFEST_PATH.name
    bios = checked_bios()
    body, labels = assemble(CAPTURED_BIOS, out=out)
    start, end = labels["expected_bios"], labels["expected_bios_end"]
    if sha256(body[start:end]) != CAPTURED_BIOS_SHA256:
        raise ValueError("embedded guard bytes are not the hash-verified BIOS capture")
    payload = pack_mz(body)
    image, layout = pack_image(payload)
    kit.write_atomic(sys_path, payload)
    kit.write_atomic(img_path, image)

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
        "payload": {"path": kit.relpath(sys_path), "size": len(payload),
                    "sha256": sha256(payload), "load_base": "0x69000",
                    "body_end": f"0x{LOAD_BASE + len(body):05X}",
                    "shared_ram_end": f"0x{SHARED_RAM_END:05X}",
                    "inherited_ss_sp": "0040:69C4"},
        "image": {"path": kit.relpath(img_path), "size": len(image),
                  "sha256": sha256(image), "files": ["STARTUP.SYS", "ROMAPP.BIN"]},
        "romapp_bin_initial": {"size": OUTPUT_SIZE, "fill": "A5",
                               "sha256": sha256(SENTINEL)},
        "high_bios_guard": {"path": kit.relpath(CAPTURED_BIOS),
                            "size": len(bios), "sha256": sha256(bios),
                            "word_sum": f"{kit.word_sum(bios):04X}"},
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
            "total_sectors": OUTPUT_SIZE // kit.BPS,
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
    kit.write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
