#!/usr/bin/env python3
"""Build WAVE316.SYS: the WAVE / CHOP / mute-group mods on OS 3.16 ("Route C").

    python3 mods/build_wave316.py [--sound FILE.SND ...] [--out DIR]

One DOS MZ file for every MPC3000, whatever its EPROM (3.08, 3.11, 3.12,
Vailixi 3.50): each EPROM's floppy loader loads it exactly like the stock
M3K316.SYS it is built from.  It holds no EPROM bytes.  Design, evidence and
the address map: notes/port_316.md.  Inputs: 07-rom/.../M3K316.SYS (hash
pinned), mods/WAVE316.args (hook patches in 3.16 load-image offsets) and the
shared cave source assembled with -DPROFILE_316.

Before anything is written the build is checked by re-doing each EPROM
loader's work (route_c.load) and the cave's entry316 in Python at both load
segments (run_entry).  entry316 must assemble to the routine modelled here
(ENTRY316, constants ENTRY316_FIXED).  With L = 7000 (3.08, 3.11) it moves the
image to L = 6900 through the relocation table route_c.build appends after the
cave (every MZ-relocated word -700h, the image copied down, the loader's
records of L rebased), so every set ends with the same memory: the final
simulated memory and registers at 3.16's entry must be identical for 6900 and
7000.  Its copy count must cover the cave, the home at 6900 + CAVE_HOME must
end below page 61, the home must then hold the relocated cave and the pool
end must be L-1 - SCSI_STK_PARAS = 67DF (the SCSI reader's private stack sits
between the pool and the image).  Every hook must
land on its cave label at the cave's home and every cave far CALL/JMP on
3.16 code outside the data segments.  Every relocated word must be a known
segment (0000, FFFF and 4853 only at their entry316 sites) and no other
word may equal one (NOT_OPERANDS lists the proven coincidences).  Every
stock target the cave calls must start, in the bytes that run, with the
same instruction shapes as the Vailixi 3.50 routine it is named after; it
may not reach into hook bytes unless it is a hook site (HOOK_TARGETS),
whose stock bytes are compared.  ndisasm cannot decode BRKXA/RETXA, so a
compared instruction holding 0F E0 / 0F F0 is an error.

Writes <out>/WAVE316.SYS, WAVE316.img (STARTUP.SYS plus test sounds),
WAVE316.json, wave316.cave.bin and wave316.cave.map.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mods import buildkit as kit  # noqa: E402
from mods import build_mod_sys as mod  # noqa: E402
from mods import route_c as rc  # noqa: E402
from emu.snd import sine441, snd, stereo1  # noqa: E402

ROOT = kit.ROOT
M3K316 = ROOT / "07-rom" / "v3.16 maintenance upgrade" / "M3K316.SYS"
M3K316_SHA256 = "cf997046c35d5eb720cd277f235f5503eba3e53c8518a7d3a782dd087fbde226"
ARGS = ROOT / "mods" / "WAVE316.args"
PROFILE = ROOT / "mods" / "profile_316.inc"
DEFINE = "PROFILE_316"
CAVE_HOME = 0x7E00              # must equal CAVE_HOME in profile_316.inc
DGROUP_316 = 0x609C             # 3.16 DGROUP relative segment
CODE_END = DGROUP_316 * 16      # 3.16 code and far data lie below DGROUP
POOL_IMM = 0x48535              # MOV BX,6FFFh immediate the entry adjusts
POOL_END = 0x6FFF               # its stock value
SHAPE_INSNS = 6                 # instructions compared per stock target
HOOK_TARGETS = frozenset({"T_D0C0_0B19", "T_D0C0_0D17", "T_B1B1_005B", "T_D21F_0008", "T_CF92_000C"})   # targets that are a hook site: the cave calls through the hook
OUT = mod.OUT

# entry316 as assembled, one NASM listing line per instruction.  {name} is the
# instruction's trailing immediate, which verify() reads and runs.
ENTRY316 = (
    # L <= UNIV_SEG: copy the cave home, set the pool end, jump to 3.16
    "fc", "ba{dx}", "81fa{univ_m1}", "773b", "0e", "1f", "b8{home}", "8ec0", "31f6", "31ff",
    "b9{count}", "f3a5", "b8{pool_seg}", "8ec0", "bb{pool_off}", "26807fff{pool_opcode}", "750f",
    "26813f{pool_word}", "7508", "89d0", "2d{pool_room}", "268907", "b84000", "8ed8",
    "ea0000{start_seg}", "f4", "ebfd",
    # .move: D = L - UNIV_SEG, halt below the table's least D
    "89d3", "81eb{univ_m1_move}", "2e3b1e{t_dmin}", "72f0", "8cc8", "8ed8", "be{t_records}",
    "8b0e{t_count}", "89d0", "40", "8ec0", "31ff",
    # a. re-relocate: every relocated word -D
    "ac", "b400", "84c0", "7518", "ad", "85c0", "7513", "83c7{skip}", "89f8", "c1e804", "83e70f",
    "8cc2", "01d0", "8ec0", "eb13", "01c7", "89f8", "c1e804", "83e70f", "8cc2", "01d0", "8ec0",
    "26291d", "e2cc",
    # b. copy N paragraphs from L:0 to UNIV_SEG:0 in chunks
    "8b16{t_paras}", "b8{univ_mv}", "8ec0", "01d8", "8ed8", "b9{chunk}", "39ca", "7302", "89d1",
    "29ca", "c1e103", "31f6", "31ff", "f3a5", "8cd8", "05{chunk_ds}", "8ed8", "8cc0", "05{chunk_es}",
    "8ec0", "85d2", "75da",
    # c. the loader's records of L: 0040:640A, 0040:68C2, SS
    "b84000", "8ed8", "b8{univ_bios}", "01d8", "3906{bios_load}", "7504", "291e{bios_load2}",
    "8cc8", "3906{bios_jmp}", "7504", "291e{bios_jmp2}", "8cd0", "29d8", "8ed0",
    # d. far jump to .moved in the moved copy
    "b8{moved}", "2ea3{moved_ptr}", "8cc8", "29d8", "2ea3{moved_seg}", "2eff2e{moved_jmp}",
    # .moved: zero the D paragraphs above UNIV_SEG + N, restart entry316
    "8cc8", "8ed8", "b8{univ_zero}", "0306{t_paras2}", "8ec0", "31c0", "31ff", "b9{zchunk}", "39cb",
    "7302", "89d9", "29cb", "c1e103", "f3ab", "8cc2", "81c2{zchunk_es}", "8ec2", "85db", "75e2",
    "e9{restart}")

# The values verify() requires of the ENTRY316 immediates that are not run
# from memory: {name: (value, what)}.  Table pointers are filled in from the
# reloc_table label.
ENTRY316_FIXED = {"univ_m1": rc.UNIV - 1, "univ_m1_move": rc.UNIV - 1, "univ_mv": rc.UNIV,
                  "univ_bios": rc.UNIV, "univ_zero": rc.UNIV, "skip": rc.SKIP & 0xFF,
                  "chunk": 0x800, "chunk_ds": 0x800, "chunk_es": 0x800, "zchunk": 0x800,
                  "zchunk_es": 0x800, "bios_load": rc.BIOS_LOAD_SEG - 0x400,
                  "bios_load2": rc.BIOS_LOAD_SEG - 0x400, "bios_jmp": rc.BIOS_JMP_SEG - 0x400,
                  "bios_jmp2": rc.BIOS_JMP_SEG - 0x400}

# Unrelocated cave words equal to a segment value that are instruction bytes,
# not operands: (mnemonic, instruction's first bytes, word position in them).
NOT_OPERANDS = (("cmp", "2e3b06", 1),   # CMP AX,[CS:disp16]: opcode 3B and ModRM 06
                ("mov", "ba20", 0),     # MOV DX,0020h (BOT-TOP+1 rows): opcode BA and the immediate's low byte
                ("call", "9a", 1),      # CALL FAR's offset word; its segment word (position 3) is the relocated one
                ("mov", "bb0900", 1),   # MOV BX,9 in draw: the sound name's text column, equal to segment 0009
                ("mov", "2e8a14", 1),   # MOV DL,[CS:SI]: opcode 8A and ModRM 14, equal to segment 148A
                ("mov", "368a14", 1),   # MOV DL,[SS:SI]: the same bytes after an SS prefix
                ("call", "e8", 1),      # near CALL rel16: a displacement, never a segment
                ("mov", "bf47", 0),     # MOV DI,2C47h (mu_grid+8): opcode BF and the immediate's low byte
                ("db", "5a4f4e45303030", 3))  # "ZONE000" (chop_name): text "E0" equals segment 3045 (T_DA1A_000D)


def _profile_values() -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """T_ targets (relative seg:off) and plain equ constants of profile_316.inc."""
    text = PROFILE.read_text()
    targets = {m[1]: (int(m[2], 16), int(m[3], 16)) for m in re.finditer(
        r"^%define (T_[0-9A-F]{4}_[0-9A-F]{4}) 0x([0-9A-F]+):0x([0-9A-F]+)", text, re.M)}
    consts = {m[1]: int(m[2], 16) for m in re.finditer(r"^(\w+)\s+equ\s+0x([0-9A-Fa-f]+)", text, re.M)}
    return targets, consts


def _shape(data: bytes, start: int, origin: int, count: int) -> list[tuple[int, str]]:
    """(length, mnemonic) of the first `count` instructions at data[start].

    Their bytes may not hold 0F E0 / 0F F0 (BRKXA/RETXA), which ndisasm decodes wrongly.
    """
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(data[start:start + 64]); f.flush()
        out = subprocess.run(["ndisasm", "-b", "16", "-o", hex(origin), f.name],
                             capture_output=True, text=True, check=True).stdout
    shape, code = [], bytearray()
    for line in out.splitlines():
        parts = line.split(None, 2)
        if parts[0].startswith("-"):    # ndisasm continues an instruction longer than 8 bytes
            more = bytes.fromhex(parts[0][1:])
            shape[-1] = (shape[-1][0] + len(more), shape[-1][1])
            code += more
            continue
        if len(shape) == count or shape and shape[-1][1] in ("ret", "retf", "iret", "jmp"):
            break                       # what follows a return or jump may be data (jump tables)
        shape.append((len(parts[1]) // 2, parts[2].split()[0] if len(parts) > 2 else ""))
        code += bytes.fromhex(parts[1])
    if re.search(rb"\x0f[\xe0\xf0]", code):
        raise ValueError(f"0x{origin:04X}: compared bytes {code.hex()} hold 0F E0 / 0F F0 (BRKXA/RETXA)")
    return shape


def check_targets(stock: bytes, patched: bytes, patches: list[rc.Patch], targets: dict[str, tuple[int, int]],
                  used: set[str], on_hook: frozenset[str] = HOOK_TARGETS) -> list[dict]:
    """Every used T_SSSS_OOOO must start like the Vailixi routine it is named after.

    Shapes come from the patched image, the bytes that run, and may not reach
    into a patch.  A target in on_hook is a hook site: a patch must start
    there, and its stock bytes are compared instead.
    """
    if not on_hook <= used:
        raise ValueError(f"hook-site targets the cave does not use: {sorted(on_hook - used)}")
    vailixi = mod.linear()
    starts = {p.off for p in patches}
    records = []
    for name in sorted(used):
        if name not in targets:
            raise ValueError(f"{name}: used by the cave but not defined in {PROFILE.name}")
        seg, off = targets[name]
        vseg, voff = int(name[2:6], 16), int(name[7:11], 16)
        s_lin, v_lin = seg * 16 + off, (vseg << 4) + voff - 0x80000
        if not 0 <= s_lin < CODE_END:
            raise ValueError(f"{name} = {seg:04X}:{off:04X}: outside 3.16 code")
        hook = name in on_hook
        if hook and s_lin not in starts:
            raise ValueError(f"{name} = {seg:04X}:{off:04X}: listed as a hook site, but no patch starts "
                             f"at 0x{s_lin:05X}")
        s_shape = _shape(stock if hook else patched, s_lin, off, SHAPE_INSNS)
        end = s_lin + sum(n for n, _ in s_shape)
        for p in patches:
            if p.off < end and s_lin < p.off + len(p.new) and not (hook and p.off == s_lin):
                raise ValueError(f"{name} = {seg:04X}:{off:04X}: compared bytes 0x{s_lin:05X}-0x{end:05X} "
                                 f"reach the patch at 0x{p.off:05X}")
        v_shape = _shape(vailixi, v_lin, voff, SHAPE_INSNS)
        if s_shape != v_shape:
            raise ValueError(f"{name} = {seg:04X}:{off:04X}: instruction shapes differ from Vailixi "
                             f"{vseg:04X}:{voff:04X}: {s_shape} vs {v_shape}")
        records.append({"symbol": name, "vailixi": f"{vseg:04X}:{voff:04X}",
                        "s316": f"{seg:04X}:{off:04X}", "image": f"0x{s_lin:05X}"})
    return records


def used_targets(transfers: list[mod.FarTransfer], targets: dict[str, tuple[int, int]]) -> set[str]:
    """The T_ symbol each far transfer names; only a JMP FAR may go to 3.16's entry 0000:0000."""
    by_value = {v: k for k, v in targets.items()}
    used = set()
    for t in transfers:
        key = (t.segment, t.offset)
        if key == (0, 0) and t.opcode == 0xEA:
            continue
        if key not in by_value:
            raise ValueError(f"far transfer {t.source!r} to {t.segment:04X}:{t.offset:04X} "
                             f"matches no T_ symbol in {PROFILE.name}")
        used.add(by_value[key])
    return used


def entry_operands(labels: dict[str, int], listing: list) -> dict[str, tuple[int, int]]:
    """Cave offset and size of each ENTRY316 immediate; entry316 must assemble to ENTRY316."""
    lines = {line.offset: line.data for line in listing}
    at, ops = labels["entry316"], {}
    for spec in ENTRY316:
        fixed, name = re.fullmatch(r"([0-9a-f]+)(?:\{(\w+)\})?", spec).groups()
        fixed, data = bytes.fromhex(fixed), lines.get(at, b"")
        size = len(data) - len(fixed)
        if not data.startswith(fixed) or size not in ((1, 2) if name else (0,)):
            raise ValueError(f"cave+0x{at:X}: entry316 assembles {data.hex() or 'nothing'} here, expected {spec}")
        if name:
            ops[name] = (at + len(fixed), size)
        at += len(data)
    return ops


def _imm(buf: bytes | bytearray, base: int, op: tuple[int, int]) -> int:
    return int.from_bytes(buf[base + op[0]:base + op[0] + op[1]], "little")


def _names_label(line: kit.ListingLine, value: int, labels: dict[str, int]) -> bool:
    """The source operand is a cave label whose offset is `value`: an offset in the cave, not a segment."""
    words = re.findall(r"[A-Za-z_.][\w.]*", line.source)
    if any(labels.get(word) == value for word in words):
        return True
    m = re.search(r",\s*([A-Za-z_][\w.]*)\s*([+-])\s*(\d+|0x[0-9A-Fa-f]+)\s*(?:;|$)", line.source)
    return bool(m and m[1] in labels
                and (labels[m[1]] + (1 if m[2] == "+" else -1) * int(m[3], 0)) & 0xFFFF == value)


def _not_operand(line: kit.ListingLine, at: int) -> bool:
    words = line.source.split()
    if words and words[0].endswith(":"):        # a label on the instruction's line
        words = words[1:]
    return any(words[:1] == [mnemonic] and line.data.startswith(bytes.fromhex(code))
               and at - line.offset == pos for mnemonic, code, pos in NOT_OPERANDS)


def cave_transfers(cave: bytes, labels: dict[str, int], listing: list) -> list[mod.FarTransfer]:
    """mod.far_transfers of the cave.  The one indirect far transfer allowed is
    entry316's JMP FAR [CS:.moved_ptr], which verify() runs (ENTRY316)."""
    jump = b"\x2e\xff\x2e" + struct.pack("<H", labels["entry316.moved_ptr"])
    indirect = frozenset(line.offset for line in listing if line.data == jump)
    if len(indirect) != 1:
        raise ValueError(f"entry316's JMP FAR [CS:.moved_ptr] found {len(indirect)} times")
    return mod.far_transfers(mod.Cave((0, "", cave.hex()), labels, cave, listing), indirect)


def _w(mem: bytearray, at: int) -> int:
    return struct.unpack_from("<H", mem, at)[0]


def run_entry(result: rc.Result, load: int, ops: dict[str, tuple[int, int]], labels: dict[str, int],
              consts: dict[str, int]) -> tuple[bytearray, dict, dict]:
    """The EPROM loader at `load`, then entry316 as assembled: its immediates are
    read from the simulated memory where the code runs and the routine is
    re-done in Python (ENTRY316 pins the instructions between them).

    Returns (memory, registers at 3.16's entry, facts)."""
    mem, regs = rc.load(result.sys, load)
    facts = {"entry": f"{regs['cs']:04X}:{regs['ip']:04X}", "moved": False}
    table = labels["reloc_table"]
    while True:
        base = regs["cs"] * 16                  # entry316's segment = run segment + stage
        live = {name: _imm(mem, base, op) for name, op in ops.items()}
        run = (live["dx"] + 1) & 0xFFFF
        if (regs["cs"] - result.stage) & 0xFFFF != run:
            raise ValueError(f"L={load:04X}: entry316 at CS {regs['cs']:04X} reads L-1 = {live['dx']:04X}")
        if live["dx"] <= live["univ_m1"]:
            break
        # .move: D = L - UNIV_SEG; the code runs at the old stage
        if facts["moved"]:
            raise ValueError(f"L={load:04X}: entry316 moves twice")
        d = (live["dx"] - live["univ_m1_move"]) & 0xFFFF
        if d < _w(mem, base + live["t_dmin"]):
            raise ValueError(f"L={load:04X}: entry316 halts (move by {d:#x} < {_w(mem, base + live['t_dmin']):#x})")
        n = _w(mem, base + live["t_paras"])
        head, positions = rc.decode_relocs(mem, base + table)
        if head["records"] != _w(mem, base + live["t_count"]) or head["paragraphs"] != n:
            raise ValueError(f"L={load:04X}: table header and entry316 disagree")
        univ = live["univ_mv"]
        if univ * 16 + n * 16 > base + labels["entry316"]:
            raise ValueError(f"L={load:04X}: the copy reaches entry316 at 0x{base + labels['entry316']:05X}")
        for pos in positions:                   # a. every relocated word -D
            at = run * 16 + pos
            struct.pack_into("<H", mem, at, (_w(mem, at) - d) & 0xFFFF)
        mem[univ * 16:univ * 16 + n * 16] = mem[run * 16:run * 16 + n * 16]   # b. dst < src: forward copy
        for at, want in ((rc.BIOS_LOAD_SEG, (live["univ_bios"] + d) & 0xFFFF), (rc.BIOS_JMP_SEG, regs["cs"])):
            if _w(mem, at) == want:             # c. the loader's records of L
                struct.pack_into("<H", mem, at, want - d)
        regs["ss"] = (regs["ss"] - d) & 0xFFFF
        if live["moved"] != labels["entry316.moved"]:
            raise ValueError(f"L={load:04X}: entry316 continues at {live['moved']:04X}, not .moved")
        regs["cs"] = (regs["cs"] - d) & 0xFFFF  # d. .moved in the moved copy
        base = regs["cs"] * 16
        moved = {name: _imm(mem, base, op) for name, op in ops.items()}
        zero = (moved["univ_zero"] + _w(mem, base + moved["t_paras2"])) * 16
        mem[zero:zero + d * 16] = bytes(d * 16)
        facts.update(moved=True, move_paragraphs=f"{d:04X}", table_records=head["records"],
                     table_bytes=head["bytes"])
    # Steps 1-3 at run = L (L <= UNIV_SEG)
    home = live["home"] * 16
    if live["home"] != (run + CAVE_HOME) & 0xFFFF:
        raise ValueError(f"L={load:04X}: entry316 copies to {live['home']:04X}, not {run:04X}+CAVE_HOME")
    if home + 2 * live["count"] > rc.PAGE61:
        raise ValueError(f"L={load:04X}: cave home ends at {home + 2 * live['count']:#x}, past page 61")
    mem[home:home + 2 * live["count"]] = mem[base:base + 2 * live["count"]]
    pool = live["pool_seg"] * 16 + live["pool_off"]
    if pool != run * 16 + POOL_IMM:
        raise ValueError(f"L={load:04X}: entry316 adjusts {live['pool_seg']:04X}:{live['pool_off']:04X}, "
                         f"not the pool-end immediate")
    if mem[pool - 1] == live["pool_opcode"] and _w(mem, pool) == live["pool_word"]:
        struct.pack_into("<H", mem, pool, (live["dx"] - live["pool_room"]) & 0xFFFF)
    if live["start_seg"] != run:
        raise ValueError(f"L={load:04X}: entry316 jumps to {live['start_seg']:04X}:0000, not {run:04X}:0000")
    regs.update(cs=run, ip=0, ds=0x0040, seg=run)
    return mem, regs, facts


def verify(result: rc.Result, cave: bytes, labels: dict[str, int], listing: list,
           patches: list[rc.Patch], consts: dict[str, int], targets: dict[str, tuple[int, int]],
           memories: dict[int, bytearray] | None = None) -> dict:
    """Loader and entry316 simulation at every load segment; returns a summary for the manifest.

    The known segments are the profile's: its T_ target segments, DGROUP_SEG,
    SND_SEG, RING_SEG, BIOS_DS_SEG, PLAYER_SEG and CAVE_HOME.  `memories`, if given, receives each
    load segment's final simulated memory.
    """
    if labels.get("cave_end") != len(cave):
        raise ValueError(f"cave_end label is {labels.get('cave_end')}, the cave is {len(cave):#x} bytes")
    if labels.get("reloc_table") != len(cave):
        raise ValueError("reloc_table must be the cave's last label (the builder appends the table there)")
    # Every far transfer in the cave, from the NASM listing (instruction bounds).
    built = mod.Cave((0, "", cave.hex()), labels, cave, listing)
    transfers = cave_transfers(cave, labels, listing)
    ops = entry_operands(labels, listing)
    entry = {name: _imm(cave, 0, op) for name, op in ops.items()}
    fixed = dict(ENTRY316_FIXED, t_paras=labels["reloc_table"], t_paras2=labels["reloc_table"],
                 t_count=labels["reloc_table"] + 2, t_dmin=labels["reloc_table"] + 4,
                 t_records=labels["reloc_table"] + rc.TABLE_HEAD, moved=labels["entry316.moved"],
                 moved_ptr=labels["entry316.moved_ptr"], moved_seg=labels["entry316.moved_ptr"] + 2,
                 moved_jmp=labels["entry316.moved_ptr"])
    wrong = {k: f"{entry[k]:04X}" for k, v in fixed.items() if entry[k] != v}
    if wrong:
        raise ValueError(f"entry316 immediates differ from the model: {wrong}")
    restart = (ops["restart"][0] + 2 + entry["restart"]) & 0xFFFF
    if restart != labels["entry316"]:
        raise ValueError(f"entry316's .moved restarts at {restart:04X}, not entry316")
    if entry["home"] != CAVE_HOME:
        raise ValueError(f"entry316 copies to paragraph {entry['home']:04X}, not CAVE_HOME {CAVE_HOME:04X}")
    copied = labels["cave_copy_end"]                          # entry316 itself stays at the stage
    if labels["entry316"] < copied:
        raise ValueError("entry316 lies inside the copied part of the cave")
    if 2 * entry["count"] - copied not in (0, 1):
        raise ValueError(f"entry316 copies {entry['count']:#x} words; the copied cave is {copied:#x} bytes")
    home_end = (rc.UNIV + CAVE_HOME) * 16 + 2 * entry["count"]
    if home_end > rc.PAGE61:
        raise ValueError(f"the cave home ends at {home_end:#x} with L = {rc.UNIV:04X}, past page 61")
    mz = rc.MZ.parse(result.sys)
    if not mz.h["ss"] | mz.h["sp"]:
        raise ValueError("the image has no e_ss:e_sp: the loader keeps 0040:69C4, which the move must not rebase")
    if len(mz.image) > CAVE_HOME * 16:
        raise ValueError(f"the loaded image ends at 0x{len(mz.image):05X}, past the cave home 0x{CAVE_HOME * 16:05X}")
    head, listed = rc.decode_relocs(mz.image, result.table)
    if listed != sorted(rc.lin(sg, o) for o, sg in mz.relocs):
        raise ValueError("the image's relocation table is not the MZ relocation list")
    if result.table != result.stage * 16 + labels["reloc_table"] or \
            head["paragraphs"] != rc.para(len(mz.image)) or result.table + head["bytes"] != len(mz.image):
        raise ValueError("the relocation table is not the image's last bytes at reloc_table")
    special = {ops["dx"][0]: 0xFFFF, ops["pool_seg"][0]: POOL_IMM >> 4, ops["start_seg"][0]: 0x0000}
    data_segs = {consts["DGROUP_SEG"], consts["SND_SEG"], consts["RING_SEG"], consts["BIOS_DS_SEG"],
                 consts["FDC_DS_SEG"]}
    allowed = {seg for seg, _ in targets.values()} | data_segs | {consts["PLAYER_SEG"], CAVE_HOME}
    reloc_words = {v: struct.unpack_from("<H", cave, v)[0]
                   for k, v in labels.items() if k.startswith("__reloc_")}
    marked = set(reloc_words)
    if not special.keys() <= marked:
        raise ValueError(f"entry316 segment words not relocated: {[hex(o) for o in special.keys() - marked]}")
    odd = {f"cave+0x{o:X}": f"{w:04X}" for o, w in reloc_words.items()
           if (w != special[o] if o in special else w not in allowed)}
    if odd:
        raise ValueError(f"relocated cave words that are not known segments at their sites: {odd}")
    move_code = range(ops["univ_m1_move"][0], labels["entry316.moved_ptr"])
    if any(o in move_code for o in marked):
        raise ValueError("a relocated word inside .move/.moved: they run after the table changed it")
    for t in transfers:
        if t.cave_offset + 3 not in marked:
            raise ValueError(f"far transfer {t.source!r} at cave+0x{t.cave_offset:X}: segment not relocated")
        if t.segment in data_segs:
            raise ValueError(f"far transfer {t.source!r} at cave+0x{t.cave_offset:X}: "
                             f"into data segment {t.segment:04X}")
    # Unmarked words equal to a relocatable segment are suspect: list them.  A
    # segment word lies within one source line's bytes.
    scanned = allowed | {POOL_IMM >> 4}
    suspects, not_operands = [], 0
    for line in listing:
        for at in range(line.offset, line.offset + len(line.data) - 1):
            value = struct.unpack_from("<H", cave, at)[0]
            if value not in scanned or at in marked:
                continue
            if _not_operand(line, at) or _names_label(line, value, labels):
                not_operands += 1
            else:
                suspects.append(f"cave+0x{at:X}={value:04X} ({built.label_at(at)}: {line.source.strip()})")
    if suspects:
        raise ValueError("unrelocated words equal to a segment value: " + ", ".join(suspects))
    image = mz.image
    if image[POOL_IMM - 1:POOL_IMM + 2] != b"\xbb" + struct.pack("<H", POOL_END):
        raise ValueError("3.16 pool-end MOV BX,6FFFh not found where the entry routine expects it")
    summary, finals = {}, {}
    for load in rc.LOADS:
        mem, regs, facts = run_entry(result, load, ops, labels, consts)
        run = regs["seg"]
        if load >= rc.UNIV and run != rc.UNIV:
            raise ValueError(f"L={load:04X}: 3.16 runs at {run:04X}, not {rc.UNIV:04X}")
        if regs["ss"] != (run + mz.h["ss"]) & 0xFFFF:
            raise ValueError(f"L={load:04X}: SS {regs['ss']:04X} at 3.16's entry, expected {run:04X}+e_ss")
        home = (run + CAVE_HOME) * 16
        relocated = bytearray(cave)
        for o, w in reloc_words.items():
            struct.pack_into("<H", relocated, o, (w + run) & 0xFFFF)
        if mem[home:home + copied] != relocated[:copied]:
            raise ValueError(f"L={load:04X}: the cave home is not the relocated cave")
        pool_end = _w(mem, run * 16 + POOL_IMM)
        want = run - 1 - consts["SCSI_STK_PARAS"]
        if pool_end != want:
            raise ValueError(f"L={load:04X}: pool end {pool_end:04X}, expected {want:04X}")
        # The SCSI reader's private stack (scsistack316.inc): the paragraphs above
        # the pool end up to the image, which the cave takes only when they fit.
        if not pool_end + 1 + consts["SCSI_STK_PARAS"] <= run:
            raise ValueError(f"L={load:04X}: no room for the SCSI reader stack above pool end {pool_end:04X}")
        for p in patches:                       # hooks land on their cave labels
            for at, name in p.labels:
                off, seg = struct.unpack_from("<HH", mem, run * 16 + at)
                if (off, seg) != (labels[name], (run + CAVE_HOME) & 0xFFFF):
                    raise ValueError(f"L={load:04X}: hook at 0x{at:05X} -> {seg:04X}:{off:04X}, "
                                     f"expected {(run + CAVE_HOME) & 0xFFFF:04X}:{labels[name]:04X}")
        stage = (run + result.stage) * 16
        for t in transfers:                     # cave far transfers land in 3.16 code
            base = home if t.cave_offset < copied else stage     # entry316 runs at the stage
            off, seg = struct.unpack_from("<HH", mem, base + t.cave_offset + 1)
            rel = (seg - run) & 0xFFFF
            if rel == CAVE_HOME:
                continue
            target = rel * 16 + off
            if not 0 <= target < CODE_END:
                raise ValueError(f"L={load:04X}: {t.source!r} -> {seg:04X}:{off:04X} outside 3.16 code")
        if facts["entry"] != f"{(load + result.stage) & 0xFFFF:04X}:{labels['entry316']:04X}":
            raise ValueError(f"L={load:04X}: entry {facts['entry']}")
        finals[load] = (mem, {k: regs[k] for k in ("cs", "ip", "ss", "sp", "ds")})
        if memories is not None:
            memories[load] = mem
        summary[f"{load:04X}"] = dict(facts, runtime_segment=f"{run:04X}",
                                      cave_home=f"0x{home:05X}-0x{home + len(cave):05X}",
                                      pool_end=f"{pool_end:04X}")
    # One memory map: every load segment at or above UNIV ends identical.
    ref = finals.get(rc.UNIV)
    for load, (mem, regs) in finals.items():
        if ref is None or load < rc.UNIV:
            continue
        if regs != ref[1]:
            raise ValueError(f"L={load:04X}: registers at 3.16's entry {regs} differ from L={rc.UNIV:04X}'s {ref[1]}")
        if mem != ref[0]:
            first = next(i for i in range(len(mem)) if mem[i] != ref[0][i])
            raise ValueError(f"L={load:04X}: final memory differs from L={rc.UNIV:04X}'s at 0x{first:05X}")
    summary["copy_words"] = f"{entry['count']:04X}"
    summary["min_move"] = f"{head['min_delta']:04X}"
    summary["table"] = {"image": f"0x{result.table:05X}", "bytes": head["bytes"], "records": head["records"]}
    summary["far_transfers"] = len(transfers)
    summary["relocated_cave_words"] = len(reloc_words)
    summary["not_operand_words"] = not_operands
    return summary


def build(sounds: tuple[Path, ...] = (), out: Path | None = None, defines: tuple[str, ...] = ()) -> dict:
    """defines: extra NASM symbols, e.g. ("DISPLAY_COMPACT",) for display316.inc's compact put-char."""
    out = OUT if out is None else out
    base = M3K316.read_bytes()
    if kit.sha256(base) != M3K316_SHA256:
        raise ValueError(f"{M3K316}: not the pinned M3K316.SYS")
    targets, consts = _profile_values()
    if consts.get("CAVE_HOME") != CAVE_HOME:
        raise ValueError("CAVE_HOME in profile_316.inc and build_wave316.py differ")
    args = mod.read_args(ARGS)
    asm = kit.assemble(args.cave, defines={DEFINE: None, **dict.fromkeys(defines)}, include=[args.cave.parent],
                       map_column="real", listing=True,
                       publish_bin=out / "wave316.cave.bin", publish_map=out / "wave316.cave.map")
    cave = asm.code
    if re.search(rb"\x0f[\xe0\xf0]", cave):
        raise ValueError("cave contains 0F E0 / 0F F0 (BRKXA/RETXA)")
    patches = [rc.expand(off, old, new, asm.labels, CAVE_HOME) for off, old, new in args.patch]
    result = rc.build(base, cave, asm.labels, patches, home=CAVE_HOME)
    transfers = cave_transfers(cave, asm.labels, asm.listing)
    used = used_targets(transfers, targets)
    shape_records = check_targets(bytes(rc.MZ.parse(base).image), bytes(rc.MZ.parse(result.sys).image),
                                  patches, targets, used)
    summary = verify(result, cave, asm.labels, asm.listing, patches, consts, targets)
    sys_path = out / "WAVE316.SYS"
    kit.write_atomic(sys_path, result.sys)
    files = [(sys_path, "STARTUP.SYS")]
    for name, planes in (("SINE441", sine441()), ("STEREO1", stereo1())):
        path = out / f"{name}.SND"
        kit.write_atomic(path, snd(name, planes))
        files.append((path, path.name))
    for path in sounds:
        files.append((path, path.name.upper()))
    disk, _ = kit.pack_fat12([(n, p.read_bytes()) for p, n in files], oem=b"MPC3K316",
                             volume_id=b"W316", label=b"WAVE316    ")
    img_path = out / "WAVE316.img"
    kit.write_atomic(img_path, disk)
    marker = next(bytes.fromhex(n).split(b"\0")[0].decode() for o, _, n in args.patch if o == 0x61B5A)
    deps = sorted({*asm.deps, ARGS, PROFILE, Path(__file__).resolve(), Path(rc.__file__).resolve(),
                   ROOT / "mods" / "buildkit.py", ROOT / "mods" / "build_mod_sys.py", ROOT / "emu" / "snd.py"})
    manifest = {
        "profile": "os316-route-c", "marker": marker,
        "base": {"path": kit.relpath(M3K316), "sha256": M3K316_SHA256},
        "sys": {"bytes": len(result.sys), "sha256": kit.sha256(result.sys)},
        "image": {"bytes": len(disk), "sha256": kit.sha256(disk),
                  "files": [{"name": n, "sha256": kit.sha256(p.read_bytes())} for p, n in files]},
        "cave": {"bytes": result.cave_len, "stage_paragraph": f"{result.stage:04X}",
                 "home_paragraph": f"{CAVE_HOME:04X}", "entry": f"{result.stage:04X}:{result.entry:04X}"},
        "relocations": {"total": result.reloc_count, "added": result.relocs_added,
                        "removed_inside_patches": [f"0x{x:05X}" for x in result.relocs_removed]},
        "patches": [{"image": f"0x{p.off:05X}", "old": p.old.hex(), "new": p.new.hex()} for p in patches],
        "targets": shape_records, "simulation": summary,
        "sources": {kit.relpath(p): kit.sha256(p.read_bytes()) for p in deps},
    }
    kit.write_atomic(out / "WAVE316.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sound", type=Path, action="append", default=[], help="add an SND file to the image")
    ap.add_argument("--out", type=Path, default=None, help="output directory (default build/mods)")
    ap.add_argument("--define", action="append", default=[], help="extra NASM symbol (DISPLAY_COMPACT)")
    a = ap.parse_args()
    m = build(tuple(a.sound), a.out, tuple(a.define))
    print(json.dumps({k: m[k] for k in ("marker", "sys", "image", "cave", "relocations", "simulation")}, indent=2))
