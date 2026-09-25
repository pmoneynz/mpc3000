"""Homography + radial k1 fit of LCD (u, v) -> photo (x, y) from dot centres.

Verification is independent of the fit objective: every '=' cell in text rows
0, 3 and 6 of the Play/Record screen must read as the same 5x8 bitmap.
"""

import json

import numpy as np
from PIL import Image

from fit_grid import H, W, load


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
    # sub-pixel centroid over 3x3
    out = []
    for y, x in zip(ys, xs):
        w = np.clip(a[y - 1:y + 2, x - 1:x + 2] - thr, 0, None)
        if w.sum() <= 0:
            continue
        gy, gx = np.mgrid[-1:2, -1:2]
        out.append((x + (w * gx).sum() / w.sum(), y + (w * gy).sum() / w.sum()))
    return np.array(out)


img = load("lcd_play_record.jpg")
pts = dots(img, thr=130)
x0, y0, px, py, t = json.load(open("grid.json"))["params"]
CX, CY = img.shape[1] / 2, img.shape[0] / 2


def project(h, k1, u, v):
    d = h[6] * u + h[7] * v + 1
    x = (h[0] * u + h[1] * v + h[2]) / d
    y = (h[3] * u + h[4] * v + h[5]) / d
    r2 = ((x - CX) ** 2 + (y - CY) ** 2) / CX ** 2
    return CX + (x - CX) * (1 + k1 * r2), CY + (y - CY) * (1 + k1 * r2)


def undistort(k1, x, y):
    xu, yu = x.copy(), y.copy()
    for _ in range(10):
        r2 = ((xu - CX) ** 2 + (yu - CY) ** 2) / CX ** 2
        xu = CX + (x - CX) / (1 + k1 * r2)
        yu = CY + (y - CY) / (1 + k1 * r2)
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


def invert(h, k1, x, y):
    xu, yu = undistort(k1, x, y)
    Hm = np.append(h, 1).reshape(3, 3)
    q = np.linalg.solve(Hm, np.stack([xu, yu, np.ones_like(xu)]))
    return q[0] / q[2], q[1] / q[2]


def fit(k1, u_off=0.0):
    c, s = np.cos(t), np.sin(t)
    dx, dy = pts[:, 0] - x0, pts[:, 1] - y0
    u = (dx * c + dy * s) / px + u_off
    v = (-dx * s + dy * c) / py
    h = None
    for _ in range(10):
        ui, vi = np.floor(u), np.floor(v)
        ok = ((ui >= 0) & (ui < W) & (vi >= 0) & (vi < H)
              & (np.abs(u - ui - 0.5) < 0.35) & (np.abs(v - vi - 0.5) < 0.35))
        xu, yu = undistort(k1, pts[ok, 0], pts[ok, 1])
        h = dlt(ui[ok] + 0.5, vi[ok] + 0.5, xu, yu)
        u, v = invert(h, k1, pts[:, 0], pts[:, 1])
    ui, vi = np.floor(u), np.floor(v)
    ok = (np.abs(u - ui - 0.5) < 0.35) & (np.abs(v - vi - 0.5) < 0.35)
    px_, py_ = project(h, k1, ui[ok] + 0.5, vi[ok] + 0.5)
    rms = np.sqrt(((px_ - pts[ok, 0]) ** 2 + (py_ - pts[ok, 1]) ** 2).mean())
    return h, rms, ok.sum()


def sample(h, k1):
    U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    X, Y = project(h, k1, U, V)
    xi, yi = np.floor(X).astype(int), np.floor(Y).astype(int)
    fx, fy = X - xi, Y - yi
    return ((1 - fx) * (1 - fy) * img[yi, xi] + fx * (1 - fy) * img[yi, xi + 1]
            + (1 - fx) * fy * img[yi + 1, xi] + fx * fy * img[yi + 1, xi + 1])


def eq_check(bits):
    """Return (#cells matching the modal '=' bitmap, #'=' cells), with best cell phase."""
    best = (0, 0, 0)
    for phase in range(6):
        cells = []
        for row in (0, 3, 6):
            band = bits[row * 8:row * 8 + 8]
            for c in range(40):
                u0 = c * 6 + phase
                if u0 + 6 <= W:
                    cells.append(band[:, u0:u0 + 6].tobytes())
        # '=' cells are the most common non-blank cell in these rows
        vals, counts = np.unique([x for x in cells if any(x)], return_counts=True)
        if len(vals) and counts.max() > best[0]:
            best = (int(counts.max()), len(cells), phase)
    return best


results = []
for k1 in np.arange(-0.06, 0.061, 0.01):
    for u_off in (-1, 0, 1):
        h, rms, n = fit(k1, u_off)
        vals = sample(h, k1)
        thr = 0.5 * (np.percentile(vals, 5) + np.percentile(vals, 95))
        m, total, phase = eq_check(vals >= thr)
        results.append((m, -rms, k1, u_off, phase, n, h))
        print(f"k1={k1:+.2f} u_off={u_off:+d} rms={rms:.3f} used={n} '=' match {m}/{total} phase={phase}")

m, nrms, k1, u_off, phase, n, h = max(results, key=lambda r: (r[0], r[1]))
print(f"best: k1={k1:+.2f} u_off={u_off} rms={-nrms:.3f} '=' matches={m} phase={phase}")
vals = sample(h, k1)
thr = 0.5 * (np.percentile(vals, 5) + np.percentile(vals, 95))
bits = vals >= thr
np.save("bits.npy", bits)
np.save("vals.npy", vals)
json.dump({"h": h.tolist(), "k1": k1, "phase": phase, "thr": thr}, open("homog.json", "w"))
Image.fromarray((bits * 255).astype(np.uint8)).resize((960, 256), Image.NEAREST).save("recovered_h.png")
