"""Fit the 240x64 LC7981 pixel lattice onto a photo of the glass.

Model: photo = origin + u * pitch_x * (cos t, sin t) + v * pitch_y * (-sin t, cos t),
with (u, v) the LCD pixel centre. Score: separation of samples into two
clusters (lit / unlit), i.e. the grid that samples dot centres, not gaps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 240, 64


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(float)[:, :, 0]


def sample(img: np.ndarray, p: np.ndarray) -> np.ndarray:
    x0, y0, px, py, t = p
    u, v = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    c, s = np.cos(t), np.sin(t)
    x = x0 + u * px * c - v * py * s
    y = y0 + u * px * s + v * py * c
    xi, yi = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - xi, y - yi
    xi = np.clip(xi, 0, img.shape[1] - 2)
    yi = np.clip(yi, 0, img.shape[0] - 2)
    return ((1 - fx) * (1 - fy) * img[yi, xi] + fx * (1 - fy) * img[yi, xi + 1]
            + (1 - fx) * fy * img[yi + 1, xi] + fx * fy * img[yi + 1, xi + 1])


def score(img: np.ndarray, p: np.ndarray) -> float:
    s = sample(img, p).ravel()
    thr = 0.5 * (np.percentile(s, 5) + np.percentile(s, 95))
    lo, hi = s[s < thr], s[s >= thr]
    if len(lo) < 100 or len(hi) < 100:
        return 0.0
    return (hi.mean() - lo.mean()) / np.sqrt(0.5 * (hi.var() + lo.var()) + 1e-6)


def fit(img: np.ndarray, p0: list[float]) -> np.ndarray:
    p = np.array(p0, float)
    steps = np.array([2.0, 2.0, 0.02, 0.02, 0.002])
    best = score(img, p)
    for _ in range(60):
        improved = False
        for i in range(len(p)):
            for d in (-1, 1):
                q = p.copy()
                q[i] += d * steps[i]
                sc = score(img, q)
                if sc > best:
                    best, p, improved = sc, q, True
        if not improved:
            steps /= 2
            if steps[0] < 0.01:
                break
    print("score", round(best, 3), "params", np.round(p, 4).tolist())
    return p


if __name__ == "__main__":
    img = load(Path(sys.argv[1]))
    best = None
    for x0 in (52, 54, 56):
        for y0 in (278, 280, 282):
            p = fit(img, [x0, y0, 3.72, 3.72, 0.0])
            sc = score(img, p)
            if best is None or sc > best[0]:
                best = (sc, p)
    Path(sys.argv[2]).write_text(json.dumps({"score": best[0], "params": best[1].tolist()}))
