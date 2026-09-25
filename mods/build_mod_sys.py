#!/usr/bin/env python3
"""Build a floppy mod: a patched Vailixi 3.50 OS that boots from `MOD350.SYS`.

    python3 mods/build_mod_sys.py [--patch FILE:OLDHEX:NEWHEX ...] [--cave SRC.asm] [--name NAME]
    python3 mods/build_mod_sys.py @mods/NAME.args

FILE is a linear-image offset in hex. OLDHEX must match the stock bytes.
An @file holds one argument per line (e.g. `--patch=21100:30:31`).
Only DGROUP [0x20000, 0x27C92) and OS code [0x30000, 0x74000) can be
patched: the BIOS pages stay EPROM after INT 10 (notes/floppy_loader.md §6).

--cave assembles SRC.asm (NASM, org 0) into the code cave at CAVE_SEG:0000
(file 0x707D0, the paragraph-aligned start of the FF run [0x707C8, 0x74000)).
In NEWHEX, `{label}` stands for the 4-byte far pointer label:CAVE_SEG, e.g.
`9a{entry}` is CALL FAR entry.

Always applied: the loader's floppy SYS branch (file 0x30207, JNZ -> JMP),
so the RAM copy does not load MOD350.SYS again. Default demo patch:
"Vailixi 3.50" -> "Vailixi 3.51" (file 0x21100).

Writes build/mods/<NAME>.SYS and build/mods/<NAME>.img (1.44 MB FAT12).
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "07-rom" / "Vailixi 3.50"
STUB_ASM = ROOT / "mods" / "mod_stub.asm"
OUT = ROOT / "build" / "mods"

DGROUP = (0x20000, 0x27C92)
CODE = (0x30000, 0x74000)
BIOS = (0x78000, 0x80000)
LOAD_SEGMENTS = (0x6900, 0x7000)        # 3.12/3.50 and 3.08/3.11 loaders
SKIP_SYS = (0x30207, "75", "eb")        # B000:0207 JNZ 0239 -> JMP 0239
DEMO = (0x21100, "30", "31")            # '0' of "Vailixi 3.50"
CAVE = (0x707D0, 0x74000)               # FF padding in the relocated code range
CAVE_SEG = (CAVE[0] + 0x80000) >> 4     # F07D: file = (CS<<4)+IP - 0x80000


def linear() -> bytes:
    ls = (ROM / "3.50 Vailixi (LSE).BIN").read_bytes()
    ms = (ROM / "3.50 Vailixi (MSO).BIN").read_bytes()
    out = bytearray(len(ls) * 2)
    out[0::2], out[1::2] = ls, ms
    return bytes(out)


def apply(img: bytearray, patches: list[tuple[int, str, str]]) -> None:
    for off, old, new in patches:
        old_b, new_b = bytes.fromhex(old), bytes.fromhex(new)
        end = off + len(old_b)
        if len(old_b) != len(new_b):
            raise ValueError(f"0x{off:05X}: old and new lengths differ")
        if not any(lo <= off and end <= hi for lo, hi in (DGROUP, CODE)):
            raise ValueError(f"0x{off:05X}: outside DGROUP and OS code; not reachable from RAM")
        if img[off:end] != old_b:
            raise ValueError(f"0x{off:05X}: expected {old}, found {img[off:end].hex()}")
        img[off:end] = new_b


def stub() -> bytes:
    out = OUT / "mod_stub.bin"
    subprocess.run(["nasm", "-f", "bin", "-o", str(out), str(STUB_ASM)], check=True)
    return out.read_bytes()


def cave(src: Path, img: bytes) -> tuple[tuple[int, str, str], dict[str, int]]:
    """Assemble src for CAVE_SEG:0000; return its FF->code patch and its labels."""
    OUT.mkdir(parents=True, exist_ok=True)
    out, map_ = OUT / f"{src.stem}.cave.bin", OUT / f"{src.stem}.cave.map"
    pre = OUT / "cave_map.inc"
    pre.write_text(f"[map symbols {map_}]\n")
    subprocess.run(["nasm", "-f", "bin", "-P", str(pre), "-o", str(out), str(src)], check=True)
    code = out.read_bytes()
    if len(code) > CAVE[1] - CAVE[0]:
        raise ValueError(f"{src}: {len(code)} bytes; the cave holds {CAVE[1] - CAVE[0]}")
    if re.search(rb"\x0f[\xe0\xf0]", code):
        raise ValueError(f"{src}: contains 0F E0 / 0F F0 (BRKXA/RETXA)")
    old = img[CAVE[0] : CAVE[0] + len(code)]
    if old != b"\xff" * len(code):
        raise ValueError("cave is not FF in the stock image")
    labels = {m[3]: int(m[1], 16) for m in re.finditer(r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)$",
                                                       map_.read_text(), re.M)}
    return (CAVE[0], old.hex(), code.hex()), labels


def far(new: str, labels: dict[str, int]) -> str:
    def ptr(m: re.Match) -> str:
        if m[1] not in labels:
            raise ValueError(f"{{{m[1]}}}: no such cave label")
        return struct.pack("<HH", labels[m[1]], CAVE_SEG).hex()
    return re.sub(r"\{(\w+)\}", ptr, new)


def para(n: int) -> int:
    return (n + 15) & ~15


def image(img: bytes) -> bytes:
    code = stub()
    fields = len(code) - 6                                  # bios_sum, code_para, dgroup_para
    dgroup_off = para(len(code))
    code_off = para(dgroup_off + DGROUP[1] - DGROUP[0])
    bios_sum = sum(struct.unpack_from(f"<{(BIOS[1] - BIOS[0]) // 2}H", img, BIOS[0])) & 0xFFFF
    for seg in LOAD_SEGMENTS:
        if 0xB0000 - (seg * 16 + code_off) < 0x4000:
            raise ValueError(f"load segment {seg:04X}: code chunks would overlap in one pass")
        if seg * 16 + dgroup_off + DGROUP[1] - DGROUP[0] > 0x80100:
            raise ValueError(f"load segment {seg:04X}: DGROUP source overlaps 8010:0000")
    body = bytearray(code_off + CODE[1] - CODE[0])
    body[: len(code)] = code
    struct.pack_into("<3H", body, fields, bios_sum, code_off >> 4, dgroup_off >> 4)
    body[dgroup_off : dgroup_off + DGROUP[1] - DGROUP[0]] = img[DGROUP[0] : DGROUP[1]]
    body[code_off:] = img[CODE[0] : CODE[1]]
    return bytes(body)


def mz(body: bytes) -> bytes:
    """INT 45 header: 2 paragraphs, no relocations, CS:IP 0:0, keep the loader's stack."""
    size = 32 + len(body)
    header = struct.pack("<14H", 0x5A4D, size % 512, (size + 511) // 512, 0, 2, 0, 0xFFFF,
                         0, 0, 0, 0, 0, 0x1C, 0)
    return header.ljust(32, b"\0") + body


def floppy(sys_path: Path, img_path: Path) -> None:
    img_path.unlink(missing_ok=True)
    subprocess.run(["mformat", "-C", "-f", "1440", "-i", str(img_path), "::"], check=True)
    subprocess.run(["mcopy", "-i", str(img_path), str(sys_path), f"::{sys_path.name}"], check=True)


def parse_patch(text: str) -> tuple[int, str, str]:
    off, old, new = text.split(":")
    return int(off, 16), old.lower(), new


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 fromfile_prefix_chars="@")
    ap.add_argument("--patch", action="append", type=parse_patch, default=[])
    ap.add_argument("--cave", type=Path)
    ap.add_argument("--name", default="MOD350")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Z0-9_]{1,8}", args.name):
        ap.error("--name must be 1-8 characters A-Z 0-9 _ (FAT 8.3 base name)")
    img = bytearray(linear())
    code, labels = cave(args.cave, img) if args.cave else (None, {})
    patches = [(off, old, far(new, labels).lower()) for off, old, new in args.patch]
    apply(img, [SKIP_SYS] + (patches or [DEMO]) + ([code] if code else []))
    OUT.mkdir(parents=True, exist_ok=True)
    sys_path, img_path = OUT / f"{args.name}.SYS", OUT / f"{args.name}.img"
    sys_path.write_bytes(mz(image(bytes(img))))
    floppy(sys_path, img_path)
    print(f"{sys_path}  {sys_path.stat().st_size} bytes\n{img_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
