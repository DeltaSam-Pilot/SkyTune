"""Real-world data point: ~5.8 FPS while loading into EGLL (spawning in) before settling around ~51 FPS on an
RTX 3070 Ti 8 GB / Ryzen 7 8700F. Low FPS or stutter right after loading in is its own problem: a temporary dip from
streaming scenery, shader compilation and rolling-cache fill - not a reason to cut settings or clear shader caches."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_real_world import m, USER_HW, applied

SPAWN = "I get 5.8 fps while loading into EGLL Heathrow when spawning in, then it settled around 51 fps"

class Detect(unittest.TestCase):
    def test_spawn_phrases(self):
        for s in (SPAWN, "low fps right after loading in", "stutters right after spawning", "fps tanks the first minute after the flight starts",
                  "really laggy just after the loading screen", "stutter when I spawn at the gate"):
            self.assertIn("spawn", m.detect_problems(s), s)

    def test_loading_word_is_not_popin_here(self):
        self.assertNotIn("popin", m.detect_problems(SPAWN))
        self.assertNotIn("popin", m.detect_problems("low fps right after loading in"))

    def test_real_popin_still_popin(self):
        self.assertEqual(m.detect_problems("scenery pops in while loading"), ["popin"])
        self.assertIn("popin", m.detect_problems("trees pop in right after spawning"))

    def test_caches_is_not_crashes(self):
        self.assertEqual(m.detect_problems("stutters after I cleared shader caches"), ["stutter"])

class Diagnose(unittest.TestCase):
    def setUp(self):
        self.cur = applied()[1]
        self.d = m.assistant_diagnose(SPAWN, hw=USER_HW, cfg=self.cur)

    def test_temporary_loading_dip(self):
        self.assertEqual(self.d["bottleneck"], "Loading")
        self.assertEqual(self.d["confidence"], "High")              # it says it settled
        self.assertIn("temporary", self.d["message"])
        notes = " ".join(self.d["notes"])
        for w in ("streaming scenery", "compiling shaders", "rolling cache", "minute"):
            self.assertIn(w, notes)
        self.assertIn("Don't clear shader caches before every flight", notes)

    def test_not_blamed_on_cpu_at_airport(self):
        self.assertNotEqual(self.d["bottleneck"], "CPU")

    def test_no_cache_clearing_or_general_cuts(self):
        ids = [f["id"] for f in self.d["fixes"]]
        self.assertNotIn("clear_shaders", ids); self.assertNotIn("update_cleanup", ids)
        self.assertFalse(set(ids) & {"traffic_down", "render_scale_down", "clouds_down", "shadows_down"})
        self.assertEqual(ids, [])                                    # SkyTune's own settings are already sensible

    def test_not_recovered_asks_to_report_back(self):
        d = m.assistant_diagnose("low fps right after loading in", hw=USER_HW, cfg=self.cur)
        self.assertEqual((d["bottleneck"], d["confidence"]), ("Loading", "Medium"))
        self.assertTrue(any("2–3 minutes" in n for n in d["notes"]))

    def test_after_clearing_caches(self):
        d = m.assistant_diagnose("stutters right after spawning, I cleared shader caches before the flight", hw=USER_HW, cfg=self.cur)
        self.assertEqual(d["bottleneck"], "Loading")
        self.assertTrue(any("shaders are being rebuilt" in n for n in d["notes"]))

    def test_high_tlod_on_8gb_gets_vram_advice_and_fixes(self):
        hv = dict(self.cur); hv["Graphics/Terrain/LoDFactor"] = 3.0; hv["Graphics/OffscreenTerrainPreCaching/Quality"] = 3
        d = m.assistant_diagnose("5 fps when spawning", hw=USER_HW, cfg=hv)
        fx = {f["id"]: f["changes"] for f in d["fixes"]}
        self.assertEqual(fx.get("tlod_vram"), {"Graphics/Terrain/LoDFactor": 2.0})
        self.assertEqual(fx.get("precache_sensible"), {"Graphics/OffscreenTerrainPreCaching/Quality": 2})
        self.assertTrue(any("8 GB of video memory" in n and "3.00" in n for n in d["notes"]))

    def test_crash_while_loading_is_not_a_dip(self):
        d = m.assistant_diagnose("the sim crashes to desktop right after loading in", hw=USER_HW, cfg=self.cur)
        self.assertNotEqual(d["bottleneck"], "Loading")

    def test_overlay_measure_after_settling_still_gpu(self):
        from test_real_world import REPORT
        self.assertEqual(m.assistant_diagnose(REPORT, hw=USER_HW, cfg=self.cur)["bottleneck"], "GPU")

if __name__ == "__main__":
    unittest.main()
