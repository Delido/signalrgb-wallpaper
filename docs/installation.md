# Installation

The long version of the [README quick start](../README.md#quick-start),
with exact paths and the Windows things that trip people up.

## Prerequisites

Confirm these are working before you start:

1. **SignalRGB** — [signalrgb.com](https://www.signalrgb.com/). Open it
   once and pick any effect; if no LEDs light up, fix that first. This
   project rides on top of SignalRGB's effect canvas, so SignalRGB has
   to be functional in the first place.
2. **A wallpaper host** — pick at least one (the installer asks):
   - **Lively Wallpaper** (free, recommended) —
     [rocksdanister.com/lively](https://www.rocksdanister.com/lively/).
     The GitHub installer build is preferred; the Microsoft Store / MSIX
     build also works.
   - **Wallpaper Engine** (paid, on Steam) — auto-detected by the
     installer; bundles get copied straight into Steam's
     `wallpaper_engine\projects\myprojects` folder.
3. **Windows 10 or 11**. No other dependency — the bridge ships as a
   single self-contained `.exe` (Python + Tk + Pillow + psutil + pystray
   all bundled by PyInstaller).

## Easy path: installer

Grab the latest `SignalRGBWallpaperSetup-<version>.exe` from the
[Releases page](https://github.com/Delido/signalrgb-wallpaper/releases/latest)
and run it. No admin needed — installs per-user into
`%LOCALAPPDATA%\Programs\SignalRGBWallpaper\`.

### Installer wizard

The **Tasks page** asks you to pick one or both wallpaper hosts plus a
few additional setup items:

**Wallpaper host:**

- ☑ **Lively Wallpaper** (default on). Required for the Lively path.
- ☑ **Auto-import into Lively** (default on, sub-task of Lively). When
  checked + a Lively install is detected (GitHub or MSIX build), the
  three glow bundles get extracted directly into Lively's
  `Library\wallpapers\signalrgb-glow-screen-{1,2,3}\` with deterministic
  folder names. Every subsequent installer run overwrites in place —
  no more *"delete and re-import after every update"* dance.
- ☐ **Wallpaper Engine** (Steam — auto-skipped if not detected). When
  checked + a Steam install is detected (HKCU registry + `libraryfolders.vdf`
  parsing for off-drive libraries), the three glow bundles get copied
  straight into `…\steamapps\common\wallpaper_engine\projects\myprojects\`.

**Additional setup:**

- ☑ **Install the SignalRGB Desktop Wallpaper plugin** (default on) —
  drops `SignalRGB_Desktop_Wallpaper.js` + `.qml` into your
  `Documents\WhirlwindFX\Plugins\` folder so SignalRGB can drive the
  bridge.
- ☑ **Start bridge automatically on logon** (default on) — adds an
  HKCU `Run` registry entry. Standard per-user autostart, no service.

### After install

The installer opens whichever folder(s) the auto-import skipped (for a
manual fallback) and starts the bridge if you kept *"Start now"*. The
bridge lives in the system tray as a small monitor icon with five RGB
pads underneath. Click it for the **Configurator…** entry — that's the
new in-browser settings UI for everything (per-screen backgrounds, glow
layout, widgets, effects, parallax, …). See
[`tray-settings.md`](tray-settings.md) for everything the tray menu
actually offers, and the in-browser [Configurator](#3-the-configurator)
section below for the main settings flow.

## Manual path (no installer)

If you'd rather not run the installer:

| File | Where it goes | Size |
| --- | --- | --- |
| `SignalRGBBridge.exe` | Anywhere stable (e.g. `C:\Tools\SignalRGBWallpaper\`) | ~20 MB |
| `SignalRGB_Desktop_Wallpaper.js` | `Documents\WhirlwindFX\Plugins\` | ~20 KB |
| `SignalRGB_Desktop_Wallpaper.qml` | same folder | ~3 KB |
| `SignalRGB_Glow_Screen{1,2,3}.zip` | Drag each onto Lively | ~100 KB each |
| `SignalRGB_Glow_WallpaperEngine.zip` | Extract; drop each `SignalRGB_Glow_ScreenN/` folder into Steam's `…\steamapps\common\wallpaper_engine\projects\myprojects\` | ~300 KB total |

Then double-click `SignalRGBBridge.exe`.

> **OneDrive note:** if your Documents folder is OneDrive-synced, the
> actual path is `%USERPROFILE%\OneDrive\Dokumente\WhirlwindFX\Plugins\`
> (German Windows) or `OneDrive\Documents\…`. SignalRGB watches whichever
> path you've redirected to.

## Steps in detail

### 1. Plugin is in the WhirlwindFX folder

SignalRGB hot-reloads on file change — the **Desktop Wallpaper - Screen N**
devices should appear in your device list within a few seconds. If they
don't:

- Restart SignalRGB (right-click its tray → Quit, then relaunch).
- Confirm the files landed in the right folder (with or without OneDrive).
- See [Troubleshooting → "Plugin not appearing"](troubleshooting.md#plugin-not-appearing).

### 2. Bridge is running in the system tray

If you don't see the icon: Windows might be hiding it. Right-click the
taskbar → Taskbar settings → "Select which icons appear on the taskbar" →
enable **SignalRGBBridge**. If the process isn't running at all, see
[Troubleshooting → "Bridge won't start"](troubleshooting.md#bridge-wont-start).

### 3. The Configurator

Right-click the tray icon → **Configurator…** (default action).
A browser tab opens at `http://127.0.0.1:17320/configurator`. Per-screen
tabs at the top.

For each active screen, the page has four collapsible sections:

- **Background** — image path field + file-picker (uploads via PNG-via-canvas
  to the bridge's `POST /screen/N/background` endpoint, same path the
  builder uses), Fit dropdown, Dim slider.
- **Glow** — layout (pixel grid / vertical / horizontal stripes / centered
  pills / hidden), strength %, grid blur, stripes blur, show-bars toggle.
- **Effects** — ambient preset tiles (snow / rain / sparks / aurora with
  live mini-canvas previews), tint toggle, density, pixelfx mode (mouse
  trail / hover glow / click ripple / all), 3D parallax slider.
- **Widgets** — prominent lock-bar at the top, drag-and-resize layout
  preview underneath (snap-to-grid optional), widget list with per-type
  *Configure* + *Remove* buttons, add-widget picker grid.

Settings push to the live wallpaper over WebSocket immediately — no
Lively reload needed.

For the screen count itself: tray → **Advanced** → **Legacy Settings
dialog…** (the classic Tk window) → set *Number of screens* to **1**,
**2**, **3**, or **4** → **Save**. The SignalRGB plugin polls the
bridge every tick and adjusts its device list.

### 4. Place the SignalRGB devices on the canvas

Open SignalRGB → Layouts. For each *Desktop Wallpaper - Screen N* device,
drag it onto the canvas at the position you want it to sample from.
Typical layouts:

- **Single monitor:** centre the device, scale to cover the canvas.
- **Two monitors (left + right):** Screen 1 on the left half, Screen 2 on
  the right half.
- **Three monitors:** divide the canvas into thirds.

Optionally bump **Glow Grid Base Size** in the plugin's settings up to
`128` — the bridge transparently chunks any frame > 4 KB across
multiple datagrams. 32 / 36 / 64 / 96 / 128 are all valid; bigger =
finer glow gradient + more browser work.

For **ultrawide monitors** (21:9 / 32:9, or anything non-square), set
the plugin's **Aspect Ratio** to *Auto* (the default) — the bridge
publishes each screen's actual viewport over `GET /config`, and the
plugin derives the longer side of the glow grid from it. So a
3840 × 1080 monitor at base size 32 sends a 114 × 32 grid instead of
a square 32 × 32 that would under-sample its width. The other
options force a fixed shape (*1:1* / *16:9* / *21:9* / *32:9* /
*9:16*) or let you type a *Custom Cols × Rows* directly. See
[`multi-screen-setup.md`](multi-screen-setup.md) for a worked example.

### 5. Assign the wallpapers

**Lively users:** if you let the installer auto-import, your library
already has *SignalRGB Glow - Screen 1 / 2 / 3 / 4* tiles. Right-click
each → *Set as wallpaper* → pick the matching monitor.

If you didn't auto-import, drag each `SignalRGB_Glow_ScreenN.zip` onto
Lively to import, then assign.

**Wallpaper Engine users:** if you let the installer auto-copy, WE
already lists the four bundles under *My Wallpapers*. Click each one,
pick the matching monitor. (Or use the **single-bundle** Workshop item
if you've subscribed to that one — assign the same wallpaper to every
monitor and set a different *Screen index* per assignment in its
properties panel.)

If you didn't auto-copy, extract `SignalRGB_Glow_WallpaperEngine.zip` and
drop each folder into `…\steamapps\common\wallpaper_engine\projects\myprojects\`.

## Next steps

- [Tray settings reference](tray-settings.md) — what every menu entry does
- [Multi-screen setup](multi-screen-setup.md) — canvas placement walkthrough
- [Building glow wallpapers](building-wallpapers.md) — using the
  in-browser builder to cut transparent regions
- [Troubleshooting](troubleshooting.md) — when something doesn't work

## Uninstalling

**Via the installer:** Windows Settings → Apps → SignalRGB Desktop
Wallpaper → Uninstall. (Or `unins000.exe` in the install folder.)

The uninstaller:

- Kills the running bridge first (`taskkill /f /im SignalRGBBridge.exe`).
- Removes the bridge exe + bundled files from `{InstallDir}`.
- Removes the auto-imported Lively folders (`signalrgb-glow-screen-{1,2,3}\`)
  if Lively was detected — leaves other Lively wallpapers alone.
- Removes the auto-copied Wallpaper Engine bundle folders if Steam was
  detected — leaves other WE wallpapers alone.
- Drops the autostart `Run` registry entry.

The plugin in `WhirlwindFX\Plugins\` is *not* removed automatically —
delete by hand if you want SignalRGB to forget about it.

**Manual install:** reverse the manual steps. The bridge writes its
config to `%LOCALAPPDATA%\SignalRGBWallpaper\config.json` — delete that
folder to throw away your saved settings.
