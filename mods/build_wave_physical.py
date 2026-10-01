#!/usr/bin/env python3
"""Build WAVEHW only from the hash-pinned 2026-10-01 physical ROM captures.

The unobserved ROM ranges are not build inputs. This profile is specific to
this capture; it is not a generic 'personalized Vailixi' compatibility mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import build_mod_sys as mod
from emu.snd import disk, sine441, snd, stereo1

APP = ROOT / 'build/hardware/2026-10-01-romapp/ROMAPP.BIN'
HIGH = ROOT / 'build/hardware/2026-10-01-romdump/BIOS.BIN'
APP_SHA = 'bc1dd8cd6d59714c1a1b0d4f5145df26a2cfec8be14ca0787f9cbef8c22be1e2'
HIGH_SHA = '2c654334e011af2943d1d08f05e3ce48ebccdf49600aab7a2f040ba016c21168'
DGROUP = (0x20000, 0x27C90)


def captured(path: Path, size: int, digest: str) -> bytes:
    data = path.read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'{path}: does not match the verified physical capture')
    return data


def inputs() -> bytearray:
    # Zero-filled holes are only workspace, never represented as observed ROM.
    # image() reads DGROUP, CODE and BIOS exclusively, all covered by captures.
    img = bytearray(0x80000)
    img[0x20000:0x74000] = captured(APP, 0x54000, APP_SHA)
    img[0x78000:0x80000] = captured(HIGH, 0x8000, HIGH_SHA)
    return img


def build(sounds: tuple[Path, ...] = ()) -> dict:
    img = inputs()
    patch, labels = mod.cave(ROOT / 'mods/wave.asm', img,
                             defines={'WAVE_CAPTURE_20261001': '1'}, stem='wavehw')
    # Preserve the captured license/serial text. Identify this RAM-only boot
    # by replacing the same-width version object, with its terminating NUL.
    version = bytes(img[0x210F5:0x21110])
    expected = b'Vailixi 3.50 (JUN/28/2008)\0'
    if version != expected:
        raise ValueError('captured version object mismatch')
    marker = b'WAVE BENCH 06'.ljust(len(version), b'\0')
    patches = [mod.SKIP_SYS, (0x210F5, version.hex(), marker.hex()),
               (0x30A22, '807eff487531', mod.far('ea{help_gate}90', labels)),
               (0x399A2, '558bec81ecc002', mod.far('ea{zones_page_entry}9090', labels)),
               (0x39A03, '8bf8a008e48846fe',
                mod.far('ea{zones_list_ready}909090', labels)),
               (0x39E7B, '83ffff7503e94b03', mod.far('ea{zones_sound_changed}909090', labels)),
               (0x39E0D, '803eb3ed0a7c05c606b3ed006a101e68a0351e68b3ed1e687f379ac60154b383c40e',
                mod.far('ea{chop_do_field}' + '90' * 29, labels)),
               (0x3A49F, 'a0b3ed988bd883fb097603e9880a',
                mod.far('ea{chop_do_dispatch}' + '90' * 9, labels)),
               (0x51719, '558bec83ec06', mod.far('ea{chop_sound_delete}90', labels)),
               (0x3A1FA, '3d75007503e99102e9300d', mod.far('ea{page_key}909090909090', labels)),
               (0x502FD, '2d1e0083da00', mod.far('ea{audition_duration}90', labels)),
               (0x504F7, '8946a8837ea800', mod.far('ea{audition_ticks}9090', labels)),
               (0x25E90, (b' ' * 20).hex(), b'0.Mute groups'.ljust(20).hex()),
               (0x488B6, '6a09', '6a0a'),
               (0x488D4, '98488bd883fb08', mod.far('ea{mute_menu_dispatch}9090', labels)),
               (0x4FBD3, '9a0700c6cf', mod.far('9a{mute_note_on_wrapper}', labels)),
               (0x507AC, '9a020037cf', mod.far('9a{mute_voice_alloc_wrapper}', labels)),
               (0x4F81D, '558bec83ec04', mod.far('ea{mute_program_init_hook}90', labels)),
               (0x4A262, 'b9bf031e8ed8f3a51f', mod.far('ea{mute_program_copy_hook}90909090', labels)),
               (0x42502, '9a8600e6ce', mod.far('9a{mute_pgm_load_close}', labels)),
               (0x428BC, '9a8600e6ce', mod.far('9a{mute_aps_load_close}', labels)),
               (0x6894E, '9a8600e6ce', mod.far('9a{mute_pgm_save_close}', labels)),
               (0x68DAE, '9a8600e6ce', mod.far('9a{mute_aps_save_close}', labels)),
               patch]
    mod.apply(img, patches)
    payload = mod.mz(mod.image(bytes(img), dgroup=DGROUP, exact_bios_path=HIGH, stem='wavehw_stub'))
    sys_path = mod.OUT / 'WAVEHW.SYS'
    sys_path.write_bytes(payload)
    files = [(sys_path, 'STARTUP.SYS')]
    for name, planes in (('SINE441', sine441()), ('STEREO1', stereo1())):
        path = mod.OUT / f'{name}.SND'
        path.write_bytes(snd(name, planes))
        files.append((path, path.name))
    for path in sounds:
        name = path.name.upper()
        if path.suffix.upper() != '.SND' or len(path.stem) > 8:
            raise ValueError(f'{path}: expected an 8.3 SND filename')
        if name in {n for _, n in files}:
            raise ValueError(f'{path}: duplicate disk filename')
        files.append((path, name))
    img_path = mod.OUT / 'WAVEHW.img'
    img_path.write_bytes(disk('wavehw-bench', files).read_bytes())
    def record(path, name=None):
        data = path.read_bytes()
        return {'name': name or path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    manifest = {
        'profile': 'physical-capture-2026-10-01', 'marker': 'WAVE BENCH 06',
        'image': record(img_path), 'files': [record(p, n) for p, n in files],
        'captures': [record(APP), record(HIGH)],
        'input_ranges': {'dgroup': [*DGROUP], 'code': [*mod.CODE], 'bios': [*mod.BIOS]},
        'unobserved_not_used': [[0, 0x20000], [0x74000, 0x78000]],
        'runtime_guard': 'exact equality of all 32768 high-ROM bytes before copying RAM OS',
        'patches': [{'linear': off, 'old': old, 'new': new} for off, old, new in patches[:-1]],
        'cave': {'linear': mod.CAVE[0], 'bytes': len(bytes.fromhex(patch[2])), 'segment': mod.CAVE_SEG},
        'sources': {str(p.relative_to(ROOT)): record(p)['sha256'] for p in (
            Path(__file__).resolve(), ROOT / 'mods/build_mod_sys.py', ROOT / 'mods/mod_stub.asm',
            ROOT / 'mods/wave.asm', ROOT / 'mods/wave_playback.inc', ROOT / 'mods/wave_numeric.inc',
            ROOT / 'mods/wave_zones.inc', ROOT / 'mods/wave_chop.inc',
            ROOT / 'mods/mute_storage.inc', ROOT / 'mods/mute_voice.inc', ROOT / 'mods/mute_ui.inc',
            ROOT / 'mods/wave_font.inc', ROOT / 'emu/snd.py')},
    }
    (mod.OUT / 'WAVEHW.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # A build changes the artifact identity; never leave a previous release's
    # validation beside a new payload/image as if those checks covered it.
    (mod.OUT / 'WAVEHW-validation.json').write_text(json.dumps({
        'marker': manifest['marker'], 'release_status': 'under_test',
        'payload_sha256': manifest['files'][0]['sha256'],
        'image_sha256': manifest['image']['sha256'],
        'note': 'This build needs checks against these exact artifact hashes.',
    }, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sound', type=Path, action='append', default=[],
                        help='include an existing SND file in the bench image')
    args = parser.parse_args()
    print(json.dumps(build(tuple(args.sound)), indent=2))
