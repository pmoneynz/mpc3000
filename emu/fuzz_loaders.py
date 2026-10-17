"""Seeded loader fuzzer for OS 3.16 (stock M3K316.SYS or PMONEY) in MAME.

Run (from the repo root, once adopted as emu/fuzz_loaders.py):

    python3 -m emu.fuzz_loaders run --types SND,PGM,APS,SEQ,ALL,PAR,SET,ST1,MID \
        --seeds 0-39 [--bios v311] [--sys "07-rom/v3.16 maintenance upgrade/M3K316.SYS"] \
        [--out build/emu/fuzz-loaders] [--workers 6]
    python3 -m emu.fuzz_loaders baseline [...]      # unmutated base of each type
    python3 -m emu.fuzz_loaders repro --type SND --seed 17 [--ops JSON]
    python3 -m emu.fuzz_loaders minimize --type SND --seed 17

Each case is one MAME run resumed from a boot snapshot (OS 3.16 at Play/Record,
SCSI search cancelled): a floppy holding the mutated file FZ.<EXT> (plus the
companion FZSND.SND that PGM/APS name) is inserted, Disk / 7 / <Load> runs
the stock loader, a type-specific key confirms (PGM <Load it>, APS/SEQ/ALL/MID
<Do it>, SET/ST1 option 1), then Main Screen twice and a short exercise
(SEQ/ALL/MID: Play 3 s, Stop; PGM/APS: pads 1-8).  The oracle (Lua, read-only:
it never writes MPC memory) reports, per case:

  crash    execution outside the OS image / cave / BIOS ROM segments, or the
           "System Error" / "software bug" screen, or MAME failing
  hang     the final screen is not Play/Record and the field editor
           (02D7:0357) never ran after the last Main Screen key
  corrupt  a 1 KiB block of the 3.16 code image changed (blocks that change
           in the unmutated baseline runs are masked), or a sound record /
           current-program note record violates its invariants
  leak     BUSY (DGROUP 9444) non-zero, or port 6Ah left at 00h (muted)
  blankmsg an "Attention!" box with no message text
  ok       anything else (load accepted, or refused with a message)

Mutations are field-aware (each format's header/count/length/name/rate
fields with boundary values) plus truncation, appended bytes, flips and
fills.  Every case is reproducible from (type, seed); `minimize` delta-debugs
the operation list of a failing case and writes the minimal file.

Address forms: 3.16 relative seg:off as stored in M3K316.SYS; runtime
CS = L + seg (PMONEY: L = 6900h on every set, entry316 moves a 7000h load).
Use a BIOS set with L = 7000h (v311, v308) for stock 3.16: with L = 6900h
stock 3.16's sequence pool overlaps its own image (notes/port_316.md) and
every sequence load would trip the code-image oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from emu.mpc3k import BUILD, REPO, disk as fat_disk, parse_screens, run
from emu.panel import key_tap, pad_hit, panel_pad, write_smf
from emu.snd import sine, snd

M3K316 = REPO / "07-rom" / "v3.16 maintenance upgrade" / "M3K316.SYS"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
OUT = BUILD / "emu" / "fuzz-loaders"
LOAD_SEGMENTS = {"default": 0x6900, "vailixi": 0x6900, "v311": 0x7000, "v308": 0x7000}
RUNTIME_PMONEY = 0x6900    # PMONEY (Route C, MZ entry in the cave) runs here on every set: entry316's move
DGROUP = 0x609C            # 3.16 relative DGROUP segment
SND_SEG = 0x539D           # 3.16 relative sound segment (records at +4800h)
IMAGE_CODE_END = 0x609C0   # 3.16 load-image bytes below DGROUP (code and far data)
EXTENT = 0x7DFB0           # 3.16 image + BSS + stack (minalloc), relative bytes
SNAP_AT = 33.8             # snapshot time: SCSI search cancelled at 33.0
# Deterministic release-gate smoke set: a few seeds per type that the
# campaign found interesting, plus the minimal corrupt-PGM crash fixture.
SMOKE_SEEDS = {"SND": (4, 9, 24), "PGM": (0, 15, 17), "APS": (10,),
               "SEQ": (8,), "SET": (0,), "ST1": (8,)}
SMOKE_FAIL = frozenset({"crash", "hang"})  # gate-fatal (mask-independent; corrupt-* needs a baseline)
T_DISK, T_SEVEN, T_LOAD, T_CONFIRM, T_CONFIRM2, T_CONFIRM3, T_CONFIRM4 = 35.0, 35.8, 39.0, 41.5, 44.0, 46.5, 48.5
T_MAIN1, T_MAIN2, T_EXERCISE, T_MAIN3, T_END = 50.0, 51.0, 52.0, 57.0, 60.0

# --------------------------------------------------------------------------
# Base files


def _u16(v): return struct.pack("<H", v & 0xFFFF)
def _u32(v): return struct.pack("<I", v & 0xFFFFFFFF)


def base_snd() -> bytes:
    """Native SND (01 02 + 24h-byte record + PCM), 2,205 mono frames."""
    return snd("FZSND", [sine(2205)])


def companion_snd() -> bytes:
    return snd("FZSND", [sine(2205)])


def base_pgm() -> bytes:
    """Stock 0x1200-byte PGM (emu/fixtures/mute-native-blank.PGM) naming FZSND
    in directory slot 0 and binding pad slots 0-7 to it."""
    from emu import pgm
    return pgm.for_sound(companion_snd(), pads=range(8))[:pgm.PGM_BYTES]


def _fixture(name: str, fixtures: Path) -> bytes:
    path = fixtures / name
    if not path.is_file():
        raise FileNotFoundError(f"{path}: run `python3 -m emu.fuzz_loaders fixtures` first")
    return path.read_bytes()


def base_aps(fixtures: Path) -> bytes:
    """Stock-saved APS (24 programs) whose sound directory names FZSND, with
    program 1 pads 0-7 bound to directory slot 0."""
    data = bytearray(_fixture("fuzz-ALL_PGMS.APS", fixtures))
    n = data[2]
    names = 7 + 0x13C + n * 0x77E
    data[names:names + 0x880] = bytes(0x880)
    data[names:names + 17] = b"FZSND".ljust(17, b"\0")
    for pad in range(8):
        data[7 + 0x13C + 0x3E + pad * 0x18] = 0
    return bytes(data)


def base_smf() -> bytes:
    """Format-1 SMF, 96 ticks/quarter, tempo track + one note track."""
    def trk(ev: bytes) -> bytes:
        return b"MTrk" + _u32be(len(ev)) + ev
    tempo = b"\x00\xff\x51\x03\x07\xa1\x20" + b"\x00\xff\x58\x04\x04\x02\x18\x08" + b"\x00\xff\x2f\x00"
    notes = b""
    for k in range(8):
        notes += b"\x00\x99" + bytes([36 + k % 4, 100]) + b"\x30\x89" + bytes([36 + k % 4, 0])
    notes += b"\x00\xff\x2f\x00"
    return b"MThd" + _u32be(6) + b"\x00\x01\x00\x02\x00\x60" + trk(tempo) + trk(notes)


def _u32be(v): return struct.pack(">I", v)


def base_set(kind: int) -> bytes:
    """Structural MPC60-style SET (kind 2) / ST1 (kind 5) following the reads of
    113A:000E: type, version 1, 3 bytes, 34 x 3Bh sound entries, [ST1: 1 byte],
    22h bytes, count byte, 3 x 20h bytes, then sample data.  Not validated as
    loadable: mutations still exercise the header parser."""
    body = bytearray([kind, 1]) + b"\x00\x10\x00"
    entries = bytearray(0x7D6)
    entries[0:5] = b"FZ01\0"
    entries[0x16:0x1A] = _u32(0x800)
    body += entries
    if kind == 5:
        body += b"\x00"
    body += bytes(0x22) + b"\x01" + bytes(0x60)
    body += bytes(0x1000)
    return bytes(body)


# --------------------------------------------------------------------------
# Formats


@dataclass(frozen=True)
class Field:
    name: str
    off: int
    width: int                  # 1, 2, 4 (little endian) or 17 (NUL-terminated name)
    values: tuple = ()          # extra interesting values for this field


@dataclass
class Format:
    ext: str
    base: object                # callable(fixtures) -> bytes
    fields: tuple
    confirm: tuple = ()         # (time, key) after <Load>
    exercise: str = ""          # "play", "pads" or ""
    companion: bool = False     # FZSND.SND on the disk
    structures: tuple = ()      # (offset, length) regions for block-level mutations


def _names(start: int, count: int, step: int = 17, label: str = "name") -> tuple:
    return tuple(Field(f"{label}{i}", start + i * step, 17) for i in range(count))


SND_FIELDS = (
    Field("magic", 0, 1, (0, 2, 0xFF)), Field("version", 1, 1, (0, 1, 2, 3, 0x7F, 0x80, 0x82, 0xFF)),
    Field("name", 2, 17), Field("volume", 0x13, 1, (0, 100, 101, 0xFF)),
    Field("tune", 0x14, 1, (0x80, 0x7F, 0x79, 0x87)), Field("stereo", 0x15, 1, (0, 1, 2, 0xFF)),
    Field("start", 0x16, 4), Field("end", 0x1A, 4), Field("length", 0x1E, 4),
    Field("wave", 0x22, 4))
PGM_FIELDS = (
    Field("magic", 0, 1, (0, 6, 8, 0xFF)), Field("version", 1, 1, (0, 1, 2, 0x80, 0xFF)),
    *_names(2, 4), Field("name127", 2 + 127 * 17, 17),
    *(Field(f"words{i}", 0x882 + 4 * i, 4) for i in (0, 1, 127)),
    Field("pgm_name", 0xA82, 17),
    *(Field(f"note{p}.sound", 0xA82 + 0x3E + p * 0x18, 1, (0x7F, 0x80, 0xFE, 0xFF)) for p in (0, 1, 63)),
    *(Field(f"note{p}.b{b}", 0xA82 + 0x3E + p * 0x18 + b, 1) for p in (0,) for b in range(1, 0x18)),
    *(Field(f"rec.b{b:02X}", 0xA82 + b, 1) for b in range(0x11, 0x3E)))
APS_FIELDS = (
    Field("magic", 0, 1, (0, 9, 0x0B, 0xFF)), Field("version", 1, 1, (0, 1, 0x80, 0xFF)),
    Field("count", 2, 1, (0, 1, 23, 24, 25, 0x7F, 0x80, 0xFF)), Field("words", 3, 4),
    *(Field(f"block.b{b:03X}", 7 + b, 1) for b in range(0, 0x13C, 7)),
    Field("pgm0_name", 7 + 0x13C, 17),
    *(Field(f"pgm0.note{p}.sound", 7 + 0x13C + 0x3E + p * 0x18, 1, (0x7F, 0x80, 0xFE)) for p in (0, 63)))
SEQ_FIELDS = (
    Field("type", 0, 1, (0, 2, 4, 0xFF)), Field("version", 1, 1, (0, 1, 2, 3, 4, 0x80, 0xFF)),
    *(Field(f"h{o:02X}w", o, 2) for o in range(2, 0x20, 2)),
    *(Field(f"h{o:02X}d", o, 4) for o in range(2, 0x20, 2)),
    Field("name", 0x0B, 17))
ALL_FIELDS = (
    Field("type", 0, 1, (0, 3, 5, 0xFF)), Field("version", 1, 1, (0, 1, 2, 3, 4, 0x80, 0xFF)),
    *(Field(f"h{o:02X}w", o, 2) for o in range(2, 0x24, 2)),
    *(Field(f"h{o:02X}d", o, 4) for o in range(2, 0x24, 2)),
    Field("name", 0x10, 17))
PAR_FIELDS = (
    Field("type", 0, 1, (0, 7, 9, 0xFF)), Field("version", 1, 1, (0, 1, 2, 0x80, 0xFF)),
    Field("length", 2, 2, (0, 1, 0x6C1, 0x6C2, 0x6C3, 0x7FFF, 0x8000, 0xFFFF)),
    *(Field(f"b{o:03X}", o, 1) for o in range(4, 0x6C6, 9)))
SET_FIELDS = (
    Field("type", 0, 1, (0, 1, 3, 5, 0xFF)), Field("version", 1, 1, (0, 1, 2, 0xFF)),
    Field("h2", 2, 1), Field("h3", 3, 2),
    *(Field(f"entry{i}.name", 5 + i * 0x3B, 17) for i in (0, 1, 33)),
    *(Field(f"entry{i}.d{d:02X}", 5 + i * 0x3B + d, 4) for i in (0, 33) for d in range(0x11, 0x3B, 4)))
MID_FIELDS = (
    Field("hdr_len", 4, 4, (0, 5, 7, 0xFFFFFFFF)), Field("format", 8, 2, (0, 1, 2, 3, 0xFFFF)),
    Field("ntrks", 10, 2, (0, 1, 2, 3, 0x40, 0xFFFF)), Field("division", 12, 2, (0, 1, 0x7FFF, 0x8000, 0xE728)),
    Field("trk0_len", 18, 4, (0, 1, 0x7FFFFFFF, 0xFFFFFFFF)), Field("trk1_len", 22 + 19 + 4, 4),
    Field("tempo", 22 + 4, 4))


def formats(fixtures: Path) -> dict[str, Format]:
    return {
        "SND": Format("SND", lambda f: base_snd(), SND_FIELDS, structures=((0x26, 2205 * 2),)),
        "PGM": Format("PGM", lambda f: base_pgm(), PGM_FIELDS, confirm=((T_CONFIRM, "soft1"),),
                      exercise="pads", companion=True, structures=((0x2, 0x880), (0x882, 0x200), (0xA82, 0x77E))),
        "APS": Format("APS", base_aps, APS_FIELDS, confirm=((T_CONFIRM, "soft1"),), exercise="pads",
                      companion=True, structures=((7, 0x13C), (7 + 0x13C, 0x77E * 24))),
        "SEQ": Format("SEQ", lambda f: _fixture("fuzz-SEQ01.SEQ", f), SEQ_FIELDS,
                      confirm=((T_CONFIRM, "soft1"),), exercise="play"),
        "ALL": Format("ALL", lambda f: _fixture("fuzz-ALL_SEQS.ALL", f), ALL_FIELDS,
                      confirm=((T_CONFIRM, "1"), (T_CONFIRM2, "soft1")), exercise="play"),
        "PAR": Format("PAR", lambda f: _fixture("fuzz-PARAMS.PAR", f), PAR_FIELDS, confirm=((T_CONFIRM, "soft1"),)),
        "SET": Format("SET", lambda f: base_set(2), SET_FIELDS, confirm=((T_CONFIRM, "1"), (T_CONFIRM2, "soft1"), (T_CONFIRM3, "soft1"), (T_CONFIRM4, "soft1")), exercise="pads"),
        "ST1": Format("ST1", lambda f: base_set(5), SET_FIELDS, confirm=((T_CONFIRM, "1"), (T_CONFIRM2, "soft1"), (T_CONFIRM3, "soft1"), (T_CONFIRM4, "soft1")), exercise="pads"),
        "MID": Format("MID", lambda f: base_smf(), MID_FIELDS, confirm=((T_CONFIRM, "soft1"),), exercise="play"),
    }

# --------------------------------------------------------------------------
# Mutations (JSON-serializable operation lists)

INTERESTING = {1: (0, 1, 0x7F, 0x80, 0xFE, 0xFF),
               2: (0, 1, 0x7FFF, 0x8000, 0xFFFE, 0xFFFF),
               4: (0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFE, 0xFFFFFFFF, 0x00FFFFFF, 0x01000000, 0x10000)}


def apply(base: bytes, ops: list) -> bytes:
    data = bytearray(base)
    for op in ops:
        kind = op[0]
        if kind == "set":
            _, off, width, value = op
            if off + width <= len(data):
                data[off:off + width] = int(value).to_bytes(width, "little")
        elif kind == "bytes":
            _, off, hexs = op
            raw = bytes.fromhex(hexs)
            if off < len(data):
                data[off:off + len(raw)] = raw[:max(0, len(data) - off)]
        elif kind == "trunc":
            del data[op[1]:]
        elif kind == "append":
            data += bytes.fromhex(op[1])
        elif kind == "flip":
            _, off, mask = op
            if off < len(data):
                data[off] ^= mask
        elif kind == "fill":
            _, off, n, b = op
            end = min(len(data), off + n)
            data[off:end] = bytes([b]) * max(0, end - off)
        else:
            raise ValueError(op)
    return bytes(data)


def _field_value(rng: random.Random, f: Field, cur: int) -> int:
    pool = list(INTERESTING.get(f.width, ())) + list(f.values)
    choice = rng.random()
    if choice < 0.6 and pool:
        return rng.choice(pool)
    if choice < 0.8:
        return (cur + rng.choice((-1, 1, -2, 2, 0x100, -0x100))) & ((1 << (8 * f.width)) - 1)
    return rng.getrandbits(8 * f.width)


def _name_bytes(rng: random.Random) -> str:
    kind = rng.randrange(5)
    if kind == 0:
        raw = bytes(rng.randrange(0x21, 0x7F) for _ in range(17))          # no NUL
    elif kind == 1:
        raw = bytes(17)                                                     # empty
    elif kind == 2:
        raw = bytes(rng.randrange(0x80, 0x100) for _ in range(16)) + b"\0"  # high bytes
    elif kind == 3:
        raw = b"FZSND".ljust(17, b"\0")                                    # duplicate of companion
    else:
        raw = bytes([0x20]) * 16 + b"\0"                                    # blanks
    return raw.hex()


def generate(fmt: Format, base: bytes, rng: random.Random) -> list:
    ops = []
    for _ in range(rng.choice((1, 1, 1, 2, 2, 3, 4))):
        r = rng.random()
        if r < 0.55 and fmt.fields:
            f = rng.choice(fmt.fields)
            if f.off >= len(base):
                continue
            if f.width == 17:
                ops.append(["bytes", f.off, _name_bytes(rng)])
            else:
                cur = int.from_bytes(base[f.off:f.off + f.width], "little")
                ops.append(["set", f.off, f.width, _field_value(rng, f, cur)])
        elif r < 0.70:
            cuts = [0, 1, 2, 3, len(base) - 1, len(base) // 2] + [f.off for f in fmt.fields] + \
                   [o + n for o, n in fmt.structures] + [o for o, _ in fmt.structures]
            cut = rng.choice(cuts) if rng.random() < 0.7 else rng.randrange(len(base))
            ops.append(["trunc", max(0, min(cut, len(base)))])
        elif r < 0.78:
            ops.append(["append", bytes(rng.getrandbits(8) for _ in range(rng.choice((1, 16, 512, 4096)))).hex()])
        elif r < 0.90:
            region = rng.choice(fmt.structures) if fmt.structures and rng.random() < 0.7 else (0, len(base))
            for _ in range(rng.choice((1, 4, 16))):
                off = region[0] + rng.randrange(max(1, min(region[1], len(base) - region[0])))
                ops.append(["flip", off, 1 << rng.randrange(8)])
        else:
            region = rng.choice(fmt.structures) if fmt.structures else (0, len(base))
            off = region[0] + rng.randrange(max(1, region[1]))
            ops.append(["fill", off, rng.choice((2, 17, 0x18, 64, 512)), rng.choice((0, 0xFF, 0x80, 0x7F))])
    return ops or [["flip", rng.randrange(len(base)), 1]]

# --------------------------------------------------------------------------
# MAME runner


ORACLE_LUA = r'''
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT")
local function now() return machine.time:as_double() end
local function phys(seg, off)
  local a = ((seg << 4) + off) & 0xfffff
  if cpu.state["XA"].value ~= 0 then
    return ((iosp:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
  end
  return a
end
local IMG = 0x300000 + LOAD_SEG * 16
local function blocks()
  local t = {}
  for b = 0, (IMAGE_CODE_END // 1024) - 1 do
    local h = 0
    local base = IMG + b * 1024
    for i = 0, 1020, 4 do h = (h * 31 + prog:read_u32(base + i)) & 0xffffffff end
    t[b] = h
  end
  return t
end
local res = {errors = {}, badpc = {}, port6a = -1, fedit_after = 0, blank = false}
local keep = {}
keep[#keep + 1] = iosp:install_write_tap(0x6a, 0x6b, "fz6a", function(o, d, m)
  if m & 0xff ~= 0 then res.port6a = d & 0xff end
end)
local function exec(seg, off, name, fn)
  local cs = (LOAD_SEG + seg) & 0xffff
  local p = 0x300000 + ((cs * 16 + off) & 0xfffff)
  keep[#keep + 1] = prog:install_read_tap(p & ~1, p | 1, name, function()
    local ps = cpu.state["PS"].value
    if ps == cs and ((cpu.state["CURPC"].value - (ps << 4)) & 0xffff) == off then fn() end
  end)
end
local last_box = -1
exec(0x063B, 0x000B, "fzbox", function()
  local sp = cpu.state["SP"].value
  local code = prog:read_u16(phys(cpu.state["SS"].value, (sp + 4) & 0xffff))
  if now() > T0 and (#res.errors == 0 or res.errors[#res.errors] ~= code or now() - last_box > 0.5) then
    res.errors[#res.errors + 1] = code
    last_box = now()
  end
end)
local last_fedit = -1
exec(0x02D7, 0x0357, "fzfedit", function()
  if now() > T_MAIN3 then res.fedit_after = res.fedit_after + 1 end
end)
local before, done, loadsample = nil, false, false
local seen_ps = {}
res.busy_load = -1
emu.register_periodic(function()
  local t = now()
  if t < T0 then return end
  if not before then before = blocks() end
  if not loadsample and t >= T_LOADSAMPLE then
    loadsample = true
    local dg = (LOAD_SEG + DGROUP) & 0xffff
    res.busy_load = prog:read_u8(phys(dg, 0x9444))
  end
  local ps = cpu.state["PS"].value
  local rel = (ps - LOAD_SEG) & 0xffff
  local ok = (rel < (EXTENT // 16)) or (rel >= 0x7E00 and rel < 0x7E00 + 0x700) or ps >= 0xF000
  if not ok and not seen_ps[ps] then
    seen_ps[ps] = true
    res.badpc[#res.badpc + 1] = string.format("%04X:%04X@%.3f", ps, (cpu.state["CURPC"].value - (ps << 4)) & 0xffff, t)
  end
  if not done and t >= T_END - 0.3 then
    done = true
    local after = blocks()
    res.changed = {}
    for b, h in pairs(before) do if after[b] ~= h then res.changed[#res.changed + 1] = b end end
    local dg = (LOAD_SEG + DGROUP) & 0xffff
    res.busy = prog:read_u8(phys(dg, 0x9444))
    -- sound directory invariants
    local ss = (LOAD_SEG + SND_SEG) & 0xffff
    local function rd(seg, off, n) local v = 0; for i = n - 1, 0, -1 do v = (v << 8) | prog:read_u8(phys(seg, off + i)) end; return v end
    res.sounds, res.bad_sounds = 0, {}
    local used = {}
    for i = 0, 127 do
      local o = 0x4800 + i * 0x24
      if prog:read_u8(phys(ss, o)) ~= 0 then
        res.sounds = res.sounds + 1
        used[i] = true
        local nul, printable = false, true
        for k = 0, 16 do local c = prog:read_u8(phys(ss, o + k)); if c == 0 then nul = true; break end; if c < 0x20 or c > 0x7e then printable = false end end
        local st, s, e, len, w = prog:read_u8(phys(ss, o + 0x13)), rd(ss, o + 0x14, 4), rd(ss, o + 0x18, 4), rd(ss, o + 0x1c, 4), rd(ss, o + 0x20, 4)
        local why = {}
        if not nul then why[#why + 1] = "name-unterminated" end
        if not printable then why[#why + 1] = "name-unprintable" end
        if st > 1 then why[#why + 1] = "stereo=" .. st end
        if s > e then why[#why + 1] = "start>end" end
        if e > len then why[#why + 1] = "end>length" end
        if len == 0 then why[#why + 1] = "length=0" end
        if w + len * (st + 1) > WAVE_WORDS then why[#why + 1] = string.format("wave %X+%X beyond memory", w, len) end
        if #why > 0 then res.bad_sounds[#res.bad_sounds + 1] = string.format("%d:%s", i, table.concat(why, ",")) end
      end
    end
    -- current program note records (far pointer DGROUP E2E6)
    local poff, pseg = rd(dg, 0xE2E6, 2), rd(dg, 0xE2E8, 2)
    res.bad_notes = {}
    for p = 0, 63 do
      local idx = prog:read_u8(phys(pseg, poff + 0x3e + p * 0x18))
      if idx ~= 0xff and (idx > 127 or not used[idx]) then res.bad_notes[#res.bad_notes + 1] = string.format("%d:%02X", p, idx) end
    end
    local f = assert(io.open(out .. "/oracle.json", "w"))
    local function arr(t, q) local s = {}; for _, v in ipairs(t) do s[#s + 1] = q and string.format("%q", v) or tostring(v) end; return "[" .. table.concat(s, ",") .. "]" end
    f:write(string.format('{"errors":%s,"badpc":%s,"port6a":%d,"fedit_after":%d,"changed":%s,"busy":%d,"busy_load":%d,"sounds":%d,"bad_sounds":%s,"bad_notes":%s}\n',
      arr(res.errors), arr(res.badpc, true), res.port6a, res.fedit_after, arr(res.changed), res.busy, res.busy_load, res.sounds, arr(res.bad_sounds, true), arr(res.bad_notes, true)))
    f:close()
  end
end)
fz_keep = keep
'''


def _taps(*items, hold=0.1):
    return [ev for at, key in items for ev in key_tap(key, at, hold)]


@dataclass
class Runner:
    out: Path
    bios: str = "v311"
    sys_path: Path = M3K316
    board_mb: int = 2
    rompath: Path | None = None
    _snap: tuple | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def load_segment(self) -> int:
        """Where 3.16 runs: the loader's segment for stock M3K316.SYS (MZ entry
        0000:0000); RUNTIME_PMONEY for a PMONEY build (entry in the cave), which
        entry316 moves there on every set."""
        raw = self.sys_path.read_bytes()
        entry_cs = int.from_bytes(raw[0x16:0x18], "little")
        return RUNTIME_PMONEY if entry_cs else LOAD_SEGMENTS[self.bios]

    def _disk(self, name: str, files: list[tuple[bytes, str]], startup: bool) -> Path:
        tmp = self.out / "files"
        tmp.mkdir(parents=True, exist_ok=True)
        real = [(self.sys_path, "STARTUP.SYS")] if startup else []
        for data, dos in files:
            p = tmp / f"{name}-{dos}"
            p.write_bytes(data)
            real.append((p, dos))
        img = fat_disk(f"fuzz-{name}", real)
        # zero directory bytes +0Ch..+13h (EPROM loaders read them as name characters)
        b = bytearray(img.read_bytes())
        for e in range(0x2600, 0x2600 + 224 * 32, 32):
            if b[e] not in (0, 0xE5):
                b[e + 0x0C:e + 0x14] = bytes(8)
        dest = self.out / "disks" / f"{name}.img"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes(b))
        img.unlink(missing_ok=True)
        return dest

    def snapshot(self) -> tuple[Path, Path, float]:
        with self._lock:
            if self._snap:
                return self._snap
            key = hashlib.sha256(self.sys_path.read_bytes() + self.bios.encode()
                                 + str(self.board_mb).encode()).hexdigest()[:12]
            d = self.out / "snapshots" / f"{self.bios}-{key}"
            if not (d / "boot.lcd").exists():
                boot = self._disk(f"boot-{key}", [], startup=True)
                env = {"PROBE_SAVE_AT": str(SNAP_AT), "PROBE_SAVE_NAME": "boot", "PROBE_SAVE_LCD": str(d / "boot.lcd")}
                events = _taps((33.0, "soft4"))
                run(self.bios, [SNAP_AT + 0.3], d / "run", floppy=boot, board_mb=self.board_mb,
                    panel=write_smf(self.out / f"snap-{key}.mid", events), rompath=self.rompath,
                    extra=["-state_directory", str(d / "states")], env=env)
                if not (d / "boot.lcd").exists():
                    raise RuntimeError(f"snapshot not written: {d}")
            self._snap = (d / "states", d / "boot.lcd", SNAP_AT)
            return self._snap

    def case(self, name: str, fmt: Format, data: bytes) -> dict:
        states, lcd, _ = self.snapshot()
        files = [(data, f"FZ.{fmt.ext}")]
        if fmt.companion:
            files.append((companion_snd(), "FZSND.SND"))
        img = self._disk(name, files, startup=False)
        events = _taps((T_DISK, "disk"), (T_SEVEN, "7"), (T_LOAD, "soft1"), *fmt.confirm,
                       (T_MAIN1, "main_screen"), (T_MAIN2, "main_screen"))
        if fmt.exercise == "play":
            events += _taps((T_EXERCISE, "play_start"), (T_EXERCISE + 3.0, "stop"))
        elif fmt.exercise == "pads":
            for k in range(8):
                events += pad_hit(panel_pad(1 + k), T_EXERCISE + 0.4 * k)
        events += _taps((T_MAIN3, "main_screen"))
        case_dir = self.out / "cases" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        L = self.load_segment
        wave_words = {2: 0x100000, 8: 0x400000, 32: 0x1000000}[self.board_mb]
        script = case_dir.parent / f"{name}.lua"
        script.write_text("\n".join([
            f"LOAD_SEG = 0x{L:04X}", f"DGROUP = 0x{DGROUP:04X}", f"SND_SEG = 0x{SND_SEG:04X}",
            f"IMAGE_CODE_END = 0x{IMAGE_CODE_END:X}", f"EXTENT = 0x{EXTENT:X}", f"WAVE_WORDS = 0x{wave_words:X}",
            f"T0 = {SNAP_AT + 0.2}", f"T_MAIN3 = {T_MAIN3}", f"T_END = {T_END}", f"T_LOADSAMPLE = {T_MAIN1 - 0.5}",
            "do", ORACLE_LUA, "end", f'dofile("{(Path(__file__).resolve().parent / "probe.lua").as_posix()}")']) + "\n")
        times = [T_CONFIRM - 0.2, T_CONFIRM2 - 0.2, T_CONFIRM3 - 0.2, T_CONFIRM4 - 0.2, T_MAIN1 - 0.2, T_END]
        result = {"name": name, "type": fmt.ext, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        try:
            screens = run(self.bios, times, case_dir / "mame", floppy=img, panel=write_smf(case_dir / "panel.mid", events),
                          rompath=self.rompath, board_mb=self.board_mb,
                          extra=["-autoboot_script", str(script), "-state_directory", str(states), "-state", "boot"],
                          env={"PROBE_LCD_SEED": str(lcd), "PROBE_REINSERT": "1"})
        except RuntimeError as exc:
            result.update(verdict=["crash"], detail=f"MAME: {exc}")
            return result
        oracle_path = case_dir / "mame" / "oracle.json"
        oracle = json.loads(oracle_path.read_text()) if oracle_path.exists() else None
        result["screens"] = [s["rows"] for s in screens]
        result["oracle"] = oracle
        return result


def classify(result: dict, mask: set[int]) -> list[str]:
    if "verdict" in result:
        return result["verdict"]
    o = result.get("oracle")
    if o is None:
        return ["crash"]
    v = []
    text = "\n".join("\n".join(rows) for rows in result["screens"])
    if o["badpc"] or "System Error" in text or "software bug" in text:
        v.append("crash")
    final = result["screens"][-1]
    if "Play/Record" not in final[0] and o["fedit_after"] == 0:
        v.append("hang")
    # Image-block diffs below DGROUP are only trusted with a corroborating
    # control-flow signal: the loaders legitimately rewrite the program table
    # and sound-record working area (image blocks ~288-350) with file content.
    LOADER_DATA = set(range(288, 352))
    extra = set(o["changed"]) - mask
    if extra and ("crash" in v or extra - LOADER_DATA):
        v.append("corrupt-code")
    if o["bad_sounds"]:
        v.append("corrupt-sound")
    if o["bad_notes"]:
        v.append("corrupt-program")
    if o.get("busy_load", 0) != 0:
        v.append("leak-busy")
    if o["port6a"] == 0:
        v.append("leak-mute")
    for rows in result["screens"]:
        if "Attention!" in rows[0] and not any(r.strip(" .") for r in rows[1:6]):
            v.append("blankmsg")
            break
    return v or ["ok"]

# --------------------------------------------------------------------------
# Campaign


def seeds(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def case_ops(fmt: Format, base: bytes, seed: int) -> list:
    return generate(fmt, base, random.Random(f"{fmt.ext}:{seed}"))


def load_mask(out: Path) -> set[int]:
    path = out / "baseline-mask.json"
    return set(json.loads(path.read_text())) if path.exists() else set()


def cmd_baseline(args, runner: Runner, fmts: dict) -> None:
    jobs = {f"base-{t}-{k}": t for t in args.types for k in range(args.repeat)}
    with ThreadPoolExecutor(args.workers) as pool:
        res = dict(zip(jobs, pool.map(lambda kv: runner.case(kv[0], fmts[kv[1]], fmts[kv[1]].base(args.fixtures)),
                                      jobs.items())))
    mask = load_mask(runner.out)
    for name, r in res.items():
        if r.get("oracle"):
            mask |= set(r["oracle"]["changed"])
    (runner.out / "baseline-mask.json").write_text(json.dumps(sorted(mask)))
    for name, r in res.items():
        print(name, classify(r, mask), r.get("oracle", {}) and {k: r["oracle"][k] for k in ("errors", "busy", "sounds")})
        for rows in r.get("screens", [])[-2:]:
            print("   |" + "|\n   |".join(rows) + "|")


def cmd_run(args, runner: Runner, fmts: dict) -> list[dict]:
    mask = load_mask(runner.out)
    jobs = []
    for t in args.types:
        base = fmts[t].base(args.fixtures)
        for s in seeds(args.seeds):
            ops = case_ops(fmts[t], base, s)
            jobs.append((t, s, ops, apply(base, ops)))

    def go(job):
        t, s, ops, data = job
        r = runner.case(f"{t}-{s}", fmts[t], data)
        r.update(seed=s, ops=ops, verdict=classify(r, mask))
        r.pop("screens_full", None)
        with open(runner.out / "results.jsonl", "a") as f:
            f.write(json.dumps({k: r[k] for k in ("name", "type", "seed", "ops", "verdict", "bytes")}
                               | {"oracle": r.get("oracle"), "final": r.get("screens", [[]])[-1]}) + "\n")
        print(f"{t}-{s}: {r['verdict']} errors={r.get('oracle') and [hex(e) for e in r['oracle']['errors']]}", flush=True)
        return r
    with ThreadPoolExecutor(args.workers) as pool:
        return list(pool.map(go, jobs))


def cmd_minimize(args, runner: Runner, fmts: dict) -> None:
    mask = load_mask(runner.out)
    fmt = fmts[args.type]
    base = fmt.base(args.fixtures)
    ops = json.loads(args.ops) if args.ops else case_ops(fmt, base, args.seed)
    want = set(json.loads(args.want)) if args.want else None
    first = runner.case(f"min-{args.type}-{args.seed}-full", fmt, apply(base, ops))
    target = set(classify(first, mask)) - {"ok"} if want is None else want
    if not target:
        print("case does not fail; nothing to minimize"); return
    n = 0
    changed = True
    while changed and len(ops) > 1:
        changed = False
        for i in range(len(ops)):
            trial = ops[:i] + ops[i + 1:]
            n += 1
            r = runner.case(f"min-{args.type}-{args.seed}-{n}", fmt, apply(base, trial))
            if target & set(classify(r, mask)):
                ops, changed = trial, True
                break
    data = apply(base, ops)
    dest = runner.out / "minimal" / f"{args.type}-{args.seed}.{fmt.ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    (dest.with_suffix(".json")).write_text(json.dumps({"type": args.type, "seed": args.seed, "ops": ops,
                                                       "verdict": sorted(target)}, indent=1))
    print(json.dumps({"minimal_ops": ops, "file": str(dest), "verdict": sorted(target)}))


def cmd_fixtures(args, runner: Runner) -> None:
    """Save SEQ, ALL, PAR (and APS) with the stock Disk UI of the booted OS."""
    raise SystemExit("fixture generation: see the report (fx_make.py); copy the stock-saved files to "
                     f"{args.fixtures}/fuzz-SEQ01.SEQ, fuzz-ALL_SEQS.ALL, fuzz-PARAMS.PAR, fuzz-ALL_PGMS.APS")


def cmd_smoke(args, runner: Runner, fmts: dict) -> int:
    """Deterministic release-gate smoke: a fixed seed set + the minimal corrupt-PGM
    fixture, run on the given --sys.  Prints one line per case and returns non-zero
    if any case is crash/hang/corrupt-code (gate-fatal).  Does not need a baseline
    (those classes are mask-independent)."""
    mask = load_mask(runner.out)
    cases = []
    for t, seeds_ in SMOKE_SEEDS.items():
        if t not in fmts:
            continue
        base = fmts[t].base(args.fixtures)
        for s in seeds_:
            cases.append((f"{t}-{s}", t, apply(base, case_ops(fmts[t], base, s))))
    # the minimal corrupt-PGM name-overflow fixture (report C1/C3)
    pbase = fmts["PGM"].base(args.fixtures)
    cases.append(("PGM-nameoverflow", "PGM", apply(pbase, [["fill", 401, 64, 0x80]])))

    def go(job):
        name, t, data = job
        r = runner.case(f"smoke-{name}", fmts[t], data)
        v = classify(r, mask)
        if not mask:
            v = [x for x in v if x != "corrupt-code"] or ["ok"]   # corrupt-code needs a baseline
        return name, v

    from concurrent.futures import ThreadPoolExecutor
    bad = 0
    with ThreadPoolExecutor(min(args.workers, 2)) as pool:
        for name, verdict in pool.map(go, cases):
            fatal = SMOKE_FAIL & set(verdict)
            print(f"{'FAIL' if fatal else 'ok  '} smoke {name}: {verdict}", flush=True)
            bad += bool(fatal)
    print(f"smoke: {len(cases)} cases, {bad} gate-fatal")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("run", "baseline", "minimize", "repro", "fixtures", "smoke"))
    ap.add_argument("--types", default="SND,PGM,APS,SEQ,ALL,PAR,SET,ST1,MID")
    ap.add_argument("--type")
    ap.add_argument("--seeds", default="0-19")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ops")
    ap.add_argument("--want")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--bios", default="v311")
    ap.add_argument("--sys", type=Path, default=M3K316)
    ap.add_argument("--board", type=int, default=2)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--fixtures", type=Path, default=FIXTURES)
    ap.add_argument("--rompath", type=Path)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MPC3K_WORKERS", "6")))
    args = ap.parse_args(argv)
    args.types = [t.strip().upper() for t in args.types.split(",") if t.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    runner = Runner(args.out.resolve(), args.bios, args.sys.resolve(), args.board,
                    args.rompath.resolve() if args.rompath else None)
    fmts = formats(args.fixtures)
    if args.command == "baseline":
        cmd_baseline(args, runner, fmts)
    elif args.command == "run":
        cmd_run(args, runner, fmts)
    elif args.command in ("minimize",):
        cmd_minimize(args, runner, fmts)
    elif args.command == "repro":
        fmt = fmts[args.type]
        base = fmt.base(args.fixtures)
        ops = json.loads(args.ops) if args.ops else case_ops(fmt, base, args.seed)
        r = runner.case(f"repro-{args.type}-{args.seed}", fmt, apply(base, ops))
        print(json.dumps({"ops": ops, "verdict": classify(r, load_mask(runner.out)), "oracle": r.get("oracle"),
                          "screens": r.get("screens")}, indent=1))
    elif args.command == "smoke":
        return cmd_smoke(args, runner, fmts)
    else:
        cmd_fixtures(args, runner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
