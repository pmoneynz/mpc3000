"""Soft-key sweep of OS 3.16 pages: does any key leak to "not yet implemented"?

    python3 -m emu.softkey_sweep316 [--sys M3K316.SYS] [--bios v311] [--out DIR]

For each mode key and each menu digit (none, 1-9, 0) one MAME run (resumed
from the fuzz_loaders boot snapshot) presses, for k = 1..4: mode, digit,
Soft Key k, Soft Key k again, captures the screen after each soft key, then
Main Screen.  A capture whose text contains "not yet implemented" (the mode
loop's default arm, 3.16 15AC:0261) is a leak.  Read-only observer.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from emu.fuzz_loaders import M3K316, OUT as FUZZ_OUT, Runner, SNAP_AT, _taps
from emu.mpc3k import run
from emu.panel import write_smf

MODES = ("disk", "program_sounds", "mixer_effects", "midi", "song", "other", "edit", "step_edit",
         "edit_loop", "tempo_sync", "transpose", "2nd_seq", "auto_punch", "count_in", "wait_for_key",
         "erase", "timing_correct", "main_screen", "assign", "help")
DIGITS = ("", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0")
STEP = 6.0


def plan(mode: str, digit: str) -> tuple[list, list[float], list[tuple]]:
    events, times, labels = [], [], []
    t = SNAP_AT + 1.2
    for k in (1, 2, 3, 4):
        keys = [(t, mode)] + ([(t + 1.0, digit)] if digit else [])
        keys += [(t + 2.2, f"soft{k}"), (t + 3.7, f"soft{k}")]
        events += _taps(*keys)
        times += [round(t + 2.0, 3), round(t + 3.5, 3), round(t + 5.2, 3)]
        labels += [(k, "page"), (k, "soft"), (k, "soft-twice")]
        events += _taps((t + 5.4, "main_screen"))
        t += STEP + 0.5
    return events, times, labels


def sweep_one(runner: Runner, mode: str, digit: str) -> dict:
    states, lcd, _ = runner.snapshot()
    events, times, labels = plan(mode, digit)
    name = f"{mode}-{digit or 'none'}"
    d = runner.out / "sweep" / name
    d.mkdir(parents=True, exist_ok=True)
    img = runner._disk(f"sweep-{name}", [], startup=False)
    screens = run(runner.bios, times, d / "mame", floppy=img, panel=write_smf(d / "panel.mid", events),
                  rompath=runner.rompath, board_mb=runner.board_mb,
                  extra=["-state_directory", str(states), "-state", "boot"],
                  env={"PROBE_LCD_SEED": str(lcd), "PROBE_REINSERT": "1"})
    hits = []
    caps = []
    for (k, what), s in zip(labels, screens):
        text = "\n".join(s["rows"])
        caps.append({"soft": k, "when": what, "rows": s["rows"]})
        if "not yet implemented" in text or "function" in s["rows"][0]:
            hits.append({"soft": k, "when": what, "rows": s["rows"]})
    return {"mode": mode, "digit": digit, "hits": hits, "captures": caps}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sys", type=Path, default=M3K316)
    ap.add_argument("--bios", default="v311")
    ap.add_argument("--out", type=Path, default=FUZZ_OUT)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MPC3K_WORKERS", "6")))
    a = ap.parse_args(argv)
    runner = Runner(a.out.resolve(), a.bios, a.sys.resolve())
    jobs = [(m, dg) for m in a.modes.split(",") for dg in DIGITS]
    with ThreadPoolExecutor(a.workers) as pool:
        results = list(pool.map(lambda j: sweep_one(runner, *j), jobs))
    (runner.out / "sweep.json").write_text(json.dumps(results, indent=1))
    for r in results:
        for h in r["hits"]:
            print(f"LEAK {r['mode']} {r['digit'] or '-'} soft{h['soft']} {h['when']}: {h['rows'][0]!r} {h['rows'][1]!r}")
    print(f"{len(results)} runs, {sum(len(r['hits']) for r in results)} leak captures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
