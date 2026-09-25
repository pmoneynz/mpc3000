"""Reference for the wave view pixels drawn by mods/wave.asm (240 x 64 LCD).

screen() is the whole view. Text uses emu/lcd_font.py in 6 x 8 cells: row 0
"Edit Snd:" + name, row 1 Start (col 6) and End (col 24) values, row 6 Length,
row 7 soft keys. The selected value's ten cells are inverted.

Column c covers samples [c*len//240, max((c+1)*len//240, that + 1)). Its line
runs from row 31 - (max >> 11) to row 31 - (min >> 11), so the wave fills
rows 16..47 around the zero line (row 31). The columns holding soft start
through soft end are inverted over rows 16..47.
"""

from __future__ import annotations

from emu.lcd_font import font

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


KEYS = "<Start>   <End>                   <Exit>"


def fmt(frames: int) -> str:
    """sss.mmm.ss, the Edit Sound field units (B99A:2619)."""
    s, r = divmod(frames, 44100)
    ms = r * 10 // 441
    return f"{s:03d}.{ms:03d}.{r - ms * 441 // 10:02d}"


def _text(lit: list[list[bool]], row: int, col: int, s: str) -> None:
    glyphs = font()
    for i, ch in enumerate(s):
        for y, bits in enumerate(glyphs[ord(ch)]):
            for x in range(5):
                if bits & (0x10 >> x):
                    lit[row * 8 + y][(col + i) * 6 + x] = True


def screen(samples: list[int], name: str, start: int, end: int, sel: int) -> list[str]:
    """The whole wave view; sel 0 = Start selected, 1 = End."""
    lit = _lit(samples, start, end)
    _text(lit, 0, 0, "Edit Snd:")
    _text(lit, 0, 9, name.ljust(16))
    _text(lit, 1, 0, "Start:")
    _text(lit, 1, 20, "End:")
    _text(lit, 6, 0, "Length:")
    _text(lit, 7, 0, KEYS)
    _text(lit, 1, 6, fmt(start))
    _text(lit, 1, 24, fmt(end))
    _text(lit, 6, 7, fmt(len(samples)))
    x0 = (6, 24)[sel] * 6
    for y in range(8, 16):
        for x in range(x0, x0 + 60):
            lit[y][x] = not lit[y][x]
    return _rows(lit)


def _rows(lit: list[list[bool]]) -> list[str]:
    return ["".join("#" if p else "." for p in row) for row in lit]


def _lit(samples: list[int], start: int, end: int) -> list[list[bool]]:
    lit = [[False] * COLS for _ in range(ROWS)]
    for x, (top, bot) in enumerate(lines(samples)):
        for y in range(top, bot + 1):
            lit[y][x] = True
    for x in range(column(start, len(samples)), column(end, len(samples)) + 1):
        for y in range(TOP, BOT + 1):
            lit[y][x] = not lit[y][x]
    return lit
