#!/usr/bin/env python3
"""Cycle profiles of PMONEY BETA 1.0 (WAVE316.SYS) against stock OS 3.16.

Both boot from floppy on the Vailixi 3.50 EPROM set (load segment 6900) at
the physical 16 MHz (NEC_CPU_DIV=2) with the fork's nec_prof profiler.  The
PMONEY payload is the harness build (byte-identical to the released
STARTUP.SYS); the baseline is the hash-pinned M3K316.SYS as STARTUP.SYS.

    python3 -m emu.pmoney_profile             # runs + build/emu/pmoney/report.md
    python3 -m emu.pmoney_profile --analyse-only

Physical addresses: 3.16 image offset o is 0x300000 + L*16 + o; the cave's
offset c is profile.cave_phys + c (notes/port_316.md, emu/harness.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from emu import harness as h
from emu import pgm as pgm_fixture
from emu.mpc3k import BUILD, M3K316, run
from emu.panel import dial, key_tap, write_smf
from emu.snd import disk, sine, sine441, snd
from emu.test_harness_lifecycle import four_zones
from emu.test_mute_voice import load_actions
from emu.test_wave_chop import do_action

OUT = BUILD / "emu" / "pmoney"
BIOS = "vailixi"
NOTES_AT = 68.0
# The harness's 3.16 timelines were measured with the core at the crystal
# rate (NEC_CPU_DIV=1); at 16 MHz the CPU-bound floppy boot is slower and the
# scripted keys arrive early.  Cycles per event do not depend on the core
# clock, so the runs keep DIV=1 and every rate is reported per 16 MHz
# second: busy cycles per emulated second / 16e6 is the physical load
# while timers (and so interrupt counts) are unchanged.
CPU_DIV = "1"
CPU_HZ = 16_000_000
# 3.16 waits for a key in two loops (image offsets; same bytes as Vailixi
# D6E1:000B and D6E0:0000): poll with the [D398] kick, and the blocking wait.
IDLE_LOOPS = ((0x2D0DB, 0x2D0EB), (0x2D0BA, 0x2D0C2), (0x2D175, 0x2D17D))
# BIOS floppy completion polls (F9F3:000E, F9D2:000C+48): waits too.
BIOS_WAITS = ((0xF9F3E, 0xF9F54), (0xF9D74, 0xF9D7C))


def taps(*items):
    return h.taps(*items)


def burst_series(start: float, n: int) -> list:
    ev = []
    for i in range(n):
        ev += h.burst(9 if i % 2 == 0 else -9, start + i)
    return ev


def jobs(profile: h.Profile) -> dict[str, dict]:
    fx = OUT / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    stock_sys = fx / "M3K316.SYS"
    stock_sys.write_bytes(M3K316.read_bytes())

    def floppy(build: str, name: str, files: list) -> Path:
        if build == "pmoney":
            return h.wave_disk(profile, f"pm-{name}", files)
        return disk(f"pm-stock-{name}", [(stock_sys, "STARTUP.SYS"), *files])

    tone = fx / "TEST.SND"
    tone.write_bytes(snd("TEST", [sine(2205)]))
    programs = {}
    for name, enabled in (("off", False), ("on", True)):
        p = fx / f"MUTE{name.upper()}.PGM"
        p.write_bytes(pgm_fixture.for_sound(tone.read_bytes(), pads=range(64), enabled=enabled,
                                            groups=[1 + pad % 4 for pad in range(64)],
                                            program_name="PROF MUTE"))
        programs[name] = p
    sine_snd = fx / "SINE441.SND"
    sine_snd.write_bytes(snd("SINE441", sine441()))

    notes = []
    for i in range(64):
        t = NOTES_AT + i * 0.1
        notes += [(t, bytes((0x90, 0x23 + i, 100))), (t + 0.04, bytes((0x80, 0x23 + i, 0)))]
    tl = h.TIMELINE_316

    out: dict[str, dict] = {}
    for build in ("stock", "pmoney"):
        out[f"{build}_idle"] = {"build": build, "disk": floppy(build, "idle", []),
                                "panel": taps((tl.cancel, "soft4")), "windows": {"idle": (38.0, 48.0)}}
        for mute in ("off", "on"):
            if build == "stock" and mute == "on":
                continue
            out[f"{build}_notes_{mute}"] = {
                "build": build, "disk": floppy(build, f"notes-{mute}", [(programs[mute], "MUTE.PGM"), (tone, "TEST.SND")]),
                "panel": load_actions(profile), "midi": notes,
                "windows": {"notes": (NOTES_AT - 0.5, NOTES_AT + 6.9)}}

    V = profile.view
    view = (burst_series(V + 3, 6)                                  # Full: wheel bursts on Start
            + taps((V + 10, "soft3")) + burst_series(V + 12, 6)     # Fine, wheel bursts
            + taps(*[(V + 19 + i, "up") for i in range(4)])          # zoom
            + taps((V + 24, "soft3"))                                # back to Full
            + taps((V + 26, "soft1"), (V + 27.3, "soft1"))           # play / stop
            + four_zones(V + 29)                                     # zone count 16 -> 4
            + taps((V + 35, "soft4")))                               # exit to Edit Sound
    out["pmoney_view"] = {"build": "pmoney", "disk": floppy("pmoney", "view", [(sine_snd, "SINE441.SND")]),
                          "panel": h.wave_events(view, profile=profile),
                          "windows": {"view_open": (V - 4.5, V + 0.5), "view_idle": (V + 0.5, V + 2.5),
                                      "wheel_full": (V + 2.9, V + 9.5), "fine_toggle": (V + 9.9, V + 11.5),
                                      "wheel_fine": (V + 11.9, V + 18.5), "zoom": (V + 18.9, V + 23.5),
                                      "full_toggle": (V + 23.9, V + 25.5), "play": (V + 25.9, V + 28.5),
                                      "zones": (V + 28.9, V + 34.5), "exit": (V + 34.9, V + 37.0)}}
    out["pmoney_chop"] = {"build": "pmoney", "disk": floppy("pmoney", "chop", [(sine_snd, "SINE441.SND")]),
                          "panel": h.wave_events(four_zones(V + 1) + do_action(V + 8, profile), profile=profile),
                          "windows": {"chop": (V + 16.9, V + 40.0)}}
    return out


def execute(name: str, job: dict) -> Path:
    out = OUT / name
    end = max(e for _, e in job["windows"].values()) + 0.5
    env = {"NEC_CPU_DIV": CPU_DIV, "NEC_PROF_DIR": str(out),
           "NEC_PROF_WINDOWS": ",".join(f"{s}:{e}" for s, e in job["windows"].values())}
    extra = []
    if job.get("midi"):
        extra += ["-midiin1", str(write_smf(OUT / f"{name}-midi.mid", job["midi"]))]
    run(BIOS, [end], out, floppy=job["disk"], panel=write_smf(OUT / f"{name}-panel.mid", job["panel"]),
        extra=extra, env=env)
    (out / "windows.json").write_text(json.dumps({k: list(v) for k, v in job["windows"].items()}))
    return out


# ---------------------------------------------------------------- analysis

def load_window(path: Path) -> dict:
    w = {"addr": {}, "incl": {}, "vec": {}, "io": {}, "ss": {}, "edges": {}}
    for line in path.read_text().splitlines():
        f = line.split()
        if not f or f[0] == "#":
            continue
        if f[0] == "T":
            w.update({k: int(v) for k, v in (x.split("=") for x in f[1:])})
        elif f[0] == "A":
            w["addr"][int(f[1], 16)] = (int(f[2]), int(f[3]))
        elif f[0] == "I":
            w["incl"][int(f[1], 16)] = (int(f[2]), int(f[3]))
        elif f[0] == "V":
            w["vec"][int(f[1], 16)] = (int(f[2]), int(f[3]))
        elif f[0] == "P":
            w["io"][int(f[1], 16)] = (int(f[2]), int(f[3]))
        elif f[0] == "S":
            w["ss"][int(f[1], 16)] = int(f[2])
        elif f[0] == "E":
            w["edges"][(int(f[1], 16), int(f[2], 16))] = int(f[3])
    return w


class Names:
    def __init__(self, profile: h.Profile):
        self.base = 0x300000 + profile.load_segment * 16
        self.cave = profile.cave_phys
        syms = profile.symbols()
        self.labels = sorted((off, name) for name, off in syms.items() if "." not in name)
        self.cave_end = self.cave + h.cave_end(profile.map)

    def in_cave(self, phys: int) -> bool:
        return self.cave <= phys < self.cave_end

    def name(self, phys: int) -> str:
        if self.in_cave(phys):
            off = phys - self.cave
            best = max((x for x in self.labels if x[0] <= off), default=(0, "?"))
            return f"cave:{best[1]}"
        if self.base <= phys < self.base + 0x7E000:
            return f"3.16+{phys - self.base:05X}"
        return f"phys {phys:06X}"


def idle_set(names: "Names") -> set[int]:
    ranges = [(names.base + s, names.base + e) for s, e in IDLE_LOOPS] + list(BIOS_WAITS)
    return {a for s, e in ranges for a in range(s, e)}


def summarize(w: dict, idle: set[int], names: Names, seconds: float) -> dict:
    total = w["total"]
    idle_c = sum(c for a, (_, c) in w["addr"].items() if a in idle)
    cave = defaultdict(int)
    stock = 0
    for a, (_, c) in w["addr"].items():
        if a in idle:
            continue
        if names.in_cave(a):
            cave[names.name(a)] += c
        else:
            stock += c
    lcd = sum(r + wr for p, (r, wr) in w["io"].items() if p in (0xE0, 0xE2))
    dsp = sum(r + wr for p, (r, wr) in w["io"].items() if 0x60 <= p <= 0x6F)
    return {"seconds": seconds, "total": total, "idle": idle_c, "busy": total - idle_c,
            "busy_pct": 100 * (total - idle_c) / seconds / CPU_HZ, "cave": sum(cave.values()),
            "stock": stock, "lcd_io": lcd, "dsp_io": dsp,
            "cave_top": sorted(cave.items(), key=lambda kv: -kv[1])[:12],
            "vectors": {f"{k:02X}": v for k, v in w["vec"].items()}}


def analyse(names: Names) -> dict:
    res = {}
    idle = idle_set(names)
    loops = {"pmoney": idle, "stock": idle}
    res["idle_loop"] = "3.16 image 2D0DB-2D0EB, 2D0BA-2D0C2, 2D175-2D17D; BIOS F9F3E-F9F54, F9D74-F9D7C"
    for run_dir in sorted(OUT.iterdir()):
        wj = run_dir / "windows.json"
        if not wj.exists():
            continue
        windows = json.loads(wj.read_text())
        build = run_dir.name.split("_")[0]
        for i, (label, (s, e)) in enumerate(windows.items()):
            p = run_dir / f"prof_{i}.txt"
            if p.exists():
                res[f"{run_dir.name}/{label}"] = summarize(load_window(p), loops[build], names, e - s)
    # Per-call costs on the note path.
    calls = {}
    for run_name in ("stock_notes_off", "pmoney_notes_off", "pmoney_notes_on"):
        w = load_window(OUT / run_name / "prof_0.txt")
        rows = {}
        for label, target in (("note builder 20ED:000D", names.base + 0x20ED * 16 + 0x0D),
                              ("allocator 205E:0008", names.base + 0x205E * 16 + 0x08)):
            c, n = w["incl"].get(target, (0, 0))
            rows[label] = (n, round(c / n) if n else None)
        for label in ("mute_note_on_wrapper", "mute_voice_alloc_wrapper"):
            off = dict((n, o) for o, n in names.labels).get(label)
            if off is not None:
                c, n = w["incl"].get(names.cave + off, (0, 0))
                rows[label] = (n, round(c / n) if n else None)
        calls[run_name] = rows
    res["note_calls"] = calls
    return res


def report(res: dict) -> str:
    md = ["# PMONEY BETA 1.0 cycle profile\n",
          "Generated by `python3 -m emu.pmoney_profile`. Vailixi 3.50 EPROM set, L=6900. Core at the harness "
          "clock (DIV=1, timelines valid); busy % is busy cycles per second over 16 MHz. "
          "One run per workload.\n", f"Idle loops: {res['idle_loop']}\n",
          "| run/window | s | busy @16MHz | busy cycles | per s | cave | LCD I/O | DSP I/O |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
    for k, v in res.items():
        if "/" in k:
            md.append(f"| {k} | {v['seconds']:.1f} | {v['busy_pct']:.1f}% | {v['busy']} | {v['busy'] / v['seconds']:.0f} | "
                      f"{v['cave']} | {v['lcd_io']} | {v['dsp_io']} |")
    md += ["", "## Note path per call (calls, inclusive cycles per call)\n"]
    for run_name, rows in res["note_calls"].items():
        md.append(f"- {run_name}: " + "; ".join(f"{k} {n} x {c}" for k, (n, c) in rows.items()))
    md += ["", "## Cave hot spots per window\n"]
    for k, v in res.items():
        if "/" in k and v["cave"]:
            md.append(f"- **{k}**: " + ", ".join(f"{n} {c}" for n, c in v["cave_top"][:8]))
    return "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--analyse-only", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    profile = h.payload("316", BIOS)
    if not args.analyse_only:
        todo = jobs(profile)
        if args.only:
            todo = {k: v for k, v in todo.items() if k in args.only.split(",")}
        OUT.mkdir(parents=True, exist_ok=True)
        h.run_parallel(todo, execute)
    res = analyse(Names(profile))
    (OUT / "result.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "report.md").write_text(report(res))
    print(OUT / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
