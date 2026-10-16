"""PMONEY performance items against the stock 3.16 bytes they replace (no MAME).

    python3 -m unittest tests.test_perf316_diff -v

The pinned PMONEY build (mods/build_wave316.py) and the stock M3K316.SYS are each
loaded as the EPROM loader leaves them at L = 6900 (route_c.simulate).  Each test
runs the stock routine in the stock image and the same entry in the PMONEY image,
where the hook leads into the cave, in tests/x86sub.py, from the same registers and
memory, and requires the same result:

* S6 and D1a are not built (the cave home must end at or below image 0x83300):
      their sites keep the stock bytes, and their differential tests left with them.
* P4  pad lookup: 301D:003B against the cave entry the two patched call sites name,
      for every note word a caller can pass, both table modes, random tables: same AX
      and SI, DI, BP, DS, SP.
* B2  REVERSE buffer swap 0B72:1BDD (-> rev_words): same SND_SEG bytes and SI, DI, BP,
      DS, SP for n around 0, the 1200h limit, n >= 10000h and n < 0.
* S3  the three empty-ring gates: the stock call they replace changes no memory and
      returns AX = 0 when the gate's condition holds; otherwise the gate enters the
      stock routine (same memory and AX as stock).
"""
from __future__ import annotations

import random
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
STACK_SEG, STACK_TOP = 0x0800, 0xFFF0
STUB = 0x0700                       # code stub at 0000:0700, HLT sentinel follows the call
DGROUP = (0x609C + L) & 0xFFFF
SND_SEG = (0x539D + L) & 0xFFFF
RING_SEG = (0x77CA + L) & 0xFFFF
BIOS_SEG = (0x0009 + L) & 0xFFFF


def seg(rel: int) -> int:
    return (rel + L) & 0xFFFF


@unittest.skipUnless(HAVE_TOOLS, "needs nasm and ndisasm")
class PerfDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            m = b.build(out=Path(tmp))
            sys_bytes = (Path(tmp) / "WAVE316.SYS").read_bytes()
        copied = 2 * int(m["simulation"]["copy_words"], 16)
        cls.pm, _ = rc.simulate(sys_bytes, L, home=b.CAVE_HOME, cave_len=copied)
        cls.st, _ = rc.simulate(b.M3K316.read_bytes(), L, home=b.CAVE_HOME, cave_len=0)
        # Install IVT 43h as each OS does at 0009:00D2.
        for mem in (cls.st, cls.pm):
            cpu = x86sub.Cpu(mem)
            cpu.s.update(cs=BIOS_SEG, ds=0, es=0, ss=STACK_SEG)
            cpu.r["sp"] = STACK_TOP
            cpu.ip = 0x00D2
            while cpu.ip != 0x00DC or cpu.s["cs"] != BIOS_SEG:
                cpu.step()
        cls.vec43 = {name: struct.unpack_from("<HH", mem, 0x10C) for name, mem in (("st", cls.st), ("pm", cls.pm))}

    # ------------------------------------------------------------ helpers
    def cpu(self, mem, *, ports=None, **regs):
        log = []
        busy = {"left": 0}
        script = ports or {}

        def pin(port, width):
            log.append(("in", port))
            if port == 0xE2:
                if busy["left"]:
                    busy["left"] -= 1
                    return 0x80
                return 0x00
            return 0xFF

        def pout(port, value, width):
            log.append(("out", port, value))
            if port in (0xE0, 0xE2):
                busy["left"] = script.get("busy", 0)

        c = x86sub.Cpu(mem, port_in=pin, port_out=pout)
        c.s.update(cs=0, ds=DGROUP, es=DGROUP, ss=STACK_SEG)
        c.r["sp"] = STACK_TOP
        c.f["if"] = True
        for k, v in regs.items():
            if k in c.r:
                c.r[k] = v & 0xFFFF
            elif k in c.s:
                c.s[k] = v & 0xFFFF
            elif k in c.f:
                c.f[k] = v
        busy["left"] = script.get("busy", 0)
        return c, log

    def run_stub(self, c, code: bytes):
        c.m[STUB:STUB + len(code) + 1] = code + b"\xF4"
        c.s["cs"], c.ip = 0, STUB
        try:
            while True:
                c.step()
        except x86sub.Halt:
            pass

    @staticmethod
    def state(c):
        return dict(c.r), {k: c.s[k] for k in ("ds", "es", "ss")}, c.flags

    # ------------------------------------------------------------ S6, D1a: not built
    def test_s6_and_d1a_sites_keep_the_stock_bytes(self) -> None:
        """S6 and D1a are left out (cave home bound, tests/test_build_wave316.py): IVT 43h
        stays the stock handler and the BIOS copy's install and free-cluster loop bytes
        (img 0x162, 0x163C) are stock."""
        self.assertEqual(self.vec43["pm"], self.vec43["st"])
        self.assertEqual(self.vec43["st"], (0x16A6, BIOS_SEG))
        image = (L << 4)
        for site, n in ((0x162, 10), (0x163C, 5)):
            self.assertEqual(self.pm[image + site:image + site + n], self.st[image + site:image + site + n], hex(site))

    # ------------------------------------------------------------ P4
    def test_p4_pad_lookup(self) -> None:
        sites = [0x3086B, 0x3266]
        target = {}
        for site in sites:
            off, sg = struct.unpack_from("<HH", self.pm, (L << 4) + site + 1)
            target[site] = (off, sg)
            self.assertEqual(self.pm[(L << 4) + site], 0x9A)
        self.assertEqual(len(set(target.values())), 1)
        cave = target[sites[0]]
        stock = (0x003B, seg(0x301D))
        rng = random.Random(4)
        notes = list(range(0, 0x80)) + list(range(0xFF80, 0x10000)) + [0x80, 0xFF, 0x100, 0x7FFF, 0x8000]
        tables = [bytes(0x25 + i for i in range(64)), bytes(0x62 - i for i in range(64))]
        for _ in range(4):
            t = bytearray(rng.randrange(0x10, 0xA0) for _ in range(64))
            t[rng.randrange(64)] = t[rng.randrange(64)]
            tables.append(bytes(t))
        for mode in (0, 1):
            for table in tables:
                for note in notes:
                    results = []
                    for mem, (off, sg) in ((self.st, stock), (self.pm, cave)):
                        mem = bytearray(mem)
                        dg = DGROUP << 4
                        mem[dg + 0x8063] = mode
                        mem[dg + 0x8064:dg + 0x8064 + 64] = table if mode else bytes(64)
                        struct.pack_into("<HH", mem, dg + 0xE2E6, 0x0100, 0x3000)
                        rec = (0x3000 << 4) + 0x0100 + 0x73E
                        mem[rec:rec + 64] = bytes(64) if mode else table
                        c, _ = self.cpu(mem, si=0x1111, di=0x2222, bp=0x3333)
                        code = b"\x68" + struct.pack("<H", note) + b"\x9A" + struct.pack("<HH", off, sg) + b"\x83\xC4\x02"
                        self.run_stub(c, code)
                        st = self.state(c)
                        results.append(({k: st[0][k] for k in ("ax", "si", "di", "bp", "sp")}, st[1]["ds"]))
                    self.assertEqual(results[0], results[1], f"note {note:04X} mode {mode} table {table.hex()}")

    # ------------------------------------------------------------ B2
    def test_b2_reverse_swap(self) -> None:
        rng = random.Random(2)
        data = bytes(rng.randrange(256) for _ in range(0x10000))
        cases = [(n, 0, idx) for n in (0, 1, 2, 3, 4, 7, 0x101) for idx in (0, 1)]
        cases += [(0x11FF, 0, 1), (0x1200, 0, 0), (0x1201, 0, 0), (0xFFFF, 0, 0), (5, 1, 0), (0xFFFE, 0xFFFF, 0),
                  (9, 0, 0xFF)]
        for n, hi, idx in cases:
            results = []
            for mem in (self.st, self.pm):
                mem = bytearray(mem)
                base = SND_SEG << 4
                mem[base:base + 0x10000] = data
                c, _ = self.cpu(mem, si=0x1111, di=0x2222, bp=0x3333, df=False)
                code = (b"\x68" + struct.pack("<H", idx) + b"\x68" + struct.pack("<H", hi)
                        + b"\x68" + struct.pack("<H", n)
                        + b"\x9A" + struct.pack("<HH", 0x1BDD, seg(0x0B72)) + b"\x83\xC4\x06")
                self.run_stub(c, code)
                st = self.state(c)
                results.append(({k: st[0][k] for k in ("si", "di", "bp", "sp")}, st[1]["ds"], st[1]["ss"],
                                c.f["df"], bytes(mem[base:base + 0x10000])))
            self.assertEqual(results[0], results[1], f"n={hi:04X}{n:04X} idx={idx}")

    # ------------------------------------------------------------ S3
    def _ring(self, mem, header: int, size: int, count: int, rng) -> None:
        base = RING_SEG << 4
        struct.pack_into("<HHHH", mem, base + header, size, count, rng.randrange(size), rng.randrange(size))
        for i in range(size):
            mem[base + header + 8 + i] = rng.randrange(256)

    def test_s3_gates(self) -> None:
        rng = random.Random(3)
        hooks = {"live": (0x42561, (0x0008, seg(0x3094)), b"", b""),
                 "pad": (0x42566, (0x000B, seg(0x3045)), b"", b""),
                 "evt": (0x33B07, (0x001E, seg(0x2EE7)), b"\x6A\x0A\x16\x55\x6A\x08", b"\x83\xC4\x08")}
        for name, (site, stock, pre, post) in hooks.items():
            gate = struct.unpack_from("<HH", self.pm, (L << 4) + site + 1)
            self.assertNotEqual(gate, stock)
            for case in range(10):
                empty = case < 6

                def memory(base_mem):
                    mem = bytearray(base_mem)
                    r = random.Random(case)
                    pend = 0 if (empty or name != "live") else r.choice([0x0001, 0x0100, 0x0101])
                    struct.pack_into("<H", mem, (DGROUP << 4) + 0x965E, pend)
                    self._ring(mem, 0x0734, 0x05F5, r.randrange(0, 0x5F6) if name == "live" else 0, r)
                    self._ring(mem, 0x0D31, 0x05F5, r.randrange(0, 0x5F6) if name == "live" else 0, r)
                    self._ring(mem, 0x06AC, 0x0080, 0 if (empty or name != "pad") else r.randrange(1, 4), r)
                    self._ring(mem, 0x2B36, 0x0100, 0 if (empty or name != "evt") else 10 * r.randrange(1, 3), r)
                    return mem

                code = lambda off, sg: pre + b"\x9A" + struct.pack("<HH", off, sg) + post   # noqa: E731
                if empty:
                    # The stock call finds nothing: no memory written outside the stack, AX = 0.
                    # The gate returns at once with the same AX, SP and DS.
                    out = []
                    for mem, (off, sg) in ((self.st, stock), (self.pm, gate)):
                        mem = memory(mem)
                        c, _ = self.cpu(mem, bp=0xFF00, si=0x0004)
                        c.writes = set()
                        self.run_stub(c, code(off, sg))
                        stack = range((STACK_SEG << 4) + 0x8000, (STACK_SEG << 4) + 0x10000)
                        wrote = sorted(a for a in c.writes if a not in stack and not STUB <= a < STUB + 32)
                        self.assertEqual(wrote, [], f"{name} case {case}: memory written")
                        out.append((c.r["ax"], c.r["sp"], c.s["ds"]))
                    self.assertEqual(out[0], out[1], f"{name} case {case}")
                    self.assertEqual(out[0][0], 0)
                else:
                    # Something to read: the gate enters the stock routine with the stock
                    # stack frame and registers.
                    ref = self.cpu(memory(self.st), bp=0xFF00, si=0x0004)[0]
                    ref.m[STUB:STUB + 32] = code(*stock).ljust(32, b"\xF4")
                    ref.s["cs"], ref.ip = 0, STUB
                    while (ref.s["cs"], ref.ip) != (stock[1], stock[0]):
                        ref.step()
                    c = self.cpu(memory(self.pm), bp=0xFF00, si=0x0004)[0]
                    c.m[STUB:STUB + 32] = code(*gate).ljust(32, b"\xF4")
                    c.s["cs"], c.ip = 0, STUB
                    try:
                        while (c.s["cs"], c.ip) != (stock[1], stock[0]):
                            c.step()
                            self.assertLess(c.steps, 50, f"{name} case {case}: gate did not enter the stock routine")
                    except x86sub.Halt:
                        self.fail(f"{name} case {case}: the gate returned although the stock routine has work")
                    frame = lambda x: [x.rw("ss", x.r["sp"] + 2 * k) for k in range(5)]   # noqa: E731
                    keep = ("cx", "dx", "bx", "sp", "bp", "si", "di")
                    self.assertEqual(({k: c.r[k] for k in keep}, dict(c.s), frame(c)[1:]),
                                     ({k: ref.r[k] for k in keep}, dict(ref.s), frame(ref)[1:]),
                                     f"{name} case {case}")


if __name__ == "__main__":
    unittest.main()
