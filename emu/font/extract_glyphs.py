"""Pair photo cells with display-RAM codes and derive per-code 5x7 glyphs.

Lattice frame: the fitted grid is offset by (+1, +1) from LCD pixel (0, 0), so
cell (r, c) occupies bits[8r+1 : 8r+8, 6c+1 : 6c+6]; its gap column and gap
row are bits[:, 6c+6] and bits[8r+8, :] (the latter only inside the frame).

Evidence classes:
  PROVEN    - code shown in >= 2 cells with identical bitmaps.
  OBSERVED  - code shown in exactly one cell (bitmap measured once).
  ASCII_HYP - taken from photo cells whose content differs from the emulator
              state (row 1 cols 24..39); the code is inferred as ASCII of the
              visible text, which is a hypothesis.
"""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

bits = np.load("bits.npy")
norm = np.load("norm.npy")
hexfile = (Path(__file__).resolve().parents[2] / "build" / "emu" / "font_ref" / "screens_hex.txt").read_text().splitlines()
codes = [[int(b, 16) for b in line.split()] for line in hexfile[1:9]]

# Row 1, cols 24..39 on the real glass: 'BPM: 80.4 (MAS) ' with the cursor on col 24.
DIFF_ROW, DIFF_COLS, CURSOR = 1, range(24, 40), (1, 24)
PHOTO_TEXT = "BPM: 80.4 (MAS) "


def cell(r, c):
    g = bits[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6]
    m = np.abs(norm[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6] - 0.5).min()
    return g, m


def rows_of(g):
    return [int("".join("1" if x else "0" for x in row), 2) for row in g]


inst = defaultdict(list)
hyp = defaultdict(list)
for r in range(8):
    for c in range(40):
        g, margin = cell(r, c)
        if (r, c) == CURSOR:
            continue
        if r == DIFF_ROW and c in DIFF_COLS:
            hyp[ord(PHOTO_TEXT[c - 24])].append(((r, c), rows_of(g), margin))
        else:
            inst[codes[r][c]].append(((r, c), rows_of(g), margin))

glyphs, conflicts = {}, []
for code, lst in sorted(inst.items()):
    variants = {tuple(x[1]) for x in lst}
    if len(variants) > 1:
        conflicts.append((code, lst))
        continue
    glyphs[code] = {"rows": lst[0][1], "cells": [x[0] for x in lst],
                    "status": "PROVEN" if len(lst) > 1 else "OBSERVED",
                    "min_margin": round(float(min(x[2] for x in lst)), 3)}
for code, lst in sorted(hyp.items()):
    variants = {tuple(x[1]) for x in lst}
    if code in glyphs:
        agree = variants == {tuple(glyphs[code]["rows"])}
        glyphs[code].setdefault("photo_diff_region_agrees", agree)
    elif len(variants) == 1:
        glyphs[code] = {"rows": lst[0][1], "cells": [x[0] for x in lst], "status": "ASCII_HYP",
                        "min_margin": round(float(min(x[2] for x in lst)), 3)}
    else:
        conflicts.append((code, lst))

gap_lit = [(r, c) for r in range(8) for c in range(39) if bits[8 * r + 1:8 * r + 8, 6 * c + 6].any()
           and (r, c) != CURSOR and (r, c + 1) != CURSOR]
ref = np.full((64, 240), "?")
ref[:63, :239] = np.where(bits[1:, 1:], "#", ".")
ref[8 * DIFF_ROW:8 * DIFF_ROW + 8, 6 * DIFF_COLS[0]:] = "?"
Path("photo_play_record.txt").write_text(
    "; LC7981 glass, Play/Record screen, from lcd_play_record.jpg (IMG_4706).\n"
    "; LCD pixel frame 240x64. '#' lit, '.' unlit, '?' not compared: outside the\n"
    "; photo lattice (row 63, col 239) or row 1 cols 24..39, where the machine\n"
    "; state differed (BPM 80.4 (MAS), block cursor) from the emulated boot.\n"
    + "\n".join("".join(r) for r in ref) + "\n")
Path("glyphs.json").write_text(json.dumps({f"{k:02X}": v for k, v in sorted(glyphs.items())}, indent=1))

print(f"codes: {len(glyphs)}  conflicts: {len(conflicts)}  cells with lit gap column: {gap_lit}")
for code, lst in conflicts:
    print(f"CONFLICT {code:02X} {chr(code) if 32 <= code < 127 else ''}:")
    for (rc, rows, m) in lst:
        print("   ", rc, [f"{x:05b}" for x in rows], "margin", round(float(m), 2))
by_status = defaultdict(list)
for k, v in glyphs.items():
    by_status[v["status"]].append(k)
for s, ks in by_status.items():
    print(s, len(ks), "".join(chr(k) if 32 < k < 127 else f"<{k:02X}>" for k in sorted(ks)))
print("diff-region agreement:", {chr(k): v["photo_diff_region_agrees"] for k, v in glyphs.items()
                                 if "photo_diff_region_agrees" in v})
print("lowest margins:", sorted((v["min_margin"], f"{k:02X}") for k, v in glyphs.items())[:6])
