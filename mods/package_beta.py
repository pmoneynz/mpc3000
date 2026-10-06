#!/usr/bin/env python3
"""Package the public beta: STARTUP.SYS alone on the floppy, README, checksums, zip.

    python3 mods/package_beta.py [--name PMONEY_BETA_1.0]

Builds WAVE316.SYS with mods/build_wave316.py (into build/mods), then writes
build/beta/<name>/ with WAVE316.img (STARTUP.SYS only, packed exactly as the
builder packs its test image, without SINE441/STEREO1), STARTUP.SYS,
README.txt (notes/beta/<name>_README.txt) and SHA256SUMS, and
build/beta/<name>.zip.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import build_wave316 as b  # noqa: E402
from mods import buildkit as kit  # noqa: E402


def package(name: str) -> dict:
    manifest = b.build()
    sys_bytes = (b.OUT / "WAVE316.SYS").read_bytes()
    if kit.sha256(sys_bytes) != manifest["sys"]["sha256"]:
        raise RuntimeError("build/mods/WAVE316.SYS does not match the build just made")
    disk, _ = kit.pack_fat12([("STARTUP.SYS", sys_bytes)], oem=b"MPC3K316",
                             volume_id=b"W316", label=b"WAVE316    ")
    readme = ROOT / "notes" / "beta" / f"{name}_README.txt"
    out = ROOT / "build" / "beta" / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    kit.write_atomic(out / "WAVE316.img", disk)
    kit.write_atomic(out / "STARTUP.SYS", sys_bytes)
    shutil.copyfile(readme, out / "README.txt")
    got = subprocess.run(["mtype", "-i", str(out / "WAVE316.img"), "::STARTUP.SYS"],
                         capture_output=True, check=True).stdout
    if got != sys_bytes:
        raise RuntimeError("STARTUP.SYS read back from the image differs")
    sums = {n: kit.sha256((out / n).read_bytes()) for n in ("STARTUP.SYS", "WAVE316.img")}
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()))
    text = readme.read_text()
    for n, h in sums.items():
        if h not in text:
            raise RuntimeError(f"{readme}: README does not list {n} {h}")
    zpath = out.parent / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("README.txt", "STARTUP.SYS", "WAVE316.img", "SHA256SUMS"):
            info = zipfile.ZipInfo(f"{name}/{f}", date_time=(2026, 10, 6, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (out / f).read_bytes())
    return {**sums, "zip": str(zpath), "zip_sha256": kit.sha256(zpath.read_bytes())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="PMONEY_BETA_1.0")
    for k, v in package(ap.parse_args().name).items():
        print(f"{k}: {v}")
