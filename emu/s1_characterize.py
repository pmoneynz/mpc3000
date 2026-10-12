#!/usr/bin/env python3
"""S1 characterization: what the per-layer note-on `CFC6:039E` computes from what.

notes/performance.md §9 step 1.  Plays every pad (MIDI In 1, channel 1, notes
0x23..0x62) at velocities 1, 32, 64, 100, 127 on stock Vailixi 3.50 and traces,
with the fork's NEC trace points (no ROM or RAM is modified):

  - the entry of `CFC6:039E` (file 0x4FFFE): its stack arguments, the event,
    the pad's note record, sound records 0-1 and the DGROUP lookup tables;
  - every far call into the BIOS 32-bit runtime (`F800:20C4` multiply,
    `20FA` signed divide, `2101` unsigned divide, `21A8` shift left) with its
    operands, and the instruction after it with the result in DX:AX;
  - every DSP port access (`0x60`-`0x6F`) between entry and return.

Three runs: `default` (native blank program, 64 pads -> one mono sound) twice,
the second in reverse order shifted by half a sequencer tick, and `varied`
(per-pad stimulus bytes in the fields the routine reads, stereo sound with
volume 77 and tune -12).  The analysis (`analyse()`) proves or refutes, for
these executions:

  1. every runtime call result is the same function of the traced inputs in
     every run (no hidden state);
  2. which calls change with velocity when everything else is fixed;
  3. the DSP write sequence per (pad, velocity) is identical across runs
     once the voice channel number is normalized.

    python3 -m emu.s1_characterize          # runs + report in build/emu/s1/
    python3 -m emu.s1_characterize --analyse-only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from emu import pgm as pgm_fixture
from emu.harness import run_parallel, taps
from emu.mpc3k import BUILD, run
from emu.panel import write_smf
from emu.snd import disk, sine, snd

OUT = BUILD / "emu" / "s1"
CS = 0xCFC6
BASE = (CS << 4)                      # stock: identity PGR frame, phys = 20-bit
ROUTE_A = 0x300000                    # Route A: third PGR maps logical B0000-F3FFF to RAM, phys = 0x300000 + 20-bit
# Builds: (Route A args file or None for the EPROM OS, physical base of CFC6:0000).
# `ctrl` is Route A with only the builder's mandatory loader patch and demo
# version string: it separates running the OS from RAM from the S1a change.
BUILDS = {"stock": (None, BASE), "ctrl": ("S1CTRL", ROUTE_A + BASE), "s1a": ("S1A", ROUTE_A + BASE)}
CAVE_PHYS = ROUTE_A + 0xF07D0         # F07D:0000 (mods/build_mod_sys.py CAVE_SEG)
ENTRY_IP = 0x039E
EXIT_IPS = (0x03B8, 0x03DA, 0x06E2, 0x0768, 0x0B24)
# Far calls into the BIOS runtime inside 039E (ndisasm of file [0x4FFFE,0x50785),
# no 0F E0/F0 in the range), with their callee.
CALLS = {0x053F: "20C4", 0x0546: "20FA", 0x0572: "20FA", 0x05F1: "20FA",
         0x065A: "20C4", 0x0661: "2101", 0x0691: "20C4", 0x0698: "2101",
         0x0771: "20FA", 0x0809: "21A8", 0x0810: "20FA", 0x0817: "20FA",
         0x0851: "21A8", 0x0858: "20FA", 0x085F: "20FA", 0x0884: "21A8",
         0x088B: "20FA", 0x0892: "20FA", 0x08CD: "20C4", 0x08D4: "20FA",
         0x08E1: "20FA", 0x091F: "20C4", 0x0926: "20FA", 0x0934: "20FA",
         0x094A: "20C4", 0x0951: "20FA"}
# Blocks of the routine (by call-site IP), named by what selects them.
BLOCKS = {"A": (0x052E, 0x061B), "B": (0x061B, 0x06A3), "C": (0x0769, 0x0779),
          "D": (0x07B4, 0x0867), "E": (0x0867, 0x089A), "F": (0x08C0, 0x08E9),
          "G": (0x090D, 0x0959)}
VELOCITIES = (1, 32, 64, 100, 127)
NOTES = range(0x23, 0x23 + 64)
TICK = 5208.5e-6                      # 120 BPM sequencer tick (notes/sequencer_model.md)
START, GAP = 46.0, 0.1               # notes after every build has loaded the 176 KB stereo sound
TABLES = "a8010:7346:CA,a8010:74DA:CA,a8010:7410:CA,a8010:6F84:3C2,a8010:75A4:10"


def block_of(ip: int) -> str:
    return next(k for k, (s, e) in BLOCKS.items() if s <= ip < e)


def trace_spec(base: int = BASE) -> str:
    entry = (f"{base + ENTRY_IP:X}=ENTRY,s0:1A,ps6:8,psA:18,psE:4,ps12:4,"
             f"aA2AE:4800:48,a8010:E739:1,a8010:E5F9:4,{TABLES}")
    points = [entry]
    for ip, callee in CALLS.items():
        points.append(f"{base + ip:X}=C{ip:04X}_{callee},s0:8")
        points.append(f"{base + ip + 5:X}=R{ip:04X}_{callee}")
    for ip in EXIT_IPS:
        points.append(f"{base + ip:X}=X{ip:04X}")
    # Voice start CFC6:0B2D (near call with PUSH CS): far pointers to the
    # parameter blocks [BP-4Ch] and [BP-5Ch] of 039E at SP+4 and SP+8.
    points.append(f"{base + 0x0B2D:X}=V0B2D,s0:14,ps4:20,ps8:10")
    # Allocator CF37:0002 (file 0x4F372): its mutable inputs are the per-channel
    # remaining-time words DS:E410 (task 1 B259:0006 counts them down), the
    # owner notes DS:E599, the rotating index DS:E597 and DS:D0AD.
    points.append(f"{base - BASE + 0xCF372:X}=L,s0:10,a8010:E410:40,a8010:E599:20,a8010:E597:2,a8010:D0AD:1")
    return ";".join(points)


# ---------------------------------------------------------------- fixtures

def varied_pgm(sound: bytes) -> bytes:
    """Native blank with every pad on the sound and stimulus bytes in the fields 039E reads.

    The values are test stimuli inside the ranges the routine's own clamps and
    101-entry tables accept (0..100, tune +-240); they are not claims about
    what the fields mean in the UI.
    """
    data = bytearray(pgm_fixture.for_sound(sound, pads=range(64), program_name="S1 VARIED"))
    for pad in range(64):
        r = pgm_fixture.NOTE_RECORDS + pad * pgm_fixture.NOTE_RECORD_BYTES
        k = pad
        data[r + 0x09:r + 0x0B] = ((k * 7) % 41 - 20).to_bytes(2, "little", signed=True)
        for off, mod, mul in ((0x0B, 101, 13), (0x0C, 101, 29), (0x0E, 101, 37), (0x0F, 16, 5),
                              (0x10, 101, 17), (0x11, 101, 23), (0x12, 101, 11), (0x13, 101, 31),
                              (0x14, 101, 19), (0x15, 101, 43), (0x16, 101, 53)):
            data[r + off] = (k * mul + off) % mod
    return bytes(data)


def fixtures() -> dict[str, list[tuple[Path, str]]]:
    d = OUT / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    mono = snd("S1MONO", [sine(2205)])                         # 50 ms, so voices free up
    stereo = bytearray(snd("S1ST", [sine(44100), sine(44100)[::-1]], vol=77))   # 1 s: start offsets stay inside
    stereo[2 + 0x12] = (-12) & 0xFF
    out = {}
    for name, sound, program in (
            ("default", mono, pgm_fixture.for_sound(mono, pads=range(64), program_name="S1 DEFAULT")),
            ("varied", bytes(stereo), varied_pgm(bytes(stereo)))):
        (d / f"{name}.SND").write_bytes(sound)
        (d / f"{name}.PGM").write_bytes(program)
        # <Load it> finds a program's sounds by file name = sound name.
        sound_file = sound[2:2 + 16].split(b"\0", 1)[0].decode() + ".SND"
        out[name] = [(d / f"{name}.PGM", "S1.PGM"), (d / f"{name}.SND", sound_file)]
    return out


def mod_sys(args_name: str) -> Path:
    """Build a Route A mod from mods/<args_name>.args (or the bare demo) into build/emu/s1/mods/."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mods"))
    import build_mod_sys as mod
    out = OUT / "mods"
    out.mkdir(parents=True, exist_ok=True)
    args_file = Path(__file__).resolve().parents[1] / "mods" / f"{args_name}.args"
    if args_file.exists():
        a = mod.read_args(args_file)
        sys_path, _ = mod.build(a.patch, a.cave, a.name, out)
    else:
        sys_path, _ = mod.build([], None, args_name, out)
    return sys_path


def notes(order: list[tuple[int, int]], shift: float) -> list[tuple[float, bytes]]:
    ev = []
    for i, (note, vel) in enumerate(order):
        t = START + shift + i * GAP
        ev += [(t, bytes((0x90, note, vel))), (t + 0.04, bytes((0x80, note, 0)))]
    return ev


def runs(builds: tuple[str, ...] = ("stock", "ctrl", "s1a")) -> dict[str, dict]:
    """Stock runs keep their historical names (default, default_rev, varied); the others are prefixed."""
    files = fixtures()
    forward = [(n, v) for v in VELOCITIES for n in NOTES]
    load = taps((20.0, "soft4"), (23.0, "disk"), (24.5, "7"), (26.5, "soft1"), (29.5, "soft1"),
                (38.0, "main_screen"))
    plans = {"default": ("default", notes(forward, 0.0)),
             "default_rev": ("default", notes(forward[::-1], TICK / 2)),
             "varied": ("varied", notes(forward, 0.0))}
    jobs = {}
    for build in builds:
        args_name, base = BUILDS[build]
        payload = [(mod_sys(args_name), "STARTUP.SYS")] if args_name else []
        for plan, (fixture, midi) in plans.items():
            if build == "ctrl" and plan != "default":
                continue
            name = plan if build == "stock" else f"{build}_{plan}"
            jobs[name] = {"build": build, "base": base, "plan": plan,
                          "disk": disk(f"s1-{build}-{fixture}", payload + files[fixture]),
                          "midi": midi, "panel": load}
    return jobs


def execute(name: str, job: dict) -> Path:
    out = OUT / name
    end = START + 1 + len(job["midi"]) / 2 * GAP
    env = {"NEC_CPU_DIV": "2", "NEC_TRACE_FILE": str(OUT / f"{name}.trace"),
           "NEC_TRACE_FROM": str(START - 0.5), "NEC_TRACE_IO": "60-6F", "NEC_TRACE_AT": trace_spec(job["base"]),
           "NEC_PROF_DIR": str(out), "NEC_PROF_WINDOWS": f"{START - 0.5}:{end}"}
    OUT.mkdir(parents=True, exist_ok=True)
    run("vailixi", [end + 0.5], out, floppy=job["disk"],
        panel=write_smf(OUT / f"{name}-panel.mid", job["panel"]),
        extra=["-midiin1", str(write_smf(OUT / f"{name}-midi.mid", job["midi"]))], env=env)
    return OUT / f"{name}.trace"


# ---------------------------------------------------------------- parsing

@dataclass
class Call:
    ip: int
    callee: str
    regs: dict[str, int]
    stack: bytes
    result: int | None = None

    @property
    def operands(self) -> tuple:
        r = self.regs
        if self.callee == "20C4":                                 # DX:AX * CX:BX
            return ((r["DW"] << 16) | r["AW"], (r["CW"] << 16) | r["BW"])
        if self.callee in ("20FA", "2101"):                       # [SP] = dividend lo, hi, divisor lo, hi
            s = self.stack
            return (int.from_bytes(s[0:4], "little"), int.from_bytes(s[4:8], "little"))
        return ((r["DW"] << 16) | r["AW"], r["CW"] & 0xFF)       # 21A8: DX:AX << CL


@dataclass
class Note:
    t: float
    run: str
    args: bytes
    event: bytes
    record: bytes
    sounds: bytes
    globals_: bytes
    tables: bytes
    mix: bytes = b""
    calls: list[Call] = field(default_factory=list)
    voice_params: list[bytes] = field(default_factory=list)
    alloc_state: list[bytes] = field(default_factory=list)
    io: list[tuple[str, str, int, int]] = field(default_factory=list)
    foreign_io: int = 0             # accesses by other stacks (tasks, ISRs) inside the window
    ss: int = 0
    exit_ip: int | None = None
    voices: int = 0

    @property
    def velocity(self) -> int:
        return self.event[3]

    @property
    def sound(self) -> bytes:
        i = self.record[0]
        return self.sounds[i * 0x24:(i + 1) * 0x24] if i < 2 else b""

    @property
    def inputs(self) -> tuple:
        """Everything 039E reads besides the constant tables (bytes)."""
        return (self.args[6:0x1A], self.event, self.record, self.sound, self.globals_, self.mix)


REGS = ("AW", "BW", "CW", "DW", "IX", "IY", "BP", "SP", "DS0", "DS1", "SS", "PSW")


def parse(path: Path, name: str) -> list[Note]:
    notes, cur, pending = [], None, {}
    for line in path.read_text().splitlines():
        f = line.split()
        if f[0] == "I":
            if cur is not None:
                # Only accesses on the note-on's own stack belong to it: a
                # higher-priority task or an ISR can run inside the window.
                if len(f) > 7 and int(f[7], 16) != cur.ss:
                    cur.foreign_io += 1
                else:
                    cur.io.append((f[3], f[4], int(f[5], 16), int(f[6], 16)))
            continue
        t, tag = float(f[1]), f[2]
        regs = dict(zip(REGS, (int(x, 16) for x in f[4:16])))
        items = {}
        for it in f[16:]:
            k, v = it.split("=", 1)
            items[k.split("@")[0]] = bytes.fromhex(v)
        if tag == "ENTRY":
            cur = Note(t, name, items["s0"], items["S6"], items["SA"],
                       items["aA2AE:4800"], items["a8010:E739"] + items["a8010:E5F9"],
                       b"".join(v for k, v in items.items() if k.startswith("a8010:7") or k.startswith("a8010:6")),
                       items["SE"] + items["S12"])
            cur.ss = regs["SS"]
            pending = {}
            notes.append(cur)
        elif cur is None:
            continue
        elif tag[0] == "C":
            c = Call(int(tag[1:5], 16), tag[6:], regs, items["s0"])
            cur.calls.append(c)
            pending[c.ip] = c
        elif tag[0] == "R":
            c = pending.pop(int(tag[1:5], 16), None)
            if c is not None:
                c.result = (regs["DW"] << 16) | regs["AW"]
        elif tag == "L":
            cur.alloc_state.append(items["a8010:E410"] + items["a8010:E599"] + items["a8010:E597"]
                                   + items["a8010:D0AD"])
        elif tag[0] == "V":
            cur.voices += 1
            cur.voice_params.append(items["S4"] + items["S8"])
        elif tag[0] == "X":
            cur.exit_ip = int(tag[1:], 16)
            cur = None
    return notes


def dsp_sequence(note: Note) -> tuple:
    """DSP accesses with the voice channel (low byte of the 0x60 select) replaced by its order of first use."""
    seen: dict[int, int] = {}
    seq = []
    for rw, size, port, data in note.io:
        if rw == "W" and port == 0x60 and size == "w":
            ch = data & 0x1F
            data = (data & ~0x1F) | seen.setdefault(ch, len(seen))
        elif rw == "W" and port == 0x60 and size == "b":
            ch = data & 0x1F
            data = (data & ~0x1F) | seen.setdefault(ch, len(seen))
        seq.append((rw, size, port, data if rw == "W" else None))
    return tuple(seq)


# ---------------------------------------------------------------- analysis

# Bytes of the [BP-4Ch] (0x20) and [BP-5Ch] (0x10) blocks that CFC6:039E
# writes on every path to its first 0B2D call (offsets from BP; disassembly of
# [0x4FFFE, 0x50785)).  The others are written only on some paths (block A's
# -54h/-50h/-4Eh, the variation-1 path's -30h) or are 0B2D's outputs
# (-4Ch, -2Dh); -35h lies between the word at -34h and the byte at -36h and
# is never written.  They hold whatever the task stack held before.
WRITTEN = (set(range(-0x4B, -0x37)) | {-0x37, -0x36, -0x34, -0x33, -0x32, -0x31}
           | {-0x5C, -0x5B, -0x5A, -0x59, -0x58, -0x57, -0x56, -0x55, -0x52, -0x51})


def voice_inputs(raw: bytes) -> bytes:
    """The written bytes of one 0B2D call's parameter blocks, in a fixed order."""
    out = bytearray()
    for off in sorted(WRITTEN):
        out.append(raw[off + 0x4C] if off >= -0x4C else raw[0x20 + off + 0x5C])
    return bytes(out)


def analyse(all_notes: dict[str, list[Note]]) -> dict:
    res: dict = {"runs": {}, "purity": {}, "velocity": {}, "dsp": {}, "blocks": {}}
    tables = {n.tables for ns in all_notes.values() for n in ns}
    res["tables_constant"] = len(tables) == 1
    for name, ns in all_notes.items():
        res["runs"][name] = {"note_ons": len(ns), "complete": sum(1 for n in ns if n.exit_ip == 0x0B24),
                             "exits": dict(Counter(f"{n.exit_ip:04X}" if n.exit_ip else "none" for n in ns)),
                             "velocities": sorted({n.velocity for n in ns}),
                             "calls_per_note": dict(Counter(len(n.calls) for n in ns))}

    # 1. Purity: (call site, operands) -> result must be single-valued, and
    #    (inputs) -> full call list must be single-valued across runs.
    by_operands: dict = defaultdict(set)
    by_inputs: dict = defaultdict(set)
    for ns in all_notes.values():
        for n in ns:
            for c in n.calls:
                by_operands[(c.callee, c.operands)].add(c.result)
            by_inputs[n.inputs].add(tuple((c.ip, c.operands, c.result) for c in n.calls))
    res["purity"] = {
        "distinct_operand_sets": len(by_operands),
        "operand_sets_with_two_results": sum(1 for v in by_operands.values() if len(v) > 1),
        "distinct_input_tuples": len(by_inputs),
        "input_tuples_seen_more_than_once": sum(1 for k in by_inputs if sum(
            1 for ns in all_notes.values() for n in ns if n.inputs == k) > 1),
        "input_tuples_with_two_call_lists": sum(1 for v in by_inputs.values() if len(v) > 1),
    }
    # Arithmetic check of the runtime itself on every traced call.
    bad = 0
    for ns in all_notes.values():
        for n in ns:
            for c in n.calls:
                a, b = c.operands
                if c.callee == "20C4":
                    want = (a * b) & 0xFFFFFFFF
                elif c.callee == "21A8":
                    want = (a << b) & 0xFFFFFFFF
                elif c.callee == "2101":
                    want = (a // b) & 0xFFFFFFFF if b else None
                else:
                    sa = a - (1 << 32) if a & 0x80000000 else a
                    sb = b - (1 << 32) if b & 0x80000000 else b
                    q = abs(sa) // abs(sb) if sb else None
                    want = None if q is None else (q if (sa < 0) == (sb < 0) else -q) & 0xFFFFFFFF
                bad += want is not None and want != c.result
    res["purity"]["runtime_results_not_matching_python"] = bad
    res["fast_divide"] = fast_divide_check(all_notes)

    # 2. Velocity dependence: within one run, group by (pad, everything but
    #    velocity); a call site depends on velocity if its operands differ.
    for name, ns in all_notes.items():
        groups: dict = defaultdict(list)
        for n in ns:
            ev = bytearray(n.event)
            ev[3] = 0
            groups[(n.args[6:0x1A].hex(), bytes(ev), n.record, n.sound, n.mix)].append(n)
        dep: dict = defaultdict(lambda: [0, 0])
        for g in groups.values():
            if len({n.velocity for n in g}) < 2:
                continue
            sites = defaultdict(set)
            for n in g:
                for c in n.calls:
                    sites[c.ip].add((n.velocity, c.operands))
            for ip, s in sites.items():
                varies = len({o for _, o in s}) > 1
                dep[ip][varies] += 1
        res["velocity"][name] = {f"{ip:04X}_{CALLS[ip]}_{block_of(ip)}": {"same": d[0], "varies": d[1]}
                                 for ip, d in sorted(dep.items())}

    # 3. DSP sequences per input tuple, across every run and build.
    seqs: dict = defaultdict(set)
    builds_of: dict = defaultdict(set)
    for name, ns in all_notes.items():
        for n in ns:
            seqs[n.inputs].add(dsp_sequence(n))
            builds_of[n.inputs].add(build_of(name))
    differing = sum(1 for s in seqs.values() if len(s) > 1)
    res["cross_build"] = {f"{a}+{b}": sum(1 for v in builds_of.values() if {a, b} <= v)
                          for a, b in (("stock", "ctrl"), ("stock", "s1a"))}
    # The arithmetic's output: what 039E hands to the voice start, per input tuple.
    params: dict = defaultdict(set)
    for ns in all_notes.values():
        for n in ns:
            params[n.inputs].add(tuple(voice_inputs(v) for v in n.voice_params))
    res["voice_params"] = {"input_tuples": len(params),
                           "voice_starts": sum(len(n.voice_params) for ns in all_notes.values() for n in ns),
                           "tuples_with_two_parameter_lists": sum(1 for v in params.values() if len(v) > 1)}
    # Whole DSP sequence per input tuple, per program: the default program never
    # contests a voice (50 ms sound, 100 ms apart); the varied one does.
    by_program: dict = defaultdict(lambda: defaultdict(set))
    for name, ns in all_notes.items():
        program = "varied" if name.endswith("varied") else "default"
        for n in ns:
            by_program[program][n.inputs].add(dsp_sequence(n))
    # Whole DSP sequences again, keyed by the inputs plus the allocator's
    # state at each allocation: equal keys must give equal sequences.
    full: dict = defaultdict(set)
    for ns in all_notes.values():
        for n in ns:
            full[(n.inputs, tuple(n.alloc_state))].add(dsp_sequence(n))
    res["dsp_with_allocator_state"] = {"keys": len(full),
                                       "keys_with_two_sequences": sum(1 for v in full.values() if len(v) > 1)}
    res["dsp_by_program"] = {k: {"input_tuples": len(v), "tuples_with_two_sequences":
                                 sum(1 for s in v.values() if len(s) > 1)} for k, v in by_program.items()}
    res["dsp"] = {"input_tuples": len(seqs), "tuples_with_two_sequences": differing,
                  "foreign_accesses_excluded": sum(n.foreign_io for ns in all_notes.values() for n in ns),
                  "writes_per_note": dict(Counter(sum(1 for x in dsp_sequence(n) if x[0] == "W")
                                                  for ns in all_notes.values() for n in ns))}

    # Block occupancy (calls per block per note), from the varied run.
    occ: dict = defaultdict(Counter)
    for name, ns in all_notes.items():
        for n in ns:
            occ[name][" ".join(sorted({block_of(c.ip) for c in n.calls}))] += 1
    res["blocks"] = {k: dict(v) for k, v in occ.items()}
    return res


def build_of(run_name: str) -> str:
    head = run_name.split("_")[0]
    return head if head in BUILDS else "stock"


def runtime_long_path(c: Call) -> bool:
    """F800:2114 takes `div bx` only when the divisor high word and the dividend high word are 0."""
    a, b = c.operands
    return (b >> 16) != 0 or ((a >> 16) != 0 and (b & 0xFFFF) != 0)


def fast_divide(callee: str, a: int, b: int) -> int | None:
    """The S1a cave (mods/s1a.asm) as a model: None where it falls back to the runtime.

    Fast path only for a divisor with high word 0 and low word non-zero: two
    32/16 DIVU steps on the dividend's magnitude, quotient negated when a
    signed dividend was negative (F800:20FA truncates toward zero).
    """
    if b == 0 or b > 0xFFFF:
        return None
    neg = callee == "20FA" and bool(a & 0x80000000)
    if neg:
        a = (-a) & 0xFFFFFFFF
    hi, r = divmod(a >> 16, b)                   # DIVU: DX=0, AX=a_hi -> AX=hi, DX=r
    lo, _ = divmod((r << 16) | (a & 0xFFFF), b)  # DIVU: DX=r < b, so the quotient fits 16 bits
    q = (hi << 16) | lo
    return (-q) & 0xFFFFFFFF if neg else q


def fast_divide_check(all_notes: dict[str, list[Note]]) -> dict:
    out = {"divides": 0, "eligible": 0, "exact": 0, "fallback": 0, "runtime_long_path": 0,
           "long_path_per_default_layer": None}
    for ns in all_notes.values():
        for n in ns:
            for c in n.calls:
                if c.callee not in ("20FA", "2101"):
                    continue
                out["divides"] += 1
                out["runtime_long_path"] += runtime_long_path(c)
                q = fast_divide(c.callee, *c.operands)
                if q is None:
                    out["fallback"] += 1
                else:
                    out["eligible"] += 1
                    out["exact"] += q == c.result
    d = all_notes.get("default", [])
    if d:
        out["long_path_per_default_layer"] = dict(Counter(
            sum(runtime_long_path(c) for c in n.calls if c.callee in ("20FA", "2101")) for n in d))
    return out


def costs(jobs: dict[str, dict]) -> dict:
    """Inclusive cycles per call of 039E, its callees and the divide routines, from the profiler windows."""
    labels = cave_labels()
    out = {}
    for name, job in jobs.items():
        shift = job["base"] - BASE
        p = OUT / name / "prof_0.txt"
        if not p.exists():
            continue
        incl = {}
        for line in p.read_text().splitlines():
            f = line.split()
            if f and f[0] == "I":
                incl[int(f[1], 16)] = (int(f[2]), int(f[3]))
        row = {}
        rows = [("CFC6:0007 builder", 0xCFC67 + shift), ("CFC6:039E layer", 0xCFFFE + shift),
                ("CFC6:0B2D voice start", 0xD078D + shift), ("CF37:0002 allocator", 0xCF372 + shift),
                ("F800:20C4 mul", 0xFA0C4), ("F800:20FA idiv", 0xFA0FA),
                ("F800:2101 udiv", 0xFA101), ("F800:21A8 shl", 0xFA1A8)]
        if job["build"] == "s1a":
            rows += [(f"F07D:{labels[k]:04X} {k}", CAVE_PHYS + labels[k]) for k in ("s1a_idiv", "s1a_udiv")]
        for label, phys in rows:
            c, n = incl.get(phys, (0, 0))
            row[label] = {"calls": n, "incl_per_call": round(c / n) if n else None, "incl": c}
        out[name] = row
    return out


def cave_labels() -> dict[str, int]:
    labels = {}
    for line in (OUT / "mods" / "s1a.cave.map").read_text().splitlines():
        f = line.split()
        if len(f) == 3 and f[2].startswith("s1a_") and "." not in f[2]:
            labels[f[2]] = int(f[0], 16)
    return labels


def report(res: dict, cost: dict) -> str:
    md = ["# S1 characterization: `CFC6:039E` per-layer note-on\n",
          "Generated by `python3 -m emu.s1_characterize`. Vailixi 3.50 (stock EPROM; Route A `ctrl`; "
          "Route A `s1a` = mods/S1A.args), CPU 16 MHz "
          "(`NEC_CPU_DIV=2`), MIDI In 1 channel 1, notes 0x23..0x62 x velocities "
          f"{', '.join(map(str, VELOCITIES))}. One trace per run; claims are about these executions.\n",
          "## Runs\n", "| run | note-ons | completed (0B24) | exits | calls per note |", "|---|--:|--:|---|---|"]
    for k, v in res["runs"].items():
        md.append(f"| {k} | {v['note_ons']} | {v['complete']} | {v['exits']} | {v['calls_per_note']} |")
    md += ["", "## Purity\n", "| check | value |", "|---|--:|"]
    for k, v in res["purity"].items():
        md.append(f"| {k} | {v} |")
    md.append(f"| DGROUP tables identical at every entry | {res['tables_constant']} |")
    md += ["", "## Fast divide model (two DIVU steps, fallback to the runtime)\n", "| check | value |", "|---|--:|"]
    for k, v in res["fast_divide"].items():
        md.append(f"| {k} | {v} |")
    md += ["", "## Velocity dependence per call site\n",
           "Groups of notes that differ only in velocity; `varies` counts groups where the call's operands changed.\n"]
    for run_name, sites in res["velocity"].items():
        md += [f"### {run_name}\n", "| site | same | varies |", "|---|--:|--:|"]
        for site, d in sites.items():
            md.append(f"| {site} | {d['same']} | {d['varies']} |")
        md.append("")
    md += ["## DSP write sequences\n", f"{res['dsp']}\n",
           "Input tuples traced in both builds: " + f"{res['cross_build']}\n",
           "Per program: " + f"{res['dsp_by_program']}\n",
           "Keyed by inputs and allocator state: " + f"{res['dsp_with_allocator_state']}\n",
           "Voice-start parameter blocks (bytes 039E writes on every path): " + f"{res['voice_params']}\n", "## Blocks taken per note\n", f"{res['blocks']}\n",
           "## Cost (inclusive cycles per call)\n"]
    for run_name, row in cost.items():
        md += [f"### {run_name}\n", "| routine | calls | incl/call |", "|---|--:|--:|"]
        for k, v in row.items():
            md.append(f"| {k} | {v['calls']} | {v['incl_per_call']} |")
        md.append("")
    return "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--analyse-only", action="store_true")
    args = ap.parse_args()
    jobs = runs()
    if not args.analyse_only:
        run_parallel(jobs, execute)
    all_notes = {name: parse(OUT / f"{name}.trace", name) for name in jobs}
    res = analyse(all_notes)
    cost = costs(jobs)
    (OUT / "result.json").write_text(json.dumps({"analysis": res, "cost": cost}, indent=1, default=str))
    (OUT / "report.md").write_text(report(res, cost))
    print(OUT / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
