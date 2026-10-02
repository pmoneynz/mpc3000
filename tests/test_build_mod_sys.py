"""Route A builder rules (mods/build_mod_sys.py) and the capture profile checks.

Every build here writes to a temporary directory, never build/mods.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mods"))
import build_mod_sys as b  # noqa: E402
import buildkit as kit  # noqa: E402

HAVE_NASM = shutil.which("nasm") is not None


class TempDir(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "out"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def asm(self, body: str, name: str = "t.asm") -> Path:
        src = self.tmp / name
        src.write_text("bits 16\norg 0\n" + body)
        return src


@unittest.skipUnless(HAVE_NASM, "needs nasm")
class CaveTests(TempDir):
    def setUp(self) -> None:
        super().setUp()
        self.img = b.linear()

    def test_cave_bounds_and_segment(self) -> None:
        self.assertEqual(b.CAVE, (0x707D0, 0x74000))
        self.assertEqual(b.CAVE_SEG, 0xF07D)
        self.assertEqual(self.img[0x707C8:0x74000], b"\xff" * (0x74000 - 0x707C8))

    def test_labels_become_far_pointers(self) -> None:
        patch, labels = b.cave(self.asm("a: nop\nb: retf\n"), self.img, out=self.out)
        self.assertEqual(patch, (0x707D0, "ffff", "90cb"))
        self.assertEqual(labels, {"a": 0, "b": 1})
        self.assertEqual(b.far("9a{b}90", labels), "9a01007df090")
        with self.assertRaises(ValueError):
            b.far("9a{c}", labels)
        self.assertEqual((self.out / "t.cave.bin").read_bytes(), b"\x90\xcb")
        self.assertIn(" b", (self.out / "t.cave.map").read_text())

    def test_rejects_oversize_and_brkxa(self) -> None:
        with self.assertRaises(ValueError):
            b.cave(self.asm(f"times {0x74000 - 0x707D0 + 1} nop\n"), self.img, out=self.out)
        with self.assertRaises(ValueError):
            b.cave(self.asm("db 0x0f, 0xe0, 0x10\n"), self.img, out=self.out)

    def test_stale_published_map_is_never_parsed(self) -> None:
        self.out.mkdir()
        (self.out / "t.cave.map").write_text(
            "Real              Virtual           Name\n"
            "            1234              1234  a\n")
        (self.out / "cave_map.inc").write_text("[map symbols /nonexistent/elsewhere.map]\n")
        _patch, labels = b.cave(self.asm("a: nop\n"), self.img, out=self.out)
        self.assertEqual(labels, {"a": 0})
        self.assertNotIn("1234", (self.out / "t.cave.map").read_text())

    def test_missing_map_from_this_run_is_an_error(self) -> None:
        real_run = subprocess.run

        def no_map(cmd, *args, **kwargs):            # NASM "succeeds" but writes no map
            if cmd and cmd[0] == "nasm" and "-P" in cmd:
                i = cmd.index("-P")
                cmd = cmd[:i] + cmd[i + 2:]
            return real_run(cmd, *args, **kwargs)
        self.out.mkdir()
        (self.out / "t.cave.map").write_text("            0              0  a\n")
        with mock.patch.object(kit.subprocess, "run", no_map):
            with self.assertRaisesRegex(RuntimeError, "no symbol map"):
                b.cave(self.asm("nop\na: nop\n"), self.img, out=self.out)

    def test_concurrent_default_stem_builds_keep_their_own_labels(self) -> None:
        sources = [self.asm(f"times {n} nop\nmark{n}: retf\n", f"s{n}.asm") for n in range(1, 9)]
        results: dict[int, dict[str, int]] = {}

        def go(n: int, src: Path) -> None:
            results[n] = b.cave(src, self.img, out=self.out)[1]
        threads = [threading.Thread(target=go, args=(n, s)) for n, s in enumerate(sources, 1)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results, {n: {f"mark{n}": n} for n in range(1, 9)})
        self.assertFalse((self.out / "cave_map.inc").exists())


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.img = bytearray(0x80000)
        self.img[0x27C8E:0x27C92] = b"\x11\x22\x33\x44"
        self.img[0x30000:0x30002] = b"\xaa\xbb"

    def test_applies_matching_patch(self) -> None:
        b.apply(self.img, [(0x30000, "aabb", "ccdd")])
        self.assertEqual(self.img[0x30000:0x30002], b"\xcc\xdd")

    def test_old_byte_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected aabc"):
            b.apply(self.img, [(0x30000, "aabc", "ccdd")])

    def test_length_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "lengths differ"):
            b.apply(self.img, [(0x30000, "aabb", "cc")])

    def test_out_of_range(self) -> None:
        for off, old in ((0x2FFFF, "00aa"), (0x74000, "00"), (0x78000, "00"), (0x1FFFF, "0000")):
            with self.subTest(off=hex(off)), self.assertRaisesRegex(ValueError, "outside"):
                b.apply(self.img, [(off, old, old)])

    def test_capture_profile_bounds_reject_unshipped_dgroup_tail(self) -> None:
        b.apply(bytearray(self.img), [(0x27C90, "3344", "0000")])      # generic ships 7C92
        for off, old in ((0x27C90, "3344"), (0x27C91, "44"), (0x27C8E, "11223344")):
            with self.subTest(off=hex(off)), self.assertRaisesRegex(ValueError, "outside"):
                b.apply(bytearray(self.img), [(off, old, "00" * (len(old) // 2))],
                        dgroup=(0x20000, 0x27C90))
        b.apply(self.img, [(0x27C8E, "1122", "0000")], dgroup=(0x20000, 0x27C90))


@unittest.skipUnless(HAVE_NASM, "needs nasm")
class ImageGuardTests(TempDir):
    def test_linear_image_is_hash_pinned(self) -> None:
        self.assertEqual(kit.sha256(b.linear()), kit.VAILIXI350_SHA256)
        with self.assertRaisesRegex(ValueError, "pinned"):
            kit.linear(kit.LS350_PATH, kit.MS350_PATH, "0" * 64)

    def test_dgroup_count_must_match_guarded_bios(self) -> None:
        img = b.linear()
        b.guard_layout(img[0x78000:], 0x7C92)
        with self.assertRaisesRegex(ValueError, "0x7AC85.*7C92"):
            b.image(img, dgroup=(0x20000, 0x27C90), out=self.out)
        self.assertFalse(self.out.exists())

    def test_exact_guard_must_be_the_pinned_capture(self) -> None:
        bios = self.tmp / "bios.bin"
        bios.write_bytes(b.linear()[0x78000:])
        with self.assertRaisesRegex(ValueError, "hash-pinned"):
            b.stub(exact_bios_path=bios, exact_bios_sha256="0" * 64, out=self.out)
        code = b.stub(exact_bios_path=bios, exact_bios_sha256=kit.sha256(bios.read_bytes()),
                      out=self.out)
        self.assertIn(bios.read_bytes(), code)


@unittest.skipUnless(HAVE_NASM, "needs nasm")
class BuildTests(TempDir):
    def test_cli_out_directory_and_deterministic_image(self) -> None:
        for _ in range(2):
            subprocess.run([sys.executable, str(ROOT / "mods/build_mod_sys.py"), "@mods/DEMO351.args",
                            f"--out={self.out}"], cwd=ROOT, check=True, capture_output=True)
            if _ == 0:
                first = (self.out / "DEMO351.img").read_bytes()
        image = (self.out / "DEMO351.img").read_bytes()
        self.assertEqual(image, first)
        entry = image[kit.ROOT_OFFSET:kit.ROOT_OFFSET + 32]
        self.assertEqual(entry[:12], b"DEMO351 SYS\x20")
        self.assertEqual(entry[0x0C:0x1A], bytes(14))
        payload = (self.out / "DEMO351.SYS").read_bytes()
        self.assertEqual(kit.extract_contiguous(image, 2, len(payload)), payload)


CAPTURES = all(p.exists() for p in (ROOT / "build/hardware/2026-10-01-romapp/ROMAPP.BIN",
                                    ROOT / "build/hardware/2026-10-01-romdump/BIOS.BIN"))


@unittest.skipUnless(HAVE_NASM, "needs nasm")
@unittest.skipUnless(CAPTURES, "needs the 2026-10-01 captures under build/hardware")
class CaptureProfileTests(TempDir):
    @classmethod
    def setUpClass(cls) -> None:
        from mods import build_wave_physical as profile
        cls.profile = profile
        cls.generic_img = b.linear()
        cls.capture_img = bytes(profile.inputs())

    def caves(self, generic_body: str, capture_body: str):
        src = self.asm(f"%ifdef {self.profile.DEFINE}\n{capture_body}\n%else\n{generic_body}\n%endif\n")
        pm = self.profile.mod
        gen = pm.assemble_cave(src, self.generic_img, publish=False)
        cap = pm.assemble_cave(src, self.capture_img, defines={self.profile.DEFINE: "1"}, publish=False)
        return gen, cap

    def check(self, generic_body: str, capture_body: str | None = None):
        gen, cap = self.caves(generic_body, generic_body if capture_body is None else capture_body)
        return self.profile.check_far_targets(self.generic_img, gen, self.capture_img, cap)

    def test_documented_shared_and_amx_targets_pass(self) -> None:
        records = self.check("call 0xD21F:0x0008\ncall 0xFB00:0x06B9\nretf",
                             "call 0xD21F:0x0008\ncall 0xFB00:0x06AF\nretf")
        self.assertEqual([(r["target"], r["kind"]) for r in records],
                         [("D21F:0008", "shared"), ("FB00:06AF", "amx-shifted")])

    def test_untranslated_bios_target_fails_and_names_it(self) -> None:
        with self.assertRaisesRegex(ValueError, r"far target FB00:06B9 .*differs from generic"):
            self.check("call 0xFB00:0x06B9\nretf")

    def test_wrong_translation_fails_and_names_it(self) -> None:
        with self.assertRaisesRegex(ValueError, r"far target D21F:0006 .*not a documented translation"):
            self.check("call 0xD21F:0x0008\nretf", "call 0xD21F:0x0006\nretf")

    def test_structurally_divergent_capture_code_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, r"far target EB80:0000 .*diverges"):
            self.check("jmp 0xEB80:0x0000")

    def test_uncaptured_target_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, r"far target F400:0010 .*outside captured"):
            self.check("jmp 0xF400:0x0010")

    def test_indirect_far_transfer_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "indirect far"):
            self.check("call far [cs:0x10]\nretf")

    def test_wave_cave_far_targets_all_validate(self) -> None:
        src = ROOT / "mods/wave.asm"
        pm = self.profile.mod
        gen = pm.assemble_cave(src, self.generic_img, publish=False)
        cap = pm.assemble_cave(src, self.capture_img, defines={self.profile.DEFINE: "1"}, publish=False)
        records = self.profile.check_far_targets(self.generic_img, gen, self.capture_img, cap)
        self.assertGreater(len(records), 0)
        self.assertEqual(sum(r["uses"] for r in records), len(pm.far_transfers(cap)))
        self.assertIn(("FB00:06AF", "FB00:06B9"),
                      {(r["target"], r["generic"]) for r in records if r["kind"] == "amx-shifted"})

    def test_translation_of_wave_args(self) -> None:
        args = b.read_args(ROOT / "mods/WAVE.args")
        patches = self.profile.translate(args.patch, self.capture_img)
        self.assertEqual(len(patches), len(args.patch))
        marker = self.profile.marker_text(args.patch)
        site, old, new = patches[0]
        self.assertEqual(site, 0x210F5)
        self.assertEqual(bytes.fromhex(new), marker.ljust(27, b"\0"))
        moved = {off for off, _, _ in patches} - {off for off, _, _ in args.patch}
        self.assertEqual(moved, {0x210F5, 0x25E90})
        trial = bytearray(self.capture_img)
        b.apply(trial, [(o, old, b.far(n, {k: 0 for k in __import__("re").findall(r"\{(\w+)\}", n)}))
                        for o, old, n in patches], dgroup=self.profile.DGROUP)

    def test_translation_rejects_undeclared_or_stale_entries(self) -> None:
        args = b.read_args(ROOT / "mods/WAVE.args")
        tr = self.profile.translate
        with self.assertRaisesRegex(ValueError, "no declared capture translation"):
            tr([*args.patch, (0x26000, "00", "01")], self.capture_img)
        bad = [(o, old if o != 0x39A03 else "8bf8a00be48846fe", n) for o, old, n in args.patch]
        with self.assertRaisesRegex(ValueError, "translation expects E40A"):
            tr(bad, self.capture_img)
        with self.assertRaisesRegex(ValueError, "VERBATIM_NEW"):
            tr([*args.patch, (0x30100, "0000", "a10a00")], self.capture_img)
        with self.assertRaisesRegex(ValueError, "exactly one marker"):
            tr([p for p in args.patch if p[0] != 0x21110], self.capture_img)

    def test_build_writes_only_to_its_out_directory(self) -> None:
        shipped = b.OUT / "WAVEHW.SYS"
        before = shipped.stat().st_mtime_ns if shipped.exists() else None
        manifest = self.profile.build(out=self.out)
        self.assertEqual(before, shipped.stat().st_mtime_ns if shipped.exists() else None)
        self.assertTrue((self.out / "WAVEHW.SYS").exists())
        self.assertTrue((self.out / "wavehw.cave.map").exists())
        args = b.read_args(ROOT / "mods/WAVE.args")
        self.assertEqual(manifest["marker"], self.profile.marker_text(args.patch).decode())
        for inc in ("mods/mute_storage.inc", "mods/mute_voice.inc", "mods/mute_ui.inc",
                    "mods/wave_font.inc", "mods/wave.asm", "mods/mod_stub.asm"):
            self.assertIn(inc, manifest["sources"])
        self.assertGreater(manifest["far_targets"]["transfers"], 0)


@unittest.skipUnless(HAVE_NASM, "needs nasm")
class WaveBenchTests(TempDir):
    def test_marker_and_sources_follow_wave_args_and_nasm(self) -> None:
        from mods import build_wave_bench as bench
        manifest = bench.main(self.out)
        args = b.read_args(ROOT / "mods/WAVE.args")
        planted = bytes.fromhex(next(n for o, _, n in args.patch if o == 0x21110)).split(b"\0")[0]
        self.assertEqual(manifest["marker"], planted.decode())
        includes = {f"mods/{p.name}" for p in kit.nasm_deps(ROOT / "mods/wave.asm",
                                                              include=[ROOT / "mods"])}
        self.assertTrue({"mods/mute_storage.inc", "mods/mute_voice.inc", "mods/mute_ui.inc"} <= includes)
        self.assertTrue(includes <= set(manifest["sources"]))
        self.assertTrue((self.out / "WAVEBENCH.img").exists())


class FontTests(unittest.TestCase):
    def test_wave_font_include_is_generated(self) -> None:
        import contextlib
        import io
        from emu import lcd_font
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            lcd_font.main()
        inc = ROOT / "mods" / "wave_font.inc"
        self.assertEqual(inc.read_text(), out.getvalue())


if __name__ == "__main__":
    unittest.main()
