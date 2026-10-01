#!/usr/bin/env python3
"""Build WAVE plus two disposable sounds for the first hardware bench session.

    python3 mods/build_wave_bench.py

Writes build/mods/WAVEBENCH.img and its SHA-256 manifest. STARTUP.SYS is the
only SYS on the FAT12 image. SND directory entries use the OS name format.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from emu.snd import disk, sine441, snd, stereo1

OUT = ROOT / "build" / "mods"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    subprocess.run([sys.executable, str(ROOT / "mods" / "build_mod_sys.py"), "@mods/WAVE.args"],
                   cwd=ROOT, check=True)
    files = [(OUT / "WAVE.SYS", "STARTUP.SYS")]
    for name, planes in (("SINE441", sine441()), ("STEREO1", stereo1())):
        path = OUT / f"{name}.SND"
        path.write_bytes(snd(name, planes))
        files.append((path, path.name))
    image = OUT / "WAVEBENCH.img"
    image.write_bytes(disk("wave-bench", files).read_bytes())
    manifest = {
        "marker": "WAVE BENCH 05",
        "image": {"name": image.name, "bytes": image.stat().st_size, "sha256": sha256(image)},
        "files": [{"name": name, "bytes": path.stat().st_size, "sha256": sha256(path)}
                  for path, name in files],
        "sources": {name: sha256(ROOT / name) for name in (
            "mods/WAVE.args", "mods/wave.asm", "mods/wave_playback.inc", "mods/wave_numeric.inc", "mods/wave_zones.inc", "mods/wave_chop.inc", "mods/wave_font.inc", "mods/mod_stub.asm",
            "mods/build_mod_sys.py", "mods/build_wave_bench.py", "emu/snd.py", "emu/mpc3k.py")},
    }
    (OUT / "WAVEBENCH.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{image}\nSHA-256 {sha256(image)}")


if __name__ == "__main__":
    main()
