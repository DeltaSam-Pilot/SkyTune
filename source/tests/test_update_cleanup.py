import os, sys, shutil, tempfile, unittest, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
S24 = os.path.join(os.path.dirname(__file__), "sample_UserCfg_2024.opt")

class UpdateCleanup(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = {"APPDATA": os.path.join(self.d, "Roaming"), "LOCALAPPDATA": os.path.join(self.d, "Local")}
        self.sim = os.path.join(self.env["APPDATA"], "Microsoft Flight Simulator 2024"); os.makedirs(self.sim)
        self.pkg = os.path.join(self.d, "D", "MSFS Packages")                     # "other drive" packages path
        self.comm = os.path.join(self.pkg, "Community"); os.makedirs(os.path.join(self.comm, "addon-a"))
        open(os.path.join(self.comm, "addon-a", "layout.json"), "w").write("{}")
        os.makedirs(os.path.join(self.pkg, "Official2024", "x"))
        t = open(S24, newline="").read().replace(r'C:\Users\Sam\AppData\Roaming\Microsoft Flight Simulator 2024\Packages', self.pkg)
        self.cfg = os.path.join(self.sim, "UserCfg.opt"); open(self.cfg, "w", newline="").write(t)
        self.nv = os.path.join(self.env["LOCALAPPDATA"], "NVIDIA", "DXCache"); os.makedirs(self.nv)
        open(os.path.join(self.nv, "s"), "wb").write(b"x" * 400)
        self.rc = os.path.join(self.sim, "ROLLINGCACHE.CCC"); open(self.rc, "wb").write(b"x" * 10)
    def tearDown(self):
        for root, dirs, files in os.walk(self.d):
            for x in dirs: os.chmod(os.path.join(root, x), 0o755)
        shutil.rmtree(self.d)
    def plan(self, reset=True): return m.plan_update_cleanup(self.cfg, reset, env=self.env)

    def test_detects_community_from_installed_packages_path(self):
        p = self.plan(); self.assertTrue(p["ok"], p.get("errors"))
        self.assertEqual(p["community"], self.comm); self.assertEqual(p["rename_to"], os.path.join(self.pkg, "Community-old"))
        self.assertEqual([c["id"] for c in p["caches"]], ["nv_dx"])
    def test_old_name_collision_uses_timestamp(self):
        os.makedirs(os.path.join(self.pkg, "Community-old"))
        now = datetime.datetime(2026, 10, 21, 20, 5)
        self.assertEqual(m.old_community_name(self.pkg, now), os.path.join(self.pkg, "Community-old-20261021-2005"))
        os.makedirs(os.path.join(self.pkg, "Community-old-20261021-2005"))
        self.assertEqual(m.old_community_name(self.pkg, now), os.path.join(self.pkg, "Community-old-20261021-2005-2"))
    def test_run_full(self):
        before = open(self.cfg).read()
        r = m.run_update_cleanup(self.cfg, self.plan()); self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.isdir(self.comm)); self.assertEqual(os.listdir(self.comm), [])
        self.assertTrue(os.path.exists(os.path.join(self.pkg, "Community-old", "addon-a", "layout.json")))
        self.assertTrue(os.path.isdir(os.path.join(self.pkg, "Official2024", "x")))          # official untouched
        self.assertEqual(os.listdir(self.nv), []); self.assertTrue(os.path.exists(self.rc))    # rolling cache kept
        self.assertEqual(open(r["backup"]).read(), before)
        c = m.UserCfg.load(self.cfg); self.assertEqual(c.get("Graphics/Terrain/LoDFactor"), "1.000000")
        self.assertEqual(c.get("InstalledPackagesPath").strip('"'), self.pkg)
        log = open(r["log"]).read(); self.assertIn("Renamed", log); self.assertIn("finished", log)
    def test_default_is_keep_settings_with_backup(self):
        before = open(self.cfg).read(); p = m.plan_update_cleanup(self.cfg, env=self.env)
        self.assertFalse(p["reset_graphics"]); r = m.run_update_cleanup(self.cfg, p)
        self.assertEqual(open(self.cfg).read(), before); self.assertEqual(open(r["backup"]).read(), before)
    def test_keep_settings(self):
        before = open(self.cfg).read(); r = m.run_update_cleanup(self.cfg, self.plan(reset=False))
        self.assertTrue(r["ok"]); self.assertEqual(open(self.cfg).read(), before)
    def test_undo_simple(self):
        before = open(self.cfg).read(); m.run_update_cleanup(self.cfg, self.plan())
        r = m.undo_update_cleanup(self.cfg); self.assertTrue(r["ok"], r)
        self.assertTrue(os.path.exists(os.path.join(self.comm, "addon-a", "layout.json")))
        self.assertFalse(os.path.exists(os.path.join(self.pkg, "Community-old")))
        self.assertEqual(open(self.cfg).read(), before); self.assertIsNone(m.undo_state(self.cfg))
    def test_undo_with_new_contents_asks_then_merges(self):
        m.run_update_cleanup(self.cfg, self.plan())
        os.makedirs(os.path.join(self.comm, "addon-new")); os.makedirs(os.path.join(self.comm, "addon-a"))   # one clash
        r = m.undo_update_cleanup(self.cfg, merge_new=False); self.assertFalse(r["ok"]); self.assertTrue(r["needs_merge"])
        self.assertTrue(os.path.isdir(os.path.join(self.pkg, "Community-old")))           # nothing changed yet
        r = m.undo_update_cleanup(self.cfg, merge_new=True); self.assertTrue(r["ok"], r)
        self.assertEqual(r["moved"], ["addon-new"]); self.assertEqual(r["conflicts"], ["addon-a"])
        self.assertTrue(os.path.exists(os.path.join(self.comm, "addon-a", "layout.json")))    # original kept
        self.assertTrue(os.path.isdir(os.path.join(self.comm, "addon-new")))
        aside = [x for x in os.listdir(self.pkg) if x.startswith("Community-new-")]; self.assertEqual(len(aside), 1)
    def test_missing_community_blocks(self):
        shutil.rmtree(self.comm); p = self.plan(); self.assertFalse(p["ok"]); self.assertIn("not found", p["errors"][0])
    def test_no_packages_path_blocks(self):
        open(self.cfg, "w").write("{Graphics\n\tPreset Custom\n}\n"); self.assertFalse(self.plan()["ok"])
    @unittest.skipIf(os.name == "nt", "creating a link needs a privilege this test does not ask for")
    def test_symlink_community_blocks(self):
        real = os.path.join(self.pkg, "real"); os.rename(self.comm, real); os.symlink(real, self.comm)
        p = self.plan(); self.assertFalse(p["ok"]); self.assertIn("link", p["errors"][0])
    @unittest.skipIf(os.name == "nt", "folder mode bits are not enforced on Windows")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores permissions")
    def test_permission_denied_blocks(self):
        os.chmod(self.pkg, 0o555); p = self.plan(); self.assertFalse(p["ok"]); self.assertIn("permission", p["errors"][0])
    def test_failure_midway_rolls_back(self):
        before = open(self.cfg).read(); p = self.plan()
        real_mkdir = os.mkdir
        def boom(path, *a, **k):
            if os.path.abspath(path) == os.path.abspath(self.comm): raise PermissionError(13, "locked", path)
            return real_mkdir(path, *a, **k)
        m.os.mkdir = boom
        try: r = m.run_update_cleanup(self.cfg, p)
        finally: m.os.mkdir = real_mkdir
        self.assertFalse(r["ok"]); self.assertTrue(os.path.exists(os.path.join(self.comm, "addon-a", "layout.json")))
        self.assertFalse(os.path.exists(os.path.join(self.pkg, "Community-old")))
        self.assertEqual(open(self.cfg).read(), before); self.assertEqual(len(os.listdir(self.nv)), 1)   # caches untouched
        self.assertIsNone(m.undo_state(self.cfg)); self.assertIn("Rollback complete", open(m.log_path_for(self.cfg)).read())
    def test_failure_on_rename_locked_folder(self):
        p = self.plan(); real = os.rename
        def boom(a, b): raise PermissionError(32, "in use", a)
        m.os.rename = boom
        try: r = m.run_update_cleanup(self.cfg, p)
        finally: m.os.rename = real
        self.assertFalse(r["ok"]); self.assertTrue(os.path.isdir(os.path.join(self.comm, "addon-a")))
if __name__ == "__main__": unittest.main()
