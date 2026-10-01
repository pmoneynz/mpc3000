"""Reference for the wave view pixels drawn by mods/wave.asm (240 x 64 LCD).

Columns: full view, column c starts at c*len//240; fine view, at
center + (c - 120)*zoom. Column c covers [lo, max(hi, lo + 1)) where hi is
the next column's start; samples outside [0, len) count as 0. Its line runs
from row 31 - (max >> 11) to row 31 - (min >> 11) (rows 16..47). Columns
overlapping the selected pair [a, b] are inverted over rows 16..47 (in the
full view the last column reaches len). The fine view XORs column 120.

Text (emu/lcd_font.py, 6-pixel cells): glyph rows 0-6 "Edit Snd:" + name;
rows 8-14 the pair's labels and values, the selected value's ten cells
inverted over rows 7-14; rows 49-55 Length, for a stereo sound "View:" L/R
at column 19 (its cell inverted over rows 49-55 when selected), and Zoom in
the fine view; rows 57-63 soft keys. Rows 15 and 48 stay blank. Plane R is
the second plane.
"""

from __future__ import annotations

from dataclasses import dataclass

from emu.lcd_font import font

COLS, ROWS, MID, TOP, BOT = 240, 64, 31, 16, 47
PAIRS = ((("Start:", 0, 6), ("End:", 20, 24)), (("Zone st:", 0, 8), ("Zone end:", 19, 28)))


@dataclass
class View:
    points: list[int]           # soft start, soft end, zone start, zone end
    sel: int = 0                # 0..3
    fine: bool = False
    zoom: int = 16
    plane: int = 0              # 0 = L (plane A), 1 = R (plane B)
    onview: bool = False        # View field selected
    too_short: bool = False     # last Ply/Stp request was below two timer ticks
    zone_current: int = 1
    zone_count: int = 16
    zone_focus: int = 0         # 0 none, 2 current zone, 3 total count


def fmt(frames: int) -> str:
    """sss.mmm.ss, the Edit Sound field units (B99A:2619)."""
    s, r = divmod(frames, 44100)
    ms = r * 10 // 441
    return f"{s:03d}.{ms:03d}.{r - ms * 441 // 10:02d}"


def bound(c: int, n: int, v: View) -> int:
    if v.fine:
        return v.points[v.sel] + (c - COLS // 2) * v.zoom
    return c * n // COLS


def lines(samples: list[int], v: View) -> list[tuple[int, int]]:
    n = len(samples)
    out = []
    for c in range(COLS):
        lo = bound(c, n, v)
        hi = max(bound(c + 1, n, v), lo + 1)
        outside = not (0 <= lo <= n and 0 <= hi <= n)
        part = samples[min(max(lo, 0), n):min(max(hi, 0), n)] + ([0] if outside else [])
        out.append((MID - (max(part) >> 11), MID - (min(part) >> 11)))
    return out


def _text(lit: list[list[bool]], y: int, col: int, s: str) -> None:
    glyphs = font()
    for i, ch in enumerate(s):
        code = ord(ch)
        if not 0x20 <= code <= 0x7E:
            code = ord("?")
        for r, bits in enumerate(glyphs[code]):
            for x in range(5):
                if bits & (0x10 >> x):
                    lit[y + r][(col + i) * 6 + x] = True


def _invert(lit: list[list[bool]], x0: int, w: int, y0: int, h: int) -> None:
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            lit[y][x] = not lit[y][x]


def screen(planes: list[list[int]], name: str, v: View) -> list[str]:
    """The whole view, rows of '#' (lit) and '.' as emu/probe.lua writes them."""
    samples = planes[v.plane]
    n = len(samples)
    lit = [[False] * COLS for _ in range(ROWS)]
    for x, (top, bot) in enumerate(lines(samples, v)):
        for y in range(top, bot + 1):
            lit[y][x] = True
    a, b = v.points[v.sel & 2], v.points[(v.sel & 2) + 1]
    for c in range(COLS):
        end = n + 1 if not v.fine and c == COLS - 1 else bound(c + 1, n, v)
        if bound(c, n, v) <= b and end > a:
            _invert(lit, c, 1, TOP, BOT - TOP + 1)
    if v.fine:
        _invert(lit, COLS // 2, 1, TOP, BOT - TOP + 1)
    _text(lit, 0, 0, "Edit Snd:")
    _text(lit, 0, 9, name.ljust(16))
    _text(lit, 0, 30, f"ZONE:{v.zone_current:02d}/{v.zone_count:02d}")
    pair = PAIRS[v.sel >> 1]
    for i, (label, lcol, vcol) in enumerate(pair):
        _text(lit, 8, lcol, label)
        _text(lit, 8, vcol, fmt(v.points[(v.sel & 2) + i]))
    _text(lit, 49, 0, "Length:")
    _text(lit, 49, 7, fmt(n))
    if len(planes) == 2:
        _text(lit, 49, 19, "View:")
        _text(lit, 49, 24, "LR"[v.plane])
    if v.fine:
        _text(lit, 49, 33, f"Zoom:{v.zoom:02d}")
    _text(lit, 57, 21, "<Full>" if v.fine else "<Fine>")
    _text(lit, 57, 10, "<Trim>" if v.sel & 2 else "<Zone>")
    _text(lit, 57, 0, "Too short" if v.too_short else "<Ply/Stp>")
    _text(lit, 57, 34, "<Exit>")
    if v.zone_focus:
        _invert(lit, (35 if v.zone_focus == 2 else 38) * 6, 12, 0, 7)
    elif v.onview:
        _invert(lit, 24 * 6, 6, 49, 7)
    else:
        _invert(lit, pair[v.sel & 1][2] * 6, 60, 7, 8)
    return ["".join("#" if p else "." for p in row) for row in lit]
