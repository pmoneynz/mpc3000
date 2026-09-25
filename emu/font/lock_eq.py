"""Re-register the Programs photo using the proven '=' 5x7 as the lattice lock."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from fit_grid import H, W, load
from recover_screen import (
    CORNERS_UV,
    affine_seed,
    bilinear,
    dots,
    extract,
    homog_from_dots,
    homography_mat,
    normalize,
    project,
    project_m,
    read_hex,
    refine_gaps,
    rows_of,
    save_preview,
    warp_gaps,
)

ROOT = Path(__file__).resolve().parent
glyphs = {int(k, 16): v for k, v in json.loads((ROOT / "glyphs.json").read_text()).items()}


def pat(rows):
    a = np.zeros((7, 5), np.uint8)
    for i, row in enumerate(rows):
        for x in range(5):
            a[i, x] = (row >> (4 - x)) & 1
    return a


EQ = pat(glyphs[0x3D]["rows"])


def eq_hits(bits):
    hits = []
    for y in range(H - 6):
        for x in range(W - 4):
            if not np.count_nonzero(bits[y:y + 7, x:x + 5] != EQ):
                hits.append((y, x))
    return hits


def main() -> None:
    img = load(ROOT / "lcd_programs.jpg")
    cx, cy = img.shape[1] / 2, img.shape[0] / 2
    print("affine…")
    p = affine_seed(img)
    print("  ", np.round(p, 4).tolist())
    pts = dots(img, thr=130)
    print("homog…")
    _m, _nrms, k1, u_off, up, vp, h = homog_from_dots(img, p, pts, cx, cy)
    print(f"  eq_phase winner k1={k1:+.2f} up,vp={up},{vp} u_off={u_off}")

    # Score a neighbourhood of UV shifts by exact '=' hits.
    best = None
    for du in range(-2, 4):
        for dv in range(-2, 4):
            U, V = np.meshgrid(np.arange(W) + 0.5 + du, np.arange(H) + 0.5 + dv)
            vals = bilinear(img, *project(h, k1, U, V, cx, cy))
            thr = 0.5 * (np.percentile(vals, 5) + np.percentile(vals, 95))
            hits = eq_hits(vals >= thr)
            # prefer hits that sit on the extract lattice (y%8==1, x%6==1)
            on = sum(1 for y, x in hits if y % 8 == 1 and x % 6 == 1)
            key = (on, len(hits), -abs(du), -abs(dv), du, dv)
            print(f"  shift du={du:+d} dv={dv:+d} eq={len(hits)} on-lattice={on}")
            if best is None or key[:2] > best[:2]:
                best = key
    _on, _n, _a, _b, du, dv = best
    print(f"using du={du} dv={dv}")

    corners = np.stack(project(h, k1, CORNERS_UV[:, 0] + du, CORNERS_UV[:, 1] + dv, cx, cy), -1)
    print("refine…")
    corners, k1, vals, rsc = refine_gaps(img, corners, k1, cx, cy)
    print("  ", round(rsc, 2), "k1", round(k1, 4))
    Hm = homography_mat(CORNERS_UV, corners)
    U0, V0 = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    X0, Y0 = project_m(Hm, k1, U0, V0, cx, cy)
    print("warp…")
    vals, ox, oy, wsc = warp_gaps(img, X0, Y0)
    print("  ", round(wsc, 2))
    norm, bits = normalize(vals)
    print("gap-col", int(bits[:, 0::6].sum()), "gap-row", int(bits[0::8].sum()),
          "eq on-lattice", sum(1 for y, x in eq_hits(bits) if y % 8 == 1 and x % 6 == 1))

    out = ROOT / "programs"
    np.save(out / "bits.npy", bits)
    np.save(out / "norm.npy", norm)
    save_preview(bits, out / "recovered.png")

    codes = read_hex(ROOT.parent / "run" / "font_programs" / "screens_hex.txt")
    # Known-code agreement
    agree = miss = 0
    for r in range(8):
        for c in range(40):
            code = codes[r][c]
            if code not in glyphs:
                continue
            g = bits[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6]
            if g.shape != (7, 5):
                continue
            if tuple(rows_of(g)) == tuple(glyphs[code]["rows"]):
                agree += 1
            else:
                miss += 1
    print(f"known agree {agree} miss {miss}")

    glyphs_new, conflicts, cursors = extract(bits, norm, codes)
    print(f"cursors {cursors} extracted {len(glyphs_new)} conflicts {len(conflicts)}")
    for code, lst in conflicts:
        ch = chr(code) if 32 <= code < 127 else ""
        variants = defaultdict(list)
        for rc, rows, m in lst:
            variants[tuple(rows)].append((rc, round(float(m), 2)))
        print(f" CONFLICT {code:02X} {ch} variants={len(variants)}")

    new_codes = sorted(set(glyphs_new) - set(glyphs))
    print("new codes:")
    for code in new_codes:
        g = glyphs_new[code]
        ch = chr(code) if 32 <= code < 127 else ""
        print(f"  {code:02X} {ch} {g['status']} n={len(g['cells'])} rows={g['rows']}")

    (out / "glyphs.json").write_text(json.dumps(
        {f"{k:02X}": v for k, v in sorted(glyphs_new.items())}, indent=1))


if __name__ == "__main__":
    main()
