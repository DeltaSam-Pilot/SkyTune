"""Behaviour carried over from SkyTune v1.2.1 (MSFS 2020 + 2024 support)."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import msfs_tweaker as m
HERE = os.path.dirname(__file__)
S20 = os.path.join(HERE, "sample_UserCfg_2020.opt"); S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")

class Editions(unittest.TestCase):
    def test_four_windows_candidates(self):
        c = m.candidate_paths(env={"APPDATA": r"C:\A", "LOCALAPPDATA": r"C:\L"})
        self.assertEqual([l for l, _ in c], ["MSFS 2024 · Steam", "MSFS 2024 · MS Store / Xbox", "MSFS 2020 · Steam", "MSFS 2020 · MS Store / Xbox"])
    def test_detect_all_side_by_side(self):
        d = tempfile.mkdtemp(); env = {"APPDATA": d, "LOCALAPPDATA": d}
        for sub in ("Microsoft Flight Simulator 2024", "Microsoft Flight Simulator"):
            os.makedirs(os.path.join(d, sub)); open(os.path.join(d, sub, "UserCfg.opt"), "w").write("{Video\n}\n")
        self.assertEqual([l for l, _ in m.detect_usercfgs(env=env)], ["MSFS 2024 · Steam", "MSFS 2020 · Steam"])
    def test_version_from_path_and_schema(self):
        self.assertEqual(m.detect_simulator_version(r"C:\x\Microsoft Flight Simulator 2024\UserCfg.opt"), "2024")
        self.assertEqual(m.detect_simulator_version(r"C:\x\Microsoft Flight Simulator\UserCfg.opt"), "2020")
        self.assertEqual(m.detect_simulator_version("/tmp/x.opt", m.UserCfg.load(S20)), "2020")
        self.assertEqual(m.detect_simulator_version("/tmp/x.opt", m.UserCfg.load(S24)), "2024")
        self.assertEqual(m.detect_simulator_version("/tmp/x.opt", m.UserCfg("{Foo\n\tBar 1\n}\n")), "unknown")

class FrameGen(unittest.TestCase):
    def test_default_fg_off(self):
        self.assertEqual(m.FG_CHOICES[m.DEFAULT_FG_LABEL] if hasattr(m, "DEFAULT_FG_LABEL") else m.DEFAULT_FG, "NONE")
        self.assertNotIn("Video/NBFramesToGenerate", m.with_user_choices(m.PRESETS["Balanced"]))
    def test_fsr_aa_choice(self):
        self.assertEqual(m.AA_CHOICES["AMD FSR"], "FSR")
    def test_multiplier_clamp(self):
        v = dict(m.PRESETS["Balanced"], **{"Video/NBFramesToGenerate": 3})
        self.assertEqual(m.with_user_choices(v, fg="FSRFG")["Video/NBFramesToGenerate"], 1)
        self.assertEqual(m.with_user_choices(v, fg="DLSSG", gpu_name="NVIDIA GeForce RTX 4080")["Video/NBFramesToGenerate"], 1)
        self.assertEqual(m.with_user_choices(v, fg="DLSSG", gpu_name="NVIDIA GeForce RTX 5080")["Video/NBFramesToGenerate"], 3)
    def test_2020_dlssg_mapping(self):
        c = m.UserCfg.load(S20)
        m.apply_values(c, {"Video/FrameGeneration": "DLSSG"}); self.assertEqual(c.get("Video/DLSSG"), "1")
        m.apply_values(c, {"Video/FrameGeneration": "FSRFG"}); self.assertEqual(c.get("Video/DLSSG"), "0")
        self.assertNotIn("Video/FrameGeneration", c.index)              # keys are never added
    def test_2020_preset_only_touches_existing(self):
        c = m.UserCfg.load(S20); before = set(c.index)
        m.apply_values(c, m.with_user_choices(m.PRESETS["Performance"]))
        self.assertEqual(set(c.index), before); self.assertEqual(c.get("Graphics/SSRaytracedShadows/Enabled"), "0")

class Traffic(unittest.TestCase):
    def test_off_is_minus_one(self):
        self.assertEqual(m.TRAFFIC_LEVELS["Off"], -1); self.assertEqual(m.TRAFFIC_LEVELS["Low"], 0)

class Caches(unittest.TestCase):
    def test_edition_filtering(self):
        env = {"APPDATA": "/a", "LOCALAPPDATA": "/l", "TEMP": "/t"}
        v20 = {m.cache_item_game_version(i) for i in m.resolve_cache_items(env, "2020")}
        v24 = {m.cache_item_game_version(i) for i in m.resolve_cache_items(env, "2024")}
        self.assertNotIn("2024", v20); self.assertNotIn("2020", v24); self.assertIn("2020", v20)
        self.assertTrue(all(m.cache_item_game_version(i) is None for i in m.resolve_cache_items(env, "unknown")))
    def test_2020_items_exist(self):
        ids = {i["id"] for i in m.CACHE_ITEMS}
        for x in ("rolling_steam_2020", "rolling_store_2020", "sceneryidx_steam_2020", "steam_shadercache_2020"): self.assertIn(x, ids)

if __name__ == "__main__": unittest.main(verbosity=2)
