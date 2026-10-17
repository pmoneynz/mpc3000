#!/usr/bin/env python3
"""Who can enter the 3.16 SCSI partition reader 2AB2:04F7?  Static reachability.

    python3 tools/scsi_reader_reach.py [build/mods/WAVE316.SYS build/mods/wave316.cave.map]

Evidence for mods/scsistack316.inc and notes/port_316.md "SCSI reader stack".
Memory is the PMONEY load image as stored (relative segments) with the copied
cave at its home paragraph 7E00, so cave hooks are followed like 3.16 code.
Recursive descent from every root:

* the eight AMX tasks of the static create table (image 0x4834C, 18-byte
  records, FFFFh-terminated at 0x483DC);
* every interrupt handler 3.16 or the cave installs (VECTORS: five AMX
  vector installs CALLF 47BF:0341, three direct IVT stores, 3.16's own BIOS
  segment 0009 vectors), which also resolves INT n inside the walk;
* the C start-up 0000:0000 (which reaches main, the UI task's code).

The walk enters near and far calls, near jump tables (bounded by their CMP or
by hand in TABLES/TARGETS) and INT n.  The AMX kernel (segment 47BF) is not
entered: it has no far or indirect transfer (kernel_transfers() checks), so
it returns only to saved contexts.  The reader chain is the five entries
STOPS.  An indirect transfer the walk cannot bound is reported as unresolved.
The one far indirect left outside the UI task, CALL FAR [79A0] in INT 40
(2A53:003C), is the EPROM's own INT 40 vector (saved at 2A53 install, image
0x2A645), BIOS ROM code that holds no 3.16 address.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import route_c as rc  # noqa: E402
from tools.v53_decode import decode_one  # noqa: E402

CODE_END = 0x609C0                  # 3.16 code and far data lie below DGROUP
CAVE_HOME = 0x7E00
KERNEL = 0x47BF
KERNEL_END = 0x75C                  # 47BF:0000..075B; the create table follows at image 0x4834C
TASK_TABLE, TASKS = 0x4834C, 8
UI_TASK = 7
STOPS = {(0x2033, 0x000C): "INT 41 service (function 0: media check)",
         (0x2AB2, 0x0767): "media check -> reader", (0x2AB2, 0x03A5): "scan (mount)",
         (0x2AB2, 0x04F7): "partition reader", (0x2AB2, 0x04FE): "reader body"}

VECTORS = {   # INT n -> every handler 3.16 installs for it
    0x08: [(0x0009, 0x1942), (0x2B50, 0x000C)], 0x09: [(0x2C45, 0x000C), (0x2CCC, 0x0000)],
    0x0B: [(0x3E16, 0x0309)], 0x0C: [(0x2C08, 0x000E)], 0x0D: [(0x2B6D, 0x006B)],
    0x0E: [(0x2C1F, 0x0000)], 0x0F: [(0x0009, 0x194E)], 0x40: [(0x2A53, 0x0024)],
    0x41: [(0x0009, 0x0360)], 0x42: [(0x0009, 0x194E)], 0x43: [(0x0009, 0x16A6)],
    0x45: [(0x0009, 0x013F)], 0x46: [(0x0009, 0x18D2)],
}
# AMX vector installs (MOV AX,seg / MOV ES,AX / MOV BX,off / MOV DL,vec / CALLF 47BF:0341)
# and direct IVT stores found in the image (vector_installs() re-finds them).
AMX_INSTALLS = {(0x2B50, 0x000C, 0x08), (0x2C08, 0x000E, 0x0C), (0x2B6D, 0x006B, 0x0D),
                (0x2C1F, 0x0000, 0x0E), (0x2C45, 0x000C, 0x09),
                (0x4852, 0x0053, 0x08)}      # OS reload 4858:0000, dead (returns at once: 7DFA-7DF9 = 1)
DIRECT_INSTALLS = {0x2A645: 0x40, 0x2CE57: 0x09, 0x3E48C: 0x0B}   # image offset of the IVT read -> vector

# Near dispatch sites the CMP heuristic does not bound, bounded by hand from the
# code before each (site: (table segment, table offset, entries)).
TABLES = {
    (0x0009, 0x16C4): (0x0009, 0x16D0, 8),     # INT 43: CMP SI,8 / JNC, CALL CS:[SI*2+16D0]
    (0x0009, 0x03CB): (0x0009, 0x03D4, 16),    # INT 41: CMP SI,10h / JC, CALL CS:[SI*2+3D4]
    (0x2A53, 0x0057): (0x2A53, 0x0004, 16),    # INT 40: AND AX,0Fh / SHL, CALL CS:[SI+4]
    (0x2B50, 0x00BC): (0x2B50, 0x0163, 11),    # IRQ 8: index < 0Bh (byte table 158..162 in front)
    (0x2B50, 0x0120): (0x2B50, 0x0184, 11),    # IRQ 8: byte table 179..183 in front
    (0x2C45, 0x0469): (0x2C45, 0x046E, 7),     # tick ISR: 6 code offsets, one more read as margin
    (0x32C6, 0x0055): (0x32C6, 0x005A, 6),     # SUB BL,55h / CMP BL,6 / JC
    (0x3314, 0x0480): (0x3314, 0x0460, 12),    # CMP AX,0Ch / JNC
    (0x2B6D, 0x0529): (0x2B6D, 0x052E, 8),     # (AL>>3)&0Eh
    (0x2B6D, 0x0550): (0x2B6D, 0x0555, 16),    # (AX&0Fh)*2
    (0x2C1F, 0x005A): (0x2C1F, 0x0026, 11),    # state byte [D4E4]; table ends where code starts
    (0x31F8, 0x0022): (0x31F8, 0x0027, 11),    # the same state byte and table shape
    (0x2A66, 0x019B): (0x2A66, 0x023A, 8),     # (AL&7)*2
}
TARGETS = {   # dispatches with explicit target lists
    (0x0009, 0x1762): [(0x0009, o) for o in (0x177A, 0x1787, 0x179A, 0x17A6, 0x17C4)],  # key table 176A, 0-terminated
    (0x0009, 0x1351): [(0x0009, 0x1394), (0x0009, 0x138C)],                              # MOV DI,1394h / 138Ch
}
EPROM_INT40 = ("CALLF_RM", "2A53:003C")
INIT = ((0x0009, 0x0006), (0x0009, 0x1AD0))      # the third initialiser is the AMX kernel 47BF:0006


class Program:
    def __init__(self, sys_bytes: bytes, cave_copy_end: int):
        mz = rc.MZ.parse(sys_bytes)
        img = bytes(mz.image)
        self.img = img
        self.mem = bytearray(0x100000)
        self.mem[:len(img)] = img
        stage = mz.h["cs"]
        self.mem[CAVE_HOME * 16:CAVE_HOME * 16 + cave_copy_end] = img[stage * 16:stage * 16 + cave_copy_end]
        self.cave = (CAVE_HOME * 16, CAVE_HOME * 16 + cave_copy_end)

    def dec(self, c: int, i: int):
        ins = decode_one(bytes(self.mem[c * 16:c * 16 + 0x10010]), 0, i)
        tcs = c if ins.kind in ("JMPS", "JMPN", "CALLN", "JCC") else ins.target_cs
        return ins, tcs

    def word(self, a: int) -> int:
        return struct.unpack_from("<H", self.mem, a)[0]

    def tasks(self) -> list[tuple[int, int, int, int, int]]:
        out = []
        for k in range(TASKS):
            ip, cs, sp, ss = struct.unpack_from("<4H", self.img, TASK_TABLE + 18 * k)
            out.append((k, cs, ip, ss, sp))
        if struct.unpack_from("<2H", self.img, TASK_TABLE + 18 * TASKS) != (0xFFFF, 0xFFFF):
            raise ValueError("the AMX create table is not 8 records and an FFFFh end")
        return out

    def _table(self, c: int, i: int, raw: bytes):
        if (c, i) in TARGETS:
            return TARGETS[(c, i)]
        if (c, i) in TABLES:
            tc, to, n = TABLES[(c, i)]
            return [(tc, self.word(tc * 16 + to + 2 * j)) for j in range(n)]
        if raw == b"\xff\xe3" and c == 0x2B6D:      # IRQ 0D: JMP BX state machine
            base = 0x2B6D * 16                      # every MOV BX,imm16 in the segment (over-approximation)
            return [(0x2B6D, self.word(a + 1)) for a in range(base, base + 0xC00)
                    if self.mem[a] == 0xBB and 0x100 <= self.word(a + 1) < 0xC00]
        if raw[:3] != b"\x2e\xff\xa7":
            return None
        disp = raw[3] | raw[4] << 8
        back = bytes(self.mem[c * 16 + i - 12:c * 16 + i])
        for k in range(len(back) - 1, -1, -1):      # CMP BX,n / Jcc right before
            if back[k:k + 2] == b"\x83\xfb" and k + 4 <= len(back):
                n = {0x72: back[k + 2], 0x77: back[k + 2] + 1, 0x76: back[k + 2] + 1}.get(back[k + 3])
                return None if n is None else [(c, self.word(c * 16 + disp + 2 * j)) for j in range(n)]
        return None

    def reach(self, roots, stops=STOPS):
        seen, work, hits, unresolved = set(), list(roots), {}, set()
        while work:
            c, i = work.pop()
            lin = (c * 16 + i) & 0xFFFFF
            if (c, i) in stops:
                hits[(c, i)] = hits.get((c, i), 0) + 1
                continue
            if lin in seen or c == KERNEL:
                continue
            if not (lin < CODE_END or self.cave[0] <= lin < self.cave[1]):
                unresolved.add(("outside", f"{c:04X}:{i:04X}"))
                continue
            seen.add(lin)
            ins, tcs = self.dec(c, i)
            k, raw = ins.kind, bytes.fromhex(ins.bytes_hex)
            nxt = (c, (i + ins.length) & 0xFFFF)
            if k in ("RET", "RETF", "IRET", "RETN", "RETFN") or raw[:1] == b"\xf4":
                continue
            if k in ("JMPN_RM", "CALLN_RM"):
                t = self._table(c, i, raw)
                if t is None:
                    unresolved.add((k, f"{c:04X}:{i:04X}"))
                else:
                    work += t
                if k == "CALLN_RM":
                    work.append(nxt)
                continue
            if k in ("JMPF_RM", "CALLF_RM"):
                unresolved.add((k, f"{c:04X}:{i:04X}"))
                if k == "CALLF_RM":
                    work.append(nxt)
                continue
            if k in ("UNKNOWN_0F", "BRKXA", "RETXA"):
                unresolved.add((k, f"{c:04X}:{i:04X}"))
                continue
            if k in ("JMPF", "JMPS", "JMPN"):
                work.append((tcs, ins.target_ip))
                continue
            if k == "JCC":
                work += [nxt, (tcs, ins.target_ip)]
                continue
            if k in ("CALLN", "CALLF"):
                work += [(tcs, ins.target_ip), nxt]
                continue
            if raw[:1] == b"\xcd":
                if raw[1] in VECTORS:
                    work += VECTORS[raw[1]]
                else:
                    unresolved.add(("INT", f"{c:04X}:{i:04X}"))
            work.append(nxt)
        return seen, hits, unresolved

    def kernel_transfers(self) -> list[str]:
        """Far, indirect and INT transfers in the AMX kernel 47BF:0000..075B (none expected)."""
        out, i = [], 0
        while i < KERNEL_END:
            ins, _ = self.dec(KERNEL, i)
            raw = bytes.fromhex(ins.bytes_hex)
            if ins.kind in ("CALLF", "JMPF", "CALLF_RM", "JMPF_RM", "CALLN_RM", "JMPN_RM") or raw[:1] == b"\xcd":
                out.append(f"47BF:{i:04X} {ins.bytes_hex}")
            i += ins.length
        return out

    def vector_installs(self) -> tuple[set, dict]:
        amx = set()
        for m in re.finditer(rb"\xb8(..)\x8e\xc0\xbb(..)\xb2(.)\x9a\x41\x03\xbf\x47", self.img[:CODE_END], re.S):
            amx.add((struct.unpack("<H", m[1])[0], struct.unpack("<H", m[2])[0], m[3][0]))
        direct = {}    # MOV AX,ES:[vec*4] after ES = 0: saved-and-replaced vectors
        for m in re.finditer(rb"(?:\x33\xc0|\x2b\xc0|\xb8\x00\x00)\x8e\xc0", self.img[:CODE_END]):
            tail = self.img[m.end():m.end() + 24]
            v = re.search(rb"\x26\xa1(..)|\xbb(..)\x9c\xfa\x26\x8b\x07", tail, re.S)
            if v and (b"\xa3" in tail or b"\x26\x89" in tail or b"\x26\xc7" in tail):
                off = struct.unpack("<H", v[1] or v[2])[0]
                if off % 4 == 0 and off < 0x400 and m.start() not in (0x2A55D,):   # 2A55D only reads IVT[3F]
                    direct[m.end() + v.start()] = off // 4
        return amx, direct


def analyse(sys_bytes: bytes, cave_copy_end: int) -> dict:
    p = Program(sys_bytes, cave_copy_end)
    res = {"kernel_transfers": p.kernel_transfers(), "roots": {}}
    roots = {f"task{k} {cs:04X}:{ip:04X} SS {ss:04X}": [(cs, ip)] for k, cs, ip, ss, sp in p.tasks()}
    roots.update({f"INT {v:02X}": hs for v, hs in VECTORS.items()})
    roots["start-up 0000:0000"] = [(0, 0)]
    for seg, off in INIT:                         # start-up initialisers (6098:0004..0016), pre-kernel
        roots[f"init {seg:04X}:{off:04X}"] = [(seg, off)]
    for name, r in roots.items():
        seen, hits, unres = p.reach(r)
        res["roots"][name] = {"insns": len(seen), "hits": sorted(f"{c:04X}:{i:04X}" for c, i in hits),
                              "unresolved": sorted(unres)}
    body = {k: v for k, v in STOPS.items() if k != (0x2AB2, 0x04FE)}
    seen, hits, unres = p.reach([(0x2AB2, 0x04FE)], body)
    res["reader_body"] = {"insns": len(seen), "hits": sorted(f"{c:04X}:{i:04X}" for c, i in hits),
                          "unresolved": sorted(unres)}
    res["installs"] = p.vector_installs()
    return res


if __name__ == "__main__":
    out = ROOT / "build" / "mods"
    sys_path = Path(sys.argv[1]) if len(sys.argv) > 1 else out / "WAVE316.SYS"
    map_path = Path(sys.argv[2]) if len(sys.argv) > 2 else out / "wave316.cave.map"
    sym = {m[3]: int(m[1], 16) for m in re.finditer(r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)$",
                                                   map_path.read_text(), re.M)}
    r = analyse(sys_path.read_bytes(), sym["cave_copy_end"])
    print("kernel far/indirect transfers:", r["kernel_transfers"] or "none")
    for name, v in r["roots"].items():
        print(f"{name:32s} insns {v['insns']:6d} reader chain {v['hits'] or '-'} unresolved {v['unresolved'] or '-'}")
    print("reader body", r["reader_body"])
    print("installs", r["installs"])
