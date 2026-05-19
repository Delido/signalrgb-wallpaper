# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0-beta] - 2026-05-19

> Prerelease. The three-phase effects roadmap landed in one drop,
> plus a brand-new in-browser configurator. Tray → **Updates** →
> **Allow beta versions** to opt in.

### 🎛️ Added — In-browser configurator

New page at `http://127.0.0.1:17320/configurator`, opened by the
tray's primary **Configurator…** action. Replaces the per-screen
Widgets / Effects right-click submenus (which had become an
unusable maze of radio submenus) with a single tabbed UI:

- **Per-screen tabs** at the top, one WebSocket per active tab.
- **Background section** — image path field, file-picker (re-uses
  the builder's PNG-via-canvas upload to the bridge's existing
  `POST /screen/N/background` endpoint), Fit dropdown, Dim slider.
- **Glow section** — layout dropdown, strength / grid-blur /
  stripes-blur sliders, show-bars toggle.
- **Effects section** — five **live mini-canvas tiles** for the
  ambient presets (snow / rain / sparks / aurora actually animate
  inside the tile so you see what each preset looks like before
  applying), tint toggle, density slider, pixelfx segmented
  buttons.
- **Widgets section** — list of all placed widgets per screen with
  icon + label + short description; **Configure** opens a real
  form-based modal (no more `prompt()` chains) built from a
  per-type option schema; Remove button per row; an "Add"
  picker-grid with all registered widget types.
- New WebSocket command `setting-update` so the page can drive
  any non-widget per-screen setting. Server-side whitelisted to
  prevent random config keys from being mutated.

Tray menu was simplified to: **Configurator…** (default click) ·
**Build Wallpaper…** · **Advanced** submenu (legacy Settings,
quick-add widget / effect submenus, reload config) · **Updates** ·
**About** · **Quit**.

### 🎆 Added — Ambient effects (Phase 2)

Four full-canvas particle presets that run behind the widgets:

- **Snow** — soft drifting flakes with sideways wobble
- **Rain** — diagonal lines, density-driven
- **Sparks** — warm hot-core embers floating up
- **Aurora** — large soft hue-shifting blobs drifting across the screen

Hand-rolled canvas engine (no extra JS dependency — the existing
`interact.js` is enough). All four presets honour an opt-in
**"Tint particles with glow colour"** toggle that pulls the
already-computed glow average and recolours the particles.

Tray → **Effects** → **Screen N** → pick the preset (radio), toggle
tint, and adjust density (1..100; defaults to 60). Live-pushed —
toggling visibly changes the wallpaper without reconnecting anything.

### 📊 Added — System-stat widgets (Phase 3)

Four new widget types appended to the registry:

- **CPU meter** — current %, plus a 120-second sparkline
- **RAM meter** — same shape for memory pressure
- **Network graph** — current ↓ / ↑ rates (human-formatted B/s · KB/s ·
  MB/s) over a dual-line chart, auto-scaled to the rolling max
- **Audio spectrum** — bar visualizer driven by Lively's
  `livelyAudioListener` (and Wallpaper Engine's
  `wallpaperRegisterAudioListener`). 64-bar FFT, scales with widget
  size; falls back to *"waiting for audio…"* when nothing is playing

CPU / RAM / Net stats come from a new `SysStatsPoller` thread in the
bridge — uses `psutil` (BSD-3-Clause, bundled into the PyInstaller
exe via `--collect-all psutil`), polls at 1 Hz, pushes a single
WebSocket frame `{type:"sysstats", data:{cpu, ram, netDown, netUp,
uptime, ts}}` to every connected wallpaper. The bridge gracefully
no-ops if `psutil` is missing at import time (dev `python bridge.py`
on a box without the module still boots; widgets render "n/a").

Audio doesn't need a bridge hop — Lively / WE inject FFT directly
into the wallpaper page.

### ✨ Added — Pixelfx (Phase 4)

Cursor-following eye-candy on its own canvas layer above the widgets:

- **Mouse trail** — a fading line of tinted dots
- **Hover glow** — a soft radial gradient that follows the cursor
- **Click ripple** — concentric circle on each click
- **All** — combine the three

Position arrives via Lively's `livelyCurrentCursorPos(x, y)` callback,
so trail + glow work under click-through too. Ripples need real
clicks, which means Lively / WE wallpaper-interaction has to be
enabled — flagged in the tray menu entry's label.

### Added — Tray plumbing

- **Effects** submenu with per-screen radio lists for ambient preset
  and pixelfx mode + tint toggle. Auto-generated from
  `AMBIENT_PRESETS_TRAY` / `PIXELFX_MODES_TRAY` constants, so adding
  another preset later is one tuple in each list.

### Removed

- **Network widget** pulled from this release after testing — the
  dual-line chart layout needed more work and the rate readings were
  flaky on some Windows network-interface combos. The bridge still
  pushes `netDown` / `netUp` in the sysstats frame, so a future
  iteration can bring the widget back without a protocol change.

### Changed

- About dialog now credits `psutil` (BSD-3-Clause).
- New top-level per-screen settings: `ambientEffect`, `ambientTint`,
  `ambientDensity`, `pixelfx`. Backfilled on existing configs.

## [0.5.3-beta] - 2026-05-19

> Prerelease. Hotfix release for the v0.5.2-beta installer.

### Fixed

- **Wallpaper Engine bundles were not actually copied into Steam**
  when the WE task was selected. The Inno Setup file entries for the
  Steam-side copy carried an `external skipifsourcedoesntexist` flag
  that I'd added without thinking. `external` in Inno Setup means
  *"look for this file at install-time at the source path"* — i.e.
  the file isn't bundled in the installer at all and was expected
  to magically exist on the user's disk. Dropped both flags so the
  bundles are now actually packed into the installer and the
  `{code:GetWallpaperEngineProjects}` destination receives them.

### Changed

- **Installer wallpaper-host selection is now explicit.** Both Lively
  and Wallpaper Engine are opt-in tasks grouped under a single
  *"Wallpaper host:"* heading on the Tasks page. Lively stays checked
  by default; Wallpaper Engine stays unchecked.
- **Every follow-up action is gated on the chosen host:**
  - Lively zips are only copied to `{InstallDir}\Lively wallpapers\`
    if the Lively task is checked.
  - WE bundles are only copied to `{InstallDir}\Wallpaper Engine
    wallpapers\` (and the Steam-side projects folder, when detected)
    if the WE task is checked.
  - Start-menu shortcuts for each wallpaper folder only show for the
    selected host(s).
  - The end-of-install "Open folder" prompts only show for the
    selected host(s) — a Lively-only user never sees a Wallpaper
    Engine prompt and vice versa.
- **Smarter post-install prompt for WE users.** If Steam +
  Wallpaper Engine were detected, the prompt now opens *Steam's*
  WE projects folder (where the bundles actually live, ready to
  assign in WE → My Wallpapers). If WE wasn't detected, it falls
  back to the local staging folder under `{InstallDir}` so the user
  can drag the folders into WE manually. Different wording in each
  case so the user knows what they're looking at.

## [0.5.2-beta] - 2026-05-19

> Prerelease. Tray → **Updates** → **Allow beta versions** to receive
> notifications about further beta drops; stable users are unaffected.

### Added

- **Wallpaper Engine support.** The wallpaper bundles are now produced
  in two formats during build: the existing Lively `.zip` files **and**
  a Wallpaper Engine `Web` project folder per screen (with a
  `project.json` manifest). The page-side HTML already had Wallpaper
  Engine's `wallpaperPropertyListener` shim, so no runtime changes were
  needed — only packaging.
- **Installer integration**. New opt-in task **"Install for Wallpaper
  Engine"** (unchecked by default).
  - When checked **and** a Wallpaper Engine install is detected, the
    three bundles get copied straight into Steam's
    `…\steamapps\common\wallpaper_engine\projects\myprojects\` —
    after install you'll find them in Wallpaper Engine's *My
    wallpapers* tab, ready to assign per monitor.
  - When unchecked or Wallpaper Engine isn't detected, the bundles
    still land under `{InstallDir}\Wallpaper Engine wallpapers\` so
    you can drop them in by hand later.
  - Steam install is detected via `HKCU\Software\Valve\Steam` →
    `SteamPath`. Off-drive Steam libraries are picked up by parsing
    `libraryfolders.vdf`, so Wallpaper Engine on a secondary drive
    still works.
- **Uninstall cleanup** removes the three Steam-side bundle folders
  it placed (leaves any other Wallpaper Engine wallpapers alone).
- A new Start-menu shortcut for the `Wallpaper Engine wallpapers`
  folder, mirroring the existing Lively one.

### Notes

- This release adds Wallpaper Engine support *alongside* Lively, not
  instead of it. Lively remains the recommended free host; Wallpaper
  Engine is a paid Steam app (~€4) and only kicks in if you already
  own it.
- If the widget weather / quote fail to load inside Wallpaper Engine:
  enable internet access for the wallpaper in Wallpaper Engine's
  *Browser* settings (WE's CEF blocks outgoing requests by default
  for some users; Lively is more permissive).

## [0.5.1-beta] - 2026-05-19

> Marked as a prerelease on GitHub. Stable users won't be auto-notified
> about this build; toggle **Allow beta versions** in the tray's Updates
> submenu to opt in.

### 🚀 Performance

- **GPU load on the grid layout: ~20 % → ~3 %.** A real measurement on
  the v0.5.0 → v0.5.1 jump, ≈ 85 % reduction. The big win was killing
  the `transition: background 0.08s linear` on individual grid zones
  — at 60 fps the bridge already delivers smoother colour changes than
  the tween could, and the compositor was juggling hundreds of in-flight
  animations every frame. Also: per-zone style writes go through
  `style.background` directly instead of `style.setProperty("--c", …)`,
  and grid zones got `contain: strict` so style recalcs don't ripple
  out of their cell. Stripes / pills layouts are unchanged (few enough
  zones that the original transitions don't show up in the profile).

### Added

- **In-app update checker** in the tray. Polls
  `https://api.github.com/repos/Delido/signalrgb-wallpaper/releases`
  on startup (after a 12 s settle) and once a day thereafter. When a
  newer release is published, the tray shows a balloon notification
  and an `⬆ Update available: vX.Y.Z — open release page` entry
  appears at the top of the tray menu. Click → release page in your
  default browser; download + run the new installer yourself (no
  unattended auto-update — keeps antivirus quiet, gives you the choice).
- **Updates submenu** in the tray:
  - **Check for updates now** — manual trigger.
  - **Enable update checks** — master switch (default on).
  - **Allow beta versions** — include GitHub prereleases in the
    comparison (default off). Toggling triggers an immediate re-check
    so you see the new candidate without waiting.
  - Status line: *"Up to date — last checked …"*, *"Last check failed: …"*
    or *"Not yet checked"*. Plus an *"Installed: vX.Y.Z"* line.
- Semver-aware version comparison (`MAJOR.MINOR.PATCH` plus optional
  `-prerelease` suffix). Prereleases sort *before* the matching stable
  per semver, so `0.5.1-beta < 0.5.1` — stable users won't be nagged
  about betas.
- Two new top-level config keys: `updateCheckEnabled` (default `true`)
  and `allowBetas` (default `false`). Backfilled on existing configs.

- **Four more widget types** (continuing the 0.5 series):
  **Sticky note** (double-click in edit mode to type inline; four
  colour variants), **Countdown** (target date + label, smart unit
  pick), **Picture frame** (URL or local path, three fit modes,
  optional rounded corners), **Quote of the day** (fetched daily
  from [Quotable](https://quotable.io/), CC BY-SA — attribution in
  the widget footer).
- **In-page widget picker** — floating card at the bottom of the
  wallpaper in edit mode; lists every registered widget type as an
  icon button. Generated from the same registry the renderers use.
- **Per-widget options editor** — each widget that takes settings
  shows a ⚙ button in edit mode (next to the ×). Prompt-driven config
  for clock style, calendar week start, weather location/units, note
  colour, countdown target/label, picture URL/fit.
- **Extensible widget registry** in `wallpaper/index.html` — one map
  with `{label, icon, markup, mount?, tick, editOptions?}` per type.
  Adding a widget = one entry here + one default in `bridge.py`'s
  `WIDGET_DEFAULTS`. Tray "Add…" submenu and the in-page picker both
  auto-iterate.

### Changed

- **Bridge tray "Widgets" submenu** generated from `WIDGET_DEFAULTS`
  instead of hard-coded `clock / calendar / weather` entries.
- **Edit-mode banner replaced by the picker**, which carries the
  bedienanleitung too ("drag · resize · ⚙ configure · × remove · lock
  in tray").
- **Drag-from-button filter** — `interact.js` ignores drags that
  start on the gear / × buttons or inside a `[contenteditable="true"]`
  region, so typing inside a sticky note doesn't move the widget.

## [0.5.0] - 2026-05-19

### Added

- **Placeable widgets on the wallpaper.** First slice of the v0.5
  widgets roadmap. Three built-in types ship in this release:
  - **Clock** — analog (SVG, 12 ticks, smooth-sweep seconds) or
    digital (HH:MM:SS + long weekday/date), 24 h or 12 h.
  - **Calendar** — current month grid, today highlighted, week-start
    configurable (Mon / Sun).
  - **Weather** — fetched from [Open-Meteo](https://open-meteo.com/)
    (free, no API key). Temperature, condition (WMO code → label),
    "updated N min ago" footer. Defaults to Berlin; per-instance
    lat/lon configurable.
- **Drag-and-resize widget editor on the live wallpaper.** Tray menu
  gains a per-screen **Widgets** submenu: pick "Edit widgets on this
  screen" to enter edit mode (handles + delete buttons appear, banner
  tells you what to do), pick again to lock. Add widgets via "Add
  clock / calendar / weather" — they spawn at default positions and
  immediately unlock edit mode so you can place them. Drag-and-resize
  uses [interact.js](https://github.com/taye/interact.js) 1.10 (MIT),
  bundled into the Lively zip — no CDN dependency at runtime.
- **Glow-tinted widgets** (opt-in per widget via `options.tintFromGlow`).
  When enabled, the widget picks up an average of the current
  SignalRGB glow colours and applies it through a `--w-tint` CSS
  variable (analog seconds hand, digital time, today-cell highlight,
  temperature). Off by default.
- **Two-way WebSocket protocol.** The bridge now decodes masked
  text frames from the wallpaper page and routes the four widget
  mutation commands (`widget-add`, `widget-remove`, `widget-update`,
  `widgets-lock`) into a thread-safe `BridgeRuntime` API that mutates
  `settings.json` and re-broadcasts. Same pipe used today for
  settings push from bridge → page; just opens the return direction.
- New per-screen settings fields:
  - `widgets`: array of `{id, type, x, y, w, h, options}` entries.
  - `widgetsLocked`: `True` (default) or `False`. Drag/resize is
    disabled while locked; the wallpaper renders widgets read-only.

### Changed

- `Broadcaster.__init__` takes a new `on_widget_command` callback that
  forwards parsed widget commands to the runtime; the constructor
  signature change is internal but worth noting if you embedded the
  bridge.

## [0.4.5] - 2026-05-18

### Changed

- **Builder UI restructured GIMP-style.** The single-sidebar wall of
  controls is replaced by a four-column layout: a vertical icon toolbox
  on the left (inline-SVG buttons for each of the 6 tools), a Tool
  Options panel that shows only the sliders/hints relevant to the
  currently active tool, the canvas in the centre, and a dedicated
  Files panel on the right with Load / Merge / Output / Apply /
  Multi-monitor-split sections. Active tool is highlighted; switching
  tools also updates the panel title and the visible option group.
- Dead `.radio-list` CSS removed, plus a few orphan styles from the
  old layout.

### Added

- **Live brush cursor.** While the Restore brush is active the
  canvas shows a circle (or square) outline that follows the pointer,
  sized to `2 * brushSize * zoom` in CSS pixels — so what you see is
  the area a click would actually affect. An inner dashed ring marks
  the hard-core radius at the current Hardness setting.
- **Brush hardness slider (0–100).** 100 = fully hard edge (legacy
  behaviour); lower values fade the alpha linearly from the hard-core
  radius out to the outer radius. Overlapping stamps within a stroke
  max-merge their alpha so soft edges don't punch holes in each
  other.
- **Brush shape selector (Round / Square).** Segmented buttons in the
  brush options; square brush uses Chebyshev (max-axis) distance for
  the same falloff model. Both shapes survive a 90° rotate.
- **Erase brush.** Seventh tool — opposite of the Restore brush. Drives
  pixel alpha *down* toward zero with the same size / hardness / shape
  controls (shared with Restore). Soft edges use min-merge so a hard
  centre stays fully transparent even if later overlapping soft stamps
  would otherwise ramp it back up. Live cursor and history rendering
  match the Restore brush.
- **Drag-and-drop on the Merge slots.** Both image-A and image-B
  pickers now accept a dropped image with a visual hover state,
  matching the canvas's existing DnD.
- **Full Undo / Redo history.** New Redo button next to Undo; any
  fresh edit clears the redo stack so we can't resurrect stale
  operations after the user branches off. Keyboard shortcuts:
  Ctrl+Z for undo, Ctrl+Y or Ctrl+Shift+Z for redo. The Reset-edits
  button now stacks everything onto the redo pile, so even Reset is
  undoable.

## [0.4.4] - 2026-05-18

### Added

- **Merge two images side-by-side in the builder.** New block under
  Step 1 with two file slots ("Pick image A…", "Pick image B…") plus a
  "Force 50/50" toggle. The default mode matches heights and keeps both
  aspect ratios (output width = sum of scaled widths); 50/50 stretches
  each half to equal width — perfect input for the existing multi-monitor
  vertical split. The merged canvas runs through the same
  edit / save / apply / split pipeline as a single loaded image, so all
  tools (polygon, ellipse, restore brush, etc.) work on it unchanged.

### Changed

- Internal: `loadFile()` refactored to a small `fileToImage()` Promise
  helper + a shared `applySourceImage(name, source)` entry point. Both
  the single-image picker and the new merge button funnel through the
  same code, which is also where future "open from URL / clipboard"
  sources would slot in cleanly.

## [0.4.3] - 2026-05-18

### Fixed

- **Settings dialog buttons no longer disappear off the bottom of the
  window.** Save / Close are now in a sticky bottom bar packed before
  the notebook (`side="bottom"` first), so they remain anchored no
  matter how the window is resized or how many sliders are visible on
  a tab.

### Changed

- **Settings dialog UX overhaul.** Each setting now has a bold label,
  the control, and a short help-text paragraph underneath explaining
  what the knob actually does. The tab content is wrapped in a
  scrollable canvas (mouse-wheel works while the pointer is over it),
  so the per-screen panel fits any window size cleanly. Default window
  size bumped to 740×720, resizable down to 620×540.
- Global "SignalRGB device count" and "Auto-pause" sections each got
  the same help-text treatment so it's obvious what each does.

### Added (docs)

- README **Gallery** section now shows four real screenshots: the
  in-browser builder, the Lively library with branded tiles, the
  SignalRGB device list, and the SignalRGB device-settings page.

## [0.4.2] - 2026-05-18

### Added

- **Auto-pause on fullscreen** — the bridge now polls Windows once a
  second via `GetForegroundWindow` + `GetMonitorInfo` and broadcasts a
  `{"type":"paused",...}` WS frame to all wallpaper pages when a
  fullscreen app (game, video player, RDP session, anything covering
  its entire monitor) becomes / leaves the foreground. The wallpaper
  pages flip into paused state — red "⏸ PAUSED" badge top-right, and
  `renderFrame()` short-circuits, so the glow freezes on its last
  drawn colours. As a bonus the bridge also stops forwarding the
  per-frame UDP→WS binary broadcasts while paused (SignalRGB plugin
  keeps sending, bridge just absorbs — saves a bit of CPU during long
  gaming sessions).
- **Tray Settings → Auto-pause** section with a checkbox **"Pause glow
  when a fullscreen application is active"**. Default on; toggle off
  and the bridge ignores fullscreen state changes.
- **`SignalRGB_LivelyPauseTester.zip`** — diagnostic wallpaper. Big
  PLAYING/PAUSED screen with a panel showing three independent
  detection paths (Lively's `livelyWallpaperPlaybackChanged` JS hook,
  HTML `visibilitychange`, and a `requestAnimationFrame` tick-rate
  probe). Useful to verify your Lively build pauses Web wallpapers at
  all before filing an issue.
- **Lively tile thumbnail** — `wallpaper_bridge/wallpaper/thumbnail.png`
  generated by `installer/generate_thumbnail.py`, referenced from
  `LivelyInfo.json` so the Library tile is branded instead of plain
  black.
- **rAF tick-rate probe** in the wallpaper HTML as a defensive
  fallback that catches OS-level rendering pause when neither Lively's
  JS hook nor `visibilitychange` fire.

### Changed

- **`LivelyInfo.json`**: `Arguments` is now `null` (was
  `"--pause-event true"`). The hook was unreliable across Lively builds
  and the auto-pause is owned by the bridge now anyway.
- `build.ps1` regenerates the thumbnail + packages a separate
  `SignalRGB_LivelyPauseTester.zip` artefact in addition to the three
  per-screen zips.

## [0.4.1] - 2026-05-17

### Added

- **Restore brush** tool in the wallpaper builder. New "Restore brush"
  radio in the tool list; "Brush size" slider (3–120 px, default 20).
  Click+drag over a transparent area to paint the original pixels back
  to opaque. The stroke previews live as you drag — the brushed
  pixels' alpha gets restored from the pristine ImageData immediately,
  no wait for the full mask recompute. On mouseup the whole stroke is
  committed as a single `restore` history entry, undoable as one
  operation.

### Fixed

- Wallpaper builder: when zoomed in beyond viewport size, the canvas
  area now actually scrolls. Was caused by a chain of default
  `min-{width,height}: auto` on the grid/flex layout that let the
  canvas expand its parents instead of triggering `overflow: auto`
  scrollbars. Fixed by adding `min-width: 0` to the canvas-area grid
  cell and `flex: 0 0 auto` to scroll children — both standard
  Chromium workarounds.

### Changed

- `applyMask` rewritten to be **order-sensitive** per-pixel (was
  bucketed-by-kind). This is what makes the restore brush compose
  correctly with subsequent removals: remove → restore → remove-again
  works because clicks are processed in order, with restore setting
  alpha back to the original and a later removal still able to clear
  it. The previous bucketed pass would have applied restore as a
  final override regardless of position. Same big-O complexity; tiny
  bit more per-pixel work for edits with many history entries.
- Rotation rotates restore-stroke coordinates the same way it rotates
  region / polygon / ellipse coords, so the brush survives a 90° turn.

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
