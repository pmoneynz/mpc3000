"""Register a glass photo by matching already-proven 5x7 glyphs.

Optimises LCD-corner homography + radial k1 so sampled cells agree with
glyphs.json. Unknown codes are then read from the locked lattice.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from fit_grid import H, W, load
from recover_screen import (
    CORNERS_UV,
    bilinear,
    homography_mat,
    normalize,
    project_m,
    read_hex,
    rows_of,
    save_preview,
)

ROOT = Path(__file__).resolve().parent
IMG = ROOT / "lcd_programs.jpg"
HEX = ROOT.parent / "run" / "font_programs" / "screens_hex.txt"
OUT = ROOT / "programs"


def templates(glyphs: dict) -> dict[int, np.ndarray]:
    out = {}
    for k, v in glyphs.items():
        code = int(k, 16) if isinstance(k, str) else k
        a = np.zeros((7, 5), np.uint8)
        for i, row in enumerate(v["rows"]):
            for x in range(5):
                a[i, x] = (row >> (4 - x)) & 1
        out[code] = a
    return out


def sample_grid(img, corners, k1, cx, cy):
    Hm = homography_mat(CORNERS_UV, corners)
    U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    return bilinear(img, *project_m(Hm, k1, U, V, cx, cy))


def xor_score(bits, codes, tmpls):
    total = n = 0
    for r in range(8):
        for c in range(40):
            t = tmpls.get(codes[r][c])
            if t is None:
                continue
            g = bits[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6]
            if g.shape != (7, 5):
                continue
            total += int(np.count_nonzero(g != t))
            n += 1
    return total, n


def main() -> None:
    img = load(IMG)
    cx, cy = img.shape[1] / 2, img.shape[0] / 2
    glyphs = json.loads((ROOT / "glyphs.json").read_text())
    tmpls = templates(glyphs)
    codes = read_hex(HEX)

    mask = img > 80
    ys, xs = np.nonzero(mask)
    x0, y0, x1, y1 = float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())
    # Inset a little: bright bbox is the lit dots, not the glass edge.
    pad_x, pad_y = 4.0, 3.0
    corners = np.array([
        [x0 - pad_x, y0 - pad_y],
        [x1 + pad_x, y0 - pad_y],
        [x1 + pad_x, y1 + pad_y],
        [x0 - pad_x, y1 + pad_y],
    ], float)
    k1 = 0.0

    def bits_of(corn, kk):
        vals = sample_grid(img, corn, kk, cx, cy)
        return normalize(vals)[1], vals

    bits, vals = bits_of(corners, k1)
    best_xor, n = xor_score(bits, codes, tmpls)
    print(f"start xor={best_xor}/{n*35} cells={n}")

    for step, kstep in ((4.0, 0.02), (2.0, 0.01), (1.0, 0.005), (0.5, 0.002), (0.25, 0.001)):
        improved = True
        while improved:
            improved = False
            for i in range(4):
                for j in range(2):
                    for d in (-step, step):
                        corners[i, j] += d
                        xor, _ = xor_score(bits_of(corners, k1)[0], codes, tmpls)
                        if xor < best_xor:
                            best_xor, improved = xor, True
                            print(f"  xor={best_xor} step={step}")
                        else:
                            corners[i, j] -= d
            for d in (-kstep, kstep):
                xor, _ = xor_score(bits_of(corners, k1 + d)[0], codes, tmpls)
                if xor < best_xor:
                    best_xor, k1, improved = xor, k1 + d, True
                    print(f"  xor={best_xor} k1={k1:.4f}")
    print("corners", np.round(corners, 2).tolist(), "k1", round(k1, 4), "xor", best_xor)

    bits, vals = bits_of(corners, k1)
    norm, bits = normalize(vals)
    save_preview(bits, OUT / "aligned.png")
    np.save(OUT / "bits_aligned.npy", bits)
    np.save(OUT / "norm_aligned.npy", norm)
    print("gap-col lit", int(bits[:, 0::6].sum()), "gap-row lit", int(bits[0::8].sum()))
    print("final xor", xor_score(bits, codes, tmpls))

    new = defaultdict(list)
    for r in range(8):
        for c in range(40):
            code = codes[r][c]
            if code in tmpls:
                continue
            g = bits[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6]
            if g.shape != (7, 5):
                continue
            margin = float(np.abs(norm[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6] - 0.5).min())
            new[code].append(((r, c), rows_of(g), margin, int(g.sum())))

    print("unknown:")
    for code in sorted(new):
        variants = defaultdict(list)
        for rc, rows, m, ones in new[code]:
            variants[tuple(rows)].append((rc, round(m, 2), ones))
        ch = chr(code) if 32 <= code < 127 else f"<{code:02X}>"
        print(f" {code:02X} {ch}")
        for rows, cells in variants.items():
            print("   ", [f"{x:05b}" for x in rows], cells)


if __name__ == "__main__":
    main()
