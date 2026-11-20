"""v1.6.0: since-last-write drift. The sim can change UserCfg after SkyTune writes. SkyTune shows that and can leave those settings out of the next write."""
import os, sys, json, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")

def can_display():
    if os.name == "nt": return True
    if not os.environ.get("DISPLAY"): return False
    try:
        import tkinter
        r = tkinter.Tk(); r.destroy(); return True
    except Exception:
        return False

class Drift(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.old = dict(os.environ)
        os.environ["HOME"] = self.d; os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        self.cfg = os.path.join(self.d, "UserCfg.opt"); shutil.copy(S24, self.cfg)
    def tearDown(self):
        os.environ.clear(); os.environ.update(self.old); shutil.rmtree(self.d, ignore_errors=True)
    def test_snapshot_has_no_path_or_key_and_drift_is_read_only(self):
        cfg = m.UserCfg.load(self.cfg)
        before = cfg.text()
        snap = m.file_snapshot(cfg)
        self.assertIn("Graphics/VolumetricClouds/Quality", snap)
        self.assertNotIn("Video/FullScreenResolution", snap)
        blob = json.dumps(snap)
        self.assertNotIn("\\", blob); self.assertNotIn("sk-", blob); self.assertNotIn(self.d, blob)
        self.assertTrue(m.save_last_apply(cfg, "2024"))
        stored = json.dumps(m.load_state())
        self.assertNotIn(self.d, stored); self.assertNotIn("api_key", stored)
        changed = dict(m.load_last_apply()["values"])
        changed["Graphics/VolumetricClouds/Quality"] = "3"
        m.save_state({"last_apply": {"edition": "2024", "values": changed}})
        info = m.describe_drift(m.load_last_apply(), cfg, "2024")
        self.assertEqual(info["kind"], "diff")
        self.assertEqual(info["rows"][0]["path"], "Graphics/VolumetricClouds/Quality")
        self.assertEqual(cfg.text(), before)
        other = m.describe_drift(m.load_last_apply(), cfg, "2020")
        self.assertEqual(other["kind"], "other"); self.assertEqual(other["rows"], [])
    def test_a_bad_snapshot_is_ignored(self):
        self.assertIsNone(m.clean_last_apply({"edition": "2024", "values": {"Graphics/VolumetricClouds/Quality": "sk-secretkey00"}}))
        self.assertIsNone(m.clean_last_apply({"edition": "2024", "values": {"Not/A/Setting": "1"}}))
        self.assertIsNone(m.clean_last_apply({"edition": "xbox", "values": {"Graphics/VolumetricClouds/Quality": "1"}}))
        self.assertEqual(m.describe_drift(None, m.UserCfg.load(self.cfg), "2024")["kind"], "none")
    def test_keeping_a_setting_removes_it_from_the_pending_list(self):
        cfg = m.UserCfg.load(self.cfg)
        cfg.set("Graphics/VolumetricClouds/Quality", "1"); cfg.save(self.cfg)
        cfg = m.UserCfg.load(self.cfg)
        values = {"Graphics/VolumetricClouds/Quality": 2, "Video/AntiAliasing": "TAA"}
        held = dict(values); held.pop("Graphics/VolumetricClouds/Quality")
        self.assertEqual([row[0] for row in m.summarize_changes(cfg, held)], ["Smooth edges"])
        self.assertIn("Cloud quality", [row[0] for row in m.summarize_changes(cfg, values)])
        self.assertEqual(cfg.get("Graphics/VolumetricClouds/Quality"), "1")

@unittest.skipUnless(can_display(), "needs a display")
class DriftGUI(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.old = dict(os.environ)
        fs = os.path.join(self.home, ".steam", "steam", "steamapps", "compatdata", "2537590", "pfx", "drive_c",
                          "users", "steamuser", "AppData", "Roaming", "Microsoft Flight Simulator 2024")
        os.makedirs(fs); self.cfg = os.path.join(fs, "UserCfg.opt"); shutil.copy(S24, self.cfg)
        os.environ["HOME"] = self.home; os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        cfg = m.UserCfg.load(self.cfg)
        cfg.set("Graphics/VolumetricClouds/Quality", "1"); cfg.save(self.cfg)
        snap = m.file_snapshot(m.UserCfg.load(self.cfg))
        snap["Graphics/VolumetricClouds/Quality"] = "3"
        m.save_state({"last_apply": {"edition": "2024", "values": snap}})
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
        for c in w.winfo_children(): out += DriftGUI.widgets(c)
        return out
    def find(self, root, text):
        for w in self.widgets(root):
            try:
                if str(w.cget("text")).strip() == text and w.winfo_ismapped(): return w
            except Exception: pass
        raise AssertionError("no visible widget %r" % text)
    def test_keep_leaves_the_sims_value_and_still_asks(self):
        def see(root):
            self.assertEqual(root._st["drift"][0]["path"], "Graphics/VolumetricClouds/Quality")
            summary = next(w for w in self.widgets(root) if w.winfo_class() == "Text")
            text = summary.get("1.0", "end")
            self.assertIn("Since SkyTune last wrote", text); self.assertIn("Cloud quality", text)
            self.find(root, "Keep the sim's values").event_generate("<Button-1>"); root.update()
            self.assertIn("Graphics/VolumetricClouds/Quality", root._st["held"])
            root._st["hw"] = dict(m.DEMO_HW)
            self.assertEqual(m.UserCfg.load(self.cfg).get("Graphics/VolumetricClouds/Quality"), "1")
        def write(root):
            self.find(root, "✈  Optimise my sim").invoke()
            self.find(root, "Yes, write").invoke()
            cfg = m.UserCfg.load(self.cfg)
            self.assertEqual(cfg.get("Graphics/VolumetricClouds/Quality"), "1")
            self.assertNotEqual(cfg.get("Video/AntiAliasing"), "DLSS")
            stored = json.dumps(m.load_state())
            self.assertNotIn(self.home, stored); self.assertNotIn("sk-", stored)
            self.assertEqual(m.load_last_apply()["values"]["Graphics/VolumetricClouds/Quality"], "1")
            self.assertEqual(m.describe_drift(m.load_last_apply(), cfg, "2024")["kind"], "match")
        self.run_gui([see, write])
