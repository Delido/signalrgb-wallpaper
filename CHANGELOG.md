# Changelog

All notable changes to **SignalRGB Desktop Wallpaper** are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.16-beta] - 2026-05-26

> Quick Looks ließen pre-Bundle Widgets manchmal mit-leben + die
> Auto-Snapshot griff den falschen State. Plus ein 404-Fix für den
> "Load current background" Pfad auf Screens deren bgImage auf eine
> gelöschte Datei zeigt.

### Fixed — Quick Looks left widgets from the previous bundle alive

Pre-v1.2.16 `applyLookBundle` sent each operation (snapshot,
per-setting update × N, widget-remove × M, widget-add × K) as its
own WS message. The bridge's `_on_widget_command` spawns a worker
thread per message — so all those mutations raced for the
`config_lock` in non-deterministic order. Two symptoms users hit:

- Pre-Look widgets sometimes survived the apply (the bundle's
  widget-add fired before the previous widget-remove had finished).
- The auto-snapshot to preset slot 1 sometimes captured POST-Look
  state instead of PRE-Look (the snapshot thread won the lock
  AFTER some setting-update threads had already mutated).

v1.2.16 introduces a single `quick-look-apply` bridge command that
wraps snapshot → non-widget settings → widget array replace in ONE
`_mutate_screen` call under one lock acquire. No race.

Also adds a sibling `widgets-set` command for any future code path
that needs an atomic widget-array replace (preset apply, future
import-bundle, etc.).

### Fixed — "Load current background" 404 left bgImage stuck

If a screen's `bgImage` referenced a file that no longer existed
on disk (manual cleanup, OneDrive sync glitch, etc.), the Builder's
"Load current background" tile-menu action hit a 404 on the
`/image` proxy and surfaced "Loading current background failed:
HTTP 404" — useful for diagnosis but not a fix. v1.2.16 detects the
404 specifically, surfaces a clear "Background file no longer
exists on disk — cleared the stale reference" toast, and POSTs
`bgImage: ""` to the screen settings so the config self-heals.

### Other

- Bridge: `replace_widgets()` helper for the standalone
  `widgets-set` command + the inline replacement inside
  `quick_look_apply`. Each entry's id is server-assigned via the
  per-screen `_widgetIdSeq` counter so client-side ID collisions
  can't happen.
- `quick_look_apply` skips `widgets` / `mirrorOf` / `cycle` from its
  settings dict — `widgets` is handled by the same call's atomic
  replace, the other two need their own special-case dispatch paths.

---

## [1.2.15-beta] - 2026-05-26

> v1.2.14 hotfix — Diagnose-Paket landete im falschen Ordner für
> OneDrive-Setups + war silent ohne sichtbares Feedback.

### Fixed — Diagnose-Paket Export auf OneDrive-Setups

`Path.home() / "Desktop"` schreibt auf OneDrive-synced Accounts in
einen Schatten-Ordner den der User nie öffnet — der echte Desktop
liegt unter `~/OneDrive/Desktop` (oder dem registry-konfigurierten
Pfad). Neuer `_resolve_desktop_path()` Helper liest erst die
Windows Shell-Folders Registry, fällt dann auf `OneDrive/Desktop`,
dann auf `~/Desktop`, dann auf Home zurück. Funktioniert auf
Standard- + OneDrive- + Unternehmens-Redirect-Setups.

### Added — Diagnose-Export öffnet Explorer mit Datei pre-selected

Nach dem Schreiben wird `explorer.exe /select,<path>` aufgerufen
damit die ZIP-Datei im Explorer hervorgehoben angezeigt wird. Tray-
Balloon konnte man leicht übersehen; ein offenes Explorer-Fenster
mit selektierter Datei ist eindeutig. Tray-Notification zeigt jetzt
auch den vollen Pfad statt nur den Dateinamen.

---

## [1.2.14-beta] - 2026-05-26

> Second audit pass — 9 items from the v1.2.13 review list land in
> this beta. Three new Quick Look bundles, an in-Builder reference-
> image colour picker, a one-click diagnostics export, full keyboard
> navigation on the wall tiles, and a WebSocket reconnect backoff
> that stops the wallpaper page from hammering a downed bridge.

### Added — Pick colour from reference image (Builder)

New "Pick from reference image…" button under the Click-pixel tool's
options. Loads any image into a modal at native resolution, hovering
over it previews the colour as both a swatch + an RGB / hex string,
clicking sends that colour back through the same tolerance-based
remove path the canvas click uses. The reference stays in memory
until "Clear ref" so users can keep popping it open while iterating
on the source. Useful for "I want to cut everything matching the
neon-cyan in this other wallpaper" workflows that previously needed
GIMP / Photoshop.

### Added — Auto-Cut hotkey (Ctrl+Shift+A)

Long-standing UX gap: running Auto-Cut on the current canvas required
selecting the AI tool from the toolbox + clicking "Run auto cut" — 3
actions for the single most-used Builder operation. v1.2.14 binds
Ctrl+Shift+A to fire the AI panel's Run button directly. Works from
any tool context as long as `originalData` is loaded and the run
button isn't already busy with a previous run.

### Added — Auto-snapshot before Quick Look apply

`applyLookBundle` now saves the screen's current state to preset
slot 1 before pushing the bundle. Users who try a Look and don't
like it can revert in 1 click via the Presets section instead of
losing whatever they had configured. Slot 1 is overwritten — same
trade-off as any other autosave.

### Added — Three new Quick Look bundles

- **Stream Overlay** — Transparent tiles, now-playing pinned
  bottom-left, clock top-right, audio spectrum strip across the
  bottom. For OBS scenes that already have alpha.
- **Pomodoro** — 25-minute countdown, sticky note with the
  technique recap, quote of the day for context-shifts between
  rounds.
- **Minimal Calendar** — Big analog clock + tall calendar, no
  effects, no glow. For users who want the wallpaper to *be* the
  calendar.

### Added — Diagnostics export (Tray → Advanced)

New "Export diagnostics bundle…" entry under the tray's Advanced
submenu. Packages the current config.json, library.json, summary
metadata (app version, Python version, install paths) and the last
re-import log into a single ZIP on the user's Desktop. For bug
reports that previously needed five round-trips of "paste your
config / paste your log / which version".

### Added — Keyboard navigation for Wall tiles (Builder)

Every wall tile now has `role="button"` + `tabindex="0"` so Tab
walks through them and Enter / Space opens the action menu. Delete
/ Backspace clears a filled slot for quick muscle-memory wipes.
Visible focus ring (accent-blue outline) so screen-reader and
keyboard-only users can see where focus landed. `aria-label` on
each tile reads "Monitor N (WxH) — image staged / empty".

### Added — Configurator narrow-viewport stylesheet

New `@media (max-width: 720px)` block. Tab row scrolls horizontally
instead of overflowing, section-card row labels stack above their
controls, the screen popover caps to viewport width, and the header
shrinks. The Configurator stays usable on a tablet / phone-landscape
even though the desktop is the primary target.

### Fixed — WebSocket reconnect storm on downed bridge

Pre-v1.2.14 every wallpaper page polled `ws://127.0.0.1:17320/`
every 1500 ms while the bridge was down — at 4 screens that's ~3
attempts/sec banging into a dead port. v1.2.14 adds exponential
backoff: 1.5 s → 3 s → 6 s → 12 s → 24 s → capped at 30 s. A
successful `ws.onopen` resets to the floor so a quick bridge
restart doesn't penalise the next disconnect. The disconnect
status line now also shows the next retry delay so users can tell
the page hasn't given up.

### Fixed — Auto-cycle could overwrite a manual background upload

`_update_background` now bumps the cycle's `lastApplyMs` to "now"
whenever a manual upload lands. Before v1.2.14, uploading a custom
background to a cycle-enabled screen would get silently rolled back
on the next CycleScheduler tick (~10 min default). Now the cycle
waits the full intervalMin after a manual override before
considering a switch.

### Other

- New i18n keys: `wall.tile_aria`, `wall.tile_filled`,
  `wall.tile_empty`, `opt.ref_pick`, `opt.ref_clear`,
  `ref_pick.title`, `ref_pick.close`, `ref_pick.hint`,
  `ref_pick.loaded`, `ref_pick.applied`, `looks.autosnapshot`,
  `tray.export_diagnostics`, `diagnostics.done`,
  `diagnostics.failed`.
- "Apply background to all screens" was flagged in the v1.2.13 audit
  but verified to already work via the existing `apply-all` button
  on the Background card (bgImage is in `SECTION_KEYS["card-bg"].keys`).

---

## [1.2.13-beta] - 2026-05-26

> Sweep through the audit list: 14 of the 22 reported issues fixed,
> 5 either non-bugs (`save_config` was already atomic, dead code was
> already gone, etc.) or accepted trade-offs documented in place, and
> 3 mid-priority items batched for a future release.

### Fixed — `add_widget` ID collisions on Quick Looks bursts

`f"w_{ms % 10_000_000}_{len(existing)}"` could collide when two
screens rapid-added widgets in the same millisecond with the same
prior count — a real risk during a Quick Looks apply, which adds
4-5 widgets in tight succession to the same screen. Replaced with
a per-screen monotonic counter persisted in
`config["screens"][n]["_widgetIdSeq"]`. IDs read `w_s<screen>_<n>`
now and stay collision-free across screens + restarts.

### Fixed — Builder `renderWall` could yank a dragged free-form tile

The 3 s `/config` poll triggers `renderWall()` which wipes
`wall-canvas.innerHTML` and rebuilds every frame. If the user was
mid-drag in free-form layout, the rebuild dropped the dragged
frame into a new DOM node and the drag died. A shared
`_wallFrameDragActive` flag gates the re-render — `mouseup`
triggers a clean render once the drag finishes via
`saveWallPositions → renderWall`, so we never miss a paint.

### Fixed — Edit re-opens compounded letterbox transparency

v1.2.8 contain-fitted the source image into a target-sized canvas
on edit open. Saving back stored the *fitted* canvas as the slot's
image, so a second edit fit again — letterbox baked into letterbox.
Slots now carry a pristine `origImg` / `origBlob` alongside the
working `img`; `editWallSlot` fits from `origImg` so the fit math
always starts from the original source.

### Fixed — `applyWall` stretched source images to slot dimensions

Pre-v1.2.13 the composite stamp used a plain
`drawImage(img, x, y, w, h)` which stretches the source to fit
regardless of aspect. A 21:9 source landed in a 16:9 slot squashed
horizontally. v1.2.13 cover-fits each tile into its slot (centre-
crop on one axis to make the other fill), matching the wallpaper
page's default background contract. Portrait-tile rotation math
follows along.

### Fixed — RSS widget accepted non-http(s) feed URLs

`fetch(feedUrl)` was called without protocol validation. Browsers
generally reject `javascript:` / `data:` / `file:` URLs in
`fetch()`, but relying on CEF-version-specific behaviour was a
weak defence. v1.2.13 validates with `new URL(s)` + an explicit
`http:` / `https:` allowlist before issuing the request; failures
surface in the widget footer instead of silently retrying.

### Fixed — `/screen/<N>/background` accepted arbitrary bytes

The HTTP POST handler only checked `Content-Type` and size, not
the actual payload bytes. v1.2.13 magic-byte-sniffs PNG / JPEG /
WebP / GIF / WebM / ISO-BMFF (MP4/MOV/M4V) before persisting and
rejects everything else with a 400, mirroring the existing
`/library/upload` validation.

### Fixed — Stale `bgImage` paths survived in config across cleanups

If the user manually emptied the `screens/` folder (or restored
from a backup that didn't include the PNGs), `bgImage` paths in
the config kept pointing into the void. `load_config` now drops
`bgImage` entries whose file no longer exists on disk so the
wallpaper page doesn't keep retrying a phantom URL.

### Fixed — Monitor-Setup couldn't be edited on a mirror screen

`update_screen_setting` blocks mutations on mirror screens to
prevent drift from the source. But `monitorSetup` is in
`_NON_MIRRORED_KEYS` — it describes physical hardware, not display
config, so a mirror screen should still own its layout
declaration. v1.2.13 exempts `monitorSetup` from the mirror block.

### Fixed — Builder `/config` poll could race on rapid tab toggle

`visibilitychange` + 3 s interval can fire two `loadWallViewports`
calls before either completes. Without an `AbortController` the
fetches race and whichever resolved last wins, not whichever was
freshest. New `_wallViewportsAbort` cancels the previous in-flight
fetch before issuing a new one.

### Fixed — Cyberpunk Streamer clock got squashed by the header

The bundle's 200×200 clock had `showHeader: true`. The 26 px
header strip squashed the analog face to a 200×174 oval. Header
off, circle round.

### Removed — Dead Span-canvas code in the Builder

`spanCanvasAcrossWall` + `updateWallSpanState` + their `els`
references never had a UI surface post-v1.2.7 (the Span button
was removed then). Cleaned out.

### Removed — Legacy `.screen-popover-trigger` CSS + element ref

The single shared "Screen settings" gear was replaced by a per-tab
gear in v1.2.10. The CSS block + the `els.screenPopoverTrigger`
fallback in `showScreenPopover` were retained as backstops; both
gone in this cleanup.

### Removed — Orphan `tray.preset_hotkeys` i18n key

The matching tray menu entry was migrated into the Configurator's
System section in v1.2.2 but the string stayed behind.

### Other

- `save_config` audit-flagged as non-atomic — verified to already
  use the temp-file + `replace()` pattern, false positive.
- `_update_background` file delete batched audit-flagged for
  `asyncio.to_thread` offloading. Left synchronous; the
  thread-pool overhead would cost more than the typical few-ms
  loop block for a handful of stale PNG deletes.
- `setSetting` optimistic-update rollback audit-flagged. The WS
  echo from the bridge's `push_settings` is the existing
  rollback signal — a rejected write gets corrected on the next
  echo automatically. No code change needed.

---

## [1.2.12-beta] - 2026-05-26

> Quick Looks no longer overwrite the user's background, dead bg keys
> dropped from every bundle, and the Gaming bundle's meters moved off
> the off-screen x=1700 anchor.

### Changed — Quick Looks keep the current background

`applyLookBundle` now filters out `bgImage` / `bgImageUrl` / `bgFit` /
`bgDim` / `bgTileScale` from the bundle's settings push. A bundle is
a *look* — effects, glow, tile style, widget layout — not a
wallpaper-swapper. Users who imported a custom background no longer
lose it by trying a different Look. The matching keys were dropped
from every bundle definition too so they don't show up as dead
clutter in source.

### Fixed — Gaming bundle meters were off-screen on sub-1920 setups

CPU / RAM / hardware-sensor widgets used `x: 1700` which assumes a
1920-wide monitor. On a 1280×720 screen the row would render
entirely outside the visible area; on a portrait monitor it was
hopelessly off-canvas. Moved to `x: 50` (top-left corner of the
useable area) — users on wider screens can drag the row right via
the unlock-and-edit flow; the bundle's job is to land somewhere
visible on every screen.

### Other

- Cyberpunk Streamer bundle dropped its `bgImage:
  "cyberpunk-skyline.png"` reference — there's no such file shipped
  with the bridge, so the entry was always dead.
- Bundle descriptions updated to drop "dark background" framing
  since the bundles no longer touch the background.

---

## [1.2.11-beta] - 2026-05-26

> Tiny follow-up: Undo / Redo buttons surface in Simple mode again.

### Changed — Undo / Redo visible in Simple mode

The History `<section>` was wholesale `simple-hide`'d in v1.2.3
when Simple mode shipped, which silently hid Undo / Redo too —
users running an Auto-Cut they didn't like had no escape hatch
besides reloading the slot. v1.2.11 keeps the Undo / Redo row
visible in Simple mode while leaving the per-step History list +
"Reset all edits" hidden (those are geared at the multi-step
brush edits the Simple flow doesn't surface anyway).

---

## [1.2.10-beta] - 2026-05-26

> Three fixes from the v1.2.9 test pass. The big one is on the bridge:
> `/config` was hand-building the per-screen dicts without
> `monitorSetup`, so Configurator-side span changes never reached the
> Builder. Plus a click-behavior change on the Wall tiles to surface
> the action menu more discoverably, and the single shared "Screen
> settings" gear becomes a per-tab gear so each monitor has its own
> clearly-belonging entry.

### Fixed — /config didn't pass through monitorSetup

The Builder reads `/config` instead of subscribing to WS settings
pushes (it has no persistent socket). The /config handler was
constructing each `screens[i]` dict with only `viewportW`,
`viewportH`, `bgImage`, and `mirrorOf` — `monitorSetup` was
silently dropped. So Configurator-side "set Screen 1 to 2 H span"
updates were correctly persisted by the bridge + visible to the
Configurator (it uses WS), but the Builder never saw them and
kept rendering everything as single-mode.

`/config` now includes `monitorSetup` (with a safe default fallback
if the screen has none) so the Builder's poll picks up Configurator
edits within its 3 s cadence + the visibilitychange tab-focus
refresh.

### Changed — Wall tile click opens the context menu

Pre-v1.2.10 a tile click jumped to a default action:

- Empty tile → file picker
- Filled tile → edit-in-canvas

That hid the menu's other entries — most users wouldn't think to
right-click to discover "Load current background", "Use current
canvas", "From library", "Clear". v1.2.10 makes every tile click
open the context menu so all options are one click away from
discovery. Right-click still works as a synonym for muscle memory.

### Changed — Per-tab settings gear instead of one shared trigger

The single "Screen settings" gear at the end of the tab row only
ever operated on the active screen, but it didn't visually belong
to any specific tab. v1.2.10 renders one gear per tab, sibling to
each tab button. Click switches to that tab + opens the popover
anchored under that gear. Inactive gears hide in lockstep with
their tab's `inactive` class, and the gear lights up in accent
colour when its screen is mirroring (was the old shared
trigger's job).

The legacy `.screen-popover-trigger` element is no longer rendered
and is force-hidden via CSS as a defensive backstop.

### Other

- `showScreenPopover()` now takes an optional `anchorEl` argument
  so the popover position follows whichever gear was clicked,
  not a hard-coded singleton.
- Outside-click listener now treats clicks on any `.tab-gear` as
  in-popover so opening the popover from a different tab doesn't
  close-and-reopen.
- Tab label moved into an inner `.tab-text` span so per-tab
  badges (mirror indicator) survive label refreshes from the
  `/config` poll.

---

## [1.2.9-beta] - 2026-05-26

> Two complaints from the v1.2.8 test pass — the Builder didn't pick
> up Configurator-side Monitor-Setup changes for up to 10 seconds, and
> the span configuration UI felt opaque (a dropdown labelled "2 — H
> span" + cryptic ▭/▯ chips). v1.2.9 fixes both: Builder polls 3× more
> often + refreshes on tab focus, and the Monitor-Setup popover
> becomes a visual layout picker with labelled monitor-shape buttons.

### Fixed — Builder didn't reflect Configurator changes promptly

The Builder is HTTP-only (no persistent WS), so it picks up
`monitorSetup` updates via the `/config` poll. The poll interval
was 10 s, which meant "edit setup in Configurator → switch back
to Builder tab" left the user staring at a stale layout long
enough to assume the change hadn't applied.

- Poll interval dropped 10 s → 3 s.
- New `visibilitychange` listener forces an immediate
  `loadWallViewports()` on tab focus. Covers the common
  "Configurator → Builder" tab switch with zero perceptible lag
  even without waiting for the next poll tick.

### Changed — Monitor-Setup popover is now a visual layout picker

The mode dropdown (`1 monitor` / `2 — H span` / `2 — V span`)
plus the chip toggles (`▭` / `▯`) read like API parameters, not
UI. v1.2.9 replaces both with:

- **Three layout cards**: each shows a literal mini-mock of the
  resulting tile layout — one rectangle for single, two
  side-by-side for span-h, two stacked for span-v. Click a card
  to pick. The active card highlights with the accent colour.
- **Per-monitor rotation buttons** (visible only when a split
  layout is active): each is a labelled monitor pictogram that
  transitions between landscape (28 × 16 px rect) and portrait
  (16 × 24 px rect) on click. The user sees the physical shape
  they're declaring, not a chip.

Copy is friendlier too: "2 side by side" / "2 stacked" instead
of "2 — H span" / "2 — V span", and the rotation buttons read
"Monitor 1 · landscape" / "Monitor 2 · portrait" instead of
just `▭` / `▯`.

### Other

- New i18n keys: `setup.orient.landscape`, `setup.orient.portrait`,
  `setup.layout.single`, `setup.layout.side_by_side`,
  `setup.layout.stacked`, `setup.rotate.btn`.
- Popover row layout: new `.pop-row-block` modifier stacks the
  label above the picker grid so the layout cards have room to
  breathe at 320 px popover width.

---

## [1.2.8-beta] - 2026-05-26

> Monitor-Setup moves to the bridge config — single source of truth
> shared between Configurator + Builder. Builder edit canvas now sizes
> to the target monitor's resolution so under-sized images can be
> positioned with intent. New tile-menu entry pulls the screen's
> currently-applied background into a slot for tweaking. Plus a fix
> for the silent Apply failures on the 2nd bridge screen.

### Added — Monitor-Setup persists in bridge config

The per-screen `monitorSetup = {mode, orientations[]}` field moves
from Builder's localStorage into `bridge.config["screens"][N]
["monitorSetup"]`. Bridge sanitises every incoming payload (unknown
modes coerce to `single`, orientations clipped to tile-count,
single-mode forced to `landscape`). Mirror-screens skip the
replication because monitorSetup describes physical hardware, not
display config.

### Added — Monitor-Setup picker in the Configurator screen-popover

Per-screen layout + orientation now editable from the same popover
that hosts Mirror and Reset. Mode select (`1 monitor` / `2 H span` /
`2 V span`) plus a ▭/▯ chip per sub-tile when a span mode is
picked. Writes go through `setting-update` like every other per-
screen field, so every connected client (Configurator + Builder)
re-renders on the WS echo.

### Changed — Builder Monitor-Setup section is now read-only

The Builder's Monitor-Setup rows render the active mode +
orientation summary + a tile preview, but the inline editors are
gone. A "→ Edit the layout in the Configurator's screen settings
popover" link points users to the canonical editor so two clients
can't race on writes. The old `signalrgb.builder.monitor_setup`
localStorage key is wiped on first v1.2.8 load.

### Added — "Load this screen's current background" tile menu entry

New row in the wall-tile right-click menu. Fetches the bridge
screen's currently-applied `bgImage` via the existing `/image`
proxy, drops it into the slot, and opens it in the in-place edit
flow. Disabled when the screen has no current background.
Replaces the manual "open file picker → navigate to screens dir
→ pick file" chain users wouldn't think to try.

### Added — Edit canvas matches target monitor resolution

`editWallSlot()` now opens the Builder canvas at the tile's
target W×H (with portrait swap if applicable). Under-sized images
are contain-fitted into the canvas (centred, no upscale,
transparent letterbox) so pixel-accurate edits map 1:1 to the
physical monitor. The user sees their image with the correct
target aspect ratio + has room to reposition / paint around it
via the existing brushes.

### Fixed — Apply silently dropped on the 2nd bridge screen

The Builder's `applyWall` checked HTTP status only. The bridge
always responds 200 OK even when the actual file write failed
(mirror block, lock contention, disk error) — it just sets
`ok:false` in the JSON body. v1.2.8 parses that body and treats
`ok:false` as a per-bridge failure with a clear error in the
toast + console.log. Adds a 60 ms breather between consecutive
POSTs as insurance against any timing weirdness on the bridge
side. Per-bridge status is now logged to the browser console for
easier diagnosis.

### Other

- New i18n keys: `setup.label`, `setup.popover_hint`,
  `setup.orient.label`, `setup.edit_in_configurator`,
  `wall.menu.currentbg`, `wall.currentbg.none`,
  `wall.currentbg.failed`.
- `_NON_MIRRORED_KEYS` extended with `monitorSetup` so mirrors keep
  their own physical-layout declaration.
- `_sanitise_monitor_setup()` validates incoming payloads end-to-
  end so a malformed Configurator send can't poison the persisted
  config.
- `wall.menu.currentbg` button disables when the owning bridge
  screen has no current background.

---

## [1.2.7-beta] - 2026-05-26

> Builder Monitor-Setup cleanup pass. Fixes the bug where a stuck
> portrait-orientation flag from a previous span edit made every
> single-mode screen render as portrait too. Drops the now-pointless
> "Bildschirme" override picker and the "⇔ Canvas spannen" button
> entirely, and renames "Bridge N" → "Screen N" so the labels match
> what Lively / Wallpaper Engine actually call them.

### Fixed — Single-mode tiles inherited a leftover portrait flag

Before v1.2.7 the per-sub-tile orientation toggle ran for span
modes only, but the `orientations[]` array stored in
`monitorSetup` survived mode switches. So a screen that the user
had once set to "span-h" with a portrait sub-tile, then switched
back to "single", silently kept `orientations: ["portrait"]` and
the single-mode tile rendered as a portrait swap of the bridge's
viewport (e.g. a 2560×1440 screen showed up as a 1440×2560 tile
with no UI to undo it).

`rebuildWallScreens()` now hard-codes `landscape` for single-mode
tiles — the tile IS the bridge's reported viewport, no rotation
math applies. The orientation array is also reset to
`["landscape"]` on every switch back to single mode so the stored
state stays clean.

### Changed — "Bridge N" → "Screen N" labels

Every Monitor-Setup row + the Apply-summary toast now reads
"Screen 1" instead of "Bridge 1". Matches the wording Lively and
Wallpaper Engine use; the "bridge" framing was an internal-API
leak.

### Removed — "Bildschirme" override picker

The Monitor Wall section's Auto / 1 / 2 / 3 / 4 picker (added in
v1.2.4 to override the bridge-reported `screenCount`) is gone.
Per-screen splits are now what users actually care about, and
they're already in the Monitor-Setup rows above. Anyone who
genuinely needs a different bridge `screenCount` can change it
in the Configurator's System section — single source of truth.

The localStorage key `signalrgb.builder.wall_screen_count` is
wiped on first v1.2.7 load so stale overrides don't carry over.

### Removed — "⇔ Canvas spannen" button + auto-suggestion hint

Already hidden in Simple mode since v1.2.6; v1.2.7 drops it from
Advanced too. The button took the central canvas and sliced it
into wall slots, which is the inverse of the v1.2.5 per-tile
direct-edit flow (each tile already gets its own image directly).
Keeping it on the Advanced surface was just a wrong-click trap.

The "Canvas aspect matches the wall — try Span across monitors"
auto-suggestion banner is gone for the same reason — it pointed
at a button that no longer exists.

### Reverted — partial v1.2.6 custom-mode addition

v1.2.6 shipped half a "custom" mode (rebuildWallScreens branch +
mode-picker option) without the per-tile editor UI. Backed out so
the dropdown doesn't expose a mode that has no editing surface.
A proper custom mode for non-rectangular spans (landscape +
portrait monitor pair → 4000×2560 bounding box) is the right
direction; it just needs the bridge to own the layout state so
the Configurator + Builder share the same definition.

### Other

- New comment in the Monitor Wall section explaining where to
  change `screenCount` now that the inline picker is gone.

---

## [1.2.6-beta] - 2026-05-25

> v1.2.5 fixes. The new tile-first flow exposed three regressions in
> the apply pipeline + a cramped right panel that didn't fit the
> Monitor-Setup rows. Plus the "Canvas spannen" button is now hidden
> in Simple mode — it conflicts with the per-tile editing flow and
> only confuses new users.

### Fixed — Slots wiped after Apply made tiles look fillable when they were empty

Pre-v1.2.5 `applyWall()` cleared every slot after a successful
upload because each slot was a one-shot delivery to a single
screen. The v1.2.5 per-tile edit flow inherited the same wipe by
accident, which meant: user loads image into a tile, edits it,
hits Apply, sees the "✓ applied 1/1" toast, then clicks the tile
to make further edits — and gets a file picker because the slot
was just emptied. Looked like the loaded image had vanished.

`applyWall()` now keeps the slot's image bytes after a successful
push and just marks `slot.applied = true`. Tile labels gain a
"✓ angewendet" badge so the user can still tell which tiles
have already been delivered, and clicking a tile drops them
straight into the in-place edit flow as expected.

### Fixed — Apply feedback was uninformative

The old "Auf 1/1 Bildschirm(e) angewendet" toast didn't say
*what* was applied or to *which* monitor. v1.2.6 builds a richer
per-bridge-screen summary:

> Bridge 1 (5120×1440) ← 2/2 tile(s)

One line per bridge screen written. Shows the composite
resolution so the user can verify the span math, and the tile
fill ratio so it's obvious if an empty sub-tile was uploaded as
transparent.

### Changed — "Span canvas" button hidden in Simple mode

The button slices the single Builder canvas into wall slots,
which is the inverse of the v1.2.5 per-tile-edit flow (each tile
already gets its own image directly). Keeping it visible in
Simple mode was a contradiction — and a tempting wrong-click for
new users. Still available in Advanced mode for the legacy
single-canvas → split workflow.

### Changed — Right panel widened to 340 px

The Monitor-Setup rows + the wall tile preview overflowed the
old 260 px column at 2-monitor span layouts (the "2 Monito…" cut
off in the screenshot). Wider right panel + bumped tile preview
sizes (horizontal 130 → 150 px base, vertical 220 → 260 px, free
150 → 160 px, 2×2 unchanged) so the standard ultrawide-span
case now fits without horizontal scrolling.

### Added — Per-sub-tile orientation (portrait / landscape)

Each sub-tile in a span setup gains a ▭/▯ toggle that flips
its orientation. A portrait sub-tile gives the user a portrait-
shaped edit canvas (long axis vertical) and the composite step
rotates the image 90° CW when stamping it into the (landscape-
shaped) bridge slot — so a span across a landscape + portrait
monitor pair where Windows rotates the physical screen now
renders the right pixels in the right orientation.

Orientations persist alongside the mode under
`signalrgb.builder.monitor_setup.orientations[]` and are
preserved when toggling modes (single ↔ span-h ↔ span-v).

### Other

- New i18n keys: `wall.applied_summary_line`, `wall.tile_applied`,
  `setup.orient.landscape_short`, `setup.orient.portrait_short`,
  `setup.orient.title`.
- Tile label suffix becomes "✓ angewendet" after apply (was
  "staged" while loaded but not yet pushed).
- Wall-tile descriptor now carries `slotW` / `slotH` (bridge
  composite slot dimensions, independent of `w` / `h` which
  are the user's edit-canvas dims; the two diverge in portrait
  mode).

---

## [1.2.5-beta] - 2026-05-25

> Builder Monitor-Setup. The Builder now starts from "tell me about
> your monitors" — declare any bridge-reported screen that's actually
> a span of multiple physical monitors, edit each resulting tile
> independently, and Apply composites everything back into one image
> per bridge screen. The classic single-canvas Load/Rotate flow stays
> available in Advanced mode for the muscle-memory crowd.

### Added — Monitor Setup at the top of the Wall section

New per-bridge-screen mode picker rendered above the wall tiles.
Each bridge-reported screen (1–4) gets a row showing its actual
reported resolution + a mode select:

- **1 monitor (use as-is)** — default, one tile covering the
  whole bridge screen
- **2 monitors — horizontal span** — splits the bridge screen
  into a left + right tile (each w/2 × h)
- **2 monitors — vertical span** — splits into top + bottom
  (each w × h/2)

Each row also shows a tiny visual preview of the resulting tile
shape so the user can verify the split before staging images.

The setup persists in `localStorage` under
`signalrgb.builder.monitor_setup` so the user only declares
their span layout once.

### Added — Tile-first editing flow

Wall-tile click behavior changed:

- **Empty tile** → opens the file picker directly. The picked
  file loads into the tile *and* the main Builder canvas
  in one step (the v1.2.4 in-place edit banner appears
  immediately).
- **Filled tile** → drops straight into the in-place edit flow
  for that slot (was: popup with file / library / canvas /
  clear / edit choices).
- **Right-click** on any tile → opens the legacy action popup
  with all options (file / library / current canvas / edit /
  clear) for users who need the alternate sources.

Empty-tile hint copy updated to mention the new shortcut + the
right-click escape hatch.

### Changed — Apply-Wall does per-bridge-screen compositing

`applyWall()` no longer ships one PNG per slot to
`/screen/N/background`. Instead it:

1. Groups the flat tile list by `bridgeIdx`.
2. For each bridge screen, builds a composite canvas at the
   bridge's reported resolution (e.g. 5120×1440).
3. Stamps each tile's image at its declared (xOffset, yOffset,
   w, h) inside that composite. Empty sub-tiles stay transparent.
4. POSTs the composite to `/screen/bridgeIdx/background`.

So a 5120×1440 bridge screen declared as "2 horizontal monitors"
plus two staged tile images becomes a single 5120×1440 PNG with
the left half = tile 0 and right half = tile 1. Wallpaper Engine
and Lively then display it across both physical monitors in
their existing span mode.

Single-tile bridge screens still go through the composite path —
the math degenerates to "draw at 0,0 covering full bridge
resolution" so the apply pipeline doesn't fork.

### Changed — Simple mode hides Load + Rotate

The classic "Load" section (Choose image… / Open from library… /
Rotate 90°) is now hidden under Simple mode because the new
tile-first flow makes it redundant. Advanced mode keeps it for
users who prefer the single-canvas → single-screen workflow.

### Other

- New data model: `bridgeScreens[]` (reported state from
  `/config`) + `monitorSetup[]` (per-screen mode) + flat
  `wallScreens[]` (tile descriptors with bridgeW/bridgeH/
  xOffset/yOffset/w/h/bridgeIdx/subIdx).
- `loadWallViewports()` reconciles `monitorSetup.length` to
  `bridgeScreenCount`; new entries default to `"single"`.
- New i18n keys: `wall.hint4`, `setup.bridge_screen`,
  `setup.mode.single`, `setup.mode.span_h`, `setup.mode.span_v`.
- `loadWallSlotFromFile()` now auto-opens the edit flow on the
  freshly-filled slot so the user lands in the edit banner
  without a second click.

---

## [1.2.4-beta] - 2026-05-25

> Builder Monitor Wall becomes a true per-monitor editor. Each tile is
> now a fully-editable slot — open it in the main canvas, use any tool
> (Auto-Cut, brushes, colour-pick, polygon, etc.) on just that
> monitor's image, then save back. Plus a "Monitors" override picker
> for users testing multi-monitor layouts they don't physically have
> connected.

### Added — Per-slot in-place editing on Wall tiles

New "Edit in main canvas" action in the wall-frame popup menu
(next to Choose file… / From library… / Use current canvas /
Clear). Opens the slot's image in the Builder's main canvas with
all existing tools available. A persistent banner above the
canvas surfaces "Editing Wall slot N" + Save / Cancel CTAs so
the user can't lose edits by accident. Save writes the edited
bytes back to the slot via the existing
`loadWallSlotFromCurrentCanvas` pipeline; Cancel drops the
in-progress edit.

Resolves the long-standing gap that wall tiles could only
receive a finished image — Auto-Cut + brushes were only
reachable for the "single full canvas" workflow.

### Added — Monitor count override picker

Top of the Monitor Wall section: new "Monitors" select with
options "Auto (from bridge)" + 1 / 2 / 3 / 4. Lets users design
wall layouts for setups they don't physically have connected
(testing a 4-monitor wall on a 2-monitor desk, etc.). Override
persists in `localStorage` (`signalrgb.builder.wall_screen_count`)
so it survives reloads.

When the user picks an explicit count, `loadWallViewports()`
uses that instead of the bridge's `screenCount`; "Auto" clears
the override.

### Other

- New i18n keys: `wall.hint3`, `wall.screen_count`,
  `wall.screen_count.auto`, `wall.menu.edit`, `wall.editing`,
  `wall.editing_banner`, `wall.editing_save`, `wall.editing_cancel`,
  `wall.edit_saved`, `wall.edit_save_failed`, `wall.edit_empty`.
- The wall-frame menu disables the Edit row on empty slots
  (rather than opening the file picker silently).
- Editing-slot banner injects itself above the canvas-toolbar
  only when in use, so users who never touch the Wall edit
  flow see zero new chrome.

---

## [1.2.3-beta] - 2026-05-25

> Builder onboarding overhaul + two fresh Quick-Looks bundles. The
> Builder's tool surface used to drop new users into a panel of nine
> tools with no signpost; v1.2.3 hides everything but Choose-image +
> Auto-Cut behind a Simple/Advanced toggle (Simple = default) and
> nudges the AI button on first image load. The Monitor Wall section
> with its built-in SPAN support stays visible in both modes so
> multi-monitor wall workflows are one click away.

### Added — Builder Simple / Advanced mode toggle

New pill in the Builder header. Simple mode (the default for first-
time users) hides:

- The bounded / region / polygon / ellipse / crop tool buttons
- The restore / erase / pattern brush tools
- The full Merge-images details fold
- The History section (undo / redo / reset-edits)

What stays visible: Click-pixel (the default colour picker), Auto-
Cut (the AI star tool), Load section, Monitor Wall section, Output
section, canvas + toolbar. Mode choice persists in `localStorage`
so returning users land in whichever mode they last picked.

A 3-step workflow hint above the Load section spells out the
Simple-mode happy path ("Load → Auto-Cut → Apply") so the user
doesn't have to discover Auto-Cut by hovering every tool icon.

### Added — Auto-Cut nudge on first image load

When an image lands on the canvas for the first time in Simple
mode, the AI tool button gets a 5-second pulse (3 × accent-bg
glow rings) to point the user at it. Suppressed after the first
firing via a `localStorage` flag, so returning users don't get
poked every load. Doesn't auto-run Otsu — running an automatic
mask on a non-glow source image would just dump alpha into the
wrong half of the picture; the pulse just makes the next click
discoverable.

### Added — Two new Quick Looks bundles

- **News Desk** — Aurora ambient + glass tile shell + digital
  clock + weather + a 540 × 420 RSS widget pre-pointed at Hacker
  News. Built for the "always-on second monitor as a dashboard"
  use case the v1.2.1 RSS widget unlocked.
- **Focus Mode** — Black background, no effects, just a big HMS
  countdown ("Focus block ends") and a sticky note with a Top-3
  template. For deep-work blocks where the wallpaper has to
  disappear.

### Other

- Mode toggle reads/writes `signalrgb.builder.mode` in
  `localStorage`; auto-cut nudge tracker uses
  `signalrgb.builder.autocut_pulse_shown`.
- Builder header gains a `.spacer` + `.mode-pick` row; main grid
  layout unchanged.
- `applySourceImage` is wrapped (not edited in-place) so the
  v1.2.3 nudge hook stays isolated from the existing load pipeline.

---

## [1.2.2-beta] - 2026-05-25

> Configurator UX overhaul. Tray's "Advanced" submenu shrinks down to
> the per-screen quick mutations; everything else (bridge toggles +
> maintenance buttons) moves into a new System section in the
> Configurator. Mirror-mode UI redesigned around a per-screen popover
> instead of the full-width bar. New left rail with one icon per
> section card for fast navigation.

### Added — Left section-nav rail

Fixed left rail with one icon button per `<section.card>` in the
Configurator. Rests at 36 × 36 px showing just icons; expands to
168 px on hover to reveal labels. Click jumps to + auto-expands
the target section. An IntersectionObserver highlights whichever
section currently dominates the viewport.

Hidden via media query under 1080 px viewport width so it never
overlaps the centred main column on narrower setups.

### Added — Configurator "System" section

New collapsible card between Widgets and Per-app profiles. Hosts
the bridge-scoped toggles and maintenance actions that used to live
in the tray's Advanced submenu:

- Global preset hotkeys
- Pause on fullscreen apps
- Check for updates on startup
- Include beta releases
- Check now / Open releases page
- Reload config from disk
- Reload wallpaper pages
- Re-import wallpaper bundles

### Changed — Mirror-mode UI

The full-width `#mirror-bar` between the tab row and main content
was visually heavy and pre-empted vertical space on every screen
even when nobody was mirroring. v1.2.2 replaces it with:

- A small `↳ N` badge inside each tab that's mirroring screen N.
  Renders on the tab itself + on the Overview card mini-thumbs.
- A "Screen settings" gear icon docked at the tab row's right
  edge. Click opens a 320 px popover with the mirror picker, an
  active-mirror hint banner, and the "Reset this screen…" button.
  Auto-closes on outside click or Esc.

### Changed — Tray Advanced submenu

Shrunk to just the two per-screen quick-mutation menus (Add
widget, Quick effects). The five toggles + buttons that used to
live alongside them are now under the Configurator's System
section, addressed via:

- `bridge-setting-update` WS commands for the four bridge-scoped
  booleans (`fullscreenPause`, `updateCheckEnabled`, `allowBetas`,
  `presetHotkeysEnabled`).
- New `system-action` WS command for the maintenance buttons.
  Whitelisted action names (`reload-config`, `reload-wallpapers`,
  `reimport-bundles`, `check-updates-now`, `open-releases`)
  dispatch to the same handlers the tray was calling.

`Broadcaster` now publishes a `bridge` object alongside the
per-screen settings push so the Configurator's System toggles
hydrate from the bridge config on connect / reconnect / cross-tab
edits.

### Other

- New i18n keys: `section.system`, `system.*`,
  `screen_popover.trigger_title`.
- `BridgeRuntime` gets a `tray` reference, set by `main()` after
  both objects exist, so the WS `system-action` dispatcher can
  invoke the existing tray methods without ripping them out.
- The legacy `#mirror-bar` element is kept hidden via CSS and
  still driven by `renderMirrorBar()` as a no-op shim — avoids
  ripping out every external reference for this release.

---

## [1.2.1-beta] - 2026-05-25

> Bug-fix + small-feature beta on top of 1.2.0-beta. Focus: fix the
> widget header layout regression, finally make pause-on-fullscreen
> work for users on MSIX Lively, add an RSS widget and a fancy
> bridge-offline standby card, and let "Choose image" auto-add to
> the Library.

### Fixed — Widget header layout broke per-type body layouts

v1.1.5 introduced the optional `.widget-header` strip at the top of
every widget. The shell wraps content in a new `.widget-body` div,
but per-widget CSS rules (`.widget-clock { display: flex; … }`,
`.widget-quote { display: flex; … }`, etc.) still targeted the
`.widget-X` root. With header on, the header bar became a flex
child of the same flex container that was centring the clock face —
the analog clock got squeezed beside the "CLOCK" header label
instead of sitting under it. Same root cause behind the
"Cyberpunk-Streamer bundle has 2 clocks" report: one widget +
header label looked like two stacked widgets because of the
collapsed layout.

Moved every per-type layout rule (display:flex / flex-direction /
gap / justify-content) from `.widget-X { … }` to
`.widget-X .widget-body { … }`. Padding and visual chrome stay on
the root so tile-shell variants (glass/solid/clear) keep their
chrome around the entire widget. Affects: clock, calendar, weather,
countdown, quote, now-playing, cpu-meter, ram-meter, net-graph,
hardware-sensor.

### Fixed — Pause-on-fullscreen never fired on MSIX Lively

Lively from the Microsoft Store runs its WebView2 inside an
AppContainer sandbox. The default AppContainer firewall rule
blocks outbound loopback (127.0.0.1) traffic, so the wallpaper
page's `ws://127.0.0.1:17320/` connection silently failed and the
bridge's `paused` WS messages never reached the wallpaper. Users
saw glow + widgets keep rendering on fullscreen games even with
"pause on fullscreen" toggled on — and most also reported widgets
never appearing at all. Same package, GitHub-installer build: no
problem (no sandbox).

Installer now ships a `msix-lively-loopback-exempt.ps1` helper that
auto-detects the MSIX-Lively package family name (via
`Get-AppxPackage` first, then a `Packages\*rocksdanister.LivelyWallpaper_*`
folder probe as fallback) and runs
`CheckNetIsolation.exe LoopbackExempt -a -n=<PFN>` to grant the
exemption. Runs in the `[Run]` section after a successful install
(`waituntilterminated` so the bridge starts with the new
permission already in place), and is also re-invoked from
`reimport-wallpaper-bundles.ps1` for users who install MSIX
Lively *after* the bridge was set up. Idempotent + a no-op on
non-MSIX-Lively systems.

### Added — RSS / Atom feed widget

New widget type `rss` reading any RSS 2.0 or Atom feed URL.
DOMParser-based XML parsing, no third-party deps. Renders the
latest N titles as a scrollable list with optional per-item
relative dates ("3h ago", "2d ago", "13/05/2026"). Channel title
fills the widget header bar; can be overridden via the `feedTitle`
option. Refresh interval configurable from 5 min to 3 h (default
15 min). Fetch errors surface inline in the widget footer.

Same CORS caveat as Weather + Quote: Wallpaper Engine's CEF
blocks outgoing cross-origin `fetch()` by default for some users;
toggle "Allow internet access" per-wallpaper if a feed never
loads.

### Added — Bridge-offline standby card

When the bridge isn't reachable, the wallpaper used to just sit
quietly showing the static background with no glow and no
widgets. v1.2.1 adds a centred standby card (frosted-glass shell,
animated pulse + scan-line, "SignalRGB Wallpaper Bridge offline"
text + instructions) that fades in after 5 s without a live WS
and fades out the instant the bridge is reachable again. 5 s
delay was picked so a quick bridge restart never flashes the
card; preview-mode iframe suppresses it (the Configurator has its
own connection status). Pure CSS animation — zero per-frame
work, no impact on the wallpaper's rendering loop.

### Added — "Choose image" auto-adds the picked image to the Library

Picking an image (or video) via the Configurator's "Choose image…"
button used to set it as the screen background but NOT add it to
the Library, so the user had to manually re-upload via "Add image…"
if they wanted to swap back to it later. The change handler now
fires both calls: the existing `/screen/N/background` POST (PNG
canvas-converted for images, raw bytes for videos) plus a
`/library/upload?name=<basename>` POST with the raw bytes
(preserves video container + JPEG quality — no canvas
recompression for the library copy). Library refresh fires
automatically so the new tile appears in the strip.

### Other

- Bridge: new `rss` entry in `WIDGET_DEFAULTS` (label "RSS feed",
  360×280, defaults to empty feedUrl + 15-min refresh + 8 items).
- Configurator: new `rss` schema in the widget options registry
  (feedUrl text, optional feedTitle override, itemCount and
  refreshMin selects, showDate + tintFromGlow booleans).
- `bg-file` accepts videos (mp4 / webm / mov / m4v / mkv) — was
  image-only before, would error if you tried to pick a video.
- Wallpaper: `_formatRssDate()` helper shared with the RSS
  widget; rss-specific CSS block (`.widget-rss` shell + list +
  per-item styling + error-foot variant).

---

## [1.2.0-beta] - 2026-05-24

> First beta of the post-v1.1 cycle. Four substantial dev tracks
> consolidated into one beta tag: a live WYSIWYG preview iframe in
> the Configurator, one-click Look-Bundles, GIF/video background
> support, and a long-standing MSIX-Lively bug finally tracked
> down.

### Added — Live preview iframe in the Configurator

The Widgets-card's layout preview used to be a schematic drag
area: each widget rendered as a coloured rectangle the user
positioned with their mouse, but the rectangle was a placeholder,
not what would actually appear on the wallpaper. v1.2-beta adds
a real iframe of the wallpaper page above the schematic preview
showing **exactly** how the current settings render — same widgets
with their real layouts, same ambient effect, same background, all
live and updating as you change settings.

Architecture:

- New `/wallpaper` and `/wallpaper/*` HTTP routes on the bridge
  serve `wallpaper/index.html` + sibling assets out of the
  PyInstaller bundle (`--add-data "wallpaper;wallpaper"` baked
  into build.ps1). Static-file serving with path-traversal
  protection.
- Wallpaper page learns `?preview=1` mode. Parallax3d, pixelfx
  and audio-glow setters all no-op when PREVIEW_MODE is true so
  the iframe doesn't fight with the on-desktop instance running
  in Lively / WE (cursor tracking, audio-listener double-feed).
  Critically, `reportViewport()` also no-ops in preview mode —
  otherwise the iframe's CSS-pixel size would overwrite the
  bridge's per-screen viewport state, which is supposed to track
  the real monitor's resolution.
- Iframe sized to the screen's NATIVE canvas (settings.viewportW
  / viewportH) then visually scaled down via CSS `transform:
  scale(containerW / nativeW)` with origin 0 0. So widgets at
  absolute pixel coords render at the same relative size they
  appear on the actual wallpaper.
- Container `overflow:hidden` + `aspect-ratio` clip the scaled
  iframe to the right shape.
- `syncLivePreviewScale()` runs on initial setup, screen switch,
  viewport changes, iframe load events, and window resize. Show
  / hide toggle remembered in localStorage.

### Added — Quick Looks

New Configurator card above Background with five pre-built
combinations: **Cyberpunk Streamer**, **Minimal Productivity**,
**Gaming**, **Music Studio**, **Holiday Vibes**. Each defines a
settings dict (background, glow, ambient effect, audio-glow,
tile-style, parallax) plus a widget set with positions, options,
and per-widget tile-style overrides.

Click a card → confirm dialog → applies in one burst: spams the
matching `setting-update` WS messages, removes existing widgets,
adds the bundle's widgets at their target positions. WS messages
are serial-per-connection so the apply order is deterministic
(setting updates land first, widget removes drain, then widget
adds populate).

`widget-add` WS schema gained optional `x` / `y` / `w` / `h` /
`options` fields so a bundle can ship the full widget layout in
one round-trip per widget (versus add-with-defaults + update-
position the legacy "Add widget" button still uses). Bundle
options merge over `WIDGET_DEFAULTS`; existing UI path unchanged.

Add-via-bundle leaves `widgetsLocked` alone (lands in read-mode)
instead of unlocking like the manual Add button does — bundles
land in a clean WYSIWYG state ready to be viewed, not edited.

### Added — GIF / video background support

`bgImage` URLs ending in `.mp4` / `.webm` / `.mov` / `.m4v` /
`.mkv` now route through a new `<video id="bg-video">` element
instead of the CSS `background-image` path. Animated GIFs already
animated via the existing image-div route (browsers play them
natively as CSS bg) and stay there; they're added to the library
scan for discovery only.

Video element setup:

- `muted` + `playsinline` + `loop` + `autoplay` — required for
  autoplay in Chromium-based wallpaper hosts.
- `preload="auto"` + `disablepictureinpicture` so it loads
  eagerly and doesn't show the PiP overlay on top of the
  wallpaper.
- Same z-index + fade transition as `#bg` so the swap between
  image-mode and video-mode is invisible.
- `bgFit` drives `object-fit` on the video the same way it
  drives `background-size` on the div. Tile modes fall back to
  cover (browsers can't `background-repeat` a `<video>`).
- Re-setting the same src is suppressed (`dataset.currentSrc`
  check) so a settings push that doesn't change `bgImage`
  doesn't restart playback from frame 0.

Library + upload:

- `_library_rebuild_catalogue` scans the new extensions in
  addition to the image set.
- `_library_slug` uniqueness check covers them so
  `spaceship.mp4` doesn't collide with an existing
  `spaceship.png`.
- `/library/upload` sniffs MP4 / MOV / WebM / GIF magic-bytes
  alongside the existing PNG / JPEG / WebP detection. ISO BMFF
  `ftyp` box discriminates MP4 vs MOV vs M4V.
- `MAX_BACKGROUND_UPLOAD_BYTES` bumped 50 MB → 200 MB so 1080p
  / 4K video loops fit comfortably.
- Configurator file-pickers (library upload + direct bg picker)
  accept the new video MIME types + extension hints.

### Fixed — MSIX-Lively auto-import (long-standing trap)

User report: clean install with auto-import-into-Lively ticked,
but the four `SignalRGB Glow – Screen N` tiles never appeared in
their MS Store Lively library. Two-layer bug:

1. **Wrong path target.** When MSIX-Lively writes to
   `%LOCALAPPDATA%\Lively Wallpaper\` in its own code, Windows
   transparently redirects to
   `%LOCALAPPDATA%\Packages\<pkg>\LocalCache\Local\Lively
   Wallpaper\` — NOT `LocalState`. The installer was probing
   only `LocalState` and silently shipped wallpapers into a
   folder Lively never reads from. Added the LocalCache probe;
   it wins over LocalState when both exist.
2. **Wrong wildcard.** Even after the path fix, the probe missed
   every Store-installed Lively because the MS Store prefixes
   every package name with a numeric publisher ID — the real
   directory is e.g. `12030rocksdanister.LivelyWallpaper_<hash>`,
   not `rocksdanister.LivelyWallpaper_<hash>`. Added a leading
   `*` to the wildcard so the publisher prefix is matched.

Both fixes land in the .iss installer (Pascal `GetLivelyLibraryPath`)
and the tray-side re-import PowerShell script. End-result: clean
install with auto-import ticked now reaches MSIX Lively too. By
extension, the v1.1.5 auto-chain re-import works on MSIX setups.

Side-effect explanation: users reporting "pause mode doesn't work
either" on MSIX Lively were observing the upstream symptom of
this bug — with no wallpaper imported, Lively had nothing to
pause. Auto-pause itself was never broken; it just had no target.

### Changed — `widget-add` WS message accepts initial positioning

Backwards-compatible extension to support the Look-Bundles
apply path. Existing "Add widget" button passes only
`widgetType` like before; bundle apply passes the full
`{widgetType, x, y, w, h, options}` payload. Bundle widgets
land at their target position without an add-then-update
round-trip per widget.

`add_widget` now also leaves `widgetsLocked` alone when the
caller supplies explicit `x` / `y` (the bundle case). Manual
adds still unlock the page so the user can find / move the
freshly-added widget.

### Notes for users on this beta

- Wallpaper-page JS changed significantly. After tray-update or
  manual install, run **Advanced → Re-import wallpaper bundles**
  once to refresh Lively / WE bundles (v1.1.7's auto-chain
  should run this automatically on the v1.1.x → v1.2.0-beta
  upgrade).
- Live preview iframe is on by default. Toggle off via the
  *Show live preview* checkbox at the top of the Widgets card
  if it's causing GPU pressure on a busy multi-monitor setup.
- Quick Looks bundles are destructive: clicking one removes
  every existing widget on the active screen and replaces with
  the bundle's set. Confirm dialog prompts before the action.

## [1.1.0] - 2026-05-23

> 🎯 **Second stable.** Drops the `-beta` suffix on the v1.1 cycle.
> Eight betas (v1.1.0-beta → v1.1.7-beta) consolidated into one
> stable surface — no new code beyond v1.1.7-beta, just a version
> bump and the formal commitment that everything shipped in this
> cycle is now considered stable.

### Headline features over v1.0

The v1.1 arc turned the v1.0 foundation into a cohesive product:

- **Tile design system for widgets** — every widget can wrap in a
  uniform shell (Glass / Solid / Clear / Off), with a global
  default plus per-widget overrides. Optional header bars (icon +
  title + actions) so each tile self-identifies.
- **Universal widget options** — `textAlign` (left / center /
  right), `textScale` (50 - 200 %), `tileStyle` override and
  `showHeader` toggle on every widget, surfaced in a new
  *Layout (applies to all widgets)* section of the Configure
  modal.
- **Background Fit tile / repeat modes** — three new entries
  (tile / tile X / tile Y) plus a Tile-scale slider (10 - 200 %)
  that scales the pattern relative to the source image's natural
  pixel dimensions. Finally lets seamless pattern wallpapers
  (carbon fibre, hex grids, retro tiles) render at native scale.
- **Three new ambient effects** — Waves, Ripples, Flowfield. Brings
  the picker to **15 presets total**.
- **Auto-update finally end-to-end** — one tray click downloads the
  installer, swaps bridge + plugin + bundle files, restarts the
  bridge, and re-imports the Lively / WE wallpaper bundles via
  CLI / project.json patch. No more "tray update doesn't reach
  Lively" friction.
- **Configurator layout-preview reflects overrides** — per-widget
  override badges (small suffix-text like *· glass*, *· center*,
  *· 150%*) plus warm-amber tint for explicit overrides, so users can
  spot misconfiguration without opening every Configure modal.
- **Hardware-sensor widget polish** — matches CPU/RAM in font
  family, sizing, unit placement, and auto-derived label cleanup.

### Compatibility

- Bridge protocol, plugin file format, WebSocket wire format and
  wallpaper-bundle structure are unchanged from v1.0. The v1.x
  stable-surface promise holds; v1.0 → v1.1 is a feature-add
  release, no breaking changes.
- Existing v1.0 + v1.1.x installs auto-update to v1.1.0 via the
  tray. The full auto-update pipeline (download / install /
  bundle copy / re-import) lands silently in one click thanks to
  the v1.1.4 → v1.1.7 fix arc.

### Why the long beta cycle

The v1.1 betas spanned a single intense work day, but the bug
hunt revealed a stack of latent issues with the auto-update flow:

- `subprocess.Popen + DETACHED_PROCESS` was reportedly dying with
  the parent on some Windows configs (v1.1.7 forerunners → fixed
  in v0.9.17 with `ShellExecuteW`).
- `CloseApplications=yes` deadlocked when paired with
  `/SUPPRESSMSGBOXES` (v0.9.19).
- Default AI cut-out model URL was non-commercial, then broken,
  then walked back entirely in favour of pure-JS classical
  saliency (v0.9.18 → v0.9.20).
- Silent installs landed with `checkedonce` tasks defaulting OFF,
  so bridge swapped but plugin + Lively + WE bundles + autostart
  all stayed at previous-install state (v1.1.6 + v1.1.7).
- Re-import script auto-launched Lively even on WE-only setups
  (v1.1.7).

Each beta surfaced + fixed the next layer. The v1.1.0 stable
release is the consolidated result.

### Workshop + Winget — maintainer todo for after stable

Bridge auto-update flows through GitHub Releases. Workshop
subscribers and Winget users update via separate channels:

- **Workshop**: run `installer\maintainer-restore-workshopid.ps1`
  (re-injects the canonical workshopid since the installer wipes
  it on every run), then WE Editor → Share on Workshop with the
  v1.1 changelog.
- **Winget**: `wingetcreate submit installer\winget` once the
  microsoft/winget-pkgs PR for v0.9.21 has merged (still
  pending moderator review at v1.1.0 cut).

## [1.1.7-beta] - 2026-05-23

> Same root-cause class as v1.1.6-beta one layer down: the
> `autostart` task that gates the [Run] entry which re-launches
> the bridge after install also runs into the `Flags: checkedonce`
> plus silent-install = OFF default trap. v1.1.6 fixed the file-copy
> tasks but forgot autostart, so the silent update path landed
> with a fresh bridge.exe on disk but no running process — user
> had to launch from the Start menu (or reboot) to actually get
> the new bridge live.

### Fixed — Bridge auto-restarts after silent update

Added `autostart` to the `/MERGETASKS` list the bridge's update-
spawn passes to the silent installer. With the task forced ON,
the [Run] entry's `Tasks: autostart` gate evaluates true, the
postinstall entry runs even in silent mode, and the fresh
bridge.exe is launched automatically as the installer exits.

Full `/MERGETASKS` is now:

```text
installplugin,
installlively,installlively\autoimport,
installwallpaperengine,
autostart
```

`installlively\autoinstall` and `openconfigurator` deliberately
stay out — re-downloading Lively every update and popping a
browser tab every update are both anti-features.

### Fixed — PowerShell window flash during re-import

The auto-chain re-import was visible as a brief PowerShell console
window flashing into view post-update. Bridge now passes
`CREATE_NO_WINDOW` to the subprocess.run call AND `-WindowStyle
Hidden` to PowerShell itself; output still lands in
`%TEMP%\signalrgb-reimport.log` so nothing's lost.

### Fixed — Re-import no longer force-launches Lively

The re-import helper called `Lively.exe --import <zip>` whenever
the Lively binary was found on disk, regardless of whether Lively
was actually running. Users with both Lively + WE installed who
only actively use WE (the reported case) had Lively auto-launching
on every update. The script now checks for a running Lively
process first (`Get-Process Lively, Livelywpf`) and skips the CLI
invocation entirely if Lively isn't up — the new ZIPs are still
sitting in `{app}\Lively wallpapers\` for whenever the user
opens Lively manually.

Removed the Explorer-folder-open fallback for the same reason —
popping a folder window mid-update is just as annoying as
auto-launching Lively.

### End-to-end auto-update timeline (post-v1.1.7)

After this release the full auto-update pipeline runs silently
without any window flash and without launching apps the user
isn't actively using:

- User clicks tray *Download + install update*
- Tk download dialog (~3 MB), then ShellExecuteW the installer
- Bridge writes the `.pending-reimport` marker, then `os._exit(0)`s
- Inno (silent) copies bridge.exe + plugin + Lively ZIPs + WE
  bundle (all four task gates forced ON), runs the `autostart`
  [Run] entry that launches the new bridge
- New bridge boots, tray icon reappears, sees the marker, waits
  5 s for things to settle, runs the re-import helper hidden
- Lively re-imported only if already running; WE project.json
  `version` bumped so WE invalidates cache on next apply
- Tray balloon confirms re-import done

Zero manual steps, zero unwanted app launches, zero console
flashes after the initial *Download + install update* click.

## [1.1.6-beta] - 2026-05-23

> Root-cause fix for the long-standing "tray update doesn't update
> Lively/WE" bug. v1.1.4-beta added the re-import path but the
> auto-chain in v1.1.5 couldn't help because the installer itself
> wasn't actually copying the new Lively/WE bundles + SignalRGB
> plugin during silent re-install.

### Fixed — Tray-update now copies host bundles + plugin

`Flags: checkedonce` on the `installplugin`, `installlively`,
`installlively\autoimport` and `installwallpaperengine` tasks in
the .iss is supposed to remember the user's first-install choice
on subsequent silent installs. In practice the recall is fragile —
silent install with no `/TASKS` or `/MERGETASKS` argument lands
with most tasks DEFAULTING TO OFF, which silently no-ops the
file-copy entries in the [Files] section that depend on those
tasks. `SignalRGBBridge.exe` lives outside any task gate so it
swapped fine; everything else stayed at the previous-install
state.

Fix: the bridge's auto-update spawn now always passes

```text
/MERGETASKS="installplugin,installlively,installlively\autoimport,installwallpaperengine"
```

so those four tasks are FORCED on during the silent re-install,
regardless of what's saved in the registry. End result: the
SignalRGB plugin, the Lively wallpaper ZIPs, and the WE
`signalrgb-glow` project all get refreshed on every auto-update,
which is what the user reasonably expects from "Download +
install update". `installlively\autoinstall` is deliberately
NOT in the merge list — we don't want to re-download Lively
itself on every update.

Combined with the v1.1.4 re-import script and the v1.1.5
auto-chain marker, the full pipeline is now:

1. Tray → *Download + install update* (silent install with
   forced tasks → bridge + plugin + bundle files all updated)
2. Bridge restarts, sees the marker
3. Re-import script runs → Lively re-imports each ZIP via its
   CLI, WE project.json version-bumped so WE invalidates its
   cache on next apply
4. Toast confirms re-import completed

All from one tray click. The previously-broken case the user
reported ("tray update → WE/Lively show old version even after
restart") is the root cause this release fixes.

## [1.1.5-beta] - 2026-05-23

> Two roadmap items land: **one-click update** (auto-chain the
> v1.1.4 re-import onto the download+install path) and the
> **per-widget header bar** (icon + title + action buttons —
> the big-polish move that finishes the v1.1 tile-shell design).

### Added — Auto-chain: Download + install → re-import in one tray click

The v1.1.4-beta workflow exposed two separate tray clicks:
*Download + install update* (bridge swaps), then
*Re-import wallpaper bundles* (Lively + WE pick up the new
wallpaper-page code). v1.1.5 chains them automatically:

1. *Download + install update* now writes a tiny marker file
   (`%LOCALAPPDATA%\SignalRGBWallpaper\.pending-reimport`) right
   before `os._exit(0)`'ing.
2. The freshly-installed bridge's `main()` checks for that
   marker at startup; if it exists, a background thread waits
   5 s for the tray icon + WS reconnects to settle, then runs
   the bundle re-import script and deletes the marker.

End result: one tray click does the whole pipeline. The manual
*Re-import wallpaper bundles* entry stays available for the
"something didn't pick up cleanly" case.

### Added — Per-widget header bar

Every widget now has an optional header strip at the top with:

- **Left**: the widget-type icon (the same SVG that already
  identifies the type in the Configurator picker — re-used
  here as the in-screen badge so each tile self-identifies).
- **Centre**: the widget's display label (e.g. *Clock*,
  *Weather*, *CPU*). Ellipsis-truncated when the widget is
  narrower than the title.
- **Right**: settings + remove action buttons, fade-in on
  hover. These used to live as floating overlays on the body
  in edit-mode only; the header docks them in a predictable
  spot and makes them reachable without entering edit mode.

Hidden by default (preserves the pre-v1.1.5 look exactly — no
visual change for existing users). Enable per-widget via a new
**"Show header bar (icon + title + actions)"** toggle in the
Configure modal's *Layout (applies to all widgets)* section.
Stored as `showHeader` on the widget's options blob.

Header tint follows the *Tint with glow colour* toggle so
multi-widget setups read as one coherent UI surface.

CSS implementation: header is a CSS-grid row (`auto 1fr auto`)
inside the widget, body gets `height: calc(100% - 26px)` to
make room. Grid handles title-truncation cleanly even when the
widget is resized down to the icon's minimum width.

### Removed

- The dev-only Cat-Widget mockup at `temp/cat-preview.html`.
  Was explored as a roaming-pet experiment; dropped after design
  review (didn't fit the project's signal-driven aesthetic, and
  the per-spawn delight wasn't worth the per-widget complexity
  on a multi-monitor setup).

## [1.1.4-beta] - 2026-05-23

> Closes the long-standing auto-update gap: Lively and Wallpaper
> Engine now pick up wallpaper-page code updates without manual
> delete + re-import. Tray entry **Re-import wallpaper bundles…**
> under Advanced wraps the whole flow.

### Added — Tray: Re-import wallpaper bundles

New tray entry **Advanced → Re-import wallpaper bundles…** that
invokes a PowerShell helper script (`reimport-wallpaper-bundles.ps1`,
shipped next to the bridge exe). The script:

- **Lively path** — locates `Lively.exe` (GitHub-installer build;
  MSIX builds fall through to a folder-open prompt) and calls
  `Lively.exe --import <zip>` for each of the four
  `SignalRGB_Glow_ScreenN.zip` bundles in
  `{app}\Lively wallpapers\`. Lively re-extracts the ZIP into a
  fresh hash folder and updates its library entry to point at it,
  finally making auto-update actually reach the wallpaper page.
- **Wallpaper Engine path** — touches the `version` field inside
  `Steam\steamapps\common\wallpaper_engine\projects\myprojects\
  signalrgb-glow\project.json` so WE invalidates its in-memory
  cache on the next apply. The user still has to right-click the
  wallpaper → Set as wallpaper once after running the script
  (WE has no public reload API), but the version-bump means WE
  then loads the new files instead of the cached pre-update
  copy.
- Writes a step-by-step log to `%TEMP%\signalrgb-reimport.log`
  for post-mortem when something doesn't pick up cleanly.

The bridge's tray handler `_reimport_bundles` searches for the
helper script in three locations (dev / PyInstaller temp /
installed-app-dir) so the same code path works in dev runs and
in shipped installs. Falls back to `powershell` (5.1) if `pwsh`
(7+) isn't installed.

### Background — why this matters

Auto-update has technically existed since v0.9.8, but it only
ever updated the bridge exe. Lively caches each imported wallpaper
in a random-hash extracted folder and ignores subsequent edits to
the source ZIP; WE caches the project at first apply. So every
beta that changed wallpaper-page code (which is most of them)
forced users to manually delete the wallpaper from Lively /
unsubscribe from WE and re-import / re-apply. Real-world friction
that defeated the point of "in-app auto-update".

With v1.1.4-beta the workflow is:

1. Tray → Advanced → *Download + install update…* (bridge swaps)
2. Tray → Advanced → *Re-import wallpaper bundles…* (Lively + WE
   pick up the new wallpaper-page code)

A future v1.1.x will chain step 2 onto step 1 automatically; for
this beta both clicks are exposed separately so the user can run
step 2 in isolation when needed.

## [1.1.3-beta] - 2026-05-23

> Hotfix on the universal widget options from v1.1.2-beta: text
> alignment and text size silently did nothing on a handful of
> widgets because their internal layouts used flex containers
> (which ignore `text-align`) and hardcoded `clamp()` font-sizes
> (which bypassed the `--w-scale` variable).

### Fixed — text alignment on meter widgets

Hardware-sensor, CPU-meter, RAM-meter, and Net-graph all use
`display: flex` internally for the stat-head and stat-value rows.
CSS `text-align` doesn't affect flex children — they need
`justify-content`. The Universal Options pipeline now emits a
second variable `--w-justify` mapped from the textAlign choice
(left → flex-start / center → center / right → flex-end), and
the meter widgets' stat-head / stat-value rules read that
variable. The pre-v1.1 hardcoded `justify-content: space-between`
on stat-head is gone since the previously-empty second child
span (where the unit used to live before v1.1.1) was already
removed.

### Fixed — text size on widgets with clamp() font-size

The earlier `--w-scale` variable only multiplied the .widget
root's font-size, which clamp()-sized children ignored. Wrapped
the clamp() expressions in `calc(clamp(...) * var(--w-scale, 1))`
for:

- `.widget-clock .digital-time` and `.digital-date`
- `.widget-cpu-meter .stat-value`, `.widget-ram-meter .stat-value`,
  `.widget-hardware-sensor .stat-value`
- `.widget-calendar table`
- `.widget-weather .wx-temp`
- `.widget-countdown .cd-time`
- `.widget-quote .q-text`
- `.widget-net-graph .stat-pair`

### Removed

- The `transform: scale(var(--w-scale))` on `.widget-clock svg`
  that looked right in DevTools but got clipped by the parent
  `.widget` element's `overflow: hidden`. Analog clock mode no
  longer responds to the Text size option — that was always
  going to be the wrong axis to control on an analog dial.
  Resize the widget itself to make analog clock bigger; the
  Text size option still works for digital mode.

## [1.1.2-beta] - 2026-05-23

> Post-v1.0 plan A landed: per-widget tile-style + universal text
> options, Background tile-scale slider, Configurator preview
> reflects overrides, and ambient effects Batch 4 (waves, ripples,
> flowfield). Fifteen ambient presets total now.

### Added — Universal widget options

Every widget gains three new options in the Configure modal, in a
new "Layout (applies to all widgets)" section under the
widget-specific fields:

- **Text alignment** — left / center / right. Applied via
  `--w-align` CSS variable, so widgets that read text-align honour
  it without touching their own per-widget CSS.
- **Text size** — 50 / 75 / 100 / 125 / 150 / 200 % scale
  multiplier. Multiplies the base font-size; SVG-based widgets
  (clock face) use `transform: scale()` so the dial resizes
  proportionally.
- **Tile style override** — inherit / off / glass / solid / clear.
  Overrides the global *Widget tile style* setting from v1.1.0-beta
  for individual widgets. Picks like "everything Glass, but this
  CPU meter Solid" now work in one click.

The Configure button is now enabled on every widget (was disabled
for CPU/RAM/Net meters with empty per-type schemas) since every
widget at minimum has the universal options.

### Added — Background tile scale slider

When *Fit* is set to a tile mode (tile / tile X / tile Y), a new
*Tile scale* slider appears in the Background card (10-200 %,
default 100). At 100 % the pattern renders at the source image's
natural pixel dimensions; below that it shrinks, above that it
grows. Wallpaper page captures the loaded image's
`naturalWidth` / `naturalHeight` into CSS custom properties so the
scaling is a single CSS recalc rather than a JS rerender.

### Added — Configurator layout preview reflects widget overrides

Each widget's preview box now shows its effective styling at a
glance:

- The label gains a small suffix-badge for any non-default
  option (e.g. *· glass*, *· center*, *· 150%*).
- Widgets with an explicit tile-style override get a warm-amber
  tint so they stand out from inherited-default siblings.
- Preview-widget text honours the chosen `textAlign`.

Lets users spot a misconfigured override without opening every
widget's Configure modal.

### Added — Ambient effects, batch 4

Fifteen presets now. Three new effects, all written from scratch
in the `AMBIENT_PRESETS` shape:

- **Waves** — multiple sinusoidal horizontal lines flowing across
  the canvas at slightly different speeds, amplitudes and phases.
- **Ripples** — concentric expanding rings, water-surface style.
  Squared-falloff alpha taper so the afterglow fades smoothly.
- **Flowfield** — particles drifting through a pseudo-noise 2D
  vector field. Cheap sin/cos noise produces the swirling-stream
  pattern flow-field pens are known for; particles lerp toward
  the noise direction so trails curve smoothly.

All three honour the *Tint with glow colour* toggle. Matching
mini-preview tiles in the Configurator picker.

## [1.1.1-beta] - 2026-05-23

> Hotfix on the v1.1.0-beta hwmon (LibreHardwareMonitor) widget.
> Two reported issues: it used a different (default sans-serif)
> font than the CPU / RAM meters next to it, and the sensor's unit
> rendered in the header next to the label instead of after the
> value — so a "GPU Load %" sensor read as `[GPU %]\n[18.00]`
> with the % glued to the label, while CPU shows `[CPU]\n[23%]`
> with the unit attached to the value.

### Fixed

- **Hardware-sensor widget font** — added `.widget-hardware-sensor`
  to the same CSS rule block that drives the CPU / RAM / Net
  meters: same monospace value font (Cascadia Mono / Consolas),
  same uppercase 11 px head label, same `clamp(22px, 28%, 48px)`
  value sizing, same tinted-mode colour. The four meter widgets
  now look like they belong to the same UI.
- **Sensor unit placement** — moved `.hwmon-unit` out of the
  `.stat-head` (where it sat next to the label) and into the
  `.stat-value` row alongside the number. Unit is rendered at
  0.55 em + 0.75 opacity so it reads as a suffix on the value
  (`18.00 %`) instead of as part of the label (`GPU%`).
- **Auto-derived label cleanup** — leaf names that already carry
  a unit suffix (`GPU Total Load %`, `CPU Package °C`, fan RPMs,
  voltages, drive sizes) get the unit suffix stripped before the
  string lands in the label cell. The user's explicit `label`
  override still wins; this only affects the auto-fallback when
  no override is set.

## [1.1.0-beta] - 2026-05-23

> First beta of the post-v1.0 cycle. Two design-system changes
> from the roadmap landed together: a new **Background Fit tile
> mode** (so seamless pattern wallpapers finally render correctly)
> and the **widget tile shell** that lets users wrap every widget
> in a uniform glass / solid / clear container. Both are opt-in;
> defaults preserve the v1.0 baseline so existing users see no
> change unless they explicitly switch to a new mode.

### Added — Background tile / repeat Fit modes

Three new entries in the Background card's *Fit* dropdown:

- **tile** — repeats the image in both X and Y. CSS:
  `background-repeat: repeat; background-size: auto`. Use for
  seamless pattern wallpapers (carbon fibre, hex grids, dot
  patterns, retro tile art) that previously had to be stretched
  or cropped to fit the screen.
- **tile X** — repeats horizontally only, image fills the screen
  height (`background-repeat: repeat-x; background-size: auto 100%`).
- **tile Y** — repeats vertically only, image fills the screen
  width (`background-repeat: repeat-y; background-size: 100% auto`).

Implementation: swapped the wallpaper page's `<img id="bg">` for a
`<div id="bg">` with `background-image` since `object-fit` has no
tile mode. The fade-on-load UX is preserved via a `new Image()`
preload that drives the same opacity transition the old `<img>`
gave us.

### Added — Widget tile shell (opt-in)

New *Tile style* dropdown in the Configurator's Widgets card with
four options:

- **Off** (default) — transparent overlays, exactly like v1.0.
  No visual change for existing users.
- **Glass** — frosted-acrylic shell on every widget. Semi-transparent
  fill + backdrop blur, subtle border, soft drop shadow. Works
  against any wallpaper.
- **Solid** — opaque dark fill. Best for users who want widgets to
  stand out completely against busy / heavy-pattern wallpapers.
- **Clear** — minimal — faint fill, subtle border, mostly
  transparent. Half-step between Off and Glass.

The shell is applied via a single `body.widget-tile-<variant>` CSS
class, so flipping every widget happens in one DOM op. Per-widget
tokens (`--widget-tile-radius`, `--widget-tile-padding`,
`--widget-tile-shadow`, `--widget-tile-border`) sit on `.widget`
itself so future overrides only need a CSS-variable tweak rather
than rewriting the variant rules.

### Why this is a beta

Both changes are visually significant. The tile shell in particular
rewires the visual hierarchy of every widget on screen — that's
the kind of change that surfaces edge cases (text contrast on
specific wallpapers, blur performance on older GPUs, padding on
unusually small widgets) that only show up under real-world use.
Shipping as `-beta` so the maintainer + opt-in beta users can
collect feedback before the v1.1.0 stable.

Set tray → Advanced → *Allow beta updates* to pick this up
automatically; otherwise download the installer below manually.

## [1.0.0] - 2026-05-23

> 🎉 **First stable release.** Drops the `-beta` suffix that's been
> trailing the version string for ~18 months and shipped across
> ~50 beta tags. No new features beyond v0.9.21 — this is a
> stability + maturity statement, not a feature drop.
>
> Everything in the v0.7 → v0.9.21 beta cycle is now considered
> stable surface. The roadmap's Tier 1 (setup polish), Tier 2
> (high-visibility features) and Tier 3 (power-user / polish) are
> all shipped. Tier 4 (ecosystem / integration: HA-MQTT bridge,
> formal REST API, plugin API, generic HTTP widget) becomes
> post-1.0 work, prioritised by community demand.

### Highlights of the road to 1.0

The beta cycle delivered, across ~50 tagged releases:

- **Setup polish** — installer with auto-Lively bootstrapper +
  Wallpaper Engine integration + SignalRGB plugin install + tray
  system-status diagnostic + Backup/Restore + first-run tour +
  per-screen Reset + Ctrl+Z undo with 20-entry ring buffer.
- **In-browser configurator + builder** — multi-screen tabs with
  resolution labels, library with hover-preview / pin / drag-reorder /
  right-click menu, monitor-wall workflow, span-canvas-across-monitors,
  crop tool, pattern-fill brushes, Auto-cut tool (Otsu + saliency,
  pure JS, no model download), live RGB glow preview, save-to-library.
- **Twelve ambient effects** — snow, rain, sparks, aurora,
  constellation, fireflies, plasma, vortex, bubbles, matrix,
  starfield, lightning. All written from scratch in the project's
  own `AMBIENT_PRESETS` shape, no per-pen licence verification
  needed. Optional glow-colour tinting on every preset.
- **Whole-screen audio-reactive glow layer** — Pulse / Spectrum /
  Waveform modes driving off the SignalRGB FFT bins.
- **Eleven+ widgets** with drag-and-resize layout — clock,
  calendar, weather (Open-Meteo), sticky notes, countdowns, photo
  frame, quote pool, CPU / RAM / GPU / drive / fan / hardware-sensor
  meters (LibreHardwareMonitor optional), audio spectrum, Now-playing
  (Windows SMTC).
- **Automation** — wallpaper auto-cycle with configurable interval /
  pool / order, global preset hotkeys (Ctrl+Shift+1..4), per-app /
  per-game profiles via foreground-window watcher.
- **Multi-monitor** — up to 4 screens, each independent or mirrored
  to any other; ultrawide-friendly aspect ratios (Auto / 16:9 /
  21:9 / 32:9 / 9:16 / Custom).
- **Auto-update** — tray "Download + install update" via
  `ShellExecuteW` plus Inno's `CloseApplications=force`;
  bulletproof after the v0.9.17 + v0.9.19 fix arc.
- **DE / EN localisation** across Configurator, Builder, About, Help,
  installer.
- **Winget submission** — manifest scaffolding in `installer/winget/`
  with maintainer helper script; first submission opened against
  `microsoft/winget-pkgs` for v0.9.21. v1.0.0 manifest follows once
  the v0.9.21 PR merges.

### Compatibility

- Bridge binary, plugin file format, WebSocket protocol, and
  wallpaper-bundle structure are all considered **stable surface**
  going forward. v1.x updates preserve compatibility; breaking
  changes wait for v2.0.
- Existing v0.9.x installations auto-update to v1.0.0 via the
  tray (the v0.9.19+ ShellExecuteW path).
- Lively / Wallpaper Engine bundles need a re-import on the first
  v1.x install since the cache extracts the zip once and doesn't
  notice version changes — same gotcha as every beta release with
  wallpaper-JS changes. Tray → Advanced → *Reload wallpaper pages*
  helps for in-place HTML reloads but not for new effects.

### Why now

Every meaningful UX surface is shipped, the auto-update path is
finally bulletproof, the licence story (MIT + permissive deps + no
non-commercial defaults) is clean, the Workshop submission is live,
the Winget package is in moderator review, and the maintainer has
been running it daily on his own machines for the last weeks
without surfacing anything that screams "still beta". Dropping the
suffix.

## [0.9.21-beta] - 2026-05-23

> Closes out the remaining Tier 3 roadmap items: a third batch of
> ambient effects + initial Winget manifest scaffolding so the
> upcoming `winget install Delido.SignalRGBWallpaper` flow has
> something concrete to ship.

### Added — Ambient effects, batch 3

Twelve presets now in the Configurator → Effects picker. Three new
visually-distinct effects, all written from scratch in the
`AMBIENT_PRESETS` shape (no copied code, no per-pen licence
verification needed):

- **Matrix** — falling vertical streams of katakana + digits +
  symbols, classic green-on-black "digital rain". Each column owns
  its length / speed / character buffer and periodically swaps a
  random glyph for the flicker. Tint mode replaces the green palette
  with the user's glow colour while keeping the head row bright
  white so the leading edge of each stream still reads against any
  background.
- **Starfield** — particles distributed in normalised polar space
  at varying z-depth; each frame z shrinks (zoom toward viewer),
  projection puts them at increasing screen radius from the centre
  with a short streak trail. The trail is the trick that sells the
  hyperspace illusion. cx / cy baked at spawn so the projection
  stays stable through the few seconds an average star lives.
- **Lightning** — brief flashing branched arcs via midpoint
  displacement (start + end + 4 subdivisions = jagged 17-point
  polyline; branch jitter shrinks with depth so the macro shape
  stays close to a straight bolt while micro-segments wobble).
  Two-phase envelope: hot flash for the first ~70 ms, then
  squared-fade tail for a real-arc-afterglow look.
  `ctx.shadowBlur` halo gives the bolt its glow, reset per draw
  so it doesn't leak into other presets.

Configurator gains matching mini-preview tiles for all three so the
picker reads at a glance.

### Added — Winget manifest scaffolding

- New `installer/winget/` directory with the three-file v1.6 manifest
  format for submission to
  [`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs):
  - `Delido.SignalRGBWallpaper.yaml` — version manifest
  - `Delido.SignalRGBWallpaper.installer.yaml` — installer URL +
    SHA256 (per-release update)
  - `Delido.SignalRGBWallpaper.locale.en-US.yaml` — metadata
    (description, tags, URLs)
- `installer/winget/README.md` documents the per-release update
  workflow + `wingetcreate submit` invocation. Status note: the
  scaffolding is in-tree as of v0.9.21; the actual first-time PR to
  `microsoft/winget-pkgs` is still a maintainer-todo since it
  requires a manual review round with the Winget moderators.

## [0.9.20-beta] - 2026-05-23

> **Drops the lazy-loaded ONNX default model entirely.** After three
> attempts at finding a stable, single-file, permissively-licensed
> hosted model (RMBG-1.4 → Xenova/u2netp → rembg/v0.0.0/u2netp.onnx),
> all of which failed in different ways (non-commercial licence,
> external-data split, fetch-blocked), v0.9.20 walks the whole
> external-fetch path back to **pure-JavaScript algorithms running
> on the canvas**. Faster, offline, no licence concerns.

### Changed — Builder Auto-cut

- **New default mode: "Auto saliency (instant)"** — frequency-tuned
  saliency *(Achanta et al. 2009, public-domain algorithm)*. For
  each pixel: Euclidean colour distance from the image's mean RGB
  plus a brightness premium; adaptive threshold. Strong on the
  "neon panels / UI overlays / glowing edges" wallpaper case
  because those regions are precisely where the colour deviates
  most from the image's overall palette.
- **"Brightness (Otsu)" stays** as the second mode for cases where
  pure-brightness thresholding fits better (e.g. uniform-coloured
  panels on a dark backdrop).
- **Both modes run in tens of milliseconds**, fully offline, no
  network, no licence considerations.
- **"Custom ONNX model" mode** is now hidden by default. Users who
  want it can opt in via `localStorage["builder.aiEnabled"] = "1"`
  or by setting a URL in `localStorage["builder.aiModelUrl"]`.
  The ORT loader stays in the codebase for that path.

### Docs

- `docs/credits.md` audit refreshed: ORT moved to opt-in section,
  RMBG / U²-Netp default-URL discussion replaced with the pure-JS
  algorithm credits (Achanta-2009 saliency + Otsu-1979).
- The earlier v0.9.18 + v0.9.19 betas are **kept** in Releases this
  time around (no yank) — v0.9.18's licence-clean Apache 2.0
  intent was correct, just had the wrong delivery mechanism;
  v0.9.19 fixed the auto-update path that all later releases
  depend on.

## [0.9.19-beta] - 2026-05-23

> Two real-world bugs from v0.9.18: the new Apache 2.0 default AI
> model URL pointed at a multi-file Hugging Face host that ORT
> couldn't auto-resolve, and the tray auto-update STILL aborted
> silently because Inno's `CloseApplications=yes` deadlocks under
> `/SUPPRESSMSGBOXES`. Both fixed.

### Fixed — Builder Auto-cut

- **AI default URL now points at the long-standing single-file
  rembg release asset** for U²-Netp (Apache 2.0) instead of
  `huggingface.co/Xenova/u2netp`. The HF Xenova host splits the
  model graph (`model.onnx`) from the weights (`model.onnx_data`),
  and `onnxruntime-web` doesn't auto-resolve the second file —
  hence the *"failed to load external data file"* error in v0.9.18.
  The rembg URL is a single self-contained `.onnx` so one fetch
  is enough. Same Apache 2.0 licence.
- `localStorage["builder.aiModelUrl"]` override still works for
  any user wanting a different model.

### Fixed — Tray auto-update

- **`CloseApplications=yes` → `force`** in the Inno script.
  `yes` shows a confirm dialog asking the user whether to close
  the running bridge before install. With `/SUPPRESSMSGBOXES` (set
  by the silent-update path) that dialog is killed before it
  renders, leaving the installer waiting on user input that will
  never come and eventually aborting. `force` skips the prompt
  and closes the bridge unconditionally before overwriting
  `SignalRGBBridge.exe`. This is the missing piece behind the
  "starts a window briefly then everything closes" symptom from
  v0.9.17 + v0.9.18.

## [0.9.18-beta] - 2026-05-23

> Licence-cleanup release: swaps the AI cut-out default model from
> RMBG-1.4 (BRIA, non-commercial) to U²-Netp (Apache 2.0). Commercial
> wallpaper / streaming / studio users no longer get steered into a
> paid-licence dependency just by clicking *AI saliency*.
>
> The v0.9.16 + v0.9.17 release tags were yanked from GitHub
> Releases for the same reason; users on those builds should either
> wait for their tray auto-update to pick this version up, or
> manually download the v0.9.18 installer from the latest release.

### Changed — Builder Auto-cut

- **Default model: U²-Netp (Apache 2.0)** at 320×320 input —
  permissive licence, free for any use including commercial.
  Replaces the v0.9.16 / v0.9.17 default which was RMBG-1.4
  (BRIA RMBG v1.4 License v1.0, non-commercial only).
- The user-facing workflow is identical: pick *AI saliency*,
  click *Run*, get a salient-region mask. The model is smaller
  (4 MB vs ~44 MB), inference is faster, and there's no licence
  trap waiting for commercial users.
- `localStorage["builder.aiModelUrl"]` + `["builder.aiInputSize"]`
  overrides still work if a user wants to point at a different
  model. Otsu mode is the default-selected option in the picker
  and uses no model / network at all.

### Docs

- `docs/credits.md` updated: U²-Netp attribution added, RMBG-1.4
  warning removed (no longer the default), audit date bumped to
  v0.9.18.
- README + roadmap re-aligned to the v0.9.x cycle reality (Tier
  1 + 2 shipped, Builder Auto-cut shipped, the Builder Wall
  workflow shipped). Outdated v0.8.0-first-stable language
  replaced.

## [0.9.17-beta] - 2026-05-23

> Bug-fix release for v0.9.16's Auto cut tool + the long-standing
> tray-side auto-update flow. Three concrete issues from real-world
> use.

### Fixed — Builder Auto cut

- **AI mode dimension mismatch.** Default model is RMBG-1.4 which
  expects 1024×1024 inputs; the v0.9.16 code fed 320×320 and the
  ORT session bailed with "Got invalid dimensions for input". Now
  feeds the model at its native resolution (1024×1024) and exposes
  both the URL and the input size via `localStorage` so users can
  bring their own model:
  - `localStorage["builder.aiModelUrl"]` — full model URL
  - `localStorage["builder.aiInputSize"]` — input H = W (1-2048)
- **Undo button stayed disabled** after an Auto-cut. `runAiCutout`
  was missing the `updateHistory()` call that every other operation
  makes, so the history sidebar didn't refresh and Ctrl+Z / the
  Rückgängig button stayed greyed out. The op was already in the
  clicks array — only the UI was wrong; existing v0.9.16 sessions
  can recover by adding any other edit (which triggers
  updateHistory) then Ctrl+Z'ing twice.
- Dropped the ImageNet-style mean/std normalisation since RMBG-1.4
  and the usual U²-Net exports both want raw [0,1] floats; the
  Threshold slider absorbs any residual per-channel offset.

### Fixed — Tray auto-update

- **Installer never visibly started after download.** The
  `subprocess.Popen(..., creationflags=DETACHED_PROCESS)` path was
  reportedly silently failing on some Windows / SmartScreen setups,
  leaving the user with a closed bridge and no install. Switched
  to `ShellExecuteW` via ctypes — goes through the user shell,
  SmartScreen gets the right provenance context, and the child is
  a fully independent process from instruction zero. Subprocess
  fallback retained if the API call fails.
- **`/VERYSILENT` → `/SILENT`** so the Inno-Setup progress bar is
  visible during install. The user gets immediate confirmation
  the install is really running, and any Inno error dialog is
  shown instead of swallowed.
- **Sleep before `os._exit` bumped 1.5 s → 3.0 s** so AV real-time
  scan of the just-downloaded exe has time to complete before the
  parent dies.
- Each step now writes to `%TEMP%/signalrgb-update.log` so future
  failures are diagnosable post-mortem.

## [0.9.16-beta] - 2026-05-23

> New Builder tool: **Auto cut**. One click detects the brightest /
> most salient regions of the loaded image and cuts them transparent —
> the typical "I want neon panels to glow with RGB" wallpaper workflow
> done in a single action instead of dozens of manual clicks.

### Added — Builder

- **Auto cut tool** (✨ icon in the toolbox). Two modes share the same
  storage + replay path so undo / redo / refine-with-brushes work
  like any other operation:
  - **Otsu (instant)** — computes the optimal brightness threshold
    via Otsu's method on a luma histogram of the canvas, then cuts
    every above-threshold pixel. No internet, no model, no WASM —
    runs synchronously on the main thread, finishes before the
    spinner can show. Genuinely good for neon / UI / sci-fi
    panel imagery where the cut signal is brightness.
  - **AI saliency (downloads ~7 MB)** — lazy-loads `onnxruntime-web`
    from jsDelivr and a U²-Netp saliency model from Hugging Face
    the first time the user clicks Run; both are browser-cached
    afterward so subsequent runs are local. Inference runs at
    320×320; the output is nearest-neighbour upsampled to canvas
    resolution at draw time.
- **Threshold slider** biases the mask cutoff ±25 % so the user can
  soften / aggress the cut without re-running the model.
- **Invert toggle** flips the mask before applying — useful when the
  saliency net picks the *subject* but the user wants the
  *background* cut instead.
- Auto-cut operations show up in the History panel like any other
  click (purple swatch · mask dimensions · invert flag) and rotate
  correctly with the *Rotate 90°* button.

### Notes

- The U²-Netp model URL can be overridden via
  `localStorage["builder.aiModelUrl"]` for users behind a CDN
  block / on a corporate mirror.
- AI mode needs internet on first use only. After the first
  successful run, the browser cache holds both the runtime and
  the model so the tool works offline.

## [0.9.15-beta] - 2026-05-23

> Second wave of ambient effects — three new presets to keep the
> Effects picker filling out. All written from scratch in the
> `AMBIENT_PRESETS` shape introduced by v0.9.12, so no per-pen
> licence verification is needed.

### Added — Ambient effects

- **Plasma** — soft full-canvas hue-cycling blobs, lava-lamp style.
  Each blob owns its hue clock so the colour wash is always
  shifting. Distinct from `aurora` (which is confined to a
  horizontal band). When *Tint* is on, drops the hue cycle and
  runs the user's glow colour so the effect stays on-palette.
- **Vortex** — particles spawn near the canvas edge and spiral
  inward toward the centre with rising angular velocity, despawning
  once they get close enough; new ones replace them at the
  perimeter. Polar-coords internally so the spiral feels stable
  on resize. Tinted variant uses the glow colour as the particle
  body.
- **Bubbles** — hollow-rim circles rising from the bottom with a
  slight horizontal wobble, growing slightly as they rise.
  Stroked rather than filled so the background image stays
  visible inside each bubble; the small specular highlight on
  the upper-left adds depth.

Configurator's effect picker gains matching tile previews so the
preset card looks right at first glance instead of needing the
wallpaper page to be visible to judge the effect.

## [0.9.14-beta] - 2026-05-23

> Builder right-panel rework — fixes the workflow-order + visual-feedback
> issues that surfaced once Span Canvas landed in v0.9.13. Source comes
> first, Wall sits second as the climax of the flow, Output is last; the
> Merge subsection collapses out of the way until it's actually needed.

### Changed — Builder right panel

- **Reordered**: Source (Load) → Monitor Wall → Output. Earlier
  layout had Wall on top but the user always has to load / merge
  *first*, so the eye was jumping bottom-to-top.
- **Merge subsection is collapsed by default.** Two-image and 2×2
  merge controls now live behind a `<details><summary>` so the
  single-image happy path doesn't have to scroll past four file-pick
  slots. The summary line tells you the section exists; clicking
  expands it inline.
- **Wall action hierarchy**: "Wand anwenden" is now a full-width,
  taller primary button. Span Canvas + Clear sit in a secondary row
  underneath so the climax of the flow is unambiguous.
- **Clear button now disables itself** when there's nothing staged
  (prevents the dead-click that previously left `wall-stat` empty).
- **Staged-ready hint** ("2/2 Bildschirme bereit — „Wand anwenden"
  überträgt.") replaces the Span-suggestion banner the moment any
  slot is filled. Earlier UI kept showing "versuche Canvas spannen"
  even after the user had just clicked it, which contradicted the
  apply-success status one line below.

## [0.9.13-beta] - 2026-05-22

> Closes the Builder merge ↔ Monitor Wall workflow gap (one-click
> span across monitors) and adds a tray-side hot-reload path so the
> next time wallpaper-page JS ships in a beta, users don't have to
> re-import the Lively/WE bundle from scratch.

### Added — Builder

- **⇔ Span canvas across monitors.** New button in the Monitor Wall
  toolbar. Slices the current canvas into one chunk per screen,
  sized proportionally to each screen's physical width, and stages
  every Wall frame in a single click. Fits the *merge two photos
  side-by-side → 7680×2160 → spread across both 2560×1440
  monitors* flow that previously needed manual cropping +
  per-frame canvas grabs.
- **Span-suggestion hint** under the Wall canvas. Lights up
  whenever the loaded canvas's aspect ratio is within 5 % of the
  wall's combined aspect (sum of screen widths over common
  height), so the user spots the shortcut without reading the
  toolbar.
- Span button enables only when (a) a canvas is loaded and (b)
  there are 2+ active screens; tracked via the new
  `updateWallSpanState` helper that runs on canvas changes and
  Apply Wall state ticks.

### Added — Tray / Bridge

- **"Reload wallpaper pages"** entry under tray → *Advanced*.
  Bridge pushes `{type: "reload"}` over the WS to every connected
  wallpaper page (configurator clients explicitly excluded so an
  open settings tab doesn't get yanked). The wallpaper page handles
  the new frame by calling `location.reload()`. Lets future
  cosmetic / widget updates land without manually re-importing
  the Lively / WE bundle for each release.
  - Caveat: the listener has to ship in the *previous* installed
    version. Wallpapers running from a pre-v0.9.13 bundle still
    need the one-time manual re-import after upgrade; from
    v0.9.13 onward the tray button does it.

## [0.9.12-beta] - 2026-05-22

> Two new ambient effects in the spirit of the planned CodePen ports
> from the roadmap. Implementations written from scratch to fit our
> existing `AMBIENT_PRESETS` shape (no third-party code carried in),
> so there's no per-pen licence verification to track.

### Added — Ambient effects

- **Constellation** — particles drift across the canvas; thin lines
  appear between any two particles within a fade radius. Inspired
  by the classic *connect-the-dots* effect (ykob/aBrjaR style).
  Triggered the addition of an optional `def.after(ctx, particles,
  tint)` post-pass hook to the ambient renderer so effects can draw
  across the whole particle set instead of one-at-a-time. Existing
  presets are untouched (no `after` defined → no-op).
- **Fireflies** — slow-drifting glow dots that pulse on their own
  per-particle phase clocks (yellow-green band by default; *Tint
  with the live glow colour* overrides). Pre-tinted variant lands
  nicely on dark backgrounds.

Both presets appear in the Configurator's *Ambient preset* tile
grid with the same mini-canvas preview the existing effects have.

## [0.9.11-beta] - 2026-05-22

> Builder Monitor Wall is now the **primary right-panel navigation**.
> Each tile pre-fills with its screen's current wallpaper and opens a
> compact action menu on click; the old *Apply to Screen N* and
> *Multi-monitor split* sections fold into it via *Use current canvas*.

### Changed — Builder right panel

- **Monitor Wall promoted to the top.** Was buried below *Apply* /
  *Split*; the new order puts it first, matching how multi-monitor
  workflows actually flow (pick layout → drop image per monitor →
  Apply).
- **Each frame pre-fills with the screen's current `bgImage`** via
  the `/image?path=` proxy. Live snapshot of the desktop instead of
  an empty box. Hover shows "Click to change" hint.
- **Bigger frames** sized for primary-nav use (130 px wide in
  horizontal mode, 150 px in 2×2 / free, 220 px in vertical).
- **Per-frame click menu** replaces the old single-button row:
  - 📁 **Choose file…** — system file picker
  - 📚 **From library…** — same Library dialog *Open from library*
    uses
  - 🖼️ **Use current canvas** — snapshots the Builder's canvas
    (with all in-progress mask edits) into the slot. Replaces the
    old *Apply to Screen N* buttons.
  - ✕ **Clear** — drops any staged image, frame reverts to current
    wallpaper preview.
  Menu positions below the clicked frame, clamps to viewport, and
  Esc / click-outside dismiss.
- **Apply Wall re-loads `/config` after success** so each frame
  paints the just-applied background (the bridge stamps a new
  timestamped filename so the proxy bypasses CEF caches).
- **Loaded slot** now wears a soft green glow ring so staged-but-
  not-yet-applied tiles read at a glance.

### Removed

- **"Apply to screen N" section** — folded into the Wall via the
  *Use current canvas* menu action.
- **"Multi-monitor split" section** — replaced by the Wall's
  horizontal layout. Split-the-canvas-and-send-each-half workflow
  is now: Wall with horizontal layout → *Use current canvas* on
  the left tile → crop canvas to right half → *Use current canvas*
  on the right tile → *Apply Wall*. Fewer one-shot buttons, one
  workflow.

The two legacy section names (`section.apply`, `section.split`)
remain in the i18n table for backwards compat but are no longer
referenced by any DOM.

## [0.9.10-beta] - 2026-05-22

> **Tier 1 setup-polish slice complete.** Adds the two remaining
> items — Ctrl+Z undo and the first-run onboarding tour — and
> trims the roadmap of two items that didn't pan out.

### Added — Configurator

- **Ctrl+Z undo / Ctrl+Y (or Ctrl+Shift+Z) redo** for the last 20
  setting changes per screen. Per-screen ring buffer captured in
  `setSetting` before each write; redo stack invalidates on the
  next manual edit (linear-history model — same as every editor's
  undo). Toast on each apply tells the user which key was
  reverted. Doesn't cover widget add/remove/move, presets,
  mirror, or cycle — those have their own scoped reversal flows.
  Reset-this-screen wipes both rings since the prior entries
  would revert to fields that no longer exist.
- **First-run onboarding tour.** Fires on first WS settings push
  when `localStorage.signalrgb.tour_seen` is absent. Seven steps:
  *Welcome → Tabs → Overview card → Background → Presets →
  Builder → Done*, each with a spotlight ring + floating tooltip
  pointed at the live DOM element being explained. Skip / Esc /
  overlay click all dismiss; the *Tour* button in the header
  re-fires it on demand.

### Removed (roadmap cleanup)

- **Mobile Configurator view** — niche, would have needed a LAN-
  bind opt-in with security ergonomics. Most users sit at the PC
  the wallpaper runs on. Marked 🅿️ parked.
- **Community wallpaper gallery** — high copyright-infringement
  risk (unfiltered user uploads of brand IP, anime stills, game
  art etc.). Moderating a public submission flow would dwarf the
  curation value. Marked 🅿️ parked. Bundled starter library +
  per-user upload remain the supported path.

## [0.9.9-beta] - 2026-05-22

> Quick fix for the Monitor Wall *Horizontal row* mode rendering as
> a vertical stack on narrow right-panel widths.

### Fixed

- **Monitor Wall: horizontal layout now scrolls horizontally** instead
  of wrapping to a column. Previously `flex-wrap: wrap` on the
  wall canvas plus 260 px right-panel width meant two ~130 px
  frames + gap exceeded the available room → second frame wrapped
  to the next line. New rule pins horizontal mode to
  `flex-wrap: nowrap; overflow-x: auto` so the row stays a row
  and the strip scrolls when it doesn't fit. The 2×2 + vertical
  layouts keep their existing wrap behaviour.

> Roadmap: added a planned **Monitor-Wall-as-primary-right-panel-nav**
> redesign for an upcoming release — promotes the Wall to the top
> of the right panel, pre-fills each frame with the screen's current
> background, adds a per-frame click menu, and collapses the now-
> redundant *Apply to Screen N* + *Multi-monitor split* sections.

## [0.9.8-beta] - 2026-05-22

> First Tier-3 item: **one-click update install**. The tray no longer
> just links you to the release page — it downloads the new installer
> and runs it silently while the old bridge bows out, then the new
> bridge auto-restarts.

### Added — Tray

- **"⬇ Download + install {tag}"** entry at the top of the tray menu,
  shown whenever an update is pending and the release ships an
  installer asset (i.e. every official build). The existing
  "open release page" entry stays for users who want to read
  release notes first.
- **Tk progress window** during download — shows percentage and
  bytes-done / bytes-total. Doesn't auto-close; the process exits
  when the installer takes over.

### Added — UpdateChecker

- **Asset URL capture** during the daily release-poll: scans
  `assets[]` for the canonical `SignalRGBWallpaperSetup*.exe` name
  and stores the direct download URL + content-length alongside the
  release tag.
- **`download_and_install(on_progress, on_done)`** — streams the
  installer into `%TEMP%`, spawns it with
  `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` (detached + own process
  group), waits 1.5 s for the installer to grab its handles, then
  `os._exit(0)` so it can replace `SignalRGBBridge.exe` in place.

### Changed — Installer

- **Dropped `skipifsilent`** from the bridge auto-launch `[Run]`
  entry. In silent mode (used by the new tray flow) the bridge
  now auto-restarts after install; in interactive mode the
  `postinstall` checkbox still gates user opt-in.

## [0.9.7-beta] - 2026-05-22

> Two follow-ups to v0.9.6: keyboard input still didn't reach the
> in-page prompt under Lively/WE (fundamental CEF wallpaper-window
> limitation, not a 0.9.6 regression), and the Quote widget's
> `api.quotable.io` source has been dead since mid-2024.

### Fixed

- **Widget gear icons now open the Configurator** in a new tab
  instead of an in-page modal. Lively/WE forward mouse events to
  wallpaper pages (so the gear click worked) but **keyboard events
  go to whichever window has OS focus** — the wallpaper is never
  the foreground window, so typed characters never reached the
  in-page input. The 0.9.6 wpPrompt overlay looked right but
  silently dropped keystrokes.
  - Each built-in widget's `editOptions` now points at a single
    `openWidgetInConfigurator(rec)` that does
    `window.open("/configurator?editWidget=<id>&editScreen=<n>")`.
  - **Configurator** parses those query params on load, switches
    to the matching screen tab, and opens the existing options
    modal for that widget id once the WS settings push arrives.
    Query params are stripped from the URL on first read so a
    hard reload doesn't re-fire the modal.
- **Quote widget — bundled local quote list.** `api.quotable.io` has
  been DNS-dead since mid-2024 (every fetch errored, every Quote
  widget rendered "couldn't fetch a quote"). Now ships with 50
  curated public-domain quotes (Einstein / Twain / Tolkien / da
  Vinci / Linus / Knuth / Dijkstra / …). No external HTTP call —
  works under WE's CEF block on outgoing fetch too. Per-tick
  refresh logic still picks a fresh entry per day. *via Quotable*
  footer removed.

## [0.9.6-beta] - 2026-05-22

> Hotfix for widget gear-icon dialogs freezing the wallpaper page.

### Fixed

- **Widget edit-options dialogs froze the page** when the user
  clicked a widget's gear icon. Built-in `window.prompt()` /
  `alert()` calls block the JavaScript thread and, under
  Lively/WE's CEF, occasionally render the dialog behind the
  wallpaper or fail to dismiss — locking the entire page.
- **`wpPrompt(label, default) → Promise<string|null>`** and
  **`wpAlert(message) → Promise<void>`** — in-page replacements
  rendered as a small DOM overlay (HTML inputs + OK/Cancel
  buttons) styled to match the wallpaper UI. Enter / Esc /
  click-outside dismiss; resolves with the entered value or
  `null` on cancel.
- All built-in widgets (clock, calendar, weather, sticky note,
  countdown, picture frame) converted to **async `editOptions`**
  using the new helpers. Their gear icons now open an in-page
  modal instead of the browser's native prompt.
- Click handler for the gear icon learned to `.catch` the
  returned Promise so async rejections surface in the console
  instead of dropping silently.

## [0.9.5-beta] - 2026-05-22

> Fourth and final Tier-2 high-visibility feature: **per-app / per-game
> profiles**. When a matching `.exe` is in the foreground, the bridge
> auto-applies a preset slot; reverts cleanly when the foreground
> changes away. Pro-tier USP against ordinary wallpaper tools.

### Added — Bridge

- **`ProfileWatcher`** — 1 Hz foreground-window poller. Reads the
  active window via Win32 `GetForegroundWindow` →
  `QueryFullProcessImageNameW`, extracts the basename, and matches
  it (case-insensitive) against the user-configured `config.profiles`
  rule list.
- **Activation snapshot** — on first match, the watcher snapshots
  every target screen's current settings before applying the rule's
  preset. On deactivation (foreground exe no longer matches any
  enabled rule), the snapshot is restored via `PRESET_SNAPSHOT_KEYS`
  so only the preset-relevant fields revert — the user's mirror
  setup, viewport, etc. stay intact.
- **One active rule at a time** — when the foreground switches from
  rule A's exe to rule B's exe, A reverts first (with A's snapshot)
  before B activates (with a fresh snapshot of the now-current
  state).
- **Rule CRUD** — `add_profile` / `update_profile` / `remove_profile`,
  routed via new `profile-add` / `profile-update` / `profile-remove`
  WS commands. Each mutation persists `config.json` and re-pushes
  every screen's settings so other open Configurator tabs sync.
- **Mirror-aware**: the watcher relies on `apply_preset` which is
  blocked on mirrors via `_block_if_mirror`; the source screen's
  preset apply propagates to mirrors through the existing
  `_replicate_to_mirrors` path.

### Added — Configurator

- **Per-app profiles card** at the bottom of the main column,
  collapsed by default. Each rule row carries:
  - Enable checkbox
  - Exe field (e.g. `cyberpunk2077.exe`, case-insensitive)
  - Optional human-readable label
  - Target screen — *All screens* or a specific tab
  - Preset slot (1..4)
  - Delete button (with confirm)
- **Add rule…** button appends a default-shaped rule
  (`example.exe`, all screens, slot 1) that the user then edits in
  place.
- **Live sync** — the `profiles` list rides alongside `data` in
  every settings push, so two open Configurator tabs stay in sync.

## [0.9.4-beta] - 2026-05-22

> Third Tier-2 high-visibility feature: **now-playing widget**. Reads
> Windows' SystemMediaTransportControls so the title + artist of
> whatever the user is listening to (Spotify, Groove, browser HTML5
> audio, Edge, anything that publishes SMTC) shows up on the
> wallpaper.

### Added — Bridge

- **`NowPlayingPoller`** — dedicated asyncio-loop thread polls
  `GlobalSystemMediaTransportControlsSessionManager.request_async`
  every second, captures the current session's media properties
  (title / artist / album), playback status, and timeline
  (position / duration). Snapshot is merged into `SysStatsPoller`'s
  payload as `nowPlaying` so the wallpaper page gets the data
  through the existing 1 Hz WS push.
- **`winrt-Windows.Media.Control`** + `winrt-Windows.Foundation` +
  `winrt-runtime` bundled via PyInstaller `--collect-all winrt`.
  When the package isn't present (older Python or build skipped
  the dep), the poller logs a notice and stays a no-op so the rest
  of the bridge keeps running.

### Added — Widget catalog

- **`now-playing`** widget type registered in three places: bridge
  `WIDGET_DEFAULTS`, configurator `WIDGET_CATALOG`, wallpaper
  `WIDGET_REGISTRY`. Options:
  - *Show progress bar* (thin bar across the bottom, animates with
    track position).
  - *Show artist line* (second line under the title).
  - *Tint with glow colour* (progress bar borrows the live tint).
- **Auto-hide** when no media session is active: title fades to "—"
  with reduced opacity instead of leaving an empty widget in the
  layout. Playback paused → title dims to 55 % opacity as a
  visual hint.

## [0.9.3-beta] - 2026-05-22

> Second Tier-2 high-visibility feature: **global preset hotkeys**.
> `Ctrl+Shift+1..4` applies the matching preset slot on every active
> screen at once — full desktop look swap in a single keystroke.

### Added

- **`HotkeyListener`** background thread on the bridge — registers
  `Ctrl+Shift+1`, `Ctrl+Shift+2`, `Ctrl+Shift+3`, `Ctrl+Shift+4`
  via Win32 `RegisterHotKey` on its own thread, pumps GetMessage,
  and on WM_HOTKEY fires `apply_preset` on every active screen for
  the matching slot. Mirrors are skipped by the existing
  `_block_if_mirror` guard, so they update via replication from
  their source instead of locally.
- **Tray toggle** under *Advanced → Preset hotkeys (Ctrl+Shift+1..4)*.
  Checkmark reflects the live state. Off by default so we don't
  grab shortcuts the user might have wired up elsewhere — flip it
  on once and it persists across restarts via
  `config.presetHotkeysEnabled`.
- **Graceful unregister** on toggle off: `Stop()` posts WM_QUIT to
  the listener thread which unregisters all hotkeys before
  returning, so other apps can reclaim the shortcuts cleanly.

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
