# SignalRGB Desktop Wallpaper

[![Release](https://img.shields.io/github/v/release/Delido/signalrgb-wallpaper?include_prereleases&sort=semver)](https://github.com/Delido/signalrgb-wallpaper/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue)

Use your current SignalRGB effect as a glow layer on your desktop wallpaper.
Up to **3 monitors**, each configurable separately. Renders inside
[Lively Wallpaper](https://www.rocksdanister.com/lively/) as a regular Web
wallpaper — no proprietary host, no custom shaders.

The principle: a PNG with **transparent cut-outs** (windows, signs, neon
strips, whatever) sits on top of a coloured glow layer. The glow comes from
the live SignalRGB canvas, so anything you cut transparent shines in
whatever colour your current effect is producing right now.

> **Status:** v0.2.0 — first public release. Bridge + tray + multi-screen
> all working. Inno Setup installer planned for the next minor release.

## Features

- **Live RGB glow** behind a transparent background image, 60 fps target
- **1–3 monitor support** with independent settings per screen
- **System tray dialog** for everything: background per screen, glow layout
  (pixel grid / stripes / pills / off), strength, dim, blur — live apply
- **Standalone bridge** as a single `.exe` (no Python required)
- **Stable wire protocol** — UDP from plugin to bridge, WebSocket from
  bridge to wallpaper, well-defined frame format

## Requirements

- Windows 10/11
- [SignalRGB](https://www.signalrgb.com/) installed and running
- [Lively Wallpaper](https://www.rocksdanister.com/lively/) — **GitHub
  installer build** (the Microsoft Store / MSIX build is fine too for
  Web-type wallpapers, but we recommend the GitHub build)

## Quick start

### Easy path: installer (since v0.4.0)

1. Grab `SignalRGBWallpaperSetup-<version>.exe` from
   [Releases](https://github.com/Delido/signalrgb-wallpaper/releases).
2. Run it. No admin needed — installs per-user into
   `%LOCALAPPDATA%\Programs\SignalRGBWallpaper\`. Keep both opt-in
   tasks checked: it installs the SignalRGB plugin into your
   `Documents\WhirlwindFX\Plugins\` folder and registers the bridge to
   start on logon.
3. The installer opens the "Lively wallpapers" subfolder at the end —
   drag `SignalRGB_Glow_Screen1.zip` (and Screen2/Screen3 if you have
   multiple monitors) onto Lively to import them.
4. In SignalRGB: right-click the bridge's tray icon → **Settings…** →
   "Number of screens" = how many monitors you want to drive.
5. Place the "Desktop Wallpaper - Screen N" devices on SignalRGB's
   canvas at the positions you want colours sampled from.
6. Activate the matching Lively wallpaper on each monitor. Pick
   background images in the tray Settings → per-screen tabs, or use
   the built-in **Build Wallpaper…** tool in the tray menu.

Uninstall via Windows Settings → Apps, or run `unins000.exe` in the
install folder.

### Manual path

If you'd rather not run an installer, grab the individual artefacts
from the same release page and place them yourself:

| File | Where it goes |
| --- | --- |
| `SignalRGBBridge.exe` | Anywhere stable (e.g. `C:\Tools\SignalRGBWallpaper\`) |
| `SignalRGB_Desktop_Wallpaper.js` + `.qml` | `Documents\WhirlwindFX\Plugins\` |
| `SignalRGB_Glow_Screen{1,2,3}.zip` | Drag into Lively |

Then run `SignalRGBBridge.exe` and proceed with steps 4–6 above.
Full step-by-step with screenshots: [docs/installation.md](docs/installation.md).

## Documentation

- [Installation guide](docs/installation.md) — the long version of the
  quick start, with screenshots and Windows path notes
- [Tray settings reference](docs/tray-settings.md) — what every slider
  and dropdown does
- [Multi-screen setup](docs/multi-screen-setup.md) — placing devices on
  the SignalRGB canvas, assigning Lively wallpapers to monitors
- [Building glow wallpapers](docs/building-wallpapers.md) — picking a
  source image, GIMP workflow to cut transparent regions, what looks good
- [Troubleshooting](docs/troubleshooting.md) — when the wallpaper stays
  black, when SignalRGB doesn't show the device, when the tray dies
- [Architecture](docs/architecture.md) — wire formats, threading model,
  why the components are split the way they are
- [Building from source](docs/building-from-source.md) — PyInstaller
  build, packaging the Lively zips, dev loop

## How it works (one paragraph)

The SignalRGB plugin registers as a virtual network device, samples
SignalRGB's effect canvas every frame, and sends each frame as a UDP
datagram to `127.0.0.1:17320` with a screen-index byte. The bridge
(`SignalRGBBridge.exe`) listens on UDP 17320 and runs a WebSocket server
on the same port. The Lively wallpaper is an HTML page that connects to
`ws://127.0.0.1:17320/?screen=N` and renders the received colours as a
CSS-grid glow layer behind a transparent background image. The bridge
also hosts a tray icon for per-screen settings (background image, layout,
glow strength, etc.) which it pushes live to the wallpaper page over the
same WebSocket. Full architecture: [docs/architecture.md](docs/architecture.md).

## Contributing

Issues and PRs welcome. Bug reports should include:

- Windows version (Win+R → `winver`)
- SignalRGB version (Settings → About in SignalRGB)
- Lively version (Settings → About in Lively) — **say whether it's the
  Microsoft Store or GitHub build**
- The bridge log if relevant: run `SignalRGBBridge.exe` from a CMD
  window (so stdout is visible) or run `python wallpaper_bridge\bridge.py`
  directly

## License

[MIT](LICENSE) © 2026 Delido
