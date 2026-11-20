"""v1.7.0: EasyjetSimPilot's MSFS 2024 SU7 settings as built-in presets. Only verified UserCfg keys."""
import os, sys, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")
S20 = os.path.join(HERE, "sample_UserCfg_2020.opt")

EXPECTED = {
    "Video/AntiAliasing": "TAA",
    "Video/PrimaryScaling": 1.0,
    "Video/SharpenAmount": 1.0,
    "Video/FrameLimiter": 0,
    "Video/FrameGeneration": "FSRFG",
    "Video/NBFramesToGenerate": 1,
    "Graphics/Terrain/LoDFactor": 1.25,
    "Graphics/OffscreenTerrainPreCaching/Quality": 2,
    "Graphics/DisplacementMapping/Enabled": 1,
    "Graphics/Buildings/Quality": 2,
    "Graphics/Procedural/TreesQuality": 2,
    "Graphics/Procedural/PlantsQuality": 1,
    "Graphics/Procedural/RocksQuality": 1,
    "Graphics/Procedural/GrassQuality": 1,
    "Graphics/ObjectsLoD/LoDFactor": 1.0,
    "Graphics/VolumetricClouds/Quality": 3,
    "Graphics/Texture/Quality": 1,
    "Graphics/Texture/MaxAnisotropy": 16,
    "Graphics/Water/FFTSize": 128,
    "Graphics/RaytracedShadows/Enabled": 0,
    "Graphics/Shadows/Size": 1024,
    "Graphics/HeightFieldShadows/Size": 256,
    "Graphics/ContactShadows/Quality": 1,
    "Graphics/WindShield/Quality": 2,
    "Graphics/SSAO/Quality": 1,
    "Graphics/ReflectionProbe/Size": 192,
    "Graphics/SSR/Quality": 1,
    "Graphics/VolumetricLights/Quality": 1,
    "Graphics/GlassCockpitsRefreshRate/Quality": 1,
    "Graphics/Characters/Quantity": 0,
    "Graphics/Traffic/AirportsServicesQuantity": 0,
    "Graphics/Traffic/ParkedAircraftQuantity": -1,
    "Graphics/Traffic/AircraftTrafficQuantity": -1,
    "Graphics/Traffic/RoadQuality": 1,
    "Graphics/Traffic/SeaQuality": 1,
    "Graphics/Fauna/Quantity": 2,
}

class CreatorPreset(unittest.TestCase):
    def test_mapped_values_match_the_video_table(self):
        values = m.easyjet_values()
        self.assertEqual(values, EXPECTED)
        known = {row[0] for row in m.SETTINGS}
        self.assertTrue(set(values) <= known)
        for path in ("Video/FullScreenResolution", "Video/Resolution", "Video/Windowed", "Video/HDR10",
                     "Video/ExposureBias", "Video/VSync", "Video/Reflex", "Video/DynamicSettings",
                     "Graphics/DOF/Quality", "Graphics/MotionBlur/Enabled", "Graphics/Particles/Quality",
                     "Graphics/Seatbelts/Enabled"):
            self.assertNotIn(path, values)
        self.assertIn("https://youtu.be/Mq63dyne32g", m.EASYJET_URL)
        self.assertIn("has not endorsed", m.EASYJET_NOTE)
        self.assertNotIn("fps", m.EASYJET_NOTE.lower())
    def test_eight_gb_variant_changes_only_three_settings(self):
        main, small = m.easyjet_values(), m.easyjet_8gb_values()
        changed = {p: small[p] for p in small if small[p] != main.get(p)}
        self.assertEqual(changed, {
            "Graphics/Terrain/LoDFactor": 1.0,
            "Graphics/OffscreenTerrainPreCaching/Quality": 1,
            "Graphics/VolumetricClouds/Quality": 2,
        })
        self.assertEqual(small["Graphics/Texture/Quality"], 1)
        labels = [row[0] for row in m.creator_differences()]
        self.assertEqual(len(labels), 3)
        self.assertTrue(any("Terrain" in label or "terrain" in label for label in labels))
    def test_hidden_for_msfs_2020_and_compare_does_not_write(self):
        self.assertEqual(m.creator_presets("2020"), {})
        self.assertEqual(m.creator_presets("unknown"), {})
        self.assertEqual(set(m.creator_presets("2024")), {m.EASYJET_NAME, m.EASYJET_8GB_NAME})
        cfg = m.UserCfg.load(S24)
        before = cfg.text()
        prof = m.build_profile("Mine", {"Graphics/VolumetricClouds/Quality": 1, "Video/AntiAliasing": "DLSS"}, edition="2024")
        rows = m.creator_vs_profile(m.EASYJET_NAME, prof)
        self.assertTrue(any(r[0] and r[2] for r in rows))
        self.assertEqual(cfg.text(), before)
        self.assertEqual(m.detect_simulator_version(S20), "2020")
        self.assertEqual(m.creator_presets(m.detect_simulator_version(S24)), m.creator_presets("2024"))

def can_display():
    if os.name == "nt": return True
    if not os.environ.get("DISPLAY"): return False
    try:
        import tkinter
        r = tkinter.Tk(); r.destroy(); return True
    except Exception:
        return False

@unittest.skipUnless(can_display(), "needs a display")
class CreatorGUI(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.old = dict(os.environ)
        fs = os.path.join(self.home, ".steam", "steam", "steamapps", "compatdata", "2537590", "pfx", "drive_c",
                          "users", "steamuser", "AppData", "Roaming", "Microsoft Flight Simulator 2024")
        os.makedirs(fs); self.cfg = os.path.join(fs, "UserCfg.opt"); shutil.copy(S24, self.cfg)
        os.environ["HOME"] = self.home; os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        import tkinter.messagebox
        m.messagebox = tkinter.messagebox
        self.saved = (m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning)
        m.sim_running = lambda: False
        m.messagebox.showinfo = lambda *a, **k: None
        m.messagebox.showwarning = lambda *a, **k: None
        m.messagebox.showerror = lambda *a, **k: None
        m.messagebox.askyesno = lambda *a, **k: True
    def tearDown(self):
        m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning = self.saved
        os.environ.clear(); os.environ.update(self.old); shutil.rmtree(self.home, ignore_errors=True)
    def run_gui(self, steps):
        import tkinter as tk
        orig = tk.Tk; errs = []
        def mk(*a, **k):
            root = orig(*a, **k)
            def go(i=0):
                if i >= len(steps): root.destroy(); return
                try: steps[i](root)
                except Exception:
                    import traceback; errs.append(traceback.format_exc()); root.destroy(); return
                root.after(400, lambda: go(i + 1))
            root.after(1500, go); return root
        tk.Tk = mk; argv = sys.argv; sys.argv = ["msfs_tweaker.py", "--nav", "Optimise"]
        try: m.run_gui(demo_hw=True)
        finally: tk.Tk = orig; sys.argv = argv
        if errs: self.fail(errs[0])
    @staticmethod
    def widgets(w):
        out = [w]
        for c in w.winfo_children(): out += CreatorGUI.widgets(c)
        return out
    def find(self, root, text):
        for w in self.widgets(root):
            try:
                if str(w.cget("text")).strip() == text and w.winfo_ismapped(): return w
            except Exception: pass
        raise AssertionError("no visible widget %r" % text)
    def test_selecting_the_preset_prepares_the_list_and_still_asks(self):
        original = open(self.cfg, "rb").read()
        def choose(root):
            root._st["hw"] = dict(m.DEMO_HW)
            box = next(w for w in self.widgets(root) if w.winfo_class() == "TCombobox" and m.EASYJET_NAME in w.cget("values"))
            box.set(m.EASYJET_8GB_NAME); box.event_generate("<<ComboboxSelected>>"); root.update()
            summary = next(w for w in self.widgets(root) if w.winfo_class() == "Text")
            text = summary.get("1.0", "end")
            self.assertIn(m.EASYJET_8GB_NAME, text)
            self.assertIn("youtu.be/Mq63dyne32g", text)
            self.assertIn("has not endorsed", text)
            self.assertIn("Differences from the main preset", text)
            self.assertEqual(open(self.cfg, "rb").read(), original)
        def write(root):
            self.find(root, "✈  Optimise my sim").invoke()
            self.find(root, "Yes, write").invoke()
            cfg = m.UserCfg.load(self.cfg)
            self.assertEqual(cfg.get("Graphics/Terrain/LoDFactor"), "1.000000")
            self.assertEqual(cfg.get("Graphics/VolumetricClouds/Quality"), "2")
            self.assertEqual(cfg.get("Graphics/Texture/Quality"), "1")
            self.assertEqual(cfg.get("Video/FrameGeneration"), "FSRFG")
            self.assertEqual(cfg.get("Video/FullScreenResolution"), "2560 1440")
            note = open(os.path.join(os.path.dirname(self.cfg), "UserCfg_backups",
                        [f for f in os.listdir(os.path.join(os.path.dirname(self.cfg), "UserCfg_backups")) if f.endswith(".review.json")][0]),
                        encoding="utf-8").read()
            self.assertIn(m.EASYJET_8GB_NAME, note)
            self.assertNotIn(self.home, note)
        self.run_gui([choose, write])
