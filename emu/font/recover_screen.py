"""Recover 5x7 glyphs from a glass photo paired with display-RAM codes.

Pipeline (same geometry as the Play/Record fit): affine seed, homography +
radial k1, gap-objective corner refine, residual warp, two-surface
normalise. Gap column is u%6==0 and gap row is v%8==0; a cell occupies
[8r+1:8r+8, 6c+1:6c+6].

Usage:
  .venv/bin/python3 font/recover_screen.py \\
      --image font/lcd_programs.jpg \\
      --hex run/font_programs/screens_hex.txt \\
      --out font/programs
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from fit_grid import H, W, fit, load, sample, score

CORNERS_UV = np.array([[0, 0], [W, 0], [W, H], [0, H]], float)


def box3(a):
    p = np.pad(a, 1, mode="edge")
    return sum(p[i:i + a.shape[0], j:j + a.shape[1]] for i in range(3) for j in range(3)) / 9


def dots(a, thr):
    s = box3(a)
    core = s[2:-2, 2:-2]
    is_max = np.ones_like(core, bool)
    for di in range(-2, 3):
        for dj in range(-2, 3):
            if di or dj:
                is_max &= core >= s[2 + di:s.shape[0] - 2 + di, 2 + dj:s.shape[1] - 2 + dj]
    ys, xs = np.nonzero(is_max & (core > thr))
    ys, xs = ys + 2, xs + 2
    out = []
    for y, x in zip(ys, xs):
        w = np.clip(a[y - 1:y + 2, x - 1:x + 2] - thr, 0, None)
        if w.sum() <= 0:
            continue
        gy, gx = np.mgrid[-1:2, -1:2]
        out.append((x + (w * gx).sum() / w.sum(), y + (w * gy).sum() / w.sum()))
    return np.array(out)


def project(h, k1, u, v, cx, cy):
    d = h[6] * u + h[7] * v + 1
    x = (h[0] * u + h[1] * v + h[2]) / d
    y = (h[3] * u + h[4] * v + h[5]) / d
    r2 = ((x - cx) ** 2 + (y - cy) ** 2) / cx ** 2
    return cx + (x - cx) * (1 + k1 * r2), cy + (y - cy) * (1 + k1 * r2)


def undistort(k1, x, y, cx, cy):
    xu, yu = x.copy(), y.copy()
    for _ in range(10):
        r2 = ((xu - cx) ** 2 + (yu - cy) ** 2) / cx ** 2
        xu = cx + (x - cx) / (1 + k1 * r2)
        yu = cy + (y - cy) / (1 + k1 * r2)
    return xu, yu


def dlt(u, v, x, y):
    A = np.zeros((2 * len(u), 8))
    b = np.concatenate([x, y])
    n = len(u)
    A[:n, 0], A[:n, 1], A[:n, 2] = u, v, 1
    A[:n, 6], A[:n, 7] = -u * x, -v * x
    A[n:, 3], A[n:, 4], A[n:, 5] = u, v, 1
    A[n:, 6], A[n:, 7] = -u * y, -v * y
    return np.linalg.lstsq(A, b, rcond=None)[0]


def invert(h, k1, x, y, cx, cy):
    xu, yu = undistort(k1, x, y, cx, cy)
    Hm = np.append(h, 1).reshape(3, 3)
    q = np.linalg.solve(Hm, np.stack([xu, yu, np.ones_like(xu)]))
    return q[0] / q[2], q[1] / q[2]


def bilinear(img, X, Y):
    xi, yi = np.floor(X).astype(int), np.floor(Y).astype(int)
    xi = np.clip(xi, 0, img.shape[1] - 2)
    yi = np.clip(yi, 0, img.shape[0] - 2)
    fx, fy = X - xi, Y - yi
    return ((1 - fx) * (1 - fy) * img[yi, xi] + fx * (1 - fy) * img[yi, xi + 1]
            + (1 - fx) * fy * img[yi + 1, xi] + fx * fy * img[yi + 1, xi + 1])


def homography_mat(src, dst):
    A = []
    for (u, v), (x, y) in zip(src, dst):
        A.append([u, v, 1, 0, 0, 0, -u * x, -v * x, -x])
        A.append([0, 0, 0, u, v, 1, -u * y, -v * y, -y])
    h = np.linalg.svd(np.array(A))[2][-1]
    return (h / h[-1]).reshape(3, 3)


def project_m(Hm, k1, u, v, cx, cy):
    d = Hm[2, 0] * u + Hm[2, 1] * v + 1
    x = (Hm[0, 0] * u + Hm[0, 1] * v + Hm[0, 2]) / d
    y = (Hm[1, 0] * u + Hm[1, 1] * v + Hm[1, 2]) / d
    r2 = ((x - cx) ** 2 + (y - cy) ** 2) / cx ** 2
    return cx + (x - cx) * (1 + k1 * r2), cy + (y - cy) * (1 + k1 * r2)


def eq_phase(bits):
    """Best (u_phase, v_phase) so '=' cells in title/rule rows agree."""
    best = (0, 0, 0, 0)
    for vp in range(8):
        for up in range(6):
            cells = []
            for row in (0, 6):
                y0 = row * 8 + vp
                if y0 + 8 > H:
                    continue
                band = bits[y0:y0 + 8]
                for c in range(40):
                    x0 = c * 6 + up
                    if x0 + 6 <= W:
                        cells.append(band[:, x0:x0 + 6].tobytes())
            lit = [x for x in cells if any(x)]
            if not lit:
                continue
            vals, counts = np.unique(lit, return_counts=True)
            if counts.max() > best[0]:
                best = (int(counts.max()), len(cells), up, vp)
    return best


def affine_seed(img):
    mask = img > 80
    ys, xs = np.nonzero(mask)
    x0, y0 = float(xs.min()), float(ys.min())
    best = None
    for dx in (0, 4, 8):
        for dy in (-2, 0, 2):
            for px in (3.65, 3.72):
                p0 = [x0 + dx, y0 + dy, px, px, 0.0]
                p = fit(img, p0)
                sc = score(img, p)
                if best is None or sc > best[0]:
                    best = (sc, p)
    return best[1]


def homog_from_dots(img, p, pts, cx, cy):
    x0, y0, px, py, t = p
    results = []
    for k1 in np.arange(-0.06, 0.061, 0.01):
        for u_off in (-1, 0, 1):
            c, s = np.cos(t), np.sin(t)
            dx, dy = pts[:, 0] - x0, pts[:, 1] - y0
            u = (dx * c + dy * s) / px + u_off
            v = (-dx * s + dy * c) / py
            h = None
            for _ in range(10):
                ui, vi = np.floor(u), np.floor(v)
                ok = ((ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
                      & (np.abs(u - ui - 0.5) < 0.35) & (np.abs(v - vi - 0.5) < 0.35))
                if ok.sum() < 20:
                    break
                xu, yu = undistort(k1, pts[ok, 0], pts[ok, 1], cx, cy)
                h = dlt(ui[ok] + 0.5, vi[ok] + 0.5, xu, yu)
                u, v = invert(h, k1, pts[:, 0], pts[:, 1], cx, cy)
            if h is None:
                continue
            U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
            vals = bilinear(img, *project(h, k1, U, V, cx, cy))
            thr = 0.5 * (np.percentile(vals, 5) + np.percentile(vals, 95))
            m, total, up, vp = eq_phase(vals >= thr)
            ui, vi = np.floor(u), np.floor(v)
            ok = (np.abs(u - ui - 0.5) < 0.35) & (np.abs(v - vi - 0.5) < 0.35)
            px_, py_ = project(h, k1, ui[ok] + 0.5, vi[ok] + 0.5, cx, cy)
            rms = np.sqrt(((px_ - pts[ok, 0]) ** 2 + (py_ - pts[ok, 1]) ** 2).mean())
            results.append((m, -rms, k1, u_off, up, vp, h))
            print(f"  k1={k1:+.2f} u_off={u_off:+d} '=' {m}/{total} phase={up},{vp} rms={rms:.3f}")
    return max(results, key=lambda r: (r[0], r[1]))


def refine_gaps(img, corners, k1, cx, cy):
    U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    gap = (U.astype(int) % 6 == 0) | (V.astype(int) % 8 == 0)

    def samp(corn, kk):
        Hm = homography_mat(CORNERS_UV, corn)
        return bilinear(img, *project_m(Hm, kk, U, V, cx, cy))

    def sc(corn, kk):
        s = samp(corn, kk)
        return np.percentile(s[~gap], 80) - s[gap].mean()

    best = sc(corners, k1)
    for step in (1.0, 0.5, 0.25, 0.125):
        improved = True
        while improved:
            improved = False
            for i in range(4):
                for j in range(2):
                    for d in (-step, step):
                        corners[i, j] += d
                        n = sc(corners, k1)
                        if n > best:
                            best, improved = n, True
                        else:
                            corners[i, j] -= d
            for d in (-step * 0.005, step * 0.005):
                n = sc(corners, k1 + d)
                if n > best:
                    best, k1, improved = n, k1 + d, True
    return corners, k1, samp(corners, k1), best


def warp_gaps(img, X0, Y0):
    U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    gap = (U.astype(int) % 6 == 0) | (V.astype(int) % 8 == 0)
    nx, ny = 9, 3
    gx, gy = U / W * (nx - 1), V / H * (ny - 1)
    ix = np.clip(np.floor(gx).astype(int), 0, nx - 2)
    iy = np.clip(np.floor(gy).astype(int), 0, ny - 2)
    fx, fy = gx - ix, gy - iy

    def interp(g):
        return ((1 - fx) * (1 - fy) * g[iy, ix] + fx * (1 - fy) * g[iy, ix + 1]
                + (1 - fx) * fy * g[iy + 1, ix] + fx * fy * g[iy + 1, ix + 1])

    def samp(ox, oy):
        return bilinear(img, X0 + interp(ox), Y0 + interp(oy))

    def sc(ox, oy):
        s = samp(ox, oy)
        return np.percentile(s[~gap], 80) - s[gap].mean()

    ox, oy = np.zeros((ny, nx)), np.zeros((ny, nx))
    best = sc(ox, oy)
    for step in (1.0, 0.5, 0.25, 0.125):
        improved = True
        while improved:
            improved = False
            for g in (ox, oy):
                for j in range(ny):
                    for i in range(nx):
                        for d in (-step, step):
                            g[j, i] += d
                            n = sc(ox, oy)
                            if n > best and abs(g[j, i]) <= 4:
                                best, improved = n, True
                            else:
                                g[j, i] -= d
    return samp(ox, oy), ox, oy, best


def normalize(vals):
    U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    un, vn = U / W - 0.5, V / H - 0.5
    B = np.stack([np.ones_like(un), un, vn, un * un, un * vn, vn * vn,
                  un ** 3, un ** 4], -1)
    gap = (U.astype(int) % 6 == 0) | (V.astype(int) % 8 == 0)

    def surface(mask):
        coef, *_ = np.linalg.lstsq(B[mask], vals[mask], rcond=None)
        return B @ coef

    dark = surface(gap)
    lit_mask = vals > dark + 40
    for _ in range(5):
        lit = surface(lit_mask & ~gap)
        lit_mask = vals > 0.5 * (dark + lit)
    norm = (vals - dark) / (lit - dark)
    return norm, norm > 0.5


def read_hex(path: Path) -> list[list[int]]:
    rows = []
    for line in path.read_text().splitlines():
        if line.startswith("@") or not line.strip():
            continue
        rows.append([int(b, 16) for b in line.split()])
    if len(rows) != 8 or any(len(r) != 40 for r in rows):
        raise ValueError(f"{path}: expected 8x40 hex rows, got {[len(r) for r in rows]}")
    return rows


def cell_bits(bits, r, c):
    return bits[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6]


def is_cursor(bits, r, c):
    block = bits[8 * r:8 * r + 8, 6 * c:6 * c + 6]
    return block.size == 48 and int(block.sum()) >= 40


def rows_of(g):
    return [int("".join("1" if x else "0" for x in row), 2) for row in g]


def extract(bits, norm, codes):
    inst, cursors = defaultdict(list), []
    for r in range(8):
        for c in range(40):
            if is_cursor(bits, r, c):
                cursors.append((r, c))
                continue
            g = cell_bits(bits, r, c)
            margin = float(np.abs(norm[8 * r + 1:8 * r + 8, 6 * c + 1:6 * c + 6] - 0.5).min())
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
    return glyphs, conflicts, cursors


def merge_glyphs(base: dict, incoming: dict, source: str) -> tuple[dict, list]:
    conflicts = []
    out = {int(k, 16) if isinstance(k, str) else k: dict(v) for k, v in base.items()}
    for code, g in incoming.items():
        code = int(code)
        rows = tuple(g["rows"])
        if code not in out:
            ng = dict(g)
            ng["cells"] = [[source, *xy] for xy in g["cells"]]
            out[code] = ng
            continue
        old = tuple(out[code]["rows"])
        if old != rows:
            conflicts.append((code, old, rows))
            continue
        tagged = out[code]["cells"]
        for cell in g["cells"]:
            entry = [source, *cell] if not (isinstance(cell[0], str)) else cell
            if entry not in tagged and cell not in tagged:
                tagged.append(entry)
        out[code]["cells"] = tagged
        n = len(tagged)
        if out[code]["status"] in ("OBSERVED", "ASCII_HYP") and n >= 2:
            out[code]["status"] = "PROVEN"
        out[code]["min_margin"] = min(out[code].get("min_margin", 1), g["min_margin"])
    return out, conflicts


def save_preview(bits, path: Path):
    Image.fromarray((bits * 255).astype(np.uint8)).resize((960, 256), Image.NEAREST).save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--hex", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--merge", type=Path, help="existing glyphs.json to merge into")
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    img = load(args.image)
    cx, cy = img.shape[1] / 2, img.shape[0] / 2
    print("affine…")
    p = affine_seed(img)
    print("  params", np.round(p, 4).tolist(), "score", round(score(img, p), 3))

    pts = dots(img, thr=130)
    print(f"dots {len(pts)}")
    print("homography…")
    m, nrms, k1, u_off, up, vp, h = homog_from_dots(img, p, pts, cx, cy)
    print(f"  best '=' {m} k1={k1:+.2f} phase={up},{vp} rms={-nrms:.3f}")

    # Resample so gap column is u%6==0 and gap row is v%8==0 (glyph at +1).
    # Shift so gap column is u%6==0 and the '=' band starts at row*8 (gap row 0).
    U, V = np.meshgrid(np.arange(W) + 0.5 + (up - 1), np.arange(H) + 0.5 + vp)
    X, Y = project(h, k1, U, V, cx, cy)
    # Corner mapping in the shifted frame (LCD 0,0 is gap).
    corners = np.stack(project(h, k1,
                               CORNERS_UV[:, 0] + (up - 1),
                               CORNERS_UV[:, 1] + vp, cx, cy), -1)
    # project() returns distorted photo coords; refine uses undistorted-then-distort
    # via homography_mat on those corners + k1. Seed with the distorted corners
    # as an approximation; refine will walk them.
    print("refine…")
    corners, k1, vals, rsc = refine_gaps(img, corners, k1, cx, cy)
    print("  score", round(rsc, 2), "k1", round(k1, 4))

    Hm = homography_mat(CORNERS_UV, corners)
    U0, V0 = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    X0, Y0 = project_m(Hm, k1, U0, V0, cx, cy)
    print("warp…")
    vals, ox, oy, wsc = warp_gaps(img, X0, Y0)
    print("  score", round(wsc, 2))

    print("normalise…")
    norm, bits = normalize(vals)
    print("  gap-col lit", int(bits[:, 0::6].sum()), "gap-row lit", int(bits[0::8].sum()))
    amb = (norm > 0.3) & (norm < 0.7)
    print("  ambiguous", int(amb.sum()))

    np.save(out / "bits.npy", bits)
    np.save(out / "norm.npy", norm)
    np.save(out / "vals.npy", vals)
    save_preview(bits, out / "recovered.png")
    json.dump({"corners": corners.tolist(), "k1": k1, "ox": ox.tolist(), "oy": oy.tolist()},
              open(out / "fit.json", "w"))

    codes = read_hex(args.hex)
    glyphs, conflicts, cursors = extract(bits, norm, codes)
    print(f"cursors {cursors}  codes {len(glyphs)}  conflicts {len(conflicts)}")
    for code, lst in conflicts:
        print(f"CONFLICT {code:02X} {chr(code) if 32 <= code < 127 else ''}:")
        seen = {}
        for (rc, rows, mgn) in lst:
            key = tuple(rows)
            seen.setdefault(key, []).append((rc, round(mgn, 2)))
        for rows, cells in seen.items():
            print("  ", [f"{x:05b}" for x in rows], cells)

    ref = np.full((64, 240), ".", dtype=object)
    ref[:63, :239] = np.where(bits[1:, 1:], "#", ".")
    for r, c in cursors:
        ref[8 * r:8 * r + 8, 6 * c:6 * c + 6] = "?"
    (out / "photo.txt").write_text(
        f"; LC7981 glass from {args.image.name}. '#' lit '.' unlit '?' cursor.\n"
        + "\n".join("".join(row) for row in ref) + "\n")
    (out / "glyphs.json").write_text(
        json.dumps({f"{k:02X}": v for k, v in sorted(glyphs.items())}, indent=1))
    by = defaultdict(list)
    for k, v in glyphs.items():
        by[v["status"]].append(k)
    for s, ks in by.items():
        print(s, len(ks), "".join(chr(k) if 32 < k < 127 else f"<{k:02X}>" for k in sorted(ks)))

    if args.merge:
        base = {int(k, 16): v for k, v in json.loads(args.merge.read_text()).items()}
        merged, mconf = merge_glyphs(base, glyphs, args.out.name)
        if mconf:
            print("MERGE CONFLICTS:")
            for code, old, new in mconf:
                print(f"  {code:02X} old {old} new {new}")
        args.merge.write_text(json.dumps(
            {f"{k:02X}": v for k, v in sorted(merged.items())}, indent=1))
        print(f"merged -> {args.merge} ({len(merged)} codes)")
        by = defaultdict(list)
        for k, v in merged.items():
            by[v["status"]].append(k)
        for s, ks in by.items():
            print(s, len(ks), "".join(chr(k) if 32 < k < 127 else f"<{k:02X}>" for k in sorted(ks)))
    return 0 if not conflicts else 1


if __name__ == "__main__":
    raise SystemExit(main())
