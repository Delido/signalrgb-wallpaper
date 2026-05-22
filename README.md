<div align="center">

![SignalRGB Desktop Wallpaper](docs/images/banner.png)

[![Release](https://img.shields.io/github/v/release/Delido/signalrgb-wallpaper?sort=semver&style=flat-square)](https://github.com/Delido/signalrgb-wallpaper/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Delido/signalrgb-wallpaper/total?style=flat-square)](https://github.com/Delido/signalrgb-wallpaper/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue?style=flat-square)](#requirements)
[![Sponsor](https://img.shields.io/badge/Buy_me_a_coffee-PayPal-00457C?style=flat-square&logo=paypal&logoColor=white)](https://paypal.me/SMendyka)

### **Live RGB glow on your desktop, driven by your SignalRGB effect.**

Multi-monitor · configurable per screen · one-click installer ·
Lively *and* Wallpaper Engine.

</div>

---

Your SignalRGB effect already drives keyboards, fans and strips —
**why not your desktop too?** This project lets the live colours from
SignalRGB shine through transparent regions of your wallpaper. Pick any
image, carve cut-outs into it (or use one of the bundled starters), and
the holes light up in whatever colour your current SignalRGB effect is
producing — in real time, 60 fps, with zero noticeable CPU cost.

Runs on top of [Lively Wallpaper](https://www.rocksdanister.com/lively/)
(free) or [Wallpaper Engine](https://www.wallpaperengine.io/) (paid, on
Steam). The one-click installer sets everything up — no Python, no
manual file copies, no terminal.

> **v0.8.0** is the first stable release after a long beta cycle.
> Full release notes in the [CHANGELOG](CHANGELOG.md).

## What you get

- 🌈 **Live RGB glow** behind a transparent background, 60 fps
- 🖥️ **Up to 4 monitors**, each fully independent or spanned
- 🖌️ **In-browser image editor** — pick any wallpaper, click out
  transparent regions, no Photoshop required
- 🎨 **Starter wallpaper library** — Cyberpunk Skyline, Neon Grid,
  Anime Window, Geometric Panels (more via *Add image…*)
- ⚙️ **Browser-based Configurator** — change background, glow,
  effects, widgets on-the-fly without restarting anything
- ✨ **Ambient effects** behind the wallpaper — snow, rain, sparks,
  aurora, plus a whole-screen audio-reactive glow layer
- 🧩 **11 desktop widgets** — clock, calendar, weather, sticky notes,
  countdowns, photo frame, quote of the day, CPU / RAM / network
  meters, audio spectrum
- 💾 **Preset slots** — save a complete "background + glow + widgets"
  combo per screen, switch with one click
- 🌐 **DE / EN UI**, auto-detected from your Windows locale
- 🎮 **Auto-pause** when a fullscreen app is active — no GPU drain
  during games

## See it in action

| Configurator | Wallpaper builder |
| :---: | :---: |
| ![Configurator](docs/images/screenshot-configurator.png) | ![Builder](docs/images/screenshot-builder.png) |
| *Pick a background from the bundled library or your own image, dial in glow strength, ambient effects and widgets — everything live in your browser.* | *Click any colour to make it transparent. Drag rectangles, polygons or ellipses. Soft brushes for fine control. Apply straight to a screen with one click.* |

| SignalRGB integration | Wallpaper Engine |
| :---: | :---: |
| ![SignalRGB device settings](docs/images/screenshot-signalrgb-aspect.png) | ![WE Screen index](docs/images/screenshot-we-screenindex.png) |
| *The plugin announces 1–4 "Desktop Wallpaper – Screen N" devices in SignalRGB. Aspect Ratio = Auto matches each monitor's real shape (ultrawide-friendly).* | *One Workshop-style bundle assigned to every monitor with a different **Screen index** per assignment. No manual canvas tricks needed.* |

## Quick start

### 1 · Install

> 📸 **Step-by-step walkthrough with screenshots:**
> [docs/installation.md](docs/installation.md#installer-walkthrough)

1. Grab `SignalRGBWallpaperSetup-<version>.exe` from
   [Releases](https://github.com/Delido/signalrgb-wallpaper/releases/latest).
2. Run it. **No admin needed** — installs per-user. The wizard's
   defaults match the most common path (Lively + auto-import + SignalRGB
   plugin + autostart + open the Configurator when done).
   - 🟢 **No Lively installed yet?** Tick *Auto-install Lively if not
     already present* and the installer downloads + silently installs
     the latest Lively from GitHub before importing the wallpapers.
   - 🟢 **Wallpaper Engine on Steam?** Auto-detected; the bundle goes
     straight into WE's *My Wallpapers*.

### 2 · Configure

After install, the Configurator opens automatically in your browser
at `http://127.0.0.1:17320/configurator`. Set the screen count
(top right, *Screens: 1 / 2 / 3 / 4*), pick a starter wallpaper
from the library strip, tweak the glow strength, optionally turn on
an ambient effect — done.

### 3 · Place SignalRGB devices

Open SignalRGB → **Layouts**. Drag each *Desktop Wallpaper – Screen N*
device onto the canvas where you want colours sampled from. For a
single monitor: cover the canvas. For two side-by-side monitors: left
half + right half. The [Help page](#help) and
[multi-screen guide](docs/multi-screen-setup.md) have worked examples.

### 4 · Assign in your wallpaper host

- **Lively users** — the installer dropped the four wallpapers into
  your Lively library. Right-click each *SignalRGB Glow – Screen N*
  tile → *Set as wallpaper* → pick the matching monitor.
- **Wallpaper Engine users** — open WE, *My Wallpapers* now contains
  *SignalRGB Glow*. Assign it to every monitor you want to drive,
  and in each per-wallpaper *Properties* panel pick a different
  *Screen index* (Screen 1 / 2 / 3 / 4).

> 💡 **Stuck or unsure which setup matches your monitors?** Right-
> click the bridge's tray icon → **Help…** for scenario walkthroughs
> (1 / 2 / 3 / 4 monitors × Lively / Wallpaper Engine, ultrawide,
> common pitfalls — all DE / EN).

## Requirements

- **Windows 10 or 11**
- **[SignalRGB](https://www.signalrgb.com/)** installed and able to drive
  your hardware (open it once, pick any effect; if no LEDs light up,
  fix that first)
- **A wallpaper host** — at least one:
  - **[Lively Wallpaper](https://www.rocksdanister.com/lively/)** —
    free, recommended. GitHub-installer build preferred; Microsoft Store
    / MSIX build also works. If you don't have Lively yet, the installer
    can fetch + install it for you.
  - **[Wallpaper Engine](https://www.wallpaperengine.io/)** — paid,
    on Steam. Auto-detected by the installer; one combined bundle gets
    dropped into `wallpaper_engine\projects\myprojects\`.

## Help

The tray icon's **Help…** entry opens a scenario-based walkthrough
covering every Lively / Wallpaper Engine setup for 1–4 monitors,
including ultrawide / non-16:9 panels and spanned configurations
(DE / EN, auto-localised). For docs beyond the in-app help:

- **[Installation guide](docs/installation.md)** — full installer
  walkthrough with screenshots and Windows path notes
- **[Multi-screen setup](docs/multi-screen-setup.md)** — placing
  SignalRGB devices on the canvas, assigning wallpapers per monitor
- **[Building glow wallpapers](docs/building-wallpapers.md)** —
  picking a source image, GIMP workflow, what looks good
- **[Tray reference](docs/tray-settings.md)** — every menu entry
  explained
- **[Troubleshooting](docs/troubleshooting.md)** — when things don't
  work
- **[Architecture](docs/architecture.md)** — wire formats, threading
  model, why the components are split the way they are
- **[Build from source](docs/building-from-source.md)** —
  PyInstaller + Inno Setup, dev loop

## How it works

The SignalRGB plugin registers as virtual lighting devices (one per
monitor) and samples your effect canvas every frame. Each frame goes
out as a UDP datagram to a small **bridge** (`SignalRGBBridge.exe`,
runs in your tray) that fans the colours out to one HTML wallpaper page
per monitor over WebSocket. The wallpaper page renders the colours as a
CSS-grid glow layer behind your background image. All per-screen
settings (background, glow, widgets, effects) live in the **in-browser
Configurator** which pushes changes live to the wallpaper without any
reload. Full architecture: [docs/architecture.md](docs/architecture.md).

## Manual install (no installer)

If you'd rather not run the installer:

| File | Where it goes |
| --- | --- |
| `SignalRGBBridge.exe` | Anywhere stable (e.g. `C:\Tools\SignalRGBWallpaper\`) |
| `SignalRGB_Desktop_Wallpaper.js` + `.qml` | `Documents\WhirlwindFX\Plugins\` |
| `SignalRGB_Glow_Screen{1,2,3,4}.zip` *(Lively)* | Drag each zip onto Lively |
| `SignalRGB_Glow_WE_Single.zip` *(Wallpaper Engine)* | Extract; drop `signalrgb-glow/` into `…\steamapps\common\wallpaper_engine\projects\myprojects\` |

Then run `SignalRGBBridge.exe`. The tray icon appears; right-click
→ *Configurator…* to set everything up.

## Uninstall

Windows Settings → **Apps** → SignalRGB Desktop Wallpaper → Uninstall.
The uninstaller removes the bridge, the auto-imported Lively folders
(`signalrgb-glow-screen-{1..4}\`), the WE bundle (`signalrgb-glow\`),
and the autostart registry entry. Your custom backgrounds, widgets and
presets in `%LOCALAPPDATA%\SignalRGBWallpaper\` stay; delete that folder
by hand to clear them too.

The SignalRGB plugin in `Documents\WhirlwindFX\Plugins\` is **not**
removed automatically — delete by hand if you want SignalRGB to forget
about it.

## What's new

**v0.8.0** is the first stable after the 0.7.x beta cycle and rolls up
the whole "0.7.0 → 0.8.0" feature wave:

- 🆕 **In-browser Help page** — scenario walkthroughs for every monitor
  setup (tray → *Help…*)
- 🆕 **Wallpaper library** with upload + delete from the Configurator
- 🆕 **Per-screen preset slots** — save / apply / clear with one click
- 🆕 **Pattern-fill brush** in the Builder (halftone / dither / hatching)
- 🆕 **Whole-screen audio-reactive glow layer** — Pulse / Spectrum /
  Waveform
- 🆕 **4-monitor support** + ultrawide-friendly aspect ratios
  (Auto / 16:9 / 21:9 / 32:9 / 9:16 / Custom)
- 🆕 **Auto-Lively bootstrapper** in the installer — Lively isn't even a
  prerequisite anymore
- 🆕 **Single Wallpaper Engine bundle** with *Screen index* property
  (one Workshop item covers any monitor count)
- 🆕 **DE / EN** localisation across Configurator, Builder, About, Help
- 🆕 **3D parallax** background-against-cursor effect
- 🆕 **Chunked UDP** transport — 128 × 128 RGB grids
- 🆕 **In-app update checker** with beta-channel opt-in

**Since v0.8.0** the 0.8.x beta cycle has piled workflow polish on
top — turn beta updates on in the tray to get them automatically:

- 🆕 **LibreHardwareMonitor integration** — new Hardware-Sensor
  widget family (CPU/GPU temps, fan RPMs, drive temps, power…)
  driven by a local LHM web server (v0.8.2-beta)
- 🆕 **Gallery rebuild** — hover-preview with RGB-mock glow,
  click-to-preview instead of click-to-apply, 5 s Undo toast,
  right-click context menu (Apply / Edit in Builder / Rename /
  Duplicate / Delete), pin-to-top, drag-and-drop reorder
  (v0.8.3 + v0.8.4-beta)
- 🆕 **Builder ↔ Library bridge** — *Open from library…* picker
  next to *Choose image*, *Save to library* button, *From
  library…* on the merge slots, deep-link via
  `?library=<file>` (v0.8.3 + v0.8.5-beta)
- 🆕 **Builder crop tool** — drag a rectangle and Confirm to
  resize the canvas; in-progress mask edits survive
  (v0.8.5-beta)
- 🆕 **Builder live-glow preview** — toggle in the canvas toolbar
  swaps the transparency checkerboard for an animated RGB
  gradient so cut-out pixels preview the actual SignalRGB glow
  (v0.8.4-beta)
- 🆕 **Tab labels show resolution** — *Screen 2 — 3840×1080*
  whenever a wallpaper page has connected (v0.8.5-beta)
- 🐛 **Perf**: SignalRGB-startup lag fixed by coalescing 5×
  redundant `applyZoneSize` rebuilds into one (v0.8.1)
- 🐛 **Installer**: library.json no longer overwritten on
  upgrade, so your uploads stay visible (v0.8.6-beta)

Full version-by-version breakdown: [CHANGELOG.md](CHANGELOG.md).

## Roadmap

Open ideas grouped by impact-to-effort ratio. Effort estimates are
the maintainer's order-of-magnitude — pull requests on any of these
are very welcome. For the long-form version with per-item
implementation notes + license-compatibility guidance, see
[docs/roadmap.md](docs/roadmap.md).

### 🎯 Tier 1 — Setup polish (biggest UX wins for least effort)

- **Setup health check in the tray** — green/red status dots for
  SignalRGB plugin loaded · bridge port reachable · wallpaper
  assigned · LHM reachable. Each red dot has a one-click fix.
  Should eliminate most "doesn't work" support traffic.
- **Backup + restore config** — export everything
  (`config.json` + Library + Presets + Widgets) as one ZIP,
  re-import via drag-and-drop in the Configurator. Killer for
  fresh-Windows installs / multi-PC users.
- **Reset / undo** — "Reset this screen to defaults" per Screen
  tab, plus Ctrl+Z for the last ~10 settings changes.
- **First-run onboarding tour** — 30-second guided overlay the
  first time the Configurator opens: Screens → Background → Glow
  → Done.

### ✨ Tier 2 — High-visibility user features

- **Wallpaper shuffle / cycle** — Library toggle: cycle every X
  minutes, randomise on logon, or pick a different image by time
  of day.
- **Preset hotkeys** — global `Ctrl+Shift+1..4` to swap between
  the four per-screen preset slots without touching the
  Configurator.
- **Per-app / per-game profiles** — foreground-window watcher
  that auto-switches presets when a specific exe runs (e.g. dim
  glow plus a clock-only widget while Cyberpunk 2077 is
  foreground).
- **Now-playing widget** — current track from Spotify or any
  Windows app that publishes through `SystemMediaTransportControls`.

### 🛠️ Tier 3 — Power-user / polish

- **Builder: AI cut-out tool** — small WebAssembly background-
  removal model for a one-click "make all the bright stuff
  transparent" mode.
- **Winget package + auto-update** — `winget install
  Delido.SignalRGBWallpaper` and a button in the update checker
  to actually download + apply the update instead of just linking
  to the release page.
- **Mobile Configurator view** — make `/configurator` responsive
  so you can change wallpaper settings from a phone on the same
  network.
- **Community wallpaper gallery** — central `wallpapers.json` in
  a community repo; the Configurator pulls it and shows
  community-submitted backgrounds alongside the local Library
  strip. PR-based submissions.
- **More ambient effects from MIT-licensed sources** — port a
  few canvas / particle pieces from MIT-licensed CodePen authors
  (e.g. [ykob](https://github.com/ykob)'s catalogue) as new
  *Effects* presets — fireflies, geometric flow fields, stars,
  etc. Per-pen license check + attribution in `docs/credits.md`
  required.

### 🔌 Tier 4 — Ecosystem / integration

- **Home Assistant / MQTT bridge** — publish wallpaper state +
  sensor values via MQTT so users can write HA automations
  ("dim wallpaper when 'movie night' scene is active").
- **REST API** — already partially possible (`/library`, `/config`,
  `/hwmon/sensors`); formalise the full WS-equivalent surface for
  Stream Deck / scripts / external tools to drive the wallpaper.
- **Plugin API for third-party widgets** — `%LOCALAPPDATA%\
  SignalRGBWallpaper\plugins\<name>\widget.js` with a defined
  contract. Long road to a community widget library.
- **Generic HTTP widget** — polls any URL on a schedule and
  renders a configurable template. Covers Discord unread /
  stocks / RSS / crypto / arbitrary REST APIs with one widget
  type instead of one per service.

Got a wish that isn't here?
[Open an issue](https://github.com/Delido/signalrgb-wallpaper/issues/new)
and tag it `enhancement`.

## Contributing

Issues and PRs welcome. Bug reports should include:

- Windows version (Win+R → `winver`)
- SignalRGB version (Settings → About in SignalRGB)
- Lively / Wallpaper Engine version — say which one + Microsoft Store
  vs GitHub build for Lively
- The bridge log if relevant: run `SignalRGBBridge.exe` from a CMD
  window (or `python wallpaper_bridge\bridge.py` directly)

## Support / donate

This project is built and maintained in spare time. If it saves you
the hassle of writing your own SignalRGB → wallpaper plumbing, or
if seeing a glow that matches your effect just makes you smile every
morning, a small tip keeps the motivation up.

<div align="center">

[![Buy me a coffee — PayPal](https://img.shields.io/badge/Buy_me_a_coffee-PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/SMendyka)

</div>

Issues, feature requests and pull requests are also very welcome —
even just an [issue](https://github.com/Delido/signalrgb-wallpaper/issues)
saying "this is broken on my machine" helps a lot.

## License

[MIT](LICENSE) © 2026 Sebastian Mendyka ([@Delido](https://github.com/Delido))
