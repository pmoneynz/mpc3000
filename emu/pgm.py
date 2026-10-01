"""Native Vailixi 3.50 PGM fixtures and the MUTE GROUPS trailer.

The fixed 0x1200-byte grammar is established by C20F:0003 and the genuine
``emu/fixtures/mute-native-blank.PGM`` saved through the stock Disk UI.  This
module edits that native file; it does not synthesize unknown program-record
fields.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence
from pathlib import Path

NATIVE_BLANK_PATH = Path(__file__).with_name("fixtures") / "mute-native-blank.PGM"

PGM_BYTES = 0x1200
NAME_DIRECTORY = 0x0002
METADATA_DIRECTORY = 0x0882
PROGRAM_RECORD = 0x0A82
PROGRAM_RECORD_BYTES = 0x077E
NOTE_RECORDS = PROGRAM_RECORD + 0x003E
NOTE_RECORD_BYTES = 0x18
PAD_COUNT = 64

MUTE_MAGIC = b"MUTEGP35"
MUTE_HEADER = struct.Struct("<8sBBHHH")
MUTE_VERSION = 1
MUTE_STATE_BYTES = 33


def mute_state(enabled: bool = False, groups: Sequence[int] = (0,) * PAD_COUNT) -> bytes:
    """Pack one enabled flag and 64 group values (0..4) into 33 bytes."""
    if len(groups) != PAD_COUNT:
        raise ValueError("a mute state needs exactly 64 pad groups")
    if any(group not in range(5) for group in groups):
        raise ValueError("mute groups must be in 0..4")
    packed = bytearray([int(enabled)])
    packed.extend(groups[i] | groups[i + 1] << 4 for i in range(0, PAD_COUNT, 2))
    return bytes(packed)


def mute_trailer(states: Sequence[bytes], *, kind: int) -> bytes:
    """Build a PGM (kind 1) or APS (kind 2) trailer from packed states."""
    count = len(states)
    if kind == 1 and count != 1:
        raise ValueError("a PGM trailer contains exactly one state")
    if kind == 2 and count > 24:
        raise ValueError("an APS trailer contains at most 24 states")
    if kind not in (1, 2) or any(len(state) != MUTE_STATE_BYTES for state in states):
        raise ValueError("invalid mute trailer kind or state length")
    return (MUTE_HEADER.pack(MUTE_MAGIC, kind, MUTE_VERSION, MUTE_HEADER.size,
                             MUTE_STATE_BYTES, count) + b"".join(states))


def native_blank() -> bytes:
    """Return the checked-in stock Disk-UI save used as the fixture base."""
    return NATIVE_BLANK_PATH.read_bytes()


def with_mute_state(native_pgm: bytes | None = None, *, enabled: bool,
                    groups: Sequence[int]) -> bytes:
    """Replace any extension on a native PGM with one exact mute trailer."""
    native_pgm = native_blank() if native_pgm is None else native_pgm
    if len(native_pgm) < PGM_BYTES or native_pgm[:2] != b"\x07\x00":
        raise ValueError("not a native Vailixi 3.50 PGM")
    return native_pgm[:PGM_BYTES] + mute_trailer([mute_state(enabled, groups)], kind=1)


def for_sound(native_pgm: bytes, native_snd: bytes | None = None, *, pads: Iterable[int],
              enabled: bool = False, groups: Sequence[int] = (0,) * PAD_COUNT,
              program_name: str | None = None) -> bytes:
    """Bind selected pad slots to one native SND while preserving the template.

    The 17-byte sound name and sample-word metadata are the exact objects used
    by the stock PGM loader.  Each selected note record stores directory index
    zero; unselected assignments remain those of the native template.
    """
    # ``for_sound(snd, ...)`` uses the checked-in native base.  Keep the
    # two-positional form for callers that need to supply another proven PGM.
    if native_snd is None:
        native_snd, native_pgm = native_pgm, native_blank()
    if len(native_pgm) < PGM_BYTES or native_pgm[:2] != b"\x07\x00":
        raise ValueError("not a native Vailixi 3.50 PGM")
    if len(native_snd) < 2 + 0x24 or native_snd[:2] != b"\x01\x02":
        raise ValueError("not a native Vailixi 3.50 SND")
    image = bytearray(native_pgm[:PGM_BYTES])
    sound_name = native_snd[2:2 + 17]
    if not sound_name.split(b"\0", 1)[0]:
        raise ValueError("the SND has an empty name")
    image[NAME_DIRECTORY:NAME_DIRECTORY + 17] = sound_name
    frames = struct.unpack_from("<I", native_snd, 2 + 0x1C)[0]
    planes = native_snd[2 + 0x13] + 1
    struct.pack_into("<I", image, METADATA_DIRECTORY, frames * planes)
    for pad in pads:
        if pad not in range(PAD_COUNT):
            raise ValueError("pad slots must be in 0..63")
        image[NOTE_RECORDS + pad * NOTE_RECORD_BYTES] = 0
    if program_name is not None:
        encoded = program_name.encode("ascii")
        if not encoded or len(encoded) > 16 or b"\0" in encoded:
            raise ValueError("program name must be 1..16 non-NUL ASCII bytes")
        image[PROGRAM_RECORD:PROGRAM_RECORD + 17] = encoded.ljust(17, b"\0")
    return bytes(image) + mute_trailer([mute_state(enabled, groups)], kind=1)


def read_mute_trailer(data: bytes, offset: int = PGM_BYTES) -> list[dict]:
    """Decode and validate a trailer for test assertions."""
    if len(data) < offset + MUTE_HEADER.size:
        raise ValueError("missing mute trailer")
    magic, kind, version, header_len, state_len, count = MUTE_HEADER.unpack_from(data, offset)
    if (magic, version, header_len, state_len) != (
            MUTE_MAGIC, MUTE_VERSION, MUTE_HEADER.size, MUTE_STATE_BYTES):
        raise ValueError("invalid mute trailer header")
    if kind not in (1, 2) or kind == 1 and count != 1 or count > 24:
        raise ValueError("invalid mute trailer kind/count")
    payload = data[offset + header_len:offset + header_len + state_len * count]
    if len(payload) != state_len * count:
        raise ValueError("short mute trailer")
    result = []
    for base in range(0, len(payload), state_len):
        raw = payload[base:base + state_len]
        groups = [(raw[1 + pad // 2] >> (4 * (pad & 1))) & 15 for pad in range(PAD_COUNT)]
        if raw[0] > 1 or any(group > 4 for group in groups):
            raise ValueError("invalid mute state value")
        result.append({"enabled": raw[0], "groups": groups})
    return result
