# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-05-17

### Added

- **Inno Setup installer** (`SignalRGBWallpaperSetup-0.4.0.exe`,
  ~21 MB). Per-user install (no admin), copies the bridge to
  `%LOCALAPPDATA%\Programs\SignalRGBWallpaper\`, optionally installs the
  SignalRGB plugin into `Documents\WhirlwindFX\Plugins\`, drops the
  three Lively wallpaper zips in a subfolder, registers an HKCU\Run
  autostart entry, and creates an Add/Remove Programs uninstaller.
  Two opt-in tasks: "Start bridge automatically on logon" and "Install
  the SignalRGB plugin into the WhirlwindFX Plugins folder". Build via
  `installer/build.ps1` (one-shot icon + exe + zips + Inno Setup
  compile). See [docs/building-from-source.md](docs/building-from-source.md)
  for the manual build path.
- **Builder: polygon tool.** New "Polygon" radio in the tool list.
  Click corners on the canvas to build the polygon outline; drag any
  corner handle to reshape; right-click a corner to delete it (with at
  least 3 corners remaining); drag the polygon body to translate the
  whole shape. Confirm/Cancel toolbar floats at the top-right of the
  canvas (fixed positioning so it's always reachable). Enter confirms,
  Esc cancels.
- **Builder: ellipse tool.** New "Ellipse" radio. Drag a bounding-box
  rectangle to lay out an axis-aligned ellipse; four N/E/S/W handles
  let you resize independently; drag the ellipse body to translate it.
  Confirm/Cancel as for polygon.
- **Builder: "Click in region" tool.** Drag a rectangle to set a
  yellow-dashed region of interest. Subsequent clicks inside that
  region pick a colour AND restrict its colour-match to within the
  region — useful for "remove this colour but only on this part of the
  image". The region persists across clicks until you drag a new one,
  switch tools, or change images.
- **About dialog now shows OSS attribution**: Python (PSF), Python
  stdlib, pystray (LGPL 3.0), Pillow (MIT-CMU/HPND), PyInstaller
  (GPL 2.0+ with linking exception), tkinter, plus an explicit note
  that `builder.html` is vanilla HTML5/JS with no third-party
  libraries. Build tooling (gh CLI, git, winget, Inno Setup) listed
  separately as not-shipped.

### Changed

- Builder shape-toolbar is now `position: fixed` (top-right, 60 px
  below page header) so Confirm/Cancel never slips off-screen.
- `applyMask` extended to handle four shape kinds (color, region,
  polygon, ellipse) and an optional `region` constraint on color
  entries. Single-pass per pixel; region-restricted color entries
  short-circuit when out of bounds.
- Rotation now rotates polygon/ellipse coordinates and
  region-restricted color clicks by 90° CW so masks stay in place
  relative to the rotated image. In-progress shape edits are
  cancelled on rotate (their coords would be in stale orientation).
- Tool change clears the bounded region overlay so it doesn't linger
  after switching to a non-bounded tool.

## [0.3.0] - 2026-05-17

### Added

- **In-browser wallpaper builder.** New tray menu item **"Build
  Wallpaper…"** opens an HTML5-canvas image editor at
  `http://127.0.0.1:17320/builder` in the user's default browser. Pure
  client-side editor, no extra install needed. Features:
  - Drag-and-drop or file picker to load PNG / JPEG / WebP / GIF / BMP.
  - **Two tools**: "Click pixel" (removes globally-similar colours) and
    "Drag rectangle" (removes a region you select).
  - **Tolerance slider** (0–200) tunes the colour-match width; tweaking
    after a click live-updates the most recent match.
  - **Soften edges** option adds a 2 px feathered rim around transparent
    cut-outs so they don't look pixelated under the CSS blur.
  - **Undo / Reset** for non-destructive iteration (the pristine
    original is kept in memory).
  - **Rotate 90°** for portrait/landscape mismatches; click history
    survives.
  - **Zoom** controls (− / + / Fit / 100%) and Ctrl+wheel.
  - **Output size cap** (default 4K) so saved PNGs don't run to 50 MB+
    on 8K source images.
  - **Save as PNG** downloads via the browser.
  - **Apply directly to Screen 1 / 2 / 3** buttons POST the current
    image to the bridge — wallpaper updates live, no Settings dialog
    round-trip.
  - **Multi-monitor split**: cut the image vertically in half and apply
    the two halves to two screens at once. Optional yellow split-guide
    overlay on the canvas.
  - Toast notifications confirm save / apply success or failure.
  - See [docs/building-wallpapers.md](docs/building-wallpapers.md#built-in-builder-the-quick-path)
    for the workflow.
- **`POST /screen/<N>/background`** bridge endpoint accepts a PNG body,
  writes it to
  `%LOCALAPPDATA%\SignalRGBWallpaper\screens\screen-<N>-<millis>.png`,
  updates the screen's config to point at it, persists `config.json`,
  and pushes the new settings to connected wallpapers. Unique-timestamp
  filename avoids browser-cache hits on rapid re-uploads; older
  `screen-<N>-*.png` files are auto-cleaned.
- **`GET /builder`** route serves the bundled `builder.html` (added via
  PyInstaller `--add-data "builder.html;."`).
- **"About…"** tray menu item opens a dialog with version, repo link,
  MIT license link, and full open-source attribution: Python (PSF),
  pystray (LGPL 3.0), Pillow (MIT-CMU/HPND), PyInstaller (GPL 2.0+ with
  linking exception), tkinter (PSF), plus reference notes for Lively
  Wallpaper (GPL 3.0) and SignalRGB (proprietary, via plugin API).
- Docs: `docs/building-wallpapers.md` now leads with the built-in
  builder as the quick path and reframes the GIMP workflow as the
  full-control alternative. `docs/tray-settings.md` documents the new
  "Build Wallpaper…" menu item.

### Changed

- Build command in `docs/building-from-source.md`: dropped
  `--specpath build_bridge` (broke `--add-data` resolution because
  PyInstaller resolves data paths relative to the spec file's
  directory) and added `--add-data "builder.html;."`. Spec file now
  lands next to `bridge.py`; gitignored.
- `.markdownlint.json`: MD013 now skips code blocks and tables
  (legitimate long lines in PowerShell snippets shouldn't trigger).

## [0.2.3] - 2026-05-17

### Fixed

- Lively pause handler in v0.2.2 mishandled the documented payload. The
  wiki spec is a **JSON-encoded string** like `'{"IsPaused":true}'`
  (note the field name and direction — `IsPaused`, not `IsPlaying` or
  `IsRunning`). The v0.2.2 handler treated raw strings via a regex that
  didn't match and defaulted to "playing", so the pause was never
  applied even when Lively's hook fired. Now we `JSON.parse` strings
  first and read `IsPaused` correctly, with defensive fallbacks for
  other field shapes some Lively builds use.
- Added a permanently-visible **PAUSED badge** in the top-right corner
  of the wallpaper (independent of the "Show debug overlay" toggle) so
  the pause behavior is verifiable.

### Known issue

- **Lively's "Pause wallpapers" tray menu is best-effort** — whether
  the JS hook fires depends on the Lively build, its current
  `WallpaperPlaybackPolicy` state, and IPC delivery to the player
  process. On setups where Lively pauses other wallpapers but not
  ours, the issue is Lively-side (the hook IPC never reaches the
  WebView2 player); on setups where it doesn't pause anything,
  Lively's pause behavior is itself broken in that environment. We
  ship the correct opt-in (`"Arguments": "--pause-event true"`) and a
  correct handler — if your Lively starts firing the hook, our code
  will pick it up.

## [0.2.2] - 2026-05-17

### Fixed

- Wallpaper now respects Lively's "Pause wallpapers" control. The glow
  layer freezes on its last colours when paused and resumes when
  playback is re-enabled. Implemented via Lively's
  `livelyWallpaperPlaybackChanged(state)` JS hook (payload shape varies
  across builds — we accept boolean, `{IsRunning}`, `{playing}`,
  `{isPlaying}` and string variants). Also pauses on
  `document.visibilitychange` as a defensive fallback for hosts that
  hide the page without firing the playback hook.

## [0.2.1] - 2026-05-17

### Changed

- Tray Settings dialog no longer auto-closes after **Save** — the window
  stays open so you can iterate on multiple screens / test live changes
  without re-opening from the tray each time. A "✓ Saved at HH:MM:SS"
  indicator next to the button confirms each save. The bottom button is
  now labeled **Close** (was "Cancel") to match the new behavior; pressing
  it just dismisses the dialog (any unsaved edits since the last Save are
  discarded).

## [0.2.0] - 2026-05-17

First public release.

### Added

- Multi-screen support (1–3 monitors). The SignalRGB plugin announces one
  virtual device per screen; each pulls colours from its own canvas region.
- System tray icon (`SignalRGBBridge.exe`) with a per-screen settings dialog
  (background image picker, layout, glow strength, dim, blur, bar sliders,
  debug overlay toggle). Settings are pushed live to running wallpapers
  over WebSocket — no Lively reload required.
- Bridge-owned screen count: tray combo "Number of screens" controls how
  many devices SignalRGB exposes. The plugin polls the bridge's
  `GET /config` endpoint and removes excess controllers on the fly.
- Pre-baked Lively wallpaper bundles, one per monitor index: each
  hardcodes a screen-index meta tag so it subscribes to the correct
  per-screen UDP stream.
- HTTP image proxy at `/image?path=…` on port 17320 so the wallpaper page
  can load images from absolute filesystem paths despite Lively's CEF
  file:// sandbox.
- Standalone `SignalRGBBridge.exe` (PyInstaller `--onefile --noconsole`,
  ~19 MB, bundles pystray + Pillow + tkinter).

### Wire format

- UDP datagram layout: `[S][R][screen_index u8][width u16 BE][height u16 BE][rgb...]`
- WebSocket subscription: `ws://127.0.0.1:17320/?screen=N`

### Known limitations

- Lively's own "Customise wallpaper" panel is intentionally disabled for
  these wallpapers (no `LivelyProperties.json` shipped). All settings live
  in the bridge's tray dialog. See
  [docs/architecture.md](docs/architecture.md#why-not-lively-properties)
  for the reasoning.
- Lively non-MSIX (GitHub installer) is supported. Lively Microsoft Store
  (MSIX) version cannot load `.exe`-type wallpapers — irrelevant for this
  project (we use Type 1 / Web wallpapers) but worth flagging.
