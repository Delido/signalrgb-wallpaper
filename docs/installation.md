# Installation

The long version of the [README quick start](../README.md#quick-start), with
exact paths and the small Windows things that trip people up.

## Prerequisites

Before you start, confirm you have these three programs installed and
working:

1. **SignalRGB** — [signalrgb.com](https://www.signalrgb.com/). Open it
   once and pick any effect; if no LEDs light up, fix that first (this
   project rides on top of SignalRGB's effect canvas, so SignalRGB must
   be functional).
2. **Lively Wallpaper** — [rocksdanister.com/lively](https://www.rocksdanister.com/lively/).
   Either the GitHub installer build or the Microsoft Store build works
   for our Web-type wallpapers. The GitHub build is preferred.
3. **No third installer needed** — the bridge ships as a single
   self-contained `.exe`.

## Downloads

Grab the latest assets from the [Releases page](https://github.com/Delido/signalrgb-wallpaper/releases/latest):

| File | Where it goes | Size |
| --- | --- | --- |
| `SignalRGBBridge.exe` | Anywhere you like — pick a stable folder you won't move (e.g. `C:\Tools\SignalRGBWallpaper\`) | ~19 MB |
| `SignalRGB_Desktop_Wallpaper.js` | `%USERPROFILE%\Documents\WhirlwindFX\Plugins\` | ~17 KB |
| `SignalRGB_Desktop_Wallpaper.qml` | same folder as `.js` | ~3 KB |
| `SignalRGB_Glow_Screen1.zip` | Drag into Lively | ~12 KB |
| `SignalRGB_Glow_Screen2.zip` | Drag into Lively (only if you have 2+ monitors) | ~12 KB |
| `SignalRGB_Glow_Screen3.zip` | Drag into Lively (only if you have 3 monitors) | ~12 KB |

> **OneDrive note:** if your Documents folder is OneDrive-synced, the
> actual path is `%USERPROFILE%\OneDrive\Dokumente\WhirlwindFX\Plugins\`
> (German Windows) or `OneDrive\Documents\…`. SignalRGB watches whichever
> path you've redirected to.

## Steps

### 1. Install the SignalRGB plugin

Copy `SignalRGB_Desktop_Wallpaper.js` and `.qml` into the Plugins folder
listed above. SignalRGB hot-reloads on file change — the device should
appear in your device list within a few seconds. If it doesn't:

- Restart SignalRGB (right-click tray → Quit, then relaunch).
- Confirm the files landed in the right folder (with or without OneDrive).
- Check [Troubleshooting → "Plugin not appearing"](troubleshooting.md#plugin-not-appearing).

### 2. Start the bridge

Double-click `SignalRGBBridge.exe`. There is no window — that's
intentional. Look in the system tray (right side of the taskbar; you may
have to click the upward chevron to "show hidden icons"). The icon is a
small monitor with five RGB pads under the screen.

If the icon doesn't appear:

- Open Task Manager → Details. There should be a `SignalRGBBridge.exe`
  entry. If it's missing, the exe failed to start — see
  [Troubleshooting → "Bridge won't start"](troubleshooting.md#bridge-wont-start).
- If the process is there but the icon isn't, Windows might be hiding
  it. Right-click the taskbar → Taskbar settings → "Select which icons
  appear on the taskbar" → enable SignalRGBBridge.

### 3. Configure how many screens you want

Right-click the tray icon → **Settings…** → at the top, set "Number of
screens" to **1**, **2**, or **3**. Click **Save**.

Within ~2 seconds the SignalRGB plugin polls the bridge, learns the new
count, and adjusts its device list: more devices get added, excess
devices get removed. Watch the SignalRGB Devices page — "Desktop
Wallpaper - Screen 1/2/3" will appear/disappear accordingly.

### 4. Place the devices on SignalRGB's canvas

Open SignalRGB → Layouts (or whatever your version calls the canvas
view). For each "Desktop Wallpaper - Screen N" device, drag it onto the
canvas at the position you want it to sample colours from. Typical
layouts:

- **Single monitor:** centre the device, scale to cover the canvas.
- **Two monitors (left+right):** put Screen 1 device on the left half,
  Screen 2 device on the right half.
- **Three monitors:** divide the canvas into thirds.

See [docs/multi-screen-setup.md](multi-screen-setup.md) for a worked
example with screenshots.

### 5. Import the wallpapers in Lively

Drag the appropriate `.zip` files onto the Lively window:

- `SignalRGB_Glow_Screen1.zip` for monitor 1
- `SignalRGB_Glow_Screen2.zip` for monitor 2 (if you have one)
- `SignalRGB_Glow_Screen3.zip` for monitor 3

In Lively's library, each tile shows up as "SignalRGB Glow - Screen N".
Activate the matching wallpaper on each monitor:

- Right-click the Screen 1 tile → Set as wallpaper → pick the right
  monitor in Lively's monitor selector.
- Repeat for Screen 2 and Screen 3.

### 6. Pick your background image(s)

Back in the tray icon → **Settings…**. There's one tab per screen.
Each tab has:

- **Background image** — Browse to any PNG/JPG/WebP/SVG on your disk.
  For the "glow shines through transparent regions" effect, use a PNG
  with alpha (transparent windows / signs / cut-outs in the design).
- Layout, glow strength, blur, etc. — see
  [docs/tray-settings.md](tray-settings.md) for every option.

Click **Save**. Settings push to the live wallpapers over WebSocket
immediately; no Lively reload needed.

## Next steps

- [Tray settings reference](tray-settings.md) — what every option does
- [Multi-screen setup](multi-screen-setup.md) — canvas placement walkthrough
- [Troubleshooting](troubleshooting.md) — when something doesn't work

## Uninstalling

1. Right-click tray icon → **Quit**. The bridge process exits.
2. Delete `SignalRGBBridge.exe` (wherever you put it).
3. Delete `SignalRGB_Desktop_Wallpaper.js` and `.qml` from your
   WhirlwindFX Plugins folder.
4. In Lively, right-click each "SignalRGB Glow - Screen N" tile →
   Delete.
5. (Optional) Delete `%LOCALAPPDATA%\SignalRGBWallpaper\` — that's the
   `config.json` with your saved settings.

No registry keys are written. No services are installed. No autostart
yet (planned for v0.3 with an installer).
