"""CHOP ZONE honours the stock Edit Sound safety settings.

Every stock Do handler refuses through B99A:1595 while the transport byte
[A7AE] and the "safe lock" setting [862F] are both non-zero, and the stock
copy wrapper mutes through D980:000C (OUT 6Ah) while "Mute audio during EDIT
SND processes" [8629] is on.  The sequencer is started with real Rec+Play,
the safe lock is cleared through Other > Extra, and the observer only reads
RAM and taps port 6Ah writes; no firmware state is injected.  The captured
profile shifts the three DGROUP bytes by -2.

Payloads come from emu.harness (built from the current sources; capture
profile for every case, the locked/running case also on generic, and the
316 profile).  The run uses the early timeline: the legacy times of this
suite minus 39 s, shifted on 3.16 by its later wave view (profile.view -
harness.VIEW = 12 s).

OS 3.16 has neither setting nor an Edit Sound mute (notes/port_316.md): its
COPY handler goes from the zone check straight to the copy at 0B72:0B34
(image 0xC254), where Vailixi tests [A7AE] and [862F] at B99A:0B2F..0B3D
(linear 0x3A4CF), and none of the 32 `cmp byte [A49B],0` in the 3.16 image
lies in its Edit Sound segment 0B72 (Vailixi has ten in B99A).  What 3.16
does instead, asserted on its profile (MAME, default and v308): entering
Edit Sound stops the sequencer that Rec+Play started (transport 3.16 DS:A49B,
the A7AE pair of mods/profile_316.inc: 8 at Rec+Play on both OSes, then 0 at
the 6 key on 3.16), so CHOP runs and writes no port 6Ah.  `unlocked_running`
(the Other > Extra safe-lock toggle) does not exist on 3.16.
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
REC_PLAY, EDIT_SOUND = 40.0, 43.5   # Rec+Play; Program/Sounds -> 6 enters Edit Sound
ZONES = 16            # default map from a fresh wave-view entry

SAFETY_LUA = """
-- DGSEG, STATE and LOCK (nil: no safe-lock byte) are prepended by the suite.
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
    local s = prog:read_u8(phys(DGSEG, STATE))
    local l = LOCK and prog:read_u8(phys(DGSEG, LOCK)) or 0
    if s * 256 + l ~= last then
        if LOCK then
            log:write(string.format('{"time":%.4f,"state":%d,"lock":%d}\\n', machine.time:as_double(), s, l))
        else
            log:write(string.format('{"time":%.4f,"state":%d}\\n', machine.time:as_double(), s))
        end
        log:flush()
        last = s * 256 + l
    end
end)
"""


def safety_prelude(profile: h.Profile) -> str:
    # [A7AE] transport, [862F] safe lock (generic); the capture is -2; 3.16
    # has the transport (A49B) only.
    lock = "nil" if profile.is316 else profile.dgroup(0x862F)
    return (f"local DGSEG, STATE, LOCK = 0x{profile.dgroup_segment:04X}, {profile.dgroup(0xA7AE)}, {lock}\n"
            + SAFETY_LUA)


def shift(profile: h.Profile) -> float:
    """Seconds this profile's timeline is later than the legacy times (3.16: 12)."""
    return profile.view - h.VIEW


class ChopSafety(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"locked_running"})
    PROFILE_NAMES = h.ALL_PROFILES
    # 3.16 has no Other > Extra "EDIT SND <Do> SOFT KEY 4 safe lock" option to
    # clear (notes/port_316.md), so the case has no subject there.
    SKIP_316 = frozenset({"unlocked_running"})

    @classmethod
    def cases(cls, profile, runs):
        s = shift(profile)
        # Other > Extra (soft4), five Downs to the safe-lock field, '-' sets OFF.
        unlock = taps((32, "other"), (33.5, "soft4"), *[(34.5 + i * .5, "down") for i in range(5)],
                      (37.5, "-"), (38.5, "main_screen"))
        # Fresh Edit Sound + wave view (default 16-zone map), CHOP ZONE, then
        # leave and re-enter Edit Sound to read the saved list selection.
        chop = (taps((42 + s, "program_sounds"), (EDIT_SOUND + s, "6"), (45 + s, "help"))
                + do_action(49 + s, profile)
                + taps((64 + s, "main_screen"), (65.5 + s, "program_sounds"), (67 + s, "6")))
        # Rec + Play through the driver HLE (MAME inputs), as before.
        rec_play = [(REC_PLAY + s, "Y7", "Rec", 0.3), (REC_PLAY + s + 0.1, "Y7", "Play", 0.1)]
        definitions = {
            "locked_running": (chop, rec_play),
            "unlocked_running": (unlock + chop, rec_play),
            "locked_stopped": (chop, []),
        }
        src = runs / "ZZSOURCE.SND"
        src.write_bytes(snd("ZZSOURCE", sine441()))
        times = [BEFORE + s, AFTER + s, REENTRY + s]
        return {name: h.Case(events=h.load_sound_events(profile=profile) + events, times=times,
                             files=[(src, "ZZSOURCE.SND")], parts=("wave_zones", "snddump"),
                             env={"SNDDUMP_PCM": "0"}, prelude=safety_prelude(profile),
                             kwargs={"press": press} if press else None)
                for name, (events, press) in definitions.items()}

    def case_dir(self, case: str, profile: str = "capture") -> Path:
        self.assertIn((profile, case), self.results, f"{profile}/{case} did not run")
        return RUNS / profile / case

    def labels316(self, case: str) -> list[str]:
        labels = [p for p, c in self.results if c == case and self.profiles[p].is316]
        if not labels:
            h.unavailable(f"316 profile not selected for {case} (MPC3K_PROFILES)")
        return labels

    def shift(self, profile: str) -> float:
        self.assertIn(profile, self.profiles, f"{profile} did not run")
        return shift(self.profiles[profile])

    def log_rows(self, case: str, profile: str = "capture") -> list[dict]:
        return [json.loads(s) for s in
                (self.case_dir(case, profile) / "safety.jsonl").read_text().splitlines()]

    def records(self, case: str, time: float, profile: str = "capture") -> list[str]:
        return [r["name"] for r in h.sound_records(self.case_dir(case, profile), time).values()]

    def transport(self, case: str, profile: str = "capture") -> list[int]:
        """Every observed transport-byte value from just before Do until after it."""
        s = self.shift(profile)
        rows = [r for r in self.log_rows(case, profile) if "state" in r]
        current = [r for r in rows if r["time"] <= BEFORE + s][-1]["state"]
        return [current] + [r["state"] for r in rows if BEFORE + s < r["time"] <= AFTER + s]

    def port6a(self, case: str, profile: str = "capture") -> list[int]:
        s = self.shift(profile)
        return [r["port6a"] for r in self.log_rows(case, profile)
                if "port6a" in r and DO_TIME + s - 1 <= r["time"] <= AFTER + s]

    def assert_refused(self, case: str, profile: str = "capture"):
        self.assertNotIn(0, self.transport(case, profile), "sequencer must run across Do")
        self.assertEqual(self.records(case, BEFORE, profile), ["ZZSOURCE"])
        self.assertEqual(self.records(case, AFTER, profile), ["ZZSOURCE"])
        self.assertEqual(self.port6a(case, profile), [], "a refusal must not mute")
        self.assertEqual(h.zone_rows(self.case_dir(case, profile))[AFTER]["valid"], 1)

    def assert_chopped(self, case: str, profile: str = "capture", mute: list[int] = (0x00, 0x0E)):
        s = self.shift(profile)
        self.assertEqual(self.records(case, BEFORE + s, profile), ["ZZSOURCE"])
        self.assertEqual(sorted(self.records(case, AFTER + s, profile)),
                         sorted(["ZZSOURCE"] + [f"ZONE{i:03d}" for i in range(ZONES)]))
        # Vailixi: the mute setting defaults ON, so one mute before the work
        # and one unmute after.  3.16 has no Edit Sound mute: no write at all.
        self.assertEqual(self.port6a(case, profile), list(mute))
        # The page's saved list selection follows the source: a fresh Edit
        # Sound entry selects ZZSOURCE, not the ZONE name now at its old slot.
        self.assertIn("Edit Snd:ZZSOURCE", self.results[(profile, case)][2]["rows"][0])

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

    def test_316_edit_sound_entry_stops_sequencer_and_chop_proceeds(self):
        for prof in self.labels316("locked_running"):
            with self.subTest(profile=prof):
                s = self.shift(prof)
                rows = [r for r in self.log_rows("locked_running", prof)
                        if "state" in r and r["time"] >= REC_PLAY + s]
                # Rec+Play starts the count-in (transport 8, as on Vailixi,
                # which goes on to 10 and runs across Do).  3.16 drops it to 0
                # at the 6 key that enters Edit Sound and never restarts it,
                # so CHOP runs, without muting.
                self.assertEqual([r["state"] for r in rows], [8, 0], rows)
                self.assertTrue(EDIT_SOUND + s <= rows[1]["time"] <= EDIT_SOUND + s + 0.5, rows)
                self.assertEqual(set(self.transport("locked_running", prof)), {0})
                self.assert_chopped("locked_running", prof, mute=[])

    def test_316_stopped_sequencer_chop_writes_no_port_6a(self):
        for prof in self.labels316("locked_stopped"):
            with self.subTest(profile=prof):
                self.assertEqual(set(self.transport("locked_stopped", prof)), {0})
                self.assert_chopped("locked_stopped", prof, mute=[])


if __name__ == "__main__":
    unittest.main()
