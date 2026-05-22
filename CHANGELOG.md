# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.2-beta] - 2026-05-22

> First Tier-2 high-visibility feature: **wallpaper auto-cycle**. Each
> screen can rotate through its library on a schedule, picking
> sequentially or randomly from the full library or pinned-only pool.

### Added — Bridge

- **`CycleScheduler`** — single background thread, 30 s tick, walks
  every screen and fires the next library entry through
  `_update_background` when `cycle.enabled` is true and at least
  `intervalMin` minutes have passed since the last apply.
- **Mirror-aware** — mirrors are skipped explicitly so the source's
  cycle drives them through the existing
  `_replicate_to_mirrors` path; the mirror doesn't get its own
  scheduler tick.
- **Persistent bookkeeping** — `cycle.lastApplyMs` and `cycle.nextIdx`
  live inside the config and survive a bridge restart, so the
  rotation picks up where it left off.
- **Partial-merge update path** — `_update_cycle` merges incoming
  config changes onto the existing cycle dict so the
  configurator can send just `enabled` or `intervalMin` without
  zeroing the scheduler's pointers. Pool / order values are
  whitelisted.

### Added — Configurator

- **Auto-cycle block** at the bottom of the Background card:
  - Enable checkbox
  - Interval (1-720 min)
  - Pool — *All library* or *Pinned only*
  - Order — *Sequential* or *Random*
  - Hint line that counts down "Next change in {n} min" between
    settings pushes (re-painted every 30 s without a full
    settings roundtrip)
- Cycle settings are **not mirrored** — every mirror still picks up
  whichever wallpaper the source's cycle chose, since the resulting
  `bgImage` replicates through the normal mirror path.

## [0.9.1-beta] - 2026-05-22

> Monitor Wall gains a **Free-form** layout option — drag each monitor
> frame to any position on a workspace, so non-standard setups
> (e.g. one portrait monitor between two landscapes, L-shape, etc.)
> can be arranged visually before applying.

### Added — Builder

- **Free-form Monitor Wall layout.** New option in the layout
  dropdown next to *Horizontal row*, *2×2 grid*, *Vertical column*.
  - Frames sit on a fixed-height workspace with a subtle 20 px grid
    background so positions feel deliberate.
  - Mouse-down on a frame → drag to reposition. Frames are clamped
    inside the workspace so they can't drift off the edge.
  - Drag is differentiated from click: small movements still open
    the file picker (no false positives), real drags suppress the
    click for 100 ms after release.
  - **Positions persist in `localStorage`** keyed by screen count so
    a layout for 2 monitors survives switching temporarily to 3 and
    back.
  - New **Reset positions** button (visible only in free-form mode)
    wipes the saved layout and re-fans to a default horizontal
    arrangement.

## [0.9.0-beta] - 2026-05-22

> Builder gains a **Monitor Wall** section: visual layout of every
> connected screen with per-tile image picker and a single
> *Apply Wall* batch upload. Generalises the per-screen Apply
> buttons + Split tools into one workflow that matches how users
> actually think about multi-monitor wallpapers.

### Added — Builder

- **Monitor Wall section** (right panel, below *Multi-monitor split*).
  - **Layout dropdown**: *Horizontal row (1×N)*, *2×2 grid*, *Vertical
    column (N×1)*. Slot count derives from the live `screenCount`
    in `/config`.
  - **Frame aspect ratios** use each screen's reported `viewportW/H`
    so an ultrawide tile actually renders ultrawide. Falls back to
    16:9 when no wallpaper page has connected to that screen yet.
  - **Per-frame image pickers**: drop a file on a frame, click the
    frame to pick from disk, or hit the *Library* hover-action to
    pull from the Configurator library — same dialog the existing
    *Open from library…* button uses.
  - **Apply Wall** batch-uploads each loaded slot to its matching
    screen via the existing `POST /screen/<N>/background` endpoint.
    Empty slots skip — lets the user push only the screens they
    care about. Re-encodes through canvas → PNG so JPEG/WebP
    inputs land in a consistent format.
  - **Clear** resets every slot in one click.
  - Layout / viewport state is re-polled every 10 s, so changing
    screen count or monitor resolution updates the Wall section
    without a reload.

## [0.8.10-beta] - 2026-05-22

> Two fixes against the v0.8.9-beta System-status dialog: plugin
> file not found on OneDrive-redirected Documents folders, and the
> Configurator's own WS tab inflating the "connected pages" count.

### Fixed

- **System status: SignalRGB plugin file shown as missing** even
  though the installer dropped it correctly. On Windows installs
  with OneDrive Documents redirection, `Path.home() / "Documents"`
  resolves to an empty/legacy folder while Inno Setup's
  `{userdocs}` token routes through `SHGetFolderPath` and writes
  to the actual OneDrive-backed path. New `_candidate_documents_dirs`
  helper walks (in order): HKCU\\Software\\Microsoft\\Windows\\
  CurrentVersion\\Explorer\\Shell Folders\\Personal (the value
  Windows uses internally, matches `{userdocs}`), then any
  `~/OneDrive*/Documents` and `~/OneDrive*/Dokumente` siblings,
  finally plain `~/Documents` / `~/Dokumente`. The dialog now
  finds the plugin file in the same folder the installer wrote
  it, and the *Open plugins folder* button opens that location.
- **System status: "Connected pages" count off by one (or more).**
  The Configurator's own open browser tab opens a WebSocket and
  was counted as a wallpaper page, so a user with two monitors
  who had the Configurator open saw "3 connected pages" instead
  of 2. WS clients now declare a `role` query parameter
  (`wallpaper` by default, `configurator` for the settings UI);
  the status dialog counts only `wallpaper`-role clients.
  Wallpaper-page WS clients without an explicit role default to
  `wallpaper` so legacy pages keep counting correctly.

## [0.8.9-beta] - 2026-05-22

> Tier 1 setup-polish bundle: tray System-status dialog with one-click
> Fix buttons, full Backup / Restore via ZIP, and Reset-this-screen
> on each tab. Plus a translation-key audit that fixed the
> `presets.slot_label` regression.

### Added — Tray

- **System status… dialog.** New tray entry opens a Tk window with
  one green/red row per "is the install actually working?" signal:
  SignalRGB plugin file present, SignalRGB.exe running, bridge port
  reachable, wallpaper pages connected, LibreHardwareMonitor
  reachable (only when a Hardware-sensor widget exists). Each red
  row offers a contextual Fix button — *Open plugins folder*,
  *Download SignalRGB*, *Open Help*, *Download LHM*. Refresh button
  re-checks without closing.

### Added — Configurator

- **Backup & Restore card** at the bottom of the main column.
  *Export everything…* downloads a `signalrgb-wallpaper-backup-<ts>.zip`
  containing `config.json`, the full `library/` folder, and the
  per-screen `screens/` backgrounds. *Restore from ZIP…* uploads
  the archive back and the bridge replaces `config.json`, merges
  library + screens files on top of the live dirs (won't nuke
  files that aren't in the ZIP), rebuilds the catalogue, and
  pushes fresh settings to every connected wallpaper page.
- **Reset this screen…** button on every tab (in the mirror bar).
  Restores every mirrorable setting to its `DEFAULT_SCREEN_SETTINGS`
  value while preserving the screen's viewport, preset slots, and
  mirror state. Confirmation dialog with explicit "what gets wiped"
  text. Hidden while the screen is in mirror mode.

### Added — Bridge

- **`GET /backup`** — streams a ZIP of `config.json` + `library/*` +
  `screens/*`. Sets `Content-Disposition: attachment; filename=...`
  so the browser saves it directly.
- **`POST /restore`** — accepts a ZIP body (100 MB cap), validates
  it has a parseable `config.json` with the expected schema, then
  extracts `library/*` and `screens/*` paths into their respective
  folders with path-traversal guards. Replaces the live config,
  rebuilds the library catalogue, and pushes settings to every
  screen.
- **`get_health_status`** — process check (`signalrgb` substring in
  any running process name), plugin file check
  (`~\Documents\WhirlwindFX\Plugins\SignalRGB_Desktop_Wallpaper.js`),
  WS-connected-page count, LHM sensor count, hardware-sensor
  widget detection. Powers the new tray dialog.
- **`reset_screen`** — restores defaults for one screen,
  preserves `viewportW/H`, `mirrorOf`, `presets`. Routed via the
  new `screen-reset` WS command.

### Fixed

- **`presets.slot_label` translation missing** — the static "Slot 1/2/3/4"
  labels rendered as raw uppercase keys when the `data-i18n` attr
  ran without a matching translation entry. Added the key plus a
  generic `data-i18n-<name>` attribute path so any HTML element
  can carry positional params for its translation template
  (used by *Slot {n}*; the pattern is now available for any future
  parameterised label).

## [0.8.8-beta] - 2026-05-22

> Closes the Workflow-polish slice with Mirror mode, plus a Builder
> 2×2-grid merge and a tooling fix from beta feedback.

### Added — Configurator

- **Mirror mode** per screen. A new bar above the section cards
  carries a *Mirror:* dropdown — pick *Independent* (the default) or
  *Mirror Screen N* to lock this screen's settings in lockstep with
  another screen's. On activation the bridge copies every mirrorable
  key from the source onto self; thereafter every mutation of the
  source replicates to the mirror via `_replicate_to_mirrors`. The
  mirror's section cards visibly disable (`.cards-disabled`) and
  reject edits at the bridge level too — a stale tab or future REST
  client can't drift a mirror away from its source. The overview
  card marks mirroring tiles with a small chevron badge.
- **Mirror invariant enforced server-side.** Per-screen mutations
  (`setting-update`, widget add/remove/update, widget lock,
  preset-apply, background upload) all run through `_block_if_mirror`
  before touching state. Chained mirrors (A → B → A, or A → B → C)
  are rejected at activation time so the propagation graph stays a
  flat star.

### Added — Builder

- **2×2 grid merge.** *Merge images* section gains a mode dropdown:
  *2 images side-by-side* (the original) or *2×2 grid (4 images)*.
  In grid mode four slots (TL / TR / BL / BR) become available, each
  with the same file picker / drag-drop / *From library…* button as
  the existing pair. Output forces equal-size quadrants; the cell
  dimensions match the largest input on each axis so neither half
  loses resolution.

### Fixed

- **Tool-options column too narrow** for long localised button
  labels. Widened from 232 px → 260 px so *"Alle Änderungen
  zurücksetzen"* and friends fit cleanly without bumping into the
  canvas border.

## [0.8.7-beta] - 2026-05-22

> Two of the three remaining Multi-monitor-convenience items from the
> Workflow-polish slice. Mirror mode is the only Workflow-polish
> entry still outstanding (deferred to v0.8.8-beta because it needs
> bridge-side invariant enforcement that wants its own focused beta).

### Added — Configurator

- **Apply to all screens — per section.** Each Background / Glow /
  Effects / Widgets card header now carries an *Apply to all* button
  (visible only when `screenCount > 1`). Click → confirm → the
  current screen's values for that section's keys get POSTed to
  every other screen. Each section declares its own key set so the
  one button works for one card without leaking into others.
- **Overview card with mini-monitor thumbnails.** New row between
  the tab strip and the first card (hidden for single-monitor
  setups). One 130 × ~73 px thumbnail per screen showing the
  current background image with a resolution overlay. Click jumps
  to that screen's tab. Active screen gets a brighter border + 2 px
  glow ring. Driven by the same `/config` poll that feeds the tab
  resolution labels — single fetch, both views consistent.

### Bridge

- **`POST /screen/<N>/settings`** — batch setting update on screen
  N. Body is a JSON object of `{key: value}` pairs; each key is
  filtered through the same `_SETTABLE_SCREEN_KEYS` whitelist the
  WS `setting-update` command uses, so the HTTP path adds no
  attack surface. Used by the Configurator's Apply-to-all flow
  because the WS connection is bound to one screen at a time.
- **`/config` returns per-screen `bgImage`** alongside
  `viewportW/H`. Used by the Overview card to paint mini-thumbnails
  without opening a WS per screen.

## [0.8.6-beta] - 2026-05-22

> Hotfix: installer was overwriting the user's `library.json`, which
> hid uploaded wallpapers from the Configurator until the user
> uploaded *another* image (forcing the bridge to rebuild the
> catalogue from disk).

### Fixed

- **Library tiles missing after an installer-driven upgrade.** The
  installer's `[Files]` section shipped a bundled `library.json`
  listing only the four starter wallpapers and overwrote the user's
  own catalogue on every install. The PNGs were still on disk, but
  the bridge's `/library/list` endpoint just returned whatever
  `library.json` said — so user uploads vanished from the strip
  (re-appearing on the next upload because that path regenerates
  `library.json` from the directory contents).
  - **Bridge**: rebuild the library catalogue once at startup. This
    repairs any state where `library.json` is out of sync with the
    actual files (installer overwrite, manual file copy, sync
    conflicts). `_library_rebuild_catalogue` already preserves
    pinned/order/addedAt for entries that survived.
  - **Installer**: split the library `[Files]` entry into two —
    PNGs always copy (so users who deleted a starter get it back),
    but `library.json` now uses `onlyifdoesntexist` so it's
    installed on first install only and never overwritten on
    upgrade.

## [0.8.5-beta] - 2026-05-22

> Bug-fix-and-polish pass over v0.8.4-beta plus the Builder crop tool.
> Heavier multi-monitor items (Mirror mode, Apply-to-all,
> Overview card) are deferred to a future beta because they need
> careful invariant work on the bridge side.

### Fixed

- **Glow preview painted on top of the canvas** instead of through
  the transparent regions. `::before` lived above the canvas in the
  positioned stack; `isolation: isolate` on `.canvas-host` plus
  `z-index: -1` on the glow layer scopes it correctly behind the
  canvas content without escaping past the host's own box.
- **Tool panel buttons clipped past the column edge** for long
  localised labels (e.g. "Alle Änderungen zurücksetzen" in the
  narrow 232 px Tools column). `.btn-row .btn` now allows wrap +
  `min-width: 0` so labels break to a second line instead of
  overflowing.

### Added — Builder

- **Library picker on Merge slots A and B.** *From library…* button
  next to each *Pick* file picker opens the same modal grid the
  *Open from library…* button uses; the picked tile lands in the
  merge slot rather than the main canvas.
- **Crop tool.** New toolbox entry (icon: crop corners). Drag a
  rectangle, then Confirm to resize the canvas to that region —
  pulls pixels through a scratch canvas so all in-progress mask
  edits survive. Click history resets on commit since the click
  coords no longer match. Switching tools mid-pending-crop cancels
  the rectangle.

### Added — Configurator

- **Tab labels show resolution** when a wallpaper page has connected
  for that screen — "Screen 2 — 3840×1080" instead of bare
  "Screen 2". Falls back to the bare label when no page is
  connected yet. Polls `/config` every 5 s so a monitor switching
  resolution shows up without a hard refresh.

## [0.8.4-beta] - 2026-05-22

> Closes the Workflow-polish slice on the Gallery side and lands the
> long-promised Builder *Show glow preview* toggle. Multi-monitor
> convenience (Mirror mode, Apply-to-all, overview card, tab
> resolutions) is the focus of the next beta.

### Added — Configurator library

- **Pin to top.** New *Pin / Unpin* entry in the right-click context
  menu. Pinned tiles render first, ahead of starters and uploads, with
  a small star badge in the upper-left corner. Persisted as
  `pinned: true` inside `library.json`; bridge merges the flag back
  into the catalogue on every directory rescan (upload / rename /
  duplicate / delete no longer wipe pin state).
- **Sort order: pinned → user order → newest → label.** The strip now
  sorts by: pinned first, then user-set `order` from drag-reorder,
  then `addedAt` descending (newest upload bubbles up), then label
  alphabetical as a stable tie-break. `addedAt` is stamped on every
  entry from file mtime so fresh uploads sort correctly even before
  the user touches anything.
- **Drag-and-drop reorder.** Each tile is `draggable=true`. Drop on
  the left/right half of a target tile to insert before/after with a
  visible drop-indicator (4 px coloured edge). New order POSTs to
  `/library/reorder` which assigns sequential `order` indices in
  `library.json`. Works across pinned + unpinned items.

### Added — Builder

- **Show glow preview toggle** in the canvas toolbar (right side,
  next to the canvas-stat). Swaps the canvas's transparency
  checkerboard for an animated RGB-cycle gradient layered behind, so
  cut-out pixels show what the SignalRGB glow will look like as you
  edit. Off by default (the checkerboard is still the canonical view
  for spotting unintended transparency).

### Bridge

- `POST /library/pin` — body `{file, pinned}`, toggles the pin flag
  on one entry without re-scanning the directory.
- `POST /library/reorder` — body `{order: [file1, file2, …]}`,
  assigns sequential order indices to listed entries; unlisted
  entries are pushed past the end so they stay reachable.
- `_library_rebuild_catalogue` preserves user-state fields
  (`pinned`, `order`, `addedAt`) across rebuilds. `addedAt` is
  stamped from file mtime for fresh entries.

## [0.8.3-beta] - 2026-05-22

> Workflow polish for the **Configurator's Library** and the **Builder**
> — first half of the planned Workflow polish slice from `docs/roadmap.md`.
> Makes browsing, picking, editing, and saving library wallpapers feel
> like a real gallery instead of a click-and-pray strip.

### Added — Configurator library

- **Hover preview popup.** Hovering a library tile opens a larger 16:9
  preview (480×302) anchored to the tile, with an animated RGB
  gradient layer behind. Since wallpapers carry transparent cut-outs
  (the entire point of this app), the gradient bleeds through and
  previews how the SignalRGB glow will look once paint lands on top.
  Auto-dismisses with a small grace period when the mouse leaves;
  Escape, scroll, or click-outside also dismiss.
- **Click-to-preview (pinned).** Clicking a tile no longer
  immediately replaces the screen's background. Instead the preview
  pins open — auto-hide on mouseleave is disabled while pinned, and a
  dedicated **Apply** button inside the popup actually commits.
  Removes a long-standing footgun where a stray click could wipe the
  current wallpaper.
- **5-second Undo toast.** When a library item is applied, the toast
  shows for 5 s with an inline **Undo** button. Clicking Undo POSTs
  the previously-active background bytes back to the screen. We
  snapshot the bytes via the `/image?path=…` proxy *before* the new
  POST — necessary because the bridge deletes the old `screen-N-*.png`
  file on each apply, so the only way to recover is to capture the
  bytes first.
- **Right-click context menu** on every tile with: **Apply** · **Edit
  in Builder…** (opens `/builder?library=<file>`) · **Rename…**
  (prompts for new label, re-uploads + deletes old) · **Duplicate**
  (creates `<label> Copy`) · **Delete…** (existing confirm dialog).
  Menu auto-clamps to the viewport and closes on Escape, scroll, or
  click-outside.

### Added — Builder

- **Open from library… picker.** New button next to *Choose image…*
  opens a centred modal grid of every library tile. Click one to load
  it as the source image — same code path the file-picker uses, so
  edits / merges / saves work identically. Reads `/library/list` on
  open (no caching).
- **Save to library button.** Once an image is loaded, the new
  *Save to library* button POSTs the current canvas to
  `/library/upload?name=…` with a prompt-supplied label, defaulting
  to the source filename. Useful for round-tripping a Builder edit
  back into the Configurator's library strip without going through
  the OS file system.
- **`?library=<file>` URL parameter.** Builder honours
  `?library=foo.png` on load and fetches that file from `/library/`
  through the standard pipeline. Used by the Configurator's
  *Edit in Builder…* context-menu item.

### Internal

- **Reusable preview popup / context menu / library dialog.** Each
  is a single DOM element built on first use and re-used across
  invocations (item, position, label). Click-outside / Escape /
  scroll dismissal is centralised. No per-tile listener leaks
  on `renderLibraryStrip` re-renders.

## [0.8.2-beta] - 2026-05-20

> Adds an optional integration with **LibreHardwareMonitor** for the
> hardware-sensor widget family, plus folds in the v0.8.1 perf
> fix-up that was sitting un-tagged.

### Added

- **Hardware Sensor widget.** New generic widget type that reads
  any sensor LibreHardwareMonitor is reporting — CPU / GPU temps,
  fan RPMs, voltages, drive temps, power readings, etc. Picks the
  sensor from a dropdown that's populated dynamically from a new
  `GET /hwmon/sensors` endpoint, with live current-value previews
  next to each path so you can find what you're looking for.
  Sparkline tracks last ~2 min @ 1 Hz. Optional label override and
  decimals control per widget. **LHM is not bundled** — users who
  want temps/fans install LibreHardwareMonitor separately (free,
  MPL 2.0) and enable its *Options → Remote Web Server*. When LHM
  isn't running the widget shows `—` and the sensor dropdown shows
  `(LHM not detected — see Help → Tips)`. Help page has a step-by-
  step setup section under *Tips*. License audit + `docs/credits.md`
  entry added; MPL 2.0 doesn't propagate because we don't
  redistribute any LHM files.
- **`/hwmon/sensors` HTTP endpoint** on the bridge — returns a
  flat sorted list of every sensor (path, current value, unit) plus
  a `status` block (online, sensorCount, lastError). Used by the
  Configurator's options modal; could also drive future Hardware
  Monitor dashboards from external tools.

### Fixed (from the unreleased v0.8.1 perf work)

- **SignalRGB-startup lag.** SignalRGB fires every `onXChanged`
  callback once per `ControllableParameter` while a plugin
  initialises — for our plugin that's `ongridSizeChanged`,
  `onaspectRatioChanged`, `oncustomColsChanged` and
  `oncustomRowsChanged`, each of which used to call `applyZoneSize`
  directly. Combined with the one `applyZoneSize` from
  `Initialize()`, every device rebuilt its `device.setControllableLeds`
  registry **five times in a row** at startup. For an ultrawide on
  `Auto + base=64` that's 5 × 14592 = ~73k LED operations per device
  per startup — and SignalRGB's JS sandbox is single-threaded across
  all plugins, so the whole tick stalled until ours finished.
  - The four `onXChanged` exports now set a module-scope `dimsDirty`
    flag instead of calling `applyZoneSize` directly. `Render()`
    coalesces the burst into a single rebuild on its next tick.
  - `applyZoneSize` itself gained an early-bail: if the resolved
    dimensions match the current `s.cols/s.rows` and the frame
    buffer is already allocated, it returns immediately — the
    expensive `setControllableLeds` call is skipped.
  - The `/config` poll only flips `dimsDirty` when the viewport for
    a screen actually changes (was: flip on every 2 s poll while
    Aspect = Auto, causing redundant rebuilds).
  - `Render()` no longer calls `computeGridDimensions()` on every
    frame — that was 30 fps × N devices = 120 calls / s of small but
    pointless arithmetic on the steady-state path.

  Together these are the difference between "noticeable hitch when
  SignalRGB starts" and "no hitch at all" on the 4-monitor /
  ultrawide setup.

## [0.8.1] - 2026-05-20 *(never tagged — folded into 0.8.2-beta)*

### Fixed

- **SignalRGB-startup lag.** SignalRGB fires every `onXChanged`
  callback once per `ControllableParameter` while a plugin
  initialises — for our plugin that's `ongridSizeChanged`,
  `onaspectRatioChanged`, `oncustomColsChanged` and
  `oncustomRowsChanged`, each of which used to call `applyZoneSize`
  directly. Combined with the one `applyZoneSize` from
  `Initialize()`, every device rebuilt its `device.setControllableLeds`
  registry **five times in a row** at startup. For an ultrawide on
  `Auto + base=64` that's 5 × 14592 = ~73k LED operations per device
  per startup — and SignalRGB's JS sandbox is single-threaded across
  all plugins, so the whole tick stalled until ours finished.
  - The four `onXChanged` exports now set a module-scope `dimsDirty`
    flag instead of calling `applyZoneSize` directly. `Render()`
    coalesces the burst into a single rebuild on its next tick.
  - `applyZoneSize` itself gained an early-bail: if the resolved
    dimensions match the current `s.cols/s.rows` and the frame
    buffer is already allocated, it returns immediately — the
    expensive `setControllableLeds` call is skipped.
  - The `/config` poll only flips `dimsDirty` when the viewport for
    a screen actually changes (was: flip on every 2 s poll while
    Aspect = Auto, causing redundant rebuilds).
  - `Render()` no longer calls `computeGridDimensions()` on every
    frame — that was 30 fps × N devices = 120 calls / s of small but
    pointless arithmetic on the steady-state path.

  Together these are the difference between "noticeable hitch when
  SignalRGB starts" and "no hitch at all" on the 4-monitor /
  ultrawide setup.

## [0.8.0] - 2026-05-20

> First stable after the long 0.7.x beta cycle. Rolls up every
> feature from v0.7.1-beta → v0.7.10-beta (full-screen audio glow,
> auto-Lively bootstrapper, library upload / delete, pattern brush,
> 4-monitor support, ultrawide aspect ratios, configurator + builder
> localisation, single-bundle Wallpaper Engine packaging, …) plus
> the items below.

### Added

- **In-browser Help page.** New `/help` route serves a scenario-based
  walkthrough — Quick start + 1/2/3/4 monitor setups for both Lively
  and Wallpaper Engine (independent vs single-bundle vs spanned),
  ultrawide aspect notes, and a Tips & common pitfalls section.
  Pure HTML, no dependencies beyond what's already bundled. Full
  DE / EN — language pulled from `GET /config` like Builder.
- **Tray menu gains a *Help…* entry** alongside *Configurator…* and
  *Build Wallpaper…*. Opens `/help` in the user's default browser.
- **Optional help-images folder.** Each scenario card carries an
  `<img>` placeholder under `/help/images/<name>.png`. Bridge serves
  whatever's in `%LOCALAPPDATA%\SignalRGBWallpaper\help_images\` (user
  override) or `wallpaper_bridge/help_assets/` (dev fallback). Missing
  images hide silently (no broken-image icons) — the ASCII diagrams
  in each card stand alone if no screenshot is provided.
- **`docs/installation.md` gains a screenshot walkthrough** of every
  Inno Setup wizard step (language → license → tasks → summary →
  file-in-use → finish). README quick-start links to it.

### Changed

- **Installer task defaults cleaned up.** *Install the SignalRGB
  Desktop Wallpaper plugin* keeps its default-on state but the
  description now flags it as **required**, and it sits at the top of
  *Additional setup* instead of buried below the autostart/configurator
  toggles. Users who casually uncheck it currently end up with a
  bridge but no SignalRGB → bridge path; the new wording makes the
  consequence obvious.
- **Removed the redundant "Open Wallpaper Engine projects folder"
  post-install action** for the auto-copy-detected case. When both
  Steam and WE are detected, the bundle is already in place and
  shows up in WE's *My Wallpapers* tab — opening Explorer to confirm
  a file landed there was filesystem-debug noise, not a normal user
  need. The not-detected fallback (where the user *does* need to
  drag a folder into WE manually) stays.

## [0.7.10-beta] - 2026-05-20

### Fixed

- **WE audio fix from v0.7.9-beta was set on the wrong JSON node.**
  v0.7.9-beta added `"supportsaudioprocessing": true` at the project
  root, but WE only honours it as a child of `general` (verified
  against real Workshop wallpapers, e.g.
  [IPdotSetAF/NeoMatrix](https://github.com/IPdotSetAF/NeoMatrix)).
  Moved to the right place — `wallpaperRegisterAudioListener`
  callbacks finally fire under WE.

## [0.7.9-beta] - 2026-05-20

### Fixed

- **Audio still dead in Wallpaper Engine.** v0.7.8-beta fixed Lively
  via `LivelyInfo.Arguments = "--audio"`, but WE has an analogous
  opt-in: `project.json` must declare `"supportsaudioprocessing":
  true` or the engine ignores every `wallpaperRegisterAudioListener`
  callback. Our `project.json` didn't set it, so the audio-glow
  layer + audio-spectrum widget saw no FFT samples on WE. Added to
  the build's combined-bundle manifest generator. *(v0.7.10-beta
  caveat: the flag was put on the top-level node here — WE silently
  ignored it. Real fix is in 0.7.10-beta.)*

## [0.7.8-beta] - 2026-05-20

> Sweep of user-reported papercuts plus the last open roadmap item.

### Added

- **Auto-Lively bootstrapper.** Closes the last *Planned* roadmap
  item: when the user opts in and Lively isn't detected, the
  installer downloads the latest Lively setup from GitHub Releases
  and runs it silently before the auto-import [Files] step. Driven
  by a new bundled `install_lively.ps1`; fails closed (no kill of
  the wizard) if GitHub is unreachable. New Inno [Tasks] entry
  `installlively/autoinstall` (sub-task of *Lively Wallpaper*,
  default on).
- **Library upload + delete in the Configurator.** Bridge gains
  `POST /library/upload?name=<label>` (raw PNG / JPEG / WebP body)
  and `DELETE /library/<file>`. Configurator's Background section
  shows an *Add image…* button next to the strip; each tile has a
  hover-only `×` delete corner. Library catalogue is rebuilt on
  every mutation so the strip refreshes immediately.

### Fixed

- **Audio listener never fired in Lively.** `LivelyInfo.Arguments`
  was `null` since v0.7.1-beta (after the `--system-cursor true`
  fiasco), but Lively only pushes audio data when the wallpaper opts
  in. Set to `"--audio"` (the documented Lively flag) so both the
  whole-screen audio glow layer AND the audio-spectrum widget
  actually receive FFT samples on Lively. WE users were unaffected.
- **Configurator status badge showed `connected · tray.screen_n`.**
  The template called `t("tray.screen_n", …)` but `tray.screen_n`
  only exists in the bridge's tray-side translation table, not the
  Configurator's. Replaced with a dedicated `conn.connected` entry
  ("connected · Screen {n}" / "verbunden · Bildschirm {n}").
- **Configurator tabs for inactive screens stayed visible** (dimmed).
  Switched to `display: none` so a 1-screen install only shows
  *Screen 1*. Lowering the screen count while a higher tab is active
  falls back to *Screen 1* automatically.
- **Hover-glow Pixelfx rendered as a square** in some CEF builds.
  The radial-gradient `fillRect` was technically alpha-0 at the
  corners but the CEF compositor was rendering the rect bounds
  anyway. Switched to `ctx.arc + ctx.fill` — guaranteed circle.

### Changed

- **Inno installer task defaults pass.** *Wallpaper Engine* now
  defaults to checked (was unchecked) — undetected Steam installs
  are still no-ops thanks to the `Check: WallpaperEngineDetected`
  gating, so the default-on doesn't risk anything. New optional
  task *Open the Configurator in your browser when done* (default
  on). Description wording for *Auto-import* + *Start bridge on
  logon* tightened.

## [0.7.7-beta] - 2026-05-20

### Added

- **Per-screen preset slots in the Configurator.** Four numbered
  slots per screen, each saving a snapshot of every settable field
  in `PRESET_SNAPSHOT_KEYS` (background image / fit / dim, glow
  layout / strength / blurs, all ambient + pixelfx + parallax +
  audio-glow knobs, **and the full widget array including positions
  and options**). New WS command types: `preset-save` /
  `preset-apply` / `preset-clear`. Bridge runtime gains matching
  `save_preset` / `apply_preset` / `clear_preset` methods. UI:
  collapsed-by-default *Presets* section above *Background* with one
  row per slot showing a short summary (widget count, layout,
  active effects). Pre-v0.7.7-beta configs auto-pad to four empty
  slots on next load.
- **Pattern-fill brush in the Builder.** New tool button in the
  toolbox (dots glyph) — instead of clearing a solid hole, paints
  transparency in a structured pattern. Three pattern types:
  *Halftone* (dot grid, dot radius modulated by density), *Dither*
  (ordered Bayer 8×8 threshold matrix), *Hatching* (parallel lines
  at a chosen angle and spacing). Scale (2..32 px), Density (5..95 %),
  Angle (0..180°) sliders. Reuses the existing brush size / hardness
  / shape options. Pattern coordinates are absolute-canvas-based, so
  adjacent strokes tile continuously instead of restarting per stamp.
  Stored as a new `kind: "pattern"` click record so undo / redo /
  rotate-90° work consistently with the other tools.
- **Wallpaper library.** Four procedurally generated starter
  wallpapers (cyberpunk skyline, neon grid, anime round window,
  geometric panels) ship with the installer, dropped into
  `%LOCALAPPDATA%\SignalRGBWallpaper\library\` together with a
  `library.json` manifest. The Configurator's *Background* section
  gets a *Library* strip of thumbnail tiles; clicking one uploads
  the full-res PNG to the active screen via the same
  `POST /screen/N/background` endpoint the Builder uses. Bridge
  serves the listing + files at `/library/list` and `/library/<file>`
  with path-traversal protection (no `..` / slashes in filenames).
  Users can add their own PNGs to the same folder; the bridge
  enumerates whatever's there.

### Changed

- **Plugin log spells out what Auto resolved to.** `applyZoneSize`
  used to log just `aspect=Auto`. Now it appends either
  `(viewport 3840x1080)` if the bridge has seen a real viewport push
  from the wallpaper page, or `(no viewport from bridge — 16:9
  fallback)` if not. Turns "why are my LEDs 7296 instead of 14592?"
  into a single-grep diagnosis in `SignalRGB_*.log`.

## [0.7.6-beta] - 2026-05-20

> Tiny plugin-side fix: SignalRGB's layout editor was rendering our
> LED cells as rectangles because the plugin declared a 1:1 visual
> aspect while sending non-square LED grids at runtime.

### Fixed

- **SignalRGB layout editor stretched LED cells horizontally.**
  `export function Size()` is the device's *visual aspect ratio* in
  the canvas — SignalRGB locks the on-canvas bounding box to that
  ratio and stretches whatever runtime `device.setSize([cols, rows])`
  pushes to fit it. Our plugin used to declare `[32, 32]` (1:1),
  which made e.g. a 32×8 runtime grid render as 4:1-stretched cells.
  Changed to `[16, 9]` so 16:9 monitor users (the dominant case)
  finally see square LED cells. Ultrawide / portrait users will still
  see some stretching in the editor but far less than before, and
  the actual glow output to the wallpaper page is unaffected — only
  the SignalRGB-editor preview was wrong.
- **`DefaultScale()`** dropped from a suspicious `60.0` to `1.0`
  (full-canvas default when the device is first dropped). Pre-
  existing user placements are not touched; this only affects
  fresh adds.

## [0.7.5-beta] - 2026-05-20

> Ships the long-standing roadmap item *Whole-screen audio-reactive
> glow layer*. The audio-spectrum widget covered "audio visualiser
> in a box" since 0.6.0-beta; this adds a full-canvas counterpart.

### Added

- **Audio-reactive glow layer** behind the wallpaper. Reuses the same
  FFT feed the audio-spectrum widget already drains (Lively's
  `livelyAudioListener` / WE's `wallpaperRegisterAudioListener`), so
  no second registration is needed. Three modes:
  - *Pulse* — overall amplitude drives a smoothed radial halo
    breathing outward from the centre.
  - *Spectrum bars* — 64 bars rising from the bottom edge.
  - *Waveform* — symmetric line through the screen's centre,
    amplitude-modulated.
  Configurator's *Effects* section gains a *Audio glow* dropdown +
  *Intensity* slider + *Tint with the live glow colour* toggle.
  Canvas uses `mix-blend-mode: screen` so it adds light over the
  underlying glow instead of replacing it.
- Settings keys whitelisted: `audioGlow` (`off`/`pulse`/`spectrum`/`wave`),
  `audioGlowIntensity` (0..100), `audioGlowTint` (bool). Defaults:
  off / 60 / false.

## [0.7.4-beta] - 2026-05-20

> Retires the legacy Tk Settings dialog: every knob it owned moved
> into the in-browser Configurator. Builder window joins the DE / EN
> localised UI.

### Added

- **Configurator owns `Number of screens`.** A small picker lives in
  the tab bar's top-right ("Screens: 1 / 2 / 3 / 4"). Clicking sends
  a new WS command type `bridge-setting-update` to the bridge, which
  persists the value to `config.json` and re-pushes settings to every
  connected Configurator so all open tabs stay in sync. Tabs beyond
  the active count are visually dimmed (clickable, but the matching
  SignalRGB device isn't announced).
- **Configurator owns *Show debug overlay*.** Per-screen checkbox in
  the Background section, wired through the existing
  `setting-update showStatus` path.
- **`GET /config` exposes the active UI language** alongside
  `screenCount` + `screens[]`. The Builder fetches it on load.
- **Builder is DE / EN.** Its own `TRANSLATIONS` map + `t()` +
  `applyI18n()` (same shape as the Configurator), covering every
  visible label, tooltip, hint, and toast message. Language source
  is the new `/config` field.

### Changed

- **Tray menu retires the *Legacy Settings dialog…* entry.** Every
  knob the dialog owned now lives in the Configurator (per-screen
  settings already moved in 0.6.0-beta; `screenCount` + `showStatus`
  finished the move in this beta). The `SettingsDialog` class stays
  in `bridge.py` as dormant code in case a future workflow needs a
  no-WebView fallback, but no menu entry reaches it.
- **Architecture doc** updated to reflect the threading model now
  having one `tk.Tk()` user — the About dialog — instead of two.

## [0.7.3-beta] - 2026-05-20

> Adds auto-cleanup of the legacy per-screen Wallpaper Engine folders
> on upgrade — previously you had to delete them manually. Same
> packaging as v0.7.2-beta otherwise (single combined WE bundle with
> a *Screen index* property).

### Changed

- **Installer wipes legacy WE folders before copying the new bundle.**
  Inno Setup's `[InstallDelete]` removes
  `SignalRGB_Glow_Screen{1..4}/` from both the install staging folder
  (`{app}\Wallpaper Engine wallpapers\`) and — when Steam is
  detected — Steam's `…\projects\myprojects\`, gated on the WE task.
  Pre-v0.7.2-beta users upgrading via the new installer get a clean
  WE library automatically. The per-screen items were never published
  to Steam Workshop, so the installer is the only path that ever
  placed those folders.

## [0.7.2-beta] - 2026-05-20

> Wallpaper Engine packaging consolidation: one Workshop item with a
> *Screen index* property replaces the four per-screen bundles. Folds
> in everything from v0.7.1-beta (4-monitor support, ultrawide aspect
> ratio, Lively-import hotfix, Weather widget cache fix).

### Changed

- **Single Wallpaper Engine bundle.** The installer now copies
  `wallpaper_bridge/we_bundles_single/signalrgb-glow/` into both
  `{app}\Wallpaper Engine wallpapers\signalrgb-glow\` and (when Steam
  is detected) `…\steamapps\common\wallpaper_engine\projects\myprojects\signalrgb-glow\`,
  instead of four per-screen folders. Subscribers assign the same
  wallpaper to every monitor they want to drive and pick a different
  *Screen index* (Screen 1 / 2 / 3 / 4) per assignment in WE's
  properties panel. The bridge already routed by `?screen=N` query
  param, so this is a packaging change only — no protocol change.
- **`installer/build.ps1`** drops step `[3b/5]` (per-screen WE bundle
  staging) entirely; the legacy `wallpaper_bridge/we_bundles/` folder
  is wiped on each build so it can't accidentally feed stale sources
  into the installer.
- **Uninstaller** removes the new `signalrgb-glow/` folder AND the
  legacy `SignalRGB_Glow_Screen{1..4}/` folders, so upgrades from
  earlier beta installs leave a clean Steam projects folder.

## [0.7.1-beta] - 2026-05-20

> Folds the Lively-import hotfix into a beta that also lifts the
> long-standing `MAX_SCREENS = 3` cap to **4**. Released as a
> prerelease — stable users with *Allow beta versions* off won't see
> it as an update.

### Added

- **4-monitor support.** The bridge's `N_SCREENS`, the SignalRGB
  plugin's `MAX_SCREENS`, the Configurator's tab generator, the
  Builder's *Apply to screen* + *Multi-monitor split* button rows,
  the installer's auto-import / WE-bundle copies, and the single-WE-
  bundle's `screenIndex` combobox all moved from 3 → 4. Bridge config
  migration is data-driven on `N_SCREENS`, so existing `config.json`
  files gain the Screen 4 settings block on next launch without
  losing anything.
- **Build emits 4 Lively zips + 4 WE folders.** `installer/build.ps1`
  iterates `0..3` for the per-screen Lively and WE stagers; installer
  copies / auto-imports / uninstaller entries all extended.
- **Non-square glow grids for ultrawide monitors.** The SignalRGB
  plugin gained an *Aspect Ratio* dropdown (Auto / 1:1 / 16:9 / 21:9
  / 32:9 / 9:16 / Custom) and *Custom Cols* / *Custom Rows* textfields.
  *Auto* reads each screen's actual viewport (the wallpaper page
  already reports it over WS; the bridge now relays it through
  `GET /config` in a new `screens[]` sidecar) and derives the longer
  side from the *Glow Grid Base Size* combobox so a 3840 × 1080 panel
  gets `base × (base · 3840/1080)` instead of a square that
  under-samples its width. The wire format already supported
  arbitrary W × H frames; the wallpaper page reads `--cols` / `--rows`
  per frame, so no client-side change was needed.

### Fixed

- **Lively import failure** (carried over from the local v0.7.1
  hotfix that was never published). `LivelyInfo.Arguments` reverted
  from `"--system-cursor true"` to `null`. Parallax + Pixelfx still
  receive cursor coordinates via the DOM `mousemove` listener
  whenever Lively's *Wallpaper interaction* setting is enabled (or
  the page is loaded in WE / a browser). Pure click-through users no
  longer get cursor-driven effects, which is a knowable trade-off
  and far less bad than a broken wallpaper.
- **Weather widget always showed Berlin.** When the user edited the
  location through the Configurator, the widget's `rec.cache` (last
  fetched payload, including the *label*) and `rec.lastFetch`
  timestamp (30-min refresh cap) were never invalidated, so the
  next render still showed the old data and the next tick wouldn't
  re-fetch for up to half an hour. `applyWidgetOptions` now stores a
  signature of the previous options and drops cache + fetch timer
  whenever it changes, forcing an immediate re-fetch on edit. Fix
  is generic — countdown / quote / any future cached widgets benefit.

## [0.7.0] - 2026-05-19

> First stable release after a long beta cycle (0.5.0 → 0.6.2-beta).
> Rolls in everything from the beta line plus the polish iteration on
> top of 0.6.2-beta: auto-import into Lively, chunked UDP transport
> (real 128 × 128 grids), DE / EN localisation, About-dialog overhaul,
> snap-to-grid in the configurator, 3D parallax, and a convenience
> top-level Lock/Unlock entry in the tray.

### Added

- **Wallpaper reports its real viewport to the bridge.** Page sends
  `{type:"viewport", w, h}` on WS open + on `window.resize`
  (debounced). Bridge persists per-screen `viewportW` / `viewportH`.
  Configurator's layout-preview scales to the actual monitor — 4K
  users now see a real 3840 × 2160 canvas instead of a guessed
  FullHD rectangle, and the preview header reports the source
  (`monitor · 3840 × 2160 px` vs `no wallpaper connected — assuming
  1920 × 1080`). Disk-write is skipped when the size matches the
  persisted value.
- **Top-level Lock / Unlock widgets in the tray.** Single entry above
  the *Advanced* submenu that toggles `widgetsLocked` across every
  active screen at once. Label flips (`🔓 Lock widgets (all screens)`
  / `🔒 Unlock widgets (all screens)`) based on current state.
- **Snap-to-grid in the Configurator's layout preview.** Toggle +
  step picker (10 / 20 / 40 / 80 px); the preview canvas overlays
  the snap grid in accent blue when enabled. Drag and resize both
  snap to the chosen step. State persists in `localStorage` so it
  survives reloads.
- **About dialog overhaul.** Now shows the maintainer's real name
  (Sebastian Mendyka) with a clickable `@Delido on GitHub` line and
  the avatar fetched from `https://github.com/Delido.png` (5 s
  timeout, cached). The wall-of-OSS text has been moved to
  `docs/credits.md` on GitHub — the dialog now links there instead.
  Added a *"Buy me a coffee"* PayPal button.
- **3D parallax** (`parallax3d`, CSS px max-displacement, 0..120).
  When > 0 the background image lerps a fraction of the cursor
  offset for a fake-depth effect. Cursor coords flow from two
  sources: Lively's `livelyCurrentCursorPos` callback (pushed by the
  host when available) and a DOM `mousemove` listener that catches
  real events when *Wallpaper interaction* is enabled. Scale-up of
  the bg image is computed per frame so the worst-case translate
  doesn't reveal edges, with 2 % headroom for jitter. Smooth RAF
  lerp; disabled (no rAF cost) when off. Slider lives in the
  Configurator's *Effects* section. Same dual cursor feed also
  covers Pixelfx.
- **Chunked UDP transport.** The SignalRGB plugin sandbox caps
  `udp.send()` at 4 096 B per datagram, which had pinned us at
  36 × 36 grids. The plugin now sends frames > 4 KB as multiple
  datagrams with a new `SC` magic (`[0x53][0x43][screen][frameId]
  [chunkIdx][chunkCount][w₂][h₂][pixelOffset₂][rgb…]`); the bridge
  buffers chunks per `(screen, frameId)` and reassembles before
  forwarding to the wallpaper page. Stale partials (different
  frame-id or > 200 ms old) are evicted. Wallpaper-side renderer is
  unchanged. `MAX_GRID` raised from 36 to **128**; combobox gains
  `64 / 96 / 128`. Backwards-compatible — anything ≤ 36 × 36 still
  uses the original single-packet `SR` format.
- **Installer auto-imports Lively wallpapers.** New opt-in sub-task
  *"Auto-import into Lively (skip the manual drag-and-drop step)"*.
  When checked and a Lively install is detected — GitHub build
  (`%LOCALAPPDATA%\Lively Wallpaper\…`) or MSIX build
  (`%LOCALAPPDATA%\Packages\rocksdanister.LivelyWallpaper_*\…`) —
  the three bundles get extracted directly into Lively's
  `Library\wallpapers\signalrgb-glow-screen-{1,2,3}\`. Deterministic
  folder names mean every subsequent installer run **overwrites in
  place**, killing the "delete + re-import after every update"
  caveat that bit every release until now. Uninstall removes the
  three folders, leaves other Lively wallpapers alone.
- **Localisation — DE / EN.** New top-level config flag
  `language: "auto" | "en" | "de"` (default `"auto"` — picks from
  Windows locale / `$LANG`). Bridge exposes a `tr(key, **kwargs)`
  helper backed by a single in-file translation table; tray menu,
  Updates submenu, Effects submenu, Widgets submenu, About dialog
  and balloon notifications are all translated. Configurator
  mirrors the same pattern (`data-i18n` attributes + `t()` helper);
  the active language arrives with every settings push from the
  bridge so the page localises on first frame. Builder window
  stays English — its ~80 strings are tracked as a separate
  follow-up.

## [0.6.2-beta] - 2026-05-19

> Prerelease. Adds `36×36` as the finest packable grid; 64×64 was
> tried and reverted because of a SignalRGB sandbox limit (see below).

### Added

- **Glow Grid Size combobox gains `36`** alongside `8 / 16 / 32`. 36×36
  fits exactly under SignalRGB's per-packet UDP cap (36×36×3 + 7 B
  header = 3 895 B); going any higher requires chunked transport.

### Known limit

- **SignalRGB's `udp.send()` is capped at 4 096 B per datagram**, well
  below the IPv4 UDP-payload ceiling. We attempted 64×64 (= 12 295 B
  per frame) and immediately saw
  `udp.error - Buffer too large. Max size is 4096 bytes!` in the
  SignalRGB log with no frames reaching the bridge. `MAX_GRID` in
  `SignalRGB_Desktop_Wallpaper.js` is therefore 36. A future iteration
  could split each frame across multiple datagrams (the bridge would
  reassemble) for true 64+ grids.

## [0.6.1-beta] - 2026-05-19

> Prerelease. Configurator UX polish on top of 0.6.0-beta.

### Changed

- **Configurator: prominent lock / unlock toggle.** The widgetsLocked
  switch was an easily-missed checkbox; it's now a full-width lock-bar
  at the top of the Widgets section with a coloured status dot, a
  big label ("Widgets locked" / "Widgets unlocked"), and a clear
  action button ("Unlock to edit" / "Lock widgets"). Single source of
  truth — flipping it pushes the same state to the live wallpaper.

### Added

- **Layout preview in the configurator.** New canvas under the lock-bar
  showing the screen as a scaled rectangle (auto-fits to the bounding
  box of all widgets or 1920×1080, whichever is bigger) with each
  widget rendered as a draggable + resizable box. Pointer events drive
  drag / resize; min size 60×60 px; positions clamp to the canvas.
  On release, the configurator sends the same `widget-update` command
  the wallpaper page uses, so the live wallpaper jumps to match. Drag
  / resize only active when the lock-bar is unlocked — locked state
  shows the layout as a static read-only view.

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
