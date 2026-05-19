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

> **Status:** v0.6.0-beta (prerelease) — full in-browser **configurator**
> with drag-and-resize layout preview, 7+ widget types
> (clock / calendar / weather / sticky note / countdown / picture / quote /
> CPU / RAM / audio spectrum), full-canvas ambient effects
> (snow / rain / sparks / aurora), cursor pixelfx (trail / hover-glow /
> click-ripple), Wallpaper Engine packaging alongside Lively, and an
> in-app GitHub update checker.

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
- **A wallpaper host** — pick at least one (the installer asks):
  - [Lively Wallpaper](https://www.rocksdanister.com/lively/) (free,
    recommended) — **GitHub installer build** preferred; the Microsoft
    Store / MSIX build also works for Web-type wallpapers
  - [Wallpaper Engine](https://www.wallpaperengine.io/) (paid, on Steam)
    — auto-detected by the installer; the three glow bundles get
    dropped straight into Steam's `wallpaper_engine\projects\myprojects`

## Quick start

### Easy path: installer

1. Grab `SignalRGBWallpaperSetup-<version>.exe` from
   [Releases](https://github.com/Delido/signalrgb-wallpaper/releases).
2. Run it. No admin needed — installs per-user into
   `%LOCALAPPDATA%\Programs\SignalRGBWallpaper\`. On the Tasks page:
   - **Wallpaper host:** check **Lively** (default) and/or **Wallpaper
     Engine**. Lively-only and WE-only setups both work; only the
     selected host's files get copied.
   - **Install SignalRGB plugin** (recommended) — drops the plugin
     into `Documents\WhirlwindFX\Plugins\` so SignalRGB can drive the
     bridge.
   - **Start bridge automatically on logon** (recommended).
3. **Lively users**: the installer opens the _Lively wallpapers_
   folder at the end — drag `SignalRGB_Glow_Screen1.zip` (and
   `Screen2.zip` / `Screen3.zip` for additional monitors) onto Lively
   to import them, then right-click → _Set as wallpaper_ on each
   monitor.
4. **Wallpaper Engine users**: if Steam + Wallpaper Engine were
   detected the bundles are already in WE's library — open Wallpaper
   Engine, find **SignalRGB Glow - Screen 1 / 2 / 3** under _My
   Wallpapers_, and assign one per monitor. If Steam wasn't detected
   the installer opens the _Wallpaper Engine wallpapers_ staging
   folder; drop the three folders into Steam's
   `…\steamapps\common\wallpaper_engine\projects\myprojects\` by hand.
5. Right-click the bridge's tray icon → **Configurator…** (the default
   action). In the browser: per-screen tabs at the top → set the
   number of screens to drive in the _Advanced → Legacy Settings_
   dialog if more than 1, then pick a background image, tweak the
   glow layout / strength, place widgets via drag-and-resize, switch
   on an ambient effect, etc.
6. In SignalRGB: place the **Desktop Wallpaper - Screen N** devices
   on SignalRGB's canvas at the positions you want colours sampled
   from. (Layouts → drag the devices.) Optionally raise *Glow Grid
   Size* in the plugin settings to `36` for a finer feed (current
   ceiling — see the roadmap for a chunked transport that would lift
   this).

Uninstall via Windows Settings → Apps, or run `unins000.exe` in the
install folder. The uninstaller also removes the three Steam-side WE
bundle folders it placed (leaves any other Wallpaper Engine wallpapers
alone).

> 💡 After updating to a new version, **re-import the Lively zips**
> in Lively (right-click the wallpaper in Lively's Library →
> _Customise / Delete_, then drag the new zip onto Lively). Lively
> caches the extracted HTML from your first import and won't pick up
> new widget / effect code otherwise. Wallpaper Engine just sees the
> new files automatically on next refresh.

### Manual path

If you'd rather not run an installer, grab the individual artefacts
from the same release page and place them yourself:

| File | Where it goes |
| --- | --- |
| `SignalRGBBridge.exe` | Anywhere stable (e.g. `C:\Tools\SignalRGBWallpaper\`) |
| `SignalRGB_Desktop_Wallpaper.js` + `.qml` | `Documents\WhirlwindFX\Plugins\` |
| `SignalRGB_Glow_Screen{1,2,3}.zip` _(Lively)_ | Drag the zip(s) into Lively |
| `SignalRGB_Glow_WallpaperEngine.zip` _(WE)_ | Extract; drop each of the three `SignalRGB_Glow_ScreenN/` folders into `…\steamapps\common\wallpaper_engine\projects\myprojects\` |

Then run `SignalRGBBridge.exe` and proceed with steps 5–6 above
(open the Configurator from the tray, place SignalRGB devices on
the canvas).
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

### Planned

- **Chunked UDP transport** — SignalRGB's plugin sandbox caps `udp.send()`
  at 4 096 bytes per datagram, which puts the per-screen glow grid ceiling
  at 36 × 36. Splitting each frame across multiple packets (the bridge
  would reassemble before broadcasting) would lift this to ~256 × 256
  without protocol drama. Touches plugin + bridge; wallpaper page is
  unchanged.
- **Whole-screen audio-reactive glow layer** — the audio spectrum widget
  shipped in 0.6.0-beta covers "audio visualiser in a box". A separate
  ambient pulse / spectrum layer behind the whole wallpaper (driven by the
  same Lively / WE FFT listener) is still open.
- **Wallpaper preset library** — curated bundle of glow-ready backgrounds
  shipped with the installer or fetched on demand
- **Simpler install** (remainder) — Lively isn't auto-imported yet;
  Wallpaper Engine auto-copy already shipped in 0.5.2-beta. A single
  bootstrapper that pulls Lively if missing and imports the zips would
  remove most of the manual setup.
- **Preset slots in the configurator** — save a
  "background + glow + dim + blur" combo per screen and switch with one click
- **More than 3 monitors** — lift the current `MAX_SCREENS = 3` cap to N
- **Localisation** — DE / EN at minimum, tray + builder + configurator +
  installer strings
- **Pattern-fill brush in the builder** — halftone / dither / hatching
  as an alternative to solid-colour transparent cuts (intentionally
  skipped during the 0.4.5 builder polish, kept on the wish list)

### Recently shipped

- ✅ **In-browser configurator** with per-screen tabs, drag-and-resize
  layout preview, prominent lock toggle, form-based widget options
  (0.6.0-beta / 0.6.1-beta)
- ✅ **Ambient effects** (snow / rain / sparks / aurora) with glow-tint
  opt-in (0.6.0-beta)
- ✅ **Pixelfx** — mouse trail, hover glow, click ripple via Lively's
  cursor callback (0.6.0-beta)
- ✅ **System-stat widgets** — CPU / RAM sparklines + audio spectrum,
  fed by a `psutil` poller in the bridge (0.6.0-beta)
- ✅ **In-app GitHub update checker** with prerelease-aware semver
  filtering (0.5.1-beta)
- ✅ **Wallpaper Engine support** — bundles built alongside Lively zips
  and auto-copied to Steam's WE projects folder when detected
  (0.5.2-beta / 0.5.3-beta)
- ✅ **Widget framework** with 7+ built-in types (clock, calendar,
  weather, sticky note, countdown, picture frame, quote, CPU, RAM,
  audio) and an extensible registry (0.5.0 / 0.5.1-beta)
- ✅ **Builder polish** — live brush cursor, hardness slider, round /
  square brush shape, erase brush, drag-and-drop merge slots, full
  undo / redo (0.4.5)
- ✅ **GIMP-style builder layout** — icon toolbox + tool options +
  canvas + files panel (0.4.5)
- ✅ **Side-by-side image merge** in the builder (0.4.4 / 0.4.5)
- ✅ **GPU-load drop** from ~20 % to ~3 % on the grid layout (0.5.1)

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
