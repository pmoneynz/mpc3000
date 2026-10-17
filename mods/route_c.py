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
  relative paragraph HOME and far-jumps to 3.16's entry 0000:0000;
* when the cave ends with the label `reloc_table` (mods/entry316.inc), a copy
  of the relocation list in the image itself, right after the cave: the entry
  routine uses it to move the image from a load segment above UNIV down to
  UNIV (notes/port_316.md "Cave space"); `encode_relocs` gives the format.

Patch NEW bytes may contain `{label}` (4 bytes: label offset, HOME segment;
the segment word is relocated) and `{seg:XXXX}` (2 bytes, relocated). OLD
bytes are the file bytes (before relocation).

`simulate()` re-does the EPROM loader's work at a load segment L in Python
(load image, add L to every listed word, the loader's BIOS records of L),
then, with `univ`, entry316's move to UNIV, then the entry copy.
mods/build_wave316.py runs entry316 from its assembled immediates instead and
compares.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

HEADER_FIELDS = "magic cblp cp crlc cparhdr minalloc maxalloc ss sp csum ip cs lfarlc ovno".split()
LOADS = (0x6900, 0x7000)            # 3.12/3.50 and 3.08/3.11 loaders
UNIV = 0x6900                       # the universal runtime load segment (entry316 UNIV_SEG)
PAGE61 = 0xF4000                    # first logical byte the image must not reach
BIOS_LOAD_SEG = 0x0400 + 0x640A     # 0040:640A, INT 45's load segment (floppy_loader.md §7)
BIOS_JMP_SEG = 0x0400 + 0x68C2      # 0040:68C2, the hand-off's JMP FAR [68C0] segment (§5)
TABLE_HEAD = 6                      # reloc_table: N paragraphs, R records, least D
SKIP = 0xFFF0                       # advance of a 00 0000 record


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


def encode_relocs(positions: list[int]) -> tuple[bytes, int]:
    """Records of the entry316 relocation table for sorted image offsets.

    01..FF: advance that many bytes and adjust the word there; 00 w (w != 0,
    w <= SKIP): advance w and adjust; 00 0000: advance SKIP only.  The first
    advance starts at offset 0.  Returns (records, count)."""
    out, count, at = bytearray(), 0, 0
    for pos in positions:
        gap = pos - at
        if gap <= 0:
            raise ValueError(f"relocation at 0x{pos:05X} not after 0x{at:05X}")
        while gap > SKIP:
            out += b"\0\0\0"
            count += 1
            gap -= SKIP
        out += bytes([gap]) if gap <= 0xFF else b"\0" + struct.pack("<H", gap)
        count += 1
        at = pos
    return bytes(out), count


def decode_relocs(table: bytes | bytearray, at: int = 0) -> tuple[dict[str, int], list[int]]:
    """Header and image offsets of a relocation table at table[at] (entry316's reading)."""
    n, count, dmin = struct.unpack_from("<3H", table, at)
    i, pos, out = at + TABLE_HEAD, 0, []
    for _ in range(count):
        b = table[i]; i += 1
        if b:
            pos += b
        else:
            w = struct.unpack_from("<H", table, i)[0]; i += 2
            if not w:
                pos += SKIP
                continue
            pos += w
        out.append(pos)
    return {"paragraphs": n, "records": count, "min_delta": dmin, "bytes": i - at}, out


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
    table: int = 0          # image offset of the relocation table (0: none)
    table_len: int = 0


def build(base: bytes, cave: bytes, cave_labels: dict[str, int], patches: list[Patch], *,
          home: int, entry_label: str = "entry316", table_label: str = "reloc_table") -> Result:
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
    table = table_len = 0
    if table_label in cave_labels:
        # The image's own copy of the relocation list (entry316's move).  The
        # least move D keeps the copy below the code that runs it: UNIV + N <=
        # L + stage + entry316's paragraph.
        if cave_labels[table_label] != len(cave):
            raise ValueError(f"{table_label} at cave+{cave_labels[table_label]:#x}, not at the cave end")
        records, count = encode_relocs(sorted(positions))
        table = len(image)
        table_len = TABLE_HEAD + len(records)
        n = stage + para(len(cave) + table_len)
        dmin = n - stage - cave_labels[entry_label] // 16
        image += struct.pack("<3H", n, count, dmin) + records
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
                  removed, len(added), len(relocs), table, table_len)


def load(sys_bytes: bytes, seg: int) -> tuple[bytearray, dict]:
    """Logical memory after the EPROM loader (INT 45 and the hand-off) at load segment seg.

    Models the image, its relocations and the loader's two BIOS-data records
    of seg; returns the hand-off registers."""
    mz = MZ.parse(sys_bytes)
    mem = bytearray(0x100000)
    base = seg * 16
    mem[base:base + len(mz.image)] = mz.image
    for o, s in mz.relocs:
        a = base + lin(s, o)
        w = (struct.unpack_from("<H", mem, a)[0] + seg) & 0xFFFF
        struct.pack_into("<H", mem, a, w)
    regs = {"cs": (seg + mz.h["cs"]) & 0xFFFF, "ip": mz.h["ip"],
            "ss": (seg + mz.h["ss"]) & 0xFFFF, "sp": mz.h["sp"]}
    struct.pack_into("<H", mem, BIOS_LOAD_SEG, seg)
    struct.pack_into("<H", mem, BIOS_JMP_SEG, regs["cs"])
    return mem, regs


def move(mem: bytearray, regs: dict, seg: int, univ: int, table: int) -> None:
    """entry316's .move and .moved: rebase an image loaded at seg > univ to univ.

    table is the relocation table's image offset."""
    d = seg - univ
    head, positions = decode_relocs(mem, seg * 16 + table)
    if d < head["min_delta"]:
        raise ValueError(f"L={seg:04X}: move by {d:#x} paragraphs, least {head['min_delta']:#x}")
    base = seg * 16
    for pos in positions:
        a = base + pos
        struct.pack_into("<H", mem, a, (struct.unpack_from("<H", mem, a)[0] - d) & 0xFFFF)
    n = head["paragraphs"] * 16
    mem[univ * 16:univ * 16 + n] = mem[base:base + n]
    mem[univ * 16 + n:base + n] = bytes(d * 16)
    for a, want in ((BIOS_LOAD_SEG, seg), (BIOS_JMP_SEG, regs["cs"])):
        if struct.unpack_from("<H", mem, a)[0] == want:
            struct.pack_into("<H", mem, a, want - d)
    regs.update(ss=(regs["ss"] - d) & 0xFFFF, cs=(regs["cs"] - d) & 0xFFFF)


def simulate(sys_bytes: bytes, seg: int, *, home: int, cave_len: int, univ: int | None = None,
             table: int = 0) -> tuple[bytearray, dict]:
    """Logical memory after the EPROM loader, entry316's move (univ and table
    given, seg > univ) and its entry copy.  regs["seg"] is 3.16's runtime load segment."""
    mem, regs = load(sys_bytes, seg)
    run = seg
    if univ is not None and table and seg > univ:
        move(mem, regs, seg, univ, table)
        run = univ
    stage = MZ.parse(sys_bytes).h["cs"]
    src, dst = (run + stage) * 16, (run + home) * 16
    mem[dst:dst + cave_len] = mem[src:src + cave_len]
    regs["seg"] = run
    return mem, regs
