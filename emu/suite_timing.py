"""Where emulator-suite time goes: wall and emulated seconds per MAME run.

    python3 -m emu.suite_timing              # runs started in the last 24 h
    python3 -m emu.suite_timing --hours 72

Reads the run folders emu.mpc3k.run leaves under build/emu: wall time is
from the creation of the run's cfg folder to MAME's last write of
mame_stdout.txt; emulated time is the last probe time in screens.txt.
"Boot" is the emulated time before Soft Key 4 cancels the SCSI search
(TIMELINE.cancel / TIMELINE_316.cancel), which every case repeats.
"""
from __future__ import annotations

import argparse
import collections
import re
import time
from pathlib import Path

from emu.harness import TIMELINE, TIMELINE_316
from emu.mpc3k import BUILD


def runs(since: float) -> list[dict]:
    found = []
    for cfg in (BUILD / "emu").glob("**/cfg"):
        d, stdout, screens = cfg.parent, cfg.parent / "mame_stdout.txt", cfg.parent / "screens.txt"
        if not stdout.exists() or not screens.exists() or cfg.stat().st_birthtime < since:
            continue
        times = [float(t) for t in re.findall(r"^@ ([\d.]+)", screens.read_text(), re.M)]
        if not times:
            continue
        is316 = "316" in str(d.relative_to(BUILD / "emu"))
        cancel = (TIMELINE_316 if is316 else TIMELINE).cancel
        found.append({"suite": d.relative_to(BUILD / "emu").parts[0], "is316": is316,
                      "wall": stdout.stat().st_mtime - cfg.stat().st_birthtime,
                      "emulated": max(times), "boot": min(max(times), cancel)})
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=float, default=24.0)
    rows = runs(time.time() - ap.parse_args().hours * 3600)
    if not rows:
        print("no runs in that window")
        return 1
    wall, emu, boot = (sum(r[k] for r in rows) for k in ("wall", "emulated", "boot"))
    print(f"{len(rows)} runs: wall {wall / 60:.0f} process-min, emulated {emu / 60:.0f} min "
          f"({emu / wall:.2f} emulated s per wall s), boot {boot / emu:.0%} of emulated time")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["suite"]].append(r)
    for suite, v in sorted(by.items(), key=lambda kv: -sum(r["wall"] for r in kv[1])):
        print(f"{suite:28s} {len(v):4d} runs  wall {sum(r['wall'] for r in v) / 60:6.1f} min  "
              f"emulated {sum(r['emulated'] for r in v) / 60:6.1f} min  boot "
              f"{sum(r['boot'] for r in v) / max(1e-9, sum(r['emulated'] for r in v)):4.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
