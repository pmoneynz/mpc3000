"""PMONEY SCSI options (mods/scsi316.inc), OS 3.16: Vailixi F12/F13.

    python3 -m unittest emu.test_scsi316 -v

A 40 MiB raw SCSI hard disk (MAME -scsi:N harddisk -hard) is formatted once
per run by PMONEY's own Disk 9 3 page (AUTO, <Fast>, <MPC only> (the stock
layout; mods/diskutil316.inc), 2 partitions) and
copied per case.  Boot snapshots are off: their key ignores the SCSI device.

  - page: Disk 9 4 SCSI Status shows the two new rows, ON and OFF by default;
  - multi on/off: Save Parameters to partition A writes the same PARAMS.PAR
    (apart from the setting's own byte); with multi-sector OFF the SPC sees
    more SELECT commands (port A4h <- 24h) than with ON, and the directory
    read back under OFF lists the file;
  - reset on/off: the disk at SCSI ID 3, <Make active> rescans AUTO; with the
    reset ON the SPC init (port A2h <- C0h) runs after each failed probe.
"""
from __future__ import annotations

import shutil
import struct
import unittest
from collections import Counter

from emu import harness as h

RUNS = h.BUILD / "emu" / "scsi-tests"
DISK_MB = 40
BLOCK = 0x831B - 0x7C61 + 4          # PARAMS.PAR offset of the multi-sector byte (4-byte header)


def scsi(path, slot=0) -> list[str]:
    return [f"-scsi:{slot}", "harddisk", "-hard", str(path)]


def fixture(p: h.Profile):
    """A formatted disk: PMONEY's own Disk 9 3 (AUTO, <Fast>, <MPC only>, <Do it>)."""
    d = RUNS / p.label
    d.mkdir(parents=True, exist_ok=True)
    hd = d / "fixture.hd"
    blank = d / "blank.hd"
    blank.write_bytes(bytes(DISK_MB << 20))
    ev = h.taps((33.0, "soft4"), (35, "disk"), (36, "9"), (37.5, "3"), (40, "soft1"), (42, "soft2"), (44, "soft1"),
                (46, "soft1"))
    h.run_case(p, d, "format", times=[60.0], events=ev, parts=[], snapshot=False, extra=scsi(blank))
    shutil.move(blank, hd)
    return hd


def fat_file(image: bytes, name: str, ext: str) -> bytes | None:
    """A file from partition A (boot sector at sector 0, FAT12/16 BPB)."""
    bps, spc, res, nfats, roots, _, _, spf = struct.unpack_from("<HBHBHHBH", image, 11)
    clusters = struct.unpack_from("<H", image, 19)[0] // spc
    fat = image[res * bps:(res + spf) * bps]
    root = (res + nfats * spf) * bps
    data = root + roots * 32
    for n in range(roots):
        e = image[root + n * 32:root + n * 32 + 32]
        if e[0] == 0:
            break
        if e[0] != 0xE5 and (e[0:8].decode("latin-1").rstrip(), e[8:11].decode("latin-1").rstrip()) == (name, ext):
            c, size, out = struct.unpack_from("<H", e, 26)[0], struct.unpack_from("<I", e, 28)[0], b""
            while 2 <= c < 0xFF8 and len(out) < size:
                at = data + (c - 2) * spc * bps
                out += image[at:at + spc * bps]
                if clusters < 4085:
                    v = struct.unpack_from("<H", fat, c * 3 // 2)[0]
                    c = v >> 4 if c & 1 else v & 0xFFF
                else:
                    c = struct.unpack_from("<H", fat, c * 2)[0]
            return out[:size]
    return None


def writes(path, port: str, value: str, start: float) -> int:
    n = 0
    for line in path.read_text().splitlines():
        f = line.split()
        if f[2] == "W" and f[3] == port and f[4] == value and float(f[0]) >= start:
            n += 1
    return n


STATUS = h.taps((35, "disk"), (36, "9"), (37.5, "4"))
SAVE_AT = 42.0
SAVE = h.taps((SAVE_AT, "disk"), (SAVE_AT + 1.5, "6"), (SAVE_AT + 3.5, "soft1"), (52.0, "disk"), (53.5, "7"))
RESCAN_AT = 42.0


class Scsi316(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        jobs = {}
        for bios in h.bios316_sets():
            p = h.payload("316", bios)
            hd = fixture(p)
            cases = {
                "page": (STATUS, [40.0], 0, None),
                "multi_on": (SAVE, [47.0, 56.0], 0, ["a4"]),
                "multi_off": (STATUS + h.dial(1, 39.0) + SAVE, [40.0, 47.0, 56.0], 0, ["a4"]),
                "reset_off": (STATUS + h.taps((RESCAN_AT, "soft1")), [55.0], 3, ["a2"]),
                "reset_on": (STATUS + h.taps((39.0, "down")) + h.dial(1, 40.0) + h.taps((RESCAN_AT, "soft1")),
                             [41.0, 55.0], 3, ["a2"]),
            }
            for name, case in cases.items():
                jobs[(p.label, name)] = (p, hd, name, *case)

        def execute(key, job):
            p, hd, name, events, times, slot, trace = job
            runs = RUNS / p.label
            disk = runs / f"{name}.hd"
            shutil.copy(hd, disk)
            screens = h.run_case(p, runs, name, times=times, events=events, parts=[], snapshot=False,
                                 extra=scsi(disk, slot), trace=[int(t, 16) for t in trace or []])
            return screens, runs / name / "io_trace.log", disk.read_bytes()

        cls.results = h.run_parallel(jobs, execute)

    def get(self, label, name):
        return self.results[(label, name)]

    def labels(self):
        return sorted({label for label, _ in self.results})

    def test_page_rows_and_defaults(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                rows = [r.replace(".", " ") for r in self.get(label, "page")[0][0]["rows"]]
                self.assertIn("SCSI Status", rows[0])
                self.assertTrue(rows[2].startswith("Multi-sector SCSI transfers:"), rows[2])
                self.assertEqual(rows[2][37:40].strip(), "ON")
                self.assertTrue(rows[3].startswith("Reset SCSI chip on AUTO search:"), rows[3])
                self.assertEqual(rows[3][37:40].strip(), "OFF")
                self.assertIn("make active:AUTO", rows[4])

    def test_multi_sector_off_writes_the_same_file_one_block_per_command(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                on_screens, on_trace, on_disk = self.get(label, "multi_on")
                off_screens, off_trace, off_disk = self.get(label, "multi_off")
                self.assertIn("Multi-sector SCSI transfers:         OFF", off_screens[0]["rows"][2].replace(".", " "))
                on, off = fat_file(on_disk, "PARAMS", "PAR"), fat_file(off_disk, "PARAMS", "PAR")
                self.assertIsNotNone(on)
                self.assertIsNotNone(off)
                self.assertEqual(len(on), len(off))
                self.assertEqual((on[BLOCK], off[BLOCK]), (0, 1))
                self.assertEqual(on[:BLOCK] + on[BLOCK + 1:], off[:BLOCK] + off[BLOCK + 1:])
                sel_on = writes(on_trace, "00A4", "24", SAVE_AT + 3.4)
                sel_off = writes(off_trace, "00A4", "24", SAVE_AT + 3.4)
                self.assertGreater(sel_on, 0)
                self.assertGreater(sel_off, sel_on)
                self.assertIn("PARAMS.PAR", "\n".join(off_screens[-1]["rows"]))

    def test_reset_on_auto_search(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                screens, trace, _ = self.get(label, "reset_on")
                self.assertIn("Reset SCSI chip on AUTO search:      ON", screens[0]["rows"][3].replace(".", " "))
                on = writes(trace, "00A2", "C0", RESCAN_AT)
                off = writes(self.get(label, "reset_off")[1], "00A2", "C0", RESCAN_AT)
                self.assertGreaterEqual(off, 1)
                self.assertEqual(on - off, 3, (on, off))          # IDs 0, 1, 2 fail before ID 3
                for name in ("reset_on", "reset_off"):
                    self.assertIn("SCSI ID 3 IN USE", self.get(label, name)[0][-1]["rows"][1])


if __name__ == "__main__":
    unittest.main()
