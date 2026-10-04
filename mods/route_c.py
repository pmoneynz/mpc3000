#!/usr/bin/env python3
"""Route C: patch OS 3.16 (M3K316.SYS) and append a relocatable cave.

Used by mods/build_wave316.py; design and evidence in notes/port_316.md.

The output is still one DOS MZ file that every MPC3000 EPROM loader can load
(notes/floppy_loader.md §7; notes/port_316.md):

* the 3.16 load image with hook bytes patched (old bytes verified);
* the cave, assembled at org 0, appended at relative paragraph STAGE (the
  3.16 image end, which is BSS that 3.16 zeroes later);
* a relocation table = 3.16's own entries, minus any inside replaced hook
  bytes, plus one entry per segment word the patches and the cave contain;
* entry CS:IP = STAGE:cave_entry. The cave's entry routine copies the cave to
  relative paragraph HOME and far-jumps to 3.16's entry 0000:0000.

Patch NEW bytes may contain `{label}` (4 bytes: label offset, HOME segment;
the segment word is relocated) and `{seg:XXXX}` (2 bytes, relocated). OLD
bytes are the file bytes (before relocation).

`simulate()` re-does the EPROM loader's work at a load segment L in Python
(load image, add L to every listed word, run the entry copy) and is used by
`verify()` to check every relocated word and every far pointer before the
file is written.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

HEADER_FIELDS = "magic cblp cp crlc cparhdr minalloc maxalloc ss sp csum ip cs lfarlc ovno".split()
LOADS = (0x6900, 0x7000)            # 3.12/3.50 and 3.08/3.11 loaders
PAGE61 = 0xF4000                    # first logical byte the image must not reach


@dataclass
class MZ:
    raw: bytes
    h: dict[str, int]
    image: bytearray
    relocs: list[tuple[int, int]]   # (offset, segment) as stored

    @classmethod
    def parse(cls, raw: bytes) -> "MZ":
        h = dict(zip(HEADER_FIELDS, struct.unpack_from("<14H", raw, 0)))
        if h["magic"] != 0x5A4D:
            raise ValueError("not an MZ executable")
        hdr = h["cparhdr"] * 16
        size = (h["cp"] - (h["cblp"] != 0)) * 512 + h["cblp"]
        if size != len(raw):
            raise ValueError(f"header size {size} != file size {len(raw)}")
        relocs = [struct.unpack_from("<HH", raw, h["lfarlc"] + 4 * i) for i in range(h["crlc"])]
        return cls(raw, h, bytearray(raw[hdr:size]), relocs)


def lin(seg: int, off: int) -> int:
    return seg * 16 + off


def para(n: int) -> int:
    return (n + 15) >> 4


@dataclass
class Patch:
    off: int
    old: bytes
    new: bytes
    reloc_words: list[int] = field(default_factory=list)   # absolute image offsets
    labels: list[tuple[int, str]] = field(default_factory=list)


def expand(off: int, old_hex: str, new_spec: str, labels: dict[str, int], home: int) -> Patch:
    """Expand {label} / {seg:XXXX} tokens in a NEW byte spec."""
    out = bytearray()
    words: list[int] = []
    used: list[tuple[int, str]] = []
    pos = 0
    for m in re.finditer(r"\{(seg:)?([0-9A-Za-z_]+)\}", new_spec):
        out += bytes.fromhex(new_spec[pos:m.start()])
        if m.group(1):
            words.append(off + len(out))
            out += struct.pack("<H", int(m.group(2), 16))
        else:
            name = m.group(2)
            if name not in labels:
                raise ValueError(f"0x{off:05X}: no cave label {name!r}")
            used.append((off + len(out), name))
            out += struct.pack("<H", labels[name])
            words.append(off + len(out))
            out += struct.pack("<H", home)
        pos = m.end()
    out += bytes.fromhex(new_spec[pos:])
    old = bytes.fromhex(old_hex)
    if len(old) != len(out):
        raise ValueError(f"0x{off:05X}: OLD is {len(old)} bytes, NEW is {len(out)}")
    return Patch(off, old, bytes(out), words, used)


@dataclass
class Result:
    sys: bytes
    stage: int
    home: int
    entry: int
    cave_len: int
    relocs_removed: list[int]
    relocs_added: int
    reloc_count: int


def build(base: bytes, cave: bytes, cave_labels: dict[str, int], patches: list[Patch], *,
          home: int, entry_label: str = "entry316") -> Result:
    mz = MZ.parse(base)
    image = mz.image
    stage = para(len(image))
    old_positions = [lin(s, o) for o, s in mz.relocs]
    replaced: list[tuple[int, int]] = []
    for p in patches:
        end = p.off + len(p.old)
        if end > len(image):
            raise ValueError(f"0x{p.off:05X}: patch runs past the 3.16 image")
        if bytes(image[p.off:end]) != p.old:
            raise ValueError(f"0x{p.off:05X}: expected {p.old.hex()}, found {image[p.off:end].hex()}")
        for a, b in replaced:
            if p.off < b and a < end:
                raise ValueError(f"0x{p.off:05X}: overlaps another patch")
        replaced.append((p.off, end))
        image[p.off:end] = p.new
    # Drop every 3.16 relocation whose word touches replaced bytes.
    keep, removed = [], []
    for (o, s), pos in zip(mz.relocs, old_positions):
        if any(a < pos + 2 and pos < b for a, b in replaced):
            removed.append(pos)
        else:
            keep.append((o, s))
    image += bytes(stage * 16 - len(image))
    image += cave
    added: list[tuple[int, int]] = []
    for p in patches:
        for w in p.reloc_words:
            added.append((w & 0xF, w >> 4))
    for name, value in sorted(cave_labels.items(), key=lambda kv: kv[1]):
        if name.startswith("__reloc_"):
            if not 0 <= value <= len(cave) - 2:
                raise ValueError(f"{name}={value:#x} outside the cave")
            added.append((value, stage))
    relocs = keep + added
    positions = [lin(s, o) for o, s in relocs]
    if len(set(positions)) != len(positions):
        raise ValueError("two relocations for one word")
    h = dict(mz.h)
    hdr = h["cparhdr"] * 16
    table_end = h["lfarlc"] + 4 * len(relocs)
    if table_end > hdr:
        raise ValueError(f"relocation table ends at {table_end:#x}, header is {hdr:#x}")
    if entry_label not in cave_labels:
        raise ValueError(f"cave has no {entry_label!r}")
    size = hdr + len(image)
    h.update(cblp=size % 512, cp=(size + 511) // 512, crlc=len(relocs),
             cs=stage, ip=cave_labels[entry_label],
             minalloc=max(0, home + para(len(cave)) - para(len(image))))
    header = bytearray(mz.raw[:hdr])
    struct.pack_into("<14H", header, 0, *(h[k] for k in HEADER_FIELDS))
    header[h["lfarlc"]:hdr] = bytes(hdr - h["lfarlc"])
    for i, (o, s) in enumerate(relocs):
        struct.pack_into("<HH", header, h["lfarlc"] + 4 * i, o, s)
    return Result(bytes(header) + bytes(image), stage, home, cave_labels[entry_label], len(cave),
                  removed, len(added), len(relocs))


def simulate(sys_bytes: bytes, load: int, *, home: int, cave_len: int) -> tuple[bytearray, dict]:
    """Logical memory image after the EPROM loader and the cave's entry copy."""
    mz = MZ.parse(sys_bytes)
    mem = bytearray(0x100000)
    base = load * 16
    mem[base:base + len(mz.image)] = mz.image
    for o, s in mz.relocs:
        a = base + lin(s, o)
        w = (struct.unpack_from("<H", mem, a)[0] + load) & 0xFFFF
        struct.pack_into("<H", mem, a, w)
    stage = mz.h["cs"]
    src, dst = base + stage * 16, base + home * 16
    mem[dst:dst + cave_len] = mem[src:src + cave_len]
    regs = {"cs": (load + mz.h["cs"]) & 0xFFFF, "ip": mz.h["ip"],
            "ss": (load + mz.h["ss"]) & 0xFFFF, "sp": mz.h["sp"]}
    return mem, regs
