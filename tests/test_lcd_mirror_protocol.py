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
            want = 1 if c < 0x7D else 2
            self.assertEqual(len(v.escape(bytes([c]))), want, hex(c))

    def test_row_messages_for_every_code(self) -> None:
        dec = v.Decoder()
        for seq, start in enumerate(range(0, 256, 20)):
            codes = bytes(range(start, min(start + 20, 256)))
            dec.feed(v.row_message(seq, seq % 8, 3, codes))
            self.assertEqual(bytes(dec.screen.text[seq % 8][3:3 + len(codes)]), codes)
        self.assertEqual((dec.bad, dec.drops), (0, 0))

    def test_full_row_fits(self) -> None:
        self.assertLessEqual(len(v.row_message(0, 7, 0, bytes(range(0x30, 0x58)))), v.MAX_MSG)
        with self.assertRaises(ValueError):
            v.row_message(0, 0, 0, bytes(range(0x80, 0xA8)))   # 80 escaped bytes: the mod splits such spans

    def test_runs(self) -> None:
        row = b"=" * 13 + b" Play/Record " + b"=" * 14
        enc = v.escape(row)
        self.assertEqual(enc[:3], bytes([0x7D, 13, 0x3D]))
        self.assertEqual(v.unescape(enc, len(row)), (row, len(enc)))
        for code in (0x00, 0x20, 0x7D, 0x7E, 0x7F, 0x80, 0xFF):
            for n in (1, 3, 4, 5, 40):
                codes = bytes([code]) * n + b"x"
                self.assertEqual(v.unescape(v.escape(codes), len(codes))[0], codes, (code, n))
        self.assertEqual(v.escape(b"\x7d"), b"\x7f\x7d")          # a literal 7D is escaped

    def test_bad_runs(self) -> None:
        dec = v.Decoder()
        dec.feed(v.message(v.ROW, 0, bytes([0, 0, 5, 0x7D, 3, 0x41, 0x41, 0x41])))   # run under 4
        dec.feed(v.message(v.ROW, 1, bytes([0, 0, 4, 0x7D, 6, 0x41])))               # run past len
        self.assertEqual(dec.bad, 2)


class SevenInEight(unittest.TestCase):
    def test_round_trip_every_length(self) -> None:
        rng = random.Random(3)
        for n in range(1, v.PIX_MAX + 1):
            data = bytes(rng.randrange(256) for _ in range(n))
            packed = v.pack7(data)
            self.assertEqual(len(packed), n + (n + 6) // 7)
            self.assertEqual(v.unpack7(packed, n), data)

    def test_pcopy(self) -> None:
        dec = v.Decoder()
        dec.feed(v.pix_message(0, 0, bytes(range(1, 31))))
        dec.feed(v.pcopy_message(1, 30, 90, 30))                 # overlapping: rows 1-3 copy row 0
        self.assertEqual(bytes(dec.screen.fb[:120]), bytes(range(1, 31)) * 4)
        dec.feed(v.pcopy_message(2, 10, 5, 11))                  # distance past the start
        dec.feed(v.pcopy_message(3, 1900, 30, 30))               # past 1919
        self.assertEqual((dec.bad, dec.messages), (2, 2))

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
        dec.feed(v.message(v.HELLO, 0, bytes([2, 2, 3, 16])))
        dec.feed(v.message(v.MODE, 1, b"\x01"))
        dec.feed(v.message(v.CURSOR, 2, bytes([2, 39, 0x7F, 1])))
        s = dec.screen
        self.assertEqual((s.hello, s.graphics, s.cursor), ((2, 2, 3, 16), True, (2, 39, 0xFF)))

    def test_malformed_rows(self) -> None:
        dec = v.Decoder()
        dec.feed(v.message(v.ROW, 0, bytes([8, 0, 1, 0x41])))        # row 8
        dec.feed(v.message(v.ROW, 1, bytes([0, 39, 2, 0x41, 0x42])))  # past column 39
        dec.feed(v.message(v.ROW, 2, bytes([0, 0, 2, 0x41])))        # short
        self.assertEqual(dec.bad, 3)
        self.assertEqual(dec.screen.text_lines()[0], " " * 40)


class Live(unittest.TestCase):
    """run_live --headless with a fake input: settled printing, counters, reconnect."""

    def test_headless_prints_settled_screens_and_reconnects(self) -> None:
        import argparse
        import contextlib
        import io
        msgs = [v.message(v.HELLO, 0, bytes([2, 2, 3, 16])), v.message(v.FULL, 1),
                v.row_message(2, 0, 0, b"Hello"), v.row_message(3, 1, 0, b"World"),
                v.message(v.CURSOR, 4, bytes([1, 2, 3, 0]))]
        opened = []
        clock = [1000.0]

        class Fake:
            lib = "fake"

            def __init__(self, name):
                opened.append(name)
                self.name = f"Fake {len(opened)}"
                self.polls = 0

            def poll(self):
                self.polls += 1
                clock[0] += 0.05
                if len(opened) == 1 and self.polls <= len(msgs):
                    return list(msgs[self.polls - 1])
                if len(opened) == 2 and self.polls > 5:
                    raise KeyboardInterrupt
                return []

            def present(self):
                return not (len(opened) == 1 and self.polls > 8)

            def close(self):
                pass
        out = io.StringIO()
        old = (v.Input, v.time.time, v.time.sleep)
        v.Input, v.time.time, v.time.sleep = Fake, lambda: clock[0], lambda s: None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(KeyboardInterrupt):
                    v.run_live(argparse.Namespace(port="x", log=None, headless=True))
        finally:
            v.Input, v.time.time, v.time.sleep = old
        text = out.getvalue()
        self.assertEqual(len(opened), 2, "reconnected after the port vanished")
        self.assertIn("|Hello", text)
        self.assertIn("|World", text)
        self.assertIn("^ cursor mode 3", text)
        self.assertIn("drops 0 dups 0 bad 0 aborted 0 foreign 0", text)

    def test_hello_resyncs_and_dups(self) -> None:
        dec = v.Decoder()
        for seq in (10, 11, 11, 12):
            dec.feed(v.message(v.FULL, seq))
        dec.feed(v.message(v.HELLO, 0, bytes([2, 2, 3, 16])))        # the MPC rebooted
        dec.feed(v.message(v.FULL, 1))
        self.assertEqual((dec.drops, dec.dups), (0, 1))
        dec.feed(b"\xf0\x43" + b"\x01" * 5000 + b"\xf7")           # long foreign SysEx
        self.assertEqual((dec.foreign, dec.bad), (1, 0))
        dec.feed(v.HEADER + b"\x06\x02" + b"\x00" * 60 + b"\xf7")  # ours, over 64 bytes
        self.assertEqual(dec.bad, 1)
        dec.feed(v.message(v.MODE, 3, b"\x05"))
        dec.feed(v.message(v.CURSOR, 4, bytes([9, 77, 0, 0])))
        self.assertEqual(dec.bad, 3)


if __name__ == "__main__":
    unittest.main()
