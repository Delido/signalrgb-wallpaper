# Roadmap (dev-side, detailed)

Long-form version of the roadmap section in [README.md](../README.md).
Items are grouped by impact-to-effort ratio. Each entry has an
effort estimate (maintainer's order-of-magnitude — not a contract),
status, and any notes on architecture / dependencies.

Status legend:

- 🔲 not started
- 🚧 in progress
- ✅ shipped (these usually get moved to `CHANGELOG.md` instead)
- 🅿️ parked / blocked

---

## 🖼️ Workflow polish — Gallery + Builder + multi-monitor (next beta)

Identified during v0.8.2-beta testing: the "find a wallpaper → cut
transparency into it → use it on a screen" loop is more friction
than it should be, and multi-monitor users have to redo the same
settings on every tab manually.

Split across two betas:

- **v0.8.3-beta — Gallery + Builder bridge** (~13 h)
- **v0.8.4-beta — Multi-monitor convenience** (~9 h)

### ✅ Gallery: hover-preview large + RGB-mock glow behind — shipped v0.8.3-beta

Hovering a Library tile pops a larger preview (around 800 × 450)
with an animated RGB-cycle gradient behind the transparent
cut-outs (or the live `currentTintCss` value if a wallpaper page
is already running). You see what the wallpaper *actually looks
like* before you commit. Click anywhere outside or press Esc to
dismiss; Apply button inside the preview to commit.

### ✅ Gallery: click is preview, Apply is separate + 5 s Undo-Toast — shipped v0.8.3-beta

Currently a single click wipes the screen's existing background.
Split into a *preview* click (popup as above) + a deliberate
*Apply* button inside. Plus: after Apply, a 5-second
*"Undo — restore previous background"* toast at the bottom of the
Configurator. Reverts via the same `POST /screen/N/background`
path using a cached prev-bg blob.

### ✅ Gallery: right-click context menu — shipped v0.8.3-beta

`contextmenu` event on Library tiles → custom menu (Configurator
already has the styling chops for it):

- Apply (default left-click action; here just for symmetry)
- Edit in Builder → opens `/builder` in a new tab with the
  image's path as a query parameter (see Builder "Open from
  library" below)
- Rename → prompts for a new label, renames the file +
  regenerates `library.json`
- Duplicate → copies the PNG with a "-copy" suffix + new
  catalogue entry
- Delete → same path as the existing hover-× button

### ✅ Gallery: sort + pin favourites — shipped v0.8.4-beta

`library.json` gains optional `pinned: true` and `addedAt`
timestamps. Render order: pinned first → built-in starters →
user uploads sorted by addedAt descending. Right-click → Pin /
Unpin toggle.

### ✅ Gallery: drag-and-drop reorder — shipped v0.8.4-beta

HTML5 drag API on Library tiles. On drop: bridge gets a
`POST /library/reorder` with the new `order` array; persisted as
an `order` field per entry in `library.json`. Render order falls
back to addedAt when `order` is absent (backwards-compatible).

### ✅ Builder: "Open from library" picker — shipped v0.8.3-beta

Currently Builder only accepts *Choose image…* + drag-and-drop.
Adds a dropdown next to those that lists every Library item;
pick one and the Builder loads it as the active image. Also
honours `?image=<path>` query string so Configurator's
*Edit in Builder* context-menu entry can deep-link.

### ✅ Builder: "Save to library" button — shipped v0.8.3-beta

New action next to *Apply to Screen N* / *Save as PNG*:

- *Save to library as…* → prompts for label, creates a new
  Library entry from the current canvas
- *Update library entry* → only enabled when the user opened
  this image from Library; overwrites in place

### ✅ Builder: live RGB preview behind the canvas — shipped v0.8.4-beta

Toggle in the Builder's top bar: *"Show glow preview"*. When on,
a CSS layer underneath the canvas runs an animated RGB cycle
(re-uses the same gradient style the Library preview uses), so
the user sees what their cut-outs look like against actual
shifting colour as they work. Defaults to off to keep the
edit canvas clean.

### ✅ Configurator: tab labels with resolution — shipped v0.8.5-beta

Tab text becomes "Screen 1 — 3840×1080" using `viewportW/H` from
the screen's settings (the bridge already tracks this for the
plugin's Auto-aspect-ratio feature). On screens that haven't
connected a wallpaper page yet, falls back to just "Screen N".

### 🔲 Configurator: mirror mode per tab — ~3 h

Checkbox in each non-Screen-1 tab: *"Mirror Screen 1"*. When
enabled, the tab becomes read-only and every settings push for
Screen 1 also gets pushed to this screen. Persisted as
`screen.mirrorOf: 0` in `config.json`. Bridge enforces the
mirror invariant on the server side so external clients (REST
API in the future) can't bypass it.

### 🔲 Configurator: "Apply to all screens" button per section — ~2 h

Small button at the right of each settings section header
(Background, Glow, Effects, Widgets): *"Apply to all screens"*.
Copies this screen's section's values to every other screen in
one shot. Quick-config instead of N-times manual setting.

### 🔲 Configurator: overview card with mini-thumbnails — ~3 h

A new card at the top of the Configurator, above the tab bar:
horizontal row of N small monitor-frame thumbnails (matching the
screen count), each showing the current background image of its
screen. Click a thumbnail → jumps to that Screen's tab. Visual
overview of which monitor shows what, without having to flip
through tabs.

### 🔲 Builder: Ctrl + Wheel zoom — ~1 h

Currently zoom is via a slider. Add `wheel` event handler with
`ctrl` modifier → zoom in / out anchored at cursor position.
Industry-standard editor feel.

### ✅ Builder: crop tool — shipped v0.8.5-beta

New toolbox entry: *Crop*. Drag a rectangle; on confirm, the
canvas resizes to that rectangle. Pre-fills the rectangle to
match the target screen's aspect ratio when known (we have
`viewportW/H` from the screen the user came from). Useful for
3840 × 2160 source images that need to fit a 3840 × 1080
ultrawide.

---

## 🎯 Tier 1 — Setup polish (biggest UX wins for least effort)

These directly reduce the "I installed it and nothing happens / I
broke something" support surface. Tier 1 = ~10 hours of work total
for a massive UX bump.

### 🔲 Setup health check in the tray — ~2-3 h

Tray entry *"System status…"* opens a small dialog with green/red
dots for:

- SignalRGB plugin file present in `Documents\WhirlwindFX\Plugins\`
- SignalRGB process running
- Bridge port 17320 reachable (== the bridge itself is alive)
- At least one wallpaper page connected (Lively or WE actively
  rendering)
- LibreHardwareMonitor reachable (only if a Hardware Sensor widget
  exists)

Each red dot has a *"Fix this…"* button — opens the relevant
folder / runs the relevant installer / pops the relevant doc page.

### 🔲 Backup + restore config — ~2 h

- *Export all* button in Configurator → writes a ZIP containing
  `config.json` + `library/` + uploaded `screens/` images +
  `help_images/` if any
- *Import from ZIP* button → drops everything back into
  `%LOCALAPPDATA%\SignalRGBWallpaper\`, restarts the relevant
  pollers
- Killer feature for: fresh Windows installs, multi-PC users,
  "let me try something risky" recovery, sending a config to a
  friend

### 🔲 Reset + undo — ~1 h

- *Reset this screen to defaults* button per Configurator tab
- Ctrl+Z in the Configurator → undo last ~10 settings changes,
  scoped per screen
- Implementation: ring buffer of last-N settings snapshots; Ctrl+Z
  pushes the previous snapshot back to the bridge via the existing
  `setting-update` WS commands

### 🔲 First-run onboarding tour — ~4 h

- Detect first launch (no key in `localStorage`)
- Overlay with 4 steps: screen count picker → background library →
  glow strength → done
- Each step highlights the relevant UI element with a soft
  border + tooltip + Next button
- Skippable; persists "tour completed" in localStorage

---

## ✨ Tier 2 — High-visibility user features

These are the features that get screenshotted and shared. Higher
ratio of "wow factor" to implementation effort.

### 🔲 Wallpaper shuffle / cycle — ~3 h

Library-section toggle:

- Cycle every X minutes
- Random on logon
- Pick by time of day (4 entries: dawn / day / dusk / night)

Implementation: bridge poller picks next entry from
`config.screens[N].cycle.pool` on schedule, fires the same
`POST /screen/N/background` path the Library tile click uses.

### 🔲 Preset hotkeys — ~3 h

Global `Ctrl+Shift+1..4` to swap between the four per-screen
preset slots without touching the Configurator.

Windows-side: register hotkeys via the bridge's main thread using
`RegisterHotKey` (Win32 API; we already have the bridge process
running so it's the natural home). On press, fire the same
`preset-apply` WS command the Configurator's Apply button uses.

### 🔲 Per-app / per-game profiles — ~5-6 h

Foreground-window watcher in the bridge (polls
`GetForegroundWindow` + `GetWindowThreadProcessId` every 500 ms
when at least one profile rule exists). When the foreground exe
matches a profile, swap to that profile's preset; revert when it
goes away.

Profile rules live in `config.profiles = [{ exe: "cyberpunk2077.exe",
screen: 0, preset: 1, dimAmbient: true }, …]`. Configurator gets
a new section to add / edit / remove rules.

Pro-level feature; huge USP against ordinary wallpaper tools.

### 🔲 Now-playing widget — ~3 h

Current track from Windows' `SystemMediaTransportControls` API
(`Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager`).
Works with Spotify, Groove, Chrome+YouTube, anything that publishes
SMTC metadata.

Python access via `winrt` package. Bridge polls every second,
publishes `{title, artist, album, paused, position}` alongside
sysstats. Widget shows title + artist + a tiny progress bar.

---

## 🛠️ Tier 3 — Power-user / polish

### 🔲 Builder: AI cut-out tool — ~6-8 h

Tiny WebAssembly background-removal model — ONNX runtime web
together with a small U²-Net variant, or alternatively RemBG.js.
Adds a *"Auto-cut bright regions"* tool to the toolbox; one click
runs the model on the current image and writes the predicted
alpha mask.

Risks: WebAssembly model can be 5-20 MB which bloats the bundle.
Maybe lazy-load from a CDN on first use instead of bundling.

### 🔲 Winget package + auto-update — ~3 h

- Submit a manifest to `microsoft/winget-pkgs`:
  `winget install Delido.SignalRGBWallpaper`
- Add a *"Download + install update"* button in the Updates tray
  submenu (currently we only link to the release page). The bridge
  downloads the new installer to `%TEMP%`, runs it silently with
  `/VERYSILENT /SUPPRESSMSGBOXES`, then exits to let the installer
  do the rest.

### 🔲 Mobile Configurator view — ~4 h

Make `/configurator` responsive (CSS media queries, hide the
draggable layout-preview canvas on small screens, swap the tab
bar for a dropdown). Phone in the same Wi-Fi network can then
hit `http://<pc-ip>:17320/configurator` and change wallpaper
settings — niche but a fun party trick.

Caveat: the bridge currently binds to 127.0.0.1 only. Mobile
access would need an opt-in toggle to bind to 0.0.0.0 (with a
loud "this exposes your wallpaper config to the LAN" warning).

### 🔲 Community wallpaper gallery — ~10-15 h

A second repo (`signalrgb-wallpaper-community`) with a curated
`wallpapers.json` index pointing at PNG release-asset URLs. The
Configurator's Library section gets a *Browse community* tab that
fetches the index and shows thumbnails. Users submit via PR with
a CC-licensed image + an entry in the JSON.

Bridge proxies download requests so the CEF doesn't have to deal
with cross-origin issues.

### 🔲 Ambient effects: port MIT-licensed CodePen pens — ~2-3 h per effect

[ykob](https://github.com/ykob)'s catalog is explicitly MIT
("If you want to use some code, you can use these freely by
adding license notation"). Some candidates:

- `ykob/pen/aBrjaR` — user-suggested starting point. Verify
  per-pen license in CodePen Settings before porting.
- Equivalent particle / flow-field / waveform pens from same author

For each ported pen:

1. Confirm per-pen license (CodePen Pro can override the default
   MIT — `Settings → License` on the pen)
2. Adapt to our `ambient` IIFE pattern: `#ambient-canvas` element,
   start/stop based on user toggle, viewport-resize handler,
   tintFromGlow option
3. Add an entry to `docs/credits.md` with: author, pen URL,
   license, optional attribution string for the wallpaper
   credits / About dialog
4. Add a per-file MIT notice comment block in the ported code

---

## 🔌 Tier 4 — Ecosystem / integration

Not a single user need; broader API + plugin work. Lower priority
unless a community / power-user request comes in.

### 🔲 Home Assistant / MQTT bridge

Bridge publishes wallpaper state (current preset, current
background, glow strength, sysstats, hwmon sensors) on MQTT topics
`signalrgb-wallpaper/<screen>/...`. Subscribes to control topics
so HA can apply presets / change backgrounds via automations.

### 🔲 REST API (formalised)

Already partially possible (`/library/list`, `/config`,
`/hwmon/sensors`, `/screen/N/background`). Formalise the rest:
list/apply presets, update settings, list/add/remove widgets.
OpenAPI spec at `/api/openapi.json`. Token auth (loopback-friendly
secret in `config.json`) so external clients can act on user's
behalf without exposing localhost-only ops to anything that hits
17320.

### 🔲 Plugin API for third-party widgets

Drop a folder under `%LOCALAPPDATA%\SignalRGBWallpaper\plugins\
<name>\` with `widget.js` + `widget.html` + `manifest.json`. The
bridge enumerates plugin folders on startup, the wallpaper page
loads each plugin in a sandboxed iframe-like context, the
Configurator picks them up in the widget catalogue.

Long road. Would need a documented stable contract (events,
properties schema, allowed APIs, no arbitrary `fetch()` to
non-allowlisted hosts, etc.).

### 🔲 Generic HTTP widget — ~5-6 h

Polls any URL on a schedule, renders a configurable template.
Covers Discord-unread / stock-ticker / RSS-headline /
crypto-price / arbitrary REST API with one widget type instead
of one widget per service. Template format: simple Mustache /
{{}} placeholders against the JSON response.

Risk: drives arbitrary requests from the wallpaper page; need
to think about cookie / credential isolation.

---

## License-compatibility notes (for future contributors)

- **CodePen public Pens default to MIT** per CodePen's
  documentation; private Pens have no license. Always verify the
  per-pen license in the Pen's *Settings → License* field
  because CodePen Pro users can override the default.
- **MIT + Apache-2.0 + 0BSD + ISC + Unlicense + CC0** — fully
  compatible with our MIT distribution; just add attribution +
  license notice
- **MPL 2.0** — file-based weak copyleft. Compatible *if* we don't
  redistribute / modify the MPL'd source files. LibreHardwareMonitor
  is the canonical example: we poll its HTTP server, don't bundle
  any of its files, so no propagation.
- **GPL / LGPL / AGPL** — copyleft. *Do not* directly link or
  bundle without consulting how that affects our MIT downstream.
  GPL-licensed *processes* are fine (Lively itself is GPL-3.0 —
  we don't link, we just render an HTML file inside it).
- **CC-BY** — attribution required at point of display
  (Open-Meteo, Quotable). Already done for current uses.
- **No license / "All rights reserved"** — assume not usable.
  Don't port.

Document every newly-added third-party piece in
[docs/credits.md](credits.md).
