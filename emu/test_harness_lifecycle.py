"""Zone-map lifetime through the hooked stock paths, driven by real panel input.

Run: python3 -m unittest emu.test_harness_lifecycle -v

Covers (notes/wave_zones.md "State lifetime", notes/wave_chop.md hooks):

- every stock Edit Sound ``Do:`` operation run while a zone map exists
  (dispatch hook B99A:0AFF clears the map before rejoining B99A:0B0D);
- reopening the view after editing the zone pair on the stock page (import
  path: the pair is clamped between its outer neighbours);
- A -> B -> A sound selection on field 0 (B99A:04DB commit hook);
- deleting the map's source sound, and another sound, on Program/Sounds 7
  (D0C0:0B19 prologue hook);
- TEMPORARY999 (made by Do COPY ZONE-> TEMP) across the waveform view: the
  stock page exit (3.16 0B72:1212, Vailixi B99A:159E) deletes it whenever
  [bp-1] != 0, and a waveform Help / Exit leaves the page only to re-enter
  it.  On 3.16 PMONEY replaces the exit's lookup (zones_exit_temp, patch at
  image 0xC932) and keeps TEMPORARY999 while zones_resume is set
  (``temp_kept_by_view``; before 2026-10-16 Help then Exit deleted it, audit
  B1, MAME); leaving Edit Sound for the main screen still deletes it, as
  stock does (``temp_deleted_on_leave``, and the end of ``temp_kept_by_view``).
  zones_exit_temp exists on 3.16 only (``%ifdef PROFILE_316``): on the
  capture profile Exit still deletes TEMPORARY999 (MAME, 2026-10-16), so the
  keep assertion is checked on 3.16 only (TEMP_KEPT_BY_VIEW).

Payloads come from emu.harness: capture for every case, generic for GENERIC,
and every case on the 316 profile (WAVE316.SYS on OS 3.16; one BIOS set per
load segment by default, all four in release mode).  Times
are relative to the profile's timeline (V = profile.view: 40 s on Vailixi,
52 s on 3.16).  Observers only read RAM.  Each case also checks that the
stock action really happened (positive control), so an unexecuted action
cannot pass.

The ``Do:`` cases are named by the Vailixi option index k (``do0`` ..
``do9``, the order of OPS).  Stock 3.16 has eight options (DGROUP
32C6..3341; dispatch 0B72:0B0A ``cmp bx,7``); PMONEY lists all ten in
Vailixi's order (mods/wave_chop.inc CHOP_EDITDO): COPY ZONE-> SND (k=1) and
TRUNC SFT ST+END (k=7) run in the cave under PMONEY's names ZONE->NEW SOUND
and CROP SOFT ST-END (OPS_316), so every case runs on 3.16 with the same
index and asserts the same result.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from emu import harness as h
from emu.harness import pcm, sound_records, taps, zone_rows
from emu.panel import dial
from emu.snd import sine441, snd, stereo1

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/harness-lifecycle-tests"
LEN = len(sine441()[0])
SOFT_START, SOFT_END = 1000, 50000
FOUR = [LEN * i // 4 for i in range(5)]
OPS = ["COPY ZONE-> TEMP", "COPY ZONE-> SND ", "INS TMP-> ZON ST", "INS TMP-> ZN END",
       "DELETE ZONE", "DEL BEFR SOFT ST", "DEL AFTR SFT END", "TRUNC SFT ST+END",
       "SILENCE ZONE", "REVERSE ZONE"]
# PMONEY on 3.16 lists the Do options in Vailixi's order (mods/wave_chop.inc
# CHOP_EDITDO); options 1 and 7 run in the cave under PMONEY's own names.
DO_INDEX_316 = {k: k for k in range(10)}
OPS_316 = [{1: "ZONE->NEW SOUND ", 7: "CROP SOFT ST-END"}.get(k, op) for k, op in enumerate(OPS)]
# Two sounds loaded one after the other.  After the first <Load> the second
# file is selected once the first sound is in RAM: 4.5 s on Vailixi (108 KB
# SINE441 done by 31 s after <Load> at 26.5 s), 5.0 s on 3.16 (done by 43.8 s
# after <Load> at 39.0 s, harness.TIMELINE_316).  The view opens 7 s after the
# second <Load> (130 KB STEREO1: 6.0 s on 3.16).
FIRST_LOADED, FIRST_LOADED_316 = 4.5, 5.0
# Profiles whose waveform Exit keeps TEMPORARY999 (zones_exit_temp, 3.16 only).
TEMP_KEPT_BY_VIEW = ("316",)
SECOND_LOADED = 7.0


def two_sound_events(profile: h.Profile, *more) -> tuple[list, float]:
    """Load AAA then BBB, open the view on AAA; returns (events, VA = view time)."""
    tl = profile.timeline
    plus = tl.load_at + tl.load_key + (FIRST_LOADED_316 if profile.is316 else FIRST_LOADED)
    view_at = plus + 1 + SECOND_LOADED
    events = (h.load_sound_events(profile=profile) + taps((plus, "+"), (plus + 1, "soft1"))
              + h.open_view_events(view_at, profile=profile))
    for part in more:
        events += part
    return events, view_at + tl.view - tl.view_at


def four_zones(at: float) -> list:
    return taps((at, "right"), (at + 1, "right"), (at + 2, "right")) + dial(-12, at + 3)


def stock_field(at: float, rights: int) -> list:
    """Exit the view to the stock page, then Right `rights` times."""
    return taps((at, "soft4")) + taps(*[(at + 2 + i * .2, "right") for i in range(rights)])


class Lifecycle(h.EmuSuite):
    RUNS = RUNS
    GENERIC = frozenset({"do4", "do8", "import_ms", "abba", "delete_source"})
    PROFILE_NAMES = h.ALL_PROFILES
    SKIP_316 = frozenset()
    VA: dict = {}

    @classmethod
    def cases(cls, profile, runs):
        V = profile.view
        one = runs / "TEST.SND"
        one.write_bytes(snd("TEST", sine441(), start=SOFT_START, end=SOFT_END))
        a = runs / "AAA.SND"
        a.write_bytes(snd("AAA", sine441()))
        b = runs / "BBB.SND"
        b.write_bytes(snd("BBB", stereo1()))
        cases = {}
        for k in range(10):
            if profile.is316 and f"do{k}" in cls.SKIP_316:
                continue
            index = DO_INDEX_316[k] if profile.is316 else k
            # Map of four zones, exit, Right x16 to Do:, select op k, Do, Help.
            events = four_zones(V + 1) + stock_field(V + 7, 16)
            if index:
                events += dial(index, V + 13)
            events += taps((V + 15, "soft4"), (V + 19, "help"))
            pcm_times = f"{V + 14.5},{V + 18}" if k in (8, 9) else "0"
            cases[f"do{k}"] = h.Case(events=h.wave_events(events, profile=profile),
                                     times=[V + 6, V + 14.5, V + 15.5, V + 18, V + 21],
                                     files=[(one, "TEST.SND")], env={"SNDDUMP_PCM": pcm_times})
        # Stock page: Right x11 is Zone end's milliseconds, x10 its seconds.
        for name, rights in (("import_ms", 11), ("import_clamp", 10)):
            events = four_zones(V + 1) + stock_field(V + 7, rights) + dial(3, V + 13)
            cases[name] = h.Case(events=h.wave_events(events + taps((V + 19, "help")), profile=profile),
                                 times=[V + 6, V + 18, V + 21], files=[(one, "TEST.SND")],
                                 env={"SNDDUMP_PCM": "0"})
        # TEMPORARY999: exit the view, Right x16 to Do: (COPY ZONE-> TEMP), Do.
        copy_temp = stock_field(V + 1, 16) + taps((V + 9, "soft4"))
        cases["temp_kept_by_view"] = h.Case(
            events=h.wave_events(copy_temp + taps((V + 13, "help"), (V + 18, "soft4"), (V + 23, "main_screen")),
                                 profile=profile),
            times=[V + 8, V + 12, V + 17, V + 22, V + 27], files=[(one, "TEST.SND")], parts=("wave_zones",))
        cases["temp_deleted_on_leave"] = h.Case(
            events=h.wave_events(copy_temp + taps((V + 13, "main_screen")), profile=profile),
            times=[V + 8, V + 12, V + 17], files=[(one, "TEST.SND")], parts=("wave_zones",))
        _, VA = two_sound_events(profile)
        cls.VA[profile.label] = VA
        # A -> B -> A on field 0, then reopen.
        events = (four_zones(VA + 1) + taps((VA + 7, "soft4"))
                  + taps(*[(VA + 9 + i * .2, "left") for i in range(16)])
                  + taps((VA + 13, "+"), (VA + 15, "-"), (VA + 17, "help")))
        cases["abba"] = h.Case(events=two_sound_events(profile, events)[0],
                               times=[VA + 6, VA + 12.5, VA + 14, VA + 16, VA + 19],
                               files=[(a, "AAA.SND"), (b, "BBB.SND")], env={"SNDDUMP_PCM": "0"})
        # Delete the map's source (AAA), or the other sound (BBB), on
        # Program/Sounds 7 <Delete> <Do it>, with the map still valid.
        for name, other in (("delete_source", False), ("delete_other", True)):
            events = (four_zones(VA + 1)
                      + taps((VA + 7, "soft4"), (VA + 9, "main_screen"), (VA + 11, "program_sounds"),
                             (VA + 12.5, "7"))
                      + (taps((VA + 14, "+")) if other else [])
                      + taps((VA + 15, "soft4"), (VA + 17, "soft1")))
            cases[name] = h.Case(events=two_sound_events(profile, events)[0],
                                 times=[VA + 6, VA + 16, VA + 19],
                                 files=[(a, "AAA.SND"), (b, "BBB.SND")], env={"SNDDUMP_PCM": "0"})
        return cases

    # ------------------------------------------------------------------

    def each_op(self, k: int):
        """Runs of case do<k>; a case that did not run fails op k only."""
        with self.subTest(op=k):
            return self.each(f"do{k}")
        return []

    def test_every_stock_do_operation_invalidates_the_map(self):
        for k in range(10):
            for prof, d, screens in self.each_op(k):
                with self.subTest(op=k, profile=prof):
                    V = self.view(prof)
                    r = zone_rows(d)
                    # The map existed when Do was pressed on op k ...
                    self.assertEqual((r[V + 14.5]["valid"], r[V + 14.5]["count"]), (1, 4))
                    ops = OPS_316 if prof.startswith("316") else OPS
                    self.assertIn(f"Do:{ops[k]}", screens[1]["rows"][5].replace(".", " "))
                    # ... and the dispatch invalidated it before the stock op.
                    self.assertEqual(r[V + 15.5]["valid"], 0)
                    self.assertEqual(r[V + 18]["valid"], 0)
                    # Reopening builds a fresh equal division of the record as
                    # the stock op left it.
                    length = sound_records(d, V + 21)[0]["length"]
                    self.assertEqual((r[V + 21]["valid"], r[V + 21]["current"], r[V + 21]["count"]),
                                     (1, 1, 16))
                    self.assertEqual(r[V + 21]["bounds"], [length * i // 16 for i in range(17)])
                    self.assertIn("mode=32", screens[4]["head"])

    def test_stock_do_operations_really_ran(self):
        """Positive controls: the effect of each stock op on zone 1 = [0, 13781)."""
        zone = FOUR[1]
        expected_length = {4: LEN - zone, 5: LEN - SOFT_START, 6: SOFT_END, 7: SOFT_END - SOFT_START}
        for k in range(10):
            for prof, d, _ in self.each_op(k):
                with self.subTest(op=k, profile=prof):
                    V = self.view(prof)
                    before, after = sound_records(d, V + 14.5), sound_records(d, V + 18)
                    self.assertEqual(len(before), 1)
                    self.assertEqual(before[0]["length"], LEN)
                    if k in (0, 1):
                        name = "TEMPORARY999" if k == 0 else "ZONE000"
                        self.assertEqual([(r["name"], r["length"]) for r in after.values()][1:],
                                         [(name, zone)])
                    elif k in (2, 3):
                        # No TEMPORARY999 exists: the stock insert is a no-op.
                        self.assertEqual(after, before)
                    elif k in expected_length:
                        self.assertEqual(after[0]["length"], expected_length[k])
                    else:
                        old, new = pcm(d, V + 14.5, 0), pcm(d, V + 18, 0)
                        self.assertEqual(new[2 * zone:], old[2 * zone:])
                        if k == 8:
                            self.assertEqual(new[:2 * zone], bytes(2 * zone))
                        else:
                            words = [old[i:i + 2] for i in range(0, 2 * zone, 2)]
                            self.assertEqual(new[:2 * zone], b"".join(reversed(words)))
                        self.assertNotEqual(new, old)

    def test_reopen_imports_the_stock_zone_pair(self):
        for prof, d, screens in self.each("import_ms"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                r = zone_rows(d)
                self.assertEqual(r[V + 6]["bounds"][:5], FOUR)
                # Stock page edit: Zone end +3 ms = +132 frames (13781 -> 13913).
                self.assertIn("Zone end:000.315.22", screens[1]["rows"][3])
                after = r[V + 21]
                self.assertEqual((after["valid"], after["current"], after["count"]), (1, 1, 4))
                self.assertEqual(after["bounds"][:5], [0, 13913, FOUR[2], FOUR[3], LEN])

    def test_reopen_clamps_an_imported_pair_to_its_neighbours(self):
        for prof, d, screens in self.each("import_clamp"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                # Stock page: Zone end +3 s, which the stock page clamps to the
                # sound length; the import clamps it to the next boundary.
                self.assertIn("Zone end:001.250.00", screens[1]["rows"][3])
                after = zone_rows(d)[V + 21]
                self.assertEqual((after["valid"], after["current"], after["count"]), (1, 1, 4))
                self.assertEqual(after["bounds"][:5], [0, FOUR[2], FOUR[2], FOUR[3], LEN])

    def test_a_b_a_selection_discards_the_map(self):
        for prof, d, screens in self.each("abba"):
            with self.subTest(profile=prof):
                VA = self.VA[prof]
                r = zone_rows(d)
                self.assertEqual((r[VA + 6]["valid"], r[VA + 6]["count"]), (1, 4))
                self.assertEqual(r[VA + 12.5]["valid"], 1)          # exit alone keeps it
                self.assertIn("Edit Snd:BBB", screens[2]["rows"][0])
                self.assertEqual(r[VA + 14]["valid"], 0)            # selecting B dropped it
                self.assertIn("Edit Snd:AAA", screens[3]["rows"][0])
                self.assertEqual(r[VA + 16]["valid"], 0)            # back on A: still dropped
                after = r[VA + 19]
                self.assertIn("mode=32", screens[4]["head"])
                self.assertEqual((after["valid"], after["current"], after["count"]), (1, 1, 16))
                self.assertEqual(after["bounds"], [LEN * i // 16 for i in range(17)])

    def test_deleting_the_source_sound_invalidates_the_map(self):
        for prof, d, _ in self.each("delete_source"):
            with self.subTest(profile=prof):
                VA = self.VA[prof]
                r = zone_rows(d)
                self.assertEqual([r[t]["valid"] for t in (VA + 6, VA + 16)], [1, 1])
                self.assertEqual(r[VA + 19]["valid"], 0)
                names = [x["name"] for x in sound_records(d, VA + 19).values()]
                self.assertEqual(names, ["BBB"])                    # AAA really deleted

    def test_deleting_another_sound_keeps_the_map(self):
        for prof, d, _ in self.each("delete_other"):
            with self.subTest(profile=prof):
                VA = self.VA[prof]
                r = zone_rows(d)
                self.assertEqual([r[t]["valid"] for t in (VA + 6, VA + 16, VA + 19)], [1, 1, 1])
                self.assertEqual(r[VA + 19]["bounds"][:5], FOUR)
                names = [x["name"] for x in sound_records(d, VA + 19).values()]
                self.assertEqual(names, ["AAA"])                    # BBB really deleted

    def temp_names(self, d: Path, t: float) -> list[str]:
        return [r["name"] for r in sound_records(d, t).values()]

    def test_temp_kept_by_view(self):
        for prof, d, screens in self.each("temp_kept_by_view"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assertEqual(self.temp_names(d, V + 8), ["TEST"])
                self.assertIn("Do:COPY ZONE-> TEMP", screens[0]["rows"][5].replace(".", " "))
                self.assertEqual(self.temp_names(d, V + 12), ["TEST", "TEMPORARY999"])
                # Help opened the view; Soft Key 4 Exit returned to the page.
                self.assertIn("mode=32", screens[2]["head"])
                self.assertEqual(self.temp_names(d, V + 17), ["TEST", "TEMPORARY999"])
                self.assertIn("Edit Snd:TEST", screens[3]["rows"][0])
                if self.profiles[prof].name in TEMP_KEPT_BY_VIEW:
                    self.assertEqual(self.temp_names(d, V + 22), ["TEST", "TEMPORARY999"])
                # Leaving Edit Sound afterwards still deletes it.
                self.assertNotIn("Edit Snd", screens[4]["rows"][0])
                self.assertEqual(self.temp_names(d, V + 27), ["TEST"])

    def test_temp_deleted_on_leave(self):
        for prof, d, screens in self.each("temp_deleted_on_leave"):
            with self.subTest(profile=prof):
                V = self.view(prof)
                self.assertEqual(self.temp_names(d, V + 8), ["TEST"])
                self.assertEqual(self.temp_names(d, V + 12), ["TEST", "TEMPORARY999"])
                self.assertNotIn("Edit Snd", screens[2]["rows"][0])
                self.assertEqual(self.temp_names(d, V + 17), ["TEST"])


if __name__ == "__main__":
    unittest.main()
