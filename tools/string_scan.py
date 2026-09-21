"""Whole-image string scan for Vailixi 3.50.

A consumer, not printability, establishes text. Printable runs without
a proven consumer stay candidates.

Regenerate ``analysis/string_scan.json`` with
``python3 tools/string_scan.py --write``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.linear_rom import load_vailixi_linear

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_PATH = REPO_ROOT / "analysis" / "string_scan.json"

PRINTABLE = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}

DIRECTORY = (0x20004, 0x205C8)
DISK_TABLE = (0x205FC, 0x20668)
DGROUP = (0x20000, 0x27C92)
WALKER_CALLS = (0x78122, 0x799BE, 0x79A17)
CODE_WINDOWS = (
    (0x3000E, 0x7079C),
    (0x7800A, 0x7A78E),
    (0x7AC00, 0x7B813),
)
PUT_STRING = {
    "cs_ip": "B1B1:005B",
    "file": 0x31B6B,
    "end": 0x31B91,
    "bytes": "558bec1e57c57e068a1d0adb7408b80400cd4347ebf2b80700cd438bd8b80300cd435f1f5dcb",
}
KADAK_FILE = 0x7B00F
KADAK_BYTES = "434f50595249474854202843292031393833204b4144414b2050524f4455435453204c54442e"


def _u16(image: bytes, offset: int) -> int:
    return image[offset] | (image[offset + 1] << 8)


def _in_code(offset: int) -> bool:
    return any(start <= offset < end for start, end in CODE_WINDOWS)


def cstring_at(image: bytes, offset: int, min_len: int = 1) -> tuple[int, str] | None:
    """Return (exclusive_end, text) for a C-string at offset.

    min_len=0 accepts a lone NUL (empty string). min_len>=1 requires
    that many printable bytes before the NUL.
    """
    i = offset
    n = len(image)
    while i < n and image[i] in PRINTABLE:
        i += 1
    if i == offset:
        if min_len == 0 and i < n and image[i] == 0:
            return i + 1, ""
        return None
    if i - offset >= min_len and i < n and image[i] == 0:
        return i + 1, image[offset:i].decode("ascii")
    return None


def iter_cstrings(image: bytes, lo: int, hi: int, min_len: int):
    i = lo
    while i < hi:
        hit = cstring_at(image, i, min_len)
        if hit and hit[1] != "":
            yield i, hit[0], hit[1]
            i = hit[0]
        else:
            i += 1


def count_cstrings(image: bytes, min_len: int, lo: int = 0, hi: int = 0x80000) -> int:
    return sum(1 for _ in iter_cstrings(image, lo, hi, min_len))


def _dir_slots(image: bytes) -> dict:
    ptrs: list[dict] = []
    nulls = 0
    numeric = 0
    off = DIRECTORY[0]
    while off < DIRECTORY[1]:
        ip = _u16(image, off)
        cs = _u16(image, off + 2)
        if cs == 0x8010:
            fo = DGROUP[0] + ip
            hit = cstring_at(image, fo, 0)
            if hit is None:
                raise AssertionError(f"directory 8010:{ip:04X} is not a C-string")
            ptrs.append(
                {
                    "slot": f"0x{off:05X}",
                    "off": f"0x{ip:04X}",
                    "file": f"0x{fo:05X}",
                    "text": hit[1],
                }
            )
        elif cs == 0 and ip == 0:
            nulls += 1
        else:
            numeric += 1
        off += 4
    empty = sum(1 for p in ptrs if p["text"] == "")
    starts = {p["file"] for p in ptrs}
    return {
        "file": f"0x{DIRECTORY[0]:05X}",
        "end": f"0x{DIRECTORY[1]:05X}",
        "ptr_8010": len(ptrs),
        "null": nulls,
        "numeric": numeric,
        "cstring_targets": len(ptrs) - empty,
        "empty_targets": empty,
        "empty_off": "0x0677",
        "unique_starts": len(starts),
        "starts": sorted(starts),
    }


def _disk_table(image: bytes) -> dict:
    rows = []
    off = DISK_TABLE[0]
    while off < DISK_TABLE[1]:
        ip = _u16(image, off)
        cs = _u16(image, off + 2)
        if cs != 0x8010:
            raise AssertionError(f"disk table 0x{off:05X} is not xxxx:8010")
        fo = DGROUP[0] + ip
        hit = cstring_at(image, fo, 1)
        if hit is None:
            raise AssertionError(f"disk table 8010:{ip:04X} is not a C-string")
        rows.append((fo, hit[1]))
        off += 4
    return {
        "file": f"0x{DISK_TABLE[0]:05X}",
        "end": f"0x{DISK_TABLE[1]:05X}",
        "count": len(rows),
        "first": rows[0][1],
        "last": rows[-1][1],
        "starts": [f"0x{fo:05X}" for fo, _t in rows],
    }


def _walker(image: bytes) -> list[dict]:
    out = []
    for call in WALKER_CALLS:
        if image[call] != 0xE8:
            raise AssertionError(f"walker caller 0x{call:05X} is not CALL near")
        start = call + 3
        hit = cstring_at(image, start, 1)
        if hit is None:
            raise AssertionError(f"walker inline at 0x{start:05X} is not a C-string")
        out.append(
            {
                "call_file": f"0x{call:05X}",
                "file": f"0x{start:05X}",
                "end": f"0x{hit[0]:05X}",
                "length": hit[0] - start - 1,
                "text": hit[1],
            }
        )
    return out


def _dgroup_starts(image: bytes) -> dict[int, str]:
    return {start: text for start, _end, text in iter_cstrings(image, DGROUP[0], DGROUP[1], 2)}


def _push_ds_far(image: bytes, starts: dict[int, str]) -> dict:
    """PUSH DS / PUSH imm16 / CALL FAR where imm16 is a DGROUP C-string."""
    sites: list[tuple[int, int, int, str, int, int]] = []
    pos = 0
    while True:
        j = image.find(b"\x1e\x68", pos)
        if j < 0 or j + 8 > len(image):
            break
        if _in_code(j) and image[j + 4] == 0x9A:
            imm = _u16(image, j + 2)
            fo = DGROUP[0] + imm
            if fo in starts:
                ip = _u16(image, j + 5)
                cs = _u16(image, j + 7)
                sites.append((j, imm, fo, starts[fo], cs, ip))
        pos = j + 1
    callees: dict[str, int] = {}
    for _j, _imm, _fo, _text, cs, ip in sites:
        key = f"{cs:04X}:{ip:04X}"
        callees[key] = callees.get(key, 0) + 1
    top = max(callees.items(), key=lambda kv: kv[1]) if callees else ("", 0)
    return {
        "pattern": "1E 68 iw 9A ip cs",
        "count": len(sites),
        "unique_targets": len({fo for _j, _imm, fo, _t, _cs, _ip in sites}),
        "starts": sorted({f"0x{fo:05X}" for _j, _imm, fo, _t, _cs, _ip in sites}),
        "callee_count": len(callees),
        "top_callee": top[0],
        "top_callee_count": top[1],
        "put_string_cs_ip": PUT_STRING["cs_ip"],
    }


def _established(directory: dict, disk: dict, walker: list[dict], push: dict, starts: dict[int, str]) -> dict:
    owners: dict[int, str] = {}
    for hex_off in directory["starts"]:
        fo = int(hex_off, 16)
        hit = starts.get(fo)
        if hit is None:
            # empty string at 0x20677 is min_len 0, not in starts (min2)
            owners[fo] = "directory"
        else:
            owners[fo] = "directory"
    for hex_off in disk["starts"]:
        owners[int(hex_off, 16)] = "disk_table"
    for rec in walker:
        owners[int(rec["file"], 16)] = "walker"
    for hex_off in push["starts"]:
        owners.setdefault(int(hex_off, 16), "push_ds_far")
    payload = 0
    for fo in owners:
        if fo in starts:
            payload += len(starts[fo]) + 1
        else:
            # empty C-string: one NUL
            payload += 1
    return {
        "unique_starts": len(owners),
        "payload_bytes": payload,
        "by_class": {
            "directory": sum(1 for v in owners.values() if v == "directory"),
            "disk_table": sum(1 for v in owners.values() if v == "disk_table"),
            "walker": sum(1 for v in owners.values() if v == "walker"),
            "push_ds_far": sum(1 for v in owners.values() if v == "push_ds_far"),
        },
        "starts": [f"0x{fo:05X}" for fo in sorted(owners)],
    }


def scan(image: bytes) -> dict:
    directory = _dir_slots(image)
    disk = _disk_table(image)
    walker = _walker(image)
    starts = _dgroup_starts(image)
    push = _push_ds_far(image, starts)
    established = _established(directory, disk, walker, push, starts)
    est_set = {int(x, 16) for x in established["starts"]}
    unconsumed = [fo for fo in starts if fo not in est_set]
    kadak = image[KADAK_FILE : KADAK_FILE + 38]
    specimens = [
        {"file": "0x210F5", "text": "Vailixi 3.50 (---/--/----)", "consumer": "push_ds_far"},
        {"file": "0x210E0", "text": "www.mansell-labs.com", "consumer": "push_ds_far"},
        {"file": "0x2066C", "text": "ALL EVENTS ", "consumer": "directory"},
        {"file": "0x20690", "text": "NO ", "consumer": "directory"},
        {"file": "0x206C5", "text": "50L", "consumer": "directory"},
        {"file": "0x20F9C", "text": "FLOPPY DISK", "consumer": "disk_table"},
        {"file": "0x78125", "text": "MPC-3000 BIOS 21/08/07\r\n", "consumer": "walker"},
        {
            "file": "0x799C1",
            "text": "============= System Error =============Sorry, but a software bug of type ",
            "consumer": "walker",
        },
    ]
    return {
        "target": "vailixi-3.50",
        "rule": "consumer_not_printability",
        "cstring_min_printable": 2,
        "scan_counts": {
            "whole_min2": count_cstrings(image, 2),
            "whole_min4": count_cstrings(image, 4),
            "dgroup_min2": count_cstrings(image, 2, DGROUP[0], DGROUP[1]),
            "dgroup_min4": count_cstrings(image, 4, DGROUP[0], DGROUP[1]),
            "app_min2": count_cstrings(image, 2, 0x30000, 0x70000),
            "app_min4": count_cstrings(image, 4, 0x30000, 0x70000),
            "bios_min2": count_cstrings(image, 2, 0x78000, 0x7AC00),
            "bios_min4": count_cstrings(image, 4, 0x78000, 0x7AC00),
        },
        "directory": {k: v for k, v in directory.items() if k != "starts"},
        "disk_label_table": {k: v for k, v in disk.items() if k != "starts"},
        "walker_inline": walker,
        "push_ds_far": {k: v for k, v in push.items() if k != "starts"},
        "put_string": {
            "cs_ip": PUT_STRING["cs_ip"],
            "file": f"0x{PUT_STRING['file']:05X}",
            "end": f"0x{PUT_STRING['end']:05X}",
            "bytes": PUT_STRING["bytes"],
            "phys20": "0xB1B6B",
        },
        "established": {
            "unique_starts": established["unique_starts"],
            "payload_bytes": established["payload_bytes"],
            "by_class": established["by_class"],
        },
        "candidates": {
            "dgroup_unconsumed_min2": len(unconsumed),
            "app_rom_min4": count_cstrings(image, 4, 0x30000, 0x70000),
            "kadak": {
                "file": f"0x{KADAK_FILE:05X}",
                "bytes": KADAK_BYTES,
                "established": False,
                "reason": "EB 40 skips; no NUL terminator; no reader",
            },
        },
        "specimens": specimens,
        "_starts": {
            "directory": directory["starts"],
            "disk_table": disk["starts"],
            "push_ds_far": push["starts"],
            "established": established["starts"],
        },
    }


def public_scan(image: bytes) -> dict:
    data = scan(image)
    data.pop("_starts", None)
    return data


def load_scan(path: Path = SCAN_PATH) -> dict:
    return json.loads(path.read_text())


def validate(image: bytes, pinned: dict) -> list[str]:
    live = scan(image)
    checks: list[str] = []

    if live["scan_counts"] != pinned["scan_counts"]:
        raise AssertionError(f"scan_counts {live['scan_counts']} != pinned")
    checks.append("string scan counts")

    for key in ("directory", "disk_label_table", "push_ds_far", "established"):
        if live[key] != pinned[key]:
            raise AssertionError(f"{key} does not match pinned scan")
    if live["walker_inline"] != pinned["walker_inline"]:
        raise AssertionError("walker_inline does not match pinned scan")
    checks.append("directory / disk table / walker / PUSH DS+far")

    put = pinned["put_string"]
    off = int(put["file"], 16)
    raw = bytes.fromhex(put["bytes"])
    if image[off : off + len(raw)] != raw:
        raise AssertionError("B1B1:005B put-string bytes mismatch")
    if image[int(put["end"], 16) - 1] != 0xCB:
        raise AssertionError("put-string does not end in RETF")
    if live["push_ds_far"]["top_callee"] != PUT_STRING["cs_ip"]:
        raise AssertionError("top PUSH DS+far callee is not B1B1:005B")
    checks.append("B1B1:005B put-string via INT 43 AX=4")

    for spec in pinned["specimens"]:
        fo = int(spec["file"], 16)
        text = spec["text"]
        got = image[fo : fo + len(text)]
        if got != text.encode("ascii"):
            raise AssertionError(f"specimen 0x{fo:05X} expected {text!r}, got {got!r}")
        if spec["consumer"] == "walker":
            continue
        if spec["file"] not in live["_starts"]["established"]:
            raise AssertionError(f"specimen 0x{fo:05X} is not established")
    checks.append(f"{len(pinned['specimens'])} specimen strings")

    kad = pinned["candidates"]["kadak"]
    if kad["established"]:
        raise AssertionError("KADAK must not be consumer-established text")
    if image[KADAK_FILE : KADAK_FILE + 38] != bytes.fromhex(kad["bytes"]):
        raise AssertionError("KADAK identity bytes mismatch")
    if 0x00 in image[KADAK_FILE : KADAK_FILE + 38]:
        raise AssertionError("KADAK unexpectedly contains a NUL")
    checks.append("KADAK remains identity bytes, not text")

    if live["candidates"]["dgroup_unconsumed_min2"] != pinned["candidates"]["dgroup_unconsumed_min2"]:
        raise AssertionError("unconsumed DGROUP count mismatch")
    checks.append(
        f"established {pinned['established']['unique_starts']} strings; "
        f"{pinned['candidates']['dgroup_unconsumed_min2']} DGROUP candidates"
    )
    return checks


def write_scan(path: Path = SCAN_PATH) -> dict:
    image = load_vailixi_linear()
    data = public_scan(image)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate analysis/string_scan.json")
    args = parser.parse_args()
    image = load_vailixi_linear()
    if args.write:
        data = write_scan()
        print(
            f"wrote {SCAN_PATH} ({data['established']['unique_starts']} established, "
            f"{data['candidates']['dgroup_unconsumed_min2']} DGROUP candidates)"
        )
        return 0
    pinned = load_scan()
    for item in validate(image, pinned):
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
