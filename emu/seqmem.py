"""Sequencer memory pool, read from RAM through each OS's own variables.

E21A:000B (3.50 file 0x621AB) returns free bytes; E21A:0096 (0x62236)
returns 100 * free / total with total = lin([P+6]:[P+4]) - lin([P+2]:[P]).
D9DD:005D is lin(seg1:off1) - lin(seg2:off2), lin = seg*16 + off. The same
byte patterns locate the DGROUP offsets in 3.12 and M3K316.SYS.
"""

from __future__ import annotations

from pathlib import Path

from emu.mpc3k import BUILD, M3K316, disk, run
from emu.panel import key_tap, write_smf

# (flag byte F, total base P) per OS, from the pattern match.
LAYOUT = {"3.50": (0x9208, 0x8E26), "3.12": (0x901B, 0x8C39), "3.16": (0x8EF5, 0x8B13)}


def offsets(f: int, p: int) -> list[int]:
    return [f, *range(f + 6, f + 0x1A, 2), p - 8, p - 6, p, p + 2, p + 4, p + 6]


def parse(path: Path) -> dict[int, int]:
    words = {}
    for line in path.read_text().splitlines()[-100:]:
        if line.startswith("@"):
            words = {"head": line}
        else:
            off, val = line.split()
            words[int(off, 16)] = int(val, 16)
    return words


def lin(w: dict, seg: int, off: int) -> int:
    return (w[seg] << 4) + w[off]


def pool(w: dict, f: int, p: int) -> dict:
    total = lin(w, p + 6, p + 4) - lin(w, p + 2, p)
    if w[f] & 0xFF:
        free = lin(w, p + 6, p + 4) - lin(w, p - 6, p - 8)
    elif lin(w, f + 0x18, f + 0x16) >= lin(w, f + 0x14, f + 0x12):
        free = (lin(w, f + 0x18, f + 0x16) - lin(w, f + 8, f + 6)
                + lin(w, f + 0xC, f + 0xA) - lin(w, f + 0x14, f + 0x12))
    else:
        free = lin(w, f + 0x18, f + 0x16) - lin(w, f + 0x14, f + 0x12)
    return {"total": total, "free": free, "free_k": (free - 400) // 1024,
            "pct": 100 * free // total if total else None}


def measure(name: str, bios: str, os_: str, t: float, floppy: Path | None = None) -> dict:
    out = BUILD / "emu" / f"seqmem_{name}"
    panel = None
    if floppy is not None:
        panel = write_smf(BUILD / "emu" / f"seqmem_{name}.mid", key_tap("soft4", 33))
    run(bios, [t], out, floppy=floppy, panel=panel, words=offsets(*LAYOUT[os_]))
    w = parse(out / "ram_words.log")
    return {"name": name, "head": w["head"], **pool(w, *LAYOUT[os_])}


if __name__ == "__main__":
    flop = disk("m3k316", [(M3K316, "M3K316.SYS")])
    for r in (measure("350_boot", "vailixi", "3.50", 15),
              measure("350", "vailixi", "3.50", 60),
              measure("312", "default", "3.12", 60),
              measure("316_via312", "default", "3.16", 60, flop),
              measure("316_via350", "vailixi", "3.16", 60, flop)):
        print(r)
