<div align="center">

![SignalRGB Desktop Wallpaper](docs/images/banner.png)

[![Release](https://img.shields.io/github/v/release/Delido/signalrgb-wallpaper?include_prereleases&sort=semver&style=flat-square)](https://github.com/Delido/signalrgb-wallpaper/releases)
[![Downloads](https://img.shields.io/github/downloads/Delido/signalrgb-wallpaper/total?style=flat-square)](https://github.com/Delido/signalrgb-wallpaper/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue?style=flat-square)](#requirements)
[![Sponsor](https://img.shields.io/badge/Buy_me_a_coffee-PayPal-00457C?style=flat-square&logo=paypal&logoColor=white)](https://paypal.me/SMendyka)

**Live RGB glow on your desktop, driven by your SignalRGB effect.**
Multi-monitor, fully configurable, with an in-browser wallpaper builder
and a one-click installer.

</div>

---

Use your current SignalRGB effect as a glow layer on your desktop wallpaper.
Up to **3 monitors**, each configurable separately. Renders inside
[Lively Wallpaper](https://www.rocksdanister.com/lively/) as a regular Web
wallpaper — no proprietary host, no custom shaders.

The principle: a PNG with **transparent cut-outs** (windows, signs, neon
strips, whatever) sits on top of a coloured glow layer. The glow comes
from the live SignalRGB canvas, so anything you cut transparent shines in
whatever colour your current effect is producing right now.

> **Status:** v0.4.3 — installer + multi-screen + in-browser builder
> (polygon / ellipse / region / restore-brush) + apply-to-screen +
> fullscreen auto-pause + redesigned per-screen settings dialog.

## Features

- 🌈 **Live RGB glow** behind a transparent background image, 60 fps target
- 🖥️ **1–3 monitor support** with independent settings per screen
- 🎚️ **System tray dialog** for everything: background per screen, glow
  layout (pixel grid / stripes / pills / off), strength, dim, blur — live apply
- 🖌️ **In-browser wallpaper builder** (`Build Wallpaper…` in tray) for
  carving transparent regions out of any image. Color-click, drag-region,
  polygon, ellipse, "click in region", and a **restore brush** to undo
  over-aggressive edits. Apply straight to a screen with one click, or
  save as PNG. Multi-monitor split halves an image across two screens.
- 🎮 **Auto-pause** when a fullscreen app (game, video, RDP) is active —
  glow freezes, CPU is saved, resumes within a second when you alt-tab
  out. Toggle in tray Settings.
- 📦 **One-click installer** (`SignalRGBWallpaperSetup-*.exe`, per-user,
  no admin) handles the bridge, the SignalRGB plugin, the Lively zips,
  autostart, and an Add/Remove Programs entry.
- 🔌 **Standalone bridge** as a single `.exe` (no Python required for users)
- 📡 **Stable wire protocol** — UDP from plugin to bridge, WebSocket
  from bridge to wallpaper, well-defined frame format

## Gallery

<!-- markdownlint-disable MD013 -->

| | |
| :---: | :---: |
| ![In-browser builder](docs/images/screenshot-builder.jpg) <br/> _**In-browser builder** — click colours to make them transparent, drag rectangles / polygons / ellipses, restore-brush over mistakes, save or apply straight to a screen_ | ![SignalRGB devices](docs/images/screenshot-signalrgb-devices.png) <br/> _**SignalRGB device list** — one virtual "Desktop Wallpaper" device per monitor, all under a single plugin_ |
| ![Lively library tiles](docs/images/screenshot-lively-library.png) <br/> _**Lively library** — branded tile thumbnails so you can find the wallpapers among everything else you've imported_ | ![SignalRGB device settings](docs/images/screenshot-signalrgb-device-settings.png) <br/> _**SignalRGB device settings** — grid size, target FPS, bridge port; the canvas placement controls live in SignalRGB's Layouts view_ |

<!-- markdownlint-enable MD013 -->

A short demo video of the builder + a multi-monitor scene would also
be a nice add here — even a 15-second screen recording dropped as a
GIF (`docs/images/demo.gif`) is enough.

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

## Roadmap

Loose, unordered list of things on the "would be nice" pile. No commitments
on timing — pull requests and votes (👍 on the matching issue) welcome.

- **Builder polish** — live brush cursor (circle preview at actual radius),
  more brush shapes / hardness, additional pattern fills, drag-and-drop
  image import, full undo/redo history
- **Desktop widgets** — clock, calendar, weather, and small effect
  modules that sit on top of the glow layer (opt-in per screen)
- **Simpler install** — single bootstrapper that pulls Lively if missing,
  imports the Lively zips automatically, and assigns them to the right
  screens without manual drag-and-drop
- **Reworked tray settings** — preview pane, search/jump for long lists,
  preset slots (save a "background + glow + dim + blur" combo and switch
  with one click)
- **More than 3 monitors** — lift the current hard cap to N screens
- **Localisation** — DE / EN at minimum, tray + builder + installer
- **Wallpaper preset library** — curated bundle of glow-ready backgrounds
  shipped with the installer or fetched on demand
- **Audio-reactive glow mode** — optional layer that pulses with system
  audio in addition to the SignalRGB colour feed
- **Wallpaper Engine support** — package the wallpaper as a
  [Wallpaper Engine](https://www.wallpaperengine.io/) Web project too, so
  users on the Steam app can run the glow without needing Lively

Have a wish that isn't here?
[Open an issue](https://github.com/Delido/signalrgb-wallpaper/issues/new)
and tag it `enhancement`.

## Contributing

Issues and PRs welcome. Bug reports should include:

- Windows version (Win+R → `winver`)
- SignalRGB version (Settings → About in SignalRGB)
- Lively version (Settings → About in Lively) — **say whether it's the
  Microsoft Store or GitHub build**
- The bridge log if relevant: run `SignalRGBBridge.exe` from a CMD
  window (so stdout is visible) or run `python wallpaper_bridge\bridge.py`
  directly

## Support / donate

This project is built and maintained in spare time. If it saves you the
hassle of writing your own SignalRGB → wallpaper plumbing, or if a glow
that matches your effect just makes you smile every morning, a small tip
keeps the motivation up.

<div align="center">

[![Buy me a coffee — PayPal](https://img.shields.io/badge/Buy_me_a_coffee-PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/SMendyka)

</div>

Issues, feature requests, and pull requests are also very welcome —
even just an [issue](https://github.com/Delido/signalrgb-wallpaper/issues)
with "this is broken on my machine" helps a lot.

## License

[MIT](LICENSE) © 2026 Delido
