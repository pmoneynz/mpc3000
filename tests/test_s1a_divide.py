"""S1a fast divide against the BIOS runtime, by executing both byte streams.

    python3 -m unittest tests.test_s1a_divide -v

A minimal 16-bit interpreter (only the encodings that occur in the cave
routine and in F800:20F7..21A5) runs the stock runtime from the pinned
Vailixi 3.50 image and the assembled cave (mods/s1a.asm, built by
mods/build_mod_sys.py) on the same operands.  For every case the two must
agree on the quotient, on whether a divide fault (INT 0) is raised, on the
8 popped operand bytes, and on SI, DI, BP, DS, ES.  It also checks that the
built S1A image redirects exactly the 17 divide calls of CFC6:039E and
changes nothing else in the relocated OS.
"""
from __future__ import annotations

import random
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mods"))
sys.path.insert(0, str(ROOT))

import build_mod_sys as mod  # noqa: E402
from tools.linear_rom import load_vailixi_linear  # noqa: E402

CAVE_SEG = mod.CAVE_SEG
REGS = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")


class DivideFault(Exception):
    pass


class Cpu:
    """Enough of an 8086 for the two divide routines; raises on anything else."""

    def __init__(self, mem: bytearray):
        self.m = mem
        self.r = dict.fromkeys(REGS, 0)
        self.seg = {"cs": 0, "ss": 0x1000, "ds": 0x2000, "es": 0x3000}
        self.ip = 0
        self.cf = self.zf = self.sf = self.of = False
        self.steps = 0

    # memory
    def rb(self, seg, off): return self.m[((self.seg[seg] << 4) + (off & 0xFFFF)) & 0xFFFFF]
    def rw(self, seg, off): return self.rb(seg, off) | self.rb(seg, off + 1) << 8

    def ww(self, seg, off, v):
        a = ((self.seg[seg] << 4) + (off & 0xFFFF)) & 0xFFFFF
        self.m[a] = v & 0xFF
        self.m[(a + 1) & 0xFFFFF] = (v >> 8) & 0xFF

    def fetch(self):
        b = self.rb("cs", self.ip)
        self.ip = (self.ip + 1) & 0xFFFF
        return b

    def fetchw(self): return self.fetch() | self.fetch() << 8
    def push(self, v): self.r["sp"] = (self.r["sp"] - 2) & 0xFFFF; self.ww("ss", self.r["sp"], v)

    def pop(self):
        v = self.rw("ss", self.r["sp"])
        self.r["sp"] = (self.r["sp"] + 2) & 0xFFFF
        return v

    # operands (16-bit only: both routines use word forms)
    def modrm(self):
        b = self.fetch()
        mod_, reg, rm = b >> 6, (b >> 3) & 7, b & 7
        if mod_ == 3:
            return reg, ("r", REGS[rm])
        if mod_ == 1 and rm == 6:
            d = self.fetch()
            return reg, ("m", (self.r["bp"] + (d - 256 if d & 0x80 else d)) & 0xFFFF)
        raise NotImplementedError(f"modrm {b:02X}")

    def get(self, opd):
        return self.r[opd[1]] if opd[0] == "r" else self.rw("ss", opd[1])

    def put(self, opd, v):
        if opd[0] == "r":
            self.r[opd[1]] = v & 0xFFFF
        else:
            self.ww("ss", opd[1], v)

    def flags(self, res, carry, overflow=False):
        self.cf, self.of = carry, overflow
        self.zf = (res & 0xFFFF) == 0
        self.sf = bool(res & 0x8000)

    def alu(self, op, a, b):
        """op: 0 add 1 or 2 adc 3 sbb 4 and 5 sub 6 xor 7 cmp; returns (result, store?)."""
        if op == 1:
            r = a | b; self.flags(r, False); return r, True
        if op == 4:
            r = a & b; self.flags(r, False); return r, True
        if op == 6:
            r = a ^ b; self.flags(r, False); return r, True
        if op in (0, 2):
            r = a + b + (self.cf if op == 2 else 0)
            self.flags(r, r > 0xFFFF, bool(~(a ^ b) & (a ^ r) & 0x8000)); return r & 0xFFFF, True
        if op in (3, 5, 7):
            r = a - b - (self.cf if op == 3 else 0)
            self.flags(r & 0xFFFF, r < 0, bool((a ^ b) & (a ^ r) & 0x8000)); return r & 0xFFFF, op != 7
        raise NotImplementedError(op)

    def step(self):
        self.steps += 1
        if self.steps > 100_000:
            raise RuntimeError("runaway")
        op = self.fetch()
        ALU = {0x01: 0, 0x03: 0, 0x09: 1, 0x0B: 1, 0x19: 3, 0x1B: 3, 0x29: 5, 0x2B: 5,
               0x31: 6, 0x33: 6, 0x39: 7, 0x3B: 7}
        if op in ALU:
            reg, opd = self.modrm()
            r = ("r", REGS[reg])
            dst, src = (opd, r) if op & 2 == 0 else (r, opd)
            v, store = self.alu(ALU[op], self.get(dst), self.get(src))
            if store:
                self.put(dst, v)
        elif op in (0x89, 0x8B):
            reg, opd = self.modrm()
            if op == 0x89:
                self.put(opd, self.r[REGS[reg]])
            else:
                self.r[REGS[reg]] = self.get(opd)
        elif op == 0x87:
            reg, opd = self.modrm()
            a, b = self.r[REGS[reg]], self.get(opd)
            self.r[REGS[reg]] = b
            self.put(opd, a)
        elif op == 0x83:
            reg, opd = self.modrm()
            imm = self.fetch()
            imm = imm | 0xFF00 if imm & 0x80 else imm
            v, store = self.alu(reg, self.get(opd), imm)
            if store:
                self.put(opd, v)
        elif op == 0xF7:
            reg, opd = self.modrm()
            v = self.get(opd)
            if reg == 0:
                imm = self.fetchw(); self.flags(v & imm, False)
            elif reg == 3:
                r = (-v) & 0xFFFF; self.flags(r, v != 0, v == 0x8000); self.put(opd, r)
            elif reg == 6:
                if v == 0:
                    raise DivideFault
                n = self.r["dx"] << 16 | self.r["ax"]
                q, rem = divmod(n, v)
                if q > 0xFFFF:
                    raise DivideFault
                self.r["ax"], self.r["dx"] = q, rem
            else:
                raise NotImplementedError(f"F7 /{reg}")
        elif op == 0xD1:
            reg, opd = self.modrm()
            v = self.get(opd)
            if reg == 4:                                  # shl
                r = v << 1; self.flags(r & 0xFFFF, bool(r & 0x10000)); self.put(opd, r)
            elif reg == 5:                                # shr
                c = bool(v & 1); r = v >> 1; self.flags(r, c); self.put(opd, r)
            elif reg == 2:                                # rcl (CF and OF only)
                c = bool(v & 0x8000); self.put(opd, (v << 1 | self.cf) & 0xFFFF); self.cf = c
            else:
                raise NotImplementedError(f"D1 /{reg}")
        elif 0x40 <= op <= 0x47:
            reg = REGS[op - 0x40]; c = self.cf
            self.alu(0, self.r[reg], 1); self.cf = c; self.r[reg] = (self.r[reg] + 1) & 0xFFFF
        elif 0x50 <= op <= 0x57:
            self.push(self.r[REGS[op - 0x50]] if op != 0x54 else self.r["sp"])
        elif 0x58 <= op <= 0x5F:
            self.r[REGS[op - 0x58]] = self.pop()
        elif op == 0x0E:
            self.push(self.seg["cs"])
        elif 0xB8 <= op <= 0xBF:
            self.r[REGS[op - 0xB8]] = self.fetchw()
        elif op == 0x92:
            self.r["ax"], self.r["dx"] = self.r["dx"], self.r["ax"]
        elif 0x70 <= op <= 0x7F or op in (0xEB, 0xE2):
            d = self.fetch()
            d = d - 256 if d & 0x80 else d
            if op == 0xEB:
                take = True
            elif op == 0xE2:
                self.r["cx"] = (self.r["cx"] - 1) & 0xFFFF
                take = self.r["cx"] != 0
            else:
                take = {0x72: self.cf, 0x73: not self.cf, 0x74: self.zf, 0x75: not self.zf,
                        0x76: self.cf or self.zf, 0x77: not (self.cf or self.zf),
                        0x78: self.sf, 0x79: not self.sf}[op]
            if take:
                self.ip = (self.ip + d) & 0xFFFF
        elif op == 0xCA:
            n = self.fetchw()
            self.ip = self.pop(); self.seg["cs"] = self.pop()
            self.r["sp"] = (self.r["sp"] + n) & 0xFFFF
        elif op == 0xEA:
            ip = self.fetchw(); cs = self.fetchw()
            self.ip, self.seg["cs"] = ip, cs
        else:
            raise NotImplementedError(f"opcode {op:02X} at {self.seg['cs']:04X}:{(self.ip - 1) & 0xFFFF:04X}")


def memory() -> tuple[bytearray, bytes]:
    img = load_vailixi_linear()
    mem = bytearray(0x100000)
    mem[0xF8000:0x100000] = img[0x78000:0x80000]              # F800 BIOS page as the CPU sees it
    built = mod.assemble_cave(ROOT / "mods" / "s1a.asm", img, publish=False)
    base = CAVE_SEG << 4
    mem[base:base + len(built.code)] = built.code
    return mem, built


def call(mem: bytearray, cs: int, ip: int, a: int, b: int) -> dict:
    cpu = Cpu(bytearray(mem))
    cpu.r.update(sp=0xFF00, bp=0x1234, si=0x5678, di=0x9ABC, ax=0xAAAA, bx=0xBBBB, cx=0xCCCC, dx=0xDDDD)
    for w in (b >> 16, b & 0xFFFF, a >> 16, a & 0xFFFF):        # push divisor hi, lo, dividend hi, lo
        cpu.push(w)
    cpu.push(0x0000); cpu.push(0x0000)                         # return to 0000:0000
    cpu.seg["cs"], cpu.ip = cs, ip
    try:
        while not (cpu.seg["cs"] == 0 and cpu.ip == 0):
            cpu.step()
    except DivideFault:
        return {"fault": True}
    return {"fault": False, "q": cpu.r["dx"] << 16 | cpu.r["ax"], "sp": cpu.r["sp"],
            "keep": (cpu.r["bp"], cpu.r["si"], cpu.r["di"], cpu.seg["ds"], cpu.seg["es"])}


def operands():
    edge = [0, 1, 2, 9, 10, 0x1B9, 0x7FFF, 0x8000, 0xC671, 0xFFFF, 0x10000, 0x10001, 0x12345678,
            0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFF0000, 0xFFFF0001, 0xFFFFFFFF, 0xFFFFFFFE]
    for a in edge:
        for b in edge:
            yield a, b
    rng = random.Random(350)
    for _ in range(3000):
        a = rng.getrandbits(32)
        b = rng.choice((rng.getrandbits(16), rng.getrandbits(32), rng.randrange(1, 0x200),
                        (-rng.randrange(1, 0x10000)) & 0xFFFFFFFF))
        yield a, b


class S1aDivide(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mem, cls.cave = memory()

    def test_cave_matches_the_runtime_on_every_case(self) -> None:
        for callee, label in ((0x20FA, "s1a_idiv"), (0x2101, "s1a_udiv")):
            fast = 0
            for a, b in operands():
                want = call(self.mem, 0xF800, callee, a, b)
                got = call(self.mem, CAVE_SEG, self.cave.labels[label], a, b)
                self.assertEqual(got, want, (label, hex(a), hex(b)))
                fast += (b >> 16) == 0 and b != 0
            self.assertGreater(fast, 1000, label)

    def test_fast_path_does_not_reach_the_runtime(self) -> None:
        """A 16-bit divisor never falls back: the cave alone returns (no F800 fetch)."""
        mem = bytearray(self.mem)
        mem[0xF8000:0x100000] = b"\xCC" * 0x8000               # INT 3 everywhere in F800
        for label in ("s1a_idiv", "s1a_udiv"):
            for a, b in ((0x319C0000, 0xC671), (0xFFFFF000, 0x1000), (0x14000, 10), (5, 1)):
                r = call(mem, CAVE_SEG, self.cave.labels[label], a, b)
                self.assertFalse(r["fault"])

    def test_only_the_seventeen_call_sites_change(self) -> None:
        args = mod.read_args(ROOT / "mods" / "S1A.args")
        stock = bytearray(load_vailixi_linear())
        patched = bytearray(stock)
        code, labels = mod.cave(args.cave, stock, out=ROOT / "build" / "mods")
        resolved = [(o, old, mod.far(new, labels).lower()) for o, old, new in args.patch]
        mod.apply(patched, resolved + [code])
        diff = [i for i in range(0x30000, 0x74000) if stock[i] != patched[i]]
        cave_range = range(mod.CAVE[0], mod.CAVE[0] + len(bytes.fromhex(code[2])))
        sites = {o for o, _, _ in resolved}
        self.assertEqual(len(sites), 17)
        for i in diff:
            self.assertTrue(i in cave_range or any(s <= i < s + 5 for s in sites), hex(i))
        for o in sites:
            self.assertTrue(0x4FFFE <= o < 0x50785)
            self.assertEqual(patched[o], 0x9A)
            off, seg = struct.unpack_from("<HH", patched, o + 1)
            self.assertEqual(seg, CAVE_SEG)
            self.assertIn(off, (labels["s1a_idiv"], labels["s1a_udiv"]))
        body = patched[0x4FFFE:0x50785]
        for old in (bytes.fromhex("9afa2000f8"), bytes.fromhex("9a012100f8")):
            self.assertNotIn(old, body)

    def test_cave_far_targets_are_the_runtime_entries(self) -> None:
        targets = {t.target for t in mod.far_transfers(self.cave)}
        self.assertEqual(targets, {"F800:20FA", "F800:2101"})


if __name__ == "__main__":
    unittest.main()
