"""Reference for the wave view pixels drawn by mods/wave.asm (240 x 64 LCD).

Column c covers samples [c*len//240, max((c+1)*len//240, that + 1)). Its line
runs from row 31 - (max >> 11) to row 31 - (min >> 11), so the wave fills
rows 16..47 around the zero line (row 31). The columns holding soft start
through soft end are inverted over rows 16..47.
"""

from __future__ import annotations

COLS, ROWS, MID, TOP, BOT = 240, 64, 31, 16, 47


def bound(c: int, length: int) -> int:
    return c * length // COLS


def column(pos: int, length: int) -> int:
    return max(c for c in range(COLS) if bound(c, length) <= pos)


def lines(samples: list[int]) -> list[tuple[int, int]]:
    n = len(samples)
    out = []
    for c in range(COLS):
        lo = bound(c, n)
        hi = max(bound(c + 1, n), lo + 1)
        part = samples[lo:hi]
        out.append((MID - (max(part) >> 11), MID - (min(part) >> 11)))
    return out


def pixels(samples: list[int], start: int, end: int) -> list[str]:
    """Rows of '#' (lit) and '.', as emu/probe.lua writes lcd_pixels.txt."""
    lit = [[False] * COLS for _ in range(ROWS)]
    for x, (top, bot) in enumerate(lines(samples)):
        for y in range(top, bot + 1):
            lit[y][x] = True
    for x in range(column(start, len(samples)), column(end, len(samples)) + 1):
        for y in range(TOP, BOT + 1):
            lit[y][x] = not lit[y][x]
    return ["".join("#" if p else "." for p in row) for row in lit]
