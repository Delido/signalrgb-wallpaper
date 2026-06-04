# OpenRGB SDK Server

v1.6.2-beta adds the inverse direction of the v1.4/v1.5 OpenRGB
channels: instead of consuming colours **from** OpenRGB devices, the
bridge can expose itself **to** the OpenRGB GUI as a set of virtual
matrix devices. Any built-in OpenRGB effect (Rainbow Wave, Breathing,
Static, …) — or the OpenRGB Effects Plugin — can then drive the
wallpaper backlight directly, without SignalRGB in the loop.

## How it fits the rest of the bridge

```text
+-----------------+        TCP/6743          +--------------------+
| OpenRGB GUI     | <----------------------> | Bridge SDK server  |
| (effect engine) |   ORGB protocol packets  | (openrgb_server.py)|
+-----------------+                          +--------------------+
                                                       |
                                              UpdateLEDs colours
                                                       v
                                              +--------------------+
                                              | SourceManager      |
                                              | (per-screen routing)
                                              +--------------------+
                                                       |
                                                       v
                                              +--------------------+
                                              | wallpaper glow     |
                                              +--------------------+
```

One virtual device per active screen. Each device is a flat linear
strip with W*H LEDs (default 32×16 = 512 per screen). The
bridge-side effect engine runs the active mode at 30 Hz and pushes
the result into the wallpaper through the same colour-source path
SignalRGB / OpenRGB-input / sACN already use.

## Enable it

1. Open the **Configurator → Integrations** tab
2. Find the **OpenRGB SDK server (beta)** card (between OpenRGB
   output and the per-screen source picker)
3. Tick **Enabled**
4. Confirm the status pill shows `running · 0 client(s)`
5. Default listen port is `6743`. Change it via the **Port** input
   if you've already got something on that port

The default port is **6743** specifically to sidestep the conflict
with OpenRGB's own GUI server running on `6742` on the same
machine. If you bind 6743 manually elsewhere, pick any other free
TCP port — the bridge re-binds immediately on save.

## Connect from OpenRGB

1. Open the OpenRGB GUI
2. Go to the **SDK Client** tab
3. Add a client pointing at `127.0.0.1:6743` (or the bridge host
   if running on another machine)
4. Click **Start Client**
5. Switch to the **Devices** tab — you should see one
   "Wallpaper Screen N" entry per active screen

If the GUI crashes on connect or you see ghost devices, you're on
an older v1.6.2-beta build — make sure you're on the latest
hotfix (post-`bfd909f`).

## Route a screen to SDK colours

Picking an effect in OpenRGB doesn't automatically show on the
wallpaper. The screen also has to be routed to the SDK source via
the per-screen picker further down the Integrations tab:

1. Find the **Colour source per screen** card (below the SDK
   server card)
2. For each screen you want SDK-driven, set the source dropdown to
   **OpenRGB SDK**

Any screen left on SignalRGB / OpenRGB / sACN keeps its existing
source. The SDK server keeps running and receiving writes, but
those writes only land on screens routed to it.

## Available modes

The virtual devices ship 6 modes. The first five are common across
real OpenRGB devices; **Color Wave** is bridge-specific.

| Mode | What it does | Speed | Brightness | Colour picker |
|---|---|---|---|---|
| **Direct** | Accepts `UpdateLEDs` writes verbatim. Use this with the OpenRGB Effects Plugin or external scripts. | — | — | — |
| **Static** | One solid colour across every LED. | — | — | yes (1 colour) |
| **Breathing** | Solid colour pulsing on a `sin(t)` brightness curve. | ✓ | ✓ | yes (1 colour) |
| **Rainbow** | All LEDs share the same hue; hue cycles over time. | ✓ | ✓ | — |
| **Rainbow Wave** | Hue varies per LED position **and** time — colours sweep across the strip. | ✓ | ✓ | — |
| **Color Wave** | Same shape as Rainbow Wave but centred on the picked colour's hue (±15° hue range). | ✓ | ✓ | yes (1 colour) |

Speed slider is normalised 0..100. Internally it maps to a per-mode
cadence — at 100 a Rainbow cycle takes about **2.5 seconds**
across the matrix, at 50 about 5 seconds, at 0 it's effectively
frozen.

Brightness slider scales the output linearly. 0 turns the device off
without dropping the mode; 100 is full.

## When to use which path

| Goal | Best path |
|---|---|
| One quick built-in effect (Rainbow Wave, Breathing, Static) without leaving OpenRGB | **Pick a mode here** + route the screen to "OpenRGB SDK" |
| Cross-device synchronised effects (wallpaper + RAM + keyboard at the same hue offset) | OpenRGB Effects Plugin → Direct mode on every device |
| Audio-reactive / game-reactive effects from a third-party tool | That tool's `UpdateLEDs` writes → Direct mode |
| SignalRGB effects on the wallpaper (the original v1.0 flow) | Leave the screen's source on `SignalRGB`, ignore the SDK server |

These are not mutually exclusive — you can run SDK + SignalRGB on
different screens simultaneously. The bridge routes per screen.

## Per-screen matrix dimensions

The virtual device's matrix is `width × height` LEDs. Default 32×16
matches the typical SignalRGB-grid resolution. You can change it
per screen by editing
`%LOCALAPPDATA%\SignalRGBWallpaper\config.json` →
`openrgbSdkServer.matrix.<screenIndex>`:

```json
"openrgbSdkServer": {
  "enabled": true,
  "host": "0.0.0.0",
  "port": 6743,
  "matrix": {
    "0": [32, 16],
    "1": [64, 32]
  }
}
```

Any 1..256 per dimension is accepted. Larger matrices mean the
descriptor gets bigger but per-LED rendering scales linearly.

A UI for matrix dimensions is a follow-up — for v1.6.2-beta the JSON
edit + bridge restart is the canonical path.

## Status endpoint

The card polls `GET /openrgb-sdk/status` every 2 s while the
Integrations tab is visible. Same JSON shape is callable from
scripts:

```json
{
  "available": true,
  "running": true,
  "host": "0.0.0.0",
  "port": 6743,
  "deviceCount": 1,
  "devices": [
    {"name": "Wallpaper Screen 1", "ledCount": 512, "matrix": [32, 16]}
  ],
  "clientCount": 1,
  "lastUpdateMs": 1717340000000,
  "lastError": "",
  "perScreen": {
    "0": {"firstColor": [255, 100, 0], "lastUpdateMs": 1717340000000}
  }
}
```

## Limitations

- **Linear zone, no matrix_map yet.** Effects iterate left-to-right
  across the LED index range, not row-by-row. Rainbow Wave on a
  32×16 device sweeps as if the LEDs were a single 512-long strip,
  not as a 2D wave. The matrix_size encoding differs between
  OpenRGB versions and the right value is still being pinned down;
  a follow-up will switch to a proper `ZONE_TYPE_MATRIX` once that
  lands.
- **Single zone per device.** No sub-zoning — every effect writes
  all LEDs at once.
- **No persistence of the GUI's last mode pick.** The bridge keeps
  the active mode in memory but doesn't save it; closing the
  OpenRGB GUI and reopening loses the pick. Direct mode is the
  on-connect default for fresh clients.
- **`UpdateSingleLED` is a no-op.** Effects use full `UpdateLEDs`
  writes; the single-LED packet path isn't wired to the engine
  yet.

## Protocol details

For implementers who want to talk to the bridge directly (custom
clients, automation), the server speaks the standard OpenRGB SDK
protocol — same wire format the official GUI uses. See
[wallpaper_bridge/openrgb_server.py](../wallpaper_bridge/openrgb_server.py)
for the byte-level packet builders and the
[OpenRGB SDK reference](https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/OpenRGBSDK.md)
for the protocol definition.
