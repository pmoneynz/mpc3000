"""Owner ledger for the Vailixi 3.50 linear image.

Owners are only ``code``, ``data``, or ``excluded_workspace``.
``unresolved`` is never an owner. Gaps are debt, not entries.
Padding is a subtype of ``data``. Do not mark unanalyzed bytes
``excluded_workspace``.

The seed is the union of Byte-ownership tables in the notes, starting
from ``boot_reset_to_bios_banner.md`` and ``amx_wait.md``, plus later
G2 notes that already opened ranges. Adjacent same-owner spans stay
separate when the notes give them different purposes.

Regenerate ``analysis/owner_ledger.json`` with
``python3 tools/owner_ledger.py --write``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.entry_scan import scan as scan_entries
from tools.linear_rom import load_vailixi_linear
from tools.transfer_scan import classify_exits, follow_entry

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "analysis" / "owner_ledger.json"
NOTES_DIR = REPO_ROOT / "notes"
IMAGE_SIZE = 524288

OWNERS = ("code", "data", "excluded_workspace")

# (start, end, owner, kind, source, why) - half-open file offsets.
SEED_RANGES: tuple[tuple[int, int, str, str, str, str], ...] = (
    (0x00000, 0x00044, "data", "padding", "notes/boot_reset_to_bios_banner.md", "leading 0xFF; unused IVT slots 0-0x10"),
    (0x00044, 0x0004C, "data", "ivt_template", "notes/boot_reset_to_bios_banner.md", "ROM IVT[0x11], IVT[0x12]"),
    (0x0004C, 0x00050, "data", "padding", "notes/boot_reset_to_bios_banner.md", "0xFF between IVT templates"),
    (0x00050, 0x00054, "data", "ivt_template", "notes/boot_reset_to_bios_banner.md", "ROM IVT[0x14]"),
    (0x00054, 0x20000, "data", "padding", "notes/boot_reset_to_bios_banner.md", "131020 0xFF bytes"),
    (0x20000, 0x27C92, "data", "dgroup", "notes/copy_7c92.md", "DS=A000 DGROUP image"),
    (0x27C92, 0x27CA0, "data", "padding", "notes/padding.md", "0xFF after DGROUP copy source"),
    (0x27CA0, 0x27CB0, "data", "zeros", "notes/copy_7c92.md", "16 zeros after DGROUP copy source"),
    (0x27CB0, 0x3000E, "data", "padding", "notes/padding.md", "unprogrammed ROM before C prologue at 0x3000E"),
    (0x300DF, 0x301A7, "code", "code", "notes/amx_create_table.md", "create-table task 7 through RETF"),
    (0x303BA, 0x3058A, "code", "code", "notes/amx_first_dispatch.md", "B03B:000A through RETF"),
    (0x30600, 0x3060D, "code", "code", "notes/amx_create_table.md", "B060:0000 timed wait"),
    (0x314B2, 0x3156E, "code", "code", "notes/amx_create_table.md", "create-table task 5 through RETF"),
    (0x31B6B, 0x31B91, "code", "code", "notes/string_scan.md", "B1B1:005B put-string INT 43 AX=4"),
    (0x32596, 0x32600, "code", "code", "notes/amx_create_table.md", "create-table task 1 through RETF"),
    (0x5518D, 0x55206, "code", "code", "notes/pgr_live_after_amx.md", "D510:008D port picker through RETF"),
    (0x59B95, 0x59BA1, "code", "code", "notes/calling_convention.md", "D9B5:0045 LDS [BP+6]"),
    (0x59BD9, 0x59C05, "code", "code", "notes/amx_first_dispatch.md", "D9BD:0009 task 6 loop"),
    (0x5DF1A, 0x5DF42, "code", "code", "notes/amx_create_table.md", "create-table task 4 through RETF"),
    (0x69374, 0x6937C, "code", "code", "notes/amx_create_table.md", "E937:0004 DS=ES=8010 RETF"),
    (0x6AD0B, 0x6AD6E, "code", "code", "notes/amx_create_table.md", "create-table task 3 through RETF"),
    (0x6C050, 0x6C093, "code", "code", "notes/amx_create_table.md", "create-table task 2 through RETF"),
    (0x7079C, 0x707A4, "data", "padding", "notes/padding.md", "0xFF after RETF before F07A table"),
    (0x707A4, 0x707B6, "data", "init_table", "notes/boot_reset_to_bios_banner.md", "F07A three 6-byte init records"),
    (0x707B6, 0x707C8, "data", "table_tail", "notes/padding.md", "F07A tail FFFF + 16 zeros"),
    (0x707C8, 0x7800A, "data", "padding", "notes/padding.md", "unprogrammed ROM before BIOS F800:000A"),
    (0x7800A, 0x78144, "code", "code", "notes/boot_reset_to_bios_banner.md", "BIOS F800:000A through RETF"),
    (0x796AA, 0x796D4, "code", "code", "notes/boot_reset_to_bios_banner.md", "INT 43 dispatcher"),
    (0x796D4, 0x796E4, "data", "table", "notes/boot_reset_to_bios_banner.md", "INT 43 eight near targets"),
    (0x796E4, 0x7971D, "code", "code", "notes/boot_reset_to_bios_banner.md", "INT 43 AX=0 LCD init"),
    (0x79752, 0x7976E, "code", "code", "notes/int43_ax4.md", "INT 43 AX=4 class walk"),
    (0x7976E, 0x7977E, "data", "table", "notes/int43_ax4.md", "INT 43 AX=4 class table"),
    (0x7977E, 0x797CC, "code", "code", "notes/int43_ax4.md", "INT 43 AX=4 CR/LF/BS/DEL/FF"),
    (0x797CC, 0x79808, "code", "code", "notes/int43_ax4.md", "INT 43 AX=4 default glyph"),
    (0x79843, 0x79875, "code", "code", "notes/boot_reset_to_bios_banner.md", "cursor 1843 + LCD put"),
    (0x79875, 0x79896, "code", "code", "notes/boot_reset_to_bios_banner.md", "inline-string walker 1875"),
    (0x79896, 0x7989C, "code", "code", "notes/calling_convention.md", "hex helper 1896"),
    (0x798CA, 0x798D6, "code", "code", "notes/boot_reset_to_bios_banner.md", "18CA INT 43 AX=4"),
    (0x79946, 0x79B26, "code", "code", "notes/ivt_inventory.md", "1946 IRET + ladder + F800:1AD4 RETF"),
    (0x7A78E, 0x7AC00, "data", "padding", "notes/padding.md", "unprogrammed ROM before FAC0:0000"),
    (0x7AC00, 0x7ACB4, "code", "code", "notes/boot_reset_to_bios_banner.md", "FAC0 reset through BRKXA 0x14"),
    (0x7ACB4, 0x7AD34, "data", "pgr", "notes/boot_reset_to_bios_banner.md", "second PGR image"),
    (0x7AD34, 0x7ADA3, "code", "code", "notes/boot_reset_to_bios_banner.md", "FAC0:0134 table walk"),
    (0x7ADA4, 0x7ADCF, "code", "code", "notes/boot_reset_to_bios_banner.md", "IVT[10h] through BRKXA 0x12"),
    (0x7ADCF, 0x7AE4F, "data", "pgr", "notes/boot_reset_to_bios_banner.md", "third PGR image"),
    (0x7AE4F, 0x7AE56, "code", "code", "notes/boot_reset_to_bios_banner.md", "ROM IVT[12] POP/IRET"),
    (0x7AE56, 0x7AED6, "data", "pgr", "notes/boot_reset_to_bios_banner.md", "first PGR image"),
    (0x7AED6, 0x7AF6A, "data", "table", "notes/boot_reset_to_bios_banner.md", "I/O tables + sentinels"),
    (0x7AF6A, 0x7B00C, "data", "padding", "notes/padding.md", "0xFF between I/O tables and AMX header"),
    (0x7B00C, 0x7B04E, "data", "amx_header", "notes/boot_reset_to_bios_banner.md", "AMX header / copyright"),
    (0x7B04E, 0x7B5E9, "code", "code", "notes/amx_wait.md", "AMX start through task 0 RETF"),
    (0x7B5E9, 0x7B616, "code", "code", "notes/amx_public_api.md", "05E9 TCB walk and 060B helper through RET"),
    (0x7B616, 0x7B762, "code", "code", "notes/amx_public_api.md", "0616 through mailbox 0743"),
    (0x7B762, 0x7B7F2, "data", "create_table", "notes/amx_wait.md", "eight 18-byte create records"),
    (0x7B7F2, 0x7B7F6, "data", "create_table", "notes/amx_first_dispatch.md", "create-table FFFF:FFFF terminator"),
    (0x7B7F6, 0x7B7FE, "data", "table", "notes/amx_first_dispatch.md", "CS:[003A] two far pointers"),
    (0x7B7FE, 0x7B802, "data", "table", "notes/padding.md", "CS:[003A] FFFF:FFFF terminator"),
    (0x7B802, 0x7B80E, "data", "table", "notes/amx_first_dispatch.md", "kernel far-ptr table 000A:0078 / 901C:1130 / FB76:00B2"),
    (0x7B80E, 0x7B812, "data", "table", "notes/padding.md", "kernel far-ptr table FFFF:FFFF terminator"),
    (0x7B812, 0x7B813, "code", "code", "notes/amx_create_table.md", "FB76:00B2 RETF stub"),
    (0x7BA01, 0x7FF00, "data", "padding", "notes/padding.md", "unprogrammed ROM before wait-state stub"),
    (0x7FF00, 0x7FF44, "code", "code", "notes/boot_reset_to_bios_banner.md", "FFF0 wait-state stub"),
    (0x7FF44, 0x7FFF0, "data", "padding", "notes/boot_reset_to_bios_banner.md", "stub tail 0xFF"),
    (0x7FFF0, 0x7FFF5, "code", "code", "notes/boot_reset_to_bios_banner.md", "reset vector"),
    (0x7FFF5, 0x80000, "data", "padding", "notes/boot_reset_to_bios_banner.md", "post-reset 0xFF"),
)

_NOTE_RANGE = re.compile(
    r"\|\s*`\[(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+)\)`\s*\|\s*([^|]+)\|"
)


def _record(start: int, end: int, owner: str, kind: str, source: str, why: str) -> dict:
    return {
        "start": f"0x{start:05X}",
        "end": f"0x{end:05X}",
        "owner": owner,
        "kind": kind,
        "source": source,
        "why": why,
    }


def _parse_cs_ip(cs_ip: str) -> tuple[int, int]:
    cs, ip = cs_ip.split(":")
    return int(cs, 16), int(ip, 16)


def _merge_runs(raw: list[tuple[int, int]]) -> list[tuple[int, int]]:
    raw = sorted(raw)
    merged: list[tuple[int, int]] = []
    for start, end in raw:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _is_bounded(exits: list[dict], hit_limit: bool) -> bool:
    if hit_limit or not exits:
        return False
    kinds = {item["kind"] for item in exits}
    if kinds & {"unknown0f", "indirect", "call_indirect"}:
        return False
    return True


def transfer_insn_ranges(image: bytes) -> list[tuple[int, int]]:
    """Merged instruction-byte runs from every D16 local walk."""
    established = set(scan_entries(image)["_unique"])
    raw: list[tuple[int, int]] = []
    for cs_ip in established:
        cs, ip = _parse_cs_ip(cs_ip)
        insns, _extra, _hit = follow_entry(image, cs, ip, established)
        for insn in insns:
            raw.append((insn.file, insn.file + insn.length))
    return _merge_runs(raw)


def callee_insn_ranges(image: bytes) -> list[tuple[int, int]]:
    """Instruction bytes of bounded CALL dests of D16 entries.

    A dest is promoted only when a D16 walk names it and its own
    local walk is bounded. Indirect dests stay candidates.
    """
    established = set(scan_entries(image)["_unique"])
    dests: set[str] = set()
    for cs_ip in established:
        cs, ip = _parse_cs_ip(cs_ip)
        insns, _extra, _hit = follow_entry(image, cs, ip, established)
        for item in classify_exits(insns, established):
            if item["kind"] in ("callf", "calln") and not item.get("established"):
                dests.add(item["dest"])
    raw: list[tuple[int, int]] = []
    for dest in dests:
        cs, ip = _parse_cs_ip(dest)
        insns, extra, hit = follow_entry(image, cs, ip, established)
        exits = classify_exits(insns, established) + extra
        if not _is_bounded(exits, hit):
            continue
        for insn in insns:
            raw.append((insn.file, insn.file + insn.length))
    return _merge_runs(raw)


def _subtract_owned(
    runs: list[tuple[int, int]], owned: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    extra: list[tuple[int, int]] = []
    for start, end in runs:
        off = start
        while off < end:
            hit = next(((s, e) for s, e in owned if s <= off < e), None)
            if hit is not None:
                off = hit[1]
                continue
            nxt = end
            for seed_start, seed_end in owned:
                if off < seed_start < nxt:
                    nxt = seed_start
            extra.append((off, min(end, nxt)))
            off = min(end, nxt)
    return extra


def emit_ledger(image: bytes | None = None) -> dict:
    if image is None:
        image = load_vailixi_linear()
    seed = list(SEED_RANGES)
    owned_spans = [(start, end) for start, end, *_ in seed]
    extras = _subtract_owned(transfer_insn_ranges(image), owned_spans)
    for start, end in extras:
        seed.append(
            (
                start,
                end,
                "code",
                "code",
                "notes/transfer_scan.md",
                "D16 local-walk instruction bytes",
            )
        )
    owned_spans = [(start, end) for start, end, *_ in seed]
    callees = _subtract_owned(callee_insn_ranges(image), owned_spans)
    for start, end in callees:
        seed.append(
            (
                start,
                end,
                "code",
                "code",
                "notes/transfer_scan.md",
                "bounded CALL dest of a D16 entry",
            )
        )
    tmp_spans = [(start, end, "code", "code") for start, end, *_ in seed]
    for start, end in gaps(tmp_spans):
        if end - start == 1 and image[start] == 0x90:
            seed.append(
                (
                    start,
                    end,
                    "code",
                    "align",
                    "notes/transfer_scan.md",
                    "NOP between owned ranges",
                )
            )
    seed.sort(key=lambda rec: rec[0])
    ranges = []
    prev_end = -1
    for start, end, owner, kind, source, why in seed:
        if owner not in OWNERS:
            raise ValueError(f"illegal owner {owner!r}")
        if not (0 <= start < end <= IMAGE_SIZE):
            raise ValueError(f"bad span 0x{start:05X}-0x{end:05X}")
        if start < prev_end:
            raise ValueError(f"overlap or unsorted at 0x{start:05X}")
        ranges.append(_record(start, end, owner, kind, source, why))
        prev_end = end
    owned = sum(end - start for start, end, *_ in seed)
    return {
        "image_size": IMAGE_SIZE,
        "owners": list(OWNERS),
        "rule": "Gaps are debt. unresolved is not an owner. No excluded_workspace without a purpose.",
        "owned_bytes": owned,
        "ranges": ranges,
    }


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text())


def ledger_spans(ledger: dict) -> list[tuple[int, int, str, str]]:
    out = []
    for rec in ledger["ranges"]:
        out.append((int(rec["start"], 16), int(rec["end"], 16), rec["owner"], rec.get("kind", "")))
    return out


def gaps(spans: list[tuple[int, int, str, str]], image_size: int = IMAGE_SIZE) -> list[tuple[int, int]]:
    holes = []
    cursor = 0
    for start, end, *_ in sorted(spans):
        if start > cursor:
            holes.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < image_size:
        holes.append((cursor, image_size))
    return holes


def owner_at(spans: list[tuple[int, int, str, str]], offset: int) -> str | None:
    for start, end, owner, _kind in spans:
        if start <= offset < end:
            return owner
    return None


def kind_at(spans: list[tuple[int, int, str, str]], offset: int) -> str | None:
    for start, end, _owner, kind in spans:
        if start <= offset < end:
            return kind
    return None


def ff_runs(image: bytes, minimum: int = 4) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    i = 0
    n = len(image)
    while i < n:
        if image[i] == 0xFF:
            j = i
            while j < n and image[j] == 0xFF:
                j += 1
            if j - i >= minimum:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def validate_ff_windows(image: bytes, ledger: dict) -> int:
    spans = ledger_spans(ledger)
    n = 0
    for start, end in ff_runs(image, 4):
        n += 1
        if start == 0x7FFF4 and end == IMAGE_SIZE:
            if kind_at(spans, start) != "code":
                raise AssertionError("reset CS high byte is not in the reset vector")
            if any(kind_at(spans, off) != "padding" for off in range(0x7FFF5, IMAGE_SIZE)):
                raise AssertionError("post-reset 0xFF is not padding")
            continue
        kinds = {kind_at(spans, off) for off in range(start, end)}
        if kinds <= {"padding"}:
            continue
        if kinds <= {"create_table", "table"}:
            continue
        raise AssertionError(
            f"FF run [0x{start:05X}, 0x{end:05X}) has kinds {sorted(k or 'gap' for k in kinds)}"
        )
    return n


def validate_ledger(image: bytes, ledger: dict) -> list[str]:
    checks: list[str] = []
    if ledger["image_size"] != IMAGE_SIZE:
        raise AssertionError("ledger image_size is not 512 KiB")
    if list(ledger["owners"]) != list(OWNERS):
        raise AssertionError("ledger owners must be code, data, excluded_workspace")
    if any(name == "unresolved" for name in ledger["owners"]):
        raise AssertionError("unresolved is not an owner")

    expected = emit_ledger(image)
    if ledger["ranges"] != expected["ranges"]:
        raise AssertionError("analysis/owner_ledger.json does not match tools/owner_ledger.py seed")
    checks.append("ledger JSON matches seed")

    spans = ledger_spans(ledger)
    owned = 0
    prev_end = -1
    for start, end, owner, kind in spans:
        if owner not in OWNERS:
            raise AssertionError(f"illegal owner {owner} at 0x{start:05X}")
        if owner == "unresolved":
            raise AssertionError("unresolved used as an owner")
        if not (0 <= start < end <= IMAGE_SIZE):
            raise AssertionError(f"span 0x{start:05X}-0x{end:05X} outside image")
        if start < prev_end:
            raise AssertionError(f"overlap at 0x{start:05X}")
        if kind == "padding":
            if any(b != 0xFF for b in image[start:end]):
                raise AssertionError(f"padding 0x{start:05X}-0x{end:05X} is not all 0xFF")
        owned += end - start
        prev_end = end
    if owned != ledger["owned_bytes"]:
        raise AssertionError("owned_bytes does not match range sum")
    if any(rec["owner"] == "excluded_workspace" for rec in ledger["ranges"]):
        raise AssertionError("seed must not mark unanalyzed bytes excluded_workspace")
    checks.append(f"ledger {len(spans)} ranges, {owned} owned bytes, no overlap")

    holes = gaps(spans)
    if not holes:
        raise AssertionError("seed ledger unexpectedly covers the whole image")
    checks.append(f"ledger {len(holes)} gaps left as debt")
    n_ff = validate_ff_windows(image, ledger)
    checks.append(f"FF windows >=4 classified: {n_ff}")
    return checks


def _note_owner(cell: str) -> str:
    text = cell.strip().lower()
    if text.startswith("data"):
        return "data"
    if text.startswith("code"):
        return "code"
    raise AssertionError(f"note owner not code/data: {cell!r}")


def _ownership_section(text: str) -> str:
    mark = "Byte ownership"
    idx = text.find(mark)
    if idx < 0:
        return ""
    rest = text[idx:]
    nxt = rest.find("\n## ", 1)
    return rest if nxt < 0 else rest[:nxt]


def parse_note_ranges(notes_dir: Path = NOTES_DIR) -> list[tuple[int, int, str, str]]:
    found: list[tuple[int, int, str, str]] = []
    for path in sorted(notes_dir.glob("*.md")):
        section = _ownership_section(path.read_text(encoding="utf-8", errors="replace"))
        if not section:
            continue
        rel = f"notes/{path.name}"
        for match in _NOTE_RANGE.finditer(section):
            start = int(match.group(1), 16)
            end = int(match.group(2), 16)
            owner = _note_owner(match.group(3))
            found.append((start, end, owner, rel))
    return found


def notes_covered(ledger: dict, notes_dir: Path = NOTES_DIR) -> int:
    spans = ledger_spans(ledger)
    rows = parse_note_ranges(notes_dir)
    if not rows:
        raise AssertionError("no Byte ownership rows parsed from notes")
    for start, end, owner, rel in rows:
        off = start
        while off < end:
            hit = None
            for s, e, led_owner, _kind in spans:
                if s <= off < e:
                    hit = (s, e, led_owner)
                    break
            if hit is None:
                raise AssertionError(f"{rel} [0x{off:05X}, 0x{end:05X}) is not in the ledger")
            _s, e, led_owner = hit
            if owner == "data" and led_owner != "data":
                raise AssertionError(f"{rel} data 0x{off:05X} owned as {led_owner}")
            if owner == "code" and led_owner not in ("code", "data"):
                raise AssertionError(f"{rel} code 0x{off:05X} owned as {led_owner}")
            off = e
    return len(rows)


def write_ledger(path: Path = LEDGER_PATH) -> dict:
    ledger = emit_ledger()
    path.write_text(json.dumps(ledger, indent=2) + "\n")
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate analysis/owner_ledger.json")
    args = parser.parse_args()
    if args.write:
        ledger = write_ledger()
        print(f"wrote {LEDGER_PATH} ({len(ledger['ranges'])} ranges, {ledger['owned_bytes']} bytes)")
        return 0
    ledger = load_ledger()
    image = load_vailixi_linear()
    for item in validate_ledger(image, ledger):
        print(item)
    n = notes_covered(ledger)
    print(f"notes Byte-ownership rows covered: {n}")
    holes = gaps(ledger_spans(ledger))
    print(f"gaps: {len(holes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
