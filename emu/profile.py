#!/usr/bin/env python3
"""Cycle profiles of stock Vailixi 3.50 under representative workloads.

Runs the patched MAME with its NEC cycle profiler (fork `nec_prof`: env
NEC_PROF_DIR / NEC_PROF_WINDOWS) and drives each workload through the panel
link, MIDI In 1 and the floppy.  Every run writes build/emu/prof/<workload>/
with one prof_<i>.txt per window, cov_*.bin coverage maps and windows.json
(window label -> file, start, end).  tools/prof_report.py turns these into
the performance map (notes/performance.md).

    python3 -m emu.profile                 # all workloads, CPU at 16 MHz
    python3 -m emu.profile --only idle,seq
    python3 -m emu.profile --div 1         # MAME's historical 32 MHz core clock

NEC_CPU_DIV=2 is the physical V53 clock (X1 = 32 MHz, CPU = X1 / 2, data
book "Clock Generator"); the pinned fork runs the core at the crystal rate
unless this is set (notes/performance.md §1).  Workload times are emulated
seconds; Soft Key 4 at 20 s cancels the SCSI search (harness.TIMELINE).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from emu import pgm as pgm_fixture
from emu.harness import burst, run_parallel, taps
from emu.mpc3k import BUILD, run
from emu.panel import dial, key_tap, pad_hit, panel_pad, write_smf
from emu.snd import disk, sine, sine441, snd, stereo1

OUT = BUILD / "emu" / "prof"
CANCEL = 20.0


@dataclass
class Workload:
    panel: list[tuple[float, bytes]]
    windows: dict[str, tuple[float, float]]
    floppy: Path | None = None
    midi: list[tuple[float, bytes]] = field(default_factory=list)
    note: str = ""

    @property
    def end(self) -> float:
        return max(e for _, e in self.windows.values()) + 0.5


def boot() -> list[tuple[float, bytes]]:
    return taps((CANCEL, "soft4"))


def pgm_disk(name: str, pads: int = 16, seconds: float = 1.0) -> Path:
    """POLY.PGM (pads 1..`pads` -> TEST) and TEST.SND (a `seconds` sine) on one floppy."""
    d = OUT / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    sound = d / f"{name}.SND"
    sound.write_bytes(snd("TEST", [sine(int(44100 * seconds))]))
    program = d / f"{name}.PGM"
    program.write_bytes(pgm_fixture.for_sound(sound.read_bytes(), pads=range(pads),
                                              program_name="PROF POLY"))
    return disk(f"prof-{name}", [(program, "POLY.PGM"), (sound, "TEST.SND")])


def snd_disk(name: str, planes, **kw) -> Path:
    d = OUT / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    sound = d / f"{name}.SND"
    sound.write_bytes(snd(name.upper()[:16], planes, **kw))
    return disk(f"prof-{name}", [(sound, f"{name.upper()[:8]}.SND")])


def load_pgm(at: float = 23.0) -> list[tuple[float, bytes]]:
    """Disk, 7, <Load> (POLY.PGM is the first file), <Load it> (with its sounds), Main Screen."""
    return taps((at, "disk"), (at + 1.5, "7"), (at + 3.5, "soft1"), (at + 6.5, "soft1"),
                (at + 15.0, "main_screen"))


def load_snd(at: float = 23.0) -> list[tuple[float, bytes]]:
    return taps((at, "disk"), (at + 1.5, "7"), (at + 3.5, "soft1"))


def record_and_play(rec: float, hits: list[tuple[float, int]], stop: float, play: float,
                    stop2: float) -> list[tuple[float, bytes]]:
    """REC (held) + PLAY START records `hits` (time, pad), STOP, PLAY START, STOP."""
    ev = key_tap("rec", rec, hold=1.0) + key_tap("play_start", rec + 0.3, hold=0.2)
    for t, pad in hits:
        ev += pad_hit(panel_pad(pad), t, 100, 0.05)
    ev += key_tap("stop", stop) + key_tap("play_start", play, hold=0.2) + key_tap("stop", stop2)
    return ev


def midi_notes(start: float, end: float, rate: float, notes: int = 16, base: int = 0x23,
               gate: float = 0.05) -> list[tuple[float, bytes]]:
    ev, i, t = [], 0, start
    while t < end:
        n = base + i % notes
        ev.append((t, bytes([0x90, n, 100])))
        ev.append((t + gate, bytes([0x80, n, 0])))
        i += 1
        t = start + i / rate
    return ev


def workloads() -> dict[str, Workload]:
    w: dict[str, Workload] = {}

    w["idle"] = Workload(boot(), {"boot": (0.0, CANCEL), "idle": (30.0, 60.0)},
                         note="Play/Record screen, no input")

    tour = ["disk", "program_sounds", "mixer_effects", "midi", "song", "other", "edit",
            "step_edit", "main_screen", "tempo_sync", "main_screen", "help", "main_screen",
            "disk", "main_screen"]
    ui = boot() + taps(*[(30.0 + i, k) for i, k in enumerate(tour)])
    for i in range(8):
        ui += burst(9 if i % 2 == 0 else -9, 46.0 + i)
    w["ui"] = Workload(ui, {"ui_tour": (30.0, 45.5), "ui_dial": (45.5, 55.0)},
                       note="screen tour (one key per second), then eight 9-step wheel bursts on Play/Record")

    hits = [(30.6 + k * 0.45, 1 + k % 8) for k in range(16)]
    w["seq"] = Workload(boot() + record_and_play(30.0, hits, 40.0, 42.0, 63.0),
                        {"seq_rec": (30.5, 38.0), "seq_play": (43.0, 63.0)},
                        note="2-bar sequence, 16 pad hits recorded (no sounds in memory), then looped playback")

    poly = pgm_disk("poly16")
    storm = [pad_hit(panel_pad(1 + i % 16), 42.0 + i * 0.015, 100, 0.01) for i in range(1000)]
    seq_hits = [(60.6 + k * 0.25, 1 + k % 16) for k in range(32)]
    ev = boot() + load_pgm() + sum(storm, []) + record_and_play(60.0, seq_hits, 70.0, 72.0, 93.0)
    w["poly"] = Workload(ev, {"disk_load_pgm": (26.5, 38.0), "poly_storm": (43.0, 57.0),
                              "seq_poly_play": (73.0, 93.0)}, floppy=poly,
                         note="POLY.PGM: 16 pads -> 1 s sine; pad storm 66 hits/s; 32-hit sequence looped with sounds")

    w["midi"] = Workload(boot() + load_pgm(), {"midi_in": (43.0, 57.0)}, floppy=poly,
                         midi=midi_notes(42.0, 57.0, 20.0),
                         note="MIDI In 1: 20 notes/s on channel 1 (notes 35..50 -> pads 1..16 with sounds)")

    # Edit Sound: Right x10 is Zone end's seconds field, x11 its milliseconds,
    # x16 is Do: (emu/test_harness_lifecycle.py).  Zone end 1.000 s, wheel
    # bursts on the milliseconds field, then Do: REVERSE ZONE (option 9).
    edit = boot() + load_snd() + taps((34.0, "program_sounds"), (35.5, "6"))
    edit += taps(*[(38.0 + i * 0.2, "right") for i in range(10)]) + dial(1, 40.5)
    edit += taps((41.0, "right"))
    for i in range(6):
        edit += burst(9 if i % 2 == 0 else -9, 42.0 + i)
    edit += taps(*[(48.5 + i * 0.2, "right") for i in range(5)])
    edit += dial(9, 50.0) + taps((53.0, "soft4"))
    w["edit"] = Workload(edit, {"disk_load_snd": (26.5, 33.0), "edit_dial": (41.5, 48.0),
                                "edit_reverse": (53.0, 60.0)},
                         floppy=snd_disk("sine441", sine441()),
                         note="Edit Sound on a 55,125-frame sine: wheel bursts on Zone end ms, then Do: REVERSE ZONE of 1.000 s")

    # Disk 3 = Save a Sound; the file exists on the disk, so <Yes> (Soft Key 3) replaces it.
    save = boot() + load_snd() + taps((34.0, "disk"), (35.5, "3"), (38.0, "+"), (40.0, "soft1"),
                                      (42.0, "soft3"))
    w["save"] = Workload(save, {"disk_save_snd": (42.0, 54.0)},
                         floppy=snd_disk("stereo1", stereo1(), vol=77),
                         note="Disk 3 (Save) of the 33,075-frame stereo sound to floppy, replacing the file")
    return w


def execute(name: str, w: Workload, div: int) -> Path:
    out = OUT / name
    env = {"NEC_PROF_DIR": str(out), "NEC_CPU_DIV": str(div),
           "NEC_PROF_WINDOWS": ",".join(f"{s}:{e}" for s, e in w.windows.values())}
    extra = []
    if w.midi:
        extra += ["-midiin1", str(write_smf(OUT / f"{name}-midi.mid", w.midi))]
    run("vailixi", [w.end], out, floppy=w.floppy, panel=write_smf(OUT / f"{name}-panel.mid", w.panel),
        extra=extra, env=env)
    index = {label: {"file": f"prof_{i}.txt", "start": s, "end": e}
             for i, (label, (s, e)) in enumerate(w.windows.items())}
    (out / "windows.json").write_text(json.dumps({"workload": name, "note": w.note, "div": div,
                                                  "windows": index}, indent=1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="", help="comma list of workload names")
    ap.add_argument("--div", type=int, default=2, help="CPU clock = 32 MHz / div (2 = physical)")
    args = ap.parse_args()
    jobs = workloads()
    if args.only:
        jobs = {k: v for k, v in jobs.items() if k in args.only.split(",")}
    OUT.mkdir(parents=True, exist_ok=True)
    results = run_parallel(jobs, lambda name, w: execute(name, w, args.div))
    for name, out in results.items():
        print(name, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
