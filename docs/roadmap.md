# Roadmap (dev-side, detailed)

Long-form version of the roadmap section in [README.md](https://github.com/Delido/signalrgb-wallpaper/blob/main/README.md).
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

### ✅ Builder: Auto cut tool — shipped v0.9.16-beta, finalised v0.9.20-beta

✨ icon in the toolbox. Two modes share the same `clicks` storage
and replay path so undo / redo / refine-with-brushes work like any
other operation:

- **Auto saliency (instant)** — frequency-tuned saliency *(Achanta,
  Hemami, Estrada, Süsstrunk 2009, published academic algorithm)*.
  For each pixel: Euclidean colour distance from the image's mean
  RGB plus a brightness-above-mean premium; adaptive threshold.
  Pure JS, ~50 ms on a typical canvas, offline, no licence
  concerns. Strong on the neon / UI-overlay / glowing-edge case
  because those regions are precisely where colour deviates most
  from the image's overall palette.
- **Brightness (Otsu)** — Otsu's method on a luma histogram for
  cases where pure-brightness thresholding fits better.

Threshold slider biases the cutoff; Invert toggle flips the
mask. Rotation handler updates the stored mask in place so
*Rotate 90°* keeps the cut aligned with the canvas.

**Power-user opt-in**: setting
`localStorage["builder.aiEnabled"] = "1"` (or supplying a URL via
`["builder.aiModelUrl"]`) injects a third *Custom ONNX model* entry
into the dropdown that lazy-loads `onnxruntime-web` from jsDelivr
and runs the user's model. Hidden by default after the v0.9.16 →
v0.9.20 default-URL saga (RMBG-1.4 was non-commercial; subsequent
Apache-2.0 URLs either 404'd or referenced external-data files
ORT couldn't auto-resolve). Going classical for the default case
solved all three constraints — works offline, licence-clean,
zero download — in one shot.

### 🚧 Winget package + auto-update — auto-update finalised v0.9.19-beta

In-app auto-update is done. Tray entry *"⬇ Download + install
{tag}"* streams the installer into `%TEMP%`, spawns it via
`ShellExecuteW` (`/SILENT /SUPPRESSMSGBOXES /NORESTART`), then
`os._exit(0)`s. The installer has `CloseApplications=force` so it
kills the running bridge cleanly before overwriting
`SignalRGBBridge.exe`; the `[Run]` section relaunches the new exe
silently. Each step writes to `%TEMP%/signalrgb-update.log` for
post-mortem diagnosis. Progress shown via a small Tk window
during download.

Originally shipped v0.9.8 with `subprocess.Popen(...,
DETACHED_PROCESS)`; v0.9.17 swapped that for `ShellExecuteW`
after reports of the spawned installer dying with the parent;
v0.9.19 added `CloseApplications=force` after the
`/SUPPRESSMSGBOXES` plus `CloseApplications=yes` interaction was
found to deadlock the silent path (Inno waits on a user-confirm
dialog that's already been killed). Three-step debugging — kept the changes documented
in the changelog so future regressions in this area have a clear
diff to look at.

Still 🔲: Winget manifest submission to `microsoft/winget-pkgs` —
needs a PR through their submission flow + ongoing manifest
updates per release. Left as a manual task for the maintainer
when there's audience for it.

### 🚧 Ambient effects: port MIT-licensed CodePen pens — first batch v0.9.12-beta

v0.9.12-beta added **Constellation** + **Fireflies** ambient presets,
written from scratch in the project's own `AMBIENT_PRESETS` shape so
no per-pen licence verification was needed. Renderer learned an
optional `def.after(ctx, particles, tint)` post-pass hook for
effects that draw across the whole particle set (used by
Constellation's connecting lines).

Further direct ports from individual MIT-licensed CodePen pens
are an open menu — picked on visual fit (looks great as a
wallpaper backdrop, plays well with the live RGB glow), not on a
single author / catalogue. CodePen's default licence is MIT but
CodePen Pro users can override per-pen, so the licence MUST be
verified per pen before porting (the pen's *Settings → License*
field is authoritative).

Candidate effect types — useful as a search lens when browsing
CodePen, not a fixed shopping list:

- Particle drift / swarm / boids
- Geometric flow fields, wave fields
- Audio-reactive visualisers (would combine with our existing
  `lastAudio` FFT bins)
- Plasma / fluid / metaball blobs (in addition to the existing
  Plasma preset)
- Generative line art, vector noise fields
- Star-field / nebula / cosmic backdrops
- Matrix-rain style cascades
- Lightning / electric arcs
- Water ripples / pond-surface effects

Per-pen workflow (each port):

1. Confirm per-pen licence is MIT (or another permissive licence
   compatible with our MIT distribution). CodePen Pro accounts can
   override the default — check *Settings → License* on the pen.
2. Adapt to our `ambient` IIFE pattern: `#ambient-canvas` element,
   `targetCount` / `spawn` / `step` / `render` / optional `after`
   hooks matching the `AMBIENT_PRESETS` shape, start/stop based on
   user toggle, viewport-resize handler, tintFromGlow option.
3. Add an entry to `docs/credits.md` with: author, pen URL, licence,
   optional attribution string for the wallpaper credits / About
   dialog.
4. Add a per-file MIT notice comment block in the ported code.

If a pen's licence is non-permissive or unverified, the
alternative is what v0.9.12 and v0.9.15 did: write a fresh
implementation *inspired by* the visual style, in our own
`AMBIENT_PRESETS` shape, with no copied code. That's licence-free
by construction and was the right call for those five effects.

---

## 🎨 Post-v1.0 — Widget design system refresh

The v0.7 → v1.0 arc added widgets incrementally — each one got built
when the feature was needed, with its own one-off visual style. The
result is a set of eleven+ widgets that all *work*, but read as
disconnected: different paddings, different header treatments,
different background tints, different type scales, different glass
/ solid / outlined chromes. On a 4-monitor wall with 8-12 widgets
visible, that visual inconsistency is the dominant noise.

🚧 **Goal:** unify every widget into a single "tile" design system
so the wallpaper reads as one coherent UI surface rather than as
"a collection of independent gadgets glued onto a background".

### What "tile" means here

A reusable container shell every widget renders into. Properties
the shell owns (not the individual widget):

- **Background** — single source of truth for the tile's fill.
  Frosted-glass / acrylic look as the default (semi-transparent +
  blur), with a clear-glass and a solid-fill variant the user can
  pick per-tile or globally.
- **Border / corner radius** — uniform across every widget. Single
  CSS variable so the user can dial it from boxy to fully rounded.
- **Shadow / depth** — subtle drop shadow to lift the tile off the
  wallpaper without competing with the SignalRGB glow underneath.
- **Header bar** — optional, configurable per widget: icon + title
  on the left, action buttons on the right (settings, refresh,
  close). Consistent height + type size everywhere.
- **Padding + spacing tokens** — every widget uses the same scale
  (e.g. 8 / 12 / 16 / 24 px) so internal layouts line up across
  tiles when placed side by side.
- **Type scale** — three sizes top: title (header), primary
  (body / big numbers), secondary (labels / units). Picked once,
  applied everywhere.
- **Tint integration** — accent colour pulls from the live glow
  colour by default, so widgets visually belong to the wallpaper
  they sit on. User can override with a fixed accent.
- **Interaction states** — hover lift, drag-mode outline, snap
  guides — defined once, applied identically across every widget.

### What the widgets contribute

Each widget is then just the *body content* inside the shell:

- Clock — the time text
- Weather — temp / condition / forecast strip
- CPU/RAM meters — bars + percentages
- Now-playing — title + artist + progress bar
- Hardware sensor — sensor name + value + unit
- …

No widget owns its own border, background, padding, or header
chrome anymore. They all inherit from the shell.

### Implementation notes

- Shell component lives in `wallpaper/index.html` as a single CSS
  class (`.widget-tile`) plus optional modifier classes
  (`.widget-tile--glass`, `--solid`, `--clear`, `--no-header`).
- Each existing widget's CSS gets trimmed down to ONLY the
  content-layout rules — every container / border / background /
  padding line gets deleted and moved to the shell.
- Builder-side widget catalogue (Configurator) gets a single
  "Tile style" panel that controls the shell variant + accent
  source globally; per-widget overrides via right-click menu on
  a tile.
- Type tokens live in CSS custom properties at the wallpaper-page
  root so the user can A/B different scales without rebuilding.
- Drag-and-resize behaviour (interact.js) is already widget-level;
  the new shell wraps that without changing the drag API.

### Why this is post-v1.0 not pre-v1.0

A design-system refresh of this size touches every widget's CSS
plus the Configurator's preview canvas plus the Builder's
drag-overlay. That's the kind of change that bricks at least one
widget on the first iteration. Better done in a focused v1.1.x
cycle than as a last-minute v1.0 scramble. The widgets all work
correctly today — they just don't look like they belong to one
product yet.

Effort estimate: **~12-16 h** end-to-end (shell design + every
widget's CSS rewrite + Configurator integration + Builder preview
update + DE/EN strings for the new "Tile style" controls).

---

## 🧩 Post-v1.0 — Background Fit: add tile / repeat mode

The Background card's *Fit* dropdown currently offers three modes:
`cover (crop to fill)`, `contain (letterbox)`, `fill (stretch)`.
Missing the obvious fourth one: **tile** — repeat a small image
across the canvas as a pattern, the way browser-style backgrounds
do. Users with seamless / pattern wallpapers (carbon fibre,
hex grids, dot patterns, abstract textures, retro 90s tile art)
currently have no way to use those at their native scale.

### What gets added

Three new dropdown entries:

- **tile** — repeat the image in both X and Y. CSS:
  `background-repeat: repeat; background-size: auto;`
- **tile X** — repeat horizontally only, image fills the screen
  height (`background-repeat: repeat-x; background-size: auto 100%;`).
- **tile Y** — repeat vertically only, image fills the screen
  width (`background-repeat: repeat-y; background-size: 100% auto;`).

### Architecture

Current implementation uses `<img id="bg">` with `object-fit:
cover/contain/fill`. `object-fit` has no tile / repeat mode, so the
tile variants need CSS `background-image` on a `<div>` instead.

Two cleanest options:

1. **Single element, CSS-only:** swap `<img>` for `<div
   id="bg">` and drive everything via `background-image` +
   `background-size` + `background-repeat`. Same DOM count, same
   GPU cost, supports every existing mode plus the new ones.
   Affects the fade-on-load transition logic since `background-image`
   doesn't fire `load` events the way `<img>` does — would need
   to preload via `new Image()` then swap.
2. **Two-element hybrid:** keep `<img>` for cover/contain/fill,
   add a hidden `<div>` for tile modes, toggle visibility based
   on bgFit value. Lower regression risk on the existing modes,
   but doubles the DOM + makes the fade-on-load transition
   asymmetric.

Recommended: option 1, with a `new Image()` preload to keep the
fade-on-load UX from regressing.

### Per-tile scale (optional follow-up)

A second slider — *Tile scale* (10 % – 200 %) — lets the user
resize the pattern without re-uploading a different-sized source
image. Drives `background-size: <scale>% auto` for *tile X*,
`auto <scale>%` for *tile Y*, and `<scale>% <scale>%` for *tile*.

### Where it lives in the code

- `wallpaper_bridge/bridge.py` — `BG_FIT_CHOICES` (line 692ish);
  add `"tile"`, `"tile-x"`, `"tile-y"`. Defaults stay `"cover"`.
- `wallpaper_bridge/configurator.html` — three new `<option>` lines
  in the `bg-fit` `<select>`, three new i18n entries in
  `TRANSLATIONS` (en + de copy).
- `wallpaper_bridge/wallpaper/index.html` — `LIVELY_BG_FIT` array
  bump + the actual `applyBg()` style-application logic.
- `wallpaper_bridge/wallpaper/index.html` styles — swap
  `#bg { object-fit: ... }` for `#bg { background-size / background-repeat }`
  driven by data-attribute.

Effort estimate: **~2-3 h** for the three new modes + i18n + a
quick sanity test on all three; another **~1 h** if the per-tile
scale slider is included.

---

## 🔁 Post-v1.0 — Hot-reload wallpaper bundles after auto-update

The single biggest UX gap in the v1.1 auto-update flow: the bridge
updates itself cleanly via the tray, but Lively and Wallpaper
Engine **don't pick up the new wallpaper-page code** even though
the installer drops fresh bundle files into both hosts' folders.
Result — every beta that changes anything wallpaper-side requires
the user to manually delete + re-import bundles in Lively, or
unsubscribe + re-apply in WE. That's the dominant friction point
in real-world updates today.

### Why it doesn't auto-pick-up

- **Lively** extracts each imported ZIP **once** into a random-
  hash folder under `%LOCALAPPDATA%\Lively Wallpaper\…\<hash>\`.
  Updating the source ZIP doesn't propagate — Lively's library
  metadata points at the hash folder, not the original ZIP.
- **Wallpaper Engine** loads the project (`project.json` +
  `index.html` + assets) into memory **at first apply**.
  Subsequent edits to those files on disk are ignored until the
  wallpaper is re-applied or WE restarts.
- Tray → *Reload wallpaper pages* only does `location.reload()`
  on the currently-running page — same cached code reloaded,
  not a fresh fetch from `{app}\Lively wallpapers\`.

### What we'd add

#### Lively path

Lively's CLI exposes an `--import-from-zip <path>` (or similar)
command that triggers a fresh re-extract. Post-install hook in
the installer (or a tray action triggered post-update) would:

1. Read Lively's `LibraryView.json` to find existing
   *SignalRGB Glow – Screen N* entries
2. Delete each entry's hash folder + JSON record
3. Call `lively.exe --import-from-zip
   "{app}\Lively wallpapers\SignalRGB_Glow_ScreenN.zip"` for
   each screen
4. Re-assign via Lively's screen-targeting CLI
   (`--set-screen N`)

If Lively's CLI doesn't support all four steps, fall back to a
"Re-import wallpapers now" tray button that opens the
*Lively wallpapers* folder + a one-step instruction overlay.

#### Wallpaper Engine path

WE has no public CLI for project reload. Two options:

1. **Win32 IPC hack** — WE's main window accepts certain custom
   messages; sending a "reload current wallpaper" message via
   `SendMessageW` could work. Needs reverse-engineering against
   WE's current build, brittle across WE updates.
2. **Subscribe-bump trick** — touch the project's `version` field
   in `project.json` then call `wallpaperengine32.exe
   -openwallpaper <project>` which forces a reload. Requires WE
   to be running and accepting CLI commands.

Realistic v1 implementation: skip the Win32 hack, do the
subscribe-bump for users with WE already running, and fall back
to a clear toast saying *"WE wallpaper needs manual re-apply"*
with a button that opens *My Wallpapers* directly.

### Architecture

- New `installer/post-install-reload.ps1` script the installer's
  `[Run]` section invokes after copying files
- Tray entry *Re-import wallpaper bundles now…* under Advanced
  for users who want to trigger it manually
- Detection logic on first start after an upgrade: if the
  bundle's version timestamp inside the wallpaper page is older
  than the bridge's, toast "Bundles need re-import — click to
  fix" with a one-click trigger

### Effort estimate

| Block | Time |
| --- | --- |
| Lively LibraryView + hash-folder cleanup logic | 1.5 h |
| Lively CLI re-import invocation + screen targeting | 1.5 h |
| WE subscribe-bump + fallback toast | 1 h |
| Tray entry + first-start version-mismatch detection | 1 h |
| Cross-host testing + edge cases (Lively portable build, MSIX, WE-not-running) | 1.5 h |
| **Total** | **~6-7 h** |

### Why it's worth doing now (before stable)

This is the single highest-ROI follow-up to the auto-update
work itself. Right now the tray's "Download + install update"
button is half a feature — bridge updates work, wallpaper code
updates don't. Closing that gap is what makes auto-update
*actually useful* for the wallpaper-page changes we keep
shipping.

---

## 🔌 Tier 4 — Ecosystem / integration (post-v1.0)

Not a single user need; broader API + plugin work. Lower priority
unless a community / power-user request comes in. Deferred past
v1.0 — the v0.7 → v1.0 arc was about getting the single-user
experience rock-solid; integration is the next layer up.

### ✅ LED ecosystem hub — shipped v1.4.0-beta + v1.5.0-beta

The single-source / single-output colour pipeline got opened up
into a full switchboard. Three input strategies feed the
broadcaster, two output strategies fan out from it, all running
off the same averaged colour stream so a single SignalRGB
effect can drive wallpaper + OpenRGB hardware + DMX lighting in
sync. Closes the long-standing "sACN/E1.31 outbound" Tier 4
item below — kept here for the architectural notes; the
**original 🔲 entry was the seed for what eventually shipped as
the multi-source bridge architecture, not just an emitter**.

**v1.4.0-beta — OpenRGB output channel:**

- Custom MIT-safe OpenRGB SDK client
  (`wallpaper_bridge/openrgb_client.py`, pure stdlib — no
  openrgb-python GPL bundling)
- `OpenRgbOutputManager` daemon thread, reconnect-with-backoff,
  30 Hz push loop
- Broadcaster frame-tap registry — reusable hook reserved for
  the sACN emitter below (and any future output)
- Configurator: enable + host/port + source-screen, live status
  pill with device list

**v1.5.0-beta — sources hub + sACN output + spatial mapping:**

- **SourceManager** routing layer: per-screen colour source
  picker (SignalRGB UDP / OpenRGB poll / sACN multicast).
  Default unchanged — every screen starts on SignalRGB. Polled
  sources synthesise SR-format frames via
  `flat_color_to_sr_frame()` so downstream code (broadcaster,
  wallpaper page) doesn't need to care that the frame didn't
  originate from UDP.
- **OpenRGB input**: `OpenRgbInputManager` polls a chosen device's
  LEDs via the same SDK client (`get_colors()` was added as a
  companion to `push_color()`), averages, emits.
- **sACN/E1.31 input**: `SacnInputManager` joins the multicast
  groups for configured universes, parses DMX, picks (R, G, B)
  from the first 3 channels of each universe.
- **sACN/E1.31 output emitter**: parallel to OpenRGB output,
  registered as a frame-tap. 30 Hz, configurable multicast /
  unicast, priority 0–200, per-screen universe assignment.
- **`sacn_codec.py`**: stdlib-only ANSI E1.31 pack/parse,
  round-trip tested. Shared by input + output managers.
- **Spatial mapping for OpenRGB output**: each device has a
  normalised (x, y) position; bridge samples the live grid at
  that point instead of averaging. Configurator has a draggable
  live-preview canvas (480×270, WS-subscribed to the source
  screen) — drag a marker to move where the device samples
  from. Backward-compat: any device without a mapping defaults
  to (0.5, 0.5) which matches v1.4's averaged behaviour on
  uniform effects.

OpenRGB SDK parser took five iterations to stabilise on real
hardware (OpenRGB 1.0rc2 + ASUS GPU + E1.31 plugin) — see
the v1.5.0-beta hotfix commits:

1. `5b0b924` — mode-struct size 44 → 48 bytes for protocol 3+
2. `f1ce581` — `min(client, server)` handshake; length-prefixed
   strings, not null-terminated
3. `3c4ee2e` — vendor string field added in protocol 1+
4. `23a9f2e` / `a350da1` — split socket-broken from 0-LED on
   both push (output) and get_colors (input) paths
5. `289bc8d` — Configurator JS scope fix on the spatial-mapping
   visibility flip

**Caveat (worth documenting for users):** OpenRGB devices in a
hardware-effect mode (firmware-driven Rainbow / Static / etc.)
do NOT expose their live frame over the SDK. The colours
returned by `REQUEST_CONTROLLER_DATA` only reflect the last
SDK-set state. For OpenRGB-as-source to actually mirror what
the GPU shows, the device must be in **Direct mode** with some
software-side effect engine (e.g. the OpenRGB Effect Engine
plugin) pushing frames the bridge can then read. This is an
architectural property of the OpenRGB SDK, not a bridge bug.

#### Follow-ups (not yet started)

- **Strip mapping** (Phase C from the v1.5 plan, ~3-4 h):
  multi-LED devices (RAM, strips, keyboard rows) get a *line*
  on the preview from (x1, y1) to (x2, y2) instead of a single
  point — each LED samples its position along the line. Lets a
  RAM stick show a horizontal gradient matching the wallpaper.
- **Multi-source mDNS/SSDP discovery** for sACN receivers — the
  current setup is "type the universe number in" which is fine
  for power users but high friction for first-timers.

### 🔁 Historical: sACN / E1.31 outbound — original Tier-4 planning notes

Kept below for the architectural commentary; the feature itself
shipped above. The original scope was "outbound emitter only";
the v1.5 implementation went broader (full sources/outputs hub)
because once SourceManager existed, adding the inbound path was
cheap and parallel.

#### What gets added

- A new bridge module that reads the same per-frame colour grid
  the WebSocket fans get, packs it into 512-channel sACN universes,
  and emits UDP-multicast packets on `239.255.0.x` (or unicast
  to a configured IP).
- Configurator UI for per-output config: destination universe
  number(s), start-channel offset, priority field (0-200), unicast
  target IP, source-name string, pixel-mapping mode
  (linear / snake / boustrophedon).
- Disabled by default — zero overhead until the user opts in.

#### Architecture

- New optional thread on the bridge side, parallel to the
  existing HwMon poller / sysstats pusher.
- Reads the same `latest_frame_by_screen` colour buffer the
  WebSocket broadcaster already maintains — no protocol changes
  needed upstream.
- Pure-Python sACN emit (`sacn` / `python-sacn` library, MIT).
  UDP-only, no extra deps.
- Per-screen device config in `config.json` under a new
  `sacnOutputs` key — list of `{screen, universeStart, channelMap,
  destIp, priority}` entries.
- Pixel mapping: SignalRGB devices are 2D grids (128×128 by
  default), sACN universes are linear 512-channel arrays. Map
  via pre-set patterns the LED community recognises (linear,
  snake, boustrophedon — same names xLights uses).

#### Effort estimate

| Block | Time |
| --- | --- |
| Core sACN emit + universe mapping | 6-10 h |
| Configurator UI (universe / channel / priority / dest IP) | 3-4 h |
| Multi-screen routing + per-device mapping | 4-6 h |
| Testing against WLED + FPP + xLights | 3-5 h |
| Docs + sample configs (WLED quick-start) | 2 h |
| **Total** | **~18-27 h** |

#### Tradeoffs

- **Network complexity** — multicast can be blocked across
  VLANs; need a clear interface-picker + a "test packet" button
  in the Configurator for diagnosis. mDNS / SSDP discovery is a
  potential phase-2.
- **Pixel-mapping confusion** — different LED setups expect
  different pixel orderings. Need preset mappings + a visual
  preview in the Configurator so the user can verify before
  committing.
- **Latency budget** — 60 fps × ~96 universes per screen × 638
  bytes per packet ≈ 6 Mb/s on a 4-screen rig. Comfortably
  inside any local LAN; need batched emit per frame so we don't
  miss frame deadlines.
- **No auth** — sACN protocol has none, relies on network
  isolation. Document clearly that this is a LAN feature; the
  bridge should refuse to bind to a routable interface unless
  the user explicitly opts in.

#### Why this lands ahead of the other Tier 4 items

Most Tier 4 items (HA / MQTT, REST API, Plugin API, Generic HTTP
widget) extend reach within power-user niches that already know
about us. sACN extends reach into a **completely separate
community** (DIY-LED, holiday-lights, ambient-lighting builders)
that doesn't currently know SignalRGB exists. The work is also
better-scoped (single protocol, well-documented spec) than the
REST API formalisation that the other Tier 4 items depend on.

### ✅ Home Assistant / MQTT bridge — shipped v1.5.0-beta

`wallpaper_bridge/mqtt_client.py` is a ~400-LOC custom MQTT 3.1.1
client (no paho-mqtt dep so the bridge keeps its MIT distribution
clean). `MqttBridge` in `bridge.py` publishes per-screen state
under a configurable topic prefix (default `signalrgb-wallpaper`)
and subscribes to `*/set` topics for control. Frame-tap-driven
glow colour publish. Will-message on `<prefix>/bridge/online` so
HA shows the bridge as unavailable when offline.

Also publishes **MQTT Discovery** payloads under
`<discoveryPrefix>/.../config` (default `homeassistant`) so HA's
MQTT integration auto-creates one device card with N × 4
entities per screen: preset select, pause switch, glow + bg
sensors. Configurable via the new Configurator System sub-section.

### ✅ REST API (formalised) — shipped v1.5.0-beta

`/api/v1/*` surface: info, screens, settings, preset/apply,
pause, profiles, plugins, sacn/discovered, mqtt/status,
auth/verify. Hand-written OpenAPI 3.1 spec at
`/api/openapi.json`. Human-readable companion in
[docs/api.md](api.md) with curl examples, Stream Deck recipe,
HA `rest_command` snippet.

Auth: per-install `apiToken` auto-generated in `config.json`,
shown + regenerable in the Configurator's System card. Loopback
requests bypass (Configurator + same-host integrations work
without configuration); remote requests need
`Authorization: Bearer <apiToken>`. Token UI: hidden by default
(`<input type="password">` with bullet placeholder), press-to-show
button, and a Bitwarden-style **Copy & forget** that auto-clears
the clipboard ~30 s later.

### ✅ Plugin API for third-party widgets — shipped v1.5.0-beta

`PluginRegistry` scans `%LOCALAPPDATA%\SignalRGBWallpaper\plugins\
<name>\` on startup + on demand for `manifest.json` files. Each
discovered plugin becomes a `plugin/<name>` widget type, served
via `/plugins/<name>/<asset>` with sandboxed path resolution
(refuses traversal) and a strict CSP header. Wallpaper page
renders instances into `sandbox="allow-scripts"` iframes; the
postMessage protocol (`{init, tint, opts}` outbound,
`{log}` inbound) is the only IPC channel.

Full author contract documented in
[docs/plugin-api.md](plugin-api.md) with a hello-world example
that a maintainer can drop into the plugins folder + see live
in <10 lines.

### ✅ Generic HTTP widget — shipped v1.5.0-beta

New `http` widget type. URL + refresh interval + mustache-
flavoured template (`{{path.to.field}}` substitutions). JSON
auto-parsed, falls back to text. Tint-from-glow option. Custom
50-LOC mustache reader, no JS library bundled.

Fetch runs from the wallpaper page (same path as the existing
RSS widget) — no bridge proxy, so the target's CORS + cache
headers apply directly. Covers Discord-unread / stock-ticker /
crypto-price / RSS-headline / arbitrary REST APIs with ONE
widget instead of one per service.

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
