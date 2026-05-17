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

> Until the Inno Setup installer ships in a later release, setup is a
> couple of manual file copies + activating things. Five minutes total.

1. **Download the latest release** from
   [Releases](https://github.com/Delido/signalrgb-wallpaper/releases).
   You'll get:
   - `SignalRGBBridge.exe` — the bridge + tray app
   - `SignalRGB_Desktop_Wallpaper.js` + `.qml` — the SignalRGB plugin
   - `SignalRGB_Glow_Screen1.zip` / `Screen2.zip` / `Screen3.zip` — the
     Lively wallpapers (one per monitor index)
2. **Install the SignalRGB plugin** — copy both files into
   `%USERPROFILE%\Documents\WhirlwindFX\Plugins\`. Open SignalRGB; the
   "Desktop Wallpaper - Screen 1" device appears in the device list.
3. **Run the bridge** — double-click `SignalRGBBridge.exe`. The tray
   icon (RGB monitor) appears on the right side of your taskbar.
4. **Import the wallpapers in Lively** — drag the zip(s) onto Lively.
   Use `Screen1.zip` for monitor 1; if you have 2 monitors, also import
   `Screen2.zip` for monitor 2.
5. **Tell SignalRGB how many monitors you're driving** — right-click
   the tray icon → **Settings…** → "Number of screens" → set to 2 (or 3).
   SignalRGB will adjust its device list within a couple of seconds.
6. **Place the devices on SignalRGB's canvas** wherever you want the
   colours pulled from. For multi-monitor: place the "Screen 1" device
   on the left half of the canvas, "Screen 2" on the right half (or
   however makes sense for your layout).
7. **Pick background images** in the tray Settings dialog — one tab per
   screen. Done.

Full step-by-step with screenshots: see
[docs/installation.md](docs/installation.md).

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
