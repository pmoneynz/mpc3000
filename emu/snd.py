"""Synthetic Vailixi 3.50 .SND files and floppy images for waveform tests.

Format (loader D7FA:000E / D7FA:03A5, saver E905:0049; notes/waveform_phase0.md §3):
`01 02`, the 36-byte sound record (+00 name, +11 vol, +12 tune, +13 stereo,
+14 start, +18 end, +1C length in frames, +20 wave address, ignored on load),
then signed 16-bit LE samples: length words, or plane A then plane B for stereo.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from emu.mpc3k import disk as fat_disk

SR = 44100


def snd(name: str, planes: list[list[int]], vol: int = 100, start: int = 0, end: int | None = None) -> bytes:
    length = len(planes[0])
    record = (name.encode()[:16].ljust(17, b"\0") + struct.pack("<BbB", vol, 0, len(planes) - 1)
              + struct.pack("<4I", start, length if end is None else end, length, 0))
    return b"\x01\x02" + record + b"".join(struct.pack(f"<{length}h", *p) for p in planes)


def sine(n: int) -> list[int]:
    return [round(30000 * math.sin(2 * math.pi * 441 * i / SR)) for i in range(n)]   # period 100


def ramp(n: int, a: int, b: int) -> list[int]:
    return [round(a + (b - a) * i / (n - 1)) for i in range(n)]


def sine441() -> list[list[int]]:
    """0.5 s sine, 0.5 s silence, 0.25 s ramp -30000..+30000 (55,125 frames)."""
    return [sine(SR // 2) + [0] * (SR // 2) + ramp(SR // 4, -30000, 30000)]


def stereo1() -> list[list[int]]:
    """A: 0.25 s sine then silence. B: 0.25 s silence then ramp +30000..-30000 (33,075 frames)."""
    q = SR // 4
    return [sine(q) + [0] * (2 * q), [0] * q + ramp(2 * q, 30000, -30000)]


def from_wav(path: Path) -> list[list[int]]:
    """Planes of a 16-bit 44.1 kHz mono or stereo WAV (no conversion)."""
    with wave.open(str(path)) as w:
        if (w.getsampwidth(), w.getframerate()) != (2, SR) or w.getnchannels() not in (1, 2):
            raise ValueError(f"{path}: need 16-bit 44.1 kHz mono or stereo")
        ch, frames = w.getnchannels(), w.readframes(w.getnframes())
    words = struct.unpack(f"<{len(frames) // 2}h", frames)
    return [list(words[c::ch]) for c in range(ch)]


def disk(name: str, files: list[tuple[Path, str]]) -> Path:
    """FAT12 image whose directory entries have +0C..+13 NUL.

    3.50 reads name characters 9-16 from there; the mtools timestamps made
    the load fail with FD00 'requested file was not found' (trace)."""
    img = fat_disk(name, files)
    b = bytearray(img.read_bytes())
    for e in range(0x2600, 0x2600 + 224 * 32, 32):
        if b[e] not in (0, 0xE5):
            b[e + 0x0C:e + 0x14] = bytes(8)
    img.write_bytes(bytes(b))
    return img
