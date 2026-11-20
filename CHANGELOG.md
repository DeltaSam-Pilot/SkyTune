# Changelog – SkyTune for MSFS 2020/2024

## v1.8.1 – 2026-11-20
A small update on top of 1.8.0. The window has a sidebar, and settings are still written only after you confirm.

- **Home.** A status line shows the sim SkyTune found, the SkyTune version, and the last apply. Cards open Optimise, Sims, Tools, Troubleshooting and Settings.
- **Sims.** MSFS 2020 and 2024 are listed for Steam, the Microsoft Store, and a custom Community folder when that path is in the settings file.
- **Sims.** Each detected install lists the Community packages by the names on disk. SkyTune only reads that folder.
- **Optional mods.** On the Sims page you can install, repair or remove AtmosphereMod by tomwhoca and the Glass Cockpit DLSS fix add-on by IFreemz. SkyTune downloads each author's latest official release only after you click, checks the size and checksum, and links the licence. It remembers the files it copied and backs up anything it replaces. Uninstall puts those files back. Other Community packages are left as they are. A clash warning still appears when AtmosphereMod is already installed.
- **NVIDIA.** The page reads the driver when it can, and can save three documented profile values for FlightSimulator.exe and FlightSimulator2024.exe only, after you confirm. It stores a backup first. Restore puts that backup back. Other cards are left alone.
- **Looks and overlay.** Natural, Vivid and Cinematic are preset files only. ReShade itself is opened from reshade.me when you click. F8 opens a small always-on-top window. It does not inject anything.
- **Updates.** The Updates page lists the official pages for SkyTune, OptiScaler, ReShade, the Glass Cockpit fix and AtmosphereMod. It does not download them until you use Install.
- **Troubleshooting.** The support pack, the graphics-mod warning and the PC check are on one page.
- **Updates.** Once a day, if you leave it on, SkyTune reads the version on its Flightsim.to page. A newer version shows a notice with a button that opens that page. Nothing is downloaded or installed for you. Turn it off under Settings.
- **Support pack and saved settings.** The pack lists its files before saving and hides account names. DLSS and frame generation are labelled "saved in your settings".

SkyTune.exe is unsigned. Download it only from the official Flightsim.to page. Changing settings is at your own risk: SkyTune backs up your file before every write, and you should keep a copy of your own as well. Results depend on your hardware, so frame rates are not guaranteed. SkyTune is a free, independent community project, not affiliated with or endorsed by Microsoft or Asobo Studio.

SkyTune.exe is unsigned. Download it only from the official Flightsim.to page. Changing settings is at your own risk: SkyTune backs up your file before every write, and you should keep a copy of your own as well. Results depend on your hardware, so frame rates are not guaranteed. SkyTune is a free, independent community project, not affiliated with or endorsed by Microsoft or Asobo Studio.

## v1.8.0 – 2026-11-14 (quality)
A quality pass on the same tools. The window starts with three steps, Help explains the common questions, and each suggested change has a one-line reason from the graphics card, video memory, processor cores, and screen refresh when those could be read. Nothing is written until you click Yes, write.

**Frame Hold**
- Set a target frame rate and a minimum and maximum for terrain detail and object detail. Optional altitude mode keeps the low end near the ground and allows the high end in cruise.
- Frame Hold only calculates. Microsoft Flight Simulator does not document a way to change those values during a flight, so SkyTune does not write into the simulator's memory and does not change the sim while it is running. The numbers go on the list after you close the sim. Yes, write still asks. Closing the window puts the list back to the file if you have not written it.

**More reliable writes**
- A missing file, a read-only file, a read-only folder, or a file another program still has open is left as it is, with a plain sentence about what to do next.
- UTF-16 and a UTF-8 byte-order mark are read and written back the same way. Old Mac line endings and mixed line endings still parse.
- A write goes to a temporary file, is checked, and then replaces the original. If that replace fails, the original file stays.
- Steam and the Microsoft Store are both checked for MSFS 2020 and MSFS 2024. A file you pick with Browse is remembered. A custom Steam library is checked too.

SkyTune.exe is unsigned. Download it only from the official Flightsim.to page. Changing settings is at your own risk: SkyTune backs up your file before every write, and you should keep a copy of your own as well. Results depend on your hardware, so frame rates are not guaranteed. SkyTune is a free, independent community project, not affiliated with or endorsed by Microsoft or Asobo Studio.

## v1.7.1 – 2026-11-14 (cleaner window)
A small polish update to 1.7.0. The window is cleaner. Guided goals, flight situations, profiles, Since last write, creator setups, the sim-update check, the read-only PC health line, bindings backup, checked restore, diagnostics, cache cleanup and the assistant are unchanged.

SkyTune.exe is unsigned. Download it only from the official Flightsim.to page. Changing settings is at your own risk: SkyTune backs up your file before every write, and you should keep a copy of your own as well. Results depend on your hardware, so frame rates are not guaranteed. SkyTune is a free, independent community project, not affiliated with or endorsed by Microsoft or Asobo Studio.

## v1.7.0 – 2026-11-14 (EasyjetSimPilot presets)
Since-last-write, flight situations, profiles and checked restore stay. This version adds two built-in MSFS 2024 setups taken from settings EasyjetSimPilot showed on screen.

**Creator setup**
- **EasyjetSimPilot (MSFS 2024 SU7)** fills Step 3 with the video's graphics choices for every setting SkyTune can already write. Resolution and display mode are not changed.
- **EasyjetSimPilot - 8 GB VRAM** is the same list with three changes for an 8 GB card at 1080p: terrain detail 125 → 100, off-screen pre-caching High → Medium, and clouds Ultra → High. Texture resolution stays High, because SkyTune treats Ultra as the step that needs more than 8 GB.
- These setups appear only when the loaded file is MSFS 2024. They are hidden for MSFS 2020.
- The credit line is “Based on settings shown in EasyjetSimPilot's video”, with the video address. The creator has not endorsed SkyTune.
- A 240 Hz screen without variable refresh may need V-Sync or a frame cap. SkyTune does not change V-Sync. There is no frame-rate promise.
- Choosing a setup only prepares the list. **Yes, write** still asks, makes a backup and a review note, and a restore still checks the file. Saved profiles can be compared with either setup. Nothing is written until you confirm.
- Settings with no verified SkyTune control are left out: HDR10, exposure, V-Sync, Reflex, dynamic settings, depth of field, motion blur, particles, the variety and character-quality rows, and seatbelts.

**Also in 1.7.0**
- A sim-update check compares the file with SkyTune's last write, or the newest backup. When many known settings differ and the file is newer, Step 3 says the settings may have been reset. **Put my settings back** only fills the list. **Yes, write** still asks.
- **PC health** is read only: free space, GPU, video memory, RAM, page file, HAGS, Memory Integrity, and the main display's refresh rate. A missing reading stays Unknown. SkyTune does not change Windows. An 8 GB card gets a suggestion to consider the 8 GB creator setup, which is not selected for you. A screen faster than 144 Hz gets a note about V-Sync or a frame cap.
- **Control bindings** are copied only when Steam `inputprofile_` files are found under userdata for MSFS 2020 or 2024. Otherwise the row says Not found. The Microsoft Store cloud-save folder is not copied.

The Windows download includes an unsigned `SkyTune.exe`. Download it only from the official Flightsim.to page. Changing settings is at your own risk: SkyTune backs up your file before every write, and you should keep a copy of your own as well. Results depend on your hardware, so frame rates are not guaranteed. SkyTune is a free, independent community project, not affiliated with or endorsed by Microsoft or Asobo Studio.

## v1.6.0 – 2026-11-14 (since last write)
Flight situations, the local diagnostic, saved profiles, review notes and checked restore stay. This version shows what changed in the settings file after SkyTune last wrote it.

**Since last write**
- After a confirmed write or a checked restore, SkyTune remembers the known graphics settings. The note stays in SkyTune's own folder. It has no file path, no account name and no API key.
- Next time that file is opened, Step 3 says how many of those settings now differ, with the old and new labels. A busy airport, a goal, or a profile does not do this. This is only the difference from SkyTune's own last write.
- **Keep the sim's values** leaves those settings out of the next write. **Include them again** puts them back on the list. Neither one writes. **Yes, write** is still required, and **Cancel** still leaves the file alone.
- A last write for MSFS 2020 is not compared with an MSFS 2024 file, or the other way around.
- A stored note that contains a key, a path, or a setting SkyTune does not know is ignored.

The Windows download includes an unsigned `SkyTune.exe`. Download it only from the official Flightsim.to page. Rebuild with `source\build_exe.bat` if you want to compile it yourself.

## v1.5.0 – 2026-11-07 (flight situations, local diagnostic, in-window confirm)
Saved profiles, review notes and checked restore stay. This version adds a situation for the flight you are about to make, and a diagnostic note you save yourself.

**This flight**
- Choose **Busy airport**, **VFR scenery** or **Airliner cockpit**. Each one adjusts the change list and says what you give up.
- Busy airport lowers traffic and object distance unless you already set a traffic level. VFR raises terrain and trees only as far as video memory allows. Airliner cockpit sharpens instruments and simplifies clouds.
- Your smooth-edges and extra-frames choices are kept. Nothing is written until you confirm.

**Confirm in the window**
- **Optimise** and **Undo** no longer rely on a small popup in the simple view. A **Yes, write** or **Yes, restore** button appears, with **Cancel**.
- Cancel leaves the settings file unchanged. Yes writes, keeps a backup and a review note, and a restore checks the file. If that check fails, the previous file is put back.
- The backup copy is a normal read and write of the file. Python 3.12's file copy calls the Windows CopyFile2 function, and Wine aborts the program on that call instead of reporting an error, so a confirmed write never landed. The settings file is copied without that call.

**Diagnostic**
- **Save diagnostic…** writes a text file where you choose. It lists the detected hardware, sim edition, goal, preferences, profile names and backup count. Account names in paths are replaced with `<user>`. API keys are not included. SkyTune does not upload the file.

**Compare**
- In Saved profiles, **Compare** shows how a profile differs from the file that is loaded. It does not write.

The Windows download includes an unsigned `SkyTune.exe` built from this source. Verify you trust the download before you run it. Rebuild with `source\build_exe.bat` if you want to compile it yourself.

## v1.4.0 – 2026-11-07 (saved profiles, change review, checked restore)
One-click hardware tuning, cache cleanup, Update Cleanup and the offline assistant are unchanged. This release adds a way to keep a setup, see exactly what a backup would put back, and refuse a restore that does not check out.

**Saved profiles**
- **Saved profiles…** on Step 3 and in Advanced settings. Save the settings on screen under a name and an optional note. They are stored in `%APPDATA%\SkyTune\profiles` (Windows) or `~/SkyTune/profiles` (Linux), next to `state.json`.
- A profile does not store screen resolution, file paths, your user name, or an API key. Unknown keys and out-of-range values are dropped. At most 24 profiles.
- **Use** only prepares Step 3. **Import…** / **Export…** are JSON files. **Delete** does not touch the simulator.
- Optimise and Apply still ask **Yes** before writing. Choosing No writes nothing. A profile is not replaced by a fresh hardware check at the moment you confirm it.

**Review and restore**
- Each new backup gets a `.review.json` note beside it: which recognised settings changed, the old and new labels, and why (optimise, assistant, profile, manual apply, or restore). The note stores a content hash of that backup, not a path.
- **Review backups…** shows the saved note, or a live difference for backups made before 1.4.0.
- Restore asks with that difference, then copies the backup and reads the result. If the file does not match, the previous file is put back. A backup that does not parse is refused. A 2020/2024 mismatch is called out in the question.
- **Worse** after an assistant fix uses the same checked restore.
- Cache deletion is unchanged: it still asks, and it still only clears whitelisted cache folders you ticked.

Version info now says 1.4.0. New `tests/test_v140.py`. The test suite has 217 tests. The Flightsim.to download includes `SkyTune.exe`, built from this source with PyInstaller. It is not code-signed. Rebuild on Windows with `source\build_exe.bat` if you want to compile it yourself.

## v1.3.2 – 2026-10-23 (looks and speed)
**Looks**
- Cleaner dark theme on an even spacing grid: rounded cards, clearer section headers, consistent fonts and sizes, and a status bar at the bottom.
- Text and button colours meet WCAG AA contrast (4.5:1 for normal text). The blue accent is a little deeper so white text on it stays readable.
- Every button now has hover and pressed states. The **✈ Optimise my sim** button is bigger and stands out more.
- Small drawn icons, status chips (sim closed / running), and sharper text on high-DPI screens (per-monitor DPI aware on Windows). New, sharper app icon: anti-aliased, with every Windows size from 16 to 256 px.
- Checked for cut-off text at 1024×600, 1280×800, 1366×768 at 125 %, 1920×1080 and 144 DPI.

**Speed**
- More responsive: network, encoding and fuzzy-matching modules load only when first used.
- **Hardware check runs in the background** with a spinner, so the window never freezes. The result is remembered on this PC for 30 days, so the next start is instant. Click **Re-check** to run it again (for example after a new graphics card). A card you pick with *Wrong graphics card?* is remembered too.
- Cache scans and cache sizes run in the background. The *Clean up* tab measures cache folders only the first time you open it.
- The "is the sim running?" check takes one cheap process snapshot instead of starting `tasklist` every few seconds, and checks less often while SkyTune is minimised. Idle CPU use is much lower.
- Slightly smaller exe (about 0.3 MB less): unused Python modules (unit testing, documentation, compression formats, decimal maths and similar) are left out of the build. No UPX packing, as it often triggers antivirus false alarms.
- Auto-detect tuning is unchanged: no settings were found that clearly needed it. No new settings keys.
- Version info now says 1.3.2. New `tests/test_v132.py` (hardware cache, process snapshot, lazy imports, icons, colour contrast, background check); the test suite has 207 tests.

## v1.3.1 – 2026-10-23 (fixes from testing, multi-problem assistant, AI guide, polish)
- **Fix: truncated Tools buttons** ("Update Cleanu") at 1280×800, 1366×768 @125% and 1920×1080. The buttons now size to their text, and an automatic check confirms no button text is cut at 1024×600 → 1920×1080 and 100–150% scaling.
- **Advanced: readable IN FILE column**: -1 Off, 0 Low, 1 Medium, 2 High, 3 Ultra; FSRFG → AMD FSR; NONE → Off (every choice setting shows its label, not the raw code).
- **Advanced: frame-generation-only controls**: when Frame generation is Off, the frame multiplier is greyed out with a hint and is never written. Turning frame generation on enables it again (AMD FSR: 2x only; DLSS FG: 2x, or up to 4x on RTX 50).
- **In-app "How to use AI" guide**: open it from **? How to use AI** next to the AI checkbox or from *AI settings*. Explains that SkyTune works offline without a key, how to get and paste a key, optional base URL / model, that the provider bills usage (no prices), that the key stays on this PC, what is sent, and how to remove the key. Also added to the README.
- **Several problems at once**: the quick buttons (Stutters, Low FPS, Blurry, Pop-in, Crashes, After update) are now toggles, highlighted when selected, and combine with typed text. **Ask** gives one combined diagnosis (a cause line per problem) with one merged, de-duplicated, ranked fix list; each fix says which problems it helps with. AI mode sends all selected problems. **Start over** clears the selection. Nothing new is saved between runs.

### Polish ("make it better")
- (a) **Step bar**: a compact *1 Check my PC › 2 What matters most › 3 Optimise* bar stays visible at the top of the simple view; it highlights where you are, ticks finished steps, and jumps to a step when clicked.
- (b) **Sim running banner**: a friendly banner ("The sim is running…") with a **Check again** button. Optimise, Undo, Apply, Restore, Clear selected, Fix stutters and Update Cleanup are disabled while it shows, and their tooltip explains why.
- (c) **Plain summary after Optimise**: "✓ Done! Cloud quality High → Ultra, AI aircraft traffic Medium → Low and 3 more. Not happy? Click Undo." Hover for the full list.
- (d) **Shorter Advanced warning**: one plain sentence ("Close the sim before applying – changing graphics in its own menu can overwrite anything you set here."). The frame-generation details moved to the Frame generation side card.
- (e) **Cache list**: a clear "N items ticked · X to free" total and a one-line "Safe to clear" note. The *Choose caches…* window now sizes itself to fit (it scrolls on short screens, and Close is always visible).
- (f) **Consistent buttons, no cut-off text**: equal-width problem buttons, the preset row wraps on narrow windows, and the layout self-check now measures every button in the simple view, all Advanced tabs and the AI guide.
- Version info now says 1.3.1. The test suite has 178 tests.

## v1.3.0 – 2026-10-23 (easier to use, plus an assistant)
- **A simple 3-step view**: **Step 1 · Check my PC** (auto-detect, with *Details* and *Wrong graphics card?* links), **Step 2 · What matters most?** (goal) with an optional **Anything bothering you?** box, and **Step 3 · Optimise my sim**, which shows what will change. A big **✈ Optimise my sim** button and **↶ Undo** stay in a fixed footer.
- **A clear result line**: after applying, you see "✓ Done! Start the sim and fly. Not happy? Click Undo." instead of a pop-up. After Undo: "↶ Undone – your previous settings are back."
- **Assistant ("Anything bothering you?")**: type a problem in plain words (typos are OK) or use the quick buttons Stutters / Low FPS / Blurry / Pop-in / Crashes / After update. SkyTune shows:
  - the likely bottleneck, with a confidence label;
  - follow-up question chips and a short chat history;
  - ranked fixes, each with an impact badge (Big help / Helps / Small help) and a trade-off line;
  - **Use top fix** or **Use ticked fixes**. Nothing is written until **Optimise my sim**.
- **Understands the sim's own performance readout**: paste the MSFS 2024 dev-mode line ("Limited by Graphics Queue", GPU / main-thread ms, LOD factor 0.50). A measured limit beats guesses from symptoms. When the graphics card is the limit, only graphics-card fixes are offered. LOD readouts at 0.50 are explained as Dynamic Settings being at its floor. A real user report (RTX 3070 Ti, Ryzen 7 8700F, 1080p, A320neo V2 at EGLL: ~51 FPS, GPU-bound) is now a test case.
- **New problem type: "Slow after loading in"** (spawning, loading into an airport, the first minute). SkyTune explains that the dip is temporary (scenery streaming, shader compilation, especially after clearing caches or a driver or sim update, and rolling-cache fill). It suggests waiting a minute on the ground and says not to clear shader caches before every flight. It only offers to set terrain pre-caching to a sensible level and keep Terrain LOD within video memory. A crash during loading is not treated as a dip. A real user report (5.8 FPS while spawning at EGLL, then ~51) is a test case.
- Fix: when the sim's readout says the graphics card is the limit, processor-only fixes such as less AI traffic are never suggested, even if those settings are still high. If the graphics settings are already light, SkyTune says there's little left to trim. If you let SkyTune choose smoothing, it offers DLSS/FSR on Balanced instead. It no longer says "Try Fix stutters" in that case.
- Fix: the word "loading" alone no longer counts as pop-in, and "caches" no longer matches "crashes" as a typo.
- **Better / Same / Worse feedback**: after a flight, **Worse** restores the backup made before the fix and suggests the next fix.
- **Optional AI mode** (off by default, your own key): OpenAI-compatible (with a configurable base URL and model, so local servers work too) or Anthropic.
  - A privacy note lists exactly what is sent. No file paths, user names or add-on lists are sent.
  - Answers must be strict JSON. Only whitelisted settings and value ranges are accepted.
  - If the AI fails or times out, SkyTune falls back to its offline answer.
  - Keys are stored with Windows DPAPI where available. Otherwise they go in a plain file, with a clear warning. There's a **Remove key** button, and no key ships with SkyTune.
- **My preferences**: a collapsed section with a one-line summary for edge smoothing (TAA / DLSS / FSR), extra frames (frame generation) and traffic. Traffic now defaults to *SkyTune decides*. Your choices are never overridden unless your message to the assistant is about them.
- **Tools row**: **⚡ Fix stutters** and **↻ Update Cleanup**, each with a one-line explanation, plus *Choose caches…* and *Undo Update Cleanup* links.
- **Remembers your choices** between runs (goal, preferences, whether the section is open) in `%APPDATA%\SkyTune\state.json`.
- **Friendlier wording**: no jargon in the simple view ("Smooth edges", "Extra frames", "Ground sharpness at a distance"…), and tooltips explain the terms. Advanced settings is unchanged.
- Fixed: the simple view could fall back to one column after the assistant answered, when the scrollbar appeared, on Windows font metrics.
- Version info now says 1.3.0 / "SkyTune for MSFS 2020 and 2024". The test suite has 150 tests.

## v1.2.1 (base for v1.3.0)
- Supports MSFS 2020 and MSFS 2024 (Steam and MS Store/Xbox, with a choice when both are installed). Update Cleanup is limited to MSFS 2024.
- Traffic Off fix: Off writes `-1` and Low writes `0` for the supported traffic and people settings.
- Frame generation is Off by default. AMD FSR upscaling is offered.

## v1.0.0 – 2026-10-21 (initial release)
- **Simple view**: welcome with three steps, a **What matters most to you?** goal picker (Best visuals / Balanced / Smooth & steady), a big **Auto-detect & Optimise** button, a plain-English "What will change" summary, a big **Apply** button and **Undo (restore last backup)**. Manual presets (Performance / Balanced / Quality / Ultra+) are in Advanced settings.
- **Goals**: auto-detect combines your hardware score with your goal and explains the result in plain English. Smooth & steady lowers CPU-heavy settings and sets a frame-rate cap (`FrameLimiter`).
- **Traffic level**: one dropdown (Off / Low / Medium / High / Ultra) for all confirmed traffic types, never overridden by goals or presets; per-type controls in Advanced.
- **Fix stutters and Clean up caches**: one click clears the sim cache folder and the Windows, NVIDIA and AMD shader caches linked to stutters; a checklist with live sizes also covers the rolling cache (ROLLINGCACHE.CCC in the Steam roaming folder or Store LocalCache), scenery indexes and old crash reports. Unconfirmed items (tmcache, RAIDumps) and profile/aircraft/mission/WASM folders are never touched. Whitelisted folders only, protected folders never touched, locked files skipped, confirmation shows the total size, blocked while the sim runs.
- **Your choices**: Anti-aliasing (TAA / NVIDIA DLSS) and Frame generation (Off / AMD FSR 3 / NVIDIA DLSS FG) dropdowns. The default is TAA + AMD FSR 3, and presets and auto-detect always keep your choice. DLSS options are hidden when the detected GPU can't use them (DLSS FG needs RTX 40/50 + HAGS).
- **Sim status light**: green "Sim closed – safe to apply" or red "MSFS 2024 is running – close it first", refreshed every few seconds. Apply and Undo are blocked while the sim runs.
- **Hardware auto-detect**: GPU, VRAM (registry qwMemorySize), CPU, RAM and display. A documented scoring table picks a preset, and the reasoning is shown before anything is applied. Includes a Balanced variant tuned to stay above 30 FPS at busy airports on 8 GB GPUs.
- **Advanced settings**: every in-game setting (render scaling, upscaler modes, LODs, textures, clouds, shadows, effects, buildings and vegetation, traffic and people) plus beyond-menu values (terrain detail up to 800, object detail up to 400, 4096 shadows, shadow cascades, parallax distances). Screen resolution is only changed if you opt in.
- **Update Cleanup**: after a sim update – backs up UserCfg.opt, renames Community to Community-old (never deletes; found via InstalledPackagesPath), creates a fresh Community folder, asks whether to keep current graphics (default) or reset to safe defaults, clears stutter caches and rebuilds scenery indexes. All-or-nothing with rollback, logged, and **Undo Update Cleanup** with safe merging.
- **Safety**: a timestamped backup before every write, one-click Undo, and a parser that keeps the file byte-for-byte apart from the changed values. Steam settings file detected first, with MS Store/Xbox as fallback.
- **Works on any PC**: GPU tiers from GTX 900 / RX 400 to RTX 50 / RX 9000, Intel Arc, integrated and laptop chips (discrete preferred, virtual adapters ignored, unknown GPUs judged by VRAM); CPU tiers incl. hybrid and X3D. Layered detection (registry → PowerShell → WMIC → dxdiag, with time limits) and **Pick my GPU…** if nothing is found. Ultrawide/4K aware; DPI-aware, resizable, scrollable window.
- **Linux and Steam Deck (Proton)**: finds the MSFS 2024 prefix (app 2537590) in native, Flatpak and Snap Steam and all libraries; runs natively with Python + Tk or via protontricks-launch; Linux detection (/sys, lspci, /proc, xrandr) and Linux shader caches; Steam Deck profile.
- **Missing or damaged UserCfg.opt**: offers to restore a backup or explains how to let the sim write a fresh one. Non-UTF-8 bytes and non-ASCII paths preserved.
- **Small screens**: works at 1280×800 (Steam Deck), 1024×600 and 1366×768 at 125–150% scaling. Apply and Undo stay in a fixed footer, "What will change" scrolls on its own, the whole simple view scrolls, columns and header stack on narrow windows, the file path is shortened in the middle (full path on hover), and text wraps to the window width.
- Dark aviation-style interface, single-file `SkyTune.exe` with embedded icon and version info.
