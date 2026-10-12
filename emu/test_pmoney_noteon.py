"""PMONEY note-on fixes (notes/performance.md section 12).

    python3 -m unittest emu.test_pmoney_noteon -v

1. S1a on OS 3.16: the 17 divide calls of 3.16's note-on layer (image
   0x21274, Vailixi CFC6:039E) reach the cave's s1a_idiv/s1a_udiv, whose
   bytes are the verified S1A routines except for their fallback far jumps,
   which go to 3.16's linked runtime copy; that copy is byte-identical to
   the BIOS runtime tests/test_s1a_divide.py executes.
2. mute_pad_of_note gives the stock answer: in one PMONEY run, every MIDI
   note's stock lookup (T_D9F2_003D called at 3.16 image 0x3086B) and the
   cave's lookup in mute_note_on_wrapper return the same pad, in both
   table modes.  The only direct writer of the mode byte DS:8063 zeroes it
   at start-up (image 0x04ABF), so for the second pass
   emu/lua/pad_mode_inject.lua sets it and fills the 64-byte table at 8064
   (reversed notes, a duplicate, a missing note, a byte >= 80h).  Both
   lookups read that same memory; this tests their equivalence, not when
   the OS uses the table.
"""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from emu import harness as h
from emu import pgm as pgm_fixture
from emu.mpc3k import BUILD, M3K316, run
from emu.panel import key_tap, write_smf
from emu.snd import sine, snd
from emu.test_mute_voice import load_actions
from mods import route_c as rc
from tools.linear_rom import load_vailixi_linear

RUNS = BUILD / "emu" / "pmoney-noteon-tests"
LAYER = 0x21274                 # 3.16 image offset of the note-on layer (Vailixi CFC6:039E)
LAYER_LEN = 1927
RUNTIME = (0x2183, 0x2231)      # 3.16 image: linked copy of F800:20F7..21A5
BIOS_RUNTIME = (0x7A0F7, 0x7A1A5)
STOCK_LOOKUP_RETURN = 0x30870   # after CALLF 301D:003B in the MIDI note handler (image 0x3086B)
MODE = 0x8063                   # 3.16 DGROUP: pad slot notes from the 8064 table while non-zero
NOTES = [0x10, 0x22, *range(0x23, 0x63), 0x63, 0x7F]
FIRST, SECOND, GAP = 68.0, 80.0, 0.1


@unittest.skipIf(h.missing_tools(), f"missing: {h.missing_tools()}")
class PmoneyNoteOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.p = h.payload("316", "vailixi")
        cls.syms = cls.p.symbols()

    def test_runtime_copy_is_the_bios_runtime(self) -> None:
        image = bytes(rc.MZ.parse(M3K316.read_bytes()).image)
        self.assertEqual(image[RUNTIME[0]:RUNTIME[1]], load_vailixi_linear()[BIOS_RUNTIME[0]:BIOS_RUNTIME[1]])

    def test_all_seventeen_divides_reach_the_cave(self) -> None:
        image = self.p.relocated_image()
        cave_seg = self.p.cave_segment
        entries = {self.syms["s1a_idiv"], self.syms["s1a_udiv"]}
        body = image[LAYER:LAYER + LAYER_LEN]
        sites = [i for i in range(len(body) - 4) if body[i] == 0x9A
                 and struct.unpack_from("<H", body, i + 3)[0] == cave_seg
                 and struct.unpack_from("<H", body, i + 1)[0] in entries]
        self.assertEqual(len(sites), 17)
        runtime_seg = (self.p.load_segment + 0x0009) & 0xFFFF
        for off in (0x20F6, 0x20FD):
            self.assertNotIn(b"\x9a" + struct.pack("<HH", off, runtime_seg), body)

    def test_cave_divide_bytes_are_the_s1a_routines(self) -> None:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mods"))
        import build_mod_sys as mod
        s1a = mod.assemble_cave(Path(__file__).resolve().parents[1] / "mods" / "s1a.asm",
                                load_vailixi_linear(), publish=False).code
        cave = self.p.cave_home_image()
        start = self.syms["s1a_idiv"]
        mine = bytearray(cave[start:start + len(s1a)])
        ref = bytearray(s1a)
        runtime_seg = (self.p.load_segment + 0x0009) & 0xFFFF
        for label, off in (("s1a_idiv", 0x20F6), ("s1a_udiv", 0x20FD)):
            jmp = mine.index(b"\xea", self.syms[label] - start + 0x20)
            self.assertEqual(bytes(mine[jmp:jmp + 5]), b"\xea" + struct.pack("<HH", off, runtime_seg))
            mine[jmp + 1:jmp + 5] = ref[jmp + 1:jmp + 5]            # compare all else byte for byte
        self.assertEqual(bytes(mine), bytes(ref))

    def test_cave_lookup_agrees_with_stock_in_both_modes(self) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        tone = RUNS / "TEST.SND"
        tone.write_bytes(snd("TEST", [sine(2205)]))
        program = RUNS / "MUTE.PGM"
        program.write_bytes(pgm_fixture.for_sound(tone.read_bytes(), pads=range(64), enabled=True,
                                                  groups=[1 + pad % 4 for pad in range(64)]))
        image = h.wave_disk(self.p, "pmoney-noteon", [(program, "MUTE.PGM"), (tone, "TEST.SND")])
        midi = []
        for start in (FIRST, SECOND):
            for i, note in enumerate(NOTES):
                t = start + i * GAP
                midi += [(t, bytes((0x90, note, 100))), (t + 0.04, bytes((0x80, note, 0)))]
        panel = load_actions(self.p)
        table = bytearray(0x62 - i for i in range(64))          # pad i -> note 62h - i
        table[40] = table[10]                                    # duplicate: first slot wins
        table[5] = 0x90                                          # >= 80h: never equal after CBW
        table[63] = 0x7E                                         # note 23h maps to no slot
        cave_at = self.p.cave_phys + self.syms["mute_note_on_wrapper.pad_known"]
        dg = self.p.dgroup_segment
        trace = RUNS / "lookup.trace"
        spec = (f"{cave_at:X}=CAVE,pb6:4,a{dg:04X}:{MODE:04X}:1;"
                f"{self.p.image_phys(STOCK_LOOKUP_RETURN):X}=STOCK,s0:2,a{dg:04X}:{MODE:04X}:1")
        end = SECOND + len(NOTES) * GAP + 1.0
        run(self.p.bios, [end], RUNS / "run", floppy=image, rompath=self.p.rompath,
            panel=write_smf(RUNS / "panel.mid", panel),
            extra=["-midiin1", str(write_smf(RUNS / "midi.mid", midi)),
                   "-autoboot_script", str(Path(__file__).resolve().parent / "lua" / "pad_mode_inject.lua")],
            env={"NEC_TRACE_FILE": str(trace), "NEC_TRACE_FROM": str(FIRST - 1), "NEC_TRACE_AT": spec,
                 "PADMODE_AT": str(SECOND - 1.0), "PADMODE_PHYS": f"{0x300000 + self.p.dgroup_segment * 16 + MODE:X}",
                 "PADMODE_TABLE": table.hex()})
        stock, compared, modes, seen, hits = None, 0, set(), {}, {}
        for line in trace.read_text().splitlines():
            f = line.split()
            if f[0] != "H":
                continue
            ax = int(f[4], 16)
            items = dict(x.split("=", 1) for x in f[16:])
            mode = int(next(v for k, v in items.items() if k.startswith("a")), 16)
            if f[2] == "STOCK":
                stock = (int(items["s0"][:2], 16), ax, mode)
            else:
                note = int(next(v for k, v in items.items() if k.startswith("B6"))[4:6], 16)
                self.assertIsNotNone(stock, "cave lookup without a preceding stock lookup")
                self.assertEqual((note, mode), stock[0::2])
                want = stock[1] if stock[1] < 64 else None
                got = ax if ax < 64 else None
                self.assertEqual(got, want, f"note {note:02X} mode {mode}")
                compared += 1
                modes.add(mode != 0)
                seen.setdefault(mode != 0, []).append(note)
                if got is not None:
                    hits.setdefault(mode != 0, set()).add(got)
                stock = None
        self.assertGreaterEqual(compared, 2 * 64)
        self.assertEqual(modes, {False, True}, "both pad table modes")
        self.assertTrue(any(n == 0x23 for n in seen[True]) and 10 in hits[True], "missing note and duplicate seen")


if __name__ == "__main__":
    unittest.main()
