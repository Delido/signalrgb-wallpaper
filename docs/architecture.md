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
│  │   - DiscoveryService announces 1..3 virtual controllers  │  │
│  │   - Per-device Render() samples device.color(x,y)        │  │
│  │   - Sends UDP frame per device, tagged with screen index │  │
│  │   - XHRs bridge /config every ~2s for screenCount        │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                          │
                          │  UDP 127.0.0.1:17320
                          │  per frame: [SR][screen][w][h][rgb...]
                          ▼
┌────────────────────────────────────────────────────────────────┐
│  SignalRGBBridge.exe   (PyInstaller bundle of bridge.py)       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ asyncio thread:                                          │  │
│  │   - UDP listener :17320 — parses screen byte, routes     │  │
│  │   - WS server :17320/?screen=N — per-screen fan-out      │  │
│  │   - HTTP image proxy :17320/image?path=… — CEF workaround│  │
│  │   - HTTP /config — exposes screenCount to plugin         │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ pystray thread (main): tray icon + menu                  │  │
│  │   - "Settings…" spawns tkinter dialog                    │  │
│  │   - "Reload config" re-reads + pushes to all clients     │  │
│  │   - "Quit" → os._exit(0) hard kill                       │  │
│  ├──────────────────────────────────────────────────────────┤  │
│  │ Per-dialog thread: tkinter Settings UI                   │  │
│  │   - Reads/writes %LOCALAPPDATA%/SignalRGBWallpaper/config│  │
│  │   - On Save: persists JSON + pushes to live wallpapers   │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                          │
                          │  ws:// + http:// on 127.0.0.1:17320
                          ▼
┌────────────────────────────────────────────────────────────────┐
│  Lively (one HTML wallpaper instance per monitor)              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ index.html (in CEF)                                      │  │
│  │   - <meta signalrgb-screen-index="N"> baked per-zip      │  │
│  │   - Connects ws://127.0.0.1:17320/?screen=N              │  │
│  │   - Binary frames → CSS-grid glow render                 │  │
│  │   - Text frames (settings JSON) → apply property changes │  │
│  │   - Background image via /image proxy (absolute paths)   │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## Wire format: UDP plugin → bridge

Each datagram is exactly one frame. No fragmentation, no batching.

```text
offset  size  field
   0    1     magic byte 'S'    (0x53)
   1    1     magic byte 'R'    (0x52)
   2    1     screen index      (u8, 0-2)
   3    2     width             (u16, big-endian)
   5    2     height            (u16, big-endian)
   7    W*H*3 RGB triplets      (row-major, 8-bit per channel)
```

Maximum payload at 32×32 grid: 7 + 32×32×3 = 3079 bytes. Well below the
typical UDP MTU on localhost; no fragmentation handling needed.

## Bridge ↔ wallpaper protocol

The wallpaper page is a WebSocket *client* of the bridge. The bridge is
the *server* and never expects payloads from the page (the page never
sends WS frames; the bridge ignores anything that arrives).

### Binary frames (bridge → page)

Wrapped raw UDP datagram. The bridge does not re-encode or strip the
header; the page parses the same `[SR][screen][w][h][rgb...]` layout
it received over UDP. The screen-index byte is technically redundant
(the bridge already filtered by `?screen=N`) but kept for symmetry.

### Text frames (bridge → page)

JSON-encoded settings push:

```json
{
  "type": "settings",
  "screen": 0,
  "data": {
    "bgImage": "C:/path/to/wallpaper.png",
    "bgFit": "cover",
    "bgDim": 0,
    "barLayout": "lay-grid",
    "showBars": true,
    "glowStrength": 100,
    "gridBlur": 30,
    "stripesBlur": 60,
    "barHeight": 38,
    "barWidth": 14,
    "showStatus": false
  }
}
```

Sent:
- Once on WS upgrade (initial settings for the connecting screen)
- On every Save in the tray Settings dialog (re-pushed to every
  connected page for the affected screen)

The page applies each `data.<key>` value via its existing
`applyProperty(name, val)` switch.

## HTTP endpoints on the bridge

Same port as the WS server (17320). The TCP handler distinguishes
WebSocket upgrades from plain HTTP by the `Upgrade: websocket` header.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/?screen=N` | GET + Upgrade | WebSocket upgrade, subscribes to screen N |
| `/image?path=<abs>` | GET | Proxies a local image file (whitelisted extensions). Workaround for Lively's CEF file:// sandbox blocking paths outside the project folder. |
| `/config` | GET | Returns `{"screenCount": N}` JSON. Polled by the SignalRGB plugin every ~2s. |

## Threading model in the bridge

Three concurrent contexts:

1. **Daemon thread** — owns the asyncio event loop. Runs UDP receiver,
   WS server, HTTP image proxy, settings push.
2. **Main thread** — runs `pystray.Icon.run()` which blocks on the
   Win32 message pump.
3. **Per-dialog thread** — spawned (daemon) when "Settings…" is
   clicked. Creates a `tk.Tk()` and runs `mainloop()`. Destroyed when
   the dialog closes.

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
├── SignalRGB_Desktop_Wallpaper.js              # plugin source
├── SignalRGB_Desktop_Wallpaper.qml             # plugin Service-Page UI
├── docs/                                       # this folder
└── wallpaper_bridge/
    ├── bridge.py                               # bridge + tray source
    ├── smoke_test.py                           # dev test for per-screen routing
    └── wallpaper/                              # HTML wallpaper template
        ├── LivelyInfo.json                     # Type 1 Web wallpaper, with __SCREEN_LABEL__
        ├── index.html                          # CEF WebSocket client + render
        └── images/                             # bundled example backgrounds
```

Build outputs (`build_bridge/`, `dist_bridge/`, generated zips, exe) are
gitignored — they're published as release assets, not committed.

## Versioning

We follow [SemVer](https://semver.org/). The plugin's `Version()` export,
the bridge's printed banner, and the GitHub release tag are all kept
in sync. Wire format changes are major bumps; new optional features are
minor bumps; bug fixes are patch bumps.
