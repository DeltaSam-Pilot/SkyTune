"""Drive the built SkyTune.exe through confirm, backup, restore and rollback. Fixture files only."""
import hashlib, json, os, subprocess, time
from pathlib import Path
from PIL import Image

WINEPREFIX = os.environ.get("WINEPREFIX") or "/tmp/wine-skytune"
EXE = os.environ["SKYTUNE_EXE"]
FIXTURE = os.environ["SKYTUNE_FIXTURE"]
DISP = ":81"
ROAM = Path(WINEPREFIX) / "drive_c/users/ubuntu/AppData/Roaming/Microsoft Flight Simulator 2024"
CFG = ROAM / "UserCfg.opt"

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def sh(cmd, timeout):
    return subprocess.run(cmd, timeout=timeout, check=False)

def tree():
    return subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True, text=True, timeout=5).stdout

def wait_main():
    for _ in range(24):
        if "1.8.0" in tree():
            return True
        time.sleep(0.25)
    return False

def shot(path):
    subprocess.run(["import", "-window", "root", path], timeout=8, check=True)

def blobs(im, pred, min_area):
    w, h = im.size
    pix = im.load()
    seen = bytearray(w * h)
    out = []
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if seen[i] or not pred(pix[x, y]):
                continue
            stack = [(x, y)]
            seen[i] = 1
            minx = maxx = x
            miny = maxy = y
            n = 0
            while stack:
                cx, cy = stack.pop()
                n += 1
                minx, maxx = min(minx, cx), max(maxx, cx)
                miny, maxy = min(miny, cy), max(maxy, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and pred(pix[nx, ny]):
                        seen[ny * w + nx] = 1
                        stack.append((nx, ny))
            if n >= min_area:
                out.append((n, (minx + maxx) // 2, (miny + maxy) // 2, minx))
    out.sort(reverse=True)
    return out

def is_blue(c):
    r, g, b = c
    return b > 130 and 40 < g < 170 and r < 40

def is_amber(c):
    """The other edition's main button is amber. The free button stays blue."""
    r, g, b = c
    return r > 140 and 50 < g < 160 and b < 50

def is_primary(c):
    return is_blue(c) or is_amber(c)

def is_teal(c):
    r, g, b = c
    return r < 40 and 90 < g < 170 and 70 < b < 140 and abs(g - b) < 40

def is_slate(c):
    r, g, b = c
    return 40 < r < 80 and 50 < g < 100 and 70 < b < 120

def click(x, y):
    subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=5, check=True)
    time.sleep(0.05)
    subprocess.run(["xdotool", "mousedown", "1"], timeout=5, check=True)
    time.sleep(0.12)
    subprocess.run(["xdotool", "mouseup", "1"], timeout=5, check=True)
    time.sleep(0.5)

def find_click(pred, area, label):
    shot("/tmp/exe-live.png")
    im = Image.open("/tmp/exe-live.png").convert("RGB")
    found = blobs(im, pred, area)
    if not found:
        raise SystemExit("missing " + label)
    _n, x, y, _x0 = found[0]
    click(x, y)
    return x, y

def launch(extra_env=None):
    env = os.environ.copy()
    env.update(WINEPREFIX=WINEPREFIX, WINEARCH="win64", WINEDEBUG="-all",
               WINEDLLOVERRIDES="mscoree,mshtml=", DISPLAY=DISP, USER="ubuntu", LOGNAME="ubuntu")
    if extra_env:
        env.update(extra_env)
    subprocess.Popen(["wine", "start", "/unix", EXE, "--demo-hw", "--detect-quiet", "--geometry", "1280x800+30+20"],
                     cwd=os.path.dirname(EXE), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_main():
        raise SystemExit("window did not open")
    time.sleep(2.2)

def stop_wine():
    subprocess.run(["wineserver", "-k"], timeout=8, env={"WINEPREFIX": WINEPREFIX})

def click_undo():
    shot("/tmp/exe-live.png")
    im = Image.open("/tmp/exe-live.png").convert("RGB")
    blues = blobs(im, is_primary, 800)
    if not blues:
        raise SystemExit("no optimise button for undo")
    _n, _x, by, x0 = blues[0]
    click(x0 - 90, by)
    time.sleep(0.45)

def main():
    os.environ["DISPLAY"] = DISP
    os.environ["WINEPREFIX"] = WINEPREFIX
    os.environ["USER"] = "ubuntu"
    xvfb = subprocess.Popen(["Xvfb", DISP, "-screen", "0", "1400x900x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    ROAM = CFG.parent
    ROAM.mkdir(parents=True, exist_ok=True)
    backups = ROAM / "UserCfg_backups"
    if backups.exists():
        import shutil
        shutil.rmtree(backups)
    CFG.write_bytes(Path(FIXTURE).read_bytes())
    original = sha(CFG)
    try:
        launch()
        find_click(is_primary, 800, "optimise")
        time.sleep(0.4)
        if sha(CFG) != original:
            raise SystemExit("file changed before confirm")
        find_click(is_slate, 200, "cancel")
        time.sleep(0.3)
        if sha(CFG) != original:
            raise SystemExit("cancel wrote the file")
        print("NO_SAME")
        find_click(is_primary, 800, "optimise again")
        time.sleep(0.4)
        find_click(is_teal, 200, "yes write")
        time.sleep(0.8)
        if sha(CFG) == original:
            raise SystemExit("yes did not write")
        print("YES_CHANGED")
        notes = list(backups.glob("*.review.json")) if backups.exists() else []
        if len(notes) != 1:
            raise SystemExit("review missing %s" % notes)
        doc = json.loads(notes[0].read_text())
        if doc.get("app_version") != "1.8.0" or not doc.get("verified") or not doc.get("changes"):
            raise SystemExit("bad review %s" % doc)
        if "sk-" in notes[0].read_text():
            raise SystemExit("review leaked a key")
        print("REVIEW_OK")
        click_undo()
        find_click(is_teal, 200, "yes restore")
        time.sleep(0.6)
        if sha(CFG) != original:
            raise SystemExit("restore did not return the original")
        print("RESTORED")
        stop_wine()
        time.sleep(0.4)
        launch()
        find_click(is_primary, 800, "optimise for rollback")
        time.sleep(0.4)
        find_click(is_teal, 200, "yes write again")
        time.sleep(0.6)
        modified = sha(CFG)
        if modified == original:
            raise SystemExit("second write did not change the file")
        stop_wine()
        time.sleep(0.4)
        launch({"SKYTUNE_RESTORE_CHECK": "fail"})
        click_undo()
        find_click(is_teal, 200, "yes restore rollback")
        time.sleep(0.6)
        if sha(CFG) != modified:
            raise SystemExit("rollback did not keep the current file")
        print("ROLLBACK_KEPT")
    finally:
        stop_wine()
        xvfb.kill()
        xvfb.wait(timeout=5)

if __name__ == "__main__":
    main()
