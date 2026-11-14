import os, sys, json, shutil, subprocess, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "msfs_tweaker.py")

class Elide(unittest.TestCase):
    def test_middle_ellipsis(self):
        p = r"C:\Users\Zoë\AppData\Roaming\Microsoft Flight Simulator 2024\UserCfg.opt"
        e = m.elide_middle(p, 30, len)
        self.assertLessEqual(len(e), 30); self.assertIn("…", e)
        self.assertTrue(e.startswith("C:\\")); self.assertTrue(e.endswith("UserCfg.opt"))
        self.assertEqual(m.elide_middle("short", 30, len), "short")

@unittest.skipUnless(shutil.which("Xvfb") and os.name != "nt", "needs Xvfb (layout smoke test)")
class LayoutSmoke(unittest.TestCase):
    """Starts the real GUI on a virtual screen at small sizes / DPI and checks nothing important is clipped."""
    def run_at(self, w, h, dpi, extra=()):
        disp = None
        for n in range(90, 220):           # first free display; a lock whose process is gone is removed
            lock, sock = "/tmp/.X%d-lock" % n, "/tmp/.X11-unix/X%d" % n
            if os.path.exists(lock):
                try:
                    with open(lock) as fh: pid = int(fh.read().strip())
                except (OSError, ValueError): pid = None
                if pid and os.path.exists("/proc/%d" % pid): continue
                for p in (lock, sock):
                    try: os.remove(p)
                    except OSError: pass
            elif os.path.exists(sock):
                continue
            disp = ":%d" % n
            break
        if not disp: self.fail("no free X display")
        x = subprocess.Popen(["Xvfb", disp, "-screen", "0", "%dx%dx24" % (w, h), "-dpi", str(dpi)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import time; time.sleep(1.5)
            home = tempfile.mkdtemp(); fs = os.path.join(home, ".steam", "steam", "steamapps", "compatdata", "2537590", "pfx", "drive_c",
                                        "users", "steamuser", "AppData", "Roaming", "Microsoft Flight Simulator 2024")
            os.makedirs(fs); shutil.copy(os.path.join(os.path.dirname(__file__), "sample_UserCfg_2024.opt"), os.path.join(fs, "UserCfg.opt"))
            env = dict(os.environ, DISPLAY=disp, HOME=home); env.pop("APPDATA", None); env.pop("LOCALAPPDATA", None)
            out = subprocess.run([sys.executable, APP, "--demo-hw", "--detect-quiet", "--welcome", "--geometry", "%dx%d+0+0" % (w, h),
                                  "--layout-check", "3500"] + list(extra), env=env, capture_output=True, text=True, timeout=60)
            line = next((l for l in out.stdout.splitlines() if l.startswith("{")), None)
            self.assertIsNotNone(line, "no layout result at %dx%d @%d: %s" % (w, h, dpi, out.stderr[-800:]))
            return json.loads(line)["checks"]
        finally:
            x.kill(); x.wait()
    def test_small_screens(self):
        for w, h, dpi in ((1280, 800, 96), (1024, 600, 96), (1366, 768, 120), (1366, 768, 144)):
            checks = self.run_at(w, h, dpi)
            for k, v in checks.items(): self.assertTrue(v, "%s at %dx%d @%d dpi" % (k, w, h, dpi))
    def test_reported_sizes_no_truncated_buttons(self):
        """v1.3.1: the sizes from the bug report – every button/label fits, incl. Tools, all Advanced tabs and the AI guide."""
        for w, h, dpi in ((1920, 1080, 96), (1920, 1080, 120), (1920, 1080, 144), (1280, 800, 96), (1366, 768, 120), (3840, 2160, 96)):
            checks = self.run_at(w, h, dpi)
            for k in ("labels_fit", "tool_buttons_fit", "advanced_labels_fit", "ai_guide_fit", "step_bar"):
                self.assertIn(k, checks); self.assertTrue(checks[k], "%s at %dx%d @%d dpi" % (k, w, h, dpi))
            self.assertTrue(all(checks.values()), checks)
    def test_sim_running_banner_fits(self):
        checks = self.run_at(1280, 800, 96, ["--sim-running"])
        self.assertIn("sim_banner", checks); self.assertTrue(all(checks.values()), checks)
