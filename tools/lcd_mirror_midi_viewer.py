#!/usr/bin/env python3
"""Viewer for the MPC3000 LCD mirror (mods/lcdmirror316.inc) over MIDI SysEx.

    python3 tools/lcd_mirror_midi_viewer.py [--port NAME] [--log FILE] [--headless]
    python3 tools/lcd_mirror_midi_viewer.py --replay MIDI.log [--out-port 4]

The mod streams the 40x8 text screen (and the Mixer page's 240x64 pixels) as
SysEx; this program decodes the stream and draws it.  Protocol (frozen, version
2; notes/lcd_mirror_midi.md "Protocol"):

    F0 7D 4D 33 4B <type> <seq> <payload...> F7      at most 64 bytes

7D is the non-commercial manufacturer ID, 4D 33 4B is "M3K", seq a 7-bit count
that increments per message (gaps are drops).  Types:

    01 HELLO   proto, mod version, OS major, OS minor (03 10 = 3.16)
    02 ROW     row 0..7, col 0..39, len 1..40, codes (escaped, run tokens; len = decoded count)
    03 CURSOR  row, col, mode lo7, mode hi1   (BIOS cursor; mode = OS cursor-mode byte)
    04 MODE    00 text, 01 graphics (Mixer)
    05 PIX     offset hi7, offset lo7 (0..1919), len 1..32, bytes packed 7-in-8
    06 FULL    a full repaint follows
    07 PCOPY   offset hi7, offset lo7, len 1..127, distance hi7, distance lo7: framebuffer
               bytes offset+i = offset-distance+i for i = 0..len-1, in that order (overlap allowed)

Character escape: a code below 7D is sent as itself; 7E nn is code 80|nn; 7F nn
is the literal nn (for 7D, 7E and 7F); 7D n c is n (4..127) copies of the code c,
itself escaped (protocol 2; protocol 1 had no run token and sent 7D as itself).  7-in-8: per group of up to 7 bytes, one
byte of high bits (bit i = bit 7 of the group's byte i), then each byte & 7F.
PIX bytes are the OS framebuffer (DGROUP 1579h, 30 bytes per row) as stored.

Input: python-rtmidi or mido (whichever is installed) for a live port; --replay
reads the replay host's --midi-log ("<seconds> <port> 0x<byte>" per line).
The Tk window needs a Python with _tkinter; --headless prints each settled
screen instead.  Any other MIDI on the port is ignored.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HEADER = bytes([0xF0, 0x7D, 0x4D, 0x33, 0x4B])
MAX_MSG = 64
PROTO = 2
HELLO, ROW, CURSOR, MODE, PIX, FULL, PCOPY = 1, 2, 3, 4, 5, 6, 7
RUN = 0x7D
RUN_MIN = 4
COLS, ROWS = 40, 8
FB_W, FB_H, FB_STRIDE = 240, 64, 30
FB_SIZE = FB_STRIDE * FB_H          # 1920
PIX_MAX = 32
# Bits of a framebuffer byte, left to right: True = bit 7 is the leftmost pixel
# (the OS bit-reverses each byte for the LC7981).  PROVEN (MAME): the Mixer page
# decoded this way equals lcd_pixels.txt with 0 differing pixels, and with
# bit 0 leftmost differs in 6374 (emu/test_lcdmirror316.py).
FB_MSB_LEFT = True


# ---------------------------------------------------------------- encoder (reference)

def escape1(c: int) -> bytes:
    if c < RUN:
        return bytes([c])
    if c >= 0x80:
        return bytes([0x7E, c & 0x7F])
    return bytes([0x7F, c])


def escape(codes: bytes) -> bytes:
    """Protocol 2 encoding of codes: runs of RUN_MIN or more become 7D n c."""
    out, i = bytearray(), 0
    while i < len(codes):
        j = i
        while j < len(codes) and codes[j] == codes[i] and j - i < 127:
            j += 1
        if j - i >= RUN_MIN:
            out += bytes([RUN, j - i]) + escape1(codes[i])
            i = j
        else:
            out += escape1(codes[i])
            i += 1
    return bytes(out)


def pack7(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 7):
        group = data[i:i + 7]
        out.append(sum(((b >> 7) & 1) << j for j, b in enumerate(group)))
        out += bytes(b & 0x7F for b in group)
    return bytes(out)


def message(kind: int, seq: int, payload: bytes = b"") -> bytes:
    msg = HEADER + bytes([kind, seq & 0x7F]) + payload + b"\xF7"
    if len(msg) > MAX_MSG or any(b & 0x80 for b in msg[1:-1]):
        raise ValueError(f"bad message {msg.hex()}")
    return msg


def row_message(seq: int, row: int, col: int, codes: bytes) -> bytes:
    return message(ROW, seq, bytes([row, col, len(codes)]) + escape(codes))


def pix_message(seq: int, offset: int, data: bytes) -> bytes:
    return message(PIX, seq, bytes([offset >> 7, offset & 0x7F, len(data)]) + pack7(data))


def pcopy_message(seq: int, offset: int, length: int, distance: int) -> bytes:
    return message(PCOPY, seq, bytes([offset >> 7, offset & 0x7F, length, distance >> 7, distance & 0x7F]))


# ---------------------------------------------------------------- decoder

def unescape(data: bytes, count: int) -> tuple[bytes, int]:
    """`count` codes from escaped `data`; returns (codes, bytes consumed)."""
    out, i = bytearray(), 0

    def one(at: int) -> tuple[int, int]:
        b = data[at]
        if b == 0x7E:
            return 0x80 | data[at + 1], at + 2
        if b == 0x7F:
            return data[at + 1], at + 2
        if b == RUN or b & 0x80:
            raise ValueError("bad code byte")
        return b, at + 1
    while len(out) < count:
        if data[i] == RUN:
            n = data[i + 1]
            if not RUN_MIN <= n <= 127:
                raise ValueError("bad run")
            c, i = one(i + 2)
            out += bytes([c]) * n
        else:
            c, i = one(i)
            out.append(c)
    if len(out) != count:
        raise ValueError("run past len")
    return bytes(out), i


def unpack7(data: bytes, count: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < count:
        hi = data[i]; i += 1
        for j in range(min(7, count - len(out))):
            out.append(data[i] | (((hi >> j) & 1) << 7)); i += 1
    if i != len(data):
        raise ValueError("PIX length mismatch")
    return bytes(out)


@dataclass
class Screen:
    text: list[bytearray] = field(default_factory=lambda: [bytearray(b" " * COLS) for _ in range(ROWS)])
    fb: bytearray = field(default_factory=lambda: bytearray(FB_SIZE))
    graphics: bool = False
    cursor: tuple[int, int, int] = (0, 0, 0)        # row, col, mode
    hello: tuple[int, ...] | None = None

    def text_lines(self) -> list[str]:
        return ["".join(chr(c) if 0x20 <= c < 0x7F else "?" for c in r) for r in self.text]

    def text_codes(self) -> list[bytes]:
        return [bytes(r) for r in self.text]

    def fb_pixels(self, msb_left: bool = FB_MSB_LEFT) -> list[str]:
        rows = []
        for y in range(FB_H):
            line = []
            for b in self.fb[y * FB_STRIDE:(y + 1) * FB_STRIDE]:
                bits = range(7, -1, -1) if msb_left else range(8)
                line += ["#" if (b >> k) & 1 else "." for k in bits]
            rows.append("".join(line))
        return rows


class Decoder:
    """Feed MIDI bytes; SysEx in this protocol updates `screen`.

    Real-time bytes (F8..FF) inside a SysEx are skipped, as MIDI allows; any
    other status byte ends it (`aborted`).  SysEx of other makers is skipped
    whole (`foreign`).  `drops` counts missing sequence numbers (a HELLO resyncs:
    the MPC rebooted or the viewer joined late; a repeated number counts in
    `dups`); `bad` counts malformed protocol messages.  `events` keeps the last
    few counter changes for the log.
    """

    def __init__(self) -> None:
        self.screen = Screen()
        self.buf: bytearray | None = None
        self.skip = False                   # inside a foreign SysEx
        self.seq: int | None = None
        self.messages = self.drops = self.dups = self.bad = self.aborted = self.foreign = 0
        self.kinds: dict[int, int] = {}
        self.longest = 0
        self.events: list[str] = []

    def counters(self) -> str:
        return (f"msgs {self.messages} drops {self.drops} dups {self.dups} bad {self.bad} "
                f"aborted {self.aborted} foreign {self.foreign}")

    def _event(self, what: str) -> None:
        self.events.append(what)
        del self.events[:-64]

    def feed(self, data: bytes | int) -> list[bytes]:
        """Returns the complete protocol messages decoded from `data`."""
        done = []
        for b in ([data] if isinstance(data, int) else data):
            if b >= 0xF8:
                continue
            if b == 0xF0:
                if self.buf is not None:
                    self.aborted += 1
                    self._event("aborted by F0")
                self.buf, self.skip = bytearray([b]), False
            elif self.buf is None:
                continue
            elif b == 0xF7:
                msg = bytes(self.buf + b"\xF7")
                self.buf, skip, self.skip = None, self.skip, False
                if skip:
                    self.foreign += 1
                elif self._handle(msg):
                    done.append(msg)
            elif b & 0x80:
                self.aborted += 1
                self._event(f"aborted by {b:02X}")
                self.buf = None
            elif self.skip:
                continue
            else:
                self.buf.append(b)
                n = len(self.buf)
                if n <= len(HEADER) and self.buf != HEADER[:n]:
                    self.skip = True                    # someone else's SysEx
                elif n >= MAX_MSG:                      # ours, longer than any we send
                    self.bad += 1
                    self._event("bad: over 64 bytes")
                    self.skip = True
        return done

    def _handle(self, msg: bytes) -> bool:
        if not msg.startswith(HEADER):
            self.foreign += 1
            return False
        self.longest = max(self.longest, len(msg))
        if len(msg) < 8:
            self.bad += 1
            self._event("bad: short")
            return False
        kind, seq, p = msg[5], msg[6], msg[7:-1]
        if kind == HELLO or self.seq is None:
            pass                                        # resync
        elif seq == self.seq:
            self.dups += 1
            self._event(f"dup seq {seq}")
        else:
            gap = (seq - self.seq - 1) & 0x7F
            if gap:
                self.drops += gap
                self._event(f"drop {gap} before seq {seq}")
        self.seq = seq
        try:
            self._apply(kind, p)
        except (IndexError, ValueError) as exc:
            self.bad += 1
            self._event(f"bad: {exc} {msg.hex()}")
            return False
        self.messages += 1
        self.kinds[kind] = self.kinds.get(kind, 0) + 1
        return True

    def _apply(self, kind: int, p: bytes) -> None:
        s = self.screen
        if kind == HELLO:
            if len(p) != 4:
                raise ValueError("HELLO length")
            s.hello = tuple(p)
        elif kind == ROW:
            row, col, n = p[0], p[1], p[2]
            codes, used = unescape(p[3:], n)
            if row >= ROWS or not 1 <= n <= COLS or col + n > COLS or 3 + used != len(p):
                raise ValueError("ROW out of range")
            s.text[row][col:col + n] = codes
        elif kind == CURSOR:
            if len(p) != 4 or p[0] >= ROWS or p[1] >= COLS or p[3] > 1:
                raise ValueError("CURSOR out of range")
            s.cursor = (p[0], p[1], p[2] | (p[3] << 7))
        elif kind == MODE:
            if len(p) != 1 or p[0] > 1:
                raise ValueError("MODE value")
            s.graphics = p[0] == 1
        elif kind == PIX:
            off, n = (p[0] << 7) | p[1], p[2]
            if not 1 <= n <= PIX_MAX or off + n > FB_SIZE:
                raise ValueError("PIX out of range")
            s.fb[off:off + n] = unpack7(p[3:], n)
        elif kind == FULL:
            if p:
                raise ValueError("FULL length")
        elif kind == PCOPY:
            if len(p) != 5:
                raise ValueError("PCOPY length")
            off, n, d = (p[0] << 7) | p[1], p[2], (p[3] << 7) | p[4]
            if not 1 <= n <= 127 or not 1 <= d <= off or off + n > FB_SIZE:
                raise ValueError("PCOPY out of range")
            for i in range(n):
                s.fb[off + i] = s.fb[off - d + i]
        else:
            raise ValueError(f"unknown type {kind}")


def read_replay_log(path: Path, port: int) -> list[tuple[float, int]]:
    """(emulated seconds, byte) of one MIDI OUT from mpc3k_replay --midi-log."""
    out = []
    for line in path.read_text().splitlines():
        t, p, b = line.split()
        if int(p) == port:
            out.append((float(t), int(b, 16)))
    return out


# ---------------------------------------------------------------- live input

class Input:
    """One MIDI input through python-rtmidi, else mido.  `poll()` returns the bytes
    received since the last call; `present()` says whether the port is still listed
    (neither library reports a vanished port on read)."""

    def __init__(self, name: str | None) -> None:
        self.want = name
        try:
            import rtmidi                               # python-rtmidi
            self.lib = "rtmidi"
            self.mi = rtmidi.MidiIn()
            self.mi.ignore_types(sysex=False, timing=True, active_sense=True)
            ports = self.mi.get_ports()
            idx = self._pick(ports)
            self.mi.open_port(idx)
            self.name = ports[idx]
        except ImportError:
            import mido
            self.lib = "mido"
            ports = mido.get_input_names()
            self.name = ports[self._pick(ports)]
            self.port = mido.open_input(self.name)

    def _pick(self, ports: list[str]) -> int:
        for i, p in enumerate(ports):
            if self.want is None or self.want.lower() in p.lower():
                return i
        raise OSError(f"no MIDI input matching {self.want!r} in {ports}")

    def poll(self) -> list[int]:
        data: list[int] = []
        if self.lib == "rtmidi":
            while (m := self.mi.get_message()) is not None:
                data += m[0]
        else:
            for m in self.port.iter_pending():
                data += m.bytes()
        return data

    def present(self) -> bool:
        if self.lib == "rtmidi":
            return self.name in self.mi.get_ports()
        import mido
        return self.name in mido.get_input_names()

    def close(self) -> None:
        try:
            self.mi.close_port() if self.lib == "rtmidi" else self.port.close()
        except Exception:                               # noqa: BLE001 - closing a dead port
            pass


def describe(msg: bytes) -> str:
    names = {HELLO: "HELLO", ROW: "ROW", CURSOR: "CURSOR", MODE: "MODE", PIX: "PIX", FULL: "FULL", PCOPY: "PCOPY"}
    return f"{names.get(msg[5], '?')} seq={msg[6]} {msg[7:-1].hex()}"


def screen_text(s: Screen) -> list[str]:
    """The settled screen for --headless: text with a ^ under the cursor, or pixels."""
    if s.graphics:
        return ["(graphics)"] + s.fb_pixels()
    rows = [f"|{r}|" for r in s.text_lines()]
    row, col, mode = s.cursor
    rows.insert(row + 1, " " * (col + 1) + f"^ cursor mode {mode}")
    return rows


QUIET = 0.1          # seconds without a protocol message before --headless prints


def run_live(args: argparse.Namespace) -> int:
    dec = Decoder()
    log = open(args.log, "a") if args.log else None

    def note(text: str) -> None:
        if log:
            log.write(f"{time.time():.3f} {text}\n")
            log.flush()
    ui = None if args.headless else TkView()
    inp: Input | None = None
    last_data = last_msg = time.time()
    last_check = last_warn = 0.0
    printed: list[str] | None = None
    while True:
        now = time.time()
        if inp is None:
            try:
                inp = Input(args.port)
                print(f"listening on {inp.name} ({inp.lib})", file=sys.stderr)
                note(f"open {inp.name}")
            except ImportError:
                print("install python-rtmidi (or mido)", file=sys.stderr)
                return 2
            except Exception as exc:                    # noqa: BLE001 - rtmidi raises its own types
                print(f"{exc}; retrying", file=sys.stderr)
                if ui and not ui.draw(dec, "no MIDI input; retrying", 0):
                    return 0
                time.sleep(1.0)
                continue
        data = inp.poll()
        if data:
            last_data = now
        for msg in dec.feed(bytes(data)):
            last_msg = now
            note(describe(msg))
        for e in dec.events:
            note(f"EVENT {e} | {dec.counters()}")
        dec.events.clear()
        if now - last_check > 2.0:
            last_check = now
            if not inp.present():
                print(f"{inp.name} disappeared; reconnecting", file=sys.stderr)
                note(f"lost {inp.name}")
                inp.close()
                inp = None
                continue
        age = now - last_data
        if ui:
            if not ui.draw(dec, inp.name, age):
                return 0
        elif now - last_msg >= QUIET:
            shown = screen_text(dec.screen)
            if shown != printed and dec.messages:
                printed = shown
                print(f"@ {now:.3f} {dec.counters()}")
                print("\n".join(shown), flush=True)
        if not ui and age > 6.0 and now - last_warn > 5.0:
            last_warn = now
            print(f"(no data for {age:.0f} s: transport running, or the link is down)", file=sys.stderr)
        time.sleep(0.005)


class TkView:
    """40x8 text through emu/lcd_font.py's glyphs (hatch for codes it lacks) or 240x64 pixels."""
    SCALE = 3

    def __init__(self) -> None:
        import tkinter as tk
        from emu.lcd_font import font
        self.tk = tk
        self.font = font()
        self.root = tk.Tk()
        self.root.title("MPC3000 LCD mirror")
        self.canvas = tk.Canvas(self.root, width=FB_W * self.SCALE, height=FB_H * self.SCALE + 18, bg="#9ab04a")
        self.canvas.pack()
        self.alive = True
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.last = None

    def _close(self) -> None:
        self.alive = False

    def pixels(self, s: Screen) -> list[str]:
        if s.graphics:
            return s.fb_pixels()
        rows = [["."] * FB_W for _ in range(FB_H)]
        for r in range(ROWS):
            for c in range(COLS):
                code = s.text[r][c]
                glyph = self.font.get(code)
                for y in range(8):
                    for x in range(6):
                        if glyph is None:
                            on = code not in (0x00, 0x20) and (x + y) % 2 == 0     # hatch
                        else:
                            on = y < 7 and x < 5 and (glyph[y] >> (4 - x)) & 1
                        if on:
                            rows[r * 8 + y][c * 6 + x] = "#"
        return ["".join(r) for r in rows]

    def draw(self, dec: Decoder, port: str, age: float) -> bool:
        if not self.alive:
            return False
        s = dec.screen
        status = f"{port}  {dec.counters()}  last data {age:.0f} s ago" + \
            ("  (transport running, or link down)" if age > 6 else "")
        state = (s.graphics, bytes(s.fb) if s.graphics else b"".join(s.text_codes()), s.cursor, status)
        if state != self.last:
            self.last = state
            k = self.SCALE
            self.canvas.delete("all")
            for y, line in enumerate(self.pixels(s)):
                x = 0
                while x < FB_W:
                    if line[x] == "#":
                        e = x
                        while e < FB_W and line[e] == "#":
                            e += 1
                        self.canvas.create_rectangle(x * k, y * k, e * k, (y + 1) * k, fill="#1c2410", width=0)
                        x = e
                    else:
                        x += 1
            r, c, mode = s.cursor
            if not s.graphics and mode:                 # cursor mode 0 hides it (INT 43 AX=2)
                self.canvas.create_rectangle(c * 6 * k, (r * 8 + 7) * k, (c * 6 + 5) * k, (r * 8 + 8) * k,
                                             outline="#1c2410")
            self.canvas.create_text(4, FB_H * k + 9, anchor="w", text=status)
        self.root.update()
        return self.alive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="substring of the MIDI input name (default: the first)")
    ap.add_argument("--log", type=Path, help="append every decoded message with the laptop clock")
    ap.add_argument("--headless", action="store_true", help="print screens instead of a window")
    ap.add_argument("--replay", type=Path, help="decode an mpc3k_replay --midi-log file and print the end state")
    ap.add_argument("--out-port", type=int, default=4, help="with --replay: MIDI OUT 1-4 (default 4 = OUT D)")
    a = ap.parse_args()
    if a.replay:
        dec = Decoder()
        for _, b in read_replay_log(a.replay, a.out_port):
            dec.feed(b)
        s = dec.screen
        print(f"{dec.counters()} longest={dec.longest} hello={s.hello}")
        print("\n".join(screen_text(s)))
        return 0
    return run_live(a)


if __name__ == "__main__":
    sys.exit(main())
