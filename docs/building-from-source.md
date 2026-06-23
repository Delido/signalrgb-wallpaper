# Building from Source

You only need this if you're modifying the bridge / plugin / wallpaper
HTML / Configurator / Builder, or producing your own release artefacts.
End users grab pre-built files from the
[Releases page](https://github.com/Delido/signalrgb-wallpaper/releases).

## Prerequisites

- **Windows 10/11**
- **Python 3.11+** with `pip` on PATH. Get it from
  [python.org](https://www.python.org/downloads/) or
  `winget install Python.Python.3.13`.
- **PowerShell 7** (`pwsh`) — the build script uses pipeline chain
  operators and `&&`. Windows-built-in 5.1 doesn't work.
  `winget install Microsoft.PowerShell`.
- **Inno Setup 6** for the installer — `winget install JRSoftware.InnoSetup`.
- *Optional:* the [GitHub CLI](https://cli.github.com/)
  (`winget install GitHub.cli`) if you plan to push releases.

## Initial setup

```powershell
git clone https://github.com/Delido/signalrgb-wallpaper.git
cd signalrgb-wallpaper

# Python deps for the bridge + build tooling
python -m pip install --user pystray Pillow psutil pyinstaller
```

`tkinter` is part of the Python Windows installer; no separate install
needed. Everything else (asyncio, json, threading, hashlib, struct,
mimetypes, webbrowser) is in the stdlib.

## One-shot build (preferred)

```powershell
pwsh installer\build.ps1
```

Stages:

1. Generate `icon.ico`, `thumbnail.png`, `banner.png`,
   `workshop_preview.png` via the four `installer/generate_*.py`
   scripts.
2. Rebuild `SignalRGBBridge.exe` with PyInstaller.
3. Stage three per-screen Lively folders
   (`wallpaper_bridge/lively_bundles/signalrgb-glow-screen-{1,2,3}/`)
   and the matching `SignalRGB_Glow_Screen{1,2,3}.zip` files.
4. Stage the single combined Wallpaper Engine bundle
   (`we_bundles_single/signalrgb-glow/`, with the `screenIndex` user
   property).
5. Stage three per-screen Wallpaper Engine bundles
   (`we_bundles/SignalRGB_Glow_Screen{1,2,3}/`).
6. Package the Lively pause-tester
   (`SignalRGB_LivelyPauseTester.zip`).
7. Compile `installer_out\SignalRGBWallpaperSetup-<version>.exe` via
   Inno Setup.

Version is read from `APP_VERSION` in `wallpaper_bridge/bridge.py`. To
override: `pwsh installer\build.ps1 -Version 0.7.2`.

## Building `SignalRGBBridge.exe` by hand

If you only need the bridge exe (no installer, no wallpaper bundles):

```powershell
cd wallpaper_bridge

python -m PyInstaller `
  --onefile `
  --noconsole `
  --name SignalRGBBridge `
  --hidden-import pystray._win32 `
  --collect-all pystray `
  --collect-submodules PIL `
  --collect-all psutil `
  --add-data "builder.html;." `
  --add-data "configurator.html;." `
  --add-data "help.html;." `
  --distpath dist_bridge `
  --workpath build_bridge `
  bridge.py

# Output: wallpaper_bridge\dist_bridge\SignalRGBBridge.exe  (~20 MB)
```

Flags explained:

- `--onefile` — single self-contained exe; users don't need Python.
- `--noconsole` — no console window when launched (we're a tray app).
  To debug, temporarily drop this flag and rebuild — stdout will be
  visible in cmd.
- `--hidden-import pystray._win32` + `--collect-all pystray` —
  PyInstaller's static analyser misses pystray's Win32 backend.
- `--collect-submodules PIL` — Pillow's image loaders are lazy-loaded;
  this pulls them all in so the tray icon + About-dialog avatar work.
- `--collect-all psutil` — psutil ships native `.pyd` extensions for
  the OS-specific syscalls behind the CPU / RAM / Network widgets.
- `--add-data "builder.html;."` + `"configurator.html;."` + `"help.html;."` — bundles
  the two in-browser UIs served at `/builder` and `/configurator`.

### Quick rebuild loop during development

When iterating on `bridge.py`, save the full PyInstaller cycle by
running the Python source directly:

```powershell
cd wallpaper_bridge
python bridge.py
```

You get a real console with stdout — ideal for debugging. The tray
icon, Configurator, legacy Settings dialog, WS server etc. all work
identically.

## Smoke-testing the bridge

`wallpaper_bridge/smoke_test.py` opens two WS subscribers (`?screen=0`
and `?screen=1`) and verifies that a fake UDP datagram tagged for one
screen reaches only that screen's clients.

```powershell
# Start the bridge first
.\wallpaper_bridge\dist_bridge\SignalRGBBridge.exe
# In another shell
python .\wallpaper_bridge\smoke_test.py
```

> The smoke test will misreport `FAIL` if SignalRGB is actively
> streaming frames through the bridge at the same time (its WS clients
> pick up real plugin traffic mixed with the test payload). Stop
> SignalRGB or unpair the plugin before running it.

## Publishing a release (maintainer notes)

1. Bump `APP_VERSION` in `wallpaper_bridge/bridge.py` and the
   `Version()` export in `SignalRGB_Desktop_Wallpaper.js`. Add an
   entry to `CHANGELOG.md`.

   **Also add a `RELEASE_NOTES` entry for the new version** in
   `wallpaper_bridge/bridge.py` (the constant just below
   `APP_VERSION`). The Configurator's "What's new" modal reads
   this on every settings push; without a matching key the
   modal falls back to a generic "Bridge updated — see GitHub
   changelog" stub. Keep the body short and user-facing (3-5
   bullets, EN + DE), full per-commit detail stays in
   `CHANGELOG.md`. The modal auto-fires once after each
   `APP_VERSION` change because the bridge writes the live
   version into `bridgeState.appVersion` and the Configurator
   compares against the persisted `lastSeenAppVersion`.
2. `pwsh installer\build.ps1` — produces the installer + all release
   artefacts.
3. Commit, tag, push:

   ```powershell
   git add -A
   git commit -m "vX.Y.Z: <one-line summary>"
   git tag vX.Y.Z
   git push origin main --tags
   ```

4. Create the release with artefacts:

   ```powershell
   gh release create vX.Y.Z `
     --title "vX.Y.Z" `
     --notes-file CHANGELOG.md `
     installer_out\SignalRGBWallpaperSetup-X.Y.Z.exe `
     wallpaper_bridge\dist_bridge\SignalRGBBridge.exe `
     wallpaper_bridge\SignalRGB_Glow_Screen1.zip `
     wallpaper_bridge\SignalRGB_Glow_Screen2.zip `
     wallpaper_bridge\SignalRGB_Glow_Screen3.zip `
     wallpaper_bridge\SignalRGB_Glow_WallpaperEngine.zip `
     wallpaper_bridge\SignalRGB_Glow_WE_Single.zip `
     SignalRGB_Desktop_Wallpaper.js `
     SignalRGB_Desktop_Wallpaper.qml
   ```

   Add `--prerelease` for beta tags (e.g. `0.7.2-beta`); the in-app
   update checker honours the *Allow beta versions* checkbox to
   decide whether to surface them.

5. Verify on the [Releases page](https://github.com/Delido/signalrgb-wallpaper/releases).
6. If you also want the Wallpaper Engine Workshop items updated, see
   [`workshop-publishing.md`](workshop-publishing.md) — that part is
   manual (no headless Steam API for it).
