"""LCD mirror SysEx protocol: the viewer's decoder (tools/lcd_mirror_midi_viewer.py).

    python3 -m unittest tests.test_lcd_mirror_protocol -v
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import lcd_mirror_midi_viewer as v  # noqa: E402


class Escapes(unittest.TestCase):
    def test_all_256_codes_round_trip(self) -> None:
        codes = bytes(range(256))
        enc = v.escape(codes)
        self.assertFalse(any(b & 0x80 for b in enc))
        self.assertEqual(v.unescape(enc, 256), (codes, len(enc)))
        for c in range(256):
            want = 1 if c < 0x7E else 2
            self.assertEqual(len(v.escape(bytes([c]))), want, hex(c))

    def test_row_messages_for_every_code(self) -> None:
        dec = v.Decoder()
        for seq, start in enumerate(range(0, 256, 20)):
            codes = bytes(range(start, min(start + 20, 256)))
            dec.feed(v.row_message(seq, seq % 8, 3, codes))
            self.assertEqual(bytes(dec.screen.text[seq % 8][3:3 + len(codes)]), codes)
        self.assertEqual((dec.bad, dec.drops), (0, 0))

    def test_full_row_fits(self) -> None:
        self.assertLessEqual(len(v.row_message(0, 7, 0, b"A" * 40)), v.MAX_MSG)
        with self.assertRaises(ValueError):
            v.row_message(0, 0, 0, b"\xff" * 40)       # 80 escaped bytes: the mod splits such spans


class SevenInEight(unittest.TestCase):
    def test_round_trip_every_length(self) -> None:
        rng = random.Random(3)
        for n in range(1, v.PIX_MAX + 1):
            data = bytes(rng.randrange(256) for _ in range(n))
            packed = v.pack7(data)
            self.assertEqual(len(packed), n + (n + 6) // 7)
            self.assertEqual(v.unpack7(packed, n), data)

    def test_pix_message(self) -> None:
        dec = v.Decoder()
        data = bytes(range(0x70, 0x90))
        msg = v.pix_message(0, 1888, data)
        self.assertLessEqual(len(msg), v.MAX_MSG)
        dec.feed(msg)
        self.assertEqual(bytes(dec.screen.fb[1888:1920]), data)
        dec.feed(v.pix_message(1, 1900, data))         # past 1919
        self.assertEqual(dec.bad, 1)


class Stream(unittest.TestCase):
    def test_drops_counted_across_wrap(self) -> None:
        dec = v.Decoder()
        for seq in (125, 126, 127, 0, 3, 4):
            dec.feed(v.message(v.FULL, seq))
        self.assertEqual(dec.drops, 2)
        self.assertEqual(dec.messages, 6)

    def test_noise_and_realtime(self) -> None:
        dec = v.Decoder()
        msg = v.row_message(0, 1, 0, b"Hello")
        noisy = b"\x90\x3c\x7f\xf8" + msg[:6] + b"\xf8\xfe" + msg[6:] + b"\x80\x3c\x00"
        self.assertEqual(dec.feed(noisy), [msg])
        self.assertEqual(dec.screen.text_lines()[1][:5], "Hello")
        dec.feed(b"\xf0\x7d\x4d\x33\x4b\x02\x01\x90\x3c\x7f")   # broken by a note-on
        self.assertEqual(dec.aborted, 1)
        dec.feed(b"\xf0\x43\x10\x4c\xf7")                        # someone else's SysEx
        self.assertEqual(dec.foreign, 1)
        self.assertEqual(dec.bad, 0)

    def test_mode_cursor_hello(self) -> None:
        dec = v.Decoder()
        dec.feed(v.message(v.HELLO, 0, bytes([1, 1, 3, 16])))
        dec.feed(v.message(v.MODE, 1, b"\x01"))
        dec.feed(v.message(v.CURSOR, 2, bytes([2, 39, 0x7F, 1])))
        s = dec.screen
        self.assertEqual((s.hello, s.graphics, s.cursor), ((1, 1, 3, 16), True, (2, 39, 0xFF)))

    def test_malformed_rows(self) -> None:
        dec = v.Decoder()
        dec.feed(v.message(v.ROW, 0, bytes([8, 0, 1, 0x41])))        # row 8
        dec.feed(v.message(v.ROW, 1, bytes([0, 39, 2, 0x41, 0x42])))  # past column 39
        dec.feed(v.message(v.ROW, 2, bytes([0, 0, 2, 0x41])))        # short
        self.assertEqual(dec.bad, 3)
        self.assertEqual(dec.screen.text_lines()[0], " " * 40)


if __name__ == "__main__":
    unittest.main()
