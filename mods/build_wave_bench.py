#!/usr/bin/env python3
"""Build WAVE plus two disposable sounds for the first hardware bench session.

    python3 mods/build_wave_bench.py [--out DIR]

Writes build/mods/WAVEBENCH.img and its SHA-256 manifest. STARTUP.SYS is the
only SYS on the FAT12 image. SND directory entries use the OS name format.
The manifest marker is the one WAVE.args plants; its sources are every file
NASM reads for the cave and stub plus the Python that shapes the bytes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from emu.snd import sine441, snd, stereo1  # noqa: E402
from mods import build_mod_sys as mod  # noqa: E402
from mods import build_wave_physical as profile  # noqa: E402

kit = mod.kit
OUT = ROOT / "build" / "mods"
WAVE_ARGS = ROOT / "mods" / "WAVE.args"


def sha256(path: Path) -> str:
    return kit.sha256(path.read_bytes())


def sources(args) -> list[Path]:
    cave = kit.nasm_deps(args.cave, include=[args.cave.parent]) if args.cave else []
    stub = kit.nasm_deps(mod.STUB_ASM, defines={"DGROUP_BYTES": mod.DGROUP[1] - mod.DGROUP[0]})
    python = [ROOT / "mods/build_mod_sys.py", ROOT / "mods/buildkit.py",
              ROOT / "mods/build_wave_bench.py", ROOT / "mods/build_wave_physical.py",
              ROOT / "emu/snd.py"]
    return list(dict.fromkeys(p.resolve() for p in [WAVE_ARGS, *cave, *stub, *python]))


def main(out: Path = OUT) -> dict:
    args = mod.read_args(WAVE_ARGS)
    marker = profile.marker_text(args.patch).decode()
    subprocess.run([sys.executable, str(ROOT / "mods" / "build_mod_sys.py"), "@mods/WAVE.args",
                    f"--out={out}"], cwd=ROOT, check=True)
    files = [(out / "WAVE.SYS", "STARTUP.SYS")]
    for name, planes in (("SINE441", sine441()), ("STEREO1", stereo1())):
        path = out / f"{name}.SND"
        kit.write_atomic(path, snd(name, planes))
        files.append((path, path.name))
    image = out / "WAVEBENCH.img"
    disk, _ = kit.pack_fat12([(name, path.read_bytes()) for path, name in files], oem=b"MPC3KWAV",
                             volume_id=b"WVBN", label=b"WAVEBENCH  ")
    kit.write_atomic(image, disk)
    manifest = {
        "marker": marker,
        "image": {"name": image.name, "bytes": image.stat().st_size, "sha256": sha256(image)},
        "files": [{"name": name, "bytes": path.stat().st_size, "sha256": sha256(path)}
                  for path, name in files],
        "sources": {kit.relpath(path): sha256(path) for path in sources(args)},
    }
    kit.write_atomic(out / "WAVEBENCH.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(f"{image}\nSHA-256 {sha256(image)}")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT, help="output directory (default build/mods)")
    main(ap.parse_args().out)
