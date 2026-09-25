"""Panel-link byte streams for the MAME `panel` port (media `midiin3`).

Frame grammar is the V53 parser at D547:0105 (linear 0x55575); evidence in
MPC3000/notes/panel_link.md:
  90 kk vv   kk < 0x10: raw pad kk (pad = kk ^ 0x0C), velocity vv (0 = release)
             kk >= 0x40: key kk, vv != 0 press, 0 release
  A0 kk vv   pad pressure (raw pad kk)
  B0 xx vv   note variation slider value vv; xx is ignored
  E0 dd dd   data entry step: dd 00 = '+', 7F = '-'
MAME's midiin starts a file 10 s after power-on; `at` is emulated time.
"""

from __future__ import annotations

from pathlib import Path

MIDIIN_START = 10.0

# Button -> key code. Identity from emulated screen effects (emu/key_sweep.py)
# except "rec"/"overdub" (panel order) and "after" (elimination).
KEYS = {
    "pad_bank": 0x5C, "full_level": 0x40, "16_levels": 0x41, "assign": 0x79, "after": 0x42,
    "0": 0x5E, "1": 0x54, "2": 0x55, "3": 0x56, "4": 0x4B,
    "5": 0x4C, "6": 0x4D, "7": 0x43, "8": 0x44, "9": 0x45,
    ".": 0x5D, "enter": 0x5F, "+": 0x65, "-": 0x6E,
    "up": 0x62, "down": 0x6B, "left": 0x6A, "right": 0x6C,
    "soft1": 0x46, "soft2": 0x47, "soft3": 0x48, "soft4": 0x49,
    "disk": 0x4E, "program_sounds": 0x51, "mixer_effects": 0x50, "midi": 0x5A,
    "song": 0x52, "other": 0x5B, "edit": 0x57, "step_edit": 0x58, "edit_loop": 0x59,
    "tempo_sync": 0x4F, "transpose": 0x63, "2nd_seq": 0x64, "auto_punch": 0x61,
    "count_in": 0x69, "wait_for_key": 0x60,
    "erase": 0x66, "timing_correct": 0x67, "tap_tempo": 0x68, "main_screen": 0x6D, "help": 0x4A,
    "rewind_bar": 0x6F, "rewind_step": 0x70, "locate": 0x71, "forward_step": 0x72, "forward_bar": 0x73,
    "rec": 0x74, "overdub": 0x75, "stop": 0x76, "play": 0x77, "play_start": 0x78,
}


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def write_smf(path: Path, events: list[tuple[float, bytes]]) -> Path:
    """Format-0 SMF, 1000 ticks per quarter at 1 s per quarter (1 tick = 1 ms)."""
    track = bytearray(b"\x00\xff\x51\x03\x0f\x42\x40")
    last = 0
    for at, msg in sorted(events, key=lambda e: e[0]):
        tick = max(0, round((at - MIDIIN_START) * 1000))
        track += _vlq(tick - last) + msg
        last = tick
    track += b"\x00\xff\x2f\x00"
    path.write_bytes(b"MThd" + (6).to_bytes(4, "big") + b"\x00\x00\x00\x01\x03\xe8"
                     + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track))
    return path


def key_tap(code: int | str, at: float, hold: float = 0.1) -> list[tuple[float, bytes]]:
    code = KEYS[code] if isinstance(code, str) else code
    return [(at, bytes([0x90, code, 0x7F])), (at + hold, bytes([0x90, code, 0x00]))]


def pad_hit(pad: int, at: float, velocity: int = 0x7F, hold: float = 0.1) -> list[tuple[float, bytes]]:
    """`pad` is the raw link index; panel pad n (1..16) is raw (n - 1) ^ 0x0C."""
    return [(at, bytes([0x90, pad, velocity])), (at + hold, bytes([0x90, pad, 0x00]))]


def panel_pad(n: int) -> int:
    return (n - 1) ^ 0x0C


def dial(steps: int, at: float, gap: float = 0.05) -> list[tuple[float, bytes]]:
    d = 0x00 if steps > 0 else 0x7F
    return [(at + i * gap, bytes([0xE0, d, d])) for i in range(abs(steps))]
