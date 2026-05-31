# REST API

The bridge exposes a versioned HTTP API at `/api/v1/*`. The same
endpoints are also described by the machine-readable
[OpenAPI 3.1 spec](http://127.0.0.1:17320/api/openapi.json) the
bridge serves at `/api/openapi.json` — point a Swagger UI / curl
/ Postman / Insomnia at it for live exploration.

This doc is the human-readable companion; the OpenAPI spec is
authoritative when they drift.

## Where the bridge lives

| Where | Value |
|---|---|
| Default binding | `127.0.0.1:17320` (loopback only) |
| WS endpoint | `ws://127.0.0.1:17320/?screen=<n>[&role=configurator]` |
| HTTP endpoint | `http://127.0.0.1:17320/api/v1/...` |
| OpenAPI spec | `http://127.0.0.1:17320/api/openapi.json` |

The bridge currently binds to **loopback only**. External LAN
clients can't reach `17320` without an explicit opt-in (planned
follow-up). On the same machine, every request is loopback
which means every request bypasses auth.

## Authentication

Every `/api/v1/*` endpoint accepts `Authorization: Bearer
<apiToken>`. The token:

- Is auto-generated on first bridge run (32-byte `secrets.token_urlsafe`)
- Is stored in `%LOCALAPPDATA%\SignalRGBWallpaper\config.json`
  under `apiToken`
- Is displayed in the Configurator's **System → REST API token**
  card (hidden by default, press-to-show, **Copy & forget**
  copies + auto-clears the clipboard after 30 s)
- Can be regenerated at any time via the same card or via
  `system-action regenerate-api-token` over the WS

**Loopback requests bypass auth.** A request from `127.0.0.1` /
`::1` doesn't need the header. Anything else (when LAN-binding
opt-in lands) must supply a valid token or gets a 401.

`/api/openapi.json` is public regardless — the spec itself is
not a secret.

## Endpoints

### `GET /api/v1/info`

Bridge version + capabilities.

```bash
curl http://127.0.0.1:17320/api/v1/info
```

```json
{
  "appVersion": "1.5.0-beta",
  "wallpaperVersion": "1.5.0-beta",
  "screenCount": 4,
  "maxScreens": 4,
  "presetSlots": 4,
  "capabilities": [
    "presets", "profiles", "openrgbOutput", "openrgbInput",
    "sacnOutput", "sacnInput", "spatialMapping",
    "mqttBridge", "plugins"
  ]
}
```

### `POST /api/v1/auth/verify`

Verifies the supplied token works (i.e. returns 401 instead of
200 on a bad token). Useful for "is my Stream Deck config
correct" sanity checks.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:17320/api/v1/auth/verify
```

```json
{ "ok": true }
```

### `GET /api/v1/screens`

List all bridge screens with summary info.

```json
{
  "screens": [
    {
      "index": 0,
      "active": true,
      "viewportW": 5120,
      "viewportH": 1440,
      "mirrorOf": null,
      "bgImage": "C:/Users/me/AppData/Local/SignalRGBWallpaper/screens/screen-0-...png"
    },
    { "index": 1, "active": true, ... },
    { "index": 2, "active": false },
    { "index": 3, "active": false }
  ]
}
```

`active: false` means the bridge is currently configured for
fewer screens than `maxScreens` (4). `mirrorOf` is the index of
the screen this one mirrors, or `null` if independent.

### `GET /api/v1/screens/<n>/settings`

Read the full per-screen settings blob. Shape matches what the
Configurator writes on the WebSocket — too many fields to
enumerate here; check `wallpaper_bridge/bridge.py`'s
`DEFAULT_SCREEN_SETTINGS` for the source of truth.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:17320/api/v1/screens/0/settings | jq .
```

Returns 404 if `n` is out of range.

### `POST /api/v1/screens/<n>/preset/<slot>/apply`

Apply preset slot `<slot>` to screen `<n>`. Slot indices are
`0..PRESET_SLOTS-1` (0..3 today).

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:17320/api/v1/screens/0/preset/2/apply
```

```json
{ "ok": true }
```

Response codes:

- `200 { "ok": true }` — applied
- `404` — screen or slot out of range
- `409` — slot is empty, or the screen is configured as a mirror
  (mirrors can't have presets applied directly; apply the preset
  to the source screen instead)

### `POST /api/v1/screens/<n>/pause`

Manual pause / resume. Body: JSON object with a single boolean
`paused`. (The `<n>` is currently ignored — pause is bridge-
global, but the path parameter is kept for forward compatibility
when per-screen pause arrives.)

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"paused": true}' \
  http://127.0.0.1:17320/api/v1/screens/0/pause
```

```json
{ "paused": true }
```

### `GET /api/v1/profiles`

List per-app profile rules (foreground-watcher-driven preset
switching).

```json
{
  "profiles": [
    {
      "id": "p_1234",
      "enabled": true,
      "exe": "Cyberpunk2077.exe",
      "label": "Cyberpunk",
      "screen": 0,
      "presetSlot": 1
    }
  ]
}
```

CRUD for profiles is currently done over the WebSocket
(`profile-add` / `profile-update` / `profile-remove`); REST CRUD
is a follow-up.

### `GET /api/v1/plugins`

List discovered 3rd-party widget plugins. See
[plugin-api.md](plugin-api.md) for the manifest schema + the
runtime contract.

```json
{
  "plugins": [
    {
      "name": "hello",
      "version": "1.0.0",
      "label": "Hello",
      "author": "you",
      "description": "",
      "widgetHtml": "widget.html",
      "iconSvg": "<svg ...></svg>",
      "defaultSize": { "w": 240, "h": 80 },
      "defaultOptions": { "name": "world" }
    }
  ]
}
```

The bridge rescans the plugins folder on every startup; trigger
a runtime rescan via WS `system-action rescan-plugins` or the
*Rescan plugins folder* button in the Configurator's Plugins
sub-section.

### `GET /api/v1/sacn/discovered`

List E1.31 senders currently advertising universes on the LAN's
Universe-Discovery multicast group (`239.255.250.214`). Stale
entries (no re-announce for >35 s) are pruned automatically.

```json
{
  "senders": [
    {
      "cid": "78c5e2a9b1f3...",
      "sourceName": "xLights",
      "universes": [1, 2, 3, 4, 5],
      "lastSeen": 1748704321.42
    }
  ]
}
```

`cid` is hex-encoded CID (16 raw bytes from the E1.31 frame).
Used by the Configurator's universe pick-list when you switch a
screen's source to sACN.

### `GET /api/v1/mqtt/status`

MQTT bridge state — useful for HA / Node-RED health checks.

```json
{
  "available": true,
  "enabled": true,
  "connected": true,
  "lastError": "",
  "lastConnectTs": 1748704000.0,
  "publishCount": 1247,
  "recvCount": 3,
  "topicPrefix": "signalrgb-wallpaper",
  "host": "localhost"
}
```

## Example: Stream Deck preset hotkey

A typical Stream Deck "System: Open" action with this URL:

```text
curl -X POST -H "Authorization: Bearer YOUR-TOKEN-HERE" \
  http://127.0.0.1:17320/api/v1/screens/0/preset/0/apply
```

…applies preset slot 0 to screen 0 with one button press. Skip
the `Authorization` header if your Stream Deck plugin runs on
the same machine as the bridge — loopback bypasses auth.

## Example: Home Assistant button (without MQTT)

```yaml
rest_command:
  signalrgb_wallpaper_preset:
    url: "http://127.0.0.1:17320/api/v1/screens/{{ screen }}/preset/{{ slot }}/apply"
    method: POST
    headers:
      Authorization: "Bearer !secret signalrgb_wallpaper_token"

# usage in an automation:
service: rest_command.signalrgb_wallpaper_preset
data:
  screen: 0
  slot: 2
```

For a more HA-idiomatic setup, enable the MQTT bridge in the
Configurator instead — HA auto-creates entities per screen, no
REST plumbing needed.

## Adding a new endpoint

The dispatcher is in `wallpaper_bridge/bridge.py` →
`Broadcaster._handle_api_request`. Each route is ~10 LOC: regex
match the path, validate parameters, call into `BridgeRuntime`
methods, return JSON via `_send_json`. Add a matching
`paths:` entry to `_serve_openapi_spec` so the spec stays in sync.
