"""Smooth residual warp on top of refined.json, optimised with the gap objective.

Offsets (dx, dy) in photo pixels live on an NX x NY control grid spanning the
LCD and are bilinearly interpolated to every LCD pixel.
"""

import json

import numpy as np
from PIL import Image

from refine_fit import CORNERS_UV, GAP, U, V, homography, img, project
from fit_grid import H, W

NX, NY = 9, 3
ref = json.load(open("refined.json"))
Hm = homography(CORNERS_UV, np.array(ref["corners"]))
X0, Y0 = project(Hm, ref["k1"], U, V)

gx = U / W * (NX - 1)
gy = V / H * (NY - 1)
ix = np.clip(np.floor(gx).astype(int), 0, NX - 2)
iy = np.clip(np.floor(gy).astype(int), 0, NY - 2)
fx, fy = gx - ix, gy - iy


def interp(g):
    return ((1 - fx) * (1 - fy) * g[iy, ix] + fx * (1 - fy) * g[iy, ix + 1]
            + (1 - fx) * fy * g[iy + 1, ix] + fx * fy * g[iy + 1, ix + 1])


def sample(ox, oy):
    X, Y = X0 + interp(ox), Y0 + interp(oy)
    xi, yi = np.floor(X).astype(int), np.floor(Y).astype(int)
    ax, ay = X - xi, Y - yi
    return ((1 - ax) * (1 - ay) * img[yi, xi] + ax * (1 - ay) * img[yi, xi + 1]
            + (1 - ax) * ay * img[yi + 1, xi] + ax * ay * img[yi + 1, xi + 1])


def score(ox, oy):
    s = sample(ox, oy)
    return np.percentile(s[~GAP], 80) - s[GAP].mean()


ox, oy = np.zeros((NY, NX)), np.zeros((NY, NX))
best = score(ox, oy)
print("start", round(best, 2))
for step in (1.0, 0.5, 0.25, 0.125):
    improved = True
    while improved:
        improved = False
        for g in (ox, oy):
            for j in range(NY):
                for i in range(NX):
                    for d in (-step, step):
                        g[j, i] += d
                        sc = score(ox, oy)
                        if sc > best and abs(g[j, i]) <= 4:
                            best, improved = sc, True
                        else:
                            g[j, i] -= d
print("final", round(best, 2))
print("ox", np.round(ox, 2).tolist())
print("oy", np.round(oy, 2).tolist())

vals = sample(ox, oy)
thr = 0.5 * (np.percentile(vals, 5) + np.percentile(vals, 95))
bits = vals >= thr
np.save("bits.npy", bits)
np.save("vals.npy", vals)
json.dump({"ox": ox.tolist(), "oy": oy.tolist(), "thr": thr}, open("warp.json", "w"))
Image.fromarray((bits * 255).astype(np.uint8)).resize((960, 256), Image.NEAREST).save("recovered_w.png")
span = np.percentile(vals, 95) - np.percentile(vals, 5)
print("lit in gap columns", int(bits[:, 0::6].sum()), "lit in gap rows", int(bits[0::8].sum()))
print("near-threshold pixels (<15% of span)", int((np.abs(vals - thr) / span < 0.15).sum()))
