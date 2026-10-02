"""CHOP ZONE honours the stock Edit Sound safety settings.

Every stock Do handler refuses through B99A:1595 while the transport byte
[A7AE] and the "safe lock" setting [862F] are both non-zero, and the stock
copy wrapper mutes through D980:000C (OUT 6Ah) while "Mute audio during EDIT
SND processes" [8629] is on.  The sequencer is started with real Rec+Play,
the safe lock is cleared through Other > Extra, and the observer only reads
RAM and taps port 6Ah writes; no firmware state is injected.  The captured
profile shifts the three DGROUP bytes by -2.

Payloads come from emu.harness (built from the current sources; capture
profile for every case, the locked/running case also on generic).  The run
uses the early timeline: the legacy times of this suite minus 39 s.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from emu import harness as h
from emu.harness import taps
from emu.snd import sine441, snd
from emu.test_wave_chop import do_action

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-safety"
DO_TIME = 58          # do_action(49) presses Do (soft4) at 49 + 9
BEFORE, AFTER, REENTRY = 48, 63, 69
ZONES = 16            # default map from a fresh wave-view entry

SAFETY_LUA = """
-- STATE and LOCK are prepended by the suite.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local prog, iosp = cpu.spaces["program"], cpu.spaces["io"]
local out = os.getenv("PROBE_OUT") or "."
local log = assert(io.open(out .. "/safety.jsonl", "w"))
local function phys(seg, off)
    local a = ((seg << 4) + off) & 0xfffff
    if cpu.state["XA"].value ~= 0 then
        return ((iosp:read_u16(0xff00 + (a >> 14) * 2) & 0x3ff) << 14) | (a & 0x3fff)
    end
    return a
end
-- Read-only tap: record each OUT 6Ah value (D980:000C mute 00h / unmute 0Eh).
CHOP_SAFETY_TAP = iosp:install_write_tap(0x6a, 0x6b, "chop_safety", function(offset, data, mask)
    if mask & 0xff ~= 0 then
        log:write(string.format('{"time":%.4f,"port6a":%d}\\n', machine.time:as_double(), data & 0xff))
        log:flush()
    end
end)
local last = -1
emu.register_periodic(function()
    local s = prog:read_u8(phys(0x8010, STATE))
    local l = prog:read_u8(phys(0x8010, LOCK))
    if s * 256 + l ~= last then
        log:write(string.format('{"time":%.4f,"state":%d,"lock":%d}\\n', machine.time:as_double(), s, l))
        log:flush()
        last = s * 256 + l
    end
end)
"""


def safety_prelude(profile: h.Profile) -> str:
    # [A7AE] transport, [862F] safe lock (generic); the capture is -2.
    return (f"local STATE, LOCK = {profile.dgroup(0xA7AE)}, {profile.dgroup(0x862F)}\n"
            + SAFETY_LUA)


class ChopSafety(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"locked_running"})

    @classmethod
    def cases(cls, profile, runs):
        # Other > Extra (soft4), five Downs to the safe-lock field, '-' sets OFF.
        unlock = taps((32, "other"), (33.5, "soft4"), *[(34.5 + i * .5, "down") for i in range(5)],
                      (37.5, "-"), (38.5, "main_screen"))
        # Fresh Edit Sound + wave view (default 16-zone map), CHOP ZONE, then
        # leave and re-enter Edit Sound to read the saved list selection.
        chop = (taps((42, "program_sounds"), (43.5, "6"), (45, "help")) + do_action(49)
                + taps((64, "main_screen"), (65.5, "program_sounds"), (67, "6")))
        # Rec + Play through the driver HLE (MAME inputs), as before.
        rec_play = [(40.0, "Y7", "Rec", 0.3), (40.1, "Y7", "Play", 0.1)]
        definitions = {
            "locked_running": (chop, rec_play),
            "unlocked_running": (unlock + chop, rec_play),
            "locked_stopped": (chop, []),
        }
        src = runs / "ZZSOURCE.SND"
        src.write_bytes(snd("ZZSOURCE", sine441()))
        return {name: h.Case(events=h.load_sound_events() + events, times=[BEFORE, AFTER, REENTRY],
                             files=[(src, "ZZSOURCE.SND")], parts=("wave_zones", "snddump"),
                             env={"SNDDUMP_PCM": "0"}, prelude=safety_prelude(profile),
                             kwargs={"press": press} if press else None)
                for name, (events, press) in definitions.items()}

    def case_dir(self, case: str, profile: str = "capture") -> Path:
        self.assertIn((profile, case), self.results, f"{profile}/{case} did not run")
        return RUNS / profile / case

    def log_rows(self, case: str, profile: str = "capture") -> list[dict]:
        return [json.loads(s) for s in
                (self.case_dir(case, profile) / "safety.jsonl").read_text().splitlines()]

    def records(self, case: str, time: int, profile: str = "capture") -> list[str]:
        return [r["name"] for r in h.sound_records(self.case_dir(case, profile), time).values()]

    def transport(self, case: str, profile: str = "capture") -> list[int]:
        """Every observed transport-byte value from just before Do until after it."""
        rows = [r for r in self.log_rows(case, profile) if "state" in r]
        current = [r for r in rows if r["time"] <= BEFORE][-1]["state"]
        return [current] + [r["state"] for r in rows if BEFORE < r["time"] <= AFTER]

    def port6a(self, case: str, profile: str = "capture") -> list[int]:
        return [r["port6a"] for r in self.log_rows(case, profile)
                if "port6a" in r and DO_TIME - 1 <= r["time"] <= AFTER]

    def assert_refused(self, case: str, profile: str = "capture"):
        self.assertNotIn(0, self.transport(case, profile), "sequencer must run across Do")
        self.assertEqual(self.records(case, BEFORE, profile), ["ZZSOURCE"])
        self.assertEqual(self.records(case, AFTER, profile), ["ZZSOURCE"])
        self.assertEqual(self.port6a(case, profile), [], "a refusal must not mute")
        self.assertEqual(h.zone_rows(self.case_dir(case, profile))[AFTER]["valid"], 1)

    def assert_chopped(self, case: str):
        self.assertEqual(self.records(case, BEFORE), ["ZZSOURCE"])
        self.assertEqual(sorted(self.records(case, AFTER)),
                         sorted(["ZZSOURCE"] + [f"ZONE{i:03d}" for i in range(ZONES)]))
        # Mute setting defaults ON: one mute before the work, one unmute after.
        self.assertEqual(self.port6a(case), [0x00, 0x0E])
        # The page's saved list selection follows the source: a fresh Edit
        # Sound entry selects ZZSOURCE, not the ZONE name now at its old slot.
        self.assertIn("Edit Snd:ZZSOURCE", self.results[("capture", case)][2]["rows"][0])

    def test_safe_lock_refuses_while_sequencer_runs(self):
        self.assert_refused("locked_running")
        self.assertEqual({r["lock"] for r in self.log_rows("locked_running") if "lock" in r
                          and r["time"] > 20}, {1})

    def test_generic_profile_safe_lock_refuses(self):
        if ("generic", "locked_running") not in self.results:
            h.unavailable("generic profile not selected (MPC3K_PROFILES)")
        self.assert_refused("locked_running", "generic")

    def test_safe_lock_off_allows_chop_while_running(self):
        self.assertNotIn(0, self.transport("unlocked_running"))
        self.assertEqual([r["lock"] for r in self.log_rows("unlocked_running") if "lock" in r][-1], 0)
        self.assert_chopped("unlocked_running")

    def test_stopped_sequencer_allows_chop_with_lock_on(self):
        self.assertEqual(set(self.transport("locked_stopped")), {0})
        self.assert_chopped("locked_stopped")


if __name__ == "__main__":
    unittest.main()
