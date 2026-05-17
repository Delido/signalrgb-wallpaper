# Troubleshooting

Common failure modes and how to diagnose them.

## How to get useful diagnostic output

The default `SignalRGBBridge.exe` build is `--noconsole` — no stdout
visible. When something's misbehaving, run the bridge with stdout
visible instead:

**Option A** — run the Python source directly:

```powershell
python wallpaper_bridge\bridge.py
```

You'll see UDP packet counts, WS client connects, settings pushes, etc.
Plus any Python exceptions.

**Option B** — run the `.exe` from cmd so its stdout/stderr inherit the
terminal (only works partially since `--noconsole` strips the handle —
prefer Option A for debugging).

For SignalRGB-side plugin issues, the plugin writes its `service.log` /
`device.log` calls to SignalRGB's plugin log file:
`%LOCALAPPDATA%\WhirlwindFX\SignalRgb\Logs\SignalRGB_*.log`

## Plugin not appearing

After copying `SignalRGB_Desktop_Wallpaper.js` and `.qml` to your
Plugins folder, SignalRGB should hot-load within seconds.

If the device doesn't show up:

1. **Confirm the Plugins folder path.** With OneDrive Documents
   redirection, it's
   `%USERPROFILE%\OneDrive\Documents\WhirlwindFX\Plugins\`
   (or `OneDrive\Dokumente\…` on German Windows). Without redirection,
   it's `%USERPROFILE%\Documents\WhirlwindFX\Plugins\`. SignalRGB only
   watches the redirected path.
2. **Restart SignalRGB.** Right-click SignalRGB's tray icon → Quit, then
   relaunch. Hot-reload sometimes doesn't trigger `DiscoveryService.Initialize`
   reliably; a full restart always does.
3. **Check the SignalRGB log** (`SignalRGB_*.log`, see above) — search
   for `Custom Plugin File Loaded` to confirm SignalRGB saw your file.
   If you see `Error: Could not open module…` that's a plugin runtime
   issue — please file an issue with the exact error.

## Bridge won't start

Symptom: you double-click `SignalRGBBridge.exe`, no tray icon, nothing.

1. **Open Task Manager → Details** and search for `SignalRGBBridge.exe`.
   If it's not there, the exe failed to start (likely an antivirus quarantine
   on the PyInstaller bundle — temporarily disable AV / add an exclusion
   and retry, or build from source).
2. **Port 17320 already in use** — another bridge is already running
   (or a different program is using 17320). Check:

   ```powershell
   Get-NetUDPEndpoint -LocalPort 17320 -ErrorAction SilentlyContinue
   Get-NetTCPConnection -LocalPort 17320 -State Listen -ErrorAction SilentlyContinue
   ```

   If something else is bound, kill it (or change `bridgePort` in the
   plugin's settings — but you'd then also need to rebuild the zips
   with a matching port hardcoded… not great, prefer killing whatever's
   conflicting).

## Wallpaper stays black / "connecting…" status

The Lively wallpaper opens but never receives frames.

1. **Enable the debug overlay** for that screen: tray → Settings… →
   the screen's tab → "Show debug overlay" → Save. The wallpaper now
   shows a tiny status line top-left.
2. **Read the status:**
   - `connecting ws://127.0.0.1:17320/?screen=N…` — bridge not running
     or wrong port. Confirm `SignalRGBBridge.exe` is in your tray.
   - `disconnected — retrying…` — bridge crashed or was killed. Start it
     again.
   - `screen N live WxH @ X fps` — wallpaper is connected and getting
     frames. If you still see no glow, the issue is on the SignalRGB
     side: confirm the device is on the canvas and a colourful effect
     is active.
3. **Confirm the plugin is sending UDP.** In SignalRGB's log
   (`SignalRGB_*.log`) search for `[DesktopWallpaper] screen N frame #`.
   If you see these, the plugin is firing; if not, the device isn't
   being rendered by SignalRGB (not on canvas / not active).

## Wrong colours on wrong monitor

You set up two monitors, but the colours from Screen 1 are showing on
monitor 2 (or similar).

The mapping happens in **Lively**, not in our code. Each wallpaper zip
hardcodes a screen index in its HTML's `<meta>` tag:

| Zip | Subscribes to |
| --- | --- |
| `SignalRGB_Glow_Screen1.zip` | UDP frames tagged `screen=0` |
| `SignalRGB_Glow_Screen2.zip` | UDP frames tagged `screen=1` |
| `SignalRGB_Glow_Screen3.zip` | UDP frames tagged `screen=2` |

And the SignalRGB devices match:
- "Desktop Wallpaper - Screen 1" device sends UDP with `screen=0` byte
- "Desktop Wallpaper - Screen 2" device sends with `screen=1`
- "Desktop Wallpaper - Screen 3" device sends with `screen=2`

So the chain is: SignalRGB device "Screen 1" → UDP screen=0 → bridge
routes to WS clients with `?screen=0` → wallpaper from `Screen1.zip`.

To fix wrong-monitor mapping, just swap which monitor each Lively
wallpaper is activated on. Or rearrange the SignalRGB canvas
placements.

## Debug overlay keeps showing despite being disabled

Should be fixed in v0.2.0. If you see it pop up anyway after upgrading,
do a hard refresh:
- In Lively, deactivate the wallpaper, then reactivate. That re-loads
  the HTML page with the current code.
- If still leaking, please file an issue.

## Tray Quit doesn't kill the bridge

Should be fixed in v0.2.0. If clicking Quit leaves `SignalRGBBridge.exe`
in Task Manager, kill it manually from Task Manager → End task. Then
file an issue with your Windows build (`winver`).

## Background image won't load

Symptom: the wallpaper renders the glow correctly but no background
image appears (or it's broken).

1. **Path issue** — confirm the file at the path you picked still exists.
   Browse to it from File Explorer.
2. **Unsupported extension** — the bridge's image proxy whitelists
   `.png .jpg .jpeg .gif .webp .svg .bmp .ico`. Other formats are
   rejected.
3. **Bridge offline** — without the bridge, the wallpaper can't fetch
   absolute-path images via the `/image` proxy.
4. Open the wallpaper's dev tools by running Lively in debug mode and
   inspect network requests. Or check the bridge's stdout (run from
   Python source) for `[http] served …` and any `404 not found` lines.

## SignalRGB shows too many / too few devices

Set "Number of screens" in the tray Settings dialog. Plugin polls the
bridge every ~2 seconds and adjusts. If it doesn't:

- Make sure the bridge is actually running (tray icon visible).
- Open `http://127.0.0.1:17320/config` in a browser — should return
  `{"screenCount": N}`. If the page errors, the bridge isn't running or
  the endpoint is broken.
- Restart SignalRGB if the plugin seems stuck.

## "Address already in use" on bridge startup

Port 17320 is occupied by an old bridge process that didn't exit
cleanly. Either:

```powershell
Get-Process -Name SignalRGBBridge -ErrorAction SilentlyContinue | Stop-Process -Force
```

Or Task Manager → End all `SignalRGBBridge.exe` entries. Then start fresh.

## Still stuck?

File an issue at [github.com/Delido/signalrgb-wallpaper/issues](https://github.com/Delido/signalrgb-wallpaper/issues)
with:

- Windows version (`winver`)
- SignalRGB version
- Lively version (and whether it's Store or GitHub build)
- What you did, what you expected, what happened
- Bridge stdout output (run `python wallpaper_bridge\bridge.py`)
- SignalRGB log snippet if relevant (lines mentioning `DesktopWallpaper`)
