"""Lazy Chop (mods/lazychop316.inc, notes/lazy_chop.md) in MAME, OS 3.16.

    python3 -m unittest emu.test_lazychop -v

Every case runs on the 316 profile once per BIOS set of harness.bios316_sets()
(all four in release mode), driven only by panel bytes (pads, keys, wheel) on
the 1 ms SMF grid (emu.panel) and, for the "midi" case, MIDI In 1.  The
observer emu/lua/lazychop316.lua logs the owned ISR path (with its TCT0
timestamp), the take's t0, stock note-on entries, ring-5 writes, DSP key-ons
and one-channel stops, and snapshots the cave, DGROUP and program state; it
writes MPC RAM only in the "wrap" case (LC_INJECT_BASE: the 32-bit TCT0 time
base is moved 1.5 s before its wrap).

Start-up: the 3.16 start-up file loader loads MUTE.PGM (program 1, pads 1-4 on
the disk's Sound) and the Sound before the SCSI search, which Soft Key 4
cancels at 51 s (emu/test_mute_voice.py).  Program/Sounds, 6, Help then open
the wave view of that Sound by V (open_view()).  Spec acceptance checks:

    A1 take, A2 timing (30/120/300 BPM, offset), A3 roll, A4 ends and Cancel,
    A5 Refine pads, mono retrigger, a MIDI voice survives, A6 CHOPS edits,
    A7 TCT0 tick phases and the 2^32 base wrap, A8 Equal Division over 64
    zones (banks A-D), A9 Convert, A10 ownership on every exit, A11 PGM
    save / load round trip.
"""
from __future__ import annotations

import json
import math
import struct
import subprocess
import unittest
from pathlib import Path

from emu import harness as h
from emu import pgm as pgm_fixture
from emu.panel import dial, key_tap, pad_hit, panel_pad, write_smf
from emu.snd import sine, snd

ROOT = Path(__file__).resolve().parents[1]
RUNS = h.BUILD / "emu" / "lazychop-tests"
TEMPLATE = ROOT / "emu/fixtures/mute-native-blank.PGM"
SR = 44_100
CANCEL = 51.0                   # the start-up loader is done; Soft Key 4 cancels the SCSI search
COUNTS_PER_FRAME = 20_000 / 441  # TCT0 (0.5 us) per 44.1 kHz frame
LC_MIN = 1368                   # the shortest slice (lazychop316.inc LC_MIN: stock 3.16's keyable minimum)
CAVE_CALLER = f"{h.RUNTIME_316 + h.CAVE_HOME_316:04X}"


def signal(n: int, seed: int = 0) -> list[int]:
    """A Source with a zero crossing every few frames and no repeating slices."""
    out = []
    for i in range(n):
        v = (12_000 * math.sin(2 * math.pi * i / 89.0 + seed) + 9_000 * math.sin(2 * math.pi * i / 23.7)
             + 30 * (((i * 7919 + seed * 104_729) % 201) - 100))
        out.append(max(-32_768, min(32_767, round(v))))
    return out


def lc_pos(raw: int, t0: int, k: int = 0) -> int:
    """mods/lazychop316.inc lc_pos: frames of TCT0 time raw after t0 + K (K in counts)."""
    d = (raw - t0 - k) & 0xFFFF_FFFF
    if d >= 1 << 31:
        return 0
    q, r = divmod(d, 20_000)
    return q * 441 + (r * 441 + 10_000) // 20_000


def crossing(x: list[int], p: int) -> bool:
    return x[p] == 0 or (x[p] < 0) != (x[p - 1] < 0)


def snap_ref(x: list[int], s: int, lo: int, hi: int) -> int:
    """The nearest zero crossing p, |p - s| <= 88, lo <= p <= hi (s + d before s - d); else s."""
    for d in range(89):
        for p in ((s + d,) if d == 0 else (s + d, s - d)):
            if max(lo, 1) <= p <= min(hi, len(x) - 1) and crossing(x, p):
                return p
    return s


def take_times(V: float) -> list[float]:
    """30 hits 0.15 s apart, hit k k mod 10 ms into the grid."""
    return [round(V + 3.3 + 0.15 * k + 0.001 * (k % 10), 3) for k in range(30)]


def open_view(tempo: str | None = None) -> tuple[list, float]:
    """Cancel the SCSI search, optionally set the tempo, open the wave view: (events, V)."""
    ev = h.taps((CANCEL, "soft4"))
    at = 54.0
    if tempo:
        ev += h.taps((51.6, "tempo_sync"), *[(52.2 + 0.4 * i, c) for i, c in enumerate(tempo)])
        ev += h.taps((52.2 + 0.4 * len(tempo) + 0.2, "enter"), (54.0, "main_screen"))
        at = 55.0
    ev += h.taps((at, "program_sounds"), (at + 0.8, "6"), (at + 3.0, "help"))
    return ev, at + 6.0


def hit(pad: int, at: float, hold: float = 0.05) -> list:
    return pad_hit(panel_pad(pad), at, hold=hold)


def zone_page(at: float, stereo: bool = False) -> list:
    """Right, Right (stereo: and the View field): from the Trim start to the ZONE
    field, where the soft keys are Lazy Chop's."""
    return h.taps(*[(at + 0.5 * i, "right") for i in range(3 if stereo else 2)])


def hits_at_phases(pad: int, times: list[float]) -> list:
    """A pad hit at each time; hit k is preceded by 8 * (k // 10) pad-pressure
    messages (A0 kk 00, 0.96 ms each on the link), so the hits also move by
    -0.32 and -0.64 ms against the 1 ms SMF grid: with a 1 ms step in the times
    every 0.32 ms of a TCT0 period is reached (A7)."""
    ev = []
    for k, t in enumerate(times):
        ev += [(t, bytes((0xA0, panel_pad(pad), 0)))] * (8 * (k // 10)) + hit(pad, t)
    return ev


def program_file(runs: Path, sound: Path, name: str = "MUTE.PGM") -> Path:
    path = runs / name
    path.write_bytes(pgm_fixture.for_sound(TEMPLATE.read_bytes(), sound.read_bytes(), pads=(0, 1, 2, 3),
                                           program_name="LC TEST"))
    return path


def parse(d: Path) -> tuple[list[tuple[str, dict]], dict[float, dict]]:
    events, snaps = [], {}
    for line in (d / "lazychop.log").read_text().splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "SNAP":
            s = json.loads(rest)
            snaps[round(s["t"], 3)] = s
            continue
        values = {}
        for field in rest.split():
            key, value = field.split("=", 1)
            values[key] = (float(value) if key == "t" else value if key in ("cs", "ip", "caller")
                           else int(value, 16) if key in ("ss", "off", "v") else int(value))
        events.append((kind, values))
    return events, snaps


def at(snaps: dict, t: float) -> dict:
    return snaps[round(t, 3)]


def shows(rows: list[str], y: int, col: int, text: str) -> bool:
    """The LCD rows hold `text` (emu/wave_ref.py's font) at glyph row y, cell column col."""
    from emu import wave_ref
    lit = [[False] * 240 for _ in range(64)]
    wave_ref._text(lit, y, col, text)
    x0, x1 = col * 6, min(240, (col + len(text)) * 6)
    return all("".join("#" if b else "." for b in lit[y + r][x0:x1]) == rows[y + r][x0:x1] for r in range(7))


EJECT = r"""
local machine = manager.machine
local ej_t = tonumber(os.getenv("EJECT_AT") or "-1")
local done = false
emu.register_periodic(function()
    if done or ej_t < 0 or machine.time:as_double() < ej_t then return end
    for tag, img in pairs(machine.images) do
        if img.image_type_name == "floppydisk" then img:unload() end
    end
    done = true
end)
"""


def stock_of(profile: h.Profile) -> h.Profile:
    """Stock M3K316.SYS on the profile's BIOS set, where its loader puts it (7000h on
    3.08 and 3.11; PMONEY's entry316 is what moves a 7000h load down)."""
    import dataclasses
    import hashlib
    fields = {f.name: getattr(profile, f.name) for f in dataclasses.fields(profile)}
    fields.update(sys=h.M3K316, sha256=hashlib.sha256(h.M3K316.read_bytes()).hexdigest())
    return StockProfile(**fields)


class StockProfile(h.Profile):
    @property
    def load_segment(self) -> int:
        return h.LOAD_SEGMENTS[self.bios]


def kinds(events, kind: str, a: float = 0.0, b: float = 1e9) -> list[dict]:
    return [v for k, v in events if k == kind and a <= v["t"] < b]


class LazyChop(h.EmuSuite):
    RUNS = RUNS
    PROFILE_NAMES = ("316",)

    @classmethod
    def cases(cls, profile, runs):
        if not TEMPLATE.is_file():
            h.unavailable(f"native PGM fixture is missing: {TEMPLATE}")
        cases: dict[str, h.Case] = {}

        def sound(name: str, planes: list[list[int]], tune: int = 0) -> Path:
            path = runs / f"{name}.SND"
            data = bytearray(snd(name, planes))
            data[2 + 0x12] = tune & 255
            path.write_bytes(bytes(data))
            return path

        def add(case: str, src: Path, events: list, times: list[float], **kw) -> None:
            pgm = program_file(runs, src, f"{case}.pgm")
            files = [(pgm, "MUTE.PGM"), (src, src.name)]
            cases[case] = h.Case(events=events, times=sorted(times), files=files,
                                 parts=("lazychop", "snddump"), **kw)

        test4 = sound("TEST", [sine(SR * 4)])
        take6 = sound("TAKE", [signal(SR * 6)])

        # Phase 1: ownership, Equal Division zones over banks A-D (A8, R2), a
        # pad held across the view's entry, mono retrigger, Exit paths (A10).
        ev, V = open_view()
        ev += hit(4, 56.0, hold=5.0)                                  # held across the view's entry
        ev += hit(1, V + 2.0) + hit(3, V + 2.5) + hit(2, V + 3.0) + hit(5, V + 3.05)
        # #14: pad 6 held with pressure while owned: the held table stays clear
        ev += hit(6, V + 3.3, hold=0.4) + [(V + 3.4 + 0.05 * k, bytes((0xA0, panel_pad(6), 0x40 + k)))
                                            for k in range(4)]
        ev += zone_page(V + 4.0) + h.taps((V + 5.0, "right")) + dial(50, V + 5.5, gap=0.05)   # 16 + 50: 64
        ev += h.taps((V + 9.0, "pad_bank")) + hit(1, V + 9.5)
        ev += h.taps((V + 10.0, "pad_bank"), (V + 10.4, "pad_bank")) + hit(16, V + 11.0)
        ev += h.taps((V + 11.5, "pad_bank"))
        add("zones", test4, ev, [V - 3.5, V + 0.5, V + 1.5, V + 3.5, V + 3.55, V + 8.8, V + 9.3, V + 12.5],
            env={"LC_FROM": str(V - 6.0), "SNDDUMP_PCM": "0"})

        ev, V = open_view()
        steps = [(V + 0.5, "owned"), (V + 1.0, "soft4"), (V + 3.0, "stock"), (V + 3.5, "help"),
                 (V + 7.5, "owned"), (V + 8.0, "help"), (V + 10.0, "stock"), (V + 10.5, "help"),
                 (V + 14.5, "owned"), (V + 15.0, "main_screen"), (V + 16.5, "stock"),
                 (V + 17.0, "program_sounds"), (V + 17.8, "6"), (V + 20.0, "help"),
                 (V + 23.5, "owned"), (V + 24.0, "disk"), (V + 26.0, "stock")]
        for at, what in steps:
            ev += hit(1, at) if what in ("owned", "stock") else key_tap(what, at)
        cls.exit_steps = steps
        add("exits", test4, ev, [V + 0.3, V + 2.5, V + 7.2, V + 9.5, V + 14.2, V + 16.0, V + 23.2, V + 25.5,
                                 V + 27.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # A10 error box + A9 short-slice refusal: Equal Division zones of 128 frames.
        tiny = sound("TINY", [signal(2048, 3)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft3", V + 1.5) + key_tap("enter", V + 3.0)
        ev += hit(1, V + 4.5) + hit(1, V + 6.0)
        add("errorbox", tiny, ev, [V, V + 4.0, V + 5.5, V + 6.5], env={"LC_FROM": str(V - 1.0)})
        # #11: a mode key acknowledging the message leaves the view with it
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft3", V + 1.5) + key_tap("enter", V + 3.0) + key_tap("disk", V + 4.5)
        ev += hit(1, V + 6.5)
        add("errmode", tiny, ev, [V + 4.0, V + 6.0, V + 7.0], env={"LC_FROM": str(V - 1.0)})
        # #11: BDE3:000E's own error box (flags [9331], [A44F] injected) with the pads stock
        ev, V = open_view()
        ev += hit(1, V + 3.0) + key_tap("soft1", V + 4.0) + hit(1, V + 5.0) + hit(1, V + 6.5)
        add("errbox", test4, ev, [V + 0.5, V + 2.5, V + 4.5, V + 7.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0",
                 "LC_INJECT_DG": f"{V + 1.0}:9331:01,{V + 1.0}:A44F:01"})

        # A5: a voice from MIDI In 1 (D8: not owned) survives the pads' mono stops.
        ev, V = open_view()
        ev += hit(1, V + 1.5) + hit(2, V + 1.6) + hit(3, V + 1.7)
        midi = write_smf(runs / "midi-external.mid", [(V + 1.0, bytes((0x90, 0x23, 0x7F)))])
        long6 = sound("LONG", [sine(SR * 6)])
        add("midi", long6, ev, [V + 0.8, V + 2.5], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"},
            kwargs={"extra": ["-midiin1", str(midi)], "snapshot": False})

        # Phase 2: the take.  Snap off, so the map is the raw chops.  Hit k of
        # 20 lands k ms into a TCT0 period apart from the 0.2 s spacing, so
        # every 10 ms phase occurs (A7).
        def take(tempo=None, offset=0, inject=None, tune_pad=False):
            ev, V = open_view(tempo)
            ev += zone_page(V + 0.5) + h.taps((V + 1.5, "soft2"), (V + 2.0, "soft1"))
            if offset:
                ev += dial(offset, V + 2.3, gap=0.1)
            ev += hit(1, V + 3.0) + hits_at_phases(2, take_times(V))
            if tune_pad:
                ev += hit(1, V + 10.5)
            env = {"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"}
            if inject is not None:
                env["LC_INJECT_BASE"] = f"{V + 2.5}:{inject}"
            return ev, [V + 2.8, V + 10.0, V + 11.5] + ([54.4] if tempo else []), env

        for case, kw, src in (("timing120", {"tune_pad": True}, take6),
                              ("timing30", {"tempo": "30", "tune_pad": True},
                               sound("TUNED", [signal(SR * 6, 1)], tune=-12)),
                              ("timing300", {"tempo": "300"}, take6),
                              ("offset", {"offset": 5}, take6),
                              ("wrap", {"inject": (1 << 32) - 3_000_000}, take6)):
            ev, times, env = take(**kw)
            add(case, src, ev, times, env=env)

        # A3 roll (20 hits 25 ms apart) with snap on, <Done>, then Refine pads (A5).
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for k in range(20):
            ev += hit(2, V + 3.5 + 0.012 * k, hold=0.005)
        ev += key_tap("soft3", V + 5.0) + hit(3, V + 6.0)
        add("roll", take6, ev, [V + 4.2, V + 5.5, V + 6.3], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # #15 snap when the field is left, #16 back to equal zones.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5) + hit(2, V + 4.5)
        ev += key_tap("soft3", V + 5.0) + hit(2, V + 5.5) + h.taps((V + 6.0, "left"), (V + 6.5, "left"))
        ev += dial(1, V + 7.0) + key_tap("right", V + 8.0)
        ev += h.taps((V + 9.0, "up"), (V + 9.5, "right"), (V + 10.0, "+"), (V + 11.0, "enter"))
        add("settle", take6, ev, [V + 6.8, V + 7.5, V + 8.5, V + 10.5, V + 11.5],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # A5 Refine: 21 slices of 0.1 s (a slice under two 10 ms player ticks does
        # not audition, wave_playback.inc audition_ticks); pads of banks A and B.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for k in range(20):
            ev += hit(2, V + 3.5 + 0.1 * k)
        ev += key_tap("soft3", V + 5.8)
        ev += hit(3, V + 6.5) + key_tap("pad_bank", V + 7.0) + hit(1, V + 7.5) + hit(6, V + 8.0)
        ev += hit(5, V + 8.5) + h.taps((V + 9.0, "pad_bank"), (V + 9.3, "pad_bank"), (V + 9.6, "pad_bank"))
        add("refine", take6, ev, [V + 6.2, V + 10.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # A6: CHOPS edits of slice 3 and refusals.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + h.taps((V + 1.5, "soft2"), (V + 2.0, "soft1")) + hit(1, V + 3.0)
        for t in (3.5, 4.0, 4.5, 5.0):
            ev += hit(2, V + t)
        ev += key_tap("soft3", V + 5.5) + hit(3, V + 6.0) + key_tap("left", V + 6.5) + dial(2, V + 7.0, gap=0.1)
        ev += key_tap("left", V + 8.0) + dial(-1, V + 8.5) + key_tap("right", V + 9.5)
        ev += dial(-30, V + 10.0, gap=0.05) + dial(200, V + 12.5, gap=0.05)
        add("edit", take6, ev, [V + 6.3, V + 7.7, V + 9.2, V + 12.2, V + 23.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # D4 on a committed numeric entry: slice 2's start typed as 0.800.00 snaps.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5) + hit(2, V + 4.5)
        ev += key_tap("soft3", V + 5.0) + hit(2, V + 5.5) + h.taps((V + 6.0, "left"), (V + 6.5, "left"))
        ev += h.taps((V + 7.5, "0"), (V + 8.5, "right"), (V + 9.5, "8"), (V + 9.8, "0"), (V + 10.1, "0"),
                     (V + 10.5, "right"), (V + 11.5, "0"), (V + 12.5, "enter"))
        add("numeric", take6, ev, [V + 7.0, V + 14.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # A4: Cancel keeps the map; STOP ends a take; a mode key cancels and leaves.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5) + hit(2, V + 4.0)
        ev += key_tap("soft4", V + 4.5)
        ev += key_tap("soft1", V + 5.5) + hit(1, V + 6.5) + hit(2, V + 7.0) + hit(2, V + 7.5)
        ev += key_tap("stop", V + 8.0)
        ev += key_tap("soft1", V + 10.0) + hit(1, V + 11.0) + hit(2, V + 11.5) + key_tap("disk", V + 12.0)
        add("cancel", take6, ev, [V + 2.5, V + 4.3, V + 5.0, V + 7.8, V + 9.0, V + 11.8, V + 13.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # A4 cap: 64 hits 40 ms apart (over LC_MIN) end the take at 64 chops; bank D
        # pad 16 plays slice 64.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0)
        for k in range(64):
            ev += hit(1 + k % 4, V + 3.0 + 0.04 * k, hold=0.01)
        ev += hit(2, V + 6.0)                                      # after the cap: Refine, slice 2
        ev += h.taps((V + 6.2, "pad_bank"), (V + 6.5, "pad_bank"), (V + 6.8, "pad_bank")) + hit(16, V + 7.2)
        add("cap64", take6, ev, [V + 5.8, V + 6.4, V + 7.6], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # Phase 4: Convert with the defaults (A9), then the pads off the view,
        # choke, and the PGM save of A11 (Disk 4, program and sounds).
        conv = sound("BREAKS", [signal(SR * 2, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for t in (3.4, 3.8, 4.3):
            ev += hit(2, V + t)
        ev += key_tap("soft3", V + 4.8) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        ev += hit(1, V + 7.1) + hit(2, V + 7.15)                   # #10: while the sounds are made
        ev += key_tap("main_screen", V + 10.0)
        ev += hit(1, V + 11.0, hold=1.0) + hit(2, V + 11.3) + hit(3, V + 12.5) + hit(4, V + 13.0)
        ev += key_tap("disk", V + 14.0) + key_tap("4", V + 16.0) + key_tap("soft1", V + 19.0)
        add("convert", conv, ev, [V + 5.2, V + 6.5, V + 9.5, V + 14.0, V + 40.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": f"{V + 5.2},{V + 9.5}"})

        # Replace a non-empty program (program 1) with choke OFF, stereo Source.
        left, right = signal(SR * 2, 7), signal(SR * 2, 9)
        stereo = sound("STEREO", [left, right])
        ev, V = open_view()
        ev += zone_page(V + 0.5, stereo=True) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for t in (3.4, 3.8):
            ev += hit(2, V + t)
        ev += key_tap("soft3", V + 4.6) + key_tap("soft3", V + 5.0)
        ev += h.taps((V + 5.5, "0"), (V + 5.8, "1"), (V + 6.3, "right"), (V + 6.8, "-"), (V + 7.5, "enter"))
        ev += h.taps((V + 8.5, "soft4"), (V + 9.5, "enter"), (V + 10.5, "soft2"))
        add("replace", stereo, ev, [V + 4.8, V + 7.3, V + 8.0, V + 9.0, V + 14.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": f"{V + 4.8},{V + 14.0}"})

        # #2: two Converts of one Source: Source-derived, unique Sound and program
        # names; the second program saved (program and sounds) to a disk that
        # already holds ZONE000.SND and BREAKS101.SND's predecessor names, then
        # reloaded on a fresh machine (test_second_convert_round_trip).
        conv2 = sound("BREAKS", [signal(SR * 2, 5)])
        old = runs / "ZONE000.SND"
        old.write_bytes(snd("ZONE000", [sine(SR // 4)]))
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.5) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        ev += key_tap("soft1", V + 10.0) + hit(1, V + 11.0) + hit(2, V + 11.6) + key_tap("soft3", V + 12.5)
        ev += key_tap("soft3", V + 13.5) + key_tap("enter", V + 15.0)
        ev += key_tap("main_screen", V + 18.0) + key_tap("disk", V + 19.0) + key_tap("4", V + 21.0)
        ev += key_tap("soft1", V + 24.0)
        pgm2 = program_file(runs, conv2, "convert2.pgm")
        cases["convert2"] = h.Case(events=ev, times=[V + 6.8, V + 9.5, V + 14.8, V + 17.5, V + 60.0],
                                   files=[(pgm2, "MUTE.PGM"), (conv2, conv2.name), (old, "ZONE000.SND")],
                                   parts=("lazychop", "snddump"),
                                   env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": f"{V + 17.5}"})

        # #4: transport running (Rec + Play) with the Edit Sound lock ON (default):
        # Convert makes nothing.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.6) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        lock = sound("LOCK", [signal(SR * 2, 5)])
        add("lockbypass", lock, ev, [V + 5.2, V + 9.5], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"},
            kwargs={"press": [(52.0, "Y7", "Rec", 0.3), (52.1, "Y7", "Play", 0.1)]})

        # #5: a MIDI In 1 note stream (D8: not owned) while pad 1 is hit 200 times
        # at shifted phases: every hit plays zone 1.
        ev, V = open_view()
        for k in range(200):
            at = round(V + 1.0 + 0.05 * k + 0.001 * (k % 7), 3)
            ev += [(at, bytes((0xA0, panel_pad(1), 0)))] * (8 * ((k // 7) % 3)) + hit(1, at, hold=0.02)
        midi_ev = []
        for k in range(1400):                   # a note every 8 ms: under the stock MIDI overload box
            at = round(V + 0.9 + 0.008 * k, 3)
            midi_ev += [(at, bytes((0x90, 0x62, 0x7F))), (round(at + 0.002, 3), bytes((0x80, 0x62, 0x00)))]
        mid = write_smf(runs / "d399race-midi.mid", sorted(midi_ev))
        add("d399race", test4, ev, [V + 0.5, V + 12.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"},
            kwargs={"extra": ["-midiin1", str(mid)], "snapshot": False})

        # #7: keystroke traps.  A take ends by itself (2 s Source) and a late
        # <Done> + Soft Key 1 follow; on the ZONE field, the stock habit Soft Key 3
        # (<Fine>) + Soft Key 1 (<Ply/Stp>); Soft Key 3 twice at once.
        trap = sound("TRAP", [signal(SR * 2, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5)
        ev += key_tap("soft3", V + 5.2) + key_tap("soft1", V + 6.0)            # late <Done>, Soft 1
        ev += key_tap("soft4", V + 7.5)                                          # leave the new Armed state
        ev += key_tap("soft3", V + 8.5) + key_tap("soft1", V + 9.0)            # habit: Fine, Ply/Stp
        ev += key_tap("soft4", V + 10.0)
        ev += key_tap("soft3", V + 11.0, hold=0.03) + key_tap("soft3", V + 11.06, hold=0.03)   # double tap
        add("traps", trap, ev, [V + 2.5, V + 5.4, V + 6.5, V + 9.5, V + 10.5, V + 12.5],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # Second review.  B1: the view never waits inside BDE3:000E.  A kick
        # ([D398] = 'P') and COUNT IN (both taken by the global filter), then Pad
        # Bank alone, twice: the bank shown follows.
        ev, V = open_view()
        ev += key_tap("count_in", V + 1.0) + key_tap("pad_bank", V + 2.0) + key_tap("pad_bank", V + 3.0)
        ev += key_tap("count_in", V + 3.5) + hit(1, V + 4.0)
        add("kickbank", test4, ev, [V + 0.8, V + 1.5, V + 2.5, V + 3.8, V + 4.5],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0", "LC_INJECT_DG": f"{V + 0.5}:D398:50"})
        # B1: a kick, then the MIDI-in overflow's flags and kick together (img
        # 0x2C3CB..0x2C3D8): the stock box opens with the pads stock.
        ev, V = open_view()
        ev += hit(1, V + 3.0) + hit(2, V + 3.5) + key_tap("soft1", V + 4.0) + hit(1, V + 5.0)
        add("kickbox", test4, ev, [V + 0.5, V + 2.5, V + 4.5, V + 6.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0",
                 "LC_INJECT_DG": f"{V + 0.8}:D398:50,{V + 1.0}:A44F:01,{V + 1.0}:9331:02,{V + 1.0}:D398:50"})
        # B1: the same on the Slices to Program page.
        cvb = sound("CVBOX", [signal(SR * 2, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5)
        ev += key_tap("soft3", V + 4.0) + key_tap("soft3", V + 5.5) + hit(1, V + 7.5) + key_tap("soft1", V + 8.5)
        ev += key_tap("enter", V + 10.0) + hit(1, V + 11.0)
        add("cvbox", cvb, ev, [V + 5.2, V + 7.0, V + 9.5, V + 12.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0",
                 "LC_INJECT_DG": f"{V + 6.5}:A44F:01,{V + 6.5}:9331:02,{V + 6.5}:D398:50"})

        # B2: the minimum slice is stock's keyable minimum (LC_MIN).  Snap OFF,
        # hits 500, 512, 530 and 556 ms after the first: the 12 and 30 ms gaps are
        # no chops; Refine pads; Convert; every slice pad keys on in Play/Record.
        shc = sound("SHORTC", [signal(SR * 2, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft2", V + 1.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for dt in (0.5, 0.512, 0.530, 0.556):
            ev += hit(2, V + 3.0 + dt, hold=0.004)
        ev += key_tap("soft3", V + 4.0) + hit(1, V + 4.4) + hit(2, V + 4.8) + hit(3, V + 5.2)
        ev += key_tap("soft3", V + 5.6) + key_tap("enter", V + 6.6)
        ev += key_tap("main_screen", V + 10.0)
        for k in range(4):
            ev += hit(k + 1, V + 11.0 + 0.4 * k)
        add("short", shc, ev, [V + 4.3, V + 5.5, V + 9.5, V + 13.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})
        # B2: Equal Division, 64 zones of a 0.9 s Source (620 frames): a pad says
        # "Slice too short"; Convert refuses, naming slice 1, and makes nothing.
        eqs = sound("SHORTEQ", [signal(int(SR * 0.9), 3)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + h.taps((V + 1.5, "right")) + dial(48, V + 2.0, gap=0.05)
        ev += hit(1, V + 5.5) + key_tap("soft3", V + 6.5) + key_tap("enter", V + 7.5)
        ev += hit(1, V + 8.5) + hit(1, V + 10.0)
        add("eqshort", eqs, ev, [V + 5.3, V + 6.0, V + 8.2, V + 9.5, V + 10.5],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # B3: <Do it> is ENTER.  A take that ends by itself (2 s Source) and <Done>
        # mashed every 0.2 s; Cancel; Soft Key 3 mashed six times 0.1 s apart;
        # Cancel; then <To program> and ENTER: only that ENTER makes the sounds.
        msh = sound("MASH", [signal(SR * 2, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        for k in range(7):
            ev += key_tap("soft3", V + 5.15 + 0.2 * k, hold=0.05)
        ev += key_tap("soft4", V + 7.0)
        for k in range(6):
            ev += key_tap("soft3", V + 8.0 + 0.1 * k, hold=0.04)
        ev += key_tap("soft4", V + 9.0) + key_tap("soft3", V + 10.0) + key_tap("enter", V + 11.0)
        add("mash", msh, ev, [V + 4.8, V + 6.8, V + 7.5, V + 8.8, V + 9.5, V + 14.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # B4: only the moved point snaps: slice 1's end stepped (its start, frame
        # 0, stays), the last slice's start stepped (its end, the Source end, stays).
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for t in (3.5, 4.0, 4.5):
            ev += hit(2, V + t)
        ev += key_tap("soft3", V + 5.0) + hit(1, V + 5.5) + key_tap("left", V + 6.0) + dial(1, V + 6.5)
        ev += key_tap("right", V + 7.5) + hit(4, V + 8.5) + h.taps((V + 9.0, "left"), (V + 9.4, "left"))
        ev += dial(1, V + 9.8) + key_tap("right", V + 10.5)
        add("settle0", take6, ev, [V + 6.3, V + 7.0, V + 8.0, V + 10.2, V + 11.0],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # B5: pads mashed while the sounds are made (ring full), then a new take:
        # its "Lost:nn" counts only its own hits.
        lst = sound("LOST", [signal(SR * 6, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 4.0) + hit(2, V + 5.0)
        ev += key_tap("soft3", V + 7.0) + key_tap("soft3", V + 7.5) + key_tap("enter", V + 8.5)
        for k in range(20):
            ev += [(round(V + 8.62 + 0.001 * k, 3), bytes((0x90, panel_pad(k % 16 + 1), 0x7F))),
                   (round(V + 8.67 + 0.001 * k, 3), bytes((0x90, panel_pad(k % 16 + 1), 0x00)))]
        ev += key_tap("soft1", V + 12.0) + hit(1, V + 13.0) + hit(2, V + 13.5) + hit(2, V + 14.0)
        add("lost2", lst, ev, [V + 11.5, V + 13.3, V + 14.3], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # B6: "Equal zones again? Enter: yes" goes away with the pad that closed it.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5) + hit(2, V + 4.0)
        ev += key_tap("soft3", V + 5.0) + key_tap("right", V + 5.5) + dial(1, V + 6.0) + hit(3, V + 6.5)
        ev += key_tap("enter", V + 7.5)
        add("askpad", take6, ev, [V + 6.3, V + 7.0, V + 8.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})

        # B7: an older BREAKS01.SND (other audio) on the disk: Convert names slice 1
        # BREAKS101; program and sounds saved (Disk 4, defaults) and reloaded on a
        # fresh machine, PMONEY and stock 3.16 (test_disk_name_collision).
        dsrc = sound("BREAKS", [signal(SR * 2, 5)])
        older = runs / "BREAKS01.SND"
        older.write_bytes(snd("BREAKS01", [sine(SR // 4)]))
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.5) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        ev += key_tap("main_screen", V + 11.0) + key_tap("disk", V + 12.0) + key_tap("4", V + 14.0)
        ev += key_tap("soft1", V + 17.0)
        pgmd = program_file(runs, dsrc, "diskcol.pgm")
        cases["diskcol"] = h.Case(events=ev, times=[V + 6.8, V + 10.5, V + 55.0],
                                  files=[(pgmd, "MUTE.PGM"), (dsrc, dsrc.name), (older, "BREAKS01.SND")],
                                  parts=("lazychop", "snddump"),
                                  env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": f"{V + 10.5}"})

        # Third review.  #1: a Source name ending in digits (LOOP1) and an older
        # LOOP101.SND (= LOOP1 + 01): slice 1 is LOOP1101.
        lsrc = sound("LOOP1", [signal(SR * 2, 5)])
        lold = runs / "LOOP101.SND"
        lold.write_bytes(snd("LOOP101", [sine(SR // 4)]))
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.5) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        ev += key_tap("main_screen", V + 11.0) + key_tap("disk", V + 12.0) + key_tap("4", V + 14.0)
        ev += key_tap("soft1", V + 17.0)
        pgml = program_file(runs, lsrc, "digitcol.pgm")
        cases["digitcol"] = h.Case(events=ev, times=[V + 6.8, V + 10.5, V + 55.0],
                                   files=[(pgml, "MUTE.PGM"), (lsrc, lsrc.name), (lold, "LOOP101.SND")],
                                   parts=("lazychop", "snddump"),
                                   env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": f"{V + 10.5}"})
        # #2: MIDI notes every 100 ms while the Slices to Program page is up: ENTER counts.
        cvm = sound("CVMIDI", [signal(SR * 2, 5)])
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.5) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        midi_ev = []
        for k in range(36):
            at = round(V + 6.0 + 0.1 * k, 3)
            midi_ev += [(at, bytes((0x90, 0x62, 0x60))), (round(at + 0.03, 3), bytes((0x80, 0x62, 0x00)))]
        mid = write_smf(runs / "cvmidi-midi.mid", midi_ev)
        add("cvmidi", cvm, ev, [V + 5.2, V + 10.5], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"},
            kwargs={"extra": ["-midiin1", str(mid)], "snapshot": False})
        # #3: '0' (a key the count field ignores) closes "Equal zones again?".
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.5) + hit(2, V + 4.0)
        ev += key_tap("soft3", V + 5.0) + key_tap("right", V + 5.5) + dial(1, V + 6.0) + key_tap("0", V + 6.5)
        add("askdigit", take6, ev, [V + 6.3, V + 7.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})
        # #4: slice 2's start stepped, pad 3 selects slice 3, its start stepped, Right.
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0)
        for t in (3.5, 4.0, 4.5):
            ev += hit(2, V + t)
        ev += key_tap("soft3", V + 5.0) + hit(2, V + 5.5) + h.taps((V + 6.0, "left"), (V + 6.4, "left"))
        ev += dial(1, V + 6.8) + hit(3, V + 7.5) + dial(1, V + 8.0) + key_tap("right", V + 8.6)
        add("settlelost", take6, ev, [V + 5.3, V + 7.2, V + 8.3, V + 9.2],
            env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})
        # #5: a readable, empty SCSI partition (the boot scan mounts it) is a checked
        # disk; a floppy taken out before Convert is not.
        from emu import test_scsi316 as ts
        hd = ts.RUNS / profile.label / "fixture.hd"
        if not hd.exists():
            hd = ts.fixture(profile)
        disk = runs / "cvscsi.hd"
        disk.write_bytes(hd.read_bytes())
        scs = sound("SCSIC", [signal(SR * 2, 5)])
        ev = h.taps((56.0, "program_sounds"), (56.8, "6"), (59.0, "help"))
        V = 65.0
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.5) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        add("cvscsi", scs, ev, [V + 5.2, V + 11.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"},
            kwargs={"extra": ts.scsi(disk, 0), "snapshot": False})
        ev, V = open_view()
        ev += zone_page(V + 0.5) + key_tap("soft1", V + 2.0) + hit(1, V + 3.0) + hit(2, V + 3.4) + hit(2, V + 3.8)
        ev += key_tap("soft3", V + 4.5) + key_tap("soft3", V + 5.5) + key_tap("enter", V + 7.0)
        add("cvnodisk", scs, ev, [V + 5.2, V + 14.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0",
                                                          "EJECT_AT": str(V + 6.0)}, prelude=EJECT)
        # #6: + and - are coalesced in the cave as BDE3:000E coalesced them: five
        # wheel steps 1 ms apart move zone 1's end as far as five 50 ms apart.
        ev, V = open_view()
        ev += hit(1, V + 1.0) + key_tap("right", V + 1.5) + h.burst(5, V + 2.0) + dial(5, V + 3.0, gap=0.05)
        add("burst", test4, ev, [V + 1.8, V + 2.8, V + 4.0], env={"LC_FROM": str(V - 1.0), "SNDDUMP_PCM": "0"})
        return cases

    # ------------------------------------------------------------ helpers
    def runs_of(self, case: str):
        for label, d, _ in self.each(case):
            profile = self.profiles[label]
            events, snaps = parse(d)
            yield label, profile, d, events, snaps

    def view_time(self, profile, tempo=None) -> float:
        return open_view(tempo)[1]

    # ------------------------------------------------------------ phase 1
    def test_zones_pads_banks_and_held_pad(self):
        for label, profile, d, ev, snaps in self.runs_of("zones"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                before, opened, released = at(snaps, V - 3.5), at(snaps, V + 0.5), at(snaps, V + 1.5)
                self.assertEqual((before["owned"], before["held"]), (0, 1))     # pad 4 held, stock press
                self.assertEqual((opened["owned"], opened["held"]), (1, 1))     # D1: the view owns the pads
                self.assertEqual(released["held"], 0)                            # its release reached stock
                rel = kinds(ev, "RING5", V, V + 1.2)
                self.assertEqual([r["count"] for r in rel[:3]], [1, 2, 3], rel)  # the 3-byte release, stock ISR
                # No stock note-on and no ring-5 event for any owned pad.
                self.assertEqual(kinds(ev, "NOTEON", V + 1.5, V + 12.5), [])
                self.assertEqual(kinds(ev, "RING5", V + 1.5, V + 12.5), [])
                base = h.sound_records(d, V + 0.5)[0]["wave"]
                n = SR * 4
                keyons = kinds(ev, "KEYON", V + 1.5, V + 12.5)
                starts = [k["start"] - base for k in keyons]
                b16 = [n * i // 16 for i in range(17)]
                b64 = [n * i // 64 for i in range(65)]
                self.assertEqual(starts, [b16[0], b16[2], b16[1], b16[4], b16[5], b64[16], b64[63]])
                self.assertEqual(len(kinds(ev, "AUD", V + 1.5, V + 12.5)), len(keyons))   # one audition path (R2)
                # Mono: pad 2's channel stopped by the cave before pad 5 keys on.
                stops = [s for s in kinds(ev, "STOP", V + 3.0, V + 3.2) if s["caller"] == CAVE_CALLER]
                self.assertEqual([s["ch"] for s in stops], [keyons[2]["ch"]])
                self.assertLess(stops[0]["t"], keyons[3]["t"])
                z = at(snaps, V + 8.8)
                self.assertEqual((z["mode"], z["count"]), (0, 64))
                self.assertEqual(z["pairs"], [[b64[i], b64[i + 1]] for i in range(64)])
                self.assertEqual(at(snaps, V + 12.5)["bank"], 0)
                # #14: the owned pad's pressure never reached the held table
                self.assertEqual(at(snaps, V + 3.55)["pressure"], [0] * 64)
                # #9: Pad Bank alone redraws the bank shown
                px = h.lcd_pixels(d)[f"{V + 9.3:.3f}"]
                self.assertTrue(shows(px, 49, 26, "Bank B"))

    def test_ownership_ends_on_every_exit(self):
        for label, profile, d, ev, snaps in self.runs_of("exits"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                owned = [snaps[round(V + x, 3)]["owned"] for x in (0.3, 2.5, 7.2, 9.5, 14.2, 16.0, 23.2, 25.5)]
                self.assertEqual(owned, [1, 0, 1, 0, 1, 0, 1, 0])
                for at, what in self.exit_steps:
                    if what not in ("owned", "stock"):
                        continue
                    notes = kinds(ev, "NOTEON", at, at + 0.2)
                    isr = kinds(ev, "ISR", at, at + 0.2)
                    if what == "stock":
                        self.assertTrue(notes, f"no stock note-on for the pad at {at}")
                        self.assertEqual(isr, [])
                    else:
                        self.assertEqual(notes, [], f"stock note-on while owned at {at}")
                        self.assertEqual(len(isr), 1)

    def test_error_box_releases_the_pads_and_short_slices_create_nothing(self):
        for label, profile, d, ev, snaps in self.runs_of("errorbox"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertEqual(at(snaps, V + 4.0)["owned"], 0)                # "Slice too short" is showing
                self.assertTrue(kinds(ev, "NOTEON", V + 4.5, V + 4.7))      # the pad plays its program note
                self.assertEqual(at(snaps, V + 5.5)["owned"], 1)                # acknowledged: the view again
                self.assertEqual(kinds(ev, "NOTEON", V + 6.0, V + 6.3), [])
                self.assertEqual(h.sound_records(d, V), h.sound_records(d, V + 6.5))
                self.assertEqual(at(snaps, V)["programs"][1], at(snaps, V + 6.5)["programs"][1])

    def test_midi_voice_survives_the_mono_stops(self):
        for label, profile, d, ev, snaps in self.runs_of("midi"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertTrue(kinds(ev, "NOTEON", V + 1.0, V + 1.2))      # D8: MIDI is not owned
                midi = kinds(ev, "KEYON", V + 1.0, V + 1.2)
                self.assertEqual(len(midi), 1)
                pads = kinds(ev, "KEYON", V + 1.5, V + 2.0)
                self.assertEqual(len(pads), 3)
                stops = kinds(ev, "STOP", V + 1.5, V + 2.0)
                self.assertEqual([s["ch"] for s in stops], [pads[0]["ch"], pads[1]["ch"]])
                self.assertNotIn(midi[0]["ch"], [s["ch"] for s in kinds(ev, "STOP", V + 1.0, V + 2.5)])
                self.assertEqual(at(snaps, V + 2.5)["owner"][midi[0]["ch"]], 0x23)   # still sounding

    # ------------------------------------------------------------ phase 2
    def check_take(self, case: str, offset_ms: int = 0, tempo=None, phases_cover: bool = True):
        results = {}
        for label, profile, d, ev, snaps in self.runs_of(case):
            with self.subTest(set=label, case=case):
                V = self.view_time(profile, tempo)
                if tempo:
                    self.assertRegex((d / "screens.txt").read_text(), rf"BPM: *{tempo}\.0")
                isr = kinds(ev, "ISR", V + 2.9, V + 9.5)
                t0 = kinds(ev, "T0", V + 2.9, V + 9.5)
                self.assertEqual(len(isr), 31)
                self.assertEqual(len(t0), 1)
                # A1: one key-on (the take), after the first hit; no stock note-on, no ring 5.
                self.assertEqual(len(kinds(ev, "KEYON", V + 2.9, V + 9.5)), 1)
                self.assertEqual(kinds(ev, "NOTEON", V, V + 10.0), [])
                self.assertEqual(kinds(ev, "RING5", V, V + 10.0), [])
                k = offset_ms * 2000
                final = at(snaps, V + 10.0)
                self.assertEqual((final["phase"], final["mode"], final["count"], final["dropped"]), (0, 1, 31, 0))
                starts = [p[0] for p in final["pairs"]]
                self.assertEqual(starts[0], 0)                                 # D2: frame 0
                errors, latency, phases = [], [], []
                # The hit's reference time: the entry of its timestamp call 2B50:0194
                # (TS, in the ISR), which reads the counter; the ISR's own log comes
                # after 0194's STI window, where a tick ISR can delay it ~30 us.
                stamps = [x for x in kinds(ev, "TS", V + 2.9, V + 9.5) if not x["ui"]]
                for i, e in enumerate(isr[1:], 1):
                    self.assertEqual(starts[i], lc_pos(e["raw"], t0[0]["raw"], k))
                    ts = max((x["t"] for x in stamps if x["t"] <= e["t"]), default=e["t"])
                    self.assertLess(e["t"] - ts, 0.0002)
                    want = (ts - t0[0]["t"] - offset_ms / 1000) * SR
                    errors.append(starts[i] - want)
                    latency.append(e["t"] - take_times(V)[i - 1])
                    phases.append(e["raw"] % 20_000)
                self.assertLessEqual(max(abs(x) for x in errors), 1.0, errors)      # A2: +-1 frame
                self.assertEqual(starts, sorted(starts))                            # A7: monotonic
                if phases_cover:        # the injected base of "wrap" moves the TCT0 phase
                    self.assertTrue(any(p <= 1000 for p in phases), phases)         # just after a tick
                    self.assertTrue(any(p >= 19_000 for p in phases), phases)       # just before one
                    self.assertGreater(len({p // 640 for p in phases}), 20, phases)  # 0.32 ms steps
                self.assertEqual(final["pairs"][-1][1], 6 * SR)
                # #6: no timestamp call (2B50:0194) on the UI task during the take
                self.assertEqual([e for e in kinds(ev, "TS", V + 2.9, V + 10.0) if e["ui"]], [])
                self.assertEqual(len(kinds(ev, "TS", V + 2.9, V + 10.0)), 31)      # one per hit, in the ISR
                results[label] = (errors, latency)
        return results

    def test_take_timing_120(self):
        self.check_take("timing120")

    def test_take_timing_30_and_tune0(self):
        res = self.check_take("timing30", tempo="30")
        for label, profile, d, ev, snaps in self.runs_of("timing30"):
            with self.subTest(set=label):
                V = self.view_time(profile, "30")
                take = kinds(ev, "KEYON", V + 2.9, V + 3.2)[0]
                pad = kinds(ev, "KEYON", V + 10.4, V + 10.8)[0]
                self.assertNotEqual(take["step"], pad["step"])          # D10: the take at Tune 0
                self.assertEqual(h.sound_records(d, V + 11.5)[0]["tune"], -12)
                ref = kinds(parse(self.RUNS / label / "timing120")[0], "KEYON", 0)
                self.assertIn(take["step"], {k["step"] for k in ref})
        self.assertTrue(res)

    def test_take_timing_300(self):
        res = self.check_take("timing300", tempo="300")
        ref = self.check_take("timing120")
        for label in res:
            lat300, lat120 = res[label][1], ref[label][1]
            # The same link latency: at most the worst interrupt-off window apart
            # (emu/fixtures/cycle_budget_316.json ifoff_max_us_play, 112 us).
            self.assertLess(max(abs(a - b) for a, b in zip(lat300, lat120)), 120e-6)

    def test_user_offset(self):
        self.check_take("offset", offset_ms=5)
        for label, profile, d, ev, snaps in self.runs_of("offset"):
            self.assertEqual(at(snaps, self.view_time(profile) + 2.8)["offset"], 5)

    def test_time_base_wrap(self):
        for label, profile, d, ev, snaps in self.runs_of("wrap"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                raws = [e["raw"] for e in kinds(ev, "ISR", V + 2.9, V + 9.5)]
                self.assertTrue(any(b < a for a, b in zip(raws, raws[1:])), raws)   # the base wrapped
        self.check_take("wrap", phases_cover=False)

    # ------------------------------------------------------------ phase 3
    def test_roll_and_snap(self):
        x = signal(SR * 6)
        for label, profile, d, ev, snaps in self.runs_of("roll"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                rec = at(snaps, V + 4.2)
                # A3 with the stock minimum (B2): a hit under LC_MIN frames after the
                # previous chop is no chop; hits 12 ms apart chop every third.
                isr = kinds(ev, "ISR", V + 2.9, V + 4.2)
                t0 = kinds(ev, "T0", V + 2.9, V + 4.2)[0]
                want = [0]
                for e in isr[1:]:
                    p = lc_pos(e["raw"], t0["raw"])
                    if p - want[-1] >= LC_MIN and p + LC_MIN <= 6 * SR:
                        want.append(p)
                n = len(want)
                self.assertEqual((len(isr), n), (21, 8))
                self.assertEqual((rec["phase"], rec["nchops"], rec["dropped"]), (2, n, 0))
                self.assertLess(h.blits(d, V + 3.45, V + 4.05), 20)        # redraws coalesced (20 hits)
                ref = at(snaps, V + 5.5)
                self.assertEqual((ref["phase"], ref["mode"], ref["count"]), (0, 1, n))         # <Done>
                raw, starts = rec["chops"], [p[0] for p in ref["pairs"]]
                self.assertEqual(raw[:n], want)
                snapped = [0]
                for i in range(1, n):
                    hi = (raw[i + 1] if i + 1 < n else 6 * SR) - LC_MIN
                    snapped.append(snap_ref(x, raw[i], snapped[-1] + LC_MIN, hi))
                self.assertEqual(starts, snapped)                         # D4
                self.assertTrue(all(crossing(x, p) for p in starts[1:]))
                self.assertEqual([p[1] for p in ref["pairs"]], starts[1:] + [6 * SR])
                self.assertTrue(all(b - a >= LC_MIN for a, b in ref["pairs"][:n]))

    def test_refine_pads_banks_and_selection(self):
        for label, profile, d, ev, snaps in self.runs_of("refine"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                ref = at(snaps, V + 6.2)
                self.assertEqual((ref["phase"], ref["mode"], ref["count"]), (0, 1, 21))
                starts = [p[0] for p in ref["pairs"]]
                base = h.sound_records(d, V + 6.2)[0]["wave"]
                keyons = kinds(ev, "KEYON", V + 6.4, V + 9.5)
                # A01 -> slice 3, B01 -> slice 17, B06 -> none (21 slices), B05 -> slice 21
                self.assertEqual([k["start"] - base for k in keyons], [starts[2], starts[16], starts[20]])
                self.assertEqual(len(kinds(ev, "AUD", V + 6.4, V + 9.5)), 3)
                self.assertEqual(at(snaps, V + 10.0)["current"], 21)          # selection follows the pad
                self.assertEqual(at(snaps, V + 10.0)["bank"], 0)

    def test_chops_edit_isolation_and_refusals(self):
        for label, profile, d, ev, snaps in self.runs_of("edit"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                step = 6 * SR // 240
                a, b, c, e, f = (at(snaps, V + x)["pairs"] for x in (6.3, 7.7, 9.2, 12.2, 23.0))
                self.assertEqual(at(snaps, V + 6.3)["current"], 3)
                self.assertEqual(b[2], [a[2][0], a[2][1] + 2 * step])     # slice 3 end
                self.assertEqual(c[2], [a[2][0] - step, b[2][1]])         # slice 3 start
                for p in (b, c, e, f):
                    self.assertEqual(p[:2] + p[3:], a[:2] + a[3:])         # slices 2 and 4 untouched
                lo = c[2][0] + LC_MIN
                self.assertGreaterEqual(e[2][1], lo)                      # refused below start + LC_MIN
                self.assertLess(e[2][1] - step, lo)
                self.assertLessEqual(f[2][1], 6 * SR)                     # refused past the Source
                self.assertGreater(f[2][1] + step, 6 * SR)

    def test_numeric_start_snaps(self):
        x = signal(SR * 6)
        for label, profile, d, ev, snaps in self.runs_of("numeric"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                before, after = at(snaps, V + 7.0), at(snaps, V + 14.0)
                self.assertEqual((before["mode"], before["count"], before["current"], before["sel"]), (1, 3, 2, 2))
                end = before["pairs"][1][1]
                want = snap_ref(x, 35_280, 0, end - LC_MIN)          # 0.800 s
                self.assertNotEqual(want, 35_280)
                self.assertEqual(after["pairs"][1], [want, end])
                self.assertEqual([after["pairs"][0], after["pairs"][2]], [before["pairs"][0], before["pairs"][2]])

    def test_cancel_stop_and_mode_key(self):
        for label, profile, d, ev, snaps in self.runs_of("cancel"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                before = at(snaps, V + 2.5)
                self.assertEqual(at(snaps, V + 4.3)["phase"], 2)
                cancelled = at(snaps, V + 5.0)
                self.assertEqual((cancelled["phase"], cancelled["mode"], cancelled["pairs"]),
                                 (0, 0, before["pairs"]))
                take = kinds(ev, "KEYON", V + 2.9, V + 3.2)[0]
                stops = [s for s in kinds(ev, "STOP", V + 4.4, V + 4.8) if s["caller"] == CAVE_CALLER]
                self.assertEqual([s["ch"] for s in stops], [take["ch"]])
                self.assertEqual(at(snaps, V + 7.8)["phase"], 2)
                stopped = at(snaps, V + 9.0)
                self.assertEqual((stopped["phase"], stopped["mode"], stopped["count"]), (0, 1, 3))
                left = at(snaps, V + 13.0)
                self.assertEqual(at(snaps, V + 11.8)["phase"], 2)
                self.assertEqual((left["owned"], left["phase"], left["mode"], left["pairs"]),
                                 (0, 0, 1, stopped["pairs"]))

    def test_64_slices(self):
        for label, profile, d, ev, snaps in self.runs_of("cap64"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                s = at(snaps, V + 5.8)
                self.assertEqual((s["phase"], s["mode"], s["count"], s["note"]), (0, 1, 64, 1))
                self.assertEqual(len(kinds(ev, "ISR", V + 2.9, V + 5.7)), 64)
                self.assertEqual(at(snaps, V + 6.4)["pairs"], s["pairs"])
                base = h.sound_records(d, V + 5.8)[0]["wave"]
                keyon = kinds(ev, "KEYON", V + 5.9, V + 7.6)
                self.assertEqual([k["start"] - base for k in keyon], [s["pairs"][1][0], s["pairs"][63][0]])

    # ------------------------------------------------------------ phase 4
    def test_convert_defaults(self):
        x = signal(SR * 2, 5)
        for label, profile, d, ev, snaps in self.runs_of("convert"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                refine = at(snaps, V + 5.2)
                n = refine["count"]
                self.assertEqual((refine["mode"], n), (1, 4))
                old, new = h.sound_records(d, V + 5.2), h.sound_records(d, V + 9.5)
                made = {i: r for i, r in new.items() if i not in old}
                self.assertEqual(sorted(r["name"] for r in made.values()), [f"BREAKS{k:02d}" for k in range(1, 5)])
                by_name = {r["name"]: i for i, r in made.items()}
                for k, (a, b) in enumerate(refine["pairs"]):
                    i = by_name[f"BREAKS{k + 1:02d}"]
                    self.assertEqual(made[i]["length"], b - a)
                    self.assertEqual(h.pcm(d, V + 9.5, i), struct.pack(f"<{b - a}h", *x[a:b]))   # bit-exact
                after = at(snaps, V + 9.5)
                self.assertEqual(after["program"], 1)                    # the first empty after program 1
                prog = after["programs"][1]
                self.assertEqual(prog["name"].rstrip(), "BREAKS")
                notes = prog["map"]
                want = [0xFF] * 64
                for k in range(n):
                    want[notes[k] - 35] = by_name[f"BREAKS{k + 1:02d}"]
                self.assertEqual(prog["sounds"], want)                   # slot order (A01..A04)
                self.assertEqual(after["mute"][1], {"enabled": 1, "groups": [1] * n + [0] * (64 - n)})
                self.assertEqual(at(snaps, V + 5.2)["programs"][0], after["programs"][0])
                keyons = kinds(ev, "KEYON", V + 10.9, V + 13.5)
                bases = [made[by_name[f"BREAKS{k:02d}"]]["wave"] for k in range(1, 5)]
                self.assertEqual([k["start"] for k in keyons], bases)    # pads key on the slices
                choke = [s for s in kinds(ev, "STOP", V + 11.2, V + 11.5) if s["caller"] == CAVE_CALLER]
                self.assertEqual([s["ch"] for s in choke], [keyons[0]["ch"]])   # D7: mute group 1
                # #8: choke ON makes each slice note MONO (+6 = 1), the others stay POLY
                poly = prog["poly"]
                self.assertEqual(sorted(k for k in range(64) if poly[k]), sorted(notes[k] - 35 for k in range(n)))
                self.assertEqual({poly[notes[k] - 35] for k in range(n)}, {1})
                # #10: pads hit while the sounds were made are not played afterwards
                self.assertEqual(kinds(ev, "AUD", V + 7.0, V + 10.0), [])
                self.assertEqual(after["note"], 1)                       # #16: "04 sounds, program 02"
                self.assertTrue(shows(h.lcd_pixels(d)[f"{V + 9.5:.3f}"], 49, 0, "04 sounds, program 02"))

    def test_replace_prompt_choke_off_stereo(self):
        planes = [signal(SR * 2, 7), signal(SR * 2, 9)]
        for label, profile, d, ev, snaps in self.runs_of("replace"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                refine = at(snaps, V + 4.8)
                n = refine["count"]
                self.assertEqual((refine["mode"], n), (1, 3))
                self.assertEqual(at(snaps, V + 9.0)["programs"][0], refine["programs"][0])   # the prompt was cancelled
                self.assertNotEqual(at(snaps, V + 9.0)["cvstatus"], 0)                       # #16: "Program kept"
                old, new = h.sound_records(d, V + 4.8), h.sound_records(d, V + 14.0)
                made = {i: r for i, r in new.items() if i not in old}
                self.assertEqual(len(made), n)
                by_name = {r["name"]: i for i, r in made.items()}
                for k, (a, b) in enumerate(refine["pairs"]):
                    i = by_name[f"STEREO{k + 1:02d}"]
                    want = b"".join(struct.pack(f"<{b - a}h", *p[a:b]) for p in planes)
                    self.assertEqual(h.pcm(d, V + 14.0, i), want)
                after = at(snaps, V + 14.0)
                self.assertEqual(after["program"], 0)
                self.assertEqual(after["programs"][0]["name"].rstrip(), "STEREO")
                self.assertEqual(after["mute"][0], {"enabled": 0, "groups": [0] * 64})
                self.assertEqual(set(after["programs"][0]["poly"]), {0})            # #8: choke OFF keeps POLY

    def test_mode_key_acknowledges_a_message_and_leaves(self):
        for label, profile, d, ev, snaps in self.runs_of("errmode"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertEqual(at(snaps, V + 4.0)["owned"], 0)
                left = at(snaps, V + 6.0)
                self.assertEqual((left["owned"], chr(left["mode_key"])), (0, "F"))   # Disk
                self.assertTrue(kinds(ev, "NOTEON", V + 6.5, V + 6.7))

    def test_stock_error_box_releases_the_pads(self):
        for label, profile, d, ev, snaps in self.runs_of("errbox"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertEqual(at(snaps, V + 0.5)["owned"], 1)
                box = at(snaps, V + 2.5)
                self.assertEqual((box["owned"], box["box"]), (0, 1))
                self.assertTrue(kinds(ev, "NOTEON", V + 3.0, V + 3.2))      # the box is up: stock
                # <Exit> (Soft Key 1) closes it; the stock box path then returns to
                # Play/Record, so the view has closed and the pads stay stock.
                after = at(snaps, V + 4.5)
                self.assertEqual((after["owned"], after["box"], chr(after["mode_key"])), (0, 0, "M"))
                self.assertTrue(kinds(ev, "NOTEON", V + 5.0, V + 5.2))
                self.assertTrue(kinds(ev, "NOTEON", V + 6.5, V + 6.8))
                self.assertIn("Play/Record", (d / "screens.txt").read_text().split("@ ")[-1])

    def test_snap_when_the_field_is_left_and_equal_zones_again(self):
        x = signal(SR * 6)
        for label, profile, d, ev, snaps in self.runs_of("settle"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                a, b, c = at(snaps, V + 6.8), at(snaps, V + 7.5), at(snaps, V + 8.5)
                self.assertEqual((a["current"], a["sel"], a["onview"]), (2, 2, 0))
                step = 6 * SR // 240
                start = a["pairs"][1][0] + step
                self.assertEqual(b["pairs"][1][0], start)              # the wheel step is exact
                want = snap_ref(x, start, 0, b["pairs"][1][1] - LC_MIN)
                self.assertNotEqual(want, start)
                self.assertEqual(c["pairs"][1][0], want)               # snapped when Right left it
                self.assertEqual([c["pairs"][0], c["pairs"][2]], [a["pairs"][0], a["pairs"][2]])
                ask, eq = at(snaps, V + 10.5), at(snaps, V + 11.5)
                self.assertEqual((ask["onview"], ask["mode"], ask["note"]), (3, 1, 1))
                self.assertEqual((eq["mode"], eq["count"]), (0, 3))
                self.assertEqual(eq["pairs"], [[6 * SR * i // 3, 6 * SR * (i + 1) // 3] for i in range(3)])

    def test_safe_lock_refuses_convert(self):
        for label, profile, d, ev, snaps in self.runs_of("lockbypass"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                before, after = at(snaps, V + 5.2), at(snaps, V + 9.5)
                self.assertEqual(before["mode"], 1)
                self.assertEqual(h.sound_records(d, V + 5.2), h.sound_records(d, V + 9.5))
                self.assertEqual(before["programs"], after["programs"])
                self.assertNotEqual(after["cvstatus"], 0)               # "Stop the sequencer first"

    def test_slot_is_the_parser_s_under_midi_traffic(self):
        for label, profile, d, ev, snaps in self.runs_of("d399race"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                base = h.sound_records(d, V + 0.5)[0]["wave"]
                isr = kinds(ev, "ISR", V + 0.9, V + 12.0)
                self.assertEqual(len(isr), 200)
                keyons = [k for k in kinds(ev, "KEYON", V + 0.9, V + 12.0) if k["cs"] == "8C25"]
                auds = kinds(ev, "AUD", V + 0.9, V + 12.0)
                self.assertEqual(len(auds), 200)                         # no hit lost to a wrong slot
                pads = [k for k in kinds(ev, "KEYON", V + 0.9, V + 12.0)
                        if any(abs(k["t"] - a["t"]) < 0.0002 for a in auds)]
                self.assertEqual({k["start"] - base for k in pads}, {0})

    def test_keystroke_traps_make_nothing(self):
        for label, profile, d, ev, snaps in self.runs_of("traps"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                first = h.sound_records(d, V + 2.5)
                for t in (5.4, 6.5, 9.5, 10.5, 12.5):
                    self.assertEqual(h.sound_records(d, V + t), first, t)
                    self.assertEqual(at(snaps, V + t)["programs"], at(snaps, V + 2.5)["programs"], t)
                self.assertEqual(at(snaps, V + 5.4)["mode"], 1)          # it ended by itself
                self.assertEqual(at(snaps, V + 6.5)["phase"], 1)         # Soft 1 armed a new take, no page

    def test_second_convert_round_trip(self):
        """#2: two Converts: no ZONEnnn, Sound and program names unique; the second
        program saved with its sounds next to an old ZONE000.SND and reloaded."""
        for label, profile, d, ev, snaps in self.runs_of("convert2"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                one, two = at(snaps, V + 9.5), at(snaps, V + 17.5)
                recs = h.sound_records(d, V + 17.5)
                names = sorted(r["name"] for r in recs.values())
                self.assertEqual(names, sorted(["BREAKS", "BREAKS01", "BREAKS02", "BREAKS03",
                                                "BREAKS101", "BREAKS102"]))
                p1, p2 = one["program"], two["program"]
                self.assertNotEqual(p1, p2)
                self.assertEqual(two["programs"][p1]["name"].rstrip(), "BREAKS")
                self.assertEqual(two["programs"][p2]["name"].rstrip(), "BREAKS02")
                # Reload: the saved floppy itself (the 16-character names live in its
                # directory tails) without MUTE.PGM, so the start-up loader takes the
                # saved program and its sounds, on a fresh machine.
                image = h.BUILD / "disks" / f"{label}-{label}-convert2.img"
                runs = self.RUNS / label
                img2 = runs / "c2-reload.img"
                img2.write_bytes(image.read_bytes())
                subprocess.run(["mdel", "-i", str(img2), "::MUTE.PGM"], check=True)
                from emu.mpc3k import run
                ev2 = h.taps((CANCEL, "soft4")) + hit(1, 54.0) + hit(2, 54.5)
                script = h.observer(profile, runs / "c2-reload.lua", ["lazychop", "snddump"])
                run(profile.bios, [53.5, 55.5], runs / "c2-reload", floppy=img2,
                    panel=write_smf(runs / "c2-reload.mid", ev2), rompath=profile.rompath,
                    extra=["-autoboot_script", str(script)], env={"LC_FROM": "52", "SNDDUMP_PCM": "53.5"})
                rev, rsnaps = parse(runs / "c2-reload")
                rrecs = h.sound_records(runs / "c2-reload", 53.5)
                byname = {r["name"]: i for i, r in rrecs.items()}
                prog = rsnaps[53.5]["programs"][0]
                for k, name in ((1, "BREAKS101"), (2, "BREAKS102")):
                    note = prog["map"][k - 1]
                    self.assertEqual(prog["sounds"][note - 35], byname[name], (name, rrecs))
                    want = h.pcm(d, V + 17.5, next(i for i, r in recs.items() if r["name"] == name))
                    self.assertEqual(h.pcm(runs / "c2-reload", 53.5, byname[name]), want)
                keyons = kinds(rev, "KEYON", 53.9, 55.0)
                self.assertEqual([k["start"] for k in keyons][:2],
                                 [rrecs[byname["BREAKS101"]]["wave"], rrecs[byname["BREAKS102"]]["wave"]])

    # ------------------------------------------------------------ second review
    def test_bank_follows_after_filtered_keys_and_kicks(self):
        """B1: a kick and COUNT IN (keys the global filter takes) do not leave the
        view waiting in BDE3:000E: Pad Bank alone still redraws the bank."""
        for label, profile, d, ev, snaps in self.runs_of("kickbank"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                px = h.lcd_pixels(d)
                self.assertEqual(at(snaps, V + 0.8)["bank"] >> 4, 0)
                self.assertTrue(shows(px[f"{V + 2.5:.3f}"], 49, 26, "Bank B"))
                self.assertTrue(shows(px[f"{V + 3.8:.3f}"], 49, 26, "Bank C"))
                self.assertEqual(at(snaps, V + 4.5)["owned"], 1)
                self.assertEqual(len(kinds(ev, "ISR", V + 4.0, V + 4.5)), 1)        # owned (bank C: no zone)
                self.assertEqual(kinds(ev, "NOTEON", V + 4.0, V + 4.5), [])

    def test_stock_box_after_a_kick_has_the_pads_stock(self):
        """B1: the overflow's flags and kick after an earlier kick: the box is up
        with the pads stock; <Exit> leaves to Play/Record."""
        for label, profile, d, ev, snaps in self.runs_of("kickbox"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertEqual(at(snaps, V + 0.5)["owned"], 1)
                box = at(snaps, V + 2.5)
                self.assertEqual((box["owned"], box["box"]), (0, 1))
                self.assertTrue(kinds(ev, "NOTEON", V + 3.0, V + 3.2))
                self.assertTrue(kinds(ev, "NOTEON", V + 3.5, V + 3.7))
                self.assertEqual(kinds(ev, "ISR", V + 2.5, V + 4.0), [])
                after = at(snaps, V + 4.5)
                self.assertEqual((after["owned"], chr(after["mode_key"])), (0, "M"))

    def test_stock_box_on_the_convert_page_has_the_pads_stock(self):
        """B1: the box on the Slices to Program page: pads stock while it is up;
        its <Exit> is no <Do it>; the page is drawn again and ENTER makes them."""
        for label, profile, d, ev, snaps in self.runs_of("cvbox"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertEqual(at(snaps, V + 5.2)["owned"], 1)
                self.assertEqual(at(snaps, V + 7.0)["owned"], 0)
                self.assertTrue(kinds(ev, "NOTEON", V + 7.5, V + 7.7))
                self.assertEqual(kinds(ev, "ISR", V + 7.0, V + 8.0), [])
                back = at(snaps, V + 9.5)
                self.assertEqual((back["owned"], chr(back["mode_key"])), (1, "L"))
                first = h.sound_records(d, V + 5.2)
                self.assertEqual(h.sound_records(d, V + 9.5), first)
                made = {i: r for i, r in h.sound_records(d, V + 12.0).items() if i not in first}
                self.assertEqual(sorted(r["name"] for r in made.values()), ["CVBOX01", "CVBOX02"])

    def test_stock_minimum_length_rule(self):
        """B2 evidence: stock 3.16 keys on a 1368-frame Sound and not a 1367-frame
        one (20ED:0697..06C0, LC_MIN)."""
        lens = (1300, 1367, 1368, 1400)
        for label, profile, d, ev, snaps in self.runs_of("short"):
            with self.subTest(set=label):
                stock = stock_of(profile)
                runs = self.RUNS / label
                paths = []
                for n in lens:
                    path = runs / f"L{n}.SND"
                    path.write_bytes(snd(f"L{n}", [signal(n, 9)]))
                    paths.append(path)
                data = bytearray(pgm_fixture.for_sound(TEMPLATE.read_bytes(), paths[0].read_bytes(), pads=(),
                                                      program_name="LENS"))
                for k, path in enumerate(paths):
                    sb = path.read_bytes()
                    data[pgm_fixture.NAME_DIRECTORY + 17 * k:pgm_fixture.NAME_DIRECTORY + 17 * (k + 1)] = sb[2:19]
                    frames = struct.unpack_from("<I", sb, 2 + 0x1C)[0]
                    struct.pack_into("<I", data, pgm_fixture.METADATA_DIRECTORY + 4 * k, frames * (sb[2 + 0x13] + 1))
                    data[pgm_fixture.NOTE_RECORDS + k * pgm_fixture.NOTE_RECORD_BYTES] = k
                pgm = runs / "lens.pgm"
                pgm.write_bytes(bytes(data))
                midi = []
                for k in range(len(lens)):
                    a = round(54.0 + 0.4 * k, 3)
                    midi += [(a, bytes((0x90, 35 + k, 0x7F))), (round(a + 0.2, 3), bytes((0x80, 35 + k, 0)))]
                mid = write_smf(runs / "lens.mid", midi)
                h.run_case(stock, runs, "stockmin", times=[53.5, 56.0], events=h.taps((CANCEL, "soft4")),
                           files=[(pgm, "MUTE.PGM")] + [(x, x.name) for x in paths], parts=("lazychop", "snddump"),
                           env={"LC_FROM": "52", "SNDDUMP_PCM": "0"}, extra=["-midiin1", str(mid)], snapshot=False)
                rev, _ = parse(runs / "stockmin")
                recs = h.sound_records(runs / "stockmin", 53.5)
                waves = {r["name"]: r["wave"] for r in recs.values()}
                self.assertEqual(sorted(waves), sorted(f"L{n}" for n in lens))
                got = sorted(k["start"] for k in kinds(rev, "KEYON", 53.9, 56.0))
                self.assertEqual(got, sorted(waves[f"L{n}"] for n in lens if n >= LC_MIN))

    def test_short_gaps_are_no_chops_and_every_slice_plays(self):
        """B2: no slice under LC_MIN: what auditions in the view plays after Convert."""
        for label, profile, d, ev, snaps in self.runs_of("short"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                ref = at(snaps, V + 4.3)
                self.assertEqual((ref["mode"], ref["count"]), (1, 3))
                self.assertTrue(all(b - a >= LC_MIN for a, b in ref["pairs"][:3]), ref["pairs"][:3])
                self.assertEqual(len(kinds(ev, "AUD", V + 4.3, V + 5.5)), 3)
                old, new = h.sound_records(d, V + 4.3), h.sound_records(d, V + 9.5)
                made = {i: r for i, r in new.items() if i not in old}
                self.assertEqual(len(made), 3)
                keyons = kinds(ev, "KEYON", V + 10.9, V + 13.0)
                self.assertEqual(sorted(k["start"] for k in keyons), sorted(r["wave"] for r in made.values()))

    def test_short_equal_zones_say_so_and_convert_refuses(self):
        """B2: a 620-frame Equal Division zone: the pad says "Slice too short";
        Convert says "Slice 01 too short" (the pads stock) and makes nothing."""
        for label, profile, d, ev, snaps in self.runs_of("eqshort"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                z = at(snaps, V + 5.3)
                self.assertEqual((z["mode"], z["count"]), (0, 64))
                px = h.lcd_pixels(d)
                self.assertTrue(shows(px[f"{V + 6.0:.3f}"], 49, 0, "Slice too short"))
                self.assertEqual(kinds(ev, "KEYON", V + 5.4, V + 6.0), [])
                self.assertTrue(shows(px[f"{V + 8.2:.3f}"], 40, 0, "Slice 01 too short"))
                self.assertEqual(at(snaps, V + 8.2)["owned"], 0)
                self.assertTrue(kinds(ev, "NOTEON", V + 8.5, V + 8.7))
                self.assertEqual(at(snaps, V + 9.5)["owned"], 1)
                self.assertEqual(h.sound_records(d, V + 5.3), h.sound_records(d, V + 10.5))
                self.assertEqual(at(snaps, V + 5.3)["programs"], at(snaps, V + 10.5)["programs"])

    def test_do_it_is_enter_and_soft_key_3_never_makes(self):
        """B3: <Done> and Soft Key 3 mashed make nothing; ENTER on the page does."""
        for label, profile, d, ev, snaps in self.runs_of("mash"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                first = h.sound_records(d, V + 4.8)
                for t in (6.8, 7.5, 8.8, 9.5):
                    self.assertEqual(h.sound_records(d, V + t), first, t)
                    self.assertEqual(at(snaps, V + t)["programs"], at(snaps, V + 4.8)["programs"], t)
                self.assertEqual(at(snaps, V + 6.8)["mode"], 1)
                made = {i: r for i, r in h.sound_records(d, V + 14.0).items() if i not in first}
                self.assertEqual(sorted(r["name"] for r in made.values()), ["MASH01", "MASH02", "MASH03"])

    def test_settle_snaps_only_the_moved_point(self):
        """B4: frame 0 and the Source end never move; only the stepped point snaps."""
        x = signal(SR * 6)
        for label, profile, d, ev, snaps in self.runs_of("settle0"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                a, b, c, e, f = (at(snaps, V + t) for t in (6.3, 7.0, 8.0, 10.2, 11.0))
                self.assertEqual((a["current"], a["count"]), (1, 4))
                step = 6 * SR // 240
                end = a["pairs"][0][1] + step
                self.assertEqual(b["pairs"][0], [0, end])                    # stepped, not snapped yet
                want = snap_ref(x, end, LC_MIN, 6 * SR)
                self.assertEqual(c["pairs"][0], [0, want])                   # start 0 kept (D2)
                self.assertEqual(c["pairs"][1:], a["pairs"][1:])
                start = c["pairs"][3][0] + step
                self.assertEqual(e["pairs"][3], [start, 6 * SR])
                want = snap_ref(x, start, 0, 6 * SR - LC_MIN)
                self.assertEqual(f["pairs"][3], [want, 6 * SR])              # the Source end kept
                self.assertEqual(f["pairs"][:3], c["pairs"][:3])

    def test_lost_counts_only_this_take(self):
        """B5: hits dropped while the sounds were made are not the next take's."""
        for label, profile, d, ev, snaps in self.runs_of("lost2"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertGreater(at(snaps, V + 11.5)["dropped"], 0)
                rec = at(snaps, V + 13.3)
                self.assertEqual((rec["phase"], rec["dropped"]), (2, 0))
                self.assertFalse(shows(h.lcd_pixels(d)[f"{V + 13.3:.3f}"], 57, 10, "Lost:"))

    def test_equal_zones_question_goes_with_a_pad(self):
        """B6: a pad closes "Equal zones again?" and takes it off row 49."""
        for label, profile, d, ev, snaps in self.runs_of("askpad"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                px = h.lcd_pixels(d)
                self.assertEqual(at(snaps, V + 6.3)["note"], 1)
                self.assertTrue(shows(px[f"{V + 6.3:.3f}"], 49, 0, "Equal zones again?"))
                self.assertEqual(at(snaps, V + 7.0)["note"], 0)
                self.assertFalse(shows(px[f"{V + 7.0:.3f}"], 49, 0, "Equal zones again?"))
                self.assertEqual((at(snaps, V + 8.0)["mode"], at(snaps, V + 8.0)["count"]), (1, 3))

    def test_disk_name_collision(self):
        """B7: slice names are unique on the selected disk: an older BREAKS01.SND
        (other audio) stays, slice 1 is BREAKS101, and a reload on a fresh machine
        (PMONEY and stock 3.16) plays the new slices bit-exactly."""
        self.check_disk_collision("diskcol", "BREAKS01.SND", ["BREAKS101", "BREAKS02", "BREAKS03"])

    def test_digit_source_disk_name_collision(self):
        """Third review #1: a Source name ending in a digit (LOOP1) and an older
        LOOP101.SND (LOOP1 + 01): slice 1 is LOOP1101; the reload is bit-exact."""
        self.check_disk_collision("digitcol", "LOOP101.SND", ["LOOP1101", "LOOP102", "LOOP103"])

    def check_disk_collision(self, case: str, older: str, names: list[str]):
        from emu.mpc3k import run
        for label, profile, d, ev, snaps in self.runs_of(case):
            with self.subTest(set=label):
                V = self.view_time(profile)
                old, new = h.sound_records(d, V + 6.8), h.sound_records(d, V + 10.5)
                made = {i: r for i, r in new.items() if i not in old}
                self.assertEqual(sorted(r["name"] for r in made.values()), sorted(names))
                self.assertTrue(shows(h.lcd_pixels(d)[f"{V + 10.5:.3f}"], 49, 0, "03 sounds, program 02"))
                self.assertFalse(shows(h.lcd_pixels(d)[f"{V + 10.5:.3f}"], 49, 22, "(disk not checked)"))
                pcm = {r["name"]: h.pcm(d, V + 10.5, i) for i, r in made.items()}
                image = h.BUILD / "disks" / f"{label}-{label}-{case}.img"
                listing = subprocess.run(["mdir", "-b", "-i", str(image), "::"], capture_output=True,
                                         text=True, check=True).stdout
                self.assertIn(older, listing.upper())
                runs = self.RUNS / label
                for tag, prof in (("pmoney", profile), ("stock", stock_of(profile))):
                    img2 = runs / f"{case}-reload-{tag}.img"
                    img2.write_bytes(image.read_bytes())
                    subprocess.run(["mdel", "-i", str(img2), "::MUTE.PGM"], check=True)
                    if tag == "stock":
                        subprocess.run(["mcopy", "-o", "-i", str(img2), str(h.M3K316), "::STARTUP.SYS"], check=True)
                    out = runs / f"{case}-reload-{tag}"
                    ev2 = h.taps((CANCEL, "soft4")) + hit(1, 54.0) + hit(2, 54.5) + hit(3, 55.0)
                    script = h.observer(prof, runs / f"{case}-reload-{tag}.lua", ["lazychop", "snddump"])
                    run(prof.bios, [53.5, 56.0], out, floppy=img2,
                        panel=write_smf(runs / f"{case}-reload-{tag}.mid", ev2), rompath=prof.rompath,
                        extra=["-autoboot_script", str(script)], env={"LC_FROM": "52", "SNDDUMP_PCM": "53.5"})
                    rev, rsnaps = parse(out)
                    recs = h.sound_records(out, 53.5)
                    byname = {r["name"]: i for i, r in recs.items()}
                    prog = rsnaps[53.5]["programs"][0]
                    order = [next(n for n in names if n.endswith(f"{k:02d}")) for k in (1, 2, 3)]   # slice k
                    for k, name in enumerate(order, 1):
                        note = prog["map"][k - 1]
                        self.assertEqual(prog["sounds"][note - 35], byname[name], (tag, name, recs))
                        self.assertEqual(h.pcm(out, 53.5, byname[name]), pcm[name], (tag, name))
                    keyons = kinds(rev, "KEYON", 53.9, 55.5)
                    self.assertEqual([k["start"] for k in keyons][:3], [recs[byname[n]]["wave"] for n in order], tag)

    def test_midi_notes_do_not_hold_enter_off(self):
        """Third review #2: steady MIDI notes ('N', 'D') do not restart the 0.25 s
        guard: ENTER on the page makes the sounds."""
        for label, profile, d, ev, snaps in self.runs_of("cvmidi"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                self.assertTrue(kinds(ev, "NOTEON", V + 6.0, V + 7.0))
                first = h.sound_records(d, V + 5.2)
                made = {i: r for i, r in h.sound_records(d, V + 10.5).items() if i not in first}
                self.assertEqual(sorted(r["name"] for r in made.values()), ["CVMIDI01", "CVMIDI02", "CVMIDI03"])

    def test_equal_zones_question_goes_with_any_key(self):
        """Third review #3: a key the field ignores ('0') closes the question and the
        row is drawn again."""
        for label, profile, d, ev, snaps in self.runs_of("askdigit"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                px = h.lcd_pixels(d)
                self.assertTrue(shows(px[f"{V + 6.3:.3f}"], 49, 0, "Equal zones again?"))
                self.assertEqual(at(snaps, V + 7.0)["note"], 0)
                self.assertFalse(shows(px[f"{V + 7.0:.3f}"], 49, 0, "Equal zones again?"))

    def test_a_stepped_point_snaps_when_another_is_stepped(self):
        """Third review #4: slice 2's stepped start snaps when slice 3's start is
        stepped next (after a pad selected it); slice 3's when the field is left."""
        x = signal(SR * 6)
        for label, profile, d, ev, snaps in self.runs_of("settlelost"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                a, b, c, e = (at(snaps, V + t) for t in (5.3, 7.2, 8.3, 9.2))
                step = 6 * SR // 240
                s2 = a["pairs"][1][0] + step
                self.assertEqual(b["pairs"][1][0], s2)
                want2 = snap_ref(x, s2, 0, a["pairs"][1][1] - LC_MIN)
                self.assertEqual(c["pairs"][1][0], want2)                    # snapped by the next step
                s3 = a["pairs"][2][0] + step
                self.assertEqual(c["pairs"][2][0], s3)
                self.assertEqual(e["pairs"][2][0], snap_ref(x, s3, 0, a["pairs"][2][1] - LC_MIN))
                self.assertEqual([e["pairs"][0], e["pairs"][3]], [a["pairs"][0], a["pairs"][3]])

    def test_empty_disk_is_a_checked_disk(self):
        """Third review #5: an empty, readable SCSI partition is checked (find first's
        no-file result FD00h); a floppy taken out is not ("(disk not checked)")."""
        for label, profile, d, ev, snaps in self.runs_of("cvscsi"):
            with self.subTest(set=label, case="cvscsi"):
                V = 65.0
                s = at(snaps, V + 11.0)
                self.assertEqual((s["diskok"], s["diskrc"]), (1, 0xFD00))
                self.assertTrue(shows(h.lcd_pixels(d)[f"{V + 11.0:.3f}"], 49, 0, "03 sounds, program 02"))
                self.assertFalse(shows(h.lcd_pixels(d)[f"{V + 11.0:.3f}"], 49, 22, "(disk not checked)"))
        for label, profile, d, ev, snaps in self.runs_of("cvnodisk"):
            with self.subTest(set=label, case="cvnodisk"):
                V = self.view_time(profile)
                s = at(snaps, V + 14.0)
                self.assertEqual(s["diskok"], 0)
                self.assertNotEqual(s["diskrc"], 0xFD00)
                self.assertTrue(shows(h.lcd_pixels(d)[f"{V + 14.0:.3f}"], 49, 0,
                                      "03 sounds, program 02 (disk not checked)"))

    def test_wheel_bursts_step_as_before(self):
        """Third review #6: + and - coalesced in the cave (no BDE3:000E): five steps
        1 ms apart move as far as five 50 ms apart, as through BDE3:000E."""
        for label, profile, d, ev, snaps in self.runs_of("burst"):
            with self.subTest(set=label):
                V = self.view_time(profile)
                step = 4 * SR // 240
                ends = [at(snaps, V + t)["pairs"][0][1] for t in (1.8, 2.8, 4.0)]
                self.assertEqual(ends, [11_025, 11_025 + 5 * step, 11_025 + 10 * step])

    def test_pgm_save_load_round_trip(self):
        for label, profile, d, ev, snaps in self.runs_of("convert"):
            with self.subTest(set=label):
                image = h.BUILD / "disks" / f"{label}-{label}-convert.img"
                listing = subprocess.run(["mdir", "-b", "-i", str(image), "::"], capture_output=True,
                                         text=True, check=True).stdout
                names = sorted(Path(line.strip()).name.upper() for line in listing.splitlines() if line.strip())
                self.assertIn("BREAKS.PGM", names)
                for k in range(1, 5):
                    self.assertIn(f"BREAKS{k:02d}.SND", names)
                files = {}
                for name in ["BREAKS.PGM"] + [f"BREAKS{k:02d}.SND" for k in range(1, 5)]:
                    out = self.RUNS / label / f"saved-{name}"
                    out.unlink(missing_ok=True)
                    subprocess.run(["mcopy", "-i", str(image), f"::{name}", str(out)], check=True)
                    files[name] = out
                trailer = pgm_fixture.read_mute_trailer(files["BREAKS.PGM"].read_bytes())
                self.assertEqual(trailer, [{"enabled": 1, "groups": [1] * 4 + [0] * 60}])
                self.round_trip(label, profile, files, at(snaps, self.view_time(profile) + 9.5))

    def round_trip(self, label, profile, files, converted):
        """A fresh machine loads the saved program and sounds (start-up loader): the
        same program, mute state and slice pads."""
        runs = self.RUNS / label
        disk_files = [(files["BREAKS.PGM"], "MUTE.PGM")] + [(p, n) for n, p in files.items() if n.endswith(".SND")]
        ev = h.taps((CANCEL, "soft4")) + hit(1, 54.0) + hit(2, 54.5) + hit(3, 55.0) + hit(4, 55.5)
        h.run_case(profile, runs, "reload", times=[53.5, 56.5], events=ev, files=disk_files,
                   parts=("lazychop", "snddump"), env={"LC_FROM": "52", "SNDDUMP_PCM": "53.5"})
        events, snaps = parse(runs / "reload")
        prog = at(snaps, 53.5)["programs"][0]
        recs = h.sound_records(runs / "reload", 53.5)
        names = {i: r["name"] for i, r in recs.items()}
        before = converted["programs"][1]
        self.assertEqual(prog["map"], before["map"])
        got = [names.get(s) if s != 0xFF else None for s in prog["sounds"]]
        self.assertEqual(sum(1 for g in got if g), 4)
        self.assertEqual(at(snaps, 53.5)["mute"][0], {"enabled": 1, "groups": [1] * 4 + [0] * 60})
        for k in range(1, 5):
            i = next(i for i, n in names.items() if n == f"BREAKS{k:02d}")
            self.assertEqual(got[prog["map"][k - 1] - 35], f"BREAKS{k:02d}")
            data = files[f"BREAKS{k:02d}.SND"].read_bytes()
            self.assertEqual(h.pcm(runs / "reload", 53.5, i), data[2 + 0x24:])
        keyons = kinds(events, "KEYON", 53.9, 56.0)
        want = [recs[next(i for i, n in names.items() if n == f"BREAKS{k:02d}")]["wave"] for k in range(1, 5)]
        self.assertEqual([k["start"] for k in keyons][:4], want)


if __name__ == "__main__":
    unittest.main()
