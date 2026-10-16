"""A small real-mode 8086/80186 interpreter for differential tests of cave code.

It runs stock 3.16 bytes and cave bytes side by side on the same memory image
(tests/test_perf316_diff.py).  It implements the integer instruction set the
compared routines use, 16-bit addressing, segment overrides, REP prefixes,
string instructions, INT/IRET and port I/O through callbacks; anything else
raises NotImplementedError, so an untested instruction cannot slip through.
Flags: CF PF AF ZF SF TF IF DF OF; PUSHF stores them with bits 1 and 12-15 set.
It models no timing and no interrupts.  BRKXA/RETXA (0F E0 / 0F F0) are
rejected; 3.16 and the cave contain none.
"""
from __future__ import annotations

REG16 = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
SREG = ("es", "cs", "ss", "ds")
FLAGBITS = {"cf": 0, "pf": 2, "af": 4, "zf": 6, "sf": 7, "tf": 8, "if": 9, "df": 10, "of": 11}


class Halt(Exception):
    pass


def _parity(v: int) -> bool:
    return bin(v & 0xFF).count("1") % 2 == 0


class Cpu:
    def __init__(self, mem: bytearray, *, port_in=None, port_out=None):
        self.m = mem
        self.r = dict.fromkeys(REG16, 0)
        self.s = dict.fromkeys(SREG, 0)
        self.ip = 0
        self.f = dict.fromkeys(FLAGBITS, False)
        self.port_in = port_in or (lambda port, width: 0xFF)
        self.port_out = port_out or (lambda port, value, width: None)
        self.steps = 0
        self.max_steps = 5_000_000
        self.writes: set[int] = set()

    # ------------------------------------------------------------ registers
    def r8(self, i):
        reg = REG16[i & 3]
        return (self.r[reg] >> 8) & 0xFF if i & 4 else self.r[reg] & 0xFF

    def w8(self, i, v):
        reg = REG16[i & 3]
        if i & 4:
            self.r[reg] = (self.r[reg] & 0x00FF) | ((v & 0xFF) << 8)
        else:
            self.r[reg] = (self.r[reg] & 0xFF00) | (v & 0xFF)

    @property
    def flags(self) -> int:
        v = 0xF002
        for k, b in FLAGBITS.items():
            if self.f[k]:
                v |= 1 << b
        return v

    @flags.setter
    def flags(self, v: int) -> None:
        for k, b in FLAGBITS.items():
            self.f[k] = bool(v >> b & 1)

    # ------------------------------------------------------------ memory
    def lin(self, seg, off):
        return ((self.s[seg] << 4) + (off & 0xFFFF)) & 0xFFFFF

    def rb(self, seg, off):
        return self.m[self.lin(seg, off)]

    def rw(self, seg, off):
        return self.rb(seg, off) | self.rb(seg, off + 1) << 8

    def wb(self, seg, off, v):
        a = self.lin(seg, off)
        self.m[a] = v & 0xFF
        self.writes.add(a)

    def ww(self, seg, off, v):
        self.wb(seg, off, v)
        self.wb(seg, off + 1, v >> 8)

    def fetch(self):
        b = self.m[self.lin("cs", self.ip)]
        self.ip = (self.ip + 1) & 0xFFFF
        return b

    def fetchw(self):
        return self.fetch() | self.fetch() << 8

    def fetchs(self):
        b = self.fetch()
        return b - 256 if b & 0x80 else b

    def push(self, v):
        self.r["sp"] = (self.r["sp"] - 2) & 0xFFFF
        self.ww("ss", self.r["sp"], v)

    def pop(self):
        v = self.rw("ss", self.r["sp"])
        self.r["sp"] = (self.r["sp"] + 2) & 0xFFFF
        return v

    # ------------------------------------------------------------ operands
    def modrm(self, seg_override):
        b = self.fetch()
        mod, reg, rm = b >> 6, (b >> 3) & 7, b & 7
        if mod == 3:
            return reg, ("r", rm)
        r = self.r
        base = {0: r["bx"] + r["si"], 1: r["bx"] + r["di"], 2: r["bp"] + r["si"], 3: r["bp"] + r["di"],
                4: r["si"], 5: r["di"], 6: r["bp"], 7: r["bx"]}[rm]
        seg = "ss" if rm in (2, 3, 6) else "ds"
        if mod == 0 and rm == 6:
            base, seg = self.fetchw(), "ds"
        elif mod == 1:
            base += self.fetchs()
        elif mod == 2:
            base += self.fetchw()
        return reg, ("m", seg_override or seg, base & 0xFFFF)

    def get(self, opd, w):
        if opd[0] == "r":
            return self.r[REG16[opd[1]]] if w else self.r8(opd[1])
        return self.rw(opd[1], opd[2]) if w else self.rb(opd[1], opd[2])

    def put(self, opd, v, w):
        if opd[0] == "r":
            if w:
                self.r[REG16[opd[1]]] = v & 0xFFFF
            else:
                self.w8(opd[1], v)
        elif w:
            self.ww(opd[1], opd[2], v)
        else:
            self.wb(opd[1], opd[2], v)

    # ------------------------------------------------------------ arithmetic
    def szp(self, res, w):
        mask = 0xFFFF if w else 0xFF
        res &= mask
        self.f["zf"] = res == 0
        self.f["sf"] = bool(res & (0x8000 if w else 0x80))
        self.f["pf"] = _parity(res)
        return res

    def alu(self, op, a, b, w):
        """0 add 1 or 2 adc 3 sbb 4 and 5 sub 6 xor 7 cmp -> (result, store)."""
        mask, top = (0xFFFF, 0x8000) if w else (0xFF, 0x80)
        if op in (1, 4, 6):
            r = {1: a | b, 4: a & b, 6: a ^ b}[op]
            self.f["cf"] = self.f["of"] = False
            self.f["af"] = False
            return self.szp(r, w), True
        if op in (0, 2):
            c = 1 if (op == 2 and self.f["cf"]) else 0
            r = a + b + c
            self.f["cf"] = r > mask
            self.f["of"] = bool(~(a ^ b) & (a ^ r) & top)
        else:
            c = 1 if (op == 3 and self.f["cf"]) else 0
            r = a - b - c
            self.f["cf"] = r < 0
            self.f["of"] = bool((a ^ b) & (a ^ r) & top)
        self.f["af"] = bool((a ^ b ^ r) & 0x10)
        return self.szp(r, w), op != 7

    def incdec(self, v, w, dec):
        mask, top = (0xFFFF, 0x8000) if w else (0xFF, 0x80)
        r = (v - 1 if dec else v + 1) & mask
        self.f["of"] = r == (top - 1 if dec else top)
        self.f["af"] = bool((v ^ r) & 0x10)
        return self.szp(r, w)

    def shift(self, op, v, n, w):
        bits = 16 if w else 8
        mask, top = (1 << bits) - 1, 1 << (bits - 1)
        n &= 0x1F
        if n == 0:
            return v
        for _ in range(n):
            if op == 0:                                   # rol
                c = bool(v & top); v = ((v << 1) | c) & mask; self.f["cf"] = c
            elif op == 1:                                 # ror
                c = bool(v & 1); v = (v >> 1) | (c << (bits - 1)); self.f["cf"] = c
            elif op == 2:                                 # rcl
                c = bool(v & top); v = ((v << 1) | self.f["cf"]) & mask; self.f["cf"] = c
            elif op == 3:                                 # rcr
                c = bool(v & 1); v = (v >> 1) | (self.f["cf"] << (bits - 1)); self.f["cf"] = c
            elif op in (4, 6):                            # shl
                self.f["cf"] = bool(v & top); v = (v << 1) & mask
            elif op == 5:                                 # shr
                self.f["cf"] = bool(v & 1); v >>= 1
            elif op == 7:                                 # sar
                self.f["cf"] = bool(v & 1); v = (v >> 1) | (v & top)
        if op in (0, 1, 2, 3):
            self.f["of"] = bool((v ^ (v << 1)) & top) if op in (0, 2) else bool((v ^ (v << 1)) & top)
        else:
            self.f["of"] = bool((v ^ (v >> 1)) & (top >> 1)) if op != 7 else False
            self.szp(v, w)
        return v

    # ------------------------------------------------------------ execution
    def run(self, until_halt=True):
        while True:
            self.step()

    def step(self):
        self.steps += 1
        if self.steps > self.max_steps:
            raise RuntimeError("step limit")
        seg_o, rep = None, None
        while True:
            op = self.fetch()
            if op in (0x26, 0x2E, 0x36, 0x3E):
                seg_o = {0x26: "es", 0x2E: "cs", 0x36: "ss", 0x3E: "ds"}[op]
            elif op in (0xF2, 0xF3):
                rep = op
            elif op == 0xF0:
                pass
            else:
                break
        r, f = self.r, self.f
        if op < 0x40 and op & 7 < 6 and op not in (0x26, 0x2E, 0x36, 0x3E):
            aop, form = op >> 3, op & 7
            w = form & 1
            if form < 4:
                reg, opd = self.modrm(seg_o)
                ro = ("r", reg)
                dst, src = (opd, ro) if form < 2 else (ro, opd)
                v, store = self.alu(aop, self.get(dst, w), self.get(src, w), w)
                if store:
                    self.put(dst, v, w)
            else:
                imm = self.fetchw() if w else self.fetch()
                acc = ("r", 0)
                v, store = self.alu(aop, self.get(acc, w), imm, w)
                if store:
                    self.put(acc, v, w)
            return
        if op in (0x06, 0x0E, 0x16, 0x1E):
            self.push(self.s[SREG[op >> 3]]); return
        if op in (0x07, 0x17, 0x1F):
            self.s[SREG[op >> 3]] = self.pop(); return
        if 0x40 <= op <= 0x4F:
            reg = REG16[op & 7]
            c = f["cf"]
            r[reg] = self.incdec(r[reg], 1, op >= 0x48)
            f["cf"] = c
            return
        if 0x50 <= op <= 0x57:
            self.push(r[REG16[op & 7]] if op != 0x54 else r["sp"]); return
        if 0x58 <= op <= 0x5F:
            r[REG16[op & 7]] = self.pop(); return
        if op == 0x60:
            sp = r["sp"]
            for reg in ("ax", "cx", "dx", "bx"):
                self.push(r[reg])
            self.push(sp)
            for reg in ("bp", "si", "di"):
                self.push(r[reg])
            return
        if op == 0x61:
            for reg in ("di", "si", "bp"):
                r[reg] = self.pop()
            self.pop()
            for reg in ("bx", "dx", "cx", "ax"):
                r[reg] = self.pop()
            return
        if op == 0x68:
            self.push(self.fetchw()); return
        if op == 0x6A:
            self.push(self.fetchs() & 0xFFFF); return
        if 0x70 <= op <= 0x7F:
            d = self.fetchs()
            if self.cond(op & 0xF):
                self.ip = (self.ip + d) & 0xFFFF
            return
        if op in (0x80, 0x81, 0x82, 0x83):
            w = op & 1
            reg, opd = self.modrm(seg_o)
            if op == 0x81:
                imm = self.fetchw()
            elif op == 0x83:
                imm = self.fetchs() & 0xFFFF
            else:
                imm = self.fetch()
            v, store = self.alu(reg, self.get(opd, w), imm, w)
            if store:
                self.put(opd, v, w)
            return
        if op in (0x84, 0x85):
            w = op & 1
            reg, opd = self.modrm(seg_o)
            self.alu(4, self.get(opd, w), self.get(("r", reg), w), w)
            return
        if op in (0x86, 0x87):
            w = op & 1
            reg, opd = self.modrm(seg_o)
            a, b = self.get(("r", reg), w), self.get(opd, w)
            self.put(("r", reg), b, w)
            self.put(opd, a, w)
            return
        if 0x88 <= op <= 0x8B:
            w = op & 1
            reg, opd = self.modrm(seg_o)
            if op & 2:
                self.put(("r", reg), self.get(opd, w), w)
            else:
                self.put(opd, self.get(("r", reg), w), w)
            return
        if op == 0x8C:
            reg, opd = self.modrm(seg_o)
            self.put(opd, self.s[SREG[reg & 3]], 1); return
        if op == 0x8D:
            reg, opd = self.modrm(None)
            r[REG16[reg]] = opd[2]; return
        if op == 0x8E:
            reg, opd = self.modrm(seg_o)
            self.s[SREG[reg & 3]] = self.get(opd, 1); return
        if op == 0x8F:
            reg, opd = self.modrm(seg_o)
            self.put(opd, self.pop(), 1); return
        if 0x90 <= op <= 0x97:
            reg = REG16[op & 7]
            r["ax"], r[reg] = r[reg], r["ax"]; return
        if op == 0x98:
            r["ax"] = (r["ax"] & 0xFF) | (0xFF00 if r["ax"] & 0x80 else 0); return
        if op == 0x99:
            r["dx"] = 0xFFFF if r["ax"] & 0x8000 else 0; return
        if op == 0x9A:
            off, seg = self.fetchw(), self.fetchw()
            self.push(self.s["cs"]); self.push(self.ip)
            self.s["cs"], self.ip = seg, off; return
        if op == 0x9C:
            self.push(self.flags); return
        if op == 0x9D:
            self.flags = self.pop(); return
        if op == 0x9E:
            v = r["ax"] >> 8
            for k in ("cf", "pf", "af", "zf", "sf"):
                f[k] = bool(v >> FLAGBITS[k] & 1)
            return
        if op == 0x9F:
            self.w8(4, self.flags & 0xFF); return
        if 0xA0 <= op <= 0xA3:
            w = op & 1
            off = self.fetchw()
            seg = seg_o or "ds"
            if op < 0xA2:
                self.put(("r", 0), self.rw(seg, off) if w else self.rb(seg, off), w)
            elif w:
                self.ww(seg, off, r["ax"])
            else:
                self.wb(seg, off, r["ax"])
            return
        if op in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF):
            self.string(op, seg_o, rep); return
        if op in (0xA8, 0xA9):
            w = op & 1
            imm = self.fetchw() if w else self.fetch()
            self.alu(4, self.get(("r", 0), w), imm, w); return
        if 0xB0 <= op <= 0xB7:
            self.w8(op & 7, self.fetch()); return
        if 0xB8 <= op <= 0xBF:
            r[REG16[op & 7]] = self.fetchw(); return
        if op in (0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3):
            w = op & 1
            reg, opd = self.modrm(seg_o)
            n = self.fetch() if op in (0xC0, 0xC1) else (1 if op in (0xD0, 0xD1) else r["cx"] & 0xFF)
            self.put(opd, self.shift(reg, self.get(opd, w), n, w), w); return
        if op in (0xC2, 0xC3):
            n = self.fetchw() if op == 0xC2 else 0
            self.ip = self.pop(); r["sp"] = (r["sp"] + n) & 0xFFFF; return
        if op in (0xC4, 0xC5):
            reg, opd = self.modrm(seg_o)
            r[REG16[reg]] = self.rw(opd[1], opd[2])
            self.s["es" if op == 0xC4 else "ds"] = self.rw(opd[1], opd[2] + 2); return
        if op in (0xC6, 0xC7):
            w = op & 1
            reg, opd = self.modrm(seg_o)
            self.put(opd, self.fetchw() if w else self.fetch(), w); return
        if op == 0xC9:
            r["sp"] = r["bp"]; r["bp"] = self.pop(); return
        if op in (0xCA, 0xCB):
            n = self.fetchw() if op == 0xCA else 0
            self.ip = self.pop(); self.s["cs"] = self.pop(); r["sp"] = (r["sp"] + n) & 0xFFFF; return
        if op == 0xCD:
            self.interrupt(self.fetch()); return
        if op == 0xCF:
            self.ip = self.pop(); self.s["cs"] = self.pop(); self.flags = self.pop(); return
        if op == 0xD7:
            seg = seg_o or "ds"
            self.w8(0, self.rb(seg, r["bx"] + (r["ax"] & 0xFF))); return
        if op in (0xE0, 0xE1, 0xE2, 0xE3):
            d = self.fetchs()
            if op == 0xE3:
                take = r["cx"] == 0
            else:
                r["cx"] = (r["cx"] - 1) & 0xFFFF
                take = r["cx"] != 0 and (op == 0xE2 or (op == 0xE1) == f["zf"])
            if take:
                self.ip = (self.ip + d) & 0xFFFF
            return
        if op in (0xE4, 0xE5, 0xEC, 0xED):
            port = self.fetch() if op < 0xEC else r["dx"]
            w = op & 1
            self.put(("r", 0), self.port_in(port, w), w); return
        if op in (0xE6, 0xE7, 0xEE, 0xEF):
            port = self.fetch() if op < 0xEE else r["dx"]
            w = op & 1
            self.port_out(port, r["ax"] if w else r["ax"] & 0xFF, w); return
        if op == 0xE8:
            d = self.fetchw()
            self.push(self.ip); self.ip = (self.ip + d) & 0xFFFF; return
        if op == 0xE9:
            d = self.fetchw(); self.ip = (self.ip + d) & 0xFFFF; return
        if op == 0xEA:
            off, seg = self.fetchw(), self.fetchw()
            self.s["cs"], self.ip = seg, off; return
        if op == 0xEB:
            d = self.fetchs(); self.ip = (self.ip + d) & 0xFFFF; return
        if op == 0xF4:
            raise Halt
        if op == 0xF5:
            f["cf"] = not f["cf"]; return
        if op in (0xF6, 0xF7):
            self.group3(op & 1, seg_o); return
        if op in (0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD):
            k, v = {0xF8: ("cf", False), 0xF9: ("cf", True), 0xFA: ("if", False), 0xFB: ("if", True),
                    0xFC: ("df", False), 0xFD: ("df", True)}[op]
            f[k] = v; return
        if op in (0xFE, 0xFF):
            w = op & 1
            reg, opd = self.modrm(seg_o)
            if reg in (0, 1):
                c = f["cf"]
                self.put(opd, self.incdec(self.get(opd, w), w, reg == 1), w)
                f["cf"] = c
            elif w and reg == 2:
                t = self.get(opd, 1); self.push(self.ip); self.ip = t
            elif w and reg == 3:
                off, seg = self.rw(opd[1], opd[2]), self.rw(opd[1], opd[2] + 2)
                self.push(self.s["cs"]); self.push(self.ip); self.s["cs"], self.ip = seg, off
            elif w and reg == 4:
                self.ip = self.get(opd, 1)
            elif w and reg == 5:
                self.ip, self.s["cs"] = self.rw(opd[1], opd[2]), self.rw(opd[1], opd[2] + 2)
            elif w and reg == 6:
                self.push(self.get(opd, 1))
            else:
                raise NotImplementedError(f"FE/FF /{reg}")
            return
        raise NotImplementedError(f"opcode {op:02X} at {self.s['cs']:04X}:{(self.ip - 1) & 0xFFFF:04X}")

    def cond(self, c):
        f = self.f
        t = {0: f["of"], 1: not f["of"], 2: f["cf"], 3: not f["cf"], 4: f["zf"], 5: not f["zf"],
             6: f["cf"] or f["zf"], 7: not (f["cf"] or f["zf"]), 8: f["sf"], 9: not f["sf"],
             10: f["pf"], 11: not f["pf"], 12: f["sf"] != f["of"], 13: f["sf"] == f["of"],
             14: f["zf"] or (f["sf"] != f["of"]), 15: not f["zf"] and (f["sf"] == f["of"])}
        return t[c]

    def interrupt(self, n):
        self.push(self.flags); self.push(self.s["cs"]); self.push(self.ip)
        self.f["if"] = self.f["tf"] = False
        self.ip = self.m[n * 4] | self.m[n * 4 + 1] << 8
        self.s["cs"] = self.m[n * 4 + 2] | self.m[n * 4 + 3] << 8

    def string(self, op, seg_o, rep):
        r, f = self.r, self.f
        w = op & 1
        size = 2 if w else 1
        step = -size if f["df"] else size
        src = seg_o or "ds"
        while True:
            if rep and r["cx"] == 0:
                return
            if op in (0xA4, 0xA5):
                v = self.rw(src, r["si"]) if w else self.rb(src, r["si"])
                (self.ww if w else self.wb)("es", r["di"], v)
                r["si"] = (r["si"] + step) & 0xFFFF; r["di"] = (r["di"] + step) & 0xFFFF
            elif op in (0xA6, 0xA7):
                a = self.rw(src, r["si"]) if w else self.rb(src, r["si"])
                b = self.rw("es", r["di"]) if w else self.rb("es", r["di"])
                self.alu(7, a, b, w)
                r["si"] = (r["si"] + step) & 0xFFFF; r["di"] = (r["di"] + step) & 0xFFFF
            elif op in (0xAA, 0xAB):
                (self.ww if w else self.wb)("es", r["di"], r["ax"] if w else r["ax"] & 0xFF)
                r["di"] = (r["di"] + step) & 0xFFFF
            elif op in (0xAC, 0xAD):
                self.put(("r", 0), self.rw(src, r["si"]) if w else self.rb(src, r["si"]), w)
                r["si"] = (r["si"] + step) & 0xFFFF
            elif op in (0xAE, 0xAF):
                b = self.rw("es", r["di"]) if w else self.rb("es", r["di"])
                self.alu(7, self.get(("r", 0), w), b, w)
                r["di"] = (r["di"] + step) & 0xFFFF
            if not rep:
                return
            r["cx"] = (r["cx"] - 1) & 0xFFFF
            if op in (0xA6, 0xA7, 0xAE, 0xAF):
                if rep == 0xF3 and not f["zf"]:
                    return
                if rep == 0xF2 and f["zf"]:
                    return

    def group3(self, w, seg_o):
        r, f = self.r, self.f
        reg, opd = self.modrm(seg_o)
        v = self.get(opd, w)
        mask = 0xFFFF if w else 0xFF
        bits = 16 if w else 8
        if reg == 0:
            imm = self.fetchw() if w else self.fetch()
            self.alu(4, v, imm, w)
        elif reg == 2:
            self.put(opd, ~v & mask, w)
        elif reg == 3:
            res, _ = self.alu(5, 0, v, w)
            self.put(opd, res, w)
            f["cf"] = v != 0
        elif reg in (4, 5):                               # mul, imul
            a = r["ax"] if w else r["ax"] & 0xFF
            if reg == 5:
                sa = a - (1 << bits) if a >> (bits - 1) else a
                sv = v - (1 << bits) if v >> (bits - 1) else v
                p = (sa * sv) & ((1 << 2 * bits) - 1)
                lo = p & mask
                slo = lo - (1 << bits) if lo >> (bits - 1) else lo
                f["cf"] = f["of"] = slo != sa * sv
            else:
                p = a * v
                f["cf"] = f["of"] = (p >> bits) != 0
            if w:
                r["ax"], r["dx"] = p & 0xFFFF, (p >> 16) & 0xFFFF
            else:
                r["ax"] = p & 0xFFFF
        elif reg in (6, 7):                               # div, idiv
            if v == 0:
                raise ZeroDivisionError("divide fault")
            if w:
                n = r["dx"] << 16 | r["ax"]
            else:
                n = r["ax"]
            if reg == 6:
                q, rem = divmod(n, v)
                if q > mask:
                    raise ZeroDivisionError("divide overflow")
            else:
                sn = n - (1 << 2 * bits) if n >> (2 * bits - 1) else n
                sv = v - (1 << bits) if v >> (bits - 1) else v
                q = abs(sn) // abs(sv)
                if (sn < 0) != (sv < 0):
                    q = -q
                rem = sn - q * sv
                if not -(1 << (bits - 1)) <= q < (1 << (bits - 1)):
                    raise ZeroDivisionError("divide overflow")
                q &= mask
                rem &= mask
            if w:
                r["ax"], r["dx"] = q, rem
            else:
                r["ax"] = (rem << 8) | q
        else:
            raise NotImplementedError(f"F6/F7 /{reg}")
