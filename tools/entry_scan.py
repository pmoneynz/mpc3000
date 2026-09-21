"""Whole-image entry-candidate scan for Vailixi 3.50.

An entry is established only when a named transfer consumer reaches
it. Whole-image ``9A`` / ``EA`` encodings are suspects until decoded
on an instruction boundary. Investigate before accepting as code.

Regenerate ``analysis/entry_scan.json`` with
``python3 tools/entry_scan.py --write``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.linear_rom import load_vailixi_linear

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_PATH = REPO_ROOT / "analysis" / "entry_scan.json"

CREATE_TABLE = 0x7B762
F07A = 0x707A4
INT43_TABLE = 0x796D4
FB00_FAR = bytes((0x00, 0xFB))

AMX_PUBLIC_IPS = (
    0x0157,
    0x0194,
    0x0347,
    0x038A,
    0x0396,
    0x03B3,
    0x0469,
    0x0484,
    0x04AC,
    0x0552,
    0x0586,
    0x0624,
    0x0637,
    0x0648,
    0x065B,
    0x067C,
    0x06B9,
    0x06E8,
    0x0725,
)

AMX_INTERNAL = (
    ("FB00:000C", 0x7B00C, "amx_start"),
    ("FB00:013E", 0x7B13E, "dispatcher"),
    ("FB00:01EA", 0x7B1EA, "select"),
    ("FB00:01CF", 0x7B1CF, "wait"),
    ("FB00:023A", 0x7B23A, "idle"),
    ("FB00:0240", 0x7B240, "create"),
    ("FB00:0537", 0x7B537, "index"),
    ("FB00:02F8", 0x7B2F8, "ivt0"),
    ("FB00:02EF", 0x7B2EF, "ivt4"),
    ("FB00:0311", 0x7B311, "default_iret"),
)

IVT_NAMED = (
    ("FB00:02F8", 0x7B2F8, "ivt_0"),
    ("F800:1956", 0x79956, "ivt_1_ladder"),
    ("F800:1959", 0x79959, "ivt_2_ladder"),
    ("FB00:02EF", 0x7B2EF, "ivt_4"),
    ("D52A:0008", 0x552A8, "ivt_8"),
    ("F800:2047", 0x7A047, "ivt_0B"),
    ("D5DD:000C", 0x55DDC, "ivt_0C"),
    ("D547:0067", 0x554D7, "ivt_0D"),
    ("D5F3:000E", 0x55F3E, "ivt_0E"),
    ("F800:1952", 0x79952, "ivt_default_iret"),
    ("FAC0:01A4", 0x7ADA4, "ivt_10"),
    ("F800:1B36", 0x79B36, "ivt_40"),
    ("F800:0364", 0x78364, "ivt_41"),
    ("F800:205E", 0x7A05E, "ivt_42"),
    ("F800:16AA", 0x796AA, "ivt_43"),
    ("F800:0143", 0x78143, "ivt_45"),
    ("F800:18D6", 0x798D6, "ivt_46"),
)

SHARED_APP = (
    ("E937:0004", 0x69374, "ds8010_set"),
    ("B060:0000", 0x30600, "timed_wait_cdecl"),
    ("D9B5:0045", 0x59B95, "far_cdecl_lds"),
)

BIOS_NEAR = (
    ("F800:1875", 0x79875, "inline_walker"),
    ("F800:1896", 0x79896, "hex_helper"),
    ("F800:18CA", 0x798CA, "int43_ax4_from_walker"),
    ("F800:19B3", 0x799B3, "unexpected_vector"),
    ("F800:1843", 0x79843, "cursor"),
    ("F800:185A", 0x7985A, "lcd_put"),
)

LOOKALIKES = (
    {
        "file": "0x7FF01",
        "bytes": "eaffb80700",
        "why": "MOV DX,0xFFEA immediate; not JMPF",
        "real_cs_ip": "FFF0:0000",
    },
    {
        "file": "0x797A7",
        "bytes": "9a00c3a1ab",
        "why": "low byte of CALL 1843 at F800:17A6 (E8 9A 00); not CALLF",
        "real_cs_ip": "F800:17A6",
    },
)


def _u16(image: bytes, offset: int) -> int:
    return image[offset] | (image[offset + 1] << 8)


def file_of(cs: int, ip: int) -> int:
    return ((cs << 4) + ip) & 0x7FFFF


def _hexb(image: bytes, offset: int, n: int) -> str:
    return image[offset : offset + n].hex()


def _rec(cs_ip: str, file_off: int, image: bytes, source: str, n: int = 5) -> dict:
    return {
        "cs_ip": cs_ip,
        "file": f"0x{file_off:05X}",
        "phys20": f"0x{(int(cs_ip.split(':')[0], 16) << 4) + int(cs_ip.split(':')[1], 16):05X}",
        "bytes": _hexb(image, file_off, n),
        "source": source,
    }


def _count_opcode(image: bytes, op: int) -> int:
    n = 0
    pos = 0
    needle = bytes((op,))
    while True:
        j = image.find(needle, pos)
        if j < 0:
            break
        n += 1
        pos = j + 1
    return n


def _fb00_calls(image: bytes) -> dict[int, int]:
    counts: dict[int, int] = {}
    pos = 0
    while True:
        j = image.find(b"\x9a", pos)
        if j < 0 or j + 5 > len(image):
            break
        if image[j + 3 : j + 5] == FB00_FAR:
            ip = _u16(image, j + 1)
            counts[ip] = counts.get(ip, 0) + 1
        pos = j + 1
    return counts


def _push_ds_far_callees(image: bytes) -> list[dict]:
    callees: dict[tuple[int, int], dict] = {}
    pos = 0
    while True:
        j = image.find(b"\x1e\x68", pos)
        if j < 0 or j + 9 > len(image):
            break
        if image[j + 4] == 0x9A:
            ip = _u16(image, j + 5)
            cs = _u16(image, j + 7)
            fo = file_of(cs, ip)
            key = (cs, ip)
            rec = callees.get(key)
            if rec is None:
                rec = {
                    "cs_ip": f"{cs:04X}:{ip:04X}",
                    "file": f"0x{fo:05X}",
                    "bytes": _hexb(image, fo, 3),
                    "count": 0,
                }
                callees[key] = rec
            rec["count"] += 1
        pos = j + 1
    return sorted(callees.values(), key=lambda r: (-r["count"], r["file"]))


def _create_records(image: bytes) -> list[dict]:
    out = []
    for n in range(8):
        off = CREATE_TABLE + n * 18
        ip = _u16(image, off)
        cs = _u16(image, off + 2)
        fo = file_of(cs, ip)
        rec = _rec(f"{cs:04X}:{ip:04X}", fo, image, f"create_table_{n}")
        rec["n"] = n
        rec["table_file"] = f"0x{off:05X}"
        out.append(rec)
    return out


def _f07a_records(image: bytes) -> list[dict]:
    out = []
    for i in range(3):
        off = F07A + i * 6
        ip = _u16(image, off + 2)
        cs = _u16(image, off + 4)
        fo = file_of(cs, ip)
        rec = _rec(f"{cs:04X}:{ip:04X}", fo, image, f"f07a_{i}", 3)
        rec["ah"] = image[off + 1]
        rec["table_bytes"] = _hexb(image, off, 6)
        out.append(rec)
    return out


def _int43_records(image: bytes) -> list[dict]:
    out = []
    for ax in range(8):
        ip = _u16(image, INT43_TABLE + ax * 2)
        fo = 0x78000 + ip
        rec = _rec(f"F800:{ip:04X}", fo, image, f"int43_ax_{ax}", 4)
        rec["ax"] = ax
        out.append(rec)
    return out


def scan(image: bytes) -> dict:
    fb = _fb00_calls(image)
    if set(fb) != set(AMX_PUBLIC_IPS):
        raise AssertionError(f"FB00 far IPs {sorted(fb)} != pinned public set")
    d14 = _push_ds_far_callees(image)
    create = _create_records(image)
    f07a = _f07a_records(image)
    int43 = _int43_records(image)

    established: list[dict] = []
    established.append(_rec("FFFF:0000", 0x7FFF0, image, "reset_vector"))
    established.append(_rec("FFF0:0000", 0x7FF00, image, "wait_stub", 3))
    established.append(_rec("FAC0:0000", 0x7AC00, image, "fac0_reset", 3))
    established.append(_rec("FAC0:001F", 0x7AC1F, image, "rom_ivt_11", 3))
    established.append(_rec("FAC0:024F", 0x7AE4F, image, "rom_ivt_12", 3))
    established.append(_rec("FAC0:0134", 0x7AD34, image, "rom_ivt_14", 3))
    established.append(_rec("B000:00DF", 0x300DF, image, "fac0_cx0_jmp", 5))
    established.extend(f07a)
    established.extend(create)
    for ip, n in sorted(fb.items()):
        rec = _rec(f"FB00:{ip:04X}", 0x7B000 + ip, image, "amx_public", 3)
        rec["call_count"] = n
        established.append(rec)
    for cs_ip, fo, src in AMX_INTERNAL:
        established.append(_rec(cs_ip, fo, image, src, 3))
    for cs_ip, fo, src in IVT_NAMED:
        established.append(_rec(cs_ip, fo, image, src, 3))
    established.extend(int43)
    for cs_ip, fo, src in SHARED_APP:
        established.append(_rec(cs_ip, fo, image, src, 3))
    for cs_ip, fo, src in BIOS_NEAR:
        established.append(_rec(cs_ip, fo, image, src, 3))
    for rec in d14:
        established.append(
            {
                "cs_ip": rec["cs_ip"],
                "file": rec["file"],
                "bytes": rec["bytes"],
                "source": "push_ds_far",
                "count": rec["count"],
            }
        )

    unique = sorted({rec["cs_ip"] for rec in established})
    for rec in d14:
        if rec["bytes"] != "558bec":
            raise AssertionError(f"{rec['cs_ip']} push_ds_far target is not cdecl")

    return {
        "target": "vailixi-3.50",
        "rule": "consumer_not_encoding",
        "raw_encodings": {
            "callf_9a": _count_opcode(image, 0x9A),
            "jmpf_ea": _count_opcode(image, 0xEA),
            "note": "Counts are encodings, not instructions. See lookalikes.",
        },
        "amx_public": {
            "pattern": "9A iw 00 FB",
            "count": sum(fb.values()),
            "unique_ips": len(fb),
            "ips": [f"0x{ip:04X}" for ip in AMX_PUBLIC_IPS],
        },
        "push_ds_far": {
            "pattern": "1E 68 iw 9A ip cs",
            "unique_targets": len(d14),
            "site_count": sum(r["count"] for r in d14),
            "all_cdecl": True,
            "top": d14[0],
        },
        "create_table": create,
        "f07a": f07a,
        "int43_near": int43,
        "lookalikes": list(LOOKALIKES),
        "established": {
            "unique_cs_ip": len(unique),
            "record_count": len(established),
            "by_source": _by_source(established),
        },
        "specimens": [
            {"cs_ip": "FFFF:0000", "file": "0x7FFF0", "source": "reset_vector"},
            {"cs_ip": "FAC0:0000", "file": "0x7AC00", "source": "wait_stub_jmp"},
            {"cs_ip": "B000:00DF", "file": "0x300DF", "source": "fac0_cx0_jmp"},
            {"cs_ip": "B1B1:005B", "file": "0x31B6B", "source": "push_ds_far"},
            {"cs_ip": "D9BD:0009", "file": "0x59BD9", "source": "create_table_6"},
            {"cs_ip": "FB00:013E", "file": "0x7B13E", "source": "dispatcher"},
        ],
        "later_ivt_plants": [
            {"file": "0x305B8", "bytes": "9a470300fb", "note": "B03B:0208 CALL 0347 DL=9; not reset-path"},
            {"file": "0x7B9B8", "bytes": "9a470300fb", "note": "FB00:09B8 CALL 0347 DL=8; not reset-path"},
        ],
        "_unique": unique,
        "_callees": d14,
    }


def _by_source(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in rows:
        src = rec["source"]
        if src.startswith("create_table"):
            key = "create_table"
        elif src.startswith("f07a"):
            key = "f07a"
        elif src.startswith("int43_ax_"):
            key = "int43_near"
        elif src.startswith("ivt_"):
            key = "ivt_named"
        elif src in ("amx_start", "dispatcher", "select", "wait", "idle", "create", "index", "ivt0", "ivt4", "default_iret"):
            key = "amx_internal"
        else:
            key = src
        out[key] = out.get(key, 0) + 1
    return out


def public_scan(image: bytes) -> dict:
    data = scan(image)
    data.pop("_unique", None)
    data.pop("_callees", None)
    return data


def load_scan(path: Path = SCAN_PATH) -> dict:
    return json.loads(path.read_text())


def validate(image: bytes, pinned: dict) -> list[str]:
    live = scan(image)
    checks: list[str] = []

    if live["raw_encodings"]["callf_9a"] != pinned["raw_encodings"]["callf_9a"]:
        raise AssertionError("9A count changed")
    if live["raw_encodings"]["jmpf_ea"] != pinned["raw_encodings"]["jmpf_ea"]:
        raise AssertionError("EA count changed")
    checks.append(
        f"raw encodings 9A={pinned['raw_encodings']['callf_9a']} "
        f"EA={pinned['raw_encodings']['jmpf_ea']} (not instruction counts)"
    )

    if live["amx_public"] != pinned["amx_public"]:
        raise AssertionError("AMX public far-call surface mismatch")
    if live["push_ds_far"]["unique_targets"] != pinned["push_ds_far"]["unique_targets"]:
        raise AssertionError("push_ds_far unique target count mismatch")
    if live["push_ds_far"]["site_count"] != pinned["push_ds_far"]["site_count"]:
        raise AssertionError("push_ds_far site count mismatch")
    checks.append(
        f"AMX public {pinned['amx_public']['count']} / "
        f"{pinned['amx_public']['unique_ips']}; "
        f"PUSH DS+far {pinned['push_ds_far']['unique_targets']} cdecl entries"
    )

    if live["established"] != pinned["established"]:
        raise AssertionError("established entry summary mismatch")
    checks.append(f"established unique CS:IP {pinned['established']['unique_cs_ip']}")

    for spec in pinned["specimens"]:
        fo = int(spec["file"], 16)
        cs, ip = spec["cs_ip"].split(":")
        if file_of(int(cs, 16), int(ip, 16)) != fo:
            raise AssertionError(f"{spec['cs_ip']} file wrap mismatch")
        if image[fo] == 0xFF:
            raise AssertionError(f"{spec['cs_ip']} starts at 0xFF")
    checks.append(f"{len(pinned['specimens'])} specimen entries")

    for look in pinned["lookalikes"]:
        fo = int(look["file"], 16)
        raw = bytes.fromhex(look["bytes"])
        if image[fo : fo + len(raw)] != raw:
            raise AssertionError(f"lookalike 0x{fo:05X} bytes mismatch")
    if image[0x7FF00:0x7FF03] != bytes.fromhex("baeaff"):
        raise AssertionError("wait stub does not begin MOV DX,0xFFEA")
    if image[0x797A6:0x797A9] != bytes.fromhex("e89a00"):
        raise AssertionError("F800:17A6 is not CALL 1843")
    checks.append("9A/EA lookalikes at 0x7FF01 and 0x797A7")

    for rec in pinned["later_ivt_plants"]:
        fo = int(rec["file"], 16)
        if image[fo : fo + 5] != bytes.fromhex(rec["bytes"]):
            raise AssertionError(f"later plant 0x{fo:05X} mismatch")
    checks.append("later 0347 plants listed, not reset-path entries")

    create = pinned["create_table"]
    if len(create) != 8:
        raise AssertionError("create-table is not 8 records")
    if create[6]["cs_ip"] != "D9BD:0009":
        raise AssertionError("create[6] is not D9BD:0009")
    checks.append("create-table 0-7 and F07A still match")
    return checks


def write_scan(path: Path = SCAN_PATH) -> dict:
    image = load_vailixi_linear()
    data = public_scan(image)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    image = load_vailixi_linear()
    if args.write:
        data = write_scan()
        print(
            f"wrote {SCAN_PATH} ({data['established']['unique_cs_ip']} unique entries, "
            f"{data['raw_encodings']['callf_9a']} raw 9A)"
        )
        return 0
    pinned = load_scan()
    for item in validate(image, pinned):
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
