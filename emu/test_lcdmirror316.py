"""LCD mirror over MIDI (mods/lcdmirror316.asm) in the emulator, OS 3.16.

    python3 -m unittest emu.test_lcdmirror316 -v

Builds the mirror (mods/build_lcdmirror316.py, OUT D) and boots its floppy and
the stock control floppy.  One panel walk (WALK): Play/Record, the cursor to
Trk and a track change with the data wheel, Other, Disk, Program/Sounds,
Mixer/Effects, the Mixer page (graphics), back to Play/Record, a Seq edit with
the wheel, then Tempo/Sync -> <Sync> -> MIDI clock OUT D and four seconds of
Play, so 3.16's own clock shares OUT D with the mirror.

Two observers of the same walk:

* the MAME harness (emu.mpc3k, this repo's pinned fork binary): screens_hex.txt
  and lcd_pixels.txt 2.2 s after each input, and every write to the OUT D
  transmit data register (I/O D8h) in io_trace.log;
* the mac-port replay host (`mpc3k_replay --midi-log`, $MPC3K_REPLAY, ROMs in
  $MPC3K_REPLAY_ROMS): every MIDI OUT byte with its emulated time and port.

At every probe time the stream decoded up to that time
(tools/lcd_mirror_midi_viewer.Decoder) must equal the captured LCD: text codes
against display RAM, or on the Mixer page the framebuffer against the 240x64
pixels.  The stream must be well formed (no drops, no message over 64 bytes,
nothing malformed or cut), the stock control must show the same LCD at every
probe time, and the clock on OUT D must arrive as it does without the mirror.

The CPU runs at the board's 16 MHz (MPC3K_LM_DIV=1 for the fork's historical 32 MHz).
These are emulator results, not hardware results (notes/lcd_mirror_midi.md).
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from emu import harness as h
from emu import mpc3k, panel

sys.path.insert(0, str(h.REPO / "tools"))
import lcd_mirror_midi_viewer as v  # noqa: E402

from mods import build_lcdmirror316 as lm  # noqa: E402

RUNS = h.BUILD / "emu" / "lcdmirror316-tests"
MACPORT = h.REPO.parent / "MPC3000-mac-port" / "build"
REPLAY = Path(os.environ.get("MPC3K_REPLAY", MACPORT / "core" / "mpc3k_replay"))
REPLAY_ROMS = Path(os.environ.get("MPC3K_REPLAY_ROMS", MACPORT / "roms"))
PORT = 4                                 # OUT D
# NEC_CPU_DIV=2 runs the V53 at the board's 16 MHz (emu/README.md "Cycle profiler");
# the fork's default 1 is twice as fast.  The 16 MHz boot reaches the SCSI search
# cancel 18 s later (emu/cycle_budget.py T0 = 51.0 against 33.0).
CPU_DIV = os.environ.get("MPC3K_LM_DIV", "2")
SHIFT = 18.0 if CPU_DIV == "2" else 0.0
ENV = {"NEC_CPU_DIV": CPU_DIV}
TX_D = 0xD8                              # TE7774 transmit data, OUT D (fork wiring, emu/test_syncout.py)
CURSOR_PHYS = 0x300000 + (0x6900 + 0x59FA) * 16 + 0x68AB     # 3.16 BIOS-copy cursor word
CMODE_PHYS = 0x300000 + (0x6900 + 0x609C) * 16 + 0x1D02      # DGROUP [1D02] cursor mode
WATCH_ENV = {"LM_CURSOR_PHYS": f"{CURSOR_PHYS:X}", "LM_CMODE_PHYS": f"{CMODE_PHYS:X}"}
F8_PERIOD = 60 / 120 / 24                # 120 BPM, 24 clocks per quarter: 20.833 ms
BYTE_TIME = 10 / 31250                   # one MIDI byte on the wire: 0.32 ms
PROBE = 2.2                              # seconds after an input
STEP = 2.5
# (time, input, label): an input is a panel key name or ("dial", steps).
_WALK = [
    (36.0, "main_screen", "play_record"),
    (38.5, "down", "cursor_trk"),
    (41.0, ("dial", 1), "track_change"),
    (43.5, "other", "other"),
    (46.0, "disk", "disk"),
    (48.5, "program_sounds", "program_sounds"),
    (51.0, "mixer_effects", "mixer_menu"),
    (53.5, "1", "mixer"),
    (56.0, "main_screen", "back_to_play_record"),
    (58.5, "up", "cursor_seq"),
    (61.0, ("dial", 2), "seq_edit"),
    (63.5, "tempo_sync", "tempo"),
    (66.0, "soft1", "sync"),
    (68.5, "right", "midi_clock_field"),
    (71.0, ("dial", 4), "midi_clock_out_d"),
    (74.0, "main_screen", "play_record_clock"),
    (76.5, "play", None),                # running: the screen changes every beat; no probe
    (80.5, "stop", "stopped"),
]
WALK = [(t + SHIFT, what, label) for t, what, label in _WALK]
PLAY, STOP = 76.5 + SHIFT, 80.5 + SHIFT
END = 84.0 + SHIFT
CANCEL = h.CANCEL_SCSI_316 + SHIFT


def walk() -> tuple[list[tuple[float, bytes]], list[str], list[float], list[str]]:
    """(harness panel events, replay event lines, probe times, labels)."""
    smf = h.taps((CANCEL, "soft4"))
    lines = [f"{CANCEL} key {panel.KEYS['soft4']} 1", f"{CANCEL + 0.1:.3f} key {panel.KEYS['soft4']} 0"]
    times, labels = [], []
    for t, what, label in WALK:
        if isinstance(what, tuple):
            smf += panel.dial(what[1], t, gap=0.15)
            lines += [f"{t + i * 0.15:.3f} dial 0 {1 if what[1] > 0 else -1}" for i in range(abs(what[1]))]
        else:
            smf += h.taps((t, what))
            code = panel.KEYS[what]
            lines += [f"{t:.3f} key {code} 1", f"{t + 0.1:.3f} key {code} 0"]
        if label:
            times.append(round(t + PROBE, 3))
            labels.append(label)
    return smf, lines, times, labels


def harness_stream(run: Path) -> list[tuple[float, int]]:
    """(time, byte) written to the OUT D transmit register."""
    out = []
    for line in (run / "io_trace.log").read_text().splitlines():
        f = line.split()
        if f[2] == "W" and int(f[3], 16) == TX_D:
            out.append((float(f[0]), int(f[4], 16)))
    return out


def screens_hex(run: Path) -> dict[float, tuple[str, list[bytes]]]:
    """Probe time -> ('text' | 'graphics', rows of display RAM)."""
    out = {}
    for block in (run / "screens_hex.txt").read_text().split("@ ")[1:]:
        head, *rows = block.strip().splitlines()
        data = [bytes.fromhex(r) for r in rows]
        out[float(head.split()[0])] = ("graphics" if len(data) == 64 else "text", data)
    return out


def cursor_at(run: Path, t: float) -> tuple[int, int, int]:
    """(row, col, mode) the viewer should show at t, from emu/lua/lcdmirror_watch.lua
    (a cursor word past the screen is sent as cell 0, lcdmirror316.asm lm_cursor)."""
    cur = mode = None
    for line in (run / "lcdmirror_watch.txt").read_text().splitlines():
        ts, c, m = line.split()
        if float(ts) > t:
            break
        cur, mode = int(c, 16), int(m, 16)
    cell = cur if cur < 320 else 0
    return cell // 40, cell % 40, mode


def decode_until(stream: list[tuple[float, int]], t: float) -> v.Decoder:
    dec = v.Decoder()
    for when, byte in stream:
        if when > t:
            break
        dec.feed(byte)
    return dec


def mismatches(stream: list[tuple[float, int]], run: Path, times: list[float], labels: list[str]) -> list[str]:
    """Probe times where the decoded stream is not the captured LCD."""
    captured = screens_hex(run)
    pixels = h.lcd_pixels(run)
    bad = []
    for t, label in zip(times, labels):
        dec = decode_until(stream, t)
        kind, rows = captured[t]
        s = dec.screen
        if kind == "text":
            if s.cursor != cursor_at(run, t):
                bad.append(f"{t} {label}: cursor {s.cursor}, machine {cursor_at(run, t)}")
            got = s.text_codes()
            # The mirror sends the BIOS shadow; display RAM holds 00 in cells the
            # shadow has as 20 (the put-char skips a cell whose shadow already holds
            # the code, notes/lcd_mirror_midi.md "Blank cells").  Both glyphs are blank.
            other = [(w[i], g[i]) for w, g in zip(rows, got) for i in range(v.COLS)
                     if w[i] != g[i] and (w[i], g[i]) != (0x00, 0x20)]
            if s.graphics or other:
                bad.append(f"{t} {label}: text {'(viewer in graphics)' if s.graphics else ''}\n"
                           + "\n".join(f"  want {w.hex()}\n  got  {g.hex()}" for w, g in zip(rows, got) if w != g))
        else:
            want = pixels[f"{t:.3f}"]
            if not s.graphics or s.fb_pixels() != want:
                diff = sum(a != b for x, y in zip(want, s.fb_pixels()) for a, b in zip(x, y))
                bad.append(f"{t} {label}: graphics={s.graphics}, {diff} pixels differ")
    return bad


def run_replay(sys_img: Path, out: Path, lines: list[str]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    floppy = out / "floppy.img"
    floppy.write_bytes(sys_img.read_bytes())         # the replay host may write back to its floppy
    (out / "events.txt").write_text("\n".join(lines) + "\n")
    log = out / "midi.log"
    proc = subprocess.run([str(REPLAY), "--rom", str(REPLAY_ROMS), "--work", str(out), "--events",
                           str(out / "events.txt"), "--stop", str(END), "--bios", "vailixi",
                           "--floppy", str(floppy), "--midi-log", str(log), "--lcd-pgm", str(out / "lcd.pgm")],
                          capture_output=True, text=True, timeout=900, env={**os.environ, **ENV})
    (out / "replay_stdout.txt").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"mpc3k_replay exited {proc.returncode}; see {out / 'replay_stdout.txt'}")
    return log


def replay_stream(log: Path, port: int = PORT) -> list[tuple[float, int]]:
    return v.read_replay_log(log, port)


def clocks(stream: list[tuple[float, int]], start: float, end: float) -> int:
    return sum(1 for t, b in stream if b == 0xF8 and start <= t < end)


def messages(stream: list[tuple[float, int]]) -> list[bytes]:
    """Every SysEx on the stream, real-time bytes inside removed."""
    out, cur = [], None
    for _, b in stream:
        if b >= 0xF8:
            continue
        if b == 0xF0:
            cur = bytearray([b])
        elif cur is not None:
            cur.append(b)
            if b == 0xF7:
                out.append(bytes(cur))
                cur = None
    return out


def settle_times(stream: list[tuple[float, int]], run: Path, times: list[float],
                 labels: list[str]) -> dict[str, float | None]:
    """Seconds from each input until the decoded picture (text and cursor, or pixels)
    last became the captured one (0 when it already was; None: no byte between the
    input and the probe)."""
    captured, pixels = screens_hex(run), h.lcd_pixels(run)
    inputs = [t for t, _, label in WALK if label]

    def norm(rows):
        return [bytes(0x20 if c == 0 else c for c in r) for r in rows]
    out = {}
    for t_in, t, label in zip(inputs, times, labels):
        kind, rows = captured[t]
        cursor = cursor_at(run, t)

        def ok() -> bool:
            sc = dec.screen
            if kind == "text":
                return not sc.graphics and norm(sc.text_codes()) == norm(rows) and sc.cursor == cursor
            return sc.graphics and sc.fb_pixels() == pixels[f"{t:.3f}"]
        dec, settled, started = v.Decoder(), None, False
        for when, byte in stream:
            if when > t:
                break
            if when >= t_in and not started:
                started = True
                settled = t_in if ok() else None        # already right at the input
            dec.feed(byte)
            if started:
                settled = (settled or when) if ok() else None
        out[label] = (settled - t_in) if started and settled is not None else None
    return out


def replay_missing() -> str | None:
    if not REPLAY.is_file():
        return f"no replay host at {REPLAY} (build it in MPC3000-mac-port: tools/build_core_lib.sh)"
    if not (REPLAY_ROMS / "mpc3000").is_dir():
        return f"no ROM set at {REPLAY_ROMS}/mpc3000"
    return None


@unittest.skipIf(h.missing_tools(), f"missing: {h.missing_tools()}")
class LcdMirror(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        cls.manifest = lm.build(PORT, RUNS / "build")
        images = {"mirror": RUNS / "build" / "LCDMIRROR_316.img", "stock": RUNS / "build" / "STOCK_316.img"}
        smf, lines, cls.times, cls.labels = walk()
        midi = panel.write_smf(RUNS / "walk.mid", smf)
        probe_times = cls.times
        jobs = {}
        for bios in h.bios316_sets():
            for name, img in images.items():
                jobs[("harness", bios, name)] = img
        cls.replay_skip = replay_missing()
        if cls.replay_skip and h.RELEASE:
            raise RuntimeError(cls.replay_skip)
        if not cls.replay_skip:
            for name, img in images.items():
                jobs[("replay", "vailixi", name)] = img

        def go(key, img):
            kind, bios, name = key
            out = RUNS / f"{kind}-{bios}-{name}"
            if kind == "harness":
                mpc3k.run(bios, probe_times + [END], out, floppy=img, panel=midi, trace=[TX_D],
                          env={**ENV, **WATCH_ENV}, extra=["-autoboot_script", str(h.LUA / "lcdmirror_watch.lua")])
                return out
            return run_replay(img, out, lines)
        cls.runs = h.run_parallel(jobs, go, workers=min(4, h.WORKERS))

    def harness_runs(self, name: str):
        return [(bios, run) for (kind, bios, n), run in self.runs.items() if kind == "harness" and n == name]

    def test_decoded_stream_equals_the_lcd_harness_trace(self) -> None:
        for bios, run in self.harness_runs("mirror"):
            with self.subTest(set=bios):
                stream = harness_stream(run)
                self.assertGreater(len(stream), 1000)
                self.assertEqual(mismatches(stream, run, self.times, self.labels), [])

    def test_decoded_stream_equals_the_lcd_replay_host(self) -> None:
        if self.replay_skip:
            self.skipTest(self.replay_skip)
        stream = replay_stream(self.runs[("replay", "vailixi", "mirror")])
        for bios, run in self.harness_runs("mirror"):
            with self.subTest(set=bios):
                self.assertEqual(mismatches(stream, run, self.times, self.labels), [])

    def test_stream_is_well_formed(self) -> None:
        streams = {f"harness {b}": harness_stream(r) for b, r in self.harness_runs("mirror")}
        if not self.replay_skip:
            log = self.runs[("replay", "vailixi", "mirror")]
            streams["replay"] = replay_stream(log)
            stock = self.runs[("replay", "vailixi", "stock")]
            for p in (1, 2, 3):       # only 3.16's own clock, while the dial passes OUT A-C
                mine, theirs = replay_stream(log, p), replay_stream(stock, p)
                self.assertEqual({b for _, b in mine} | {b for _, b in theirs}, {0xF8}, f"OUT {'ABC'[p - 1]}")
                self.assertLessEqual(abs(len(mine) - len(theirs)), 1, f"OUT {'ABC'[p - 1]} clock count")
        for name, stream in streams.items():
            with self.subTest(stream=name):
                dec = v.Decoder()
                for _, b in stream:
                    dec.feed(b)
                self.assertEqual((dec.drops, dec.bad, dec.aborted, dec.foreign), (0, 0, 0, 0))
                self.assertLessEqual(dec.longest, v.MAX_MSG)
                msgs = messages(stream)
                self.assertEqual(len(msgs), dec.messages)
                self.assertEqual([m[6] for m in msgs], [i & 0x7F for i in range(len(msgs))], "sequence numbers")
                self.assertEqual(msgs[0][5], v.HELLO)
                self.assertEqual(dec.screen.hello, (v.PROTO, 2, 3, 16))
                self.assertGreater(dec.kinds.get(v.PIX, 0), 0)
                self.assertGreater(dec.kinds.get(v.PCOPY, 0), 0)
                self.assertGreaterEqual(dec.kinds.get(v.MODE, 0), 2)

    def test_stock_control_shows_the_same_lcd(self) -> None:
        stock = dict(self.harness_runs("stock"))
        for bios, run in self.harness_runs("mirror"):
            with self.subTest(set=bios):
                a, b = screens_hex(run), screens_hex(stock[bios])
                self.assertEqual([t for t in self.times if a[t] != b[t]], [])
                self.assertEqual({x for _, x in harness_stream(stock[bios])} - {0xF8, 0xFA, 0xFB, 0xFC}, set(),
                                 "stock sends only its clock on OUT D")

    def test_latency_and_silence_while_playing(self) -> None:
        for bios, run in self.harness_runs("mirror"):
            with self.subTest(set=bios):
                stream = harness_stream(run)
                late = {k: d for k, d in settle_times(stream, run, self.times, self.labels).items()
                        if d is not None and d > (2.0 if k == "mixer" else 0.6)}
                self.assertEqual(late, {})
                self.assertEqual([t for t, b in stream if b == 0xF0 and PLAY + 0.05 < t < STOP], [],
                                 "SysEx started while the transport ran")

    def test_os_clock_on_the_same_output(self) -> None:
        """3.16 sends F8 on OUT D from the moment MIDI clock OUT D is chosen, stopped too, so
        the clock and the mirror share the port from then until Play.  A real-time byte
        waits at most for the byte on the wire (the TxRdy ISR takes the RT ring first)."""
        stock = dict(self.harness_runs("stock"))
        shared = (WALK[[w[2] for w in WALK].index("midi_clock_out_d")][0] + 1.0, PLAY)
        for bios, run in self.harness_runs("mirror"):
            with self.subTest(set=bios):
                for name, stream in (("mirror", harness_stream(run)), ("stock", harness_stream(stock[bios]))):
                    f8 = [t for t, b in stream if b == 0xF8 and shared[0] <= t < shared[1]]
                    self.assertGreater(len(f8), 100, name)
                    worst = max(abs(b - a - F8_PERIOD) for a, b in zip(f8, f8[1:]))
                    self.assertLessEqual(worst, BYTE_TIME * 1.1, f"{name}: F8 interval off by {worst * 1e3:.3f} ms")
                mine, theirs = harness_stream(run), harness_stream(stock[bios])
                n_mine, n_stock = clocks(mine, PLAY, STOP + 0.5), clocks(theirs, PLAY, STOP + 0.5)
                self.assertGreater(n_stock, 150)                 # 120 BPM, 24 per quarter: ~48 per second
                self.assertLessEqual(abs(n_mine - n_stock), 2)
                for b in (0xFB, 0xFC):                           # 3.16 sends Continue at Play, Stop at Stop
                    n = sum(1 for t, x in theirs if x == b)
                    self.assertGreater(n, 0, f"{b:02X}")
                    self.assertEqual(sum(1 for t, x in mine if x == b), n)


if __name__ == "__main__":
    unittest.main()
