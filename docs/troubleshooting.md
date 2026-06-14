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

1. **Enable the debug overlay** for that screen: tray icon →
   **Configurator…** → pick the screen tab → *Background* → tick
   *Show debug overlay (top-left status line on the wallpaper)*. The
   wallpaper now shows a tiny status line top-left.
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

Set *Number of screens* in the Configurator (top-right of the tab
bar — *Screens: 1 / 2 / 3 / 4*). Plugin polls the bridge every ~2
seconds and adjusts. If it doesn't:

- Make sure the bridge is actually running (tray icon visible).
- Open `http://127.0.0.1:17320/config` in a browser — should return
  `{"screenCount": N}`. If the page errors, the bridge isn't running or
  the endpoint is broken.
- Restart SignalRGB if the plugin seems stuck.

## Lively "Pause wallpapers" doesn't stop the glow

The wallpaper page implements Lively's
`window.livelyWallpaperPlaybackChanged(state)` hook per the
[wiki spec](https://github.com/rocksdanister/lively/wiki/Web-Guide-V-:-System-Data)
and shows a red "⏸ PAUSED" badge in the top-right corner when the hook
fires. It also subscribes to `document.visibilitychange` as a defensive
fallback for hosts that suspend the surface without firing the Lively
event. We deliberately do **not** pass `--pause-event true` in
`LivelyInfo.Arguments` — newer Lively builds reject that as an unknown
option (Wallpaper plugin exception on import). The pause hook still
fires on builds that push it without the opt-in.

**But** whether either hook actually fires depends on the Lively build
and the user's environment — some setups don't deliver the suspend
IPC to the WebView2 player at all, in which case the visibilitychange
fallback is the only signal the page gets.

Quick check: when you click "Pause wallpapers" in Lively's tray, do
**other** Web-type wallpapers in your library actually pause (freeze)?

- **No** → Lively itself isn't pausing in your environment. This is
  a Lively-side issue; we can't work around it from a wallpaper page.
  File an issue at the [Lively repo](https://github.com/rocksdanister/lively/issues)
  with your Lively version and Windows build.
- **Yes for others but not ours** → file an issue against this project
  with your Lively version (`Settings → About` in Lively).

## Updated wallpaper but Lively still shows the old version

Symptom: you rebuilt + reimported a wallpaper zip (or pulled a new
release), but the wallpaper in Lively keeps rendering the old
behaviour — old layout, no parallax, missing widgets.

Lively extracts each imported wallpaper zip **once** into a
random-hash folder under
`%USERPROFILE%\AppData\Local\Lively Wallpaper\Library\wallpapers\<hash>\`
(MSIX build path differs; both end in `Library\wallpapers\<hash>\`).
Re-zipping the source folder does **not** propagate — Lively never
re-reads the original zip.

To pick up new HTML / JS / `LivelyInfo.json` changes:

1. In Lively's **Library**, right-click the wallpaper → **Delete**.
2. Drag the new zip onto Lively (or re-run the installer with
   *Auto-import into Lively* enabled — v0.7.0+ uses deterministic
   folder names `signalrgb-glow-screen-{1,2,3}\`, which the installer
   overwrites in place, so no manual delete needed for future
   updates).
3. Right-click each new tile → **Set as wallpaper** for the matching
   monitor.

The deterministic-folder auto-import is the v0.7.0 fix specifically
for this footgun. Pre-v0.7.0 users coming from a manual drag-import
still hit it once on the upgrade — after the installer takes over,
subsequent updates are silent.

## Lively import fails: "Unknown options are passed. WallpaperPluginException"

If Lively shows *Error initializing — Unknown options are passed.
Exception: WallpaperPluginException* when importing the wallpaper,
you're on the broken **v0.7.0** Lively bundles —
`LivelyInfo.Arguments` carried an invalid `--system-cursor true`
value that Lively rejects on import. Fixed in **v0.7.1** (Arguments
reverted to `null`).

To recover:

1. Install **v0.7.1** or newer (re-run the installer with *Auto-import
   into Lively* enabled, or grab the fresh `SignalRGB_Glow_ScreenN.zip`
   from the release page).
2. In Lively's Library, delete the broken tiles (the import error
   leaves a stub entry), then re-import the fresh zip.

The parallax + cursor-driven Pixelfx effects still work on v0.7.1 —
they receive the cursor through the DOM `mousemove` listener whenever
Lively's *Wallpaper interaction* setting is on, instead of through
the rejected argument.

## Parallax / cursor effects don't react in Lively

The 3D parallax (Configurator → Effects → *3D parallax*) and the
mouse-driven Pixelfx modes (*Trail*, *Glow*, *Ripple — all*) need
real-time cursor coordinates. v0.7.1 reads them from the wallpaper
page's DOM `mousemove` events, which only fire when the wallpaper
surface is reachable by real mouse events:

- **Lively** — toggle the wallpaper's *Wallpaper interaction* setting
  to **on** (right-click the active tile → *Customise* → top of the
  panel). Click-through mode delivers no DOM mousemove events to the
  page, so the parallax / Pixelfx stays still.
- **Wallpaper Engine** — set *Mouse input* to *Allow*. Same logic.
- **Builder / Configurator preview / browser tab** — works
  automatically; those surfaces are normal interactive web pages.

Click-driven Pixelfx (the *Ripple* mode) additionally needs real
clicks to reach the wallpaper, which is the same requirement as
*interaction-on*.

## Setting the SignalRGB plugin's Glow Grid Base Size > 36 errors out

Symptom: in SignalRGB's plugin settings, you bump *Glow Grid Base
Size* to **64**, **96**, or **128**, hit Save, and SignalRGB's log
shows:

```text
udp.error - Buffer too large. Max size is 4096 bytes!
```

This is the SignalRGB plugin sandbox's hard 4 KB `udp.send()` cap.
The plugin and bridge **do** support larger grids — v0.6.0+ chunks
frames > 4 KB across multiple datagrams (`SC` wire format) and the
bridge reassembles them.

If you're seeing the error:

- **Check the bundle versions match.** Both `SignalRGBBridge.exe` and
  `SignalRGB_Desktop_Wallpaper.js` must be ≥ v0.6.0 — the chunked
  protocol is implemented in both halves. Old plugin file + new
  bridge (or vice versa) fall back to the single-packet `SR` format
  and hit the limit.
- **Re-run the installer** with *Install the SignalRGB Desktop
  Wallpaper plugin* enabled to drop the matching JS / QML in
  `Documents\WhirlwindFX\Plugins\`.
- Then re-pick **64 / 96 / 128** in the plugin settings.

## Plugin's Aspect Ratio = Auto, but the glow grid is still square

The plugin's *Auto* mode reads the per-screen viewport from the
bridge's `GET /config` endpoint, and the bridge only knows the
viewport once a wallpaper page has connected via WebSocket and pushed
its `{type:"viewport", w, h}` frame. Before that's happened, *Auto*
falls back to 16:9.

Steps to check:

1. **Is the wallpaper actually running?** Set the wallpaper in Lively /
   Wallpaper Engine for that screen index. The viewport is sent on
   WS open + on `window.resize` (debounced).
2. **Does the bridge see it?** Open
   `http://127.0.0.1:17320/config` in a browser — the `screens[]`
   array should show `{viewportW: …, viewportH: …}` populated for
   each connected screen.
3. **Is the plugin reading it?** Check SignalRGB's log
   (`SignalRGB_*.log`); on every Update tick the plugin XHRs `/config`
   and updates its internal viewport cache. A grid change is logged
   as `screen N grid CxR (aspect=Auto)` — confirm the numbers match
   the monitor.

If the wallpaper has been running but the viewport is still 0, the
WS connect happened before this beta. Reload the wallpaper (Lively:
right-click → *Unset* + *Set as wallpaper* again; WE: similar) to
re-trigger the `viewport` push.

If you'd rather not rely on Auto, pick a fixed aspect (*16:9* /
*21:9* / *32:9* / *9:16*) or *Custom* + type the cols × rows.

## Windows Defender flags `SignalRGBBridge.exe` as Trojan:Win32/Wacatac.C!ml

This is a false positive on the PyInstaller `--onedir` build. `Wacatac.C!ml`
is a machine-learning heuristic detection — it fires on lots of
PyInstaller-packed Python applications because the bootloader pattern
(small native EXE that unpacks a Python interpreter + bytecode into
`_internal/` at startup) overlaps with common malware packers.

**The bridge does nothing malicious.** Source is at
[github.com/Delido/signalrgb-wallpaper](https://github.com/Delido/signalrgb-wallpaper)
and the build is reproducible (`pwsh installer\build.ps1`).

### Recovery

1. Open *Windows Security → Virus & threat protection → Protection
   history* → click the Wacatac entry → **Actions → Allow**.
2. If the file was quarantined: click **Actions → Restore**. If
   Restore is greyed out, re-run the installer — it'll drop a fresh
   copy at the original path.
3. (Optional, only if it keeps re-flagging) *Windows Security →
   Virus & threat protection → Manage settings → Exclusions →
   Add an exclusion → Folder*, pick
   `%LOCALAPPDATA%\Programs\SignalRGBWallpaper`.

### Help reduce false positives for everyone

The Microsoft Defender team accepts false-positive reports at
[microsoft.com/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission).
A submission with the installer or `SignalRGBBridge.exe` typically
clears the specific build's hash within 24-72 hours and trains the
ML model away from this signature for future builds. Free, takes
~2 minutes, requires a free Microsoft account.

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
