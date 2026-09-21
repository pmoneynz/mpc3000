"""Transfer inventory from established Vailixi 3.50 entries.

From each D15 CS:IP, walk a local CFG (no JMPF/CALLF enter), then
classify every exit: return, far/near call, far jump, XA, or
indirect. A named target resolves the transfer. Indirect [rm] stays
named UNDETERMINED.

Regenerate ``analysis/transfer_scan.json`` with
``python3 tools/transfer_scan.py --write``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.entry_scan import scan as scan_entries
from tools.linear_rom import load_vailixi_linear
from tools.v53_decode import decode_one

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_PATH = REPO_ROOT / "analysis" / "transfer_scan.json"


def _parse(cs_ip: str) -> tuple[int, int]:
    cs, ip = cs_ip.split(":")
    return int(cs, 16), int(ip, 16)


def _file_of(cs: int, ip: int) -> int:
    return ((cs << 4) + ip) & 0x7FFFF


def follow_entry(image: bytes, cs: int, ip: int, established: set[str], *, limit: int = 800):
    """Local CFG that does not enter another established CS:IP."""
    start = f"{cs:04X}:{ip:04X}"
    seen: set[tuple[int, int]] = set()
    work = [(cs, ip)]
    out = []
    extra_exits: list[dict] = []
    while work and len(out) < limit:
        c, i = work.pop(0)
        here = f"{c:04X}:{i:04X}"
        if here in established and here != start:
            extra_exits.append(
                {
                    "kind": "to_established",
                    "dest": here,
                    "established": True,
                    "file": f"0x{((c << 4) + i) & 0x7FFFF:05X}",
                }
            )
            continue
        if (c, i) in seen:
            continue
        seen.add((c, i))
        insn = decode_one(image, c, i)
        out.append(insn)
        if insn.kind in (
            "RETF",
            "RET",
            "IRET",
            "RETN",
            "RETFN",
            "JMPF",
            "JMPF_RM",
            "JMPN_RM",
            "UNKNOWN_0F",
        ):
            continue
        fall_ip = (i + insn.length) & 0xFFFF
        if insn.kind in ("JMPS", "JMPN"):
            work.append((insn.target_cs or c, insn.target_ip or 0))
            continue
        if insn.kind == "JCC":
            work.append((c, fall_ip))
            work.append((insn.target_cs or c, insn.target_ip or 0))
            continue
        if insn.kind in ("CALLN", "CALLF", "CALLN_RM", "CALLF_RM", "BRKXA", "RETXA"):
            work.append((c, fall_ip))
            continue
        work.append((c, fall_ip))
    return out, extra_exits, len(out) >= limit


def classify_exits(insns, established: set[str]) -> list[dict]:
    exits: list[dict] = []
    for insn in insns:
        if insn.kind in ("RETF", "RET", "IRET", "RETN", "RETFN"):
            exits.append(
                {"kind": "return", "how": insn.kind, "file": f"0x{insn.file:05X}"}
            )
        elif insn.kind == "JMPF" and insn.target_cs is not None:
            dest = f"{insn.target_cs:04X}:{insn.target_ip:04X}"
            exits.append(
                {
                    "kind": "jmpf",
                    "dest": dest,
                    "established": dest in established,
                    "file": f"0x{insn.file:05X}",
                }
            )
        elif insn.kind in ("JMPF_RM", "JMPN_RM"):
            exits.append(
                {
                    "kind": "indirect",
                    "how": insn.kind,
                    "file": f"0x{insn.file:05X}",
                    "bytes": insn.bytes_hex,
                }
            )
        elif insn.kind == "CALLF" and insn.target_cs is not None:
            dest = f"{insn.target_cs:04X}:{insn.target_ip:04X}"
            exits.append(
                {
                    "kind": "callf",
                    "dest": dest,
                    "established": dest in established,
                    "file": f"0x{insn.file:05X}",
                }
            )
        elif insn.kind == "CALLN" and insn.target_ip is not None:
            dest = f"{insn.cs:04X}:{insn.target_ip:04X}"
            exits.append(
                {
                    "kind": "calln",
                    "dest": dest,
                    "established": dest in established,
                    "file": f"0x{insn.file:05X}",
                }
            )
        elif insn.kind in ("CALLF_RM", "CALLN_RM"):
            exits.append(
                {
                    "kind": "call_indirect",
                    "how": insn.kind,
                    "file": f"0x{insn.file:05X}",
                    "bytes": insn.bytes_hex,
                }
            )
        elif insn.kind in ("BRKXA", "RETXA"):
            exits.append(
                {
                    "kind": insn.kind.lower(),
                    "text": insn.text,
                    "file": f"0x{insn.file:05X}",
                    "bytes": insn.bytes_hex,
                }
            )
        elif insn.kind == "UNKNOWN_0F":
            exits.append(
                {
                    "kind": "unknown0f",
                    "text": insn.text,
                    "file": f"0x{insn.file:05X}",
                    "bytes": insn.bytes_hex,
                }
            )
    return exits


def _status(cs_ip: str, exits: list[dict], hit_limit: bool) -> str:
    if hit_limit:
        return "unbounded"
    kinds = {e["kind"] for e in exits}
    if not exits:
        return "loop"
    if "unknown0f" in kinds:
        return "unknown0f"
    if kinds & {"indirect", "call_indirect"}:
        return "indirect"
    return "bounded"


def scan(image: bytes) -> dict:
    entries = scan_entries(image)
    established = set(entries["_unique"])
    rows = []
    kind_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    new_callf: set[str] = set()
    new_calln: set[str] = set()
    jmpf_unest = 0

    for cs_ip in established:
        cs, ip = _parse(cs_ip)
        insns, extra, hit = follow_entry(image, cs, ip, established)
        exits = classify_exits(insns, established) + extra
        status = _status(cs_ip, exits, hit)
        for e in exits:
            kind_counts[e["kind"]] = kind_counts.get(e["kind"], 0) + 1
            if e["kind"] == "callf" and not e.get("established"):
                new_callf.add(e["dest"])
            if e["kind"] == "calln" and not e.get("established"):
                new_calln.add(e["dest"])
            if e["kind"] == "jmpf" and not e.get("established"):
                jmpf_unest += 1
        status_counts[status] = status_counts.get(status, 0) + 1
        files = [i.file for i in insns]
        rows.append(
            {
                "cs_ip": cs_ip,
                "file": f"0x{_file_of(cs, ip):05X}",
                "n_insns": len(insns),
                "span": [f"0x{min(files):05X}", f"0x{max(i.file + i.length for i in insns):05X}"]
                if files
                else None,
                "status": status,
                "exit_count": len(exits),
            }
        )

    rows.sort(key=lambda r: r["file"])
    if jmpf_unest:
        raise AssertionError("JMPF to a non-established CS:IP")
    if status_counts.get("unbounded") or status_counts.get("unknown0f"):
        raise AssertionError("an established entry is unbounded or hit UNKNOWN_0F")

    idle = next(r for r in rows if r["cs_ip"] == "FB00:023A")
    if idle["status"] != "loop":
        raise AssertionError("FB00:023A is not classified as the idle loop")
    if image[0x7B23A:0x7B240] != bytes.fromhex("90909090ebfa"):
        raise AssertionError("idle bytes changed")

    return {
        "target": "vailixi-3.50",
        "rule": "local_cfg_no_far_enter",
        "entries": len(rows),
        "status_counts": status_counts,
        "exit_counts": kind_counts,
        "discovered": {
            "callf_new": len(new_callf),
            "calln_new": len(new_calln),
            "jmpf_unestablished": jmpf_unest,
        },
        "specimens": {
            "idle": idle,
            "put_string": next(r for r in rows if r["cs_ip"] == "B1B1:005B"),
            "task6": next(r for r in rows if r["cs_ip"] == "D9BD:0009"),
            "reset": next(r for r in rows if r["cs_ip"] == "FFFF:0000"),
            "dispatcher": next(r for r in rows if r["cs_ip"] == "FB00:013E"),
        },
        "indirect_entries": [r["cs_ip"] for r in rows if r["status"] == "indirect"],
        "rows": rows,
    }


def load_scan(path: Path = SCAN_PATH) -> dict:
    return json.loads(path.read_text())


def validate(image: bytes, pinned: dict) -> list[str]:
    live = scan(image)
    checks: list[str] = []
    for key in ("entries", "status_counts", "exit_counts", "discovered", "indirect_entries"):
        if live[key] != pinned[key]:
            raise AssertionError(f"transfer_scan {key} mismatch")
    checks.append(
        f"followed {pinned['entries']} entries; "
        f"{pinned['status_counts'].get('bounded', 0)} bounded, "
        f"{pinned['status_counts'].get('indirect', 0)} indirect, "
        f"{pinned['status_counts'].get('loop', 0)} loop"
    )
    if pinned["discovered"]["jmpf_unestablished"] != 0:
        raise AssertionError("JMPF dest not established")
    if live["specimens"]["idle"]["status"] != "loop":
        raise AssertionError("idle not a loop")
    if live["specimens"]["put_string"]["status"] != "bounded":
        raise AssertionError("B1B1:005B not bounded")
    if image[0x7B23A:0x7B240] != bytes.fromhex("90909090ebfa"):
        raise AssertionError("idle bytes")
    checks.append("idle loop and B1B1:005B put-string exits classified")
    if pinned["discovered"]["callf_new"] < 1:
        raise AssertionError("expected newly discovered CALLF targets")
    checks.append(
        f"discovered {pinned['discovered']['callf_new']} CALLF + "
        f"{pinned['discovered']['calln_new']} CALLN candidates (not accepted as code)"
    )
    return checks


def write_scan(path: Path = SCAN_PATH) -> dict:
    image = load_vailixi_linear()
    data = scan(image)
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
            f"wrote {SCAN_PATH} ({data['entries']} entries, "
            f"{data['status_counts']})"
        )
        return 0
    pinned = load_scan()
    for item in validate(image, pinned):
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
