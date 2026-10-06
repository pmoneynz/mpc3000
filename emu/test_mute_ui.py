"""Mute-group UI: real panel input, observed settings, and LCD pixels.

Run: python3 -m unittest emu.test_mute_ui -v
Payloads come from emu.harness, built from the current sources: every case on
capture and on the 316 profile (WAVE316.SYS on OS 3.16; one BIOS set per load
segment by default, all four in release mode), the generic case also on
generic; their SHA-256 is logged.  Times are Vailixi times (Soft Key 4 cancels
the SCSI search at 20 s) moved by delay(profile): 13 s on 3.16, which boots
later.  The mute page is the same cave code on every profile; only the stock
default pad -> note map it displays differs on 3.16 (pad_note).
"""
import hashlib
import json
from pathlib import Path
import unittest

from emu import harness as h
from emu import test_mpc3k as base
from emu import wave_ref
from emu.panel import dial, key_tap, pad_hit, panel_pad
from emu.snd import disk
from emu.test_wave_zones import symbols, taps

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'build/emu/mute-ui-tests'
OPEN = taps((20,'soft4'), (23,'program_sounds'), (25,'0'))   # cancel SCSI, Program/Sounds -> 0
PARTS = ('repeat_watch', 'mute_ui')

# Note field of a pad on a fresh boot.  Vailixi's default program maps pad n
# to note n + 34.  3.16 has its own default map, not linear: DGROUP 087F
# (image 0x6123F) = 37, 36, 42, ..., 98 for pads 1..64, copied to DS:8064 by
# image 0x493D and into each program record's pad map (+73Eh) by program init
# (207C:0393); the page reads it back through 301D:000A (T_D9F2_000C), whose
# global-map flag DS:8063 start-up clears (image 0x4ABF).  Stock 3.16's Select
# Program shows pad 1 the same way ("Assign Note:37/A01",
# emu/test_port316_boot.py).  The pads these suites draw:
NOTES_316 = {1: 37, 64: 98}


def pad_note(profile: h.Profile, pad: int) -> int:
    return NOTES_316[pad] if profile.is316 else pad + 34


def delay(profile: h.Profile) -> float:
    """Seconds this profile's panel is ready later than Vailixi's (0 or 13)."""
    return profile.timeline.cancel - h.TIMELINE.cancel


def later(events: list, dt: float) -> list:
    return [(t + dt, data) for t, data in events]


def at(profile: h.Profile):
    """A Vailixi probe time -> this profile's probe time (as the observers log it)."""
    dt = delay(profile)
    return lambda t: round(t + dt, 3)


def each_run(suite: h.EmuSuite, case: str):
    """(label, profile, run directory, screens, time map) per profile that ran `case`."""
    for label, d, screens in suite.each(case):
        profile = suite.profiles[label]
        yield label, profile, d, screens, at(profile)


def observer(directory: Path, generic: bool = False, profile: h.Profile | None = None) -> Path:
    """Read-only mute observer.  With `profile`, use the payload under test
    (emu.harness) and also log the repeat counts; otherwise the release map."""
    if profile is not None:
        return h.observer(profile, directory / f'observe-{profile.name}.lua',
                          ['repeat_watch', 'mute_ui'])
    offsets = symbols(ROOT / ('build/mods/wave.cave.map' if generic else 'build/mods/wavehw.cave.map'))
    names = ('mu_program', 'mu_pad', 'mu_focus', 'mute_states')
    prefix = ('local MUTE_OFFSETS={' + ','.join(f'{n}={offsets[n]}' for n in names) + '}\n'
              + f'local MUTE_PROGRAM_OFFSET={0xE60E if generic else 0xE60C}\n'
              + f'local MUTE_PROBE_PATH="{ROOT / "emu/probe.lua"}"\n')
    result = directory / ('observe-generic.lua' if generic else 'observe.lua')
    result.write_text(prefix + (ROOT / 'emu/lua/mute_ui.lua').read_text())
    return result


def states(directory: Path, at: float) -> list[dict]:
    raw = (directory / f'mute_state_{at:.3f}.bin').read_bytes()
    return [{'enabled': raw[p * 33],
             'groups': [(raw[p * 33 + 1 + i // 2] >> (4 * (i % 2))) & 15 for i in range(64)]}
            for p in range(24)]


def rows(directory: Path) -> dict[float, dict]:
    return {r['time']: r for line in (directory / 'mute_ui.jsonl').read_text().splitlines()
            if (r := json.loads(line))}


def pixels(directory: Path) -> dict[float, list[str]]:
    blocks = (directory / 'lcd_pixels.txt').read_text().split('@ ')[1:]
    return {float(b.split()[0]): b.splitlines()[1:65] for b in blocks}


def screen(program: int, pad: int, groups: list[int], enabled: bool, focus: int,
           prompt: bool = False, note: int | None = None) -> list[str]:
    """The page as drawn; `note` is the pad's Note field (default: Vailixi's pad + 34)."""
    lit = [[False] * 240 for _ in range(64)]
    if not prompt:
        wave_ref._text(lit, 0, 0, 'Mute Groups:')
        wave_ref._text(lit, 0, 13, f'PROGRAM_{program:02d}')
    wave_ref._text(lit, 8, 0, f'Program:{program:02d}    Enabled:{"ON " if enabled else "OFF"}')
    wave_ref._text(lit, 8, 30, f'Note:{pad + 34 if note is None else note:02d}')
    group = groups[pad - 1]
    group_text = str(group).ljust(3) if group else 'OFF'
    wave_ref._text(lit, 16, 0, f'Pad:{pad:02d} ({chr(65 + (pad - 1) // 16)}{(pad - 1) % 16 + 1:02d})  Group:{group_text}')
    for bank in range(4):
        chars = ''.join(str(g) if g else '-' for g in groups[bank * 16:bank * 16 + 16])
        spaced = ' '.join(chars[i:i+4] for i in range(0,16,4))
        wave_ref._text(lit, 24 + bank * 8, 0, f'{chr(65 + bank)} {bank*16+1:02d}-{bank*16+16:02d}:{spaced}')
    if prompt:  # Apply All confirmation replaces only the title and soft-key rows
        wave_ref._text(lit, 0, 0, f'Program {program:02d}: set all 64 pads to group {group_text}')
        wave_ref._text(lit, 57, 20, '<Do it>     <Cancel>')
    else:
        wave_ref._text(lit, 57, 0, '<Apply All>')
        wave_ref._text(lit, 57, 34, '<Exit>')
    n = pad - 1
    wave_ref._invert(lit, (8 + n % 16 + (n % 16) // 4) * 6, 6, 24 + n // 16 * 8, 7)
    wave_ref._invert(lit, (8,22,4,20)[focus] * 6, (12,18,12,18)[focus], (8,8,16,16)[focus], 7)
    return [''.join('#' if value else '.' for value in line) for line in lit]


class MuteUI(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({'generic'})
    PROFILE_NAMES = h.ALL_PROFILES

    @classmethod
    def cases(cls, profile, runs):
        basic = taps((27,'+'), (28,'right'), (29,'right'), (30,'1'),
                     (31,'left'), (32,'6'), (32.3,'4'), (33,'right'), (34,'4'))
        definitions = {
            'individual': (basic, [26,30.5,35]),
            'all': (basic + taps((36,'soft1'),(38,'soft3')), [35,37,39]),
            'programs': (basic + taps((35,'left'),(36,'left'),(37,'left'),(38,'+'),
                         (39,'right'),(40,'+'),(41,'right'),(42,'2'),(42.3,'0'),
                         (43,'right'),(44,'3'),(46,'left'),(47,'left'),(48,'left'),(49,'-')),
                         [38.5,45,50]),
            'bounds': (taps((27,'left')) + dial(40,28,gap=.025) + dial(-40,31,gap=.025)
                       + taps((34,'right'),(35,'right')) + dial(100,36,gap=.025)
                       + taps((40,'right')) + dial(7,41,gap=.025) + dial(-10,43,gap=.025),
                       [30,33,39,42,45]),
            'banks': (taps((27,'right')) + pad_hit(panel_pad(1),28)
                       + taps((29,'pad_bank')) + pad_hit(panel_pad(16),30)
                       + taps((31,'pad_bank')) + pad_hit(panel_pad(1),32)
                       + taps((33,'pad_bank')) + pad_hit(panel_pad(16),34),
                       [28.5,30.5,32.5,34.5]),
            'generic': (basic + taps((36,'soft4')), [35,37]),
            # Wheel bursts 1 ms apart (coalesced by the stock reader): program,
            # enable, pad and group must apply the whole repeat count, clamped.
            'burst': (taps((27,'left')) + h.burst(9,28) + h.burst(-5,30)
                      + taps((32,'right')) + h.burst(3,33)
                      + taps((35,'right')) + h.burst(9,36) + h.burst(9,38)
                      + taps((40,'right')) + h.burst(9,41) + h.burst(-3,43),
                      [27.5,29,31,34,37,39,42,44]),
        }
        t, dt = at(profile), delay(profile)
        return {name: h.Case(events=later(OPEN + events, dt), times=[t(x) for x in times], parts=PARTS)
                for name, (events, times) in definitions.items()}

    def test_defaults_and_individual_pad_1_and_64(self):
        for label, _, d, _, t in each_run(self, 'individual'):
            with self.subTest(profile=label):
                initial = states(d,t(26))
                self.assertEqual(initial,[{'enabled':0,'groups':[0]*64} for _ in range(24)])
                result = states(d,t(35))[0]
                self.assertEqual(result,{'enabled':1,'groups':[1]+[0]*62+[4]})
                self.assertEqual(rows(d)[t(35)]['pad'],63)

    def test_apply_all_asks_then_soft_key_3_applies_and_retains_enable(self):
        for label, profile, d, _, t in each_run(self, 'all'):
            with self.subTest(profile=label):
                before = states(d,t(35))
                self.assertEqual(states(d,t(37)),before)  # Soft Key 1 only asks
                self.assertEqual(states(d,t(39))[0],{'enabled':1,'groups':[4]*64})
                self.assertEqual(states(d,t(39))[1:],before[1:])
                lcd = pixels(d)
                note = pad_note(profile,64)
                self.assertEqual(lcd[t(37)],screen(1,64,[1]+[0]*62+[4],True,3,prompt=True,note=note))
                self.assertEqual(lcd[t(39)],screen(1,64,[4]*64,True,3,note=note))

    def test_program_settings_are_independent(self):
        for label, _, d, _, t in each_run(self, 'programs'):
            with self.subTest(profile=label):
                middle = states(d,t(45))
                self.assertEqual(middle[0],{'enabled':1,'groups':[1]+[0]*62+[4]})
                self.assertEqual(middle[1],{'enabled':1,'groups':[0]*19+[3]+[0]*44})
                self.assertEqual(states(d,t(50)),middle)
                self.assertEqual(rows(d)[t(50)]['active_program'],0)

    def test_fields_clamp_and_fast_wheel_keeps_all_steps(self):
        for label, _, d, _, t in each_run(self, 'bounds'):
            with self.subTest(profile=label):
                r=rows(d)
                self.assertEqual([r[t(30)]['program'],r[t(33)]['program']],[23,0])
                self.assertEqual(r[t(39)]['pad'],63)
                self.assertEqual(states(d,t(42))[0]['groups'][63],4)
                self.assertEqual(states(d,t(45))[0]['groups'][63],0)

    def test_physical_pads_select_across_all_four_banks(self):
        for label, _, d, _, t in each_run(self, 'banks'):
            with self.subTest(profile=label):
                r=rows(d)
                self.assertEqual([r[t(x)]['pad'] for x in (28.5,30.5,32.5,34.5)],[0,31,32,63])

    def test_generic_profile_and_exit_to_menu(self):
        for label, _, d, screens, t in each_run(self, 'generic'):
            with self.subTest(profile=label):
                self.assertEqual(states(d,t(35))[0],{'enabled':1,'groups':[1]+[0]*62+[4]})
                self.assertIn('0.Mute.groups',''.join(screens[-1]['rows']).replace(' ','.'))

    def test_coalesced_wheel_bursts_apply_every_step(self):
        for label, _, d, _, t in each_run(self, 'burst'):
            with self.subTest(profile=label):
                r=rows(d)
                self.assertEqual([(r[t(x)]['program'],r[t(x)]['focus']) for x in (27.5,29,31)],
                                 [(0,0),(9,0),(4,0)])
                self.assertEqual(r[t(31)]['active_program'],4)
                self.assertEqual(states(d,t(34))[4]['enabled'],1)
                self.assertEqual([r[t(x)]['pad'] for x in (37,39)],[9,18])
                groups=[states(d,t(x))[4]['groups'][18] for x in (39,42,44)]
                self.assertEqual(groups,[0,4,1])
                self.assertEqual(states(d,t(44))[:4],states(d,t(27.5))[:4])
                # Coalescing really happened for every field: counts above one and
                # fewer redraws than wheel events.
                for x,events in ((28,9),(30,5),(33,3),(36,9),(38,9),(41,9),(43,3)):
                    counts=h.repeats(d,'mu_repeat',t(x),t(x)+1)
                    self.assertEqual(sum(counts),events,(x,counts))
                    self.assertGreater(max(counts),1,(x,counts))
                    self.assertLess(h.blits(d,t(x),t(x)+1),events,x)

    def test_complete_lcd_layout_and_focus(self):
        for label, profile, d, _, t in each_run(self, 'individual'):
            with self.subTest(profile=label):
                lcd = pixels(d)
                self.assertEqual(lcd[t(26)],screen(1,1,[0]*64,False,1,note=pad_note(profile,1)))
                self.assertEqual(lcd[t(35)],screen(1,64,[1]+[0]*62+[4],True,3,note=pad_note(profile,64)))


if __name__ == '__main__':
    unittest.main()
