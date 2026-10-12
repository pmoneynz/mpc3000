#!/usr/bin/env python3
"""Turn emu.profile runs into the performance map.

Reads build/emu/prof/<workload>/{windows.json,prof_<i>.txt,cov_*.bin}
(fork `nec_prof` dumps), partitions executed ROM into routines (every call
target seen at run time, plus owner-ledger range starts and established
entries), and writes build/emu/prof/report.md and report.json:

  - per window: busy/idle split, interrupt vectors (count, mean cost, share),
    stack contexts (AMX task), top routines by self and inclusive cycles,
    top I/O ports, hottest basic blocks with ndisasm text;
  - ROM map: every ledger range and gap with executed / read / untouched byte
    counts over the union of all runs (dynamic coverage, not an all-paths claim).

    python3 tools/prof_report.py [--prof build/emu/prof] [--top 40]

Addresses: `phys` is the 24-bit physical address the profiler keyed on.  ROM
code runs from identity PGR frames, so file = phys & 0x7FFFF for phys <
0x100000 (the EPROM mirror); phys >= 0x300000 is work RAM.  CS:IP names come
from the ledger row that owns the routine's first byte (its `why` text), else
from the 20-bit form file + 0x80000.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.linear_rom import load_vailixi_linear  # noqa: E402
from tools.v53_decode import decode_one  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROF = REPO / "build" / "emu" / "prof"
LEDGER = REPO / "analysis" / "owner_ledger.json"
ENTRIES = REPO / "analysis" / "entry_scan.json"
CPU_HZ = 16_000_000

# AMX create-table stacks (notes/amx_create_table.md) and the kernel stacks
# (notes/amx_wait.md, irq_wrappers.md).  Keyed by SS.
STACKS = {0x912F: "AMX kernel stack (scheduler)", 0x9186: "task 0 (AMX timer walker)", 0x91C5: "task 1 (8010 walker)",
          0x91F7: "task 2 (sequencer playback)", 0x9267: "task 3 (pad/note)",
          0x92CB: "task 4 (wait worker)", 0x930A: "task 5", 0x9348: "task 6",
          0x9387: "task 7 (UI)", 0x901C: "ISR stack (FB00:0157)"}

# Known entries, by file offset (notes, and the disassembly in notes/performance.md).
# Everything else is named by CS:IP.
KNOWN = {0x7B23A: "AMX idle spin FB00:023A", 0x552A8: "ISR 08 D52A:0008 system tick 100 Hz",
         0x561AA: "ISR 09 D61A:000A sequencer tick", 0x554D7: "ISR 0D D547:0067 serial RX",
         0x55DDC: "ISR 0C D5DD:000C serial", 0x55F3E: "ISR 0E D5F3:000E",
         0x7B157: "AMX FB00:0157 ISR enter", 0x7B194: "AMX FB00:0194 ISR leave",
         0x7B1EA: "AMX FB00:01EA select", 0x7B537: "AMX FB00:0537 index->TCB",
         0x7B284: "AMX FB00:0284 create/resume frame", 0x7B4DC: "AMX FB00:04DC",
         0x7B725: "AMX FB00:0725 get message", 0x7B743: "AMX FB00:0743 queue header",
         0x7B6B9: "AMX FB00:06B9 enqueue", 0x7B6E8: "AMX FB00:06E8 dequeue",
         0x31B6B: "B1B1:005B put-string", 0x796AA: "BIOS INT 43 F800:16AA",
         0x79752: "BIOS INT 43 AX=4 char class walk F800:1752",
         0x7B4AC: "AMX FB00:04AC wake", 0x7B3B3: "AMX FB00:03B3 post",
         0x7B484: "AMX FB00:0484 timed wait", 0x6C050: "task 2 EC05:0000 playback",
         0x6C093: "task 2 EC05:0043 per-tick body", 0x300DF: "task 7 B000:00DF UI",
         0x56E1B: "task 7 D6E1:000B key-queue poll (idle)", 0x56E00: "task 7 D6E0:0000 blocking key wait (idle)",
         0x79F3E: "BIOS F9F3:000E floppy completion poll", 0x79D2C: "BIOS F9D2:000C floppy command + poll",
         0x5D8AE: "DD8A:000E event drain (CFB3:0008 per event)",
         0x58BDC: "D8BD:000C serial ring read", 0x58CCE: "D8CC:000E ring read (0x2B36)",
         0x58CEF: "D8CE:000F ring read", 0x58D15: "D8D1:0005 ring pop loop", 0x58D64: "D8D6:0004 ring read tail",
         0x7A114: "BIOS F800:2114 32-bit divide body", 0x7A0FA: "BIOS F800:20FA signed 32-bit divide",
         0x7A101: "BIOS F800:2101 unsigned 32-bit divide", 0x7A0C4: "BIOS F800:20C4 32x32 multiply",
         0x7A1A8: "BIOS F800:21A8 32-bit shift left",
         0x4F372: "CF37:0002 voice allocator", 0x4FC67: "CFC6:0007 note builder",
         0x4FFFE: "CFC6:039E note-on layer", 0x5078D: "CFC6:0B2D voice start",
         0x5695D: "D695:000D transport stop (tick ISR)", 0x5620E: "D620:000E tick ISR clock/UI kick",
         0x56487: "D648:0007 tick ISR tempo map + TCT1 reload", 0x5A69A: "DA69:000A tick ISR sync out",
         0x5A4C8: "DA4C:0008 bar.beat.tick advance", 0x5CF06: "DCF0:0006", 0x5A1AD: "DA1A:000D",
         0x5A9B2: "DA9B:0002", 0x32596: "task 1 B259:0006 8010 walker", 0x3095D: "B095:000D"}

# Idle: task 7 spins on the key queue count and [D6AB] (D6E1:000B, file 56E29-56E38),
# and the AMX empty-queue spin FB00:023A (never reached once task 7 exists).
# D6E0:0000 (file 56E08-56E0F) is the blocking variant (no [D6AB] test), used
# by modal prompts.  The BIOS floppy driver polls bit 15 of DS:[0] for the FDC
# completion that ISR 0B sets (F9D2:000C+48, F9F3:000E): that is a wait too.
IDLE = ((0x56E29, 0x56E39), (0x56E08, 0x56E10), (0x7B23A, 0x7B240), (0x79F3E, 0x79F54), (0x79D74, 0x79D7C))

# Exclusive partition of ROM by address, for the subsystem table.
REGIONS = (("UI key-queue poll (idle)", 0x56E29, 0x56E39), ("UI blocking key wait (idle)", 0x56E08, 0x56E10),
           ("BIOS floppy completion poll (wait)", 0x79F3E, 0x79F54), ("BIOS floppy completion poll 2 (wait)", 0x79D74, 0x79D7C),
           ("AMX kernel FB00-FB93", 0x7B000, 0x7BA01),
           ("BIOS F800 (LCD, INT 43/45/46)", 0x78000, 0x7A000), ("runtime FA0x-FA7x (math, timers)", 0x7A000, 0x7AC00),
           ("reset/XA FAC0", 0x7AC00, 0x7B000), ("app ROM B000-F07A", 0x30000, 0x74000))

CSIP = re.compile(r"\b([0-9A-F]{4}):([0-9A-F]{4})\b")


def file_of(phys: int) -> int | None:
    return phys & 0x7FFFF if phys < 0x100000 else None


@dataclass
class Window:
    workload: str
    label: str
    start: float
    end: float
    total: int = 0
    insns: int = 0
    halt: int = 0
    irq_entry: int = 0
    irqs: int = 0
    addr: dict[int, tuple[int, int]] = field(default_factory=dict)       # phys -> count, cycles
    edges: dict[tuple[int, int], int] = field(default_factory=dict)
    incl: dict[int, tuple[int, int]] = field(default_factory=dict)       # entry -> cycles, calls
    vec: dict[int, tuple[int, int, int]] = field(default_factory=dict)   # vector -> count, incl, self
    ss: dict[int, int] = field(default_factory=dict)
    io: dict[int, tuple[int, int]] = field(default_factory=dict)

    @property
    def seconds(self) -> float:
        return self.end - self.start


def parse(path: Path, workload: str, label: str, start: float, end: float) -> Window:
    w = Window(workload, label, start, end)
    for line in path.read_text().splitlines():
        if not line or line[0] == "#":
            continue
        k, *f = line.split()
        if k == "T":
            kv = dict(x.split("=") for x in f)
            w.total, w.insns, w.halt = int(kv["total"]), int(kv["insns"]), int(kv["halt"])
            w.irq_entry, w.irqs = int(kv["irq_entry"]), int(kv["irqs"])
        elif k == "A":
            w.addr[int(f[0], 16)] = (int(f[1]), int(f[2]))
        elif k == "E":
            w.edges[(int(f[0], 16), int(f[1], 16))] = int(f[2])
        elif k == "I":
            w.incl[int(f[0], 16)] = (int(f[1]), int(f[2]))
        elif k == "V":
            w.vec[int(f[0], 16)] = (int(f[1]), int(f[2]), int(f[3]))
        elif k == "S":
            w.ss[int(f[0], 16)] = int(f[1])
        elif k == "P":
            w.io[int(f[0], 16)] = (int(f[1]), int(f[2]))
    return w


def load_windows(prof: Path) -> list[Window]:
    out = []
    for index in sorted(prof.glob("*/windows.json")):
        meta = json.loads(index.read_text())
        for label, wi in meta["windows"].items():
            p = index.parent / wi["file"]
            if p.exists():
                out.append(parse(p, meta["workload"], label, wi["start"], wi["end"]))
    return out


# ---------------------------------------------------------------- routines

class Routines:
    """Partition of executed ROM into routines: entry = greatest known entry <= file."""

    def __init__(self, ledger: dict, entries: dict, windows: list[Window]):
        self.ranges = [(int(r["start"], 16), int(r["end"], 16), r) for r in ledger["ranges"]]
        self.ranges.sort()
        starts = set()
        self.names: dict[int, str] = dict(KNOWN)
        for s, e, r in self.ranges:
            if r["owner"] == "code":
                starts.add(s)
                m = CSIP.search(r.get("why", ""))
                if m and ((int(m[1], 16) << 4) + int(m[2], 16)) & 0x7FFFF == s and s not in self.names:
                    self.names[s] = f"{m[1]}:{m[2]}"
        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("cs_ip"), str) and CSIP.fullmatch(node["cs_ip"]):
                    yield node["cs_ip"]
                for v in node.values():
                    yield from walk(v)
            elif isinstance(node, list):
                for v in node:
                    yield from walk(v)
        for cs_ip in walk(entries):
            cs, ip = (int(x, 16) for x in cs_ip.split(":"))
            f = ((cs << 4) + ip) & 0x7FFFF
            starts.add(f)
            self.names.setdefault(f, cs_ip)
        for w in windows:
            for (_, t), _ in w.edges.items():
                if (f := file_of(t)) is not None:
                    starts.add(f)
            for e in w.incl:
                if (f := file_of(e)) is not None:
                    starts.add(f)
        self.starts = sorted(starts)
        self.cs_hint: list[tuple[int, int, int]] = []     # (start, end, CS) from ledger why
        for s, e, r in self.ranges:
            m = CSIP.search(r.get("why", ""))
            if m:
                cs = int(m[1], 16)
                if ((cs << 4) & 0x7FFFF) <= s < ((cs << 4) & 0x7FFFF) + 0x10000:
                    self.cs_hint.append((s, e, cs))

    def entry(self, f: int) -> int:
        import bisect
        i = bisect.bisect_right(self.starts, f) - 1
        if i < 0:
            return f
        e = self.starts[i]
        return e if f - e < 0x4000 else f

    def owner(self, f: int) -> dict | None:
        import bisect
        i = bisect.bisect_right(self.ranges, (f, 0xFFFFF, {})) - 1
        if i >= 0 and self.ranges[i][0] <= f < self.ranges[i][1]:
            return self.ranges[i][2]
        return None

    def csip(self, f: int) -> str:
        for s, e, cs in self.cs_hint:
            if s <= f < e:
                return f"{cs:04X}:{(f - ((cs << 4) & 0x7FFFF)) & 0xFFFF:04X}"
        return f"{(f + 0x80000) >> 4:04X}:{(f + 0x80000) & 0xF:04X}"

    def name(self, phys: int) -> str:
        f = file_of(phys)
        if f is None:
            return f"RAM@{phys:06X}"
        e = self.entry(f)
        base = self.names.get(e) or self.csip(e)
        return base if e == f else f"{base}+{f - e:X}"


# ---------------------------------------------------------------- analysis

def per_routine(w: Window, rt: Routines) -> dict[int, list]:
    """entry file -> [self cycles, insn count, inclusive cycles, calls]."""
    acc: dict[int, list] = defaultdict(lambda: [0, 0, 0, 0])
    for phys, (n, c) in w.addr.items():
        f = file_of(phys)
        key = rt.entry(f) if f is not None else phys
        acc[key][0] += c
        acc[key][1] += n
    for entry, (c, calls) in w.incl.items():
        f = file_of(entry)
        key = f if f is not None else entry
        acc[key][2] += c
        acc[key][3] += calls
    return acc


def idle_cycles(w: Window) -> int:
    return sum(c for phys, (_, c) in w.addr.items()
               if phys < 0x100000 and any(s <= (phys & 0x7FFFF) < e for s, e in IDLE))


def regions(w: Window) -> dict[str, tuple[int, int]]:
    """Cycles and instructions per exclusive address region."""
    acc = {name: [0, 0] for name, _, _ in REGIONS}
    acc["RAM / other"] = [0, 0]
    for phys, (n, c) in w.addr.items():
        f = file_of(phys)
        key = "RAM / other"
        if f is not None:
            for name, s, e in REGIONS:
                if s <= f < e:
                    key = name
                    break
        acc[key][0] += c
        acc[key][1] += n
    return {k: tuple(v) for k, v in acc.items()}


def disasm(image: bytes, file: int, length: int) -> list[tuple[int, str]]:
    """ndisasm text for [file, file+length); instruction bounds re-checked with decode_one."""
    data = image[file:file + length]
    try:
        out = subprocess.run(["ndisasm", "-b", "16", "-o", str(file), "-"], input=data,
                             capture_output=True, check=True).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        return [(file, data.hex())]
    rows = []
    for line in out.splitlines():
        m = re.match(r"^([0-9A-F]+)\s+([0-9A-F]+)\s+(.*)$", line.strip())
        if m:
            rows.append((int(m[1], 16), m[3].strip()))
    return rows


def hot_blocks(w: Window, image: bytes, rt: Routines, top: int) -> list[dict]:
    """Hottest basic blocks: maximal runs of consecutive executed instructions."""
    rom = sorted((phys & 0x7FFFF, n, c) for phys, (n, c) in w.addr.items() if phys < 0x100000)
    blocks, cur = [], None
    for f, n, c in rom:
        if cur and f == cur["next"] and n == cur["count"]:
            cur["cycles"] += c
            cur["end"] = f
        else:
            if cur:
                blocks.append(cur)
            cur = {"start": f, "end": f, "count": n, "cycles": c, "next": f}
        try:
            cur["next"] = f + decode_one(image, 0, f).length
        except Exception:
            cur["next"] = f + 1
    if cur:
        blocks.append(cur)
    blocks.sort(key=lambda b: -b["cycles"])
    out = []
    for b in blocks[:top]:
        length = b["next"] - b["start"]
        out.append({"start": b["start"], "length": length, "count": b["count"], "cycles": b["cycles"],
                    "routine": rt.name(b["start"] + 0x80000 if b["start"] >= 0x30000 else b["start"]),
                    "text": disasm(image, b["start"], length)})
    return out


# ---------------------------------------------------------------- coverage

def coverage(prof: Path) -> tuple[bytearray, bytearray, bytearray]:
    """Union of cov_fetch/read/write over every run, folded onto the 512 KiB file."""
    fetched, read, written = bytearray(0x80000), bytearray(0x80000), bytearray(0x80000)
    for d in prof.iterdir():
        for name, acc in (("cov_fetch.bin", fetched), ("cov_read.bin", read), ("cov_write.bin", written)):
            p = d / name
            if not p.exists():
                continue
            bits = p.read_bytes()
            for f in range(0x80000):
                for phys in (f, f + 0x80000):
                    if bits[phys >> 3] >> (phys & 7) & 1:
                        acc[f] = 1
                        break
    return fetched, read, written


def rom_map(rt: Routines, fetched: bytearray, read: bytearray) -> list[dict]:
    rows = []
    pos = 0
    for s, e, r in rt.ranges:
        if s > pos:
            rows.append({"start": pos, "end": s, "owner": "gap", "kind": "gap", "why": ""})
        rows.append({"start": s, "end": e, "owner": r["owner"], "kind": r.get("kind", r["owner"]),
                     "why": r.get("why", "")})
        pos = max(pos, e)
    if pos < 0x80000:
        rows.append({"start": pos, "end": 0x80000, "owner": "gap", "kind": "gap", "why": ""})
    for row in rows:
        s, e = row["start"], row["end"]
        row["bytes"] = e - s
        row["fetched"] = sum(fetched[s:e])
        row["read"] = sum(1 for i in range(s, e) if read[i] and not fetched[i])
        row["untouched"] = row["bytes"] - row["fetched"] - row["read"]
    return rows


# ---------------------------------------------------------------- report

def pct(a: float, b: float) -> str:
    return f"{100 * a / b:5.1f}%" if b else "   -  "


def report(windows: list[Window], rt: Routines, image: bytes, cov, top: int) -> tuple[str, dict]:
    md, js = [], {"windows": [], "rom_map": []}
    md.append("# Cycle profile report\n")
    md.append("Generated by tools/prof_report.py from emu.profile runs. CPU clock 16 MHz "
              "(NEC_CPU_DIV=2). One run per workload; each row is one execution, not an all-paths claim.\n")
    md.append("## Windows\n")
    md.append("| workload | window | s | cycles | insns | busy | idle+waits | IRQs/s | IRQ incl | ISR 09 seq tick | ISR 08 sys tick | ISR 0D serial |")
    md.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for w in windows:
        idle = idle_cycles(w)
        v = lambda n: w.vec.get(n, (0, 0, 0))[1]
        irq_incl = sum(x[1] for x in w.vec.values())
        md.append(f"| {w.workload} | {w.label} | {w.seconds:.1f} | {w.total} | {w.insns} | {pct(w.total - idle, w.total)} | "
                  f"{pct(idle, w.total)} | {w.irqs / w.seconds:.0f} | {pct(irq_incl, w.total)} | {pct(v(9), w.total)} | "
                  f"{pct(v(8), w.total)} | {pct(v(0xD), w.total)} |")
    md.append("")
    for w in windows:
        idle = idle_cycles(w)
        busy = w.total - idle
        rows = per_routine(w, rt)
        jw = {"workload": w.workload, "label": w.label, "start": w.start, "end": w.end, "total": w.total,
              "insns": w.insns, "idle": idle, "irqs": w.irqs, "irq_entry": w.irq_entry,
              "vectors": {f"{k:02X}": v for k, v in w.vec.items()},
              "stacks": {f"{k:04X}": v for k, v in w.ss.items()},
              "routines": [], "io": {f"{k:04X}": v for k, v in sorted(w.io.items())}}
        md.append(f"## {w.workload} / {w.label} ({w.start:g}-{w.end:g} s)\n")
        md.append(f"Total {w.total} cycles = {w.total / w.seconds / CPU_HZ * 100:.1f}% of {CPU_HZ // 1_000_000} MHz x "
                  f"{w.seconds:.1f} s; busy {busy} ({pct(busy, w.total).strip()}), idle spin {idle}; "
                  f"{w.insns} instructions, {w.total / max(1, w.insns):.2f} cycles/insn; {w.irqs} interrupts "
                  f"({w.irq_entry} entry cycles).\n")
        md.append("### Interrupt vectors\n")
        md.append("| vector | count | per s | mean incl | mean self | incl share | self share |")
        md.append("|---|--:|--:|--:|--:|--:|--:|")
        for vec, (n, incl, self_) in sorted(w.vec.items()):
            md.append(f"| {vec:02X} | {n} | {n / w.seconds:.1f} | {incl / max(1, n):.0f} | {self_ / max(1, n):.0f} | "
                      f"{pct(incl, w.total)} | {pct(self_, w.total)} |")
        md.append("\n### Stack contexts (exclusive; ISR time is inside the stack it ran on)\n")
        md.append("| SS | context | cycles | share |")
        md.append("|---|---|--:|--:|")
        for ss, c in sorted(w.ss.items(), key=lambda kv: -kv[1]):
            md.append(f"| {ss:04X} | {STACKS.get(ss, '?')} | {c} | {pct(c, w.total)} |")
        md.append("\n### Code regions (exclusive)\n")
        md.append("| region | cycles | share | insns |")
        md.append("|---|--:|--:|--:|")
        reg = regions(w)
        jw["regions"] = reg
        for name, (c, n) in sorted(reg.items(), key=lambda kv: -kv[1][0]):
            md.append(f"| {name} | {c} | {pct(c, w.total)} | {n} |")
        md.append(f"\n### Top {top} routines by self cycles\n")
        md.append("| routine | file | self | self % | insns | incl | calls | incl/call |")
        md.append("|---|---|--:|--:|--:|--:|--:|--:|")
        ordered = sorted(rows.items(), key=lambda kv: -kv[1][0])
        for entry, (s, n, incl, calls) in ordered[:top]:
            name = rt.names.get(entry) or (rt.csip(entry) if entry < 0x80000 else f"RAM@{entry:06X}")
            md.append(f"| {name} | {entry:05X} | {s} | {pct(s, w.total)} | {n} | {incl} | {calls} | "
                      f"{incl / calls:.0f} |" if calls else
                      f"| {name} | {entry:05X} | {s} | {pct(s, w.total)} | {n} | {incl} | {calls} | - |")
        for entry, (s, n, incl, calls) in ordered:
            jw["routines"].append({"entry": entry, "name": rt.names.get(entry) or (rt.csip(entry) if entry < 0x80000 else f"RAM@{entry:06X}"),
                                   "self": s, "insns": n, "incl": incl, "calls": calls})
        md.append(f"\n### Top {top} routines by inclusive cycles\n")
        md.append("| routine | file | incl | incl % | calls | incl/call | self |")
        md.append("|---|---|--:|--:|--:|--:|--:|")
        for entry, (s, n, incl, calls) in sorted(rows.items(), key=lambda kv: -kv[1][2])[:top]:
            name = rt.names.get(entry) or (rt.csip(entry) if entry < 0x80000 else f"RAM@{entry:06X}")
            md.append(f"| {name} | {entry:05X} | {incl} | {pct(incl, w.total)} | {calls} | "
                      f"{incl / max(1, calls):.0f} | {s} |")
        md.append("\n### I/O ports (accesses in window)\n")
        md.append("| port | reads | writes |")
        md.append("|---|--:|--:|")
        for port, (r, wr) in sorted(w.io.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:24]:
            md.append(f"| {port:04X} | {r} | {wr} |")
        md.append("\n### Hottest basic blocks\n")
        blocks = hot_blocks(w, image, rt, 12)
        jw["blocks"] = [{k: v for k, v in b.items() if k != "text"} for b in blocks]
        for b in blocks:
            md.append(f"**{b['routine']}** file {b['start']:05X}, {b['length']} bytes, executed {b['count']} times, "
                      f"{b['cycles']} cycles ({pct(b['cycles'], w.total).strip()}), "
                      f"{b['cycles'] / b['count']:.1f} cycles per pass\n")
            md.append("```")
            for off, text in b["text"]:
                md.append(f"{off:05X}  {text}")
            md.append("```\n")
        js["windows"].append(jw)

    fetched, read, _ = cov
    rows = rom_map(rt, fetched, read)
    js["rom_map"] = rows
    md.append("## ROM map (union of all runs)\n")
    tot = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        t = tot[(r["owner"], r["kind"])]
        t[0] += r["bytes"]; t[1] += r["fetched"]; t[2] += r["read"]; t[3] += r["untouched"]
    md.append("| owner | kind | bytes | fetched | read only | untouched |")
    md.append("|---|---|--:|--:|--:|--:|")
    for (o, k), t in sorted(tot.items()):
        md.append(f"| {o} | {k} | {t[0]} | {t[1]} | {t[2]} | {t[3]} |")
    md.append("\nLargest owned-code ranges with no fetch in any run (dead in these workloads, not proven dead):\n")
    md.append("| file | bytes | why |")
    md.append("|---|--:|---|")
    for r in sorted((r for r in rows if r["owner"] == "code" and r["fetched"] == 0), key=lambda r: -r["bytes"])[:25]:
        md.append(f"| {r['start']:05X}-{r['end']:05X} | {r['bytes']} | {r['why'][:70]} |")
    md.append("\nGaps (unowned) with any fetch (code the ledger has not opened yet):\n")
    md.append("| file | bytes | fetched | read |")
    md.append("|---|--:|--:|--:|")
    for r in sorted((r for r in rows if r["owner"] == "gap" and r["fetched"]), key=lambda r: -r["fetched"])[:25]:
        md.append(f"| {r['start']:05X}-{r['end']:05X} | {r['bytes']} | {r['fetched']} | {r['read']} |")
    return "\n".join(md) + "\n", js


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prof", type=Path, default=PROF)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()
    windows = load_windows(args.prof)
    if not windows:
        print("no windows under", args.prof)
        return 1
    ledger = json.loads(LEDGER.read_text())
    entries = json.loads(ENTRIES.read_text())
    rt = Routines(ledger, entries, windows)
    image = load_vailixi_linear()
    cov = coverage(args.prof)
    md, js = report(windows, rt, image, cov, args.top)
    (args.prof / "report.md").write_text(md)
    (args.prof / "report.json").write_text(json.dumps(js, indent=1))
    print(args.prof / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
