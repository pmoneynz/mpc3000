#!/usr/bin/env python3
"""LCD mirror cost at the board's 16 MHz: interrupt-off windows per tick, mirror against stock.

    python3 -m emu.lcdmirror_cost [--bios vailixi]

Runs emu/test_lcdmirror316.py's panel walk on the mirror floppy and on the stock
control with NEC_CPU_DIV=2 and emu/lua/lcdmirror_cost.lua, which logs opcode
fetches of: the tick handler entry 2B50:000C and its IRET 2B50:0061, the AMX
exit 47BF:018E, and in the cave lm_tick, the STI (lm_if_on), the CLI after the
work (lm_if_off), lm_push and its two POPFs.  Per tick (the tick handler has
no STI; notes/lcd_mirror_midi.md §3.2):

  stock     entry -> AMX exit                     interrupts off throughout
  mirror    entry -> STI (or AMX exit if no STI)  off: stock body + the cave's gates
            lm_push -> its POPF                   off: one message into the ring
            CLI -> AMX exit                       off: the re-kick
            lm_tick -> AMX exit                   time in the cave (interruptible part included)

Every window ends at the AMX exit, which both builds then run identically.

Prints percentiles in microseconds and writes build/emu/lcdmirror316-cost/cost.json.
Fetch taps fire at prefetch, up to a few cycles early.  Emulator timing (MAME's V53
cycle model), not a hardware measurement.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from emu import harness as h  # noqa: E402
from emu import mpc3k, panel  # noqa: E402
from emu import test_lcdmirror316 as t  # noqa: E402
from mods import build_lcdmirror316 as lm  # noqa: E402

OUT = h.BUILD / "emu" / "lcdmirror316-cost"
IMAGE = 0x300000 + 0x69000                       # physical image base (L = 6900h)
CAVE = 0x300000 + (0x6900 + 0x7E00) * 16         # physical cave home
STOCK_POINTS = {"entry": IMAGE + 0x2B50C, "iret": IMAGE + 0x2B561, "amx": IMAGE + 0x47BF * 16 + 0x18E}
CAVE_POINTS = {"tick": "lm_tick", "on": "..@lm_if_on", "off": "..@lm_if_off", "push": "lm_push",
               "pe1": "..@lm_push_end1", "pe2": "..@lm_push_end2"}


def points(labels: dict[str, int] | None) -> str:
    pts = dict(STOCK_POINTS)
    if labels:
        pts.update({k: CAVE + labels[v] for k, v in CAVE_POINTS.items()})
    return ",".join(f"{k}={v:X}" for k, v in pts.items())


def windows(log: Path) -> dict[str, list[float]]:
    """Microsecond windows by kind.  Windows end at the AMX exit 47BF:018E, which both
    builds then run the same way (its dispatch, if any, switches to a task)."""
    out: dict[str, list[float]] = {"tick_off": [], "push_off": [], "tail_off": [], "cave": []}
    entry = push = off = tick = None
    for line in log.read_text().splitlines():
        ts, name = line.split()
        tm = float(ts)
        if name == "entry":
            entry, off = tm, None
        elif name == "on" and entry is not None:
            out["tick_off"].append((tm - entry) * 1e6)
            entry = None
        elif name == "push":
            push = tm
        elif name in ("pe1", "pe2") and push is not None:
            out["push_off"].append((tm - push) * 1e6)
            push = None
        elif name == "off":
            off = tm
        elif name == "tick":
            tick = tm
        elif name == "amx":
            if entry is not None:                 # no STI this tick: off from entry to the exit
                out["tick_off"].append((tm - entry) * 1e6)
                entry = None
            if off is not None:
                out["tail_off"].append((tm - off) * 1e6)
                off = None
            if tick is not None:
                out["cave"].append((tm - tick) * 1e6)
                tick = None
    return out


def stats(xs: list[float]) -> dict:
    if not xs:
        return {}
    xs = sorted(xs)
    pick = lambda q: round(xs[min(len(xs) - 1, int(q * len(xs)))], 1)   # noqa: E731
    return {"n": len(xs), "p50": pick(0.5), "p90": pick(0.9), "p99": pick(0.99), "max": round(xs[-1], 1)}


def run(bios: str = "vailixi") -> dict:
    build = lm.build(t.PORT, OUT / "build")
    labels = {k: int(v, 16) for k, v in build["cave"]["labels"].items()}
    labels.update({k: int(v, 16) for k, v in build["cave"]["probe_labels"].items()})
    smf, _, _, _ = t.walk()
    midi = panel.write_smf(OUT / "walk.mid", smf)
    res = {}
    jobs = {"mirror": (OUT / "build" / "LCDMIRROR_316.img", labels), "stock": (OUT / "build" / "STOCK_316.img", None)}

    def go(name, job):
        img, labs = job
        out = OUT / f"{bios}-{name}"
        mpc3k.run(bios, [t.END], out, floppy=img, panel=midi, env={**t.ENV, "LM_POINTS": points(labs)},
                  extra=["-autoboot_script", str(h.LUA / "lcdmirror_cost.lua")])
        return {k: stats(v) for k, v in windows(out / "lcdmirror_cost.txt").items()}
    res = h.run_parallel(jobs, go, workers=2)
    res["cpu_div"] = t.CPU_DIV
    res["sys_sha256"] = build["sys"]["sha256"]
    (OUT / "cost.json").write_text(json.dumps(res, indent=1) + "\n")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bios", default="vailixi")
    a = ap.parse_args()
    res = run(a.bios)
    for name in ("stock", "mirror"):
        for kind, st in res[name].items():
            if st:
                print(f"{name:7} {kind:9} " + " ".join(f"{k} {v}" for k, v in st.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
