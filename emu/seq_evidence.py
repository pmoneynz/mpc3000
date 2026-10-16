#!/usr/bin/env python3
"""Emulator traces cited by notes/sequencer_model.md (Vailixi 3.50).

Records a two-bar sequence with pad hits at chosen tick phases, stops, then
plays it from the start, with emu/lua/seq_watch.lua timestamping the tick
counter, transport state and event playback.  Prints:

  - the tick period (TCT1) while idle,
  - the transport state byte [D800] at each change,
  - the position [9232] at which each hit was processed,
  - when each recorded event was played, in ticks after the last start.

Run from the repo root:  python3 -m emu.seq_evidence

RECORD_START and TICK are what the pinned MAME build produced for this key
script; they only place the hits.  The printed phases are measured, so the
result stays valid if the build moves them.
"""

from __future__ import annotations

import bisect

from emu.mpc3k import BUILD, LUA, run
from emu.panel import key_tap, pad_hit, panel_pad, write_smf

RECORD_START = 46.306511
TICK = 5208.5e-6
WATCH = "irq=D838,pos=9232,state=D800,held=975A,played=76FE,next=9242"


def events() -> list[tuple[float, bytes]]:
    ev = (key_tap("rec", 46.0, hold=1.0) + key_tap("play_start", 46.3, hold=0.2)
          + key_tap("stop", 56.0)
          + key_tap("play_start", 57.5, hold=0.2) + key_tap("stop", 62.5))
    # One hit per quarter note of the first pass, 9..15 ticks after the beat.
    for j, late in enumerate(range(9, 16), start=1):
        ev += pad_hit(panel_pad(j), RECORD_START + (96 * j + late) * TICK, 100, 0.05)
    # Second pass (overdub): 4 ticks before the loop point, and 1 tick after
    # the second 1/16 of bar 1.
    ev += pad_hit(panel_pad(8), RECORD_START + (768 + 764) * TICK, 100, 0.05)
    ev += pad_hit(panel_pad(9), RECORD_START + (1536 + 25) * TICK, 100, 0.05)
    return ev


def main() -> int:
    out = BUILD / "emu" / "seq_evidence"
    run("vailixi", [44.0, 63.0], out,
        panel=write_smf(BUILD / "emu" / "seq_evidence.mid", events()),
        extra=["-autoboot_script", str(LUA / "seq_watch.lua")],
        env={"SEQ_WATCH": WATCH})

    rows = [line.split() for line in (out / "seq_watch.log").read_text().splitlines()]
    log = [(float(t), name, int(value, 16)) for t, name, value, _mask in rows]

    irq = [t for t, name, _ in log if name == "irq" and 44.0 < t < 46.0]
    print(f"idle tick period: {(irq[-1] - irq[0]) / (len(irq) - 1) * 1e6:.3f} us")

    states = [(t, value & 0xFF) for t, name, value in log if name == "state"]
    print("transport state [D800]:", [(round(t, 6), value) for t, value in states])
    starts = [t for t, value in states if value in (6, 8)]

    pos = [(t, value) for t, name, value in log if name == "pos"]
    pos_times = [t for t, _ in pos]

    def position(t: float) -> int:
        return pos[bisect.bisect_right(pos_times, t) - 1][1]

    for t, name, value in log:
        if name == "held" and value & 0xFF and t > starts[0]:
            p = position(t)
            print(f"hit processed with [9232]={p:3d} (phase {p % 24:2d} of 24)")
    for t, name, value in log:
        if name == "played" and value == 1 and t > starts[0]:
            since = (t - max(s for s in starts if s <= t)) / TICK
            print(f"event played with [9232]={position(t):3d}, {since:8.2f} ticks after the start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
