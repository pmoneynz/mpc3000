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


# mtools stamps each image with the host clock: a random volume serial
# (boot sector +27h) and, per directory entry, creation time/date and access
# date (+0Ch..+13h) plus write time/date (+16h..+19h).  The EPROM floppy
# loaders read entry bytes +0Ch..+13h as name characters 9-16: with 3.08 the
# creation-time word at +0Eh decides whether M3K316.SYS loads or the OS stops
# with "software bug of type 11h" (reproduced 8/8 with a captured image; e.g.
# 2D2Ch/2D73h fail, 2C82h/2D82h pass), and 3.50 failed with FD00 on SND disks.
# So test results depended on the time of day the image was made.  Every
# image is normalized: reserved/creation/access bytes zero, a fixed write
# stamp and a fixed serial, so equal inputs give byte-identical images.
VOLUME_SERIAL = b"MPC3"
WRITE_STAMP = bytes.fromhex("0000215c")        # 00:00:00, 2026-01-01
ROOT_DIR, ROOT_ENTRIES = 0x2600, 224


def normalize_image(img: Path) -> None:
    data = bytearray(img.read_bytes())
    data[0x27:0x2B] = VOLUME_SERIAL
    for entry in range(ROOT_DIR, ROOT_DIR + ROOT_ENTRIES * 32, 32):
        if data[entry] == 0:
            break
        if data[entry] == 0xE5:
            continue
        data[entry + 0x0C:entry + 0x14] = bytes(8)
        data[entry + 0x16:entry + 0x1A] = WRITE_STAMP
    img.write_bytes(bytes(data))


def disk(name: str, files: list[tuple[Path, str]]) -> Path:
    """1.44 MB FAT12 image in build/disks/; files land in the root directory in list order.

    The image is deterministic (normalize_image): no host-clock bytes.
    """
    img = DISKS / f"{name}.img"
    DISKS.mkdir(parents=True, exist_ok=True)
    img.unlink(missing_ok=True)
    subprocess.run(["mformat", "-C", "-f", "1440", "-i", str(img), "::"], check=True)
    for src, dst in files:
        subprocess.run(["mcopy", "-i", str(img), str(src), f"::{dst}"], check=True)
    normalize_image(img)
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
        rompath: Path | None = None, env: dict[str, str] | None = None,
        timeout: float | None = None) -> list[dict]:
    """Boot once and return one parsed screen per entry of `times`.

    The probe exits MAME after the last time.  A Lua error or a hang would
    otherwise leave MAME running forever, so the process is killed after
    `timeout` wall seconds (default 240 + 8 per emulated second, scaled by
    MPC3K_TIMEOUT_SCALE) and the run fails with the log location.
    """
    if not times or list(times) != sorted(times):
        raise ValueError(f"times must be non-empty and ascending: {times}")
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
    environment = {"PROBE_OUT": str(out), "PROBE_TIMES": ",".join(str(t) for t in times),
           "PROBE_TRACE": ",".join(f"{p:x}" for p in trace or []),
           "PROBE_PRESS": ";".join(f"{t}:{port}:{field}:{hold}" for t, port, field, hold in press or []),
           "PROBE_WORDS": ",".join(f"{w:x}" for w in words or []),
           "PATH": "/usr/bin:/bin",
           # Headless on macOS: no Cocoa window, no Dock icon, no focus grab.
           "SDL_VIDEO_DRIVER": "dummy", "SDL_MAC_BACKGROUND_APP": "1",
           **(env or {})}
    if timeout is None:
        timeout = (240 + 8 * max(times)) * float(os.environ.get("MPC3K_TIMEOUT_SCALE", "1"))
    try:
        proc = subprocess.run(cmd, cwd=out, env=environment, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:     # subprocess.run has killed MAME
        def text(b):
            return b.decode(errors="replace") if isinstance(b, bytes) else (b or "")
        (out / "mame_stdout.txt").write_text(text(exc.stdout) + text(exc.stderr))
        raise RuntimeError(f"MAME killed after {timeout:.0f} s wall time (probe times up to "
                           f"{max(times)} s never completed; Lua error or hang?); see "
                           f"{out / 'mame_stdout.txt'}") from None
    (out / "mame_stdout.txt").write_text(proc.stdout + proc.stderr)
    screens_file = out / "screens.txt"
    if proc.returncode != 0 or not screens_file.exists():
        raise RuntimeError(f"MAME exited {proc.returncode}; see {out / 'mame_stdout.txt'}")
    screens = parse_screens(screens_file.read_text())
    if len(screens) != len(times):
        raise RuntimeError(f"captured {len(screens)} screens for {len(times)} requested times; "
                           f"see {out / 'mame_stdout.txt'}")
    return screens


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
