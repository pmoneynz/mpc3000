"""Convert MPC3000 .SND sounds to Akai S1000/S3000 samples on an Akai floppy image.

    python3 tools/snd2akai.py KICK.SND SNARE.SND -o build/akai/DRUMS.img
    python3 tools/snd2akai.py *.SND -o build/akai/DRUMS.hfe --label DRUMS
    python3 tools/snd2akai.py --list build/akai/DRUMS.img
    python3 tools/snd2akai.py --extract build/akai/DRUMS.img -o build/akai/snd/

The MPC3000 reads the result with Disk -> 8 "Load S1000/S3000 Sample Files";
S1000, S1100, S3000, S3200 and CD3000 samplers read it as an Akai disk.
`.img` is the raw 1.6 MB (HD) or 800 KB (DD) image, for FlashFloppy/Gotek with
`host = akai` (a PC floppy drive cannot write its 1024-byte sectors); `.hfe` is
the same disk as an HxC flux image (FlashFloppy, HxC, MAME).

Default: an S1000 floppy holding S1000 samples (150-byte header). Vailixi 3.50
reads floppy samples with a fixed 0x96-byte header whatever the file type
(`BE7E:03CA`, `BE7E:045A`; notes/akai_disk.md), so this is the layout every
reader loads exactly. `--s3000` writes a native S3000 floppy (S3000 flag,
192-byte headers); 3.50 loads those with 21 leading zero words and the last
21 frames missing, and cannot find the directory of a DD S3000 floppy.

SND (notes/waveform_phase0.md section 3): `01 02`, the 36-byte sound record
(+00 name, 16 characters space padded; +12 tune; +13 stereo; +14 soft start;
+18 soft end; +1C length in frames), then signed 16-bit LE samples, plane A
then plane B for stereo.

Akai floppy (akaiutil 4.6.8 `akaiutil.h`; the 3.50 loader in
notes/akai_disk.md): 1 KiB blocks = 1 KiB sectors, 10 (HD) or 5 (DD) per
track, 80 cylinders, 2 heads; block b is cylinder b // (2*spt), head
(b // spt) & 1, sector b % spt + 1. The header (5 HD / 4 DD blocks) holds 64
directory entries of 24 bytes, one 16-bit FAT word per block at 0x600, then
the volume label. FAT: 0x4000 system, 0xC000 end of file, else next block.
A stereo SND becomes NAME-L and NAME-R of equal size, the pair both the
samplers and the MPC3000 join back into one stereo sound.
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

SR = 44100
BLOCK = 1024
CYLINDERS = 80
HEADS = 2

FAT_OFFSET = 0x600
FAT_FREE = 0x0000
FAT_SYS = 0x4000
FAT_END = 0xC000

ENTRIES = 64           # 3.50 scans 64 entries on floppy, also on S3000 floppies
S3000_DIR_BLOCKS = 12  # S3000 floppy: 510-entry directory after the header
S3000_FLAG = 0xFF      # header entry 0 type on an S3000 floppy

S1000_OSVER = 0x0428   # "4.40"
S3000_OSVER = 0x1100   # "17.00"

TYPE_S1000_SAMPLE = 0x73   # 's'
TYPE_S3000_SAMPLE = 0xF3   # 's' | 0x80

S1000_HEADER = 0x96
S3000_HEADER = 0xC0
NAME_LEN = 12
EMPTY_NAME = "VVVVVVVVVVVV"   # akaiutil AKAI_EMPTY1000_FNAME
S1000_TAG = 0x20

PMODE_NOLOOP = 2
STPAIR_NONE = 0xFFFF
TUNE_LIMIT = 120       # 3.50 clamps the converted tune to +-120 (BE7E:0B17)


@dataclass(frozen=True)
class Density:
    name: str
    spt: int             # 1 KiB sectors per track
    header_blocks: int
    hfe_rate: int        # HFE kbit/s: one HFE bit per MFM cell
    sector_offset: int   # akaiutil_io.h physical interleave
    track_skew: int

    @property
    def blocks(self) -> int:
        return CYLINDERS * HEADS * self.spt

    @property
    def size(self) -> int:
        return self.blocks * BLOCK

    @property
    def label_offset(self) -> int:
        return FAT_OFFSET + 2 * self.blocks


HD = Density("hd", 10, 5, 500, 6, 4)
DD = Density("dd", 5, 4, 250, 3, 2)
DENSITIES = {d.name: d for d in (HD, DD)}


class ConvertError(ValueError):
    pass


# --- names ---------------------------------------------------------------

AKAI_CHARS = "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-."   # 3.50 table DS:3F1A, '_' shown for space


def clean_name(text: str) -> str:
    """The name in Akai characters: upper case, '_' as space, anything else '-', trimmed."""
    out = []
    for ch in text.upper().replace("_", " "):
        out.append(ch if ch in AKAI_CHARS else "-")
    return "".join(out).strip()


def encode_name(text: str) -> bytes:
    if len(text) > NAME_LEN or any(ch not in AKAI_CHARS for ch in text):
        raise ConvertError(f"{text!r} is not a valid Akai name")
    return bytes(AKAI_CHARS.index(ch) for ch in text.ljust(NAME_LEN))


def decode_name(raw: bytes) -> str:
    return "".join(AKAI_CHARS[c] if c < len(AKAI_CHARS) else "?" for c in raw).rstrip()


# --- SND -----------------------------------------------------------------

@dataclass
class Sound:
    name: str
    planes: list[bytes]   # signed 16-bit LE PCM per plane
    start: int
    end: int
    tune: int

    @property
    def frames(self) -> int:
        return len(self.planes[0]) // 2


def read_snd(data: bytes, origin: str = "SND") -> Sound:
    if len(data) < 38 or data[0] != 0x01 or data[1] & 0x7F != 0x02:
        raise ConvertError(f"{origin}: not an MPC3000 SND (header {data[:2].hex(' ') or 'empty'}, want 01 02)")
    rec = data[2:38]
    stereo = rec[0x13]
    if stereo > 1:
        raise ConvertError(f"{origin}: stereo byte is {stereo}, not 0 or 1")
    start, end, length = struct.unpack_from("<3I", rec, 0x14)
    planes = 1 + stereo
    want = 38 + 2 * length * planes
    if length == 0:
        raise ConvertError(f"{origin}: empty sound")
    if len(data) != want:
        raise ConvertError(f"{origin}: {len(data)} bytes, but {length} frames x {planes} plane(s) is {want}")
    name = rec[:16].split(b"\0", 1)[0].decode("latin-1").strip()
    tune = struct.unpack_from("<b", rec, 0x12)[0]
    pcm = data[38:]
    return Sound(name, [pcm[i * 2 * length:(i + 1) * 2 * length] for i in range(planes)], start, end, tune)


def write_snd(sound: Sound, vol: int = 100) -> bytes:
    """An SND as the MPC3000 Disk 8 loader would make it (for --extract and tests)."""
    record = (sound.name.encode("latin-1")[:16].ljust(16, b" ") + b"\0"
              + struct.pack("<BbB", vol, sound.tune, len(sound.planes) - 1)
              + struct.pack("<4I", sound.start, sound.end, sound.frames, 0))
    return b"\x01\x02" + record + b"".join(sound.planes)


# --- S1000/S3000 sample --------------------------------------------------

def akai_tune(mpc_tune: int) -> int:
    """Header +14 int16 (semitones in the high byte, 1/256 below) that 3.50 turns back into mpc_tune.

    3.50: tune = trunc((v + 13*sign(v)) * 10 / 256), clamped to +-120 (BE7E:0AE5..0B24).
    """
    if not -TUNE_LIMIT <= mpc_tune <= TUNE_LIMIT:
        raise ConvertError(f"tune {mpc_tune} outside +-{TUNE_LIMIT}")
    return round(mpc_tune * 25.6)


def mpc_tune(v: int) -> int:
    """The 3.50 loader's conversion of header +14 (for reading images back)."""
    v += 13 if v >= 0 else -13
    t = abs(v) * 10 // 256 * (1 if v >= 0 else -1)
    return max(-TUNE_LIMIT, min(TUNE_LIMIT, t))


def markers(sound: Sound) -> tuple[int, int]:
    """SND soft start/end, which 3.50 copies back verbatim; a bad pair becomes the whole sound."""
    start, end = sound.start, sound.end
    if not 0 <= start < end <= sound.frames:
        return 0, sound.frames
    return start, end


def sample_header(name: str, frames: int, start: int, end: int, tune: int, s3000: bool) -> bytes:
    """akaiutil akai_wav2sample defaults, plus the SND's markers and tune."""
    h = bytearray(S3000_HEADER if s3000 else S1000_HEADER)
    h[0x00] = 0x03                      # block ID
    h[0x01] = 0x01                      # bandwidth 20 kHz
    h[0x02] = 60                        # root key
    h[0x03:0x0F] = encode_name(name)
    h[0x0F] = 0x80
    h[0x13] = PMODE_NOLOOP              # no loops: +10 count stays 0
    struct.pack_into("<h", h, 0x14, akai_tune(tune))
    struct.pack_into("<3I", h, 0x1A, frames, start, end)
    struct.pack_into("<HH", h, 0x88, STPAIR_NONE, SR)
    return bytes(h)


def sample_names(base: str, stereo: bool) -> list[str]:
    if not stereo:
        name = base[:NAME_LEN].rstrip()
        if len(name) > 2 and name[-2] == "-" and name[-1] in "LR":
            name = name[:-2] + " " + name[-1]     # else 3.50 pairs it with an equal-size partner
        return [name]
    stem = base[:NAME_LEN - 2].rstrip().ljust(NAME_LEN - 2)
    return [stem + "-L", stem + "-R"]


def akai_samples(sound: Sound, base: str, s3000: bool) -> list[tuple[str, bytes]]:
    """(Akai name, file bytes) per plane; stereo is NAME-L (plane A) then NAME-R."""
    start, end = markers(sound)
    names = sample_names(base, len(sound.planes) == 2)
    return [(n, sample_header(n, sound.frames, start, end, sound.tune, s3000) + pcm)
            for n, pcm in zip(names, sound.planes)]


def parse_sample(body: bytes, header: int) -> dict:
    if len(body) < header or body[0] != 0x03:
        raise ConvertError("not an S1000/S3000 sample")
    frames, start, end = struct.unpack_from("<3I", body, 0x1A)
    if len(body) != header + 2 * frames:
        raise ConvertError(f"sample of {len(body)} bytes does not hold {frames} frames")
    return {"name": decode_name(body[3:15]), "frames": frames, "start": start, "end": end,
            "tune": struct.unpack_from("<h", body, 0x14)[0],
            "rate": struct.unpack_from("<H", body, 0x8A)[0], "pcm": body[header:]}


# --- floppy --------------------------------------------------------------

@dataclass
class DirEntry:
    name: str
    type: int
    size: int
    start: int
    osver: int


class AkaiFloppy:
    """An empty Akai S1000 (default) or S3000 floppy, filled with add()."""

    def __init__(self, density: Density = HD, s3000: bool = False, label: str = "NOT NAMED"):
        self.density = density
        self.s3000 = s3000
        self.label = clean_name(label)[:NAME_LEN].rstrip() or "NOT NAMED"
        self.osver = S3000_OSVER if s3000 else S1000_OSVER
        self.ftype = TYPE_S3000_SAMPLE if s3000 else TYPE_S1000_SAMPLE
        self.system_blocks = density.header_blocks + (S3000_DIR_BLOCKS if s3000 else 0)
        self.fat = [FAT_SYS] * self.system_blocks + [FAT_FREE] * (density.blocks - self.system_blocks)
        self.data = bytearray(density.size)
        self.entries: list[DirEntry] = []

    @property
    def capacity(self) -> int:
        return self.density.blocks - self.system_blocks

    @property
    def free_blocks(self) -> int:
        return self.fat.count(FAT_FREE)

    def fits(self, files: list[tuple[str, bytes]]) -> bool:
        need = sum(blocks(body) for _, body in files)
        return need <= self.free_blocks and len(self.entries) + len(files) <= ENTRIES

    def add(self, name: str, body: bytes) -> DirEntry:
        if any(e.name == name for e in self.entries):
            raise ConvertError(f"{name}: already on this disk")
        if len(body) > 0xFFFFFF:
            raise ConvertError(f"{name}: {len(body)} bytes exceeds the 24-bit size field")
        if len(self.entries) >= ENTRIES:
            raise ConvertError(f"{name}: directory full ({ENTRIES} files)")
        count = blocks(body)
        free = [b for b, v in enumerate(self.fat) if v == FAT_FREE][:count]
        if len(free) < count:
            raise ConvertError(f"{name}: needs {count} KiB, {self.free_blocks} KiB free")
        for i, here in enumerate(free):
            self.fat[here] = free[i + 1] if i + 1 < count else FAT_END
            self.data[here * BLOCK:(here + 1) * BLOCK] = body[i * BLOCK:(i + 1) * BLOCK].ljust(BLOCK, b"\0")
        entry = DirEntry(name, self.ftype, len(body), free[0], self.osver)
        self.entries.append(entry)
        return entry

    def _entry(self, e: DirEntry | None) -> bytes:
        tags = bytes(4) if self.s3000 else bytes([S1000_TAG] * 4)
        if e is None:
            if self.s3000:
                return bytes(24)
            return encode_name(EMPTY_NAME) + tags + bytes(6) + struct.pack("<H", self.osver)
        return (encode_name(e.name) + tags + bytes([e.type]) + struct.pack("<I", e.size)[:3]
                + struct.pack("<HH", e.start, e.osver))

    def image(self) -> bytes:
        d = self.density
        img = bytearray(self.data)
        listed: list[DirEntry | None] = [*self.entries] + [None] * (ENTRIES - len(self.entries))
        if self.s3000:
            # akaiutil akai_wipe_floppy: empty S1000 entries with S3000 tags, entry 0 flagged.
            empty = encode_name(EMPTY_NAME) + bytes(10) + struct.pack("<H", self.osver)
            for i in range(ENTRIES):
                img[i * 24:(i + 1) * 24] = empty
            img[0x10] = S3000_FLAG
            vdir = d.header_blocks * BLOCK
            for i, e in enumerate(listed):
                img[vdir + i * 24:vdir + (i + 1) * 24] = self._entry(e)
        else:
            for i, e in enumerate(listed):
                img[i * 24:(i + 1) * 24] = self._entry(e)
        struct.pack_into(f"<{d.blocks}H", img, FAT_OFFSET, *self.fat)
        label = bytearray(0x40)
        label[0:NAME_LEN] = encode_name(self.label)
        struct.pack_into("<H", label, 0x0E, self.osver)
        label[0x11] = 1                 # akai_init_volparam: program select OMNI, enable
        label[0x12] = 1
        if self.s3000:
            label[0x16:0x1A] = b"\x32\x09\x0c\xff"
        img[d.label_offset:d.label_offset + 0x40] = label
        return bytes(img)


def blocks(body: bytes) -> int:
    return max(1, -(-len(body) // BLOCK))


def density_of(img: bytes) -> Density:
    for d in (HD, DD):
        if len(img) == d.size:
            return d
    raise ConvertError(f"{len(img)} bytes is not an Akai HD ({HD.size}) or DD ({DD.size}) floppy image")


def read_floppy(img: bytes) -> tuple[str, bool, list[tuple[DirEntry, bytes]]]:
    """(label, is_s3000, [(entry, file bytes)]) for every used entry of an Akai floppy image."""
    d = density_of(img)
    fat = struct.unpack_from(f"<{d.blocks}H", img, FAT_OFFSET)
    s3000 = img[0x10] == S3000_FLAG
    base, count = (d.header_blocks * BLOCK, 510) if s3000 else (0, ENTRIES)
    files = []
    for i in range(count):
        raw = img[base + i * 24:base + (i + 1) * 24]
        if raw[16] == 0:
            continue
        size = raw[17] | raw[18] << 8 | raw[19] << 16
        start, osver = struct.unpack_from("<HH", raw, 20)
        entry = DirEntry(decode_name(raw[:NAME_LEN]), raw[16], size, start, osver)
        body = bytearray()
        block, seen = start, set()
        while True:
            if block in seen or not 0 <= block < d.blocks or fat[block] in (FAT_FREE, FAT_SYS):
                raise ConvertError(f"{entry.name}: broken FAT chain at block {block}")
            seen.add(block)
            body += img[block * BLOCK:(block + 1) * BLOCK]
            if fat[block] == FAT_END or len(body) >= size:
                break
            block = fat[block]
        if len(body) < size or fat[block] != FAT_END:
            raise ConvertError(f"{entry.name}: FAT chain does not match the {size}-byte size")
        files.append((entry, bytes(body[:size])))
    return decode_name(img[d.label_offset:d.label_offset + NAME_LEN]), s3000, files


def extract(img: bytes) -> list[Sound]:
    """The sounds the MPC3000 would make of an image we wrote: stereo pairs joined, header per type."""
    _, _, files = read_floppy(img)
    samples = {}
    for entry, body in files:
        if entry.type & 0x7F == TYPE_S1000_SAMPLE:
            header = S3000_HEADER if entry.type == TYPE_S3000_SAMPLE else S1000_HEADER
            samples[entry.name] = parse_sample(body, header)
    sounds = []
    for name, s in samples.items():
        if name.endswith("-R") and name[:-1] + "L" in samples:
            continue
        planes = [s["pcm"]]
        if name.endswith("-L") and name[:-1] + "R" in samples:
            planes.append(samples[name[:-1] + "R"]["pcm"])
            name = name[:-2].rstrip()
        sounds.append(Sound(name, planes, s["start"], s["end"], mpc_tune(s["tune"])))
    return sounds


# --- HFE (HxC flux image; FlashFloppy, HxC, MAME) ------------------------

_CRC_TABLE = []
for _n in range(256):
    _c = _n << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021 if _c & 0x8000 else _c << 1) & 0xFFFF
    _CRC_TABLE.append(_c)


def _crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-CCITT as the FDC computes it over the A1 marks and the field."""
    for byte in data:
        crc = (crc << 8 & 0xFFFF) ^ _CRC_TABLE[crc >> 8 ^ byte]
    return crc


def _mfm_word(cells: int) -> bytes:
    """16 cells, first in time as the top bit, as two HFE bytes (first cell in bit 0)."""
    flipped = int(f"{cells:016b}"[::-1], 2)
    return struct.pack("<H", flipped)


# _MFM_TABLE[previous data bit][byte]: the byte's 16 cells (clock, data per bit).
_MFM_TABLE = [[b""] * 256 for _ in range(2)]
for _last in range(2):
    for _value in range(256):
        _cells, _prev = 0, _last
        for _i in range(7, -1, -1):
            _bit = _value >> _i & 1
            _cells = _cells << 2 | int(not (_bit or _prev)) << 1 | _bit
            _prev = _bit
        _MFM_TABLE[_last][_value] = _mfm_word(_cells)


class _MFM:
    """An MFM cell stream in HFE byte order; every field is whole bytes (16 cells)."""

    def __init__(self) -> None:
        self.out = bytearray()
        self.last = 0

    def put(self, data: bytes) -> None:
        last = self.last
        for value in data:
            self.out += _MFM_TABLE[last][value]
            last = value & 1
        self.last = last

    def sync(self, word: int) -> None:
        """Three marks with a missing clock: 0x4489 (A1) or 0x5224 (C2)."""
        self.out += _mfm_word(word) * 3
        self.last = word & 1


def _track_bytes(d: Density) -> int:
    return d.hfe_rate * 400 // 8   # one cell per 500000/rate ns: 400*rate cells in 200 ms


def _track(img: bytes, d: Density, cyl: int, head: int) -> bytes:
    """One IBM MFM track as Akai formats it: gap3 0x74, sectors interleaved per akaiutil."""
    m = _MFM()
    m.put(b"\x4E" * 80 + b"\x00" * 12)
    m.sync(0x5224)
    m.put(b"\xFC" + b"\x4E" * 50)
    for slot in range(d.spt):
        sec = 1 + (d.sector_offset + slot + cyl * (d.spt - d.track_skew)) % d.spt
        block = (cyl * HEADS + head) * d.spt + sec - 1
        for field, gap in ((bytes([0xFE, cyl, head, sec, 3]), 22),
                           (b"\xFB" + img[block * BLOCK:(block + 1) * BLOCK], 0x74)):
            m.put(b"\x00" * 12)
            m.sync(0x4489)
            m.put(field + struct.pack(">H", _crc16(b"\xA1\xA1\xA1" + field)) + b"\x4E" * gap)
    total = _track_bytes(d)
    if len(m.out) > total:
        raise AssertionError(f"track {cyl}/{head} needs {len(m.out)} bytes, has {total}")
    m.put(b"\x4E" * ((total - len(m.out)) // 2))
    return bytes(m.out)


def hfe(img: bytes) -> bytes:
    d = density_of(img)
    side = _track_bytes(d)
    span = -(-side // 256) * 512            # both sides, interleaved in 256-byte halves
    header = bytearray(b"\xFF" * 512)
    header[0:20] = (b"HXCPICFE" + bytes([0, CYLINDERS, HEADS, 0x00])   # ISOIBM_MFM
                    + struct.pack("<HHBBH", d.hfe_rate, 300, 0x07, 0x00, 1))  # generic Shugart
    lut = bytearray(b"\xFF" * 512)
    out = bytearray()
    for cyl in range(CYLINDERS):
        struct.pack_into("<HH", lut, cyl * 4, 2 + cyl * span // 512, 2 * side)
        sides = [_track(img, d, cyl, h) for h in range(HEADS)]
        chunk = bytearray(span)
        for i in range(0, side, 256):
            chunk[2 * i:2 * i + 256] = sides[0][i:i + 256].ljust(256, b"\0")
            chunk[2 * i + 256:2 * i + 512] = sides[1][i:i + 256].ljust(256, b"\0")
        out += chunk
    return bytes(header + lut + out)


# --- driver --------------------------------------------------------------

def free_base(disk: AkaiFloppy, base: str, stereo: bool) -> str:
    """base, or base with a number replacing its tail, whose sample name(s) are not on disk."""
    taken = {e.name for e in disk.entries}
    width = NAME_LEN - 2 if stereo else NAME_LEN
    for n in range(1000):
        tag = str(n) if n else ""
        candidate = (base[:width - len(tag)].rstrip() + tag) or "SAMPLE"
        if not taken & set(sample_names(candidate, stereo)):
            return candidate
    raise ConvertError(f"no free name for {base!r}")


def convert(paths: list[Path], density: Density = HD, s3000: bool = False,
            label: str = "NOT NAMED") -> list[AkaiFloppy]:
    """Fill floppies in order; a sound that does not fit starts the next disk."""
    disks = [AkaiFloppy(density, s3000, label)]
    for path in paths:
        sound = read_snd(path.read_bytes(), str(path))
        stereo = len(sound.planes) == 2
        base = clean_name(sound.name) or clean_name(path.stem) or "SAMPLE"
        files = akai_samples(sound, base, s3000)
        if not AkaiFloppy(density, s3000).fits(files):
            raise ConvertError(f"{path}: {sum(blocks(b) for _, b in files)} KiB does not fit on an empty "
                               f"{density.name.upper()} floppy ({disks[0].capacity} KiB)")
        if not disks[-1].fits(files):
            disks.append(AkaiFloppy(density, s3000, label))
        disk = disks[-1]
        for akai_name, body in akai_samples(sound, free_base(disk, base, stereo), s3000):
            disk.add(akai_name, body)
    return disks


def output_paths(out: Path, count: int) -> list[Path]:
    if count == 1:
        return [out]
    return [out.with_name(f"{out.stem}{i + 1:02d}{out.suffix}") for i in range(count)]


def load_image(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:8] == b"HXCPICFE":
        raise ConvertError(f"{path}: give the .img; HFE images are write-only here")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1].split("\n\nSND")[0])
    ap.add_argument("snd", nargs="*", type=Path, help="MPC3000 .SND files")
    ap.add_argument("-o", "--out", type=Path,
                    help="output .img or .hfe (more disks: NAME01, NAME02, ...); with --extract, a directory")
    ap.add_argument("--density", choices=sorted(DENSITIES), default="hd")
    ap.add_argument("--s3000", action="store_true", help="native S3000 floppy and 192-byte headers")
    ap.add_argument("--label", default="NOT NAMED", help="volume label (12 Akai characters)")
    ap.add_argument("--list", type=Path, metavar="IMG", help="list an Akai floppy image")
    ap.add_argument("--extract", type=Path, metavar="IMG", help="write the image's samples back as .SND")
    args = ap.parse_args(argv)
    try:
        if args.list:
            label, s3000, files = read_floppy(load_image(args.list))
            print(f"{args.list}: {'S3000' if s3000 else 'S1000'} floppy {label!r}, {len(files)} file(s)")
            for entry, body in files:
                line = f"  {entry.name:12}  type {entry.type:02X}  {entry.size:8} bytes  block {entry.start}"
                if entry.type & 0x7F == TYPE_S1000_SAMPLE:
                    s = parse_sample(body, S3000_HEADER if entry.type == TYPE_S3000_SAMPLE else S1000_HEADER)
                    line += f"  {s['frames']} frames {s['rate']} Hz  start {s['start']} end {s['end']}"
                print(line)
            return 0
        if args.extract:
            if not args.out:
                ap.error("--extract needs -o DIR")
            args.out.mkdir(parents=True, exist_ok=True)
            for sound in extract(load_image(args.extract)):
                path = args.out / f"{sound.name.replace(' ', '_') or 'SAMPLE'}.SND"
                path.write_bytes(write_snd(sound))
                print(path)
            return 0
        if not args.snd or not args.out:
            ap.error("give .SND files and -o OUT.img|OUT.hfe, or --list / --extract IMG")
        if args.out.suffix.lower() not in (".img", ".hfe"):
            ap.error("-o must end in .img or .hfe")
        density = DENSITIES[args.density]
        if args.s3000 and density is DD:
            print("snd2akai: warning: MPC3000 3.50 cannot read the directory of a DD S3000 floppy",
                  file=sys.stderr)
        disks = convert(args.snd, density, args.s3000, args.label)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        for disk, path in zip(disks, output_paths(args.out, len(disks))):
            img = disk.image()
            path.write_bytes(hfe(img) if path.suffix.lower() == ".hfe" else img)
            names = ", ".join(e.name for e in disk.entries)
            print(f"{path}: {len(disk.entries)} sample(s), {disk.free_blocks} KiB free: {names}")
        return 0
    except (ConvertError, OSError) as exc:
        print(f"snd2akai: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
