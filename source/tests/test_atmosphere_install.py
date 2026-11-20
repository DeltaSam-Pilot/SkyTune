"""AtmosphereMod is an opt-in download. The install record can be undone, and other packages stay put."""
import io, os, shutil, tempfile, unittest, zipfile
import msfs_tweaker as m

def _zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("AtmosphereMod-1.0/payload/AtmosphereMod.addon64", b"new-addon")
        archive.writestr("AtmosphereMod-1.0/payload/tunables.ini", b"haze=1\n")
        archive.writestr("AtmosphereMod-1.0/payload/efb/atmospheremod-weather/manifest.json", b"{}")
        archive.writestr("AtmosphereMod-1.0/Install AtmosphereMod.cmd", b"echo no\n")
        archive.writestr("AtmosphereMod-1.0/installer/install.py", b"print('no')\n")
    return buf.getvalue()

class AtmosphereInstall(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.exe = os.path.join(self.d, "sim")
        self.community = os.path.join(self.d, "Community")
        self.local = os.path.join(self.d, "Local")
        os.makedirs(self.exe)
        kept = os.path.join(self.community, "fsdreamteam-gsx-pro")
        os.makedirs(kept)
        with open(os.path.join(kept, "readme.txt"), "wb") as handle:
            handle.write(b"KEEP")
        with open(os.path.join(self.exe, "AtmosphereMod.addon64"), "wb") as handle:
            handle.write(b"OLD")
        self.record = {"mods": []}
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
    def test_release_asset_is_the_authors_zip(self):
        spec = m.official_mod("atmosphere")
        self.assertEqual(spec["author"], "tomwhoca")
        self.assertIn("LICENSE", spec["licence"])
        release = {"assets": [{"name": "source.zip", "size": 1}, {"name": "AtmosphereMod-1.2.3.zip", "size": 9}]}
        self.assertEqual(m.choose_release_asset("atmosphere", release)["name"], "AtmosphereMod-1.2.3.zip")
    def test_install_records_files_and_leaves_other_packages(self):
        before = open(os.path.join(self.community, "fsdreamteam-gsx-pro", "readme.txt"), "rb").read()
        result = m.install_atmosphere_payload(_zip(), self.exe, self.community, self.local, self.record, "v1.2.3")
        self.assertTrue(result["ok"], result)
        self.assertEqual(open(os.path.join(self.exe, "AtmosphereMod.addon64"), "rb").read(), b"new-addon")
        self.assertEqual(open(os.path.join(self.exe, "AtmosphereMod.addon64.skytune-backup"), "rb").read(), b"OLD")
        self.assertTrue(os.path.isfile(os.path.join(self.community, "atmospheremod-weather", "manifest.json")))
        self.assertEqual(open(os.path.join(self.community, "fsdreamteam-gsx-pro", "readme.txt"), "rb").read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.community, "install.py")))
        paths = [item["path"] for item in self.record["mods"][0]["files"]]
        self.assertIn(os.path.join(self.exe, "AtmosphereMod.addon64"), paths)
        self.assertTrue(any(path.endswith("manifest.json") for path in paths))
    def test_uninstall_restores_the_backup_only(self):
        m.install_atmosphere_payload(_zip(), self.exe, self.community, self.local, self.record, "v1.2.3")
        result = m.uninstall_managed_mod(self.record, "atmosphere")
        self.assertTrue(result["ok"], result)
        self.assertEqual(open(os.path.join(self.exe, "AtmosphereMod.addon64"), "rb").read(), b"OLD")
        self.assertFalse(os.path.exists(os.path.join(self.exe, "AtmosphereMod.addon64.skytune-backup")))
        self.assertFalse(os.path.exists(os.path.join(self.community, "atmospheremod-weather", "manifest.json")))
        self.assertEqual(open(os.path.join(self.community, "fsdreamteam-gsx-pro", "readme.txt"), "rb").read(), b"KEEP")
        self.assertEqual(self.record["mods"], [])
    def test_a_bad_checksum_installs_nothing(self):
        asset = {"size": 4, "digest": "sha256:" + "0" * 64}
        self.assertIsNotNone(m.verify_download(b"nope", asset))
    def test_clash_warning_still_sees_the_addon(self):
        with open(os.path.join(self.exe, "FlightSimulator2024.exe"), "wb") as handle:
            handle.write(b"")
        found = m.find_graphics_mods(edition="2024", program_dirs=[self.exe], community=self.community, env={})
        self.assertIn("atmosphere", [item["id"] for item in found])
