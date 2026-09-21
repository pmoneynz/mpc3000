"""Bounded 8086/V53 instruction-length decoder for boot-slice work.

Treats `0F E0 ib` / `0F F0 ib` as BRKXA/RETXA. Does not claim 8086
equivalence beyond lengths needed to partition this image.
"""

from __future__ import annotations

from dataclasses import dataclass


def _modrm_extra(modrm: int) -> int:
    mod = modrm >> 6
    rm = modrm & 7
    if mod == 3:
        return 0
    if mod == 0:
        return 2 if rm == 6 else 0
    if mod == 1:
        return 1
    return 2


def _has_modrm(op: int) -> bool:
    if op in (0x0F,):
        return False
    # ALU / r,imm groups with modrm
    if op in (
        0x00,
        0x01,
        0x02,
        0x03,
        0x08,
        0x09,
        0x0A,
        0x0B,
        0x10,
        0x11,
        0x12,
        0x13,
        0x18,
        0x19,
        0x1A,
        0x1B,
        0x20,
        0x21,
        0x22,
        0x23,
        0x28,
        0x29,
        0x2A,
        0x2B,
        0x30,
        0x31,
        0x32,
        0x33,
        0x38,
        0x39,
        0x3A,
        0x3B,
        0x84,
        0x85,
        0x86,
        0x87,
        0x88,
        0x89,
        0x8A,
        0x8B,
        0x8C,
        0x8D,
        0x8E,
        0x8F,
        0xC0,
        0xC1,
        0xC4,
        0xC5,
        0xC6,
        0xC7,
        0xD0,
        0xD1,
        0xD2,
        0xD3,
        0xD8,
        0xD9,
        0xDA,
        0xDB,
        0xDC,
        0xDD,
        0xDE,
        0xDF,
        0xF6,
        0xF7,
        0xFE,
        0xFF,
        0x62,
        0x63,
        0x69,
        0x6B,
    ):
        return True
    if op in range(0x80, 0x84):
        return True
    return False


def _imm_len(op: int, modrm: int | None) -> int:
    if op in (0x04, 0x0C, 0x14, 0x1C, 0x24, 0x2C, 0x34, 0x3C):
        return 1
    if op in (0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D):
        return 2
    if op in range(0x70, 0x80) or op in (0xE0, 0xE1, 0xE2, 0xE3, 0xEB):
        return 1
    if op == 0xE8 or op == 0xE9:
        return 2
    if op == 0xEA or op == 0x9A:
        return 4
    if op in range(0xB0, 0xB8):
        return 1
    if op in range(0xB8, 0xC0):
        return 2
    if op in (0xC2, 0xCA):
        return 2
    if op in (0xC8,):
        return 3
    if op in (0xCD,):
        return 1
    if op in (0xD4, 0xD5):
        return 1
    if op in (0xE4, 0xE5, 0xE6, 0xE7):
        return 1
    if op in (0x68,):
        return 2
    if op in (0x6A,):
        return 1
    if op in (0xA0, 0xA1, 0xA2, 0xA3):
        return 2
    if op in (0xA8,):
        return 1
    if op in (0xA9,):
        return 2
    if op in (0x80, 0x82, 0x83):
        return 1
    if op == 0x81:
        return 2
    if op in (0xC0, 0xC1):
        return 1
    if op in (0xC6,):
        return 1
    if op in (0xC7,):
        return 2
    if op in (0xF6, 0xF7) and modrm is not None:
        # /0 test has immediate
        if ((modrm >> 3) & 7) == 0:
            return 1 if op == 0xF6 else 2
    if op in (0x69,):
        return 2
    if op in (0x6B,):
        return 1
    return 0


@dataclass(frozen=True)
class Insn:
    file: int
    cs: int
    ip: int
    length: int
    bytes_hex: str
    kind: str
    text: str
    target_cs: int | None = None
    target_ip: int | None = None


def decode_one(image: bytes, cs: int, ip: int) -> Insn:
    file_off = ((cs << 4) + ip) & 0x7FFFF
    if file_off >= len(image):
        raise ValueError(f"fetch off image CS:IP={cs:04X}:{ip:04X}")
    start = file_off
    prefixes = 0
    while image[file_off] in (0x26, 0x2E, 0x36, 0x3E, 0x64, 0x65, 0x66, 0x67, 0xF0, 0xF2, 0xF3):
        prefixes += 1
        file_off += 1
        if prefixes > 4:
            break
    op = image[file_off]
    file_off += 1

    if op == 0x0F:
        op2 = image[file_off]
        file_off += 1
        if op2 in (0xE0, 0xF0):
            vec = image[file_off]
            file_off += 1
            name = "BRKXA" if op2 == 0xE0 else "RETXA"
            raw = image[start:file_off]
            return Insn(
                start,
                cs,
                ip,
                len(raw),
                raw.hex(),
                name,
                f"{name} 0x{vec:02X}",
            )
        raw = image[start:file_off]
        return Insn(start, cs, ip, len(raw), raw.hex(), "UNKNOWN_0F", f"db 0F {op2:02X}")

    modrm = None
    if _has_modrm(op):
        modrm = image[file_off]
        file_off += 1
        file_off += _modrm_extra(modrm)

    file_off += _imm_len(op, modrm)
    raw = image[start:file_off]
    kind = "op"
    text = raw.hex()
    tcs = tip = None

    if op == 0xEA:
        tip = raw[-4] | (raw[-3] << 8)
        tcs = raw[-2] | (raw[-1] << 8)
        kind = "JMPF"
        text = f"jmp {tcs:04X}:{tip:04X}"
    elif op == 0x9A:
        tip = raw[-4] | (raw[-3] << 8)
        tcs = raw[-2] | (raw[-1] << 8)
        kind = "CALLF"
        text = f"call {tcs:04X}:{tip:04X}"
    elif op == 0xEB:
        rel = raw[-1]
        if rel >= 128:
            rel -= 256
        tip = (ip + len(raw) + rel) & 0xFFFF
        tcs = cs
        kind = "JMPS"
        text = f"jmp short {cs:04X}:{tip:04X}"
    elif op == 0xE9:
        rel = raw[-2] | (raw[-1] << 8)
        if rel >= 0x8000:
            rel -= 0x10000
        tip = (ip + len(raw) + rel) & 0xFFFF
        tcs = cs
        kind = "JMPN"
        text = f"jmp near {cs:04X}:{tip:04X}"
    elif op == 0xE8:
        rel = raw[-2] | (raw[-1] << 8)
        if rel >= 0x8000:
            rel -= 0x10000
        tip = (ip + len(raw) + rel) & 0xFFFF
        tcs = cs
        kind = "CALLN"
        text = f"call near {cs:04X}:{tip:04X}"
    elif 0x70 <= op <= 0x7F or op in (0xE0, 0xE1, 0xE2, 0xE3):
        rel = raw[-1]
        if rel >= 128:
            rel -= 256
        tip = (ip + len(raw) + rel) & 0xFFFF
        tcs = cs
        kind = "JCC"
        text = f"jcc {cs:04X}:{tip:04X}"
    elif op == 0xCB:
        kind = "RETF"
        text = "retf"
    elif op == 0xC3:
        kind = "RET"
        text = "ret"
    elif op == 0xCF:
        kind = "IRET"
        text = "iret"
    elif op == 0xC2:
        kind = "RETN"
        text = "retn"
    elif op == 0xCA:
        kind = "RETFN"
        text = "retf n"
    elif op == 0xFF and modrm is not None:
        grp = (modrm >> 3) & 7
        if grp == 4:
            kind = "JMPN_RM"
            text = "jmp near [rm]"
        elif grp == 5:
            kind = "JMPF_RM"
            text = "jmp far [rm]"
        elif grp == 2:
            kind = "CALLN_RM"
            text = "call near [rm]"
        elif grp == 3:
            kind = "CALLF_RM"
            text = "call far [rm]"

    return Insn(start, cs, ip, len(raw), raw.hex(), kind, text, tcs, tip)


def follow(image: bytes, cs: int, ip: int, *, limit: int = 400) -> list[Insn]:
    """Linear-ish CFG: follow fallthrough and taken branches; stop at RETF/JMPF/indirect."""
    seen: set[tuple[int, int]] = set()
    work = [(cs, ip)]
    out: list[Insn] = []
    while work and len(out) < limit:
        c, i = work.pop(0)
        if (c, i) in seen:
            continue
        seen.add((c, i))
        insn = decode_one(image, c, i)
        out.append(insn)
        if insn.kind in ("RETF", "RET", "IRET", "RETN", "RETFN", "JMPF_RM", "JMPN_RM"):
            continue
        if insn.kind == "UNKNOWN_0F":
            continue
        fall_ip = (i + insn.length) & 0xFFFF
        if insn.kind == "JMPF":
            work.append((insn.target_cs or 0, insn.target_ip or 0))
            continue
        if insn.kind in ("JMPS", "JMPN"):
            work.append((insn.target_cs or c, insn.target_ip or 0))
            continue
        if insn.kind == "JCC":
            work.append((c, fall_ip))
            work.append((insn.target_cs or c, insn.target_ip or 0))
            continue
        if insn.kind in ("CALLN", "CALLF", "CALLN_RM", "CALLF_RM", "BRKXA", "RETXA"):
            # do not enter callees; continue after the call
            work.append((c, fall_ip))
            continue
        work.append((c, fall_ip))
    out.sort(key=lambda x: (x.cs, x.ip))
    return out
