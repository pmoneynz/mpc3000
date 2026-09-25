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
    (0x30630, 0x30644, "code", "code", "notes/transfer_scan.md", "B060:0030 DEC/LES thunk through RETF; CALLN from B060:0064"),
    (0x30644, 0x3095D, "code", "code", "notes/transfer_scan.md", "B060:0044 through 02D6 packed CALLN leftovers through RETF"),
    (0x30D01, 0x30D15, "data", "jump_table", "notes/transfer_scan.md", "B060 JMP CS:[BX+0701] 10 near IPs"),
    (0x30D15, 0x30E6E, "code", "code", "notes/transfer_scan.md", "B060:0715 cdecl through RETF; CALLN B060:05E8/0601/0611"),
    (0x30E6E, 0x30EE6, "code", "code", "notes/transfer_scan.md", "B060:086E cdecl through RETF; CALLN B060:0769"),
    (0x30F82, 0x30FB1, "code", "code", "notes/transfer_scan.md", "B060:0982 cdecl through RETF; CALLN B060:07B1"),
    (0x30FB1, 0x30FE4, "code", "code", "notes/transfer_scan.md", "B060:09B1 cdecl through RETF; CALLN B060:098D"),
    (0x30FE4, 0x31004, "code", "code", "notes/transfer_scan.md", "B060:09E4 cdecl through RETF; CALLN B060:09A9"),
    (0x31004, 0x3104A, "code", "code", "notes/transfer_scan.md", "B060:0A04 cdecl through RETF; CALLN B060:099B"),
    (0x3104A, 0x3107B, "code", "code", "notes/transfer_scan.md", "B060:0A4A cdecl through RETF; CALLN B060:07D7"),
    (0x3107B, 0x310D9, "code", "code", "notes/transfer_scan.md", "B060:0A7B cdecl through RETF; CALLF B2A0:0007/B31B:0007"),
    (0x31258, 0x3126C, "data", "jump_table", "notes/transfer_scan.md", "B060 JMP CS:[BX+0C58] 10 near IPs"),
    (0x3126C, 0x312BF, "code", "code", "notes/transfer_scan.md", "B060:0C6C cdecl through RETF; CALLF C303:04A9"),
    (0x312BF, 0x31304, "code", "code", "notes/transfer_scan.md", "B060:0CBF cdecl through RETF; CALLF BE1A:04D1/04E1"),
    (0x31304, 0x31370, "code", "code", "notes/transfer_scan.md", "B060:0D04 through RETF; CALLF EBC8:00B0"),
    (0x314B2, 0x3156E, "code", "code", "notes/amx_create_table.md", "create-table task 5 through RETF"),
    (0x31B32, 0x31B36, "code", "code", "notes/transfer_scan.md", "B1B1:0022 MOV AX,[1D1A] RETF; CALLF DE5C:0040"),
    (0x31B6B, 0x31B91, "code", "code", "notes/string_scan.md", "B1B1:005B put-string INT 43 AX=4"),
    (0x31C00, 0x31C6F, "code", "code", "notes/transfer_scan.md", "B1BC:0040 LES DI SCASB count RETF; CALLN B1BC:0382"),
    (0x31FE2, 0x31FFC, "data", "jump_table", "notes/transfer_scan.md", "B1BC JMP CS:[BX+0422] 13 near IPs"),
    (0x320A4, 0x321AF, "code", "code", "notes/transfer_scan.md", "B20A:0004 cdecl through RETF; CALLF EB1A:0155/025F/030D"),
    (0x32596, 0x32600, "code", "code", "notes/amx_create_table.md", "create-table task 1 through RETF"),
    (0x3261A, 0x32811, "code", "code", "notes/transfer_scan.md", "B261:000A cdecl through RETF; CALLF B060:0A7B/08E6/0715"),
    (0x32883, 0x32922, "code", "code", "notes/transfer_scan.md", "B261:0273 cdecl through RETF; CALLN from 000A; CALLF B060:08E6"),
    (0x32922, 0x32928, "code", "code", "notes/transfer_scan.md", "B261:0312 MOV [E748],0 RETF; CALLF B060:03B7"),
    (0x32928, 0x32A07, "code", "code", "notes/transfer_scan.md", "B292:0008 cdecl through RETF; CALLF B060:06A1"),
    (0x32A07, 0x32BA3, "code", "code", "notes/transfer_scan.md", "B2A0:0007 cdecl through RETF; CALLF B060:0691"),
    (0x32DAF, 0x32E79, "code", "code", "notes/transfer_scan.md", "B2DA:000F cdecl through RETF; CALLF B060:0681"),
    (0x32F12, 0x331B7, "code", "code", "notes/transfer_scan.md", "B2F1:0002 cdecl through RETF; CALLF B060:0661"),
    (0x331B7, 0x333C4, "code", "code", "notes/transfer_scan.md", "B31B:0007 cdecl through RETF; CALLF B060:063D"),
    (0x33B38, 0x33B8E, "code", "code", "notes/transfer_scan.md", "B354:05F8 cdecl through RETF; CALLF C303:00D4"),
    (0x33EDF, 0x33FD6, "code", "code", "notes/transfer_scan.md", "B3ED:000F cdecl through RETF; CALLF C425:01B5"),
    (0x33FD6, 0x34841, "code", "code", "notes/transfer_scan.md", "B3FD:0006 through three JMP CS:[BX]; CALLF C425:011F"),
    (0x34841, 0x3485D, "data", "jump_table", "notes/transfer_scan.md", "B3FD JMP CS:[BX+0871] 14 near IPs BX<=0x0D then SHL 1"),
    (0x3485D, 0x34877, "data", "jump_table", "notes/transfer_scan.md", "B3FD JMP CS:[BX+088D] 13 near IPs BX<=0x0C then SHL 1"),
    (0x34877, 0x34893, "data", "jump_table", "notes/transfer_scan.md", "B3FD JMP CS:[BX+08A7] 14 near IPs BX<=0x0D then SHL 1"),
    (0x34893, 0x34923, "code", "code", "notes/transfer_scan.md", "B3FD:08C3 cdecl through RETF; CALLN B3FD:029E/03B7"),
    (0x34923, 0x3494B, "code", "code", "notes/transfer_scan.md", "B3FD:0953 cdecl through RETF; CALLN B3FD:03CA"),
    (0x3494B, 0x3497C, "code", "code", "notes/transfer_scan.md", "B3FD:097B cdecl through RETF; CALLN B3FD:025A/032E"),
    (0x3497C, 0x349B2, "code", "code", "notes/transfer_scan.md", "B3FD:09AC cdecl through RETF; CALLN B3FD:011D/0345"),
    (0x349B2, 0x349FF, "code", "code", "notes/transfer_scan.md", "B3FD:09E2 cdecl through RETF; CALLN B3FD:05FD/06A2"),
    (0x349FF, 0x34A66, "code", "code", "notes/transfer_scan.md", "B3FD:0A2F cdecl through RETF; CALLN B3FD:052B/05BB"),
    (0x34A66, 0x34A9C, "code", "code", "notes/transfer_scan.md", "B3FD:0A96 through RETF; CALLN from B3FD:0500"),
    (0x3E1A2, 0x3E292, "code", "code", "notes/transfer_scan.md", "BE1A:0002 through JMP CS:[BX+01FB]; CALLF C425:01F6"),
    (0x3E292, 0x3E335, "code", "code", "notes/transfer_scan.md", "BE1A 01FB dests 00F2/0105/0131/0185"),
    (0x3E335, 0x3E39B, "code", "code", "notes/transfer_scan.md", "BE1A shared 0195 through RETF"),
    (0x3E39B, 0x3E3A3, "data", "jump_table", "notes/transfer_scan.md", "BE1A JMP CS:[BX+01FB] 4 near IPs BX<=3 then SHL 1"),
    (0x3E3A3, 0x3E3CB, "code", "code", "notes/transfer_scan.md", "BE1A:0203 cdecl through RETF; CALLN BE1A:0070/010C/0160"),
    (0x3E3CB, 0x3E40C, "code", "code", "notes/transfer_scan.md", "BE1A:022B cdecl through RETF; CALLN BE1A:0129/017D/018F"),
    (0x3E40C, 0x3E7CF, "code", "code", "notes/transfer_scan.md", "BE1A:026C through three JMP CS:[BX]; CALLF C425:0200"),
    (0x3E7CF, 0x3E7D7, "data", "jump_table", "notes/transfer_scan.md", "BE1A JMP CS:[BX+062F] 4 near IPs BX<=3 then SHL 1"),
    (0x3E7D7, 0x3E7E1, "data", "jump_table", "notes/transfer_scan.md", "BE1A JMP CS:[BX+0637] 5 near IPs BX<=4 then SHL 1"),
    (0x3E7E1, 0x3E7E9, "data", "jump_table", "notes/transfer_scan.md", "BE1A JMP CS:[BX+0641] 4 near IPs BX<=3 then SHL 1"),
    (0x42D0C, 0x42E67, "code", "code", "notes/transfer_scan.md", "C2D0:000C cdecl through RETF; CALLF C425:012F"),
    (0x42E67, 0x43034, "code", "code", "notes/transfer_scan.md", "C2E6:0007 cdecl through RETF; CALLF C425:019B"),
    (0x43034, 0x43BFC, "code", "code", "notes/transfer_scan.md", "C303:0004 through two JMP CS:[BX]; CALLF C425:0106"),
    (0x43BFC, 0x43C18, "data", "jump_table", "notes/transfer_scan.md", "C303 JMP CS:[BX+0BCC] 14 near IPs BX<=0x0D then SHL 1"),
    (0x43C18, 0x43C3E, "data", "jump_table", "notes/transfer_scan.md", "C303 JMP CS:[BX+0BE8] 19 near IPs BX<=0x12 then SHL 1"),
    (0x43C3E, 0x43C94, "code", "code", "notes/transfer_scan.md", "C303:0C0E cdecl through RETF; CALLN C303:0465/04D3"),
    (0x43C94, 0x43D1E, "code", "code", "notes/transfer_scan.md", "C303:0C64 cdecl through RETF; CALLN C303:067B/09CF/09F9"),
    (0x43D1E, 0x43D77, "code", "code", "notes/transfer_scan.md", "C303:0CEE through RETF; CALLN from C303:04DB"),
    (0x43D77, 0x43DA6, "code", "code", "notes/transfer_scan.md", "C303:0D47 PUSH 0/6 put-string through RETF; CALLF B1B1/EA97"),
    (0x43DA6, 0x44259, "code", "code", "notes/transfer_scan.md", "C303:0D76 through 11C4 packed CALLN leftovers through RETF"),
    (0x44483, 0x444B9, "data", "jump_table", "notes/transfer_scan.md", "C425 JMP CS:[BX+0233] 27 near IPs"),
    (0x444B9, 0x444E5, "code", "code", "notes/transfer_scan.md", "C425:0269 cdecl through RETF; CALLN C425:0220"),
    (0x444E5, 0x44535, "code", "code", "notes/transfer_scan.md", "C44E:0005 through JMP CS:[BX+00B8]; CALLF C425:01BF"),
    (0x44535, 0x44598, "code", "code", "notes/transfer_scan.md", "C44E 00B8 dests 0055..0079 plus shared RETF 00B3"),
    (0x44598, 0x445A2, "data", "jump_table", "notes/transfer_scan.md", "C44E JMP CS:[BX+00B8] 5 near IPs BX<=4 then SHL 1"),
    (0x445A2, 0x445F9, "code", "code", "notes/transfer_scan.md", "C44E:00C2 cdecl through RETF; CALLN from C44E:01C5"),
    (0x445F9, 0x4479F, "code", "code", "notes/transfer_scan.md", "C44E:0119 cdecl through RETF; CALLN from C44E:0057"),
    (0x4479F, 0x4492D, "code", "code", "notes/transfer_scan.md", "C44E:02BF through RETF; CALLN C44E:0060; both BX switches stay inside"),
    (0x4492D, 0x44945, "data", "jump_table", "notes/transfer_scan.md", "C44E JMP CS:[BX+044D] and [BX+0459], 6 near IPs each; index (SI-0x75)<=5"),
    (0x44945, 0x44965, "code", "code", "notes/transfer_scan.md", "C44E:0465 through RETF; CALLN from C44E:02F0 and 039A"),
    (0x44965, 0x44B96, "code", "code", "notes/transfer_scan.md", "C44E:0485 cdecl through RETF; CALLN from C44E:0069"),
    (0x44B96, 0x44BEF, "code", "code", "notes/transfer_scan.md", "C44E:06B6 cdecl through RETF; CALLN from C44E:05ED"),
    (0x44BEF, 0x44C8D, "code", "code", "notes/transfer_scan.md", "C44E:070F cdecl through RETF; CALLN from C44E:0072"),
    (0x44C8D, 0x44D19, "code", "code", "notes/transfer_scan.md", "C4C8:000D through RETF; CALLF from C425:0160; slot callees not entered"),
    (0x44D19, 0x44D23, "data", "jump_table", "notes/transfer_scan.md", "C4C8 JMP CS:[BX+0099] 5 near IPs; index (SX [BP-1])-1, JA if >4"),
    (0x44D23, 0x45059, "code", "code", "notes/transfer_scan.md", "C4C8:00A3 through RETF; CALLN from slot 006B; near callees not entered"),
    (0x450C8, 0x45110, "code", "code", "notes/transfer_scan.md", "C4C8:0448 through RETF; CALLN from 00A3 at 0186/019E/01B6; 0927 and 0EC9 not entered"),
    (0x45110, 0x45179, "code", "code", "notes/transfer_scan.md", "C4C8:0490 through RETF; CALLN from 00A3 at 00F0/035E; zeros DS:1591 for 0x3C0 words"),
    (0x45179, 0x45239, "code", "code", "notes/transfer_scan.md", "C4C8:04F9 through RETF; CALLN from 00A3 at 02E6 and from 0490 at 04E9; B13A:0000 not entered"),
    (0x45239, 0x452F8, "code", "code", "notes/transfer_scan.md", "C4C8:05B9 through RETF; CALLN from 00A3 at 0336 and from 0490 at 04BF; B13A:0000 not entered"),
    (0x455A7, 0x45602, "code", "code", "notes/transfer_scan.md", "C4C8:0927 through RETF; CALLN from 00A3 at 01EB/0220/02A9 and from 0448 at 045C/0486; B13A:0000 not entered"),
    (0x45602, 0x4569E, "code", "code", "notes/transfer_scan.md", "C4C8:0982 through RETF; CALLN from 0490 at 04B4; 0FB1 and B13A:0000 not entered"),
    (0x45719, 0x4576F, "code", "code", "notes/transfer_scan.md", "C4C8:0A99 through RETF; CALLN from 0490 at 04A9 with argument 0; sets bits at DS:1591"),
    (0x458E4, 0x45971, "code", "code", "notes/transfer_scan.md", "C4C8:0C64 through both RETFs; CALLN from 00A3 at 0375; 0C35 not entered"),
    (0x458B5, 0x458E4, "code", "code", "notes/transfer_scan.md", "C4C8:0C35 through both RETFs; CALLN from 0C64 at 0C89/0CA3; 0AEF and 0B8F not entered"),
    (0x4576F, 0x4580F, "code", "code", "notes/transfer_scan.md", "C4C8:0AEF through both RETFs; CALLN from 0C35 at 0C5C; calls owned 04F9 and 05B9"),
    (0x4580F, 0x458B5, "code", "code", "notes/transfer_scan.md", "C4C8:0B8F through both RETFs; CALLN from 0C35 at 0C4C; clamps DX at 0x64"),
    (0x45B49, 0x45B8D, "code", "code", "notes/transfer_scan.md", "C4C8:0EC9 through RETF; CALLN from 00A3 at 01D9/020E/027E/029B and from 0448 at 0474; B13A:0000 not entered"),
    (0x45BDF, 0x45C19, "code", "code", "notes/transfer_scan.md", "C4C8:0F5F through RETF; CALLN from 00A3 at 039F and from 0490 at 04E1; stores 1 at [98DC]"),
    (0x45B8D, 0x45BDF, "code", "code", "notes/transfer_scan.md", "C4C8:0F0D through RETF; CALLN from 0F5F at 0F95; popcount of 0x780 bytes at [SI+1591]"),
    (0x45C31, 0x45C5F, "code", "code", "notes/transfer_scan.md", "C4C8:0FB1 through both RETFs; CALLN from 0982 at 09C6; scans [SI+13E5] for [BP+6]"),
        (0x45C5F, 0x45F29, "code", "code", "notes/transfer_scan.md", "C4C8:0FDF through RETF; CALLN from slot 0074; 0678, 06E1, and 0E5A not entered"),
        (0x45F29, 0x4611B, "code", "code", "notes/transfer_scan.md", "C4C8:12A9 reached run through JMP CS:[BX+1850]; CALLN from slot 007D"),
        (0x46129, 0x46137, "code", "code", "notes/transfer_scan.md", "C4C8:14A9 PUSH DS / PUSH imm16 0x54BA / CALLF B1B1:005B / ADD SP,4 / JMPS 14D3; 1850 slots BX==2 and BX==3; meets owned 14D3"),
        (0x46137, 0x46145, "code", "code", "notes/transfer_scan.md", "C4C8:14B7 PUSH DS / PUSH imm16 0x54BF / CALLF B1B1:005B / ADD SP,4 / JMPS 14D3; 1850 slots BX==4 and BX==5; meets owned 14D3"),
        (0x46153, 0x461CB, "code", "code", "notes/transfer_scan.md", "C4C8:12A9 reached run through JMP CS:[BX+1844]"),
        (0x46364, 0x4637D, "code", "code", "notes/transfer_scan.md", "C4C8:16E4 MOV AL,[BP-1] / CBW / PUSH AX / CALLF CFC6:02D6 / ADD SP,2 / MOV BL,[BP-2] / MOV ES,DX / XCHG AX,BX / MOV ES:[BX],AL / JMP 17C8; 1844 slot BX==1; meets owned 17C8"),
        (0x4637D, 0x46397, "code", "code", "notes/transfer_scan.md", "C4C8:16FD MOV AL,[BP-1] / CBW / PUSH AX / CALLF CFC6:033A / ADD SP,2 / MOV BL,[BP-4] / MOV ES,DX / XCHG AX,BX / MOV ES:[BX+2],AL / JMP 17C8; 1844 slot BX==2; meets owned 17C8"),
        (0x46397, 0x463B1, "code", "code", "notes/transfer_scan.md", "C4C8:1717 MOV AL,[BP-1] / CBW / PUSH AX / CALLF CFC6:02D6 / ADD SP,2 / MOV BL,[BP-3] / MOV ES,DX / XCHG AX,BX / MOV ES:[BX+1],AL / JMP 17C8; 1844 slot BX==3; meets owned 17C8"),
        (0x46448, 0x4646D, "code", "code", "notes/transfer_scan.md", "C4C8:12A9 reached run through JMP CS:[BX+1818]"),
        (0x46476, 0x4647E, "code", "code", "notes/transfer_scan.md", "C4C8:17F6 PUSH CS / CALL 12A9 / MOV DX,AX / JMPS 180C; 1818 slot BX==4; meets owned 180C"),
        (0x4647E, 0x46486, "code", "code", "notes/transfer_scan.md", "C4C8:17FE PUSH CS / CALL 12A9 / MOV DX,AX / JMPS 180C; 1818 slot BX==5; meets owned 180C"),
        (0x4648C, 0x46498, "code", "code", "notes/transfer_scan.md", "C4C8:12A9 exit; DX==0 jumps to 12B5 else RETF"),
        (0x46498, 0x464A4, "data", "jump_table", "notes/transfer_scan.md", "C4C8 JMP CS:[BX+1818] 6 near IPs (DX-0x75)<=5 then SHL 1"),
        (0x464C4, 0x464D0, "data", "jump_table", "notes/transfer_scan.md", "C4C8 JMP CS:[BX+1844] 6 near IPs BX<=5 then SHL 1"),
        (0x464D0, 0x464E0, "data", "jump_table", "notes/transfer_scan.md", "C4C8 JMP CS:[BX+1850] 8 near IPs BX<=7 then SHL 1"),
        (0x467BF, 0x468BC, "code", "code", "notes/transfer_scan.md", "C4C8:1B3F through RETF; CALLN from slot 0086; 1C57 and 1D83 already owned"),
        (0x46A43, 0x46C2B, "code", "code", "notes/transfer_scan.md", "C4C8:1DC3 through RETF; CALLN from slot 008F; 1D83, 1C57, and 1C3C already owned"),
        (0x4A9B4, 0x4AC4E, "code", "code", "notes/transfer_scan.md", "CA9B:0004 through RETF; CALLF from C425:01CE; CA9B:029E not entered"),
        (0x47944, 0x47A6B, "code", "code", "notes/transfer_scan.md", "C6C2:0D24 through RETF; CALLN from C6C2:14B5; C6C2:1169, leftover prefix, and C887:09AC not entered"),
        (0x47D89, 0x47E0F, "code", "code", "notes/transfer_scan.md", "C6C2:1169 through RETF; CALLN from C6C2:1546; leftover prefix and C887:09AC not entered"),
        (0x47E0F, 0x47EF2, "code", "code", "notes/transfer_scan.md", "C6C2:11EF through RETF; CALLN from C6C2:12EE; leftover prefix and leftover 1345 not entered"),
        (0x47EF2, 0x47F44, "code", "code", "notes/transfer_scan.md", "C6C2:12D2 through RETF; CALLN from C6C2:1340; C6C2:11EF not entered"),
        (0x47F44, 0x47F65, "code", "code", "notes/transfer_scan.md", "C6C2:1324 through RETF; CALLN from C6C2:13C9; C6C2:12D2 not entered"),
        (0x47F82, 0x48209, "code", "code", "notes/transfer_scan.md", "C6C2:1362 through RETF; CALLF from DE5C:01D6; C6C2:182D and C6C2:1324 not entered"),
        (0x4844D, 0x484B5, "code", "code", "notes/transfer_scan.md", "C6C2:182D through RETF; CALLN from C6C2:13C2; C6C2:1895 and D90C:0006 not entered"),
        (0x484B5, 0x484C9, "code", "code", "notes/transfer_scan.md", "C6C2:1895 through RETF; CALLN from C6C2:185F; D90C:0006 and C887:09AC not entered"),
        (0x5926D, 0x5928D, "code", "code", "notes/transfer_scan.md", "D90C:01AD through RETF; CALLF from C6C2:1458; D90C:0454, D90C:0006, and C887:09AC not entered"),
        (0x593F8, 0x59501, "code", "code", "notes/transfer_scan.md", "D90C:0338 through RETF; CALLF from C6C2:1873; D90C:0454, D90C:0006, and D90C:0574 not entered"),
        (0x59634, 0x5964F, "code", "code", "notes/transfer_scan.md", "D90C:0574 through RET; CALLN from D90C:0360; D90C:0454, D90C:0006, and C887:09AC not entered"),
        (0x452F8, 0x45361, "code", "code", "notes/transfer_scan.md", "C4C8:0678 through RETF; CALLN from 0FDF; 07A2 and 06E1 not entered"),
        (0x45361, 0x45422, "code", "code", "notes/transfer_scan.md", "C4C8:06E1 through RETF; CALLN from 0678 and 0FDF; B13A:0000 not entered"),
        (0x45422, 0x454C9, "code", "code", "notes/transfer_scan.md", "C4C8:07A2 through JMP CS:[BX+0913]; CALLN from 0678"),
        (0x454C9, 0x454CF, "code", "code", "notes/transfer_scan.md", "C4C8:0849 MOV SI,0x0010 / JMP 08D4; 0913 slot BX==0; meets owned 08D4"),
        (0x454CF, 0x454DF, "code", "code", "notes/transfer_scan.md", "C4C8:084F OR DI,DI / JZ 0858 / MOV AX,0x0011 / JMPS 085B / MOV AX,0x0002 / MOV SI,AX / JMPS 08D4; 0913 slot BX==1; meets owned 08D4"),
        (0x454DF, 0x454EF, "code", "code", "notes/transfer_scan.md", "C4C8:085F OR DI,DI / JZ 0868 / MOV AX,0x0011 / JMPS 086B / MOV AX,0x0003 / MOV SI,AX / JMPS 08D4; 0913 slot BX==2; meets owned 08D4"),
        (0x454EF, 0x454FF, "code", "code", "notes/transfer_scan.md", "C4C8:086F OR DI,DI / JZ 0878 / MOV AX,0x0012 / JMPS 087B / MOV AX,0x0004 / MOV SI,AX / JMPS 08D4; 0913 slot BX==3; meets owned 08D4"),
        (0x454FF, 0x4550F, "code", "code", "notes/transfer_scan.md", "C4C8:087F OR DI,DI / JZ 0888 / MOV AX,0x0012 / JMPS 088B / MOV AX,0x0005 / MOV SI,AX / JMPS 08D4; 0913 slot BX==4; meets owned 08D4"),
        (0x4550F, 0x4551F, "code", "code", "notes/transfer_scan.md", "C4C8:088F OR DI,DI / JZ 0898 / MOV AX,0x0013 / JMPS 089B / MOV AX,0x0006 / MOV SI,AX / JMPS 08D4; 0913 slot BX==5; meets owned 08D4"),
        (0x4551F, 0x4552F, "code", "code", "notes/transfer_scan.md", "C4C8:089F OR DI,DI / JZ 08A8 / MOV AX,0x0013 / JMPS 08AB / MOV AX,0x0007 / MOV SI,AX / JMPS 08D4; 0913 slot BX==6; meets owned 08D4"),
        (0x4552F, 0x4553F, "code", "code", "notes/transfer_scan.md", "C4C8:08AF OR DI,DI / JZ 08B8 / MOV AX,0x0014 / JMPS 08BB / MOV AX,0x0008 / MOV SI,AX / JMPS 08D4; 0913 slot BX==7; meets owned 08D4"),
        (0x4553F, 0x4554F, "code", "code", "notes/transfer_scan.md", "C4C8:08BF OR DI,DI / JZ 08C8 / MOV AX,0x0014 / JMPS 08CB / MOV AX,0x0009 / MOV SI,AX / JMPS 08D4; 0913 slot BX==8; meets owned 08D4"),
        (0x4554F, 0x45554, "code", "code", "notes/transfer_scan.md", "C4C8:08CF MOV SI,0x000F / JMPS 08D4; 0913 slot BX==9; meets owned 08D4"),
        (0x45554, 0x45593, "code", "code", "notes/transfer_scan.md", "C4C8:07A2 continuation from 08D4 through RETF; B13A:0000 not entered"),
        (0x45593, 0x455A7, "data", "jump_table", "notes/transfer_scan.md", "C4C8 JMP CS:[BX+0913] 10 near IPs BX<=9 then SHL 1"),
        (0x45ADA, 0x45B49, "code", "code", "notes/transfer_scan.md", "C4C8:0E5A through RETF; CALLN from 0FDF; 0E2B not entered"),
        (0x45AAB, 0x45ADA, "code", "code", "notes/transfer_scan.md", "C4C8:0E2B through both RETFs; CALLN from 0E5A; 0CF1 and 0D8B not entered"),
        (0x45971, 0x45A0B, "code", "code", "notes/transfer_scan.md", "C4C8:0CF1 through both RETFs; CALLN from 0E2B; calls owned 06E1 and 07A2"),
        (0x45A0B, 0x45AAB, "code", "code", "notes/transfer_scan.md", "C4C8:0D8B through both RETFs; CALLN from 0E2B when byte is 0x2B; calls owned 06E1 and 07A2"),
        (0x59AAD, 0x59AE7, "code", "code", "notes/transfer_scan.md", "D9A2:008D through RETF; CALLF from C4C8:0CF1 and C4C8:0D8B"),
        (0x34ADB, 0x34D23, "code", "code", "notes/transfer_scan.md", "B3FD:0B0B through RETF; CALLN from B3FD:03EC; 0D53 not entered"),
        (0x34D23, 0x34EB9, "code", "code", "notes/transfer_scan.md", "B3FD:0D53 through RETF; CALLN from 0B0B; 0ACC and 0EE9 not entered"),
        (0x34EB9, 0x34F49, "code", "code", "notes/transfer_scan.md", "B3FD:0EE9 through RETF; CALLN from 0D53; B77C:20EA and 0F79 not entered"),
        (0x34F49, 0x35098, "code", "code", "notes/transfer_scan.md", "B3FD:0F79 through RETF; CALLN from B3FD:03FB; 0ACC and B77C not entered"),
        (0x34A9C, 0x34ADB, "code", "code", "notes/transfer_scan.md", "B3FD:0ACC through RETF; CALLN from 0D53 and 0F79; meets owned 0B0B"),
        (0x398AA, 0x398BB, "code", "code", "notes/transfer_scan.md", "B77C:20EA through RETF; CALLF from B3FD:0D53, 0EE9, and 0F79; 20C5 already owned"),
        (0x6605E, 0x66095, "code", "code", "notes/transfer_scan.md", "E605:000E through RETF; CALLF from B3FD:0F79; E1A6:0007 already owned"),
        (0x396E6, 0x39725, "code", "code", "notes/transfer_scan.md", "B77C:1F26 through RETF; CALLF from B3FD:0F79; E4D6:000D already owned"),
        (0x66174, 0x66447, "code", "code", "notes/transfer_scan.md", "E617:0004 through six RETFs; CALLF from B3FD:0F79; 035A, 02D7, and 03AE not entered"),
        (0x66447, 0x664C6, "code", "code", "notes/transfer_scan.md", "E617:02D7 through RETF and loop; CALLN from 0004; 035A not entered"),
        (0x664CA, 0x6651E, "code", "code", "notes/transfer_scan.md", "E617:035A through three RETFs; CALLN from 0004; 03AE not entered"),
        (0x6651E, 0x66554, "code", "code", "notes/transfer_scan.md", "E617:03AE through RETF; CALLN from 0004; E655:0004 not entered"),
        (0x66554, 0x66616, "code", "code", "notes/transfer_scan.md", "E655:0004 through both RETFs; CALLF from E617:0004; meets owned E661:0006"),
        (0x66920, 0x66A9D, "code", "code", "notes/transfer_scan.md", "E692:0000 through three RETFs; CALLF from E617:0004; E7D5:0001 not entered"),
        (0x67D51, 0x67DB9, "code", "code", "notes/transfer_scan.md", "E7D5:0001 through three RETFs; CALLF from E692:0000; E1A6:0007 already owned"),
        (0x397ED, 0x3981B, "code", "code", "notes/transfer_scan.md", "B77C:202D through RETF; CALLF from BE1A:003F; 1FDB and 1F65 not entered"),
        (0x39725, 0x3979B, "code", "code", "notes/transfer_scan.md", "B77C:1F65 through RETF; CALLN from B77C:202D; D0C0:10B6 and 1FDB not entered"),
        (0x3981B, 0x39885, "code", "code", "notes/transfer_scan.md", "B77C:205B through RETF; CALLF from CEBF:008D; E72C:00A1 not entered; meets owned 20C5"),
        (0x67361, 0x67399, "code", "code", "notes/transfer_scan.md", "E72C:00A1 through RETF; CALLF from B77C:205B; E72C:0006 not entered"),
        (0x672C6, 0x67361, "code", "code", "notes/transfer_scan.md", "E72C:0006 through six RETFs; CALLN from E72C:00A1; E1A6:0007 already owned; meets owned 00A1"),
        (0x51CB6, 0x51CEF, "code", "code", "notes/transfer_scan.md", "D0C0:10B6 through RETF; CALLF from B77C:1F83; D0C0:101D not entered; meets owned code at 0x51CEF"),
        (0x51C1D, 0x51CB6, "code", "code", "notes/transfer_scan.md", "D0C0:101D through RETF; CALLN from D0C0:10E7; meets owned 10B6"),
    (0x4EBF8, 0x4ED2E, "code", "code", "notes/transfer_scan.md", "CEBF:0008 through JMP CS:[BX+026A]; CALLF C425:01D8"),
    (0x4ED2E, 0x4EDA2, "code", "code", "notes/transfer_scan.md", "CEBF 026A dests 013E/0175/0189"),
    (0x4EDA2, 0x4EE5A, "code", "code", "notes/transfer_scan.md", "CEBF shared 01B2 through RETF"),
    (0x4EE5A, 0x4EE62, "data", "jump_table", "notes/transfer_scan.md", "CEBF JMP CS:[BX+026A] 4 near IPs BX<=3 then SHL 1"),
    (0x50785, 0x5078D, "data", "jump_table", "notes/transfer_scan.md", "CFC6 JMP CS:[BX+0B25] 4 near IPs"),
    (0x53A7C, 0x53A84, "data", "table", "notes/transfer_scan.md", "D3A7 OR AL,CS:[BX+000C] 8 bit masks BX<=7"),
    (0x53AAA, 0x53AC8, "code", "code", "notes/transfer_scan.md", "D3A7:003A OUT 0xA4 pulse / CALL FB00:0484 RET"),
    (0x53AC8, 0x53B20, "code", "code", "notes/transfer_scan.md", "D3A7:0058 0xC0xx I/O through RET; CALLN from 00B0"),
    (0x53B20, 0x53B78, "code", "code", "notes/transfer_scan.md", "D3A7:00B0 port poll / CALL 0058 / RET; 6 CALLN sites"),
    (0x53CAC, 0x53CBC, "data", "jump_table", "notes/transfer_scan.md", "D3A7 JMP CS:[BX+023C] 8 near IPs"),
    (0x5518D, 0x55206, "code", "code", "notes/pgr_live_after_amx.md", "D510:008D port picker through RETF"),
    (0x55206, 0x55218, "data", "table", "notes/pgr_live_after_amx.md", "D510 JMP CS:[BX+0106] 9 port words"),
    (0x553FF, 0x55417, "data", "jump_table", "notes/transfer_scan.md", "D52A CALL CS:[BX+015F] 12 near IPs"),
    (0x55420, 0x55430, "data", "jump_table", "notes/transfer_scan.md", "D52A CALL CS:[BX+0180] 8 near IPs"),
    (0x55732, 0x55742, "code", "code", "notes/transfer_scan.md", "D52A:0492 through JMP 06A0; reached MOV BX,0492 at 0312 stores [7626]"),
    (0x557BF, 0x557ED, "code", "code", "notes/transfer_scan.md", "D52A:051F through JMP 064C; reached [SI+762E] word 051F"),
    (0x55807, 0x5580A, "code", "code", "notes/transfer_scan.md", "D52A:0567 JMP 064C; JCC target from D52A:051F"),
    (0x558EC, 0x55901, "code", "code", "notes/transfer_scan.md", "D52A:064C through JMP 06A0; join from D52A:051F"),
    (0x5598F, 0x55996, "code", "code", "notes/transfer_scan.md", "D547:051F through JMP 0907; reached [SI+762E] word 051F"),
    (0x559AA, 0x559BA, "data", "jump_table", "notes/transfer_scan.md", "D547 JMP CS:[BX+053A] 8 near IPs BX=(nibble<<1)&0xE"),
    (0x559BA, 0x559C5, "code", "code", "notes/transfer_scan.md", "D547:054A slot-7 dest through fall into 0555"),
    (0x559D1, 0x559F1, "data", "jump_table", "notes/transfer_scan.md", "D547 JMP CS:[DI+0561] 16 near IPs"),
    (0x55A9D, 0x55ACD, "code", "code", "notes/transfer_scan.md", "D547:062D through JMP 0907; reached JMP 062D from 07E1"),
    (0x55ACD, 0x55AD3, "code", "code", "notes/transfer_scan.md", "D547:065D through JMP 0907; JNS target from D547:063E"),
    (0x55D3F, 0x55D48, "code", "code", "notes/transfer_scan.md", "D547:08CF through JMPS 0907; BX slot 6 stores [SI+762E] word 08CF"),
    (0x55D49, 0x55D70, "code", "code", "notes/transfer_scan.md", "D547:08D9 through JMPS 0907; 08CF stores [SI+762E] word 08D9"),
    (0x55AD3, 0x55ADD, "code", "code", "notes/transfer_scan.md", "D547:0663 through JMP 0907; slot 2 stores [SI+762E] word 0663"),
    (0x55ADD, 0x55B03, "code", "code", "notes/transfer_scan.md", "D547:066D through JMP short 06A7; reached [SI+762E] word 066D"),
    (0x55B04, 0x55B17, "code", "code", "notes/transfer_scan.md", "D547:0694 through fall into 06A7; slot 3 stores [SI+762E] word 0694"),
    (0x55B17, 0x55B43, "code", "code", "notes/transfer_scan.md", "D547:06A7 through JMP 0907; stores [SI+762E] word 051F"),
    (0x55B43, 0x55B4D, "code", "code", "notes/transfer_scan.md", "D547:06D3 through JMP 0900; slot 4 stores [SI+762E] word 06D3"),
    (0x55B4D, 0x55B5C, "code", "code", "notes/transfer_scan.md", "D547:06DD through JMP 0907; slot 1 stores [SI+762E] word 06DD"),
    (0x55B5C, 0x55B78, "code", "code", "notes/transfer_scan.md", "D547:06EC through JMP short 0716; 06DD stores [SI+762E] word 06EC"),
    (0x55B79, 0x55B8C, "code", "code", "notes/transfer_scan.md", "D547:0709 through JMP 0900; join stores [SI+762E] word 06DD"),
    (0x55B8C, 0x55B96, "code", "code", "notes/transfer_scan.md", "D547:071C through JMP 0907; slot 0 stores [SI+762E] word 071C"),
    (0x55B96, 0x55BA3, "code", "code", "notes/transfer_scan.md", "D547:0726 through JMP 0900; 071C stores [SI+762E] word 0726"),
    (0x55BA3, 0x55BAD, "code", "code", "notes/transfer_scan.md", "D547:0733 through JMP 0907; slot 3 stores [SI+762E] word 0733"),
    (0x55BAD, 0x55BF0, "code", "code", "notes/transfer_scan.md", "D547:073D through JMP 0900; 0733 stores [SI+762E] word 073D"),
    (0x55BF0, 0x55C1F, "code", "code", "notes/transfer_scan.md", "D547:0780 through JMP 0907; 073D JNZ after CMP [98DB],0"),
    (0x55C1F, 0x55C4E, "code", "code", "notes/transfer_scan.md", "D547:07AF through JMP 0900; BX slot 5 stores [SI+762E] word 07AF"),
    (0x55C4E, 0x55C51, "code", "code", "notes/transfer_scan.md", "D547:07DE JMP 0907; JZ/JL targets from D547:07AF body"),
    (0x55C51, 0x55C9B, "code", "code", "notes/transfer_scan.md", "D547:07E1 through JMP 062D; DI slot 0 stores [SI+762E] word 07E1"),
    (0x55C9B, 0x55D3E, "code", "code", "notes/transfer_scan.md", "D547:082B through JMPS 0907; DI slot 1 stub 0587 stores [SI+762E] word 082B"),
    (0x55DA3, 0x55DB9, "code", "code", "notes/transfer_scan.md", "D547:0933 through JMP short 0956; CALLN from D547:0860 and D547:08BD"),
    (0x55DBA, 0x55DC7, "code", "code", "notes/transfer_scan.md", "D547:094A through RET; JNZ 093E and JZ 094D join"),
    (0x55EF4, 0x55F04, "data", "table", "notes/transfer_scan.md", "D5DD MOV BX,CS:[SI+0124]/[SI+012C] two 4-word arrays; CALLN D5DD:0032"),
    (0x55F64, 0x55F7A, "data", "jump_table", "notes/transfer_scan.md", "D5F3 JMP CS:[BX+0034] 11 near IPs"),
    (0x5660C, 0x56618, "data", "jump_table", "notes/transfer_scan.md", "D61A JMP CS:[BX+046C] 6 near IPs"),
    (0x56E8B, 0x56EB5, "code", "code", "notes/transfer_scan.md", "D6E0:008B ES=DS / AMX 0725/06B9 through RETF; CALLF C303:029C"),
    (0x58BCA, 0x58BDC, "data", "jump_table", "notes/transfer_scan.md", "D8BC JMP CS:[BX+000A] 9 near IPs"),
    (0x59B95, 0x59BA1, "code", "code", "notes/calling_convention.md", "D9B5:0045 LDS [BP+6]"),
    (0x59BD9, 0x59C05, "code", "code", "notes/amx_first_dispatch.md", "D9BD:0009 task 6 loop"),
    (0x59C95, 0x59C9D, "data", "jump_table", "notes/transfer_scan.md", "D9C0 JMP CS:[BX+0095] 4 near IPs"),
    (0x59F92, 0x59FCD, "code", "code", "notes/transfer_scan.md", "D9F2:0072 cdecl through RETF; CALLF from C44E:020D"),
    (0x5B24D, 0x5B25F, "data", "jump_table", "notes/transfer_scan.md", "DAF2 JMP CS:[BX+032D] 9 near IPs"),
    (0x5B447, 0x5B461, "data", "jump_table", "notes/transfer_scan.md", "DB28 JMP CS:[BX+01C7] 13 near IPs"),
    (0x5B56B, 0x5B585, "data", "jump_table", "notes/transfer_scan.md", "DB28 JMP CS:[BX+02EB] 13 near IPs"),
    (0x5BC6B, 0x5BC87, "data", "jump_table", "notes/transfer_scan.md", "DB28 JMP CS:[BX+09EB] 14 near IPs"),
    (0x5BCAD, 0x5BCD4, "code", "code", "notes/transfer_scan.md", "DB28:0A2D ES:[BX] init through RETF; CALLN DB28:077B"),
    (0x5C5B2, 0x5C5CA, "data", "table", "notes/transfer_scan.md", "DC5B MOV BX,CS:[BX+0002] 12 words; CALLF DA9B:0002"),
    (0x5C6E2, 0x5C702, "data", "table", "notes/transfer_scan.md", "DC6E MOV DX,CS:[BX+0002] 16 mask words BX=(n&0xF)<<1; CALLF DC23:000A"),
    (0x5CA78, 0x5CA84, "data", "jump_table", "notes/transfer_scan.md", "DCA2 JMP CS:[BX+0058] 6 near IPs"),
    (0x5CB74, 0x5CB79, "code", "code", "notes/transfer_scan.md", "DCA2:0154 MOV AL,0x59 / JMP 0016; CALLF DE5C:055B"),
    (0x5CB86, 0x5CD91, "code", "code", "notes/transfer_scan.md", "DCA2:0166 through RETF; CALLN DCA2:0019"),
    (0x5CD91, 0x5CDE9, "code", "code", "notes/transfer_scan.md", "DCA2:0371 through RETF; CALLN DCA2:0361"),
    (0x5CDE9, 0x5CE02, "code", "code", "notes/transfer_scan.md", "DCA2:03C9 through RET; CALLN DCA2:0187"),
    (0x5D35E, 0x5D376, "data", "jump_table", "notes/transfer_scan.md", "DCF0 JMP CS:[BX+045E] 12 near IPs"),
    (0x5DBBC, 0x5DBC8, "data", "table", "notes/transfer_scan.md", "DD9A MOV CX,CS:[SI+021C] 6 words"),
    (0x5DBCF, 0x5DBEF, "data", "table", "notes/transfer_scan.md", "DD9A MOV BX,CS:[BX+022F] 16 mask words"),
    (0x5DBEF, 0x5DC0F, "data", "table", "notes/transfer_scan.md", "DD9A MOV BX,CS:[BX+024F] 16 mask words"),
    (0x5DF1A, 0x5DF42, "code", "code", "notes/amx_create_table.md", "create-table task 4 through RETF"),
    (0x5EE45, 0x5EE8D, "data", "jump_table", "notes/transfer_scan.md", "DE5C JMP CS:[BX+0885] 36 near IPs"),
    (0x5EE8D, 0x5EE9B, "data", "jump_table", "notes/transfer_scan.md", "DE5C JMP CS:[BX+08CD] 7 near IPs"),
    (0x63989, 0x63A99, "code", "code", "notes/transfer_scan.md", "E398:0009 through RETF; CALLF C2E6:01B9"),
    (0x63A99, 0x63B70, "code", "code", "notes/transfer_scan.md", "E398:0119 cdecl through RETF; CALLN E398:0091"),
    (0x63B70, 0x63CE6, "code", "code", "notes/transfer_scan.md", "E398:01F0 cdecl through RETF; CALLF C2E6:00EC"),
    (0x63CE6, 0x63D06, "code", "code", "notes/transfer_scan.md", "E398:0366 through RETF; CALLF C2E6:0126"),
    (0x63D06, 0x63D3D, "code", "code", "notes/transfer_scan.md", "E398:0386 through RETF; CALLN E398:0065"),
    (0x63D3D, 0x63DDA, "code", "code", "notes/transfer_scan.md", "E398:03BD cdecl through RETF; CALLN E398:00AB"),
    (0x63DDA, 0x63E78, "code", "code", "notes/transfer_scan.md", "E398:045A cdecl through RETF; CALLN E398:0351"),
    (0x63E78, 0x63EA5, "code", "code", "notes/transfer_scan.md", "E3E7:0008 cdecl through RETF; CALLF E4FA:0025"),
    (0x64FAC, 0x65110, "code", "code", "notes/transfer_scan.md", "E4FA:000C cdecl through RETF; CALLF C303:06D1"),
    (0x607A4, 0x608C1, "code", "code", "notes/transfer_scan.md", "E07A:0004 cdecl through RETF; CALLF from E398:0055"),
    (0x612D9, 0x613B0, "code", "code", "notes/transfer_scan.md", "E12D:0009 cdecl through RETF; CALLF from E398:0394"),
    (0x65110, 0x651D3, "code", "code", "notes/transfer_scan.md", "E4FA:0170 cdecl through RETF; CALLN E4FA:0167"),
    (0x65815, 0x65820, "code", "code", "notes/transfer_scan.md", "E56F:0125 CLI snapshot RETF; CALLF DE5C:0489"),
    (0x65820, 0x6595A, "code", "code", "notes/transfer_scan.md", "E582:0000 cdecl through RETF; CALLF B3FD:0615"),
    (0x659E6, 0x65A15, "code", "code", "notes/transfer_scan.md", "E59E:0006 copy 9208.. through RETF; CALLF from E398:0036"),
    (0x65A15, 0x65A79, "code", "code", "notes/transfer_scan.md", "E59E:0035 flag/AMX through RETF; CALLF E521/DF4F/E566"),
    (0x65A83, 0x65AB0, "code", "code", "notes/transfer_scan.md", "E5A8:0003 copy 9209.. through RETF; CALLF from E398:0031"),
    (0x65AB0, 0x65AF1, "code", "code", "notes/transfer_scan.md", "E5A8:0030 copy 9209.. through RETF; CALLF EB5B:0087"),
    (0x66148, 0x66174, "code", "code", "notes/transfer_scan.md", "E614:0008 flag thunk RETF; CALLF from E704:0081"),
    (0x66616, 0x666A5, "code", "code", "notes/transfer_scan.md", "E661:0006 cdecl through RETF; CALLF from B3FD"),
    (0x666A5, 0x666FC, "code", "code", "notes/transfer_scan.md", "E661:0095 cdecl through RETF; CALLF from B3FD:0480"),
    (0x6676D, 0x66883, "code", "code", "notes/transfer_scan.md", "E676:000D cdecl through RETF; CALLF B3FD:0042"),
    (0x66908, 0x66920, "code", "code", "notes/transfer_scan.md", "E688:0088 compare RETF; CALLF DE5C:04E6"),
    (0x66D11, 0x66D8B, "code", "code", "notes/transfer_scan.md", "E6D1:0001 cdecl through RETF; CALLF from E398:0206"),
    (0x670C1, 0x670CB, "code", "code", "notes/transfer_scan.md", "E704:0081 PUSH CS / CALL 0007 / CALLF E614:0008 RETF"),
    (0x6769C, 0x67725, "code", "code", "notes/transfer_scan.md", "E739:030C cdecl through RETF; CALLF from E7E0:0043"),
    (0x67E0A, 0x67F57, "code", "code", "notes/transfer_scan.md", "E7E0:000A cdecl through RETF; CALLF CEBF:021C"),
    (0x69374, 0x6937C, "code", "code", "notes/amx_create_table.md", "E937:0004 DS=ES=8010 RETF"),
    (0x6AD0B, 0x6AD6E, "code", "code", "notes/amx_create_table.md", "create-table task 3 through RETF"),
    (0x6B0B2, 0x6B0B6, "data", "table", "notes/transfer_scan.md", "EB0B MOV AX/DX,CS:[0002]/[0004] 32-bit dividend; CALLF DC08:0046"),
    (0x6B1A2, 0x6B4F2, "code", "code", "notes/transfer_scan.md", "EB1A:0002 cdecl through RETF; CALLF DE5C:0496"),
    (0x6B7E2, 0x6B7EC, "data", "jump_table", "notes/transfer_scan.md", "EB74 JMP CS:[BX+00A2] 5 near IPs"),
    (0x6BC83, 0x6BD59, "code", "code", "notes/transfer_scan.md", "EBC8:0003 cdecl through RETF; CALLF C44E:0031"),
    (0x6BE65, 0x6BE6F, "data", "jump_table", "notes/transfer_scan.md", "EBC8 JMP CS:[BX+01E5] 5 near IPs"),
    (0x6C050, 0x6C093, "code", "code", "notes/amx_create_table.md", "create-table task 2 through RETF"),
    (0x7079C, 0x707A4, "data", "padding", "notes/padding.md", "0xFF after RETF before F07A table"),
    (0x707A4, 0x707B6, "data", "init_table", "notes/boot_reset_to_bios_banner.md", "F07A three 6-byte init records"),
    (0x707B6, 0x707C8, "data", "table_tail", "notes/padding.md", "F07A tail FFFF + 16 zeros"),
    (0x707C8, 0x7800A, "data", "padding", "notes/padding.md", "unprogrammed ROM before BIOS F800:000A"),
    (0x7800A, 0x78144, "code", "code", "notes/boot_reset_to_bios_banner.md", "BIOS F800:000A through RETF"),
    (0x7831F, 0x78325, "data", "table", "notes/transfer_scan.md", "F800 MOV SI,031F MOV CX,3 MOV BX,CS:[SI] 3 words"),
    (0x796AA, 0x796D4, "code", "code", "notes/boot_reset_to_bios_banner.md", "INT 43 dispatcher"),
    (0x796D4, 0x796E4, "data", "table", "notes/boot_reset_to_bios_banner.md", "INT 43 eight near targets"),
    (0x796E4, 0x7971D, "code", "code", "notes/boot_reset_to_bios_banner.md", "INT 43 AX=0 LCD init"),
    (0x7971D, 0x79734, "code", "code", "notes/int43_ax4.md", "INT 43 AX=1 fill 0x140 spaces; CALLN F800:1843/17CC"),
    (0x79734, 0x79744, "code", "code", "notes/int43_ax4.md", "INT 43 AX=2 LCD_put AX=((BX&3)<<2)+0x30; CALLN F800:185A"),
    (0x79744, 0x79752, "code", "code", "notes/int43_ax4.md", "INT 43 AX=3 cursor row*40+col; CALLN F800:1843"),
    (0x79752, 0x7976E, "code", "code", "notes/int43_ax4.md", "INT 43 AX=4 class walk"),
    (0x7976E, 0x7977E, "data", "table", "notes/int43_ax4.md", "INT 43 AX=4 class table"),
    (0x7977E, 0x797CC, "code", "code", "notes/int43_ax4.md", "INT 43 AX=4 CR/LF/BS/DEL/FF"),
    (0x797CC, 0x79808, "code", "code", "notes/int43_ax4.md", "INT 43 AX=4 default glyph"),
    (0x79808, 0x7981B, "code", "code", "notes/int43_ax4.md", "INT 43 AX=5 copy shadow 662B to 676B"),
    (0x7981B, 0x79839, "code", "code", "notes/int43_ax4.md", "INT 43 AX=6 replay 676B via 17CC; CALLN F800:1843/17CC"),
    (0x79839, 0x79843, "code", "code", "notes/int43_ax4.md", "INT 43 AX=7 cursor /40 -> AH=row AL=col"),
    (0x79843, 0x79875, "code", "code", "notes/boot_reset_to_bios_banner.md", "cursor 1843 + LCD put"),
    (0x79875, 0x79896, "code", "code", "notes/boot_reset_to_bios_banner.md", "inline-string walker 1875"),
    (0x79896, 0x798CA, "code", "code", "notes/hex_helper.md", "F800:1896/189C AL as 2 hex digits via 18CA"),
    (0x798CA, 0x798D6, "code", "code", "notes/boot_reset_to_bios_banner.md", "18CA INT 43 AX=4"),
    (0x79906, 0x79946, "data", "table", "notes/transfer_scan.md", "F800:1906 16x4-byte records; LEA SI,[BX+1906] OUTSW"),
    (0x79946, 0x79B26, "code", "code", "notes/ivt_inventory.md", "1946 IRET + ladder + F800:1AD4 RETF"),
    (0x79B26, 0x79B36, "data", "jump_table", "notes/ivt_inventory.md", "INT 40 CALL CS:[SI] 8 near IPs at F800:1B26"),
    (0x7A094, 0x7A09A, "data", "table", "notes/transfer_scan.md", "F800 MOV AX,CS:[BX+2094] 3 words BL<3"),
    (0x7A0F7, 0x7A0FA, "code", "code", "notes/transfer_scan.md", "F800:20F7 POP CX/PUSH CS/PUSH CX; CALLN F800:2687/26A8"),
    (0x7A42D, 0x7A45B, "code", "code", "notes/transfer_scan.md", "F800:242D copy through RET 8; 6 CALLN from 24A5.."),
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
    (0x7B814, 0x7B818, "data", "table", "notes/amx_first_dispatch.md", "FB76:00B4 list header count=1 word=0008"),
    (0x7B818, 0x7B81A, "code", "code", "notes/amx_first_dispatch.md", "FB81:0008 JMP 003A"),
    (0x7B81A, 0x7B842, "data", "jump_over", "notes/amx_first_dispatch.md", "FB81:000A jump-over 10 + 38x58 + 90; not walked"),
    (0x7B842, 0x7B84A, "data", "table", "notes/amx_first_dispatch.md", "FB81 CS:[0032]=FB76:00B4 CS:[0036]=A850:0004"),
    (0x7B84A, 0x7B871, "code", "code", "notes/amx_first_dispatch.md", "FB81:003A list copy through RETF; CALLN 0061"),
    (0x7B871, 0x7B899, "code", "code", "notes/amx_first_dispatch.md", "FB81:0061 PUSH ES / CALLF FB00:065B AL=2 through RET"),
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


def switch_table_dests(image: bytes) -> set[str]:
    dests: set[str] = set()
    for start, end, cs in SWITCH_TABLES:
        for off in range(start, end, 2):
            ip = image[off] | (image[off + 1] << 8)
            dests.add(f"{cs:04X}:{ip:04X}")
    return dests


def callee_walks(image: bytes) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """BFS CALL dests from D15 and bounded switch-table IPs.

    Bounded dests are promoted. Indirect dests are not promoted;
    only their decoded instruction bytes are returned as prefixes.
    ``D61A:000A`` is a planted IVT slot, not a switch dest; it stays
    prefix-only in ``switch_and_planted_ranges``.
    """
    established = set(scan_entries(image)["_unique"])
    accepted = set(established)
    frontier = list(established)
    bounded_raw: list[tuple[int, int]] = []
    prefix_raw: list[tuple[int, int]] = []
    seen_unbounded: set[str] = set()
    for dest in sorted(switch_table_dests(image)):
        if dest in accepted:
            continue
        cs, ip = _parse_cs_ip(dest)
        insns, extra, hit = follow_entry(image, cs, ip, accepted)
        exits = classify_exits(insns, accepted) + extra
        if _is_bounded(exits, hit):
            accepted.add(dest)
            frontier.append(dest)
            continue
        seen_unbounded.add(dest)
        for insn in insns:
            prefix_raw.append((insn.file, insn.file + insn.length))
    while frontier:
        dests: set[str] = set()
        for cs_ip in frontier:
            cs, ip = _parse_cs_ip(cs_ip)
            insns, _extra, _hit = follow_entry(image, cs, ip, accepted)
            for item in classify_exits(insns, accepted):
                if item["kind"] in ("callf", "calln") and item["dest"] not in accepted:
                    dests.add(item["dest"])
        nxt: list[str] = []
        for dest in dests:
            cs, ip = _parse_cs_ip(dest)
            insns, extra, hit = follow_entry(image, cs, ip, accepted)
            exits = classify_exits(insns, accepted) + extra
            if _is_bounded(exits, hit):
                accepted.add(dest)
                nxt.append(dest)
                for insn in insns:
                    bounded_raw.append((insn.file, insn.file + insn.length))
                continue
            if dest not in seen_unbounded:
                seen_unbounded.add(dest)
                for insn in insns:
                    prefix_raw.append((insn.file, insn.file + insn.length))
        frontier = nxt
    return _merge_runs(bounded_raw), _merge_runs(prefix_raw)


def callee_insn_ranges(image: bytes) -> list[tuple[int, int]]:
    bounded, _prefixes = callee_walks(image)
    return bounded


def indirect_prefix_ranges(image: bytes) -> list[tuple[int, int]]:
    _bounded, prefixes = callee_walks(image)
    return prefixes


# (start, end, cs) - owned near-IP tables. Dest walks use that CS.
SWITCH_TABLES: tuple[tuple[int, int, int], ...] = (
    (0x30D01, 0x30D15, 0xB060),
    (0x31258, 0x3126C, 0xB060),
    (0x31FE2, 0x31FFC, 0xB1BC),
    (0x44483, 0x444B9, 0xC425),
    (0x50785, 0x5078D, 0xCFC6),
    (0x53CAC, 0x53CBC, 0xD3A7),
    (0x553FF, 0x55417, 0xD52A),
    (0x55420, 0x55430, 0xD52A),
    (0x559AA, 0x559BA, 0xD547),
    (0x559D1, 0x559F1, 0xD547),
    (0x55F64, 0x55F7A, 0xD5F3),
    (0x5660C, 0x56618, 0xD61A),
    (0x58BCA, 0x58BDC, 0xD8BC),
    (0x59C95, 0x59C9D, 0xD9C0),
    (0x5B24D, 0x5B25F, 0xDAF2),
    (0x5B447, 0x5B461, 0xDB28),
    (0x5B56B, 0x5B585, 0xDB28),
    (0x5BC6B, 0x5BC87, 0xDB28),
    (0x5CA78, 0x5CA84, 0xDCA2),
    (0x5D35E, 0x5D376, 0xDCF0),
    (0x5EE45, 0x5EE8D, 0xDE5C),
    (0x5EE8D, 0x5EE9B, 0xDE5C),
    (0x6B7E2, 0x6B7EC, 0xEB74),
    (0x6BE65, 0x6BE6F, 0xEBC8),
    (0x79B26, 0x79B36, 0xF800),
)

PLANTED_IVT: tuple[str, ...] = ("D61A:000A", "FB93:0059")


def switch_and_planted_ranges(image: bytes) -> list[tuple[int, int]]:
    """Instruction bytes of switch-table IPs and proven 0347 plants.

    Table dests have a named JMP/CALL [rm] consumer. D61A:000A is
    IVT[9] after B03B:01F7 MOV ES,D61A / MOV BX,000A / MOV DL,9.
    FB93:0059 is IVT[8] after FB00:09B8 MOV ES,FB93 / MOV BX,0059
    / MOV DL,8. Indirect dests contribute prefixes only.
    """
    established = set(scan_entries(image)["_unique"])
    dests: set[str] = set(PLANTED_IVT)
    for start, end, cs in SWITCH_TABLES:
        for off in range(start, end, 2):
            ip = image[off] | (image[off + 1] << 8)
            dests.add(f"{cs:04X}:{ip:04X}")
    raw: list[tuple[int, int]] = []
    for dest in dests:
        cs, ip = _parse_cs_ip(dest)
        insns, extra, hit = follow_entry(image, cs, ip, established)
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
    bounded, prefixes = callee_walks(image)
    for start, end in _subtract_owned(bounded, owned_spans):
        seed.append(
            (
                start,
                end,
                "code",
                "code",
                "notes/transfer_scan.md",
                "bounded CALL dest reachable from a D16 entry or switch-table dest",
            )
        )
    owned_spans = [(start, end) for start, end, *_ in seed]
    for start, end in _subtract_owned(prefixes, owned_spans):
        seed.append(
            (
                start,
                end,
                "code",
                "code",
                "notes/transfer_scan.md",
                "instruction prefix of an indirect CALL dest",
            )
        )
    owned_spans = [(start, end) for start, end, *_ in seed]
    for start, end in _subtract_owned(switch_and_planted_ranges(image), owned_spans):
        seed.append(
            (
                start,
                end,
                "code",
                "code",
                "notes/transfer_scan.md",
                "switch-table or 0347-plant dest instruction bytes",
            )
        )
    tmp_spans = [(start, end, "code", "code") for start, end, *_ in seed]
    for start, end in gaps(tmp_spans):
        # D547:0693 (file 0x55B03), D547:0708 (file 0x55B78),
        # and D547:0949 (file 0x55DB9) are unentered NOP bytes.
        # No owned transfer targets them.
        # D90C:058F (file 0x5964F) is the 0xFF after D90C:0574 RET.
        # No owned transfer targets it; first run ended at RET.
        if end - start == 1 and image[start] == 0x90 and start not in (0x55B03, 0x55B78, 0x55D48, 0x55DB9):
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
        elif end - start == 1 and image[start] == 0xFF and start not in (0x5964F,):
            seed.append(
                (
                    start,
                    end,
                    "data",
                    "padding",
                    "notes/padding.md",
                    "0xFF align between owned ranges",
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
