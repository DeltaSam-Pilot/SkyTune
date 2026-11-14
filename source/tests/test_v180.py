"""v1.8.0: writes that survive odd files, and suggestions that explain themselves."""
import os, stat, glob, shutil, tempfile, unittest
sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, sys_path)
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))
S24 = os.path.join(HERE, "sample_UserCfg_2024.opt")

def tiny(nl="\r\n"):
    return "{Graphics%s Version 2.1.0%s Preset High%s}%s{Video%s AntiAliasing DLSS%s}%s" % (nl, nl, nl, nl, nl, nl, nl)

def _mode_bits_stick(path):
    mode = os.stat(path).st_mode
    os.chmod(path, stat.S_IREAD)
    stuck = not os.access(path, os.W_OK)
    os.chmod(path, mode)
    return stuck

class Writes(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.p = os.path.join(self.d, "UserCfg.opt"); shutil.copy(S24, self.p)
    def tearDown(self):
        os.chmod(self.d, 0o755); os.chmod(self.p, 0o644)
        shutil.rmtree(self.d, ignore_errors=True)
    def test_read_only_file_is_left_unchanged(self):
        if not _mode_bits_stick(self.p):
            self.skipTest("this system does not honour a read-only file mode")
        orig = open(self.p, "rb").read(); os.chmod(self.p, stat.S_IREAD)
        cfg = m.UserCfg.load(self.p); cfg.set("Video/AntiAliasing", "TAA")
        with self.assertRaises(OSError) as cm:
            m.write_with_backup(cfg, self.p)
        self.assertIn("read-only", str(cm.exception))
        self.assertEqual(open(self.p, "rb").read(), orig)
    def test_missing_file_creates_nothing(self):
        missing = os.path.join(self.d, "missing", "UserCfg.opt")
        cfg = m.UserCfg(tiny())
        with self.assertRaises(OSError) as cm:
            m.write_with_backup(cfg, missing)
        self.assertIn("isn't there", str(cm.exception))
        self.assertFalse(os.path.exists(missing))
    def test_locked_file_is_reported_in_plain_english(self):
        real = os.open
        def locked(path, flags, *a, **k):
            if os.path.abspath(path) == os.path.abspath(self.p) and flags == os.O_RDWR:
                raise PermissionError("busy")
            return real(path, flags, *a, **k)
        os.open = locked
        try:
            self.assertIn("another program", m.write_blocked(self.p))
        finally:
            os.open = real
    def test_read_only_folder_blocks_the_write(self):
        if os.name == "nt":
            self.skipTest("folder mode bits are not enforced on Windows")
        os.chmod(self.d, 0o555)
        self.assertIn("read-only", m.write_blocked(self.p))
    def test_replace_failure_keeps_the_original(self):
        orig = open(self.p, "rb").read()
        cfg = m.UserCfg.load(self.p); cfg.set("Video/AntiAliasing", "TAA")
        real = os.replace
        def boom(src, dst):
            raise OSError("disk")
        os.replace = boom
        try:
            with self.assertRaises(OSError):
                cfg.save(self.p)
        finally:
            os.replace = real
        self.assertEqual(open(self.p, "rb").read(), orig)
        self.assertFalse(glob.glob(os.path.join(self.d, ".skytune-*")))
    def test_utf16_and_bom_round_trip(self):
        for enc, prefix, decode in (
            ("utf-16-le", b"\xff\xfe", "utf-16-le"),
            ("utf-8-sig", b"\xef\xbb\xbf", "utf-8"),
        ):
            body = tiny().encode(decode)
            open(self.p, "wb").write(prefix + body)
            cfg = m.UserCfg.load(self.p)
            self.assertEqual(cfg.get("Video/AntiAliasing"), "DLSS")
            cfg.save(self.p)
            self.assertEqual(open(self.p, "rb").read(), prefix + body)
            cfg.set("Video/AntiAliasing", "TAA"); cfg.save(self.p)
            again = m.UserCfg.load(self.p)
            self.assertEqual(again.encoding, enc)
            self.assertEqual(again.get("Video/AntiAliasing"), "TAA")
    def test_cr_only_and_mixed_endings(self):
        open(self.p, "wb").write(tiny("\r").encode("utf-8"))
        cfg = m.UserCfg.load(self.p)
        self.assertEqual(cfg.newline, "\r")
        self.assertEqual(cfg.get("Graphics/Preset"), "High")
        cfg.save(self.p)
        self.assertIn(b"\r", open(self.p, "rb").read()); self.assertNotIn(b"\n", open(self.p, "rb").read())
        mixed = "{Graphics\r\n Version 2.1.0\n Preset High\r\n}\r\n{Video\r\n AntiAliasing DLSS\r\n}\r\n"
        cfg = m.UserCfg(mixed)
        self.assertEqual(cfg.get("Video/AntiAliasing"), "DLSS")
        self.assertEqual(cfg.get("Graphics/Preset"), "High")
    def test_restore_refuses_a_read_only_file(self):
        if not _mode_bits_stick(self.p):
            self.skipTest("this system does not honour a read-only file mode")
        cfg = m.UserCfg.load(self.p); cfg.set("Video/AntiAliasing", "TAA"); m.write_with_backup(cfg, self.p)
        backup = m.list_backups(self.p)[-1]
        current = open(self.p, "rb").read()
        os.chmod(self.p, stat.S_IREAD)
        result = m.apply_restore(self.p, backup)
        self.assertFalse(result["ok"]); self.assertIn("read-only", result["error"])
        self.assertEqual(open(self.p, "rb").read(), current)
    def test_restore_recreates_a_missing_file(self):
        cfg = m.UserCfg.load(self.p); cfg.set("Video/AntiAliasing", "TAA"); m.write_with_backup(cfg, self.p)
        backup = m.list_backups(self.p)[-1]
        os.remove(self.p)
        result = m.apply_restore(self.p, backup)
        self.assertTrue(result["ok"], result)
        self.assertTrue(os.path.isfile(self.p))
        self.assertEqual(m.UserCfg.load(self.p).get("Video/AntiAliasing"), "DLSS")

class Places(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = os.environ.copy()
    def tearDown(self):
        os.environ.clear(); os.environ.update(self.env)
        shutil.rmtree(self.d, ignore_errors=True)
    def plant(self, *parts):
        folder = os.path.join(self.d, *parts); os.makedirs(folder)
        shutil.copy(S24, os.path.join(folder, "UserCfg.opt"))
        return folder
    def test_steam_and_store_for_both_sims(self):
        self.plant("Roaming", "Microsoft Flight Simulator 2024")
        self.plant("Local", "Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache")
        self.plant("Roaming", "Microsoft Flight Simulator")
        self.plant("Local", "Packages", "Microsoft.FlightSimulator_8wekyb3d8bbwe", "LocalCache")
        os.environ["APPDATA"] = os.path.join(self.d, "Roaming")
        os.environ["LOCALAPPDATA"] = os.path.join(self.d, "Local")
        os.environ["HOME"] = self.d
        labels = [label for label, _path in m.detect_usercfgs()]
        self.assertEqual(labels[0], "MSFS 2024 · Steam")
        self.assertIn("MSFS 2024 · MS Store / Xbox", labels)
        self.assertIn("MSFS 2020 · Steam", labels)
        self.assertIn("MSFS 2020 · MS Store / Xbox", labels)
    def test_remembered_custom_path(self):
        os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = os.environ["HOME"] = self.d
        custom = os.path.join(self.d, "Games", "MSFS", "UserCfg.opt")
        os.makedirs(os.path.dirname(custom)); shutil.copy(S24, custom)
        self.assertTrue(m.remember_cfg(custom))
        found = m.detect_usercfgs()
        self.assertEqual(found[-1][0], "Saved location")
        self.assertEqual(os.path.abspath(found[-1][1]), os.path.abspath(custom))
    def test_custom_steam_library(self):
        os.environ["HOME"] = self.d
        os.environ.pop("APPDATA", None); os.environ.pop("LOCALAPPDATA", None)
        steam = os.path.join(self.d, ".steam", "steam", "steamapps")
        os.makedirs(steam)
        library = os.path.join(self.d, "Library")
        user = os.path.join(library, "steamapps", "compatdata", "1250410", "pfx", "drive_c", "users", "steamuser",
                            "AppData", "Roaming", "Microsoft Flight Simulator")
        os.makedirs(user, exist_ok=True); shutil.copy(S24, os.path.join(user, "UserCfg.opt"))
        open(os.path.join(steam, "libraryfolders.vdf"), "w").write('"path" "%s"\n' % library)
        labels = [label for label, _path in m.detect_usercfgs(self.d)]
        self.assertIn("MSFS 2020 Steam (Proton)", labels)

class Reasons(unittest.TestCase):
    def test_each_reason_names_the_hardware_it_used(self):
        hw = {"gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8, "cores": 8, "refresh_hz": 240}
        self.assertIn("8", m.setting_reason("Graphics/Texture/Quality", hw))
        self.assertIn("video memory", m.setting_reason("Graphics/Texture/Quality", hw).lower())
        self.assertIn("240", m.setting_reason("Video/FrameLimiter", hw))
        self.assertIn("6", m.setting_reason("Graphics/Terrain/LoDFactor", {"gpu": "NVIDIA GeForce RTX 3060", "vram_gb": 12, "cores": 6}))
        low = m.setting_reason("Graphics/VolumetricClouds/Quality", {"gpu": "Intel Iris Xe Graphics", "vram_gb": 2, "cores": 4})
        self.assertIn("tier", low.lower())
    def test_reasons_do_not_write(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "UserCfg.opt"); shutil.copy(S24, p)
        before = open(p, "rb").read()
        cfg = m.UserCfg.load(p)
        m.plan({"gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8, "cores": 8, "ram_gb": 32, "width": 1920, "height": 1080})
        m.change_reasons(cfg, {"Graphics/Texture/Quality": 1}, {"vram_gb": 8, "gpu": "NVIDIA GeForce RTX 3070 Ti"})
        self.assertEqual(open(p, "rb").read(), before)
        shutil.rmtree(d)
    def test_help_is_plain_and_has_the_disclaimer(self):
        text = "\n".join(body for _title, body in m.HELP_PAGES)
        self.assertIn("1. Close the simulator.", text)
        self.assertIn("2. Click Check my PC", text)
        self.assertIn("3. Read the list", text)
        self.assertIn("official Flightsim.to page", text)
        self.assertIn("frame rates are not guaranteed", text)
        self.assertNotIn("Traceback", text)
        self.assertIn("read-only", m.plain_error(OSError("That settings file is read-only.")))
        self.assertNotIn("Traceback", m.plain_error(RuntimeError("Traceback (most recent call last):\nboom")))
