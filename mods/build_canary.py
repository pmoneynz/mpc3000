"""Build the Vailixi 3.50 floppy canary.

Reads the Vailixi chip pair. Writes only build/mods/.

The ROM boot path (Vailixi 3.50 linear, same call shape on 3.11 and 3.12):

- The floppy scan passes argument 0. That selects the name ``????????????????``
  plus extension ``SYS`` (CEE6:0175 -> INT 41 AX=9). Eight ``?`` name bytes
  match any 8.3 name whose extension is SYS. SCSI partition startup passes
  argument 1, uses ``STARTUP ????????``, and does not call the MZ loader.
- Attribute bits 0x1E (hidden, system, volume, directory) are skipped.
- A hit calls FB93:0066, which is the same bytes as FB00:0996. That entry
  runs INT 10 (FAC0:01A4 loads the third PGR, pages 0-60 become RAM, pages
  62-63 stay BIOS ROM) and INT 45 (F800:0143).
- INT 45 requires an MZ image, loads it at segment 0x6900, applies
  relocations, and jumps to CS:IP. This canary has no relocations. Entry
  is 6900:0000.
- The entry prints the version string through INT 43 AX=4 with the
  character in BL, which is the same service the BIOS walker and
  B1B1:005B use. CR and LF are entries in that function's control table.

The one changed byte is linear file 0x21100, the ``0`` in ``Vailixi 3.50``.
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LS_PATH = REPO / "07-rom" / "Vailixi 3.50" / "3.50 Vailixi (LSE).BIN"
MS_PATH = REPO / "07-rom" / "Vailixi 3.50" / "3.50 Vailixi (MSO).BIN"
OUT_DIR = REPO / "build" / "mods"

CHIP_SIZE = 262144
STRING_FILE = 0x210F5
STRING_LEN = 26
PATCH_INDEX = 11  # '0' of "3.50"
PATCH_FROM = 0x30
PATCH_TO = 0x31

# BIOS geometry slot 2, F800:034F. Mount (F800:0F38) selects the slot by
# sectors/track only; the other fields are kept equal to the slot anyway.
# 1.44 MiB: 512-byte sectors, 1 sector/cluster, 1 reserved, 2 FATs,
# 224 root entries, 2880 sectors, media F0, 9 sectors/FAT, 18 sectors/track,
# 2 heads, 0 hidden.
BIOS_BPB = bytes(
    [
        0x00,
        0x02,
        0x01,
        0x01,
        0x00,
        0x02,
        0xE0,
        0x00,
        0x40,
        0x0B,
        0xF0,
        0x09,
        0x00,
        0x12,
        0x00,
        0x02,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
    ]
)

BPS = 512
SECTORS = 2880
RESERVED = 1
FAT_COUNT = 2
ROOT_ENTRIES = 224
SECTORS_PER_FAT = 9
ROOT_SECTORS = (ROOT_ENTRIES * 32) // BPS
DATA_START = RESERVED + FAT_COUNT * SECTORS_PER_FAT + ROOT_SECTORS
IMAGE_BYTES = 0x100


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def interleave(ls: bytes, ms: bytes) -> bytes:
    if len(ls) != CHIP_SIZE or len(ms) != CHIP_SIZE:
        raise ValueError(f"chip size {len(ls)}/{len(ms)}, expected {CHIP_SIZE}")
    out = bytearray(CHIP_SIZE * 2)
    out[0::2] = ls
    out[1::2] = ms
    return bytes(out)


def version_string(linear: bytes) -> bytes:
    raw = linear[STRING_FILE : STRING_FILE + STRING_LEN]
    if raw != b"Vailixi 3.50 (---/--/----)":
        raise ValueError(f"version string mismatch: {raw!r}")
    if linear[STRING_FILE + PATCH_INDEX] != PATCH_FROM:
        raise ValueError("patch byte is not 0x30")
    if linear.count(raw) != 1:
        raise ValueError("version string is not unique")
    return raw


def canary_text(original: bytes) -> bytes:
    patched = bytearray(original)
    patched[PATCH_INDEX] = PATCH_TO
    if patched.count(bytes([PATCH_TO])) != original.count(bytes([PATCH_TO])) + 1:
        raise ValueError("patch did not change exactly one byte")
    if bytes(patched) == original:
        raise ValueError("patch was a no-op")
    diffs = [i for i, (a, b) in enumerate(zip(original, patched)) if a != b]
    if diffs != [PATCH_INDEX]:
        raise ValueError(f"unexpected diffs {diffs}")
    return bytes(patched)


def stub(text: bytes) -> bytes:
    """CS-relative entry. String sits immediately after the halt."""
    # Layout is fixed so the short jumps below stay valid.
    # 0000 cli / cld / DS=CS / SS=CS / SP=0100 / sti
    # 000A SI = string
    # 000D load BL / test / jz halt / AX=4 / INT 43 / inc SI / jmp 000D
    # 001B jmp $
    # 001D string (CR LF + text + NUL)
    head = bytes(
        [
            0xFA,
            0xFC,
            0x0E,
            0x1F,
            0x0E,
            0x17,
            0xBC,
            0x00,
            0x01,
            0xFB,
            0xBE,
            0x1D,
            0x00,
            0x8A,
            0x1C,
            0x84,
            0xDB,
            0x74,
            0x08,
            0xB8,
            0x04,
            0x00,
            0xCD,
            0x43,
            0x46,
            0xEB,
            0xF2,
            0xEB,
            0xFE,
        ]
    )
    if len(head) != 0x1D:
        raise ValueError(f"stub head is {len(head)} bytes, expected 0x1D")
    body = head + b"\r\n" + text + b"\x00"
    if len(body) > 0x80:
        raise ValueError("stub collides with the stack at 0x100")
    image = body + bytes(IMAGE_BYTES - len(body))
    if image[0x0A : 0x0D] != b"\xbe\x1d\x00":
        raise ValueError("SI immediate does not point at the string")
    if image[0x1D : 0x1F] != b"\r\n":
        raise ValueError("CR LF missing")
    if image[0x1F : 0x1F + len(text)] != text:
        raise ValueError("canary text was not planted at 0x1F")
    return image


def pack_mz(image: bytes) -> bytes:
    """INT 45 header. Paragraph count 2. No relocations. CS:IP = 0:0.

    SS:SP = 0:0 makes FB93:0066 keep the stack it already switched to
    0040:69C4; the stub then replaces SS:SP with CS:0100.
    """
    header_paras = 2
    header = bytearray(header_paras * 16)
    file_size = len(header) + len(image)
    pages = (file_size + 511) // 512
    last = file_size % 512
    struct.pack_into(
        "<14H",
        header,
        0,
        0x5A4D,  # magic
        last,  # e_cblp
        pages,  # e_cp
        0,  # e_crlc
        header_paras,  # e_cparhdr
        0,  # e_minalloc
        0xFFFF,  # e_maxalloc
        0,  # e_ss
        0,  # e_sp
        0,  # e_csum
        0,  # e_ip
        0,  # e_cs
        0x1C,  # e_lfarlc
        0,  # e_ovno
    )
    blob = bytes(header) + image
    accept_mz(blob)
    return blob


def accept_mz(blob: bytes) -> None:
    """Replay the checks in F800:0143. Reject anything that returns AH!=0."""
    if len(blob) < 0x1C:
        raise ValueError("header shorter than 0x1C")
    if blob[0:2] != b"MZ":
        raise ValueError("magic")
    cblp, cp, crlc, cparhdr = struct.unpack_from("<4H", blob, 2)
    header = cparhdr * 16
    if header < 0x1C or header > len(blob):
        raise ValueError("paragraph count")
    if cblp == 0:
        file_size = cp * 512
    else:
        file_size = (cp - 1) * 512 + cblp
    if file_size != len(blob):
        raise ValueError(f"page size {file_size} != {len(blob)}")
    image_size = file_size - header
    if image_size != IMAGE_BYTES:
        raise ValueError("image size")
    if crlc != 0:
        raise ValueError("relocations")
    ss, sp = struct.unpack_from("<2H", blob, 0x0E)
    ip, cs = struct.unpack_from("<2H", blob, 0x14)
    if (cs, ip, ss, sp) != (0, 0, 0, 0):
        raise ValueError(f"entry/stack {cs:04X}:{ip:04X} {ss:04X}:{sp:04X}")


def fat12_set(fat: bytearray, cluster: int, value: int) -> None:
    offset = cluster + (cluster // 2)
    if cluster & 1:
        fat[offset] = (fat[offset] & 0x0F) | ((value & 0x0F) << 4)
        fat[offset + 1] = (value >> 4) & 0xFF
    else:
        fat[offset] = value & 0xFF
        fat[offset + 1] = (fat[offset + 1] & 0xF0) | ((value >> 8) & 0x0F)


def pack_floppy(payload: bytes) -> bytes:
    if len(BIOS_BPB) != 21:
        raise ValueError("BPB length")
    if struct.unpack_from("<H", BIOS_BPB, 0x0D)[0] != 18:
        raise ValueError("geometry slot is selected by sectors/track == 18")
    if DATA_START != 33:
        raise ValueError(f"data start {DATA_START}")
    if len(payload) > BPS:
        raise ValueError("payload exceeds one cluster; extend the FAT chain")

    disk = bytearray(SECTORS * BPS)
    disk[0:3] = b"\xeb\x3c\x90"
    disk[3:11] = b"MPC3KCAN"
    disk[11:32] = BIOS_BPB
    disk[0x26] = 0x29
    disk[0x27:0x2B] = b"\x50\x35\x43\x4E"  # volume id, not interpreted by the matcher
    disk[0x2B:0x36] = b"VAILIXI350 "  # 11-byte label; a short slice would shrink the image
    disk[0x36:0x3E] = b"FAT12   "
    disk[0x1FE:0x200] = b"\x55\xaa"
    if disk[11:32] != BIOS_BPB:
        raise ValueError("boot BPB drifted from the BIOS table")

    fat = bytearray(SECTORS_PER_FAT * BPS)
    fat[0:3] = b"\xf0\xff\xff"
    fat12_set(fat, 2, 0xFFF)
    for copy in range(FAT_COUNT):
        start = (RESERVED + copy * SECTORS_PER_FAT) * BPS
        disk[start : start + len(fat)] = fat

    ent = bytearray(32)
    ent[0:8] = b"STARTUP "
    ent[8:11] = b"SYS"
    ent[11] = 0x20
    struct.pack_into("<H", ent, 26, 2)
    struct.pack_into("<I", ent, 28, len(payload))
    root_off = (RESERVED + FAT_COUNT * SECTORS_PER_FAT) * BPS
    disk[root_off : root_off + 32] = ent

    data_off = DATA_START * BPS
    disk[data_off : data_off + len(payload)] = payload
    if len(disk) != SECTORS * BPS:
        raise ValueError(f"image shrank to {len(disk)}")
    return bytes(disk)


def directory_matches(image: bytes) -> None:
    """Replay F800:136C against the normalized pattern STARTUP.SYS."""
    root_off = (RESERVED + FAT_COUNT * SECTORS_PER_FAT) * BPS
    ent = image[root_off : root_off + 32]
    if ent[11] & 0x1E:
        raise ValueError("attribute would be skipped")
    pattern = b"STARTUP SYS"
    for i, expected in enumerate(pattern):
        if expected != 0x3F and ent[i] != expected:
            raise ValueError(f"dirent[{i}] {ent[i]:02X} != {expected:02X}")
    if ent[0:11] != b"STARTUP SYS":
        raise ValueError("8.3 name")


def main() -> int:
    linear = interleave(LS_PATH.read_bytes(), MS_PATH.read_bytes())
    rom_bpb = linear[0x7834F : 0x7834F + 21]
    if rom_bpb != BIOS_BPB:
        raise ValueError(f"BIOS geometry slot drifted: {rom_bpb.hex()}")
    original = version_string(linear)
    text = canary_text(original)
    image = stub(text)
    payload = pack_mz(image)
    floppy = pack_floppy(payload)
    directory_matches(floppy)

    if b"Vailixi 3.50" in payload:
        raise ValueError("unpatched version string leaked into the EXE")
    if b"Vailixi 3.51 (---/--/----)" not in payload:
        raise ValueError("canary string missing")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sys_path = OUT_DIR / "STARTUP.SYS"
    img_path = OUT_DIR / "vailixi350-canary.img"
    sys_path.write_bytes(payload)
    img_path.write_bytes(floppy)

    print(f"source string file 0x{STRING_FILE:05X} {original.decode()}")
    print(f"patched byte     file 0x{STRING_FILE + PATCH_INDEX:05X} 0x{PATCH_FROM:02X} -> 0x{PATCH_TO:02X}")
    print(f"canary string    {text.decode()}")
    print(f"STARTUP.SYS      {len(payload)} bytes  sha256 {sha256(payload)}")
    print(f"floppy image     {len(floppy)} bytes  sha256 {sha256(floppy)}")
    print(f"wrote            {sys_path}")
    print(f"wrote            {img_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
