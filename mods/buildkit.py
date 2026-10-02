"""Shared machinery for the floppy builders in mods/.

One copy of: ROM interleave with hash pins, the 16-bit word sum, the INT 45
MZ header, NASM invocation (private scratch directory, map, listing and
dependency parsing), and the deterministic 1.44 MB FAT12 packer.

Every NASM run happens in a fresh private directory. The map, listing and
dependency files parsed afterwards can only have been written by that run;
outputs are then published atomically under the caller's names.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROM350 = ROOT / "07-rom" / "Vailixi 3.50"
LS350_PATH = ROM350 / "3.50 Vailixi (LSE).BIN"
MS350_PATH = ROM350 / "3.50 Vailixi (MSO).BIN"
ROM312 = ROOT / "07-rom" / "v3.12"
LS312_PATH = ROM312 / "MPC312LS.BIN"
MS312_PATH = ROM312 / "MPC312MS.BIN"
CHIP_SIZE = 0x40000
# Linear (even=LSE, odd=MSO) Vailixi 3.50 image; AGENTS.md target.
VAILIXI350_SHA256 = "a52b7122bf40d020544300bb270afb815e99c1969847a28d457ce727bbe770c9"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def word_sum(data: bytes) -> int:
    """Sum of little-endian 16-bit words, modulo 0x10000."""
    if len(data) & 1:
        raise ValueError("word sum needs an even byte count")
    return sum(struct.unpack(f"<{len(data) // 2}H", data)) & 0xFFFF


def interleave(ls: bytes, ms: bytes) -> bytes:
    """Even bytes from the LS chip, odd bytes from the MS chip."""
    if len(ls) != CHIP_SIZE or len(ms) != CHIP_SIZE:
        raise ValueError(f"chip size {len(ls)}/{len(ms)}, expected {CHIP_SIZE}")
    out = bytearray(CHIP_SIZE * 2)
    out[0::2], out[1::2] = ls, ms
    return bytes(out)


def linear(ls_path: Path, ms_path: Path, digest: str | None = None) -> bytes:
    image = interleave(ls_path.read_bytes(), ms_path.read_bytes())
    if digest is not None and sha256(image) != digest:
        raise ValueError(f"{ls_path.name}/{ms_path.name}: interleaved image SHA-256 "
                         f"{sha256(image)} is not the pinned {digest}")
    return image


def vailixi350() -> bytes:
    """The hash-pinned Vailixi 3.50 linear image."""
    return linear(LS350_PATH, MS350_PATH, VAILIXI350_SHA256)


def relpath(path: Path) -> str:
    """Repository-relative text for manifests; absolute outside the repository."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


# --- INT 45 MZ header -------------------------------------------------------

def pack_mz(body: bytes) -> bytes:
    """2-paragraph header, no relocations, CS:IP 0:0, SS:SP 0:0 (keep the loader's stack)."""
    size = 32 + len(body)
    header = struct.pack("<14H", 0x5A4D, size % 512, (size + 511) // 512, 0, 2, 0, 0xFFFF,
                         0, 0, 0, 0, 0, 0x1C, 0)
    return header.ljust(32, b"\0") + body


def validate_mz(payload: bytes) -> int:
    """Replay the INT 45 header facts and the inherited-stack contract; return body size."""
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
    return len(payload) - header_paras * 16


# --- NASM -------------------------------------------------------------------

_MAP_LINE = re.compile(r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)\s*$", re.M)
_LST_LINE = re.compile(r"^\s*\d+\s+(?:<\d+>\s+)?([0-9A-F]{8})\s+((?:[0-9A-F]{2}|[\[(][0-9A-F]+[\])])+)(-?)(?:<rep ([0-9A-F]+)h>)?\s*(?:<\d+>\s*)?(.*)$")


def parse_map(text: str, column: str = "virtual") -> dict[str, int]:
    """Symbols of a NASM `[map symbols]` file; column is 'real' or 'virtual'."""
    index = {"real": 1, "virtual": 2}[column]
    return {m[3]: int(m[index], 16) for m in _MAP_LINE.finditer(text)}


@dataclass(frozen=True)
class ListingLine:
    offset: int        # output offset of the first byte
    data: bytes        # bytes emitted by this source line
    source: str        # source text (label, instruction, comment)


def parse_listing(text: str) -> list[ListingLine]:
    """Emitted-byte lines of a NASM listing, with continuation lines merged."""
    out: list[ListingLine] = []
    pending: tuple[int, bytearray, str] | None = None
    for line in text.splitlines():
        m = _LST_LINE.match(line)
        if not m:
            continue
        off, cont, source = int(m[1], 16), m[3], m[5]
        data = bytes.fromhex(re.sub(r"[\[\]()]", "", m[2])) * int(m[4] or "1", 16)
        if pending is not None and off == pending[0] + len(pending[1]) and not source:
            pending[1].extend(data)
        else:
            if pending is not None:
                out.append(ListingLine(pending[0], bytes(pending[1]), pending[2]))
            pending = (off, bytearray(data), source)
        if not cont:
            out.append(ListingLine(pending[0], bytes(pending[1]), pending[2]))
            pending = None
    if pending is not None:
        out.append(ListingLine(pending[0], bytes(pending[1]), pending[2]))
    return out


def parse_deps(text: str, cwd: Path) -> list[Path]:
    """Prerequisites of a make-style rule written by `nasm -M` / `-MD`."""
    body = text.replace("\\\n", " ")
    rule = body.split("\n\n")[0]
    if ":" not in rule:
        raise ValueError("NASM dependency output has no rule")
    words = re.findall(r"(?:\\.|[^\s\\])+", rule.split(" : ", 1)[1] if " : " in rule
                       else rule.split(":", 1)[1])
    return [(cwd / re.sub(r"\\(.)", r"\1", w)).resolve() for w in words]


def define_args(defines: Mapping[str, int | str | None] | None) -> list[str]:
    args: list[str] = []
    for name, value in (defines or {}).items():
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError(f"invalid NASM define name: {name!r}")
        args.append(f"-D{name}" if value is None else f"-D{name}={value}")
    return args


def nasm_string(path: Path) -> str:
    """A NASM string literal naming path (for incbin defines)."""
    text = str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


@dataclass
class Assembly:
    code: bytes
    labels: dict[str, int] = field(default_factory=dict)
    listing: list[ListingLine] = field(default_factory=list)
    deps: list[Path] = field(default_factory=list)


def _publish(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o644)                 # mkstemp creates 0600
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def assemble(src: Path, *, defines: Mapping[str, int | str | None] | None = None,
             include: Iterable[Path] = (), map_column: str = "virtual",
             symbols: bool = True, listing: bool = False, cwd: Path = ROOT,
             publish_bin: Path | None = None, publish_map: Path | None = None) -> Assembly:
    """Run NASM -f bin on src in a fresh private directory.

    Labels come only from the map this invocation wrote (the directory did
    not exist before it); a missing map is an error, never a fallback.
    """
    src = src.resolve()
    with tempfile.TemporaryDirectory(prefix="nasm-") as scratch:
        tmp = Path(scratch).resolve()
        out, map_, lst, dep = tmp / "out.bin", tmp / "out.map", tmp / "out.lst", tmp / "out.d"
        cmd = ["nasm", "-f", "bin", *[f"-I{Path(d).resolve()}/" for d in include],
               *define_args(defines)]
        if symbols:
            pre = tmp / "map.inc"
            pre.write_text(f"[map symbols {map_}]\n")
            cmd += ["-P", str(pre)]
        if listing:
            cmd += ["-l", str(lst)]
        cmd += ["-MD", str(dep), "-MT", "out", "-o", str(out), str(src)]
        subprocess.run(cmd, cwd=cwd, check=True)
        result = Assembly(out.read_bytes())
        if symbols:
            if not map_.is_file():
                raise RuntimeError(f"{src}: NASM wrote no symbol map for this run")
            result.labels = parse_map(map_.read_text(), map_column)
        if listing:
            if not lst.is_file():
                raise RuntimeError(f"{src}: NASM wrote no listing for this run")
            result.listing = parse_listing(lst.read_text())
        if not dep.is_file():
            raise RuntimeError(f"{src}: NASM wrote no dependency list for this run")
        result.deps = [p for p in parse_deps(dep.read_text(), cwd) if tmp not in p.parents]
        if publish_bin is not None:
            _publish(out, publish_bin)
        if publish_map is not None and symbols:
            _publish(map_, publish_map)
    return result


def nasm_deps(src: Path, *, defines: Mapping[str, int | str | None] | None = None,
              include: Iterable[Path] = (), cwd: Path = ROOT) -> list[Path]:
    """Every file NASM reads for src with these defines (`nasm -M`)."""
    cmd = ["nasm", "-M", "-MT", "out", *[f"-I{Path(d).resolve()}/" for d in include],
           *define_args(defines), str(src.resolve())]
    text = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout
    return parse_deps(text, cwd)


# --- deterministic 1.44 MB FAT12 --------------------------------------------

# BIOS geometry slot 2, F800:034F. Mount (F800:0F38) selects the slot by
# sectors/track only; the other fields are kept equal to the slot anyway.
# 512-byte sectors, 1 sector/cluster, 1 reserved, 2 FATs, 224 root entries,
# 2880 sectors, media F0, 9 sectors/FAT, 18 sectors/track, 2 heads, 0 hidden.
BIOS_BPB = bytes([0x00, 0x02, 0x01, 0x01, 0x00, 0x02, 0xE0, 0x00, 0x40, 0x0B, 0xF0,
                  0x09, 0x00, 0x12, 0x00, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00])
BPS = 512
SECTORS = 2880
RESERVED = 1
FAT_COUNT = 2
ROOT_ENTRIES = 224
SECTORS_PER_FAT = 9
ROOT_SECTORS = (ROOT_ENTRIES * 32) // BPS
ROOT_OFFSET = (RESERVED + FAT_COUNT * SECTORS_PER_FAT) * BPS
DATA_START = RESERVED + FAT_COUNT * SECTORS_PER_FAT + ROOT_SECTORS


def fat12_set(fat: bytearray, cluster: int, value: int) -> None:
    offset = cluster + (cluster // 2)
    if cluster & 1:
        fat[offset] = (fat[offset] & 0x0F) | ((value & 0x0F) << 4)
        fat[offset + 1] = (value >> 4) & 0xFF
    else:
        fat[offset] = value & 0xFF
        fat[offset + 1] = (fat[offset + 1] & 0xF0) | ((value >> 8) & 0x0F)


def fat_name(name: str | bytes) -> bytes:
    """`NAME.EXT` (or an 11-byte directory name) as the 11 directory bytes."""
    if isinstance(name, bytes):
        if len(name) != 11:
            raise ValueError("FAT name must be exactly 11 bytes")
        return name
    base, _, ext = name.upper().partition(".")
    if not re.fullmatch(r"[A-Z0-9_$~!#%&@^'()\-{}]{1,8}", base) or \
            not re.fullmatch(r"[A-Z0-9_$~!#%&@^'()\-{}]{0,3}", ext):
        raise ValueError(f"{name!r} is not an 8.3 name")
    return base.ljust(8).encode() + ext.ljust(3).encode()


def directory_entry(name: str | bytes, first_cluster: int, size: int) -> bytes:
    entry = bytearray(32)
    entry[:11] = fat_name(name)
    entry[11] = 0x20
    # +0C..+13 stay NUL: 3.50 reads MPC filename characters 9-16 there.
    # Times and dates stay zero too, so the image is a function of its inputs.
    struct.pack_into("<H", entry, 26, first_cluster)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def clusters_needed(size: int) -> int:
    return (size + BPS - 1) // BPS


def pack_fat12(files: list[tuple[str | bytes, bytes]], *, oem: bytes,
               volume_id: bytes, label: bytes) -> tuple[bytes, list[dict[str, int]]]:
    """1.44 MB image; files are contiguous from cluster 2, in list order.

    Returns the image and, per file, its first/last cluster and data offset.
    """
    if len(BIOS_BPB) != 21 or struct.unpack_from("<H", BIOS_BPB, 0x0D)[0] != 18:
        raise ValueError("geometry slot is selected by sectors/track == 18")
    if len(oem) != 8 or len(volume_id) != 4 or len(label) != 11:
        raise ValueError("OEM, volume id and label must be 8, 4 and 11 bytes")
    if len(files) > ROOT_ENTRIES:
        raise ValueError("too many root entries")
    names = [fat_name(name) for name, _ in files]
    if len(set(names)) != len(names):
        raise ValueError("duplicate disk filename")
    disk = bytearray(SECTORS * BPS)
    disk[0:3] = b"\xeb\x3c\x90"
    disk[3:11] = oem
    disk[11:32] = BIOS_BPB
    disk[0x26] = 0x29
    disk[0x27:0x2B] = volume_id
    disk[0x2B:0x36] = label
    disk[0x36:0x3E] = b"FAT12   "
    disk[0x1FE:0x200] = b"\x55\xaa"

    fat = bytearray(SECTORS_PER_FAT * BPS)
    fat[0:3] = b"\xf0\xff\xff"
    layout: list[dict[str, int]] = []
    cluster = 2
    for index, (name, data) in enumerate(zip(names, (d for _, d in files))):
        count = clusters_needed(len(data))
        first = cluster if count else 0
        if count and cluster + count - 1 - 1 > SECTORS - DATA_START:
            raise ValueError("files do not fit FAT12 data area")
        for c in range(cluster, cluster + count):
            fat12_set(fat, c, 0xFFF if c == cluster + count - 1 else c + 1)
        offset = (DATA_START + cluster - 2) * BPS
        disk[offset:offset + len(data)] = data
        root = ROOT_OFFSET + index * 32
        disk[root:root + 32] = directory_entry(name, first, len(data))
        layout.append({"first_cluster": first, "last_cluster": cluster + count - 1,
                       "clusters": count, "data_offset": offset, "root_entry": root})
        cluster += count
    for copy in range(FAT_COUNT):
        start = (RESERVED + copy * SECTORS_PER_FAT) * BPS
        disk[start:start + len(fat)] = fat
    if len(disk) != SECTORS * BPS:
        raise ValueError("disk image size changed")
    return bytes(disk), layout


def extract_contiguous(image: bytes, first_cluster: int, size: int) -> bytes:
    offset = (DATA_START + first_cluster - 2) * BPS
    return image[offset:offset + size]


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)                 # mkstemp creates 0600
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
