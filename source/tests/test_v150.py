"""v1.5.0: flight situations, private diagnostic text, and profile compare stays read-only."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")

class Situations(unittest.TestCase):
    def base(self):
        return {"Graphics/ObjectsLoD/LoDFactor": 2.0, "Graphics/Buildings/Quality": 3,
                "Graphics/Traffic/AircraftTrafficQuantity": 3, "Graphics/Characters/Quantity": 3,
                "Graphics/Terrain/LoDFactor": 1.0, "Graphics/Procedural/TreesQuality": 1,
                "Graphics/VolumetricClouds/Quality": 2, "Video/SharpenAmount": 0.4,
                "Graphics/GlassCockpitsRefreshRate/Quality": 0, "Video/PrimaryScaling": 0.8,
                "Video/AntiAliasing": "TAA", "Video/FrameGeneration": "NONE"}
    def test_busy_airport_lowers_detail_and_keeps_a_traffic_choice(self):
        v, notes = m.scenario_adjust(self.base(), "Busy airport", {"vram_gb": 8})
        self.assertEqual(v["Graphics/Traffic/AircraftTrafficQuantity"], 0)
        self.assertLessEqual(v["Graphics/ObjectsLoD/LoDFactor"], 1.0)
        self.assertTrue(any("processor" in n for n in notes))
        kept, notes2 = m.scenario_adjust(self.base(), "Busy airport", {"vram_gb": 8}, locked=("traffic",))
        self.assertEqual(kept["Graphics/Traffic/AircraftTrafficQuantity"], 3)
        self.assertTrue(any("traffic choice is kept" in n for n in notes2))
    def test_vfr_respects_small_vram(self):
        v, notes = m.scenario_adjust(self.base(), "VFR scenery", {"vram_gb": 4})
        self.assertLessEqual(v["Graphics/Terrain/LoDFactor"], 1.0)
        self.assertTrue(any("Video memory is tight" in n for n in notes))
        big, _ = m.scenario_adjust(self.base(), "VFR scenery", {"vram_gb": 12})
        self.assertGreater(big["Graphics/Terrain/LoDFactor"], 1.0)
        self.assertGreaterEqual(big["Graphics/Procedural/TreesQuality"], 2)
    def test_cockpit_keeps_smooth_edges_and_simplifies_clouds(self):
        v, notes = m.scenario_adjust(self.base(), "Airliner cockpit", {"vram_gb": 8}, locked=("aa", "fg"))
        self.assertEqual(v["Video/AntiAliasing"], "TAA")
        self.assertEqual(v["Video/FrameGeneration"], "NONE")
        self.assertGreaterEqual(v["Video/SharpenAmount"], 1.2)
        self.assertEqual(v["Graphics/GlassCockpitsRefreshRate/Quality"], 2)
        self.assertEqual(v["Graphics/VolumetricClouds/Quality"], 1)
        self.assertTrue(any("instruments" in n for n in notes))
        self.assertEqual(self.base()["Graphics/VolumetricClouds/Quality"], 2)
    def test_unknown_situation(self):
        with self.assertRaises(ValueError): m.scenario_adjust(self.base(), "Race", {})

class Diagnostic(unittest.TestCase):
    def test_redacts_account_and_refuses_a_key(self):
        text = m.build_diagnostic({
            "edition": "2024", "install": r"C:\Users\Sam\AppData\Roaming\Microsoft Flight Simulator 2024\UserCfg.opt",
            "hardware": {"gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8, "errors": ["/home/sam/steam missing"]},
            "profile_names": ["Busy airports"], "goal": "Balanced", "aa": "TAA", "fg": "Off", "traffic": "SkyTune decides",
            "backup_count": 1, "known_settings": 40, "sim_running": False})
        self.assertIn("1.8.2", text)
        self.assertIn(r"C:\Users\<user>\AppData", text)
        self.assertNotIn(r"Users\Sam", text)
        self.assertIn("/home/<user>/steam", text)
        self.assertNotIn("sk-", text)
        self.assertIn("Busy airports", text)
        self.assertIn("does not upload", text)
        with self.assertRaises(ValueError):
            m.build_diagnostic({"install": "api_key=sk-notreallyakey00"})
    def test_compare_does_not_modify(self):
        cfg = m.UserCfg.load(S24)
        before = cfg.text()
        prof = m.build_profile("Clouds", {"Graphics/VolumetricClouds/Quality": 3}, edition="2024")
        plan = m.profile_apply_plan(cfg, prof)
        self.assertEqual(cfg.text(), before)
        self.assertTrue(plan["changes"])

class ExeConfirm(unittest.TestCase):
    def test_binary_confirm_backup_and_restore(self):
        exe = os.path.join(os.path.dirname(HERE), "dist", "SkyTune.exe")
        if not os.path.isfile(exe):
            self.skipTest("built exe not present")
        if not os.path.isfile("/usr/bin/wine"):
            self.skipTest("wine not present")
        import subprocess, tempfile, shutil
        helper = os.path.join(tempfile.mkdtemp(), "run_exe_flow.py")
        shutil.copy(os.path.join(HERE, "exe_flow_runner.py"), helper)
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env["SKYTUNE_EXE"] = exe
        env["SKYTUNE_FIXTURE"] = S24
        env["WINEPREFIX"] = env.get("WINEPREFIX") or "/tmp/wine-skytune"
        proc = subprocess.run([sys.executable, helper], cwd=os.path.dirname(helper), env=env,
                              timeout=110, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-1000:])
        self.assertIn("NO_SAME", proc.stdout)
        self.assertIn("YES_CHANGED", proc.stdout)
        self.assertIn("REVIEW_OK", proc.stdout)
        self.assertIn("RESTORED", proc.stdout)
        self.assertIn("ROLLBACK_KEPT", proc.stdout)
