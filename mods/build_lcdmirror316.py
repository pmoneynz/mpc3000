#!/usr/bin/env python3
"""Build the LCD mirror experiment: stock OS 3.16 that streams its screen as MIDI SysEx.

    python3 mods/build_lcdmirror316.py [--port 1-4] [--out DIR]

Design, protocol and evidence: notes/lcd_mirror_midi.md.  Inputs: the pinned
07-rom/.../M3K316.SYS (never modified), mods/LCDMIRROR316.args (hook patches
in 3.16 load-image offsets) and mods/lcdmirror316.asm assembled with
-DPROFILE_316.  The output is a Route C file (mods/route_c.py, notes/port_316.md):
3.16 plus a cave that entry316 copies home, so it boots from every EPROM set
like the stock file.  The cave holds nothing but the mirror and entry316 (which
also keeps 3.16's sequence pool below the image, notes/port_316.md "Pool fix").

The build is checked with mods/build_wave316.py's verify(): the EPROM loaders
and entry316 are re-run in Python at both load segments, every hook must land
on its cave label, and every relocated cave word must be a known segment.

Writes <out>/M3K316.SYS (patched), LCDMIRROR_316.img (FAT12, the patched file as
its only SYS), STOCK_316.img (control: the stock file), lcdmirror316.cave.map,
LCDMIRROR_316.json; prints every SHA-256 and the changed byte ranges.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mods import build_mod_sys as mod  # noqa: E402
from mods import build_wave316 as w316  # noqa: E402
from mods import buildkit as kit  # noqa: E402
from mods import route_c as rc  # noqa: E402

ROOT = kit.ROOT
ARGS = ROOT / "mods" / "LCDMIRROR316.args"
OUT = ROOT / "build" / "lcd_mirror"
PORTS = {1: "OUT A", 2: "OUT B", 3: "OUT C", 4: "OUT D"}
# Stock bytes the cave depends on but does not call: (image offset, hex, what).
# Evidence for each: notes/lcd_mirror_midi.md "3.16 map".
STOCK_FACTS = (
    (0x32860, "2e133019321f3425", "3286:0000 bulk ring offsets OUT A-D (= the cave's lm_rings)"),
    (0x32870, "c600ce00d600de00", "3286:0010 TE7774 control ports C6/CE/D6/DE"),
    (0x30372, "b8ca778ec0", "3033:0042 MOV AX,77CA / MOV ES,AX: the bulk push's ring segment = RING_SEG"),
    (0x02B5B, "b9fa05", "02B2:003B MOV CX,05FA: bulk ring capacity = LM_CAP"),
    (0x33B33, "800e5c9601800e159302a01593bac600ee",
     "33AF:0043 stock kick OUT A: OR [965C],1 / OR [9315],2 / OUT C6 (= lm_kick)"),
    (0x17453, "c606c99501", "1650:0F53 graphics init sets [95C9] = 1 (LM_MIXFLAG)"),
    (0x16936, "c606c99500", "1650:03FD text re-init sets [95C9] = 0"),
    (0x04288, "891e021d", "0427:0018 INT 43 AX=2 wrapper stores the cursor mode in [1D02] (LM_CMODE)"),
    (0x47D56, "2ec53e3c00fe4d107813", "47BF:0166 AMX ISR entry: LDS DI,[CS:3C] / DEC BYTE [DI+10] / JS (nesting byte)"),
    (0x42682, "803e9ba406", "422F:0392 CMP BYTE [A49B],6: the gate before 340C:0000, where task 2 waits for empty OUT rings"),
)
def stock_facts(image: bytes) -> list[str]:
    facts = []
    for off, want, what in STOCK_FACTS:
        got = image[off:off + len(want) // 2].hex()
        if got != want:
            raise ValueError(f"image 0x{off:05X} ({what}): {got}, expected {want}")
        facts.append(f"0x{off:05X} {want} {what}")
    return facts


def changed_ranges(a: bytes, b: bytes) -> list[tuple[int, int]]:
    """[start, end) file ranges where b differs from a, b's tail included."""
    out, i, n = [], 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            if out and i - out[-1][1] < 16:
                out[-1] = (out[-1][0], j)
            else:
                out.append((i, j))
            i = j
        else:
            i += 1
    if len(b) > len(a):
        out.append((len(a), len(b)))
    return out


def build(port: int = 4, out: Path | None = None) -> dict:
    if port not in PORTS:
        raise ValueError("--port is 1-4 (OUT A-D)")
    out = OUT if out is None else out
    base = w316.M3K316.read_bytes()
    if kit.sha256(base) != w316.M3K316_SHA256:
        raise ValueError(f"{w316.M3K316}: not the pinned M3K316.SYS")
    targets, consts = w316._profile_values()
    args = mod.read_args(ARGS)
    asm = kit.assemble(args.cave, defines={w316.DEFINE: None, "LM_PORT": port}, include=[args.cave.parent],
                       map_column="real", listing=True, publish_map=out / "lcdmirror316.cave.map")
    cave = asm.code
    if re.search(rb"\x0f[\xe0\xf0]", cave):
        raise ValueError("cave contains 0F E0 / 0F F0 (BRKXA/RETXA)")
    stock_image = bytes(rc.MZ.parse(base).image)
    facts = stock_facts(stock_image)
    rings = asm.labels["lm_rings"]
    if cave[rings:rings + 8] != stock_image[0x32860:0x32868]:
        raise ValueError("lm_rings differs from the stock ring table 3286:0000")
    patches = [rc.expand(off, old, new, asm.labels, w316.CAVE_HOME) for off, old, new in args.patch]
    result = rc.build(base, cave, asm.labels, patches, home=w316.CAVE_HOME)
    transfers = w316.cave_transfers(cave, asm.labels, asm.listing)
    used = w316.used_targets(transfers, targets)
    shapes = w316.check_targets(stock_image, bytes(rc.MZ.parse(result.sys).image), patches, targets, used,
                                on_hook=frozenset())
    summary = w316.verify(result, cave, asm.labels, asm.listing, patches, consts, targets)

    sys_path = out / "M3K316.SYS"
    kit.write_atomic(sys_path, result.sys)
    images = {}
    for name, data, label in (("LCDMIRROR_316.img", result.sys, b"LCDMIRROR  "),
                              ("STOCK_316.img", base, b"STOCK316   ")):
        disk, _ = kit.pack_fat12([("M3K316.SYS", data)], oem=b"MPC3K316", volume_id=b"LM16", label=label)
        kit.write_atomic(out / name, disk)
        images[name] = kit.sha256(disk)
    ranges = changed_ranges(base, result.sys)
    hdr = rc.MZ.parse(base).h["cparhdr"] * 16
    manifest = {
        "experiment": "LCD mirror over MIDI SysEx (notes/lcd_mirror_midi.md); emulator results are not hardware results",
        "port": port, "port_name": PORTS[port],
        "stock_sys": {"path": kit.relpath(w316.M3K316), "sha256": w316.M3K316_SHA256, "bytes": len(base)},
        "sys": {"path": kit.relpath(sys_path), "sha256": kit.sha256(result.sys), "bytes": len(result.sys)},
        "images": images,
        "cave": {"bytes": len(cave), "home_paragraph": f"{w316.CAVE_HOME:04X}",
                 "labels": {k: f"{v:04X}" for k, v in sorted(asm.labels.items())
                            if k.startswith("lm_") and "." not in k},
                 "probe_labels": {k: f"{v:04X}" for k, v in sorted(asm.labels.items()) if k.startswith("..@lm_")}},
        "patches": [{"image": f"0x{p.off:05X}", "old": p.old.hex(), "new": p.new.hex()} for p in patches],
        "changed_file_ranges": [
            {"file": f"0x{a:06X}-0x{b:06X}",
             "what": "MZ header and relocation table" if b <= hdr else
                     ("appended cave and relocation list" if a >= len(base) else
                      f"image 0x{a - hdr:05X}-0x{b - hdr:05X}")} for a, b in ranges],
        "stock_facts": facts,
        "targets": shapes,
        "verify": summary,
    }
    (out / "LCDMIRROR_316.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4, help="MIDI OUT 1-4 the mirror sends on (default 4 = OUT D)")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    m = build(a.port, a.out.resolve())
    print(f"M3K316.SYS (LCD mirror, {m['port_name']})  sha256 {m['sys']['sha256']}  {m['sys']['bytes']} bytes")
    print(f"stock M3K316.SYS                   sha256 {m['stock_sys']['sha256']}")
    for name, digest in m["images"].items():
        print(f"{name:34} sha256 {digest}")
    print(f"cave {m['cave']['bytes']} bytes at home paragraph {m['cave']['home_paragraph']}")
    for r in m["changed_file_ranges"]:
        print(f"changed {r['file']}  {r['what']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
