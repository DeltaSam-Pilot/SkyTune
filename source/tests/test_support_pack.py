"""Support pack, read-only graphics-mod notes, and saved DLSS / frame-generation wording."""
import os, re, sys, json, shutil, tempfile, zipfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")

def _touch(folder, name, body=b"leave-me\n"):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(body)
    return path

def _snapshot(root):
    found = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                found[os.path.relpath(path, root)] = f.read()
    return found

class SupportPack(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "UserCfg.opt")
        shutil.copy(S24, self.p)
        self.state = os.path.join(self.d, "state.json")
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
    def test_file_list_is_only_skytune_notes_and_the_settings_file(self):
        folder = os.path.join(self.d, "UserCfg_backups")
        os.makedirs(folder)
        with open(os.path.join(folder, "UserCfg_19990101-000000-000000.opt"), "w", encoding="utf-8") as f:
            f.write('MARKER_OLD "C:\\Users\\Sam\\old"\n')
        with open(os.path.join(folder, "api_key.txt"), "w", encoding="utf-8") as f:
            f.write("sk-secretvalue00\n")
        with open(os.path.join(folder, "SkyTune_log.txt"), "w", encoding="utf-8") as f:
            f.write("log C:\\Users\\Sam\\AppData\\Roaming\\note pilot@example.com sk-notreallyakey00\n")
        cfg = m.UserCfg.load(self.p)
        cfg.set("Video/AntiAliasing", "TAA")
        m.write_with_backup(cfg, self.p, review={"reason": "optimise", "changes": [("Smooth edges", "NVIDIA DLSS", "TAA")], "edition": "2024"})
        m.save_last_apply(m.UserCfg.load(self.p), "2024", self.state)
        hw = {"gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8, "cpu": "AMD Ryzen 7 5800X", "cores": 8,
              "ram_gb": 32, "width": 1920, "height": 1080, "errors": [r"C:\Users\Sam\AppData\missing"]}
        when = __import__("datetime").datetime(2026, 11, 20, 9, 0, 0)
        entries = m.build_support_pack(self.p, "2024", hw, state_path=self.state, now=when)
        names = m.support_pack_names(entries)
        self.assertEqual(names, ["README.txt", "hardware.txt", "SkyTune_log.txt", "last-apply.json",
                                 "before-review.json", "before-UserCfg.opt", "UserCfg.opt"])
        self.assertNotIn("api_key.txt", names)
        blob = "\n".join(item["text"] for item in entries)
        self.assertNotIn("MARKER_OLD", blob)
        self.assertNotIn("sk-secretvalue00", blob)
        self.assertIn("version: %s" % m.VERSION, entries[0]["text"])
        self.assertIn("sim: MSFS 2024", entries[0]["text"])
        self.assertIn("date: 2026-11-20", entries[0]["text"])
    def test_username_email_and_token_are_masked(self):
        folder = os.path.join(self.d, "UserCfg_backups")
        os.makedirs(folder)
        with open(os.path.join(folder, "SkyTune_log.txt"), "w", encoding="utf-8") as f:
            f.write("C:\\Users\\Sam\\AppData and /home/sam/steam and pilot@example.com bearer sk-notreallyakey00\n")
        entries = m.build_support_pack(self.p, "2024", {"gpu": "Example", "errors": ["/Users/Sam/Library"]}, state_path=self.state)
        blob = "\n".join(item["text"] for item in entries)
        self.assertIn("<user>", blob)
        self.assertIn("<email>", blob)
        self.assertIn("<token>", blob)
        self.assertNotIn("Users\\Sam", blob)
        self.assertNotIn("Users/Sam", blob)
        self.assertNotIn("/home/sam", blob)
        self.assertNotIn("pilot@", blob)
        self.assertNotRegex(blob, r"sk-[A-Za-z0-9]{8,}")
    def test_zip_contains_the_reviewed_names_only(self):
        entries = m.build_support_pack(self.p, "unknown", {"gpu": "Example"}, state_path=self.state,
                                       now=__import__("datetime").datetime(2026, 11, 20))
        dest = os.path.join(self.d, "SkyTune-support.zip")
        written = m.write_support_pack(dest, entries)
        self.assertEqual(written, m.support_pack_names(entries))
        with zipfile.ZipFile(dest) as zf:
            self.assertEqual(zf.namelist(), written)
            readme = zf.read("README.txt").decode("utf-8")
            cfg = zf.read("UserCfg.opt").decode("utf-8")
        self.assertIn("sim: MSFS (not detected)", readme)
        self.assertIn("date: 2026-11-20", readme)
        self.assertIn(r"C:\Users\<user>\AppData", cfg)
        self.assertNotIn("Sam", cfg)
    def test_reading_the_list_creates_nothing(self):
        before = set(os.listdir(self.d))
        m.build_support_pack(self.p, "2024", {}, state_path=os.path.join(self.d, "missing-state.json"))
        self.assertEqual(set(os.listdir(self.d)), before)
    def test_start_dir_prefers_desktop(self):
        home = os.path.join(self.d, "home")
        os.makedirs(home)
        env = {"HOME": home, "USERPROFILE": home}
        self.assertEqual(m.support_pack_start_dir(env), home)
        os.makedirs(os.path.join(home, "Documents"))
        self.assertEqual(m.support_pack_start_dir(env), os.path.join(home, "Documents"))
        os.makedirs(os.path.join(home, "Desktop"))
        self.assertEqual(m.support_pack_start_dir(env), os.path.join(home, "Desktop"))

class GraphicsMods(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
    def test_known_files_warn_and_nothing_is_changed(self):
        game = os.path.join(self.d, "MSFS 2024")
        _touch(game, "FlightSimulator2024.exe")
        _touch(game, "OptiScaler.ini", b"Dxgi=false\nsecret-token\n")
        _touch(game, "ReShade.ini", b"[GENERAL]\n")
        _touch(game, "glass-cockpit-dlss-fix.addon64")
        _touch(os.path.join(game, "nested"), "OptiScaler.ini", b"hidden\n")
        before = _snapshot(self.d)
        found = m.find_graphics_mods(edition="2024", program_dirs=[game], community=None, env={})
        self.assertEqual(_snapshot(self.d), before)
        ids = [item["id"] for item in found]
        self.assertEqual(ids, ["reshade", "optiscaler", "glass"])
        warnings = " ".join(m.graphics_mod_warnings(found))
        self.assertIn("OptiScaler", warnings)
        self.assertIn("DLSS", warnings)
        self.assertIn("saved in your settings", warnings)
        self.assertNotIn("secret-token", warnings)
        self.assertNotIn(game, warnings)
    def test_glass_fix_is_msfs_2024_only(self):
        game = os.path.join(self.d, "MSFS 2020")
        _touch(game, "FlightSimulator.exe")
        _touch(game, "glass-cockpit-dlss-fix.addon64")
        _touch(game, "OptiScaler.ini")
        found = m.find_graphics_mods(edition="2020", program_dirs=[game], community=None, env={})
        self.assertEqual([item["id"] for item in found], ["optiscaler"])
        self.assertIn("DLSS", found[0]["warning"])
    def test_atmosphere_from_community_or_its_own_folder(self):
        comm = os.path.join(self.d, "Community", "AtmosphereMod")
        os.makedirs(comm)
        found = m.find_graphics_mods(edition="2024", program_dirs=[], community=os.path.dirname(comm), env={})
        self.assertEqual([item["id"] for item in found], ["atmosphere"])
        self.assertIn("cloud", found[0]["warning"].lower())
        local = os.path.join(self.d, "Local")
        tun = os.path.join(local, "AtmosphereMod", "tunables.ini")
        os.makedirs(os.path.dirname(tun))
        with open(tun, "w", encoding="utf-8") as f:
            f.write("haze=1\n")
        with open(tun, "rb") as handle:
            before = handle.read()
        found = m.find_graphics_mods(edition="2024", program_dirs=[], community=None, env={"LOCALAPPDATA": local})
        with open(tun, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual([item["id"] for item in found], ["atmosphere"])
        self.assertEqual(found[0]["file"], "tunables.ini")
    def test_empty_folder_is_silent(self):
        game = os.path.join(self.d, "plain")
        _touch(game, "FlightSimulator2024.exe")
        self.assertEqual(m.find_graphics_mods(edition="2024", program_dirs=[game], community=None, env={}), [])

class SavedUpscalerWording(unittest.TestCase):
    def test_dlss_and_frame_generation_are_saved_not_active(self):
        both = m.UserCfg("{Graphics\n Version 2.1.0\n}\n{Video\n AntiAliasing DLSS\n FrameGeneration DLSSG\n}\n")
        note = m.upscaler_saved_note(both)
        self.assertIn("DLSS and frame generation are saved in your settings", note)
        self.assertNotIn("active", note.lower())
        off = m.UserCfg("{Graphics\n Version 2.1.0\n}\n{Video\n AntiAliasing TAA\n FrameGeneration NONE\n}\n")
        self.assertEqual(m.upscaler_saved_note(off), "")
        self.assertEqual(m.saved_setting_suffix("Video/FrameGeneration", "NONE"), "")
        self.assertEqual(m.saved_setting_suffix("Video/AntiAliasing", "DLSS"), "saved in your settings")
        self.assertEqual(m.saved_setting_suffix("Graphics/VolumetricClouds/Quality", "3"), "")
        legacy = m.UserCfg("{Graphics\n Version 2.1.0\n}\n{Video\n DLSSG 1\n}\n")
        self.assertIn("frame generation is saved in your settings", m.upscaler_saved_note(legacy))
        self.assertEqual(m.in_file_label("Video/AntiAliasing", "DLSS"), "NVIDIA DLSS")
        self.assertEqual(m.in_file_label("Video/FrameGeneration", "DLSSG"), "NVIDIA DLSS FG")
    def test_preference_line_and_frame_generation_card(self):
        plain = m.prefs_summary("TAA", "Off", "SkyTune decides")
        self.assertEqual(plain, "Smooth edges: TAA  ·  Extra frames: Off  ·  Traffic: SkyTune decides")
        self.assertNotIn("active", plain.lower())
        marked = m.prefs_summary("NVIDIA DLSS", "NVIDIA DLSS FG", "Low")
        self.assertIn("saved in your settings", marked)
        self.assertNotIn("active", marked.lower())
        self.assertIn("saved in your settings", m.FRAME_GEN_NOTE)
        self.assertNotIn("active", m.FRAME_GEN_NOTE.lower())
        self.assertNotIn("active", m.OPTISCALER_WARNING.lower())
        self.assertNotIn("active", m.GLASS_DLSS_WARNING.lower())

def _can_display():
    if os.name == "nt":
        return True
    if not os.environ.get("DISPLAY"):
        return False
    try:
        import tkinter
        root = tkinter.Tk(); root.destroy(); return True
    except Exception:
        return False

@unittest.skipUnless(_can_display(), "needs a display")
class SupportPackButton(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.old = dict(os.environ)
        roaming = os.path.join(self.home, "Roaming")
        fs = os.path.join(roaming, "Microsoft Flight Simulator 2024")
        os.makedirs(fs)
        shutil.copy(S24, os.path.join(fs, "UserCfg.opt"))
        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home
        os.environ["APPDATA"] = roaming
        os.environ["LOCALAPPDATA"] = os.path.join(self.home, "Local")
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.home, ".config")
        import tkinter.messagebox
        m.messagebox = tkinter.messagebox
        self.saved = (m.messagebox.askyesno, m.messagebox.showinfo, m.messagebox.showerror)
        self.seen = {}
        def ask(*args, **_k):
            self.seen["ask"] = args
            return False
        m.messagebox.askyesno = ask
        m.messagebox.showinfo = lambda *a, **k: None
        m.messagebox.showerror = lambda *a, **k: None
    def tearDown(self):
        m.messagebox.askyesno, m.messagebox.showinfo, m.messagebox.showerror = self.saved
        os.environ.clear(); os.environ.update(self.old)
        shutil.rmtree(self.home, ignore_errors=True)
    def test_button_lists_files_before_saving(self):
        import tkinter as tk
        errs = []
        orig = tk.Tk
        def mk(*a, **k):
            root = orig(*a, **k)
            def click():
                try:
                    button = next(w for w in self._widgets(root)
                                  if w.winfo_class() == "TButton" and str(w.cget("text")) == "Support pack")
                    button.invoke()
                except Exception:
                    import traceback; errs.append(traceback.format_exc()); root.destroy(); return
                root.destroy()
            root.after(1600, click)
            return root
        tk.Tk = mk
        old = sys.argv; sys.argv = ["msfs_tweaker.py"]
        try:
            m.run_gui(demo_hw=True)
        finally:
            tk.Tk = orig; sys.argv = old
        if errs:
            self.fail(errs[0])
        text = self.seen["ask"][1]
        self.assertIn("README.txt", text)
        self.assertIn("hardware.txt", text)
        self.assertIn("UserCfg.opt", text)
        self.assertNotIn("Sam", text)
        self.assertFalse(any(name.endswith(".zip") for name in os.listdir(self.home)))
    @staticmethod
    def _widgets(w):
        out = [w]
        for child in w.winfo_children():
            out += SupportPackButton._widgets(child)
        return out

class FreeEdition(unittest.TestCase):
    def test_free_build_does_not_name_a_paid_edition(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        product = os.path.dirname(root)
        bad = []
        for base in (root, product):
            for name in ("msfs_tweaker.py", "README.md", "DETAILS.md", "CHANGELOG.md"):
                path = os.path.join(base, name)
                if not os.path.isfile(path):
                    path = os.path.join(root, name)
                if not os.path.isfile(path):
                    continue
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                if re.search(r"(?i)(?<![A-Za-z])pro(?![A-Za-z])", text):
                    bad.append(path)
        self.assertEqual(bad, [])
