#!/usr/bin/env python3
"""Per-event cycle budgets of PMONEY (OS 3.16 + cave) against stock OS 3.16.

    python3 -m emu.cycle_budget                  # PMONEY runs, metrics, budgets
    python3 -m emu.cycle_budget --refresh-stock  # also re-measure stock 3.16 and rewrite
                                                 # the stock column and stock-relative budgets
    python3 -m unittest emu.test_cycle_budget -v # the release-gate test

Workloads of the PMONEY re-profile (notes/performance.md) at the physical CPU
clock (NEC_CPU_DIV=2) on the Vailixi 3.50 BIOS set (load segment L = 6900).  At
that clock the 3.16 floppy boot reaches the SCSI search by 50 s, so Soft Key 4 is
at T0 = 51 and every run boots cold (the harness's boot snapshots are DIV=1).

Each run records the fork's nec_prof windows (NEC_PROF_DIR / NEC_PROF_WINDOWS).
Worst cases use trace points (NEC_TRACE_AT) in a second run of the same workload:
every CLI, STI, POPF, IRET and INT the profile pass executed, the eight hardware
ISR entries of the live IVT, the tick ISR's final CLI and task 2's exits.  POPF and
IRET record the flags they pop.  Cycle counts are deterministic for one MAME build
and input set (repeated runs give identical counts), so the budgets in
emu/fixtures/cycle_budget_316.json are tight.  Times are cycles / 16 MHz.

Addresses: 3.16 image offset o is physical 0x300000 + L*16 + o (3.16 keeps the
loader's third PGR); cave labels come from the payload map (profile.cave_phys).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import deque
from pathlib import Path

from emu import harness as h
from emu import pgm as pgm_fixture
from emu.mpc3k import BUILD, M3K316, run
from emu.panel import MIDIIN_START, dial, pad_hit, panel_pad, write_smf
from emu.snd import disk, sine, sine441, snd

OUT = BUILD / "emu" / "cycle-budget"
BUDGETS = Path(__file__).resolve().parent / "fixtures" / "cycle_budget_316.json"
BIOS = "vailixi"
L = 0x6900
BASE = h.PHYS_316 + L * 16
CPU_HZ = 16_000_000
T0 = 51.0                       # Soft Key 4 cancels the SCSI search (DIV=2 boot)
REC = 69.0                      # Rec + Play: 2 bars recorded from MIDI In 1
# Waits that are not work: 3.16 key waits and 3.16's BIOS-copy floppy completion polls.
IDLE_LOOPS = ((0x2D0DB, 0x2D0EB), (0x2D0BA, 0x2D0C2), (0x2D175, 0x2D17D), (0x1FCA, 0x1FE0), (0x1E00, 0x1E08))
IMAGE_END = 0x6D59B             # end of the 3.16 load image (img offsets)

# 3.16 image offsets (Vailixi counterparts in notes/performance.md)
TICK_BODY = 0x42342             # 422F:0052 playback tick body (Vx EC05:0043)
NOTE_BUILDER = 0x20EDD          # 20ED:000D (Vx CFC6:0007)
STOCK_LOOKUP = 0x3020B          # 301D:003B stock pad lookup
INT43 = 0x1736                  # 0009:16A6 3.16 BIOS-copy INT 43
PR_REDRAW = 0x159C8             # Play/Record field redraw
FREE_CLUSTER = 0x1632           # 0009:15A2 FAT12 free-cluster search
REVERSE = 0xD0D9                # 0B72:19B9 Edit Sound REVERSE ZONE
SILENCE = 0xD399                # 0B72:1C79 Edit Sound SILENCE ZONE
STOCK_BLIT = 0x17401            # 1650:0F01
DSP_START = (0x2325, 0x004C)    # OUT 62h at each voice set-up (img 0x2329C)
LONG_FRAMES = 220_500
# Trace points.  Hardware ISR entries from the live IVT (08..0F), task 2 exits, the
# tick ISR's final CLI (2C45:085C).
ISRS = {0x2B50C: "isr08", 0x2C45C: "isr09", 0x019FD: "isr0a", 0x020D3: "isr0b", 0x2C08E: "isr0c",
        0x2B73B: "isr0d", 0x2C1F0: "isr0e", 0x019DE: "isr0f"}
EXTRA = {0x4231F: "t2out", 0x42341: "t2out", 0x2CCAC: "t9end"}
IF_OPS = {0xFA: "cli", 0xFB: "sti", 0x9D: "popf", 0xCF: "iret", 0xCD: "int"}

taps = h.taps


# ------------------------------------------------------------------ fixtures
def fixtures() -> dict[str, Path]:
    d = OUT / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    tone = d / "TEST.SND"
    tone.write_bytes(snd("TEST", [sine(2205)]))
    out = {"tone": tone}
    for name, mute in (("off", False), ("on", True)):
        p = d / f"MUTE{name.upper()}.PGM"
        p.write_bytes(pgm_fixture.for_sound(tone.read_bytes(), pads=range(64), enabled=mute,
                                            groups=[1 + pad % 4 for pad in range(64)], program_name="PROF MUTE"))
        out[name] = p
    s = d / "SINE441.SND"
    s.write_bytes(snd("SINE441", sine441()))
    out["sine"] = s
    long_ = d / "LONG.SND"
    long_.write_bytes(snd("LONG", [[round(30000 * (i / LONG_FRAMES) * math.sin(2 * math.pi * i / 100))
                                    for i in range(LONG_FRAMES)]]))
    out["long"] = long_
    stock = d / "M3K316.SYS"
    stock.write_bytes(M3K316.read_bytes())
    out["stock"] = stock
    return out


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def midi_file(path: Path, events: list[tuple[float, bytes, str]]) -> Path:
    """SMF for MIDI In 1.  kind 'm': a channel message as is; 'x': raw bytes as one
    F7-escape event, which MAME transmits (after an F7) back to back at 31,250 baud."""
    track = bytearray(b"\x00\xff\x51\x03\x0f\x42\x40")
    last = 0
    for at, msg, kind in sorted(events, key=lambda e: e[0]):
        tick = max(0, round((at - MIDIIN_START) * 1000))
        track += _vlq(tick - last)
        last = tick
        track += msg if kind == "m" else b"\xf7" + _vlq(len(msg)) + msg
    track += b"\x00\xff\x2f\x00"
    path.write_bytes(b"MThd" + (6).to_bytes(4, "big") + b"\x00\x00\x00\x01\x03\xe8"
                     + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track))
    return path


# ------------------------------------------------------------------ workloads
def load_first(t: float) -> list:
    """Disk, 7, <Load> (first file), <Load it> (the program and its sounds), Main Screen."""
    return taps((t, "disk"), (t + 1, "7"), (t + 5, "soft1"), (t + 9, "soft1"), (t + 14, "main_screen"))


def chords(start: float, end: float) -> list[tuple[float, bytes]]:
    """Four-note chords every 16th at 120 BPM (MIDI In 1, channel 1, notes 37..52)."""
    ev, i, t = [], 0, start
    while t < end:
        for j in range(4):
            n = 37 + (i * 4 + j) % 16
            ev += [(t, bytes((0x90, n, 100))), (t + 0.06, bytes((0x80, n, 0)))]
        i += 1
        t = start + i * 0.125
    return ev


RECORD = [(REC, "Y7", "Rec", 0.3), (REC + 0.1, "Y7", "Play", 0.1)]


def sync_page(t: float, steps: int, tempo300: bool) -> tuple[list, float, float]:
    """Tempo 300 (optional), Sync page: MIDI clock and MIDI tm code dialled `steps`
    (1 = OUT A, 5 = ALL).  Returns (events, Play Start time, Sync page screen time)."""
    ev = taps((t, "tempo_sync"))
    if tempo300:
        ev += taps((t + 1.0, "3"), (t + 1.4, "0"), (t + 1.8, "0"), (t + 2.2, "enter"))
        t += 3.0
    ev += taps((t + 1.0, "soft1"), (t + 2.5, "right")) + dial(steps, t + 3.0, gap=0.1)
    ev += taps((t + 4.0, "down")) + dial(steps, t + 4.5, gap=0.1) + taps((t + 5.5, "main_screen"))
    return ev, t + 7.0, t + 5.3


def flood(kind: str, seconds: float) -> bytes:
    """Full-rate MIDI In 1 data: CC running status, poly aftertouch running status,
    or 1,024-byte sysex messages back to back."""
    n = int(3125 * seconds)
    body = bytearray()
    if kind == "cc":
        body.append(0xB0)
        while len(body) < n:
            body += bytes((0x03, len(body) & 0x7F))
    elif kind == "pressure":
        body.append(0xA0)
        while len(body) < n:
            body += bytes((37 + len(body) % 16, len(body) & 0x7F))
    elif kind == "sysex":
        while len(body) < n:
            body += b"\xf0\x7d" + bytes(i & 0x7F for i in range(1020)) + b"\xf7"
        return bytes(body)
    else:
        raise ValueError(kind)
    return bytes(body[:n])


MIDI_CHORDS = [69.0 + k for k in range(6)]      # 16-note MIDI chords, stopped
PAD_CHORDS = [76.0 + k for k in range(6)]       # 16-pad panel chords, stopped
FLOODS = (("stopped_cc", "cc", 83.0, 3.0), ("stopped_pressure", "pressure", 87.0, 3.0),
          ("stopped_sysex", "sysex", 91.0, 3.0))


def midi_job(floppy, fx, mute: str, floods: bool = True) -> dict:
    """MUTE.PGM loaded, transport stopped: six MIDI chords, six pad chords, then
    full-rate CC / aftertouch / sysex floods.  The probe logs OUT 62h (voice set-up)."""
    panel = taps((T0, "soft4")) + load_first(53.0)
    midi = []
    for t in MIDI_CHORDS:
        midi += [(t, bytes((0x90, 37 + j, 100)), "m") for j in range(16)]
        midi += [(t + 0.5, bytes((0x80, 37 + j, 0)), "m") for j in range(16)]
    for t in PAD_CHORDS:
        for p in range(1, 17):
            panel += pad_hit(panel_pad(p), t, 100, 0.3)
    windows = {"midichord": (68.9, 75.0), "padchord": (75.9, 82.0)}
    if floods:
        for name, kind, at, sec in FLOODS:
            data = flood(kind, sec)
            midi.append((at, data, "x"))
            windows[name] = (at + 0.1, at + 0.1 + len(data) / 3125.0)
    return {"disk": floppy(f"midi{mute}", [(fx[mute], "MUTE.PGM"), (fx["tone"], "TEST.SND")]),
            "panel": panel, "midi": midi, "windows": windows, "io": [0x62]}


def jobs(build: str, fx: dict, profile: h.Profile) -> dict[str, dict]:
    """Workload name -> job for build 'stock' or 'pmoney'."""
    def floppy(name, files):
        if build == "pmoney":
            return h.wave_disk(profile, f"budget-{name}", files)
        return disk(f"budget-stock-{name}", [(fx["stock"], "STARTUP.SYS"), *files])

    pgm = [(fx["off"], "MUTE.PGM"), (fx["tone"], "TEST.SND")]
    rec = [(t, m, "m") for t, m in chords(REC + 0.2, REC + 4.0)]
    out: dict[str, dict] = {}
    out["idle"] = {"disk": floppy("idle", []), "panel": taps((T0, "soft4")), "windows": {"idle": (56.0, 66.0)},
                   "screens": {58.0: ["Play/Record", "BPM:120.0"]}}
    out["seq"] = {"disk": floppy("seq", pgm), "midi": rec, "press": RECORD + [(75.5, "Y7", "Play Start", 0.1),
                                                                             (90.0, "Y7", "Play Start", 0.1)],
                  "panel": (taps((T0, "soft4")) + load_first(53.0) + taps((REC + 5.0, "stop"))
                            + taps((85.0, "stop"), (86.0, "tempo_sync"), (87.0, "3"), (87.4, "0"), (87.8, "0"),
                                   (88.2, "enter"), (89.0, "main_screen"), (99.5, "stop"))),
                  "windows": {"play120": (76.5, 84.5), "play300": (91.0, 99.0)},
                  "screens": {80.0: ["BPM:120.0", "Bars:  2"], 95.0: ["BPM:300.0", "Bars:  2"]},
                  "ticks": {"play120": 1536, "play300": 3840}, "trace": True}
    # Every feature on.  PMONEY: mute-group program, MIDI clock and MTC to ALL four
    # outputs, 300 BPM.  Stock: the same with OUT A (the most it can send).
    steps, field = (5, "ALL") if build == "pmoney" else (1, "OUT A")
    page, play, at = sync_page(76.0, steps, True)
    out["allon"] = {"disk": floppy("allon", [(fx["on" if build == "pmoney" else "off"], "MUTE.PGM"),
                                             (fx["tone"], "TEST.SND")]),
                    "panel": taps((T0, "soft4")) + load_first(53.0) + taps((REC + 5.0, "stop")) + page
                    + taps((play + 10.0, "stop")),
                    "midi": rec, "press": RECORD + [(play, "Y7", "Play Start", 0.1)],
                    "windows": {"allon300": (play + 1.0, play + 9.0)},
                    "screens": {at: [f"MIDI clock:{field}", f"MIDI tm code:{field}"], play + 5.0: ["BPM:300.0"]},
                    "ticks": {"allon300": 3840}, "trace": True}
    page, play, at = sync_page(76.0, 1, False)
    out["synca"] = {"disk": floppy("synca", pgm),
                    "panel": taps((T0, "soft4")) + load_first(53.0) + taps((REC + 5.0, "stop")) + page
                    + taps((play + 10.0, "stop")),
                    "midi": rec, "press": RECORD + [(play, "Y7", "Play Start", 0.1)],
                    "windows": {"synca120": (play + 1.0, play + 9.0)},
                    "screens": {at: ["MIDI clock:OUT A", "MIDI tm code:OUT A"], play + 5.0: ["BPM:120.0"]},
                    "ticks": {"synca120": 1536}}
    out["midi"] = midi_job(floppy, fx, "off")
    if build == "pmoney":
        out["midi_mute"] = midi_job(floppy, fx, "on", floods=False)
    tour = ["disk", "program_sounds", "mixer_effects", "midi", "song", "other", "edit", "step_edit", "main_screen",
            "tempo_sync", "main_screen", "help", "main_screen", "disk", "main_screen"]
    ui = taps((T0, "soft4")) + taps(*[(53.0 + i, k) for i, k in enumerate(tour)])
    for i in range(8):
        ui += h.burst(9 if i % 2 == 0 else -9, 69.0 + i)
    out["ui"] = {"disk": floppy("ui", []), "panel": ui, "windows": {"ui_tour": (52.9, 68.5), "ui_dial": (68.9, 77.5)},
                 "screens": {78.0: ["Play/Record"]}}
    # Edit Sound on LONG.SND (220,500 frames): Zone end = 5 s, then Do REVERSE and
    # Do SILENCE (Do list order differs: stock 7 / -1, PMONEY 9 / -1 from COPY).
    rev = 7 if build == "stock" else 9
    edit = taps((T0, "soft4"), (53.0, "disk"), (54.0, "7"), (58.0, "soft1"), (84.0, "program_sounds"), (85.5, "6"))
    edit += taps(*[(88.0 + i * 0.25, "right") for i in range(10)]) + dial(5, 91.0, gap=0.1)
    edit += taps(*[(93.0 + i * 0.2, "right") for i in range(6)])
    edit += dial(rev, 96.0, gap=0.1) + taps((97.5, "soft4")) + dial(-1, 108.0, gap=0.1) + taps((109.5, "soft4"))
    out["editdo"] = {"disk": floppy("editdo", [(fx["long"], "LONG.SND")]), "panel": edit,
                     "windows": {"do_reverse": (97.4, 107.4), "do_silence": (109.4, 119.4)},
                     "screens": {92.5: ["Zone end:005.000.00"], 97.3: ["Do:REVERSE ZONE"],
                                 108.9: ["Do:SILENCE ZONE"]}}
    out["disk"] = {"disk": floppy("disk", [(fx["long"], "LONG.SND")]),
                   "panel": taps((T0, "soft4"), (53.0, "disk"), (54.0, "7"), (58.0, "soft1"),
                                 (86.0, "disk"), (87.5, "3"), (90.0, "soft1"), (92.0, "soft3")),
                   "windows": {"disk_save": (92.0, 120.0)}}
    if build == "pmoney":
        from emu.test_harness_lifecycle import four_zones
        V = 72.0

        def bursts(start, n):
            ev = []
            for i in range(n):
                ev += h.burst(9 if i % 2 == 0 else -9, start + i)
            return ev
        open_view = taps((T0, "soft4"), (53.0, "disk"), (54.0, "7"), (58.0, "soft1"), (67.0, "program_sounds"),
                         (68.0, "6"), (70.5, "help"))
        view = (open_view + bursts(V + 3, 6) + taps((V + 10, "soft3")) + bursts(V + 12, 6)
                + taps(*[(V + 19 + i, "up") for i in range(4)]) + taps((V + 24, "soft3")) + four_zones(V + 29)
                + taps((V + 35, "soft4")))
        out["view"] = {"disk": floppy("view", [(fx["sine"], "SINE441.SND")]), "panel": view,
                       "windows": {"wheel_full": (V + 2.9, V + 9.5), "wheel_fine": (V + 11.9, V + 18.5),
                                   "zoom": (V + 18.9, V + 23.5), "zones": (V + 28.9, V + 34.5)}}
        out["viewzoom"] = {"disk": floppy("viewzoom", [(fx["sine"], "SINE441.SND")]),
                           "panel": open_view + taps((V + 3, "soft3"), (V + 5, "down"), (V + 6, "down"))
                           + bursts(V + 8, 6),
                           "windows": {"wheel_fine64": (V + 7.9, V + 14.5)}}
    return out


# ------------------------------------------------------------------ running
def run_dir(build: str, name: str, trace: bool = False) -> Path:
    return OUT / build / (f"{name}-trace" if trace else name)


def execute(build: str, name: str, job: dict, profile: h.Profile, points: str | None = None) -> Path:
    """Profile pass (points None) or trace pass (NEC_TRACE_AT = points over the job's windows)."""
    out = run_dir(build, name, points is not None)
    windows = sorted(job["windows"].items(), key=lambda kv: kv[1][0])
    env = {"NEC_CPU_DIV": "2"}
    if points is None:
        env.update(NEC_PROF_DIR=str(out), NEC_PROF_WINDOWS=",".join(f"{s}:{e}" for _, (s, e) in windows))
    else:
        env.update(NEC_TRACE_FILE=str(out / "points.trace"), NEC_TRACE_FROM=str(windows[0][1][0]),
                   NEC_TRACE_AT=points)
    (OUT / build).mkdir(parents=True, exist_ok=True)
    extra = []
    if job.get("midi"):
        extra += ["-midiin1", str(midi_file(OUT / build / f"{name}-midi.mid", job["midi"]))]
    end = max(e for _, (_, e) in windows) + 0.3
    times = sorted(set(list(job.get("screens", {})) + [end]))
    screens = run(BIOS, times, out, floppy=job["disk"], panel=write_smf(OUT / build / f"{name}-panel.mid", job["panel"]),
                  extra=extra, env=env, rompath=profile.rompath, press=job.get("press"),
                  trace=job.get("io") if points is None else None)
    (out / "windows.json").write_text(json.dumps({k: list(v) for k, v in windows}))
    (out / "screens.json").write_text(json.dumps(screens))
    return out


def memory(build: str, profile: h.Profile) -> tuple[bytes, int]:
    """(bytes, physical address of byte 0) the build executes from: 3.16 image (+ cave home)."""
    from mods import route_c as rc
    if build == "pmoney":
        mem, _ = rc.simulate(profile.sys.read_bytes(), L, home=h.CAVE_HOME_316, cave_len=h.cave_copy_end(profile.map))
        return bytes(mem), h.PHYS_316
    return bytes(rc.MZ.parse(M3K316.read_bytes()).image), BASE


def if_points(build: str, profile: h.Profile, names: list[str]) -> tuple[str, int]:
    """NEC_TRACE_AT spec from the profile pass: every executed IF-changing instruction plus
    the ISR entries and task-2 exits; and the cycles executed outside the known code."""
    mem, origin = memory(build, profile)
    cave_lo = profile.cave_phys if build == "pmoney" else None
    cave_hi = cave_lo + h.cave_copy_end(profile.map) if cave_lo else None
    tags: dict[int, list[str]] = {}
    outside = 0
    for name in names:
        for w in windows_of(run_dir(build, name)).values():
            for a, c in w["addr"].items():
                known = BASE <= a < BASE + IMAGE_END or (cave_lo is not None and cave_lo <= a < cave_hi)
                if not known:
                    outside += c
                    continue
                op = IF_OPS.get(mem[a - origin])
                if op:
                    tags.setdefault(a, []).append(op)
    for off, tag in {**ISRS, **EXTRA}.items():
        tags.setdefault(BASE + off, []).insert(0, tag)
    spec = []
    for a, t in sorted(tags.items()):
        item = ",s0:2" if "popf" in t else ",s4:2" if "iret" in t else ""
        spec.append(f"{a:X}={'+'.join(dict.fromkeys(t))}{item}")
    return ";".join(spec), outside


# ------------------------------------------------------------------ analysis
def load_window(path: Path) -> dict:
    w = {"addr": {}, "incl": {}, "vec": {}}
    for line in path.read_text().splitlines():
        f = line.split()
        if not f or f[0] == "#":
            continue
        if f[0] == "T":
            w.update({k: int(v) for k, v in (x.split("=") for x in f[1:])})
        elif f[0] == "A":
            w["addr"][int(f[1], 16)] = int(f[3])
        elif f[0] == "I":
            w["incl"][int(f[1], 16)] = (int(f[2]), int(f[3]))
        elif f[0] == "V":
            w["vec"][int(f[1], 16)] = (int(f[2]), int(f[3]))
    return w


def windows_of(path: Path) -> dict[str, dict]:
    spec = json.loads((path / "windows.json").read_text())
    out = {}
    for i, (label, (s, e)) in enumerate(spec.items()):
        w = load_window(path / f"prof_{i}.txt")
        w["seconds"] = e - s
        out[label] = w
    return out


# Cave code that runs only inside the 2D0DB key-wait spin (its hook there), as
# (first label, label after it): Input Thru's pending-resume gate (thru316.inc
# thru_idle; the resume itself, thru_idle_resume, is work).
CAVE_WAITS = (("thru_idle", "thru_idle_end"),)
_IDLE: set[int] = set()


def idle_addresses() -> set[int]:
    """Physical addresses of the waits (IDLE_LOOPS and CAVE_WAITS of this checkout's payload)."""
    if not _IDLE:
        for s, e in IDLE_LOOPS:
            _IDLE.update(range(BASE + s, BASE + e))
        profile = h.payload("316", BIOS)
        syms = profile.symbols()
        for s, e in CAVE_WAITS:
            _IDLE.update(range(profile.cave_phys + syms[s], profile.cave_phys + syms[e]))
    return _IDLE


def busy(w: dict) -> int:
    idle = idle_addresses()
    return w["total"] - sum(c for a, c in w["addr"].items() if a in idle)


def busy_pct(w: dict) -> float:
    return 100 * busy(w) / (w["seconds"] * CPU_HZ)


def per_call(w: dict, phys: int) -> tuple[int, float | None]:
    """(calls, mean inclusive cycles) of the routine at phys."""
    c, n = w["incl"].get(phys, (0, 0))
    return n, (c / n if n else None)


def per_vector(w: dict, vec: int) -> tuple[int, float | None]:
    n, c = w["vec"].get(vec, (0, 0))
    return n, (c / n if n else None)


def parse_trace(path: Path):
    """(t, tags, cs:ip, psw, popped word) per trace-point hit."""
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) < 16 or f[0] != "H":
            continue
        item = None
        if len(f) > 16 and "=" in f[16]:
            hx = f[16].split("=")[1]
            item = int(hx[2:4] + hx[0:2], 16)
        yield float(f[1]), f[2].split("+"), f[3], int(f[15], 16), item


def trace_metrics(path: Path, start: float, end: float) -> dict:
    """Interrupt-off windows (s), worst tick completion (k-th ISR-09 entry to the k-th
    task-2 return, s), worst ISR-09 own time (entry to its final CLI minus nested ISRs, s),
    and the number of trace hits whose PSW disagreed with the tracked IF state."""
    off = None
    worst_off, worst_at = 0.0, None
    inconsistent = 0
    pending: deque = deque()
    done = []
    own = []
    t09 = None
    nested_open: list[float] = []
    nested = 0.0
    started = False
    for t, tags, psip, psw, item in parse_trace(path):
        if t < start:
            continue
        if t > end:
            break
        IF = bool(psw & 0x200)
        isr = next((x for x in tags if x.startswith("isr")), None)
        if not started:                       # take the IF state from the first hit
            started = True
            off = None if IF or isr else t
        if isr:
            if off is None:
                off = t
            if isr == "isr09":
                pending.append(t)
                t09, nested, nested_open = t, 0.0, []
            elif t09 is not None:
                nested_open.append(t)
        elif IF != (off is None):
            inconsistent += 1
            off = None if IF else t
        if "t2out" in tags and pending:
            done.append(t - pending.popleft())
        if "t9end" in tags and t09 is not None:
            own.append(t - t09 - nested)
            t09 = None
        for op in tags:
            if op in ("cli", "int"):
                if off is None:
                    off = t
            elif op == "sti":
                if off is not None:
                    if t - off > worst_off:
                        worst_off, worst_at = t - off, (off, psip)
                    off = None
            elif op in ("popf", "iret") and item is not None:
                if item & 0x200:
                    if off is not None:
                        if t - off > worst_off:
                            worst_off, worst_at = t - off, (off, psip)
                        off = None
                elif off is None:
                    off = t
                if op == "iret" and nested_open:
                    nested += t - nested_open.pop()
    return {"ifoff_max": worst_off, "ifoff_at": worst_at, "tick_done_max": max(done) if done else None,
            "ticks_done": len(done), "isr09_own_max": max(own) if own else None, "inconsistent": inconsistent}


def chord_times(io_log: Path, starts: list[float]) -> list[tuple[int, float | None, float | None]]:
    """Per chord: (voice set-ups, first, last) — OUT 62h at 2325:004C within 0.45 s, in s."""
    want = f"{(DSP_START[0] + L) & 0xFFFF:04X}:{DSP_START[1]:04X}"
    ev = []
    for line in io_log.read_text().splitlines():
        f = line.split()
        if len(f) >= 5 and f[1] == want and f[2] == "W" and f[3] == "0062":
            ev.append(float(f[0]))
    out = []
    for t in starts:
        xs = [x - t for x in ev if t <= x < t + 0.45]
        out.append((len(xs), xs[0] if xs else None, xs[-1] if xs else None))
    return out


def screen_problems(build: str, name: str, job: dict) -> list[str]:
    path = run_dir(build, name) / "screens.json"
    # The text decoder shows some blank cells as '.', so compare with '.' read as a blank.
    shots = {round(s["time"], 3): "\n".join(s["rows"]).replace(".", " ") for s in json.loads(path.read_text())}
    bad = []
    for t, wants in job.get("screens", {}).items():
        text = shots.get(round(t, 3), "")
        bad += [f"{build}/{name} @ {t}: {w!r} not on screen" for w in wants if w.replace(".", " ") not in text]
    return bad


def metrics(build: str, profile: h.Profile, todo: dict) -> tuple[dict, list[str]]:
    """Metric values and validity problems (a problem fails the test before any budget)."""
    m: dict[str, float] = {}
    bad: list[str] = []
    syms = profile.symbols() if build == "pmoney" else {}
    cave = profile.cave_phys

    cache: dict[str, dict] = {}

    def W(name):
        if name not in cache:
            cache[name] = windows_of(run_dir(build, name))
        return cache[name]

    for name, job in todo.items():
        bad += screen_problems(build, name, job)
        ws = W(name)
        for label, w in ws.items():
            if not w.get("total"):
                bad.append(f"{build}/{name}/{label}: empty profile window")
        for label, n in job.get("ticks", {}).items():
            got = ws[label]["vec"].get(9, (0, 0))[0]
            if abs(got - n) > 2:
                bad.append(f"{build}/{name}/{label}: {got} tick interrupts, expected {n}")

    idle = W("idle")["idle"]
    m["idle_busy_pct"] = busy_pct(idle)
    m["tick_isr_idle"] = per_vector(idle, 9)[1]
    m["tick_body_idle"] = per_call(idle, BASE + TICK_BODY)[1]
    m["tick_sum_idle"] = m["tick_isr_idle"] + m["tick_body_idle"]
    windows = {**W("seq"), **W("allon"), **W("synca")}
    for lab in ("play120", "play300", "allon300", "synca120"):
        w = windows[lab]
        m[f"tick_isr_{lab}"] = per_vector(w, 9)[1]
        m[f"tick_body_{lab}"] = per_call(w, BASE + TICK_BODY)[1]
        m[f"tick_sum_{lab}"] = m[f"tick_isr_{lab}"] + m[f"tick_body_{lab}"]
        m[f"busy_pct_{lab}"] = busy_pct(w)
    m["tx_isr_synca120"] = per_vector(windows["synca120"], 0x0C)[1]
    m["tx_isr_allon300"] = per_vector(windows["allon300"], 0x0C)[1]
    for name, labels in (("seq", ("play120", "play300")), ("allon", ("allon300",))):
        path = run_dir(build, name, True) / "points.trace"
        spec = json.loads((run_dir(build, name) / "windows.json").read_text())
        for lab in labels:
            s, e = spec[lab]
            tr = trace_metrics(path, s, e)
            if tr["inconsistent"]:
                bad.append(f"{build}/{name}/{lab}: {tr['inconsistent']} trace hits disagree with the tracked IF state")
            if not tr["ticks_done"]:
                bad.append(f"{build}/{name}/{lab}: no tick completions traced")
            m[f"ifoff_max_us_{lab}"] = 1e6 * tr["ifoff_max"]
            m[f"tick_done_max_ms_{lab}"] = 1e3 * tr["tick_done_max"] if tr["tick_done_max"] else None
            m[f"isr09_own_max_{lab}"] = CPU_HZ * tr["isr09_own_max"] if tr["isr09_own_max"] else None
    m["ifoff_max_us_play"] = max(m["ifoff_max_us_play120"], m["ifoff_max_us_play300"])

    for name in ("midi", "midi_mute"):
        if name not in todo:
            continue
        ws = W(name)
        mute = "on" if name == "midi_mute" else "off"
        mc = ws["midichord"]
        if "mute_note_on_wrapper" in syms:
            m[f"note_wrapper_{mute}"] = per_call(mc, cave + syms["mute_note_on_wrapper"])[1]
        else:
            m[f"note_wrapper_{mute}"] = per_call(mc, BASE + NOTE_BUILDER)[1]
        if name != "midi":
            continue
        n, m["pad_lookup"] = (per_call(mc, cave + syms["pad_lookup_far"]) if "pad_lookup_far" in syms
                              else per_call(mc, BASE + STOCK_LOOKUP))
        if n < 96:
            bad.append(f"{build}/midi: {n} pad lookups in the MIDI chord window, expected >= 96")
        io = run_dir(build, name) / "io_trace.log"
        ch = chord_times(io, MIDI_CHORDS)
        pc = chord_times(io, PAD_CHORDS)
        if any(x[0] < 16 for x in ch + pc):
            bad.append(f"{build}/midi: voice set-ups per chord {[x[0] for x in ch + pc]}, expected >= 16 each")
        else:
            m["chord_midi_first_ms"] = 1e3 * max(x[1] for x in ch)
            m["chord_midi_last_ms"] = 1e3 * max(x[2] for x in ch)
            m["chord_pad_last_ms"] = 1e3 * max(x[2] for x in pc)
        for lab, kind, _, _ in FLOODS:
            w = ws[lab]
            m[f"busy_pct_{lab}"] = busy_pct(w)
            m[f"rx_byte_{lab}"] = per_vector(w, 0x0D)[1]
            m[f"extra_tick_bodies_{lab}"] = per_call(w, BASE + TICK_BODY)[0] - w["vec"].get(9, (0, 0))[0]

    ui = W("ui")
    tour, wheel = ui["ui_tour"], ui["ui_dial"]
    rate = busy(idle) / idle["seconds"]
    m["screen_change"] = (busy(tour) - rate * tour["seconds"]) / 15
    n, m["pr_redraw"] = per_call(wheel, BASE + PR_REDRAW)
    if n < 8:
        bad.append(f"{build}/ui: {n} Play/Record redraws in the wheel window, expected >= 8")

    def int43(w):
        k = c = 0
        for phys in [BASE + INT43] + ([cave + syms["int43_fast"]] if "int43_fast" in syms else []):
            got = w["incl"].get(phys, (0, 0))
            c += got[0]
            k += got[1]
        return c / k if k else None
    m["int43_tour"] = int43(tour)
    m["int43_wheel"] = int43(wheel)

    ed = W("editdo")
    for lab, off in (("reverse", REVERSE), ("silence", SILENCE)):
        n, c = per_call(ed[f"do_{lab}"], BASE + off)
        if n != 1:
            bad.append(f"{build}/editdo: {n} {lab.upper()} calls in its window, expected 1")
        m[f"{lab}_per_frame"] = c / LONG_FRAMES if c else None
    n, m["free_cluster_search"] = per_call(W("disk")["disk_save"], BASE + FREE_CLUSTER)
    if n < 10:
        bad.append(f"{build}/disk: {n} free-cluster searches in the save window, expected >= 10")

    if build == "pmoney":
        blit = syms.get("fast_blit")

        def redraw(w, at_least):
            n, r = per_call(w, cave + syms["refresh"])
            k, b = per_call(w, cave + blit) if blit is not None else per_call(w, BASE + STOCK_BLIT)
            if n < at_least or not k:
                bad.append(f"{build}/view: {n} redraws ({k} blits), expected >= {at_least}")
                return None
            return r + b
        vw = W("view")
        for lab, n in (("wheel_full", 6), ("wheel_fine", 6), ("zoom", 4), ("zones", 4)):
            m[f"view_{lab}"] = redraw(vw[lab], n)
        m["view_wheel_fine64"] = redraw(W("viewzoom")["wheel_fine64"], 6)
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}, bad


# ------------------------------------------------------------------ driver
def run_build(build: str, profile: h.Profile, workers: int | None = None,
              analyse_only: bool = False) -> tuple[dict, list[str]]:
    fx = fixtures()
    todo = jobs(build, fx, profile)
    if not analyse_only:
        h.run_parallel(todo, lambda name, job: execute(build, name, job, profile), workers)
    traced = [n for n, j in todo.items() if j.get("trace")]
    points, outside = if_points(build, profile, list(todo))
    (OUT / build / "trace_points.txt").write_text(points.replace(";", "\n") + "\n")
    if not analyse_only:
        h.run_parallel({n: todo[n] for n in traced},
                       lambda name, job: execute(build, name, job, profile, points), workers)
    res, bad = metrics(build, profile, todo)
    if outside:
        bad.append(f"{build}: {outside} cycles executed outside the 3.16 image and the cave; "
                   "the trace-point set may miss IF changes there")
    res["_payload"] = profile.sha256 if build == "pmoney" else hashlib.sha256(M3K316.read_bytes()).hexdigest()
    (OUT / f"{build}.json").write_text(json.dumps({"metrics": res, "problems": bad}, indent=1, sort_keys=True))
    return res, bad


def budget_of(spec: dict, stock: float | None) -> float | None:
    """Budget from a rule: 'abs' (spec['budget']), 'stock', 'stock+P%', 'stock/N'."""
    rule = spec["rule"]
    if rule == "abs":
        return spec["budget"]
    if stock is None:
        return None
    if rule == "stock":
        return stock
    if rule.startswith("stock+") and rule.endswith("%"):
        return round(stock * (1 + float(rule[6:-1]) / 100), 3)
    if rule.startswith("stock/"):
        return round(stock / float(rule[6:]), 3)
    raise ValueError(rule)


def compare(res: dict, budgets: dict) -> tuple[list[str], list[str]]:
    """(violations, tighten notes)."""
    bad, tight = [], []
    for name, spec in budgets["metrics"].items():
        v = res.get(name)
        limit = spec.get("budget")
        if v is None:
            bad.append(f"{name}: not measured")
            continue
        if limit is None:
            bad.append(f"{name}: no budget (stock reference not measured; run --refresh-stock)")
            continue
        if v > limit:
            bad.append(f"{name}: {v} > budget {limit} ({spec['rule']}; stock {spec.get('stock')})")
        elif limit and v < 0.9 * limit:
            tight.append(f"{name}: {v} is >= 10 % under its budget {limit}")
    return bad, tight


def report(res: dict, budgets: dict) -> str:
    lines = ["| metric | stock 3.16 | PMONEY | budget | rule | ok |", "|---|--:|--:|--:|---|---|"]
    for name, spec in budgets["metrics"].items():
        v = res.get(name)
        ok = v is not None and spec["budget"] is not None and v <= spec["budget"]
        lines.append(f"| {name} | {spec.get('stock')} | {v} | {spec['budget']} | {spec['rule']} | {'yes' if ok else 'NO'} |")
    return "\n".join(lines) + "\n"


def refresh_stock(budgets: dict, stock: dict) -> dict:
    out = json.loads(json.dumps(budgets))
    out["stock_m3k316_sha256"] = stock["_payload"]
    for name, spec in out["metrics"].items():
        spec["stock"] = stock.get(name)
        if spec["rule"] != "abs":
            spec["budget"] = budget_of(spec, spec["stock"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh-stock", action="store_true")
    ap.add_argument("--workers", type=int)
    ap.add_argument("--analyse-only", action="store_true", help="re-read the last runs, no MAME")
    args = ap.parse_args()
    profile = h.payload("316", BIOS)
    budgets = json.loads(BUDGETS.read_text())
    if args.refresh_stock:
        stock, bad = run_build("stock", profile, args.workers, args.analyse_only)
        if bad:
            print("stock run invalid:\n  " + "\n  ".join(bad))
            return 1
        budgets = refresh_stock(budgets, stock)
        BUDGETS.write_text(json.dumps(budgets, indent=1) + "\n")
    res, problems = run_build("pmoney", profile, args.workers, args.analyse_only)
    (OUT / "report.md").write_text(report(res, budgets))
    bad, tight = compare(res, budgets)
    print("\n".join(problems + bad) or "all budgets met")
    print("\n".join(f"tighten: {t}" for t in tight))
    return 1 if problems or bad else 0


if __name__ == "__main__":
    sys.exit(main())
