# Tray icon reference

What every entry in the bridge's tray menu does. The bridge itself runs
silently in the system tray (small monitor icon with five RGB pads
underneath); all day-to-day work happens through the **Configurator**
opened from this menu.

Right-click the tray icon to open the menu. Left-click runs the default
action (Configurator).

## Top level

| Entry | What it does |
| --- | --- |
| **Configurator…** *(default click)* | Opens `http://127.0.0.1:17320/configurator` in your default browser. Main UI — per-screen tabs for background / glow / effects / widgets, drag-and-resize layout preview, live settings push back to the wallpaper. See [the Configurator section](#the-configurator) below. |
| **Build Wallpaper…** | Opens `http://127.0.0.1:17320/builder` — the in-browser editor for carving transparent regions out of any image. See [building-wallpapers.md](building-wallpapers.md). |
| **🔓 Lock / 🔒 Unlock widgets (all screens)** | One-click toggle that flips `widgetsLocked` on every active screen. Mirrors the lock-bar at the top of the Configurator's Widgets section. When unlocked, widgets can be dragged + resized on the live wallpaper *and* in the Configurator preview. |
| **Advanced** *(submenu)* | Power-user stuff pushed out of the default menu — see below. |
| **Updates** *(submenu)* | In-app update checker + the "Allow beta versions" toggle — see below. |
| **About…** | Standalone window with version, GitHub link, maintainer + avatar, open-source-credits link, and a "Buy me a coffee" PayPal button. |
| **Quit** | Hard-stops the bridge process. Wallpaper pages disconnect; the SignalRGB plugin keeps trying to send UDP but with nothing listening. Re-launch the exe to resume. |

When a newer release is published, an extra `⬆ Update available: vX.Y.Z — open release page` entry appears at the top of the menu.

## Advanced submenu

| Entry | What it does |
| --- | --- |
| **Legacy Settings dialog…** | The classic Tk window that pre-dated the Configurator. Still useful for one thing the Configurator doesn't cover yet: the global `Number of screens` knob. Pick 1 / 2 / 3 / 4, click Save — SignalRGB picks up the new count within ~2 s. |
| **Quick add widget** *(submenu)* | Per-screen submenu that mirrors the Configurator's *Add a widget* picker grid. Same eleven types, plus an *Edit widgets* toggle and a "Currently placed: N" status line. |
| **Quick effects** *(submenu)* | Per-screen submenu with radio lists for ambient preset (off / snow / rain / sparks / aurora), tint-with-glow toggle, and pixelfx mode (off / trail / glow / ripple / all). Same state as the Configurator's Effects section. |
| **Reload config** | Re-reads `%LOCALAPPDATA%\SignalRGBWallpaper\config.json` from disk. Useful if you edited it by hand or are debugging settings sync. Pushes the reloaded state to all connected wallpaper pages. |

## Updates submenu

| Entry | What it does |
| --- | --- |
| **Check for updates now** | Manual trigger. Hits GitHub Releases API; refreshes the menu with a "Latest: vX.Y.Z — open release page" entry if newer. |
| **Enable update checks** *(checkbox)* | Master switch (default on). When off, the daily background poll is suspended. |
| **Allow beta versions** *(checkbox)* | Default off. When on, prerelease tags participate in the comparison. Semver-aware — `0.7.0-beta < 0.7.0`, so stable users won't get downgraded to a beta. |
| Status line | One of: *Up to date — last checked Xm ago* · *Latest: vX.Y.Z — open release page* · *Last check failed: …* · *Not yet checked*. |
| *Installed: vX.Y.Z* | Read-only indicator of the running bridge version. |

## The Configurator

The Configurator is the in-browser UI served at
`http://127.0.0.1:17320/configurator`. Per-screen tabs at the top
(*Screen 1 / 2 / 3 / 4* — only the ones up to your screen count are
useful). Each tab has four collapsible sections.

### Background

| Control | What it does |
| --- | --- |
| Image path | Direct path to your background image (PNG / JPG / WebP / SVG). Editable text field — paste a URL or absolute path. |
| Choose image… | File picker; the bridge converts to PNG and stores it under `%LOCALAPPDATA%\SignalRGBWallpaper\screens\screen-N-<timestamp>.png`. |
| Open Builder… | Opens the in-browser builder in a new tab — for cutting transparent regions out of an image. |
| Fit | `cover` (crop to fill — default), `contain` (letterbox), `fill` (stretch). |
| Dim | Black overlay opacity, 0–100 %. Useful when a bright background drowns out the glow. |

### Glow

| Control | What it does |
| --- | --- |
| Show glow layer | Master on/off for the SignalRGB-driven glow layer. |
| Layout | Pixel grid (default), vertical stripes, horizontal stripes, centered pills, hidden. |
| Strength | Multiplier for the glow's overall brightness/blur, 0–200 %. |
| Grid blur | Blur radius in CSS pixels for the pixel-grid layout (default 30 px). Larger = softer / more diffuse glow. |
| Stripes blur | Same for the stripes layout (default 60 px). |

### Effects

| Control | What it does |
| --- | --- |
| Ambient preset | Five tiles: *Off / Snow / Rain / Sparks / Aurora*. Each except *Off* shows a live mini-canvas preview running the actual preset. Click to apply. |
| Tint particles with the live glow colour | When on, the particle colours track the live SignalRGB-feed average. Off by default. |
| Density | 1–100, controls particle count / saturation. Default 60. |
| Pixelfx (cursor) | Mouse-trail / hover-glow / click-ripple / all combined. Trail and glow work under Lively click-through (cursor pos is pushed by the host); ripple needs real clicks (toggle *Wallpaper interaction* in Lively). |
| 3D parallax | Background image slides against the cursor for a fake-depth effect, 0–120 px max-displacement. 30 ≈ subtle, 80 ≈ dramatic. Uses Lively's `livelyCurrentCursorPos` + a DOM mousemove fallback. |

### Widgets

| Control | What it does |
| --- | --- |
| Lock-bar | Big toggle at the top with a colored status dot. Locked = read-only; unlocked = drag + resize active on the wallpaper *and* in the layout preview. |
| Layout preview | Scaled rectangle of the screen (auto-fits to the reported viewport, falls back to 1920×1080 if no wallpaper is connected yet). Each widget is a draggable + resizable box. Drop = persisted via WebSocket. |
| Snap to grid | Toggle + step picker (10 / 20 / 40 / 80 px). When on, drag + resize snap to the grid and the preview overlays the snap grid in accent blue. State persists in browser localStorage. |
| Widget list | Per-widget rows showing icon + label + a short description. *Configure* opens a form modal (per-type options schema, no more prompts). *Remove* deletes the widget. |
| Add a widget | Picker grid with all eleven registered widget types (clock, calendar, weather, sticky-note, countdown, picture, quote, CPU meter, RAM meter, audio spectrum, network — well, network is hidden but the registry slot is there). Click to add at the type's default position; the widget appears on the live wallpaper immediately. |

## Where settings live

- `%LOCALAPPDATA%\SignalRGBWallpaper\config.json` — main config: per-screen
  settings array, screen count, language, update-check flags. Updated on
  every settings change.
- `%LOCALAPPDATA%\SignalRGBWallpaper\screens\screen-N-<timestamp>.png` —
  any background image uploaded through the Configurator or the
  Builder. Old timestamps get pruned on the next upload.
- `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\SignalRGBWallpaperBridge` —
  autostart entry (set by the installer when the matching task is
  checked). Remove it with the uninstaller or delete the value by hand.

## Localisation

The whole tray menu + About dialog respect the **language** config key
(`auto` / `en` / `de`). `auto` (default) picks from your Windows locale.
Override by editing `config.json`:

```json
"language": "de"
```

The Configurator picks up the active language on its first WebSocket
push from the bridge and re-localises live without a reload.

Builder window strings are English-only for now — tracked on the README
roadmap.
