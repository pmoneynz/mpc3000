"""Assemble MAME's mpc3000 romset in build/roms/mpc3000/.

OS chips are copied from 07-rom/ under the names the driver expects.
Two files are placeholders that do not match the driver's hashes:

- the panel MCU ROM (dump absent, notes/front_panel.md): 32 KiB of 0xFF;
  the driver's panel HLE supplies keys, pads, dial and slider.
- hd61830.bin, the LCD character generator, built from emu/font/glyphs.json
  (glass photos). Layout follows MAME hd61830_device::draw_char: codes
  0x20..0x7F at (code-0x20)*7, 0xA0..0xDF at 96*7 + (code-0xA0)*7,
  0xE0..0xFF at 160*7 + (code-0xE0)*11; bit 0 is the leftmost pixel.
  Codes with no photo evidence get a hatch so they are visibly unproven.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROM = REPO / "07-rom"
GLYPHS = REPO / "emu" / "font" / "glyphs.json"
ROMS = REPO / "build" / "roms"

CHIPS = {
    "mpc312ls.bin": "v3.12/MPC312LS.BIN",
    "mpc312ms.bin": "v3.12/MPC312MS.BIN",
    "3.50 vailixi lse.bin": "Vailixi 3.50/3.50 Vailixi (LSE).BIN",
    "3.50 vailixi mso.bin": "Vailixi 3.50/3.50 Vailixi (MSO).BIN",
    "mpc311ls.bin": "v3.11/MPC311LS.BIN",
    "mpc311ms.bin": "v3.11/MPC311MS.BIN",
    "mpc3000_v3.08_lsb.bin": "v3.08/MPC3000_V3.08_LSB.BIN",
    "mpc3000_v3.08_msb.bin": "v3.08/MPC3000_V3.08_MSB.BIN",
}
PANEL = "mp3000__op_v1.0.am27c256__id0110.ic602.bin"
HATCH = [0b10101, 0b01010] * 5 + [0b10101]


def cg_rom() -> bytes:
    glyphs = {int(k, 16): v for k, v in json.loads(GLYPHS.read_text()).items()}
    rom = bytearray(0x5C0)

    def put(base: int, rows: list[int]) -> None:
        rom[base : base + len(rows)] = bytes(rows)

    for code in range(0x20, 0x80):
        g = glyphs.get(code)
        put((code - 0x20) * 7, [int(f"{r:05b}"[::-1], 2) for r in g["rows"]] if g else HATCH[:7])
    for code in range(0xA0, 0xE0):
        put(96 * 7 + (code - 0xA0) * 7, HATCH[:7])
    for code in range(0xE0, 0x100):
        put(160 * 7 + (code - 0xE0) * 11, HATCH)
    return bytes(rom)


def build() -> Path:
    """Write the set if any file differs; return the -rompath directory."""
    files = {name: (ROM / src).read_bytes() for name, src in CHIPS.items()}
    files[PANEL] = b"\xff" * 0x8000
    files["hd61830.bin"] = cg_rom()
    out = ROMS / "mpc3000"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = out / name
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    return ROMS


if __name__ == "__main__":
    print(build() / "mpc3000")
