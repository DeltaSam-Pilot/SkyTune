"""Drives the real v1.3.0 simple view in-process: ask -> Use top fix -> Optimise -> Worse (auto-undo),
the one-line result, and preferences remembered between runs."""
import os, sys, json, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

def can_display():
    if os.name == "nt": return True
    if not os.environ.get("DISPLAY"): return False
    try:
        import tkinter; r = tkinter.Tk(); r.destroy(); return True
    except Exception: return False

@unittest.skipUnless(can_display(), "needs a display")
class SimpleFlow(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.old = dict(os.environ)
        fs = os.path.join(self.home, ".steam", "steam", "steamapps", "compatdata", "2537590", "pfx", "drive_c",
                          "users", "steamuser", "AppData", "Roaming", "Microsoft Flight Simulator 2024")
        os.makedirs(fs); self.cfg = os.path.join(fs, "UserCfg.opt")
        shutil.copy(os.path.join(HERE, "sample_UserCfg_2024.opt"), self.cfg)
        os.environ["HOME"] = self.home; os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        import msfs_tweaker as m; self.m = m
        import tkinter.messagebox; m.messagebox = tkinter.messagebox
        self.saved = (m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning)
        m.sim_running = lambda: False
        self.boxes = []
        m.messagebox.showinfo = lambda *a, **k: self.boxes.append(("info", a))
        m.messagebox.showwarning = lambda *a, **k: self.boxes.append(("warn", a))
        m.messagebox.showerror = lambda *a, **k: self.boxes.append(("err", a))
        m.messagebox.askyesno = lambda *a, **k: True
    def tearDown(self):
        m = self.m
        m.sim_running, m.messagebox.showinfo, m.messagebox.askyesno, m.messagebox.showerror, m.messagebox.showwarning = self.saved
        os.environ.clear(); os.environ.update(self.old); shutil.rmtree(self.home, ignore_errors=True)

    def run_gui(self, steps):
        """Run the GUI; steps is a list of callables(root) run 400 ms apart, then the window closes."""
        m = self.m; import tkinter as tk
        orig = tk.Tk; errs = []
        def mk(*a, **k):
            root = orig(*a, **k)
            def go(i=0):
                if i >= len(steps): root.destroy(); return
                try: steps[i](root)
                except Exception as e:
                    import traceback; errs.append(traceback.format_exc()); root.destroy(); return
                root.after(400, lambda: go(i + 1))
            root.after(1500, go); return root
        tk.Tk = mk
        argv = sys.argv; sys.argv = ["msfs_tweaker.py", "--nav", "Optimise"]
        try: m.run_gui(demo_hw=True)
        finally: tk.Tk = orig; sys.argv = argv
        if errs: self.fail(errs[0])

    @staticmethod
    def widgets(w):
        out = [w]
        for c in w.winfo_children(): out += SimpleFlow.widgets(c)
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

    def test_fix_optimise_worse_undo(self):
        orig = open(self.cfg, "rb").read(); seen = {}
        def ask(root):
            e = next(w for w in self.widgets(root) if w.winfo_class() == "TEntry")
            e.delete(0, "end"); e.insert(0, "stutters at busy airprots"); self.find(root, "Ask").invoke()
        def top(root):
            self.assertTrue(any(l.startswith("Likely cause:") for l in self.labels(root)))
            self.find(root, "Use top fix").invoke()
        def optimise(root):
            self.find(root, "✈  Optimise my sim").invoke()
            self.find(root, "Yes, write").invoke()
        def check_applied(root):
            seen["after"] = open(self.cfg, "rb").read()
            self.assertNotEqual(seen["after"], orig)
            done = [l for l in self.labels(root) if l.startswith("✓ Done!")]      # v1.3.1: plain summary of what changed
            self.assertTrue(done and "→" in done[0] and done[0].endswith("Not happy? Click Undo."), done)
            self.assertFalse([b for b in self.boxes if b[0] == "info"], "simple view must not pop up a message box")
            self.find(root, "✗ Worse").invoke()
        def check_undone(root):
            self.assertEqual(open(self.cfg, "rb").read(), orig, "Worse must restore the settings from before the fix")
            self.assertTrue(any(l.startswith("Undone.") for l in self.labels(root)))
        self.run_gui([ask, top, optimise, check_applied, check_undone])

    def test_prefs_remembered(self):
        def change(root):
            self.find(root, "▸  My preferences").event_generate("<Button-1>"); root.update()
            cbs = [w for w in self.widgets(root) if w.winfo_class() == "TCombobox" and w.winfo_ismapped()]
            tr = next(c for c in cbs if c.get() == "SkyTune decides"); tr.set("Off"); tr.event_generate("<<ComboboxSelected>>")
            self.find(root, "Smooth & steady").invoke()
        self.run_gui([change])
        st = json.load(open(os.path.join(self.home, "SkyTune", "state.json")))["prefs"]
        self.assertEqual((st["traffic"], st["goal"], st["prefs_open"]), ("Off", "Smooth & steady", True))
        def check(root):
            cbs = [w.get() for w in self.widgets(root) if w.winfo_class() == "TCombobox" and w.winfo_ismapped()]
            self.assertIn("Off", cbs)
            self.assertTrue(any("Traffic: Off" in l for l in self.labels(root)))
            self.find(root, "▾  My preferences")
        self.run_gui([check])

if __name__ == "__main__":
    unittest.main()
