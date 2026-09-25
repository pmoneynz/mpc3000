"""Normalise vals.npy by fitted dark and lit illumination surfaces, then threshold.

Dark level: fitted to the gap columns/rows (structurally unlit).
Lit level: fitted to samples above the running midpoint threshold.
norm = (vals - dark) / (lit - dark); bit = norm > 0.5.
"""

import numpy as np
from PIL import Image

from fit_grid import H, W

vals = np.load("vals.npy")
U, V = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
un, vn = U / W - 0.5, V / H - 0.5
B = np.stack([np.ones_like(un), un, vn, un * un, un * vn, vn * vn,
              un ** 3, un ** 4], -1)
GAP = (U.astype(int) % 6 == 0) | (V.astype(int) % 8 == 0)


def surface(mask):
    coef, *_ = np.linalg.lstsq(B[mask], vals[mask], rcond=None)
    return B @ coef


dark = surface(GAP)
lit_mask = vals > dark + 40
for _ in range(5):
    lit = surface(lit_mask & ~GAP)
    lit_mask = vals > 0.5 * (dark + lit)
norm = (vals - dark) / (lit - dark)
bits = norm > 0.5

np.save("bits.npy", bits)
np.save("norm.npy", norm)
Image.fromarray((bits * 255).astype(np.uint8)).resize((960, 256), Image.NEAREST).save("recovered_n.png")
if __name__ == "__main__":
    print("dark  u=0,120,239:", [round(float(dark[32, u])) for u in (0, 120, 239)])
    print("lit   u=0,120,239:", [round(float(lit[32, u])) for u in (0, 120, 239)])
    print("lit in gap columns", int(bits[:, 0::6].sum()), "lit in gap rows", int(bits[0::8].sum()))
    amb = (norm > 0.3) & (norm < 0.7)
    print("ambiguous pixels (0.3..0.7)", int(amb.sum()))
    vs, us = np.nonzero(amb)
    print("ambiguous cells (row,col):", sorted({(int(v) // 8, int(u) // 6) for v, u in zip(vs, us)}))
