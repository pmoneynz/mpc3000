"""Shared fixtures for the WAVE / MUTE GROUPS emulator suites.

Every suite gets its payload from :func:`payload`, which assembles the cave
and builds the SYS from the *current* sources into a test-private directory,
``build/emu/harness-payloads/<source digest>/<profile>/``.  Release artifacts
in ``build/mods`` are never read or written: both builders are called with
their ``out=`` directory set to a private temporary directory.  The payload SHA-256 and
the source digest are printed to stderr and written beside each suite's runs
(``payload-<profile>.json``), and every disk image is read back to prove its
``STARTUP.SYS`` is that payload.

Profiles:

- ``generic``: ``mods/WAVE.args`` on the repository 3.50 interleave, booted
  from the stock romset (``build/roms``).
- ``capture``: ``mods/build_wave_physical.py`` (``WAVE_CAPTURE_20261001``),
  booted from the composite romset: the hash-pinned 2026-10-01 captures over
  the reference interleave (see ``emu/test_wave_physical.py``).

Release mode (``MPC3K_RELEASE=1``) turns every :func:`unavailable` call into
an error, so a missing tool or capture cannot be reported as a skip.  Run
``python3 -m emu.harness_release <suites>`` to get a run that also fails on any
remaining ``SkipTest`` and prints ``skipped=0``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path

from emu.mpc3k import BUILD, MAME, REPO
from emu.panel import dial, key_tap

RELEASE = os.environ.get("MPC3K_RELEASE", "") not in ("", "0")
PAYLOADS = BUILD / "emu" / "harness-payloads"
LUA = REPO / "emu" / "lua"
PROBE = REPO / "emu" / "probe.lua"
SNDDUMP = LUA / "snddump.lua"
WAVE_ARGS = REPO / "mods" / "WAVE.args"
PROFILES = ("capture", "generic")

# Stock DGROUP words in the generic image.  The 2026-10-01 capture's DGROUP
# is two bytes shorter before these objects (notes/wave_physical_profile.md).
DG_KEY_REPEAT = 0xD69A          # D6E0:001B normalized-key repeat count
DG_KEY_QUEUE = 0x12BC           # FB00 queue header: +0 capacity, +2 count
DG_ACTIVE_PROGRAM = 0xE60E


# --------------------------------------------------------------------------
# Skips


def missing_tools() -> list[str]:
    missing = [] if MAME.is_file() else [f"MAME binary {MAME} (set MPC3K_MAME)"]
    return missing + [t for t in ("nasm", "mformat", "mcopy") if shutil.which(t) is None]


def unavailable(reason: str):
    """Skip normally; fail in release mode."""
    if RELEASE:
        raise RuntimeError(f"MPC3K_RELEASE=1 forbids skipping: {reason}")
    raise unittest.SkipTest(reason)


def require_tools() -> None:
    if missing := missing_tools():
        unavailable("emulator tests need: " + ", ".join(missing))


# --------------------------------------------------------------------------
# Payloads


@dataclass(frozen=True)
class Profile:
    name: str
    sys: Path
    map: Path
    rompath: Path
    sha256: str
    source_digest: str

    @property
    def capture(self) -> bool:
        return self.name == "capture"

    def dgroup(self, generic_offset: int) -> int:
        """Translate a generic DGROUP offset to this profile."""
        return generic_offset - 2 if self.capture else generic_offset

    def symbols(self) -> dict[str, int]:
        return symbols(self.map)

    def record(self, runs: Path) -> None:
        runs.mkdir(parents=True, exist_ok=True)
        info = {"profile": self.name, "sys": str(self.sys), "sha256": self.sha256,
                "source_digest": self.source_digest, "rompath": str(self.rompath)}
        (runs / f"payload-{self.name}.json").write_text(json.dumps(info, indent=2) + "\n")
        print(f"[harness] {runs.name}: {self.name} STARTUP.SYS sha256={self.sha256} "
              f"sources={self.source_digest[:16]}", file=sys.stderr)


def symbols(map_path: Path) -> dict[str, int]:
    return {m[3]: int(m[1], 16) for m in re.finditer(
        r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)$", map_path.read_text(), re.M)}


def _sources() -> list[Path]:
    """Everything the two payload builds read (the builders, buildkit, every
    NASM source the cave and stub can include, the ROM inputs)."""
    from mods import build_wave_physical as physical
    files = (sorted((REPO / "mods").glob("*.inc")) + sorted((REPO / "mods").glob("*.asm")) + [
        REPO / "mods/build_mod_sys.py", REPO / "mods/build_wave_physical.py",
        REPO / "mods/buildkit.py", WAVE_ARGS, REPO / "emu/snd.py",
        REPO / "emu/romset.py", REPO / "emu/font/glyphs.json",
        REPO / "07-rom/Vailixi 3.50/3.50 Vailixi (LSE).BIN",
        REPO / "07-rom/Vailixi 3.50/3.50 Vailixi (MSO).BIN"])
    return files + [p for p in (physical.APP, physical.HIGH) if p.is_file()]


def source_digest() -> str:
    h = hashlib.sha256()
    version = subprocess.run(["nasm", "-v"], capture_output=True, text=True).stdout
    h.update(version.encode())
    for path in _sources():
        h.update(str(path.relative_to(REPO)).encode() + b"\0")
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def _build_generic(out: Path) -> Path:
    """mods/build_mod_sys.py @mods/WAVE.args with --out `out` (never build/mods)."""
    from mods import build_mod_sys as mod
    args = mod.read_args(WAVE_ARGS)
    sys_path, _ = mod.build(args.patch, args.cave, args.name, out)
    (out / "wave.map").write_bytes((out / "wave.cave.map").read_bytes())
    return sys_path


def _build_capture(out: Path) -> Path:
    """mods/build_wave_physical.build(out=`out`): every artifact lands in `out`."""
    from mods import build_wave_physical as physical
    physical.build(out=out)
    (out / "wave.map").write_bytes((out / "wavehw.cave.map").read_bytes())
    return out / "WAVEHW.SYS"


def composite_roms(dest: Path) -> Path:
    """Captured ranges over the reference interleave (no file under 07-rom/ written)."""
    from emu.romset import build as romset
    from mods import build_mod_sys as mod
    from mods import build_wave_physical as physical
    shutil.copytree(romset(), dest, dirs_exist_ok=True)
    image = bytearray(mod.linear())
    capture = physical.inputs()
    image[0x20000:0x74000] = capture[0x20000:0x74000]
    image[0x78000:] = capture[0x78000:]
    (dest / "mpc3000/3.50 vailixi lse.bin").write_bytes(image[::2])
    (dest / "mpc3000/3.50 vailixi mso.bin").write_bytes(image[1::2])
    (dest / "composite.json").write_text(json.dumps({
        "physical_ranges": [[0x20000, 0x74000], [0x78000, 0x80000]],
        "reference_substituted_unobserved_ranges": [[0, 0x20000], [0x74000, 0x78000]],
        "sha256": hashlib.sha256(image).hexdigest()}, indent=2) + "\n")
    return dest


_lock = threading.Lock()
_cache: dict[str, Profile] = {}


def payload(name: str) -> Profile:
    """Build (once per process) and return the payload under test for `name`."""
    if name not in PROFILES:
        raise ValueError(f"unknown profile {name!r}")
    with _lock:
        if name in _cache:
            return _cache[name]
        require_tools()
        if name == "capture":
            from mods import build_wave_physical as physical
            if not physical.APP.is_file() or not physical.HIGH.is_file():
                unavailable(f"capture profile needs {physical.APP} and {physical.HIGH}")
        digest = source_digest()
        final = PAYLOADS / digest[:20] / name
        PAYLOADS.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=PAYLOADS))
        try:
            built = _build_generic(tmp) if name == "generic" else _build_capture(tmp)
            sha = hashlib.sha256(built.read_bytes()).hexdigest()
            if name == "capture":
                composite_roms(tmp / "roms")
            if final.exists():
                # Same sources must give the same bytes; otherwise the digest
                # does not tie a run to its sources.
                old = json.loads((final / "payload.json").read_text())
                if old["sha256"] != sha:
                    raise RuntimeError(f"non-deterministic {name} build: {old['sha256']} != {sha}")
            else:
                (tmp / "payload.json").write_text(json.dumps(
                    {"profile": name, "sys": built.name, "sha256": sha,
                     "source_digest": digest}, indent=2) + "\n")
                final.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.rename(tmp, final)
                    tmp = None
                except OSError:
                    if not final.exists():
                        raise
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
        from emu.romset import build as romset
        sys_name = "WAVE.SYS" if name == "generic" else "WAVEHW.SYS"
        profile = Profile(name=name, sys=final / sys_name, map=final / "wave.map",
                          rompath=romset() if name == "generic" else final / "roms",
                          sha256=sha, source_digest=digest)
        if hashlib.sha256(profile.sys.read_bytes()).hexdigest() != sha:
            raise RuntimeError(f"{profile.sys} changed after the build")
        _cache[name] = profile
        return profile


def wave_disk(profile: Profile, name: str, files: list[tuple[Path, str]] = ()) -> Path:
    """Floppy with the payload as STARTUP.SYS; its readback must hash to the payload."""
    from emu.snd import disk
    image = disk(f"{profile.name}-{name}", [(profile.sys, "STARTUP.SYS"), *files])
    got = subprocess.run(["mtype", "-i", str(image), "::STARTUP.SYS"],
                         capture_output=True, check=True).stdout
    if hashlib.sha256(got).hexdigest() != profile.sha256:
        raise RuntimeError(f"{image}: STARTUP.SYS is not payload {profile.sha256}")
    return image


# --------------------------------------------------------------------------
# Panel timeline
#
# The boot from a STARTUP.SYS floppy reaches the SCSI search well before
# 20 s.  Soft Key 4 cancels it, which puts every menu in reach by ~23 s
# (instead of the ~60 s SCSI time-out).  Times below are emulated seconds.

CANCEL_SCSI = 20.0


def taps(*items: tuple[float, str], hold: float = 0.1) -> list[tuple[float, bytes]]:
    return [event for at, key in items for event in key_tap(key, at, hold)]


def burst(steps: int, at: float) -> list[tuple[float, bytes]]:
    """Wheel steps 1 ms apart: back to back on the 31250-baud link (3 bytes ~ 0.96 ms)."""
    return dial(steps, at, gap=0.001)


def load_sound_events(at: float = 23.0) -> list[tuple[float, bytes]]:
    """Cancel SCSI, then Disk / 7 / <Load> of the disk's first sound (Load at at+3.5)."""
    return taps((CANCEL_SCSI, "soft4"), (at, "disk"), (at + 1.5, "7"), (at + 3.5, "soft1"))


def open_view_events(at: float = 34.0) -> list[tuple[float, bytes]]:
    """Program/Sounds / 6 / Help: the wave view is drawn by at + 4."""
    return taps((at, "program_sounds"), (at + 1.5, "6"), (at + 3.5, "help"))


# A sound of up to ~170 KB loaded with load_sound_events() is in RAM by 32 s
# (108 KB SINE441: <Load> at 26.5 s, done by 31 s).  open_view_events() at
# 34 s then shows the wave view from VIEW = 40 s.  The suites used to idle
# until the SCSI time-out; their old timeline is this one plus 40 s.
VIEW = 40.0


def wave_events(*more: list[tuple[float, bytes]], load_at: float = 23.0,
                view_at: float = 34.0) -> list[tuple[float, bytes]]:
    """Load the disk's sound, open its wave view, then `more` events."""
    events = load_sound_events(load_at) + open_view_events(view_at)
    for part in more:
        events += part
    return events


def label(t: float) -> str:
    """File label used by the Lua observers for a probe time (Lua '%g')."""
    return f"{t:g}"


# --------------------------------------------------------------------------
# Logs


def lcd_pixels(run_dir: Path) -> dict[str, list[str]]:
    blocks = (run_dir / "lcd_pixels.txt").read_text().split("@ ")[1:]
    return {b.split()[0]: b.splitlines()[1:65] for b in blocks}


def blits(run_dir: Path, start: float, end: float) -> int:
    """Full-screen LCD blits (C4C8 cursor reset, IR 0A = 00) in [start, end)."""
    count = 0
    for line in (run_dir / "lcd_io.log").read_text().splitlines():
        f = line.split()
        if len(f) >= 4 and f[2] == "IR=0A" and f[3] == "D=00" and start <= float(f[0]) < end:
            count += 1
    return count


def parse_kv_log(path: Path, hex_keys: set[str] = frozenset(),
                 text_keys: set[str] = frozenset()) -> list[tuple[str, dict]]:
    """Parse 'KIND k=v ...' lines; t is float, hex_keys base 16, text_keys verbatim."""
    events = []
    for line in path.read_text().splitlines():
        kind, *fields = line.split()
        values: dict = {}
        for field in fields:
            key, value = field.split("=", 1)
            if key == "t":
                values[key] = float(value)
            elif key in text_keys:
                values[key] = value
            elif key in hex_keys:
                values[key] = int(value, 16)
            else:
                values[key] = int(value)
        events.append((kind, values))
    return events


def require_marker(path: Path, marker: str) -> str:
    """The run has exited, so the log is complete; a missing marker is a failed probe."""
    text = path.read_text() if path.is_file() else ""
    if marker not in text:
        raise RuntimeError(f"{path}: probe never wrote {marker!r}")
    return text


# --------------------------------------------------------------------------
# Observers and runs


def observer(profile: Profile, path: Path, parts: list[str], prelude: str = "") -> Path:
    """One autoboot script: a preamble, then each emu/lua/<part>.lua, then probe.lua.

    The preamble defines CAVE (every symbol of this profile's assembled map),
    DG (this profile's DGROUP offsets) and the table names the individual
    observers expect.  Each part runs in its own `do` block with its trailing
    chain `dofile` removed, so the parts can be combined freely.  All parts
    only install taps and read memory; none writes MPC state.  `prelude` is
    a suite's own read-only Lua, run in its own block after the preamble.
    """
    cave = profile.symbols()
    lines = ["CAVE = {" + ",".join(f'["{k}"]={v}' for k, v in sorted(cave.items())) + "}",
             f"DG = {{key_repeat={profile.dgroup(DG_KEY_REPEAT)},"
             f"key_queue={profile.dgroup(DG_KEY_QUEUE)},"
             f"active_program={profile.dgroup(DG_ACTIVE_PROGRAM)}}}",
             "WAVE_ZONE_OFFSETS = CAVE", "MUTE_OFFSETS = CAVE", "MUTE_VOICE_OFFSETS = CAVE",
             "MUTE_PROGRAM_OFFSET = DG.active_program"]
    if prelude:
        lines += ["do -- suite prelude", *prelude.splitlines(), "end"]
    for part in parts:
        body = [line for line in (LUA / f"{part}.lua").read_text().splitlines()
                if not line.startswith("dofile(")]
        lines += [f"do -- {part}.lua", *body, "end"]
    lines.append(f'dofile("{PROBE.as_posix()}")')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def run_case(profile: Profile, runs: Path, name: str, *, times: list[float],
             events: list[tuple[float, bytes]], files: list[tuple[Path, str]] = (),
             parts: list[str] = ("repeat_watch", "wave_zones", "snddump"),
             env: dict[str, str] | None = None, extra: list[str] = (),
             prelude: str = "", **kwargs) -> list[dict]:
    """Boot this profile with its payload disk, drive the panel link, observe."""
    from emu.mpc3k import run
    from emu.panel import write_smf
    case_dir = runs / name
    image = wave_disk(profile, f"{runs.name}-{name}", list(files))
    panel = write_smf(runs / f"{name}.mid", events)
    script = observer(profile, runs / f"{name}.lua", list(parts), prelude)
    return run("vailixi", times, case_dir, floppy=image, panel=panel, rompath=profile.rompath,
               extra=["-autoboot_script", str(script), *extra], env=env, **kwargs)


def run_parallel(jobs: dict, fn, workers: int = 4) -> dict:
    """Run fn(name, job) for each job on a small pool; returns {name: result}."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {name: pool.submit(fn, name, job) for name, job in jobs.items()}
        return {name: future.result() for name, future in futures.items()}


def repeats(run_dir: Path, symbol: str = "key_repeat", start: float = 0.0,
            end: float = float("inf")) -> list[int]:
    """Repeat counts the cave stored for each key it processed in [start, end)."""
    return [v["value"] for kind, v in parse_kv_log(run_dir / "repeat.log", hex_keys={"mask"}, text_keys={"sym"})
            if kind == "REPEAT" and v["sym"] == symbol and start <= v["t"] < end]


def zone_rows(run_dir: Path) -> dict[float, dict]:
    """wave_zones.lua snapshots keyed by probe time (rounded to ms)."""
    return {round(r["time"], 3): r for line in (run_dir / "zones.jsonl").read_text().splitlines()
            if (r := json.loads(line))}


def sound_records(run_dir: Path, t: float) -> dict[int, dict]:
    """Decoded sound directory captured by wave_zones.lua at probe time t."""
    import struct
    data = (run_dir / f"records_{label(t)}.bin").read_bytes()
    return {i: {"name": r[:16].decode().rstrip(" \0"), "volume": r[0x11],
                "tune": struct.unpack_from("b", r, 0x12)[0], "stereo": r[0x13],
                "start": struct.unpack_from("<I", r, 0x14)[0],
                "end": struct.unpack_from("<I", r, 0x18)[0],
                "length": struct.unpack_from("<I", r, 0x1C)[0],
                "wave": struct.unpack_from("<I", r, 0x20)[0]}
            for i in range(128) if (r := data[i * 36:(i + 1) * 36])[0]}


def pcm(run_dir: Path, t: float, index: int) -> bytes:
    return (run_dir / f"wave_{label(t)}_idx{index}.bin").read_bytes()


# --------------------------------------------------------------------------
# Profile-parameterised suites

GENERIC_ALL = os.environ.get("MPC3K_GENERIC", "") == "all"


@dataclass
class Case:
    events: list
    times: list[float]
    files: list = ()
    parts: tuple = ("repeat_watch", "wave_zones", "snddump")
    env: dict | None = None
    kwargs: dict | None = None
    prelude: str = ""


class EmuSuite(unittest.TestCase):
    """Runs `cases()` on the capture profile and the GENERIC subset on generic.

    MPC3K_GENERIC=all runs every case on both profiles.  Results are keyed by
    (profile, case); each case directory is RUNS/<profile>/<case>.
    """
    RUNS: Path
    GENERIC: frozenset = frozenset()
    CAPTURE_ONLY: frozenset = frozenset()     # cases whose expectations are capture-specific
    WORKERS = 4
    results: dict = {}
    profiles: dict = {}

    @classmethod
    def cases(cls, profile: Profile, runs: Path) -> dict[str, Case]:
        raise NotImplementedError

    @classmethod
    def setUpClass(cls) -> None:
        require_tools()
        jobs = {}
        cls.profiles = {}
        # Development aid: MPC3K_CASES=a,b runs only those cases (others then
        # fail as "did not run"); MPC3K_PROFILES=generic runs one profile.
        only = set(filter(None, os.environ.get("MPC3K_CASES", "").split(",")))
        wanted = set(filter(None, os.environ.get("MPC3K_PROFILES", "").split(","))) or set(PROFILES)
        for name in PROFILES:
            if name not in wanted:
                continue
            profile = payload(name)
            cls.profiles[name] = profile
            runs = cls.RUNS / name
            runs.mkdir(parents=True, exist_ok=True)
            profile.record(cls.RUNS)
            for case, spec in cls.cases(profile, runs).items():
                if only and case not in only:
                    continue
                if name == "generic" and case in cls.CAPTURE_ONLY:
                    continue
                if name == "generic" and not (GENERIC_ALL or case in cls.GENERIC):
                    continue
                jobs[(name, case)] = (profile, runs, spec)

        def go(key, job):
            profile, runs, spec = job
            return run_case(profile, runs, key[1], times=spec.times, events=spec.events,
                            files=list(spec.files), parts=spec.parts, env=spec.env,
                            prelude=spec.prelude, **(spec.kwargs or {}))
        cls.results = run_parallel(jobs, go, cls.WORKERS)

    def each(self, case: str) -> list[tuple[str, Path, list[dict]]]:
        found = [(p, self.RUNS / p / c, s) for (p, c), s in self.results.items() if c == case]
        self.assertTrue(found, f"case {case} did not run")
        return found
