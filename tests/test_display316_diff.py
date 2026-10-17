"""PMONEY display speed-up (mods/display316.inc) against the stock 3.16 bytes (no MAME).

    python3 -m unittest tests.test_display316_diff -v

Both put-char variants are built (mods/build_wave316.py: P, the default, and MX with
DISPLAY_COMPACT) and loaded with stock M3K316.SYS as the EPROM loader leaves them at
L = 6900 (route_c.simulate); IVT 43h is installed by running 0009:00D2 in each.  The
stock and PMONEY bytes run side by side in tests/x86sub.py against an LC7981 model
(instruction register, cursor address with auto-increment and the HD61830 low-byte
carry MAME models, display RAM, a busy-flag script of n busy polls after every OUT).
DIV leaves the arithmetic flags undefined on the V53: here every DIV scrambles them,
so a routine that leaked DIV's flags would differ from stock.

Dynamic (instruction level):
* Step 1, INT 43 AX=4's rewritten class walk: identical to stock in every case, with
  invariant I held or broken: memory, LC7981 state, the exact port log (with IF at
  each OUT), registers, SP, segments, flags.
* put-char 0427:0040, both variants, every BL x cursor {0, 1, 27h, 28h, FFh, 100h,
  13Eh, 13Fh} x shadow cell equal / unequal x [68AF] 0 / FFh x IF 0 / 1 x busy 0 / 2,
  random entry flags, under invariant I ([68AF] = FFh => LC7981 address = [68AB]):
  every memory byte outside the stack, the LC7981 address and RAM, AX..DI, BP, SP, DS,
  ES, SS, flags.  The port log may differ only by omitted (0Ah, lo) (0Bh, hi) pairs
  that each set the address it already held, and IF is 1 at every OUT as in stock.
* String writer 0427:0065, both variants: the empty string and every one-byte string
  over the same grid (8,192 cases each); P also random call sequences (strings with
  embedded 0Dh 0Ah 08h 7Fh 0Ch and other controls, 80h-FFh, crossing 13Fh, empty,
  wrapping DI at FFF8h, interleaved with put-char), compared after every call.
* Random multi-character sequences (printables, controls, 00h, 80h-FFh) from random
  states satisfying I, compared after every character.
* With I broken the replica's output differs (the precondition is real, and the
  harness sees it).

Static (instruction bounded, stock 3.16 image and the cave):
* The only LC7981 port writers (OUT E0h / E2h) are the BIOS copy 0009:1856, the
  BIOS copy's E2h/E0h DX forms nowhere else, 1650:0F8D, 03B0:000A and the cave's
  fast_blit; 03B0:000A is called only from segment 1650 and 1650:0F8D only from
  inside 1650; the cave's only LC7981 writer is fast_blit.
* The BIOS copy's [68AF] and [68AB] writers are 17D4 (0), 183F (cursor, FFh), 17FC
  (cursor + 1 after a put) and 1813 ([68AD]); nothing outside segment 0009 names
  59FA:68AB / 68AF (no relocated 59FA DS load outside 0009 reaches them).
* Every INT 43 in the image is in the BIOS copy or in 0427.
"""
from __future__ import annotations

import random
import re
import shutil
import struct
import subprocess
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
IMG = L << 4
STACK_SEG, STACK_TOP = 0x0800, 0xFFF0
STUB = 0x0700
BIOS_SEG = (0x0009 + L) & 0xFFFF
BIOS_DS = (0x59FA + L) & 0xFFFF
SEG427 = (0x0427 + L) & 0xFFFF
DGROUP = (0x609C + L) & 0xFFFF
SHADOW, CURSOR, VALID = 0x662B, 0x68AB, 0x68AF
STR_SEG = 0x2000                    # string buffer for 0427:0065 (outside image, stack and stub)
CURSORS = (0, 1, 0x27, 0x28, 0xFF, 0x100, 0x13E, 0x13F)
STACK = range((STACK_SEG << 4), (STACK_SEG << 4) + 0x10000)
ARITH = ("cf", "pf", "af", "zf", "sf", "of")


class Cpu(x86sub.Cpu):
    """x86sub with DIV/IDIV leaving pseudo-random arithmetic flags (undefined on the V53)."""

    def __init__(self, *a, seed=0, **k):
        super().__init__(*a, **k)
        self.scramble = random.Random(seed)

    def group3(self, w, seg_o):
        modrm = self.m[self.lin("cs", self.ip)]
        super().group3(w, seg_o)
        if (modrm >> 3) & 7 in (6, 7):
            for f in ARITH:
                self.f[f] = self.scramble.random() < 0.5


class LCD:
    """LC7981 as MAME's HD61830 models it: IR, cursor address (CAC), display RAM, busy polls."""

    def __init__(self, addr: int, busy: int = 0):
        self.addr, self.ram, self.ir, self.busy, self.left = addr, {}, None, busy, 0
        self.log: list[tuple] = []
        self.cpu = None

    def pin(self, port, width):
        assert port == 0xE2, f"IN {port:X}"
        if self.left:
            self.left -= 1
            return 0x80
        return 0x00

    def pout(self, port, v, width):
        assert width == 0 or not width, "word OUT"
        self.log.append((port, v, self.cpu.f["if"]))
        if port == 0xE2:
            self.ir = v
        elif port == 0xE0:
            if self.ir == 0x0A:
                if self.addr & 0x80 and not v & 0x80:      # hd61830.cpp: CAC low-byte carry
                    self.addr = ((((self.addr >> 8) + 1) << 8) | v) & 0xFFFF
                else:
                    self.addr = (self.addr & 0xFF00) | v
            elif self.ir == 0x0B:
                self.addr = (v << 8) | (self.addr & 0xFF)
            elif self.ir == 0x0C:
                self.ram[self.addr] = v
                self.addr = (self.addr + 1) & 0xFFFF
            else:
                raise AssertionError(f"LC7981 instruction {self.ir:02X} from put-char")
        else:
            raise AssertionError(f"OUT {port:X}")
        self.left = self.busy

    def commands(self):
        """(instruction, data) pairs of the log."""
        out, ir = [], None
        for port, v, _ in self.log:
            if port == 0xE2:
                ir = v
            else:
                out.append((ir, v))
        return out


def install_int43(mem: bytearray) -> None:
    cpu = x86sub.Cpu(mem)
    cpu.s.update(cs=BIOS_SEG, ds=0, es=0, ss=STACK_SEG)
    cpu.r["sp"] = STACK_TOP
    cpu.ip = 0x00D2
    while cpu.ip != 0x00DC or cpu.s["cs"] != BIOS_SEG:
        cpu.step()


def redundant_pairs_only(stock: list, cand: list, start_addr: int) -> str | None:
    """None if cand is stock with some (0A,lo)(0B,hi) pairs left out, each one setting the
    address the controller already held; else the first difference."""
    addr, i, j = start_addr, 0, 0
    while i < len(stock):
        if j < len(cand) and stock[i] == cand[j]:
            ir, v = stock[i]
            if ir == 0x0A:
                addr = ((((addr >> 8) + 1) << 8) | v) & 0xFFFF if addr & 0x80 and not v & 0x80 else (addr & 0xFF00) | v
            elif ir == 0x0B:
                addr = (v << 8) | (addr & 0xFF)
            elif ir == 0x0C:
                addr = (addr + 1) & 0xFFFF
            i += 1
            j += 1
            continue
        if (i + 1 < len(stock) and stock[i][0] == 0x0A and stock[i + 1][0] == 0x0B
                and (stock[i + 1][1] << 8 | stock[i][1]) == addr):
            i += 2                                  # a redundant re-address, left out
            continue
        return f"stock command {i} {stock[i]} vs candidate {j} {cand[j] if j < len(cand) else None}"
    return None if j == len(cand) else f"candidate has extra commands from {j}"


@unittest.skipUnless(HAVE_TOOLS, "needs nasm and ndisasm")
class DisplayDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stock_sys = b.M3K316.read_bytes()
        cls.st, _ = rc.simulate(cls.stock_sys, L, home=b.CAVE_HOME, cave_len=0)
        install_int43(cls.st)
        cls.pm, cls.maps = {}, {}
        (ROOT / "build").mkdir(exist_ok=True)
        for name, defines in (("P", ()), ("MX", ("DISPLAY_COMPACT",))):
            with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
                m = b.build(out=Path(tmp), defines=defines)
                sys_bytes = (Path(tmp) / "WAVE316.SYS").read_bytes()
                cls.maps[name] = (Path(tmp) / "wave316.cave.map").read_text()
            copied = 2 * int(m["simulation"]["copy_words"], 16)
            mem, _ = rc.simulate(sys_bytes, L, home=b.CAVE_HOME, cave_len=copied)
            install_int43(mem)
            cls.pm[name] = mem
            if name == "P":
                cls.cave_bin_p = sys_bytes

    # ------------------------------------------------------------ running
    def setup(self, base, cursor, cell_equal, ch, valid, hw, rng):
        mem = bytearray(base)
        d = BIOS_DS << 4
        for i in range(0x280):                 # shadow 662B and the AX=5 copy 676B
            mem[d + SHADOW + i] = rng.randrange(0x20, 0x7F)
        if cell_equal:
            mem[d + SHADOW + cursor] = ch
        elif mem[d + SHADOW + cursor] == ch:
            mem[d + SHADOW + cursor] = ch ^ 0x01
        struct.pack_into("<H", mem, d + CURSOR, cursor)
        struct.pack_into("<H", mem, d + CURSOR + 2, rng.randrange(0x140))    # [68AD]
        mem[d + VALID] = valid
        return mem

    def call(self, mem, code: bytes, lcd: LCD, *, if_=True, flags=0, seed=0):
        c = Cpu(mem, port_in=lcd.pin, port_out=lcd.pout, seed=seed)
        lcd.cpu = c
        c.s.update(cs=0, ds=DGROUP, es=0x1234, ss=STACK_SEG)
        c.r.update(ax=0x1111, bx=0x2222, cx=0x3333, dx=0x4444, si=0x5555, di=0x6666, bp=0x7777, sp=STACK_TOP)
        c.flags = flags
        c.f["if"], c.f["tf"], c.f["df"] = if_, False, bool(flags & 0x400)
        mem[STUB:STUB + len(code) + 1] = code + b"\xF4"
        c.ip = STUB
        try:
            while True:
                c.step()
        except x86sub.Halt:
            pass
        written = {a for a in c.writes if a not in STACK and not STUB <= a < STUB + 32}
        return c, written

    @staticmethod
    def putc_code(ch):
        return b"\x6A" + bytes([ch]) if ch < 0x80 else b"\x68" + struct.pack("<H", ch)

    def putc(self, mem, ch, lcd, **kw):
        code = self.putc_code(ch) + b"\x9A" + struct.pack("<HH", 0x0040, SEG427) + b"\x83\xC4\x02"
        return self.call(mem, code, lcd, **kw)

    @staticmethod
    def regs(c):
        return {**{k: c.r[k] for k in ("ax", "bx", "cx", "dx", "si", "di", "bp", "sp")},
                **{k: c.s[k] for k in ("ds", "es", "ss")}, "flags": c.flags}

    @staticmethod
    def same_memory(ms, mc, ws, wc):
        """Final bytes of every address either run wrote (outside the stack and stub) are equal."""
        return [hex(a) for a in sorted(ws | wc) if ms[a] != mc[a]]

    def compare(self, name, label, s, r, start_addr, ref, cand):
        (sc, slcd), (cc, clcd) = s, r
        self.assertEqual(self.regs(cc), self.regs(sc), f"{name} {label}: registers/flags")
        self.assertEqual(self.same_memory(sc.m, cc.m, ref, cand), [], f"{name} {label}: memory")
        self.assertEqual((clcd.addr, clcd.ram), (slcd.addr, slcd.ram), f"{name} {label}: LC7981")
        self.assertIsNone(redundant_pairs_only(slcd.commands(), clcd.commands(), start_addr),
                          f"{name} {label}: port log")
        self.assertTrue(all(i for _, _, i in clcd.log), f"{name} {label}: an OUT with IF = 0")

    # ------------------------------------------------------------ hook and image facts
    def test_hook_and_relocated_bios_ds(self) -> None:
        image = rc.MZ.parse(self.stock_sys)
        relocs = {o + s * 16 for o, s in image.relocs}
        self.assertIn(0x90 + 0x16B2, relocs, "0009:16B1 MOV AX,59FAh is relocated")
        self.assertEqual(bytes(image.image[0x90 + 0x16B1:0x90 + 0x16B4]), b"\xB8\xFA\x59")
        self.assertEqual(bytes(image.image[0x42B0:0x42C9]).hex(),
                         "558bec8a5e06b80400cd43b80700cd438bd8b80300cd435dcb")
        for name, mem in self.pm.items():
            self.assertEqual(mem[IMG + 0x42B0], 0xEA, name)
            off, sg = struct.unpack_from("<HH", mem, IMG + 0x42B1)
            self.assertEqual(sg, (b.CAVE_HOME + L) & 0xFFFF)
            want = int(re.search(r"^\s+([0-9A-F]+)\s+[0-9A-F]+\s+fast_putc$", self.maps[name], re.M)[1], 16)
            self.assertEqual(off, want, name)
            self.assertEqual(mem[IMG + 0x42B5], 0x90)
            self.assertEqual(mem[IMG + 0x42B6:IMG + 0x42C9], self.st[IMG + 0x42B6:IMG + 0x42C9])
            self.assertEqual(mem[IMG + 0x42D5], 0xEA, name)          # string writer 0427:0065
            off, sg = struct.unpack_from("<HH", mem, IMG + 0x42D6)
            want = int(re.search(r"^\s+([0-9A-F]+)\s+[0-9A-F]+\s+fast_puts$", self.maps[name], re.M)[1], 16)
            self.assertEqual((off, sg), (want, (b.CAVE_HOME + L) & 0xFFFF), name)
            self.assertEqual(mem[IMG + 0x42DA:IMG + 0x42FB], self.st[IMG + 0x42DA:IMG + 0x42FB])
            # 0427:0012 (cursor shape, img 0x4282) is untouched
            self.assertEqual(mem[IMG + 0x4282:IMG + 0x42B0], self.st[IMG + 0x4282:IMG + 0x42B0])

    # ------------------------------------------------------------ Step 1
    def test_step1_class_walk_identical(self) -> None:
        pm = self.pm["P"]
        self.assertNotEqual(pm[IMG + 0x17DE:IMG + 0x17F9], self.st[IMG + 0x17DE:IMG + 0x17F9])
        rng = random.Random(1)
        n = 0
        for ch in range(256):
            for cursor in CURSORS:
                for equal in (True, False):
                    for valid, hw in ((0xFF, cursor), (0xFF, 0x0777), (0, 0x0555)):    # I held, broken, vacuous
                        for if_ in (False, True):
                            seed = rng.randrange(1 << 30)
                            flags = rng.randrange(0x10000) & 0x0ED5
                            out = []
                            for mem in (self.st, pm):
                                m = self.setup(mem, cursor, equal, ch, valid, hw, random.Random(seed))
                                lcd = LCD(hw, busy=seed % 3)
                                code = b"\xB3" + bytes([ch]) + b"\xB8\x04\x00\xCD\x43"
                                c, written = self.call(m, code, lcd, if_=if_, flags=flags, seed=seed)
                                out.append((self.regs(c), {a: m[a] for a in written}, lcd.addr, lcd.ram, lcd.log))
                            self.assertEqual(out[1], out[0], f"BL={ch:02X} cursor={cursor:X} eq={equal} "
                                                             f"[68AF]={valid:02X} hw={hw:X} IF={if_}")
                            n += 1
        self.assertEqual(n, 256 * len(CURSORS) * 2 * 3 * 2)

    # ------------------------------------------------------------ put-char
    def grid(self, name: str) -> int:
        cand = self.pm[name]
        rng = random.Random(2)
        n = 0
        for ch in range(256):
            for cursor in CURSORS:
                for equal in (True, False):
                    for valid in (0, 0xFF):
                        for if_ in (False, True):
                            for busy in (0, 2):
                                seed = rng.randrange(1 << 30)
                                hw = cursor if valid else rng.choice((0x0777, 0x0000, cursor, 0x0140))
                                flags = rng.randrange(0x10000) & 0x0ED5
                                res, writes = [], []
                                for mem in (self.st, cand):
                                    m = self.setup(mem, cursor, equal, ch, valid, hw, random.Random(seed))
                                    lcd = LCD(hw, busy)
                                    c, w = self.putc(m, ch, lcd, if_=if_, flags=flags, seed=seed)
                                    res.append((c, lcd))
                                    writes.append(w)
                                label = (f"BL={ch:02X} cursor={cursor:X} eq={equal} [68AF]={valid:02X} "
                                         f"IF={if_} busy={busy}")
                                self.compare(name, label, res[0], res[1], hw, writes[0], writes[1])
                                n += 1
        return n

    def test_putc_full_replica_grid(self) -> None:
        self.assertEqual(self.grid("P"), 256 * len(CURSORS) * 2 * 2 * 2 * 2)

    def test_putc_compact_grid(self) -> None:
        self.assertEqual(self.grid("MX"), 256 * len(CURSORS) * 2 * 2 * 2 * 2)

    def sequences(self, name: str, trials: int) -> int:
        cand = self.pm[name]
        rng = random.Random(3)
        chars = 0
        alphabet = [0x20, 0x41, 0x42, 0x30, 0x31]
        rare = [0x0D, 0x0A, 0x08, 0x7F, 0x0C, 0x00, 0x01, 0x1F, 0x80, 0xA5, 0xFF, 0x7E]
        for trial in range(trials):
            start = rng.choice([0, 0xF0, 0xFA, 0x118, 0x130, 0x13A, 0x13F, rng.randrange(0x140)])
            shadow = bytes(rng.choice(alphabet) for _ in range(0x140))
            text = [rng.choice(rare) if rng.random() < 0.12 else rng.choice(alphabet)
                    for _ in range(rng.randrange(1, 70))]
            valid = rng.choice([0, 0xFF])
            hw = start if valid else rng.randrange(0x10000)
            busy = rng.choice([0, 1, 3])
            mems, lcds = [], []
            for base in (self.st, cand):
                m = bytearray(base)
                d = BIOS_DS << 4
                m[d + SHADOW:d + SHADOW + 0x140] = shadow
                struct.pack_into("<H", m, d + CURSOR, start)
                m[d + VALID] = valid
                mems.append(m)
                lcds.append(LCD(hw, busy))
            for k, ch in enumerate(text):
                res, writes, logs0 = [], [], []
                addr0 = lcds[0].addr
                for m, lcd in zip(mems, lcds):
                    logs0.append(len(lcd.log))
                    c, w = self.putc(m, ch, lcd, if_=True, flags=0x0202, seed=trial * 100 + k)
                    res.append(c)
                    writes.append(w)
                s_cmds = LCD.commands(type("x", (), {"log": lcds[0].log[logs0[0]:]})())
                c_cmds = LCD.commands(type("x", (), {"log": lcds[1].log[logs0[1]:]})())
                label = f"trial {trial} char {k} ({ch:02X}) of {bytes(text).hex()}"
                self.assertEqual(self.regs(res[1]), self.regs(res[0]), f"{name} {label}")
                self.assertEqual(self.same_memory(mems[0], mems[1], writes[0], writes[1]), [],
                                 f"{name} {label}: memory")
                self.assertEqual((lcds[1].addr, lcds[1].ram), (lcds[0].addr, lcds[0].ram), f"{name} {label}")
                self.assertIsNone(redundant_pairs_only(s_cmds, c_cmds, addr0), f"{name} {label}: port log")
                chars += 1
            self.assertEqual(mems[1][(BIOS_DS << 4):(BIOS_DS << 4) + 0x68B0],
                             mems[0][(BIOS_DS << 4):(BIOS_DS << 4) + 0x68B0])
        return chars

    def test_putc_sequences(self) -> None:
        for name in ("P", "MX"):
            with self.subTest(variant=name):
                self.assertGreater(self.sequences(name, 300), 9000)

    def test_broken_invariant_is_visible(self) -> None:
        """[68AF] = FFh with the LC7981 address elsewhere: stock re-syncs after the first
        character, the replica keeps writing at the stale address.  Two changed characters."""
        cand = self.pm["P"]
        ram = []
        for mem in (self.st, cand):
            m = self.setup(mem, 0x10, False, 0x41, 0xFF, 0x0777, random.Random(9))
            m[(BIOS_DS << 4) + SHADOW + 0x11] = 0x20
            lcd = LCD(0x0777)
            self.putc(m, 0x41, lcd)
            self.putc(m, 0x42, lcd)
            ram.append(lcd.ram)
        self.assertEqual(ram[0], {0x0777: 0x41, 0x0011: 0x42})
        self.assertEqual(ram[1], {0x0777: 0x41, 0x0778: 0x42})

    # ------------------------------------------------------------ string writer 0427:0065
    def puts(self, mem, text: bytes, lcd, *, where=(STR_SEG, 0x0010), **kw):
        seg_, off = where
        for i, ch in enumerate(text + b"\0"):
            mem[((seg_ << 4) + ((off + i) & 0xFFFF)) & 0xFFFFF] = ch
        code = (b"\x68" + struct.pack("<H", seg_) + b"\x68" + struct.pack("<H", off)
                + b"\x9A" + struct.pack("<HH", 0x0065, SEG427) + b"\x83\xC4\x04")
        return self.call(mem, code, lcd, **kw)

    def string_grid(self, name: str) -> int:
        """Empty string and every one-byte string (01h-FFh), each cursor, cell equal /
        unequal, [68AF] 0 / FFh, IF 0 / 1."""
        cand = self.pm[name]
        rng = random.Random(5)
        n = 0
        for ch in range(256):
            text = bytes([ch]) if ch else b""
            for cursor in CURSORS:
                for equal in (True, False):
                    for valid in (0, 0xFF):
                        for if_ in (False, True):
                            seed = rng.randrange(1 << 30)
                            hw = cursor if valid else rng.choice((0x0777, 0x0000, cursor))
                            flags = rng.randrange(0x10000) & 0x0ED5
                            busy = seed % 3
                            res, writes = [], []
                            for mem in (self.st, cand):
                                m = self.setup(mem, cursor, equal, ch, valid, hw, random.Random(seed))
                                lcd = LCD(hw, busy)
                                c, w = self.puts(m, text, lcd, if_=if_, flags=flags, seed=seed)
                                res.append((c, lcd))
                                writes.append(w)
                            label = f"puts {text.hex() or 'empty'} cursor={cursor:X} eq={equal} [68AF]={valid:02X} IF={if_}"
                            self.compare(name, label, res[0], res[1], hw, writes[0], writes[1])
                            n += 1
        return n

    def test_puts_grid(self) -> None:
        for name in ("P", "MX"):
            with self.subTest(variant=name):
                self.assertEqual(self.string_grid(name), 256 * len(CURSORS) * 2 * 2 * 2)

    def string_sequences(self, name: str, trials: int) -> tuple[int, int]:
        """Random strings (printables, embedded 0Dh 0Ah 08h 7Fh 0Ch, other controls,
        80h-FFh), many crossing 13Fh, some at offset FFF8h (DI wraps in the segment),
        interleaved with put-char calls, from random states satisfying I."""
        cand = self.pm[name]
        rng = random.Random(6)
        alphabet = [0x20, 0x41, 0x42, 0x30, 0x31]
        rare = [0x0D, 0x0A, 0x08, 0x7F, 0x0C, 0x01, 0x1F, 0x80, 0xA5, 0xFF, 0x7E]
        calls = chars = 0
        for trial in range(trials):
            start = rng.choice([0, 0xF0, 0x118, 0x130, 0x13A, 0x13F, rng.randrange(0x140)])
            shadow = bytes(rng.choice(alphabet) for _ in range(0x140))
            valid = rng.choice([0, 0xFF])
            hw = start if valid else rng.randrange(0x10000)
            busy = rng.choice([0, 1, 3])
            mems, lcds = [], []
            for base in (self.st, cand):
                m = bytearray(base)
                d = BIOS_DS << 4
                m[d + SHADOW:d + SHADOW + 0x140] = shadow
                struct.pack_into("<H", m, d + CURSOR, start)
                m[d + VALID] = valid
                mems.append(m)
                lcds.append(LCD(hw, busy))
            for k in range(rng.randrange(1, 8)):
                if rng.random() < 0.25:
                    op, arg = "putc", rng.choice(alphabet + rare)
                else:
                    op = "puts"
                    arg = bytes(rng.choice(rare) if rng.random() < 0.1 else rng.choice(alphabet)
                                for _ in range(rng.choice([0, 1, 5, 40, rng.randrange(80)])))
                where = (STR_SEG, 0xFFF8) if rng.random() < 0.1 else (STR_SEG, 0x0010 + rng.randrange(64))
                flags = rng.randrange(0x10000) & 0x0ED5
                res, writes, logs0 = [], [], []
                addr0 = lcds[0].addr
                for m, lcd in zip(mems, lcds):
                    logs0.append(len(lcd.log))
                    if op == "putc":
                        c, w = self.putc(m, arg, lcd, if_=True, flags=flags, seed=trial)
                    else:
                        c, w = self.puts(m, arg, lcd, where=where, if_=True, flags=flags, seed=trial)
                    res.append(c)
                    writes.append(w)
                s_cmds = LCD.commands(type("x", (), {"log": lcds[0].log[logs0[0]:]})())
                c_cmds = LCD.commands(type("x", (), {"log": lcds[1].log[logs0[1]:]})())
                label = f"trial {trial} call {k} {op} {arg if op == 'putc' else arg.hex()}"
                self.assertEqual(self.regs(res[1]), self.regs(res[0]), f"{name} {label}")
                self.assertEqual(self.same_memory(mems[0], mems[1], writes[0], writes[1]), [],
                                 f"{name} {label}: memory")
                self.assertEqual((lcds[1].addr, lcds[1].ram), (lcds[0].addr, lcds[0].ram), f"{name} {label}")
                self.assertIsNone(redundant_pairs_only(s_cmds, c_cmds, addr0), f"{name} {label}: port log")
                self.assertTrue(all(i for _, _, i in lcds[1].log[logs0[1]:]), f"{name} {label}: OUT with IF = 0")
                calls += 1
                chars += len(arg) if op == "puts" else 1
        return calls, chars

    def test_puts_sequences(self) -> None:
        calls, chars = self.string_sequences("P", 700)
        self.assertGreater(calls, 2000)
        self.assertGreater(chars, 30000)

    # ------------------------------------------------------------ static
    def test_static_invariant_writers(self) -> None:
        """Who can break I, and that text output is kept away from them (stock 3.16 image)."""
        image = rc.MZ.parse(self.stock_sys)
        im = bytes(image.image)
        relocs = sorted(o + s * 16 for o, s in image.relocs)

        # 1. LC7981 port writes.  OUT imm8 to E0h/E2h: only 0009:185F / 1868 (img 0x18EF,
        # 0x18F8).  Every other E6/E7 E0/E2 byte pair is the disp16 0E0E6h/0E2E6h/0E2E7h of a
        # ModRM-direct or moffs instruction (MUTE_RECORD and its neighbours), not an OUT.
        imm = [m.start() for m in re.finditer(rb"[\xE6\xE7][\xE0\xE2]", im)]
        operand = [h for h in imm if (im[h - 1] & 0xC7) == 0x06 or im[h - 1] in (0xA0, 0xA1, 0xA2, 0xA3)]
        self.assertEqual(sorted(set(imm) - set(operand)), [0x18EF, 0x18F8])
        self.assertEqual({im[h - 2:h].hex() for h in operand if (im[h - 1] & 0xC7) == 0x06},
                         {"c41e", "8b1e", "8b36", "8b3e", "ff36"})
        # OUT DX: DX = 00E0h / 00E2h is loaded (MOV DX,imm16; no MOV DL / push / MOV AX of
        # the port anywhere) only in 03B0:00FD (img 0x3BFD) and 1650:0F8D (img 0x1748D).
        dx = sorted(m.start() for m in re.finditer(rb"\xBA[\xE0\xE2]\x00", im))
        self.assertEqual(dx, [0x3C01, 0x3C0A, 0x3C16, 0x17490, 0x1749C])
        for pat in (rb"\xB2[\xE0\xE2]", rb"\x68[\xE0\xE2]\x00", rb"\xB8[\xE0\xE2]\x00"):
            self.assertIsNone(re.search(pat, im), pat)
        self.assertEqual(im[0x3BFD:0x3C1C].hex(),
                         "5286c450bae200ecd0d072f858bae200ee90909090909086e0bae000ee5ac3")
        self.assertEqual(im[0x1748D:0x174A5].hex(), "558becbae200eca88075f88a4606eebae0008a4608ee5dcb")
        # 03B0:00FD is near-called only inside 03B0:000A (img 0x3B0A..0x3C1C); 03B0:000A is
        # far-called only from segment 1650 (img 0x16500..0x18490); 1650:0F8D only by near
        # calls inside 1650: 03CD (3), 03FD (4), 0F01 (2 + per byte), 0F53 (4).
        def near_callers(target):
            return [a for a in range(len(im) - 3) if im[a] == 0xE8
                    and (a + 3 + struct.unpack_from("<h", im, a + 1)[0]) == target]
        self.assertTrue(all(0x3B0A <= a < 0x3C1C for a in near_callers(0x3BFD)))
        far = lambda seg, off: [r - 3 for r in relocs if r >= 2 and struct.unpack_from("<HH", im, r - 2) == (off, seg)]  # noqa: E731
        c03b0 = far(0x03B0, 0x000A)
        self.assertEqual(len(c03b0), 11)
        self.assertTrue(all(0x16500 <= a < 0x18490 and im[a] == 0x9A for a in c03b0), c03b0)
        self.assertEqual(far(0x1650, 0x0F8D) + far(0x03B0, 0x00FD), [])
        inner = [a - 0x16500 for a in near_callers(0x1748D)]
        self.assertEqual(inner, [0x03D4, 0x03E0, 0x03EE, 0x0407, 0x0413, 0x041F, 0x042B,
                                 0x0F08, 0x0F14, 0x0F44, 0x0F5E, 0x0F6A, 0x0F76, 0x0F82])
        # 2. Segment 1650's far entries (all callers are CALLF): 0001, 03CD, 03FD, 1C4B, 1D77.
        entries = sorted({struct.unpack_from("<H", im, r - 2)[0] for r in relocs
                          if struct.unpack_from("<H", im, r)[0] == 0x1650 and im[r - 3] == 0x9A})
        self.assertEqual(entries, [0x0001, 0x03CD, 0x03FD, 0x1C4B, 0x1D77])
        # 3. The graphics protocol.  [95C9] (DGROUP) = 1 while graphics are shown: set only by
        # 1650:0F53 (graphics mode + blit; 1650:0EBD draws and ends in it), cleared only by 1650:03FD
        # after 1650:0431 CALLF 0427:000C (INT 43 AX=1: 183F(0), 320 cells, 183F(0): I
        # holds).  03CD (graphics RAM clear) is far-called once, at img 0xF8A6, followed by
        # CALLF 0427:000C at 0xF8AB.  Every other reader of [95C9] prints only when it is 0
        # (four background printers) or leaves graphics first through 1650:03FD (0x6553).
        refs = sorted(m.start() for m in re.finditer(rb"\xC9\x95", im))
        self.assertEqual(refs, [0x6553, 0x16938, 0x17455, 0x34841, 0x37DFC, 0x3C221, 0x3C25D])
        self.assertEqual(im[0x16936:0x1693C].hex(), "c606c99500cb")      # 1650:0436 = 0, RETF
        self.assertEqual(im[0x16931:0x16936].hex(), "9a0c002704")        # 1650:0431 CALLF 0427:000C
        self.assertEqual(im[0x427C:0x4282].hex(), "b80100cd43cb")          # 0427:000C: INT 43 AX=1
        self.assertEqual(im[0x17453:0x17458].hex(), "c606c99501")        # 1650:0F53 = 1
        self.assertEqual(im[0x0F8A6:0x0F8B0].hex(), "9acd0350169a0c002704")
        self.assertEqual(im[0x6551:0x655D].hex(), "803ec99500740a9afd035016")
        for a, skip in ((0x34840, "a0c995980bc07403e999"), (0x37DFB, "a0c995980bc07533"),
                        (0x3C220, "a0c995980bc07533"), (0x3C25C, "a0c995980bc07505")):
            self.assertEqual(im[a:a + len(skip) // 2].hex(), skip, hex(a))
        body = [m.start() for m in re.finditer(rb"\xC6\x06\xC9\x95\x01", im)]
        self.assertEqual(body, [0x17453])
        # 4. BIOS copy objects: [68AF] written only by 17D4 (0) and 1850 (FFh, in 183F), [68AB]
        # only by 17FC (cursor + 1) and 183F; nothing outside 0009 names them (DS 59FA).
        self.assertEqual(sorted(m.start() for m in re.finditer(rb"\xC6\x06\xAF\x68", im)),
                         [0x90 + 0x17D4, 0x90 + 0x1850])
        self.assertEqual(sorted(m.start() for m in re.finditer(rb"\xA3\xAB\x68", im)),
                         [0x90 + 0x17FC, 0x90 + 0x183F])
        # Relocated 59FA words outside the BIOS copy: 0x1092F/0x1094B copy 1E7Bh words to
        # 59FA:024D (ends 3F43, below the shadow) and store that far pointer at DGROUP E45F
        # (its initial value is the far pointer at img 0x64520); 0x485AC/0x485D3 are the OS
        # reload (SS = 59FA, SP = 69C4, then INT 45: the EPROM re-initialises 59FA).
        ds_loads = [r for r in relocs if struct.unpack_from("<H", im, r)[0] == 0x59FA]
        self.assertEqual([hex(r) for r in ds_loads if not 0x90 <= r < 0x90 + 0x2000],
                         ["0x1092f", "0x1094b", "0x485ac", "0x485d3", "0x64522"])
        self.assertEqual(im[0x1092E:0x1093F].hex(), "b8fa59bf4d028b1661e48b365fe4b97b1e")
        self.assertLess(0x024D + 2 * 0x1E7B, SHADOW)
        # INT 43 only in the BIOS copy and in 0427 (img 0x4270..0x4340).
        ints = [m.start() for m in re.finditer(rb"\xCD\x43", im)]
        self.assertTrue(all(0x90 <= a < 0x90 + 0x2000 or 0x4270 <= a < 0x4340 for a in ints),
                        [hex(a) for a in ints])

    def test_static_cave_lcd_writers(self) -> None:
        """The cave writes the LC7981 only in fast_blit (graphics mode: wave view and mute
        page, each between T_C4C8_0F5F and T_C4C8_0409) and in display316.inc's put-char."""
        sources = {p.name: p.read_text() for p in (ROOT / "mods").glob("*.inc")}
        sources["wave.asm"] = (ROOT / "mods" / "wave.asm").read_text()
        outs = sorted((n, re.sub(r"\s+", " ", line.split(";")[0].strip()))
                      for n, t in sources.items() if n not in ("profile_capture.inc", "profile_vailixi.inc")
                      for line in t.splitlines() if re.search(r"\bout\s+0x?E[02]", line, re.I))
        self.assertEqual(outs, [("display316.inc", "out 0xE0, al"), ("display316.inc", "out 0xE2, al"),
                                ("wave.asm", "out 0xE0, al"), ("wave.asm", "out 0xE0, al"),
                                ("wave.asm", "out 0xE2, al"), ("wave.asm", "out 0xE2, al")])
        calls = sorted((n, i) for n, t in sources.items() for i, line in enumerate(t.splitlines())
                       if re.match(r"\s*(\.\w+:)?\s*call\s+fast_blit", line))
        self.assertEqual([n for n, _ in calls], ["mute_ui.inc", "wave.asm"])
        ints = [n for n, t in sources.items() if re.search(r"^\s*int\s+0x43", t, re.M | re.I)]
        self.assertEqual(ints, ["display316.inc"])

if __name__ == "__main__":
    unittest.main()
