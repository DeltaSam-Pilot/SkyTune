import os, sys, shutil, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
S24 = os.path.join(os.path.dirname(__file__), "sample_UserCfg_2024.opt")

class Cleaner(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.env = {"APPDATA": os.path.join(self.d, "Roaming"), "LOCALAPPDATA": os.path.join(self.d, "Local")}
        self.steam = os.path.join(self.env["APPDATA"], "Microsoft Flight Simulator 2024")
        os.makedirs(os.path.join(self.steam, "cache", "sub")); os.makedirs(os.path.join(self.steam, "SceneryIndexes"))
        os.makedirs(os.path.join(self.steam, "Packages", "Community", "addon"))
        self.w(os.path.join(self.steam, "UserCfg.opt"), 100); self.w(os.path.join(self.steam, "ROLLINGCACHE.CCC"), 5000)
        self.w(os.path.join(self.steam, "cache", "a.bin"), 1000); self.w(os.path.join(self.steam, "cache", "sub", "b.bin"), 2000)
        self.w(os.path.join(self.steam, "SceneryIndexes", "x.idx"), 300)
        self.w(os.path.join(self.steam, "Packages", "Community", "addon", "keep.txt"), 50)
        self.nv = os.path.join(self.env["LOCALAPPDATA"], "NVIDIA", "DXCache"); os.makedirs(self.nv)
        self.w(os.path.join(self.nv, "s1.nvph"), 700)
        self.items = m.resolve_cache_items(self.env); self.by = {i["id"]: i for i in self.items}
    def tearDown(self):
        for root, dirs, files in os.walk(self.d):
            for x in dirs: os.chmod(os.path.join(root, x), 0o755)
        shutil.rmtree(self.d)
    def w(self, p, n):
        with open(p, "wb") as f: f.write(b"x" * n)

    def test_resolve_paths_and_existence(self):
        self.assertTrue(self.by["rolling_steam"]["exists"]); self.assertTrue(self.by["nv_dx"]["exists"])
        self.assertFalse(self.by["amd_dx"]["exists"])
        self.assertEqual(self.by["nv_perdriver"]["path"], os.path.join(self.d, "LocalLow", "NVIDIA", "PerDriverVersion", "DXCache"))
        self.assertTrue(self.by["rolling_store"]["path"].endswith(os.path.join("Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache", "ROLLINGCACHE.CCC")))
    def test_sizes(self):
        self.assertEqual(m.path_size(self.by["simcache_steam"]["path"]), 3000)
        self.assertEqual(m.path_size(self.by["rolling_steam"]["path"]), 5000)
        self.assertEqual(m.human_size(1536), "1.5 KB"); self.assertEqual(m.human_size(512), "512 B")
        self.assertEqual(m.human_size(3 * 1024 ** 3), "3.0 GB")
    def test_whitelist_enforced(self):
        self.assertTrue(m.is_whitelisted(os.path.join(self.steam, "cache", "a.bin"), self.items))
        for bad in (os.path.join(self.steam, "UserCfg.opt"), self.steam, os.path.join(self.steam, "Packages", "Community"),
                    os.path.join(self.steam, "cache", ".."), self.d, os.path.join(self.env["LOCALAPPDATA"], "NVIDIA")):
            self.assertFalse(m.is_whitelisted(bad, self.items), bad)
        self.assertFalse(m.is_whitelisted(os.path.join(self.steam, "cache", "Community", "x"), self.items))
        r = m.clear_item({"id": "rogue", "kind": "dir", "path": self.steam}, self.items)
        self.assertEqual(r["deleted"], 0); self.assertTrue(r["refused"])
        self.assertTrue(os.path.exists(os.path.join(self.steam, "UserCfg.opt")))
    def test_clear_contents_keeps_folder_and_protected(self):
        r = m.clear_item(self.by["simcache_steam"], self.items)
        self.assertEqual((r["freed"], r["deleted"]), (3000, 2))
        self.assertEqual(os.listdir(self.by["simcache_steam"]["path"]), [])
        self.assertEqual(m.clear_item(self.by["rolling_steam"], self.items)["freed"], 5000)
        for keep in ("UserCfg.opt", os.path.join("Packages", "Community", "addon", "keep.txt"), os.path.join("SceneryIndexes", "x.idx")):
            self.assertTrue(os.path.exists(os.path.join(self.steam, keep)), keep)
    def test_symlink_not_followed(self):
        link = os.path.join(self.steam, "cache", "evil"); os.symlink(os.path.join(self.steam, "Packages"), link)
        m.clear_item(self.by["simcache_steam"], self.items)
        self.assertTrue(os.path.exists(os.path.join(self.steam, "Packages", "Community", "addon", "keep.txt")))
        self.assertEqual(m.path_size(link), 0)
    def test_locked_files_skipped(self):
        locked = os.path.join(self.nv, "s1.nvph"); self.w(os.path.join(self.nv, "s2.nvph"), 10)
        real = os.remove
        def fake(p, *a, **k):
            if os.path.abspath(p) == os.path.abspath(locked): raise PermissionError(13, "in use", p)
            return real(p, *a, **k)
        m.os.remove = fake
        try: r = m.clear_item(self.by["nv_dx"], self.items)
        finally: m.os.remove = real
        self.assertEqual(r["skipped"], [locked]); self.assertEqual(r["deleted"], 1); self.assertTrue(os.path.exists(locked))
    @unittest.skipIf(os.name == "nt", "folder mode bits are not enforced on Windows")
    def test_locked_subfolder_kept(self):
        sub = os.path.join(self.steam, "cache", "sub"); os.chmod(sub, 0o555)
        r = m.clear_item(self.by["simcache_steam"], self.items)
        if os.geteuid() != 0:
            self.assertEqual(len(r["skipped"]), 1); self.assertTrue(os.path.isdir(sub))
        self.assertFalse(os.path.exists(os.path.join(self.steam, "cache", "a.bin")))
    def test_stutter_fix_defaults(self):
        ids = {it["id"] for it in m.CACHE_ITEMS if it["default"]}
        self.assertEqual(ids, {"d3dscache", "nv_dx", "nv_gl", "nv_perdriver", "amd_dx", "amd_dxc",
                               "simcache_steam", "simcache_store"})
        for it in m.CACHE_ITEMS: self.assertEqual(bool(it["stutter"]), it["default"], it["id"])   # every default has a source
        self.assertEqual([i["id"] for i in m.stutter_fix_items(self.items)], ["simcache_steam", "nv_dx"])  # only existing
        r = m.clear_item(self.by["nv_dx"], self.items); self.assertEqual(r["freed"], 700)
        self.assertTrue(os.path.exists(os.path.join(self.steam, "ROLLINGCACHE.CCC")))              # rolling cache not in fix
    def test_roaming_folder_layout(self):
        # Real Steam layout: never touch protected/unknown items next to the caches
        keep = ["SimObjects", "MISSIONS", "WASM", "SammyBoy#5628", "CAAC5B2F9F390315", "tmcache", "RAIDumps", "Weather"]
        for k in keep: os.makedirs(os.path.join(self.steam, k)); self.w(os.path.join(self.steam, k, "f"), 10)
        for f in ["EXE.xml", "SimConnect.xml", "DevMode", "FlightSimulator2024.CFG", "GrantedRewards.BIN"]:
            self.w(os.path.join(self.steam, f), 10)
        os.makedirs(os.path.join(self.steam, "AsoboReport-OldCrashes")); self.w(os.path.join(self.steam, "AsoboReport-OldCrashes", "c.txt"), 40)
        items = m.resolve_cache_items(self.env); by = {i["id"]: i for i in items}
        self.assertEqual(by["rolling_steam"]["path"], os.path.join(self.steam, "ROLLINGCACHE.CCC"))
        self.assertFalse(by["oldcrashes_steam"]["default"]); self.assertIsNone(by["oldcrashes_steam"]["stutter"])
        for it in items:
            if it["exists"]: m.clear_item(it, items)
        for k in keep: self.assertTrue(os.path.exists(os.path.join(self.steam, k, "f")), k)
        for f in ["EXE.xml", "SimConnect.xml", "DevMode", "FlightSimulator2024.CFG", "GrantedRewards.BIN", "UserCfg.opt"]:
            self.assertTrue(os.path.exists(os.path.join(self.steam, f)), f)
        self.assertTrue(os.path.exists(os.path.join(self.steam, "Packages", "Community", "addon", "keep.txt")))
        self.assertEqual(os.listdir(os.path.join(self.steam, "AsoboReport-OldCrashes")), [])
        for it in items: self.assertFalse(m.is_whitelisted(os.path.join(self.steam, "SimObjects"), [it]))
    def test_update_cleanup_includes_scenery_indexes(self):
        ids = [i["id"] for i in m.update_cleanup_items(self.items)]
        self.assertIn("sceneryidx_steam", ids); self.assertIn("simcache_steam", ids)
        self.assertNotIn("rolling_steam", ids); self.assertNotIn("sceneryidx_steam", [i["id"] for i in m.stutter_fix_items(self.items)])
    def test_missing_item_is_noop(self):
        r = m.clear_item(self.by["amd_dx"], self.items); self.assertEqual((r["freed"], r["deleted"], r["skipped"]), (0, 0, []))
    def test_every_item_is_cache_like(self):
        for it in m.CACHE_ITEMS:
            self.assertNotIn(it["rel"][-1].lower(), m.PROTECTED_NAMES); self.assertTrue(it["title"] and it["explain"])

class Traffic(unittest.TestCase):
    def test_traffic_keys_exist_in_2024_sample(self):
        c = m.UserCfg.load(S24)
        for path, label, tip in m.TRAFFIC_CATS:
            self.assertIn(path, c.index, path); self.assertIn("CPU", tip)
    def test_presets_respect_traffic_choices(self):
        choice = {p: None for p, _, _ in m.TRAFFIC_CATS}
        choice["Graphics/Traffic/AircraftTrafficQuantity"] = 2; choice["Graphics/Characters/Quantity"] = 0
        for name in m.PRESETS:
            v = m.with_user_choices(m.PRESETS[name], traffic=choice)
            self.assertEqual(v["Graphics/Traffic/AircraftTrafficQuantity"], 2, name)
            self.assertEqual(v["Graphics/Characters/Quantity"], 0, name)
            self.assertEqual(v.get("Graphics/Traffic/RoadQuality"), m.PRESETS[name].get("Graphics/Traffic/RoadQuality"))
            self.assertEqual((v["Video/AntiAliasing"], v["Video/FrameGeneration"]), ("TAA", "NONE"))
    def test_traffic_written_to_file(self):
        c = m.UserCfg.load(S24)
        m.apply_values(c, m.with_user_choices(m.PRESETS["Ultra+"], traffic={"Graphics/Traffic/SeaQuality": 0, "Graphics/Fauna/Quantity": 2}))
        self.assertEqual(c.get("Graphics/Traffic/SeaQuality"), "0"); self.assertEqual(c.get("Graphics/Fauna/Quantity"), "2")
    def test_master_level_mapping(self):
        self.assertEqual(set(m.traffic_for_level("High").values()), {2})
        self.assertEqual(set(m.traffic_for_level("Ultra").values()), {3})
        self.assertEqual(set(m.traffic_for_level("Off").values()), {-1})
        self.assertEqual(set(m.traffic_for_level("Low").values()), {0})
        self.assertEqual(set(m.traffic_for_level("SkyTune decides").values()), {None})
        self.assertEqual(len(m.traffic_for_level("Low")), len(m.TRAFFIC_CATS))
    def test_master_level_beats_presets_and_goals(self):
        hw = {"gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8, "cores": 8, "ram_gb": 32, "width": 1920, "height": 1080}
        for g in m.GOALS:
            for lvl, val in (("Off", -1), ("Ultra", 3), ("Medium", 1)):
                v = m.with_user_choices(m.plan(hw, g)[1], traffic=m.traffic_for_level(lvl))
                for p, _, _ in m.TRAFFIC_CATS:
                    if p in v or val is not None: self.assertEqual(v[p], val, (g, lvl, p))
    def test_preset_decides_is_noop(self):
        self.assertEqual(m.with_user_choices(m.PRESETS["Balanced"], traffic={p: None for p, _, _ in m.TRAFFIC_CATS}),
                         m.with_user_choices(m.PRESETS["Balanced"]))
if __name__ == "__main__": unittest.main()
