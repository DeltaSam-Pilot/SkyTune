"""v1.4.0: saved graphics profiles, before/after review notes, and restore that checks the file came back."""
import os, sys, json, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")
S20 = os.path.join(HERE, "sample_UserCfg_2020.opt")

def can_display():
    if os.name == "nt": return True
    if not os.environ.get("DISPLAY"): return False
    try:
        import tkinter; r = tkinter.Tk(); r.destroy(); return True
    except Exception: return False

class Profiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.cfg = os.path.join(self.d, "UserCfg.opt"); shutil.copy(S24, self.cfg)
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)
    def test_save_round_trip_drops_resolution_and_secrets(self):
        cfg = m.UserCfg.load(self.cfg)
        values, _skipped = {}, []
        snap, rejected = m.clean_profile_values({p: cfg.get(p) for p in cfg.index})
        self.assertIn("Graphics/VolumetricClouds/Quality", snap)
        self.assertNotIn("Video/FullScreenResolution", snap)
        self.assertTrue(any("resolution" in e for _p, e in rejected))
        prof = m.build_profile("Busy airports", dict(snap, **{"Video/FullScreenResolution": "1920 1080",
                                                              "C:\\Users\\Sam\\secret.txt": 1, "api_key": "sk-shouldnotsave000"}),
                                note="api_key=sk-shouldnotsave000", goal="Smooth & steady", edition="2024", source="pending")
        self.assertEqual(prof["note"], "")
        self.assertNotIn("api_key", prof["values"])
        self.assertNotIn("C:\\Users\\Sam\\secret.txt", json.dumps(prof))
        saved = m.save_profile(prof, self.d)
        on_disk = json.load(open(os.path.join(self.d, saved["id"] + ".json"), encoding="utf-8"))
        self.assertNotIn("path", on_disk); self.assertNotIn(self.d, json.dumps(on_disk))
        again = m.list_profiles(self.d)
        self.assertEqual(again[0]["name"], "Busy airports"); self.assertEqual(again[0]["goal"], "Smooth & steady")
        self.assertEqual(m.load_profile(self.d, again[0]["id"])["values"]["Graphics/VolumetricClouds/Quality"], snap["Graphics/VolumetricClouds/Quality"])
    def test_rejects_bad_documents_and_path_tricks(self):
        with self.assertRaises(ValueError): m.build_profile("  ", {"Graphics/VolumetricClouds/Quality": 1})
        with self.assertRaises(ValueError): m.build_profile("../etc/passwd", {"Graphics/VolumetricClouds/Quality": 1})
        with self.assertRaises(ValueError): m.build_profile("Only resolution", {"Video/FullScreenResolution": "1920 1080"})
        self.assertIsNone(m.validate_profile_document({"format": "other", "format_version": 1})[0])
        prof, errs = m.validate_profile_document({"hello": "world"})
        self.assertIsNone(prof); self.assertTrue(errs)
        self.assertFalse(m.delete_profile(self.d, "../outside"))
        self.assertIsNone(m.load_profile(self.d, "../outside"))
        junk = os.path.join(self.d, "not-json.json"); open(junk, "w").write("{")
        prof, errs = m.read_profile_file(junk); self.assertIsNone(prof); self.assertIn("JSON", errs[0])
        huge = os.path.join(self.d, "huge.json"); open(huge, "wb").write(b"{" + b"a" * (m.MAX_PROFILE_BYTES + 10))
        self.assertIn("too large", m.read_profile_file(huge)[1][0])
    def test_range_uses_the_wider_limit_and_import_export(self):
        self.assertEqual(m.coerce_setting("Graphics/Terrain/LoDFactor", 5.0)[0], 5.0)     # beyond the in-game slider, inside Advanced
        self.assertIsNone(m.coerce_setting("Graphics/Terrain/LoDFactor", 9)[0])
        self.assertEqual(m.coerce_setting("Graphics/VolumetricClouds/Quality", "Ultra")[0], 3)
        self.assertEqual(m.coerce_setting("Graphics/VolumetricClouds/Quality", "3")[0], 3)
        self.assertIsNone(m.coerce_setting("Graphics/VolumetricClouds/Quality", True)[0])
        prof = m.build_profile("Night flight", {"Graphics/VolumetricClouds/Quality": "Low", "Graphics/Terrain/LoDFactor": "1.5"},
                                edition="2024")
        dest = os.path.join(self.d, "out", "night.json"); m.export_profile(prof, dest)
        raw = open(dest, encoding="utf-8").read()
        self.assertNotIn("\"id\"", raw); self.assertNotIn(self.d, raw)
        loaded, errs = m.read_profile_file(dest); self.assertEqual(errs, []); self.assertEqual(loaded["name"], "Night flight")
        m.save_profile(loaded, self.d)
        with self.assertRaises(ValueError): m.save_profile(loaded, self.d, replace=False)
        replaced = m.save_profile(loaded, self.d, replace=True)
        self.assertEqual(len(m.list_profiles(self.d)), 1); self.assertEqual(replaced["id"], m.profile_slug("Night flight"))
        open(os.path.join(self.d, "broken.json"), "w").write("{not json")
        self.assertEqual(len(m.list_profiles(self.d)), 1)
    def test_apply_plan_does_not_touch_the_file_or_add_keys(self):
        cfg = m.UserCfg.load(self.cfg); before = cfg.text()
        prof = m.build_profile("Clouds", {"Graphics/VolumetricClouds/Quality": 3, "Graphics/Procedural/TreesQuality": 0,
                                           "Not/A/Key": 1}, edition="2020")
        plan = m.profile_apply_plan(cfg, prof)
        self.assertEqual(cfg.text(), before)
        self.assertTrue(any(lab == "Cloud quality" and new == "Ultra" for lab, _o, new in plan["changes"]))
        self.assertNotIn("Not/A/Key", plan["values"])
        # a 2024-only key that is present is applied; resolution never is
        self.assertIn("Graphics/VolumetricClouds/Quality", plan["values"])
    def test_profile_cap(self):
        for i in range(m.MAX_PROFILES):
            m.save_profile(m.build_profile("Setup %d" % i, {"Graphics/VolumetricClouds/Quality": 1}), self.d)
        with self.assertRaises(ValueError):
            m.save_profile(m.build_profile("One more", {"Graphics/VolumetricClouds/Quality": 1}), self.d)
        self.assertTrue(m.delete_profile(self.d, m.profile_slug("Setup 0")))
        m.save_profile(m.build_profile("One more", {"Graphics/VolumetricClouds/Quality": 2}), self.d)
        self.assertEqual(len(m.list_profiles(self.d)), m.MAX_PROFILES)

class ReviewAndRestore(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "Microsoft Flight Simulator 2024", "UserCfg.opt")
        os.makedirs(os.path.dirname(self.p)); shutil.copy(S24, self.p)
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)
    def test_review_records_before_after_without_paths_or_secrets(self):
        before = m.UserCfg.load(self.p); original = open(self.p, "rb").read()
        cfg = m.UserCfg.load(self.p); m.apply_values(cfg, {"Graphics/VolumetricClouds/Quality": 3})
        rows = m.diff_known_settings(before, cfg)
        b = m.write_with_backup(cfg, self.p, review={"reason": "profile", "changes": rows, "edition": "2024",
                                                     "profile": "Busy airports", "warnings": []})
        self.assertEqual(open(b, "rb").read(), original)
        review = m.read_change_review(b); text = json.dumps(review)
        self.assertEqual(review["format"], "skytune-review"); self.assertTrue(review["verified"]); self.assertEqual(len(review["sha256"]), 64)
        self.assertIn("Cloud quality", text); self.assertIn("Ultra", text)
        self.assertNotIn(self.d, text); self.assertNotIn("api_key", text)
        self.assertIn("Busy airports", m.backup_label(b, review))
        secret = m.write_change_review(b, "profile", rows, profile="Busy airports", warnings=["api_key=sk-notreallyakey00"])
        secret_text = json.dumps(secret)
        self.assertNotIn("sk-", secret_text); self.assertNotIn("api_key", secret_text)
        self.assertEqual(secret["changes"], []); self.assertIn("sensitive", " ".join(secret["warnings"]))
        plain = m.confirm_summary(m.diff_tuples(rows), intro="Write profile \"Busy airports\" to the simulator settings?")
        self.assertIn("→", plain); self.assertIn("Nothing is written until you choose Yes", plain)
    def test_restore_checks_and_rolls_back(self):
        original = open(self.p, "rb").read()
        cfg = m.UserCfg.load(self.p); m.apply_values(cfg, {"Graphics/VolumetricClouds/Quality": 3})
        backup = m.write_with_backup(cfg, self.p)          # backup is the original, file is now Ultra
        modified = open(self.p, "rb").read()
        self.assertNotEqual(modified, original)
        bad = os.path.join(self.d, "notes.txt"); open(bad, "w").write("not a settings file")
        refused = m.plan_restore(self.p, bad); self.assertFalse(refused["ok"]); self.assertIn("can't be used", refused["error"])
        self.assertFalse(m.plan_restore(self.p, self.p)["ok"])
        plan = m.plan_restore(self.p, backup)
        self.assertTrue(plan["ok"]); self.assertTrue(any(old == "Ultra" and new == "Medium" for _l, old, new in plan["changes"]))
        real = m._files_match_parsed
        m._files_match_parsed = lambda *a, **k: False
        try: failed = m.apply_restore(self.p, backup, reason="restore")
        finally: m._files_match_parsed = real
        self.assertFalse(failed["ok"]); self.assertFalse(failed["verified"])
        self.assertEqual(open(self.p, "rb").read(), modified)       # previous file put back
        done = m.apply_restore(self.p, backup, reason="restore")
        self.assertTrue(done["ok"]); self.assertTrue(done["verified"])
        self.assertEqual(open(self.p, "rb").read(), original)
        vr = m.UserCfg.load(self.p).get("GraphicsVR/Terrain/LoDFactor")
        self.assertEqual(vr, m.UserCfg(original.decode("utf-8")).get("GraphicsVR/Terrain/LoDFactor"))
    def test_edition_mismatch_and_tampered_backup_are_warnings(self):
        p20 = os.path.join(self.d, "Microsoft Flight Simulator", "UserCfg.opt")
        os.makedirs(os.path.dirname(p20)); shutil.copy(S20, p20)
        plan = m.plan_restore(self.p, p20)
        self.assertTrue(plan["ok"])
        self.assertTrue(any("MSFS 2020" in w and "MSFS 2024" in w for w in plan["warnings"]))
        cfg = m.UserCfg.load(self.p); m.apply_values(cfg, {"Graphics/Shadows/Size": 1024})
        backup = m.write_with_backup(cfg, self.p, review={"reason": "optimise", "changes": [("Shadow sharpness", "2048", "1024")], "edition": "2024"})
        edited = m.UserCfg.load(backup); edited.set("Graphics/Shadows/Size", "2048"); edited.save(backup)
        warned = m.plan_restore(self.p, backup)
        self.assertTrue(any("changed since" in w for w in warned["warnings"]))
    def test_old_backup_without_a_note_still_plans(self):
        cfg = m.UserCfg.load(self.p); m.apply_values(cfg, {"Graphics/Texture/Quality": 2})
        backup = m.write_with_backup(cfg, self.p)          # no review sidecar
        self.assertIsNone(m.read_change_review(backup))
        plan = m.plan_restore(self.p, backup)
        self.assertTrue(plan["ok"]); self.assertIsNone(plan["saved_review"]); self.assertTrue(plan["changes"])

@unittest.skipUnless(can_display(), "needs a display")
class ProfilesGUI(unittest.TestCase):
    """Drives the real window: save a profile, refuse the write, then confirm it, then read the backup note."""
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.old = dict(os.environ)
        fs = os.path.join(self.home, ".steam", "steam", "steamapps", "compatdata", "2537590", "pfx", "drive_c",
                          "users", "steamuser", "AppData", "Roaming", "Microsoft Flight Simulator 2024")
        os.makedirs(fs); self.cfg = os.path.join(fs, "UserCfg.opt"); shutil.copy(S24, self.cfg)
        os.environ["HOME"] = self.home; os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        import tkinter.messagebox; m.messagebox = tkinter.messagebox
        self.saved = (m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning)
        m.sim_running = lambda: False
        self.asks, self.yes = [], True
        m.messagebox.showinfo = lambda *a, **k: None
        m.messagebox.showwarning = lambda *a, **k: None
        m.messagebox.showerror = lambda *a, **k: None
        m.messagebox.askyesno = lambda *a, **k: self.asks.append(a) or self.yes
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
                root.after(450, lambda: go(i + 1))
            root.after(1600, go); return root
        tk.Tk = mk; argv = sys.argv; sys.argv = ["msfs_tweaker.py", "--nav", "Optimise"]
        try: m.run_gui(demo_hw=True)
        finally: tk.Tk = orig; sys.argv = argv
        if errs: self.fail(errs[0])
    @staticmethod
    def widgets(w):
        out = [w]
        for c in w.winfo_children(): out += ProfilesGUI.widgets(c)
        return out
    def find(self, root, text):
        for w in self.widgets(root):
            try:
                if str(w.cget("text")).strip() == text and w.winfo_ismapped(): return w
            except Exception: pass
        raise AssertionError("no visible widget %r" % text)
    def labels(self, root):
        out = []
        for w in self.widgets(root):
            try: out.append(str(w.cget("textvariable") and w.getvar(w.cget("textvariable")) or w.cget("text")))
            except Exception: pass
        return out
    def test_profile_confirm_and_backup_review(self):
        original = open(self.cfg, "rb").read(); seen = {}
        def save(root):
            self.find(root, "Saved profiles…").event_generate("<Button-1>")
            root.update_idletasks(); root.update()
            d = root._st["profiles_win"]; self.assertTrue(d.winfo_exists())
            root._st["vars"]["Graphics/VolumetricClouds/Quality"][0][2].set("Ultra")
            entries = [w for w in self.widgets(d) if w.winfo_class() == "TEntry"]
            entries[0].delete(0, "end"); entries[0].insert(0, "Busy airports")
            entries[1].delete(0, "end"); entries[1].insert(0, "Clouds down a step for a heavy airport")
            self.find(d, "Save").invoke()
            seen["dialog"] = d
        def saved(root):
            files = os.listdir(os.path.join(self.home, "SkyTune", "profiles"))
            self.assertTrue(any(f.endswith(".json") for f in files), files)
            self.assertEqual(open(self.cfg, "rb").read(), original)
            blob = open(os.path.join(self.home, "SkyTune", "profiles", files[0]), encoding="utf-8").read()
            self.assertNotIn(self.home, blob); self.assertNotIn("api_key", blob)
            self.find(seen["dialog"], "Use").invoke()
        def ready(root):
            self.assertFalse(root._st["profiles_win"].winfo_exists())
            self.assertEqual(open(self.cfg, "rb").read(), original)
            self.assertTrue(any("Busy airports" in l and "ready" in l for l in self.labels(root)), self.labels(root))
            summary = next(w for w in self.widgets(root) if w.winfo_class() == "Text")
            text = summary.get("1.0", "end"); self.assertIn("Busy airports", text); self.assertIn("→", text)
            self.find(root, "✈  Optimise my sim").invoke()
        def refused(root):
            self.assertEqual(open(self.cfg, "rb").read(), original)
            self.assertTrue(any("Yes, write" in l or l.startswith("Confirm ") for l in self.labels(root)), self.labels(root))
            self.find(root, "Cancel").invoke()
            self.assertTrue(any(l.startswith("Cancelled") for l in self.labels(root)))
            self.find(root, "✈  Optimise my sim").invoke()
        def written(root):
            self.find(root, "Yes, write").invoke()
            self.assertNotEqual(open(self.cfg, "rb").read(), original)
            self.assertEqual(m.UserCfg.load(self.cfg).get("Graphics/VolumetricClouds/Quality"), "3")
            self.assertEqual(m.UserCfg.load(self.cfg).get("GraphicsVR/Terrain/LoDFactor"), "0.500000")
            reviews = [f for f in os.listdir(os.path.join(os.path.dirname(self.cfg), "UserCfg_backups")) if f.endswith(".review.json")]
            self.assertEqual(len(reviews), 1)
            note = open(os.path.join(os.path.dirname(self.cfg), "UserCfg_backups", reviews[0]), encoding="utf-8").read()
            self.assertNotIn(self.home, note); self.assertIn("Busy airports", note); self.assertIn("Cloud quality", note)
            self.assertTrue(any(l.startswith("✓ Done!") for l in self.labels(root)))
            self.find(root, "Review backups…").event_generate("<Button-1>")
        def reviewed(root):
            d = root._st["backups_win"]; self.assertTrue(d.winfo_exists())
            box = next(w for w in self.widgets(d) if w.winfo_class() == "Text")
            text = box.get("1.0", "end")
            self.assertIn("→", text); self.assertIn("Busy airports", text)
            self.find(d, "Close").invoke()
        self.run_gui([save, saved, ready, refused, written, reviewed])

if __name__ == "__main__":
    unittest.main()
