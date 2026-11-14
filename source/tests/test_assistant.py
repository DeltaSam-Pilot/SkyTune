"""v1.3.0 assistant: offline rules engine, diagnosis, ranked fixes, feedback loop, AI mode (mocked) and prefs."""
import os, sys, json, tempfile, threading, unittest, http.server, socket
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import msfs_tweaker as m
HERE = os.path.dirname(os.path.abspath(__file__))

HEAVY = {  # a deliberately heavy file
    "Video/AntiAliasing": "DLSS", "Video/DLSSMode": "PERFORMANCE", "Video/FrameGeneration": "DLSSG", "Video/PrimaryScaling": 1.0,
    "Video/SharpenAmount": 0.0, "Video/FrameLimiter": 0, "Graphics/Terrain/LoDFactor": 3.0, "Graphics/ObjectsLoD/LoDFactor": 2.0,
    "Graphics/Texture/Quality": 0, "Graphics/Texture/MaxAnisotropy": 4, "Graphics/VolumetricClouds/Quality": 3,
    "Graphics/Shadows/Size": 2048, "Graphics/ContactShadows/Quality": 3, "Graphics/RaytracedShadows/Enabled": 1,
    "Graphics/OffscreenTerrainPreCaching/Quality": 0, "Graphics/GlassCockpitsRefreshRate/Quality": 2,
    "Graphics/Traffic/AircraftTrafficQuantity": 3, "Graphics/Traffic/ParkedAircraftQuantity": 3,
    "Graphics/Traffic/AirportsServicesQuantity": 3, "Graphics/Characters/Quantity": 3}
PROFILES = {
    "deck": dict(gpu="AMD Custom GPU 0405 (Van Gogh)", vram_gb=4.0, cpu="AMD Custom APU 0405", cores=4, threads=8, ram_gb=16, width=1280, height=800, integrated=True),
    "mid": dict(m.DEMO_HW),
    "high": dict(gpu="NVIDIA GeForce RTX 4090", vram_gb=24.0, cpu="AMD Ryzen 7 7800X3D", cores=8, threads=16, ram_gb=64, width=3840, height=2160),
    "oldcpu": dict(gpu="NVIDIA GeForce RTX 4070", vram_gb=12.0, cpu="Intel Core i5-4590", cores=4, threads=4, ram_gb=16, width=1920, height=1080),
}
PHRASES = {  # phrase (with typos) -> expected problem id
    "my sim studders at busy airprots": "stutter", "stuttering everywhere": "stutter", "it hitches every few seconds": "stutter",
    "fps is terrible": "low_fps", "low frame rate in cruise": "low_fps", "the framerate is bad": "low_fps",
    "everything looks blury": "blurry", "cockpit text is fuzzy": "blurry", "trees pop in late": "popin",
    "buildings appear late": "popin", "the sim craches to desktop": "crash", "CTD on approach": "crash",
    "problems since the update": "after_update", "after SU2 it's worse": "after_update",
}

class Offline(unittest.TestCase):
    def test_phrases_detected_with_typos(self):
        for ph, pid in PHRASES.items():
            self.assertIn(pid, m.detect_problems(ph), ph)
    def test_phrases_by_profiles_give_fixes(self):
        for name, hw in PROFILES.items():
            for ph, pid in PHRASES.items():
                d = m.assistant_diagnose(ph, hw, HEAVY)
                self.assertTrue(d["fixes"], (name, ph)); self.assertIn(d["confidence"], ("High", "Medium", "Low"))
                for f in d["fixes"]:
                    self.assertIn(f["impact"], ("High", "Med", "Low")); self.assertTrue(f["cost"])
                    self.assertTrue(f["changes"] or f["tool"], f["id"])
                    for k, v in f["changes"].items():   # never increases load when the problem is performance
                        if pid in ("low_fps",) and isinstance(v, (int, float)) and k in HEAVY and "Texture/Quality" not in k and "PreCaching" not in k and "FrameLimiter" not in k:
                            self.assertLessEqual(v, HEAVY[k], (name, ph, k))
    def test_nonsense(self):
        d = m.assistant_diagnose("hello there", PROFILES["mid"], HEAVY)
        self.assertEqual(d["fixes"], []); self.assertEqual(d["problems"], []); self.assertIn("quick buttons", d["message"])

class Diagnosis(unittest.TestCase):
    def test_airport_stutter_is_cpu(self):
        d = m.assistant_diagnose("stutters at busy airports", PROFILES["oldcpu"], HEAVY)
        self.assertEqual(d["bottleneck"], "CPU"); self.assertEqual(d["confidence"], "High")
    def test_cruise_low_fps_is_gpu(self):
        d = m.assistant_diagnose("low fps in cruise", PROFILES["high"], HEAVY)
        self.assertEqual(d["bottleneck"], "GPU")
        self.assertIn(d["fixes"][0]["id"], ("clouds_down", "shadows_down", "render_scale_down"))
    def test_vram_textures(self):
        d = m.assistant_diagnose("stutters after a long flight", PROFILES["mid"], HEAVY)
        self.assertEqual(d["bottleneck"], "VRAM"); self.assertEqual(d["fixes"][0]["id"], "textures_fit")
        self.assertEqual(d["fixes"][0]["changes"], {"Graphics/Texture/Quality": 1})
    def test_update_crash_is_addons(self):
        d = m.assistant_diagnose("crashes since the sim update", PROFILES["mid"], HEAVY)
        self.assertEqual(d["bottleneck"], "Add-ons"); self.assertEqual(d["fixes"][0]["tool"], "update_cleanup")
    def test_after_update_stutter_is_cache(self):
        d = m.assistant_diagnose("stutters since a driver update", PROFILES["high"], {})
        self.assertEqual(d["bottleneck"], "Cache"); self.assertEqual(d["fixes"][0]["tool"], "fix_stutters")
    def test_uses_cfg_values(self):
        light = dict(HEAVY, **{"Graphics/ObjectsLoD/LoDFactor": 0.8, "Graphics/Terrain/LoDFactor": 0.8})
        ids = lambda c: [f["id"] for f in m.assistant_diagnose("stutters at airports", PROFILES["mid"], c)["fixes"]]
        self.assertIn("lower_olod", ids(HEAVY)); self.assertNotIn("lower_olod", ids(light))
    def test_followups_and_history(self):
        d = m.assistant_diagnose("it stutters", PROFILES["mid"], HEAVY)
        self.assertEqual([s for s, _, _ in d["followups"]], ["where", "when"])
        d2 = m.assistant_diagnose("", PROFILES["mid"], HEAVY, ctx={"where": "airport"}, history=["it stutters"])
        self.assertIn("stutter", d2["problems"]); self.assertEqual(d2["bottleneck"], "CPU")
        self.assertNotIn("where", [s for s, _, _ in d2["followups"]])
    def test_chip_symptom_adds_problem(self):
        d = m.assistant_diagnose("", PROFILES["mid"], HEAVY, ctx={"symptom": "late"})
        self.assertIn("popin", d["problems"])
    def test_ranked_and_capped(self):
        d = m.assistant_diagnose("stutters and low fps at busy airports", PROFILES["oldcpu"], HEAVY)
        sc = [f["score"] for f in d["fixes"]]; self.assertEqual(sc, sorted(sc, reverse=True)); self.assertLessEqual(len(sc), 6)

class LockedPrefs(unittest.TestCase):
    def all_keys(self, d): return {k for f in d["fixes"] for k in f["changes"]}
    def test_prefs_untouched_unless_asked(self):
        for ph in PHRASES:
            for hw in PROFILES.values():
                keys = self.all_keys(m.assistant_diagnose(ph, hw, HEAVY))
                self.assertFalse(keys & {"Video/AntiAliasing", "Video/DLSSMode", "Video/FrameGeneration", "Video/NBFramesToGenerate"}, ph)
                self.assertFalse(keys & {p for p, _, _ in m.TRAFFIC_CATS}, ph)
    def test_asked_unlocks(self):
        self.assertIn("Graphics/Traffic/AircraftTrafficQuantity", self.all_keys(m.assistant_diagnose("AI traffic makes it stutter at the airport", PROFILES["mid"], HEAVY)))
        self.assertIn("Video/FrameGeneration", self.all_keys(m.assistant_diagnose("crashes with frame gen on", PROFILES["mid"], HEAVY)))
        self.assertIn("Video/DLSSMode", self.all_keys(m.assistant_diagnose("DLSS looks blurry", PROFILES["mid"], HEAVY)))
    def test_unlocked_traffic_when_skytune_decides(self):
        d = m.assistant_diagnose("stutters at busy airports", PROFILES["mid"], HEAVY, locked=("aa", "fg"))
        self.assertIn("traffic_down", [f["id"] for f in d["fixes"]])

class Feedback(unittest.TestCase):
    def setUp(self):
        self.d = m.assistant_diagnose("stutters at busy airports", PROFILES["oldcpu"], HEAVY); self.s = m.FixSession(self.d)
    def test_worse_undoes_and_suggests_next(self):
        f = self.s.stage(self.s.next_fix()); self.s.applied("/tmp/backup.opt")
        r = self.s.feedback("worse")
        if f["tool"]: self.assertEqual(r["action"], "none")
        else: self.assertEqual((r["action"], r["undo"]), ("undo", "/tmp/backup.opt"))
        self.assertIsNotNone(r["next"]); self.assertNotEqual(r["next"]["id"], f["id"])
    def test_worse_on_settings_fix(self):
        f = next(x for x in self.d["fixes"] if not x["tool"]); self.s.stage(f); self.s.applied("B")
        r = self.s.feedback("Worse"); self.assertEqual(r["undo"], "B"); self.assertIn("Undone", r["message"])
    def test_same_keeps_and_moves_on(self):
        f1 = self.s.stage(self.s.next_fix()); self.s.applied("B"); r = self.s.feedback("same")
        self.assertEqual(r["action"], "keep"); self.assertIsNone(r["undo"]); self.assertNotEqual(r["next"]["id"], f1["id"])
    def test_better_finishes(self):
        self.s.stage(self.s.next_fix()); r = self.s.feedback("better")
        self.assertTrue(self.s.done); self.assertIsNone(r["next"])
    def test_runs_out(self):
        while self.s.next_fix(): self.s.stage(self.s.next_fix())
        self.assertIsNone(self.s.feedback("same")["next"])
        self.assertRaises(ValueError, self.s.feedback, "meh")

class Whitelist(unittest.TestCase):
    def setUp(self): self.wl = m.ai_whitelist(HEAVY)
    def test_only_present_and_unlocked(self):
        self.assertIn("Graphics/Terrain/LoDFactor", self.wl); self.assertNotIn("Video/FrameGeneration", self.wl)
        self.assertNotIn("Graphics/Traffic/AircraftTrafficQuantity", self.wl); self.assertNotIn("Graphics/Water/FFTSize", self.wl)
        self.assertIn("Video/FrameGeneration", m.ai_whitelist(HEAVY, asked={"fg"}))
    def test_validation(self):
        ch, rej = m.validate_ai_changes({"Graphics/Terrain/LoDFactor": 1.23, "Graphics/Texture/Quality": "1", "Graphics/Shadows/Size": 999,
                                         "Video/FrameGeneration": "NONE", "Evil/Key": 1, "Graphics/ObjectsLoD/LoDFactor": 99,
                                         "Graphics/VolumetricClouds/Quality": True, "Video/FrameLimiter": "abc"}, self.wl)
        self.assertEqual(ch, {"Graphics/Terrain/LoDFactor": 1.25, "Graphics/Texture/Quality": 1, "Graphics/VolumetricClouds/Quality": 1})
        self.assertEqual(len(rej), 5)
    def test_parse_reply(self):
        good = json.dumps({"bottleneck": "CPU", "confidence": "High", "summary": "CPU.", "fixes": [
            {"title": "Lower OLOD", "why": "x", "impact": "high", "cost": "pop", "changes": {"Graphics/ObjectsLoD/LoDFactor": 0.8}},
            {"title": "bad", "changes": {"Video/FrameGeneration": "NONE"}}]})
        r = m.parse_ai_reply("```json\n%s\n```" % good, self.wl)
        self.assertEqual(len(r["fixes"]), 1); self.assertEqual(r["fixes"][0]["impact"], "High")
        for bad in ("Sure! here you go", "[]", json.dumps({"fixes": []}), json.dumps({"fixes": [{"changes": {"X/Y": 1}}]})):
            self.assertRaises(ValueError, m.parse_ai_reply, bad, self.wl)
    def test_base_url(self):
        self.assertTrue(m.valid_base_url("https://api.openai.com/v1")); self.assertTrue(m.valid_base_url("http://localhost:1234/v1"))
        self.assertFalse(m.valid_base_url("http://evil.example/v1")); self.assertFalse(m.valid_base_url("file:///etc/passwd"))

class Mock(http.server.BaseHTTPRequestHandler):
    reply = None; delay = 0; seen = []
    def log_message(self, *a): pass
    def do_POST(self):
        import time
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Mock.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body)); time.sleep(Mock.delay)
        if Mock.reply is None: self.send_response(500); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(Mock.reply(self.path)).encode())

class AIMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Mock)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_port
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self): Mock.seen.clear(); Mock.delay = 0
    CONTENT = json.dumps({"bottleneck": "GPU", "confidence": "Medium", "summary": "Your GPU is busy.",
                          "fixes": [{"title": "Lighter clouds", "why": "heavy", "impact": "High", "cost": "clouds",
                                     "changes": {"Graphics/VolumetricClouds/Quality": 1, "Video/FrameGeneration": "NONE"}}]})
    def run_ai(self, provider="openai", **kw):
        return m.ai_diagnose("low fps in cruise", ["earlier msg"], PROFILES["mid"], HEAVY, edition="2024", key="sk-test",
                             provider=provider, base_url=self.base + ("/v1" if provider == "openai" else ""), model="test-model", **kw)
    def test_openai_compatible(self):
        Mock.reply = lambda p: {"choices": [{"message": {"content": self.CONTENT}}]}
        d = self.run_ai()
        self.assertEqual(d["source"], "ai"); self.assertEqual(d["bottleneck"], "GPU")
        self.assertEqual(d["fixes"][0]["changes"], {"Graphics/VolumetricClouds/Quality": 1})   # FG stripped by whitelist
        path, headers, body = Mock.seen[0]
        self.assertEqual(path, "/v1/chat/completions"); self.assertEqual(headers["authorization"], "Bearer sk-test")
        self.assertEqual(body["model"], "test-model")
        sent = json.loads(body["messages"][1]["content"])
        self.assertEqual(set(sent), {"problem", "earlier_messages", "context", "goal", "simulator", "hardware", "offline_diagnosis",
                                     "allowed_keys", "current_values"})
        self.assertNotIn("Video/FrameGeneration", sent["allowed_keys"]); self.assertNotIn("errors", sent["hardware"])
        self.assertNotIn("vram_src", json.dumps(sent)); self.assertNotIn("Users", json.dumps(sent))
    def test_anthropic(self):
        Mock.reply = lambda p: {"content": [{"type": "text", "text": self.CONTENT}]}
        d = self.run_ai("anthropic")
        self.assertEqual(d["source"], "ai"); path, headers, body = Mock.seen[0]
        self.assertEqual(path, "/v1/messages"); self.assertEqual(headers["x-api-key"], "sk-test"); self.assertIn("system", body)
    def test_fallback_on_http_error(self):
        Mock.reply = None; d = self.run_ai()
        self.assertEqual(d["source"], "offline"); self.assertEqual(d["fallback_reason"], "HTTP 500"); self.assertTrue(d["fixes"])
    def test_fallback_on_bad_json(self):
        Mock.reply = lambda p: {"choices": [{"message": {"content": "I think you should lower clouds."}}]}
        d = self.run_ai(); self.assertEqual(d["source"], "offline"); self.assertIn("JSON", d["fallback_reason"])
    def test_fallback_on_timeout(self):
        Mock.reply = lambda p: {"choices": [{"message": {"content": self.CONTENT}}]}; Mock.delay = 1.5
        d = self.run_ai(timeout=0.4); self.assertEqual(d["source"], "offline"); self.assertEqual(d["fallback_reason"], "timed out")
    def test_fallback_without_key_or_server(self):
        d = m.ai_diagnose("stutters", hw=PROFILES["mid"], cfg=HEAVY, key=None); self.assertEqual(d["fallback_reason"], "no API key saved")
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        d = m.ai_diagnose("stutters", hw=PROFILES["mid"], cfg=HEAVY, key="k", base_url="http://127.0.0.1:%d/v1" % port)
        self.assertEqual(d["source"], "offline"); self.assertTrue(d["fallback_reason"])
        d = m.ai_diagnose("stutters", hw=PROFILES["mid"], cfg=HEAVY, key="k", base_url="http://example.com/v1")
        self.assertIn("https", d["fallback_reason"])

class Storage(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.env = {"HOME": self.home}
    def test_prefs_roundtrip_and_merge(self):
        p = os.path.join(self.home, "state.json")
        m.save_state({"first_launch_done": True}, p)
        self.assertTrue(m.save_prefs({"goal": "Smooth & steady", "aa": "AMD FSR", "fg": "AMD FSR", "traffic": "Low", "prefs_open": True}, p))
        pr = m.load_prefs(p)
        self.assertEqual((pr["goal"], pr["aa"], pr["fg"], pr["traffic"], pr["prefs_open"]), ("Smooth & steady", "AMD FSR", "AMD FSR", "Low", True))
        self.assertTrue(m.load_state(p)["first_launch_done"])
        m.save_prefs({"goal": "Balanced"}, p); self.assertEqual(m.load_prefs(p)["aa"], "AMD FSR")
    def test_bad_prefs_fall_back(self):
        p = os.path.join(self.home, "state.json")
        with open(p, "w") as f: json.dump({"prefs": {"goal": "Turbo", "aa": 5, "traffic": "Low", "ai_base_url": "http://evil.example"}}, f)
        pr = m.load_prefs(p); self.assertEqual((pr["goal"], pr["aa"], pr["traffic"], pr["ai_base_url"]), ("Balanced", "TAA", "Low", ""))
        with open(p, "w") as f: f.write("{broken")
        self.assertEqual(m.load_prefs(p), m.PREF_DEFAULTS)
    def test_key_plain_file(self):
        self.assertEqual(m.config_dir(self.env), os.path.join(self.home, ".config", "SkyTune"))
        self.assertEqual(m.load_api_key(self.env), (None, None))
        self.assertEqual(m.save_api_key(" sk-abc ", self.env), "plain")
        self.assertEqual(m.load_api_key(self.env), ("sk-abc", "plain"))
        if os.name != "nt": self.assertEqual(os.stat(os.path.join(self.home, ".config", "SkyTune", "api_key.txt")).st_mode & 0o777, 0o600)
        self.assertTrue(m.remove_api_key(self.env)); self.assertEqual(m.load_api_key(self.env), (None, None))
        self.assertFalse(m.remove_api_key(self.env))
        self.assertRaises(ValueError, m.save_api_key, "has space", self.env)
    def test_appdata_location(self):
        self.assertEqual(m.config_dir({"APPDATA": self.home}), os.path.join(self.home, "SkyTune"))
    def test_no_key_shipped(self):
        with open(m.__file__, encoding="utf-8") as f: src = f.read()
        import re
        self.assertFalse(re.search(r"sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9]", src))

if __name__ == "__main__":
    unittest.main()
