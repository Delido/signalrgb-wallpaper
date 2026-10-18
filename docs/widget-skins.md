# Widget Skins

Different visual treatments for the **same** widget type. Picked
per widget from the widget config modal — no markup changes
needed, no plugin install, no reload.

## How it works

Each widget type in `wallpaper/index.html`'s `WIDGET_REGISTRY` can
declare an optional `skins` block. Each skin defines its own
`markup()` (the initial inner HTML for the widget body) plus an
optional `render(rec)` that the widget's `tick` callback delegates
to when that skin is active.

```js
WIDGET_REGISTRY.weather = {
  label: "Weather",
  markup: () => "...default layout...",
  tick:   (rec) => {
    const skin = _widgetActiveSkin(rec);
    if (skin && skin.render) skin.render(rec);
    else                     renderWeatherCache(rec);
    // ...other tick work...
  },
  skins: {
    compact: { markup: () => "...", render: (rec) => { /* ... */ } },
    hexagon: { markup: () => "...", render: (rec) => { /* ... */ } },
  },
};
```

A widget's active skin is whatever its `opts.skin` value resolves
to (default = `"default"`, which is implicit — falls back to the
top-level `markup` + the existing `tick` render path). Changing
the skin in the Configurator's widget config modal regenerates
the widget body and adds a `widget-skin-<id>` class so the
matching CSS rules in `<style>` take effect.

## Bundled skins (v2.3.4-beta)

The Weather widget ships three skins as the proof-of-concept set:

| Skin id | Look |
| --- | --- |
| `default` | Icon left · location + condition centre · temperature right · stats row below |
| `compact` | One-line icon + temperature, location + condition combined underneath, no extras |
| `hexagon` | Big hexagonal tile in the centre (icon + temp + condition), small extras row below |

Pick a skin from the widget's gear → **Skin** dropdown in the
Configurator. Switch lives instantly — no reload, no
re-create-from-scratch dance.

## Sensor skins (v2.6.0)

The three sensor widgets — **CPU**, **RAM** and **Hardware sensor** —
share one set of skins:

| Skin id | Look |
| --- | --- |
| `default` | Classic: number plus a thin sparkline (unchanged) |
| `ring` | Donut gauge, the value large in the middle, unit underneath |
| `bar` | Value plus a segmented, slanted bar |
| `graph` | Area graph of the last minute with a `-1m / -30s / now` axis and the current value top-right |

Pick one from the widget's gear → **Look** dropdown.

**Colour** follows the widget theme's accent, or the glow colour when
*Tint with glow colour* is on — so the same widget turns pink on a
synthwave theme and green under a matrix-style glow without extra
settings.

**Scale** (how full the ring or bar is):

1. *Scale maximum* in the widget options, if set
2. the sensor's own range — SignalRGB reports one per sensor, e.g. a
   pump at 0–3000 RPM
3. 0–100 for `%` and `°C`
4. otherwise the recent peak

**Automatic sensor** (Hardware sensor only): instead of picking a
sensor, choose a role — CPU temperature, GPU temperature, GPU load,
liquid temperature or pump speed — and each PC finds its own matching
sensor. SignalRGB sensors are preferred; LibreHardwareMonitor is the
fallback. Hot-spot and memory-junction readings never count as "GPU
temperature". An explicitly picked sensor always wins. This is how the
**Hardware Monitor** Quick Look works on machines whose sensor names it
cannot know.

All three widgets expose a `reading(rec)` returning
`{label, value, unit, decimals, lo, hi, history}`, and the skins only
ever draw a reading. A new sensor source therefore needs no new skin,
and a new skin works for every sensor.

## Discovery

The Configurator hardcodes the skin list per widget type for
v2.3.4-beta. The bridge also serves the catalog at
`GET /widgets/skins[?type=weather]` so future iterations (and 3rd
party tooling) can fetch it programmatically:

```json
{
  "type": "weather",
  "skins": [
    {"id": "default", "label": "Default"},
    {"id": "compact", "label": "Compact"},
    {"id": "hexagon", "label": "Hexagon"}
  ]
}
```

## Adding a new skin

Today every skin is bundled — there's no user-skin install path
yet. To add a new skin for an existing widget type:

1. Define it under `WIDGET_REGISTRY[type].skins.<id>` in
   `wallpaper_bridge/wallpaper/index.html`. Provide a `markup()`
   returning the body HTML and an optional `render(rec)`. The
   tick callback for that widget needs to delegate to
   `_widgetActiveSkin(rec).render` when present (the Weather
   widget shows the pattern).
2. Add matching `.widget-<type>.widget-skin-<id> { … }` CSS in
   the same `<style>` block. The widget-skin-`<id>` class is
   automatically applied to the widget's root element.
3. Append the new id + label to the same widget's entry in
   `SKIN_CATALOG_MIRROR` (wallpaper) **and** to `WIDGET_CATALOG.<type>.schema`'s
   skin select options (`configurator.html`) **and** to the
   server-side catalog in `bridge.py`'s
   `/widgets/skins` handler. Three places, kept in sync by hand;
   for the sensor skins `tests/test_sensor_skins.mjs` fails if they
   drift.

## What about user-uploaded skins?

Planned for a follow-up — likely
`%LOCALAPPDATA%\SignalRGBWallpaper\widget-skins\<widget>\<id>\`
with a `manifest.json` + `body.html` + `style.css` pair, signed
or hash-pinned to prevent drive-by replacement. Until then, every
skin is bundled with the wallpaper code so security is the
build-time review process — no script execution from external
sources.

## Skins ≠ plugins

The existing [Plugin API](plugin-api.md) is for entirely new
**widget types**, served as sandboxed iframes with their own
`manifest.json` discovery path. Skins are a lighter mechanism for
**re-styling existing types** — same data flow, same options
schema, just a different visual rendering. Pick plugins when you
need a new kind of widget; pick skins when you want the existing
clock / weather / calendar to look different.
