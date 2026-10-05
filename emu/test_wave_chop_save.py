"""Save a chopped stereo sound with stock Disk UI, then reload it cold.

Run: python3 -m unittest emu.test_wave_chop_save -v
The payloads are built from the current sources by emu.harness: capture, and
316 (WAVE316.SYS on OS 3.16) on each BIOS set of harness.bios316_sets() (one
per load segment by default, all four in release mode); MPC3K_PROFILES
narrows as for EmuSuite.  Each profile's job saves, then cold-boots the disk
it saved, so the two runs are sequential and the profiles run in parallel.
Times are relative to V = profile.view and the profile's timeline.  3.16's
Disk menu and Save/Load pages take the same keys (Disk -> 3 "A sound",
Disk -> 7 "Load,erase,rename"); only its file list appears later.
"""
import hashlib
import os
from pathlib import Path
import struct
import unittest

from emu import harness as h
from emu.harness import taps
from emu.mpc3k import run
from emu.panel import dial, write_smf
from emu.snd import snd, stereo1
from emu.test_wave_chop import do_action

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "build/emu/wave-chop-save"


def reload_events(profile: h.Profile) -> tuple[list, float]:
    """Cold boot of the saved disk: Disk / 7, '+' selects the second file
    (ZONE000.SND), <Load>, then Edit Sound.  Returns the events and the time
    the file list shows ZONE000 (Vailixi 26.75)."""
    tl = profile.timeline
    # '+' once the file list is up: 3.0 s after Disk on Vailixi; 3.16 lists
    # the files 3.5 s after Disk (harness.TIMELINE_316), so at its <Load> time.
    plus = tl.load_at + (tl.load_key if profile.is316 else 3.0)
    events = (taps((tl.cancel, "soft4"), (tl.load_at, "disk"), (tl.load_at + tl.load_seven, "7"),
                   (plus, "+"), (plus + 1.5, "soft1"))
              + taps((tl.view_at, "program_sounds"), (tl.view_at + tl.view_six, "6")))
    return events, plus + 0.75


def save_and_reload(profile: h.Profile) -> dict:
    runs = RUNS / profile.label
    runs.mkdir(parents=True, exist_ok=True)
    V = profile.view
    src = runs / "SAMPLE.SND"
    data = bytearray(snd("SAMPLE", stereo1(), vol=77))
    data[2 + 0x12] = (-12) & 255
    src.write_bytes(data)
    events = h.wave_events(taps((V + 1, "right"), (V + 2, "right"), (V + 3, "right"),
                                (V + 4, "right"))
                           + dial(-12, V + 5) + do_action(V + 8, profile)
                           + taps((V + 24, "disk"), (V + 25.5, "3"), (V + 28, "+"),
                                  (V + 30, "soft1")), profile=profile)
    image = h.wave_disk(profile, "wave-chop-save", [(src, "SAMPLE.SND")])
    before = hashlib.sha256(image.read_bytes()).hexdigest()
    first = runs / "save"
    screens = run(profile.bios, [V + 22, V + 29, V + 42], first, floppy=image,
                  rompath=profile.rompath, panel=write_smf(runs / "save.mid", events),
                  extra=["-autoboot_script",
                         str(h.observer(profile, runs / "save.lua", ["wave_zones", "snddump"]))])
    saved = image.read_bytes()

    load, listed = reload_events(profile)
    second = runs / "reload"
    loaded = run(profile.bios, [listed, V], second, floppy=image, rompath=profile.rompath,
                 panel=write_smf(runs / "load.mid", load),
                 extra=["-autoboot_script",
                        str(h.observer(profile, runs / "reload.lua", ["wave_zones", "snddump"]))])
    return {"first": first, "second": second, "screens": screens, "loaded": loaded,
            "before": before, "saved": saved, "listed": listed}


class ChopSave(unittest.TestCase):
    results: dict = {}
    profiles: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        h.require_tools()
        wanted = set(filter(None, os.environ.get("MPC3K_PROFILES", "").split(","))) or set(h.ALL_PROFILES)
        selected = (([h.payload("capture")] if "capture" in wanted else [])
                    + ([h.payload("316", bios) for bios in h.bios316_sets()] if "316" in wanted else []))
        cls.profiles = {p.label: p for p in selected}
        for p in selected:
            p.record(RUNS)
        cls.results = h.run_parallel(cls.profiles, lambda label, p: save_and_reload(p))

    def test_stereo_chop_survives_stock_save_and_cold_reload(self):
        self.assertTrue(self.results, "no profile selected (MPC3K_PROFILES)")
        for label, r in self.results.items():
            with self.subTest(profile=label):
                V = self.profiles[label].view
                first, second = r["first"], r["second"]
                self.assertIn("ZONE000", "".join(r["screens"][1]["rows"]))
                self.assertNotEqual(hashlib.sha256(r["saved"]).hexdigest(), r["before"])
                self.assertIn(b"ZONE000 SND", r["saved"][0x2600:0x4200])
                self.assertIn("ZONE000", "".join(r["loaded"][0]["rows"]))
                self.assertIn("ZONE000", "".join(r["loaded"][1]["rows"]))
                self.assertEqual(h.pcm(second, V, 0), h.pcm(first, V + 22, 1))
                old = (first / f"records_{h.label(V + 22)}.bin").read_bytes()[36:72]
                new = (second / f"records_{h.label(V)}.bin").read_bytes()[:36]
                self.assertEqual(new[:0x20], old[:0x20])
                self.assertEqual(struct.unpack_from("<I", new, 0x1C)[0], 33075 // 4)


if __name__ == "__main__":
    unittest.main()
