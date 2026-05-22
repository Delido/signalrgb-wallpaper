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

## 🖼️ Workflow polish — Gallery + Builder + multi-monitor

Identified during v0.8.2-beta testing: the "find a wallpaper → cut
transparency into it → use it on a screen" loop was too much
friction, and multi-monitor users had to redo settings on every
tab manually.

Shipped across the v0.8.3 → v0.8.7 beta cycle:

- **v0.8.3-beta** — Gallery + Builder bridge (hover preview,
  click-to-preview + Undo, right-click menu, Builder open/save
  library, ?library deep-link)
- **v0.8.4-beta** — Pin + sort + drag-reorder, Builder glow preview
- **v0.8.5-beta** — Bug fixes, Builder crop tool, tab labels with
  resolution, library picker on Builder merge slots
- **v0.8.6-beta** — Installer-overwrite hotfix (library.json)
- **v0.8.7-beta** — Apply-to-all per section, overview card with
  mini-monitor thumbnails
- **v0.8.8-beta** — Mirror mode, Builder 2×2-grid merge, Tool-options
  column widened

Workflow-polish slice complete. ✅

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

### ✅ Configurator: mirror mode per tab — shipped v0.8.8-beta

Generalised beyond the original "Mirror Screen 1" — any screen can
mirror any other (cycle/self detection at activation). Bridge
enforces the invariant via `_block_if_mirror` on every per-screen
mutation path (`setting-update`, widgets, presets, background) and
`_replicate_to_mirrors` fans changes out from source to mirrors.

### ✅ Configurator: "Apply to all screens" button per section — shipped v0.8.7-beta

Small button at the right of each settings section header
(Background, Glow, Effects, Widgets): *"Apply to all screens"*.
Copies this screen's section's values to every other screen in
one shot. Quick-config instead of N-times manual setting.

### ✅ Configurator: overview card with mini-thumbnails — shipped v0.8.7-beta

### ✅ Builder: Monitor Wall as primary right-panel nav — shipped v0.9.11-beta

Wall promoted to the top of the right panel; *Apply to Screen N* +
*Multi-monitor split* sections removed (folded into the Wall via
*Use current canvas* on each frame). Frames pre-fill with the
screen's current `bgImage` via the `/image?path=` proxy. Per-frame
click opens a 4-item menu (📁 Choose file, 📚 From library, 🖼️ Use
current canvas, ✕ Clear). Apply Wall re-loads `/config` after
success so frames immediately show the just-applied backgrounds.
Horizontal layout's `nowrap; overflow-x: auto` fix from v0.9.9
carried forward.

### ✅ Builder: ⇔ Span canvas across monitors — shipped v0.9.13-beta

Single button in the Wall toolbar slices the current canvas into
one chunk per monitor (sized proportionally to each screen's
physical width) and stages every frame at once. Closes the merge
→ wall workflow gap: a 7680×2160 canvas built from two photos
can now go onto a 2 × 2560×1440 wall in one click instead of
manual per-frame cropping. Hint under the wall canvas lights up
whenever the canvas's aspect ratio is within 5 % of the wall's
combined aspect so the shortcut is discoverable. Shipped alongside
a tray *Reload wallpaper pages* command for future hot-reload of
the wallpaper JS without re-import.

### ✅ Builder: right-panel rework (Source → Wall → Output) — shipped v0.9.14-beta

Section order corrected so the user's natural flow (load /
merge first, then push to the wall) maps to top-to-bottom panel
scrolling. Two-image / 2×2 merge controls collapsed into a
`<details>` since the single-image happy path doesn't need
four file-pick slots in view. *Wand anwenden* promoted to a
full-width primary button with Span / Clear in a secondary row;
*Clear* now disables itself when nothing is staged. Staged-ready
hint replaces the *try Span* banner the moment any slot fills, so
the UI no longer suggests an action the user has just performed.

A new card at the top of the Configurator, above the tab bar:
horizontal row of N small monitor-frame thumbnails (matching the
screen count), each showing the current background image of its
screen. Click a thumbnail → jumps to that Screen's tab. Visual
overview of which monitor shows what, without having to flip
through tabs.

### ✅ Builder: Ctrl + Wheel zoom — shipped (pre-0.8.3-beta)

Already implemented in `builder.html` — `canvasArea` listens for
`wheel` events and zooms in/out by 1.1× when `ctrlKey` is held.

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

### ✅ Setup health check in the tray — shipped v0.8.9-beta

Tray entry *System status…* opens a Tk dialog with five rows:
SignalRGB plugin file present, SignalRGB.exe running, bridge port
reachable, wallpaper pages connected, LHM reachable (only if a
Hardware-sensor widget exists). Each red row offers a contextual
Fix button: open plugins folder, download SignalRGB, open Help,
download LHM.

### ✅ Backup + restore config — shipped v0.8.9-beta

*Export everything…* in the Configurator (new *Backup & Restore*
card) downloads a `signalrgb-wallpaper-backup-<timestamp>.zip` via
`GET /backup` — contains `config.json` + the full `library/` and
`screens/` dirs. *Restore from ZIP…* uploads to `POST /restore`;
bridge swaps in the config, merges library/screens files on top of
the live dirs (won't nuke unmatched local files), rebuilds the
library catalogue, and pushes new settings to every screen.
`help_images/` not yet included since users don't customise it.

### ✅ Reset + undo — shipped v0.8.9-beta + v0.9.10-beta

*Reset this screen to defaults* button in the mirror bar
(v0.8.9-beta). **Ctrl+Z undo** + **Ctrl+Y / Ctrl+Shift+Z redo**
across the last 20 setting changes per screen
(v0.9.10-beta) — per-screen ring buffer, captured in `setSetting`
before each write. Manual edits invalidate the redo stack
(linear-history model). Doesn't cover widgets / presets /
mirror / cycle, which have their own scoped flows.

### ✅ First-run onboarding tour — shipped v0.9.10-beta

Configurator-side overlay that fires on first WS settings push when
`signalrgb.tour_seen` isn't set in `localStorage`. Seven steps
(Welcome → Tabs → Overview → Background → Presets → Builder →
Done), each with a spotlight ring + floating tooltip on the live
DOM element. Skip / Esc / overlay click dismiss; *Tour* button in
the header replays it on demand. Tier 1 complete.

---

## ✨ Tier 2 — High-visibility user features

These are the features that get screenshotted and shared. Higher
ratio of "wow factor" to implementation effort.

### ✅ Wallpaper shuffle / cycle — shipped v0.9.2-beta

Per-screen *Auto-cycle* block inside the Background card.
Configurable: enable, interval (1-720 min), pool (all library /
pinned only), order (sequential / random). `CycleScheduler`
background thread runs a 30 s tick; mirror screens are skipped
since the source's cycle propagates to them via the existing
mirror-replication path. Time-of-day pool (dawn / day / dusk /
night) deferred to a follow-up.

### ✅ Preset hotkeys — shipped v0.9.3-beta

Global `Ctrl+Shift+1..4` applies preset slot N on every active
screen. `HotkeyListener` runs on its own thread, uses
`RegisterHotKey` for each hotkey and a GetMessage loop for
dispatch. Tray toggle under Advanced flips
`config.presetHotkeysEnabled`; off by default so we don't grab
shortcuts the user might already be using.

### ✅ Per-app / per-game profiles — shipped v0.9.5-beta

`ProfileWatcher` polls foreground at 1 Hz via
`GetForegroundWindow → QueryFullProcessImageNameW`, matches basename
against `config.profiles` rules (case-insensitive), and applies the
rule's preset slot to the chosen screen(s). Snapshots prior state
on activation; reverts to it when the foreground changes away. Only
one rule active at a time. Configurator's *Per-app profiles* card
adds / edits / removes rules; CRUD over new
`profile-add`/`profile-update`/`profile-remove` WS commands.

### ✅ Now-playing widget — shipped v0.9.4-beta

`NowPlayingPoller` reads Windows SMTC via the `winrt-Windows.Media.
Control` package (split-package successor of legacy `winsdk`), runs
on a dedicated asyncio-loop thread, and merges its snapshot into
the existing 1 Hz `sysstats` WS push. Widget rendering on the
wallpaper page shows title + artist + optional progress bar; tints
the bar with the live glow colour when *Tint* is on.

---

## 🛠️ Tier 3 — Power-user / polish

### ✅ Builder: Auto cut tool — shipped v0.9.16-beta

✨ icon in the toolbox. Two modes share the same `clicks` storage
and replay path so undo / redo / refine-with-brushes work like any
other operation:

- **Otsu (instant)** — computes the optimal brightness threshold
  via Otsu's method on a luma histogram. No internet, no model,
  no WASM. Genuinely strong for neon / UI / sci-fi panel imagery
  where the cut signal is brightness.
- **AI saliency** — lazy-loads `onnxruntime-web` from jsDelivr and
  a U²-Netp saliency model from Hugging Face on first click;
  both are browser-cached after. Inference at 320×320, mask
  upsampled at draw time. Total cold-start download ~7 MB.

Threshold slider biases the cutoff ±25 %; Invert toggle flips
the mask. Rotation handler updates the stored mask in place so
*Rotate 90°* keeps the cut aligned with the canvas. Model URL
override via `localStorage["builder.aiModelUrl"]` for users
behind a CDN block.

### 🚧 Winget package + auto-update — auto-update shipped v0.9.8-beta

In-app auto-update flow is done: tray entry *"⬇ Download + install
{tag}"* streams the installer into `%TEMP%`, spawns it with
`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`, then `os._exit(0)`s so
the installer can replace `SignalRGBBridge.exe`. Installer's `[Run]`
entry now auto-restarts the bridge in silent mode. Progress shown
via a small Tk window during download.

Still 🔲: Winget manifest submission to `microsoft/winget-pkgs` —
needs a PR through their submission flow + ongoing manifest
updates per release. Left as a manual task for the maintainer
when there's audience for it.

### 🅿️ Mobile Configurator view — parked

Removed from the roadmap: niche use case, would need the bridge
to bind to 0.0.0.0 with a "this exposes your wallpaper config
to the LAN" opt-in, and most users sit at the PC the wallpaper
runs on anyway.

### 🅿️ Community wallpaper gallery — parked

Removed from the roadmap: high copyright-infringement risk
(unfiltered user uploads of brand IP, anime stills, game art,
etc.) — moderating a public submission flow would dwarf the
useful curation work. The bundled starter library + per-user
upload remain the supported path.

### 🚧 Ambient effects: port MIT-licensed CodePen pens — first batch v0.9.12-beta

v0.9.12-beta added **Constellation** + **Fireflies** ambient presets,
written from scratch in the project's own `AMBIENT_PRESETS` shape so
no per-pen licence verification was needed. Renderer learned an
optional `def.after(ctx, particles, tint)` post-pass hook for
effects that draw across the whole particle set (used by
Constellation's connecting lines).

Further direct ports from individual CodePen pens still pending —

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
