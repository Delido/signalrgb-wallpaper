# Architecture

How the pieces fit together, and why they're split the way they are.

For the chronological design history (what we tried, what failed, why we
landed here), see [HANDOFF.md](../HANDOFF.md) in the repo root.

## Components

```text
┌────────────────────────────────────────────────────────────────┐
│  SignalRGB                                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ SignalRGB_Desktop_Wallpaper.js (sandboxed JS plugin)     │  │
│  │   - DiscoveryService announces 1..4 virtual controllers  │  │
│  │   - Per-device Render() samples device.color(x,y)        │  │
│  │   - Frames <= 4 KB → single 'SR' datagram                │  │
│  │   - Frames > 4 KB → chunked 'SC' datagrams (frameId,     │  │
│  │     chunkIdx, chunkCount, pixelOffset)                   │  │
│  │   - XHRs bridge /config every ~2s for screenCount        │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                          │
                          │  UDP 127.0.0.1:17320
                          ▼
┌────────────────────────────────────────────────────────────────┐
│  SignalRGBBridge.exe   (PyInstaller bundle of bridge.py)       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ asyncio thread:                                          │  │
│  │   - UDP listener :17320 — parses SR or reassembles SC,   │  │
│  │     routes by screen byte                                │  │
│  │   - WS server :17320/?screen=N — per-screen fan-out      │  │
│  │   - HTTP image proxy :17320/image?path=… — CEF workaround│  │
│  │   - HTTP /builder, /configurator (static HTML)           │  │
│  │   - HTTP /config — exposes screenCount to plugin         │  │
│  │   - HTTP POST /screen/N/background — builder upload sink │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ pystray thread (main): tray icon + menu                  │  │
│  │   - "Configurator…" opens /configurator in browser       │  │
│  │   - "Build Wallpaper…" opens /builder in browser         │  │
│  │   - "Advanced → Legacy Settings dialog" spawns tkinter   │  │
│  │   - "Reload config" re-reads + pushes to all clients     │  │
│  │   - "Quit" → os._exit(0) hard kill                       │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ Per-dialog thread: tkinter Legacy Settings UI            │  │
│  │   - Pre-dates the Configurator; still owns               │  │
│  │     'Number of screens' + per-screen 'Show debug overlay'│  │
│  │   - All other knobs live in the Configurator now         │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ Shared state:                                            │  │
│  │   - %LOCALAPPDATA%/SignalRGBWallpaper/config.json        │  │
│  │     (per-screen settings, screen count, language,        │  │
│  │     update-check flags)                                  │  │
│  │   - %LOCALAPPDATA%/SignalRGBWallpaper/screens/           │  │
│  │     (uploaded backgrounds, screen-N-<timestamp>.png)     │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                          │
                          │  ws:// + http:// on 127.0.0.1:17320
                          ▼
┌────────────────────────────────────────────────────────────────┐
│  Wallpaper host (Lively / Wallpaper Engine)                    │
│  One HTML wallpaper instance per monitor.                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ index.html (in CEF / WebView2)                           │  │
│  │   - <meta signalrgb-screen-index="N"> baked per-zip      │  │
│  │     (or set at runtime via WE's screenIndex property,    │  │
│  │     single-bundle variant)                               │  │
│  │   - Connects ws://127.0.0.1:17320/?screen=N              │  │
│  │   - Binary frames → CSS-grid glow render                 │  │
│  │   - Text frames (settings JSON) → apply property changes │  │
│  │   - Background image via /image proxy (absolute paths)   │  │
│  │   - Sends `viewport` on open + resize                    │  │
│  │   - Sends `widget-*` commands when widgets dragged       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Browser tab (any monitor): /configurator                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ configurator.html (separate WS client, no screen filter) │  │
│  │   - Per-screen tabs; layout preview, widget editor       │  │
│  │   - Sends `setting-update` / `widget-add` / `widget-     │  │
│  │     update` / `widget-remove` / `widgets-lock` commands  │  │
│  │   - Bridge fans the resulting state back to the matching │  │
│  │     wallpaper page over its WS                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## Wire format: UDP plugin → bridge

Each datagram carries either a whole frame (`SR`) or one chunk of a
larger frame (`SC`). The SignalRGB plugin sandbox caps `udp.send()`
at 4 096 bytes, so any frame > ~36×36 RGB grid (3 895 B + 7 B header)
has to be split.

### `SR` — single-packet frame (≤ 4 KB)

```text
offset  size  field
   0    1     magic byte 'S'    (0x53)
   1    1     magic byte 'R'    (0x52)
   2    1     screen index      (u8, 0-3)
   3    2     width             (u16, big-endian)
   5    2     height            (u16, big-endian)
   7    W*H*3 RGB triplets      (row-major, 8-bit per channel)
```

Up to and including a 36×36 grid (3 895 B payload), every frame fits
in one `SR` datagram.

### `SC` — chunked frame (any size)

For frames > 4 KB the plugin splits the RGB payload into N pieces
and ships them in N datagrams sharing a `frameId`. The bridge buffers
chunks by `(screen, frameId)` and reassembles before forwarding. A
partial frame that doesn't complete within `_STALE_AFTER_S` (0.2 s)
is dropped — the next full frame from the plugin replaces it.

```text
offset  size  field
   0    1     magic byte 'S'    (0x53)
   1    1     magic byte 'C'    (0x43)
   2    1     screen index      (u8, 0-3)
   3    1     frameId           (u8, wraps modulo 256)
   4    1     chunkIdx          (u8)
   5    1     chunkCount        (u8)
   6    2     width             (u16, big-endian)
   8    2     height            (u16, big-endian)
  10    2     pixelOffset       (u16, big-endian — start pixel)
  12    L     RGB triplets      (L = MAX_PAYLOAD - 12; last chunk
                                  carries the remainder)
```

Valid grid sizes are `[8, 16, 32, 36, 64, 96, 128]` (the combobox
options in the plugin's QML). 32 / 36 stay on the `SR` path; the
larger three go chunked.

## Bridge ↔ wallpaper protocol

The wallpaper page and the Configurator are both WebSocket *clients*
of the bridge. The bridge is the *server*; it fans the reassembled
SignalRGB UDP frames out as binary WS frames, and it pushes settings
state as text frames. The page and the Configurator can also send
text frames back — page-side for viewport reports, Configurator-side
for the bulk of settings mutations.

### Binary frames (bridge → page)

A reassembled SignalRGB frame, re-wrapped in the `SR` layout:
`[SR][screen][w][h][rgb...]`. Chunked `SC` frames are merged on the
bridge before forwarding, so the page only ever sees `SR`. The screen
byte is technically redundant (the WS subscription already filtered
by `?screen=N`) but kept for symmetry with the UDP-level format.

### Text frames (bridge → page / Configurator)

JSON-encoded settings + sysstats + pause-state push.

`type: "settings"` — current per-screen settings snapshot. Sent on WS
open and after every Configurator / tray / legacy-dialog mutation
that affects that screen:

```json
{
  "type": "settings",
  "screen": 0,
  "language": "en",
  "data": {
    "bgImage": "C:/Users/.../wallpaper.png",
    "bgFit": "cover",
    "bgDim": 0,
    "barLayout": "lay-grid",
    "showBars": true,
    "glowStrength": 100,
    "gridBlur": 30,
    "stripesBlur": 60,
    "showStatus": false,
    "ambientPreset": "snow",
    "ambientTint": false,
    "ambientDensity": 60,
    "pixelfxMode": "all",
    "parallax3d": 30,
    "widgetsLocked": false,
    "widgets": [ /* { id, type, x, y, w, h, options } */ ],
    "viewportW": 3840,
    "viewportH": 2160
  }
}
```

`type: "paused"` — wallpaper should pause / resume rendering. Tracked
separately so the bridge can push pause state without re-serialising
the full settings blob.

`type: "sysstats"` — periodic snapshot from the `psutil` poller for
the CPU / RAM / Network widgets. One frame is fanned out to every
connected client at a fixed interval.

The page's `livelyPropertyListener(name, value)` (also wired up for
WE via `wallpaperPropertyListener.applyUserProperties`) handles each
`data.<key>` value through the same switch the wallpaper-host
properties go through, so settings push and host-property push share
one application path.

### Text frames (page / Configurator → bridge)

JSON commands. The bridge routes them through
`Broadcaster.handle_client_message(screen, msg)`. Recognised types
(unknown types are silently dropped — newer clients shouldn't crash
an older bridge):

| `type` | Sender | Payload | Effect |
| --- | --- | --- | --- |
| `viewport` | wallpaper page | `{w, h}` | Bridge persists `viewportW/H` for that screen; Configurator's layout preview reads these to scale correctly (avoids 4K layouts squeezed into a 1080p box). |
| `setting-update` | Configurator | `{key, value}` | Updates one settings field; persists + re-pushes. |
| `widget-add` | Configurator + wallpaper page (after drag) | `{widget: {…}}` | Appends to the `widgets` array. |
| `widget-update` | both | `{id, patch: {…}}` | Patches one widget's fields (position, size, options). |
| `widget-remove` | Configurator | `{id}` | Drops a widget. |
| `widgets-lock` | Configurator + tray | `{locked: bool}` | Flips the `widgetsLocked` master toggle. |

## HTTP endpoints on the bridge

Same port as the WS server (17320). The TCP handler distinguishes
WebSocket upgrades from plain HTTP by the `Upgrade: websocket` header.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/?screen=N` | GET + Upgrade | WebSocket upgrade. With `?screen=N` the client joins that screen's fan-out group; the Configurator omits it and joins a broadcast group that sees every screen's settings. |
| `/image?path=<abs>` | GET | Proxies a local image file (whitelisted extensions). Workaround for Lively's CEF and Wallpaper Engine's CEF file:// sandboxes blocking paths outside the project folder. |
| `/config` | GET | Returns `{"screenCount": N, "screens": [{"viewportW": w, "viewportH": h}, …]}` JSON. Polled by the SignalRGB plugin every ~2 s; `screenCount` drives device discovery, the `screens[]` sidecar lets the plugin's Aspect Ratio = *Auto* derive cols × rows from the actual monitor instead of assuming square. |
| `/screen/<N>/background` | POST | Receives a raw PNG body (Content-Type: image/png) and stores it under `%LOCALAPPDATA%\SignalRGBWallpaper\screens\screen-N-<timestamp>.png`. Used by the in-browser builder and the Configurator's *Choose image…* picker (which canvas-encodes any user-picked file to PNG before posting). |
| `/builder` | GET | Serves `builder.html` — the in-browser transparency-cutter. Pure client-side canvas app; saves through the same `POST /screen/N/background` endpoint above. |
| `/configurator` | GET | Serves `configurator.html` — the in-browser settings UI. Opens its own WS to push commands. |

## Threading model in the bridge

Three concurrent contexts:

1. **Daemon thread** — owns the asyncio event loop. Runs UDP receiver
   (including `SC` chunk reassembly), WS server, HTTP image proxy,
   `/builder` + `/configurator` + `/config` HTTP routes, settings push,
   sysstats poller.
2. **Main thread** — runs `pystray.Icon.run()` which blocks on the
   Win32 message pump.
3. **Per-dialog thread** — spawned (daemon) when *Advanced → Legacy
   Settings dialog…* is clicked. Creates a `tk.Tk()` and runs
   `mainloop()`. Destroyed when the dialog closes. The About dialog
   spawns a separate one of these (also tkinter).

Cross-thread invariants:
- The asyncio loop's state is touched ONLY via
  `asyncio.run_coroutine_threadsafe` from other threads
  (see `Broadcaster.push_settings_threadsafe`).
- The shared `config` dict is guarded by `threading.Lock` — all reads
  and writes from non-asyncio threads acquire it.
- `os._exit(0)` is called from the Quit menu callback (worker thread).
  We deliberately do not gracefully shut down — see commit history for
  why `icon.stop()` + return-to-main was unreliable.

## Why a separate bridge process? Can't the plugin do it directly?

Short answer: **no**, the SignalRGB plugin sandbox cannot run a server.

Long answer:

- The SignalRGB plugin runtime exposes `@SignalRGB/udp` (client + server),
  `@SignalRGB/tcp` (documented but missing from runtime — verified
  2026-05-17 with a probe plugin: *"Could not open module
  file:///.../@SignalRGB/tcp for reading"*), HID, base64, and
  `XMLHttpRequest`. It does NOT expose `WebSocket`, file IO, or
  process spawning.
- The Lively wallpaper is HTML in CEF. Browsers cannot receive UDP.
- So a bridge process must exist somewhere to convert UDP → WS.
- The plugin can't *spawn* the bridge (no `child_process`), so the
  bridge has to be a separate, separately-installed executable.

This is the same architecture every "SignalRGB → external app" project
ends up with (e.g. Fefedu973's SignalRGB-To-OpenRGB-Bridge requires a
manually-started Node.js server for the same reason).

## Why not Lively Properties? <a name="why-not-lively-properties"></a>

Lively does deliver `LivelyProperties.json` settings to its built-in
Web wallpaper player — that's how third-party Web wallpapers normally
get a Customise UI. We don't ship a `LivelyProperties.json`, so Lively's
Customise button is intentionally absent for our wallpapers.

Why: settings need to be **per-screen** AND **per-monitor instance**,
and need to live in a place the bridge can also read (so the bridge can
push the same settings to the wallpaper on connect, before the user
even opens the dialog). Lively's per-instance property storage was the
wrong shape:

- It writes per-screen JSON to its own data dir which the bridge has no
  easy way to discover.
- For Application-type wallpapers it doesn't deliver properties at all
  (we verified this in the codebase — `ExtPrograms.LivelyPropertyCopyPath
  => null`, `SendMessage = //todo`).
- Having two systems (Lively Customise AND tray dialog) writing settings
  would be confusing.

So we made the bridge the **single source of truth** for settings. Lively
just shows the wallpaper; the tray owns configuration.

## File layout in the repo

```text
.
├── README.md                                   # user-facing
├── CHANGELOG.md                                # version history
├── LICENSE                                     # MIT
├── HANDOFF.md                                  # design history / archaeology
├── SignalRGB_Desktop_Wallpaper.js              # plugin source (UDP sender)
├── SignalRGB_Desktop_Wallpaper.qml             # plugin Service-Page UI
├── docs/                                       # this folder
├── installer/
│   ├── build.ps1                               # build script (PyInstaller → ISCC)
│   ├── signalrgb-wallpaper.iss                 # Inno Setup script
│   ├── generate_icon.py                        # tray-icon generator
│   ├── generate_thumbnail.py                   # Lively tile thumbnail generator
│   ├── generate_banner.py                      # README banner generator
│   └── generate_workshop_preview.py            # Steam Workshop preview (1920×1080)
└── wallpaper_bridge/
    ├── bridge.py                               # bridge + tray + i18n + About
    ├── smoke_test.py                           # dev test for per-screen routing
    ├── builder.html                            # served at /builder
    ├── configurator.html                       # served at /configurator
    └── wallpaper/                              # HTML wallpaper template
        ├── LivelyInfo.json                     # Type 1 Web wallpaper
        ├── index.html                          # CEF WebSocket client + render
        ├── interact.min.js                     # drag/resize for widgets (MIT)
        ├── interact.LICENSE.txt                # MIT notice required by interact.js
        ├── thumbnail.png                       # Lively tile thumbnail
        ├── workshop_preview.png                # Steam Workshop preview image
        └── images/                             # bundled example backgrounds
```

The Wallpaper Engine bundles staged by `installer/build.ps1` go into
`wallpaper_bridge/we_bundles/SignalRGB_Glow_Screen{1,2,3}/` (per-screen)
and `wallpaper_bridge/we_bundles_single/signalrgb-glow/` (single
combined bundle with the `screenIndex` user property). The Lively
folders go into `wallpaper_bridge/lively_bundles/signalrgb-glow-
screen-{1,2,3}/` and are zipped into `SignalRGB_Glow_Screen{1,2,3}.zip`
release artefacts.

Build outputs (`build_bridge/`, `dist_bridge/`, generated zips, exe) are
gitignored — they're published as release assets, not committed.

## Versioning

We follow [SemVer](https://semver.org/). The plugin's `Version()` export,
the bridge's printed banner, and the GitHub release tag are all kept
in sync. Wire format changes are major bumps; new optional features are
minor bumps; bug fixes are patch bumps.
