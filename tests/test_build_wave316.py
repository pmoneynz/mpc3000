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
SYS_SHA256 = "1638489e813b98b439e102a5763b6aac8f995a1f64f7389ed337c0564b1be7b2"
IMG_SHA256 = "e5ef60379748312e8e3cb37336ba84d70cb4939f32726de8a945ef6872d85b49"
CAVE_SHA256 = "7551e909db371801a53a21f65c0cdd5ade7f24e318ea6904caa638596ec368ac"
# Size budget (notes/port_316.md "Cave space"): entry316 runs 3.16 at L = 6900
# on every EPROM set (3.08/3.11 load at 7000 and are moved down), so the cave
# home 7E00 must end below F400h: 53,248 bytes on every machine.  Lower
# HOME_BUDGET after each size step; raise it only with a note.
HOME_LIMIT = 0xF4000 - 0x69000 - 0x7E00 * 16
CAVE_HOME_IMAGE = 0x7E00 * 16      # image offset of the cave home (relative paragraph 7E00)
HOME_BUDGET = 21_386            # bytes (+232 display316 put-char and string writer, 2026-10-17;
                                # earlier: entry316 copies to the home (19,200 after the size
                                # pass; +350 for the audit and stock-bug fixes, 2026-10-16;
                                # 20,690 with the performance pass, perf316.inc and the view's
                                # fast paths without S6 and D1a, 2026-10-16; 21,140 with the
                                # crash fixes C1-C3 and scsistack316, 2026-10-17; 21,154 with
                                # scsistack316's no-wrap fallback, 2026-10-17)
HOME_HEADROOM = 31_000          # kept free under the universal page-61 limit (31,862 free with
                                # display316; 32,094 before it,
                                # 2026-10-17; before the universal layout the 3.08/3.11
                                # limit left 3,436 and this was 3,400).  This is the binding
                                # limit: the old SCSI stack-wrap backstop (home end <= image
                                # 0x83300) is gone, see SCSI_DEPTH below.
# Stock 3.16's SCSI partition reader 2AB2:04F7 opens SUB SP,100Eh; entered on the UI
# stack (SS rel 73E1) with SP ~ 07D2 it wrapped to SS:F7xx, image ~0x835xx, inside the
# cave home's range.  scsistack316 runs it on its private stack; its fallback (busy or no
# private stack, both unreachable: tools/scsi_reader_reach.py, emu.test_scsi316) runs the
# stock frame only with SP >= SCSI_STK_BYTES and otherwise returns the reader's error 4, so
# no path can wrap (test_scsi_wrapper_* below).  SCSI_DEPTH: the reader's deepest measured
# use, which SCSI_STK_BYTES must cover.
SCSI_DEPTH = 0x109A
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
        self.assertEqual((sim["6900"]["pool_end"], sim["7000"]["pool_end"]), ("67DF", "67DF"))
        self.assertEqual((sim["6900"]["runtime_segment"], sim["7000"]["runtime_segment"]), ("6900", "6900"))
        self.assertEqual((sim["6900"]["moved"], sim["7000"]["moved"]), (False, True))
        self.assertEqual((sim["copy_words"], sim["min_move"]), ("29C5", "01F2"))
        self.assertEqual((sim["table"]["bytes"], sim["table"]["records"]), (7639, 7317))
        copied = 2 * int(sim["copy_words"], 16)
        self.assertLessEqual(copied, HOME_BUDGET, f"cave home {copied} B over budget")
        self.assertGreaterEqual(HOME_LIMIT - copied, HOME_HEADROOM)
        # +6 banner316; S1a, compress, sysinfo316, editdo, xparams316, tc316,
        # eraseall316, syncout316 and scsi316 (Vailixi ports,
        # notes/vailixi_features.md) bring 280 and 46; diskutil316 +60 and +2;
        # the size pass (push cs, shared ui316 helpers) 251 and 36; the audit
        # and stock-bug fixes (bugfix316.inc) 259 and 35; the performance pass
        # (perf316.inc, R5 so_mtc_send, the view's fast paths) 267 and 40;
        # display316 (BIOS DS 59FA twice and the stock fallback 0427:0046) +3
        self.assertEqual((sim["relocated_cave_words"], sim["not_operand_words"]), (279, 41))


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
        cls.transfers = b.cave_transfers(cls.cave, cls.labels, cls.listing)
        cls.used = b.used_targets(cls.transfers, cls.targets)
        cls.stock = bytes(rc.MZ.parse(cls.base).image)
        cls.patched = bytes(rc.MZ.parse(cls.result.sys).image)

    def verify(self, cave: bytes | None = None, labels: dict | None = None, listing: list | None = None,
               result: rc.Result | None = None, memories: dict | None = None) -> dict:
        cave = self.cave if cave is None else cave
        labels = self.labels if labels is None else labels
        listing = self.listing if listing is None else listing
        result = rc.build(self.base, cave, labels, self.patches, home=b.CAVE_HOME) if result is None else result
        return b.verify(result, cave, labels, listing, self.patches, self.consts, self.targets, memories)

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
        self.assertEqual(self.verify()["7000"]["pool_end"], "67DF")
        self.assertEqual(len(self.check_targets()), len(self.used))

    # A. entry316 is run, not assumed.

    def test_pool_leaves_the_scsi_reader_stack(self) -> None:
        # entry316 lowers the pool end by SCSI_STK_PARAS (scsistack316.inc's stack)
        with self.assertRaisesRegex(ValueError, "pool end 68FF, expected 67DF"):
            self.verify(**self.poke_op("pool_room", 0))

    def test_cave_end_label_is_the_cave_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "cave_end label"):
            self.verify(labels=dict(self.labels, cave_end=self.labels["cave_end"] - 2))

    def test_entry316_must_assemble_to_the_modelled_routine(self) -> None:
        at = self.ops["pool_word"][0] + 2               # JNE .pool_done -> JE
        with self.assertRaisesRegex(ValueError, "entry316 assembles 7408 here, expected 7508"):
            self.verify(**self.poke(at, b"\x74"))

    def test_entry316_constants_are_the_model(self) -> None:
        for name, value in (("univ_mv", 0x6800), ("chunk", 0x1000), ("bios_jmp", 0x68C0), ("t_dmin", 0),
                            ("moved", 0)):
            with self.subTest(name), self.assertRaisesRegex(ValueError, f"immediates differ.*'{name}'"):
                self.verify(**self.poke_op(name, value))

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

    def run_wrapper(self, busy: int, sp: int) -> tuple:
        """scsistack316's wrapper from the reader's patched prologue, on the final L=6900
        memory: the UI task's stack SS = 6900+73E1 with the caller's far return address
        (2AB2:0772) at SP.  Stops at the reader body 2AB2:04FE or back at the caller."""
        from tests.x86sub import Cpu
        mems: dict[int, bytearray] = {}
        self.verify(memories=mems)
        mem = mems[0x6900]
        home = (0x6900 + b.CAVE_HOME) * 16
        mem[home + self.labels["scsi_stk_busy"]] = busy
        cpu = Cpu(mem)
        reader_cs, ret = (0x6900 + 0x2AB2) & 0xFFFF, 0x0772
        cpu.s.update(cs=(0x6900 + b.CAVE_HOME) & 0xFFFF, ss=0x6900 + 0x73E1, ds=0x6900 + 0x609C, es=0)
        cpu.ip, cpu.r["sp"], cpu.r["bp"] = self.labels["scsi_stack"], sp, 0x3E38
        cpu.ww("ss", sp, ret)
        cpu.ww("ss", sp + 2, reader_cs)
        cpu.writes.clear()
        while not (cpu.s["cs"] == reader_cs and cpu.ip in (0x04FE, ret)):
            cpu.step()
        return cpu, mem

    def test_scsi_wrapper_takes_the_private_stack(self) -> None:
        cpu, _ = self.run_wrapper(busy=0, sp=0x07D2)
        stk = self.consts["SCSI_STK_PARAS"]
        self.assertEqual(cpu.ip, 0x04FE)
        self.assertEqual(cpu.s["ss"], 0x6900 - stk)                    # just below the image
        self.assertEqual(cpu.r["sp"], stk * 16 - 4 - 2 - 0x100E)      # far frame, BP, the 100Eh frame

    def test_scsi_wrapper_fallback_cannot_wrap(self) -> None:
        self.assertGreaterEqual(self.consts["SCSI_STK_PARAS"] * 16, SCSI_DEPTH)
        # Held, shallow caller stack: no read, error 4, nothing written on the caller's stack.
        cpu, mem = self.run_wrapper(busy=1, sp=0x07D2)
        self.assertEqual((cpu.ip, cpu.r["ax"], cpu.r["sp"]), (0x0772, 4, 0x07D6))
        self.assertEqual(mem[(0x6900 + 0x609C) * 16 + 0x79A4], 0)
        busy = (0x6900 + b.CAVE_HOME) * 16 + self.labels["scsi_stk_busy"]
        self.assertLessEqual(cpu.writes, {busy, (0x6900 + 0x609C) * 16 + 0x79A4})   # XCHG and [79A4] only
        # Held, deep enough: the stock frame on the caller's stack, entirely below SP.
        sp = self.consts["SCSI_STK_PARAS"] * 16
        cpu, _ = self.run_wrapper(busy=1, sp=sp)
        self.assertEqual((cpu.ip, cpu.r["sp"], cpu.r["bp"]), (0x04FE, sp - 2 - 0x100E, sp - 2))
        self.assertGreaterEqual(sp - SCSI_DEPTH, 0)                    # the deepest use stays above SS:0000

    def test_move_halts_below_the_least_move(self) -> None:
        # .move halts when the copy would reach entry316 (L - 6900 < the table's least D).
        least = int(self.verify()["min_move"], 16)
        with mock.patch.object(rc, "LOADS", (0x6900, 0x6900 + least)):
            self.assertTrue(self.verify()[f"{0x6900 + least:04X}"]["moved"])
        with mock.patch.object(rc, "LOADS", (0x6900, 0x6900 + least - 1)), \
                self.assertRaisesRegex(ValueError, f"L={0x6900 + least - 1:04X}: entry316 halts"):
            self.verify()

    def test_other_load_segments(self) -> None:
        # Below 6900 entry316 runs in place (no move); above it, any L moves to 6900.
        with mock.patch.object(rc, "LOADS", (0x6800, 0x6900, 0x7000, 0x7400)):
            sim = self.verify()
        self.assertEqual([sim[k]["runtime_segment"] for k in ("6800", "6900", "7000", "7400")],
                         ["6800", "6900", "6900", "6900"])
        self.assertEqual(sim["6800"]["pool_end"], "66DF")

    def test_relocation_table_is_the_mz_list(self) -> None:
        sys_bytes = bytearray(self.result.sys)
        hdr = rc.MZ.parse(self.result.sys).h["cparhdr"] * 16
        sys_bytes[hdr + self.result.table + rc.TABLE_HEAD] += 1     # first record one byte further
        with self.assertRaisesRegex(ValueError, "not the MZ relocation list"):
            self.verify(result=dataclasses.replace(self.result, sys=bytes(sys_bytes)))

    def test_table_records_round_trip(self) -> None:
        positions = [3, 5, 0x105, 0x105 + rc.SKIP + 1, 0x105 + 3 * rc.SKIP + 7, 0x50000]
        records, count = rc.encode_relocs(positions)
        head, out = rc.decode_relocs(struct.pack("<3H", 0, count, 0) + records)
        self.assertEqual(out, positions)
        with self.assertRaisesRegex(ValueError, "not after"):
            rc.encode_relocs([0])

    def test_final_memory_is_identical_for_6900_and_7000(self) -> None:
        mems: dict[int, bytearray] = {}
        self.verify(memories=mems)
        self.assertEqual(sorted(mems), [0x6900, 0x7000])
        self.assertTrue(mems[0x6900] == mems[0x7000])

    def test_entry316_bytes_run_in_x86sub(self) -> None:
        # The assembled entry316 run by the interpreter from the loader's hand-off
        # state at both load segments: the same memory and registers at 3.16's
        # entry 6900:0000, and the builder's model agrees with every byte except
        # the 2-byte PUSH CS / POP DS slot under SP (the model has no stack).
        from tests.x86sub import Cpu
        mems: dict[int, bytearray] = {}
        self.verify(memories=mems)
        runs = {}
        for load in (0x6900, 0x7000):
            mem, regs = rc.load(self.result.sys, load)
            cpu = Cpu(mem)
            cpu.s.update(cs=regs["cs"], ss=regs["ss"], ds=0x0040, es=regs["cs"])
            cpu.ip, cpu.r["sp"], cpu.r["bp"] = regs["ip"], regs["sp"], 0x69B6
            cpu.f["df"] = True
            while not (cpu.s["cs"] == 0x6900 and cpu.ip == 0):
                cpu.step()
            state = (dict(cpu.r), dict(cpu.s), cpu.flags)
            stack = {(cpu.s["ss"] * 16 + cpu.r["sp"] - 2 + i) for i in range(2)}
            model = mems[load]
            diff = set() if mem == model else {i for i in range(len(mem)) if mem[i] != model[i]}
            self.assertLessEqual(diff, stack, f"L={load:04X}: model differs at {sorted(diff)[:8]}")
            runs[load] = (mem, state, cpu.steps)
        self.assertEqual(runs[0x6900][1], runs[0x7000][1])
        self.assertTrue(runs[0x6900][0] == runs[0x7000][0])
        self.assertEqual(runs[0x7000][1][0]["bp"], 0x69B6)
        self.assertEqual(runs[0x7000][1][1]["ss"], 0x6900 + rc.MZ.parse(self.result.sys).h["ss"])

    def test_pool_rule_is_run_as_assembled(self) -> None:
        for name, value in (("pool_opcode", 0xBA), ("pool_word", 0x6FFE), ("pool_off", 0x0006)):
            with self.subTest(name), self.assertRaisesRegex(ValueError, "pool"):
                self.verify(**self.poke_op(name, value))

    # B. Targets are shape-checked in the bytes that run.

    def test_hook_site_target_needs_the_allow_list(self) -> None:
        with self.assertRaisesRegex(ValueError, f"T_D0C0_0B19 .* reach the patch at 0x{HOOK:05X}"):
            self.check_targets(on_hook=b.HOOK_TARGETS - {"T_D0C0_0B19"})

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
