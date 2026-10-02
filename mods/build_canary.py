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

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildkit as kit  # noqa: E402

REPO = kit.ROOT
LS_PATH = kit.LS350_PATH
MS_PATH = kit.MS350_PATH
OUT_DIR = REPO / "build" / "mods"

CHIP_SIZE = kit.CHIP_SIZE
STRING_FILE = 0x210F5
STRING_LEN = 26
PATCH_INDEX = 11  # '0' of "3.50"
PATCH_FROM = 0x30
PATCH_TO = 0x31

# FAT12 geometry: BIOS slot 2 at F800:034F (see buildkit.BIOS_BPB).
BIOS_BPB = kit.BIOS_BPB
BPS = kit.BPS
SECTORS = kit.SECTORS
RESERVED = kit.RESERVED
FAT_COUNT = kit.FAT_COUNT
ROOT_ENTRIES = kit.ROOT_ENTRIES
SECTORS_PER_FAT = kit.SECTORS_PER_FAT
ROOT_SECTORS = kit.ROOT_SECTORS
DATA_START = kit.DATA_START
IMAGE_BYTES = 0x100
VOLUME_ID = b"\x50\x35\x43\x4E"   # volume id, not interpreted by the matcher
VOLUME_LABEL = b"VAILIXI350 "      # 11-byte label

sha256 = kit.sha256
interleave = kit.interleave
fat12_set = kit.fat12_set


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
    blob = kit.pack_mz(image)
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


def pack_floppy(payload: bytes) -> bytes:
    if DATA_START != 33:
        raise ValueError(f"data start {DATA_START}")
    if len(payload) > BPS:
        raise ValueError("payload exceeds one cluster; extend the FAT chain")
    image, _ = kit.pack_fat12([("STARTUP.SYS", payload)], oem=b"MPC3KCAN",
                              volume_id=VOLUME_ID, label=VOLUME_LABEL)
    if image[11:32] != BIOS_BPB:
        raise ValueError("boot BPB drifted from the BIOS table")
    return image


def directory_matches(image: bytes) -> None:
    """Replay F800:136C against the normalized pattern STARTUP.SYS."""
    root_off = kit.ROOT_OFFSET
    ent = image[root_off : root_off + 32]
    if ent[11] & 0x1E:
        raise ValueError("attribute would be skipped")
    pattern = b"STARTUP SYS"
    for i, expected in enumerate(pattern):
        if expected != 0x3F and ent[i] != expected:
            raise ValueError(f"dirent[{i}] {ent[i]:02X} != {expected:02X}")
    if ent[0:11] != b"STARTUP SYS":
        raise ValueError("8.3 name")


def main(out: Path | None = None) -> int:
    out_dir = OUT_DIR if out is None else out
    linear = kit.vailixi350()
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

    sys_path = out_dir / "STARTUP.SYS"
    img_path = out_dir / "vailixi350-canary.img"
    kit.write_atomic(sys_path, payload)
    kit.write_atomic(img_path, floppy)

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
