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
loader's work in Python at both load segments (route_c.simulate): every hook
must land on its cave label at the cave's home, every cave far CALL/JMP on
3.16 code, every relocated word must be a known segment, and every stock
target the cave calls must start with the same instruction shapes as the
Vailixi 3.50 routine it is named after.

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
SHAPE_INSNS = 6                 # instructions compared per stock target
OUT = mod.OUT


def _profile_values() -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """T_ targets (relative seg:off) and plain equ constants of profile_316.inc."""
    text = PROFILE.read_text()
    targets = {m[1]: (int(m[2], 16), int(m[3], 16)) for m in re.finditer(
        r"^%define (T_[0-9A-F]{4}_[0-9A-F]{4}) 0x([0-9A-F]+):0x([0-9A-F]+)", text, re.M)}
    consts = {m[1]: int(m[2], 16) for m in re.finditer(r"^(\w+)\s+equ\s+0x([0-9A-Fa-f]+)", text, re.M)}
    return targets, consts


def _shape(data: bytes, start: int, origin: int, count: int) -> list[tuple[int, str]]:
    """(length, mnemonic) of the first `count` instructions at data[start]."""
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(data[start:start + 64]); f.flush()
        out = subprocess.run(["ndisasm", "-b", "16", "-o", hex(origin), f.name],
                             capture_output=True, text=True, check=True).stdout
    shape = []
    for line in out.splitlines()[:count]:
        parts = line.split(None, 2)
        mnemonic = parts[2].split()[0] if len(parts) > 2 else ""
        shape.append((len(parts[1]) // 2, mnemonic))
        if mnemonic in ("ret", "retf", "iret", "jmp"):
            break                       # what follows may be data (jump tables)
    return shape


def check_targets(image: bytes, targets: dict[str, tuple[int, int]], used: set[str]) -> list[dict]:
    """Every used T_SSSS_OOOO must start like the Vailixi routine it is named after."""
    vailixi = mod.linear()
    records = []
    for name in sorted(used):
        if name not in targets:
            raise ValueError(f"{name}: used by the cave but not defined in {PROFILE.name}")
        seg, off = targets[name]
        vseg, voff = int(name[2:6], 16), int(name[7:11], 16)
        s_lin, v_lin = seg * 16 + off, (vseg << 4) + voff - 0x80000
        if not 0 <= s_lin < CODE_END:
            raise ValueError(f"{name} = {seg:04X}:{off:04X}: outside 3.16 code")
        s_shape = _shape(image, s_lin, off, SHAPE_INSNS)
        v_shape = _shape(vailixi, v_lin, voff, SHAPE_INSNS)
        if s_shape != v_shape:
            raise ValueError(f"{name} = {seg:04X}:{off:04X}: instruction shapes differ from Vailixi "
                             f"{vseg:04X}:{voff:04X}: {s_shape} vs {v_shape}")
        records.append({"symbol": name, "vailixi": f"{vseg:04X}:{voff:04X}",
                        "s316": f"{seg:04X}:{off:04X}", "image": f"0x{s_lin:05X}"})
    return records


def verify(result: rc.Result, cave: bytes, labels: dict[str, int], listing: list,
           patches: list[rc.Patch], consts: dict[str, int]) -> dict:
    """Loader simulation at both load segments; returns a summary for the manifest."""
    # Every far transfer in the cave, from the NASM listing (instruction bounds).
    built = mod.Cave((0, "", cave.hex()), labels, cave, listing)
    transfers = mod.far_transfers(built)
    target_segs = {t.segment for t in transfers}
    allowed = target_segs | {consts["DGROUP_SEG"], consts["SND_SEG"], consts["PLAYER_SEG"],
                             CAVE_HOME, POOL_IMM >> 4, 0xFFFF, 0x0000}
    reloc_words = {v: struct.unpack_from("<H", cave, v)[0]
                   for k, v in labels.items() if k.startswith("__reloc_")}
    odd = {hex(o): hex(w) for o, w in reloc_words.items() if w not in allowed}
    if odd:
        raise ValueError(f"relocated cave words that are not known segments: {odd}")
    marked = set(reloc_words)
    for t in transfers:
        if t.cave_offset + 3 not in marked:
            raise ValueError(f"far transfer {t.source!r} at cave+0x{t.cave_offset:X}: segment not relocated")
    # Unmarked words equal to a relocatable segment are suspect: list them.
    suspects = []
    for value in (consts["DGROUP_SEG"], consts["SND_SEG"], consts["PLAYER_SEG"], CAVE_HOME):
        for m in re.finditer(re.escape(struct.pack("<H", value)), cave):
            if m.start() not in marked:
                suspects.append(f"cave+0x{m.start():X}={value:04X} ({built.label_at(m.start())})")
    if suspects:
        raise ValueError("unrelocated words equal to a segment value: " + ", ".join(suspects))
    summary = {}
    for load in rc.LOADS:
        mem, regs = rc.simulate(result.sys, load, home=CAVE_HOME, cave_len=len(cave))
        home = (load + CAVE_HOME) * 16
        if home + len(cave) > rc.PAGE61:
            raise ValueError(f"L={load:04X}: cave home ends at {home + len(cave):#x}, past page 61")
        if mem[home:home + len(cave)] != mem[load * 16 + result.stage * 16:][:len(cave)]:
            raise ValueError("staging copy and home copy differ")
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
                                  "cave_home": f"0x{home:05X}-0x{home + len(cave):05X}"}
    image = rc.MZ.parse(result.sys).image
    if image[POOL_IMM - 1:POOL_IMM + 2] != b"\xbb\xff\x6f":
        raise ValueError("3.16 pool-end MOV BX,6FFFh not found where the entry routine expects it")
    summary["far_transfers"] = len(transfers)
    summary["relocated_cave_words"] = len(reloc_words)
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
    # Every far transfer must name a profile target (or be the entry's jump to
    # 3.16's own entry 0000:0000); those targets are then shape-checked.
    transfers = mod.far_transfers(mod.Cave((0, "", cave.hex()), asm.labels, cave, asm.listing))
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
    image = rc.MZ.parse(base).image
    shape_records = check_targets(bytes(image), targets, used)
    summary = verify(result, cave, asm.labels, asm.listing, patches, consts)
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
