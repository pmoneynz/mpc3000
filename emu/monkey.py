#!/usr/bin/env python3
"""Random-input soak test ("monkey") for PMONEY OS against stock OS 3.16.

    python3 monkey.py soak --seeds 1-48 --minutes 5 --bios default,v308 --scsi-every 6
    python3 monkey.py smoke                       # release gate: SMOKE_SEEDS, exit 1 on any failure
    python3 monkey.py one --os pmoney --bios default --seed 7 --minutes 5
    python3 monkey.py one --os stock --bios v308 --actions DIR/actions.json [--cold] [--pixels 40,41]
    python3 monkey.py shrink --run RUN_DIR --cls HANG [--os stock]
    python3 monkey.py timeline --run RUN_DIR [--from T --to T --full]
    python3 monkey.py compare | coverage | summary | rejudge | show --seed N

(adopted into the repository: ``python3 -m emu.monkey ...``, observer
``emu/lua/monkey.lua``, gate ``python3 -m unittest emu.test_monkey``).
``--workers N`` (default ``MPC3K_WORKERS`` or one per core) bounds the MAME
processes; ``--work DIR`` (default ``build/emu/monkey``, or ``MONKEY_WORK``)
holds everything a run writes: payload cache, boot snapshots, fixtures, runs.

Each run boots OS 3.16 in the pinned MAME fork from a floppy whose
STARTUP.SYS is either the PMONEY payload (``harness.payload("316", bios)``,
built from the current sources and pinned by SHA-256 into ``work/payload``)
or the unmodified ``M3K316.SYS`` ("stock"), plus SND / PGM / MID files, and
optionally a raw SCSI hard disk.  Runs resume from a per-target boot
snapshot (PMONEY: entry316's first write to the cave home, as
harness.boot_snapshot; stock: 3.16 start-up zeroing DGROUP:FC90), except
SCSI runs and ``--cold``.

A seeded generator (:func:`generate`) turns the seed into a list of actions:
panel-link key taps, data-wheel bursts, pads with pressure and slider,
Rec/Play/Overdub chords, MIDI In 1 note/controller/sysex/clock streams, and
macros weighted toward PMONEY's own pages (wave view, zones, CHOP, Edit Sound
Do, compress, mute groups, System Information, Extra Settings, Sync, timing
correct, erase all, Disk 9 copy/format/SCSI, PMONEY pages while the
sequencer runs).  The same seed gives the same actions on both OSes; the
action list (``actions.json`` in every run) is the unit the shrinker removes.
After the actions a fixed epilogue (Stop, Stop, Main Screen, Other, Main
Screen, Soft Key 4, Main Screen) checks that the machine still answers.

Observation is read-only (``monkey.lua``): screen text and an LCD hash every
second, the 3.16 key-queue count, PC spread, IVT vector 0-7 dispatches,
writes to the cave's instruction bytes, foreign writes into cave data,
writes into 3.16 code, writes above 3.16's memory outside the cave (with
SS:SP), and at the end the cave home and the sound directory.  :func:`judge`
turns that into failure classes; :func:`compare` sets each PMONEY class
against the stock run of the same seed.  Results are deterministic per
(OS, BIOS, actions, options): MAME runs with -nothrottle, fresh NVRAM and
normalized disk images (two runs of a seed give identical samples).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _repo() -> Path:
    for cand in (HERE.parent, Path(os.environ.get("MPC3K_REPO", "")), Path.home() / "Documents" / "MPC3000"):
        if cand and (cand / "emu" / "harness.py").is_file():
            return cand.resolve()
    raise SystemExit("cannot find the MPC3000 repository (set MPC3K_REPO)")


REPO = _repo()
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from emu import fat12  # noqa: E402
from emu import harness as h  # noqa: E402
from emu.mpc3k import M3K316, normalize_image, parse_screens, run as mame_run  # noqa: E402
from emu.panel import KEYS, panel_pad, write_smf  # noqa: E402

LUA = (HERE / "lua" / "monkey.lua") if (HERE / "lua" / "monkey.lua").is_file() else HERE / "monkey.lua"
LUA_TEXT = LUA.read_text()           # read once: a campaign keeps the observer it started with
PROBE = REPO / "emu" / "probe.lua"
DEFAULT_WORK = REPO / "build" / "emu" / "monkey"

# 3.16 constants (notes/port_316.md, mods/profile_316.inc)
PHYS = 0x300000
DGROUP_REL = 0x609C
CODE_END = DGROUP_REL * 16          # image offset of DGROUP: [0, CODE_END) is code + far data
# 3.16's last code byte: the far-call relocation with the highest target is
# 4853:0006 (image 0x48586, the pool-bound routine), which ends with
# POP ES / POP BP / RETF at image 0x485E7..0x485E9; zeros follow.  Every
# write below CODE_LIMIT is a write into 3.16 code (with L = 6900h stock
# 3.16's sequence pool overlaps image 0x0000-0x6FFF: notes/port_316.md).
CODE_LIMIT = 0x485EA
TOP_FROM = 0x7DFB0                  # end of image + BSS + stack (minalloc 0x7DFB paragraphs)
TOP_END = PHYS + 0xF4000            # page 61 is NVRAM
KEY_QUEUE = 0x12A4                  # profile_316.inc KEY_QUEUE (generic 8010:12BC)
SND_REL = 0x539D                    # sound segment (generic A2AE); records at +4800h
RECORD, RECORDS = 36, 128
WAVE_WORDS = 1 << 20                # 2 MB board: sound RAM in 16-bit words
BSS_END_PROBE = 0xFC90              # DGROUP:FC90 is zeroed by 3.16's start-up (BSS 7980..FC9E)

CANCEL = h.TIMELINE_316.cancel      # 33.0: Soft Key 4 cancels the SCSI search
START = 34.5                        # random phase starts (Play/Record by 33.6)
SAMPLE = 1.0                        # monkey.lua sample interval
WATCH_FROM = 31.0                   # writes are judged from here (banner; boot done)
CRASH_TEXT = ("System Error", "software bug", "Sorry, but")
# A floppy format keeps the UI task away from the key queue for ~80 s (stock
# and PMONEY alike, pilot seed 4); longer than this is reported.
UI_BLOCK_LIMIT = 150.0
# Cave data labels 3.16 code legitimately writes (buffers the cave hands to
# stock file routines).  Extend only after reading the writer.
#   mute_staging, mute_read_header: PGM/APS trailer reads (stock file read, 6909:065D / 0722)
#   so_shadow: the Sync Out fields pass CS:so_shadow to the stock field editor
#              T_B354_01C6, which stores the edited value (mods/syncout316.inc so_field)
#   chop_name: CHOP passes CS:chop_name to stock routines (mods/wave_chop.inc)
#   cave_pool: the 3.16 session scratch pool (mods/mute_storage.inc) holds
#              mute_staging and mute_read_header; other cave variables alias
#              it as equates, so a write anywhere in it is named cave_pool.
FOREIGN_OK = {"mute_staging", "mute_read_header", "so_shadow", "chop_name", "cave_pool"}

# ------------------------------------------------------------------------- targets


@dataclass(frozen=True)
class Target:
    """One OS on one BIOS set: PMONEY (cave) or stock M3K316.SYS."""
    os: str                 # "pmoney" | "stock"
    bios: str
    sys: Path
    sha256: str
    rompath: Path
    profile: h.Profile      # the PMONEY profile of this BIOS (addresses; cave map)

    @property
    def label(self) -> str:
        return f"{self.os}-{self.bios}"

    @property
    def pmoney(self) -> bool:
        return self.os == "pmoney"

    @property
    def load_segment(self) -> int:
        return h.LOAD_SEGMENTS[self.bios]

    @property
    def image_phys(self) -> int:
        return PHYS + self.load_segment * 16

    @property
    def dg_phys(self) -> int:
        return PHYS + ((self.load_segment + DGROUP_REL) & 0xFFFF) * 16

    @property
    def records_phys(self) -> int:
        return PHYS + ((self.load_segment + SND_REL) & 0xFFFF) * 16 + 0x4800

    @property
    def cave_len(self) -> int:
        return h.cave_end(self.profile.map) if self.pmoney else 0

    @property
    def snapshot_trigger(self) -> int:
        """Physical address whose first CPU write marks the boot snapshot.

        PMONEY: entry316's first write to the cave home (as harness.boot_snapshot).
        Stock: 3.16's start-up zeroing BSS (DGROUP:FC90), past every byte the
        EPROM loader writes (it reads whole sectors, so it may write a little
        past the image end at DGROUP:7980)."""
        return self.profile.cave_phys if self.pmoney else self.dg_phys + BSS_END_PROBE


_payload_lock = threading.Lock()


def targets(work: Path, bios_sets: list[str], oses: list[str]) -> dict[str, Target]:
    """Build the PMONEY payload (cached under work/cache) and pin it into work/payload."""
    h.PAYLOADS = work / "cache" / "payloads"
    out: dict[str, Target] = {}
    with _payload_lock:
        for bios in bios_sets:
            p = h.payload("316", bios)
            pin = work / "payload" / p.sha256[:16]
            if not (pin / "WAVE316.SYS").is_file():
                pin.mkdir(parents=True, exist_ok=True)
                for f in ("WAVE316.SYS", "wave.map", "wave316.cave.bin", "WAVE316.json", "payload.json"):
                    if (p.sys.parent / f).is_file():
                        shutil.copy(p.sys.parent / f, pin / f)
            # Labels can change without changing a byte (a new label at an
            # existing address): keep the pinned map current with the sources.
            if (p.sys.parent / "wave.map").is_file():
                shutil.copy(p.sys.parent / "wave.map", pin / "wave.map")
            p = dataclasses.replace(p, sys=pin / "WAVE316.SYS", map=pin / "wave.map")
            for os_ in oses:
                if os_ == "pmoney":
                    out[f"pmoney-{bios}"] = Target("pmoney", bios, p.sys, p.sha256, p.rompath, p)
                else:
                    out[f"stock-{bios}"] = Target("stock", bios, M3K316,
                                                  hashlib.sha256(M3K316.read_bytes()).hexdigest(), p.rompath, p)
    return out


# ------------------------------------------------------------------------- cave layout


def cave_layout(target: Target, work: Path) -> tuple[Path, list[tuple[int, int, str]]]:
    """'1'/'0' per cave byte (instruction / data) from the NASM listing, and the data lines.

    The cave is re-assembled exactly as mods/build_wave316.py does (same
    source, define and include path) and must equal the payload's
    wave316.cave.bin, so the listing describes the bytes under test."""
    pin = target.profile.sys.parent
    code_file = pin / "cave_code.bits"
    data_file = pin / "cave_data.json"
    if code_file.is_file() and data_file.is_file():
        return code_file, [tuple(x) for x in json.loads(data_file.read_text())]
    from mods import build_mod_sys as mod
    from mods import build_wave316 as b316
    from mods import buildkit as kit
    args = mod.read_args(b316.ARGS)
    asm = kit.assemble(args.cave, defines={b316.DEFINE: None}, include=[args.cave.parent],
                       map_column="real", listing=True)
    ref = (pin / "wave316.cave.bin").read_bytes()
    if asm.code != ref:
        raise RuntimeError("re-assembled cave differs from the payload's wave316.cave.bin "
                           "(sources changed since the payload was built?)")
    bits = bytearray(b"0" * len(ref))
    data_lines = []
    data_ops = {"db", "dw", "dd", "dq", "dt", "times", "resb", "resw", "resd", "incbin", "align", "alignb"}
    for line in asm.listing:
        toks = line.source.split(";")[0].split()
        if toks and toks[0].endswith(":"):
            toks = toks[1:]
        is_data = bool(toks) and (toks[0].lower() in data_ops or (len(toks) > 1 and toks[1].lower() in data_ops))
        if not toks:
            is_data = True
        if is_data:
            data_lines.append((line.offset, len(line.data), line.source.strip()[:60]))
        else:
            for i in range(line.offset, min(len(bits), line.offset + len(line.data))):
                bits[i] = ord("1")
    code_file.write_bytes(bytes(bits))
    data_file.write_text(json.dumps(data_lines))
    return code_file, data_lines


def cave_labels(target: Target) -> list[tuple[int, str]]:
    """Cave labels (offset, name) sorted, for naming a changed byte."""
    syms = target.profile.symbols()
    n = target.cave_len
    out = [(v, k) for k, v in syms.items()
           if 0 <= v < n and not k.startswith(("T_", "__reloc")) and not re.fullmatch(r"[A-Z0-9_]+", k)]
    return sorted(out)


def label_of(labels: list[tuple[int, str]], off: int) -> str:
    best = None
    for v, k in labels:
        if v <= off:
            best = (v, k)
        else:
            break
    return f"{best[1]}+{off - best[0]:X}" if best else f"{off:X}"


# ------------------------------------------------------------------------- fixtures


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def song_mid() -> bytes:
    """A 4-bar format-0 SMF (drum notes on channel 10) for Disk Load as a sequence."""
    track = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20")          # 120 BPM
    track += b"\x00\xff\x58\x04\x04\x02\x18\x08"
    last = 0
    evs = []
    for beat in range(16):
        t = beat * 96
        for note in ((36,) if beat % 2 == 0 else (38,)) + (42,):
            evs.append((t, bytes([0x99, note, 100])))
            evs.append((t + 48, bytes([0x89, note, 0])))
    for t, msg in sorted(evs, key=lambda e: e[0]):
        track += _vlq(t - last) + msg
        last = t
    track += b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 96) + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def floppy_files(work: Path) -> list[tuple[str, bytes]]:
    """SND, PGM and MID files every monkey floppy carries after STARTUP.SYS."""
    from emu import pgm
    from emu.snd import sine, sine441, snd, stereo1
    a = snd("SINE441", sine441())
    files = [("SINE441.SND", a), ("STEREO1.SND", snd("STEREO1", stereo1())),
             ("SHORT.SND", snd("SHORT", [sine(3000)])),
             ("KICK.SND", snd("KICK", [[int(20000 * (1 - i / 6000)) * (1 if (i // 40) % 2 else -1)
                                        for i in range(6000)]])),
             ("PADS.PGM", pgm.for_sound(a, pads=range(16), enabled=True,
                                        groups=[1, 1, 2, 2, 3, 3, 4, 4] + [0] * 56, program_name="PADS")),
             ("SONG.MID", song_mid())]
    return files


def make_floppy(path: Path, sys_bytes: bytes, files: list[tuple[str, bytes]]) -> Path:
    """Deterministic 1.44 MB FAT12 image (mtools, then emu.mpc3k.normalize_image)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    subprocess.run(["mformat", "-C", "-f", "1440", "-i", str(path), "::"], check=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        for name, data in [("STARTUP.SYS", sys_bytes), *files]:
            src = Path(tmp) / name
            src.write_bytes(data)
            subprocess.run(["mcopy", "-i", str(path), str(src), f"::{name}"], check=True)
    normalize_image(path)
    return path


SCSI_MB = 40


def scsi_fixture(work: Path, target: Target) -> Path:
    """A 40 MiB raw SCSI disk formatted by PMONEY's Disk 9 3 with the stock layout
    (AUTO, <Fast>, <MPC only>; emu/test_scsi316.py), plus SINE441.SND in volume A."""
    hd = work / "fixtures" / f"scsi-{target.bios}.hd"
    if hd.is_file():
        return hd
    d = work / "fixtures" / f"scsi-format-{target.bios}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    blank = d / "blank.hd"
    blank.write_bytes(bytes(SCSI_MB << 20))
    ev = h.taps((33.0, "soft4"), (35, "disk"), (36, "9"), (37.5, "3"), (40, "soft1"), (42, "soft2"),
                (44, "soft1"), (46, "soft1"))
    floppy = make_floppy(d / "boot.img", target.sys.read_bytes(), [])
    mame_run(target.bios, [60.0], d / "run", floppy=floppy, panel=write_smf(d / "panel.mid", ev),
             rompath=target.rompath, extra=["-scsi:0", "harddisk", "-hard", str(blank)])
    src = d / "SINE441.SND"
    src.write_bytes(dict(floppy_files(work))["SINE441.SND"])
    subprocess.run(["mcopy", "-i", str(blank), str(src), "::SINE441.SND"], check=True)
    shutil.move(blank, hd)
    return hd


# ------------------------------------------------------------------------- snapshots

_snap_lock = threading.Lock()


def boot_snapshot(work: Path, target: Target) -> tuple[Path, Path, float]:
    """(state directory, LCD shadow, time) of this target's boot snapshot, made once.

    Same mechanism as harness.boot_snapshot (PROBE_SAVE_ON_WRITE), with the
    trigger of Target.snapshot_trigger and a midiin1 file mounted so the
    snapshot has the devices a monkey run has."""
    mame_sha = hashlib.sha256(Path(h.MAME).read_bytes()).hexdigest()
    key = hashlib.sha256(f"{mame_sha} {target.sha256} {target.bios} {target.snapshot_trigger:X} "
                         f"{target.rompath}".encode()).hexdigest()[:16]
    final = work / "cache" / "snapshots" / f"{target.label}-{key}"
    with _snap_lock:
        if not (final / "boot.lcd.at").exists():
            tmp = Path(tempfile.mkdtemp(prefix=f"{target.label}-", dir=_mk(final.parent)))
            try:
                floppy = make_floppy(tmp / "boot.img", target.sys.read_bytes(), [])
                panel = write_smf(tmp / "panel.mid", [(CANCEL + 100, b"\xf8")])
                midi = write_smf(tmp / "midi.mid", [(CANCEL + 100, b"\xf8")])
                mame_run(target.bios, [CANCEL - 0.2], tmp / "snap", floppy=floppy, panel=panel,
                         rompath=target.rompath,
                         extra=["-midiin1", str(midi), "-state_directory", str(tmp / "states")],
                         env={"PROBE_SAVE_ON_WRITE": f"{target.snapshot_trigger:X}", "PROBE_SAVE_NAME": "boot",
                              "PROBE_SAVE_LCD": str(tmp / "boot.lcd")})
                if not (tmp / "boot.lcd.at").exists() or not list((tmp / "states").rglob("boot.sta")):
                    raise RuntimeError(f"{target.label}: boot snapshot not written; see {tmp}")
                os.rename(tmp, final)
                tmp = None
            finally:
                if tmp is not None:
                    shutil.rmtree(tmp, ignore_errors=True)
    return final / "states", final / "boot.lcd", float((final / "boot.lcd.at").read_text())


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------------- actions

# Every panel key on the link (emu/panel.py KEYS).
ALL_KEYS = sorted(KEYS)
NAV_KEYS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "enter", "+", "-", "up", "down",
            "left", "right", "soft1", "soft2", "soft3", "soft4"]
MODE_KEYS = ["disk", "program_sounds", "mixer_effects", "midi", "song", "other", "edit", "step_edit",
             "edit_loop", "tempo_sync", "transpose", "2nd_seq", "auto_punch", "count_in", "wait_for_key",
             "erase", "timing_correct", "main_screen", "help"]


@dataclass
class Action:
    """A unit of input: panel-link events, MIDI In 1 events, all at absolute times."""
    t: float
    kind: str
    desc: str
    panel: list = field(default_factory=list)      # (t, bytes)
    midi: list = field(default_factory=list)       # (t, bytes)
    end: float = 0.0

    def to_json(self) -> dict:
        return {"t": round(self.t, 4), "kind": self.kind, "desc": self.desc, "end": round(self.end, 4),
                "panel": [[round(t, 4), b.hex()] for t, b in self.panel],
                "midi": [[round(t, 4), b.hex()] for t, b in self.midi]}

    @classmethod
    def from_json(cls, d: dict) -> "Action":
        return cls(d["t"], d["kind"], d["desc"], [(t, bytes.fromhex(b)) for t, b in d["panel"]],
                   [(t, bytes.fromhex(b)) for t, b in d["midi"]], d["end"])


class Builder:
    """Accumulates the events of one action from a running clock."""

    def __init__(self, rng: random.Random, t: float):
        self.rng, self.t0, self.t = rng, t, t
        self.panel: list = []
        self.midi: list = []
        self.words: list[str] = []

    def gap(self, lo: float = 0.25, hi: float = 0.9) -> None:
        self.t += self.rng.uniform(lo, hi)

    def tap(self, key: str, hold: float = 0.1, gap: tuple[float, float] | None = (0.3, 0.9)) -> None:
        code = KEYS[key]
        self.panel += [(self.t, bytes([0x90, code, 0x7F])), (self.t + hold, bytes([0x90, code, 0x00]))]
        self.words.append(key)
        if gap:
            self.gap(*gap)

    def chord(self, first: str, second: str, hold: float = 0.5, offset: float = 0.2) -> None:
        """Hold `first`, press `second` `offset` s into it (Rec + Play)."""
        a, b = KEYS[first], KEYS[second]
        self.panel += [(self.t, bytes([0x90, a, 0x7F])), (self.t + hold, bytes([0x90, a, 0x00])),
                       (self.t + offset, bytes([0x90, b, 0x7F])), (self.t + offset + 0.1, bytes([0x90, b, 0x00]))]
        self.words.append(f"{first}+{second}")
        self.t += hold + 0.2

    def wheel(self, steps: int, gap: float | None = None) -> None:
        if steps == 0:
            return
        gap = gap if gap is not None else self.rng.choice([0.001, 0.001, 0.02, 0.05])
        d = 0x00 if steps > 0 else 0x7F
        for i in range(abs(steps)):
            self.panel.append((self.t + i * gap, bytes([0xE0, d, d])))
        self.words.append(f"wheel{steps:+d}")
        self.t += abs(steps) * gap + self.rng.uniform(0.2, 0.6)

    def pad(self, n: int | None = None, velocity: int | None = None, hold: float | None = None) -> None:
        n = n if n is not None else self.rng.randint(1, 16)
        velocity = velocity if velocity is not None else self.rng.randint(1, 127)
        hold = hold if hold is not None else self.rng.uniform(0.03, 0.4)
        raw = panel_pad(n)
        self.panel += [(self.t, bytes([0x90, raw, velocity])), (self.t + hold, bytes([0x90, raw, 0x00]))]
        if self.rng.random() < 0.2:
            self.panel.append((self.t + hold / 2, bytes([0xA0, raw, self.rng.randint(0, 127)])))
        self.words.append(f"pad{n}")
        self.gap(0.05, 0.4)

    def slider(self) -> None:
        self.panel.append((self.t, bytes([0xB0, 0x00, self.rng.randint(0, 127)])))
        self.words.append("slider")
        self.gap(0.05, 0.3)

    def wait(self, lo: float, hi: float) -> None:
        dt = self.rng.uniform(lo, hi)
        self.words.append(f"wait{dt:.1f}")
        self.t += dt

    def done(self, kind: str) -> Action:
        return Action(self.t0, kind, " ".join(self.words), self.panel, self.midi, self.t)


def _random_inner(b: Builder, n: int, keys: list[str]) -> None:
    """n random presses among `keys`, wheel bursts and digits."""
    for _ in range(n):
        r = b.rng.random()
        if r < 0.3:
            b.wheel(b.rng.randint(-24, 24))
        else:
            b.tap(b.rng.choice(keys), gap=(0.15, 0.8))


# Each macro: (name, weight, builder).  PMONEY's own pages carry most weight.
def m_tap_any(b: Builder) -> None:
    b.tap(b.rng.choice(ALL_KEYS), gap=(0.1, 0.8))


def m_tap_nav(b: Builder) -> None:
    for _ in range(b.rng.randint(1, 4)):
        b.tap(b.rng.choice(NAV_KEYS), gap=(0.1, 0.6))


def m_mode(b: Builder) -> None:
    b.tap(b.rng.choice(MODE_KEYS))
    _random_inner(b, b.rng.randint(0, 4), NAV_KEYS)


def m_wheel(b: Builder) -> None:
    b.wheel(b.rng.choice([-1, 1]) * b.rng.choice([1, 2, 3, 5, 9, 16, 30, 60]))


def m_pads(b: Builder) -> None:
    for _ in range(b.rng.randint(1, 12)):
        b.pad()
    if b.rng.random() < 0.3:
        b.slider()


def m_record(b: Builder) -> None:
    b.chord("rec", b.rng.choice(["play", "play_start"]))
    for _ in range(b.rng.randint(0, 20)):
        b.pad(hold=b.rng.uniform(0.03, 0.2))
    b.wait(0.5, 6.0)
    b.tap("stop", gap=(0.5, 1.5))


def m_overdub(b: Builder) -> None:
    b.chord("overdub", b.rng.choice(["play", "play_start"]))
    for _ in range(b.rng.randint(0, 10)):
        b.pad(hold=0.1)
    b.wait(0.5, 4.0)
    b.tap("stop", gap=(0.5, 1.5))


def m_play(b: Builder) -> None:
    b.tap(b.rng.choice(["play", "play_start"]))
    for _ in range(b.rng.randint(0, 5)):
        if b.rng.random() < 0.5:
            b.pad()
        else:
            b.tap(b.rng.choice(ALL_KEYS))
    b.wait(0.5, 6.0)
    b.tap("stop", gap=(0.4, 1.0))


def m_locate(b: Builder) -> None:
    for _ in range(b.rng.randint(1, 4)):
        b.tap(b.rng.choice(["rewind_bar", "rewind_step", "locate", "forward_step", "forward_bar"]))


def m_wait(b: Builder) -> None:
    b.wait(1.0, 10.0)


def m_midi_notes(b: Builder) -> None:
    t = b.t
    ch = b.rng.randint(0, 15)
    for _ in range(b.rng.randint(1, 40)):
        note, vel = b.rng.randint(0, 127), b.rng.randint(1, 127)
        if b.rng.random() < 0.15:
            ch = b.rng.randint(0, 15)
        b.midi.append((t, bytes([0x90 | ch, note, vel])))
        b.midi.append((t + b.rng.uniform(0.01, 0.5), bytes([0x80 | ch, note, 0x40])))
        t += b.rng.choice([0.002, 0.01, 0.05, 0.1, 0.2])
    b.words.append("midi-notes")
    b.t = t + b.rng.uniform(0.2, 1.0)


def m_midi_ctrl(b: Builder) -> None:
    t = b.t
    for _ in range(b.rng.randint(1, 30)):
        ch = b.rng.randint(0, 15)
        r = b.rng.random()
        if r < 0.5:
            msg = bytes([0xB0 | ch, b.rng.randint(0, 127), b.rng.randint(0, 127)])
        elif r < 0.65:
            msg = bytes([0xC0 | ch, b.rng.randint(0, 127)])
        elif r < 0.8:
            msg = bytes([0xE0 | ch, b.rng.randint(0, 127), b.rng.randint(0, 127)])
        elif r < 0.9:
            msg = bytes([0xD0 | ch, b.rng.randint(0, 127)])
        else:
            msg = bytes([0xA0 | ch, b.rng.randint(0, 127), b.rng.randint(0, 127)])
        b.midi.append((t, msg))
        t += b.rng.choice([0.002, 0.01, 0.05])
    b.words.append("midi-ctrl")
    b.t = t + 0.3


def m_midi_sysex(b: Builder) -> None:
    n = b.rng.choice([0, 1, 4, 16, 100, 600])
    head = b.rng.choice([b"\x47", b"\x47\x00\x0c", b"\x7e", b"\x7f\x7f\x06", b""])
    body = head + bytes(b.rng.randint(0, 127) for _ in range(n))
    data = body + b"\xf7"
    b.midi.append((b.t, b"\xf0" + _vlq(len(data)) + data))
    b.words.append(f"sysex{len(data)}")
    b.t += 0.0003 * len(data) + b.rng.uniform(0.2, 1.0)


def escaped(msg: bytes) -> bytes:
    """A system common / real-time message as an SMF escape event (F7 len bytes).

    MAME's midiin SMF reader takes any F1..FE status as a length-prefixed
    event, so a bare F8 desynchronises the track (generator 2 did that; seed
    14 then made MAME refuse the file).  The escape plays as F7 followed by
    the message: a stray EOX before each, which a MIDI receiver ignores
    outside a sysex."""
    return b"\xf7" + _vlq(len(msg)) + msg


def m_midi_realtime(b: Builder) -> None:
    t = b.t
    if b.rng.random() < 0.5:
        b.midi.append((t, escaped(b"\xf2" + bytes([b.rng.randint(0, 127), b.rng.randint(0, 7)]))))
    b.midi.append((t + 0.01, escaped(bytes([b.rng.choice([0xFA, 0xFB])]))))
    n = b.rng.randint(10, 400)
    period = b.rng.choice([0.0208, 0.0104, 0.005, 0.04])
    for i in range(n):
        b.midi.append((t + 0.02 + i * period, escaped(b"\xf8")))
        if b.rng.random() < 0.05:
            b.midi.append((t + 0.02 + i * period + 0.001, escaped(bytes([0xF1, b.rng.randint(0, 127)]))))
    end = t + 0.02 + n * period
    if b.rng.random() < 0.8:
        b.midi.append((end, escaped(b"\xfc")))
    b.words.append(f"midi-clock{n}")
    b.t = end + 0.3


def m_wave_view(b: Builder) -> None:
    b.tap("program_sounds", gap=(0.8, 1.2))
    b.tap("6", gap=(1.0, 2.0))
    if b.rng.random() < 0.3:
        b.wheel(b.rng.randint(-3, 3))           # another sound
    b.tap("help", gap=(2.5, 4.0))
    _random_inner(b, b.rng.randint(3, 25), ["soft1", "soft2", "soft3", "up", "down", "left", "right",
                                            "1", "2", "3", "4", "8", "9", "0", "enter", "+", "-", "help"])
    if b.rng.random() < 0.6:
        b.tap("soft4")


def m_edit_sound_do(b: Builder) -> None:
    b.tap("program_sounds", gap=(0.8, 1.2))
    b.tap("6", gap=(1.0, 2.0))
    for _ in range(b.rng.randint(0, 18)):
        b.tap(b.rng.choice(["right", "right", "right", "left", "down", "up"]), gap=(0.15, 0.3))
    b.wheel(b.rng.randint(-12, 12))
    if b.rng.random() < 0.3:
        _random_inner(b, b.rng.randint(1, 4), ["1", "2", "5", "9", "0", "enter", "left", "right"])
    b.tap("soft4", gap=(1.0, 3.0))                # <Do>
    for _ in range(b.rng.randint(0, 3)):
        b.tap(b.rng.choice(["soft1", "soft4", "enter", "soft2", "main_screen"]), gap=(0.5, 4.0))
    b.wait(0.5, 6.0)


def m_chop(b: Builder) -> None:
    b.tap("program_sounds", gap=(0.8, 1.2))
    b.tap("6", gap=(1.0, 2.0))
    b.tap("help", gap=(2.5, 4.0))
    b.tap("soft2", gap=(0.4, 0.8))                # Zone mode
    for _ in range(b.rng.randint(0, 3)):
        b.tap(b.rng.choice(["right", "left"]), gap=(0.2, 0.5))
    b.wheel(b.rng.randint(-16, 16))
    if b.rng.random() < 0.5:
        _random_inner(b, b.rng.randint(1, 6), ["left", "right", "up", "down", "soft3", "soft1"])
    b.tap("soft4", gap=(1.0, 2.0))                # back to Edit Sound
    for _ in range(16):
        b.tap("right", gap=(0.15, 0.25))
    b.wheel(b.rng.choice([10, 10, 10, 9, 11, 8]), gap=0.05)   # CHOP ZONE is Do #10
    b.tap("soft4", gap=(1.0, 3.0))                # <Do>
    for _ in range(b.rng.randint(0, 2)):
        b.tap(b.rng.choice(["soft1", "soft4", "enter", "help"]), gap=(1.0, 6.0))
    b.wait(1.0, 8.0)


def m_compress(b: Builder) -> None:
    b.tap("program_sounds", gap=(0.8, 1.2))
    b.tap("9", gap=(1.0, 2.0))
    if b.rng.random() < 0.4:
        b.wheel(b.rng.randint(-4, 4))
    b.tap(b.rng.choice(["soft1", "soft1", "soft4", "enter"]), gap=(1.0, 2.0))
    b.wait(0.5, 6.0)


def m_mute(b: Builder) -> None:
    b.tap("program_sounds", gap=(0.8, 1.2))
    b.tap("0", gap=(1.5, 2.5))
    for _ in range(b.rng.randint(2, 20)):
        r = b.rng.random()
        if r < 0.15:
            b.pad()
        elif r < 0.3:
            b.wheel(b.rng.randint(-6, 6))
        elif r < 0.37:
            b.tap("soft1", gap=(0.8, 1.5))
            b.tap(b.rng.choice(["soft1", "soft4", "soft2", "enter", "main_screen"]), gap=(0.5, 1.2))
        else:
            b.tap(b.rng.choice(["left", "right", "up", "down", "+", "-", "0", "1", "2", "3", "4", "5",
                                "pad_bank", "soft2", "soft3", "enter"]), gap=(0.15, 0.6))
    if b.rng.random() < 0.5:
        b.tap("soft4")


def m_program_sounds(b: Builder) -> None:
    b.tap("program_sounds", gap=(0.8, 1.2))
    b.tap(b.rng.choice("0123456789"), gap=(1.0, 2.0))
    _random_inner(b, b.rng.randint(0, 6), NAV_KEYS)


def m_sysinfo(b: Builder) -> None:
    b.tap("other", gap=(0.8, 1.5))
    b.tap("soft3", gap=(0.5, 3.0))
    if b.rng.random() < 0.3:
        _random_inner(b, b.rng.randint(1, 3), NAV_KEYS)
    b.tap(b.rng.choice(["soft1", "soft1", "main_screen", "other"]))


def m_extra_settings(b: Builder) -> None:
    b.tap("other", gap=(0.8, 1.5))
    b.tap("soft4", gap=(1.0, 1.8))
    for _ in range(b.rng.randint(1, 12)):
        r = b.rng.random()
        if r < 0.25:
            b.wheel(b.rng.randint(-3, 3))
        else:
            b.tap(b.rng.choice(["down", "up", "+", "-", "left", "right", "soft1", "soft2", "soft3", "enter"]),
                  gap=(0.2, 0.7))
    b.tap(b.rng.choice(["main_screen", "soft4", "other"]))


def m_sync(b: Builder) -> None:
    b.tap("tempo_sync", gap=(0.8, 1.5))
    b.tap("soft1", gap=(1.0, 1.8))
    for _ in range(b.rng.randint(1, 10)):
        if b.rng.random() < 0.4:
            b.wheel(b.rng.randint(-6, 6))
        else:
            b.tap(b.rng.choice(["right", "left", "down", "up", "soft1", "soft2", "soft4", "+", "-"]),
                  gap=(0.2, 0.7))
    if b.rng.random() < 0.4:
        m_play(b)


def m_timing_correct(b: Builder) -> None:
    b.tap("timing_correct", gap=(0.8, 1.5))
    for _ in range(b.rng.randint(1, 6)):
        if b.rng.random() < 0.6:
            b.wheel(b.rng.randint(-13, 13))
        else:
            b.tap(b.rng.choice(["down", "up", "left", "right", "soft1", "soft4", "enter"]), gap=(0.2, 0.7))


def m_disk_load(b: Builder) -> None:
    b.tap("disk", gap=(1.0, 2.0))
    b.tap("7", gap=(3.0, 4.5))                    # the file list is ready ~3.5 s after Disk
    if b.rng.random() < 0.5:
        b.tap(b.rng.choice(["down", "up"]), gap=(0.3, 0.6))
    b.wheel(b.rng.randint(-6, 6), gap=0.05)
    b.tap("soft1", gap=(1.0, 3.0))                # <Load>
    if b.rng.random() < 0.5:
        b.tap(b.rng.choice(["soft1", "soft4", "enter"]), gap=(0.5, 2.0))
    b.wait(2.0, 8.0)


def m_disk_save(b: Builder) -> None:
    b.tap("disk", gap=(1.0, 2.0))
    b.tap(b.rng.choice("123456"), gap=(1.0, 3.0))
    if b.rng.random() < 0.5:
        b.wheel(b.rng.randint(-4, 4), gap=0.05)
    b.tap(b.rng.choice(["soft1", "soft1", "soft4"]), gap=(1.0, 3.0))
    if b.rng.random() < 0.3:
        b.tap(b.rng.choice(["soft1", "soft4", "enter"]), gap=(0.5, 2.0))
    b.wait(2.0, 8.0)


def m_erase_all(b: Builder) -> None:
    b.tap("disk", gap=(1.0, 2.0))
    b.tap("7", gap=(3.0, 4.5))
    b.tap("soft2", gap=(1.5, 2.5))                # <Erase>
    b.tap("soft2", gap=(1.5, 2.5))                # <Erase all>
    b.tap(b.rng.choice(["soft1", "main_screen", "soft4", "soft1"]), gap=(1.0, 3.0))
    b.wait(1.0, 6.0)


def m_disk9(b: Builder) -> None:
    b.tap("disk", gap=(1.0, 2.0))
    b.tap("9", gap=(1.0, 2.0))
    b.tap(b.rng.choice("12345"), gap=(1.0, 2.5))
    for _ in range(b.rng.randint(1, 8)):
        if b.rng.random() < 0.3:
            b.wheel(b.rng.randint(-5, 5))
        else:
            b.tap(b.rng.choice(["soft1", "soft2", "soft3", "soft4", "down", "up", "left", "right", "enter"]),
                  gap=(0.5, 2.5))
    b.wait(1.0, 8.0)


def m_while_running(b: Builder) -> None:
    """Start the sequencer (play or record), then a PMONEY page while it runs, then Stop."""
    if b.rng.random() < 0.5:
        b.chord("rec", "play")
    else:
        b.tap(b.rng.choice(["play", "play_start"]), gap=(0.4, 0.8))
    page = b.rng.choice([m_wave_view, m_edit_sound_do, m_compress, m_mute, m_chop, m_sync, m_extra_settings])
    page(b)
    for _ in range(b.rng.randint(0, 6)):
        b.pad(hold=0.1)
    b.tap("stop", gap=(0.5, 1.5))


MACROS = [
    # generic
    ("tap_any", 8, m_tap_any), ("tap_nav", 6, m_tap_nav), ("mode", 6, m_mode), ("wheel", 5, m_wheel),
    ("pads", 5, m_pads), ("record", 3, m_record), ("overdub", 1, m_overdub), ("play", 3, m_play),
    ("locate", 1, m_locate), ("wait", 3, m_wait), ("program_sounds", 3, m_program_sounds),
    ("disk_load", 4, m_disk_load), ("disk_save", 2, m_disk_save),
    # MIDI In 1 (only when the run has MIDI)
    ("midi_notes", 3, m_midi_notes), ("midi_ctrl", 2, m_midi_ctrl), ("midi_sysex", 1, m_midi_sysex),
    ("midi_realtime", 1, m_midi_realtime),
    # PMONEY's own pages
    ("wave_view", 9, m_wave_view), ("edit_sound_do", 4, m_edit_sound_do), ("chop", 4, m_chop),
    ("compress", 4, m_compress), ("mute", 6, m_mute), ("sysinfo", 2, m_sysinfo),
    ("extra_settings", 4, m_extra_settings), ("sync", 3, m_sync), ("timing_correct", 2, m_timing_correct),
    ("erase_all", 1, m_erase_all), ("disk9", 3, m_disk9), ("while_running", 4, m_while_running),
]
GENERATOR = 3       # bump when MACROS or a macro changes: seeds then mean other actions
# 3: real-time / system common MIDI as SMF escapes (2 wrote bare F8.., which
#    MAME's SMF reader misparses); the actions of a seed are otherwise those of 2.
MIDI_MACROS = {"midi_notes", "midi_ctrl", "midi_sysex", "midi_realtime"}


@dataclass(frozen=True)
class Options:
    minutes: float = 5.0
    midi: bool = True
    scsi: bool = False

    def tag(self) -> str:
        return (f"g{GENERATOR}-m{self.minutes:g}" + ("" if self.midi else "-nomidi")
                + ("-scsi" if self.scsi else ""))


def generate(seed: int, opts: Options) -> list[Action]:
    """The seed's action list: macros drawn by weight until the random phase ends."""
    rng = random.Random(f"monkey-{seed}")
    macros = [m for m in MACROS if opts.midi or m[0] not in MIDI_MACROS]
    names, weights = [m[0] for m in macros], [m[1] for m in macros]
    fns = {m[0]: m[2] for m in macros}
    end = START + 60.0 * opts.minutes
    t, actions = START, []
    while True:
        name = rng.choices(names, weights)[0]
        b = Builder(random.Random(rng.getrandbits(64)), t)
        fns[name](b)
        a = b.done(name)
        if a.end > end:
            break
        actions.append(a)
        t = a.end + rng.uniform(0.1, 1.0)
    return actions


def epilogue(t: float) -> tuple[list, list[float]]:
    """Fixed liveness check after the random phase.

    Stop, Stop, Main Screen [s1], Other [s2], Main Screen [s3], then Soft
    Key 4 (the <No>/<Cancel> of most stock prompts) and Main Screen [s4].
    Returns (panel events, the four probe times)."""
    b = Builder(random.Random(0), t)
    times = []
    for key, wait, sample in (("stop", 1.0, False), ("stop", 1.5, False), ("main_screen", 3.0, True),
                              ("other", 2.5, True), ("main_screen", 2.5, True), ("soft4", 1.5, False),
                              ("main_screen", 2.5, True)):
        b.tap(key, gap=None)
        b.t += wait
        if sample:
            times.append(round(b.t, 3))
            b.t += 0.5
    return b.panel, times


def check_smf(path: Path) -> int:
    """Parse an SMF the way MAME's midiin_device::midi_sequence does (running
    status, F0/F7/F1..FE as length-prefixed events, FF meta); raise
    ValueError where MAME would refuse the file.  Returns the event count."""
    data = path.read_bytes()
    if data[:4] != b"MThd" or struct.unpack(">I", data[4:8])[0] != 6:
        raise ValueError("not an SMF")
    fmt, ntrk, div = struct.unpack(">HHH", data[8:14])
    pos, events = 14, 0
    for _ in range(ntrk):
        if data[pos:pos + 4] != b"MTrk":
            raise ValueError(f"bad track header at {pos}")
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        p, end, last = pos + 8, pos + 8 + size, 0

        def var() -> int:
            nonlocal p
            v = 0
            while True:
                if p >= end:
                    raise ValueError("variable-length value out of bounds")
                c = data[p]; p += 1
                v = (v << 7) | (c & 0x7F)
                if not c & 0x80:
                    return v
        while p < end:
            var()
            if p >= end:
                raise ValueError("event out of bounds")
            st = data[p]
            if st & 0x80:
                last = st; p += 1
            else:
                st = last
            if st >> 4 != 15:
                p += 1 if st >> 4 in (12, 13) else 2
            elif st != 0xFF:
                n = var(); p += n
            else:
                mt = data[p]; p += 1
                n = var(); p += n
                if mt == 0x2F:
                    break
            if p > end:
                raise ValueError("event data out of bounds")
            events += 1
        pos = end
    return events


# ------------------------------------------------------------------------- one run


@dataclass
class RunResult:
    label: str
    seed: int
    tag: str
    ok: bool
    classes: dict
    details: dict
    wall: float
    emulated: float
    dir: str


def run_actions(work: Path, target: Target, name: str, actions: list[Action], opts: Options,
                runs_dir: Path | None = None, keep: bool = False, pixels: list[float] | None = None,
                cold: bool = False, lean: bool | None = None) -> RunResult:
    """Boot `target`, play `actions`, then the epilogue; observe and judge.

    The run resumes from the target's boot snapshot unless `cold` or a SCSI
    disk is attached (the snapshot has no SCSI device).  `lean` (default:
    no `pixels` asked) replaces emu/probe.lua by monkey.lua's own
    screens.txt writer, without probe.lua's whole-I/O-space taps."""
    if lean is None:
        lean = not pixels
    t_wall = time.time()
    rd = (runs_dir or work / "runs" / target.label) / name
    if rd.exists():
        shutil.rmtree(rd)
    rd.mkdir(parents=True)
    files = floppy_files(work)
    floppy = make_floppy(rd / "floppy.img", target.sys.read_bytes(), files)
    before_fat = fat12.check(floppy.read_bytes())
    last = max([a.end for a in actions], default=START)
    epi, probe_times = epilogue(max(last, START) + 0.5)
    panel_events = h.taps((CANCEL, "soft4")) + [e for a in actions for e in a.panel] + epi
    midi_events = [e for a in actions for e in a.midi] or [(probe_times[-1] + 50, b"\xf8")]
    panel = write_smf(rd / "panel.mid", panel_events)
    midi = write_smf(rd / "midi1.mid", midi_events)
    for f in (panel, midi):
        check_smf(f)                      # a file MAME would refuse is a harness error, not a result
    extra = ["-midiin1", str(midi)]
    env = {}
    snap_at = None
    if opts.scsi:
        hd = rd / "scsi.hd"
        shutil.copy(scsi_fixture(work, target), hd)
        extra += ["-scsi:0", "harddisk", "-hard", str(hd)]
    elif cold:
        pass
    else:
        states, lcd, snap_at = boot_snapshot(work, target)
        extra += ["-state_directory", str(states), "-state", "boot"]
        env.update(PROBE_LCD_SEED=str(lcd), PROBE_REINSERT="0")
    code_file = None
    if target.pmoney:
        code_file, _ = cave_layout(target, work)
    times = sorted(set([*(pixels or []), *probe_times]))
    dump_at = [round(last + 0.25, 3), round(probe_times[-1] - 0.05, 3)]
    script = rd / "observer.lua"
    lines = [
        "local MONKEY = {",
        f"  sample = {SAMPLE}, sample_from = {WATCH_FROM}, watch_from = {WATCH_FROM},",
        f"  dg_phys = 0x{target.dg_phys:06X}, key_queue = 0x{KEY_QUEUE:04X},",
        f"  image_phys = 0x{target.image_phys:06X}, code_end = 0x{CODE_END:05X}, code_limit = 0x{CODE_LIMIT:05X},",
        f"  top_from = 0x{TOP_FROM:05X}, top_end = 0x{TOP_END:06X},",
        f"  cave_phys = 0x{target.profile.cave_phys:06X}, cave_len = {target.cave_len},",
        f"  cave_logical = 0x{target.profile.cave_phys - PHYS:05X}, records_phys = 0x{target.records_phys:06X},",
        f"  cave_code = \"{code_file.as_posix() if code_file else ''}\",",
        "  dump_at = {" + ",".join(f"{t}" for t in dump_at) + "},",
        f"  lean = {'true' if lean else 'false'},",
        "}",
        # MAME runs the autoboot script in its own environment: a dofile'd
        # chunk would not see MONKEY, so the observer is inlined (as
        # harness.observer does with its parts) and only probe.lua is chained.
        "do -- monkey.lua",
        *LUA_TEXT.splitlines(),
        "end",
        *([] if lean else [f'dofile("{PROBE.as_posix()}")']),
    ]
    script.write_text("\n".join(lines) + "\n")
    extra = ["-autoboot_script", str(script), *extra]
    error = None
    screens = []
    try:
        screens = mame_run(target.bios, times, rd / "mame", floppy=floppy, panel=panel, rompath=target.rompath,
                           extra=extra, env=env, timeout=(300 + 6 * max(times)) * float(
                               os.environ.get("MPC3K_TIMEOUT_SCALE", "1")))
    except RuntimeError as exc:
        error = str(exc)
    meta = {"target": target.label, "sha256": target.sha256, "name": name, "opts": dataclasses.asdict(opts),
            "probe_times": probe_times, "dump_at": dump_at, "snapshot_at": snap_at, "error": error,
            "actions": len(actions), "random_end": last}
    (rd / "actions.json").write_text(json.dumps([a.to_json() for a in actions]))
    classes, details = judge(work, target, rd, meta, screens, before_fat)
    result = RunResult(target.label, -1, opts.tag(), not classes, classes, details, time.time() - t_wall,
                       probe_times[-1] - (snap_at or 0.0), str(rd))
    (rd / "result.json").write_text(json.dumps({**meta, **dataclasses.asdict(result)}, indent=1))
    if not keep and not classes:
        # passing runs keep only the small logs
        for f in ("floppy.img", "scsi.hd"):
            (rd / f).unlink(missing_ok=True)
        snap = rd / "mame" / "snap"
        if snap.exists():
            shutil.rmtree(snap, ignore_errors=True)
    return result


# ------------------------------------------------------------------------- judging


def load_samples(rd: Path) -> list[dict]:
    f = rd / "mame" / "monkey_samples.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def screen_text(s: dict) -> str:
    return "\n".join(r.replace(".", " ") for r in s["rows"])


def decode_records(data: bytes) -> list[dict]:
    out = []
    for i in range(RECORDS):
        r = data[i * RECORD:(i + 1) * RECORD]
        if len(r) < RECORD or r[0] == 0:
            continue
        start, end, length, wave = struct.unpack_from("<IIII", r, 0x14)
        out.append({"i": i, "name": r[:16], "stereo": r[0x13], "volume": r[0x11],
                    "tune": struct.unpack_from("<b", r, 0x12)[0], "start": start, "end": end,
                    "length": length, "wave": wave})
    return out


def record_problems(data: bytes) -> list[str]:
    """Sound-directory invariants: printable names, stereo 0/1, soft start <= end <=
    length, sample ranges inside sound RAM and pairwise disjoint."""
    recs = decode_records(data)
    problems = []
    spans = []
    for r in recs:
        tag = f"#{r['i']} {r['name'].decode('latin-1').rstrip()!r}"
        if any(c < 0x20 or c > 0x7E for c in r["name"]):
            problems.append(f"{tag} name bytes {r['name'].hex()}")
        if r["stereo"] not in (0, 1):
            problems.append(f"{tag} stereo={r['stereo']}")
        if not r["start"] <= r["end"] <= r["length"]:
            problems.append(f"{tag} start={r['start']} end={r['end']} length={r['length']}")
        span = (r["wave"], r["wave"] + r["length"] * (2 if r["stereo"] == 1 else 1))
        # length 0 is a state stock 3.16 itself makes (Edit Sound DELETE ZONE over
        # the whole sound; stock seed 48), so only a range past sound RAM is reported
        if span[1] > WAVE_WORDS:
            problems.append(f"{tag} wave={r['wave']} length={r['length']} outside sound RAM")
        spans.append((span, tag))
    spans.sort()
    for (a, ta), (b, tb) in zip(spans, spans[1:]):
        if b[0] < a[1]:
            problems.append(f"{ta} [{a[0]},{a[1]}) overlaps {tb} [{b[0]},{b[1]})")
    return problems


_images: dict = {}


def opcode_at(target: Target, ps: int, ip: int) -> bytes | None:
    """Three bytes of the target's load image at runtime PS:IP (None outside the image)."""
    if target.sys not in _images:
        from mods import route_c as rc
        _images[target.sys] = bytes(rc.MZ.parse(target.sys.read_bytes()).image)
    img = _images[target.sys]
    off = ((ps - target.load_segment) & 0xFFFF) * 16 + ip
    return img[off:off + 3] if 0 <= off < CODE_LIMIT else None


def is_trap(op: bytes, vec: int) -> bool:
    """Could this instruction raise vector `vec`? (DIV/IDIV, INT n, INT3, INTO, BOUND)"""
    b0 = op[0]
    if vec == 0 and b0 in (0xF6, 0xF7) and (op[1] >> 3) & 7 in (6, 7):
        return True
    if b0 == 0xCD and op[1] == vec:
        return True
    return (b0 == 0xCC and vec == 3) or (b0 == 0xCE and vec == 4) or (b0 == 0x62 and vec == 5)


def judge(work: Path, target: Target, rd: Path, meta: dict, screens: list, before_fat: dict) -> tuple[dict, dict]:
    """Failure classes of one run (empty dict = pass) and supporting details."""
    classes: dict = {}
    details: dict = {}
    mame = rd / "mame"
    if meta["error"]:
        kind = "MAME_TIMEOUT" if "killed after" in meta["error"] else "MAME_FAIL"
        classes[kind] = meta["error"][:300]
    samples = load_samples(rd)
    details["samples"] = len(samples)
    # ---- crash screen (BIOS ladder "System Error ... software bug of type XXh")
    for s in samples:
        txt = " ".join(s["rows"]).replace(".", " ")
        if any(c in txt for c in CRASH_TEXT):
            classes["CRASH"] = {"t": s["t"], "screen": s["rows"]}
            break
    # ---- liveness: the epilogue must reach Play/Record
    probe_times = meta["probe_times"]
    if screens:
        by_t = {round(x["time"], 3): x for x in screens}
        eps = [by_t.get(round(t, 3)) for t in probe_times]
        details["epilogue"] = [x["rows"][0] if x else None for x in eps]

        def is_main(x):
            return x is not None and "Play/Record" in x["rows"][0].replace(".", " ")
        main_ok = is_main(eps[0]) or is_main(eps[2])
        if not main_ok and len(eps) > 3 and is_main(eps[3]):
            details["epilogue_needed_soft4"] = eps[2]["rows"] if eps[2] else None
            main_ok = True
        if not main_ok and "CRASH" not in classes:
            tail = [x for x in samples if x["t"] >= meta["random_end"]]
            hashes = {x["hash"] for x in tail}
            # keys not consumed: the queue is full, or the epilogue's presses pile up
            # (at 1 s sampling a live UI task shows 0 queued keys)
            kq_full = bool(tail) and (all(x["kq"][0] >= x["kq"][1] > 0 for x in tail[-5:])
                                      or tail[-1]["kq"][0] >= 3)
            spread = max((x["pcs"] for x in tail[-5:]), default=0)
            frozen_from = None
            if samples:
                last_hash = samples[-1]["hash"]
                for smp in reversed(samples):
                    if smp["hash"] != last_hash:
                        break
                    frozen_from = smp["t"]
            info = {"rows": [x["rows"] for x in eps if x], "distinct_hashes_after_random_phase": len(hashes),
                    "key_queue_full_at_end": kq_full, "max_distinct_pcs_last5": spread,
                    "lcd_writes_after": sum(x["lcdw"] for x in tail), "top_pcs": [x["top"] for x in tail[-6:]],
                    "frozen_from": frozen_from}
            if kq_full or (tail and spread <= 2):
                classes["HANG"] = info            # keys not consumed, or the CPU spins in a few bytes
            elif len(hashes) <= 1:
                classes["STUCK_SCREEN"] = info    # keys consumed, but no epilogue key changes the screen
            else:
                classes["NOT_MAIN"] = info        # alive, but Stop/Main Screen/Soft Key 4 never reach Play/Record
    # ---- key queue saturated for a long stretch (UI task not reading keys)
    longest, run_start, cur = 0.0, None, None
    for s in samples:
        full = s["kq"][1] > 0 and s["kq"][0] >= s["kq"][1]
        if full and run_start is None:
            run_start = s["t"]
        if not full and run_start is not None:
            if s["t"] - run_start > longest:
                longest, cur = s["t"] - run_start, run_start
            run_start = None
    if run_start is not None and samples and samples[-1]["t"] - run_start > longest:
        longest, cur = samples[-1]["t"] - run_start, run_start
    details["kq_full_longest"] = [round(longest, 1), cur]
    if longest >= UI_BLOCK_LIMIT:
        classes["UI_BLOCKED"] = {"seconds": round(longest, 1), "from": cur}
    # ---- monkey.lua events and summaries
    ev = (mame / "monkey_events.log").read_text().splitlines() if (mame / "monkey_events.log").is_file() else []
    summaries = sorted(mame.glob("monkey_summary_*.json"), key=lambda p: float(p.stem.split("_")[-1]))
    if summaries:
        try:
            details["summary"] = json.loads(summaries[-1].read_text())
        except json.JSONDecodeError:
            pass
    ivt = [e for e in ev if " IVT " in e]
    if ivt:
        # The tap sees every read of IVT words 0-7: a vector fetch, or a data
        # read through a null far pointer.  The instruction at PS:IP tells them apart.
        traps, nulls = [], []
        for e in ivt:
            m = re.search(r"vec=(\d+) pc=([0-9A-F]{4}):([0-9A-F]{4})", e)
            op = opcode_at(target, int(m[2], 16), int(m[3], 16)) if m else None
            (traps if op is None or is_trap(op, int(m[1])) else nulls).append(f"{e} op={op.hex() if op else '?'}")
        if traps:
            classes["TRAP"] = traps[:10]
        if nulls:
            details["null_pointer_reads"] = nulls[:10]
    code_w = [e for e in ev if " CAVECODE " in e]
    if code_w:
        classes["CAVE_CODE_WRITE"] = code_w[:20]
    foreign = [e for e in ev if " CAVEFOREIGN " in e]
    if foreign and target.pmoney:
        # 3.16 routines fill cave buffers the cave passes them (file reads into
        # mute_staging / mute_read_header): data, by design.  Name the labels;
        # a label outside FOREIGN_OK is a failure.
        labels = cave_labels(target)
        syms = target.profile.symbols()
        pool = (syms["cave_pool"], syms["cave_pool_end"]) if "cave_pool_end" in syms else None

        def name(off: int) -> str:
            if pool and pool[0] <= off < pool[1]:
                return "cave_pool"
            return label_of(labels, off).split("+")[0]
        named = sorted({name(int(e.split()[2].split("=")[1], 16)) for e in foreign})
        details["cave_foreign_labels"] = named
        bad = [n for n in named if n not in FOREIGN_OK]
        if bad:
            classes["CAVE_FOREIGN_WRITE"] = {"labels": bad, "events": foreign[:20]}
    codew = [e for e in ev if " IMGCODE " in e]
    if codew:
        classes["IMAGE_CODE_WRITE"] = codew[:20]
    img = [e for e in ev if " IMGW " in e]
    if img:
        details["far_data_first_writes"] = img[:400]
    top = [e for e in ev if " TOPW " in e]
    if top:
        details["top_writes"] = top[:50]
        lowest = min(int(e.split()[2].split("=")[1], 16) for e in top)
        exact = (details.get("summary") or {}).get("top_min_image", -1)
        if exact is not None and exact >= 0:
            lowest = min(lowest, exact)
        info = {"lowest_image_offset": f"{lowest:05X}", "events": top[:20]}
        cave_end_image = 0x7E000 + h.cave_end(target.profile.map)
        info["above_cave_end_by"] = lowest - cave_end_image          # PMONEY's cave end (both OSes)
        # A write whose address is SS:SP of the writer, with SP above 8000h:
        # a task stack that ran below offset 0 and wrapped (16-bit SP).
        wraps = []
        for e in top:
            m = re.search(r"image=([0-9A-F]+) .* ss:sp=([0-9A-F]{4}):([0-9A-F]{4})", e)
            if m:
                img, ss, sp = int(m[1], 16), int(m[2], 16), int(m[3], 16)
                if sp >= 0x8000 and ((ss - target.load_segment) & 0xFFFF) * 16 + sp in range(img - 0x40, img + 0x40):
                    wraps.append(e)
        if wraps:
            info["stack_wrap"] = wraps[:10]
        classes["TOP_WRITE"] = info
    # ---- cave home vs the loader image (instruction bytes must not change)
    if target.pmoney:
        dumps = sorted(mame.glob("monkey_cave_*.bin"), key=lambda p: float(p.stem.split("_")[-1]))
        if dumps:
            home = target.profile.cave_home_image()
            code_file, _ = cave_layout(target, work)
            bits = code_file.read_bytes()
            ram = dumps[-1].read_bytes()
            labels = cave_labels(target)
            diff_code = [i for i in range(min(len(ram), len(home))) if ram[i] != home[i] and bits[i] == 49]
            diff_data = sorted({label_of(labels, i).split("+")[0]
                                for i in range(min(len(ram), len(home))) if ram[i] != home[i] and bits[i] != 49})
            details["cave_changed_data_labels"] = diff_data
            if diff_code:
                classes["CAVE_CODE_DIFF"] = [f"{i:04X} {label_of(labels, i)} {home[i]:02X}->{ram[i]:02X}"
                                             for i in diff_code[:30]]
        elif not meta["error"]:
            classes["NO_CAVE_DUMP"] = True
    # ---- sound directory sanity (both dumps)
    for path in sorted(mame.glob("monkey_records_*.bin"), key=lambda p: float(p.stem.split("_")[-1])):
        problems = record_problems(path.read_bytes())
        if problems:
            classes["SOUND_DIR"] = {"dump": path.name, "problems": problems[:20]}
            break
    # ---- floppy filesystem
    img_path = rd / "floppy.img"
    if img_path.is_file():
        try:
            report = fat12.check(img_path.read_bytes())
            details["fat"] = report
            if not (report["fat_copies_equal"] and report["chains_match_sizes"] and not report["lost_clusters"]):
                classes["FAT"] = report
        except Exception as exc:          # noqa: BLE001  cross-linked or unreadable
            classes["FAT"] = repr(exc)
    return classes, details


# ------------------------------------------------------------------------- campaign


def run_seed(work: Path, target: Target, seed: int, opts: Options, keep: bool = False) -> RunResult:
    actions = generate(seed, opts)
    r = run_actions(work, target, f"seed{seed}-{opts.tag()}", actions, opts, keep=keep)
    r.seed = seed
    rd = Path(r.dir)
    data = json.loads((rd / "result.json").read_text())
    data["seed"] = seed
    (rd / "result.json").write_text(json.dumps(data, indent=1))
    return r


def parse_seeds(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += range(int(a), int(b) + 1)
        elif part:
            out.append(int(part))
    return out


def soak(work: Path, seeds: list[int], bios_sets: list[str], oses: list[str], opts_for, workers: int,
         reverse: bool = False) -> list[dict]:
    """Every (target, seed) run; several soak processes may share one work
    directory: a run already finished, or whose samples were written in the
    last 10 minutes, is skipped when its turn comes."""
    tg = targets(work, bios_sets, oses)
    # make snapshots / fixtures / cave layout serially first
    for t in tg.values():
        if t.pmoney:
            cave_layout(t, work)
        boot_snapshot(work, t)
    jobs = {}
    for seed in (sorted(seeds, reverse=True) if reverse else seeds):
        opts = opts_for(seed)
        for label, t in tg.items():
            done = work / "runs" / label / f"seed{seed}-{opts.tag()}" / "result.json"
            if done.is_file() and json.loads(done.read_text()).get("sha256") == t.sha256:
                continue                  # finished earlier with the same payload: keep it
            if opts.scsi:
                scsi_fixture(work, t)
            jobs[(label, seed)] = (t, seed, opts)
    if not jobs:
        return []
    log = work / "results.jsonl"
    lock = threading.Lock()

    def go(key, job):
        t, seed, opts = job
        rd = work / "runs" / t.label / f"seed{seed}-{opts.tag()}"
        if (rd / "result.json").is_file():
            return {"label": t.label, "seed": seed, "skipped": "done"}
        samples = rd / "mame" / "monkey_samples.jsonl"
        if samples.is_file() and time.time() - samples.stat().st_mtime < 600:
            return {"label": t.label, "seed": seed, "skipped": "running elsewhere"}
        try:
            r = run_seed(work, t, seed, opts)
            row = {"label": t.label, "seed": seed, "tag": opts.tag(), "ok": r.ok, "classes": sorted(r.classes),
                   "wall": round(r.wall, 1), "emulated": round(r.emulated, 1), "dir": r.dir}
        except Exception as exc:          # noqa: BLE001  harness error: report, keep going
            row = {"label": t.label, "seed": seed, "tag": opts.tag(), "ok": False, "classes": ["HARNESS"],
                   "error": repr(exc)}
        with lock:
            with log.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(json.dumps(row), flush=True)
        return row

    res = h.run_parallel(jobs, go, workers)
    return list(res.values())


def default_opts(minutes: float, scsi_every: int):
    def f(seed: int) -> Options:
        return Options(minutes=minutes, midi=seed % 3 != 0, scsi=bool(scsi_every) and seed % scsi_every == 0)
    return f


def print_timeline(rd: Path, t0: float = 0.0, t1: float = 1e9, full: bool = False) -> None:
    """Actions (with their keys) interleaved with every screen change and every observer event."""
    items = []
    for a in json.loads((rd / "actions.json").read_text()):
        items.append((a["t"], 0, f"ACTION {a['kind']:15s} {a['desc']}"))
    prev = None
    for smp in load_samples(rd):
        rows = [r.replace(".", " ") for r in smp["rows"]]
        if smp["mode"] == 0x32:
            rows = [f"<graphics screen, hash {smp['hash']:08X}>"]
        if rows != prev:
            body = ("\n" + "\n".join("    |" + r + "|" for r in rows)) if full else f" {rows[0]!r} / {rows[-1]!r}"
            items.append((smp["t"], 1, f"SCREEN mode={smp['mode']:02X} kq={smp['kq']} top={smp['top']}{body}"))
        prev = rows
    ev = rd / "mame" / "monkey_events.log"
    if ev.is_file():
        for line in ev.read_text().splitlines():
            if " IMGW " in line or (" CAVEFOREIGN " in line and not full):
                continue
            items.append((float(line.split()[0]), 2, "EVENT " + line.split(" ", 1)[1]))
    for t, _, text in sorted(items):
        if t0 <= t <= t1:
            print(f"{t:9.3f} {text}")


# ------------------------------------------------------------------------- smoke (release gate)

# Fixed seeds whose actions reach every PMONEY page macro; a few emulated
# minutes each, PMONEY only, both BIOS sets (one per load segment).
SMOKE_SEEDS = (5, 6, 7)          # together they reach all 12 PMONEY macros in 3 minutes (generator 2)
SMOKE_MINUTES = 3.0


def smoke(work: Path, bios_sets: list[str], workers: int | None = None) -> dict:
    """Run the smoke seeds; return {run: classes} for every run that failed (empty: pass)."""
    tg = targets(work, bios_sets, ["pmoney"])
    for t in tg.values():
        cave_layout(t, work)
        boot_snapshot(work, t)
    opts = Options(minutes=SMOKE_MINUTES, midi=True, scsi=False)
    jobs = {(label, seed): (t, seed) for label, t in tg.items() for seed in SMOKE_SEEDS}

    def go(key, job):
        t, seed = job
        r = run_actions(work, t, f"seed{seed}-{opts.tag()}", generate(seed, opts), opts,
                        runs_dir=work / "smoke" / t.label)
        return r.classes

    res = h.run_parallel(jobs, go, workers)
    return {f"{label} seed {seed}": classes for (label, seed), classes in res.items() if classes}


def rejudge(work: Path, pattern: str = "runs/*/*/result.json") -> int:
    """Re-run judge() on finished runs (after a judging change); returns the count."""
    tgs: dict = {}
    n = 0
    for f in sorted(work.glob(pattern)):
        meta = json.loads(f.read_text())
        label = meta["target"]
        if label not in tgs:
            os_, bios = label.split("-", 1)
            tgs[label] = targets(work, [bios], [os_])[label]
        rd = f.parent
        sf = rd / "mame" / "screens.txt"
        screens = parse_screens(sf.read_text()) if sf.is_file() else []
        old_details = meta.get("details", {})
        classes, details = judge(work, tgs[label], rd, meta, screens, {})
        if "fat" not in details and "fat" in old_details:
            details["fat"] = old_details["fat"]
            if "FAT" in meta.get("classes", {}):
                classes["FAT"] = meta["classes"]["FAT"]
        meta.update(classes=classes, details=details, ok=not classes)
        f.write_text(json.dumps(meta, indent=1))
        n += 1
    return n


# ------------------------------------------------------------------------- comparison

# Classes that are the same failure seen through different observers.
_STUCK = {"HANG", "CRASH", "NOT_MAIN", "STUCK_SCREEN", "UI_BLOCKED"}
RELATED = {"HANG": _STUCK, "CRASH": _STUCK, "NOT_MAIN": _STUCK, "STUCK_SCREEN": _STUCK, "UI_BLOCKED": _STUCK}


def load_results(work: Path) -> list[dict]:
    """Every finished run under work/runs (result.json), newest per (label, name)."""
    out = []
    for f in sorted((work / "runs").glob("*/*/result.json")):
        try:
            out.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            pass
    return out


def compare(work: Path) -> dict:
    """PMONEY classes against the stock run of the same seed, BIOS and options."""
    runs = [r for r in load_results(work) if r["name"].startswith("seed")]
    by = {(r["label"], r["name"]): r for r in runs}
    rows = []
    for r in runs:
        if not r["label"].startswith("pmoney-"):
            continue
        bios = r["label"].split("-", 1)[1]
        st = by.get((f"stock-{bios}", r["name"]))
        pc, sc = set(r["classes"]), set(st["classes"]) if st else None
        verdict = {}
        for c in sorted(pc):
            if sc is None:
                verdict[c] = "no stock run"
            elif c in sc:
                verdict[c] = "also stock (same class)"
            elif sc & RELATED.get(c, {c}):
                verdict[c] = "also stock (related class)"
            else:
                verdict[c] = "PMONEY only"
        rows.append({"bios": bios, "name": r["name"], "pmoney": sorted(pc),
                     "stock": sorted(sc) if sc is not None else None, "verdict": verdict,
                     "emulated": r.get("emulated"), "pmoney_dir": r["dir"], "stock_dir": st["dir"] if st else None})
    emu = {"pmoney": 0.0, "stock": 0.0}
    for r in runs:
        emu[r["label"].split("-")[0]] += max(0.0, (r.get("random_end") or START) - START)
    # aggregated informational observations
    agg: dict = {"cave_changed_data_labels": set(), "cave_foreign_labels": set()}
    far = {"pmoney": {}, "stock": {}}
    ssmin = {"pmoney": {}, "stock": {}}
    for r in runs:
        os_ = r["label"].split("-")[0]
        d = r["details"]
        agg["cave_changed_data_labels"] |= set(d.get("cave_changed_data_labels", []))
        agg["cave_foreign_labels"] |= set(d.get("cave_foreign_labels", []))
        for e in d.get("far_data_first_writes", []):
            f = e.split()
            off = int(f[2].split("=")[1], 16) >> 8
            far[os_].setdefault(off, (f[0], f[5], r["name"], r["label"]))
        for ss, sp in (d.get("summary") or {}).get("ss_min_sp", {}).items():
            ssmin[os_][ss] = min(sp, ssmin[os_].get(ss, 0x10000))
    only = {f"{b << 8:05X}": v for b, v in sorted(far["pmoney"].items()) if b not in far["stock"]}
    return {"rows": rows, "random_phase_seconds": emu, "cave_changed_data_labels": sorted(agg["cave_changed_data_labels"]),
            "cave_foreign_labels": sorted(agg["cave_foreign_labels"]), "far_data_pmoney_only": only,
            "ss_min_sp": {k: {ss: f"{sp:04X}" for ss, sp in sorted(v.items())} for k, v in ssmin.items()}}


def coverage(work: Path, label_prefix: str = "pmoney-") -> dict:
    """How often PMONEY's own screens were on the LCD across finished runs (seconds
    of samples), and what the sound directory held at the end (CHOP / compress results)."""
    pages = {
        # the wave view and the Mute groups page are both graphics screens (mode 32h):
        # told apart by the macro whose window holds the sample
        "wave view (graphics, wave/chop macro)": lambda x: x["mode"] == 0x32 and x["kind"] in ("wave_view", "chop"),
        "Mute groups (graphics, mute macro)": lambda x: x["mode"] == 0x32 and x["kind"] == "mute",
        "graphics screen, other macro": lambda x: x["mode"] == 0x32 and x["kind"] not in ("wave_view", "chop", "mute"),
        "Edit Sound": lambda x: "Edit Snd:" in x["rows"][0],
        "Compress Sound": lambda x: "Compress Sound" in x["rows"][0],
        "System Information": lambda x: "PMONEY" in x["rows"][2] and "Sound memory free" in x["rows"][3],
        "Extra Settings": lambda x: "Extra Settings" in x["rows"][0],
        "Sync In / Sync Out": lambda x: "Sync In" in x["rows"][0],
        "Timing Correct": lambda x: "Timing Correct" in x["rows"][0],
        "Erase all confirmation": lambda x: "rase" in x["rows"][0] and "all" in " ".join(x["rows"]).lower(),
        "Disk 9 pages": lambda x: any(k in x["rows"][0] for k in ("Copy, Format", "Format a", "Format Hard",
                                                                  "SCSI Status", "Copy SCSI", "Copy a Floppy")),
    }
    secs = {k: 0 for k in pages}
    runs = zones = compressed = 0
    for f in sorted((work / "runs").glob(f"{label_prefix}*/seed*/result.json")):
        runs += 1
        rd = f.parent
        acts = json.loads((rd / "actions.json").read_text())
        for x in load_samples(rd):
            if x["t"] < START:
                continue
            kind = next((a["kind"] for a in reversed(acts) if a["t"] <= x["t"]), "")
            x = {**x, "kind": kind, "rows": [r.replace(".", " ") for r in x["rows"]]}
            for k, fn in pages.items():
                try:
                    if fn(x):
                        secs[k] += SAMPLE
                except IndexError:
                    pass
        recs = sorted((rd / "mame").glob("monkey_records_*.bin"))
        if recs:
            names = [r["name"].decode("latin-1").strip() for r in decode_records(recs[-1].read_bytes())]
            zones += sum(n.startswith("ZONE") for n in names)
            compressed += sum(1 for r in decode_records(recs[-1].read_bytes()) if r["tune"] <= -120)
    return {"runs": runs, "seconds_on_page": secs, "zone_sounds_at_end": zones,
            "sounds_with_tune_le_-120_at_end": compressed}


# ------------------------------------------------------------------------- shrinking


def failure_time(cls: str, info) -> float | None:
    """Emulated time at which a class first showed, when the observer recorded one."""
    try:
        if cls in ("CRASH",):
            return float(info["t"])
        if cls in ("HANG", "STUCK_SCREEN", "NOT_MAIN"):
            return float(info["frozen_from"]) if info.get("frozen_from") else None
        if cls == "UI_BLOCKED":
            return float(info["from"])
        if isinstance(info, list) and info and isinstance(info[0], str):
            return float(info[0].split()[0])
        if isinstance(info, dict) and info.get("events"):
            return float(info["events"][0].split()[0])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return None


def compact(actions: list[Action], start: float = START, gap: float = 1.0) -> list[Action]:
    """The same actions back to back from `start`, each keeping its own inner timing."""
    out, t = [], start
    for a in actions:
        d = t - a.t
        out.append(Action(a.t + d, a.kind, a.desc, [(x + d, b) for x, b in a.panel],
                          [(x + d, b) for x, b in a.midi], a.end + d))
        t = a.end + d + gap
    return out


def shrink(work: Path, target: Target, actions: list[Action], name: str, opts: Options, cls: str, workers: int,
           max_rounds: int = 10, fail_at: float | None = None) -> list[Action]:
    """Delta-debug `actions` (a failing run's actions.json) to a small list that still shows `cls`.

    1. Prefix: the actions that start before the failure time (`fail_at`,
       from the original run's observer), else the shortest failing prefix
       of a 10 % grid.
    2. ddmin over that prefix, `workers` candidates per round in parallel;
       remaining actions keep their absolute times.
    3. Compaction: the survivors back to back from START (1 s apart), kept
       if it still fails, so the reported sequence has no idle gaps.
    Every candidate is a full MAME run of the same target and options;
    history.json in the shrink directory lists them all."""
    sd = work / "shrink" / f"{target.label}-{name}-{cls}"
    sd.mkdir(parents=True, exist_ok=True)
    counter = [0]
    lock = threading.Lock()
    history = []

    def fails(cand: list[Action], tag: str = "") -> bool:
        with lock:
            counter[0] += 1
            n = counter[0]
        r = run_actions(work, target, f"try{n:03d}{tag}", cand, opts, runs_dir=sd)
        ok = cls in r.classes
        with lock:
            history.append({"try": n, "tag": tag, "actions": len(cand), "fails": ok, "classes": sorted(r.classes),
                            "kinds": [a.kind for a in cand] if len(cand) <= 12 else None})
            (sd / "history.json").write_text(json.dumps(history, indent=1))
        if not ok:
            shutil.rmtree(r.dir, ignore_errors=True)
        return ok

    def batch(cands: list[list[Action]], tag: str = "") -> list[bool]:
        res = h.run_parallel({i: c for i, c in enumerate(cands)}, lambda i, c: fails(c, tag), workers)
        return [res[i] for i in range(len(cands))]

    cur = None
    if fail_at is not None:
        pre = [a for a in actions if a.t <= fail_at]
        if pre and batch([pre], "-prefix")[0]:
            cur = pre
    if cur is None:
        n = len(actions)
        grid = sorted({max(1, round(n * f)) for f in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)} | {n})
        oks = batch([actions[:k] for k in grid[:-1]], "-grid")
        k = next((g for g, ok in zip(grid, oks) if ok), n)
        cur = actions[:k]
    gran, rounds = 2, 0
    while len(cur) >= 2 and rounds < max_rounds:
        rounds += 1
        size = max(1, -(-len(cur) // gran))
        chunks = [cur[i:i + size] for i in range(0, len(cur), size)]
        cands = [[a for j, c in enumerate(chunks) if j != i for a in c] for i in range(len(chunks))]
        if gran > 2:
            cands += chunks                  # ddmin also tries each chunk alone
        oks = batch(cands, f"-r{rounds}")
        hit = next((c for c, ok in zip(cands, oks) if ok), None)
        if hit is not None:
            cur = hit
            gran = 2 if len(hit) <= size else max(gran - 1, 2)
            continue
        if gran >= len(cur):
            break
        gran = min(len(cur), gran * 2)
    (sd / "minimal.json").write_text(json.dumps([a.to_json() for a in cur], indent=1))
    tight = compact(cur)
    if batch([tight], "-compact")[0]:
        cur = tight
        (sd / "minimal_compact.json").write_text(json.dumps([a.to_json() for a in cur], indent=1))
    return cur


# ------------------------------------------------------------------------- CLI


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, default=Path(os.environ.get("MONKEY_WORK", DEFAULT_WORK)))
    ap.add_argument("--workers", type=int, default=h.WORKERS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("soak")
    s.add_argument("--seeds", default="1-8")
    s.add_argument("--minutes", type=float, default=5.0)
    s.add_argument("--bios", default="default,v308")
    s.add_argument("--os", default="pmoney,stock")
    s.add_argument("--scsi-every", type=int, default=0, help="every Nth seed attaches a SCSI disk (0: never)")
    s.add_argument("--reverse", action="store_true", help="highest seeds first (a second soak process)")
    o = sub.add_parser("one")
    o.add_argument("--os", default="pmoney")
    o.add_argument("--bios", default="default")
    o.add_argument("--seed", type=int, required=True)
    o.add_argument("--minutes", type=float, default=5.0)
    o.add_argument("--no-midi", action="store_true")
    o.add_argument("--scsi", action="store_true")
    o.add_argument("--actions", type=Path, help="replay this actions.json / minimal.json instead of the seed")
    o.add_argument("--pixels", default="", help="extra probe times (screens + pixels)")
    o.add_argument("--cold", action="store_true", help="boot cold instead of resuming the boot snapshot")
    o.add_argument("--name", default=None, help="run directory name")
    k = sub.add_parser("shrink")
    k.add_argument("--run", type=Path, required=True, help="a failing run directory (actions.json, result.json)")
    k.add_argument("--os", default=None, help="shrink on this OS instead of the run's (pmoney/stock)")
    k.add_argument("--cls", required=True)
    g = sub.add_parser("show")
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--minutes", type=float, default=5.0)
    g.add_argument("--no-midi", action="store_true")
    sm = sub.add_parser("smoke", help="release gate: SMOKE_SEEDS on PMONEY, SMOKE_MINUTES each, both BIOS sets")
    sm.add_argument("--bios", default="default,v308")
    sub.add_parser("summary")
    sub.add_parser("compare")
    sub.add_parser("coverage")
    rj = sub.add_parser("rejudge", help="re-run the judge on finished runs")
    rj.add_argument("--pattern", default="runs/*/*/result.json")
    tl = sub.add_parser("timeline", help="actions interleaved with screen changes of one run")
    tl.add_argument("--run", type=Path, required=True)
    tl.add_argument("--from", dest="t0", type=float, default=0.0)
    tl.add_argument("--to", dest="t1", type=float, default=1e9)
    tl.add_argument("--full", action="store_true", help="print whole screens, not only the title row")
    a = ap.parse_args()
    work = a.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if a.cmd == "soak":
        soak(work, parse_seeds(a.seeds), a.bios.split(","), a.os.split(","),
             default_opts(a.minutes, a.scsi_every), a.workers, reverse=a.reverse)
        return 0
    if a.cmd == "smoke":
        failures = smoke(work, a.bios.split(","), a.workers)
        print("SMOKE", "FAIL" if failures else "OK", json.dumps(failures, indent=1))
        return 1 if failures else 0
    if a.cmd == "show":
        for act in generate(a.seed, Options(a.minutes, not a.no_midi)):
            print(f"{act.t:8.2f} {act.end:8.2f} {act.kind:15s} {act.desc}")
        return 0
    if a.cmd == "summary":
        rows = [json.loads(x) for x in (work / "results.jsonl").read_text().splitlines()]
        for r in rows:
            print(r["label"], r["seed"], r["tag"], "ok" if r["ok"] else ",".join(r["classes"]))
        return 0
    if a.cmd == "rejudge":
        print("rejudged", rejudge(work, a.pattern))
        return 0
    if a.cmd == "coverage":
        print(json.dumps(coverage(work), indent=1))
        return 0
    if a.cmd == "timeline":
        print_timeline(a.run, a.t0, a.t1, a.full)
        return 0
    if a.cmd == "compare":
        c = compare(work)
        (work / "compare.json").write_text(json.dumps(c, indent=1, default=str))
        for row in c["rows"]:
            if row["pmoney"] or row["stock"]:
                print(row["bios"], row["name"], "pmoney:", ",".join(row["pmoney"]) or "-",
                      "| stock:", ",".join(row["stock"] or []) or "-", "|", row["verdict"])
        print("random-phase emulated minutes:", {k: round(v / 60, 1) for k, v in c["random_phase_seconds"].items()})
        print("runs compared:", len(c["rows"]))
        return 0
    if a.cmd == "shrink":
        meta = json.loads((a.run / "result.json").read_text())
        opts = Options(**meta["opts"])
        os_, bios = meta["target"].split("-", 1)
        os_ = a.os or os_
        t = targets(work, [bios], [os_])[f"{os_}-{bios}"]
        acts = [Action.from_json(x) for x in json.loads((a.run / "actions.json").read_text())]
        info = meta["classes"].get(a.cls)
        cur = shrink(work, t, acts, meta["name"], opts, a.cls, a.workers,
                     fail_at=failure_time(a.cls, info) if info is not None and os_ == meta["target"].split("-")[0]
                     else None)
        for act in cur:
            print(f"{act.t:8.2f} {act.kind:15s} {act.desc}")
        return 0
    opts = Options(a.minutes, not a.no_midi, a.scsi)
    t = targets(work, [a.bios], [a.os])[f"{a.os}-{a.bios}"]
    if a.cmd == "one":
        pixels = [float(x) for x in a.pixels.split(",") if x]
        if a.actions:
            acts = [Action.from_json(x) for x in json.loads(a.actions.read_text())]
            name = a.name or f"replay-{a.actions.parent.name}-{a.actions.stem}" + ("-cold" if a.cold else "")
        else:
            acts = generate(a.seed, opts)
            name = a.name or f"seed{a.seed}-{opts.tag()}" + ("-cold" if a.cold else "")
        r = run_actions(work, t, name, acts, opts, keep=True, pixels=pixels, cold=a.cold)
        print(json.dumps({"ok": r.ok, "classes": r.classes, "dir": r.dir, "wall": round(r.wall, 1),
                          "emulated": r.emulated}, indent=1, default=str))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
