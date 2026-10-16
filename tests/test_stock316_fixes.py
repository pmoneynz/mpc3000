"""Vailixi 3.50 fixes that stock OS 3.16 already contains (no PMONEY hook).

    python3 -m unittest tests.test_stock316_fixes -v

B4/B5 (recording past 327.6 s; full 32 MB for recording): stock 3.12
compares the sampler's tick counter with Length x 10 (tenths of a second)
signed, so a Length of 3277 or more stops the recording at the first poll
(3.12 C2E5:1429, file 0x44279).  Vailixi makes four signed operations on
Length unsigned; 3.16's load image has the same four edits.  PROVEN (bytes).
B1 ("function not implemented"): 3.12's Edit Sequence menu counts 10
entries with handlers for 1-9 (key 0 hits the message), and Mixer/Effects 3
handles only Soft Key 1.  3.16 counts 9 and switches on every soft key, as
Vailixi.  B2 (audio live during sound load/save): 3.12's mute routine
DA3F:000A is an empty stub; 3.16's 2FAB:000E writes port 6Ah (Vailixi
D980:000C without PUSHF/CLI) and is called at the same load/save sites.  B3
(sequence-memory message at the 128-sound limit): 3.12 pushes the worker's
-1..-3 straight to the error box; 3.16 negates it, byte for byte Vailixi
C20F:045F.  PROVEN (bytes).

If PMONEY ever patches these sites, these pins must move with it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from mods.route_c import MZ

ROOT = Path(__file__).resolve().parents[1]
SYS316 = ROOT / "07-rom" / "v3.16 maintenance upgrade" / "M3K316.SYS"

# image offset: (bytes, what)
LENGTH_UNSIGNED = {
    0x187C2: ("7605", "1849:0332 JNA (3.12 JNG): Length clamp"),
    0x18932: ("7604", "1849:04A2 JNA (3.12 JNG): Length clamp"),
    0x19061: ("33c9", "1849:0BD1 XOR CX,CX (3.12 CWD): Length zero-extended"),
    0x198C7: ("7709", "1849:1437 JA (3.12 JG): tick counter [D38C] versus Length x 10"),
}


B1_B2_B3 = {
    0x09585: ("6a09", "B1 0955:0035 Edit Sequence menu: 9 entries"),
    0x17CD0: ("8bda83eb7583fb057726d1e32effa70c18", "B1 1650:17D0 Mixer soft-key switch"),
    0x17D0C: ("fa1700180018e117ea17f217", "B1 1650:180C Mixer soft-key table"),
    0x2FABE: ("558bec8a46063c017406b00ee66a7a04b000e66a5dcb", "B2 2FAB:000E port 6Ah mute"),
    **{off: ("9a0e00ab2f", "B2 CALLF 2FAB:000E") for off in
       (0x2E31B, 0x2E37E, 0x3F270, 0x3F298, 0x3E817, 0x3E842, 0x12053, 0x12093, 0x120E5)},
    0x13DC5: ("8bc6f7d850", "B3 1396:0465 mov ax,si / neg ax / push ax"),
}


class StockFixes316(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.image = MZ.parse(SYS316.read_bytes()).image

    def test_length_compares_are_unsigned(self) -> None:
        for off, (want, what) in LENGTH_UNSIGNED.items():
            with self.subTest(site=hex(off), what=what):
                self.assertEqual(self.image[off:off + len(want) // 2].hex(), want)

    def test_b1_b2_b3_sites(self) -> None:
        for off, (want, what) in B1_B2_B3.items():
            with self.subTest(site=hex(off), what=what):
                self.assertEqual(self.image[off:off + len(want) // 2].hex(), want)

    def test_tick_counter_compare_and_reset(self) -> None:
        self.assertEqual(self.image[0x198C3:0x198C7].hex(), "3b068cd3")      # cmp ax,[D38C]
        self.assertEqual(self.image[0x191C9:0x191CF].hex(), "c7068cd30000")  # mov word [D38C],0


if __name__ == "__main__":
    unittest.main()
