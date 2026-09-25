#!/usr/bin/env python3
"""Pin the ROM floppy startup loader in every EPROM OS image in `07-rom/`.

Chain (notes/floppy_loader.md): OS entry -> floppy test -> loader(arg 0)
-> find `????????????????` + `SYS` -> SYS hand-off `FB93:` -> INT 10
(third PGR) -> INT 45 MZ loader -> far jump to the loaded image.

    python3 tools/floppy_loader.py           # verify, write analysis/floppy_loader.json
    python3 tools/floppy_loader.py --check   # verify, compare with the JSON
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.linear_rom import interleave_ls_ms
from tools.v53_decode import Insn, decode_one

REPO_ROOT = Path(__file__).resolve().parents[1]
ROM_ROOT = REPO_ROOT / "07-rom"
OUT_PATH = REPO_ROOT / "analysis" / "floppy_loader.json"

STRINGS = {
    "floppy": b"Searching floppy for startup files...",
    "scsi": b"Searching SCSI for hard disk... <Cancel>",
    "loading": b"Loading files ...",
    "startup": b"STARTUP ????????",
    "wild": b"????????????????",
    "sys": b"SYS",
    "aps": b"APS",
    "pgm": b"PGM",
    "all": b"ALL",
}
INT45_SHA256 = "8edaf65787efb484a8aae0b3178f8f7416f3a4cca0ca813a5f901b91beb2ef31"
INT45_LEN = 468
LOADER_INSNS = 217
HANDOFF_INSNS = 48

# DGROUP ROM image sits at `dgroup` in the linear file and is copied to
# RAM `8010:0000` (notes/copy_7c92.md), so DS offset X is file dgroup+X.
VERSIONS = {
    "3.08": dict(chips=("v3.08/MPC3000_V3.08_LSB.BIN", "v3.08/MPC3000_V3.08_MSB.BIN"),
                 entry=(0xB6ED, 0x0000), test=(0xB6ED, 0x0355), loader=(0xB6ED, 0x0148),
                 handoff=0x0064, int45=0x013D, load_seg=0x7000, geometry=0x0319,
                 third_pgr=0x7AD29, dgroup=0x30000, str_base=0x11D1),
    "3.11": dict(chips=("v3.11/MPC311LS.BIN", "v3.11/MPC311MS.BIN"),
                 entry=(0xB000, 0x0074), test=(0xB000, 0x034E), loader=(0xB000, 0x0141),
                 handoff=0x005A, int45=0x0143, load_seg=0x7000, geometry=0x031F,
                 third_pgr=0x7ADCF, dgroup=0x20000, str_base=0x11D3),
    "3.12": dict(chips=("v3.12/MPC312LS.BIN", "v3.12/MPC312MS.BIN"),
                 entry=(0xB000, 0x0074), test=(0xB000, 0x034E), loader=(0xB000, 0x0141),
                 handoff=0x005C, int45=0x0143, load_seg=0x6900, geometry=0x031F,
                 third_pgr=0x7ADCF, dgroup=0x20000, str_base=0x11D3),
    "3.50": dict(chips=("Vailixi 3.50/3.50 Vailixi (LSE).BIN", "Vailixi 3.50/3.50 Vailixi (MSO).BIN"),
                 entry=(0xB000, 0x00DF), test=(0xB000, 0x03B4), loader=(0xB000, 0x01A7),
                 handoff=0x0066, int45=0x0143, load_seg=0x6900, geometry=0x031F,
                 third_pgr=0x7ADCF, dgroup=0x20000, str_base=0x11C9),
}
# Geometry slots: (total sectors, sectors/track) for 720K, 800K, 1.44M.
GEOMETRY = [(1440, 9), (1600, 10), (2880, 18)]


def file_of(cs: int, ip: int) -> int:
    return ((cs << 4) + ip) & 0x7FFFF


def u16(img: bytes, off: int) -> int:
    return img[off] | (img[off + 1] << 8)


def walk(img: bytes, cs: int, ip: int, end: str = "RETF", count: int = 1) -> list[Insn]:
    """Linear decode until the `count`-th `end`. Refuses to cross BRKXA/RETXA."""
    out: list[Insn] = []
    while True:
        insn = decode_one(img, cs, ip)
        if insn.kind in ("BRKXA", "RETXA"):
            raise AssertionError(f"{cs:04X}:{ip:04X} {insn.kind} inside a pinned routine")
        out.append(insn)
        ip += insn.length
        if insn.kind == end:
            count -= 1
            if count == 0:
                return out


def blob(img: bytes, insns: list[Insn]) -> bytes:
    return img[insns[0].file : insns[-1].file + insns[-1].length]


def push_imm(insns: list[Insn]) -> list[int]:
    return [int(i.bytes_hex[4:6] + i.bytes_hex[2:4], 16) for i in insns if i.bytes_hex[:2] == "68" and i.length == 3]


def mov_si(insns: list[Insn]) -> list[int]:
    return [int(i.bytes_hex[4:6] + i.bytes_hex[2:4], 16) for i in insns if i.bytes_hex[:2] == "be"]


def string_offsets(base: int) -> dict[str, int]:
    """The nine strings are one NUL-separated block in STRINGS order."""
    out, off = {}, base
    for name, text in STRINGS.items():
        out[name] = off
        off += len(text) + 1
    return out


def expect(cond: bool, what: str) -> None:
    if not cond:
        raise AssertionError(what)


def load(version: str) -> bytes:
    ls, ms = (ROM_ROOT / p for p in VERSIONS[version]["chips"])
    return interleave_ls_ms(ls.read_bytes(), ms.read_bytes())


def pin(version: str, img: bytes) -> dict:
    v = VERSIONS[version]
    tag = f"{version}:"
    strs = string_offsets(v["str_base"])
    for name, off in strs.items():
        f = v["dgroup"] + off
        expect(img[f : f + len(STRINGS[name]) + 1] == STRINGS[name] + b"\0", f"{tag} string {name} at 0x{f:05X}")

    entry = walk(img, *v["entry"])
    expect(entry[0].bytes_hex + entry[1].bytes_hex == "5633f6", f"{tag} entry prologue PUSH SI / XOR SI,SI")
    pushes = push_imm(entry)
    expect(pushes.count(strs["floppy"]) == 1 and pushes.count(strs["scsi"]) == 1, f"{tag} entry string pushes")
    near = [(i.target_cs, i.target_ip) for i in entry if i.kind == "CALLN"]
    expect(near[-3:] == [v["test"], v["loader"], v["loader"]], f"{tag} entry near calls {near}")
    args = [entry[k - 3].bytes_hex for k, i in enumerate(entry) if i.kind == "CALLN" and (i.target_cs, i.target_ip) == v["loader"]]
    expect(args == ["6a00", "6a01"], f"{tag} loader call args {args}")

    test = walk(img, *v["test"])
    expect([i.kind for i in test] == ["CALLF", "RETF"], f"{tag} floppy test stub")

    loader = walk(img, *v["loader"])
    expect(len(loader) == LOADER_INSNS, f"{tag} loader length {len(loader)}")
    expect(push_imm(loader).count(strs["loading"]) == 1, f"{tag} loader pushes Loading files")
    expect(mov_si(loader)[:6] == [strs[k] for k in ("startup", "wild", "sys", "aps", "pgm", "all")],
           f"{tag} loader pattern/extension order")
    far = [(i.target_cs, i.target_ip) for i in loader if i.kind == "CALLF"]
    expect(far.count((0xFB93, v["handoff"])) == 1, f"{tag} loader CALLF FB93:{v['handoff']:04X}")

    handoff = walk(img, 0xFB93, v["handoff"])
    hb = blob(img, handoff).hex()
    seg = v["load_seg"].to_bytes(2, "little").hex()
    expect(len(handoff) == HANDOFF_INSNS, f"{tag} hand-off length {len(handoff)}")
    for frag, what in (("bcc469fbcd10", "SS:SP=0040:69C4, INT 10"), (f"b8{seg}8ec0cd45", "ES=load seg, INT 45"),
                       ("ff2ec068", "JMP FAR [68C0]"), ("cd11ebfc", "INT 11 spin")):
        expect(frag in hb, f"{tag} hand-off {what}")

    int45 = walk(img, 0xF800, v["int45"], "IRET", 2)
    ib = blob(img, int45)
    expect(len(ib) == INT45_LEN and hashlib.sha256(ib).hexdigest() == INT45_SHA256, f"{tag} INT 45 bytes")
    ivt45 = img.find(bytes([0xB8]) + v["int45"].to_bytes(2, "little") + bytes.fromhex("a31401"), 0x78000)
    expect(ivt45 > 0, f"{tag} BIOS plants IVT[45h]=F800:{v['int45']:04X}")

    pgr = [u16(img, v["third_pgr"] + 2 * n) for n in range(64)]
    expect(pgr == [0xC0 + n for n in range(61)] + [0x140, 0x3E, 0x3F], f"{tag} third PGR")

    g = 0x78000 + v["geometry"]
    slots = [u16(img, g + 2 * k) for k in range(3)]
    got = [(u16(img, 0x78000 + s + 8), u16(img, 0x78000 + s + 0x0D)) for s in slots]
    expect(got == GEOMETRY, f"{tag} geometry slots {got}")

    def rec(cs: int, ip: int, insns: list[Insn]) -> dict:
        b = blob(img, insns)
        return {"cs_ip": f"{cs:04X}:{ip:04X}", "file": f"0x{insns[0].file:05X}", "end_file": f"0x{insns[-1].file:05X}",
                "insns": len(insns), "sha256": hashlib.sha256(b).hexdigest(), "bytes": b.hex()}

    return {
        "linear_sha256": hashlib.sha256(img).hexdigest(),
        "load_segment": f"0x{v['load_seg']:04X}",
        "strings": {k: {"ds": f"0x{o:04X}", "file": f"0x{v['dgroup'] + o:05X}", "text": STRINGS[k].decode()} for k, o in strs.items()},
        "os_entry": rec(*v["entry"], entry),
        "floppy_test": rec(*v["test"], test) | {"target": f"{test[0].target_cs:04X}:{test[0].target_ip:04X}"},
        "loader": rec(*v["loader"], loader),
        "sys_handoff": rec(0xFB93, v["handoff"], handoff),
        "int45_mz_loader": rec(0xF800, v["int45"], int45) | {"ivt_store_file": f"0x{ivt45:05X}"},
        "third_pgr_file": f"0x{v['third_pgr']:05X}",
        "geometry_table": {"cs_ip": f"F800:{v['geometry']:04X}", "slots": [f"F800:{s:04X}" for s in slots]},
    }


def build() -> dict:
    return {version: pin(version, load(version)) for version in VERSIONS}


def check(path: Path = OUT_PATH) -> list[str]:
    facts = build()
    expect(json.loads(path.read_text()) == facts, f"{path} is stale; rerun tools/floppy_loader.py")
    return [f"floppy loader {v}: entry {f['os_entry']['cs_ip']} loader {f['loader']['cs_ip']} "
            f"hand-off {f['sys_handoff']['cs_ip']} seg {f['load_segment']}" for v, f in facts.items()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        lines = check()
    else:
        facts = build()
        OUT_PATH.write_text(json.dumps(facts, indent=1) + "\n")
        lines = [f"wrote {OUT_PATH.relative_to(REPO_ROOT)}"]
    print("\n".join(["PASS"] + lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
