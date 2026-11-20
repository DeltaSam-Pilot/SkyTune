# SkyTune — Graphics and Compatibility Details

## Compatibility statement

SkyTune v1.8.1 targets **Microsoft Flight Simulator 2020 and Microsoft Flight Simulator 2024 on PC**. Windows 10/11 x64 is the primary supported environment. Steam and Microsoft Store/Xbox app installations are detected at the common configuration locations, and a manual file picker is available for custom locations.

Linux / Steam Deck support is experimental and intended for users who already run a simulator edition through Steam Proton. The tool can be launched with Python 3 + Tkinter, but Microsoft does not officially support running MSFS on Linux. Xbox consoles cannot run third-party desktop utilities. macOS is not a supported simulator host.

No third-party utility can guarantee compatibility with every past, future, beta or modified simulator build. To avoid assuming that an unknown version has the same schema, SkyTune changes only recognised settings which already exist in the selected `UserCfg.opt`. Newly introduced or unknown keys are preserved. Auto-detection can be bypassed with **Browse…**.

## The simple view (v1.3.2)

1. **Check my PC** runs hardware detection and shows a one-line result, such as "✓ GPU (8 GB) · CPU · 32 GB memory · 2560 × 1440 screen · found MSFS 2024". *Details* opens the full reasoning. *Wrong graphics card?* lets you pick your card.
2. **What matters most?** sets the goal (below). **Anything bothering you?** is optional (see *Assistant*).
3. **Optimise my sim** lists every setting that will change, from and to. The footer button writes them after making a backup. If you click it before checking your PC, SkyTune checks first.

Under **My preferences**: Smooth edges = anti-aliasing/upscaler (TAA, NVIDIA DLSS, AMD FSR). Extra frames = frame generation (Off, AMD FSR, NVIDIA DLSS FG). Traffic & people = one level for all supported traffic and population settings, or *SkyTune decides*. Goals and presets never override these choices.

Your goal, preferences and whether the section is open are remembered in `%APPDATA%\SkyTune\state.json` (`~/SkyTune/state.json` when run natively on Linux). Problem buttons you select are not remembered. Advanced settings: the *IN FILE* column shows readable labels (Off / Low / Medium / High / Ultra, AMD FSR, NVIDIA DLSS FG), and frame-generation-only controls (the frame multiplier) are greyed out and never written while frame generation is Off.

**Several problems at once (v1.3.1).** The quick buttons are toggles. Everything selected is combined with any typed text into one diagnosis: each problem gets its own likely-cause line, and the fixes are merged into one ranked list (up to 6, or 8 for three or more problems). A setting is only changed by one fix, so fixes never contradict each other; each fix shows which of your problems it helps with. In AI mode, the prompt lists all selected problems.

## Assistant

The assistant runs **offline**. It matches your words, with typos tolerated, against six problem types: stutters, low FPS, blurry image, pop-in, crashes, and problems after an update. It uses the detected hardware and current settings to name a likely bottleneck (graphics card, video memory, processor / main thread, caches, or add-ons) and gives a confidence label: high, medium or low. Hover over the label to see the reasons. Fixes are ranked by expected impact for your PC, and each one shows its trade-off. Fixes never change your Smooth edges, Extra frames or Traffic choices unless your message mentions them. Settings fixes are only staged, and nothing is written until **Optimise my sim**. Tool fixes (Fix stutters, Update Cleanup) ask before running.

After applying, rate your next flight **Better / Same / Worse**. **Worse** restores the backup made just before that fix, then suggests the next fix. SkyTune cannot read your frame times itself, so without a readout these are informed suggestions, not measurements.

**Paste the sim's own readout for a better answer.** In MSFS 2024, Developer Mode → Debug → Display FPS shows what limits the frame. If your message includes it, for example "51 fps, Limited by Graphics Queue, GPU 32.6 ms, main thread 25.4 ms, LOD factor 0.50", the assistant reads it:
- *Limited by Graphics Queue / GPU* or *Limited by Main Thread* is treated as a measurement and outweighs guesses from symptoms. For example, "busy airport" alone points at the processor. When GPU and main-thread times differ by 12% or more, the longer one also counts.
- When the graphics card is measured as the limit, only graphics-card fixes are offered (lighter clouds, shadow maps down to 1024, render scale 90% with TAA). Traffic and object distance mostly cost processor time, so they are not suggested.
- Terrain/Objects/Buildings LOD factor readouts of **0.50** mean the sim's **Dynamic Settings** has already halved those distances to chase its frame-rate target; 0.50 is its minimum. SkyTune says so and suggests lowering the target or turning Dynamic Settings off for steady detail, rather than lowering LOD further. SkyTune does not change Dynamic Settings itself.
- Numbers in a readout ("LOD factor", "frame time … ms") are not mistaken for a pop-in or stutter complaint.

**Low FPS or stutter right after loading in (spawning).** This is its own problem type, "Slow after loading in". Words like *spawning*, *loading into*, *right after loading* or *first minute* trigger it, and "loading" alone no longer counts as pop-in. For the first minute or two after spawning, the sim is still streaming scenery, compiling shaders and filling its rolling cache, so a deep dip is normal. Shader compilation takes longer after you clear shader caches or after a driver or sim update. The assistant:
- says it's a temporary dip, not a settings problem, and suggests waiting a minute or two on the ground before judging FPS. Confidence is high if you say it settled afterwards. If you didn't, it asks you to report back when FPS hasn't recovered after 2–3 minutes;
- advises against clearing shader caches before every flight, because that makes every load-in slow again. It doesn't offer cache clearing, Update Cleanup or general graphics cuts for this problem;
- offers only load-in fixes, and only when they apply: off-screen terrain pre-caching at a sensible level (High, or Medium with less than 8 GB of video memory), and Terrain LOD at 2.00 or lower (1.50 below 8 GB) when it's set higher on a card with 8 GB or less. It explains this as a VRAM issue;
- doesn't treat a crash during loading as a temporary dip.

## Optional AI mode (your own key)

AI mode is off by default and needs your own API key. Supported providers:
- **OpenAI-compatible:** default base URL `https://api.openai.com/v1`. The base URL and model are configurable, so other compatible services or a local server (`http://localhost…`) also work. Plain `http://` is only accepted for this computer.
- **Anthropic.**

The default model names are only a starting point. Change them in *AI settings* if your provider has retired them.

**What is sent:** only what you typed (and earlier messages in this chat), a hardware summary (graphics card, video memory, processor, cores, memory, screen size), your goal, the simulator version, and the current values of the settings SkyTune can change. No file paths, user names, add-on lists or other files are sent. Requests go directly from your PC to the provider; SkyTune has no server.

The reply must be strict JSON. Any setting outside SkyTune's whitelist, or any value outside its allowed range, is dropped. If the provider errors, times out (20 s) or returns something invalid, SkyTune shows its offline answer and says so.

**Key storage:** on Windows, the key is encrypted with DPAPI for your Windows account (`%APPDATA%\SkyTune\api_key.dpapi`). Where DPAPI isn't available, it is saved as a plain-text file (`api_key.txt`), and SkyTune warns you first. **Remove key** deletes it. SkyTune never ships with a key.

## User goals

| Goal | Behaviour |
|---|---|
| **Best visuals** | Steps quality up where detected hardware resources appear sufficient; VRAM limits texture choices. Expensive ray-traced shadows/displacement mapping are reserved for high-end hardware. |
| **Balanced** | A general starting point that balances visual detail and frame time. |
| **Smooth & steady** | Reduces CPU-heavy traffic/detail and can apply a frame-rate cap to favour consistent frame pacing. |

These profiles are starting points, not FPS guarantees. Aircraft, airports, weather, traffic, add-ons, drivers, background work and simulator updates materially affect performance.

## Manual profiles

Advanced settings includes Performance, Balanced, Quality, Ultra+ and Balanced-30. Ultra+ is intentionally kept at TLOD 300, OLOD 200 and 2048 shadow maps rather than forcing extremely high values by default. Beyond-menu controls remain available for informed manual tuning.

## Real-world data point (one sample, not a benchmark)

One user's report with SkyTune v1.2.1/v1.3.0 settings applied (Balanced-30, chosen automatically for this PC):

| | |
|---|---|
| PC | NVIDIA RTX 3070 Ti 8 GB · AMD Ryzen 7 8700F · 32 GB · 1920×1080 |
| Sim | MSFS 2024 (Steam), iniBuilds A320neo V2, on the ground at EGLL London Heathrow (a heavy airport) |
| Dev-mode overlay | ~51 FPS, **Limited by Graphics Queue** (GPU-bound); GPU queue ~32.6 ms vs main thread ~25.4 ms |
| LOD factor readouts | Terrain / Objects / Buildings 0.50, i.e. Dynamic Settings at its floor |

What it tells us:
- Balanced-30 aims for at least 30 FPS before frame generation at busy airports. One of the heaviest airport and airliner combinations still gave about 51 FPS, so the target held here.
- The low traffic and people settings kept the processor out of the way: the main thread was faster than the graphics queue. If you want more FPS on this kind of PC, change graphics-card settings (clouds, shadows, render scale), not LOD or traffic. Dynamic Settings had already halved LOD.
- The millisecond values and the FPS figure don't convert directly into each other: the overlay's queue timings overlap within a frame, and generated frames are counted if frame generation is on. Use them to compare against each other, not as frame times.
- **Loading in:** while spawning at EGLL, the same user briefly saw about **5.8 FPS** before it settled around 51 FPS. Whether it fully recovered on that flight is not yet confirmed. A dip like that during load-in is expected (scenery streaming, shader compilation, rolling-cache fill) and isn't the settled frame rate. It's a test case too (`tests/test_loading_in.py`): the assistant must call it a temporary loading dip, must not blame the processor or suggest clearing shader caches, and asks you to report back if FPS hasn't recovered after 2–3 minutes.
- This is a single sample from one flight. Weather, time of day, add-ons, drivers and sim updates change the result. It's a regression test case for the assistant (`tests/test_real_world.py`: it must call this GPU-bound), not a performance promise.

## Upscaling and frame generation

- **TAA:** broad GPU compatibility and a useful baseline.
- **NVIDIA DLSS:** availability depends on compatible NVIDIA hardware and the simulator's own implementation.
- **AMD FSR:** broad GPU support; exact implementation depends on the simulator and driver.
- **Frame generation:** off by default. Frame generation can smooth displayed motion but does not improve simulation/input latency. Aim for a stable base frame rate before enabling it. DLSS Frame Generation requires compatible RTX hardware; generated-frame multiplier options depend on supported hardware and simulator implementation.

If the simulator crashes or behaves unexpectedly after changing settings, use **↶ Undo** (Advanced: **Undo (restore last backup)**) or set *Extra frames* (frame generation) to Off in **My preferences**.

## Hardware detection

SkyTune estimates GPU model and video memory, CPU, system memory, and display resolution where the host exposes these details. Windows detection uses multiple fallbacks; Linux detection depends on available system tools. Unknown GPU models can be selected manually. If detection is incomplete, review the detected system and choose conservatively instead of treating the recommendation as exact.

## Performance and threads (v1.3.2)

- Slow work never runs on the window's thread: the hardware check, cache scans and sizes, and the sim-running check run on background threads and hand their result back to the window. A spinner shows in the status bar while they run.
- The hardware check result is stored in `state.json` (`hw_cache`, next to SkyTune's other remembered preferences) together with the date and a machine ID. It is reused for up to 30 days on the same PC. **Re-check** runs a fresh check. Nothing leaves your PC.
- The sim-running check reads one process snapshot (Windows Toolhelp; `/proc` on Linux) instead of starting `tasklist`/`ps`. It runs every 4 s, or every 15 s while SkyTune is minimised, and the window only redraws the light when the state changes.
- Network, encoding and fuzzy-matching modules are imported on first use.
- The exe build leaves out modules SkyTune never uses (`unittest`, `pydoc`, `doctest`, `pdb`, `xmlrpc`, `sqlite3`, `lib2to3`, `tkinter.tix`, `asyncio` and similar). It is not UPX-packed, as UPX often causes antivirus false alarms.

## Creator setups (v1.7.0)

Two built-in setups are offered only when the loaded file is detected as MSFS 2024. They are not hardware scores and they are not goals. Choosing one copies verified values into the on-screen settings. The simulator file changes only after **Yes, write**.

The values come from settings shown in EasyjetSimPilot's video (https://youtu.be/Mq63dyne32g), paused around 9:03–9:24, for MSFS 2024 Sim Update 7 on a Ryzen 7 3700X, RTX 3060 12 GB, 32 GB RAM and a 1080p screen. SkyTune does not claim the creator endorses this program. A 240 Hz screen without variable refresh may need V-Sync or a frame cap. V-Sync itself is not a setting SkyTune writes. No frame rate is promised.

Only keys in SkyTune's settings table are written. Terrain LOD 125 is `1.25`, objects LOD 100 is `1.0`, texture High is `1` (that scale is inverted in the file), clouds Ultra is `3`, frame generation AMD FSR is `FSRFG`, and the 2x multiplier is `1`. Traffic Off is `-1` and Low is `0`. Resolution and display mode are not included.

The 8 GB variant changes only terrain LOD to `1.0`, off-screen pre-caching to Medium (`1`), and clouds to High (`2`). Texture stays High. The Step 3 list shows those three differences.

Saved profiles can be compared with either setup. The comparison does not write.

Settings left out, because SkyTune has no verified control for them: HDR10, exposure compensation, V-Sync and its interval, NVIDIA Reflex, dynamic settings, depth of field, motion blur, particles, character variety and quality, airport-services variety, parked-aircraft variety, aircraft-traffic variety, and seatbelts.

## Since last write (v1.6.0)

Microsoft Flight Simulator rewrites `UserCfg.opt` when it exits and when graphics are changed in its menu. After every confirmed write and every checked restore, SkyTune stores the known settings from that file in `state.json` under `last_apply`. The record is an edition (`2020`, `2024`, or `unknown`) and raw values for settings SkyTune already understands. Resolution is not stored. A value that contains a slash, a backslash, or anything that looks like an API key is not stored. The settings path and the account name are not stored.

On the next open, Step 3 compares that record with the file. It lists the label SkyTune wrote and the label in the file now. **Keep the sim's values** removes those paths from the pending list. **Include them again** puts them back. The file changes only after **Yes, write** or **Yes, restore**. A 2020 record is not compared with a 2024 file. A record that fails the same checks is ignored, and Step 3 says SkyTune has not written yet.

## Flight situations, confirm button and diagnostic (v1.5.0)

**This flight** is a situation you choose, not a diagnosis of a problem. Busy airport reduces traffic and object distance unless you have already set a traffic level. VFR scenery raises terrain and trees only up to a cap that depends on video memory. Airliner cockpit raises instrument sharpening and glass-cockpit refresh, and steps clouds down. Smooth-edges and extra-frames choices are kept. The situation only changes the on-screen list.

In the simple view, **Optimise** and **Undo** arm a **Yes, write** or **Yes, restore** button. **Cancel** writes nothing. The write still makes a backup and a review note. Restore still re-reads the file and puts the previous copy back if the check fails. Advanced settings still uses a Yes/No question because that view has no footer bar.

**Save diagnostic…** asks where to save a text file. The file contains version, whether the sim is running, the edition, a path with the account name replaced by `<user>`, hardware names, goal, preferences, profile names and a backup count. It does not contain an API key and it is not sent anywhere.

**Compare** in Saved profiles lists the difference between a profile and the loaded file and does not write.

## Saved profiles, review notes and checked restore (v1.4.0)

Profiles are JSON documents (`format` `skytune-profile`, version 1) in the SkyTune data folder, not in the simulator folder. On Windows that is `%APPDATA%\SkyTune\profiles`. When SkyTune runs natively on Linux it is `~/SkyTune/profiles`, beside `state.json`. Each file holds a name, an optional note, the goal, the sim edition the profile was saved from, and values for settings SkyTune already knows. Display resolution is omitted. Values outside the allowed range, including the wider beyond-menu range where a setting has one, are rejected. A profile never adds a key the selected `UserCfg.opt` does not already contain.

Using a profile copies those values into the on-screen settings. The write still goes through the same confirmation as Optimise / Apply: the dialog lists the before → after changes and does nothing if you choose No. A backup is taken first, then the temp file is parsed before it replaces `UserCfg.opt`.

The review sidecar (`UserCfg_<timestamp>.review.json`) sits next to that backup. It records labels and raw-to-label text, a reason, an optional profile name, and a SHA-256 of the backup bytes. It does not record the settings path, the Windows profile path, or API keys. If a note looks like a pasted key, the change list is left out and the review says so. Backups from 1.3.2 and earlier have no sidecar; Review backups compares the two files instead.

Restore refuses a missing file, the live settings file itself, an empty file, or a file that does not parse as a `{Graphics}` / `{Video}` config. It warns when the backup's edition and the current file's edition are 2020 and 2024 the other way around. After the copy, SkyTune loads both files and compares every key. A mismatch copies the safety backup (the pre-restore file) back over the settings file.

No frame-rate numbers were added. The single real-world sample already in this document is still one flight, not a benchmark.

## File handling and safety

- Typical Windows locations are checked for both Steam and Store/Xbox app installs. Custom installs can be selected manually.
- On Steam Proton, SkyTune checks the common Steam roots and listed libraries for simulator prefix settings.
- The editor preserves entries it does not understand and does not add absent graphics keys.
- Backups are stored beside the selected settings in `UserCfg_backups`.
- Close the simulator before changes. The simulator may rewrite `UserCfg.opt` on exit or when the in-game graphics menu changes.
- **Update Cleanup is validated for MSFS 2024 only**; the workflow is disabled for MSFS 2020 to avoid changing an unverified folder layout.

## Tests

Run `python -m unittest discover -s tests -v` from the `source` directory. The tests cover parsing, settings discovery, hardware detection, path detection, safe cleanup, rollback, the assistant (problem matching, ranking, locked preferences, Worse → auto-undo, sim-overlay readouts including the real-world GPU-bound case, the load-in / spawning dip), AI response validation against a local mock server, key storage, remembered preferences, saved profiles, review notes, checked restore, flight situations, the local diagnostic text, and the simple-view layout at small screen sizes (1024×600, 1280×800, 1366×768 at 125–150%). v1.3.2 shipped 207 tests; v1.4.0 adds `tests/test_v140.py`; v1.5.0 adds `tests/test_v150.py`; v1.6.0 adds `tests/test_v160.py`; v1.7.0 adds `tests/test_v170.py`. One extra test drives the built `dist/SkyTune.exe` through confirm, backup, restore and rollback on a fixture file, and is skipped when that exe is not present. Tests write only under temporary directories.

SkyTune is an independent community project and is not affiliated with Microsoft or Asobo Studio.


## Traffic Off behaviour

The master Traffic level "Off" writes `-1` into each supported traffic/population quantity key in `UserCfg.opt`; `0` is Low and is kept separate. This includes AI aircraft, parked aircraft, ground services, people, road traffic, sea traffic and wildlife where those keys exist in the selected graphics schema. It does not change the separate in-game Online Aircraft Traffic Type or Multiplayer settings.
