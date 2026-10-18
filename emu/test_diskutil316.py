"""PMONEY disk utilities (mods/diskutil316.inc), OS 3.16: Vailixi H6, F15/F16, F11, F14.

    python3 -m unittest emu.test_diskutil316 -v

Raw MAME SCSI hard disks (512-byte sectors; -scsi:N harddisk -hard / -hard1
-hard2), boot snapshots off (their key ignores the SCSI devices).  Disk 9 3
(Format Hard Disk) with AUTO finds unit 0.  Per BIOS set (h.bios316_sets()):

Stage 1, from blank or pattern-filled disks:
  - hyb1 / hyb5: <Fast>, <MPC + PC>, option 1 (40 MiB: 5 volumes) or option 5
    (80 MiB: 2 volumes of 65,535 sectors), <Partition now>.  The disk equals
    the layout model below sector for sector (every other sector stays zero);
    mtools reads every volume; on a host copy of the option-5 disk mcopy
    stores a 33,392,558-byte file in volume A (F16);
  - std: <Fast>, <MPC only>, the stock count page's <Do it>; std_stock: the
    same keys (no layout page) on the unmodified M3K316.SYS.  The two disks are
    equal apart from bytes 1Ch-1Fh of each boot sector (uninitialised stack);
  - cancel / zero_cancel: a mode key on the confirmation page; the disk is
    unchanged;
  - zero: <Zero>, <Zero now>: every sector is zero, then the layout page;
    zero_stop: <Stop> leaves a zeroed prefix and the rest as it was;
  - src: a 9 MiB option-1 disk (one volume) with PARAMS.PAR saved by PMONEY.

Stage 2:
  - copy: src (unit 0) onto a 16,065-sector blank (unit 1, smaller than the
    source disk but not than its layout): the target equals the source's
    first 16,065 sectors; copy_small: a 16,064-sector target is refused;
    copy_same: source = target is refused; copy_cancel; copy_stop: a prefix
    is copied, the rest stays zero; copy_active: unit 1 onto the active unit 0,
    (the std disk, mounted at boot with 2 stock partitions), which is
    rescanned: PMONEY then sees the copied hybrid volume;
  - mount1 / mount5 / mount_vx: a reboot with the hyb1 / hyb5 disk or a
    Vailixi-built model disk: the partitions are mounted (count, table,
    geometry), Select disk reaches the last one, Free is the volume's free
    space; a PMONEY save lands in volume A and mtools reads it back;
  - f16: on a 32 MB board, the hyb5 disk with a 16,696,260-frame sound
    (33,392,558 bytes) in volume A: PMONEY loads it, saves it into volume B,
    and the saved file has every frame of the original;
  - zero_leave: the src disk, mounted by the boot scan (1 volume); <Zero>,
    <Zero now>, then a mode key (Disk) on the layout page and Disk 6 <Do it>.
    A successful zero rescans: no partition is left mounted (PART_COUNT 0,
    read by emu/lua/dg_words316.lua), Disk offers no "Select disk", Save
    Parameters offers no SCSI DISK, and the save does not touch the zeroed
    disk.  Before the fix the old mount survived and PARAMS.PAR was written
    into the zeroed disk (audit 2026-10-16 F-2, MAME);
  - stock: the unmodified M3K316.SYS with the hyb5 disk: Disk 9 4 <Make
    active> searches until the time-out and shows box FF48 ("No SCSI device
    was found"), as for a blank disk; no partition is mounted and the disk
    stays byte-identical.
"""
from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import unittest

from emu import harness as h
from emu.mpc3k import run
from emu.panel import write_smf
from emu.snd import disk as floppy
from emu.test_scsi316 import dg_bytes, dg_env, fat_file

RUNS = h.BUILD / "emu" / "diskutil-tests"
CYL = 16065
MiB = 1 << 20
BIG_SND = 33_392_558            # F16: the largest sound, in one file

# DGROUP words read at each probe time (3.16 offsets, mods/profile_316.inc).
PART_COUNT, DISK_LAYOUT, SCSI_ACTIVE, PART_TABLE = 0x79AA, 0x79A4, 0x79A6, 0x79AF
PART_GEOMETRY = 0x79A8          # heads (lo), sectors/track (hi)
WORDS = [PART_COUNT, DISK_LAYOUT, SCSI_ACTIVE, PART_GEOMETRY] + [PART_TABLE + 2 * i for i in range(12)]


# --------------------------------------------------------------------------- layout model

def hybrid_layout(cap: int, n: int, variant: str = "pmoney") -> tuple[dict[int, bytes], dict]:
    """Sectors (LBA -> 512 bytes) of a hybrid layout, option n, on `cap` sectors.

    Vailixi 3.50 D3CB:0095 mode 1 (spec port/diskutil 5.2); 'pmoney' applies
    D2 (32 sectors/cluster for n >= 4), D3 (FAT sector 0 = F8 FF FF) and
    PMONEY's OEM name, serial and labels.  Sectors not listed are zero."""
    stride = n * CYL
    c = min(cap // stride, 26)
    assert c >= 1
    pm = variant == "pmoney"
    size = 0xFFFF if n == 5 else stride - 63
    V = [126] + [k * stride + 63 for k in range(1, c)]
    E = [63] + [k * stride for k in range(1, c)]
    spc = 32 if (n == 5 or (pm and n >= 4)) else 16
    secs: dict[int, bytes] = {}

    def sig(b):
        b[0x1B8:0x1BC] = bytes([0xCA, 0xFE, 0x20, 0x07])
        b[0x1FE:0x200] = b"\x55\xaa"
    for i in range(c):
        label = (b"PMONEY-PT-" if pm else b"MPC-PART--") + bytes([65 + i])
        b = bytearray(512)
        b[0:3] = b"\xeb\x3c\x90"
        b[3:11] = b"PMONEY  " if pm else b"MPC-3000"
        total = size - 63 if (i == 0 and n < 5) else size
        struct.pack_into("<HBHBHHBHHHII", b, 0x0B, 512, spc, 1, 2, 512, total, 0xF8, 11, 16, 16, V[i], 0)
        b[0x24:0x27] = b"\x82\x00\x29"
        b[0x27:0x2B] = bytes([i + 1, 0, 0x4D, 0x50]) if pm else bytes([i + 1, 0, 0xFE, 0xCA])
        b[0x2B:0x36] = label
        b[0x36:0x3E] = b"FAT12   "
        b[0x1FE:0x200] = b"\x55\xaa"
        secs[V[i]] = bytes(b)
        for si in range(54):
            f = bytearray(512)
            if si in (0, 11):
                fat0 = b"\xf8\xff\xff" if pm else b"\xf8\xff\xff\xff\xff"
                f[0:len(fat0)] = fat0
            if si == 22:
                f[0:11] = label
                f[11] = 8
            secs[V[i] + 1 + si] = bytes(f)
        e = bytearray(512)
        sig(e)
        e[0x18] = e[0x1A] = 0x10
        for k, v in enumerate(V):
            struct.pack_into("<I", e, 0x80 + 4 * k, v)
        ln = stride - 126 if i == 0 else stride - 63
        e[0x1BE:0x1CE] = bytes([0, 2 if i == 0 else 1, 1, (i * n) & 0xFF, 1, 0xFE, 0x3F,
                                ((i + 1) * n - 1) & 0xFF]) + struct.pack("<II", 63, ln)
        if i < c - 1:
            e[0x1CE:0x1DE] = bytes([0, 0, 1, ((i + 1) * n) & 0xFF, 5, 0xFE, 0x3F,
                                    ((i + 2) * n - 1) & 0xFF]) + struct.pack("<II", E[i + 1] - 63, stride)
        secs[E[i]] = bytes(e)
    m = bytearray(512)
    sig(m)
    ext = c * stride - 63
    m[0x1BE:0x1CE] = bytes([0, 1, 1, 0, 5, 0xFE, 0x3F, ((ext // 63 // 254) - 1) & 0xFF]) + struct.pack("<II", 63, ext)
    secs[0] = bytes(m)
    return secs, {"count": c, "V": V, "E": E, "spc": spc, "size": size, "extent": c * stride}


def model_image(cap: int, n: int, variant: str) -> bytes:
    img = bytearray(cap * 512)
    for lba, b in hybrid_layout(cap, n, variant)[0].items():
        img[lba * 512:(lba + 1) * 512] = b
    return bytes(img)


def pattern(sectors: int) -> bytes:
    """Every sector holds its LBA (dword) 128 times: nothing in it is zero."""
    return b"".join(struct.pack("<I", 0x5A000000 | lba) * 128 for lba in range(sectors))


def sector(image: bytes, lba: int) -> bytes:
    return image[lba * 512:(lba + 1) * 512]


def mtools(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=True,
                          env={"MTOOLS_SKIP_CHECK": "1", "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"}).stdout


def scsi(*paths) -> list[str]:
    if len(paths) == 1:
        return ["-scsi:0", "harddisk", "-hard", str(paths[0])]
    out = []
    for i, p in enumerate(paths):
        out += [f"-scsi:{i}", "harddisk", f"-hard{i + 1}", str(p)]
    return out


def words(run_dir, ds: int) -> list[dict[int, int] | None]:
    """ram_words.log: one {offset: word} per probe time, or None where the probe's
    DS sample (the most frequent DS since the last time) was not DGROUP `ds`."""
    snaps = []
    for line in (run_dir / "ram_words.log").read_text().splitlines():
        if line.startswith("@"):
            snaps.append({} if f"DS={ds:04X}" in line else None)
        elif snaps[-1] is not None:
            off, val = line.split()
            snaps[-1][int(off, 16)] = int(val, 16)
    return snaps


def text(screen: dict) -> str:
    return "\n".join(screen["rows"]).replace(".", " ")


# --------------------------------------------------------------------------- panel timelines

FORMAT = h.taps((h.CANCEL_SCSI_316, "soft4"), (35, "disk"), (36, "9"), (37.5, "3"), (40, "soft1"))


def hybrid(n: int, confirm: str = "soft1") -> list:
    return FORMAT + h.taps((42, "soft2"), (44, "soft2"), (46, str(n)), (48, confirm))


SAVE_PARAMS = h.taps((52, "disk"), (53.5, "6"), (55.5, "soft1"))
COPY_MENU = h.taps((h.CANCEL_SCSI_316, "soft4"), (35, "disk"), (36, "9"), (37.5, "5"))
# Mount runs do not cancel the boot scan: it finds unit 0 and mounts it (~39 s).
MOUNT = h.taps((40, "disk"), (41.5, "0"))
MOUNT_SAVE = h.taps((47, "disk"), (48.5, "6"), (50.5, "soft1"))
# F16: Disk 7 <Load> of the 32 MB sound from volume A (~100 s), Select disk B,
# Disk 3 <Do it> saves it there (~75 s).
F16_EVENTS = (h.taps((40, "disk"), (40.8, "7"), (44, "soft1"), (150, "disk"), (151.5, "0")) + h.dial(1, 153.0)
              + h.taps((154.5, "soft1"), (156, "disk"), (157.5, "3"), (160, "soft1")))
F16_TIMES = [148.0, 154.0, 159.0, 165.0, 245.0]
F16_FRAMES = 16_696_260         # 33,392,558-byte SND


def big_sound() -> bytes:
    """A mono SND of F16_FRAMES frames (header 01 02 + the 36-byte record), byte ramp PCM."""
    record = (b"BIGSOUND".ljust(17, b"\0") + struct.pack("<BbB", 100, 0, 0)
              + struct.pack("<4I", 0, F16_FRAMES, F16_FRAMES, 0))
    pcm = (bytes(range(256)) * (F16_FRAMES * 2 // 256 + 1))[:F16_FRAMES * 2]
    return b"\x01\x02" + record + pcm
# Cancel the boot scan (an unrecognised disk is searched until the time-out),
# then Disk 9 4 <Make active>: a scan that mounts unit 0 if it can.
MAKE_ACTIVE = h.taps((h.CANCEL_SCSI_316, "soft4"), (35, "disk"), (36, "9"), (37.5, "4"), (39, "soft1"))
# zero_leave: the boot scan mounts the src disk (~39 s); Disk 9 3, AUTO (unit 0),
# <Zero>, <Zero now> (9 MiB: done well before 66 s); then Disk (a mode key) on
# the layout page, 6 (Save Parameters), <Do it>.
ZERO_LEAVE = h.taps((40, "disk"), (41, "9"), (42.5, "3"), (45, "soft1"), (47, "soft3"), (49, "soft1"),
                    (70, "disk"), (71.5, "6"), (74.5, "soft1"))
ZERO_LEAVE_TIMES = [44.0, 48.0, 69.0, 71.0, 74.0, 80.0]


class DiskUtil316(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.res: dict = {}
        cls.disks: dict = {}
        stage1, stage2 = {}, {}
        profiles = [h.payload("316", bios) for bios in h.bios316_sets()]
        for p in profiles:
            runs = RUNS / p.label
            if runs.exists():
                shutil.rmtree(runs)
            runs.mkdir(parents=True)

            def job(name, size, events, times, *, fill=None, stock=False):
                stage1[(p.label, name)] = (p, runs, name, [(f"{name}.hd", fill if fill is not None else bytes(size))],
                                           events, times, stock, {})
            job("hyb1", 40 * MiB, hybrid(1), [41.0, 43.0, 45.0, 47.0, 55.0])
            job("hyb5", 80 * MiB, hybrid(5), [45.0, 47.0, 55.0])
            job("std", 40 * MiB, FORMAT + h.taps((42, "soft2"), (44, "soft1"), (46, "soft1")), [43.0, 45.0, 55.0])
            job("std_stock", 40 * MiB, FORMAT + h.taps((42, "soft2"), (45, "soft1")), [44.0, 55.0], stock=True)
            job("cancel", 0, hybrid(1, confirm="main_screen"), [47.0, 50.0], fill=pattern(80 * 1024))
            job("zero", 0, FORMAT + h.taps((42, "soft3"), (44, "soft1")), [43.0, 45.0, 60.0], fill=pattern(18 * 1024))
            job("zero_stop", 0, FORMAT + h.taps((42, "soft3"), (44, "soft1"), (46, "soft1")), [45.5, 50.0],
                fill=pattern(80 * 1024))
            job("zero_cancel", 0, FORMAT + h.taps((42, "soft3"), (44, "main_screen")), [43.0, 47.0],
                fill=pattern(18 * 1024))
            job("src", 0, hybrid(1) + SAVE_PARAMS, [47.0, 60.0], fill=pattern(18 * 1024))

        def execute(key, job):
            p, runs, name, disks, events, times, stock, kwargs = job
            paths = []
            for fname, data in disks:
                path = runs / fname
                if isinstance(data, str):
                    shutil.copy(runs / data, path)
                else:
                    path.write_bytes(data)
                paths.append(path)
            before = [path.read_bytes() for path in paths]
            if stock:
                img = floppy(f"{p.label}-diskutil-{name}", [(h.M3K316, "STARTUP.SYS")])
                screens = run(p.bios, times, runs / name, floppy=img, panel=write_smf(runs / f"{name}.mid", events),
                              rompath=p.rompath, extra=scsi(*paths), words=WORDS)
            else:
                kwargs = dict(kwargs)
                screens = h.run_case(p, runs, name, times=times, events=events, parts=kwargs.pop("parts", []),
                                     snapshot=False, extra=scsi(*paths), words=WORDS, **kwargs)
            return {"screens": screens, "before": before, "after": [path.read_bytes() for path in paths],
                    # stock M3K316.SYS runs where the EPROM loaded it; PMONEY at 6900 on every set
                    "words": words(runs / name, (p.loader_segment + h.DGROUP_316) & 0xFFFF if stock
                                   else p.dgroup_segment)}

        cls.res.update(h.run_parallel(stage1, execute))

        for p in profiles:
            runs = RUNS / p.label
            # Vailixi-built model disk for mount_vx (40 MiB, option 1: 5 volumes).
            (runs / "vx_model.hd").write_bytes(model_image(80 * 1024, 1, "vailixi"))
            # F16: the hyb5 disk with a 16,696,260-frame sound in volume A, 32 MB board.
            big = runs / "BIGSOUND.SND"
            big.write_bytes(big_sound())
            shutil.copy(runs / "hyb5.hd", runs / "f16_src.hd")
            mtools("mcopy", "-i", f"{runs / 'f16_src.hd'}@@{126 * 512}", str(big), "::BIGSOUND.SND")

            def job2(name, disks, events, times, stock=False, **kwargs):
                stage2[(p.label, name)] = (p, runs, name, disks, events, times, stock, kwargs)
            src = "src.hd"
            job2("copy", [("copy_a.hd", src), ("copy_b.hd", bytes(CYL * 512))],
                 COPY_MENU + h.taps((40, "soft1"), (42, "soft1")), [37.2, 39.0, 41.0, 44.0, 80.0])
            job2("copy_small", [("small_a.hd", src), ("small_b.hd", bytes((CYL - 1) * 512))],
                 COPY_MENU + h.taps((40, "soft1")), [42.0])
            job2("copy_same", [("same_a.hd", src), ("same_b.hd", bytes(CYL * 512))],
                 COPY_MENU + h.dial(1, 39.0) + h.taps((40.5, "soft1")), [40.0, 42.0])
            job2("copy_cancel", [("cancel_a.hd", src), ("cancel_b.hd", bytes(CYL * 512))],
                 COPY_MENU + h.taps((40, "soft1"), (42, "main_screen")), [41.0, 45.0])
            job2("copy_stop", [("stop_a.hd", src), ("stop_b.hd", bytes(CYL * 512))],
                 COPY_MENU + h.taps((40, "soft1"), (42, "soft1"), (45, "soft1")), [44.0, 48.0])
            # Unit 0: the std disk (stock layout, 2 partitions), mounted by the boot scan.
            job2("copy_active", [("active_a.hd", "std.hd"), ("active_b.hd", src)],
                 h.taps((40, "disk"), (41, "9"), (42.5, "5")) + h.dial(1, 44.0) + h.taps((45, "down"))
                 + h.dial(-1, 46.0) + h.taps((47.5, "soft1"), (49.5, "soft1"), (85, "disk"), (86.5, "6")),
                 [43.5, 47.0, 49.0, 84.0, 89.0])
            job2("f16", [("f16.hd", "f16_src.hd")], F16_EVENTS, F16_TIMES, board_mb=32)
            job2("mount1", [("mount1.hd", "hyb1.hd")], MOUNT + h.dial(4, 43.0) + MOUNT_SAVE, [42.5, 45.0, 50.0, 58.0])
            job2("mount5", [("mount5.hd", "hyb5.hd")], MOUNT + h.dial(1, 43.0) + MOUNT_SAVE, [42.5, 45.0, 50.0, 58.0])
            job2("mount_vx", [("mount_vx.hd", "vx_model.hd")], MOUNT + h.dial(4, 43.0) + h.taps((47, "disk"), (48.5, "6")),
                 [42.5, 45.0, 50.0])
            job2("stock", [("stock.hd", "hyb5.hd")], MAKE_ACTIVE, [41.0, 84.0], stock=True)
            job2("zero_leave", [("zero_leave.hd", src)], ZERO_LEAVE, ZERO_LEAVE_TIMES,
                 parts=["dg_words"], env=dg_env([PART_COUNT, DISK_LAYOUT]))

        cls.res.update(h.run_parallel(stage2, execute))

    # ----------------------------------------------------------------------- helpers

    def labels(self) -> list[str]:
        labels = sorted({label for label, _ in self.res})
        self.assertTrue(labels, "no BIOS set ran")
        return labels

    def get(self, label: str, name: str) -> dict:
        return self.res[(label, name)]

    def assert_model(self, image: bytes, n: int) -> dict:
        secs, info = hybrid_layout(len(image) // 512, n)
        for lba, b in secs.items():
            self.assertEqual(sector(image, lba), b, f"LBA {lba}")
        listed = set(secs)
        nonzero = [lba for lba in range(len(image) // 512) if lba not in listed and any(sector(image, lba))]
        self.assertEqual(nonzero, [])
        return info

    # ----------------------------------------------------------------------- F15: create

    def test_hybrid_option1_pages_and_layout(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "hyb1")
                s = r["screens"]
                self.assertIn("<Slow>     <Fast>     <Zero>", s[0]["rows"][7])
                self.assertIn("Choose the partition layout:", text(s[1]))
                self.assertIn("<MPC only> <MPC + PC>", s[1]["rows"][7])
                self.assertIn("PC-Readable Partitions", s[2]["rows"][0])
                rows = text(s[2]).splitlines()
                self.assertTrue(rows[1].startswith("1   5 volume(s) of  8 MB"), rows[1])
                self.assertTrue(rows[5].startswith("5   1 volume(s) of 32 MB"), rows[5])
                self.assertIn("Select option:", rows[7])
                self.assertIn("SCSI unit 0: 5 volume(s) of 8 MB", text(s[3]))
                self.assertIn("<Partition now>", s[3]["rows"][7])
                self.assertIn("Select option:", s[4]["rows"][7])          # back to the Disk page
                for row in s[0]["rows"] + s[1]["rows"] + s[2]["rows"] + s[3]["rows"]:
                    self.assertLessEqual(len(row), 40)
                info = self.assert_model(r["after"][0], 1)
                self.assertEqual(info["count"], 5)
                self.assertEqual(r["words"][-1][PART_COUNT] & 0xFF, 5)   # the rescan mounted it

    def test_hybrid_option5_layout_and_32mb_file(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "hyb5")
                self.assertIn("SCSI unit 0: 2 volume(s) of 32 MB", text(r["screens"][1]))
                image = r["after"][0]
                info = self.assert_model(image, 5)
                self.assertEqual((info["count"], info["V"], info["spc"]), (2, [126, 80388], 32))
                host = RUNS / label / "hyb5_host.hd"
                host.write_bytes(image)
                big = RUNS / label / "BIG.SND"
                big.write_bytes(hashlib.sha256(b"F16").digest() * (BIG_SND // 32) + bytes(BIG_SND % 32))
                for v in info["V"]:
                    self.assertIn("No files", mtools("mdir", "-i", f"{host}@@{v * 512}", "::"))
                mtools("mcopy", "-i", f"{host}@@{126 * 512}", str(big), "::BIG.SND")
                listing = mtools("mdir", "-i", f"{host}@@{126 * 512}", "::")
                self.assertRegex(listing, r"BIG\s+SND\s+33\s?392\s?558")
                self.assertRegex(listing, r"114\s?688 bytes free")
                back = RUNS / label / "BIG.back"
                mtools("mcopy", "-o", "-i", f"{host}@@{126 * 512}", "::BIG.SND", str(back))
                self.assertEqual(back.read_bytes(), big.read_bytes())

    def test_option1_volumes_read_by_mtools(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                image = self.get(label, "hyb1")["after"][0]
                host = RUNS / label / "hyb1_host.hd"
                host.write_bytes(image)
                for i, v in enumerate(hybrid_layout(len(image) // 512, 1)[1]["V"]):
                    out = mtools("mdir", "-i", f"{host}@@{v * 512}", "::")
                    self.assertIn(f"PMONEY-PT-{chr(65 + i)}", out)
                    self.assertIn("No files", out)

    def test_standard_path_is_the_stock_layout(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                pm, stock = self.get(label, "std"), self.get(label, "std_stock")
                self.assertIn("Enter number of partitions", text(pm["screens"][1]))
                self.assertIn("Enter number of partitions", text(stock["screens"][0]))
                a, b = pm["after"][0], stock["after"][0]
                self.assertEqual(sector(a, 0)[0x1FC:0x200], b"\x55\xaa\x55\xaa")
                starts = [struct.unpack_from("<I", a, 0x40 + 4 * k)[0] for k in range(26)]
                starts = starts[:1] + [s for s in starts[1:] if s]
                self.assertEqual(len(starts), 2)
                masked_a, masked_b = bytearray(a), bytearray(b)
                for s in starts:
                    masked_a[s * 512 + 0x1C:s * 512 + 0x20] = bytes(4)
                    masked_b[s * 512 + 0x1C:s * 512 + 0x20] = bytes(4)
                self.assertEqual(hashlib.sha256(masked_a).hexdigest(), hashlib.sha256(masked_b).hexdigest())
                self.assertTrue(any(a))

    def test_cancel_on_confirmation_writes_nothing(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                for name in ("cancel", "zero_cancel"):
                    r = self.get(label, name)
                    self.assertEqual(r["after"][0], r["before"][0], name)
                self.assertIn("<Partition now>", self.get(label, "cancel")["screens"][0]["rows"][7])
                self.assertIn("<Zero now>", self.get(label, "zero_cancel")["screens"][0]["rows"][7])

    # ----------------------------------------------------------------------- F14: <Zero>

    def test_zero_fills_then_layout_page(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "zero")
                s = r["screens"]
                self.assertIn("Zero Hard Disk", s[0]["rows"][0])
                self.assertIn("Every sector of SCSI unit 0 is set", text(s[0]))
                self.assertIn("<Zero now>", s[0]["rows"][7])
                self.assertIn("Zeroing sectors", text(s[1]))
                self.assertIn("<Stop>", s[1]["rows"][7])
                self.assertIn("Choose the partition layout:", text(s[2]))
                image = r["after"][0]
                n = len(image) // 512
                for lba in (0, 1, 63, 126, 4095, 4096, 9000, n // 2, n - 2, n - 1):
                    self.assertEqual(sector(image, lba), bytes(512), f"LBA {lba}")
                self.assertEqual(image, bytes(len(image)))

    def test_zero_then_leaving_the_layout_page_unmounts(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "zero_leave")
                s = r["screens"]
                ram = dg_bytes(RUNS / label / "zero_leave")
                mounted, *_, saved = (ram[t] for t in ZERO_LEAVE_TIMES)
                # Positive control: the boot scan had mounted the src disk's volume.
                self.assertEqual(mounted[PART_COUNT], 1)
                self.assertTrue(any(r["before"][0]))
                self.assertIn("Zero Hard Disk", s[1]["rows"][0])
                self.assertIn("Choose the partition layout:", text(s[2]))
                # The zero rescanned: nothing mounted from the layout page on.
                for t in ZERO_LEAVE_TIMES[2:]:
                    self.assertEqual(ram[t][PART_COUNT], 0, t)
                self.assertIn("Select option:", s[3]["rows"][7])         # the Disk page
                self.assertNotIn("Select disk", text(s[3]))
                self.assertIn("Save Parameters", s[4]["rows"][0])
                self.assertNotIn("SCSI DISK", text(s[4]))
                self.assertNotIn("SCSI DISK", text(s[5]))
                self.assertEqual(saved[PART_COUNT], 0)
                # The save went elsewhere: the zeroed disk is still all zero.
                self.assertEqual(r["after"][0], bytes(len(r["after"][0])))

    def test_zero_stop_leaves_a_prefix(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "zero_stop")
                before, after = r["before"][0], r["after"][0]
                n = len(after) // 512
                first = next(lba for lba in range(n) if sector(after, lba) != bytes(512))
                self.assertGreater(first, 0)
                self.assertLess(first, n)
                self.assertEqual(after[first * 512:], before[first * 512:])
                self.assertIn("Select option:", r["screens"][1]["rows"][7])     # back to the Disk page

    # ----------------------------------------------------------------------- F11: copier

    def test_copy_menu_and_copy(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "copy")
                s = r["screens"][1:]
                self.assertIn("Copy SCSI Disk", s[0]["rows"][0])
                self.assertIn("Copy from SCSI unit:0", s[0]["rows"][4])
                self.assertIn("Copy onto SCSI unit:1", s[0]["rows"][5])
                self.assertIn("Copy SCSI unit 0 onto unit 1?", text(s[1]))
                self.assertIn("All data on unit 1 is lost", text(s[1]))
                self.assertIn("<Copy now>", s[1]["rows"][7])
                self.assertIn("Copying sectors", text(s[2]))
                self.assertIn("Select option:", s[3]["rows"][7])
                src, dst = r["after"]
                self.assertEqual(src, r["before"][0])
                self.assertEqual(dst, src[:CYL * 512])
                self.assertIn("PARAMS", mtools("mdir", "-i", f"{RUNS / label / 'copy_b.hd'}@@{126 * 512}", "::"))

    def test_copy_menu_has_item5(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                rows = self.get(label, "copy")["screens"][0]["rows"]
                self.assertIn("Copy, Format, Other", rows[0])
                self.assertIn("4 SCSI status, make SCSI device active", rows[4].replace(".", " "))
                self.assertIn("5 Copy a SCSI disk to another", rows[5].replace(".", " "))
                self.assertIn("Select option:", rows[7])

    def test_copy_refusals(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                small = self.get(label, "copy_small")
                self.assertIn("The target disk is too small", small["screens"][0]["rows"][3].replace(".", " "))
                self.assertIn("Copy onto SCSI unit:1", small["screens"][0]["rows"][5])
                self.assertIn("<Back>", small["screens"][0]["rows"][7])
                self.assertEqual(small["after"], small["before"])
                same = self.get(label, "copy_same")
                self.assertIn("Copy from SCSI unit:1", same["screens"][0]["rows"][4])
                self.assertIn("Choose two different units", text(same["screens"][1]))
                self.assertEqual(same["after"], same["before"])
                cancel = self.get(label, "copy_cancel")
                self.assertIn("<Copy now>", cancel["screens"][0]["rows"][7])
                self.assertEqual(cancel["after"], cancel["before"])

    def test_copy_stop(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "copy_stop")
                src, dst = r["after"]
                n = len(dst) // 512
                first = next((lba for lba in range(n) if sector(dst, lba) != sector(src, lba)), n)
                self.assertGreater(first, 0)
                self.assertLess(first, n)
                self.assertEqual(dst[first * 512:], bytes(len(dst) - first * 512))
                self.assertIn("Select option:", r["screens"][1]["rows"][7])

    def test_copy_onto_the_active_unit_rescans(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "copy_active")
                s, w = r["screens"], r["words"]
                before = next(x for x in w[:3] if x is not None)
                self.assertEqual(before[SCSI_ACTIVE], 0)                 # unit 0 mounted at boot
                self.assertEqual((before[PART_COUNT] & 0xFF, before[DISK_LAYOUT] & 0xFF), (2, 1))
                self.assertIn("Copy from SCSI unit:0", s[0]["rows"][4])  # defaults: the active unit, the next
                self.assertIn("Copy onto SCSI unit:1", s[0]["rows"][5])
                self.assertIn("Copy from SCSI unit:1", s[1]["rows"][4])
                self.assertIn("Copy onto SCSI unit:0", s[1]["rows"][5])
                self.assertIn("Copy SCSI unit 1 onto unit 0?", text(s[2]))
                after = w[3]                                            # the copy's rescan
                self.assertEqual(after[PART_COUNT] & 0xFF, 1)
                self.assertEqual(after[DISK_LAYOUT] & 0xFF, 1)
                self.assertEqual(after[PART_TABLE], 126)
                dst, src = r["after"]
                self.assertEqual(dst[:CYL * 512], src[:CYL * 512])
                self.assertEqual(dst[CYL * 512:], r["before"][0][CYL * 512:])
                self.assertIn("Disk:SCSI DISK PART A", text(s[4]))
                self.assertRegex(text(s[4]), r"Free:\s*7928K")          # 992 clusters, PARAMS.PAR in one

    # ----------------------------------------------------------------------- H6: mount

    def assert_mounted(self, label: str, name: str, n: int, variant: str) -> dict:
        """Boot scan mounted the disk; Select disk reaches the last volume; Free is its free space."""
        r = self.get(label, name)
        image = r["before"][0]
        info = hybrid_layout(len(image) // 512, n, variant)[1]
        w = next(x for x in r["words"] if x is not None)
        self.assertEqual(w[PART_COUNT] & 0xFF, info["count"])
        self.assertEqual(w[DISK_LAYOUT] & 0xFF, 1)
        self.assertEqual(w[SCSI_ACTIVE], 0)
        self.assertEqual(w[PART_GEOMETRY], 0x1010)                      # heads 16, sectors/track 16
        table = [w[PART_TABLE + 4 * k] | w[PART_TABLE + 4 * k + 2] << 16 for k in range(min(info["count"], 3))]
        self.assertEqual(table, info["V"][:3])
        s = r["screens"]
        last = chr(64 + info["count"])
        self.assertIn("Select Disk", s[0]["rows"][0])
        self.assertIn("Disk:SCSI DISK PART A", text(s[0]))
        self.assertIn(f"Disk:SCSI DISK PART {last}", text(s[1]))       # the dial selects at once
        total = info["size"] - (63 if (n < 5 and info["count"] == 1) else 0)   # the last volume
        clusters = (total - 55) // info["spc"]                         # BIOS FS 0009:155B
        reserved = 0 if variant == "pmoney" else 2                      # Vailixi FAT F8 FF FF FF FF: clusters 2, 3
        self.assertIn(f"Disk:SCSI DISK PART {last}", text(s[2]))
        self.assertRegex(text(s[2]), rf"Free:\s*{(clusters - reserved) * info['spc'] // 2}K")
        return info

    def test_pmoney_mounts_its_layouts_after_reboot(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                for name, n in (("mount1", 1), ("mount5", 5)):
                    info = self.assert_mounted(label, name, n, "pmoney")
                    r = self.get(label, name)
                    image = r["after"][0]
                    v = info["V"][-1]                                   # PARAMS.PAR went to the last volume
                    params = fat_file(image[v * 512:], "PARAMS", "PAR")
                    self.assertIsNotNone(params, name)
                    self.assertEqual(image[(v + 1) * 512:(v + 12) * 512], image[(v + 12) * 512:(v + 23) * 512])
                    host = RUNS / label / f"{name}_host.hd"
                    host.write_bytes(image)
                    back = RUNS / label / f"{name}.par"
                    mtools("mcopy", "-o", "-i", f"{host}@@{v * 512}", "::PARAMS.PAR", str(back))
                    self.assertEqual(back.read_bytes(), params)
                    secs = hybrid_layout(len(image) // 512, n)[0]
                    changed = [lba for lba in range(len(image) // 512)
                               if sector(image, lba) != secs.get(lba, bytes(512))]
                    self.assertTrue(changed)
                    self.assertGreaterEqual(min(changed), v + 1, name)  # only the last volume was written

    def test_pmoney_mounts_vailixi_layout(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                self.assert_mounted(label, "mount_vx", 1, "vailixi")
                r = self.get(label, "mount_vx")
                self.assertEqual(r["after"], r["before"])

    def test_stock_316_sees_no_partitions_and_writes_nothing(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "stock")
                self.assertEqual(r["after"], r["before"])
                seen = [x for x in r["words"] if x is not None]
                self.assertTrue(seen)
                for w in seen:
                    self.assertEqual(w[PART_COUNT] & 0xFF, 0)
                    self.assertEqual(w[DISK_LAYOUT] & 0xFF, 0)
                # Code 5 (not an MPC or Akai disk): searched until the time-out, then box FF48,
                # as with a blank disk (spec U6, observed here in MAME).
                self.assertIn("Searching SCSI for hard disk", r["screens"][0]["rows"][7])
                self.assertIn("No SCSI device was found", text(r["screens"][1]))
                self.assertIn("FF48", r["screens"][1]["rows"][7])

    def test_f16_32mb_sound_load_and_save(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "f16")
                s = r["screens"]
                self.assertRegex(text(s[0]), r"Free\(snd\):\s*10K")         # loaded: 32,610K used; 26K before Input Thru's 16K ring
                self.assertIn("Disk:SCSI DISK PART B", text(s[1]))
                self.assertIn("Save a Sound", s[2]["rows"][0])
                self.assertRegex(text(s[2]), r"Disk:SCSI DISK PART B\s+Free:32736K")
                self.assertIn("Saving 'BIGSOUND SND'", text(s[3]))
                self.assertRegex(text(s[4]), r"Free:\s*112K")
                self.assertIn("<Do it>", s[4]["rows"][7])
                host = RUNS / label / "f16_host.hd"
                host.write_bytes(r["after"][0])
                back = RUNS / label / "BIGSOUND.back"
                mtools("mcopy", "-o", "-i", f"{host}@@{80388 * 512}", "::BIGSOUND.SND", str(back))
                saved, original = back.read_bytes(), big_sound()
                self.assertEqual(len(saved), BIG_SND)
                self.assertEqual(saved[38:], original[38:])                # every frame
                self.assertEqual(saved[:10], original[:10])                # 01 02, name
                self.assertEqual(saved[19:38 - 4], original[19:38 - 4])    # vol..length (+20h: wave address)
                self.assertEqual(r["after"][0][:80388 * 512], r["before"][0][:80388 * 512])   # volume A unchanged

    def test_src_fixture(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                r = self.get(label, "src")
                self.assertIn("SCSI unit 0: 1 volume(s) of 8 MB", text(r["screens"][0]))
                self.assertIsNotNone(fat_file(r["after"][0][126 * 512:], "PARAMS", "PAR"))


class LayoutModel(unittest.TestCase):
    """No MAME: the layout model's invariants (spec 5.3) over capacities 8 MiB .. 1 GiB."""

    def test_invariants(self) -> None:
        for cap in (16_384, 81_920, 163_840, 417_690, 1_000_000, 2_097_152):
            for n in range(1, 6):
                if cap < n * CYL:
                    continue
                secs, info = hybrid_layout(cap, n)
                self.assertLessEqual(info["extent"], min(cap, 1 << 21))
                for v in info["V"]:
                    b = secs[v]
                    spc, total, fat = b[0x0D], struct.unpack_from("<H", b, 0x13)[0], struct.unpack_from("<H", b, 0x16)[0]
                    self.assertLessEqual(total, 0xFFFF)
                    self.assertLessEqual((total - 55) // spc + 2, fat * 512 * 2 // 3, (cap, n))   # fits FAT12
                    self.assertLessEqual(v + total, info["extent"])
                m = secs[0]
                self.assertEqual(m[0x1FC:0x1FE], b"\0\0")                # not a stock MPC disk
                self.assertEqual((m[0x1C2], struct.unpack_from("<I", m, 0x1C6)[0]), (5, 63))


if __name__ == "__main__":
    unittest.main()
