"""5x7 font for text drawn in LCD graphics mode (mods/wave.asm, emu/wave_ref.py).

Glyphs in emu/font/glyphs.json come from glass photos of the LC7981's own
text. DESIGNED fills the other printable codes: our pixels, no claim about the
controller ROM. Rows are 5-bit, bit 4 = leftmost pixel.

    python3 -m emu.lcd_font > mods/wave_font.inc
"""

from __future__ import annotations

import json
from pathlib import Path

GLYPHS = Path(__file__).resolve().parent / "font" / "glyphs.json"

DESIGNED = {
    "!": "00100 00100 00100 00100 00000 00000 00100",
    '"': "01010 01010 01010 00000 00000 00000 00000",
    "#": "01010 01010 11111 01010 11111 01010 01010",
    "$": "00100 01111 10100 01110 00101 11110 00100",
    "'": "01100 00100 01000 00000 00000 00000 00000",
    "*": "00000 00100 10101 01110 10101 00100 00000",
    ",": "00000 00000 00000 00000 01100 00100 01000",
    ";": "00000 01100 01100 00000 01100 00100 01000",
    "?": "01110 10001 00001 00010 00100 00000 00100",
    "@": "01110 10001 00001 01101 10101 10101 01110",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "W": "10001 10001 10001 10101 10101 10101 01010",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "[": "01110 01000 01000 01000 01000 01000 01110",
    "\\": "00000 10000 01000 00100 00010 00001 00000",
    "]": "01110 00010 00010 00010 00010 00010 01110",
    "^": "00100 01010 10001 00000 00000 00000 00000",
    "_": "00000 00000 00000 00000 00000 00000 11111",
    "`": "01000 00100 00010 00000 00000 00000 00000",
    "b": "10000 10000 10110 11001 10001 10001 11110",
    "j": "00010 00000 00110 00010 00010 10010 01100",
    "v": "00000 00000 10001 10001 10001 01010 00100",
    "x": "00000 00000 10001 01010 00100 01010 10001",
    "z": "00000 00000 11111 00010 00100 01000 11111",
    "{": "00010 00100 00100 01000 00100 00100 00010",
    "|": "00100 00100 00100 00100 00100 00100 00100",
    "}": "01000 00100 00100 00010 00100 00100 01000",
    "~": "00000 00000 00000 01101 10010 00000 00000",
}


def font() -> dict[int, list[int]]:
    """Codes 0x20-0x7E -> seven 5-bit rows."""
    observed = {int(k, 16): v["rows"] for k, v in json.loads(GLYPHS.read_text()).items()}
    out = {}
    for code in range(0x20, 0x7F):
        if code in observed:
            out[code] = observed[code]
        else:
            out[code] = [int(r, 2) for r in DESIGNED[chr(code)].split()]
    return out


def columns(rows: list[int]) -> list[int]:
    """A glyph's 5 column bytes, bit 0 = top row (rows: bit 4 = leftmost pixel)."""
    return [sum(((r >> (4 - c)) & 1) << y for y, r in enumerate(rows)) for c in range(5)]


def main() -> None:
    print("; Generated from the 5x7 glyphs of `python3 -m emu.lcd_font` (row form) by")
    print("; transposing each glyph: 5 column bytes, bit 0 = top row.  Codes 20h-7Eh.")
    print("font:")
    for code, rows in font().items():
        print(f"        db {', '.join(f'0x{c:02X}' for c in columns(rows))}   ; {code:02X} {chr(code)!r}")


if __name__ == "__main__":
    main()
