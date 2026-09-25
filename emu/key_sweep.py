"""Drive panel key sequences on the emulated OS and record what changes.

Run: python3 -m emu.key_sweep   (from the repo root)

Each scenario boots Vailixi 3.50, taps keys at the given emulated times and
records: LCD text at SHOT, LCD cursor-address writes (IR 0A/0B) and bytes
the OS writes to the panel link (TE7774 ch2/ch3 data, ports D0/D8) after
the first tap. Output: build/emu/key_sweep/<scenario>/ and summary.txt.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from emu.mpc3k import BUILD, run
from emu.panel import key_tap, write_smf

OUT = BUILD / "emu" / "key_sweep"
T0 = 45.0


def scenario(name: str, taps: list[tuple[int, float]], shot: float) -> dict:
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    events = [e for code, at in taps for e in key_tap(code, at)]
    panel = write_smf(OUT / f"{name}.mid", events) if events else None
    rows = run("vailixi", [shot], d, panel=panel, trace=[0xD0, 0xD8])[-1]["rows"]
    start = taps[0][1] if taps else T0

    def after(path: Path, pred) -> list[str]:
        out = []
        for line in path.read_text().splitlines():
            f = line.split()
            if float(f[0]) >= start and pred(f):
                out.append(" ".join(f[1:]))
        return out

    tx = after(d / "io_trace.log", lambda f: f[2] == "W")
    cursor = after(d / "lcd_io.log", lambda f: f[2] in ("IR=0A", "IR=0B"))
    return {"rows": rows, "tx": tx, "cursor": cursor}


def sweep(cases: dict[str, tuple[list[tuple[int, float]], float]]) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {n: pool.submit(scenario, n, taps, shot) for n, (taps, shot) in cases.items()}
        return {n: f.result() for n, f in futs.items()}


def report(results: dict[str, dict], base: str) -> list[str]:
    b = results[base]
    lines = []
    for name, r in results.items():
        if name == base:
            continue
        changed = [i for i in range(8) if r["rows"][i] != b["rows"][i]]
        lines.append(f"{name}: rows {changed or '-'}  tx {r['tx'] or '-'}  cursor {r['cursor'][-2:] or '-'}")
        for i in changed:
            lines.append(f"    {i}: |{r['rows'][i]}|")
    return lines


def main() -> None:
    cases = {"base": ([], T0 + 2)}
    cases |= {f"{c:02X}": ([(c, T0)], T0 + 2) for c in range(0x40, 0x7A)}
    results = sweep(cases)
    lines = report(results, "base")
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n")
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
