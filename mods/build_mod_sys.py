#!/usr/bin/env python3
"""Build a floppy mod: a patched Vailixi 3.50 OS that boots from `MOD350.SYS`.

    python3 mods/build_mod_sys.py [--patch FILE:OLDHEX:NEWHEX ...] [--cave SRC.asm] [--name NAME]
    python3 mods/build_mod_sys.py @mods/NAME.args [--out DIR]

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

Writes build/mods/<NAME>.SYS and build/mods/<NAME>.img (1.44 MB FAT12,
deterministic: buildkit.pack_fat12). --out writes them elsewhere.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildkit as kit  # noqa: E402

ROOT = kit.ROOT
ROM = kit.ROM350
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
# Reset DGROUP layout immediates in the BIOS the stub guards (XA=1, third PGR):
DGROUP_COPY_COUNT = 0x7AC84             # FAC0:0084 B9 iw  MOV CX,<DGROUP bytes>; REP MOVSW from A000:0
BSS_START = 0x7AD3D                     # FAC0:013D BF iw  MOV DI,<BSS start> after rejoin FAC0:0134


def linear() -> bytes:
    """Interleaved Vailixi 3.50 image, SHA-256 pinned (buildkit.VAILIXI350_SHA256)."""
    return kit.vailixi350()


def apply(img: bytearray, patches: list[tuple[int, str, str]], *,
          dgroup: tuple[int, int] = DGROUP) -> None:
    """Apply FILE:OLD:NEW patches; every byte must lie in the shipped DGROUP or OS code."""
    for off, old, new in patches:
        old_b, new_b = bytes.fromhex(old), bytes.fromhex(new)
        end = off + len(old_b)
        if len(old_b) != len(new_b):
            raise ValueError(f"0x{off:05X}: old and new lengths differ")
        if not old_b:
            raise ValueError(f"0x{off:05X}: empty patch")
        if not any(lo <= off and end <= hi for lo, hi in (dgroup, CODE)):
            raise ValueError(f"0x{off:05X}-0x{end:05X}: outside shipped DGROUP "
                             f"[0x{dgroup[0]:05X},0x{dgroup[1]:05X}) and OS code; not reachable from RAM")
        if img[off:end] != old_b:
            raise ValueError(f"0x{off:05X}: expected {old}, found {img[off:end].hex()}")
        img[off:end] = new_b


def _stem(value: str) -> str:
    if not value or Path(value).name != value:
        raise ValueError("output stem must be a plain filename")
    return value


_define_args = kit.define_args


def stub(*, dgroup_bytes: int = 0x7C92, exact_bios_path: Path | None = None,
         stem: str = "mod_stub", exact_bios_sha256: str | None = None,
         out: Path | None = None) -> bytes:
    if dgroup_bytes <= 0 or dgroup_bytes > 0xFFFF or dgroup_bytes & 1:
        raise ValueError("DGROUP byte count must be a positive even 16-bit value")
    stem = _stem(stem)
    out = OUT if out is None else out
    defines: dict[str, int | str] = {"DGROUP_BYTES": dgroup_bytes}
    expected = None
    if exact_bios_path is not None:
        exact_bios_path = exact_bios_path.resolve()
        expected = exact_bios_path.read_bytes()
        if len(expected) != BIOS[1] - BIOS[0]:
            raise ValueError("exact BIOS guard must be exactly 32 KiB")
        if exact_bios_sha256 is not None and kit.sha256(expected) != exact_bios_sha256:
            raise ValueError(f"{exact_bios_path}: not the hash-pinned BIOS capture")
        defines["EXACT_BIOS_PATH"] = kit.nasm_string(exact_bios_path)
    asm = kit.assemble(STUB_ASM, defines=defines, publish_bin=out / f"{stem}.bin")
    if expected is not None:
        start = asm.labels.get("expected_bios")
        if start is None:
            raise ValueError("exact-guard stub has no expected_bios label")
        embedded = asm.code[start:start + len(expected)]
        if embedded != expected or (exact_bios_sha256 is not None
                                    and kit.sha256(embedded) != exact_bios_sha256):
            raise ValueError("embedded guard bytes are not the hash-verified BIOS capture")
    return asm.code


@dataclass(frozen=True)
class FarTransfer:
    """A direct CALL FAR (9A) or JMP FAR (EA) instruction in an assembled cave."""
    cave_offset: int
    opcode: int
    segment: int
    offset: int
    source: str

    @property
    def target(self) -> str:
        return f"{self.segment:04X}:{self.offset:04X}"

    @property
    def linear(self) -> int:
        return (self.segment << 4) + self.offset - 0x80000


@dataclass
class Cave:
    patch: tuple[int, str, str]
    labels: dict[str, int]
    code: bytes
    listing: list[kit.ListingLine] = field(default_factory=list)
    deps: list[Path] = field(default_factory=list)

    def label_at(self, offset: int) -> str:
        """Nearest cave label at or before offset (for messages)."""
        best = max(((v, k) for k, v in self.labels.items() if v <= offset), default=(0, "?"))
        return f"{best[1]}+0x{offset - best[0]:X}"


_PREFIXES = {0x26, 0x2E, 0x36, 0x3E}
_TRANSFER = re.compile(r"^(?:[.\w$@?]+:\s*)?(call|jmp)\b", re.I)


def far_transfers(cave: Cave) -> list[FarTransfer]:
    """Direct far transfers at NASM-listed instruction boundaries.

    The listing must account for every cave byte exactly once; an indirect
    far CALL/JMP (FF /3, FF /5) has no static target and is rejected.
    """
    covered = bytearray(len(cave.code))
    found: list[FarTransfer] = []
    for line in cave.listing:
        if cave.code[line.offset:line.offset + len(line.data)] != line.data:
            raise ValueError(f"cave+0x{line.offset:X}: listing bytes differ from the binary")
        for i in range(line.offset, line.offset + len(line.data)):
            covered[i] += 1
        if not _TRANSFER.match(line.source):
            continue
        data = line.data
        while data and data[0] in _PREFIXES:
            data = data[1:]
        if len(data) == 5 and data[0] in (0x9A, 0xEA):
            off, seg = struct.unpack_from("<HH", data, 1)
            found.append(FarTransfer(line.offset, data[0], seg, off, line.source.strip()))
        elif len(data) >= 2 and data[0] == 0xFF and (data[1] >> 3) & 7 in (3, 5):
            raise ValueError(f"cave+0x{line.offset:X} ({cave.label_at(line.offset)}): indirect far "
                             f"transfer {line.source.strip()!r} has no checkable target")
    if any(c != 1 for c in covered):
        raise ValueError("NASM listing does not account for every cave byte exactly once")
    return found


def assemble_cave(src: Path, img: bytes, *, defines: Mapping[str, int | str | None] | None = None,
                  stem: str | None = None, out: Path | None = None,
                  publish: bool = True) -> Cave:
    """Assemble src for CAVE_SEG:0000 in a private NASM directory.

    Labels come only from the map written by this NASM run. With publish,
    the binary and map are then copied to <out>/<stem>.cave.{bin,map}.
    """
    out = OUT if out is None else out
    output_stem = _stem(stem or src.stem)
    asm = kit.assemble(src, defines=defines, include=[src.resolve().parent], map_column="real",
                       listing=True,
                       publish_bin=out / f"{output_stem}.cave.bin" if publish else None,
                       publish_map=out / f"{output_stem}.cave.map" if publish else None)
    code = asm.code
    if len(code) > CAVE[1] - CAVE[0]:
        raise ValueError(f"{src}: {len(code)} bytes; the cave holds {CAVE[1] - CAVE[0]}")
    if re.search(rb"\x0f[\xe0\xf0]", code):
        raise ValueError(f"{src}: contains 0F E0 / 0F F0 (BRKXA/RETXA)")
    old = img[CAVE[0] : CAVE[0] + len(code)]
    if old != b"\xff" * len(code):
        raise ValueError("cave is not FF in the stock image")
    return Cave((CAVE[0], old.hex(), code.hex()), asm.labels, code, asm.listing, asm.deps)


def cave(src: Path, img: bytes, *, defines: Mapping[str, int | str | None] | None = None,
         stem: str | None = None, out: Path | None = None) -> tuple[tuple[int, str, str], dict[str, int]]:
    """Assemble src for CAVE_SEG:0000; return its FF->code patch and its labels."""
    built = assemble_cave(src, img, defines=defines, stem=stem, out=out)
    return built.patch, built.labels


def far(new: str, labels: dict[str, int]) -> str:
    def ptr(m: re.Match) -> str:
        if m[1] not in labels:
            raise ValueError(f"{{{m[1]}}}: no such cave label")
        return struct.pack("<HH", labels[m[1]], CAVE_SEG).hex()
    return re.sub(r"\{(\w+)\}", ptr, new)


def para(n: int) -> int:
    return (n + 15) & ~15


def guard_layout(bios: bytes, dgroup_bytes: int) -> None:
    """The guarded BIOS must copy exactly dgroup_bytes and start BSS there."""
    for linear_off, opcode, what in ((DGROUP_COPY_COUNT, 0xB9, "FAC0:0084 MOV CX (DGROUP copy count)"),
                                     (BSS_START, 0xBF, "FAC0:013D MOV DI (BSS start)")):
        at = linear_off - BIOS[0]
        if bios[at] != opcode:
            raise ValueError(f"linear 0x{linear_off:05X}: {what} opcode {bios[at]:02X}, expected {opcode:02X}")
        value = struct.unpack_from("<H", bios, at + 1)[0]
        if value != dgroup_bytes:
            raise ValueError(f"linear 0x{linear_off + 1:05X}: {what} is {value:04X}; "
                             f"the image ships {dgroup_bytes:04X} DGROUP bytes")


def image(img: bytes, *, dgroup: tuple[int, int] = DGROUP,
          exact_bios_path: Path | None = None, stem: str = "mod_stub",
          exact_bios_sha256: str | None = None, out: Path | None = None) -> bytes:
    dgroup_bytes = dgroup[1] - dgroup[0]
    if not (0 <= dgroup[0] < dgroup[1] <= len(img)):
        raise ValueError("DGROUP bounds are outside the source image")
    if CODE[1] > len(img) or BIOS[1] > len(img):
        raise ValueError("OS code or BIOS bounds are outside the source image")
    bios = img[BIOS[0]:BIOS[1]]
    if exact_bios_path is not None and exact_bios_path.read_bytes() != bios:
        raise ValueError("exact BIOS guard differs from the source image's BIOS range")
    guard_layout(bios, dgroup_bytes)
    code = stub(dgroup_bytes=dgroup_bytes, exact_bios_path=exact_bios_path, stem=stem,
                exact_bios_sha256=exact_bios_sha256, out=out)
    fields = len(code) - 6                                  # bios_sum, code_para, dgroup_para
    dgroup_off = para(len(code))
    code_off = para(dgroup_off + dgroup_bytes)
    bios_sum = 0 if exact_bios_path is not None else kit.word_sum(bios)
    for seg in LOAD_SEGMENTS:
        if 0xB0000 - (seg * 16 + code_off) < 0x4000:
            raise ValueError(f"load segment {seg:04X}: code chunks would overlap in one pass")
        if seg * 16 + dgroup_off + dgroup_bytes > 0x80100:
            raise ValueError(f"load segment {seg:04X}: DGROUP source overlaps 8010:0000")
    body = bytearray(code_off + CODE[1] - CODE[0])
    body[: len(code)] = code
    struct.pack_into("<3H", body, fields, bios_sum, code_off >> 4, dgroup_off >> 4)
    body[dgroup_off : dgroup_off + dgroup_bytes] = img[dgroup[0] : dgroup[1]]
    body[code_off:] = img[CODE[0] : CODE[1]]
    return bytes(body)


def mz(body: bytes) -> bytes:
    """INT 45 header: 2 paragraphs, no relocations, CS:IP 0:0, keep the loader's stack."""
    payload = kit.pack_mz(body)
    kit.validate_mz(payload)
    return payload


def floppy(sys_path: Path, img_path: Path) -> None:
    """Deterministic 1.44 MB FAT12 holding sys_path under its own name."""
    data, _ = kit.pack_fat12([(sys_path.name, sys_path.read_bytes())], oem=b"MPC3KMOD",
                             volume_id=b"RAMO", label=sys_path.stem.upper()[:11].ljust(11).encode())
    kit.write_atomic(img_path, data)


def parse_patch(text: str) -> tuple[int, str, str]:
    off, old, new = text.split(":")
    return int(off, 16), old.lower(), new


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 fromfile_prefix_chars="@")
    ap.add_argument("--patch", action="append", type=parse_patch, default=[])
    ap.add_argument("--cave", type=Path)
    ap.add_argument("--name", default="MOD350")
    ap.add_argument("--out", type=Path, default=OUT, help="output directory (default build/mods)")
    return ap


def read_args(path: Path) -> argparse.Namespace:
    """Parse a mods/*.args file; a relative --cave is resolved against the repository."""
    args = parser().parse_args([f"@{path.resolve()}"])
    if args.cave is not None and not args.cave.is_absolute():
        args.cave = ROOT / args.cave
    return args


def build(patches: list[tuple[int, str, str]], cave_src: Path | None = None,
          name: str = "MOD350", out: Path = OUT) -> tuple[Path, Path]:
    if not re.fullmatch(r"[A-Z0-9_]{1,8}", name):
        raise ValueError("--name must be 1-8 characters A-Z 0-9 _ (FAT 8.3 base name)")
    img = bytearray(linear())
    code, labels = cave(cave_src, img, out=out) if cave_src else (None, {})
    resolved = [(off, old, far(new, labels).lower()) for off, old, new in patches]
    apply(img, [SKIP_SYS] + (resolved or [DEMO]) + ([code] if code else []))
    sys_path, img_path = out / f"{name}.SYS", out / f"{name}.img"
    kit.write_atomic(sys_path, mz(image(bytes(img), out=out)))
    floppy(sys_path, img_path)
    return sys_path, img_path


def main(argv: list[str] | None = None) -> int:
    ap = parser()
    args = ap.parse_args(argv)
    try:
        sys_path, img_path = build(args.patch, args.cave, args.name, args.out)
    except ValueError as exc:
        if "--name" in str(exc):
            ap.error(str(exc))
        raise
    print(f"{sys_path}  {sys_path.stat().st_size} bytes\n{img_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
