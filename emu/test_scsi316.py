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
    reset ON the SPC init (port A2h <- C0h) runs after each failed probe;
  - make_active: the boot scan mounts unit 0; Disk 9 4, Down x2 (SCSI device
    address), <Make active>, then the wheel +1 changes the unit field, not
    Multi-sector.  The stock page re-renders after <Make active> and appends
    its field records at FIELD_PTR (DS:7A69, Vailixi 7D7B), which the cursor
    had left on record 2; PMONEY's rows routine now resets FIELD_PTR to
    FIELD_FIRST (DS:7A6E) on every pass (audit 2026-10-16 F-1, MAME).  DGROUP
    bytes come from emu/lua/dg_words316.lua (DG_PHYS + offset, read-only).
  - disk7 (stock 3.16 stack overrun, mods/scsistack316.inc): Disk 7's media
    check enters the partition reader 2AB2:04F7 on the UI stack with SP below
    its 100Eh-byte frame; the reader runs on the private stack between the
    sequence pool and the image, and no write lands in [cave end, image
    0x84000) (stock: the frame wraps to 73E1:F7C2 = image 0x835D2).
"""
from __future__ import annotations

import shutil
import struct
import unittest
from collections import Counter

from emu import harness as h
from mods import build_wave316 as b316

RUNS = h.BUILD / "emu" / "scsi-tests"
DISK_MB = 40
BLOCK = 0x831B - 0x7C61 + 4          # PARAMS.PAR offset of the multi-sector byte (4-byte header)
# DGROUP (3.16 offsets, mods/profile_316.inc): the stock field list of the
# page builder T_B060_*: FIELD_INDEX (byte, current field), FIELD_PTR (word,
# append/current record pointer), FIELD_FIRST (records of 14 bytes, byte +1 =
# screen row), and the multi-sector setting byte (PARAMS.PAR image 7C61+).
FIELD_INDEX, FIELD_PTR, FIELD_FIRST, FIELD_SIZE = 0x7A67, 0x7A69, 0x7A6E, 14
MULTI_SECTOR = 0x831B
FIELD_BYTES = [FIELD_INDEX, FIELD_PTR, FIELD_PTR + 1] + list(range(FIELD_FIRST, FIELD_FIRST + 8 * FIELD_SIZE)) + [MULTI_SECTOR]


def dg_env(offsets) -> dict[str, str]:
    """Environment of the dg_words observer part (emu/lua/dg_words316.lua)."""
    return {"DG_BYTES": ",".join(f"{o:X}" for o in offsets)}


def dg_bytes(run_dir) -> dict[float, dict[int, int]]:
    """dg_words.log: {probe time: {DGROUP offset: byte}}."""
    out = {}
    for line in (run_dir / "dg_words.log").read_text().splitlines():
        t, *fields = line.split()
        out[float(t[2:])] = {int(k, 16): int(v, 16) for k, v in (f.split("=") for f in fields)}
    return out


def dg_word(snap: dict[int, int], off: int) -> int:
    return snap[off] | snap[off + 1] << 8


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
DISK7 = h.taps((35, "disk"), (36.5, "7"))
READER = 0x2B017                     # 2AB2:04F7, the SCSI partition reader (image offset)
UI_SS = 0x73E1                       # the UI task's stack segment (create-table record 7, relative)
FRAME = 0x100E + 2                   # SUB SP,100Eh after PUSH BP: an entry SP below this wraps
WATCH_FROM = 34.0                    # after boot (the EPROM's RAM test writes everywhere at reset)
# Read-only observer: writes in [cave end, image 0x84000), reader entries (SS:SP),
# and writes made on the reader's private stack (SS = its segment).
STACK_WATCH = """
local cpu = manager.machine.devices[":maincpu"]
local prog = cpu.spaces["program"]
local log = assert(io.open(os.getenv("PROBE_OUT") .. "/stack_watch.log", "w"))
local armed = false
local function st(n) return cpu.state[n].value end
local function now() return manager.machine.time:as_double() end
local function pc() local ps = st("PS"); return string.format("%04X:%04X", ps, (st("CURPC") - ps * 16) & 0xffff) end
emu.register_periodic(function() if not armed and now() >= {watch} then armed = true end end)
local stk_seg = (IMAGE_PHYS - 0x300000) // 16 - {paras}
local entry = IMAGE_PHYS + {reader}
local n_stack = 0
STACK_WATCH_TAPS = {{
  prog:install_write_tap((CAVE_PHYS + CAVE_LEN) & ~1, IMAGE_PHYS + 0x84000 - 1, "sw_top", function(off, data, mask)
    if armed and off >= CAVE_PHYS + CAVE_LEN then log:write(string.format("TOP %.6f image=%05X pc=%s ss:sp=%04X:%04X\\n", now(), off - IMAGE_PHYS, pc(), st("SS"), st("SP"))); log:flush() end
  end),
  prog:install_read_tap(entry & ~1, (entry | 1) + 2, "sw_entry", function(off, data, mask)
    if armed then log:write(string.format("ENTRY %.6f pc=%s ss:sp=%04X:%04X\\n", now(), pc(), st("SS"), st("SP"))); log:flush() end
  end),
  prog:install_write_tap(IMAGE_PHYS - {paras} * 16, IMAGE_PHYS - 1, "sw_stack", function(off, data, mask)
    if armed and st("SS") == stk_seg then
      n_stack = n_stack + 1
      if n_stack <= 4 then log:write(string.format("STACK %.6f pc=%s ss:sp=%04X:%04X\\n", now(), pc(), st("SS"), st("SP"))); log:flush() end
    end
  end),
}}
"""

# make_active: no cancel, the boot scan mounts unit 0 (~39 s).  Disk 9 4,
# Down x2 to the unit field, <Make active> (rescan), wheel +1, then Down x5
# (the cursor stops on the last field record).
MAKE_ACTIVE = (h.taps((40, "disk"), (41, "9"), (42.5, "4"), (44.0, "down"), (44.5, "down"), (46.0, "soft1"))
               + h.dial(1, 52.0) + h.taps(*[(54.0 + 0.5 * i, "down") for i in range(5)]))
MAKE_ACTIVE_TIMES = [45.5, 51.5, 53.0, 57.0]


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
                "make_active": (MAKE_ACTIVE, MAKE_ACTIVE_TIMES, 0, None, FIELD_BYTES),
                "disk7": (DISK7, [40.0], 0, None),
            }
            for name, case in cases.items():
                events, times, slot, trace, *dg = case
                jobs[(p.label, name)] = (p, hd, name, events, times, slot, trace, dg[0] if dg else None)
        paras = b316._profile_values()[1]["SCSI_STK_PARAS"]
        watch = STACK_WATCH.format(watch=WATCH_FROM, paras=paras, reader=READER)

        def execute(key, job):
            p, hd, name, events, times, slot, trace, dg = job
            runs = RUNS / p.label
            disk = runs / f"{name}.hd"
            shutil.copy(hd, disk)
            screens = h.run_case(p, runs, name, times=times, events=events, parts=["dg_words"] if dg else [],
                                 env=dg_env(dg) if dg else None, snapshot=False,
                                 extra=scsi(disk, slot), trace=[int(t, 16) for t in trace or []],
                                 prelude=watch if name == "disk7" else "")
            return screens, runs / name / "io_trace.log", disk.read_bytes()

        cls.results = h.run_parallel(jobs, execute)
        cls.loads = {p.label: p.load_segment for p, *_ in jobs.values()}

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

    def test_make_active_then_wheel_edits_the_unit_field(self) -> None:
        """After <Make active> the cursor is still on the unit field and the field
        list holds the page's four records (rows 2-5) once.  Before the fix the
        re-render appended the rows again at FIELD_PTR: record 2 became row 2
        (Multi-sector), so the wheel turned Multi-sector OFF ([831B] = 1) and
        the unit stayed AUTO."""
        for label in self.labels():
            with self.subTest(set=label):
                screens = self.get(label, "make_active")[0]
                ram = dg_bytes(RUNS / label / "make_active")
                rows = [[r.replace(".", " ") for r in s["rows"]] for s in screens]
                before, rescanned, turned, moved = (ram[t] for t in MAKE_ACTIVE_TIMES)
                # Before <Make active>: unit AUTO, cursor on field 2 (the unit row).
                self.assertIn("make active:AUTO", rows[0][4])
                self.assertEqual(before[FIELD_INDEX], 2)
                self.assertEqual([before[FIELD_FIRST + k * FIELD_SIZE + 1] for k in range(4)], [2, 3, 4, 5])
                # The rescan re-rendered the page: still four records, rows 2-5, cursor on 2.
                self.assertIn("SCSI ID 0 IN USE", rows[1][1])
                self.assertEqual(rescanned[FIELD_INDEX], 2)
                self.assertEqual([rescanned[FIELD_FIRST + k * FIELD_SIZE + 1] for k in range(4)], [2, 3, 4, 5])
                self.assertEqual(dg_word(rescanned, FIELD_PTR), FIELD_FIRST + 2 * FIELD_SIZE)
                # Wheel +1: the unit changes, Multi-sector stays ON.
                self.assertTrue(rows[2][4].startswith("SCSI device address to make active:0"), rows[2][4])
                self.assertEqual(rows[2][2][37:40].strip(), "ON")
                self.assertEqual(turned[MULTI_SECTOR], 0)
                # Down x5 stops on the last of the four records (index 3, row 5).
                self.assertEqual(moved[FIELD_INDEX], 3)
                self.assertEqual(dg_word(moved, FIELD_PTR), FIELD_FIRST + 3 * FIELD_SIZE)
                self.assertEqual(moved[MULTI_SECTOR], 0)


    def test_disk7_reader_runs_on_its_own_stack(self) -> None:
        for label in self.labels():
            with self.subTest(set=label):
                screens, trace, _ = self.get(label, "disk7")
                self.assertIn("Load/Erase/Rename Files", screens[-1]["rows"][0])
                lines = (trace.parent / "stack_watch.log").read_text().splitlines()
                entries = [line.split() for line in lines if line.startswith("ENTRY")]
                ui = [int(e[3][-4:], 16) for e in entries
                      if (int(e[3][6:10], 16) - self.loads[label]) & 0xFFFF == UI_SS]
                self.assertTrue(any(sp < FRAME for sp in ui), entries)    # the stock frame would wrap here
                self.assertTrue(any(line.startswith("STACK") for line in lines), lines[:20])
                self.assertEqual([line for line in lines if line.startswith("TOP")], [])


if __name__ == "__main__":
    unittest.main()
