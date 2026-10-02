#!/usr/bin/env python3
"""Build WAVEHW only from the hash-pinned 2026-10-01 physical ROM captures.

The unobserved ROM ranges are not build inputs. This profile is specific to
this capture; it is not a generic 'personalized Vailixi' compatibility mode.

The hook list is generated from mods/WAVE.args through the explicit
translation below (notes/wave_physical_profile.md), and every far CALL/JMP
target in the assembled cave is checked against the captured image.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import build_mod_sys as mod  # noqa: E402
from emu.snd import sine441, snd, stereo1  # noqa: E402

kit = mod.kit

APP = ROOT / 'build/hardware/2026-10-01-romapp/ROMAPP.BIN'
HIGH = ROOT / 'build/hardware/2026-10-01-romdump/BIOS.BIN'
APP_SHA = 'bc1dd8cd6d59714c1a1b0d4f5145df26a2cfec8be14ca0787f9cbef8c22be1e2'
HIGH_SHA = '2c654334e011af2943d1d08f05e3ce48ebccdf49600aab7a2f040ba016c21168'
DGROUP = (0x20000, 0x27C90)
WAVE_ARGS = ROOT / 'mods/WAVE.args'
DEFINE = 'WAVE_CAPTURE_20261001'

# --- generic WAVE.args -> capture translation (PROVEN: wave_physical_profile.md) ---
# Generic DGROUP objects from linear 0x2113F ("System Information") on sit two
# bytes lower in the capture; below 0x210F5 the images are identical.
DGROUP_SHIFT_FROM = 0x2113F
DGROUP_SHIFT = 2
# The generic bench marker overwrites the license slot 0x21110, which is the
# customer's license/serial in the capture; the capture marker replaces the
# same-width version object instead.
MARKER_SITE = 0x21110
VERSION_OBJECT = (0x210F5, b'Vailixi 3.50 (JUN/28/2008)\0')
# Other DGROUP data patches: generic linear -> capture linear (checked = -2).
DATA_MOVES = {0x25E92: 0x25E90}         # Program/Sounds menu entry "0." (20 bytes)
# DGROUP word operands inside generic code-patch OLD bytes:
# {site: {byte index: generic word}}; capture word = generic - 2.
OPERAND_SHIFTS = {
    0x39A03: {3: 0xE40A},                                         # LIST_SELECTION
    0x39E0D: {2: 0xEDB5, 9: 0xEDB5, 16: 0x35A2, 20: 0xEDB5, 24: 0x3781},  # CHOP_DO, option table, label
    0x3A49F: {1: 0xEDB5},                                         # CHOP_DO
}
# Code patches whose NEW bytes are not just EA/9A {label} plus NOP fill, reviewed
# to hold no DGROUP operand: generic NEW is valid unchanged in the capture.
VERBATIM_NEW = {0x488B6: '6a0a',        # PUSH 10: Program/Sounds menu item count
                0x4C3C4: 'b83100',      # CB10:12C4 MOV AX,49: APS size shown on the Save page, KB (was 46)
                0x4C3E3: '053100',      # CB10:12E3 ADD AX,49: same budget, with sounds
                0x4BF5D: 'c746fc3100'}  # CB10:0E5D MOV [BP-4],49: the APS size the save check enforces (was 42)

# --- far-target check -------------------------------------------------------
FAR_WINDOW = 64                         # bytes compared from each far target
AMX_SHIFT = 0xA                         # captured BIOS/AMX entries: generic - 0xA
CAPTURE_DIVERGES = (0x6B700, 0x70800)   # captured code numbering differs structurally here


def captured(path: Path, size: int, digest: str) -> bytes:
    data = path.read_bytes()
    if len(data) != size or kit.sha256(data) != digest:
        raise ValueError(f'{path}: does not match the verified physical capture')
    return data


def inputs() -> bytearray:
    # Zero-filled holes are only workspace, never represented as observed ROM.
    # image() reads DGROUP, CODE and BIOS exclusively, all covered by captures.
    img = bytearray(0x80000)
    img[0x20000:0x74000] = captured(APP, 0x54000, APP_SHA)
    img[0x78000:0x80000] = captured(HIGH, 0x8000, HIGH_SHA)
    return img


def marker_text(patches: list[tuple[int, str, str]]) -> bytes:
    """The bench marker planted by the generic marker patch in WAVE.args."""
    sites = [new for off, _old, new in patches if off == MARKER_SITE]
    if len(sites) != 1:
        raise ValueError(f'WAVE.args must carry exactly one marker patch at 0x{MARKER_SITE:05X}')
    raw = bytes.fromhex(sites[0])
    text = raw.split(b'\0', 1)[0]
    if not text.startswith(b'WAVE BENCH ') or not text.isascii() or raw[len(text):].strip(b'\0'):
        raise ValueError(f'unexpected marker patch bytes {raw!r}')
    return text


def _shift_word(data: bytearray, index: int, generic: int, site: int) -> None:
    found = struct.unpack_from('<H', data, index)[0]
    if found != generic:
        raise ValueError(f'0x{site:05X}+{index}: generic operand {found:04X}, translation expects {generic:04X}')
    if generic < DGROUP_SHIFT_FROM - 0x20000:
        raise ValueError(f'0x{site:05X}+{index}: {generic:04X} is below the shifted DGROUP range')
    struct.pack_into('<H', data, index, generic - DGROUP_SHIFT)


def translate(patches: list[tuple[int, str, str]], img: bytes) -> list[tuple[int, str, str]]:
    """Generic WAVE.args patches -> capture patches (NEW keeps {label} placeholders).

    Every DGROUP site and every DGROUP operand must be declared above; old
    bytes are verified against the capture by mod.apply().
    """
    marker = marker_text(patches)
    out: list[tuple[int, str, str]] = []
    for off, old, new in patches:
        if off == MARKER_SITE:
            site, expected = VERSION_OBJECT
            version = bytes(img[site:site + len(expected)])
            if version != expected:
                raise ValueError('captured version object mismatch')
            if len(marker) >= len(version):
                raise ValueError('marker does not fit the captured version object')
            out.append((site, version.hex(), marker.ljust(len(version), b'\0').hex()))
        elif mod.DGROUP[0] <= off < mod.DGROUP[1]:
            if off not in DATA_MOVES:
                raise ValueError(f'0x{off:05X}: generic DGROUP patch has no declared capture translation')
            moved = DATA_MOVES[off]
            if off < DGROUP_SHIFT_FROM or moved != off - DGROUP_SHIFT:
                raise ValueError(f'0x{off:05X}->0x{moved:05X}: not the proven DGROUP shift')
            out.append((moved, old, new))
        elif mod.CODE[0] <= off < mod.CODE[1]:
            data = bytearray(bytes.fromhex(old))
            for index, generic in OPERAND_SHIFTS.get(off, {}).items():
                _shift_word(data, index, generic, off)
            body = new.lower()
            if off in VERBATIM_NEW:
                if body != VERBATIM_NEW[off]:
                    raise ValueError(f'0x{off:05X}: reviewed verbatim NEW bytes changed')
            elif not re.fullmatch(r'(ea|9a)\{\w+\}(90)*', body):
                raise ValueError(f'0x{off:05X}: NEW is not a far hook to a cave label; review it '
                                 'for DGROUP operands and declare it in VERBATIM_NEW')
            out.append((off, bytes(data).hex(), new))
        else:
            raise ValueError(f'0x{off:05X}: outside DGROUP and OS code')
    for site in OPERAND_SHIFTS:
        if site not in {off for off, _, _ in patches}:
            raise ValueError(f'0x{site:05X}: declared operand translation has no WAVE.args patch')
    return out


def _explained(gen: bytes, cap: bytes, g0: int, c0: int, n: int) -> list[int]:
    """Window offsets whose difference is not a documented capture operand shift."""
    def bios_segment(seg: int) -> bool:
        return mod.BIOS[0] + 0x80000 <= seg << 4 < mod.BIOS[1] + 0x80000
    bad, i = [], 0
    while i < n:
        if gen[g0 + i] == cap[c0 + i]:
            i += 1
            continue
        for j in range(i - 3, i + 1):           # far pointer into the shifted AMX/BIOS
            go, gs = struct.unpack_from('<HH', gen, g0 + j)
            co, cs = struct.unpack_from('<HH', cap, c0 + j)
            if bios_segment(gs) and bios_segment(cs) and \
                    (gs << 4) + go - ((cs << 4) + co) == AMX_SHIFT:
                i = j + 4
                break
        else:
            for j in (i - 1, i):                 # DGROUP word operand, shifted range
                gw = struct.unpack_from('<H', gen, g0 + j)[0]
                cw = struct.unpack_from('<H', cap, c0 + j)[0]
                if gw >= DGROUP_SHIFT_FROM - 0x20000 and (gw - cw) & 0xFFFF == DGROUP_SHIFT:
                    i = j + 2
                    break
            else:
                bad.append(i)
                i += 1
    return bad


def check_far_targets(generic_img: bytes, generic: mod.Cave, capture_img: bytes,
                      capture: mod.Cave, window: int = FAR_WINDOW) -> list[dict]:
    """Fail unless every capture-cave far target is the generic routine it replaces.

    The two caves come from the same sources; their far transfers pair by
    order and must be the same kind (CALL/JMP). A shared target must hold the same bytes in both
    images over `window` bytes, except DGROUP word operands (generic >= 113F,
    capture = generic - 2) and far pointers into the BIOS/AMX (capture =
    generic - 0xA). A profile-specific target must be the documented AMX
    translation of its generic target and pass the same comparison.
    """
    gen_t, cap_t = mod.far_transfers(generic), mod.far_transfers(capture)
    if len(gen_t) != len(cap_t):
        raise ValueError(f'far transfer count differs: generic {len(gen_t)}, capture {len(cap_t)}')
    regions = (mod.CODE, mod.BIOS)
    records: dict[tuple[int, int], dict] = {}
    for g, c in zip(gen_t, cap_t):
        where = f'cave+0x{c.cave_offset:04X} ({capture.label_at(c.cave_offset)}) {c.source!r}'
        if g.opcode != c.opcode:
            raise ValueError(f'{where}: pairs with generic {g.source!r}, a different transfer kind')
        if mod.CAVE[0] <= c.linear < mod.CAVE[1] or mod.CAVE[0] <= g.linear < mod.CAVE[1]:
            if (g.segment, g.offset) != (c.segment, c.offset):
                raise ValueError(f'{where}: cave-internal far target differs between profiles')
            continue
        if g.linear == c.linear:
            kind = 'shared'
        elif mod.BIOS[0] <= g.linear < mod.BIOS[1] and g.linear - c.linear == AMX_SHIFT:
            kind = 'amx-shifted'
        else:
            raise ValueError(f'far target {c.target} at {where}: not a documented translation of '
                             f'generic {g.target} (linear 0x{g.linear:05X} -> 0x{c.linear:05X})')
        region = next((r for r in regions if r[0] <= c.linear and c.linear + window <= r[1]), None)
        if region is None or not any(r[0] <= g.linear and g.linear + window <= r[1] for r in regions):
            raise ValueError(f'far target {c.target} at {where}: linear 0x{c.linear:05X} window is '
                             'outside captured OS code and BIOS')
        if region is mod.CODE and c.linear + window > CAPTURE_DIVERGES[0] and c.linear < CAPTURE_DIVERGES[1]:
            raise ValueError(f'far target {c.target} at {where}: inside captured code that diverges '
                             f'structurally [0x{CAPTURE_DIVERGES[0]:05X},0x{CAPTURE_DIVERGES[1]:05X})')
        bad = _explained(generic_img, capture_img, g.linear, c.linear, window)
        if bad:
            raise ValueError(
                f'far target {c.target} at {where}: captured linear 0x{c.linear:05X} differs from generic '
                f'{g.target} (0x{g.linear:05X}) at +' + ', +'.join(f'0x{b:02X}' for b in bad[:8]) +
                ' beyond the documented DGROUP -2 / AMX -0xA operand shifts')
        rec = records.setdefault((c.segment, c.offset), {
            'target': c.target, 'generic': g.target, 'linear': c.linear, 'kind': kind, 'uses': 0})
        rec['uses'] += 1
    return sorted(records.values(), key=lambda r: r['linear'])


def _record(path: Path, name: str | None = None) -> dict:
    data = path.read_bytes()
    return {'name': name or path.name, 'bytes': len(data), 'sha256': kit.sha256(data)}


def build(sounds: tuple[Path, ...] = (), out: Path | None = None) -> dict:
    out = mod.OUT if out is None else out
    img = inputs()
    args = mod.read_args(WAVE_ARGS)
    if args.cave is None:
        raise ValueError('WAVE.args names no cave source')
    capture = mod.assemble_cave(args.cave, img, defines={DEFINE: '1'}, stem='wavehw', out=out)
    generic_img = mod.linear()
    generic = mod.assemble_cave(args.cave, generic_img, publish=False)
    far_targets = check_far_targets(generic_img, generic, img, capture)
    hooks = [(off, old, mod.far(new, capture.labels).lower())
             for off, old, new in translate(args.patch, img)]
    marker = marker_text(args.patch).decode()
    patches = [mod.SKIP_SYS, *hooks, capture.patch]
    mod.apply(img, patches, dgroup=DGROUP)
    payload = mod.mz(mod.image(bytes(img), dgroup=DGROUP, exact_bios_path=HIGH, stem='wavehw_stub',
                               exact_bios_sha256=HIGH_SHA, out=out))
    sys_path = out / 'WAVEHW.SYS'
    kit.write_atomic(sys_path, payload)
    files = [(sys_path, 'STARTUP.SYS')]
    for name, planes in (('SINE441', sine441()), ('STEREO1', stereo1())):
        path = out / f'{name}.SND'
        kit.write_atomic(path, snd(name, planes))
        files.append((path, path.name))
    for path in sounds:
        name = path.name.upper()
        if path.suffix.upper() != '.SND' or len(path.stem) > 8:
            raise ValueError(f'{path}: expected an 8.3 SND filename')
        if name in {n for _, n in files}:
            raise ValueError(f'{path}: duplicate disk filename')
        files.append((path, name))
    img_path = out / 'WAVEHW.img'
    disk, _ = kit.pack_fat12([(n, p.read_bytes()) for p, n in files], oem=b'MPC3KWHW',
                             volume_id=b'WVHW', label=b'WAVEHW     ')
    kit.write_atomic(img_path, disk)
    stub_deps = kit.nasm_deps(mod.STUB_ASM, defines={'DGROUP_BYTES': DGROUP[1] - DGROUP[0],
                                                     'EXACT_BIOS_PATH': kit.nasm_string(HIGH)})
    sources = [Path(__file__).resolve(), ROOT / 'mods/build_mod_sys.py', ROOT / 'mods/buildkit.py',
               WAVE_ARGS, *stub_deps, *capture.deps, ROOT / 'emu/snd.py']
    manifest = {
        'profile': 'physical-capture-2026-10-01', 'marker': marker,
        'image': _record(img_path), 'files': [_record(p, n) for p, n in files],
        'captures': [_record(APP), _record(HIGH)],
        'input_ranges': {'dgroup': [*DGROUP], 'code': [*mod.CODE], 'bios': [*mod.BIOS]},
        'unobserved_not_used': [[0, 0x20000], [0x74000, 0x78000]],
        'runtime_guard': 'exact equality of all 32768 high-ROM bytes before copying RAM OS',
        'patches': [{'linear': off, 'old': old, 'new': new} for off, old, new in patches[:-1]],
        'cave': {'linear': mod.CAVE[0], 'bytes': len(capture.code), 'segment': mod.CAVE_SEG},
        'far_targets': {'window': FAR_WINDOW, 'transfers': sum(r['uses'] for r in far_targets),
                        'targets': [{**r, 'linear': f"0x{r['linear']:05X}"} for r in far_targets]},
        'sources': {kit.relpath(p): kit.sha256(p.read_bytes())
                    for p in dict.fromkeys(p.resolve() for p in sources)},
    }
    kit.write_atomic(out / 'WAVEHW.json', (json.dumps(manifest, indent=2) + '\n').encode())
    # A build changes the artifact identity; never leave a previous release's
    # validation beside a new payload/image as if those checks covered it.
    kit.write_atomic(out / 'WAVEHW-validation.json', (json.dumps({
        'marker': manifest['marker'], 'release_status': 'under_test',
        'payload_sha256': manifest['files'][0]['sha256'],
        'image_sha256': manifest['image']['sha256'],
        'note': 'This build needs checks against these exact artifact hashes.',
    }, indent=2) + '\n').encode())
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sound', type=Path, action='append', default=[],
                        help='include an existing SND file in the bench image')
    parser.add_argument('--out', type=Path, default=None, help='output directory (default build/mods)')
    args = parser.parse_args()
    print(json.dumps(build(tuple(args.sound), args.out), indent=2))
