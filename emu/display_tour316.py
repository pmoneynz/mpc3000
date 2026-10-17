#!/usr/bin/env python3
"""Page tour of the 316 payload with the display watch (mods/display316.inc).

    python3 -m emu.display_tour316 OUT_DIR [--bios default,v308]

Boots the current 316 payload (harness.payload: built from this checkout's mods/)
on each BIOS set, loads SINE441.SND, and visits Play/Record (wheel), Edit Sound
(wheel), the wave view and back, Mute groups, Mixer, Disk pages, Other, System
Information, Extra Settings (wheel), Sync, MIDI, Song, Edit, Step Edit and Help,
capturing the LCD (screens.txt, screens_hex.txt, lcd_pixels.txt) 2.2 s after each
input, with emu/lua/display_watch316.lua (invariant I at every put-char entry,
SS of put-char and INT 43, LC7981 writers).  Run it in an unmodified checkout and
in this one and compare with emu.test_display316 (or compare() below): the LCD
must be identical at every probe time.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from emu import harness as h
from emu.panel import dial
from emu.snd import sine441, snd

T0 = h.TIMELINE_316.cancel          # 33.0: Soft Key 4 cancels the SCSI search
STEP = 2.5                          # seconds between inputs; probes 2.2 s after each (6.0 / 5.7 after Disk 7)


def tour() -> tuple[list, list[float], list[str]]:
    """(panel events, probe times, labels)."""
    ev = h.taps((T0, "soft4"), (35.0, "disk"), (35.8, "7"), (39.0, "soft1"))   # load SINE441 by ~44
    times, labels = [44.5], ["loaded"]
    t = 45.0
    steps = [("main_screen", "play_record"), (("dial", 3), "pr_wheel_up"), (("dial", -2), "pr_wheel_down"),
             ("program_sounds", "program_sounds"), ("6", "edit_sound"), (("dial", 1), "es_wheel_sound"),
             ("right", "es_right"), ("right", "es_right2"), (("dial", 2), "es_wheel_field"),
             ("help", "wave_view"), (("dial", 3), "wave_view_wheel"), ("soft4", "wave_view_exit"),
             ("program_sounds", "program_sounds2"), ("0", "mute_groups"), (("dial", 1), "mute_wheel"),
             ("mixer_effects", "mixer"), ("1", "mixer_1"), (("dial", 2), "mixer_wheel"),
             ("disk", "disk"), ("7", "disk_7"), ("main_screen", "play_record2"),
             ("other", "other"), ("soft3", "sysinfo"), ("soft1", "other_back"), ("soft4", "extra_settings"),
             (("dial", 1), "extra_wheel"), (("dial", -1), "extra_wheel_back"),
             ("tempo_sync", "sync"), ("midi", "midi"), ("song", "song"), ("edit", "edit"),
             ("step_edit", "step_edit"), ("main_screen", "play_record3"), ("help", "help"),
             ("main_screen", "play_record4")]
    for what, label in steps:
        if isinstance(what, tuple):
            ev += dial(what[1], t, gap=0.15)
        else:
            ev += h.taps((t, what))
        wait = 6.0 if label == "disk_7" else STEP
        times.append(round(t + wait - 0.3, 3))
        labels.append(label)
        t += wait
    return ev, times, labels


def run(out: Path, bios_sets: tuple[str, ...]) -> dict:
    events, times, labels = tour()
    jobs = {}
    for bios in bios_sets:
        p = h.payload("316", bios)
        jobs[p.label] = p

    def go(label, p):
        runs = out / label
        runs.mkdir(parents=True, exist_ok=True)
        p.record(runs)
        h.run_case(p, runs, "tour", times=times, events=events,
                   files=[(write_sine(out), "SINE441.SND")], parts=["display_watch"])
        return str(runs / "tour")
    result = h.run_parallel(jobs, go)
    (out / "tour.json").write_text(json.dumps({"times": times, "labels": labels, "runs": result}, indent=1))
    return result


def write_sine(out: Path) -> Path:
    path = out / "SINE441.SND"
    if not path.exists():
        path.write_bytes(snd("SINE441", sine441()))
    return path


def watch(run_dir: Path) -> dict:
    """display_watch.txt as a dict."""
    w = {"ss_putc": {}, "ss_puts": {}, "ss_int43": {}, "ax_int43": {}, "writers": {}, "viol": []}
    for line in (run_dir / "display_watch.txt").read_text().splitlines():
        f = line.split()
        if f[0] == "PUTC":
            w.update({("violations" if k == "viol" else k): int(v) for k, v in (x.split("=") for x in f[1:])})
        elif f[0] == "PUTS":
            w.update({"puts_" + k: int(v) for k, v in (x.split("=") for x in f[1:])})
        elif f[0] in ("SS", "AX"):
            k, v = f[2].split("=")
            w[f"{f[0].lower()}_{f[1]}"][k] = int(v)
        elif f[0] == "WRITER":
            w["writers"][f"{f[1]} {f[2]}"] = int(f[3])
        elif f[0] == "VIOL":
            w["viol"].append(line)
    return w


def compare(a: Path, b: Path) -> list[str]:
    """Probe times whose LCD pixels or display RAM differ between two tour runs."""
    diffs = []
    pa, pb = h.lcd_pixels(a), h.lcd_pixels(b)
    if pa.keys() != pb.keys():
        return [f"probe times differ: {sorted(pa)} vs {sorted(pb)}"]
    ha = (a / "screens_hex.txt").read_text().split("@ ")[1:]
    hb = (b / "screens_hex.txt").read_text().split("@ ")[1:]
    for t in pa:
        if pa[t] != pb[t]:
            diffs.append(f"pixels differ at {t}")
    for x, y in zip(ha, hb):
        if x != y:
            diffs.append(f"display RAM differs at {x.split()[0]}")
    return diffs


def digests(run_dir: Path) -> dict[str, str]:
    """Probe time -> sha256 of that capture's LCD pixels and display RAM."""
    import hashlib
    pix = h.lcd_pixels(run_dir)
    ram = {b.split()[0]: b.split("\n", 1)[1] for b in (run_dir / "screens_hex.txt").read_text().split("@ ")[1:]}
    return {t: hashlib.sha256(("\n".join(pix[t]) + "\n" + ram[t]).encode()).hexdigest() for t in pix}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--bios", default=",".join(h.BIOS_316_DEFAULT))
    ap.add_argument("--record", type=Path, help="write the LCD digests of each set to this JSON fixture")
    a = ap.parse_args()
    res = run(a.out.resolve(), tuple(a.bios.split(",")))
    for label, d in res.items():
        print(label, json.dumps(watch(Path(d)), indent=None))
    if a.record:
        events, times, labels = tour()
        a.record.write_text(json.dumps({"labels": dict(zip([f"{t:.3f}" for t in times], labels)),
                                        "digests": {label: digests(Path(d)) for label, d in res.items()}},
                                       indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
