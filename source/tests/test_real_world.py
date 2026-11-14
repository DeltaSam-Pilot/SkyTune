"""Real-world data point (one user, one sample - not a benchmark): RTX 3070 Ti 8 GB, Ryzen 7 8700F, 32 GB, 1080p,
MSFS 2024 Steam, iniBuilds A320neo V2 on the ground at EGLL with SkyTune's settings applied. The dev-mode overlay
showed ~51 FPS 'Limited by Graphics Queue' (GPU queue ~32.6 ms vs main thread ~25.4 ms) and Terrain/Objects/Buildings
LOD factor readouts of 0.50 (Dynamic Settings at its floor). The assistant must call this GPU-bound."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m

USER_HW = dict(gpu="NVIDIA GeForce RTX 3070 Ti", vram_gb=8.0, cpu="AMD Ryzen 7 8700F 8-Core Processor", cores=8, threads=16,
               ram_gb=32, width=1920, height=1080)
REPORT = ("Getting about 51 fps on the ground at EGLL in the iniBuilds A320neo V2. Dev mode overlay says Limited by "
          "Graphics Queue, GPU queue 32.6 ms, main thread 25.4 ms, Terrain/Objects/Buildings LOD factor 0.50")

def applied():   # what SkyTune writes for this PC with default choices
    preset = m.recommend(USER_HW)[0]
    return preset, m.with_user_choices(m.PRESETS[preset], gpu_name=USER_HW["gpu"])

class Profile(unittest.TestCase):
    def test_user_pc_gets_balanced_30(self):
        self.assertEqual(m.cpu_tier(USER_HW["cpu"]), 3)
        self.assertEqual(m.gpu_tier(USER_HW["gpu"], 8)[0], 2)
        preset, vals = applied()
        self.assertEqual(preset, "Balanced-30")
        self.assertEqual(vals["Graphics/Terrain/LoDFactor"], 1.0); self.assertEqual(vals["Graphics/ObjectsLoD/LoDFactor"], 1.0)
        self.assertEqual(vals["Video/FrameGeneration"], "NONE")          # frame gen off by default (v1.2.1)
        self.assertLessEqual(vals["Graphics/Shadows/Size"], 2048)

class MeasuredLimitFilters(unittest.TestCase):
    def test_gpu_measured_never_offers_cpu_only_fixes_even_from_stock_settings(self):
        cur = {"Graphics/VolumetricClouds/Quality": 2, "Graphics/Shadows/Size": 768, "Graphics/Terrain/LoDFactor": 0.75}
        for p, _, _ in m.TRAFFIC_CATS[:4]: cur[p] = 2      # traffic still Medium, as in the demo screenshot
        d = m.assistant_diagnose(REPORT, hw=dict(m.DEMO_HW), cfg=cur)
        self.assertEqual(d["bottleneck"], "GPU")
        ids = [f["id"] for f in d["fixes"]]
        self.assertNotIn("traffic_down", ids); self.assertEqual(ids[0], "clouds_down")
        self.assertTrue(all(tuple(f["targets"]) != ("CPU",) for f in d["fixes"]))

    def test_gpu_measured_on_already_light_settings_offers_upscaling_not_cache_clearing(self):
        cur = m.current_values(m.UserCfg.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_UserCfg_2024.opt")))
        d = m.assistant_diagnose(REPORT, hw=dict(m.DEMO_HW), cfg=cur)          # default: smoothing preference locked
        self.assertEqual(d["fixes"], []); self.assertIn("already light", d["message"]); self.assertIn("My preferences", d["message"])
        self.assertNotIn("Fix stutters", d["message"])
        d2 = m.assistant_diagnose(REPORT, hw=dict(m.DEMO_HW), cfg=cur, locked=())  # user let SkyTune decide smoothing
        fx = {f["id"]: f["changes"] for f in d2["fixes"]}
        self.assertEqual(fx.get("upscaler_faster"), {"Video/DLSSMode": "BALANCED"})

class Overlay(unittest.TestCase):
    def test_parse_user_readout(self):
        ov = m.parse_overlay(REPORT)
        self.assertEqual(ov, {"fps": 51.0, "limited": "GPU", "gpu_ms": 32.6, "main_ms": 25.4, "lod_floor": True})
    def test_parse_variants(self):
        self.assertEqual(m.parse_overlay("limited by main thread, 40 fps")["limited"], "CPU")
        self.assertEqual(m.parse_overlay("I'm GPU-bound at 45fps")["limited"], "GPU")
        self.assertEqual(m.parse_overlay("fps: 38,5")["fps"], 38.5)
        self.assertEqual(m.parse_overlay("stutters on approach at busy airports"), {})
        self.assertNotIn("lod_floor", m.parse_overlay("LOD factor 1.00, 50 fps"))
    def test_ms_only_decides(self):
        d = m.assistant_diagnose("low fps, gpu 14 ms, main thread 28 ms", hw=USER_HW, cfg=applied()[1])
        self.assertEqual(d["bottleneck"], "CPU")

class Diagnosis(unittest.TestCase):
    def setUp(self):
        self.d = m.assistant_diagnose(REPORT, hw=USER_HW, cfg=applied()[1])
    def test_says_gpu_bound_with_high_confidence(self):
        self.assertEqual(self.d["bottleneck"], "GPU")
        self.assertEqual(self.d["confidence"], "High")
        self.assertIn("graphics card", self.d["message"])
        self.assertTrue(any("measurement" in w for w in self.d["why"]))
    def test_measurement_beats_busy_airport_heuristic(self):
        # without the readout, "busy airport" points at the processor; with it, the measurement wins
        self.assertEqual(self.d["context"].get("where"), "airport")
        self.assertEqual(m.assistant_diagnose("low fps at a busy airport", hw=USER_HW, cfg=applied()[1])["bottleneck"], "CPU")
    def test_lod_readout_is_not_a_popin_complaint(self):
        self.assertEqual(self.d["problems"], ["low_fps"])
        self.assertIn("popin", m.assistant_diagnose("scenery pops in, lod too low")["problems"])
    def test_fixes_target_the_graphics_card_only(self):
        ids = [f["id"] for f in self.d["fixes"]]
        self.assertTrue(ids, "expected at least one fix")
        self.assertEqual(ids[0], "clouds_down")
        for f in self.d["fixes"]:
            self.assertIn("GPU", f["targets"], f["id"])
            for k in f["changes"]: self.assertNotIn("LoDFactor", k)      # no LOD changes: CPU-side and DS already at floor
        self.assertNotIn("traffic_down", ids)                              # locked preference, not asked about
    def test_dynamic_settings_note(self):
        self.assertTrue(any("Dynamic Settings" in n and "0.50" in n for n in self.d["notes"]))
        self.assertNotIn("Dynamic Settings", self.d["message"])   # shown as a note line under the answer, message stays short
    def test_feedback_loop_walks_gpu_fixes(self):
        s = m.FixSession(self.d); first = s.next_fix(); s.stage(first); s.applied("backup.opt")
        r = s.feedback("worse")
        self.assertEqual((r["action"], r["undo"]), ("undo", "backup.opt"))   # Worse -> auto-undo of that change
        nxt = s.next_fix()
        self.assertIsNotNone(nxt); self.assertNotEqual(nxt["id"], first["id"])

if __name__ == "__main__":
    unittest.main()
