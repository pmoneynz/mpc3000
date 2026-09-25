"""Extract unknown glyphs from neighbour cells of proven templates.

Finds proven 5x7 bitmaps ('.' '1' '4' '8' '=') in the Programs photo by
scaled template match, then reads the 5x7 immediately to the left of each
menu 'N.' pair.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from fit_grid import load

ROOT = Path(__file__).resolve().parent
glyphs = {int(k, 16): v["rows"] for k, v in json.loads((ROOT / "glyphs.json").read_text()).items()}


def pat(rows):
    a = np.zeros((7, 5), float)
    for i, row in enumerate(rows):
        for x in range(5):
            a[i, x] = (row >> (4 - x)) & 1
    return a


def sample_cell(img, x0, y0, px, py, t=0.0):
    """Sample 5x7 at photo origin (x0,y0) of pixel (0,0), pitch (px,py)."""
    c, s = np.cos(t), np.sin(t)
    out = np.zeros((7, 5))
    for v in range(7):
        for u in range(5):
            x = x0 + (u + 0.5) * px * c - (v + 0.5) * py * s
            y = y0 + (u + 0.5) * px * s + (v + 0.5) * py * c
            xi, yi = int(np.floor(x)), int(np.floor(y))
            if not (0 <= xi < img.shape[1] - 1 and 0 <= yi < img.shape[0] - 1):
                continue
            fx, fy = x - xi, y - yi
            out[v, u] = ((1 - fx) * (1 - fy) * img[yi, xi] + fx * (1 - fy) * img[yi, xi + 1]
                         + (1 - fx) * fy * img[yi + 1, xi] + fx * fy * img[yi + 1, xi + 1])
    return out


def ncc(a, tmpl):
    a = a - a.mean()
    t = tmpl - tmpl.mean()
    den = np.sqrt((a * a).sum() * (t * t).sum()) + 1e-9
    return float((a * t).sum() / den)


def bits_of(cell):
    lo, hi = np.percentile(cell, 15), np.percentile(cell, 85)
    thr = 0.5 * (lo + hi)
    return cell > thr


def rows_of(g):
    return [int("".join("1" if x else "0" for x in row), 2) for row in g]


def main() -> None:
    img = load(ROOT / "lcd_programs.jpg")
    period = pat(glyphs[0x2E])
    # Search a band around the LCD.
    best = []
    for py in (3.45, 3.55, 3.65, 3.72):
        px = py
        # coarse scan
        for y0 in range(275, 500, 2):
            for x0 in range(40, 900, 2):
                cell = sample_cell(img, x0, y0, px, py)
                sc = ncc(cell, period)
                if sc > 0.72:
                    best.append((sc, x0, y0, px, py))
    best.sort(reverse=True)
    print(f"period candidates {len(best)}")
    for t in best[:20]:
        print(f"  ncc={t[0]:.3f} x={t[1]} y={t[2]} p={t[3]}")

    # Cluster: keep local maxima more than 8 photo-px apart.
    kept = []
    for sc, x0, y0, px, py in best:
        if any(abs(x0 - x) < 8 and abs(y0 - y) < 8 for _, x, y, _, _ in kept):
            continue
        kept.append((sc, x0, y0, px, py))
    print(f"kept {len(kept)}")

    # For each period, read the cell one pitch-6 to the left (the digit).
    found = defaultdict(list)
    for sc, x0, y0, px, py in kept:
        digit = sample_cell(img, x0 - 6 * px, y0, px, py)
        g = bits_of(digit)
        ones = int(g.sum())
        # skip blanks
        if ones < 4:
            continue
        print(f"left of period @({x0},{y0}) p={px} ncc={sc:.3f} ones={ones}")
        print(" ", "\n  ".join("".join("#" if p else "." for p in row) for row in g))
        found[round(y0 / 20)].append((rows_of(g), (x0, y0), sc, ones))


if __name__ == "__main__":
    main()
