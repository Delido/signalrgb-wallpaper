# Plugin API for 3rd-party widgets (v1.5.0-beta)

The bridge scans `%LOCALAPPDATA%\SignalRGBWallpaper\plugins\<name>\`
on startup. Every folder there that contains a `manifest.json` becomes
a new widget type — `plugin/<name>` — that shows up in the
Configurator's *Add widget* picker. Each instance renders into a
**sandboxed iframe** in the wallpaper page, isolated from the rest
of the page.

This doc is the stable contract for plugin authors. If you stick to
it, your plugin keeps working across bridge releases.

## Folder layout

```
%LOCALAPPDATA%\SignalRGBWallpaper\plugins\
    weather-pro\
        manifest.json   (required)
        widget.html     (default name; entry point)
        widget.css      (optional, referenced from widget.html)
        widget.js       (optional, referenced from widget.html)
        icon.svg        (optional, inline SVG markup also accepted)
        assets\         (any other files — images, fonts, …)
```

Anything outside `<your plugin folder>` is **not served** by the
bridge — the HTTP route refuses path traversal. Inside, all files
are reachable via `/plugins/<name>/<relative-path>`.

## manifest.json schema

```json
{
    "name":           "weather-pro",
    "version":        "1.0.0",
    "label":          "Weather Pro",
    "author":         "Your Name",
    "description":    "Detailed forecast widget with hourly chart",
    "widgetHtml":     "widget.html",
    "iconSvg":        "<svg viewBox='0 0 24 24'><circle .../></svg>",
    "defaultSize":    { "w": 320, "h": 240 },
    "defaultOptions": { "city": "Berlin", "units": "metric" }
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | `[a-zA-Z0-9_-]` only. Used in the URL path + the widget type. |
| `version` | yes | Plain string, displayed in the Configurator. |
| `label` | no | Shown in the picker. Defaults to `name`. |
| `author` | no | Free-text. |
| `description` | no | Free-text, max 512 chars. |
| `widgetHtml` | no | Defaults to `widget.html`. Must exist or the plugin is skipped. |
| `iconSvg` | no | Inline `<svg …>…</svg>` markup. Used in the picker. |
| `defaultSize` | no | `{ w, h }` in CSS pixels. Defaults to `320×200`. |
| `defaultOptions` | no | Initial options for new instances. Editable per-instance from the Configurator. |

## Runtime contract

Your `widget.html` runs in an iframe with
`sandbox="allow-scripts"`. That means:

- No access to the wallpaper page's DOM, cookies, or `localStorage`.
- No `<form>` submissions.
- No `window.open()` / no top-frame navigation.
- `fetch()` / `XMLHttpRequest` are subject to the same-origin and
  CSP policies. The bridge serves your assets with `Content-Security-
  Policy: default-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self'` — so cross-origin requests need explicit
  CORS headers from the target.

The wallpaper page talks to your iframe **only** via `postMessage`.
Listen for these messages on `window`:

```javascript
window.addEventListener("message", (ev) => {
    if (!ev.data || typeof ev.data !== "object") return;
    switch (ev.data.type) {
        case "init":
            // Sent once, right after your iframe finishes loading.
            // ev.data.options  → current widget options
            // ev.data.tint     → current glow colour CSS string
            //                    (e.g. "#6ab0ff")
            applyOptions(ev.data.options);
            applyTint(ev.data.tint);
            break;
        case "tint":
            // Sent on every glow-colour change + once per second.
            applyTint(ev.data.color);
            break;
        case "opts":
            // Sent whenever the user edits this widget's options
            // in the Configurator.
            applyOptions(ev.data.options);
            break;
    }
});
```

You can send messages back to the wallpaper page via
`window.parent.postMessage({...}, "*")`. Today only the `log` type
is forwarded — anything else is ignored:

```javascript
window.parent.postMessage({ type: "log", message: "loaded" }, "*");
```

(A future revision will open a small set of safe RPCs — subscribe to
sysstats, request a settings change. For v1.5 the protocol is
outbound-only from the wallpaper page.)

## Minimal example

`%LOCALAPPDATA%\SignalRGBWallpaper\plugins\hello\manifest.json`:

```json
{
    "name": "hello",
    "version": "1.0.0",
    "label": "Hello",
    "iconSvg": "<svg viewBox='0 0 24 24'><circle cx='12' cy='12' r='9'/></svg>",
    "defaultSize": { "w": 240, "h": 80 },
    "defaultOptions": { "name": "world" }
}
```

`hello\widget.html`:

```html
<!doctype html>
<meta charset="utf-8">
<style>
    html, body { margin: 0; padding: 0; height: 100%;
                  display: grid; place-items: center;
                  background: rgba(0, 0, 0, 0.6); color: #fff;
                  font: 18px system-ui, sans-serif; }
    .ring { color: var(--tint, #6ab0ff); }
</style>
<div id="root">…</div>
<script>
    let opts = {};
    function render() {
        document.getElementById("root").innerHTML =
            "Hello, <span class='ring'>" +
            (opts.name || "world") + "</span>";
    }
    window.addEventListener("message", (ev) => {
        if (!ev.data) return;
        if (ev.data.type === "init" || ev.data.type === "opts") {
            opts = ev.data.options || {};
            render();
        }
        if (ev.data.type === "init" || ev.data.type === "tint") {
            const c = ev.data.tint || ev.data.color;
            if (c) document.documentElement.style.setProperty("--tint", c);
        }
    });
    render();
</script>
```

Restart the bridge (or hit the rescan button in the Configurator's
*Plugins* sub-section), then open the wallpaper page's widget
picker — *Hello* appears as a new entry.

## Status + reload

- `/api/v1/plugins` (REST API) returns the catalogue.
- `/plugins/<name>/<path>` (HTTP) serves plugin assets — sandboxed
  to the plugin's own folder, refuses traversal.
- The bridge rescans on startup; the Configurator's *Plugins* card
  has a *Rescan now* button for hot-reload during plugin development.
