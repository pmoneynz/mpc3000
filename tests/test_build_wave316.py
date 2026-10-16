"""OS 3.16 Route C builder (mods/build_wave316.py): the pinned build and one
mutation per verification rule, applied to in-memory inputs.  No MAME.

The build writes to a temporary directory under build/, never build/mods.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mods import build_mod_sys as mod  # noqa: E402
from mods import build_wave316 as b  # noqa: E402
from mods import buildkit as kit  # noqa: E402
from mods import route_c as rc  # noqa: E402

HAVE_TOOLS = shutil.which("nasm") is not None and shutil.which("ndisasm") is not None
SYS_SHA256 = "227bad563ee2b9db523c60d384e5f0571c12d60ed10931f64edb0e44fa03af99"
IMG_SHA256 = "c29e0119327f5dc546a80def41b213076a67cb437c8a0c9a748643a7da5d4732"
CAVE_SHA256 = "03885338784553a6dfea7a5fe586c351c72e0a1356fc55150c1b3d611d8777a7"
HOOK = 0x2298F                  # chop_sound_delete hook, on T_D0C0_0B19 = 21E7:0B1F


@unittest.skipUnless(HAVE_TOOLS, "needs nasm and ndisasm")
class PinnedBuild(unittest.TestCase):
    def test_outputs_and_entry316_model(self) -> None:
        (ROOT / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            out = Path(tmp)
            m = b.build(out=out)
            self.assertEqual(kit.sha256((out / "WAVE316.SYS").read_bytes()), SYS_SHA256)
            self.assertEqual(kit.sha256((out / "WAVE316.img").read_bytes()), IMG_SHA256)
            self.assertEqual(kit.sha256((out / "wave316.cave.bin").read_bytes()), CAVE_SHA256)
        sim = m["simulation"]
        self.assertEqual((sim["6900"]["pool_end"], sim["7000"]["pool_end"]), ("68FF", "6FFF"))
        self.assertEqual((sim["copy_words"], sim["halt_above"]), ("292E", "70D9"))
        # +6 banner316; S1a, compress, sysinfo316, editdo, xparams316, tc316,
        # eraseall316, syncout316 and scsi316 (Vailixi ports,
        # notes/vailixi_features.md) bring 280 and 46; diskutil316 +60 and +2
        self.assertEqual((sim["relocated_cave_words"], sim["not_operand_words"]), (340, 48))


@unittest.skipUnless(HAVE_TOOLS, "needs nasm and ndisasm")
class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = b.M3K316.read_bytes()
        cls.targets, cls.consts = b._profile_values()
        args = mod.read_args(b.ARGS)
        asm = kit.assemble(args.cave, defines={b.DEFINE: None}, include=[args.cave.parent],
                           map_column="real", listing=True)
        cls.cave, cls.labels, cls.listing = asm.code, asm.labels, asm.listing
        cls.patches = [rc.expand(off, old, new, asm.labels, b.CAVE_HOME) for off, old, new in args.patch]
        cls.result = rc.build(cls.base, cls.cave, cls.labels, cls.patches, home=b.CAVE_HOME)
        cls.ops = b.entry_operands(cls.labels, cls.listing)
        cls.transfers = mod.far_transfers(mod.Cave((0, "", cls.cave.hex()), cls.labels, cls.cave, cls.listing))
        cls.used = b.used_targets(cls.transfers, cls.targets)
        cls.stock = bytes(rc.MZ.parse(cls.base).image)
        cls.patched = bytes(rc.MZ.parse(cls.result.sys).image)

    def verify(self, cave: bytes | None = None, labels: dict | None = None, listing: list | None = None,
               result: rc.Result | None = None) -> dict:
        cave = self.cave if cave is None else cave
        labels = self.labels if labels is None else labels
        listing = self.listing if listing is None else listing
        result = rc.build(self.base, cave, labels, self.patches, home=b.CAVE_HOME) if result is None else result
        return b.verify(result, cave, labels, listing, self.patches, self.consts, self.targets)

    def poke(self, at: int, data: bytes) -> dict:
        """verify() inputs with data written at cave offset `at`, in the binary and its listing."""
        cave = bytearray(self.cave)
        cave[at:at + len(data)] = data
        listing = [dataclasses.replace(line, data=bytes(cave[line.offset:line.offset + len(line.data)]))
                   for line in self.listing]
        return {"cave": bytes(cave), "listing": listing}

    def poke_op(self, name: str, value: int) -> dict:
        at, size = self.ops[name]
        return self.poke(at, value.to_bytes(size, "little"))

    def check_targets(self, targets: dict | None = None, used: set | None = None,
                      patched: bytes | None = None, patches: list | None = None, **kw) -> list[dict]:
        return b.check_targets(self.stock, self.patched if patched is None else patched,
                               self.patches if patches is None else patches,
                               self.targets if targets is None else targets,
                               self.used if used is None else used, **kw)

    def test_unmutated_inputs_pass(self) -> None:
        self.assertEqual(self.verify()["7000"]["pool_end"], "6FFF")
        self.assertEqual(len(self.check_targets()), len(self.used))

    # A. entry316 is run, not assumed.

    def test_cave_end_label_is_the_cave_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "cave_end label"):
            self.verify(labels=dict(self.labels, cave_end=self.labels["cave_end"] - 2))

    def test_entry316_must_assemble_to_the_modelled_routine(self) -> None:
        at = self.ops["pool_limit"][0] + 2              # JAE .pool_done -> JB
        with self.assertRaisesRegex(ValueError, "entry316 assembles 7203 here, expected 7303"):
            self.verify(**self.poke(at, b"\x72"))

    def test_copy_count_covers_the_cave(self) -> None:
        count = (len(self.cave) + 1) // 2
        for value in (count - 1, count + 1):
            with self.subTest(count=hex(value)), self.assertRaisesRegex(ValueError, "entry316 copies"):
                self.verify(**self.poke_op("count", value))

    def test_home_is_compared_with_the_relocated_cave(self) -> None:
        sys_bytes = bytearray(self.result.sys)
        sys_bytes[rc.MZ.parse(self.result.sys).h["cparhdr"] * 16 + self.result.stage * 16] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "the cave home is not the relocated cave"):
            self.verify(result=dataclasses.replace(self.result, sys=bytes(sys_bytes)))

    def test_halt_bound_is_the_last_load_segment_below_page_61(self) -> None:
        bound = self.verify()["halt_above"]
        for value in (int(bound, 16) - 1, int(bound, 16) + 1):
            with self.subTest(bound=hex(value)), self.assertRaisesRegex(ValueError, "entry316 halts above"):
                self.verify(**self.poke_op("halt_bound", value))

    def test_every_load_segment_passes_the_halt_bound(self) -> None:
        last = (rc.PAGE61 - len(self.cave)) // 16 - b.CAVE_HOME
        with mock.patch.object(rc, "LOADS", (last,)):
            self.assertIn(f"{last:04X}", self.verify())
        with mock.patch.object(rc, "LOADS", (0x6900, last + 1)), \
                self.assertRaisesRegex(ValueError, f"L={last + 1:04X}: entry316 halts"):
            self.verify()

    def test_pool_rule_is_run_as_assembled(self) -> None:
        for name, value in (("pool_opcode", 0xBA), ("pool_word", 0x6FFE), ("pool_limit", 0x6000),
                            ("pool_off", 0x0006)):
            with self.subTest(name), self.assertRaisesRegex(ValueError, "pool"):
                self.verify(**self.poke_op(name, value))

    # B. Targets are shape-checked in the bytes that run.

    def test_hook_site_target_needs_the_allow_list(self) -> None:
        with self.assertRaisesRegex(ValueError, f"T_D0C0_0B19 .* reach the patch at 0x{HOOK:05X}"):
            self.check_targets(on_hook=frozenset())

    def test_allow_listed_target_must_start_a_patch(self) -> None:
        targets = dict(self.targets, T_D0C0_0B19=(0x21E7, 0x0B20))
        with self.assertRaisesRegex(ValueError, f"no patch starts at 0x{HOOK + 1:05X}"):
            self.check_targets(targets=targets)
        with self.assertRaisesRegex(ValueError, "does not use"):
            self.check_targets(used=self.used - {"T_D0C0_0B19"})

    def test_target_may_not_reach_a_patch(self) -> None:
        for where, patch in (((0x21E7, 0x0B20), HOOK),     # inside the hook bytes
                             ((0x0318, 0x0004), 0x318C)):  # CALLF; ADD SP,2 then the help_gate hook
            targets = dict(self.targets, T_D0C0_0B1F=where)
            with self.subTest(where=where), \
                    self.assertRaisesRegex(ValueError, f"T_D0C0_0B1F .* reach the patch at 0x{patch:05X}"):
                self.check_targets(targets=targets)

    def test_same_shape_patch_inside_a_target_fails(self) -> None:
        seg, off = self.targets["T_D0C0_0B1F"]
        at = seg * 16 + off
        self.assertEqual(self.patched[at], 0x56)                       # PUSH SI -> PUSH DI: same shape
        patched = bytearray(self.patched)
        patched[at] = 0x57
        inputs = {"patched": bytes(patched), "patches": self.patches + [rc.Patch(at, b"\x56", b"\x57")]}
        with self.assertRaisesRegex(ValueError, f"T_D0C0_0B19 .* reach the patch at 0x{at:05X}"):
            self.check_targets(**inputs)                                # the hook site's stock bytes too
        with self.assertRaisesRegex(ValueError, f"T_D0C0_0B1F .* reach the patch at 0x{at:05X}"):
            self.check_targets(used={"T_D0C0_0B1F"}, on_hook=frozenset(), **inputs)

    # C. Relocated and unrelocated segment words.

    def test_entry316_values_only_at_their_sites(self) -> None:
        site = next(t.cave_offset + 3 for t in self.transfers if t.opcode == 0x9A)
        for value in (0xFFFF, 0x0000, b.POOL_IMM >> 4):
            with self.subTest(value=hex(value)), self.assertRaisesRegex(
                    ValueError, re.escape(f"at their sites: {{'cave+0x{site:X}': '{value:04X}'}}")):
                self.verify(**self.poke(site, struct.pack("<H", value)))
        with self.assertRaisesRegex(ValueError, "at their sites"):
            self.verify(**self.poke_op("dx", b.CAVE_HOME))

    def test_unrelocated_word_equal_to_any_allowed_segment(self) -> None:
        line = next(line for line in self.listing if line.data == bytes.fromhex("ba2000"))
        for seg in (0x0B72, 0x0427, 0x21E7, self.consts["SND_SEG"], b.CAVE_HOME):
            with self.subTest(seg=hex(seg)), self.assertRaisesRegex(
                    ValueError, f"unrelocated words equal to a segment value: cave\\+0x{line.offset + 1:X}={seg:04X}"):
                self.verify(**self.poke(line.offset + 1, struct.pack("<H", seg)))

    def test_far_transfer_into_a_data_segment(self) -> None:
        t = next(t for t in self.transfers if t.opcode == 0x9A)
        for seg in (self.consts["SND_SEG"], self.consts["DGROUP_SEG"]):
            with self.subTest(seg=hex(seg)), self.assertRaisesRegex(ValueError, f"into data segment {seg:04X}"):
                self.verify(**self.poke(t.cave_offset + 3, struct.pack("<H", seg)))

    # D. ndisasm is not trusted across BRKXA/RETXA.

    def test_target_shape_refuses_brkxa_retxa_on_either_side(self) -> None:
        seg, off = self.targets["T_D0C0_0B1F"]
        patched = bytearray(self.patched)
        patched[seg * 16 + off + 1:seg * 16 + off + 3] = b"\x0f\xe0"
        with self.assertRaisesRegex(ValueError, "BRKXA/RETXA"):
            self.check_targets(patched=bytes(patched))
        vailixi = bytearray(mod.linear())
        v_lin = (0xD0C0 << 4) + 0x0B1F - 0x80000
        vailixi[v_lin:v_lin + 2] = b"\x0f\xf0"
        with mock.patch.object(mod, "linear", return_value=bytes(vailixi)), \
                self.assertRaisesRegex(ValueError, "BRKXA/RETXA"):
            self.check_targets()


@unittest.skipUnless(shutil.which("ndisasm"), "needs ndisasm")
class Shape(unittest.TestCase):
    def test_compared_bytes_may_not_hold_brkxa_retxa(self) -> None:
        for code in ("0fe0", "900ff0", "558bec0fe0"):
            with self.subTest(code), self.assertRaisesRegex(ValueError, "BRKXA/RETXA"):
                b._shape(bytes.fromhex(code) + b"\x90" * 16, 0, 0, b.SHAPE_INSNS)

    def test_bytes_after_the_compared_instructions_are_not_checked(self) -> None:
        self.assertEqual(b._shape(bytes.fromhex("c30fe0"), 0, 0, 6), [(1, "ret")])
        self.assertEqual(b._shape(b"\x90" * 6 + b"\x0f\xe0", 0, 0, 6), [(1, "nop")] * 6)

    def test_long_instruction_continuation_line(self) -> None:
        self.assertEqual(b._shape(bytes.fromhex("66c706341278563412") + b"\x90", 0, 0, 2),
                         [(9, "mov"), (1, "nop")])


if __name__ == "__main__":
    unittest.main()
