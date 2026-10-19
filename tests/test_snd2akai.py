"""tools/snd2akai.py: MPC3000 SND -> Akai S1000/S3000 floppy images.

The 3.50 loader model below follows notes/akai_disk.md (BE7E:0F9F and its
helpers); the emulator test in emu/test_akai_load.py runs the real loader.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from emu.snd import sine, snd, sine441, stereo1  # noqa: E402
from tools import snd2akai as sa  # noqa: E402

# akaiutil 4.6.8 `formatfloppyh1` / `formatfloppyh3` on a zeroed 1,638,400-byte file.
AKAIUTIL_EMPTY_S1000_HD = "0f6efb0507c25ddb28553cf40c0b69334067b0e0894f4a01987ef7cf3d2fcef8"
AKAIUTIL_EMPTY_S3000_HD = "a91379f57f9f8b017b6eca5b3f3fbf5cd87254658211f3b4b553b98ca0dc9fd6"


def load_350(img: bytes) -> list[sa.Sound]:
    """What Vailixi 3.50 Disk 8 makes of each listed floppy sample (notes/akai_disk.md)."""
    d = sa.density_of(img)
    base = 0x1400 if img[0x10] == 0xFF else 0                          # BE7E:04DF
    fat = struct.unpack_from(f"<{d.blocks}H", img, 0x600)
    entries = {}
    for i in range(64):                                                 # BE7E:03C5
        raw = img[base + i * 24:base + (i + 1) * 24]
        if raw[0x10] & 0x7F == 0x73:                                    # BE7E:043E
            entries[sa.decode_name(raw[:12])] = (raw[0x11] | raw[0x12] << 8 | raw[0x13] << 16,
                                                 struct.unpack_from("<H", raw, 0x14)[0])

    def words(name: str) -> tuple[bytes, int, int, int]:
        size, block = entries[name]
        out = bytearray(img[block * 1024 + 0x96:(block + 1) * 1024])   # header fixed at 0x96
        head = img[block * 1024:block * 1024 + 0x96]
        assert sa.decode_name(head[3:15]) == name                      # BE7E:0939
        count, start, end = struct.unpack_from("<3I", head, 0x1A)
        while len(out) < 2 * count:
            block = fat[block]
            assert block != 0x8000                                      # BE7E:0A4F
            out += img[block * 1024:(block + 1) * 1024]
        return bytes(out[:2 * count]), start, end, struct.unpack_from("<h", head, 0x14)[0]

    sounds = []
    for name in entries:
        if len(name) > 2 and name[-2] == "-" and name[-1] in "LR":      # BE7E:0626
            left, right = name[:-1] + "L", name[:-1] + "R"
            if right in entries and left in entries and entries[left][0] == entries[right][0]:
                if name == right:
                    continue
                (a, start, end, tune), (b, *_) = words(left), words(right)
                sounds.append(sa.Sound(left[:-2].rstrip(), [a, b], start, end, sa.mpc_tune(tune)))
                continue
        pcm, start, end, tune = words(name)
        sounds.append(sa.Sound(name, [pcm], start, end, sa.mpc_tune(tune)))
    return sounds


def snd_bytes(name: str, planes: list[list[int]], **kw) -> bytes:
    data = bytearray(snd(name, planes, **{k: v for k, v in kw.items() if k != "tune"}))
    data[2 + 0x12] = kw.get("tune", 0) & 0xFF
    return bytes(data)


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="snd2akai-"))
        self.addCleanup(shutil.rmtree, self.dir)

    def put(self, file: str, data: bytes) -> Path:
        path = self.dir / file
        path.write_bytes(data)
        return path


class NameTests(unittest.TestCase):
    def test_akai_characters(self) -> None:
        self.assertEqual(sa.clean_name("kick_01"), "KICK 01")
        self.assertEqual(sa.clean_name("  Snare (2)! "), "SNARE -2--")
        self.assertEqual(sa.clean_name("a#b+c-d.e"), "A#B+C-D.E")
        self.assertEqual(sa.decode_name(sa.encode_name("A#B+C-D.E 09")), "A#B+C-D.E 09")
        self.assertEqual(sa.encode_name("AB"), bytes([11, 12] + [10] * 10))
        for bad in ("TOO LONG NAME", "lower", "Ü"):
            with self.assertRaises(sa.ConvertError):
                sa.encode_name(bad)

    def test_stereo_names_keep_the_suffix(self) -> None:
        self.assertEqual(sa.sample_names("A VERY LONG NAME", True), ["A VERY LON-L", "A VERY LON-R"])
        self.assertEqual(sa.sample_names("ST", True), ["ST        -L", "ST        -R"])
        self.assertEqual(sa.sample_names("A VERY LONG NAME", False), ["A VERY LONG"])
        self.assertEqual(sa.sample_names("SNARE-L", False), ["SNARE L"])
        self.assertEqual(sa.sample_names("-R", False), ["-R"])

    def test_tune_survives_the_350_conversion(self) -> None:
        for t in range(-120, 121):
            self.assertEqual(sa.mpc_tune(sa.akai_tune(t)), t)
        self.assertEqual(sa.akai_tune(10), 256)        # one semitone in the high byte
        with self.assertRaises(sa.ConvertError):
            sa.akai_tune(121)


class SndTests(unittest.TestCase):
    def test_read_mono_and_stereo(self) -> None:
        mono = sa.read_snd(snd("SINE441", sine441()))
        self.assertEqual((mono.name, mono.frames, len(mono.planes), mono.start, mono.end),
                         ("SINE441", 55125, 1, 0, 55125))
        st = sa.read_snd(snd("STEREO1", stereo1(), start=5, end=99))
        self.assertEqual((st.frames, len(st.planes), st.start, st.end), (33075, 2, 5, 99))
        self.assertEqual(st.planes[1], struct.pack(f"<{st.frames}h", *stereo1()[1]))

    def test_write_snd_is_the_inverse(self) -> None:
        data = snd_bytes("TUNED", [sine(500)], start=3, end=400, tune=-37)
        again = sa.write_snd(sa.read_snd(data))
        self.assertEqual(again[2:18], b"TUNED" + b" " * 11)    # the MPC record pads with spaces
        self.assertEqual(sa.read_snd(again), sa.read_snd(data))

    def test_rejects_malformed_files(self) -> None:
        good = snd("X", [sine(10)])
        for bad, why in ((b"", "not an MPC3000 SND"), (b"\x01\x01" + good[2:], "not an MPC3000 SND"),
                         (good[:-1], "frames"), (good + b"\0\0", "frames"),
                         (good[:21] + b"\x02" + good[22:], "stereo byte"),
                         (snd("X", [[]]), "empty")):
            with self.assertRaisesRegex(sa.ConvertError, why):
                sa.read_snd(bad)

    def test_bad_markers_become_the_whole_sound(self) -> None:
        for start, end in ((0, 0), (10, 10), (11, 10), (0, 501)):
            s = sa.read_snd(snd("X", [sine(500)], start=start, end=end))
            self.assertEqual(sa.markers(s), (0, 500))
        self.assertEqual(sa.markers(sa.read_snd(snd("X", [sine(500)], start=1, end=500))), (1, 500))


class FloppyTests(Fixture):
    def test_empty_floppies_match_akaiutil(self) -> None:
        for s3000, digest in ((False, AKAIUTIL_EMPTY_S1000_HD), (True, AKAIUTIL_EMPTY_S3000_HD)):
            img = sa.AkaiFloppy(sa.HD, s3000).image()
            self.assertEqual(len(img), 1_638_400)
            self.assertEqual(hashlib.sha256(img).hexdigest(), digest)

    def test_layout(self) -> None:
        disk = sa.AkaiFloppy(sa.HD, False, "my disk")
        disk.add("A", b"\x03" + b"\0" * 2047)          # two blocks
        disk.add("B", b"\x03")
        img = disk.image()
        self.assertEqual(img[0:24], sa.encode_name("A") + b"\x20" * 4 + b"\x73\x00\x08\x00\x05\x00\x28\x04")
        self.assertEqual(img[24 + 16:24 + 22], b"\x73\x01\x00\x00\x07\x00")
        self.assertEqual(struct.unpack_from("<8H", img, 0x600), (0x4000,) * 5 + (6, 0xC000, 0xC000))
        self.assertEqual(sa.decode_name(img[0x1280:0x128C]), "MY DISK")
        s3 = sa.AkaiFloppy(sa.HD, True)
        s3.add("A", b"\x03")
        img = s3.image()
        self.assertEqual(img[0x10], 0xFF)
        self.assertEqual(img[0x1400 + 16:0x1400 + 24], b"\xF3\x01\x00\x00\x11\x00\x00\x11")
        self.assertEqual(struct.unpack_from("<18H", img, 0x600), (0x4000,) * 17 + (0xC000,))

    def test_dd_geometry(self) -> None:
        disk = sa.AkaiFloppy(sa.DD)
        self.assertEqual((disk.density.size, disk.capacity, disk.density.label_offset), (819_200, 796, 0xC40))
        disk.add("X", b"\x03")
        label, _, files = sa.read_floppy(disk.image())
        self.assertEqual((label, files[0][0].start), ("NOT NAMED", 4))

    def test_full_disk_and_directory(self) -> None:
        disk = sa.AkaiFloppy()
        disk.add("BIG", bytes(disk.capacity * 1024))
        self.assertEqual(disk.free_blocks, 0)
        with self.assertRaisesRegex(sa.ConvertError, "KiB free"):
            disk.add("MORE", b"\x03")
        disk = sa.AkaiFloppy()
        for i in range(64):
            disk.add(f"S{i}", b"\x03")
        with self.assertRaisesRegex(sa.ConvertError, "directory full"):
            disk.add("S64", b"\x03")
        disk = sa.AkaiFloppy()
        disk.add("A", b"\x03")
        with self.assertRaisesRegex(sa.ConvertError, "already"):
            disk.add("A", b"\x03")

    def test_reader_rejects_broken_chains(self) -> None:
        disk = sa.AkaiFloppy()
        disk.add("A", b"\x03" * 3000)
        img = bytearray(disk.image())
        struct.pack_into("<H", img, 0x600 + 2 * 6, 5)       # block 6 points back into the header
        with self.assertRaisesRegex(sa.ConvertError, "broken FAT chain"):
            sa.read_floppy(bytes(img))
        with self.assertRaisesRegex(sa.ConvertError, "not an Akai"):
            sa.read_floppy(b"\0" * 1_474_560)


class ConvertTests(Fixture):
    def sounds(self) -> dict[str, bytes]:
        return {"KICK.SND": snd_bytes("Kick_01", sine441(), tune=-25),
                "PAD.SND": snd_bytes("Stereo Pad!", stereo1(), start=10, end=30000, tune=120),
                "HIT.SND": snd_bytes("", [sine(441)], start=0, end=441)}

    def test_350_loads_exactly_what_was_converted(self) -> None:
        paths = [self.put(k, v) for k, v in self.sounds().items()]
        [disk] = sa.convert(paths)
        loaded = {s.name: s for s in load_350(disk.image())}
        self.assertEqual(sorted(loaded), ["HIT", "KICK 01", "STEREO PAD"])
        for path, name in zip(paths, ("KICK 01", "STEREO PAD", "HIT")):
            src = sa.read_snd(path.read_bytes())
            got = loaded[name]
            self.assertEqual(got.planes, src.planes, name)
            self.assertEqual((got.start, got.end, got.tune), (src.start, src.end, src.tune), name)
        self.assertEqual({s.name: s.planes for s in sa.extract(disk.image())},
                         {k: v.planes for k, v in loaded.items()})

    def test_s3000_floppy_shifts_the_350_load_by_21_words(self) -> None:
        path = self.put("KICK.SND", snd("KICK", sine441()))
        [disk] = sa.convert([path], s3000=True)
        [got] = load_350(disk.image())
        src = sa.read_snd(path.read_bytes()).planes[0]
        self.assertEqual(got.planes[0], bytes(42) + src[:-42])
        [own] = sa.extract(disk.image())
        self.assertEqual(own.planes[0], src)

    def test_dd_round_trip(self) -> None:
        paths = [self.put(k, v) for k, v in self.sounds().items()]
        [disk] = sa.convert(paths, sa.DD)
        self.assertEqual(len(disk.image()), 819_200)
        self.assertEqual(sorted(s.name for s in load_350(disk.image())), ["HIT", "KICK 01", "STEREO PAD"])

    def test_duplicate_names_get_numbers(self) -> None:
        a = self.put("A.SND", snd("Same", [sine(100)]))
        b = self.put("B.SND", snd("same", [sine(200)]))
        c = self.put("C.SND", snd("PAIR NAME LONG", stereo1()))
        d = self.put("D.SND", snd("PAIR NAME LONG", stereo1()))
        [disk] = sa.convert([a, b, c, d])
        self.assertEqual([e.name for e in disk.entries],
                         ["SAME", "SAME1", "PAIR NAME -L", "PAIR NAME -R", "PAIR NAME1-L", "PAIR NAME1-R"])
        self.assertEqual(sorted(s.name for s in load_350(disk.image())),
                         ["PAIR NAME", "PAIR NAME1", "SAME", "SAME1"])

    def test_overflow_starts_a_new_disk(self) -> None:
        frames = 400 * 1024 // 2                           # 400 KiB + header per sound
        paths = [self.put(f"S{i}.SND", snd(f"S{i}", [[i] * frames])) for i in range(5)]
        disks = sa.convert(paths)
        self.assertEqual([[e.name for e in d.entries] for d in disks], [["S0", "S1", "S2"], ["S3", "S4"]])
        for disk in disks:
            for s in load_350(disk.image()):
                i = int(s.name[1:])
                self.assertEqual(s.planes[0], struct.pack("<h", i) * frames)

    def test_too_big_for_one_floppy(self) -> None:
        fits = self.put("FITS.SND", snd("FITS", [[0] * (1595 * 512 - 75)]))     # 1595 KiB with header
        self.assertEqual(sa.convert([fits])[0].free_blocks, 0)
        path = self.put("LONG.SND", snd("LONG", [[0] * (1595 * 512 - 74)]))
        with self.assertRaisesRegex(sa.ConvertError, "does not fit"):
            sa.convert([path])
        s3 = self.put("S3.SND", snd("S3", [[0] * (1583 * 512 - 95)]))
        with self.assertRaisesRegex(sa.ConvertError, "does not fit"):
            sa.convert([s3], s3000=True)

    def test_cli(self) -> None:
        paths = [str(self.put(k, v)) for k, v in self.sounds().items()]
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(sa.main([*paths, "-o", str(self.dir / "o" / "D.img"), "--label", "drums"]), 0)
            self.assertEqual(sa.main(["--list", str(self.dir / "o" / "D.img")]), 0)
            self.assertEqual(sa.main(["--extract", str(self.dir / "o" / "D.img"), "-o", str(self.dir / "x")]), 0)
            self.assertEqual(sa.main([*paths, "-o", str(self.dir / "o" / "D.hfe")]), 0)
        self.assertIn("S1000 floppy 'DRUMS', 4 file(s)", out.getvalue())
        back, src = sa.read_snd((self.dir / "x" / "KICK_01.SND").read_bytes()), sa.read_snd(self.sounds()["KICK.SND"])
        self.assertEqual((back.name, back.planes, back.start, back.end, back.tune),
                         ("KICK 01", src.planes, src.start, src.end, src.tune))
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(sa.main([str(self.put("BAD.SND", b"junk")), "-o", str(self.dir / "B.img")]), 1)
        self.assertIn("not an MPC3000 SND", err.getvalue())
        self.assertFalse((self.dir / "B.img").exists())


def decode_hfe(data: bytes) -> bytes:
    """Sectors of an HFE image, by MFM sync search; checks every ID and data CRC."""
    assert data[:8] == b"HXCPICFE" and data[11] == 0
    cyls, heads, rate = data[9], data[10], struct.unpack_from("<H", data, 12)[0]
    spt = {500: 10, 250: 5}[rate]
    img = bytearray(cyls * heads * spt * 1024)
    found = set()
    for cyl in range(cyls):
        off, length = struct.unpack_from("<HH", data, 512 + 4 * cyl)
        raw = data[off * 512:off * 512 + -(-length // 512) * 512]
        for head in range(heads):
            side = b"".join(raw[i + 256 * head:i + 256 * head + 256] for i in range(0, len(raw), 512))
            bits = "".join(f"{b:08b}"[::-1] for b in side[:length // 2])
            pos, idam = 0, None
            while (pos := bits.find("0100010010001001" * 3, pos)) >= 0:
                pos += 48
                field = bytes(int(bits[pos + 16 * i + 1:pos + 16 * i + 16:2], 2) for i in range(1031))
                if field[0] == 0xFE:
                    assert sa._crc16(b"\xA1\xA1\xA1" + field[:7]) == 0
                    idam = field[1:5]
                elif field[0] == 0xFB:
                    assert idam is not None and idam[0] == cyl and idam[1] == head and idam[3] == 3
                    assert sa._crc16(b"\xA1\xA1\xA1" + field[:1027]) == 0
                    block = (cyl * heads + head) * spt + idam[2] - 1
                    img[block * 1024:(block + 1) * 1024] = field[1:1025]
                    found.add(block)
                    idam = None
    assert len(found) == len(img) // 1024, len(found)
    return bytes(img)


class HfeTests(unittest.TestCase):
    def test_hfe_holds_every_sector(self) -> None:
        for density in (sa.HD, sa.DD):
            disk = sa.AkaiFloppy(density)
            disk.add("X", bytes(range(256)) * 40)
            img = disk.image()
            data = sa.hfe(img)
            self.assertEqual(struct.unpack_from("<H", data, 12)[0], density.hfe_rate)
            self.assertEqual(decode_hfe(data), img)


@unittest.skipUnless(os.environ.get("AKAIUTIL"), "set AKAIUTIL to an akaiutil binary for the cross-check")
class AkaiutilTests(Fixture):
    """akaiutil (sourceforge.net/projects/akaiutil) reads our disks and exports the PCM unchanged."""

    def test_akaiutil_exports_the_source_pcm(self) -> None:
        paths = [self.put("KICK.SND", snd("Kick", sine441())), self.put("PAD.SND", snd("Pad", stereo1()))]
        for s3000 in (False, True):
            work = self.dir / f"s{s3000}"
            work.mkdir()
            [disk] = sa.convert(paths, s3000=s3000)
            (work / "d.img").write_bytes(disk.image())
            run = subprocess.run([os.environ["AKAIUTIL"], "-r", "d.img"], cwd=work, input="sample2wavall\nq\n",
                                 capture_output=True, text=True, timeout=60)
            self.assertIn("exported 3 file(s)", run.stdout)
            kick, pad = (sa.read_snd(p.read_bytes()) for p in paths)
            for name, pcm in (("KICK", kick.planes[0]), ("PAD       -L", pad.planes[0]),
                              ("PAD       -R", pad.planes[1])):
                with wave.open(str(work / f"{name}.wav")) as w:
                    self.assertEqual((w.getframerate(), w.getnchannels()), (44100, 1))
                    self.assertEqual(w.readframes(w.getnframes()), pcm)


if __name__ == "__main__":
    unittest.main()
