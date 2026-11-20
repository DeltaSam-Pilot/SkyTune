"""v1.3.2: look + performance pass – remembered hardware check, cheap process list, lazy modules, drawn icons,
contrast of the theme colours, background work with a spinner, lazy Clean up tab."""
import os, sys, json, time, shutil, tempfile, datetime, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_v131 import GUI as _GUI

HW = {"gpu": "NVIDIA GeForce RTX 4070", "vram_gb": 12.0, "cpu": "AMD Ryzen 7 7800X3D", "cores": 8, "threads": 16,
      "ram_gb": 32.0, "width": 2560, "height": 1440, "errors": []}

class HardwareCache(unittest.TestCase):
    def setUp(self): self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "state.json")
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)
    def test_round_trip_and_note(self):
        now = datetime.datetime(2026, 10, 23, 20, 0)
        self.assertTrue(m.save_hw_cache(dict(HW, extra="x"), self.p, now=now))
        hw, when = m.load_hw_cache(self.p, now=now + datetime.timedelta(days=3))
        self.assertEqual(hw["gpu"], HW["gpu"]); self.assertTrue(hw["cached"]); self.assertNotIn("extra", hw)
        self.assertEqual(when, now)
        self.assertEqual(m.hw_cache_note(when, now), "checked today")
        self.assertEqual(m.hw_cache_note(when, now + datetime.timedelta(days=3)), "checked 3 days ago")
    def test_keeps_other_state(self):
        m.save_state({"first_launch_done": True, "goal": "Balanced"}, self.p)
        m.save_hw_cache(HW, self.p)
        d = json.load(open(self.p)); self.assertTrue(d["first_launch_done"]); self.assertEqual(d["goal"], "Balanced")
    def test_expired_other_pc_unknown_or_broken(self):
        now = datetime.datetime(2026, 10, 23)
        m.save_hw_cache(HW, self.p, now=now)
        self.assertEqual(m.load_hw_cache(self.p, now=now + datetime.timedelta(days=31)), (None, None))
        d = json.load(open(self.p)); d["hw_cache"]["machine"] = "SOMEONE-ELSE|4"; json.dump(d, open(self.p, "w"))
        self.assertEqual(m.load_hw_cache(self.p, now=now), (None, None))
        self.assertFalse(m.save_hw_cache(dict(HW, gpu="Unknown"), os.path.join(self.d, "b.json")))
        self.assertFalse(os.path.exists(os.path.join(self.d, "b.json")))
        open(self.p, "w").write("{not json"); self.assertEqual(m.load_hw_cache(self.p), (None, None))

class Processes(unittest.TestCase):
    def test_names_running(self):
        self.assertTrue(m.names_running(["explorer.exe", "FlightSimulator2024.exe"], m.SIM_PROCESSES))
        self.assertFalse(m.names_running(["explorer.exe"], m.SIM_PROCESSES))
        self.assertIsNone(m.names_running(None, m.SIM_PROCESSES))
    def test_process_names_here_without_spawning(self):
        names = m.process_names(); self.assertIsInstance(names, list); self.assertTrue(names)
        self.assertTrue(any("python" in n for n in names), names[:20])
        self.assertIs(m.sim_running(), False)
    def test_no_tasklist_by_default(self):
        import inspect
        self.assertIn("CreateToolhelp32Snapshot", inspect.getsource(m._win_process_names))
        self.assertNotIn("tasklist", inspect.getsource(m.sim_running))

class LazyModules(unittest.TestCase):
    def test_proxies_work(self):
        self.assertEqual(m.base64.b64encode(b"sky").decode(), "c2t5")
        self.assertTrue(m.urllib.parse.quote("a b") == "a%20b")
        self.assertTrue(hasattr(m.urllib.request, "urlopen")); self.assertTrue(m.difflib.SequenceMatcher)
        self.assertTrue(callable(m.socket.create_connection))
    def test_startup_does_not_import_network_stack(self):
        import subprocess
        code = ("import sys; sys.path.insert(0, %r); import msfs_tweaker; "
                "print(','.join(n for n in ('urllib.request', 'http.client', 'ssl', 'email.message', 'difflib') if n in sys.modules))"
                % os.path.dirname(HERE))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60).stdout.strip()
        self.assertEqual(out, "")

class DrawnIcons(unittest.TestCase):
    def test_icon_pixels(self):
        for kind in ("check", "dot", "ring", "radio", "bar", "spin0", "spin7"):
            rows = m.icon_pixels(kind, 12, 16, "#38bdf8", "#141e30")
            self.assertEqual(len(rows), 16); self.assertTrue(all(len(r) == 12 for r in rows))
            flat = [c for r in rows for c in r]
            self.assertTrue(all(c.startswith("#") and len(c) == 7 for c in flat))
            self.assertIn("#141e30", flat, kind); self.assertGreater(len(set(flat)), 1, kind)
        self.assertNotEqual(m.icon_pixels("spin0", 12, 12, "#ffffff", "#000000"), m.icon_pixels("spin3", 12, 12, "#ffffff", "#000000"))
    def test_corner(self):
        rows = m.corner_pixels(6, "#0b1220", "#26354f", "#141e30")
        self.assertEqual(rows[0][0], "#0b1220"); self.assertEqual(rows[-1][-1], "#141e30"); self.assertEqual(len(rows), 6)
    def test_pick_font_falls_back(self):
        class R:
            pass
        self.assertIn(m.pick_font(None, ("No Such Font 123",)), ("TkDefaultFont", "No Such Font 123", "Segoe UI"))

def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)

class Theme(unittest.TestCase):
    def test_text_contrast_wcag_aa(self):
        T = m.THEME
        pairs = [("text", "bg"), ("text", "card"), ("text", "card2"), ("muted", "bg"), ("muted", "card"), ("muted", "header"),
                 ("accent", "card"), ("sel_text", "sel"), ("sel_text", "sel_hi"), ("danger_text", "danger_bg"),
                 ("danger_text", "danger_hover"), ("ok", "card"), ("warn", "card"), ("text", "hover"), ("muted", "card2")]
        for fg, bg in pairs: self.assertGreaterEqual(contrast(T[fg], T[bg]), 4.5, (fg, bg, round(contrast(T[fg], T[bg]), 2)))
        for bg in ("primary", "primary_hi", "primary_pr"): self.assertGreaterEqual(contrast("#ffffff", T[bg]), 4.5, bg)
    def test_dark_theme_and_blue_accent_kept(self):
        self.assertEqual(m.THEME["bg"], "#0b1220"); self.assertEqual(m.THEME["accent"], "#38bdf8")

class AppIcon(unittest.TestCase):
    """The app icon has every Windows size (crisp at 100-200% scaling) and the in-app logo is 256 px."""
    ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    def test_ico_sizes(self):
        import struct
        data = open(os.path.join(self.ASSETS, "app.ico"), "rb").read()
        _, kind, n = struct.unpack("<HHH", data[:6]); self.assertEqual(kind, 1)
        sizes = {(data[6 + 16 * i] or 256) for i in range(n)}
        for s in (16, 24, 32, 48, 256): self.assertIn(s, sizes)
    def test_png_logo(self):
        import struct
        data = open(os.path.join(self.ASSETS, "app.png"), "rb").read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (256, 256))

class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(m.VERSION, "1.8.1")
        root = os.path.dirname(os.path.dirname(HERE))
        if not os.path.isfile(os.path.join(root, "CHANGELOG.md")): root = os.path.dirname(HERE)
        with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as f:
            text = f.read(); self.assertIn("1.4.0", text); self.assertIn("1.3.2", text)

class GUI(_GUI):
    def run_real(self, steps, argv=(), detect=None):
        """Like run_gui but without demo hardware, with detect_hardware stubbed (counts calls)."""
        import tkinter as tk
        self.calls = 0
        def fake():
            self.calls += 1; time.sleep(0.3); return dict(HW)
        saved = m.detect_hardware; m.detect_hardware = detect or fake
        orig = tk.Tk; errs = []
        def mk(*a, **k):
            root = orig(*a, **k)
            def go(i=0):
                if i >= len(steps): root.destroy(); return
                try: steps[i](root)
                except Exception:
                    import traceback; errs.append(traceback.format_exc()); root.destroy(); return
                root.after(700, lambda: go(i + 1))
            root.after(1500, go); return root
        tk.Tk = mk; old = sys.argv; sys.argv = ["msfs_tweaker.py", "--nav", "Optimise"] + list(argv)
        try: m.run_gui(demo_hw=False)
        finally: tk.Tk = orig; sys.argv = old; m.detect_hardware = saved
        if errs: self.fail(errs[0])
    def test_check_is_threaded_then_remembered(self):
        seen = {}
        def click(root):
            t = time.time(); self.find(root, "Check my PC").invoke(); seen["click_s"] = time.time() - t
            self.assertLess(seen["click_s"], 0.2)                              # the window never waits for the check
            self.assertTrue(root._st["busy"]["n"] >= 1)
        def done(root):
            self.assertEqual(root._st["busy"]["n"], 0); self.assertEqual(root._st["hw"]["gpu"], HW["gpu"])
            self.assertEqual(self.calls, 1)
            hw, when = m.load_hw_cache(); self.assertEqual(hw["gpu"], HW["gpu"])
        self.run_real([click, done])
        def again(root):
            self.assertTrue(any("Last check (checked today)" in l for l in self.labels(root)), self.labels(root))
            self.find(root, "Check my PC").invoke()
            self.assertEqual(self.calls, 0); self.assertTrue(root._st["hw"].get("cached"))
            self.assertTrue(any("checked today" in l and "Your PC suits" in l for l in self.labels(root)))
            self.find(root, "Re-check").event_generate("<Button-1>")
        def fresh(root):
            self.assertEqual(self.calls, 1); self.assertFalse(root._st["hw"].get("cached"))
        self.run_real([again, fresh])
    def test_clean_up_tab_built_on_first_visit(self):
        def adv(root):
            self.assertFalse(root._st["cleaner_built"])
            self.find(root, "Advanced settings ▸").invoke()
        def tab(root):
            self.assertFalse(root._st["cleaner_built"])
            nb = [w for w in self.widgets(root) if w.winfo_class() == "TNotebook"][0]; nb.select(2)
        def built(root): self.assertTrue(root._st["cleaner_built"])
        self.run_gui([adv, tab, built])
    def test_failed_check_keeps_window_usable(self):
        def boom(): raise OSError("WMI is broken")
        def click(root): self.find(root, "Check my PC").invoke()
        def after(root):
            self.assertEqual(root._st["busy"]["n"], 0)
            self.assertTrue(any("Couldn't check this PC" in l for l in self.labels(root)))
            self.assertIn("!disabled", self.find(root, "Check my PC").state() or ["!disabled"])
        self.run_real([click, after], detect=boom)

if __name__ == "__main__":
    unittest.main()
