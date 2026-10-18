"""Lazy Chop's self-contained cave code (mods/lazychop316.inc) in tests/x86sub.py, no MAME.

    python3 -m unittest tests.test_lazychop316 -v

The pinned PMONEY build and the stock M3K316.SYS are loaded as the EPROM loader
leaves them at L = 6900 (route_c.simulate), as tests/test_perf316_diff.py does.

* lc_pos (time -> frames) against the specification's formula
  q*441 + (r*441 + 10000) div 20000 for times around t0, the 2^32 wrap of the
  TCT0 base and the user offset; it keeps BX, CX, SI, DI.
* The panel-parser hooks, differentially: with the pads not owned (lc_owned 0,
  or MODE / OPTION not Edit Sound) the press 2B6D:022E and the release
  2B6D:04A5 do exactly what the stock bytes do (memory and registers).  Owned,
  a press queues {TCT0 time, slot, velocity} in the cave ring and key 'D', and
  nothing in ring 5; a full ring drops the hit; the release of a captured pad
  is kept from ring 5, every other release is stock.
* lc_pop returns the ring in order and CF on empty.
* lc_snap_search against a Python reference on random buffers and windows.
* Review fixes (2026-10-18): chop_name_slice's names for every Source length
  (unique, Source-derived, never ZONEnnn); chop_make_name writes its whole
  template; the slot of an owned press comes from the parser's own bytes, not
  [D399]; owned pad pressure leaves the held table alone; lc_alloc_seen drops a
  listed audition channel another caller allocates; the recording row shows
  hits lost on a full ring ("Lost:nn").
* Second review (2026-10-18): lc_disk_entry marks only the disk names of the
  Convert form and chop_name_slice skips them (B7); lc_settle never moves a start
  at frame 0 or an end at the Source end (B4).
* Third review: disk names of Sources that end in digits (#1); + and - taken
  and coalesced without BDE3:000E (#6).
"""
from __future__ import annotations

import random
import re
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from mods import build_wave316 as b  # noqa: E402
from mods import route_c as rc  # noqa: E402
import x86sub  # noqa: E402

HAVE_TOOLS = shutil.which("nasm") is not None and shutil.which("ndisasm") is not None
L = 0x6900
DGROUP = (0x609C + L) & 0xFFFF
SND_SEG = (0x539D + L) & 0xFFFF
RING_SEG = (0x77CA + L) & 0xFFFF
CAVE = (b.CAVE_HOME + L) & 0xFFFF
PARSER = (0x2B6D + L) & 0xFFFF
STACK_SEG, STACK_TOP = 0x0800, 0xFFF0
KEY_QUEUE = 0x12A4
RING5 = 0x06AC
BASE = 0xD501                   # TCT0 time base (100 Hz ISR 2B50:0018)
PARSER_HLT = 0xF000             # 2B6D:F000 = image 0x3A6D0, code no test runs: the near-return HLT


def lc_pos(t: int, t0: int, k: int) -> int:
    d = (t - t0 - k) & 0xFFFF_FFFF
    if d >= 1 << 31:
        return 0
    q, r = divmod(d, 20_000)
    return q * 441 + (r * 441 + 10_000) // 20_000


def snap_ref(x: list[int], s: int, lo: int, hi: int) -> int | None:
    for d in range(89):
        for p in ((s,) if d == 0 else (s + d, s - d)):
            if lo <= p <= hi and (x[p] == 0 or (x[p] < 0) != (x[p - 1] < 0)):
                return p
    return None


@unittest.skipUnless(HAVE_TOOLS, "needs nasm and ndisasm")
class LazyChopCode(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            m = b.build(out=Path(tmp))
            sys_bytes = (Path(tmp) / "WAVE316.SYS").read_bytes()
            text = (Path(tmp) / "wave316.cave.map").read_text()
        cls.sym = {g[3]: int(g[1], 16) for g in re.finditer(r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)$",
                                                             text, re.M)}
        copied = 2 * int(m["simulation"]["copy_words"], 16)
        cls.pm, _ = rc.simulate(sys_bytes, L, home=b.CAVE_HOME, cave_len=copied)
        cls.st, _ = rc.simulate(b.M3K316.read_bytes(), L, home=b.CAVE_HOME, cave_len=0)

    # ------------------------------------------------------------ helpers
    def cave(self, mem, name: str, size: int = 1, value: int | None = None) -> int:
        a = (CAVE << 4) + self.sym[name]
        if value is not None:
            mem[a:a + size] = value.to_bytes(size, "little")
        return int.from_bytes(mem[a:a + size], "little")

    def cpu(self, mem, counter: list[int] | None = None):
        """x86sub CPU; TCT0 counter 0 reads `counter[0]` (latched low then high byte)."""
        state = {"latch": None, "byte": 0}

        def pin(port, width):
            if port == 0xC030:
                if state["byte"] == 0:
                    state["latch"] = counter[0] if counter else 0
                v = (state["latch"] >> (8 * state["byte"])) & 0xFF
                state["byte"] ^= 1
                return v
            if port == 0xC011:
                return 0x00
            return 0xFF
        c = x86sub.Cpu(mem, port_in=pin)
        c.s.update(ds=DGROUP, es=DGROUP, ss=STACK_SEG)
        c.r["sp"] = STACK_TOP
        c.f["if"] = False
        return c

    def call_near(self, c, seg: int, ip: int, ret_seg_off: int) -> None:
        """Run seg:ip with a near return to a HLT at seg:ret_seg_off."""
        c.m[(seg << 4) + ret_seg_off] = 0xF4
        c.push(ret_seg_off)
        c.s["cs"], c.ip = seg, ip
        try:
            while True:
                c.step()
        except x86sub.Halt:
            pass

    # ------------------------------------------------------------ lc_pos
    def test_position_arithmetic(self) -> None:
        rng = random.Random(7)
        cases = []
        for t0 in (0, 75_025_684, 0xFFFF_FFFF - 3_000_000, 0xFFFF_FFF0, rng.randrange(1 << 32)):
            for off_ms in (0, 5, -20, 20):
                for delta in (0, 1, 22, 23, 45, 46, 19_999, 20_000, 1_310_720, 3_199_250, 8_000_000,
                              60_000_000, 2_000_000_000, (1 << 31) - 1, 1 << 31, 0xFFFF_FFFF,
                              *(rng.randrange(0, 12_000_000) for _ in range(6))):
                    cases.append((t0, off_ms, (t0 + delta) & 0xFFFF_FFFF))
        for t0, off_ms, t in cases:
            mem = bytearray(self.pm)
            k = (off_ms * 2000) & 0xFFFF_FFFF
            self.cave(mem, "lc_t0", 4, t0)
            self.cave(mem, "lc_k", 4, k)
            c = self.cpu(mem)
            c.r.update(ax=t & 0xFFFF, dx=t >> 16, bx=0x1111, cx=0x2222, si=0x3333, di=0x4444)
            self.call_near(c, CAVE, self.sym["lc_pos"], self.sym["lc_line"])
            got = (c.r["dx"] << 16) | c.r["ax"]
            self.assertEqual(got, lc_pos(t, t0, off_ms * 2000), f"t0={t0} off={off_ms} t={t}")
            self.assertEqual((c.r["bx"], c.r["cx"], c.r["si"], c.r["di"]), (0x1111, 0x2222, 0x3333, 0x4444))

    # ------------------------------------------------------------ panel parser hooks
    def parser_state(self, mem, *, raw: int, bank: int, vel: int, release: bool) -> None:
        dg = DGROUP << 4
        mem[dg + 0x7018] = 0x80 if release else 0x90
        mem[dg + 0x7019] = 0x25 + raw
        mem[dg + 0x701A] = 0x40 if release else vel
        mem[dg + 0x701B] = 0x17
        mem[dg + 0x701C] = raw
        mem[dg + 0xD38F] = bank
        mem[dg + 0xD399] = bank + raw
        rb = RING_SEG << 4
        struct.pack_into("<HHHH", mem, rb + RING5, 0x80, 0, 0, 0)
        struct.pack_into("<HHHH", mem, dg + KEY_QUEUE, 8, 0, 0, 0)

    def run_parser(self, mem, site: int, counter: int = 0):
        c = self.cpu(mem, [counter])
        c.r.update(si=0x5555, di=0x6666, bp=0x7777)
        c.writes = set()
        self.call_near(c, PARSER, site, PARSER_HLT)
        stack = range((STACK_SEG << 4) + 0x8000, (STACK_SEG << 4) + 0x10000)
        return c, sorted(a for a in c.writes if a not in stack and a != (PARSER << 4) + PARSER_HLT)

    def owned(self, mem, flag: int = 1, mode: int = ord("L"), option: int = 6) -> None:
        self.cave(mem, "lc_owned", 1, flag)
        mem[(DGROUP << 4) + 0xD4B8] = mode
        mem[(DGROUP << 4) + 0xD4B7] = option

    def test_not_owned_press_and_release_are_stock(self) -> None:
        for flag, mode, option in ((0, ord("L"), 6), (1, ord("G"), 6), (1, ord("L"), 5), (0, ord("M"), 0)):
            for site, release in ((0x022E, False), (0x04A5, True)):
                out = []
                for base in (self.st, self.pm):
                    mem = bytearray(base)
                    self.parser_state(mem, raw=5, bank=0x10, vel=0x63, release=release)
                    if base is self.pm:
                        self.owned(mem, flag, mode, option)
                        self.cave(mem, "lc_captured", 2, 0)
                    c, wrote = self.run_parser(mem, site)
                    regs = {k: c.r[k] for k in ("bx", "si", "di", "bp", "sp")}
                    cave = (CAVE << 4)
                    self.assertFalse([a for a in wrote if cave <= a < cave + 0x10000])   # no cave state
                    out.append((regs, {a: mem[a] for a in wrote},
                                bytes(mem[(RING_SEG << 4) + RING5:(RING_SEG << 4) + RING5 + 0x90])))
                self.assertEqual(out[0], out[1], f"site {site:04X} owned={flag} mode={mode} option={option}")

    def test_owned_press_queues_the_cave_ring_and_key(self) -> None:
        mem = bytearray(self.pm)
        self.owned(mem)
        self.cave(mem, "lc_captured", 2, 0)
        head = self.cave(mem, "lc_head")
        tail = self.cave(mem, "lc_tail", 1, head)
        struct.pack_into("<I", mem, (DGROUP << 4) + BASE, 0x1234_5678)
        self.parser_state(mem, raw=3, bank=0x20, vel=0x51, release=False)
        c, wrote = self.run_parser(mem, 0x022E, counter=20_000 - 4321)
        e = (CAVE << 4) + self.sym["lc_ring"] + 8 * tail
        t, slot, vel = struct.unpack_from("<IBB", mem, e)
        self.assertEqual((t, slot, vel), (0x1234_5678 + 4321, 0x23, 0x51))
        self.assertEqual(self.cave(mem, "lc_tail"), (tail + 1) % 16)
        self.assertEqual(self.cave(mem, "lc_captured", 2), 1 << 3)
        rb = RING_SEG << 4
        self.assertEqual(struct.unpack_from("<H", mem, rb + RING5 + 2)[0], 0)          # nothing in ring 5
        qb = (DGROUP << 4) + KEY_QUEUE
        count, write = struct.unpack_from("<HH", mem, qb + 2)
        self.assertEqual((count, mem[qb + 8 + write]), (1, ord("D")))
        self.assertEqual(struct.unpack_from("<H", mem, (DGROUP << 4) + 0x7016)[0], 0x0121)
        self.assertEqual((c.r["si"], c.r["di"], c.r["bp"]), (0x5555, 0x6666, 0x7777))

        # The captured pad's release stays in the cave; another pad's is stock.
        self.parser_state(mem, raw=3, bank=0x20, vel=0, release=True)
        self.run_parser(mem, 0x04A5)
        self.assertEqual(struct.unpack_from("<H", mem, rb + RING5 + 2)[0], 0)
        self.assertEqual(self.cave(mem, "lc_captured", 2), 0)
        self.parser_state(mem, raw=3, bank=0x20, vel=0, release=True)
        self.run_parser(mem, 0x04A5)
        self.assertEqual(struct.unpack_from("<H", mem, rb + RING5 + 2)[0], 3)          # stock: 3 bytes

    def test_full_ring_drops_and_pop_order(self) -> None:
        mem = bytearray(self.pm)
        self.owned(mem)
        self.cave(mem, "lc_head", 1, 0)
        self.cave(mem, "lc_tail", 1, 0)
        self.cave(mem, "lc_dropped", 1, 0)
        struct.pack_into("<I", mem, (DGROUP << 4) + BASE, 1_000_000)
        for i in range(17):
            self.parser_state(mem, raw=i % 16, bank=0, vel=0x40 + i, release=False)
            self.run_parser(mem, 0x022E, counter=20_000 - 100 * (i + 1))
        self.assertEqual((self.cave(mem, "lc_tail"), self.cave(mem, "lc_dropped")), (15, 2))
        got = []
        while True:
            c = self.cpu(mem)
            self.call_near(c, CAVE, self.sym["lc_pop"], self.sym["lc_line"])
            if c.f["cf"]:
                break
            got.append(((c.r["dx"] << 16) | c.r["ax"], c.r["cx"] & 0xFF))
        self.assertEqual(got, [(1_000_000 + 100 * (i + 1), i % 16) for i in range(15)])
        self.assertEqual(self.cave(mem, "lc_head"), 15)

    # ------------------------------------------------------------ snap
    def test_snap_search(self) -> None:
        rng = random.Random(11)
        for trial in range(300):
            n = rng.randrange(2, 179)
            kind = trial % 3
            if kind == 0:
                x = [rng.randrange(-30000, 30000) for _ in range(n)]
            elif kind == 1:
                x = [rng.randrange(1, 30000) * (1 if (i // rng.randrange(5, 60)) % 2 else -1) for i in range(n)]
            else:
                x = [rng.choice((0, 5, -5, 300, -300)) for _ in range(n)]
            s = rng.randrange(0, n)
            lo = rng.randrange(1, n) if rng.random() < 0.5 else 1
            hi = rng.randrange(lo, n) if rng.random() < 0.5 else n - 1
            mem = bytearray(self.pm)
            base = SND_SEG << 4
            struct.pack_into(f"<{n}h", mem, base, *x)
            c = self.cpu(mem)
            c.r.update(bx=s, si=lo, di=hi, cx=0xAAAA, dx=0xBBBB)
            self.call_near(c, CAVE, self.sym["lc_snap_search"], self.sym["lc_line"])
            want = snap_ref(x, s, lo, hi)
            self.assertEqual(None if c.f["cf"] else c.r["ax"], want, f"trial {trial}")
            self.assertEqual((c.r["bx"], c.r["cx"], c.r["dx"], c.r["si"], c.r["di"]), (s, 0xAAAA, 0xBBBB, lo, hi))

    # ------------------------------------------------------------ review fixes
    def name_ref(self, src: bytes, k: int, taken: set[str]) -> str:
        text = src.split(b"\0")[0].decode("latin1")[:16].rstrip(" ")
        n = k
        while True:
            d = 2 if n < 100 else 3 if n < 1000 else 4 if n < 10000 else 5
            cand = (text[:15 - d] + str(n).zfill(d)).ljust(16)
            if cand not in taken:
                return cand
            n += 100

    def set_records(self, mem, names: list[str]) -> None:
        base = (SND_SEG << 4) + 0x4800
        mem[base:base + 128 * 0x24] = bytes(128 * 0x24)
        for i, name in enumerate(names):
            mem[base + i * 0x24:base + i * 0x24 + 17] = name.encode("latin1").ljust(16)[:16] + b"\0"
            struct.pack_into("<I", mem, base + i * 0x24 + 0x1C, 1000)

    def slice_name(self, mem, src: bytes, k: int) -> str:
        self.cave(mem, "chop_naming", 1, 1)
        self.cave(mem, "chop_zone", 1, k - 1)
        a = (CAVE << 4) + self.sym["zones_identity"]
        mem[a:a + 16] = src.ljust(16, b" ")[:16]
        c = self.cpu(mem)
        c.f["if"] = True
        self.call_near(c, CAVE, self.sym["chop_name_slice"], self.sym["lc_line"])
        a = (CAVE << 4) + self.sym["chop_name"]
        self.assertEqual(mem[a + 16], 0)
        return mem[a:a + 16].decode("latin1")

    def test_slice_names_every_length(self) -> None:
        full = b"FUNKYDRUMMERLOOP"
        mem = bytearray(self.pm)
        for n in range(1, 17):
            for src in (full[:n], full[:n - 1] + b" " if n > 1 else b"A", b"AB CD"[:n]):
                for k in (1, 2, 9, 10, 64):
                    self.set_records(mem, [])
                    got = self.slice_name(mem, src, k)
                    self.assertEqual(got, self.name_ref(src, k, set()), (src, k))
                    self.assertNotIn("ZONE", got)
        # after a longer previous name nothing of it is left
        self.set_records(mem, [])
        self.slice_name(mem, full, 3)
        self.assertEqual(self.slice_name(mem, b"KICK", 3), "KICK03".ljust(16))

    def test_slice_names_unique_in_memory(self) -> None:
        mem = bytearray(self.pm)
        for src in (b"BREAKS", b"FUNKYDRUMMERLOOP", b"ZONE"):
            taken = []
            for k in (1, 2, 3):
                taken.append(self.name_ref(src, k, set()))
            for rounds in range(3):
                self.set_records(mem, taken)
                for k in (1, 2, 3):
                    got = self.slice_name(mem, src, k)
                    self.assertEqual(got, self.name_ref(src, k, set(taken)))
                    self.assertNotIn(got, taken)
                    taken.append(got)
                    self.set_records(mem, taken)

    def test_make_name_writes_its_template(self) -> None:
        mem = bytearray(self.pm)
        self.set_records(mem, [])
        a = (CAVE << 4) + self.sym["chop_name"]
        mem[a:a + 17] = b"BREAKS01XYZQWERT\0"
        c = self.cpu(mem)                         # Edit Sound's ZONE->NEW SOUND calls it directly
        self.call_near(c, CAVE, self.sym["chop_make_name"], self.sym["lc_line"])
        self.assertRegex(mem[a:a + 17].decode("latin1"), r"^ZONE\d{3} {9}\x00$")

    def test_owned_slot_ignores_d399(self) -> None:
        mem = bytearray(self.pm)
        self.owned(mem)
        self.cave(mem, "lc_head", 1, 0)
        self.cave(mem, "lc_tail", 1, 0)
        self.parser_state(mem, raw=2, bank=0x30, vel=0x40, release=False)
        mem[(DGROUP << 4) + 0xD399] = 63          # the MIDI note handler wrote it meanwhile
        self.run_parser(mem, 0x022E, counter=10_000)
        e = (CAVE << 4) + self.sym["lc_ring"]
        self.assertEqual(mem[e + 4], 0x32)

    def test_owned_pressure_skips_the_held_table(self) -> None:
        for captured, want in ((1 << 4, 0x00), (0, 0x55)):
            mem = bytearray(self.pm)
            self.owned(mem)
            self.cave(mem, "lc_captured", 2, captured)
            dg = DGROUP << 4
            mem[dg + 0x701C] = 4
            mem[dg + 0x9548 + 0x30] = 0
            c = self.cpu(mem)
            c.r.update(ax=0x55, bx=0x30)
            c.writes = set()
            self.call_near(c, PARSER, 0x02CC, PARSER_HLT)
            self.assertEqual(mem[dg + 0x9548 + 0x30], want)
            self.assertEqual(struct.unpack_from("<H", mem, dg + 0x7016)[0], 0x0121)

    def test_alloc_seen_drops_a_reused_channel(self) -> None:
        mem = bytearray(self.pm)
        self.cave(mem, "lc_owned", 1, 1)
        self.cave(mem, "lc_aud_n", 1, 3)
        a = (CAVE << 4) + self.sym["lc_aud_ch"]
        mem[a:a + 4] = bytes((5, 9, 12, 0))
        c = self.cpu(mem)
        # a frame chain that is not aud_range's: BP -> a frame whose saved BP is 0
        c.r["bp"] = 0x8000
        c.ww("ss", 0x8000, 0x8100)
        c.ww("ss", 0x8100, 0x8200)
        c.ww("ss", 0x8102, 0x1234)
        c.r.update(bx=9, ax=9)
        self.call_near(c, CAVE, self.sym["lc_alloc_seen"], self.sym["lc_line"])
        self.assertEqual(self.cave(mem, "lc_aud_n"), 2)
        self.assertEqual(sorted(mem[a:a + 2]), [5, 12])
        self.assertEqual((c.r["ax"], c.r["bx"]), (9, 9))


    def test_recording_row_shows_lost_hits(self) -> None:
        """#16: hits dropped on a full ring show as "Lost:nn" at column 10 while recording."""
        fbs = {}
        for dropped in (0, 7):
            mem = bytearray(self.pm)
            self.cave(mem, "lc_phase", 1, 2)
            self.cave(mem, "lc_nchops", 1, 3)
            self.cave(mem, "lc_dropped", 1, dropped)
            fb = (DGROUP << 4) + 0x1579
            mem[fb:fb + 30 * 64] = bytes(30 * 64)
            c = self.cpu(mem)
            self.call_near(c, CAVE, self.sym["lc_softkeys"], self.sym["lc_line"])
            self.assertTrue(c.f["cf"])
            fbs[dropped] = bytes(mem[fb:fb + 30 * 64])
            if dropped:
                a = (CAVE << 4) + self.sym["lc_s_lost"]
                self.assertEqual(mem[a:a + 7], b"Lost:07")
        diff = {i % 30 for i in range(30 * 64) if fbs[0][i] != fbs[7][i]}
        self.assertTrue(diff)
        self.assertLessEqual(diff, set(range(10 * 6 // 8, (17 * 6 - 1) // 8 + 1)))   # 6-pixel columns 10..16

    # ------------------------------------------------------------ second review
    def disk_entry(self, mem, raw: bytes) -> None:
        a = (CAVE << 4) + self.sym["lc_find"]
        mem[a:a + 28] = bytes(28)
        mem[a + 7:a + 7 + len(raw)] = raw
        c = self.cpu(mem)
        self.call_near(c, CAVE, self.sym["lc_disk_entry"], self.sym["lc_line"])

    def taken(self, mem) -> set[int]:
        a = (CAVE << 4) + self.sym["lc_taken"]
        return {n for n in range(1000) if mem[a + n // 8] >> (n % 8) & 1}

    def test_disk_names_mark_the_convert_form(self):
        """B7: a .SND file of the selected disk named as Convert would name a slice
        of this Source marks its number; nothing else does."""
        a = (CAVE << 4)
        for src, raw, want in (
                (b"BREAKS", b"BREAKS01SND\0", {1}),                       # 8.3
                (b"BREAKS", b"BREAKS01PGM\0", set()),                     # not a Sound
                (b"BREAKS", b"BREAKS101       SND\0", {101}),             # long name, 3 digits
                (b"BREAKS", b"BREAKS012       SND\0", set()),             # 012: written 12
                (b"BREAKS", b"BREAKX05SND\0", set()),
                (b"BREAKS", b"BREAKS7 SND\0", set()),                     # one digit
                (b"BREAKS", b"BREAKS  SND\0", set()),
                (b"FUNKYDRUMMERLOOP", b"FUNKYDRUMMERL02 SND\0", {2}),     # 13 + 2
                (b"FUNKYDRUMMERLOOP", b"FUNKYDRUMMER102 SND\0", {102}),   # 12 + 3
                (b"FUNKYDRUMMERLOOP", b"FUNKYDRUMMERLO02SND\0", set()),   # 14 + 2: not ours
                # Third review #1: Source names that end in digits
                (b"LOOP1", b"LOOP101 SND\0", {1}),
                (b"LOOP1", b"LOOP1101SND\0", {101}),
                (b"LOOP1", b"LOOP1   SND\0", set()),
                (b"KICK808", b"KICK80801       SND\0", {1}),
                (b"KICK808", b"KICK808101      SND\0", {101}),
                (b"KICK808", b"KICK808 SND\0", set()),
                (b"BEAT 1", b"BEAT 101SND\0", {1}),
                (b"DRUMS90", b"DRUMS90101      SND\0", {101}),
                (b"DRUMS90", b"DRUMS9001       SND\0", {1}),
                (b"DRUMS90", b"DRUMS90 SND\0", set()),
        ):
            with self.subTest(src=src, raw=raw):
                mem = bytearray(self.pm)
                z = a + self.sym["zones_identity"]
                mem[z:z + 16] = src.ljust(16, b" ")
                self.cave(mem, "lc_name_len", 2, len(src))
                t = a + self.sym["lc_taken"]
                mem[t:t + 125] = bytes(125)
                self.disk_entry(mem, raw)
                self.assertEqual(self.taken(mem), want)

    def test_slice_name_skips_disk_names(self):
        """B7: chop_name_slice never takes a number lc_disk_scan found on the disk."""
        mem = bytearray(self.pm)
        self.set_records(mem, [])
        t = (CAVE << 4) + self.sym["lc_taken"]
        mem[t:t + 125] = bytes(125)
        for n in (1, 101):
            mem[t + n // 8] |= 1 << (n % 8)
        self.assertEqual(self.slice_name(mem, b"BREAKS", 1), "BREAKS201".ljust(16))
        self.assertEqual(self.slice_name(mem, b"BREAKS", 2), "BREAKS02".ljust(16))

    def settle(self, mem, point: int) -> None:
        self.cave(mem, "lc_edit_dirty", 1, 1)
        self.cave(mem, "lc_edit_point", 1, point)
        self.cave(mem, "lc_snap", 1, 1)
        self.cave(mem, "zones_mode", 1, 1)
        c = self.cpu(mem)
        self.call_near(c, CAVE, self.sym["lc_settle"], self.sym["lc_line"])

    def test_settle_keeps_frame_0_and_the_source_end(self):
        """B4: the stepped point is the one lc_settle may move; a start at frame 0 or
        an end at the Source end is never moved (D2), and the other point is left."""
        n = 6 * 44_100
        for point, slice_, pair in ((0, 0, (0, 30_000)), (1, 1, (30_000, n))):
            mem = bytearray(self.pm)
            self.cave(mem, "len", 4, n)
            self.cave(mem, "zones_count", 1, 2)
            self.cave(mem, "lc_edit_slice", 1, slice_)
            pa = (CAVE << 4) + self.sym["zones_pairs"]
            struct.pack_into("<4I", mem, pa, 0, 30_000, 30_000, n)
            before = bytes(mem[pa:pa + 16])
            self.settle(mem, point)
            self.assertEqual(bytes(mem[pa:pa + 16]), before, point)
            self.assertEqual(self.cave(mem, "lc_edit_dirty"), 0)

    def test_plus_minus_coalesced_without_bde3(self):
        """Third review #6: lc_take_key takes + (or -) and the copies of it at the
        head of the queue itself, KEY_REPEAT = their number, the next key left."""
        for keys, want, left in ((b"+++x", (ord("+"), 3), 1), (b"-+", (ord("-"), 1), 1), (b"+", (ord("+"), 1), 0)):
            with self.subTest(keys=keys):
                mem = bytearray(self.pm)
                q = (DGROUP << 4) + KEY_QUEUE
                n = len(keys)
                struct.pack_into("<4H", mem, q, 8, n, 0, n)       # capacity 8, count, write, read
                for i, k in enumerate(keys):                      # the head is [8 + read - 1]
                    mem[q + 8 + n - 1 - i] = k
                c = self.cpu(mem)
                c.f["if"] = True
                self.call_near(c, CAVE, self.sym["lc_take_key"], self.sym["lc_line"])
                rep = struct.unpack_from("<H", mem, (DGROUP << 4) + 0xD387)[0]
                self.assertEqual((c.r["ax"] & 0xFF, rep), want)
                self.assertEqual(struct.unpack_from("<H", mem, q + 2)[0], left)

if __name__ == "__main__":
    unittest.main()
