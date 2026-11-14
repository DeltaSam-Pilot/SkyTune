import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
S24 = os.path.join(os.path.dirname(__file__), "sample_UserCfg_2024.opt")
def hw(gpu, vram, cores, ram, w, h):
    return {"gpu": gpu, "vram_gb": vram, "cores": cores, "threads": cores * 2, "ram_gb": ram, "width": w, "height": h, "cpu": "x"}
SAM = hw("NVIDIA GeForce RTX 3070 Ti", 8, 8, 32, 1920, 1080)
PROFILES = {"sam": SAM, "4090_4k": hw("NVIDIA GeForce RTX 4090", 24, 8, 64, 3840, 2160),
            "7800xt": hw("AMD Radeon RX 7800 XT", 16, 8, 32, 2560, 1440), "1660": hw("NVIDIA GeForce GTX 1660 SUPER", 6, 6, 16, 1920, 1080),
            "igpu": hw("Intel(R) UHD Graphics 770", 1, 8, 16, 1920, 1080), "4080_4core": hw("NVIDIA GeForce RTX 4080", 16, 4, 32, 1920, 1080)}

class Goals(unittest.TestCase):
    def test_every_goal_and_profile_produces_valid_plan(self):
        c = m.UserCfg.load(S24)
        for g in m.GOALS:
            for name, h in PROFILES.items():
                preset, values, score, plain, tech = m.plan(h, g)
                self.assertIn(preset, m.PRESETS, (g, name)); self.assertTrue(0 <= score <= 4)
                self.assertTrue(plain and all(isinstance(x, str) for x in plain))
                self.assertIn("kept", plain[-1])
                cfg = m.UserCfg(c.text()); m.apply_values(cfg, m.with_user_choices(values))
                self.assertEqual(cfg.get("Video/AntiAliasing"), "TAA"); self.assertEqual(cfg.get("Video/FrameGeneration"), "NONE")
    def test_sam_3070ti_balanced(self):
        p, v, s, plain, _ = m.plan(SAM, "Balanced")
        self.assertEqual((p, s), ("Balanced-30", 2)); self.assertNotIn("Video/FrameLimiter", v)
    def test_sam_3070ti_best_visuals_vram_limited(self):
        p, v, s, plain, _ = m.plan(SAM, "Best visuals")
        self.assertEqual((p, s), ("Balanced", 2))                       # 8 GB VRAM blocks moving up
        self.assertEqual(v["Graphics/Texture/Quality"], 1)              # textures stay High (VRAM)
        self.assertEqual(v["Graphics/VolumetricClouds/Quality"], 3); self.assertGreaterEqual(v["Graphics/Shadows/Size"], 2048)
        self.assertTrue(any("video memory" in x for x in plain))
    def test_sam_3070ti_smooth(self):
        p, v, s, plain, _ = m.plan(SAM, "Smooth & steady")
        self.assertEqual(p, "Balanced-30"); self.assertEqual(v["Video/FrameLimiter"], 30)
        self.assertLessEqual(v["Graphics/ObjectsLoD/LoDFactor"], 0.8); self.assertLessEqual(v["Graphics/Terrain/LoDFactor"], 1.0)
        self.assertEqual(v["Graphics/Traffic/AircraftTrafficQuantity"], 0); self.assertEqual(v["Graphics/Characters/Quantity"], 0)
        self.assertTrue(any("30 FPS" in x for x in plain))
    def test_goal_shifts(self):
        self.assertEqual(m.plan(PROFILES["7800xt"], "Best visuals")[0], "Ultra+")
        self.assertEqual(m.plan(PROFILES["7800xt"], "Balanced")[0], "Quality")
        self.assertEqual(m.plan(PROFILES["7800xt"], "Smooth & steady")[0], "Balanced-30")
        self.assertEqual(m.plan(PROFILES["4090_4k"], "Smooth & steady")[0], "Quality")
        self.assertEqual(m.plan(PROFILES["4090_4k"], "Smooth & steady")[1]["Video/FrameLimiter"], 40)
        self.assertEqual(m.plan(PROFILES["4080_4core"], "Best visuals")[0], "Performance")   # CPU cap holds
        self.assertEqual(m.plan(PROFILES["igpu"], "Best visuals")[0], "Performance")
    def test_goal_respects_user_choices(self):
        traffic = {"Graphics/Traffic/AircraftTrafficQuantity": 2}
        for g in m.GOALS:
            v = m.with_user_choices(m.plan(SAM, g)[1], "DLSS", "NONE", traffic)
            self.assertEqual((v["Video/AntiAliasing"], v["Video/FrameGeneration"]), ("DLSS", "NONE"))
            self.assertEqual(v["Graphics/Traffic/AircraftTrafficQuantity"], 2, g)
    def test_goal_adjust_never_mutates_presets(self):
        import copy; snap = copy.deepcopy(m.PRESETS)
        for g in m.GOALS:
            for p in m.PRESETS: m.goal_adjust(m.PRESETS[p], g, 2)
        self.assertEqual(m.PRESETS, snap)
    def test_frame_limiter_key_confirmed_in_sample(self):
        self.assertIn("Video/FrameLimiter", m.UserCfg.load(S24).index)
if __name__ == "__main__": unittest.main()
