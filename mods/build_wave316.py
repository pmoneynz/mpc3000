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
loader's work (route_c.simulate) and the cave's entry316 in Python at both
load segments.  entry316 must assemble to the routine modelled here
(ENTRY316); its copy count must cover the cave, its halt bound must be the
highest L-1 whose home ends below page 61, the home must then hold the
relocated cave and the pool end must be min(L-1, 6FFFh).  Every hook must
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
HOOK_TARGETS = frozenset({"T_D0C0_0B19"})   # targets that are a hook site: the cave calls through the hook
OUT = mod.OUT

# entry316 as assembled, one NASM listing line per instruction.  {name} is the
# instruction's trailing immediate, which verify() reads and runs.
ENTRY316 = ("fc", "ba{dx}", "81fa{halt_bound}", "7739", "0e", "1f", "b8{home}", "8ec0", "31f6", "31ff",
            "b9{count}", "f3a5", "b8{pool_seg}", "8ec0", "bb{pool_off}", "26807fff{pool_opcode}", "7510",
            "26813f{pool_word}", "7509", "81fa{pool_limit}", "7303", "268917", "b84000", "8ed8",
            "ea0000{start_seg}", "f4", "ebfd")

# Unrelocated cave words equal to a segment value that are instruction bytes,
# not operands: (mnemonic, instruction's first bytes, word position in them).
NOT_OPERANDS = (("cmp", "2e3b06", 1),   # CMP AX,[CS:disp16]: opcode 3B and ModRM 06
                ("mov", "ba20", 0),     # MOV DX,0020h (BOT-TOP+1 rows): opcode BA and the immediate's low byte
                ("call", "9a", 1),      # CALL FAR's offset word; its segment word (position 3) is the relocated one
                ("mov", "bb0900", 1),   # MOV BX,9 in draw: the sound name's text column, equal to segment 0009
                ("mov", "2e8a14", 1),   # MOV DL,[CS:SI]: opcode 8A and ModRM 14, equal to segment 148A
                ("mov", "368a14", 1))   # MOV DL,[SS:SI]: the same bytes after an SS prefix


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
    return any(labels.get(word) == value for word in re.findall(r"[A-Za-z_.][\w.]*", line.source))


def _not_operand(line: kit.ListingLine, at: int) -> bool:
    words = line.source.split()
    if words and words[0].endswith(":"):        # a label on the instruction's line
        words = words[1:]
    return any(words[:1] == [mnemonic] and line.data.startswith(bytes.fromhex(code))
               and at - line.offset == pos for mnemonic, code, pos in NOT_OPERANDS)


def verify(result: rc.Result, cave: bytes, labels: dict[str, int], listing: list,
           patches: list[rc.Patch], consts: dict[str, int], targets: dict[str, tuple[int, int]]) -> dict:
    """Loader and entry316 simulation at both load segments; returns a summary for the manifest.

    The known segments are the profile's: its T_ target segments, DGROUP_SEG,
    SND_SEG, PLAYER_SEG and CAVE_HOME.
    """
    if labels.get("cave_end") != len(cave):
        raise ValueError(f"cave_end label is {labels.get('cave_end')}, the cave is {len(cave):#x} bytes")
    # Every far transfer in the cave, from the NASM listing (instruction bounds).
    built = mod.Cave((0, "", cave.hex()), labels, cave, listing)
    transfers = mod.far_transfers(built)
    ops = entry_operands(labels, listing)
    entry = {name: _imm(cave, 0, op) for name, op in ops.items()}
    if entry["home"] != CAVE_HOME:
        raise ValueError(f"entry316 copies to paragraph {entry['home']:04X}, not CAVE_HOME {CAVE_HOME:04X}")
    if 2 * entry["count"] - len(cave) not in (0, 1):
        raise ValueError(f"entry316 copies {entry['count']:#x} words; the cave is {len(cave):#x} bytes")
    bound = (rc.PAGE61 - len(cave)) // 16 - CAVE_HOME - 1     # highest L-1 whose home ends below page 61
    if entry["halt_bound"] != bound:
        raise ValueError(f"entry316 halts above L-1 = {entry['halt_bound']:04X}, expected {bound:04X}")
    special = {ops["dx"][0]: 0xFFFF, ops["pool_seg"][0]: POOL_IMM >> 4, ops["start_seg"][0]: 0x0000}
    data_segs = {consts["DGROUP_SEG"], consts["SND_SEG"]}
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
    image = rc.MZ.parse(result.sys).image
    if image[POOL_IMM - 1:POOL_IMM + 2] != b"\xbb" + struct.pack("<H", POOL_END):
        raise ValueError("3.16 pool-end MOV BX,6FFFh not found where the entry routine expects it")
    summary = {}
    for load in rc.LOADS:
        mem, regs = rc.simulate(result.sys, load, home=entry["home"], cave_len=2 * entry["count"])
        live = {name: _imm(mem, (load + result.stage) * 16, op) for name, op in ops.items()}
        dx = live["dx"]
        if dx != (load - 1) & 0xFFFF or live["home"] != (load + CAVE_HOME) & 0xFFFF:
            raise ValueError(f"L={load:04X}: entry316 runs with L-1 = {dx:04X}, home {live['home']:04X}")
        if dx > live["halt_bound"]:
            raise ValueError(f"L={load:04X}: entry316 halts (L-1 {dx:04X} > {live['halt_bound']:04X})")
        home = live["home"] * 16
        if home + 2 * live["count"] > rc.PAGE61:
            raise ValueError(f"L={load:04X}: cave home ends at {home + 2 * live['count']:#x}, past page 61")
        relocated = bytearray(cave)
        for o, w in reloc_words.items():
            struct.pack_into("<H", relocated, o, (w + load) & 0xFFFF)
        if mem[home:home + len(cave)] != relocated:
            raise ValueError(f"L={load:04X}: the cave home is not the relocated cave")
        pool = live["pool_seg"] * 16 + live["pool_off"]
        if pool != load * 16 + POOL_IMM:
            raise ValueError(f"L={load:04X}: entry316 adjusts {live['pool_seg']:04X}:{live['pool_off']:04X}, "
                             f"not the pool-end immediate")
        if (mem[pool - 1] == live["pool_opcode"] and _imm(mem, pool, (0, 2)) == live["pool_word"]
                and dx < live["pool_limit"]):
            struct.pack_into("<H", mem, pool, dx)
        pool_end = _imm(mem, pool, (0, 2))
        if pool_end != min(load - 1, POOL_END):
            raise ValueError(f"L={load:04X}: pool end {pool_end:04X}, expected {min(load - 1, POOL_END):04X}")
        for p in patches:                       # hooks land on their cave labels
            for at, name in p.labels:
                off, seg = struct.unpack_from("<HH", mem, load * 16 + at)
                if (off, seg) != (labels[name], (load + CAVE_HOME) & 0xFFFF):
                    raise ValueError(f"L={load:04X}: hook at 0x{at:05X} -> {seg:04X}:{off:04X}, "
                                     f"expected {(load + CAVE_HOME) & 0xFFFF:04X}:{labels[name]:04X}")
        for t in transfers:                     # cave far transfers land in 3.16 code
            off, seg = struct.unpack_from("<HH", mem, home + t.cave_offset + 1)
            rel = (seg - load) & 0xFFFF
            if rel == CAVE_HOME:
                continue
            target = rel * 16 + off
            if not 0 <= target < CODE_END:
                raise ValueError(f"L={load:04X}: {t.source!r} -> {seg:04X}:{off:04X} outside 3.16 code")
        if regs["cs"] != (load + result.stage) & 0xFFFF or regs["ip"] != labels["entry316"]:
            raise ValueError(f"L={load:04X}: entry {regs['cs']:04X}:{regs['ip']:04X}")
        summary[f"{load:04X}"] = {"entry": f"{regs['cs']:04X}:{regs['ip']:04X}",
                                  "cave_home": f"0x{home:05X}-0x{home + len(cave):05X}",
                                  "pool_end": f"{pool_end:04X}"}
    summary["copy_words"] = f"{entry['count']:04X}"
    summary["halt_above"] = f"{bound:04X}"
    summary["far_transfers"] = len(transfers)
    summary["relocated_cave_words"] = len(reloc_words)
    summary["not_operand_words"] = not_operands
    return summary


def build(sounds: tuple[Path, ...] = (), out: Path | None = None) -> dict:
    out = OUT if out is None else out
    base = M3K316.read_bytes()
    if kit.sha256(base) != M3K316_SHA256:
        raise ValueError(f"{M3K316}: not the pinned M3K316.SYS")
    targets, consts = _profile_values()
    if consts.get("CAVE_HOME") != CAVE_HOME:
        raise ValueError("CAVE_HOME in profile_316.inc and build_wave316.py differ")
    args = mod.read_args(ARGS)
    asm = kit.assemble(args.cave, defines={DEFINE: None}, include=[args.cave.parent],
                       map_column="real", listing=True,
                       publish_bin=out / "wave316.cave.bin", publish_map=out / "wave316.cave.map")
    cave = asm.code
    if re.search(rb"\x0f[\xe0\xf0]", cave):
        raise ValueError("cave contains 0F E0 / 0F F0 (BRKXA/RETXA)")
    patches = [rc.expand(off, old, new, asm.labels, CAVE_HOME) for off, old, new in args.patch]
    result = rc.build(base, cave, asm.labels, patches, home=CAVE_HOME)
    transfers = mod.far_transfers(mod.Cave((0, "", cave.hex()), asm.labels, cave, asm.listing))
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
    a = ap.parse_args()
    m = build(tuple(a.sound), a.out)
    print(json.dumps({k: m[k] for k in ("marker", "sys", "image", "cave", "relocations", "simulation")}, indent=2))
