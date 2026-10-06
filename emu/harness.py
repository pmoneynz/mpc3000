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
- ``316``: ``mods/build_wave316.py`` (``WAVE316.SYS``, OS 3.16 Route C),
  booted from the stock romset on any of the BIOS sets ``default`` (3.12),
  ``vailixi``, ``v311`` and ``v308``: ``payload("316", bios=...)``.  The
  EPROM loader puts it at load segment ``L`` (0x6900 or 0x7000); the
  profile exposes ``L``, the cave home, DGROUP translation and relocated
  3.16 addresses (notes/port_316.md).

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
PROFILES = ("capture", "generic")          # what EmuSuite runs unless a suite opts in to 316
ALL_PROFILES = PROFILES + ("316",)

# OS 3.16 (Route C).  Load segment L per MAME BIOS set (notes/port_316.md,
# notes/floppy_loader.md): 3.12 and 3.50 load at 6900h, 3.08 and 3.11 at 7000h.
M3K316 = REPO / "07-rom" / "v3.16 maintenance upgrade" / "M3K316.SYS"
WAVE316_ARGS = REPO / "mods" / "WAVE316.args"
PROFILE_316 = REPO / "mods" / "profile_316.inc"
LOAD_SEGMENTS = {"default": 0x6900, "vailixi": 0x6900, "v311": 0x7000, "v308": 0x7000}
BIOS_316 = tuple(LOAD_SEGMENTS)
PHYS_316 = 0x300000             # 3.16 keeps the loader's third PGR: physical = 0x300000 + logical
CAVE_HOME_316 = 0x7E00          # relative paragraph of the cave home (mods/profile_316.inc)
DGROUP_316 = 0x609C             # relative DGROUP segment
SND_SEG_316 = 0x539D            # relative sound segment (generic A2AE)

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
class Runtime:
    """A 3.16 relative seg:off after the EPROM loader added L to its segment."""
    cs: int
    ip: int
    phys: int           # 0x300000 + cs*16 + ip (third PGR, XA on)

    def __str__(self) -> str:
        return f"{self.cs:04X}:{self.ip:04X} (phys 0x{self.phys:06X})"


@dataclass(frozen=True)
class Profile:
    name: str
    sys: Path
    map: Path
    rompath: Path
    sha256: str
    source_digest: str
    bios: str = "vailixi"       # MAME BIOS set the runs boot (316: any of BIOS_316)

    @property
    def capture(self) -> bool:
        return self.name == "capture"

    @property
    def is316(self) -> bool:
        return self.name == "316"

    @property
    def label(self) -> str:
        """Run/result key: the profile name, plus the BIOS set for 316 ('316-v308')."""
        return f"316-{self.bios}" if self.is316 else self.name

    @property
    def timeline(self) -> "Timeline":
        return TIMELINE_316 if self.is316 else TIMELINE

    @property
    def view(self) -> float:
        """Time from which wave_events() shows the wave view of a ~170 KB sound."""
        return self.timeline.view

    def _need316(self, what: str) -> None:
        if not self.is316:
            raise ValueError(f"{what} is defined for the 316 profile only, not {self.name!r}")

    @property
    def load_segment(self) -> int:
        """L: the EPROM loader's load segment for this BIOS set."""
        self._need316("load_segment")
        return LOAD_SEGMENTS[self.bios]

    @property
    def cave_segment(self) -> int:
        """Runtime segment of the cave (its map offsets are CS-relative)."""
        return (self.load_segment + CAVE_HOME_316) & 0xFFFF if self.is316 else 0xF07D

    @property
    def cave_phys(self) -> int:
        """Physical address of cave offset 0 (316: 0x300000 + L*16 + 0x7E000)."""
        return PHYS_316 + self.cave_segment * 16 if self.is316 else 0x3F07D0

    @property
    def dgroup_segment(self) -> int:
        return (self.load_segment + DGROUP_316) & 0xFFFF if self.is316 else 0x8010

    @property
    def sound_segment(self) -> int:
        """Segment of the sound buffer / records (records at +4800h)."""
        return (self.load_segment + SND_SEG_316) & 0xFFFF if self.is316 else 0xA2AE

    def dgroup(self, generic_offset: int) -> int:
        """Translate a generic DGROUP offset to this profile.

        316: through the generic -> 3.16 pairs of mods/profile_316.inc
        (``NAME equ 0x<3.16> ; <generic>: ...``); an offset without a pair
        raises KeyError rather than guessing."""
        if self.is316:
            table = dgroup316_table()
            if generic_offset not in table:
                raise KeyError(f"generic DGROUP 0x{generic_offset:04X} has no 3.16 pair in {PROFILE_316.name}")
            return table[generic_offset]
        return generic_offset - 2 if self.capture else generic_offset

    def dgroup_phys(self, generic_offset: int) -> int:
        """316: physical address of a generic DGROUP offset, 0x300000 + (L+609C)*16 + offset."""
        self._need316("dgroup_phys")
        return PHYS_316 + self.dgroup_segment * 16 + self.dgroup(generic_offset)

    def runtime(self, seg: int, off: int) -> Runtime:
        """A 3.16 relative seg:off (notes/port_316.md) as runtime CS:IP and physical address."""
        self._need316("runtime")
        cs = (self.load_segment + seg) & 0xFFFF
        return Runtime(cs, off, PHYS_316 + ((cs * 16 + off) & 0xFFFFF))

    def target(self, name: str) -> Runtime:
        """Runtime address of a profile_316.inc stock target, e.g. 'T_B99A_0AF3'."""
        seg, off = targets316()[name]
        return self.runtime(seg, off)

    def image_phys(self, image_offset: int) -> int:
        """Physical address of a 3.16 load-image offset (0x300000 + L*16 + offset)."""
        self._need316("image_phys")
        return PHYS_316 + self.load_segment * 16 + image_offset

    def relocated_image(self) -> bytes:
        """This payload's load image with every MZ relocation applied for L (no entry copy)."""
        self._need316("relocated_image")
        from mods import route_c as rc
        mz = rc.MZ.parse(self.sys.read_bytes())
        image = bytearray(mz.image)
        for off, seg in mz.relocs:
            a = rc.lin(seg, off)
            word = int.from_bytes(image[a:a + 2], "little")
            image[a:a + 2] = ((word + self.load_segment) & 0xFFFF).to_bytes(2, "little")
        return bytes(image)

    def cave_home_image(self) -> bytes:
        """The cave as the entry routine leaves it at its home (loader simulation)."""
        self._need316("cave_home_image")
        from mods import route_c as rc
        size = cave_end(self.map)
        mem, _ = rc.simulate(self.sys.read_bytes(), self.load_segment, home=CAVE_HOME_316, cave_len=size)
        home = (self.load_segment + CAVE_HOME_316) * 16
        return bytes(mem[home:home + size])

    def symbols(self) -> dict[str, int]:
        return symbols(self.map)

    def record(self, runs: Path) -> None:
        runs.mkdir(parents=True, exist_ok=True)
        info = {"profile": self.name, "sys": str(self.sys), "sha256": self.sha256,
                "source_digest": self.source_digest, "rompath": str(self.rompath)}
        if self.is316:
            info.update(bios=self.bios, load_segment=f"{self.load_segment:04X}")
        (runs / f"payload-{self.label}.json").write_text(json.dumps(info, indent=2) + "\n")
        print(f"[harness] {runs.name}: {self.label} STARTUP.SYS sha256={self.sha256} "
              f"sources={self.source_digest[:16]}", file=sys.stderr)


def symbols(map_path: Path) -> dict[str, int]:
    return {m[3]: int(m[1], 16) for m in re.finditer(
        r"^\s*([0-9A-Fa-f]+)\s+([0-9A-Fa-f]+)\s+(\S+)$", map_path.read_text(), re.M)}


def cave_end(map_path: Path) -> int:
    return symbols(map_path)["cave_end"]


# Equates of profile_316.inc that carry a generic address but are not DGROUP
# offsets (segments and a code offset).
_NOT_DGROUP_316 = {"SND_SEG", "DGROUP_SEG", "PLAYER_SEG", "CAVE_SEG", "CAVE_HOME", "PLAYER_CE9_RET",
                   "POOL_INIT_IMM"}


def dgroup316_table() -> dict[int, int]:
    """Generic Vailixi DGROUP offset -> 3.16 DGROUP offset, from mods/profile_316.inc."""
    table: dict[int, int] = {}
    for m in re.finditer(r"^(\w+)\s+equ\s+0x([0-9A-Fa-f]+)\s*;\s*([0-9A-F]{4}):",
                         PROFILE_316.read_text(), re.M):
        if m[1] in _NOT_DGROUP_316:
            continue
        generic, s316 = int(m[3], 16), int(m[2], 16)
        if table.setdefault(generic, s316) != s316:
            raise ValueError(f"{PROFILE_316.name}: generic 0x{generic:04X} maps to "
                             f"0x{table[generic]:04X} and 0x{s316:04X}")
    return table


def targets316() -> dict[str, tuple[int, int]]:
    """profile_316.inc stock targets: T_SSSS_OOOO -> 3.16 relative (seg, off)."""
    return {m[1]: (int(m[2], 16), int(m[3], 16)) for m in re.finditer(
        r"^%define (T_[0-9A-F]{4}_[0-9A-F]{4}) 0x([0-9A-F]+):0x([0-9A-F]+)", PROFILE_316.read_text(), re.M)}


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


def _sources316() -> list[Path]:
    """Everything mods/build_wave316.py reads: route_c, the entry and profile
    includes (mods/*.inc), the cave sources, WAVE316.args, M3K316.SYS, and the
    3.50 chips its stock-target shape check disassembles."""
    return (sorted((REPO / "mods").glob("*.inc")) + sorted((REPO / "mods").glob("*.asm")) + [
        REPO / "mods/build_wave316.py", REPO / "mods/route_c.py", REPO / "mods/build_mod_sys.py",
        REPO / "mods/buildkit.py", WAVE316_ARGS, M3K316, REPO / "emu/snd.py",
        REPO / "emu/romset.py", REPO / "emu/font/glyphs.json",
        REPO / "07-rom/Vailixi 3.50/3.50 Vailixi (LSE).BIN",
        REPO / "07-rom/Vailixi 3.50/3.50 Vailixi (MSO).BIN"])


def source_digest(profile: str | None = None) -> str:
    """Digest of a payload's inputs.  The capture and generic profiles share
    one digest (unchanged by the 316 profile); 316 has its own, which also
    covers the ndisasm version its builder uses."""
    h = hashlib.sha256()
    version = subprocess.run(["nasm", "-v"], capture_output=True, text=True).stdout
    h.update(version.encode())
    if profile == "316":
        h.update(b"316\0" + subprocess.run(["ndisasm", "-v"], capture_output=True, text=True).stdout.encode())
    for path in (_sources316() if profile == "316" else _sources()):
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


def _build_316(out: Path) -> Path:
    """mods/build_wave316.build(out=`out`): WAVE316.SYS and its cave map land in `out`."""
    from mods import build_wave316 as b316
    b316.build(out=out)
    (out / "wave.map").write_bytes((out / "wave316.cave.map").read_bytes())
    return out / "WAVE316.SYS"


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


def payload(name: str, bios: str | None = None) -> Profile:
    """Build (once per process) and return the payload under test for `name`.

    `bios` selects the MAME BIOS set the runs boot: the 316 profile takes any
    of BIOS_316 (default 'default'); capture and generic run on 'vailixi' only."""
    if name not in ALL_PROFILES:
        raise ValueError(f"unknown profile {name!r}")
    if name == "316":
        bios = bios or "default"
        if bios not in BIOS_316:
            raise ValueError(f"316 profile: unknown BIOS set {bios!r} (one of {BIOS_316})")
    elif bios not in (None, "vailixi"):
        raise ValueError(f"profile {name!r} runs on the vailixi BIOS set only")
    profile = _payload(name)
    if name == "316":
        from dataclasses import replace
        profile = replace(profile, bios=bios)
    return profile


def _payload(name: str) -> Profile:
    with _lock:
        if name in _cache:
            return _cache[name]
        require_tools()
        if name == "316":
            if shutil.which("ndisasm") is None:
                unavailable("316 profile needs ndisasm")
            if not M3K316.is_file():
                unavailable(f"316 profile needs {M3K316}")
        if name == "capture":
            from mods import build_wave_physical as physical
            if not physical.APP.is_file() or not physical.HIGH.is_file():
                unavailable(f"capture profile needs {physical.APP} and {physical.HIGH}")
        digest = source_digest(name)
        final = PAYLOADS / digest[:20] / name
        PAYLOADS.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=PAYLOADS))
        try:
            builder = {"generic": _build_generic, "capture": _build_capture, "316": _build_316}[name]
            built = builder(tmp)
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
        sys_name = {"generic": "WAVE.SYS", "capture": "WAVEHW.SYS", "316": "WAVE316.SYS"}[name]
        profile = Profile(name=name, sys=final / sys_name, map=final / "wave.map",
                          rompath=final / "roms" if name == "capture" else romset(),
                          sha256=sha, source_digest=digest)
        if hashlib.sha256(profile.sys.read_bytes()).hexdigest() != sha:
            raise RuntimeError(f"{profile.sys} changed after the build")
        _cache[name] = profile
        return profile


def wave_disk(profile: Profile, name: str, files: list[tuple[Path, str]] = ()) -> Path:
    """Floppy with the payload as STARTUP.SYS; its readback must hash to the payload."""
    from emu.snd import disk
    image = disk(f"{profile.label}-{name}", [(profile.sys, "STARTUP.SYS"), *files])
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


@dataclass(frozen=True)
class Timeline:
    """Boot / load / wave-view key times of one OS (emulated seconds)."""
    cancel: float               # Soft Key 4 cancels the SCSI search
    load_at: float              # Disk
    load_seven: float           # Disk -> 7
    load_key: float             # Disk -> Soft Key 1 <Load> (first file of the list)
    view_at: float              # Program/Sounds
    view_six: float             # Program/Sounds -> 6 (Edit Sound)
    view_help: float            # Program/Sounds -> Help (wave view)
    view: float                 # wave view on screen from here (default view_at)


TIMELINE = Timeline(CANCEL_SCSI, 23.0, 1.5, 3.5, 34.0, 1.5, 3.5, 40.0)

# OS 3.16 on any BIOS set (scratchpad timeline_316.py, verified on screen on
# all four sets; emu/test_port316_boot.py re-checks it): banner 31 s, SCSI
# search 32.6 s, Soft Key 4 at 33.0 -> Play/Record by 33.6.  Disk at 35.0,
# 7 at 35.8, the file list is ready 3.5 s after Disk, <Load> at 39.0 (108K
# SINE441 loaded by 43.8, 130K by 45.0).  Program/Sounds 46.0, 6 at 46.8
# (Edit Sound by 47.5), Help at 49.0: wave view by 52.
CANCEL_SCSI_316 = 33.0
TIMELINE_316 = Timeline(CANCEL_SCSI_316, 35.0, 0.8, 4.0, 46.0, 0.8, 3.0, 52.0)
VIEW_316 = TIMELINE_316.view


def timeline(profile: "Profile | None" = None) -> Timeline:
    return TIMELINE if profile is None else profile.timeline


def taps(*items: tuple[float, str], hold: float = 0.1) -> list[tuple[float, bytes]]:
    return [event for at, key in items for event in key_tap(key, at, hold)]


def burst(steps: int, at: float) -> list[tuple[float, bytes]]:
    """Wheel steps 1 ms apart: back to back on the 31250-baud link (3 bytes ~ 0.96 ms)."""
    return dial(steps, at, gap=0.001)


def load_sound_events(at: float | None = None, profile: "Profile | None" = None) -> list[tuple[float, bytes]]:
    """Cancel SCSI, then Disk / 7 / <Load> of the disk's first sound.

    Vailixi profiles: Disk at `at` (23), 7 at+1.5, <Load> at+3.5.  316:
    Disk at `at` (35), 7 at+0.8, <Load> at+4.0."""
    tl = timeline(profile)
    at = tl.load_at if at is None else at
    return taps((tl.cancel, "soft4"), (at, "disk"), (at + tl.load_seven, "7"), (at + tl.load_key, "soft1"))


def open_view_events(at: float | None = None, profile: "Profile | None" = None) -> list[tuple[float, bytes]]:
    """Program/Sounds / 6 / Help: the wave view is drawn by at + 4 (316: at + 6)."""
    tl = timeline(profile)
    at = tl.view_at if at is None else at
    return taps((at, "program_sounds"), (at + tl.view_six, "6"), (at + tl.view_help, "help"))


# A sound of up to ~170 KB loaded with load_sound_events() is in RAM by 32 s
# (108 KB SINE441: <Load> at 26.5 s, done by 31 s).  open_view_events() at
# 34 s then shows the wave view from VIEW = 40 s.  The suites used to idle
# until the SCSI time-out; their old timeline is this one plus 40 s.
VIEW = 40.0


def wave_events(*more: list[tuple[float, bytes]], load_at: float | None = None,
                view_at: float | None = None, profile: "Profile | None" = None) -> list[tuple[float, bytes]]:
    """Load the disk's sound, open its wave view, then `more` events.

    The view is open from profile.view (VIEW = 40 for Vailixi, VIEW_316 = 52)."""
    events = load_sound_events(load_at, profile) + open_view_events(view_at, profile)
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
    if profile.is316:
        # Runtime segments and physical bases for the *316.lua parts.
        lines += [f"LOAD_SEG = 0x{profile.load_segment:04X}",
                  f"CAVE_SEG = 0x{profile.cave_segment:04X}", f"CAVE_PHYS = 0x{profile.cave_phys:06X}",
                  f"DG_SEG = 0x{profile.dgroup_segment:04X}",
                  f"DG_PHYS = 0x{PHYS_316 + profile.dgroup_segment * 16:06X}",
                  f"SND_SEG = 0x{profile.sound_segment:04X}",
                  f"IMAGE_PHYS = 0x{profile.image_phys(0):06X}", f"CAVE_LEN = {cave_end(profile.map)}"]
    if prelude:
        lines += ["do -- suite prelude", *prelude.splitlines(), "end"]
    for part in parts:
        # The 316 profile reads its own addresses: part X is emu/lua/X316.lua
        # (a part without a 316 port fails here instead of reading Vailixi RAM).
        source = LUA / (f"{part}316.lua" if profile.is316 else f"{part}.lua")
        if not source.is_file():
            raise FileNotFoundError(f"observer part {part!r} has no {profile.name} version {source}")
        body = [line for line in source.read_text().splitlines()
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
    return run(profile.bios, times, case_dir, floppy=image, panel=panel, rompath=profile.rompath,
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
# BIOS sets the 316 profile runs on: one per load segment by default, all four
# in release mode; MPC3K_BIOS_316=v311,vailixi (or "all") overrides.
BIOS_316_DEFAULT = ("default", "v308")


def bios316_sets() -> tuple[str, ...]:
    spec = os.environ.get("MPC3K_BIOS_316", "")
    if spec == "all" or (RELEASE and not spec):
        return BIOS_316
    if not spec:
        return BIOS_316_DEFAULT
    sets = tuple(filter(None, spec.split(",")))
    unknown = [b for b in sets if b not in BIOS_316]
    if unknown:
        raise ValueError(f"MPC3K_BIOS_316: unknown BIOS sets {unknown}")
    if RELEASE and set(sets) != set(BIOS_316):
        raise RuntimeError(f"MPC3K_RELEASE=1 runs 316 on every BIOS set, not {sets}")
    return sets


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

    MPC3K_GENERIC=all runs every case on both profiles.  A suite that lists
    "316" in PROFILE_NAMES also runs every case (minus SKIP_316) on the 316
    profile, once per BIOS set of bios316_sets().  Results are keyed by
    (label, case), label = profile.label ('capture', 'generic', '316-v308');
    each case directory is RUNS/<label>/<case>.  `cases()` must take its
    times from profile.view / profile.timeline.
    """
    RUNS: Path
    GENERIC: frozenset = frozenset()
    CAPTURE_ONLY: frozenset = frozenset()     # cases whose expectations are capture-specific
    PROFILE_NAMES: tuple = PROFILES           # add "316" once the suite's observers are ported
    SKIP_316: frozenset = frozenset()         # cases that do not apply to 3.16 (say why)
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
        wanted = set(filter(None, os.environ.get("MPC3K_PROFILES", "").split(","))) or set(ALL_PROFILES)
        selected = []
        for name in cls.PROFILE_NAMES:
            if name not in wanted:
                continue
            selected += [payload(name, bios) for bios in bios316_sets()] if name == "316" else [payload(name)]
        for profile in selected:
            name = profile.name
            cls.profiles[profile.label] = profile
            runs = cls.RUNS / profile.label
            runs.mkdir(parents=True, exist_ok=True)
            profile.record(cls.RUNS)
            for case, spec in cls.cases(profile, runs).items():
                if only and case not in only:
                    continue
                if name == "generic" and case in cls.CAPTURE_ONLY:
                    continue
                if name == "generic" and not (GENERIC_ALL or case in cls.GENERIC):
                    continue
                if name == "316" and case in cls.SKIP_316:
                    continue
                jobs[(profile.label, case)] = (profile, runs, spec)

        def go(key, job):
            profile, runs, spec = job
            return run_case(profile, runs, key[1], times=spec.times, events=spec.events,
                            files=list(spec.files), parts=spec.parts, env=spec.env,
                            prelude=spec.prelude, **(spec.kwargs or {}))
        cls.results = run_parallel(jobs, go, cls.WORKERS)

    def view(self, label: str) -> float:
        """Wave-view time of the profile a result label belongs to."""
        return self.profiles[label].view

    def each(self, case: str) -> list[tuple[str, Path, list[dict]]]:
        found = [(p, self.RUNS / p / c, s) for (p, c), s in self.results.items() if c == case]
        self.assertTrue(found, f"case {case} did not run")
        return found
