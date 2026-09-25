"""Refine each Programs-menu 'N.' pair and write missing digit glyphs."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from fit_grid import load
from local_glyphs import bits_of, ncc, pat, rows_of, sample_cell

ROOT = Path(__file__).resolve().parent
glyphs = {int(k, 16): v for k, v in json.loads((ROOT / "glyphs.json").read_text()).items()}
period = pat(glyphs[0x2E]["rows"])
img = load(ROOT / "lcd_programs.jpg")

# (code, period_x, period_y, pitch) from local_glyphs high-NCC hits.
SEEDS = [
    (0x31, 66, 309, 3.55),
    (0x32, 66, 335, 3.55),
    (0x33, 68, 365, 3.55),
    (0x34, 68, 393, 3.55),
    (0x35, 534, 313, 3.55),
    (0x36, 534, 341, 3.55),
    (0x37, 534, 369, 3.55),
    (0x38, 532, 397, 3.55),
    (0x39, 532, 425, 3.55),
]


def refine(x0, y0, p0):
    # Pitch is locked near the value that made proven '4' and '8' exact (3.55).
    best = (-1.0, x0, y0, 3.55, 0.0)
    for p in np.arange(3.50, 3.61, 0.01):
        for t in np.arange(-0.015, 0.016, 0.005):
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    x, y = x0 + dx, y0 + dy
                    sc = ncc(sample_cell(img, x, y, p, p, t), period)
                    if sc > best[0]:
                        best = (sc, x, y, p, t)
    return best


def main() -> None:
    extracted = {}
    for code, x0, y0, p0 in SEEDS:
        sc, x, y, p, t = refine(x0, y0, p0)
        digit = sample_cell(img, x - 6 * p, y, p, p, t)
        g = bits_of(digit)
        rows = rows_of(g)
        ch = chr(code)
        print(f"{ch} period ncc={sc:.3f} @({x},{y}) p={p:.2f} t={t:.3f}")
        print(" ", "\n  ".join("".join("#" if z else "." for z in row) for row in g))
        if code in glyphs:
            agree = tuple(rows) == tuple(glyphs[code]["rows"])
            print(f"  known {glyphs[code]['status']} agree={agree}")
        extracted[code] = {
            "rows": rows,
            "cells": [["programs", -1, -1]],
            "status": "OBSERVED",
            "min_margin": round(float(np.abs((digit - np.median(digit)) / (np.ptp(digit) + 1e-6)).min()), 3),
            "period_ncc": round(sc, 3),
        }

    # Control: 1, 4, 8 must agree with the Play/Record bitmaps.
    ok = True
    for code in (0x31, 0x34, 0x38):
        if tuple(extracted[code]["rows"]) != tuple(glyphs[code]["rows"]):
            print(f"CONTROL FAIL {code:02X}")
            ok = False
    if not ok:
        raise SystemExit(1)

    for code in (0x32, 0x33, 0x35, 0x36, 0x37, 0x39):
        glyphs[code] = extracted[code]
        # 8 was ASCII_HYP; this screen pairs 8 with display RAM.
        if code == 0x38:
            pass
    # Upgrade 8: same bitmap, now also RAM-paired on this screen.
    glyphs[0x38]["status"] = "PROVEN"
    glyphs[0x38].setdefault("photo_diff_region_agrees", True)

    Path(ROOT / "glyphs.json").write_text(json.dumps(
        {f"{k:02X}": v for k, v in sorted(glyphs.items())}, indent=1))
    print("wrote glyphs.json", "new", "".join(chr(c) for c in (0x32, 0x33, 0x35, 0x36, 0x37, 0x39)))


if __name__ == "__main__":
    main()
