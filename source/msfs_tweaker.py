#!/usr/bin/env python3
"""SkyTune for Microsoft Flight Simulator 2020/2024 and compatible UserCfg files.
Standard library only (Tkinter UI). Only settings already present in a selected config are edited.
"""
import os, re, sys, shutil, subprocess, datetime, glob, time, errno, tempfile
import json
# v1.3.2: network / encoding / fuzzy-match modules load on first use (faster start-up). The explicit imports in the
# loaders keep PyInstaller's analysis working.
class _Lazy:
    def __init__(self, loader): self.__dict__["_loader"], self.__dict__["_mod"] = loader, None
    def _get(self):
        if self.__dict__["_mod"] is None: self.__dict__["_mod"] = self.__dict__["_loader"]()
        return self.__dict__["_mod"]
    def __getattr__(self, a): return getattr(self._get(), a)
    def __setattr__(self, a, v): setattr(self._get(), a, v)
def _imp_urllib():
    import urllib.request, urllib.parse, urllib.error
    return urllib
def _imp_base64():
    import base64
    return base64
def _imp_difflib():
    import difflib
    return difflib
def _imp_socket():
    import socket
    return socket
urllib, base64, difflib, socket = _Lazy(_imp_urllib), _Lazy(_imp_base64), _Lazy(_imp_difflib), _Lazy(_imp_socket)

APP_NAME = "SkyTune for MSFS 2020/2024"
SHORT_NAME = "SkyTune"
VERSION = "1.8.0"
# The other entry point may set EXTRA before the window opens. This file does not name that build.
EXTRA = None
SIM_PROCESS = "FlightSimulator2024.exe"
SIM_PROCESSES = ("FlightSimulator2024.exe", "FlightSimulator.exe")

# ---------------------------------------------------------------- locations
STEAM_APP_ID = "2537590"          # MSFS 2024 on Steam
STEAM_APP_ID_2020 = "1250410"     # MSFS 2020 on Steam
STORE_PKG = "Microsoft.Limitless_8wekyb3d8bbwe"
STORE_PKG_2020 = "Microsoft.FlightSimulator_8wekyb3d8bbwe"
# (version, label, Steam app id, roaming folder name, Store package)
SIMULATOR_PROFILES = (
    ("2024", "MSFS 2024", STEAM_APP_ID, "Microsoft Flight Simulator 2024", STORE_PKG),
    ("2020", "MSFS 2020", STEAM_APP_ID_2020, "Microsoft Flight Simulator", STORE_PKG_2020),
)

def _win_dirs(env=None):
    """APPDATA / LOCALAPPDATA with fallbacks when the variables are missing (unicode-safe)."""
    env = os.environ if env is None else env
    home = env.get("USERPROFILE") or os.path.expanduser("~")
    return (env.get("APPDATA") or os.path.join(home, "AppData", "Roaming"),
            env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"))

def steam_roots(home=None):
    """Common native Steam, Debian/Ubuntu, Flatpak and Snap roots on Linux/SteamOS."""
    home = home or os.path.expanduser("~")
    return [os.path.join(home, *p) for p in ((".steam", "steam"), (".local", "share", "Steam"), (".steam", "debian-installation"),
            (".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"), ("snap", "steam", "common", ".local", "share", "Steam"))]

def steam_libraries(home=None):
    """All Steam library folders (each has steamapps/), from libraryfolders.vdf, de-duplicated."""
    libs, seen = [], set()
    for r in steam_roots(home):
        cands = [r]
        try:
            with open(os.path.join(r, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="replace") as f:
                cands += [x.replace("\\\\", "\\") for x in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError: pass
        for c in cands:
            if not os.path.isdir(os.path.join(c, "steamapps")): continue
            k = os.path.realpath(c)
            if k not in seen: seen.add(k); libs.append(c)
    return libs

def proton_users(home=None, app_id=STEAM_APP_ID):
    """Windows user folders inside a Steam game's Proton prefix; 'steamuser' is listed first."""
    out = []
    for lib in steam_libraries(home):
        u = os.path.join(lib, "steamapps", "compatdata", str(app_id), "pfx", "drive_c", "users")
        try: names = sorted(os.listdir(u), key=lambda n: (n.lower() != "steamuser", n.lower()))
        except OSError: continue
        out += [(lib, os.path.join(u, n)) for n in names if n.lower() != "public" and os.path.isdir(os.path.join(u, n))]
    return out

def proton_profiles(home=None):
    """Candidate UserCfg locations for both Steam editions under all known Proton prefixes."""
    out = []
    for version, label, app_id, roaming_folder, _pkg in SIMULATOR_PROFILES:
        for _lib, user in proton_users(home, app_id):
            path = os.path.join(user, "AppData", "Roaming", roaming_folder, "UserCfg.opt")
            out.append(("%s Steam (Proton)" % label, path))
    return out

def linux_env(home=None, game_version=None):
    """Environment-like cache roots for the best matching Proton prefix."""
    home = home or os.path.expanduser("~")
    profiles = []
    for version, _label, app_id, roaming_folder, _pkg in SIMULATOR_PROFILES:
        if game_version and version != str(game_version): continue
        for lib, user in proton_users(home, app_id):
            cfg = os.path.join(user, "AppData", "Roaming", roaming_folder, "UserCfg.opt")
            profiles.append((version, lib, user, cfg))
    pick = next((x for x in profiles if os.path.isfile(x[3])), profiles[0] if profiles else (None, None, None, None))
    _version, lib, user, _cfg = pick
    xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    env = {"XDGCACHE": xdg, "STEAMLIB": lib or ""}
    if user: env.update(APPDATA=os.path.join(user, "AppData", "Roaming"), LOCALAPPDATA=os.path.join(user, "AppData", "Local"))
    return env

def candidate_paths(home=None, env=None):
    """Discover MSFS 2020 and 2024 Steam/Store config paths, plus both Proton editions on Linux."""
    env = os.environ if env is None else env
    if os.name != "nt" and not env.get("APPDATA"):
        return proton_profiles(home)
    appdata, local = _win_dirs(env)
    return [
        ("MSFS 2024 · Steam", os.path.join(appdata, "Microsoft Flight Simulator 2024", "UserCfg.opt")),
        ("MSFS 2024 · MS Store / Xbox", os.path.join(local, "Packages", STORE_PKG, "LocalCache", "UserCfg.opt")),
        ("MSFS 2020 · Steam", os.path.join(appdata, "Microsoft Flight Simulator", "UserCfg.opt")),
        ("MSFS 2020 · MS Store / Xbox", os.path.join(local, "Packages", STORE_PKG_2020, "LocalCache", "UserCfg.opt")),
    ]

def detect_usercfgs(home=None, env=None):
    """Return every existing supported config in priority order, including installations side by side."""
    found, seen = [], set()
    for label, path in candidate_paths(home, env):
        key = os.path.normcase(os.path.abspath(path)) if path else None
        if path and key not in seen and os.path.isfile(path):
            seen.add(key); found.append((label, path))
    remembered = remembered_cfg()
    if isinstance(remembered, str) and remembered and os.path.isfile(remembered):
        key = os.path.normcase(os.path.abspath(remembered))
        if key not in seen:
            found.append(("Saved location", remembered))
    return found

def detect_usercfg():
    found = detect_usercfgs()
    return found[0] if found else (None, None)

def detect_simulator_version(path, cfg=None):
    """Infer the edition from the config path first, then distinctive schema keys.

    Unknown/future schemas remain editable through Browse, but SkyTune only writes existing known keys.
    """
    norm = os.path.normpath(str(path or "")).lower().replace("\\", "/")
    if "microsoft flight simulator 2024" in norm or "microsoft.limitless_8wekyb3d8bbwe" in norm or "/2537590/" in norm:
        return "2024"
    if "microsoft flight simulator" in norm or "microsoft.flightsimulator_8wekyb3d8bbwe" in norm or "/1250410/" in norm:
        return "2020"
    if cfg is None and path and os.path.isfile(path):
        try: cfg = UserCfg.load(path)
        except Exception: cfg = None
    keys = cfg.index if cfg else {}
    if "Video/FrameGeneration" in keys or "Graphics/DisplacementMapping/Enabled" in keys or "Graphics/Procedural/TreesQuality" in keys:
        return "2024"
    if "Video/DLSSG" in keys or "Graphics/SSRaytracedShadows/Enabled" in keys or "Graphics/VegetationLarge/Quality" in keys:
        return "2020"
    return "unknown"

def cfg_problem(path):
    """None if the selected config is usable; otherwise a plain-English failure reason."""
    if not path or not os.path.isfile(path): return "missing"
    try:
        if os.path.getsize(path) == 0: return "empty"
        cfg = UserCfg.load(path)
    except Exception as e:
        return "damaged (%s)" % e
    if not any(k.startswith("Graphics/") for k in cfg.index) or not any(k.startswith("Video/") for k in cfg.index):
        return "damaged (no {Graphics} / {Video} sections)"
    return None

def open_folder(path):
    """Open a folder using the host platform's default file manager when possible."""
    try:
        if os.name == "nt": os.startfile(path); return
        if sys.platform == "darwin": subprocess.Popen(["open", path]); return
        subprocess.Popen(["xdg-open", path])
    except Exception: pass

def _win_process_names():
    """Image names of running processes from one Toolhelp snapshot (v1.3.2: no tasklist child process, ~1 ms)."""
    import ctypes
    from ctypes import wintypes
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PE))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.CreateToolhelp32Snapshot(0x2, 0)                  # TH32CS_SNAPPROCESS
    if not h or h == ctypes.c_void_p(-1).value: raise OSError("process snapshot failed")
    names = []
    try:
        e = PE(); e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(h, ctypes.byref(e))
        while ok:
            names.append(e.szExeFile); ok = k32.Process32NextW(h, ctypes.byref(e))
    finally:
        k32.CloseHandle(h)
    return names

def _tasklist_names():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), errors="replace").stdout or ""
    return [ln.split('","')[0].strip('"') for ln in out.splitlines() if ln.startswith('"')]

def _proc_cmdlines(root="/proc"):
    """Linux/Proton: command line of every process (the sim shows up as ...\\FlightSimulator2024.exe)."""
    out = []
    for pid in os.listdir(root):
        if not pid.isdigit(): continue
        try:
            with open(os.path.join(root, pid, "cmdline"), "rb") as f: raw = f.read(4096)
        except OSError: continue
        if raw: out.append(raw.replace(b"\0", b" ").decode("utf-8", "replace"))
    return out

def process_names():
    """Running process names (Windows) or command lines (Linux), or None if they can't be read. v1.3.2: one cheap
    snapshot instead of a tasklist/pgrep child process every few seconds."""
    try:
        if os.name == "nt":
            try: return _win_process_names()
            except Exception: return _tasklist_names()
        if os.path.isdir("/proc"): return _proc_cmdlines()
        out = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True, timeout=5).stdout
        return out.splitlines()[1:]
    except Exception:
        return None

def names_running(names, wanted):
    """True if any of `wanted` (exe names) is in `names` (from process_names)."""
    if names is None: return None
    want = [w.lower() for w in wanted]
    if os.name == "nt":
        have = {n.lower() for n in names}
        return any(w in have for w in want)
    return any(w in n.lower() for n in names for w in want)

def sim_running():
    """True if either MSFS 2020 or MSFS 2024 is running, False if neither, None if unknown."""
    return names_running(process_names(), SIM_PROCESSES)

# ---------------------------------------------------------------- parser
_LINE = re.compile(r'^(\s*)(\S+)(\s+)(.*?)(\s*)$')

def decode_cfg_bytes(data):
    """Return (text, encoding). UTF-16 and UTF-8 byte-order marks are recognised. Anything else is UTF-8."""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", "surrogateescape"), "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", "surrogateescape"), "utf-16-be"
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "surrogateescape"), "utf-8-sig"
    return data.decode("utf-8", "surrogateescape"), "utf-8"

def atomic_write(path, data):
    """Write bytes via a temp file in the same folder, flush it, then replace. A crash keeps the old file or the new one, not a half-written file."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".skytune-", dir=directory)
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(tmp, path)
        tmp = None
        try:
            dirfd = os.open(directory, os.O_RDONLY)
            try: os.fsync(dirfd)
            finally: os.close(dirfd)
        except OSError:
            pass
    finally:
        if fd is not None:
            try: os.close(fd)
            except OSError: pass
        if tmp:
            try: os.remove(tmp)
            except OSError: pass

def write_blocked(path):
    """A plain sentence when a settings write must not start, or None when it is safe to try."""
    if not path:
        return "Choose your UserCfg.opt first. Click Find file, or Browse and pick the file."
    if not os.path.isfile(path):
        return "UserCfg.opt isn't there. Start the simulator, reach the main menu, quit, then click Find file. Or use Browse if the sim lives in a custom folder."
    parent = os.path.dirname(os.path.abspath(path)) or "."
    if not os.access(parent, os.W_OK):
        return "SkyTune can't save a backup next to that file because the folder is read-only. Nothing was written."
    if not os.access(path, os.W_OK):
        return "That settings file is read-only. Close the simulator, allow changes to the file, and try again. Nothing was written."
    try:
        fd = os.open(path, os.O_RDWR)
    except PermissionError:
        return "That settings file is open in another program. Close the simulator and try again. Nothing was written."
    except OSError as e:
        if getattr(e, "errno", None) in (errno.EACCES, errno.EPERM, errno.EBUSY, errno.ETXTBSY):
            return "That settings file is open in another program. Close the simulator and try again. Nothing was written."
    else:
        os.close(fd)
    return None

def restore_blocked(path):
    """A plain sentence when a restore must not start, or None. A missing file can be recreated."""
    if not path:
        return "Choose your UserCfg.opt first."
    parent = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(parent):
        return "The folder for that settings file isn't there. Nothing was changed."
    if not os.access(parent, os.W_OK):
        return "SkyTune can't write in that folder. Nothing was changed."
    if not os.path.isfile(path):
        return None
    return write_blocked(path)

def plain_error(exc):
    """One sentence for a dialog. Never a stack trace."""
    text = str(exc or "").strip()
    first = text.splitlines()[0] if text else ""
    if not first or "Traceback" in text or first.startswith("[Errno"):
        return "Something went wrong, and nothing was written. Close the simulator and try again."
    return first[:400]

HELP_PAGES = (
    ("Start", "SkyTune works in three steps.\n\n1. Close the simulator. Click Find file, or Browse if your install is in a custom folder.\n2. Click Check my PC, then pick Best visuals, Balanced, or Smooth & steady.\n3. Read the list in Step 3. Click Optimise, then Yes, write. Cancel leaves the file alone."),
    ("Where the file lives", "MSFS 2020 and MSFS 2024 each keep a UserCfg.opt. Steam and the Microsoft Store use different folders, and SkyTune looks in the usual places for both. A file you pick with Browse is remembered on this PC."),
    ("If a write cannot finish", "A missing file, a read-only file, or a file the simulator still has open is left as it is. Close the simulator and try again. A successful write is checked in a temporary file and then put in place, so a power cut cannot leave a half-written settings file."),
    ("Why a setting was suggested", "Step 3 gives a one-line reason for each change, using video memory, graphics-card tier, processor cores, and screen refresh when those could be read. The list is only a suggestion. Nothing is written until you click Yes, write."),
    ("Safety", "SkyTune is unsigned. Download it only from the official Flightsim.to page. Changing settings is at your own risk: SkyTune backs up your file before every write, and you should keep a copy of your own as well. Results depend on your hardware, so frame rates are not guaranteed. SkyTune is a free, independent community project, not affiliated with or endorsed by Microsoft or Asobo Studio."),
)

class UserCfg:
    """Line-preserving parser. Only lines whose value is changed are rewritten;
    everything else (whitespace, CRLF, ordering, unknown keys) is byte-identical."""
    def __init__(self, text):
        self.encoding = "utf-8"
        lone = text.replace("\r\n", "")
        if "\r" in lone and "\n" not in lone:
            self.newline = "\r"
            self.lines = text.split("\r")
        elif "\r" in lone or ("\n" in lone and "\r\n" in text):
            crlf, cr, lf = text.count("\r\n"), lone.count("\r"), lone.count("\n")
            self.newline = "\r\n" if crlf >= cr and crlf >= lf else ("\r" if cr > lf else "\n")
            self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        else:
            self.newline = "\r\n" if "\r\n" in text else "\n"
            self.lines = text.split(self.newline)
        self.index = {}      # "Graphics/Terrain/LoDFactor" -> line idx
        self._parse()

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            data = f.read()
        text, enc = decode_cfg_bytes(data)
        cfg = cls(text)
        cfg.encoding = enc
        return cfg

    def encoded(self):
        text = self.text()
        enc = getattr(self, "encoding", "utf-8") or "utf-8"
        if enc == "utf-16-le":
            return b"\xff\xfe" + text.encode("utf-16-le", "surrogateescape")
        if enc == "utf-16-be":
            return b"\xfe\xff" + text.encode("utf-16-be", "surrogateescape")
        if enc == "utf-8-sig":
            return b"\xef\xbb\xbf" + text.encode("utf-8", "surrogateescape")
        return text.encode("utf-8", "surrogateescape")

    def _parse(self):
        stack = []
        for i, raw in enumerate(self.lines):
            s = raw.strip()
            if not s:
                continue
            if s.startswith("{"):
                stack.append(s[1:].strip())
            elif s == "}":
                if not stack:
                    raise ValueError("Unbalanced '}' at line %d" % (i + 1))
                stack.pop()
            else:
                m = _LINE.match(raw)
                key = m.group(2) if m else s
                self.index["/".join(stack + [key])] = i
        if stack:
            raise ValueError("Unclosed block(s): " + "/".join(stack))

    def get(self, path):
        i = self.index.get(path)
        if i is None:
            return None
        m = _LINE.match(self.lines[i])
        return m.group(4) if m else ""

    def set(self, path, value):
        i = self.index.get(path)
        if i is None:
            raise KeyError(path)
        m = _LINE.match(self.lines[i])
        self.lines[i] = m.group(1) + m.group(2) + m.group(3) + str(value) + m.group(5)

    def text(self):
        return self.newline.join(self.lines)

    def save(self, path):
        """Write this file atomically. The parser re-reads the temp file before it replaces the original."""
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".skytune-", dir=directory)
        try:
            os.write(fd, self.encoded())
            os.fsync(fd)
            os.close(fd)
            fd = None
            UserCfg.load(tmp)
            os.replace(tmp, path)
            tmp = None
            try:
                dirfd = os.open(directory, os.O_RDONLY)
                try: os.fsync(dirfd)
                finally: os.close(dirfd)
            except OSError:
                pass
        finally:
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
            if tmp:
                try: os.remove(tmp)
                except OSError: pass

# ---------------------------------------------------------------- settings
# Each setting: path, label, group ("ingame" | "advanced"), kind, spec, tooltip.
# kind: float (spec=(min,max,step)), int (same), choice (spec=dict label->value, value written verbatim)
# Key names confirmed from real MSFS 2024 UserCfg.opt files (Graphics Version 2.1.0) - see README.
Q4 = {"Low": 0, "Medium": 1, "High": 2, "Ultra": 3}
OFF_Q4 = {"Off": -1, **Q4}                    # traffic/population keys: -1 = Off, 0 = Low
ON_OFF = {"Off": 0, "On": 1}
TEX_Q = {"Ultra": 0, "High": 1, "Medium": 2, "Low": 3}   # inverted in the file
FG_NOTE = ("NONE = off, FSRFG = AMD FSR frame generation (broad GPU support), "
           "DLSSG = NVIDIA DLSS frame generation (RTX 40/50 only, Windows HAGS required). "
           "FSR frame generation supports 2x only; 3x/4x multipliers are restricted to RTX 50 series. "
           "Enable frame generation after confirming a stable base frame rate; it smooths motion but does not improve input response.")
SETTINGS = [
    # ---- In-game menu settings ({Video} + {Graphics})
    ("Video/AntiAliasing", "Anti-aliasing / upscaler", "ingame", "choice",
     {"TAA": "TAA", "NVIDIA DLSS": "DLSS", "AMD FSR": "FSR"},
     "Choose TAA, NVIDIA DLSS Super Resolution (RTX only), or AMD FSR upscaling. FSR version can depend on your GPU driver."),
    ("Video/PrimaryScaling", "Render scaling (TAA)", "ingame", "float", (0.5, 2.0, 0.05),
     "Internal render resolution scale with TAA. 1.0 = 100 (native); <1 = faster, >1 = supersampling."),
    ("Video/SharpenAmount", "Sharpening", "ingame", "float", (0.0, 2.0, 0.1), "Post sharpening amount (1.0 = 100)."),
    ("Video/FrameGeneration", "Frame generation", "ingame", "choice",
     {"Off": "NONE", "AMD FSR": "FSRFG", "NVIDIA DLSS FG": "DLSSG"}, FG_NOTE),
    ("Video/NBFramesToGenerate", "Frame-gen multiplier", "ingame", "choice",
     {"2x": 1, "3x": 2, "4x": 3}, "Generated frames per real frame (1 = 2x). AMD FSR supports 2x; 3x/4x are restricted to RTX 50-series DLSS Frame Generation."),
    ("Video/FSRMode", "FSR upscaler mode", "ingame", "choice",
     {"Quality": "QUALITY", "Balanced": "BALANCED", "Performance": "PERFORMANCE"},
     "Only used when anti-aliasing is AMD FSR."),
    ("Video/DLSSMode", "DLSS mode", "ingame", "choice",
     {"Auto": "AUTO", "Quality": "QUALITY", "Balanced": "BALANCED", "Performance": "PERFORMANCE"},
     "Only used when anti-aliasing is DLSS."),
    ("Video/FrameLimiter", "Frame limiter (0=off)", "ingame", "int", (0, 240, 1), "FPS cap. 0 = unlimited."),
    ("Graphics/Terrain/LoDFactor", "Terrain LOD (TLOD)", "ingame", "float", (0.1, 4.0, 0.05),
     "1.0 = 100 in menu, menu range up to 400. Heavy CPU cost."),
    ("Graphics/ObjectsLoD/LoDFactor", "Objects LOD (OLOD)", "ingame", "float", (0.1, 2.0, 0.05),
     "1.0 = 100 (menu max 200). Strong CPU cost at busy airports/cities."),
    ("Graphics/OffscreenTerrainPreCaching/Quality", "Off-screen terrain pre-caching", "ingame", "choice", Q4, "Reduces pop-in, costs RAM."),
    ("Graphics/Texture/Quality", "Texture resolution", "ingame", "choice", TEX_Q, "0 = Ultra .. 3 = Low. Ultra needs >8 GB VRAM."),
    ("Graphics/Texture/MaxAnisotropy", "Anisotropic filtering", "ingame", "choice",
     {"Off": 1, "2x": 2, "4x": 4, "8x": 8, "16x": 16}, "Cheap on modern GPUs."),
    ("Graphics/VolumetricClouds/Quality", "Volumetric clouds", "ingame", "choice", Q4, "Biggest GPU cost."),
    ("Graphics/Shadows/Size", "Shadow maps", "ingame", "choice",
     {"768": 768, "1024": 1024, "1536": 1536, "2048": 2048}, "Shadow map resolution."),
    ("Graphics/HeightFieldShadows/Size", "Terrain shadows", "ingame", "choice",
     {"128": 128, "256": 256, "512": 512, "1024": 1024, "2048": 2048}, "Terrain shadow resolution; 256–512 is a good quality/performance starting point."),
    ("Graphics/RaytracedShadows/Enabled", "Ray-traced shadows", "ingame", "choice", ON_OFF,
     "Can improve cockpit shadowing, but is expensive. Presets keep it off unless Best visuals is selected on top-tier hardware."),
    ("Graphics/SSRaytracedShadows/Enabled", "Screen-space ray-traced shadows (MSFS 2020)", "ingame", "choice", ON_OFF,
     "Legacy MSFS 2020 control. Presets keep this off for a safer performance baseline."),
    ("Graphics/DisplacementMapping/Enabled", "Displacement mapping", "ingame", "choice", ON_OFF,
     "Adds ground relief and can be costly. Off is a sensible default for airliners; Best visuals can enable it on top-tier hardware."),
    ("Graphics/ContactShadows/Quality", "Contact shadows", "ingame", "choice", Q4, "Screen-space contact shadows."),
    ("Graphics/Water/FFTSize", "Water waves", "ingame", "choice", {"Low (64)": 64, "Medium (128)": 128, "High (256)": 256}, "Wave sim resolution."),
    ("Graphics/ReflectionProbe/Size", "Cubemap reflections", "ingame", "choice",
     {"128": 128, "192": 192, "256": 256}, "Environment reflection resolution."),
    ("Graphics/SSR/Quality", "Raymarched reflections", "ingame", "choice", Q4, "Screen-space reflections."),
    ("Graphics/SSAO/Quality", "Ambient occlusion", "ingame", "choice", Q4, "SSAO quality."),
    ("Graphics/VolumetricLights/Quality", "Light shafts", "ingame", "choice", Q4, "Volumetric light quality."),
    ("Graphics/WindShield/Quality", "Windshield effects", "ingame", "choice", Q4, "Rain/ice on windshield."),
    ("Graphics/VegetationLarge/Quality", "Large vegetation (MSFS 2020)", "ingame", "choice", Q4, "Legacy MSFS 2020 tree and large vegetation quality."),
    ("Graphics/VegetationSmall/Quality", "Small vegetation (MSFS 2020)", "ingame", "choice", Q4, "Legacy MSFS 2020 grass and small vegetation quality."),
    ("Graphics/TextureSynthesis/Quality", "Texture synthesis (MSFS 2020)", "ingame", "choice", Q4, "Legacy MSFS 2020 ground texture synthesis quality."),
    ("Graphics/VectorDataTessellation/Quality", "Vector detail (MSFS 2020)", "ingame", "choice", Q4, "Legacy MSFS 2020 vector data and road/shore tessellation."),
    ("Graphics/Buildings/Quality", "Buildings", "ingame", "choice", Q4, "Building detail (CPU)."),
    ("Graphics/Procedural/TreesQuality", "Trees", "ingame", "choice", Q4, "Tree detail/density."),
    ("Graphics/Procedural/PlantsQuality", "Plants", "ingame", "choice", Q4, "Plant detail."),
    ("Graphics/Procedural/GrassQuality", "Grass", "ingame", "choice", Q4, "Grass detail."),
    ("Graphics/Procedural/RocksQuality", "Rocks", "ingame", "choice", Q4, "Rock detail."),
    ("Graphics/GlassCockpitsRefreshRate/Quality", "Glass cockpit refresh rate", "ingame", "choice",
     {"Low": 0, "Medium": 1, "High": 2}, "Avionics screen refresh - CPU cost."),
    ("Graphics/Characters/Quantity", "Characters quantity", "ingame", "choice", OFF_Q4, "People at airports. Off is written as -1; Low is 0."),
    ("Graphics/Traffic/AircraftTrafficQuantity", "Aircraft traffic quantity", "ingame", "choice", OFF_Q4, "AI aircraft. Off is written as -1; Low is 0."),
    ("Graphics/Traffic/ParkedAircraftQuantity", "Parked aircraft quantity", "ingame", "choice", OFF_Q4, "Static aircraft. Off is written as -1; Low is 0."),
    ("Graphics/Traffic/AirportsServicesQuantity", "Airport services quantity", "ingame", "choice", OFF_Q4, "Ground vehicles. Off is written as -1 where the simulator supports it; Low is 0."),
    ("Graphics/Traffic/RoadQuality", "Road traffic", "ingame", "choice", OFF_Q4, "Road vehicles. Off is written as -1; Low is 0."),
    ("Graphics/Traffic/SeaQuality", "Boats & ships", "ingame", "choice", OFF_Q4, "Sea traffic. Off is written as -1; Low is 0."),
    ("Graphics/Fauna/Quantity", "Wildlife", "ingame", "choice", OFF_Q4, "Animals. Off is written as -1; Low is 0."),
    ("Video/FullScreenResolution", "Full-screen resolution", "display", "text", None,
     "Only written if you tick 'Change display resolution'. Format: WIDTH HEIGHT"),
    # ---- Advanced (beyond menu)
    ("Graphics/Terrain/LoDFactor", "Terrain LOD beyond menu", "advanced", "float", (0.1, 8.0, 0.05),
     "Above 4.0 (400) is beyond the menu; returns diminish above ~4-5."),
    ("Graphics/ObjectsLoD/LoDFactor", "Objects LOD beyond menu", "advanced", "float", (0.1, 4.0, 0.05), "Above 2.0 is beyond the menu."),
    ("Graphics/Shadows/Size", "Shadow maps beyond menu", "advanced", "choice",
     {"768": 768, "1024": 1024, "1536": 1536, "2048": 2048, "4096": 4096}, "4096 exceeds the menu."),
    ("Graphics/Shadows/MaxSliceCount", "Shadow cascades", "advanced", "int", (1, 4, 1), "Not in menu."),
    ("Graphics/Terrain/POMMaxDist", "Parallax occlusion distance", "advanced", "float", (0.0, 60.0, 1.0), "Not in menu."),
    ("Graphics/Terrain/POMSubsplitsMaxDist", "Parallax subsplit distance", "advanced", "float", (0.0, 30.0, 0.5), "Not in menu."),
]
KINDS = {}
for _s in SETTINGS: KINDS.setdefault(_s[0], _s[3])

# Defaults: TAA, frame generation off. The GUI overrides these with the user's choices via with_user_choices().
COMMON = {"Video/AntiAliasing": "TAA", "Video/FrameGeneration": "NONE"}

def _preset(tl, ol, tex, clouds, sh, hsh, q, traffic, chars, scale, water, refl, pre, anis=16):
    return dict(COMMON, **{
        "Video/PrimaryScaling": scale,
        "Graphics/Terrain/LoDFactor": tl, "Graphics/ObjectsLoD/LoDFactor": ol,
        "Graphics/Texture/Quality": tex, "Graphics/Texture/MaxAnisotropy": anis,
        "Graphics/VolumetricClouds/Quality": clouds, "Graphics/Shadows/Size": sh,
        "Graphics/HeightFieldShadows/Size": hsh, "Graphics/OffscreenTerrainPreCaching/Quality": pre,
        "Graphics/Water/FFTSize": water, "Graphics/ReflectionProbe/Size": refl,
        "Graphics/ContactShadows/Quality": q, "Graphics/SSR/Quality": q, "Graphics/SSAO/Quality": q,
        "Graphics/VolumetricLights/Quality": q, "Graphics/WindShield/Quality": min(q, 2),
        "Graphics/Buildings/Quality": q, "Graphics/Procedural/TreesQuality": q,
        "Graphics/Procedural/PlantsQuality": q, "Graphics/Procedural/GrassQuality": q,
        "Graphics/Procedural/RocksQuality": q,
        # MSFS 2020 equivalents (only written when present in the selected file)
        "Graphics/VegetationLarge/Quality": q, "Graphics/VegetationSmall/Quality": q,
        "Graphics/TextureSynthesis/Quality": q, "Graphics/VectorDataTessellation/Quality": q,
        "Graphics/Characters/Quantity": chars,
        "Graphics/Traffic/AircraftTrafficQuantity": traffic, "Graphics/Traffic/ParkedAircraftQuantity": traffic,
        "Graphics/Traffic/AirportsServicesQuantity": traffic, "Graphics/Traffic/RoadQuality": traffic,
        "Graphics/Traffic/SeaQuality": traffic, "Graphics/Fauna/Quantity": traffic,
        # expensive extras stay off in presets
        "Graphics/RaytracedShadows/Enabled": 0, "Graphics/DisplacementMapping/Enabled": 0,
        "Graphics/SSRaytracedShadows/Enabled": 0,
    })

PRESETS = {
    #                      TLOD OLOD tex clouds shadow hshadow q  traffic chars scale water refl pre
    "Performance": _preset(0.75, 0.75, 2, 1, 1024, 256, 1, 0, 0, 0.85, 64, 128, 1, anis=8),
    "Balanced":    _preset(1.00, 1.00, 1, 2, 1536, 512, 1, 1, 1, 1.00, 128, 192, 2),
    "Quality":     _preset(2.00, 1.50, 1, 2, 2048, 512, 2, 2, 2, 1.00, 128, 256, 2),
    "Ultra+":      _preset(3.00, 2.00, 0, 3, 2048, 512, 3, 2, 2, 1.00, 256, 256, 3),
}
# Ultra+ is capped at TLOD 300 / OLOD 200 / 2048 shadow maps; beyond-menu values stay manual (Advanced).
# Balanced-30: tuned for 8 GB RTX 3070 Ti-class @1080p to hold >=30 FPS *before* frame gen at busy
# airports: TLOD/OLOD 100, traffic/characters Low-Medium, glass cockpits Medium. FG is a bonus.
# Real-world sample (one user, not a benchmark): RTX 3070 Ti 8 GB + Ryzen 7 8700F, 1080p, MSFS 2024, iniBuilds
# A320neo V2 on the ground at EGLL with these settings: ~51 FPS, "Limited by Graphics Queue" (GPU-bound), so the
# >=30 FPS target holds and the light traffic keeps the processor out of the way.
PRESETS["Balanced-30"] = dict(PRESETS["Balanced"], **{
    "Graphics/Characters/Quantity": 0, "Graphics/Traffic/AircraftTrafficQuantity": 1,
    "Graphics/Traffic/ParkedAircraftQuantity": 0, "Graphics/Traffic/AirportsServicesQuantity": 0,
    "Graphics/GlassCockpitsRefreshRate/Quality": 1, "Graphics/Buildings/Quality": 1,
    "Graphics/Texture/Quality": 1, "Graphics/VolumetricClouds/Quality": 2, "Video/PrimaryScaling": 1.0})

# ---------------------------------------------------------------- v1.7.0 creator setup (MSFS 2024 only)
# Values are the ones EasyjetSimPilot showed for MSFS 2024 Sim Update 7, mapped only where SkyTune
# already has a verified UserCfg key and value scale. Resolution, display mode and every unmapped
# menu row are left out. Nothing here writes a file.
EASYJET_NAME = "EasyjetSimPilot (MSFS 2024 SU7)"
EASYJET_8GB_NAME = "EasyjetSimPilot - 8 GB VRAM"
EASYJET_CREDIT = "Based on settings shown in EasyjetSimPilot's video"
EASYJET_URL = "https://youtu.be/Mq63dyne32g"
EASYJET_NOTE = ("A 240 Hz screen without variable refresh may need V-Sync or a frame cap. "
                "SkyTune does not change V-Sync. This is not a frame-rate promise, and the creator has not endorsed SkyTune.")
EASYJET_UNMAPPED = (
    "Display mode", "HDR10", "Exposure compensation", "Resolution", "V-Sync", "V-Sync interval",
    "NVIDIA Reflex", "Dynamic settings", "Depth of field", "Motion blur", "Particles",
    "Character variety", "Character quality", "Airport services variety", "Parked aircraft variety",
    "Aircraft traffic variety", "Seatbelt visibility",
)
# 8 GB cards: only the heavy video-memory rows move. Texture stays High because the settings table
# treats Ultra, not High, as the step that needs more than 8 GB.
EASYJET_8GB_CHANGES = {
    "Graphics/Terrain/LoDFactor": 1.0,
    "Graphics/OffscreenTerrainPreCaching/Quality": 1,
    "Graphics/VolumetricClouds/Quality": 2,
}
EASYJET_8GB_KEPT = "Texture resolution stays High. SkyTune's table treats Ultra as the step that needs more than 8 GB."

def easyjet_values():
    """MSFS 2024 SU7 values from the video, using only keys in SETTINGS."""
    return {
        "Video/AntiAliasing": "TAA",
        "Video/PrimaryScaling": 1.0,
        "Video/SharpenAmount": 1.0,
        "Video/FrameLimiter": 0,
        "Video/FrameGeneration": "FSRFG",
        "Video/NBFramesToGenerate": 1,
        "Graphics/Terrain/LoDFactor": 1.25,
        "Graphics/OffscreenTerrainPreCaching/Quality": 2,
        "Graphics/DisplacementMapping/Enabled": 1,
        "Graphics/Buildings/Quality": 2,
        "Graphics/Procedural/TreesQuality": 2,
        "Graphics/Procedural/PlantsQuality": 1,
        "Graphics/Procedural/RocksQuality": 1,
        "Graphics/Procedural/GrassQuality": 1,
        "Graphics/ObjectsLoD/LoDFactor": 1.0,
        "Graphics/VolumetricClouds/Quality": 3,
        "Graphics/Texture/Quality": 1,
        "Graphics/Texture/MaxAnisotropy": 16,
        "Graphics/Water/FFTSize": 128,
        "Graphics/RaytracedShadows/Enabled": 0,
        "Graphics/Shadows/Size": 1024,
        "Graphics/HeightFieldShadows/Size": 256,
        "Graphics/ContactShadows/Quality": 1,
        "Graphics/WindShield/Quality": 2,
        "Graphics/SSAO/Quality": 1,
        "Graphics/ReflectionProbe/Size": 192,
        "Graphics/SSR/Quality": 1,
        "Graphics/VolumetricLights/Quality": 1,
        "Graphics/GlassCockpitsRefreshRate/Quality": 1,
        "Graphics/Characters/Quantity": 0,
        "Graphics/Traffic/AirportsServicesQuantity": 0,
        "Graphics/Traffic/ParkedAircraftQuantity": -1,
        "Graphics/Traffic/AircraftTrafficQuantity": -1,
        "Graphics/Traffic/RoadQuality": 1,
        "Graphics/Traffic/SeaQuality": 1,
        "Graphics/Fauna/Quantity": 2,
    }

def easyjet_8gb_values():
    values = easyjet_values()
    values.update(EASYJET_8GB_CHANGES)
    return values

def creator_presets(edition):
    """Built-in creator setups for this simulator edition. Empty for MSFS 2020."""
    if edition != "2024": return {}
    return {EASYJET_NAME: easyjet_values(), EASYJET_8GB_NAME: easyjet_8gb_values()}

def creator_differences():
    """(label, main display, 8 GB display) for the rows the smaller-VRAM variant changes."""
    main = easyjet_values()
    rows = []
    for path, new in EASYJET_8GB_CHANGES.items():
        rows.append((setting_label(path), _display(path, main[path]), _display(path, new)))
    return rows

def creator_vs_profile(name, profile):
    """Differences between a built-in creator setup and a saved profile. Does not write."""
    vals = creator_presets("2024").get(name)
    if vals is None: raise ValueError("Unknown creator setup.")
    prof_vals = (profile or {}).get("values") or {}
    rows = []
    seen = []
    for path in list(vals) + list(prof_vals):
        if path in seen: continue
        seen.append(path)
        if _same_setting(path, vals.get(path), prof_vals.get(path)): continue
        rows.append((setting_label(path), _display(path, vals.get(path)), _display(path, prof_vals.get(path))))
    return rows

def _same_setting(path, left, right):
    if left is None or right is None: return left is None and right is None
    kind = KINDS.get(path, "int")
    try: return format_value(kind, left) == format_value(kind, right)
    except (TypeError, ValueError): return str(left) == str(right)

def format_value(kind, v):
    if kind == "float":
        return "%.6f" % float(v)
    if kind in ("text",):
        return " ".join(str(v).replace("x", " ").split())
    if isinstance(v, str) and not re.fullmatch(r"-?\d+(\.\d+)?", v):
        return v
    return str(int(float(v)))

def apply_values(cfg, values, change_resolution=False):
    """values: path -> value. Keys absent from the file are skipped (never added).
    Display resolution only written if change_resolution. Graphics changes set Preset Custom."""
    changed = []
    for p, v in values.items():
        target = p
        # MSFS 2020 has no Video/FrameGeneration; its DLSS frame generation is the
        # boolean Video/DLSSG. Map the 2024 choice onto it when only DLSSG exists.
        if p == "Video/FrameGeneration" and target not in cfg.index and "Video/DLSSG" in cfg.index:
            target = "Video/DLSSG"
            v = 1 if str(v).upper() == "DLSSG" else 0
        if target not in cfg.index:
            continue
        if target in ("Video/FullScreenResolution", "Video/Resolution") and not change_resolution:
            continue
        nv = format_value(KINDS.get(target, KINDS.get(p, "int")), v)
        if cfg.get(target) != nv:
            cfg.set(target, nv); changed.append(target)
    if any(p.startswith("Graphics/") for p in changed) and "Graphics/Preset" in cfg.index \
            and cfg.get("Graphics/Preset") != "Custom":
        cfg.set("Graphics/Preset", "Custom"); changed.append("Graphics/Preset")
    return changed

# ---------------------------------------------------------------- hardware detection
# Layered, every layer optional and time-limited: (1) Windows registry via winreg (no subprocess), (2) PowerShell CIM,
# (3) WMIC (removed from Windows 11 24H2+), (4) dxdiag /t (slow, last resort). Linux: /sys, lspci, glxinfo,
# vulkaninfo, /proc, xrandr. Nothing here may raise or hang; failures are recorded in hw["errors"].
PS_SCRIPT = r"""
$ErrorActionPreference='SilentlyContinue'
$g=@(); Get-CimInstance Win32_VideoController | ForEach-Object { $g += [pscustomobject]@{Name=$_.Name; Bytes=[int64]$_.AdapterRAM; Src='wmi'} }
$c=Get-CimInstance Win32_Processor | Select-Object -First 1
[pscustomobject]@{gpus=$g; cpu=$c.Name; cores=$c.NumberOfCores; threads=$c.NumberOfLogicalProcessors} | ConvertTo-Json -Depth 4 -Compress
"""
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IGNORED_ADAPTERS = re.compile(r"basic (display|render)|remote|virtual|parsec|meta virtual|citrix|vmware|hyper-v|"
                              r"displaylink|spacedesk|idd|indirect|mirage|luminon|oculus", re.I)

def _run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                              creationflags=_NOWIN, errors="replace").stdout or ""
    except Exception:
        return ""

def _ram_gb():
    if os.name != "nt":
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"): return round(int(line.split()[1]) / 2**20)
        return 0
    import ctypes
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS(); m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ullTotalPhys / 2**30)

def make_dpi_aware():
    """Per-monitor DPI awareness on Windows 8.1+, system-aware fallback. Must run before Tk() is created."""
    if os.name != "nt": return
    import ctypes
    # v1.3.2: per-monitor v2 first (Windows 10 1703+: crisp text and correctly scaled dialogs), then older fallbacks
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)): return
    except Exception: pass
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2), lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try: fn(); return
        except Exception: pass

def _screen():
    """Primary monitor size in physical pixels (the sim normally runs there)."""
    if os.name == "nt":
        import ctypes
        make_dpi_aware()
        return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    return parse_xrandr(_run(["xrandr", "--current"], 5))

def parse_xrandr(out):
    prim = re.search(r" connected primary (\d+)x(\d+)", out) or re.search(r" connected (\d+)x(\d+)", out)
    if prim: return int(prim.group(1)), int(prim.group(2))
    cur = re.search(r"current (\d+) x (\d+)", out)
    return (int(cur.group(1)), int(cur.group(2))) if cur else (0, 0)

def _reg_gpus():
    """Display adapters from the registry: DriverDesc + HardwareInformation.qwMemorySize (64-bit, accurate)."""
    import winreg
    out = []
    key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
        i = 0
        while True:
            try: sub = winreg.EnumKey(k, i)
            except OSError: break
            i += 1
            if not sub.isdigit(): continue
            try:
                with winreg.OpenKey(k, sub) as s:
                    name = winreg.QueryValueEx(s, "DriverDesc")[0]
                    b = 0
                    for val in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                        try:
                            v = winreg.QueryValueEx(s, val)[0]
                            b = int.from_bytes(v[:8], "little") if isinstance(v, (bytes, bytearray)) else int(v)
                            if b: break
                        except OSError: pass
                    out.append({"Name": name, "Bytes": b, "Src": "registry"})
            except OSError: pass
    return out

def _reg_cpu():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
        return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()

def parse_wmic(out):
    """`wmic path win32_VideoController get Name,AdapterRAM /format:list` output."""
    gpus, cur = [], {}
    for line in out.splitlines() + [""]:
        line = line.strip()
        if not line:
            if cur.get("Name"): gpus.append({"Name": cur["Name"], "Bytes": int(cur.get("AdapterRAM") or 0), "Src": "wmi"})
            cur = {}; continue
        if "=" in line:
            k, v = line.split("=", 1); cur[k.strip()] = v.strip()
    return gpus

def parse_dxdiag(text):
    """dxdiag /t report: 'Card name:' + 'Dedicated Memory: 8031 MB' per display device."""
    gpus = []
    for block in re.split(r"\n\s*Card name:", "\n" + text)[1:]:
        name = block.splitlines()[0].strip()
        m = re.search(r"Dedicated Memory:\s*([\d,]+)\s*MB", block)
        gpus.append({"Name": name, "Bytes": int(m.group(1).replace(",", "")) * 2**20 if m else 0, "Src": "dxdiag"})
    return gpus

def _dxdiag_gpus(timeout=60):
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".txt"); os.close(fd)
    try:
        _run(["dxdiag", "/whql:off", "/t", p], timeout)
        with open(p, encoding="utf-16" if open(p, "rb").read(2) in (b"\xff\xfe", b"\xfe\xff") else "mbcs", errors="replace") as f:
            return parse_dxdiag(f.read())
    finally:
        try: os.remove(p)
        except OSError: pass

def linux_gpus(sys_root="/sys", lspci_out=None):
    """GPUs on Linux: AMD VRAM from /sys/class/drm/card*/device/mem_info_vram_total, names from lspci,
    NVIDIA VRAM from nvidia-smi."""
    gpus = []
    lspci_out = _run(["lspci", "-mm"], 5) if lspci_out is None else lspci_out
    for line in lspci_out.splitlines():
        if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', line):
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3: gpus.append({"Name": "%s %s" % (parts[1], parts[2]), "Bytes": 0, "Src": "lspci"})
    for vf in sorted(glob.glob(os.path.join(sys_root, "class", "drm", "card*", "device", "mem_info_vram_total"))):
        try:
            b = int(open(vf).read().strip())
            dev = os.path.dirname(vf); name = ""
            try: name = open(os.path.join(dev, "product_name")).read().strip()
            except OSError: pass
            gpus.append({"Name": name or "AMD Radeon (amdgpu)", "Bytes": b, "Src": "sysfs"})
        except (OSError, ValueError): pass
    smi = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], 5) if lspci_out is not None and sys_root == "/sys" else ""
    for line in smi.splitlines():
        if "," in line:
            n, mb = line.rsplit(",", 1)
            try: gpus.append({"Name": n.strip(), "Bytes": int(float(mb)) * 2**20, "Src": "nvidia-smi"})
            except ValueError: pass
    if not any(g["Bytes"] for g in gpus):
        r = _run(["glxinfo", "-B"], 5)
        m = re.search(r"Device:\s*(.+?)\s*\(", r); v = re.search(r"Video memory:\s*(\d+)MB", r)
        if m: gpus.append({"Name": m.group(1), "Bytes": int(v.group(1)) * 2**20 if v else 0, "Src": "glxinfo"})
    return gpus

def linux_cpu(cpuinfo_text=None):
    if cpuinfo_text is None:
        try: cpuinfo_text = open("/proc/cpuinfo").read()
        except OSError: cpuinfo_text = ""
    m = re.search(r"model name\s*:\s*(.+)", cpuinfo_text)
    cores = {(p, c) for p, c in re.findall(r"physical id\s*:\s*(\d+)[\s\S]*?core id\s*:\s*(\d+)", cpuinfo_text)}
    threads = len(re.findall(r"^processor\s*:", cpuinfo_text, re.M))
    return (m.group(1).strip() if m else "Unknown"), (len(cores) or threads // 2 or 0), threads

def _clean(name):
    return re.sub(r"\s+", " ", re.sub(r"\((R|TM|C)\)|®|™", "", name or "", flags=re.I)).strip()

def is_integrated(name):
    n = _clean(name)
    if re.search(r"Intel.*(UHD|Iris|HD Graphics)|Intel\(R\) Graphics|Intel Arc Graphics$|Arc\(TM\) Graphics$", n, re.I): return True
    if re.search(r"AMD|Radeon", n, re.I) and re.search(r"Radeon\(TM\)? Graphics|Radeon Graphics|Vega \d+ Graphics|\b[4-9][0-9]0M\b|Custom GPU|VanGogh|Van Gogh|Aerith|Sephiroth|Renoir|Cezanne|Rembrandt|Phoenix|Raphael|Strix", n, re.I) \
            and not re.search(r"\bRX\b|W\d{4}|WX \d", n, re.I): return True
    return False

def pick_gpu(gpus):
    """Prefer a real discrete GPU (laptops/hybrid and multi-GPU); registry qwMemorySize beats WMI AdapterRAM
    (32-bit, caps at 4 GB); virtual/remote adapters ignored."""
    rank = {"registry": 5, "sysfs": 5, "nvidia-smi": 5, "dxdiag": 4, "glxinfo": 3, "manual": 6, "wmi": 1, "lspci": 0}
    label = {"registry": "registry qwMemorySize", "wmi": "WMI AdapterRAM (max 4 GB, may be low)", "dxdiag": "dxdiag",
             "sysfs": "Linux sysfs", "nvidia-smi": "nvidia-smi", "glxinfo": "glxinfo", "lspci": "lspci (no VRAM)", "manual": "chosen by you"}
    by = {}
    for g in gpus or []:
        n = re.sub(r"\s+", " ", (g.get("Name") or "")).strip()
        if not n or IGNORED_ADAPTERS.search(n): continue
        e = by.setdefault(n.lower(), {"name": n, "vram_bytes": 0, "src": None, "r": -1})
        b = int(g.get("Bytes") or 0); src = g.get("Src") or "wmi"
        if src == "wmi": b &= 0xFFFFFFFF
        if b > 0 and rank.get(src, 0) > e["r"]:
            e["vram_bytes"], e["src"], e["r"] = b, label.get(src, src), rank.get(src, 0)
    if not by: return {"name": "Unknown", "vram_gb": 0, "src": None, "integrated": False}
    best = max(by.values(), key=lambda e: (not is_integrated(e["name"]), gpu_tier(e["name"], e["vram_bytes"] / 2**30)[0], e["vram_bytes"]))
    return {"name": best["name"], "vram_gb": round(best["vram_bytes"] / 2**30, 1), "src": best["src"],
            "integrated": is_integrated(best["name"])}

def detect_hardware(timeouts=(20, 15, 60)):
    hw = {"gpu": "Unknown", "vram_gb": 0, "vram_src": None, "cpu": "Unknown", "cores": 0, "threads": os.cpu_count() or 0,
          "ram_gb": 0, "width": 0, "height": 0, "errors": [], "integrated": False, "platform": "windows" if os.name == "nt" else "linux"}
    gpus = []
    try:
        if os.name == "nt":
            try: gpus += _reg_gpus()
            except Exception as e: hw["errors"].append("Registry GPU query failed: %s" % e)
            try: hw["cpu"] = _reg_cpu()
            except Exception as e: hw["errors"].append("Registry CPU query failed: %s" % e)
            if not any(g["Bytes"] for g in gpus) or not hw["cores"]:
                import json
                try:
                    d = json.loads(_run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT], timeouts[0]) or "{}")
                    gl = d.get("gpus") or []; gpus += [gl] if isinstance(gl, dict) else gl
                    if d.get("cpu") and hw["cpu"] == "Unknown": hw["cpu"] = d["cpu"].strip()
                    hw["cores"] = int(d.get("cores") or 0); hw["threads"] = int(d.get("threads") or hw["threads"])
                except Exception as e: hw["errors"].append("PowerShell query failed: %s" % e)
            if not gpus:
                gpus += parse_wmic(_run(["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM", "/format:list"], timeouts[1]))
            if not hw["cores"]:
                m = re.search(r"NumberOfCores=(\d+)", _run(["wmic", "cpu", "get", "NumberOfCores", "/format:list"], timeouts[1]))
                hw["cores"] = int(m.group(1)) if m else 0
            if not any(g.get("Bytes") for g in gpus):
                try: gpus += _dxdiag_gpus(timeouts[2])
                except Exception as e: hw["errors"].append("dxdiag failed: %s" % e)
        else:
            gpus += linux_gpus()
            hw["cpu"], hw["cores"], hw["threads"] = linux_cpu()
    except Exception as e:
        hw["errors"].append("Hardware query failed: %s" % e)
    g = pick_gpu(gpus)
    hw.update(gpu=g["name"], vram_gb=g["vram_gb"], vram_src=g["src"], integrated=g["integrated"])
    if not hw["cores"] and hw["threads"]: hw["cores"] = max(1, hw["threads"] // 2)
    if hw["gpu"] == "Unknown": hw["errors"].append("Graphics card not detected – choose yours with “Pick my GPU”.")
    try: hw["ram_gb"] = _ram_gb()
    except Exception as e: hw["errors"].append("RAM: %s" % e)
    try: hw["width"], hw["height"] = _screen()
    except Exception as e: hw["errors"].append("Screen: %s" % e)
    return hw

# GPU tier list (0 = integrated/very weak .. 4 = flagship). First match wins; order matters.
# Laptop/Max-Q/Mobile variants drop one tier (lower power limits). Unknown GPUs fall back to VRAM.
GPU_TIERS = [
    (4, r"RTX\s*(4080|4090|5080|5090)|RX\s*7900\s*XTX|RX\s*9070\s*XT"),
    (3, r"RTX\s*(3080|3090|4070|5070)|RX\s*(6800|6900|6950|7800|7900\s*(XT|GRE)|9070)|RX\s*9060\s*XT|RTX\s*A?(4500|5000|5500|6000)"),
    (2, r"RTX\s*(2070|2080|3060|3070|4060|5060)|RX\s*(6600|6650|6700|6750|7600|7700|9060)|GTX\s*1080|TITAN\s*(X|V|Xp)|"
        r"Arc\s*(A7[57]0|B5[78]0)|Radeon\s*VII|RTX\s*A?4000"),
    (1, r"RTX\s*(2050|2060|3050)|GTX\s*(970|980|1060|1070|1650|1660)|RX\s*(470|480|570|580|590|5500|5600|5700|6400|6500|6550|Vega)|"
        r"Arc\s*A(3|5)\d0|Radeon\s*(\d{3}M|8[0-9]0M)\b|Radeon\s*890M|Radeon\s*780M|Radeon\s*880M|Arc\s*(140|130)V"),
    (0, r"GTX\s*(9[56]0|10[35]0)|GT\s*\d+|MX\s*\d+|RX\s*(460|550|560)|Intel|Radeon.*Graphics|Vega\s*\d+|Van\s*Gogh|Custom GPU"),
]
def gpu_tier(name, vram_gb=0):
    """(tier, reason). Mobile variants -1; unknown names fall back to VRAM."""
    n = _clean(name)
    for t, rx in GPU_TIERS:
        if re.search(rx, n, re.I):
            if t and re.search(r"Laptop|Mobile|Max-?Q|\bM\b|Notebook", n, re.I) and not re.search(r"\d{3}M\b", n):
                return t - 1, "laptop version"
            return t, rx
    if vram_gb:
        return (0 if vram_gb < 4 else 1 if vram_gb < 8 else 2 if vram_gb < 16 else 3), "unknown model – estimated from %.0f GB VRAM" % vram_gb
    return 0, None

# CPU tier (MSFS is main-thread bound; X3D cache helps most). None = unknown -> fall back to core count.
CPU_TIERS = [
    (4, r"X3D|i9-1[2-4]\d{3}|i7-1[34]7\d{2}K|Core\s*Ultra\s*9|Ryzen\s*9\s*[79]\d{3}"),
    (3, r"i7-1[2-4]\d{3}|i5-1[34]6\d{2}|Core\s*Ultra\s*[57]\s*2\d{2}K|Core\s*Ultra\s*7|Ryzen\s*[79]\s*[5-9]\d{3}|Ryzen\s*5\s*[79]\d{3}|i9-1[01]\d{3}"),
    (2, r"i5-1[2-4]\d{3}|i[579]-(9|10|11)\d{3}|i7-8\d{3}|Core\s*Ultra\s*5|Ryzen\s*[579]\s*[3-6]\d{3}|Ryzen\s*7\s*2\d{3}|Ryzen\s*Z1"),
    (1, r"i[357]-[4-8]\d{3}|i3-|Ryzen\s*[3-7]\s*[12]\d{3}|Ryzen\s*3|Custom APU|AMD Custom|Zen\s*2"),
    (0, r"Celeron|Pentium|Athlon|Atom|N\d{3,4}\b|FX-"),
]
def cpu_tier(name):
    n = _clean(name)
    for t, rx in CPU_TIERS:
        if re.search(rx, n, re.I):
            if t and re.search(r"\d{4,5}U\b|\d{3}U\b|\bU\b", n): t -= 1      # low-power laptop chips
            return t
    return None

LEVELS = ["Performance", "Performance", "Balanced", "Quality", "Ultra+"]

def is_steam_deck(hw):
    return bool(re.search(r"Van\s*Gogh|Aerith|Sephiroth|Custom GPU 0405|Steam Deck|AMD Custom APU 0[49]0[05]", (hw.get("gpu") or "") + " " + (hw.get("cpu") or ""), re.I)) \
        or (hw.get("width"), hw.get("height")) in ((1280, 800), (800, 1280)) and hw.get("integrated")

def recommend(hw):
    """Return (preset_name, score, reasons). Score = GPU tier, then capped by VRAM/CPU/RAM, adjusted for
    resolution. See DETAILS 'Auto-detect scoring table'."""
    reasons = []
    gname = hw.get("gpu") or "Unknown"
    v = hw.get("vram_gb") or 0
    t, why = gpu_tier(gname, v)
    integ = hw.get("integrated") or is_integrated(gname)
    if integ and t > 1: t = 1
    reasons.append("GPU '%s' -> tier %d%s" % (gname, t, " (%s)" % why if why and " " in why else ""))
    if integ: reasons.append("Integrated graphics share system memory – keeping settings light")
    s = t
    if gname == "Unknown":
        reasons.append("GPU not detected - falling back to the safest preset; pick one manually if you know better")
    if v and not integ:
        vcap = 0 if v < 3 else 1 if v < 6 else 2 if v < 10 else 3 if v < 16 else 4
        if vcap < s: reasons.append("VRAM %.0f GB caps score at %d" % (v, vcap)); s = vcap
    hard = False
    ct = cpu_tier(hw.get("cpu"))
    c = hw.get("cores") or 0
    if ct is not None:
        ccap = {0: 1, 1: 1, 2: 3, 3: 4, 4: 4}[ct]
        if c and c < 4: ccap = min(ccap, 1)
        if ccap < s: reasons.append("CPU '%s' (tier %d) caps score at %d" % (hw.get("cpu"), ct, ccap)); s = ccap; hard = True
    else:
        ccap = 1 if c and c < 6 else 2 if c and c < 8 else 4
        if ccap < s: reasons.append("%d CPU cores caps score at %d" % (c, ccap)); s = ccap; hard = True
    r = hw.get("ram_gb") or 0
    rcap = 0 if r and r < 12 and integ else 1 if r and r < 16 else 3 if r and r < 32 else 4
    if rcap < s: reasons.append("%d GB RAM caps score at %d" % (r, rcap)); s = rcap; hard = True
    w, h = hw.get("width") or 0, hw.get("height") or 0
    px = w * h
    if px >= 3840 * 2160 * 0.9 and s < 4:
        s = max(0, s - 1); reasons.append("4K-class display: -1")
    elif px > 2560 * 1440 * 1.2 and s in (2, 3) and t < 4:
        s -= 1; reasons.append("Ultrawide/high-resolution display (%dx%d): -1" % (w, h))
    elif 0 < px <= 1920 * 1200 and s == 1 and t >= 2 and not hard:
        s = 2; reasons.append("1080p display lets a tier-2+ GPU run Balanced")
    if is_steam_deck(hw):
        s = 0; reasons.append("Steam Deck / handheld APU at 1280×800 – lightest settings")
    preset = LEVELS[s]
    # 8 GB-class mid/high GPU at <=1440p: use the >=30 FPS tuned Balanced (CPU-bound busy airports).
    if preset == "Balanced" and t >= 2 and 0 < px <= 2560 * 1440:
        preset = "Balanced-30"
        reasons.append("Using 'Balanced-30': TLOD/OLOD 100, low traffic/characters to stay >30 FPS at busy "
                       "airports before optional frame generation")
    reasons.append("Score %d -> %s. Your anti-aliasing and frame-generation choices are kept." % (s, preset))
    return preset, s, reasons

# For "Pick my GPU" when detection fails: (label, name used for tiering, typical VRAM GB)
MANUAL_GPUS = [
    ("Integrated graphics (Intel UHD / Iris Xe, AMD Radeon Graphics)", "Intel Iris Xe Graphics", 2),
    ("AMD Radeon 780M / 880M / 890M (integrated)", "AMD Radeon 780M", 4),
    ("Steam Deck", "AMD Custom GPU 0405 (Van Gogh)", 4),
    ("NVIDIA GTX 970 / 980 / 1060 / 1070 / 1650 / 1660", "NVIDIA GeForce GTX 1660", 6),
    ("AMD RX 470 – 590 / 5500 – 5700 / 6500", "AMD Radeon RX 580", 8),
    ("Intel Arc A380 / A580", "Intel Arc A580", 8),
    ("NVIDIA RTX 2060 / 3050", "NVIDIA GeForce RTX 3050", 8),
    ("NVIDIA RTX 2070 / 2080 / 3060 / 3070 / 4060 / 5060", "NVIDIA GeForce RTX 3070", 8),
    ("AMD RX 6600 – 6750 / 7600 / 7700 / 9060", "AMD Radeon RX 6700 XT", 12),
    ("Intel Arc A750 / A770 / B570 / B580", "Intel Arc A770", 16),
    ("NVIDIA RTX 3080 / 3090 / 4070 / 5070", "NVIDIA GeForce RTX 4070", 12),
    ("AMD RX 6800 / 6900 / 7800 / 7900 XT / 9070", "AMD Radeon RX 7800 XT", 16),
    ("NVIDIA RTX 4080 / 4090 / 5080 / 5090", "NVIDIA GeForce RTX 4090", 24),
    ("AMD RX 7900 XTX / 9070 XT", "AMD Radeon RX 7900 XTX", 24),
]
def manual_hw(hw, label, vram_gb=None, laptop=False):
    name, v = next((n, v) for l, n, v in MANUAL_GPUS if l == label)
    out = dict(hw, gpu=name + (" Laptop GPU" if laptop else ""), vram_gb=float(vram_gb or v), vram_src="chosen by you",
               integrated=is_integrated(name), errors=[e for e in hw.get("errors", []) if "not detected" not in e])
    return out

def hw_summary(hw):
    return ("GPU: %s (%.1f GB VRAM via %s)\nCPU: %s (%s cores / %s threads)\nRAM: %s GB\nDisplay: %sx%s" %
            (hw["gpu"], hw["vram_gb"], hw.get("vram_src"), hw["cpu"], hw["cores"], hw["threads"],
             hw["ram_gb"], hw["width"], hw["height"]))


# ---------------------------------------------------------------- goals
GOALS = ["Best visuals", "Balanced", "Smooth & steady"]
DEFAULT_GOAL = "Balanced"
PRESET_SCORE = {"Performance": 1, "Balanced": 2, "Balanced-30": 2, "Quality": 3, "Ultra+": 4}
GOAL_BLURB = {
    "Best visuals": "Highest quality your PC can handle – richer clouds, shadows and lighting.",
    "Balanced": "Good looks and good frame rates (recommended).",
    "Smooth & steady": "Even, stutter-free frames – lighter CPU load and a frame-rate cap.",
}

def goal_adjust(values, goal, score):
    """Adjust preset values for the user's goal. Returns a new dict; never mutates PRESETS."""
    v = dict(values)
    def up(p, x):
        if p in v: v[p] = max(v[p], x)
    def down(p, x):
        if p in v: v[p] = min(v[p], x)
    if goal == "Best visuals":
        hi = 3 if score >= 2 else 2
        up("Graphics/VolumetricClouds/Quality", hi); up("Graphics/Shadows/Size", 2048 if score >= 2 else 1536)
        for p in ("Graphics/ContactShadows/Quality", "Graphics/SSAO/Quality", "Graphics/VolumetricLights/Quality",
                  "Graphics/SSR/Quality", "Graphics/Buildings/Quality", "Graphics/Procedural/TreesQuality",
                  "Graphics/Procedural/GrassQuality"):
            up(p, 2 if score >= 2 else 1)
        if score >= 2: up("Graphics/Terrain/LoDFactor", 1.5)
        if score >= 4:
            v["Graphics/RaytracedShadows/Enabled"] = 1
            v["Graphics/DisplacementMapping/Enabled"] = 1
    elif goal == "Smooth & steady":
        down("Graphics/Terrain/LoDFactor", 1.0); down("Graphics/ObjectsLoD/LoDFactor", 0.8)
        for p in ("Graphics/Traffic/AircraftTrafficQuantity", "Graphics/Traffic/ParkedAircraftQuantity",
                  "Graphics/Traffic/AirportsServicesQuantity", "Graphics/Characters/Quantity"):
            down(p, 0)
        down("Graphics/Traffic/RoadQuality", 1); down("Graphics/Buildings/Quality", 1)
        v["Graphics/GlassCockpitsRefreshRate/Quality"] = 1
        up("Graphics/OffscreenTerrainPreCaching/Quality", 2)        # pre-loading terrain reduces hitches
        v["Video/FrameLimiter"] = 30 if score <= 2 else 40          # confirmed {Video} key; caps real frames
    return v

def plan(hw, goal=DEFAULT_GOAL):
    """Combine hardware score with the user's goal. Returns (preset, values, score, plain_reasons, tech_reasons)."""
    preset, s, tech = recommend(hw)
    t, _ = gpu_tier(hw.get("gpu")); vram = hw.get("vram_gb") or 0
    vcap = 1 if vram and vram < 6 else 2 if vram and vram < 10 else 3 if vram and vram < 16 else 4
    plain = []
    if goal == "Best visuals":
        hard = any("CPU cores" in r or "RAM caps" in r for r in tech)
        ns = min(s + 1, vcap, 4)
        if ns > s and not hard and t > 0:
            s = ns; preset = LEVELS[s]
            plain.append("You picked Best visuals, so we moved up one level to %s." % preset)
        else:
            preset = "Balanced" if preset == "Balanced-30" else preset
            plain.append("You picked Best visuals. Your %s is the limit, so we kept %s detail and used spare "
                         "graphics power for nicer clouds, shadows and lighting." %
                         ("%.0f GB of video memory" % vram if vram and ns <= s else "processor or memory", preset))
    elif goal == "Smooth & steady":
        if s >= 3:
            s -= 1; preset = "Balanced-30" if LEVELS[s] == "Balanced" else LEVELS[s]
            plain.append("You picked Smooth & steady, so we stepped down one level to %s for headroom." % preset)
        elif preset == "Balanced":
            preset = "Balanced-30"
        plain.append("To keep frames even, we lowered the settings that load your processor most (AI traffic, people, "
                     "object distance) and capped the frame rate at %d FPS so frame times stay consistent – frame generation "
                     "can still double what you see." % (30 if s <= 2 else 40))
    else:
        plain.append("Balanced: good looks with good frame rates.")
    values = goal_adjust(PRESETS[preset], goal, s)
    shown = "Balanced" if preset == "Balanced-30" else preset
    plain.insert(0, "Your PC scores %d out of 4, so it suits the %s preset." % (s, shown))
    if preset == "Balanced-30":
        plain.append("Tuned to stay above 30 FPS at busy airports before frame generation.")
    plain.append("Your anti-aliasing, frame generation and traffic choices are kept.")
    return preset, values, s, plain, tech

# ---------------------------------------------------------------- v1.5.0 flight situations and a local diagnostic
# A situation is a deliberate setup for one kind of flight. It is not a problem diagnosis.
# It never writes the simulator file; Optimise still asks first.
SCENARIOS = ("Busy airport", "VFR scenery", "Airliner cockpit")
SCENARIO_NONE = "No extra situation"

def _lower_to(current, cap):
    n = _num(current)
    if n is None: return cap
    return cap if n > cap else n

def scenario_adjust(values, scenario, hw=None, locked=()):
    """Return (values, notes). Explains the tradeoff. Locked choices (aa, fg, traffic) are kept.
    Does not read or write any file."""
    if scenario not in SCENARIOS:
        raise ValueError("Unknown flight situation.")
    v = dict(values or {})
    hw = hw or {}
    vram = _num(hw.get("vram_gb")) or 0
    locked = set(locked or ())
    notes = []
    def put(path, raw):
        val, err = coerce_setting(path, raw)
        if err: return False
        v[path] = val
        return True
    if scenario == "Busy airport":
        notes.append("Fewer aircraft, vehicles and people, and shorter object distance, so a busy airport is easier on the processor. The apron looks quieter.")
        if "traffic" in locked:
            notes.append("Your traffic choice is kept.")
        else:
            for path, _label, _tip in TRAFFIC_CATS:
                put(path, 0)
        lod = _lower_to(v.get("Graphics/ObjectsLoD/LoDFactor"), 1.0)
        put("Graphics/ObjectsLoD/LoDFactor", lod)
        bld = _lower_to(v.get("Graphics/Buildings/Quality"), 1)
        put("Graphics/Buildings/Quality", bld)
    elif scenario == "VFR scenery":
        cap = 1.0 if vram and vram < 6 else 1.5 if vram and vram < 10 else 2.0
        cur = _num(v.get("Graphics/Terrain/LoDFactor"))
        cur = 1.0 if cur is None else cur
        target = min(cap, cur + 0.25) if cur < cap else cur
        put("Graphics/Terrain/LoDFactor", target)
        if not vram or vram >= 6:
            trees = _num(v.get("Graphics/Procedural/TreesQuality"))
            trees = 1 if trees is None else min(2, trees + (0 if trees >= 2 else 1))
            put("Graphics/Procedural/TreesQuality", trees)
        if vram >= 10:
            clouds = _num(v.get("Graphics/VolumetricClouds/Quality"))
            if clouds is not None and clouds < 2: put("Graphics/VolumetricClouds/Quality", clouds + 1)
        notes.append("More terrain and trees for looking outside. That uses more processor time and video memory. The instrument panel is left as it is.")
        if vram and vram < 6:
            notes.append("Video memory is tight, so terrain distance stays modest.")
    else:
        if "aa" not in locked:
            scale = _num(v.get("Video/PrimaryScaling"))
            if str(v.get("Video/AntiAliasing", "")).upper() == "TAA" and scale is not None and scale < 1:
                put("Video/PrimaryScaling", 1.0)
        sharp = _num(v.get("Video/SharpenAmount"))
        if sharp is None or sharp < 1.2: put("Video/SharpenAmount", 1.2)
        glass = _num(v.get("Graphics/GlassCockpitsRefreshRate/Quality"))
        if glass is None or glass < 2: put("Graphics/GlassCockpitsRefreshRate/Quality", 2)
        clouds = _num(v.get("Graphics/VolumetricClouds/Quality"))
        if clouds is not None and clouds >= 2: put("Graphics/VolumetricClouds/Quality", clouds - 1)
        notes.append("Clearer instruments and a slightly simpler sky. Distant clouds give up a step so the panel stays easier to read.")
        if "aa" in locked and "fg" in locked:
            notes.append("Your smooth-edges and extra-frames choices are kept.")
    return v, notes

def redact_user_text(text):
    """Hide account names in paths. Leaves the rest of a diagnostic readable."""
    s = str(text or "")
    s = re.sub(r"(?i)([A-Za-z]:\\Users\\)[^\\]+", r"\1<user>", s)
    s = re.sub(r"(?i)(/users/)[^/]+", r"\1<user>", s)
    s = re.sub(r"/home/[^/\s]+", "/home/<user>", s)
    return s

def build_diagnostic(info):
    """Plain-text note the user saves themselves. No API key, no upload, no raw account name."""
    info = info or {}
    lines = [
        "SkyTune diagnostic",
        "version: %s" % VERSION,
        "This file stays on your PC. SkyTune does not upload it.",
        "",
        "sim_running: %s" % info.get("sim_running"),
        "edition: %s" % (info.get("edition") or "unknown"),
        "install: %s" % redact_user_text(info.get("install") or "not loaded"),
        "settings_problem: %s" % (info.get("problem") or "none"),
        "known_settings_in_file: %s" % info.get("known_settings", 0),
        "goal: %s" % (info.get("goal") or ""),
        "smooth_edges: %s" % (info.get("aa") or ""),
        "extra_frames: %s" % (info.get("fg") or ""),
        "traffic: %s" % (info.get("traffic") or ""),
        "situation: %s" % (info.get("scenario") or SCENARIO_NONE),
        "profiles: %s" % (", ".join(info.get("profile_names") or []) or "none"),
        "backups: %s" % info.get("backup_count", 0),
        "control_bindings: %s" % (info.get("bindings") or "Not found"),
    ]
    health = info.get("health") or {}
    if health:
        lines += ["", "pc_health (read only):",
                  "  free_gb: %s" % health.get("free_gb", "Unknown"),
                  "  graphics: %s" % redact_user_text(health.get("gpu") or "Unknown"),
                  "  video_memory_gb: %s" % health.get("vram_gb", "Unknown"),
                  "  memory_gb: %s" % health.get("ram_gb", "Unknown"),
                  "  pagefile: %s" % health.get("pagefile", "Unknown"),
                  "  hags: %s" % health.get("hags", "Unknown"),
                  "  memory_integrity: %s" % health.get("memory_integrity", "Unknown"),
                  "  refresh_hz: %s" % health.get("refresh_hz", "Unknown")]
        for tip in (health.get("tips") or [])[:4]:
            lines.append("  tip: %s" % redact_user_text(tip))
    hw = info.get("hardware") or {}
    if hw:
        lines += ["", "hardware:",
                  "  graphics: %s" % redact_user_text(hw.get("gpu") or ""),
                  "  video_memory_gb: %s" % hw.get("vram_gb"),
                  "  processor: %s" % redact_user_text(hw.get("cpu") or ""),
                  "  memory_gb: %s" % hw.get("ram_gb"),
                  "  screen: %s x %s" % (hw.get("width") or "", hw.get("height") or "")]
        errs = [redact_user_text(e) for e in (hw.get("errors") or [])][:6]
        if errs:
            lines.append("  detection_notes:")
            lines += ["  - %s" % e for e in errs]
    lines += ["", "Not included: API keys, add-on lists, and your account name."]
    text = "\n".join(lines) + "\n"
    if re.search(r"sk-[A-Za-z0-9]{8,}|api[_-]?key\s*[:=]", text, re.I):
        raise ValueError("Diagnostic refused to include a key.")
    return text

def mask_personal(text):
    """Hide account names, mail addresses and tokens. Leaves the rest of a note readable."""
    s = redact_user_text(str(text or ""))
    s = re.sub(r"(?i)([A-Za-z]:\\Users\\)[^\\/\r\n]+", r"\1<user>", s)
    s = re.sub(r"(?i)([\\/]Users[\\/])[^\\/\r\n]+", r"\1<user>", s)
    s = re.sub(r"(?i)(/home/)[^/\s]+", r"\1<user>", s)
    s = re.sub(r"(?i)\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", "<email>", s)
    s = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "<token>", s)
    s = re.sub(r"(?i)((?:api[_-]?key|token|bearer)\s*[:=]\s*)\S+", r"\1<token>", s)
    return s

def _read_text_file(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    return data.decode("utf-8", "replace")

def support_pack_start_dir(env=None):
    """Desktop when that folder exists, otherwise Documents, otherwise the home folder."""
    env = os.environ if env is None else env
    home = env.get("USERPROFILE") or env.get("HOME") or os.path.expanduser("~")
    for name in ("Desktop", "Documents"):
        path = os.path.join(home, name)
        if os.path.isdir(path):
            return path
    return home

def _hardware_note(hw, health=None):
    hw = hw or {}
    lines = ["SkyTune PC check", "version: %s" % VERSION, ""]
    lines.append("graphics: %s" % (hw.get("gpu") or "not checked"))
    lines.append("video_memory_gb: %s" % (hw.get("vram_gb") if hw.get("vram_gb") else "not checked"))
    lines.append("processor: %s" % (hw.get("cpu") or "not checked"))
    lines.append("cores: %s" % (hw.get("cores") or "not checked"))
    lines.append("memory_gb: %s" % (hw.get("ram_gb") if hw.get("ram_gb") else "not checked"))
    if hw.get("width"):
        lines.append("screen: %s x %s" % (hw.get("width"), hw.get("height") or ""))
    errs = [mask_personal(e) for e in (hw.get("errors") or [])][:6]
    if errs:
        lines.append("detection_notes:")
        lines += ["- %s" % e for e in errs]
    health = health or {}
    if health:
        lines += ["", "pc_health (read only):",
                  "  free_gb: %s" % health.get("free_gb", "Unknown"),
                  "  pagefile: %s" % health.get("pagefile", "Unknown"),
                  "  hags: %s" % health.get("hags", "Unknown"),
                  "  memory_integrity: %s" % health.get("memory_integrity", "Unknown"),
                  "  refresh_hz: %s" % health.get("refresh_hz", "Unknown")]
    lines += ["", "This is the check SkyTune already stored. It does not change the PC."]
    return "\n".join(lines) + "\n"

def _cfg_text(path):
    try:
        return UserCfg.load(path).text()
    except Exception:
        return _read_text_file(path)

def _newest_backup_file(cfg_path):
    folder = os.path.join(os.path.dirname(cfg_path), "UserCfg_backups")
    if not os.path.isdir(folder):
        return ""
    try:
        names = [n for n in os.listdir(folder) if n.startswith("UserCfg_") and n.endswith(".opt")]
    except OSError:
        return ""
    if not names:
        return ""
    return os.path.join(folder, sorted(names)[-1])

def build_support_pack(cfg_path=None, edition=None, hw=None, health=None, state_path=None, now=None):
    """The files a support pack would contain. Reads SkyTune's own notes and the sim settings file. Writes nothing."""
    now = now or datetime.datetime.now()
    edition = edition if edition in ("2020", "2024") else "unknown"
    sim = {"2020": "MSFS 2020", "2024": "MSFS 2024"}.get(edition, "MSFS (not detected)")
    readme = (
        "SkyTune support pack\n"
        "version: %s\n"
        "sim: %s\n"
        "date: %s\n\n"
        "Account names in paths are written as <user>.\n"
        "This file stays on your PC. SkyTune does not upload it.\n"
    ) % (VERSION, sim, now.strftime("%Y-%m-%d"))
    files = [{"name": "README.txt", "text": readme},
             {"name": "hardware.txt", "text": mask_personal(_hardware_note(hw, health))}]
    if cfg_path and os.path.isfile(os.path.join(os.path.dirname(cfg_path), "UserCfg_backups", "SkyTune_log.txt")):
        log_path = os.path.join(os.path.dirname(cfg_path), "UserCfg_backups", "SkyTune_log.txt")
        files.append({"name": "SkyTune_log.txt", "text": mask_personal(_read_text_file(log_path))})
    snap = load_last_apply(state_path)
    if snap:
        files.append({"name": "last-apply.json", "text": mask_personal(json.dumps(snap, indent=1, sort_keys=True) + "\n")})
    if cfg_path and os.path.isfile(cfg_path):
        backup = _newest_backup_file(cfg_path)
        if backup:
            review = read_change_review(backup)
            if review:
                files.append({"name": "before-review.json",
                              "text": mask_personal(json.dumps(review, indent=1, sort_keys=True) + "\n")})
            before = _cfg_text(backup)
            if before:
                files.append({"name": "before-UserCfg.opt", "text": mask_personal(before)})
        current = _cfg_text(cfg_path)
        if current:
            files.append({"name": "UserCfg.opt", "text": mask_personal(current)})
    clean = []
    for item in files:
        text = mask_personal(item["text"])
        if re.search(r"sk-[A-Za-z0-9]{8,}", text):
            continue
        clean.append({"name": item["name"], "text": text})
    return clean

def support_pack_names(entries):
    """Archive names, in order, with no folders and no account paths."""
    names = []
    for item in entries or []:
        name = str(item.get("name") or "")
        if name and name == os.path.basename(name) and name not in names:
            names.append(name)
    return names

def write_support_pack(dest, entries):
    """Write the reviewed list into a zip. Names are the archive names only."""
    import zipfile
    kept = []
    for item in entries or []:
        name = str(item.get("name") or "")
        if not name or name != os.path.basename(name) or name in {n for n, _t in kept}:
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        kept.append((name, mask_personal(text)))
    if not kept:
        raise OSError("There is nothing to put in the support pack.")
    folder = os.path.dirname(os.path.abspath(dest)) or "."
    if not os.path.isdir(folder):
        raise OSError("That folder isn't there.")
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in kept:
            zf.writestr(name, text.encode("utf-8"))
    return [name for name, _text in kept]

# ---------------------------------------------------------------- other graphics mods (read only)
# SkyTune only looks for known filenames. It does not open, rename or delete those mods.
RESHADE_WARNING = (
    "ReShade is installed next to the simulator. It can draw over the picture, including DLSS, "
    "so what you see may not match the settings SkyTune saves. SkyTune does not change ReShade.")
OPTISCALER_WARNING = (
    "OptiScaler is installed. It can replace DLSS or frame generation with a different upscaler, "
    "so DLSS saved in your settings may not be what is running. SkyTune does not change OptiScaler.")
GLASS_DLSS_WARNING = (
    "The Glass Cockpit DLSS fix for MSFS 2024 is installed. It changes how DLSS draws cockpit screens. "
    "The DLSS choice is only saved in your settings. SkyTune does not change that mod.")
ATMOSPHERE_WARNING = (
    "AtmosphereMod is installed. It changes sky, haze and cloud lighting while the simulator runs, "
    "so those settings SkyTune saves may not be what you see. SkyTune does not change AtmosphereMod.")
GRAPHICS_MODS = (
    {"id": "reshade", "name": "ReShade", "files": ("ReShade.ini", "ReShade64.dll", "ReShade.log"), "warning": RESHADE_WARNING},
    {"id": "optiscaler", "name": "OptiScaler", "files": ("OptiScaler.ini", "OptiScaler.dll", "OptiScaler.log"), "warning": OPTISCALER_WARNING},
    {"id": "glass", "name": "Glass Cockpit DLSS fix",
     "files": ("glass-cockpit-dlss-fix.addon64", "glass-cockpit-dlss-fix.ini", "glass-cockpit-dlss-fix.log",
               "glass-cockpit-dlss-fix-status.txt"),
     "warning": GLASS_DLSS_WARNING},
    {"id": "atmosphere", "name": "AtmosphereMod", "files": ("AtmosphereMod.addon64",), "warning": ATMOSPHERE_WARNING},
)
SIM_EXE_NAMES = ("FlightSimulator.exe", "FlightSimulator2024.exe")

def _dir_names(folder):
    try:
        return {n.lower(): n for n in os.listdir(folder)}
    except OSError:
        return {}

def _named_file(folder, filenames):
    have = _dir_names(folder)
    for name in filenames:
        found = have.get(name.lower())
        if found and os.path.isfile(os.path.join(folder, found)):
            return found
    return ""

def _sim_edition_in(folder):
    have = _dir_names(folder)
    if "flightsimulator2024.exe" in have:
        return "2024"
    if "flightsimulator.exe" in have:
        return "2020"
    return ""

def sim_program_dirs(home=None, env=None):
    """Folders that contain a simulator executable. Reads directory names only."""
    env = os.environ if env is None else env
    home = home or env.get("HOME") or os.path.expanduser("~")
    found, seen = [], set()
    def add(folder):
        if not folder or not os.path.isdir(folder):
            return
        key = os.path.normcase(os.path.abspath(folder))
        if key in seen or not _sim_edition_in(folder):
            return
        seen.add(key)
        found.append(folder)
    for lib in steam_libraries(home):
        common = os.path.join(lib, "steamapps", "common")
        for name in _dir_names(common).values():
            add(os.path.join(common, name))
    if os.name == "nt":
        drive = env.get("SystemDrive") or "C:"
        if not drive.endswith("\\"):
            drive += "\\"
        for parts in (("XboxGames", "Microsoft Flight Simulator 2024", "Content"),
                      ("XboxGames", "Microsoft Flight Simulator", "Content")):
            add(os.path.join(drive, *parts))
    return found

def find_graphics_mods(cfg=None, edition=None, program_dirs=None, community=None, env=None):
    """Known graphics mods that can sit on top of a saved setting. Does not change any file."""
    env = os.environ if env is None else env
    if program_dirs is None:
        program_dirs = sim_program_dirs(env=env)
    if community is None and cfg is not None:
        community = community_path(cfg)
    edition = edition if edition in ("2020", "2024", "unknown") else "unknown"
    found, seen = [], set()
    def add(spec, filename):
        if spec["id"] in seen:
            return
        seen.add(spec["id"])
        found.append({"id": spec["id"], "name": spec["name"], "file": filename, "warning": spec["warning"]})
    for folder in program_dirs or []:
        folder_edition = _sim_edition_in(folder)
        if edition in ("2020", "2024") and folder_edition and folder_edition != edition:
            continue
        for spec in GRAPHICS_MODS:
            if spec["id"] == "glass" and (edition == "2020" or folder_edition == "2020"):
                continue
            hit = _named_file(folder, spec["files"])
            if hit:
                add(spec, hit)
    atmosphere = next(spec for spec in GRAPHICS_MODS if spec["id"] == "atmosphere")
    local = env.get("LOCALAPPDATA")
    if local and os.path.isfile(os.path.join(local, "AtmosphereMod", "tunables.ini")):
        add(atmosphere, "tunables.ini")
    if community and os.path.isdir(community):
        for name in _dir_names(community).values():
            if "atmospheremod" in name.lower() and os.path.isdir(os.path.join(community, name)):
                add(atmosphere, name)
                break
    return found

def graphics_mod_warnings(found):
    lines = []
    for item in found or []:
        text = item.get("warning") or ""
        if text and text not in lines:
            lines.append(text)
    return lines

# ---------------------------------------------------------------- backups
def backup_dir(cfg_path):
    d = os.path.join(os.path.dirname(cfg_path), "UserCfg_backups")
    os.makedirs(d, exist_ok=True)
    return d

def copy_bytes(src, dst):
    """Copy a settings file by reading and writing it. Python 3.12's shutil.copy2 calls CopyFile2.
    Wine treats that missing call as a fatal abort, so a confirmed write never finishes. A normal read and write does."""
    with open(src, "rb") as f:
        data = f.read()
    tmp = dst + ".copytmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dst)
    return dst

def make_backup(cfg_path):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dst = os.path.join(backup_dir(cfg_path), "UserCfg_%s.opt" % ts)
    copy_bytes(cfg_path, dst)
    return dst

def list_backups(cfg_path):
    return sorted(glob.glob(os.path.join(backup_dir(cfg_path), "UserCfg_*.opt")))

def write_with_backup(cfg, cfg_path, review=None):
    """Backup, then replace the file atomically. A read-only, missing, or locked file is left untouched."""
    blocked = write_blocked(cfg_path)
    if blocked:
        raise OSError(blocked)
    b = make_backup(cfg_path)
    cfg.save(cfg_path)
    if review:
        try:
            write_change_review(b, review.get("reason") or "apply", review.get("changes") or [],
                                edition=review.get("edition") or "unknown", profile=review.get("profile") or "",
                                warnings=review.get("warnings") or (), verified=True)
        except Exception:
            pass
    return b

# ---------------------------------------------------------------- v1.4.0 saved profiles, change review, verified restore
# Profiles remember a named graphics setup on this PC. They are not written to the sim until the user confirms.
# Reviews sit beside backups and record before/after labels only — no file paths, user names, or API keys.
PROFILE_FORMAT, PROFILE_FORMAT_VERSION = "skytune-profile", 1
REVIEW_FORMAT, REVIEW_FORMAT_VERSION = "skytune-review", 1
MAX_PROFILES, MAX_PROFILE_BYTES, MAX_PROFILE_NAME, MAX_PROFILE_NOTE = 24, 65536, 40, 240
SKIP_PROFILE_PATHS = ("Video/FullScreenResolution", "Video/Resolution")
REASON_PLAIN = {"optimise": "optimise", "assistant": "assistant fix", "profile": "saved profile", "restore": "restore",
                "worse": "undo after Worse", "repair": "repair a damaged file", "manual": "advanced apply", "apply": "apply"}

def remembered_cfg():
    """A settings file the user picked earlier, if it is still there. Kept out of state.json so that note stays free of paths."""
    try:
        with open(os.path.join(skytune_data_dir(), "remembered_cfg.txt"), encoding="utf-8") as f:
            path = f.read().strip()
    except OSError:
        return ""
    return path if path and os.path.isfile(path) else ""

def remember_cfg(path):
    if not path:
        return False
    dest = os.path.join(skytune_data_dir(), "remembered_cfg.txt")
    try:
        atomic_write(dest, (path.strip() + "\n").encode("utf-8"))
        return True
    except OSError:
        return False

def skytune_data_dir(env=None):
    """SkyTune's own folder, next to state.json. Windows: %APPDATA%\\SkyTune. Elsewhere: ~/SkyTune."""
    env = os.environ if env is None else env
    base = env.get("APPDATA") or env.get("HOME") or os.path.expanduser("~")
    d = os.path.join(base, "SkyTune")
    os.makedirs(d, exist_ok=True)
    return d

def profiles_dir(env=None):
    d = os.path.join(skytune_data_dir(env), "profiles")
    os.makedirs(d, exist_ok=True)
    return d

def profile_slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", _clean_str(name, MAX_PROFILE_NAME).lower()).strip("-")[:32]
    return s or "profile"

def _setting_bounds(path):
    """Widest allowed range for a known setting. Duplicate rows (in-game and beyond-menu) are combined."""
    specs = [s for s in SETTINGS if s[0] == path]
    if not specs: return None
    kind = specs[0][3]
    if kind == "text": return {"kind": "text"}
    if kind == "choice":
        labels, codes = {}, {}
        for s in specs:
            for lab, val in (s[4] or {}).items():
                labels[str(lab).lower()] = val
                codes[str(val).lower()] = val
        return {"kind": "choice", "labels": labels, "codes": codes}
    los, his = [], []
    for s in specs:
        lo, hi, _step = s[4]
        los.append(float(lo)); his.append(float(hi))
    return {"kind": kind, "lo": min(los), "hi": max(his)}

def coerce_setting(path, raw):
    """Return (internal value, error). Internal values are what apply_values already accepts."""
    if path in SKIP_PROFILE_PATHS: return None, "display resolution is kept out of profiles"
    bounds = _setting_bounds(path)
    if not bounds: return None, "not a setting SkyTune changes"
    if bounds["kind"] == "text": return None, "not saved in a profile"
    if isinstance(raw, bool) or isinstance(raw, (dict, list, tuple)): return None, "not a valid value"
    if bounds["kind"] == "choice":
        key = str(raw).strip().lower()
        if key in bounds["codes"]: return bounds["codes"][key], None
        if key in bounds["labels"]: return bounds["labels"][key], None
        n = _num(raw)
        if n is not None:
            for val in bounds["codes"].values():
                if isinstance(val, (int, float)) and not isinstance(val, bool) and float(val) == n: return val, None
        return None, "not one of the allowed choices"
    n = _num(raw)
    if n is None or n != n or n in (float("inf"), float("-inf")): return None, "not a number"
    if n < bounds["lo"] - 1e-9 or n > bounds["hi"] + 1e-9: return None, "outside %s–%s" % (bounds["lo"], bounds["hi"])
    if bounds["kind"] == "int": return int(round(n)), None
    return float(n), None

def clean_profile_values(values):
    """Keep only whitelisted, in-range settings. Everything else is listed and dropped."""
    clean, rejected = {}, []
    if not isinstance(values, dict): return clean, [("values", "not an object")]
    items = list(values.items())
    for path, raw in items[:80]:
        val, err = coerce_setting(str(path), raw)
        if err: rejected.append((str(path), err)); continue
        clean[str(path)] = val
    if len(items) > 80: rejected.append(("…", "too many settings; extras were left out"))
    return clean, rejected

def _parse_stamp(s):
    try: return datetime.datetime.fromisoformat(str(s))
    except Exception: return datetime.datetime.now()

def build_profile(name, values, note="", goal=None, edition=None, source="current", now=None):
    """Validated profile document. Raises ValueError with a sentence the UI can show."""
    name = _clean_str(name, MAX_PROFILE_NAME)
    if not name: raise ValueError("Give the profile a name.")
    if re.search(r"[\\/]", name): raise ValueError("The name can't include a folder path.")
    note = _clean_str(note, MAX_PROFILE_NOTE)
    clean, rejected = clean_profile_values(values)
    if not clean: raise ValueError("Nothing in this setup can be saved as a profile.")
    if re.search(r"(api[_-]?key\s*[:=]|bearer\s+\S|sk-[A-Za-z0-9]{8,})", note, re.I): note = ""
    rejected = ["%s: %s" % (_setting_key(p) or "setting", _review_text(e, 80) or "left out") for p, e in rejected][:12]
    if goal not in GOALS: goal = None
    if edition not in ("2020", "2024", "unknown"): edition = None
    if source not in ("current", "pending", "import"): source = "current"
    now = now or datetime.datetime.now()
    return {"format": PROFILE_FORMAT, "format_version": PROFILE_FORMAT_VERSION, "app": SHORT_NAME, "app_version": VERSION,
            "name": name, "note": note, "goal": goal, "edition": edition, "source": source,
            "created": now.isoformat(timespec="seconds"), "values": clean, "rejected": rejected}

def validate_profile_document(data):
    """(profile, errors). Extra fields such as keys or paths are dropped. A bad document returns (None, [reason])."""
    if not isinstance(data, dict): return None, ["This file is not a SkyTune profile."]
    if data.get("format") != PROFILE_FORMAT or data.get("format_version") != PROFILE_FORMAT_VERSION:
        return None, ["This file is not a SkyTune profile (version %s)." % PROFILE_FORMAT_VERSION]
    source = data.get("source") if data.get("source") in ("current", "pending", "import") else "import"
    try:
        profile = build_profile(data.get("name"), data.get("values") or {}, note=data.get("note") or "",
                                 goal=data.get("goal"), edition=data.get("edition"), source=source,
                                 now=_parse_stamp(data.get("created")))
    except ValueError as e:
        return None, [str(e)]
    return profile, []

def _profile_path(directory, slug):
    if not re.fullmatch(r"[a-z0-9-]{1,40}", slug or ""): raise ValueError("Bad profile name.")
    os.makedirs(directory, exist_ok=True)
    base = os.path.realpath(directory)
    path = os.path.realpath(os.path.join(base, slug + ".json"))
    if os.path.normcase(os.path.dirname(path)) != os.path.normcase(base): raise ValueError("Bad profile name.")
    return path

def _assign_profile_id(profile, stem):
    profile["id"] = stem if re.fullmatch(r"[a-z0-9-]{1,40}", stem or "") else profile_slug(profile.get("name") or "")
    return profile

def list_profiles(directory=None, env=None):
    """Valid profiles only, by name. A broken file is skipped so one bad save can't hide the rest."""
    directory = directory or profiles_dir(env)
    out = []
    if not os.path.isdir(directory): return out
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"): continue
        path = os.path.join(directory, fname)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > MAX_PROFILE_BYTES: continue
            with open(path, encoding="utf-8") as f: data = json.load(f)
            profile, _errs = validate_profile_document(data)
            if not profile: continue
            _assign_profile_id(profile, os.path.splitext(fname)[0])
            profile["path"] = path
            out.append(profile)
        except Exception:
            continue
    out.sort(key=lambda p: (p.get("name") or "").lower())
    return out

def load_profile(directory, profile_id, env=None):
    directory = directory or profiles_dir(env)
    if not re.fullmatch(r"[a-z0-9-]{1,40}", profile_id or ""): return None
    try: path = _profile_path(directory, profile_id)
    except ValueError: return None
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_PROFILE_BYTES: return None
        with open(path, encoding="utf-8") as f: data = json.load(f)
    except (OSError, ValueError): return None
    profile, _errs = validate_profile_document(data)
    if not profile: return None
    _assign_profile_id(profile, profile_id); profile["path"] = path
    return profile

def save_profile(profile, directory=None, replace=False, env=None):
    """Write a profile atomically. Refuses a 25th profile and refuses to overwrite unless replace=True."""
    directory = directory or profiles_dir(env)
    os.makedirs(directory, exist_ok=True)
    existing = list_profiles(directory)
    same = [p for p in existing if p["name"].lower() == profile["name"].lower()]
    if same and not replace:
        raise ValueError("A profile named \"%s\" is already saved. Delete it or choose another name." % profile["name"])
    if not same and len(existing) >= MAX_PROFILES:
        raise ValueError("You already have %d profiles. Delete one before saving another." % MAX_PROFILES)
    slug = same[0]["id"] if same else profile_slug(profile["name"])
    if not same:
        taken = {p["id"] for p in existing}; base, n = slug, 2
        while slug in taken: slug = "%s-%d" % (base, n); n += 1
    doc = {k: profile[k] for k in ("format", "format_version", "app", "app_version", "name", "note", "goal", "edition",
                                   "source", "created", "values")}
    if profile.get("rejected"): doc["rejected"] = list(profile["rejected"])[:12]
    doc["id"] = slug
    raw = json.dumps(doc, indent=1, sort_keys=True).encode("utf-8")
    if len(raw) > MAX_PROFILE_BYTES: raise ValueError("This profile is too large to save.")
    path = _profile_path(directory, slug)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f: f.write(raw)
    os.replace(tmp, path)
    doc["path"] = path
    return doc

def delete_profile(directory, profile_id, env=None):
    directory = directory or profiles_dir(env)
    if not re.fullmatch(r"[a-z0-9-]{1,40}", profile_id or ""): return False
    try: path = _profile_path(directory, profile_id)
    except ValueError: return False
    if not os.path.isfile(path): return False
    os.remove(path)
    return True

def read_profile_file(path):
    """Import check. Does not save and does not follow a file over the size cap."""
    if not path or not os.path.isfile(path): return None, ["That file is missing."]
    try:
        if os.path.getsize(path) > MAX_PROFILE_BYTES: return None, ["That file is too large to be a SkyTune profile."]
        with open(path, encoding="utf-8") as f: data = json.load(f)
    except Exception:
        return None, ["That file isn't valid JSON."]
    return validate_profile_document(data)

def export_profile(profile, dest_path):
    """Portable JSON: no id, no path, no rejected-key notes."""
    doc = {k: profile[k] for k in ("format", "format_version", "app", "app_version", "name", "note", "goal", "edition",
                                   "source", "created", "values") if k in profile}
    raw = json.dumps(doc, indent=1, sort_keys=True).encode("utf-8")
    parent = os.path.dirname(os.path.abspath(dest_path))
    if parent: os.makedirs(parent, exist_ok=True)
    tmp = dest_path + ".tmp"
    with open(tmp, "wb") as f: f.write(raw)
    os.replace(tmp, dest_path)
    return dest_path

def profile_apply_plan(cfg, profile):
    """What Use would stage. Does not modify cfg. Keys missing from this sim file are reported, not added."""
    values = profile.get("values") or {}
    applicable = {p: v for p, v in values.items() if p in getattr(cfg, "index", {})}
    changes = summarize_changes(cfg, applicable, change_resolution=False)
    absent = []
    for p in values:
        if p not in cfg.index: absent.append(PLAIN.get(p) or p.split("/")[-1])
    return {"changes": changes, "absent": absent, "values": applicable}

def setting_label(path):
    return PLAIN.get(path) or next((x[1] for x in SETTINGS if x[0] == path), path.rsplit("/", 1)[-1])

def diff_known_settings(before_cfg, after_cfg):
    """Recognised settings (plus Graphics preset) whose raw value differs. Order follows SETTINGS."""
    rows, seen = [], set()
    for path in [s[0] for s in SETTINGS] + ["Graphics/Preset"]:
        if path in seen: continue
        seen.add(path)
        if before_cfg is None or after_cfg is None: continue
        if path not in before_cfg.index or path not in after_cfg.index: continue
        old, new = before_cfg.get(path), after_cfg.get(path)
        if old == new: continue
        rows.append({"path": path, "label": setting_label(path), "before": _display(path, old), "after": _display(path, new),
                     "before_raw": old, "after_raw": new})
    return rows

def diff_tuples(rows):
    return [(r["label"], r["before"], r["after"]) for r in rows]

def confirm_summary(changes, warnings=(), intro="", limit=8):
    """Short text for the Yes/No dialog. The full list stays in Step 3 or Review backups."""
    lines = []
    if intro: lines += [intro, ""]
    for w in warnings: lines.append("Note: " + w)
    if warnings: lines.append("")
    changes = list(changes or [])
    if not changes: lines.append("No recognised graphics settings would change.")
    else:
        lines.append("%d setting%s:" % (len(changes), "" if len(changes) == 1 else "s"))
        for item in changes[:limit]:
            lab, old, new = (item["label"], item["before"], item["after"]) if isinstance(item, dict) else item[:3]
            lines.append("• %s: %s → %s" % (lab, old, new))
        extra = len(changes) - limit
        if extra > 0: lines.append("• and %d more" % extra)
    lines += ["", "Nothing is written until you choose Yes. A backup is kept first."]
    return "\n".join(lines)

def _review_text(s, n):
    """Plain text for a review note. Drops filesystem paths so a note can't smuggle a user folder."""
    s = _clean_str(s, n)
    if not s or re.search(r"[\\]|[A-Za-z]:", s) or s.startswith("/") or s.startswith("~"): return ""
    return s

def _setting_key(path):
    path = str(path or "")
    return path if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(/[A-Za-z][A-Za-z0-9]*)+", path) else ""

def file_sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
    return h.hexdigest()

def review_sidecar(backup_path):
    root, _ext = os.path.splitext(backup_path)
    return root + ".review.json"

def write_change_review(backup_path, reason, changes, edition="unknown", profile="", warnings=(), verified=False):
    """Sidecar next to a backup. Stores labels and a content hash, not paths or secrets."""
    blob_bits = [str(reason or ""), str(profile or "")] + [str(w) for w in (warnings or [])]
    sensitive = re.compile(r"(api[_-]?key\s*[:=]|bearer\s+\S|sk-[A-Za-z0-9]{8,}|password\s*[:=])", re.I)
    if any(sensitive.search(b) for b in blob_bits):
        reason, profile, warnings, changes = "change", "", ["A review note was left out because it looked sensitive."], []
    rows = []
    for item in list(changes or [])[:80]:
        if isinstance(item, dict):
            label = _review_text(item.get("label"), 80) or _review_text(setting_label(item.get("path") or ""), 80)
            rows.append({"path": _setting_key(item.get("path")), "label": label,
                         "before": _review_text(item.get("before"), 40), "after": _review_text(item.get("after"), 40)})
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            rows.append({"path": "", "label": _review_text(item[0], 80), "before": _review_text(item[1], 40),
                         "after": _review_text(item[2], 40)})
    try: digest = file_sha256(backup_path)
    except OSError: digest = ""
    doc = {"format": REVIEW_FORMAT, "format_version": REVIEW_FORMAT_VERSION, "app_version": VERSION,
           "time": datetime.datetime.now().isoformat(timespec="seconds"),
           "reason": _review_text(reason, 80) or "change",
           "edition": edition if edition in ("2020", "2024", "unknown") else "unknown",
           "backup": os.path.basename(backup_path), "profile": _review_text(profile, MAX_PROFILE_NAME),
           "verified": bool(verified), "sha256": digest,
           "warnings": [w for w in (_review_text(x, 180) for x in list(warnings)[:8]) if w],
           "changes": rows}
    path = review_sidecar(backup_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(doc, f, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return doc

def read_change_review(backup_path):
    path = review_sidecar(backup_path)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MAX_PROFILE_BYTES: return None
        with open(path, encoding="utf-8") as f: data = json.load(f)
        if not isinstance(data, dict) or data.get("format") != REVIEW_FORMAT: return None
        return data
    except Exception:
        return None

def backup_label(path, review=None):
    """One list row: local time, why the backup was made, and the saved profile name when there is one."""
    base = os.path.basename(path or "")
    found = re.match(r"UserCfg_(\d{8})-(\d{6})", base)
    when = base
    if found:
        d, t = found.group(1), found.group(2)
        when = "%s-%s-%s %s:%s:%s" % (d[:4], d[4:6], d[6:8], t[:2], t[2:4], t[4:6])
    review = review or {}
    if review.get("edition") in ("2020", "2024"): tail = " · MSFS " + review["edition"]
    else: tail = ""
    if review.get("profile"): tail += " · " + review["profile"]
    elif review.get("reason"): tail = " · " + REASON_PLAIN.get(review["reason"], review["reason"])
    else: tail = ""
    n = review.get("changes")
    if isinstance(n, list) and n: tail += " · %d" % len(n)
    return when + tail

def plan_restore(cfg_path, backup_path):
    """Describe a restore without writing. ok=False means the file must not be copied back."""
    empty = {"ok": False, "error": "", "changes": [], "warnings": [], "rows": [], "saved_review": None,
             "edition": "unknown", "current_edition": "unknown", "backup_name": os.path.basename(backup_path or "")}
    if not backup_path or not os.path.isfile(backup_path):
        empty["error"] = "That backup file is missing."; return empty
    try:
        if cfg_path and os.path.isfile(cfg_path) and os.path.samefile(cfg_path, backup_path):
            empty["error"] = "That is the current settings file, not a backup."; return empty
    except OSError:
        pass
    problem = cfg_problem(backup_path)
    if problem:
        empty["error"] = "This backup can't be used (%s)." % problem; return empty
    try: backup_cfg = UserCfg.load(backup_path)
    except Exception as e:
        empty["error"] = "This backup can't be read (%s)." % e; return empty
    bed = detect_simulator_version(backup_path, backup_cfg)
    warnings, rows = [], []
    current_problem = cfg_problem(cfg_path) if cfg_path else "missing"
    if current_problem:
        warnings.append("The current settings file is %s. Restoring replaces the whole file." % current_problem)
        ced = detect_simulator_version(cfg_path) if cfg_path else "unknown"
    else:
        current_cfg = UserCfg.load(cfg_path)
        ced = detect_simulator_version(cfg_path, current_cfg)
        rows = diff_known_settings(current_cfg, backup_cfg)
    if ced in ("2020", "2024") and bed in ("2020", "2024") and ced != bed:
        warnings.append("This backup looks like MSFS %s, and the current file looks like MSFS %s." % (bed, ced))
    saved = read_change_review(backup_path)
    if saved and saved.get("sha256"):
        try:
            if file_sha256(backup_path) != saved["sha256"]:
                warnings.append("This backup file has changed since SkyTune wrote the review note. The difference below is what is in the file now.")
        except OSError:
            pass
    return {"ok": True, "error": None, "rows": rows, "changes": diff_tuples(rows), "warnings": warnings, "saved_review": saved,
            "edition": bed, "current_edition": ced, "backup_name": os.path.basename(backup_path)}

def _files_match_parsed(left_path, right_path):
    # Test seam only: SKYTUNE_RESTORE_CHECK=fail forces the rollback path. Normal launches never set it.
    if os.environ.get("SKYTUNE_RESTORE_CHECK") == "fail":
        return False
    left, right = UserCfg.load(left_path), UserCfg.load(right_path)
    if set(left.index) != set(right.index): return False
    return all(left.get(k) == right.get(k) for k in left.index)

def apply_restore(cfg_path, backup_path, reason="restore"):
    """Put a backup back. The current file is copied aside first. If the result doesn't match the backup, that copy is put back.
    Never raises. Does not ask — the caller has to confirm."""
    blocked = restore_blocked(cfg_path)
    if blocked:
        return {"ok": False, "error": blocked, "verified": False, "safety": None, "changes": [], "warnings": []}
    plan = plan_restore(cfg_path, backup_path)
    if not plan["ok"]:
        return {"ok": False, "error": plan["error"], "verified": False, "safety": None, "changes": [], "warnings": []}
    safety = None
    try:
        if cfg_path and os.path.isfile(cfg_path): safety = make_backup(cfg_path)
        copy_bytes(backup_path, cfg_path)
        if cfg_problem(cfg_path) or not _files_match_parsed(cfg_path, backup_path):
            raise ValueError("the restored file does not match the backup")
    except Exception as e:
        if safety and os.path.isfile(safety):
            try: copy_bytes(safety, cfg_path)
            except OSError: pass
        return {"ok": False, "error": "Restore failed, so your previous file was put back (%s)." % e, "verified": False,
                "safety": safety, "changes": plan["changes"], "warnings": plan["warnings"]}
    if safety:
        try:
            write_change_review(safety, reason, plan["rows"], edition=plan.get("edition") or "unknown",
                                warnings=plan["warnings"], verified=True)
        except OSError:
            pass
    return {"ok": True, "error": None, "verified": True, "safety": safety, "changes": plan["changes"],
            "warnings": plan["warnings"], "rows": plan["rows"], "backup_name": plan["backup_name"]}

# ---------------------------------------------------------------- update cleanup
SAFE_DEFAULT_PRESET = "Balanced"

def installed_packages_path(cfg):
    v = cfg.get("InstalledPackagesPath")
    if not v: return None
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"': v = v[1:-1]
    return v or None

def community_path(cfg):
    p = installed_packages_path(cfg)
    return os.path.join(p, "Community") if p else None

def _log(log_path, msg):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass

def log_path_for(cfg_path):
    return os.path.join(backup_dir(cfg_path), "SkyTune_log.txt")

def _state_path(cfg_path):
    return os.path.join(backup_dir(cfg_path), "last_update_cleanup.json")

def old_community_name(parent, now=None):
    base = os.path.join(parent, "Community-old")
    if not os.path.exists(base): return base
    ts = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M")
    p = base + "-" + ts; n = 2
    while os.path.exists(p): p = "%s-%s-%d" % (base, ts, n); n += 1
    return p

def plan_update_cleanup(cfg_path, reset_graphics=False, env=None):
    """Pre-flight: returns dict(ok, errors, community, rename_to, caches, reset_graphics). Changes nothing."""
    errors = []
    try: cfg = UserCfg.load(cfg_path)
    except Exception as e: return {"ok": False, "errors": ["Can't read UserCfg.opt: %s" % e]}
    comm = community_path(cfg)
    if not comm: errors.append("UserCfg.opt has no InstalledPackagesPath, so the Community folder can't be found.")
    elif _is_link(comm): errors.append("The Community folder is a link/junction – SkyTune won't rename it. Move it manually.")
    elif not os.path.isdir(comm): errors.append("Community folder not found at %s" % comm)
    elif not os.access(os.path.dirname(comm), os.W_OK): errors.append("No permission to rename folders in %s" % os.path.dirname(comm))
    items = resolve_cache_items(env)
    return {"ok": not errors, "errors": errors, "community": comm,
            "rename_to": old_community_name(os.path.dirname(comm)) if comm and not errors else None,
            "caches": update_cleanup_items(items), "whitelist": items, "reset_graphics": reset_graphics}

def run_update_cleanup(cfg_path, plan_):
    """Do it. Reversible steps first; any failure rolls back what was done. Returns dict(ok, error, ...)."""
    log = log_path_for(cfg_path); done = {"backup": None, "renamed": False, "created": False}
    comm, old = plan_["community"], plan_["rename_to"]
    _log(log, "Update Cleanup started (community=%s, reset_graphics=%s)" % (comm, plan_["reset_graphics"]))
    try:
        done["backup"] = make_backup(cfg_path); _log(log, "Backed up UserCfg.opt to %s" % done["backup"])
        os.rename(comm, old); done["renamed"] = True; _log(log, "Renamed %s -> %s" % (comm, old))
        os.mkdir(comm); done["created"] = True; _log(log, "Created empty %s" % comm)
        if plan_["reset_graphics"]:
            cfg = UserCfg.load(cfg_path)
            ch = apply_values(cfg, with_user_choices(PRESETS[SAFE_DEFAULT_PRESET]))
            write_with_backup(cfg, cfg_path); _log(log, "Reset graphics to %s (%d values)" % (SAFE_DEFAULT_PRESET, len(ch)))
    except Exception as e:
        _log(log, "ERROR: %s – rolling back" % e)
        try:
            if done["created"] and os.path.isdir(comm) and not os.listdir(comm): os.rmdir(comm)
            if done["renamed"] and not os.path.exists(comm): os.rename(old, comm)
            if done["backup"]: copy_bytes(done["backup"], cfg_path)
            _log(log, "Rollback complete – nothing changed")
        except Exception as e2:
            _log(log, "ROLLBACK FAILED: %s" % e2)
            return {"ok": False, "error": "%s (and rollback failed: %s – see log %s)" % (e, e2, log)}
        return {"ok": False, "error": str(e)}
    freed = skipped = 0
    for it in plan_["caches"]:
        r = clear_item(it, plan_["whitelist"]); freed += r["freed"]; skipped += len(r["skipped"])
        _log(log, "Cleared %s: %d bytes, %d skipped" % (it["title"], r["freed"], len(r["skipped"])))
    state = {"community": comm, "renamed_to": old, "backup": done["backup"],
             "time": datetime.datetime.now().isoformat(timespec="seconds")}
    import json
    with open(_state_path(cfg_path), "w", encoding="utf-8") as f: json.dump(state, f)
    _log(log, "Update Cleanup finished")
    return {"ok": True, "freed": freed, "skipped": skipped, "renamed_to": old, "backup": done["backup"], "log": log}

def undo_state(cfg_path):
    import json
    try:
        with open(_state_path(cfg_path), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return None

def undo_update_cleanup(cfg_path, merge_new=True):
    """Restore the old Community folder name and the UserCfg backup.
    If the new Community folder has contents: merge_new=True moves them into the restored folder (name clashes are
    kept in 'Community-new-<ts>'); merge_new=False aborts. Returns dict(ok, error, moved, conflicts)."""
    st = undo_state(cfg_path); log = log_path_for(cfg_path)
    if not st: return {"ok": False, "error": "No Update Cleanup to undo."}
    comm, old = st["community"], st["renamed_to"]
    if not os.path.isdir(old): return {"ok": False, "error": "The renamed folder %s is missing." % old}
    moved, conflicts = [], []
    new_items = os.listdir(comm) if os.path.isdir(comm) else []
    if new_items and not merge_new:
        return {"ok": False, "error": "The new Community folder has add-ons in it.", "needs_merge": True}
    _log(log, "Undo Update Cleanup started")
    try:
        for name in new_items:
            src, dst = os.path.join(comm, name), os.path.join(old, name)
            if os.path.exists(dst): conflicts.append(name); continue
            shutil.move(src, dst); moved.append(name); _log(log, "Moved %s back into %s" % (name, old))
        if os.path.isdir(comm):
            if os.listdir(comm):
                keep = comm + "-new-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                os.rename(comm, keep); _log(log, "Name clashes kept in %s" % keep)
            else:
                os.rmdir(comm)
        os.rename(old, comm); _log(log, "Renamed %s -> %s" % (old, comm))
    except Exception as e:
        _log(log, "ERROR during undo: %s" % e)
        return {"ok": False, "error": str(e), "moved": moved, "conflicts": conflicts}
    if st.get("backup") and os.path.isfile(st["backup"]):
        make_backup(cfg_path); copy_bytes(st["backup"], cfg_path); _log(log, "Restored UserCfg.opt from %s" % st["backup"])
    os.remove(_state_path(cfg_path)); _log(log, "Undo finished")
    return {"ok": True, "moved": moved, "conflicts": conflicts}

def app_state_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "SkyTune"); os.makedirs(d, exist_ok=True)
    return os.path.join(d, "state.json")



# ---------------------------------------------------------------- cache cleaner
# Only folders/files confirmed by sources (see README). Folder items: contents are deleted, the folder is kept.
CACHE_ITEMS = [
    {"id": "rolling_steam", "edition": "Steam", "kind": "file", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator 2024", "ROLLINGCACHE.CCC"), "default": False,
     "title": "Rolling cache (Steam)",
     "explain": "Scenery the sim downloaded while you flew. MSFS 2024 makes a fresh one next launch. Clear it if scenery "
                "looks wrong or you want the disk space back. Its size is set in the sim (Options › General)."},
    {"id": "simcache_steam", "edition": "Steam", "kind": "dir", "base": "APPDATA", "stutter": "MSFS forums: 'What are the exact steps to clear all shader caches?' (t/738164) and 'How do you delete the shader cache in FS2024?' (t/773731)",
     "rel": ("Microsoft Flight Simulator 2024", "cache"), "default": True,
     "title": "Sim cache folder (Steam)", "explain": "Temporary files the sim rebuilds by itself (incl. rolling-cache helper "
                "files). Users clear it with the shader caches to fix stutters after updates or driver changes."},
    {"id": "sceneryidx_steam", "edition": "Steam", "kind": "dir", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator 2024", "SceneryIndexes"), "default": False,
     "update": True,
     "title": "Scenery indexes (Steam)", "explain": "Index of installed scenery. Rebuilt on next launch (first start is "
                "slower) – fixes missing or wrong add-on scenery, especially after an update. Not a stutter fix."},
    {"id": "rolling_store", "edition": "MS Store / Xbox", "kind": "file", "base": "LOCALAPPDATA", "stutter": None,
     "rel": ("Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache", "ROLLINGCACHE.CCC"), "default": False,
     "title": "Rolling cache (MS Store / Xbox)", "explain": "Same as the Steam rolling cache, for the MS Store / Xbox app version."},
    {"id": "sceneryidx_store", "edition": "MS Store / Xbox", "kind": "dir", "base": "LOCALAPPDATA", "stutter": None,
     "rel": ("Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache", "SceneryIndexes"), "default": False,
     "update": True,
     "title": "Scenery indexes (MS Store / Xbox)", "explain": "Index of installed scenery. Rebuilt on next launch – fixes "
                "missing add-on scenery after an update. Not a stutter fix."},
    {"id": "simcache_store", "edition": "MS Store / Xbox", "kind": "dir", "base": "LOCALAPPDATA", "stutter": "MSFS forums: 'What are the exact steps to clear all shader caches?' (t/738164) and 'How do you delete the shader cache in FS2024?' (t/773731)",
     "rel": ("Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalState", "cache"), "default": True,
     "title": "Sim cache folder (MS Store / Xbox)", "explain": "Temporary files the sim rebuilds by itself. Cleared with "
                "the shader caches to fix stutters."},
    {"id": "oldcrashes_steam", "edition": "Steam", "kind": "dir", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator 2024", "AsoboReport-OldCrashes"), "default": False,
     "title": "Old crash reports (Steam)", "explain": "Copies of past crash reports. Only diagnostics – safe to clear for "
                "disk space; does not affect stutters."},
    # ---- MSFS 2020 (only offered when the selected UserCfg.opt is a 2020 file)
    {"id": "rolling_steam_2020", "edition": "MSFS 2020 / Steam", "kind": "file", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator", "ROLLINGCACHE.CCC"), "default": False,
     "title": "Rolling cache (MSFS 2020 Steam)",
     "explain": "Downloaded scenery cache for MSFS 2020. Recreated by the sim; clear only when scenery is wrong or to reclaim disk space."},
    {"id": "simcache_steam_2020", "edition": "MSFS 2020 / Steam", "kind": "dir", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator", "cache"), "default": False,
     "title": "Sim cache folder (MSFS 2020 Steam)",
     "explain": "Temporary simulator cache. Optional; files are rebuilt by the sim."},
    {"id": "sceneryidx_steam_2020", "edition": "MSFS 2020 / Steam", "kind": "dir", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator", "SceneryIndexes"), "default": False, "update": True,
     "title": "Scenery indexes (MSFS 2020 Steam)",
     "explain": "Scenery indexes are rebuilt after clearing; the first launch may be slower."},
    {"id": "rolling_store_2020", "edition": "MSFS 2020 / MS Store / Xbox", "kind": "file", "base": "LOCALAPPDATA", "stutter": None,
     "rel": ("Packages", STORE_PKG_2020, "LocalCache", "ROLLINGCACHE.CCC"), "default": False,
     "title": "Rolling cache (MSFS 2020 Store/Xbox)",
     "explain": "Downloaded scenery cache for MSFS 2020. Recreated by the sim; clear only when scenery is wrong or to reclaim disk space."},
    {"id": "simcache_store_2020", "edition": "MSFS 2020 / MS Store / Xbox", "kind": "dir", "base": "LOCALAPPDATA", "stutter": None,
     "rel": ("Packages", STORE_PKG_2020, "LocalCache", "cache"), "default": False,
     "title": "Sim cache folder (MSFS 2020 Store/Xbox)",
     "explain": "Temporary simulator cache. Optional; files are rebuilt by the sim."},
    {"id": "sceneryidx_store_2020", "edition": "MSFS 2020 / MS Store / Xbox", "kind": "dir", "base": "LOCALAPPDATA", "stutter": None,
     "rel": ("Packages", STORE_PKG_2020, "LocalCache", "SceneryIndexes"), "default": False, "update": True,
     "title": "Scenery indexes (MSFS 2020 Store/Xbox)",
     "explain": "Scenery indexes are rebuilt after clearing; the first launch may be slower."},
    {"id": "oldcrashes_steam_2020", "edition": "MSFS 2020 / Steam", "kind": "dir", "base": "APPDATA", "stutter": None,
     "rel": ("Microsoft Flight Simulator", "AsoboReport-OldCrashes"), "default": False,
     "title": "Old crash reports (MSFS 2020 Steam)",
     "explain": "Past crash-report copies; optional and only useful to clear for disk space."},
    {"id": "d3dscache", "edition": "Windows / GPU", "kind": "dir", "base": "LOCALAPPDATA", "rel": ("D3DSCache",), "default": True, "stutter": "MSFS forums: 'What are the exact steps to clear all shader caches?' (t/738164) and 'How do you delete the shader cache in FS2024?' (t/773731)",
     "title": "DirectX shader cache (Windows)", "explain": "Compiled shaders for all DirectX games. Clearing can fix stutters "
                "or glitches after a driver update. Games rebuild it."},
    {"id": "nv_dx", "edition": "Windows / GPU", "kind": "dir", "base": "LOCALAPPDATA", "rel": ("NVIDIA", "DXCache"), "default": True, "stutter": "MSFS forums: 'What are the exact steps to clear all shader caches?' (t/738164) and 'How do you delete the shader cache in FS2024?' (t/773731)",
     "title": "NVIDIA DirectX shader cache", "explain": "NVIDIA's compiled shaders for DirectX games."},
    {"id": "nv_gl", "edition": "Windows / GPU", "kind": "dir", "base": "LOCALAPPDATA", "rel": ("NVIDIA", "GLCache"), "default": True, "stutter": "MSFS forums: 'What are the exact steps to clear all shader caches?' (t/738164) and 'How do you delete the shader cache in FS2024?' (t/773731)",
     "title": "NVIDIA OpenGL/Vulkan shader cache", "explain": "NVIDIA's compiled shaders for OpenGL/Vulkan games."},
    {"id": "nv_perdriver", "edition": "Windows / GPU", "kind": "dir", "base": "LOCALLOW", "stutter": "MSFS forums: 'FPS performance – VRAM bug?' p.31 (t/668753) and t/738164",
     "rel": ("NVIDIA", "PerDriverVersion", "DXCache"), "default": True,
     "title": "NVIDIA per-driver shader cache", "explain": "Shader cache kept per NVIDIA driver version."},
    {"id": "amd_dx", "edition": "Windows / GPU", "kind": "dir", "base": "LOCALAPPDATA", "rel": ("AMD", "DxCache"), "default": True, "stutter": 'MSFS forums t/738164 (AMD shader cache list)',
     "title": "AMD DirectX shader cache", "explain": "AMD's compiled shaders for DirectX games."},
    {"id": "steam_shadercache", "edition": "Linux / Steam Deck", "kind": "dir", "base": "STEAMSHADER", "stutter": None,
     "rel": (STEAM_APP_ID,), "default": False, "title": "Steam shader pre-cache for MSFS 2024 (Linux)",
     "explain": "Steam's DXVK/VKD3D shader cache for MSFS 2024 only. Steam rebuilds it; the first flights may stutter while it does."},
    {"id": "steam_shadercache_2020", "edition": "Linux / Steam Deck", "kind": "dir", "base": "STEAMSHADER", "stutter": None,
     "rel": (STEAM_APP_ID_2020,), "default": False, "title": "Steam shader pre-cache for MSFS 2020 (Linux)",
     "explain": "Steam's DXVK/VKD3D shader cache for MSFS 2020 only. Steam rebuilds it; the first flights may stutter while it does."},
    {"id": "mesa_cache", "edition": "Linux / Steam Deck", "kind": "dir", "base": "XDGCACHE", "stutter": None,
     "rel": ("mesa_shader_cache",), "default": False, "title": "Mesa shader cache (Linux, AMD/Intel)",
     "explain": "Compiled shaders of the Mesa graphics driver for all games (Mesa default cache folder). Rebuilt automatically."},
    {"id": "nv_gl_linux", "edition": "Linux / Steam Deck", "kind": "dir", "base": "XDGCACHE", "stutter": None,
     "rel": ("nvidia", "GLCache"), "default": False, "title": "NVIDIA shader cache (Linux)",
     "explain": "NVIDIA Linux driver's shader disk cache (driver default folder). Rebuilt automatically."},
    {"id": "amd_dxc", "edition": "Windows / GPU", "kind": "dir", "base": "LOCALAPPDATA", "rel": ("AMD", "DxcCache"), "default": True, "stutter": 'MSFS forums t/738164 (AMD shader cache list)',
     "title": "AMD DirectX 12 shader cache", "explain": "AMD's compiled DirectX 12 shaders."},
]
# Names that must never be deleted, wherever they appear (case-insensitive).
PROTECTED_NAMES = {"usercfg.opt", "community", "community2024", "official", "official2020", "official2024", "packages",
                   "streamedpackages", "logbook", "logbook.bin", "missions", "flights", "savedflights", "usercfg_backups",
                   "simobjects", "wasm", "exe.xml", "simconnect.xml", "devmode", "flightsimulator2024.cfg",
                   "grantedrewards.bin", "weather", "pc"}
# Not cleaned (purpose not confirmed by any source): tmcache, RAIDumps, imgui, Report-loading.toml, VFSTimings.csv,
# profile folders (e.g. Name#1234, hex IDs).

def _base_dirs(env=None):
    if env is None: env = os.environ if os.name == "nt" else linux_env()
    local = env.get("LOCALAPPDATA", "")
    locallow = os.path.join(os.path.dirname(local), "LocalLow") if local else ""
    lib = env.get("STEAMLIB", "")
    return {"APPDATA": env.get("APPDATA", ""), "LOCALAPPDATA": local, "LOCALLOW": locallow,
            "STEAMSHADER": os.path.join(lib, "steamapps", "shadercache") if lib else "", "XDGCACHE": env.get("XDGCACHE", "")}

def cache_item_game_version(item):
    """Return '2020', '2024', or None for a simulator-independent cache item."""
    item_id = str(item.get("id", ""))
    if "2020" in item_id or STEAM_APP_ID_2020 in item.get("rel", ()) or STORE_PKG_2020 in item.get("rel", ()):
        return "2020"
    rel = item.get("rel", ())
    if STEAM_APP_ID in rel or STORE_PKG in rel or "Microsoft Flight Simulator 2024" in rel:
        return "2024"
    return None

def resolve_cache_items(env=None, sim_version=None):
    """Return whitelisted caches, optionally limited to the active MSFS edition plus shared driver caches."""
    if env is None:
        env = os.environ if os.name == "nt" else linux_env(game_version=sim_version)
    bases, out = _base_dirs(env), []
    for it in CACHE_ITEMS:
        item_version = cache_item_game_version(it)
        if sim_version in ("2020", "2024") and item_version not in (None, sim_version):
            continue
        if sim_version == "unknown" and item_version is not None:
            continue
        b = bases.get(it["base"])
        if not b: continue
        p = os.path.abspath(os.path.join(b, *it["rel"]))
        out.append(dict(it, path=p, exists=os.path.isfile(p) if it["kind"] == "file" else os.path.isdir(p)))
    return out

def _is_link(p):
    try:
        return os.path.islink(p) or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
    except OSError:
        return True

def is_whitelisted(target, items):
    """target must be (inside) one of the resolved whitelist paths, not a link, and contain no protected name
    below the whitelist root."""
    t = os.path.normcase(os.path.realpath(target))
    for it in items:
        root = os.path.normcase(os.path.realpath(it["path"]))
        if it["kind"] == "file":
            if t == root: return True
            continue
        if t == root or t.startswith(root + os.sep):
            rel = os.path.relpath(t, root)
            parts = [] if rel == "." else rel.split(os.sep)
            if any(x.lower() in PROTECTED_NAMES for x in parts): return False
            return True
    return False

def path_size(p):
    """Bytes used by a file or folder tree (links are not followed)."""
    if _is_link(p): return 0
    if os.path.isfile(p):
        try: return os.path.getsize(p)
        except OSError: return 0
    total = 0
    for root, dirs, files in os.walk(p, followlinks=False):
        dirs[:] = [d for d in dirs if not _is_link(os.path.join(root, d))]
        for f in files:
            fp = os.path.join(root, f)
            try:
                if not _is_link(fp): total += os.path.getsize(fp)
            except OSError: pass
    return total

def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0

def stutter_fix_items(items):
    """The one-click 'Fix stutters' set: existing caches that sources link to stutters when stale/corrupt."""
    return [it for it in items if it.get("stutter") and it["exists"]]

def update_cleanup_items(items):
    """Update Cleanup clears the stutter set plus scenery indexes (known post-update fix)."""
    return [it for it in items if (it.get("stutter") or it.get("update")) and it["exists"]]

def clear_item(item, whitelist):
    """Delete a whitelisted cache file, or the *contents* of a whitelisted folder. Locked/in-use files are skipped.
    Returns dict(freed, deleted, skipped=[paths], refused=[paths])."""
    res = {"freed": 0, "deleted": 0, "skipped": [], "refused": []}
    root = item["path"]
    if not is_whitelisted(root, whitelist) or _is_link(root) or os.path.basename(root).lower() in PROTECTED_NAMES:
        res["refused"].append(root); return res
    def rm_file(fp):
        if _is_link(fp) or not is_whitelisted(fp, whitelist) or os.path.basename(fp).lower() in PROTECTED_NAMES:
            res["refused"].append(fp); return
        try:
            sz = os.path.getsize(fp); os.remove(fp); res["freed"] += sz; res["deleted"] += 1
        except OSError:
            res["skipped"].append(fp)
    if item["kind"] == "file":
        if os.path.isfile(root): rm_file(root)
        return res
    if not os.path.isdir(root): return res
    for cur, dirs, files in os.walk(root, topdown=False, followlinks=False):
        for f in files: rm_file(os.path.join(cur, f))
        for d in dirs:
            dp = os.path.join(cur, d)
            if _is_link(dp) or not is_whitelisted(dp, whitelist):
                res["refused"].append(dp); continue
            try: os.rmdir(dp)
            except OSError: pass          # not empty (locked file inside) – leave it
    return res

# ---------------------------------------------------------------- plain-English helpers
SIMPLE_PRESETS = ["Performance", "Balanced", "Quality", "Ultra+"]
PLAIN = {
    "Video/AntiAliasing": "Anti-aliasing", "Video/PrimaryScaling": "Render resolution",
    "Video/FrameGeneration": "Frame generation", "Video/DLSSG": "NVIDIA DLSS frame generation",
    "Video/NBFramesToGenerate": "Frame generation multiplier",
    "Graphics/Terrain/LoDFactor": "Terrain detail distance", "Graphics/ObjectsLoD/LoDFactor": "Buildings & objects distance",
    "Graphics/Texture/Quality": "Texture sharpness", "Graphics/VolumetricClouds/Quality": "Cloud quality",
    "Graphics/Shadows/Size": "Shadow sharpness", "Graphics/Traffic/AircraftTrafficQuantity": "AI aircraft traffic",
    "Graphics/Characters/Quantity": "People at airports", "Video/FullScreenResolution": "Screen resolution",
}
# v1.3.0: friendlier names for the simple view's "What will change" list (Advanced keeps the sim's own names)
PLAIN.update({
    "Video/AntiAliasing": "Smooth edges", "Video/FrameGeneration": "Extra frames", "Video/DLSSG": "Extra frames (NVIDIA)",
    "Video/NBFramesToGenerate": "Extra frames multiplier", "Video/SharpenAmount": "Image sharpening",
    "Video/FSRMode": "AMD FSR quality", "Video/DLSSMode": "NVIDIA DLSS quality", "Video/FrameLimiter": "Frame rate cap",
    "Graphics/OffscreenTerrainPreCaching/Quality": "Preload scenery around you",
    "Graphics/Texture/MaxAnisotropy": "Ground sharpness at a distance", "Graphics/HeightFieldShadows/Size": "Terrain shadows",
    "Graphics/DisplacementMapping/Enabled": "3D ground detail", "Graphics/ReflectionProbe/Size": "Reflections (detail)",
    "Graphics/SSR/Quality": "Reflections (on surfaces)", "Graphics/SSAO/Quality": "Soft shadows in corners",
    "Graphics/VolumetricLights/Quality": "Light shafts", "Graphics/TextureSynthesis/Quality": "Ground texture variety",
    "Graphics/VectorDataTessellation/Quality": "Roads & coastline detail", "Graphics/Shadows/MaxSliceCount": "Shadow distance",
    "Graphics/Terrain/POMMaxDist": "3D ground detail distance", "Graphics/Terrain/POMSubsplitsMaxDist": "3D ground detail (fine)",
    "Graphics/RaytracedShadows/Enabled": "Ray-traced shadows", "Graphics/ContactShadows/Quality": "Contact shadows",
    "Graphics/Preset": "Graphics preset",
})


AA_CHOICES = {"TAA": "TAA", "NVIDIA DLSS": "DLSS", "AMD FSR": "FSR"}   # values written to UserCfg.opt
FG_CHOICES = {"Off": "NONE", "AMD FSR": "FSRFG", "NVIDIA DLSS FG": "DLSSG"}
DEFAULT_AA, DEFAULT_FG = "TAA", "NONE"


# Traffic & people (confirmed {Traffic}/{Characters}/{Fauna} keys in MSFS 2024 UserCfg.opt).
TRAFFIC_CATS = [
    ("Graphics/Traffic/AircraftTrafficQuantity", "AI aircraft", "Other planes flying and taxiing. The biggest CPU cost at busy airports."),
    ("Graphics/Traffic/ParkedAircraftQuantity", "Parked aircraft", "Static planes at gates and stands. CPU and video memory."),
    ("Graphics/Traffic/AirportsServicesQuantity", "Ground vehicles", "Fuel trucks, tugs and buses at airports. CPU cost at busy airports."),
    ("Graphics/Characters/Quantity", "People", "Ground crew and passengers at airports. CPU cost at busy airports."),
    ("Graphics/Traffic/RoadQuality", "Road traffic", "Cars on roads and motorways. Moderate CPU cost over cities."),
    ("Graphics/Traffic/SeaQuality", "Boats & ships", "Boats and ships on water. Small CPU cost."),
    ("Graphics/Fauna/Quantity", "Wildlife", "Animals. Small CPU cost."),
]
# Simple-view master traffic level -> value written to every traffic key: Off = -1, Low..Ultra = 0..3
# (the same codes as OFF_Q4). "SkyTune decides" leaves the keys to the goal/preset.
TRAFFIC_LEVELS = {"SkyTune decides": None, "Off": -1, "Low": 0, "Medium": 1, "High": 2, "Ultra": 3}

def traffic_for_level(level_name):
    lvl = TRAFFIC_LEVELS.get(level_name)
    return {p: lvl for p, _, _ in TRAFFIC_CATS}

def frame_generation_multiplier_limit(fg, gpu_name=None):
    """Return the maximum UserCfg multiplier (1=2x, 2=3x, 3=4x) for the selected FG mode."""
    if fg != "DLSSG":
        return 1
    if re.search(r"RTX\s*50\d\d", gpu_name or "", re.I):
        return 3
    return 1

def with_user_choices(values, aa=DEFAULT_AA, fg=DEFAULT_FG, traffic=None, gpu_name=None):
    """Return a copy of preset values where user choices win and unsupported FG multipliers are clamped."""
    v = dict(values); v["Video/AntiAliasing"] = aa; v["Video/FrameGeneration"] = fg
    if fg == "NONE":
        v.pop("Video/NBFramesToGenerate", None)
    else:
        try:
            requested = int(float(v.get("Video/NBFramesToGenerate", 1)))
        except (TypeError, ValueError):
            requested = 1
        v["Video/NBFramesToGenerate"] = max(1, min(requested, frame_generation_multiplier_limit(fg, gpu_name)))
    for path, level in (traffic or {}).items():     # user's traffic choices win (None = let the preset decide)
        if level is not None: v[path] = level
    return v

def dlss_support(gpu_name):
    """(dlss_aa_ok, dlss_fg_ok, note). None = unknown GPU (allowed, with a warning)."""
    n = gpu_name or ""
    if not n or n == "Unknown":
        return None, None, "GPU not detected – DLSS needs an NVIDIA RTX card; DLSS frame generation needs RTX 40/50 + HAGS."
    if not re.search(r"RTX", n, re.I):
        return False, False, "NVIDIA DLSS is unavailable on %s. Use TAA or AMD FSR upscaling; AMD frame generation is a separate option." % n
    if re.search(r"RTX\s*(40|50)\d\d", n, re.I):
        return True, True, "DLSS frame generation needs Windows 'Hardware-accelerated GPU scheduling' (HAGS) turned on."
    return True, False, "DLSS frame generation needs an RTX 40 or 50 card – use AMD FSR frame generation instead."

def _display(path, raw):
    if raw is None: return "?"
    if path == "Video/DLSSG":
        return "On" if str(raw).strip() in ("1", "true", "True") else "Off"
    if path.endswith("LoDFactor") or path == "Video/PrimaryScaling":
        try: return "%d%%" % round(float(raw) * 100) if path == "Video/PrimaryScaling" else "%d" % round(float(raw) * 100)
        except ValueError: return raw
    for sp, label, group, kind, spec, tip in SETTINGS:
        if sp == path and kind == "choice":
            inv = {str(v): k for k, v in spec.items()}
            return inv.get(str(raw), str(raw))
    return str(raw)

# ---------------------------------------------------------------- v1.6.0 since last write
# The simulator rewrites UserCfg.opt when it exits or when graphics are changed in its menu.
# SkyTune remembers the known settings from its own last write (no path, no account name, no key)
# and shows what now differs. Keeping those values only changes the pending list. Nothing is written here.
SNAPSHOT_SKIP = ("Video/FullScreenResolution", "Video/Resolution")

def known_setting_paths():
    seen = []
    for path, _label, _group, _kind, _spec, _tip in SETTINGS:
        if path in SNAPSHOT_SKIP or path in seen: continue
        seen.append(path)
    return seen

def file_snapshot(cfg):
    """Raw values of known settings that exist in this file. Skips resolution, paths and anything that looks like a key."""
    out = {}
    for path in known_setting_paths():
        if cfg is None or path not in cfg.index: continue
        raw = str(cfg.get(path) if cfg.get(path) is not None else "").strip()
        if not raw or len(raw) > 40: continue
        if re.search(r"[\\/]|sk-|api[_-]?key", raw, re.I): continue
        out[path] = raw
    return out

def clean_last_apply(data):
    """A stored snapshot, or None. Rejects unknown keys, paths and secrets."""
    if not isinstance(data, dict): return None
    edition = data.get("edition")
    if edition not in ("2020", "2024", "unknown"): return None
    values = data.get("values")
    if not isinstance(values, dict) or not values or len(values) > 80: return None
    known = set(known_setting_paths())
    clean = {}
    for path, raw in values.items():
        if path not in known or not isinstance(raw, str): return None
        if len(raw) > 40 or re.search(r"[\\/]|sk-|api[_-]?key", raw, re.I): return None
        clean[path] = raw.strip()
    if not clean: return None
    out = {"edition": edition, "values": clean}
    try:
        ts = float(data.get("written_at"))
        if ts > 0: out["written_at"] = ts
    except (TypeError, ValueError): pass
    return out

def load_last_apply(path=None):
    return clean_last_apply(load_state(path).get("last_apply"))

def save_last_apply(cfg, edition, path=None):
    """Remember this file's known settings as SkyTune's last write. Returns False if there is nothing safe to store."""
    edition = edition if edition in ("2020", "2024", "unknown") else "unknown"
    snap = clean_last_apply({"edition": edition, "values": file_snapshot(cfg), "written_at": time.time()})
    if not snap: return False
    return save_state({"last_apply": snap}, path)

def drift_since_write(snapshot, cfg):
    """Recognised settings whose file value differs from the snapshot. Does not write."""
    snap = snapshot if isinstance(snapshot, dict) and "values" in (snapshot or {}) else None
    snap = clean_last_apply(snap) if snap and "edition" in snap else None
    if not snap or cfg is None: return []
    rows = []
    for path, was in snap["values"].items():
        if path not in cfg.index: continue
        now = str(cfg.get(path) if cfg.get(path) is not None else "").strip()
        if now == was: continue
        label = PLAIN.get(path) or next((x[1] for x in SETTINGS if x[0] == path), path)
        rows.append({"path": path, "label": label, "was": _display(path, was), "now": _display(path, now)})
    rows.sort(key=lambda r: r["label"].lower())
    return rows

def describe_drift(snapshot, cfg, edition):
    """none / other / match / diff. 'other' means the last write was for the other simulator, so the values are not compared."""
    snap = clean_last_apply(snapshot)
    if not snap: return {"kind": "none", "rows": []}
    if snap["edition"] in ("2020", "2024") and edition in ("2020", "2024") and snap["edition"] != edition:
        return {"kind": "other", "rows": [], "written_edition": snap["edition"]}
    rows = drift_since_write(snap, cfg)
    return {"kind": "diff" if rows else "match", "rows": rows}

# ---------------------------------------------------------------- v1.7.0 sim-update reset, read-only health, control-binding files
# A sim update can rewrite UserCfg.opt. This only compares known settings with SkyTune's last write
# or newest backup. It does not write. "Put my settings back" is a separate, confirmed step.
RESET_MIN_CHANGES = 8

def snapshot_to_values(values):
    """Turn stored raw strings into the types set_var expects. Unknown keys are dropped."""
    out = {}
    for path, raw in (values or {}).items():
        if path not in KINDS: continue
        kind = KINDS[path]
        try:
            if kind == "float": out[path] = float(raw)
            elif kind == "int": out[path] = int(float(raw))
            else: out[path] = str(raw).strip()
        except (TypeError, ValueError):
            continue
    return out

def reset_report(cfg, snapshot=None, backup_cfg=None, file_mtime=None, written_at=None):
    """Read-only. reset is true when many known settings differ and the file is newer than SkyTune's note,
    or many differ from the newest backup when no note time was stored."""
    source_name, source = None, None
    snap = clean_last_apply(snapshot) if snapshot else None
    if snap:
        source, source_name = snap, "last write"
        if written_at is None: written_at = snap.get("written_at")
    elif backup_cfg is not None:
        source = {"edition": "unknown", "values": file_snapshot(backup_cfg)}
        source_name = "last backup"
    if not source or cfg is None:
        return {"reset": False, "rows": [], "source": None, "values": {}, "newer": False}
    rows = drift_since_write(source, cfg)
    newer = False
    try:
        if file_mtime is not None and written_at is not None:
            newer = float(file_mtime) > float(written_at)
    except (TypeError, ValueError):
        newer = False
    many = len(rows) >= RESET_MIN_CHANGES
    reset = bool(many and (newer or (written_at is None and source_name == "last backup")))
    return {"reset": reset, "rows": rows, "source": source_name, "values": source.get("values") or {}, "newer": newer}

def parse_hags(value):
    """HwSchMode: 2 on, 1 off. Anything else is Unknown. Does not write the registry."""
    if value is None: return "Unknown"
    text = str(value).strip()
    if text == "2": return "On"
    if text == "1": return "Off"
    return "Unknown"

def parse_memory_integrity(value):
    """HVCI Enabled: 1 on, 0 off. Does not write the registry."""
    if value is None: return "Unknown"
    text = str(value).strip()
    if text == "1": return "On"
    if text == "0": return "Off"
    return "Unknown"

def parse_pagefile(managed, allocated_mb=None):
    """AutomaticManagedPagefile true means system-managed. A number is the allocated size. Never changes it."""
    if isinstance(managed, str): managed = managed.strip().lower()
    if managed is True or managed in ("true", "1"): return "System managed"
    if allocated_mb is None or managed in (None, ""): return "Unknown"
    try: return "%d MB" % int(float(allocated_mb))
    except (TypeError, ValueError): return "Unknown"

def read_health(path=None, hw=None, probes=None):
    """Read-only PC notes. Missing values stay Unknown. probes replaces live Windows reads in tests."""
    probes = dict(probes or {})
    out = {"free_gb": "Unknown", "gpu": "Unknown", "vram_gb": "Unknown", "ram_gb": "Unknown",
           "pagefile": "Unknown", "hags": "Unknown", "memory_integrity": "Unknown", "refresh_hz": "Unknown"}
    if path:
        try:
            usage = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or path)
            out["free_gb"] = round(usage.free / (1024 ** 3), 1)
        except OSError:
            pass
    hw = hw or {}
    if hw.get("gpu") and hw.get("gpu") != "Unknown": out["gpu"] = hw.get("gpu")
    if hw.get("vram_gb"): out["vram_gb"] = hw.get("vram_gb")
    if hw.get("ram_gb"): out["ram_gb"] = hw.get("ram_gb")
    for key in out:
        if key in probes and probes[key] is not None: out[key] = probes[key]
    if "hags_raw" in probes: out["hags"] = parse_hags(probes.get("hags_raw"))
    if "hvci_raw" in probes: out["memory_integrity"] = parse_memory_integrity(probes.get("hvci_raw"))
    if "page_managed" in probes or "page_mb" in probes:
        out["pagefile"] = parse_pagefile(probes.get("page_managed"), probes.get("page_mb"))
    tips = []
    try:
        if 0 < float(out["vram_gb"]) <= 8:
            tips.append("8 GB of video memory is tight for Ultra textures. The 8 GB creator setup keeps texture resolution at High.")
    except (TypeError, ValueError): pass
    try:
        if float(out["refresh_hz"]) > 144:
            tips.append("This screen is faster than 144 Hz. Without variable refresh it may need V-Sync or a frame cap. SkyTune does not change V-Sync or any Windows setting.")
    except (TypeError, ValueError): pass
    out["tips"] = tips
    return out

def windows_health_probes(timeout=8):
    """Live Windows reads. Each failure becomes Unknown. Nothing is written."""
    probes = {}
    if os.name != "nt": return probes
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers") as k:
            probes["hags_raw"] = winreg.QueryValueEx(k, "HwSchMode")[0]
    except OSError: pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity") as k:
            probes["hvci_raw"] = winreg.QueryValueEx(k, "Enabled")[0]
    except OSError: pass
    script = ("$c=Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue; "
              "$p=Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue | Select-Object -First 1; "
              "$v=Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Select-Object -First 1; "
              "[pscustomobject]@{managed=$c.AutomaticManagedPagefile; mb=$p.AllocatedBaseSize; hz=$v.CurrentRefreshRate} | ConvertTo-Json -Compress")
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    try:
        data = json.loads(out) if out.strip().startswith("{") else {}
    except ValueError:
        data = {}
    if "managed" in data: probes["page_managed"] = data.get("managed")
    if data.get("mb") not in (None, ""): probes["page_mb"] = data.get("mb")
    if data.get("hz") not in (None, "", 0): probes["refresh_hz"] = data.get("hz")
    return probes

def binding_search_dirs(home=None, steam_path=None):
    """Existing Steam userdata remote folders for MSFS 2020 (1250410) and 2024 (2537590).
    Directories are not created. The Microsoft Store cloud-save folder is not searched."""
    dirs = []
    roots = list(steam_roots(home))
    if steam_path and os.path.isdir(steam_path): roots.append(steam_path)
    seen = set()
    for root in roots:
        userdata = os.path.join(root, "userdata")
        if not os.path.isdir(userdata): continue
        for app in ("1250410", "2537590"):
            for remote in glob.glob(os.path.join(userdata, "*", app, "remote")):
                key = os.path.normcase(os.path.abspath(remote))
                if key not in seen and os.path.isdir(remote):
                    seen.add(key); dirs.append(remote)
    return dirs

def find_input_profiles(home=None, steam_path=None):
    """inputprofile_* files only. Other save files are ignored. Returns [] when none exist."""
    found = []
    for remote in binding_search_dirs(home, steam_path):
        try: names = os.listdir(remote)
        except OSError: continue
        for name in sorted(names):
            if not name.lower().startswith("inputprofile_"): continue
            path = os.path.join(remote, name)
            if os.path.isfile(path): found.append(path)
    return found

def backup_bindings(backup_opt, files):
    """Copy found inputprofile files next to a settings backup. Skips any other name. Returns the folder or None."""
    import hashlib
    chosen = [p for p in files or [] if os.path.isfile(p) and os.path.basename(p).lower().startswith("inputprofile_")]
    if not chosen: return None
    dest = backup_opt + ".bindings"
    os.makedirs(dest, exist_ok=True)
    manifest = []
    for src in chosen:
        name = os.path.basename(src)
        copy_bytes(src, os.path.join(dest, name))
        manifest.append({"name": name, "sha256": hashlib.sha256(open(src, "rb").read()).hexdigest()})
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"files": manifest}, f, indent=1)
    return dest

def restore_bindings(backup_opt, found_files):
    """Copy a bindings backup onto inputprofile files that can be found again by the same search.
    A file that is not found is skipped. The result is checked by hash. Does not create new paths."""
    import hashlib
    folder = backup_opt + ".bindings"
    man_path = os.path.join(folder, "manifest.json")
    if not os.path.isfile(man_path):
        return {"ok": False, "restored": [], "missing": [], "error": "Not found"}
    try:
        manifest = json.load(open(man_path, encoding="utf-8")).get("files") or []
    except (OSError, ValueError):
        return {"ok": False, "restored": [], "missing": [], "error": "Not found"}
    by_name = {}
    for path in found_files or []:
        by_name.setdefault(os.path.basename(path).lower(), path)
    restored, missing = [], []
    for item in manifest:
        name = item.get("name") or ""
        if not name.lower().startswith("inputprofile_"): continue
        src = os.path.join(folder, name)
        dest = by_name.get(name.lower())
        if not dest or not os.path.isfile(src):
            missing.append(name); continue
        copy_bytes(src, dest)
        got = hashlib.sha256(open(dest, "rb").read()).hexdigest()
        if item.get("sha256") and got != item["sha256"]:
            return {"ok": False, "restored": restored, "missing": missing, "error": "binding check failed for %s" % name}
        restored.append(name)
    return {"ok": not missing, "restored": restored, "missing": missing, "error": None if not missing else "Not found"}

# v1.3.1: human labels for the raw codes shown in Advanced's "IN FILE" column (was e.g. "-1" or "FSRFG")
FG_CODE_LABELS = {"NONE": "Off", "FSRFG": "AMD FSR", "DLSSG": "NVIDIA DLSS FG"}

def in_file_label(path, raw, kind=None, spec=None):
    """What the file says, in words: traffic -1 -> Off, 0..3 -> Low..Ultra, FSRFG -> AMD FSR, 0.750000 -> 0.75.
    Unknown codes are shown as they are."""
    if raw is None: return "–"
    t = str(raw).strip()
    if path == "Video/FrameGeneration": return FG_CODE_LABELS.get(t.upper(), t)
    if path == "Video/DLSSG": return "On" if t in ("1", "true", "True") else "Off"
    sdef = next((x for x in SETTINGS if x[0] == path and (kind is None or x[3] == kind)), None)
    if kind is None and sdef: kind = sdef[3]
    if spec is None and sdef: spec = sdef[4]
    if kind == "choice" and isinstance(spec, dict):
        n = _num(t)
        for label, v in spec.items():
            if str(v).upper() == t.upper() or (isinstance(v, (int, float)) and n is not None and float(v) == n):
                return label
        return t
    if kind in ("float", "int") and isinstance(spec, tuple):
        n = _num(t)
        if n is None: return t
        return "%d" % round(n) if kind == "int" or spec[2] >= 1 else "%.2f" % n
    return t

SAVED_SETTING = "saved in your settings"

def shows_saved_upscaler(path, raw=None):
    """True when this row is DLSS or frame generation, and the value is not an explicit off."""
    if path == "Video/AntiAliasing":
        return str(raw or "").strip().upper() == "DLSS"
    if path == "Video/DLSSMode":
        return True
    if path == "Video/FrameGeneration":
        return str(raw or "").strip().upper() not in ("", "NONE", "OFF")
    if path == "Video/DLSSG":
        return str(raw or "").strip() in ("1", "1.0", "true", "True")
    return False

def saved_setting_suffix(path, raw=None):
    return SAVED_SETTING if shows_saved_upscaler(path, raw) else ""

def upscaler_saved_note(cfg):
    """One sentence for the file's DLSS or frame-generation value. Empty when neither is saved on."""
    if cfg is None:
        return ""
    parts = []
    if shows_saved_upscaler("Video/AntiAliasing", cfg.get("Video/AntiAliasing")):
        parts.append("DLSS")
    if shows_saved_upscaler("Video/FrameGeneration", cfg.get("Video/FrameGeneration")) or shows_saved_upscaler("Video/DLSSG", cfg.get("Video/DLSSG")):
        parts.append("frame generation")
    if not parts:
        return ""
    verb = "is" if len(parts) == 1 else "are"
    return "%s %s saved in your settings. A saved setting does not prove it is running." % (" and ".join(parts), verb)

def choice_saved_note(aa, fg):
    """The preferences line adds the same phrase when DLSS or frame generation is selected."""
    aa_u, fg_u = (aa or "").upper(), (fg or "").upper()
    if "DLSS" in aa_u or fg_u not in ("", "OFF", "NONE"):
        return SAVED_SETTING
    return ""

FRAME_GEN_NOTE = (
    "DLSS and frame generation shown here are saved in your settings. "
    "A saved setting does not prove they are running. "
    "Frame generation is best enabled after the base frame rate is stable (aim for at least 30 FPS). "
    "VSync behaviour can change while frame generation is saved in your settings.\n\n"
    "AMD FSR frame generation works on most GPUs (2x). "
    "NVIDIA DLSS frame generation needs an RTX 40 or 50 card with hardware-accelerated GPU scheduling; "
    "3x and 4x need an RTX 50-series card.")

# v1.3.1: controls that only mean something while frame generation is on
FG_DEPENDENT = ("Video/NBFramesToGenerate",)
FG_MULT_LABELS = {"2x": 1, "3x": 2, "4x": 3}

def fg_dependent_state(fg, gpu_name=None):
    """For a frame-generation choice (label like "Off"/"AMD FSR" or file code like "NONE"/"FSRFG"):
    {"enabled": bool, "multipliers": [allowed labels], "hint": str}. Off -> disabled and never written."""
    code = FG_CHOICES.get(fg, fg)
    for sdef in SETTINGS:
        if sdef[0] == "Video/FrameGeneration" and fg in sdef[4]: code = sdef[4][fg]
    code = str(code or "NONE").upper()
    if code in ("NONE", "OFF", "0", ""):
        return {"enabled": False, "multipliers": [], "hint": "Only used when Frame generation is on."}
    lim = frame_generation_multiplier_limit(code, gpu_name)
    mults = [k for k, v in FG_MULT_LABELS.items() if v <= lim]
    hint = "AMD FSR frame generation is 2x only." if code == "FSRFG" else \
           ("" if lim >= 3 else "3x/4x need an RTX 50-series card.")
    return {"enabled": True, "multipliers": mults, "hint": hint}

def summarize_changes(cfg, values, change_resolution=False):
    """Plain-English list of (label, old, new) for values that would change. Does not modify cfg."""
    out, seen = [], set()
    for path, v in values.items():
        if path in seen or path not in cfg.index: continue
        seen.add(path)
        if path in ("Video/FullScreenResolution", "Video/Resolution") and not change_resolution: continue
        old = cfg.get(path); new = format_value(KINDS.get(path, "int"), v)
        if old != new:
            label = PLAIN.get(path) or next((x[1] for x in SETTINGS if x[0] == path), path)
            out.append((label, _display(path, old), _display(path, new)))
    return out

def _hw_number(hw, key):
    try:
        n = float((hw or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0
    return n

def setting_reason(path, hw=None):
    """One plain sentence for why this setting is on the list. Does not read or write a file."""
    hw = hw or {}
    vram, cores, hz = _hw_number(hw, "vram_gb"), _hw_number(hw, "cores"), _hw_number(hw, "refresh_hz")
    name = hw.get("gpu") or ""
    tier = gpu_tier(name, vram)[0] if name else None
    if path == "Graphics/Texture/Quality":
        if 0 < vram <= 8:
            return "Texture resolution stays at High because this card has about %.0f GB of video memory." % vram
        if vram > 8:
            return "This card has about %.0f GB of video memory, so texture resolution can stay high." % vram
        return "Texture resolution follows the preset. Ultra needs more than 8 GB of video memory."
    if path in ("Graphics/Terrain/LoDFactor", "Graphics/ObjectsLoD/LoDFactor"):
        if 0 < cores < 8:
            return "Distance stays moderate because this processor has %.0f cores." % cores
        return "Distance follows the preset. It costs processor time at a busy airport."
    if path == "Video/FrameLimiter":
        if hz > 144:
            return "This screen refreshes at %.0f Hz. A frame cap keeps motion even on a screen faster than 144 Hz. SkyTune does not change V-Sync." % hz
        return "A frame cap keeps frame times steady. SkyTune does not change V-Sync."
    if "Traffic" in path or "Characters" in path or path.endswith("Fauna/Quantity"):
        if 0 < cores <= 8:
            return "Traffic and people stay lighter so a %.0f-core processor has room at a busy airport." % cores
        return "Traffic and people follow the goal. They are mostly processor work."
    if path == "Graphics/VolumetricClouds/Quality":
        if tier is not None and tier <= 1:
            return "Clouds stay lighter because this graphics card is in a lower tier."
        if 0 < vram <= 8:
            return "Clouds are eased off on a %.0f GB card so video memory stays free for textures." % vram
        return "Cloud quality follows the goal. Denser clouds use the graphics card."
    if 0 < vram <= 8 and str(path).startswith("Graphics/"):
        return "Kept within what about %.0f GB of video memory can hold." % vram
    if tier is not None:
        return "Chosen for this graphics card (tier %d). Nothing is written until you confirm." % tier
    return "Suggested from your goal. Nothing is written until you confirm."

def change_reasons(cfg, values, hw=None, change_resolution=False):
    """Map each visible change's label to its one-line reason. Does not modify cfg."""
    out, seen = {}, set()
    for path, v in (values or {}).items():
        if path in seen or path not in getattr(cfg, "index", {}): continue
        seen.add(path)
        if path in ("Video/FullScreenResolution", "Video/Resolution") and not change_resolution: continue
        old = cfg.get(path); new = format_value(KINDS.get(path, "int"), v)
        if old != new:
            label = PLAIN.get(path) or next((x[1] for x in SETTINGS if x[0] == path), path)
            out[label] = setting_reason(path, hw)
    return out

TERRAIN_LOD = "Graphics/Terrain/LoDFactor"
OBJECT_LOD = "Graphics/ObjectsLoD/LoDFactor"
FRAME_HOLD_LIMITS = {TERRAIN_LOD: (0.1, 8.0), OBJECT_LOD: (0.1, 4.0)}
FRAME_HOLD_WARNING = (
    "Frame Hold does not change Microsoft Flight Simulator while it is running. "
    "The simulator has no documented way to set terrain or object detail during a flight, "
    "and SkyTune will not write into the simulator's memory. "
    "Type the frame rate you see, and the altitude if you want the altitude rule. "
    "Close the simulator before using the numbers. Yes, write still asks. "
    "Closing this window puts the list back to the file if you have not written it."
)
HELP_PAGES = HELP_PAGES + (("Frame Hold", FRAME_HOLD_WARNING),)

def _hold_range(pair, limits):
    lo, hi = float(pair[0]), float(pair[1])
    lo = min(limits[1], max(limits[0], lo))
    hi = min(limits[1], max(limits[0], hi))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi

class FrameHold:
    """Work out terrain and object detail for a target frame rate.

    This object only calculates. It does not open the simulator, write memory, or save a settings file.
    Pass frame rate and altitude in yourself. A missing frame rate is left as None and is never invented.
    """
    def __init__(self, target_fps=30, terrain=(1.0, 2.0), objects=(0.5, 1.5),
                 altitude_mode=False, ground_ft=2000, cruise_ft=10000, step=0.1):
        target = float(target_fps)
        if target <= 0:
            raise ValueError("The target frame rate has to be above zero.")
        self.target = target
        self.terrain_range = _hold_range(terrain, FRAME_HOLD_LIMITS[TERRAIN_LOD])
        self.object_range = _hold_range(objects, FRAME_HOLD_LIMITS[OBJECT_LOD])
        self.altitude_mode = bool(altitude_mode)
        self.ground_ft = float(ground_ft)
        self.cruise_ft = float(cruise_ft)
        if self.cruise_ft <= self.ground_ft:
            self.cruise_ft = self.ground_ft + 1.0
        self.step = abs(float(step)) or 0.1
        self.current = None
        self.original = None
        self.active = False

    def start(self, terrain, objects):
        self.original = (float(terrain), float(objects))
        self.current = (self._fit(terrain, self.terrain_range), self._fit(objects, self.object_range))
        self.active = True
        return self.note("Frame Hold is on. Nothing has been written.")

    def stop(self):
        self.active = False
        back = self.original
        self.current = back
        return back

    def _fit(self, value, bounds):
        return min(bounds[1], max(bounds[0], float(value)))

    def _caps(self, altitude_ft):
        if not self.altitude_mode or altitude_ft is None:
            return self.terrain_range[1], self.object_range[1], None
        span = self.cruise_ft - self.ground_ft
        factor = min(1.0, max(0.0, (float(altitude_ft) - self.ground_ft) / span))
        return (self.terrain_range[0] + factor * (self.terrain_range[1] - self.terrain_range[0]),
                self.object_range[0] + factor * (self.object_range[1] - self.object_range[0]),
                factor)

    def update(self, fps=None, altitude_ft=None):
        """One sample. fps and altitude_ft may be None. Returns the detail to show, not a file write."""
        if not self.active:
            raise RuntimeError("Frame Hold is off.")
        if fps is not None:
            fps = float(fps)
            if fps < 0:
                raise ValueError("A frame rate cannot be negative.")
        if altitude_ft is not None:
            altitude_ft = float(altitude_ft)
        t_cap, o_cap, factor = self._caps(altitude_ft)
        terrain, objects = self.current
        terrain, objects = min(terrain, t_cap), min(objects, o_cap)
        notes = []
        if fps is None:
            notes.append("No frame rate yet, so detail was not moved for speed.")
        elif fps < self.target * 0.9:
            terrain = max(self.terrain_range[0], terrain - self.step)
            objects = max(self.object_range[0], objects - self.step)
            notes.append("Frames are under the target, so detail steps down.")
        elif fps > self.target * 1.1:
            terrain = min(t_cap, terrain + self.step)
            objects = min(o_cap, objects + self.step)
            notes.append("Frames are above the target, so detail can step up.")
        else:
            notes.append("Frames are close to the target, so detail stays.")
        if self.altitude_mode and factor is None:
            notes.append("Altitude was not provided, so the altitude rule is waiting.")
        elif factor == 0:
            notes.append("Near the ground, detail stays at the low end of your range.")
        elif factor == 1:
            notes.append("In cruise, detail may use the high end of your range.")
        terrain, objects = round(terrain, 2), round(objects, 2)
        self.current = (terrain, objects)
        return self.note(" ".join(notes))

    def note(self, reason):
        terrain, objects = self.current
        return {"terrain": terrain, "objects": objects,
                "terrain_menu": int(round(terrain * 100)), "objects_menu": int(round(objects * 100)),
                "reason": reason, "written": False}

def frame_hold_block(sim_is_running):
    """Why the list must not change, or None when the simulator is closed."""
    if sim_is_running:
        return "The simulator is running, so the list was not changed. Close it, then try again."
    if sim_is_running is None:
        return "SkyTune can't tell if the simulator is running. Close it, then try again."
    return None

def frame_hold_values(result, cfg):
    """The two detail values that belong on the confirm list. Does not write the file."""
    out = {}
    index = getattr(cfg, "index", {}) or {}
    if result and TERRAIN_LOD in index:
        out[TERRAIN_LOD] = result["terrain"]
    if result and OBJECT_LOD in index:
        out[OBJECT_LOD] = result["objects"]
    return out

def change_summary_line(items, limit=3):
    """v1.3.1: one short plain line for the footer after Optimise, e.g.
    'Cloud quality High → Ultra, AI aircraft traffic Medium → Low and 4 more'. items = summarize_changes() output."""
    items = list(items or [])
    if not items: return ""
    parts = ["%s %s → %s" % (lab, old, new) if old not in (None, "?", "") else "%s %s" % (lab, new) for lab, old, new in items[:limit]]
    more = len(items) - limit
    return ", ".join(parts) + (" and %d more" % more if more > 0 else "")

SIM_LOCK_TIP = ("Close Microsoft Flight Simulator first – it overwrites these settings when it exits. "
                "Then click “Check again”.")
SIM_BANNER_TEXT = ("Microsoft Flight Simulator is running. Close it first – the sim saves its own settings when it exits "
                   "and would undo SkyTune's changes.")
ADV_BANNER_TEXT = "Close the sim before applying – changing graphics in its own menu can overwrite anything you set here."
CACHE_SAFE_NOTE = ("✓ Safe to clear: these are temporary files the sim rebuilds. Your settings, add-ons and flights are "
                   "never touched – the first flight afterwards just loads a bit slower.")

def cache_total_text(n_items, n_bytes, measuring=False):
    """v1.3.1: clear total for the ticked caches."""
    if measuring: return "Measuring sizes…"
    if not n_items: return "Nothing ticked"
    return "%d item%s ticked · %s to free" % (n_items, "" if n_items == 1 else "s", human_size(n_bytes))

STEP_NAMES = ("Check my PC", "What matters most", "Optimise")

def sim_status_text(running):
    if running is None: return "warn", "Can't tell if MSFS is running – make sure it is closed"
    return ("err", "Microsoft Flight Simulator is running – close it first") if running else ("ok", "Sim closed – safe to apply")

# ---------------------------------------------------------------- remembered choices (v1.3.0)
PREF_DEFAULTS = {"goal": DEFAULT_GOAL, "aa": "TAA", "fg": "Off", "traffic": "SkyTune decides", "prefs_open": False,
                 "ai_enabled": False, "ai_provider": "openai", "ai_base_url": "", "ai_model": ""}

def load_state(path=None):
    """Read state.json (welcome flag + remembered choices). Never raises; bad files give {}."""
    try:
        with open(path or app_state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def save_state(updates, path=None):
    """Merge updates into state.json atomically. Returns True on success."""
    p = path or app_state_path()
    try:
        d = load_state(p); d.update(updates)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(tmp, p); return True
    except Exception:
        return False

# ---------------------------------------------------------------- v1.3.2: remembered hardware check
HW_CACHE_DAYS = 30
HW_CACHE_KEYS = ("gpu", "vram_gb", "vram_src", "cpu", "cores", "threads", "ram_gb", "width", "height", "laptop", "errors")

def machine_id():
    try: n = os.environ.get("COMPUTERNAME") or (os.uname().nodename if hasattr(os, "uname") else "")
    except Exception: n = ""
    return "%s|%s" % (n, os.cpu_count() or 0)

def save_hw_cache(hw, path=None, now=None):
    """Remember a hardware check so 'Check my PC' is instant next time. Unknown cards are not remembered."""
    if not isinstance(hw, dict) or not hw.get("gpu") or hw.get("gpu") == "Unknown": return False
    keep = {k: hw[k] for k in HW_CACHE_KEYS if k in hw}
    when = (now or datetime.datetime.now()).isoformat(timespec="seconds")
    return save_state({"hw_cache": {"hw": keep, "time": when, "machine": machine_id()}}, path)

def load_hw_cache(path=None, now=None, max_days=HW_CACHE_DAYS):
    """(hw, checked_at datetime) from an earlier check on this PC, or (None, None) if missing, old or from another PC."""
    try:
        d = load_state(path).get("hw_cache")
        if not isinstance(d, dict) or d.get("machine") != machine_id(): return None, None
        hw, when = d.get("hw"), datetime.datetime.fromisoformat(str(d.get("time")))
        age = ((now or datetime.datetime.now()) - when).total_seconds()
        if not isinstance(hw, dict) or not isinstance(hw.get("gpu"), str) or age < -86400 or age > max_days * 86400: return None, None
        out = {"gpu": "Unknown", "vram_gb": 0, "cpu": "", "cores": 0, "threads": 0, "ram_gb": 0, "width": 0, "height": 0, "errors": []}
        out.update({k: hw[k] for k in HW_CACHE_KEYS if k in hw}); out["cached"] = True
        return out, when
    except Exception:
        return None, None

def hw_cache_note(when, now=None):
    """'checked today' / 'checked 3 days ago' for the Step 1 line."""
    if not when: return ""
    days = ((now or datetime.datetime.now()).date() - when.date()).days
    return "checked today" if days <= 0 else "checked yesterday" if days == 1 else "checked %d days ago" % days

def load_prefs(path=None):
    """Remembered choices, each validated – anything unknown falls back to the default."""
    raw = load_state(path).get("prefs") or {}
    out = dict(PREF_DEFAULTS)
    if not isinstance(raw, dict): return out
    checks = {"goal": lambda v: v in GOALS, "aa": lambda v: v in AA_CHOICES, "fg": lambda v: v in FG_CHOICES,
              "traffic": lambda v: v in TRAFFIC_LEVELS, "prefs_open": lambda v: isinstance(v, bool),
              "ai_enabled": lambda v: isinstance(v, bool), "ai_provider": lambda v: v in AI_PROVIDERS,
              "ai_base_url": lambda v: isinstance(v, str) and (v == "" or valid_base_url(v)),
              "ai_model": lambda v: isinstance(v, str) and len(v) <= 100 and not re.search(r"[\s\"'<>]", v)}
    for k, ok in checks.items():
        if k in raw:
            try:
                if ok(raw[k]): out[k] = raw[k]
            except Exception: pass
    return out

def save_prefs(prefs, path=None):
    clean = {k: prefs[k] for k in PREF_DEFAULTS if k in prefs}
    cur = load_state(path).get("prefs") or {}
    if not isinstance(cur, dict): cur = {}
    cur.update(clean)
    return save_state({"prefs": cur}, path)

def prefs_summary(aa, fg, traffic):
    """One plain line for the collapsed 'My preferences' section."""
    tr = "SkyTune decides" if traffic == "SkyTune decides" else traffic
    line = "Smooth edges: %s  ·  Extra frames: %s  ·  Traffic: %s" % (aa, fg, tr)
    note = choice_saved_note(aa, fg)
    return line if not note else line + "  ·  " + note

# ---------------------------------------------------------------- API key storage (AI mode, optional)
def config_dir(env=None):
    """%APPDATA%\\SkyTune on Windows, ~/.config/SkyTune elsewhere."""
    env = os.environ if env is None else env
    if env.get("APPDATA"):
        base = env["APPDATA"]
    else:
        home = env.get("HOME") or os.path.expanduser("~")
        base = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    d = os.path.join(base, "SkyTune"); os.makedirs(d, exist_ok=True)
    return d

KEY_DPAPI, KEY_PLAIN = "api_key.dpapi", "api_key.txt"

def _dpapi(data, protect):
    """Windows DPAPI (current user) through ctypes. Raises OSError when unavailable."""
    import ctypes
    from ctypes import wintypes
    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))); dst = BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(src), None, None, None, None, 0x01, ctypes.byref(dst)):     # CRYPTPROTECT_UI_FORBIDDEN
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(dst.pbData, ctypes.c_void_p))

def dpapi_available():
    if os.name != "nt": return False
    try: return _dpapi(_dpapi(b"skytune", True), False) == b"skytune"
    except Exception: return False

def save_api_key(key, env=None, allow_dpapi=True):
    """Store the user's own API key. Returns 'dpapi' (encrypted for this Windows user) or 'plain' (file only
    readable by you, NOT encrypted – the GUI warns about this)."""
    key = (key or "").strip()
    if not key or len(key) > 400 or re.search(r"\s", key): raise ValueError("That doesn't look like an API key.")
    d = config_dir(env); remove_api_key(env)
    if allow_dpapi and dpapi_available():
        blob = _dpapi(key.encode("utf-8"), True)
        with open(os.path.join(d, KEY_DPAPI), "wb") as f: f.write(b"SKYTUNE-DPAPI1\n" + base64.b64encode(blob))
        return "dpapi"
    p = os.path.join(d, KEY_PLAIN)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(key)
    try: os.chmod(p, 0o600)
    except Exception: pass
    return "plain"

def load_api_key(env=None):
    """(key or None, 'dpapi' | 'plain' | None)."""
    d = config_dir(env)
    p = os.path.join(d, KEY_DPAPI)
    if os.path.isfile(p):
        try:
            with open(p, "rb") as f: raw = f.read()
            if raw.startswith(b"SKYTUNE-DPAPI1\n"):
                return _dpapi(base64.b64decode(raw.split(b"\n", 1)[1]), False).decode("utf-8"), "dpapi"
        except Exception:
            return None, None
    p = os.path.join(d, KEY_PLAIN)
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f: k = f.read().strip()
            return (k, "plain") if k else (None, None)
        except Exception:
            return None, None
    return None, None

def remove_api_key(env=None):
    """Delete any stored key. Returns True if something was removed."""
    gone = False
    for n in (KEY_DPAPI, KEY_PLAIN):
        p = os.path.join(config_dir(env), n)
        if os.path.isfile(p):
            os.remove(p); gone = True
    return gone

# ---------------------------------------------------------------- assistant: "Anything bothering you?"
# Offline rules engine (default). Typos are handled with difflib. Nothing is ever written until the user
# clicks "Optimise my sim"; fixes are only staged.
PROBLEMS = {
    "stutter": ("Stutters", ("stutter", "stutters", "stuttering", "hitch", "hitches", "hitching", "freeze", "freezes",
                             "freezing", "jerky", "choppy", "judder", "juddering", "spikes", "microstutter", "hiccup", "hiccups"),
                ("lag spike", "frame time", "frametime", "micro stutter", "pauses")),
    "low_fps": ("Low FPS", ("fps", "framerate", "slow", "laggy", "sluggish", "performance", "slideshow", "frames"),
                ("frame rate", "low frames", "runs bad", "runs badly", "unplayable")),
    "blurry": ("Blurry", ("blurry", "blur", "blurred", "soft", "fuzzy", "smeary", "smudgy", "ghosting", "shimmer",
                          "shimmering", "jaggies", "jagged", "aliasing", "unsharp", "unreadable", "pixelated"),
               ("not sharp", "hard to read", "cockpit text")),
    "popin": ("Pop-in", ("popin", "popping", "pops", "draw", "lod", "appearing", "loading"),
              ("pop in", "pop-in", "pop up", "draw distance", "appear late", "appears late", "trees appear",
               "buildings appear", "load in", "loads in", "textures load")),
    "crash": ("Crashes", ("crash", "crashes", "crashing", "crashed", "ctd", "closes", "hangs", "freezes", "dxgi"),
              ("to desktop", "not responding", "black screen", "shuts down", "won't start", "wont start", "doesn't start")),
    "spawn": ("Slow after loading in", ("spawn", "spawning", "spawned", "respawn"),
              ("loading in", "loaded in", "loading into", "load into", "loaded into", "just loaded", "after loading",
               "after the loading screen", "when i load", "when it loads", "first minute", "first few minutes",
               "flight starts", "start of the flight", "start of a flight", "while loading", "during loading")),
    "after_update": ("After update", ("update", "updated", "patch", "patched", "su1", "su2", "su3", "su4"),
                     ("sim update", "after the update", "since the update", "driver update", "new driver", "world update")),
}
QUICK_PROBLEMS = [("Stutters", "stutter"), ("Low FPS", "low_fps"), ("Blurry", "blurry"), ("Pop-in", "popin"),
                  ("Crashes", "crash"), ("After update", "after_update")]
QUICK_TEXT = {"stutter": "My sim stutters", "low_fps": "My FPS is too low", "blurry": "The image looks blurry",
              "popin": "Scenery pops in late", "crash": "The sim crashes", "after_update": "Problems since a sim update"}

def selected_problem_text(selected, text=""):
    """v1.3.1: the chips the user selected plus what they typed, as one plain sentence (shown in the chat and
    sent to the AI)."""
    sel = [pid for _, pid in QUICK_PROBLEMS if pid in (selected or ())]
    sel += [p for p in (selected or ()) if p in PROBLEMS and p not in sel]
    parts = [QUICK_TEXT.get(p, PROBLEMS[p][0]) for p in sel]
    t = (text or "").strip()
    if t: parts.append(t)
    return "; ".join(parts)

def _join_labels(labels):
    labels = list(labels)
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]

# words that mean "you may touch my locked preferences"
PREF_WORDS = {"aa": ("dlss", "fsr", "taa", "anti-aliasing", "antialiasing", "anti aliasing", "upscaler", "upscaling", "aliasing"),
              "fg": ("frame gen", "framegen", "frame generation", "fg", "dlss fg", "fake frames", "dlssg", "fsr fg"),
              "traffic": ("traffic", "ai planes", "ai aircraft", "people", "ground crew", "airliners", "vehicles", "boats", "cars")}
FOLLOWUPS = [
    ("where", "Where does it happen?", [("At busy airports", "airport"), ("Over cities", "city"),
                                        ("In cruise", "cruise"), ("Everywhere", "everywhere")]),
    ("when", "When did it start?", [("After a sim update", "sim_update"), ("After a driver update", "driver_update"),
                                    ("After a long flight", "long_flight"), ("Always been like this", "always")]),
    ("symptom", "What does it look like?", [("Short freezes", "freezes"), ("Low FPS all the time", "low_all"),
                                            ("Blurry text or scenery", "blurry"), ("Things appear late", "late")]),
]
CTX_WORDS = {"where": {"airport": ("airport", "airports", "gate", "taxi", "taxiing", "ground", "landing", "approach", "heathrow",
                                   "jfk", "egll", "kjfk", "takeoff", "take off", "apron", "hub"),
                       "city": ("city", "cities", "london", "new york", "photogrammetry", "town", "downtown"),
                       "cruise": ("cruise", "cruising", "altitude", "high up", "airborne", "en route")},
             "when": {"sim_update": ("sim update", "after the update", "since the update", "patch", "su1", "su2", "su3"),
                      "driver_update": ("driver", "drivers", "nvidia update", "amd update"),
                      "long_flight": ("long flight", "hours", "after a while", "longer flight", "over time")}}

def _norm_text(t):
    return re.sub(r"[^a-z0-9+\-' ]+", " ", (t or "").lower().replace("’", "'"))

_NO_FUZZ = {"caches", "cached", "shader", "shaders", "settle", "settled", "settles", "loaded", "loading", "spawns"}  # real words, not typos

def _has(text, words, phrases=()):
    """Word match with difflib typo tolerance (words of 5+ letters), plus plain phrase matches."""
    t = _norm_text(text); toks = t.split()
    for ph in phrases:
        if ph in t: return True
    singles = [w for w in words if " " not in w]
    for ph in (w for w in words if " " in w):
        if ph in t: return True
    for tok in toks:
        if tok in singles: return True
        if len(tok) >= 5 and tok not in _NO_FUZZ:
            long_ = [w for w in singles if len(w) >= 5]
            if difflib.get_close_matches(tok, long_, n=1, cutoff=0.75): return True
    return False

def detect_problems(text):
    """Return problem ids found in free text, in PROBLEMS order (typos tolerated)."""
    out = []
    for pid, (_, words, phrases) in PROBLEMS.items():
        if _has(text, words, phrases): out.append(pid)
    if "crash" in out and "stutter" in out and not _has(text, ("stutter", "stutters", "stuttering", "hitch", "jerky", "choppy")):
        out.remove("stutter")              # "freezes then crashes" = a crash, not stutter
    if "spawn" in out and "popin" in out and not _has(text, ("popin", "popping", "pops"),
            ("pop in", "pop-in", "pop up", "draw distance", "appear late", "appears late", "trees appear", "buildings appear")):
        out.remove("popin")                # "slow while loading in" is the load-in dip, not scenery pop-in
    elif "spawn" in out and "popin" in out and not _has(text, PROBLEMS["spawn"][1], PROBLEMS["spawn"][2][:12]):
        out.remove("spawn")                # "pops in while loading" = pop-in; only the weak phrases matched
    return out

_CLEARED_CACHE = re.compile(r"(clear|cleared|clearing|delete|deleted|deleting|wipe|wiped)\w*\s+(the\s+|my\s+|all\s+)?(shader|cache)|fix\s+stutters", re.I)
_RECOVERED = re.compile(r"\b(settl\w*|recover\w*|goes back|went back|back to normal|then (it'?s )?fine|then ok|normal after|fine after|improves after|then smooth)\b", re.I)

def detect_context(text):
    t = _norm_text(text); ctx = {}
    for slot, opts in CTX_WORDS.items():
        for val, words in opts.items():
            toks = t.split(); singles = [w for w in words if " " not in w and len(w) >= 5]
            if any((" " in w and w in t) or w in toks for w in words) or \
               any(len(x) >= 5 and difflib.get_close_matches(x, singles, n=1, cutoff=0.8) for x in toks):
                ctx[slot] = val; break
    return ctx

def asked_prefs(text):
    """Which locked preferences the user explicitly talks about ('aa', 'fg', 'traffic')."""
    t = " " + _norm_text(text) + " "
    return {k for k, words in PREF_WORDS.items() if any((" %s " % w) in t or (" " in w and w in t) for w in words)}

def _num(v, default=None):
    try: return float(v)
    except (TypeError, ValueError): return default

def current_values(cfg):
    """path -> number/str for every known SETTINGS key in the file (exposed keys only)."""
    out = {}
    if not cfg: return out
    for s in SETTINGS:
        if s[3] == "text" or s[0] in out: continue
        v = cfg.get(s[0])
        if v is None: continue
        n = _num(v); out[s[0]] = v if n is None else (int(n) if n == int(n) and s[3] != "float" else n)
    return out

# ---- measured readouts pasted from the sim's own overlay (MSFS 2024 dev mode: Debug > Display FPS)
# e.g. "51 fps, Limited by Graphics Queue, GPU 32.6 ms, main thread 25.4 ms, terrain/objects LOD 0.50".
# A measurement beats any guess from symptoms, so diagnose_bottleneck weights it heavily.
_OV_NUM = r"(\d{1,3}(?:[.,]\d{1,2})?)"
def parse_overlay(text):
    """Return {} or a dict with any of: fps, limited ('GPU'|'CPU'), gpu_ms, main_ms, lod_floor (True when
    LOD factor readouts of 0.5 are mentioned - Dynamic Settings has cut detail to its minimum)."""
    t = (text or "").lower().replace("\u2013", "-"); out = {}
    f = lambda s: float(s.replace(",", "."))
    m = re.search(_OV_NUM + r"\s*fps\b", t) or re.search(r"\bfps\D{0,6}" + _OV_NUM, t)
    if m and 1 <= f(m.group(1)) <= 500: out["fps"] = f(m.group(1))
    if re.search(r"limited\s+by\s+(the\s+)?(graphics\s+queue|gpu|graphics\s+card|graphics)\b|\bgpu[\s-]*(bound|limited)\b", t): out["limited"] = "GPU"
    elif re.search(r"limited\s+by\s+(the\s+)?(main\s*thread|cpu|processor|main)\b|\b(cpu|main\s*thread)[\s-]*(bound|limited)\b", t): out["limited"] = "CPU"
    m = re.search(r"\b(?:gpu|graphics)(?:\s+queue)?\D{0,12}?" + _OV_NUM + r"\s*ms\b", t)
    if m: out["gpu_ms"] = f(m.group(1))
    m = re.search(r"\bmain\s*thread\D{0,12}?" + _OV_NUM + r"\s*ms\b", t) or re.search(r"\b(?:cpu|mt)\D{0,8}?" + _OV_NUM + r"\s*ms\b", t)
    if m: out["main_ms"] = f(m.group(1))
    if re.search(r"\b(lod|tlod|olod)\b[^.\n]{0,60}?\b0[.,]50?\b|\b0[.,]50?\b[^.\n]{0,20}\b(lod|tlod|olod)\b", t): out["lod_floor"] = True
    return out

BOTTLENECKS = ("CPU", "GPU", "VRAM", "Cache", "Add-ons", "Loading")
BOTTLENECK_SHORT = {"CPU": "processor", "GPU": "graphics card", "VRAM": "video memory", "Cache": "old caches",
                    "Add-ons": "add-ons", "Loading": "still loading in"}
BOTTLENECK_PLAIN = {"CPU": "your processor (too much to simulate at once)",
                    "GPU": "your graphics card (too much to draw)",
                    "VRAM": "your graphics card's memory (textures don't fit)",
                    "Cache": "old or broken cache files",
                    "Add-ons": "an add-on or leftover files after an update",
                    "Loading": "the sim still loading in (scenery streaming and shader building – a temporary dip)"}

def diagnose_bottleneck(problems, ctx, hw, cur):
    """Score each bottleneck from symptoms, context, hardware and the actual cfg values.
    Returns (name, confidence 'High'|'Medium'|'Low', reasons[list of plain strings], scores)."""
    hw = hw or {}; sc = {b: 0 for b in BOTTLENECKS}; why = {b: [] for b in BOTTLENECKS}
    def add(b, n, r):
        sc[b] += n
        if r and r not in why[b]: why[b].append(r)
    gt, _ = gpu_tier(hw.get("gpu"), hw.get("vram_gb") or 0) if hw.get("gpu") else (None, None)
    ct = cpu_tier(hw.get("cpu")) if hw.get("cpu") else None
    vram = hw.get("vram_gb") or 0; cores = hw.get("cores") or 0
    px = (hw.get("width") or 0) * (hw.get("height") or 0)
    where, when = ctx.get("where"), ctx.get("when"); sym = ctx.get("symptom")
    traffic = max([cur.get(p, -1) for p, _, _ in TRAFFIC_CATS[:4] if isinstance(cur.get(p), (int, float))] or [-1])
    olod = cur.get("Graphics/ObjectsLoD/LoDFactor"); tlod = cur.get("Graphics/Terrain/LoDFactor")
    tex = cur.get("Graphics/Texture/Quality"); clouds = cur.get("Graphics/VolumetricClouds/Quality")
    scale = cur.get("Video/PrimaryScaling"); shadows = cur.get("Graphics/Shadows/Size")
    slow = "low_fps" in problems or "stutter" in problems or sym in ("freezes", "low_all")
    if slow:
        if where in ("airport", "city"): add("CPU", 3, "It happens at busy airports or over cities – that's processor work (traffic, people, buildings).")
        if where == "cruise": add("GPU", 2, "It happens in cruise, where the processor has little to do – so it's the graphics card.")
        if isinstance(traffic, (int, float)) and traffic >= 2: add("CPU", 1, "AI traffic or people are set to High or more in your settings.")
        if isinstance(olod, (int, float)) and olod > 1.5: add("CPU", 1, "Object distance (OLOD) is %.2f – high values load the processor." % olod)
        if isinstance(tlod, (int, float)) and tlod > 2.0: add("CPU", 1, "Terrain distance (TLOD) is %.2f – very high values load processor and graphics card." % tlod); add("GPU", 1, None)
        if ct is not None and ct <= 1: add("CPU", 2, "Your processor (%s) is on the slower side for MSFS." % hw.get("cpu"))
        elif cores and cores < 6: add("CPU", 1, "Your processor has %d cores – MSFS likes 6 or more." % cores)
        if gt is not None and gt <= 1: add("GPU", 2, "Your graphics card (%s) is entry-level for MSFS." % hw.get("gpu"))
        if px >= 2560 * 1440 and isinstance(scale, (int, float)) and scale >= 1.0: add("GPU", 1, "You render at %dx%d or more at full scale." % (hw.get("width"), hw.get("height")))
        if isinstance(clouds, (int, float)) and clouds >= 3: add("GPU", 1, "Clouds are on Ultra – one of the heaviest settings.")
        if isinstance(shadows, (int, float)) and shadows >= 2048: add("GPU", 1, "Shadow maps are 2048 or more.")
        if "low_fps" in problems and where in (None, "everywhere") and sym != "freezes": add("GPU", 1, None)
    ov = ctx.get("overlay") or {}
    if ov.get("limited") in ("GPU", "CPU"):
        b = ov["limited"]
        add(b, 8, "The sim's own readout says it is limited by %s – that's a measurement, so it beats any guess." %
            ("the graphics queue (graphics card)" if b == "GPU" else "the main thread (processor)"))
    g, mt = ov.get("gpu_ms"), ov.get("main_ms")
    if g and mt and abs(g - mt) / max(g, mt) >= 0.12:
        b = "GPU" if g > mt else "CPU"
        add(b, 3, "Graphics card time (%.1f ms) is %s than main-thread time (%.1f ms)." % (g, "longer" if g > mt else "shorter", mt))
    if "spawn" in problems and "crash" not in problems:
        add("Loading", 10, "It happens right after loading in – the sim is still streaming scenery, building shaders and filling its cache.")
        if ctx.get("recovered"): add("Loading", 2, "It gets better after a while on its own – typical for loading, not for settings.")
        if ctx.get("cleared_cache") or when in ("sim_update", "driver_update"):
            add("Loading", 1, "Shaders are rebuilt after clearing caches or an update, so the first load-in is slower.")
    if "stutter" in problems or sym == "freezes":
        add("Cache", 1, "Stutters are often caused by stale shader caches.")
        if vram and isinstance(tex, (int, float)) and ((vram <= 8 and tex <= 0) or (vram < 8 and tex <= 1)):
            add("VRAM", 3, "Textures are set to %s but your card has %.0f GB of video memory." % ({0: "Ultra", 1: "High"}.get(int(tex), "?"), vram))
        if when == "long_flight": add("VRAM", 2, "It gets worse during long flights – video memory fills up.")
    if "popin" in problems or sym == "late":
        if isinstance(tlod, (int, float)) and tlod < 1.0: add("GPU", 0, "Terrain distance (TLOD) is only %.2f." % tlod)
        if vram and vram < 8: add("VRAM", 2, "%.0f GB of video memory makes scenery stream in later." % vram)
        add("Cache", 1, "Scenery that loads late can also be an old scenery index.")
    if "after_update" in problems or when in ("sim_update", "driver_update"):
        add("Cache", 3, "Problems right after an update usually come from old caches built for the previous version.")
        if when != "driver_update": add("Add-ons", 2, "Add-ons in your Community folder often break after sim updates.")
    if "crash" in problems:
        add("Add-ons", 3, "Crashes are most often caused by an outdated add-on.")
        if "after_update" in problems or when == "sim_update": add("Add-ons", 2, None)
        if vram and vram <= 8 and isinstance(tex, (int, float)) and tex <= 0: add("VRAM", 2, "Ultra textures on %.0f GB can run the card out of memory." % vram)
    if "blurry" in problems:
        if isinstance(scale, (int, float)) and scale < 1.0: add("GPU", 0, None)
    order = sorted(BOTTLENECKS, key=lambda b: (-sc[b], BOTTLENECKS.index(b)))
    top, second = order[0], order[1]
    if sc[top] <= 0:
        return None, "Low", ["Tell me a bit more – where and when does it happen?"], sc
    conf = "High" if sc[top] >= 4 and sc[top] - sc[second] >= 2 else "Medium" if sc[top] >= 2 else "Low"
    if top == "Loading": conf = "High" if ctx.get("recovered") else "Medium"
    if ov.get("limited") and ov["limited"] != top and conf == "High": conf = "Medium"
    return top, conf, why[top] or ["Based on what you described."], sc

IMPACT_W = {"High": 3, "Med": 2, "Low": 1}

def _fix(fid, title, why, impact, cost, targets, problems, changes=None, tool=None, pref=None):
    return {"id": fid, "title": title, "why": why, "impact": impact, "cost": cost, "targets": targets,
            "problems": problems, "changes": changes or {}, "tool": tool, "pref": pref}

def candidate_fixes(problems, ctx, hw, cur, locked=("aa", "fg", "traffic"), asked=()):
    """All fixes that would actually change something (or run a tool). Locked user preferences are left
    alone unless the user asked about them."""
    hw = hw or {}; vram = hw.get("vram_gb") or 0; F = []
    ct = cpu_tier(hw.get("cpu")) if hw.get("cpu") else None
    gpu_measured = ((ctx or {}).get("overlay") or {}).get("limited") == "GPU"   # the sim itself says GPU-bound
    def lower(p, target):
        v = cur.get(p); return {p: target} if isinstance(v, (int, float)) and v > target else {}
    def raise_(p, target):
        v = cur.get(p); return {p: target} if isinstance(v, (int, float)) and v < target else {}
    def better_tex_than(target):   # texture quality is inverted: 0 = Ultra
        v = cur.get("Graphics/Texture/Quality"); return {"Graphics/Texture/Quality": target} if isinstance(v, (int, float)) and v < target else {}
    F.append(_fix("clear_shaders", "Clear shader caches (Fix stutters)", "Removes old shader and sim caches that cause stutters after driver or sim updates.",
                  "High", "First flight loads slower", ("Cache",), ("stutter", "after_update", "popin"), tool="fix_stutters"))
    F.append(_fix("update_cleanup", "Run Update Cleanup", "Moves your add-ons aside (renamed, never deleted) and clears update leftovers – the quickest way to find a broken add-on.",
                  "High", "Add-ons off until you move them back · undoable", ("Add-ons",), ("crash", "after_update"), tool="update_cleanup"))
    olod_t = 0.8 if (ct is not None and ct <= 1) else 1.0
    F.append(_fix("lower_olod", "Lower object distance", "Fewer buildings and objects to simulate far away – the biggest processor saver.",
                  "High", "Objects appear a little later", ("CPU",), ("stutter", "low_fps"), lower("Graphics/ObjectsLoD/LoDFactor", olod_t)))
    F.append(_fix("lower_tlod", "Lower terrain distance", "Less terrain detail far away – helps both processor and graphics card.",
                  "Med", "Distant hills less detailed", ("CPU", "GPU"), ("stutter", "low_fps"), lower("Graphics/Terrain/LoDFactor", 1.0)))
    F.append(_fix("glass_cockpit", "Slower glass-cockpit refresh", "Cockpit screens update a bit less often – frees processor time in airliners.",
                  "Low", "Cockpit screens slightly less smooth", ("CPU",), ("stutter", "low_fps"), lower("Graphics/GlassCockpitsRefreshRate/Quality", 1)))
    F.append(_fix("fps_cap", "Cap the frame rate", "A steady 30 FPS feels smoother than jumping between 25 and 50.",
                  "Med", "No more than 30 FPS", ("CPU",), ("stutter",),
                  {"Video/FrameLimiter": 30} if cur.get("Video/FrameLimiter") in (0, 0.0) else {}))
    tex_t = 1 if vram >= 8 else 2
    F.append(_fix("textures_fit", "Textures that fit your video memory", "Ultra textures overflow the graphics card's memory, which causes stutters and crashes.",
                  "High", "Slightly softer up close", ("VRAM",), ("stutter", "crash", "popin", "spawn"), better_tex_than(tex_t)))
    # load-in dip: keep off-screen pre-caching sensible (more = more to load and more memory) and TLOD within video memory
    pc_t = 2 if (not vram or vram >= 8) else 1; pc = cur.get("Graphics/OffscreenTerrainPreCaching/Quality")
    F.append(_fix("precache_sensible", "Sensible terrain pre-loading", "Pre-loads terrain around you at a level your video memory handles, so loading in settles faster.",
                  "Med", "None worth noting", ("Loading", "VRAM"), ("spawn",),
                  {"Graphics/OffscreenTerrainPreCaching/Quality": pc_t} if isinstance(pc, (int, float)) and pc != pc_t else {}))
    tl_t = 1.5 if (vram and vram < 8) else 2.0
    F.append(_fix("tlod_vram", "Terrain distance that fits your video memory", "Very high terrain distance can fill %s video memory while scenery loads." % ("your %.0f GB of" % vram if vram else "the"),
                  "Med", "Distant hills less detailed", ("Loading", "VRAM"), ("spawn",),
                  lower("Graphics/Terrain/LoDFactor", tl_t) if (vram and vram <= 8) else {}))
    F.append(_fix("clouds_down", "Lighter clouds", "3D clouds are one of the heaviest settings for the graphics card.",
                  "High", "Clouds slightly less detailed", ("GPU",), ("low_fps",), lower("Graphics/VolumetricClouds/Quality", 1 if (gpu_measured or (hw and (gpu_tier(hw.get("gpu"), vram)[0] if hw.get("gpu") else 2) <= 1)) else 2)))
    sh = {}
    sh.update(lower("Graphics/Shadows/Size", 1024 if gpu_measured else 1536)); sh.update(lower("Graphics/ContactShadows/Quality", 1))
    sh.update(lower("Graphics/RaytracedShadows/Enabled", 0))
    F.append(_fix("shadows_down", "Lighter shadows", "Smaller shadow maps and no ray-traced shadows free up the graphics card.",
                  "Med", "Shadows a bit softer", ("GPU", "VRAM"), ("low_fps",), sh))
    rs = {}
    if cur.get("Video/AntiAliasing") == "TAA": rs = lower("Video/PrimaryScaling", 0.9)
    F.append(_fix("render_scale_down", "Render a little below screen resolution", "Draws 10% fewer pixels – the graphics card gets a lot faster.",
                  "Med", "Slightly softer image", ("GPU",), ("low_fps",), rs))
    pre = raise_("Graphics/OffscreenTerrainPreCaching/Quality", 2)
    F.append(_fix("precache", "Pre-load terrain off-screen", "Loads terrain around you before you look at it, so less pops in.",
                  "Med", "Slightly more memory use", ("Cache", "VRAM", "CPU"), ("popin", "stutter"), pre))
    pop = {}
    if not (ct is not None and ct <= 1):
        pop.update(raise_("Graphics/Terrain/LoDFactor", 1.5 if vram >= 8 else 1.2))
    F.append(_fix("raise_tlod", "Show terrain detail further away", "Detailed terrain loads further ahead, so less appears suddenly.",
                  "Med", "Costs some FPS", ("GPU",), ("popin",), pop))
    bl = {}
    if cur.get("Video/AntiAliasing") == "TAA": bl.update(raise_("Video/PrimaryScaling", 1.0))
    bl.update(raise_("Graphics/Texture/MaxAnisotropy", 16))
    F.append(_fix("sharper", "Sharper image", "Renders at full screen resolution with full texture filtering, so text and runways stay crisp.",
                  "High", "Costs a little FPS", ("GPU",), ("blurry",), bl))
    shp = raise_("Video/SharpenAmount", 0.5)
    F.append(_fix("sharpen", "A touch of sharpening", "Adds light sharpening to counter the soft look of edge smoothing.",
                  "Low", "None", ("GPU",), ("blurry",), shp))
    # ---- locked preferences: only when the user asked about them
    allow = lambda k: (k not in locked) or (k in asked)
    if allow("traffic"):
        tr = {}
        for p, _, _ in TRAFFIC_CATS[:4]: tr.update(lower(p, 0))
        F.append(_fix("traffic_down", "Less AI traffic and people", "AI planes, ground vehicles and people are the biggest processor cost at busy airports.",
                      "High", "Quieter airports", ("CPU",), ("stutter", "low_fps"), tr, pref="traffic"))
    if allow("aa"):
        q = {}
        if cur.get("Video/AntiAliasing") == "DLSS" and cur.get("Video/DLSSMode") in ("PERFORMANCE", "BALANCED", "ULTRA_PERFORMANCE", "AUTO"):
            q["Video/DLSSMode"] = "QUALITY"
        if cur.get("Video/AntiAliasing") == "FSR" and cur.get("Video/FSRMode") in ("PERFORMANCE", "BALANCED"): q["Video/FSRMode"] = "QUALITY"
        F.append(_fix("upscaler_quality", "Upscaling on Quality", "Your DLSS/FSR upscaling is set to a faster mode, which looks soft. Quality is sharper.",
                      "High", "Costs some FPS", ("GPU",), ("blurry",), q, pref="aa"))
        if gpu_measured:   # the sim says the graphics card is the limit: let the upscaler do a bit more
            u = {}
            if cur.get("Video/AntiAliasing") == "DLSS" and cur.get("Video/DLSSMode") in ("QUALITY", "DLAA"): u["Video/DLSSMode"] = "BALANCED"
            if cur.get("Video/AntiAliasing") == "FSR" and cur.get("Video/FSRMode") in ("QUALITY", "NATIVE_AA"): u["Video/FSRMode"] = "BALANCED"
            F.append(_fix("upscaler_faster", "Upscaling on Balanced", "The graphics card draws fewer pixels and DLSS/FSR fills in the rest – a solid FPS gain when the card is the limit.",
                          "Med", "Slightly softer image", ("GPU",), ("low_fps",), u, pref="aa"))
    if allow("fg"):
        fgv = cur.get("Video/FrameGeneration")
        F.append(_fix("fg_off", "Turn off extra frames", "Extra frames (frame generation) can cause crashes and uneven motion when the base frame rate is low.",
                      "Med", "Motion less smooth", ("GPU", "Add-ons"), ("crash", "stutter"),
                      {"Video/FrameGeneration": "NONE"} if fgv not in (None, "NONE") else {}, pref="fg"))
        F.append(_fix("fg_on", "Try extra frames (AMD FSR)", "Adds in-between frames (frame generation) so motion looks smoother when your processor is the limit.",
                      "Med", "Slight input delay", ("CPU",), ("low_fps",),
                      {"Video/FrameGeneration": "FSRFG"} if fgv == "NONE" else {}, pref="fg"))
    return [f for f in F if f["changes"] or f["tool"]]

def dedupe_fixes(ranked, conflicts=None):
    """v1.3.1: merge a best-first fix list. A tool is listed once; a setting is changed by the best-ranked fix
    only, so duplicates disappear and opposite changes (e.g. lower vs raise terrain distance when both FPS and
    pop-in are picked) can't both be staged. A fix left with nothing to change is dropped."""
    kept, claimed, tools = [], {}, set()
    for f in ranked:
        if f.get("tool"):
            if f["tool"] in tools: continue
            tools.add(f["tool"]); kept.append(f); continue
        ch = {k: v for k, v in f["changes"].items() if k not in claimed}
        clash = [k for k, v in f["changes"].items() if k in claimed and claimed[k][0] != v]
        if clash and conflicts is not None:
            conflicts.append((f["title"], claimed[clash[0]][1]))
        if not ch: continue
        if len(ch) != len(f["changes"]): f = dict(f, changes=ch)
        for k, v in ch.items(): claimed[k] = (v, f["title"])
        kept.append(f)
    return kept

def rank_fixes(fixes, problems, bottleneck, ctx=None, limit=None, conflicts=None):
    """Order fixes by relevance to the problems, then the diagnosed bottleneck, then impact. A fix must match
    one of the problems to be listed. Returns at most 6 (8 when several problems are picked), with impact
    upgraded when it targets the bottleneck. With several problems the list is merged and de-duplicated, and
    each problem keeps at least its best fix."""
    ctx = ctx or {}
    if bottleneck == "Loading":   # a temporary load-in dip: no tools (clearing caches makes the next load slower) and no general cuts
        fixes = [f for f in fixes if "spawn" in f["problems"] and not f.get("tool")]
    meas = (ctx.get("overlay") or {}).get("limited")
    if meas in ("GPU", "CPU") and bottleneck == meas:   # the sim measured the limit: skip fixes that only help the other side
        other = "CPU" if meas == "GPU" else "GPU"
        fixes = [f for f in fixes if tuple(f["targets"]) != (other,)]
    def score(f):
        rel = sum(1 for p in f["problems"] if p in problems)
        if not rel: return None
        s = IMPACT_W[f["impact"]] + 3 * rel
        if bottleneck and bottleneck in f["targets"]: s += 4 if f["targets"][0] == bottleneck else 2
        if f["tool"] == "update_cleanup" and "crash" not in problems and ctx.get("when") != "sim_update": s -= 4
        return s
    scored = [(score(f), i, f) for i, f in enumerate(fixes)]
    out = []
    for s, i, f in sorted((x for x in scored if x[0] is not None), key=lambda x: (-x[0], x[1])):
        g = dict(f, score=s)
        if bottleneck and bottleneck == f["targets"][0] and f["impact"] == "Med": g["impact"] = "High"
        g["covers"] = [p for p in problems if p in f["problems"]]
        out.append(g)
    out = dedupe_fixes(out, conflicts)
    limit = limit or (6 if len(problems) <= 2 else 8)
    pick = []
    for p in problems:            # every problem gets its best fix in the list (when it has one)
        f = next((f for f in out if p in f["problems"]), None)
        if f is not None and f not in pick: pick.append(f)
    for f in out:
        if len(pick) >= limit: break
        if f not in pick: pick.append(f)
    return [f for f in out if f in pick]

def open_followups(ctx):
    return [(slot, q, opts) for slot, q, opts in FOLLOWUPS if slot not in ctx]

def assistant_diagnose(text, hw=None, cfg=None, goal=DEFAULT_GOAL, ctx=None, history=(), locked=("aa", "fg", "traffic"), selected=()):
    """Offline diagnosis. text = the latest message; history = earlier user messages (strings);
    selected = problem ids picked with the quick chips (v1.3.1: several at once, combined with the text).
    Returns a dict the GUI renders and the AI mode receives as context."""
    selected = [p for p in (selected or ()) if p in PROBLEMS]
    alltext = " ".join(list(history) + [text or ""])
    ov = parse_overlay(alltext)
    rtext = alltext
    if ov:   # readout labels ("LOD factor 0.50", "frame time 19 ms") are numbers, not complaints
        rtext = re.sub(r"\b[to]?lod\b(\s*factors?)?(\s*readouts?)?", " ", rtext, flags=re.I)
        rtext = re.sub(r"\bframe\s*-?time\b(?=\D{0,8}\d)", " ", rtext, flags=re.I)
    problems = detect_problems(rtext); c = detect_context(rtext); c.update(ctx or {})
    problems = [p for p in PROBLEMS if p in problems or p in selected]   # chips + typed text, one list
    if c.get("symptom") == "freezes" and "stutter" not in problems: problems.append("stutter")
    if c.get("symptom") == "low_all" and "low_fps" not in problems: problems.append("low_fps")
    if c.get("symptom") == "blurry" and "blurry" not in problems: problems.append("blurry")
    if c.get("symptom") == "late" and "popin" not in problems: problems.append("popin")
    if c.get("when") in ("sim_update", "driver_update") and "after_update" not in problems: problems.append("after_update")
    if "spawn" in problems:
        if _CLEARED_CACHE.search(alltext): c["cleared_cache"] = True
        if _RECOVERED.search(alltext): c["recovered"] = True
    if ov:
        c["overlay"] = ov
        # pasted performance readouts without a named complaint = "I want more FPS"
        if (ov.get("limited") or ov.get("fps")) and not any(p in problems for p in ("low_fps", "stutter", "spawn")): problems.append("low_fps")
    cur = current_values(cfg) if cfg is not None and not isinstance(cfg, dict) else dict(cfg or {})
    bn, conf, why, scores = diagnose_bottleneck(problems, c, hw, cur)
    asked = asked_prefs(alltext)
    conflicts = []
    fixes = rank_fixes(candidate_fixes(problems, c, hw, cur, locked, asked), problems, bn, c, conflicts=conflicts) if problems else []
    if not problems:
        msg = "I didn't quite catch that. Pick one or more of the quick buttons above, or describe what you see (e.g. “stutters at busy airports”)."
    elif not fixes:
        msg = ("Your graphics settings are already light for this card, so there's little left to trim without losing a lot of "
               "image quality. For more FPS, let upscaling do more (set Smooth edges in My preferences to DLSS or FSR), or tell me more." if (c.get("overlay") or {}).get("limited") == "GPU" else
               "Your settings already look right for this. Try “Fix stutters” or tell me more.")
    else:
        msg = "Looks like %s. Best first step: %s." % (BOTTLENECK_PLAIN.get(bn, "a mix of things") if bn else "a mix of things", (fixes[0]["title"] if fixes[0]["title"][:2].isupper() else fixes[0]["title"][:1].lower() + fixes[0]["title"][1:]))
        if len(problems) > 1:
            msg = "You mentioned %s. " % _join_labels(PROBLEMS[p][0] for p in problems) + \
                  "Main cause: %s. Best first step: %s." % (BOTTLENECK_PLAIN.get(bn, "a mix of things") if bn else "a mix of things",
                                                           fixes[0]["title"][:1].lower() + fixes[0]["title"][1:] if not fixes[0]["title"][:2].isupper() else fixes[0]["title"])
    per_problem = []
    if len(problems) > 1:          # one line per problem: its own likely cause and its best fix in the merged list
        for p in problems:
            b1, _, _, _ = diagnose_bottleneck([p], c, hw, cur)
            f1 = next((f for f in fixes if p in f["problems"]), None)
            per_problem.append({"id": p, "label": PROBLEMS[p][0], "cause": BOTTLENECK_SHORT.get(b1) if b1 else None,
                                "fix": f1["title"] if f1 else None})
    notes = []
    for lost, won in conflicts[:1]:
        notes.append("Two of your problems pull the same setting in opposite directions – I kept “%s” and left out the "
                     "opposite part of “%s”. Try one at a time." % (won, lost))
    if bn == "Loading":
        notes.append("A big FPS drop for the first minute or two after loading in is normal: the sim is still streaming scenery, "
                     "compiling shaders and filling its rolling cache. Wait on the ground for a minute or two before judging FPS.")
        notes.append(("You cleared caches or updated recently, so shaders are being rebuilt – this first load-in takes longer. That's expected once."
                      if c.get("cleared_cache") or c.get("when") in ("sim_update", "driver_update") else
                      "The first flight after clearing shader caches or a driver/sim update dips longer, because shaders are rebuilt."))
        notes.append("Don't clear shader caches before every flight – that makes every load-in slow again. Use Fix stutters only after "
                     "a driver or sim update, or when stutters don't go away.")
        tl = cur.get("Graphics/Terrain/LoDFactor"); vr = (hw or {}).get("vram_gb") or 0
        if vr and vr <= 8 and isinstance(tl, (int, float)) and tl > 1.5:
            notes.append("With %.0f GB of video memory, terrain distance %.2f can fill it while scenery loads – keep it at 2.00 or lower." % (vr, tl))
        if not c.get("recovered"):
            notes.append("If FPS hasn't recovered after 2–3 minutes, tell me – then it's your settings, not loading.")
    if ov.get("lod_floor"):
        notes.append("Your LOD readouts at 0.50 mean the sim's Dynamic Settings has already halved terrain and object "
                     "distance to chase its frame-rate target (0.50 is its minimum). Lowering LOD further won't help much; "
                     "lower the frame-rate target or turn Dynamic Settings off for steady detail.")
    if ov.get("limited") == "GPU" and bn == "GPU":
        notes.append("Traffic and object distance mostly cost processor time, so they won't raise FPS much here.")
    if bn == "Loading":
        msg = "Looks like a temporary dip while the sim loads in, not a settings problem." + \
              (" Optional: %s." % (fixes[0]["title"][:1].lower() + fixes[0]["title"][1:]) if fixes else " Your settings look fine for this.")
    return {"source": "offline", "problems": problems, "selected": selected, "per_problem": per_problem, "notes": notes, "problem_labels": [PROBLEMS[p][0] for p in problems], "context": c,
            "bottleneck": bn, "confidence": conf, "why": why, "fixes": fixes,
            "followups": [x for x in open_followups(c) if not (problems and x[0] == "symptom")],
            "message": msg, "asked_prefs": sorted(asked), "goal": goal}

# ---------------------------------------------------------------- feedback loop (Better / Same / Worse)
class FixSession:
    """Tracks one problem-solving session. GUI: stage(fix) -> user clicks Optimise -> applied(backup)
    -> feedback('better'|'same'|'worse'). Worse means: restore that backup, then try the next fix."""
    def __init__(self, diagnosis):
        self.d = diagnosis; self.tried = []; self.current = None; self.backup = None; self.done = False
    def next_fix(self):
        return next((f for f in self.d.get("fixes", []) if f["id"] not in self.tried), None)
    def stage(self, fix):
        self.current = fix; self.backup = None
        if fix["id"] not in self.tried: self.tried.append(fix["id"])
        return fix
    def applied(self, backup_path):
        self.backup = backup_path
    def feedback(self, verdict):
        verdict = (verdict or "").lower()
        if verdict not in ("better", "same", "worse"): raise ValueError(verdict)
        nxt = self.next_fix()
        if verdict == "better":
            self.done = True
            return {"action": "keep", "undo": None, "next": None, "message": "Great – keeping it. Enjoy your flight!"}
        if verdict == "same":
            return {"action": "keep", "undo": None, "next": nxt,
                    "message": ("Kept it. Next try: %s." % nxt["title"]) if nxt else "Kept it. I'm out of ideas for this one – try Advanced, or ask in AI mode."}
        undo = self.backup if (self.current and not self.current.get("tool")) else None
        return {"action": "undo" if undo else "none", "undo": undo, "next": nxt,
                "message": ("Undone. Next try: %s." % nxt["title"]) if nxt and undo else
                           ("Next try: %s." % nxt["title"]) if nxt else "Undone. I'm out of ideas for this one."}

# ---------------------------------------------------------------- AI mode (optional, the user's own key)
AI_PROVIDERS = {
    "openai": {"label": "OpenAI-compatible", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "anthropic": {"label": "Anthropic", "base_url": "https://api.anthropic.com", "model": "claude-3-5-haiku-latest"},
}
AI_TIMEOUT = 20

def valid_base_url(u):
    """https:// anywhere, or plain http:// only to this computer (for local models)."""
    try: pu = urllib.parse.urlparse(u)
    except Exception: return False
    if pu.scheme == "https" and pu.hostname: return True
    return pu.scheme == "http" and pu.hostname in ("localhost", "127.0.0.1", "::1")

def ai_whitelist(cfg_or_values, locked=("aa", "fg", "traffic"), asked=()):
    """Keys the AI may suggest, with allowed values: {path: ('choice', [values]) | ('range', lo, hi, step)}.
    Only keys present in the user's file; locked preference keys only when the user asked about them."""
    cur = current_values(cfg_or_values) if not isinstance(cfg_or_values, dict) else cfg_or_values
    pref_keys = {"aa": {"Video/AntiAliasing", "Video/DLSSMode", "Video/FSRMode"},
                 "fg": {"Video/FrameGeneration", "Video/NBFramesToGenerate"},
                 "traffic": {p for p, _, _ in TRAFFIC_CATS}}
    blocked = set()
    for k, keys in pref_keys.items():
        if k in locked and k not in asked: blocked |= keys
    wl = {}
    for path, label, group, kind, spec, tip in SETTINGS:
        if kind == "text" or path in blocked or path not in cur: continue
        if kind == "choice":
            vals = list(spec.values())
            if path in wl and wl[path][0] == "choice":      # advanced row widens the list
                vals = sorted(set(wl[path][1]) | set(vals), key=lambda x: (str(type(x)), x))
            wl[path] = ("choice", vals)
        else:
            lo, hi, step = spec
            if path in wl and wl[path][0] == "range": lo, hi = min(lo, wl[path][1]), max(hi, wl[path][2])
            if group != "advanced":
                hi = min(hi, 4.0) if "LoDFactor" in path else hi    # never more than the in-game maximum from AI
            wl[path] = ("range", lo, hi, step)
    return wl

def _clean_str(s, n=220):
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()
    return s[:n]

def validate_ai_changes(changes, wl):
    """Keep only whitelisted keys with valid values. Returns (clean, rejected[list of str])."""
    clean, rej = {}, []
    if not isinstance(changes, dict): return clean, ["changes is not an object"]
    for k, v in list(changes.items())[:20]:
        if k not in wl: rej.append("%s: not allowed" % _clean_str(k, 60)); continue
        spec = wl[k]
        if spec[0] == "choice":
            allowed = spec[1]
            hit = next((a for a in allowed if str(a).upper() == str(v).upper()), None)
            if hit is None:
                n = _num(v)
                hit = next((a for a in allowed if isinstance(a, (int, float)) and n is not None and float(a) == n), None)
            if hit is None: rej.append("%s=%s: not a valid value" % (k, _clean_str(v, 20))); continue
            clean[k] = hit
        else:
            n = _num(v)
            if n is None or isinstance(v, bool) or n != n: rej.append("%s: not a number" % k); continue
            lo, hi, step = spec[1], spec[2], spec[3]
            if n < lo or n > hi: rej.append("%s=%s: out of range %s–%s" % (k, n, lo, hi)); continue
            q = round(round(n / step) * step, 4)
            clean[k] = int(q) if step >= 1 and float(q).is_integer() else q
    return clean, rej

def parse_ai_reply(text, wl):
    """Strict JSON (an optional single ```json fence is tolerated). Raises ValueError when unusable."""
    t = (text or "").strip()
    m_ = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m_: t = m_.group(1)
    if not t.startswith("{"): raise ValueError("reply is not a JSON object")
    obj = json.loads(t)
    if not isinstance(obj, dict) or not isinstance(obj.get("fixes"), list): raise ValueError("reply has no fixes list")
    bn = obj.get("bottleneck") if obj.get("bottleneck") in BOTTLENECKS else None
    conf = obj.get("confidence") if obj.get("confidence") in ("High", "Medium", "Low") else "Low"
    fixes, rejected = [], []
    for n, f in enumerate(obj["fixes"][:8]):
        if not isinstance(f, dict): continue
        ch, rej = validate_ai_changes(f.get("changes"), wl); rejected += rej
        if not ch: continue
        imp = {"high": "High", "med": "Med", "medium": "Med", "low": "Low"}.get(str(f.get("impact", "")).lower(), "Med")
        fixes.append({"id": "ai_%d" % n, "title": _clean_str(f.get("title"), 80) or "AI suggestion %d" % (n + 1),
                      "why": _clean_str(f.get("why")), "impact": imp, "cost": _clean_str(f.get("cost"), 60) or "–",
                      "targets": (bn or "GPU",), "problems": (), "changes": ch, "tool": None, "pref": None, "score": 0})
    if not fixes: raise ValueError("no valid changes in reply" + (" (%s)" % "; ".join(rejected[:3]) if rejected else ""))
    return {"bottleneck": bn, "confidence": conf, "message": _clean_str(obj.get("summary"), 300),
            "why": [_clean_str(x) for x in (obj.get("why") or [])[:4] if isinstance(x, str)], "fixes": fixes[:6], "rejected": rejected}

AI_SYSTEM = ("You are SkyTune's Microsoft Flight Simulator graphics assistant. Reply with ONE JSON object only, no prose: "
             "{\"bottleneck\": \"CPU|GPU|VRAM|Cache|Add-ons|Loading\", \"confidence\": \"High|Medium|Low\", \"summary\": \"one friendly sentence\", "
             "\"why\": [\"short reason\"], \"fixes\": [{\"title\": \"short\", \"why\": \"one sentence\", \"impact\": \"High|Med|Low\", "
             "\"cost\": \"what the user gives up\", \"changes\": {\"<key>\": <value>}}]}. Use ONLY keys from allowed_keys and values within "
             "their allowed values/ranges. Rank fixes best first, at most 5. Never change keys that are not listed. "
             "When several problems are listed, give one combined answer whose fixes cover all of them, without duplicates "
             "or contradicting changes.")

def ai_payload(text, history, hw, wl, cur, diagnosis, goal, edition, selected=()):
    """Exactly what is sent: the problem text (selected problem chips + typed text), a hardware summary and the
    exposed graphics keys (+ the offline diagnosis)."""
    hw = hw or {}
    sel = [p for p in (selected or ()) if p in PROBLEMS]
    out = {"problem": _clean_str(selected_problem_text(sel, text) if sel else text, 1000),
            "earlier_messages": [_clean_str(h, 400) for h in list(history)[-6:]],
            "context": diagnosis.get("context", {}), "goal": goal, "simulator": "MSFS %s" % edition if edition in ("2020", "2024") else "MSFS",
            "hardware": {"gpu": hw.get("gpu"), "vram_gb": hw.get("vram_gb"), "cpu": hw.get("cpu"), "cores": hw.get("cores"),
                         "threads": hw.get("threads"), "ram_gb": hw.get("ram_gb"), "display": "%sx%s" % (hw.get("width"), hw.get("height"))},
            "offline_diagnosis": {"bottleneck": diagnosis.get("bottleneck"), "confidence": diagnosis.get("confidence"),
                                  "reasons": diagnosis.get("why", []), "problems": diagnosis.get("problems", [])},
            "allowed_keys": {k: ({"values": v[1]} if v[0] == "choice" else {"min": v[1], "max": v[2], "step": v[3]}) for k, v in wl.items()},
            "current_values": {k: cur[k] for k in wl if k in cur}}
    if sel:                                    # v1.3.1: every problem the user picked, so the AI answers all of them
        out["selected_problems"] = [PROBLEMS[p][0] for p in sel]
        out["all_problems"] = [PROBLEMS[p][0] for p in diagnosis.get("problems", []) if p in PROBLEMS]
    return out

def ai_http(provider, base_url, model, key, payload, timeout=AI_TIMEOUT, urlopen=None):
    """One HTTPS request with urllib. Returns the model's text reply."""
    urlopen = urlopen or urllib.request.urlopen
    base = (base_url or AI_PROVIDERS[provider]["base_url"]).rstrip("/"); model = model or AI_PROVIDERS[provider]["model"]
    if not valid_base_url(base): raise ValueError("Base URL must start with https:// (or http://localhost).")
    user = json.dumps(payload, separators=(",", ":"))
    if provider == "anthropic":
        url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        body = {"model": model, "max_tokens": 1200, "temperature": 0.2, "system": AI_SYSTEM, "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    else:
        url = base + "/chat/completions"
        body = {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": AI_SYSTEM}, {"role": "user", "content": user}]}
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    headers["User-Agent"] = "SkyTune/" + VERSION
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read(2_000_000).decode("utf-8"))
    if provider == "anthropic":
        return "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
    return data["choices"][0]["message"]["content"]

def ai_diagnose(text, history=(), hw=None, cfg=None, goal=DEFAULT_GOAL, ctx=None, edition="unknown", key=None,
                provider="openai", base_url="", model="", locked=("aa", "fg", "traffic"), timeout=AI_TIMEOUT, urlopen=None, selected=()):
    """AI mode. Always computes the offline diagnosis first; on any error or timeout returns it unchanged
    with source='offline' and fallback_reason set."""
    off = assistant_diagnose(text, hw, cfg, goal, ctx, history, locked, selected)
    if not key:
        return dict(off, fallback_reason="no API key saved")
    cur = current_values(cfg) if cfg is not None and not isinstance(cfg, dict) else dict(cfg or {})
    wl = ai_whitelist(cur, locked, set(off["asked_prefs"]))
    try:
        payload = ai_payload(text, history, hw, wl, cur, off, goal, edition, selected)
        reply = ai_http(provider, base_url, model, key, payload, timeout, urlopen)
        res = parse_ai_reply(reply, wl)
    except Exception as e:
        reason = "timed out" if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e) else \
                 "HTTP %s" % e.code if isinstance(e, urllib.error.HTTPError) else _clean_str(e, 120) or e.__class__.__name__
        return dict(off, fallback_reason=reason)
    out = dict(off); out.update({k: v for k, v in res.items() if v})
    out["source"] = "ai"; out["fixes"] = res["fixes"]
    if not res.get("bottleneck"): out["bottleneck"] = off["bottleneck"]
    return out

PRIVACY_NOTE = ("AI mode is optional and off by default. When you click Ask, SkyTune sends ONLY: the problems you picked, what you typed (and your earlier "
                "messages in this chat), a hardware summary (graphics card, video memory, processor, cores, memory, screen size), "
                "your goal, the simulator version, and the current values of the graphics settings SkyTune can change. "
                "No file paths, user names, add-on lists or other files are sent. It goes directly from your PC to the provider "
                "you chose, using your own key – SkyTune has no server. Suggestions are checked against the allowed settings and "
                "ranges, and nothing is changed until you click “Optimise my sim”.")

# v1.3.1: the in-app "How to use AI" guide (also in README). (heading, text) pairs; no prices, no download links.
AI_GUIDE_TITLE = "How to use AI (optional)"
AI_GUIDE = [
    ("You don't need it", "SkyTune works fully offline without any key. The built-in advice is free and needs no account. "
                          "AI is an optional extra opinion – leave it off if you like."),
    ("1 · Get an API key", "Create an API key with an OpenAI-compatible provider – for example on the API keys page of the "
                           "OpenAI platform (platform.openai.com). Anthropic keys work too. Other OpenAI-compatible "
                           "services and AI models running on your own PC also work."),
    ("2 · Paste it into AI settings", "Click “AI settings”, paste the key and click Save. Optional: set the address (base URL) "
                                      "and model if your provider gives you different ones. Leave them empty for the defaults."),
    ("3 · Ask", "Tick “Also ask an AI (your own key)”, pick your problems and/or describe what's wrong, then click Ask. "
                "If the AI is slow or fails, SkyTune shows its own offline answer instead."),
    ("What it costs", "SkyTune is free and never charges you. Using an API key may cost money: your provider bills you "
                      "directly for what you use, at their prices. Check your provider's pricing and limits."),
    ("What is sent", "Only the problems you picked and what you typed, a hardware summary (graphics card, video memory, "
                     "processor, memory, screen size) and the current values of the graphics settings SkyTune can change. "
                     "No personal files, file paths, user names or add-on lists. It goes straight from your PC to your "
                     "provider – SkyTune has no server."),
    ("Your key stays on this PC", "The key is saved only on this computer (encrypted for your Windows account where Windows "
                                  "supports it). It is never shared or included in SkyTune."),
    ("Remove the key", "Open “AI settings” and click “Remove key”. Untick “Also ask an AI” to stay fully offline."),
]

def ai_guide_text():
    return AI_GUIDE_TITLE + "\n\n" + "\n\n".join("%s\n%s" % (h, t) for h, t in AI_GUIDE)

UI_FONTS = ("Segoe UI", "Segoe UI Variable Text", "Inter", "Noto Sans", "DejaVu Sans")
TYPE = {"h1": 18, "title": 12, "body": 10, "hint": 9, "small": 8}     # v1.3.2 type scale (points): header/title/body/hint
SPACE = 4                                                              # v1.3.2 spacing grid (px at 96 DPI)

def pick_font(root, candidates=UI_FONTS):
    """First installed UI font. v1.3.2: asks Tk about each candidate instead of listing every installed font
    (tkfont.families() was the single slowest step of start-up, ~0.45 s)."""
    import tkinter.font as tkfont
    for f in candidates:
        try:
            if tkfont.Font(root=root, family=f, size=10).actual("family").lower() == f.lower(): return f
        except Exception: pass
    return "TkDefaultFont"

def _mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#%02x%02x%02x" % tuple(int(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t + 0.5) for i in (0, 2, 4))

def _seg_dist(px_, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px_ - ax) * dx + (py - ay) * dy) / float(dx * dx + dy * dy or 1)))
    return ((px_ - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5

def icon_shape(kind, u, v):
    """Coverage test in unit coordinates (0..1) for the small drawn icons."""
    import math
    d = ((u - 0.5) ** 2 + (v - 0.5) ** 2) ** 0.5
    if kind == "check":
        return min(_seg_dist(u, v, 0.16, 0.52, 0.40, 0.76), _seg_dist(u, v, 0.40, 0.76, 0.86, 0.26)) <= 0.09
    if kind == "dot": return d <= 0.45
    if kind == "ring": return 0.33 <= d <= 0.45
    if kind == "radio": return d <= 0.20 or 0.33 <= d <= 0.45
    if kind == "bar":          # u is in units of the image height here, so the bar keeps its shape at any width
        return u <= 0.25 and (0.125 <= v <= 0.875 or ((u - 0.125) ** 2 + min(abs(v - 0.125), abs(v - 0.875)) ** 2) ** 0.5 <= 0.125)
    if kind.startswith("spin"):
        a0 = int(kind[4:]) * 30
        if not 0.30 <= d <= 0.45: return False
        ang = (math.degrees(math.atan2(0.5 - v, u - 0.5)) - a0) % 360
        return ang <= 270
    return False

def icon_pixels(kind, w, h, fg, bg, ss=3):
    """Anti-aliased icon as rows of colours (blended onto bg) – drawn in code, no image files."""
    rows = []
    for j in range(h):
        row = []
        for i in range(w):
            hit = sum(1 for a in range(ss) for b in range(ss)
                      if icon_shape(kind, (i + (a + 0.5) / ss) / w * (w / float(h) if kind == "bar" else 1),
                                    (j + (b + 0.5) / ss) / h))
            row.append(_mix(bg, fg, hit / float(ss * ss)))
        rows.append(row)
    return rows

def corner_pixels(r, outside, border, fill, ss=3):
    """Top-left rounded-card corner, r x r: outside colour, 1 px border arc, card fill."""
    rows = []
    for j in range(r):
        row = []
        for i in range(r):
            acc = [0.0, 0.0, 0.0]
            for a in range(ss):
                for b in range(ss):
                    x, y = i + (a + 0.5) / ss, j + (b + 0.5) / ss
                    d = ((x - r) ** 2 + (y - r) ** 2) ** 0.5
                    c = outside if d > r else border if d > r - 1.15 else fill
                    for k in range(3): acc[k] += int(c[1 + 2 * k:3 + 2 * k], 16)
            row.append("#%02x%02x%02x" % tuple(int(x / (ss * ss) + 0.5) for x in acc))
        rows.append(row)
    return rows

# ---------------------------------------------------------------- GUI
THEME = {
    "bg": "#0b1220", "header": "#0e1729", "card": "#141e30", "card2": "#1b273c", "border": "#26354f",
    "text": "#e8eef7", "muted": "#97a8c0", "accent": "#38bdf8", "accent_hi": "#7dd3fc", "accent_dk": "#0284c7",
    "danger": "#f87171", "danger_dk": "#b91c1c", "warn": "#fbbf24", "ok": "#34d399", "field": "#0f1828",
    # v1.3.2: interaction states and selection tint – every text/background pair is at least 4.5:1 (WCAG AA)
    "hover": "#24344f", "pressed": "#152036", "line": "#33476a", "primary": "#0369a1", "primary_hi": "#0277b6",
    "primary_pr": "#075985", "sel": "#0c3a5c", "sel_hi": "#0f4a73", "sel_text": "#e0f2fe", "focus": "#7dd3fc",
    "danger_bg": "#3a1820", "danger_hover": "#4a1d28", "danger_pr": "#5b2330", "danger_text": "#fca5a5",
}
# In-game tab card grouping (by key path)
INGAME_CARDS = [
    ("Display & upscaling", lambda p: p.startswith("Video/")),
    ("Traffic & population", lambda p: "/Traffic/" in p or "/Characters/" in p),
    ("Scenery & detail", lambda p: any(k in p for k in ("LoD", "PreCaching", "Texture/", "Buildings", "Procedural",
                                                          "GlassCockpits"))),
    ("Lighting, clouds & effects", lambda p: True),
]

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

DEMO_HW = {"gpu": "NVIDIA GeForce RTX 3070 Ti", "vram_gb": 8.0, "vram_src": "registry qwMemorySize",
           "cpu": "AMD Ryzen 7 5800X 8-Core Processor", "cores": 8, "threads": 16, "ram_gb": 32,
           "width": 1920, "height": 1080, "errors": []}

def elide_middle(text, max_px, measure):
    """Shorten text with a middle ellipsis so measure(text) <= max_px (keeps drive and file name visible)."""
    if measure(text) <= max_px or len(text) < 8: return text
    lo, hi, best = 1, len(text) - 1, text[:1] + "…"
    while lo <= hi:
        keep = (lo + hi) // 2
        cand = text[:(keep + 1) // 2] + "…" + text[len(text) - keep // 2:]
        if measure(cand) <= max_px: best, lo = cand, keep + 1
        else: hi = keep - 1
    return best

def run_gui(demo_hw=False, start_tab=0, auto_open_detect=False, start_view="simple", show_welcome=False, start_preset=None, open_clean=False, quiet_detect=False, goal=None, geometry=None, layout_check=None):
    import json, threading
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import tkinter.font as tkfont
    T = dict(THEME)

    make_dpi_aware()
    if EXTRA is not None:
        EXTRA.apply_theme(T)
    root = tk.Tk(); root.title(EXTRA.title(VERSION) if EXTRA is not None else "SkyTune " + VERSION)
    def _report_callback(_et, ev, _tb):
        try:
            if not root.winfo_exists():
                return
            messagebox.showerror(SHORT_NAME, plain_error(ev), parent=root)
        except Exception:
            pass
    root.report_callback_exception = _report_callback
    try:
        dpi = root.winfo_fpixels("1i"); root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception: dpi = 96
    DPIF = max(1.0, dpi / 96.0); sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    ww, wh = min(int(1300 * DPIF), int(sw * 0.96)), min(int(1000 * DPIF), int(sh * 0.90))
    root.geometry("%dx%d+%d+%d" % (ww, wh, max(0, (sw - ww) // 2), max(0, (sh - wh) // 3)))
    root.minsize(min(640, ww), min(460, wh)); root.resizable(True, True)
    if geometry: root.geometry(geometry)
    if (sw <= 1366 or sh <= 820) and not geometry:
        try: root.state("zoomed")
        except Exception: pass
    root.configure(bg=T["bg"])
    try:
        if os.name == "nt": root.iconbitmap(default=resource_path("app.ico"))    # v1.3.2: every dialog gets the app icon
        else: root.iconphoto(True, tk.PhotoImage(file=resource_path(os.path.join("assets", "app.png"))))
    except Exception: pass

    F = pick_font(root)
    for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        try: tkfont.nametofont(n).configure(family=F, size=TYPE["body"])
        except Exception: pass
    FONT, FONT_B, FONT_S = (F, TYPE["body"]), (F, TYPE["body"], "bold"), (F, TYPE["hint"])
    FONT_T, FONT_H1 = (F, TYPE["title"], "bold"), (F, TYPE["h1"], "bold")
    def px(n):
        """v1.3.2: spacing in grid units that follows the screen DPI like the text does."""
        return int(round(n * DPIF))
    ICONS = {}
    def icon(kind, w, h, fg, bg):
        """Crisp anti-aliased icon drawn in code (check, radio, ring, bar, spinner frames) – cached, no files."""
        key = (kind, w, h, fg, bg)
        if key not in ICONS:
            im = tk.PhotoImage(master=root, width=w, height=h)
            if kind != "blank": im.put(" ".join("{%s}" % " ".join(r_) for r_ in icon_pixels(kind, w, h, fg, bg)))
            ICONS[key] = im
        return ICONS[key]
    root._icons = ICONS

    s = ttk.Style(root); s.theme_use("clam")
    s.configure(".", background=T["bg"], foreground=T["text"], font=FONT, bordercolor=T["border"],
                darkcolor=T["card"], lightcolor=T["card"], troughcolor=T["field"], focuscolor=T["focus"],
                selectbackground=T["accent_dk"], selectforeground="#ffffff", fieldbackground=T["field"])
    for name, bg in (("TFrame", T["bg"]), ("Card.TFrame", T["card"]), ("Header.TFrame", T["header"])):
        s.configure(name, background=bg)
    s.configure("TLabel", background=T["bg"]); s.configure("Card.TLabel", background=T["card"])
    s.configure("Muted.Card.TLabel", background=T["card"], foreground=T["muted"], font=FONT_S)
    s.configure("CardTitle.TLabel", background=T["card"], foreground=T["text"], font=FONT_T)
    s.configure("Value.Card.TLabel", background=T["card"], foreground=T["accent_hi"], font=FONT_B)
    s.configure("Total.Card.TLabel", background=T["card"], foreground=T["accent_hi"], font=FONT_T)
    s.configure("Ok.Card.TLabel", background=T["card"], foreground=T["ok"], font=FONT_S)
    s.configure("H1.TLabel", background=T["header"], foreground=T["text"], font=FONT_H1)
    s.configure("Sub.TLabel", background=T["header"], foreground=T["muted"], font=FONT_S)
    s.configure("Ver.TLabel", background=T["sel"], foreground=T["sel_text"], font=(F, TYPE["hint"], "bold"), padding=(px(8), px(2)))
    s.configure("Path.TLabel", background=T["header"], foreground=T["accent_hi"], font=FONT_S)
    s.configure("Status.TLabel", background=T["header"], foreground=T["text"], font=FONT_S, padding=(px(8), px(6)))
    s.configure("StatusNote.TLabel", background=T["header"], foreground=T["muted"], font=FONT_S, padding=(px(12), px(6)))

    def btn(style, bg, hover, pressed, fg="#ffffff", border=None, hborder=None, font=None, pad=(16, 8)):
        """v1.3.2: every button has distinct hover, pressed, focus and disabled looks."""
        s.configure(style, background=bg, foreground=fg, borderwidth=1, bordercolor=border or bg, focusthickness=0,
                    relief="flat", padding=(px(pad[0]), px(pad[1])), font=font or FONT_B, lightcolor=bg, darkcolor=bg)
        st_ = [("disabled", T["card2"]), ("pressed", pressed), ("active", hover)]
        s.map(style, background=st_, lightcolor=st_, darkcolor=st_, relief=[("pressed", "flat")],
              bordercolor=[("disabled", T["border"]), ("focus", T["focus"]), ("pressed", hborder or pressed), ("active", hborder or hover)],
              foreground=[("disabled", T["muted"])])
    btn("Primary.TButton", T["primary"], T["primary_hi"], T["primary_pr"])
    btn("Secondary.TButton", T["card2"], T["hover"], T["pressed"], fg=T["text"], border=T["line"], hborder="#46608a")
    btn("Danger.TButton", T["danger_bg"], T["danger_hover"], T["danger_pr"], fg=T["danger_text"], border="#5b2330", hborder="#8a3446")
    btn("Preset.TButton", T["card2"], T["sel"], T["pressed"], fg=T["text"], border=T["line"], hborder=T["accent_dk"], pad=(12, 8))
    btn("Big.Primary.TButton", T["primary"], T["primary_hi"], T["primary_pr"], border=T["accent"], hborder=T["accent_hi"],
        font=(F, 13, "bold"), pad=(24, 14))
    btn("Big.Danger.TButton", T["danger_bg"], T["danger_hover"], T["danger_pr"], fg=T["danger_text"], border="#5b2330",
        hborder="#8a3446", font=(F, 11, "bold"), pad=(20, 12))
    btn("Confirm.TButton", "#0f766e", "#115e59", "#134e4a", pad=(14, 8))
    btn("Cancel.TButton", "#334155", "#1e293b", "#0f172a", pad=(14, 8))
    # goal picker: radio-style dot/ring icons drawn in code; chips: tinted when selected with a ✓ (same width either way)
    isz = px(14)
    s.configure("Pick.TRadiobutton", background=T["card2"], foreground=T["text"], font=(F, 11, "bold"), padding=(px(16), px(12)),
                indicatorsize=0, borderwidth=1, relief="flat", compound="left", image=icon("ring", isz, isz, T["muted"], T["card2"]))
    s.layout("Pick.TRadiobutton", [("Radiobutton.padding", {"sticky": "nswe", "children": [("Radiobutton.label", {"sticky": "nswe"})]})])
    s.map("Pick.TRadiobutton", background=[("selected", T["primary"]), ("pressed", T["pressed"]), ("active", T["hover"])],
          foreground=[("selected", "#ffffff")],
          image=[("selected", icon("radio", isz, isz, "#ffffff", T["primary"])), ("active", icon("ring", isz, isz, T["accent_hi"], T["hover"]))])
    s.configure("Big.Card.TLabel", background=T["card"], foreground=T["text"], font=(F, 11))
    # v1.3.1: multi-select problem chips (click to select, click again to unselect)
    csz = px(12)
    s.configure("Chip.TCheckbutton", background=T["card2"], foreground=T["text"], font=FONT_B, padding=(px(12), px(8)),
                indicatorsize=0, borderwidth=1, relief="flat", anchor="center", compound="left", image=icon("blank", csz, csz, "", ""))
    s.layout("Chip.TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [("Checkbutton.label", {"sticky": "nswe"})]})])
    s.map("Chip.TCheckbutton", background=[("selected", "active", T["sel_hi"]), ("selected", T["sel"]), ("pressed", T["pressed"]), ("active", T["hover"])],
          foreground=[("selected", T["sel_text"])],
          image=[("selected", "active", icon("check", csz, csz, T["accent_hi"], T["sel_hi"])), ("selected", icon("check", csz, csz, T["accent_hi"], T["sel"]))])

    s.configure("TNotebook", background=T["bg"], borderwidth=0, tabmargins=(0, px(6), 0, 0))
    s.configure("TNotebook.Tab", background=T["bg"], foreground=T["muted"], padding=(px(18), px(8)), font=FONT_B, borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", T["card"]), ("active", T["card2"])], foreground=[("selected", T["accent_hi"]), ("active", T["text"])],
          lightcolor=[("selected", T["card"])], bordercolor=[("selected", T["border"])])
    s.configure("TCombobox", fieldbackground=T["field"], background=T["card2"], foreground=T["text"],
                arrowcolor=T["accent"], bordercolor=T["line"], padding=px(4), selectbackground=T["field"], lightcolor=T["field"], darkcolor=T["field"])
    s.map("TCombobox", fieldbackground=[("disabled", T["card2"]), ("readonly", T["field"])],
          foreground=[("disabled", T["muted"]), ("readonly", T["text"])], arrowcolor=[("disabled", T["border"]), ("active", T["accent_hi"])],
          bordercolor=[("focus", T["accent"]), ("active", "#46608a")], background=[("active", T["hover"])], selectbackground=[("readonly", T["field"])])
    root.option_add("*TCombobox*Listbox.background", T["field"]); root.option_add("*TCombobox*Listbox.foreground", T["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", T["primary"]); root.option_add("*TCombobox*Listbox.font", FONT)
    s.configure("Horizontal.TScale", background=T["accent"], troughcolor=T["field"], bordercolor=T["line"],
                lightcolor=T["accent"], darkcolor=T["accent"], sliderlength=px(16), sliderthickness=px(14), gripcount=0)
    s.map("Horizontal.TScale", background=[("active", T["accent_hi"])], lightcolor=[("active", T["accent_hi"])],
          darkcolor=[("active", T["accent_hi"])])
    s.configure("TEntry", fieldbackground=T["field"], foreground=T["text"], insertcolor=T["text"], padding=px(4),
                bordercolor=T["line"], lightcolor=T["field"], darkcolor=T["field"])
    s.map("TEntry", bordercolor=[("focus", T["accent"]), ("hover", "#46608a")], lightcolor=[("focus", T["accent"])])
    s.configure("Card.TCheckbutton", background=T["card"], foreground=T["text"], indicatorbackground=T["field"],
                indicatorforeground="#ffffff", indicatormargin=(0, 0, px(6), 0), bordercolor=T["line"])
    s.map("Card.TCheckbutton", background=[("active", T["card"])], foreground=[("disabled", T["muted"]), ("active", T["accent_hi"])],
          indicatorbackground=[("selected", "active", T["primary_hi"]), ("selected", T["primary"]), ("active", T["hover"])])
    for sb_ in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        s.configure(sb_, background=T["card2"], troughcolor=T["bg"], arrowcolor=T["muted"], gripcount=0,
                    bordercolor=T["bg"], lightcolor=T["card2"], darkcolor=T["card2"])
        s.map(sb_, background=[("pressed", T["line"]), ("active", T["hover"])], arrowcolor=[("active", T["text"])],
              lightcolor=[("active", T["hover"])], darkcolor=[("active", T["hover"])])

    class Tip:
        def __init__(self, w, text):
            self.w, self.text, self.top, self.job = w, text, None, None
            w._skytip = self
            w.bind("<Enter>", self.sched, add="+"); w.bind("<Leave>", self.hide, add="+")
        def sched(self, _=None): self.job = self.w.after(350, self.show)
        def show(self):
            if not self.text: return
            self.top = tk.Toplevel(self.w); self.top.wm_overrideredirect(True)
            self.top.geometry("+%d+%d" % (self.w.winfo_rootx() + 16, self.w.winfo_rooty() + self.w.winfo_height() + 6))
            f = tk.Frame(self.top, bg=T["accent_dk"], padx=1, pady=1); f.pack()
            tk.Label(f, text=self.text, bg="#0f1a2c", fg=T["text"], font=FONT_S, wraplength=int(380 * DPIF), justify="left",
                     padx=10, pady=8).pack()
        def hide(self, _=None):
            if self.job: self.w.after_cancel(self.job); self.job = None
            if self.top: self.top.destroy(); self.top = None

    WRAPS = []      # (label, container, margin): wraplength follows the container width (window size + DPI)
    def autowrap(lbl, container, margin=8):
        WRAPS.append((lbl, container, margin)); return lbl
    def rewrap():
        # In the two-column simple view the canvas window is max(content, canvas) wide, so a container can stay
        # wider than the visible area once text wrapped wide (e.g. just before the scrollbar appeared). Cap the
        # left column's text by what really fits: canvas width minus (right column + gap + padding).
        capL = None
        try:
            if col_mode.get("stacked") is False and _scv.winfo_width() > 50:
                capL = (scol_l.winfo_width(), _scv.winfo_width() - (simple.winfo_width() - scol_l.winfo_width()), str(scol_l))
        except (NameError, tk.TclError): capL = None
        for lbl, cont, mg in list(WRAPS):
            try:
                w = cont.winfo_width()
                if capL and str(cont).startswith(capL[2]) and w > 50:
                    w = min(w, capL[1] - (capL[0] - w))
                if w > 50: lbl.configure(wraplength=max(int(160 * DPIF), w - int(mg * DPIF)))
            except tk.TclError: WRAPS.remove((lbl, cont, mg))
    def _bg_of(w):
        try: return str(w.cget("bg"))
        except tk.TclError: pass
        try: return s.lookup(str(w.cget("style")) or w.winfo_class(), "background") or T["bg"]
        except tk.TclError: return T["bg"]
    CORNERS = {}
    def round_corners(outer, parent, fill=None):
        """v1.3.2: soft rounded corners – four tiny anti-aliased images over the card's square corners."""
        try:
            out_bg, r = _bg_of(parent), px(6)
            key = (out_bg, fill or T["card"], r)
            if key not in CORNERS:
                rows, ims = corner_pixels(r, out_bg, T["border"], fill or T["card"]), []
                for fx, fy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    rr = rows[::-1] if fy else rows
                    rr = [row[::-1] for row in rr] if fx else rr
                    im = tk.PhotoImage(master=root, width=r, height=r); im.put(" ".join("{%s}" % " ".join(row) for row in rr)); ims.append(im)
                CORNERS[key] = ims
            for im, (fx, fy) in zip(CORNERS[key], ((0, 0), (1, 0), (0, 1), (1, 1))):
                tk.Label(outer, image=im, bd=0, highlightthickness=0, padx=0, pady=0, bg=T["border"]).place(
                    relx=fx, rely=fy, x=1 - r if fx else -1, y=1 - r if fy else -1)    # place() measures inside the 1 px padding
        except Exception: pass
    def card(parent, title=None, subtitle=None):
        outer = tk.Frame(parent, bg=T["border"], padx=1, pady=1)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=(px(16), px(12))); inner.pack(fill="both", expand=True)
        round_corners(outer, parent)
        if title:
            ttk.Label(inner, text=title, style="CardTitle.TLabel", compound="left",
                      image=icon("bar", px(12), px(16), T["accent"], T["card"])).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, px(2)))
            if subtitle:
                autowrap(ttk.Label(inner, text=subtitle, style="Muted.Card.TLabel", wraplength=620, justify="left"), inner, 36).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        return outer, inner

    st = {"path": None, "cfg": None, "edition": "unknown", "vars": {}, "cleaner_built": False, "held": set(), "drift": []}
    root._st = st          # lets the GUI tests look at the live state
    res_opt = tk.BooleanVar(value=False)
    status = tk.StringVar(value="Ready.")
    path_var = tk.StringVar(value="No UserCfg.opt loaded")

    # ---- header
    hdr = ttk.Frame(root, style="Header.TFrame", padding=(20, 14)); hdr.pack(fill="x")
    tk.Frame(root, bg=T["accent"], height=max(2, px(2))).pack(fill="x")
    left = ttk.Frame(hdr, style="Header.TFrame"); left.pack(side="left")
    try:
        logo = tk.PhotoImage(file=resource_path(os.path.join("assets", "app.png"))).subsample(max(2, int(round(6 / DPIF))))
        tk.Label(left, image=logo, bg=T["header"]).pack(side="left", padx=(0, 12)); root._logo = logo
    except Exception: pass
    tbox = ttk.Frame(left, style="Header.TFrame"); tbox.pack(side="left")
    trow = ttk.Frame(tbox, style="Header.TFrame"); trow.pack(anchor="w")
    ttk.Label(trow, text=APP_NAME, style="H1.TLabel").pack(side="left")
    ttk.Label(trow, text="v" + VERSION, style="Ver.TLabel").pack(side="left", padx=10)
    if EXTRA is not None:
        EXTRA.add_badge(trow, tk, F)
    ttk.Label(tbox, text="Better-looking, smoother flights – one click, with automatic backups",
              style="Sub.TLabel").pack(anchor="w")
    right = ttk.Frame(hdr, style="Header.TFrame"); right.pack(side="right")
    br = ttk.Frame(right, style="Header.TFrame"); br.pack(anchor="e")
    sim_pill = tk.Label(br, text="  ●  Checking sim…  ", bg=T["card2"], fg=T["muted"], font=FONT_B, padx=8, pady=6)
    sim_pill.pack(side="left", padx=(0, 10))
    view_btn = ttk.Button(br, text="Advanced settings ▸", style="Secondary.TButton", command=lambda: toggle_view())
    view_btn.pack(side="left", padx=4)
    find_btn = ttk.Button(br, text="Find file", style="Secondary.TButton", command=lambda: autodetect_async()); find_btn.pack(side="left", padx=4)
    ttk.Button(br, text="Browse…", style="Secondary.TButton", command=lambda: browse()).pack(side="left")
    path_lbl = ttk.Label(right, text="", style="Path.TLabel"); path_lbl.pack(anchor="e", pady=(6, 0))
    path_tip = Tip(path_lbl, "")
    _pfont = tkfont.Font(font=FONT_S)
    hdr_mode = {"narrow": None}
    def relayout_header(_=None):
        hw_ = hdr.winfo_width()
        if hw_ < 50: return
        need = left.winfo_reqwidth() + br.winfo_reqwidth() + int(60 * DPIF)
        narrow = hw_ < need
        if narrow != hdr_mode["narrow"]:
            hdr_mode["narrow"] = narrow
            right.pack_forget(); left.pack_forget()
            if narrow:
                left.pack(side="top", anchor="w"); right.pack(side="top", anchor="w", fill="x", pady=(10, 0))
                br.pack_configure(anchor="w"); path_lbl.pack_configure(anchor="w")
            else:
                left.pack(side="left"); right.pack(side="right"); br.pack_configure(anchor="e"); path_lbl.pack_configure(anchor="e")
        avail = (hw_ - int(40 * DPIF)) if narrow else max(int(200 * DPIF), hw_ - left.winfo_reqwidth() - int(70 * DPIF))
        full = path_var.get(); key = (full, avail)
        if hdr_mode.get("elided", (None,))[0] != key:
            hdr_mode["elided"] = (key, elide_middle(full, avail, _pfont.measure))
            path_lbl.configure(text=hdr_mode["elided"][1])
        path_tip.text = full
    path_var.trace_add("write", lambda *_: relayout_header())

    # ---- status bar (pack before body so it stays at bottom)
    sbar = ttk.Frame(root, style="Header.TFrame"); sbar.pack(side="bottom", fill="x")
    tk.Frame(root, bg=T["border"], height=1).pack(side="bottom", fill="x")          # v1.3.2: hairline above the status bar
    dot = tk.Label(sbar, text="●", bg=T["header"], fg=T["ok"], font=FONT_S); dot.pack(side="left", padx=(px(14), 0))
    spin = tk.Label(sbar, bg=T["header"], bd=0, padx=0, pady=0)            # shown instead of the dot while busy
    status_lbl = ttk.Label(sbar, textvariable=status, style="Status.TLabel"); status_lbl.pack(side="left")
    ttk.Label(sbar, text="MSFS 2020/2024 · automatic backups in UserCfg_backups", style="StatusNote.TLabel").pack(side="right")
    def set_status(msg, kind="ok"):
        status.set(msg); dot.configure(fg={"ok": T["ok"], "warn": T["warn"], "err": T["danger"], "info": T["accent"]}[kind])
    BUSY = {"n": 0, "job": None, "k": 0}
    def _spin_tick():
        if not BUSY["n"]: BUSY["job"] = None; return
        z = px(12); spin.configure(image=icon("spin%d" % (BUSY["k"] % 12), z, z, T["accent"], T["header"]))
        BUSY["k"] += 1; BUSY["job"] = root.after(80, _spin_tick)
    def busy(on):
        """v1.3.2: spinner in the status bar while background work runs (animates only while busy – no idle cost)."""
        BUSY["n"] = max(0, BUSY["n"] + (1 if on else -1))
        try:
            if BUSY["n"] and not BUSY.get("shown"):
                BUSY["shown"] = True; dot.pack_forget(); spin.pack(side="left", padx=(px(14), 0), before=status_lbl)
                if not BUSY["job"]: _spin_tick()
            elif not BUSY["n"] and BUSY.get("shown"):
                BUSY["shown"] = False; spin.pack_forget(); dot.pack(side="left", padx=(px(14), 0), before=status_lbl)
        except tk.TclError: pass
    st["busy"] = BUSY                                  # (the GUI tests look at this)
    def run_bg(work, done=None, msg=None, fail=None):
        """v1.3.2: run slow work (file scans, sizes, deletes, hardware checks) on a worker thread; `done(result)` runs
        back on the UI thread, so the window never freezes."""
        prev = (status.get(), dot.cget("fg"))
        if msg: set_status(msg, "info")
        busy(True)
        def w():
            try: res, err = work(), None
            except Exception as e: res, err = None, e
            def fin():
                busy(False)
                if msg and status.get() == msg: status.set(prev[0]); dot.configure(fg=prev[1])    # put the old line back
                if err is not None:
                    if fail: fail(err)
                    else: set_status("Something went wrong: %s" % (str(err)[:160] or err.__class__.__name__), "err")
                elif done: done(res)
            try: root.after(0, fin)
            except (RuntimeError, tk.TclError): pass          # window already closed
        threading.Thread(target=w, daemon=True).start()

    # ---- banner
    ban = tk.Frame(root, bg="#2a2110", highlightthickness=1, highlightbackground="#5c4512")
    ban.pack(fill="x", padx=20, pady=(14, 0)); ban.pack_forget()
    tk.Label(ban, text="⚠", bg="#2a2110", fg=T["warn"], font=(F, 14)).pack(side="left", padx=(12, 8), pady=6)
    autowrap(tk.Label(ban, bg="#2a2110", fg="#f5deb3", font=FONT_S, justify="left", wraplength=1000, anchor="w",
                      text=ADV_BANNER_TEXT), ban, 60).pack(side="left", fill="x", pady=6)

    # ---- v1.3.1 (b): friendly "sim is running" banner with Check again; write buttons are locked meanwhile
    simban = tk.Frame(root, bg="#3a1820", highlightthickness=1, highlightbackground="#5b2330")
    tk.Label(simban, text="✋", bg="#3a1820", fg=T["danger"], font=(F, 14)).pack(side="left", padx=(12, 8), pady=8)
    simban_btn = ttk.Button(simban, text="Check again", style="Secondary.TButton", command=lambda: check_sim_now())
    simban_btn.pack(side="right", padx=10, pady=6)
    autowrap(tk.Label(simban, bg="#3a1820", fg="#f7d4da", font=FONT_B, justify="left", wraplength=900, anchor="w",
                      text=SIM_BANNER_TEXT), simban, 200).pack(side="left", fill="x", pady=8)
    st["sim_locks"] = []
    def sim_lock(w, tip=None):
        """Register a button that writes files: disabled (with an explanatory tooltip) while the sim runs."""
        t_ = tip or getattr(w, "_skytip", None) or Tip(w, ""); st["sim_locks"].append((w, t_, t_.text)); apply_sim_lock(); return w
    def apply_sim_lock():
        on = bool(st.get("sim"))
        for w, t_, normal in list(st["sim_locks"]):
            try:
                if not w.winfo_exists(): st["sim_locks"].remove((w, t_, normal)); continue
                w.state(["disabled"] if on else ["!disabled"]); t_.text = SIM_LOCK_TIP if on else normal
            except tk.TclError: pass
    def check_sim_now():
        set_status("Checking whether the sim is still running…", "info")
        def work():
            r = True if "--sim-running" in sys.argv else sim_running()
            root.after(0, lambda: (show_sim(r), set_status("The sim is still running – close it, then click “Check again”.", "err")
                                   if r else set_status("The sim is closed – you're good to go.")))
        threading.Thread(target=work, daemon=True).start()

    simple_outer = ttk.Frame(root)
    _scv = tk.Canvas(simple_outer, bg=T["bg"], highlightthickness=0)
    _ssb = ttk.Scrollbar(simple_outer, command=_scv.yview); _shb = ttk.Scrollbar(simple_outer, orient="horizontal", command=_scv.xview)
    simple = ttk.Frame(_scv, padding=(20, 14)); _sw = _scv.create_window((0, 0), window=simple, anchor="nw")
    def _sfit(_=None):
        cw, ch = _scv.winfo_width(), _scv.winfo_height()
        if cw > 50: relayout_cols(cw)
        rw, rh = simple.winfo_reqwidth(), simple.winfo_reqheight()
        _scv.itemconfigure(_sw, width=max(rw, cw), height=max(rh, ch)); _scv.configure(scrollregion=(0, 0, max(rw, cw), max(rh, ch)))
        if rh > ch: _ssb.pack(side="right", fill="y", before=_scv)
        else: _ssb.pack_forget()
        if rw > cw: _shb.pack(side="bottom", fill="x", before=_scv)
        else: _shb.pack_forget()
    simple.bind("<Configure>", _sfit); _scv.bind("<Configure>", _sfit)
    _scv.configure(yscrollcommand=lambda a, b: (_ssb.set(a, b), root.after_idle(update_steps)), xscrollcommand=_shb.set)
    stepbar = tk.Frame(simple_outer, bg=T["bg"]); stepbar.pack(side="top", fill="x", padx=20, pady=(8, 0))
    step_lbls = []
    for n_, nm_ in enumerate(STEP_NAMES):
        if n_: tk.Label(stepbar, text="›", bg=T["bg"], fg=T["border"], font=FONT_B).pack(side="left", padx=6)
        l_ = tk.Label(stepbar, text="", bg=T["bg"], fg=T["muted"], font=FONT_B, cursor="hand2", padx=8, pady=3)
        l_.pack(side="left"); l_.bind("<Button-1>", lambda e, k=n_: goto_step(k)); step_lbls.append(l_)
        l_.bind("<Enter>", lambda e, w=l_: w.configure(fg=T["accent_hi"]), add="+"); l_.bind("<Leave>", lambda e: update_steps(), add="+")
    tk.Frame(simple_outer, bg=T["border"], height=1).pack(side="top", fill="x", padx=20, pady=(6, 0))
    _scv.pack(side="left", fill="both", expand=True)
    def step_cards(): return (ao2, go2, so)
    def goto_step(k):
        c_ = step_cards()[k]; h_ = max(simple.winfo_height(), 1)
        _scv.yview_moveto(max(0.0, (c_.winfo_rooty() - simple.winfo_rooty() - 8) / h_)); update_steps()
    def current_step():
        done = [bool(st.get("hw")), bool(st.get("step2") or st.get("optimised")), bool(st.get("optimised"))]
        if col_mode.get("stacked") and _scv.yview() != (0.0, 1.0):
            top = _scv.winfo_rooty(); cur = 0
            for k, c_ in enumerate(step_cards()):
                if c_.winfo_rooty() - top <= _scv.winfo_height() * 0.35: cur = k
            return cur, done
        return next((k for k, d_ in enumerate(done) if not d_), 2), done
    def update_steps():
        try: cur, done = current_step()
        except (tk.TclError, NameError): return
        for k, l_ in enumerate(step_lbls):
            l_.configure(text=("✓ " if done[k] else "%d  " % (k + 1)) + STEP_NAMES[k],
                         fg=(T["sel_text"] if k == cur else (T["ok"] if done[k] else T["muted"])),
                         bg=(T["sel"] if k == cur else T["bg"]))
        st["step_now"] = cur
    def _swheel(e):
        if view["adv"] or _scv.yview() == (0.0, 1.0): return
        _scv.yview_scroll(-1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1, "units")
    for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"): root.bind(ev, _swheel, add="+")
    body = ttk.Frame(root, padding=(20, 12))

    # ================= simple view =================
    
    scol_l = ttk.Frame(simple); scol_l.pack(side="left", fill="both", expand=True)
    scol_r = ttk.Frame(simple, width=430); scol_r.pack(side="right", fill="both", padx=(16, 0))
    col_mode = {"stacked": None, "need": 0}
    def relayout_cols(width):
        if col_mode["stacked"]: stacked = width < col_mode["need"]
        else:
            req = simple.winfo_reqwidth()
            now = time.monotonic()
            if req > width + 2:
                # wrapped labels may still carry the wraplength of a wider window (see rewrap): give re-wrapping
                # up to 1 s to settle before falling back to one column, so the view isn't wrongly stacked
                t0 = col_mode.setdefault("t0", now)
                if now - t0 < 1.0:
                    if not col_mode.get("pending"):
                        col_mode["pending"] = True
                        root.after(40, lambda: (col_mode.update(pending=False), rewrap(), _sfit()))
                    return
            col_mode.pop("t0", None)
            stacked = req > width + 2
            if stacked: col_mode["need"] = req
        if stacked == col_mode["stacked"]: return
        col_mode["stacked"] = stacked
        scol_l.pack_forget(); scol_r.pack_forget()
        if stacked:
            scol_l.pack(side="top", fill="x", expand=False); scol_r.pack(side="top", fill="x", pady=(14, 0))
        else:
            # right column first: it keeps its natural width and the left column (whose text wraps) takes the rest
            scol_r.pack(side="right", fill="both", padx=(16, 0)); scol_l.pack(side="left", fill="both", expand=True)
        root.after_idle(lambda: (rewrap(), _sfit()))
    # ---- v1.3.0 simple view: 1 Check my PC · 2 What matters most? (+ Anything bothering you?) · 3 Optimise my sim
    PREFS = load_prefs()
    def remember(**kw):
        PREFS.update(kw); save_prefs(PREFS)
    def link(parent, text, cmd, tip=None):
        l = tk.Label(parent, text=text, bg=T["card"], fg=T["accent"], font=(F, TYPE["hint"], "underline"), cursor="hand2", takefocus=1)
        l.bind("<Button-1>", lambda e: cmd()); l.bind("<Return>", lambda e: cmd()); l.bind("<space>", lambda e: cmd())
        l.bind("<Enter>", lambda e: l.configure(fg=T["accent_hi"]), add="+"); l.bind("<Leave>", lambda e: l.configure(fg=T["accent"]), add="+")
        l.bind("<FocusIn>", lambda e: l.configure(fg=T["accent_hi"]), add="+"); l.bind("<FocusOut>", lambda e: l.configure(fg=T["accent"]), add="+")
        if tip: Tip(l, tip)
        return l
    def badge(parent, text, kind):
        bg, fg = {"High": ("#0f3d2e", T["ok"]), "Med": ("#3d2f0f", T["warn"]), "Low": (T["card2"], T["muted"]),
                  "cost": (T["card2"], T["text"])}[kind]
        return tk.Label(parent, text=" %s " % text, bg=bg, fg=fg, font=(F, 8, "bold"), padx=3, pady=1)

    welcome_o, welcome_i = card(scol_l, "Start here", "1. Close the simulator.\n"
                                "2. Click Check my PC, then pick what matters most.\n"
                                "3. Read the list, click Optimise, then Yes, write. Cancel leaves the file alone.")
    ttk.Button(welcome_i, text="Got it", style="Secondary.TButton", command=lambda: dismiss_welcome()).grid(row=2, column=0, sticky="w", pady=(4, 0))

    # Step 1
    ao2, ai2 = card(scol_l, "Step 1 · Check my PC", "SkyTune looks at your graphics card, processor, memory and screen.")
    ao2.pack(fill="x", pady=(0, 14))
    s1 = ttk.Frame(ai2, style="Card.TFrame"); s1.grid(row=2, column=0, sticky="w")
    check_btn = ttk.Button(s1, text="Check my PC", style="Big.Primary.TButton", command=lambda: auto_detect(popup=False))
    check_btn.pack(side="left")
    Tip(check_btn, "Reads your hardware (nothing is sent anywhere) and picks the right settings for it and your goal below.")
    s1l = ttk.Frame(s1, style="Card.TFrame"); s1l.pack(side="left", padx=(14, 0))
    link(s1l, "Details", lambda: st.get("hw") and show_reco(st["hw"]), "What SkyTune found and why it chose these settings.").pack(anchor="w")
    link(s1l, "Wrong graphics card?", lambda: pick_gpu_dialog(st.get("hw") or dict(DEMO_HW if demo_hw else {"gpu": "Unknown", "vram_gb": 0, "cpu": "", "cores": 0, "threads": 0, "ram_gb": 0, "width": 0, "height": 0, "errors": []})),
         "Pick your card yourself if the check got it wrong.").pack(anchor="w", pady=(2, 0))
    link(s1l, "Re-check", lambda: auto_detect(popup=False, fresh=True),
         "Check the hardware again (SkyTune remembers the last check on this PC for 30 days).").pack(anchor="w", pady=(2, 0))
    link(s1l, "Save diagnostic…", lambda: save_diagnostic(),
         "Writes a text note you choose, for troubleshooting. It is not uploaded and has no API key.").pack(anchor="w", pady=(2, 0))
    link(s1l, "Help", lambda: open_help(), "Answers for the first run, a missing file, and why a setting was suggested.").pack(anchor="w", pady=(2, 0))
    link(s1l, "Frame Hold…", lambda: open_frame_hold(),
         "Work out terrain and object detail for a target frame rate. It does not change the simulator while it is running.").pack(anchor="w", pady=(2, 0))
    reco_var = tk.StringVar(value="Not checked yet.")
    autowrap(ttk.Label(ai2, textvariable=reco_var, style="Value.Card.TLabel", wraplength=int(300 * DPIF), justify="left"), ai2, 36).grid(row=3, column=0, sticky="w", pady=(10, 0))
    health_var = tk.StringVar(value="PC health: not read yet. This check does not change Windows.")
    autowrap(tk.Label(ai2, textvariable=health_var, bg=T["card"], fg=T["muted"], font=FONT_S, justify="left", anchor="w", wraplength=int(300 * DPIF)), ai2, 36).grid(row=4, column=0, sticky="w", pady=(6, 0))
    mod_var = tk.StringVar(value="")
    mod_lbl = autowrap(tk.Label(ai2, textvariable=mod_var, bg=T["card"], fg=T["warn"], font=FONT_S, justify="left", anchor="w", wraplength=int(300 * DPIF)), ai2, 36)
    def refresh_mods():
        try:
            found = find_graphics_mods(st.get("cfg"), st.get("edition"))
        except Exception:
            found = []
        st["mods"] = found
        text = " ".join(graphics_mod_warnings(found))
        mod_var.set(text)
        if text:
            if not mod_lbl.winfo_ismapped():
                mod_lbl.grid(row=5, column=0, sticky="w", pady=(6, 0))
        elif mod_lbl.winfo_ismapped():
            mod_lbl.grid_remove()
    def refresh_health():
        probes = {}
        try: probes = windows_health_probes(8)
        except Exception: probes = {}
        st["health"] = read_health(st.get("path"), st.get("hw"), probes)
        h = st["health"]
        health_var.set("PC health (read only): %s GB free · %s · VRAM %s · RAM %s · page file %s · HAGS %s · Memory Integrity %s · %s Hz. %s" % (
            h.get("free_gb"), h.get("gpu"), h.get("vram_gb"), h.get("ram_gb"), h.get("pagefile"),
            h.get("hags"), h.get("memory_integrity"), h.get("refresh_hz"),
            " ".join(h.get("tips") or []) or "No Windows setting was changed."))
        try:
            if st.get("edition") == "2024" and 0 < float(h.get("vram_gb")) <= 8:
                health_var.set(health_var.get() + " Suggested start: EasyjetSimPilot - 8 GB VRAM. It stays unselected until you choose it.")
        except (TypeError, ValueError): pass
    cur_preset = {"name": None}

    # Step 2
    go2, gi2 = card(scol_l, "Step 2 · What matters most?")
    go2.pack(fill="x", pady=(0, 14))
    goal_var = tk.StringVar(value=PREFS["goal"]); goal_blurb = tk.StringVar(value=GOAL_BLURB[PREFS["goal"]])
    grow = ttk.Frame(gi2, style="Card.TFrame"); grow.grid(row=2, column=0, sticky="w", pady=(4, 0))
    for n, g in enumerate(GOALS):
        rb = ttk.Radiobutton(grow, text=g, value=g, variable=goal_var, style="Pick.TRadiobutton", width=15,
                             command=lambda: on_goal()); rb.grid(row=0, column=n, padx=(0, 8)); Tip(rb, GOAL_BLURB[g])
    ttk.Label(gi2, textvariable=goal_blurb, style="Muted.Card.TLabel").grid(row=3, column=0, sticky="w", pady=(4, 10))
    def on_goal():
        st["step2"] = True; root.after_idle(update_steps)
        goal_blurb.set(GOAL_BLURB[goal_var.get()]); remember(goal=goal_var.get())
        if st.get("hw"): show_reco(st["hw"], popup=False)
        elif cur_preset["name"]: load_preset(cur_preset["name"])
    tk.Frame(gi2, bg=T["border"], height=1).grid(row=4, column=0, sticky="we", pady=(0, 10)); gi2.columnconfigure(0, weight=1)
    ttk.Label(gi2, text="Anything bothering you?  (optional)", style="Big.Card.TLabel").grid(row=5, column=0, sticky="w")
    qrow = ttk.Frame(gi2, style="Card.TFrame"); qrow.grid(row=6, column=0, sticky="w", pady=(6, 4))
    QTIPS = {"stutter": "Short freezes or hitches.", "low_fps": "The sim feels slow or choppy all the time.",
             "blurry": "Cockpit text or scenery looks soft.", "popin": "Trees, buildings or ground detail appear late.",
             "crash": "The sim closes, freezes for good or won't start.", "after_update": "Something broke after a sim or driver update."}
    chip_vars, chip_btns = {}, {}
    CHIP_HINT = "Pick one or more, then click Ask. Click again to unselect."
    chip_hint = tk.StringVar(value=CHIP_HINT)
    def selected_chips():
        return [pid for _, pid in QUICK_PROBLEMS if chip_vars[pid].get()]
    def upd_chip_hint():
        sel = selected_chips()
        chip_hint.set(("Selected: %s – click Ask (add details below if you like)." % ", ".join(PROBLEMS[p][0] for p in sel)) if sel else CHIP_HINT)
    for n, (lbl, pid) in enumerate(QUICK_PROBLEMS):
        chip_vars[pid] = tk.BooleanVar(value=False)    # never remembered between runs
        qb = ttk.Checkbutton(qrow, text=lbl, variable=chip_vars[pid], style="Chip.TCheckbutton", command=upd_chip_hint)
        qb.grid(row=n // 3, column=n % 3, padx=(0, 6), pady=(0, 6), sticky="we"); chip_btns[pid] = qb
        Tip(qb, QTIPS[pid] + "\nYou can pick several – click again to unselect.")
    for c_ in range(3): qrow.columnconfigure(c_, uniform="chips")
    ttk.Label(qrow, textvariable=chip_hint, style="Muted.Card.TLabel").grid(row=2, column=0, columnspan=3, sticky="w")
    erow = ttk.Frame(gi2, style="Card.TFrame"); erow.grid(row=7, column=0, sticky="we"); erow.columnconfigure(0, weight=1)
    ask_var = tk.StringVar()
    ask_entry = ttk.Entry(erow, textvariable=ask_var, font=FONT); ask_entry.grid(row=0, column=0, sticky="we")
    ask_entry.bind("<Return>", lambda e: ask(ask_var.get()))
    ttk.Button(erow, text="Ask", style="Primary.TButton", command=lambda: ask(ask_var.get())).grid(row=0, column=1, padx=(8, 0))
    Tip(ask_entry, "Describe it in your own words, e.g. “stutters on approach at busy airports”. Typos are fine.")
    airow = ttk.Frame(gi2, style="Card.TFrame"); airow.grid(row=8, column=0, sticky="w", pady=(6, 0))
    ai_on = tk.BooleanVar(value=PREFS["ai_enabled"])
    aicb = ttk.Checkbutton(airow, text="Also ask an AI (your own key)", variable=ai_on, style="Card.TCheckbutton",
                           command=lambda: (remember(ai_enabled=ai_on.get()), ai_on.get() and not load_api_key()[0] and ai_settings()))
    aicb.pack(side="left"); Tip(aicb, "Optional. Off by default – SkyTune works fully offline. " + PRIVACY_NOTE)
    link(airow, "AI settings", lambda: ai_settings(), "Paste your own key, choose the provider – or remove the key.").pack(side="left", padx=(10, 0))
    link(airow, "? How to use AI", lambda: ai_guide(), "A short guide: getting a key, costs, what is sent.").pack(side="left", padx=(10, 0))
    asst = ttk.Frame(gi2, style="Card.TFrame"); asst.grid(row=9, column=0, sticky="we", pady=(8, 0)); asst.columnconfigure(0, weight=1)
    st.update(chat=[], said=[], ctx={}, diag=None, session=None, fix_vars={}, staged=None, feedback=False, last_sel=[])

    def ask(text, new=False, ctx_update=None):
        text = (text or "").strip(); sel = selected_chips()
        if not ctx_update and sel != st.get("last_sel"): new = True     # a different set of problems = a fresh question
        if new: st["chat"], st["said"], st["ctx"], st["session"], st["feedback"] = [], [], {}, None, False
        if ctx_update: st["ctx"].update(ctx_update)
        if not text and not ctx_update and not sel:
            set_status("Pick one or more problems above, or type what's bothering you.", "warn"); return
        hist = list(st["chat"]); st["last_sel"] = sel; st["step2"] = True
        if text: st["chat"].append(text)
        if not ctx_update and (text or sel): st["said"].append(selected_problem_text(sel, text))
        ask_var.set("")
        locked = ("aa", "fg") + (("traffic",) if tr_all.get() != "SkyTune decides" else ())
        cfgv = current_values(st["cfg"]) if st.get("cfg") else {}
        hw = st.get("hw") or (dict(DEMO_HW) if demo_hw else None)
        kw = dict(hw=hw, cfg=cfgv, goal=goal_var.get(), ctx=st["ctx"], locked=locked)
        if ai_on.get() and load_api_key()[0]:
            set_status("Asking the AI…", "info"); render([("info", "Thinking…")])
            key = load_api_key()[0]
            def work():
                d = ai_diagnose(text, hist, edition=st.get("edition"), key=key, provider=PREFS["ai_provider"],
                                base_url=PREFS["ai_base_url"], model=PREFS["ai_model"], selected=sel, **kw)
                root.after(0, lambda: got(d))
            threading.Thread(target=work, daemon=True).start()
        else:
            got(assistant_diagnose(text, history=hist, selected=sel, **kw))
    def got(d):
        st["diag"] = d; st["ctx"] = dict(d.get("context") or {}); st["session"] = FixSession(d); st["feedback"] = False
        if d.get("fallback_reason") and ai_on.get():
            set_status("AI unavailable (%s) – using SkyTune's own advice." % d["fallback_reason"], "warn")
        else:
            set_status("Here's what I suggest. Nothing changes until you click “Optimise my sim”.", "info")
        render()
    def render(extra=None):
        for w in asst.winfo_children(): w.destroy()
        r = 0
        def line(text, fg=T["text"], font=FONT, pady=(0, 2)):
            nonlocal r
            l = autowrap(tk.Label(asst, text=text, bg=T["card"], fg=fg, font=font, justify="left", anchor="w", wraplength=int(300 * DPIF)), gi2, 40)
            l.grid(row=r, column=0, sticky="w", pady=pady); r += 1; return l
        for msg in st["said"][-3:]: line("You:  " + msg, T["muted"], FONT_S)
        if extra:
            for _, t_ in extra: line(t_, T["accent"])
            return
        d = st.get("diag")
        if not d: return
        src = "AI" if d.get("source") == "ai" else "SkyTune"
        line("%s:  %s" % (src, d["message"]), T["text"], FONT_B, (2, 4))
        if d.get("bottleneck"):
            cl = line("Likely cause: %s  ·  confidence %s" % (BOTTLENECK_PLAIN[d["bottleneck"]], d["confidence"].lower()), T["accent_hi"], FONT_S)
            Tip(cl, "Why I think so:\n• " + "\n• ".join(d.get("why") or ["Based on what you described."]))
        for pp in d.get("per_problem") or []:        # v1.3.1: one line per selected problem
            line("•  %s: %s  →  %s" % (pp["label"], ("likely " + pp["cause"]) if pp["cause"] else "cause unclear",
                                       pp["fix"] or "nothing to change in your settings"), T["text"], FONT_S, (1, 1))
        for nt in (d.get("notes") or [])[:4]: line("•  " + nt, T["text"], FONT_S, (2, 1))
        for slot, q, opts in (d.get("followups") or [])[:2]:
            line(q, T["muted"], FONT_S, (6, 2))
            fr = ttk.Frame(asst, style="Card.TFrame"); fr.grid(row=r, column=0, sticky="w"); r += 1
            for lbl, val in opts:
                ch = tk.Label(fr, text=" %s " % lbl, bg=T["card2"], fg=T["text"], font=FONT_S, padx=4, pady=2, cursor="hand2",
                              highlightthickness=1, highlightbackground=T["border"])
                ch.bind("<Button-1>", lambda e, s_=slot, v=val: ask("", ctx_update={s_: v})); ch.pack(side="left", padx=(0, 4))
        st["fix_vars"] = {}
        fixes = d.get("fixes") or []
        if fixes:
            line("Suggested fixes, best first:", T["muted"], FONT_S, (8, 2))
        for n, f in enumerate(fixes):
            fr = ttk.Frame(asst, style="Card.TFrame"); fr.grid(row=r, column=0, sticky="w", pady=1); r += 1
            v = tk.BooleanVar(value=(n == 0)); st["fix_vars"][f["id"]] = v
            cb = ttk.Checkbutton(fr, text=f["title"], variable=v, style="Card.TCheckbutton"); cb.pack(side="left")
            badge(fr, {"High": "Big help", "Med": "Helps", "Low": "Small help"}[f["impact"]], f["impact"]).pack(side="left", padx=(6, 0))
            cov = [PROBLEMS[p][0] for p in f.get("covers") or [] if p in PROBLEMS]
            line("      " + ("Helps with: %s  ·  " % ", ".join(cov) if len(d.get("problems") or []) > 1 and cov else "") +
                 "Trade-off: " + f["cost"], T["muted"], FONT_S, (0, 3))
            Tip(cb, f["why"] + ("\n\nThis runs a tool – it asks first." if f.get("tool") else
                                "\n\nChanges: " + ", ".join("%s → %s" % (PLAIN.get(k, k.split("/")[-2] if "/" in k else k), val) for k, val in f["changes"].items())))
        br_ = ttk.Frame(asst, style="Card.TFrame"); br_.grid(row=r, column=0, sticky="w", pady=(8, 0)); r += 1
        if fixes:
            ttk.Button(br_, text="Use top fix", style="Primary.TButton", command=lambda: use_fixes([fixes[0]])).pack(side="left")
            ttk.Button(br_, text="Use ticked fixes", style="Secondary.TButton",
                       command=lambda: use_fixes([f for f in fixes if st["fix_vars"][f["id"]].get()])).pack(side="left", padx=8)
        link(br_, "Start over", start_over, "Clears your selections and this chat.").pack(side="left", padx=6)
        if st.get("feedback"):
            fb = ttk.Frame(asst, style="Card.TFrame"); fb.grid(row=r, column=0, sticky="w", pady=(10, 0)); r += 1
            tk.Label(fb, text="After your next flight – how was it?", bg=T["card"], fg=T["text"], font=FONT_B).pack(side="left", padx=(0, 8))
            for lbl, val in (("✓ Better", "better"), ("= Same", "same"), ("✗ Worse", "worse")):
                ttk.Button(fb, text=lbl, style="Secondary.TButton", command=lambda v_=val: feedback(v_)).pack(side="left", padx=(0, 6))
        root.after_idle(rewrap)
    def start_over():
        for v in chip_vars.values(): v.set(False)
        st.update(chat=[], said=[], ctx={}, diag=None, session=None, feedback=False, last_sel=[])
        ask_var.set(""); upd_chip_hint(); render(); set_status("Cleared – pick what's bothering you, or just optimise.")
    st["start_over"] = start_over; st["chip_vars"] = chip_vars; st["chip_btns"] = chip_btns

    def ai_guide():
        """v1.3.1: a short, friendly guide to the optional AI (offline by default)."""
        d = tk.Toplevel(root); d.title(AI_GUIDE_TITLE + " – SkyTune"); d.configure(bg=T["bg"]); d.transient(root)
        d.geometry("+%d+%d" % (root.winfo_rootx() + 120, root.winfo_rooty() + 50)); st["guide_win"] = d
        w = ttk.Frame(d, padding=16); w.pack(fill="both", expand=True)
        o, i = card(w, AI_GUIDE_TITLE, "Optional – SkyTune's own advice works offline, free, with no key."); o.pack(fill="both", expand=True)
        wl_ = int(300 * DPIF)
        for n, (h, t_) in enumerate(AI_GUIDE):
            cell = ttk.Frame(i, style="Card.TFrame"); cell.grid(row=2 + n // 2, column=n % 2, sticky="nw", padx=(0, 18), pady=(4, 8))
            ttk.Label(cell, text=h, style="Value.Card.TLabel").pack(anchor="w")
            ttk.Label(cell, text=t_, style="Muted.Card.TLabel", wraplength=wl_, justify="left").pack(anchor="w")
        bb = ttk.Frame(w); bb.pack(fill="x", pady=(12, 0))
        ttk.Button(bb, text="Close", style="Secondary.TButton", command=d.destroy).pack(side="right")
        ttk.Button(bb, text="Open AI settings", style="Primary.TButton", command=lambda: (d.destroy(), ai_settings())).pack(side="right", padx=8)
        return d

    st["ai_guide"] = lambda: ai_guide(); st["show_sim"] = lambda r: show_sim(r)

    def stage_changes(changes):
        """Put a fix's values into the pending settings without undoing a lighter value already pending."""
        if not st.get("cfg"): return 0
        file_v = current_values(st["cfg"]); pend = collect(); n = 0
        for p, v in changes.items():
            if p not in st["vars"]: continue
            fv, pv = _num(file_v.get(p)), _num(pend.get(p)); nv = _num(v)
            if nv is not None and fv is not None and pv is not None and p != "Graphics/Texture/Quality":
                v = min(pv, nv) if nv < fv else max(pv, nv)
                if float(v).is_integer() and not isinstance(nv, float): v = int(v)
            set_var(p, v); n += 1
            if p == "Video/FrameGeneration":
                inv = {x: k for k, x in active_fg_choices().items()}
                if v in inv: fg_var.set(inv[v])
            if p == "Video/AntiAliasing":
                inv = {x: k for k, x in AA_CHOICES.items()}
                if v in inv: aa_var.set(inv[v])
        refresh_summary(); return n
    def use_fixes(fixes):
        if not fixes: set_status("Tick at least one fix first.", "warn"); return
        sess = st.get("session")
        tools = [f for f in fixes if f.get("tool")]; sets = [f for f in fixes if not f.get("tool")]
        for f in fixes:
            if sess: sess.stage(f)
        n = 0
        for f in sets: n += stage_changes(f["changes"])
        if sets:
            st["staged"] = sets
            set_status("Ready – click “Optimise my sim” to save %d change%s." % (n, "" if n == 1 else "s"), "info")
            result_var.set("Fix ready. Click “Optimise my sim” to save it."); result_lbl.configure(fg=T["accent"])
        for f in tools:
            if f["tool"] == "fix_stutters": fix_stutters()
            elif f["tool"] == "update_cleanup": update_cleanup()
        if tools and not sets: st["feedback"] = True; render()
    def feedback(verdict):
        sess = st.get("session")
        if not sess: return
        r = sess.feedback(verdict)
        if r["action"] == "undo" and r["undo"] and st.get("path") and os.path.isfile(r["undo"]) and sim_check():
            undone = apply_restore(st["path"], r["undo"], reason="worse")
            if undone["ok"]:
                save_last_apply(UserCfg.load(st["path"]), st.get("edition"))
                st["held"] = set(); load(st["path"])
            else:
                set_status(undone["error"], "err"); messagebox.showerror(SHORT_NAME, undone["error"])
                r = dict(r, message=undone["error"])
        st["feedback"] = False
        if r["next"] and not r["next"].get("tool"):
            use_fixes([r["next"]])
        set_status(r["message"], "ok" if verdict == "better" else "info")
        render(); line_ = r["message"] + ("" if not r["next"] or r["next"].get("tool") else "  Click “Optimise my sim” to try it.")
        result_var.set(line_); result_lbl.configure(fg=T["accent_hi"])

    def ai_settings():
        d = tk.Toplevel(root); d.title("AI settings – SkyTune"); d.configure(bg=T["bg"]); d.transient(root)
        d.geometry("+%d+%d" % (root.winfo_rootx() + 160, root.winfo_rooty() + 70))
        w = ttk.Frame(d, padding=18); w.pack(fill="both", expand=True)
        o, i = card(w, "Ask an AI too (optional)", "Uses your own API key. SkyTune never ships or shares a key."); o.pack(fill="x")
        autowrap(ttk.Label(i, text=PRIVACY_NOTE, style="Muted.Card.TLabel", wraplength=560, justify="left"), i, 36).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))
        link(i, "? How to use AI – getting a key, costs, removing it", lambda: ai_guide()).grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        pv = tk.StringVar(value=AI_PROVIDERS[PREFS["ai_provider"]]["label"])
        bu = tk.StringVar(value=PREFS["ai_base_url"]); mo = tk.StringVar(value=PREFS["ai_model"]); kv = tk.StringVar()
        labels = {v["label"]: k for k, v in AI_PROVIDERS.items()}
        ttk.Label(i, text="Provider", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=3)
        pcb = ttk.Combobox(i, textvariable=pv, values=list(labels), state="readonly", width=24); pcb.grid(row=3, column=1, sticky="w")
        Tip(pcb, "OpenAI-compatible works with OpenAI and many others (OpenRouter, Groq, LM Studio, Ollama…) – set their address below.")
        ttk.Label(i, text="Address (base URL)", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=3)
        be = ttk.Entry(i, textvariable=bu, width=44); be.grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Label(i, text="Model", style="Card.TLabel").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(i, textvariable=mo, width=30).grid(row=5, column=1, sticky="w")
        hint = tk.StringVar()
        def fill_hint(_=None):
            pr = AI_PROVIDERS[labels[pv.get()]]; hint.set("Leave empty for %s  ·  %s" % (pr["base_url"], pr["model"]))
        pcb.bind("<<ComboboxSelected>>", fill_hint); fill_hint()
        ttk.Label(i, textvariable=hint, style="Muted.Card.TLabel").grid(row=6, column=1, columnspan=2, sticky="w")
        ttk.Label(i, text="API key", style="Card.TLabel").grid(row=7, column=0, sticky="w", pady=(10, 3))
        ttk.Entry(i, textvariable=kv, width=44, show="•").grid(row=7, column=1, columnspan=2, sticky="w", pady=(10, 3))
        kst = tk.StringVar()
        klbl = tk.Label(i, textvariable=kst, bg=T["card"], fg=T["muted"], font=FONT_S, wraplength=560, justify="left")
        klbl.grid(row=8, column=0, columnspan=3, sticky="w", pady=(2, 0))
        def show_key_state():
            k, how = load_api_key()
            if not k: kst.set("No key saved."); klbl.configure(fg=T["muted"])
            elif how == "dpapi": kst.set("✓ A key is saved, encrypted for your Windows account."); klbl.configure(fg=T["ok"])
            else: kst.set("⚠ A key is saved in a plain file only your account can read – it is NOT encrypted on this system:\n" +
                          os.path.join(config_dir(), KEY_PLAIN)); klbl.configure(fg=T["warn"])
        show_key_state()
        def save():
            url = bu.get().strip()
            if url and not valid_base_url(url):
                messagebox.showerror(SHORT_NAME, "The address must start with https:// (or http://localhost for a model on this PC).", parent=d); return
            remember(ai_provider=labels[pv.get()], ai_base_url=url, ai_model=mo.get().strip()[:100])
            if kv.get().strip():
                try: how = save_api_key(kv.get())
                except Exception as e: messagebox.showerror(SHORT_NAME, str(e), parent=d); return
                kv.set("")
                if how == "plain":
                    messagebox.showwarning(SHORT_NAME, "Windows encryption isn't available here, so the key was saved in a plain file "
                                           "that only your account can read. Use “Remove key” to delete it any time.", parent=d)
            show_key_state(); set_status("AI settings saved.")
        def remove():
            remove_api_key(); show_key_state(); set_status("API key removed.")
        bb = ttk.Frame(w); bb.pack(fill="x", pady=(12, 0))
        ttk.Button(bb, text="Close", style="Secondary.TButton", command=d.destroy).pack(side="right")
        ttk.Button(bb, text="Save", style="Primary.TButton", command=save).pack(side="right", padx=8)
        ttk.Button(bb, text="Remove key", style="Danger.TButton", command=remove).pack(side="left")

    # Step 3 (right column) – the big button lives in the sticky footer so it is always visible
    so, si = card(scol_r, "Step 3 · Optimise my sim", "Here's what will change. SkyTune asks before it writes. Not happy later? Undo, or review a backup.")
    so.pack(fill="both", expand=True)
    drift_row = ttk.Frame(si, style="Card.TFrame")
    drift_row.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 8))
    ttk.Label(drift_row, text="Since last write", style="Card.TLabel").pack(side="left")
    drift_var = tk.StringVar(value="No SkyTune write yet.")
    drift_lbl = tk.Label(drift_row, textvariable=drift_var, bg=T["card"], fg=T["muted"], font=FONT_S, anchor="w", justify="left")
    drift_lbl.pack(side="left", padx=(8, 0))
    keep_link = link(drift_row, "Keep the sim's values", lambda: toggle_hold(),
                     "Leave the settings the sim changed out of the next write. SkyTune still asks before it writes anything else.")
    Tip(drift_lbl, "Compared with the known settings from SkyTune's own last write on this PC. The simulator file is not changed.")
    def refresh_drift():
        info = describe_drift(load_last_apply(), st.get("cfg"), st.get("edition") or "unknown")
        st["drift"] = info["rows"]
        kind = info["kind"]
        if kind != "diff": st["held"] = set()
        else: st["held"] = {p for p in (st.get("held") or set()) if p in {r["path"] for r in info["rows"]}}
        if kind == "none": drift_var.set("No SkyTune write yet.")
        elif kind == "other": drift_var.set("Last write was MSFS %s, so this file is not compared." % info.get("written_edition"))
        elif kind == "match": drift_var.set("These settings still match.")
        else:
            n = len(info["rows"])
            drift_var.set("%d setting%s differ." % (n, "" if n == 1 else "s"))
        held = st.get("held") or set()
        if kind == "diff" and info["rows"]:
            keep_link.configure(text="Include them again" if held else "Keep the sim's values")
            if not keep_link.winfo_ismapped(): keep_link.pack(side="left", padx=(12, 0))
        elif keep_link.winfo_ismapped():
            keep_link.pack_forget()
    def toggle_hold():
        rows = st.get("drift") or []
        if not rows: return
        if st.get("held"):
            st["held"] = set()
            set_status("SkyTune's list includes those settings again. Nothing is written until you confirm.", "info")
        else:
            st["held"] = {r["path"] for r in rows}
            set_status("Those settings stay as the sim has them. Nothing is written until you confirm.", "info")
        refresh_drift(); refresh_summary()
    CREATOR_NONE = "No creator setup"
    creator_row = ttk.Frame(si, style="Card.TFrame")
    creator_row.grid(row=3, column=0, columnspan=2, sticky="we", pady=(0, 8))
    ttk.Label(creator_row, text="Creator setup", style="Card.TLabel").pack(side="left")
    creator_var = tk.StringVar(value=CREATOR_NONE)
    creator_cb = ttk.Combobox(creator_row, textvariable=creator_var, state="readonly", width=34,
                              values=(CREATOR_NONE,) + tuple(creator_presets("2024")))
    creator_cb.pack(side="left", padx=(8, 0))
    creator_cb.bind("<<ComboboxSelected>>", lambda e: apply_creator())
    Tip(creator_cb, EASYJET_CREDIT + " (" + EASYJET_URL + "). " + EASYJET_NOTE + " Nothing is written until you confirm.")
    def refresh_creator_row():
        if st.get("edition") == "2024":
            if not creator_row.winfo_ismapped():
                creator_row.grid(row=3, column=0, columnspan=2, sticky="we", pady=(0, 8))
        else:
            if creator_var.get() != CREATOR_NONE: creator_var.set(CREATOR_NONE)
            st["creator"] = None
            if creator_row.winfo_ismapped(): creator_row.grid_remove()
    def apply_creator(_=None):
        name = creator_var.get()
        presets = creator_presets(st.get("edition"))
        if name not in presets:
            st["creator"] = None
            st["active_profile"] = None
            refresh_summary(); return
        st["creator"] = name
        st["active_profile"] = {"name": name, "edition": "2024"}
        cur_preset["name"] = None
        for path, val in presets[name].items(): set_var(path, val)
        if st.get("sync_fg_rows"): st["sync_fg_rows"]()
        refresh_summary()
        set_status("“%s” is in the list. Nothing is written until you confirm." % name, "info")
    reset_row = ttk.Frame(si, style="Card.TFrame")
    reset_var = tk.StringVar(value="")
    reset_lbl = tk.Label(reset_row, textvariable=reset_var, bg=T["card"], fg=T["warn"], font=FONT_S, justify="left", anchor="w", wraplength=280)
    reset_lbl.pack(side="left", fill="x", expand=True)
    put_back_btn = ttk.Button(reset_row, text="Put my settings back", style="Secondary.TButton", command=lambda: put_settings_back())
    def refresh_reset():
        cfg = st.get("cfg")
        snap = load_last_apply()
        backup_cfg = None
        mtime = None
        if st.get("path") and os.path.isfile(st["path"]):
            try: mtime = os.path.getmtime(st["path"])
            except OSError: mtime = None
        if not snap and st.get("path"):
            bs = list_backups(st["path"])
            if bs:
                try: backup_cfg = UserCfg.load(bs[-1])
                except Exception: backup_cfg = None
        info = reset_report(cfg, snap, backup_cfg, mtime, (snap or {}).get("written_at") if snap else None)
        st["reset"] = info
        if info.get("reset"):
            reset_var.set("Your settings may have been reset by a sim update. %d known settings differ from SkyTune's %s." % (
                len(info["rows"]), info.get("source") or "earlier note"))
            if not reset_row.winfo_ismapped():
                reset_row.grid(row=8, column=0, columnspan=2, sticky="we", pady=(8, 0))
            if not put_back_btn.winfo_ismapped(): put_back_btn.pack(side="right")
        elif reset_row.winfo_ismapped():
            reset_row.grid_remove()
    def put_settings_back():
        info = st.get("reset") or {}
        values = snapshot_to_values(info.get("values"))
        if not values or not st.get("cfg"):
            set_status("There is no earlier SkyTune note to put back.", "warn"); return
        for path, val in values.items():
            if path in st.get("cfg").index: set_var(path, val)
        st["active_profile"] = {"name": "Settings from before the reset", "edition": st.get("edition")}
        refresh_summary()
        set_status("Earlier settings are in the list. Click Optimise, then Yes, write. Nothing is written yet.", "info")
    bind_row = ttk.Frame(si, style="Card.TFrame")
    bind_row.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
    bind_var = tk.BooleanVar(value=False)
    bind_cb = ttk.Checkbutton(bind_row, text="Back up control bindings", variable=bind_var, command=lambda: st.__setitem__("backup_bindings", bool(bind_var.get())))
    bind_cb.pack(side="left")
    bind_status = tk.StringVar(value="Not found")
    tk.Label(bind_row, textvariable=bind_status, bg=T["card"], fg=T["muted"], font=FONT_S).pack(side="left", padx=(8, 0))
    def refresh_bindings():
        found = find_input_profiles()
        st["bindings"] = found
        if found:
            bind_status.set("%d found" % len(found))
            bind_cb.state(["!disabled"])
        else:
            bind_var.set(False); st["backup_bindings"] = False
            bind_status.set("Not found")
            bind_cb.state(["disabled"])
    Tip(bind_cb, "Copies Steam inputprofile files found next to this PC's Steam userdata. Microsoft Store bindings are not copied. Nothing is written until you confirm a settings write, and a restore checks the copy.")
    flight_row = ttk.Frame(si, style="Card.TFrame")
    flight_row.grid(row=4, column=0, columnspan=2, sticky="we", pady=(0, 8))
    ttk.Label(flight_row, text="This flight", style="Card.TLabel").pack(side="left")
    scenario_var = tk.StringVar(value=SCENARIO_NONE)
    flight_cb = ttk.Combobox(flight_row, textvariable=scenario_var, state="readonly", width=22,
                             values=(SCENARIO_NONE,) + SCENARIOS)
    flight_cb.pack(side="left", padx=(8, 0))
    flight_cb.bind("<<ComboboxSelected>>", lambda e: apply_flight())
    Tip(flight_cb, "A situation for this flight. It adjusts the list and explains the tradeoff. Nothing is written until you confirm.")
    link_row = ttk.Frame(si, style="Card.TFrame"); link_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 8))
    link(link_row, "Saved profiles…", lambda: profiles_dialog(),
         "Save this setup and use it again on this PC. Using a profile only prepares changes.").pack(side="left")
    link(link_row, "Review backups…", lambda: backups_dialog(),
         "See the before/after difference for each backup, then restore one if you want.").pack(side="left", padx=(14, 0))
    if EXTRA is not None:
        EXTRA.add_controls(link_row, {
            "root": root, "T": T, "link": link, "edition": lambda: st.get("edition") or "2024",
            "version": VERSION, "restore_latest": lambda: restore(True),
            "restore_path": lambda src: restore(False, src=src),
            "list_backups": lambda: list_backups(st["path"]) if st.get("path") else [],
            "read_review": read_change_review, "backup_label": backup_label,
            "cfg_path": lambda: st.get("path"),
        })
    summary = tk.Text(si, height=6, width=40, bg=T["card"], fg=T["text"], relief="flat", font=FONT, wrap="word",
                      highlightthickness=0, padx=2, pady=4, cursor="arrow")
    summary.grid(row=6, column=0, sticky="nsew"); si.rowconfigure(6, weight=1); si.columnconfigure(0, weight=1)
    sum_sb = ttk.Scrollbar(si, command=summary.yview); summary.configure(yscrollcommand=sum_sb.set)
    sum_sb.grid(row=6, column=1, sticky="ns")
    def _sum_wheel(e):
        summary.yview_scroll(-2 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 2, "units"); return "break"
    for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"): summary.bind(ev, _sum_wheel)
    summary.tag_configure("old", foreground=T["muted"]); summary.tag_configure("new", foreground=T["accent_hi"], font=FONT_B)
    summary.tag_configure("head", foreground=T["text"], font=FONT_B); summary.tag_configure("muted", foreground=T["muted"])
    footer = ttk.Frame(root, style="Header.TFrame", padding=(20, 10))
    tk.Frame(footer, bg=T["border"], height=1).pack(side="top", fill="x", pady=(0, 10))
    apply_big = ttk.Button(footer, text="✈  Optimise my sim", style="Big.Primary.TButton", command=lambda: optimise())
    apply_big.pack(side="right", fill="x", expand=True, padx=(10, 0))
    undo_big = ttk.Button(footer, text="↶  Undo", style="Big.Danger.TButton", command=lambda: restore(True))
    undo_big.pack(side="right")
    confirm_bar = tk.Frame(footer, bg=T["header"])
    yes_btn = ttk.Button(confirm_bar, text="Yes, write", style="Confirm.TButton", command=lambda: commit_pending())
    yes_btn.pack(side="left")
    cancel_btn = ttk.Button(confirm_bar, text="Cancel", style="Cancel.TButton", command=lambda: cancel_pending())
    cancel_btn.pack(side="left", padx=(8, 0))
    sim_lock(apply_big, Tip(apply_big, "Shows what will change. Nothing is written until you click Yes, write."))
    sim_lock(undo_big, Tip(undo_big, "Shows what the latest backup would put back. Nothing changes until you click Yes, restore."))
    result_var = tk.StringVar(value="Every change is backed up first.")
    result_lbl = tk.Label(footer, textvariable=result_var, bg=T["header"], fg=T["muted"], font=FONT_B, justify="left", anchor="w")
    result_lbl.pack(side="left", padx=(0, 10), fill="x", expand=True)
    autowrap(result_lbl, footer, 520); result_tip = Tip(result_lbl, "")
    def optimise():
        if not st.get("cfg"): autodetect()
        if not st.get("cfg"): return
        if not st.get("hw") and not st.get("staged") and not (st.get("active_profile") or {}).get("name"):
            set_status("Checking your PC first…", "info"); auto_detect(popup=False, then=apply); return
        apply()

    # My preferences (collapsed)
    prefs_card, prefs_inner = card(scol_r); prefs_card.pack(fill="x", pady=(14, 0))
    phead = ttk.Frame(prefs_inner, style="Card.TFrame"); phead.grid(row=0, column=0, sticky="we"); prefs_inner.columnconfigure(0, weight=1)
    ptoggle = tk.Label(phead, text="▸  My preferences", bg=T["card"], fg=T["accent"], font=(F, 11, "bold"), cursor="hand2")
    ptoggle.pack(side="left")
    psum = tk.StringVar()
    psum_lbl = autowrap(tk.Label(prefs_inner, textvariable=psum, bg=T["card"], fg=T["muted"], font=FONT_S, justify="left", anchor="w", wraplength=400), prefs_inner, 36)
    psum_lbl.grid(row=1, column=0, sticky="w", pady=(4, 0))
    pbody = ttk.Frame(prefs_inner, style="Card.TFrame")
    def show_prefs(open_):
        ptoggle.configure(text=("▾" if open_ else "▸") + "  My preferences")
        if open_: pbody.grid(row=2, column=0, sticky="we", pady=(8, 0))
        else: pbody.grid_remove()
    def toggle_prefs():
        o_ = not PREFS.get("prefs_open"); remember(prefs_open=o_); show_prefs(o_)
    ptoggle.bind("<Button-1>", lambda e: toggle_prefs()); psum_lbl.bind("<Button-1>", lambda e: toggle_prefs())
    Tip(ptoggle, "Your own choices. SkyTune keeps them and never changes them unless you ask.")
    aa_var = tk.StringVar(value=PREFS["aa"]); fg_var = tk.StringVar(value=PREFS["fg"]); dlss_note = tk.StringVar(value="")
    aa_l = ttk.Label(pbody, text="Smooth edges", style="Card.TLabel"); aa_l.grid(row=0, column=0, sticky="w", pady=3)
    aa_cb = ttk.Combobox(pbody, textvariable=aa_var, values=list(AA_CHOICES), state="readonly", width=18)
    aa_cb.grid(row=0, column=1, sticky="w", padx=12)
    fg_l = ttk.Label(pbody, text="Extra frames", style="Card.TLabel"); fg_l.grid(row=1, column=0, sticky="w", pady=3)
    fg_cb = ttk.Combobox(pbody, textvariable=fg_var, values=list(FG_CHOICES), state="readonly", width=18)
    fg_cb.grid(row=1, column=1, sticky="w", padx=12)
    AA_TIP = ("Smooth edges (also called anti-aliasing) removes jagged edges and can upscale the image.\nTAA: works on every graphics card and is a good starting point for clear cockpit text.\n"
              "NVIDIA DLSS: RTX cards only, and it is saved in your settings. That does not prove DLSS is running. "
              "AMD FSR: broad GPU support; the FSR version from the graphics driver may differ.\n"
              "For DLSS/FSR, choose Quality first and lower it only if you need more performance.")
    FG_TIP = ("Extra frames (also called frame generation) adds in-between frames for smoother motion, but does not improve input response. Start with Off until you confirm a stable base frame rate.\n"
              "AMD FSR frame generation: broad GPU support and 2x only. NVIDIA DLSS FG: RTX 40/50 only, HAGS required; 3x/4x multipliers are RTX 50-only.\n"
              "The choice is saved in your settings. A saved setting does not prove frame generation is running.")
    for w_, t_ in ((aa_cb, AA_TIP), (aa_l, AA_TIP), (fg_cb, FG_TIP), (fg_l, FG_TIP)): Tip(w_, t_)
    tr_all = tk.StringVar(value=PREFS["traffic"])
    tr_l = ttk.Label(pbody, text="Traffic & people", style="Card.TLabel"); tr_l.grid(row=2, column=0, sticky="w", pady=3)
    tr_cb = ttk.Combobox(pbody, textvariable=tr_all, values=list(TRAFFIC_LEVELS), state="readonly", width=18)
    tr_cb.grid(row=2, column=1, sticky="w", padx=12)
    TR_TIP = ("One setting for all traffic and population: AI aircraft, parked aircraft, ground vehicles, people, road traffic, "
              "boats and wildlife. Lots of traffic is hard work for your processor at busy airports.\n'Off' writes the simulator's actual -1 Off value to supported graphics settings; Low writes 0.\n"
              "Online Aircraft Traffic Type and Multiplayer are separate simulator options and are not changed here. "
              "Disable those in the simulator's Online/Traffic settings too if you also want to stop live or multiplayer aircraft.\n"
              "Fine-tune each graphics category in Advanced settings.")
    Tip(tr_cb, TR_TIP); Tip(tr_l, TR_TIP)
    autowrap(tk.Label(pbody, textvariable=dlss_note, bg=T["card"], fg=T["warn"], font=FONT_S, wraplength=400,
             justify="left"), pbody, 20).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
    def upd_psum():
        psum.set(prefs_summary(aa_var.get(), fg_var.get(), tr_all.get()))
    def active_fg_choices():
        cfg = st.get("cfg")
        if cfg and "Video/FrameGeneration" not in cfg.index:
            # MSFS 2020 only exposes DLSS frame generation (boolean Video/DLSSG)
            if "Video/DLSSG" in cfg.index:
                return {"Off": "NONE", "NVIDIA DLSS FG": "DLSSG"}
            return {"Off": "NONE"}
        return FG_CHOICES
    def choices():
        return AA_CHOICES.get(aa_var.get(), DEFAULT_AA), active_fg_choices().get(fg_var.get(), DEFAULT_FG)
    def on_choice(_=None):
        aa, fg = choices(); set_var("Video/AntiAliasing", aa); set_var("Video/FrameGeneration", fg)
        if st.get("cfg") and "Video/FrameGeneration" not in st["cfg"].index and "Video/DLSSG" in st["cfg"].index:
            legacy_fg = 1 if fg == "DLSSG" else 0
            # remembered for the MSFS 2020 DLSSG mapping
            st["legacy_fg"] = legacy_fg
        # the multiplier is clamped to what the GPU supports when values are built
        set_var("Video/NBFramesToGenerate", 1)
        if _ is not None:
            remember(aa=aa_var.get(), fg=fg_var.get()); st["active_profile"] = None
            st["creator"] = None
            if creator_var.get() != CREATOR_NONE: creator_var.set(CREATOR_NONE)
        upd_psum(); refresh_summary()
    aa_cb.bind("<<ComboboxSelected>>", on_choice); fg_cb.bind("<<ComboboxSelected>>", on_choice)
    def apply_gpu_limits(gpu):
        aa_ok, fg_ok, note = dlss_support(gpu)
        aa_cb.configure(values=[k for k, v in AA_CHOICES.items() if v != "DLSS" or aa_ok is not False])
        fg_allowed = active_fg_choices()
        if os.name != "nt":
            # DLSS frame generation is not available under Proton/Wine
            fg_allowed = {k: v for k, v in fg_allowed.items() if v != "DLSSG"}
        fg_names = [k for k, v in fg_allowed.items() if v != "DLSSG" or fg_ok is not False]
        if not fg_names: fg_names = ["Off"]
        fg_cb.configure(values=fg_names)
        if aa_var.get() not in aa_cb.cget("values"): aa_var.set("TAA")
        if fg_var.get() not in fg_names: fg_var.set("Off")
        dlss_note.set("⚠  " + note if note else ""); on_choice()
        if st.get("sync_fg_rows"): st["sync_fg_rows"]()
    def traffic_choices():
        return traffic_for_level(tr_all.get())
    def on_traffic(_=None):
        for p, lvl in traffic_choices().items():
            if lvl is not None: set_var(p, lvl)
        if _ is not None:
            remember(traffic=tr_all.get()); st["active_profile"] = None
            st["creator"] = None
            if creator_var.get() != CREATOR_NONE: creator_var.set(CREATOR_NONE)
        upd_psum(); refresh_summary()
    tr_cb.bind("<<ComboboxSelected>>", on_traffic)
    upd_psum(); show_prefs(PREFS.get("prefs_open"))

    # Tools
    clo, cli = card(scol_r, "Tools"); clo.pack(fill="x", pady=(14, 0)); cli.columnconfigure(1, weight=1)
    fx = ttk.Button(cli, text="⚡  Fix stutters", style="Secondary.TButton", command=lambda: fix_stutters()); fx.grid(row=2, column=0, sticky="we", pady=(6, 0))
    autowrap(ttk.Label(cli, text="Clears old caches that cause stutters.", style="Muted.Card.TLabel", wraplength=260), cli, 200).grid(row=2, column=1, sticky="w", padx=10, pady=(6, 0))
    Tip(fx, "Clears the sim cache folder and the Windows, NVIDIA and AMD shader caches that often cause stutters after driver or sim updates.\n"
            "Asks first and shows the total size. Your first flight afterwards loads slower while shaders rebuild.")
    uc = ttk.Button(cli, text="↻  Update Cleanup", style="Secondary.TButton", command=lambda: update_cleanup())
    uc.grid(row=3, column=0, sticky="we", pady=(8, 0))      # v1.3.1: no fixed width (was cut off as "Update Cleanu")
    st["tool_buttons"] = (fx, uc)
    autowrap(ttk.Label(cli, text="After a sim update: sets add-ons aside to find what broke.", style="Muted.Card.TLabel", wraplength=260), cli, 200).grid(row=3, column=1, sticky="w", padx=10, pady=(8, 0))
    Tip(uc, "After a sim update: backs up your settings, moves your add-ons aside (renamed, never deleted), "
            "optionally resets graphics, clears shader caches and rebuilds scenery indexes. Shows every step first. Fully undoable.")
    sim_lock(fx); sim_lock(uc)
    tl = ttk.Frame(cli, style="Card.TFrame"); tl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
    link(tl, "Choose caches…", lambda: open_cleaner(), "Pick exactly which caches to clear.").pack(side="left")
    link(tl, "Undo Update Cleanup", lambda: undo_cleanup(), "Moves your add-ons back and restores your settings.").pack(side="left", padx=(14, 0))
    sp = ttk.Button(cli, text="Support pack", style="Secondary.TButton", command=lambda: save_support_pack())
    sp.grid(row=5, column=0, sticky="we", pady=(8, 0))
    autowrap(ttk.Label(cli, text="A zip of the log, the PC check and the last settings change.", style="Muted.Card.TLabel", wraplength=260), cli, 200).grid(row=5, column=1, sticky="w", padx=10, pady=(8, 0))
    Tip(sp, "Saves a zip you can keep: SkyTune's log, the PC check, and the latest before/after settings. You see the file list before it is saved. Account names are hidden. Nothing is uploaded.")


    # ================= cache cleaner =================
    def build_cleaner(parent, compact=False):
        items = resolve_cache_items(sim_version=st.get("edition"))
        rows, vars_ = [], {}
        o, i = card(parent, "Clean up caches", "Clear temporary and shader caches. Never touches your settings, add-ons "
                    "(Community), official content, logbook or saved flights.")
        o.pack(fill="both", expand=True)
        total_var = tk.StringVar(value="Measuring…")
        r = 2
        missing = [it for it in items if not it["exists"]]
        for it in [x for x in items if x["exists"]]:
            v = tk.BooleanVar(value=it["default"] and it["exists"]); vars_[it["id"]] = v
            cb = ttk.Checkbutton(i, text=it["title"], variable=v, style="Card.TCheckbutton",
                                 command=lambda: update_total())
            cb.grid(row=r, column=0, sticky="w", pady=(6, 0))
            if not it["exists"]: cb.state(["disabled"])
            sz = tk.StringVar(value="not found" if not it["exists"] else "…")
            ttk.Label(i, textvariable=sz, style="Value.Card.TLabel", width=10).grid(row=r, column=1, sticky="e", padx=8)
            ttk.Label(i, text=("⚡ stutter fix · " if it.get("stutter") else "") + it["edition"],
                      style="Muted.Card.TLabel").grid(row=r, column=2, sticky="w")
            ex = autowrap(ttk.Label(i, text=it["explain"], style="Muted.Card.TLabel", wraplength=560 if not compact else 520, justify="left"), i, 140)
            ex.grid(row=r + 1, column=0, columnspan=3, sticky="w", padx=(26, 0))
            Tip(cb, it["explain"] + ("\n\nLinked to stutters when stale or corrupt – source: " + it["stutter"] if it.get("stutter") else "")
                + "\n\n" + it["path"])
            rows.append((it, v, sz)); r += 2
        if missing:
            ttk.Label(i, text="Not on this PC (skipped): " + ", ".join(x["title"] for x in missing), style="Muted.Card.TLabel",
                      wraplength=600, justify="left").grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0)); r += 1
        if not rows:
            ttk.Label(i, text="No caches found – nothing to clean.", style="Card.TLabel").grid(row=r, column=0, sticky="w"); r += 1
        autowrap(ttk.Label(i, text=CACHE_SAFE_NOTE, style="Ok.Card.TLabel", wraplength=600, justify="left"), i, 40).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(10, 0)); r += 1
        i.columnconfigure(0, weight=1)
        sizes = {}
        def update_total():
            tick = [it for it, v, _ in rows if v.get()]
            total_var.set(cache_total_text(len(tick), sum(sizes.get(it["id"], 0) for it in tick),
                                           measuring=any(it["id"] not in sizes for it in tick)))
        def measure():
            for it, v, sz in rows:
                if it["exists"]:
                    n = path_size(it["path"]); sizes[it["id"]] = n
                    root.after(0, lambda sz=sz, n=n: sz.set(human_size(n)))
            root.after(0, update_total)
        threading.Thread(target=measure, daemon=True).start()
        foot = ttk.Frame(i, style="Card.TFrame"); foot.grid(row=r, column=0, columnspan=3, sticky="we", pady=(14, 0))
        ttk.Label(foot, textvariable=total_var, style="Total.Card.TLabel").pack(side="left")
        def do_clear():
            sel = [it for it, v, _ in rows if v.get() and it["exists"]]
            if not sel: set_status("Tick at least one item to clear.", "warn"); return
            run_clear(sel, items, sizes, done=lambda: threading.Thread(target=measure, daemon=True).start())
        cb_ = ttk.Button(foot, text="Clear selected", style="Danger.TButton", command=do_clear); cb_.pack(side="right")
        sim_lock(cb_, Tip(cb_, "Deletes the ticked caches after asking you."))
        st["cache_total"] = total_var
        return o

    def run_clear(sel, items, sizes, title="Clear", done=None):
        if not sel: set_status("Nothing to clear.", "warn"); return False
        if not sim_check(): return False
        tot = sum(sizes.get(it["id"], 0) for it in sel)
        if not messagebox.askyesno(SHORT_NAME, "%s %d item%s (%s)?\n\n%s\n\nYour first flight afterwards will load "
                                   "slower while shaders and caches rebuild. Files in use are skipped safely." %
                                   (title, len(sel), "" if len(sel) == 1 else "s", human_size(tot),
                                    "\n".join("• " + it["title"] for it in sel))): return False
        def work():                                 # v1.3.2: deleting thousands of files no longer freezes the window
            freed = deleted = 0; skipped = []
            for it in sel:
                res = clear_item(it, items); freed += res["freed"]; deleted += res["deleted"]; skipped += res["skipped"] + res["refused"]
            return freed, deleted, skipped
        def fin(r_):
            freed, deleted, skipped = r_
            msg = "Freed %s (%d files)." % (human_size(freed), deleted)
            if skipped: msg += "\n\n%d file(s) were in use and were skipped – that's normal. Restart Windows and run it again to get them." % len(skipped)
            set_status("Caches cleared – " + msg.split("\n")[0]); messagebox.showinfo(SHORT_NAME, "Done! " + msg)
            if done: done()
        run_bg(work, fin, "Clearing caches…")
        return True


    def update_cleanup():
        if not st["path"]: set_status("Load your UserCfg.opt first.", "warn"); return
        if st.get("edition") != "2024":
            messagebox.showinfo(SHORT_NAME, "Update Cleanup's add-on migration and simulator-cache map is currently validated for MSFS 2024 only. Graphics optimisation works with MSFS 2020 too; this destructive cleanup is disabled for this file to avoid touching the wrong folders.")
            return
        if not sim_check(): return
        reset = tk.BooleanVar(value=False)          # default: keep current graphics settings
        p = plan_update_cleanup(st["path"], reset_graphics=False)
        dlg = tk.Toplevel(root); dlg.title("Update Cleanup – SkyTune"); dlg.configure(bg=T["bg"]); dlg.transient(root)
        dlg.geometry("720x600+%d+%d" % (root.winfo_rootx() + 120, root.winfo_rooty() + 60))
        wrap = ttk.Frame(dlg, padding=16); wrap.pack(fill="both", expand=True)
        o, i = card(wrap, "Update Cleanup", "Use after a sim update if MSFS crashes, stutters or looks wrong. Here's exactly what will happen:")
        o.pack(fill="both", expand=True)
        if not p["ok"]:
            for n, e in enumerate(p["errors"]):
                tk.Label(i, text="⚠  " + e, bg=T["card"], fg=T["warn"], font=FONT, wraplength=640, justify="left").grid(row=2 + n, column=0, sticky="w")
            ttk.Button(wrap, text="Close", style="Secondary.TButton", command=dlg.destroy).pack(anchor="e", pady=(10, 0)); return
        tot = sum(path_size(it["path"]) for it in p["caches"])
        steps = ["1.  Back up your UserCfg.opt.",
                 "2.  Rename your add-ons folder (nothing is deleted):\n      %s\n      →  %s" % (p["community"], os.path.basename(p["rename_to"])),
                 "3.  Create a fresh, empty Community folder so the sim starts without add-ons.",
                 "4.  Graphics settings – your choice below (UserCfg.opt is backed up first either way).",
                 "5.  Clear %d cache%s – shader caches, sim cache and scenery indexes (%s). Your first flight loads slower while they rebuild." %
                 (len(p["caches"]), "" if len(p["caches"]) == 1 else "s", human_size(tot))]
        for n, t_ in enumerate(steps):
            ttk.Label(i, text=t_, style="Card.TLabel", wraplength=640, justify="left").grid(row=2 + n, column=0, sticky="w", pady=3)
        gf = ttk.Frame(i, style="Card.TFrame"); gf.grid(row=8, column=0, sticky="w", pady=(10, 0))
        ttk.Label(gf, text="Graphics settings:", style="Big.Card.TLabel").pack(side="left", padx=(0, 10))
        ttk.Radiobutton(gf, text="Keep my current settings", value=False, variable=reset, style="Pick.TRadiobutton").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(gf, text="Reset to safe defaults", value=True, variable=reset, style="Pick.TRadiobutton").pack(side="left")
        ttk.Label(i, text="Is this your add-ons folder? Check the path above. You can undo all of this with “Undo Update Cleanup”. "
                  "A log is saved next to your backups.", style="Muted.Card.TLabel", wraplength=640, justify="left").grid(row=9, column=0, sticky="w", pady=(10, 0))
        def go():
            if not sim_check(): return
            p["reset_graphics"] = reset.get(); dlg.destroy()
            r = run_update_cleanup(st["path"], p); load(st["path"])
            if r["ok"]:
                set_status("Update Cleanup done – add-ons moved to %s" % os.path.basename(r["renamed_to"]))
                messagebox.showinfo(SHORT_NAME, "Update Cleanup done! ✈\n\n• Add-ons moved to %s\n• Freed %s of caches%s\n\n"
                                    "Start MSFS 2024. When it works, move add-ons back a few at a time, or click "
                                    "“Undo Update Cleanup”." % (os.path.basename(r["renamed_to"]), human_size(r["freed"]),
                                                               " (%d files in use were skipped)" % r["skipped"] if r["skipped"] else ""))
            else:
                set_status("Update Cleanup stopped – nothing was changed.", "err")
                messagebox.showerror(SHORT_NAME, "Update Cleanup couldn't finish, so SkyTune put everything back as it was.\n\n%s" % r["error"])
        bb = ttk.Frame(wrap); bb.pack(fill="x", pady=(10, 0))
        ttk.Button(bb, text="Cancel", style="Secondary.TButton", command=dlg.destroy).pack(side="right")
        ttk.Button(bb, text="Run Update Cleanup", style="Primary.TButton", command=go).pack(side="right", padx=8)

    def undo_cleanup():
        if not st["path"]: return
        if not sim_check(): return
        stt = undo_state(st["path"])
        if not stt: messagebox.showinfo(SHORT_NAME, "There's no Update Cleanup to undo."); return
        if not messagebox.askyesno(SHORT_NAME, "Undo the Update Cleanup from %s?\n\n• Rename %s back to Community\n• Restore your "
                                   "UserCfg.opt from before" % (stt["time"].replace("T", " "), os.path.basename(stt["renamed_to"]))): return
        r = undo_update_cleanup(st["path"], merge_new=False)
        if not r["ok"] and r.get("needs_merge"):
            if not messagebox.askyesno(SHORT_NAME, "You've added things to the new Community folder since.\n\nMove them into the "
                                       "restored folder? (Anything with the same name is kept aside, never overwritten.)"): return
            r = undo_update_cleanup(st["path"], merge_new=True)
        load(st["path"])
        if r["ok"]:
            msg = "Undone – your add-ons folder and settings are back."
            if r.get("conflicts"): msg += "\n\n%d item(s) had the same name and were kept in a 'Community-new-…' folder." % len(r["conflicts"])
            set_status("Update Cleanup undone."); messagebox.showinfo(SHORT_NAME, msg)
        else:
            set_status("Undo failed – see log.", "err"); messagebox.showerror(SHORT_NAME, "Couldn't undo:\n\n%s" % r["error"])

    def fix_stutters():
        items = resolve_cache_items(sim_version=st.get("edition")); sel = stutter_fix_items(items)
        if not sel:
            messagebox.showinfo(SHORT_NAME, "No stutter-related caches found on this PC – nothing to clear."); return
        run_bg(lambda: {it["id"]: path_size(it["path"]) for it in sel},          # v1.3.2: sizes measured off the UI thread
               lambda sizes: run_clear(sel, items, sizes, title="Fix stutters: clear"), "Measuring caches…")

    def open_cleaner():
        dlg = tk.Toplevel(root); dlg.title("Clean up caches – SkyTune"); dlg.configure(bg=T["bg"]); dlg.transient(root)
        try: dlg.iconbitmap(resource_path("app.ico")) if os.name == "nt" else None
        except Exception: pass
        # v1.3.1: the window fits its content (the list grew a total + "safe to clear" note and was cut off at a
        # fixed 700 px); on short screens the list scrolls and Close stays visible.
        foot = ttk.Frame(dlg, padding=(16, 0, 16, 12)); foot.pack(side="bottom", fill="x")
        ttk.Button(foot, text="Close", style="Secondary.TButton", command=dlg.destroy).pack(anchor="e")
        body = ttk.Frame(dlg); body.pack(fill="both", expand=True)
        cv = tk.Canvas(body, bg=T["bg"], highlightthickness=0); sb = ttk.Scrollbar(body, command=cv.yview)
        cv.configure(yscrollcommand=sb.set); cv.pack(side="left", fill="both", expand=True)
        wrap = ttk.Frame(cv, padding=16); win = cv.create_window((0, 0), window=wrap, anchor="nw")
        build_cleaner(wrap, compact=True)
        def fit(_e=None):
            cv.itemconfigure(win, width=cv.winfo_width()); cv.configure(scrollregion=(0, 0, 0, wrap.winfo_reqheight()))
            if wrap.winfo_reqheight() > cv.winfo_height() + 1:
                if not sb.winfo_ismapped(): sb.pack(side="right", fill="y")
            elif sb.winfo_ismapped(): sb.pack_forget()
        cv.bind("<Configure>", fit); wrap.bind("<Configure>", fit)
        dlg.bind("<MouseWheel>", lambda e: cv.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        dlg.bind("<Button-4>", lambda e: cv.yview_scroll(-1, "units")); dlg.bind("<Button-5>", lambda e: cv.yview_scroll(1, "units"))
        dlg.update_idletasks()
        w_ = max(720, wrap.winfo_reqwidth() + 20); h_ = wrap.winfo_reqheight() + foot.winfo_reqheight() + 4
        h_ = min(h_, dlg.winfo_screenheight() - 90); w_ = min(w_, dlg.winfo_screenwidth() - 40)
        x_ = max(0, min(root.winfo_rootx() + 120, dlg.winfo_screenwidth() - w_ - 10)); y_ = max(0, min(root.winfo_rooty() + 40, dlg.winfo_screenheight() - h_ - 60))
        dlg.geometry("%dx%d+%d+%d" % (w_, h_, x_, y_)); st["cleaner_dlg"] = dlg

    def refresh_summary():
        summary.config(state="normal"); summary.delete("1.0", "end")
        if not st["cfg"]:
            summary.insert("end", "No settings file loaded yet.\nClick “Find file” or “Browse…” at the top.", "muted")
        else:
            note = upscaler_saved_note(st["cfg"])
            if note:
                summary.insert("end", note + "\n\n", "muted")
            ch = summarize_changes(st["cfg"], collect(), res_opt.get())
            prof = st.get("active_profile") or {}
            if st.get("creator"):
                summary.insert("end", st["creator"] + "\n", "head")
                summary.insert("end", EASYJET_CREDIT + ". " + EASYJET_URL + "\n", "muted")
                summary.insert("end", "The creator has not endorsed SkyTune. " + EASYJET_NOTE + "\n", "muted")
                if st["creator"] == EASYJET_8GB_NAME:
                    summary.insert("end", "Differences from the main preset:\n", "head")
                    for label, old, new in creator_differences():
                        summary.insert("end", "• %s  " % label); summary.insert("end", old, "old")
                        summary.insert("end", "  →  "); summary.insert("end", new + "\n", "new")
                    summary.insert("end", EASYJET_8GB_KEPT + "\n", "muted")
                summary.insert("end", "Not changed: %s.\n\n" % ", ".join(EASYJET_UNMAPPED), "muted")
            elif prof.get("name"):
                summary.insert("end", "Prepared from profile “%s”.\n" % prof["name"], "head")
            rows = st.get("drift") or []
            held = st.get("held") or set()
            if rows:
                summary.insert("end", "Since SkyTune last wrote, %d setting%s differ:\n" % (len(rows), "" if len(rows) == 1 else "s"), "head")
                for row in rows[:6]:
                    if row["path"] in held:
                        summary.insert("end", "• %s stays %s\n" % (row["label"], row["now"]), "muted")
                    else:
                        summary.insert("end", "• %s  " % row["label"]); summary.insert("end", row["was"], "old")
                        summary.insert("end", "  now  "); summary.insert("end", row["now"] + "\n", "new")
                if len(rows) > 6: summary.insert("end", "• and %d more\n" % (len(rows) - 6), "muted")
                summary.insert("end", "\n")
            scen = st.get("scenario") or {}
            if scen.get("name"):
                summary.insert("end", "This flight: %s\n" % scen["name"], "head")
                for note in (scen.get("notes") or [])[:3]:
                    summary.insert("end", note + "\n", "muted")
            if not ch:
                summary.insert("end", "Nothing to change – your settings already match.\n\nPick a preset, use a saved profile, or run Auto-detect.", "muted")
            else:
                summary.insert("end", "%d setting%s will change:\n\n" % (len(ch), "" if len(ch) == 1 else "s"), "head")
                why = {}
                try:
                    hw = dict(st.get("hw") or {})
                    hz = (st.get("health") or {}).get("refresh_hz")
                    if not hw.get("refresh_hz"):
                        hw["refresh_hz"] = hz
                    why = change_reasons(st["cfg"], collect(), hw, res_opt.get())
                except Exception:
                    why = {}
                for label, old, new in ch:
                    summary.insert("end", "• %s  " % label); summary.insert("end", old, "old")
                    summary.insert("end", "  →  "); summary.insert("end", new + "\n", "new")
                    if why.get(label):
                        summary.insert("end", "  %s\n" % why[label], "muted")
                summary.insert("end", "\nSkyTune asks before writing. A backup is made first.", "muted")
        summary.config(state="disabled")



    def dismiss_welcome():
        welcome_o.pack_forget()
        try: save_state({"first_launch_done": True})
        except Exception: pass

    view = {"adv": False}
    def toggle_view(force=None):
        view["adv"] = (not view["adv"]) if force is None else force
        if view["adv"]:
            simple_outer.pack_forget(); footer.pack_forget(); ban.pack(fill="x", padx=20, pady=(14, 0)); body.pack(fill="both", expand=True)
            if st.get("sim"): simban.pack(fill="x", padx=20, pady=(12, 0), before=ban)
            view_btn.configure(text="◂ Simple view")
        else:
            body.pack_forget(); ban.pack_forget(); footer.pack(side="bottom", fill="x"); simple_outer.pack(fill="both", expand=True); refresh_summary()
            if st.get("sim"): simban.pack(fill="x", padx=20, pady=(12, 0), before=simple_outer)
            view_btn.configure(text="Advanced settings ▸")

    def poll_sim():
        """v1.3.2: one process snapshot (no tasklist child process) every 4 s – every 15 s while minimised."""
        if not st.get("sim_poll_busy"):
            st["sim_poll_busy"] = True
            def work():
                r = True if "--sim-running" in sys.argv else sim_running()
                def fin(): st["sim_poll_busy"] = False; show_sim(r)
                try: root.after(0, fin)
                except (RuntimeError, tk.TclError): pass
            threading.Thread(target=work, daemon=True).start()
        try: idle = root.state() in ("iconic", "withdrawn")
        except tk.TclError: return
        root.after(15000 if idle else 4000, poll_sim)
    def show_sim(r):
        if st.get("sim_shown") == r and r is not None and "sim" in st: return      # unchanged – skip the redraw
        st["sim_shown"] = r
        kind, text = sim_status_text(r)
        bg = {"ok": "#0f3d2e", "err": "#4a1520", "warn": "#3d2f0f"}[kind]
        fg = {"ok": T["ok"], "err": T["danger"], "warn": T["warn"]}[kind]
        sim_pill.configure(text="  ●  %s  " % text, bg=bg, fg=fg)
        was = st.get("sim"); st["sim"] = r
        if bool(r) != bool(was) or "sim_shown" not in st:
            st["sim_shown"] = bool(r)
            if r: simban.pack(fill="x", padx=20, pady=(12, 0), before=ban if view["adv"] else simple_outer)
            else: simban.pack_forget()
        apply_sim_lock()

    side = ttk.Frame(body, width=250); side.pack(side="right", fill="y", padx=(14, 0))
    main = ttk.Frame(body); main.pack(side="left", fill="both", expand=True)

    # presets card
    po, pi = card(main, "Presets", "Manual presets (adjusted for your goal). Your anti-aliasing, frame-generation and traffic choices are kept.")
    po.pack(fill="x", pady=(0, 12))
    prow = ttk.Frame(pi, style="Card.TFrame"); prow.grid(row=2, column=0, columnspan=4, sticky="we")
    _pbtns = []
    for k_, name in enumerate(PRESETS):
        b = ttk.Button(prow, text=name, style="Preset.TButton", command=lambda n=name: (st.__setitem__("hw", None), load_preset(n)))
        b.grid(row=0, column=k_, padx=(0, 6), sticky="w"); _pbtns.append(b)
    _adb = ttk.Button(prow, text="✦ Auto-detect", style="Primary.TButton", command=lambda: auto_detect())
    prow.columnconfigure(len(_pbtns), weight=1)
    _pmode = {"wrap": None}
    def _preset_wrap(e=None):
        # v1.3.1: on narrow windows Auto-detect moves under the presets instead of being cut off
        need = sum(b.winfo_reqwidth() + 6 for b in _pbtns) + _adb.winfo_reqwidth() + 8
        wrap = prow.winfo_width() < need
        if wrap == _pmode["wrap"]: return
        _pmode["wrap"] = wrap
        if wrap: _adb.grid(row=1, column=0, columnspan=len(_pbtns) + 1, sticky="w", pady=(6, 0))
        else: _adb.grid(row=0, column=len(_pbtns) + 1, sticky="e", pady=0)
    _preset_wrap(); prow.bind("<Configure>", _preset_wrap, add="+")
    pi.columnconfigure(0, weight=1)

    nb = ttk.Notebook(main); nb.pack(fill="both", expand=True)
    tabs = {}
    def scroll_tab(title):
        outer = ttk.Frame(nb); nb.add(outer, text=title)
        cv = tk.Canvas(outer, bg=T["bg"], highlightthickness=0); sb = ttk.Scrollbar(outer, command=cv.yview)
        inner = ttk.Frame(cv, padding=(0, 12, 8, 12))
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        cv.configure(yscrollcommand=sb.set); cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        def wheel(e):
            d = -1 if (getattr(e, "num", 0) == 4 or e.delta > 0) else 1
            cv.yview_scroll(d * 2, "units")
        cv.bind("<Enter>", lambda e: (cv.bind_all("<MouseWheel>", wheel), cv.bind_all("<Button-4>", wheel), cv.bind_all("<Button-5>", wheel)))
        cv.bind("<Leave>", lambda e: (cv.unbind_all("<MouseWheel>"), cv.unbind_all("<Button-4>"), cv.unbind_all("<Button-5>")))
        return inner
    tabs["ingame"] = scroll_tab("  In-game settings  ")
    tabs["advanced"] = scroll_tab("  Advanced (beyond menu)  ")
    clean_tab = scroll_tab("  Clean up  ")

    # side actions card
    ao, ai = card(side, "Actions"); ao.pack(fill="x")
    for text, style, fn in (("Apply changes", "Primary.TButton", lambda: apply()),
                            ("Reload from file", "Secondary.TButton", lambda: load(st["path"])),
                            ("Saved profiles…", "Secondary.TButton", lambda: profiles_dialog()),
                            ("Review backups…", "Secondary.TButton", lambda: backups_dialog()),
                            ("Open backups folder", "Secondary.TButton",
                             lambda: st["path"] and open_folder(backup_dir(st["path"]))),
                            ("Restore latest backup", "Danger.TButton", lambda: restore(True)),
                            ("Restore a backup…", "Danger.TButton", lambda: restore(False))):
        ab_ = ttk.Button(ai, text=text, style=style, command=fn); ab_.grid(sticky="we", pady=4, column=0, columnspan=4)
        if text in ("Apply changes", "Restore latest backup", "Restore a backup…"): sim_lock(ab_)
    ai.columnconfigure(0, weight=1)
    ttk.Label(ai, text="Every write asks first. A timestamped backup is kept, with a before/after note. Preset is set to Custom.",
              style="Muted.Card.TLabel", wraplength=200, justify="left").grid(sticky="w", pady=(8, 0), column=0)
    io, ii = card(side, "Frame generation"); io.pack(fill="x", pady=12)
    ttk.Label(ii, style="Muted.Card.TLabel", wraplength=200, justify="left", text=FRAME_GEN_NOTE).grid(sticky="w", column=0)

    def add_row(parent, r, path, label, kind, spec, tip):
        cur = st["cfg"].get(path)
        lab = ttk.Label(parent, text=label, style="Card.TLabel"); lab.grid(row=r, column=0, sticky="w", pady=5, padx=(0, 12))
        extra = saved_setting_suffix(path, cur)
        Tip(lab, tip + (("\n\n" + extra[0].upper() + extra[1:] + ". A saved setting does not prove it is running.") if extra else "") + "\n\nKey: " + path)
        ttk.Label(parent, text=in_file_label(path, cur, kind, spec), style="Muted.Card.TLabel", width=14).grid(row=r, column=1, sticky="w")
        cell = ttk.Frame(parent, style="Card.TFrame"); cell.grid(row=r, column=2, sticky="we")
        if kind == "choice":
            inv = {str(v): k for k, v in spec.items()}
            var = tk.StringVar(value=inv.get(cur, cur))
            w = ttk.Combobox(cell, textvariable=var, values=list(spec.keys()), width=16, state="readonly"); w.pack(side="left")
        elif kind == "text":
            var = tk.StringVar(value=cur); w = ttk.Entry(cell, textvariable=var, width=14); w.pack(side="left")
            ttk.Checkbutton(cell, text="Change display resolution", variable=res_opt, style="Card.TCheckbutton").pack(side="left", padx=10)
        else:
            lo, hi, step = spec
            var = tk.DoubleVar(value=float(cur)); disp = tk.StringVar()
            fmt = (lambda v: "%d" % round(v)) if kind == "int" or step >= 1 else (lambda v: "%.2f" % v)
            def on(v, var=var, disp=disp, step=step, fmt=fmt):
                q = round(float(v) / step) * step; var.set(round(q, 4)); disp.set(fmt(q))
            w = ttk.Scale(cell, from_=lo, to=hi, variable=var, orient="horizontal", length=300, command=on)
            w.pack(side="left"); on(float(cur))
            var.trace_add("write", lambda *_a, var=var, disp=disp, fmt=fmt: disp.set(fmt(float(var.get()))))
            ttk.Label(cell, textvariable=disp, style="Value.Card.TLabel", width=6).pack(side="left", padx=10)
            ttk.Label(cell, text="%s – %s" % (fmt(lo), fmt(hi)), style="Muted.Card.TLabel").pack(side="left")
        Tip(w, tip + (("\n\n" + extra[0].upper() + extra[1:] + ". A saved setting does not prove it is running.") if extra else ""))
        if extra:
            ttk.Label(cell, text=extra, style="Muted.Card.TLabel").pack(side="left", padx=(8, 0))
        st["vars"].setdefault(path, []).append((kind, spec, var))
        if path in FG_DEPENDENT:
            hv = tk.StringVar(); ttk.Label(cell, textvariable=hv, style="Muted.Card.TLabel").pack(side="left", padx=10)
            st.setdefault("rows", {}).setdefault(path, []).append({"label": lab, "widget": w, "hint": hv})

    def build_rows():
        for t in tabs.values():
            for w in t.winfo_children(): w.destroy()
        st["vars"].clear(); st["rows"] = {}; cfg = st["cfg"]
        present = [x for x in SETTINGS if cfg.get(x[0]) is not None]
        buckets = {t: [] for t, _ in INGAME_CARDS}; adv = []
        for sdef in present:
            group = sdef[2]
            if group == "advanced": adv.append(sdef); continue
            for title, pred in INGAME_CARDS:
                if pred(sdef[0]): buckets[title].append(sdef); break
        def emit(parent, title, sub, items):
            if not items: return
            o, i = card(parent, title, sub); o.pack(fill="x", pady=(0, 12))
            hdr_r = 2
            for col, txt in ((0, "SETTING"), (1, "IN FILE"), (2, "NEW VALUE")):
                ttk.Label(i, text=txt, style="Muted.Card.TLabel").grid(row=hdr_r, column=col, sticky="w")
            i.columnconfigure(2, weight=1)
            for n, (path, label, group, kind, spec, tip) in enumerate(items):
                add_row(i, hdr_r + 1 + n, path, label, kind, spec, tip)
        subs = {"Display & upscaling": "Anti-aliasing, render scaling, frame generation. Resolution only changes if you opt in.",
                "Traffic & population": "Biggest CPU cost at busy airports – lower these first to hold 30+ FPS.",
                "Scenery & detail": "LODs, textures and procedural scenery.",
                "Lighting, clouds & effects": "Mostly GPU-bound settings."}
        for title, _ in INGAME_CARDS: emit(tabs["ingame"], title, subs[title], buckets[title])
        emit(tabs["advanced"], "Beyond the in-game menu",
             "Values outside menu limits. Big performance cost; the sim may clamp them if you touch the menu.", adv)
        for kind, spec, var in st["vars"].get("Video/FrameGeneration", []):
            var.trace_add("write", lambda *_a: sync_fg_rows())
        sync_fg_rows()

    def sync_fg_rows():
        """v1.3.1: frame-gen-only controls (the multiplier) are greyed out and not written while Frame generation is Off."""
        ent = st["vars"].get("Video/FrameGeneration")
        fgv = ent[0][2].get() if ent else "Off"
        state = fg_dependent_state(fgv, (st.get("hw") or {}).get("gpu"))
        for path in FG_DEPENDENT:
            for row in st.get("rows", {}).get(path, []):
                w = row["widget"]
                if state["enabled"]:
                    w.configure(state="readonly", values=state["multipliers"] or list(FG_MULT_LABELS))
                    row["label"].configure(style="Card.TLabel")
                else:
                    w.configure(state="disabled"); row["label"].configure(style="Muted.Card.TLabel")
                row["hint"].set(state["hint"])
        st["fg_state"] = state
    st["sync_fg_rows"] = sync_fg_rows

    def set_var(path, v):
        for kind, spec, var in st["vars"].get(path, []):
            if kind == "choice":
                inv = {str(x): k for k, x in spec.items()}; var.set(inv.get(str(v), str(v)))
            else: var.set(v)
    def collect():
        out = {}
        for path, entries in st["vars"].items():
            cur = st["cfg"].get(path); pick = None
            for kind, spec, var in entries:
                v = var.get()
                if kind == "choice": v = spec.get(v, v)
                if pick is None or format_value(KINDS[path], v) != cur: pick = v
            out[path] = pick
        if "Video/FrameGeneration" in st["cfg"].index:
            fg = out.get("Video/FrameGeneration", choices()[1])
            if fg == "NONE":
                out.pop("Video/NBFramesToGenerate", None)
                set_var("Video/NBFramesToGenerate", 1)
            else:
                gpu_name = (st.get("hw") or {}).get("gpu")
                max_mult = frame_generation_multiplier_limit(fg, gpu_name)
                try: mult = int(float(out.get("Video/NBFramesToGenerate", 1)))
                except (TypeError, ValueError): mult = 1
                safe_mult = max(1, min(mult, max_mult))
                out["Video/NBFramesToGenerate"] = safe_mult
                if safe_mult != mult: set_var("Video/NBFramesToGenerate", safe_mult)
        elif "Video/DLSSG" in st["cfg"].index:
            # MSFS 2020: frame generation is the boolean Video/DLSSG
            out["Video/DLSSG"] = 1 if choices()[1] == "DLSSG" else 0
        for path in st.get("held") or ():
            out.pop(path, None)
        return out

    def load(p):
        if not p: return
        prob = cfg_problem(p)
        if prob:
            bs = list_backups(p) if os.path.isdir(os.path.dirname(p)) else []
            set_status("Settings file is %s." % prob.split(" (")[0], "err")
            if bs and messagebox.askyesno(SHORT_NAME, "Your simulator settings file is %s:\n%s\n\nSkyTune has a backup from %s. "
                                          "Put it back now? (The current file is kept as a backup too.)" % (prob, p, os.path.basename(bs[-1]))):
                repaired = apply_restore(p, bs[-1], reason="repair")
                if not repaired["ok"]:
                    messagebox.showerror(SHORT_NAME, repaired["error"]); return
                return load(p)
            messagebox.showinfo(SHORT_NAME, "Your simulator settings file is %s:\n%s\n\nStart the simulator once, wait for the main "
                                "menu, then quit it normally – it writes a fresh file. Then click “Find file”." % (prob, p))
            return
        try: st["cfg"] = UserCfg.load(p); st["path"] = p
        except Exception as e:
            messagebox.showerror(APP_NAME, "That file could not be read.\n\n%s\n\nNext: pick UserCfg.opt with Browse, or start the simulator once and quit so it writes a fresh file." % plain_error(e))
            set_status("That settings file could not be read.", "err"); return
        remember_cfg(p)
        st["edition"] = detect_simulator_version(p, st["cfg"])
        st["active_profile"] = None
        refresh_creator_row()
        refresh_drift()
        refresh_reset()
        refresh_bindings()
        refresh_health()
        path_var.set(p); build_rows()
        refresh_mods()
        apply_gpu_limits((st.get("hw") or {}).get("gpu"))
        edition_label = {"2020": "MSFS 2020", "2024": "MSFS 2024", "unknown": "compatible/unknown MSFS config"}.get(st["edition"], "MSFS")
        set_status("Loaded %s (%d supported settings)" % (edition_label, sum(1 for x in SETTINGS if x[0] in st["cfg"].index)))
        refresh_summary()
        if st.get("cleaner_built"):
            for child in clean_tab.winfo_children(): child.destroy()
            build_cleaner(clean_tab); st["cleaner_built"] = True

    def choose_detected_config(found):
        if not found: return
        if len(found) == 1:
            label, path = found[0]; load(path)
            set_status("Found %s. Next: click Check my PC. Nothing is written until you confirm." % label); return
        dlg = tk.Toplevel(root); dlg.title("Choose simulator installation"); dlg.configure(bg=T["bg"]); dlg.transient(root)
        wrap = ttk.Frame(dlg, padding=16); wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="More than one MSFS settings file was found.", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(wrap, text="Choose which install SkyTune should optimise:", style="Muted.Card.TLabel").pack(anchor="w", pady=(4, 8))
        lb = tk.Listbox(wrap, width=74, height=min(6, len(found)), bg=T["field"], fg=T["text"], selectbackground=T["accent_dk"],
                        relief="flat", highlightthickness=1, highlightbackground=T["border"])
        for label, path in found: lb.insert("end", "%s — %s" % (label, path))
        lb.selection_set(0); lb.pack(fill="both", expand=True)
        def accept(_=None):
            choice = lb.curselection()
            if not choice: return
            label, path = found[choice[0]]; dlg.destroy(); load(path); set_status("Selected %s – %s" % (label, path))
        bb = ttk.Frame(wrap); bb.pack(fill="x", pady=(10, 0))
        ttk.Button(bb, text="Cancel", style="Secondary.TButton", command=dlg.destroy).pack(side="right")
        ttk.Button(bb, text="Use selected install", style="Primary.TButton", command=accept).pack(side="right", padx=8)
        lb.bind("<Double-Button-1>", accept)
        dlg.geometry("820x340")

    def autodetect_async():
        """v1.3.2: 'Find file' scans the usual places (and Steam libraries) on a worker thread."""
        try: find_btn.state(["disabled"])
        except tk.TclError: pass
        def done(found):
            try: find_btn.state(["!disabled"])
            except tk.TclError: pass
            autodetect(found)
        run_bg(detect_usercfgs, done, "Looking for your settings file…", lambda e: (find_btn.state(["!disabled"]), autodetect([])))
    def autodetect(found=None):
        found = detect_usercfgs() if found is None else found
        if found: choose_detected_config(found)
        else:
            set_status("No settings file yet. Next: start the sim once, quit it, then click Find file. Or use Browse.", "warn")
            messagebox.showinfo(APP_NAME, "SkyTune couldn't find a UserCfg.opt for MSFS 2020 or 2024.\n\n"
                                "Next: start the simulator, reach the main menu, and quit. Then click Find file.\n"
                                "If the sim is installed in a custom folder, click Browse and pick UserCfg.opt.")

    def open_help():
        dlg = tk.Toplevel(root); dlg.title("Help – SkyTune"); dlg.configure(bg=T["bg"]); dlg.transient(root)
        dlg.geometry("720x560+%d+%d" % (root.winfo_rootx() + 80, root.winfo_rooty() + 40))
        wrap = ttk.Frame(dlg, padding=16); wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Help", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(wrap, text="Three steps. Nothing is written until you click Yes, write.", style="Muted.Card.TLabel").pack(anchor="w", pady=(2, 8))
        box = tk.Text(wrap, wrap="word", bg=T["card"], fg=T["text"], font=FONT, relief="flat", padx=12, pady=10, highlightthickness=0)
        box.pack(fill="both", expand=True)
        for title, body in HELP_PAGES:
            box.insert("end", title + "\n", "head")
            box.insert("end", body + "\n\n")
        box.tag_configure("head", font=(F, 12, "bold"), foreground=T["accent_hi"])
        box.config(state="disabled")
        ttk.Button(wrap, text="Close", style="Secondary.TButton", command=dlg.destroy).pack(anchor="e", pady=(10, 0))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
    root.bind("<Alt-h>", lambda e: open_help()); root.bind("<Alt-H>", lambda e: open_help())

    def open_frame_hold():
        if not st.get("cfg"):
            messagebox.showinfo(SHORT_NAME, "Load your UserCfg.opt first. Click Find file, or Browse.")
            return
        cfg = st["cfg"]
        if TERRAIN_LOD not in cfg.index and OBJECT_LOD not in cfg.index:
            messagebox.showinfo(SHORT_NAME, "This settings file has no terrain or object detail line SkyTune can use.")
            return
        def num(path, default):
            raw = cfg.get(path)
            try: return float(raw)
            except (TypeError, ValueError): return default
        hold = FrameHold()
        hold.start(num(TERRAIN_LOD, 1.0), num(OBJECT_LOD, 1.0))
        dlg = tk.Toplevel(root); dlg.title("Frame Hold – SkyTune"); dlg.configure(bg=T["bg"]); dlg.transient(root)
        dlg.geometry("640x560+%d+%d" % (max(0, root.winfo_rootx() + 70), max(0, root.winfo_rooty() + 30)))
        wrap = ttk.Frame(dlg, padding=16); wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="Frame Hold", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(wrap, text=FRAME_HOLD_WARNING, style="Muted.Card.TLabel", wraplength=590, justify="left").pack(anchor="w", pady=(6, 10))
        form = ttk.Frame(wrap); form.pack(fill="x")
        fields = {}
        def add_row(row, label, key, value):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=value)
            ttk.Entry(form, textvariable=var, width=12).grid(row=row, column=1, sticky="w", padx=(8, 0))
            fields[key] = var
        add_row(0, "Target frames per second", "target", "30")
        add_row(1, "Terrain detail minimum (10–800)", "tlo", "50")
        add_row(2, "Terrain detail maximum (10–800)", "thi", "200")
        add_row(3, "Object detail minimum (10–400)", "olo", "50")
        add_row(4, "Object detail maximum (10–400)", "ohi", "150")
        add_row(5, "Ground altitude, feet", "ground", "2000")
        add_row(6, "Cruise altitude, feet", "cruise", "10000")
        alt_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Lower detail near the ground, higher detail in cruise", variable=alt_on).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 2))
        add_row(8, "Frame rate you see now (blank if unknown)", "fps", "")
        add_row(9, "Altitude now, feet (blank if unknown)", "altitude", "")
        result = tk.StringVar(value="Enter a frame rate when you have one. SkyTune will not guess.")
        ttk.Label(wrap, textvariable=result, style="Card.TLabel", wraplength=590, justify="left").pack(anchor="w", pady=(10, 6))
        latest = {"value": None}
        def blank(key):
            text = fields[key].get().strip()
            return None if text == "" else text
        def calculate():
            try:
                session = FrameHold(target_fps=fields["target"].get(),
                                    terrain=(float(fields["tlo"].get()) / 100.0, float(fields["thi"].get()) / 100.0),
                                    objects=(float(fields["olo"].get()) / 100.0, float(fields["ohi"].get()) / 100.0),
                                    altitude_mode=bool(alt_on.get()),
                                    ground_ft=fields["ground"].get(), cruise_ft=fields["cruise"].get())
                session.start(hold.original[0], hold.original[1])
                session.current = hold.current
                sample = session.update(fps=blank("fps"), altitude_ft=blank("altitude"))
            except (TypeError, ValueError) as exc:
                result.set(plain_error(exc)); return
            hold.current = session.current
            hold.terrain_range, hold.object_range = session.terrain_range, session.object_range
            hold.target, hold.altitude_mode = session.target, session.altitude_mode
            hold.ground_ft, hold.cruise_ft, hold.step = session.ground_ft, session.cruise_ft, session.step
            latest["value"] = sample
            result.set("Terrain detail %d. Object detail %d. %s Nothing is written yet." % (
                sample["terrain_menu"], sample["objects_menu"], sample["reason"]))
        def use_values():
            if latest["value"] is None:
                result.set("Calculate first. Nothing was written."); return
            blocked = frame_hold_block(sim_running())
            if blocked:
                result.set(blocked)
                return
            chosen = frame_hold_values(latest["value"], st["cfg"])
            if not chosen:
                result.set("This file has no terrain or object detail line to fill."); return
            for path, value in chosen.items():
                set_var(path, value)
            refresh_summary()
            result.set("Those numbers are on the list. Click Optimise, then Yes, write. Nothing is written yet.")
        def close():
            hold.stop()
            if st.get("cfg"):
                for path in (TERRAIN_LOD, OBJECT_LOD):
                    raw = st["cfg"].get(path)
                    if raw is None: continue
                    try: set_var(path, float(raw))
                    except ValueError: set_var(path, raw)
                refresh_summary()
            dlg.destroy()
        buttons = ttk.Frame(wrap); buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Calculate", style="Primary.TButton", command=calculate).pack(side="left")
        ttk.Button(buttons, text="Use these values", command=use_values).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", style="Secondary.TButton", command=close).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda e: close())

    def browse():
        p = filedialog.askopenfilename(title="Select UserCfg.opt", filetypes=[("UserCfg", "*.opt"), ("All", "*.*")])
        if p: load(p)

    def load_preset(name, values=None):
        if not st["cfg"]: set_status("Load a UserCfg.opt first.", "warn"); return
        st["active_profile"] = None
        st["creator"] = None
        if creator_var.get() != CREATOR_NONE: creator_var.set(CREATOR_NONE)
        cur_preset["name"] = name
        vals = values if values is not None else goal_adjust(PRESETS[name], goal_var.get(), PRESET_SCORE.get(name, 2))
        for path, v in with_user_choices(vals, *choices(), traffic=traffic_choices(), gpu_name=(st.get("hw") or {}).get("gpu")).items(): set_var(path, v)
        disp = "Balanced" if name == "Balanced-30" else name
        refresh_summary()
        set_status("'%s' is ready – check “What will change”, then click Apply." % disp, "info")

    def auto_detect(popup=True, then=None, fresh=False):
        """v1.3.2: uses the remembered check from this PC (instant) unless fresh=True ('Re-check'); a real check runs
        on a worker thread with a spinner, so the window stays responsive while Windows is asked about the hardware."""
        if not demo_hw and not fresh:
            hw_, when_ = load_hw_cache()
            if hw_:
                st["hw_when"] = when_; show_reco(hw_, popup=popup); then and then(); return
        if st.get("hw_job"): return                  # a check is already running – its result will show up
        st["hw_job"] = True; reco_var.set("Checking your PC…")
        try: check_btn.state(["disabled"])
        except (NameError, tk.TclError): pass
        def done(hw):
            st["hw_job"] = False
            try: check_btn.state(["!disabled"])
            except (NameError, tk.TclError): pass
            if not demo_hw: save_hw_cache(hw); st["hw_when"] = datetime.datetime.now()
            show_reco(hw, popup=popup); then and then()
        def fail(e):
            st["hw_job"] = False
            try: check_btn.state(["!disabled"])
            except (NameError, tk.TclError): pass
            reco_var.set("Couldn't check this PC. Next: click “Wrong graphics card?” and pick it.")
            set_status(plain_error(e), "err")
        run_bg(lambda: dict(DEMO_HW) if demo_hw else detect_hardware(), done, "Checking your PC…", fail)

    def show_reco(hw, popup=True):
        st["hw"] = hw; root.after_idle(update_steps)
        preset, values, score, reasons, tech = plan(hw, goal_var.get())
        disp = "Balanced" if preset == "Balanced-30" else preset
        apply_gpu_limits(hw.get("gpu"))
        load_preset(preset, values=values)
        bits = [hw.get("gpu") or "Unknown graphics card"]
        if hw.get("vram_gb"): bits[0] += " (%g GB)" % round(hw["vram_gb"], 1)
        if hw.get("cpu"): bits.append(hw["cpu"])
        if hw.get("ram_gb"): bits.append("%s GB memory" % hw["ram_gb"])
        if hw.get("width"): bits.append("%s × %s screen" % (hw["width"], hw["height"]))
        sim = {"2020": "MSFS 2020", "2024": "MSFS 2024"}.get(st.get("edition"), "")
        note = ("  ·  " + hw_cache_note(st.get("hw_when"))) if hw.get("cached") and st.get("hw_when") else ""
        reco_var.set("✓ %s%s%s\nYour PC suits the “%s” level for “%s”. See Step 3." %
                     ("  ·  ".join(bits), ("  ·  found " + sim) if sim and st.get("cfg") else "", note, disp, goal_var.get()))
        set_status("Settings for '%s' are ready – nothing is saved until you click “Optimise my sim”." % goal_var.get(), "info")
        if not popup: return
        dlg = tk.Toplevel(root); dlg.title("Auto-detect – recommended settings"); dlg.configure(bg=T["bg"])
        dlg.transient(root); dlg.geometry("680x640+%d+%d" % (root.winfo_rootx() + 140, root.winfo_rooty() + 90))
        try: dlg.iconbitmap(resource_path("app.ico")) if os.name == "nt" else None
        except Exception: pass
        wrap = ttk.Frame(dlg, padding=18); wrap.pack(fill="both", expand=True)
        ho, hi = card(wrap, "Detected hardware"); ho.pack(fill="x")
        rows = [("GPU", hw["gpu"]), ("VRAM", "%.1f GB  (%s)" % (hw["vram_gb"], hw.get("vram_src") or "n/a")),
                ("CPU", "%s  ·  %s cores / %s threads" % (hw["cpu"], hw["cores"], hw["threads"])),
                ("RAM", "%s GB" % hw["ram_gb"]), ("Display", "%s × %s" % (hw["width"], hw["height"]))]
        for n, (k, v) in enumerate(rows):
            ttk.Label(hi, text=k, style="Muted.Card.TLabel").grid(row=2 + n, column=0, sticky="w", padx=(0, 16), pady=2)
            ttk.Label(hi, text=v, style="Card.TLabel").grid(row=2 + n, column=1, sticky="w")
        ro, ri = card(wrap, "What SkyTune chose – goal: " + goal_var.get()); ro.pack(fill="x", pady=12)
        pill = tk.Label(ri, text="  %s  " % (disp + (" · 30+ FPS tuned" if preset == "Balanced-30" else "")), bg=T["accent_dk"], fg="#ffffff", font=(F, 13, "bold"), pady=4)
        pill.grid(row=2, column=0, sticky="w")
        ttk.Label(ri, text="score %d / 4" % score, style="Muted.Card.TLabel").grid(row=2, column=1, sticky="w", padx=12)
        for n, r in enumerate(reasons):
            ttk.Label(ri, text="•  " + r, style="Card.TLabel", wraplength=560, justify="left").grid(
                row=3 + n, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(ri, text="Loaded into SkyTune – nothing is written until you click Apply.",
                  style="Muted.Card.TLabel").grid(row=19, column=0, columnspan=4, sticky="w", pady=(8, 0))
        if hw.get("errors"):
            for n, e in enumerate(hw["errors"]):
                tk.Label(ri, text="⚠  " + e, bg=T["card"], fg=T["warn"], font=FONT_S, wraplength=560,
                         justify="left").grid(row=20 + n, column=0, columnspan=4, sticky="w", pady=2)
        bb = ttk.Frame(wrap); bb.pack(fill="x")
        ttk.Button(bb, text="OK", style="Primary.TButton", command=dlg.destroy).pack(side="right")
        ttk.Button(bb, text="Pick my GPU…", style="Secondary.TButton",
                   command=lambda: (dlg.destroy(), pick_gpu_dialog(hw))).pack(side="right", padx=8)

    def pick_gpu_dialog(hw):
        d = tk.Toplevel(root); d.title("Pick my graphics card"); d.configure(bg=T["bg"]); d.transient(root)
        w = ttk.Frame(d, padding=18); w.pack(fill="both", expand=True)
        o, i = card(w, "Which graphics card do you have?", "Use this if auto-detect got it wrong or found nothing."); o.pack(fill="x")
        gv = tk.StringVar(value=MANUAL_GPUS[7][0]); vv = tk.StringVar(value="8"); lv = tk.BooleanVar(value=False)
        ttk.Combobox(i, textvariable=gv, values=[l for l, _, _ in MANUAL_GPUS], width=58, state="readonly").grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(i, text="Video memory (GB)", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(i, textvariable=vv, values=["2", "4", "6", "8", "10", "12", "16", "20", "24", "32"], width=6, state="readonly").grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(i, text="It's a laptop graphics chip", variable=lv, style="Card.TCheckbutton").grid(row=4, column=0, columnspan=2, sticky="w", pady=4)
        def ok():
            d.destroy(); h_ = manual_hw(hw, gv.get(), float(vv.get()), lv.get())
            if not demo_hw: save_hw_cache(h_)                # v1.3.2: remember the card you picked
            h_.pop("cached", None); show_reco(h_)
        ttk.Button(w, text="Use this card", style="Primary.TButton", command=ok).pack(side="right", pady=(12, 0))

    def sim_check():
        r = sim_running()
        if r:
            set_status("Microsoft Flight Simulator is still running – nothing was changed.", "err")
            messagebox.showerror(SHORT_NAME, "Microsoft Flight Simulator 2020/2024 is still running.\n\nPlease close it completely "
                                 "(if it's stuck, end FlightSimulator2024.exe in Task Manager) and try again.\nNothing was changed."); return False
        if r is None:
            return messagebox.askyesno(APP_NAME, "Could not check whether the sim is running. Continue anyway?")
        return True

    def stage_profile(prof):
        """Put a saved profile into the pending settings. Does not write the simulator file."""
        plan = profile_apply_plan(st["cfg"], prof)
        if prof.get("goal") in GOALS:
            goal_var.set(prof["goal"]); goal_blurb.set(GOAL_BLURB[prof["goal"]]); remember(goal=prof["goal"])
        for path, val in plan["values"].items(): set_var(path, val)
        aa_inv = {v: k for k, v in AA_CHOICES.items()}
        if plan["values"].get("Video/AntiAliasing") in aa_inv: aa_var.set(aa_inv[plan["values"]["Video/AntiAliasing"]])
        fg_inv = {v: k for k, v in active_fg_choices().items()}
        if plan["values"].get("Video/FrameGeneration") in fg_inv: fg_var.set(fg_inv[plan["values"]["Video/FrameGeneration"]])
        elif "Video/DLSSG" in plan["values"]:
            fg_var.set("NVIDIA DLSS FG" if str(plan["values"]["Video/DLSSG"]) in ("1", "1.0") else "Off")
        levels = [prof["values"][p] for p, _l, _t in TRAFFIC_CATS if p in (prof.get("values") or {})]
        if levels and all(x == levels[0] for x in levels):
            tr_inv = {v: k for k, v in TRAFFIC_LEVELS.items() if v is not None}
            if levels[0] in tr_inv: tr_all.set(tr_inv[levels[0]])
        upd_psum()
        if st.get("sync_fg_rows"): st["sync_fg_rows"]()
        st["active_profile"] = {"name": prof["name"], "edition": prof.get("edition"), "id": prof.get("id")}
        remember(aa=aa_var.get(), fg=fg_var.get(), traffic=tr_all.get())
        refresh_summary()
        return plan

    def _dialog_geom(d, w, h):
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        w_, h_ = min(w, max(520, sw - 40)), min(h, max(420, sh - 80))
        x_ = max(0, min(root.winfo_rootx() + 48, sw - w_ - 8)); y_ = max(0, min(root.winfo_rooty() + 28, sh - h_ - 8))
        d.geometry("%dx%d+%d+%d" % (w_, h_, x_, y_)); d.minsize(min(520, w_), min(420, h_))

    def profiles_dialog():
        """v1.4.0: named setups stored beside state.json. Use prepares changes; Optimise still asks before writing."""
        if not st.get("cfg"): set_status("Load a settings file first.", "warn"); return None
        d = tk.Toplevel(root); d.title("Saved profiles – SkyTune"); d.configure(bg=T["bg"]); d.transient(root)
        _dialog_geom(d, 760, 560); st["profiles_win"] = d
        wrap = ttk.Frame(d, padding=16); wrap.pack(fill="both", expand=True)
        o, i = card(wrap, "Saved profiles", "A profile is a named graphics setup kept on this PC. It does not include your screen "
                    "resolution or API key. Using one only fills in Step 3 — SkyTune still asks before it writes.")
        o.pack(fill="both", expand=True); i.columnconfigure(0, weight=1); i.rowconfigure(3, weight=1)
        lb = tk.Listbox(i, height=8, bg=T["field"], fg=T["text"], selectbackground=T["accent_dk"], relief="flat",
                        highlightthickness=1, highlightbackground=T["border"], activestyle="none", font=FONT, exportselection=False)
        lb.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=(4, 8))
        detail = tk.StringVar(value="Save the settings now on screen, or select a profile to use it.")
        autowrap(ttk.Label(i, textvariable=detail, style="Muted.Card.TLabel", wraplength=680, justify="left"), i, 36).grid(
            row=4, column=0, columnspan=4, sticky="w")
        name_var, note_var = tk.StringVar(), tk.StringVar()
        form = ttk.Frame(i, style="Card.TFrame"); form.grid(row=5, column=0, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Label(form, text="Name", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(form, textvariable=name_var, width=28).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="Note", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 8))
        ttk.Entry(form, textvariable=note_var, width=36).grid(row=0, column=3, sticky="we"); form.columnconfigure(3, weight=1)
        holder = {"items": []}
        def current():
            sel = lb.curselection()
            if not sel or sel[0] >= len(holder["items"]): return None
            return holder["items"][sel[0]]
        def show_detail(_=None):
            p = current()
            if not p:
                detail.set("Save the settings now on screen, or select a profile to use it."); return
            when = (p.get("created") or "")[:16].replace("T", " ")
            detail.set("%s  ·  saved %s\n%s" % (p["name"], when or "earlier", p.get("note") or "No note."))
            name_var.set(p["name"]); note_var.set(p.get("note") or "")
        def refresh_list(select_id=None):
            holder["items"] = list_profiles(); lb.delete(0, "end")
            for p in holder["items"]:
                ed = {"2020": "MSFS 2020", "2024": "MSFS 2024"}.get(p.get("edition") or "", "any sim")
                lb.insert("end", "%s   ·   %s   ·   %d settings" % (p["name"], ed, len(p.get("values") or {})))
            if select_id:
                for n, p in enumerate(holder["items"]):
                    if p.get("id") == select_id: lb.selection_set(n); lb.activate(n); break
            if holder["items"] and not lb.curselection():
                lb.selection_set(0); lb.activate(0)
            show_detail()
        lb.bind("<<ListboxSelect>>", show_detail)
        def do_save():
            try:
                prof = build_profile(name_var.get(), collect(), note=note_var.get(), goal=goal_var.get(),
                                      edition=st.get("edition"), source="pending")
            except ValueError as e:
                messagebox.showerror(SHORT_NAME, str(e), parent=d); return
            existing = [p for p in holder["items"] if p["name"].lower() == prof["name"].lower()]
            if existing and not messagebox.askyesno(SHORT_NAME, "Replace the saved profile \"%s\"?" % prof["name"], parent=d, default="no"):
                return
            try: saved = save_profile(prof, replace=bool(existing))
            except ValueError as e:
                messagebox.showerror(SHORT_NAME, str(e), parent=d); return
            extra = (" Left out: %s." % "; ".join(saved.get("rejected") or [])) if saved.get("rejected") else ""
            set_status("Saved profile \"%s\" on this PC (%d settings). The simulator file was not changed.%s" % (
                saved["name"], len(saved["values"]), extra))
            refresh_list(saved.get("id"))
        creator_pick = tk.StringVar(value="The loaded file")
        if st.get("edition") == "2024":
            pick_row = ttk.Frame(i, style="Card.TFrame"); pick_row.grid(row=6, column=0, columnspan=4, sticky="w", pady=(8, 0))
            ttk.Label(pick_row, text="Compare with", style="Card.TLabel").pack(side="left")
            ttk.Combobox(pick_row, textvariable=creator_pick, state="readonly", width=34,
                         values=("The loaded file",) + tuple(creator_presets("2024"))).pack(side="left", padx=(8, 0))
        def do_compare():
            p = current()
            if not p or not st.get("cfg"):
                set_status("Select a profile to compare.", "warn"); return
            chosen = creator_pick.get()
            if chosen in creator_presets("2024"):
                rows = creator_vs_profile(chosen, p)
                lines = ["Compared with %s. Nothing is written." % chosen, ""]
                if not rows: lines.append("The recognised settings match this creator setup.")
                else:
                    lines.append("%d setting%s differ:" % (len(rows), "" if len(rows) == 1 else "s"))
                    lines += ["• %s: %s → %s" % (a, b if b != "?" else "not in the setup", c if c != "?" else "not in the profile") for a, b, c in rows[:12]]
                detail.set("\n".join(lines)); return
            plan = profile_apply_plan(st["cfg"], p)
            lines = ["Compared with the file loaded now. Nothing is written.", ""]
            if not plan["changes"]:
                lines.append("The recognised settings already match.")
            else:
                lines.append("%d setting%s would change if you Use this profile:" % (len(plan["changes"]), "" if len(plan["changes"]) == 1 else "s"))
                lines += ["• %s: %s → %s" % (a, b, c) for a, b, c in plan["changes"][:12]]
            if plan["absent"]:
                lines.append("%d settings are not in this file, so they would be skipped." % len(plan["absent"]))
            detail.set("\n".join(lines))
        def do_use():
            p = current()
            if not p: set_status("Select a profile first.", "warn"); return
            plan = stage_profile(p); n = len(plan["changes"]); absent = plan["absent"]
            msg = "Profile \"%s\" is ready – %d setting%s will change. Check Step 3, then click Optimise. Nothing is written yet." % (
                p["name"], n, "" if n == 1 else "s")
            if absent: msg += " %d settings from the profile aren't in this file, so they were skipped." % len(absent)
            set_status(msg, "info")
            result_var.set("Profile \"%s\" is ready. Check the list, then click Optimise." % p["name"])
            result_lbl.configure(fg=T["accent"]); d.destroy()
        def do_delete():
            p = current()
            if not p: set_status("Select a profile first.", "warn"); return
            if not messagebox.askyesno(SHORT_NAME, "Delete the saved profile \"%s\"? This does not change the simulator." % p["name"],
                                       parent=d, default="no"): return
            delete_profile(profiles_dir(), p["id"])
            if (st.get("active_profile") or {}).get("id") == p["id"]:
                st["active_profile"] = None; refresh_summary()
            set_status("Deleted profile \"%s\"." % p["name"]); refresh_list()
        def do_import():
            path = filedialog.askopenfilename(parent=d, title="Import a SkyTune profile", filetypes=[("SkyTune profile", "*.json"), ("All", "*.*")])
            if not path: return
            prof, errs = read_profile_file(path)
            if not prof:
                messagebox.showerror(SHORT_NAME, errs[0] if errs else "That file isn't a SkyTune profile.", parent=d); return
            existing = [p for p in list_profiles() if p["name"].lower() == prof["name"].lower()]
            if existing and not messagebox.askyesno(SHORT_NAME, "Replace the saved profile \"%s\" with this file?" % prof["name"], parent=d, default="no"):
                return
            try: saved = save_profile(prof, replace=bool(existing))
            except ValueError as e:
                messagebox.showerror(SHORT_NAME, str(e), parent=d); return
            set_status("Imported \"%s\". Select it and click Use — nothing is written yet." % saved["name"]); refresh_list(saved.get("id"))
        def do_export():
            p = current()
            if not p: set_status("Select a profile to export.", "warn"); return
            dest = filedialog.asksaveasfilename(parent=d, title="Export profile", defaultextension=".json",
                                                 initialfile=profile_slug(p["name"]) + ".json", filetypes=[("SkyTune profile", "*.json")])
            if not dest: return
            export_profile(p, dest); set_status("Exported profile \"%s\"." % p["name"])
        bb = ttk.Frame(wrap); bb.pack(fill="x", pady=(12, 0))
        right = ttk.Frame(bb); right.pack(side="top", anchor="e")
        ttk.Button(right, text="Close", style="Secondary.TButton", command=d.destroy).pack(side="right")
        ttk.Button(right, text="Use", style="Primary.TButton", command=do_use).pack(side="right", padx=(0, 8))
        ttk.Button(right, text="Save", style="Primary.TButton", command=do_save).pack(side="right", padx=(0, 8))
        left = ttk.Frame(bb); left.pack(side="top", anchor="w", pady=(8, 0))
        ttk.Button(left, text="Export…", style="Secondary.TButton", command=do_export).pack(side="left")
        ttk.Button(left, text="Import…", style="Secondary.TButton", command=do_import).pack(side="left", padx=(8, 0))
        ttk.Button(left, text="Delete", style="Danger.TButton", command=do_delete).pack(side="left", padx=(8, 0))
        ttk.Button(left, text="Compare", style="Secondary.TButton", command=do_compare).pack(side="left", padx=(8, 0))
        refresh_list(); return d

    def backups_dialog():
        """v1.4.0: read a backup's before/after note, or the live difference, before restoring it."""
        if not st.get("path"): set_status("Load a settings file first.", "warn"); return None
        d = tk.Toplevel(root); d.title("Review backups – SkyTune"); d.configure(bg=T["bg"]); d.transient(root)
        _dialog_geom(d, 760, 560); st["backups_win"] = d
        wrap = ttk.Frame(d, padding=16); wrap.pack(fill="both", expand=True)
        o, i = card(wrap, "Review backups", "Each backup is your settings file from before a change. The list is the difference "
                    "between that backup and the file you have now. The whole file is restored, including settings SkyTune does not edit. "
                    "Restore asks first, then checks the file matches.")
        o.pack(fill="both", expand=True); i.columnconfigure(0, weight=1); i.rowconfigure(4, weight=1)
        lb = tk.Listbox(i, height=6, bg=T["field"], fg=T["text"], selectbackground=T["accent_dk"], relief="flat",
                        highlightthickness=1, highlightbackground=T["border"], activestyle="none", font=FONT, exportselection=False)
        lb.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        txt = tk.Text(i, height=12, bg=T["card"], fg=T["text"], relief="flat", font=FONT, wrap="word", highlightthickness=0, padx=4, pady=4)
        txt.grid(row=4, column=0, sticky="nsew", pady=(8, 0)); txt.tag_configure("muted", foreground=T["muted"])
        holder = {"items": []}
        def fill_review(_=None):
            txt.config(state="normal"); txt.delete("1.0", "end")
            sel = lb.curselection()
            if not sel:
                txt.insert("end", "No backups yet.\n\nSkyTune keeps one the first time you write settings.", "muted")
                txt.config(state="disabled"); return
            path = holder["items"][sel[0]]; plan = plan_restore(st["path"], path); saved = plan.get("saved_review") or {}
            if saved:
                why = saved.get("profile") or REASON_PLAIN.get(saved.get("reason"), saved.get("reason") or "change")
                txt.insert("end", "Saved note: %s\n" % why, "muted")
                if saved.get("verified"): txt.insert("end", "SkyTune checked that write after saving it.\n", "muted")
                txt.insert("end", "\n")
            else:
                txt.insert("end", "No saved note for this backup (it was made before review notes existed). The difference below is calculated now.\n\n", "muted")
            if not plan["ok"]: txt.insert("end", plan["error"])
            else:
                for warn in plan["warnings"]: txt.insert("end", "Note: %s\n" % warn)
                ch = plan["changes"]
                if not ch: txt.insert("end", "No recognised graphics settings differ from the current file.\n")
                else:
                    txt.insert("end", "Restoring would change %d setting%s:\n\n" % (len(ch), "" if len(ch) == 1 else "s"))
                    for lab, old, new in ch: txt.insert("end", "• %s: %s → %s\n" % (lab, old, new))
            txt.config(state="disabled")
        def refresh():
            holder["items"] = list(reversed(list_backups(st["path"]))); lb.delete(0, "end")
            for path in holder["items"]: lb.insert("end", backup_label(path, read_change_review(path)))
            if holder["items"]: lb.selection_set(0)
            fill_review()
        lb.bind("<<ListboxSelect>>", fill_review)
        def do_restore():
            sel = lb.curselection()
            if not sel: set_status("Select a backup first.", "warn"); return
            src = holder["items"][sel[0]]; d.destroy(); restore(False, src=src)
        bb = ttk.Frame(wrap); bb.pack(fill="x", pady=(12, 0))
        rb = ttk.Button(bb, text="Restore selected", style="Danger.TButton", command=do_restore); rb.pack(side="right")
        sim_lock(rb, Tip(rb, "Puts this backup back after you confirm. Your current file is saved first, and the result is checked."))
        ttk.Button(bb, text="Close", style="Secondary.TButton", command=d.destroy).pack(side="right", padx=(0, 8))
        refresh(); return d

    def apply_flight():
        name = scenario_var.get()
        if not st.get("cfg") or name not in SCENARIOS:
            st["scenario"] = None
            refresh_summary(); return
        locked = ["aa", "fg"]
        if tr_all.get() != "SkyTune decides": locked.append("traffic")
        vals, notes = scenario_adjust(collect(), name, st.get("hw"), locked=tuple(locked))
        for path, val in vals.items(): set_var(path, val)
        st["scenario"] = {"name": name, "notes": notes}
        refresh_summary()
        set_status("“%s” is ready in the list. Nothing is written until you confirm." % name, "info")
    def save_diagnostic():
        try: names = [p["name"] for p in list_profiles()]
        except Exception: names = []
        hw = st.get("hw") or {}
        keep = {k: hw.get(k) for k in ("gpu", "vram_gb", "cpu", "ram_gb", "width", "height", "errors")}
        try:
            text = build_diagnostic({
                "sim_running": st.get("sim"), "edition": st.get("edition"),
                "install": path_var.get() if st.get("path") else "not loaded",
                "problem": cfg_problem(st["path"]) if st.get("path") else "not loaded",
                "known_settings": sum(1 for sdef in SETTINGS if st.get("cfg") and sdef[0] in st["cfg"].index),
                "goal": goal_var.get(), "aa": aa_var.get(), "fg": fg_var.get(), "traffic": tr_all.get(),
                "scenario": (st.get("scenario") or {}).get("name") or scenario_var.get(),
                "profile_names": names,
                "backup_count": len(list_backups(st["path"])) if st.get("path") else 0,
                "bindings": ("%d found" % len(st.get("bindings") or [])) if st.get("bindings") else "Not found",
                "health": st.get("health") or read_health(st.get("path"), st.get("hw")),
                "hardware": keep})
        except ValueError as e:
            messagebox.showerror(SHORT_NAME, str(e)); return
        dest = filedialog.asksaveasfilename(title="Save SkyTune diagnostic", defaultextension=".txt",
                                            initialfile="SkyTune-diagnostic.txt", filetypes=[("Text", "*.txt")])
        if not dest: return
        try:
            with open(dest, "w", encoding="utf-8") as f: f.write(text)
        except OSError as e:
            messagebox.showerror(SHORT_NAME, "Couldn't save the diagnostic:\n%s" % e); return
        set_status("Diagnostic saved on this PC. It was not uploaded.")
    def save_support_pack():
        entries = build_support_pack(st.get("path"), st.get("edition"), st.get("hw"), st.get("health"))
        names = support_pack_names(entries)
        if not names:
            set_status("There is nothing to put in a support pack yet.", "warn"); return
        listing = "\n".join("• " + name for name in names)
        if not messagebox.askyesno(SHORT_NAME,
                                   "These files will be included:\n\n%s\n\nAccount names are written as <user>. Nothing is uploaded.\n\nSave this zip?" % listing,
                                   default="no"):
            set_status("Support pack cancelled. Nothing was saved.", "info"); return
        dest = filedialog.asksaveasfilename(title="Save SkyTune support pack", defaultextension=".zip",
                                            initialdir=support_pack_start_dir(), initialfile="SkyTune-support.zip",
                                            filetypes=[("Zip", "*.zip")])
        if not dest:
            return
        try:
            write_support_pack(dest, entries)
        except OSError as e:
            messagebox.showerror(SHORT_NAME, "Couldn't save the support pack:\n%s" % plain_error(e)); return
        set_status("Support pack saved on this PC. It was not uploaded.")
    def show_confirm_bar(text):
        yes_btn.configure(text="Yes, write" if (st.get("pending") or {}).get("kind") == "apply" else "Yes, restore")
        if not confirm_bar.winfo_ismapped():
            confirm_bar.pack(side="left", before=result_lbl)
        result_var.set(text); result_lbl.configure(fg=T["accent_hi"])
        result_tip.text = text
        try: confirm_bar.update_idletasks()
        except tk.TclError: pass
    def hide_confirm_bar():
        st["pending"] = None
        try:
            if confirm_bar.winfo_ismapped(): confirm_bar.pack_forget()
        except tk.TclError: pass
    def cancel_pending():
        hide_confirm_bar()
        set_status("Cancelled – nothing was written.", "info")
        result_var.set("Cancelled – your settings file was not changed."); result_lbl.configure(fg=T["muted"])
    def commit_pending():
        pending = st.get("pending")
        if not pending or not st.get("path") or not sim_check(): return
        kind = pending.get("kind")
        hide_confirm_bar()
        if kind == "restore":
            result = apply_restore(st["path"], pending.get("src"), reason="restore")
            if not result["ok"]:
                set_status(result["error"], "err"); messagebox.showerror(SHORT_NAME, result["error"])
                if os.path.isfile(st["path"]): load(st["path"])
                return
            save_last_apply(UserCfg.load(st["path"]), st.get("edition"))
            st["held"] = set()
            bind_note = ""
            if st.get("backup_bindings"):
                checked = restore_bindings(pending.get("src"), find_input_profiles())
                if checked.get("restored"): bind_note = " Bindings checked: %d." % len(checked["restored"])
                elif checked.get("error"): bind_note = " Control bindings: Not found."
            load(st["path"])
            set_status("Restored and checked – settings match %s.%s" % (os.path.basename(pending.get("src") or ""), bind_note))
            if not view["adv"]:
                result_tip.text = ""; st["optimised"] = False
                result_var.set("↶ Undone – your previous settings are back."); result_lbl.configure(fg=T["accent_hi"])
            else:
                messagebox.showinfo(SHORT_NAME, "Done – your previous settings are back, and SkyTune checked that the file matches the backup.")
            return
        before = UserCfg.load(st["path"]); cfg = UserCfg.load(st["path"])
        changed = apply_values(cfg, pending.get("values") or {}, change_resolution=pending.get("res"))
        if not changed:
            set_status("Nothing to change – your settings already match.", "info")
            result_var.set("Your settings already match – nothing to change."); result_lbl.configure(fg=T["ok"]); return
        rows = diff_known_settings(before, cfg)
        try:
            b = write_with_backup(cfg, st["path"], review={"reason": pending.get("reason") or "optimise", "changes": rows,
                                                           "edition": st.get("edition") or "unknown",
                                                           "profile": pending.get("profile") or "",
                                                           "warnings": pending.get("warnings") or ()})
            if st.get("backup_bindings"):
                backup_bindings(b, st.get("bindings") or find_input_profiles())
        except Exception as e:
            set_status("Couldn't save the settings file.", "err")
            messagebox.showerror(SHORT_NAME, plain_error(e) + "\n\nYour original file was not changed."); return
        plain = pending.get("plain") or []
        save_last_apply(UserCfg.load(st["path"]), st.get("edition"))
        st["held"] = set()
        load(st["path"])
        set_status("Done! %d settings changed · backup saved as %s" % (len(changed), os.path.basename(b)))
        if st.get("staged") and st.get("session"):
            st["session"].applied(b); st["staged"] = None; st["feedback"] = True; render()
        if not view["adv"]:
            st["optimised"] = True; line_ = change_summary_line(plain); update_steps()
            result_var.set("✓ Done! %s. Not happy? Click Undo." % line_ if line_ else "✓ Done! Start the sim and fly. Not happy? Click Undo.")
            result_tip.text = ("Changed:\n" + "\n".join("• %s: %s → %s" % x for x in plain)) if plain else ""
            result_lbl.configure(fg=T["ok"]); return
        messagebox.showinfo(SHORT_NAME, "All set! ✈\n\n%d settings were changed.\nA backup was saved as %s.\n\n"
                            "Start Microsoft Flight Simulator and enjoy your flight. Changing graphics in the sim's own menu may undo some "
                            "of these values – just run SkyTune again." % (len(changed), os.path.basename(b)))
    def apply():
        if not st["cfg"] or not sim_check(): return
        before = UserCfg.load(st["path"]); vals = collect()
        plain = summarize_changes(before, vals, change_resolution=res_opt.get())
        cfg = UserCfg.load(st["path"])
        changed = apply_values(cfg, vals, change_resolution=res_opt.get())
        if not changed:
            hide_confirm_bar()
            set_status("Nothing to change – your settings already match.", "info")
            if not view["adv"]:
                result_var.set("Your settings already match – nothing to change. Start the sim and fly!"); result_lbl.configure(fg=T["ok"]); return
            messagebox.showinfo(SHORT_NAME, "Your settings already match – nothing needed changing."); return
        prof = dict(st.get("active_profile") or {})
        warnings = []
        if prof.get("edition") in ("2020", "2024") and st.get("edition") in ("2020", "2024") and prof["edition"] != st["edition"]:
            warnings.append("This profile was saved for MSFS %s and this file looks like MSFS %s. Only settings that already exist here are written." % (
                prof["edition"], st["edition"]))
        if prof.get("name"): reason = "profile"
        elif st.get("staged"): reason = "assistant"
        elif view["adv"]: reason = "manual"
        else: reason = "optimise"
        st["pending"] = {"kind": "apply", "values": vals, "res": bool(res_opt.get()), "reason": reason,
                         "warnings": warnings, "profile": prof.get("name") or "", "plain": plain}
        if view["adv"]:
            if not messagebox.askyesno(SHORT_NAME, confirm_summary(plain, warnings, "Write these changes to the simulator settings?"), default="no"):
                cancel_pending(); return
            commit_pending(); return
        line_ = change_summary_line(plain)
        held_n = len(st.get("held") or ())
        held_note = "" if not held_n else " Leaving %d setting%s as the sim has them." % (held_n, "" if held_n == 1 else "s")
        show_confirm_bar("Confirm %d change%s%s. Click Yes, write. Cancel leaves the file alone.%s" % (
            len(plain), "" if len(plain) == 1 else "s", (": " + line_) if line_ else "", held_note))
        set_status("Nothing is written until you click Yes, write.", "info")

    def restore(latest, src=None):
        if not st["path"] or not sim_check(): return
        bs = list_backups(st["path"])
        if src is None:
            if not bs:
                set_status("No backups yet – nothing to undo.", "warn")
                messagebox.showinfo(SHORT_NAME, "There's nothing to undo yet. SkyTune makes a backup the first time you click Apply."); return
            src = bs[-1] if latest else filedialog.askopenfilename(
                initialdir=backup_dir(st["path"]), title="Choose a SkyTune backup",
                filetypes=[("Settings backup", "*.opt"), ("All", "*.*")])
        if not src: return
        plan = plan_restore(st["path"], src)
        if not plan["ok"]:
            set_status(plan["error"], "err"); messagebox.showerror(SHORT_NAME, plan["error"]); return
        intro = "Restore settings from %s?" % plan["backup_name"]
        saved = plan.get("saved_review") or {}
        if saved.get("profile"): intro += "\n\nSaved note: profile %s." % saved["profile"]
        elif saved.get("reason"): intro += "\n\nSaved note: %s." % REASON_PLAIN.get(saved["reason"], saved["reason"])
        st["pending"] = {"kind": "restore", "src": src}
        if view["adv"]:
            if not messagebox.askyesno(SHORT_NAME, confirm_summary(plan["changes"], plan["warnings"], intro), default="no"):
                cancel_pending(); return
            commit_pending(); return
        line_ = change_summary_line(plan["changes"])
        show_confirm_bar("Restore %s%s. Click Yes, restore. Cancel leaves the file alone." % (
            plan["backup_name"], (" – " + line_) if line_ else ""))
        set_status("Nothing is restored until you click Yes, restore.", "info")

    def ensure_cleaner():
        try:
            if st.get("cleaner_built") or nb.index("current") != nb.index(clean_tab.master.master): return
        except tk.TclError: return
        build_cleaner(clean_tab); st["cleaner_built"] = True
    def first_launch():
        autodetect()
        if st["cfg"]: on_choice()                      # remembered (or default) edge smoothing / extra frames
        if st["cfg"] and tr_all.get() != "SkyTune decides": on_traffic()
        if demo_hw: apply_gpu_limits(DEMO_HW["gpu"])
        toggle_view(start_view == "advanced"); nb.select(start_tab)
        try: first = not load_state().get("first_launch_done")
        except Exception: first = False
        if first or show_welcome: welcome_o.pack(fill="x", pady=(0, 14), before=ao2)
        poll_sim()
        # v1.3.2: the cache list (which measures every cache folder) is built the first time the Clean up tab is shown
        nb.bind("<<NotebookTabChanged>>", lambda e: ensure_cleaner(), add="+"); ensure_cleaner()
        if not demo_hw and not quiet_detect:
            hw_, when_ = load_hw_cache()
            if hw_: reco_var.set("Last check (%s): %s – click “Check my PC” to use it, or Re-check." % (hw_cache_note(when_), hw_.get("gpu")))
        if goal in GOALS: goal_var.set(goal); goal_blurb.set(GOAL_BLURB[goal])
        if open_clean: root.after(500, open_cleaner)
        if "--update-cleanup" in sys.argv: root.after(700, update_cleanup)
        if start_preset: root.after(300, lambda: load_preset(start_preset))
        if auto_open_detect: root.after(600, auto_detect)
        if quiet_detect: root.after(600, lambda: auto_detect(popup=False))
        if "--prefs-open" in sys.argv: show_prefs(True)
        _atext = sys.argv[sys.argv.index("--assistant") + 1] if "--assistant" in sys.argv else ""
        if "--chips" in sys.argv:
            for p_ in sys.argv[sys.argv.index("--chips") + 1].split(","):
                if p_ in chip_vars: chip_vars[p_].set(True)
            upd_chip_hint(); root.after(900, lambda: ask(_atext))
        elif "--assistant" in sys.argv: root.after(900, lambda: ask(_atext, new=True))
        if "--ai-guide" in sys.argv: root.after(1000, ai_guide)
        if "--fg" in sys.argv:
            root.after(800, lambda: set_var("Video/FrameGeneration", sys.argv[sys.argv.index("--fg") + 1]))
        if "--ai-settings" in sys.argv: root.after(900, ai_settings)
        if "--scroll" in sys.argv: root.after(1500, lambda: _scv.yview_moveto(float(sys.argv[sys.argv.index("--scroll") + 1])))
        if "--profiles" in sys.argv: root.after(800, profiles_dialog)
        if "--backups" in sys.argv: root.after(800, backups_dialog)

    def all_widgets(top):
        out, todo = [], [top]
        while todo:
            w = todo.pop(); out.append(w); todo.extend(w.winfo_children())
        return out

    def truncated_widgets(top):
        """v1.3.1: mapped buttons/check boxes/radio buttons whose text doesn't fit (ttk clips it silently)."""
        bad, todo = [], [top]
        while todo:
            w = todo.pop(); todo.extend(w.winfo_children())
            if w.winfo_class() not in ("TButton", "TCheckbutton", "TRadiobutton") or not w.winfo_ismapped(): continue
            try:
                txt = str(w.cget("text"))
                if not txt or str(w.cget("image")): continue
                sty = str(w.cget("style")) or w.winfo_class()
                fnt = s.lookup(sty, "font") or s.lookup(w.winfo_class(), "font") or "TkDefaultFont"
                need = max(tkfont.Font(root=root, font=fnt).measure(l) for l in txt.split("\n"))
                pad = [int(float(x)) for x in re.findall(r"-?\d+(?:\.\d+)?", str(s.lookup(sty, "padding") or "0"))] or [0]
                lr = pad[0] + (pad[2] if len(pad) >= 3 else pad[0])
                if w.winfo_class() == "TButton": need += lr
                if need > w.winfo_width() + 1: bad.append(w)
            except (tk.TclError, ValueError): continue
        return bad
    st["truncated_widgets"] = truncated_widgets

    _rj = {"id": None}
    def _on_root_cfg(_=None):
        if _rj["id"]: root.after_cancel(_rj["id"])
        _rj["id"] = root.after(60, lambda: (relayout_header(), rewrap(), _sfit()))
    root.bind("<Configure>", _on_root_cfg, add="+")
    root.after(100, first_launch)
    if os.environ.get("SKYTUNE_PROBE"):           # developer start-up timing hook (perf measurements only)
        root.after(100, lambda: root.after_idle(lambda: open(os.environ["SKYTUNE_PROBE"], "w").write(str(time.time()))))
    if layout_check:
        def _check():
            root.update_idletasks(); root.update()
            rh = root.winfo_height(); ok = []
            for name, w in (("apply", apply_big), ("undo", undo_big)):
                y = w.winfo_rooty() - root.winfo_rooty()
                ok.append((name, w.winfo_ismapped() and y >= 0 and y + w.winfo_height() <= rh))
            pw = path_lbl.winfo_rootx() - root.winfo_rootx() + path_lbl.winfo_reqwidth()
            ok.append(("path", pw <= root.winfo_width()))
            ok.append(("hdr_buttons", br.winfo_rootx() - root.winfo_rootx() + br.winfo_reqwidth() <= root.winfo_width()))
            ok.append(("no_hscroll", simple.winfo_reqwidth() <= _scv.winfo_width() + 2))
            ok.append(("summary_scroll", bool(sum_sb.winfo_ismapped())))
            ok.append(("steps", all(w.winfo_ismapped() for w in (ao2, go2, so, clo, prefs_card))))
            ok.append(("prefs_collapsed", bool(PREFS.get("prefs_open")) or "--prefs-open" in sys.argv or not pbody.winfo_ismapped()))
            cut = truncated_widgets(root)
            ok.append(("labels_fit", not cut))
            ok.append(("step_bar", stepbar.winfo_ismapped() and stepbar.winfo_reqwidth() <= root.winfo_width()))
            if "--sim-running" in sys.argv:
                ok.append(("sim_banner", bool(simban.winfo_ismapped()) and "disabled" in apply_big.state()))
            # v1.3.1: also every Advanced tab (Tools buttons were cut off in 1.3.0) and the AI guide window
            toggle_view(True); adv_cut = []
            for t_ in range(len(nb.tabs())):
                nb.select(t_); root.update_idletasks(); root.update(); adv_cut += [w for w in truncated_widgets(root) if w not in adv_cut]
            ok.append(("advanced_labels_fit", not adv_cut))
            ok.append(("tool_buttons_fit", all(w.winfo_width() > 1 for w in st.get("tool_buttons", ()))
                       and not any(w in cut + adv_cut for w in st.get("tool_buttons", ()))))
            g_ = ai_guide(); root.update_idletasks(); root.update(); g_cut = truncated_widgets(g_)
            ok.append(("ai_guide_fit", not g_cut)); cut += adv_cut + g_cut
            open_cleaner(); c_ = st["cleaner_dlg"]; root.update_idletasks(); root.update(); c_cut = truncated_widgets(c_)
            closeb = [w for w in all_widgets(c_) if isinstance(w, ttk.Button) and str(w.cget("text")) == "Close"]
            ok.append(("cleaner_fits", not c_cut and bool(closeb) and closeb[0].winfo_ismapped()
                       and closeb[0].winfo_rooty() + closeb[0].winfo_height() <= c_.winfo_rooty() + c_.winfo_height() + 1
                       and c_.winfo_rooty() + c_.winfo_height() <= c_.winfo_screenheight())); cut += c_cut
            print(json.dumps({"size": [root.winfo_width(), rh], "checks": dict(ok), "cut": [str(w.cget("text")) for w in cut], "dbg": [hdr_mode["narrow"], hdr.winfo_width(), left.winfo_reqwidth(), br.winfo_reqwidth(), br.winfo_rootx() - root.winfo_rootx(), path_lbl.winfo_reqwidth(), simple.winfo_reqwidth(), _scv.winfo_width(), col_mode["stacked"]]}), flush=True)
            root.destroy()
        root.after(int(layout_check), _check)
    if "--shot" in sys.argv:
        shot_path = sys.argv[sys.argv.index("--shot") + 1]
        delay = int(sys.argv[sys.argv.index("--shot-delay") + 1]) if "--shot-delay" in sys.argv else 2200
        def _shot():
            root.update_idletasks(); root.update()
            wid = str(root.winfo_id()); wrote = False
            for cmd in (["import", "-window", "root", shot_path], ["import", "-window", wid, shot_path]):
                try:
                    subprocess.run(cmd, check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    wrote = True; break
                except Exception:
                    continue
            if not wrote:
                try:
                    with open(shot_path + ".txt", "w", encoding="utf-8") as fh: fh.write("screenshot tool missing\n")
                except OSError: pass
            root.destroy()
        root.after(delay, _shot)
    root.mainloop()

def main():
    a = sys.argv[1:]
    run_gui(demo_hw="--demo-hw" in a, start_tab=int(a[a.index("--tab") + 1]) if "--tab" in a else 0,
            auto_open_detect="--open-detect" in a, start_view="advanced" if "--advanced" in a else "simple",
            show_welcome="--welcome" in a, start_preset=a[a.index("--preset") + 1] if "--preset" in a else None,
            open_clean="--clean" in a, quiet_detect="--detect-quiet" in a,
            goal=a[a.index("--goal") + 1] if "--goal" in a else None,
            geometry=a[a.index("--geometry") + 1] if "--geometry" in a else None,
            layout_check=a[a.index("--layout-check") + 1] if "--layout-check" in a else None)

if __name__ == "__main__":
    main()
