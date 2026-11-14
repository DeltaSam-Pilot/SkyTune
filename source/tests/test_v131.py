"""v1.3.1: readable IN FILE values, frame-gen-only controls, multi-select problem chips with one combined answer,
the AI guide, and the polish pass (step bar, sim-running banner, change summary, cache total, short banner)."""
import os, sys, json, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_assistant as ta          # profiles / heavy file only

def product_root():
    """Docs ship beside source/ (the 1.3.2 zip layout). Fall back to source/ if a dev copy put them there."""
    source = os.path.dirname(HERE)
    parent = os.path.dirname(source)
    return parent if os.path.isfile(os.path.join(parent, "README.md")) else source

class Version(unittest.TestCase):
    def test_version_everywhere(self):
        self.assertEqual(m.VERSION, "1.8.0")
        source = os.path.dirname(HERE)
        with open(os.path.join(source, "assets", "version_info.txt"), encoding="utf-8") as f: vi = f.read()
        self.assertIn("(1,8,0,0)", vi.replace(" ", "")); self.assertIn("'1.8.0'", vi)
        self.assertNotIn("1.7.0", vi); self.assertNotIn("1.6.0", vi); self.assertNotIn("1.5.0", vi)
        for f in ("README.md", "CHANGELOG.md", "DETAILS.md"):
            with open(os.path.join(product_root(), f), encoding="utf-8") as fh: self.assertIn("1.8.0", fh.read(), f)
        with open(os.path.join(product_root(), "CHANGELOG.md"), encoding="utf-8") as fh: self.assertIn("1.3.2", fh.read())

class InFileLabels(unittest.TestCase):
    def test_traffic_levels(self):
        p = "Graphics/Traffic/AircraftTrafficQuantity"
        for raw, lab in (("-1", "Off"), ("0", "Low"), ("1", "Medium"), ("2", "High"), ("3", "Ultra")):
            self.assertEqual(m.in_file_label(p, raw), lab, raw)
    def test_quality_and_frame_generation(self):
        self.assertEqual(m.in_file_label("Graphics/VolumetricClouds/Quality", "3"), "Ultra")
        self.assertEqual(m.in_file_label("Video/FrameGeneration", "FSRFG"), "AMD FSR")
        self.assertEqual(m.in_file_label("Video/FrameGeneration", "NONE"), "Off")
        self.assertEqual(m.in_file_label("Video/FrameGeneration", "DLSSG"), "NVIDIA DLSS FG")
        self.assertEqual(m.in_file_label("Video/DLSSG", "1"), "On")
        self.assertEqual(m.in_file_label("Video/NBFramesToGenerate", "1"), "2x")
        self.assertEqual(m.in_file_label("Video/AntiAliasing", "DLSS"), "NVIDIA DLSS")
    def test_numbers_and_unknowns(self):
        self.assertEqual(m.in_file_label("Graphics/Terrain/LoDFactor", "0.750000"), "0.75")
        self.assertEqual(m.in_file_label("Video/FrameGeneration", "XESSFG"), "XESSFG")     # unknown codes stay readable
        self.assertEqual(m.in_file_label("Graphics/Traffic/AircraftTrafficQuantity", None), "–")
    def test_no_raw_codes_for_any_choice(self):
        for path, label, group, kind, spec, tip in m.SETTINGS:
            if kind != "choice" or not isinstance(spec, dict): continue
            for lab, v in spec.items():
                self.assertEqual(m.in_file_label(path, str(v), kind, spec), lab, path)

class FrameGenDependent(unittest.TestCase):
    def test_off_disables_multiplier(self):
        for fg in ("Off", "NONE"):
            s = m.fg_dependent_state(fg); self.assertFalse(s["enabled"]); self.assertEqual(s["multipliers"], [])
            self.assertIn("Frame generation is on", s["hint"])
    def test_fsr_is_2x_only(self):
        for fg in ("AMD FSR", "FSRFG"):
            s = m.fg_dependent_state(fg, "AMD Radeon RX 7800 XT"); self.assertTrue(s["enabled"]); self.assertEqual(s["multipliers"], ["2x"])
    def test_dlss_multipliers_by_card(self):
        self.assertEqual(m.fg_dependent_state("DLSSG", "NVIDIA GeForce RTX 5080")["multipliers"], ["2x", "3x", "4x"])
        self.assertEqual(m.fg_dependent_state("NVIDIA DLSS FG", "NVIDIA GeForce RTX 4070")["multipliers"], ["2x"])
    def test_not_written_when_off(self):
        tmp = tempfile.mkdtemp(); p = os.path.join(tmp, "UserCfg.opt")
        shutil.copy(os.path.join(HERE, "sample_UserCfg_2024.opt"), p)
        cfg = m.UserCfg.load(p); self.assertEqual(cfg.get("Video/FrameGeneration"), "NONE")
        self.assertEqual(cfg.get("Video/NBFramesToGenerate"), "1"); shutil.rmtree(tmp)

class MultiSelect(unittest.TestCase):
    def test_problem_text(self):
        self.assertEqual(m.selected_problem_text(["popin", "stutter"], " at EGLL "), "My sim stutters; Scenery pops in late; at EGLL")
        self.assertEqual(m.selected_problem_text([], "hello"), "hello"); self.assertEqual(m.selected_problem_text(["low_fps"]), "My FPS is too low")
    def test_combined_diagnosis_covers_all(self):
        d = m.assistant_diagnose("", ta.PROFILES["oldcpu"], ta.HEAVY, selected=["stutter", "blurry", "popin"])
        self.assertEqual(set(d["problems"]), {"stutter", "blurry", "popin"}); self.assertEqual(d["selected"], ["stutter", "blurry", "popin"])
        self.assertIn("You mentioned", d["message"]); self.assertEqual([p["id"] for p in d["per_problem"]], ["stutter", "blurry", "popin"])
        covered = set(); [covered.update(f.get("covers") or []) for f in d["fixes"]]
        self.assertTrue({"stutter", "blurry", "popin"} <= covered, covered)
        self.assertLessEqual(len(d["fixes"]), 8)
    def test_merged_list_has_no_duplicates_or_contradictions(self):
        for hw in ta.PROFILES.values():
            d = m.assistant_diagnose("", hw, ta.HEAVY, selected=[p for _, p in m.QUICK_PROBLEMS])
            ids = [f["id"] for f in d["fixes"]]; self.assertEqual(len(ids), len(set(ids)))
            keys = [k for f in d["fixes"] for k in (f.get("changes") or {})]
            self.assertEqual(len(keys), len(set(keys)), "one setting is changed by one fix only")
            titles = [f["title"] for f in d["fixes"]]; self.assertEqual(len(titles), len(set(titles)))
    def test_dedupe_conflicts(self):
        a = {"id": "a", "title": "A", "changes": {"Graphics/Terrain/LoDFactor": 1.0, "Graphics/Shadows/Size": 1024}}
        b = {"id": "b", "title": "B", "changes": {"Graphics/Terrain/LoDFactor": 2.0}}
        c = {"id": "c", "title": "C", "changes": {"Graphics/Shadows/Size": 1024, "Graphics/SSAO/Quality": 1}}
        conf = []; out = m.dedupe_fixes([a, b, c], conf)
        self.assertEqual([f["id"] for f in out], ["a", "c"]); self.assertEqual(out[1]["changes"], {"Graphics/SSAO/Quality": 1})
        self.assertIn(("B", "A"), conf)
    def test_selected_and_text_combined(self):
        d = m.assistant_diagnose("and it crashes on approach", ta.PROFILES["mid"], ta.HEAVY, selected=["low_fps"])
        self.assertIn("low_fps", d["problems"]); self.assertIn("crash", d["problems"])
    def test_ai_payload_has_all_selected(self):
        d = m.assistant_diagnose("", ta.PROFILES["mid"], ta.HEAVY, selected=["stutter", "low_fps"])
        p = m.ai_payload("at night", [], ta.PROFILES["mid"], m.ai_whitelist(ta.HEAVY, ("aa", "fg", "traffic"), set()), ta.HEAVY, d, m.DEFAULT_GOAL, "2024", selected=["stutter", "low_fps"])
        self.assertEqual(p["problem"], "My sim stutters; My FPS is too low; at night")
        self.assertEqual(p["selected_problems"], [m.PROBLEMS["stutter"][0], m.PROBLEMS["low_fps"][0]])
        p0 = m.ai_payload("x", [], ta.PROFILES["mid"], {}, {}, d, m.DEFAULT_GOAL, "2024")
        self.assertNotIn("selected_problems", p0)
        self.assertIn("several problems", m.AI_SYSTEM); self.assertIn("problems you picked", m.PRIVACY_NOTE)
    def test_nothing_persisted(self):
        self.assertFalse([k for k in m.PREF_DEFAULTS if "chip" in k or "select" in k])

class AIGuide(unittest.TestCase):
    def test_content(self):
        t = m.ai_guide_text(); low = t.lower()
        self.assertIn("offline", low); self.assertIn("without any key", low)
        self.assertIn("platform.openai.com", low); self.assertIn("api key", low)
        self.assertIn("base url", low); self.assertIn("model", low); self.assertIn("ask", low)
        self.assertIn("bill", low); self.assertNotRegex(t, r"[$€£]\s*\d")          # no invented prices
        self.assertIn("remove key", low); self.assertIn("what is sent", low); self.assertIn("this pc", low)
    def test_docs_have_guide(self):
        with open(os.path.join(product_root(), "README.md"), encoding="utf-8") as f: readme = f.read()
        self.assertIn("How to use AI", readme)
        desc = os.path.join(product_root(), "SkyTune-flightsim-description.md")
        if os.path.exists(desc):
            with open(desc, encoding="utf-8") as f: d = f.read()
            self.assertIn("How to use AI", d); self.assertIn("v1.3.1", d)
            self.assertNotRegex(d, r"https?://(?!platform\.openai\.com|console\.anthropic\.com)\S*\.(zip|exe)")

class Polish(unittest.TestCase):
    def test_change_summary(self):
        items = [("Cloud quality", "High", "Ultra"), ("AI aircraft traffic", "Medium", "Low"), ("Smooth edges", "TAA", "NVIDIA DLSS"),
                 ("Shadow sharpness", "1024", "2048"), ("Frame rate cap", "0", "60")]
        self.assertEqual(m.change_summary_line(items[:2]), "Cloud quality High → Ultra, AI aircraft traffic Medium → Low")
        self.assertTrue(m.change_summary_line(items).endswith("and 2 more")); self.assertEqual(m.change_summary_line([]), "")
    def test_cache_total(self):
        self.assertEqual(m.cache_total_text(0, 0), "Nothing ticked")
        self.assertEqual(m.cache_total_text(2, 3 * 1024 ** 3), "2 items ticked · %s to free" % m.human_size(3 * 1024 ** 3))
        self.assertEqual(m.cache_total_text(1, 5), "1 item ticked · %s to free" % m.human_size(5))
        self.assertIn("Measuring", m.cache_total_text(1, 0, measuring=True)); self.assertIn("Safe to clear", m.CACHE_SAFE_NOTE)
    def test_short_banners(self):
        self.assertEqual(m.ADV_BANNER_TEXT.count(". "), 0); self.assertLess(len(m.ADV_BANNER_TEXT), 120)
        self.assertIn("Check again", m.SIM_LOCK_TIP)

def can_display():
    if os.name == "nt": return True
    if not os.environ.get("DISPLAY"): return False
    try:
        import tkinter; r = tkinter.Tk(); r.destroy(); return True
    except Exception: return False

@unittest.skipUnless(can_display(), "needs a display")
class GUI(unittest.TestCase):
    """Drives the real window in-process (same approach as test_simple_flow)."""
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.old = dict(os.environ)
        fs = os.path.join(self.home, ".steam", "steam", "steamapps", "compatdata", "2537590", "pfx", "drive_c",
                          "users", "steamuser", "AppData", "Roaming", "Microsoft Flight Simulator 2024")
        os.makedirs(fs); self.cfg = os.path.join(fs, "UserCfg.opt")
        shutil.copy(os.path.join(HERE, "sample_UserCfg_2024.opt"), self.cfg)
        os.environ["HOME"] = self.home; os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        import tkinter.messagebox; m.messagebox = tkinter.messagebox
        self.saved = (m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning)
        self.sim = False; m.sim_running = lambda: self.sim
        self.boxes = []
        m.messagebox.showinfo = lambda *a, **k: self.boxes.append(("info", a))
        m.messagebox.showwarning = lambda *a, **k: self.boxes.append(("warn", a))
        m.messagebox.showerror = lambda *a, **k: self.boxes.append(("err", a))
        m.messagebox.askyesno = lambda *a, **k: True
    def tearDown(self):
        m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning = self.saved
        os.environ.clear(); os.environ.update(self.old); shutil.rmtree(self.home, ignore_errors=True)
    def run_gui(self, steps, argv=()):
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
        tk.Tk = mk
        old = sys.argv; sys.argv = ["msfs_tweaker.py"] + list(argv)
        try: m.run_gui(demo_hw=True)
        finally: tk.Tk = orig; sys.argv = old
        if errs: self.fail(errs[0])
    @staticmethod
    def widgets(w):
        out = [w]
        for c in w.winfo_children(): out += GUI.widgets(c)
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

    def test_chips_multi_select_and_start_over(self):
        def pick(root):
            st = root._st
            for lbl in ("Stutters", "Pop-in", "Blurry"): self.find(root, lbl).invoke()
            self.assertEqual([p for p, v in st["chip_vars"].items() if v.get()], ["stutter", "blurry", "popin"])
            self.assertTrue("selected" in st["chip_btns"]["stutter"].state())
            self.find(root, "Pop-in").invoke(); self.assertFalse(st["chip_vars"]["popin"].get())     # click again = unselect
            self.find(root, "Pop-in").invoke()
            self.assertTrue(any(l.startswith("Selected: Stutters") for l in self.labels(root)))
            self.find(root, "Ask").invoke()
        def answered(root):
            st = root._st; d = st["diag"]
            self.assertEqual(set(d["problems"]), {"stutter", "blurry", "popin"})
            labs = self.labels(root)
            self.assertTrue(any(l.startswith("You:  My sim stutters; The image looks blurry; Scenery pops in late") for l in labs), labs)
            self.assertTrue(any(l.startswith("•  Stutters:") for l in labs)); self.assertTrue(any("Helps with:" in l for l in labs))
            self.find(root, "Start over").event_generate("<Button-1>")
        def cleared(root):
            st = root._st
            self.assertFalse(any(v.get() for v in st["chip_vars"].values())); self.assertIsNone(st["diag"])
            self.assertEqual(st["chat"], []); self.assertIn("Pick one or more, then click Ask. Click again to unselect.", self.labels(root))
        self.run_gui([pick, answered, cleared])

    def test_ai_guide_opens_from_link_and_needs_no_key(self):
        def open_(root):
            self.find(root, "? How to use AI").event_generate("<Button-1>")
        def check(root):
            g = root._st.get("guide_win"); self.assertTrue(g and g.winfo_exists())
            labs = self.labels(g); self.assertIn("How to use AI (optional)", labs)
            self.assertTrue(any("without any key" in l for l in labs)); self.assertIn("Open AI settings", labs)
            self.assertFalse(m.load_prefs().get("ai_enabled"))
        self.run_gui([open_, check])

    def test_multiplier_greyed_when_frame_gen_off(self):
        def adv(root):
            self.find(root, "Advanced settings ▸").invoke()
        def off(root):
            st = root._st; labs = self.labels(root)
            self.assertIn("Only used when Frame generation is on.", labs)
            self.assertNotIn("NONE", labs); self.assertNotIn("FSRFG", labs)
            row = st["rows"]["Video/NBFramesToGenerate"][0]
            self.assertIn("disabled", row["widget"].state())
            st["vars"]["Video/FrameGeneration"][0][2].set("AMD FSR")
        def fsr(root):
            st = root._st; row = st["rows"]["Video/NBFramesToGenerate"][0]
            self.assertNotIn("disabled", row["widget"].state()); self.assertEqual(list(row["widget"].cget("values")), ["2x"])
            self.assertIn("AMD FSR frame generation is 2x only.", self.labels(root))
            st["vars"]["Video/FrameGeneration"][0][2].set("Off")
            st["vars"]["Video/NBFramesToGenerate"][0][2].set("4x")       # even if something sets it, it must not be written
            st["vars"]["Graphics/VolumetricClouds/Quality"][0][2].set("Ultra")
            self.find(root, "Apply changes").invoke()
        def written(root):
            cfg = m.UserCfg.load(self.cfg)
            self.assertEqual(cfg.get("Graphics/VolumetricClouds/Quality"), "3")
            self.assertEqual(cfg.get("Video/NBFramesToGenerate"), "1"); self.assertEqual(cfg.get("Video/FrameGeneration"), "NONE")
        self.run_gui([adv, off, fsr, written])

    def test_sim_running_banner_locks_buttons(self):
        def run(root):
            self.sim = True; root._st["show_sim"](True)
        def locked(root):
            self.assertIn("Check again", self.labels(root)); b = self.find(root, "✈  Optimise my sim")
            self.assertIn("disabled", b.state()); self.assertEqual(b._skytip.text, m.SIM_LOCK_TIP)
            self.assertIn("disabled", self.find(root, "↶  Undo").state())
            self.sim = False; self.find(root, "Check again").invoke()
        def wait(root): pass
        def unlocked(root):
            b = self.find(root, "✈  Optimise my sim"); self.assertNotIn("disabled", b.state()); self.assertNotEqual(b._skytip.text, m.SIM_LOCK_TIP)
            self.assertNotIn("Check again", [l for w in self.widgets(root) if w.winfo_ismapped() for l in [str(getattr(w, "cget")("text")) if "text" in w.keys() else ""]])
        self.run_gui([run, locked, wait, wait, unlocked])

    def test_step_bar_and_change_summary(self):
        def start(root):
            labs = self.labels(root); self.assertIn("1  Check my PC", labs); self.assertIn("3  Optimise", labs)
            self.find(root, "✈  Optimise my sim").invoke()
        def wait(root): pass
        def done(root):
            self.find(root, "Yes, write").invoke()
            labs = self.labels(root); self.assertIn("✓ Optimise", labs); self.assertIn("✓ Check my PC", labs)
            line = [l for l in labs if l.startswith("✓ Done!")]
            self.assertTrue(line and "→" in line[0] and "Click Undo" in line[0], line)
            self.assertTrue(self.find(root, "↶  Undo").winfo_ismapped())
        self.run_gui([start, wait, wait, wait, done])
