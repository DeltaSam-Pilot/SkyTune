import os, sys, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(__file__)
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")
SLEG = os.path.join(HERE, "sample_UserCfg_legacy.opt")

class Parser(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "UserCfg.opt"); shutil.copy(S24, self.p)
    def tearDown(self): shutil.rmtree(self.d)
    def raw(self): return open(self.p, "rb").read()

    def test_roundtrip_identical_both_samples(self):
        for s in (S24, SLEG):
            shutil.copy(s, self.p); b = self.raw(); m.UserCfg.load(self.p).save(self.p); self.assertEqual(b, self.raw())
    def test_reads_nested(self):
        c = m.UserCfg.load(self.p)
        self.assertEqual(c.get("Graphics/Version"), "2.1.0")
        self.assertEqual(c.get("Video/FrameGeneration"), "NONE")
        self.assertEqual(c.get("Video/FullScreenResolution"), "2560 1440")
        self.assertEqual(c.get("Graphics/Procedural/TreesQuality"), "1")
        self.assertEqual(c.get("GraphicsVR/Terrain/LoDFactor"), "0.500000")
    def test_all_2024_keys_exist_in_real_2024_sample(self):
        c = m.UserCfg.load(self.p)
        for s in m.SETTINGS:
            if "(MSFS 2020)" in s[1]: continue          # legacy 2020-only keys are absent from 2024 files
            self.assertIn(s[0], c.index, s[0])
    def _apply(self, vals):
        shutil.copy(S24, self.p); before = self.raw().split(b"\r\n")
        c = m.UserCfg.load(self.p); ch = m.apply_values(c, vals); m.write_with_backup(c, self.p)
        c2 = m.UserCfg.load(self.p); after = self.raw().split(b"\r\n"); self.assertEqual(len(before), len(after))
        idx = {c2.index[p] for p in ch}
        for i, (a, b) in enumerate(zip(before, after)):
            if i not in idx: self.assertEqual(a, b)
        self.assertEqual(c2.get("Video/FullScreenResolution"), "2560 1440")
        self.assertEqual(c2.get("GraphicsVR/Terrain/LoDFactor"), "0.500000"); self.assertEqual(c2.get("Video/FrameGenerationVR"), "NONE")
        return c2
    def test_default_choices_taa_fg_off(self):
        for name in m.PRESETS:
            c2 = self._apply(m.with_user_choices(m.PRESETS[name]))
            self.assertEqual((c2.get("Video/AntiAliasing"), c2.get("Video/FrameGeneration"), c2.get("Video/NBFramesToGenerate")),
                             ("TAA", "NONE", "1"), name); self.assertEqual(c2.get("Graphics/Preset"), "Custom")
    def test_presets_respect_user_choices(self):
        for aa in m.AA_CHOICES.values():
            for fg in m.FG_CHOICES.values():
                for name in m.PRESETS:
                    v = m.with_user_choices(m.PRESETS[name], aa, fg)
                    self.assertEqual((v["Video/AntiAliasing"], v["Video/FrameGeneration"]), (aa, fg))
                    if fg == "NONE": self.assertNotIn("Video/NBFramesToGenerate", v)
        c2 = self._apply(m.with_user_choices(m.PRESETS["Quality"], "DLSS", "NONE"))
        self.assertEqual((c2.get("Video/AntiAliasing"), c2.get("Video/FrameGeneration")), ("DLSS", "NONE"))
        c2 = self._apply(m.with_user_choices(m.PRESETS["Performance"], "TAA", "DLSSG"))
        self.assertEqual(c2.get("Video/FrameGeneration"), "DLSSG")
    def test_with_user_choices_does_not_mutate_presets(self):
        before = dict(m.PRESETS["Balanced"]); m.with_user_choices(m.PRESETS["Balanced"], "DLSS", "NONE")
        self.assertEqual(m.PRESETS["Balanced"], before)
    def test_dlss_support(self):
        self.assertEqual(m.dlss_support("NVIDIA GeForce RTX 3070 Ti")[:2], (True, False))
        self.assertEqual(m.dlss_support("NVIDIA GeForce RTX 4070 SUPER")[:2], (True, True))
        self.assertEqual(m.dlss_support("NVIDIA GeForce RTX 5090")[:2], (True, True))
        self.assertEqual(m.dlss_support("AMD Radeon RX 7800 XT")[:2], (False, False))
        self.assertEqual(m.dlss_support("NVIDIA GeForce GTX 1660 SUPER")[:2], (False, False))
        self.assertEqual(m.dlss_support("Unknown")[:2], (None, None))
        self.assertIn("HAGS", m.dlss_support("NVIDIA GeForce RTX 4080")[2])
    def test_resolution_opt_in(self):
        c = m.UserCfg.load(self.p)
        self.assertEqual(m.apply_values(c, {"Video/FullScreenResolution": "1920x1080"}), [])
        m.apply_values(c, {"Video/FullScreenResolution": "1920x1080"}, change_resolution=True)
        self.assertEqual(c.get("Video/FullScreenResolution"), "1920 1080")
    def test_preset_custom_on_legacy(self):
        shutil.copy(SLEG, self.p); c = m.UserCfg.load(self.p)
        c.set("Graphics/Preset", "High"); m.apply_values(c, {"Graphics/Terrain/LoDFactor": 5})
        self.assertEqual(c.get("Graphics/Preset"), "Custom"); self.assertEqual(c.get("Graphics/Terrain/LoDFactor"), "5.000000")
    def test_backup_and_restore(self):
        orig = self.raw(); c = m.UserCfg.load(self.p); m.apply_values(c, {"Graphics/Terrain/LoDFactor": 3})
        b = m.write_with_backup(c, self.p); self.assertEqual(open(b, "rb").read(), orig)
        self.assertNotEqual(self.raw(), orig); shutil.copy2(b, self.p); self.assertEqual(self.raw(), orig)
    def test_lf_and_spaces(self):
        t = open(S24, newline="").read().replace("\r\n", "\n").replace("\t", "    ")
        c = m.UserCfg(t); self.assertEqual(c.text(), t)
        c.set("Video/AntiAliasing", "TAA"); self.assertIn("    AntiAliasing TAA\n", c.text())
    def test_unbalanced(self):
        with self.assertRaises(ValueError): m.UserCfg("{Graphics\n\tPreset Custom\n")
    def test_missing_key_never_added(self):
        c = m.UserCfg("{Graphics\n\tPreset High\n}\n"); self.assertEqual(m.apply_values(c, m.PRESETS["Ultra+"]), [])
    def test_detect_steam_first(self):
        st = os.path.join(self.d, "Microsoft Flight Simulator 2024"); os.makedirs(st); shutil.copy(S24, os.path.join(st, "UserCfg.opt"))
        ms = os.path.join(self.d, "Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache"); os.makedirs(ms); shutil.copy(S24, os.path.join(ms, "UserCfg.opt"))
        os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = self.d
        self.assertEqual(m.detect_usercfg()[0], "MSFS 2024 · Steam"); os.remove(os.path.join(st, "UserCfg.opt"))
        self.assertEqual(m.detect_usercfg()[0], "MSFS 2024 · MS Store / Xbox")

def hw(gpu, vram, cores, ram, w, h):
    return {"gpu": gpu, "vram_gb": vram, "cores": cores, "threads": cores * 2, "ram_gb": ram, "width": w, "height": h, "cpu": "x"}

class Mapping(unittest.TestCase):
    def rec(self, *a): return m.recommend(hw(*a))[0]
    def test_sam_3070ti_1080p(self):
        p, s, r = m.recommend(hw("NVIDIA GeForce RTX 3070 Ti", 8, 8, 32, 1920, 1080))
        self.assertEqual(p, "Balanced-30")
        v = m.PRESETS[p]
        self.assertLessEqual(v["Graphics/Terrain/LoDFactor"], 1.0); self.assertLessEqual(v["Graphics/ObjectsLoD/LoDFactor"], 1.0)
        self.assertEqual(v["Graphics/Texture/Quality"], 1)          # High, fits 8 GB
        self.assertLessEqual(v["Graphics/Traffic/AircraftTrafficQuantity"], 1)
        self.assertEqual(v["Video/FrameGeneration"], "NONE")
    def test_flagships(self):
        self.assertEqual(self.rec("NVIDIA GeForce RTX 4090", 24, 8, 64, 3840, 2160), "Ultra+")
        self.assertEqual(self.rec("AMD Radeon RX 7900 XTX", 24, 16, 64, 2560, 1440), "Ultra+")
    def test_amd_mid(self):
        self.assertEqual(self.rec("AMD Radeon RX 7800 XT", 16, 8, 32, 2560, 1440), "Quality")
        self.assertEqual(self.rec("AMD Radeon RX 7900 GRE", 16, 8, 32, 3840, 2160), "Balanced")
        self.assertEqual(self.rec("AMD Radeon RX 6600", 8, 6, 16, 1920, 1080), "Balanced-30")
    def test_caps(self):
        self.assertEqual(self.rec("NVIDIA GeForce RTX 4080", 16, 4, 32, 1920, 1080), "Performance")   # 4 cores
        self.assertEqual(self.rec("NVIDIA GeForce RTX 4080", 16, 8, 8, 1920, 1080), "Performance")    # 8 GB RAM
        self.assertEqual(self.rec("NVIDIA GeForce RTX 3080", 10, 8, 32, 3840, 2160), "Balanced")
        self.assertEqual(self.rec("Intel(R) UHD Graphics 770", 1, 8, 16, 1920, 1080), "Performance")
        self.assertEqual(self.rec("NVIDIA GeForce GTX 1660 SUPER", 6, 6, 16, 1920, 1080), "Performance")
    def test_vram_registry_preferred(self):
        g = m.pick_gpu([{"Name": "NVIDIA GeForce RTX 3070 Ti", "Bytes": 4293918720, "Src": "wmi"},
                        {"Name": "NVIDIA GeForce RTX 3070 Ti", "Bytes": 8589934592, "Src": "registry"},
                        {"Name": "Intel(R) UHD Graphics 770", "Bytes": 1073741824, "Src": "wmi"}])
        self.assertEqual(g["name"], "NVIDIA GeForce RTX 3070 Ti"); self.assertEqual(g["vram_gb"], 8.0)
        self.assertIn("registry", g["src"])
    def test_vram_wmi_fallback(self):
        g = m.pick_gpu([{"Name": "AMD Radeon RX 6800", "Bytes": 4293918720, "Src": "wmi"}]); self.assertEqual(g["vram_gb"], 4.0)
        self.assertIn("max 4 GB", g["src"])
if __name__ == "__main__": unittest.main(verbosity=2)

class Plain(unittest.TestCase):
    def test_summary_plain_english(self):
        c = m.UserCfg.load(S24); before = c.text()
        ch = m.summarize_changes(c, m.with_user_choices(m.PRESETS["Balanced-30"]))
        self.assertEqual(c.text(), before)                       # summary never modifies
        d = {l: (o, n) for l, o, n in ch}
        self.assertEqual(d["Smooth edges"], ("NVIDIA DLSS", "TAA"))
        self.assertEqual(d["Terrain detail distance"], ("75", "100"))
        self.assertNotIn("Screen resolution", d)
        # summary count matches what apply would change (excluding auto Preset Custom)
        ch2 = m.apply_values(m.UserCfg.load(S24), m.with_user_choices(m.PRESETS["Balanced-30"]))
        self.assertEqual(len(ch), len([p for p in ch2 if p != "Graphics/Preset"]))
    def test_summary_resolution_opt_in(self):
        c = m.UserCfg.load(S24)
        self.assertEqual(m.summarize_changes(c, {"Video/FullScreenResolution": "1920 1080"}), [])
        self.assertEqual(m.summarize_changes(c, {"Video/FullScreenResolution": "1920 1080"}, True),
                         [("Screen resolution", "2560 1440", "1920 1080")])
    def test_no_changes(self):
        c = m.UserCfg.load(S24); self.assertEqual(m.summarize_changes(c, {"Video/AntiAliasing": "DLSS"}), [])
    def test_sim_status_text(self):
        self.assertEqual(m.sim_status_text(False), ("ok", "Sim closed – safe to apply"))
        self.assertEqual(m.sim_status_text(True)[0], "err"); self.assertIn("close it first", m.sim_status_text(True)[1])
        self.assertEqual(m.sim_status_text(None)[0], "warn")
    def test_simple_presets_exist(self):
        for p in m.SIMPLE_PRESETS: self.assertIn(p, m.PRESETS)
    def test_names(self):
        self.assertEqual(m.APP_NAME, "SkyTune for MSFS 2020/2024"); self.assertEqual(m.VERSION, "1.8.0")
