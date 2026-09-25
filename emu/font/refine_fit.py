"""Refine homography + k1 so every cell's gap column and gap row sample dark.

Model parameters: photo positions of the four LCD corners (8) and radial k1.
Start: homog.json.  Gap geometry (from the recovered bitmap): gap column is
u % 6 == 0 and gap row is v % 8 == 0 in the LCD frame used here.
"""

import json

import numpy as np
from PIL import Image

from fit_grid import H, W, load

img = load("lcd_play_record.jpg")
CX, CY = img.shape[1] / 2, img.shape[0] / 2
CORNERS_UV = np.array([[0, 0], [W, 0], [W, H], [0, H]], float)
U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
GAP = (U.astype(int) % 6 == 0) | (V.astype(int) % 8 == 0)


def homography(src, dst):
    A = []
    for (u, v), (x, y) in zip(src, dst):
        A.append([u, v, 1, 0, 0, 0, -u * x, -v * x, -x])
        A.append([0, 0, 0, u, v, 1, -u * y, -v * y, -y])
    h = np.linalg.svd(np.array(A))[2][-1]
    return (h / h[-1]).reshape(3, 3)


def project(Hm, k1, u, v):
    d = Hm[2, 0] * u + Hm[2, 1] * v + 1
    x = (Hm[0, 0] * u + Hm[0, 1] * v + Hm[0, 2]) / d
    y = (Hm[1, 0] * u + Hm[1, 1] * v + Hm[1, 2]) / d
    r2 = ((x - CX) ** 2 + (y - CY) ** 2) / CX ** 2
    return CX + (x - CX) * (1 + k1 * r2), CY + (y - CY) * (1 + k1 * r2)


def undistorted_corners(Hm):
    q = Hm @ np.vstack([CORNERS_UV.T, np.ones(4)])
    return (q[:2] / q[2]).T


def sample(corners, k1):
    Hm = homography(CORNERS_UV, corners)
    X, Y = project(Hm, k1, U, V)
    xi, yi = np.floor(X).astype(int), np.floor(Y).astype(int)
    fx, fy = X - xi, Y - yi
    return ((1 - fx) * (1 - fy) * img[yi, xi] + fx * (1 - fy) * img[yi, xi + 1]
            + (1 - fx) * fy * img[yi + 1, xi] + fx * fy * img[yi + 1, xi + 1])


def score(corners, k1):
    s = sample(corners, k1)
    return np.percentile(s[~GAP], 80) - s[GAP].mean()


if __name__ == "__main__":
    start = json.load(open("homog.json"))
    corners = undistorted_corners(np.append(start["h"], 1).reshape(3, 3))
    k1 = start["k1"]
    best = score(corners, k1)
    print("start", round(best, 2))
    for step in (1.0, 0.5, 0.25, 0.125):
        improved = True
        while improved:
            improved = False
            for i in range(4):
                for j in range(2):
                    for d in (-step, step):
                        corners[i, j] += d
                        sc = score(corners, k1)
                        if sc > best:
                            best, improved = sc, True
                        else:
                            corners[i, j] -= d
            for d in (-step * 0.005, step * 0.005):
                sc = score(corners, k1 + d)
                if sc > best:
                    best, k1, improved = sc, k1 + d, True
    print("final", round(best, 2), "k1", round(k1, 4))
    print("corners", np.round(corners, 2).tolist())

    vals = sample(corners, k1)
    thr = 0.5 * (np.percentile(vals, 5) + np.percentile(vals, 95))
    bits = vals >= thr
    np.save("bits.npy", bits)
    np.save("vals.npy", vals)
    json.dump({"corners": corners.tolist(), "k1": k1, "thr": thr}, open("refined.json", "w"))
    Image.fromarray((bits * 255).astype(np.uint8)).resize((960, 256), Image.NEAREST).save("recovered_r.png")
    print("lit in gap columns", int(bits[:, 0::6].sum()), "lit in gap rows", int(bits[0::8].sum()))
    print("lit per column-in-cell", [int(bits[:, k::6].sum()) for k in range(6)])
