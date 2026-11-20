"""1.8.1 pieces: logs in the support pack, per-card OptiScaler options, neural status, NVIDIA profiles."""
import os, shutil, tempfile, unittest, zipfile
import msfs_tweaker as m

class SupportLogs(unittest.TestCase):
    def test_optiscaler_and_reshade_logs_are_masked_and_optional(self):
        folder = tempfile.mkdtemp()
        try:
            sim = os.path.join(folder, "sim")
            os.makedirs(sim)
            with open(os.path.join(sim, "OptiScaler.log"), "w", encoding="utf-8") as handle:
                handle.write(r"C:\Users\Sam\game pilot@example.com")
            with open(os.path.join(sim, "ReShade.log"), "w", encoding="utf-8") as handle:
                handle.write("reshade ok")
            with open(os.path.join(sim, "notes.dll"), "wb") as handle:
                handle.write(b"nope")
            entries = m.build_support_pack(extra_logs=m.mod_logs([sim]))
            names = m.support_pack_names(entries)
            self.assertIn("OptiScaler.log", names)
            self.assertIn("ReShade.log", names)
            self.assertNotIn("notes.dll", names)
            text = next(item["text"] for item in entries if item["name"] == "OptiScaler.log")
            self.assertIn("<user>", text)
            self.assertNotIn("Sam", text)
            self.assertIn("<email>", text)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

class OptiChoices(unittest.TestCase):
    def test_vendor_mapping_and_best_quality(self):
        rtx = m.optiscaler_choices("NVIDIA GeForce RTX 4070")
        self.assertEqual([item["id"] for item in rtx["upscalers"]], ["dlss", "fsr", "xess"])
        self.assertIn("dlss_fg", [item["id"] for item in rtx["frame_generation"]])
        self.assertIn("fsr_fg", [item["id"] for item in rtx["frame_generation"]])
        amd = m.optiscaler_choices("AMD Radeon RX 7800 XT")
        self.assertEqual([item["id"] for item in amd["upscalers"]], ["fsr", "xess"])
        self.assertNotIn("dlss_fg", [item["id"] for item in amd["frame_generation"]])
        intel = m.optiscaler_choices("Intel Arc A770")
        self.assertEqual([item["id"] for item in intel["upscalers"]], ["fsr", "xess"])
        gtx = m.optiscaler_choices("NVIDIA GeForce GTX 1660")
        self.assertNotIn("dlss", [item["id"] for item in gtx["upscalers"]])
        for choice in (rtx, amd, intel, gtx):
            blob = " ".join(item["label"] for item in choice["upscalers"] + choice["frame_generation"])
            self.assertNotIn("DLSS 5", blob)
            self.assertTrue(all(item["saved"] == "saved in your settings" for item in choice["upscalers"]))
        best = m.best_quality_optiscaler("NVIDIA GeForce RTX 4070")
        self.assertEqual(best["mode"], "DLAA")
        self.assertIn("saved in your settings", best["summary"])
        self.assertNotIn("DLSS 5", best["summary"])
        self.assertEqual(m.best_quality_optiscaler("AMD Radeon RX 7800 XT")["mode"], "Native AA")
        self.assertEqual(m.best_quality_optiscaler("Intel Arc A770")["dx12_upscaler"], "xess")

class Neural(unittest.TestCase):
    def test_observed_only_with_log_evidence(self):
        quiet = m.neural_status("NVIDIA GeForce RTX 4070", "")
        self.assertEqual(quiet[0]["state"], "saved in your settings")
        self.assertFalse(quiet[0]["observed"])
        seen = m.neural_status("NVIDIA GeForce RTX 4070", "DLSS selected for this run")
        self.assertEqual(seen[0]["state"], "observed in the log")
        amd = m.neural_status("AMD Radeon RX 7800 XT", "FSR 4 init ok")
        self.assertEqual(amd, [])
        rdna = m.neural_status("AMD Radeon RX 9070 XT", "")
        self.assertEqual(rdna[0]["id"], "fsr_neural")
        self.assertEqual(rdna[0]["state"], "saved in your settings")
        self.assertNotIn("DLSS 5", rdna[0]["label"])

class NvidiaProfile(unittest.TestCase):
    def test_non_nvidia_does_nothing_and_restore_uses_the_backup(self):
        self.assertIsNone(m.nvidia_profile_plan("AMD Radeon RX 7800 XT"))
        written = []
        current = {"FlightSimulator.exe": {0x1057EB71: 5}, "FlightSimulator2024.exe": {0x1057EB71: 5}}
        def reader(exe):
            return dict(current[exe])
        def writer(exe, setting, value):
            written.append((exe, setting, value))
            current[exe][setting] = value
        plan = m.nvidia_profile_plan("NVIDIA GeForce RTX 4070")
        result = m.apply_nvidia_profile(plan, reader, writer)
        self.assertTrue(result["ok"])
        self.assertEqual(result["backup"]["profiles"]["FlightSimulator.exe"][str(0x1057EB71)], 5)
        self.assertTrue(all(os.path.basename(item[0]) in m.MSFS_NVIDIA_EXECUTABLES for item in written))
        restored = []
        m.restore_nvidia_profile(result["backup"], lambda exe, setting, value: restored.append((exe, setting, value)))
        self.assertEqual(restored[0][2], 5)
        bad = m.nvidia_profile_plan("NVIDIA GeForce RTX 4070")
        bad["executables"] = ["OtherGame.exe"]
        refused = m.apply_nvidia_profile(bad, reader, writer)
        self.assertFalse(refused["ok"])
        self.assertIsNone(refused["backup"])

class UpdateCatalog(unittest.TestCase):
    def test_check_reads_versions_and_does_not_download(self):
        pages = {
            "https://flightsim.to/addon/117307/sky-tune": "Version 2.0.0 in the description. Downloads 10 Version 1.7.0 File Size 1 MB",
            "https://api.github.com/repos/optiscaler/OptiScaler/releases/latest": '{"tag_name":"v0.9.5","assets":[]}',
            "https://reshade.me": "Version 6.8.0 was released. Download ReShade 6.8.0",
            "https://api.github.com/repos/IFreemz/msfs2024-glass-cockpit-dlss-fix/releases/latest": '{"tag_name":"v1.1.0"}',
            "https://api.github.com/repos/tomwhoca/AtmosphereMod/releases/latest": '{"tag_name":"v0.7.3"}',
        }
        seen = []
        def fetch(url):
            seen.append(url)
            if url not in pages:
                raise OSError(url)
            return pages[url]
        lines = m.catalog_lines(fetch)
        self.assertEqual(lines[0], "SkyTune · 1.7.0")
        self.assertIn("OptiScaler · 0.9.5", lines)
        self.assertIn("ReShade · 6.8.0", lines)
        self.assertTrue(all("browser_download" not in url for url in seen))
        def broken(_url):
            raise OSError("offline")
        self.assertTrue(all(line.endswith("could not be read") for line in m.catalog_lines(broken)))

class LooksAndOverlay(unittest.TestCase):
    def test_presets_are_ini_files_and_overlay_does_not_invent_fps(self):
        folder = tempfile.mkdtemp()
        try:
            record = {"mods": []}
            result = m.write_reshade_presets(folder, record)
            self.assertEqual(len(result["files"]), 3)
            text = open(os.path.join(folder, "SkyTune-Natural.ini"), encoding="utf-8").read()
            self.assertIn("Tonemap.fx", text)
            self.assertNotIn("float4", text)
            self.assertEqual(len(record["mods"][0]["files"]), 3)
            m.uninstall_managed_mod(record, "reshade")
            self.assertFalse(os.path.exists(os.path.join(folder, "SkyTune-Vivid.ini")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertIn("FPS not read", m.overlay_text(None, "Natural"))
        self.assertIn("saved in your settings", m.overlay_text(60, "Vivid"))
        csv = "Application,MsBetweenPresents\nFlightSimulator.exe,16.6\nFlightSimulator.exe,16.8\n"
        self.assertEqual(m.fps_from_presentmon_csv(csv), 60)
        self.assertIsNone(m.fps_from_presentmon_csv("Application,Other\n"))
        self.assertIsNone(m.presentmon_fps(lookup=lambda _name: None))
        self.assertEqual(len(m.UPDATE_CATALOG), 5)

class OptiArchive(unittest.TestCase):
    def test_7z_keeps_only_dll_and_ini(self):
        folder = tempfile.mkdtemp()
        try:
            with open(os.path.join(folder, "OptiScaler.dll"), "wb") as handle:
                handle.write(b"dll")
            with open(os.path.join(folder, "notes.txt"), "wb") as handle:
                handle.write(b"no")
            result = m.optiscaler_archive_files(b"not-a-real-7z", "OptiScaler.7z", unpack=lambda _data: folder)
            self.assertEqual(result["files"], {"OptiScaler.dll": b"dll"})
            missing = m.optiscaler_archive_files(b"x", "OptiScaler.7z", unpack=lambda _data: None)
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["files"], {})
        finally:
            shutil.rmtree(folder, ignore_errors=True)

class OptiRecord(unittest.TestCase):
    def test_install_record_and_uninstall(self):
        folder = tempfile.mkdtemp()
        try:
            with open(os.path.join(folder, "dxgi.dll"), "wb") as handle:
                handle.write(b"old")
            record = {"mods": []}
            result = m.install_optiscaler_files(
                {"OptiScaler.dll": b"new", "OptiScaler.ini": b"Dx12Upscaler=auto\n", "readme.cpp": b"no"},
                folder, record, "v0.9.5")
            self.assertTrue(result["ok"])
            self.assertEqual(open(os.path.join(folder, "dxgi.dll"), "rb").read(), b"new")
            self.assertEqual(open(os.path.join(folder, "dxgi.dll.skytune-backup"), "rb").read(), b"old")
            self.assertTrue(os.path.isfile(os.path.join(folder, "OptiScaler.ini")))
            self.assertFalse(os.path.exists(os.path.join(folder, "readme.cpp")))
            m.uninstall_managed_mod(record, "optiscaler")
            self.assertEqual(open(os.path.join(folder, "dxgi.dll"), "rb").read(), b"old")
        finally:
            shutil.rmtree(folder, ignore_errors=True)
