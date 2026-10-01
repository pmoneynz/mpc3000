#!/usr/bin/env python3
"""Run the patched MAME mpc3000 driver headless and capture LCD text.

Every run gets fresh NVRAM and cfg directories so results are reproducible.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from emu.romset import build as build_roms

REPO = Path(__file__).resolve().parents[1]
BUILD = REPO / "build"
MAME = Path(os.environ.get("MPC3K_MAME", REPO.parent / "MPC3000_builds" / "mame" / "mpc3k"))
PROBE = Path(__file__).resolve().parent / "probe.lua"
LUA = Path(__file__).resolve().parent / "lua"
DISKS = BUILD / "disks"
M3K316 = REPO / "07-rom" / "v3.16 maintenance upgrade" / "M3K316.SYS"

BOARD_MB = {2: 0x00, 8: 0x01, 32: 0x02}
SIMM_MB = {0: 0x00, 1: 0x10, 4: 0x20}

CFG = """<?xml version="1.0"?>
<mameconfig version="10">
    <system name="mpc3000">
        <input>
            <port tag=":CONFIG" type="CONFIG" mask="3" defvalue="0" value="{board}" />
            <port tag=":CONFIG" type="CONFIG" mask="48" defvalue="0" value="{simm}" />
            <port tag=":CONFIG" type="CONFIG" mask="8" defvalue="0" value="{smpte}" />
        </input>
    </system>
</mameconfig>
"""


def disk(name: str, files: list[tuple[Path, str]]) -> Path:
    """1.44 MB FAT12 image in build/disks/; files land in the root directory in list order."""
    img = DISKS / f"{name}.img"
    DISKS.mkdir(parents=True, exist_ok=True)
    img.unlink(missing_ok=True)
    subprocess.run(["mformat", "-C", "-f", "1440", "-i", str(img), "::"], check=True)
    for src, dst in files:
        subprocess.run(["mcopy", "-i", str(img), str(src), f"::{dst}"], check=True)
    return img


def parse_screens(text: str) -> list[dict]:
    screens = []
    for block in re.split(r"^@ ", text, flags=re.M)[1:]:
        head, *rows = block.rstrip("\n").split("\n")
        screens.append({"time": float(head.split()[0]), "head": head,
                        "rows": [r[1:-1] for r in rows]})
    return screens


def run(bios: str, times: list[float], out: Path, *, board_mb: int = 2, simm_mb: int = 0,
        smpte: bool = False, floppy: Path | None = None, panel: Path | None = None,
        trace: list[int] | None = None, press: list[tuple[float, str, str, float]] | None = None,
        words: list[int] | None = None, extra: list[str] | None = None,
        rompath: Path | None = None) -> list[dict]:
    if out.exists():
        shutil.rmtree(out)
    (out / "cfg").mkdir(parents=True)
    (out / "cfg" / "mpc3000.cfg").write_text(
        CFG.format(board=BOARD_MB[board_mb], simm=SIMM_MB[simm_mb], smpte=8 if smpte else 0))

    cmd = [str(MAME), "mpc3000", "-bios", bios, "-rompath", str(rompath or build_roms()),
           "-video", "none", "-sound", "none", "-nothrottle", "-skip_gameinfo",
           "-cfg_directory", str(out / "cfg"),
           "-nvram_directory", str(out / "nvram"),
           "-snapshot_directory", str(out / "snap"),
           "-autoboot_script", str(PROBE)]
    if floppy is not None:
        cmd += ["-flop", str(floppy.resolve())]
    if panel is not None:
        cmd += ["-midiin3", str(panel.resolve())]
    cmd += extra or []
    env = {"PROBE_OUT": str(out), "PROBE_TIMES": ",".join(str(t) for t in times),
           "PROBE_TRACE": ",".join(f"{p:x}" for p in trace or []),
           "PROBE_PRESS": ";".join(f"{t}:{port}:{field}:{hold}" for t, port, field, hold in press or []),
           "PROBE_WORDS": ",".join(f"{w:x}" for w in words or []),
           "PATH": "/usr/bin:/bin",
           # Headless on macOS: no Cocoa window, no Dock icon, no focus grab.
           "SDL_VIDEO_DRIVER": "dummy", "SDL_MAC_BACKGROUND_APP": "1"}
    proc = subprocess.run(cmd, cwd=out, env=env, capture_output=True, text=True)
    (out / "mame_stdout.txt").write_text(proc.stdout + proc.stderr)
    screens_file = out / "screens.txt"
    if proc.returncode != 0 or not screens_file.exists():
        raise RuntimeError(f"MAME exited {proc.returncode}; see {out / 'mame_stdout.txt'}")
    return parse_screens(screens_file.read_text())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bios", default="vailixi")
    ap.add_argument("--times", default="5,10,40")
    ap.add_argument("--board", type=int, default=2, choices=sorted(BOARD_MB),
                    help="memory board MB: 2 (stock), 8 (EXM3008), 32")
    ap.add_argument("--simm", type=int, default=0, choices=sorted(SIMM_MB),
                    help="MB per SIMM in the pair (0 = empty)")
    ap.add_argument("--smpte", action="store_true")
    ap.add_argument("--floppy", type=Path)
    ap.add_argument("--panel", type=Path, help="SMF of panel-link frames (emu/panel.py)")
    ap.add_argument("--out", type=Path, default=BUILD / "emu" / "last")
    args = ap.parse_args()

    times = [float(t) for t in args.times.split(",")]
    for s in run(args.bios, times, args.out.resolve(), board_mb=args.board, simm_mb=args.simm,
                 smpte=args.smpte, floppy=args.floppy,
                 panel=args.panel):
        print("@", s["head"])
        for r in s["rows"]:
            print("|" + r + "|")
    return 0


if __name__ == "__main__":
    sys.exit(main())
