import os, sys, shutil, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
S24 = os.path.join(os.path.dirname(__file__), "sample_UserCfg_2024.opt")

def hw(gpu, vram, cpu, cores, ram, w, h, integrated=None):
    d = {"gpu": gpu, "vram_gb": vram, "cpu": cpu, "cores": cores, "threads": cores * 2, "ram_gb": ram,
         "width": w, "height": h, "errors": []}
    d["integrated"] = m.is_integrated(gpu) if integrated is None else integrated
    return d

PROFILES = {   # name: (hw, allowed presets)
    "low-end laptop iGPU": (hw("Intel(R) UHD Graphics 620", 1, "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz", 4, 8, 1366, 768), {"Performance"}),
    "Radeon 780M APU": (hw("AMD Radeon 780M Graphics", 4, "AMD Ryzen 7 7840HS", 8, 16, 1920, 1200), {"Performance"}),
    "Steam Deck": (hw("AMD Custom GPU 0405", 1, "AMD Custom APU 0405", 4, 16, 1280, 800), {"Performance"}),
    "GTX 1060": (hw("NVIDIA GeForce GTX 1060 6GB", 6, "Intel(R) Core(TM) i5-8400 CPU", 6, 16, 1920, 1080), {"Performance"}),
    "GTX 970": (hw("NVIDIA GeForce GTX 970", 4, "Intel(R) Core(TM) i7-4790K", 4, 16, 1920, 1080), {"Performance"}),
    "RX 580": (hw("Radeon RX 580 Series", 8, "AMD Ryzen 5 3600 6-Core Processor", 6, 16, 1920, 1080), {"Performance"}),
    "Arc A770": (hw("Intel(R) Arc(TM) A770 Graphics", 16, "Intel(R) Core(TM) i5-12400F", 6, 32, 2560, 1440), {"Balanced-30"}),
    "RTX 4060 laptop": (hw("NVIDIA GeForce RTX 4060 Laptop GPU", 8, "13th Gen Intel(R) Core(TM) i7-13700H", 14, 16, 1920, 1080), {"Performance", "Balanced-30"}),
    "RTX 3070 Ti 1080p": (hw("NVIDIA GeForce RTX 3070 Ti", 8, "AMD Ryzen 7 5800X 8-Core Processor", 8, 32, 1920, 1080), {"Balanced-30"}),
    "RX 7900 XTX 4K ultrawide": (hw("AMD Radeon RX 7900 XTX", 24, "AMD Ryzen 7 7800X3D 8-Core Processor", 8, 64, 5120, 2160), {"Ultra+", "Quality"}),
    "RTX 4090 4K": (hw("NVIDIA GeForce RTX 4090", 24, "AMD Ryzen 9 9950X3D", 16, 64, 3840, 2160), {"Ultra+"}),
    "RTX 5070 ultrawide 1440": (hw("NVIDIA GeForce RTX 5070", 12, "Intel(R) Core(TM) Ultra 7 265K", 20, 32, 3440, 1440), {"Balanced"}),
    "unknown GPU 12 GB": (hw("Mystery Graphics 9000", 12, "Unknown", 0, 32, 1920, 1080), {"Balanced-30"}),
    "nothing detected": (hw("Unknown", 0, "Unknown", 0, 0, 0, 0), {"Performance"}),
}

class Profiles(unittest.TestCase):
    def test_profiles(self):
        for name, (h, ok) in PROFILES.items():
            for goal in m.GOALS:
                preset, values, score, reasons, tech = m.plan(h, goal)
                self.assertTrue(reasons and values, name)
            p, s, r = m.recommend(h)
            self.assertIn(p, ok, "%s -> %s %s" % (name, p, r))
    def test_tiers(self):
        self.assertEqual(m.gpu_tier("NVIDIA GeForce RTX 5090")[0], 4)
        self.assertEqual(m.gpu_tier("AMD Radeon RX 9070 XT")[0], 4)
        self.assertEqual(m.gpu_tier("AMD Radeon RX 9070")[0], 3)
        self.assertEqual(m.gpu_tier("AMD Radeon RX 7900 XT")[0], 3)
        self.assertEqual(m.gpu_tier("NVIDIA GeForce RTX 3080 Laptop GPU")[0], 2)
        self.assertEqual(m.gpu_tier("NVIDIA GeForce RTX 2080 with Max-Q Design")[0], 1)
        self.assertEqual(m.gpu_tier("Intel(R) Arc(TM) B580 Graphics")[0], 2)
        self.assertEqual(m.gpu_tier("AMD Radeon RX 470")[0], 1)
        self.assertEqual(m.gpu_tier("NVIDIA GeForce GTX 950")[0], 0)
        self.assertEqual(m.gpu_tier("Brand new GPU", 24)[0], 3)
        self.assertTrue(m.is_integrated("Intel(R) Iris(R) Xe Graphics")); self.assertTrue(m.is_integrated("AMD Radeon(TM) Graphics"))
        self.assertFalse(m.is_integrated("AMD Radeon RX 6800M")); self.assertFalse(m.is_integrated("Intel(R) Arc(TM) A770 Graphics"))
    def test_cpu_tiers(self):
        self.assertEqual(m.cpu_tier("AMD Ryzen 7 5800X3D 8-Core Processor"), 4)
        self.assertEqual(m.cpu_tier("Intel(R) Core(TM) i9-14900K"), 4)
        self.assertEqual(m.cpu_tier("Intel(R) Core(TM) Ultra 9 285K"), 4)
        self.assertEqual(m.cpu_tier("Intel(R) Core(TM) i5-12400F"), 2)
        self.assertEqual(m.cpu_tier("Intel(R) Celeron(R) N4020"), 0)
        self.assertIsNone(m.cpu_tier("Some future CPU"))
    def test_prefers_discrete_and_ignores_virtual(self):
        g = m.pick_gpu([{"Name": "AMD Radeon(TM) Graphics", "Bytes": 512 << 20, "Src": "registry"},
                        {"Name": "AMD Radeon RX 7600S", "Bytes": 8 << 30, "Src": "registry"},
                        {"Name": "Parsec Virtual Display Adapter", "Bytes": 0, "Src": "wmi"},
                        {"Name": "Microsoft Basic Display Adapter", "Bytes": 0, "Src": "wmi"}])
        self.assertEqual(g["name"], "AMD Radeon RX 7600S"); self.assertEqual(g["vram_gb"], 8.0)
        g = m.pick_gpu([{"Name": "NVIDIA GeForce RTX 3060", "Bytes": 12 << 30, "Src": "registry"},
                        {"Name": "NVIDIA GeForce RTX 4080", "Bytes": 16 << 30, "Src": "registry"}])
        self.assertEqual(g["name"], "NVIDIA GeForce RTX 4080")                      # multi-GPU: strongest
        g = m.pick_gpu([{"Name": "NVIDIA GeForce RTX 3080", "Bytes": 0xFFFFFFFF + 1 + 10 << 30, "Src": "wmi"},
                        {"Name": "NVIDIA GeForce RTX 3080", "Bytes": 10 << 30, "Src": "registry"}])
        self.assertEqual(g["vram_gb"], 10.0)                                           # registry beats WMI
        self.assertEqual(m.pick_gpu([])["name"], "Unknown")
    def test_parsers(self):
        self.assertEqual(m.parse_wmic("\r\nAdapterRAM=4293918720\r\nName=NVIDIA GeForce RTX 3070\r\n\r\n")[0]["Name"], "NVIDIA GeForce RTX 3070")
        dx = "Display Devices\n---\n          Card name: AMD Radeon RX 6700 XT\n   Dedicated Memory: 12,272 MB\n"
        self.assertEqual(m.parse_dxdiag(dx), [{"Name": "AMD Radeon RX 6700 XT", "Bytes": 12272 << 20, "Src": "dxdiag"}])
        self.assertEqual(m.parse_xrandr("Screen 0: minimum 8 x 8, current 4480 x 1440\nDP-1 connected primary 3440x1440+0+0\nHDMI-1 connected 1040x1440+3440+0"), (3440, 1440))
        self.assertEqual(m.parse_xrandr("Screen 0: current 1280 x 800, maximum 8192"), (1280, 800))
        cpu = "processor\t: 0\nmodel name\t: AMD Custom APU 0405\nphysical id\t: 0\ncore id\t: 0\nprocessor\t: 1\nmodel name\t: AMD Custom APU 0405\nphysical id\t: 0\ncore id\t: 1\n"
        self.assertEqual(m.linux_cpu(cpu), ("AMD Custom APU 0405", 2, 2))
    def test_linux_sysfs_gpu(self):
        d = tempfile.mkdtemp()
        try:
            dev = os.path.join(d, "class", "drm", "card1", "device"); os.makedirs(dev)
            open(os.path.join(dev, "mem_info_vram_total"), "w").write(str(16 << 30))
            lspci = '03:00.0 "VGA compatible controller" "Advanced Micro Devices, Inc. [AMD/ATI]" "Navi 21 [Radeon RX 6800/6800 XT / 6900 XT]" -rc1'
            gl = m.linux_gpus(sys_root=d, lspci_out=lspci)
            self.assertTrue(any(g["Bytes"] == 16 << 30 for g in gl))
        finally: shutil.rmtree(d)
    def test_detect_never_raises(self):
        with mock.patch.object(m, "_run", return_value=""), mock.patch.object(m, "_ram_gb", side_effect=OSError("x")), \
             mock.patch.object(m, "_screen", side_effect=OSError("y")), mock.patch.object(m, "linux_gpus", side_effect=RuntimeError("z")):
            h = m.detect_hardware()
        self.assertEqual(h["gpu"], "Unknown"); self.assertTrue(h["errors"])
        self.assertEqual(m.recommend(h)[0], "Performance")
    def test_manual_pick(self):
        h = m.manual_hw(PROFILES["nothing detected"][0], "Intel Arc A750 / A770 / B570 / B580", 16)
        self.assertEqual(h["vram_gb"], 16.0); self.assertFalse(any("not detected" in e for e in h["errors"]))
        lap = m.manual_hw(h, "NVIDIA RTX 4080 / 4090 / 5080 / 5090", 12, laptop=True)
        self.assertLess(m.gpu_tier(lap["gpu"])[0], 4)

class LinuxPaths(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="hömé-")
        self.lib2 = os.path.join(self.home, "mnt", "Games", "SteamLibrary")
        root = os.path.join(self.home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")   # Flatpak
        os.makedirs(os.path.join(root, "steamapps"))
        with open(os.path.join(root, "steamapps", "libraryfolders.vdf"), "w") as f:
            f.write('"libraryfolders"\n{\n "0"\n {\n  "path"  "%s"\n }\n "1"\n {\n  "path"  "%s"\n }\n}\n' % (root, self.lib2))
        self.u = os.path.join(self.lib2, "steamapps", "compatdata", "2537590", "pfx", "drive_c", "users", "steamuser")
        self.fs = os.path.join(self.u, "AppData", "Roaming", "Microsoft Flight Simulator 2024"); os.makedirs(self.fs)
        os.makedirs(os.path.join(self.u, "..", "Public"))
        shutil.copy(S24, os.path.join(self.fs, "UserCfg.opt"))
        open(os.path.join(self.fs, "ROLLINGCACHE.CCC"), "wb").write(b"x" * 10)
        self.sc = os.path.join(self.lib2, "steamapps", "shadercache", "2537590"); os.makedirs(self.sc)
        open(os.path.join(self.sc, "fozpipelinesv6"), "wb").write(b"y" * 20)
        os.makedirs(os.path.join(self.lib2, "steamapps", "shadercache", "123"))
    def tearDown(self): shutil.rmtree(self.home)
    def test_finds_prefix_on_second_library_flatpak(self):
        with mock.patch.object(m.os, "name", "posix"):
            c = m.candidate_paths(self.home)
        self.assertEqual(c[0][1], os.path.join(self.fs, "UserCfg.opt")); self.assertEqual(len(c), 1)
        env = m.linux_env(self.home)
        self.assertEqual(env["APPDATA"], os.path.join(self.u, "AppData", "Roaming"))
        items = {i["id"]: i for i in m.resolve_cache_items(env)}
        self.assertTrue(items["rolling_steam"]["exists"]); self.assertTrue(items["steam_shadercache"]["exists"])
        self.assertEqual(items["steam_shadercache"]["path"], self.sc)
        r = m.clear_item(items["steam_shadercache"], list(items.values())); self.assertEqual(r["freed"], 20)
        self.assertTrue(os.path.isdir(os.path.join(self.lib2, "steamapps", "shadercache", "123")))   # other games untouched
        self.assertIsNone(m.cfg_problem(os.path.join(self.fs, "UserCfg.opt")))

class BrokenCfg(unittest.TestCase):
    def setUp(self): self.d = tempfile.mkdtemp(prefix="Zoë OneDrive-")
    def tearDown(self): shutil.rmtree(self.d)
    def test_missing_empty_damaged(self):
        p = os.path.join(self.d, "UserCfg.opt")
        self.assertEqual(m.cfg_problem(p), "missing")
        open(p, "w").close(); self.assertEqual(m.cfg_problem(p), "empty")
        open(p, "w").write("{Graphics\n Version 1\n"); self.assertTrue(m.cfg_problem(p).startswith("damaged"))
        open(p, "w").write("garbage line\n"); self.assertTrue(m.cfg_problem(p).startswith("damaged"))
    def test_non_utf8_bytes_preserved(self):
        p = os.path.join(self.d, "UserCfg.opt"); raw = open(S24, "rb").read().replace(b"{Graphics", b"{Graphics\r\n\tNote caf\xe9", 1)
        open(p, "wb").write(raw)
        c = m.UserCfg.load(p); c.set("Graphics/Terrain/LoDFactor", "1.5"); c.save(p)
        out = open(p, "rb").read(); self.assertIn(b"caf\xe9", out); self.assertIn(b"1.5", out)
